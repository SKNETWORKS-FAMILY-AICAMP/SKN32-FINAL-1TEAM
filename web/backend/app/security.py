"""Google OAuth 검증 + 세션용 JWT 발급/검증.

기술스택 선정서 3-2: "프론트 SDK로 토큰 발급, FastAPI에서 google-auth로 검증".
프론트(Google Identity Services)가 보내주는 id_token 을 여기서 검증하고,
검증 통과 시 우리 서비스 자체 JWT(세션 토큰)를 발급한다.

세션 저장 방식은 httpOnly 쿠키로 확정했다(backend_decisions.md #1) — 프론트가
Authorization 헤더를 실어 보낼 필요 없이, 브라우저가 쿠키를 자동으로 실어 보낸다.
대신 프론트는 fetch/axios 요청에 `credentials: 'include'` 를 반드시 넣어야 한다.
"""
import datetime
import hashlib
import os
import secrets
import sys

import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RefreshToken, User

# TODO: 실제 배포 전 .env 에 GOOGLE_CLIENT_ID / JWT_SECRET 을 채운다.
# config.py 의 require() 를 그대로 쓰면 값이 없을 때 팀 컨벤션대로 친절한 안내와 함께 종료된다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
import config as pipeline_config  # noqa: E402 -- repo 루트를 sys.path 에 넣은 뒤라야 import 가능

JWT_ALG = 'HS256'

# [2026-09-18 개정] Access/Refresh 이원화. 예전엔 세션 JWT 하나를 7일짜리로 발급해서
# 로그아웃해도 쿠키만 지워질 뿐 토큰 자체는 만료 전까지 계속 유효했다(탈취되면 로그아웃이
# 무의미) — 이제 Access Token은 짧게 만료시켜 탈취 피해 창을 줄이고, 이어하기(기획서 4-7)에
# 필요한 "오래 로그인 유지"는 DB에 저장돼 실제로 폐기 가능한 Refresh Token이 담당한다.
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 14

SESSION_COOKIE_NAME = 'sbrain_session'  # Access Token 쿠키 — 기존 이름 유지(verify_*.py/tests 참고)
REFRESH_COOKIE_NAME = 'sbrain_refresh'


def verify_google_id_token(id_token_str: str) -> dict:
    """구글 ID 토큰을 검증하고 payload(sub, email, name 등)를 반환한다.
    서명·발급자·만료·audience(GOOGLE_CLIENT_ID)까지 google-auth 라이브러리가 확인한다."""
    client_id = pipeline_config.require('GOOGLE_CLIENT_ID')
    try:
        payload = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), client_id, clock_skew_in_seconds=10
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
        'exp': now + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALG)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def issue_refresh_token(db: Session, user_id: int) -> tuple[str, RefreshToken]:
    """새 Refresh Token을 발급한다. 원문(raw)은 이번 응답 쿠키에만 실리고, DB에는 해시만
    저장한다(DB 유출 시에도 토큰 재구성 불가) — commit은 호출한 쪽이 원하는 시점에 한다."""
    raw = secrets.token_urlsafe(32)
    now = datetime.datetime.utcnow()
    row = RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        issued_at=now,
        expires_at=now + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(row)
    db.flush()  # row.token_id 확보 (rotate_refresh_token의 rotated_to_id에 필요)
    return raw, row


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[User, str, str]:
    """Refresh Token으로 새 Access+Refresh 쌍을 발급한다(POST /auth/refresh). 기존 토큰은
    즉시 revoke하고 회전(rotation)한다 — 탈취된 토큰이 재사용돼도 그 다음 재발급부터는
    막힌다. 반환값: (user, 새 access token, 새 refresh token 원문)."""
    old = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_token(raw_token)).one_or_none()
    if old is None or old.revoked_at is not None or old.expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='세션이 만료되었습니다. 다시 로그인해 주세요.')

    user = db.get(User, old.user_id)
    if user is None or user.status != 'active':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='계정을 사용할 수 없습니다')

    new_raw, new_row = issue_refresh_token(db, user.user_id)
    old.revoked_at = datetime.datetime.utcnow()
    old.rotated_to_id = new_row.token_id
    db.commit()
    return user, issue_access_token(user.user_id), new_raw


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """로그아웃 — 이 토큰으로는 더 이상 재발급(POST /auth/refresh)할 수 없게 만든다."""
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_token(raw_token)).one_or_none()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.datetime.utcnow()
        db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    """Access Token(JWT)을 httpOnly 쿠키로 내려준다 (backend_decisions.md #1, 확정).

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
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path='/',
    )


def set_refresh_cookie(response: Response, token: str) -> None:
    """Refresh Token을 httpOnly 쿠키로 내려준다 — set_session_cookie와 같은 SameSite/secure
    정책을 쓴다. path를 굳이 /auth/refresh로 좁히지 않는다 — 그러면 POST /auth/logout이
    이 쿠키를 못 읽어 revoke_refresh_token을 호출할 수 없어진다(로그아웃 시 DB 폐기가
    이 기능의 핵심이라 path='/'로 단순하게 둔다)."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,  # TODO: 배포(https) 시 True로 변경
        samesite='lax',
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path='/',
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path='/')
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path='/')


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