"""T-B2 1단계: 계획서 본문에서 인포그래픽에 넣을 값을 LLM으로 뽑는다."""
from __future__ import annotations

from pydantic import BaseModel, Field

from engineering_agent.infographic.style import CATEGORY_TEMPLATE_FILE


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
