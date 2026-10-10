"""담당자 결과 → 우리 계약 (spec 4.7 출력 변환). 매핑 · 문장 나누기 · 수치 토큰 규칙은 잠정이다(settings PROVISIONAL).

- 기록용 칸(model · responseId · usage · inputChars · requestedModel · 호출 fallbackReason · 시각)은 산출물에 싣지 않는다 —
  common.pick이 칸을 골라 싣는다(spec 4.17).
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from ...models import ItemSpec, MarketAnalysis, RequirementAnalysis, Sentence, Token
from .inputs import CONFIRM

# 산출물에 싣는 담당자 결과 칸 (spec 4.7)
SECTION_KEYS = ("generatedText", "facts", "sourceRefs", "needsUserConfirmation", "issues")              # F16
IMAGE_SPEC_KEYS = ("nodes", "flowType", "visualStyle", "generatedText", "facts", "sourceRefs", "issues")  # F18 그림 하나
DIAGRAM_OUTPUT_KEYS = ("imageSpecs", "imageTypes", "nodes", "flowType", "visualStyle", "generatedText", "facts",
                       "sourceRefs", "issues")                                                           # 그림 항목
TABLE_KEYS = ("generatedText", "tables", "issues", "tableFallbackUsed", "fallbackReason")                 # F17
TABLE_DEFAULTS = {"tables": [], "tableFallbackUsed": False, "fallbackReason": ""}

# 글자로 요약할 때 건너뛰는 칸 — 출처 · 상태 표시 (잠정)
_SKIP_KEYS = frozenset({"sourceRef", "sourceRefs", "evidenceRefs", "evidence", "status", "confidence", "url",
                        "originalFacts", "functionId", "functionName"})

# 문장 끝 — '다.' · '음.' · '임.' · '함.' · '.' 뒤 공백에서 나눈다. 숫자 뒤 '.'(번호 '1.')에서는 나누지 않는다 (잠정)
_SENTENCE_END = re.compile(r"(?<=[^\d\s]\.)\s+")
# 수치 토큰 — 숫자 + 단위(원 · 억 · 만 · % · 명 · 건 · 개) (잠정, spec 4.7)
_NUMERIC = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:억\s*원|만\s*원|억|만|원|%|명|건|개)")


def sentences(code: str, text: str | None) -> list[Sentence]:
    """본문을 줄과 문장 끝으로 나눈다. sentenceId = s-<항목 번호>-<순번>, paragraphNo = 줄 순번, isTitle 거짓 (잠정)."""
    out: list[Sentence] = []
    paragraph = 0
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        paragraph += 1
        for part in _SENTENCE_END.split(line):
            part = part.strip()
            if part:
                out.append(Sentence(sentence_id=f"s-{code}-{len(out) + 1}", text=part, is_title=False,
                                    paragraph_no=paragraph))
    return out


def text_of(value: Any) -> str:
    """담당자 결과 값을 한 줄 글자로 (사전 · 목록은 값을 ' · ' · '; '로 잇는다, 출처 · 상태 칸 제외)."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return " · ".join(t for k, v in value.items() if k not in _SKIP_KEYS for t in [text_of(v)] if t)
    if isinstance(value, list):
        return "; ".join(t for t in (text_of(v) for v in value) if t)
    return str(value)


def name_of(value: Any) -> str:
    """기능 · 경쟁사 하나의 이름 — 글자면 그대로, 사전이면 name · feature · title 칸, 없으면 요약 글자."""
    if isinstance(value, dict):
        for key in ("name", "feature", "title", "기능", "featureName"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        return text_of(value)
    return text_of(value)


def names(values: Any) -> list[str]:
    """목록의 이름들(빈 이름 · 겹침 제외, 순서 유지)."""
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(n for n in (name_of(v) for v in values) if n))


# ── T-S1 · T-S2 출력 ─────────────────────────────────────
def requirement_analysis(item: ItemSpec, f02: dict[str, Any], features: list[str]) -> RequirementAnalysis:
    """RequirementAnalysis (잠정 매핑): problemStatement = 아이디어 요약, targetCustomer = F02 targetCustomer(없으면 아이템 사양),
    featureList = 확정 featureList, differentiator = F02 differentiation, useCases = F02 deliverables."""
    return RequirementAnalysis(
        problem_statement=item.one_line_summary,
        target_customer=text_of(f02.get("targetCustomer")) or item.target_customer,
        feature_list=list(features),
        differentiator=text_of(f02.get("differentiation")) or CONFIRM,
        use_cases=names(f02.get("deliverables")))


def market_analysis(f03: dict[str, Any], f04: dict[str, Any], f12: dict[str, Any]) -> MarketAnalysis:
    """MarketAnalysis (잠정 매핑): marketDefinition = F03 marketNeed · marketTrend 요약, marketSize = [](담당자 F03이 수치 시장
    규모를 내지 않음), competitors = F04 competitors[].name, positioning = F12 competition · entry 요약."""
    definition = " / ".join(t for t in (text_of(f03.get("marketNeed")), text_of(f03.get("marketTrend"))) if t)
    positioning = " / ".join(t for t in (text_of(f12.get("competition")), text_of(f12.get("entry"))) if t)
    return MarketAnalysis(market_definition=definition or CONFIRM, market_size=[],
                          competitors=names(f04.get("competitors")), positioning=positioning or CONFIRM)


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in _SKIP_KEYS:
                yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def numeric_tokens(*values: Any) -> list[Token]:
    """결과 글자에서 숫자 + 단위 토큰을 뽑는다(type 수치금액, 같은 값은 개수로, 처음 나온 순서) — 잠정 규칙."""
    counts: dict[str, int] = {}
    for value in values:
        for text in _strings(value):
            for m in _NUMERIC.findall(text):
                token = re.sub(r"\s+", "", m)
                counts[token] = counts.get(token, 0) + 1
    return [Token(type="수치금액", value=v, count=n) for v, n in counts.items()]
