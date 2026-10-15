"""시각 UTC 통일 · 한국 날짜 (spec 2 · 13).

- 프로세스 안의 시각은 시간대 있는 UTC다. 웹 함수 결과의 시각도 모두 UTC다(JSON이면 Z 또는 +00:00).
- DB DATETIME 칸(orch_ 테이블 · 우리가 INSERT하는 웹 표 셋)은 시간대 없는 UTC 값이다. 읽을 때 UTC를 붙인다.
- 시간대 없는 값(옛 JSON · DB 값, 웹이 넘기는 시각 인자, 테스트가 넘기는 값)은 UTC로 본다.
- '오늘'은 한국 날짜(UTC+9 고정)다 — G-01 기준일, 마감 안내, 스텁 공고 날짜.
- proofread_logs.created_at은 DB 기본값이 아니라 단계 저장 시각(UTC)이다. 워커 로그 시각도 UTC(끝에 Z).
"""
from __future__ import annotations

import dataclasses
import re
from datetime import date, datetime, timedelta

import pytest
from conftest import Backend, Clock, make_app, set_consent, start_and_select, to_screen6, to_screen9
from pydantic import BaseModel
from sqlalchemy import DateTime, text
from webdb import proofread_rows

import sbrain.worker as worker_mod
from sbrain.agents.stubs import StubScenario
from sbrain.bootstrap import build_stub_app
from sbrain.models import Notice, Run
from sbrain.models.clock import KST, UTC, as_utc, kst_month, kst_today, naive_utc, utc_clock, utc_now
from sbrain.store_sql import SqlStore
from sbrain.orchestrator.store import RunFilter
from sbrain.store_sql.schema import ORCH_TABLES
from sbrain.worker import Worker, WorkerConfig

def pid_of(app, rid: str) -> str:
    return app.store.load_run(rid).project_id


def is_time_column(col) -> bool:
    return isinstance(col.type, DateTime) or isinstance(getattr(col.type, "impl", None), DateTime)


ISO_TIME = re.compile(r'"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)([^"]*)"')


def times_in(obj) -> list[datetime]:
    """결과 안의 모든 datetime — 모델 · dataclass · 목록 · 사전을 따라간다."""
    out: list[datetime] = []

    def walk(x) -> None:
        if isinstance(x, datetime):
            out.append(x)
        elif isinstance(x, BaseModel):
            for f in type(x).model_fields:
                walk(getattr(x, f))
        elif dataclasses.is_dataclass(x) and not isinstance(x, type):
            for f in dataclasses.fields(x):
                walk(getattr(x, f.name))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple, set)):
            for v in x:
                walk(v)
    walk(obj)
    return out


def is_utc(t: datetime) -> bool:
    return t.tzinfo is not None and t.utcoffset() == timedelta(0)


def assert_all_utc(*results) -> int:
    found = [t for r in results for t in times_in(r)]
    assert all(is_utc(t) for t in found), [t for t in found if not is_utc(t)]
    for r in results:   # JSON으로 내보내면 시간대 표시(Z 또는 +00:00)가 붙는다
        for x in (r if isinstance(r, list) else [r]):
            if isinstance(x, BaseModel):
                assert all(tz in ("Z", "+00:00") for _, tz in ISO_TIME.findall(x.model_dump_json(by_alias=True)))
    return len(found)


# ── 시계 함수 ─────────────────────────────────────────
def test_clock_helpers():
    assert is_utc(utc_now()) and abs(utc_now() - datetime.now(UTC)) < timedelta(seconds=5)
    assert as_utc(datetime(2026, 9, 26, 9)) == datetime(2026, 9, 26, 9, tzinfo=UTC)          # 시간대 없으면 UTC
    converted = as_utc(datetime(2026, 9, 26, 18, tzinfo=KST))
    assert converted == datetime(2026, 9, 26, 9, tzinfo=UTC) and converted.tzinfo is UTC
    assert as_utc(None) is None and naive_utc(None) is None
    stored = naive_utc(datetime(2026, 9, 26, 18, tzinfo=KST))
    assert stored == datetime(2026, 9, 26, 9) and stored.tzinfo is None                     # DB 값: 시간대 없는 UTC
    assert kst_today(datetime(2026, 9, 26, 14, 59, 59, tzinfo=UTC)) == date(2026, 9, 26)
    assert kst_today(datetime(2026, 9, 26, 15, 0, tzinfo=UTC)) == date(2026, 9, 27)          # 한국은 다음 날
    assert kst_today(datetime(2026, 9, 26, 15, 0)) == date(2026, 9, 27)                       # 시간대 없으면 UTC
    assert kst_today() in (datetime.now(UTC).date(), datetime.now(UTC).date() + timedelta(days=1))
    assert kst_month(datetime(2026, 9, 30, 14, 59, tzinfo=UTC)) == "2026-09"
    assert kst_month(datetime(2026, 9, 30, 15, 0, tzinfo=UTC)) == "2026-10"
    wrapped = utc_clock(lambda: datetime(2026, 9, 26, 9))
    assert wrapped() == datetime(2026, 9, 26, 9, tzinfo=UTC) and is_utc(wrapped())
    assert utc_clock(utc_now) is utc_now


def test_models_treat_naive_as_utc_and_dump_with_offset(clock):
    n = Notice(code="X", message="m", at="2026-09-26T09:00:00")                              # 옛 JSON
    assert n.at == datetime(2026, 9, 26, 9, tzinfo=UTC)
    assert Notice(code="X", message="m", at=datetime(2026, 9, 26, 18, tzinfo=KST)).at == n.at
    assert Notice(code="X", message="m", at=datetime(2026, 9, 26, 9)).dump()["at"] in (
        "2026-09-26T09:00:00Z", "2026-09-26T09:00:00+00:00")
    app = make_app(clock)
    rid = to_screen6(app)
    saved = app.store.load_run(rid).dump()
    assert assert_all_utc(app.store.load_run(rid)) >= 3
    # 시간대 표시를 뗀 옛 실행 건 JSON도 읽히고 UTC로 본다
    old = Run.model_validate_json(re.sub(r'(T\d{2}:\d{2}:\d{2}(?:\.\d+)?)(Z|\+00:00)"', r'\1"',
                                         Run.model_validate(saved).model_dump_json(by_alias=True)))
    assert assert_all_utc(old) >= 3 and old.dump() == saved


# ── DB 값 ─────────────────────────────────────────────
def sql_app(tmp_path, start: datetime, scenario: StubScenario | None = None):
    clock = Clock(start, Backend("sql", tmp_path))
    return make_app(clock, scenario), clock


def raw_times(engine, table: str, columns: list[str]) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT {', '.join(columns)} FROM {table}")).all()
    return [v for r in rows for v in r if v is not None]


def test_db_datetime_columns_hold_naive_utc(tmp_path):
    # 시계가 한국 시각(18:00+09:00)을 줘도 DB에는 시간대 없는 UTC(09:00)로 들어간다
    app, clock = sql_app(tmp_path, datetime(2026, 9, 26, 18, 0, tzinfo=KST))
    rid = to_screen6(app)                                                    # 알림(화면 6) 생김
    failed = start_and_select(app, "acc-2")
    app.llm.plan("T-S1", ["auth"] * 50)
    app.orchestrator.start_writing(failed)
    app.orchestrator.advance(failed)                                         # 실패 → generation_failure_alerts
    assert app.store.load_run(failed).state.progress == "실패"
    engine = app.store.engine
    values = []
    for table in ORCH_TABLES:
        cols = [c.name for c in table.columns if is_time_column(c)]
        if cols:
            values += raw_times(engine, table.name, cols)
    values += raw_times(engine, "notifications", ["created_at", "read_at"])
    values += raw_times(engine, "generation_failure_alerts", ["created_at"])
    assert len(values) > 30
    for v in values:
        parsed = datetime.fromisoformat(str(v))
        assert parsed.tzinfo is None and "+" not in str(v)                  # 시간대 없는 값
        assert datetime(2026, 9, 26, 9, 0) <= parsed < datetime(2026, 9, 26, 10, 0), v   # UTC (한국 시각 아님)
    # 읽으면 UTC가 붙는다
    run = app.store.load_run(rid)
    assert is_utc(run.created_at) and run.created_at.hour == 9
    [row] = app.store.query_runs(RunFilter(project_ids=[run.project_id]))
    assert is_utc(row.updated_at)
    art = app.store.get_artifact(rid, "itemSpec", 1)
    assert is_utc(art.created_at) and art.created_at.hour == 9
    req = app.store.latest_start_request(run.project_id)
    assert all(is_utc(t) for t in (req.created_at, req.updated_at, req.finished_at))


def test_notifications_read_from_web_table_carry_utc(tmp_path):
    app, _ = sql_app(tmp_path, datetime(2026, 9, 26, 9, 0, tzinfo=UTC))
    rid = to_screen6(app)
    raw = raw_times(app.store.engine, "notifications", ["created_at"])
    notes = app.store.notifications(rid)
    assert notes and len(raw) == len(notes)
    assert [n.created_at for n in notes] == [as_utc(datetime.fromisoformat(v)) for v in raw]
    assert all(is_utc(n.created_at) for n in notes)
    with app.store.engine.begin() as conn:                                   # 웹이 읽음 처리(UTC로 씀)
        conn.execute(text("UPDATE notifications SET read_at = '2026-09-26 10:30:00'"))
    assert {n.read_at for n in app.store.notifications(rid)} == {datetime(2026, 9, 26, 10, 30, tzinfo=UTC)}


def test_proofread_logs_created_at_is_save_time_in_utc(tmp_path):
    app, clock = sql_app(tmp_path, datetime(2026, 9, 26, 18, 0, tzinfo=KST),
                         StubScenario(tp1_targets=1, tp2_behavior={"s-1-1-1": ["violate", "ok"]}))
    rid = to_screen9(app)
    set_consent(app, rid)
    before = as_utc(clock.t)
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    after = as_utc(clock.t)
    [row] = proofread_rows(app.store.engine, int(app.store.load_run(rid).project_id))
    created = datetime.fromisoformat(str(row["created_at"]))
    assert created.tzinfo is None                                            # 시간대 없는 UTC
    assert before <= as_utc(created) <= after                                # DB 기본값(지금)이 아니라 저장 시각


# ── 시간대 없는 입력 ───────────────────────────────────
def test_naive_clock_is_treated_as_utc(store_backend):
    clock = Clock(datetime(2026, 9, 26, 9, 0), store_backend)                # 테스트가 넘기는 시간대 없는 시계
    app = make_app(clock)
    rid = to_screen6(app)
    run = app.store.load_run(rid)
    assert is_utc(run.created_at) and run.created_at - datetime(2026, 9, 26, 9, tzinfo=UTC) < timedelta(seconds=1)
    assert assert_all_utc(app.orchestrator.view_project(run.project_id)) >= 1


def test_naive_web_time_arguments_are_utc(clock):
    app = make_app(clock)
    start_and_select(app)
    since, until = datetime(2026, 9, 26, 9, 0), datetime(2026, 9, 26, 10, 0)  # 웹이 넘기는 시간대 없는 값
    aware = app.orchestrator.admin_executions(since=since.replace(tzinfo=UTC), until=until.replace(tzinfo=UTC))
    naive = app.orchestrator.admin_executions(since=since, until=until)
    korea = app.orchestrator.admin_executions(since=datetime(2026, 9, 26, 18, 0, tzinfo=KST))
    ids = [e.execution_id for e in aware]
    assert ids and [e.execution_id for e in naive] == ids == [e.execution_id for e in korea]
    assert app.orchestrator.admin_executions(since=until) == []
    assert app.orchestrator.admin_executions(until=since) == []
    # tick(now) — 시간대 없는 값을 UTC로 본다
    rid = start_and_select(app, "acc-2")
    app.llm.plan("T-S2", ["timeout"] * 6)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기" and is_utc(run.next_resume_at)
    due = naive_utc(run.next_resume_at)
    assert app.orchestrator.tick(due - timedelta(seconds=1)) == []
    assert app.orchestrator.tick(due + timedelta(seconds=1)) == [rid]


# ── 웹 함수 결과 ───────────────────────────────────────
def test_every_time_in_web_results_is_utc(clock):
    clock.t = datetime(2026, 9, 26, 18, 0, tzinfo=KST)                       # 한국 시각을 주는 시계
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    a = to_screen6(app)
    p = pid_of(app, a)
    accepted = app.orchestrator.request_rework_for_project(p, "문제인식")
    assert is_utc(accepted.collect_until) and accepted.collect_until.hour == 9
    view = app.orchestrator.view_project(p)
    assert view.run.collecting and view.run.notifications
    clock.advance(seconds=3)
    app.orchestrator.advance(a)
    b = start_and_select(app, "acc-2")                                       # 재개대기 — next_resume_at
    app.llm.plan("T-S2", ["timeout"] * 6)
    app.orchestrator.start_writing(b)
    app.orchestrator.advance(b)
    pb = pid_of(app, b)
    waiting = app.orchestrator.view_project(pb)
    assert waiting.run.next_resume_at is not None
    executions = app.orchestrator.admin_executions()
    results = [
        accepted, app.orchestrator.view_project(p), waiting, app.orchestrator.project_views([p, pb]),
        app.orchestrator.wait_project(p, timeout_sec=0), app.orchestrator.start_status(p),
        app.orchestrator.rework_result(p), app.orchestrator.outputs(p),
        app.orchestrator.admin_runs(), executions, app.orchestrator.admin_calls(executions[-1].execution_id),
        app.orchestrator.admin_score_history(p),
    ]
    assert assert_all_utc(*results) > 20
    assert all(t.hour == 9 for r in results for t in times_in(r))           # 한국 18시 = UTC 9시


# ── 한국 날짜 ─────────────────────────────────────────
def test_g01_today_and_stub_dates_use_korean_date(clock):
    clock.t = datetime(2026, 9, 26, 15, 30, tzinfo=UTC)                      # 한국은 9월 27일 00:30
    app = make_app(clock)
    seen = []
    base = app.registry.get("G-01").fn

    def spy(inp, tools):
        seen.append(inp.today)
        return base(inp, tools)
    app.registry.bind("G-01", spy)
    rid = start_and_select(app)
    assert seen == [date(2026, 9, 27)]                                       # 자격 판정 기준일 TODAY
    ann = app.engine.open_context(app.store.load_run(rid)).get("selectedAnnouncement")
    assert ann.apply_end == date(2026, 10, 27)                               # 스텁 공고 날짜도 한국 날짜 기준


def test_deadline_notice_uses_korean_date(clock):
    app = make_app(clock)                                                    # 2026-09-26 09:00 UTC (한국 18:00)
    rid = start_and_select(app)
    ann = app.engine.open_context(app.store.load_run(rid)).get("selectedAnnouncement")
    assert ann.apply_end == date(2026, 10, 26)

    def closed() -> bool:
        return "E-RUN-CLOSED" in [n.code for n in app.orchestrator.view(rid).notices]
    clock.t = datetime(2026, 10, 26, 14, 59, tzinfo=UTC)                     # 한국 10월 26일 23:59 — 마감일 당일
    assert not closed()
    clock.t = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)                      # 한국 10월 27일 — 마감일이 지났다
    assert closed()


# ── 워커 로그 ─────────────────────────────────────────
def test_worker_log_time_is_utc(monkeypatch):
    lines: list[str] = []
    w = Worker(build_stub_app(), WorkerConfig(), log=lines.append, name="w")
    monkeypatch.setattr(worker_mod, "utc_now", lambda: datetime(2026, 9, 26, 9, 0, 5, tzinfo=UTC))
    w.log("w", "시작")
    assert lines == ["2026-09-26 09:00:05Z w 시작"]                           # 끝의 Z로 UTC임을 보인다


def test_sql_store_rejects_nothing_naive(tmp_path):
    """SqlStore에 시간대 없는 시각 인자를 넘겨도(웹 · 테스트) UTC로 본다."""
    app, clock = sql_app(tmp_path, datetime(2026, 9, 26, 9, 0, tzinfo=UTC))
    rid = start_and_select(app)
    assert isinstance(app.store, SqlStore)
    assert not app.store.is_locked(rid, datetime(2026, 9, 26, 9, 0))
    assert app.store.runs_due_for_resume(datetime(2026, 9, 26, 9, 0)) == []


@pytest.mark.parametrize("value", ["2026-09-26T09:00:00", "2026-09-26T09:00:00Z", "2026-09-26T18:00:00+09:00"])
def test_old_and_new_json_times_compare(value):
    assert Notice(code="X", message="m", at=value).at == datetime(2026, 9, 26, 9, tzinfo=UTC)
