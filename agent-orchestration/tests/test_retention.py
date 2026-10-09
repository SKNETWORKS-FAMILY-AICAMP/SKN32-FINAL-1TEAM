"""실행 로그 보관 기간 작업 (spec 5.1 · 5.4) — 12개월 지난 실행 건 · 끝난 시작 요청의 기록을 통계 줄로 옮기고 지운다.

흐름 테스트는 메모리 저장소와 SqlStore(SQLite)로 한 번씩 돈다. 고정 시계를 13개월 넘게 넘겨 대상을 만든다.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest
from conftest import make_app, pre_input, project_for, start_and_select, to_screen6, to_screen9
from flow_helpers import finish, pid, rework
from sqlalchemy import select

from sbrain.agents.stubs import StubScenario
from sbrain.flow.retention import (
    BATCH_SIZE, INTERVAL_SEC, JOB_NAME, retention_cutoff, run_retention, start_retention,
)
from sbrain.models.clock import KST, kst_month
from sbrain.orchestrator.settings import PROVISIONAL
from sbrain.store_sql import SqlStore
from sbrain.store_sql.schema import RUNS

UTC = timezone.utc
LATER = 400   # 일 — 12개월(달력)을 넘기는 날 수
SUMMARY_KEYS = {"runs", "deletedRuns", "requests", "skipped"}


def retain(app, clock, owner: str = "w", **kw):
    """작업 점유를 잡고 끝까지 돈다 (워커의 ④와 같은 순서)."""
    assert start_retention(app.store, owner, 60)
    return run_retention(app.store, owner, now=clock(), lease_sec=60, **kw)


def record_counts(app, rid: str) -> list[int]:
    s = app.store
    return [len(s.executions(rid)), len(s.call_logs(rid)), len(s.events(rid)), len(s.feedback(rid)),
            len(s.comparisons(rid)), len(s.pointer_events(rid))]


def sql_updated_at(app, rid: str):
    """SqlStore면 updated_at 컬럼 · run_json의 updatedAt, 메모리면 run_json의 updatedAt만."""
    if isinstance(app.store, SqlStore):
        with app.store.engine.connect() as conn:
            row = conn.execute(select(RUNS.c.updated_at, RUNS.c.run_json).where(RUNS.c.run_id == rid)).first()
        return row.updated_at, row.run_json["updatedAt"]
    return app.store.load_run(rid).dump()["updatedAt"]


# ── 기준 시각 ──────────────────────────────────────────
def test_cutoff_is_twelve_calendar_months_before_in_utc():
    assert retention_cutoff(datetime(2026, 10, 5, 3, 4, 5, tzinfo=UTC)) == datetime(2025, 10, 5, 3, 4, 5, tzinfo=UTC)
    assert retention_cutoff(datetime(2026, 3, 31, tzinfo=UTC)) == datetime(2025, 3, 31, tzinfo=UTC)
    assert retention_cutoff(datetime(2028, 2, 29, 12, tzinfo=UTC)) == datetime(2027, 2, 28, 12, tzinfo=UTC)
    assert retention_cutoff(datetime(2028, 3, 1, tzinfo=UTC)) == datetime(2027, 3, 1, tzinfo=UTC)   # 365일이 아니다
    assert retention_cutoff(datetime(2026, 1, 15)) == datetime(2025, 1, 15, tzinfo=UTC)          # 시간대 없으면 UTC
    # 한국 시각은 UTC로 바꾼 뒤 계산한다 (KST 2026-01-01 05:00 = UTC 2025-12-31 20:00)
    assert retention_cutoff(datetime(2026, 1, 1, 5, tzinfo=KST)) == datetime(2024, 12, 31, 20, tzinfo=UTC)
    assert retention_cutoff(datetime(2026, 5, 31, tzinfo=UTC), months=3) == datetime(2026, 2, 28, tzinfo=UTC)


def test_provisional_values_listed():
    assert BATCH_SIZE == 100 and INTERVAL_SEC == 24 * 3600
    for key in ("retention.batchSize", "retention.intervalSec", "retention.checkSec", "retention.leaseSec",
                "store.accountLockTimeoutSec"):
        assert key in PROVISIONAL
    assert "orchestrator/store.py" in PROVISIONAL["store.accountLockTimeoutSec"]


def test_cutoff_boundary_just_before_and_after(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    updated = app.store.load_run(rid).updated_at
    year_later = updated.replace(year=updated.year + 1)
    assert start_retention(app.store, "w", 60)
    out = run_retention(app.store, "w", now=year_later, lease_sec=60)        # 기준 시각 = 마지막 활동 → 대상 아님
    assert out.finished and out.summary.runs == 0
    assert any(record_counts(app, rid)) and app.store.log_stats("실행") == []
    clock.advance(hours=25)
    assert start_retention(app.store, "w", 60)
    out = run_retention(app.store, "w", now=year_later + timedelta(milliseconds=1), lease_sec=60)
    assert out.finished and out.summary.runs == 1
    assert record_counts(app, rid) == [0] * 6


# ── 건너뛰는 실행 건 ─────────────────────────────────────
def test_busy_and_leased_runs_are_skipped(clock):
    app = make_app(clock)
    moved = to_screen6(app, "acc-1")
    running = start_and_select(app, "acc-2")
    app.orchestrator.start_writing(running)                                      # '실행' (워커가 돌 차례)
    waiting = start_and_select(app, "acc-3")
    app.llm.plan("T-S1", ["timeout"] * 6)
    app.orchestrator.start_writing(waiting)
    app.orchestrator.advance(waiting)                                            # '재개대기'
    leased = to_screen6(app, "acc-4")
    raced = to_screen6(app, "acc-5")
    assert [app.store.load_run(r).state.progress for r in (moved, running, waiting, leased, raced)] == [
        "사용자대기", "실행", "재개대기", "사용자대기", "사용자대기"]
    clock.advance(days=LATER)
    assert app.store.acquire(leased, "other", 3600)                              # 다른 곳이 점유 중
    before = {r: record_counts(app, r) for r in (running, waiting, leased, raced)}
    targets = app.store.retention_run_targets
    grabbed = []

    def racing(cutoff, limit):                                                   # 읽은 뒤 점유 전에 다른 워커가 잡는다
        ids = targets(cutoff, limit)
        if raced in ids and not grabbed:
            grabbed.append(app.store.acquire(raced, "other", 3600))
        return ids
    app.store.retention_run_targets = racing
    out = retain(app, clock)
    assert grabbed == [True]
    assert out.finished and (out.summary.runs, out.summary.skipped) == (1, 1)   # 점유를 못 잡은 것만 '건너뜀'
    assert record_counts(app, moved) == [0] * 6
    for r, counts in before.items():
        assert record_counts(app, r) == counts and app.store.load_run(r).stats_parts == 0
    assert app.store.is_locked(leased, clock()) and app.store.is_locked(raced, clock())   # 남의 점유는 그대로


# ── 살아 있는 실행 건 ────────────────────────────────────
def test_live_run_records_moved_and_run_row_artifacts_kept(clock):
    app = make_app(clock, StubScenario(category="원페이지"))
    rid = to_screen6(app)
    before = app.store.load_run(rid)
    pointers = app.store.get_pointers(rid)
    values = {k: app.store.get_artifact(rid, k, v).value for k, v in pointers.items()}
    stamp = sql_updated_at(app, rid)
    assert any(record_counts(app, rid))
    clock.advance(days=LATER)
    out = retain(app, clock)
    assert out.finished and out.summary.as_dict() == {"runs": 1, "deletedRuns": 0, "requests": 1, "skipped": 0}
    after = app.store.load_run(rid)
    assert after.stats_parts == 1 and after.model_copy(update={"stats_parts": 0}) == before   # 실행 건 값 그대로
    assert sql_updated_at(app, rid) == stamp                                     # 마지막 활동 시각(컬럼 · JSON) 그대로
    assert app.store.get_pointers(rid) == pointers
    assert {k: app.store.get_artifact(rid, k, v).value for k, v in pointers.items()} == values
    assert record_counts(app, rid) == [0] * 6
    assert not app.store.is_locked(rid, clock())                                 # 실행 건 점유를 풀었다
    [row] = app.store.log_stats("실행")
    assert (row.kind, row.reason, row.part, row.count, row.category, row.status, row.month) == (
        "실행", "12개월", 1, 1, "원페이지", "사용자대기", kst_month(before.created_at))
    assert row.data["tasks"]["T-C1"]["runs"]["첫실행"] == 1
    job = app.store.get_job(JOB_NAME)
    assert job.lease_owner is None and job.last_finished_at is not None
    assert job.last_summary == out.summary.as_dict() and set(job.last_summary) == SUMMARY_KEYS


def test_live_run_moved_again_later_is_part_two(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    clock.advance(days=LATER)
    assert retain(app, clock).summary.runs == 1
    clock.advance(hours=25)
    assert retain(app, clock).summary.runs == 0                                  # 옮길 기록이 없으면 줄을 쓰지 않는다
    assert len(app.store.log_stats("실행")) == 1
    rework(app, clock, rid, "문제인식")                                           # 다시 움직인다 → 새 기록
    assert app.store.load_run(rid).last_rework.status == "완료"
    clock.advance(days=LATER)
    assert retain(app, clock).summary.runs == 1
    assert [r.part for r in app.store.log_stats("실행")] == [1, 2]
    assert app.store.load_run(rid).stats_parts == 2
    assert app.store.log_stats("실행")[1].data["tasks"]["T-W1"]["runs"]["재작성"] == 1


def test_results_unchanged_after_retention(clock):
    """화면 10 문장 비교 · 지금까지 결과 · 재작성 결과가 기록을 옮긴 뒤에도 같다."""
    app = make_app(clock, StubScenario(tp1_targets=4))
    done = to_screen9(app, "acc-1")
    finish(app, done)
    app2 = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    reworked = to_screen9(app2, "acc-2")
    rework(app2, clock, reworked, "문제인식")
    clock.advance(days=LATER)
    p, p2 = pid(app, done), pid(app2, reworked)

    def snapshot():
        return (app.orchestrator.screen(p, 10).dump(), app.orchestrator.screen(p, 11).dump(),
                app.orchestrator.outputs(p).dump(), asdict(app.orchestrator.view(done)),
                app2.orchestrator.rework_result(p2).dump(), app2.orchestrator.outputs(p2).dump(),
                app2.orchestrator.screen(p2, 9).dump())
    before = snapshot()
    assert any(s["adopted"] for s in before[0]["sentences"])
    assert retain(app, clock).summary.runs == 1 and retain(app2, clock).summary.runs == 1
    assert record_counts(app, done) == [0] * 6 and record_counts(app2, reworked) == [0] * 6
    assert snapshot() == before


# ── 완전 삭제된 실행 건 ──────────────────────────────────
def test_permanently_deleted_run_row_removed_with_category_in_row(clock):
    app = make_app(clock, StubScenario(category="원페이지"))
    rid = to_screen6(app)
    project = pid(app, rid)
    app.orchestrator.delete_project_data(project)
    assert not app.store.get_pointers(rid) and any(record_counts(app, rid)[:1])  # 산출물만 지워졌다
    assert app.orchestrator.missing_projects([project]) == []                    # 실행 건 줄이 남아 있음
    clock.advance(days=LATER)
    out = retain(app, clock)
    assert (out.summary.runs, out.summary.deleted_runs, out.summary.skipped) == (1, 1, 0)
    with pytest.raises(KeyError):
        app.store.load_run(rid)                                                  # 실행 건 줄도 지웠다
    assert app.store.find_run_by_project(project) is None
    assert app.orchestrator.missing_projects([project, int(project)]) == [project]   # 이제 없음
    assert record_counts(app, rid) == [0] * 6
    [row] = app.store.log_stats("실행")
    assert (row.category, row.part, row.data["finalScores"]) == (
        "원페이지", 1, {"doc": None, "artifact": None, "total": None})


def test_deleted_run_with_nothing_to_move_writes_no_row(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    app.orchestrator.delete_project_data(pid(app, rid))
    assert app.store.acquire(rid, "earlier", 60)                                 # 이전에 기록만 옮긴 것처럼
    app.store.retire_run(rid, "earlier")
    app.store.release(rid, "earlier")
    clock.advance(days=LATER)
    out = retain(app, clock)
    assert (out.summary.runs, out.summary.deleted_runs) == (0, 1)
    assert app.store.log_stats("실행") == []
    with pytest.raises(KeyError):
        app.store.load_run(rid)


# ── 시작 요청 ──────────────────────────────────────────
def test_finished_start_requests_counted_and_deleted(clock):
    app = make_app(clock)
    for acc in ("acc-1", "acc-2"):
        assert app.orchestrator.start_run(acc, pre_input(), project_id=project_for(app)).ok
    app.llm.plan("T-C1", ["auth"] * 20)
    failed = app.orchestrator.start_run("acc-3", pre_input(), project_id=project_for(app))
    assert not failed.ok
    app.llm.plan("T-C1", [])
    old = [r for acc in ("acc-1", "acc-2", "acc-3") for r in app.store.list_start_requests(acc)]
    assert sorted(r.status for r in old) == ["실패", "완료", "완료"]
    clock.advance(days=LATER)
    assert app.orchestrator.start_run("acc-4", pre_input(), project_id=project_for(app)).ok   # 최근 요청은 남는다
    out = retain(app, clock, batch_size=2)                                       # 묶음 둘로
    assert out.summary.requests == 3
    for acc in ("acc-1", "acc-2", "acc-3"):
        assert app.store.list_start_requests(acc) == []
    assert len(app.store.list_start_requests("acc-4")) == 1
    rows = app.store.log_stats("시작요청")
    assert sum(r.count for r in rows) == 3 and {r.reason for r in rows} == {"12개월"}
    by_status = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + r.count
        assert r.month == kst_month(old[0].created_at) and r.category is None and r.data is None
    assert by_status == {"완료": 2, "실패": 1}


# ── 작업 점유 ──────────────────────────────────────────
def test_job_runs_on_one_worker_and_not_again_within_interval(clock):
    app = make_app(clock)
    assert start_retention(app.store, "a", 60)
    assert not start_retention(app.store, "b", 60)                               # 두 워커가 함께 시작하지 않는다
    assert not start_retention(app.store, "a", 60)
    out = run_retention(app.store, "a", now=clock(), lease_sec=60)
    assert out.finished
    job = app.store.get_job(JOB_NAME)
    assert job.lease_owner is None and job.last_finished_at is not None
    assert job.last_summary == {"runs": 0, "deletedRuns": 0, "requests": 0, "skipped": 0}
    assert not start_retention(app.store, "b", 60)                               # 24시간 안에는 다시 돌지 않는다
    clock.advance(hours=23, minutes=59)
    assert not start_retention(app.store, "b", 60)
    clock.advance(minutes=2)
    assert start_retention(app.store, "b", 60)


def test_stop_signal_releases_without_finishing_and_next_run_continues(clock):
    app = make_app(clock)
    rids = [to_screen6(app, f"acc-{i}") for i in range(3)]
    clock.advance(days=LATER)
    out = retain(app, clock, "a", stop=lambda: len(app.store.log_stats("실행")) >= 1, batch_size=1)
    assert not out.finished and out.summary.runs == 1
    job = app.store.get_job(JOB_NAME)
    assert job.last_finished_at is None and job.lease_owner is None              # 마친 시각은 쓰지 않고 점유만 푼다
    assert start_retention(app.store, "b", 60)                                    # 바로 다시 (남은 것부터)
    out = run_retention(app.store, "b", now=clock(), lease_sec=60)
    assert out.finished and out.summary.runs == 2
    assert all(record_counts(app, r) == [0] * 6 for r in rids)
    assert len(app.store.log_stats("실행")) == 3


def test_expired_job_lease_taken_over_by_other_worker(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    clock.advance(days=LATER)
    assert start_retention(app.store, "dead", 60)                                 # 잡은 뒤 죽은 워커
    assert not start_retention(app.store, "alive", 60)
    clock.advance(seconds=61)
    assert start_retention(app.store, "alive", 60)
    late = run_retention(app.store, "dead", now=clock(), lease_sec=60)           # 점유를 잃은 쪽은 아무것도 하지 않는다
    assert not late.finished and late.summary.as_dict() == dict.fromkeys(SUMMARY_KEYS, 0)
    assert any(record_counts(app, rid))
    out = run_retention(app.store, "alive", now=clock(), lease_sec=60)
    assert out.finished and out.summary.runs == 1
    assert app.store.get_job(JOB_NAME).lease_owner is None


def test_failed_run_rolls_back_only_that_run(clock):
    app = make_app(clock)
    rids = [to_screen6(app, f"acc-{i}") for i in range(3)]
    clock.advance(days=LATER)
    retire = app.store.retire_run
    failing = rids[0]

    def broken(run_id, owner, **kw):
        if run_id == failing:
            raise RuntimeError(f"DB 끊김 {run_id}")
        return retire(run_id, owner, **kw)
    app.store.retire_run = broken
    lines: list[str] = []
    out = retain(app, clock, log=lines.append, batch_size=1)
    assert out.finished and (out.summary.runs, out.summary.skipped) == (2, 1)
    assert any(record_counts(app, failing)) and app.store.load_run(failing).stats_parts == 0
    assert not app.store.is_locked(failing, clock())                             # 실행 건 점유 다시 잡기를 타지 않는다
    assert lines == ["보관 작업 오류 실행 건 RuntimeError"]                        # 오류 종류만
    app.store.retire_run = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("늘 실패"))
    clock.advance(hours=25)
    out = retain(app, clock, batch_size=1)                                       # 계속 실패해도 한 바퀴에서 끝난다
    assert out.finished and out.summary.skipped == 1 and out.summary.runs == 0


# ── 식별자 · 자유 글 없음 ─────────────────────────────────
def test_rows_summary_and_logs_carry_no_identifiers(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    accounts = ("acct-MARKER-1", "acct-MARKER-2")
    live = to_screen6(app, accounts[0])
    rework(app, clock, live, "문제인식")
    gone = to_screen6(app, accounts[1])
    app.orchestrator.delete_project_data(pid(app, gone))
    markers = [*accounts, live, gone, "헬스장", "김서준", "A01"]
    markers += [r.execution_id for rid in (live, gone) for r in app.store.executions(rid)]
    markers += [r.request_id for acc in accounts for r in app.store.list_start_requests(acc)]
    markers += [p for p in (pid(app, live),) if len(str(p)) >= 4]
    clock.advance(days=LATER)
    lines: list[str] = []
    out = retain(app, clock, log=lines.append)
    assert out.summary.as_dict() == {"runs": 2, "deletedRuns": 1, "requests": 2, "skipped": 0}
    text = json.dumps([asdict(r) for r in app.store.log_stats()], default=str, ensure_ascii=False)
    text += json.dumps(app.store.get_job(JOB_NAME).last_summary, ensure_ascii=False) + "\n".join(lines)
    assert [m for m in markers if m in text] == []
