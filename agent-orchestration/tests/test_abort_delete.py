"""project_id로 중단(abort_project) · 완전 삭제(delete_project_data)."""
from __future__ import annotations

import pytest
from conftest import make_app, project_record, start_and_select, to_screen6, to_screen9

from sbrain.intake import MemoryProjectInputSource
from sbrain.orchestrator.errors import CommandError


def app_with_project(clock):
    return make_app(clock, project_inputs=MemoryProjectInputSource([project_record()]))


def logs(app, rid: str) -> tuple[int, int, int]:
    return len(app.store.executions(rid)), len(app.store.call_logs(rid)), len(app.store.events(rid))


# ── 중단 ──────────────────────────────────────────────
def test_abort_waiting_request(clock):
    app = app_with_project(clock)
    check = app.orchestrator.request_start("7", 101)
    res = app.orchestrator.abort_project(101)
    assert (res.cancelled_requests, res.cancel_requested, res.run_id) == ([check.request_id], [], None)
    assert app.orchestrator.start_status(101).status == "취소"
    assert app.orchestrator.run_start_request(check.request_id).status == "취소"
    assert app.store.list_runs("7") == [] and app.llm.requests == []


def test_abort_processing_request_stops_before_run(clock):
    app = app_with_project(clock)
    check = app.orchestrator.request_start("7", 101)
    assert app.store.acquire_start_request(check.request_id, "worker-1", 60)   # 워커가 처리 중
    res = app.orchestrator.abort_project(101)
    assert (res.cancelled_requests, res.cancel_requested) == ([], [check.request_id])
    st = app.orchestrator.run_start_request(check.request_id, owner="worker-1")
    assert (st.status, st.run_id) == ("취소", None) and app.store.list_runs("7") == []


def test_abort_running_run_leaves_request_between_steps(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.orchestrator.start_writing(rid)                                          # '실행'
    assert app.store.acquire(rid, "worker", 60)                                  # 워커가 단계를 도는 중
    pid = app.store.load_run(rid).project_id
    res = app.orchestrator.abort_project(pid)
    assert (res.run_id, res.run_action) == (rid, "중단요청") and app.store.is_abort_requested(rid)
    app.store.release(rid, "worker")
    app.orchestrator.advance(rid)                                                # 단계 사이에서 반영
    assert app.store.load_run(rid).state.progress == "중단"


def test_abort_user_waiting_and_already_ended(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    pid = app.store.load_run(rid).project_id
    res = app.orchestrator.abort_project(pid)
    assert res.run_action == "중단" and app.store.load_run(rid).state.progress == "중단"
    again = app.orchestrator.abort_project(pid)
    assert again.run_action == "이미끝남"                                        # 이미 끝난 실행 건은 그대로
    assert app.orchestrator.abort_project("424242").run_id is None              # 실행 건 · 요청 없음


# ── 완전 삭제 ──────────────────────────────────────────
def test_delete_removes_artifacts_and_forms_keeps_logs(clock):
    app = app_with_project(clock)
    st = app.orchestrator.run_start_request(app.orchestrator.request_start("7", 101).request_id)
    rid = st.run_id
    app.orchestrator.select_announcement(rid, "A01")
    app.orchestrator.advance(rid)
    before = logs(app, rid)
    res = app.orchestrator.delete_project_data(101)
    assert (res.run_id, res.deleted_artifacts, res.cleared_forms, res.abort.run_action) == (rid, True, 1, "중단")
    assert app.store.get_pointers(rid) == {} and app.store.get_latest_versions(rid) == {}   # 산출물 · 입력 사본
    assert app.store.get_start_request(st.request_id).form is None
    after = logs(app, rid)
    assert after[:2] == before[:2] and after[2] == before[2] + 1               # 실행 로그는 남는다 (+ '중단' 사건)
    run = app.store.load_run(rid)
    assert run.state.progress == "중단" and app.orchestrator.view_project(101).run.progress == "중단"


def test_delete_while_step_running_is_busy(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.orchestrator.start_writing(rid)
    assert app.store.acquire(rid, "worker", 60)
    pid = app.store.load_run(rid).project_id
    with pytest.raises(CommandError) as e:
        app.orchestrator.delete_project_data(pid)
    assert e.value.code == "BUSY" and app.store.get_pointers(rid)              # 아직 지우지 않았다
    app.store.release(rid, "worker")
    app.orchestrator.advance(rid)                                                # 워커가 중단을 반영
    res = app.orchestrator.delete_project_data(pid)                              # 다시 부르면 지운다
    assert res.deleted_artifacts and res.abort.run_action == "이미끝남" and app.store.get_pointers(rid) == {}


def test_delete_completed_project(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    pid = app.store.load_run(rid).project_id
    res = app.orchestrator.delete_project_data(pid)
    assert res.abort.run_action == "이미끝남" and res.deleted_artifacts
    assert app.store.load_run(rid).state.progress == "완료" and app.store.get_pointers(rid) == {}
    assert len(app.orchestrator.admin_executions(project_id=pid, limit=100)) == 23   # 관리자 실행 기록은 남는다
