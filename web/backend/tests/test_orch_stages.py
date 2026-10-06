"""[SB-243] 공고 선택 → 자격 확인 → 계획서 · 프로토타입 · 종합 평가 · 검수 시작 — 오케스트레이터 경유(가짜 gateway).

단계는 워커가 돌리고, 웹은 명령을 넣은 뒤 진행 상태를 읽는다. 여기서는 웹이 올바른 함수를 올바른 인자로 부르고
응답을 기대한 모양으로 만드는지만 본다."""
import json
from datetime import UTC, datetime

from orch_fakes import (
    Card,
    ConfirmationNeeded,
    Notice,
    ProjectView,
    make_gate,
    make_gate_screen,
    make_outputs,
    make_run,
)

from app.orch import OrchError


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '단계 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _notice(code: str, message: str = '안내') -> Notice:
    return Notice(code=code, message=message, at=datetime.now(UTC))


def _calls(orch, name: str) -> list:
    return [(args, kwargs) for n, args, kwargs in orch.calls if n == name]


def _ready_after_select(orch, *, gate=None, notices=(), announcement_id='N-01', screen_notices=()):
    """공고 선택 → 자격 확인이 끝난 상태: 명령 전엔 안내 0개, 끝난 뒤엔 notices가 쌓인다."""
    before = ProjectView('1', run=make_run(step='공고선택', progress='사용자대기', screen_status='확인 필요', resume_step=3))
    after = ProjectView('1', run=make_run(
        step='계획서작성', progress='사용자대기', screen_status='확인 필요', resume_step=5,
        announcement_id=announcement_id, notices=list(notices)))
    orch.responses['view_project'] = lambda pid: before
    orch.responses['wait_project'] = lambda pid, timeout_sec=60.0: after
    orch.responses['screen'] = lambda pid, n: make_gate_screen(
        announcement_id, gate or make_gate(), notices=list(screen_notices))
    orch.responses['outputs'] = lambda pid: make_outputs(candidates=[
        Card(announcement_id='N-01', title='공고1', fit_score=0.9, match_reason='딱 맞아요')])


# ── POST /generate ────────────────────────────────────────────────────────────────────
def test_generate_selects_announcement_and_returns_eligibility(authed_client, orch):
    pid = _create(authed_client)
    _ready_after_select(orch)

    r = authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['status'] == 'ready'
    assert body['eligibility']['passed'] is True
    assert body['match'] == {'notice_id': 'N-01', 'fit_score': 0.9, 'reason': '딱 맞아요', 'status': 'user_waiting',
                             'score_reasons': []}
    assert body['plan'] is None and body['verdict'] is None
    assert _calls(orch, 'select_announcement_for_project') == [((pid, 'N-01'), {})]


def test_generate_rejected_gate_shows_new_notices_and_unknown_conditions(authed_client, orch):
    pid = _create(authed_client)
    gate = make_gate(passed=False, failed_conditions=['업력'], unknown_conditions=['지원대상 유형'])
    _ready_after_select(
        orch, gate=gate, notices=[_notice('E-G1-REJECT', '조건에 맞지 않아요')],
        screen_notices=[_notice('E-G1-UNPARSED', '확인이 필요해요')])

    body = authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'}).json()

    assert body['status'] == 'ready'
    assert body['eligibility']['passed'] is False
    assert body['eligibility']['failed_conditions'] == ['업력']
    assert body['eligibility']['unknown_conditions'] == ['지원대상 유형']
    assert [n['code'] for n in body['notices']] == ['E-G1-REJECT', 'E-G1-UNPARSED']


def test_generate_only_reports_notices_added_by_this_selection(authed_client, orch):
    """실행 건에 이미 쌓여 있던 안내(이전 시도)는 이번 결과의 안내로 보이지 않는다."""
    pid = _create(authed_client)
    old = _notice('E-G1-REJECT', '이전 공고 불통과')
    before = ProjectView('1', run=make_run(step='공고선택', progress='사용자대기', resume_step=3, notices=[old]))
    after = ProjectView('1', run=make_run(
        step='계획서작성', progress='사용자대기', resume_step=5, announcement_id='N-01', notices=[old]))
    _ready_after_select(orch)
    orch.responses['view_project'] = lambda p: before
    orch.responses['wait_project'] = lambda p, timeout_sec=60.0: after

    body = authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'}).json()

    assert body['notices'] == []


def test_generate_pending_while_worker_checks_eligibility(authed_client, orch):
    pid = _create(authed_client)
    _ready_after_select(orch)
    orch.responses['wait_project'] = lambda p, timeout_sec=60.0: ProjectView(
        '1', run=make_run(step='자격확인', progress='실행'))

    body = authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'}).json()

    assert body['status'] == 'pending'
    assert body['eligibility'] is None
    assert _calls(orch, 'screen') == []


def test_generate_fails_when_announcement_server_failed(authed_client, orch):
    """공고 서버 오류면 고르기 전 값 그대로라 화면 4의 공고가 다르다 — 실패 안내를 보여 준다."""
    pid = _create(authed_client)
    _ready_after_select(orch, announcement_id='N-OLD', notices=[_notice('X-C2-FAIL', '공고를 확인하지 못했어요.')])

    body = authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'}).json()

    assert body['status'] == 'failed'
    assert body['code'] == 'X-C2-FAIL'
    assert body['message'] == '공고를 확인하지 못했어요.'
    assert body['eligibility'] is None


def test_generate_fails_when_no_gate_result_exists(authed_client, orch):
    pid = _create(authed_client)
    _ready_after_select(orch, notices=[_notice('X-C2-GONE', '공고가 사라졌어요')])
    orch.responses['screen'] = OrchError('SCREEN_NOT_READY', '화면 4 — 자격 확인 전')

    body = authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'}).json()

    assert body['status'] == 'failed'
    assert body['code'] == 'X-C2-GONE'


def test_generate_requires_a_notice_id(authed_client, orch):
    pid = _create(authed_client)
    r = authed_client.post(f'/projects/{pid}/generate', json={})
    assert r.status_code == 422
    assert _calls(orch, 'select_announcement_for_project') == []


def test_generate_maps_orchestrator_errors(authed_client, orch):
    pid = _create(authed_client)
    for code, status in [('INVALID_ANNOUNCEMENT', 422), ('ANNOUNCEMENT_BLOCKED', 409), ('INVALID_STATE', 409), ('BUSY', 409)]:
        orch.responses['select_announcement_for_project'] = OrchError(code, 'x')
        r = authed_client.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'})
        assert r.status_code == status, (code, r.text)


def test_generate_requires_ownership(login_as, orch):
    pid = _create(login_as('owner@example.com'))
    other = login_as('other@example.com')
    r = other.post(f'/projects/{pid}/generate', json={'notice_id': 'N-01'})
    assert r.status_code == 404
    assert _calls(orch, 'select_announcement_for_project') == []


def test_eligibility_reads_screen_4_again(authed_client, orch):
    pid = _create(authed_client)
    _ready_after_select(orch)

    body = authed_client.get(f'/projects/{pid}/eligibility').json()

    assert body['status'] == 'ready' and body['eligibility']['passed'] is True
    assert _calls(orch, 'select_announcement_for_project') == []


# ── 단계 시작 ─────────────────────────────────────────────────────────────────────────
def _status_view(orch, **run_overrides):
    orch.responses['view_project'] = lambda pid: ProjectView(str(pid), run=make_run(**run_overrides))


def test_plan_start_calls_start_writing_and_returns_status(authed_client, orch):
    pid = _create(authed_client)
    _status_view(orch, step='계획서작성', progress='실행', percent=0, resume_step=5)

    r = authed_client.post(f'/projects/{pid}/plan/start')

    assert r.status_code == 200, r.text
    assert r.json()['stage'] == 'plan_writing' and r.json()['match_status'] == 'in_progress'
    assert _calls(orch, 'start_writing_for_project') == [((pid,), {})]


def test_plan_start_twice_returns_current_status(authed_client, orch):
    """이미 시작돼 진행 중이면 INVALID_STATE — 한 번만 시작되고 지금 상태를 돌려준다."""
    pid = _create(authed_client)
    orch.responses['start_writing_for_project'] = OrchError('INVALID_STATE', '진행 중')
    _status_view(orch, step='계획서작성', progress='실행', percent=40, resume_step=5)

    r = authed_client.post(f'/projects/{pid}/plan/start')

    assert r.status_code == 200
    assert r.json()['progress_percent'] == 40


def test_plan_start_before_choosing_an_announcement_is_400(authed_client, orch):
    pid = _create(authed_client)
    # 실행 건이 없다
    orch.responses['start_writing_for_project'] = OrchError('RUN_NOT_FOUND', 'x')
    assert authed_client.post(f'/projects/{pid}/plan/start').status_code == 400
    # 공고를 고르기 전(또는 자격 불통과로 돌아온) 대기 지점
    orch.responses['start_writing_for_project'] = OrchError('INVALID_STATE', 'x')
    _status_view(orch, step='공고선택', progress='사용자대기', screen_status='확인 필요', resume_step=3)
    r = authed_client.post(f'/projects/{pid}/plan/start')
    assert r.status_code == 400 and '공고를 선택' in r.json()['detail']


def test_plan_start_busy_is_409(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['start_writing_for_project'] = OrchError('BUSY', 'x')
    assert authed_client.post(f'/projects/{pid}/plan/start').status_code == 409


def test_prototype_start_decides_screen_6(authed_client, orch):
    pid = _create(authed_client)
    _status_view(orch, step='프로토타입제작', progress='실행', percent=0, resume_step=7)

    r = authed_client.post(f'/projects/{pid}/prototype/start')

    assert r.status_code == 200 and r.json()['stage'] == 'prototype_building'
    assert _calls(orch, 'decide_for_project') == [((pid, 6, '진행'), {})]


def test_final_review_start_decides_screen_8(authed_client, orch):
    pid = _create(authed_client)
    _status_view(orch, step='종합평가', progress='사용자대기', screen_status='확인 필요', resume_step=9)

    r = authed_client.post(f'/projects/{pid}/final-review/start')

    assert r.status_code == 200 and r.json()['stage'] == 'final_review_pending'
    assert _calls(orch, 'decide_for_project') == [((pid, 8, '진행'), {})]


def test_review_start_decides_screen_9(authed_client, orch):
    pid = _create(authed_client)
    _status_view(orch, step='표현검수', progress='실행', percent=10, resume_step=10)

    r = authed_client.post(f'/projects/{pid}/review/start')

    assert r.status_code == 200 and r.json()['stage'] == 'reviewing'
    assert _calls(orch, 'decide_for_project') == [((pid, 9, '진행'), {'confirmed': False})]


def test_review_start_needs_confirmation_when_below_threshold(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['decide_for_project'] = lambda p, screen, action, confirmed=False: (
        None if confirmed else ConfirmationNeeded(reason='기준 점수 미달', items={'current': 70, 'threshold': 80}))
    _status_view(orch, step='표현검수', progress='실행', percent=0, resume_step=10)

    r = authed_client.post(f'/projects/{pid}/review/start')
    assert r.status_code == 409
    assert r.json()['detail'] == {
        'confirmation_required': True, 'reason': '기준 점수 미달', 'items': {'current': 70, 'threshold': 80}}

    r = authed_client.post(f'/projects/{pid}/review/start', json={'confirmed': True})
    assert r.status_code == 200 and r.json()['stage'] == 'reviewing'
    assert _calls(orch, 'decide_for_project')[-1] == ((pid, 9, '진행'), {'confirmed': True})
