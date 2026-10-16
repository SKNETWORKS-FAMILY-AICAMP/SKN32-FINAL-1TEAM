"""결과 통합 T-C4 실구현.

- 누락 검사: 계획서 · 프로토타입 · 인포그래픽 · 점수 보고서 없음(①) · 계획서 항목 0개(②) · 검증-2 점수 없음(④) → 맞는 경우를 모두
  모아 ContractError 하나(E-C4-MISSING). 흐름에서는 실행 실패 · 관리자 알림 · 실패 사유에 코드와 경우 번호. 진입 파일 없음 ·
  안내 문서 없음은 실패가 아니다.
- 결과물 묶음: 계획서 파일 칸은 늘 비움(웹이 planDoc으로 만든다), 계획서 파일을 파일 저장소에 넣지 않음, 옛 실행 건 호환.
- 미달 항목: 문서층(검증-1 fail — 총점 통과여도, 입력 오류는 따로, warning · 입력 없음 제외) · 산출물층(통과 필수 조건이면 그 줄만,
  코드 점검 — 부분 점수 포함 · 해당 없음 제외, 대조 불가면 그 줄만, 빠진 · 부분 기능) · 점수 · 이름 · 태그 · 사유 · 순서.
  환산 칸이 빈 옛 보고서도 같은 값.
- 안내 문구 두 경우, 조립(워커 · 스텁이 같은 함수), LLM 호출 없음, 기록 · 사건 · 관리자 조회에 미달 글 없음.
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

import json

import pytest
from conftest import make_app, to_screen9
from flow_helpers import ctx_of, pid, records_of_task, run_review
from worker_helpers import projects

from sbrain.agents.stubs import FakeLLM, StubScenario, bind_stubs
from sbrain.agents.supervisor import IMPLEMENTED, PLAIN_TASK_IDS, PLAIN_TASKS, RULES, judge, tc4
from sbrain.agents.supervisor.readme import PROTOTYPE_NOTICE
from sbrain.bootstrap import build_app
from sbrain.contracts import tasks as c
from sbrain.flow.catalog import SECTION_RESULTS, build_registry
from sbrain.flow.score_scale import scaled_report_fields, score_maxes
from sbrain.models import (
    ArtifactScore, CodeCheck, CodeCheckResult, Deliverable, DocScore, DocScoreItem, FeatureMatchResult, FileRef,
    Infographic, PlanDoc, PlanSection, ProofreadLog, Prototype, SectionResult, ShortfallItem, extension_fields,
)
from sbrain.orchestrator.errors import ERROR_CODES, ContractError
from sbrain.orchestrator.registry import art
from sbrain.orchestrator.settings import PROVISIONAL, ScoringSettings, Settings

HTML_WEIGHTS = [3, 2, 2, 2, 1, 2, 2, 1]
READY = "계획서 · 프로토타입 · 검증 결과를 내려받을 수 있습니다."
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
BODY = "3.4.1"   # 스텁 흐름 양식(개인사업자 early_startup)의 본문 항목


# ── 도움 ────────────────────────────────────────────────
def fref(name: str, media_type: str) -> FileRef:
    return FileRef(key=f"run-x/e/u/{name}", name=name, media_type=media_type, size=1, sha256="0" * 64)


ENTRY, README, ASSET = fref("index.html", "text/html"), fref("README.md", "text/markdown"), fref("a.png", "image/png")
IMAGE = fref("infographic.svg", "image/svg+xml")


def checks(failed: dict[int, float] | None = None, *, not_applicable: set[int] = frozenset(),
           details: dict[int, str] | None = None) -> list[CodeCheck]:
    """코드 점검 8칸 — failed: 번호 → 얻은 점수(만점 아님), not_applicable: 해당 없음 번호."""
    failed, details = failed or {}, details or {}
    rows = []
    for i, w in enumerate(HTML_WEIGHTS, start=1):
        if i in not_applicable:
            rows.append(CodeCheck(no=i, name=f"점검{i}", weight=w, passed=True, detail="해당 없음 — 대상 없음",
                                  earned=0, applicable=False))
        elif i in failed:
            earned = failed[i]
            rows.append(CodeCheck(no=i, name=f"점검{i}", weight=w, passed=False,
                                  detail=details.get(i, f"{earned:g}/{w}점 — 근거{i}"), earned=earned))
        else:
            rows.append(CodeCheck(no=i, name=f"점검{i}", weight=w, passed=True, detail=f"{w}/{w}점 — 통과", earned=w))
    return rows


def artifact(*, failed: dict[int, float] | None = None, not_applicable: set[int] = frozenset(),
             details: dict[int, str] | None = None, gate: list[str] | None = None, feature: float = 15.0,
             missing: list[str] | None = None, partial: list[str] | None = None,
             withheld: bool = False) -> ArtifactScore:
    rows = checks(failed, not_applicable=not_applicable, details=details)
    if gate:
        rows = [r.model_copy(update={"passed": False, "earned": 0}) for r in rows]
    code_total = 0.0 if gate else 15.0 - sum(r.weight - (r.earned or 0) for r in rows if r.applicable and not r.passed)
    fm = FeatureMatchResult(score=0 if gate or withheld else feature, missing_features=list(missing or []),
                            partial_features=list(partial or []), extra_features=[], findings=[],
                            judged_by="htmlParse", withheld=withheld,
                            withheld_reason="E-V2-NOFEATURE" if withheld else None)
    cc = CodeCheckResult(total=code_total, checks=rows, gate_failures=list(gate or []))
    return ArtifactScore(total=0 if gate else code_total + fm.score, code_check=cc, feature_match=fm)


SECTIONS = [("2.4.1", "문제 인식", "1-1"), ("2.5.2", "사업비 집행계획", "2-1"), ("2.6.1", "성장 전략", "3-1"),
            ("2.7.1", "팀 구성", "4-1")]


def doc_score(total: float = 60.0) -> DocScore:
    per = round(total / len(SECTIONS), 2)
    return DocScore(total=total, items=[DocScoreItem(item_code=code, score=per, max_score=17.5, comment="")
                                        for code, _, _ in SECTIONS])


def report(art: ArtifactScore | None, *, doc_total: float = 60.0, threshold: float = 70.0):
    """판정 실구현(G-02b)이 만든 점수 보고서 — 환산 칸이 채워져 있다. art가 None이면 검증-2 점수를 뺀다."""
    base = art or artifact()
    inp = c.G02bIn(doc_score=doc_score(doc_total), artifact_score=base, threshold=threshold, rework_usage=[],
                   settings_snapshot=Settings().dump(), category="웹개발")
    out = judge.run_g02b(inp).score_report
    return out if art is not None else out.model_copy(update={"artifact_score": None})


def plan_doc(sections=SECTIONS) -> PlanDoc:
    return PlanDoc(sections=[PlanSection(section_code=code, title=title, sentences=[], tag=tag)
                             for code, title, tag in sections],
                   feature_list=["기능 A", "기능 B"], charts=[], tables=[], protected_tokens=[])


def result(code: str, status: str = "pass", *, issues=(), warnings=(), input_missing=False, input_error=False,
           tag: str | None = None) -> SectionResult:
    tag = tag if tag is not None else next((t for c_, _, t in SECTIONS if c_ == code), None)
    return SectionResult(section_code=code, tag=tag, content_type="section", status=status, issues=list(issues),
                         warnings=list(warnings), input_missing=input_missing, input_error=input_error, score=50.0,
                         verified_ref="planDoc@1")


PROOFREAD = ProofreadLog(total_sentences=0, adopted_count=0, retained_by_check_ids=[], retained_by_call_failure_ids=[],
                         early_stopped_sentence_ids=[], token_preservation_rate=1.0, model_version="m")


def tc4_in(**over) -> c.TC4In:
    values = dict(plan_doc=plan_doc(), prototype=Prototype(entry_file=ENTRY, kind="html", asset_files=[ASSET],
                                                           readme_file=README, implemented_features=[]),
                  infographic=Infographic(image_file=IMAGE, format="svg", alt_text="a"),
                  score_report=report(artifact()), proofread_log=PROOFREAD, section_results=None)
    values.update(over)
    return c.TC4In(**values)


class NoTools:
    """T-C4는 tools를 받지만 부르지 않는다 — 어떤 속성을 읽어도 실패한다."""

    def __getattr__(self, name):
        raise AssertionError(f"T-C4가 tools.{name}을 불렀다")


def run(inp: c.TC4In) -> c.TC4Out:
    return tc4.run(inp, NoTools())


def kinds(items: list[ShortfallItem]) -> list[tuple[str, str, str | None]]:
    return [(i.layer, i.kind, i.code) for i in items]


# ── 누락 검사 ───────────────────────────────────────────
@pytest.mark.parametrize(("field", "key"), [("plan_doc", "planDoc"), ("prototype", "prototype"),
                                            ("infographic", "infographic"), ("score_report", "scoreReport.overall")])
def test_each_missing_artifact_is_case_1(field, key):
    with pytest.raises(ContractError) as e:
        run(tc4_in(**{field: None}))
    assert str(e.value) == f"E-C4-MISSING ①: {key}"


def test_missing_cases_are_all_collected_into_one_error():
    with pytest.raises(ContractError) as e:
        run(tc4_in(prototype=None, score_report=report(None)))
    assert str(e.value) == "E-C4-MISSING ①④: prototype, scoreReport.overall.artifactScore"
    with pytest.raises(ContractError) as e:
        run(tc4_in(plan_doc=plan_doc([]), infographic=None, score_report=report(None)))
    assert str(e.value) == "E-C4-MISSING ①②④: infographic, planDoc.sections, scoreReport.overall.artifactScore"
    with pytest.raises(ContractError) as e:
        run(tc4_in(plan_doc=plan_doc([])))
    assert str(e.value) == "E-C4-MISSING ②: planDoc.sections"


def test_missing_message_has_no_content():
    with pytest.raises(ContractError) as e:
        run(tc4_in(plan_doc=plan_doc([]), score_report=report(None), prototype=None))
    text = str(e.value)
    assert all(word not in text for word in ("index.html", "README", "사업비", "기능 A", "run-x"))


def test_no_entry_file_and_no_readme_are_not_missing():
    proto = Prototype(entry_file=None, kind="html", asset_files=[], readme_file=None, implemented_features=[])
    out = run(tc4_in(prototype=proto))
    assert out.deliverable.prototype_files == []


def test_error_code_registered_and_wording_provisional():
    # 오류 코드는 기준 문서 시트 6, 오류 글 모양 · 미달 항목 고정 문구 · 안내 문구는 잠정
    e = ERROR_CODES["E-C4-MISSING"]
    assert (e.where, e.message, e.handling) == ("T-C4", "", "실행 실패 · 관리자 알림")
    assert {"tc4.missing", "tc4.shortfall", "tc4.userMessage"} <= set(PROVISIONAL)
    assert "E-C4-MISSING" in PROVISIONAL["tc4.missing"]


# ── 결과물 묶음 ─────────────────────────────────────────
def test_deliverable_empties_plan_doc_file_and_keeps_stub_shape():
    inp = tc4_in()
    d = run(inp).deliverable
    assert d.plan_doc_file is None
    assert d.prototype_files == [ENTRY, README, ASSET] and d.infographic_file == IMAGE
    assert d.score_report == inp.score_report and d.proofread_log == PROOFREAD
    assert (d.disclaimer, d.prototype_notice, d.score_notice, d.submission_notice) == (
        tc4.DISCLAIMER, PROTOTYPE_NOTICE, tc4.SCORE_NOTICE, tc4.SUBMISSION_NOTICE)
    assert tc4.DISCLAIMER == "본 문서는 S-Brain이 생성한 초안입니다. 제출 전 작성자 본인의 확인과 수정이 필요합니다."


def test_old_deliverable_still_reads():
    d = run(tc4_in()).deliverable
    old = d.dump()
    old.pop("shortfallItems")
    old["planDocFile"] = fref("plan.docx", DOCX).dump()
    back = Deliverable.model_validate(old)
    assert back.plan_doc_file.name == "plan.docx" and back.shortfall_items == []


def test_fields_and_type_are_in_basedoc_and_optional():
    # 기능정의서 v1.11에 들어갔다 — 확장 표시 없음. 선택 선언 · 기본값은 그대로
    assert not {"planDocFile", "shortfallItems"} & set(extension_fields(Deliverable))
    assert Deliverable.model_fields["plan_doc_file"].default is None
    assert Deliverable.model_fields["shortfall_items"].default_factory is list
    assert extension_fields(ShortfallItem) == []
    assert extension_fields(c.TC4In) == []
    assert all(c.TC4In.model_fields[f].default is None
               for f in ("plan_doc", "prototype", "infographic", "score_report", "section_results"))


# ── 미달 항목 — 문서층 ──────────────────────────────────
def test_document_layer_fail_lines_even_when_total_passes():
    rep = report(artifact(), doc_total=60.0, threshold=70.0)
    assert rep.passed
    results = [result("2.4.1", "fail", issues=["근거 없음", "수치 누락"]), result("2.5.2", "fail", input_error=True,
                                                                            issues=["상한 초과"]),
               result("2.6.1", "warning", warnings=["보완"]), result("2.7.1", "warning", input_missing=True)]
    items = run(tc4_in(score_report=rep, section_results=results)).deliverable.shortfall_items
    assert kinds(items) == [("document", "verifyFail", "2.4.1"), ("document", "inputError", "2.5.2")]
    first, second = items
    assert (first.name, first.tag, first.score, first.max_score, first.reason) == (
        "문제 인식", "1-1", 15.0, 17.5, "근거 없음 · 수치 누락")
    assert (second.name, second.tag, second.reason) == ("사업비 집행계획", "2-1", "상한 초과")


def test_document_layer_fallbacks_name_score_reason():
    rep = report(artifact())
    unknown = result("9.9.9", "fail", tag=None)   # 계획서 항목 · 점수 줄에 없는 번호, issues 없음
    [item] = run(tc4_in(score_report=rep, section_results=[unknown])).deliverable.shortfall_items
    assert (item.name, item.tag, item.score, item.max_score, item.reason) == ("9.9.9", None, None, None, "fail")


def test_no_section_results_no_document_lines():
    items = run(tc4_in(section_results=None)).deliverable.shortfall_items
    assert [i for i in items if i.layer == "document"] == []


# ── 미달 항목 — 산출물층 ────────────────────────────────
def test_code_check_lines_partial_and_zero_without_not_applicable():
    art = artifact(failed={1: 1.5, 4: 0}, not_applicable={8}, details={4: ""})
    rep = report(art)
    items = run(tc4_in(score_report=rep)).deliverable.shortfall_items
    assert kinds(items) == [("artifact", "codeCheck", "1"), ("artifact", "codeCheck", "4")]
    scaled = {ch.no: ch for ch in rep.code_check_items}
    one, four = items
    assert (one.name, one.score, one.max_score, one.reason) == ("점검1", scaled[1].earned, scaled[1].weight,
                                                                 scaled[1].detail)
    assert one.reason.endswith("— 근거1")
    assert (four.score, four.max_score, four.reason) == (scaled[4].earned, scaled[4].weight, tc4.CODE_CHECK_REASON)
    assert one.tag is None and four.tag is None


def test_old_report_without_scaled_fields_gives_same_values():
    art = artifact(failed={1: 1.5, 4: 0}, withheld=True)
    rep = report(art)
    new = run(tc4_in(score_report=rep)).deliverable.shortfall_items
    old_rep = rep.model_copy(update={"code_check_items": [], "feature_match_score": None, "feature_match_max": None,
                                     "code_check_score": None, "code_check_max": None})
    old = run(tc4_in(score_report=old_rep)).deliverable.shortfall_items
    assert old == new
    fields = scaled_report_fields(score_maxes(rep.settings_snapshot), art)
    assert new[-1].kind == "featureMatchWithheld"
    assert (new[-1].score, new[-1].max_score) == (fields["feature_match_score"], fields["feature_match_max"])


def test_gate_failure_lines_only():
    art = artifact(gate=["entry", "sandbox"], missing=["기능 A", "기능 B"])
    items = run(tc4_in(score_report=report(art))).deliverable.shortfall_items
    assert kinds(items) == [("artifact", "gateFailure", "entry"), ("artifact", "gateFailure", "sandbox")]
    assert [(i.name, i.reason, i.score, i.max_score) for i in items] == [
        (tc4.GATE_NAMES["entry"], tc4.GATE_REASONS["entry"], None, None),
        (tc4.GATE_NAMES["sandbox"], tc4.GATE_REASONS["sandbox"], None, None)]


def test_withheld_feature_match_only_that_line():
    art = artifact(failed={2: 0}, withheld=True, missing=["기능 A"], partial=["기능 B"])
    rep = report(art)
    items = run(tc4_in(score_report=rep)).deliverable.shortfall_items
    assert kinds(items) == [("artifact", "codeCheck", "2"), ("artifact", "featureMatchWithheld", None)]
    w = items[-1]
    assert (w.name, w.reason, w.score, w.max_score) == (tc4.WITHHELD_NAME, tc4.WITHHELD_REASON,
                                                        rep.feature_match_score, rep.feature_match_max)


def test_missing_and_partial_feature_lines_in_received_order():
    art = artifact(feature=7.5, missing=["기능 B", "기능 A"], partial=["기능 C"])
    items = run(tc4_in(score_report=report(art))).deliverable.shortfall_items
    assert [(i.kind, i.name, i.code, i.score, i.reason) for i in items] == [
        ("missingFeature", "기능 B", None, None, tc4.MISSING_FEATURE_REASON),
        ("missingFeature", "기능 A", None, None, tc4.MISSING_FEATURE_REASON),
        ("partialFeature", "기능 C", None, None, tc4.PARTIAL_FEATURE_REASON)]


def test_full_order_document_then_artifact():
    art = artifact(failed={5: 0, 3: 1}, feature=7.5, missing=["기능 A"], partial=["기능 B"])
    results = [result("2.6.1", "fail", issues=["x"]), result("2.4.1", "fail", input_error=True, issues=["y"])]
    items = run(tc4_in(score_report=report(art), section_results=results)).deliverable.shortfall_items
    assert [(i.kind, i.code or i.name) for i in items] == [
        ("verifyFail", "2.6.1"), ("inputError", "2.4.1"), ("codeCheck", "3"), ("codeCheck", "5"),
        ("missingFeature", "기능 A"), ("partialFeature", "기능 B")]


# ── 안내 문구 ───────────────────────────────────────────
def test_user_message_ready_when_nothing_short():
    out = run(tc4_in())
    assert out.deliverable.shortfall_items == [] and out.deliverable.score_report.passed
    assert out.user_message == READY


def test_user_message_lists_total_shortfall_and_items():
    art = artifact(failed={1: 1.5}, feature=7.5, partial=["기능 B"])
    rep = report(art, doc_total=30.0, threshold=70.0)
    assert not rep.passed
    results = [result("2.4.1", "fail", issues=["근거 없음"])]
    out = run(tc4_in(score_report=rep, section_results=results))
    lines = out.user_message.split("\n")
    assert lines[0] == READY
    assert lines[1] == tc4.TOTAL_SHORT_LINE.format(score=f"{rep.display_score:g}", threshold=f"{rep.threshold:g}")
    assert lines[2] == tc4.LAYER_HEADINGS["document"]
    assert lines[3] == "- 문제 인식 (7.5/17.5점): 근거 없음"          # 문서층 30점을 네 항목에 나눈 점수
    assert lines[4] == tc4.LAYER_HEADINGS["artifact"]
    scaled = {ch.no: ch for ch in rep.code_check_items}[1]
    assert lines[5] == f"- 점검1 ({scaled.earned:g}/{scaled.weight:g}점): {scaled.detail}"
    assert lines[6] == f"- 기능 B: {tc4.PARTIAL_FEATURE_REASON}"
    assert lines[-1] == tc4.REVIEW_LINE and len(lines) == 8


def test_user_message_items_only_without_total_line():
    results = [result("2.4.1", "fail", issues=["근거 없음"])]
    out = run(tc4_in(section_results=results))
    lines = out.user_message.split("\n")
    assert lines[0] == READY and lines[1] == tc4.LAYER_HEADINGS["document"] and lines[-1] == tc4.REVIEW_LINE


def test_user_message_total_short_without_items():
    rep = report(artifact(), doc_total=10.0, threshold=70.0)
    lines = run(tc4_in(score_report=rep)).user_message.split("\n")
    assert lines == [READY, tc4.TOTAL_SHORT_LINE.format(score=f"{rep.display_score:g}",
                                                        threshold=f"{rep.threshold:g}"), tc4.REVIEW_LINE]


# ── 조립 ────────────────────────────────────────────────
def test_plain_task_table_is_separate_from_rules_and_llm_tasks():
    assert PLAIN_TASKS == {"T-C4": tc4.run} and PLAIN_TASK_IDS == {"T-C4"}
    assert "T-C4" not in RULES and "T-C4" not in IMPLEMENTED
    spec = build_registry().get("T-C4")
    assert spec.kind == "task" and not spec.uses_llm
    assert all(spec.inputs[f].optional for f in ("plan_doc", "prototype", "infographic", "score_report"))
    assert spec.inputs["proofread_log"].optional                 # 검수가 흐름에서 빠져 선택 입력 · 늘 None
    assert (spec.inputs["section_results"].key, spec.inputs["section_results"].optional) == (SECTION_RESULTS, True)


def test_stub_assembly_wraps_the_real_tc4():
    r = build_registry()
    bind_stubs(r, StubScenario())
    fn = r.get("T-C4").fn
    assert fn.__wrapped__ is tc4.run
    inp = tc4_in()
    assert fn(inp, NoTools()) == tc4.run(inp, NoTools())
    r2 = build_registry()
    bind_stubs(r2, StubScenario(raise_in={"T-C4"}))
    with pytest.raises(RuntimeError):
        r2.get("T-C4").fn(inp, NoTools())


def test_worker_assembly_binds_real_tc4(tmp_path, db):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    app = build_app(url, project_inputs=projects(1), llm=FakeLLM())
    assert app.registry.get("T-C4").fn is tc4.run


# ── 흐름 ────────────────────────────────────────────────
def finished(app):
    rid = to_screen9(app)
    run_review(app, rid)
    return rid


def test_flow_completes_without_plan_file_and_without_llm(clock):
    app = make_app(clock)
    rid = finished(app)
    assert app.store.load_run(rid).state.progress == "완료"
    d = ctx_of(app, rid).get("deliverable")
    assert d.plan_doc_file is None
    assert not any(k.endswith("/plan.docx") or k.endswith(".docx") for k in app.engine.files.keys())
    [rec] = records_of_task(app, rid, "T-C4")
    assert [x for x in app.store.call_logs(rid) if x.execution_id == rec.execution_id] == []   # LLM · 파일 호출 없음
    assert not rec.model


def test_flow_outputs_and_screen_11_carry_shortfall_items(clock):
    # 스텁 T-V2 기본값: 기능 2개 중 '수업 예약'이 부분 인정
    app = make_app(clock, StubScenario(fail_items={BODY}))
    rid = finished(app)
    p = pid(app, rid)
    out = app.orchestrator.outputs(p).dump()
    d = out["deliverable"]
    assert d["planDocFile"] is None
    kinds_ = [(i["layer"], i["kind"]) for i in d["shortfallItems"]]
    assert ("document", "verifyFail") in kinds_ and ("artifact", "partialFeature") in kinds_
    assert set(d["shortfallItems"][0]) == {"layer", "kind", "code", "tag", "name", "score", "maxScore", "reason"}
    s11 = app.orchestrator.screen(p, 11)
    assert s11.deliverable.shortfall_items and s11.user_message.startswith(READY)


def test_shortfall_text_not_in_records_events_admin(clock):
    app = make_app(clock, StubScenario(fail_items={BODY}, fail_item_issues={BODY: ["비밀스러운 판정 글"]}))
    rid = finished(app)
    assert any(i.reason == "비밀스러운 판정 글" for i in ctx_of(app, rid).get("deliverable").shortfall_items)
    dumped = json.dumps([
        [x.dump() for x in app.store.executions(rid)], [x.dump() for x in app.store.events(rid)],
        [x.dump() for x in app.store.call_logs(rid)], [x.dump() for x in app.orchestrator.admin_runs()],
        [x.dump() for x in app.orchestrator.admin_executions(limit=None)],
    ], ensure_ascii=False, default=str)
    assert tc4.PARTIAL_FEATURE_REASON not in dumped and tc4.LAYER_HEADINGS["document"] not in dumped
    assert "비밀스러운 판정 글" not in dumped and tc4.REVIEW_LINE not in dumped


def wrap_tc4_input(app, **update):
    base = app.registry.get("T-C4").fn

    def fn(inp, tools):
        return base(inp.model_copy(update={k: v(inp) for k, v in update.items()}), tools)
    app.registry.bind("T-C4", fn)


def assert_failed_with(app, rid, cases: str):
    run = app.store.load_run(rid)
    assert run.state.progress == "실패" and run.admin_alert
    assert f"E-C4-MISSING {cases}" in run.failure_reason and run.failure_reason.startswith("T-C4: 운영오류")
    assert run.notices[-1].code == "E-RUN-FAIL"
    assert not ctx_of(app, rid).has("deliverable")
    assert any(e.kind == "단계오류" and "E-C4-MISSING" in e.detail for e in app.store.events(rid))


def test_flow_missing_artifact_score_fails_run(clock):
    app = make_app(clock)
    wrap_tc4_input(app, score_report=lambda inp: inp.score_report.model_copy(update={"artifact_score": None}))
    rid = finished(app)
    assert_failed_with(app, rid, "④")


def test_flow_no_plan_sections_fails_run(clock):
    app = make_app(clock)
    wrap_tc4_input(app, plan_doc=lambda inp: inp.plan_doc.model_copy(update={"sections": []}))
    rid = finished(app)
    assert_failed_with(app, rid, "②")


def test_flow_absent_artifact_reaches_tc4_and_fails_with_code(clock):
    app = make_app(clock)
    app.registry.get("T-C4").inputs["infographic"] = art("infographic.absent", optional=True)   # 산출물이 없는 경우
    rid = finished(app)
    assert_failed_with(app, rid, "①")
    assert "infographic" in app.store.load_run(rid).failure_reason


def test_flow_gate_failure_without_entry_file_completes(clock):
    app = make_app(clock, StubScenario(gate_failures=["entry"]))
    base = app.registry.get("T-B1").fn

    def tb1(inp, tools):
        out = base(inp, tools)
        return out.model_copy(update={"entry_file": None,
                                      "prototype": out.prototype.model_copy(update={"entry_file": None})})
    app.registry.bind("T-B1", tb1)
    rid = finished(app)
    assert app.store.load_run(rid).state.progress == "완료"
    items = ctx_of(app, rid).get("deliverable").shortfall_items
    assert [(i.kind, i.code) for i in items if i.layer == "artifact"] == [("gateFailure", "entry")]


def test_flow_without_readme_completes(clock):
    app = make_app(clock, StubScenario(raise_in={"G-04"}))
    rid = finished(app)
    assert app.store.load_run(rid).state.progress == "완료"
    assert ctx_of(app, rid).get("prototype").readme_file is None


def test_custom_scoring_max_flows_through(clock):
    # 산출물 배점이 다른 설정 사본 — 코드 점검 줄 배점이 환산 칸(C 기준)이다
    snap = Settings(scoring=ScoringSettings(code_check_max=25, feature_match_max=5)).dump()
    art = artifact(failed={1: 0})
    inp = c.G02bIn(doc_score=doc_score(), artifact_score=art, threshold=70, rework_usage=[], settings_snapshot=snap,
                   category="웹개발")
    rep = judge.run_g02b(inp).score_report
    [item] = run(tc4_in(score_report=rep)).deliverable.shortfall_items
    row = {ch.no: ch for ch in rep.code_check_items}[1]
    assert (item.score, item.max_score) == (row.earned, row.weight) and round(item.max_score) == 5   # 25 × 3 ÷ 15
