"""Pydantic v2 요청/응답 스키마. app_schema.sql(설계 문서 기준)과 1:1로 대응한다."""
import datetime
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import pipeline_stages as ps


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
    # [2026-09-27 신규] 필수 동의 완료 시각 — NULL이면 아직 동의 전. 설정 화면에서
    # 동의 상태를 보여주거나, 나중에 재동의를 유도할 때 쓴다.
    terms_agreed_at: datetime.datetime | None = None
    privacy_agreed_at: datetime.datetime | None = None
    # [2026-09-29 신규, 프론트 요청사항 4차 C-1] "만 16세 이상입니다" 동의 완료 시각 —
    # 위 둘과 같은 용도(NULL이면 아직 동의 전).
    age_confirmed_at: datetime.datetime | None = None
    # [2026-09-18 추가, 프론트 담당자 인계서] User 테이블 컬럼이 아니라 요청마다 계산해서 채운다
    # (app/routers/profile.py compute_has_profile) — user_profiles 슬롯 중 하나라도 필수
    # 입력 항목(신청자 유형/대표자 정보/지역/주업종/대표자 이력 1건 이상, biz 유형이면
    # 사업자번호까지)을 전부 채웠는지. 기본값 False는 UserOut.model_validate(user)가 User
    # ORM 객체에서 값을 못 찾아도 에러 안 나게 하기 위함 — 호출부가 항상 명시적으로
    # 덮어써야 한다(app/routers/auth.py).
    has_profile: bool = False


class GoogleLoginResponse(BaseModel):
    user: UserOut
    # [2026-09-15 개정, 2026-09-27 재개정] 원래 무조건 True로 고정돼 있던 값이라 프론트가
    # 실질적으로 못 쓰고 있었다 — 한 번은 "신규 가입 여부"(not is_new_user)로 계산하도록
    # 고쳤었는데, 이러면 계정만 생기고 필수 동의 화면을 실제로 완료하기 전에 이탈한
    # 사용자가 재로그인할 때 (더 이상 신규가 아니므로) 동의 화면을 건너뛰는 문제가 있었다.
    # 이제 users.terms_agreed_at/privacy_agreed_at(PATCH /auth/consent가 채움)이 실제로
    # 둘 다 채워졌는지로 계산한다 — 진짜로 필수 동의를 마쳤는지를 본다. 프론트(Login.jsx)는
    # 이 값이 True면 동의 화면을 건너뛰고, False면 보여준다.
    has_agreed_terms: bool = Field(
        ..., description='이 계정이 필수 동의(이용약관·개인정보)를 실제로 완료했는지',
    )
    is_new_user: bool = Field(
        ..., description='이번 로그인으로 계정이 방금 새로 만들어졌는지 (has_agreed_terms의 반대값과 동일)',
    )


class AuthMeOut(UserOut):
    """GET /auth/me 응답. 지금은 UserOut과 필드가 같지만, 로그인 응답과
    세션 확인 응답의 용도를 스키마 이름으로 구분해두려고 따로 둔다."""


class ConsentUpdateRequest(BaseModel):
    """[2026-09-15 신규, 2026-09-27 확장] 로그인 이후(이미 세션이 있는 상태)에 동의값을
    바꿀 때 쓴다 — 신규 가입 직후 동의 화면 제출, 또는 나중에 설정 화면에서 선택 동의를
    바꿀 때 둘 다 이 엔드포인트(PATCH /auth/consent) 하나로 처리한다. 전부 선택 필드라
    일부만 보내도 된다(None은 그대로 둠).

    [2026-09-27] 필수 약관(이용약관/개인정보) 필드를 추가했다 — 예전엔 "가입 자체를
    막는 게 아니라 프론트에서만 체크를 강제"했는데, 서버가 동의 여부를 전혀 모르는
    상태였다(공식 기능정의서 v1.9 E-AUTH-CONSENT 대비 갭). true를 보내면 그 시각을
    저장하고(users.terms_agreed_at/privacy_agreed_at), false를 보내면 철회로 보고
    NULL로 되돌린다. 둘 다 채워지기 전까지는 POST /projects(새 실행 시작)가
    차단된다(routers/projects.py create_project 참고)."""
    model_config = ConfigDict(populate_by_name=True)

    ai_training_agreed: bool | None = Field(None, alias='aiTrainingAgreed')
    notify_agreed: bool | None = Field(None, alias='notifyAgreed')
    terms_agreed: bool | None = Field(None, alias='termsAgreed', description='이용약관 동의(필수)')
    privacy_agreed: bool | None = Field(None, alias='privacyAgreed', description='개인정보 수집·이용 동의(필수)')
    # [2026-09-29 신규, 프론트 요청사항 4차 C-1] "만 16세 이상입니다" 필수 동의 — 팀 확정
    # 2026-09-29. terms_agreed/privacy_agreed와 같은 방식으로 처리한다(true=지금 시각
    # 저장, false=철회로 보고 NULL). 실제로는 철회를 받을 일이 없는 필수 항목이지만,
    # 같은 패턴을 그대로 쓰는 게 더 단순하다.
    age_confirmed: bool | None = Field(None, alias='ageConfirmed', description='만 16세 이상입니다(필수)')


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


# [2026-09-22 신규, 담당자] IntakeForm.jsx "사업 계획" 섹션의 목록 항목들 — App.jsx
# intakeDetailPayload가 이미 이 키 이름 그대로(snake_case) 보내고 있다. 항목 모양이 아직
# 팀 논의 중이라(채용예정인력·협업회사 필수입력 전환 제안) 여기서도 필드를 꽉 채우지 않고
# 전부 선택으로 둔다 — project_plan_inputs에 JSON 그대로 저장(app/models.py 참고).
class PlanCareerIn(BaseModel):
    type: str | None = None
    title: str | None = None
    period: str | None = None
    has_proof: bool = False


class PlanHireIn(BaseModel):
    job: str | None = None
    headcount: str | None = None
    required_skill: str | None = None
    hire_month: str | None = Field(None, description='YYYY-MM')


class PlanEquipmentIn(BaseModel):
    name: str | None = None
    status: str | None = None


class PlanPartnerIn(BaseModel):
    """계획서 별첨용 ProjectPartner(partner_name/capability/collaboration_plan/
    collaboration_timing)와는 다른, 사전 정보 입력 화면의 단순 협력 기관 항목이다."""
    name: str | None = None
    status: str | None = None


_MONTH_RE = re.compile(r'^\d{4}-\d{2}$')

# [2026-09-29 신규, 프론트 요청사항 4차 C-2] 대표자 생년월일이 실제로 받는 최소 나이 —
# 프론트도 같은 값으로 입력 연도를 제한하지만(derive.js MIN_CEO_AGE, 우회 가능) 서버에서도
# 같은 기준으로 막는다. 대표자 정보를 받는 곳(ProjectCreateRequest.ceo_birth_date,
# BasicProfileIn.birth_date)이 이 상수를 공유한다. config.py(레포 루트)는 .env 비밀값
# 로더 전용이라(그 파일 자체 docstring 참고) 여기 둔다 — ATTACH_MAX_FILES/MB와 같은 이유.
MIN_CEO_AGE = 16


def _check_min_age(birth_date: datetime.date) -> None:
    """만 나이가 MIN_CEO_AGE 이상인지 확인한다(생일이 아직 안 지났으면 -1)."""
    today = datetime.date.today()
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    if age < MIN_CEO_AGE:
        raise ValueError('대표자는 만 16세 이상만 입력할 수 있어요')


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
    # 있었다(리뷰 중 발견). 실제 사용자 입력이 아닌 가짜 값을 계속 저장하느니
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

    # [2026-09-22 배선] IntakeForm.jsx가 2026-09-18 프론트 커밋(병합 시점 담당자
    # 인수인계 불가로 확인)에서 새로 받기 시작한 "사업 계획" 입력. App.jsx intakeDetailPayload가
    # 이미 이 이름 그대로(snake_case) 보내고 있었는데 여기 대응 필드가 없어 pydantic 기본
    # extra='ignore'로 조용히 버려지고 있었다(App.jsx 자체 주석 "서버 ProjectCreateRequest에
    # 아직 필드가 없어 지금은 서버가 무시" 참고). project_plan_inputs 테이블(project당 1행)에
    # 그대로 저장한다(app/routers/projects.py create_project, app/models.py ProjectPlanInput).
    # [2026-09-22 신규] 계획서 공식 양식이 요구하는데 대응 입력칸이 없어 계속 '○○○'
    # 플레이스홀더로만 나가고 있던 항목(예비창업자 전용, 사업자등록 전이라 직장 대신
    # 직업 구분만 받음). "아이템 범주"는 여기 안 넣는다 — Agent가 짓는 항목(models.py
    # ProjectPlanInput.occupation 주석 참고).
    occupation: str | None = Field(None, max_length=100, description='예비창업자 직업(직장명 기재 불가)')

    ceo_birth_date: datetime.date | None = None
    ceo_gender: str | None = Field(None, max_length=10)
    region_sido: str | None = Field(None, max_length=20)
    region_sigungu: str | None = Field(None, max_length=50)
    main_industry: str | None = Field(None, max_length=100)
    certifications: list[str] = Field(default_factory=list)
    ceo_careers: list[PlanCareerIn] = Field(default_factory=list)
    ceo_capability: str | None = None

    dev_start_month: str | None = Field(None, description='개발 시작월 YYYY-MM')
    dev_end_month: str | None = Field(None, description='개발 종료월 YYYY-MM')

    # 예비창업자 전용 — 마이페이지 budget_scale과 같은 상한(derive.js PRELIMINARY_BUDGET_CAP_MANWON).
    budget_scale_manwon: int | None = Field(None, ge=0, le=2000)

    # 개인사업자 · 법인 전용
    self_funding_allowed: bool | None = None
    self_cash_limit: int | None = Field(None, ge=0)
    self_in_kind_resources: str | None = None

    no_hires: bool = False
    hires: list[PlanHireIn] = Field(default_factory=list)
    no_equipment: bool = False
    equipment: list[PlanEquipmentIn] = Field(default_factory=list)
    no_partners: bool = False
    partners: list[PlanPartnerIn] = Field(default_factory=list)

    @field_validator('applicant_type')
    @classmethod
    def _check_applicant_type(cls, v: str | None) -> str | None:
        if v in (None, ''):
            return None
        if v not in {'preliminary', 'individual', 'corp'}:
            raise ValueError('applicant_type은 preliminary/individual/corp 중 하나여야 합니다')
        return v

    @field_validator('dev_start_month', 'dev_end_month')
    @classmethod
    def _check_month(cls, v: str | None) -> str | None:
        if v in (None, ''):
            return None
        if not _MONTH_RE.match(v):
            raise ValueError('YYYY-MM 형식이어야 합니다')
        return v

    @field_validator('ceo_birth_date')
    @classmethod
    def _check_ceo_birth_date_age(cls, v: datetime.date | None) -> datetime.date | None:
        if v is not None:
            _check_min_age(v)
        return v

    @model_validator(mode='after')
    def _check_main_industry_of_business(self) -> 'ProjectCreateRequest':
        """개인사업자 · 법인의 주업종은 드롭다운 9종(pipeline_stages.MAIN_INDUSTRIES)만 저장된다(DB ENUM). 다른 값이 오면 저장하다
        DB 오류(500)가 나므로 입력 단계에서 422로 막는다. 빈 값은 '없음'으로 본다. 예비창업자의 주업종은 자유 텍스트라 그대로 둔다."""
        if self.applicant_type in ('individual', 'corp'):
            if self.main_industry in ('', None):
                self.main_industry = None
            elif self.main_industry not in ps.MAIN_INDUSTRIES:
                raise ValueError(f"개인사업자 · 법인의 주업종은 다음 중 하나여야 합니다: {', '.join(ps.MAIN_INDUSTRIES)}")
        return self


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


class ProjectPlanInputOut(BaseModel):
    """[2026-09-22 신규] app/models.py ProjectPlanInput 조회용. hires/equipment/partners/
    ceo_careers/certifications는 저장된 JSON을 그대로 내려준다(ProfileOut.basic/capability와
    같은 이유 — 프론트 항목 모양 그대로, 변환 코드 불필요)."""
    model_config = ConfigDict(from_attributes=True)

    ceo_birth_date: datetime.date | None = None
    ceo_gender: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    main_industry: str | None = None
    main_industry_free: str | None = None
    certifications: list = Field(default_factory=list)
    ceo_careers: list = Field(default_factory=list)
    ceo_capability: str | None = None
    occupation: str | None = None
    dev_start_month: str | None = None
    dev_end_month: str | None = None
    budget_scale_manwon: int | None = None
    self_funding_allowed: bool | None = None
    self_cash_limit: int | None = None
    self_in_kind_resources: str | None = None
    no_hires: bool = False
    hires: list = Field(default_factory=list)
    no_equipment: bool = False
    equipment: list = Field(default_factory=list)
    no_partners: bool = False
    partners: list = Field(default_factory=list)


class ProjectDetailOut(ProjectOut):
    team_members: list[TeamMemberOut] = Field(default_factory=list)
    pricing_items: list[PricingItemOut] = Field(default_factory=list)
    attachments: list[ProjectAttachmentOut] = Field(default_factory=list)
    company: CompanyOut | None = None
    plan_input: ProjectPlanInputOut | None = None


# ---------------------------------------------------------------------------
# 산출물 데모 생성 (매칭 → 자격게이트 → 사업계획서 → 산출물 → 최종판정)
# ---------------------------------------------------------------------------
# [SB-243~245] 이 아래 스키마들은 오케스트레이터 결과(app/orch/mapping.py가 만든다)를 화면에 내려주는 응답 모양이다.
# 처음 더미 파이프라인(seed_dummy_pipeline.py · app/agents.py, 없어짐)에 맞춰 만든 모양을 프론트가 그대로 쓰고 있어서
# 이름(Demo*)은 그대로 둔다.
class DemoGenerateRequest(BaseModel):
    # [SB-243] 이제 필수다(후보 중 사용자가 고른 공고) — 생략하면 라우터가 422로 답한다. 임시 데모 자동 선택은 없어졌다.
    notice_id: str | None = Field(None, description='사용자가 고른 공고 notice_id(공고 후보에 있는 값).')


class ProceedRequest(BaseModel):
    """review/start(종합 평가 → 표현 검수) 요청 — 기준 점수에 못 미친 채 진행한다는 사용자의 확인."""
    confirmed: bool = False


class BonusItemOut(BaseModel):
    name: str
    points: float


class MatchCandidateOut(BaseModel):
    """GET /projects/{id}/match-candidates 응답 항목 하나 — 오케스트레이터가 공고팀 순위로 뽑은 후보 한 건(화면 3).
    사용자가 고르면 POST /projects/{id}/generate 로 공고가 확정된다."""

    notice_id: str
    title: str
    org: str | None = None
    apply_end: datetime.date | None = None
    # 가산점(만점 기준 없음, 공고마다 다름). None = 계산 못 함("가산점 정보 없음"), 0 = 해당 가점 없음.
    bonus_score: float | None = None
    reason: str
    url: str | None = None
    batch: int = 1  # 1=첫 매칭, 2=재실행
    # [SB-242] 오케스트레이터(공고 서버 추천) 카드에서 새로 오는 값 — 모두 선택이라 없어도 된다.
    rank: int | None = None
    fit_score: float | None = None  # 0이면 마감 임박순 대체 경로라 적합도를 숨긴다
    content_changed: bool = False  # 추가 조회에서 다시 나온 공고의 내용이 바뀜
    apply_period_type: str | None = None
    bonus_items: list[BonusItemOut] = Field(default_factory=list)
    source_notice: str | None = None  # 카드마다 출처 고지


class OrchNoticeOut(BaseModel):
    """오케스트레이터 안내(시트 6 오류코드 문구) — 화면에 함께 보여준다."""

    code: str
    message: str


class MatchCandidatesOut(BaseModel):
    candidates: list[MatchCandidateOut]
    rematch_used: bool
    # [SB-242] 공고 매칭은 워커가 비동기로 돌려 응답이 늦을 수 있다. 'ready' 말고는 candidates가 비어 있고
    # 프론트가 다시 부른다(pending) 또는 안내만 보여준다(failed · no_match).
    status: str = 'ready'  # 'ready' | 'pending' | 'failed' | 'no_match'
    code: str | None = None
    message: str | None = None
    notices: list[OrchNoticeOut] = Field(default_factory=list)
    blocked_notice_ids: list[str] = Field(default_factory=list)  # 자격 불통과로 고를 수 없는 공고 ID


class EligibilityCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    passed: bool
    undecidable: bool
    failed_conditions: list | None = None
    missing_inputs: list | None = None
    # [SB-243] 읽지 못해 통과로 본 조건('지원대상 유형' · '업력') — 진행을 막지 않고 화면 4에 '확인 필요'로 안내한다.
    unknown_conditions: list = Field(default_factory=list)
    # [SB-274] 화면 4(자격 확인)의 업력 표시와 작성 시작 버튼. 오케스트레이터 화면 4 값 그대로다.
    # 업력은 년 단위 소수 한 자리이고 예비창업자 · 업력을 모르면 None이다.
    business_age_years: float | None = None
    # 자격 확인을 통과해 작성 단계로 들어갈 수 있는 상태면 True(불통과면 False). 잠정 주의: 지금 오케스트레이터는 확인 필요 조건
    # (unknown_conditions)이 있어도 통과로 보고 True를 주는데, 기능정의서 v1.9 E-G1-UNPARSED("임의 통과를 허용하지 않는다")와 다르다 —
    # 기능정의서 개정 여부를 누리님께 확인 중이라 결정에 따라 뜻이 바뀔 수 있다.
    can_start_writing: bool = False


class PlanSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tag: str
    title: str
    body: str | None = None


class ArtifactScoreReasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason_text: str
    item_code: str | None = None
    display_name: str | None = None
    score: float | None = None
    max_score: float | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    artifact_id: int | None = None  # [SB-243] 산출물은 오케스트레이터가 갖고 있어 행 번호가 없다
    category: str
    infographic_path: str
    executable_path: str | None = None
    artifact_score: float | None = None
    score_reasons: list[ArtifactScoreReasonOut] = Field(default_factory=list)


class PlanScoreReasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason_text: str
    item_code: str | None = None
    display_name: str | None = None
    score: float | None = None
    max_score: float | None = None


class FormatFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    finding_type: str
    message: str
    severity: str | None = None
    sentence_id: str | None = None  # [SB-243]


class ProofreadLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    original_text: str
    corrected_text: str
    reason: str | None = None
    # [2026-09-28 신규, 프론트 2차 요청 A-3] 모델(app/models.py ProofreadLog)엔 이미 있는데
    # 응답에서 빠져 있었다 — 이게 있어야 "1차 반려 → 2차 통과" 같은 시도별 과정을 화면에
    # 그릴 수 있다(위반이면 passed=False + violation_type/note, attempt_no로 회차 구분).
    attempt_no: int
    passed: bool
    violation_type: str | None = None
    violation_note: str | None = None
    # [SB-243] 같은 문장의 시도를 묶는 키(프론트 reviewParagraphsFrom이 section_id로 묶는다) ← sentenceId
    section_id: str | None = None


class BusinessPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    plan_id: int | None = None  # [SB-243] 계획서는 오케스트레이터가 갖고 있어 행 번호가 없다
    doc_score: float | None = None
    threshold: float | None = None
    sections: list[PlanSectionOut] = Field(default_factory=list)
    score_reasons: list[PlanScoreReasonOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    format_findings: list[FormatFindingOut] = Field(default_factory=list)
    proofread_logs: list[ProofreadLogOut] = Field(default_factory=list)
    # [SB-243] 오케스트레이터 계획서의 차트 · 표 · 기능 목록(구조는 작성 Agent · 프론트와 맞추는 중이라 원본 그대로 싣는다)
    feature_list: list[str] = Field(default_factory=list)
    charts: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)


class VerdictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    overall_passed: bool
    model_version: str | None = None  # [SB-243] 오케스트레이터는 주지 않는다
    first_pass_passed: bool | None = None  # [SB-243] 오케스트레이터는 주지 않는다

    # [2026-09-22 신규, 프론트 전달사항 10번] 검증결과서(front/src/features/workflow/
    # verificationReport.js)의 "종합 판정" 행 — 문서층/자동검증/계획서대조 세 층 점수와
    # 총점·판정기준. 항목별 세부(01/02/03)는 이미 BusinessPlanOut.score_reasons(사업계획서
    # 평가)와 ArtifactOut.score_reasons(자동검증은 item_code 'CHECK-', 계획서대조는
    # 'FEATURE-' 접두어로 구분)에 있어서, 여기선 그 세 층을 합산한 요약만 담는다.
    # Verdict 테이블 자체엔 없는 값이라(verification_policies에서 가져옴) model_validate가
    # 아니라 라우터(_build_demo_response)가 직접 계산해서 채운다.
    doc_score: float | None = None
    doc_max_score: float | None = None
    code_score: float | None = None
    code_max_score: float | None = None
    plan_match_score: float | None = None
    plan_match_max_score: float | None = None
    # [SB-301] 계획서 대조 판정이 보류됐으면 True — 이때 plan_match_score는 0점으로 합산되어 오므로(총점에도 0점이 들어 있다)
    # 화면은 0점이 아니라 "대조 불가"로 보여 준다. 보류 사유 코드는 사용자에게 내지 않는다(관리자 기록).
    plan_match_withheld: bool = False
    total_score: float | None = None
    pass_threshold: float | None = None


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
    """[2026-09-28, match_results 테이블 통합] 예전엔 match_results 테이블(자체 PK인
    match_id)에서 이 값들을 읽었으나, 그 테이블이 projects로 합쳐지면서 이제 이 필드들은
    Project 모델에 직접 있다 — 별도 식별자가 필요 없으니 match_id는 뺐다(부모 응답의
    project_id로 충분)."""

    model_config = ConfigDict(from_attributes=True)
    notice_id: str | None = None
    fit_score: float | None = None
    reason: str | None = None
    status: str | None = None
    score_reasons: list[MatchScoreReasonOut] = Field(default_factory=list)


class ProjectStatusOut(BaseModel):
    """GET /projects/{id}/status 응답 — 이어하기(기획서 v1.7 4-7절 p.20, 8케이스) 화면
    판별 결과. app/pipeline_stages.py의 STAGE_TO_SCREEN/NO_MATCH_SCREEN 매핑을 그대로
    반영하며, 8케이스 전부에 대한 판별 로직은 tests/verify_resume_cases.py로 검증됐다.

    - 이 프로젝트에 아직 매칭(notice_id/stage)이 없으면(8케이스의 ①, 아직 공고 선택 전):
      screen=3(NO_MATCH_SCREEN), stage/match_status는 전부 None.
    - stage가 NULL이면(마이그레이션 이전 데이터 등, 정상 흐름에서는 발생하지 않아야 함):
      screen도 None으로 내려간다 — 프론트는 이 경우 화면을 확정할 수 없으니 기본
      진입점(예: 프로젝트 목록)으로 보내는 게 안전하다.
    - progress_percent는 stage가 '계획서 작성 중'/'프로토타입 제작 중'처럼 한 단계
      안에서도 오래 걸리는 구간일 때만 값이 있고, 그 외 stage에서는 None이다.

    [2026-09-28, match_results 테이블 통합] match_id 필드는 뺐다 — project_id가 곧
    이 실행 단위의 유일한 식별자다."""

    model_config = ConfigDict(from_attributes=True)
    project_id: int
    screen: int | None = None
    stage: str | None = None
    progress_percent: int | None = None
    match_status: str | None = None
    # [SB-247] 사용자 응답에서는 항상 None이다 — 실패 사유 원문은 사용자에게 보이지 않고 관리자 API에만 나간다(기존 화면 호환용 필드).
    # 실패는 match_status='failed'로 안다(확정된 실패 — 새 프로젝트로 다시 시작, 기능정의서 E-RUN-FAIL).
    failure_reason: str | None = None
    # [2026-09-23 신규, 2026-09-27 개명] 자동 재개 소진 횟수(상한은 설정값)와 다음 자동 재개
    # 예정 시각 — match_status='waiting_resume'일 때만 next_retry_at에 값이 있다.
    # 화면에 "N번째 재개 중" 또는 "다음 재개까지 남은 시간" 같은 걸 보여주고 싶으면
    # 쓰면 된다. [2026-09-27] 필드명을 retry_count -> resume_count로 바로잡았다 —
    # 이 값은 스펙의 Run.resumeCount(재개 횟수)이지 Run.retryCount(호출 재시도 횟수)가
    # 아니다.
    resume_count: int = 0
    next_retry_at: datetime.datetime | None = None
    # [2026-09-27 신규, SB-139] 공식 기능정의서 v1.9 E-RUN-CLOSED: "이어하기로 돌아왔을
    # 때 선택 공고 마감" — 마감 사실만 알리고 계속 진행할지는 사용자가 정한다(실행을
    # 막지 않는다). 매칭 자체가 없거나(screen=NO_MATCH_SCREEN) 공고 정보를 못 찾으면
    # False.
    notice_closed: bool = False
    # [SB-272] 재작성 진행 — 기획서 4-7 · 5-8: 재작성 중에는 요청한 화면에서 '진행 중'으로 보이고 이어하기로 돌아와도 그 화면으로 온다.
    # 재작성 중에도 stage는 재작성 전 단계 그대로이고 match_status는 in_progress이므로, 이 두 값으로 "그 화면에서 재작성 중"을
    # 가려 버튼을 막고 '진행 중'을 보여 준다(오케스트레이터 RunView 값 그대로, 실행 건이 없으면 None · False).
    rework_screen: int | None = Field(None, description='재작성 중인 화면(6 · 8 · 9). 재작성 중이 아니면 None')
    collecting: bool = Field(False, description='재작성 요청을 모으는 중(잠정 2초)이면 True — 모으는 중에도 재작성 중으로 본다')


class RetryTaskRequest(BaseModel):
    """POST /projects/{id}/retry-task 요청 — 기능정의서 cf. 요구사항("개별 작업 재시도 시
    단순히 동일한 결과를 반환하는 방식이 아닌, 실제 작업을 다시 수행하도록 구현 /
    재시도에 따라 결과물이 실제로 변경되는 것을 확인할 수 있도록 구현") 대응.

    task_key는 웹이 쓰는 작업 이름이다 — 사용자가 재작성할 수 있는 건 writing · implement_prototype · implement_infographic뿐이고(app/orch/mapping.py
    orch_bundle_of), 나머지는 400이다. 아래는 예전 14개 값 중 '조율'(오케스트레이션
    체크포인트 4개 — coordinate_intake/user_decision_doc/user_decision_final/
    coordinate_finalize, 콘텐츠를 만들지 않아 "재시도해도 결과물이 바뀐다"는 개념 자체가
    안 맞는다)만 빼고 나머지 10개를 전부 받는다. 각 값이 실제로 무엇을 다시 만드는지는
    app/agents.py 모듈 docstring의 매핑표 참고:

        'strategy'                                -> plan_canonical_data(F01~F15 분석 결과)
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
    # [2026-09-28 신규, 프론트 답변 반영] task_key='writing'은 화면상 묶음 3개(사업계획서
    # 본문 작성/그래프 생성/표 생성)를 공유하므로 어느 묶음인지 필수로 받는다
    # (app/pipeline_stages.py WRITING_BUNDLES). 그 외 task_key는 이미 묶음과 1:1이라
    # 생략 가능 — 값을 보내면 그 task_key의 고정 묶음과 일치하는지만 검증한다.
    bundle_id: str | None = Field(
        default=None,
        description="writing 재시도는 필수: '사업계획서 본문 작성' | '그래프 생성' | '표 생성'. 그 외엔 생략 가능.",
    )


class ReworkAcceptedOut(BaseModel):
    """POST /projects/{id}/retry-task 응답 — [SB-243~244] 재작성은 이제 접수만 하고 바로 돌아온다. 결과(전후 비교)는
    진행 상태(GET /status의 rework_screen · collecting · match_status)를 보다가 끝나면 GET /rework-result로 읽는다
    ([SB-272] 두 필드는 GET /status · GET /projects에 있다)."""
    project_id: int
    task_key: str
    bundle_id: str  # 웹 묶음 이름(문제인식 · 실현가능성 · 성장전략 · 팀 구성 · 실행 파일 제작 · 인포그래픽 제작)
    cycle_id: str  # 같은 화면에서 모으는 시간 안에 들어온 요청은 같은 cycle_id로 합쳐진다
    screen: int
    bundles: list[str]  # 지금까지 모인 묶음(웹 이름, 요청 순서)
    collect_until: datetime.datetime
    duplicate: bool = False  # 이미 모은 묶음이라 한 번으로 쳤다(기회를 더 쓰지 않음)


class ReworkFileChangeOut(BaseModel):
    artifact: str  # 'prototype' | 'infographic'
    before_path: str | None = None
    after_path: str | None = None


class ReworkResultOut(BaseModel):
    """GET /projects/{id}/rework-result 응답 — 마지막 재작성 한 건. 재작성한 적이 없으면 404.

    status: '진행중' | '완료' | '실패'. 진행 중이면 공통 필드만 있다. `changed`는 예전 retry-task 응답과 같은 모양
    (sections · executable_path · infographic_path · version_kept · version_comparison)으로 풀어 둔 값이라 화면이 그대로 쓸 수 있다."""
    project_id: int
    cycle_id: str
    screen: int
    bundles: list[str]
    status: str
    started_at: datetime.datetime
    ended_at: datetime.datetime | None = None
    kept: str | None = None  # '전' | '후'
    basis: str | None = None  # document | artifact | total
    before_score: float | None = None
    after_score: float | None = None
    before_refs: list[str] = Field(default_factory=list)
    after_refs: list[str] = Field(default_factory=list)
    plan_before: list[PlanSectionOut] | None = None
    plan_after: list[PlanSectionOut] | None = None
    files: list[ReworkFileChangeOut] = Field(default_factory=list)
    rolled_back: bool = False
    refunded_bundles: list[str] = Field(default_factory=list)
    notice_code: str | None = None
    changed: dict = Field(default_factory=dict)


class BundleUsageOut(BaseModel):
    """프론트 답변 반영 — 화면에 보이는 "묶음(bundle)" 단위 재작성(rework) 사용/잔여 횟수.
    task_key가 아니라 bundle_id로 센다(writing 하나가 묶음 3개를 가리키므로 — 자세한 배경은
    app/pipeline_stages.py WRITING_BUNDLES 참고). 재작성 실패는 세지 않는다(retry_task가
    rerun_type='rerun' AND status='completed'인 행만 used로 센다)."""
    bundle_id: str
    layer: str  # 'document' | 'artifact'
    used: int
    remaining: int


class DemoGenerateResponse(BaseModel):
    """POST /generate(공고 선택 → 자격 확인)와 GET /result(지금까지 결과)가 함께 쓴다.

    [SB-243] 공고를 고른 직후엔 계획서 · 점수가 아직 없어 plan 이하가 비고(plan=None), 자격 확인 결과를 기다리는 중이면
    status='pending', 공고 서버 오류로 자격 확인을 못 했으면 status='failed'(+ message · notices)로 답한다.
    예전의 agent_executions 필드는 없어졌다(관리자 조회가 대신한다)."""
    project_id: int
    status: str = 'ready'  # 'ready' | 'pending' | 'failed'
    code: str | None = None
    message: str | None = None
    notices: list[OrchNoticeOut] = Field(default_factory=list)
    match: MatchResultOut | None = None
    eligibility: EligibilityCheckOut | None = None
    plan: BusinessPlanOut | None = None
    # [2026-09-22 수정, 프론트 전달사항 3번] "GET /result는 프로토타입이 아직 만들어지는
    # 중이어도 완성된 계획서는 돌려줘야 한다" — verdict는 산출물(artifact) 채점까지 끝나야
    # 나오는 값이라, 계획서만 끝나고 프로토타입/검증이 아직인 상태에선 없을 수 있다.
    # 예전엔 verdict가 없으면(=artifact가 없으면) 통째로 404를 냈는데, 생성이 단계별로 끝나는
    # 흐름에선 이 틈이 그대로 404가 되므로 verdict 없이도 계획서를 돌려준다.
    verdict: VerdictOut | None = None
    # [2026-09-28 신규] 프론트 요청 2 — RERUN_CAP 프론트 상수를 없애고 관리자가 상한을
    # 바꾸면 화면도 같이 따라가도록, 상한값과 묶음별 사용/잔여 횟수를 같이 내려준다.
    # [2026-09-28 수정] task_key 단위였던 retry_budget을 bundle_id 단위 bundle_usages로
    # 교체 — writing 하나가 화면상 묶음 3개를 가리키는 문제 때문(app/pipeline_stages.py
    # WRITING_BUNDLES 참고). strategy/verify1_*/verify2_*/review_* 처럼 화면에 "재작성"
    # 버튼이 없는 task_key는 애초에 묶음 개념이 아니라서 이 목록에 안 나온다.
    rework_cap: int = 0
    bundle_usages: list[BundleUsageOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 프로젝트 목록 (대시보드 "내 프로젝트")
# ---------------------------------------------------------------------------
class ProjectListItemOut(BaseModel):
    """GET /projects(목록) 응답 항목 하나 — 프로젝트 1건 + 가장 최근 매칭(있으면) 요약.

    [2026-09-23 개정] 화면 헤더 종모양 알림(NotificationBell, front/src/features/workflow/
    shared.jsx)이 이 목록 엔드포인트를 이미 폴링하고 있어서, 별도 알림 엔드포인트 대신
    여기에 display_status/resume_count/next_retry_at/failure_reason을 추가했다."""

    model_config = ConfigDict(from_attributes=True)
    project_id: int
    description: str
    created_at: datetime.datetime
    notice_id: str | None = None
    notice_title: str | None = None
    match_status: str | None = None
    # 서비스 내부 상태(실행/재개대기/사용자대기/실패/완료/중단, match_status)를 화면 문구로
    # 분류한 값 — app/pipeline_stages.py status_to_display 참고. 매칭 자체가 없으면 None.
    display_status: str | None = Field(None, description="'진행'/'확인이 필요합니다'/'문제가 생겨 멈췄다'/'완료'/'중단됨' 중 하나, 매칭 없으면 None")
    stage: str | None = None
    progress_percent: int | None = None
    screen: int | None = None
    # [2026-09-27 개명] retry_count -> resume_count (ProjectStatusOut과 같은 이유).
    resume_count: int = 0
    next_retry_at: datetime.datetime | None = None
    failure_reason: str | None = None  # ProjectStatusOut과 같다 — 사용자 응답에서는 항상 None
    # [SB-272] ProjectStatusOut과 같은 값(재작성 중인 화면 · 요청 모으는 중)
    rework_screen: int | None = None
    collecting: bool = False


# ---------------------------------------------------------------------------
# 사용자 알림 (화면 헤더 종모양 — SB-141)
# ---------------------------------------------------------------------------
class NotificationOut(BaseModel):
    """GET /projects/notifications 응답 항목 하나 — 공식 기능정의서 v1.9 Notification
    타입. GET /projects의 display_status(진행/완료/실패 3분류 요약)와는 별개로, "그동안
    무슨 일이 있었는지"의 개별 이력을 담는다."""

    model_config = ConfigDict(from_attributes=True)
    notification_id: int
    project_id: int
    kind: str = Field(..., description="'문서평가'/'산출물확인'/'표현검수'/'실패' 중 하나")
    failure_scope: str | None = Field(None, description="kind='실패'일 때만: '실행' 또는 '재작성'")
    target_step: int | None = Field(None, description='알림을 누르면 들어갈 화면 번호. kind=실패면 None(이어하기 목록으로 연결)')
    created_at: datetime.datetime
    read_at: datetime.datetime | None = None


class NotificationReadIn(BaseModel):
    read: bool = Field(..., description='true면 읽음 처리, false면 다시 안읽음으로 되돌림')


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
    rework_cap: int = Field(ge=0)
    deviation_cap: float = Field(ge=0, le=100, allow_inf_nan=False)
    token_retry_cap: int = Field(ge=0)


class ChecklistItemIn(BaseModel):
    check_item_id: int
    weight: float = Field(ge=0, le=100, allow_inf_nan=False)
    enabled: bool


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    check_item_id: int
    # [2026-09-22 신규, 프론트 전달사항 10번] item_code는 artifact_score_reasons.item_code와
    # 매칭되는 값, item_no는 카테고리(웹/원페이지) 안에서의 순번(1~8, 1번=진입 파일 존재
    # 여부 — 미충족 시 해당 카테고리 자동 검증 점수 전체 0점 규칙 적용 대상). category의
    # 뜻도 '정적분석/실행검증'에서 '산출물 카테고리(html/svg)'로 바뀌었다(models.py 참고).
    item_code: str
    item_no: int
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
    rework_cap: int
    deviation_cap: float
    token_retry_cap: int


class ItemOut(BaseModel):
    """GET /admin/items(관리자 대시보드 "진행 현황" 탭) 응답 — 프로젝트 1건당 한 행.

    [SB-245] 값(현재 단계·시도 횟수·마지막 갱신 시각·점수·정체 여부·보관 여부)은 오케스트레이터 조회(관리자 실행 건 · 실행 기록)에서
    읽는다. 웹 projects 행은 실행 건이 없는 공고 매칭 전 프로젝트와 보관 여부에만 쓴다.

    admin-dashboard.html 목업에 있던 "지금 Agent가 뭘 하고 있는지 설명하는 자연어 텍스트", "조율(Supervisor) 진행 상태
    서술", "에러 로그"는 여전히 내려주지 않는다 — 지어낸 텍스트로 채우는 것보다 프론트가 "이 필드는 없다"를 명확히 알 수 있는 쪽이
    낫다는 원래 판단은 그대로다. 오케스트레이터 조회 결과에서 만들 수 있는 값이 생기면 이 스키마에 추가한다."""

    model_config = ConfigDict(from_attributes=True)
    project_id: int
    description: str
    user_name: str
    created_at: datetime.datetime
    match_status: str | None = None
    failure_reason: str | None = None
    stage: str | None = None
    status_label: str = Field(..., description="'공고 매칭 전'/'진행중'/'판단 대기'/'완료'/'중단'/'실패' 중 하나")
    step: str | None = Field(None, description='마지막으로 실행된 Agent 이름(전략/작성/구현/검증-1/검증-2/검수) — 오케스트레이터 실행 기록 최신 행 기준')
    attempts: int | None = Field(None, description='같은 단계(step)를 몇 번째 시도 중인지 — 오케스트레이터 실행 기록 최신값')
    last_updated: datetime.datetime | None = Field(None, description='오케스트레이터 실행 건의 마지막 갱신 시각, 없으면 프로젝트 등록 시각')
    stalled: bool = Field(False, description='완료·보관 상태가 아니면서 마지막 갱신 후 48시간 이상 지났는지')
    score: float | None = Field(None, description='현재 버전의 문서 점수 + 산출물 점수 합계(둘 다 없으면 None)')
    archived: bool = False
    # [2026-09-23 신규, 2026-09-27 개명] 생성 작업(계획서/프로토타입) 자동 재개 소진
    # 횟수(0~5)와 마지막 실패 사유 — match_status가 'waiting_resume'/'failed'일 때만
    # 의미가 있다.
    generation_resume_count: int = 0
    generation_failure_reason: str | None = None
    # [2026-09-27 신규, SB-134] 마지막 실패 원인 분류('일시'/'입력'/'운영') — 입력·운영이면
    # 영구 오류로 재개 없이 바로 실패 확정된 것. NULL이면 실패 이력이 없거나 초기화됨.
    generation_last_error_kind: str | None = None


class ItemArchiveIn(BaseModel):
    archived: bool = Field(..., description='True면 보관 처리, False면 복원')


class GenerationFailureAlertOut(BaseModel):
    """GET /admin/generation-alerts 응답 — 생성 작업이 status='failed'로 확정될 때마다(재개 상한
    소진 또는 입력·운영 같은 영구 오류로 즉시 확정) 오케스트레이터 워커가 한 행씩 쌓는 관리자 알림
    (generation_failure_alerts)."""

    model_config = ConfigDict(from_attributes=True)
    alert_id: int
    project_id: int
    stage: str
    resume_count: int
    last_error_kind: str = Field(..., description="'일시'/'입력'/'운영' 중 하나 — 실패 확정 시점의 원인 분류")
    failure_reason: str | None = None
    created_at: datetime.datetime
    acknowledged_at: datetime.datetime | None = None


class GenerationFailureAlertAckIn(BaseModel):
    acknowledged: bool = Field(..., description='True면 확인 처리, False면 확인 취소')


class ScoreHistoryEntryOut(BaseModel):
    scored_at: datetime.datetime | None = None  # 채점 끝 시각을 모르면 None
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
    total_tokens: int  # 글 토큰만(이미지 토큰은 total_image_tokens)
    total_image_tokens: int = 0  # [SB-302] 이미지 입력 + 출력 토큰 합. 이미지 호출이 없으면 0
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
    """GET /admin/ops-summary(운영 현황 탭) 응답. [SB-245] 오케스트레이터 admin_summary(최근 12개월 범위)
    집계값이다 — 쌓인 실행이 적으면 값 대부분이 0/None으로 보일 수 있는데, 그건 "연동이 안 된 것"이
    아니라 "쌓인 실행이 아직 적다"는 뜻이다.

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
    시도를 기록한 행의 model_version이다. consent는 그 프로젝트
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


class RecoveryTrainedIn(BaseModel):
    """POST /admin/recovery-items/trained 요청 — 학습 데이터로 내보낸 검수 회수 문단의 log_id 목록."""
    log_ids: list[int] = Field(..., min_length=1, max_length=1000)


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
    status: str | None = Field(
        None, description="'active' / 'suspended' / 'dormant' (조회에는 탈퇴 중인 계정의 'withdrawing'도 나온다 — 관리자가 정하는 값은 앞의 셋)")


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

    @field_validator('birth_date')
    @classmethod
    def _check_birth_date_age(cls, v: str) -> str:
        if v:
            _check_min_age(datetime.date.fromisoformat(v))
        return v

    @field_validator('budget_scale')
    @classmethod
    def _check_budget_scale(cls, v: str) -> str:
        """[2026-09-18, 프론트 담당자 인계서] 만원 단위 숫자 문자열, 0~2000 — 프론트가 입력
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
