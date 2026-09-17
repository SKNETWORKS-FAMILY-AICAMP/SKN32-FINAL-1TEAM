"""app/routers/biz_check.py — 마이페이지 사업자등록번호 자동 검증.

국세청 API를 실제로 호출하면 테스트가 네트워크·키에 의존하게 되므로
requests.post를 갈아치워서 검증한다(login_as가 verify_google_id_token을
갈아치우는 것과 같은 패턴).

실행:
    pytest tests/test_biz_check.py -v
"""
import app.routers.biz_check as biz_check


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _stub_nts_response(monkeypatch, payload, status_code=200):
    monkeypatch.setattr(
        biz_check.requests, 'post',
        lambda *args, **kwargs: _FakeResponse(status_code, payload),
    )


def test_biz_check_requires_login(client):
    res = client.post('/biz-check', json={'b_no': '1320557431'})
    assert res.status_code == 401


def test_biz_check_rejects_bad_format(authed_client):
    res = authed_client.post('/biz-check', json={'b_no': '123'})
    assert res.status_code == 400


def test_biz_check_active_business(monkeypatch, authed_client):
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
    body = res.json()
    assert body['valid'] is True
    assert body['label'] == '계속사업자'
    assert body['tax_type'] == '부가가치세 일반과세자'


def test_biz_check_unregistered_number(monkeypatch, authed_client):
    monkeypatch.setenv('NTS_SERVICE_KEY', 'pytest-dummy-key')
    _stub_nts_response(monkeypatch, {'request_cnt': 1, 'match_cnt': 0, 'data': []})
    res = authed_client.post('/biz-check', json={'b_no': '0000000000'})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['valid'] is False


def test_biz_check_upstream_error(monkeypatch, authed_client):
    monkeypatch.setenv('NTS_SERVICE_KEY', 'pytest-dummy-key')
    _stub_nts_response(monkeypatch, {}, status_code=500)
    res = authed_client.post('/biz-check', json={'b_no': '1320557431'})
    assert res.status_code == 502
