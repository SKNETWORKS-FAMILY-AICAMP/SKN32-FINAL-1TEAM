"""연결 코드 공통 부품 — 양식 항목 · 담당자 항목 계약 · 문맥 · 목표 항목 · 재개 이어 쓰기 · 동시 호출 (spec 4.7 · 4.13 · 4.14).

- 담당자 함수 결과는 산출물 값 안에만 싣는다. 이 모듈의 예외 메시지에는 항목 번호 · 필드 이름 · 개수만 넣는다.
- 재개 이어 쓰기(4.13): 받은 결과는 '키 → JSON 문자열'(엔진 장치 PARTIAL). 재시도를 다 쓴 호출이 일시 오류면 그때까지
  받은 결과(앞 재개에서 받은 것 + 이번에 받은 것)를 그 예외의 partial에 실어 원래 예외를 다시 올린다 — 받는 것이 아니다.
- 동시 호출(4.14): 표준 라이브러리 스레드 풀. 모두 끝난 뒤 실패를 판단하고 순서는 T-C3와 같다 — ① 재시도 소진이 아닌 예외
  ② 일시가 아닌 재시도 소진 ③ 일시 재시도 소진 + 받은 결과. 여러 개면 키 순서상 앞의 것, 올리는 것은 원래 예외 객체다.
"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

from ...flow.rework_map import section_tag
from ...models import FormSpec, ReworkInput
from ...orchestrator.errors import ToolCallExhausted
from . import contract
from .inputs import EARLY_STARTUP, PRE_STARTUP, document_type

# 동시 호출 수 (사용자 결정 2026-10-10 — 잠정 아님, spec 4.14)
TW1_CONCURRENCY = 4    # 본문 항목
TV1_CONCURRENCY = 4    # 항목 검증
TW2_CONCURRENCY = 2    # 그림 두 개

# strategyData 안의 담당자 canonical 밖 칸 (근거 자료 · 원본 사실 · 울타리 · 문서 유형)
STRATEGY_META_KEYS = ("research", "original_facts", "strategy_limits", "document_type")


class PartnerContractError(ValueError):
    """양식 항목이 담당자 계약에 없음 등 — 메시지에는 개수만."""


# ── 양식 항목 ─────────────────────────────────────────
def form_items(form: FormSpec, kind: str) -> list[tuple[str, str, str | None, str]]:
    """양식의 계획서 항목 (번호, 제목, 태그, 종류) — 양식 순서. 태그 칸이 항목 수와 맞지 않으면 짝짓기 표(rework_map),
    종류 칸이 맞지 않으면 담당자 계약의 contentType으로 채운다."""
    codes, titles = list(form.section_codes), list(form.section_titles)
    specs = section_specs(kind)
    tags = list(form.section_tags) if len(form.section_tags) == len(codes) else [section_tag(c) for c in codes]
    if len(form.section_kinds) == len(codes):
        kinds = list(form.section_kinds)
    else:
        kinds = [str(specs[c]["contentType"]) if c in specs else "section" for c in codes]
    return list(zip(codes, titles, tags, kinds))


def section_specs(kind: str) -> dict[str, dict[str, Any]]:
    """담당자 문서 유형의 항목 계약(번호 → 계약 사본, '_documentType' 붙임)."""
    out: dict[str, dict[str, Any]] = {}
    for spec in contract.document_specs(kind):
        spec["_documentType"] = kind
        out[str(spec["sectionId"])] = spec
    return out


def spec_for(specs: dict[str, dict[str, Any]], code: str) -> dict[str, Any]:
    """그 항목의 계약 사본. 없으면 PartnerContractError(항목 번호는 메시지에 넣지 않는다 — 양식 값)."""
    if code not in specs:
        raise PartnerContractError("양식 항목이 담당자 계약에 없음")
    return copy.deepcopy(specs[code])


def kind_of(strategy_data: dict[str, Any] | None, applicant_type: str | None = None) -> str:
    """담당자 문서 유형 — T-S1이 strategyData에 적은 값, 없으면 신청자 유형으로."""
    value = (strategy_data or {}).get("document_type")
    if value in (PRE_STARTUP, EARLY_STARTUP):
        return str(value)
    return document_type(applicant_type or "")


# ── 담당자 문맥 (F16 · F18 · F19) ─────────────────────────
def canonical_of(strategy_data: dict[str, Any] | None, market_strategy_data: dict[str, Any] | None) -> dict[str, Any]:
    """담당자 canonical — T-S1 결과(web_data ~ feasibility_plan) + T-S2 결과(market_analysis ~ growth_strategy)."""
    sd = strategy_data or {}
    canonical = {k: copy.deepcopy(v) for k, v in sd.items() if k not in STRATEGY_META_KEYS}
    canonical.update(copy.deepcopy(market_strategy_data or {}))
    return canonical


def original_of(strategy_data: dict[str, Any] | None, feature_list: list[str] | None) -> dict[str, Any]:
    """원본 사실(T-S1 original_facts) 사본. 울타리 featureList는 T-S1이 확정한 featureList로 바꾼다 (spec 4.5)."""
    sd = strategy_data or {}
    original = copy.deepcopy(sd.get("original_facts") or {})
    for key in ("item", "period", "team", "resources", "budget", "schedule"):
        original.setdefault(key, {} if key not in ("schedule",) else [])
    limits = dict(original.get("strategy_limits") or sd.get("strategy_limits") or {})
    if feature_list is not None:
        limits["featureList"] = list(feature_list)
    original["strategy_limits"] = limits
    return original


def research_of(strategy_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """근거 자료 목록(sourceRef · domain …) — 담당자 section_source의 research 인자."""
    research = (strategy_data or {}).get("research") or {}
    sources = research.get("sources") if isinstance(research, dict) else None
    return [s for s in (sources or []) if isinstance(s, dict) and "sourceRef" in s and "domain" in s]


# ── 목표 항목 (spec 4.7) ─────────────────────────────────
def targets_of(rework: ReworkInput | None) -> dict[str, list[str]]:
    return dict(rework.target_items) if rework is not None else {}


def retry_instruction(rework: ReworkInput | None) -> str:
    """담당자 retryInstruction — 재작성 지시의 보완 지시(instructionDelta), 재수행이면 빈 문자열."""
    if rework is None or rework.mode != "재작성" or rework.order is None:
        return ""
    return rework.order.instruction_delta


def made_items(codes: Iterable[str], targets: dict[str, list[str]] | set[str], has_base: Callable[[str], bool]) -> list[str]:
    """이번에 만들(검증할) 항목 — 목표 항목이 있으면 그 항목만, 없으면 모두. 직전 결과가 없는 항목은 목표 밖이어도 만든다."""
    return [c for c in codes if not targets or c in targets or not has_base(c)]


def pick(output: dict[str, Any], keys: tuple[str, ...], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """담당자 결과에서 산출물에 싣는 칸만 (기록용 칸 model · responseId · usage · inputChars 등을 버린다, spec 4.17)."""
    base = {"generatedText": "", "facts": [], "sourceRefs": [], "needsUserConfirmation": [], "issues": []}
    base.update(defaults or {})
    return {k: copy.deepcopy(output[k]) if k in output else copy.deepcopy(base.get(k)) for k in keys}


# ── 재개 이어 쓰기 (spec 4.13) ───────────────────────────
def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode(text: Any) -> Any | None:
    """받은 결과 글자 → 값. 읽을 수 없으면 None(그 키는 다시 부른다)."""
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def received_from(prior: dict[str, str], keys: Iterable[str]) -> dict[str, Any]:
    """재개 때 받은 결과 중 이번 키이고 읽을 수 있는 것만 (키 → 값)."""
    out: dict[str, Any] = {}
    for key in keys:
        value = decode(prior.get(key)) if key in prior else None
        if value is not None:
            out[key] = value
    return out


class Steps:
    """차례로 부르는 담당자 함수(T-S1 · T-S2)의 재개 이어 쓰기 — 키(F번호)마다 받은 결과를 쓰고 빠진 것만 부른다."""

    def __init__(self, prior: dict[str, str]) -> None:
        self.prior = dict(prior)
        self.received: dict[str, str] = {}

    def run(self, key: str | None, make: Callable[[], Any]) -> Any:
        """key가 있고 받은 결과가 있으면 그것을, 아니면 make()를 부른다. key가 None이면 받은 결과에 남기지 않는다(자료 검색)."""
        if key is not None and key in self.prior:
            value = decode(self.prior[key])
            if value is not None:
                self.received[key] = self.prior[key]
                return value
        try:
            value = make()
        except ToolCallExhausted as e:
            if e.error_kind == "일시":
                e.partial = {**self.received}   # 내용이라 메시지에는 싣지 않는다 (속성으로만)
            raise
        if key is not None:
            self.received[key] = encode(value)
        return value


def failure(errors: list[BaseException], received: dict[str, str]) -> BaseException:
    """올릴 예외(원래 객체) — ① 재시도 소진이 아닌 예외 ② 일시가 아닌 재시도 소진 ③ 일시 재시도 소진 + 받은 결과."""
    for err in errors:
        if not isinstance(err, ToolCallExhausted):
            return err
    exhausted = [e for e in errors if isinstance(e, ToolCallExhausted)]
    for err in exhausted:
        if err.error_kind != "일시":
            return err
    first = exhausted[0]
    first.partial = dict(received)
    return first


def gather(keys: list[str], one: Callable[[str], Any], workers: int, received: dict[str, str],
           encode_value: Callable[[Any], str] = encode, name: str = "partner") -> dict[str, Any]:
    """keys를 동시에(최대 workers개) one(key)로 부른다. 결과는 키 → 값(끝난 순서와 상관없이 keys 순서).
    one은 스레드 안에서 호출 수단(partner_call)을 스스로 연다. 실패는 모두 끝난 뒤 failure 순서로 올린다."""
    if not keys:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(keys)), thread_name_prefix=name) as pool:
        futures = [(k, pool.submit(one, k)) for k in keys]
    got: dict[str, Any] = {}
    errors: list[BaseException] = []
    for key, fut in futures:
        err = fut.exception()
        if err is None:
            got[key] = fut.result()
        else:
            errors.append(err)
    if errors:
        raise failure(errors, {**received, **{k: encode_value(v) for k, v in got.items()}})
    return got
