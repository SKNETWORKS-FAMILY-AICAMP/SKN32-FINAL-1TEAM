"""구현 · 검증-2 끼우기 + 산출물층 환산 — 계약 확장 칸 · 설정 · 흐름 연결 · 호출 기록 칸 자르기 · 스텁 채우기.

- 새 칸 기본값과 옛 JSON(새 칸 없는 산출물 · 설정 사본) 읽기, JSON 별칭
- 흐름 연결: T-V2 출력 featureElements → 다음 T-V2 입력, G-02b 입력 category
- ScoreView가 점수 보고서의 환산 칸 여덟을 그대로 옮김, 관리자 만점 칸(값은 뒤 작업)
- 호출 기록 목적 · 항목 칸 200자 자르기(목적별 모델은 원래 목적), SQL 저장소 저장
- 스텁 T-V2 earned · applicable · featureElements · 통과 필수 조건 실패 → 대조 0, 스텁 T-B2 SVG, 스텁 G-02b 종류
- 잠정 목록(PROVISIONAL)
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import make_app, to_screen8, to_screen9
from flow_helpers import ctx_of, records_of_task, rework

from sbrain.agents.stubs import StubScenario, bind_stubs
from sbrain.contracts import tasks as c
from sbrain.flow import reads
from sbrain.flow.catalog import artifact_types, build_registry
from sbrain.models import (
    ArtifactScore, CodeCheck, CodeCheckResult, DocScore, FeatureMatchResult, FileRef, Infographic, ItemSpec, PlanDoc,
    Prototype, ScoreReport,
)
from sbrain.models.clock import utc_now
from sbrain.orchestrator.settings import PROVISIONAL, ScoringSettings, Settings
from sbrain.orchestrator.tools import CallSink, LLMRequest, Tools, ToolsConfig, ToolsContext
from sbrain.orchestrator.trace import CALL_LOG_TEXT_MAX
from sbrain.store_sql.schema import CALL_LOGS

FEATURES = ["회원 등록·조회", "수업 예약"]
SCALED = ("doc_layer_max", "code_check_score", "code_check_max", "feature_match_score", "feature_match_max",
          "artifact_layer_score", "artifact_layer_max")
SCALED_JSON = ("docLayerMax", "codeCheckScore", "codeCheckMax", "featureMatchScore", "featureMatchMax",
               "artifactLayerScore", "artifactLayerMax", "codeCheckItems")


def fref(name: str, media_type: str) -> FileRef:
    return FileRef(key=f"run-x/e/u/{name}", name=name, media_type=media_type, size=1, sha256="0" * 64)


def code_check_result() -> CodeCheckResult:
    return CodeCheckResult(total=15, checks=[CodeCheck(no=i, name=f"c{i}", weight=2, passed=True, detail="")
                                             for i in range(1, 9)])


def feature_match() -> FeatureMatchResult:
    return FeatureMatchResult(score=15, missing_features=[], extra_features=[], findings=[], judged_by="htmlParse")


def score_report(**over) -> ScoreReport:
    base = dict(doc_score=DocScore(total=50, items=[]), total=70, threshold=80, passed=False, failed_task_ids=[],
                rework_orders=[], rework_usage=[], phase="overall", display_score=70, rework_diff=[],
                comparisons=[], notices=[], settings_snapshot={}, rubric_version="r1")
    base.update(over)
    return ScoreReport(**base)


# ── 새 칸 기본값 · 옛 JSON · 별칭 ─────────────────────────
def test_code_check_new_fields_default_and_old_json():
    old = {"no": 1, "name": "동작 연결", "weight": 3, "passed": True, "detail": "3/3점 — 근거"}
    ch = CodeCheck.model_validate(old)
    assert (ch.earned, ch.applicable) == (None, True)
    ch = CodeCheck(no=2, name="n", weight=2, passed=True, detail="해당 없음 — 이유", earned=0, applicable=False)
    assert {"earned": 0, "applicable": False}.items() <= ch.dump().items()


def test_infographic_icon_fallback_default_and_old_json():
    old = Infographic(image_file=fref("infographic.svg", "image/svg+xml"), format="svg", alt_text="a").dump()
    old.pop("iconFallback")
    assert Infographic.model_validate(old).icon_fallback is False
    assert Infographic.model_validate({**old, "iconFallback": True}).dump()["iconFallback"] is True


def test_tv2_feature_elements_defaults():
    proto = Prototype(entry_file=fref("index.html", "text/html"), kind="html", asset_files=[],
                      implemented_features=FEATURES)
    info = Infographic(image_file=fref("infographic.svg", "image/svg+xml"), format="svg", alt_text="a")
    inp = c.TV2In(prototype=proto, infographic=info, feature_list=FEATURES)
    assert inp.feature_elements is None
    elems = {"k1": ["요소 1", "요소 2"]}
    assert c.TV2In(prototype=proto, infographic=info, feature_list=FEATURES,
                   feature_elements=elems).dump()["featureElements"] == elems
    art = ArtifactScore(total=30, code_check=code_check_result(), feature_match=feature_match())
    out = c.TV2Out(artifact_score=art, code_check=art.code_check, feature_match=art.feature_match)
    assert out.feature_elements == {} and out.dump()["featureElements"] == {}


def test_g02b_category_default():
    art = ArtifactScore(total=30, code_check=code_check_result(), feature_match=feature_match())
    inp = c.G02bIn(doc_score=DocScore(total=50, items=[]), artifact_score=art, threshold=80, rework_usage=[])
    assert inp.category is None
    assert c.G02bIn.model_validate({**inp.dump(), "category": "원페이지"}).category == "원페이지"


def test_score_report_scaled_fields_default_and_old_json():
    report = score_report()
    assert all(getattr(report, name) is None for name in SCALED) and report.code_check_items == []
    old = report.dump()
    for key in SCALED_JSON:
        old.pop(key)
    again = ScoreReport.model_validate(old)
    assert all(getattr(again, name) is None for name in SCALED) and again.code_check_items == []
    full = score_report(doc_layer_max=70, code_check_score=10, code_check_max=20, feature_match_score=5,
                        feature_match_max=10, artifact_layer_score=15, artifact_layer_max=30,
                        code_check_items=[CodeCheck(no=1, name="n", weight=2.5, passed=True, detail="", earned=2.5)])
    dumped = full.dump()
    assert set(SCALED_JSON) <= dumped.keys()
    assert dumped["codeCheckItems"][0]["earned"] == 2.5


def test_scoring_settings_new_maxes_default_and_old_snapshot():
    s = ScoringSettings()
    assert (s.code_check_max, s.feature_match_max, s.artifact_layer_max) == (15, 15, 30)
    old = Settings().dump()
    old["scoring"].pop("codeCheckMax")
    old["scoring"].pop("featureMatchMax")
    again = Settings.model_validate(old)
    assert (again.scoring.code_check_max, again.scoring.feature_match_max) == (15, 15)
    assert {"codeCheckMax": 15, "featureMatchMax": 15}.items() <= Settings().dump()["scoring"].items()


# ── 흐름 연결 (catalog) ─────────────────────────────────
def test_catalog_wires_feature_elements_and_category():
    r = build_registry()
    tv2, g02b = r.get("T-V2"), r.get("G-02b")
    assert tv2.outputs["feature_elements"] == "featureElements"
    bind = tv2.inputs["feature_elements"]
    assert (bind.kind, bind.key, bind.optional) == ("art", "featureElements", True)
    bind = g02b.inputs["category"]
    assert (bind.kind, bind.key, bind.optional) == ("art", "category", False)
    exact, _ = artifact_types(r)
    assert exact["featureElements"] == dict[str, list[str]]


def test_flow_passes_feature_elements_to_next_tv2_and_category_to_g02b(clock):
    seen: list = []
    app = make_app(clock)
    stub_tv2 = app.registry.get("T-V2").fn

    def tv2(inp: c.TV2In, tools) -> c.TV2Out:
        seen.append(inp.feature_elements)
        out = stub_tv2(inp, tools)
        return out.model_copy(update={"feature_elements": {**out.feature_elements, f"k{len(seen)}": ["요소"]}})

    app.registry.bind("T-V2", tv2)
    rid = to_screen8(app)
    assert seen == [None]                                                   # 첫 T-V2는 직전 목록 없음
    ctx = ctx_of(app, rid)
    assert ctx.get("featureElements") == {"k1": ["요소"]}
    [g02b] = records_of_task(app, rid, "G-02b")
    assert ctx.ref("category") in g02b.inputs                               # G-02b가 실행 건 카테고리를 받는다
    # 산출물층 재작성 → 다음 T-V2가 직전 목록을 받는다
    rework(app, clock, rid, "실행 파일")
    assert seen[:2] == [None, {"k1": ["요소"]}]
    assert ctx_of(app, rid).get("featureElements") == {"k1": ["요소"], "k2": ["요소"]}


# ── ScoreView · 관리자 만점 칸 ──────────────────────────
def test_score_view_copies_scaled_fields():
    items = [CodeCheck(no=i, name=f"c{i}", weight=1.88, passed=True, detail="1.88/1.88점 — 근거", earned=1.88)
             for i in range(1, 9)]
    report = score_report(doc_layer_max=70, code_check_score=12.5, code_check_max=15, feature_match_score=7.5,
                          feature_match_max=15, artifact_layer_score=20, artifact_layer_max=30,
                          code_check_items=items)
    view = reads._score(report)
    for name in SCALED:
        assert getattr(view, name) == getattr(report, name)
    assert view.code_check_items == items
    assert set(SCALED_JSON) <= view.dump().keys()
    empty = reads._score(score_report())
    assert all(getattr(empty, name) is None for name in SCALED) and empty.code_check_items == []


def test_outputs_score_view_has_scaled_keys(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    out = app.orchestrator.outputs(app.store.load_run(rid).project_id).dump()
    for key in ("documentScoreReport", "overallScoreReport"):
        assert set(SCALED_JSON) <= out[key].keys()


def test_admin_models_have_max_fields_defaulting_none():
    for model, names in ((reads.AdminRun, {"docMax", "artifactMax"}),
                         (reads.AdminScoreHistory, {"docMax", "codeCheckMax", "featureMatchMax"})):
        props = model.model_json_schema(by_alias=True)["properties"]
        assert names <= props.keys()
        assert all(model.model_fields[n].default is None
                   for n, info in model.model_fields.items() if info.alias in names)


# ── 호출 기록 목적 · 항목 칸 자르기 ─────────────────────
class Recorder:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return '{"ok": true}'


def test_call_log_text_max_matches_schema():
    assert CALL_LOG_TEXT_MAX == 200
    assert CALL_LOGS.c.purpose.type.length == CALL_LOG_TEXT_MAX
    assert CALL_LOGS.c.item_key.type.length == CALL_LOG_TEXT_MAX


def test_long_purpose_and_item_key_are_clipped_in_log_only():
    feature = "기능" * 150                                   # 300자 기능 이름
    purpose = f"계획서 대조: {feature}"
    rec, sink = Recorder(), CallSink()
    cfg = ToolsConfig(agent="검증-2", provider="p", model="task-model", temperature=None, timeout_sec=10,
                      retry_count=0, retry_interval_sec=0, purpose_models={purpose: "purpose-model"})
    tools = Tools(cfg, ToolsContext(run_id="r", execution_id="e", task_id="T-V2", providers={"p": rec}, sink=sink,
                                    now=utc_now))
    tools.for_item(feature).llm([{"role": "user", "content": "x"}], purpose=purpose)
    tools.search("짧은 목적", lambda timeout: None)
    [log, short] = sink.drain()
    assert log.purpose == purpose[:CALL_LOG_TEXT_MAX] and len(log.purpose) == CALL_LOG_TEXT_MAX
    assert log.item_key == feature[:CALL_LOG_TEXT_MAX]
    assert log.model == "purpose-model"                      # 목적별 모델은 자르기 전 목적으로 찾는다
    [req] = rec.requests
    assert (req.model, req.metadata["purpose"], req.metadata["item_key"]) == ("purpose-model", purpose, feature)
    assert (short.purpose, short.item_key) == ("짧은 목적", None)


def test_long_purpose_call_log_is_saved(clock):
    feature = "긴기능이름" * 60                              # 300자
    purpose = f"계획서 대조: {feature}"
    s = Settings()
    s.tasks["T-V2"].purpose_models = {purpose: "purpose-model"}
    app = make_app(clock, settings=s)
    stub_tv2 = app.registry.get("T-V2").fn

    def tv2(inp: c.TV2In, tools) -> c.TV2Out:
        tools.for_item(feature).llm([{"role": "user", "content": "x"}], purpose=purpose)
        return stub_tv2(inp, tools)

    app.registry.bind("T-V2", tv2)
    rid = to_screen8(app)
    [log] = [x for x in app.store.call_logs(rid) if x.task_id == "T-V2" and x.item_key]
    assert len(log.purpose) == len(log.item_key) == CALL_LOG_TEXT_MAX
    assert log.purpose == purpose[:CALL_LOG_TEXT_MAX] and log.model == "purpose-model"
    [q] = [q for q in app.llm.requests if q.metadata.get("item_key") == feature]
    assert q.metadata["purpose"] == purpose


# ── 스텁 ────────────────────────────────────────────────
def stub_fn(task_id: str, sc: StubScenario):
    r = build_registry()
    bind_stubs(r, sc)
    return r.get(task_id).fn


def tv2_in(features: list[str], elements: dict | None = None) -> c.TV2In:
    proto = Prototype(entry_file=fref("index.html", "text/html"), kind="html", asset_files=[],
                      implemented_features=features)
    info = Infographic(image_file=fref("infographic.svg", "image/svg+xml"), format="svg", alt_text="i")
    return c.TV2In(prototype=proto, infographic=info, feature_list=features, feature_elements=elements,
                   plan_doc=PlanDoc(sections=[], feature_list=features, charts=[], tables=[], protected_tokens=[]))


TOOLS = SimpleNamespace(llm=lambda *a, **k: None)
F4 = ["f1", "f2", "f3", "f4"]


def test_stub_tv2_fills_earned_applicable_and_feature_elements():
    out = stub_fn("T-V2", StubScenario(art_scores=[(10.0, 15.0)]))(tv2_in(F4), TOOLS)
    checks = out.code_check.checks
    assert all(ch.applicable for ch in checks)
    assert all(ch.earned == (ch.weight if ch.passed else 0) for ch in checks)
    assert sum(ch.earned for ch in checks) == out.code_check.total == 10.0
    assert out.feature_elements == {}
    elems = {"k": ["a", "b"]}
    assert stub_fn("T-V2", StubScenario())(tv2_in(F4, elems), TOOLS).feature_elements == elems


def test_stub_tv2_gate_failure_zeroes_feature_match():
    out = stub_fn("T-V2", StubScenario(gate_failures=["secret"], art_scores=[(15.0, 15.0)]))(tv2_in(F4), TOOLS)
    fm = out.feature_match
    assert out.code_check.gate_failures == ["secret"] and out.code_check.total == 0
    assert fm.score == 0 and fm.missing_features == F4 and fm.partial_features == [] and not fm.withheld
    assert out.artifact_score.total == 0 and out.artifact_score.feature_match.score == 0
    assert all(ch.earned == 0 and ch.applicable for ch in out.code_check.checks)


class PutOnly:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, bytes, str]] = []

    def put(self, name: str, data: bytes, media_type: str) -> FileRef:
        self.put_calls.append((name, data, media_type))
        return fref(name, media_type)


@pytest.mark.parametrize("category,name", [("웹개발", "infographic.svg"), ("AI_API", "infographic.svg"),
                                           ("원페이지", "onepage.svg")])
def test_stub_tb2_puts_svg_in_every_category(category, name):
    files = PutOnly()
    tools = SimpleNamespace(llm=lambda *a, **k: None, files=files)
    item = ItemSpec(item_name="i", one_line_summary="s", target_customer="t", core_features=FEATURES,
                    category=category, keywords=[])
    inp = c.TB2In(plan_doc=PlanDoc(sections=[], feature_list=FEATURES, charts=[], tables=[], protected_tokens=[]),
                  item_spec=item, category=category, instruction="지시")
    out = stub_fn("T-B2", StubScenario(category=category))(inp, tools)
    [(put_name, data, media_type)] = files.put_calls
    assert (put_name, media_type) == (name, "image/svg+xml") and data.startswith(b"<svg")
    info = out.infographic
    assert (info.image_file.name, info.format, info.icon_fallback) == (name, "svg", False)


@pytest.mark.parametrize("category,task_id", [("원페이지", "T-B2"), ("웹개발", "T-B1")])
def test_stub_g02b_kind_from_input_category(category, task_id):
    cc = code_check_result().model_copy(update={"total": 0, "gate_failures": ["entry"]})
    art = ArtifactScore(total=0, code_check=cc, feature_match=feature_match())
    inp = c.G02bIn(doc_score=DocScore(total=60, items=[]), artifact_score=art, threshold=80, rework_usage=[],
                   category=category)
    other = "웹개발" if category == "원페이지" else "원페이지"         # 상황 조절 값은 일부러 다르게
    out = stub_fn("G-02b", StubScenario(category=other))(inp)
    assert [o.task_id for o in out.rework_orders if o.layer == "artifact"] == [task_id]


# ── 잠정 목록 ───────────────────────────────────────────
def test_provisional_entries_for_scaling_work():
    assert "T-B2 맞춤 아이콘 사용 불가 — 기본 아이콘으로 계속" in PROVISIONAL["event.이미지대체"]
    assert "T-B2 이미지 호출 실패 — 기본 아이콘으로 계속" in PROVISIONAL["event.이미지대체"]
    for key, word in (("g04.templateText", "기본 문구"), ("scoring.scaledRounding", "소수 둘째 자리"),
                      ("tv2.fileDecode", "대체 문자")):
        assert word in PROVISIONAL[key]
