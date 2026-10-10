"""T-V1 사업계획서 검증 — 담당자 F19(validate_section) + 파이프라인 보정 + 채점(score_section) (spec 4.9).

- 항목마다 담당자 validate_section(규칙 검사, 필요할 때만 LLM 의미 검증 F19)과 담당자 파이프라인의 보정
  (_reconcile_validation · _remove_roadmap_deadline_warnings · _check_agreement_table_overrun · 초기창업 3.5.3 단계 미지정 처리)을
  그대로 적용한 뒤 score_section으로 항목 점수(0 ~ 100)를 낸다. 담당자 결과의 기록용 칸(model · responseId · usage)은 버린다.
- F19에 넘기는 항목 내용: 본문 = sectionOutputs, 표 = tableOutputs, 그림 = diagramOutputs. 근거는 담당자 section_source.
- 입력 없음: 표의 사용자 원본 행이 비었거나 예비창업 사업비에 단계 미지정 행이 있으면 inputMissing 참 · status warning,
  issue는 warning '입력 확인 필요 — <사업비 집행계획 | 추진 일정>'으로 바꾼다.
- 점수: D = 입력 docLayerMax(설정 사본 scoring.docLayerMax, 비면 설정 기본값), N = 항목 수. 항목 점수 = 담당자 점수 × D ÷ 100 ÷ N
  (소수 둘째 자리 반올림, 잠정), 문서층 총점 = 반올림한 항목 점수의 합(더 반올림하지 않음). varianceFlag는 늘 거짓.
- 목표 항목(ReworkInput.targetItems)이 있으면 그 항목만 다시 검증하고 나머지는 baseSectionResults를 그대로 가져온다(verifiedRef도
  원래 값). 총점은 합친 결과 전체로 다시 낸다. 동시 4개(spec 4.14), 재개 때 받은 판정(키 = 항목 번호)은 다시 하지 않는다.
- T-V1은 지시문을 받지 않는다 — 담당자 호출 수단의 지시문은 None이다.
"""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from typing import Any

from ...contracts.tasks import TV1In, TV1Out
from ...models import DocScore, DocScoreItem, SectionResult
from ...orchestrator.settings import ScoringSettings
from ...orchestrator.tools import Tools
from . import inputs as ins
from .agent_strategy.functions import python_functions as py
from .agent_strategy.runtime.pipeline import (
    _check_agreement_table_overrun, _reconcile_validation, _remove_roadmap_deadline_warnings, section_source,
)
from .agent_validation_1 import validation_1  # noqa: F401 — 불러올 때 자료를 읽어 둔다(실행 중 파일 읽기 방지)
from .agent_validation_1.scoring import score_section
from .calls import partner_call
from .common import (
    TV1_CONCURRENCY, canonical_of, form_items, gather, kind_of, made_items, original_of, research_of,
    section_specs, spec_for, targets_of,
)
from .contract import SCORE_POLICY_VERSION

DEFAULT_REF = "planDoc"                    # 검증한 계획서 버전을 받지 못했을 때의 verifiedRef
NO_DEDUCTION = "감점 없음"                  # 항목 점수 comment — 감점 사유가 없을 때
INPUT_MISSING = "입력 확인 필요 — {label}"  # 입력 없음 warning (잠정 문구, spec 4.9)
SCORE_DIGITS = 2                           # 항목 점수 소수 자리 (잠정)
_STATUSES = ("pass", "warning", "fail")


def doc_layer_max(inp: TV1In) -> float:
    return float(inp.doc_layer_max) if inp.doc_layer_max is not None else float(ScoringSettings().doc_layer_max)


def _input_missing(validation: dict[str, Any], label: str) -> dict[str, Any]:
    """입력 없음 — issue를 버리고 warning '입력 확인 필요 — …'를 앞에 두고 status warning (spec 4.9)."""
    note = INPUT_MISSING.format(label=label)
    out = dict(validation)
    out["issues"] = []
    out["warnings"] = [note] + [w for w in validation.get("warnings", []) if w != note]
    out["status"] = "warning"
    return out


def _early_unassigned_budget(validation: dict[str, Any], kind: str, spec: dict[str, Any],
                             content: dict[str, Any]) -> dict[str, Any]:
    """초기창업 3.5.3 단계 미지정 원본 사업비 처리 — 담당자 run_pipeline 그대로."""
    tables = content.get("tables") or []
    if (kind == ins.EARLY_STARTUP and spec.get("functionId") == "F17" and spec.get("sectionId") == "3.5.3"
            and tables and isinstance(tables[0], dict) and tables[0].get("rows") == []
            and (tables[0].get("rules") or {}).get("unassignedOriginalRows")):
        validation["issues"] = [i for i in validation.get("issues", []) if "필수 표" not in str(i) and "예산" not in str(i)]
        validation.setdefault("warnings", []).append("단계 미지정 원본 사업비가 보존되어 단계 확정이 필요함")
        validation["status"] = "warning" if not validation.get("issues") else validation.get("status", "fail")
    return validation


def run_tv1(inp: TV1In, tools: Tools) -> TV1Out:
    kind = kind_of(inp.strategy_data, inp.company_info.applicant_type)
    specs = section_specs(kind)
    items = form_items(inp.form_spec, kind)
    codes = [code for code, _, _, _ in items]
    meta = {code: (tag, k) for code, _, tag, k in items}
    contents = {"section": inp.section_outputs, "table": inp.table_outputs, "image": inp.diagram_outputs}
    missing = ins.missing_inputs(inp.company_info, kind, [c for c, _, _, k in items if k == "table"])
    ref = inp.plan_doc_ref or DEFAULT_REF
    targets = targets_of(inp.rework_input)
    base = {r.section_code: r for r in inp.base_section_results or []}
    made = made_items(codes, targets, lambda c: c in base)
    canonical = canonical_of(inp.strategy_data, inp.market_strategy_data)
    original = original_of(inp.strategy_data, inp.feature_list)
    research = research_of(inp.strategy_data)

    received: dict[str, SectionResult] = {}
    for code in made:
        try:
            received[code] = SectionResult.model_validate(json.loads(inp.prior_results[code]))
        except (KeyError, ValueError, TypeError):
            continue

    def one(code: str) -> SectionResult:
        tag, k = meta[code]
        spec = spec_for(specs, code)
        content = copy.deepcopy((contents.get(k) or {}).get(code) or {})
        source = section_source(spec, canonical, original, research)
        with partner_call(tools.for_item(code), None):
            validation = py.validate_section(section_spec=spec, content=content, source_data=source)
        validation = _reconcile_validation(spec, content, validation)
        validation = _remove_roadmap_deadline_warnings(validation, source, kind)
        validation = _check_agreement_table_overrun(validation, spec, content, source, kind)
        validation = _early_unassigned_budget(validation, kind, spec, content)
        if code in missing:
            validation = _input_missing(validation, missing[code])
        evaluation = score_section(spec, content, validation, kind, source)
        status = validation.get("status")
        return SectionResult(
            section_code=code, tag=tag, content_type=k, status=status if status in _STATUSES else "fail",
            issues=[str(x) for x in validation.get("issues", [])],
            warnings=[str(x) for x in validation.get("warnings", [])],
            needs_user_confirmation=[str(x) for x in validation.get("needsUserConfirmation", [])],
            input_missing=code in missing, score=float(evaluation["score"]),
            deductions=[str(d.get("reason", "")) for d in evaluation.get("deductions", []) if isinstance(d, dict)],
            verified_ref=ref)

    todo = [c for c in made if c not in received]
    got = gather(todo, one, TV1_CONCURRENCY, {c: inp.prior_results[c] for c in received},
                 encode_value=lambda r: json.dumps(r.dump(), ensure_ascii=False), name="tv1")
    results = [got[c] if c in got else received[c] if c in received else base[c] for c in codes]

    d = doc_layer_max(inp)
    n = max(len(results), 1)
    score_items = [DocScoreItem(item_code=r.section_code, score=round(r.score * d / 100 / n, SCORE_DIGITS),
                                max_score=d / n, evidence_locator=r.section_code,
                                comment=" · ".join(x for x in r.deductions if x) or NO_DEDUCTION) for r in results]
    total = float(sum((Decimal(str(i.score)) for i in score_items), Decimal(0)))
    doc_score = DocScore(total=total, items=score_items)
    return TV1Out(doc_score=doc_score, items=score_items, variance_flag=False, section_results=results,
                  score_policy_version=SCORE_POLICY_VERSION)
