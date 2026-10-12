"""협약기간 내 일정의 끝나는 달 ≤ 개발 종료월 (SB-354 · F19).

검증-1이 같은 기준으로 그 일정을 '입력 오류'로 실패 처리하고 재작성으로도 고쳐지지 않아서, 입력 때 422로 막는다.
협약 이후(growth) 일정과 개발 종료월이 없는 요청은 검사하지 않고, 협약기간 최대 개월 수는 공고마다 달라 막지 않는다.
오류 위치는 `schedule_items[i].period`라 화면이 그 줄의 '추진 기간' 칸을 표시할 수 있다.

실행:
    pytest tests/test_schedule_within_dev_period.py -v
"""
import pytest
from pydantic import ValidationError

from app import schemas


def _schedule(period='2026.05~2026.07', section='feasibility'):
    return {'section': section, 'category': '개발', 'content': '모델 고도화', 'period': period, 'detail': ''}


def _request(schedules, dev_end_month='2026-08', **overrides):
    base = {'applicant_type': 'individual', 'ceo_name': '가', 'description': '아이디어',
            'dev_start_month': '2026-05', 'dev_end_month': dev_end_month, 'schedule_items': schedules}
    base.update(overrides)
    return schemas.ProjectCreateRequest.model_validate(base)


def _locs(exc: pytest.ExceptionInfo) -> list[tuple]:
    return [e['loc'] for e in exc.value.errors()]


def test_row_ending_after_the_development_end_month_is_rejected_with_its_period_location():
    with pytest.raises(ValidationError) as exc:
        _request([_schedule('2026.05~2026.07'), _schedule('2026.08~2026.09')])
    assert _locs(exc) == [('schedule_items', 1, 'period')]


def test_row_ending_in_the_development_end_month_is_accepted():
    assert len(_request([_schedule('2026.06~2026.08')]).schedule_items) == 1


def test_every_late_row_is_reported():
    with pytest.raises(ValidationError) as exc:
        _request([_schedule('2026.05~2026.09'), _schedule('2026.05~2026.07'), _schedule('2026.10~2026.12')])
    assert _locs(exc) == [('schedule_items', 0, 'period'), ('schedule_items', 2, 'period')]


@pytest.mark.parametrize('period', ['2026-05 ~ 2026-09', '2026/05~2026/09', '2026년 5월 ~ 2026년 9월', '2026.5~2026.9'])
def test_the_latest_month_is_read_the_same_way_as_verification_1(period):
    with pytest.raises(ValidationError) as exc:
        _request([_schedule(period)])
    assert _locs(exc) == [('schedule_items', 0, 'period')]


def test_a_year_ahead_of_the_development_end_is_rejected_even_when_the_month_number_is_smaller():
    with pytest.raises(ValidationError):
        _request([_schedule('2026.11~2027.02')], dev_end_month='2026-12')


def test_after_agreement_rows_are_not_checked():
    assert len(_request([_schedule('2027.01~2027.12', section='growth')]).schedule_items) == 1


def test_no_development_end_month_means_no_check():
    assert len(_request([_schedule('2030.01~2030.12')], dev_end_month=None).schedule_items) == 1


def test_a_period_with_no_readable_month_is_left_to_the_year_check():
    # 연도만 있고 월을 읽을 수 없으면 비교할 달이 없다(검증-1도 이런 줄은 건너뛴다)
    assert len(_request([_schedule('2026')]).schedule_items) == 1


def test_the_agreement_month_limit_is_not_checked_here():
    # 예비창업 8개월 · 초기창업 10개월은 공고마다 다르다 — 12개월 일정도 개발 종료월 안이면 받는다
    assert len(_request([_schedule('2026.01~2026.12')], dev_end_month='2026-12').schedule_items) == 1
