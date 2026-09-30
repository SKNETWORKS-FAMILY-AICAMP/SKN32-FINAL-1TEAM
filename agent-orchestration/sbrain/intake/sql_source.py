"""웹 DB(공유 MySQL)에서 사전 정보 입력을 읽는다 — SQLAlchemy Core.

- 테이블 구조는 처음 읽을 때 DB에서 가져오고(reflection), 필요한 컬럼이 없으면 SchemaMismatch를 올린다.
  기본키 이름을 몰라도 저장 순서(기본키 순)로 읽을 수 있다.
- 필요한 컬럼만 SELECT 한다. 웹 쪽에 컬럼이 늘어도 영향이 없다.
- 테이블 · 컬럼 이름은 웹 스키마(app_schema.sql, 저장소 미포함)와 맞췄다 (2026-09-30 확인).
  기본키는 companies.company_id · projects.project_id · team_members.member_id ·
  pricing_items.pricing_id · project_plan_inputs.input_id이다.
- 접속 예: create_engine("mysql+pymysql://user:pw@host:3306/db") — 접속 정보는 코드에 넣지 않는다.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, fields

from sqlalchemy import Engine, MetaData, Table, select
from sqlalchemy.exc import NoSuchTableError

from .record import (
    CompanyRow, PlanInputRow, PricingItemRow, ProjectInputRecord, ProjectRow, TeamMemberRow,
)


@dataclass(frozen=True)
class WebDbTables:
    """웹 DB 테이블 이름 (app_schema.sql)."""
    companies: str = "companies"
    projects: str = "projects"
    team_members: str = "team_members"
    pricing_items: str = "pricing_items"
    plan_inputs: str = "project_plan_inputs"


# 테이블별로 읽는 컬럼 (행 모델의 필드 + 조인 키)
COLUMNS: dict[str, list[str]] = {
    "companies": list(CompanyRow.model_fields),
    "projects": list(ProjectRow.model_fields),
    "team_members": ["project_id", *TeamMemberRow.model_fields],
    "pricing_items": ["project_id", *PricingItemRow.model_fields],
    "plan_inputs": ["project_id", *PlanInputRow.model_fields],
}


class SchemaMismatch(RuntimeError):
    """웹 DB에 필요한 테이블 · 컬럼이 없음."""


class SqlProjectInputSource:
    def __init__(self, engine: Engine, tables: WebDbTables | None = None) -> None:
        self._engine = engine
        self._names = tables or WebDbTables()
        self._tables: dict[str, Table] | None = None
        self._lock = threading.Lock()

    def load(self, project_id: int | str) -> ProjectInputRecord | None:
        t = self._reflect()
        with self._engine.connect() as conn:
            project = conn.execute(
                self._select(t, "projects").where(t["projects"].c.project_id == project_id)
            ).mappings().first()
            if project is None or project["archived_at"] is not None:
                return None
            company = conn.execute(
                self._select(t, "companies").where(t["companies"].c.company_id == project["company_id"])
            ).mappings().first()
            if company is None:
                return None
            pid = project["project_id"]
            team = conn.execute(self._children(t, "team_members", pid)).mappings().all()
            prices = conn.execute(self._children(t, "pricing_items", pid)).mappings().all()
            plan = conn.execute(self._children(t, "plan_inputs", pid)).mappings().first()
        return ProjectInputRecord(
            project=ProjectRow.model_validate(dict(project)),
            company=CompanyRow.model_validate(dict(company)),
            team_members=[TeamMemberRow.model_validate(dict(r)) for r in team],
            pricing_items=[PricingItemRow.model_validate(dict(r)) for r in prices],
            plan_input=PlanInputRow.model_validate(dict(plan)) if plan is not None else None,
        )

    # ── 내부 ─────────────────────────────────────────
    def _reflect(self) -> dict[str, Table]:
        with self._lock:
            if self._tables is None:
                meta, tables, problems = MetaData(), {}, []
                for f in fields(self._names):
                    name = getattr(self._names, f.name)
                    try:
                        table = Table(name, meta, autoload_with=self._engine)
                    except NoSuchTableError:  # 접속 오류 등은 그대로 올린다
                        problems.append(f"{name}: 테이블 없음")
                        continue
                    lacking = [c for c in COLUMNS[f.name] if c not in table.c]
                    if lacking:
                        problems.append(f"{name}: 컬럼 없음 {lacking}")
                    tables[f.name] = table
                if problems:
                    raise SchemaMismatch("웹 DB 구조가 예상과 다름 — " + "; ".join(problems))
                self._tables = tables
            return self._tables

    @staticmethod
    def _select(t: dict[str, Table], key: str):
        table = t[key]
        return select(*(table.c[c] for c in COLUMNS[key]))

    def _children(self, t: dict[str, Table], key: str, project_id):
        table = t[key]
        return (self._select(t, key)
                .where(table.c.project_id == project_id)
                .order_by(*table.primary_key.columns))
