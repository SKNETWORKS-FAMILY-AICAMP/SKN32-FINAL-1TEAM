"""Pydantic v2 요청/응답 스키마. app_schema.sql(설계 문서 기준)과 1:1로 대응한다."""
import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------
class GoogleLoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id_token: str = Field(..., description='Google Identity Services 가 프론트에서 발급한 ID 토큰')
    ai_training_agreed: bool = Field(
        default=False,
        alias='aiTrainingAgreed',
        description=(
            'AI 학습 데이터 활용 동의. 연동합의서 #3(동의 이력)에 해당하지만, '
            'users 테이블에 이 값을 저장할 컬럼이 아직 없어서 지금은 영속화하지 않는다 '
            '(회의에서 컬럼 추가 여부 논의 필요 — backend_decisions.md 참고).'
        ),
    )
    notify_agreed: bool = Field(
        default=True,
        alias='notifyAgreed',
        description='알림 수신 동의 — users.notify_enabled 로 그대로 저장된다.',
    )


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str
    name: str
    role: str
    status: str
    notify_enabled: bool
    face_verified_at: datetime.datetime | None = None


class GoogleLoginResponse(BaseModel):
    user: UserOut
    has_agreed_terms: bool = Field(
        ..., description='로그인 시점 약관 동의 여부 (연동합의서 #3, 확정)',
    )


class AuthMeOut(UserOut):
    """GET /auth/me 응답. 지금은 UserOut과 필드가 같지만, 로그인 응답과
    세션 확인 응답의 용도를 스키마 이름으로 구분해두려고 따로 둔다."""


# ---------------------------------------------------------------------------
# 프로젝트 생성 (사전 정보 입력 폼 — company + item + 하위 정보를 한 번에 적재)
# ---------------------------------------------------------------------------
class TeamMemberIn(BaseModel):
    name: str = Field(..., max_length=100)
    role: str | None = Field(None, max_length=100)
    experience: str | None = None


class PricingItemIn(BaseModel):
    service_name: str = Field(..., max_length=255)
    unit_price: float | None = Field(None, description='단가(원), 미정이면 NULL')


class ProjectCreateRequest(BaseModel):
    """POST /projects 의 본문. 연동합의서 #6(첨부파일 처리) 확정에 따라 실제 요청은
    JSON이 아니라 multipart/form-data 로 오고, 이 스키마는 그 안의 'payload' 폼 필드에
    JSON 문자열로 담겨 온다 — 실제 파일 바이트는 별도의 'files' 폼 필드로 온다
    (app/routers/projects.py 의 create_project 참고). 그래서 여기엔 attachments 필드가 없다 —
    첨부파일 메타데이터(file_name/file_url)는 클라이언트가 보내는 게 아니라, 서버가
    실제로 저장한 뒤 직접 만들어서 ProjectAttachment 로 적재한다."""

    # 회사(예비창업자/기업) 프로필 — 계정에 이미 프로필이 있으면 이 값들은 무시되고 기존 프로필을 재사용한다.
    start_type: str = Field(..., description='시작 유형: 온라인/오프라인/전자상거래 등')
    biz_type: str | None = Field(None, max_length=100)
    ceo_name: str | None = Field(None, max_length=100)
    founded_at: datetime.date | None = None

    # 아이템(지원 아이템) 본문
    description: str = Field(..., min_length=1, description='아이템 설명(사업 아이디어 서술)')
    notify_region: str = Field(..., max_length=32)
    notify_industry: str = Field(..., max_length=32)

    team_members: list[TeamMemberIn] = Field(default_factory=list)
    pricing_items: list[PricingItemIn] = Field(default_factory=list, description='수익모델 단가 — 4-6 정책상 최소 1건 권장')


class TeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    member_id: int
    name: str
    role: str | None = None
    experience: str | None = None


class PricingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pricing_id: int
    service_name: str
    unit_price: float | None = None


class ProjectAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    attachment_id: int
    file_name: str
    file_url: str


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    company_id: int
    description: str
    notify_region: str
    notify_industry: str
    created_at: datetime.datetime


class ProjectDetailOut(ProjectOut):
    team_members: list[TeamMemberOut] = Field(default_factory=list)
    pricing_items: list[PricingItemOut] = Field(default_factory=list)
    attachments: list[ProjectAttachmentOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 산출물 데모 생성 (매칭 → 자격게이트 → 사업계획서 → 산출물 → 최종판정)
# ---------------------------------------------------------------------------
class DemoGenerateRequest(BaseModel):
    notice_id: str | None = Field(
        None, description='매칭시킬 공고 notice_id. 생략하면 모집중(open)인 공고 중 하나를 데모용으로 자동 선택한다.',
    )


class PlanSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tag: str
    title: str
    body: str | None = None


class ArtifactScoreReasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason_text: str


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    artifact_id: int
    category: str
    infographic_path: str
    executable_path: str | None = None
    artifact_score: float | None = None
    score_reasons: list[ArtifactScoreReasonOut] = Field(default_factory=list)


class PlanScoreReasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason_text: str


class BusinessPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    plan_id: int
    doc_score: float | None = None
    threshold: float | None = None
    sections: list[PlanSectionOut] = Field(default_factory=list)
    score_reasons: list[PlanScoreReasonOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)


class VerdictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    overall_passed: bool
    model_version: str
    first_pass_passed: bool


class MatchResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    match_id: int
    notice_id: str
    fit_score: float | None = None
    reason: str | None = None
    status: str


class AgentExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    agent_name: str
    model_used: str
    rerun_type: str
    token_usage: int
    status: str
    started_at: datetime.datetime


class DemoGenerateResponse(BaseModel):
    project_id: int
    match: MatchResultOut
    plan: BusinessPlanOut
    verdict: VerdictOut
    agent_executions: list[AgentExecutionOut]


# ---------------------------------------------------------------------------
# 관리자 - 검증 정책 (admin-dashboard.html 대응)
# ---------------------------------------------------------------------------
class PolicyScoresIn(BaseModel):
    doc_weight: float
    code_weight: float
    plan_weight: float


class PolicyThresholdsIn(BaseModel):
    pass_threshold: float
    rerun_cap: int
    deviation_cap: float


class ChecklistItemIn(BaseModel):
    check_item_id: int
    weight: float
    enabled: bool


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    check_item_id: int
    name: str
    method: str
    category: str
    weight: float
    enabled: bool


class VerificationPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    doc_weight: float
    code_weight: float
    plan_weight: float
    pass_threshold: float
    rerun_cap: int
    deviation_cap: float


# ---------------------------------------------------------------------------
# 관리자 - 사용자 관리
# ---------------------------------------------------------------------------
class UserRoleStatusIn(BaseModel):
    role: str | None = Field(None, description="'user' 또는 'admin'")
    status: str | None = Field(None, description="'active' / 'suspended' / 'dormant'")


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------
class FaqCreateRequest(BaseModel):
    question: str = Field(..., min_length=1)


class FaqAnswerIn(BaseModel):
    answer: str = Field(..., min_length=1)
    is_visible: bool = False


class FaqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    faq_id: int
    question: str
    answer: str | None = None
    is_visible: bool
    created_at: datetime.datetime
    answered_at: datetime.datetime | None = None