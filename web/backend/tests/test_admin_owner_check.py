"""관리자도 다른 사용자의 프로젝트는 읽거나 바꿀 수 없다 (SB-418).

기획서 6-7: 관리자 열람은 메타데이터(/admin/*)로 한정한다 — 사용자의 계획서 · 결과 · 산출물 내용은 관리자도 받을 수 없다.
`_get_owned_project`에 `user.role != 'admin'` 예외가 있어 `/projects/{id}/...` 경로로는 관리자가 남의 프로젝트 상세 · 결과 · 계획서 파일을 받고
시작 · 삭제 · 영구 삭제까지 할 수 있었다(2026-10-21 운영 서버 점검에서 발견). 관리자 화면은 /admin/* 만 쓰므로 이 예외는 필요 없다.

실행:
    pytest tests/test_admin_owner_check.py -v
"""
import json

import pytest

from app.models import Project, User


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '소유자 검사 시험'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _as_admin(login_as, db_session, email='admin@example.com'):
    client = login_as(email)
    db_session.query(User).filter(User.email == email).update({'role': 'admin'})
    db_session.commit()
    return client


READ_PATHS = [
    '', '/status', '/eligibility', '/match-candidates', '/result', '/rework-result',
    '/plan-document.docx', '/plan-document.pdf', '/plan-document.hwp', '/deliverable.zip',
]


@pytest.mark.parametrize('suffix', READ_PATHS)
def test_admin_cannot_read_someone_elses_project(login_as, db_session, orch, suffix):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    admin = _as_admin(login_as, db_session)
    before = len(orch.calls)

    res = admin.get(f'/projects/{pid}{suffix}')

    assert res.status_code == 404, f'{suffix or "(상세)"} → {res.status_code}'
    assert len(orch.calls) == before   # 소유자가 아니면 오케스트레이터에는 묻지도 않는다


WRITE_REQUESTS = [
    ('post', '/plan/start', None),
    ('post', '/prototype/start', None),
    ('post', '/final-review/start', None),
    ('post', '/review/start', None),
    ('post', '/generate', {'notice_id': 'kstartup:1'}),
    ('post', '/match-candidates/rematch', None),
    ('post', '/retry-task', {'task_key': 'writing', 'bundle_id': '문제인식'}),
    ('delete', '', None),
    ('delete', '/permanent', None),
]


@pytest.mark.parametrize(('method', 'suffix', 'body'), WRITE_REQUESTS)
def test_admin_cannot_change_someone_elses_project(login_as, db_session, orch, method, suffix, body):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    admin = _as_admin(login_as, db_session)
    before = len(orch.calls)

    kwargs = {'json': body} if body is not None else {}
    res = getattr(admin, method)(f'/projects/{pid}{suffix}', **kwargs)

    assert res.status_code == 404, f'{method.upper()} {suffix or "(프로젝트)"} → {res.status_code}'
    assert len(orch.calls) == before                       # 시작 · 중단 · 삭제 같은 명령이 오케스트레이터로 나가지 않음
    db_session.expire_all()
    assert db_session.get(Project, pid) is not None        # 프로젝트가 지워지지 않음
    owner = login_as('owner@example.com')                  # login_as는 같은 클라이언트의 쿠키를 바꿔 끼우므로 소유자로 다시 로그인한다
    assert owner.get(f'/projects/{pid}').status_code == 200  # 소유자는 그대로 볼 수 있음


def test_admin_still_works_with_their_own_project(login_as, db_session):
    """관리자 계정도 서비스를 쓸 때는 일반 사용자와 같다 — 자기 프로젝트는 만들고 읽는다."""
    admin = _as_admin(login_as, db_session)
    pid = _create(admin)

    assert admin.get(f'/projects/{pid}').status_code == 200
    assert admin.get(f'/projects/{pid}/status').status_code == 200
    assert pid in [p['project_id'] for p in admin.get('/projects').json()]


def test_admin_project_list_has_only_their_own_projects(login_as, db_session):
    owner = login_as('owner@example.com')
    owner_pid = _create(owner)
    admin = _as_admin(login_as, db_session)
    admin_pid = _create(admin)

    ids = [p['project_id'] for p in admin.get('/projects').json()]

    assert admin_pid in ids and owner_pid not in ids


def test_owner_is_unaffected(login_as):
    owner = login_as('owner@example.com')
    pid = _create(owner)

    assert owner.get(f'/projects/{pid}').status_code == 200
    assert owner.get(f'/projects/{pid}/status').status_code == 200


def test_admin_api_still_lists_every_project_metadata(login_as, db_session):
    """관리자 열람은 /admin/* 메타데이터로 계속 가능하다 — 목록에는 다른 사용자의 프로젝트가 보인다."""
    owner = login_as('owner@example.com')
    pid = _create(owner)
    admin = _as_admin(login_as, db_session)

    res = admin.get('/admin/items')

    assert res.status_code == 200
    rows = res.json()
    rows = rows if isinstance(rows, list) else rows.get('items', [])
    assert pid in [r['project_id'] for r in rows]
