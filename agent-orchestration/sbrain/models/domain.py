"""시트 4 도메인 타입 — 입력 · 공고 · 계획서 · 산출물 · 검수 · 결과물.

사용 중지 타입(SupplementInput · SlotCheckResult · Message)과
웹팀 · 공고 수집 영역 타입(Account · Consent · SourceConfig)은 두지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

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
    """시트 4 수익모델 항목 하나(서비스 · 상품명과 단가)."""
    service_name: str
    unit_price: int                      # 원


class FormExtension(SBModel):
    """PreInput · CompanyInfo가 함께 쓰는 사전 정보 입력 값 (웹 DB 원본 그대로). 기준 문서 v1.10에서 두 타입에 들어갔다.

    T-C1이 폼 값 그대로 companyInfo에 옮겨 계획서 작성까지 전달한다.
    """
    # 수익모델 항목 전체. revenueUnitPrice(확장)는 첫 항목 단가.
    # 기준 문서는 필수(1건 이상)이고 흐름이 늘 채운다. 기본값 빈 목록은 옛 실행 건 호환용 선언
    revenue_items: list[RevenueItem] = Field(default_factory=list)
    company_name: str | None = None                 # 기업명 · 법인명(상호)
    biz_type: str | None = None                     # 업종 (companies.biz_type)
    representative_type: str | None = None          # 대표자 유형(단독 · 공동 · 각자대표)
    output_summary: str | None = None               # 산출물 — 협약기간 내 목표(형태 · 수량)
    tech_field: str | None = None                   # 전문기술분야
    regional_priority_area: str | None = None       # 지방우대 지역(해당 시 지역명)
    occupation: str | None = None                   # 예비창업자 직업(직장명 제외)
    representative_capability: str | None = None    # 대표자의 기술력 · 노하우 · 인적 네트워크
    self_in_kind_resources: str | None = None       # 현물 자기부담 자원(보유 장비 · 공간 등)


class PreInput(FormExtension):
    idea_text: str
    applicant_type: ApplicantType
    representative_name: str
    representative_career: list[str]
    founded_at: date | None = None
    revenue_unit_price: int = ext(note="새 판(v1.10)에서 빠졌지만 남김 — 첫 수익모델 항목의 단가로 채움")
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
    is_first_startup: bool | None = ext(
        None, note="새 판(v1.10)에서 빠졌지만 남김 — 늘 비어 있고 공고 서버 요청의 first_startup으로 계속 보냄")
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
    revenue_unit_price: int = ext(note="새 판(v1.10)에서 빠졌지만 남김 — 첫 수익모델 항목의 단가로 채움")
    team_careers: list[str]
    region: str
    industry_code: str
    birth_date: date
    gender: str
    certifications: list[str] | None = None
    hiring_plan: str
    facilities: str
    partners: str
    is_first_startup: bool | None = ext(
        None, note="새 판(v1.10)에서 빠졌지만 남김 — 늘 비어 있고 공고 서버 요청의 first_startup으로 계속 보냄")
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


# 공고 모집 형태 표기 (applyPeriodType) — 공고 서버 값을 바꾼 것. 모르면 '모름' (spec 4.4)
APPLY_PERIOD_UNKNOWN = "모름"


class Announcement(SBModel):
    """시트 4 공고. 접수 시작 · 마감일 · 지원 금액 · 금액 표기는 비어 있을 수 있다
    (마감일 없는 공고 · 금액 정보 없는 공고 — 기준 문서 v1.10 시트 4, spec 5)."""
    announcement_id: str
    title: str
    agency: str
    support_field: str  # enum('창업(06)','기술개발(02)') — 공고 서버의 분류 문자열을 그대로 받는다
    apply_start: date | None = None
    apply_end: date | None = None
    status: str  # enum('모집중','마감')
    eligibility: EligibilityRule
    eligibility_parsed: bool
    support_amount_max: int | None = None
    support_amount_text: str | None = None
    form_spec: FormSpec
    evaluation_items: list[EvalItem]
    summary_embedding: list[float]
    bonus_info: str | None = None
    # 모집 형태 표기: 기간 있음 · 예산 소진 시까지 · 상시·수시 · 선착순·모집 완료 시까지 · 모름 (spec 4.4)
    apply_period_type: str = APPLY_PERIOD_UNKNOWN


class BonusItem(SBModel):
    """시트 4 가산점 항목 — 항목별 근거 하나(공고 서버 추천 결과의 bonus_items 한 항목)."""
    name: str
    points: float


class AnnouncementCard(SBModel):
    """시트 4 공고 카드. 마감일 · 지원 금액이 비어 있을 수 있다(추천 결과에는 금액이 없다 — 기준 문서 v1.10 시트 4, spec 5)."""
    announcement_id: str
    title: str
    agency: str
    apply_end: date | None = None
    support_amount_max: int | None = None
    fit_score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1, le=20)
    display_type: str  # enum('card','list')
    match_reason: str
    source_notice: str
    original_url: str
    apply_period_type: str = APPLY_PERIOD_UNKNOWN  # 모집 형태 표기 (Announcement.applyPeriodType과 같은 값)
    # 추가 조회에서 다시 나온 첫 조회 카드의 공고 내용이 바뀌었는지 — Orchestrator가 정한다 (spec 4.2.2)
    content_changed: bool = False
    # 공고 서버의 내용 버전. 공고 내용이 바뀔 때만 바뀐다. 같은지만 비교하며 웹은 쓰지 않는다
    content_version: str | None = None
    # 이 신청자가 받을 수 있는 가산점 합계. 0 = 해당 가점 없음, null = 계산하지 못함
    bonus_score: float | None = None
    bonus_items: list[BonusItem] = Field(default_factory=list)  # 가산점 항목별 근거 (합계와 맞는다)


class GateResult(SBModel):
    passed: bool
    failed_conditions: list[str]
    missing_inputs: list[str]
    undecidable: bool
    # 확인 필요 조건 이름('지원대상 유형' · '업력') — 읽지 못해 통과로 본 조건. 진행을 막지 않고 화면 4에 안내 (spec 4.3.3)
    unknown_conditions: list[str] = Field(default_factory=list)


# ── 작업 분해 ─────────────────────────────────────────
class TaskInstruction(SBModel):
    task_id: str
    agent: AgentName
    order: int
    instruction: str
    context: dict[str, Any]
    # 작업 분해가 쓴 안내(정리한 것) — 지시문의 안내 부분과 같은 글자. 지시 대상이 아니면 빈 문자열.
    # 재작성 · 재수행 때 안내를 다시 쓰는 출발점이다
    guidance: str = ""


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


# 보호 토큰 위반 종류 — 웹 proofread_logs.violation_type 표기 (시트 4 TokenType의 '수치금액'은 '수치·금액')
ProofreadViolationType = Literal["날짜", "수치·금액", "고유명사", "기능명"]


class RejectedAttempt(SBModel):
    """확장 — 보호 토큰 검사를 통과하지 못한(반려된) T-P2 시도 하나. 웹 proofread_logs '검수 회수 문단' 한 행.

    문장 내용(원문 · 시도 문장)을 담는다 — 산출물 내용을 기록에 남기지 않는 규칙의 유일한 예외라서
    웹 proofread_logs에만 쓰고(프로젝트 주인이 학습 데이터 편입에 동의한 경우만), 실행 기록 · 추적 사건 · 로그 ·
    관리자 조회에는 싣지 않는다.
    """
    run_id: str
    original_text: str
    corrected_text: str             # 반려된 시도 문장
    reason: str                     # 위반 요약
    attempt_no: int = Field(ge=1)
    violation_type: ProofreadViolationType | None = None
    violation_note: str             # 위반 토큰 목록 전체
    model_version: str | None = None  # 그 시도를 만든 T-P2 실행의 모델


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
