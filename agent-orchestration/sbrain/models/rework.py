"""시트 4 재작성 · 재수행 관련 타입.

ReworkInput · ReworkComparison은 추적 기록을 위해 확장 필드를 더했다(ext).
"""
from __future__ import annotations

from datetime import datetime

from .base import KeptSide, Layer, ReworkMode, ReworkUnit, SBModel, ext


class CheckResult(SBModel):
    passed: bool
    failures: list[str]
    final_action: str | None = None


class ReworkOrder(SBModel):
    task_id: str
    unit: ReworkUnit
    targets: list[str]
    reason: str
    instruction_delta: str
    layer: Layer


class ReworkInput(SBModel):
    mode: ReworkMode
    previous_result_ref: str
    issues: list[str]
    order: ReworkOrder | None = None
    is_final_attempt: bool
    # 확장 — 피드백 추적
    source_refs: list[str] = ext(default_factory=list, note="이 입력의 근거가 된 산출물@버전 (check · reworkOrders · 사용자 선택)")
    feedback_id: str | None = ext(None, note="추적 기록 FeedbackLink 식별자")
    # 확장 — 기능정의서의 reworkInput '기존 결과 + 문제가 된 내용' 자리 (이름은 담당자 임시안). 채우는 것은 흐름이
    # 정한다(T-B1 재작성 대상 · 재수행만). 이 산출물(재작성 입력 JSON)에만 있고 기록 · 로그 · 사건 · 관리자 조회 · 예외
    # 메시지 · 다시 쓰기 LLM 요청에는 싣지 않는다
    previous_source_text: str | None = ext(None, note="재실행 대상의 이전 결과 원문. T-B1만 채운다")


class BundleUsage(SBModel):
    bundle_id: str
    layer: Layer
    used_count: int
    remaining: int


class ReworkDiff(SBModel):
    task_id: str
    layer: Layer
    label: str
    before_summary: str
    after_summary: str
    detail: str | None = None


class ReworkComparison(SBModel):
    bundle_id: str
    before_refs: list[str]
    after_refs: list[str]
    before_score: float
    after_score: float
    kept: KeptSide
    # 확장 — 추적
    cycle_id: str = ext(note="재작성 사이클 식별자")
    screen: int = ext(note="재작성을 요청한 화면(6 · 8 · 9)")
    basis: str = ext(note="비교 기준: document · artifact · total")
    compared_at: datetime = ext()
