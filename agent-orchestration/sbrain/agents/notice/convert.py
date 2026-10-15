"""공고 서버 응답 값 검사 · 변환 도움 (spec 3.3 · 4.1.3 · 4.4).

- 약속 밖이면 `FormatError`를 올려 tools가 재시도하게 한다. 메시지에는 키 경로(과 목록 자리)만 넣는다 — 값 · 본문은 넣지 않는다.
- 키 규칙 (spec 3.3 "필요한 키가 없거나 → FormatError"): 우리가 쓰는 키는 모두 **있어야** 한다. 값이 null일 수 있는 키도
  키 자체는 있어야 한다. 키가 없어도 되는 것은 spec이 "키가 없거나"·"없음"으로 정한 것뿐이다 — 추천 결과의
  `content_version` · `bonus_score` · `bonus_items` · `apply_period_type`, 상세의 `bonus_info` · `apply_period_type`.
  이 키에만 `missing_ok=True`를 준다.
- 수는 bool을 받지 않고(JSON true가 1로 읽히지 않게), 유한한 값만 받는다 — `1e400`처럼 넘치는 수는 inf로 읽혀 저장하면
  null이 되고 다시 읽을 때 깨진다. 실수로 바꿀 수 없을 만큼 큰 정수도 받지 않는다.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from pydantic import ValidationError

from ...orchestrator.errors import FormatError

# 모집 형태 표기 (확장, spec 4.4) — 그 밖의 값 · 없음은 '모름'
PERIOD_LABELS: dict[str, str] = {
    "fixed": "기간 있음",
    "budget_exhaustion": "예산 소진 시까지",
    "rolling": "상시·수시",
    "until_filled": "선착순·모집 완료 시까지",
}
PERIOD_UNKNOWN = "모름"


def bad(where: str) -> FormatError:
    return FormatError(f"공고 서버 응답 형식 오류: {where}")


def from_validation(where: str, e: ValidationError) -> FormatError:
    """pydantic 오류 → FormatError. 오류 메시지에는 입력 값이 들어 있어 필드 이름만 옮긴다."""
    fields = sorted({".".join(str(p) for p in err["loc"]) for err in e.errors()})
    return bad(f"{where} {fields}")


def obj(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise bad(where)
    return value


def req(d: dict[str, Any], key: str, where: str) -> Any:
    """키가 있어야 한다 (값은 null이어도 된다)."""
    if key not in d:
        raise bad(f"{where}.{key}")
    return d[key]


def _value(d: dict[str, Any], key: str, where: str, missing_ok: bool) -> Any:
    return d.get(key) if missing_ok else req(d, key, where)


def finite(v: Any, where: str) -> float:
    """유한한 수(bool 아님) → float. 넘치는 수(inf · nan) · 실수로 바꿀 수 없는 큰 정수는 약속 밖."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise bad(where)
    try:
        f = float(v)
    except OverflowError:
        raise bad(where) from None
    if not math.isfinite(f):
        raise bad(where)
    return f


def req_str(d: dict[str, Any], key: str, where: str, *, nonempty: bool = False) -> str:
    v = req(d, key, where)
    if not isinstance(v, str) or (nonempty and not v.strip()):
        raise bad(f"{where}.{key}")
    return v


def req_bool(d: dict[str, Any], key: str, where: str) -> bool:
    v = req(d, key, where)
    if not isinstance(v, bool):
        raise bad(f"{where}.{key}")
    return v


def req_int(d: dict[str, Any], key: str, where: str) -> int:
    v = req(d, key, where)
    if not isinstance(v, int) or isinstance(v, bool):
        raise bad(f"{where}.{key}")
    return v


def req_list(d: dict[str, Any], key: str, where: str) -> list[Any]:
    v = req(d, key, where)
    if not isinstance(v, list):
        raise bad(f"{where}.{key}")
    return v


def req_str_list(d: dict[str, Any], key: str, where: str) -> list[str]:
    v = req_list(d, key, where)
    if not all(isinstance(x, str) for x in v):
        raise bad(f"{where}.{key}")
    return list(v)


def opt_str(d: dict[str, Any], key: str, where: str, *, missing_ok: bool = False) -> str | None:
    """문자열 또는 null."""
    v = _value(d, key, where, missing_ok)
    if v is not None and not isinstance(v, str):
        raise bad(f"{where}.{key}")
    return v


def opt_bool(d: dict[str, Any], key: str, where: str) -> bool | None:
    """참 · 거짓 또는 null."""
    v = req(d, key, where)
    if v is not None and not isinstance(v, bool):
        raise bad(f"{where}.{key}")
    return v


def opt_number(d: dict[str, Any], key: str, where: str, *, missing_ok: bool = False) -> float | None:
    """유한한 수 또는 null."""
    v = _value(d, key, where, missing_ok)
    return None if v is None else finite(v, f"{where}.{key}")


def opt_count(d: dict[str, Any], key: str, where: str) -> int | None:
    """0 이상의 정수 또는 null (개월 · 원). 실수로 바꿀 수 없을 만큼 크면 약속 밖."""
    v = req(d, key, where)
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise bad(f"{where}.{key}")
    finite(v, f"{where}.{key}")
    return v


def opt_date(d: dict[str, Any], key: str, where: str) -> date | None:
    """'YYYY-MM-DD' → 날짜. null · ''은 null(마감일 없는 공고). 키는 있어야 한다."""
    v = req(d, key, where)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise bad(f"{where}.{key}")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise bad(f"{where}.{key}") from None


def first_text(d: dict[str, Any], keys: tuple[str, ...], where: str, default: str) -> str:
    """키 순서대로 비어 있지 않은 첫 문자열. 모두 비었으면 default. 키는 모두 있어야 한다(값은 null이어도 된다)."""
    values = [opt_str(d, key, where) for key in keys]
    for v in values:
        if v is not None and v.strip():
            return v.strip()
    return default


def period_label(value: Any) -> str:
    """모집 형태 표기 (spec 4.4) — 표에 없는 값 · 없음은 '모름'. 키가 없어도 된다."""
    return PERIOD_LABELS.get(value, PERIOD_UNKNOWN) if isinstance(value, str) else PERIOD_UNKNOWN
