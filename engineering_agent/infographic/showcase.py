"""Reference-led composition: hero illustration, feature band, roadmap and metrics.

All factual labels come from input. Decorative geometry never creates fake data.
The business model / category controls which illustration and diagram are shown.
"""
from __future__ import annotations

import math
import re

from engineering_agent.infographic import artsheet, icons
from engineering_agent.infographic.design_kit import arrow, section_frame, showcase_defs
from engineering_agent.infographic.layout import (
    fit, fit_size, wrap, parse_milestones, PAGE_WIDTH, TITLE_SIZE, TITLE_WIDTH,
)
from engineering_agent.infographic.svg_parts import esc, wrapped_text, EMPTY_VALUE_TEXT
from engineering_agent.infographic.themes import BASE, THEMES

C = THEMES[BASE]
M = 28
INNER = PAGE_WIDTH - 2 * M


def text(x, y, value, size=15, color=None, weight=400, anchor="start", attrs=""):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'text-anchor="{anchor}" fill="{color or C["body"]}" {attrs}>{esc(value)}</text>')


SUMMARY_LINES = 2
SUMMARY_LINE_HEIGHT = 22


def summary_text(summary: str, y: float) -> tuple[str, float]:
    """머리말의 한 줄 소개. (SVG, 한 줄일 때보다 늘어난 높이).

    한 줄 소개는 조율이 준 입력값이라 재수행으로 짧아지지 않는다. 한 줄에 다 들어가지
    않으면 두 줄로 감고, 아래 내용은 늘어난 높이만큼 내린다."""
    svg, n = wrapped_text(450, y, summary, size=16, max_width=780, max_lines=SUMMARY_LINES,
                          line_height=SUMMARY_LINE_HEIGHT, fill=C["ink"],
                          attrs='font-weight="600" data-field="item_summary"', anchor="middle")
    return svg, (n - 1) * SUMMARY_LINE_HEIGHT


def paragraph(x, y, value, width, lines=3, size=15, field="", feature="", anchor="start"):
    attrs = f'data-field="{field}" data-role="value"'
    if feature:
        attrs += f' data-feature="{esc(feature)}"'
    return wrapped_text(x, y, str(value), size=size, max_width=width, max_lines=lines,
                        line_height=size + 7, fill=C["body"], attrs=attrs, anchor=anchor)[0]


def _cloud(cx, cy):
    """Data intake illustration. The network has no quantitative meaning."""
    x, y = cx - 75, cy - 44
    paths = (
        f'<path d="M{x + 26},{y + 87} C{x - 9},{y + 87} {x - 12},{y + 33} {x + 25},{y + 28} '
        f'C{x + 27},{y + 6} {x + 48},{y + 1} {x + 65},{y + 16} '
        f'C{x + 87},{y - 24} {x + 138},{y - 4} {x + 138},{y + 31} '
        f'C{x + 176},{y + 36} {x + 173},{y + 87} {x + 139},{y + 87} Z" '
        f'fill="url(#kit-wash)" stroke="{C["accent"]}" stroke-width="3" filter="url(#kit-shadow)"/>'
    )
    pts = [(cx - 42, cy + 5), (cx - 23, cy - 14), (cx + 5, cy + 2),
           (cx + 33, cy - 22), (cx + 42, cy + 20), (cx - 4, cy + 31)]
    for a, b in [(0, 1), (0, 2), (0, 5), (1, 2), (1, 3), (2, 3), (2, 4), (2, 5), (3, 4), (4, 5)]:
        paths += f'<path d="M{pts[a][0]},{pts[a][1]} L{pts[b][0]},{pts[b][1]}" stroke="{C["accent"]}" stroke-opacity=".35"/>'
    for px, py in pts:
        paths += f'<circle cx="{px}" cy="{py}" r="3" fill="#FFFFFF" stroke="{C["accent"]}"/>'
    return paths


def _hub(cx, cy, name):
    r = 52
    points = " ".join(f"{cx + r * math.cos(math.radians(a))},{cy + r * math.sin(math.radians(a))}"
                      for a in (-90, -30, 30, 90, 150, 210))
    return (f'<polygon points="{points}" fill="url(#kit-wash)" stroke="{C["accent"]}" '
            f'filter="url(#kit-shadow)"/>' + icons.icon(name, cx, cy, 56, C["accent_deep"], 2))


def _hero(category, data, features, y):
    """Large domain-relevant visual plus a truthful, illustrative result surface."""
    cy = y + 78
    pipeline = data.get("pipeline") or {}
    steps = data.get("solution_steps") or data.get("flow_steps") or []
    is_ai = category == "AI_API" or any(w in str(data.get("item_summary", "")) + str(data.get("item_name", ""))
                                       for w in ("AI", "인공지능", "데이터 분석"))
    source = pipeline.get("input", "") if category == "AI_API" else (steps[0] if steps else data.get("target_users", ""))
    process = pipeline.get("process", "") if category == "AI_API" else data.get("solution", "")
    source_field = "pipeline.input" if category == "AI_API" else ("hero_source" if steps else "target_users")
    process_field = "pipeline.process" if category == "AI_API" else "hero_process"
    if not process:
        process = steps[1] if len(steps) > 1 else data.get("item_summary", "")
        if len(steps) <= 1:
            process_field = "item_summary"
    parts = []
    if is_ai:
        parts.append(_cloud(112, cy))
    else:
        name = icons.pick(str(source), "users")
        parts.append(f'<circle cx="112" cy="{cy}" r="64" fill="url(#kit-wash)" '
                     f'stroke="{C["line"]}" filter="url(#kit-shadow)"/>')
        parts.append(icons.icon(name, 112, cy, 88, C["accent_deep"], 2))
    # Three incoming strands emphasize aggregation, rather than unrelated card boxes.
    for dy in (-16, 0, 16):
        parts.append(f'<path d="M186,{cy + dy} C218,{cy + dy} 228,{cy} 248,{cy}" '
                     f'fill="none" stroke="{C["accent"]}" stroke-width="1.2" stroke-dasharray="3 3"/>')
    parts.append(_hub(299, cy, "funnel" if is_ai else icons.pick(str(process), "target")))
    parts.append(arrow(351, cy, 401, cy, C["accent"]))
    parts.append(text(112, cy + 94, "입력" if category == "AI_API" else "고객 접점", 17,
                      C["ink"], 700, "middle", 'data-role="label"'))
    parts.append(paragraph(112, cy + 119, source, 165, 6, 13,
                           source_field, anchor="middle"))
    parts.append(text(299, cy + 94, "AI 분석" if is_ai else "서비스 운영", 17,
                      C["ink"], 700, "middle", 'data-role="label"'))
    parts.append(paragraph(299, cy + 119, process, 176, 6, 13,
                           process_field, anchor="middle"))
    x, w = 416, 456
    parts.append(f'<rect x="{x}" y="{y + 6}" width="{w}" height="228" rx="14" '
                 f'fill="#FFFFFF" stroke="{C["line"]}" filter="url(#kit-shadow)"/>')
    parts.append(text(x + 18, y + 34, "결과 화면 구성", 17, C["ink"], 700, attrs='data-role="label"'))
    parts.append(text(x + w - 18, y + 34, "기능 개념도", 12, C["muted"], anchor="end"))
    parts.append(f'<line x1="{x + 16}" y1="{y + 48}" x2="{x + w - 16}" y2="{y + 48}" stroke="{C["line"]}"/>')
    output = pipeline.get("output", "") if category == "AI_API" else data.get("item_summary", "")
    if category == "AI_API":
        if output:
            parts.append(paragraph(x + 20, y + 76, output, w - 40, 2, 14, "pipeline.output"))
    elif output:
        # 한 줄 소개(입력값)를 여기 한 번 더 싣는다. 두 줄에 안 들어가면 글자를 줄이고, 그래도 넘치면
        # 싣지 않는다 — 머리말에 이미 전부 있고, 잘린 채로 실으면 원페이지 잘림 감점만 생긴다.
        size = next((s for s in (14, 12) if not wrap(str(output), s, w - 40, 2)[1]), None)
        if size:
            parts.append(paragraph(x + 20, y + 76, output, w - 40, 2, size, "item_summary"))
    metrics = [m for m in data.get("key_metrics") or [] if isinstance(m, dict) and m.get("value")][:3]
    details = data.get("feature_details") or []
    if metrics:
        cell = (w - 36) / len(metrics)
        for i, metric in enumerate(metrics):
            mx = x + 18 + i * cell
            parts.append(f'<rect x="{mx}" y="{y + 109}" width="{cell - 8}" height="107" rx="6" '
                         f'fill="#FFFFFF" stroke="{C["line"]}"/>')
            parts.append(wrapped_text(mx + 10, y + 128, str(metric.get("label", "")), size=12,
                                      max_width=cell - 28, max_lines=2, line_height=15,
                                      fill=C["muted"], attrs='data-field="key_metric_label"')[0])
            size = fit_size(str(metric["value"]), 27, cell - 28)
            parts.append(text(mx + 10, y + 175, fit(str(metric["value"]), size, cell - 28),
                              size, C["accent_deep"], 800, attrs='data-field="key_metric"'))
            parts.append(icons.icon(icons.pick_metric(str(metric["value"]), str(metric.get("label", ""))),
                                    mx + 20, y + 199, 19, C["accent_deep"], 1.3))
    for i, feat in enumerate([] if metrics else features[:3]):
        ry = y + 113 + i * 35
        parts.append(icons.icon(icons.pick(feat), x + 30, ry + 1, 20, C["accent_deep"], 1.5))
        parts.append(text(x + 50, ry + 5, fit(feat, 14, 140), 14, C["ink"], 700))
        detail = str(details[i]) if i < len(details) else ""
        if detail:
            parts.append(text(x + 200, ry + 5, fit(detail, 12, w - 220), 12, C["muted"]))
        parts.append(f'<line x1="{x + 50}" y1="{ry + 17}" x2="{x + w - 20}" y2="{ry + 17}" '
                     f'stroke="{C["line"]}"/>')
    lines = max(len(wrap(str(source) or EMPTY_VALUE_TEXT, 13, 165, 6)[0]),
                len(wrap(str(process) or EMPTY_VALUE_TEXT, 13, 176, 6)[0]))
    return "".join(parts), y + max(264, 197 + (lines - 1) * 20 + 24)


def _features(data, features, y, category):
    """A continuous icon-led band, with adaptive rows and intact source details."""
    n = len(features)
    cols = _feature_columns(features, data.get("feature_details") or [])
    width = (INNER - 24) / cols
    details = data.get("feature_details") or []
    rows, cursor = [], y + 32
    for start in range(0, n, cols):
        row_parts, used = [], []
        count = min(cols, n - start)
        left = M + 12 + ((cols - count) * width / 2)
        for j in range(count):
            i = start + j
            cx = left + (j + .5) * width
            feat = features[i]
            row_parts.append(artsheet.icon(data, artsheet.key("feature", feat), cx, cursor + 32, 68)
                             or icons.icon(icons.pick(feat), cx, cursor + 35, 46, C["accent_deep"], 1.7))
            name, name_lines = wrapped_text(cx, cursor + 83, feat, size=16, max_width=width - 26,
                                           max_lines=2, line_height=22, fill=C["ink"],
                                           attrs=f'font-weight="700" data-field="feature" data-feature="{esc(feat)}" data-role="value"',
                                           anchor="middle")
            detail = str(details[i]).strip() if i < len(details) else ""
            row_parts.append(name)
            dt_y = cursor + 83 + name_lines * 22
            dt_lines = 0
            if detail or category == "원페이지":
                dt, dt_lines = wrapped_text(cx, dt_y, detail, size=13, max_width=width - 26,
                                            max_lines=4, line_height=20, fill=C["body"],
                                            attrs=f'data-field="feature_detail" data-feature="{esc(feat)}" data-role="value"',
                                            anchor="middle")
                row_parts.append(dt)
            used.append(83 + name_lines * 22 + max(0, dt_lines - 1) * 20 + 22)
            if j < count - 1:
                rx = left + (j + 1) * width
                row_parts.append(f'<line x1="{rx}" y1="{cursor + 10}" x2="{rx}" y2="{{bottom}}" stroke="{C["line"]}"/>')
        h = max(used)
        rows.extend(part.replace("{bottom}", str(cursor + h - 14)) for part in row_parts)
        cursor += h + 10
    if not features:
        rows.append(text(M + 24, cursor + 38, "등록된 기능이 없습니다", 15, C["muted"]))
        cursor += 80
    h = cursor - y + 4
    return section_frame(M, y, INNER, h, "핵심 기능", C) + "".join(rows), y + h


def _feature_columns(features, details):
    """A single panoramic band when the text fits; otherwise expand into spacious rows."""
    n = len(features)
    if 5 <= n <= 7:
        width = (INNER - 24) / n - 26
        if all(not wrap(str(f), 16, width, 2)[1] for f in features) and all(
                not wrap(str(d), 13, width, 4)[1] for d in details):
            return n
    return min(max(n, 1), 4)


def _business(data, y):
    """Six required facts remain visible even when the optional hero has no inputs."""
    problem, solution = str(data.get("problem", "")), str(data.get("solution", ""))
    w = (INNER - 14) / 2
    max_lines = max(len(wrap(v or EMPTY_VALUE_TEXT, 15, w - 42, 3)[0]) for v in (problem, solution))
    h = 55 + max_lines * 22 + 14
    parts = []
    for i, (value, name, field, icon_name) in enumerate([
        (problem, "해결할 문제", "problem", "alert"), (solution, "해결 방식", "solution", "bulb")
    ]):
        x = M + i * (w + 14)
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
                     f'fill="{C["tint"] if i else "#FFFFFF"}" stroke="{C["line"]}"/>')
        parts.append(icons.icon(icon_name, x + 29, y + 27, 24, C["accent_deep"], 1.6))
        parts.append(text(x + 50, y + 33, name, 17, C["ink"], 700, attrs='data-role="label"'))
        parts.append(paragraph(x + 21, y + 66, value, w - 42, 3, 15, field))
    return "".join(parts), y + h


# 원형 일정의 원 크기. 원이 작으면(반지름 51) 실제 일정 글자("2026년 12월~2027년 3월")가 들어가지
# 않아 늘 직선 타임라인으로 바뀌었다. 날짜 두 줄 + 내용 두 줄이 들어가게 키운다.
_ORBIT_NODE, _ORBIT_RADIUS, _ORBIT_TEXT = 62, 94, 104


def _roadmap(data, x, y, w, h):
    timeline = str(data.get("timeline_baseline", ""))
    milestones = parse_milestones(timeline)
    parts = [section_frame(x, y, w, h, "사업 추진 단계", C)]
    if not _orbital_milestones(milestones):
        parts += [icons.icon("calendar", x + w / 2, y + 82, 58, C["accent_deep"], 2),
                  paragraph(x + w / 2, y + 146, timeline, w - 50, 3, 15,
                            "timeline_baseline", anchor="middle")]
        return "".join(parts)
    # Open orbital path shows a chronological progression, not an invented cycle.
    n = min(len(milestones), 4)
    cx, cy = x + w / 2, y + 167
    radius = min(_ORBIT_RADIUS, w / 2 - _ORBIT_NODE - 10)
    node_r = _ORBIT_NODE
    pts = [(cx + radius * math.cos(math.radians(-90 + i * 360 / n)),
            cy + radius * math.sin(math.radians(-90 + i * 360 / n))) for i in range(n)]
    for i in range(n - 1):
        a1, a2 = math.radians(-90 + i * 360 / n), math.radians(-90 + (i + 1) * 360 / n)
        offset = math.asin(min(.95, (node_r + 5) / radius))
        a1, a2 = a1 + offset, a2 - offset
        if a2 > a1:
            p1 = (cx + radius * math.cos(a1), cy + radius * math.sin(a1))
            p2 = (cx + radius * math.cos(a2), cy + radius * math.sin(a2))
            parts.append(f'<path d="M{p1[0]},{p1[1]} A{radius},{radius} 0 0 1 {p2[0]},{p2[1]}" '
                         f'stroke="{C["accent"]}" stroke-width="5" fill="none" stroke-opacity=".45"/>')
            parts.append(arrow(p2[0] - 8 * (-math.sin(a2)), p2[1] - 8 * math.cos(a2),
                               p2[0], p2[1], C["accent"]))
    # A white backing keeps the center icon distinct from the orbit.
    parts.append(artsheet.icon(data, artsheet.key("timeline"), cx, cy, 72)
                 or icons.icon("flag", cx, cy, 40, C["accent_deep"], 1.7))
    for (px, py), (date, event) in zip(pts, milestones):
        parts.append(f'<circle cx="{px}" cy="{py}" r="{node_r}" fill="url(#kit-wash)" '
                     f'stroke="{C["accent"]}" stroke-width="1.4"/>')
        date_svg, dn = wrapped_text(px, py - 12 - (len(wrap(date, 12, _ORBIT_TEXT, 2)[0]) - 1) * 15, date,
                                    size=12, max_width=_ORBIT_TEXT, max_lines=2, line_height=15,
                                    fill=C["accent_deep"], anchor="middle",
                                    attrs='font-weight="700" data-field="timeline_baseline" data-role="value"')
        parts.append(date_svg)
        parts.append(wrapped_text(px, py + 8, event, size=12, max_width=_ORBIT_TEXT, max_lines=2,
                                  line_height=16, fill=C["body"], anchor="middle",
                                  attrs='data-field="timeline_baseline" data-role="value"')[0])
    return "".join(parts)


def _orbital_milestones(milestones):
    """Use the orbit only if every date and action fits; otherwise retain full prose."""
    return (2 <= len(milestones) <= 4
            and all(not wrap(date, 12, _ORBIT_TEXT, 2)[1] and not wrap(event, 12, _ORBIT_TEXT, 2)[1]
                    for date, event in milestones))


def _metrics_revenue(data, x, y, w, h):
    metrics = [m for m in data.get("key_metrics") or [] if isinstance(m, dict) and m.get("value")][:3]
    parts = [section_frame(x, y, w, h, "사업 지표 · 수익 모델", C)]
    if metrics:
        cell = (w - 30) / len(metrics)
        for i, metric in enumerate(metrics):
            cx = x + 15 + (i + .5) * cell
            parts.append(artsheet.icon(data, artsheet.key("metric", metric.get("label", "")), cx, y + 60, 54)
                         or icons.icon(icons.pick_metric(str(metric["value"]), str(metric.get("label", ""))),
                                       cx, y + 61, 38, C["accent_deep"], 1.6))
            size = fit_size(str(metric["value"]), 26, cell - 14)
            parts.append(text(cx, y + 108, fit(str(metric["value"]), size, cell - 14), size,
                              C["accent_deep"], 800, "middle", 'data-field="key_metric"'))
            parts.append(paragraph(cx, y + 134, metric.get("label", ""), cell - 14, 2, 13,
                                   "key_metric_label", anchor="middle"))
            if i:
                parts.append(f'<line x1="{x + 15 + i * cell}" y1="{y + 42}" '
                             f'x2="{x + 15 + i * cell}" y2="{y + 164}" stroke="{C["line"]}"/>')
        top = y + 190
    else:
        top = y + 70
    parts.append(text(x + 22, top, "수익 모델", 17, C["ink"], 700, attrs='data-role="label"'))
    value = str(data.get("revenue_unit_price", ""))
    price = re.search(r"\d[\d,.]*\s*(?:만\s*|억\s*|천\s*)?원", value)
    if price:
        parts.append(text(x + 22, top + 38, fit(price.group(), 28, w - 44), 28,
                          C["accent_deep"], 800, attrs='data-field="revenue_unit_price"'))
        top += 45
    parts.append(paragraph(x + 22, top + 26, value, w - 44, 2, 15, "revenue_unit_price"))
    return "".join(parts)


def _process(data, category, y):
    steps = data.get("solution_steps") if category == "원페이지" else data.get("flow_steps")
    steps = [str(step) for step in steps or []]
    if len(steps) < 2:
        return "", y
    n = min(len(steps), 5)
    width = (INNER - 32) / n
    h = 150 + ((len(steps) - 1) // n) * 118
    parts = [section_frame(M, y, INNER, h, "서비스 제공 과정" if category == "원페이지" else "사용자 흐름", C)]
    for i, step in enumerate(steps):
        row, col = divmod(i, n)
        count = min(n, len(steps) - row * n)
        left = M + 16 + (n - count) * width / 2
        cx = left + (col + .5) * width
        ry = y + row * 118
        parts.append(artsheet.icon(data, artsheet.key("step", step), cx, ry + 62, 64)
                     or icons.badge(icons.pick(step), cx, ry + 62, 26, C["tint"], C["accent_deep"]))
        field = "solution_steps" if category == "원페이지" else "flow_steps"
        parts.append(paragraph(cx, ry + 116, step, width - 28, 2, 15, field, anchor="middle"))
        if col < count - 1:
            parts.append(arrow(cx + 34, ry + 62, cx + width - 34, ry + 62, C["accent"]))
    return "".join(parts), y + h


def build_showcase(category: str, data: dict, features: list[str]) -> tuple[str, int]:
    parts = [showcase_defs(C)]
    parts.append(text(450, 62, fit(str(data.get("item_name", "")), TITLE_SIZE, TITLE_WIDTH),
                      TITLE_SIZE, C["ink"], 800, "middle", 'data-field="item_name" data-role="title"'))
    summary = str(data.get("item_summary", ""))
    dy = 0
    if summary:
        svg, dy = summary_text(summary, 98)
        parts.append(svg)
    parts.append(text(450, 130 + dy, fit(str(data.get("target_users", "")) or EMPTY_VALUE_TEXT, 15, 520),
                      15, C["muted"], 400, "middle", 'data-field="target_users" data-role="value"'))
    hero, y = _hero(category, data, features, 152 + dy)
    parts.append(hero)
    if category == "원페이지":
        business, y = _business(data, y + 8)
        parts.append(business)
    band, y = _features(data, features, y + 28, category)
    parts.append(band)
    process, y = _process(data, category, y + 30)
    parts.append(process)
    if category == "원페이지":
        y += 30
        w = (INNER - 14) / 2
        parts.append(_roadmap(data, M, y, w, 330))
        parts.append(_metrics_revenue(data, M + w + 14, y, w, 330))
        y += 330
    parts.append(f'<line x1="{M}" y1="{y + 24}" x2="{PAGE_WIDTH - M}" y2="{y + 24}" stroke="{C["line"]}"/>')
    parts.append(text(M, y + 47, "S-BRAIN", 12, C["muted"], 700))
    return "\n".join(parts), int(y + 65)


def showcase_slots(category: str, data: dict) -> list[tuple]:
    """Use actual composition widths to report source truncation before rendering."""
    slots = [("item_name", str(data.get("item_name", "")), TITLE_SIZE, TITLE_WIDTH, 1),
             ("item_summary", str(data.get("item_summary", "")), 16, 780, SUMMARY_LINES),
             ("target_users", str(data.get("target_users", "")), 15, 520, 1)]
    features = [str(f) for f in data.get("features") or []]
    cols = _feature_columns(features, data.get("feature_details") or [])
    width = (INNER - 24) / cols - 26
    slots += [("feature", f, 16, width, 2) for f in features]
    slots += [("feature_detail", str(d), 13, width, 4) for d in data.get("feature_details") or []]
    if category == "원페이지":
        w = (INNER - 14) / 2
        slots += [(field, str(data.get(field, "")), 15, w - 42, 3) for field in ("problem", "solution")]
        slots.append(("revenue_unit_price", str(data.get("revenue_unit_price", "")), 15, w - 44, 2))
        timeline = str(data.get("timeline_baseline", ""))
        milestones = parse_milestones(timeline)
        if _orbital_milestones(milestones):
            slots += [("timeline_baseline", date, 12, 94, 1) for date, _ in milestones]
            slots += [("timeline_baseline", event, 13, 86, 2) for _, event in milestones]
        else:
            slots.append(("timeline_baseline", timeline, 15, w - 50, 3))
        metrics = [m for m in data.get("key_metrics") or [] if isinstance(m, dict) and m.get("value")][:3]
        cell = (w - 30) / max(len(metrics), 1)
        slots += [("key_metric", str(m["value"]), 26, cell - 14, 1) for m in metrics]
        slots += [("key_metric_label", str(m.get("label", "")), 13, cell - 14, 2) for m in metrics]
    if category == "AI_API":
        pipeline = data.get("pipeline") or {}
        slots += [("pipeline.input", str(pipeline.get("input", "")), 13, 165, 6),
                  ("pipeline.process", str(pipeline.get("process", "")), 13, 176, 6),
                  ("pipeline.output", str(pipeline.get("output", "")), 14, 416, 2)]
    else:
        steps = data.get("solution_steps") if category == "원페이지" else data.get("flow_steps")
        steps = [str(step) for step in steps or []]
        if len(steps) >= 2:
            width = (INNER - 32) / min(len(steps), 5) - 28
            slots += [("solution_steps" if category == "원페이지" else "flow_steps", step, 15, width, 2)
                      for step in steps]
    return slots
