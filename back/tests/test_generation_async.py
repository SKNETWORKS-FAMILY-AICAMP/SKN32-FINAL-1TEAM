"""app/routers/projects.py의 생성 비동기화(2026-09-22, 프론트 전달사항 1번) — pytest 버전.

threading.Thread(daemon=True) + 프로세스 메모리 안의 _running_generations 셋 대신,
match_results.worker_claimed_at 컬럼 하나로 "지금 어떤 프로세스가 이 stage를 처리 중인지"를
DB 자체로 표현하도록 바꿨다(Redis 등 새 브로커 없이 서버 재시작·다중 워커에 대응하기 위함).
이 테스트는 그 클레임/복구 로직만 검증한다 — 진행 내용물(fake sleep로 progress_percent만
올리는 부분)은 기존 동작 그대로라 별도로 다루지 않는다.
"""
import datetime
import json
import time

import app.routers.projects as projects_router
from app.models import MatchResult, Notice


def _payload(**overrides):
    base = {
        'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': None, 'description': 'AI 기반 동네 헬스장 통합 예약 서비스',
        'team_members': [], 'pricing_items': [],
    }
    base.update(overrides)
    return base


def _seed_notice(db_session, notice_id: str) -> Notice:
    notice = Notice(
        notice_id=notice_id, source='k-startup', title='테스트 공고', organizer='창업진흥원',
        recruitment_status='open', url=f'https://example.com/notice/{notice_id}',
    )
    db_session.add(notice)
    db_session.commit()
    db_session.refresh(notice)
    return notice


def _create_match(authed_client, db_session, notice_id: str) -> MatchResult:
    """POST /generate로 실제 엔드포인트를 그대로 태워 match_results 행을 하나 만든다 —
    company/project FK를 손으로 채우는 대신 기존 파이프라인을 재사용."""
    notice = _seed_notice(db_session, notice_id)
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']
    r = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': notice.notice_id})
    assert r.status_code == 200, r.text
    match_id = r.json()['match']['match_id']
    db_session.expire_all()
    return db_session.get(MatchResult, match_id)


def _wait_until_done(db_session, match: MatchResult, done_stage: str, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        db_session.expire_all()
        db_session.refresh(match)
        if match.stage == done_stage:
            return
        time.sleep(0.05)
    raise AssertionError(f'{timeout_s}초 안에 stage={done_stage!r}에 도달하지 못함(마지막 stage={match.stage!r})')


def test_duplicate_claim_does_not_double_run(authed_client, db_session, monkeypatch):
    """같은 stage를 거의 동시에 두 번 클레임 시도하면 하나만 성공해야 한다 — 여러 요청/
    복구 루프가 겹쳐도 실행 스레드가 중복으로 뜨지 않는 걸 보장하는 부분."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-DUP')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 0
    match.worker_claimed_at = None
    db_session.commit()

    running, done = projects_router.ps.STAGE_PLAN_WRITING, projects_router.ps.STAGE_PLAN_REVIEW_PENDING
    first = projects_router._try_claim_and_run(match.match_id, running, done)
    second = projects_router._try_claim_and_run(match.match_id, running, done)

    assert first is True, '첫 클레임은 성공해야 함'
    assert second is False, '방금 클레임된 작업을 두 번째 호출이 또 가져가면 중복 실행이 됨'

    _wait_until_done(db_session, match, done)
    assert match.progress_percent == 100


def test_recovery_picks_up_orphaned_generation(authed_client, db_session, monkeypatch):
    """서버가 재시작돼 스레드가 죽은 상황(stage는 진행중인데 worker_claimed_at이 없음)을
    흉내내고, 복구 루프 한 tick이 이어받아 끝까지 진행시키는지 확인한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-ORPHAN')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 40  # 재시작 전에 이미 진행되던 중이었다는 설정
    match.worker_claimed_at = None  # 그 진행을 맡았던 스레드는 이미 죽음
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)
    assert match.progress_percent == 100


def test_recovery_ignores_freshly_claimed_generation(authed_client, db_session):
    """다른 워커가 방금 클레임한(아직 안 오래된) 작업은 복구 루프가 건드리면 안 된다."""
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-FRESH')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 10
    match.worker_claimed_at = datetime.datetime.utcnow()  # 방금 다른 워커가 클레임한 것처럼
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)
    time.sleep(0.1)  # 잘못 클레임돼 스레드가 떴다면 진행됐을 시간을 줌

    db_session.expire_all()
    db_session.refresh(match)
    assert match.stage == projects_router.ps.STAGE_PLAN_WRITING, '진행중이던 작업의 stage가 바뀌면 안 됨'
    assert match.progress_percent == 10, '복구 루프가 손대면 안 됨(다른 워커가 이미 처리 중인 작업)'


def test_stale_claim_gets_reclaimed(authed_client, db_session, monkeypatch):
    """클레임이 있어도 GENERATION_CLAIM_STALE_SECONDS보다 오래됐으면 죽은 워커로 보고
    복구 루프가 다시 가져가야 한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-STALE')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 70
    match.worker_claimed_at = datetime.datetime.utcnow() - datetime.timedelta(
        seconds=projects_router.GENERATION_CLAIM_STALE_SECONDS + 5,
    )
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)
    assert match.progress_percent == 100


def test_plan_start_endpoint_still_completes_via_claim(authed_client, db_session, monkeypatch):
    """엔드투엔드 확인 — POST /plan/start가 DB 클레임 경로로 바뀐 뒤에도 정상적으로
    plan_review_pending까지 도달하고, GET /status가 그 값을 그대로 보여주는지."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-E2E')
    project_id = match.project_id

    r = authed_client.post(f'/projects/{project_id}/plan/start')
    assert r.status_code == 200, r.text
    assert r.json()['stage'] == projects_router.ps.STAGE_PLAN_WRITING

    # 여러 번 불러도 한 번만 실행돼야 한다(문서 1번 확정 사항).
    r2 = authed_client.post(f'/projects/{project_id}/plan/start')
    assert r2.status_code == 200, r2.text

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)

    status = authed_client.get(f'/projects/{project_id}/status').json()
    assert status['stage'] == projects_router.ps.STAGE_PLAN_REVIEW_PENDING
    assert status['progress_percent'] == 100


def _wait_until_status(db_session, match: MatchResult, status: str, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        db_session.expire_all()
        db_session.refresh(match)
        if match.status == status:
            return
        time.sleep(0.05)
    raise AssertionError(f'{timeout_s}초 안에 status={status!r}가 되지 못함(마지막 status={match.status!r})')


def _monkeypatch_boom(monkeypatch, message='더미 에이전트 강제 실패(테스트)'):
    """projects.time은 표준 라이브러리 time 모듈 그 자체라(같은 객체), 여기서 sleep을
    갈아치우면 테스트 파일의 폴링(_wait_until_status 등)에도 그대로 적용된다 — 생성 스텝
    간격(DUMMY_GENERATION_STEP_SECONDS)일 때만 실패를 흉내내고, 그 외(폴링 등)는 진짜
    sleep으로 넘겨야 한다."""
    _real_sleep = time.sleep

    def _boom(seconds):
        if seconds == projects_router.DUMMY_GENERATION_STEP_SECONDS:
            raise RuntimeError(message)
        _real_sleep(seconds)

    monkeypatch.setattr(projects_router.time, 'sleep', _boom)


def test_first_failure_schedules_backoff_retry_instead_of_failing(authed_client, db_session, monkeypatch):
    """[2026-09-23 개정] 첫 실패에서 바로 status='failed'가 되면 안 된다 — 15초 뒤
    자동 재시도를 예약한 status='waiting_resume'이 되고, retry_count가 1이 돼야 한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    _monkeypatch_boom(monkeypatch)

    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-BACKOFF1')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 0
    match.worker_claimed_at = None
    db_session.commit()

    claimed = projects_router._try_claim_and_run(
        match.match_id, projects_router.ps.STAGE_PLAN_WRITING, projects_router.ps.STAGE_PLAN_REVIEW_PENDING,
    )
    assert claimed is True

    _wait_until_status(db_session, match, 'waiting_resume')
    assert match.stage == projects_router.ps.STAGE_PLAN_WRITING, '실패해도 stage는 실패한 단계 그대로여야 함'
    assert '더미 에이전트 강제 실패' in (match.failure_reason or '')
    assert match.retry_count == 1
    assert match.next_retry_at is not None
    expected_delay = projects_router.GENERATION_RETRY_BASE_SECONDS  # 1번째 재시도 = 기본 간격(15초)
    actual_delay = (match.next_retry_at - datetime.datetime.utcnow()).total_seconds()
    assert expected_delay - 2 < actual_delay <= expected_delay, f'1번째 백오프는 {expected_delay}초여야 함(실제 {actual_delay})'

    # 아직 재시도 5회를 다 못 썼으니 관리자 알림은 안 생겨야 한다.
    alerts = db_session.query(projects_router.GenerationFailureAlert).filter_by(match_id=match.match_id).all()
    assert alerts == [], '재시도 여지가 남아있는 실패는 관리자 알림 대상이 아님'


def test_recovery_does_not_retry_before_next_retry_at(authed_client, db_session):
    """status='waiting_resume'이어도 next_retry_at이 아직 안 지났으면 복구 루프가
    건드리면 안 된다 — 백오프 간격을 지켜야 함."""
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-BACKOFF-EARLY')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 40
    match.status = 'waiting_resume'
    match.retry_count = 1
    match.failure_reason = '이전 실패(테스트)'
    match.worker_claimed_at = None
    match.next_retry_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=30)
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)
    time.sleep(0.1)  # 잘못 재시작됐다면 진행됐을 시간을 줌

    db_session.expire_all()
    db_session.refresh(match)
    assert match.status == 'waiting_resume', '백오프 대기 시간이 남았으면 손대면 안 됨'
    assert match.progress_percent == 40


def test_recovery_retries_after_next_retry_at_passes(authed_client, db_session, monkeypatch):
    """next_retry_at이 지나면 복구 루프가 자동으로 다시 이어받아야 하고(사용자 개입 없이),
    이미 진행된 부분(progress_percent)부터 재개해야 한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-BACKOFF-DUE')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 40
    match.status = 'waiting_resume'
    match.retry_count = 1
    match.failure_reason = '이전 실패(테스트)'
    match.worker_claimed_at = None
    match.next_retry_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)  # 이미 지남
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)
    assert match.status == 'in_progress', '클레임되면서 waiting_resume -> in_progress로 되돌아가야 함'
    assert match.retry_count == 0, '성공적으로 재개됐으면 실패 스트릭이 리셋돼야 함'
    assert match.progress_percent == 100


def test_max_retries_exhausted_marks_failed_and_creates_alert(authed_client, db_session, monkeypatch):
    """자동 재시도 5회를 전부 소진하고도 실패하면 status='failed'로 확정되고,
    generation_failure_alerts에 관리자 알림 행이 하나 남아야 한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    _monkeypatch_boom(monkeypatch, message='6번째 실패(테스트)')

    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-CAP')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 70
    match.status = 'waiting_resume'
    match.retry_count = projects_router.GENERATION_RETRY_MAX_ATTEMPTS  # 이미 5회 소진
    match.worker_claimed_at = None
    match.next_retry_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)

    _wait_until_status(db_session, match, 'failed')
    assert match.retry_count == projects_router.GENERATION_RETRY_MAX_ATTEMPTS + 1
    assert match.next_retry_at is None
    assert '6번째 실패' in (match.failure_reason or '')

    alerts = db_session.query(projects_router.GenerationFailureAlert).filter_by(match_id=match.match_id).all()
    assert len(alerts) == 1, '재시도 상한 도달 시 관리자 알림이 정확히 한 행 생겨야 함'
    alert = alerts[0]
    assert alert.project_id == match.project_id
    assert alert.stage == projects_router.ps.STAGE_PLAN_WRITING
    assert alert.retry_count == projects_router.GENERATION_RETRY_MAX_ATTEMPTS
    assert '6번째 실패' in (alert.failure_reason or '')
    assert alert.acknowledged_at is None


def test_recovery_loop_does_not_retry_failed_generation(authed_client, db_session):
    """실패로 확정된 작업은 클레임이 없어도(=고아처럼 보여도) 복구 루프가 자동으로
    다시 돌리면 안 된다 — 사용자가 명시적으로 재시도해야 한다."""
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-FAIL-NORETRY')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 40
    match.status = 'failed'
    match.failure_reason = '더미 실패(테스트)'
    match.worker_claimed_at = None
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)
    time.sleep(0.1)  # 잘못 재시작됐다면 진행됐을 시간을 줌

    db_session.expire_all()
    db_session.refresh(match)
    assert match.status == 'failed'
    assert match.progress_percent == 40, '복구 루프가 실패한 작업을 건드리면 안 됨'


def test_plan_start_retries_after_failure(authed_client, db_session, monkeypatch):
    """실패 후 사용자가 다시 POST /plan/start를 호출하면(= "다시 시도" 버튼) status/
    failure_reason이 리셋되고 처음부터 다시 돌아 정상 완료돼야 한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-RETRY')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 70
    match.status = 'failed'
    match.failure_reason = '이전 시도 실패(테스트)'
    match.worker_claimed_at = None
    db_session.commit()

    r = authed_client.post(f'/projects/{match.project_id}/plan/start')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['match_status'] == 'in_progress'
    assert body['failure_reason'] is None
    assert body['progress_percent'] == 0, '다시 시도는 처음부터 다시 돌아야 함'
    # [2026-09-23] 수동 "다시 이어가기"는 0이 아니라 1로 간다 — 이 클릭 자체가 재시도
    # 1회를 쓴 걸로 친다(원래 재시도 예산 5회의 연장선).
    assert body['retry_count'] == 1

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)
    assert match.status == 'in_progress'
    assert match.failure_reason is None


# ============================================================================
# 화면 헤더 종모양 알림 — GET /projects(목록)의 display_status/재시도 필드
# (front/src/features/workflow/shared.jsx NotificationBell이 이 엔드포인트를 이미
# 폴링하고 있어서, 별도 알림 엔드포인트 대신 여기에 필드를 얹었다.)
# ============================================================================

def test_list_projects_classifies_waiting_resume_and_failed_for_display(authed_client, db_session):
    """waiting_resume/failed 상태가 화면 문구(진행/문제가 생겨 멈췄다)로 분류되고,
    재시도 횟수·다음 재시도 시각·실패 사유도 그대로 실려야 한다."""
    waiting = _create_match(authed_client, db_session, 'NOTICE-NOTIFY-WAITING')
    waiting.stage = projects_router.ps.STAGE_PLAN_WRITING
    waiting.status = 'waiting_resume'
    waiting.retry_count = 2
    waiting.failure_reason = '30초 후 재시도 예정(테스트)'
    waiting.next_retry_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=30)
    db_session.commit()

    res = authed_client.get('/projects')
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r['project_id'] == waiting.project_id)
    assert row['match_status'] == 'waiting_resume'
    assert row['display_status'] == '진행', '재개대기도 화면엔 그냥 진행 중으로 보여야 함'
    assert row['retry_count'] == 2
    assert row['next_retry_at'] is not None
    assert row['failure_reason'] == '30초 후 재시도 예정(테스트)'

    # 실패로 확정되면(자동 재시도 5회 소진) 별도 문구로 분류돼야 한다 — 동시 실행 1건
    # 제한 때문에 앞의 waiting_resume 매칭을 먼저 보관 처리해야 새 프로젝트를 만들 수 있다.
    waiting.archived_at = datetime.datetime.utcnow()
    waiting.archived_by = 'user'
    db_session.commit()

    failed = _create_match(authed_client, db_session, 'NOTICE-NOTIFY-FAILED')
    failed.stage = projects_router.ps.STAGE_PROTOTYPE_BUILDING
    failed.status = 'failed'
    failed.retry_count = 6
    failed.failure_reason = '재시도 5회 소진(테스트)'
    db_session.commit()

    res2 = authed_client.get('/projects')
    row2 = next(r for r in res2.json() if r['project_id'] == failed.project_id)
    assert row2['display_status'] == '문제가 생겨 멈췄다'
    assert row2['retry_count'] == 6


def test_list_projects_classifies_completed_for_display(authed_client, db_session):
    done = _create_match(authed_client, db_session, 'NOTICE-NOTIFY-DONE')
    done.stage = projects_router.ps.STAGE_DONE
    done.status = 'completed'
    db_session.commit()

    res = authed_client.get('/projects')
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r['project_id'] == done.project_id)
    assert row['display_status'] == '완료'
