"""T-B2 2단계: 뽑은 값을 템플릿에 채워 SVG를 만들고 시도별 폴더에 저장한다.

[S-Brain] 저장하지 않는다 — SVG 글자 · 대체 텍스트 · 파일 이름을 돌려주고, 연결 코드가 tools.files.put으로 넣는다.
템플릿은 불러올 때 읽어 둔 상수(resources)에서 꺼낸다. (시도 ID · 경로 import 삭제 — VENDORED.md)
"""
from __future__ import annotations

from ... import resources as _res   # [S-Brain] 템플릿은 불러올 때 읽어 둔 상수
from .style import (  # [S-Brain] 패키지 상대 import
    BRAND_COLORS,
    CATEGORY_ACCENT,
    CATEGORY_LABEL,
    CATEGORY_TEMPLATE_FILE,
)
from .layout import fit  # [S-Brain] 패키지 상대 import
from .svg_parts import esc, build_alt_text, build_desc_text  # [S-Brain] 패키지 상대 import
from . import fonts, themes  # [S-Brain] 패키지 상대 import
from .design_kit import TITLE_SIZE, TITLE_WIDTH  # [S-Brain] 패키지 상대 import
from .showcase import build_showcase  # [S-Brain] 패키지 상대 import
from .composer import compose  # [S-Brain] 패키지 상대 import


# [S-Brain] 템플릿 폴더(_TEMPLATE_DIR) · 산출물 폴더(_OUTPUT_DIR) 상수 삭제 — 템플릿은 resources 상수, 저장은 연결 코드


def _load_template(filename: str) -> str:
    return _res.template(filename)   # [S-Brain] 실행 중 파일을 읽지 않는다(없으면 FileNotFoundError — 원래와 같음)


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


def render_infographic(category: str, data: dict) -> dict:   # [S-Brain] run_id 인자 삭제(시도 폴더 없음)
    """카테고리 + 데이터를 받아 인포그래픽 SVG를 렌더링하고 파일로 저장한다.

    [S-Brain] 저장하지 않고 {"file_name", "alt_text", "source_text"}를 돌려준다. file_name은 담당자가 저장하던 파일
    이름(원페이지 onepage.svg, 그 밖 infographic.svg) — 연결 코드가 이 이름으로 tools.files.put 한다.

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

    # [S-Brain] 시도 폴더 만들기 · 파일 쓰기 삭제 — 연결 코드가 file_name으로 tools.files.put 한다.
    # 원페이지는 이 파일이 Prototype.entryFilePath가 되므로 기능정의서 시트 4의
    # "원페이지는 onepage.svg" 표기를 따른다.
    file_name = "onepage.svg" if category == "원페이지" else "infographic.svg"   # [S-Brain]

    return {"file_name": file_name, "alt_text": alt_text, "source_text": svg}   # [S-Brain] file_path 대신 file_name
