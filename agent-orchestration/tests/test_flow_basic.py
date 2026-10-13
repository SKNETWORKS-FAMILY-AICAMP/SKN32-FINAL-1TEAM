"""기본 흐름 — 20단계 실행 순서, 카테고리 분기, 게이트, 사전 단계 오류, 동시 실행 제한."""
from __future__ import annotations

from conftest import executed, make_app, pre_input, start_and_select, to_screen6, to_screen8, to_screen9

from sbrain.agents.stubs import StubScenario
from sbrain.flow.catalog import build_registry


def run_to_end(app, rid):
    app.orchestrator.decide(rid, 9, "진행")
    app.orchestrator.advance(rid)


def test_web_full_flow_runs_all_steps_in_order(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    run_to_end(app, rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("결과물", "완료")
    assert executed(app, rid) == [
        "T-C1", "T-C2", "G-01", "T-C3", "T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "M-1", "T-V1", "G-02a",
        "T-B1", "T-B2", "G-04", "M-3", "T-V2", "G-02b", "G-03", "T-P1", "T-P2", "M-4", "T-C4"]
    counted = {s.task_id for s in build_registry().specs() if s.counted}
    assert len(counted & set(executed(app, rid))) == 14
    kinds = [n.kind for n in app.store.notifications(rid)]
    assert kinds == ["문서평가", "산출물확인", "표현검수"]


def test_onepage_skips_tb1_and_wraps_infographic(clock):
    app = make_app(clock, StubScenario(category="원페이지"))
    rid = to_screen9(app)
    run_to_end(app, rid)
    ex = executed(app, rid)
    assert "T-B1" not in ex and "M-2" in ex
    counted = {s.task_id for s in build_registry().specs() if s.counted}
    assert len(counted & set(ex)) == 13
    ctx = app.engine.open_context(app.store.load_run(rid))
    proto = ctx.get("prototype")
    assert proto.kind == "svg-onepage"
    assert proto.entry_file == ctx.get("infographic").image_file and proto.entry_file.name == "onepage.svg"
    assert proto.asset_files == [] and proto.readme_file == ctx.get("readmeFile")
    assert proto.readme_file.name == "README.md" and proto.readme_file.media_type == "text/markdown"


def test_states_at_wait_points(clock):
    app = make_app(clock)
    res = app.orchestrator.start_run("acc-1", pre_input())
    v = app.orchestrator.view(res.run_id)
    assert (v.step, v.progress, v.screen_status, v.resume_step) == ("공고선택", "사용자대기", "확인 필요", 3)
    app.orchestrator.select_announcement(res.run_id, "A01")
    app.orchestrator.advance(res.run_id)
    v = app.orchestrator.view(res.run_id)
    assert (v.step, v.progress, v.resume_step) == ("계획서작성", "사용자대기", 5)
    app.orchestrator.start_writing(res.run_id)
    assert app.orchestrator.view(res.run_id).current_label == "작업 분해"
    app.orchestrator.advance(res.run_id)
    v = app.orchestrator.view(res.run_id)
    assert (v.step, v.progress, v.resume_step) == ("문서평가", "사용자대기", 6)


def test_gate_fail_returns_to_selection_then_reselect(clock):
    app = make_app(clock, StubScenario(gate_fail_ids={"A01"}))
    rid = start_and_select(app, announcement="A01")
    v = app.orchestrator.view(rid)
    assert (v.step, v.progress) == ("공고선택", "사용자대기")
    assert v.notices[-1].code == "E-G1-REJECT"
    app.orchestrator.select_announcement(rid, "A02")
    app.orchestrator.advance(rid)
    assert app.orchestrator.view(rid).step == "계획서작성"
    assert executed(app, rid).count("G-01") == 2


def test_no_candidates_and_stale_collection(clock):
    app = make_app(clock, StubScenario(candidate_count=0))
    res = app.orchestrator.start_run("acc-1", pre_input())
    assert res.code == "E-C2-NOMATCH" and app.store.list_runs("acc-1") == []
    app = make_app(clock, StubScenario(collection_status="지연"))
    assert app.orchestrator.start_run("acc-1", pre_input()).code == "E-C2-STALE"


def test_concurrency_and_profile_block(clock):
    app = make_app(clock)
    first = app.orchestrator.start_run("acc-1", pre_input())
    second = app.orchestrator.start_run("acc-1", pre_input())
    assert second.code == "E-RUN-CONCURRENT" and second.active_run_id == first.run_id
    app2 = make_app(clock, profile_count=lambda a: 0)
    assert app2.orchestrator.start_run("acc-2", pre_input()).code == "E-AUTH-PROFILE"


def test_abort_between_tasks_and_completed_not_counted(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    assert app.orchestrator.abort(rid) is not None  # 확인 먼저
    app.orchestrator.abort(rid, confirmed=True)
    assert app.store.load_run(rid).state.progress == "중단"
    assert app.orchestrator.start_run("acc-1", pre_input()).ok  # 중단 건은 1건 제한에서 세지 않음


def test_abort_requested_while_running_applies_between_tasks(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.orchestrator.start_writing(rid)
    app.store.request_abort(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "중단"
    assert executed(app, rid)[-1] == "G-01"  # 작성 구간의 첫 Task 전에 멈춤


def test_proceed_below_threshold_needs_confirmation(clock):
    app = make_app(clock, StubScenario(doc_scores=[50.0], art_scores=[(10.0, 7.0)]))
    rid = to_screen9(app)
    need = app.orchestrator.decide(rid, 9, "진행")
    assert need is not None and set(need.items) == {"현재 점수", "기준", "남는 미달 항목", "되돌릴 수 없음"}
    assert app.store.load_run(rid).state.step == "종합평가"
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "완료"


def test_lock_prevents_parallel_advance(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.orchestrator.start_writing(rid)
    assert app.store.acquire(rid, "other-worker", 60)
    assert app.orchestrator.advance(rid) == "busy"
    app.store.release(rid, "other-worker")
    assert app.orchestrator.advance(rid) == "사용자대기"
