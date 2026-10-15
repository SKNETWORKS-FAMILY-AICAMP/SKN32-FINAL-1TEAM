"""SVG infographic design tokens. Coordinates remain owned by layout.py.

An editorial hierarchy, one accent, and quiet rules replace decorative cards.
Keep all text live and preserve data-field/data-role for artifact verification.
"""
from __future__ import annotations

from contextvars import ContextVar

TITLE_SIZE = 36
TITLE_WIDTH = 820

# 구역 틀 모양. 모든 구역을 같은 흰 카드에 담았더니 색 · 그림 · 구성이 달라도 같은 양식으로 보였다(실측: 실제
# 예시 계획서 셋). 디자인 사양(design.py)이 고르고, 지면 한 장을 조립하는 동안만 composer.compose가 정한다.
# ContextVar라 조율 워커가 여러 스레드로 T-B2를 동시에 돌려도 서로 섞이지 않는다.
#   card  흰 둥근 카드 + 탭 제목(기본)
#   panel 테두리 없는 옅은 색 판, 제목은 판 안 왼쪽 위
#   open  틀 없이 강조선 + 제목, 아래 가는 구분선(여백 중심)
FRAME_STYLES = ("card", "panel", "open")
FRAME_STYLE: ContextVar[str] = ContextVar("frame_style", default="card")


def showcase_defs(colors: dict[str, str]) -> str:
    """Shared materials for large illustrations and sections, without raster assets."""
    return (
        '<defs>'
        f'<linearGradient id="kit-wash" x1="0" y1="0" x2="0" y2="1">'
        f'<stop stop-color="#FFFFFF"/><stop offset="1" stop-color="{colors["tint"]}"/>'
        '</linearGradient>'
        f'<linearGradient id="kit-solid" x1="0" y1="0" x2="1" y2="1">'
        f'<stop stop-color="{colors["accent"]}"/><stop offset="1" stop-color="{colors["accent_deep"]}"/>'
        '</linearGradient>'
        '<filter id="kit-shadow" x="-30%" y="-30%" width="160%" height="180%">'
        '<feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#18342B" flood-opacity="0.09"/>'
        '</filter></defs>'
    )


def section_frame(x: float, y: float, width: float, height: float, title: str,
                  colors: dict[str, str]) -> str:
    from engineering_agent.infographic.svg_parts import esc
    from engineering_agent.infographic.layout import estimate_text_width

    style = FRAME_STYLE.get()
    label = (f'<text x="{x + 24}" y="{y + 11}" font-size="18" font-weight="700" '
             f'data-role="label" fill="{colors["ink"]}">{esc(title)}</text>')
    if style == "panel":
        # 제목 글자는 판(옅은 색) 위에 놓인다 — 검증-2 명도 대비는 글자를 감싸는 가장 작은 rect를 배경으로 본다.
        return (f'<rect x="{x}" y="{y - 12}" width="{width}" height="{height + 12}" rx="18" '
                f'fill="{colors["tint"]}"/>' + label)
    if style == "open":
        return (f'<rect x="{x + 24}" y="{y - 14}" width="34" height="4" rx="2" fill="{colors["accent"]}"/>'
                + label
                + f'<line x1="{x}" y1="{y + height}" x2="{x + width}" y2="{y + height}" '
                  f'stroke="{colors["line"]}" stroke-width="1.5"/>')
    tab = estimate_text_width(title, 18) + 28
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" '
        f'fill="#FFFFFF" stroke="{colors["line"]}"/>'
        f'<rect x="{x + 10}" y="{y - 10}" width="{tab}" height="30" rx="8" '
        f'fill="{colors["tint"]}"/>'
        + label
    )


def arrow(x1: float, y1: float, x2: float, y2: float, color: str) -> str:
    """Straight connectors for the hero and process components."""
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    a = (x2 - 9 * math.cos(angle - .5), y2 - 9 * math.sin(angle - .5))
    b = (x2 - 9 * math.cos(angle + .5), y2 - 9 * math.sin(angle + .5))
    return (f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="1.8" fill="none"/>'
            f'<path d="M{a[0]},{a[1]} L{x2},{y2} L{b[0]},{b[1]} Z" fill="{color}"/>')


