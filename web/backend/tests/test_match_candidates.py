"""GET /projects/{id}/match-candidates, POST .../match-candidates/rematch — 오케스트레이터(화면 3) 경유.

공고 추천은 워커가 돌리고 웹은 결과를 읽는다. 가짜 오케스트레이터(orch fixture)로 상태를 만든다.

실행:
    pytest tests/test_match_candidates.py -v
"""
from datetime import datetime

import pytest
from orch_fakes import (
    CandidatesScreen,
    Notice,
    ProjectView,
    StartStatus,
    make_cards,
    make_run,
)

from app.orch.errors import OrchError
from tests.test_projects import _create_project, _login, _new_client

USER_EMAIL = 'match-candidates-test@example.com'
NOW = datetime(2026, 10, 5, 12, 0, 0)


@pytest.fixture()
def user_client(db_session):
    uc = _new_client()
    _login(uc, USER_EMAIL, '매칭후보테스트유저')
    return uc


def _ready(orch, screen: CandidatesScreen):
    """사전 단계가 끝나 공고선택 · 사용자대기인 상태."""
    run = make_run(step='공고선택', progress='사용자대기', screen_status='확인 필요', resume_step=3, percent=0)
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: ProjectView(str(pid), run=run)
    orch.responses['screen'] = lambda pid, n: screen


def test_ready_returns_cards_in_rank_order_with_new_fields(user_client, orch):
    project_id = _create_project(user_client)
    _ready(orch, CandidatesScreen(candidates=make_cards(1, 10)))
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert body['status'] == 'ready'
    assert [c['rank'] for c in body['candidates']] == list(range(1, 11))
    first = body['candidates'][0]
    assert first['notice_id'] == 'N-01' and first['org'] == '테스트기관' and first['batch'] == 1
    assert first['bonus_score'] is None  # 가산점 계산 못 함 — 0이 아니라 null
    assert first['source_notice'] == '출처: 테스트'
    assert body['rematch_used'] is False
    assert orch.calls[-1][:2] == ('screen', (project_id, 3))


def test_more_candidates_come_after_first_with_batch_two(user_client, orch):
    project_id = _create_project(user_client)
    _ready(orch, CandidatesScreen(candidates=make_cards(1, 10), more_candidates=make_cards(11, 10), more_available=False))
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert [c['batch'] for c in body['candidates']] == [1] * 10 + [2] * 10
    assert [c['rank'] for c in body['candidates']] == list(range(1, 21))
    assert body['rematch_used'] is True


def test_blocked_ids_and_notices_are_passed_through(user_client, orch):
    project_id = _create_project(user_client)
    notice = Notice(code='E-C2-EMBED', message='추천 정확도가 낮아요', at=NOW)
    _ready(orch, CandidatesScreen(candidates=make_cards(1, 3), blocked_announcement_ids=['N-02'], notices=[notice]))
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert body['blocked_notice_ids'] == ['N-02']
    assert body['notices'] == [{'code': 'E-C2-EMBED', 'message': '추천 정확도가 낮아요'}]


def test_pending_while_pre_stage_runs(user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: ProjectView(
        str(pid), start=StartStatus(request_id='q1', status='처리중'))
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert body['status'] == 'pending' and body['candidates'] == []
    assert not [c for c in orch.calls if c[0] == 'screen']


def test_pending_while_run_is_executing(user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: ProjectView(
        str(pid), run=make_run(step='자격확인', progress='실행'))
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert body['status'] == 'pending'
    assert not [c for c in orch.calls if c[0] == 'screen']


def test_no_match_is_reported_without_retry(user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: ProjectView(
        str(pid), start=StartStatus(request_id='q1', status='실패', code='E-C2-NOMATCH', message='신청 가능한 공고가 없어요'))
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert (body['status'], body['code'], body['message']) == ('no_match', 'E-C2-NOMATCH', '신청 가능한 공고가 없어요')
    assert len([c for c in orch.calls if c[0] == 'request_start']) == 1  # 프로젝트 생성 때 한 번뿐 — 다시 넣지 않는다


@pytest.mark.parametrize('code', ['E-C1-TIMEOUT', 'X-C2-FAIL', 'E-C2-STALE'])
def test_retryable_start_failure_requests_start_again(user_client, orch, code):
    project_id = _create_project(user_client)
    failed = ProjectView('x', start=StartStatus(request_id='q1', status='실패', code=code, message='다시 시도'))
    ok = ProjectView('x', run=make_run(step='공고선택', progress='사용자대기', resume_step=3))
    answers = iter([failed, ok])
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: next(answers)
    orch.responses['screen'] = lambda pid, n: CandidatesScreen(candidates=make_cards(1, 2))
    before = len([c for c in orch.calls if c[0] == 'request_start'])
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert body['status'] == 'ready' and len(body['candidates']) == 2
    assert len([c for c in orch.calls if c[0] == 'request_start']) == before + 1


def test_nothing_started_reports_failed(user_client):
    project_id = _create_project(user_client)
    body = user_client.get(f'/projects/{project_id}/match-candidates').json()
    assert body['status'] == 'failed' and body['candidates'] == []


def test_screen_not_ready_maps_to_409(user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: ProjectView(
        str(pid), run=make_run(step='문서평가', progress='사용자대기'))
    orch.responses['screen'] = OrchError('INVALID_STATE', 'x')
    assert user_client.get(f'/projects/{project_id}/match-candidates').status_code == 409


def test_other_users_project_is_404(user_client, login_as, orch):
    project_id = _create_project(user_client)
    other = login_as('someone-else@example.com', '남')
    assert other.get(f'/projects/{project_id}/match-candidates').status_code in (403, 404)


def test_rematch_returns_merged_list_and_marks_used(user_client, orch):
    project_id = _create_project(user_client)
    _ready(orch, CandidatesScreen(candidates=make_cards(1, 10), more_candidates=make_cards(11, 10), more_available=False))
    res = user_client.post(f'/projects/{project_id}/match-candidates/rematch')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['rematch_used'] is True and body['message'] is None
    assert len([c for c in body['candidates'] if c['batch'] == 2]) == 10
    assert any(c[0] == 'more_candidates_for_project' and c[1] == (project_id,) for c in orch.calls)


def test_rematch_without_new_cards_says_nothing_more(user_client, orch):
    project_id = _create_project(user_client)
    _ready(orch, CandidatesScreen(candidates=make_cards(1, 10), more_candidates=[], more_available=False))
    body = user_client.post(f'/projects/{project_id}/match-candidates/rematch').json()
    assert body['message'] == '지금은 더 보여드릴 공고가 없어요.'
    assert len(body['candidates']) == 10


def test_rematch_failure_keeps_chance_and_shows_notice(user_client, orch):
    project_id = _create_project(user_client)
    notice = Notice(code='X-C2-FAIL', message='공고를 찾지 못했어요. 다시 시도해 주세요.', at=NOW)
    _ready(orch, CandidatesScreen(candidates=make_cards(1, 10), more_available=True, notices=[notice]))
    body = user_client.post(f'/projects/{project_id}/match-candidates/rematch').json()
    assert body['rematch_used'] is False  # 실패한 추가 조회는 기회를 돌려받는다
    assert body['message'] is None
    assert body['notices'][0]['code'] == 'X-C2-FAIL'


def test_rematch_limit_maps_to_409(user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['more_candidates_for_project'] = OrchError('MORE_LIMIT', '')
    res = user_client.post(f'/projects/{project_id}/match-candidates/rematch')
    assert res.status_code == 409
    assert res.json()['detail'] == '공고 다시 찾기는 한 번만 할 수 있어요.'


def test_rematch_before_run_exists_is_404(user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['more_candidates_for_project'] = OrchError('RUN_NOT_FOUND', '')
    assert user_client.post(f'/projects/{project_id}/match-candidates/rematch').status_code == 404
