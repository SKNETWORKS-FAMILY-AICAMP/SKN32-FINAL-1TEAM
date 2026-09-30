"""T-B2 1단계: 계획서 본문에서 인포그래픽에 넣을 값을 LLM으로 뽑는다."""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from engineering_agent.infographic.layout import (
    FLOW_LINES,
    ONEPAGE_DETAIL_LINES,
    ONEPAGE_FOOT_LINES,
    ONEPAGE_VALUE_LINES,
    PIPE_LINES,
    W_AI_PIPELINE,
    W_FEATURE_DETAIL,
    W_METRIC_LABEL,
    W_ONEPAGE_TARGET,
    W_ONEPAGE_VALUE,
    W_WEBDEV_FLOW,
)
from engineering_agent.infographic.style import CATEGORY_TEMPLATE_FILE


# 카테고리별로 render_infographic()의 body 빌더가 실제로 소비하는 필드만 요구한다 —
# 스키마를 넓게 잡으면 LLM이 안 쓰이는 필드까지 채우려다 없는 사실을 지어낼 여지가 생긴다.
_SCHEMA_HINTS: dict[str, str] = {
    "원페이지": (
        '{"item_name": str, "features": [str, ...], "target_users": str, '
        '"problem": str, "solution": str, "revenue_unit_price": str, '
        '"timeline_baseline": str, '
        '"feature_details": [{"name": str, "detail": str}, ...], '
        '"key_metrics": [{"value": str, "label": str}, ...]}'
    ),
    "웹개발": ('{"item_name": str, "features": [str, ...], "flow_steps": [str, ...], '
             '"feature_details": [{"name": str, "detail": str}, ...]}'),
    "AI_API": (
        '{"item_name": str, "features": [str, ...], '
        '"pipeline": {"input": str, "process": str, "output": str}, '
        '"feature_details": [{"name": str, "detail": str}, ...]}'
    ),
}


def _max_chars(width: float, font_size: float) -> int:
    """한글 기준으로 그 자리에 잘리지 않고 들어가는 글자 수(여유 10%)."""
    return int(width / font_size * 0.9)


# 값 자리의 글자 수 한도. layout._slots()의 폭 · 글자 크기와 같은 값에서 나온다 — 한도를
# 알려주지 않으면 모델이 문장을 통째로 옮겨 넣어 지면 폭을 넘기고 잘린다.
_LENGTH_HINTS: dict[str, str] = {
    "원페이지": (f"target_users {_max_chars(W_ONEPAGE_TARGET, 15)}자 이내, problem · solution 각 "
               f"{_max_chars(W_ONEPAGE_VALUE, 15) * ONEPAGE_VALUE_LINES}자 이내, "
               f"revenue_unit_price · timeline_baseline 각 "
               f"{_max_chars(W_ONEPAGE_VALUE, 15) * ONEPAGE_FOOT_LINES}자 이내"),
    "웹개발": (f"flow_steps는 사용자가 화면에서 하는 행동 순서 3~5개, 각 "
             f"{_max_chars(W_WEBDEV_FLOW, 15) * FLOW_LINES}자 이내 (예: '메뉴 고르기')"),
    "AI_API": (f"pipeline의 input · process · output은 각각 "
               f"{_max_chars(W_AI_PIPELINE, 15) * PIPE_LINES}자 이내"),
}


class FeatureDetail(BaseModel):
    name: str
    detail: str = ""


class KeyMetric(BaseModel):
    value: str
    label: str = ""


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
    # 원페이지 전용. 지면 위쪽 큰 숫자 카드. 계획서에 적힌 숫자만 — T-B2 자체 검사와
    # 검증-2 계획서 대조가 둘 다 계획서에 없는 숫자를 잡는다.
    key_metrics: list[KeyMetric] = Field(default_factory=list)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _format_error(message: str) -> Exception:
    """tools가 재시도 대상으로 인식하는 FormatError. import을 실패 시점으로 미룬다
    (builder_html._format_error와 같은 이유)."""
    from sbrain.orchestrator.errors import FormatError

    return FormatError(message)


def parse_content(text) -> InfographicContent:
    """LLM 응답에서 JSON 객체를 꺼내 검사한다.

    tools.llm에 schema=를 넘기면 tools가 응답 전체를 순수 JSON으로 검사해서, 모델이
    ```json 코드블록이나 앞뒤 설명을 붙이면 형식 오류로 재시도하다 실패한다. 호출처가
    JSON 모드를 켜는지와 상관없이 산출물이 나오도록 여기서 감싼 것을 벗긴다. 그래도
    읽을 수 없으면 FormatError로 tools의 재시도 경로를 탄다.
    """
    if isinstance(text, InfographicContent):
        return text
    raw = str(text or "").strip()
    fenced = _FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise _format_error("T-B2 응답에 JSON 객체가 없음")
    try:
        return InfographicContent.model_validate(json.loads(raw[start:end + 1]))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise _format_error(f"T-B2 응답 JSON을 읽을 수 없음: {type(exc).__name__}") from None


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
        "2. 다른 설명 없이 JSON 객체 하나만 출력하라. 값은 원문 낱말로 쓰고 없으면 빈 문자열로 남겨라.\n"
        f"3. 출력 스키마: {_SCHEMA_HINTS[category]}\n"
        f"4. 길이: {_LENGTH_HINTS[category]}. 문장을 통째로 옮기거나 여러 문장을 이어 붙이지 "
        "말고 핵심만 줄여라. 줄바꿈을 넣지 마라. 줄일 때도 원문에 없는 낱말·숫자를 보태지 마라."
    )
    system_prompt += (
        "\n5. feature_details에는 '기능 목록'의 기능마다 하나씩, name에 기능명을 그대로 "
        "쓰고 detail에 그 기능이 무엇을 하는지 본문에서 찾은 한 문장을 원문 낱말 그대로 "
        f"적어라. {_max_chars(W_FEATURE_DETAIL, 14) * ONEPAGE_DETAIL_LINES}자를 넘기지 마라. "
        "기능명을 되풀이하지 말고, 본문이 그 기능을 설명하지 않으면 detail을 빈 문자열로 남겨라."
    )
    if category == "원페이지":
        system_prompt += (
            "\n6. key_metrics에는 본문에서 사업을 가장 잘 보여주는 숫자를 최대 3개 골라라. "
            "value는 본문에 적힌 숫자와 단위를 그대로(예: '18%', '12분', '29,000원'), "
            f"label은 그 숫자가 무엇인지 {_max_chars(W_METRIC_LABEL, 13)}자 이내로 적어라"
            "(예: '반찬 폐기율'). 본문에 숫자가 없으면 빈 리스트로 남겨라."
        )
    result = tools.llm(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": plan_text}],
        parse=parse_content, purpose="T-B2 인포그래픽 정보 추출"
    )
    return result.model_dump()
