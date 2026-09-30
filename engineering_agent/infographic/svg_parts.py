"""지면의 글 조각(제목 · 값 · 기능 목록)과 대체 텍스트 문장을 만든다.

값 노드의 data-field · data-role · data-feature 표식은 검증-2가 항목을 찾는
규약이다. 표식을 바꾸면 verification_agent/rules/r4_onepage.py와
verification_agent/feature_match.py도 같이 바꿔야 한다."""
from __future__ import annotations

from engineering_agent.infographic.style import BRAND_COLORS
from engineering_agent.infographic.layout import W_FEATURE_LIST, fit, wrap


def esc(text: object) -> str:
    """SVG 텍스트 노드에 안전하게 넣기 위한 XML 이스케이프.

    사용자/LLM이 채운 데이터(아이템명 등)에 &, <, > 같은 문자가 섞이면
    SVG 파싱 자체가 깨지므로 반드시 거친다.
    """
    s = str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def section_title(x: int, y: int, text: str) -> str:
    """구획 제목. data-role='label'은 채점기가 정보 계층(제목>라벨>값)을 역할로
    판정하기 위한 표식이다 — 글자 크기 종류만 세면 템플릿이 고정된 탓에 항상
    통과해 버려서 아무것도 걸러내지 못한다."""
    return (f'<text x="{x}" y="{y}" font-size="18" font-weight="700" '
            f'data-role="label" fill="{BRAND_COLORS["text"]}">{esc(text)}</text>')


# 값이 비었을 때 지면에 들어가는 문구. 채점기는 이 문구를 "값 없음"으로 읽는다
# (verification_agent/rules/r4_onepage.py의 _PLACEHOLDER_VALUES와 같은 목록).
EMPTY_VALUE_TEXT = "정보 없음"
# 기능 설명 글자색. text_muted(#64748B)는 배경 #F8FAFC 위에서 대비 4.55라 기준선에
# 붙어 있어 한 단계 진한 색을 쓴다.
DETAIL_TEXT = "#334155"


def card(x: float, y: float, w: float, h: float, fill: str = "#FFFFFF",
         stroke: str = "#E2E8F0") -> str:
    """흰 카드. 검증-2 명도 대비는 글자를 감싸는 가장 작은 rect의 fill을 배경으로 본다."""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1"/>')


def wrapped_text(x: float, y: float, text: str, *, size: int, max_width: float,
                 max_lines: int, line_height: float, fill: str, attrs: str = "",
                 anchor: str = "start") -> tuple[str, int]:
    """여러 줄 값. text 하나에 줄마다 tspan을 둔다 — 검증-2가 노드 하나로 값을 읽고,
    줄 끝 띄어쓰기를 남겨 이어 읽으면 원문과 같다. (SVG 조각, 줄 수)."""
    shown = str(text).strip() or EMPTY_VALUE_TEXT
    lines, _ = wrap(shown, size, max_width, max_lines)
    spans = "".join(
        f'<tspan x="{x}" dy="{0 if i == 0 else line_height}">'
        f'{esc(line + (" " if i < len(lines) - 1 else ""))}</tspan>'
        for i, line in enumerate(lines))
    anchor_attr = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}"{anchor_attr} {attrs} fill="{fill}">'
            f'{spans}</text>'.replace("  ", " "), len(lines))


def feature_bullet_list(x: int, y: int, features: list[str]) -> tuple[str, int]:
    """불릿 리스트를 <g> 블록 문자열로 조립한다. 반환값의 y는 리스트 다음 줄 좌표."""
    parts: list[str] = []
    if not features:
        parts.append(
            f'<text x="{x + 16}" y="{y}" font-size="15" data-role="value" '
            f'fill="{BRAND_COLORS["text_muted"]}">등록된 기능이 없습니다</text>'
        )
        y += 34
        return "\n".join(parts), y
    for feat in features:
        parts.append(
            f'<circle cx="{x + 6}" cy="{y - 6}" r="5" fill="{BRAND_COLORS["secondary"]}"/>'
            f'<text x="{x + 22}" y="{y}" font-size="16" data-field="feature" data-role="value" '
            f'fill="{BRAND_COLORS["text"]}">{esc(fit(feat, 16, W_FEATURE_LIST))}</text>'
        )
        y += 34
    return "\n".join(parts), y


def build_alt_text(category: str, item_name: str, features: list[str]) -> str:
    """altText 자동 생성 — 채점 모듈이 <title>에서 이 텍스트를 그대로 읽는다."""
    if features:
        summary = ", ".join(features[:3])
        if len(features) > 3:
            summary += " 등"
    else:
        summary = "정보 없음"
    return f"{item_name} 인포그래픽: 핵심 기능 {summary}"


def build_desc_text(category: str, item_name: str, data: dict) -> str:
    """<desc> 본문. <title>(altText)과 같은 문장을 넣으면 스크린리더에 더해지는
    정보가 없어 검증 2번이 형식만 통과한다. 지면에 실제로 적힌 값을 담아 <title>과
    다른 문장으로 만든다(원페이지 전용).
    """
    parts: list[str] = []
    for field, label in (
        ("target_users", "목표 고객"), ("problem", "문제 정의"),
        ("solution", "해결 방안"), ("revenue_unit_price", "수익모델 단가"),
        ("timeline_baseline", "추진 일정 기준선"),
    ):
        value = str(data.get(field, "")).strip()
        if value and value != EMPTY_VALUE_TEXT:
            parts.append(f"{label} {value}")
    body = ". ".join(parts) if parts else "지면에 기재된 항목이 없습니다"
    return f"{item_name} 원페이지 지면 설명. {body}."
