"""T-B2 2단계: 뽑은 값을 템플릿에 채워 SVG를 만들고 시도별 폴더에 저장한다."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from engineering_agent.infographic.style import (
    BRAND_COLORS,
    CATEGORY_ACCENT,
    CATEGORY_LABEL,
    CATEGORY_TEMPLATE_FILE,
)
from engineering_agent.infographic.layout import fit
from engineering_agent.infographic.svg_parts import esc, build_alt_text, build_desc_text
from engineering_agent.infographic import fonts, themes
from engineering_agent.infographic.design_kit import TITLE_SIZE, TITLE_WIDTH
from engineering_agent.infographic.showcase import build_showcase
from engineering_agent.infographic.composer import compose


# 템플릿과 산출물 폴더는 패키지 밖(engineering_agent/)에 그대로 둔다 —
# output/은 .gitignore 규칙이 이 경로를 가리킨다.
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "infographic_templates"
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


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

    # 모델이 블록 구성(layout)을 골랐으면 그 구성으로 조립하고, 없으면 기본 showcase.
    variant = data.get("design_variant") or ("composed" if data.get("layout") else "showcase")
    if variant == "composed":
        body_svg, height = compose(category, data, features)
        title_block = ""
    elif variant == "showcase":
        body_svg, height = build_showcase(category, data, features)
        title_block = ""  # Showcase owns its centered title and hero composition.
    else:
        raise ValueError(f"알 수 없는 디자인 변형: {variant!r}")
    alt_text = build_alt_text(category, item_name, features)

    template = _load_template(CATEGORY_TEMPLATE_FILE[category])
    mapping = {
            "svg_height": str(height),
            "item_name": esc(fit(item_name, TITLE_SIZE, TITLE_WIDTH)),
            "category_label": CATEGORY_LABEL[category],
            "category_color": CATEGORY_ACCENT[category],
            "color_bg": BRAND_COLORS["bg"],
            "color_primary": BRAND_COLORS["primary"],
            "color_text_muted": BRAND_COLORS["text_muted"],
            "alt_text": esc(alt_text),
            "body_block": body_svg,
            "title_block": title_block,
    }
    if category == "원페이지":
        # <title>과 다른 문장이어야 검증 2번이 형식만 통과하지 않는다.
        mapping["desc_text"] = esc(build_desc_text(category, item_name, data))
    svg = _substitute(template, mapping)
    # 사업 분야에 맞춰 지면 색을 바꾼다. 같은 아이템이면 같은 색.
    svg = themes.apply(svg, themes.pick(data))
    # 디자인 글꼴(미리 잘라 둔 Pretendard)을 넣는다. 글자는 그대로 <text>다.
    svg = fonts.embed(svg)

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
