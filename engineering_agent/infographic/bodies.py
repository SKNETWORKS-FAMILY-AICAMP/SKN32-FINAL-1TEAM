"""카테고리별 지면 본문(원페이지 · 웹개발 · AI API)을 조립한다."""
from __future__ import annotations

from engineering_agent.infographic.style import BRAND_COLORS, CATEGORY_ACCENT
from engineering_agent.infographic.layout import (
    W_WEBDEV_FEATURE,
    W_WEBDEV_FLOW,
    W_AI_PIPELINE,
    fit,
)
from engineering_agent.infographic.svg_parts import (
    esc,
    section_title,
    EMPTY_VALUE_TEXT,
    value_text,
    feature_bullet_list,
    feature_detail_list,
)


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
        parts.append(section_title(40, y, label))
        parts.append(value_text(40, y + 30, field, str(data.get(field, ""))))
        y += 76
    parts.append(section_title(40, y, "핵심 기능"))
    y += 34
    feature_svg, y = feature_detail_list(40, y, features, data.get("feature_details") or [])
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
    parts.append(section_title(40, y, "핵심 기능"))
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
            f'data-role="value" fill="{BRAND_COLORS["text"]}">{esc(fit(feat, 16, W_WEBDEV_FEATURE))}</text>'
        )
    rows_used = (len(features) + 1) // 2 if features else 0
    y += rows_used * row_h + (30 if features else 34)
    if not features:
        parts.append(
            f'<text x="56" y="{y - 20}" font-size="15" fill="{BRAND_COLORS["text_muted"]}">등록된 기능이 없습니다</text>'
        )

    if flow_steps:
        parts.append(section_title(40, y, "사용자 플로우"))
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
                f'fill="{BRAND_COLORS["text"]}" text-anchor="middle">{esc(fit(step, 15, W_WEBDEV_FLOW))}</text>'
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
        ("input", "입력", str(pipeline.get("input", "")).strip() or EMPTY_VALUE_TEXT),
        ("process", "처리", str(pipeline.get("process", "")).strip() or EMPTY_VALUE_TEXT),
        ("output", "출력", str(pipeline.get("output", "")).strip() or EMPTY_VALUE_TEXT),
    ]
    accent = CATEGORY_ACCENT["AI_API"]

    parts: list[str] = []
    y = 150
    parts.append(section_title(40, y, "처리 파이프라인"))
    y += 44

    box_w, box_h, gap = 220, 120, 60
    total_w = 3 * box_w + 2 * gap
    start_x = (900 - total_w) // 2
    for i, (label_key, label, text) in enumerate(stages):
        bx = start_x + i * (box_w + gap)
        parts.append(
            f'<text x="{bx + box_w / 2}" y="{y}" font-size="14" font-weight="700" data-role="label" fill="{accent}" text-anchor="middle">{esc(label)}</text>'
            f'<rect x="{bx}" y="{y + 14}" width="{box_w}" height="{box_h}" rx="12" '
            f'fill="{BRAND_COLORS["surface"]}" stroke="{accent}" stroke-width="2"/>'
            f'<text x="{bx + box_w / 2}" y="{y + 14 + box_h / 2 + 6}" font-size="15" '
            f'data-field="pipeline.{label_key}" data-role="value" '
            f'fill="{BRAND_COLORS["text"]}" text-anchor="middle">{esc(fit(text, 15, W_AI_PIPELINE))}</text>'
        )
        if i < 2:
            ax1, ax2 = bx + box_w + 10, bx + box_w + gap - 10
            amidy = y + 14 + box_h / 2
            parts.append(
                f'<line x1="{ax1}" y1="{amidy}" x2="{ax2}" y2="{amidy}" '
                f'stroke="{BRAND_COLORS["text_muted"]}" stroke-width="2" marker-end="url(#arrowhead)"/>'
            )
    y += 14 + box_h + 40

    parts.append(section_title(40, y, "핵심 기능"))
    y += 34
    feature_svg, y = feature_bullet_list(40, y, features)
    parts.append(feature_svg)

    y += 30
    return "\n".join(parts), int(y)


BODY_BUILDERS = {
    "원페이지": _build_onepage_body,
    "웹개발": _build_webdev_body,
    "AI_API": _build_ai_api_body,
}
