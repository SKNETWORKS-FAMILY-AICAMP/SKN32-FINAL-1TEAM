"""판정 G-02a(문서 평가) · G-02b(종합 평가) — 조율 Agent의 규칙 단계 (기준 문서 시트 2 r17 · r20, 시트 5 R-6 · 0024).

규칙 단계라 tools를 받지 않는다(LLM 없음). 함수 모양은 run(inp) -> 출력.

- 전후 비교 · 되돌리기는 하지 않는다. Orchestrator가 넘긴 비교 결과(cycleInfo)를 점수 보고서에 담기만 한다(경계).
- 흐름을 가르는 값은 필드로만 읽는다(status · inputMissing · gateFailures · missingFeatures 등) — 문구로 가르지 않는다.
- 계획서 묶음 후보(doc_candidates, business-rules 19.7): 묶음 · 항목은 항목별 재작성 묶음 표(flow/rework_map)로 가른다.
  1. 묶음마다 그 묶음 항목 중 fail · warning이고 입력 없음이 아닌 항목이 있으면 후보 — Task는 그 묶음 첫 항목 종류의 Task,
     사유 · 보완 지시는 '<항목 번호> <issues · warnings>' 줄을 이은 것.
  2. 문서층 표시 점수가 기준 미만인데 1의 후보가 없으면 묶음 모두가 후보(사유 = 판정 지시가 없는 묶음의 고정 문구).
  3. 기회를 다 쓴 묶음도 그대로 넣는다(웹이 고를 수 없게 표시하고 Orchestrator도 거절한다).
- 산출물층 재작성 지시(artifact_orders, business-rules 8.7): 다시 돌릴 Task · 사유는 공용 규칙 artifact_rework_reasons 그대로.
  산출물 종류는 G-02b 입력 확장 category(실행 건 카테고리)로 정한다 — 원페이지 → svg-onepage, 그 밖 → html.
- 다음 동작: 표시 점수가 기준 이상이면 진행가능, 미만이면 재작성권유, 미만인데 후보 묶음의 남은 기회가 모두 0이면 상한도달.
  묶음의 남은 기회 = 재작성 사용 기록(reworkUsage)의 remaining, 기록이 없으면(아직 쓰지 않음) 설정 사본의 rework.perBundle.
- 배점(D · C · P)은 그 실행 건 설정 사본(settingsSnapshot)에서 읽고 환산은 flow/score_scale 한 곳에서 한다. 배점 0은 0 그대로다
  (D = 0이면 문서층 표시 점수 0 — 나눗셈 오류만 막는다 D12).
- G-02a: 표시 점수 = 문서층 total ÷ D × 100(소수 첫째 자리). 점수 보고서 환산 칸은 docLayerMax만.
- G-02b: 총점 = 문서층 total + 산출물층 환산(소수 첫째 자리). 점수 보고서에 환산 칸(층 · 만점 · 코드 점검 항목 줄)을 싣고
  artifactScore(검증-2 원점수)는 그대로 싣는다. reworkDiff의 산출물층 전후 요약은 환산 값 / C + P.
  E-G2-UNREACHABLE(R-6 ②): 문서층 total + (C + P) < 기준이면 notices에 안내 — 계획서 묶음 중 남은 기회가 있는 묶음이 있으면
  첫 문구, 없으면 둘째 문구. 버튼 · 요청을 막지 않는다.
- 안내(notices): G-02a는 확정 동작(checks의 finalAction) + '입력 확인 필요'(입력 없음 항목이 있으면), G-02b는 '입력 확인 필요' +
  E-G2-UNREACHABLE.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...contracts.tasks import G02aIn, G02aOut, G02bIn, G02bOut
from ...flow.rework_map import (
    KIND_TASK, REWORK_DEFAULT_REASON, TASK_BUNDLE, artifact_rework_reasons, document_bundles, order_bundles,
    section_bundle,
)
from ...flow.score_scale import ScoreMaxes, display_score, scale_artifact, scaled_report_fields, score_maxes
from ...models import ArtifactScore, BundleUsage, ReworkDiff, ReworkOrder, ScoreReport, SectionResult
from ...orchestrator.errors import UNREACHABLE_NO_DOC_CHANCE, message
from ...orchestrator.settings import ReworkSettings

# 입력 없음 항목이 있을 때 점수 보고서 notices에 더하는 안내 (잠정 문구, business-rules 19.7)
INPUT_MISSING_NOTICE = "입력 확인 필요 — 사업비 집행계획 · 추진 일정을 입력하면 해당 표가 채워집니다."
ONEPAGE_CATEGORY = "원페이지"


def prototype_kind(category: str | None) -> str:
    """실행 건 카테고리 → 산출물 종류 (원페이지 → svg-onepage, 그 밖 → html)."""
    return "svg-onepage" if category == ONEPAGE_CATEGORY else "html"


def per_bundle(snapshot: Mapping[str, Any] | None) -> int:
    """설정 사본의 묶음별 재작성 횟수(rework.perBundle) — 칸이 없거나 숫자가 아니면 설정 기본값."""
    rework = snapshot.get("rework") if isinstance(snapshot, Mapping) else None
    value = rework.get("perBundle") if isinstance(rework, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ReworkSettings().per_bundle
    return int(value)


def bundle_remaining(bundle: str, usage: list[BundleUsage], snapshot: Mapping[str, Any] | None) -> int:
    """묶음의 남은 재작성 기회 — 사용 기록에 있으면 그 remaining, 없으면(아직 쓰지 않음) 설정 사본의 rework.perBundle."""
    for u in usage:
        if u.bundle_id == bundle:
            return u.remaining
    return per_bundle(snapshot)


def doc_candidates(results: list[SectionResult] | None, doc_display: float, threshold: float) -> list[ReworkOrder]:
    """계획서 묶음 재작성 지시 (business-rules 19.7). 판정(results)이 없으면(None) 1의 후보는 없는 것으로 본다."""
    results = list(results or [])
    first_kind: dict[str, str] = {}
    flagged: dict[str, list[SectionResult]] = {}
    for r in results:
        bundle = section_bundle(r.section_code)
        if bundle is None:
            continue
        first_kind.setdefault(bundle, r.content_type)
        if r.status in ("fail", "warning") and not r.input_missing:
            flagged.setdefault(bundle, []).append(r)

    def order(bundle: str, reason: str) -> ReworkOrder:
        task_id = KIND_TASK.get(first_kind.get(bundle, "section"), "T-W1")
        return ReworkOrder(task_id=task_id, unit="묶음", targets=[bundle], reason=reason, instruction_delta=reason,
                           layer="document")
    orders = []
    for bundle in document_bundles():
        if bundle in flagged:
            lines = [f"{r.section_code} {' · '.join([*r.issues, *r.warnings]) or r.status}" for r in flagged[bundle]]
            orders.append(order(bundle, "\n".join(lines)))
    if not orders and doc_display < threshold:
        orders = [order(bundle, REWORK_DEFAULT_REASON) for bundle in document_bundles()]
    return orders


def artifact_orders(score: ArtifactScore, kind: str) -> list[ReworkOrder]:
    """산출물층 재작성 지시 — 다시 돌릴 Task · 사유는 공용 규칙(artifact_rework_reasons). 같은 Task의 사유는 '; '로 잇는다.
    보류된 대조는 이미 0점이라 재정규화하지 않는다(2026-09-30 결정 8)."""
    return [ReworkOrder(task_id=task_id, unit="묶음", targets=[TASK_BUNDLE[task_id]], reason="; ".join(rs),
                        instruction_delta="; ".join(rs), layer="artifact")
            for task_id, rs in artifact_rework_reasons(score, kind).items()]


def next_action(passed: bool, orders: list[ReworkOrder], usage: list[BundleUsage],
                snapshot: Mapping[str, Any] | None) -> str:
    """진행가능 · 재작성권유 · 상한도달 — 후보 묶음(order_bundles — 기회를 세는 이름)의 남은 기회가 모두 0이면 상한도달."""
    if passed:
        return "진행가능"
    names = [b for o in orders for b in order_bundles(o)]
    if names and all(bundle_remaining(b, usage, snapshot) <= 0 for b in names):
        return "상한도달"
    return "재작성권유"


def input_notices(results: list[SectionResult] | None) -> list[str]:
    """입력 없음 항목이 하나라도 있으면 '입력 확인 필요' 안내 (business-rules 19.7)."""
    return [INPUT_MISSING_NOTICE] if any(r.input_missing for r in results or []) else []


def unreachable_notices(doc_total: float, maxes: ScoreMaxes, threshold: float, usage: list[BundleUsage],
                        snapshot: Mapping[str, Any] | None) -> list[str]:
    """E-G2-UNREACHABLE (R-6 ②) — 문서층 total + 산출물층 만점(C + P) < 기준이면 안내 하나. 계획서 묶음 중 남은 기회가 있는
    묶음이 있으면 첫 문구(계획서 항목을 함께 선택), 없으면 둘째 문구(이대로 진행할 수 있음). 도달할 수 있으면 빈 목록."""
    if doc_total + maxes.artifact >= threshold:
        return []
    if any(bundle_remaining(b, usage, snapshot) > 0 for b in document_bundles()):
        return [message("E-G2-UNREACHABLE")]
    return [UNREACHABLE_NO_DOC_CHANCE]


def run_g02a(inp: G02aIn) -> G02aOut:
    """문서 평가 판정 — 표시 점수(문서층 → 100점 환산, D = 설정 사본 scoring.docLayerMax)로 다음 동작을 정하고, 계획서 묶음
    후보는 항목 판정(sectionResults)으로 낸다."""
    maxes = score_maxes(inp.settings_snapshot)
    display = display_score(inp.doc_score.total, maxes.doc)
    passed = display >= inp.threshold
    orders = doc_candidates(inp.section_results, display, inp.threshold)
    na = next_action(passed, orders, inp.rework_usage, inp.settings_snapshot)
    report = ScoreReport(
        doc_score=inp.doc_score, artifact_score=None, total=inp.doc_score.total, threshold=inp.threshold,
        passed=passed, failed_task_ids=sorted({o.task_id for o in orders}),
        rework_orders=orders, rework_usage=inp.rework_usage, phase="document", display_score=display,
        carried_over_layer=None, rework_diff=[],
        comparisons=inp.cycle_info.comparisons if inp.cycle_info else [],
        notices=[ch.final_action for ch in (inp.checks or []) if ch.final_action] + input_notices(inp.section_results),
        settings_snapshot=inp.settings_snapshot, rubric_version=inp.rubric_version,
        **scaled_report_fields(maxes))
    return G02aOut(score_report=report, failed_task_ids=report.failed_task_ids, rework_orders=orders, next_action=na)


def run_g02b(inp: G02bIn) -> G02bOut:
    """종합 평가 판정 — 총점(문서층 + 산출물층 환산)으로 다음 동작을 정한다. 계획서 묶음 후보는 G-02a와 같은 규칙(문서층 표시
    점수 기준), 산출물층 지시는 공용 규칙(종류는 입력 category로)."""
    maxes = score_maxes(inp.settings_snapshot)
    fields = scaled_report_fields(maxes, inp.artifact_score)
    artifact_layer = fields["artifact_layer_score"]
    total = round(inp.doc_score.total + artifact_layer, 1)
    doc_display = display_score(inp.doc_score.total, maxes.doc)
    orders = (doc_candidates(inp.section_results, doc_display, inp.threshold)
              + artifact_orders(inp.artifact_score, prototype_kind(inp.category)))
    na = next_action(total >= inp.threshold, orders, inp.rework_usage, inp.settings_snapshot)
    ci = inp.cycle_info
    diff: list[ReworkDiff] = []
    if ci is not None:
        if ci.previous_doc_score is not None:
            diff.append(ReworkDiff(task_id="T-W1", layer="document", label="문서층",
                                   before_summary=f"{ci.previous_doc_score.total}/{maxes.doc:g}",
                                   after_summary=f"{inp.doc_score.total}/{maxes.doc:g}"))
        if ci.previous_artifact_score is not None:
            before = scale_artifact(ci.previous_artifact_score, maxes).artifact_layer_score
            diff.append(ReworkDiff(task_id="T-V2", layer="artifact", label="산출물층",
                                   before_summary=f"{before}/{maxes.artifact:g}",
                                   after_summary=f"{artifact_layer}/{maxes.artifact:g}"))
    notices = (input_notices(inp.section_results)
               + unreachable_notices(inp.doc_score.total, maxes, inp.threshold, inp.rework_usage, inp.settings_snapshot))
    report = ScoreReport(
        doc_score=inp.doc_score, artifact_score=inp.artifact_score, total=total, threshold=inp.threshold,
        passed=total >= inp.threshold, failed_task_ids=sorted({o.task_id for o in orders}),
        rework_orders=orders, rework_usage=inp.rework_usage, phase="overall", display_score=total,
        carried_over_layer=ci.carried_over_layer if ci else None, rework_diff=diff,
        comparisons=ci.comparisons if ci else [], notices=notices,
        settings_snapshot=inp.settings_snapshot, rubric_version=inp.rubric_version, **fields)
    return G02bOut(score_report=report, failed_task_ids=report.failed_task_ids, rework_orders=orders,
                   next_action=na, rework_diff=diff)


__all__ = [
    "INPUT_MISSING_NOTICE", "artifact_orders", "bundle_remaining", "doc_candidates", "input_notices", "next_action",
    "per_bundle", "prototype_kind", "run_g02a", "run_g02b", "unreachable_notices",
]
