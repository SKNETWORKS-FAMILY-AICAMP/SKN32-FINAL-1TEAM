"""산출물 경로 → 웹 주소 변환 (SB-293).

오케스트레이터는 저장 폴더 기준 상대 경로 `<project_id>/<시도 ID>/<파일>`을 주고, 웹은 `/projects/{id}/artifact-files/{시도 ID}/{파일}`로 바꿔 준다.

실행:
    pytest tests/test_artifact_urls.py -v
"""
import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from orch_fakes import make_outputs, make_plan_doc, make_score_view

from app import artifact_store
from app.artifact_store import artifact_url

ATTEMPT = '3f2a9c4d5e6f7a8b9c0d1e2f3a4b5c6d'


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, 'ARTIFACT_DIR', str(tmp_path))
    return tmp_path


def _url(pid, filename, attempt=ATTEMPT):
    return f'/projects/{pid}/artifact-files/{attempt}/{filename}'


# ── 변환 규칙 ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('filename', ['index.html', 'infographic.svg', 'onepage.svg'])
def test_relative_path_becomes_download_url(store, filename):
    assert artifact_url(7, f'7/{ATTEMPT}/{filename}') == _url(7, filename)


def test_windows_separators_and_dot_prefix_are_accepted(store):
    assert artifact_url(7, f'.\\7\\{ATTEMPT}\\index.html') == _url(7, 'index.html')
    assert artifact_url(7, f'./7/{ATTEMPT}/index.html') == _url(7, 'index.html')


def test_absolute_path_inside_the_artifact_folder_becomes_url(store):
    """조율이 저장 폴더를 넘기기 전에 구현 Agent가 공유 폴더 안에 절대 경로로 쓰는 경우."""
    absolute = os.path.join(str(store), '7', ATTEMPT, 'infographic.svg')
    assert artifact_url(7, absolute) == _url(7, 'infographic.svg')


@pytest.mark.parametrize('path', [
    None, '',                                                  # 비어 있으면 그대로
    '/uploads/p/index.html', '/u/a.html',                      # 옛 값
    'C:/somewhere/else/7/' + ATTEMPT + '/index.html',          # 저장 폴더 밖 절대 경로
    f'8/{ATTEMPT}/index.html',                                 # 다른 프로젝트 번호
    f'7/{ATTEMPT}/secret.txt',                                 # 허용 이름이 아님
    f'7/{ATTEMPT}/index.HTML',
    f'7/../{ATTEMPT}/index.html',                              # 상위 폴더
    f'7/{ATTEMPT}/../index.html',
    '7/a b/index.html',                                        # 시도 ID 모양이 아님
    f'7/{ATTEMPT}/sub/index.html',                             # 단계가 많음
    f'{ATTEMPT}/index.html',                                   # 단계가 적음
    'index.html',
    f'https://cdn.example.com/7/{ATTEMPT}/index.html',         # 이미 주소
    _url(7, 'index.html'),
])
def test_other_shapes_are_returned_unchanged(store, path):
    assert artifact_url(7, path) == path


def test_absolute_path_cannot_climb_out_of_the_folder(store):
    escaping = os.path.join(str(store), '7', '..', '..', '7', ATTEMPT, 'index.html')
    assert artifact_url(7, escaping) == escaping


# ── GET /result · GET /rework-result 응답에 적용 ──────────────────────────────────────
def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '주소 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _outputs(pid, category, prototype, infographic):
    report = make_score_view(total=82.0, threshold=80.0, passed=True)
    return make_outputs(
        step='결과물', progress='완료', category=category, plan_doc=make_plan_doc(),
        doc_score=NS(total=52.0, items=[]), document_score_report=make_score_view(with_artifact=False),
        overall_score_report=report, prototype=prototype, infographic=infographic)


def test_webdev_result_paths_are_urls(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs(
        pid, '웹개발', NS(entry_file_path=f'{pid}/{ATTEMPT}/index.html'), NS(image_path=f'{pid}/{ATTEMPT}/infographic.svg'))

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['executable_path'] == _url(pid, 'index.html')
    assert artifact['infographic_path'] == _url(pid, 'infographic.svg')


def test_onepage_result_shows_the_svg_as_infographic_and_hides_executable(authed_client, orch):
    """원페이지는 두 경로가 같은 onepage.svg — 인포그래픽만 보이고 실행 경로는 없다."""
    pid = _create(authed_client)
    same = f'{pid}/{ATTEMPT}/onepage.svg'
    orch.responses['outputs'] = lambda p: _outputs(pid, '원페이지', NS(entry_file_path=same), NS(image_path=same))

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['category'] == 'onepage'
    assert artifact['infographic_path'] == _url(pid, 'onepage.svg')
    assert artifact['executable_path'] is None


def test_legacy_paths_in_result_are_left_alone(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs(
        pid, '웹개발', NS(entry_file_path='/uploads/p/index.html'), NS(image_path='/uploads/p/info.png'))

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['executable_path'] == '/uploads/p/index.html'
    assert artifact['infographic_path'] == '/uploads/p/info.png'


def test_converted_url_is_downloadable_by_the_owner(authed_client, orch, store):
    """결과가 알려 준 주소를 그대로 요청하면 파일이 내려온다(SB-292와 이어진다)."""
    pid = _create(authed_client)
    folder = store / str(pid) / ATTEMPT
    folder.mkdir(parents=True)
    (folder / 'index.html').write_text('<html>ok</html>', encoding='utf-8')
    (folder / 'infographic.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding='utf-8')
    orch.responses['outputs'] = lambda p: _outputs(
        pid, '웹개발', NS(entry_file_path=f'{pid}/{ATTEMPT}/index.html'), NS(image_path=f'{pid}/{ATTEMPT}/infographic.svg'))
    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    html = authed_client.get(artifact['executable_path'])
    svg = authed_client.get(artifact['infographic_path'])

    assert html.status_code == 200 and html.text == '<html>ok</html>'
    assert svg.status_code == 200 and svg.headers['content-type'] == 'image/svg+xml'


def test_rework_result_file_paths_are_urls(authed_client, orch):
    pid = _create(authed_client)
    other = 'b' * 32
    orch.responses['rework_result'] = lambda p: NS(
        project_id=str(pid), run_id='r1', cycle_id='cyc-1', screen=6, bundles=['실행 파일'], status='완료',
        started_at=datetime(2026, 10, 6, 1, 0, tzinfo=UTC), ended_at=datetime(2026, 10, 6, 1, 5, tzinfo=UTC),
        kept='후', basis='artifact', before_score=50.0, after_score=58.0, before_refs=[], after_refs=[],
        plan_before=None, plan_after=None, rolled_back=False, refunded_bundles=[], notice_code=None,
        files=[NS(artifact='prototype', before_path=f'{pid}/{ATTEMPT}/index.html', after_path=f'{pid}/{other}/index.html')])

    body = authed_client.get(f'/projects/{pid}/rework-result').json()

    assert body['files'] == [{
        'artifact': 'prototype', 'before_path': _url(pid, 'index.html'), 'after_path': _url(pid, 'index.html', other)}]
    assert body['changed']['executable_path'] == {
        'before': _url(pid, 'index.html'), 'after': _url(pid, 'index.html', other)}
