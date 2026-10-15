"""탈퇴 중인 계정은 새 실행을 시작할 수 없다 (SB-298) — 명세 7.3: 탈퇴 처리 중에는 그 계정으로 request_start를 부르지 않는다.

탈퇴(DELETE /auth/me)가 BUSY로 멈췄다가 다시 불리는 사이에도 막혀야 하므로, 탈퇴를 시작하면 계정을 'withdrawing'으로 표시한다.
표시된 계정도 로그인 · 세션은 그대로여서(탈퇴를 이어서 해야 한다) 새 시작만 거절한다.

실행:
    pytest tests/test_account_withdrawing.py -v
"""
import json

import pytest
from orch_fakes import ProjectView, StartCheck, StartStatus

from app.models import Project, User
from app.orch import OrchError
from app.orch.mapping import START_RETRYABLE


def _calls(orch, name: str) -> list:
    return [c for c in orch.calls if c[0] == name]


def _mark_withdrawing(db_session) -> None:
    db_session.query(User).update({'status': 'withdrawing'})
    db_session.commit()


def _payload(description: str = '탈퇴 중 시작 테스트') -> dict:
    return {'payload': json.dumps({'description': description})}


def test_busy_withdrawal_marks_the_account_and_blocks_new_starts(authed_client, db_session, orch):
    first = authed_client.post('/projects', data=_payload('첫 프로젝트')).json()['project_id']
    orch.responses['delete_project_data'] = OrchError('BUSY', '단계 진행 중')

    res = authed_client.delete('/auth/me')

    assert res.status_code == 409 and res.json()['code'] == 'BUSY'
    db_session.expire_all()
    assert db_session.query(User).one().status == 'withdrawing'  # 다시 부르기 전에도 표시가 남는다

    starts, actives = len(_calls(orch, 'request_start')), len(_calls(orch, 'active_work'))
    res = authed_client.post('/projects', data=_payload('탈퇴 중 새 프로젝트'))

    assert res.status_code == 409
    assert res.json()['code'] == 'ACCOUNT_WITHDRAWING' and '탈퇴' in res.json()['detail']
    assert len(_calls(orch, 'request_start')) == starts and len(_calls(orch, 'active_work')) == actives  # 오케스트레이터를 부르지 않는다
    assert db_session.query(Project).count() == 1 and db_session.query(Project).one().project_id == first


def test_withdrawing_account_keeps_session_and_can_finish_withdrawal(authed_client, db_session, orch):
    authed_client.post('/projects', data=_payload())
    orch.responses['delete_project_data'] = OrchError('BUSY', '단계 진행 중')
    assert authed_client.delete('/auth/me').status_code == 409

    assert authed_client.get('/auth/me').status_code == 200            # 세션 그대로
    assert authed_client.get('/projects').status_code == 200           # 읽기도 그대로
    assert authed_client.post('/auth/refresh').status_code == 200      # 세션 갱신도 된다

    orch.responses['delete_project_data'] = lambda project_id: None
    orch.responses['delete_account_data'] = lambda account_id: None
    assert authed_client.delete('/auth/me').status_code == 204         # 다시 부르면 마친다
    db_session.expire_all()
    assert db_session.query(User).count() == 0


def test_withdrawing_account_can_sign_in_again(client, db_session, monkeypatch):
    """로그인이 막히면 BUSY로 멈춘 탈퇴를 이어서 할 방법이 없다."""
    from tests.test_auth_consent import _fake_login
    _fake_login(monkeypatch, 'withdrawing@example.com', 'sub-withdrawing')
    assert client.post('/auth/google', json={'id_token': 'dummy'}).status_code == 200
    _mark_withdrawing(db_session)

    assert client.post('/auth/google', json={'id_token': 'dummy'}).status_code == 200


def test_suspended_account_still_cannot_sign_in(client, db_session, monkeypatch):
    from tests.test_auth_consent import _fake_login
    _fake_login(monkeypatch, 'suspended@example.com', 'sub-suspended')
    client.post('/auth/google', json={'id_token': 'dummy'})
    db_session.query(User).update({'status': 'suspended'})
    db_session.commit()

    assert client.post('/auth/google', json={'id_token': 'dummy'}).status_code == 403


def test_withdrawal_starting_while_saving_is_caught_before_request_start(authed_client, db_session, orch):
    """저장하는 사이에 다른 요청에서 탈퇴가 시작됐다 — 시작 요청을 넣지 않고 방금 만든 프로젝트를 지운다."""
    def active_work_then_withdraw(account_id):
        _mark_withdrawing(db_session)
        return None
    orch.responses['active_work'] = active_work_then_withdraw

    res = authed_client.post('/projects', data=_payload())

    assert res.status_code == 409 and res.json()['code'] == 'ACCOUNT_WITHDRAWING'
    assert _calls(orch, 'request_start') == []
    db_session.expire_all()
    assert db_session.query(Project).count() == 0


def test_withdrawal_starting_during_request_start_pulls_the_request_back(authed_client, db_session, orch):
    """시작 요청을 넣는 사이에 탈퇴가 시작됐다 — 탈퇴가 끝난 뒤 남은 요청은 지워지지 않으므로 거두고 프로젝트를 지운다."""
    def request_start_then_withdraw(account_id, project_id):
        _mark_withdrawing(db_session)
        return StartCheck(ok=True, request_id='req-1')
    orch.responses['request_start'] = request_start_then_withdraw

    res = authed_client.post('/projects', data=_payload())

    assert res.status_code == 409 and res.json()['code'] == 'ACCOUNT_WITHDRAWING'
    aborted = _calls(orch, 'abort_project')
    assert len(aborted) == 1
    db_session.expire_all()
    assert db_session.query(Project).count() == 0


@pytest.mark.parametrize('withdrawing', [False, True])
def test_candidate_retry_does_not_resubmit_start_while_withdrawing(authed_client, db_session, orch, withdrawing):
    """시작 실패 뒤 후보를 다시 읽을 때 웹이 시작 요청을 다시 넣는 경로도 막는다."""
    project_id = authed_client.post('/projects', data=_payload()).json()['project_id']
    code = sorted(START_RETRYABLE)[0]
    failed = ProjectView('x', start=StartStatus(request_id='q1', status='실패', code=code, message='다시 시도'))
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: failed
    if withdrawing:
        _mark_withdrawing(db_session)
    before = len(_calls(orch, 'request_start'))

    body = authed_client.get(f'/projects/{project_id}/match-candidates').json()

    if withdrawing:
        assert body['status'] == 'failed' and body['code'] == 'ACCOUNT_WITHDRAWING'
        assert len(_calls(orch, 'request_start')) == before
    else:  # 비교용 — 탈퇴 중이 아니면 지금처럼 시작 요청을 다시 넣는다
        assert len(_calls(orch, 'request_start')) == before + 1
