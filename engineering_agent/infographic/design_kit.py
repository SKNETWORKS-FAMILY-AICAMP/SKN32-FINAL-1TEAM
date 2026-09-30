"""SVG infographic design tokens. Coordinates remain owned by layout.py.

An editorial hierarchy, one accent, and quiet rules replace decorative cards.
Keep all text live and preserve data-field/data-role for artifact verification.
"""
from __future__ import annotations

TITLE_SIZE = 36
TITLE_WIDTH = 820
RADIUS = 4

# Showcase is the default composition; editorial remains available for dense reports.
SHOWCASE = {
    "margin": 28, "gap": 14, "title_size": 36, "section_size": 18,
    "body_size": 15, "detail_size": 13, "metric_size": 28,
    "section_radius": 12, "icon_size": 46, "hero_height": 252,
}


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

    tab = estimate_text_width(title, 18) + 28
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" '
        f'fill="#FFFFFF" stroke="{colors["line"]}"/>'
        f'<rect x="{x + 10}" y="{y - 10}" width="{tab}" height="30" rx="8" '
        f'fill="{colors["tint"]}"/>'
        f'<text x="{x + 24}" y="{y + 11}" font-size="18" font-weight="700" '
        f'data-role="label" fill="{colors["ink"]}">{esc(title)}</text>'
    )


def arrow(x1: float, y1: float, x2: float, y2: float, color: str) -> str:
    """Straight connectors for the hero and process components."""
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    a = (x2 - 9 * math.cos(angle - .5), y2 - 9 * math.sin(angle - .5))
    b = (x2 - 9 * math.cos(angle + .5), y2 - 9 * math.sin(angle + .5))
    return (f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="1.8" fill="none"/>'
            f'<path d="M{a[0]},{a[1]} L{x2},{y2} L{b[0]},{b[1]} Z" fill="{color}"/>')


def rule(x: float, y: float, width: float, color: str) -> str:
    return (f'<line x1="{x}" y1="{y}" x2="{x + width}" y2="{y}" '
            f'stroke="{color}" stroke-width="1"/>')
