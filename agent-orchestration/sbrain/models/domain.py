"""시트 4 도메인 타입 — 입력 · 공고 · 계획서 · 산출물 · 검수 · 결과물.

사용 중지 타입(SupplementInput · SlotCheckResult · Message)과
웹팀 · 공고 수집 영역 타입(Account · Consent · SourceConfig)은 두지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field

from .base import (
    AgentName, ApplicantType, Category, ChartType, EndingRule, ExtractStatus,
    FileFormat, ImageFormat, JudgedBy, KeptReason, PrototypeKind, SBModel,
    StyleType, TokenType, ViolationType, ext,
)


# ── 입력 ─────────────────────────────────────────────
class File(SBModel):
    file_name: str
    format: FileFormat
    uploaded_at: datetime


class RevenueItem(SBModel):
    """확장 — 수익모델 항목 하나(서비스 · 상품명과 단가). 기준 문서는 단가 1개(int)만 둔다."""
    service_name: str
    unit_price: int                      # 원


class FormExtension(SBModel):
    """확장 — 사전 정보 입력 중 기준 문서 PreInput · CompanyInfo에 자리가 없는 값 (웹 DB 원본 그대로).

    PreInput과 CompanyInfo가 함께 쓴다. T-C1이 폼 값 그대로 companyInfo에 옮겨 계획서 작성까지 전달한다.
    """
    revenue_items: list[RevenueItem] = ext(
        default_factory=list, note="수익모델 항목 전체. revenueUnitPrice는 호환용으로 첫 항목 단가")
    company_name: str | None = ext(None, note="기업명 · 법인명(상호)")
    biz_type: str | None = ext(None, note="업종 (companies.biz_type)")
    representative_type: str | None = ext(None, note="대표자 유형(단독 · 공동 · 각자대표)")
    output_summary: str | None = ext(None, note="산출물 — 협약기간 내 목표(형태 · 수량)")
    tech_field: str | None = ext(None, note="전문기술분야")
    regional_priority_area: str | None = ext(None, note="지방우대 지역(해당 시 지역명)")
    occupation: str | None = ext(None, note="예비창업자 직업(직장명 제외)")
    representative_capability: str | None = ext(None, note="대표자의 기술력 · 노하우 · 인적 네트워크")
    self_in_kind_resources: str | None = ext(None, note="현물 자기부담 자원(보유 장비 · 공간 등)")


class PreInput(FormExtension):
    idea_text: str
    applicant_type: ApplicantType
    representative_name: str
    representative_career: list[str]
    founded_at: date | None = None
    revenue_unit_price: int
    development_period: str
    team_careers: list[str]
    birth_date: date
    gender: str
    region: str
    industry_code: str
    certifications: list[str] | None = None
    hiring_plan: str
    facilities: str
    partners: str
    is_first_startup: bool | None = None
    desired_scale: str | None = None
    business_reg_no: str | None = None
    self_fund_amount: int | None = None
    attachments: list[File] | None = None


class CompanyInfo(FormExtension):
    representative_name: str
    representative_career: list[str]
    founded_at: date | None = None
    business_age_years: float | None = None
    applicant_type: ApplicantType
    revenue_unit_price: int
    team_careers: list[str]
    region: str
    industry_code: str
    birth_date: date
    gender: str
    certifications: list[str] | None = None
    hiring_plan: str
    facilities: str
    partners: str
    is_first_startup: bool | None = None
    desired_scale: str | None = None
    business_reg_no: str | None = None
    self_fund_amount: int | None = None


class ItemSpec(SBModel):
    item_name: str
    one_line_summary: str
    target_customer: str
    core_features: list[str] = Field(min_length=1)
    category: Category
    keywords: list[str]


class ReferenceDoc(SBModel):
    doc_id: str
    file_name: str
    format: FileFormat
    extracted_text: str
    extract_status: ExtractStatus
    original_discarded_at: datetime


class Token(SBModel):
    type: TokenType
    value: str
    count: int


class Excerpt(SBModel):
    doc_id: str
    slot: str
    text: str


class ReferenceSummary(SBModel):
    doc_ids: list[str]
    excerpts: list[Excerpt]
    cited_numbers: list[Token]
    isolation_note: str


# ── 공고 · 양식 · 채점 기준 ─────────────────────────────
class EligibilityRule(SBModel):
    applicant_types: list[str]
    business_age_max_years: float | None = None
    age_max: int | None = None
    region_codes: list[str] | None = None
    industry_codes: list[str] | None = None


class FormatSpec(SBModel):
    style_type: StyleType
    ending_rule: EndingRule
    max_chars_per_section: int | None = None
    banned_expressions: list[str]


class FormSpec(SBModel):
    form_version: str
    applicant_types: list[str]
    section_codes: list[str]
    section_titles: list[str]
    max_chars_per_section: int | None = None
    format_spec: FormatSpec
    attachment_required: bool


class EvalItem(SBModel):
    item_code: str
    item_name: str
    max_score: float
    description: str


class RubricItem(SBModel):
    item_code: str
    criteria: list[str]
    score_bands: list[dict[str, Any]]
    evidence_required: bool


class Rubric(SBModel):
    rubric_id: str
    version: str
    items: list[RubricItem]


class Announcement(SBModel):
    announcement_id: str
    title: str
    agency: str
    support_field: str  # enum('창업(06)','기술개발(02)')
    apply_start: date
    apply_end: date
    status: str  # enum('모집중','마감')
    eligibility: EligibilityRule
    eligibility_parsed: bool
    support_amount_max: int
    support_amount_text: str
    form_spec: FormSpec
    evaluation_items: list[EvalItem]
    summary_embedding: list[float]
    bonus_info: str | None = None


class AnnouncementCard(SBModel):
    announcement_id: str
    title: str
    agency: str
    apply_end: date
    support_amount_max: int
    fit_score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1, le=20)
    display_type: str  # enum('card','list')
    match_reason: str
    source_notice: str
    original_url: str


class GateResult(SBModel):
    passed: bool
    failed_conditions: list[str]
    missing_inputs: list[str]
    undecidable: bool


# ── 작업 분해 ─────────────────────────────────────────
class TaskInstruction(SBModel):
    task_id: str
    agent: AgentName
    order: int
    instruction: str
    context: dict[str, Any]


class TaskPlan(SBModel):
    plan_id: str
    category: Category
    tasks: list[TaskInstruction] = Field(min_length=13, max_length=14)


# ── 전략 · 작성 ───────────────────────────────────────
class RequirementAnalysis(SBModel):
    problem_statement: str
    target_customer: str
    feature_list: list[str]
    differentiator: str
    use_cases: list[str]


class MarketSizeItem(SBModel):
    label: str
    value: float
    unit: str
    source_name: str
    source_url: str | None = None
    basis: str


class MarketAnalysis(SBModel):
    market_definition: str
    market_size: list[MarketSizeItem]
    competitors: list[str]
    positioning: str


class Sentence(SBModel):
    sentence_id: str
    text: str
    is_title: bool
    paragraph_no: int


class PlanSection(SBModel):
    section_code: str
    title: str
    sentences: list[Sentence]


class ChartSpec(SBModel):
    chart_id: str
    type: ChartType
    title: str
    axis_labels: list[str] = Field(min_length=2, max_length=2)
    series: list[dict[str, Any]]
    source_ref: str
    image_path: str | None = None


class TableSpec(SBModel):
    table_id: str
    title: str
    headers: list[str]
    rows: list[list[str]]
    source_ref: str


class PlanDoc(SBModel):
    sections: list[PlanSection]
    feature_list: list[str]
    charts: list[ChartSpec]
    tables: list[TableSpec]
    protected_tokens: list[Token]


# ── 구현 산출물 ───────────────────────────────────────
class Prototype(SBModel):
    entry_file_path: str
    kind: PrototypeKind
    source_text: str
    asset_paths: list[str]
    readme_path: str | None = None
    implemented_features: list[str]


class Infographic(SBModel):
    image_path: str
    format: ImageFormat
    alt_text: str


# ── 검수 ─────────────────────────────────────────────
class TokenCheckResult(SBModel):
    passed: bool
    missing_tokens: list[str]
    altered_tokens: list[str]
    contaminated_tokens: list[str]


class FormatFinding(SBModel):
    sentence_id: str
    violation_type: ViolationType
    detail: str


class ProofreadLog(SBModel):
    total_sentences: int
    adopted_count: int
    retained_by_check_ids: list[str]
    retained_by_call_failure_ids: list[str]
    early_stopped_sentence_ids: list[str]
    token_preservation_rate: float = Field(ge=0, le=1)
    model_version: str


# ── 결과물 ───────────────────────────────────────────
class Deliverable(SBModel):
    plan_doc_path: str
    prototype_path: str
    infographic_path: str
    score_report: "ScoreReport"
    proofread_log: ProofreadLog
    disclaimer: str
    prototype_notice: str
    score_notice: str
    submission_notice: str


from .scoring import ScoreReport  # noqa: E402

Deliverable.model_rebuild()
