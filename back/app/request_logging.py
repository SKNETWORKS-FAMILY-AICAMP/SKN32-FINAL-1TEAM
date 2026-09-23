"""웹서비스 HTTP 요청 로그 미들웨어 — 팀 로깅 정책("웹서비스" 담당 분량) 대응.

라우터마다 로그 호출을 일일이 넣는 대신 미들웨어 하나로 모든 요청의 시작/끝을 빠짐없이
남긴다 — 정책이 요구하는 "메소드 시작(누가 언제)/기능/성공 또는 실패/메소드 end/실패 시
에러 타입"을 요청(=API 메소드 호출) 단위로 충족한다.

담는 것: request_id(요청 하나 추적용), user_id(세션 쿠키에서 읽은 sub, 없으면 'anon'),
HTTP 메소드·경로, 처리 시간(ms), 상태코드, 성공/실패.
안 담는 것(개인정보 제외 원칙): 요청/응답 바디, 쿼리스트링 값, 쿠키·헤더 원문 — 전부 사용자가
입력한 이름·이메일·사업자번호 등을 담을 수 있어서 로그에 절대 안 남긴다. path는 FastAPI가
매칭한 라우트 템플릿(예: /projects/{project_id})을 쓴다 — 실제 값 대신 자리표시자만 남아
숫자 ID조차 로그에 그대로 안 찍힌다.

레벨 규칙(정책의 "실패 시 에러 타입 - info/warn/error" 대응): 2xx/3xx=INFO(성공),
4xx=WARNING(요청 자체가 못 통과한, 예상 가능한 실패), 5xx 또는 처리 중 예외=ERROR.
"""
import os
import sys
import time
import uuid

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import web_logger
from app.security import JWT_ALG, SESSION_COOKIE_NAME

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
import config as pipeline_config  # noqa: E402 -- app/security.py와 동일한 부트스트랩


def _peek_user_id(request: Request) -> str:
    """로그 표기용으로만 세션 쿠키를 살짝 들여다본다 — 이 미들웨어는 Depends(get_current_user)
    보다 먼저 도니 인증 여부를 판단할 자리가 아니다(그건 여전히 라우터 몫). DB 조회 없이
    토큰의 sub 클레임만 읽고, 없거나 깨졌으면 조용히 'anon'으로 남긴다."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return 'anon'
    try:
        secret = pipeline_config.require('JWT_SECRET')
        payload = jwt.decode(token, secret, algorithms=[JWT_ALG])
        return str(payload.get('sub', 'anon'))
    except Exception:
        return 'anon'


def _route_path(request: Request) -> str:
    """실제 경로 대신 매칭된 라우트 템플릿을 쓴다 — /projects/{project_id}처럼 자리표시자만
    남기고, 매칭 전(404 등)엔 request.url.path로 대체한다."""
    route = request.scope.get('route')
    return route.path if route is not None else request.url.path


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:12]
        user_id = _peek_user_id(request)
        method = request.method
        start = time.monotonic()
        web_logger.info(f'req_id={request_id} user_id={user_id} {method} {request.url.path} start')

        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            web_logger.error(
                f'req_id={request_id} user_id={user_id} {method} {request.url.path} end '
                f'status=500 elapsed_ms={elapsed_ms} result=fail error_type={type(exc).__name__}'
            )
            raise

        elapsed_ms = int((time.monotonic() - start) * 1000)
        status_code = response.status_code
        path = _route_path(request)
        if status_code >= 500:
            level, result = 'error', 'fail'
        elif status_code >= 400:
            level, result = 'warning', 'fail'
        else:
            level, result = 'info', 'success'
        getattr(web_logger, level)(
            f'req_id={request_id} user_id={user_id} {method} {path} end '
            f'status={status_code} elapsed_ms={elapsed_ms} result={result}'
        )
        return response
