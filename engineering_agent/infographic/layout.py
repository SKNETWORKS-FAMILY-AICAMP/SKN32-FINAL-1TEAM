"""글자 폭 추정과 지면 폭 판정. 값이 잘리거나 넘치는지는 여기서 정한다."""
from __future__ import annotations

import re

from engineering_agent.infographic.style import CATEGORY_TEMPLATE_FILE
from engineering_agent.infographic.design_kit import TITLE_SIZE, TITLE_WIDTH  # noqa: F401 (showcase · composer가 여기서 가져간다)


PAGE_WIDTH = 900

# 각 자리의 글자가 쓸 수 있는 최대 폭(px). 본문 builder가 실제로 쓰는 좌표에서 나온 값이라
# 레이아웃을 바꾸면 여기도 같이 바꿔야 한다 — overflow_fields()가 이 값으로 판정한다.

# 웹개발 사용자 흐름 · AI API 파이프라인(bodies). 기능 타일은 원페이지와 같다.
FLOW_PER_ROW = 5
FLOW_GAP = 40
FLOW_LINES = 2
PIPE_GAP = 56
PIPE_PANEL = (PAGE_WIDTH - 80 - 2 * PIPE_GAP) / 3   # 236
W_AI_PIPELINE = PIPE_PANEL - 48
PIPE_LINES = 3


def flow_layout(n: int):
    """흐름 단계 배치: 줄마다 (시작 번호, 개수, 왼쪽 x, 상자 폭, 간격). 폭은 첫 줄 기준으로 통일."""
    per = min(max(n, 1), FLOW_PER_ROW)
    width = (PAGE_WIDTH - 80 - (per - 1) * FLOW_GAP) / per
    rows = []
    for start in range(0, n, per):
        chunk = min(per, n - start)
        left = (PAGE_WIDTH - (chunk * width + (chunk - 1) * FLOW_GAP)) / 2
        rows.append((start, chunk, left, width, FLOW_GAP))
    return rows


def flow_text_width(n: int) -> float:
    return flow_layout(n)[0][3] - 20 if n else 0


# 원페이지 지면(onepage.build_onepage_body). 머리말 → 핵심 수치 → 문제·해결 → 핵심 기능 → 수익·일정.
OP_GAP = 16
OP_PANEL = (PAGE_WIDTH - 80 - 56) // 2   # 문제 · 해결 패널 폭 382 (사이 화살표 56)
OP_PAD = 24
W_OP_TARGET = 520                       # 머리말 목표 고객 알약 안
W_OP_VALUE = OP_PANEL - 2 * OP_PAD      # 문제 · 해결 값 334
OP_VALUE_LINES = 3
OP_FOOT = (PAGE_WIDTH - 80 - OP_GAP) // 2  # 수익 · 일정 패널 폭 402
W_OP_FOOT = OP_FOOT - 2 * OP_PAD           # 354
OP_FOOT_LINES = 2
OP_DETAIL_SIZE = 13
OP_DETAIL_LINES = 4


def feature_columns(n: int) -> int:
    """기능 타일 열 수. 한 줄에 최대 4개, 마지막 줄이 하나만 남지 않게 고른다."""
    if n <= 4:
        return max(n, 1)
    return 3 if n in (5, 6, 9) else 4


def feature_tile_width(n: int) -> float:
    cols = feature_columns(n)
    return (PAGE_WIDTH - 80 - (cols - 1) * OP_GAP) / cols


_DATE_RE = re.compile(
    r"\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?(?:\s*[1-4]\s*분기)?"
    # 기간(예: 2026년 11월~12월, 2026년 12월~2027년 3월)은 한 날짜로 묶는다.
    r"(?:\s*[~\-–]\s*(?:\d{4}\s*년\s*)?\d{1,2}\s*월(?:\s*\d{1,2}\s*일)?)?"
    # 점 · 빗금 꼴도 기간을 한 날짜로 묶는다(예: 2026.04~2026.06, 2026.05~07). 묶지 않으면 끝 날짜가
    # 다음 단계로 잘못 나뉘거나('~'만 남은 단계) 끝 달이 할 일 글에 섞인다(실측: 실제 계획서 두 건).
    r"|\d{4}[-./]\d{1,2}(?:[-./]\d{1,2})?(?:\s*[~–]\s*(?:\d{4}[-./])?\d{1,2}(?:[-./]\d{1,2})?(?!\d))?")
_EVENT_TRIM_RE = re.compile(r"^[\s,·에은는부터까지]+|(?:하고|하며|하여|이고|고|,|·|및|\s)+$")


def parse_milestones(text: str) -> list[tuple[str, str]]:
    """추진 일정 문구를 (날짜, 할 일) 목록으로 나눈다. 두 개 미만이면 빈 목록.

    글자는 모두 원문에서 잘라 쓴다 — 없는 날짜나 낱말을 만들지 않는다.
    """
    text = " ".join(str(text).split())
    # 괄호 속 날짜(예: '시범 운영(2027년 1월 15일 개시)')는 앞 단계의 설명이라 단계로 나누지 않는다.
    inside = [False] * len(text)
    depth = 0
    for i, ch in enumerate(text):
        depth += ch == "("
        inside[i] = depth > 0
        depth -= ch == ")" and depth > 0
    matches = [m for m in _DATE_RE.finditer(text) if not inside[m.start()]]
    if len(matches) < 2:
        return []
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        event = _EVENT_TRIM_RE.sub("", text[m.end():end]).strip()
        out.append((m.group(0).strip(), event))
    return out if all(event for _, event in out) else []


def estimate_text_width(text: str, font_size: float) -> float:
    """글자 폭 어림값. 한글·CJK는 전각(≈font_size), 그 외는 반각(≈0.55배)으로 센다.

    정확한 폭은 폰트 메트릭이 있어야 나오지만, 여기서 필요한 것은 "지면을 넘겼는가"
    수준의 판정이라 이 어림으로 충분하다. 표준 라이브러리만 쓴다는 제약도 지킨다.
    """
    wide = sum(1 for ch in text if ord(ch) > 0x2000)
    return wide * font_size + (len(text) - wide) * font_size * 0.55


def fit_size(text: str, font_size: float, max_width: float, min_size: float = 16) -> float:
    """큰 숫자처럼 자르면 안 되는 글자는 폭에 맞을 때까지 글자 크기를 줄인다."""
    size = font_size
    while size > min_size and estimate_text_width(text, size) > max_width:
        size -= 1
    return size


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
    """본문 builder가 쓰는 자리와 일치한다(showcase)."""
    from engineering_agent.infographic.showcase import showcase_slots
    return showcase_slots(category, data)


def overflow_fields(category: str, data: dict) -> list[str]:
    """지면 폭을 넘겨 잘라내야 하는 값의 필드명 목록.

    T-B2 자체 검사가 이걸 실패로 올려 재수행에서 더 짧은 문장을 받게 한다.
    지면 한 장이 산출물 전체인 원페이지에서는 넘쳐서 안 보이는 것이 빠진 것과 같다
    (기획서 5-4).
    """
    if category not in CATEGORY_TEMPLATE_FILE:
        raise ValueError(f"알 수 없는 카테고리: {category!r}")
    if (data.get("design_variant") or ("composed" if data.get("layout") else "showcase")) == "composed":
        # 블록 구성은 모델이 고르므로 자리를 미리 셀 수 없다. 실제로 조립해 잘린 값을 찾는다.
        from engineering_agent.infographic.composer import truncated_fields
        return truncated_fields(category, data)
    seen: list[str] = []
    for field, text, size, max_width, max_lines in _slots(category, data):
        if text.strip() and wrap(text, size, max_width, max_lines)[1] and field not in seen:
            seen.append(field)
    return seen
