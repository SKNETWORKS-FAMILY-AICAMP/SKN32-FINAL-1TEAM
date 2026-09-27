"""스텁 Agent — 뼈대 검증용. 7개 Agent(조율 포함)의 Task와 합치기를 타입에 맞는 더미 결과로 구현한다.

- LLM Task 스텁은 tools.llm을 한 번 이상 불러 tools 경로를 거치게 한다.
- StubScenario로 점수 · 검사 결과 · 오류를 조절해 흐름 테스트를 만든다.
- 실제 구현이 나오면 registry.bind(task_id, fn)로 바꿔 끼운다.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from pydantic import BaseModel

from ..contracts import tasks as c
from ..models import (
    Announcement, AnnouncementCard, ArtifactScore, ChartSpec, CheckResult, CodeCheck,
    CodeCheckResult, CompanyInfo, Deliverable, DocScore, DocScoreItem, EligibilityRule,
    EvalItem, FeatureMatchResult, FormatFinding, FormatSpec, FormSpec, GateResult,
    Infographic, ItemSpec, MarketAnalysis, MarketSizeItem, PlanDoc, PlanSection,
    ProofreadLog, Prototype, ReferenceDoc, RequirementAnalysis, ReworkDiff, ReworkOrder,
    Rubric, RubricItem, ScoreReport, Sentence, TableSpec, TaskInstruction, TaskPlan,
    Token, TokenCheckResult,
)
from ..orchestrator.errors import ProviderError, ToolCallExhausted
from ..orchestrator.registry import TaskRegistry
from ..orchestrator.tools import LLMRequest, Tools
from ..flow.rework_map import (
    CODE_CHECK_TARGET, FEATURE_MISSING_TARGET, LIST_README_BUNDLE, TASK_BUNDLE,
)

DOC_LAYER_MAX = 70.0
HTML_WEIGHTS = [3, 2, 2, 1, 2, 2, 1, 2]
SVG_WEIGHTS = [3, 2, 2, 2, 2, 2, 1, 1]
HTML_NAMES = ["진입 파일", "대체 텍스트", "label 연결", "html lang", "명도 대비", "제목 계층", "실행 안내", "비밀값"]
SVG_NAMES = ["진입 파일", "대체 텍스트", "핵심 정보 항목", "명도 대비", "정보 계층", "텍스트 실재성", "최소 글자 크기", "열람 안내"]
EVAL = [("문제인식", 20.0), ("실현가능성", 20.0), ("성장전략", 15.0), ("팀구성", 15.0)]

# 기획서 6-8 고정 문구
DISCLAIMER = "본 문서는 S-Brain이 생성한 초안입니다. 제출 전 작성자 본인의 확인과 수정이 필요합니다."
SCORE_NOTICE = "검증 점수는 서비스 내부 기준(rubric 상수)에 따른 값이며 실제 심사 점수가 아닙니다."
PROTOTYPE_NOTICE = "이 프로토타입은 AI가 생성했습니다."
SUBMISSION_NOTICE = "공고에 따라 AI 작성 문서의 제출을 제한하거나 명시를 요구할 수 있습니다. 제출 요건을 확인해주세요."


class Ack(BaseModel):
    ok: bool


# ── 가짜 LLM 호출처 ───────────────────────────────────
class FakeLLM:
    """스크립트대로 응답하는 가짜 호출처. script[(task_id, item_key)] = ['timeout', 'ok', ...]."""

    def __init__(self) -> None:
        self.script: dict[tuple[str, str | None], list[str]] = {}
        self.requests: list[LLMRequest] = []
        self._lock = threading.Lock()

    def plan(self, task_id: str, outcomes: list[str], item_key: str | None = None) -> None:
        self.script[(task_id, item_key)] = list(outcomes)

    def complete(self, request: LLMRequest) -> str:
        with self._lock:
            self.requests.append(request)
            key = (request.metadata["task_id"], request.metadata.get("item_key"))
            queue = self.script.get(key) or self.script.get((key[0], None)) or []
            outcome = queue.pop(0) if queue else "ok"
        if outcome == "timeout":
            raise TimeoutError()
        if outcome == "rate_limit":
            raise ProviderError("429", status=429)
        if outcome == "bad_request":
            raise ProviderError("400", status=400)
        if outcome == "auth":
            raise ProviderError("401", status=401)
        if outcome == "bad_json":
            return "not json"
        return '{"ok": true}'


# ── 시나리오 ──────────────────────────────────────────
@dataclass
class StubScenario:
    category: str = "웹개발"
    candidate_count: int = 10
    collection_status: str = "정상"
    gate_fail_ids: set[str] = field(default_factory=set)
    doc_scores: list[float] = field(default_factory=lambda: [60.0])         # T-V1 차례대로 (마지막 반복)
    art_scores: list[tuple[float, float]] = field(default_factory=lambda: [(15.0, 11.0)])  # T-V2 (코드, 대조)
    check_fail_times: dict[str, int] = field(default_factory=dict)          # Task별 검사 불통과 횟수
    omit_final_action: set[str] = field(default_factory=set)                # 확정 동작을 빠뜨릴 Task
    tw1_change_features: bool = False
    tp1_targets: int = 3
    no_tokens: bool = False
    tp2_behavior: dict[str, list[str]] = field(default_factory=dict)       # 문장별 'ok' · 'violate' · 'same'
    raise_in: set[str] = field(default_factory=set)                         # 코드 오류를 낼 단계
    embed_fail: bool = False                                                # T-C2 임베딩 검색 오류
    _counters: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def tick(self, name: str) -> int:
        with self._lock:
            n = self._counters.get(name, 0)
            self._counters[name] = n + 1
            return n

    def pick(self, name: str, seq: list) -> Any:
        i = self.tick(name)
        return seq[min(i, len(seq) - 1)]


# ── 데이터 공급 (공고 DB · 상수) ──────────────────────────
def make_announcement(announcement_id: str, today: date, *, eligible: bool = True) -> Announcement:
    codes = ["1-1", "2-1", "3-3"]
    return Announcement(
        announcement_id=announcement_id, title=f"창업지원사업 {announcement_id}", agency="중소벤처기업부",
        support_field="창업(06)", apply_start=today - timedelta(days=10), apply_end=today + timedelta(days=30),
        status="모집중",
        eligibility=EligibilityRule(applicant_types=["예비창업자", "개인사업자", "법인"] if eligible else [],
                                    business_age_max_years=3),
        eligibility_parsed=True, support_amount_max=100_000_000, support_amount_text="1억원",
        form_spec=FormSpec(form_version="예비-2026", applicant_types=["예비창업자", "개인사업자", "법인"],
                           section_codes=codes, section_titles=["문제인식", "실현가능성", "성장전략"],
                           format_spec=FormatSpec(style_type="개조식", ending_rule="단정형", banned_expressions=[]),
                           attachment_required=False),
        evaluation_items=[EvalItem(item_code=code, item_name=code, max_score=m, description=code) for code, m in EVAL],
        summary_embedding=[0.0, 0.1],
    )


def stub_rubric() -> Rubric:
    return Rubric(rubric_id="rubric-stub", version="stub-1", items=[
        RubricItem(item_code=code, criteria=["기준"], score_bands=[{"min": 0, "max": m, "label": "구간"}],
                   evidence_required=True) for code, m in EVAL])


def make_constants() -> Callable:
    rubric = stub_rubric()

    def constants(ctx, name: str) -> Any:
        if name == "rubric":
            return rubric
        raise KeyError(name)
    return constants


# ── 공통 도움 ─────────────────────────────────────────
def _ask(tools: Tools, purpose: str) -> None:
    tools.llm([{"role": "user", "content": purpose}], schema=Ack, purpose=purpose)


def _check(sc: StubScenario, task_id: str, rework_input, final_action: str) -> CheckResult:
    fail_times = sc.check_fail_times.get(task_id, 0)
    n = sc.tick(f"check:{task_id}")
    if n < fail_times:
        final = rework_input is not None and rework_input.is_final_attempt and task_id not in sc.omit_final_action
        return CheckResult(passed=False, failures=[f"{task_id} 검사 불통과 {n + 1}"],
                           final_action=final_action if final else None)
    return CheckResult(passed=True, failures=[])


def _maybe_raise(sc: StubScenario, step: str) -> None:
    if step in sc.raise_in:
        raise RuntimeError(f"{step} 스텁 오류")


def _doc_score(total: float) -> DocScore:
    items, acc = [], 0.0
    for i, (code, m) in enumerate(EVAL):
        s = round(m * total / DOC_LAYER_MAX, 1) if i < len(EVAL) - 1 else round(total - acc, 1)
        acc += s
        items.append(DocScoreItem(item_code=code, score=s, max_score=m, evidence_locator=f"{code}-근거", comment=""))
    return DocScore(total=total, items=items)


def _code_check(kind: str, code_total: float) -> CodeCheckResult:
    weights, names = (HTML_WEIGHTS, HTML_NAMES) if kind == "html" else (SVG_WEIGHTS, SVG_NAMES)
    deficit, failed = 15 - code_total, set()
    for no in (4, 5, 3, 6, 8, 2, 7):
        w = weights[no - 1]
        if deficit >= w:
            failed.add(no)
            deficit -= w
    checks = [CodeCheck(no=i + 1, name=names[i], weight=weights[i], passed=(i + 1) not in failed, detail="")
              for i in range(8)]
    return CodeCheckResult(total=code_total, checks=checks)


# ── 스텁 묶기 ─────────────────────────────────────────
def bind_stubs(registry: TaskRegistry, sc: StubScenario, *, now: Callable[[], datetime] = datetime.now) -> None:
    today = lambda: now().date()  # noqa: E731

    def r8(inp: c.R8In) -> c.R8Out:
        return c.R8Out(reference_docs=[ReferenceDoc(doc_id=f"doc-{i}", file_name=f.file_name, format=f.format,
                                                    extracted_text="추출 텍스트", extract_status="성공",
                                                    original_discarded_at=now())
                                       for i, f in enumerate(inp.attachments)])

    def tc1(inp: c.TC1In, tools: Tools) -> c.TC1Out:
        _ask(tools, "카테고리 판정")
        f = inp.form_input
        item = ItemSpec(item_name=f.idea_text[:20], one_line_summary=f.idea_text, target_customer="소상공인",
                        core_features=["회원 등록·조회", "수업 예약"], category=sc.category, keywords=["헬스장"])
        # companyInfo는 폼 값을 코드로 그대로 옮긴다 (LLM에 맡기지 않음)
        company = CompanyInfo(**{k: getattr(f, k) for k in CompanyInfo.model_fields if hasattr(f, k)})
        return c.TC1Out(item_spec=item, category=sc.category, company_info=company,
                        category_reason="화면 중심 서비스", confidence=0.8)

    def tc2(inp: c.TC2In, tools: Tools) -> c.TC2Out:
        mode = None
        try:
            tools.search("임베딩 검색", lambda timeout: _search_or_fail(sc.embed_fail))
        except ToolCallExhausted:
            mode = "BM25단독"  # 임베딩 검색 오류 → BM25 단독 순위 (5-3)
        tools.search("BM25 검색", lambda timeout: [])
        n = sc.candidate_count if inp.offset == 0 else min(10, sc.candidate_count)
        cards = [AnnouncementCard(
            announcement_id=f"A{inp.offset + i + 1:02d}", title=f"공고 {inp.offset + i + 1}", agency="기관",
            apply_end=inp.today + timedelta(days=30), support_amount_max=100_000_000, fit_score=0.9,
            rank=inp.offset + i + 1, display_type="card" if inp.offset + i < 3 else "list", match_reason="유사",
            source_notice="본 AI 요약 정보는 K-Startup 공고 내용을 바탕으로 생성되었습니다.",
            original_url="https://example.invalid") for i in range(n)]
        return c.TC2Out(candidates=cards, collection_status=sc.collection_status, filtered_count=n,
                        fallback_used=mode is not None, fallback_mode=mode)

    def g01(inp: c.G01In) -> c.G01Out:
        _maybe_raise(sc, "G-01")
        if not inp.eligibility_parsed:
            return c.G01Out(gate_result=GateResult(passed=False, failed_conditions=[], missing_inputs=[],
                                                   undecidable=True))
        failed = [] if inp.company_info.applicant_type in inp.eligibility.applicant_types else ["지원대상 유형"]
        return c.G01Out(gate_result=GateResult(passed=not failed, failed_conditions=failed, missing_inputs=[],
                                               undecidable=False), business_age_years=None)

    def tc3(inp: c.TC3In, tools: Tools) -> c.TC3Out:
        _ask(tools, "작업 분해")
        order = ["T-C1", "T-C2", "T-C3", "T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "T-V1", "T-B1", "T-B2",
                 "T-V2", "T-P1", "T-P2"]
        agent = {"C": "조율", "S": "전략", "W": "작성", "B": "구현", "P": "검수"}
        if inp.item_spec.category == "원페이지":
            order.remove("T-B1")
        tasks = [TaskInstruction(task_id=t, agent=("검증-1" if t == "T-V1" else "검증-2" if t == "T-V2"
                                                     else agent[t[2]]),
                                 order=i + 1, instruction=f"{t} 지시",
                                 context={"formVersion": inp.selected_announcement.form_spec.form_version,
                                          "applyEnd": inp.selected_announcement.apply_end.isoformat(),
                                          "supportAmountMax": inp.selected_announcement.support_amount_max})
                 for i, t in enumerate(order)]
        plan = TaskPlan(plan_id="plan-1", category=inp.item_spec.category, tasks=tasks)
        return c.TC3Out(task_plan=plan, task_count=len(tasks), instruction_set=tasks)

    def ts1(inp: c.TS1In, tools: Tools) -> c.TS1Out:
        _ask(tools, "요구사항 분석")
        feats = list(inp.item_spec.core_features)
        ra = RequirementAnalysis(problem_statement="문제", target_customer="고객", feature_list=feats,
                                 differentiator="차별점", use_cases=["사례"])
        return c.TS1Out(requirement_analysis=ra, feature_list=feats,
                        check=_check(sc, "T-S1", inp.rework_input, "itemSpec.coreFeatures 승계"))

    def ts2(inp: c.TS2In, tools: Tools) -> c.TS2Out:
        _ask(tools, "시장 분석")
        ma = MarketAnalysis(market_definition="시장", competitors=["경쟁사"], positioning="포지션",
                            market_size=[MarketSizeItem(label="국내 시장", value=1200, unit="억원",
                                                        source_name="통계청", basis="추정")])
        return c.TS2Out(market_analysis=ma, numeric_tokens=[Token(type="수치금액", value="1200억원", count=1)],
                        check=_check(sc, "T-S2", inp.rework_input, "출처 없는 수치 제거"))

    def tw1(inp: c.TW1In, tools: Tools) -> c.TW1Out:
        feats = list(inp.requirement_analysis.feature_list)
        if sc.tw1_change_features:
            feats = feats + ["임의 기능"]
        sections = []
        for code, title in zip(inp.form_spec.section_codes, inp.form_spec.section_titles):
            _ask(tools, f"섹션 {code} 작성")
            sections.append(PlanSection(section_code=code, title=title, sentences=[
                Sentence(sentence_id=f"s-{code}-{i}", text=f"{title} 문장 {i} (1억원)", is_title=False, paragraph_no=1)
                for i in range(1, 3)]))
        plan = PlanDoc(sections=sections, feature_list=feats, charts=[], tables=[], protected_tokens=[])
        return c.TW1Out(plan_doc=plan, sections=sections, feature_list=feats,
                        check=_check(sc, "T-W1", inp.rework_input, "입력에 없는 경력 서술 삭제"))

    def tw2(inp: c.TW2In, tools: Tools) -> c.TW2Out:
        _ask(tools, "그래프")
        chart = ChartSpec(chart_id="chart-1", type="bar", title="시장 규모", axis_labels=["연도", "억원"],
                          series=[{"x": 2026, "y": 1200}], source_ref="1-1")
        return c.TW2Out(charts=[chart], check=_check(sc, "T-W2", inp.rework_input, "차트 폐기 · 참조 문구 제거"))

    def tw3(inp: c.TW3In, tools: Tools) -> c.TW3Out:
        _ask(tools, "표")
        table = TableSpec(table_id="table-1", title="자금운용", headers=["항목", "금액"], rows=[["개발", "5천만원"]],
                          source_ref="3-3")
        return c.TW3Out(tables=[table], check=_check(sc, "T-W3", inp.rework_input, "표 제거 · 본문 서술 대체"))

    def m1(inp: c.M1In) -> c.M1Out:
        _maybe_raise(sc, "M-1")
        return c.M1Out(plan_doc=inp.plan_doc.model_copy(update={"charts": inp.charts, "tables": inp.tables}))

    def tv1(inp: c.TV1In, tools: Tools) -> c.TV1Out:
        _ask(tools, "문서층 채점")
        ds = _doc_score(sc.pick("T-V1", sc.doc_scores))
        return c.TV1Out(doc_score=ds, items=ds.items, variance_flag=False)

    def g02a(inp: c.G02aIn) -> c.G02aOut:
        _maybe_raise(sc, "G-02a")
        display = round(inp.doc_score.total / DOC_LAYER_MAX * 100, 1)
        orders = _doc_orders(inp.doc_score, inp.threshold)
        na = _next_action(display >= inp.threshold, orders, inp.rework_usage)
        report = ScoreReport(
            doc_score=inp.doc_score, artifact_score=None, total=inp.doc_score.total, threshold=inp.threshold,
            passed=display >= inp.threshold, failed_task_ids=sorted({o.task_id for o in orders}),
            rework_orders=orders, rework_usage=inp.rework_usage, phase="document", display_score=display,
            carried_over_layer=None, rework_diff=[],
            comparisons=inp.cycle_info.comparisons if inp.cycle_info else [],
            notices=[ch.final_action for ch in (inp.checks or []) if ch.final_action],
            settings_snapshot=inp.settings_snapshot, rubric_version=inp.rubric_version)
        return c.G02aOut(score_report=report, failed_task_ids=report.failed_task_ids, rework_orders=orders,
                         next_action=na)

    def tb1(inp: c.TB1In, tools: Tools) -> c.TB1Out:
        _ask(tools, "실행 파일 제작")
        proto = Prototype(entry_file_path="/prototype.html", kind="html", source_text="<html lang='ko'></html>",
                          asset_paths=[], implemented_features=list(inp.feature_list))
        return c.TB1Out(prototype=proto, implemented_features=list(inp.feature_list),
                        entry_file_path="/prototype.html", check=_check(sc, "T-B1", inp.rework_input, ""))

    def tb2(inp: c.TB2In, tools: Tools) -> c.TB2Out:
        _ask(tools, "인포그래픽 제작")
        fmt = "svg" if inp.category == "원페이지" else "png"
        return c.TB2Out(infographic=Infographic(image_path=f"/infographic.{fmt}", format=fmt, alt_text="인포그래픽"),
                        check=_check(sc, "T-B2", inp.rework_input, ""))

    def m2(inp: c.M2In) -> c.M2Out:
        return c.M2Out(prototype=Prototype(entry_file_path="onepage.svg", kind="svg-onepage",
                                           source_text="<svg><text>원페이지</text></svg>",
                                           asset_paths=[inp.infographic.image_path],
                                           implemented_features=list(inp.feature_list)))

    def g04(inp: c.G04In) -> c.G04Out:
        _maybe_raise(sc, "G-04")
        return c.G04Out(readme_path="/README.md")

    def m3(inp: c.M3In) -> c.M3Out:
        _maybe_raise(sc, "M-3")
        return c.M3Out(prototype=inp.prototype.model_copy(update={"readme_path": inp.readme_path}))

    def tv2(inp: c.TV2In, tools: Tools) -> c.TV2Out:
        try:
            _ask(tools, "대조 보조")
            judged = "htmlParse" if inp.prototype.kind == "html" else "svgTextParse"
        except ToolCallExhausted:
            judged = "htmlParse" if inp.prototype.kind == "html" else "svgTextParse"  # 문자열 대조만으로 산출
        code_total, feat = sc.pick("T-V2", sc.art_scores)
        missing = max(0, round((15 - feat) / 4))
        fm = FeatureMatchResult(score=feat, missing_features=inp.feature_list[:missing], extra_features=[],
                                findings=[f"'{m}' 기능이 프로토타입에 존재하지 않습니다." for m in inp.feature_list[:missing]],
                                judged_by=judged)
        cc = _code_check(inp.prototype.kind, code_total)
        return c.TV2Out(artifact_score=ArtifactScore(total=code_total + feat, code_check=cc, feature_match=fm),
                        code_check=cc, feature_match=fm)

    def g02b(inp: c.G02bIn) -> c.G02bOut:
        total = round(inp.doc_score.total + inp.artifact_score.total, 1)
        orders = _doc_orders(inp.doc_score, inp.threshold) + _art_orders(inp.artifact_score, sc.category)
        na = _next_action(total >= inp.threshold, orders, inp.rework_usage)
        ci = inp.cycle_info
        diff: list[ReworkDiff] = []
        if ci is not None:
            if ci.previous_doc_score is not None:
                diff.append(ReworkDiff(task_id="T-W1", layer="document", label="문서층",
                                       before_summary=f"{ci.previous_doc_score.total}/70",
                                       after_summary=f"{inp.doc_score.total}/70"))
            if ci.previous_artifact_score is not None:
                diff.append(ReworkDiff(task_id="T-V2", layer="artifact", label="산출물층",
                                       before_summary=f"{ci.previous_artifact_score.total}/30",
                                       after_summary=f"{inp.artifact_score.total}/30"))
        report = ScoreReport(
            doc_score=inp.doc_score, artifact_score=inp.artifact_score, total=total, threshold=inp.threshold,
            passed=total >= inp.threshold, failed_task_ids=sorted({o.task_id for o in orders}),
            rework_orders=orders, rework_usage=inp.rework_usage, phase="overall", display_score=total,
            carried_over_layer=ci.carried_over_layer if ci else None, rework_diff=diff,
            comparisons=ci.comparisons if ci else [], notices=[], settings_snapshot=inp.settings_snapshot,
            rubric_version=inp.rubric_version)
        return c.G02bOut(score_report=report, failed_task_ids=report.failed_task_ids, rework_orders=orders,
                         next_action=na, rework_diff=diff)

    def g03(inp: c.G03In) -> c.G03Out:
        if sc.no_tokens:
            return c.G03Out(protected_tokens=[])
        a = inp.announcement
        tokens = [Token(type="수치금액", value=a.support_amount_text, count=1),
                  Token(type="날짜", value=a.apply_end.isoformat(), count=1),
                  Token(type="고유명사", value=a.title, count=1),
                  Token(type="고유명사", value=inp.company_info.representative_name, count=1)]
        tokens += [Token(type="기능명", value=f, count=1) for f in inp.feature_list] + list(inp.numeric_tokens)
        return c.G03Out(protected_tokens=tokens)

    def tp1(inp: c.TP1In, tools: Tools) -> c.TP1Out:
        _ask(tools, "형식 검수")
        ids = [s.sentence_id for sec in inp.plan_doc.sections for s in sec.sentences][: sc.tp1_targets]
        return c.TP1Out(format_findings=[FormatFinding(sentence_id=i, violation_type="종결형", detail="단정형으로")
                                         for i in ids], target_sentence_ids=ids)

    def tp2(inp: c.TP2In, tools: Tools) -> c.TP2Out:
        tools.llm([{"role": "user", "content": inp.sentence.text}], schema=Ack, purpose=f"윤문 재수행 {inp.redo_count}")
        plan = sc.tp2_behavior.get(inp.sentence.sentence_id, ["ok"])
        behavior = plan[min(inp.redo_count, len(plan) - 1)]
        if behavior == "ok":
            revised = inp.sentence.model_copy(update={"text": inp.sentence.text + " (윤문)"})
            return c.TP2Out(revised=revised, adopted=True, final_redo_count=inp.redo_count,
                            token_check=TokenCheckResult(passed=True, missing_tokens=[], altered_tokens=[],
                                                         contaminated_tokens=[]))
        text = "동일 출력" if behavior == "same" else f"변형 {inp.redo_count}"
        return c.TP2Out(revised=inp.sentence.model_copy(update={"text": text}), adopted=False,
                        final_redo_count=inp.redo_count,
                        token_check=TokenCheckResult(passed=False, missing_tokens=["1억원"], altered_tokens=[],
                                                     contaminated_tokens=[]),
                        next_redo_hint=["'1억원' 유지"])

    def m4(inp: c.M4In) -> c.M4Out:
        by_id = {r.sentence_id: r for r in inp.sentence_results}
        sections = [sec.model_copy(update={"sentences": [
            by_id[s.sentence_id].revised if s.sentence_id in by_id and by_id[s.sentence_id].adopted else s
            for s in sec.sentences]}) for sec in inp.plan_doc.sections]
        n = len(inp.target_sentence_ids)
        first_pass = sum(1 for r in inp.sentence_results if r.adopted and r.final_redo_count == 0)
        log = ProofreadLog(
            total_sentences=n, adopted_count=sum(1 for r in inp.sentence_results if r.adopted),
            retained_by_check_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "검증실패"],
            retained_by_call_failure_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "호출실패"],
            early_stopped_sentence_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "조기중단"],
            token_preservation_rate=(first_pass / n) if n else 1.0, model_version=inp.model_version)
        return c.M4Out(plan_doc=inp.plan_doc.model_copy(update={"sections": sections}), proofread_log=log)

    def tc4(inp: c.TC4In, tools: Tools) -> c.TC4Out:
        d = Deliverable(plan_doc_path="/plan.docx", prototype_path=inp.prototype.entry_file_path,
                        infographic_path=inp.infographic.image_path, score_report=inp.score_report,
                        proofread_log=inp.proofread_log, disclaimer=DISCLAIMER, prototype_notice=PROTOTYPE_NOTICE,
                        score_notice=SCORE_NOTICE, submission_notice=SUBMISSION_NOTICE)
        return c.TC4Out(deliverable=d, user_message="계획서 · 프로토타입 · 검증 결과를 내려받을 수 있습니다.")

    for tid, fn in {
        "R-8": r8, "T-C1": tc1, "T-C2": tc2, "G-01": g01, "T-C3": tc3, "T-S1": ts1, "T-S2": ts2,
        "T-W1": tw1, "T-W2": tw2, "T-W3": tw3, "M-1": m1, "T-V1": tv1, "G-02a": g02a, "T-B1": tb1,
        "T-B2": tb2, "M-2": m2, "G-04": g04, "M-3": m3, "T-V2": tv2, "G-02b": g02b, "G-03": g03,
        "T-P1": tp1, "T-P2": tp2, "M-4": m4, "T-C4": tc4,
    }.items():
        registry.bind(tid, fn)


def _search_or_fail(fail: bool) -> list:
    if fail:
        raise ProviderError("embedding down", status=503)
    return []


def _doc_orders(ds: DocScore, threshold: float) -> list[ReworkOrder]:
    # 계획서 항목 묶음 구성은 미확정 — 스텁은 평가 항목 하나를 묶음 하나로 둔다
    return [ReworkOrder(task_id="T-W1", unit="묶음", targets=[f"묶음-{it.item_code}"],
                        reason=f"{it.item_code} {it.score}/{it.max_score}", instruction_delta=f"{it.item_code} 보완",
                        layer="document")
            for it in ds.items if it.score / it.max_score * 100 < threshold]


def _art_orders(score: ArtifactScore, category: str) -> list[ReworkOrder]:
    kind = "svg-onepage" if category == "원페이지" else "html"
    reasons: dict[str, list[str]] = {}
    for ch in score.code_check.checks:
        if not ch.passed:
            reasons.setdefault(CODE_CHECK_TARGET[kind][ch.no], []).append(f"코드 검증 {ch.no}번 {ch.name}")
    if score.feature_match.missing_features:
        reasons.setdefault(FEATURE_MISSING_TARGET[kind], []).append(f"대조 {score.feature_match.score}/15")
    orders = []
    for task_id, rs in reasons.items():
        if task_id == "G-04" and not LIST_README_BUNDLE:
            continue
        orders.append(ReworkOrder(task_id=task_id, unit="묶음", targets=[TASK_BUNDLE[task_id]], reason="; ".join(rs),
                                  instruction_delta="; ".join(rs), layer="artifact"))
    return orders


def _next_action(passed: bool, orders: list[ReworkOrder], usage) -> str:
    if passed:
        return "진행가능"
    remaining = {u.bundle_id: u.remaining for u in usage}
    names = [t for o in orders for t in (o.targets if o.layer == "document" else [TASK_BUNDLE.get(o.task_id, o.task_id)])]
    if names and all(remaining.get(b, 1) <= 0 for b in names):
        return "상한도달"
    return "재작성권유"

