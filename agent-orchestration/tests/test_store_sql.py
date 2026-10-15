"""SQL 저장소 부속 — DDL 파일, 설정 입력(verification_policies — token_retry_cap은 선택 컬럼), 웹 테이블 구조 확인."""
from __future__ import annotations

import pytest
from conftest import TIMING, Clock, make_app, pre_input
from mysqldb import MYSQL, require_mysql, split_sql, xdist_groups
from sqlalchemy import Column, Integer, MetaData, Table, insert, update
from webdb import POLICIES, create_web_tables, new_project

from sbrain.intake.sql_source import SchemaMismatch
from sbrain.store_sql import (
    DbSettingsProvider, SqlStore, create_orchestrator_tables, create_sqlite_engine,
)
from sbrain.store_sql.ddl import DDL_PATH, render
from sbrain.store_sql.schema import ORCH_TABLES, RECORD_TABLES


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
    assert len(ORCH_TABLES) == 13
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


def test_file_deletion_table_is_minimal_and_outside_records():
    """파일 삭제 대기열 표 (spec 4.6) — 칸 · 타입 · 고유 제약 · 색인 하나, orch_runs 외래 키 없음, RECORD_TABLES 밖.

    run_id를 갖는 표 중 RECORD_TABLES에 넣지 않는 것은 이 표 하나다(넣으면 12개월 처리 · 탈퇴가 줄을 지워 파일이 남는다).
    """
    tables = {t.name: t for t in ORCH_TABLES}
    t = tables["orch_file_deletions"]
    assert [c.name for c in t.columns] == [
        "deletion_id", "run_id", "key_prefix", "status", "attempts", "last_error_kind", "created_at", "next_at",
        "last_tried_at", "gave_up_at", "retried_by", "retried_at", "retry_count"]
    assert [c.name for c in t.primary_key] == ["deletion_id"]
    assert not t.foreign_keys                                                     # 실행 건 줄이 지워져도 남는다
    lengths = {c.name: getattr(c.type, "length", None) for c in t.columns}
    assert lengths["deletion_id"] == lengths["run_id"] == lengths["retried_by"] == 64
    assert lengths["key_prefix"] == 80 and lengths["status"] == lengths["last_error_kind"] == 10
    nullable = {c.name: c.nullable for c in t.columns}
    assert all(nullable[c] for c in ("last_error_kind", "last_tried_at", "gave_up_at", "retried_by", "retried_at"))
    assert not any(nullable[c] for c in ("run_id", "key_prefix", "status", "attempts", "created_at", "next_at",
                                         "retry_count"))
    assert {i.name: [c.name for c in i.columns] for i in t.indexes} == {
        "ix_orch_file_deletions_status_next": ["status", "next_at"]}
    assert "CONSTRAINT uq_orch_file_deletions_run UNIQUE (run_id)" in render()
    assert t not in RECORD_TABLES
    with_run_id = {x.name for x in ORCH_TABLES if "run_id" in x.c} - {x.name for x in RECORD_TABLES}
    # 실행 건 · 산출물 · 시작 요청(만든 실행 건)은 원래 기록 표가 아니다. 새로 생긴 예외는 대기열 하나
    assert with_run_id == {"orch_runs", "orch_start_requests", "orch_artifact_versions", "orch_artifact_pointers",
                           "orch_file_deletions"}


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
        conn.execute(insert(POLICIES).values(policy_id=1, doc_weight=60, code_weight=12, plan_weight=28,
                                             pass_threshold=75, rerun_cap=3, rework_cap=2, deviation_cap=4.5,
                                             token_retry_cap=1))
        conn.execute(insert(POLICIES).values(policy_id=2, pass_threshold=10))   # 첫 행만 쓴다
    s = provider.current()
    assert (s.scoring.doc_layer_max, s.scoring.artifact_layer_max, s.scoring.threshold) == (60, 40, 75)
    # 코드 점검 배점 C = code_weight, 계획서 대조 배점 P = plan_weight, 산출물층 배점 = C + P (spec 4.6)
    assert (s.scoring.code_check_max, s.scoring.feature_match_max) == (12, 28)
    assert {"codeCheckMax": 12, "featureMatchMax": 28, "artifactLayerMax": 40}.items() <= \
        provider.snapshot()["scoring"].items()
    assert (s.redo.redo_count, s.rework.per_bundle, s.redo.proofread_redo_count) == (3, 2, 1)
    assert s.scoring.deviation_cap == 4.5
    assert s.retry.retry_count == 5 and s.tasks["T-C1"].model == "gpt-6-luna"      # 나머지는 코드 기본값
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


def policies_without_token_retry_cap(engine) -> Table:
    """웹이 token_retry_cap을 지운 verification_policies (그 밖의 컬럼은 POLICIES와 같다)."""
    table = Table("verification_policies", MetaData(),
                  *(Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable,
                           server_default=c.server_default.arg if c.server_default is not None else None)
                    for c in POLICIES.columns if c.name != "token_retry_cap"))
    table.create(engine)
    return table


def test_token_retry_cap_is_optional_column(tmp_path):
    """token_retry_cap은 선택 컬럼 — 없어도 설정 읽기가 실패하지 않고 코드 기본값(None = 재수행 횟수와 같음)을 쓴다."""
    engine = create_sqlite_engine(tmp_path / "no-token-cap.db")
    table = policies_without_token_retry_cap(engine)
    provider = DbSettingsProvider(engine)
    assert provider.current() == provider._settings                               # 행이 없어도 오류 없음
    with engine.begin() as conn:
        conn.execute(insert(table).values(policy_id=1, rerun_cap=3, rework_cap=2))
    s = provider.current()
    assert s.redo.proofread_redo_count is None                                    # 코드 기본값 — 재수행 횟수와 같음
    assert (s.redo.redo_count, s.rework.per_bundle) == (3, 2)                     # 다른 컬럼은 그대로 읽는다
    assert provider.snapshot()["redo"]["proofreadRedoCount"] is None
    with engine.connect() as conn:
        assert SqlStore(engine).web.first_policy(conn)["token_retry_cap"] is None


def test_token_retry_cap_is_read_when_present(web_engine):
    """컬럼이 있으면 지금처럼 redo.proofreadRedoCount로 읽는다 (0도 그대로)."""
    with web_engine.begin() as conn:
        conn.execute(insert(POLICIES).values(policy_id=1, rerun_cap=3, token_retry_cap=0))
    s = DbSettingsProvider(web_engine).current()
    assert s.redo.proofread_redo_count == 0


# ── MySQL 묶음 확인 (DB 없이) ──────────────────────────
def no_db_url(monkeypatch) -> None:
    monkeypatch.setattr("mysqldb.get_env", lambda name, default=None: None)


def test_require_mysql_outside_any_group_fails_even_without_db(monkeypatch):
    """묶음 없는 테스트가 MySQL에 닿으면 건너뜀이 아니라 실패다 — DB 주소가 없어도 묶음을 먼저 본다."""
    no_db_url(monkeypatch)
    with pytest.raises(pytest.fail.Exception, match="MySQL 묶음"):
        require_mysql()


@TIMING
def test_require_mysql_in_other_group_fails(monkeypatch):
    no_db_url(monkeypatch)
    with pytest.raises(pytest.fail.Exception, match="timing"):
        require_mysql()


@MYSQL
def test_require_mysql_in_mysql_group_skips_without_db(monkeypatch):
    no_db_url(monkeypatch)
    with pytest.raises(pytest.skip.Exception):
        require_mysql()


@TIMING
@pytest.mark.parametrize("kind", [pytest.param("mysql", marks=MYSQL)])
def test_mysql_group_wins_over_timing(request, kind):
    """MySQL 매개변수가 붙은 시간 테스트는 MySQL 묶음 하나에만 든다 (conftest.py)."""
    assert xdist_groups(request.node) == {"mysql"}
