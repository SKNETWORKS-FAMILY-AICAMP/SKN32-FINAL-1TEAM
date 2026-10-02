"""conftest.py의 SQLite 스위치 인프라(fixture: client/login_as/authed_client/db_session)가
실제로 동작하는지 확인하는 최소한의 스모크 테스트.

지금 tests/ 아래엔 이 파일 말고 다른 test_*.py가 없다 — verify_retry_task.py 같은
기존 검증 스크립트들을 pytest로 옮기는 건 이번 범위가 아니라서(README/testing_guide.md
참고, 지금은 각 스크립트를 `python verify_xxx.py`로 직접 돌리는 방식을 그대로 쓴다),
conftest.py만 있고 test_*.py가 하나도 없으면 pytest가 "수집된 테스트 0개"로
exit code 5를 내서 CI가 그대로 빨간불이 된다 — 그래서 인프라 자체가 실제로 작동하는지
보여주는 용도로 최소한의 테스트 몇 개를 여기 둔다."""


def test_health(client):
    res = client.get('/health')
    assert res.status_code == 200
    assert res.json() == {'status': 'ok'}


def test_login_as_sets_session_cookie(authed_client):
    res = authed_client.get('/auth/me')
    assert res.status_code == 200
    assert res.json()['email'] == 'pytest-user@example.com'


def test_login_as_supports_multiple_accounts(login_as):
    client_a = login_as('a@example.com', name='에이')
    me_a = client_a.get('/auth/me')
    assert me_a.json()['email'] == 'a@example.com'

    client_b = login_as('b@example.com', name='비')
    me_b = client_b.get('/auth/me')
    assert me_b.json()['email'] == 'b@example.com'

    # 같은 TestClient(쿠키 저장소 공유)라 마지막에 로그인한 계정(b)의 쿠키가 남는다 —
    # login_as를 두 번 부르면 이전 계정으로는 더 이상 인증되지 않는다는 것까지 같이 확인.
    assert client_a is client_b


def test_db_session_is_isolated_between_tests(db_session):
    """이 테스트가 만든 유저가 다음 테스트로 안 새는지 확인 — 아래
    test_db_session_starts_empty가 그걸 검증한다(테스트 실행 순서는 파일 안에서는
    선언 순서를 따르므로, 이 테스트가 먼저 돈다)."""
    from app.models import User

    db_session.add(User(
        google_sub='leftover-sub', email='leftover@example.com', name='잔여유저',
        role='user', status='active',
    ))
    db_session.commit()
    assert db_session.query(User).count() == 1


def test_db_session_starts_empty(db_session):
    from app.models import User

    assert db_session.query(User).count() == 0, (
        '이전 테스트(test_db_session_is_isolated_between_tests)가 만든 행이 남아있음 — '
        'conftest.py의 db_session fixture가 테스트 간 정리를 제대로 안 하고 있다는 뜻'
    )
