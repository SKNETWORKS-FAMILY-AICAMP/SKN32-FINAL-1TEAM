"""POST /projects/{id}/retry-task 확장분 검증 (pytest 버전) — tests/verify_retry_task.py는
"재시도하면 값이 실제로 바뀌는가"를 검증하고, 이 파일은 2026-09-18에 추가된 두 가지를
검증한다:

1. verify1_*/verify2_* 재시도가 verification_score_history에 새 행(is_rerun=True)을
   남기는지 — 예전엔 plan.doc_score/artifact.artifact_score만 갱신하고 이력을 안 남겨서
   관리자 대시보드 "운영 현황"의 채점 편차(1회→2회)가 항상 0건으로 보이는 버그가 있었다.
2. review_token_check 재시도가 attempt_no를 증가시키고, 보호 토큰 위반 시
   passed=False/violation_type/violation_note/recovery_status='pending'을 남기는지.

app.agents.run_review_token_check_retry는 무작위 판정이라 이 파일에서는 결정론적 결과를
얻기 위해 monkeypatch로 갈아치운다.
"""
import pytest

from app.models import Company, Notice, Project, User, VerificationPolicy
from app.security import issue_access_token
from seed_dummy_pipeline import seed_dummy_pipeline


def _client_for(user_id: int):
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    token = issue_access_token(user_id)
    client.cookies.set('sbrain_session', token)
    return client


@pytest.fixture()
def retry_setup(db_session):
    email = 'retry-test@example.com'
    user = User(email=email, name='재시도테스트', google_sub='sub-retry-test', role='user', status='active')
    db_session.add(user)
    db_session.flush()
    company = Company(user_id=user.user_id, ceo_name='재시도테스트')
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.company_id, description='재시도 검증용 프로젝트')
    db_session.add(project)
    db_session.flush()
    notice = Notice(
        notice_id=f'RETRY-TEST-{project.project_id}', source='k-startup',
        title='재시도 검증용 공고', recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project.project_id, notice_id=notice.notice_id, retry_agents=())
    # [2026-09-28 신규] 이 파일의 여러 테스트가 같은 task_key를 반복 호출해 "값이 실제로
    # 바뀌는지"만 본다 — rework_cap(재작성 상한, 기본 1)의 409는 별도 테스트
    # (test_retry_task_enforces_rework_cap)에서 다루므로, 여기 공용 fixture에서는 상한을
    # 넉넉히 풀어둔다.
    policy = db_session.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    policy.rework_cap = 10
    db_session.commit()
    client = _client_for(user.user_id)
    return {'client': client, 'project_id': project.project_id, 'plan_id': verdict.plan_id}


def _retry(client, project_id, task_key, bundle_id=None):
    # writing은 bundle_id가 필수라서(app/pipeline_stages.py WRITING_BUNDLES), 이 파일의
    # 다른 테스트들이 다 고쳐 쓰지 않도록 기본값(문제인식)을 여기서 채워준다 — 묶음
    # 간 독립을 직접 검증하는 테스트만 bundle_id를 명시적으로 넘긴다.
    body = {'task_key': task_key}
    if task_key == 'writing':
        from app import pipeline_stages as ps
        body['bundle_id'] = bundle_id or ps.BUNDLE_PSST_PROBLEM
    elif bundle_id is not None:
        body['bundle_id'] = bundle_id
    return client.post(f'/projects/{project_id}/retry-task', json=body)


# ============================================================================
# verification_score_history — 재채점 시 이력이 실제로 쌓이는지
# ============================================================================

def test_verify1_retry_appends_score_history(retry_setup, db_session):
    from app.models import VerificationScoreHistory

    before = (
        db_session.query(VerificationScoreHistory)
        .filter(VerificationScoreHistory.plan_id == retry_setup['plan_id'], VerificationScoreHistory.layer == 'doc')
        .count()
    )
    res = _retry(retry_setup['client'], retry_setup['project_id'], 'verify1_rubric')
    assert res.status_code == 200, res.text

    db_session.expire_all()
    rows = (
        db_session.query(VerificationScoreHistory)
        .filter(VerificationScoreHistory.plan_id == retry_setup['plan_id'], VerificationScoreHistory.layer == 'doc')
        .order_by(VerificationScoreHistory.history_id.asc())
        .all()
    )
    assert len(rows) == before + 1, '재채점 후 doc layer 이력이 안 늘었음'
    assert rows[-1].is_rerun is True
    assert rows[-1].applied_pass_threshold is not None


def test_verify2_retry_appends_score_history(retry_setup, db_session):
    from app.models import VerificationScoreHistory

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'verify2_static')
    assert res.status_code == 200, res.text

    db_session.expire_all()
    rows = (
        db_session.query(VerificationScoreHistory)
        .filter(VerificationScoreHistory.plan_id == retry_setup['plan_id'], VerificationScoreHistory.layer == 'code')
        .order_by(VerificationScoreHistory.history_id.asc())
        .all()
    )
    assert len(rows) == 2, 'seed에서 1건 + retry에서 1건 = 2건이어야 함'
    assert rows[-1].is_rerun is True


def test_repeated_verify1_retry_keeps_appending(retry_setup, db_session):
    """이 gap을 고치기 전엔 재채점을 몇 번 해도 이력이 하나도 안 늘었다 — 여러 번 불러서
    매번 늘어나는지까지 확인한다(1회만 늘고 멈추는 반쪽짜리 수정을 방지)."""
    from app.models import VerificationScoreHistory

    for _ in range(3):
        res = _retry(retry_setup['client'], retry_setup['project_id'], 'verify1_evidence')
        assert res.status_code == 200, res.text

    db_session.expire_all()
    count = (
        db_session.query(VerificationScoreHistory)
        .filter(VerificationScoreHistory.plan_id == retry_setup['plan_id'], VerificationScoreHistory.layer == 'doc')
        .count()
    )
    assert count == 1 + 3  # seed 1건 + retry 3건


# ============================================================================
# 작성/구현 재시도에 딸려오는 자동 재검증 (2026-09-18 추가)
# ============================================================================

def test_strategy_retry_writes_canonical_data_not_sections(retry_setup, db_session):
    """[2026-09-22] '전략' 재시도는 이제 plan_sections가 아니라 plan_canonical_data에 쓴다 —
    구글 드라이브 "전략/작성/검증1" 시트의 Strategy Agent(F01~F15, 분석 자료 생성)와
    Writing Agent(F16, 최종 문단 작성) 구분에 맞춘 것(app/agents.py 모듈 docstring 참고)."""
    from app.models import PlanCanonicalData

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'strategy')
    assert res.status_code == 200, res.text
    changed = res.json()['changed']
    assert 'canonical_data' in changed
    assert set(changed['canonical_data']) == {'market_analysis', 'growth_strategy'}

    db_session.expire_all()
    rows = (
        db_session.query(PlanCanonicalData)
        .filter(PlanCanonicalData.plan_id == retry_setup['plan_id'])
        .all()
    )
    assert {r.data_key for r in rows} == {'market_analysis', 'growth_strategy'}

    # 다시 호출해도 (plan_id, data_key) 유일성 때문에 새 행이 추가되는 게 아니라 갱신돼야 한다.
    res2 = _retry(retry_setup['client'], retry_setup['project_id'], 'strategy')
    assert res2.status_code == 200, res2.text
    db_session.expire_all()
    count = (
        db_session.query(PlanCanonicalData)
        .filter(PlanCanonicalData.plan_id == retry_setup['plan_id'])
        .count()
    )
    assert count == 2, '재시도할 때마다 새 행이 쌓이면 안 됨 — upsert여야 함'


def test_writing_retry_also_rescores_verify1(retry_setup, db_session):
    """"본문 작성을 재작성했는데 점수가 그대로다"는 지적(하정원님) — 화면에 검증-1을 따로
    재시도하는 버튼이 없어서 실제로 점수를 바꿀 방법이 없었다. writing 재시도에 검증-1
    (rubric+evidence) 재채점을 자동으로 붙여 고쳤다."""
    from app.models import VerificationScoreHistory

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res.status_code == 200, res.text
    assert 'verify1_rescore' in res.json()['changed']
    assert set(res.json()['changed']['verify1_rescore']) == {'verify1_rubric', 'verify1_evidence'}

    db_session.expire_all()
    count = (
        db_session.query(VerificationScoreHistory)
        .filter(VerificationScoreHistory.plan_id == retry_setup['plan_id'], VerificationScoreHistory.layer == 'doc')
        .count()
    )
    assert count == 1 + 2  # seed 1건 + writing이 자동으로 붙인 rubric/evidence 2건


def test_implement_prototype_retry_also_rescores_verify2(retry_setup, db_session):
    from app.models import VerificationScoreHistory

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'implement_prototype')
    assert res.status_code == 200, res.text
    assert 'verify2_rescore' in res.json()['changed']
    assert set(res.json()['changed']['verify2_rescore']) == {'verify2_static', 'verify2_crosscheck'}

    db_session.expire_all()
    count = (
        db_session.query(VerificationScoreHistory)
        .filter(VerificationScoreHistory.plan_id == retry_setup['plan_id'], VerificationScoreHistory.layer == 'code')
        .count()
    )
    assert count == 1 + 2  # seed 1건 + implement가 자동으로 붙인 static/crosscheck 2건


# ============================================================================
# output_ref — SB-148: agent_executions가 산출물 참조({table,id})를 남기는지
# (프롬프트/응답 원문이 아니라 참조만 — agent-orchestration 저장소의 ExecutionRecord/
# CallLog 설계를 관계형 id로 옮긴 것)
# ============================================================================

def test_strategy_retry_records_output_ref_to_canonical_data(retry_setup, db_session):
    from app.models import AgentExecution, PlanCanonicalData

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'strategy')
    assert res.status_code == 200, res.text

    db_session.expire_all()
    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.task_key == 'strategy')
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    assert execution.output_ref is not None
    tables = {ref['table'] for ref in execution.output_ref}
    assert tables == {'plan_canonical_data'}
    ids = {ref['id'] for ref in execution.output_ref}
    real_ids = {
        r.data_id for r in db_session.query(PlanCanonicalData).filter(PlanCanonicalData.plan_id == retry_setup['plan_id'])
    }
    assert ids == real_ids


def test_writing_retry_records_output_ref_to_plan_sections(retry_setup, db_session):
    from app.models import AgentExecution, PlanSection

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res.status_code == 200, res.text

    db_session.expire_all()
    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.task_key == 'writing')
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    assert execution.output_ref is not None
    for ref in execution.output_ref:
        assert ref['table'] == 'plan_sections'
        section = db_session.get(PlanSection, ref['id'])
        assert section is not None and section.plan_id == retry_setup['plan_id']


def test_implement_prototype_retry_records_output_ref_to_artifact(retry_setup, db_session):
    from app.models import AgentExecution, Artifact

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'implement_prototype')
    assert res.status_code == 200, res.text

    db_session.expire_all()
    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.task_key == 'implement_prototype')
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    # [SB-155] 재시도마다 새 버전 행이 쌓이므로(is_current 여부와 무관), output_ref는
    # 방금 만들어진(가장 최근) 행을 가리켜야 한다.
    artifact = (
        db_session.query(Artifact).filter(Artifact.plan_id == retry_setup['plan_id'])
        .order_by(Artifact.artifact_id.desc()).first()
    )
    assert execution.output_ref == {'table': 'artifacts', 'id': artifact.artifact_id}


def test_review_token_check_retry_records_output_ref_to_proofread_log(retry_setup, db_session):
    from app.models import AgentExecution, ProofreadLog

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res.status_code == 200, res.text

    db_session.expire_all()
    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.task_key == 'review_token_check')
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    assert execution.output_ref['table'] == 'proofread_logs'
    log = db_session.get(ProofreadLog, execution.output_ref['id'])
    assert log is not None and log.plan_id == retry_setup['plan_id']


# ============================================================================
# review_token_check — attempt_no / passed / violation_* / recovery_status
# ============================================================================

def test_review_token_check_increments_attempt_no(retry_setup, db_session):
    from app.models import ProofreadLog

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res.status_code == 200, res.text
    res2 = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res2.status_code == 200, res2.text

    db_session.expire_all()
    rows = (
        db_session.query(ProofreadLog)
        .filter(ProofreadLog.plan_id == retry_setup['plan_id'])
        .order_by(ProofreadLog.attempt_no.asc())
        .all()
    )
    # seed_dummy_pipeline이 이미 attempt_no=1인 행을 하나 만들어두므로 재시도 2번이면 2,3이 된다.
    assert [r.attempt_no for r in rows] == [1, 2, 3]


def test_review_token_check_violation_sets_recovery_pending(monkeypatch, retry_setup, db_session):
    import app.routers.projects as projects_router
    from app.models import ProofreadLog

    monkeypatch.setattr(
        projects_router.agents, 'run_review_token_check_retry',
        lambda description, attempt_no=1: projects_router.agents.ProofreadResult(
            corrected_text='(고정 시도안) 반려될 예정',
            reason='테스트 고정 반려',
            passed=False,
            violation_type='수치·금액',
            violation_note='테스트로 고정한 위반 사유',
        ),
    )
    res = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['changed']['passed'] is False
    assert body['changed']['violation_type'] == '수치·금액'

    db_session.expire_all()
    latest = (
        db_session.query(ProofreadLog)
        .filter(ProofreadLog.plan_id == retry_setup['plan_id'])
        .order_by(ProofreadLog.log_id.desc())
        .first()
    )
    assert latest.passed is False
    assert latest.violation_type == '수치·금액'
    assert latest.recovery_status == 'pending'


def test_review_token_check_stores_score_from_agent_result(monkeypatch, retry_setup, db_session):
    from decimal import Decimal

    import app.routers.projects as projects_router
    from app.models import ProofreadLog

    monkeypatch.setattr(
        projects_router.agents, 'run_review_token_check_retry',
        lambda description, attempt_no=1: projects_router.agents.ProofreadResult(
            corrected_text='(고정 시도안) 80점', reason='테스트 고정 점수',
            score=Decimal('80'), passed=True,
        ),
    )
    res = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res.status_code == 200, res.text
    assert res.json()['changed']['score']['after'] == 80.0

    db_session.expire_all()
    latest = (
        db_session.query(ProofreadLog)
        .filter(ProofreadLog.plan_id == retry_setup['plan_id'])
        .order_by(ProofreadLog.log_id.desc())
        .first()
    )
    assert latest.score == Decimal('80.00')


def test_retry_task_failure_is_recorded_on_agent_execution(monkeypatch, retry_setup, db_session):
    """[2026-09-28 신규] 지금은 app.agents.run_*_retry()가 전부 더미(무작위)라 실패할
    일이 없지만, 실제 Agent가 연동된 뒤 예외가 나면 (1) agent_executions에 status='failed'
    행이 남고 error_kind/error_reason이 채워져야 하고, (2) 클라이언트는 502와 함께
    구조화된 오류를 받아야 한다 — 프론트가 "이 재시도가 재시도 가능한 오류인지"를
    error_kind로 구분할 수 있어야 하기 때문."""
    import app.routers.projects as projects_router
    from app.models import AgentExecution

    def _boom(description, tags):
        raise RuntimeError('결제 크레딧 소진(테스트)')  # 운영 오류로 분류돼야 함

    monkeypatch.setattr(projects_router.agents, 'run_writing_agent_retry', _boom)

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res.status_code == 502, res.text
    detail = res.json()['detail']
    assert detail['task_key'] == 'writing'
    assert detail['error_kind'] == projects_router.ps.ERROR_KIND_OPERATIONAL

    db_session.expire_all()
    failed = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.project_id == retry_setup['project_id'], AgentExecution.task_key == 'writing')
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    assert failed.status == 'failed'
    assert failed.error_kind == projects_router.ps.ERROR_KIND_OPERATIONAL
    assert '결제 크레딧 소진' in failed.error_reason


def test_review_token_check_success_leaves_recovery_null(monkeypatch, retry_setup, db_session):
    import app.routers.projects as projects_router
    from app.models import ProofreadLog

    monkeypatch.setattr(
        projects_router.agents, 'run_review_token_check_retry',
        lambda description, attempt_no=1: projects_router.agents.ProofreadResult(
            corrected_text='(고정 시도안) 통과',
            reason='테스트 고정 통과',
            passed=True,
        ),
    )
    res = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res.status_code == 200, res.text
    assert res.json()['changed']['passed'] is True

    db_session.expire_all()
    latest = (
        db_session.query(ProofreadLog)
        .filter(ProofreadLog.plan_id == retry_setup['plan_id'])
        .order_by(ProofreadLog.log_id.desc())
        .first()
    )
    assert latest.passed is True
    assert latest.recovery_status is None
    assert latest.violation_type is None


def test_review_token_check_multi_attempt_ordering_and_fields_are_independent(monkeypatch, retry_setup, db_session):
    """[SB-165 후속] 프론트 reviewParagraphsFrom(front/src/features/workflow/utils.js)이
    이제 plan.proofread_logs를 section_id로 묶어 attempt_no 순으로 "1차 반려 → 2차 통과"를
    그린다 — 그 전제(같은 section 안에서 attempt_no가 1,2,3... 순서대로 매겨지고, 각 행의
    passed/violation_type/violation_note가 이전/다음 시도 값과 섞이지 않는다)를 직접
    검증한다. 위의 increments_attempt_no 테스트는 순서만, violation_sets_recovery_pending/
    success_leaves_recovery_null은 필드값만 각각 한 시도로 따로 보므로, 이 테스트는 그
    둘을 실패→통과 한 흐름 안에서 같이 본다."""
    import app.routers.projects as projects_router
    from app.models import ProofreadLog

    results = [
        projects_router.agents.ProofreadResult(
            corrected_text='(고정 1차 시도) 반려될 예정', reason=None, passed=False,
            violation_type='수치·금액', violation_note='1차 반려 사유(테스트)',
        ),
        projects_router.agents.ProofreadResult(
            corrected_text='(고정 2차 시도) 통과', reason='띄어쓰기 교정(테스트)', passed=True,
        ),
    ]
    calls = iter(results)
    monkeypatch.setattr(
        projects_router.agents, 'run_review_token_check_retry',
        lambda description, attempt_no=1: next(calls),
    )

    res1 = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res1.status_code == 200, res1.text
    res2 = _retry(retry_setup['client'], retry_setup['project_id'], 'review_token_check')
    assert res2.status_code == 200, res2.text

    db_session.expire_all()
    rows = (
        db_session.query(ProofreadLog)
        .filter(ProofreadLog.plan_id == retry_setup['plan_id'])
        .order_by(ProofreadLog.attempt_no.asc())
        .all()
    )
    # seed_dummy_pipeline이 attempt_no=1인 통과 행을 하나 미리 만들어두므로(이 흐름과는
    # 무관한 seed 시도) 이 테스트의 1차/2차는 attempt_no 2·3이 된다 — 순서 자체가 핵심이라
    # attempt_no 절대값이 아니라 "증가 순서 + 그 순서에 맞는 필드"로 검증한다.
    assert len(rows) == 3
    seeded, first_attempt, second_attempt = rows
    assert [r.attempt_no for r in rows] == sorted(r.attempt_no for r in rows), 'attempt_no가 오름차순이 아님'

    assert first_attempt.passed is False
    assert first_attempt.violation_type == '수치·금액'
    assert first_attempt.violation_note == '1차 반려 사유(테스트)'
    assert first_attempt.recovery_status == 'pending'

    # 2차 시도가 1차의 반려 흔적(violation_type/note)을 물려받으면 안 된다 — 독립적이어야
    # reviewParagraphsFrom이 "2차는 통과, issue 없음"으로 정확히 그릴 수 있다.
    assert second_attempt.passed is True
    assert second_attempt.violation_type is None
    assert second_attempt.violation_note is None
    assert second_attempt.recovery_status is None
    assert second_attempt.corrected_text == '(고정 2차 시도) 통과'

    # 같은 section에 묶여야 프론트가 하나의 문단(스포트라이트)으로 인식한다.
    assert first_attempt.section_id == second_attempt.section_id == seeded.section_id


# ============================================================================
# rework_cap(재작성 상한) — 프론트 요청 1·2 (2026-09-28)
# ============================================================================

def test_retry_task_enforces_rework_cap(retry_setup, db_session):
    """retry_setup fixture가 rework_cap을 10으로 풀어두므로, 여기서는 이 테스트 전용으로
    1로 다시 낮춰서 실제 상한 동작(1회는 성공, 2회째는 409)을 검증한다."""
    from app.models import VerificationPolicy

    policy = db_session.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    policy.rework_cap = 1
    db_session.commit()

    res1 = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res1.status_code == 200, res1.text

    res2 = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res2.status_code == 409, res2.text
    assert '1회' in res2.json()['detail']

    # 다른 task_key는 상한을 공유하지 않는다(항목마다 1회).
    res3 = _retry(retry_setup['client'], retry_setup['project_id'], 'strategy')
    assert res3.status_code == 200, res3.text


def test_rework_cap_is_counted_per_bundle_not_per_task_key(retry_setup, db_session):
    """버그 재현/회귀 방지 — writing 하나가 화면상 묶음 여러 개(PSST 4항목)를 가리켜서,
    task_key로만 세면 "실현가능성" 1회 재작성했다고 "성장전략" 재작성까지 막혀버렸다
    (프론트 답변 md "⚠ 중요 — bundle_id를 task_key로 잡으면 안 됩니다" 참고). 묶음마다
    따로 1회씩 허용돼야 한다."""
    from app import pipeline_stages as ps
    from app.models import VerificationPolicy

    policy = db_session.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    policy.rework_cap = 1
    db_session.commit()

    res1 = _retry(retry_setup['client'], retry_setup['project_id'], 'writing', ps.BUNDLE_PSST_SOLUTION)
    assert res1.status_code == 200, res1.text

    # 같은 묶음(실현가능성)을 또 재작성하면 막힌다.
    res2 = _retry(retry_setup['client'], retry_setup['project_id'], 'writing', ps.BUNDLE_PSST_SOLUTION)
    assert res2.status_code == 409, res2.text

    # 다른 묶음(성장전략)은 아직 안 썼으므로 여전히 가능해야 한다 — 이게 고친 버그.
    res3 = _retry(retry_setup['client'], retry_setup['project_id'], 'writing', ps.BUNDLE_PSST_SCALEUP)
    assert res3.status_code == 200, res3.text


def test_writing_retry_without_bundle_id_is_rejected(retry_setup):
    res = retry_setup['client'].post(
        f'/projects/{retry_setup["project_id"]}/retry-task', json={'task_key': 'writing'},
    )
    assert res.status_code == 400, res.text
    assert 'bundle_id' in res.json()['detail']


def test_implement_prototype_bundle_id_mismatch_is_rejected(retry_setup):
    res = retry_setup['client'].post(
        f'/projects/{retry_setup["project_id"]}/retry-task',
        json={'task_key': 'implement_prototype', 'bundle_id': '인포그래픽 제작'},
    )
    assert res.status_code == 400, res.text
    assert 'bundle_id' in res.json()['detail']


def test_failed_rework_does_not_consume_cap(monkeypatch, retry_setup, db_session):
    """기획서 5-6절 "재작성이 실패하면 쓴 기회를 돌려준다" — 실패한 시도는 rework_cap을
    소진하지 않아야 하므로, 실패 뒤 같은 task_key를 다시 불러도(rework_cap=1이어도)
    여전히 성공해야 한다."""
    import app.routers.projects as projects_router
    from app.models import VerificationPolicy

    policy = db_session.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    policy.rework_cap = 1
    db_session.commit()

    def _boom(description, tags):
        raise RuntimeError('일시 오류(테스트)')

    monkeypatch.setattr(projects_router.agents, 'run_writing_agent_retry', _boom)
    res1 = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res1.status_code == 502, res1.text

    monkeypatch.undo()
    res2 = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res2.status_code == 200, res2.text


def test_result_response_includes_rework_cap_and_bundle_usages(retry_setup, db_session):
    """프론트 요청 2 — GET /projects/{id}/result가 rework_cap과 묶음별 사용/잔여 횟수를
    내려줘야 프론트가 RERUN_CAP 상수 없이 화면을 그릴 수 있다. [2026-09-28 수정] task_key
    기준이던 retry_budget을 bundle_id 기준 bundle_usages로 바꿨다 — writing 하나가 화면상
    묶음 여러 개(PSST 4항목)를 가리켜서 task_key만으로는 셀 수 없었기 때문(프론트 답변 md
    참고). strategy처럼 화면에 재작성 버튼이 없는 task_key는 더 이상 이 목록에 없다."""
    from app import pipeline_stages as ps
    from app.models import VerificationPolicy

    policy = db_session.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    policy.rework_cap = 1
    db_session.commit()

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'writing', ps.BUNDLE_PSST_PROBLEM)
    assert res.status_code == 200, res.text

    result = retry_setup['client'].get(f'/projects/{retry_setup["project_id"]}/result')
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['rework_cap'] == 1

    usage_by_bundle = {item['bundle_id']: item for item in body['bundle_usages']}
    assert usage_by_bundle[ps.BUNDLE_PSST_PROBLEM] == {
        'bundle_id': ps.BUNDLE_PSST_PROBLEM, 'layer': 'document', 'used': 1, 'remaining': 0,
    }
    # 다른 묶음은 안 건드렸으니 그대로 남아있어야 한다(버그였다면 여기도 0으로 깎였을 것).
    assert usage_by_bundle[ps.BUNDLE_PSST_SOLUTION]['remaining'] == 1
    assert usage_by_bundle[ps.BUNDLE_PSST_SCALEUP]['remaining'] == 1
    assert usage_by_bundle[ps.BUNDLE_PSST_TEAM]['remaining'] == 1
    assert usage_by_bundle[ps.BUNDLE_ARTIFACT_PROTOTYPE]['remaining'] == 1
    assert usage_by_bundle[ps.BUNDLE_ARTIFACT_INFOGRAPHIC]['remaining'] == 1
    assert 'strategy' not in usage_by_bundle  # 재작성 버튼이 없는 task_key는 묶음이 아님

    writing_exec = next(e for e in body['agent_executions'] if e['task_key'] == 'writing' and e['rerun_type'] == 'rerun')
    assert writing_exec['attempt_no'] == 2  # seed(attempt_no=1) + retry(attempt_no=2)
    assert writing_exec['bundle_id'] == ps.BUNDLE_PSST_PROBLEM


# ============================================================================
# [2026-09-28 신규, 프론트 2차 요청 C] 재채점 시 reason_text도 같이 갱신되는지 —
# 예전엔 score/evidence_locator만 바뀌고 reason_text는 재채점 전 문장("...통과") 그대로
# 남아서, 점수가 떨어져도 사유는 "통과"라고 뜨는 모순이 있었다.
# ============================================================================

def test_verify2_retry_updates_reason_text(monkeypatch, retry_setup, db_session):
    from decimal import Decimal

    import app.routers.projects as projects_router
    from app.models import ArtifactScoreReason

    monkeypatch.setattr(
        projects_router.agents, 'run_verify2_retry',
        lambda rubric_items, *, check_kind: [
            projects_router.agents.ScoreItemResult(
                item_code=item_code, score=Decimal('0.00'), max_score=max_score,
                evidence_locator=None, reason_text='(테스트 고정) 재채점 후 미달 처리',
            )
            for item_code, max_score in rubric_items
        ],
    )
    res = _retry(retry_setup['client'], retry_setup['project_id'], 'verify2_static')
    assert res.status_code == 200, res.text

    db_session.expire_all()
    rows = (
        db_session.query(ArtifactScoreReason)
        .filter(ArtifactScoreReason.item_code.like('CHECK-%'))
        .all()
    )
    assert rows, 'CHECK-* 항목이 하나도 없음'
    for row in rows:
        assert row.score == Decimal('0.00')
        assert row.reason_text == '(테스트 고정) 재채점 후 미달 처리', (
            'reason_text가 재채점 후에도 안 바뀜 — 점수/사유 모순 버그 재발'
        )


# ============================================================================
# [2026-09-28 신규, 프론트 2차 요청 B-3] overall_passed는 저장된 값이 아니라 그 순간의
# 총점·기준값에서 유도해야 한다 — 재채점으로 점수가 기준 밑으로 떨어지면 판정도 같이
# 바뀌어야 한다(첫 결과가 통과였다는 사실인 first_pass_passed는 안 바뀌어야 정상).
# ============================================================================

def test_overall_passed_reflects_current_total_score_after_rescore(monkeypatch, retry_setup, db_session):
    from decimal import Decimal

    import app.routers.projects as projects_router
    from app.models import Verdict

    result = retry_setup['client'].get(f'/projects/{retry_setup["project_id"]}/result')
    assert result.status_code == 200, result.text
    before = result.json()['verdict']
    assert before['overall_passed'] is True, '테스트 전제(seed 기본값은 통과)가 깨짐'
    assert before['first_pass_passed'] is True

    # 코드 검증 8항목을 전부 0점으로 떨어뜨려서 총점이 기준(80) 밑으로 가게 만든다.
    monkeypatch.setattr(
        projects_router.agents, 'run_verify2_retry',
        lambda rubric_items, *, check_kind: [
            projects_router.agents.ScoreItemResult(
                item_code=item_code, score=Decimal('0.00'), max_score=max_score,
                evidence_locator=None, reason_text='(테스트 고정) 미달',
            )
            for item_code, max_score in rubric_items
        ],
    )
    res = _retry(retry_setup['client'], retry_setup['project_id'], 'verify2_static')
    assert res.status_code == 200, res.text

    result2 = retry_setup['client'].get(f'/projects/{retry_setup["project_id"]}/result')
    assert result2.status_code == 200, result2.text
    after = result2.json()['verdict']
    assert after['total_score'] < after['pass_threshold']
    assert after['overall_passed'] is False, (
        '총점이 기준 밑으로 떨어졌는데도 overall_passed가 True — 저장된 값을 그대로 내려주는 버그 재발'
    )
    # 최초 결과가 통과였다는 역사적 사실은 재채점으로 안 바뀌어야 한다.
    assert after['first_pass_passed'] is True

    db_session.expire_all()
    verdict_row = db_session.get(Verdict, db_session.query(Verdict.verdict_id).filter(
        Verdict.plan_id == retry_setup['plan_id']
    ).scalar())
    assert verdict_row.overall_passed is True, (
        '저장된 verdict.overall_passed까지 바뀌면 안 된다 — 판정은 읽는 시점에만 유도한다'
    )


# ============================================================================
# [2026-09-28 신규, 프론트 2차 요청 A-2] 재작성 전후 점수 비교 + 버전 보존(JSON 스냅샷).
# 기획서 5-6절: "재작성 전후의 검증 점수를 비교해 높은 쪽을 남긴다", "이전 결과는
# 삭제하지 않고 보존한다".
# ============================================================================

def test_writing_retry_rolls_back_when_score_drops(monkeypatch, retry_setup, db_session):
    from decimal import Decimal

    import app.routers.projects as projects_router
    from app.models import BusinessPlan

    plan = db_session.get(BusinessPlan, retry_setup['plan_id'])
    before_doc_score = plan.doc_score
    before_bodies = {s.tag: s.body for s in plan.sections}

    def _low_score(items):
        return [
            projects_router.agents.ScoreItemResult(
                item_code=item_code, score=Decimal('0.00'), max_score=max_score,
                evidence_locator=None, reason_text='(테스트 고정) 낮은 점수',
            )
            for item_code, max_score in items
        ]
    monkeypatch.setattr(projects_router.agents, 'run_verify1_rubric_retry', _low_score)
    monkeypatch.setattr(projects_router.agents, 'run_verify1_evidence_retry', _low_score)

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res.status_code == 200, res.text
    changed = res.json()['changed']
    assert changed['version_kept'] == 'previous'
    assert changed['version_comparison']['before_score'] == float(before_doc_score)

    db_session.expire_all()
    plan = db_session.get(BusinessPlan, retry_setup['plan_id'])
    assert plan.doc_score == before_doc_score, '점수가 떨어졌는데 doc_score가 되돌아가지 않음'
    for s in plan.sections:
        assert s.body == before_bodies[s.tag], f'{s.tag} 본문이 되돌아가지 않음(재작성 시도가 그대로 남음)'
    assert plan.version_history and plan.version_history[-1]['kept'] == 'previous'


def test_writing_retry_keeps_new_when_score_improves(monkeypatch, retry_setup, db_session):
    from decimal import Decimal

    import app.routers.projects as projects_router
    from app.models import BusinessPlan

    plan = db_session.get(BusinessPlan, retry_setup['plan_id'])
    # seed의 doc_score 기본값(58.50)은 plan_score_reasons 합계(28)보다 큰 "자리표시자"라서
    # (seed_dummy_pipeline.py DEFAULT_DOC_SCORE 참고), 항목을 만점 처리해도 그보다 낮게
    # 나온다 — "점수가 오르는" 시나리오를 확실히 만들려고 합계보다 낮은 값으로 미리 낮춰둔다.
    plan.doc_score = Decimal('10.00')
    db_session.commit()
    before_doc_score = plan.doc_score

    def _full_marks(items):
        return [
            projects_router.agents.ScoreItemResult(
                item_code=item_code, score=max_score, max_score=max_score,
                evidence_locator='test:fixed', reason_text='(테스트 고정) 만점',
            )
            for item_code, max_score in items
        ]
    monkeypatch.setattr(projects_router.agents, 'run_verify1_rubric_retry', _full_marks)
    monkeypatch.setattr(projects_router.agents, 'run_verify1_evidence_retry', _full_marks)

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'writing')
    assert res.status_code == 200, res.text
    changed = res.json()['changed']
    assert changed['version_kept'] == 'new'

    db_session.expire_all()
    plan = db_session.get(BusinessPlan, retry_setup['plan_id'])
    assert plan.doc_score > before_doc_score
    assert plan.version_history and plan.version_history[-1]['kept'] == 'new'


def test_implement_prototype_retry_keeps_old_version_current_when_score_drops(monkeypatch, retry_setup, db_session):
    """[SB-155] 점수가 낮아지면 새 버전 행은 만들어지되 is_current=False로 남고, 예전
    행(is_current=True)은 건드리지 않는다 — JSON 스냅샷을 되돌리던 예전 방식과 달리
    실제로 두 행이 DB에 공존한다."""
    import os
    from decimal import Decimal

    import app.routers.projects as projects_router
    from app.models import Artifact

    old = db_session.query(Artifact).filter(Artifact.plan_id == retry_setup['plan_id']).one()
    before_path = old.executable_path
    before_score = old.artifact_score
    before_version = old.version

    def _low_score(items, *, check_kind):
        return [
            projects_router.agents.ScoreItemResult(
                item_code=item_code, score=Decimal('0.00'), max_score=max_score,
                evidence_locator=None, reason_text='(테스트 고정) 낮은 점수',
            )
            for item_code, max_score in items
        ]
    monkeypatch.setattr(projects_router.agents, 'run_verify2_retry', _low_score)

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'implement_prototype')
    assert res.status_code == 200, res.text
    changed = res.json()['changed']
    assert changed['version_kept'] == 'previous'

    db_session.expire_all()
    rows = (
        db_session.query(Artifact).filter(Artifact.plan_id == retry_setup['plan_id'])
        .order_by(Artifact.artifact_id.asc()).all()
    )
    assert len(rows) == 2, '점수가 낮아져도 새 버전 행 자체는 쌓여야 한다(보존)'
    still_current, new_version = rows[0], rows[1]
    assert still_current.is_current is True
    assert still_current.executable_path == before_path
    assert still_current.artifact_score == before_score
    assert still_current.version == before_version

    assert new_version.is_current is False
    assert new_version.version == before_version + 1
    new_path = changed['executable_path']['after']
    assert new_version.executable_path == new_path
    assert new_path != before_path

    # [SB-155] "이전 결과는 삭제하지 않고 보존한다" — 채택되지 않은 새 버전도 파일은
    # 지우지 않는다(예전엔 고아 파일 방지로 즉시 지웠으나, 지금은 행 자체가 보존 대상).
    from app.routers.projects import UPLOAD_DIR
    disk_path = os.path.join(UPLOAD_DIR, os.path.basename(new_path))
    assert os.path.exists(disk_path), '채택 안 된 버전이어도 파일 자체는 보존돼야 함'


def test_implement_prototype_retry_switches_current_when_score_improves(monkeypatch, retry_setup, db_session):
    """[SB-155] 점수가 오르면 새 버전 행이 is_current=True가 되고, 예전 행은
    is_current=False로 내려간다(예전 행도 지우지 않고 그대로 보존).

    [파일 보존 회귀 테스트] 반대 방향(점수 하락 시 새 버전 파일 보존)은 위
    test_implement_prototype_retry_keeps_old_version_current_when_score_drops에서 이미
    검증한다 — 이 테스트는 그 짝: 새 버전이 채택돼도 밀려난 예전 버전의 파일을 지우면
    안 된다(SB-155 이전엔 rollback 시 os.remove로 고아 파일을 지웠으나, 지금은 예전
    버전도 히스토리로 보존 대상이라 디스크 파일도 절대 지우면 안 됨)."""
    import os

    import app.routers.projects as projects_router
    from app.models import Artifact

    old = db_session.query(Artifact).filter(Artifact.plan_id == retry_setup['plan_id']).one()
    old_artifact_id = old.artifact_id
    old_path = old.executable_path

    def _full_marks(items, *, check_kind):
        return [
            projects_router.agents.ScoreItemResult(
                item_code=item_code, score=max_score, max_score=max_score,
                evidence_locator='test:fixed', reason_text='(테스트 고정) 만점',
            )
            for item_code, max_score in items
        ]
    monkeypatch.setattr(projects_router.agents, 'run_verify2_retry', _full_marks)

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'implement_prototype')
    assert res.status_code == 200, res.text
    changed = res.json()['changed']
    assert changed['version_kept'] == 'new'

    db_session.expire_all()
    old = db_session.get(Artifact, old_artifact_id)
    assert old.is_current is False
    assert old.executable_path == old_path, '예전 행은 손대지 않고 그대로 보존돼야 함'

    current = (
        db_session.query(Artifact)
        .filter(Artifact.plan_id == retry_setup['plan_id'], Artifact.is_current.is_(True))
        .one()
    )
    assert current.artifact_id != old_artifact_id
    assert current.executable_path == changed['executable_path']['after']
    assert current.version == old.version + 1

    from app.routers.projects import UPLOAD_DIR
    old_disk_path = os.path.join(UPLOAD_DIR, os.path.basename(old_path))
    assert os.path.exists(old_disk_path), '새 버전이 채택돼도 밀려난 예전 버전 파일은 지우면 안 됨'


def test_implement_prototype_retry_cleans_up_file_when_transaction_fails(monkeypatch, retry_setup, db_session):
    """[SB-161 후속] 위 두 테스트는 "버전 행까지는 만들어졌는데 점수가 낮아/높아 채택
    여부만 갈리는" 정상 케이스의 파일 보존을 다룬다. 이 테스트는 그와 다른 경우 —
    파일은 디스크에 썼는데 그 직후 버전 행 생성/재채점(_rescore_verify2)이 실패해서
    트랜잭션 자체가 롤백되는 경우다. 이때는 그 파일을 가리키는 DB 행이 아예 없으므로
    "이전 결과는 삭제하지 않고 보존한다"(SB-155)의 보존 대상이 아니라 진짜 고아
    파일이다 — 트랜잭션이 롤백돼 Artifact 행 자체가 남지 않는지, 그리고 파일도 같이
    지워지는지를 확인한다."""
    import os

    import app.routers.projects as projects_router
    from app.models import Artifact
    from app.routers.projects import UPLOAD_DIR

    before_ids = {row.artifact_id for row in db_session.query(Artifact.artifact_id).all()}
    before_path = db_session.query(Artifact).filter(Artifact.plan_id == retry_setup['plan_id']).one().executable_path
    # UPLOAD_DIR은 테스트마다 새로 만드는 게 아니라 전체 스위트가 공유하는 실제 디렉터리라
    # (다른 테스트가 미리 써둔 파일들이 이미 있을 수 있음) 절대 개수가 아니라 이 호출
    # 전후로 "새로 생긴 파일이 있는가"만 diff로 본다.
    before_files = set(os.listdir(UPLOAD_DIR))

    def _boom(rubric_items, *, check_kind):
        raise RuntimeError('일시 오류(테스트) — 재채점 실패')
    monkeypatch.setattr(projects_router.agents, 'run_verify2_retry', _boom)

    res = _retry(retry_setup['client'], retry_setup['project_id'], 'implement_prototype')
    assert res.status_code == 502, res.text

    db_session.expire_all()
    rows = db_session.query(Artifact).filter(Artifact.plan_id == retry_setup['plan_id']).all()
    assert {r.artifact_id for r in rows} == before_ids, (
        '트랜잭션이 실패했는데 버전 행이 남아있음 — 롤백이 안 되고 있음'
    )
    assert rows[0].executable_path == before_path, '기존 행도 손대지 않아야 함'

    after_files = set(os.listdir(UPLOAD_DIR))
    assert after_files == before_files, f'고아 파일이 안 지워지고 남아있음: {after_files - before_files}'
