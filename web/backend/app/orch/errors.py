"""오케스트레이터 오류 → 웹 HTTP 응답.

오케스트레이터의 CommandError.code(함수 명세 10.2절)를 웹이 정한 HTTP 상태와 사용자 문구로 바꾼다.
상태 코드와 문구는 잠정이다 — 프론트가 detail을 그대로 보여 주므로 프론트와 맞춰 확정한다.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse


class OrchError(Exception):
    """gateway가 오케스트레이터의 CommandError를 웹 쪽 예외로 바꿔 올린 것."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(f'{code}: {detail}')
        self.code = code
        self.detail = detail


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
    'E-G2-LIMIT': (409, '이 항목은 다시 만들 수 있는 횟수를 모두 사용했어요.'),
    'INVALID_ANNOUNCEMENT': (422, '선택할 수 없는 공고예요.'),
    'INVALID_SCREEN': (422, '알 수 없는 화면이에요.'),
    'INVALID_ACTION': (422, '알 수 없는 요청이에요.'),
    'INVALID_ORDER': (422, '이 화면에서 다시 만들 수 없는 항목이에요.'),
    'NO_SELECTION': (422, '다시 만들 항목을 선택해 주세요.'),
    'WEB_NOT_ALLOWED': (500, _GENERIC),
    'NO_PROJECT_SOURCE': (500, _GENERIC),
}

KNOWN_CODES = frozenset(_RULES)


def http_status_for(code: str) -> int:
    return _RULES.get(code, (500, _GENERIC))[0]


def user_message_for(code: str) -> str:
    return _RULES.get(code, (500, _GENERIC))[1]


def to_http_exception(err: OrchError) -> HTTPException:
    status, message = _RULES.get(err.code, (500, _GENERIC))
    return HTTPException(status_code=status, detail=message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OrchError)
    async def _orch_error_handler(_request, err: OrchError) -> JSONResponse:
        exc = to_http_exception(err)
        return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})
