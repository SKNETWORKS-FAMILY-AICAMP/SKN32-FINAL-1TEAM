"""로그인. 구글 Identity Services가 프론트에서 발급한 id_token을 받아 검증하고,
신규면 users 행을 만들고(최초 로그인 = 회원가입), 기존이면 그대로 우리 세션을 내준다.

세션은 httpOnly 쿠키로 내려준다(backend_decisions.md #1, #3 확정).

[2026-09-15 변경] 원래는 "재로그인 때도 매번 동의 체크를 거쳐 최신 값으로 갱신"하는
구조였는데, 이미 있는 계정은 동의 화면 자체를 다시 안 보여주기로 바뀌었다(사용자
피드백) — 프론트가 최초 호출은 화면 노출 없이 기본값으로 바로 보내고, has_agreed_terms
(=계정이 이미 있었는지)를 보고서야 신규 계정에 한해 동의 화면을 띄운다. 그래서 이제
동의값(ai_training_agreed/notify_enabled)은 "최초 가입 시"에만 반영하고, 이미 있는
계정은 이 호출의 body 값이 실제 선택인지 프론트 기본값인지 알 수 없으니 건드리지 않는다."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import AuthMeOut, GoogleLoginRequest, GoogleLoginResponse, UserOut
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
    is_new = user is None
    if is_new:
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
        # 이미 있는 계정 — 동의값은 최초 가입 때만 반영하고 여기서는 건드리지 않는다
        # (모듈 docstring의 2026-09-15 변경 참고).

    token = issue_access_token(user.user_id)
    set_session_cookie(response, token)

    # has_agreed_terms=False면(=방금 막 만들어진 신규 계정) 프론트가 이제서야 동의
    # 화면을 띄우고 실제 선택값으로 이 엔드포인트를 한 번 더 호출한다.
    return GoogleLoginResponse(user=UserOut.model_validate(user), has_agreed_terms=not is_new)


@router.get('/me', response_model=AuthMeOut)
def read_me(current_user: User = Depends(get_current_user)):
    return AuthMeOut.model_validate(current_user)


@router.post('/logout')
def logout(response: Response):
    clear_session_cookie(response)
    return {'ok': True}