"""Regression tests for completion, archival, deletion and private downloads."""
import json

from fastapi.testclient import TestClient
from test_generation_async import _create_match

from app.models import Artifact, ProjectPlanInput, User
from app.routers import projects


def create(client):
    return client.post('/projects', data={'payload': json.dumps({'description': 'review test'})})


def test_finished_generation_allows_new_project(authed_client, db_session, monkeypatch):
    match = _create_match(authed_client, db_session, 'REVIEW-DONE')
    match.stage = 'prototype_building'
    match.status = 'in_progress'
    match.progress_percent = 90
    db_session.commit()
    monkeypatch.setattr(projects, 'DUMMY_GENERATION_STEP_SECONDS', 0)
    projects._simulate_generation(match.match_id, 'prototype_building', 'done')
    db_session.refresh(match)
    assert match.status == 'completed'
    assert create(authed_client).status_code == 201


def test_legacy_done_status_does_not_block(authed_client, db_session):
    match = _create_match(authed_client, db_session, 'REVIEW-LEGACY')
    match.stage = 'done'
    match.status = 'in_progress'
    db_session.commit()
    assert create(authed_client).status_code == 201


def test_archived_running_project_does_not_block(authed_client, db_session):
    match = _create_match(authed_client, db_session, 'REVIEW-ARCHIVE')
    match.stage = 'plan_writing'
    match.status = 'in_progress'
    db_session.commit()
    assert create(authed_client).status_code == 409
    assert authed_client.delete(f'/projects/{match.project_id}').status_code == 204
    assert create(authed_client).status_code == 201


def test_waiting_resume_blocks_new_project(authed_client, db_session):
    """[2026-09-26 회귀] 공식 기능정의서 v1.9 E-RUN-CONCURRENT(R-9) — waiting_resume(자동
    재개 백오프 대기 중)도 화면상 "진행"으로 보이는 실행 중 상태라 동시 실행 1건 제한에
    걸려야 한다. 예전엔 ACTIVE_MATCH_STATUSES에 in_progress만 있어서 재개 대기 중에도
    새 프로젝트를 하나 더 만들 수 있는 버그가 있었다."""
    match = _create_match(authed_client, db_session, 'REVIEW-WAITING-RESUME')
    match.stage = 'plan_writing'
    match.status = 'waiting_resume'
    db_session.commit()
    assert create(authed_client).status_code == 409

    # failed는 반대로 제한에서 안 세야 한다(E-RUN-FAIL "계정당 1건 제한에서 세지 않는다").
    match.status = 'failed'
    db_session.commit()
    assert create(authed_client).status_code == 201


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


def test_artifact_owner_keeps_preview_access(authed_client, login_as, db_session, monkeypatch, tmp_path):
    match = _create_match(authed_client, db_session, 'REVIEW-ARTIFACT')
    artifact = db_session.query(Artifact).join(Artifact.plan).filter_by(match_id=match.match_id).first()
    artifact.executable_path = '/uploads/preview.html'
    db_session.commit()
    monkeypatch.setattr(projects, 'UPLOAD_DIR', str(tmp_path))
    (tmp_path / 'preview.html').write_text('<h1>Preview</h1>')
    r = authed_client.get('/uploads/preview.html')
    assert r.status_code == 200
    assert r.headers['content-disposition'].startswith('inline')
    assert r.headers['content-security-policy'] == 'sandbox allow-scripts'
    assert login_as('stranger@example.com').get('/uploads/preview.html').status_code == 404
