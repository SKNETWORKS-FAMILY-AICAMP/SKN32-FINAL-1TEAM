"""로그인. 구글 Identity Services가 프론트에서 발급한 id_token을 받아 검증하고,
신규면 users 행을 만들고(최초 로그인 = 회원가입), 기존이면 그대로 우리 세션을 내준다.

세션은 httpOnly 쿠키로 내려준다(backend_decisions.md #1, #3 확정)."""
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
    if user is None:
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
        # 로그인 화면에서 동의 체크를 매번 거치는 구조라, 재로그인 시에도 최신 동의
        # 값으로 갱신한다(users.ai_training_agreed — schemas.GoogleLoginRequest 참고).
        if user.ai_training_agreed != body.ai_training_agreed:
            user.ai_training_agreed = body.ai_training_agreed
            db.commit()
            db.refresh(user)

    token = issue_access_token(user.user_id)
    set_session_cookie(response, token)

    has_agreed_terms = True
    return GoogleLoginResponse(user=UserOut.model_validate(user), has_agreed_terms=has_agreed_terms)


@router.get('/me', response_model=AuthMeOut)
def read_me(current_user: User = Depends(get_current_user)):
    return AuthMeOut.model_validate(current_user)


@router.post('/logout')
def logout(response: Response):
    clear_session_cookie(response)
    return {'ok': True}