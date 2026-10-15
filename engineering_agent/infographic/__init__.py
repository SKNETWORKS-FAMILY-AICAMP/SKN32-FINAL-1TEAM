"""T-B2 인포그래픽: 계획서에서 값을 뽑고(content) 템플릿에 채워 저장한다(render).

    style      색 · 카테고리 표기
    layout     글자 폭 · 잘림 · 넘침
    svg_parts  지면 글 조각 · 대체 텍스트 (검증-2가 읽는 data-* 표식)
    bodies     카테고리별 본문
    content    LLM 추출 스키마와 프롬프트
    render     템플릿 채우기 · 파일 저장
"""
from engineering_agent.infographic.content import (
    FeatureDetail,
    InfographicContent,
    generate_infographic_content,
)
from engineering_agent.infographic.layout import estimate_text_width, overflow_fields
from engineering_agent.infographic.render import render_infographic

__all__ = [
    "FeatureDetail", "InfographicContent", "estimate_text_width",
    "generate_infographic_content", "overflow_fields", "render_infographic",
]
