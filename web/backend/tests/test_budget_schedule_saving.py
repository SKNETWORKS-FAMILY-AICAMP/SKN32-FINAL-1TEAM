"""사업비 집행계획 · 추진 일정 저장 (SB-331).

POST /projects가 budget_items · schedule_items를 project_budget_items · project_schedule_items에 보낸 순서(item_order 1부터)대로
저장한다. 오케스트레이터가 request_start 때 이 두 표를 읽으므로 request_start를 부르기 전에 이미 커밋되어 있어야 하고,
시작 요청이 거절되면 방금 만든 프로젝트와 함께 이 행들도 지워진다."""
import json

from orch_fakes import StartCheck

from app.database import SessionLocal
from app.models import Project, ProjectBudgetItem, ProjectScheduleItem


def _budget(**overrides):
    row = {'category': '외주용역비', 'execution_plan': '앱 개발 외주', 'total_amount': 15000000,
           'government_amount': 15000000, 'self_cash_amount': 0, 'self_in_kind_amount': 0}
    row.update(overrides)
    return row


def _schedule(**overrides):
    row = {'section': 'feasibility', 'category': '개발', 'content': '모델 고도화', 'period': '2026.05~2026.07', 'detail': '정확도 80%'}
    row.update(overrides)
    return row


def _payload(applicant_type='corp', **overrides):
    base = {'applicant_type': applicant_type, 'biz_type': '법인', 'ceo_name': '박테스트', 'founded_at': '2024-01-01',
            'description': 'AI 기반 서비스', 'team_members': [], 'pricing_items': []}
    base.update(overrides)
    return {'payload': json.dumps(base)}


def _preliminary_items():
    return {
        'applicant_type': 'preliminary',
        'budget_items': [
            _budget(phase='1단계'),
            _budget(phase='1단계', category='재료비', execution_plan='라벨링', total_amount=5000000, government_amount=5000000),
            _budget(phase='2단계', category='광고선전비', execution_plan='SNS 마케팅', total_amount=10000000, government_amount=10000000),
        ],
        'schedule_items': [
            _schedule(),
            _schedule(category='출시', content='앱 출시', period='2026.09~2026.11', detail=''),
            _schedule(section='growth', category='사업화', content='보험사 제휴', period='2027.01~2027.06'),
        ],
    }


def test_rows_are_saved_in_the_order_sent_and_returned(authed_client, db_session):
    r = authed_client.post('/projects', data=_payload(**_preliminary_items()))
    assert r.status_code == 201, r.text
    body = r.json()
    project_id = body['project_id']

    assert [(b['phase'], b['category'], b['total_amount']) for b in body['budget_items']] == [
        ('1단계', '외주용역비', 15000000), ('1단계', '재료비', 5000000), ('2단계', '광고선전비', 10000000)]
    assert [(s['section'], s['category']) for s in body['schedule_items']] == [
        ('feasibility', '개발'), ('feasibility', '출시'), ('growth', '사업화')]

    budget = db_session.query(ProjectBudgetItem).filter_by(project_id=project_id).order_by(ProjectBudgetItem.item_order).all()
    assert [b.item_order for b in budget] == [1, 2, 3]
    assert [int(b.government_amount) for b in budget] == [15000000, 5000000, 10000000]
    schedule = db_session.query(ProjectScheduleItem).filter_by(project_id=project_id).order_by(ProjectScheduleItem.item_order).all()
    assert [s.item_order for s in schedule] == [1, 2, 3]
    assert schedule[1].detail == ''  # 비워 보낸 세부내용은 ''로 저장된다

    got = authed_client.get(f'/projects/{project_id}').json()
    assert got['budget_items'] == body['budget_items']
    assert got['schedule_items'] == body['schedule_items']


def test_business_owner_rows_have_no_phase(authed_client, db_session):
    r = authed_client.post('/projects', data=_payload('corp', budget_items=[_budget(
        total_amount=100, government_amount=60, self_cash_amount=30, self_in_kind_amount=10)]))
    assert r.status_code == 201, r.text
    row = db_session.query(ProjectBudgetItem).one()
    assert row.phase is None
    assert (int(row.total_amount), int(row.government_amount), int(row.self_cash_amount), int(row.self_in_kind_amount)) == (100, 60, 30, 10)


def test_project_without_the_lists_saves_no_rows(authed_client, db_session):
    r = authed_client.post('/projects', data=_payload())
    assert r.status_code == 201, r.text
    assert r.json()['budget_items'] == [] and r.json()['schedule_items'] == []
    assert db_session.query(ProjectBudgetItem).count() == 0
    assert db_session.query(ProjectScheduleItem).count() == 0


def test_rows_are_already_committed_when_request_start_is_called(authed_client, orch):
    """오케스트레이터는 request_start 때 다른 연결로 이 두 표를 읽는다 — 그 시점에 커밋된 행이 보여야 한다."""
    seen = {}

    def request_start(account_id, project_id):
        other = SessionLocal()  # 요청 처리 세션과 별개의 연결 — 커밋되지 않은 행은 보이지 않는다
        try:
            seen['budget'] = other.query(ProjectBudgetItem).filter_by(project_id=project_id).count()
            seen['schedule'] = other.query(ProjectScheduleItem).filter_by(project_id=project_id).count()
        finally:
            other.close()
        return StartCheck(ok=True, request_id='req-1')

    orch.responses['request_start'] = request_start
    r = authed_client.post('/projects', data=_payload(**_preliminary_items()))
    assert r.status_code == 201, r.text
    assert seen == {'budget': 3, 'schedule': 3}


def test_rejected_start_removes_the_project_and_its_rows(authed_client, db_session, orch):
    orch.responses['request_start'] = lambda account_id, project_id: StartCheck(
        ok=False, code='E-C1-REQUIRED', message='필수 항목이 비어 있어요', missing=['사업비 집행계획'])
    r = authed_client.post('/projects', data=_payload(**_preliminary_items()))
    assert r.status_code == 422
    assert r.json()['detail']['missing'] == ['사업비 집행계획']
    assert db_session.query(Project).count() == 0
    assert db_session.query(ProjectBudgetItem).count() == 0
    assert db_session.query(ProjectScheduleItem).count() == 0


def test_invalid_rows_are_rejected_before_anything_is_saved(authed_client, db_session, orch):
    bad = _budget(total_amount=1)  # 정부지원 15,000,000과 합계가 맞지 않는다
    r = authed_client.post('/projects', data=_payload('corp', budget_items=[bad]))
    assert r.status_code == 422
    assert db_session.query(Project).count() == 0
    assert db_session.query(ProjectBudgetItem).count() == 0
    assert not [c for c in orch.calls if c[0] == 'request_start']
