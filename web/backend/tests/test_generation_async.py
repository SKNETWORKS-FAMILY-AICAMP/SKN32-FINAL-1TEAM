"""app/routers/projects.py의 생성 비동기화(2026-09-22, 프론트 전달사항 1번) — pytest 버전.

threading.Thread(daemon=True) + 프로세스 메모리 안의 _running_generations 셋 대신,
projects.worker_claimed_at 컬럼 하나로 "지금 어떤 프로세스가 이 stage를 처리 중인지"를
DB 자체로 표현하도록 바꿨다(Redis 등 새 브로커 없이 서버 재시작·다중 워커에 대응하기 위함).
이 테스트는 그 클레임/복구 로직만 검증한다 — 진행 내용물(fake sleep로 progress_percent만
올리는 부분)은 기존 동작 그대로라 별도로 다루지 않는다.

[2026-09-28, match_results 테이블 통합] 이 테스트가 다루던 MatchResult 행은 이제
Project 행 자체다(project(1):match(1)) — 아래 헬퍼가 돌려주는 `match` 변수는 실제로는
Project 인스턴스이고, match_id 대신 project_id를 키로 쓴다.
"""
import datetime
import json
import time

import app.routers.projects as projects_router
from app.models import Notice, Project


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


def _create_match(authed_client, db_session, notice_id: str) -> Project:
    """POST /generate로 실제 엔드포인트를 그대로 태워 매칭 상태(이제 project 행 자체에
    얹힘)를 만든다 — company/project FK를 손으로 채우는 대신 기존 파이프라인을 재사용."""
    notice = _seed_notice(db_session, notice_id)
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']
    r = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': notice.notice_id})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    return db_session.get(Project, project_id)


def _wait_until_done(db_session, match: Project, done_stage: str, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        db_session.expire_all()
        db_session.refresh(match)
        if match.stage == done_stage:
            return
        time.sleep(0.05)
    raise AssertionError(f'{timeout_s}초 안에 stage={done_stage!r}에 도달하지 못함(마지막 stage={match.stage!r})')


def test_prototype_building_completion_replaces_dummy_artifact_with_v2(authed_client, db_session, monkeypatch):
    """[2026-09-29 신규, 프론트 5차 D-2] prototype_building 워커가 100%에 도달하면
    seed_dummy_pipeline이 매칭 시점에 미리 만들어둔 더미 산출물(version=1)을 구현
    Agent(T-B1/T-B2) 실제 호출 결과(version=2)로 교체해야 한다 — 구현·검증-2 담당
    확인(옵션 A, Downloads/백엔드_답변_D2_구현Agent_호출시점.md) 반영. 더미 v1은 점수 비교
    없이 즉시 is_current=False가 되고(조건 2-2), 교체 자체는 rework_cap을 쓰지 않아야
    한다(조건 2-3, rerun_type='initial')."""
    from app.models import AgentExecution, Artifact, BusinessPlan

    match = _create_match(authed_client, db_session, 'PROTO-D2')
    plan = db_session.query(BusinessPlan).filter_by(project_id=match.project_id).one()
    old_artifact = db_session.query(Artifact).filter_by(plan_id=plan.plan_id).one()
    assert old_artifact.version == 1
    assert old_artifact.is_current is True

    match.stage = projects_router.ps.STAGE_PROTOTYPE_BUILDING
    match.status = 'in_progress'
    match.progress_percent = 90
    db_session.commit()
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0)
    projects_router._simulate_generation(match.project_id, projects_router.ps.STAGE_PROTOTYPE_BUILDING, 'done')

    db_session.expire_all()
    artifacts = db_session.query(Artifact).filter_by(plan_id=plan.plan_id).order_by(Artifact.artifact_id).all()
    assert len(artifacts) == 2, '더미(v1) + 실제 호출 결과(v2) 두 행이 남아야 한다'
    assert artifacts[0].artifact_id == old_artifact.artifact_id
    assert artifacts[0].is_current is False
    new_artifact = artifacts[1]
    assert new_artifact.version == 2
    assert new_artifact.is_current is True
    assert new_artifact.infographic_path != old_artifact.infographic_path
    assert new_artifact.executable_path != old_artifact.executable_path

    executions = db_session.query(AgentExecution).filter(
        AgentExecution.project_id == match.project_id,
        AgentExecution.task_key.in_(['implement_prototype', 'implement_infographic']),
    ).all()
    assert executions, '실제 구현 Agent 호출이 agent_executions에 기록돼야 한다'
    assert all(e.rerun_type == 'initial' for e in executions)
    assert all(e.status == projects_router.ps.GENERATION_STATUS_COMPLETED for e in executions)

    # [조건 2-3] 이 교체는 사용자의 재작성이 아니므로 rework_cap 카운트(retry_task와 같은
    # 필터: rerun_type='rerun' AND status='completed')에 잡히면 안 된다.
    rework_used = db_session.query(AgentExecution).filter(
        AgentExecution.project_id == match.project_id,
        AgentExecution.task_key.in_(['implement_prototype', 'implement_infographic']),
        AgentExecution.rerun_type == 'rerun',
        AgentExecution.status == projects_router.ps.GENERATION_STATUS_COMPLETED,
    ).count()
    assert rework_used == 0


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
    first = projects_router._try_claim_and_run(match.project_id, running, done)
    second = projects_router._try_claim_and_run(match.project_id, running, done)

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


def _wait_until_status(db_session, match: Project, status: str, timeout_s: float = 5.0) -> None:
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
    """[2026-09-23 개정, 2026-09-26 단위 정정] 첫 실패에서 바로 status='failed'가 되면
    안 된다 — 15분 뒤 자동 재개를 예약한 status='waiting_resume'이 되고, resume_count가
    1이 돼야 한다(공식 기능정의서 v1.9 R-11 — 세션 초반엔 단위 없이 전달받아 초로
    잘못 구현했던 걸 정정)."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    _monkeypatch_boom(monkeypatch)

    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-BACKOFF1')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 0
    match.worker_claimed_at = None
    db_session.commit()

    claimed = projects_router._try_claim_and_run(
        match.project_id, projects_router.ps.STAGE_PLAN_WRITING, projects_router.ps.STAGE_PLAN_REVIEW_PENDING,
    )
    assert claimed is True

    _wait_until_status(db_session, match, 'waiting_resume')
    assert match.stage == projects_router.ps.STAGE_PLAN_WRITING, '실패해도 stage는 실패한 단계 그대로여야 함'
    assert '더미 에이전트 강제 실패' in (match.failure_reason or '')
    assert match.resume_count == 1
    assert match.next_retry_at is not None
    expected_delay = projects_router.GENERATION_RESUME_BASE_SECONDS  # 1번째 재개 = 기본 간격(15분)
    actual_delay = (match.next_retry_at - datetime.datetime.utcnow()).total_seconds()
    assert expected_delay - 2 < actual_delay <= expected_delay, f'1번째 백오프는 {expected_delay}초여야 함(실제 {actual_delay})'
    assert match.resume_started_at is not None, '실패 스트릭 시작 시각이 기록돼야 함(재개 총 대기 상한 계산용)'
    assert match.last_error_kind == projects_router.ps.ERROR_KIND_TRANSIENT, '분류할 키워드가 없는 일반 예외는 일시 오류로 봐야 함'

    # 아직 재개 5회를 다 못 썼으니 관리자 알림은 안 생겨야 한다.
    alerts = db_session.query(projects_router.GenerationFailureAlert).filter_by(project_id=match.project_id).all()
    assert alerts == [], '재시도 여지가 남아있는 실패는 관리자 알림 대상이 아님'


def test_operational_error_fails_immediately_without_resume(authed_client, db_session, monkeypatch):
    """[2026-09-27 신규, SB-134] 공식 기능정의서 v1.9 R-11 — "재개는 일시 오류일 때만
    하며 ... 영구 오류가 나면 실행을 실패로 끝낸다." API 연결·키 만료·크레딧 소진 같은
    운영 오류는 재개(백오프 대기)를 시도하지 않고 바로 status='failed'로 확정되고,
    resume_count는 늘어나지 않아야 한다(재개를 시도한 적이 없으므로)."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    _monkeypatch_boom(monkeypatch, message='결제 크레딧 소진으로 호출 실패(테스트)')

    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-OPFAIL')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 0
    match.worker_claimed_at = None
    db_session.commit()

    claimed = projects_router._try_claim_and_run(
        match.project_id, projects_router.ps.STAGE_PLAN_WRITING, projects_router.ps.STAGE_PLAN_REVIEW_PENDING,
    )
    assert claimed is True

    _wait_until_status(db_session, match, 'failed')
    assert match.last_error_kind == projects_router.ps.ERROR_KIND_OPERATIONAL
    assert match.resume_count == 0, '재개를 시도한 적이 없으므로 재개 횟수는 그대로여야 함'
    assert match.next_retry_at is None

    alerts = db_session.query(projects_router.GenerationFailureAlert).filter_by(project_id=match.project_id).all()
    assert len(alerts) == 1, '영구 오류는 재개 상한과 무관하게 즉시 관리자 알림이 생겨야 함'
    assert alerts[0].last_error_kind == projects_router.ps.ERROR_KIND_OPERATIONAL
    assert alerts[0].resume_count == 0


def test_stage_failure_records_agent_execution(authed_client, db_session, monkeypatch):
    """[2026-09-28 신규] 관리자 "에이전트 테스크" 탭이 단계(stage) 단위 실패도 볼 수
    있어야 한다 — _simulate_generation이 실패하면 match_results뿐 아니라
    agent_executions에도 status='failed' + error_kind/error_reason 행이 남아야 한다
    (app/pipeline_stages.py STAGE_TO_AGENT_TASK 참고)."""
    from app.models import AgentExecution

    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    _monkeypatch_boom(monkeypatch, message='결제 크레딧 소진으로 호출 실패(테스트)')

    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-AGENTLOG')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 0
    match.worker_claimed_at = None
    db_session.commit()

    claimed = projects_router._try_claim_and_run(
        match.project_id, projects_router.ps.STAGE_PLAN_WRITING, projects_router.ps.STAGE_PLAN_REVIEW_PENDING,
    )
    assert claimed is True

    _wait_until_status(db_session, match, 'failed')

    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.project_id == match.project_id, AgentExecution.task_key == 'writing')
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    assert execution is not None, 'stage 실패가 agent_executions에 안 남았음'
    assert execution.agent_name == '작성'
    assert execution.status == 'failed'
    assert execution.error_kind == projects_router.ps.ERROR_KIND_OPERATIONAL
    assert '결제 크레딧 소진' in execution.error_reason


def test_recovery_does_not_retry_before_next_retry_at(authed_client, db_session):
    """status='waiting_resume'이어도 next_retry_at이 아직 안 지났으면 복구 루프가
    건드리면 안 된다 — 백오프 간격을 지켜야 함."""
    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-BACKOFF-EARLY')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 40
    match.status = 'waiting_resume'
    match.resume_count = 1
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
    match.resume_count = 1
    match.failure_reason = '이전 실패(테스트)'
    match.worker_claimed_at = None
    match.next_retry_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)  # 이미 지남
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)
    assert match.status == 'in_progress', '클레임되면서 waiting_resume -> in_progress로 되돌아가야 함'
    assert match.resume_count == 0, '성공적으로 재개됐으면 실패 스트릭이 리셋돼야 함'
    assert match.progress_percent == 100


def test_max_retries_exhausted_marks_failed_and_creates_alert(authed_client, db_session, monkeypatch):
    """자동 재개 5회를 전부 소진하고도 실패하면 status='failed'로 확정되고,
    generation_failure_alerts에 관리자 알림 행이 하나 남아야 한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    _monkeypatch_boom(monkeypatch, message='6번째 실패(테스트)')

    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-CAP')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 70
    match.status = 'waiting_resume'
    match.resume_count = projects_router.GENERATION_RESUME_MAX_ATTEMPTS  # 이미 5회 소진
    match.resume_started_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
    match.worker_claimed_at = None
    match.next_retry_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)

    _wait_until_status(db_session, match, 'failed')
    assert match.resume_count == projects_router.GENERATION_RESUME_MAX_ATTEMPTS + 1
    assert match.next_retry_at is None
    assert '6번째 실패' in (match.failure_reason or '')

    alerts = db_session.query(projects_router.GenerationFailureAlert).filter_by(project_id=match.project_id).all()
    assert len(alerts) == 1, '재개 상한 도달 시 관리자 알림이 정확히 한 행 생겨야 함'
    alert = alerts[0]
    assert alert.project_id == match.project_id
    assert alert.stage == projects_router.ps.STAGE_PLAN_WRITING
    assert alert.resume_count == projects_router.GENERATION_RESUME_MAX_ATTEMPTS
    assert '6번째 실패' in (alert.failure_reason or '')


def test_resume_total_cap_exceeded_marks_failed_before_attempt_cap(authed_client, db_session, monkeypatch):
    """[2026-09-26 신규] 공식 기능정의서 v1.9의 "재개 총 대기 상한"(12시간) — 재개
    횟수(5번) 자체를 다 안 썼어도, 첫 실패 이후 12시간이 지났으면 그걸로 바로
    실패 확정돼야 한다(비용이 무한정 발산하지 않도록)."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    _monkeypatch_boom(monkeypatch, message='12시간 넘긴 재개(테스트)')

    match = _create_match(authed_client, db_session, 'NOTICE-ASYNC-TOTALCAP')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.progress_percent = 50
    match.status = 'waiting_resume'
    match.resume_count = 1  # 재개 횟수 상한(5)엔 한참 못 미침
    match.resume_started_at = datetime.datetime.utcnow() - datetime.timedelta(hours=13)  # 12시간 상한 초과
    match.worker_claimed_at = None
    match.next_retry_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    db_session.commit()

    projects_router._recover_orphaned_generations_once(db_session)

    _wait_until_status(db_session, match, 'failed')
    assert match.resume_count == 2, '재개 횟수 상한(5)엔 못 미쳤어도 실패로 확정돼야 함'

    alerts = db_session.query(projects_router.GenerationFailureAlert).filter_by(project_id=match.project_id).all()
    assert len(alerts) == 1
    assert alerts[0].acknowledged_at is None


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
    assert body['resume_count'] == 1

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)
    assert match.status == 'in_progress'
    assert match.failure_reason is None


# ============================================================================
# 화면 헤더 종모양 알림 — GET /projects(목록)의 display_status/재시도 필드
# (front/src/features/workflow/shared.jsx NotificationBell이 이 엔드포인트를 이미
# 폴링하고 있어서, 별도 알림 엔드포인트 대신 여기에 필드를 얹었다.)
# ============================================================================

def test_regenerate_fail_streak_blocks_plan_start_after_cap(authed_client, db_session, monkeypatch):
    """연속으로 regenerate_cap(기본 2)번 "처음부터 다시 생성"이 최종 실패하면, 그 다음
    POST /plan/start는 409로 막혀야 하고 마지막 확정 알림은 regenerate_exhausted=True로
    남아야 한다(관리자가 우선 확인할 건)."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-REGEN-CAP')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.status = 'failed'
    match.worker_claimed_at = None
    db_session.commit()

    _monkeypatch_boom(monkeypatch, message='결제 크레딧 소진으로 호출 실패(테스트)')

    for _ in range(2):  # verification_policies.regenerate_cap 기본값
        r = authed_client.post(f'/projects/{match.project_id}/plan/start')
        assert r.status_code == 200, r.text
        _wait_until_status(db_session, match, 'failed')

    assert match.regenerate_fail_streak == 2

    r3 = authed_client.post(f'/projects/{match.project_id}/plan/start')
    assert r3.status_code == 409, r3.text
    assert r3.json()['detail'] == '문제가 기록됐고 확인 후 조치할게요. 잠시 후 다시 시도해 주세요.'

    alert = (
        db_session.query(projects_router.GenerationFailureAlert)
        .filter_by(project_id=match.project_id)
        .order_by(projects_router.GenerationFailureAlert.alert_id.desc())
        .first()
    )
    assert alert.regenerate_exhausted is True, '상한에 닿은 마지막 확정 실패는 관리자가 우선 봐야 함'


def test_regenerate_success_resets_fail_streak(authed_client, db_session, monkeypatch):
    """이전에 몇 번 실패했더라도, "처음부터 다시 생성"이 이번엔 성공하면 연속 실패
    스트릭이 0으로, is_regenerating도 False로 완전히 되돌아가야 한다."""
    monkeypatch.setattr(projects_router, 'DUMMY_GENERATION_STEP_SECONDS', 0.02)
    match = _create_match(authed_client, db_session, 'NOTICE-REGEN-RESET')
    match.stage = projects_router.ps.STAGE_PLAN_WRITING
    match.status = 'failed'
    match.regenerate_fail_streak = 1  # 이전에 한 번 실패했던 상태를 흉내
    match.worker_claimed_at = None
    db_session.commit()

    r = authed_client.post(f'/projects/{match.project_id}/plan/start')
    assert r.status_code == 200, r.text

    _wait_until_done(db_session, match, projects_router.ps.STAGE_PLAN_REVIEW_PENDING)
    assert match.regenerate_fail_streak == 0
    assert match.is_regenerating is False


def test_task_level_retry_still_uses_rerun_not_regenerate(authed_client, db_session):
    """task별 재작성(POST /retry-task)은 "처음부터 다시 생성"과 무관한 별개 경로이므로,
    Project.is_regenerating이 켜져 있어도 agent_executions.rerun_type은 여전히
    'rerun'이어야 한다(회귀 방지 — 두 예산을 헷갈리면 안 됨)."""
    from app.models import AgentExecution

    match = _create_match(authed_client, db_session, 'NOTICE-REGEN-VS-RERUN')
    match.stage = projects_router.ps.STAGE_DONE
    match.status = 'completed'
    match.is_regenerating = True  # 다른 stage 재시도가 아직 안 끝난 상황을 흉내
    db_session.commit()

    r = authed_client.post(
        f'/projects/{match.project_id}/retry-task',
        json={'task_key': 'writing', 'bundle_id': projects_router.ps.WRITING_BUNDLES[0]},
    )
    assert r.status_code == 200, r.text

    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.project_id == match.project_id, AgentExecution.task_key == 'writing')
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    assert execution is not None
    assert execution.rerun_type == 'rerun'


def test_classify_error_kind_prefers_declared_error_kind_over_keywords(authed_client, db_session):
    """[2026-09-29 신규, 프론트 요청사항 3차 B-3] 실제 Agent가 붙으면 Orchestration
    tools.llm이 올리는 예외(예: ToolCallExhausted)가 error_kind 속성을 이미 실어서 온다
    — 메시지 키워드로 다시 추측하지 말고 그 값을 그대로 써야 한다. 아래 예외는 메시지에
    '크레딧'(운영 키워드)이 들어있지만 error_kind='입력'을 명시적으로 실어 보냈으므로,
    분류 결과는 '입력'이어야 한다(키워드 추측이 이겼다면 '운영'이 나왔을 것)."""

    class _FakeToolCallExhausted(Exception):
        def __init__(self, message, error_kind):
            super().__init__(message)
            self.error_kind = error_kind

    exc = _FakeToolCallExhausted('크레딧 관련 입력값이 스키마와 안 맞음', projects_router.ps.ERROR_KIND_INPUT)
    assert projects_router.ps.classify_error_kind(exc) == projects_router.ps.ERROR_KIND_INPUT
