"""테스트용 웹 DB — Orchestrator가 쓰는 웹 테이블의 SQLite 최소 정의와 프로젝트 행 만들기.

컬럼 이름 · 뜻은 웹 스키마(app_schema.sql)와 같고 형식만 SQLite에 맞게 줄였다.
MySQL 통합 테스트는 실제 app_schema.sql을 쓴다(mysqldb.py).

- proofread_logs는 웹 스키마 변경 뒤의 모양(project_id · model_version 있음, plan_id 없어도 됨)이다.
  옛 모양(plan_id NOT NULL, project_id 없음)은 use_old_proofread_logs로 바꿔 시험한다.
- 학습 동의는 projects.company_id → companies.user_id → users.ai_training_agreed로 읽는다.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, Column, DateTime, Engine, Integer, MetaData, Numeric, String, Table, Text, func, insert, select,
    text,
)

META = MetaData()

USERS = Table(
    "users", META,
    Column("user_id", Integer, primary_key=True), Column("email", String(255)),
    Column("ai_training_agreed", Boolean, nullable=False, server_default=text("0")))

COMPANIES = Table(
    "companies", META, Column("company_id", Integer, primary_key=True), Column("user_id", Integer, nullable=False))

PROJECTS = Table(
    "projects", META,
    Column("project_id", Integer, primary_key=True), Column("company_id", Integer),
    Column("description", Text), Column("status", String(20)), Column("stage", String(30)),
    Column("progress_percent", Integer), Column("notice_id", String(320)), Column("failure_reason", Text),
    Column("archived_at", DateTime), Column("created_at", DateTime))

Table("notifications", META,
      Column("notification_id", Integer, primary_key=True), Column("project_id", Integer, nullable=False),
      Column("kind", String(10), nullable=False), Column("failure_scope", String(10)),
      Column("target_step", Integer), Column("channel", String(10), nullable=False, server_default="화면"),
      Column("created_at", DateTime, nullable=False), Column("read_at", DateTime))

Table("generation_failure_alerts", META,
      Column("alert_id", Integer, primary_key=True), Column("project_id", Integer, nullable=False),
      Column("stage", String(30), nullable=False), Column("resume_count", Integer, nullable=False),
      Column("last_error_kind", String(10), nullable=False), Column("failure_reason", Text),
      Column("created_at", DateTime, nullable=False), Column("acknowledged_at", DateTime),
      Column("regenerate_exhausted", Boolean, nullable=False, server_default=text("0")))


def proofread_columns(*, new: bool) -> list[Column]:
    """proofread_logs 컬럼 — new면 웹 스키마 변경 뒤(project_id · model_version, plan_id NULL 허용)."""
    cols = [Column("log_id", Integer, primary_key=True)]
    if new:
        cols.append(Column("project_id", Integer, nullable=False))
    cols += [
        Column("plan_id", Integer, nullable=new),
        Column("section_id", Integer),
        Column("original_text", Text, nullable=False), Column("corrected_text", Text, nullable=False),
        Column("reason", Text), Column("attempt_no", Integer, nullable=False, server_default=text("1")),
        Column("score", Numeric(5, 2), nullable=False, server_default=text("100.00")),
        Column("passed", Boolean, nullable=False, server_default=text("1")),
        Column("violation_note", Text), Column("violation_type", String(20)),
        Column("recovery_status", String(20)), Column("recovery_label", Text),
        Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    ]
    if new:
        cols.append(Column("model_version", String(50)))
    return cols


PROOFREAD_LOGS = Table("proofread_logs", META, *proofread_columns(new=True))
OLD_PROOFREAD_LOGS = Table("proofread_logs", MetaData(), *proofread_columns(new=False))   # 웹 스키마 변경 전

POLICIES = Table(
    "verification_policies", META,
    Column("policy_id", Integer, primary_key=True),
    Column("doc_weight", Numeric(5, 2), nullable=False, server_default=text("70")),
    Column("code_weight", Numeric(5, 2), nullable=False, server_default=text("15")),
    Column("plan_weight", Numeric(5, 2), nullable=False, server_default=text("15")),
    Column("pass_threshold", Numeric(5, 2), nullable=False, server_default=text("80")),
    Column("rerun_cap", Integer, nullable=False, server_default=text("2")),
    Column("rework_cap", Integer, nullable=False, server_default=text("1")),
    Column("deviation_cap", Numeric(5, 2), nullable=False, server_default=text("5")),
    Column("token_retry_cap", Integer, nullable=False, server_default=text("2")),
    Column("regenerate_cap", Integer, nullable=False, server_default=text("2")))

_ids = itertools.count(1001)


def create_web_tables(engine: Engine) -> None:
    META.create_all(engine)


def use_old_proofread_logs(engine: Engine) -> None:
    """SQLite 테스트 DB의 proofread_logs를 웹 스키마 변경 전 모양으로 바꾼다."""
    PROOFREAD_LOGS.drop(engine)
    OLD_PROOFREAD_LOGS.create(engine)


def new_project(engine: Engine, *, agreed: bool = False) -> int:
    """웹 projects 행을 하나 만들고 project_id를 돌려준다. 주인 계정(학습 동의 = agreed) · 회사 행도 만든다."""
    with engine.begin() as conn:
        if engine.dialect.name != "mysql":
            pid = next(_ids)
            uid = conn.execute(insert(USERS).values(email=f"{pid}@test.local", ai_training_agreed=agreed)
                               ).inserted_primary_key[0]
            cid = conn.execute(insert(COMPANIES).values(user_id=uid)).inserted_primary_key[0]
            conn.execute(insert(PROJECTS).values(project_id=pid, company_id=cid, description="테스트",
                                                 created_at=datetime(2026, 9, 26)))
            return pid
        key = uuid.uuid4().hex
        uid = conn.execute(text("INSERT INTO users (email, name, google_sub, ai_training_agreed) "
                                "VALUES (:e, '테스트', :g, :a)"),
                           {"e": f"{key}@test.local", "g": key, "a": agreed}).lastrowid
        cid = conn.execute(text("INSERT INTO companies (user_id, applicant_type) VALUES (:u, 'corp')"),
                           {"u": uid}).lastrowid
        return conn.execute(text("INSERT INTO projects (company_id, description) VALUES (:c, '테스트')"),
                            {"c": cid}).lastrowid


def set_training_consent(engine: Engine, project_id: int, agreed: bool) -> None:
    """프로젝트 주인 계정의 학습 데이터 편입 동의(users.ai_training_agreed)를 바꾼다 (웹이 로그인마다 갱신)."""
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE users SET ai_training_agreed = :a WHERE user_id = (SELECT c.user_id FROM companies c "
            "JOIN projects p ON p.company_id = c.company_id WHERE p.project_id = :p)"), {"a": agreed, "p": project_id})


def project_row(engine: Engine, project_id: int) -> dict[str, Any]:
    """웹 projects 행 전체 (Orchestrator가 바꾸지 않는지 확인용)."""
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT * FROM projects WHERE project_id = :p"), {"p": project_id})
                    .mappings().one())


def proofread_rows(engine: Engine, project_id: int) -> list[dict[str, Any]]:
    """웹 proofread_logs의 프로젝트 행 (쓴 순서)."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "SELECT * FROM proofread_logs WHERE project_id = :p ORDER BY log_id"), {"p": project_id}).mappings()]


def count_rows(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(text(table))).scalar_one()
