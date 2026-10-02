"""사전 단계 시작을 확인(request_start, 웹 요청 안)과 실행(run_start_request, 워커)으로 나누기."""
from __future__ import annotations

import pytest
from conftest import make_app, project_record

from sbrain.agents.stubs import StubScenario
from sbrain.flow import ActiveWork
from sbrain.intake import MemoryProjectInputSource
from sbrain.models import Run
from sbrain.models.run import make_state
from sbrain.orchestrator.errors import CommandError, message
from sbrain.orchestrator.store import CommitBatch


def project(pid: int, user: int = 7):
    return project_record(project={"project_id": pid}, company={"user_id": user})


def app_with(clock, *records, scenario: StubScenario | None = None, **kw):
    source = MemoryProjectInputSource(list(records) or [project(101)])
    return make_app(clock, scenario, project_inputs=source, **kw)


def test_request_then_worker_creates_run(clock):
    app = app_with(clock)
    check = app.orchestrator.request_start("7", 101)
    assert check.ok and check.request_id
    st = app.orchestrator.start_status(101)
    assert (st.status, st.run_id, st.code) == ("대기", None, None)
    assert app.store.get_start_request(check.request_id).form["ideaText"] == "동네 헬스장 회원 관리 서비스"
    assert app.store.list_runs("7") == [] and app.llm.requests == []       # 사전 단계는 워커가 돈다
    done = app.orchestrator.run_start_request(check.request_id, owner="worker-1")
    assert done.status == "완료" and done.run_id
    run = app.store.load_run(done.run_id)
    assert run.project_id == "101" and (run.state.step, run.state.progress) == ("공고선택", "사용자대기")
    assert app.orchestrator.start_status(101) == done
    assert app.orchestrator.run_start_request(check.request_id) == done      # 끝난 요청은 다시 돌지 않는다
    assert len(app.store.list_runs("7")) == 1


def test_required_items_are_listed_without_request(clock):
    app = app_with(clock, project_record(pricing_items=[], plan={"ceo_gender": None}))
    check = app.orchestrator.request_start("7", 101)
    assert (check.ok, check.code, check.missing) == (False, "E-C1-REQUIRED", ["수익모델 단가", "성별"])
    assert check.message == "필수 항목을 입력해주세요: 수익모델 단가, 성별"
    assert app.orchestrator.start_status(101) is None


def test_owner_and_profile_checks(clock):
    app = app_with(clock)
    with pytest.raises(CommandError, match="PROJECT_NOT_FOUND"):
        app.orchestrator.request_start("8", 101)                             # 다른 계정의 프로젝트
    app2 = app_with(clock, profile_count=lambda a: 0)
    assert app2.orchestrator.request_start("7", 101).code == "E-AUTH-PROFILE"
    assert app2.orchestrator.start_status(101) is None


def test_concurrent_start_reports_active_work(clock):
    app = app_with(clock, project(101), project(102))
    first = app.orchestrator.request_start("7", 101)
    blocked = app.orchestrator.request_start("7", 102)                       # 대기 중인 요청이 막는다
    assert (blocked.ok, blocked.code) == (False, "E-RUN-CONCURRENT")
    assert blocked.message == message("E-RUN-CONCURRENT")
    assert blocked.active == ActiveWork(project_id="101", request_id=first.request_id)
    st = app.orchestrator.run_start_request(first.request_id)
    blocked = app.orchestrator.request_start("7", 102)                       # 진행 중인 실행 건이 막는다
    assert blocked.active == ActiveWork(project_id="101", run_id=st.run_id, step="공고선택", resume_step=3,
                                        screen_status="확인 필요")
    assert app.orchestrator.start_status(102) is None


def test_started_project_cannot_start_again(clock):
    app = app_with(clock)
    st = app.orchestrator.run_start_request(app.orchestrator.request_start("7", 101).request_id)
    app.orchestrator.abort(st.run_id, confirmed=True)
    with pytest.raises(CommandError, match="PROJECT_ALREADY_STARTED"):     # 새로 시작은 새 프로젝트로
        app.orchestrator.request_start("7", 101)


def test_pre_stage_failure_fails_request_and_allows_retry(clock):
    app = app_with(clock)
    app.llm.plan("T-C1", ["timeout"] * 6)
    st = app.orchestrator.run_start_request(app.orchestrator.request_start("7", 101).request_id)
    assert (st.status, st.code, st.message) == ("실패", "E-C1-TIMEOUT", message("E-C1-TIMEOUT"))
    assert app.store.list_runs("7") == []
    retry = app.orchestrator.request_start("7", 101)                        # 실패한 요청은 막지 않는다
    assert retry.ok and app.orchestrator.run_start_request(retry.request_id).status == "완료"


def test_failure_keeps_notices(clock):
    app = app_with(clock, scenario=StubScenario(candidate_count=0, embed_fail=True))
    st = app.orchestrator.run_start_request(app.orchestrator.request_start("7", 101).request_id)
    assert (st.status, st.code) == ("실패", "E-C2-NOMATCH")
    assert [n.code for n in st.notices] == ["E-C2-EMBED"]
    app2 = app_with(clock, scenario=StubScenario(collection_status="지연"))
    assert app2.orchestrator.run_start_request(app2.orchestrator.request_start("7", 101).request_id).code == "E-C2-STALE"


def test_cancel_waiting_and_processing_requests(clock):
    app = app_with(clock, project(101), project(102))
    first = app.orchestrator.request_start("7", 101)
    assert app.store.cancel_start_request(first.request_id) == "취소"        # 대기 → 바로 취소
    assert app.orchestrator.run_start_request(first.request_id).status == "취소"
    assert app.llm.requests == []
    second = app.orchestrator.request_start("7", 102)                       # 취소된 요청은 막지 않는다
    assert second.ok
    assert app.store.acquire_start_request(second.request_id, "worker-1", 60)
    assert app.store.cancel_start_request(second.request_id) == "취소요청"   # 처리 중 → 취소 요청만
    st = app.orchestrator.run_start_request(second.request_id, owner="worker-1")
    assert (st.status, st.run_id) == ("취소", None) and app.store.list_runs("7") == []
    assert app.store.cancel_start_request(second.request_id) == ""           # 이미 끝남


def test_cancel_during_pre_stage_stops_before_run(clock):
    app = app_with(clock)
    check = app.orchestrator.request_start("7", 101)

    def cancel_while_running(_request):
        app.store.cancel_start_request(check.request_id)                    # 사전 단계 도중 취소
        return '{"ok": true}'
    app.llm.respond("T-C1", cancel_while_running)
    st = app.orchestrator.run_start_request(check.request_id)
    assert st.status == "취소" and app.store.list_runs("7") == []
    assert len(app.llm.requests) == 1                                        # 사전 단계는 돌았다


def test_lease_keeps_other_workers_out(clock):
    app = app_with(clock)
    check = app.orchestrator.request_start("7", 101)
    assert app.store.acquire_start_request(check.request_id, "worker-1", 60)
    st = app.orchestrator.run_start_request(check.request_id, owner="worker-2")
    assert st.status == "처리중" and app.llm.requests == []                   # 다른 워커가 처리 중
    clock.advance(seconds=61)
    st = app.orchestrator.run_start_request(check.request_id, owner="worker-2")   # 점유 만료 → 이어받음
    assert st.status == "완료"
    assert app.store.get_start_request(check.request_id).claim_count == 2


def test_run_created_elsewhere_fails_request(clock):
    """요청 처리 중에 같은 계정의 실행 건이 생기면 만들지 않고 E-RUN-CONCURRENT로 끝낸다."""
    app = app_with(clock)
    check = app.orchestrator.request_start("7", 101)
    other = Run(run_id="other-run", account_id="7", state=make_state("공고선택", "사용자대기"), current_phase="setup",
                settings_snapshot={}, updated_at=clock.t, created_at=clock.t)

    def create_other(_request):
        assert app.store.create_run(other, CommitBatch())                   # 다른 경로로 생긴 실행 건
        return '{"ok": true}'
    app.llm.respond("T-C1", create_other)
    st = app.orchestrator.run_start_request(check.request_id)
    assert (st.status, st.code, st.run_id) == ("실패", "E-RUN-CONCURRENT", None)
    assert st.active == ActiveWork(project_id=None, run_id="other-run", step="공고선택", resume_step=3,
                                   screen_status="확인 필요")
    assert [r.run_id for r in app.store.list_runs("7")] == ["other-run"]


def test_active_work_matches_request_start_counting(clock):
    """웹이 사전 정보를 저장하기 전에 보는 동시 실행 확인 — request_start와 같은 기준으로 센다."""
    app = app_with(clock, project(101), project(102), project(201, user=8))
    assert app.orchestrator.active_work("7") is None
    first = app.orchestrator.request_start("7", 101)
    work = app.orchestrator.active_work("7")                                 # 대기 중인 시작 요청
    assert work == ActiveWork(project_id="101", request_id=first.request_id)
    assert app.orchestrator.request_start("7", 102).active == work
    assert app.orchestrator.active_work("8") is None                         # 다른 계정은 따로 센다
    assert app.store.acquire_start_request(first.request_id, "worker-1", 60)
    assert app.orchestrator.active_work("7") == work                         # 처리중도 센다
    st = app.orchestrator.run_start_request(first.request_id, owner="worker-1")
    work = app.orchestrator.active_work("7")                                 # 확인 필요 실행 건
    assert work == ActiveWork(project_id="101", run_id=st.run_id, step="공고선택", resume_step=3,
                              screen_status="확인 필요")
    assert app.orchestrator.request_start("7", 102).active == work
    app.orchestrator.abort(st.run_id, confirmed=True)
    assert app.orchestrator.active_work("7") is None
    assert app.orchestrator.request_start("7", 102).ok
