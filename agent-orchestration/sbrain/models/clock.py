"""시각 — 프로세스 안의 '지금'은 이 모듈의 UTC 시계 하나에서 나온다.

- 프로세스 안의 모든 시각은 시간대가 있는 UTC다. datetime.now()(로컬 시각) · datetime.utcnow()(시간대 없음)를
  쓰지 않고 utc_now()를 쓴다. 시계를 주입받는 곳은 utc_clock()으로 감싸 시간대 없는 값을 UTC로 바꾼다.
- 시간대 없는 값을 받으면 UTC로 본다(as_utc) — 옛 JSON · DB 값, 웹이 넘기는 시각 인자, 테스트가 넘기는 값.
- DB DATETIME 칸에는 시간대 없는 UTC 값을 넣는다(naive_utc). 읽을 때 UTC를 붙인다(as_utc).
- '오늘'이 필요한 판단(자격 판정 기준일 · 마감 안내 · 스텁 공고 날짜)은 한국 날짜다(kst_today).
  한국은 일광 절약 시간이 없어 UTC+9 고정 오프셋으로 계산한다(새 패키지 없이).
- 프로젝트 안의 다른 패키지를 import하지 않는다(엔진 · 저장소 · 흐름이 모두 쓴다).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable, overload

UTC = timezone.utc
KST = timezone(timedelta(hours=9), "KST")   # 한국 표준시 (UTC+9 고정, 일광 절약 시간 없음)
UTC_MIN = datetime.min.replace(tzinfo=UTC)  # 정렬 기본값 — 시간대 있는 값과 비교할 수 있는 가장 이른 시각


def utc_now() -> datetime:
    """지금 (시간대 있는 UTC)."""
    return datetime.now(UTC)


@overload
def as_utc(dt: datetime) -> datetime: ...
@overload
def as_utc(dt: None) -> None: ...
def as_utc(dt: datetime | None) -> datetime | None:
    """시간대 있는 UTC로 — 시간대가 없으면 UTC로 보고 붙이고, 다른 시간대면 UTC로 바꾼다. None은 그대로."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


@overload
def naive_utc(dt: datetime) -> datetime: ...
@overload
def naive_utc(dt: None) -> None: ...
def naive_utc(dt: datetime | None) -> datetime | None:
    """DB DATETIME 칸에 넣을 값 — UTC로 바꾼 뒤 시간대를 뗀다. None은 그대로."""
    return None if dt is None else as_utc(dt).replace(tzinfo=None)


def utc_clock(now: Callable[[], datetime]) -> Callable[[], datetime]:
    """주입받은 시계를 시간대 있는 UTC를 돌려주는 시계로 감싼다 (테스트의 시간대 없는 시계는 UTC로 본다).

    이미 감싼 시계 · utc_now는 그대로 돌려준다(여러 구성 요소가 같은 시계를 받아도 한 겹만).
    """
    if now is utc_now or getattr(now, "utc_clock", False):
        return now

    def clock() -> datetime:
        return as_utc(now())
    clock.utc_clock = True  # type: ignore[attr-defined]
    return clock


def kst_today(now: datetime | None = None) -> date:
    """한국 날짜 — now(없으면 지금)를 UTC+9로 옮긴 날짜. UTC 15:00 이후는 한국에서 다음 날이다."""
    return as_utc(now if now is not None else utc_now()).astimezone(KST).date()


def kst_month(dt: datetime) -> str:
    """한국 날짜 기준 달 'YYYY-MM'."""
    return as_utc(dt).astimezone(KST).strftime("%Y-%m")


__all__ = ["KST", "UTC", "UTC_MIN", "as_utc", "kst_month", "kst_today", "naive_utc", "utc_clock", "utc_now"]
