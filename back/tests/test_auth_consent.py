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

    # [2026-09-27] 필수 동의(이용약관/개인정보)를 아직 완료하지 않았으므로, 신규가
    # 아니게 됐어도(is_new_user=False) has_agreed_terms는 여전히 False여야 한다 —
    # 예전엔 "신규가 아니면 True"였는데, 그러면 계정만 만들고 필수 동의 화면을
    # 실제로 완료하기 전에 이탈한 사용자가 재로그인할 때 동의 화면을 건너뛰는
    # 버그가 있었다.
    r2 = client.post('/auth/google', json={
        'id_token': 'dummy', 'aiTrainingAgreed': False, 'notifyAgreed': True,
    })
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2['is_new_user'] is False
    assert body2['has_agreed_terms'] is False
    assert body2['user']['ai_training_agreed'] is True   # 최초 가입 때 값(True) 그대로
    assert body2['user']['notify_enabled'] is False        # 최초 가입 때 값(False) 그대로

    # 필수 동의를 완료하면 그 다음부터는 has_agreed_terms가 True로 바뀐다.
    consent_res = client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True})
    assert consent_res.status_code == 200, consent_res.text
    r3 = client.post('/auth/google', json={'id_token': 'dummy'})
    assert r3.json()['has_agreed_terms'] is True


def test_patch_consent_revokes_required_consent_to_null(client, monkeypatch):
    """[2026-09-27 신규] false를 보내면 철회로 보고 NULL로 되돌아가야 한다
    (E-AUTH-CONSENT: "철회 이후 수집을 중단한다")."""
    _fake_login(monkeypatch, 'revoke@example.com', 'sub-revoke')
    client.post('/auth/google', json={'id_token': 'dummy'})

    r1 = client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True})
    assert r1.json()['terms_agreed_at'] is not None
    assert r1.json()['privacy_agreed_at'] is not None

    r2 = client.patch('/auth/consent', json={'termsAgreed': False})
    assert r2.json()['terms_agreed_at'] is None
    assert r2.json()['privacy_agreed_at'] is not None  # privacyAgreed는 안 건드렸으니 유지


def test_create_project_blocked_until_required_consent_completed(client, monkeypatch):
    """[2026-09-27 신규] 공식 기능정의서 v1.9 E-AUTH-CONSENT — 필수 동의를 마치기 전엔
    새 실행(POST /projects)을 시작할 수 없고, 완료하면 열려야 한다."""
    import json as json_module

    _fake_login(monkeypatch, 'gate@example.com', 'sub-gate')
    client.post('/auth/google', json={'id_token': 'dummy'})

    payload = json_module.dumps({'description': 'consent gate test'})
    r1 = client.post('/projects', data={'payload': payload})
    assert r1.status_code == 403, r1.text

    consent_res = client.patch('/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True})
    assert consent_res.status_code == 200

    r2 = client.post('/projects', data={'payload': payload})
    assert r2.status_code == 201, r2.text


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
