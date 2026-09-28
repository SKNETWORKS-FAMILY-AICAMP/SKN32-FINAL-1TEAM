"""재작성 사이클 — 화면 6 · 8 · 9 경로, 합치기 포함, 전후 비교 · 되돌리기, 실패 시 기회 반환, 추적 기록."""
from __future__ import annotations

import pytest

from conftest import executed, make_app, to_screen6, to_screen8, to_screen9

from sbrain.agents.stubs import StubScenario
from sbrain.orchestrator.errors import CommandError


def cycle_steps(app, rid, cycle_id):
    return [r.task_id for r in app.store.executions(rid) if r.cycle_id == cycle_id]


def last_cycle_id(app, rid):
    return [e for e in app.store.events(rid) if e.kind == "재작성시작"][-1].cycle_id


def orders(app, rid, judge):
    ctx = app.engine.open_context(app.store.load_run(rid))
    return ctx.get(f"{judge}.reworkOrders")


# ── 합치기가 모든 경로에 들어가는지 ───────────────────────
def test_merges_on_first_run_and_every_rework_path(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 55.0, 60.0], art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen6(app)
    assert "M-1" in executed(app, rid)  # 첫 실행

    chosen6 = orders(app, rid, "G-02a")[:1]
    app.orchestrator.decide(rid, 6, "재작성", chosen6)  # 화면 6
    app.orchestrator.advance(rid)
    steps6 = cycle_steps(app, rid, last_cycle_id(app, rid))
    assert steps6 == ["T-W1", "M-1", "T-V1", "G-02a"]

    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    art = [o for o in orders(app, rid, "G-02b") if o.task_id == "T-B1"]
    app.orchestrator.decide(rid, 8, "재작성", art)  # 화면 8
    app.orchestrator.advance(rid)
    steps8 = cycle_steps(app, rid, last_cycle_id(app, rid))
    assert steps8 == ["T-B1", "G-04", "M-3", "T-V2", "G-02b"]

    app.orchestrator.decide(rid, 8, "진행")
    doc = [o for o in orders(app, rid, "G-02b") if o.layer == "document" and o.targets != chosen6[0].targets]
    assert doc, "종합 평가에도 계획서 항목이 함께 제시되어야 한다"
    app.orchestrator.decide(rid, 9, "재작성", doc[:1])  # 화면 9 계획서
    app.orchestrator.advance(rid)
    steps9 = cycle_steps(app, rid, last_cycle_id(app, rid))
    assert steps9 == ["T-W1", "M-1", "T-V1", "T-B1", "G-04", "M-3", "T-V2", "G-02b"]


def test_onepage_rework_path_includes_wrap_merge(clock):
    app = make_app(clock, StubScenario(category="원페이지", art_scores=[(12.0, 7.0)]))
    rid = to_screen8(app)
    art = orders(app, rid, "G-02b")
    assert {o.task_id for o in art if o.layer == "artifact"} == {"T-B2"}
    app.orchestrator.decide(rid, 8, "재작성", [o for o in art if o.task_id == "T-B2"])
    app.orchestrator.advance(rid)
    assert cycle_steps(app, rid, last_cycle_id(app, rid)) == ["T-B2", "M-2", "G-04", "M-3", "T-V2", "G-02b"]


# ── 전후 비교 · 되돌리기 · 추적 ───────────────────────────
def test_screen9_document_rework_drop_reverts_plan_and_html(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 45.0], art_scores=[(12.0, 7.0), (12.0, 7.0)]))
    rid = to_screen9(app)
    before = app.store.get_pointers(rid)
    doc = [o for o in orders(app, rid, "G-02b") if o.layer == "document"][:1]
    app.orchestrator.decide(rid, 9, "재작성", doc)
    app.orchestrator.advance(rid)
    after = app.store.get_pointers(rid)
    # 점수가 떨어져 계획서와 HTML을 함께 되돌렸다
    assert after["planDoc"] == before["planDoc"] and after["prototype"] == before["prototype"]
    assert after["docScore"] == before["docScore"]

    # 기록만으로 '되돌릴 HTML 버전'을 찾을 수 있는가
    comp = [c for c in app.store.comparisons(rid) if c.screen == 9][-1]
    assert comp.kept == "전" and comp.basis == "total"
    html_before = [r for r in comp.before_refs if r.startswith("prototype@")]
    assert html_before == [f"prototype@{before['prototype']}"]
    moves = [e for e in app.store.pointer_events(rid) if e.key == "prototype" and e.cycle_id == comp.cycle_id]
    assert moves and moves[-1].to_version == before["prototype"]
    # T-B1 반영은 재작성 횟수를 쓰지 않는다
    usage = {u.bundle_id: u for u in app.store.load_run(rid).rework_usage}
    assert "실행 파일" not in usage and usage[doc[0].targets[0]].used_count == 1
    # 기록은 지우지 않는다 — 버려진 버전도 남아 있다
    assert app.store.get_latest_versions(rid)["prototype"] > before["prototype"]
    # 계획서 재작성의 HTML 반영도 피드백 전달로 연결된다 (출처: 합치기①이 만든 계획서)
    reflect = next(f for f in app.store.feedback(rid) if f.kind == "재작성반영")
    src = next(r for r in app.store.executions(rid) if r.execution_id == reflect.source_execution_id)
    tb1 = next(r for r in app.store.executions(rid) if r.execution_id == reflect.target_execution_id)
    assert (src.task_id, tb1.task_id, tb1.rework_role) == ("M-1", "T-B1", "반영")


def test_merge_error_during_rework_is_rework_failure(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)

    def broken(inp):
        raise RuntimeError("합치기 오류")
    app.registry.bind("M-1", broken)
    app.orchestrator.decide(rid, 6, "재작성", orders(app, rid, "G-02a")[:1])
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("문서평가", "사용자대기")  # 실행은 계속
    n = app.store.notifications(rid)[-1]
    assert (n.kind, n.failure_scope) == ("실패", "재작성")


def test_final_scores_trace_to_scored_versions(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0], art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "재작성", orders(app, rid, "G-02a")[:2])
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 8, "재작성", [o for o in orders(app, rid, "G-02b") if o.task_id == "T-B1"])
    app.orchestrator.advance(rid)
    ptr = app.store.get_pointers(rid)
    recs = app.store.executions(rid)

    def producer(ref):
        return next(r for r in recs if ref in r.outputs and r.status == "성공" and r.task_id in ("T-V1", "T-V2"))

    tv1 = producer(f"docScore@{ptr['docScore']}")
    tv2 = producer(f"artifactScore@{ptr['artifactScore']}")
    plan_in = [i for i in tv1.inputs if i.startswith("planDoc@")]
    proto_in = [i for i in tv2.inputs if i.startswith("prototype@")]
    assert plan_in and proto_in
    # 채점한 계획서는 합치기①이 만든 버전, 채점한 프로토타입은 합치기③이 만든 버전
    m1 = next(r for r in recs if plan_in[0] in r.outputs)
    m3 = next(r for r in recs if proto_in[0] in r.outputs)
    assert (m1.task_id, m3.task_id) == ("M-1", "M-3")
    assert tv1.model is not None and tv1.temperature == 0.0  # T-V1 온도 덮어쓰기


def test_rework_feedback_links_orders_to_target_execution(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    g02a_exec = next(r for r in app.store.executions(rid) if r.task_id == "G-02a")
    chosen = orders(app, rid, "G-02a")[:1]
    app.orchestrator.decide(rid, 6, "재작성", chosen)
    app.orchestrator.advance(rid)
    tw1 = [r for r in app.store.executions(rid) if r.task_id == "T-W1"][-1]
    fb = next(f for f in app.store.feedback(rid) if f.kind == "재작성")
    assert fb.source_execution_id == g02a_exec.execution_id
    assert fb.source_refs[0] == "G-02a.reworkOrders@1" and fb.source_refs[1].startswith("decision@")
    assert fb.target_execution_id == tw1.execution_id and tw1.trigger == "재작성"
    assert tw1.rework_role == "대상" and tw1.bundle_id == chosen[0].targets[0]
    ctx = app.engine.open_context(app.store.load_run(rid))
    ri = ctx.get_ref(fb.via_ref)
    assert ri.mode == "재작성" and ri.order.targets == chosen[0].targets


def test_screen6_improvement_kept_and_demo_scores(clock):
    # 기획서 7-4 시연: 문서 평가 74 → 재작성 → 86, 종합 79 → 프로토타입만 재작성 → 86
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0], art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen6(app)
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.get("scoreReport.document").display_score == 74.3
    app.orchestrator.decide(rid, 6, "재작성", orders(app, rid, "G-02a")[:1])
    app.orchestrator.advance(rid)
    ctx = app.engine.open_context(app.store.load_run(rid))
    rep = ctx.get("scoreReport.document")
    assert rep.display_score == 85.7 and rep.comparisons[0].kept == "후"
    assert ctx.get("G-02a.nextAction") == "진행가능"
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 8, "진행")
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.get("scoreReport.overall").total == 79.0
    art = [o for o in orders(app, rid, "G-02b") if o.layer == "artifact"]
    app.orchestrator.decide(rid, 9, "재작성", art)
    app.orchestrator.advance(rid)
    # 화면 9 프로토타입만 재작성 경로에도 합치기③이 들어간다
    assert cycle_steps(app, rid, last_cycle_id(app, rid)) == ["T-B1", "G-04", "M-3", "T-V2", "G-02b"]
    ctx = app.engine.open_context(app.store.load_run(rid))
    rep = ctx.get("scoreReport.overall")
    assert rep.total == 86.0 and rep.carried_over_layer == "document" and rep.passed
    assert [d.layer for d in rep.rework_diff] == ["artifact"]
    app.orchestrator.decide(rid, 9, "진행")
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "완료"


def test_rework_failure_rolls_back_and_refunds(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0]))
    rid = to_screen6(app)
    before = app.store.get_pointers(rid)
    chosen = orders(app, rid, "G-02a")[:1]
    app.llm.plan("T-W1", ["auth"] * 50)  # 영구 오류
    app.orchestrator.decide(rid, 6, "재작성", chosen)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.rework_screen, run.cycle) == ("문서평가", "사용자대기", None, None)
    usage = {u.bundle_id: u for u in run.rework_usage}[chosen[0].targets[0]]
    assert (usage.used_count, usage.remaining) == (0, 1)  # 기회 반환
    assert app.store.get_pointers(rid)["planDoc"] == before["planDoc"]
    n = app.store.notifications(rid)[-1]
    assert (n.kind, n.failure_scope, n.target_step) == ("실패", "재작성", 6)
    assert run.notices[-1].code == "E-RUN-ROLLBACK"


def test_rework_resume_wait_shows_requested_screen(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    app.llm.plan("T-W1", ["timeout"] * 6)
    app.orchestrator.decide(rid, 6, "재작성", orders(app, rid, "G-02a")[:1])
    app.orchestrator.advance(rid)
    v = app.orchestrator.view(rid)
    assert (v.progress, v.screen_status, v.resume_step) == ("재개대기", "진행 중", 6)


def test_bundle_limit(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 52.0]))
    rid = to_screen6(app)
    chosen = orders(app, rid, "G-02a")[:1]
    app.orchestrator.decide(rid, 6, "재작성", chosen)
    app.orchestrator.advance(rid)
    with pytest.raises(CommandError) as e:
        app.orchestrator.decide(rid, 6, "재작성", chosen)
    assert e.value.code == "E-G2-LIMIT"


def test_invalid_order_rejected(clock):
    app = make_app(clock, StubScenario(category="원페이지", art_scores=[(12.0, 7.0)]))
    rid = to_screen8(app)
    from sbrain.models import ReworkOrder
    fake = ReworkOrder(task_id="T-B1", unit="묶음", targets=["실행 파일"], reason="x", instruction_delta="x",
                       layer="artifact")
    with pytest.raises(CommandError):
        app.orchestrator.decide(rid, 8, "재작성", [fake])
