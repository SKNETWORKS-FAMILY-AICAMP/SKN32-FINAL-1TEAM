"""app/routers/profile.py — 마이페이지 프로필 저장/조회(SB-59 v2, 슬롯형) pytest 버전.

authed_client fixture(conftest.py)와 test_biz_check.py의 requests.post 바꿔치기 방식을
그대로 쓴다.

실행:
    pytest tests/test_profile.py -v
"""
import app.routers.biz_check as biz_check
from app.models import UserProfile
from app.schemas import MAX_PROFILES

_SAMPLE_BODY = {
    'name': '정보 1',
    'basic': {
        'applicantType': 'individual', 'ceoName': '홍길동', 'birthDate': '1995-04-30', 'gender': '남성',
        'region': {'sido': '대전광역시', 'sigungu': '유성구'}, 'industry': '응용 소프트웨어 개발',
        'certs': ['벤처기업', '노란우산공제'],
        'bizNo': '132-05-57431', 'openedAt': '2025-05-12',
        'selfFunding': True, 'selfFundingMin': '5,000,000', 'selfFundingMax': '10,000,000',
    },
    'capability': {
        'careers': [{'type': '경력', 'title': '○○전자 · 백엔드 개발', 'period': '2019.03 – 2023.10', 'hasProof': True}],
        'skills': '…', 'soloFounder': False,
        'team': [{'name': '김개발', 'role': 'CTO', 'career': 'AI 엔지니어 5년', 'status': '재직 중'}],
        'hires': [{'job': '프론트엔드 개발', 'count': '1명', 'skill': 'React 3년', 'when': '2027-03'}],
        'equipment': [{'name': 'GPU 서버', 'status': '보유'}],
        'partners': [{'name': '○○대학 · 실증 지원', 'status': '협력 중'}],
    },
}


def _stub_nts_response(monkeypatch, payload, status_code=200):
    class _FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    monkeypatch.setattr(
        biz_check.requests, 'post',
        lambda *args, **kwargs: _FakeResponse(status_code, payload),
    )


def test_profile_requires_login(client):
    res = client.get('/profile')
    assert res.status_code == 401
    res = client.post('/profile', json=_SAMPLE_BODY)
    assert res.status_code == 401


def test_list_profiles_empty_for_unsaved_account(authed_client):
    res = authed_client.get('/profile')
    assert res.status_code == 200, res.text
    assert res.json() == []


def test_create_then_list_returns_saved_slot(authed_client):
    res = authed_client.post('/profile', json=_SAMPLE_BODY)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created['name'] == '정보 1'
    assert created['basic']['ceoName'] == '홍길동'
    assert created['basic']['region']['sido'] == '대전광역시'
    assert created['capability']['team'][0]['name'] == '김개발'
    assert created['bizStatus'] is None

    res = authed_client.get('/profile')
    assert res.status_code == 200, res.text
    listed = res.json()
    assert len(listed) == 1
    assert listed[0] == created


def test_create_up_to_max_profiles_then_409(authed_client):
    for _ in range(MAX_PROFILES):
        res = authed_client.post('/profile', json=_SAMPLE_BODY)
        assert res.status_code == 201, res.text

    res = authed_client.post('/profile', json=_SAMPLE_BODY)
    assert res.status_code == 409, res.text


def test_put_updates_existing_slot(authed_client):
    profile_id = authed_client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']

    updated = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], ceoName='김철수'))
    res = authed_client.put(f'/profile/{profile_id}', json=updated)
    assert res.status_code == 200, res.text
    assert res.json()['basic']['ceoName'] == '김철수'


def test_put_unknown_profile_returns_404(authed_client):
    res = authed_client.put('/profile/999999', json=_SAMPLE_BODY)
    assert res.status_code == 404


def test_delete_profile_removes_row(db_session, authed_client):
    profile_id = authed_client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']
    res = authed_client.delete(f'/profile/{profile_id}')
    assert res.status_code == 204

    assert db_session.query(UserProfile).count() == 0
    assert authed_client.get('/profile').json() == []


def test_other_account_profile_is_isolated(login_as):
    # login_as는 같은 TestClient의 세션 쿠키를 계정마다 바꿔치기하는 방식이라(conftest.py),
    # A로 로그인해 생성까지 마친 뒤에 B로 전환해야 두 계정이 실제로 분리된다.
    client = login_as('profile-a@example.com')
    profile_id = client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']

    client = login_as('profile-b@example.com')
    assert client.get('/profile').json() == []
    assert client.put(f'/profile/{profile_id}', json=_SAMPLE_BODY).status_code == 404
    assert client.delete(f'/profile/{profile_id}').status_code == 404


def test_put_ignores_biz_status_in_body(authed_client):
    profile_id = authed_client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']
    body = dict(_SAMPLE_BODY, bizStatus={
        'valid': True, 'b_stt_cd': '01', 'label': '계속사업자',
        'tax_type': '부가가치세 일반과세자', 'checkedNo': '132-05-57431',
    })
    res = authed_client.put(f'/profile/{profile_id}', json=body)
    assert res.status_code == 200, res.text
    assert res.json()['bizStatus'] is None  # 실제 /biz-check를 거치지 않았으면 여전히 null


def test_biz_check_with_profile_id_fills_biz_status_on_get(monkeypatch, authed_client):
    profile_id = authed_client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']
    monkeypatch.setenv('NTS_SERVICE_KEY', 'pytest-dummy-key')
    _stub_nts_response(monkeypatch, {
        'request_cnt': 1, 'match_cnt': 1, 'status_code': 'OK',
        'data': [{
            'b_no': '1320557431', 'b_stt': '계속사업자', 'b_stt_cd': '01',
            'tax_type': '부가가치세 일반과세자', 'tax_type_cd': '01',
        }],
    })
    res = authed_client.post('/biz-check', json={'b_no': '132-05-57431', 'profile_id': profile_id})
    assert res.status_code == 200, res.text

    res = authed_client.get('/profile')
    assert res.status_code == 200, res.text
    biz_status = res.json()[0]['bizStatus']
    assert biz_status is not None
    assert biz_status['valid'] is True
    assert biz_status['label'] == '계속사업자'
    assert biz_status['tax_type'] == '부가가치세 일반과세자'
    assert biz_status['checkedNo'] == '132-05-57431'  # 하이픈 형식으로 내려와야 함


def test_biz_check_without_profile_id_does_not_touch_any_slot(monkeypatch, authed_client, db_session):
    profile_id = authed_client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']
    monkeypatch.setenv('NTS_SERVICE_KEY', 'pytest-dummy-key')
    _stub_nts_response(monkeypatch, {
        'request_cnt': 1, 'match_cnt': 1, 'status_code': 'OK',
        'data': [{
            'b_no': '1320557431', 'b_stt': '계속사업자', 'b_stt_cd': '01',
            'tax_type': '부가가치세 일반과세자', 'tax_type_cd': '01',
        }],
    })
    res = authed_client.post('/biz-check', json={'b_no': '132-05-57431'})
    assert res.status_code == 200, res.text
    assert res.json()['valid'] is True  # 조회 자체는 되지만

    row = db_session.get(UserProfile, profile_id)
    db_session.refresh(row)
    assert row.biz_checked_no is None  # 어느 슬롯에도 저장 안 됨


def test_biz_check_rejects_profile_id_of_other_account(monkeypatch, login_as):
    client = login_as('biz-owner@example.com')
    profile_id = client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']

    other = login_as('biz-stranger@example.com')
    monkeypatch.setenv('NTS_SERVICE_KEY', 'pytest-dummy-key')
    _stub_nts_response(monkeypatch, {
        'request_cnt': 1, 'match_cnt': 1, 'status_code': 'OK',
        'data': [{'b_no': '1320557431', 'b_stt': '계속사업자', 'b_stt_cd': '01', 'tax_type': '부가가치세 일반과세자', 'tax_type_cd': '01'}],
    })
    res = other.post('/biz-check', json={'b_no': '132-05-57431', 'profile_id': profile_id})
    assert res.status_code == 404


def test_put_different_biz_no_clears_checked_result(monkeypatch, authed_client):
    profile_id = authed_client.post('/profile', json=_SAMPLE_BODY).json()['profile_id']
    monkeypatch.setenv('NTS_SERVICE_KEY', 'pytest-dummy-key')
    _stub_nts_response(monkeypatch, {
        'request_cnt': 1, 'match_cnt': 1, 'status_code': 'OK',
        'data': [{
            'b_no': '1320557431', 'b_stt': '계속사업자', 'b_stt_cd': '01',
            'tax_type': '부가가치세 일반과세자', 'tax_type_cd': '01',
        }],
    })
    authed_client.post('/biz-check', json={'b_no': '132-05-57431', 'profile_id': profile_id})
    res = authed_client.get('/profile')
    assert res.json()[0]['bizStatus'] is not None  # 사전 조건: 채워져 있어야 함

    other_body = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], bizNo='999-88-77776'))
    res = authed_client.put(f'/profile/{profile_id}', json=other_body)
    assert res.status_code == 200, res.text
    assert res.json()['bizStatus'] is None

    res = authed_client.get('/profile')
    assert res.json()[0]['bizStatus'] is None


def test_invalid_applicant_type_returns_422(authed_client):
    bad_body = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], applicantType='abc'))
    res = authed_client.post('/profile', json=bad_body)
    assert res.status_code == 422


def test_invalid_date_format_returns_422(authed_client):
    bad_body = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], birthDate='1995/04/30'))
    res = authed_client.post('/profile', json=bad_body)
    assert res.status_code == 422


def test_budget_scale_over_2000_returns_422(authed_client):
    bad_body = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], applicantType='preliminary', budgetScale='2500'))
    res = authed_client.post('/profile', json=bad_body)
    assert res.status_code == 422


def test_budget_scale_non_numeric_returns_422(authed_client):
    bad_body = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], applicantType='preliminary', budgetScale='abc'))
    res = authed_client.post('/profile', json=bad_body)
    assert res.status_code == 422


def test_budget_scale_at_cap_is_accepted(authed_client):
    ok_body = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], applicantType='preliminary', budgetScale='2000'))
    res = authed_client.post('/profile', json=ok_body)
    assert res.status_code == 201, res.text


# ============================================================================
# has_profile (GET /auth/me, POST /auth/google) — 정재희님 인계서 "필수 입력 항목" 기준
# ============================================================================

def test_has_profile_false_when_no_profile_saved(authed_client):
    assert authed_client.get('/auth/me').json()['has_profile'] is False


def test_has_profile_true_once_all_required_fields_saved(authed_client):
    authed_client.post('/profile', json=_SAMPLE_BODY)
    assert authed_client.get('/auth/me').json()['has_profile'] is True


def test_has_profile_false_when_only_applicant_type_filled(authed_client):
    # 인계서 지적: "신청자 유형만 채우고 나머지는 비워둔 계정" → has_profile: false
    thin_basic = {**_SAMPLE_BODY['basic']}
    for key in ('ceoName', 'birthDate', 'gender', 'industry', 'bizNo'):
        thin_basic[key] = ''
    thin_basic['region'] = {'sido': '', 'sigungu': ''}
    thin_body = {'name': '정보 1', 'basic': thin_basic, 'capability': {**_SAMPLE_BODY['capability'], 'careers': []}}
    authed_client.post('/profile', json=thin_body)
    assert authed_client.get('/auth/me').json()['has_profile'] is False


def test_has_profile_false_for_biz_type_missing_biz_no(authed_client):
    # individual/corp인데 사업자번호가 빈 경우 — 나머지 필수 항목은 다 채워도 false여야 함.
    body = dict(_SAMPLE_BODY, basic=dict(_SAMPLE_BODY['basic'], bizNo=''))
    authed_client.post('/profile', json=body)
    assert authed_client.get('/auth/me').json()['has_profile'] is False
