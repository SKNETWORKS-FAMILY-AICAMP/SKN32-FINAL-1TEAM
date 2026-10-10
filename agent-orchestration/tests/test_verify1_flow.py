"""검증-1 fail 재수행 · 항목 단위 자체 검사 재수행 · 태그 묶음 재작성 · 판정 후보 (spec 4.8 · 4.10 · 4.11 · 4.12).

- 검증-1 재수행: T-V1 바로 뒤에 fail 항목만 해당 Task(본문 T-W1 · 그림 T-W2)로 다시 쓰고 그 항목만 다시 검증한다. 표는 다시
  만들지 않고 다시 검증만, 끝내 fail이면 T-W3 대체 → M-1(T-V1 다시 안 함). 항목마다 1회, 입력 없음 제외, 재작성 기회 안 씀.
- 끼우는 자리: 첫 작성 G-02a 앞 · 화면 6 전후 비교 앞 · 화면 9 T-B1 앞. 흐름 상태 Run.verify1(사이클마다 새로, 끝 · 실패 ·
  중단 때 비움, 재개 뒤 같은 대상).
- 자체 검사 재수행: 걸린 항목(check.failedItems)만, 검증-1 재수행과 횟수 따로, T-W3는 재수행 없이 바로 대체.
- 재작성: 고른 묶음 항목만 종류별 Task로, 다시 만든 항목만 재검증 · 나머지 이어받음, T-W3 · T-V1 지시문 다시 쓰기 없음.
- 판정 후보: fail · warning 묶음, 입력 없음 제외 + 안내, 80 미만 · 후보 없음 → 묶음 모두, 배점은 설정 docLayerMax.
- 짝짓기 한 곳: rework_map 표를 바꾸면 목표 · 후보 · 그림 항목 재작성(T-W2)이 따라 바뀐다.
스텁 앱 신청자는 법인(초기창업 3.1.1 ~ 3.7.4) — 본문 3.4.1(문제인식) · 그림 3.3.6(묶음 없음) · 표 3.5.2 · 3.5.3(실현가능성).
흐름 테스트는 clock · store_backend 장치로 메모리 · SQLite 두 저장소에서 돈다.
"""
from __future__ import annotations

import json

from conftest import make_app, to_screen6, to_screen9
from flow_helpers import ctx_of, cycle_steps, last_cycle_id, pid, records_of_task, rework, usage_of

from sbrain.agents.stubs import INPUT_MISSING_NOTICE, StubScenario
from sbrain.agents.supervisor.plan import PURPOSE_REWRITE
from sbrain.agents.supervisor.rewrite import rewrite_guidance
from sbrain.flow import rework_map
from sbrain.flow.sbrain_flow import FALLBACK_ROLE, VERIFY1_ROLE, WRITE, bundle_orders
from sbrain.orchestrator import Settings

BODY, IMAGE, TABLE, TABLE2 = "3.4.1", "3.3.6", "3.5.2", "3.5.3"


# ── 도움 ─────────────────────────────────────────────
def writing_steps(app, rid) -> list[str]:
    """첫 작성 구간에서 돈 단계 (T-C3 다음부터 첫 G-02a까지)."""
    steps = [r.task_id for r in app.store.executions(rid)]
    start = steps.index("T-C3") + 1
    return steps[start:steps.index("G-02a", start) + 1]


def rework_inputs(app, rid, task_id) -> list:
    """그 Task의 재작성 · 재수행 입력 버전 전부 (버전 순)."""
    ctx = ctx_of(app, rid)
    latest = app.store.get_latest_versions(rid).get(f"{task_id}.reworkInput", 0)
    return [ctx.get(f"{task_id}.reworkInput", v) for v in range(1, latest + 1)]


def calls(app, purpose: str) -> int:
    return sum(1 for r in app.llm.requests if r.metadata["purpose"] == purpose)


def results(app, rid) -> dict:
    return {r.section_code: r for r in ctx_of(app, rid).get("sectionResults")}


def counting(app, task_id: str, purpose: str, action) -> list[int]:
    """그 Task의 그 목적 호출마다 action(n)을 부르는 가짜 응답 — n은 1부터. 다시 쓰기 호출이면 새 안내를 준다."""
    seen = [0]

    def reply(request) -> str:
        if request.metadata["purpose"] == PURPOSE_REWRITE:
            return json.dumps({"guidance": f"새 안내 {request.metadata['task_id']}"}, ensure_ascii=False)
        if request.metadata["purpose"] == purpose:
            seen[0] += 1
            action(seen[0])
        return '{"ok": true}'
    app.llm.respond(task_id, reply)
    return seen


# ── 검증-1 재수행: 첫 작성 ──────────────────────────────────
def test_first_writing_redoes_only_failed_items_then_replaces_failed_table(clock):
    sc = StubScenario(fail_items={TABLE}, fail_item_times={BODY: 1, IMAGE: 1})
    app = make_app(clock, sc)
    seen_total: list[tuple[int, list[str]]] = []

    def on_tv1(n: int) -> None:   # 두 번째 T-V1 직전 저장 상태 — 끼운 단계만큼 구간 단계 수가 늘었다
        if n == 2:
            run = app.store.load_run(rid_box[0])
            seen_total.append((run.segment_total, list(run.queue)))
    rid_box: list[str] = []
    counting(app, "T-V1", "문서층 채점", on_tv1)
    real_start = app.orchestrator.start_writing

    def start(rid):
        rid_box.append(rid)
        return real_start(rid)
    app.orchestrator.start_writing = start
    rid = to_screen6(app)

    # 끼우는 자리: T-V1 바로 뒤 · G-02a 앞. 본문 → T-W1, 그림 → T-W2, 표는 다시 만들지 않고 다시 검증만, 끝내 fail인 표는 대체
    assert writing_steps(app, rid) == [
        "T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "M-1", "T-V1",
        "T-W1", "T-W2", "M-1", "T-V1", "T-W3", "M-1", "G-02a"]
    # 두 번째 T-V1 직전: T-W1 · T-W2 · M-1 · T-V1 4단계를 끼운 만큼 구간 단계 수가 늘었다 (진행률)
    assert seen_total == [(len(WRITE) + 4, ["T-V1", "G-02a"])]
    # 다시 쓴 항목만 다시 썼다
    assert calls(app, f"섹션 {BODY} 작성") == 2 and calls(app, "섹션 3.1.1 작성") == 1
    assert calls(app, f"그림 {IMAGE} 작성") == 2
    tw1, tw2, tv1, tw3 = (rework_inputs(app, rid, t)[-1] for t in ("T-W1", "T-W2", "T-V1", "T-W3"))
    assert (tw1.mode, tw1.redo_source, tw1.unit, tw1.target_items) == (
        "재수행", "검증-1", "섹션", {BODY: [f"{BODY} 결함 (스텁)"]})
    assert (tw2.redo_source, tw2.unit, list(tw2.target_items)) == ("검증-1", "차트 1건", [IMAGE])
    assert (tv1.mode, tv1.redo_source, set(tv1.target_items)) == ("재수행", "검증-1", {BODY, IMAGE, TABLE})
    assert (tw3.redo_source, tw3.unit, tw3.fallback_items) == ("검증-1", "표 1건", [TABLE])
    redo_w1 = records_of_task(app, rid, "T-W1")[-1]
    assert (redo_w1.trigger, redo_w1.rework_role) == ("재수행", VERIFY1_ROLE) and redo_w1.feedback_in
    assert records_of_task(app, rid, "T-W3")[-1].rework_role == FALLBACK_ROLE
    # 판정: 다시 쓴 본문 · 그림은 통과, 표는 대체했어도 fail 그대로(다시 검증하지 않음)
    res = results(app, rid)
    assert (res[BODY].status, res[IMAGE].status, res[TABLE].status) == ("pass", "pass", "fail")
    ctx = ctx_of(app, rid)
    out = ctx.get("tableOutputs")[TABLE]
    assert out["tableFallbackUsed"] and out["fallbackReason"] == f"{TABLE} 결함 (스텁)"
    plan = ctx.get("planDoc")
    assert TABLE not in [t.source_ref for t in plan.tables] and TABLE2 in [t.source_ref for t in plan.tables]
    assert "대체" in next(s for s in plan.sections if s.section_code == TABLE).sentences[0].text
    # 흐름 상태 — 첫 작성 사이클, 끝나면 진행 표시를 비운다. 재작성 기회를 쓰지 않는다
    v = app.store.load_run(rid).verify1
    assert (v.cycle_key, v.phase, v.pending_items) == ("첫작성", "없음", {})
    assert v.redo_counts == {BODY: 1, IMAGE: 1, TABLE: 1} and len(v.made_items) == 24
    assert app.store.load_run(rid).rework_usage == []
    # 표가 fail로 남아 실현가능성 묶음이 후보다
    orders = ctx.get("G-02a.reworkOrders")
    assert [o.targets for o in orders] == [["실현가능성"]] and TABLE in orders[0].reason


def test_redo_once_per_item_and_body_fail_stays_without_fallback(clock):
    app = make_app(clock, StubScenario(fail_items={BODY}))
    rid = to_screen6(app)
    assert writing_steps(app, rid)[6:] == ["T-V1", "T-W1", "M-1", "T-V1", "G-02a"]   # 1회뿐, 본문은 대체 없음
    assert calls(app, f"섹션 {BODY} 작성") == 2
    assert results(app, rid)[BODY].status == "fail"
    orders = ctx_of(app, rid).get("G-02a.reworkOrders")
    assert [(o.task_id, o.targets) for o in orders] == [("T-W1", ["문제인식"])]
    assert orders[0].reason == f"{BODY} {BODY} 결함 (스텁)" == orders[0].instruction_delta


def test_input_missing_and_warning_are_not_redone_and_candidates_skip_input_missing(clock):
    app = make_app(clock, StubScenario(doc_scores=[60.0], input_missing_items={TABLE2}, warning_items={"3.6.1"}))
    rid = to_screen6(app)
    assert writing_steps(app, rid).count("T-V1") == 1                            # fail이 없어 재수행 없음
    res = results(app, rid)
    assert (res[TABLE2].status, res[TABLE2].input_missing) == ("warning", True)
    ctx = ctx_of(app, rid)
    orders = ctx.get("G-02a.reworkOrders")
    assert [o.targets for o in orders] == [["성장전략"]]                        # 입력 없음 warning은 후보에서 뺀다
    report = ctx.get("scoreReport.document")
    assert INPUT_MISSING_NOTICE in report.notices
    assert ctx.get("G-02a.nextAction") == "진행가능"                            # 다음 동작은 점수(85.7 ≥ 80)로


def test_overall_judge_keeps_artifact_orders_and_uses_total_for_next_action(clock):
    app = make_app(clock, StubScenario(doc_scores=[60.0], warning_items={"3.6.1"}, art_scores=[(12.0, 7.0)]))
    rid = to_screen9(app)
    ctx = ctx_of(app, rid)
    orders = ctx.get("G-02b.reworkOrders")
    assert [(o.layer, o.targets) for o in orders if o.layer == "document"] == [("document", ["성장전략"])]
    assert {o.task_id for o in orders if o.layer == "artifact"} == {"T-B1"}     # 산출물층 후보 규칙은 그대로
    report = ctx.get("scoreReport.overall")
    assert report.total == 79.5 and ctx.get("G-02b.nextAction") == "재작성권유"  # 두 층 합산 점수로
    assert report.notices == []


def test_display_score_uses_doc_layer_max_setting(clock):
    s = Settings()
    s.scoring.doc_layer_max = 60
    app = make_app(clock, StubScenario(doc_scores=[52.0]), settings=s)
    rid = to_screen6(app)
    ctx = ctx_of(app, rid)
    assert ctx.get("scoreReport.document").display_score == 86.7                 # 52 ÷ 60 × 100 (70이면 74.3)
    assert ctx.get("G-02a.nextAction") == "진행가능" and ctx.get("G-02a.reworkOrders") == []


def test_plan_doc_ref_is_verified_ref(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    tv1 = records_of_task(app, rid, "T-V1")[0]
    ref = next(i for i in tv1.inputs if i.startswith("planDoc@"))
    assert {r.verified_ref for r in ctx_of(app, rid).get("sectionResults")} == {ref}


# ── 자체 검사 재수행 (항목 단위 · 횟수 따로 · T-W3 바로 대체) ──────────
def test_self_check_redo_targets_failed_items_and_counts_apart_from_verify1(clock):
    sc = StubScenario(fail_item_times={BODY: 1}, check_fail_items={"T-W1": [BODY]})
    app = make_app(clock, sc)
    spec = app.registry.get("T-W1")
    original = spec.fn

    def fn(inp, tools):   # 검증-1 재수행으로 다시 쓴 T-W1이 자체 검사에 한 번 걸리게 한다
        ri = inp.rework_input
        if ri is not None and ri.redo_source == "검증-1":
            sc.check_fail_times["T-W1"] = sc._counters.get("check:T-W1", 0) + 1
        return original(inp, tools)
    app.registry.bind("T-W1", fn)
    rid = to_screen6(app)
    assert writing_steps(app, rid)[6:] == ["T-V1", "T-W1", "T-W1", "M-1", "T-V1", "G-02a"]
    verify1, check = rework_inputs(app, rid, "T-W1")                              # 첫 작성은 입력 없음
    assert (verify1.redo_source, list(verify1.target_items)) == ("검증-1", [BODY])
    assert (check.mode, check.redo_source, check.unit) == ("재수행", "검사", "섹션")
    assert check.target_items == {BODY: ["T-W1 검사 불통과 2"]}                   # 걸린 항목만 (check.failedItems)
    recs = records_of_task(app, rid, "T-W1")
    assert [(r.trigger, r.redo_count) for r in recs[1:]] == [("재수행", 0), ("재수행", 1)]   # 횟수를 따로 센다
    assert app.store.load_run(rid).verify1.redo_counts == {BODY: 1}


def test_self_check_redo_without_failed_items_keeps_previous_targets(clock):
    sc = StubScenario(fail_item_times={BODY: 1})
    app = make_app(clock, sc)
    spec = app.registry.get("T-W1")
    original = spec.fn

    def fn(inp, tools):
        ri = inp.rework_input
        if ri is not None and ri.redo_source == "검증-1":
            sc.check_fail_times["T-W1"] = sc._counters.get("check:T-W1", 0) + 1
        return original(inp, tools)
    app.registry.bind("T-W1", fn)
    rid = to_screen6(app)
    check = rework_inputs(app, rid, "T-W1")[-1]
    assert (check.redo_source, list(check.target_items)) == ("검사", [BODY])      # 모든 항목으로 넓히지 않는다
    assert calls(app, f"섹션 {BODY} 작성") == 3 and calls(app, "섹션 3.1.1 작성") == 1


def test_table_task_check_failure_replaces_table_at_once_without_redo(clock):
    app = make_app(clock, StubScenario(check_fail_times={"T-W3": 1}, check_fail_items={"T-W3": [TABLE]}))
    rid = to_screen6(app)
    assert writing_steps(app, rid).count("T-W3") == 1                            # 재수행 0회
    ctx = ctx_of(app, rid)
    check = ctx.get("T-W3.check")
    assert not check.passed and check.final_action == "표 제거 · 본문 서술 대체" and list(check.failed_items) == [TABLE]
    assert ctx.get("tableOutputs")[TABLE]["tableFallbackUsed"]
    assert not [e for e in app.store.events(rid) if e.kind == "확정동작누락"]
    assert "T-W3.reworkInput" not in app.store.get_pointers(rid)
    assert "표 제거 · 본문 서술 대체" in ctx.get("scoreReport.document").notices


# ── 재작성 사이클 (태그 묶음 · 사이클 안 검증-1 재수행) ──────────────
def test_screen6_rework_remakes_bundle_items_and_runs_verify1_before_compare(clock):
    sc = StubScenario(doc_scores=[52.0, 52.0, 55.0, 60.0], fail_items={"3.5.1"})
    app = make_app(clock, sc)
    app.engine.flow.rewriter = rewrite_guidance
    for task_id in ("T-W1", "T-W2", "T-W3", "T-V1"):
        counting(app, task_id, "-", lambda n: None)
    rid = to_screen6(app)
    before = results(app, rid)
    calls_before = calls(app, "섹션 3.5.1 작성")
    [acc] = rework(app, clock, rid, "실현가능성")
    # 고른 묶음 항목(본문 3.5.1 · 표 3.5.2 · 3.5.3)만 → 검증-1 재수행(3.5.1 fail) → 전후 비교 → G-02a
    assert cycle_steps(app, rid, acc.cycle_id) == ["T-W1", "T-W3", "M-1", "T-V1", "T-W1", "M-1", "T-V1", "G-02a"]
    assert calls(app, "섹션 3.5.1 작성") - calls_before == 2 and calls(app, "섹션 3.4.1 작성") == 1
    assert calls(app, "섹션 3.1.1 작성") == 1                                    # 태그 없는 항목(일반현황)은 그대로
    tw1 = rework_inputs(app, rid, "T-W1")
    cycle_w1 = [ri for ri in tw1 if ri.mode == "재작성"][-1]
    assert cycle_w1.target_items == {"3.5.1": ["3.5.1 결함 (스텁)"]}           # 문제 목록 = 직전 issues + warnings
    tw3 = rework_inputs(app, rid, "T-W3")[-1]
    assert (tw3.mode, tw3.target_items) == ("재작성", {TABLE: [], TABLE2: []})
    tv1 = rework_inputs(app, rid, "T-V1")
    assert [(ri.mode, sorted(ri.target_items)) for ri in tv1[-2:]] == [
        ("재작성", ["3.5.1", TABLE, TABLE2]), ("재수행", ["3.5.1"])]
    # 다시 쓴 항목만 다시 검증하고 나머지는 이어받는다 (verifiedRef 그대로)
    after = results(app, rid)
    assert after[BODY].verified_ref == before[BODY].verified_ref
    assert after[TABLE].verified_ref != before[TABLE].verified_ref
    # 전후 비교는 검증-1 재수행 뒤 마지막 점수로 한 번
    [comp] = [c for c in app.store.comparisons(rid) if c.cycle_id == acc.cycle_id]
    assert (comp.before_score, comp.after_score, comp.kept) == (52.0, 60.0, "후")   # 55(재작성 T-V1)가 아니라 60
    assert ctx_of(app, rid).get("docScore").total == 60.0
    # 기회는 고른 묶음만, 흐름 상태는 이 사이클 것으로 새로 시작했다가 끝에서 비운다
    assert usage_of(app, rid) == {"실현가능성": (1, 0)}
    v = app.store.load_run(rid).verify1
    assert (v.cycle_key, v.made_items, v.redo_counts, v.phase, v.pending_items) == (
        acc.cycle_id, ["3.5.1", TABLE, TABLE2], {"3.5.1": 1}, "없음", {})
    # T-W3 · T-V1에는 지시문 다시 쓰기 호출이 없다 — T-W1만 첫 작성 검증-1 재수행 · 재작성 · 사이클 안 검증-1 재수행 각각 한 번
    rewrites = [r.metadata["task_id"] for r in app.llm.requests if r.metadata["purpose"] == PURPOSE_REWRITE]
    assert rewrites == ["T-W1"] * 3


def test_screen9_document_rework_puts_verify1_redo_before_html(clock):
    app = make_app(clock, StubScenario(fail_items={BODY}))
    rid = to_screen9(app)
    [acc] = rework(app, clock, rid, "문제인식")
    assert cycle_steps(app, rid, acc.cycle_id) == [
        "T-W1", "M-1", "T-V1", "T-W1", "M-1", "T-V1", "T-B1", "G-04", "M-3", "T-V2", "G-02b"]
    assert usage_of(app, rid) == {"문제인식": (1, 0)}


def test_resume_during_verify1_redo_keeps_targets(clock):
    app = make_app(clock, StubScenario(fail_item_times={BODY: 1}))

    def action(n: int) -> None:
        if 2 <= n <= 7:   # 검증-1 재수행의 T-W1 호출이 재시도를 다 쓴다 (재시도 5회 + 처음)
            raise TimeoutError()
    counting(app, "T-W1", f"섹션 {BODY} 작성", action)
    rid = to_screen6(app)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기" and run.current_task == "T-W1"
    assert (run.verify1.phase, list(run.verify1.pending_items)) == ("재수행중", [BODY])
    clock.advance(minutes=16)
    assert app.orchestrator.tick(clock.t) == [rid]
    assert app.store.load_run(rid).state.step == "문서평가"
    redo = records_of_task(app, rid, "T-W1")[-1]
    assert redo.resume_count == 1 and redo.rework_role == VERIFY1_ROLE
    assert [list(ri.target_items) for ri in rework_inputs(app, rid, "T-W1")] == [[BODY]]   # 같은 재수행 입력으로 이었다
    assert results(app, rid)[BODY].status == "pass"
    assert app.store.load_run(rid).verify1.phase == "없음"


def test_rework_failure_during_verify1_redo_rolls_back_and_clears_state(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0], fail_items={BODY}))

    def action(n: int) -> None:
        if n >= 4:        # 1 첫 작성 · 2 첫 작성 재수행 · 3 재작성 · 4 재작성 안 검증-1 재수행 → 영구 오류
            from sbrain.orchestrator.errors import ProviderError
            raise ProviderError("401", status=401)
    counting(app, "T-W1", f"섹션 {BODY} 작성", action)
    rid = to_screen6(app)
    before = app.store.get_pointers(rid)
    rework(app, clock, rid, "문제인식")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.last_rework.status) == ("문서평가", "사용자대기", "실패")
    assert usage_of(app, rid) == {"문제인식": (0, 1)}                           # 기회 반환
    assert app.store.get_pointers(rid)["planDoc"] == before["planDoc"]
    assert (run.verify1.phase, run.verify1.pending_items) == ("없음", {})


def test_abort_during_verify1_redo_clears_state(clock):
    app = make_app(clock, StubScenario(fail_items={BODY}))
    box: list[str] = []

    def action(n: int) -> None:
        if n == 2:        # 검증-1 재수행 T-W1 도중 중단 요청 — 단계 사이에서 반영된다
            app.store.request_abort(box[0])
    counting(app, "T-W1", f"섹션 {BODY} 작성", action)
    real_start = app.orchestrator.start_writing

    def start(rid):
        box.append(rid)
        return real_start(rid)
    app.orchestrator.start_writing = start
    rid = to_screen6(app)
    run = app.store.load_run(rid)
    assert run.state.progress == "중단"
    assert (run.verify1.phase, run.verify1.pending_items) == ("없음", {})


# ── 짝짓기 한 곳 (spec 4.6) ─────────────────────────────────
def test_pairing_table_swap_drives_targets_candidates_and_image_rework(clock, monkeypatch):
    table = dict(rework_map.SECTION_BUNDLE_TABLE)
    table["3.3"] = ("1-1", "문제인식")      # 시험용 짝짓기 — 개요 · 그림(3.3.x)을 문제인식 묶음에
    monkeypatch.setattr(rework_map, "SECTION_BUNDLE_TABLE", table)
    assert rework_map.section_tags(["3.3.6", "3.1.1"]) == ["1-1", None]
    app = make_app(clock, StubScenario(fail_item_times={IMAGE: 2}))
    rid = to_screen6(app)
    assert writing_steps(app, rid)[6:] == ["T-V1", "T-W2", "M-1", "T-V1", "G-02a"]   # 그림 fail → T-W2 재수행
    orders = ctx_of(app, rid).get("G-02a.reworkOrders")
    assert [(o.task_id, o.targets) for o in orders] == [("T-W1", ["문제인식"])]      # 묶음 첫 항목 3.3.1은 본문
    [acc] = rework(app, clock, rid, "문제인식")
    assert cycle_steps(app, rid, acc.cycle_id) == ["T-W1", "T-W2", "M-1", "T-V1", "G-02a"]
    tw2 = rework_inputs(app, rid, "T-W2")[-1]
    assert (tw2.mode, tw2.target_items) == ("재작성", {IMAGE: [f"{IMAGE} 결함 (스텁)"]})
    tw1 = rework_inputs(app, rid, "T-W1")[-1]
    assert list(tw1.target_items) == ["3.3.1", "3.3.2", "3.3.3", "3.3.4", "3.3.5", BODY]
    assert calls(app, f"그림 {IMAGE} 작성") == 3                                 # 첫 작성 · 검증-1 재수행 · 재작성
    assert results(app, rid)[IMAGE].status == "pass"


def test_bundle_orders_pick_tasks_by_item_kind(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    form = ctx_of(app, rid).get("formSpec")
    assert list(bundle_orders(["문제인식"], [], form)) == ["T-W1"]
    assert list(bundle_orders(["실현가능성"], [], form)) == ["T-W1", "T-W3"]
    assert list(bundle_orders(["문제인식", "성장전략"], [], form)) == ["T-W1", "T-W3"]
    assert list(bundle_orders(["문제인식"], [])) == ["T-W1", "T-W2", "T-W3"]       # 양식이 없으면 세 Task 모두
    assert pid(app, rid)
