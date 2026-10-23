"""휴지통으로 옮긴(보관 처리한) 프로젝트는 목록에서만 숨겨지지 않고 /projects/{id}/... 경로에서도 열리지 않는다 (SB-421).

DELETE /projects/{id}는 실행 건이 있으면 archived_at만 채운다. 목록(GET /projects)은 그걸 숨기지만 /status 같은 경로는
소유자 검사만 해서 200으로 응답했다(2026-10-21 운영 서버 점검에서 발견). 이제 보관된 프로젝트는 소유자에게도 404이고,
휴지통에서 다시 지우는 DELETE와 영구 삭제만 열려 있다.

실행:
    pytest tests/test_archived_project_routes.py -v
"""
import datetime
import json

import pytest
from orch_fakes import ProjectView, make_run

from app.models import Project
from tests.test_admin_owner_check import READ_PATHS, WRITE_REQUESTS


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '휴지통 시험'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _archive(db_session, project_id: int, by: str = 'user') -> None:
    project = db_session.get(Project, project_id)
    project.archived_at = datetime.datetime.utcnow()
    project.archived_by = by
    db_session.commit()


@pytest.mark.parametrize('suffix', READ_PATHS)
def test_archived_project_is_not_readable_even_by_owner(login_as, db_session, orch, suffix):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _archive(db_session, pid)
    before = len(orch.calls)

    res = owner.get(f'/projects/{pid}{suffix}')

    assert res.status_code == 404, f'{suffix or "(상세)"} → {res.status_code}'
    assert len(orch.calls) == before   # 보관된 프로젝트는 오케스트레이터에 묻지도 않는다


# 휴지통에서 다시 지우는 DELETE 와 영구 삭제는 보관된 프로젝트에도 열려 있어야 한다
BLOCKED_WRITES = [w for w in WRITE_REQUESTS if w[1] not in ('', '/permanent')]


@pytest.mark.parametrize(('method', 'suffix', 'body'), BLOCKED_WRITES)
def test_archived_project_cannot_be_changed(login_as, db_session, orch, method, suffix, body):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _archive(db_session, pid)
    before = len(orch.calls)

    kwargs = {'json': body} if body is not None else {}
    res = getattr(owner, method)(f'/projects/{pid}{suffix}', **kwargs)

    assert res.status_code == 404, f'{method.upper()} {suffix} → {res.status_code}'
    assert len(orch.calls) == before


def test_archived_by_admin_is_also_closed_to_owner(login_as, db_session):
    """관리자가 보관 처리한 프로젝트(archived_by='admin')도 사용자에게는 목록과 같이 닫혀 있다."""
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _archive(db_session, pid, by='admin')

    assert owner.get(f'/projects/{pid}/status').status_code == 404


def test_restored_project_opens_again(login_as, db_session):
    """보관을 풀면(관리자 복원 포함) 다시 열린다."""
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _archive(db_session, pid)
    assert owner.get(f'/projects/{pid}/status').status_code == 404

    project = db_session.get(Project, pid)
    project.archived_at = None
    project.archived_by = None
    db_session.commit()

    assert owner.get(f'/projects/{pid}/status').status_code == 200


def test_owner_can_still_delete_an_archived_project_again(login_as, db_session):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _archive(db_session, pid)

    assert owner.delete(f'/projects/{pid}').status_code == 204


def test_owner_can_still_permanently_delete_an_archived_project(login_as, db_session):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _archive(db_session, pid)

    assert owner.delete(f'/projects/{pid}/permanent').status_code == 204
    db_session.expire_all()
    assert db_session.get(Project, pid) is None


def test_not_archived_project_is_unaffected(login_as):
    owner = login_as('owner@example.com')
    pid = _create(owner)

    assert owner.get(f'/projects/{pid}').status_code == 200
    assert owner.get(f'/projects/{pid}/status').status_code == 200


def test_trashing_through_the_api_closes_the_routes(login_as, db_session, orch):
    """실제 휴지통 버튼(DELETE)으로 보관 처리한 직후에도 같다 — 목록에서 사라지고 /status도 404."""
    orch.responses['view_project'] = lambda p: ProjectView(str(p), run=make_run())   # 실행 건이 있다 → 보관 처리
    owner = login_as('owner@example.com')
    pid = _create(owner)

    assert owner.delete(f'/projects/{pid}').status_code == 204

    assert pid not in [p['project_id'] for p in owner.get('/projects').json()]
    assert owner.get(f'/projects/{pid}/status').status_code == 404


def test_archived_project_artifact_files_are_closed(login_as, db_session, orch):
    """산출물 파일 내려받기(/artifact-files/{key})도 보관된 프로젝트는 소유자에게 404 — 파일 저장소를 부르지도 않는다."""
    class _File:
        data, media_type, name, size, sha256 = b'<html></html>', 'text/html', 'index.html', 13, ''

    orch.responses['read_artifact_file'] = lambda project_id, key: _File()
    owner = login_as('owner@example.com')
    pid = _create(owner)
    assert owner.get(f'/projects/{pid}/artifact-files/k').status_code == 200     # 보관 전에는 받는다

    _archive(db_session, pid)
    before = len(orch.calls)

    assert owner.get(f'/projects/{pid}/artifact-files/k').status_code == 404
    assert len(orch.calls) == before
