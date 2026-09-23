"""[더미] 계획서·프로토타입 생성 진행 — POST .../plan/start, .../prototype/start + GET .../status.

실행:
    pytest tests/test_generation_progress.py -v
"""
import json
import time

import pytest

import app.routers.projects as projects_router
from app.models import Notice


@pytest.fixture(autouse=True)
def fast_generation(monkeypatch):
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.01)


def _matched_project(client, db_session) -> int:
    db_session.add(Notice(notice_id='NOTICE-GEN-1', source='kstartup', title='생성 진행 테스트 공고', recruitment_status='open'))
    db_session.commit()
    payload = {'description': '진행률 테스트용 아이템', 'team_members': [], 'pricing_items': []}
    project_id = client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']
    r = client.post(f'/projects/{project_id}/generate', json={'notice_id': 'NOTICE-GEN-1'})
    assert r.status_code == 200, r.text
    return project_id


def _wait_for_stage(client, project_id, stage, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f'/projects/{project_id}/status').json()
        if body['stage'] == stage:
            return body
        time.sleep(0.02)
    raise AssertionError(f'stage가 {stage}가 되지 않음: {body}')


def test_generate_leaves_plan_not_started(authed_client, db_session):
    project_id = _matched_project(authed_client, db_session)
    body = authed_client.get(f'/projects/{project_id}/status').json()
    assert body['stage'] is None


def test_plan_then_prototype_progress_to_done(authed_client, db_session):
    project_id = _matched_project(authed_client, db_session)

    started = authed_client.post(f'/projects/{project_id}/plan/start').json()
    assert started['stage'] == 'plan_writing'
    assert started['progress_percent'] == 0
    done = _wait_for_stage(authed_client, project_id, 'plan_review_pending')
    assert done['progress_percent'] == 100

    started = authed_client.post(f'/projects/{project_id}/prototype/start').json()
    assert started['stage'] == 'prototype_building'
    _wait_for_stage(authed_client, project_id, 'done')


def test_prototype_cannot_start_before_plan(authed_client, db_session):
    project_id = _matched_project(authed_client, db_session)
    body = authed_client.post(f'/projects/{project_id}/prototype/start').json()
    assert body['stage'] is None


def test_plan_start_twice_does_not_restart(authed_client, db_session):
    project_id = _matched_project(authed_client, db_session)
    authed_client.post(f'/projects/{project_id}/plan/start')
    _wait_for_stage(authed_client, project_id, 'plan_review_pending')
    again = authed_client.post(f'/projects/{project_id}/plan/start').json()
    assert again['stage'] == 'plan_review_pending'


def test_start_requires_match(authed_client):
    payload = {'description': '매칭 전 프로젝트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']
    assert authed_client.post(f'/projects/{project_id}/plan/start').status_code == 400
