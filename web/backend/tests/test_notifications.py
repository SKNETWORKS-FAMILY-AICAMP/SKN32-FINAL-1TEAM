"""GET /projects/notifications, PATCH /projects/notifications/{id}/read — SB-141.

[SB-243] 알림 행은 이제 워커(오케스트레이터)가 notifications 테이블에 INSERT한다(명세 4.4). 웹은 목록을 읽고
read_at만 갱신하므로, 여기서는 행을 직접 심어 두고 두 엔드포인트의 동작만 확인한다.

실행:
    pytest tests/test_notifications.py -v
"""
import json

from app.models import Notification


def _project_id(client) -> int:
    payload = {'description': '알림 테스트용 아이템', 'team_members': [], 'pricing_items': []}
    return client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']


def _add_notification(db_session, project_id, **overrides) -> int:
    row = Notification(project_id=project_id, **{'kind': '문서평가', 'target_step': 6, **overrides})
    db_session.add(row)
    db_session.commit()
    return row.notification_id


def test_lists_notifications_written_by_the_worker(authed_client, db_session):
    project_id = _project_id(authed_client)
    _add_notification(db_session, project_id)

    notifications = authed_client.get('/projects/notifications').json()

    assert len(notifications) == 1
    notif = notifications[0]
    assert notif['kind'] == '문서평가'
    assert notif['target_step'] == 6
    assert notif['failure_scope'] is None
    assert notif['read_at'] is None
    assert notif['project_id'] == project_id


def test_run_failure_notification_has_run_scope_and_no_target_step(authed_client, db_session):
    project_id = _project_id(authed_client)
    _add_notification(db_session, project_id, kind='실패', failure_scope='실행', target_step=None)

    notif = authed_client.get('/projects/notifications').json()[0]

    assert notif['kind'] == '실패' and notif['failure_scope'] == '실행' and notif['target_step'] is None


def test_unread_only_filter_and_mark_read(authed_client, db_session):
    project_id = _project_id(authed_client)
    notification_id = _add_notification(db_session, project_id)

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
    project_id = _project_id(authed_client)
    notification_id = _add_notification(db_session, project_id)

    # [주의] login_as는 같은 TestClient의 세션 쿠키를 바꿔치기하는 방식이라(conftest.py),
    # 이후로는 authed_client도 other_client와 같은(2번 계정) 세션을 본다.
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
