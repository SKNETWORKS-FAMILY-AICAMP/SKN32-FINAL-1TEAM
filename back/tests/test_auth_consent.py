"""[2026-09-15] POST /auth/google의 has_agreed_terms/is_new_user 계산과, 기존 유저
재로그인 시 동의값을 더 이상 덮어쓰지 않는지, PATCH /auth/consent로 동의값을 바꿀 수
있는지 확인한다. — "한 번 동의하면 다시 안 물어봐야 하는데 왜 자꾸 뜨냐"는 버그 리포트의
원인(응답의 has_agreed_terms가 무조건 True로 고정돼 있어 프론트가 못 썼던 것 + 재로그인마다
body 값으로 동의를 덮어쓰던 것)을 고친 회귀 테스트."""


def _fake_login(monkeypatch, email: str, sub: str):
    import app.routers.auth as auth_router
    import app.security as security

    fake = lambda id_token_str: {'sub': sub, 'email': email, 'name': '동의테스트'}  # noqa: E731
    monkeypatch.setattr(security, 'verify_google_id_token', fake)
    monkeypatch.setattr(auth_router, 'verify_google_id_token', fake)


def test_first_login_is_new_user_and_uses_submitted_consent(client, monkeypatch):
    _fake_login(monkeypatch, 'newbie@example.com', 'sub-newbie')
    res = client.post('/auth/google', json={
        'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': False,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['is_new_user'] is True
    assert body['has_agreed_terms'] is False  # 방금 막 가입 -> "이전부터 동의돼 있던 상태"는 아님
    assert body['user']['ai_training_agreed'] is True
    assert body['user']['notify_enabled'] is False


def test_second_login_is_not_new_and_keeps_stored_consent(client, monkeypatch):
    _fake_login(monkeypatch, 'returning@example.com', 'sub-returning')
    r1 = client.post('/auth/google', json={
        'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': False,
    })
    assert r1.status_code == 200
    assert r1.json()['is_new_user'] is True

    # 재로그인 — 이번엔 body에 정반대 값을 보내도(예: 프론트가 기본값으로 다시 보내는 경우)
    # 기존에 저장된 동의값이 그대로 유지돼야 한다(예전 버그: 여기서 덮어써버림).
    r2 = client.post('/auth/google', json={
        'id_token': 'dummy', 'aiTrainingAgreed': False, 'notifyAgreed': True,
    })
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2['is_new_user'] is False
    assert body2['has_agreed_terms'] is True
    assert body2['user']['ai_training_agreed'] is True   # 최초 가입 때 값(True) 그대로
    assert body2['user']['notify_enabled'] is False        # 최초 가입 때 값(False) 그대로


def test_patch_consent_updates_only_provided_fields(client, monkeypatch):
    _fake_login(monkeypatch, 'consent-patch@example.com', 'sub-consent-patch')
    r1 = client.post('/auth/google', json={
        'id_token': 'dummy', 'aiTrainingAgreed': False, 'notifyAgreed': False,
    })
    assert r1.json()['user']['ai_training_agreed'] is False
    assert r1.json()['user']['notify_enabled'] is False

    # ai_training_agreed만 바꾸고 notify_agreed는 안 보냄 -> notify_enabled는 그대로 False 유지
    r2 = client.patch('/auth/consent', json={'aiTrainingAgreed': True})
    assert r2.status_code == 200, r2.text
    assert r2.json()['ai_training_agreed'] is True
    assert r2.json()['notify_enabled'] is False

    r3 = client.patch('/auth/consent', json={'notifyAgreed': True})
    assert r3.status_code == 200
    assert r3.json()['ai_training_agreed'] is True   # 앞서 바꾼 값 유지
    assert r3.json()['notify_enabled'] is True


def test_login_rejects_google_account_without_email(client, monkeypatch):
    """[2026-09-18] users.email이 NOT NULL이라, 이메일 없는 구글 계정으로 로그인하면
    예전엔 여기가 아니라 DB INSERT에서 알 수 없는 500으로 죽었다 — 명확한 4xx로 막는다."""
    import app.routers.auth as auth_router
    import app.security as security

    fake = lambda id_token_str: {'sub': 'sub-no-email', 'name': '이메일없음'}  # noqa: E731
    monkeypatch.setattr(security, 'verify_google_id_token', fake)
    monkeypatch.setattr(auth_router, 'verify_google_id_token', fake)

    res = client.post('/auth/google', json={'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True})
    assert res.status_code == 400, res.text


def test_patch_consent_requires_login(client):
    res = client.patch('/auth/consent', json={'aiTrainingAgreed': True})
    assert res.status_code == 401
