"""워커를 기다리는 동안 DB 연결을 붙잡지 않는다 (SB-266).

후보 · 자격 확인 조회는 워커가 끝내길 최대 ORCH_WAIT_TIMEOUT_SEC(운영 25초) 기다린다. 이 동안 요청의 DB 세션이 연결을 붙잡고 있으면
(웹 DB 연결 풀은 기본 15개) 워커가 느릴 때 대기 요청 15개만 쌓여도 DB를 쓰는 모든 요청이 막히고, 그 이상이면 풀 시간 초과(500)가 난다.
실제 서버에서 측정한 결과는 scripts/load_check.py. 여기서는 대기 중에 이 요청이 연결을 붙잡고 있지 않은지만 본다.

실행:
    pytest tests/test_db_connection_during_wait.py -v
"""
import json

import pytest
from orch_fakes import CandidatesScreen, ProjectView, make_cards, make_run

from app.database import engine


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '연결 점검'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _recording_wait(orch, seen: list, view):
    """wait_project가 불릴 때 풀에서 빌려 간 연결 수를 기록한다."""
    def wait(project_id, timeout_sec=60.0):
        seen.append(engine.pool.checkedout())
        return view
    orch.responses['wait_project'] = wait


def test_candidate_wait_does_not_hold_a_db_connection(authed_client, orch):
    if not hasattr(engine.pool, 'checkedout'):
        pytest.skip('연결 수를 셀 수 없는 풀')
    pid = _create(authed_client)
    baseline, seen = engine.pool.checkedout(), []
    _recording_wait(orch, seen, ProjectView('x', run=make_run(step='공고선택', progress='사용자대기', resume_step=3)))
    orch.responses['screen'] = lambda p, n: CandidatesScreen(candidates=make_cards(1, 2))

    assert authed_client.get(f'/projects/{pid}/match-candidates').status_code == 200

    assert seen and max(seen) <= baseline, f'기다리는 동안 연결 {max(seen)}개 사용(요청 밖 기준 {baseline}개)'


def test_candidate_retry_wait_also_releases_the_connection(authed_client, orch):
    """시작 실패 뒤 시작 요청을 다시 넣고 기다리는 두 번째 대기도 연결을 붙잡지 않는다."""
    from orch_fakes import StartStatus
    if not hasattr(engine.pool, 'checkedout'):
        pytest.skip('연결 수를 셀 수 없는 풀')
    pid = _create(authed_client)
    baseline, seen = engine.pool.checkedout(), []
    failed = ProjectView('x', start=StartStatus(request_id='q1', status='실패', code='X-C2-FAIL', message='다시 시도'))
    ok = ProjectView('x', run=make_run(step='공고선택', progress='사용자대기', resume_step=3))
    answers = iter([failed, ok])

    def wait(project_id, timeout_sec=60.0):
        seen.append(engine.pool.checkedout())
        return next(answers)
    orch.responses['wait_project'] = wait
    orch.responses['screen'] = lambda p, n: CandidatesScreen(candidates=make_cards(1, 2))

    assert authed_client.get(f'/projects/{pid}/match-candidates').status_code == 200

    assert len(seen) == 2 and max(seen) <= baseline, f'대기 {len(seen)}번, 연결 {seen}(기준 {baseline})'


def test_eligibility_wait_does_not_hold_a_db_connection(authed_client, orch):
    from tests.test_orch_stages import _ready_after_select
    if not hasattr(engine.pool, 'checkedout'):
        pytest.skip('연결 수를 셀 수 없는 풀')
    pid = _create(authed_client)
    _ready_after_select(orch)
    view = orch.responses['wait_project'](pid)
    baseline, seen = engine.pool.checkedout(), []
    _recording_wait(orch, seen, view)

    assert authed_client.get(f'/projects/{pid}/eligibility').status_code == 200
    assert authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'}).status_code == 200

    assert len(seen) == 2 and max(seen) <= baseline, f'대기 {len(seen)}번, 연결 {seen}(기준 {baseline})'
