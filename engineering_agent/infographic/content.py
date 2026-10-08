"""T-B2 1단계: 계획서 본문에서 인포그래픽에 넣을 값을 LLM으로 뽑는다."""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from engineering_agent.infographic.layout import (
    FLOW_LINES,
    OP_DETAIL_LINES,
    OP_DETAIL_SIZE,
    OP_FOOT_LINES,
    OP_VALUE_LINES,
    PIPE_LINES,
    W_AI_PIPELINE,
    W_OP_FOOT,
    W_OP_TARGET,
    W_OP_VALUE,
    feature_tile_width,
    flow_text_width,
)
from engineering_agent.infographic.compose_guide import COMPOSE_GUIDE
from engineering_agent.infographic.style import CATEGORY_TEMPLATE_FILE


# 카테고리별로 render_infographic()의 body 빌더가 실제로 소비하는 필드만 요구한다 —
# 스키마를 넓게 잡으면 LLM이 안 쓰이는 필드까지 채우려다 없는 사실을 지어낼 여지가 생긴다.
_SCHEMA_HINTS: dict[str, str] = {
    "원페이지": (
        '{"item_name": str, "features": [str, ...], "target_users": str, '
        '"problem": str, "solution": str, "revenue_unit_price": str, '
        '"timeline_baseline": str, '
        '"feature_details": [{"name": str, "detail": str}, ...], '
        '"key_metrics": [{"value": str, "label": str}, ...], "solution_steps": [str, ...]}'
    ),
    "웹개발": ('{"item_name": str, "features": [str, ...], "flow_steps": [str, ...], '
             '"problem": str, "solution": str, "revenue_unit_price": str, "timeline_baseline": str, '
             '"key_metrics": [{"value": str, "label": str}, ...], '
             '"feature_details": [{"name": str, "detail": str}, ...]}'),
    "AI_API": (
        '{"item_name": str, "features": [str, ...], '
        '"pipeline": {"input": str, "process": str, "output": str}, '
        '"problem": str, "solution": str, "revenue_unit_price": str, "timeline_baseline": str, '
        '"key_metrics": [{"value": str, "label": str}, ...], '
        '"feature_details": [{"name": str, "detail": str}, ...]}'
    ),
}


def _max_chars(width: float, font_size: float) -> int:
    """한글 기준으로 그 자리에 잘리지 않고 들어가는 글자 수(여유 10%)."""
    return int(width / font_size * 0.9)


# 값 자리의 글자 수 한도. layout._slots()의 폭 · 글자 크기와 같은 값에서 나온다 — 한도를
# 알려주지 않으면 모델이 문장을 통째로 옮겨 넣어 지면 폭을 넘기고 잘린다.
_COMMON_LEN = ("problem · solution 각 40자 이내, revenue_unit_price 40자 이내, timeline_baseline 100자 이내"
               "(계획서의 추진 단계를 빠짐없이 '날짜(기간) 할 일' 짝으로 쉼표로 이어 적어라)")
_LENGTH_HINTS: dict[str, str] = {
    "원페이지": (f"target_users {_max_chars(W_OP_TARGET, 15)}자 이내, problem · solution 각 "
               f"{_max_chars(W_OP_VALUE, 15) * OP_VALUE_LINES}자 이내, "
               f"revenue_unit_price {_max_chars(W_OP_FOOT, 15) * OP_FOOT_LINES}자 이내, "
               "timeline_baseline 100자 이내. timeline_baseline에는 계획서의 추진 단계를 빠짐없이 모두 "
               "'2026년 12월~2027년 3월 개발, 2027년 4월 1일 정식 출시, 2027년 5월~12월 확산'처럼 "
               "'날짜(기간) 할 일' 짝을 쉼표로 이어 적어라. 할 일은 한 단계당 8자 안팎"),
    "웹개발": (f"flow_steps는 사용자가 화면에서 하는 행동 순서 3~5개, 각 "
             f"{_max_chars(flow_text_width(5), 15) * FLOW_LINES}자 이내 (예: '메뉴 고르기'). " + _COMMON_LEN),
    "AI_API": (f"pipeline의 input · process · output은 각각 "
               f"{_max_chars(W_AI_PIPELINE, 15) * PIPE_LINES}자 이내. " + _COMMON_LEN),
}


def _detail_chars(category: str, feature_count: int = 4) -> int:
    """기능 설명 글자 수 한도. 실제 기능 수의 타일 폭 기준(모르면 가장 좁은 4칸) — 세 카테고리 공용.
    가장 좁은 칸(44자)을 모든 계획서에 주었더니, 기능이 적어 칸이 넓은데도 설명을 짧게 줄여 계획서의 요소가 빠졌다."""
    return _max_chars(feature_tile_width(max(1, feature_count)) - 24, OP_DETAIL_SIZE) * OP_DETAIL_LINES


class FeatureDetail(BaseModel):
    name: str
    detail: str = ""


class KeyMetric(BaseModel):
    value: str
    label: str = ""
    # 전후 막대(metrics · bars)용 이전 값. 계획서에 '18%에서 9%로'처럼 둘 다 있을 때만.
    before: str = ""


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
    solution_steps: list[str] = Field(default_factory=list, max_length=4)
    # ── 블록 구성(composer.py) ── 모델이 고른 지면 구성과 블록별 짧은 구절.
    layout: list[dict] = Field(default_factory=list)
    outcome: str = ""
    before_after: list[dict] = Field(default_factory=list)
    market_levels: list[dict] = Field(default_factory=list)
    comparison: dict = Field(default_factory=dict)
    revenue_flow: dict = Field(default_factory=dict)
    effects: list[dict] = Field(default_factory=list)
    tagline: str = ""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _format_error(message: str) -> Exception:
    """tools가 재시도 대상으로 인식하는 FormatError. import을 실패 시점으로 미룬다
    (builder_html._format_error와 같은 이유)."""
    from sbrain.orchestrator.errors import FormatError

    return FormatError(message)


_LIST_KEYS = ("features", "flow_steps", "feature_details", "key_metrics", "solution_steps", "layout",
              "before_after", "market_levels", "effects")
_DICT_KEYS = ("pipeline", "comparison", "revenue_flow")


def _tidy(obj):
    """모델이 자주 틀리는 모양을 스키마 검사 전에 바로잡는다. 내용은 바꾸지 않는다 —
    잘못된 모양의 선택 항목은 비우고, 절차는 네 단계까지만 쓴다."""
    if not isinstance(obj, dict):
        return obj
    for key in _LIST_KEYS:
        if key in obj and not isinstance(obj[key], list):
            obj[key] = []
    for key in _DICT_KEYS:
        if key in obj and not isinstance(obj[key], dict):
            obj[key] = {}
    for key in ("before_after", "market_levels", "effects", "layout", "feature_details"):
        if key in obj:
            obj[key] = [row for row in obj[key] if isinstance(row, dict)]
    if "key_metrics" in obj:
        obj["key_metrics"] = [m for m in obj["key_metrics"]
                              if isinstance(m, dict) and str(m.get("value", "")).strip()]
        for m in obj["key_metrics"]:
            m.update({k: str(v) for k, v in m.items() if not isinstance(v, str)})
    if "solution_steps" in obj:
        obj["solution_steps"] = [str(s) for s in obj["solution_steps"]][:4]
    if isinstance(obj.get("pipeline"), dict):
        obj["pipeline"] = {k: str(v) for k, v in obj["pipeline"].items()}
    for key in ("problem", "solution", "outcome", "tagline", "target_users",
                "revenue_unit_price", "timeline_baseline"):
        if key in obj and not isinstance(obj[key], str):
            obj[key] = str(obj[key]) if obj[key] is not None else ""
    return obj


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
        return InfographicContent.model_validate(_tidy(json.loads(raw[start:end + 1])))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise _format_error(f"T-B2 응답 JSON을 읽을 수 없음: {type(exc).__name__}") from None


def generate_infographic_content(category: str, plan_text: str, tools,
                                 feature_notes: dict[str, str] | None = None) -> dict:
    """T-B2 1단계: 사업계획서 본문(작성 Agent 산출물)에서 인포그래픽 데이터를 추출한다.

    반환값은 render_infographic()의 data 인자로 그대로 넘길 수 있는 형태다.
    렌더러가 소비하는 사실·수치·절차만 추출한다. 없는 내용은 채우지 않는다.
    추출 결과의 누락·수치·길이는 Task의 자체 검사와 검증-2에서 따로 검사한다.
    feature_notes: 기능마다 계획서가 그 기능을 설명한 줄(builder_html.feature_notes). 있으면 기능 설명을 이 줄에서
    줄여 쓰게 한다 — 검증-2가 원페이지 기능 설명을 이 줄의 요소로 대조한다.
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
    notes = {f: n for f, n in (feature_notes or {}).items() if n.strip()}
    limit = _detail_chars(category, len(feature_notes) if feature_notes else 4)
    system_prompt += (
        "\n5. feature_details에는 '기능 목록'의 기능마다 하나씩, name에 기능명을 그대로 "
        "쓰고 detail에 그 기능이 무엇을 하는지 적어라. "
        + ("아래 '기능별 계획서 설명'이 있는 기능은 그 설명을 줄여 쓴다: 무엇을 받거나 다루는지 · 무엇으로 하는지 · "
           "어떤 결과를 내는지 같은 핵심 요소와 원문 낱말은 빼지 말고, 꾸밈말 · 배경 설명 · 되풀이부터 뺀다. "
           if notes else "본문에서 찾은 한 문장을 원문 낱말 그대로 적는다. ")
        + f"{limit}자를 넘기지 마라. "
        "기능명을 되풀이하지 말고, 본문이 그 기능을 설명하지 않으면 detail을 빈 문자열로 남겨라."
    )
    if notes:
        # 검증-2는 원페이지 기능 설명을 이 줄의 요소(최대 5개)가 있는지로 대조한다. 본문 전체에서 모델이 스스로
        # 고르게 하면 실행마다 다른 줄 · 다른 요소를 골라 같은 계획서의 대조 점수가 7.03 ~ 10.78로 흔들렸다(실측).
        system_prompt += "\n[기능별 계획서 설명]\n" + "\n".join(f"- {f}: {n}" for f, n in notes.items())
    system_prompt += (
            "\n6. key_metrics에는 본문에서 사업을 가장 잘 보여주는 숫자를 최대 3개 골라라. "
            "value는 본문에 적힌 숫자와 단위를 그대로(예: '18%', '12분', '29,000원'), "
            "label은 그 숫자가 무엇인지 14자 이내로 적어라"
            "(예: '반찬 폐기율'). 본문에 숫자가 없으면 빈 리스트로 남겨라."
            "\n7. solution은 기능 이름을 나열하지 말고, 이 사업이 problem을 어떤 방식으로 "
            "푸는지를 한 구절로 적어라(형식 예: 'A를 미리 받아 B를 줄인다'). 기능 목록은 지면에 "
            "따로 들어간다."
    )
    if category == "원페이지":
        system_prompt += (
            "\n8. solution_steps는 본문에 명시된 서비스 제공 또는 운영 절차가 있을 때만 "
            "2~4개 순서대로 적어라. 각 단계는 행위와 대상을 짝지은 짧은 구절로, "
            f"{_max_chars(flow_text_width(4), 15) * FLOW_LINES}자 이내로 적어라. "
            "순서가 명시되지 않으면 빈 리스트로 남겨라. 기능 목록을 임의로 절차로 바꾸지 마라."
        )
    # 지면 구성은 코드가 정하므로(design.py) 프롬프트에 단계 구역이 보이지 않는다. 예전에는 웹개발 뼈대에 단계 구역을
    # 늘 넣어 모델이 flow_steps를 채웠는데, 빼고 나니 비워 '사용자 화면 흐름 누락'이 났다(실측). 필수 값임을 적는다.
    if category == "웹개발":
        system_prompt += (
            "\n8. flow_steps는 반드시 채운다(웹개발 지면의 필수 정보). 사용자가 이 서비스 화면에서 하는 행동을 "
            "순서대로 3~5개, 본문의 기능 · 이용 과정 낱말로 적어라."
        )
    if category == "AI_API":
        system_prompt += (
            "\n8. pipeline의 input · process · output은 반드시 모두 채운다(AI API 지면의 필수 정보). "
            "본문에서 AI가 받는 것 · 하는 일 · 내놓는 것을 찾아 적어라."
        )
    system_prompt += (
        "\n편집 원칙: '혁신적인', '최적의', '차별화된', '스마트한 솔루션'처럼 "
        "구체적 정보를 전달하지 않는 수식어를 덧붙이지 마라. 누가 무엇을 하는지와 "
        "어떤 결과가 나오는지 보여주는 구절을 우선하라. 수치는 목표·현재 실적·문제 현황을 "
        "혼동하지 않도록 label에 본문의 맥락을 보존하라."
    )
    # 지면 재료와 구역 제목. 구성(순서 · 변형 · 폭)은 design.py가 재료를 보고 정한다.
    system_prompt += COMPOSE_GUIDE
    system_prompt += ('\n출력 스키마에 다음 키를 더한다: "layout", "outcome", "before_after", "market_levels", '
                      '"comparison", "revenue_flow", "effects", "tagline" (재료가 없으면 빈 값).')
    result = tools.llm(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": plan_text}],
        parse=parse_content, purpose="T-B2 인포그래픽 정보 추출"
    )
    return result.model_dump()
