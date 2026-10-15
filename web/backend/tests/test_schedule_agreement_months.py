r"""협약기간 내 일정의 개월 수 ≤ 협약기간 최대 개월 수 (누리 님 2026-10-13 부탁).

서비스는 2026년 공고 기준으로 운영하므로 최대 개월 수를 신청자 유형별로 고정한다 — 예비창업자 8개월 · 개인사업자 · 법인 10개월. 세는 법은 검증-1과 같다:
협약기간 내(feasibility) 줄만 보고, 추진기간에서 `(20\d{2})[-./~년\s]*(\d{1,2})`로 연 · 월을 모두 읽어(월 1 ~ 12만) 가장 이른 달부터 가장 늦은 달까지
첫 달과 끝 달을 모두 센다(2026-03 ~ 2026-10 = 8개월). 달을 하나도 못 읽으면 검사하지 않는다. 오류 위치는 `schedule_items[i].period`다.

실행:
    pytest tests/test_schedule_agreement_months.py -v
"""
import pytest
from pydantic import ValidationError

from app import schemas


def _schedule(period, section='feasibility'):
    return {'section': section, 'category': '개발', 'content': '모델 고도화', 'period': period, 'detail': ''}


def _request(schedules, applicant_type='preliminary', **overrides):
    base = {'applicant_type': applicant_type, 'ceo_name': '가', 'description': '아이디어', 'schedule_items': schedules}
    if applicant_type != 'preliminary':
        base['biz_type'] = '법인' if applicant_type == 'corp' else '개인'
    base.update(overrides)
    return schemas.ProjectCreateRequest.model_validate(base)


def _locs(exc):
    return [e['loc'] for e in exc.value.errors()]


def test_the_limits_are_fixed_per_applicant_type():
    assert schemas.AGREEMENT_MAX_MONTHS == {'preliminary': 8, 'individual': 10, 'corp': 10}


@pytest.mark.parametrize('applicant_type,limit', [('preliminary', 8), ('individual', 10), ('corp', 10)])
def test_exactly_the_limit_is_accepted_and_one_more_month_is_rejected(applicant_type, limit):
    assert len(_request([_schedule(f'2026.01~2026.{limit:02d}')], applicant_type).schedule_items) == 1  # 1월 ~ limit월 = limit개월
    with pytest.raises(ValidationError) as exc:
        _request([_schedule(f'2026.01~2026.{limit + 1:02d}')], applicant_type)
    assert _locs(exc) == [('schedule_items', 0, 'period')]
    assert f'{limit + 1}개월' in exc.value.errors()[0]['msg']


def test_the_count_spans_all_rows_from_the_earliest_to_the_latest_month():
    rows = [_schedule('2026.03~2026.05'), _schedule('2026.08~2026.11')]  # 3월 ~ 11월 = 9개월
    with pytest.raises(ValidationError) as exc:
        _request(rows, 'preliminary')
    assert _locs(exc) == [('schedule_items', 1, 'period')]  # 가장 늦은 달이 나온 줄
    assert len(_request(rows, 'individual').schedule_items) == 2  # 개인사업자는 10개월까지


def test_the_count_crosses_the_year_boundary():
    assert len(_request([_schedule('2026.11~2027.06')], 'preliminary').schedule_items) == 1  # 11 ~ 6 = 8개월
    with pytest.raises(ValidationError):
        _request([_schedule('2026.11~2027.07')], 'preliminary')  # 9개월


@pytest.mark.parametrize('period', ['2026-03 ~ 2026-12', '2026/03~2026/12', '2026년 3월 ~ 2026년 12월', '2026.3~2026.12'])
def test_months_are_read_the_same_way_as_verification_1(period):
    with pytest.raises(ValidationError):
        _request([_schedule(period)], 'preliminary')


def test_after_agreement_rows_are_not_counted():
    rows = [_schedule('2026.03~2026.06'), _schedule('2026.07~2027.12', section='growth')]
    assert len(_request(rows, 'preliminary').schedule_items) == 2


def test_months_outside_1_to_12_are_skipped_and_a_year_only_period_is_not_checked():
    assert len(_request([_schedule('2026.03~2026.13')], 'preliminary').schedule_items) == 1  # 13월은 버리고 3월 하나
    assert len(_request([_schedule('2026')], 'preliminary').schedule_items) == 1


def test_no_applicant_type_or_no_schedule_is_not_checked():
    assert len(_request([_schedule('2026.01~2027.12')], None).schedule_items) == 1
    assert _request([], 'preliminary').schedule_items == []


def test_it_works_together_with_the_development_end_month_check():
    with pytest.raises(ValidationError) as exc:
        _request([_schedule('2026.03~2026.12')], 'preliminary', dev_start_month='2026-03', dev_end_month='2026-08')
    assert len(exc.value.errors()) >= 1


@pytest.mark.parametrize('applicant_type,phrase', [('preliminary', '예비창업자는 협약기간이'), ('individual', '개인사업자 · 법인은 협약기간이'), ('corp', '개인사업자 · 법인은 협약기간이')])
def test_the_message_uses_the_right_particle_for_each_applicant_type(applicant_type, phrase):
    with pytest.raises(ValidationError) as exc:
        _request([_schedule('2026.01~2026.12')], applicant_type)
    assert phrase in exc.value.errors()[0]['msg']
