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
            'AI 학습 데이터 활용 동의(연동합의서 #3). users.ai_training_agreed 로 저장되며, '
            '로그인 화면에서 동의 체크를 매번 거치는 구조라 로그인할 때마다 최신 값으로 갱신한다.'
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
    ai_training_agreed: bool
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


class ProjectStatusOut(BaseModel):
    """GET /projects/{id}/status 응답 — 이어하기(기획서 v1.7 4-7절 p.20, 8케이스) 화면
    판별 결과. app/pipeline_stages.py의 STAGE_TO_SCREEN/NO_MATCH_SCREEN 매핑을 그대로
    반영하며, 8케이스 전부에 대한 판별 로직은 verify_resume_cases.py로 검증됐다.

    - 이 프로젝트에 매칭(match_results) 자체가 없으면(8케이스의 ①, 아직 공고 선택 전):
      screen=3(NO_MATCH_SCREEN), stage/match_id/match_status는 전부 None.
    - 매칭은 있는데 stage가 NULL이면(마이그레이션 이전 데이터 등, 정상 흐름에서는
      발생하지 않아야 함): screen도 None으로 내려간다 — 프론트는 이 경우 화면을
      확정할 수 없으니 기본 진입점(예: 프로젝트 목록)으로 보내는 게 안전하다.
    - progress_percent는 stage가 '계획서 작성 중'/'프로토타입 제작 중'처럼 한 단계
      안에서도 오래 걸리는 구간일 때만 값이 있고, 그 외 stage에서는 None이다."""

    model_config = ConfigDict(from_attributes=True)
    project_id: int
    screen: int | None = None
    stage: str | None = None
    progress_percent: int | None = None
    match_id: int | None = None
    match_status: str | None = None


class RetryTaskRequest(BaseModel):
    """POST /projects/{id}/retry-task 요청 — 기능정의서 cf. 요구사항("개별 작업 재시도 시
    단순히 동일한 결과를 반환하는 방식이 아닌, 실제 작업을 다시 수행하도록 구현 /
    재시도에 따라 결과물이 실제로 변경되는 것을 확인할 수 있도록 구현") 대응.

    task_key는 app/models.py의 FIXED_TASK_SEQUENCE에 있는 14개 값 중 '조율'(오케스트레이션
    체크포인트 4개 — coordinate_intake/user_decision_doc/user_decision_final/
    coordinate_finalize, 콘텐츠를 만들지 않아 "재시도해도 결과물이 바뀐다"는 개념 자체가
    안 맞는다)만 빼고 나머지 10개를 전부 받는다. 각 값이 실제로 무엇을 다시 만드는지는
    app/agents.py 모듈 docstring의 매핑표 참고:

        'strategy'                                -> plan_sections '3-1'(성장 전략)
        'writing'                                  -> plan_sections '1-1'/'2-1'
        'verify1_rubric' / 'verify1_evidence'      -> plan_score_reasons(+ doc_score)
        'implement_prototype' / 'implement_infographic' -> artifacts 파일 경로
        'verify2_static' / 'verify2_crosscheck'    -> artifact_score_reasons(+ artifact_score)
        'review_expression'                        -> format_findings(T-P1)
        'review_token_check'                       -> proofread_logs(T-P2)
    """

    task_key: str = Field(
        ...,
        description=(
            "'strategy' | 'writing' | 'verify1_rubric' | 'verify1_evidence' | "
            "'implement_prototype' | 'implement_infographic' | 'verify2_static' | "
            "'verify2_crosscheck' | 'review_expression' | 'review_token_check'"
        ),
    )


class RetryTaskResponse(BaseModel):
    project_id: int
    match_id: int
    task_key: str
    agent_name: str
    attempt_no: int
    changed: dict = Field(
        ...,
        description=(
            '재시도 전/후 값 비교. task_key에 따라 모양이 다르다 — 섹션 재작성(strategy/'
            "writing)은 {'sections': {tag: {'before', 'after'}}}, 채점(verify1_*/verify2_*)은 "
            "{'scores': {item_code: {'before', 'after'}}, 'doc_score' 또는 'artifact_score': "
            "{'before', 'after'}}, 산출물 재생성(implement_*)은 {'executable_path' 또는 "
            "'infographic_path': {'before', 'after'}}, 검수(review_expression/"
            "review_token_check)는 {'finding' 또는 'corrected_text': {'before', 'after'}} 형태. "
            '어느 모양이든 호출할 때마다 실제로 값이 달라졌는지(=진짜로 다시 수행했는지) '
            '이 필드로 바로 확인 가능.'
        ),
    )


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
    token_retry_cap: int


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
    token_retry_cap: int


class ItemOut(BaseModel):
    """GET /admin/items(관리자 대시보드 "진행 현황" 탭) 응답 — 프로젝트 1건당 한 행.

    admin-dashboard.html 목업엔 이보다 훨씬 많은 필드(지금 Agent가 뭘 하고 있는지 설명하는
    텍스트, 조율(Supervisor) 진행 상태, 정체(stalled) 판정, 에러 로그 등)가 있지만, 전부
    실제 오케스트레이터(다른 팀원 작업)가 값을 채워줘야 의미가 있는 필드들이다. 기능정의서
    cf. 요구사항("실제 기능이 연동되기 전까지는 예외 처리하여 더미 코드기반으로 진행")을
    여기서는 "그 필드들을 아예 안 내려준다"로 해석했다 — 무작위 더미 텍스트로 채워서 마치
    동작하는 것처럼 보이게 하는 것보다, 프론트가 "이 필드는 아직 없다"를 명확히 알 수 있는
    쪽이 낫다고 판단했다(admin.py도 아직 main.py에 안 붙어 있어 실제로 호출되지도 않는다).
    오케스트레이터 연동 시점에 이 스키마에 필드를 추가하면 된다."""

    model_config = ConfigDict(from_attributes=True)
    project_id: int
    description: str
    user_name: str
    created_at: datetime.datetime
    match_status: str | None = None
    stage: str | None = None


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
