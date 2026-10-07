"""산출물층 검증 반영 (작업지시 C1 ~ C10 · spec 4 · 3.3).

- 계약 확장 필드 · T-V2 입력(planDoc) · 출력(diagnostics) · G-04 자체 검사
- 산출물층 미달 → 다시 돌릴 Task (artifact_rework_reasons — 통과 필수 조건 · 결함 출처 · 누락 · 부분 인정 · 보류)
- 스텁 T-V2의 1.4판 점수식(부분 0.5) · 보류 · 진단 · 통과 필수 조건
- 원페이지 계획서 재작성의 T-B2 → M-2 반영
- T-B1 계획서 입력 · 재실행 때 이전 원문(previous_source_text)
- T-B2 이미지 호출 실패 예외와 '이미지대체' 사건
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from conftest import executed, make_app, to_screen6, to_screen8, to_screen9
from flow_helpers import ctx_of, cycle_steps, last_cycle_id, records_of_task, rework, usage_of

from sbrain.agents.stubs import HTML_NAMES, HTML_WEIGHTS, SVG_NAMES, SVG_WEIGHTS, StubScenario, bind_stubs
from sbrain.agents.supervisor.plan import PURPOSE_REWRITE
from sbrain.agents.supervisor.rewrite import rewrite_guidance
from sbrain.contracts import tasks as c
from sbrain.flow import rework_map
from sbrain.flow.catalog import build_registry
from sbrain.flow.rework_map import (
    CODE_CHECK_TARGET, DEFECT_SOURCE_TARGET, FEATURE_MISSING_TARGET, GATE_TARGET, TASK_BUNDLE,
    artifact_rework_reasons,
)
from sbrain.models import (
    ArtifactScore, CodeCheck, CodeCheckResult, FeatureMatchResult, Infographic, ItemSpec, PlanDoc, Prototype,
    ReworkInput,
)
from sbrain.models.base import extension_fields
from sbrain.orchestrator.errors import ERROR_CODES, ToolCallExhausted
from sbrain.orchestrator.settings import PROVISIONAL

FEATURES = ["회원 등록·조회", "수업 예약"]   # 스텁 T-C1의 핵심 기능 = featureList
IMAGE_FALLBACK = "T-B2 이미지 호출 실패 — 기본 아이콘으로 계속"


# ── 도움 ─────────────────────────────────────────────
def events(app, rid, kind):
    return [e for e in app.store.events(rid) if e.kind == kind]


def code_check(kind: str, failed: dict[int, list[str]] | None = None, gate: list[str] | None = None,
               ) -> CodeCheckResult:
    """칸 8개 — failed: 불통과 칸 번호 → 결함 출처."""
    failed = failed or {}
    names = HTML_NAMES if kind == "html" else SVG_NAMES
    weights = HTML_WEIGHTS if kind == "html" else SVG_WEIGHTS
    checks = [CodeCheck(no=i + 1, name=names[i], weight=weights[i], passed=(i + 1) not in failed, detail="",
                        defect_sources=failed.get(i + 1, [])) for i in range(8)]
    total = 15 - sum(weights[n - 1] for n in failed)
    return CodeCheckResult(total=max(total, 0), checks=checks, gate_failures=gate or [])


def score(kind: str, *, failed=None, gate=None, missing=(), partial=(), withheld=False) -> ArtifactScore:
    cc = code_check(kind, failed, gate)
    fm = FeatureMatchResult(score=0 if withheld else 10, missing_features=list(missing),
                            partial_features=list(partial), extra_features=[], findings=["인정"],
                            judged_by="htmlParse" if kind == "html" else "svgTextParse", withheld=withheld,
                            withheld_reason="E-V2-NOFEATURE" if withheld else None)
    return ArtifactScore(total=cc.total + fm.score, code_check=cc, feature_match=fm)


# ── C1 · C7 · spec 4.1 ~ 4.3: 계약 확장 필드 ─────────────────────
def test_new_contract_fields_are_extensions():
    from sbrain.models import CheckResult
    assert "defectSources" in extension_fields(CodeCheck)
    assert "gateFailures" in extension_fields(CodeCheckResult)
    assert {"withheld", "withheldReason", "partialFeatures"} <= set(extension_fields(FeatureMatchResult))
    assert "planDoc" in extension_fields(c.TV2In)
    assert "diagnostics" in extension_fields(c.TV2Out)
    assert "check" in extension_fields(c.G04Out)
    assert "planDoc" in extension_fields(c.TB1In)
    assert "previousSourceText" in extension_fields(ReworkInput)
    # 기본값 — 담당자 코드가 채우기 전에도 검증을 통과한다
    fm = FeatureMatchResult(score=0, missing_features=[], extra_features=[], findings=[], judged_by="htmlParse")
    assert (fm.withheld, fm.withheld_reason, fm.partial_features) == (False, None, [])
    assert c.G04Out(readme_path="/README.md").check is None
    assert c.G04Out.model_fields["check"].annotation == CheckResult | None
    assert ReworkInput(mode="재수행", previous_result_ref="x@1", issues=[], is_final_attempt=False
                       ).previous_source_text is None
    # 스키마에 x-extension 표시
    schema = FeatureMatchResult.model_json_schema(by_alias=True)
    assert schema["properties"]["partialFeatures"]["x-extension"] is True


def test_catalog_wires_plan_doc_diagnostics_and_g04_check():
    r = build_registry()
    tv2, tb1, g04 = r.get("T-V2"), r.get("T-B1"), r.get("G-04")
    assert (tv2.inputs["plan_doc"].kind, tv2.inputs["plan_doc"].key) == ("art", "planDoc")
    assert tv2.outputs["diagnostics"] == "T-V2.diagnostics"
    assert (tb1.inputs["plan_doc"].kind, tb1.inputs["plan_doc"].key) == ("art", "planDoc")
    assert g04.outputs["check"] == "G-04.check" and g04.redo
    assert g04.failure.on_step_error == "continue"


# ── C4 · spec 4.1: 산출물층 미달 → 다시 돌릴 Task ─────────────────
def test_rework_map_tables():
    assert 2 not in CODE_CHECK_TARGET["html"]
    assert set(CODE_CHECK_TARGET["html"].values()) == {"T-B1"}
    assert CODE_CHECK_TARGET["svg-onepage"] == {n: "T-B2" for n in range(1, 9)}
    assert GATE_TARGET == {"html": "T-B1", "svg-onepage": "T-B2"}
    assert DEFECT_SOURCE_TARGET == {"prototype": "T-B1", "infographic": "T-B2"}
    assert FEATURE_MISSING_TARGET == {"html": "T-B1", "svg-onepage": "T-B2"}
    assert "G-04" not in TASK_BUNDLE
    assert not hasattr(rework_map, "BUNDLE_README") and not hasattr(rework_map, "LIST_README_BUNDLE")


@pytest.mark.parametrize("kind,target", [("html", "T-B1"), ("svg-onepage", "T-B2")])
def test_gate_failure_sends_only_category_target(kind, target):
    every = {n: ["prototype", "infographic"] for n in range(1, 9)}
    s = score(kind, failed=every, gate=["entry", "sandbox"], missing=FEATURES, partial=["x"])
    assert artifact_rework_reasons(s, kind) == {target: ["통과 필수 조건 실패: entry, sandbox"]}


@pytest.mark.parametrize("sources,targets", [
    (["prototype"], {"T-B1"}), (["infographic"], {"T-B2"}), (["prototype", "infographic"], {"T-B1", "T-B2"}),
    ([], {"T-B2"}),                                              # 결함 출처가 없으면 T-B2로 (잠정)
])
def test_html_alt_text_goes_by_defect_sources(sources, targets):
    reasons = artifact_rework_reasons(score("html", failed={2: sources}), "html")
    assert set(reasons) == targets
    assert all(any("2번" in line for line in lines) for lines in reasons.values())


def test_other_html_checks_go_to_tb1_and_g04_never_listed():
    every = {n: ["prototype"] for n in range(1, 9)}
    reasons = artifact_rework_reasons(score("html", failed=every), "html")
    assert set(reasons) == {"T-B1"} and len(reasons["T-B1"]) == 8
    reasons = artifact_rework_reasons(score("svg-onepage", failed={n: [] for n in range(1, 9)}), "svg-onepage")
    assert set(reasons) == {"T-B2"}


@pytest.mark.parametrize("kind,target", [("html", "T-B1"), ("svg-onepage", "T-B2")])
def test_feature_reasons_from_missing_and_partial(kind, target):
    assert artifact_rework_reasons(score(kind), kind) == {}
    assert artifact_rework_reasons(score(kind, missing=["a", "b"]), kind) == {target: ["누락 기능: a, b"]}
    assert artifact_rework_reasons(score(kind, partial=["c"]), kind) == {target: ["부분 인정 기능: c"]}
    assert artifact_rework_reasons(score(kind, missing=["a"], partial=["c"]), kind) == {
        target: ["누락 기능: a", "부분 인정 기능: c"]}
    # 보류면 대조 사유를 넣지 않는다
    assert artifact_rework_reasons(score(kind, missing=["a"], partial=["c"], withheld=True), kind) == {}


def test_flow_does_not_branch_on_findings_text():
    s = score("html")
    s.feature_match.findings = ["누락 기능: 가짜", "통과 필수 조건 실패로 검사 생략: entry"]
    assert artifact_rework_reasons(s, "html") == {}


# ── C8 · spec 4: 스텁 T-V2 ───────────────────────────────
def stub_fn(task_id: str, sc: StubScenario):
    r = build_registry()
    bind_stubs(r, sc)
    return r.get(task_id).fn


def tv2_in(features: list[str], kind: str = "html") -> c.TV2In:
    proto = Prototype(entry_file_path="/index.html", kind=kind, source_text="<html></html>", asset_paths=[],
                      implemented_features=features)
    return c.TV2In(prototype=proto, infographic=Infographic(image_path="/i.png", format="png", alt_text="i"),
                   feature_list=features, plan_doc=PlanDoc(sections=[], feature_list=features, charts=[], tables=[],
                                                           protected_tokens=[]))


TOOLS = SimpleNamespace(llm=lambda *a, **k: None)
F4 = ["f1", "f2", "f3", "f4"]


@pytest.mark.parametrize("knob,full,partial,missing,points,first", [
    (15.0, ["f1", "f2", "f3", "f4"], [], [], 15.0, "인정 4/4개 (규칙 4건 → LLM 확인: 충족 4 · 부분 0 · 미충족 0)"),
    (11.0, ["f1", "f2", "f3"], [], ["f4"], 11.25, "인정 3/4개 (규칙 4건 → LLM 확인: 충족 3 · 부분 0 · 미충족 1)"),
    (10.0, ["f1", "f2"], ["f3"], ["f4"], 9.375, "인정 2.5/4개 (규칙 4건 → LLM 확인: 충족 2 · 부분 1 · 미충족 1)"),
    (0.0, [], [], F4, 0.0, "인정 0/4개 (규칙 4건 → LLM 확인: 충족 0 · 부분 0 · 미충족 4)"),
])
def test_stub_tv2_partial_formula(knob, full, partial, missing, points, first):
    out = stub_fn("T-V2", StubScenario(art_scores=[(15.0, knob)]))(tv2_in(F4), TOOLS)
    fm = out.feature_match
    assert (fm.missing_features, fm.partial_features, fm.score) == (missing, partial, points)
    assert fm.findings[0] == first and not fm.withheld
    assert out.artifact_score.total == 15.0 + points


def test_stub_tv2_scenario_partial_list_reassigns_rest():
    out = stub_fn("T-V2", StubScenario(art_scores=[(15.0, 10.0)], partial_features=["f1"]))(tv2_in(F4), TOOLS)
    fm = out.feature_match
    assert (fm.partial_features, fm.missing_features, fm.score) == (["f1"], ["f4"], 9.375)
    assert fm.findings[0] == "인정 2.5/4개 (규칙 4건 → LLM 확인: 충족 2 · 부분 1 · 미충족 1)"


def test_stub_tv2_withheld_diagnostics_and_gate():
    out = stub_fn("T-V2", StubScenario())(tv2_in([]), TOOLS)
    fm = out.feature_match
    assert (fm.withheld, fm.withheld_reason, fm.score, fm.missing_features) == (True, "E-V2-NOFEATURE", 0, [])
    out = stub_fn("T-V2", StubScenario(withhold_feature_match=True, diagnostics=["진단 1"]))(tv2_in(F4), TOOLS)
    assert out.feature_match.withheld and out.feature_match.score == 0 and out.diagnostics == ["진단 1"]
    assert out.artifact_score.total == out.code_check.total
    out = stub_fn("T-V2", StubScenario(gate_failures=["secret"]))(tv2_in(F4), TOOLS)
    assert out.code_check.gate_failures == ["secret"] and out.artifact_score.total == 0


def test_stub_code_check_names_weights_and_defect_sources():
    assert HTML_WEIGHTS == [3, 2, 2, 2, 1, 2, 2, 1] and sum(SVG_WEIGHTS) == 15
    assert HTML_NAMES == ["동작 연결", "대체 텍스트", "label 연결", "명도 대비", "제목 계층", "1440px 폭",
                          "스크립트 동작 오류 없음", "임시 문구 없음"]
    assert SVG_WEIGHTS == [2, 3, 2, 2, 2, 2, 1, 1]
    assert SVG_NAMES == ["대체 텍스트", "핵심 정보 6항목", "명도 대비", "정보 계층", "잘림 없음", "지면 밖 넘침 없음",
                         "텍스트 실재성", "최소 글자 크기"]
    out = stub_fn("T-V2", StubScenario(art_scores=[(3.0, 15.0)]))(tv2_in(F4), TOOLS)
    alt = out.code_check.checks[1]
    assert not alt.passed and alt.defect_sources == ["infographic"]
    out = stub_fn("T-V2", StubScenario(art_scores=[(3.0, 15.0)], alt_defect_sources=["prototype"]))(tv2_in(F4), TOOLS)
    assert out.code_check.checks[1].defect_sources == ["prototype"]


def test_stub_tb1_entry_is_index_html():
    tb1 = stub_fn("T-B1", StubScenario())
    out = tb1(c.TB1In(feature_list=F4, item_spec=ItemSpec(item_name="i", one_line_summary="s", target_customer="t",
                                                          core_features=F4, category="웹개발", keywords=[]),
                      category="웹개발", instruction="지시"), TOOLS)
    assert out.entry_file_path == "/index.html" and out.prototype.entry_file_path == "/index.html"


# ── C9 · 잠정 표시 ─────────────────────────────────────────
def test_error_codes_and_provisional_events():
    assert "검증-2 통과 필수 조건(entry)" in ERROR_CODES["E-B1-ENTRY"].handling
    sandbox = ERROR_CODES["E-B1-SANDBOX"]
    assert (sandbox.where, sandbox.message) == ("T-B1", "")
    assert ERROR_CODES["E-V2-NOFEATURE"].message == ""
    assert "withheld=true" in ERROR_CODES["E-V2-NOFEATURE"].handling
    for kind in ("대조보류", "검증2진단", "안내문서자체검사실패", "이미지대체"):
        assert f"event.{kind}" in PROVISIONAL


# ── C2 · C3 · 4.2: 흐름 — 입력 연결 · 보류 · 진단 ─────────────────
def test_tv2_and_tb1_receive_plan_doc(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    [tv2] = records_of_task(app, rid, "T-V2")
    [tb1] = records_of_task(app, rid, "T-B1")
    assert any(i.startswith("planDoc@") for i in tv2.inputs)
    assert any(i.startswith("planDoc@") for i in tb1.inputs)
    assert ctx_of(app, rid).get("T-V2.diagnostics") == []


def test_withheld_match_adds_admin_event_scores_zero_and_continues(clock):
    app = make_app(clock, StubScenario(withhold_feature_match=True, diagnostics=["진단 하나", "진단 둘"]))
    rid = to_screen8(app)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("산출물확인", "사용자대기")
    [held] = events(app, rid, "대조보류")
    assert held.detail == "T-V2 대조 판정 보류 (E-V2-NOFEATURE) — 0점 합산"
    [tv2] = records_of_task(app, rid, "T-V2")
    assert held.execution_id == tv2.execution_id
    assert [e.detail for e in events(app, rid, "검증2진단")] == ["진단 하나", "진단 둘"]
    ctx = ctx_of(app, rid)
    report = ctx.get("scoreReport.overall")
    art = ctx.get("artifactScore")
    assert art.feature_match.score == 0 and art.total == art.code_check.total
    assert report.total == round(ctx.get("docScore").total + art.total, 1)
    assert not any("누락 기능" in o.reason or "부분 인정" in o.reason for o in report.rework_orders)


def test_no_events_when_match_judged(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    assert events(app, rid, "대조보류") == [] and events(app, rid, "검증2진단") == []


@pytest.mark.parametrize("category,target", [("웹개발", "T-B1"), ("원페이지", "T-B2")])
def test_partial_only_creates_rework_order(clock, category, target):
    app = make_app(clock, StubScenario(category=category, art_scores=[(15.0, 15.0)], partial_features=["수업 예약"]))
    rid = to_screen8(app)
    art = ctx_of(app, rid).get("artifactScore")
    assert art.feature_match.partial_features == ["수업 예약"] and art.feature_match.missing_features == []
    orders = [o for o in ctx_of(app, rid).get("G-02b.reworkOrders") if o.layer == "artifact"]
    assert [o.task_id for o in orders] == [target]
    assert "부분 인정 기능: 수업 예약" in orders[0].reason and "누락 기능" not in orders[0].reason


# ── C7: G-04 자체 검사 ─────────────────────────────────────
def test_g04_self_check_redo_then_continue(clock):
    app = make_app(clock, StubScenario(check_fail_times={"G-04": 1}))
    rid = to_screen8(app)
    assert executed(app, rid).count("G-04") == 2
    assert events(app, rid, "안내문서자체검사실패") == []
    assert app.store.load_run(rid).state.step == "산출물확인"


def test_g04_self_check_exhausted_records_event_and_continues(clock):
    app = make_app(clock, StubScenario(check_fail_times={"G-04": 9}))
    rid = to_screen8(app)
    assert executed(app, rid).count("G-04") == 3                        # 재수행 횟수 2
    [ev] = events(app, rid, "안내문서자체검사실패")
    assert ev.execution_id == records_of_task(app, rid, "G-04")[-1].execution_id
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("산출물확인", "사용자대기")
    orders = ctx_of(app, rid).get("G-02b.reworkOrders")
    assert all(o.task_id != "G-04" for o in orders)


# ── C6: 원페이지 계획서 재작성의 T-B2 반영 ─────────────────────────
def test_onepage_screen9_document_rework_reflects_infographic(clock):
    app = make_app(clock, StubScenario(category="원페이지"))
    rid = to_screen9(app)
    rework(app, clock, rid, "성장전략")
    cyc = last_cycle_id(app, rid)
    assert cycle_steps(app, rid, cyc) == [
        "T-W1", "T-W2", "T-W3", "M-1", "T-V1", "T-B2", "M-2", "G-04", "M-3", "T-V2", "G-02b"]
    [tb2] = [r for r in records_of_task(app, rid, "T-B2") if r.cycle_id == cyc]
    assert tb2.rework_role == "반영" and tb2.feedback_in == []
    assert not any(i.startswith("T-B2.reworkInput") for i in tb2.inputs)
    assert "T-B2.reworkInput" not in app.store.get_pointers(rid)
    assert usage_of(app, rid) == {"성장전략": (1, 0)}


def test_onepage_document_and_infographic_together_runs_tb2_once_as_target(clock):
    app = make_app(clock, StubScenario(category="원페이지", art_scores=[(12.0, 7.0)]))
    rid = to_screen9(app)
    rework(app, clock, rid, "성장전략", "인포그래픽")
    cyc = last_cycle_id(app, rid)
    assert cycle_steps(app, rid, cyc).count("T-B2") == 1
    [tb2] = [r for r in records_of_task(app, rid, "T-B2") if r.cycle_id == cyc]
    assert tb2.rework_role == "대상" and tb2.feedback_in
    assert any(i.startswith("T-B2.reworkInput@") for i in tb2.inputs)


def test_onepage_document_rework_drop_reverts_plan_infographic_and_prototype(clock):
    app = make_app(clock, StubScenario(category="원페이지", doc_scores=[52.0, 45.0],
                                       art_scores=[(12.0, 7.0), (12.0, 7.0)]))
    rid = to_screen9(app)
    before = app.store.get_pointers(rid)
    rework(app, clock, rid, "문제인식")
    after = app.store.get_pointers(rid)
    for key in ("planDoc", "infographic", "prototype"):
        assert after[key] == before[key], key
        assert app.store.get_latest_versions(rid)[key] > before[key]      # 새로 만들었다가 되돌렸다


# ── spec 4.3: 재실행 때 이전 원문 ───────────────────────────────
def numbered_html(app) -> None:
    """T-B1이 실행마다 다른 원문을 만든다 — '<html>원문표지-n</html>'."""
    base, n = app.registry.get("T-B1").fn, [0]

    def fn(inp, tools):
        out = base(inp, tools)
        text = f"<html>원문표지-{n[0]}</html>"
        n[0] += 1
        return out.model_copy(update={"prototype": out.prototype.model_copy(update={"source_text": text})})
    app.registry.bind("T-B1", fn)


def capture(app, task_id: str) -> list:
    seen, base = [], app.registry.get(task_id).fn

    def fn(inp, tools):
        seen.append(inp.rework_input)
        return base(inp, tools)
    app.registry.bind(task_id, fn)
    return seen


def test_previous_source_text_on_target_rework(clock):
    app = make_app(clock, StubScenario(art_scores=[(12.0, 7.0)]))
    numbered_html(app)
    seen = capture(app, "T-B1")
    rid = to_screen8(app)
    assert seen == [None]                                                  # 첫 실행은 재작성 입력이 없다
    rework(app, clock, rid, "실행 파일")
    ri = seen[-1]
    assert ri.mode == "재작성" and ri.previous_source_text == "<html>원문표지-0</html>"


def test_previous_source_text_on_redo_including_reflect_run(clock):
    app = make_app(clock, StubScenario(check_fail_times={"T-B1": 1}))
    numbered_html(app)
    seen = capture(app, "T-B1")
    rid = to_screen9(app)
    first, redo = seen
    assert first is None and redo.mode == "재수행" and redo.previous_source_text == "<html>원문표지-0</html>"
    app.scenario.check_fail_times["T-B1"] = 3                             # 반영 실행 불통과 → 재수행
    rework(app, clock, rid, "문제인식")
    reflect, reflect_redo = seen[2:]
    assert reflect.mode == "재작성" and reflect.previous_source_text is None   # 반영은 채우지 않는다
    assert reflect_redo.mode == "재수행" and reflect_redo.previous_source_text == "<html>원문표지-2</html>"


def test_previous_source_text_not_filled_for_other_tasks(clock):
    app = make_app(clock, StubScenario(category="원페이지", art_scores=[(12.0, 7.0)],
                                       check_fail_times={"T-S1": 1, "T-B2": 1}))
    s1, b2 = capture(app, "T-S1"), capture(app, "T-B2")
    rid = to_screen8(app)
    rework(app, clock, rid, "인포그래픽")
    assert s1[1].mode == "재수행" and s1[1].previous_source_text is None
    assert b2[1].mode == "재수행" and b2[1].previous_source_text is None
    assert b2[-1].mode == "재작성" and b2[-1].previous_source_text is None


def test_resume_reuses_same_rework_input(clock):
    app = make_app(clock, StubScenario(check_fail_times={"T-B1": 1}))
    numbered_html(app)
    seen = capture(app, "T-B1")
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.llm.plan("T-B1", ["ok"] + ["timeout"] * 6)                        # 재수행 실행이 재시도를 다 쓴다
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기"
    ref = run.redo_state.rework_input_ref
    clock.advance(minutes=16)
    assert app.orchestrator.tick(clock.t) == [rid]
    assert app.store.load_run(rid).state.step == "산출물확인"
    redo, resumed = seen[1], seen[2]
    assert resumed == redo and resumed.previous_source_text == "<html>원문표지-0</html>"
    assert ref in records_of_task(app, rid, "T-B1")[-1].inputs
    assert app.store.get_pointers(rid)["T-B1.reworkInput"] == int(ref.split("@")[1])


def test_previous_source_text_not_sent_to_rewrite_llm(clock):
    app = make_app(clock, StubScenario(art_scores=[(12.0, 7.0)], check_fail_times={"T-B1": 1}))
    app.engine.flow.rewriter = rewrite_guidance

    def reply(request):
        if request.metadata["purpose"] == PURPOSE_REWRITE:
            return json.dumps({"guidance": "새 안내"}, ensure_ascii=False)
        return '{"ok": true}'
    app.llm.respond("T-B1", reply)
    numbered_html(app)
    seen = capture(app, "T-B1")
    rid = to_screen8(app)
    rework(app, clock, rid, "실행 파일")
    assert [ri.previous_source_text for ri in seen if ri is not None] == [
        "<html>원문표지-0</html>", "<html>원문표지-1</html>"]
    asked = [r for r in app.llm.requests if r.metadata["purpose"] == PURPOSE_REWRITE]
    assert len(asked) == 2                                                # 재수행 · 재작성 대상
    for r in asked:
        assert "원문표지" not in "\n".join(m["content"] for m in r.messages)


def test_previous_source_text_not_in_records_or_admin_views(clock):
    app = make_app(clock, StubScenario(art_scores=[(12.0, 7.0)], check_fail_times={"T-B1": 1}))
    numbered_html(app)
    rid = to_screen8(app)
    rework(app, clock, rid, "실행 파일")
    o, s = app.orchestrator, app.store
    assert ctx_of(app, rid).get("T-B1.reworkInput").previous_source_text   # 산출물에만 있다
    parts = [r.dump() for r in s.executions(rid)] + [x.dump() for x in s.call_logs(rid)]
    parts += [e.dump() for e in s.events(rid)] + [f.dump() for f in s.feedback(rid)]
    parts += [r.dump() for r in o.admin_executions(limit=500)] + [o.admin_summary().dump()]
    parts += [x.dump() for r in s.executions(rid) for x in o.admin_calls(r.execution_id)]
    parts += [x.dump() for x in o.admin_runs(limit=500)]
    assert "원문표지" not in json.dumps(parts, ensure_ascii=False, default=str)


# ── spec 3.3: T-B2 이미지 호출 실패 예외 ─────────────────────────
def icon_tb2(app) -> None:
    """T-B2가 아이콘을 그리고, 이미지 호출이 재시도를 다 쓰면 기본 아이콘으로 계속한다(담당자 코드와 같은 모양)."""
    base = app.registry.get("T-B2").fn

    def fn(inp, tools):
        try:
            tools.image("아이콘을 그려라", purpose="아이콘")
        except ToolCallExhausted:
            pass   # 기본 아이콘
        return base(inp, tools)
    app.registry.bind("T-B2", fn)


def test_tb2_image_failure_continues_with_one_event(clock):
    app = make_app(clock)
    icon_tb2(app)
    app.image.plan("T-B2", ["timeout"] * 6)
    rid = to_screen8(app)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("산출물확인", "사용자대기")
    [tb2] = records_of_task(app, rid, "T-B2")
    assert tb2.status == "성공"
    [ev] = events(app, rid, "이미지대체")
    assert (ev.detail, ev.execution_id, ev.refs) == (IMAGE_FALLBACK, tb2.execution_id, [])


def test_no_image_event_when_image_succeeds(clock):
    app = make_app(clock)
    icon_tb2(app)
    rid = to_screen8(app)
    assert events(app, rid, "이미지대체") == []


def test_image_event_per_execution_record_across_redo(clock):
    app = make_app(clock, StubScenario(check_fail_times={"T-B2": 1}))
    icon_tb2(app)
    app.image.plan("T-B2", ["timeout"] * 12)                             # 두 실행 모두 이미지 실패
    rid = to_screen8(app)
    recs = records_of_task(app, rid, "T-B2")
    assert len(recs) == 2
    assert sorted(e.execution_id for e in events(app, rid, "이미지대체")) == sorted(r.execution_id for r in recs)


def test_tb2_text_call_failure_still_waits_for_resume(clock):
    app = make_app(clock)
    icon_tb2(app)
    app.llm.plan("T-B2", ["timeout"] * 6)
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기" and run.current_task == "T-B2"
    assert events(app, rid, "이미지대체") == []


def test_alt_text_without_defect_sources_records_event_and_tb2_reason(clock):
    # HTML 2번 미충족인데 결함 출처가 비었다(담당자 쪽 누락) — T-B2로 보내고 관리자 사건을 남긴다 (C4 규칙 2, 잠정)
    app = make_app(clock, StubScenario(art_scores=[(3.0, 15.0)], alt_defect_sources=[]))
    rid = to_screen8(app)
    [ev] = events(app, rid, "대체텍스트출처누락")
    [tv2] = records_of_task(app, rid, "T-V2")
    assert (ev.detail, ev.execution_id) == ("HTML 2번 미충족인데 defect_sources가 비어 있음 — T-B2로 보냄", tv2.execution_id)
    orders = {o.task_id: o for o in ctx_of(app, rid).get("G-02b.reworkOrders") if o.layer == "artifact"}
    assert "코드 검증 2번 대체 텍스트" in orders["T-B2"].reason
    assert "event.대체텍스트출처누락" in PROVISIONAL


def test_no_alt_text_event_when_defect_sources_given(clock):
    app = make_app(clock, StubScenario(art_scores=[(3.0, 15.0)]))
    rid = to_screen8(app)
    assert events(app, rid, "대체텍스트출처누락") == []
