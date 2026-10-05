"""DELETE /projects/{id}/permanent — "건별 삭제"(완전 삭제). 프로젝트 기획서 v1.10 6-7절
표: 사전 정보 입력값/산출물은 "건별 삭제 가능"이라고 명시돼 있다. 기존 DELETE /projects/{id}
(휴지통 버튼)는 매칭 이후엔 archive만 하는데, 이 엔드포인트는 그것과 독립적으로 보관 여부와
무관하게 바로 완전히 지운다.

실행:
    pytest tests/test_project_permanent_delete.py -v
"""
import json

from orch_fakes import ProjectView, make_run

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
    PermanentDeletionLog,
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
    db_session.add(Notification(project_id=project_id, kind='문서평가', target_step=6))
    db_session.add(GenerationFailureAlert(
        project_id=project_id, stage='plan_writing',
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
    assert db_session.query(EligibilityCheck).filter_by(project_id=project_id).count() == 0
    assert db_session.query(MatchScoreReason).filter_by(project_id=project_id).count() == 0
    assert db_session.query(BusinessPlan).filter_by(project_id=project_id).count() == 0
    assert db_session.query(PlanSection).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(PlanScoreReason).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(Artifact).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(ArtifactScoreReason).filter_by(artifact_id=artifact_id).count() == 0
    assert db_session.query(Verdict).filter_by(plan_id=plan_id).count() == 0
    assert db_session.query(AgentExecution).filter_by(project_id=project_id).count() == 0
    assert db_session.query(Notification).filter_by(project_id=project_id).count() == 0
    assert db_session.query(GenerationFailureAlert).filter_by(project_id=project_id).count() == 0
    # 공고 수집 파이프라인 소유 테이블은 프로젝트와 무관하므로 그대로 남아야 한다.
    assert db_session.query(Notice).filter_by(notice_id='PERM-DEL-001').count() == 1


def test_permanent_delete_removes_all_artifact_version_files_from_disk(authed_client, db_session):
    """[SB-160] 완전 삭제는 DB 행뿐 아니라 디스크의 산출물 파일도 지워야 한다 — 지금
    채택된 버전(is_current=True)만이 아니라, 재작성으로 쌓인 예전 버전 행(SB-155,
    is_current=False)의 파일까지 전부. 안 지우면 UPLOAD_DIR에 고아 파일로 영원히 남는다."""
    import os

    from app.routers.projects import UPLOAD_DIR

    payload = {'description': '완전 삭제 버전 파일 정리 테스트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']

    notice = Notice(notice_id='PERM-DEL-FILES', source='k-startup', title='건별삭제 파일정리 테스트용 공고', recruitment_status='open')
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='PERM-DEL-FILES', retry_agents=())
    db_session.commit()

    artifact = db_session.query(Artifact).filter_by(artifact_id=verdict.artifact_id).one()
    current_infographic = os.path.join(UPLOAD_DIR, os.path.basename(artifact.infographic_path))
    current_executable = os.path.join(UPLOAD_DIR, os.path.basename(artifact.executable_path))
    assert os.path.exists(current_infographic)
    assert os.path.exists(current_executable)
    # 삭제 전엔 실제로 다운로드 가능해야 한다(뒤에서 볼 404가 "원래도 안 됐던 것"이 아님을
    # 보장하기 위한 대조군).
    assert authed_client.get(artifact.infographic_path).status_code == 200
    assert authed_client.get(artifact.executable_path).status_code == 200

    # [SB-155] 재작성으로 쌓인, 채택되지 않은 예전 버전 행을 흉내낸다 — 실제로 디스크에
    # 파일을 하나 더 만들어두고 그 경로를 가리키는 두 번째(is_current=False) Artifact
    # 행을 추가한다.
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    old_stored_name = 'old-version-test.svg'
    old_path = os.path.join(UPLOAD_DIR, old_stored_name)
    with open(old_path, 'wb') as f:
        f.write(b'old version content')
    rejected_version = Artifact(
        plan_id=artifact.plan_id, category=artifact.category,
        infographic_path=f'/uploads/{old_stored_name}', executable_path=None,
        version=artifact.version + 1, is_current=False,
    )
    db_session.add(rejected_version)
    db_session.commit()
    assert os.path.exists(old_path)

    infographic_url = artifact.infographic_path
    executable_url = artifact.executable_path

    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text

    assert not os.path.exists(current_infographic)
    assert not os.path.exists(current_executable)
    assert not os.path.exists(old_path)
    assert authed_client.get(infographic_url).status_code == 404
    assert authed_client.get(executable_url).status_code == 404


def test_permanent_delete_works_on_already_archived_project(authed_client, db_session, orch):
    """archive된(휴지통) 프로젝트도 permanent delete로 완전히 지울 수 있어야 한다 —
    두 액션이 서로 배타적이지 않다."""
    orch.responses['view_project'] = lambda pid: ProjectView(str(pid), run=make_run())  # 실행 건이 있다 → 보관 처리
    payload = {'description': '보관 후 완전삭제 테스트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']
    notice = Notice(notice_id='PERM-DEL-002', source='k-startup', title='보관 테스트용 공고', recruitment_status='open')
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='PERM-DEL-002', retry_agents=())
    db_session.commit()

    archive_res = authed_client.delete(f'/projects/{project_id}')
    assert archive_res.status_code == 204, archive_res.text
    db_session.expire_all()
    project = db_session.query(Project).filter_by(project_id=project_id).one()
    assert project.archived_at is not None, '휴지통 버튼은 archive만 해야 함(기존 동작 유지 확인)'

    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0


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


def test_permanent_delete_asks_orchestrator_first(authed_client, db_session, orch):
    """[SB-244] 웹 행을 지우기 전에 delete_project_data(진행 중이면 중단 · 산출물 · 입력 사본 삭제)를 부른다."""
    payload = {'description': '완전삭제 순서 테스트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']

    res = authed_client.delete(f'/projects/{project_id}/permanent')

    assert res.status_code == 204, res.text
    assert ('delete_project_data', (project_id,), {}) in orch.calls
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0


def test_permanent_delete_busy_keeps_web_rows(authed_client, db_session, orch):
    """워커가 단계를 도는 중이면 BUSY — 409로 "잠시 뒤 다시"를 알리고 웹 행은 지우지 않는다(재시도는 사용자가)."""
    from app.orch import OrchError

    payload = {'description': '완전삭제 BUSY 테스트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']
    orch.responses['delete_project_data'] = OrchError('BUSY', '단계 진행 중')

    res = authed_client.delete(f'/projects/{project_id}/permanent')

    assert res.status_code == 409
    assert '잠시 뒤' in res.json()['detail']
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 1

    # 단계가 끝난 뒤 다시 누르면 지워진다
    orch.responses.pop('delete_project_data')
    assert authed_client.delete(f'/projects/{project_id}/permanent').status_code == 204
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0
def test_permanent_delete_writes_audit_log_without_identifiers(authed_client, db_session):
    """[2026-09-28 신규, 프론트 요청 4] 완전 삭제는 식별자 없이 "언제 삭제됐는지"만
    permanent_deletion_log에 남겨서, 삭제된 프로젝트가 있었다는 사실 자체는 통계로
    확인할 수 있어야 한다."""
    payload = {'description': '완전삭제 감사로그 테스트', 'team_members': [], 'pricing_items': []}
    project_id = authed_client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']

    before = db_session.query(PermanentDeletionLog).count()
    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text

    after = db_session.query(PermanentDeletionLog).count()
    assert after == before + 1
