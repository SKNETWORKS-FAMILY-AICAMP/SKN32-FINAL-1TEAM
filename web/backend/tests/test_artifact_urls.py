"""산출물 파일 참조(FileRef) → 웹 주소 변환 (SB-293 · SB-314).

오케스트레이터는 결과에 파일 참조(`key` 포함)만 싣고, 웹은 `/projects/{id}/artifact-files/{key}`로 바꿔 준다. key의 뜻은 풀지 않는다.

실행:
    pytest tests/test_artifact_urls.py -v
"""
import json
from datetime import UTC, datetime
from types import SimpleNamespace as NS

from orch_fakes import make_outputs, make_plan_doc, make_score_view

from app.orch.mapping import file_url

RUN, EXEC1, EXEC2, UNIQ = 'r' * 12, 'e' * 12, 'f' * 12, 'u' * 8


def _ref(name: str, execution: str = EXEC1):
    """오케스트레이터가 짓는 key 모양(<runId>/<executionId>/<고유값>/<name>)의 가짜 파일 참조."""
    return NS(key=f'{RUN}/{execution}/{UNIQ}/{name}', name=name)


def _url(pid, name, execution=EXEC1):
    return f'/projects/{pid}/artifact-files/{RUN}/{execution}/{UNIQ}/{name}'


# ── 변환 규칙 ─────────────────────────────────────────────────────────────────────────
def test_reference_becomes_download_url():
    assert file_url(7, _ref('index.html')) == _url(7, 'index.html')


def test_missing_reference_has_no_url():
    assert file_url(7, None) is None


# ── GET /result · GET /rework-result 응답에 적용 ──────────────────────────────────────
def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '주소 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _outputs(category, prototype, infographic):
    report = make_score_view(total=82.0, threshold=80.0, passed=True)
    return make_outputs(
        step='결과물', progress='완료', category=category, plan_doc=make_plan_doc(),
        doc_score=NS(total=52.0, items=[]), document_score_report=make_score_view(with_artifact=False),
        overall_score_report=report, prototype=prototype, infographic=infographic)


def test_webdev_result_references_are_urls(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs(
        '웹개발', NS(entry_file=_ref('index.html')), NS(image_file=_ref('infographic.svg')))

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['executable_path'] == _url(pid, 'index.html')
    assert artifact['infographic_path'] == _url(pid, 'infographic.svg')


def test_onepage_result_shows_the_svg_as_infographic_and_hides_executable(authed_client, orch):
    """원페이지는 두 참조가 같은 onepage.svg — 인포그래픽만 보이고 실행 경로는 없다."""
    pid = _create(authed_client)
    same = _ref('onepage.svg')
    orch.responses['outputs'] = lambda p: _outputs('원페이지', NS(entry_file=same), NS(image_file=same))

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['category'] == 'onepage'
    assert artifact['infographic_path'] == _url(pid, 'onepage.svg')
    assert artifact['executable_path'] is None


def test_webdev_without_entry_file_has_no_executable_path(authed_client, orch):
    """진입 파일이 없으면(entryFile = null) 실행 경로도 없다."""
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs('웹개발', NS(entry_file=None), NS(image_file=_ref('infographic.svg')))

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['executable_path'] is None
    assert artifact['infographic_path'] == _url(pid, 'infographic.svg')


def test_rework_result_file_references_are_urls(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['rework_result'] = lambda p: NS(
        project_id=str(pid), run_id='r1', cycle_id='cyc-1', screen=6, bundles=['실행 파일'], status='완료',
        started_at=datetime(2026, 10, 6, 1, 0, tzinfo=UTC), ended_at=datetime(2026, 10, 6, 1, 5, tzinfo=UTC),
        kept='후', basis='artifact', before_score=50.0, after_score=58.0, before_refs=[], after_refs=[],
        plan_before=None, plan_after=None, rolled_back=False, refunded_bundles=[], notice_code=None,
        files=[NS(artifact='prototype', before_file=_ref('index.html'), after_file=_ref('index.html', EXEC2))])

    body = authed_client.get(f'/projects/{pid}/rework-result').json()

    assert body['files'] == [{
        'artifact': 'prototype', 'before_path': _url(pid, 'index.html'), 'after_path': _url(pid, 'index.html', EXEC2)}]
    assert body['changed']['executable_path'] == {
        'before': _url(pid, 'index.html'), 'after': _url(pid, 'index.html', EXEC2)}


def test_onepage_without_infographic_shows_the_prototype_svg_as_infographic(authed_client, orch):
    """오케스트레이터가 원페이지의 인포그래픽을 비우고 prototype.entryFile만 보내도 같은 onepage.svg를 인포그래픽으로 보여 준다."""
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs('원페이지', NS(entry_file=_ref('onepage.svg')), None)

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['infographic_path'] == _url(pid, 'onepage.svg')
    assert artifact['executable_path'] is None


def test_webdev_without_infographic_keeps_an_empty_infographic_path(authed_client, orch):
    """웹개발은 인포그래픽이 따로 있어야 하므로 비어 있으면 실행 파일을 대신 쓰지 않는다."""
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs('웹개발', NS(entry_file=_ref('index.html')), None)

    artifact = authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]

    assert artifact['infographic_path'] == '' and artifact['executable_path'] == _url(pid, 'index.html')
