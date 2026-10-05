"""DELETE /auth/me — 계정 삭제(탈퇴). 프로젝트 기획서 v1.10 6-7절.

실행:
    pytest tests/test_account_deletion.py -v
"""
import json

from app.models import (
    AgentExecution,
    Artifact,
    ArtifactScoreReason,
    BusinessPlan,
    Company,
    EligibilityCheck,
    GenerationFailureAlert,
    MatchScoreReason,
    Notice,
    Notification,
    PlanScoreReason,
    PlanSection,
    Project,
    ProjectPlanInput,
    RefreshToken,
    User,
    UserProfile,
    Verdict,
)
from seed_dummy_pipeline import seed_dummy_pipeline


def test_delete_account_with_no_projects_removes_user(authed_client, db_session):
    """가장 단순한 경우 — 프로젝트를 하나도 안 만든 계정도 깨끗하게 지워져야 한다."""
    user = db_session.query(User).one()
    assert db_session.query(UserProfile).filter_by(user_id=user.user_id).count() == 1  # authed_client가 기본 프로필 생성

    res = authed_client.delete('/auth/me')
    assert res.status_code == 204, res.text

    assert db_session.query(User).count() == 0
    assert db_session.query(UserProfile).count() == 0

    # 세션 쿠키가 지워져서 이후 요청은 인증 실패해야 한다.
    assert authed_client.get('/auth/me').status_code == 401


def test_delete_account_cascades_full_pipeline_data(authed_client, db_session):
    """[핵심] 계정 · 회사 · 프로젝트 · 매칭 · 계획서 · 산출물 · 검증 결과 · 알림까지
    전부 지워져야 한다(v1.10: "모든 실행 건을 삭제한다")."""
    payload = {'description': '탈퇴 테스트용 프로젝트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']

    notice = Notice(notice_id='ACCOUNT-DEL-001', source='k-startup', title='탈퇴 테스트용 더미 공고', recruitment_status='open')
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='ACCOUNT-DEL-001', retry_agents=())
    db_session.add(Notification(project_id=project_id, kind='문서평가', target_step=6))
    db_session.add(GenerationFailureAlert(
        project_id=project_id, stage='plan_writing',
        resume_count=5, last_error_kind='일시', failure_reason='탈퇴 전 마지막 실패(테스트)',
    ))
    db_session.commit()

    plan_id = verdict.plan_id
    artifact_id = verdict.artifact_id

    # 삭제 전 실제로 데이터가 있는지 먼저 확인 — 아니면 아래 0건 확인이 무의미해진다.
    assert db_session.query(PlanSection).filter_by(plan_id=plan_id).count() > 0
    assert db_session.query(ArtifactScoreReason).filter_by(artifact_id=artifact_id).count() > 0
    assert db_session.query(AgentExecution).filter_by(project_id=project_id).count() > 0

    res = authed_client.delete('/auth/me')
    assert res.status_code == 204, res.text

    assert db_session.query(User).count() == 0
    assert db_session.query(Company).count() == 0
    assert db_session.query(Project).count() == 0
    assert db_session.query(ProjectPlanInput).count() == 0
    assert db_session.query(EligibilityCheck).count() == 0
    assert db_session.query(MatchScoreReason).count() == 0
    assert db_session.query(BusinessPlan).count() == 0
    assert db_session.query(PlanSection).count() == 0
    assert db_session.query(PlanScoreReason).count() == 0
    assert db_session.query(Artifact).count() == 0
    assert db_session.query(ArtifactScoreReason).count() == 0
    assert db_session.query(Verdict).count() == 0
    assert db_session.query(AgentExecution).count() == 0
    assert db_session.query(Notification).count() == 0
    assert db_session.query(GenerationFailureAlert).count() == 0
    # 공고 수집 파이프라인 소유 테이블은 계정과 무관하므로 그대로 남아야 한다.
    assert db_session.query(Notice).filter_by(notice_id='ACCOUNT-DEL-001').count() == 1


def test_delete_account_does_not_affect_other_accounts(authed_client, db_session, login_as):
    """다른 계정의 프로젝트·리프레시 토큰은 영향받지 않아야 한다."""
    payload = {'description': '계정A 프로젝트', 'team_members': [], 'pricing_items': []}
    authed_client.post('/projects', data={'payload': json.dumps(payload)})
    user_a = db_session.query(User).filter_by(email='pytest-user@example.com').one()
    user_a_id = user_a.user_id

    other_client = login_as('account-b@example.com')
    payload_b = {'description': '계정B 프로젝트', 'team_members': [], 'pricing_items': []}
    project_b_id = other_client.post('/projects', data={'payload': json.dumps(payload_b)}).json()['project_id']
    user_b = db_session.query(User).filter_by(email='account-b@example.com').one()

    # login_as가 같은 TestClient 세션을 계정 B로 바꿔놨으므로, 계정 A를 지우려면
    # 다시 A로 로그인해야 한다 — 여기서는 대신 직접 DB로 A의 전용 클라이언트를 못 쓰니,
    # A 계정 삭제는 DB 기준으로만 검증(그 계정이 실제로 없어졌는지)하고, 격리 확인은
    # B가 살아있는지로 한다.
    from app.routers.auth import _delete_account_cascade
    _delete_account_cascade(db_session, user_a)
    db_session.commit()

    assert db_session.query(User).filter_by(user_id=user_a_id).count() == 0
    assert db_session.query(User).filter_by(user_id=user_b.user_id).count() == 1
    assert db_session.query(Project).filter_by(project_id=project_b_id).count() == 1
    assert other_client.get('/auth/me').status_code == 200


def test_delete_account_removes_refresh_tokens(authed_client, db_session):
    user = db_session.query(User).one()
    assert db_session.query(RefreshToken).filter_by(user_id=user.user_id).count() >= 1

    authed_client.delete('/auth/me')

    assert db_session.query(RefreshToken).count() == 0


def test_delete_account_clears_orchestrator_data_first(authed_client, db_session, orch):
    """[SB-244] 프로젝트마다 delete_project_data → 모두 끝나면 delete_account_data → 웹 행 삭제 순서."""
    ids = []
    for i in range(2):
        payload = {'description': f'탈퇴 프로젝트 {i}', 'team_members': [], 'pricing_items': []}
        ids.append(authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id'])
    user = db_session.query(User).one()
    user_id = user.user_id

    res = authed_client.delete('/auth/me')

    assert res.status_code == 204, res.text
    names = [(n, a) for n, a, _kw in orch.calls if n in ('delete_project_data', 'delete_account_data')]
    assert names == [('delete_project_data', (ids[0],)), ('delete_project_data', (ids[1],)),
                     ('delete_account_data', (str(user_id),))]
    assert db_session.query(User).count() == 0


def test_delete_account_busy_keeps_web_rows(authed_client, db_session, orch):
    """어느 단계에서든 BUSY면 웹 행을 하나도 지우지 않는다 — 다시 부르면 남은 것부터 이어서 한다."""
    from app.orch import OrchError

    payload = {'description': '탈퇴 BUSY 프로젝트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']
    orch.responses['delete_account_data'] = OrchError('BUSY', '점유 중')

    res = authed_client.delete('/auth/me')

    assert res.status_code == 409
    assert db_session.query(User).count() == 1
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 1
    assert authed_client.get('/auth/me').status_code == 200  # 세션도 그대로

    orch.responses['delete_account_data'] = lambda account_id: None
    assert authed_client.delete('/auth/me').status_code == 204
    assert db_session.query(User).count() == 0
