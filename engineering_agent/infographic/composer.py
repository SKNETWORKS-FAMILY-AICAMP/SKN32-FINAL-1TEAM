"""LLM이 고른 블록 구성으로 인포그래픽 지면을 조립한다(design_variant="composed").

LLM은 계획서를 읽고 "어떤 블록을, 어떤 변형으로, 어떤 순서 · 폭으로" 쓸지만 고른다
(content.py의 layout). 좌표 · 글자 감기 · 그림은 전부 이 모듈과 디자인 키트
(design_kit.py · showcase.py)가 정한다 — 모델이 SVG를 직접 그리면 글자가 겹치거나
칸을 넘기 때문이다. 같은 계획서라도 모델이 다른 구성을 고르면 다른 지면이 나온다.

글자는 모두 추출값이고 장식에는 숫자를 쓰지 않는다. 필수 6정보(item_name · target_users ·
problem · solution · revenue_unit_price · timeline_baseline)와 기능 표식은 구성이 무엇이든
지면에 남도록 normalize_layout()이 빠진 블록을 채워 넣는다.
"""
from __future__ import annotations

import re

from engineering_agent.infographic import artsheet, icons
from engineering_agent.infographic.design_kit import FRAME_STYLE, FRAME_STYLES, arrow, section_frame, showcase_defs
from engineering_agent.infographic.layout import (
    PAGE_WIDTH, TITLE_SIZE, TITLE_WIDTH, estimate_text_width, fit, fit_size, parse_milestones, wrap,
)
from engineering_agent.infographic.showcase import (
    C, INNER, M, _features, _hero, _metrics_revenue, _orbital_milestones, _process, _roadmap, summary_text,
    text,
)
from engineering_agent.infographic.svg_parts import EMPTY_VALUE_TEXT, esc, wrapped_text

GAP = 14
HALF = (INNER - GAP) / 2
TOP_PAD = 42      # 섹션 탭 아래 본문 시작
BOTTOM_PAD = 20
PROBLEM = "#B42318"
PROBLEM_TINT = "#FDECEA"

# 블록 → 변형 → 쓸 수 있는 폭. 앞의 변형이 기본값이다.
CATALOG: dict[str, dict[str, tuple[str, ...]]] = {
    "hero": {"hub": ("full",), "journey": ("full",)},
    "problem_solution": {"split": ("full",), "before_after": ("full", "half")},
    "features": {"band": ("full",), "grid": ("full", "half")},
    "process": {"steps": ("full",)},
    "market": {"nested": ("half", "full")},
    "competition": {"table": ("full", "half")},
    "revenue": {"flow": ("half", "full"), "card": ("half", "full")},
    "roadmap": {"line": ("full", "half"), "orbit": ("half",)},
    "metrics": {"cards": ("full", "half"), "bars": ("half", "full"), "with_revenue": ("half",)},
    "effects": {"cards": ("full", "half")},
    "tagline": {"band": ("full",)},
}
DEFAULT_TITLES = {
    "problem_solution": "문제와 해결", "features": "핵심 기능", "process": "서비스 제공 과정",
    "market": "시장 규모", "competition": "경쟁력", "revenue": "수익 구조",
    "roadmap": "추진 일정", "metrics": "성과 목표", "effects": "기대 효과",
}


def _para(x, y, value, width, lines, size, color, attrs, anchor="start", weight=None):
    extra = f' font-weight="{weight}"' if weight else ""
    return wrapped_text(x, y, str(value), size=size, max_width=width, max_lines=lines,
                        line_height=size + 7, fill=color, attrs=attrs + extra, anchor=anchor)


def _items(data, key, fields, limit):
    rows = []
    for row in data.get(key) or []:
        if isinstance(row, dict) and all(str(row.get(f, "")).strip() for f in fields[:1]):
            rows.append({f: str(row.get(f, "")).strip() for f in fields})
    return rows[:limit]


# ── 블록 본문. (x, y, w)는 섹션 틀 안쪽 시작점 · 폭. (SVG, 본문 높이) 반환 ────────────


def _journey(data, x, y, w):
    """문제 → 해결 → 효과 세 원을 굵은 화살표로 잇는 대표 도식."""
    nodes = [("문제", "alert", "problem", data.get("problem", ""), PROBLEM, PROBLEM_TINT),
             ("해결", "bulb", "solution", data.get("solution", ""), C["accent_deep"], C["tint"]),
             ("효과", "growth", "outcome", data.get("outcome", ""), C["accent_deep"], C["tint"])]
    nodes = [n for n in nodes if str(n[3]).strip() or n[2] != "outcome"]
    step = w / len(nodes)
    parts, heights = [], []
    if artsheet.has(data, artsheet.HERO):
        # 제목 아래 대표 도식이 이미 문제 → 사용 → 결과를 그림으로 보여 준다. 같은 원을 또 그리지 않고
        # 그림의 세 부분 아래에 글만 붙인다.
        for i, (name, _, field, value, tone, _) in enumerate(nodes):
            cx = x + (i + .5) * step
            parts.append(f'<rect x="{cx - 22}" y="{y}" width="44" height="5" rx="2.5" fill="{tone}"/>')
            parts.append(text(cx, y + 34, name, 19, tone, 800, "middle", 'data-role="label"'))
            svg, lines = _para(cx, y + 62, value or EMPTY_VALUE_TEXT, step - 44, 3, 15, C["body"],
                               f'data-field="{field}" data-role="value"', "middle")
            parts.append(svg)
            heights.append(62 + (lines - 1) * 22)
        return "".join(parts), max(heights) + 14
    for i, (name, icon_name, field, value, tone, tint) in enumerate(nodes):
        cx = x + (i + .5) * step
        custom = artsheet.icon(data, artsheet.key("story", field), cx, y + 66, 124)
        parts.append(custom + f'<circle cx="{cx}" cy="{y + 66}" r="62" fill="none" stroke="{tone}" '
                     f'stroke-opacity=".35" stroke-width="2"/>' if custom else
                     f'<circle cx="{cx}" cy="{y + 66}" r="62" fill="{tint}" stroke="{tone}" '
                     f'stroke-opacity=".35" stroke-width="2" filter="url(#kit-shadow)"/>'
                     + icons.icon(icon_name, cx, y + 66, 60, tone, 2))
        parts.append(text(cx, y + 160, name, 18, C["ink"], 700, "middle", 'data-role="label"'))
        svg, lines = _para(cx, y + 188, value or EMPTY_VALUE_TEXT, step - 40, 3, 15, C["body"],
                           f'data-field="{field}" data-role="value"', "middle")
        parts.append(svg)
        heights.append(188 + (lines - 1) * 22)
        if i < len(nodes) - 1:
            parts.append(_thick_arrow(cx + 76, cx + step - 76, y + 66, C["accent"]))
    return "".join(parts), max(heights) + 16


def _pipeline_captions(data, x, y, w):
    """AI API의 입력 → 처리 → 출력. 제목 아래 대표 도식이 이 흐름을 그리므로 여기서는 그림 아래 글만 붙인다.
    (대표 도식이 없으면 예전 개념도 showcase._hero를 쓴다.)"""
    pipeline = data.get("pipeline") or {}
    stages = [("입력", "input"), ("AI 처리", "process"), ("출력", "output")]
    step = w / len(stages)
    parts, heights = [], []
    for i, (name, field) in enumerate(stages):
        cx = x + (i + .5) * step
        parts.append(f'<rect x="{cx - 22}" y="{y}" width="44" height="5" rx="2.5" fill="{C["accent_deep"]}"/>')
        parts.append(text(cx, y + 34, name, 19, C["accent_deep"], 800, "middle", 'data-role="label"'))
        svg, lines = _para(cx, y + 62, pipeline.get(field, "") or EMPTY_VALUE_TEXT, step - 44, 4, 15, C["body"],
                           f'data-field="pipeline.{field}" data-role="value"', "middle")
        parts.append(svg)
        heights.append(62 + (lines - 1) * 22)
    return "".join(parts), max(heights) + 14


def _thick_arrow(x1, x2, y, color):
    return (f'<path d="M{x1},{y} L{x2 - 12},{y}" stroke="{color}" stroke-width="6" '
            f'stroke-linecap="round"/>'
            f'<path d="M{x2 - 16},{y - 11} L{x2},{y} L{x2 - 16},{y + 11} Z" fill="{color}"/>')


def _split(data, x, y, w):
    """문제 · 해결 두 판(디자인 키트 _business와 같은 재질)."""
    col = (w - GAP) / 2
    parts, heights = [], []
    for i, (value, name, field, icon_name, tone, fill) in enumerate([
        (data.get("problem", ""), "해결할 문제", "problem", "alert", PROBLEM, "#FFFFFF"),
        (data.get("solution", ""), "해결 방식", "solution", "bulb", C["accent_deep"], C["tint"]),
    ]):
        cx = x + i * (col + GAP)
        body, lines = _para(cx + 22, y + 70, value or EMPTY_VALUE_TEXT, col - 44, 3, 15, C["body"],
                            f'data-field="{field}" data-role="value"')
        heights.append(70 + (lines - 1) * 22 + 22)
        parts.append((cx, fill, (artsheet.icon(data, artsheet.key("story", field), cx + 38, y + 34, 48)
                                 or icons.badge(icon_name, cx + 38, y + 34, 20,
                                                PROBLEM_TINT if i == 0 else "#FFFFFF", tone))
                      + text(cx + 68, y + 40, name, 17, C["ink"], 700, attrs='data-role="label"') + body))
    h = max(heights)
    svg = "".join(f'<rect x="{cx}" y="{y}" width="{col}" height="{h}" rx="12" fill="{fill}" '
                  f'stroke="{C["line"]}"/>' + inner for cx, fill, inner in parts)
    return svg, h


def _before_after(data, x, y, w):
    """같은 기준을 줄마다 맞댄 전후 비교. 문제 · 해결 구절도 머리 줄에 남긴다."""
    rows = _items(data, "before_after", ("label", "before", "after"), 4)
    name = str(data.get("item_name", "")).strip()
    label_w = w * .30
    col = (w - label_w) / 2
    parts = [
        f'<rect x="{x + label_w + col}" y="{y - 4}" width="{col}" height="{{H}}" rx="10" fill="{C["tint"]}"/>',
        text(x + label_w + 14, y + 18, "지금", 15, PROBLEM, 700),
        text(x + label_w + col + 14, y + 18, fit(name or "이후", 15, col - 28), 15, C["accent_deep"], 700),
    ]
    cy = y + 30
    if data.get("_ps_elsewhere"):
        return _before_after_rows(rows, parts, x, y, cy, w, label_w, col)
    prob, pl = _para(x + label_w + 14, cy + 20, data.get("problem", "") or EMPTY_VALUE_TEXT, col - 28, 3, 13,
                     C["body"], 'data-field="problem" data-role="value"')
    sol, sl = _para(x + label_w + col + 14, cy + 20, data.get("solution", "") or EMPTY_VALUE_TEXT, col - 28, 3,
                    13, C["body"], 'data-field="solution" data-role="value"')
    parts += [text(x + 4, cy + 20, "요약", 13, C["muted"], 700), prob, sol]
    cy += 20 + (max(pl, sl) - 1) * 20 + 20
    return _before_after_rows(rows, parts, x, y, cy, w, label_w, col)


def _before_after_rows(rows, parts, x, y, cy, w, label_w, col):
    for row in rows:
        parts.append(f'<line x1="{x}" y1="{cy}" x2="{x + w}" y2="{cy}" stroke="{C["line"]}"/>')
        lab, ll = _para(x + 4, cy + 26, row["label"], label_w - 14, 2, 13, C["muted"],
                        'data-field="before_after"')
        bef, bl = _para(x + label_w + 14, cy + 28, row["before"], col - 28, 2, 18, PROBLEM,
                        'data-field="before_after"', weight=800)
        aft, al = _para(x + label_w + col + 14, cy + 28, row["after"], col - 28, 2, 18, C["accent_deep"],
                        'data-field="before_after"', weight=800)
        parts += [lab, bef, aft]
        cy += 28 + (max(ll, bl, al) - 1) * 24 + 16
    h = cy - y + 4
    return "".join(parts).replace("{H}", str(h + 4)), h


def _feature_grid(data, features, x, y, w):
    details = data.get("feature_details") or []
    cols = 2 if w > 600 else 1
    col = (w - (cols - 1) * GAP) / cols
    parts, cy, heights = [], y, []
    for i, feat in enumerate(features):
        c = i % cols
        if c == 0 and i:
            cy += max(heights) + 12
            heights = []
        cx = x + c * (col + GAP)
        name, nl = _para(cx + 58, cy + 22, feat, col - 70, 2, 16, C["ink"],
                         f'data-field="feature" data-feature="{esc(feat)}" data-role="value"', weight=700)
        detail = str(details[i]).strip() if i < len(details) else ""
        dt_y = cy + 22 + nl * 22
        dt, dl = _para(cx + 58, dt_y, detail or EMPTY_VALUE_TEXT, col - 70, 2, 13, C["body"],
                       f'data-field="feature_detail" data-feature="{esc(feat)}" data-role="value"')
        parts += [artsheet.icon(data, artsheet.key("feature", feat), cx + 24, cy + 22, 48)
                  or icons.badge(icons.pick(feat), cx + 24, cy + 20, 20, C["tint"], C["accent_deep"]), name, dt]
        heights.append(22 + nl * 22 + (dl - 1) * 20 + 8)
    cy += max(heights or [0])
    return "".join(parts), cy - y + 4


def _market(data, x, y, w):
    """전체 → 진입 가능 → 초기 목표 시장을 바닥선에 맞춰 포갠 원(계층형)."""
    levels = _items(data, "market_levels", ("label", "value"), 3)
    if not levels:
        return "", 0
    radii = [86, 60, 34] if len(levels) == 3 else [86, 48][:len(levels)]
    base_y = y + 190
    # 반 칸이면 왼쪽, 한 줄 전체면 원과 라벨 묶음을 가운데로.
    cx = x + 100 if w < 600 else x + w / 2 - 170
    shades = [C["tint"], C["line"], C["accent"]]
    parts = []
    for i, r in enumerate(radii):
        parts.append(f'<circle cx="{cx}" cy="{base_y - r}" r="{r}" fill="{shades[i]}" '
                     f'fill-opacity="{.9 if i < 2 else .85}" stroke="{C["accent"]}" stroke-opacity=".4"/>')
    parts.append(f'<line x1="{cx - 96}" y1="{base_y}" x2="{cx + 96}" y2="{base_y}" stroke="{C["line"]}"/>')
    label_x = cx + 120
    tw = min(x + w - label_x, 320)
    for i, (r, lv) in enumerate(zip(radii, levels)):
        ty = base_y - 2 * r + 14 + i * 6
        parts.append(f'<path d="M{cx + r * .6},{base_y - 2 * r + 18} L{label_x - 8},{ty - 5}" '
                     f'stroke="{C["accent"]}" stroke-opacity=".6"/>')
        vs = fit_size(lv["value"], 20, tw, 14)
        parts.append(text(label_x, ty, fit(lv["value"], vs, tw), vs, C["accent_deep"], 800,
                          attrs='data-field="market_levels"'))
        lab, _ = _para(label_x, ty + 20, lv["label"], tw, 2, 13, C["body"], 'data-field="market_levels"')
        parts.append(lab)
    return "".join(parts), 214


def _competition(data, x, y, w):
    comp = data.get("comparison") or {}
    rows = _items(comp, "rows", ("criterion", "others", "ours"), 4)
    if not rows:
        return "", 0
    others = str(comp.get("others", "")).strip() or "기존 방식"
    name = str(data.get("item_name", "")).strip() or "우리 서비스"
    c0 = w * .28
    col = (w - c0) / 2
    parts = [f'<rect x="{x + c0 + col}" y="{y - 4}" width="{col}" height="{{H}}" rx="10" fill="{C["tint"]}"/>',
             text(x + c0 + 14, y + 18, fit(others, 15, col - 28), 15, C["muted"], 700),
             text(x + c0 + col + 14, y + 18, fit(name, 15, col - 28), 15, C["accent_deep"], 700)]
    cy = y + 30
    for row in rows:
        parts.append(f'<line x1="{x}" y1="{cy}" x2="{x + w}" y2="{cy}" stroke="{C["line"]}"/>')
        a, al = _para(x + 4, cy + 24, row["criterion"], c0 - 14, 2, 13, C["muted"], 'data-field="comparison"')
        b, bl = _para(x + c0 + 14, cy + 24, row["others"], col - 28, 2, 14, C["body"], 'data-field="comparison"')
        c, cl = _para(x + c0 + col + 14, cy + 24, row["ours"], col - 28, 2, 14, C["accent_deep"],
                      'data-field="comparison"', weight=700)
        parts += [a, b, c]
        cy += 24 + (max(al, bl, cl) - 1) * 21 + 16
    h = cy - y + 4
    return "".join(parts).replace("{H}", str(h + 4)), h


_PRICE_RE = re.compile(r"\d[\d,.]*\s*(?:만\s*|억\s*|천\s*)?원")


def _revenue_flow(data, x, y, w):
    """돈과 가치의 이동: 내는 쪽 → 우리 서비스, 반대 방향에 받는 가치."""
    flow = data.get("revenue_flow") or {}
    payer = str(flow.get("payer", "")).strip() or "고객"
    payment = str(flow.get("payment", "")).strip()
    value = str(flow.get("value", "")).strip()
    left, right = x + 60, x + w - 60
    cy = y + 60
    parts = [
        artsheet.icon(data, artsheet.key("revenue", "payer"), left, cy, 80) or (
            f'<circle cx="{left}" cy="{cy}" r="38" fill="{C["tint"]}" filter="url(#kit-shadow)"/>'
            + icons.icon(icons.pick(payer, "users"), left, cy, 40, C["accent_deep"], 1.8)),
        artsheet.icon(data, artsheet.key("revenue", "service"), right, cy, 80) or (
            f'<circle cx="{right}" cy="{cy}" r="38" fill="url(#kit-solid)" filter="url(#kit-shadow)"/>'
            + icons.icon(icons.pick(str(data.get("item_summary", "")), "target"), right, cy, 40, "#FFFFFF", 1.8)),
        text(left, cy + 62, fit(payer, 14, 150), 14, C["ink"], 700, "middle", 'data-field="revenue_flow"'),
        text(right, cy + 62, fit(str(data.get("item_name", "")), 14, 150), 14, C["ink"], 700, "middle"),
        arrow(left + 48, cy - 12, right - 48, cy - 12, C["accent_deep"]),
    ]
    span = right - left - 110
    # 반 칸에서는 화살표 사이가 좁다. 한 줄에 안 들어가면 자르지 않고 두 줄로 쓴다.
    mid = (left + right) / 2
    if payment:
        _, n = _para(mid, 0, payment, span, 2, 15, C["accent_deep"], "", "middle", 800)
        svg, _ = _para(mid, cy - 22 - (n - 1) * 22, payment, span, 2, 15, C["accent_deep"],
                       'data-field="revenue_flow"', "middle", 800)
        parts.append(svg)
    if value:
        parts.append(arrow(right - 48, cy + 14, left + 48, cy + 14, C["muted"]))
        svg, _ = _para(mid, cy + 36, value, span, 2, 13, C["body"], 'data-field="revenue_flow"', "middle")
        parts.append(svg)
    body, lines = _para(x + 4, cy + 104, data.get("revenue_unit_price", "") or EMPTY_VALUE_TEXT, w - 8, 2, 14,
                        C["body"], 'data-field="revenue_unit_price" data-role="value"')
    parts.append(f'<line x1="{x}" y1="{cy + 80}" x2="{x + w}" y2="{cy + 80}" stroke="{C["line"]}"/>')
    parts.append(body)
    return "".join(parts), cy + 104 - y + (lines - 1) * 21 + 12


def _revenue_card(data, x, y, w):
    value = str(data.get("revenue_unit_price", ""))
    price = _PRICE_RE.search(value)
    parts = [artsheet.icon(data, artsheet.key("revenue", "service"), x + 30, y + 30, 60)
             or icons.badge("coin", x + 30, y + 30, 26, C["tint"], C["accent_deep"])]
    if price:
        size = fit_size(price.group(), 30, w - 80)
        parts.append(text(x + 72, y + 42, fit(price.group(), size, w - 80), size, C["accent_deep"], 800,
                          attrs='data-field="revenue_unit_price"'))
    body, lines = _para(x + 4, y + 88, value or EMPTY_VALUE_TEXT, w - 8, 3, 15, C["body"],
                        'data-field="revenue_unit_price" data-role="value"')
    parts.append(body)
    return "".join(parts), 88 + (lines - 1) * 22 + 12


def _roadmap_line(data, x, y, w):
    timeline = str(data.get("timeline_baseline", ""))
    stones = parse_milestones(timeline)
    if len(stones) < 2:
        body, lines = _para(x + 44, y + 30, timeline or EMPTY_VALUE_TEXT, w - 50, 3, 15, C["body"],
                            'data-field="timeline_baseline" data-role="value"')
        return icons.icon("calendar", x + 18, y + 24, 28, C["accent_deep"], 1.8) + body, 30 + (lines - 1) * 22 + 14
    n = min(len(stones), 5)
    step = w / n
    # 긴 기간(2026년 12월~2027년 3월)은 두 줄로 감는다. 모든 날짜 줄 수를 맞춰 선을 한 높이에 둔다.
    date_lines = max(len(wrap(d, 13, step - 12, 2)[0]) for d, _ in stones[:n])
    line_y = y + 30 + date_lines * 18
    parts = [f'<path d="M{x + step / 2},{line_y} L{x + w - step / 2 + 18},{line_y}" '
             f'stroke="{C["line"]}" stroke-width="6" stroke-linecap="round"/>',
             f'<path d="M{x + step / 2},{line_y} L{x + w - step / 2},{line_y}" '
             f'stroke="url(#kit-solid)" stroke-width="3"/>']
    heights = []
    for i, (date, event) in enumerate(stones[:n]):
        cx = x + (i + .5) * step
        parts.append(f'<circle cx="{cx}" cy="{line_y}" r="11" fill="#FFFFFF" stroke="{C["accent"]}" '
                     f'stroke-width="4"/>')
        dt, _ = _para(cx, y + 16, date, step - 12, 2, 13, C["accent_deep"],
                      'data-field="timeline_baseline" data-role="value"', "middle", weight=700)
        parts.append(dt)
        ev, el = _para(cx, line_y + 34, event, step - 16, 3, 14, C["ink"],
                       'data-field="timeline_baseline" data-role="value"', "middle")
        parts.append(ev)
        heights.append(34 + (el - 1) * 21)
    return "".join(parts), line_y - y + max(heights) + 14


_NUM_RE = re.compile(r"\d[\d,.]*")


def _number(value: str) -> float | None:
    m = _NUM_RE.search(value.replace(" ", ""))
    try:
        return float(m.group().replace(",", "")) if m else None
    except ValueError:
        return None


def _metric_cards(data, x, y, w):
    metrics = [m for m in data.get("key_metrics") or [] if isinstance(m, dict) and str(m.get("value", "")).strip()][:4]
    if not metrics:
        return "", 0
    cell = w / len(metrics)
    parts, heights = [], []
    for i, m in enumerate(metrics):
        cx = x + (i + .5) * cell
        parts.append(artsheet.icon(data, artsheet.key("metric", m.get("label", "")), cx, y + 32, 64)
                     or icons.badge(icons.pick_metric(str(m["value"]), str(m.get("label", ""))),
                                    cx, y + 30, 26, C["tint"], C["accent_deep"]))
        size = fit_size(str(m["value"]), 28, cell - 16)
        parts.append(text(cx, y + 96, fit(str(m["value"]), size, cell - 16), size, C["accent_deep"], 800, "middle",
                          'data-field="key_metric"'))
        lab, ll = _para(cx, y + 122, m.get("label", ""), cell - 20, 2, 13, C["body"],
                        'data-field="key_metric_label"', "middle")
        parts.append(lab)
        heights.append(122 + (ll - 1) * 20 + 12)
        if i:
            parts.append(f'<line x1="{x + i * cell}" y1="{y + 8}" x2="{x + i * cell}" y2="{y + 140}" '
                         f'stroke="{C["line"]}"/>')
    return "".join(parts), max(heights)


def _metric_bars(data, x, y, w):
    """전후 값이 모두 숫자인 지표는 길이 비율대로 막대 두 개. 나머지는 카드로."""
    metrics = [m for m in data.get("key_metrics") or [] if isinstance(m, dict) and str(m.get("value", "")).strip()][:4]
    paired = [m for m in metrics if _number(str(m.get("before", ""))) and _number(str(m["value"]))]
    if not paired:
        return _metric_cards(data, x, y, w)
    parts, cy = [], y
    bar_x, bar_w = x + 4, w - 120
    for m in paired:
        before, after = _number(str(m["before"])), _number(str(m["value"]))
        top = max(before, after)
        lab, ll = _para(x + 4, cy + 16, m.get("label", ""), w - 8, 1, 14, C["ink"],
                        'data-field="key_metric_label"', weight=700)
        parts.append(lab)
        for j, (val, raw, color) in enumerate(((before, m["before"], C["line"]), (after, m["value"], C["accent_deep"]))):
            by = cy + 30 + j * 26
            parts.append(f'<rect x="{bar_x}" y="{by}" width="{bar_w}" height="14" rx="7" fill="#F1F3F5"/>')
            parts.append(f'<rect x="{bar_x}" y="{by}" width="{max(10, bar_w * val / top):.1f}" height="14" '
                         f'rx="7" fill="{color}"/>')
            parts.append(text(bar_x + bar_w + 12, by + 12, fit(str(raw), fit_size(str(raw), 15, 100, 12), 100),
                              fit_size(str(raw), 15, 100, 12),
                              C["muted"] if j == 0 else C["accent_deep"], 800,
                              attrs='data-field="key_metric"'))
        cy += 94
    rest = [m for m in metrics if m not in paired]
    if rest:
        sub = dict(data, key_metrics=rest)
        svg, h = _metric_cards(sub, x, cy, w)
        parts.append(svg)
        cy += h
    return "".join(parts), cy - y


def _effects(data, x, y, w):
    rows = _items(data, "effects", ("who", "what"), 4)
    if not rows:
        return "", 0
    if w <= 600:
        # 반 칸에 두 열로 놓으면 세 번째가 혼자 아래 줄로 내려간다. 한 줄에 하나씩 세로로 놓는다.
        parts, cy = [], y + 4
        for row in rows:
            parts.append(artsheet.icon(data, artsheet.key("effect", row["who"]), x + 28, cy + 28, 56)
                         or icons.badge(icons.pick(row["who"], "users"), x + 28, cy + 28, 24, C["tint"],
                                        C["accent_deep"]))
            parts.append(text(x + 70, cy + 22, fit(row["who"], 15, w - 80), 15, C["ink"], 700,
                              attrs='data-field="effects"'))
            wt, wl = _para(x + 70, cy + 44, row["what"], w - 80, 2, 13, C["body"], 'data-field="effects"')
            parts.append(wt)
            cy += max(62, 44 + (wl - 1) * 20 + 16)
        return "".join(parts), cy - y
    cols = len(rows)
    col = (w - (cols - 1) * GAP) / cols
    parts, cy, heights = [], y, []
    for i, row in enumerate(rows):
        c = i % cols
        if c == 0 and i:
            cy += max(heights) + 12
            heights = []
        cx = x + c * (col + GAP) + col / 2
        parts.append(artsheet.icon(data, artsheet.key("effect", row["who"]), cx, cy + 32, 64)
                     or icons.badge(icons.pick(row["who"], "users"), cx, cy + 30, 26, C["tint"], C["accent_deep"]))
        parts.append(text(cx, cy + 82, fit(row["who"], 15, col - 16), 15, C["ink"], 700, "middle",
                          'data-field="effects"'))
        wt, wl = _para(cx, cy + 106, row["what"], col - 20, 2, 13, C["body"], 'data-field="effects"', "middle")
        parts.append(wt)
        heights.append(106 + (wl - 1) * 20 + 10)
    cy += max(heights)
    return "".join(parts), cy - y


def _tagline(data, x, y, w):
    line = str(data.get("tagline", "")).strip()
    if not line:
        return "", 0
    style = FRAME_STYLE.get()
    if style == "card":  # 진한 띠 — 흰 카드 지면의 마무리
        box, ink = f'<rect x="{x}" y="{y}" width="{w}" height="72" rx="16" fill="{C["accent_deep"]}"/>', "#FFFFFF"
    elif style == "panel":  # 옅은 판 지면은 같은 옅은 판에 진한 글자
        box, ink = f'<rect x="{x}" y="{y}" width="{w}" height="72" rx="36" fill="{C["tint"]}"/>', C["accent_deep"]
    else:  # 열린 지면은 흰 바탕에 강조색 테두리
        box = (f'<rect x="{x}" y="{y}" width="{w}" height="72" rx="10" fill="#FFFFFF" '
               f'stroke="{C["accent"]}" stroke-width="2"/>')
        ink = C["accent_deep"]
    return (box + icons.icon("target", x + 44, y + 36, 30, ink, 2)
            + text(x + w / 2 + 16, y + 44, fit(line, 20, w - 140), 20, ink, 800, "middle",
                   'data-field="tagline"')), 72


# ── 구성 정리 · 조립 ─────────────────────────────────────────────


# 내용이 반 칸 폭이면 충분한 도식.
_NARROW = {("market", "nested"), ("revenue", "flow"), ("revenue", "card"), ("competition", "table")}


def default_layout(category: str) -> list[dict]:
    if category == "원페이지":
        return [{"block": "hero", "variant": "hub"}, {"block": "problem_solution", "variant": "split"},
                {"block": "features", "variant": "band"}, {"block": "process", "variant": "steps"},
                {"block": "roadmap", "variant": "orbit", "width": "half"},
                {"block": "metrics", "variant": "with_revenue", "width": "half"}]
    return [{"block": "hero", "variant": "hub"}, {"block": "features", "variant": "band"},
            {"block": "process", "variant": "steps"}]


def normalize_layout(category: str, data: dict) -> list[dict]:
    """모델이 고른 구성을 목록 안으로 정리하고, 필수 정보를 담는 블록을 채운다."""
    out, seen = [], set()
    for raw in data.get("layout") or []:
        if not isinstance(raw, dict):
            continue
        block = str(raw.get("block", "")).strip()
        if block not in CATALOG or block in seen:
            continue
        variants = CATALOG[block]
        variant = str(raw.get("variant", "")).strip()
        variant = variant if variant in variants else next(iter(variants))
        width = str(raw.get("width", "")).strip()
        width = width if width in variants[variant] else variants[variant][0]
        title = fit(str(raw.get("title", "")).strip() or DEFAULT_TITLES.get(block, ""), 18, 260)
        out.append({"block": block, "variant": variant, "width": width, "title": title})
        seen.add(block)
    if not out:
        out = [dict(b, width=b.get("width", "full"), title=DEFAULT_TITLES.get(b["block"], ""))
               for b in default_layout(category)]
        seen = {b["block"] for b in out}

    def add(block, variant, width="full", at=None):
        item = {"block": block, "variant": variant, "width": width, "title": DEFAULT_TITLES.get(block, "")}
        out.insert(len(out) if at is None else at, item)
        seen.add(block)

    if "hero" in seen and category == "AI_API":
        pass
    elif category == "AI_API":
        add("hero", "hub", at=0)
    has_problem = "problem_solution" in seen or any(
        b["block"] == "hero" and b["variant"] == "journey" for b in out)
    if category == "원페이지" and not has_problem:
        add("problem_solution", "split", at=1 if out and out[0]["block"] == "hero" else 0)
    if "features" not in seen:
        add("features", "band", at=min(2, len(out)))
    if category == "웹개발" and "process" not in seen and len(data.get("flow_steps") or []) >= 2:
        add("process", "steps")
    if category == "원페이지":
        has_revenue = "revenue" in seen or any(b["block"] == "metrics" and b["variant"] == "with_revenue"
                                               for b in out)
        if not has_revenue:
            add("revenue", "card", "half")
        if "roadmap" not in seen:
            add("roadmap", "line")
    # 여정 대표 도식이 문제 · 해결을 이미 보여 주면 split 판은 같은 글의 반복이다.
    if any((b["block"], b["variant"]) == ("hero", "journey") for b in out):
        out = [b for b in out if (b["block"], b["variant"]) != ("problem_solution", "split")]
    # 원형 궤도는 칸이 작다. 단계 글이 들어가지 않으면 가로 타임라인으로 바꾼다(폭은 짝을 따른다).
    if not _orbital_milestones(parse_milestones(str(data.get("timeline_baseline", "")))):
        for b in out:
            if (b["block"], b["variant"]) == ("roadmap", "orbit"):
                b["variant"] = "line"
    # 가로 타임라인은 단계가 넷 이상이면 반 칸에 들어가지 않는다(한 단계 폭 75px — 할 일 글이 잘린다,
    # 실측: 실제 계획서 두 건). 한 줄 전체를 쓴다. 짝이던 블록은 아래 짝짓기에서 다시 자리를 찾는다.
    if len(parse_milestones(str(data.get("timeline_baseline", "")))) >= 4:
        for b in out:
            if (b["block"], b["variant"]) == ("roadmap", "line"):
                b["width"] = "full"
    # 문제 · 해결 요약을 전후 비교표가 떠맡으면 반 칸으로는 좁다.
    if not any((b["block"], b["variant"]) in (("hero", "journey"), ("problem_solution", "split")) for b in out):
        for b in out:
            if (b["block"], b["variant"]) == ("problem_solution", "before_after"):
                b["width"] = "full"
    # 웹개발 · AI API 지면은 필수 6정보 채점 대상이 아니다. 재료가 빈 블록은 "정보 없음"을
    # 찍지 말고 뺀다.
    if category != "원페이지":
        def filled(key):
            return str(data.get(key, "")).strip() not in ("", "정보 없음")
        need = {("hero", "journey"): lambda: filled("problem") and filled("solution"),
                ("problem_solution", "split"): lambda: filled("problem") and filled("solution"),
                ("revenue", "flow"): lambda: filled("revenue_unit_price") or bool(data.get("revenue_flow")),
                ("revenue", "card"): lambda: filled("revenue_unit_price"),
                ("roadmap", "line"): lambda: filled("timeline_baseline"),
                ("roadmap", "orbit"): lambda: filled("timeline_baseline")}
        out = [b for b in out if need.get((b["block"], b["variant"]), lambda: True)()]
        if category == "AI_API" and not any(b["block"] == "hero" for b in out):
            out.insert(0, {"block": "hero", "variant": "hub", "width": "full", "title": ""})
    # 폭이 좁은 도식(겹친 원 · 수익 흐름 등)이 한 줄 전체를 차지하면 옆이 빈다. 둘이 이어지면 반 칸씩 나란히 둔다.
    for a, b in zip(out, out[1:]):
        if all(bb["width"] == "full" and (bb["block"], bb["variant"]) in _NARROW for bb in (a, b)):
            a["width"] = b["width"] = "half"
    # 좁은 도식이 혼자 남으면(짝이던 블록이 재료가 없어 빠진 경우 등) 반 칸으로 줄일 수 있는 옆 블록과 짝짓는다.
    paired = set()
    i = 0
    while i < len(out) - 1:
        if out[i]["width"] == "half" and out[i + 1]["width"] == "half":
            paired.update((i, i + 1))
            i += 2
        else:
            i += 1
    for i, b in enumerate(out):
        if i in paired or (b["block"], b["variant"]) not in _NARROW:
            continue
        for j in (i + 1, i - 1):
            if not 0 <= j < len(out) or j in paired:
                continue
            other = out[j]
            if other["block"] in ("hero", "tagline", "process") or (other["block"], other["variant"]) == (
                    "features", "band") or "half" not in CATALOG[other["block"]][other["variant"]]:
                continue
            if other["block"] == "roadmap" and len(parse_milestones(str(data.get("timeline_baseline", "")))) >= 4:
                continue
            b["width"] = other["width"] = "half"
            paired.update((i, j))
            break
    # 하단 메시지는 항상 맨 끝.
    out.sort(key=lambda b: b["block"] == "tagline")
    return out


def _render_block(category, data, features, b, x, y, w):
    """(틀 포함 SVG, 전체 높이). 틀 있는 블록은 탭 제목 아래에 본문을 둔다."""
    block, variant = b["block"], b["variant"]
    if block == "hero":
        if variant == "journey":
            return _journey(data, x, y, w)
        if category == "AI_API" and artsheet.has(data, artsheet.HERO):
            return _pipeline_captions(data, x, y, w)
        svg, end = _hero(category, data, features, y)
        return svg, end - y
    if block == "features" and variant == "band":
        svg, end = _features(data, features, y, category)
        return svg, end - y
    if block == "process":
        svg, end = _process(data, category, y)
        return svg, end - y
    if block == "tagline":
        return _tagline(data, x, y, w)
    body_fn = {
        ("problem_solution", "split"): lambda: _split(data, x, y, w),
        ("problem_solution", "before_after"): lambda: _before_after(data, x + 20, y + TOP_PAD, w - 40),
        ("features", "grid"): lambda: _feature_grid(data, features, x + 20, y + TOP_PAD, w - 40),
        ("market", "nested"): lambda: _market(data, x + 20, y + TOP_PAD, w - 40),
        ("competition", "table"): lambda: _competition(data, x + 20, y + TOP_PAD, w - 40),
        ("revenue", "flow"): lambda: _revenue_flow(data, x + 20, y + TOP_PAD, w - 40),
        ("revenue", "card"): lambda: _revenue_card(data, x + 20, y + TOP_PAD, w - 40),
        ("roadmap", "line"): lambda: _roadmap_line(data, x + 20, y + TOP_PAD, w - 40),
        ("metrics", "cards"): lambda: _metric_cards(data, x + 20, y + TOP_PAD, w - 40),
        ("metrics", "bars"): lambda: _metric_bars(data, x + 20, y + TOP_PAD, w - 40),
        ("effects", "cards"): lambda: _effects(data, x + 20, y + TOP_PAD, w - 40),
    }.get((block, variant))
    if body_fn is None:
        return "", 0
    body, h = body_fn()
    if not body:
        return "", 0
    if (block, variant) == ("problem_solution", "split"):
        return body, h
    return ("FRAME", body, TOP_PAD + h + BOTTOM_PAD), None


def _framed(b, x, y, w, body, h):
    return section_frame(x, y, w, h, b["title"], C) + body


def compose(category: str, data: dict, features: list[str]) -> tuple[str, int]:
    """구역 틀 모양(card · panel · open)은 디자인 사양이 고른 것을 조립하는 동안만 쓴다."""
    design = data.get("_design") if isinstance(data.get("_design"), dict) else {}
    frame = design.get("frame") if design.get("frame") in FRAME_STYLES else "card"
    token = FRAME_STYLE.set(frame)
    try:
        return _compose(category, data, features)
    finally:
        FRAME_STYLE.reset(token)


def _compose(category: str, data: dict, features: list[str]) -> tuple[str, int]:
    # 맞춤 아이콘(artsheet)이 있으면 탭 달린 구역 틀로 그린다. 아이콘이 구역마다 들어가는 모양이라
    # 아이콘이 볼거리가 된다. 없으면 아이콘에 기대지 않는 포스터 모양으로 그린다.
    style = data.get("style") or ("framed" if data.get("_art") else "poster")
    if style == "poster":
        body, h = compose_poster(category, data, features)
        return showcase_defs(C) + body, h
    parts = [showcase_defs(C), artsheet.defs(data)]
    parts.append(text(450, 62, fit(str(data.get("item_name", "")), TITLE_SIZE, TITLE_WIDTH),
                      TITLE_SIZE, C["ink"], 800, "middle", 'data-field="item_name" data-role="title"'))
    summary = str(data.get("item_summary", ""))
    dy = 0
    if summary:
        svg, dy = summary_text(summary, 98)
        parts.append(svg)
    target = fit(str(data.get("target_users", "")) or EMPTY_VALUE_TEXT, 15, 520)
    tw = estimate_text_width(target, 15) + 60
    parts.append(f'<rect x="{450 - tw / 2}" y="{110 + dy}" width="{tw}" height="32" rx="16" fill="{C["tint"]}"/>'
                 + icons.icon("users", 450 - tw / 2 + 22, 126 + dy, 18, C["accent_deep"], 1.8)
                 + text(450 + 12, 131 + dy, target, 15, C["ink"], 400, "middle",
                        'data-field="target_users" data-role="value"'))
    y = 168 + dy
    banner = artsheet.slot(data, artsheet.HERO, M, y, INNER, 216, 18)
    if banner:
        parts.append(banner)
        y += 216 + 10
    layout = [dict(b) for b in normalize_layout(category, data)]
    # 포스터의 대표 도식은 문제 · 해결을 이미 크게 보여 준다(AI API 제외). split 판은 반복이다.
    if category != "AI_API" and any(b["block"] == "hero" for b in layout):
        layout = [b for b in layout if (b["block"], b["variant"]) != ("problem_solution", "split")]
    data = dict(data, _ps_elsewhere=any(
        (b["block"], b["variant"]) in (("hero", "journey"), ("problem_solution", "split")) for b in layout))
    i = 0
    while i < len(layout):
        b = layout[i]
        pair = (b["width"] == "half" and i + 1 < len(layout) and layout[i + 1]["width"] == "half")
        if pair:
            left, right = b, layout[i + 1]
            rendered = []
            for bb, bx in ((left, M), (right, M + HALF + GAP)):
                if (bb["block"], bb["variant"]) == ("roadmap", "orbit"):
                    rendered.append(("ORBIT", bb, bx, 330))
                elif (bb["block"], bb["variant"]) == ("metrics", "with_revenue"):
                    rendered.append(("MREV", bb, bx, 330))
                else:
                    res = _render_block(category, data, features, bb, bx, y + 14, HALF)
                    if isinstance(res[0], tuple):
                        _, body, h = res[0]
                        rendered.append(("BODY", bb, bx, h, body))
                    else:
                        rendered.append(("RAW", bb, bx, res[1], res[0]))
            h = max(r[3] for r in rendered)
            # 짝의 높이가 크게 다르면 짧은 쪽 아래가 비어 보인다. 반 칸 전용이 아니면 한 줄씩 편다.
            # 폭이 좁은 도식은 펴면 옆이 더 크게 비므로 짝을 유지한다.
            fixed = any(r[0] in ("ORBIT", "MREV") or (r[1]["block"], r[1]["variant"]) in _NARROW
                        for r in rendered)
            if not fixed and min(r[3] for r in rendered) < h * .6:
                left["width"] = right["width"] = "full"
                continue
            for r in rendered:
                kind, bb, bx = r[0], r[1], r[2]
                if kind == "ORBIT":
                    parts.append(_roadmap(data, bx, y + 14, HALF, h))
                elif kind == "MREV":
                    parts.append(_metrics_revenue(data, bx, y + 14, HALF, h))
                elif kind == "BODY":
                    parts.append(_framed(bb, bx, y + 14, HALF, r[4], h))
                elif r[4]:
                    parts.append(r[4])
            y += 14 + h + 14
            i += 2
            continue
        width = INNER
        if (b["block"], b["variant"]) in (("roadmap", "orbit"), ("metrics", "with_revenue")):
            fn = _roadmap if b["block"] == "roadmap" else _metrics_revenue
            parts.append(fn(data, M, y + 14, width, 330))
            y += 14 + 330 + 14
            i += 1
            continue
        res = _render_block(category, data, features, b, M, y + 14, width)
        if isinstance(res[0], tuple):
            _, body, h = res[0]
            parts.append(_framed(b, M, y + 14, width, body, h))
            y += 14 + h + 14
        elif res[0]:
            parts.append(res[0])
            y += 14 + res[1] + 14
        i += 1
    parts.append(f'<line x1="{M}" y1="{y + 16}" x2="{PAGE_WIDTH - M}" y2="{y + 16}" stroke="{C["line"]}"/>')
    parts.append(text(M, y + 39, "S-BRAIN", 12, C["muted"], 700))
    return "\n".join(parts), int(y + 57)


_TEXT_RE = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.S)


def truncated_fields(category: str, data: dict) -> list[str]:
    """실제로 조립해 말줄임(…)으로 잘린 값의 표식 목록. 자체 검사가 재수행 사유로 쓴다."""
    svg, _ = compose(category, data, [str(f) for f in data.get("features") or []])
    seen = []
    for attrs, inner in _TEXT_RE.findall(svg):
        field = re.search(r'data-field="([^"]+)"', attrs)
        shown = re.sub(r"<[^>]+>", "", inner).strip()
        if field and shown.endswith("…") and field.group(1) not in seen:
            seen.append(field.group(1))
    return seen


# ── 포스터 스타일 조립(기본) ────────────────────────────────────────


def _poster_body(category, data, features, b, x, y, w):
    from engineering_agent.infographic import poster as P
    key = (b["block"], b["variant"])
    if b["block"] == "hero":
        return P.journey(data, x, y, w) if b["variant"] == "journey" else P.statement(category, data, x, y, w)
    table = {
        ("problem_solution", "split"): lambda: P.split(data, x, y, w),
        ("problem_solution", "before_after"): lambda: P.before_after(data, x, y, w),
        ("features", "band"): lambda: P.features_list(data, features, x, y, w),
        ("features", "grid"): lambda: P.features_list(data, features, x, y, w),
        ("process", "steps"): lambda: P.process(data, category, x, y, w),
        ("market", "nested"): lambda: P.market(data, x, y, w),
        ("competition", "table"): lambda: P.competition(data, x, y, w),
        ("revenue", "flow"): lambda: P.revenue(data, x, y, w, "flow"),
        ("revenue", "card"): lambda: P.revenue(data, x, y, w, "card"),
        ("roadmap", "line"): lambda: P.roadmap(data, x, y, w),
        ("roadmap", "orbit"): lambda: P.roadmap(data, x, y, w),
        ("metrics", "cards"): lambda: P.metrics(data, x, y, w),
        ("metrics", "bars"): lambda: P.metrics(data, x, y, w, bars=True),
        ("metrics", "with_revenue"): lambda: P.metrics(data, x, y, w),
        ("effects", "cards"): lambda: P.effects(data, x, y, w),
        ("tagline", "band"): lambda: P.tagline(data, x, y, w),
    }
    fn = table.get(key)
    return fn() if fn else ("", 0)


def compose_poster(category: str, data: dict, features: list[str]) -> tuple[str, int]:
    from engineering_agent.infographic import poster as P
    head, y, lead_shown = P.header(category, data)
    parts = [head]
    layout = [dict(b) for b in normalize_layout(category, data)]
    # 지표+수익 한 칸 변형은 포스터에서 지표와 수익 두 블록으로 나눠 그린다.
    for i, b in enumerate(list(layout)):
        if (b["block"], b["variant"]) == ("metrics", "with_revenue"):
            layout.insert(i + 1, {"block": "revenue", "variant": "card", "width": b["width"], "title": "수익 구조"})
            b["variant"] = "cards"
            break
    data = dict(data, _ps_elsewhere=any(
        (b["block"], b["variant"]) in (("hero", "journey"), ("problem_solution", "split")) or
        (b["block"] == "hero" and category != "AI_API") for b in layout),
        _lead_metric_shown=lead_shown)
    x0, full, gap = 40, 820, 40
    half = (full - gap) / 2
    y += 20
    i = 0
    while i < len(layout):
        b = layout[i]
        framed = b["block"] not in ("hero", "tagline")
        pair = b["width"] == "half" and i + 1 < len(layout) and layout[i + 1]["width"] == "half"
        # 단계가 셋 이상인 일정은 반 칸에서 비좁다.
        many = len(parse_milestones(str(data.get("timeline_baseline", "")))) >= 3
        if pair and many and any(bb["block"] == "roadmap" for bb in (b, layout[i + 1])):
            b["width"] = layout[i + 1]["width"] = "full"
            continue
        if pair:
            bodies = []
            for bb, bx in ((b, x0), (layout[i + 1], x0 + half + gap)):
                svg, h = _poster_body(category, data, features, bb, bx, y + 58, half)
                bodies.append((bb, bx, svg, h))
            hs = [h for *_, h in bodies]
            if min(hs) < max(hs) * .55 or not all(svg for _, _, svg, _ in bodies):
                b["width"] = layout[i + 1]["width"] = "full"
                continue
            for bb, bx, svg, h in bodies:
                parts.append(P.heading(bx, y + 28, half, bb["title"]) + svg)
            y += 58 + max(hs) + 36
            i += 2
            continue
        top = y + 58 if framed else y + 10
        svg, h = _poster_body(category, data, features, b, x0, top, full)
        if svg:
            if framed:
                parts.append(P.heading(x0, y + 28, full, b["title"]))
            parts.append(svg)
            y = top + h + 36
        i += 1
    return "\n".join(parts), int(y + 10)
