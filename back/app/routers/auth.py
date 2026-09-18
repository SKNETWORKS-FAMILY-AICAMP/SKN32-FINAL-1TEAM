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
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
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
        has_agreed_terms=not is_new_user,
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
    """신규 가입 직후 동의 화면 제출, 또는 나중에 설정 화면에서 선택 동의(학습데이터
    활용/유사 공고 알림)를 바꿀 때 쓴다. 둘 다 선택이라 일부만 보내도 되고(None은 그대로
    둠), 필수 약관(이용약관/개인정보) 자체는 이 테이블에 컬럼이 없어 여기서 다루지 않는다
    — 프론트에서만 가입 진행을 막는 게이트로 쓰인다."""
    if body.ai_training_agreed is not None:
        current_user.ai_training_agreed = body.ai_training_agreed
    if body.notify_agreed is not None:
        current_user.notify_enabled = body.notify_agreed
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)


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
