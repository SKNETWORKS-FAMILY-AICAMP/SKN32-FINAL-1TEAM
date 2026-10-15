"""관리자 — 산출물 파일 삭제 대기열 (SB-318): GET /admin/file-deletions · POST /admin/file-deletions/{id}/retry.

파일은 오케스트레이터가 같은 트랜잭션에서 대기열에 넣고 워커가 지운다. 웹은 목록을 보여 주고 '포기'한 줄을 다시 시도하게 할 뿐이다.

실행:
    pytest tests/test_admin_file_deletions.py -v
"""
from datetime import UTC, datetime

import pytest
from orch_fakes import make_file_deletion

from app.models import User
from app.orch import OrchError


@pytest.fixture()
def admin(login_as, db_session):
    client = login_as('admin@example.com')
    db_session.query(User).filter(User.email == 'admin@example.com').update({'role': 'admin'})
    db_session.commit()
    return client


def _admin_id(db_session) -> str:
    return str(db_session.query(User).filter(User.email == 'admin@example.com').one().user_id)


def _calls(orch, name):
    return [c for c in orch.calls if c[0] == name]


def test_list_returns_metadata_only_with_utc_times(admin, orch):
    when = datetime(2026, 10, 8, 3, 4, 5, tzinfo=UTC)
    orch.responses['admin_file_deletions'] = lambda **kw: [
        make_file_deletion(deletion_id='d1', status='포기', attempts=3, last_error_kind='운영', created_at=when, next_at=when,
                           last_tried_at=when, gave_up_at=when),
        make_file_deletion(deletion_id='d2', status='대기', attempts=0, last_error_kind=None, last_tried_at=None, gave_up_at=None)]

    r = admin.get('/admin/file-deletions')

    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x['deletion_id'] for x in rows] == ['d1', 'd2']
    assert rows[0]['status'] == '포기' and rows[0]['attempts'] == 3 and rows[0]['last_error_kind'] == '운영'
    assert rows[0]['created_at'] == '2026-10-08T03:04:05Z' and rows[0]['gave_up_at'] == '2026-10-08T03:04:05Z'
    assert rows[1]['last_tried_at'] is None and rows[1]['gave_up_at'] is None and rows[1]['retried_by'] is None
    # 파일 이름 · 키 · 사용자 · 오류 메시지는 응답에 없다
    assert set(rows[0]) == {
        'deletion_id', 'run_id', 'status', 'attempts', 'last_error_kind', 'created_at', 'next_at', 'last_tried_at',
        'gave_up_at', 'retried_by', 'retried_at', 'retry_count'}


def test_list_passes_status_and_paging_to_the_orchestrator(admin, orch):
    orch.responses['admin_file_deletions'] = lambda **kw: []

    admin.get('/admin/file-deletions?status=포기&limit=20&offset=40')

    assert _calls(orch, 'admin_file_deletions') == [('admin_file_deletions', (), {'status': '포기', 'limit': 20, 'offset': 40})]


def test_list_defaults(admin, orch):
    orch.responses['admin_file_deletions'] = lambda **kw: []

    assert admin.get('/admin/file-deletions').json() == []

    assert _calls(orch, 'admin_file_deletions')[0][2] == {'status': None, 'limit': 50, 'offset': 0}


@pytest.mark.parametrize('query', ['status=완료', 'limit=0', 'limit=201', 'offset=-1'])
def test_list_rejects_invalid_parameters(admin, orch, query):
    assert admin.get(f'/admin/file-deletions?{query}').status_code == 422
    assert _calls(orch, 'admin_file_deletions') == []


def test_retry_sends_the_admin_id_and_returns_the_changed_row(admin, orch, db_session):
    orch.responses['admin_retry_file_deletion'] = lambda deletion_id, admin_id: make_file_deletion(
        deletion_id=deletion_id, status='대기', attempts=0, gave_up_at=None, retried_by=admin_id, retry_count=1)

    r = admin.post('/admin/file-deletions/d1/retry')

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['deletion_id'] == 'd1' and body['status'] == '대기' and body['retry_count'] == 1
    assert body['retried_by'] == _admin_id(db_session)
    assert _calls(orch, 'admin_retry_file_deletion') == [('admin_retry_file_deletion', ('d1', _admin_id(db_session)), {})]


@pytest.mark.parametrize('code, status', [('FILE_DELETION_NOT_FOUND', 404), ('INVALID_STATE', 409)])
def test_retry_errors_become_http_errors(admin, orch, code, status):
    orch.responses['admin_retry_file_deletion'] = OrchError(code)

    r = admin.post('/admin/file-deletions/d1/retry')

    assert r.status_code == status and r.json()['code'] == code


def test_users_that_are_not_admin_get_403_and_the_orchestrator_is_not_asked(authed_client, orch):
    assert authed_client.get('/admin/file-deletions').status_code == 403
    assert authed_client.post('/admin/file-deletions/d1/retry').status_code == 403
    assert not _calls(orch, 'admin_file_deletions') and not _calls(orch, 'admin_retry_file_deletion')


def test_requires_login(client, orch):
    assert client.get('/admin/file-deletions').status_code == 401
    assert client.post('/admin/file-deletions/d1/retry').status_code == 401
