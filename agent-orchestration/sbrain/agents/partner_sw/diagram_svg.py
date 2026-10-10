"""그림 SVG 그리기 — 담당자 시험 서버의 flow_image(app/testing/test_server.py)를 옮긴 것 (spec 4.6).

가로 카드 + 화살표, 아래에 안내 문구 'AI 생성 명세 기반 개념도 · 상세 설계 검토 필요'. 그림은 파일 하나로 열린다(외부
참조 · 글꼴 파일 · 그림 파일을 부르지 않는다). 그리기 규칙만 옮겼다 — 바꾼 곳:
- 노드 계약이 깨진 출력의 기본 흐름 대체는 뺐다(우리는 F18 응답 검사에서 FormatError로 재시도한다, spec 4.1).
- 돌려주는 것은 SVG 바이트(utf-8)다. 파일은 Task가 tools.files로 넣는다.
"""
from __future__ import annotations

import html
import re
from typing import Any

SVG_TYPE = "image/svg+xml"
FILE_NAMES = {"USER_FLOW": "userflow.svg", "SERVICE_ARCHITECTURE": "architecture.svg"}   # 파일 이름 (spec 4.6)
NOTICE = "AI 생성 명세 기반 개념도 · 상세 설계 검토 필요"


def _safe_color(value: Any, fallback: str) -> str:
    value = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value) or re.fullmatch(r"(?:rgb|rgba|hsl|hsla)\([^)]{1,40}\)", value):
        return value
    return fallback


def render(output: dict[str, Any]) -> bytes:
    """F18 그림 하나(nodes · flowType · visualStyle)를 SVG로 그린다 — 담당자 flow_image의 그리기 그대로."""
    nodes = [str(n) for n in output.get("nodes") or []]
    width = 1100 / max(len(nodes), 1)
    flow_type = output.get("flowType", "USER_FLOW")
    title = "USERFLOW" if flow_type == "USER_FLOW" else "서비스 구조도"
    visual = output.get("visualStyle") if isinstance(output.get("visualStyle"), dict) else {}
    palette = ([_safe_color(x, "#2563eb") for x in visual.get("palette", [])[:6]]
               if isinstance(visual.get("palette"), list) else None)
    background = _safe_color(visual.get("background"), "#f8fafc") if isinstance(visual.get("background"), str) else None
    accent = _safe_color(visual.get("accent"), "#2457d6") if isinstance(visual.get("accent"), str) else None
    style = str(output.get("styleInstruction", "")).lower()
    if palette and len(palette) >= 3:
        colors = [str(x) for x in palette[:6]]
        background = background or "#f8fafc"
        accent = accent or colors[0]
    elif any(word in style for word in ("파란", "blue", "navy", "청색")):
        colors = ["#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa", "#1e40af", "#0ea5e9"]
        background, accent = "#eff6ff", "#1e3a8a"
    elif any(word in style for word in ("초록", "green", "민트")):
        colors = ["#047857", "#059669", "#10b981", "#34d399", "#065f46", "#14b8a6"]
        background, accent = "#ecfdf5", "#065f46"
    elif any(word in style for word in ("보라", "purple", "violet")):
        colors = ["#6d28d9", "#7c3aed", "#8b5cf6", "#a78bfa", "#5b21b6", "#c026d3"]
        background, accent = "#f5f3ff", "#4c1d95"
    else:
        colors = ["#2563eb", "#7c3aed", "#0891b2", "#059669", "#d97706", "#db2777"]
        background, accent = "#f8fafc", "#2457d6"
    card_style = visual.get("cardStyle") if isinstance(visual.get("cardStyle"), dict) else {}
    try:
        radius = max(0, min(28, int(card_style.get("radius", 12))))
    except (TypeError, ValueError):
        radius = 12
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1140 230"><rect width="1140" height="230" rx="16" '
           f'fill="{background}"/><text x="40" y="38" font-family="sans-serif" font-size="22" font-weight="700" '
           f'fill="#172033">{title}</text>')
    for i, node in enumerate(nodes):
        x = 20 + i * width
        svg += (f'<rect x="{x}" y="65" width="{width - 22}" height="65" rx="{radius}" fill="{colors[i % len(colors)]}"/>'
                f'<text x="{x + (width - 22) / 2}" y="104" text-anchor="middle" font-family="sans-serif" font-size="14" '
                f'font-weight="600" fill="white">{html.escape(node)}</text>')
        if i < len(nodes) - 1:
            svg += f'<text x="{x + width - 21}" y="104" fill="{accent}">→</text>'
    svg += (f'<text x="40" y="185" font-family="sans-serif" font-size="13" fill="#667085">{NOTICE}</text></svg>')
    return svg.encode("utf-8")
