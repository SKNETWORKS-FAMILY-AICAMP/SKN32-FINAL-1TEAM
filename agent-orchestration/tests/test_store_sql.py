"""SQL 저장소 부속 — DDL 파일, 설정 입력(verification_policies), 웹 테이블 구조 확인 · 학습 동의 읽기."""
from __future__ import annotations

import pytest
from conftest import Clock, make_app, pre_input
from mysqldb import split_sql
from sqlalchemy import Column, Integer, MetaData, Table, UniqueConstraint, insert, update
from test_store_contract import new_run, rejected
from webdb import (
    POLICIES, PROOFREAD_LOGS, create_web_tables, new_project, proofread_columns, set_training_consent,
    use_old_proofread_logs,
)

from sbrain.intake.sql_source import SchemaMismatch
from sbrain.orchestrator.store import CommitBatch
from sbrain.store_sql import (
    DbSettingsProvider, SqlStore, create_orchestrator_tables, create_sqlite_engine,
)
from sbrain.store_sql.ddl import DDL_PATH, render
from sbrain.store_sql.schema import ORCH_TABLES
from sbrain.store_sql.web_tables import ProofreadWriteError


def test_ddl_file_is_current():
    """sql/orchestrator_schema.sql = schema.py에서 만든 결과 (다르면 python -m sbrain.store_sql.ddl)."""
    assert DDL_PATH.read_text(encoding="utf-8") == render()


def test_ddl_is_create_if_not_exists_only():
    text = render()
    statements = split_sql(text)
    assert len(statements) == len(ORCH_TABLES)
    assert all(s.startswith("CREATE TABLE IF NOT EXISTS orch_") for s in statements)
    assert "ENGINE=InnoDB" in text and "utf8mb4_bin" in text and "DATETIME(6)" in text
    assert "JSON" not in text.replace("_json", "").replace("JSON 이름", "").replace("(JSON)", "")


def test_stats_and_job_tables_have_no_identifier_columns():
    """통계 줄 · 작업 상태 표에는 계정 · 프로젝트 · 실행 건 · 실행 · 공고 ID나 자유 글 컬럼이 없다 (spec 4.1 · 5.4)."""
    tables = {t.name: t for t in ORCH_TABLES}
    assert len(ORCH_TABLES) == 12
    stats, jobs = tables["orch_log_stats"], tables["orch_jobs"]
    assert [c.name for c in stats.columns] == [
        "seq", "kind", "reason", "month", "category", "status", "result_code", "part", "count", "data_json",
        "created_at"]
    assert [c.name for c in jobs.columns] == [
        "job_name", "lease_owner", "lease_until", "last_started_at", "last_finished_at", "last_summary"]
    assert [c.name for c in stats.primary_key] == ["seq"] and [c.name for c in jobs.primary_key] == ["job_name"]
    nullable = {c.name: c.nullable for c in stats.columns}
    assert not any(nullable[c] for c in ("kind", "reason", "month", "part", "count", "created_at"))
    assert all(nullable[c] for c in ("category", "status", "result_code", "data_json"))
    indexes = {t: {i.name: [c.name for c in i.columns] for i in tables[t].indexes} for t in tables}
    assert indexes["orch_log_stats"] == {"ix_orch_log_stats_kind_month": ["kind", "month"]}
    assert indexes["orch_runs"]["ix_orch_runs_updated"] == ["updated_at"]
    assert indexes["orch_start_requests"]["ix_orch_start_requests_status_updated"] == ["status", "updated_at"]
    ddl = render()
    assert "part INTEGER NOT NULL COMMENT" in ddl and "DEFAULT 1, \n\tcount INTEGER NOT NULL" in ddl
    assert "month CHAR(7) NOT NULL" in ddl


@pytest.fixture
def web_engine(tmp_path):
    engine = create_sqlite_engine(tmp_path / "web.db", fast=True)
    create_orchestrator_tables(engine)
    create_web_tables(engine)
    return engine


def test_settings_from_verification_policies(web_engine):
    provider = DbSettingsProvider(web_engine)
    assert provider.current() == provider._settings          # 행이 없으면 코드 기본값
    with web_engine.begin() as conn:
        conn.execute(insert(POLICIES).values(policy_id=1, doc_weight=60, code_weight=20, plan_weight=20,
                                             pass_threshold=75, rerun_cap=3, rework_cap=2, deviation_cap=4.5,
                                             token_retry_cap=1))
        conn.execute(insert(POLICIES).values(policy_id=2, pass_threshold=10))   # 첫 행만 쓴다
    s = provider.current()
    assert (s.scoring.doc_layer_max, s.scoring.artifact_layer_max, s.scoring.threshold) == (60, 40, 75)
    assert (s.redo.redo_count, s.rework.per_bundle, s.redo.proofread_redo_count) == (3, 2, 1)
    assert s.scoring.deviation_cap == 4.5
    assert s.retry.retry_count == 5 and s.agents["조율"].model == "gpt-6-luna"      # 나머지는 코드 기본값
    assert provider.snapshot()["scoring"]["deviationCap"] == 4.5


def test_settings_are_fixed_at_run_start(web_engine):
    with web_engine.begin() as conn:
        conn.execute(insert(POLICIES).values(policy_id=1, pass_threshold=75))
    clock = Clock()
    app = make_app(clock, store=SqlStore(web_engine, now=clock))
    app.orchestrator.settings = DbSettingsProvider(web_engine)
    res = app.orchestrator.start_run("acc-1", pre_input(), project_id=str(new_project(web_engine)))
    assert res.ok
    with web_engine.begin() as conn:
        conn.execute(update(POLICIES).values(pass_threshold=90))
    run = app.store.load_run(res.run_id)
    assert run.settings_snapshot["scoring"]["threshold"] == 75                   # 시작 때 값 그대로


def test_missing_web_column_is_reported(tmp_path):
    engine = create_sqlite_engine(tmp_path / "broken.db")
    Table("verification_policies", MetaData(), Column("policy_id", Integer, primary_key=True)).create(engine)
    with pytest.raises(SchemaMismatch, match="deviation_cap"):
        DbSettingsProvider(engine).current()
    with pytest.raises(SchemaMismatch, match="notifications"):
        with engine.connect() as conn:
            SqlStore(engine).web.table(conn, "notifications")


def test_proofread_logs_mismatch_is_reported_not_raised(tmp_path):
    """proofread_logs만 구조가 맞지 않아도 SchemaMismatch를 올리지 않고 이유를 돌려준다 (단계 저장을 되돌리지 않게)."""
    engine = create_sqlite_engine(tmp_path / "old.db")
    create_web_tables(engine)
    use_old_proofread_logs(engine)
    web = SqlStore(engine).web
    with engine.connect() as conn:
        table, problem = web.proofread_logs(conn)
        assert table is None and "project_id" in problem and "model_version" in problem
    engine = create_sqlite_engine(tmp_path / "none.db")
    with engine.connect() as conn:
        table, problem = SqlStore(engine).web.proofread_logs(conn)
        assert table is None and "proofread_logs" in problem
    engine = create_sqlite_engine(tmp_path / "new.db")
    create_web_tables(engine)
    with engine.connect() as conn:
        table, problem = SqlStore(engine).web.proofread_logs(conn)
        assert table is not None and problem == ""


def test_proofread_logs_with_unfillable_required_column_is_skipped(tmp_path):
    """필요한 컬럼이 다 있어도 Orchestrator가 채우지 않는 필수 컬럼(기본값 없음)이 남아 있으면 쓰지 않는다 (잠정)."""
    engine = create_sqlite_engine(tmp_path / "half.db")
    create_web_tables(engine)
    PROOFREAD_LOGS.drop(engine)
    Table("proofread_logs", MetaData(), *proofread_columns(new=True),
          Column("plan_ref", Integer, nullable=False)).create(engine)
    with engine.connect() as conn:
        table, problem = SqlStore(engine).web.proofread_logs(conn)
    assert table is None and "plan_ref" in problem


def test_proofread_write_error_hides_content_and_rolls_back(tmp_path):
    """proofread_logs INSERT 오류는 단계 저장 전체를 되돌리고, 예외 메시지에 문장 내용(SQL 인자)을 싣지 않는다."""
    engine = create_sqlite_engine(tmp_path / "dup.db", fast=True)
    create_orchestrator_tables(engine)
    create_web_tables(engine)
    PROOFREAD_LOGS.drop(engine)
    Table("proofread_logs", MetaData(), *proofread_columns(new=True),
          UniqueConstraint("project_id", "attempt_no")).create(engine)
    store, clock = SqlStore(engine), Clock()
    run = new_run(clock, "acc-dup", project_id=str(new_project(engine, agreed=True)))
    assert store.create_run(run, CommitBatch()) and store.acquire(run.run_id, "w", 60)
    with pytest.raises(ProofreadWriteError) as e:
        store.commit(run.run_id, "w", CommitBatch(run=run.model_copy(update={"current_task": "T-P2"}),
                                                  rejected_attempts=[rejected(run, 1), rejected(run, 1)]))
    assert "IntegrityError" in str(e.value) and "반려" not in str(e.value) and "원문" not in str(e.value)
    assert store.load_run(run.run_id).current_task is None                       # 한 트랜잭션 — 함께 되돌려짐


def test_consent_columns_are_checked(tmp_path):
    """학습 동의 확인에 쓰는 컬럼(users.ai_training_agreed 등)이 없으면 다른 웹 테이블처럼 SchemaMismatch."""
    engine = create_sqlite_engine(tmp_path / "no-consent.db")
    meta = MetaData()
    Table("projects", meta, Column("project_id", Integer, primary_key=True), Column("company_id", Integer))
    Table("companies", meta, Column("company_id", Integer, primary_key=True), Column("user_id", Integer))
    Table("users", meta, Column("user_id", Integer, primary_key=True))
    meta.create_all(engine)
    with pytest.raises(SchemaMismatch, match="ai_training_agreed"):
        with engine.connect() as conn:
            SqlStore(engine).web.training_agreed(conn, 1)


def test_training_agreed_follows_owner_account(web_engine):
    agreed, refused = new_project(web_engine, agreed=True), new_project(web_engine)
    web = SqlStore(web_engine).web
    with web_engine.connect() as conn:
        assert web.training_agreed(conn, agreed) and not web.training_agreed(conn, refused)
        assert not web.training_agreed(conn, 999_999)                          # 없는 프로젝트
    set_training_consent(web_engine, refused, True)
    with web_engine.connect() as conn:
        assert web.training_agreed(conn, refused)
