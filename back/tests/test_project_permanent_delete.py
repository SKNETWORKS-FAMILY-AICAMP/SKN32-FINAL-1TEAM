"""DELETE /projects/{id}/permanent — "건별 삭제"(완전 삭제). 프로젝트 기획서 v1.10 6-7절
표: 사전 정보 입력값/산출물은 "건별 삭제 가능"이라고 명시돼 있다. 기존 DELETE /projects/{id}
(휴지통 버튼)는 매칭 이후엔 archive만 하는데, 이 엔드포인트는 그것과 독립적으로 보관 여부와
무관하게 바로 완전히 지운다.

실행:
    pytest tests/test_project_permanent_delete.py -v
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
    MatchResult,
    MatchScoreReason,
    Notice,
    Notification,
    PlanScoreReason,
    PlanSection,
    Project,
    Verdict,
)
from seed_dummy_pipeline import seed_dummy_pipeline


def test_permanent_delete_works_without_archiving_first(authed_client, db_session):
    """보관(archive) 없이 바로 완전 삭제가 가능해야 한다 — archive와 독립된 별도 액션."""
    payload = {'description': '건별 삭제 테스트용 프로젝트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']

    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0


def test_permanent_delete_cascades_full_pipeline_and_own_company(authed_client, db_session):
    """[핵심] 매칭·계획서·산출물·검증 결과·알림까지 전부 지워야 하고, 그 프로젝트 전용
    company 행도 같이 지워야 한다(Company는 project 1:1, app/models.py 참고)."""
    payload = {'description': '건별 삭제 파이프라인 테스트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']

    notice = Notice(notice_id='PERM-DEL-001', source='k-startup', title='건별삭제 테스트용 더미 공고', recruitment_status='open')
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='PERM-DEL-001', retry_agents=())
    match = db_session.query(MatchResult).filter_by(project_id=project_id).one()
    match_id = match.match_id
    db_session.add(Notification(match_id=match_id, project_id=project_id, kind='문서평가', target_step=6))
    db_session.add(GenerationFailureAlert(
        match_id=match_id, project_id=project_id, stage='plan_writing',
        resume_count=1, last_error_kind='일시', failure_reason='건별 삭제 전 마지막 실패(테스트)',
    ))
    db_session.commit()

    plan_id = verdict.plan_id
    artifact_id = verdict.artifact_id
    company_id = db_session.query(Project).filter_by(project_id=project_id).one().company_id

    assert db_session.query(PlanSection).filter_by(plan_id=plan_id).count() > 0
    assert db_session.query(ArtifactScoreReason).filter_by(artifact_id=artifact_id).count() > 0

    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text

    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0
    assert db_session.query(Company).filter_by(company_id=company_id).count() == 0
    assert db_session.query(MatchResult).filter_by(project_id=project_id).count() == 0
    assert db_session.query(EligibilityCheck).filter_by(match_id=match_id).count() == 0
    assert db_session.query(MatchScoreReason).filter_by(match_id=match_id).count() == 0
    assert db_session.query(BusinessPlan).filter_by(match_id=match_id).count() == 0
    assert db_session.query(PlanSection).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(PlanScoreReason).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(Artifact).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(ArtifactScoreReason).filter_by(artifact_id=artifact_id).count() == 0
    assert db_session.query(Verdict).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(AgentExecution).filter_by(match_id=match_id).count() == 0
    assert db_session.query(Notification).filter_by(match_id=match_id).count() == 0
    assert db_session.query(GenerationFailureAlert).filter_by(match_id=match_id).count() == 0
    # 공고 수집 파이프라인 소유 테이블은 프로젝트와 무관하므로 그대로 남아야 한다.
    assert db_session.query(Notice).filter_by(notice_id='PERM-DEL-001').count() == 1


def test_permanent_delete_works_on_already_archived_project(authed_client, db_session):
    """archive된(휴지통) 프로젝트도 permanent delete로 완전히 지울 수 있어야 한다 —
    두 액션이 서로 배타적이지 않다."""
    payload = {'description': '보관 후 완전삭제 테스트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']
    notice = Notice(notice_id='PERM-DEL-002', source='k-startup', title='보관 테스트용 공고', recruitment_status='open')
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='PERM-DEL-002', retry_agents=())
    db_session.commit()

    archive_res = authed_client.delete(f'/projects/{project_id}')
    assert archive_res.status_code == 204, archive_res.text
    match = db_session.query(MatchResult).filter_by(project_id=project_id).one()
    assert match.archived_at is not None, '휴지통 버튼은 archive만 해야 함(기존 동작 유지 확인)'

    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0
    assert db_session.query(MatchResult).filter_by(project_id=project_id).count() == 0


def test_permanent_delete_does_not_affect_other_accounts_projects(authed_client, db_session, login_as):
    """다른 계정의 프로젝트는 영향받지 않아야 한다."""
    payload = {'description': '계정A 프로젝트', 'team_members': [], 'pricing_items': []}
    project_a_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']

    other_client = login_as('perm-delete-other@example.com')
    payload_b = {'description': '계정B 프로젝트', 'team_members': [], 'pricing_items': []}
    project_b_id = other_client.post('/projects', data={'payload': json.dumps(payload_b)}).json()['project_id']

    # login_as가 같은 TestClient 세션을 계정 B로 바꿔놨으므로, 계정 A의 프로젝트를
    # 완전삭제하려면 다시 A로 로그인한 클라이언트가 필요하다 — 여기서는 대신 소유권
    # 검사(_get_owned_project)가 B로는 A 프로젝트를 못 지우게 막는지만 확인한다.
    # (다른 프로젝트 엔드포인트들과 마찬가지로 소유권 불일치는 404로 가린다 — 존재 여부 자체를
    # 노출하지 않기 위함, _get_owned_project 참고.)
    forbidden = other_client.delete(f'/projects/{project_a_id}/permanent')
    assert forbidden.status_code == 404

    assert db_session.query(Project).filter_by(project_id=project_a_id).count() == 1
    assert db_session.query(Project).filter_by(project_id=project_b_id).count() == 1
