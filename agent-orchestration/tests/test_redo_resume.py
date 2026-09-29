"""재수행 루프 · 재개 · 실패 처리 · 불변 산출물 · 규칙 단계 오류."""
from __future__ import annotations

from datetime import timedelta

from conftest import executed, make_app, start_and_select, to_screen6

from sbrain.agents.stubs import StubScenario


def test_redo_loop_counts_and_marks_final_attempt(clock):
    app = make_app(clock, StubScenario(check_fail_times={"T-S1": 3}))
    rid = to_screen6(app)
    recs = [r for r in app.store.executions(rid) if r.task_id == "T-S1"]
    assert [r.trigger for r in recs] == ["첫실행", "재수행", "재수행"]
    assert [r.redo_count for r in recs] == [0, 1, 2]
    ctx = app.engine.open_context(app.store.load_run(rid))
    ri1, ri2 = ctx.get("T-S1.reworkInput", 1), ctx.get("T-S1.reworkInput", 2)
    assert (ri1.mode, ri1.is_final_attempt, ri2.is_final_attempt) == ("재수행", False, True)
    assert ri1.previous_result_ref == recs[0].result_ref
    last_check = ctx.get("T-S1.check")
    assert not last_check.passed and last_check.final_action == "itemSpec.coreFeatures 승계"
    # 피드백 전달: check@n → 다음 실행
    fb = [f for f in app.store.feedback(rid) if f.target_task_id == "T-S1"]
    assert [(f.source_execution_id, f.target_execution_id) for f in fb] == [
        (recs[0].execution_id, recs[1].execution_id), (recs[1].execution_id, recs[2].execution_id)]
    assert fb[0].source_refs == ["T-S1.check@1"] and fb[0].via_ref == "T-S1.reworkInput@1"
    assert recs[1].feedback_in == [fb[0].feedback_id]
    assert "T-S1.reworkInput@1" in recs[1].inputs


def test_missing_final_action_is_recorded(clock):
    app = make_app(clock, StubScenario(check_fail_times={"T-S2": 3}, omit_final_action={"T-S2"}))
    rid = to_screen6(app)
    assert any(e.kind == "확정동작누락" for e in app.store.events(rid))


def test_non_exception_task_sends_as_is(clock):
    app = make_app(clock, StubScenario(check_fail_times={"T-B1": 5}))
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    assert executed(app, rid).count("T-B1") == 3  # 첫 실행 + 재수행 2회 뒤 그대로 보냄
    assert app.store.load_run(rid).state.step == "산출물확인"
    assert not any(e.kind == "확정동작누락" for e in app.store.events(rid))


def test_resume_after_retries_then_success(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-S2", ["timeout"] * 6)  # 재시도 5회까지 모두 실패
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.state.screen_status, run.current_task) == ("재개대기", "진행 중", "T-S2")
    assert run.resume_count == 1 and run.retry_count == 5 and run.last_error_kind == "일시"
    assert run.next_resume_at - clock.t < timedelta(minutes=15, seconds=1)
    assert app.orchestrator.tick(clock.t) == []  # 아직 시각 전
    clock.advance(minutes=16)
    assert app.orchestrator.tick(clock.t) == [rid]
    run = app.store.load_run(rid)
    assert run.state.step == "문서평가" and run.resume_count == 0
    ts2 = [r for r in app.store.executions(rid) if r.task_id == "T-S2"]
    assert len(ts2) == 1 and ts2[0].resume_count == 1 and ts2[0].status == "성공"  # 재개는 같은 시도를 이어 쓴다
    calls = [c for c in app.store.call_logs(rid) if c.task_id == "T-S2"]
    assert [len(c.tries) for c in calls] == [6, 1]  # 재시도는 호출 로그에만, 새 버전 없음


def test_resume_intervals_double_and_limit_fails_run(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-S1", ["timeout"] * 200)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    waits = []
    for _ in range(5):
        run = app.store.load_run(rid)
        assert run.state.progress == "재개대기"
        waits.append(run.next_resume_at - clock.t)
        clock.t = run.next_resume_at + timedelta(seconds=1)
        app.orchestrator.tick(clock.t)
    assert [round(w.total_seconds() / 60) for w in waits] == [15, 30, 60, 120, 240]
    run = app.store.load_run(rid)
    assert run.state.progress == "실패" and not run.admin_alert
    kinds = [(n.kind, n.failure_scope, n.target_step) for n in app.store.notifications(rid)]
    assert kinds[-1] == ("실패", "실행", None)
    assert run.notices[-1].code == "E-RUN-FAIL"


def test_permanent_error_fails_immediately_with_admin_alert(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-C3", ["auth"] * 6)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "실패" and run.admin_alert and run.last_error_kind == "운영"


def test_feature_list_is_immutable(clock):
    app = make_app(clock, StubScenario(tw1_change_features=True))
    rid = to_screen6(app)
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.version("featureList") == 1 and "임의 기능" not in ctx.get("featureList")
    assert any(e.kind == "불변산출물변경시도" for e in app.store.events(rid))


def test_g04_error_continues_but_merge_error_fails(clock):
    app = make_app(clock, StubScenario(raise_in={"G-04"}))
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.step == "산출물확인"  # G-04 실패는 계속 진행 (해당 검증 항목만 미충족)
    assert any(e.kind == "단계오류계속" for e in app.store.events(rid))

    app = make_app(clock, StubScenario(raise_in={"M-1"}))
    rid = start_and_select(app, account="acc-2")
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "실패" and run.admin_alert  # 합치기 오류 → 운영 오류 → 실행 실패 (잠정)
