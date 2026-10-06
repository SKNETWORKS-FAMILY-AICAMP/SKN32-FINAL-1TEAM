"""[SB-244] 재작성 — POST /retry-task(접수) · GET /rework-result(전후 비교). 오케스트레이터 경유(가짜 gateway)."""
import json
from datetime import UTC, datetime
from types import SimpleNamespace as NS

from orch_fakes import ReworkAccepted, make_section

from app.orch import OrchError


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '재작성 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _accepted(**overrides):
    base = dict(project_id='1', run_id='r1', cycle_id='cyc-1', screen=6, bundles=['문제인식'],
                collect_until=datetime(2026, 10, 6, 1, 0, tzinfo=UTC))
    base.update(overrides)
    return ReworkAccepted(**base)


def _calls(orch, name):
    return [(args, kwargs) for n, args, kwargs in orch.calls if n == name]


def _retry(client, pid, task_key, bundle_id=None):
    body = {'task_key': task_key}
    if bundle_id is not None:
        body['bundle_id'] = bundle_id
    return client.post(f'/projects/{pid}/retry-task', json=body)


def test_retry_task_requests_rework_by_bundle_name(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['request_rework_for_project'] = lambda p, bundle: _accepted(bundles=[bundle])

    r = _retry(authed_client, pid, 'writing', '성장전략')

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['task_key'] == 'writing' and body['bundle_id'] == '성장전략'
    assert body['cycle_id'] == 'cyc-1' and body['screen'] == 6 and body['duplicate'] is False
    assert body['bundles'] == ['성장전략']
    assert body['collect_until'].startswith('2026-10-06T01:00:00')
    assert _calls(orch, 'request_rework_for_project') == [((pid, '성장전략'), {})]


def test_retry_task_maps_artifact_bundle_names(authed_client, orch):
    """웹의 task_key는 오케스트레이터 묶음 이름으로, 응답은 다시 웹 이름으로 바뀐다(실행 파일 ↔ 실행 파일 제작)."""
    pid = _create(authed_client)
    orch.responses['request_rework_for_project'] = lambda p, bundle: _accepted(
        screen=8, bundles=['문제인식', bundle])

    r = _retry(authed_client, pid, 'implement_prototype')

    assert r.status_code == 200, r.text
    assert r.json()['bundle_id'] == '실행 파일 제작'
    assert r.json()['bundles'] == ['문제인식', '실행 파일 제작']
    assert _calls(orch, 'request_rework_for_project') == [((pid, '실행 파일'), {})]

    r = _retry(authed_client, pid, 'implement_infographic')
    assert _calls(orch, 'request_rework_for_project')[-1] == ((pid, '인포그래픽'), {})


def test_retry_task_duplicate_bundle_in_same_collect_window(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['request_rework_for_project'] = lambda p, bundle: _accepted(duplicate=True)
    assert _retry(authed_client, pid, 'writing', '문제인식').json()['duplicate'] is True


def test_retry_task_rejects_non_reworkable_task_keys_and_bad_bundles(authed_client, orch):
    pid = _create(authed_client)
    for task_key, bundle_id in [
        ('strategy', None), ('verify1_rubric', None), ('review_token_check', None),   # 사용자 재작성 대상이 아니다
        ('writing', None), ('writing', '그래프 생성'),                                   # writing은 문서층 묶음 이름이 필요
        ('implement_prototype', '인포그래픽 제작'),                                      # 고정 묶음과 다름
        ('not_a_real_task', None),
    ]:
        r = _retry(authed_client, pid, task_key, bundle_id)
        assert r.status_code == 400, (task_key, bundle_id, r.text)
    assert _calls(orch, 'request_rework_for_project') == []


def test_retry_task_maps_orchestrator_errors(authed_client, orch):
    pid = _create(authed_client)
    for code, status in [('INVALID_STATE', 409), ('E-G2-LIMIT', 409), ('BUSY', 409), ('INVALID_ORDER', 422),
                         ('RUN_NOT_FOUND', 404)]:
        orch.responses['request_rework_for_project'] = OrchError(code, 'x')
        assert _retry(authed_client, pid, 'writing', '문제인식').status_code == status, code


def test_retry_task_requires_ownership(login_as, orch):
    pid = _create(login_as('owner@example.com'))
    other = login_as('other@example.com')
    assert _retry(other, pid, 'writing', '문제인식').status_code == 404
    assert _calls(orch, 'request_rework_for_project') == []


def _result(**overrides):
    base = dict(project_id='1', run_id='r1', cycle_id='cyc-1', screen=6, bundles=['문제인식'], status='완료',
                started_at=datetime(2026, 10, 6, 1, 0, tzinfo=UTC), ended_at=datetime(2026, 10, 6, 1, 5, tzinfo=UTC),
                kept='후', basis='document', before_score=50.0, after_score=58.0, before_refs=['계획서@1'],
                after_refs=['계획서@2'], plan_before=None, plan_after=None, files=[], rolled_back=False,
                refunded_bundles=[], notice_code=None)
    base.update(overrides)
    return NS(**base)


def test_rework_result_completed_with_changed_sections_and_files(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['rework_result'] = lambda p: _result(
        bundles=['문제인식', '실행 파일'],
        plan_before=[make_section('1-1', '문제', '이전 본문'), make_section('2-1', '실현', '그대로')],
        plan_after=[make_section('1-1', '문제', '새 본문'), make_section('2-1', '실현', '그대로')],
        files=[NS(artifact='prototype', before_path='/u/a.html', after_path='/u/b.html')])

    r = authed_client.get(f'/projects/{pid}/rework-result')

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['status'] == '완료' and body['kept'] == '후' and body['basis'] == 'document'
    assert body['bundles'] == ['문제인식', '실행 파일 제작']
    assert body['before_score'] == 50.0 and body['after_score'] == 58.0
    assert [s['body'] for s in body['plan_after']] == ['새 본문', '그대로']
    assert body['changed']['sections'] == {'1-1': {'before': '이전 본문', 'after': '새 본문'}}  # 같은 섹션은 뺀다
    assert body['changed']['executable_path'] == {'before': '/u/a.html', 'after': '/u/b.html'}
    assert body['changed']['version_kept'] == 'new'
    assert body['changed']['version_comparison'] == {'before_score': 50.0, 'after_score': 58.0}


def test_rework_result_kept_previous_when_score_dropped(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['rework_result'] = lambda p: _result(kept='전', before_score=60.0, after_score=55.0)
    assert authed_client.get(f'/projects/{pid}/rework-result').json()['changed']['version_kept'] == 'previous'


def test_rework_result_in_progress_has_only_common_fields(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['rework_result'] = lambda p: _result(
        status='진행중', ended_at=None, kept=None, basis=None, before_score=None, after_score=None,
        before_refs=[], after_refs=[])
    body = authed_client.get(f'/projects/{pid}/rework-result').json()
    assert body['status'] == '진행중' and body['ended_at'] is None and body['changed'] == {}


def test_rework_result_failed_reports_rollback_and_refund(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['rework_result'] = lambda p: _result(
        status='실패', kept=None, basis=None, before_score=None, after_score=None, before_refs=[], after_refs=[],
        rolled_back=True, refunded_bundles=['인포그래픽'], notice_code='E-RUN-ROLLBACK')
    body = authed_client.get(f'/projects/{pid}/rework-result').json()
    assert body['status'] == '실패' and body['rolled_back'] is True
    assert body['refunded_bundles'] == ['인포그래픽 제작'] and body['notice_code'] == 'E-RUN-ROLLBACK'


def test_rework_result_404_when_never_reworked_and_409_when_not_viewable(authed_client, orch):
    pid = _create(authed_client)
    assert authed_client.get(f'/projects/{pid}/rework-result').status_code == 404  # 기본 None
    orch.responses['rework_result'] = OrchError('RUN_NOT_VIEWABLE', 'x')
    assert authed_client.get(f'/projects/{pid}/rework-result').status_code == 409
