"""탈퇴 (delete_account_data, 확장) — 계정의 orch_ 데이터를 통계 줄로 옮긴 뒤 모두 지운다.

웹 순서: 프로젝트마다 abort_project → delete_project_data → delete_account_data → 웹 행 삭제.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict

import pytest
from conftest import TIMING, make_app, pre_input, start_and_select, to_screen6

from sbrain.bootstrap import build_web
from sbrain.flow.service import AccountDeleteResult
from sbrain.orchestrator.errors import CommandError
from sbrain.orchestrator.store import StartRequest
from sbrain.store_sql import SqlStore, create_orchestrator_tables, create_sqlite_engine

ACCT = "acct-WITHDRAW-MARKER"
OTHER = "acct-OTHER-MARKER"


def finished_run(app, account: str = ACCT) -> str:
    """사용자대기까지 간 실행 건을 중단해 끝낸다 (완전 삭제는 하지 않음 — 산출물이 남는다)."""
    rid = to_screen6(app, account)
    app.orchestrator.abort_project(app.store.load_run(rid).project_id)
    assert app.store.load_run(rid).state.progress == "중단"
    return rid


def waiting_request(app, clock, account: str = ACCT, request_id: str = "req-WAIT-MARKER") -> str:
    now = clock()
    req = StartRequest(request_id=request_id, project_id=None, account_id=account, status="대기",
                       form=pre_input().dump(), created_at=now, updated_at=now)
    assert app.store.add_start_request(req) is None
    return request_id


def gone(app, rid: str) -> bool:
    """실행 건 줄 · 산출물 · 여섯 기록이 모두 없다."""
    with pytest.raises(KeyError):
        app.store.load_run(rid)
    return (app.store.get_pointers(rid) == {} and app.store.get_latest_versions(rid) == {}
            and app.store.executions(rid) == [] and app.store.call_logs(rid) == []
            and app.store.events(rid) == [] and app.store.feedback(rid) == []
            and app.store.comparisons(rid) == [] and app.store.pointer_events(rid) == [])


def stats_text(app) -> str:
    return json.dumps([asdict(r) for r in app.store.log_stats()], ensure_ascii=False, default=str)


def execution_ids(app, rid: str) -> list[str]:
    return [r.execution_id for r in app.store.executions(rid)]


# ── 지우기 ─────────────────────────────────────────────
def test_delete_account_moves_to_stats_and_deletes_all(clock):
    app = make_app(clock)
    rid1 = finished_run(app)                                   # 끝난 실행 건 (산출물이 남아 있음 — 웹이 완전 삭제를 빠뜨림)
    rid2 = start_and_select(app, ACCT)                         # 진행 중 (사용자대기) → 바로 중단
    other = start_and_select(app, OTHER)
    other_before = (len(app.store.executions(other)), app.store.get_pointers(other))
    reqs = [r.request_id for r in app.store.list_start_requests(ACCT)]
    ids = [rid1, rid2, *reqs, *execution_ids(app, rid1), *execution_ids(app, rid2)]
    assert len(reqs) == 2 and app.store.get_pointers(rid1)

    res = app.orchestrator.delete_account_data(ACCT)

    assert isinstance(res, AccountDeleteResult)
    assert (res.account_id, res.cancelled_requests, res.aborted_runs) == (ACCT, [], [rid2])
    assert (res.deleted_runs, res.deleted_requests, res.stats_rows) == (2, 2, 3)
    assert gone(app, rid1) and gone(app, rid2)
    assert app.store.list_runs(ACCT) == [] and app.store.list_start_requests(ACCT) == []
    run_rows, req_rows = app.store.log_stats("실행"), app.store.log_stats("시작요청")
    assert [(r.reason, r.status) for r in run_rows] == [("탈퇴", "중단"), ("탈퇴", "중단")]
    assert [(r.reason, r.status, r.count) for r in req_rows] == [("탈퇴", "완료", 2)]
    text = stats_text(app)                                     # 통계 줄에 식별자가 없다
    assert ACCT not in text and not [i for i in ids if i in text]
    # 다른 계정은 그대로
    assert (len(app.store.executions(other)), app.store.get_pointers(other)) == other_before
    assert app.store.load_run(other).state.progress == "사용자대기"
    assert len(app.store.list_start_requests(OTHER)) == 1


def test_waiting_request_is_cancelled_and_counted(clock):
    app = make_app(clock)
    req = waiting_request(app, clock)
    res = app.orchestrator.delete_account_data(ACCT)
    assert (res.cancelled_requests, res.aborted_runs, res.deleted_runs, res.deleted_requests, res.stats_rows) == (
        [req], [], 0, 1, 1)
    assert app.store.list_start_requests(ACCT) == []
    assert [(r.kind, r.reason, r.status) for r in app.store.log_stats()] == [("시작요청", "탈퇴", "취소")]


def test_permanently_deleted_run_and_run_without_records(clock):
    """완전 삭제된 실행 건(산출물 없음)과 기록을 이미 옮긴 실행 건(기록 없음)도 지운다. 기록이 없으면 실행 줄을 쓰지 않는다."""
    app = make_app(clock)
    deleted = to_screen6(app, ACCT)
    app.orchestrator.delete_project_data(app.store.load_run(deleted).project_id)   # 웹 순서대로 완전 삭제
    assert not app.store.has_pointers(deleted)
    empty = finished_run(app)
    assert app.store.acquire(empty, "retention", 60)
    app.store.retire_run(empty, "retention")                                      # 기록만 옮겨 지운 상태
    app.store.release(empty, "retention")
    res = app.orchestrator.delete_account_data(ACCT)
    assert (res.deleted_runs, res.deleted_requests) == (2, 2)
    assert res.stats_rows == 1 + 1                             # 실행 줄은 기록이 있는 쪽만 + 시작요청 줄 1
    assert len(app.store.log_stats("실행")) == 1
    assert gone(app, deleted) and gone(app, empty)


def test_calling_again_returns_all_zero(clock):
    app = make_app(clock)
    finished_run(app)
    app.orchestrator.delete_account_data(ACCT)
    stats = len(app.store.log_stats())
    again = app.orchestrator.delete_account_data(ACCT)
    assert again == AccountDeleteResult(ACCT, [], [], 0, 0, 0)
    assert len(app.store.log_stats()) == stats
    assert app.orchestrator.delete_account_data("acct-NEVER-SEEN") == AccountDeleteResult("acct-NEVER-SEEN",
                                                                                         [], [], 0, 0, 0)


def test_run_deleted_after_listing_is_skipped_not_counted(clock):
    """목록을 읽은 뒤 다른 곳(보관 기간 작업)이 먼저 지운 실행 건은 세지 않고 건너뛴다 — 메모리 · SQL 저장소 모두."""
    app = make_app(clock)
    victim = finished_run(app)
    kept = finished_run(app)
    list_runs = app.store.list_runs
    calls = {"n": 0}

    def hooked(account_id):
        runs = list_runs(account_id)
        calls["n"] += 1
        if calls["n"] == 2:                                       # ⑤의 목록을 읽은 직후, 처리 전에 다른 곳이 지운다
            assert app.store.acquire(victim, "retention", 60)
            app.store.retire_run(victim, "retention", delete_run=True)
            app.store.release(victim, "retention")
        return runs
    app.store.list_runs = hooked
    res = app.orchestrator.delete_account_data(ACCT)
    assert calls["n"] == 2
    assert (res.deleted_runs, res.deleted_requests, res.stats_rows) == (1, 2, 2)
    assert len(app.store.log_stats("실행")) == 1
    assert gone(app, victim) and gone(app, kept)


# ── BUSY ──────────────────────────────────────────────
def busy(app, account: str = ACCT) -> CommandError:
    with pytest.raises(CommandError) as e:
        app.orchestrator.delete_account_data(account)
    assert e.value.code == "BUSY"
    return e.value


def no_ids(err: CommandError, *ids: str) -> bool:
    return not [i for i in ids if i in str(err)]


def test_processing_request_is_busy_and_leaves_cancel_request(clock):
    app = make_app(clock)
    rid = finished_run(app)
    req = waiting_request(app, clock)
    assert app.store.acquire_start_request(req, "worker-1", 60)                     # 워커가 처리 중
    err = busy(app)
    assert no_ids(err, ACCT, req, rid)
    assert app.store.get_start_request(req).cancel_requested                         # 취소 요청은 남는다
    assert app.store.has_pointers(rid) and app.store.executions(rid)                 # 아무것도 지우지 않았다
    assert app.store.log_stats() == [] and len(app.store.list_start_requests(ACCT)) == 2
    st = app.orchestrator.run_start_request(req, owner="worker-1")                   # 워커가 만들기 직전에 취소
    assert (st.status, st.run_id) == ("취소", None)
    res = app.orchestrator.delete_account_data(ACCT)                                 # 다시 부르면 지운다
    assert (res.deleted_runs, res.deleted_requests) == (1, 2) and gone(app, rid)


def test_step_running_is_busy_and_leaves_abort_request(clock):
    app = make_app(clock)
    rid = start_and_select(app, ACCT)
    app.orchestrator.start_writing(rid)                                               # '실행'
    assert app.store.acquire(rid, "worker", 60)                                       # 워커가 단계를 도는 중
    err = busy(app)
    assert no_ids(err, ACCT, rid)
    assert app.store.is_abort_requested(rid) and app.store.has_pointers(rid)
    assert app.store.log_stats() == [] and app.store.list_start_requests(ACCT)
    app.store.release(rid, "worker")
    app.orchestrator.advance(rid)                                                     # 단계 사이에서 중단 반영
    assert app.store.load_run(rid).state.progress == "중단"
    res = app.orchestrator.delete_account_data(ACCT)
    assert (res.aborted_runs, res.deleted_runs, res.deleted_requests) == ([], 1, 1) and gone(app, rid)


def test_leased_finished_run_is_busy_and_resumes_from_rest(clock):
    """끝난 실행 건이라도 점유를 못 잡으면 BUSY. 이미 처리한 실행 건은 지워진 채로 두고, 다시 부르면 남은 것부터 한다."""
    app = make_app(clock)
    first = finished_run(app)
    second = finished_run(app)
    assert app.store.acquire(second, "retention", 60)                                 # 다른 곳이 점유 중
    err = busy(app)
    assert no_ids(err, ACCT, first, second)
    assert gone(app, first)                                                           # 먼저 처리한 것은 지워졌다
    assert app.store.has_pointers(second) and len(app.store.list_start_requests(ACCT)) == 2
    assert len(app.store.log_stats("실행")) == 1 and app.store.log_stats("시작요청") == []
    app.store.release(second, "retention")
    res = app.orchestrator.delete_account_data(ACCT)
    assert (res.deleted_runs, res.deleted_requests, res.stats_rows) == (1, 2, 2) and gone(app, second)
    assert len(app.store.log_stats("실행")) == 2


@TIMING
def test_account_lock_timeout_is_busy(clock):
    app = make_app(clock)
    rid = finished_run(app)
    app.store.account_lock_timeout = 0.05
    held, done = threading.Event(), threading.Event()

    def hold():
        with app.store.account_guard(ACCT):
            held.set()
            done.wait(5)
    t = threading.Thread(target=hold)
    t.start()
    try:
        assert held.wait(5)
        err = busy(app)
        assert no_ids(err, ACCT, rid) and err.__cause__ is None
        assert app.store.has_pointers(rid) and app.store.log_stats() == []
    finally:
        done.set()
        t.join(5)


# ── 계정 잠금 ─────────────────────────────────────────
@TIMING
def test_start_request_cannot_slip_in_while_deleting(clock):
    """함수가 끝날 때까지 같은 계정의 add_start_request는 계정 잠금을 기다린다 — 지우는 도중에 새 요청이 끼어들지 않는다."""
    app = make_app(clock)
    rid = finished_run(app)
    list_runs = app.store.list_runs
    seen: dict[str, object] = {}

    def add():
        now = clock()
        req = StartRequest(request_id="req-LATE", project_id=None, account_id=ACCT, status="대기",
                           form=pre_input().dump(), created_at=now, updated_at=now)
        seen["result"] = app.store.add_start_request(req)

    def hooked(account_id):
        if "thread" not in seen:                                  # 함수 안(계정 잠금을 잡은 뒤)에서 다른 스레드가 요청을 넣는다
            t = threading.Thread(target=add)
            seen["thread"] = t
            t.start()
            t.join(0.3)
            seen["alive_inside"] = t.is_alive()
        return list_runs(account_id)
    app.store.list_runs = hooked
    res = app.orchestrator.delete_account_data(ACCT)
    t = seen["thread"]
    t.join(10)
    assert seen["alive_inside"] is True                           # 함수 안에서는 기다렸다
    assert not t.is_alive() and seen["result"] is None            # 끝난 뒤에 들어갔다
    assert (res.deleted_runs, res.deleted_requests) == (1, 1) and gone(app, rid)
    assert [r.request_id for r in app.store.list_start_requests(ACCT)] == ["req-LATE"]   # 뒤에 온 요청은 남는다


# ── 웹 조립 ───────────────────────────────────────────
def test_web_assembly_can_call(tmp_path):
    from webdb import create_web_tables
    path = tmp_path / "web.db"
    engine = create_sqlite_engine(path, fast=True)
    create_orchestrator_tables(engine)
    create_web_tables(engine)
    web = build_web(f"sqlite:///{path.as_posix()}", profile_count=lambda a: 1)
    assert isinstance(web.store, SqlStore)
    assert web.orchestrator.delete_account_data("acct-EMPTY") == AccountDeleteResult("acct-EMPTY", [], [], 0, 0, 0)
