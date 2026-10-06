"""DELETE /projects/{id}/permanent — "건별 삭제"(완전 삭제). 프로젝트 기획서 v1.10 6-7절
표: 사전 정보 입력값/산출물은 "건별 삭제 가능"이라고 명시돼 있다. 기존 DELETE /projects/{id}
(휴지통 버튼)는 실행 건이 있으면 archive만 하는데, 이 엔드포인트는 그것과 독립적으로 보관 여부와
무관하게 바로 완전히 지운다.

[SB-244 · SB-247] 오케스트레이터의 산출물 · 입력 사본을 먼저 지우고(delete_project_data) 웹 행을 지운다 —
웹에는 더 이상 계획서 · 산출물 · 점수 테이블이 없다. 워커가 단계를 도는 중(BUSY)이면 웹 행을 지우지 않는다.

실행:
    pytest tests/test_project_permanent_delete.py -v
"""
import json

from orch_fakes import ProjectView, make_run

from app.models import (
    Company,
    GenerationFailureAlert,
    Notification,
    PermanentDeletionLog,
    PricingItem,
    Project,
    ProjectPlanInput,
    TeamMember,
)
from app.orch import OrchError


def _create(client, description='건별 삭제 테스트용 프로젝트', **extra) -> int:
    payload = {'description': description, 'team_members': [], 'pricing_items': [], **extra}
    return client.post('/projects', data={'payload': json.dumps(payload)}).json()['project_id']


def test_permanent_delete_works_without_archiving_first(authed_client, db_session):
    """보관(archive) 없이 바로 완전 삭제가 가능해야 한다 — archive와 독립된 별도 액션."""
    project_id = _create(authed_client)

    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0


def test_permanent_delete_removes_web_rows_and_own_company(authed_client, db_session):
    """[핵심] 입력값(팀원 · 단가 · 사업 계획) · 알림 · 생성 실패 알림이 전부 지워지고, 그 프로젝트 전용 company
    행도 같이 지워진다(Company는 project 1:1, app/models.py 참고)."""
    project_id = _create(
        authed_client, '건별 삭제 입력값 테스트',
        team_members=[{'name': '박팀원', 'role': '개발', 'experience': '3년'}],
        pricing_items=[{'service_name': '구독', 'unit_price': 9900}])
    db_session.add(Notification(project_id=project_id, kind='문서평가', target_step=6))
    db_session.add(GenerationFailureAlert(
        project_id=project_id, stage='계획서작성', resume_count=1, last_error_kind='일시',
        failure_reason='건별 삭제 전 마지막 실패(테스트)'))
    db_session.commit()
    company_id = db_session.query(Project).filter_by(project_id=project_id).one().company_id
    assert db_session.query(TeamMember).filter_by(project_id=project_id).count() == 1
    assert db_session.query(PricingItem).filter_by(project_id=project_id).count() == 1

    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text

    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0
    assert db_session.query(Company).filter_by(company_id=company_id).count() == 0
    assert db_session.query(TeamMember).filter_by(project_id=project_id).count() == 0
    assert db_session.query(PricingItem).filter_by(project_id=project_id).count() == 0
    assert db_session.query(ProjectPlanInput).filter_by(project_id=project_id).count() == 0
    assert db_session.query(Notification).filter_by(project_id=project_id).count() == 0
    assert db_session.query(GenerationFailureAlert).filter_by(project_id=project_id).count() == 0


def test_permanent_delete_works_on_already_archived_project(authed_client, db_session, orch):
    """archive된(휴지통) 프로젝트도 permanent delete로 완전히 지울 수 있어야 한다 — 두 액션이 서로 배타적이지 않다."""
    orch.responses['view_project'] = lambda pid: ProjectView(str(pid), run=make_run())  # 실행 건이 있다 → 보관 처리
    project_id = _create(authed_client, '보관 후 완전삭제 테스트')

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
    project_a_id = _create(authed_client, '계정A 프로젝트')

    other_client = login_as('perm-delete-other@example.com')
    project_b_id = _create(other_client, '계정B 프로젝트')

    # login_as가 같은 TestClient 세션을 계정 B로 바꿔놨으므로, B로는 A 프로젝트를 못 지우는지만 확인한다.
    # (다른 프로젝트 엔드포인트들과 마찬가지로 소유권 불일치는 404로 가린다 — 존재 여부 자체를 노출하지 않기 위함)
    forbidden = other_client.delete(f'/projects/{project_a_id}/permanent')
    assert forbidden.status_code == 404

    assert db_session.query(Project).filter_by(project_id=project_a_id).count() == 1
    assert db_session.query(Project).filter_by(project_id=project_b_id).count() == 1


def test_permanent_delete_asks_orchestrator_first(authed_client, db_session, orch):
    """[SB-244] 웹 행을 지우기 전에 delete_project_data(진행 중이면 중단 · 산출물 · 입력 사본 삭제)를 부른다."""
    project_id = _create(authed_client, '완전삭제 순서 테스트')

    res = authed_client.delete(f'/projects/{project_id}/permanent')

    assert res.status_code == 204, res.text
    assert ('delete_project_data', (project_id,), {}) in orch.calls
    assert db_session.query(Project).filter_by(project_id=project_id).count() == 0


def test_permanent_delete_busy_keeps_web_rows(authed_client, db_session, orch):
    """워커가 단계를 도는 중이면 BUSY — 409로 "잠시 뒤 다시"를 알리고 웹 행은 지우지 않는다(재시도는 사용자가)."""
    project_id = _create(authed_client, '완전삭제 BUSY 테스트')
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
    project_id = _create(authed_client, '완전삭제 감사로그 테스트')

    before = db_session.query(PermanentDeletionLog).count()
    res = authed_client.delete(f'/projects/{project_id}/permanent')
    assert res.status_code == 204, res.text

    after = db_session.query(PermanentDeletionLog).count()
    assert after == before + 1
