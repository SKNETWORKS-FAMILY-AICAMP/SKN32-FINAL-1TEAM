"""S-Brain Task 등록부 — 시트 2(실행 순서 · 호출 규칙) · 시트 3(입출력) 기준.

실행 함수(fn)는 여기서 묶지 않는다. Agent 구현(지금은 스텁)이 bind로 끼운다.
합치기 M-1 ~ M-4와 R-8은 기준 문서에 Task ID가 없어 구현용 ID를 붙였다.
"""
from __future__ import annotations

from ..contracts import tasks as c
from ..orchestrator.registry import (
    CHECKS, INSTR, PARTIAL, PARTIAL_SUFFIX, REWORK, TODAY, FailurePolicy, TaskRegistry, TaskSpec, TempRule,
    art, cmd, const, flow_value, run_field, setting,
)
from .rework_map import FINAL_ACTION_EXCEPTIONS

SA = "selectedAnnouncement"
# T-C3가 고른 양식 · 평가 항목 · 채점 기준표 (확장 출력, 시트 4 이름)
FORM_SPEC, EVAL_ITEMS, RUBRIC = "formSpec", "evaluationItems", "rubric"
# 재작성 · 재수행 때 다시 쓴 지시문 (내부 산출물 <taskId>.instruction, 문자열 — 재작성 비교 · 되돌리기 대상 아님)
INSTRUCTION_SUFFIX = ".instruction"
# 추가 조회 결과 (확장, 등록부 밖 — Orchestrator가 만든다, spec 4.2.2). 유효한(성공한) 추가 조회만 그 결과와 같은 저장에서
# 남긴다. 실패한 추가 조회가 남긴 T-C2 출력(candidates 버전)은 화면 · 결과 · 한도 · 공고 선택 어디서도 읽지 않는다.
FIRST_CANDIDATES = "firstCandidates"   # 첫 조회 목록 — 추가 조회에 다시 나온 카드를 새 내용으로 바꾼 것 (자리 · 순위 그대로)
MORE_CANDIDATES = "moreCandidates"     # 추가 조회 목록 — 첫 조회와 겹친 공고를 뺀 것 (받은 순서 그대로)
# 전략 · 작성 · 검증-1 확장 출력 (spec 4.7, 결정 0024) — 기준 문서 타입이 없는 확장 출력이라 이 이름을 쓴다
STRATEGY_DATA = "strategyData"               # T-S1 — 담당자 전략 함수 결과
MARKET_STRATEGY_DATA = "marketStrategyData"  # T-S2 — 담당자 시장 함수 결과
SECTION_OUTPUTS = "sectionOutputs"           # T-W1 — 본문 항목 번호 → F16 결과
DIAGRAMS = "diagrams"                        # T-W2 — 그림 목록 (DiagramSpec)
DIAGRAM_OUTPUTS = "diagramOutputs"           # T-W2 — 그림 항목 번호 → F18 결과
TABLE_SECTIONS = "tableSections"             # T-W3 — 표 항목 서술 · 대체 본문 (PlanSection)
TABLE_OUTPUTS = "tableOutputs"               # T-W3 — 표 항목 번호 → F17 결과
SECTION_RESULTS = "sectionResults"           # T-V1 — 항목별 검증-1 판정 (SectionResult)

# 산출물 키 중 첫 버전 이후 바뀌면 안 되는 것 (시트 2 T-S1 · T-W1: 확정 후 변경 불가)
IMMUTABLE_KEYS = frozenset({"featureList"})


def _check_key(task_id: str) -> str:
    return f"{task_id}.check"


def build_registry() -> TaskRegistry:
    r = TaskRegistry()

    def task(task_id, name, agent, order, i, o, inputs, outputs, primary, **kw):
        kw.setdefault("counted", True)
        kw.setdefault("uses_llm", True)
        if task_id in FINAL_ACTION_EXCEPTIONS:
            kw.setdefault("final_action_exception", True)
        r.register(TaskSpec(task_id, name, agent, "task", i, o, inputs, outputs, primary, order=order, **kw))

    def rule(task_id, name, agent, order, i, o, inputs, outputs, primary, kind="rule", **kw):
        r.register(TaskSpec(task_id, name, agent, kind, i, o, inputs, outputs, primary, order=order, **kw))

    # ── 사전 단계 ─────────────────────────────────────
    rule("R-8", "첨부 문서 텍스트 추출", "조율", None, c.R8In, c.R8Out,
         {"attachments": art("formInput", "attachments")},
         {"reference_docs": "referenceDocs"}, "reference_docs")
    task("T-C1", "요구사항 해석", "조율", 1, c.TC1In, c.TC1Out,
         {"form_input": art("formInput"), "reference_docs": art("referenceDocs", optional=True)},
         {"item_spec": "itemSpec", "category": "category", "company_info": "companyInfo",
          "category_reason": "categoryReason", "confidence": "confidence",
          "reference_summary": "referenceSummary"}, "item_spec",
         failure=FailurePolicy(resumable=False))  # 재개 없이 진입 전 상태로 롤백 (E-C1-TIMEOUT)
    task("T-C2", "공고 매칭", "조율", 2, c.TC2In, c.TC2Out,
         {"item_spec": art("itemSpec"), "company_info": art("companyInfo"), "today": TODAY,
          "top_k": const("topK"), "offset": cmd("offset", 0)},
         {"candidates": "candidates", "collection_status": "collectionStatus",
          "filtered_count": "filteredCount", "fallback_used": "fallbackUsed",
          "fallback_mode": "fallbackMode"}, "candidates",
         # 추가 조회 구간(MORE)에서는 어떤 오류든 흐름이 받아 공고선택 대기로 돌리고 기회를 돌려준다(spec 4.2.3).
         # 사전 단계(PRE, 첫 조회)는 그대로 — 시작 요청이 X-C2-FAIL로 끝난다
         uses_llm=False, failure=FailurePolicy(resumable=False, fallback_in_task=True,
                                               rescue_segments=frozenset({"MORE"})))
    # G-01 — 고른 공고(마지막 decision의 공고 ID)의 상세 받기와 자격 판정을 한 단계에서 한다. 공고 서버를 tools로 부르는
    # Task(LLM 없음)이다 — 기준 문서 v1.10 시트 2도 공고 서버 호출에 재시도 · 제한 시간을 둔다. 선택 공고 · 자격 결과 · 업력을 한 번에 저장한다(spec 4.3.2).
    # 재개하지 않고, 자격 확인 구간(GATE)에서는 어떤 오류든 흐름이 받아 고르기 전 대기 지점으로 돌린다(4.3.4).
    # 고정 Task 14개에 세지 않는다(기획서 4-4).
    task("G-01", "자격요건 게이트", "조율", 3, c.G01In, c.G01Out,
         {"company_info": art("companyInfo"), "today": TODAY, "announcement_id": cmd("announcementId")},
         {"gate_result": "gateResult", "business_age_years": "businessAgeYears", "selected_announcement": SA},
         "gate_result", counted=False, uses_llm=False,
         failure=FailurePolicy(resumable=False, rescue_segments=frozenset({"GATE"})))

    # ── 계획서 작성 ───────────────────────────────────
    # T-C3 — 신청자 유형으로 양식 · 평가 항목 · 채점 기준표를 고르고(출력 formSpec · evaluationItems · rubric),
    # 뒷 단계(T-W1 · T-V1 · T-P1 · T-P2 · G-02a · G-02b)는 선택 공고의 같은 이름 필드 대신 이 출력을 읽는다 (T-C3 spec 4).
    # 선택 공고의 formSpec · evaluationItems는 자리 표시 값으로 남는다. 업력은 G-01 출력에서 받는다(입력 businessAgeYears)
    # 재개 때는 앞 실행이 받은 안내(T-C3.partial)를 prior_guidance로 받아 빠진 Task만 부른다(엔진 일반 장치 PARTIAL)
    task("T-C3", "작업 분해", "조율", 4, c.TC3In, c.TC3Out,
         {"selected_announcement": art(SA), "item_spec": art("itemSpec"), "gate_result": art("gateResult"),
          "company_info": art("companyInfo"), "reference_summary": art("referenceSummary", optional=True),
          "business_age_years": art("businessAgeYears", optional=True), "prior_guidance": PARTIAL},
         {"task_plan": "taskPlan", "task_count": "taskCount", "instruction_set": "instructionSet",
          "form_spec": FORM_SPEC, "evaluation_items": EVAL_ITEMS, "rubric": RUBRIC}, "task_plan")
    # T-S1 ~ T-V1 확장 입력 · 출력(spec 4.7, 결정 0024) — 전략 · 작성 · 검증-1 담당자 함수(F01 ~ F19)를 끼우며 더했다.
    # 직전 결과(base…)는 같은 키의 지금 값(없으면 None)이고, 재개 때 받은 결과는 PARTIAL로 잇는다(T-W3는 규칙 코드라 없음)
    task("T-S1", "요구사항 분석", "전략", 5, c.TS1In, c.TS1Out,
         {"item_spec": art("itemSpec"), "selected_announcement": art(SA), "instruction": INSTR,
          "rework_input": REWORK, "company_info": art("companyInfo"), "form_input": art("formInput"),
          "prior_results": PARTIAL},
         {"requirement_analysis": "requirementAnalysis", "feature_list": "featureList",
          "check": _check_key("T-S1"), "strategy_data": STRATEGY_DATA}, "requirement_analysis", redo=True)
    task("T-S2", "목표 시장 분석", "전략", 6, c.TS2In, c.TS2Out,
         {"item_spec": art("itemSpec"), "requirement_analysis": art("requirementAnalysis"),
          "selected_announcement": art(SA), "instruction": INSTR, "rework_input": REWORK,
          "strategy_data": art(STRATEGY_DATA), "prior_results": PARTIAL},
         {"market_analysis": "marketAnalysis", "numeric_tokens": "numericTokens",
          "check": _check_key("T-S2"), "market_strategy_data": MARKET_STRATEGY_DATA}, "market_analysis", redo=True)
    task("T-W1", "사업계획서 본문 작성", "작성", 7, c.TW1In, c.TW1Out,
         {"requirement_analysis": art("requirementAnalysis"), "market_analysis": art("marketAnalysis"),
          "selected_announcement": art(SA), "company_info": art("companyInfo"),
          "form_spec": art(FORM_SPEC), "instruction": INSTR, "rework_input": REWORK,
          "strategy_data": art(STRATEGY_DATA), "market_strategy_data": art(MARKET_STRATEGY_DATA),
          "feature_list": art("featureList"), "base_plan_doc": art("planDoc", optional=True),
          "base_section_outputs": art(SECTION_OUTPUTS, optional=True), "prior_results": PARTIAL},
         {"plan_doc": "planDoc", "sections": "sections", "feature_list": "featureList",
          "check": _check_key("T-W1"), "section_outputs": SECTION_OUTPUTS}, "plan_doc", redo=True)
    task("T-W2", "그래프 생성", "작성", 8, c.TW2In, c.TW2Out,
         {"plan_doc": art("planDoc"), "market_analysis": art("marketAnalysis"), "instruction": INSTR,
          "rework_input": REWORK, "strategy_data": art(STRATEGY_DATA), "feature_list": art("featureList"),
          "base_diagrams": art(DIAGRAMS, optional=True), "base_diagram_outputs": art(DIAGRAM_OUTPUTS, optional=True),
          "prior_results": PARTIAL},
         {"charts": "charts", "check": _check_key("T-W2"), "diagrams": DIAGRAMS,
          "diagram_outputs": DIAGRAM_OUTPUTS}, "charts", redo=True)
    # T-W3 — 담당자 F17은 규칙 코드라 LLM을 부르지 않는다(uses_llm=False — Task 설정 항목 없음, spec 4.2).
    # 지시문 입력(instruction)은 작업 계획에 그대로 있다
    task("T-W3", "표 생성", "작성", 9, c.TW3In, c.TW3Out,
         {"plan_doc": art("planDoc"), "company_info": art("companyInfo"), "selected_announcement": art(SA),
          "instruction": INSTR, "rework_input": REWORK, "strategy_data": art(STRATEGY_DATA),
          "form_spec": art(FORM_SPEC), "base_tables": art("tables", optional=True),
          "base_table_sections": art(TABLE_SECTIONS, optional=True),
          "base_table_outputs": art(TABLE_OUTPUTS, optional=True)},
         {"tables": "tables", "check": _check_key("T-W3"), "table_sections": TABLE_SECTIONS,
          "table_outputs": TABLE_OUTPUTS}, "tables", redo=True, uses_llm=False)
    rule("M-1", "합치기① 차트 · 표를 계획서에 합침", "조율", None, c.M1In, c.M1Out,
         {"plan_doc": art("planDoc"), "charts": art("charts"), "tables": art("tables"),
          "chart_check": art(_check_key("T-W2"), optional=True),
          "table_check": art(_check_key("T-W3"), optional=True),
          "diagrams": art(DIAGRAMS), "table_sections": art(TABLE_SECTIONS)},
         {"plan_doc": "planDoc"}, "plan_doc", kind="merge")
    # T-V1 — 재작성 · 검증-1 재수행 때 다시 검증할 목표 항목을 재작성 · 재수행 입력(REWORK)으로 받는다 (spec 4.7)
    task("T-V1", "사업계획서 검증", "검증-1", 10, c.TV1In, c.TV1Out,
         {"plan_doc": art("planDoc"), "evaluation_items": art(EVAL_ITEMS), "rubric": art(RUBRIC),
          "strategy_data": art(STRATEGY_DATA), "market_strategy_data": art(MARKET_STRATEGY_DATA),
          "feature_list": art("featureList"), "form_spec": art(FORM_SPEC),
          "section_outputs": art(SECTION_OUTPUTS), "table_outputs": art(TABLE_OUTPUTS),
          "diagram_outputs": art(DIAGRAM_OUTPUTS), "company_info": art("companyInfo"),
          "selected_announcement": art(SA), "base_section_results": art(SECTION_RESULTS, optional=True),
          "rework_input": REWORK, "prior_results": PARTIAL, "plan_doc_ref": flow_value("planDocRef"),
          "doc_layer_max": setting("scoring.doc_layer_max")},
         {"doc_score": "docScore", "items": "T-V1.items", "variance_flag": "varianceFlag",
          "section_results": SECTION_RESULTS, "score_policy_version": "scorePolicyVersion"}, "doc_score",
         temperature=TempRule(fixed=0.0))
    rule("G-02a", "문서 평가 판정", "조율", 11, c.G02aIn, c.G02aOut,
         {"doc_score": art("docScore"), "threshold": setting("scoring.threshold"),
          "rework_usage": run_field("rework_usage"), "selected_orders": cmd("selectedOrders"),
          "checks": CHECKS, "user_action": cmd("userAction"), "cycle_info": flow_value("cycleInfo"),
          "settings_snapshot": run_field("settings_snapshot"), "rubric_version": flow_value("rubricVersion"),
          "section_results": art(SECTION_RESULTS, optional=True)},
         {"score_report": "scoreReport.document", "failed_task_ids": "G-02a.failedTaskIds",
          "rework_orders": "G-02a.reworkOrders", "next_action": "G-02a.nextAction"}, "score_report")

    # ── 프로토타입 ───────────────────────────────────
    # T-B1 계획서(확장 입력) — T-B2 · T-V2와 같은 값. 계획서 반영 실행의 재작성 입력은 추적 기록용으로 그대로 붙인다
    task("T-B1", "실행 파일(HTML) 제작", "구현", 12, c.TB1In, c.TB1Out,
         {"feature_list": art("featureList"), "item_spec": art("itemSpec"), "category": art("category"),
          "plan_doc": art("planDoc"), "instruction": INSTR, "rework_input": REWORK},
         {"prototype": "prototype", "implemented_features": "implementedFeatures",
          "entry_file": "entryFile", "check": _check_key("T-B1")}, "prototype", redo=True)
    task("T-B2", "인포그래픽 제작", "구현", 13, c.TB2In, c.TB2Out,
         {"plan_doc": art("planDoc"), "item_spec": art("itemSpec"), "category": art("category"),
          "instruction": INSTR, "rework_input": REWORK},
         {"infographic": "infographic", "check": _check_key("T-B2")}, "infographic", redo=True)
    rule("M-2", "합치기② 원페이지 산출물을 Prototype으로 감쌈", "조율", None, c.M2In, c.M2Out,
         {"infographic": art("infographic"), "item_spec": art("itemSpec"), "feature_list": art("featureList")},
         {"prototype": "prototype"}, "prototype", kind="merge")
    # G-04 — 오류면 계속(점수 밖). 자체 검사(확장 출력 check — 실행 · 열람 안내 낱말)가 불통과면 재수행 횟수까지 같은
    # 입력으로 다시 만들고(재수행 루프가 만든 G-04.reworkInput은 입력에 연결하지 않아 쓰이지 않는다), 끝내 불통과면
    # 흐름이 관리자 기록('안내문서자체검사실패')을 남기고 계속한다 (2026-09-30 결정 5 · 6).
    # 안내 문서는 파일이라 파일을 쓰는 규칙 단계로 표시한다 — 엔진이 run(inp, files)로 파일 창구를 넘긴다 (결정 0023)
    rule("G-04", "실행 안내 문서 생성", "조율", 14, c.G04In, c.G04Out,
         {"prototype": art("prototype"), "infographic": art("infographic"), "item_spec": art("itemSpec"),
          "announcement": art(SA)},
         {"readme_file": "readmeFile", "check": _check_key("G-04")}, "readme_file", redo=True,
         failure=FailurePolicy(on_step_error="continue"), writes_files=True)
    rule("M-3", "합치기③ readmeFile을 Prototype에 기입", "조율", None, c.M3In, c.M3Out,
         {"prototype": art("prototype"), "readme_file": art("readmeFile", optional=True)},
         {"prototype": "prototype"}, "prototype", kind="merge")
    # T-V2 — 계획서(확장 입력, T-B2와 같은 값)는 원페이지 대조의 근거라 늘 채운다. 진단(확장 출력)은 관리자 기록 전용이다
    task("T-V2", "프로토타입 검증", "검증-2", 15, c.TV2In, c.TV2Out,
         {"prototype": art("prototype"), "infographic": art("infographic"), "feature_list": art("featureList"),
          "plan_doc": art("planDoc")},
         {"artifact_score": "artifactScore", "code_check": "codeCheck", "feature_match": "featureMatch",
          "diagnostics": "T-V2.diagnostics"},
         "artifact_score", failure=FailurePolicy(fallback_in_task=True))
    rule("G-02b", "종합 평가 판정", "조율", 16, c.G02bIn, c.G02bOut,
         {"doc_score": art("docScore"), "artifact_score": art("artifactScore"),
          "threshold": setting("scoring.threshold"), "rework_usage": run_field("rework_usage"),
          "selected_orders": cmd("selectedOrders"), "checks": CHECKS, "user_action": cmd("userAction"),
          "cycle_info": flow_value("cycleInfo"), "settings_snapshot": run_field("settings_snapshot"),
          "rubric_version": flow_value("rubricVersion"), "section_results": art(SECTION_RESULTS, optional=True)},
         {"score_report": "scoreReport.overall", "failed_task_ids": "G-02b.failedTaskIds",
          "rework_orders": "G-02b.reworkOrders", "next_action": "G-02b.nextAction",
          "rework_diff": "reworkDiff"}, "score_report")

    # ── 표현 검수 · 결과 통합 ───────────────────────────
    rule("G-03", "보호 토큰 추출", "검수", 17, c.G03In, c.G03Out,
         {"plan_doc": art("planDoc"), "announcement": art(SA), "company_info": art("companyInfo"),
          "feature_list": art("featureList"), "reference_summary": art("referenceSummary", optional=True),
          "numeric_tokens": art("numericTokens")},
         {"protected_tokens": "protectedTokens"}, "protected_tokens")
    task("T-P1", "사업계획서 문장 형식 검수", "검수", 18, c.TP1In, c.TP1Out,
         {"plan_doc": art("planDoc"), "format_spec": art(FORM_SPEC, "format_spec"),
          "protected_tokens": art("protectedTokens")},
         {"format_findings": "formatFindings", "target_sentence_ids": "targetSentenceIds"}, "format_findings")
    # T-P2는 문장별 병렬 실행이라 전용 실행기(flow)가 부르고, 결과는 sentenceResults로 모은다
    task("T-P2", "한국어 문장 윤문", "검수", 19, c.TP2In, c.TP2Out, {}, {}, "",
         temperature=TempRule(max=0.2), failure=FailurePolicy(keep_original_per_item=True), redo=True)
    rule("M-4", "합치기④ 검수 결과를 계획서에 반영 · 검수 로그 집계", "조율", None, c.M4In, c.M4Out,
         {"plan_doc": art("planDoc"), "sentence_results": art("sentenceResults"),
          "target_sentence_ids": art("targetSentenceIds"), "model_version": setting("tasks.T-P2.model")},
         {"plan_doc": "planDoc", "proofread_log": "proofreadLog"}, "plan_doc", kind="merge")
    task("T-C4", "결과 통합 · 전달", "조율", 20, c.TC4In, c.TC4Out,
         {"plan_doc": art("planDoc"), "prototype": art("prototype"), "infographic": art("infographic"),
          "score_report": art("scoreReport.overall"), "proofread_log": art("proofreadLog")},
         {"deliverable": "deliverable", "user_message": "userMessage"}, "deliverable",
         counted=False, uses_llm=False)  # LLM 사용 여부는 기준 문서에 없음 (미정)
    return r


def artifact_types(registry: TaskRegistry) -> tuple[dict, dict]:
    """산출물 키 → 타입. Task 출력 외에 Orchestrator · 사용자 명령이 만드는 산출물을 더한다.

    선택 공고(selectedAnnouncement)는 G-01 출력이라 등록부에서 온다 — 여기 따로 적지 않는다. 전략 · 작성 · 검증-1 확장 출력
    (strategyData · marketStrategyData · sectionOutputs · diagrams · diagramOutputs · tableSections · tableOutputs ·
    sectionResults · scorePolicyVersion)도 Task 출력이라 등록부에서 타입이 온다.
    """
    from ..models import AnnouncementCard, PreInput, ReworkInput
    exact = registry.artifact_types()
    exact.update({
        "formInput": PreInput,
        "sentenceResults": list[c.SentenceResult],
        "decision": dict,
        FIRST_CANDIDATES: list[AnnouncementCard],
        MORE_CANDIDATES: list[AnnouncementCard],
    })
    # 재개 때 이어 쓸 받은 결과 <taskId>.partial (엔진 일반 장치 PARTIAL — 키 → 받은 값 문자열)
    suffix = {".reworkInput": ReworkInput, INSTRUCTION_SUFFIX: str, PARTIAL_SUFFIX: dict[str, str]}
    return exact, suffix
