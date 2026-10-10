"""사업비 집행계획 · 추진 일정 입력 검사 (SB-330).

금액 네 칸은 모두 필수(0 허용, 총사업비만 1 이상), 총사업비 = 정부지원 + 자기부담 현금 + 현물, 단계(phase)는 예비창업만,
추진기간에는 연도가 있어야 한다. 오류 위치(loc)는 표 이름 · 줄 번호(0부터) · 칸이라 화면이 칸을 표시할 수 있다."""
import json

import pytest
from pydantic import ValidationError

from app import schemas


def _budget(**overrides):
    row = {'phase': '1단계', 'category': '외주용역비', 'execution_plan': '앱 개발 외주', 'total_amount': 15000000,
           'government_amount': 15000000, 'self_cash_amount': 0, 'self_in_kind_amount': 0}
    row.update(overrides)
    return row


def _corp_budget(**overrides):
    return _budget(phase=None, **overrides)


def _schedule(**overrides):
    row = {'section': 'feasibility', 'category': '개발', 'content': '모델 고도화', 'period': '2026.05~2026.07', 'detail': '정확도 80%'}
    row.update(overrides)
    return row


def _request(applicant_type='preliminary', **overrides):
    base = {'applicant_type': applicant_type, 'ceo_name': '가', 'description': '아이디어'}
    base.update(overrides)
    return schemas.ProjectCreateRequest.model_validate(base)


def _locs(exc: pytest.ExceptionInfo) -> list[tuple]:
    return [e['loc'] for e in exc.value.errors()]


# ── 사업비 한 줄 ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('field', ['category', 'execution_plan', 'total_amount', 'government_amount', 'self_cash_amount', 'self_in_kind_amount'])
def test_budget_row_requires_every_field_except_phase(field):
    row = _budget()
    del row[field]
    with pytest.raises(ValidationError) as exc:
        _request(budget_items=[row])
    assert _locs(exc) == [('budget_items', 0, field)]


@pytest.mark.parametrize('field', ['total_amount', 'government_amount', 'self_cash_amount', 'self_in_kind_amount'])
def test_blank_amount_is_rejected_not_read_as_zero(field):
    for blank in (None, ''):
        with pytest.raises(ValidationError) as exc:
            _request(budget_items=[_budget(**{field: blank})])
        assert ('budget_items', 0, field) in _locs(exc)


@pytest.mark.parametrize('field', ['category', 'execution_plan'])
def test_blank_text_is_rejected(field):
    for blank in ('', '   '):
        with pytest.raises(ValidationError) as exc:
            _request(budget_items=[_budget(**{field: blank})])
        assert _locs(exc) == [('budget_items', 0, field)]


def test_text_is_stripped():
    body = _request(budget_items=[_budget(category='  외주용역비  ', execution_plan=' 앱 개발 ')])
    assert body.budget_items[0].category == '외주용역비'
    assert body.budget_items[0].execution_plan == '앱 개발'


def test_zero_is_allowed_for_the_parts_but_total_must_be_positive():
    row = _budget(total_amount=5, government_amount=5, self_cash_amount=0, self_in_kind_amount=0)
    assert _request(budget_items=[row]).budget_items[0].self_cash_amount == 0
    with pytest.raises(ValidationError) as exc:
        _request(budget_items=[_budget(total_amount=0, government_amount=0)])
    assert _locs(exc) == [('budget_items', 0, 'total_amount')]


@pytest.mark.parametrize('field', ['government_amount', 'self_cash_amount', 'self_in_kind_amount', 'total_amount'])
def test_negative_amounts_are_rejected(field):
    with pytest.raises(ValidationError) as exc:
        _request(budget_items=[_budget(**{field: -1})])
    assert ('budget_items', 0, field) in _locs(exc)


def test_amount_over_the_db_limit_is_rejected():
    over = schemas.MAX_AMOUNT_WON + 1
    with pytest.raises(ValidationError) as exc:
        _request(budget_items=[_budget(total_amount=over, government_amount=over)])
    assert ('budget_items', 0, 'total_amount') in _locs(exc)
    ok = schemas.MAX_AMOUNT_WON
    assert _request(budget_items=[_budget(total_amount=ok, government_amount=ok)]).budget_items[0].total_amount == ok


def test_total_must_equal_government_plus_cash_plus_in_kind():
    with pytest.raises(ValidationError) as exc:
        _request('corp', budget_items=[
            _corp_budget(),
            _corp_budget(total_amount=100, government_amount=60, self_cash_amount=30, self_in_kind_amount=0)])
    assert _locs(exc) == [('budget_items', 1, 'total_amount')]
    assert '총사업비' in exc.value.errors()[0]['msg']
    ok = _request('corp', budget_items=[
        _corp_budget(total_amount=100, government_amount=60, self_cash_amount=30, self_in_kind_amount=10)])
    assert ok.budget_items[0].self_in_kind_amount == 10


# ── 유형별 단계 · 자기부담 ───────────────────────────────────────────────────────────────
def test_preliminary_requires_a_phase_on_every_row():
    with pytest.raises(ValidationError) as exc:
        _request('preliminary', budget_items=[_budget(), _budget(phase=None), _budget(phase=None)])
    assert _locs(exc) == [('budget_items', 1, 'phase'), ('budget_items', 2, 'phase')]


def test_preliminary_takes_self_funding_as_cash_only():
    with pytest.raises(ValidationError) as exc:
        _request('preliminary', budget_items=[
            _budget(total_amount=10, government_amount=5, self_cash_amount=3, self_in_kind_amount=2)])
    assert _locs(exc) == [('budget_items', 0, 'self_in_kind_amount')]
    ok = _request('preliminary', budget_items=[
        _budget(total_amount=10, government_amount=5, self_cash_amount=5, self_in_kind_amount=0)])
    assert ok.budget_items[0].self_cash_amount == 5


@pytest.mark.parametrize('applicant_type', ['individual', 'corp'])
def test_business_owners_do_not_use_phase(applicant_type):
    with pytest.raises(ValidationError) as exc:
        _request(applicant_type, budget_items=[_corp_budget(), _budget(phase='2단계')])
    assert _locs(exc) == [('budget_items', 1, 'phase')]
    assert _request(applicant_type, budget_items=[_corp_budget()]).budget_items[0].phase is None


def test_phase_is_not_checked_when_the_applicant_type_is_missing():
    assert _request(None, budget_items=[_budget()]).budget_items[0].phase == '1단계'


def test_all_row_errors_are_reported_together():
    with pytest.raises(ValidationError) as exc:
        _request('preliminary', budget_items=[
            _budget(phase=None, total_amount=10, government_amount=5, self_cash_amount=2, self_in_kind_amount=3),
            _budget(phase=None)])
    assert _locs(exc) == [('budget_items', 0, 'phase'), ('budget_items', 0, 'self_in_kind_amount'), ('budget_items', 1, 'phase')]


# ── 추진 일정 한 줄 ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('field', ['category', 'content', 'period'])
def test_schedule_row_requires_category_content_and_period(field):
    row = _schedule()
    del row[field]
    with pytest.raises(ValidationError) as exc:
        _request(schedule_items=[row])
    assert _locs(exc) == [('schedule_items', 0, field)]
    with pytest.raises(ValidationError):
        _request(schedule_items=[_schedule(**{field: '  '})])


def test_schedule_detail_is_optional_and_stored_as_empty_text():
    row = _schedule()
    del row['detail']
    assert _request(schedule_items=[row]).schedule_items[0].detail == ''
    assert _request(schedule_items=[_schedule(detail=None)]).schedule_items[0].detail == ''


@pytest.mark.parametrize('period', ['2026.05~2026.07', '2026-05 ~ 2026-07', '2026년 5월 ~ 7월', '2027.01'])
def test_schedule_period_with_a_year_is_accepted(period):
    assert _request(schedule_items=[_schedule(period=period)]).schedule_items[0].period == period


@pytest.mark.parametrize('period', ['5월~7월', '미정', '3개월'])
def test_schedule_period_without_a_year_is_rejected(period):
    with pytest.raises(ValidationError) as exc:
        _request(schedule_items=[_schedule(period=period)])
    assert _locs(exc) == [('schedule_items', 0, 'period')]


# ── POST /projects의 422 ─────────────────────────────────────────────────────────────────
def _payload(**overrides):
    base = {'applicant_type': 'corp', 'biz_type': '법인', 'ceo_name': '박테스트', 'founded_at': '2024-01-01',
            'description': 'AI 기반 서비스', 'team_members': [], 'pricing_items': []}
    base.update(overrides)
    return base


def test_post_projects_answers_422_with_row_and_cell_location(authed_client):
    payload = _payload(budget_items=[_corp_budget(), _corp_budget(total_amount=100, government_amount=60)])
    r = authed_client.post('/projects', data={'payload': json.dumps(payload)})
    assert r.status_code == 422, r.text
    body = r.json()
    assert body['code'] == 'VALIDATION_ERROR'
    assert [e['loc'] for e in body['detail']] == [['budget_items', 1, 'total_amount']]
    assert '총사업비' in body['detail'][0]['msg']


def test_post_projects_reports_a_missing_amount_at_its_cell(authed_client):
    row = _corp_budget()
    del row['self_cash_amount']
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload(budget_items=[row]))})
    assert r.status_code == 422, r.text
    assert [e['loc'] for e in r.json()['detail']] == [['budget_items', 0, 'self_cash_amount']]
