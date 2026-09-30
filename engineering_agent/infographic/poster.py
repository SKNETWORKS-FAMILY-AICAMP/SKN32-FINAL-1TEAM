"""포스터 스타일 블록. composer.compose()가 style="poster"일 때 쓴다.

카드 · 탭 · 옅은 원 아이콘을 반복하지 않는다. 구역은 굵은 색 막대와 얇은 선으로 나누고,
숫자는 크게, 설명 속 숫자는 굵은 색으로 강조한다. 글자는 모두 추출값이고 장식에는
숫자를 쓰지 않는다. data-field · data-role 표식은 composer와 같다.
"""
from __future__ import annotations

import re

from engineering_agent.infographic import icons, illustrations
from engineering_agent.infographic.layout import (
    estimate_text_width, fit, fit_size, parse_milestones, wrap,
)
from engineering_agent.infographic.showcase import C
from engineering_agent.infographic.svg_parts import EMPTY_VALUE_TEXT, esc

INK = "#111827"
BODY = "#374151"
MUTED = "#4B5563"
RULE = "#E5E7EB"
PROBLEM = "#B42318"
NUM_RE = re.compile(r"\d[\d,.]*\s*(?:%|%p|배|분|초|시간|일|개월|년|월|건|곳|명|개|팀|대|회|만\s*원|억\s*원|조\s*원|원|만|억|조)?")


def t(x, y, value, size, color=INK, weight=400, anchor="start", attrs=""):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}"{a} '
            f'fill="{color}" {attrs}>{esc(value)}</text>')


def _emph(line: str, accent: str) -> str:
    """한 줄 안의 숫자(+단위)를 굵은 색 tspan으로. 글자는 그대로라 이어 읽으면 원문과 같다."""
    out, last = [], 0
    for m in NUM_RE.finditer(line):
        out.append(esc(line[last:m.start()]))
        out.append(f'<tspan font-weight="800" fill="{accent}">{esc(m.group())}</tspan>')
        last = m.end()
    out.append(esc(line[last:]))
    return "".join(out)


def para(x, y, value, width, lines, size, color=BODY, attrs="", anchor="start", weight=400,
         accent=None, lh=None):
    """여러 줄 글. 숫자 강조. (SVG, 줄 수)."""
    shown = str(value).strip() or EMPTY_VALUE_TEXT
    rows, _ = wrap(shown, size, width, lines)
    lh = lh or size + 8
    spans = "".join(
        f'<tspan x="{x:.1f}" dy="{0 if i == 0 else lh}">'
        f'{_emph(row + (" " if i < len(rows) - 1 else ""), accent or C["accent_deep"])}</tspan>'
        for i, row in enumerate(rows))
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}"{a} '
            f'fill="{color}" {attrs}>{spans}</text>', len(rows))


def heading(x, y, w, title):
    """구획 제목: 굵은 색 막대 + 제목 + 오른쪽으로 이어지는 얇은 선."""
    tw = estimate_text_width(title, 20)
    return (f'<rect x="{x}" y="{y - 17}" width="5" height="22" fill="{C["accent"]}"/>'
            + t(x + 16, y, title, 20, INK, 800, attrs='data-role="label"')
            + f'<line x1="{x + 30 + tw}" y1="{y - 6}" x2="{x + w}" y2="{y - 6}" stroke="{RULE}"/>')


def _items(data, key, fields, limit):
    rows = []
    for row in data.get(key) or []:
        if isinstance(row, dict) and str(row.get(fields[0], "")).strip():
            rows.append({f: str(row.get(f, "")).strip() for f in fields})
    return rows[:limit]


def _metrics(data, limit=4):
    return [m for m in data.get("key_metrics") or []
            if isinstance(m, dict) and str(m.get("value", "")).strip()][:limit]


# ── 머리말 ────────────────────────────────────────────────────


def header(category, data):
    """왼쪽: 분류 · 제목 · 소개 · 목표 고객 / 오른쪽: 대표 일러스트(없으면 가장 큰 숫자 하나).
    (SVG, 아래 끝 y, 첫 지표를 머리말에 보였는지)."""
    parts = []
    art = illustrations.image(illustrations.pick(category, data), 560, 24, 300, 190)
    kind = {"원페이지": "사업 한눈에 보기", "웹개발": "서비스 한눈에 보기", "AI_API": "AI 서비스 한눈에 보기"}[category]
    parts.append(t(40, 52, kind, 14, C["accent_deep"], 800, attrs='letter-spacing="2"'))
    lead = [] if art else _metrics(data, 1)
    left_w = 500 if art else (520 if lead else 820)
    size = fit_size(str(data.get("item_name", "")), 46, left_w, 30)
    parts.append(t(40, 106, fit(str(data.get("item_name", "")), size, left_w), size, INK, 900,
                   attrs='data-field="item_name" data-role="title" letter-spacing="-1"'))
    summary = str(data.get("item_summary", "")).strip()
    y = 140
    if summary:
        svg, n = para(40, y, summary, left_w, 2, 18, BODY, 'data-field="item_summary"', weight=500)
        parts.append(svg)
        y += n * 26
    target = str(data.get("target_users", "")).strip() or EMPTY_VALUE_TEXT
    parts.append(icons.icon("users", 50, y + 8, 18, C["accent_deep"], 2))
    parts.append(t(66, y + 14, "목표 고객", 14, C["accent_deep"], 800))
    parts.append(t(66 + estimate_text_width("목표 고객", 14) + 12, y + 14,
                   fit(target, 15, left_w - 110), 15, INK, 600, attrs='data-field="target_users" data-role="value"'))
    bottom = y + 34
    if art:
        parts.append(art)
        bottom = max(bottom, 214)
    elif lead:
        m = lead[0]
        vx = 600
        parts.append(f'<rect x="{vx - 20}" y="34" width="300" height="{bottom - 44}" fill="{C["accent_deep"]}"/>')
        vs = fit_size(str(m["value"]), 64, 250, 32)
        parts.append(t(vx, 34 + (bottom - 44) / 2 + 10, fit(str(m["value"]), vs, 260), vs, "#FFFFFF", 900,
                       attrs='data-field="key_metric" letter-spacing="-2"'))
        lab, _ = para(vx, 34 + (bottom - 44) / 2 + 40, m.get("label", ""), 250, 2, 14, "#FFFFFF",
                      'data-field="key_metric_label"', accent="#FFFFFF")
        parts.append(lab)
    parts.append(f'<rect x="40" y="{bottom + 6}" width="820" height="4" fill="{INK}"/>')
    return "".join(parts), bottom + 10, bool(lead)


# ── 블록 본문. (x, y, w): 제목 아래 본문 시작점. (SVG, 높이) ─────────────


def journey(data, x, y, w):
    cols = [("문제", "alert", "problem", data.get("problem", ""), PROBLEM),
            ("해결", "bulb", "solution", data.get("solution", ""), C["accent_deep"]),
            ("효과", "growth", "outcome", data.get("outcome", ""), C["accent_deep"])]
    cols = [c for c in cols if str(c[3]).strip() or c[2] != "outcome"]
    step = w / len(cols)
    parts, hs = [], []
    for i, (name, icon_name, field, value, tone) in enumerate(cols):
        cx = x + i * step
        parts.append(icons.icon(icon_name, cx + 22, y + 22, 40, tone, 2.2))
        parts.append(t(cx + 54, y + 30, name, 18, tone, 900, attrs='data-role="label"'))
        body, n = para(cx, y + 70, value or EMPTY_VALUE_TEXT, step - 56, 4, 16, INK,
                       f'data-field="{field}" data-role="value"', weight=600,
                       accent=PROBLEM if i == 0 else C["accent_deep"], lh=25)
        parts.append(body)
        hs.append(70 + (n - 1) * 25 + 10)
        if i < len(cols) - 1:
            ax = cx + step - 34
            parts.append(f'<path d="M{ax},{y + 8} L{ax + 20},{y + 30} L{ax},{y + 52}" fill="none" '
                         f'stroke="{RULE}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(parts), max(hs)


def split(data, x, y, w):
    col = (w - 40) / 2
    parts, hs = [], []
    for i, (name, field, tone) in enumerate([("해결할 문제", "problem", PROBLEM),
                                             ("해결 방식", "solution", C["accent_deep"])]):
        cx = x + i * (col + 40)
        parts.append(f'<rect x="{cx}" y="{y}" width="4" height="{{H}}" fill="{tone}"/>')
        parts.append(t(cx + 18, y + 18, name, 16, tone, 900, attrs='data-role="label"'))
        body, n = para(cx + 18, y + 48, data.get(field, ""), col - 20, 3, 16, INK,
                       f'data-field="{field}" data-role="value"', weight=500, lh=25)
        parts.append(body)
        hs.append(48 + (n - 1) * 25 + 8)
    h = max(hs)
    return "".join(parts).replace("{H}", str(h)), h


def before_after(data, x, y, w):
    rows = _items(data, "before_after", ("label", "before", "after"), 4)
    parts, cy = [], y
    if not data.get("_ps_elsewhere"):
        sv, n = split(data, x, y, w)
        parts.append(sv)
        cy = y + n + 26
    lw = w * .32
    colw = (w - lw) / 2
    parts.append(t(x + lw, cy + 14, "지금", 14, PROBLEM, 900))
    parts.append(t(x + lw + colw, cy + 14, fit(str(data.get("item_name", "")) + " 이후", 14, colw - 10), 14,
                   C["accent_deep"], 900))
    cy += 26
    for row in rows:
        parts.append(f'<line x1="{x}" y1="{cy}" x2="{x + w}" y2="{cy}" stroke="{RULE}"/>')
        lab, ln = para(x, cy + 30, row["label"], lw - 16, 2, 15, MUTED, 'data-field="before_after"', weight=600)
        big = 30 if re.search(r"\d", row["before"] + row["after"]) else 20
        bs = fit_size(row["before"], big, colw - 50, 14)
        parts.append(lab)
        parts.append(t(x + lw, cy + 36, fit(row["before"], bs, colw - 50), bs, PROBLEM, 900,
                       attrs='data-field="before_after" text-decoration="line-through"'))
        parts.append(f'<path d="M{x + lw + colw - 40},{cy + 26} L{x + lw + colw - 20},{cy + 26}" stroke="{MUTED}" '
                     f'stroke-width="2.5"/><path d="M{x + lw + colw - 26},{cy + 20} L{x + lw + colw - 18},{cy + 26} '
                     f'L{x + lw + colw - 26},{cy + 32}" fill="none" stroke="{MUTED}" stroke-width="2.5"/>')
        as_ = fit_size(row["after"], big, colw - 10, 14)
        parts.append(t(x + lw + colw, cy + 36, fit(row["after"], as_, colw - 10), as_, C["accent_deep"], 900,
                       attrs='data-field="before_after"'))
        cy += max(52, 30 + (ln - 1) * 22 + 18)
    return "".join(parts), cy - y


def features_list(data, features, x, y, w):
    details = data.get("feature_details") or []
    cols = 2 if w > 600 else 1
    col = (w - (cols - 1) * 36) / cols
    parts, cy, hs = [], y, []
    for i, feat in enumerate(features):
        c = i % cols
        if c == 0 and i:
            cy += max(hs) + 18
            hs = []
            parts.append(f'<line x1="{x}" y1="{cy - 9}" x2="{x + w}" y2="{cy - 9}" stroke="{RULE}"/>')
        cx = x + c * (col + 36)
        parts.append(icons.icon(icons.pick(feat), cx + 16, cy + 16, 32, C["accent_deep"], 2))
        name, nl = para(cx + 46, cy + 20, feat, col - 50, 2, 16, INK,
                        f'data-field="feature" data-feature="{esc(feat)}" data-role="value"', weight=800)
        detail = str(details[i]).strip() if i < len(details) else ""
        dt, dl = para(cx + 46, cy + 20 + nl * 24, detail or EMPTY_VALUE_TEXT, col - 50, 3, 14, BODY,
                      f'data-field="feature_detail" data-feature="{esc(feat)}" data-role="value"')
        parts += [name, dt]
        hs.append(20 + nl * 24 + (dl - 1) * 22 + 6)
    return "".join(parts), cy - y + max(hs or [0])


def process(data, category, x, y, w):
    steps = data.get("solution_steps") if category == "원페이지" else data.get("flow_steps")
    steps = [str(s) for s in steps or []][:6]
    if len(steps) < 2:
        return "", 0
    step = w / len(steps)
    cy = y + 34
    parts = [f'<line x1="{x + step / 2}" y1="{cy}" x2="{x + w - step / 2}" y2="{cy}" stroke="{C["accent"]}" '
             f'stroke-width="4"/>']
    field = "solution_steps" if category == "원페이지" else "flow_steps"
    hs = []
    for i, s in enumerate(steps):
        cx = x + (i + .5) * step
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="32" fill="{C["accent_deep"]}"/>')
        parts.append(icons.icon(icons.pick(s), cx, cy, 30, "#FFFFFF", 2.2))
        body, n = para(cx, cy + 62, s, step - 18, 2, 15, INK, f'data-field="{field}" data-role="value"',
                       "middle", 700)
        parts.append(body)
        hs.append(cy + 62 + (n - 1) * 22 - y + 8)
    return "".join(parts), max(hs)


def market(data, x, y, w):
    levels = _items(data, "market_levels", ("label", "value"), 3)
    if not levels:
        return "", 0
    units = {re.sub(r"[\d,.\s약]", "", lv["value"]) for lv in levels}
    nums = [re.search(r"\d[\d,.]*", lv["value"].replace(" ", "")) for lv in levels]
    if len(units) == 1 and all(nums):
        levels.sort(key=lambda lv: -float(re.search(r"\d[\d,.]*", lv["value"].replace(" ", "")).group()
                                           .replace(",", "")))
    radii = [92, 62, 34][:len(levels)] if len(levels) == 3 else [92, 50][:len(levels)]
    base = y + 196
    cx = x + 100 if w < 600 else x + 150
    fills = [C["tint"], C["accent"], C["accent_deep"]]
    parts = []
    for i, r in enumerate(radii):
        parts.append(f'<circle cx="{cx}" cy="{base - r}" r="{r}" fill="{fills[i]}" '
                     f'fill-opacity="{[1, .55, 1][i]}"/>')
    lx = cx + 124
    tw = min(x + w - lx, 380)
    ty = y + 26
    for i, (r, lv) in enumerate(zip(radii, levels)):
        parts.append(f'<path d="M{cx + r * .5},{base - 2 * r + 12} L{lx - 10},{ty - 8}" stroke="{INK}" '
                     f'stroke-width="1"/><circle cx="{cx + r * .5}" cy="{base - 2 * r + 12}" r="3" fill="{INK}"/>')
        vs = fit_size(lv["value"], 28, tw, 16)
        parts.append(t(lx, ty, fit(lv["value"], vs, tw), vs, C["accent_deep"], 900, attrs='data-field="market_levels"'))
        lab, ln = para(lx, ty + 22, lv["label"], tw, 2, 14, MUTED, 'data-field="market_levels"', weight=600, lh=18)
        parts.append(lab)
        ty += 22 + ln * 18 + 26
    return "".join(parts), max(204, ty - y - 20)


def competition(data, x, y, w):
    comp = data.get("comparison") or {}
    rows = _items(comp, "rows", ("criterion", "others", "ours"), 4)
    if not rows:
        return "", 0
    others = str(comp.get("others", "")).strip() or "기존 방식"
    c0, col = w * .26, w * .37
    parts = [t(x + c0, y + 16, fit(others, 15, col - 12), 15, MUTED, 800),
             f'<rect x="{x + c0 + col - 12}" y="{y - 6}" width="{col + 12}" height="{{H}}" fill="{C["accent_deep"]}"/>',
             t(x + c0 + col + 4, y + 16, fit(str(data.get("item_name", "")) or "우리", 15, col - 12), 15, "#FFFFFF", 900)]
    cy = y + 30
    for row in rows:
        parts.append(f'<line x1="{x}" y1="{cy}" x2="{x + c0 + col - 12}" y2="{cy}" stroke="{RULE}"/>')
        a, al = para(x, cy + 26, row["criterion"], c0 - 14, 2, 14, INK, 'data-field="comparison"', weight=800)
        b, bl = para(x + c0, cy + 26, row["others"], col - 24, 2, 14, MUTED, 'data-field="comparison"')
        c, cl = para(x + c0 + col + 4, cy + 26, row["ours"], col - 20, 2, 15, "#FFFFFF", 'data-field="comparison"',
                     weight=800, accent="#FFFFFF")
        parts += [a, b, c]
        cy += 26 + (max(al, bl, cl) - 1) * 22 + 16
    h = cy - y
    return "".join(parts).replace("{H}", str(h + 6)), h


def revenue(data, x, y, w, variant):
    flow = data.get("revenue_flow") or {}
    parts, cy = [], y
    price = re.search(r"\d[\d,.]*\s*(?:만\s*|억\s*|천\s*)?원", str(data.get("revenue_unit_price", "")))
    if variant == "flow" and (flow.get("payer") or flow.get("payment")):
        payer = str(flow.get("payer", "")).strip() or "고객"
        left, right = x + 34, x + w - 34
        mid = y + 40
        parts += [f'<circle cx="{left}" cy="{mid}" r="30" fill="{INK}"/>',
                  icons.icon(icons.pick(payer, "users"), left, mid, 30, "#FFFFFF", 2),
                  f'<circle cx="{right}" cy="{mid}" r="30" fill="{C["accent_deep"]}"/>',
                  icons.icon("target", right, mid, 30, "#FFFFFF", 2),
                  t(left, mid + 52, fit(payer, 14, 120), 14, INK, 800, "middle", 'data-field="revenue_flow"'),
                  t(right, mid + 52, fit(str(data.get("item_name", "")), 14, 120), 14, C["accent_deep"], 800, "middle"),
                  f'<path d="M{left + 40},{mid - 8} L{right - 44},{mid - 8}" stroke="{INK}" stroke-width="3"/>'
                  f'<path d="M{right - 54},{mid - 16} L{right - 42},{mid - 8} L{right - 54},{mid}" fill="none" '
                  f'stroke="{INK}" stroke-width="3"/>']
        span = right - left - 100
        if flow.get("payment"):
            _, pn = para(0, 0, str(flow["payment"]), span, 2, 17)
            pay, _ = para((left + right) / 2, mid - 18 - (pn - 1) * 22, str(flow["payment"]), span, 2, 17, INK,
                          'data-field="revenue_flow"', "middle", 900, lh=22)
            parts.append(pay)
        if flow.get("value"):
            parts.append(f'<path d="M{right - 40},{mid + 10} L{left + 44},{mid + 10}" stroke="{MUTED}" '
                         f'stroke-width="1.5" stroke-dasharray="5 4"/>')
            vs = fit_size(str(flow["value"]), 14, span, 12)
            parts.append(t((left + right) / 2, mid + 32, fit(str(flow["value"]), vs, span), vs, MUTED, 600,
                           "middle", 'data-field="revenue_flow"'))
        cy = mid + 76
    elif price:
        ps = fit_size(price.group(), 48, w, 24)
        parts.append(t(x, y + 46, fit(price.group(), ps, w), ps, C["accent_deep"], 900,
                       attrs='data-field="revenue_unit_price" letter-spacing="-1"'))
        cy = y + 64
    body, n = para(x, cy + 20, data.get("revenue_unit_price", ""), w, 3, 15, INK,
                   'data-field="revenue_unit_price" data-role="value"', weight=600)
    parts.append(body)
    return "".join(parts), cy - y + 20 + (n - 1) * 23 + 6


def roadmap(data, x, y, w):
    timeline = str(data.get("timeline_baseline", ""))
    stones = parse_milestones(timeline)
    if len(stones) < 2:
        body, n = para(x, y + 20, timeline, w, 3, 16, INK, 'data-field="timeline_baseline" data-role="value"',
                       weight=600)
        return body, 20 + (n - 1) * 24 + 8
    stones = stones[:5]
    step = w / len(stones)
    dl = max(len(wrap(d, 15, step - 20, 2)[0]) for d, _ in stones)
    line_y = y + 12 + dl * 20 + 14
    parts = [f'<rect x="{x}" y="{line_y - 3}" width="{w}" height="6" fill="{C["tint"]}"/>',
             f'<rect x="{x}" y="{line_y - 3}" width="{step * (len(stones) - .5):.1f}" height="6" fill="{C["accent"]}"/>']
    hs = []
    for i, (date, event) in enumerate(stones):
        sx = x + i * step
        parts.append(f'<circle cx="{sx + 10}" cy="{line_y}" r="10" fill="{C["accent_deep"]}"/>')
        d, _ = para(sx, y + 16, date, step - 20, 2, 15, C["accent_deep"],
                    'data-field="timeline_baseline" data-role="value"', weight=900, lh=20)
        e, n = para(sx, line_y + 36, event, step - 24, 3, 15, INK,
                    'data-field="timeline_baseline" data-role="value"', weight=600, lh=22)
        parts += [d, e]
        hs.append(line_y + 36 + (n - 1) * 22 - y + 8)
    return "".join(parts), max(hs)


def metrics(data, x, y, w, bars=False):
    ms = _metrics(data)
    # 머리말이 첫 지표를 크게 보여 주므로 여기서는 반복하지 않는다(지표가 둘 이상일 때).
    if data.get("_lead_metric_shown") and len(ms) > 1:
        ms = ms[1:]
    if not ms:
        return "", 0
    parts, cy = [], y
    num = re.compile(r"\d[\d,.]*")

    def val(s):
        m = num.search(str(s).replace(" ", ""))
        try:
            return float(m.group().replace(",", "")) if m else None
        except ValueError:
            return None
    paired = [m for m in ms if bars and val(m.get("before", "")) and val(m["value"])]
    for m in paired:
        b, a = val(m["before"]), val(m["value"])
        top = max(a, b)
        lab, _ = para(x, cy + 16, m.get("label", ""), w, 1, 15, INK, 'data-field="key_metric_label"', weight=800)
        parts.append(lab)
        bw = w - 110
        for j, (v, raw, col) in enumerate(((b, m["before"], "#D1D5DB"), (a, m["value"], C["accent_deep"]))):
            by = cy + 30 + j * 30
            parts.append(f'<rect x="{x}" y="{by}" width="{max(8, bw * v / top):.1f}" height="20" fill="{col}"/>')
            parts.append(t(x + max(8, bw * v / top) + 10, by + 16, fit(str(raw), 18, 100), 18,
                           MUTED if j == 0 else C["accent_deep"], 900, attrs='data-field="key_metric"'))
        cy += 104
    rest = [m for m in ms if m not in paired]
    if rest:
        cell = w / len(rest)
        hs = []
        for i, m in enumerate(rest):
            cx = x + i * cell
            if i:
                parts.append(f'<line x1="{cx - 14}" y1="{cy}" x2="{cx - 14}" y2="{cy + 96}" stroke="{RULE}"/>')
            vs = fit_size(str(m["value"]), 40, cell - 24, 20)
            parts.append(t(cx, cy + 44, fit(str(m["value"]), vs, cell - 24), vs, C["accent_deep"], 900,
                           attrs='data-field="key_metric" letter-spacing="-1"'))
            lab, n = para(cx, cy + 72, m.get("label", ""), cell - 28, 2, 14, MUTED, 'data-field="key_metric_label"',
                          weight=600)
            parts.append(lab)
            hs.append(72 + (n - 1) * 22 + 8)
        cy += max(hs)
    return "".join(parts), cy - y


def effects(data, x, y, w):
    rows = _items(data, "effects", ("who", "what"), 4)
    if not rows:
        return "", 0
    cols = len(rows) if w > 600 else min(2, len(rows))
    col = w / cols
    parts, cy, hs = [], y, []
    for i, r in enumerate(rows):
        c = i % cols
        if c == 0 and i:
            cy += max(hs) + 16
            hs = []
        cx = x + c * col
        parts.append(icons.icon(icons.pick(r["who"], "users"), cx + 14, cy + 14, 28, C["accent_deep"], 2))
        parts.append(t(cx + 38, cy + 22, fit(r["who"], 16, col - 50), 16, C["accent_deep"], 900,
                       attrs='data-field="effects"'))
        body, n = para(cx, cy + 54, r["what"], col - 24, 3, 15, INK, 'data-field="effects"', weight=600, lh=22)
        parts.append(body)
        hs.append(54 + (n - 1) * 22 + 6)
    return "".join(parts), cy - y + max(hs)


def tagline(data, x, y, w):
    line = str(data.get("tagline", "")).strip()
    if not line:
        return "", 0
    size = fit_size(line, 28, w - 40, 18)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="6" fill="{INK}"/>'
            + t(x, y + 52, fit(line, size, w - 20), size, INK, 900, attrs='data-field="tagline" letter-spacing="-1"')), 64


def statement(category, data, x, y, w):
    """대표 도식(허브형 자리). AI API는 입력 → 처리 → 출력을 채운 원으로, 나머지는
    문제(작게) → 해결(크게) → 효과(색 상자)로 한 문장처럼 읽힌다."""
    if category == "AI_API":
        pipe = data.get("pipeline") or {}
        stages = [("입력", "input", "doc"), ("처리", "process", "ai"), ("출력", "output", "chart")]
        step = w / 3
        parts, hs = [f'<line x1="{x + step / 2}" y1="{y + 44}" x2="{x + w - step / 2}" y2="{y + 44}" '
                     f'stroke="{C["accent"]}" stroke-width="5"/>'], []
        for i, (name, key, ic) in enumerate(stages):
            cx = x + (i + .5) * step
            parts.append(f'<circle cx="{cx}" cy="{y + 44}" r="42" fill="{C["accent_deep"] if i == 1 else INK}"/>')
            parts.append(icons.icon(icons.pick(str(pipe.get(key, "")), ic) if i != 1 else "ai", cx, y + 44, 38,
                                    "#FFFFFF", 2.2))
            parts.append(t(cx, y + 118, name, 18, C["accent_deep"], 900, "middle", 'data-role="label"'))
            body, n = para(cx, y + 146, pipe.get(key, ""), step - 30, 3, 16, INK,
                           f'data-field="pipeline.{key}" data-role="value"', "middle", 600, lh=24)
            parts.append(body)
            hs.append(146 + (n - 1) * 24 + 8)
        return "".join(parts), max(hs)
    parts = [t(x, y + 16, "문제", 16, PROBLEM, 900, attrs='data-role="label"')]
    prob, pn = para(x + 52, y + 16, data.get("problem", ""), w - 60, 2, 16, MUTED,
                    'data-field="problem" data-role="value"', weight=600, accent=PROBLEM, lh=24)
    parts.append(prob)
    cy = y + 16 + pn * 24 + 18
    outcome = str(data.get("outcome", "")).strip()
    sol_w = w - 290 if outcome else w
    parts.append(t(x, cy + 10, "해결", 16, C["accent_deep"], 900, attrs='data-role="label"'))
    sol, sn = para(x, cy + 52, data.get("solution", ""), sol_w - 10, 3, 24, INK,
                   'data-field="solution" letter-spacing="-.5"', weight=800, lh=34)
    parts.append(sol)
    h = cy + 52 + (sn - 1) * 34 - y + 16
    if outcome:
        bx = x + w - 260
        _, on = para(0, 0, outcome, 220, 3, 17)
        box_h = max(h - (cy - y) + 8, 62 + (on - 1) * 24 + 26)
        parts.append(f'<rect x="{bx}" y="{cy - 8}" width="260" height="{box_h}" fill="{C["accent_deep"]}"/>')
        parts.append(icons.icon("growth", bx + 30, cy + 20, 28, "#FFFFFF", 2.2))
        parts.append(t(bx + 54, cy + 27, "효과", 15, "#FFFFFF", 900))
        oc, _ = para(bx + 20, cy + 62, outcome, 220, 3, 17, "#FFFFFF", 'data-field="outcome"', weight=800,
                     accent="#FFFFFF", lh=24)
        parts.append(oc)
        h = max(h, cy - y + box_h)
    return "".join(parts), h
