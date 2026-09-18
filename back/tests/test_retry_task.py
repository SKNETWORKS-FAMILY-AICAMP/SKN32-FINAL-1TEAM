"""POST /projects/{id}/retry-task 확장분 검증 (pytest 버전) — verify_retry_task.py는
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

from app.models import Company, Notice, Project, User
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
    db_session.commit()
    client = _client_for(user.user_id)
    return {'client': client, 'project_id': project.project_id, 'plan_id': verdict.plan_id}


def _retry(client, project_id, task_key):
    return client.post(f'/projects/{project_id}/retry-task', json={'task_key': task_key})


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
    from app.models import ProofreadLog
    import app.routers.projects as projects_router

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

    from app.models import ProofreadLog
    import app.routers.projects as projects_router

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


def test_review_token_check_success_leaves_recovery_null(monkeypatch, retry_setup, db_session):
    from app.models import ProofreadLog
    import app.routers.projects as projects_router

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
