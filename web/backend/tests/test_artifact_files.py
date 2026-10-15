"""GET /projects/{id}/artifact-files/{key} — 산출물 파일 내려 주기 (SB-292 · SB-315).

파일은 오케스트레이터의 파일 저장소에 있고, 웹은 결과의 파일 참조 key로 read_artifact_file을 불러 받는다(SB-311). 소유자만 받고(관리자도 못 받는다),
key의 뜻은 웹이 풀지 않는다 — 형식 · 내용은 오케스트레이터가 준 값 그대로다.

실행:
    pytest tests/test_artifact_files.py -v
"""
import json
from types import SimpleNamespace as NS

import pytest

from app.models import User
from app.orch import OrchError

KEY = 'r' * 12 + '/' + 'e' * 12 + '/' + 'u' * 8 + '/index.html'
HTML = '<!DOCTYPE html><html><head><title>반찬온</title></head><body><script>document.title="ok"</script></body></html>'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text x="1" y="5">인포그래픽</text></svg>'
PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(256))


def _file(data: bytes | str, media_type: str, name: str = 'index.html'):
    """오케스트레이터가 돌려주는 ArtifactFile(name · media_type · size · sha256 · data) 모양의 가짜."""
    raw = data.encode('utf-8') if isinstance(data, str) else data
    return NS(name=name, media_type=media_type, size=len(raw), sha256='0' * 64, data=raw)


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '파일 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _url(project_id, key=KEY):
    return f'/projects/{project_id}/artifact-files/{key}'


def _reads(orch):
    return [c for c in orch.calls if c[0] == 'read_artifact_file']


def test_owner_gets_the_html_with_safe_headers(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['read_artifact_file'] = lambda project_id, key: _file(HTML, 'text/html')

    r = authed_client.get(_url(pid))

    assert r.status_code == 200, r.text
    assert r.text == HTML
    assert r.headers['content-type'].startswith('text/html')
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert r.headers['cache-control'] == 'private, no-store'
    csp = r.headers['content-security-policy']
    assert 'sandbox allow-scripts' in csp and "default-src 'none'" in csp  # 직접 열어도 이 서버의 로그인 정보로 실행되지 않고 밖으로 나가지 못한다
    assert 'allow-same-origin' not in csp


def test_key_and_project_id_are_passed_through_untouched(authed_client, orch):
    """웹은 key의 뜻을 풀지 않고 그대로 넘긴다 — 프로젝트 번호는 숫자로."""
    pid = _create(authed_client)
    orch.responses['read_artifact_file'] = lambda project_id, key: _file(HTML, 'text/html')

    authed_client.get(_url(pid))

    assert _reads(orch) == [('read_artifact_file', (pid, KEY), {})]


def test_content_type_comes_from_the_orchestrator_not_the_key(authed_client, orch):
    """key가 .html로 끝나도 형식은 오케스트레이터가 기록한 값을 쓴다."""
    pid = _create(authed_client)
    orch.responses['read_artifact_file'] = lambda project_id, key: _file(SVG, 'image/svg+xml', 'onepage.svg')

    r = authed_client.get(_url(pid))

    assert r.headers['content-type'] == 'image/svg+xml' and r.text == SVG


def test_binary_file_is_served_byte_for_byte(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['read_artifact_file'] = lambda project_id, key: _file(PNG, 'image/png', 'infographic.png')

    r = authed_client.get(_url(pid, 'r/e/u/infographic.png'))

    assert r.status_code == 200 and r.content == PNG and r.headers['content-type'] == 'image/png'


def test_large_file_is_served_whole(authed_client, orch):
    """구현 Agent의 SVG는 맞춤 아이콘이 들어가 2.5MB쯤 된다."""
    pid = _create(authed_client)
    big = '<svg xmlns="http://www.w3.org/2000/svg"><!--' + ('x' * 2_500_000) + '--></svg>'
    orch.responses['read_artifact_file'] = lambda project_id, key: _file(big, 'image/svg+xml', 'infographic.svg')

    r = authed_client.get(_url(pid))

    assert r.status_code == 200 and len(r.content) == len(big.encode('utf-8'))


def test_other_users_cannot_download_and_the_orchestrator_is_not_asked(login_as, orch):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    orch.responses['read_artifact_file'] = lambda project_id, key: _file(HTML, 'text/html')
    assert owner.get(_url(pid)).status_code == 200
    reads_by_owner = len(_reads(orch))

    other = login_as('other@example.com')
    forbidden = other.get(_url(pid))
    orch.responses['read_artifact_file'] = OrchError('FILE_NOT_FOUND')
    owner_again = login_as('owner@example.com')
    missing = owner_again.get(_url(pid))

    assert forbidden.status_code == 404 and forbidden.json() == missing.json()  # 없는 파일과 같은 응답
    assert len(_reads(orch)) == reads_by_owner + 1                              # 주인이 아닌 사람의 요청은 오케스트레이터까지 가지 않는다


def test_admin_cannot_download_someone_elses_artifacts(login_as, db_session, orch):
    """기획서 6-7: 관리자 열람은 메타데이터로 한정 — 첨부 파일과 달리 산출물 내용은 관리자도 못 받는다."""
    owner = login_as('owner@example.com')
    pid = _create(owner)
    orch.responses['read_artifact_file'] = lambda project_id, key: _file(HTML, 'text/html')
    admin = login_as('admin@example.com')
    db_session.query(User).filter(User.email == 'admin@example.com').update({'role': 'admin'})
    db_session.commit()

    assert admin.get(_url(pid)).status_code == 404
    assert _reads(orch) == []


def test_requires_login(client, orch):
    assert client.get(_url(1)).status_code == 401
    assert _reads(orch) == []


@pytest.mark.parametrize('code, status', [
    ('FILE_NOT_FOUND', 404), ('RUN_NOT_FOUND', 404), ('FILE_STORE_UNAVAILABLE', 503), ('RUN_NOT_VIEWABLE', 409),
])
def test_orchestrator_errors_become_http_errors(authed_client, orch, code, status):
    pid = _create(authed_client)
    orch.responses['read_artifact_file'] = OrchError(code)

    r = authed_client.get(_url(pid))

    assert r.status_code == status
    assert code in r.text or status == 503  # 503은 내부 설정 문제라 코드 이름을 밖으로 내지 않는다(INTERNAL_ERROR)


def test_missing_file_message_does_not_reveal_the_key(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['read_artifact_file'] = OrchError('FILE_NOT_FOUND', KEY)

    r = authed_client.get(_url(pid))

    assert r.status_code == 404 and KEY not in r.text and 'index.html' not in r.text
