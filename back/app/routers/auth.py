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
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.status != 'active':
        raise HTTPException(status_code=403, detail='정지되었거나 사용할 수 없는 계정입니다')

    token = issue_access_token(user.user_id)
    set_session_cookie(response, token)

    # NOTE: aiTrainingAgreed는 users 테이블에 저장할 컬럼이 없어서 지금은 영속화하지
    # 않는다(schemas.GoogleLoginRequest 설명 참고). 로그인 화면에서 동의 체크를 거쳐야만
    # 이 엔드포인트가 호출되는 구조라, 여기 도달했다면 이번 로그인에 한해 동의 완료로 본다.
    has_agreed_terms = True
    return GoogleLoginResponse(user=UserOut.model_validate(user), has_agreed_terms=has_agreed_terms)


@router.get('/me', response_model=AuthMeOut)
def read_me(current_user: User = Depends(get_current_user)):
    return AuthMeOut.model_validate(current_user)


@router.post('/logout')
def logout(response: Response):
    clear_session_cookie(response)
    return {'ok': True}