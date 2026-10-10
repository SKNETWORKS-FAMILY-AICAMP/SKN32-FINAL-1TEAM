"""사업비 집행계획 · 추진 일정의 요청 · 응답 모양 (SB-329).

요청(ProjectCreateRequest.budget_items · schedule_items)은 배열 순서대로 받는 목록이고, 응답(ProjectDetailOut)은 같은 이름 · 모양을
item_order 순으로 돌려준다. 저장하는 쪽(생성 처리)은 SB-331, 값 검사(필수 · 음수 · 합계 · 유형별 단계)는 test_budget_schedule_validation.py(SB-330)다."""
import decimal

import pytest
from pydantic import ValidationError

from app import models, schemas


def _budget(**overrides):
    row = {'phase': '1단계', 'category': '외주용역비', 'execution_plan': '앱 개발 외주', 'total_amount': 15000000,
           'government_amount': 15000000, 'self_cash_amount': 0, 'self_in_kind_amount': 0}
    row.update(overrides)
    return row


def _schedule(**overrides):
    row = {'section': 'feasibility', 'category': '개발', 'content': '모델 고도화', 'period': '2026.05~2026.07', 'detail': '정확도 80%'}
    row.update(overrides)
    return row


def _request(applicant_type='preliminary', **overrides):
    base = {'applicant_type': applicant_type, 'ceo_name': '가', 'description': '아이디어'}
    base.update(overrides)
    return schemas.ProjectCreateRequest.model_validate(base)


def test_request_without_the_lists_defaults_to_empty():
    body = _request()
    assert body.budget_items == []
    assert body.schedule_items == []


def test_request_accepts_both_lists_in_the_given_order():
    body = _request(
        budget_items=[_budget(), _budget(phase='2단계', category='광고선전비', execution_plan='SNS 마케팅', total_amount=10000000,
                                         government_amount=10000000)],
        schedule_items=[_schedule(), _schedule(section='growth', category='사업화', content='보험사 제휴', period='2027.01~2027.06',
                                               detail='')])
    assert [b.category for b in body.budget_items] == ['외주용역비', '광고선전비']
    assert [b.phase for b in body.budget_items] == ['1단계', '2단계']
    assert body.budget_items[0].total_amount == 15000000
    assert [s.section for s in body.schedule_items] == ['feasibility', 'growth']
    assert body.schedule_items[1].detail == ''


@pytest.mark.parametrize('phase', ['3단계', '1', 1, '일단계'])
def test_budget_phase_accepts_only_stage_one_or_two(phase):
    with pytest.raises(ValidationError):
        _request(budget_items=[_budget(phase=phase)])


@pytest.mark.parametrize('section', ['agreement', 'roadmap', '협약기간 내', ''])
def test_schedule_section_accepts_only_feasibility_or_growth(section):
    with pytest.raises(ValidationError):
        _request(schedule_items=[_schedule(section=section)])


def test_schedule_section_is_required():
    row = _schedule()
    del row['section']
    with pytest.raises(ValidationError):
        _request(schedule_items=[row])


def test_amounts_are_whole_won():
    with pytest.raises(ValidationError):
        _request(budget_items=[_budget(total_amount=1000.5)])


def test_error_location_names_the_table_and_row():
    with pytest.raises(ValidationError) as exc:
        _request(budget_items=[_budget(), _budget(), _budget(phase='9단계')])
    assert exc.value.errors()[0]['loc'] == ('budget_items', 2, 'phase')


def test_lists_have_a_row_limit():
    _request(budget_items=[_budget()] * schemas.MAX_BUDGET_ITEMS)
    with pytest.raises(ValidationError):
        _request(budget_items=[_budget()] * (schemas.MAX_BUDGET_ITEMS + 1))
    _request(schedule_items=[_schedule()] * schemas.MAX_SCHEDULE_ITEMS)
    with pytest.raises(ValidationError):
        _request(schedule_items=[_schedule()] * (schemas.MAX_SCHEDULE_ITEMS + 1))


def test_text_columns_respect_their_db_limits():
    with pytest.raises(ValidationError):
        _request(budget_items=[_budget(category='x' * 101)])
    with pytest.raises(ValidationError):
        _request(schedule_items=[_schedule(period='2026.05' + 'x' * 50)])


def _project(db):
    user = models.User(email='shape@example.com', name='가', google_sub='sub-shape')
    db.add(user)
    db.flush()
    company = models.Company(user_id=user.user_id, applicant_type='preliminary', ceo_name='가')
    db.add(company)
    db.flush()
    project = models.Project(company_id=company.company_id, description='프로젝트')
    db.add(project)
    db.flush()
    return project


def test_detail_returns_rows_in_item_order_with_whole_won_amounts(db_session):
    project = _project(db_session)
    # 일부러 순서를 뒤집어 넣는다 — 응답은 item_order 순이어야 한다
    db_session.add_all([
        models.ProjectBudgetItem(project_id=project.project_id, item_order=2, phase='2단계', category='광고선전비',
                                 total_amount=decimal.Decimal('10000000.00'), government_amount=decimal.Decimal('10000000.00'),
                                 self_cash_amount=decimal.Decimal('0.00'), self_in_kind_amount=decimal.Decimal('0.00')),
        models.ProjectBudgetItem(project_id=project.project_id, item_order=1, phase='1단계', category='외주용역비',
                                 execution_plan='앱 개발 외주', total_amount=decimal.Decimal('15000000.00')),
        models.ProjectScheduleItem(project_id=project.project_id, item_order=2, section='growth', category='사업화',
                                   period='2027.01~2027.06'),
        models.ProjectScheduleItem(project_id=project.project_id, item_order=1, section='feasibility', category='개발',
                                   content='모델 고도화', period='2026.05~2026.07', detail='정확도 80%'),
    ])
    db_session.commit()
    db_session.refresh(project)

    out = schemas.ProjectDetailOut.model_validate(project).model_dump()
    assert [b['category'] for b in out['budget_items']] == ['외주용역비', '광고선전비']
    assert out['budget_items'][0] == {
        'phase': '1단계', 'category': '외주용역비', 'execution_plan': '앱 개발 외주', 'total_amount': 15000000,
        'government_amount': None, 'self_cash_amount': None, 'self_in_kind_amount': None}
    assert isinstance(out['budget_items'][1]['total_amount'], int)
    assert out['budget_items'][1]['self_cash_amount'] == 0
    assert [s['section'] for s in out['schedule_items']] == ['feasibility', 'growth']
    assert out['schedule_items'][0] == {
        'section': 'feasibility', 'category': '개발', 'content': '모델 고도화', 'period': '2026.05~2026.07', 'detail': '정확도 80%'}


def test_detail_without_rows_returns_empty_lists(db_session):
    project = _project(db_session)
    db_session.commit()
    db_session.refresh(project)
    out = schemas.ProjectDetailOut.model_validate(project)
    assert out.budget_items == []
    assert out.schedule_items == []
