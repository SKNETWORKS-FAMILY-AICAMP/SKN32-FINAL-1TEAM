"""Regression tests for completion, archival, deletion and private downloads."""
import json

from fastapi.testclient import TestClient
from orch_fakes import AbortResult, ActiveWork, ProjectView, make_run

from app.models import Project, ProjectPlanInput, User
from app.routers import projects


def create(client):
    return client.post('/projects', data={'payload': json.dumps({'description': 'review test'})})


def _running_work(orch, state, project_id):
    """진행 중인 작업이 project_id 프로젝트인 상태 — abort_project가 불리면 진행 중이 아니게 된다."""
    orch.responses['active_work'] = lambda account_id: ActiveWork(
        project_id=str(project_id), run_id='r1', step='계획서작성', resume_step=5) if state['active'] else None

    def abort(pid):
        state['active'] = False
        return AbortResult(project_id=str(pid), run_id='r1', run_action='중단')

    orch.responses['abort_project'] = abort
    orch.responses['view_project'] = lambda pid: ProjectView(str(pid), run=make_run())


def test_archived_running_project_does_not_block(authed_client, db_session, orch):
    """휴지통(DELETE)은 오케스트레이터에 중단을 알린 뒤 보관한다 — 그 뒤 새 프로젝트를 만들 수 있다."""
    pid = create(authed_client).json()['project_id']
    state = {'active': True}
    _running_work(orch, state, pid)
    assert create(authed_client).status_code == 409
    assert authed_client.delete(f'/projects/{pid}').status_code == 204
    assert ('abort_project', (pid,), {}) in orch.calls
    assert create(authed_client).status_code == 201
    db_session.expire_all()
    assert db_session.get(Project, pid).archived_at is not None, '실행 건이 있던 프로젝트는 지우지 않고 보관해야 한다'


def test_concurrent_project_blocked_response_supports_abandon_and_restart(authed_client, db_session, orch):
    """[2026-09-27 신규, SB-138] 공식 기능정의서 v1.9 E-RUN-CONCURRENT — 진행 중인 실행이
    있으면 blocked=true와 함께 어느 프로젝트가 막고 있는지(active_project_id) 구조화된
    정보를 내려줘야 프론트가 "이어하기 / 중단 후 새로 시작" 선택 화면을 만들 수 있다.
    "중단 후 새로 시작"은 새 엔드포인트가 아니라 기존 DELETE /projects/{id}를 그대로
    쓴다 — 그 active_project_id로 DELETE를 부르면 다시 새 프로젝트를 만들 수 있어야 한다."""
    pid = create(authed_client).json()['project_id']
    state = {'active': True}
    _running_work(orch, state, pid)

    res = create(authed_client)
    assert res.status_code == 409
    body = res.json()['detail']
    assert body['blocked'] is True
    assert body['active_project_id'] == pid
    assert body['active_stage'] == 'plan_writing'
    assert body['active_display_status'] == '진행'

    # "중단 후 새로 시작" — active_project_id로 기존 삭제(보관) 엔드포인트를 부르면 된다.
    assert authed_client.delete(f'/projects/{body["active_project_id"]}').status_code == 204
    assert create(authed_client).status_code == 201


def test_failed_run_does_not_block_new_project(authed_client, orch):
    """E-RUN-FAIL — 실패한 실행 건은 계정당 1건 제한에서 세지 않는다. 오케스트레이터가 active_work로
    None을 주면(실패 · 완료 · 중단은 진행 중이 아니다) 새 프로젝트를 만들 수 있다."""
    pid = create(authed_client).json()['project_id']
    orch.responses['view_project'] = lambda p: ProjectView(str(p), run=make_run(progress='실패'))
    orch.responses['active_work'] = None
    assert create(authed_client).status_code == 201
    assert pid


def test_delete_removes_plan_inputs(authed_client, db_session):
    pid = create(authed_client).json()['project_id']
    assert db_session.query(ProjectPlanInput).filter_by(project_id=pid).count() == 1
    assert authed_client.delete(f'/projects/{pid}').status_code == 204
    assert db_session.query(ProjectPlanInput).filter_by(project_id=pid).count() == 0


def test_private_uploads(authed_client, login_as, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(projects, 'UPLOAD_DIR', str(tmp_path))
    r = authed_client.post('/projects', data={'payload': json.dumps({'description': 'private'})},
                          files={'files': ('secret.txt', b'private content', 'text/plain')})
    assert r.status_code == 201
    url = r.json()['attachments'][0]['file_url']
    from app.main import app
    assert TestClient(app).get(url).status_code == 401
    own = authed_client.get(url)
    assert own.status_code == 200 and own.content == b'private content'
    assert own.headers['cache-control'] == 'private, no-store'
    assert own.headers['content-disposition'].startswith('attachment')
    other = login_as('other@example.com')
    assert other.get(url).status_code == 404
    user = db_session.query(User).filter_by(email='other@example.com').one()
    user.role = 'admin'
    db_session.commit()
    assert other.get(url).status_code == 200
    (tmp_path / 'untracked.txt').write_text('untracked')
    assert other.get('/uploads/untracked.txt').status_code == 404


