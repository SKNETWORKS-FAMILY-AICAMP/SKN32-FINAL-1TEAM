"""글자 폭 추정과 지면 폭 판정. 값이 잘리거나 넘치는지는 여기서 정한다."""
from __future__ import annotations

from engineering_agent.infographic.style import CATEGORY_TEMPLATE_FILE


PAGE_WIDTH = 900

# 각 자리의 글자가 쓸 수 있는 최대 폭(px). 본문 builder가 실제로 쓰는 좌표에서 나온 값이라
# 레이아웃을 바꾸면 여기도 같이 바꿔야 한다 — overflow_fields()가 이 값으로 판정한다.
W_TITLE = 660          # 머리말 아이템명: x=40, 배지가 x=716에서 시작
W_ONEPAGE_VALUE = 820  # 원페이지 값: x=40, 우여백 40
W_FEATURE_LIST = 800   # 불릿 리스트: x=62, 우여백 40
W_FEATURE_DETAIL = 800  # 원페이지 기능 설명: 기능명 아랫줄, 같은 폭
W_WEBDEV_FEATURE = 330  # 2단 그리드 한 칸: col_w 400 - 아이콘 영역
W_WEBDEV_FLOW = 170    # 플로우 박스 190 - 좌우 여백
W_AI_PIPELINE = 200    # 파이프라인 박스 220 - 좌우 여백


def estimate_text_width(text: str, font_size: float) -> float:
    """글자 폭 어림값. 한글·CJK는 전각(≈font_size), 그 외는 반각(≈0.55배)으로 센다.

    정확한 폭은 폰트 메트릭이 있어야 나오지만, 여기서 필요한 것은 "지면을 넘겼는가"
    수준의 판정이라 이 어림으로 충분하다. 표준 라이브러리만 쓴다는 제약도 지킨다.
    """
    wide = sum(1 for ch in text if ord(ch) > 0x2000)
    return wide * font_size + (len(text) - wide) * font_size * 0.55


def fit(text: str, font_size: float, max_width: float) -> str:
    """지면 폭을 넘기면 말줄임표로 잘라낸다.

    넘치는 채로 그리면 지면 밖으로 밀려나 사람에게도 보이지 않고 검증 6번에도
    걸린다. 자르는 쪽이 낫고, 잘렸다는 사실은 overflow_fields()가 따로 보고한다.
    """
    if estimate_text_width(text, font_size) <= max_width:
        return text
    kept = ""
    for ch in text:
        if estimate_text_width(kept + ch + "…", font_size) > max_width:
            break
        kept += ch
    return kept + "…"


def _slots(category: str, data: dict) -> list[tuple[str, str, float, float]]:
    """(필드명, 글자, 글자크기, 허용폭) 목록. 본문 builder가 쓰는 자리와 일치한다."""
    features = [str(f) for f in (data.get("features") or [])]
    slots: list[tuple[str, str, float, float]] = [
        ("item_name", str(data.get("item_name", "")), 30, W_TITLE),
    ]
    if category == "원페이지":
        for field in ("target_users", "problem", "solution",
                      "revenue_unit_price", "timeline_baseline"):
            slots.append((field, str(data.get(field, "")), 16, W_ONEPAGE_VALUE))
        slots += [("feature", f, 16, W_FEATURE_LIST) for f in features]
        slots += [("feature_detail", str(d), 14, W_FEATURE_DETAIL)
                  for d in (data.get("feature_details") or [])]
    elif category == "웹개발":
        slots += [("feature", f, 16, W_WEBDEV_FEATURE) for f in features]
        slots += [("flow_steps", str(s), 15, W_WEBDEV_FLOW)
                  for s in (data.get("flow_steps") or [])]
    else:  # AI_API
        pipeline = data.get("pipeline") or {}
        slots += [(f"pipeline.{key}", str(pipeline.get(key, "")), 15, W_AI_PIPELINE)
                  for key in ("input", "process", "output")]
        slots += [("feature", f, 16, W_FEATURE_LIST) for f in features]
    return slots


def overflow_fields(category: str, data: dict) -> list[str]:
    """지면 폭을 넘겨 잘라내야 하는 값의 필드명 목록.

    T-B2 자체 검사가 이걸 실패로 올려 재수행에서 더 짧은 문장을 받게 한다.
    지면 한 장이 산출물 전체인 원페이지에서는 넘쳐서 안 보이는 것이 빠진 것과 같다
    (기획서 5-4).
    """
    if category not in CATEGORY_TEMPLATE_FILE:
        raise ValueError(f"알 수 없는 카테고리: {category!r}")
    seen: list[str] = []
    for field, text, size, max_width in _slots(category, data):
        if text.strip() and estimate_text_width(text, size) > max_width and field not in seen:
            seen.append(field)
    return seen
