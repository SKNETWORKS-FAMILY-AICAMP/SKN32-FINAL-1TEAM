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
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    AuthMeOut,
    ConsentUpdateRequest,
    GoogleLoginRequest,
    GoogleLoginResponse,
    UserOut,
)
from app.security import (
    clear_session_cookie,
    get_current_user,
    issue_access_token,
    set_session_cookie,
    verify_google_id_token,
)

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/google', response_model=GoogleLoginResponse)
def login_with_google(body: GoogleLoginRequest, response: Response, db: Session = Depends(get_db)):
    payload = verify_google_id_token(body.id_token)
    google_sub = payload['sub']
    email = payload.get('email')
    name = payload.get('name') or (email.split('@')[0] if email else '사용자')

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

    token = issue_access_token(user.user_id)
    set_session_cookie(response, token)

    return GoogleLoginResponse(
        user=UserOut.model_validate(user),
        has_agreed_terms=not is_new_user,
        is_new_user=is_new_user,
    )


@router.get('/me', response_model=AuthMeOut)
def read_me(current_user: User = Depends(get_current_user)):
    return AuthMeOut.model_validate(current_user)


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
def logout(response: Response):
    clear_session_cookie(response)
    return {'ok': True}
