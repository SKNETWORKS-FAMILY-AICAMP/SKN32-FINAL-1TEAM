"""카테고리별 지면 본문(원페이지 · 웹개발 · AI API)을 조립한다."""
from __future__ import annotations

from engineering_agent.infographic.style import BRAND_COLORS, CATEGORY_ACCENT
from engineering_agent.infographic.layout import (
    FLOW_BOX,
    FLOW_LINES,
    FLOW_PER_ROW,
    ONEPAGE_CARD_PAD,
    ONEPAGE_DETAIL_LINES,
    ONEPAGE_FOOT_LINES,
    ONEPAGE_GAP,
    ONEPAGE_HALF_CARD,
    ONEPAGE_VALUE_LINES,
    PAGE_WIDTH,
    PIPE_BOX,
    PIPE_LINES,
    W_AI_PIPELINE,
    W_FEATURE_DETAIL,
    W_METRIC_LABEL,
    W_ONEPAGE_FEATURE,
    W_ONEPAGE_TARGET,
    W_ONEPAGE_VALUE,
    W_WEBDEV_FLOW,
    fit,
)
from engineering_agent.infographic.svg_parts import (
    DETAIL_TEXT,
    EMPTY_VALUE_TEXT,
    card,
    esc,
    feature_bullet_list,
    section_title,
    wrapped_text,
)


# ---------------------------------------------------------------------------
# 카테고리별 본문(body) 조립
# ---------------------------------------------------------------------------


# 원페이지 카드 색. 모두 흰 카드 위에서 명도 대비 4.5:1 이상(검증-2 3번).
_ONEPAGE_TONES = {
    "problem": "#B91C1C",
    "solution": "#047857",
    "revenue_unit_price": "#B45309",
    "timeline_baseline": "#6D28D9",
    "metric": "#1D4ED8",
    "muted": "#475569",
}


def _label(x: float, y: float, text: str, fill: str, size: int = 17) -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="700" data-role="label" '
            f'fill="{fill}">{esc(text)}</text>')


def _value_card(x: float, y: float, field: str, label: str, value: str,
                max_lines: int) -> tuple[str, int]:
    """라벨 + 여러 줄 값의 (글자 조각, 줄 수). 카드 rect는 높이가 정해진 뒤 그린다."""
    text, lines = wrapped_text(
        x + ONEPAGE_CARD_PAD, y + 66, value, size=15, max_width=W_ONEPAGE_VALUE,
        max_lines=max_lines, line_height=22, fill=BRAND_COLORS["text"],
        attrs=f'data-field="{field}" data-role="value"')
    return _label(x + ONEPAGE_CARD_PAD, y + 36, label, _ONEPAGE_TONES[field]) + text, lines


def _card_row(y: float, cells: list[tuple[str, str, str]], max_lines: int,
              arrow: bool = False) -> tuple[list[str], float]:
    """2단 카드 한 줄. 두 카드 높이를 긴 쪽에 맞춘다."""
    x_right = 40 + ONEPAGE_HALF_CARD + ONEPAGE_GAP
    built = [_value_card(x, y, field, label, value, max_lines)
             for x, (field, label, value) in zip((40, x_right), cells)]
    height = 66 + (max(lines for _, lines in built) - 1) * 22 + 28
    parts = [card(x, y, ONEPAGE_HALF_CARD, height) for x in (40, x_right)]
    parts += [svg for svg, _ in built]
    if arrow:
        mx, my = 40 + ONEPAGE_HALF_CARD + ONEPAGE_GAP / 2, y + height / 2
        parts.append(
            f'<circle cx="{mx}" cy="{my}" r="15" fill="{BRAND_COLORS["primary"]}"/>'
            f'<path d="M{mx - 6},{my} L{mx + 5},{my} M{mx + 1},{my - 5} L{mx + 6},{my} '
            f'L{mx + 1},{my + 5}" stroke="#FFFFFF" stroke-width="2.4" fill="none" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')
    return parts, y + height


def _metric_row(y: float, metrics: list[dict]) -> tuple[list[str], float]:
    """계획서에서 뽑은 핵심 수치 카드(최대 3개).

    data-role이 없어 정보 계층 판정에는 들어가지 않고, data-field가 있어 검증-2의
    '계획서에 없는 숫자' 감점 대상에는 들어간다.
    """
    n = len(metrics)
    width = (PAGE_WIDTH - 80 - (n - 1) * ONEPAGE_GAP) / n
    parts: list[str] = []
    for i, metric in enumerate(metrics):
        x = 40 + i * (width + ONEPAGE_GAP)
        cx = x + width / 2
        parts.append(card(x, y, width, 100))
        parts.append(
            f'<text x="{cx}" y="{y + 52}" font-size="32" font-weight="800" text-anchor="middle" '
            f'data-field="key_metric" fill="{_ONEPAGE_TONES["metric"]}">'
            f'{esc(fit(metric["value"], 32, width - 24))}</text>')
        parts.append(
            f'<text x="{cx}" y="{y + 80}" font-size="13" text-anchor="middle" '
            f'data-field="key_metric_label" fill="{_ONEPAGE_TONES["muted"]}">'
            f'{esc(fit(metric["label"], 13, W_METRIC_LABEL))}</text>')
    return parts, y + 100


def _feature_cards(y: float, features: list[str], details: list, *, accent: str,
                   require_detail: bool = True) -> tuple[list[str], float]:
    """핵심 기능 2열 카드: 체크 배지 + 기능명 + 계획서에서 뽑은 설명(최대 2줄).

    설명 노드의 data-field="feature_detail"과 data-feature="기능명"은 검증-2가 원페이지
    기능별 설명을 찾는 표식이다. 원페이지(require_detail)는 설명이 비면 "정보 없음"을
    적고 검증-2가 그 기능을 인정하지 않는다. 웹개발 · AI API 지면은 채점 대상이
    아니라 설명이 없으면 그 줄을 비운다.
    """
    if not features:
        svg, y = feature_bullet_list(40, y + 20, features)
        return [svg], y
    parts: list[str] = []
    x_right = 40 + ONEPAGE_HALF_CARD + ONEPAGE_GAP
    for start in range(0, len(features), 2):
        row = []
        for col, i in enumerate(range(start, min(start + 2, len(features)))):
            x, feat = (40, x_right)[col], features[i]
            detail = (str(details[i]) if i < len(details) else "").strip()
            if detail or require_detail:
                text, lines = wrapped_text(
                    x + ONEPAGE_CARD_PAD, y + 72, detail, size=14, max_width=W_FEATURE_DETAIL,
                    max_lines=ONEPAGE_DETAIL_LINES, line_height=20, fill=DETAIL_TEXT,
                    attrs=f'data-field="feature_detail" data-feature="{esc(feat)}" data-role="value"')
            else:
                text, lines = "", 0
            # 배지에 번호 대신 체크 표시를 그린다. 검증-2는 지면의 모든 숫자를 계획서와
            # 대조하므로 장식용 숫자도 "계획서에 없는 수치"가 된다.
            bx, by = x + ONEPAGE_CARD_PAD, y + 20
            head = (
                f'<rect x="{bx}" y="{by}" width="28" height="28" rx="8" fill="{accent}"/>'
                f'<path d="M{bx + 8},{by + 14.5} L{bx + 12.5},{by + 19} L{bx + 20},{by + 10}" '
                f'stroke="#FFFFFF" stroke-width="2.6" fill="none" stroke-linecap="round" '
                f'stroke-linejoin="round"/>'
                f'<text x="{x + 62}" y="{y + 40}" font-size="16" font-weight="700" '
                f'data-field="feature" data-feature="{esc(feat)}" data-role="value" '
                f'fill="{BRAND_COLORS["text"]}">{esc(fit(feat, 16, W_ONEPAGE_FEATURE))}</text>')
            row.append((x, head + text, lines))
        most = max(lines for *_, lines in row)
        height = 72 + (most - 1) * 20 + 26 if most else 68
        parts += [card(x, y, ONEPAGE_HALF_CARD, height) for x, *_ in row]
        parts += [svg for _, svg, _ in row]
        y += height + ONEPAGE_GAP
    return parts, y - ONEPAGE_GAP


def _build_onepage_body(data: dict, features: list[str]) -> tuple[str, int]:
    """원페이지 지면: 머리말 목표 고객 → 핵심 수치 → 문제·해결 → 핵심 기능 → 수익·일정.

    필수 여섯 정보 중 아이템명은 템플릿 머리말이, 나머지 다섯은 여기서 그린다. 값 노드에
    data-field를 붙여 채점기가 순서가 아니라 표식으로 찾게 한다.
    """
    target = str(data.get("target_users", "")).strip() or EMPTY_VALUE_TEXT
    parts = [
        _label(40, 132, "목표 고객", "#FFFFFF", size=16),
        f'<text x="128" y="132" font-size="15" data-field="target_users" data-role="value" '
        f'fill="#FFFFFF">{esc(fit(target, 15, W_ONEPAGE_TARGET))}</text>',
    ]
    metrics = [{"value": str(m.get("value", "")).strip(), "label": str(m.get("label", "")).strip()}
               for m in (data.get("key_metrics") or []) if isinstance(m, dict)]
    metrics = [m for m in metrics if m["value"]][:3]
    y = 182
    if metrics:
        row, y = _metric_row(y, metrics)
        parts += row
        y += ONEPAGE_GAP + 4

    row, y = _card_row(y, [("problem", "문제 정의", str(data.get("problem", ""))),
                           ("solution", "해결 방안", str(data.get("solution", "")))],
                       ONEPAGE_VALUE_LINES, arrow=True)
    parts += row

    y += 44
    parts.append(section_title(40, y, "핵심 기능"))
    row, y = _feature_cards(y + 18, features, data.get("feature_details") or [],
                            accent=BRAND_COLORS["primary"])
    parts += row

    row, y = _card_row(y + 24, [("revenue_unit_price", "수익 모델", str(data.get("revenue_unit_price", ""))),
                                ("timeline_baseline", "추진 일정", str(data.get("timeline_baseline", "")))],
                       ONEPAGE_FOOT_LINES)
    parts += row
    return "\n".join(parts), int(y + 36)


def _step_badge(cx: float, cy: float, n: int, color: str) -> str:
    """흐름 단계 번호 원. 웹개발 · AI API 지면은 검증-2 계획서 대조 대상이 아니라
    번호를 써도 된다(원페이지 기능 카드는 체크 표시를 쓴다)."""
    return (f'<circle cx="{cx}" cy="{cy}" r="13" fill="{color}"/>'
            f'<text x="{cx}" y="{cy + 5}" font-size="13" font-weight="700" '
            f'text-anchor="middle" fill="#FFFFFF">{n}</text>')


def _arrow(x1: float, x2: float, y: float) -> str:
    return (f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{BRAND_COLORS["text_muted"]}" '
            f'stroke-width="2" marker-end="url(#arrowhead)"/>')


def _build_webdev_body(data: dict, features: list[str]) -> tuple[str, int]:
    """웹개발: 핵심 기능 카드 + 사용자 흐름(번호 붙은 단계 상자, 한 줄 최대 5개)."""
    accent = CATEGORY_ACCENT["웹개발"]
    flow_steps = [str(s) for s in (data.get("flow_steps") or data.get("user_flow") or [])]

    parts = [section_title(40, 150, "핵심 기능")]
    row, y = _feature_cards(168, features, data.get("feature_details") or [],
                            accent=accent, require_detail=False)
    parts += row

    if flow_steps:
        y += 50
        parts.append(section_title(40, y, "사용자 흐름"))
        y += 22
        for start in range(0, len(flow_steps), FLOW_PER_ROW):
            chunk = flow_steps[start:start + FLOW_PER_ROW]
            n = len(chunk)
            gap = (PAGE_WIDTH - 80 - FLOW_PER_ROW * FLOW_BOX) / (FLOW_PER_ROW - 1)
            left = (PAGE_WIDTH - (n * FLOW_BOX + (n - 1) * gap)) / 2
            built = []
            for j, step in enumerate(chunk):
                bx = left + j * (FLOW_BOX + gap)
                text, lines = wrapped_text(
                    bx + FLOW_BOX / 2, y + 60, step, size=15, max_width=W_WEBDEV_FLOW,
                    max_lines=FLOW_LINES, line_height=20, fill=BRAND_COLORS["text"],
                    attrs='font-weight="700" data-field="flow_steps" data-role="value"',
                    anchor="middle")
                built.append((bx, text, lines))
            height = 60 + (max(lines for *_, lines in built) - 1) * 20 + 22
            for j, (bx, text, _) in enumerate(built):
                parts.append(card(bx, y, FLOW_BOX, height, stroke=accent))
                parts.append(_step_badge(bx + FLOW_BOX / 2, y + 26, start + j + 1, accent))
                parts.append(text)
                if j < n - 1:
                    parts.append(_arrow(bx + FLOW_BOX + 4, bx + FLOW_BOX + gap - 4, y + height / 2))
            y += height + ONEPAGE_GAP
        y -= ONEPAGE_GAP
    return "\n".join(parts), int(y + 40)


def _build_ai_api_body(data: dict, features: list[str]) -> tuple[str, int]:
    """AI API: 입력 → 처리 → 출력 파이프라인 카드 + 핵심 기능 카드."""
    accent = CATEGORY_ACCENT["AI_API"]
    pipeline = data.get("pipeline") or {}
    stages = [("input", "입력"), ("process", "처리"), ("output", "출력")]

    parts = [section_title(40, 150, "처리 흐름")]
    y = 172
    gap = (PAGE_WIDTH - 80 - 3 * PIPE_BOX) / 2
    built = []
    for i, (key, label) in enumerate(stages):
        bx = 40 + i * (PIPE_BOX + gap)
        text, lines = wrapped_text(
            bx + ONEPAGE_CARD_PAD, y + 70, str(pipeline.get(key, "")), size=15,
            max_width=W_AI_PIPELINE, max_lines=PIPE_LINES, line_height=21,
            fill=BRAND_COLORS["text"], attrs=f'data-field="pipeline.{key}" data-role="value"')
        head = (_step_badge(bx + ONEPAGE_CARD_PAD + 13, y + 30, i + 1, accent)
                + _label(bx + ONEPAGE_CARD_PAD + 36, y + 36, label, accent))
        built.append((bx, head + text, lines))
    height = 70 + (max(lines for *_, lines in built) - 1) * 21 + 26
    for i, (bx, svg, _) in enumerate(built):
        parts.append(card(bx, y, PIPE_BOX, height, stroke=accent))
        parts.append(svg)
        if i < 2:
            parts.append(_arrow(bx + PIPE_BOX + 6, bx + PIPE_BOX + gap - 6, y + height / 2))
    y += height + 50

    parts.append(section_title(40, y, "핵심 기능"))
    row, y = _feature_cards(y + 18, features, data.get("feature_details") or [],
                            accent=accent, require_detail=False)
    parts += row
    return "\n".join(parts), int(y + 40)


BODY_BUILDERS = {
    "원페이지": _build_onepage_body,
    "웹개발": _build_webdev_body,
    "AI_API": _build_ai_api_body,
}
