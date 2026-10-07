"""GET /projects/{id}/artifact-files/{시도 ID}/{파일} — 산출물 파일 내려 주기 (SB-292).

저장 위치와 이름 규칙은 app/artifact_store.py. 소유자만 받고(관리자도 못 받는다), 허용 이름 세 개와 정해진 폴더 구조의 파일만 열린다.

실행:
    pytest tests/test_artifact_files.py -v
"""
import json
import os

import pytest

from app import artifact_store
from app.models import User

ATTEMPT = '3f2a9c4d5e6f7a8b9c0d1e2f3a4b5c6d'
HTML = '<!DOCTYPE html><html><head><title>반찬온</title></head><body><script>document.title="ok"</script></body></html>'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text x="1" y="5">인포그래픽</text></svg>'


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """테스트마다 새 저장 폴더."""
    monkeypatch.setattr(artifact_store, 'ARTIFACT_DIR', str(tmp_path))
    return tmp_path


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '파일 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _put(store, project_id, filename, content, attempt=ATTEMPT):
    folder = store / str(project_id) / attempt
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text(content, encoding='utf-8')


def _url(project_id, filename, attempt=ATTEMPT):
    return f'/projects/{project_id}/artifact-files/{attempt}/{filename}'


def test_owner_gets_the_html_with_safe_headers(authed_client, store):
    pid = _create(authed_client)
    _put(store, pid, 'index.html', HTML)

    r = authed_client.get(_url(pid, 'index.html'))

    assert r.status_code == 200, r.text
    assert r.text == HTML
    assert r.headers['content-type'] == 'text/html; charset=utf-8'
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert r.headers['cache-control'] == 'private, no-store'
    csp = r.headers['content-security-policy']
    assert 'sandbox allow-scripts' in csp and "default-src 'none'" in csp  # 직접 열어도 이 서버의 로그인 정보로 실행되지 않고 밖으로 나가지 못한다
    assert 'allow-same-origin' not in csp


@pytest.mark.parametrize('filename', ['infographic.svg', 'onepage.svg'])
def test_svg_files_are_served_as_svg(authed_client, store, filename):
    pid = _create(authed_client)
    _put(store, pid, filename, SVG)

    r = authed_client.get(_url(pid, filename))

    assert r.status_code == 200 and r.text == SVG
    assert r.headers['content-type'] == 'image/svg+xml'


def test_large_file_is_served_whole(authed_client, store):
    """구현 Agent의 SVG는 맞춤 아이콘이 들어가 2.5MB쯤 된다."""
    pid = _create(authed_client)
    big = '<svg xmlns="http://www.w3.org/2000/svg"><!--' + ('x' * 2_500_000) + '--></svg>'
    _put(store, pid, 'infographic.svg', big)

    r = authed_client.get(_url(pid, 'infographic.svg'))

    assert r.status_code == 200 and len(r.content) == len(big.encode('utf-8'))


def test_other_users_cannot_download(login_as, store):
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _put(store, pid, 'index.html', HTML)

    assert owner.get(_url(pid, 'index.html')).status_code == 200
    other = login_as('other@example.com')
    r = other.get(_url(pid, 'index.html'))
    assert r.status_code == 404 and r.json()['detail'] == '파일을 찾을 수 없습니다'  # 없는 파일과 같은 응답


def test_admin_cannot_download_someone_elses_artifacts(login_as, db_session, store):
    """기획서 6-7: 관리자 열람은 메타데이터로 한정 — 첨부 파일과 달리 산출물 내용은 관리자도 못 받는다."""
    owner = login_as('owner@example.com')
    pid = _create(owner)
    _put(store, pid, 'index.html', HTML)
    admin = login_as('admin@example.com')
    db_session.query(User).filter(User.email == 'admin@example.com').update({'role': 'admin'})
    db_session.commit()

    assert admin.get(_url(pid, 'index.html')).status_code == 404


def test_requires_login(client, store):
    assert client.get(_url(1, 'index.html')).status_code == 401


@pytest.mark.parametrize('filename', ['secret.txt', 'index.HTML', 'README.md', 'prototype.html', 'index.html.bak', '.env'])
def test_only_the_three_names_are_served(authed_client, store, filename):
    pid = _create(authed_client)
    _put(store, pid, filename, 'x')

    assert authed_client.get(_url(pid, filename)).status_code == 404


@pytest.mark.parametrize('attempt', ['..', '.', 'a b', 'a/b', 'a' * 65, '%2e%2e', 'x.y'])
def test_attempt_id_must_be_a_plain_token(authed_client, store, attempt):
    pid = _create(authed_client)
    _put(store, pid, 'index.html', HTML)

    assert authed_client.get(f'/projects/{pid}/artifact-files/{attempt}/index.html').status_code in (404, 405)


def test_path_traversal_is_rejected(authed_client, store):
    pid = _create(authed_client)
    _put(store, pid, 'index.html', HTML)
    (store / 'outside.html').write_text('x', encoding='utf-8')

    for path in (f'/projects/{pid}/artifact-files/{ATTEMPT}/..%2f..%2foutside.html',
                 f'/projects/{pid}/artifact-files/..%2f{pid}%2f{ATTEMPT}/index.html',
                 f'/projects/{pid}/artifact-files/{ATTEMPT}/%2e%2e/%2e%2e/outside.html'):
        assert authed_client.get(path).status_code == 404, path


def test_missing_file_is_404(authed_client, store):
    pid = _create(authed_client)

    assert authed_client.get(_url(pid, 'index.html')).status_code == 404


def test_cannot_reach_another_projects_folder(login_as, store):
    """내 프로젝트 번호로 남의 프로젝트 폴더의 파일을 받을 수 없다."""
    their_pid = _create(login_as('theirs@example.com'))   # login_as는 같은 클라이언트의 로그인 계정을 바꾼다 — 순서대로 쓴다
    _put(store, their_pid, 'index.html', HTML)
    mine = login_as('mine@example.com')
    my_pid = _create(mine)

    assert mine.get(_url(my_pid, 'index.html')).status_code == 404       # 내 폴더에는 없다
    assert mine.get(_url(their_pid, 'index.html')).status_code == 404    # 남의 프로젝트 번호


def test_symlink_pointing_outside_the_project_folder_is_rejected(authed_client, store, tmp_path_factory):
    pid = _create(authed_client)
    outside = tmp_path_factory.mktemp('outside') / 'secret.html'
    outside.write_text('비밀', encoding='utf-8')
    folder = store / str(pid) / ATTEMPT
    folder.mkdir(parents=True)
    try:
        os.symlink(outside, folder / 'index.html')
    except (OSError, NotImplementedError):
        pytest.skip('이 환경에서는 심볼릭 링크를 만들 수 없음')

    assert authed_client.get(_url(pid, 'index.html')).status_code == 404


def test_each_attempt_has_its_own_folder_and_old_attempts_stay_reachable(authed_client, store):
    """재작성은 항상 새 시도 폴더에 쓰고 이전 파일은 남는다 — 두 시도의 파일을 각각 받을 수 있다."""
    pid = _create(authed_client)
    _put(store, pid, 'index.html', '<html>첫 시도</html>', attempt='a' * 32)
    _put(store, pid, 'index.html', '<html>재작성</html>', attempt='b' * 32)

    assert authed_client.get(_url(pid, 'index.html', attempt='a' * 32)).text == '<html>첫 시도</html>'
    assert authed_client.get(_url(pid, 'index.html', attempt='b' * 32)).text == '<html>재작성</html>'


def test_artifact_dir_defaults_under_uploads_and_can_be_overridden():
    import importlib

    assert artifact_store.ARTIFACT_DIR.replace('\\', '/').endswith('uploads/artifacts') or os.environ.get('ARTIFACT_DIR')
    os.environ['ARTIFACT_DIR'] = os.path.join(os.getcwd(), 'custom-artifacts')
    try:
        reloaded = importlib.reload(artifact_store)
        assert reloaded.ARTIFACT_DIR.endswith('custom-artifacts')
    finally:
        del os.environ['ARTIFACT_DIR']
        importlib.reload(artifact_store)


def test_directory_junction_pointing_outside_is_rejected(authed_client, store, tmp_path_factory):
    """시도 폴더가 저장 폴더 밖을 가리키는 링크여도 열리지 않는다(Windows는 심볼릭 링크 권한이 없어 권한이 필요 없는 정션으로 확인)."""
    import subprocess
    import sys

    pid = _create(authed_client)
    outside = tmp_path_factory.mktemp('outside_dir')
    (outside / 'index.html').write_text('비밀', encoding='utf-8')
    project_folder = store / str(pid)
    project_folder.mkdir(parents=True)
    link = project_folder / ATTEMPT
    try:
        if sys.platform == 'win32':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
        else:
            os.symlink(outside, link, target_is_directory=True)
    except (OSError, subprocess.CalledProcessError, NotImplementedError):
        pytest.skip('이 환경에서는 디렉터리 링크를 만들 수 없음')
    assert (link / 'index.html').is_file()  # 링크는 실제로 동작한다

    assert authed_client.get(_url(pid, 'index.html')).status_code == 404
