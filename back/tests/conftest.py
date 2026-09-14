"""pytest 전역 설정 — 테스트 스위트가 절대 팀 공유 AWS MySQL을 건드리지 않도록,
`app.*`가 처음 import되기 전에 DB_BACKEND=sqlite로 미리 정해둔다(개발용 dev.db와도
분리된 테스트 전용 SQLite 파일을 쓴다). verify_*.py 스크립트들이 각자 파일 맨 위에서
반복하던 "env var 먼저 세팅 -> IS_SQLITE 확인 -> 로그인 monkeypatch" 패턴을 pytest
전체가 공유하는 fixture로 정리한 것 — app/database.py 모듈 docstring이 말하는
"테스트 스위트의 pytest 방식"이 바로 이 파일이다.

pytest는 테스트 파일을 수집(import)하기 *전에* 같은 디렉터리의 conftest.py를 먼저
읽는다 — 그 성질을 이용한다. 그래서 os.environ을 건드리는 코드가 이 파일에서 어떤
`app.*`/`config` import보다도 먼저 나와야 한다(아래 import들에 달린 `# noqa: E402`는
그래서 나온 것 — config.py를 import 가능하게 하려면 repo 루트를 sys.path에 먼저
넣어야 하고, env var 세팅도 그보다 먼저여야 해서 표준적인 "파일 맨 위 import 블록"
순서를 지킬 수가 없다).
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_TEST_DB_PATH = os.path.join(_REPO_ROOT, 'test.db')

# verify_*.py와 똑같은 컨벤션: setdefault만 쓴다. 개발자 셸에 이미 DB_BACKEND=mysql
# 같은 게 export돼 있다면 그 값을 존중하고(여기서 강제로 덮어쓰지 않고), 대신 바로
# 아래 IS_SQLITE 체크에서 곧장 실패하게 만든다 — "모르고 진짜 공유 DB에 테스트를
# 돌렸다"가 조용히 넘어가는 것보다 시끄럽게 막는 쪽이 훨씬 안전하다.
os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('SQLITE_PATH', _TEST_DB_PATH)
os.environ.setdefault('GOOGLE_CLIENT_ID', 'pytest-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'pytest-dummy-secret-not-for-production')

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import IS_SQLITE  # noqa: E402

if not IS_SQLITE:
    raise RuntimeError(
        'pytest가 DB_BACKEND=sqlite가 아닌 상태로 실행되려고 합니다 — 이대로 두면 팀 공유 '
        'AWS MySQL에 테스트 데이터를 쓸 수 있어 여기서 중단합니다. 셸에 export된(또는 .env의) '
        'DB_BACKEND 값을 확인하세요.'
    )


@pytest.fixture(scope='session', autouse=True)
def _fresh_test_db():
    """세션(전체 pytest 실행) 시작 시 테스트 전용 SQLite 파일(test.db)을 지우고 새로
    만든다. 개발용 dev.db(seed_dummy_*.py로 수동으로 채워서 Swagger로 눈으로 확인하는
    용도)와는 완전히 다른 파일이라, pytest를 돌려도 그쪽 데이터는 안 건드린다."""
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)
    import app.models  # noqa: F401 -- Base.metadata에 테이블들을 등록시키기 위한 import
    from app.database import Base, engine
    Base.metadata.create_all(bind=engine)
    yield
    # 끝나고 파일은 일부러 안 지운다 — 실패한 테스트가 있으면 sqlite3 CLI 등으로
    # test.db를 직접 열어 무슨 값이 남았는지 확인해볼 수 있게. 다음 실행 시작 시
    # 위에서 다시 지우고 새로 만들어서, 이전 실행 잔재가 다음 실행에 안 새어든다.


@pytest.fixture()
def db_session():
    """테스트 함수 하나당 깨끗한 DB 상태를 보장한다. 매 테스트가 끝날 때마다 전체
    테이블을 비워서(스키마 자체는 세션 fixture가 이미 만들어둠) 테스트 간에 데이터가
    새지 않게 한다 — 실행 순서에 결과가 좌우되는 테스트를 방지."""
    from app.database import Base, SessionLocal, engine

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture()
def client(db_session):
    """인증 안 된 TestClient. db_session과 같은 엔진(SQLite 파일)을 보므로, 테스트
    안에서 db_session으로 미리 데이터를 심어두고 이 client로 호출해도 같은 DB를 본다."""
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def login_as(client):
    """호출할 때마다 이메일별로 로그인 처리된 TestClient를 돌려주는 팩토리.

    구글 ID 토큰 검증(app.security.verify_google_id_token)을 더미로 갈아치우고
    실제로 POST /auth/google을 호출해서 세션 쿠키까지 심어둔다 — verify_retry_task.py
    등 verify_*.py 스크립트들이 파일마다 반복하던 로그인 monkeypatch 패턴을 fixture로
    뽑아낸 것. app.routers.auth가 `from app.security import verify_google_id_token`로
    함수를 직접 이름 바인딩해 가져가기 때문에, security 모듈뿐 아니라 auth 라우터
    모듈의 이름도 같이 바꿔치기해야 실제로 먹힌다(둘 중 하나만 바꾸면 안 걸림).

    같은 프로세스 안에서 여러 계정을 번갈아 테스트해야 할 때(예: 소유권 체크, 계정당
    동시 실행 1건 제한)는 login_as('a@x.com'), login_as('b@x.com')처럼 여러 번 부르면
    된다."""
    import app.routers.auth as auth_router
    import app.security as security

    def _login(email: str = 'pytest-user@example.com', name: str = 'pytest유저'):
        fake_sub = f'test-sub-{email}'
        security.verify_google_id_token = lambda id_token_str: {
            'sub': fake_sub, 'email': email, 'name': name,
        }
        auth_router.verify_google_id_token = security.verify_google_id_token
        res = client.post('/auth/google', json={
            'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True,
        })
        assert res.status_code == 200, f'테스트 로그인 실패: {res.status_code} {res.text}'
        return client

    return _login


@pytest.fixture()
def authed_client(login_as):
    """가장 흔한 케이스 — 계정 하나로 로그인만 된 TestClient가 바로 필요할 때."""
    return login_as()
