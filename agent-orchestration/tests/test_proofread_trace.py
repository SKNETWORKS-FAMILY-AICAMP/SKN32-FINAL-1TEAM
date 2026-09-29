"""T-P2 문장 병렬 처리와 추적 기록 원칙."""
from __future__ import annotations

from conftest import executed, make_app, pre_input, to_screen9

from sbrain.agents.stubs import StubScenario
from sbrain.models import extension_fields
from sbrain.orchestrator.trace import ExecutionRecord


def run_review(app, rid):
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)


def sentence_results(app, rid):
    ctx = app.engine.open_context(app.store.load_run(rid))
    return {r.sentence_id: r for r in ctx.get("sentenceResults")}, ctx


def test_tp2_redo_early_stop_and_keep_original(clock):
    sc = StubScenario(tp1_targets=4, tp2_behavior={
        "s-1-1-1": ["ok"],
        "s-1-1-2": ["violate", "ok"],             # 1회 재수행 후 채택
        "s-2-1-1": ["violate", "same", "same"],   # 지시를 바꿔도 같은 출력 → 조기 중단
        "s-2-1-2": ["violate", "violate", "violate"],  # 검수 재수행 횟수 초과 → 원문 유지
    })
    app = make_app(clock, sc)
    rid = to_screen9(app)
    run_review(app, rid)
    res, ctx = sentence_results(app, rid)
    assert res["s-1-1-1"].adopted and res["s-1-1-1"].final_redo_count == 0
    assert res["s-1-1-2"].adopted and res["s-1-1-2"].final_redo_count == 1
    assert res["s-2-1-1"].kept_reason == "조기중단"
    assert (res["s-2-1-2"].kept_reason, res["s-2-1-2"].final_redo_count) == ("검증실패", 2)
    log = ctx.get("proofreadLog")
    assert log.adopted_count == 2 and log.early_stopped_sentence_ids == ["s-2-1-1"]
    assert log.retained_by_check_ids == ["s-2-1-2"] and log.token_preservation_rate == 0.25
    # 채택 문장만 계획서에 반영
    plan = ctx.get("planDoc")
    texts = {s.sentence_id: s.text for sec in plan.sections for s in sec.sentences}
    assert texts["s-1-1-1"].endswith("(윤문)") and not texts["s-2-1-2"].endswith("(윤문)")
    # 호출 로그는 문장별, 입력 · 출력 이력은 Task 단위
    tp2 = [r for r in app.store.executions(rid) if r.task_id == "T-P2"]
    assert len(tp2) == 1 and tp2[0].outputs == ["sentenceResults@1"]
    assert tp2[0].temperature <= 0.2
    calls = [c for c in app.store.call_logs(rid) if c.task_id == "T-P2"]
    assert {c.item_key for c in calls} == set(res)
    assert sum(1 for c in calls if c.item_key == "s-2-1-2") == 3  # 첫 호출 + 재수행 2회


def test_tp2_redo_hint_accumulates(clock):
    sc = StubScenario(tp1_targets=1, tp2_behavior={"s-1-1-1": ["violate", "violate", "ok"]})
    app = make_app(clock, sc)
    seen = []
    base = app.registry.get("T-P2").fn

    def spy(inp, tools):
        seen.append(list(inp.redo_hint))
        return base(inp, tools)
    app.registry.bind("T-P2", spy)
    rid = to_screen9(app)
    run_review(app, rid)
    assert seen == [[], ["'1억원' 유지"], ["'1억원' 유지"]]  # 교체하지 않고 누적 (같은 문구는 한 번)


def test_tp2_call_failures_keep_original_or_resume_by_ratio(clock):
    sc = StubScenario(tp1_targets=4)
    app = make_app(clock, sc)
    app.llm.plan("T-P2", ["timeout"] * 6, item_key="s-1-1-1")  # 1/4 = 25% ≤ 30% → 원문 유지하고 완료
    rid = to_screen9(app)
    run_review(app, rid)
    res, _ = sentence_results(app, rid)
    assert res["s-1-1-1"].kept_reason == "호출실패"
    assert app.store.load_run(rid).state.progress == "완료"

    app = make_app(clock, StubScenario(tp1_targets=4))
    for sid in ("s-1-1-1", "s-1-1-2"):
        app.llm.plan("T-P2", ["timeout"] * 6, item_key=sid)  # 2/4 = 50% > 30% → 재개
    rid = to_screen9(app, account="acc-2")
    run_review(app, rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기" and run.state.step == "표현검수"
    clock.advance(minutes=16)
    app.orchestrator.tick(clock.t)
    res, _ = sentence_results(app, rid)
    assert all(r.adopted for r in res.values())  # 실패한 문장만 다시 처리
    assert app.store.load_run(rid).state.progress == "완료"
    tp2 = [r for r in app.store.executions(rid) if r.task_id == "T-P2"]
    assert len(tp2) == 1 and tp2[0].resume_count == 1


def test_tp2_skipped_when_no_tokens(clock):
    app = make_app(clock, StubScenario(no_tokens=True))
    rid = to_screen9(app)
    run_review(app, rid)
    tp2 = [r for r in app.store.executions(rid) if r.task_id == "T-P2"][0]
    assert tp2.status == "생략" and "보호 토큰" in tp2.output_meta.note
    assert app.store.load_run(rid).state.progress == "완료"


def test_trace_covers_rule_and_merge_steps_without_content(clock):
    app = make_app(clock)
    res = app.orchestrator.start_run("acc-1", pre_input())
    rid = res.run_id
    app.orchestrator.select_announcement(rid, "A01")
    app.orchestrator.advance(rid)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    recs = {r.task_id: r for r in app.store.executions(rid)}
    for tid in ("G-01", "M-1", "G-02a"):
        assert recs[tid].step_kind in ("rule", "merge") and recs[tid].model is None
        assert recs[tid].inputs and recs[tid].outputs
    # 첫 실행도 입력 산출물명@버전을 남긴다
    assert "planDoc@2" in recs["T-V1"].inputs and "planDoc@1" in recs["M-1"].inputs
    assert recs["T-S1"].model == "미정" and recs["T-S1"].agent == "전략"
    # 기록에는 산출물 내용이 없다 (참조와 메타만)
    dump = "".join(r.model_dump_json() for r in app.store.executions(rid))
    assert "헬스장" not in dump and "김서준" not in dump
    assert extension_fields(ExecutionRecord)  # 확장 필드 표시


def test_settings_snapshot_fixed_at_start(clock):
    app = make_app(clock)
    res = app.orchestrator.start_run("acc-1", pre_input())
    s = app.settings.current().model_copy(deep=True)
    s.scoring.threshold = 50
    s.agents["전략"].model = "바뀐 모델"
    app.settings.update(s)
    app.orchestrator.select_announcement(res.run_id, "A01")
    app.orchestrator.advance(res.run_id)
    app.orchestrator.start_writing(res.run_id)
    app.orchestrator.advance(res.run_id)
    recs = {r.task_id: r for r in app.store.executions(res.run_id)}
    assert recs["T-S1"].model == "미정"  # 실행 시작 시점 값
    ctx = app.engine.open_context(app.store.load_run(res.run_id))
    assert ctx.get("scoreReport.document").threshold == 80
    assert ctx.get("scoreReport.document").settings_snapshot["scoring"]["threshold"] == 80
