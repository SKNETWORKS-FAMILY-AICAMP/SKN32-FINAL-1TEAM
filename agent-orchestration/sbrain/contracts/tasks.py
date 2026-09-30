"""시트 3 Task 입출력 규격.

- 입력 · 출력 필드는 시트 3의 변수명 그대로다(JSON은 camelCase).
- 시트 3의 temperature 입력(T-V1 · T-P2)은 Task 입력에서 빼고 tools 설정으로 적용한다.
  같은 값을 두 곳에 두면 어긋날 수 있기 때문이다.
- 기준 문서에 없는 입력 · 출력은 ext()로 표시한다.
- M-1 ~ M-4(합치기)와 R-8은 기준 문서에 Task ID가 없어 구현용 ID를 붙였다.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field

from ..models import (
    AnnouncementCard, Announcement, ArtifactScore, ChartSpec, CheckResult,
    CodeCheckResult, CompanyInfo, Deliverable, DocScore, DocScoreItem,
    EligibilityRule, EvalItem, FeatureMatchResult, File, FormatFinding,
    FormatSpec, FormSpec, GateResult, Infographic, ItemSpec, MarketAnalysis,
    PlanDoc, PlanSection, PreInput, ProofreadLog, Prototype, ReferenceDoc,
    ReferenceSummary, RequirementAnalysis, ReworkComparison, ReworkDiff,
    ReworkInput, ReworkOrder, Rubric, ScoreReport, Sentence, TableSpec,
    TaskInstruction, TaskPlan, Token, TokenCheckResult, BundleUsage,
)
from ..models.base import (
    Category, CollectionStatus, FallbackMode, KeptReason, Layer, NextAction,
    SBModel, UserAction, ext,
)


# ── 확장 입력 · 출력 타입 ─────────────────────────────
class ReworkCycleInfo(SBModel):
    """확장 — G-02a · G-02b가 재작성 결과를 판정할 때 받는 사이클 정보.

    기준 문서의 G-02 입력에는 재작성 전 점수가 없어 전후 비교 결과를 담을 수 없다.
    전후 비교(높은 쪽 선택과 되돌리기)는 버전 포인터 조작이라 Orchestrator가 하고,
    그 결과를 이 입력으로 넘겨 scoreReport.comparisons · carriedOverLayer · reworkDiff에 담게 한다.
    """
    cycle_id: str
    screen: int
    comparisons: list[ReworkComparison]
    rescored_layers: list[Layer]
    carried_over_layer: Layer | None = None
    reworked_task_ids: list[str]
    previous_doc_score: DocScore | None = None
    previous_artifact_score: ArtifactScore | None = None


class SentenceResult(SBModel):
    """확장 — T-P2 문장별 결과를 Task 단위로 모은 산출물(sentenceResults)."""
    sentence_id: str
    adopted: bool
    revised: Sentence | None = None
    kept_reason: KeptReason | None = None
    final_redo_count: int
    token_check: TokenCheckResult | None = None


# ── 조율 ─────────────────────────────────────────────
class R8In(SBModel):
    attachments: list[File]


class R8Out(SBModel):
    reference_docs: list[ReferenceDoc]


class TC1In(SBModel):
    form_input: PreInput
    reference_docs: list[ReferenceDoc] | None = None


class TC1Out(SBModel):
    item_spec: ItemSpec
    category: Category
    company_info: CompanyInfo
    category_reason: str
    confidence: float | None = Field(None, ge=0, le=1)
    reference_summary: ReferenceSummary | None = None
    category_defaulted: bool = ext(False, note="카테고리 판정 실패로 기본값(웹개발)을 썼는지. 추적 기록용 (시트 2 T-C1 ③)")


class TC2In(SBModel):
    item_spec: ItemSpec
    company_info: CompanyInfo
    today: date
    top_k: int
    offset: int


class TC2Out(SBModel):
    candidates: list[AnnouncementCard] = Field(max_length=10)
    collection_status: CollectionStatus
    filtered_count: int
    fallback_used: bool
    fallback_mode: FallbackMode | None = None


class G01In(SBModel):
    company_info: CompanyInfo
    eligibility: EligibilityRule
    eligibility_parsed: bool
    today: date


class G01Out(SBModel):
    gate_result: GateResult
    business_age_years: float | None = None


class TC3In(SBModel):
    selected_announcement: Announcement
    item_spec: ItemSpec
    gate_result: GateResult
    company_info: CompanyInfo
    reference_summary: ReferenceSummary | None = None


class TC3Out(SBModel):
    task_plan: TaskPlan
    task_count: int
    instruction_set: list[TaskInstruction]


class G02aIn(SBModel):
    doc_score: DocScore
    threshold: float
    rework_usage: list[BundleUsage]
    selected_orders: list[ReworkOrder] | None = None
    checks: list[CheckResult] | None = None
    user_action: UserAction | None = None
    cycle_info: ReworkCycleInfo | None = ext(None, note="재작성 사이클 정보")
    settings_snapshot: dict[str, Any] = ext(default_factory=dict, note="판정에 쓴 설정값을 scoreReport에 기록하기 위한 입력 (Run.settingsSnapshot)")
    rubric_version: str = ext("", note="scoreReport.rubricVersion 기록용 (채점에 쓴 Rubric.version)")


class G02aOut(SBModel):
    score_report: ScoreReport
    failed_task_ids: list[str]
    rework_orders: list[ReworkOrder]
    next_action: NextAction


class G02bIn(SBModel):
    doc_score: DocScore
    artifact_score: ArtifactScore
    threshold: float
    rework_usage: list[BundleUsage]
    selected_orders: list[ReworkOrder] | None = None
    checks: list[CheckResult] | None = None
    user_action: UserAction | None = None
    cycle_info: ReworkCycleInfo | None = ext(None, note="재작성 사이클 정보")
    settings_snapshot: dict[str, Any] = ext(default_factory=dict, note="판정에 쓴 설정값을 scoreReport에 기록하기 위한 입력 (Run.settingsSnapshot)")
    rubric_version: str = ext("", note="scoreReport.rubricVersion 기록용 (채점에 쓴 Rubric.version)")


class G02bOut(SBModel):
    score_report: ScoreReport
    failed_task_ids: list[str]
    rework_orders: list[ReworkOrder]
    next_action: NextAction
    rework_diff: list[ReworkDiff]


class G04In(SBModel):
    prototype: Prototype
    infographic: Infographic
    item_spec: ItemSpec
    announcement: Announcement


class G04Out(SBModel):
    readme_path: str


class TC4In(SBModel):
    plan_doc: PlanDoc
    prototype: Prototype
    infographic: Infographic
    score_report: ScoreReport
    proofread_log: ProofreadLog


class TC4Out(SBModel):
    deliverable: Deliverable
    user_message: str


# ── 합치기 (조율 소속 규칙 단계, 구현용 ID) ─────────────────
class M1In(SBModel):
    """합치기① — T-W2 · T-W3 결과를 계획서에 합친다. 확정 동작(차트 폐기 등)도 checks로 받는다."""
    plan_doc: PlanDoc
    charts: list[ChartSpec]
    tables: list[TableSpec]
    chart_check: CheckResult | None = None
    table_check: CheckResult | None = None


class M1Out(SBModel):
    plan_doc: PlanDoc


class M2In(SBModel):
    """합치기② — 원페이지면 T-B2 산출물을 Prototype(kind='svg-onepage')으로 감싼다."""
    infographic: Infographic
    item_spec: ItemSpec
    feature_list: list[str]


class M2Out(SBModel):
    prototype: Prototype


class M3In(SBModel):
    """합치기③ — G-04가 만든 readmePath를 Prototype에 기입한다."""
    prototype: Prototype
    readme_path: str | None = None


class M3Out(SBModel):
    prototype: Prototype


class M4In(SBModel):
    """합치기④ — 채택된 문장을 계획서에 반영하고 ProofreadLog를 집계한다."""
    plan_doc: PlanDoc
    sentence_results: list[SentenceResult]
    target_sentence_ids: list[str]
    model_version: str


class M4Out(SBModel):
    plan_doc: PlanDoc
    proofread_log: ProofreadLog


# ── 전략 ─────────────────────────────────────────────
class TS1In(SBModel):
    item_spec: ItemSpec
    selected_announcement: Announcement
    instruction: str
    rework_input: ReworkInput | None = None


class TS1Out(SBModel):
    requirement_analysis: RequirementAnalysis
    feature_list: list[str]
    check: CheckResult


class TS2In(SBModel):
    item_spec: ItemSpec
    requirement_analysis: RequirementAnalysis
    selected_announcement: Announcement
    instruction: str
    rework_input: ReworkInput | None = None


class TS2Out(SBModel):
    market_analysis: MarketAnalysis
    numeric_tokens: list[Token]
    check: CheckResult


# ── 작성 ─────────────────────────────────────────────
class TW1In(SBModel):
    requirement_analysis: RequirementAnalysis
    market_analysis: MarketAnalysis
    selected_announcement: Announcement
    company_info: CompanyInfo
    form_spec: FormSpec
    instruction: str
    rework_input: ReworkInput | None = None


class TW1Out(SBModel):
    plan_doc: PlanDoc
    sections: list[PlanSection]
    feature_list: list[str]
    check: CheckResult


class TW2In(SBModel):
    plan_doc: PlanDoc
    market_analysis: MarketAnalysis
    instruction: str
    rework_input: ReworkInput | None = None


class TW2Out(SBModel):
    charts: list[ChartSpec]
    check: CheckResult


class TW3In(SBModel):
    plan_doc: PlanDoc
    company_info: CompanyInfo
    selected_announcement: Announcement
    instruction: str
    rework_input: ReworkInput | None = None


class TW3Out(SBModel):
    tables: list[TableSpec]
    check: CheckResult


# ── 검증 ─────────────────────────────────────────────
class TV1In(SBModel):
    plan_doc: PlanDoc
    evaluation_items: list[EvalItem]
    rubric: Rubric


class TV1Out(SBModel):
    doc_score: DocScore
    items: list[DocScoreItem]
    variance_flag: bool


class TV2In(SBModel):
    prototype: Prototype
    infographic: Infographic
    feature_list: list[str]


class TV2Out(SBModel):
    artifact_score: ArtifactScore
    code_check: CodeCheckResult
    feature_match: FeatureMatchResult


# ── 구현 ─────────────────────────────────────────────
class TB1In(SBModel):
    feature_list: list[str]
    item_spec: ItemSpec
    category: Category
    instruction: str
    rework_input: ReworkInput | None = None


class TB1Out(SBModel):
    prototype: Prototype
    implemented_features: list[str]
    entry_file_path: str
    check: CheckResult


class TB2In(SBModel):
    plan_doc: PlanDoc
    item_spec: ItemSpec
    category: Category
    instruction: str
    rework_input: ReworkInput | None = None


class TB2Out(SBModel):
    infographic: Infographic
    check: CheckResult


# ── 검수 ─────────────────────────────────────────────
class G03In(SBModel):
    plan_doc: PlanDoc
    announcement: Announcement
    company_info: CompanyInfo
    feature_list: list[str]
    reference_summary: ReferenceSummary | None = None
    numeric_tokens: list[Token]


class G03Out(SBModel):
    protected_tokens: list[Token]


class TP1In(SBModel):
    plan_doc: PlanDoc
    format_spec: FormatSpec
    protected_tokens: list[Token]


class TP1Out(SBModel):
    format_findings: list[FormatFinding]
    target_sentence_ids: list[str]


class TP2In(SBModel):
    sentence: Sentence
    protected_tokens: list[Token]
    format_findings: list[FormatFinding]
    format_spec: FormatSpec
    redo_hint: list[str]
    redo_count: int


class TP2Out(SBModel):
    revised: Sentence
    token_check: TokenCheckResult
    adopted: bool
    kept_reason: KeptReason | None = None
    final_redo_count: int
    next_redo_hint: list[str] = ext(default_factory=list, note="검수 Agent가 위반 유형별로 만든 재수행 지시. Orchestrator가 누적해 다음 호출의 redoHint로 넘긴다 (검수 파트 합의 필요)")


def output_types(model: type[SBModel]) -> dict[str, Any]:
    """출력 모델의 필드별 타입 (산출물 복원용)."""
    return {name: info.annotation for name, info in model.model_fields.items()}
