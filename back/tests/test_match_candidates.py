"""GET /projects/{id}/match-candidates, POST .../match-candidates/rematch.

실행:
    pytest tests/test_match_candidates.py -v
"""
import pytest

from app.models import Notice
from tests.test_projects import _create_project, _login, _new_client

USER_EMAIL = 'match-candidates-test@example.com'


@pytest.fixture()
def user_client(db_session):
    uc = _new_client()
    _login(uc, USER_EMAIL, '매칭후보테스트유저')
    return uc


@pytest.fixture()
def notices(db_session):
    db_session.add_all([
        Notice(notice_id=f'N-{i:02d}', source='kstartup', title=f'테스트 공고 {i}', recruitment_status='open')
        for i in range(25)
    ])
    db_session.commit()


def test_first_call_returns_ten_and_is_stable(user_client, notices):
    project_id = _create_project(user_client)
    first = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert len(first['candidates']) == 10
    assert first['rematch_used'] is False
    assert {c['batch'] for c in first['candidates']} == {1}

    again = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert again == first


def test_rematch_adds_ten_new_and_keeps_previous(user_client, notices):
    project_id = _create_project(user_client)
    first = user_client.get(f'/projects/{project_id}/match-candidates').json()['candidates']

    res = user_client.post(f'/projects/{project_id}/match-candidates/rematch')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['rematch_used'] is True
    old = [c for c in body['candidates'] if c['batch'] == 1]
    new = [c for c in body['candidates'] if c['batch'] == 2]
    assert len(new) == 10
    assert {c['notice_id'] for c in old} == {c['notice_id'] for c in first}
    assert not {c['notice_id'] for c in old} & {c['notice_id'] for c in new}


def test_rematch_only_once_even_after_reload(user_client, notices):
    project_id = _create_project(user_client)
    user_client.get(f'/projects/{project_id}/match-candidates')
    assert user_client.post(f'/projects/{project_id}/match-candidates/rematch').status_code == 200

    reloaded = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert reloaded['rematch_used'] is True
    assert len(reloaded['candidates']) == 20
    assert user_client.post(f'/projects/{project_id}/match-candidates/rematch').status_code == 409


def test_rematch_before_first_match_is_rejected(user_client, notices):
    project_id = _create_project(user_client)
    assert user_client.post(f'/projects/{project_id}/match-candidates/rematch').status_code == 400
