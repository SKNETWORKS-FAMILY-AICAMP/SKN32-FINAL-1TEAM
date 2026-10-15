"""GET /projects/notifications, PATCH /projects/notifications/{id}/read — SB-141.

실행:
    pytest tests/test_notifications.py -v
"""
import json
import time

import pytest

import app.routers.projects as projects_router
from app.models import Notice


@pytest.fixture(autouse=True)
def fast_generation(monkeypatch):
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.01)


def _matched_project(client, db_session, notice_id='NOTICE-NOTIF-1') -> int:
    db_session.add(Notice(notice_id=notice_id, source='kstartup', title='알림 테스트 공고', recruitment_status='open'))
    db_session.commit()
    payload = {'description': '알림 테스트용 아이템', 'team_members': [], 'pricing_items': []}
    project_id = client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']
    r = client.post(f'/projects/{project_id}/generate', json={'notice_id': notice_id})
    assert r.status_code == 200, r.text
    return project_id


def _monkeypatch_boom(monkeypatch, message='더미 에이전트 강제 실패(테스트)'):
    real_sleep = time.sleep

    def _boom(seconds):
        if seconds == projects_router.DUMMY_GENERATION_STEP_SECONDS:
            raise RuntimeError(message)
        real_sleep(seconds)

    monkeypatch.setattr(projects_router.time, 'sleep', _boom)


def test_doc_review_completion_creates_notification(authed_client, db_session):
    """[신규] 문서평가(검증-1)가 끝나 plan_review_pending에 도달하면 kind='문서평가'
    알림이 하나 생겨야 한다 — target_step은 화면 6."""
    project_id = _matched_project(authed_client, db_session)
    authed_client.post(f'/projects/{project_id}/plan/start')

    deadline = time.time() + 5
    notifications = []
    while time.time() < deadline:
        notifications = authed_client.get('/projects/notifications').json()
        if notifications:
            break
        time.sleep(0.02)

    assert len(notifications) == 1, notifications
    notif = notifications[0]
    assert notif['kind'] == '문서평가'
    assert notif['target_step'] == 6
    assert notif['failure_scope'] is None
    assert notif['read_at'] is None
    assert notif['project_id'] == project_id


def test_run_failure_creates_notification_with_run_scope(authed_client, db_session, monkeypatch):
    """[신규] 영구 오류(운영)로 즉시 실패하면 kind='실패', failure_scope='실행' 알림이
    생겨야 하고, target_step은 없어야 한다(이어하기 목록으로 연결)."""
    _monkeypatch_boom(monkeypatch, message='크레딧 소진(테스트)')
    project_id = _matched_project(authed_client, db_session, 'NOTICE-NOTIF-FAIL')
    authed_client.post(f'/projects/{project_id}/plan/start')

    deadline = time.time() + 5
    notifications = []
    while time.time() < deadline:
        notifications = authed_client.get('/projects/notifications').json()
        if notifications:
            break
        time.sleep(0.02)

    assert len(notifications) == 1, notifications
    notif = notifications[0]
    assert notif['kind'] == '실패'
    assert notif['failure_scope'] == '실행'
    assert notif['target_step'] is None


def test_unread_only_filter_and_mark_read(authed_client, db_session):
    project_id = _matched_project(authed_client, db_session)
    authed_client.post(f'/projects/{project_id}/plan/start')

    deadline = time.time() + 5
    notifications = []
    while time.time() < deadline:
        notifications = authed_client.get('/projects/notifications').json()
        if notifications:
            break
        time.sleep(0.02)
    notification_id = notifications[0]['notification_id']

    unread = authed_client.get('/projects/notifications', params={'unread_only': True}).json()
    assert len(unread) == 1

    res = authed_client.patch(f'/projects/notifications/{notification_id}/read', json={'read': True})
    assert res.status_code == 200, res.text
    assert res.json()['read_at'] is not None

    unread_after = authed_client.get('/projects/notifications', params={'unread_only': True}).json()
    assert unread_after == []

    # 다시 안읽음으로 되돌릴 수도 있다.
    res2 = authed_client.patch(f'/projects/notifications/{notification_id}/read', json={'read': False})
    assert res2.json()['read_at'] is None


def test_notifications_are_isolated_per_account(authed_client, db_session, login_as):
    project_id = _matched_project(authed_client, db_session)
    authed_client.post(f'/projects/{project_id}/plan/start')

    deadline = time.time() + 5
    notifications = []
    while time.time() < deadline:
        notifications = authed_client.get('/projects/notifications').json()
        if notifications:
            break
        time.sleep(0.02)
    notification_id = notifications[0]['notification_id']

    # [주의] login_as는 같은 TestClient의 세션 쿠키를 바꿔치기하는 방식이라(conftest.py),
    # 이후로는 authed_client도 other_client와 같은(2번 계정) 세션을 본다 — notification_id는
    # 반드시 전환 전에 미리 구해둬야 한다.
    other_client = login_as('other-notif@example.com')
    assert other_client.get('/projects/notifications').json() == []
    assert other_client.patch(f'/projects/notifications/{notification_id}/read', json={'read': True}).status_code == 404


def test_notifications_route_not_shadowed_by_project_id_route(authed_client, db_session):
    """[회귀] GET /projects/notifications가 GET /projects/{project_id}보다 라우터에
    먼저 등록돼 있어야 한다 — 안 그러면 "notifications"를 project_id로 파싱하려다
    422가 난다."""
    res = authed_client.get('/projects/notifications')
    assert res.status_code == 200, res.text
    assert res.json() == []
