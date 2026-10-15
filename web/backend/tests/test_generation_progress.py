"""[더미] 계획서·프로토타입 생성 진행 — POST .../plan/start, .../prototype/start + GET .../status.

실행:
    pytest tests/test_generation_progress.py -v
"""
import datetime
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


def test_status_reports_notice_closed_but_does_not_block(authed_client, db_session):
    """[2026-09-27 신규, SB-139] 공식 기능정의서 v1.9 E-RUN-CLOSED — 이어하기로 돌아왔을
    때 선택 공고가 마감됐으면 notice_closed=true만 내려주고 실행 자체는 막지 않는다
    (마감 사실만 알리고 계속 진행할지는 사용자가 정한다)."""
    project_id = _matched_project(authed_client, db_session)
    status = authed_client.get(f'/projects/{project_id}/status').json()
    assert status['notice_closed'] is False, "모집중('open')인 공고는 마감이 아니어야 함"

    notice = db_session.query(Notice).filter_by(notice_id='NOTICE-GEN-1').one()
    notice.recruitment_status = 'closed'
    db_session.commit()

    status = authed_client.get(f'/projects/{project_id}/status').json()
    assert status['notice_closed'] is True
    # 마감돼도 실행 조회 자체는 막히지 않는다 — 계속 진행할지는 사용자가 정한다.
    assert status['stage'] is None  # 아직 계획서 작성을 시작 안 한 상태 그대로


def test_status_detects_closed_via_apply_end_even_if_status_stale(authed_client, db_session):
    """recruitment_status 갱신이 늦어도, apply_end가 지났으면 마감으로 판단해야 한다."""
    project_id = _matched_project(authed_client, db_session)
    notice = db_session.query(Notice).filter_by(notice_id='NOTICE-GEN-1').one()
    notice.apply_end = datetime.date.today() - datetime.timedelta(days=1)
    db_session.commit()

    status = authed_client.get(f'/projects/{project_id}/status').json()
    assert status['notice_closed'] is True
