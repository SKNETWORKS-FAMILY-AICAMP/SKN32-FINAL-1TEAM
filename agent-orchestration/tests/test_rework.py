"""재작성 — 묶음 요청 · 모으기(같은 화면의 요청을 한 번에) · 문서층 임시 처리, 화면 6 · 8 · 9 경로, 합치기 포함,
전후 비교 · 되돌리기, 실패 시 모은 묶음 모두 기회 반환, 마지막 재작성 요약, 추적 기록 (spec 3.2)."""
from __future__ import annotations

import time

import pytest

from conftest import TIMING, executed, make_app, start_and_select, to_screen6, to_screen8, to_screen9
from flow_helpers import WINDOW, code_of, cycle_steps, last_cycle_id, pid, rework, usage_of

from sbrain.agents.stubs import StubScenario
from sbrain.flow.sbrain_flow import REWORK_DEFAULT_REASON, bundle_orders, default_instruction_builder
from sbrain.models import ReworkOrder
from sbrain.orchestrator.errors import CommandError


def orders(app, rid, judge):
    ctx = app.engine.open_context(app.store.load_run(rid))
    return ctx.get(f"{judge}.reworkOrders")


def request(app, rid, bundle):
    return app.orchestrator.request_rework_for_project(pid(app, rid), bundle)


def rework_input(app, rid, task_id):
    ctx = app.engine.open_context(app.store.load_run(rid))
    return ctx.get(f"{task_id}.reworkInput")


# ── 합치기가 모든 경로에 들어가는지 · 문서층 임시 처리 순서 ────────
def test_merges_on_first_run_and_every_rework_path(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 55.0, 60.0], art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen6(app)
    assert "M-1" in executed(app, rid)  # 첫 실행

    rework(app, clock, rid, "문제인식")  # 화면 6 — 문제인식 묶음 항목(본문뿐)만 다시 만든다 (spec 4.11)
    assert cycle_steps(app, rid, last_cycle_id(app, rid)) == ["T-W1", "M-1", "T-V1", "G-02a"]

    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    art = [o for o in orders(app, rid, "G-02b") if o.task_id == "T-B1"]
    app.orchestrator.decide(rid, 8, "재작성", art)  # 기존 경로 — 산출물층 지시는 그 묶음 이름의 요청으로 처리
    clock.advance(seconds=WINDOW)
    app.orchestrator.advance(rid)
    assert cycle_steps(app, rid, last_cycle_id(app, rid)) == ["T-B1", "G-04", "M-3", "T-V2", "G-02b"]

    app.orchestrator.decide(rid, 8, "진행")
    rework(app, clock, rid, "실현가능성")  # 화면 9 계획서 — 본문 · 표 항목, HTML 반영 · 두 층 재채점
    assert cycle_steps(app, rid, last_cycle_id(app, rid)) == [
        "T-W1", "T-W3", "M-1", "T-V1", "T-B1", "G-04", "M-3", "T-V2", "G-02b"]


def test_onepage_rework_path_includes_wrap_merge(clock):
    app = make_app(clock, StubScenario(category="원페이지", art_scores=[(12.0, 7.0)]))
    rid = to_screen8(app)
    art = orders(app, rid, "G-02b")
    assert {o.task_id for o in art if o.layer == "artifact"} == {"T-B2"}
    rework(app, clock, rid, "인포그래픽")
    assert cycle_steps(app, rid, last_cycle_id(app, rid)) == ["T-B2", "M-2", "G-04", "M-3", "T-V2", "G-02b"]


# ── 모으기 ─────────────────────────────────────────────
def test_requests_within_window_merge_into_one_rework(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    a = request(app, rid, "인포그래픽")
    b = request(app, rid, "문제인식")
    c = request(app, rid, "실행 파일")
    assert a.cycle_id == b.cycle_id == c.cycle_id and (a.screen, b.screen, c.screen) == (9, 9, 9)
    assert (a.bundles, c.bundles) == (["인포그래픽"], ["인포그래픽", "문제인식", "실행 파일"])
    assert a.collect_until == c.collect_until and not c.duplicate
    run = app.store.load_run(rid)
    # 모으는 동안은 '진행 중'으로 보이고 요청한 화면으로 돌아온다 (진행 상태 값은 새로 만들지 않는다)
    assert (run.state.step, run.state.progress, run.state.screen_status, run.state.resume_step) == (
        "종합평가", "실행", "진행 중", 9)
    assert usage_of(app, rid) == {"인포그래픽": (1, 0), "문제인식": (1, 0), "실행 파일": (1, 0)}  # 접수 때 센다
    assert run.last_rework.status == "진행중" and run.last_rework.bundles == ["인포그래픽", "문제인식", "실행 파일"]

    app.orchestrator.advance(rid)                                   # 모으는 시간 안에는 진행하지 않는다
    assert cycle_steps(app, rid, a.cycle_id) == []
    clock.advance(seconds=WINDOW)
    app.orchestrator.advance(rid)
    assert len([e for e in app.store.events(rid) if e.kind == "재작성시작"]) == 1   # 재작성 한 번
    # 합집합 · 기준 문서 순서 (문제인식 묶음은 본문 항목뿐 — T-W1)
    assert cycle_steps(app, rid, a.cycle_id) == [
        "T-W1", "M-1", "T-V1", "T-B1", "T-B2", "G-04", "M-3", "T-V2", "G-02b"]
    comps = [x for x in app.store.comparisons(rid) if x.cycle_id == a.cycle_id]
    assert sorted(x.bundle_id for x in comps) == sorted(["인포그래픽", "문제인식", "실행 파일"])
    assert len({(x.before_score, x.after_score, x.kept, x.basis) for x in comps}) == 1  # 요청 전체를 한 번 비교
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.cycle) == ("종합평가", "사용자대기", None)
    s = run.last_rework
    assert (s.cycle_id, s.screen, s.status, s.kept, s.basis) == (a.cycle_id, 9, "완료", comps[0].kept, "total")
    assert (s.before_score, s.after_score) == (comps[0].before_score, comps[0].after_score)
    assert s.after_refs == comps[0].after_refs and s.before_refs == comps[0].before_refs and not s.rolled_back


def test_duplicate_bundle_counted_once(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    first = request(app, rid, "실행 파일")
    again = request(app, rid, "실행 파일")
    assert again.duplicate and again.cycle_id == first.cycle_id and again.bundles == ["실행 파일"]
    assert usage_of(app, rid) == {"실행 파일": (1, 0)}                 # 기회는 한 번만 쓴다


def test_late_request_and_proceed_while_collecting_rejected(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    request(app, rid, "실행 파일")
    assert code_of(lambda: app.orchestrator.decide(rid, 8, "진행")) == "INVALID_STATE"   # 모으는 동안 '진행'
    clock.advance(seconds=WINDOW)
    assert code_of(lambda: request(app, rid, "인포그래픽")) == "INVALID_STATE"           # 모으는 시간이 끝남
    assert usage_of(app, rid) == {"실행 파일": (1, 0)}


@TIMING
def test_request_while_worker_runs_rework_is_rejected_at_once(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    request(app, rid, "실행 파일")
    clock.advance(seconds=WINDOW)
    seen = []

    def during(_request):
        t0 = time.monotonic()
        try:
            request(app, rid, "인포그래픽")
        except CommandError as e:
            seen.append((e.code, time.monotonic() - t0))
        return '{"ok": true}'
    app.llm.respond("T-B1", during)
    app.orchestrator.advance(rid)                                    # 진행하는 쪽이 점유한 채 T-B1을 돈다
    assert seen and seen[0][0] == "INVALID_STATE" and seen[0][1] < 1.0  # 점유를 기다리지 않는다
    assert app.store.load_run(rid).state.progress == "사용자대기"


@TIMING
def test_busy_when_other_command_holds_lease(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    app.orchestrator.rework_lease_retry_sec = 0.2
    assert app.store.acquire(rid, "cmd-other", 60)
    t0 = time.monotonic()
    assert code_of(lambda: request(app, rid, "실행 파일")) == "BUSY"
    assert time.monotonic() - t0 >= 0.2                              # 짧게 다시 시도했다
    app.store.release(rid, "cmd-other")
    assert request(app, rid, "실행 파일").bundles == ["실행 파일"]


def test_abort_while_collecting_does_not_run_rework(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    acc = request(app, rid, "실행 파일")
    assert app.orchestrator.abort_project(pid(app, rid)).run_action == "중단"
    clock.advance(seconds=WINDOW)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.cycle, run.queue) == ("중단", None, [])
    assert cycle_steps(app, rid, acc.cycle_id) == []


# ── 이름 · 층 · 화면 · 상태 규칙 ───────────────────────────
def test_bundle_name_layer_and_state_rules(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0]))
    rid = start_and_select(app)                                      # 계획서작성 · 사용자대기 — 대기 지점이 아님
    assert code_of(lambda: request(app, rid, "문제인식")) == "INVALID_STATE"
    assert code_of(lambda: app.orchestrator.request_rework_for_project(987654, "문제인식")) == "RUN_NOT_FOUND"
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)                                    # 화면 6
    assert code_of(lambda: request(app, rid, "실행 파일")) == "INVALID_ORDER"       # 화면 6 산출물층
    assert code_of(lambda: request(app, rid, "없는 묶음")) == "INVALID_ORDER"
    assert code_of(lambda: request(app, rid, "2.4")) == "INVALID_ORDER"         # 항목 번호 · 태그로는 받지 않는다
    assert code_of(lambda: request(app, rid, "1-1")) == "INVALID_ORDER"
    # 문서층 판정 지시의 대상은 묶음 이름 하나다 (spec 4.12)
    assert [o.targets for o in orders(app, rid, "G-02a")] == [["문제인식"], ["실현가능성"], ["성장전략"], ["팀 구성"]]
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)                                    # 화면 8
    assert code_of(lambda: request(app, rid, "문제인식")) == "INVALID_ORDER"         # 화면 8 문서층
    assert app.store.load_run(rid).rework_usage == []


def test_onepage_executable_rejected(clock):
    app = make_app(clock, StubScenario(category="원페이지"))
    rid = to_screen8(app)
    assert code_of(lambda: request(app, rid, "실행 파일")) == "INVALID_ORDER"
    app.orchestrator.decide(rid, 8, "진행")
    assert code_of(lambda: request(app, rid, "실행 파일")) == "INVALID_ORDER"
    assert request(app, rid, "인포그래픽").screen == 9


def test_legacy_decide_rejects_document_orders(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0]))
    rid = to_screen6(app)
    doc = orders(app, rid, "G-02a")[:1]
    assert code_of(lambda: app.orchestrator.decide(rid, 6, "재작성", doc)) == "INVALID_ORDER"
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 8, "진행")
    doc9 = [o for o in orders(app, rid, "G-02b") if o.layer == "document"][:1]
    assert code_of(lambda: app.orchestrator.decide(rid, 9, "재작성", doc9)) == "INVALID_ORDER"
    run = app.store.load_run(rid)
    assert (run.state.progress, run.rework_usage, run.cycle) == ("사용자대기", [], None)


def test_invalid_order_rejected(clock):
    app = make_app(clock, StubScenario(category="원페이지", art_scores=[(12.0, 7.0)]))
    rid = to_screen8(app)
    from sbrain.models import ReworkOrder
    fake = ReworkOrder(task_id="T-B1", unit="묶음", targets=["실행 파일"], reason="x", instruction_delta="x",
                       layer="artifact")
    with pytest.raises(CommandError):
        app.orchestrator.decide(rid, 8, "재작성", [fake])


# ── 횟수 ───────────────────────────────────────────────
def test_bundle_limit(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 52.0]))
    rid = to_screen6(app)
    rework(app, clock, rid, "문제인식")
    assert code_of(lambda: request(app, rid, "문제인식")) == "E-G2-LIMIT"
    assert request(app, rid, "실현가능성").bundles == ["실현가능성"]      # 문서층 묶음은 이름마다 센다


def test_bundle_used_at_screen8_rejected_at_screen9(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    rework(app, clock, rid, "실행 파일")
    app.orchestrator.decide(rid, 8, "진행")
    assert code_of(lambda: request(app, rid, "실행 파일")) == "E-G2-LIMIT"
    assert request(app, rid, "인포그래픽").screen == 9


def test_non_failing_bundle_and_pass_state_accepted_and_rescored(clock):
    app = make_app(clock)                                            # 기본 점수 — 문서층 통과, 판정 지시 없음
    rid = to_screen6(app)
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.get("G-02a.nextAction") == "진행가능" and ctx.get("G-02a.reworkOrders") == []
    [acc] = rework(app, clock, rid, "팀 구성")
    assert cycle_steps(app, rid, acc.cycle_id) == ["T-W1", "M-1", "T-V1", "G-02a"]  # 그 묶음 항목만 다시 만들고 채점
    ri = rework_input(app, rid, "T-W1")
    assert (ri.order.reason, ri.order.targets) == (REWORK_DEFAULT_REASON, ["팀 구성"])   # 판정 지시가 없으면 고정 문구
    assert ri.order.instruction_delta == REWORK_DEFAULT_REASON                         # 시트 4: 보완 지시는 비워 둘 수 없다
    assert default_instruction_builder("지시", ri).count(REWORK_DEFAULT_REASON) == 1      # 지시문에는 한 번만
    assert [x.bundle_id for x in app.store.comparisons(rid) if x.cycle_id == acc.cycle_id] == ["팀 구성"]

    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)                                    # 화면 8 — 판정 지시는 T-B1(실행 파일)뿐
    assert {o.task_id for o in orders(app, rid, "G-02b") if o.layer == "artifact"} == {"T-B1"}
    [acc8] = rework(app, clock, rid, "인포그래픽")
    assert cycle_steps(app, rid, acc8.cycle_id) == ["T-B2", "G-04", "M-3", "T-V2", "G-02b"]
    order = rework_input(app, rid, "T-B2").order
    assert (order.reason, order.instruction_delta) == (REWORK_DEFAULT_REASON, REWORK_DEFAULT_REASON)


def test_artifact_bundle_uses_judge_order(clock):
    app = make_app(clock, StubScenario(art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen8(app)
    [judge] = [o for o in orders(app, rid, "G-02b") if o.task_id == "T-B1"]
    rework(app, clock, rid, "실행 파일")
    ri = rework_input(app, rid, "T-B1")
    assert (ri.order.reason, ri.order.instruction_delta, ri.order.targets) == (
        judge.reason, judge.instruction_delta, ["실행 파일"])


# ── 전후 비교 · 되돌리기 · 추적 ───────────────────────────
def test_screen9_document_rework_drop_reverts_plan_and_html(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 45.0], art_scores=[(12.0, 7.0), (12.0, 7.0)]))
    rid = to_screen9(app)
    before = app.store.get_pointers(rid)
    rework(app, clock, rid, "문제인식")
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
    assert usage_of(app, rid) == {"문제인식": (1, 0)}
    s = app.store.load_run(rid).last_rework
    assert (s.status, s.kept, s.before_refs) == ("완료", "전", comp.before_refs)
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
    rework(app, clock, rid, "문제인식")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("문서평가", "사용자대기")  # 실행은 계속
    n = app.store.notifications(rid)[-1]
    assert (n.kind, n.failure_scope) == ("실패", "재작성")
    assert run.last_rework.status == "실패"


def test_final_scores_trace_to_scored_versions(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0], art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen6(app)
    rework(app, clock, rid, "문제인식", "실현가능성")
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    rework(app, clock, rid, "실행 파일")
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
    # T-V1 기본 설정(gpt-5.6-terra, spec 4.2)은 온도를 보내지 않아 온도 덮어쓰기(fixed 0.0)가 걸리지 않는다 — 기본 온도가
    # 있을 때의 덮어쓰기는 test_task_settings.py의 test_each_task_records_its_own_entry가 본다
    assert tv1.model == "gpt-5.6-terra" and tv1.temperature is None


def test_rework_feedback_links_orders_to_target_execution(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    g02a_exec = next(r for r in app.store.executions(rid) if r.task_id == "G-02a")
    judge_doc = [o for o in orders(app, rid, "G-02a") if o.layer == "document"]
    assert len(judge_doc) == 4                                        # 80 미만 · 후보 없음 → 묶음 모두 (spec 4.12 ②)
    rework(app, clock, rid, "실현가능성")
    tws = [r for r in app.store.executions(rid) if r.trigger == "재작성" and r.task_id in ("T-W1", "T-W2", "T-W3")]
    assert [r.task_id for r in tws] == ["T-W1", "T-W3"]               # 실현가능성 = 본문 · 표 항목
    fbs = [f for f in app.store.feedback(rid) if f.kind == "재작성"]
    assert [f.target_execution_id for f in fbs] == [r.execution_id for r in tws]
    fb, tw1 = fbs[0], tws[0]
    assert fb.source_execution_id == g02a_exec.execution_id
    assert fb.source_refs[0] == "G-02a.reworkOrders@1" and fb.source_refs[1].startswith("decision@")
    assert tw1.rework_role == "대상" and tw1.bundle_id == "실현가능성"
    ctx = app.engine.open_context(app.store.load_run(rid))
    ri = ctx.get_ref(fb.via_ref)
    assert ri.mode == "재작성" and ri.order.targets == ["실현가능성"]
    # 고른 묶음을 대상으로 한 판정 지시만 쓴다 (spec 4.11)
    [mine] = [o for o in judge_doc if o.targets == ["실현가능성"]]
    assert (ri.order.reason, ri.order.instruction_delta) == (mine.reason, mine.instruction_delta)
    # 목표 항목 = 그 묶음의 그 Task 종류 항목 (본문은 T-W1, 표는 T-W3)
    form = ctx.get("formSpec")
    kinds = dict(zip(form.section_codes, form.section_kinds))
    assert list(ri.target_items) == [c for c in form.section_codes if c.startswith("3.5.") and kinds[c] == "section"]
    tw3_ri = ctx.get_ref(fbs[1].via_ref)
    assert list(tw3_ri.target_items) == [c for c in form.section_codes if c.startswith("3.5.") and kinds[c] == "table"]
    # 판정에는 모은 지시 전체가 사용자 선택으로 넘어간다
    decision = ctx.get_ref(fb.source_refs[1])
    assert decision["userAction"] == "재작성" and decision["bundles"] == ["실현가능성"]
    assert [o["taskId"] for o in decision["selectedOrders"]] == ["T-W1", "T-W3"]


def test_screen6_improvement_kept_and_demo_scores(clock):
    # 기획서 7-4 시연: 문서 평가 74 → 재작성 → 86, 종합 79 → 프로토타입만 재작성 → 86
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0], art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen6(app)
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.get("scoreReport.document").display_score == 74.3
    rework(app, clock, rid, "문제인식")
    ctx = app.engine.open_context(app.store.load_run(rid))
    rep = ctx.get("scoreReport.document")
    assert rep.display_score == 85.7 and rep.comparisons[0].kept == "후"
    assert ctx.get("G-02a.nextAction") == "진행가능"
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 8, "진행")
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.get("scoreReport.overall").total == 79.5   # 대조 손잡이 7 → 7.5 (1.4판 몫, 기능 2개 중 1 인정)
    art = [o for o in orders(app, rid, "G-02b") if o.layer == "artifact"]
    app.orchestrator.decide(rid, 9, "재작성", art)                    # 기존 경로 (산출물층)
    clock.advance(seconds=WINDOW)
    app.orchestrator.advance(rid)
    # 화면 9 프로토타입만 재작성 경로에도 합치기③이 들어간다
    assert cycle_steps(app, rid, last_cycle_id(app, rid)) == ["T-B1", "G-04", "M-3", "T-V2", "G-02b"]
    ctx = app.engine.open_context(app.store.load_run(rid))
    rep = ctx.get("scoreReport.overall")
    assert rep.total == 86.2 and rep.carried_over_layer == "document" and rep.passed   # 대조 11.25 (1.4판 몫)
    assert [d.layer for d in rep.rework_diff] == ["artifact"]
    app.orchestrator.decide(rid, 9, "진행")
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "완료"


# ── 재작성 실패 ─────────────────────────────────────────
def test_rework_failure_rolls_back_and_refunds(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0]))
    rid = to_screen6(app)
    before = app.store.get_pointers(rid)
    app.llm.plan("T-W1", ["auth"] * 50)  # 영구 오류
    rework(app, clock, rid, "문제인식")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.rework_screen, run.cycle) == ("문서평가", "사용자대기", None, None)
    assert usage_of(app, rid) == {"문제인식": (0, 1)}  # 기회 반환
    assert app.store.get_pointers(rid)["planDoc"] == before["planDoc"]
    n = app.store.notifications(rid)[-1]
    assert (n.kind, n.failure_scope, n.target_step) == ("실패", "재작성", 6)
    assert run.notices[-1].code == "E-RUN-ROLLBACK"


def test_rework_failure_refunds_all_collected_bundles(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    [ok] = rework(app, clock, rid, "문제인식")                         # 성공한 재작성
    assert app.store.load_run(rid).last_rework.status == "완료"
    before = app.store.get_pointers(rid)
    app.llm.plan("T-B1", ["auth"] * 50)                               # 영구 오류
    acc = rework(app, clock, rid, "실행 파일", "인포그래픽")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("종합평가", "사용자대기")
    assert usage_of(app, rid) == {"문제인식": (1, 0), "실행 파일": (0, 1), "인포그래픽": (0, 1)}
    assert app.store.get_pointers(rid)["prototype"] == before["prototype"]
    s = run.last_rework                                               # 이전 성공이 '마지막'으로 남지 않는다
    assert s.cycle_id == acc[0].cycle_id != ok.cycle_id
    assert (s.status, s.rolled_back, s.refunded_bundles, s.notice_code, s.screen) == (
        "실패", True, ["실행 파일", "인포그래픽"], "E-RUN-ROLLBACK", 9)
    assert (s.kept, s.before_refs, s.after_refs) == (None, [], [])
    assert not [c for c in app.store.comparisons(rid) if c.cycle_id == s.cycle_id]


def test_rework_resume_wait_shows_requested_screen(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    app.llm.plan("T-W1", ["timeout"] * 6)
    rework(app, clock, rid, "문제인식")
    v = app.orchestrator.view(rid)
    assert (v.progress, v.screen_status, v.resume_step) == ("재개대기", "진행 중", 6)
    assert code_of(lambda: request(app, rid, "실현가능성")) == "INVALID_STATE"   # 재개대기는 대기 지점이 아님


def test_bundle_orders_never_leave_instruction_delta_empty():
    """판정 지시에 사유만 있고 보완 지시가 비어 있어도 고정 문구로 채운다 (시트 4: instructionDelta는 비워 둘 수 없다)."""
    judge = ReworkOrder(task_id="T-B1", unit="묶음", targets=["항목 1"], reason="미달 사유", instruction_delta="",
                        layer="artifact")
    order = bundle_orders(["실행 파일"], [judge])["T-B1"]
    assert (order.reason, order.instruction_delta, order.targets) == ("미달 사유", REWORK_DEFAULT_REASON, ["실행 파일"])
