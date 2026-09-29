"""로그인. 구글 Identity Services가 프론트에서 발급한 id_token을 받아 검증하고,
신규면 users 행을 만들고(최초 로그인 = 회원가입), 기존이면 그대로 우리 세션을 내준다.

세션은 httpOnly 쿠키로 내려준다(backend_decisions.md #1, #3 확정).

[2026-09-15 개정] 예전엔 기존 유저가 재로그인할 때마다 body의 동의값(ai_training_agreed)으로
users.ai_training_agreed를 덮어썼다 — 그런데 프론트의 "이미 동의했으면 동의 화면을 다시 안
보여준다"는 판단이 새로고침하면 날아가는 React state 하나에만 의존하고 있어서, 실제로는
거의 매번 동의 화면이 다시 뜨고, 사용자가 그냥 필수 항목만 다시 체크하고 넘어가면 예전에
켜뒀던 선택 동의(학습데이터/알림)가 기본값으로 조용히 되돌아가는 문제가 있었다.

이제 동의값은 신규 가입 시점에만 반영하고, 기존 유저 로그인에서는 body의 동의값을 아예
무시한다(User row는 안 건드림) — 동의를 나중에 바꾸고 싶으면 PATCH /auth/consent를 명시적으로
호출해야 한다. 프론트가 "동의 화면을 다시 보여줄지"를 판단할 수 있도록, 응답에
has_agreed_terms/is_new_user를 실제 값으로 채워 돌려준다(예전엔 has_agreed_terms가 무조건
True로 고정돼 있어서 프론트가 쓸 수 없는 값이었다)."""
import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AgentExecution,
    Artifact,
    ArtifactScoreReason,
    BusinessPlan,
    Company,
    EligibilityCheck,
    Faq,
    FormatFinding,
    GenerationFailureAlert,
    MatchCandidate,
    MatchScoreReason,
    NoticeAlert,
    Notification,
    PlanCanonicalData,
    PlanScoreReason,
    PlanSection,
    PricingItem,
    Project,
    ProjectAttachment,
    ProjectBudgetItem,
    ProjectPartner,
    ProjectPlanInput,
    ProjectScheduleItem,
    ProofreadLog,
    RefreshToken,
    TeamMember,
    User,
    UserProfile,
    Verdict,
    VerificationScoreHistory,
)
from app.routers.profile import compute_has_profile
from app.schemas import (
    AuthMeOut,
    ConsentUpdateRequest,
    GoogleLoginRequest,
    GoogleLoginResponse,
    UserOut,
)
from app.security import (
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    get_current_user,
    issue_access_token,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    set_refresh_cookie,
    set_session_cookie,
    verify_google_id_token,
)

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/google', response_model=GoogleLoginResponse)
def login_with_google(body: GoogleLoginRequest, response: Response, db: Session = Depends(get_db)):
    payload = verify_google_id_token(body.id_token)
    google_sub = payload['sub']
    email = payload.get('email')
    # [2026-09-18] users.email은 NOT NULL + UNIQUE라 이메일 없이 넘어가면 여기가 아니라
    # DB INSERT 시점에 알 수 없는 500으로 죽는다 — 구글 ID 토큰 표준 클레임상 email은
    # 거의 항상 오지만(Google Identity Services 로그인 버튼은 별도 scope 동의 없이도
    # 기본 프로필 클레임으로 내려준다), 계정 정책상 이메일 없는 구글 계정처럼 드문
    # 경우까지 대비해 여기서 명확한 4xx로 막는다(하정원님 지시 — "이메일을 필수로").
    if not email:
        raise HTTPException(status_code=400, detail='이 구글 계정에서 이메일 정보를 가져올 수 없어 로그인할 수 없습니다')
    name = payload.get('name') or email.split('@')[0]

    user = db.query(User).filter(User.google_sub == google_sub).one_or_none()
    is_new_user = user is None
    if is_new_user:
        # 이메일이 이미 다른 방식으로 등록돼 있으면 막는다(지금은 구글 로그인만 지원)
        if db.query(User).filter(User.email == email).one_or_none() is not None:
            raise HTTPException(status_code=409, detail='이미 다른 방식으로 가입된 이메일입니다')
        user = User(
            google_sub=google_sub,
            email=email,
            name=name,
            role='user',
            status='active',
            notify_enabled=body.notify_agreed,
            ai_training_agreed=body.ai_training_agreed,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if user.status != 'active':
            raise HTTPException(status_code=403, detail='정지되었거나 사용할 수 없는 계정입니다')
        # 기존 유저는 body의 동의값을 더 이상 반영하지 않는다(모듈 docstring 참고) —
        # 이미 저장된 값을 그대로 유지한다. 바꾸려면 PATCH /auth/consent.

    access_token = issue_access_token(user.user_id)
    refresh_token_raw, _ = issue_refresh_token(db, user.user_id)
    db.commit()  # issue_refresh_token은 flush만 하므로 여기서 실제로 저장한다
    set_session_cookie(response, access_token)
    set_refresh_cookie(response, refresh_token_raw)

    user_out = UserOut.model_validate(user)
    user_out.has_profile = compute_has_profile(db, user.user_id)
    return GoogleLoginResponse(
        user=user_out,
        has_agreed_terms=(
            user.terms_agreed_at is not None
            and user.privacy_agreed_at is not None
            and user.age_confirmed_at is not None
        ),
        is_new_user=is_new_user,
    )


@router.get('/me', response_model=AuthMeOut)
def read_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = AuthMeOut.model_validate(current_user)
    out.has_profile = compute_has_profile(db, current_user.user_id)
    return out


@router.post('/refresh')
def refresh_access_token(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    """Access Token(30분)이 만료됐을 때 프론트가 부르는 재발급 엔드포인트 — 프론트는
    다른 API가 401을 돌려주면 이걸 먼저 호출해 새 Access Token을 받은 뒤, 원래 요청을
    한 번 재시도한다(api.js apiFetch 참고). Refresh Token 자체도 호출마다 새로 회전
    (rotate_refresh_token)되므로, 응답에서 새 쿠키 두 개를 모두 다시 심어준다."""
    if refresh_token is None:
        raise HTTPException(status_code=401, detail='로그인이 필요합니다')
    _user, new_access, new_refresh = rotate_refresh_token(db, refresh_token)
    set_session_cookie(response, new_access)
    set_refresh_cookie(response, new_refresh)
    return {'ok': True}


@router.patch('/consent', response_model=UserOut)
def update_consent(
    body: ConsentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """신규 가입 직후 동의 화면 제출, 또는 나중에 설정 화면에서 동의값을 바꿀 때 쓴다.
    전부 선택 필드라 일부만 보내도 된다(None은 그대로 둠).

    [2026-09-27 확장, 2026-09-29 프론트 요청사항 4차 C-1] 필수 동의(이용약관/개인정보/
    만 16세 이상)도 이제 이 엔드포인트로 기록한다 — true면 지금 시각을 저장하고, false면
    철회로 보고 NULL로 되돌린다(공식 기능정의서 v1.9 E-AUTH-CONSENT: "철회 이후 수집을
    중단한다" — 연령 확인은 실제로 철회를 받을 일이 없지만 같은 패턴을 그대로 쓴다).
    새 실행 시작(POST /projects)은 셋 다 값이 있어야 허용된다."""
    if body.ai_training_agreed is not None:
        current_user.ai_training_agreed = body.ai_training_agreed
    if body.notify_agreed is not None:
        current_user.notify_enabled = body.notify_agreed
    if body.terms_agreed is not None:
        current_user.terms_agreed_at = datetime.datetime.utcnow() if body.terms_agreed else None
    if body.privacy_agreed is not None:
        current_user.privacy_agreed_at = datetime.datetime.utcnow() if body.privacy_agreed else None
    if body.age_confirmed is not None:
        current_user.age_confirmed_at = datetime.datetime.utcnow() if body.age_confirmed else None
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)


def _delete_account_cascade(db: Session, user: User) -> None:
    """[2026-09-28 신규] 계정 삭제(탈퇴) — 프로젝트 기획서 v1.10 6-7절: "계정 식별자와
    마이페이지 프로필, 모든 실행 건을 삭제한다. 진행 중인 실행이 있으면 중단한 뒤
    삭제한다." 진행 중인 실행을 별도로 'halted'로 바꾸는 중간 단계는 두지 않는다 —
    이 함수가 끝나면 그 실행의 project 행 자체가 사라지므로, 더미 생성 루프
    (_simulate_generation)가 다음 루프에서 db.get(Project, ...)가 None을 보고
    조용히 멈춘다(app/routers/projects.py 참고) — 실질적으로 "중단 후 삭제"와 같다.

    app_schema.sql(MySQL)에는 이미 이 테이블들 대부분에 ON DELETE CASCADE가 걸려있지만,
    (1) SQLite 테스트 스키마(models.py에서 직접 생성)는 ForeignKey에 ondelete를 안 줘서
    cascade가 전혀 없고, (2) 그래서 MySQL/SQLite 어느 쪽에서 돌든 동일하게 동작하도록
    delete_project()와 같은 방식(자식부터 명시적으로 지우는 순서)을 따른다.

    [2026-09-28, match_results 테이블 통합] project(1):match(1)로 합쳐지면서 match_ids
    조회 단계 자체가 없어졌다 — project_ids가 곧 이전의 match_ids 역할을 겸한다."""
    company_ids = [c.company_id for c in db.query(Company.company_id).filter(Company.user_id == user.user_id)]
    project_ids = [p.project_id for p in db.query(Project.project_id).filter(Project.company_id.in_(company_ids))] if company_ids else []
    plan_ids = [p.plan_id for p in db.query(BusinessPlan.plan_id).filter(BusinessPlan.project_id.in_(project_ids))] if project_ids else []

    if plan_ids:
        artifact_ids = [a.artifact_id for a in db.query(Artifact.artifact_id).filter(Artifact.plan_id.in_(plan_ids))]
        if artifact_ids:
            db.query(ArtifactScoreReason).filter(ArtifactScoreReason.artifact_id.in_(artifact_ids)).delete(synchronize_session=False)
        db.query(Verdict).filter(Verdict.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(Artifact).filter(Artifact.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(ProofreadLog).filter(ProofreadLog.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(FormatFinding).filter(FormatFinding.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(PlanScoreReason).filter(PlanScoreReason.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(PlanCanonicalData).filter(PlanCanonicalData.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(VerificationScoreHistory).filter(VerificationScoreHistory.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(PlanSection).filter(PlanSection.plan_id.in_(plan_ids)).delete(synchronize_session=False)
    if project_ids:
        db.query(BusinessPlan).filter(BusinessPlan.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(GenerationFailureAlert).filter(GenerationFailureAlert.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(MatchScoreReason).filter(MatchScoreReason.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(EligibilityCheck).filter(EligibilityCheck.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(AgentExecution).filter(AgentExecution.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(MatchCandidate).filter(MatchCandidate.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(NoticeAlert).filter(NoticeAlert.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(ProjectAttachment).filter(ProjectAttachment.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(TeamMember).filter(TeamMember.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(PricingItem).filter(PricingItem.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(ProjectBudgetItem).filter(ProjectBudgetItem.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(ProjectScheduleItem).filter(ProjectScheduleItem.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(ProjectPartner).filter(ProjectPartner.project_id.in_(project_ids)).delete(synchronize_session=False)
        db.query(ProjectPlanInput).filter(ProjectPlanInput.project_id.in_(project_ids)).delete(synchronize_session=False)
    if company_ids:
        db.query(Project).filter(Project.company_id.in_(company_ids)).delete(synchronize_session=False)
    db.query(Company).filter(Company.user_id == user.user_id).delete(synchronize_session=False)
    db.query(UserProfile).filter(UserProfile.user_id == user.user_id).delete(synchronize_session=False)
    db.query(RefreshToken).filter(RefreshToken.user_id == user.user_id).delete(synchronize_session=False)
    db.query(Faq).filter(Faq.user_id == user.user_id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()


@router.delete('/me', status_code=204)
def delete_account(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """계정 삭제(탈퇴) — 프로젝트 기획서 v1.10 6-7절. 계정 식별자, 마이페이지 프로필,
    회사 프로필, 프로젝트와 그 아래 매칭·계획서·산출물·검증 이력까지 전부 지운다.
    되돌릴 수 없다 — 프론트는 이 호출 전에 반드시 확인 다이얼로그를 거쳐야 한다.

    refresh_tokens 행 자체가 _delete_account_cascade에서 통째로 삭제되므로
    revoke_refresh_token을 따로 부를 필요가 없다(행이 없으면 재발급도 당연히 안 됨).
    쿠키는 주입받은 response에 직접 지워야 한다 — 새 Response 객체를 만들어 반환하면
    FastAPI가 그 객체를 쓰지 않고 이 쿠키 삭제가 사라진다(logout()과 같은 패턴)."""
    _delete_account_cascade(db, current_user)
    clear_auth_cookies(response)


@router.post('/logout')
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    # Refresh Token을 실제로 DB에서 폐기한다 — 쿠키만 지우면 탈취된 토큰 원문이 만료
    # 전까지(최대 14일) 여전히 유효해, 로그아웃이 이 브라우저에서만 유효할 뿐이었다.
    if refresh_token is not None:
        revoke_refresh_token(db, refresh_token)
    clear_auth_cookies(response)
    return {'ok': True}
