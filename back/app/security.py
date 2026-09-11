"""Google OAuth 검증 + 세션용 JWT 발급/검증.

기술스택 선정서 3-2: "프론트 SDK로 토큰 발급, FastAPI에서 google-auth로 검증".
프론트(Google Identity Services)가 보내주는 id_token 을 여기서 검증하고,
검증 통과 시 우리 서비스 자체 JWT(세션 토큰)를 발급한다.

세션 저장 방식은 httpOnly 쿠키로 확정했다(backend_decisions.md #1) — 프론트가
Authorization 헤더를 실어 보낼 필요 없이, 브라우저가 쿠키를 자동으로 실어 보낸다.
대신 프론트는 fetch/axios 요청에 `credentials: 'include'` 를 반드시 넣어야 한다.
"""
import datetime
import os
import sys

import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

# TODO: 실제 배포 전 .env 에 GOOGLE_CLIENT_ID / JWT_SECRET 을 채운다.
# config.py 의 require() 를 그대로 쓰면 값이 없을 때 팀 컨벤션대로 친절한 안내와 함께 종료된다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
import config as pipeline_config  # noqa: E402 -- repo 루트를 sys.path 에 넣은 뒤라야 import 가능

JWT_ALG = 'HS256'
JWT_EXPIRE_HOURS = 24 * 7  # 이어하기(기획서 4-7) 고려해 넉넉하게

SESSION_COOKIE_NAME = 'sbrain_session'


def verify_google_id_token(id_token_str: str) -> dict:
    """구글 ID 토큰을 검증하고 payload(sub, email, name 등)를 반환한다.
    서명·발급자·만료·audience(GOOGLE_CLIENT_ID)까지 google-auth 라이브러리가 확인한다."""
    client_id = pipeline_config.require('GOOGLE_CLIENT_ID')
    try:
        payload = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), client_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f'구글 토큰 검증 실패: {exc}') from exc
    return payload


def issue_access_token(user_id: int) -> str:
    secret = pipeline_config.require('JWT_SECRET')
    now = datetime.datetime.utcnow()
    payload = {
        'sub': str(user_id),
        'iat': now,
        'exp': now + datetime.timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALG)


def set_session_cookie(response: Response, token: str) -> None:
    """세션 JWT를 httpOnly 쿠키로 내려준다 (backend_decisions.md #1, 확정).

    주의(회의에서 공유 필요): 지금 합의(#4)대로면 백엔드는 http://localhost:8000,
    프론트는 http://127.0.0.1:5174 인데, 브라우저 SameSite 판정 기준으로
    `localhost` 와 `127.0.0.1` 은 서로 다른 site 라서 SameSite=Lax 쿠키가
    전달되지 않을 수 있다. 로컬 개발에서는 프론트도 `http://localhost:5174` 로
    띄우는 걸 권장한다 — 그러면 SameSite=Lax + secure=False(http) 로도 문제없이
    쿠키가 오간다. 굳이 127.0.0.1을 써야 하면 samesite='none' + secure=True 로
    바꿔야 하는데, 그러면 로컬에서도 https가 필요해져 번거로워진다.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,  # TODO: 배포(https) 시 True로 변경
        samesite='lax',
        max_age=JWT_EXPIRE_HOURS * 3600,
        path='/',
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path='/')


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    if session_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='로그인이 필요합니다')
    secret = pipeline_config.require('JWT_SECRET')
    try:
        payload = jwt.decode(session_token, secret, algorithms=[JWT_ALG])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='세션이 유효하지 않습니다') from exc

    user = db.get(User, int(payload['sub']))
    if user is None or user.status != 'active':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='계정을 사용할 수 없습니다')
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='관리자만 접근할 수 있습니다')
    return user