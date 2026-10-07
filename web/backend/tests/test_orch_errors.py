"""app/orch/errors.py — CommandError 코드 → HTTP 응답."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.orch.errors import (
    KNOWN_CODES,
    CodedHTTPException,
    OrchError,
    http_status_for,
    register_error_handlers,
    to_http_exception,
    user_message_for,
)

# 함수 명세 10.2절의 CommandError.code 전부
SPEC_CODES = {
    'PROJECT_NOT_FOUND', 'PROJECT_ALREADY_STARTED', 'RUN_NOT_FOUND', 'RUN_NOT_VIEWABLE', 'WEB_NOT_ALLOWED',
    'SCREEN_NOT_READY', 'INVALID_SCREEN', 'INVALID_STATE', 'BUSY', 'MORE_LIMIT', 'INVALID_ANNOUNCEMENT',
    'ANNOUNCEMENT_BLOCKED', 'NO_SELECTION', 'INVALID_ORDER', 'INVALID_ACTION', 'E-G2-LIMIT', 'NO_PROJECT_SOURCE',
}


def test_every_spec_code_has_a_rule():
    assert KNOWN_CODES == SPEC_CODES


@pytest.mark.parametrize('code, status', [
    ('PROJECT_NOT_FOUND', 404), ('RUN_NOT_FOUND', 404),
    ('INVALID_STATE', 409), ('BUSY', 409), ('E-G2-LIMIT', 409), ('MORE_LIMIT', 409), ('ANNOUNCEMENT_BLOCKED', 409),
    ('RUN_NOT_VIEWABLE', 409),
    ('INVALID_ANNOUNCEMENT', 422), ('INVALID_ORDER', 422), ('NO_SELECTION', 422),
    ('WEB_NOT_ALLOWED', 500), ('NO_PROJECT_SOURCE', 500),
])
def test_status_by_code(code, status):
    assert http_status_for(code) == status
    assert to_http_exception(OrchError(code)).status_code == status


def test_unknown_code_is_500_and_does_not_leak_detail():
    exc = to_http_exception(OrchError('SOMETHING_NEW', '내부 사정 abc'))
    assert exc.status_code == 500
    assert 'abc' not in exc.detail and 'SOMETHING_NEW' not in exc.detail


def test_internal_errors_do_not_expose_detail_to_users():
    exc = to_http_exception(OrchError('WEB_NOT_ALLOWED', 'advance'))
    assert 'advance' not in exc.detail
    assert exc.detail == user_message_for('NO_PROJECT_SOURCE')


def test_exception_handler_returns_status_and_detail():
    app = FastAPI()
    register_error_handlers(app)

    @app.get('/boom')
    def boom():
        raise OrchError('BUSY', 'x')

    resp = TestClient(app).get('/boom')
    assert resp.status_code == 409
    assert resp.json() == {'detail': user_message_for('BUSY'), 'code': 'BUSY'}


# ── [SB-273] 모든 오류 응답은 본문 최상위에 code를 가진다 ───────────────────────────────────────
@pytest.mark.parametrize('code', sorted(c for c in SPEC_CODES if http_status_for(c) < 500))
def test_orchestrator_errors_keep_their_own_code(code):
    exc = to_http_exception(OrchError(code))
    assert exc.code == code and exc.status_code == http_status_for(code)


@pytest.mark.parametrize('code', ['WEB_NOT_ALLOWED', 'NO_PROJECT_SOURCE', 'SOMETHING_NEW'])
def test_internal_errors_do_not_expose_their_code(code):
    exc = to_http_exception(OrchError(code, '내부'))
    assert exc.status_code == 500 and exc.code == 'INTERNAL_ERROR'


def test_group_limit_message_matches_the_spec():
    """기능정의서 v1.9 시트 6 E-G2-LIMIT의 사용자 노출 문구 그대로."""
    assert user_message_for('E-G2-LIMIT') == (
        '이 항목은 다시 만들 수 있는 횟수를 모두 사용했습니다. 다시 만들기 전과 후 중 점수가 높은 결과가 반영되어 있습니다.')


class _Body(BaseModel):
    n: int


def _error_app() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get('/plain/{status}')
    def plain(status: int):
        raise HTTPException(status_code=status, detail='문구')

    @app.get('/headers')
    def with_headers():
        raise HTTPException(status_code=401, detail='로그인', headers={'WWW-Authenticate': 'Bearer'})

    @app.get('/coded')
    def coded():
        raise CodedHTTPException(409, 'CONFIRMATION_REQUIRED', {'confirmation_required': True, 'items': {'a': 1}})

    @app.get('/empty')
    def empty():
        raise HTTPException(status_code=204)

    @app.post('/validate')
    def validate(body: _Body):
        return body

    @app.get('/crash')
    def crash():
        raise RuntimeError('내부 사정 abc')

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize('status, code', [
    (400, 'BAD_REQUEST'), (401, 'UNAUTHORIZED'), (403, 'FORBIDDEN'), (404, 'NOT_FOUND'), (409, 'CONFLICT'),
    (413, 'PAYLOAD_TOO_LARGE'), (422, 'VALIDATION_ERROR'), (500, 'INTERNAL_ERROR'), (503, 'SERVICE_UNAVAILABLE'),
    (418, 'BAD_REQUEST'),
])
def test_plain_http_errors_get_a_default_code_by_status(status, code):
    resp = _error_app().get(f'/plain/{status}')
    assert resp.status_code == status
    assert resp.json() == {'detail': '문구', 'code': code}


def test_unknown_route_and_method_get_codes():
    client = _error_app()
    resp = client.get('/nope')
    assert resp.status_code == 404 and resp.json()['code'] == 'NOT_FOUND'
    resp = client.post('/plain/400')
    assert resp.status_code == 405 and resp.json()['code'] == 'METHOD_NOT_ALLOWED'


def test_coded_exception_keeps_object_detail():
    resp = _error_app().get('/coded')
    assert resp.status_code == 409
    assert resp.json() == {
        'detail': {'confirmation_required': True, 'items': {'a': 1}}, 'code': 'CONFIRMATION_REQUIRED'}


def test_response_headers_are_kept():
    resp = _error_app().get('/headers')
    assert resp.status_code == 401 and resp.headers['www-authenticate'] == 'Bearer'


def test_status_without_a_body_stays_empty():
    resp = _error_app().get('/empty')
    assert resp.status_code == 204 and resp.content == b''


def test_validation_error_keeps_detail_list_and_adds_code():
    resp = _error_app().post('/validate', json={'n': 'abc'})
    assert resp.status_code == 422
    body = resp.json()
    assert body['code'] == 'VALIDATION_ERROR'
    assert isinstance(body['detail'], list) and body['detail'][0]['loc'] == ['body', 'n']


def test_unhandled_error_is_json_without_internal_details():
    resp = _error_app().get('/crash')
    assert resp.status_code == 500
    assert resp.json() == {'detail': '요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.', 'code': 'INTERNAL_ERROR'}
    assert 'abc' not in resp.text
