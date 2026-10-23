import datetime

import pytest

from app.notice_status import KST, notice_display_status

TODAY = datetime.date(2026, 10, 21)
BEFORE = TODAY - datetime.timedelta(days=1)
AFTER = TODAY + datetime.timedelta(days=1)


@pytest.mark.parametrize(('status', 'start', 'end', 'kind', 'expected'), [
    ('open', BEFORE, BEFORE, 'fixed', '마감'),
    ('closed', AFTER, AFTER, 'fixed', '접수 예정'),
    ('closed', BEFORE, AFTER, 'fixed', '마감'),
    ('open', BEFORE, AFTER, 'fixed', '모집중'),
    ('unknown', BEFORE, AFTER, 'fixed', '접수기간 내 · 원문 확인'),
    ('unknown', TODAY, TODAY, 'fixed', '접수기간 내 · 원문 확인'),
    ('unknown', None, None, None, '확인 필요'),
    ('unknown', BEFORE, None, None, '확인 필요'),
    ('unknown', None, AFTER, None, '확인 필요'),
    ('unknown', BEFORE, AFTER, 'budget_exhaustion', '확인 필요'),
    ('unknown', BEFORE, AFTER, 'rolling', '확인 필요'),
    ('unknown', BEFORE, AFTER, 'until_filled', '확인 필요'),
    ('unknown', AFTER, BEFORE, 'fixed', '확인 필요'),
    ('unknown', BEFORE, AFTER, 'unknown', '접수기간 내 · 원문 확인'),
    ('open', None, None, 'rolling', '모집중'),
])
def test_display_status(status, start, end, kind, expected):
    assert notice_display_status(status, start, end, kind, today=TODAY) == expected


def test_korea_date_at_utc_day_boundary():
    utc_time = datetime.datetime(2026, 10, 20, 15, 0, tzinfo=datetime.UTC)
    assert utc_time.astimezone(KST).date() == TODAY
