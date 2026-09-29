"""T-B2: 계획서에서 구조화된 정보를 추출하고 시도별 SVG를 렌더링한다."""

import uuid
import re
from pathlib import Path
from pydantic import BaseModel, Field

# 3개 템플릿이 공유하는 브랜드 컬러 팔레트.
# 값 하나 바꾸면 3개 카테고리 전부에 일관되게 반영되도록 상수로만 정의한다.
BRAND_COLORS = {
    "bg": "#F8FAFC",
    "surface": "#FFFFFF",
    "primary": "#2563EB",
    "secondary": "#10B981",
    "accent": "#F59E0B",
    "text": "#0F172A",
    "text_muted": "#64748B",
    "border": "#E2E8F0",
}

# 카테고리별 강조색 — 배지·플로우 박스 테두리 등 카테고리를 한눈에 구분하는 용도.
CATEGORY_ACCENT = {
    "원페이지": "#2563EB",
    "웹개발": "#7C3AED",
    "AI_API": "#0EA5A4",
}

CATEGORY_LABEL = {
    "원페이지": "원페이지",
    "웹개발": "웹개발",
    "AI_API": "AI API",
}

CATEGORY_TEMPLATE_FILE = {
    "원페이지": "onepage_template.svg",
    "웹개발": "webdev_template.svg",
    "AI_API": "ai_api_template.svg",
}

_TEMPLATE_DIR = Path(__file__).parent / "infographic_templates"
_OUTPUT_DIR = Path(__file__).parent / "output"

# 카테고리별로 render_infographic()의 body 빌더가 실제로 소비하는 필드만 요구한다 —
# 스키마를 넓게 잡으면 LLM이 안 쓰이는 필드까지 채우려다 없는 사실을 지어낼 여지가 생긴다.
_SCHEMA_HINTS: dict[str, str] = {
    "원페이지": (
        '{"item_name": str, "features": [str, ...], "target_users": str, '
        '"problem": str, "solution": str, "revenue_unit_price": str, '
        '"timeline_baseline": str, '
        '"feature_details": [{"name": str, "detail": str}, ...]}'
    ),
    "웹개발": '{"item_name": str, "features": [str, ...], "flow_steps": [str, ...]}',
    "AI_API": (
        '{"item_name": str, "features": [str, ...], '
        '"pipeline": {"input": str, "process": str, "output": str}}'
    ),
}


class FeatureDetail(BaseModel):
    name: str
    detail: str = ""


class InfographicContent(BaseModel):
    item_name: str
    features: list[str]
    target_users: str = ""
    problem: str = ""
    solution: str = ""
    revenue_unit_price: str = ""
    timeline_baseline: str = ""
    flow_steps: list[str] = Field(default_factory=list)
    pipeline: dict[str, str] = Field(default_factory=dict)
    # 원페이지 전용. 기능마다 계획서 본문에서 뽑은 한 줄 설명 — 검증-2는 이 설명이
    # 계획서에 근거가 있는지로 계획서 대조를 판정한다. 기능명은 목록을 옮겨 적은 것이라
    # 기능명만 보면 자기 채점이 된다.
    feature_details: list[FeatureDetail] = Field(default_factory=list)


PAGE_WIDTH = 900

# 각 자리의 글자가 쓸 수 있는 최대 폭(px). 본문 builder가 실제로 쓰는 좌표에서 나온 값이라
# 레이아웃을 바꾸면 여기도 같이 바꿔야 한다 — overflow_fields()가 이 값으로 판정한다.
_W_TITLE = 660          # 머리말 아이템명: x=40, 배지가 x=716에서 시작
_W_ONEPAGE_VALUE = 820  # 원페이지 값: x=40, 우여백 40
_W_FEATURE_LIST = 800   # 불릿 리스트: x=62, 우여백 40
_W_FEATURE_DETAIL = 800  # 원페이지 기능 설명: 기능명 아랫줄, 같은 폭
_W_WEBDEV_FEATURE = 330  # 2단 그리드 한 칸: col_w 400 - 아이콘 영역
_W_WEBDEV_FLOW = 170    # 플로우 박스 190 - 좌우 여백
_W_AI_PIPELINE = 200    # 파이프라인 박스 220 - 좌우 여백


def estimate_text_width(text: str, font_size: float) -> float:
    """글자 폭 어림값. 한글·CJK는 전각(≈font_size), 그 외는 반각(≈0.55배)으로 센다.

    정확한 폭은 폰트 메트릭이 있어야 나오지만, 여기서 필요한 것은 "지면을 넘겼는가"
    수준의 판정이라 이 어림으로 충분하다. 표준 라이브러리만 쓴다는 제약도 지킨다.
    """
    wide = sum(1 for ch in text if ord(ch) > 0x2000)
    return wide * font_size + (len(text) - wide) * font_size * 0.55


def _fit(text: str, font_size: float, max_width: float) -> str:
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


def _slots(category: str, data: dict) -> list[tuple[str, str, float, float]]:
    """(필드명, 글자, 글자크기, 허용폭) 목록. 본문 builder가 쓰는 자리와 일치한다."""
    features = [str(f) for f in (data.get("features") or [])]
    slots: list[tuple[str, str, float, float]] = [
        ("item_name", str(data.get("item_name", "")), 30, _W_TITLE),
    ]
    if category == "원페이지":
        for field in ("target_users", "problem", "solution",
                      "revenue_unit_price", "timeline_baseline"):
            slots.append((field, str(data.get(field, "")), 16, _W_ONEPAGE_VALUE))
        slots += [("feature", f, 16, _W_FEATURE_LIST) for f in features]
        slots += [("feature_detail", str(d), 14, _W_FEATURE_DETAIL)
                  for d in (data.get("feature_details") or [])]
    elif category == "웹개발":
        slots += [("feature", f, 16, _W_WEBDEV_FEATURE) for f in features]
        slots += [("flow_steps", str(s), 15, _W_WEBDEV_FLOW)
                  for s in (data.get("flow_steps") or [])]
    else:  # AI_API
        pipeline = data.get("pipeline") or {}
        slots += [(f"pipeline.{key}", str(pipeline.get(key, "")), 15, _W_AI_PIPELINE)
                  for key in ("input", "process", "output")]
        slots += [("feature", f, 16, _W_FEATURE_LIST) for f in features]
    return slots


def overflow_fields(category: str, data: dict) -> list[str]:
    """지면 폭을 넘겨 잘라내야 하는 값의 필드명 목록.

    T-B2 자체 검사가 이걸 실패로 올려 재수행에서 더 짧은 문장을 받게 한다.
    지면 한 장이 산출물 전체인 원페이지에서는 넘쳐서 안 보이는 것이 빠진 것과 같다
    (기획서 5-4).
    """
    if category not in CATEGORY_TEMPLATE_FILE:
        raise ValueError(f"알 수 없는 카테고리: {category!r}")
    seen: list[str] = []
    for field, text, size, max_width in _slots(category, data):
        if text.strip() and estimate_text_width(text, size) > max_width and field not in seen:
            seen.append(field)
    return seen


def _esc(text: object) -> str:
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


def _load_template(filename: str) -> str:
    path = _TEMPLATE_DIR / filename
    return path.read_text(encoding="utf-8")


def _substitute(template: str, mapping: dict[str, str]) -> str:
    """{{key}} 토큰을 값으로 치환하고, 치환 누락(잔재)이 없는지 검증한다.

    "템플릿에 주입한 값이 렌더링 결과에 정확히 일치해야 한다"는 요구사항의
    핵심 방어선 — mapping에 있는 키인데도 결과에 여전히 {{key}} 형태로
    남아있다면 치환 버그이므로 조용히 넘기지 않고 바로 예외를 던진다.
    """
    result = template
    for key, value in mapping.items():
        result = result.replace("{{" + key + "}}", value)
    leftover = [key for key in mapping if "{{" + key + "}}" in result]
    if leftover:
        raise ValueError(f"치환되지 않은 플레이스홀더가 남아있습니다: {leftover}")
    return result


def _section_title(x: int, y: int, text: str) -> str:
    """구획 제목. data-role='label'은 채점기가 정보 계층(제목>라벨>값)을 역할로
    판정하기 위한 표식이다 — 글자 크기 종류만 세면 템플릿이 고정된 탓에 항상
    통과해 버려서 아무것도 걸러내지 못한다."""
    return (f'<text x="{x}" y="{y}" font-size="18" font-weight="700" '
            f'data-role="label" fill="{BRAND_COLORS["text"]}">{_esc(text)}</text>')


# 값이 비었을 때 지면에 들어가는 문구. 채점기는 이 문구를 "값 없음"으로 읽는다
# (verification_agent/rules/r4_onepage.py의 _PLACEHOLDER_VALUES와 같은 목록).
_EMPTY_VALUE_TEXT = "정보 없음"
# 기능 설명 글자색. text_muted(#64748B)는 배경 #F8FAFC 위에서 대비 4.55라 기준선에
# 붙어 있어 한 단계 진한 색을 쓴다.
_DETAIL_TEXT = "#334155"


def _value_text(x: int, y: int, field: str, value: str, size: int = 16,
                max_width: float = _W_ONEPAGE_VALUE) -> str:
    """값 노드. data-field로 어떤 항목의 값인지 표시한다 — 채점기가 '라벨 다음
    노드'라는 순서 가정 없이 항목을 찾을 수 있어야 템플릿 수정에 안 깨진다."""
    shown = str(value).strip() or _EMPTY_VALUE_TEXT
    shown = _fit(shown, size, max_width)
    return (f'<text x="{x}" y="{y}" font-size="{size}" data-field="{field}" '
            f'data-role="value" fill="{BRAND_COLORS["text"]}">{_esc(shown)}</text>')


def _feature_bullet_list(x: int, y: int, features: list[str]) -> tuple[str, int]:
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
            f'fill="{BRAND_COLORS["text"]}">{_esc(_fit(feat, 16, _W_FEATURE_LIST))}</text>'
        )
        y += 34
    return "\n".join(parts), y


def _feature_detail_list(x: int, y: int, features: list[str],
                         details: list[str]) -> tuple[str, int]:
    """원페이지 핵심 기능: 기능명 한 줄 + 계획서에서 뽑은 설명 한 줄.

    설명 노드의 data-field="feature_detail"과 data-feature="기능명"은 검증-2가 기능별
    설명을 찾는 표식이다. 설명이 비면 "정보 없음"을 적고, 검증-2는 그 기능을 인정하지 않는다.
    """
    if not features:
        return _feature_bullet_list(x, y, features)
    parts: list[str] = []
    for i, feat in enumerate(features):
        detail = (str(details[i]) if i < len(details) else "").strip() or _EMPTY_VALUE_TEXT
        parts.append(
            f'<circle cx="{x + 6}" cy="{y - 6}" r="5" fill="{BRAND_COLORS["secondary"]}"/>'
            f'<text x="{x + 22}" y="{y}" font-size="16" font-weight="700" data-field="feature" '
            f'data-feature="{_esc(feat)}" data-role="value" fill="{BRAND_COLORS["text"]}">'
            f'{_esc(_fit(feat, 16, _W_FEATURE_LIST))}</text>'
            f'<text x="{x + 22}" y="{y + 24}" font-size="14" data-field="feature_detail" '
            f'data-feature="{_esc(feat)}" data-role="value" fill="{_DETAIL_TEXT}">'
            f'{_esc(_fit(detail, 14, _W_FEATURE_DETAIL))}</text>'
        )
        y += 58
    return "\n".join(parts), y


def _build_alt_text(category: str, item_name: str, features: list[str]) -> str:
    """altText 자동 생성 — 채점 모듈이 <title>에서 이 텍스트를 그대로 읽는다."""
    if features:
        summary = ", ".join(features[:3])
        if len(features) > 3:
            summary += " 등"
    else:
        summary = "정보 없음"
    return f"{item_name} 인포그래픽: 핵심 기능 {summary}"


def _build_desc_text(category: str, item_name: str, data: dict) -> str:
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
        if value and value != _EMPTY_VALUE_TEXT:
            parts.append(f"{label} {value}")
    body = ". ".join(parts) if parts else "지면에 기재된 항목이 없습니다"
    return f"{item_name} 원페이지 지면 설명. {body}."


# ---------------------------------------------------------------------------
# 카테고리별 본문(body) 조립
# ---------------------------------------------------------------------------


def _build_onepage_body(data: dict, features: list[str]) -> tuple[str, int]:
    """원페이지의 필수 여섯 정보를 실제 SVG text 노드로 그린다.

    여섯 정보 중 아이템명은 템플릿 머리말이 담당하고, 나머지 다섯 개를 여기서
    라벨 + 값 한 쌍으로 그린다. 값 노드에는 data-field를 붙여 채점기가 순서가
    아니라 표식으로 찾게 한다.
    """
    parts: list[str] = []
    y = 150
    for field, label in (
        ("target_users", "목표 고객"),
        ("problem", "문제 정의"),
        ("solution", "해결 방안"),
        ("revenue_unit_price", "수익모델 단가"),
        ("timeline_baseline", "추진 일정 기준선"),
    ):
        parts.append(_section_title(40, y, label))
        parts.append(_value_text(40, y + 30, field, str(data.get(field, ""))))
        y += 76
    parts.append(_section_title(40, y, "핵심 기능"))
    y += 34
    feature_svg, y = _feature_detail_list(40, y, features, data.get("feature_details") or [])
    parts.append(feature_svg)

    y += 30
    return "\n".join(parts), y


def _build_webdev_body(data: dict, features: list[str]) -> tuple[str, int]:
    """웹개발: 아이콘+텍스트 기능 3~4개 + 사용자 플로우 A→B→C."""
    flow_steps = [str(s) for s in (data.get("flow_steps") or data.get("user_flow") or [])]
    icon_colors = [
        BRAND_COLORS["primary"],
        BRAND_COLORS["secondary"],
        BRAND_COLORS["accent"],
        CATEGORY_ACCENT["웹개발"],
    ]

    parts: list[str] = []
    y = 150
    parts.append(_section_title(40, y, "핵심 기능"))
    y += 40

    col_w, row_h, icon_r = 400, 70, 20
    for i, feat in enumerate(features):
        col, row = i % 2, i // 2
        cx, cy = 40 + col * col_w, y + row * row_h
        icon_color = icon_colors[i % len(icon_colors)]
        parts.append(
            f'<circle cx="{cx + icon_r}" cy="{cy + icon_r}" r="{icon_r}" fill="{icon_color}"/>'
            f'<text x="{cx + icon_r}" y="{cy + icon_r + 6}" font-size="16" font-weight="700" fill="#FFFFFF" text-anchor="middle">{i + 1}</text>'
            f'<text x="{cx + 2 * icon_r + 16}" y="{cy + icon_r + 6}" font-size="16" data-field="feature" '
            f'data-role="value" fill="{BRAND_COLORS["text"]}">{_esc(_fit(feat, 16, _W_WEBDEV_FEATURE))}</text>'
        )
    rows_used = (len(features) + 1) // 2 if features else 0
    y += rows_used * row_h + (30 if features else 34)
    if not features:
        parts.append(
            f'<text x="56" y="{y - 20}" font-size="15" fill="{BRAND_COLORS["text_muted"]}">등록된 기능이 없습니다</text>'
        )

    if flow_steps:
        parts.append(_section_title(40, y, "사용자 플로우"))
        y += 40
        box_w, box_h, gap = 190, 64, 50
        for i, step in enumerate(flow_steps):
            row, col = divmod(i, 3)
            row_count = min(3, len(flow_steps) - row * 3)
            total_w = row_count * box_w + (row_count - 1) * gap
            bx = (900 - total_w) // 2 + col * (box_w + gap)
            by = y + row * (box_h + 24)
            parts.append(
                f'<rect x="{bx}" y="{by}" width="{box_w}" height="{box_h}" rx="10" '
                f'fill="{BRAND_COLORS["surface"]}" stroke="{CATEGORY_ACCENT["웹개발"]}" stroke-width="2"/>'
                f'<text x="{bx + box_w / 2}" y="{by + box_h / 2 + 6}" font-size="15" font-weight="700" '
                f'data-field="flow_steps" data-role="value" '
                f'fill="{BRAND_COLORS["text"]}" text-anchor="middle">{_esc(_fit(step, 15, _W_WEBDEV_FLOW))}</text>'
            )
            if col < row_count - 1:
                ax1, ax2 = bx + box_w + 8, bx + box_w + gap - 8
                amidy = by + box_h / 2
                parts.append(
                    f'<line x1="{ax1}" y1="{amidy}" x2="{ax2}" y2="{amidy}" '
                    f'stroke="{BRAND_COLORS["text_muted"]}" stroke-width="2" marker-end="url(#arrowhead)"/>'
                )
        y += ((len(flow_steps) + 2) // 3) * (box_h + 24) + 16
    else:
        y += 10

    return "\n".join(parts), int(y)


def _build_ai_api_body(data: dict, features: list[str]) -> tuple[str, int]:
    """AI_API: 입력→처리→출력 3단 파이프라인 + 핵심 기능 리스트."""
    pipeline = data.get("pipeline") or {}
    stages = [
        ("input", "입력", str(pipeline.get("input", "")).strip() or _EMPTY_VALUE_TEXT),
        ("process", "처리", str(pipeline.get("process", "")).strip() or _EMPTY_VALUE_TEXT),
        ("output", "출력", str(pipeline.get("output", "")).strip() or _EMPTY_VALUE_TEXT),
    ]
    accent = CATEGORY_ACCENT["AI_API"]

    parts: list[str] = []
    y = 150
    parts.append(_section_title(40, y, "처리 파이프라인"))
    y += 44

    box_w, box_h, gap = 220, 120, 60
    total_w = 3 * box_w + 2 * gap
    start_x = (900 - total_w) // 2
    for i, (label_key, label, text) in enumerate(stages):
        bx = start_x + i * (box_w + gap)
        parts.append(
            f'<text x="{bx + box_w / 2}" y="{y}" font-size="14" font-weight="700" data-role="label" fill="{accent}" text-anchor="middle">{_esc(label)}</text>'
            f'<rect x="{bx}" y="{y + 14}" width="{box_w}" height="{box_h}" rx="12" '
            f'fill="{BRAND_COLORS["surface"]}" stroke="{accent}" stroke-width="2"/>'
            f'<text x="{bx + box_w / 2}" y="{y + 14 + box_h / 2 + 6}" font-size="15" '
            f'data-field="pipeline.{label_key}" data-role="value" '
            f'fill="{BRAND_COLORS["text"]}" text-anchor="middle">{_esc(_fit(text, 15, _W_AI_PIPELINE))}</text>'
        )
        if i < 2:
            ax1, ax2 = bx + box_w + 10, bx + box_w + gap - 10
            amidy = y + 14 + box_h / 2
            parts.append(
                f'<line x1="{ax1}" y1="{amidy}" x2="{ax2}" y2="{amidy}" '
                f'stroke="{BRAND_COLORS["text_muted"]}" stroke-width="2" marker-end="url(#arrowhead)"/>'
            )
    y += 14 + box_h + 40

    parts.append(_section_title(40, y, "핵심 기능"))
    y += 34
    feature_svg, y = _feature_bullet_list(40, y, features)
    parts.append(feature_svg)

    y += 30
    return "\n".join(parts), int(y)


_BODY_BUILDERS = {
    "원페이지": _build_onepage_body,
    "웹개발": _build_webdev_body,
    "AI_API": _build_ai_api_body,
}


def generate_infographic_content(category: str, plan_text: str, tools) -> dict:
    """T-B2 1단계: 사업계획서 본문(작성 Agent 산출물)에서 인포그래픽 데이터를 추출한다.

    반환값은 render_infographic()의 data 인자로 그대로 넘길 수 있는 형태다.
    팀 경력·수익모델 단가처럼 조율 Agent가 사용자에게서 직접 받아야 하는 사실
    항목은 이 스키마에 아예 없다 — render_infographic이 소비하는 필드(기능,
    목표 고객층, 플로우, 파이프라인 단계 등)만 뽑으므로 이 함수가 사실을
    지어낼 대상 자체가 없다.
    """
    if category not in CATEGORY_TEMPLATE_FILE:
        raise ValueError(
            f"알 수 없는 카테고리: {category!r} (허용값: {sorted(CATEGORY_TEMPLATE_FILE)})"
        )

    system_prompt = (
        "너는 사업계획서 본문에서 인포그래픽에 넣을 항목만 뽑아내는 추출기다.\n"
        "규칙:\n"
        "1. 본문에 명시적으로 나오지 않은 숫자·사실은 절대 지어내지 마라 — 없으면 "
        '빈 리스트나 "정보 없음"으로 남겨라.\n'
        "2. 다른 설명 없이 JSON 객체 하나만 출력하라. 값은 원문에서 그대로 인용하고 없으면 빈 문자열로 남겨라.\n"
        f"3. 출력 스키마: {_SCHEMA_HINTS[category]}"
    )
    if category == "원페이지":
        system_prompt += (
            "\n4. feature_details에는 '기능 목록'의 기능마다 하나씩, name에 기능명을 그대로 "
            "쓰고 detail에 그 기능이 무엇을 하는지 본문에서 찾은 한 문장을 원문 낱말 그대로 "
            "적어라. 45자를 넘기지 마라. 기능명을 되풀이하지 말고, 본문이 그 기능을 설명하지 "
            "않으면 detail을 빈 문자열로 남겨라."
        )
    result = tools.llm(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": plan_text}],
        schema=InfographicContent, purpose="T-B2 인포그래픽 정보 추출"
    )
    return result.model_dump()


def render_infographic(category: str, data: dict, run_id: str | None = None) -> dict:
    """카테고리 + 데이터를 받아 인포그래픽 SVG를 렌더링하고 파일로 저장한다.

    category: '원페이지' | '웹개발' | 'AI_API'
    data: {
        "item_name": str,
        "features": list[str],
        "target_users": str,          # 원페이지 전용
        "problem": str, "solution": str,
        "revenue_unit_price": str, "timeline_baseline": str,
        "flow_steps": list[str],      # 웹개발 전용, A→B→C 순서
        "pipeline": {"input": str, "process": str, "output": str},  # AI_API 전용
    }
    run_id: 생략 시 UUID를 생성한다. 기존 시도 ID는 재사용할 수 없다.
    """
    if category not in CATEGORY_TEMPLATE_FILE:
        raise ValueError(
            f"알 수 없는 카테고리: {category!r} (허용값: {sorted(CATEGORY_TEMPLATE_FILE)})"
        )

    item_name = str(data.get("item_name", "")).strip() or "이름 미정 아이템"
    features = [str(f) for f in (data.get("features") or [])]

    body_svg, height = _BODY_BUILDERS[category](data, features)
    alt_text = _build_alt_text(category, item_name, features)

    template = _load_template(CATEGORY_TEMPLATE_FILE[category])
    mapping = {
            "svg_height": str(height),
            "item_name": _esc(_fit(item_name, 30, _W_TITLE)),
            "category_label": CATEGORY_LABEL[category],
            "category_color": CATEGORY_ACCENT[category],
            "color_bg": BRAND_COLORS["bg"],
            "color_primary": BRAND_COLORS["primary"],
            "color_text_muted": BRAND_COLORS["text_muted"],
            "alt_text": _esc(alt_text),
            "body_block": body_svg,
    }
    if category == "원페이지":
        # <title>과 다른 문장이어야 검증 2번이 형식만 통과하지 않는다.
        mapping["desc_text"] = _esc(_build_desc_text(category, item_name, data))
    svg = _substitute(template, mapping)

    run_id = run_id or uuid.uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("시도 ID는 영문/숫자/_/-만 허용합니다")
    out_dir = _OUTPUT_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    # 원페이지는 이 파일이 Prototype.entryFilePath가 되므로 기능정의서 시트 4의
    # "원페이지는 onepage.svg" 표기를 따른다.
    file_path = out_dir / ("onepage.svg" if category == "원페이지" else "infographic.svg")
    with file_path.open("x", encoding="utf-8") as target:
        target.write(svg)

    return {"file_path": str(file_path.resolve()), "alt_text": alt_text, "source_text": svg}
