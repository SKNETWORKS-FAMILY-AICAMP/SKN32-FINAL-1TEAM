"""app/orch/errors.py — CommandError 코드 → HTTP 응답."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.orch.errors import (
    KNOWN_CODES,
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
    assert resp.json() == {'detail': user_message_for('BUSY')}
