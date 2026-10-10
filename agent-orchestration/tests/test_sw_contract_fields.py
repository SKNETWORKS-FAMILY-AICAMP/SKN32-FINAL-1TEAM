"""전략 · 작성 · 검증-1 끼우기 T1 — 계약 칸 · 새 타입 · 설정 · 함수별 모델 · 등록부 연결 · 스텁 새 칸 (spec 4.2 · 4.3 타입 ·
4.6 칸 · 4.7 · 4.8 칸 · 4.10 상태 칸 · 4.12 입력 · 4.13 연결 · 4.1 JSON 응답).

동작(재수행 · 재작성 · 후보 규칙)은 바꾸지 않는다 — 칸이 생기고 스텁이 새 칸을 규격대로 채우는지만 본다.
흐름 테스트는 clock · store_backend 장치로 메모리 · SQLite 두 저장소에서 돈다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from conftest import make_app, pre_input, to_screen6

from sbrain.agents.stubs import StubScenario
from sbrain.contracts import tasks as c
from sbrain.flow.catalog import artifact_types, build_registry
from sbrain.models import (
    BudgetItem, CheckResult, CompanyInfo, DiagramSpec, PlanDoc, PlanSection, PreInput, ReworkInput, Run,
    ScheduleItem, SectionResult, Verify1State, extension_fields,
)
from sbrain.models.clock import utc_now
from sbrain.orchestrator import settings as settings_mod
from sbrain.orchestrator.errors import FormatError, ToolCallExhausted
from sbrain.orchestrator.openai_provider import OpenAIProvider
from sbrain.orchestrator.registry import PARTIAL, REWORK
from sbrain.orchestrator.settings import RedoSettings, Settings, TaskModelSetting
from sbrain.orchestrator.tools import CallSink, LLMRequest, LLMResponse, TokenUsage, Tools, ToolsConfig, ToolsContext

DECISION = "결정 0024"


def _note(model, alias: str) -> str:
    return model.model_json_schema(by_alias=True)["properties"][alias].get("x-note", "")


def _ref(name: str = "userflow.svg") -> dict:
    return {"key": f"run-1/exec-1/abc/{name}", "name": name, "mediaType": "image/svg+xml", "size": 10,
            "sha256": "0" * 64}


# ── 새 타입 · 확장 칸 ──────────────────────────────────
NEW_TYPE_FIELDS = [
    (PreInput, {"budgetItems", "scheduleItems"}),
    (CompanyInfo, {"budgetItems", "scheduleItems"}),
    (PlanDoc, {"diagrams"}),
    (Run, {"verify1"}),
    (c.TV1Out, {"sectionResults"}),
    (c.TV1In, {"baseSectionResults"}),
    (c.TW2Out, {"diagrams"}),
    (c.TW2In, {"baseDiagrams"}),
    (c.M1In, {"diagrams"}),
    (c.G02aIn, {"sectionResults"}),
    (c.G02bIn, {"sectionResults"}),
]


@pytest.mark.parametrize(("model", "names"), NEW_TYPE_FIELDS, ids=[m.__name__ for m, _ in NEW_TYPE_FIELDS])
def test_new_type_fields_are_extensions_with_decision_note(model, names):
    assert names <= set(extension_fields(model))
    assert all(DECISION in _note(model, n) for n in names)


EXT_FIELDS = [
    (PreInput, {"teamRoleCareers"}),
    (CompanyInfo, {"teamRoleCareers"}),
    (PlanSection, {"tag", "contentType"}),
    (c.TS1In, {"companyInfo", "priorResults"}),
    (c.TS1Out, {"strategyData"}),
    (c.TS2In, {"strategyData", "priorResults"}),
    (c.TS2Out, {"marketStrategyData"}),
    (c.TW1In, {"strategyData", "marketStrategyData", "featureList", "basePlanDoc", "baseSectionOutputs",
               "priorResults"}),
    (c.TW1Out, {"sectionOutputs"}),
    (c.TW2In, {"strategyData", "featureList", "baseDiagramOutputs", "priorResults"}),
    (c.TW2Out, {"diagramOutputs"}),
    (c.TW3In, {"strategyData", "formSpec", "baseTables", "baseTableSections", "baseTableOutputs"}),
    (c.TW3Out, {"tableSections", "tableOutputs"}),
    (c.M1In, {"tableSections"}),
    (c.TV1In, {"strategyData", "marketStrategyData", "featureList", "formSpec", "sectionOutputs", "tableOutputs",
               "diagramOutputs", "companyInfo", "selectedAnnouncement", "reworkInput", "priorResults"}),
    (c.TV1Out, {"scorePolicyVersion"}),
    (CheckResult, {"failedItems"}),
    (ReworkInput, {"targetItems", "redoSource", "unit", "fallbackItems"}),
    (TaskModelSetting, {"purposeModels"}),
]


@pytest.mark.parametrize(("model", "names"), EXT_FIELDS, ids=[m.__name__ for m, _ in EXT_FIELDS])
def test_added_fields_are_extensions(model, names):
    assert names <= set(extension_fields(model))


@pytest.mark.parametrize("model", [BudgetItem, ScheduleItem, DiagramSpec, SectionResult, Verify1State])
def test_new_types_mark_every_field_as_extension(model):
    aliases = {info.alias or n for n, info in model.model_fields.items()}
    assert set(extension_fields(model)) == aliases


def test_new_fields_have_defaults_so_old_json_reads():
    pre = pre_input()
    assert (pre.budget_items, pre.schedule_items, pre.team_role_careers) == ([], [], [])
    sec = PlanSection.model_validate({"sectionCode": "1-1", "title": "t", "sentences": []})
    assert (sec.tag, sec.content_type) == (None, "section")
    plan = PlanDoc.model_validate({"sections": [], "featureList": [], "charts": [], "tables": [],
                                   "protectedTokens": []})
    assert plan.diagrams == []
    assert CheckResult(passed=True, failures=[]).failed_items == {}
    ri = ReworkInput(mode="재수행", previous_result_ref="x@1", issues=[], is_final_attempt=False)
    assert (ri.target_items, ri.redo_source, ri.unit, ri.fallback_items) == ({}, None, None, [])
    assert c.G02aIn.model_fields["section_results"].default is None
    assert c.G02bIn.model_fields["section_results"].default is None
    fs = c.FormSpec.model_validate({"formVersion": "v", "applicantTypes": [], "sectionCodes": ["1-1"],
                                    "sectionTitles": ["t"], "formatSpec": {"styleType": "개조식",
                                    "endingRule": "단정형", "bannedExpressions": []}, "attachmentRequired": False})
    assert (fs.section_tags, fs.section_kinds) == ([], [])


def test_new_type_shapes():
    b = BudgetItem(category="재료비", execution_plan="부품", total_amount=None, government_amount=1,
                   self_cash_amount=None, self_in_kind_amount=None)
    assert b.phase is None and b.dump()["totalAmount"] is None
    s = ScheduleItem(scope="agreement", category="개발", content="c", period="p", detail="d")
    assert s.dump()["scope"] == "agreement"
    with pytest.raises(ValidationError):
        ScheduleItem(scope="feasibility", category="개발", content="c", period="p", detail="d")
    d = DiagramSpec(diagram_id="2.3.6-USER_FLOW", flow_type="USER_FLOW", nodes=["a", "b", "c"], visual_style={},
                    source_ref="2.3.6", image_file=_ref())
    assert d.dump()["flowType"] == "USER_FLOW"
    for bad in (["a", "b"], ["a"] * 7, ["", "b", "c"], ["x" * 36, "b", "c"]):
        with pytest.raises(ValidationError):
            DiagramSpec(diagram_id="x", flow_type="USER_FLOW", nodes=bad, visual_style={}, source_ref="2.3.6",
                        image_file=_ref())
    r = SectionResult(section_code="2.4.1", content_type="section", status="fail", score=40.0,
                      verified_ref="planDoc@3")
    assert (r.tag, r.issues, r.warnings, r.needs_user_confirmation, r.input_missing, r.deductions) == (
        None, [], [], [], False, [])
    v = Verify1State(cycle_key="첫작성")
    assert (v.made_items, v.redo_counts, v.phase, v.pending_items) == ([], {}, "없음", {})
    run_json = {"runId": "r", "accountId": "a", "state": {"step": "계획서작성", "progress": "실행", "resumeStep": 5},
                "currentPhase": "document", "settingsSnapshot": {}, "updatedAt": "2026-10-10T00:00:00Z",
                "createdAt": "2026-10-10T00:00:00Z"}
    assert Run.model_validate(run_json).verify1 is None
    assert Run.model_validate({**run_json, "verify1": v.dump()}).verify1 == v


# ── 등록부 연결 ───────────────────────────────────────
OUTPUT_KEYS = {
    "T-S1": {"strategy_data": "strategyData"},
    "T-S2": {"market_strategy_data": "marketStrategyData"},
    "T-W1": {"section_outputs": "sectionOutputs"},
    "T-W2": {"diagrams": "diagrams", "diagram_outputs": "diagramOutputs", "charts": "charts"},
    "T-W3": {"table_sections": "tableSections", "table_outputs": "tableOutputs"},
    "T-V1": {"section_results": "sectionResults", "score_policy_version": "scorePolicyVersion"},
}

INPUT_ARTS = {
    "T-S1": {"company_info": ("companyInfo", False)},
    "T-S2": {"strategy_data": ("strategyData", False)},
    "T-W1": {"strategy_data": ("strategyData", False), "market_strategy_data": ("marketStrategyData", False),
             "feature_list": ("featureList", False), "base_plan_doc": ("planDoc", True),
             "base_section_outputs": ("sectionOutputs", True)},
    "T-W2": {"strategy_data": ("strategyData", False), "feature_list": ("featureList", False),
             "base_diagrams": ("diagrams", True), "base_diagram_outputs": ("diagramOutputs", True)},
    "T-W3": {"strategy_data": ("strategyData", False), "company_info": ("companyInfo", False),
             "form_spec": ("formSpec", False), "base_tables": ("tables", True),
             "base_table_sections": ("tableSections", True), "base_table_outputs": ("tableOutputs", True)},
    "M-1": {"diagrams": ("diagrams", False), "table_sections": ("tableSections", False)},
    "T-V1": {"strategy_data": ("strategyData", False), "market_strategy_data": ("marketStrategyData", False),
             "feature_list": ("featureList", False), "form_spec": ("formSpec", False),
             "section_outputs": ("sectionOutputs", False), "table_outputs": ("tableOutputs", False),
             "diagram_outputs": ("diagramOutputs", False), "company_info": ("companyInfo", False),
             "selected_announcement": ("selectedAnnouncement", False),
             "base_section_results": ("sectionResults", True)},
    "G-02a": {"section_results": ("sectionResults", True)},
    "G-02b": {"section_results": ("sectionResults", True)},
}


def test_registry_outputs_and_inputs():
    reg = build_registry()
    for tid, outs in OUTPUT_KEYS.items():
        assert outs.items() <= reg.get(tid).outputs.items(), tid
    for tid, ins in INPUT_ARTS.items():
        spec = reg.get(tid)
        for fname, (key, optional) in ins.items():
            b = spec.inputs[fname]
            assert (b.kind, b.key, b.optional) == ("art", key, optional), (tid, fname)


def test_registry_partial_rework_and_llm_flags():
    reg = build_registry()
    for tid in ("T-S1", "T-S2", "T-W1", "T-W2", "T-V1"):
        assert reg.get(tid).inputs["prior_results"] is PARTIAL, tid
    assert "prior_results" not in reg.get("T-W3").inputs        # 규칙 코드라 재개 이어 쓰기 대상이 아니다
    assert reg.get("T-V1").inputs["rework_input"] is REWORK
    assert reg.get("T-W3").uses_llm is False and reg.get("T-W3").redo is True
    for tid in ("T-S1", "T-S2", "T-W1", "T-W2", "T-V1"):
        assert reg.get(tid).uses_llm is True, tid


def test_artifact_types_cover_new_keys():
    exact, _ = artifact_types(build_registry())
    assert exact["sectionResults"] == list[SectionResult]
    assert exact["diagrams"] == list[DiagramSpec]
    assert exact["tableSections"] == list[PlanSection]
    assert exact["scorePolicyVersion"] is str
    for key in ("strategyData", "marketStrategyData", "sectionOutputs", "diagramOutputs", "tableOutputs"):
        assert key in exact, key


# ── 설정 ─────────────────────────────────────────────
TABLE = {
    "T-S1": ("gpt-5.6-terra", {"F01": "gpt-6-luna", "F05": "gpt-6-luna", "F06": "gpt-5.6-sol", "F07": "gpt-6.1-sol",
                               "F08": "gpt-6.1-sol", "F09": "gpt-5.6-terra", "F13": "gpt-6-luna",
                               "F14": "gpt-6-luna", "F15": "gpt-6-luna"}),
    "T-S2": ("gpt-6.1-sol", {"F04": "gpt-5.6-terra"}),
    "T-W1": ("gpt-5.6-sol", {}),
    "T-W2": ("gpt-6-luna", {}),
    "T-V1": ("gpt-5.6-terra", {}),
}


def test_default_tasks_follow_partner_table():
    t = Settings().tasks
    assert "T-W3" not in t
    for tid, (model, purposes) in TABLE.items():
        row = t[tid]
        assert (row.provider, row.model, row.temperature, row.reasoning_effort, row.purpose_models) == (
            "openai", model, None, None, purposes), tid
    assert t["T-C1"].purpose_models == {}
    assert Settings().task_timeouts["T-W3"] == 120.0             # 제한 시간 항목은 남긴다
    assert Settings().redo.verify1_redo_count == 1 and RedoSettings().verify1_redo_count == 1


def test_snapshot_without_purpose_models_reads():
    snap = Settings().dump()
    for row in snap["tasks"].values():
        row.pop("purposeModels")
    back = Settings.model_validate(snap)
    assert all(v.purpose_models == {} for v in back.tasks.values())
    redo = dict(snap["redo"])
    redo.pop("verify1RedoCount")
    assert Settings.model_validate({**snap, "redo": redo}).redo.verify1_redo_count == 1
    legacy = Settings.model_validate({"agents": {"전략": {"provider": "p", "model": "m", "temperature": 0.7}}})
    assert legacy.tasks is None and legacy.agents["전략"].model == "m"


def test_plan_tables_switch_and_provisional():
    assert settings_mod.PLAN_TABLES_REQUIRED is False
    assert "planTables.required" in settings_mod.PROVISIONAL
    assert "redo.verify1RedoCount" in settings_mod.PROVISIONAL
    assert "purposeModels" in settings_mod.PROVISIONAL["tasks"]


# ── tools: 목적별 모델 · json_mode ──────────────────────
class Recorder:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return '{"ok": true}'


def _tools(purpose_models: dict | None = None) -> tuple[Tools, Recorder, CallSink]:
    rec, sink = Recorder(), CallSink()
    cfg = ToolsConfig(agent="전략", provider="p", model="task-model", temperature=None, timeout_sec=10,
                      retry_count=0, retry_interval_sec=0, purpose_models=purpose_models or {})
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-S1", providers={"p": rec}, sink=sink, now=utc_now)
    return Tools(cfg, ctx), rec, sink


def test_purpose_model_used_and_logged():
    tools, rec, sink = _tools({"F01": "luna"})
    tools.llm([{"role": "user", "content": "x"}], purpose="F01")
    tools.llm([{"role": "user", "content": "x"}], purpose="F02")
    assert [q.model for q in rec.requests] == ["luna", "task-model"]
    assert [log.model for log in sink.drain()] == ["luna", "task-model"]


def test_json_mode_rides_on_request():
    tools, rec, _ = _tools()
    tools.llm([{"role": "user", "content": "x"}], purpose="F01", json_mode=True)
    tools.llm([{"role": "user", "content": "x"}], purpose="F01")
    assert [q.json_mode for q in rec.requests] == [True, False]
    assert ToolsConfig(agent="a", provider=None, model=None, temperature=None, timeout_sec=1, retry_count=0,
                       retry_interval_sec=0).purpose_models == {}


def test_engine_moves_purpose_models_to_tools(clock):
    s = Settings()
    s.tasks["T-S1"].purpose_models = {"요구사항 분석": "목적-모델"}
    app = make_app(clock, settings=s)
    rid = to_screen6(app)
    [q] = [q for q in app.llm.requests if q.metadata["task_id"] == "T-S1"]
    assert q.model == "목적-모델"
    [log] = [log for log in app.store.call_logs(rid) if log.task_id == "T-S1"]
    assert log.model == "목적-모델"
    other = [q for q in app.llm.requests if q.metadata["task_id"] == "T-S2"]
    assert other and all(q.model == "gpt-6.1-sol" for q in other)


# ── OpenAI 호출처: response_format · 잘린 응답 ─────────────
class FakeCompletions:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content, finish = self.outcomes.pop(0)
        usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, prompt_tokens_details=None,
                                completion_tokens_details=None)
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish)])


def _provider(outcomes: list) -> tuple[OpenAIProvider, FakeCompletions]:
    comp = FakeCompletions(outcomes)
    return OpenAIProvider(SimpleNamespace(chat=SimpleNamespace(completions=comp))), comp


def _request(**over) -> LLMRequest:
    base = dict(provider="openai", model="gpt-test", temperature=None, messages=[{"role": "user", "content": "x"}],
                timeout_sec=5.0, response_schema=None, metadata={"task_id": "T-S1"})
    return LLMRequest(**{**base, **over})


def test_response_format_three_cases():
    p, comp = _provider([('{"a": 1}', "stop")] * 4)
    p.complete(_request(json_mode=True))
    assert comp.calls[-1]["response_format"] == {"type": "json_object"}
    schema = {"title": "Ack", "type": "object"}
    p.complete(_request(json_mode=True, response_schema=schema))
    assert comp.calls[-1]["response_format"]["type"] == "json_schema"       # 스키마가 우선
    p.complete(_request(response_schema=schema))
    assert comp.calls[-1]["response_format"]["type"] == "json_schema"
    p.complete(_request())
    assert "response_format" not in comp.calls[-1]


@pytest.mark.parametrize("json_mode", [True, False])
def test_length_cut_is_format_error_with_usage(json_mode):
    p, _ = _provider([('{"a": 1', "length")])
    with pytest.raises(FormatError) as e:
        p.complete(_request(json_mode=json_mode))
    assert e.value.usage == TokenUsage(input_tokens=11, output_tokens=7)
    assert '{"a"' not in str(e.value)                                        # 응답 내용은 메시지에 없다


def test_length_cut_retried_by_tools_without_json_mode():
    p, comp = _provider([("잘린", "length"), ("답", "stop")])
    cfg = ToolsConfig(agent="조율", provider="openai", model="gpt-test", temperature=None, timeout_sec=5,
                      retry_count=2, retry_interval_sec=0)
    sink = CallSink()
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-C1", providers={"openai": p}, sink=sink,
                       now=utc_now, sleep=lambda s: None)
    assert Tools(cfg, ctx).llm([{"role": "user", "content": "x"}], purpose="시험") == "답"
    [log] = sink.drain()
    assert [t.outcome for t in log.tries] == ["형식오류", "성공"] and log.tries[0].input_tokens == 11
    assert len(comp.calls) == 2


def test_length_cut_exhausts_as_format_error():
    p, _ = _provider([("잘린", "length")] * 2)
    cfg = ToolsConfig(agent="조율", provider="openai", model="gpt-test", temperature=None, timeout_sec=5,
                      retry_count=1, retry_interval_sec=0)
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-C1", providers={"openai": p}, sink=CallSink(),
                       now=utc_now, sleep=lambda s: None)
    with pytest.raises(ToolCallExhausted) as e:
        Tools(cfg, ctx).llm([{"role": "user", "content": "x"}], purpose="시험", json_mode=True)
    assert (e.value.error, e.value.error_kind) == ("형식오류", "일시")


def test_llm_response_unchanged_without_finish_reason():
    p, comp = _provider([("답", None)])
    assert p.complete(_request()) == LLMResponse("답", TokenUsage(input_tokens=11, output_tokens=7))


# ── 스텁이 새 칸을 채운다 ──────────────────────────────
def test_stub_scenario_has_item_knobs():
    sc = StubScenario()
    assert (sc.fail_items, sc.warning_items, sc.input_missing_items) == (set(), set(), set())


def test_stubs_fill_new_outputs(clock):
    app = make_app(clock)
    rid = to_screen6(app)
    ctx = app.engine.open_context(app.store.load_run(rid))
    form = ctx.get("formSpec")
    assert isinstance(ctx.get("strategyData"), dict) and ctx.get("strategyData")
    assert isinstance(ctx.get("marketStrategyData"), dict) and ctx.get("marketStrategyData")
    # 양식 = 담당자 항목(법인 → early_startup 24개, T2): 본문 · 표 · 그림 항목별로 나뉜다
    kinds = dict(zip(form.section_codes, form.section_kinds))
    by_kind = {k: [c for c in form.section_codes if kinds[c] == k] for k in ("section", "table", "image")}
    assert by_kind["table"] and by_kind["image"]
    outs = ctx.get("sectionOutputs")
    assert list(outs) == by_kind["section"]
    assert all({"generatedText", "facts", "sourceRefs", "needsUserConfirmation", "issues"} <= set(v)
               for v in outs.values())
    assert list(ctx.get("diagramOutputs")) == by_kind["image"]
    assert [d.source_ref for d in ctx.get("diagrams")] == [c for c in by_kind["image"] for _ in range(2)]
    assert [s.section_code for s in ctx.get("tableSections")] == by_kind["table"] == list(ctx.get("tableOutputs"))
    results = ctx.get("sectionResults")
    assert [r.section_code for r in results] == form.section_codes
    assert all(isinstance(r, SectionResult) and r.status == "pass" and not r.input_missing for r in results)
    assert ctx.get("scorePolicyVersion") == ctx.get("rubric").version
    plan = ctx.get("planDoc")
    assert [s.section_code for s in plan.sections] == form.section_codes
    assert [(s.content_type, s.tag) for s in plan.sections] == list(zip(form.section_kinds, form.section_tags))
    assert plan.diagrams == ctx.get("diagrams")
    # T-W3는 LLM을 부르지 않는다 — 호출처 요청 · 호출 기록 모두 없고 실행 기록의 모델도 빈다
    assert not [q for q in app.llm.requests if q.metadata["task_id"] == "T-W3"]
    assert not [log for log in app.store.call_logs(rid) if log.task_id == "T-W3" and log.call_type == "llm"]
    [tw3] = [r for r in app.store.executions(rid) if r.task_id == "T-W3"]
    assert tw3.status == "성공" and tw3.model is None


def test_stub_m1_merges_diagrams_and_table_sections():
    from sbrain.agents.stubs import bind_stubs
    reg = build_registry()
    bind_stubs(reg, StubScenario())
    sec = lambda code, kind, text: PlanSection(section_code=code, title=code, sentences=[  # noqa: E731
        {"sentenceId": f"s-{code}-1", "text": text, "isTitle": False, "paragraphNo": 1}] if text else [],
        content_type=kind)
    plan = PlanDoc(sections=[sec("2.4.1", "section", "본문"), sec("2.5.3", "table", ""), sec("2.3.6", "image", "")],
                   feature_list=[], charts=[], tables=[], protected_tokens=[])
    diagram = DiagramSpec(diagram_id="2.3.6-USER_FLOW", flow_type="USER_FLOW", nodes=["a", "b", "c"],
                          visual_style={}, source_ref="2.3.6", image_file=_ref())
    out = reg.get("M-1").fn(c.M1In(plan_doc=plan, charts=[], tables=[], diagrams=[diagram],
                                   table_sections=[sec("2.5.3", "table", "표 서술")]))
    assert [s.section_code for s in out.plan_doc.sections] == ["2.4.1", "2.5.3", "2.3.6"]
    assert out.plan_doc.sections[1].sentences[0].text == "표 서술"
    assert out.plan_doc.diagrams == [diagram]
