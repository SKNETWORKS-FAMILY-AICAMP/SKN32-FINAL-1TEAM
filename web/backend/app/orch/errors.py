"""오류 → 웹 HTTP 응답.

오케스트레이터의 CommandError.code(함수 명세 10.2절)를 웹이 정한 HTTP 상태와 사용자 문구로 바꾼다.
상태 코드와 문구는 잠정이다 — 프론트가 detail을 그대로 보여 주므로 프론트와 맞춰 확정한다.

[SB-273] 모든 오류 응답은 본문 최상위에 `code`를 가진다: {"detail": ..., "code": "ANNOUNCEMENT_BLOCKED"}.
detail은 예전과 같다(문자열이거나, 확인 요청 · 막힘 안내처럼 객체) — 프론트는 detail을 보여 주고 code로 분기한다.
code 이름은 세 갈래다:
  1) 오케스트레이터 오류 — 그 코드 그대로(BUSY · ANNOUNCEMENT_BLOCKED · E-G2-LIMIT …). 500으로 답하는 내부 오류(WEB_NOT_ALLOWED · 모르는 코드)는
     내부 이름을 싣지 않고 INTERNAL_ERROR.
  2) 웹이 직접 내는 오류 — CodedHTTPException으로 정한 이름(E-RUN-CONCURRENT · CONFIRMATION_REQUIRED · PLAN_NOT_READY …).
     기능정의서 시트 6에 있는 코드(E-RUN-CONCURRENT · E-AUTH-CONSENT · E-AUTH-PROFILE · E-C1-REQUIRED)는 그 이름을 쓴다.
  3) 그 밖의 HTTP 오류(인증 · 권한 · 없는 경로 · 입력 검증 …) — 상태 코드별 기본 이름(UNAUTHORIZED · FORBIDDEN · NOT_FOUND · VALIDATION_ERROR …).
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException


class OrchError(Exception):
    """gateway가 오케스트레이터의 CommandError를 웹 쪽 예외로 바꿔 올린 것."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(f'{code}: {detail}')
        self.code = code
        self.detail = detail


class CodedHTTPException(HTTPException):
    """웹이 직접 내는 오류 — 본문 최상위 code를 이름으로 정해 붙인다(detail은 그대로)."""

    def __init__(
        self, status_code: int, code: str, detail: Any = None, headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


INTERNAL_ERROR = 'INTERNAL_ERROR'
_GENERIC = '요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.'

# 코드 → (HTTP 상태, 사용자에게 보이는 문구). 500은 웹 설정 · 호출 오류라 내부 내용을 싣지 않는다.
_RULES: dict[str, tuple[int, str]] = {
    'PROJECT_NOT_FOUND': (404, '프로젝트를 찾을 수 없어요.'),
    'RUN_NOT_FOUND': (404, '아직 시작된 작업이 없어요.'),
    'PROJECT_ALREADY_STARTED': (409, '이미 시작된 프로젝트예요. 새 프로젝트로 시작해 주세요.'),
    'RUN_NOT_VIEWABLE': (409, '일시적인 문제로 작업을 완료하지 못했습니다. 새 작업으로 다시 시작해주세요.'),
    'SCREEN_NOT_READY': (409, '아직 이 화면을 볼 수 있는 단계가 아니에요.'),
    'INVALID_STATE': (409, '지금 단계에서는 할 수 없는 요청이에요.'),
    'BUSY': (409, '작업이 진행 중이에요. 잠시 뒤 다시 시도해 주세요.'),
    'MORE_LIMIT': (409, '공고 다시 찾기는 한 번만 할 수 있어요.'),
    'ANNOUNCEMENT_BLOCKED': (409, '신청 자격에 맞지 않는 공고예요. 다른 공고를 선택해 주세요.'),
    # 기능정의서 v1.9 시트 6 E-G2-LIMIT의 사용자 노출 문구 그대로
    'E-G2-LIMIT': (409, '이 항목은 다시 만들 수 있는 횟수를 모두 사용했습니다. '
                        '다시 만들기 전과 후 중 점수가 높은 결과가 반영되어 있습니다.'),
    'INVALID_ANNOUNCEMENT': (422, '선택할 수 없는 공고예요.'),
    'INVALID_SCREEN': (422, '알 수 없는 화면이에요.'),
    'INVALID_ACTION': (422, '알 수 없는 요청이에요.'),
    'INVALID_ORDER': (422, '이 화면에서 다시 만들 수 없는 항목이에요.'),
    'NO_SELECTION': (422, '다시 만들 항목을 선택해 주세요.'),
    'WEB_NOT_ALLOWED': (500, _GENERIC),
    'NO_PROJECT_SOURCE': (500, _GENERIC),
}

KNOWN_CODES = frozenset(_RULES)

# 상태 코드별 기본 code — CodedHTTPException이 아닌 HTTP 오류(인증 · 권한 · 없는 경로 · 입력 검증 …)에 붙는다
_STATUS_CODES: dict[int, str] = {
    400: 'BAD_REQUEST', 401: 'UNAUTHORIZED', 403: 'FORBIDDEN', 404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED',
    409: 'CONFLICT', 413: 'PAYLOAD_TOO_LARGE', 422: 'VALIDATION_ERROR', 429: 'TOO_MANY_REQUESTS',
    500: INTERNAL_ERROR, 503: 'SERVICE_UNAVAILABLE',
}


def http_status_for(code: str) -> int:
    return _RULES.get(code, (500, _GENERIC))[0]


def user_message_for(code: str) -> str:
    return _RULES.get(code, (500, _GENERIC))[1]


def code_for_status(status_code: int) -> str:
    """CodedHTTPException이 아닌 오류의 기본 code."""
    return _STATUS_CODES.get(status_code, INTERNAL_ERROR if status_code >= 500 else 'BAD_REQUEST')


def error_code_of(exc: StarletteHTTPException) -> str:
    return getattr(exc, 'code', None) or code_for_status(exc.status_code)


def error_body(detail: Any, code: str) -> dict[str, Any]:
    return {'detail': detail, 'code': code}


def to_http_exception(err: OrchError) -> CodedHTTPException:
    status, message = _RULES.get(err.code, (500, _GENERIC))
    # 500은 내부 오류라 오케스트레이터 코드 이름을 밖으로 내지 않는다
    code = err.code if err.code in _RULES and status < 500 else INTERNAL_ERROR
    return CodedHTTPException(status_code=status, code=code, detail=message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OrchError)
    async def _orch_error_handler(_request: Request, err: OrchError) -> JSONResponse:
        exc = to_http_exception(err)
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.detail, exc.code))

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_request: Request, exc: StarletteHTTPException) -> Response:
        # FastAPI 기본 처리와 같다(본문이 없는 상태 · 응답 헤더 유지) — 본문에 code만 더한다
        headers = getattr(exc, 'headers', None)
        if exc.status_code < 200 or exc.status_code in (204, 205, 304):
            return Response(status_code=exc.status_code, headers=headers)
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc.detail, error_code_of(exc)), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=error_body(jsonable_encoder(exc.errors()), _STATUS_CODES[422]))

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        # 예상 못 한 오류 — 내용은 서버 로그에만 남기고(예외는 계속 올라간다) 사용자에게는 일반 문구만 준다
        return JSONResponse(status_code=500, content=error_body(_GENERIC, INTERNAL_ERROR))
