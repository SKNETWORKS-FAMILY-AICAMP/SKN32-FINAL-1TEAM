"""[SB-246] proofread_logs(검수 회수 문단) 보관 규칙 — 학습에 반영된(trained) 행만 남긴다.

완전 삭제 · 계정 탈퇴 · 학습 동의 철회 때 그 사용자의 pending · labeled · excluded 행(과 상태 없는 옛 행)은 지우고,
trained 행은 프로젝트 · 계획서와의 연결만 끊은 채 남긴다. 워커는 project_id로 행을 쓴다(plan_id 없음).
"""
import json

from dummy_seed import create_match

from app.models import ProofreadLog, User

STATUSES = ['pending', 'labeled', 'excluded', 'trained', None]


def _project(client, description='보관 규칙 프로젝트') -> int:
    payload = {'description': description, 'team_members': [], 'pricing_items': []}
    r = client.post('/projects', data={'payload': json.dumps(payload)})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _add_logs(db_session, project_id) -> dict:
    """워커가 쓴 것처럼 project_id로 상태별 행을 하나씩 심고 {상태: log_id}를 돌려준다."""
    rows = {}
    for status in STATUSES:
        row = ProofreadLog(
            project_id=project_id, original_text=f'원문-{status}', corrected_text=f'시도-{status}', attempt_no=1,
            passed=False, violation_type='날짜', recovery_status=status, model_version='tp2-test')
        db_session.add(row)
        db_session.flush()
        rows[status] = row.log_id
    db_session.commit()
    return rows


def _surviving(db_session) -> dict[int, ProofreadLog]:
    db_session.expire_all()
    return {r.log_id: r for r in db_session.query(ProofreadLog).all()}


def test_permanent_delete_keeps_only_trained_rows_and_detaches_them(authed_client, db_session):
    project_id = _project(authed_client)
    other_id = _project(authed_client, '다른 프로젝트')
    mine = _add_logs(db_session, project_id)
    others = _add_logs(db_session, other_id)

    res = authed_client.delete(f'/projects/{project_id}/permanent')

    assert res.status_code == 204, res.text
    left = _surviving(db_session)
    assert mine['trained'] in left, 'trained 행은 남아야 한다'
    for status in ('pending', 'labeled', 'excluded', None):
        assert mine[status] not in left, f'{status} 행은 지워져야 한다'
    kept = left[mine['trained']]
    assert kept.project_id is None and kept.plan_id is None  # 연결만 끊긴다
    assert kept.original_text == '원문-trained' and kept.model_version == 'tp2-test'
    # 다른 프로젝트의 행은 그대로
    assert all(log_id in left for log_id in others.values())
    assert all(left[log_id].project_id == other_id for log_id in others.values())


def test_permanent_delete_clears_untrained_legacy_plan_rows(authed_client, db_session):
    """더미 시절 행(plan_id만 있고 project_id는 없음)도 같은 규칙으로 지워진다."""
    from app.models import BusinessPlan

    project = create_match(authed_client, db_session, 'RETENTION-LEGACY')
    plan = db_session.query(BusinessPlan).filter_by(project_id=project.project_id).one()
    legacy_pending = ProofreadLog(plan_id=plan.plan_id, original_text='a', corrected_text='b', recovery_status='pending')
    legacy_trained = ProofreadLog(plan_id=plan.plan_id, original_text='c', corrected_text='d', recovery_status='trained')
    db_session.add_all([legacy_pending, legacy_trained])
    db_session.commit()
    pending_id, trained_id = legacy_pending.log_id, legacy_trained.log_id

    assert authed_client.delete(f'/projects/{project.project_id}/permanent').status_code == 204

    left = _surviving(db_session)
    assert pending_id not in left and trained_id in left
    assert left[trained_id].plan_id is None and left[trained_id].project_id is None


def test_delete_account_keeps_only_trained_rows(authed_client, db_session):
    first = _project(authed_client, '탈퇴 프로젝트 1')
    second = _project(authed_client, '탈퇴 프로젝트 2')
    rows = [_add_logs(db_session, first), _add_logs(db_session, second)]

    assert authed_client.delete('/auth/me').status_code == 204

    left = _surviving(db_session)
    assert set(left) == {r['trained'] for r in rows}
    assert all(r.project_id is None for r in left.values())


def test_consent_revocation_deletes_untrained_rows_of_that_user_only(login_as, db_session):
    owner = login_as('consent-owner@example.com')
    owner_project = _project(owner, '동의 철회 프로젝트')
    owner_rows = _add_logs(db_session, owner_project)
    other = login_as('consent-other@example.com')
    other_project = _project(other, '다른 사람 프로젝트')
    other_rows = _add_logs(db_session, other_project)

    # 철회하지 않은 동의 갱신은 아무것도 지우지 않는다
    assert other.patch('/auth/consent', json={'aiTrainingAgreed': True}).status_code == 200
    assert len(_surviving(db_session)) == 2 * len(STATUSES)

    # login_as는 같은 TestClient 세션을 바꿔치기하므로 owner로 다시 로그인한다
    owner = login_as('consent-owner@example.com')
    res = owner.patch('/auth/consent', json={'aiTrainingAgreed': False})

    assert res.status_code == 200, res.text
    assert res.json()['ai_training_agreed'] is False
    left = _surviving(db_session)
    assert owner_rows['trained'] in left, 'trained 행은 철회해도 남는다'
    for status in ('pending', 'labeled', 'excluded', None):
        assert owner_rows[status] not in left
    assert left[owner_rows['trained']].project_id == owner_project  # 프로젝트가 살아 있으니 연결은 그대로
    assert all(log_id in left for log_id in other_rows.values())  # 다른 사용자의 행은 그대로
    assert db_session.query(User).filter_by(email='consent-owner@example.com').one().ai_training_agreed is False


# ── 관리자: 검수 회수 문단 ─────────────────────────────────────────────────────────────
def test_admin_recovery_items_show_detached_trained_rows(authed_client, db_session):
    """프로젝트가 지워져 연결이 끊긴 trained 행도 목록에 남고, 프로젝트 설명은 없으며 동의한 것으로 본다."""
    from fastapi.testclient import TestClient

    project_id = _project(authed_client)
    rows = _add_logs(db_session, project_id)
    assert authed_client.delete(f'/projects/{project_id}/permanent').status_code == 204
    user = db_session.query(User).one()
    user.role = 'admin'
    db_session.commit()

    from app.main import app
    admin = TestClient(app)
    admin.cookies.update(authed_client.cookies)
    res = admin.get('/admin/recovery-items')

    assert res.status_code == 200, res.text
    items = res.json()
    assert [i['log_id'] for i in items] == [rows['trained']]
    assert items[0]['project_id'] is None and items[0]['project_description'] is None
    assert items[0]['recovery_status'] == 'trained' and items[0]['consent'] is True
    assert items[0]['model_version'] == 'tp2-test'


def _admin(authed_client, db_session):
    from fastapi.testclient import TestClient

    user = db_session.query(User).one()
    user.role = 'admin'
    db_session.commit()
    from app.main import app
    admin = TestClient(app)
    admin.cookies.update(authed_client.cookies)
    return admin


def test_mark_trained_requires_labeled_rows(authed_client, db_session):
    project_id = _project(authed_client)
    rows = _add_logs(db_session, project_id)
    admin = _admin(authed_client, db_session)

    # pending이 섞여 있으면 아무것도 바꾸지 않고 409
    res = admin.post('/admin/recovery-items/trained', json={'log_ids': [rows['labeled'], rows['pending']]})
    assert res.status_code == 409, res.text
    db_session.expire_all()
    assert db_session.get(ProofreadLog, rows['labeled']).recovery_status == 'labeled'

    # 없는 ID는 404
    assert admin.post('/admin/recovery-items/trained', json={'log_ids': [999999]}).status_code == 404

    # labeled(와 이미 trained)만이면 표시된다
    res = admin.post('/admin/recovery-items/trained', json={'log_ids': [rows['labeled'], rows['trained']]})
    assert res.status_code == 200, res.text
    assert {i['recovery_status'] for i in res.json()} == {'trained'}
    db_session.expire_all()
    assert db_session.get(ProofreadLog, rows['labeled']).recovery_status == 'trained'


def test_trained_row_cannot_be_relabeled_and_trained_rows_survive_deletion(authed_client, db_session):
    project_id = _project(authed_client)
    rows = _add_logs(db_session, project_id)
    admin = _admin(authed_client, db_session)

    admin.post('/admin/recovery-items/trained', json={'log_ids': [rows['labeled']]})
    res = admin.put(f"/admin/recovery-items/{rows['labeled']}", json={'recovery_status': 'excluded'})
    assert res.status_code == 409, res.text

    # 방금 trained가 된 행도 완전 삭제 뒤에 남는다
    assert authed_client.delete(f'/projects/{project_id}/permanent').status_code == 204
    left = _surviving(db_session)
    assert {rows['labeled'], rows['trained']} <= set(left)
    assert rows['pending'] not in left
