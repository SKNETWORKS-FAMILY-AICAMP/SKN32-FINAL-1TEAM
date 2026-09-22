"""Pydantic v2 요청/응답 스키마. app_schema.sql(설계 문서 기준)과 1:1로 대응한다."""
import datetime
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------
class GoogleLoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id_token: str = Field(..., description='Google Identity Services 가 프론트에서 발급한 ID 토큰')
    # [2026-09-15 개정] 예전엔 로그인할 때마다 이 값으로 users.ai_training_agreed를 덮어썼는데
    # (재로그인 시 프론트가 동의 화면을 다시 안 보여주면 기본값 False/True가 그대로 실려가서
    # 이미 저장해둔 동의를 조용히 지워버리는 부작용이 있었다), 이제 이 두 필드는 "신규 가입
    # 시점"에만 쓰인다 — 기존 유저 로그인에서는 auth.py가 이 값을 아예 무시한다. 기존 유저가
    # 동의값을 바꾸고 싶으면 PATCH /auth/consent를 따로 쓴다(ConsentUpdateRequest).
    ai_training_agreed: bool = Field(
        default=False,
        alias='aiTrainingAgreed',
        description='AI 학습 데이터 활용 동의(연동합의서 #3) — 신규 가입 시에만 반영된다.',
    )
    notify_agreed: bool = Field(
        default=True,
        alias='notifyAgreed',
        description='알림 수신 동의 — 신규 가입 시에만 반영된다(users.notify_enabled).',
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
    # [2026-09-18 추가, 정재희님 인계서] User 테이블 컬럼이 아니라 요청마다 계산해서 채운다
    # (app/routers/profile.py compute_has_profile) — user_profiles 슬롯 중 하나라도 필수
    # 입력 항목(신청자 유형/대표자 정보/지역/주업종/대표자 이력 1건 이상, biz 유형이면
    # 사업자번호까지)을 전부 채웠는지. 기본값 False는 UserOut.model_validate(user)가 User
    # ORM 객체에서 값을 못 찾아도 에러 안 나게 하기 위함 — 호출부가 항상 명시적으로
    # 덮어써야 한다(app/routers/auth.py).
    has_profile: bool = False


class GoogleLoginResponse(BaseModel):
    user: UserOut
    # [2026-09-15 개정] 원래 무조건 True로 고정돼 있던 값이라 프론트가 실질적으로 못 쓰고
    # 있었다 — 이제 "이번 로그인이 기존 계정이라 필수 약관 동의가 이미 저장돼 있는지"를
    # 실제로 계산해서 내려준다(= not is_new_user). 프론트(Login.jsx)는 이 값이 True면
    # 동의 화면을 건너뛰고, False(신규 가입)면 동의 화면을 보여준다.
    has_agreed_terms: bool = Field(
        ..., description='이 계정이 이전에 이미 필수 약관에 동의한 적이 있는지 (신규 가입이면 False)',
    )
    is_new_user: bool = Field(
        ..., description='이번 로그인으로 계정이 방금 새로 만들어졌는지 (has_agreed_terms의 반대값과 동일)',
    )


class AuthMeOut(UserOut):
    """GET /auth/me 응답. 지금은 UserOut과 필드가 같지만, 로그인 응답과
    세션 확인 응답의 용도를 스키마 이름으로 구분해두려고 따로 둔다."""


class ConsentUpdateRequest(BaseModel):
    """[2026-09-15 신규] 로그인 이후(이미 세션이 있는 상태)에 동의값을 바꿀 때 쓴다 —
    신규 가입 직후 동의 화면 제출, 또는 나중에 설정 화면에서 선택 동의를 바꿀 때 둘 다
    이 엔드포인트(PATCH /auth/consent) 하나로 처리한다. 둘 다 선택이라(필수 약관은
    가입 자체를 막는 게 아니라 프론트에서만 체크를 강제하므로 여기 스키마에는 없음)
    일부만 보내도 된다."""
    model_config = ConfigDict(populate_by_name=True)

    ai_training_agreed: bool | None = Field(None, alias='aiTrainingAgreed')
    notify_agreed: bool | None = Field(None, alias='notifyAgreed')


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

    # 회사(예비창업자/기업) 프로필 — [2026-09-15 개정] 예전엔 계정에 이미 프로필이 있으면
    # 이 값들이 무시되고 기존 프로필을 재사용했는데(프로젝트마다 다른 신청자 정보를 못 씀),
    # 이제 POST /projects마다 이 값 그대로 회사 프로필을 새로 만든다(app/routers/projects.py
    # _create_company_for_project 참고).
    #
    # [2026-09-17 삭제] start_type(시작 유형: 온라인/오프라인/전자상거래 등)은 IntakeForm.jsx에
    # 이걸 물어보는 입력칸이 아예 없어서 App.jsx가 항상 '온라인'을 고정값으로 채워 보내고
    # 있었다(하정원님 지적으로 발견). 실제 사용자 입력이 아닌 가짜 값을 계속 저장하느니
    # 필드 자체를 없앴다. [2026-09-18] 그 뒤로 모든 행이 NULL로만 쌓이는 게 확인돼
    # companies.start_type 컬럼 자체도 완전히 지웠다(app_schema.sql/models.py/CompanyOut).
    # 나중에 진짜 입력칸이 생기면 컬럼부터 다시 추가해야 한다.
    # [2026-09-17 배선] IntakeForm.jsx가 필수로 물어보는데 요청 바디에 실려 오지 않고 있던
    # 필드 — 이제 프론트가 보내면 여기서 받는다. 기존 호출자(create_test_project.py 등)가
    # 안 보내도 깨지지 않도록 필수로는 안 만들었다(None이면 그냥 저장 안 함, companies.
    # applicant_type NULL 그대로 — Company 모델 참고).
    applicant_type: str | None = Field(None, description='신청자 유형: preliminary/individual/corp')
    biz_type: str | None = Field(None, max_length=100)
    ceo_name: str | None = Field(None, max_length=100)
    founded_at: datetime.date | None = None
    # [2026-09-17 배선] company_name/business_reg_no/rep_type 컬럼은 있었는데 이 요청
    # 스키마에 받는 필드가 없어서 계획서 다운로드 시 계속 placeholder로 나가고 있었다
    # (멘토링 피드백으로 발견). "마이페이지 프로필 저장/재사용"을 이 테이블에 붙이려던
    # is_saved_profile/biz_reg_lookup_* 컬럼은 결국 user_profiles(v2)로 다르게 구현되면서
    # 2026-09-18에 완전히 삭제했다(app/models.py Company 참고).
    company_name: str | None = Field(None, max_length=255, description='기업명/법인명(상호)')
    business_reg_no: str | None = Field(None, max_length=32, description='사업자등록번호')
    rep_type: str | None = Field(None, max_length=20, description='대표자 유형(단독/공동/각자대표)')

    # 아이템(지원 아이템) 본문
    description: str = Field(..., min_length=1, description='아이템 설명(사업 아이디어 서술)')
    # [2026-09-17 삭제] notify_region/notify_industry("관심 공고 알림" 필터용으로 설계됐던
    # 필드)도 start_type과 같은 이유로 없앴다 — IntakeForm.jsx에 입력칸이 없어서 App.jsx가
    # 항상 '전국'/'기타' 고정값을 채워 보내고 있었다. [2026-09-18] 그 뒤로 모든 행이 NULL로만
    # 쌓이는 게 확인돼 projects.notify_region/notify_industry 컬럼 자체도 완전히 지웠다
    # (app_schema.sql/models.py/ProjectOut) — _build_plan_document_data도 fallback 없이
    # 그냥 고정 플레이스홀더를 쓰도록 같이 정리했다.
    # [2026-09-17 배선] 계획서 공식 양식(별첨1)이 요구하는데 못 받고 있던 나머지 항목.
    output_summary: str | None = Field(None, description='산출물(협약기간 내 목표 — 형태·수량)')
    tech_field: str | None = Field(None, max_length=100, description='전문기술분야')
    regional_priority_area: str | None = Field(None, max_length=100, description='지방우대 지역 해당여부(해당 시 지역명)')

    team_members: list[TeamMemberIn] = Field(default_factory=list)
    pricing_items: list[PricingItemIn] = Field(default_factory=list, description='수익모델 단가 — 4-6 정책상 최소 1건 권장')

    @field_validator('applicant_type')
    @classmethod
    def _check_applicant_type(cls, v: str | None) -> str | None:
        if v in (None, ''):
            return None
        if v not in {'preliminary', 'individual', 'corp'}:
            raise ValueError('applicant_type은 preliminary/individual/corp 중 하나여야 합니다')
        return v


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


class CompanyOut(BaseModel):
    """[2026-09-17 신규] 회사(예비창업자/기업) 프로필 조회용 — 지금까지 company_id만
    노출되고 실제 프로필 내용은 어떤 응답에도 없었다. ProjectDetailOut.company로만 노출한다
    (목록 조회는 그대로 가볍게 유지)."""

    model_config = ConfigDict(from_attributes=True)
    company_id: int
    applicant_type: str | None = None
    biz_type: str | None = None
    ceo_name: str | None = None
    founded_at: datetime.date | None = None
    company_name: str | None = None
    business_reg_no: str | None = None
    rep_type: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    company_id: int
    description: str
    created_at: datetime.datetime
    output_summary: str | None = None
    tech_field: str | None = None
    regional_priority_area: str | None = None


class ProjectDetailOut(ProjectOut):
    team_members: list[TeamMemberOut] = Field(default_factory=list)
    pricing_items: list[PricingItemOut] = Field(default_factory=list)
    attachments: list[ProjectAttachmentOut] = Field(default_factory=list)
    company: CompanyOut | None = None


# ---------------------------------------------------------------------------
# 산출물 데모 생성 (매칭 → 자격게이트 → 사업계획서 → 산출물 → 최종판정)
# ---------------------------------------------------------------------------
# [2026-09-15, 프론트 통합 임시 구현] 실제 오케스트레이터(Agent 파이프라인)가 아직
# 다른 팀원 작업이라(app/agents.py 모듈 docstring 참고) 이 아래 스키마들은
# seed_dummy_pipeline.py의 더미 로직을 POST /projects/{id}/generate 로 감싼 결과를
# 표현하는 용도다 — 오케스트레이터가 실제로 붙으면 이 스키마들은 그대로 두고
# projects.py의 라우터 구현부만 바꾸면 된다(agents.py의 재시도 함수들과 같은 패턴).
class DemoGenerateRequest(BaseModel):
    notice_id: str | None = Field(
        None, description='매칭시킬 공고 notice_id. 생략하면 모집중(open)인 공고 중 하나를 데모용으로 자동 선택한다.',
    )


class MatchCandidateOut(BaseModel):
    """GET /projects/{id}/match-candidates 응답 항목 하나 — 아직 match_results에 저장된
    행이 아니라, notices 테이블에서 후보로 뽑아 화면에 보여주기 위한 임시 값이다(사용자가
    고르면 그때 POST /projects/{id}/generate 로 실제 match_results 행이 생긴다)."""

    notice_id: str
    title: str
    org: str | None = None
    apply_end: datetime.date | None = None
    bonus_score: float  # 가산점(만점 기준 없음, 공고마다 다름)
    reason: str
    url: str | None = None
    batch: int = 1  # 1=첫 매칭, 2=재실행


class MatchCandidatesOut(BaseModel):
    candidates: list[MatchCandidateOut]
    rematch_used: bool


class EligibilityCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    passed: bool
    undecidable: bool
    failed_conditions: list | None = None
    missing_inputs: list | None = None


class PlanSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tag: str
    title: str
    body: str | None = None


class ArtifactScoreReasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason_text: str
    item_code: str | None = None
    score: float | None = None
    max_score: float | None = None


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
    item_code: str | None = None
    score: float | None = None
    max_score: float | None = None


class FormatFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    finding_type: str
    message: str
    severity: str | None = None


class ProofreadLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    original_text: str
    corrected_text: str
    reason: str | None = None


class BusinessPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    plan_id: int
    doc_score: float | None = None
    threshold: float | None = None
    sections: list[PlanSectionOut] = Field(default_factory=list)
    score_reasons: list[PlanScoreReasonOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    format_findings: list[FormatFindingOut] = Field(default_factory=list)
    proofread_logs: list[ProofreadLogOut] = Field(default_factory=list)


class VerdictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    overall_passed: bool
    model_version: str
    first_pass_passed: bool


class MatchScoreReasonOut(BaseModel):
    """[2026-09-17 신규] match_score_reasons 테이블 배선 — 매칭 근거를 정량 점수로 노출
    (plan_score_reasons/artifact_score_reasons와 동일 패턴). 지금은 이 테이블에 아무도 쓰는
    코드가 없어 항상 빈 리스트로 나가지만, 매칭 Agent가 채우기 시작하면 이 필드로 바로
    노출된다(스키마 쪽은 이미 준비됨)."""

    model_config = ConfigDict(from_attributes=True)
    reason_text: str
    item_code: str | None = None
    score: float | None = None
    max_score: float | None = None


class MatchResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    match_id: int
    notice_id: str
    fit_score: float | None = None
    reason: str | None = None
    status: str
    score_reasons: list[MatchScoreReasonOut] = Field(default_factory=list)


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
    eligibility: EligibilityCheckOut
    plan: BusinessPlanOut
    verdict: VerdictOut
    agent_executions: list[AgentExecutionOut]


# ---------------------------------------------------------------------------
# 프로젝트 목록 (대시보드 "내 프로젝트")
# ---------------------------------------------------------------------------
class ProjectListItemOut(BaseModel):
    """GET /projects(목록) 응답 항목 하나 — 프로젝트 1건 + 가장 최근 매칭(있으면) 요약."""

    model_config = ConfigDict(from_attributes=True)
    project_id: int
    description: str
    created_at: datetime.datetime
    notice_id: str | None = None
    notice_title: str | None = None
    match_status: str | None = None
    stage: str | None = None
    progress_percent: int | None = None
    screen: int | None = None


# ---------------------------------------------------------------------------
# 관리자 - 검증 정책 (admin-dashboard.html 대응)
# ---------------------------------------------------------------------------
class PolicyScoresIn(BaseModel):
    doc_weight: float = Field(ge=0, le=100, allow_inf_nan=False)
    code_weight: float = Field(ge=0, le=100, allow_inf_nan=False)
    plan_weight: float = Field(ge=0, le=100, allow_inf_nan=False)


class PolicyThresholdsIn(BaseModel):
    pass_threshold: float = Field(ge=0, le=100, allow_inf_nan=False)
    rerun_cap: int = Field(ge=0)
    deviation_cap: float = Field(ge=0, le=100, allow_inf_nan=False)
    token_retry_cap: int = Field(ge=0)


class ChecklistItemIn(BaseModel):
    check_item_id: int
    weight: float = Field(ge=0, le=100, allow_inf_nan=False)
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

    [2026-09-18 확장] agent_executions/business_plans/artifacts에서 실제로 뽑을 수 있는
    값(현재 단계·시도 횟수·마지막 갱신 시각·점수·정체 여부·보관 여부)은 이제 채워서
    내려준다 — 전부 이미 존재하는 실제 테이블에서 계산한 값이지 지어낸 값이 아니다.

    다만 admin-dashboard.html 목업에 있던 "지금 Agent가 뭘 하고 있는지 설명하는 자연어
    텍스트", "조율(Supervisor) 진행 상태 서술", "에러 로그"는 여전히 안 내려준다 — 이건
    실시간으로 도는 오케스트레이터(다른 팀원 작업)의 내부 상태를 그대로 옮겨야 의미가
    있는 값이라, 지금처럼 오케스트레이터가 없는 상태에서 채우면 전부 지어낸 텍스트가
    된다. 무작위 더미 텍스트로 채워서 마치 동작하는 것처럼 보이게 하는 것보다, 프론트가
    "이 필드는 아직 없다"를 명확히 알 수 있는 쪽이 낫다는 원래 판단은 그대로 유지한다.
    오케스트레이터 연동 시점에 이 스키마에 그 필드들을 추가하면 된다."""

    model_config = ConfigDict(from_attributes=True)
    project_id: int
    description: str
    user_name: str
    created_at: datetime.datetime
    match_status: str | None = None
    stage: str | None = None
    status_label: str = Field(..., description="'공고 매칭 전'/'진행중'/'판단 대기'/'완료'/'중단' 중 하나")
    step: str | None = Field(None, description='마지막으로 실행된 Agent 이름(전략/작성/구현/검증-1/검증-2/검수) — agent_executions 최신 행 기준')
    attempts: int | None = Field(None, description='같은 단계(step)를 몇 번째 시도 중인지 — agent_executions.attempt_no 최신값')
    last_updated: datetime.datetime | None = Field(None, description='agent_executions 최신 실행 시각, 없으면 프로젝트 등록 시각')
    stalled: bool = Field(False, description='완료·보관 상태가 아니면서 마지막 갱신 후 48시간 이상 지났는지')
    score: float | None = Field(None, description='doc_score + artifact_score 합계(둘 다 없으면 None)')
    archived: bool = False


class ItemArchiveIn(BaseModel):
    archived: bool = Field(..., description='True면 보관 처리, False면 복원')


class ScoreHistoryEntryOut(BaseModel):
    scored_at: datetime.datetime
    score: float
    is_rerun: bool


class ItemScoreHistoryOut(BaseModel):
    """GET /admin/items/{project_id}/score-history 응답 — verification_score_history를
    layer(doc/code/plan)별로 묶어 최신순으로 내려준다. 관리자 대시보드 "진행 현황" 탭의
    "이력보기" 모달이 쓴다."""

    doc: list[ScoreHistoryEntryOut] = Field(default_factory=list)
    code: list[ScoreHistoryEntryOut] = Field(default_factory=list)
    plan: list[ScoreHistoryEntryOut] = Field(default_factory=list)


class NoticeAdminOut(BaseModel):
    """GET /admin/notices(관리자 대시보드 "공고 관리" 탭의 "공고 전체 관리" 표) 응답.

    notices 테이블은 이 앱이 아니라 공고 수집 파이프라인(다른 팀원 레포)이 소유한
    읽기 전용 테이블이다(app/models.py Notice 클래스 주석 참고) — 그래서 여기서도
    조회만 하고 수정·삭제 액션은 만들지 않는다. 같은 이유로 "공고 수집 현황"(출처별
    마지막 성공 시각·임베딩 실패 원인)과 "수집 실패 이력"은 우리 쪽 DB에 그 정보(출처별
    헬스체크, 실패 로그)를 남기는 테이블이 아예 없어서 이 스키마에도 넣지 않았다 —
    다른 팀원의 수집 파이프라인 쪽에 로그가 있을 수 있지만 이 앱에서는 접근할 수 없다."""

    model_config = ConfigDict(from_attributes=True)
    notice_id: str
    title: str
    source: str
    apply_start: datetime.date | None = None
    apply_end: datetime.date | None = None
    recruitment_status: str
    has_embedding: bool = Field(..., description='embedding 컬럼이 채워졌는지(매칭에 쓰일 준비가 됐는지)')


class AgentTaskOut(BaseModel):
    """GET /admin/agent-tasks(관리자 대시보드 "에이전트 테스크" 탭의 "Task별 보기") 응답 —
    Agent 1개당 한 행. agent_name/담당 태스크 종류는 app/models.py FIXED_TASK_SEQUENCE
    (코드에 고정된 실제 파이프라인 구조)에서 뽑고, 최근 실행 프로젝트·상태는
    agent_executions에서 그 Agent의 가장 최근 행을 찾아 채운다 — 둘 다 실제 값이고
    지어낸 텍스트는 없다. "배치 기준"(어느 모델을 쓸지) 정책은 이걸 저장하는 테이블이
    아직 없어서(프론트 로컬 상태 전용) 이 응답엔 없다."""

    agent_name: str
    defined_task_count: int = Field(..., description='FIXED_TASK_SEQUENCE 기준 이 Agent가 맡는 서로 다른 task_key 수')
    total_executions: int = Field(0, description='agent_executions에 쌓인 이 Agent의 전체 실행 행 수')
    recent_project_id: int | None = None
    recent_project_description: str | None = None
    recent_status: str | None = None


class AgentOpsSummaryOut(BaseModel):
    """GET /admin/agent-ops-summary(에이전트 테스크 탭의 "운영 지표 요약" 아코디언) 응답 —
    agent_executions/proofread_logs 전체를 집계한 값이다. admin-dashboard.html 목업엔
    "선별 재수행 대비 전체 재실행" 비교도 있었는데, 이 앱엔 그 구분을 남기는 컬럼이
    없어서(rerun_type은 initial/rerun 2값뿐 — RefreshToken이 아니라 AgentExecution.
    rerun_type 컬럼 주석 참고) 만들지 않았다. 대신 실제로 있는 값(최초 실행 대비 재시도
    실행의 평균 토큰 사용량 차이)만 담는다.

    [2026-09-18] token_violation_rate 추가 — OpsSummaryOut의 것과 같은 계산(전체
    proofread_logs 중 passed=False 비율, 전체 프로젝트 평균)이다. "운영 현황" 탭과
    "에이전트 테스크" 탭 양쪽에서 같은 지표를 보여주고 싶어서 두 응답에 각각 넣었다 —
    모델 버전별 비교는 여전히 못 한다(그 시도를 만든 모델 버전을 남기는 컬럼이 없음)."""

    total_executions: int
    initial_executions: int
    rerun_executions: int
    total_tokens: int
    initial_avg_tokens: float | None = None
    rerun_avg_tokens: float | None = None
    token_violation_rate: float | None = None
    token_violation_count: int = 0
    token_check_count: int = 0


class NoticeSourceStatusOut(BaseModel):
    """GET /admin/collection-status(공고 관리 탭 "공고 수집 현황" 카드) 응답의 출처 1개당
    한 행. notices.source의 실제 값(kstartup/bizinfo) 기준이라 목업의 3번째 카드
    "지자체 통합공고"는 없다 — 그런 출처로 수집된 공고가 실제로 없다(NoticeAdminOut 주석
    참고, notices는 다른 팀원의 수집 파이프라인 소유)."""

    source: str
    label: str
    total_count: int
    embedded_count: int
    latest_run_input_count: int | None = Field(None, description='가장 최근 import_runs.report.summary.input_counts[source]')


class ImportRunOut(BaseModel):
    """import_runs(공고 수집 파이프라인이 매 배치마다 남기는 실행 기록) 1건. issue_counts는
    그 배치에서 파싱 등에 실패한 항목 집계(예: {"unparsed_period": 53})이지 "수집 자체
    실패"가 아니다 — 실제 데이터를 보면 이 서비스가 그동안 겪은 "수집 실패"라는 사건
    자체가 없고(매 배치가 accepted_count≈input 그대로 성공), 있는 건 배치 안에서 일부
    항목의 데이터 품질 이슈뿐이다. 그래서 화면 이름도 "수집 실패 이력"이 아니라 "최근
    수집 실행 이력"으로 바꿨다 — 없는 실패를 지어내지 않기 위해서다."""

    run_id: str
    # [2026-09-18 추가] generated_at(수집 파이프라인이 이 배치를 실제로 만든 시각)은 그동안
    # ImportRun에 매핑만 해두고 응답에는 안 내려주고 있었다 — imported_at(우리 쪽에서
    # 적재한 시각)과 다른 정보라(배치 생성→우리 적재까지 걸린 시간을 보여줄 수 있음) 굳이
    # 숨길 이유가 없어 같이 내려준다.
    generated_at: datetime.datetime
    imported_at: datetime.datetime
    accepted_count: int
    input_counts: dict[str, int] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(default_factory=dict)


class CollectionStatusOut(BaseModel):
    sources: list[NoticeSourceStatusOut] = Field(default_factory=list)
    recent_runs: list[ImportRunOut] = Field(default_factory=list)


class ScoreBucketOut(BaseModel):
    label: str
    count: int


class LayerDeviationOut(BaseModel):
    layer: str
    round1_avg: float | None = None
    round2_avg: float | None = None
    delta_avg: float | None = None
    sample_count: int = 0


class OpsSummaryOut(BaseModel):
    """GET /admin/ops-summary(운영 현황 탭) 응답. 전부 business_plans/artifacts/verdicts/
    match_results/agent_executions/verification_score_history/proofread_logs 실제
    집계값이다 — 지금 이 프로젝트들엔 아직 파이프라인이 거의 안 돌아 값 대부분이
    0/None으로 보일 수 있는데, 그건 "연동이 안 된 것"이 아니라 "쌓인 실행이 아직
    적다"는 뜻이다(seed_dummy_pipeline.py 등으로 몇 건 만들어보면 채워진다).

    [2026-09-18] token_violation_rate 추가 — proofread_logs.passed=False(보호 토큰인
    수치·날짜·고유명사·기능명을 AI가 임의로 삭제·변조한 시도) 비율을 전체 프로젝트
    기준으로 평균 낸 값이다. 모델 버전(v1/v2/v3)별로 쪼갠 값은 안 만들었다 — 어느
    검수 모델 버전으로 그 시도가 만들어졌는지 남기는 컬럼이 없어서, 버전별 비교는
    할 수 없고 "전체 평균 위반율" 하나만 낸다."""

    status_counts: dict[str, int] = Field(default_factory=dict)
    doc_avg: float | None = None
    doc_count: int = 0
    total_avg: float | None = None
    total_count: int = 0
    pass_count: int = 0
    pass_rate: float | None = None
    pass_threshold: float
    rerun_matches: int = 0
    matches_with_execution: int = 0
    rerun_rate: float | None = None
    score_buckets: list[ScoreBucketOut] = Field(default_factory=list)
    deviations: list[LayerDeviationOut] = Field(default_factory=list)
    token_violation_rate: float | None = Field(None, description='proofread_logs 전체 시도 중 passed=False 비율(%), 전체 프로젝트 평균')
    token_violation_count: int = 0
    token_check_count: int = 0


class RecoveryItemOut(BaseModel):
    """GET /admin/recovery-items(관리자 대시보드 "검수 회수 문단" 탭) 응답 — proofread_logs
    중 passed=False(보호 토큰 위반으로 반려된 시도) 1건당 한 행. model_version은 그
    시도가 속한 plan의 최종 verdicts.model_version(있으면)을 그대로 붙인 것 — 이
    시도 자체의 모델 버전을 남기는 컬럼은 없어서 근사치다. consent는 그 프로젝트
    소유자의 "지금 시점" AI 학습 데이터 활용 동의 여부(users.ai_training_agreed)다."""

    log_id: int
    project_id: int | None = None
    project_description: str | None = None
    model_version: str | None = None
    violation_type: str | None = None
    occurred_at: datetime.datetime
    consent: bool
    original: str
    attempt: str
    recovery_status: str
    label: str | None = None


class RecoveryLabelIn(BaseModel):
    recovery_status: str = Field(..., description="'pending' / 'labeled' / 'excluded'")
    label: str | None = Field(None, description="recovery_status='labeled'일 때 사람이 정리한 정답 문장")

    @field_validator('recovery_status')
    @classmethod
    def _check_recovery_status(cls, v: str) -> str:
        if v not in ('pending', 'labeled', 'excluded'):
            raise ValueError("recovery_status는 pending/labeled/excluded 중 하나여야 합니다")
        return v


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


# ---------------------------------------------------------------------------
# 마이페이지 - 사업자등록번호 상태 확인 (국세청 API 중계)
# ---------------------------------------------------------------------------
class BizCheckRequest(BaseModel):
    b_no: str = Field(..., description='사업자등록번호 (하이픈 있어도 됨)')
    # [2026-09-18 v2] 마이페이지가 계정당 여러 슬롯을 가질 수 있게 되면서, 조회 결과를
    # user_profiles 어느 행에 붙일지 클라이언트가 알려줘야 한다 — 프론트가 아직 이 조회를
    # 특정 슬롯에 연결해 보내도록 배선되기 전(front/src/features/mypage/BizNoField.jsx)에는
    # None으로 와도 되고, 그 경우 app/routers/biz_check.py는 조회 결과만 반환하고 어느
    # 프로필에도 저장하지 않는다(어느 슬롯 것인지 알 수 없으니 함부로 아무 슬롯에나 붙이면
    # 안 됨).
    profile_id: int | None = Field(None, description='결과를 저장할 마이페이지 정보 슬롯 ID')


class BizCheckOut(BaseModel):
    valid: bool
    b_stt_cd: str | None = Field(None, description="01=계속사업자 02=휴업자 03=폐업자")
    label: str | None = None
    tax_type: str | None = None
    tax_type_cd: str | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# 마이페이지 - 프로필 저장/조회 (SB-59 v2 — 슬롯형, 계정당 최대 3개)
# ---------------------------------------------------------------------------
# 요청·응답 모양을 프론트 스토어(front/src/store/useMyPageStore.js)의 profile 객체와
# 똑같이 맞춰서 프론트에서 변환 코드가 필요 없게 한다 — 그래서 필드명은 camelCase alias를
# 쓴다. capability는 화면 전용이라 판정용으로 뽑아 쓰는 값이 없으므로 굳이 하위 필드를 전부
# 모델링하지 않고 dict로 받아 원본 그대로 저장한다 — 프론트가 목록 항목을 늘려도(예: hires)
# 여기 스키마를 매번 고칠 필요가 없다.
MAX_PROFILES = 3
_ALLOWED_APPLICANT_TYPES = {'', 'preliminary', 'individual', 'corp'}
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _validate_optional_date_str(value: str) -> str:
    """미입력(빈 문자열)은 그대로 허용. 값이 있으면 YYYY-MM-DD 형식 + 실제로 존재하는
    날짜인지 확인한다."""
    if value == '':
        return value
    if not _DATE_RE.match(value):
        raise ValueError('날짜는 YYYY-MM-DD 형식이어야 합니다')
    try:
        datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('존재하지 않는 날짜입니다') from exc
    return value


class ProfileRegionIn(BaseModel):
    sido: str = ''
    sigungu: str = ''


class BasicProfileIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')

    applicant_type: str = Field('', alias='applicantType', description='preliminary/individual/corp, 미선택 시 빈 문자열')
    ceo_name: str = Field('', alias='ceoName')
    birth_date: str = Field('', alias='birthDate')
    gender: str = ''
    region: ProfileRegionIn = Field(default_factory=ProfileRegionIn)
    industry: str = ''
    certs: list[str] = Field(default_factory=list)
    # 예비창업자 전용
    budget_scale: str = Field('', alias='budgetScale')
    # 개인사업자·법인 전용
    biz_no: str = Field('', alias='bizNo', description='하이픈 포함 원본 그대로(예: 132-05-57431)')
    opened_at: str = Field('', alias='openedAt')
    self_funding: bool = Field(False, alias='selfFunding')
    self_funding_min: str = Field('', alias='selfFundingMin')
    self_funding_max: str = Field('', alias='selfFundingMax')

    @field_validator('applicant_type')
    @classmethod
    def _check_applicant_type(cls, v: str) -> str:
        if v not in _ALLOWED_APPLICANT_TYPES:
            raise ValueError('applicantType은 preliminary/individual/corp 중 하나여야 합니다')
        return v

    @field_validator('birth_date', 'opened_at')
    @classmethod
    def _check_dates(cls, v: str) -> str:
        return _validate_optional_date_str(v)

    @field_validator('budget_scale')
    @classmethod
    def _check_budget_scale(cls, v: str) -> str:
        """[2026-09-18, 정재희님 인계서] 만원 단위 숫자 문자열, 0~2000 — 프론트가 입력
        자체를 2000에서 자르지만(clampBudget, BasicInfo.jsx) 서버도 한 번 더 막는다."""
        if v == '':
            return v
        if not v.isdigit():
            raise ValueError('budgetScale은 숫자 문자열이어야 합니다')
        if int(v) > 2000:
            raise ValueError('budgetScale은 2000(만원)을 넘을 수 없습니다')
        return v


class ProfileSaveRequest(BaseModel):
    """POST /profile, PUT /profile/{profile_id} 공통 바디. bizStatus가 섞여 와도(pydantic
    기본 extra='ignore') 조용히 버려진다 — 클라이언트가 국세청 조회 결과를 조작해서 보낼 수
    없게 하기 위함이라 일부러 이 스키마에 bizStatus 필드를 두지 않았다. name을 생략하면
    새 슬롯 생성 시 '정보 N', 기존 슬롯 수정 시 이름은 그대로 둔다."""
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    basic: BasicProfileIn
    capability: dict = Field(default_factory=dict)


class ProfileOut(BaseModel):
    """GET(목록)/POST/PUT 공통 응답 모양 — 슬롯 하나. basic/capability는 저장된 JSON
    원본을 그대로 내려준다(프론트 스토어 profiles 배열 항목 그대로 넣을 수 있게). bizStatus는
    저장한 적 없거나 bizNo가 바뀌어 조회 결과가 비워진 상태면 null."""
    profile_id: int
    name: str
    basic: dict
    capability: dict
    biz_status: dict | None = Field(None, alias='bizStatus')

    model_config = ConfigDict(populate_by_name=True)


# 새 슬롯 기본값 — 프론트 스토어(useMyPageStore.js)의 emptyProfile()과 정확히 같은 모양
# (빈 문자열/빈 배열/false)으로 내려줘서 프론트가 별도 분기 없이 바로 빈 폼으로 렌더링할 수
# 있게 한다. dict는 참조 공유를 피하려고 쓰는 쪽에서 매번 깊은 복사해서 쓴다
# (app/routers/profile.py 참고).
PROFILE_DEFAULT_BASIC: dict = {
    'applicantType': '', 'ceoName': '', 'birthDate': '', 'gender': '',
    'region': {'sido': '', 'sigungu': ''}, 'industry': '', 'certs': [],
    'budgetScale': '',
    'bizNo': '', 'openedAt': '',
    'selfFunding': False, 'selfFundingMin': '', 'selfFundingMax': '',
}
PROFILE_DEFAULT_CAPABILITY: dict = {
    'careers': [], 'skills': '', 'soloFounder': False, 'team': [], 'hires': [], 'equipment': [], 'partners': [],
}
