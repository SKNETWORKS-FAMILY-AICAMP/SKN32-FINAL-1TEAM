"""색상값 해석과 명도 대비 계산 (WCAG 2.x 상대 휘도).

HTML 코드 점검(r4.py)과 원페이지 SVG 점검(r4_onepage.py)이 같이 쓴다.
"""
from __future__ import annotations

import re

# CSS Level 1 기본 색상 이름 + 생성 산출물에서 흔히 쓰이는 몇 가지.
_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "lime": (0, 255, 0), "aqua": (0, 255, 255),
    "teal": (0, 128, 128), "navy": (0, 0, 128), "fuchsia": (255, 0, 255),
    "purple": (128, 0, 128), "orange": (255, 165, 0), "pink": (255, 192, 203),
    "brown": (165, 42, 42),
}

_HEX_RE = re.compile(r"^#([0-9a-f]{3,8})$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*[\d.]+\s*)?\)$"
)


def parse_color(value: str) -> tuple[int, int, int] | None:
    """hex/rgb/rgba/기본 명명색만 지원한다. HSL 등은 판정불가로 처리."""
    v = value.strip().lower()
    if v in _NAMED_COLORS:
        return _NAMED_COLORS[v]

    hex_match = _HEX_RE.match(v)
    if hex_match:
        hex_part = hex_match.group(1)
        if len(hex_part) in (3, 4):
            hex_part = "".join(ch * 2 for ch in hex_part[:3])
        elif len(hex_part) in (6, 8):
            hex_part = hex_part[:6]
        else:
            return None
        try:
            return (int(hex_part[0:2], 16), int(hex_part[2:4], 16), int(hex_part[4:6], 16))
        except ValueError:
            return None

    rgb_match = _RGB_RE.match(v)
    if rgb_match:
        try:
            r, g, b = (min(255, max(0, round(float(rgb_match.group(i))))) for i in (1, 2, 3))
            return (r, g, b)
        except ValueError:
            return None
    return None


def _srgb_channel_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_channel_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    l1 = _relative_luminance(rgb_a)
    l2 = _relative_luminance(rgb_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _background_shorthand_color(value: str) -> str | None:
    """background 단축 속성에서 색상 토큰만 뽑는다. url()·그라디언트는 판정 밖."""
    if "url(" in value.lower() or "gradient" in value.lower():
        return None
    for token in re.split(r"\s+", value.strip()):
        if token and parse_color(token) is not None:
            return token
    return None


def extract_paired_declarations(css_text: str) -> list[tuple[str, dict[str, str]]]:
    """같은 셀렉터 블록 안에 글자색과 배경색이 함께 명시된 것만 추린다.

    캐스케이드·상속 계산은 브라우저 스타일 엔진이 필요하다 — 이 모듈은 "같은 셀렉터에
    명시적으로 짝지어 선언된 경우"만 검사 범위로 못박아 재현성을 지킨다.
    """
    css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    pairs: list[tuple[str, dict[str, str]]] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = match.group(1).strip()
        if not selector or selector.startswith("@"):
            continue
        declared: dict[str, str] = {}
        shorthand_bg: str | None = None
        for decl in match.group(2).split(";"):
            if ":" not in decl:
                continue
            prop, _, val = decl.partition(":")
            prop = prop.strip().lower()
            if prop in ("color", "background-color"):
                declared[prop] = val.strip()
            elif prop == "background":
                shorthand_bg = _background_shorthand_color(val)
        if "background-color" not in declared and shorthand_bg is not None:
            declared["background-color"] = shorthand_bg
        if "color" in declared and "background-color" in declared:
            pairs.append((selector, declared))
    return pairs
