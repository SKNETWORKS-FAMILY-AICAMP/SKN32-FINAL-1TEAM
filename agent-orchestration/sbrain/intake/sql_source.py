"""웹 DB(공유 MySQL)에서 사전 정보 입력을 읽는다 — SQLAlchemy Core.

- 테이블 구조는 처음 읽을 때 DB에서 가져오고(reflection), 필요한 컬럼이 없으면 SchemaMismatch를 올린다.
  기본키 이름을 몰라도 저장 순서(기본키 순)로 읽을 수 있다.
- 필요한 컬럼만 SELECT 한다. 웹 쪽에 컬럼이 늘어도 영향이 없다.
- 테이블 · 컬럼 이름은 웹 스키마(web/backend/app_schema.sql)와 맞췄다 (2026-09-30 확인).
  기본키는 companies.company_id · projects.project_id · team_members.member_id ·
  pricing_items.pricing_id · project_plan_inputs.input_id이다.
- 사업비 · 일정(project_budget_items · project_schedule_items, spec 4.3)은 item_order 순으로 읽는다.
  project_budget_items.phase는 아직 웹 스키마에 없는 선택 컬럼이라 있으면 읽고 없으면 None이다(OPTIONAL_COLUMNS).
- 웹 테이블은 읽기만 한다.
- 접속 예: create_engine("mysql+pymysql://user:pw@host:3306/db") — 접속 정보는 코드에 넣지 않는다.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, fields

from sqlalchemy import Engine, MetaData, Table, select
from sqlalchemy.exc import NoSuchTableError

from .record import (
    BudgetItemRow, CompanyRow, PlanInputRow, PricingItemRow, ProjectInputRecord, ProjectRow, ScheduleItemRow,
    TeamMemberRow,
)


@dataclass(frozen=True)
class WebDbTables:
    """웹 DB 테이블 이름 (app_schema.sql)."""
    companies: str = "companies"
    projects: str = "projects"
    team_members: str = "team_members"
    pricing_items: str = "pricing_items"
    plan_inputs: str = "project_plan_inputs"
    budget_items: str = "project_budget_items"       # 사업비 집행계획 (spec 4.3)
    schedule_items: str = "project_schedule_items"   # 추진 일정 (spec 4.3)


# 있으면 읽고 없으면 None으로 보는 컬럼 — 없어도 SchemaMismatch가 아니다.
# project_budget_items.phase는 웹이 더하기로 한 컬럼이라 아직 웹 스키마에 없다 (spec 4.3)
OPTIONAL_COLUMNS: dict[str, list[str]] = {
    "budget_items": ["phase"],
}

# item_order 순으로 읽는 테이블 — 빈 순서(NULL)는 뒤, 같은 순서 안은 기본키 순
ITEM_ORDERED = ("budget_items", "schedule_items")

# 테이블별로 꼭 있어야 하는 컬럼 (행 모델의 필드 + 조인 · 정렬 키, 선택 컬럼 제외)
COLUMNS: dict[str, list[str]] = {
    "companies": list(CompanyRow.model_fields),
    "projects": list(ProjectRow.model_fields),
    "team_members": ["project_id", *TeamMemberRow.model_fields],
    "pricing_items": ["project_id", *PricingItemRow.model_fields],
    "plan_inputs": ["project_id", *PlanInputRow.model_fields],
    "budget_items": ["project_id", "item_order",
                     *(f for f in BudgetItemRow.model_fields if f not in OPTIONAL_COLUMNS["budget_items"])],
    "schedule_items": ["project_id", "item_order", *ScheduleItemRow.model_fields],
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
            budgets = conn.execute(self._children(t, "budget_items", pid)).mappings().all()
            schedules = conn.execute(self._children(t, "schedule_items", pid)).mappings().all()
        return ProjectInputRecord(
            project=ProjectRow.model_validate(dict(project)),
            company=CompanyRow.model_validate(dict(company)),
            team_members=[TeamMemberRow.model_validate(dict(r)) for r in team],
            pricing_items=[PricingItemRow.model_validate(dict(r)) for r in prices],
            plan_input=PlanInputRow.model_validate(dict(plan)) if plan is not None else None,
            budget_items=[BudgetItemRow.model_validate(dict(r)) for r in budgets],
            schedule_items=[ScheduleItemRow.model_validate(dict(r)) for r in schedules],
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
        present = [c for c in OPTIONAL_COLUMNS.get(key, []) if c in table.c]   # 없는 선택 컬럼은 행 모델 기본값(None)
        return select(*(table.c[c] for c in [*COLUMNS[key], *present]))

    def _children(self, t: dict[str, Table], key: str, project_id):
        table = t[key]
        order = [table.c.item_order.is_(None), table.c.item_order] if key in ITEM_ORDERED else []
        return (self._select(t, key)
                .where(table.c.project_id == project_id)
                .order_by(*order, *table.primary_key.columns))
