"""글자 폭 추정과 지면 폭 판정. 값이 잘리거나 넘치는지는 여기서 정한다."""
from __future__ import annotations

from engineering_agent.infographic.style import CATEGORY_TEMPLATE_FILE


PAGE_WIDTH = 900

# 각 자리의 글자가 쓸 수 있는 최대 폭(px). 본문 builder가 실제로 쓰는 좌표에서 나온 값이라
# 레이아웃을 바꾸면 여기도 같이 바꿔야 한다 — overflow_fields()가 이 값으로 판정한다.
W_TITLE = 660          # 머리말 아이템명: x=40, 배지가 x=716에서 시작
W_FEATURE_LIST = 800   # 불릿 리스트: x=62, 우여백 40

# 원페이지 카드 배치(bodies._build_onepage_body). 값은 카드 안에서 여러 줄로 감긴다.
ONEPAGE_GAP = 20
ONEPAGE_HALF_CARD = (PAGE_WIDTH - 80 - ONEPAGE_GAP) // 2   # 2단 카드 한 칸 폭 400
ONEPAGE_CARD_PAD = 22
W_ONEPAGE_TARGET = 600                                     # 머리말 목표 고객 한 줄
W_ONEPAGE_VALUE = ONEPAGE_HALF_CARD - 2 * ONEPAGE_CARD_PAD  # 카드 속 값 356
W_FEATURE_DETAIL = W_ONEPAGE_VALUE                         # 기능 카드 설명
W_ONEPAGE_FEATURE = ONEPAGE_HALF_CARD - 62 - ONEPAGE_CARD_PAD  # 기능 카드 이름(번호 배지 옆) 316
W_METRIC_LABEL = 230                                       # 핵심 수치 카드 설명
ONEPAGE_VALUE_LINES = 3    # 문제 · 해결 카드
ONEPAGE_FOOT_LINES = 2     # 수익 모델 · 추진 일정 카드
ONEPAGE_DETAIL_LINES = 2   # 기능 설명
# 웹개발 흐름 · AI API 파이프라인 카드(bodies._build_webdev_body · _build_ai_api_body).
FLOW_BOX = 140          # 흐름 단계 상자 폭. 한 줄에 최대 5개
FLOW_PER_ROW = 5
W_WEBDEV_FLOW = FLOW_BOX - 20
FLOW_LINES = 2
PIPE_BOX = 240          # 입력 · 처리 · 출력 상자 폭
W_AI_PIPELINE = PIPE_BOX - 2 * ONEPAGE_CARD_PAD
PIPE_LINES = 3


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


def _split_long(word: str, font_size: float, max_width: float) -> list[str]:
    """한 줄 폭보다 긴 낱말을 글자 단위로 쪼갠다."""
    pieces, cur = [], ""
    for ch in word:
        if cur and estimate_text_width(cur + ch, font_size) > max_width:
            pieces.append(cur)
            cur = ""
        cur += ch
    return pieces + [cur] if cur else pieces


def wrap(text: str, font_size: float, max_width: float, max_lines: int) -> tuple[list[str], bool]:
    """띄어쓰기 단위로 줄을 감는다. (줄 목록, 잘렸는지).

    줄 수가 넘치면 마지막 줄을 말줄임표로 자른다. 줄 끝 띄어쓰기는 앞 줄에 남겨 두어
    줄을 이어 붙이면 원문과 같아지게 한다 — 검증-2는 text 노드의 글자를 이어 읽는다.
    """
    text = " ".join(str(text).split())
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        cand = f"{cur} {word}" if cur else word
        if estimate_text_width(cand, font_size) <= max_width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        parts = _split_long(word, font_size, max_width)
        lines += parts[:-1]
        cur = parts[-1] if parts else ""
    if cur:
        lines.append(cur)
    if len(lines) <= max_lines:
        return lines, False
    kept = lines[:max_lines]
    kept[-1] = fit(" ".join(lines[max_lines - 1:]), font_size, max_width)
    return kept, True


# (필드명, 글자, 글자크기, 허용폭, 최대 줄 수)
Slot = tuple[str, str, float, float, int]


def _slots(category: str, data: dict) -> list[Slot]:
    """본문 builder가 쓰는 자리와 일치한다."""
    features = [str(f) for f in (data.get("features") or [])]
    slots: list[Slot] = [("item_name", str(data.get("item_name", "")), 30, W_TITLE, 1)]
    if category == "원페이지":
        slots.append(("target_users", str(data.get("target_users", "")), 15, W_ONEPAGE_TARGET, 1))
        for field in ("problem", "solution"):
            slots.append((field, str(data.get(field, "")), 15, W_ONEPAGE_VALUE, ONEPAGE_VALUE_LINES))
        for field in ("revenue_unit_price", "timeline_baseline"):
            slots.append((field, str(data.get(field, "")), 15, W_ONEPAGE_VALUE, ONEPAGE_FOOT_LINES))
        slots += [("feature", f, 16, W_ONEPAGE_FEATURE, 1) for f in features]
        slots += [("feature_detail", str(d), 14, W_FEATURE_DETAIL, ONEPAGE_DETAIL_LINES)
                  for d in (data.get("feature_details") or [])]
        slots += [("key_metric", str(m.get("label", "")), 13, W_METRIC_LABEL, 1)
                  for m in (data.get("key_metrics") or []) if isinstance(m, dict)]
    elif category == "웹개발":
        slots += [("flow_steps", str(s), 15, W_WEBDEV_FLOW, FLOW_LINES)
                  for s in (data.get("flow_steps") or [])]
    else:  # AI_API
        pipeline = data.get("pipeline") or {}
        slots += [(f"pipeline.{key}", str(pipeline.get(key, "")), 15, W_AI_PIPELINE, PIPE_LINES)
                  for key in ("input", "process", "output")]
    if category != "원페이지":
        # 기능 카드는 세 카테고리가 같다(bodies._feature_cards).
        slots += [("feature", f, 16, W_ONEPAGE_FEATURE, 1) for f in features]
        slots += [("feature_detail", str(d), 14, W_FEATURE_DETAIL, ONEPAGE_DETAIL_LINES)
                  for d in (data.get("feature_details") or [])]
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
    for field, text, size, max_width, max_lines in _slots(category, data):
        if text.strip() and wrap(text, size, max_width, max_lines)[1] and field not in seen:
            seen.append(field)
    return seen
