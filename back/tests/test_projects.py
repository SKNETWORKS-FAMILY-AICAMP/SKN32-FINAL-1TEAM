"""app/routers/projects.py의 DELETE /projects/{id} — pytest 버전.

다른 테스트 파일과 같은 패턴(test_admin.py 참고)으로 완전히 독립적으로 구성한다.

실행:
    pytest tests/test_projects.py -v
"""
import json

import pytest
from fastapi.testclient import TestClient

import app.routers.auth as auth_router
import app.security as security
from app.models import MatchResult, Notice, Project
from seed_dummy_pipeline import seed_dummy_pipeline

USER_EMAIL = 'delete-test@example.com'


def _new_client() -> TestClient:
    # 다른 테스트 파일과 동일 패턴 — app.main 지연 import(test_admin.py 주석 참고).
    from app.main import app
    return TestClient(app)


def _login(client: TestClient, email: str, name: str) -> None:
    fake_sub = f'test-sub-{email}'
    security.verify_google_id_token = lambda id_token_str: {'sub': fake_sub, 'email': email, 'name': name}
    auth_router.verify_google_id_token = security.verify_google_id_token
    res = client.post('/auth/google', json={'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True})
    assert res.status_code == 200, f'로그인 실패({email}): {res.status_code} {res.text}'


def _create_project(client: TestClient, description: str = '삭제 테스트용 프로젝트') -> int:
    payload = {
        'start_type': '온라인', 'biz_type': 'AI 서비스', 'ceo_name': '삭제테스트유저',
        'description': description, 'notify_region': '서울', 'notify_industry': 'IT',
        'team_members': [], 'pricing_items': [],
    }
    res = client.post('/projects', data={'payload': json.dumps(payload)})
    assert res.status_code == 201, res.text
    return res.json()['project_id']


@pytest.fixture()
def user_client(db_session):
    uc = _new_client()
    _login(uc, USER_EMAIL, '삭제테스트유저')
    return uc


def test_delete_project_without_match_hard_deletes(user_client, db_session):
    """아직 공고 매칭 전(match_results 없음)이면 실제로 지워진다 — 목록에서도, DB에서도."""
    project_id = _create_project(user_client)

    listed = user_client.get('/projects').json()
    assert any(p['project_id'] == project_id for p in listed), '방금 만든 프로젝트가 목록에 없음'

    res = user_client.delete(f'/projects/{project_id}')
    assert res.status_code == 204, res.text

    listed_after = user_client.get('/projects').json()
    assert not any(p['project_id'] == project_id for p in listed_after), '삭제했는데 목록에 여전히 보임'

    db_session.expire_all()
    assert db_session.get(Project, project_id) is None, '매칭 전 프로젝트인데 DB에서 실제로 안 지워짐'


def test_delete_project_with_match_archives_instead_of_deleting(user_client, db_session):
    """매칭 이후(계획서·산출물 등 이미 생김)면 실제로 지우지 않고 보관 처리만 한다 —
    목록에서는 사라지지만(사용자 기준), DB에는 match_results.archived_at과 함께 남는다."""
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='DELETE-TEST-001', source='k-startup', title='삭제 테스트용 더미 공고', recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='DELETE-TEST-001', retry_agents=())
    db_session.commit()

    res = user_client.delete(f'/projects/{project_id}')
    assert res.status_code == 204, res.text

    listed_after = user_client.get('/projects').json()
    assert not any(p['project_id'] == project_id for p in listed_after), '보관 처리했는데 목록에 여전히 보임'

    db_session.expire_all()
    project = db_session.get(Project, project_id)
    assert project is not None, '매칭까지 된 프로젝트인데 실제로 지워짐 — 계획서/산출물 데이터가 같이 날아갔을 것'
    match = (
        db_session.query(MatchResult)
        .filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    assert match is not None and match.archived_at is not None, 'archived_at이 안 채워짐'
    assert match.archived_by == 'user'


def test_delete_project_requires_ownership(db_session):
    """남의 프로젝트는 지울 수 없다 — 404로 존재 자체를 숨긴다(_get_owned_project와 동일 정책)."""
    owner = _new_client()
    _login(owner, USER_EMAIL, '삭제테스트유저')
    project_id = _create_project(owner)

    other = _new_client()
    _login(other, 'someone-else@example.com', '다른유저')
    res = other.delete(f'/projects/{project_id}')
    assert res.status_code == 404, res.text
