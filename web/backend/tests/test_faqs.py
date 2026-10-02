"""app/routers/faqs.py + users.ai_training_agreed 영속화 — pytest 버전.

설계 문서 3.3절(API·Agent 입출력-DB 스키마 정합성 점검)에서 "불일치(알려진 갭)"으로
지적됐던 두 가지가 실제로 해소됐는지 검증한다:
  1. FaqCreateRequest 스키마는 있었지만 그걸 쓰는 라우터가 없던 갭 -> POST/GET /faqs
  2. GoogleLoginRequest.ai_training_agreed 가 요청엔 들어오지만 DB에 저장되지 않던 갭
     -> users.ai_training_agreed 컬럼에 실제로 저장/갱신되는지

실행:
    pytest tests/test_faqs.py -v
"""
from app.models import Faq, User


def _new_client():
    # 다른 테스트 파일과 동일 패턴 — app.main을 모듈 최상단에서 import하면 pytest
    # 수집 단계에서 세션 fixture(_fresh_test_db)보다 먼저 init_sqlite_dev_db()가
    # 돌아 readonly database 에러가 난다(tests/test_admin.py 참고). 함수 안에서 지연 import.
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def _login(client, email, ai_training_agreed):
    import app.routers.auth as auth_router
    import app.security as security

    fake_sub = f'test-sub-{email}'
    security.verify_google_id_token = lambda id_token_str: {'sub': fake_sub, 'email': email, 'name': '테스트유저'}
    auth_router.verify_google_id_token = security.verify_google_id_token
    res = client.post('/auth/google', json={
        'id_token': 'dummy', 'aiTrainingAgreed': ai_training_agreed, 'notifyAgreed': True,
    })
    assert res.status_code == 200, res.text
    return res.json()['user']


def test_create_faq_persists_and_defaults_hidden(db_session):
    client = _new_client()
    _login(client, 'faq-writer@example.com', True)

    res = client.post('/faqs', json={'question': 'SQLite로도 개발할 수 있나요?'})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body['question'] == 'SQLite로도 개발할 수 있나요?'
    assert body['answer'] is None
    assert body['is_visible'] is False  # 관리자가 답변 저장 전까지는 비공개(DB 기본값)

    faq = db_session.query(Faq).filter(Faq.faq_id == body['faq_id']).one()
    writer = db_session.query(User).filter(User.email == 'faq-writer@example.com').one()
    assert faq.user_id == writer.user_id  # 질문이 로그인한 유저 본인 것으로 저장됐는지


def test_create_faq_requires_login(db_session):
    client = _new_client()
    res = client.post('/faqs', json={'question': '로그인 안 하고 질문해도 되나요?'})
    assert res.status_code == 401


def test_list_faqs_only_shows_visible(db_session):
    client = _new_client()
    _login(client, 'faq-reader@example.com', True)

    hidden = Faq(user_id=db_session.query(User).filter(User.email == 'faq-reader@example.com').one().user_id,
                 question='아직 비공개 질문', answer=None, is_visible=False)
    visible = Faq(user_id=hidden.user_id, question='공개된 질문', answer='공개된 답변', is_visible=True)
    db_session.add_all([hidden, visible])
    db_session.commit()

    res = client.get('/faqs')
    assert res.status_code == 200
    questions = [f['question'] for f in res.json()]
    assert '공개된 질문' in questions
    assert '아직 비공개 질문' not in questions


def test_list_faqs_works_without_login(db_session):
    # 공개 FAQ 목록은 로그인 여부와 무관하게 조회 가능해야 한다.
    client = _new_client()
    res = client.get('/faqs')
    assert res.status_code == 200
    assert res.json() == []


def test_ai_training_agreed_persisted_on_signup(db_session):
    client = _new_client()
    _login(client, 'consent-yes@example.com', True)

    user = db_session.query(User).filter(User.email == 'consent-yes@example.com').one()
    assert user.ai_training_agreed is True


def test_ai_training_agreed_survives_relogin_and_changes_only_via_patch(db_session):
    """[2026-09-15 개정] 예전엔 재로그인할 때마다 body의 동의값으로 덮어썼는데(그래서
    이 테스트 이름도 원래 '...updates_on_relogin'이었다) — 그러면 프론트가 재로그인 시
    동의 화면을 건너뛰고 기본값을 보내는 순간 이미 저장해둔 동의가 조용히 꺼져버리는
    문제가 있었다. 이제 재로그인은 저장된 값을 그대로 두고, 바꾸려면 PATCH /auth/consent를
    명시적으로 호출해야 한다."""
    client = _new_client()
    first = _login(client, 'consent-changes@example.com', True)
    assert first['ai_training_agreed'] is True

    # 같은 계정으로 다른 값(False)을 실어 다시 로그인해도 기존 값(True)이 유지돼야 한다.
    second = _login(client, 'consent-changes@example.com', False)
    assert second['ai_training_agreed'] is True

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == 'consent-changes@example.com').one()
    assert user.ai_training_agreed is True

    # 동의를 실제로 철회하려면 PATCH /auth/consent를 써야 한다.
    res = client.patch('/auth/consent', json={'aiTrainingAgreed': False})
    assert res.status_code == 200, res.text
    assert res.json()['ai_training_agreed'] is False
    db_session.expire_all()
    user = db_session.query(User).filter(User.email == 'consent-changes@example.com').one()
    assert user.ai_training_agreed is False
