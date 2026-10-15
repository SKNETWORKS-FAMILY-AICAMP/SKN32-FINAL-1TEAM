"""응답 시각은 항상 UTC · 끝에 Z다 (SB-264, 명세 11.1).

웹 표(DB)에서 읽은 시각은 시간대 표시가 없는 UTC라 그대로 내보내면 받는 쪽이 시간대를 짐작해야 한다 — 응답 스키마가 Z를 붙여 내보낸다.
프론트(time.js)는 시간대 표시가 있든 없든 UTC로 읽어 한국 시간으로 바꾸므로 화면은 달라지지 않는다.

실행:
    pytest tests/test_utc_timestamps.py -v
"""
import datetime
import json

import pytest
from pydantic import BaseModel

from app.schemas import UtcDatetime


class _Row(BaseModel):
    at: UtcDatetime
    maybe: UtcDatetime | None = None


def _dump(**kwargs) -> dict:
    return _Row(**kwargs).model_dump(mode='json')


def test_naive_datetime_is_treated_as_utc_and_gets_z():
    assert _dump(at=datetime.datetime(2026, 10, 6, 7, 14, 59))['at'] == '2026-10-06T07:14:59Z'


def test_microseconds_are_kept():
    assert _dump(at=datetime.datetime(2026, 10, 6, 7, 14, 59, 123456))['at'] == '2026-10-06T07:14:59.123456Z'


def test_aware_datetime_is_converted_to_utc():
    kst = datetime.timezone(datetime.timedelta(hours=9))
    assert _dump(at=datetime.datetime(2026, 10, 6, 16, 14, 59, tzinfo=kst))['at'] == '2026-10-06T07:14:59Z'
    assert _dump(at=datetime.datetime(2026, 10, 6, 7, 14, 59, tzinfo=datetime.UTC))['at'] == '2026-10-06T07:14:59Z'


def test_none_stays_none():
    assert _dump(at=datetime.datetime(2026, 10, 6), maybe=None)['maybe'] is None


def test_parsing_a_request_value_is_unchanged():
    parsed = _Row(at='2026-10-06T07:14:59Z')
    assert parsed.at.tzinfo is not None and parsed.at.utcoffset() == datetime.timedelta(0)


def test_api_time_is_utc_with_z_and_matches_the_real_clock(authed_client):
    """서버(이 컴퓨터는 한국 시간)의 로컬 시각이 아니라 UTC로 나가는지 — 로컬 시각을 쓰는 곳이 있으면 9시간 어긋난다."""
    created = authed_client.post('/projects', data={'payload': json.dumps({'description': '시각 점검'})})
    assert created.status_code == 201, created.text
    project_id = created.json()['project_id']

    row = next(p for p in authed_client.get('/projects').json() if p['project_id'] == project_id)

    assert row['created_at'].endswith('Z')
    shown = datetime.datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
    now = datetime.datetime.now(datetime.UTC)
    assert abs((now - shown).total_seconds()) < 120, f'{row["created_at"]} vs 지금(UTC) {now.isoformat()}'


@pytest.mark.parametrize('path', ['/projects', '/projects/notifications'])
def test_list_endpoints_never_emit_naive_times(authed_client, path):
    authed_client.post('/projects', data={'payload': json.dumps({'description': '시각 점검'})})
    for row in authed_client.get(path).json():
        for key, value in row.items():
            if key.endswith('_at') and isinstance(value, str):
                assert value.endswith('Z'), (path, key, value)
