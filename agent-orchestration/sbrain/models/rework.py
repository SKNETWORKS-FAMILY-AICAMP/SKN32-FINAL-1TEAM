"""시트 4 재작성 · 재수행 관련 타입.

ReworkInput · ReworkComparison은 추적 기록을 위해 확장 필드를 더했다(ext).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from .base import KeptSide, Layer, ReworkMode, ReworkUnit, SBModel, ext
from .files import FileRef

# 재수행이 어느 쪽에서 왔는지 — 자체 검사(check) · 검증-1 판정 (확장, spec 4.7)
RedoSource = Literal["검사", "검증-1"]


class CheckResult(SBModel):
    passed: bool
    failures: list[str]
    final_action: str | None = None
    # 확장 — 불통과 항목 번호 → 그 항목의 문제 목록. 재수행 때 흐름이 ReworkInput.targetItems로 옮긴다 (spec 4.8)
    failed_items: dict[str, list[str]] = ext(
        default_factory=dict, note="불통과 항목 번호 → 문제 목록 — 재수행 대상 항목 (흐름은 이 칸으로 가른다)")


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
    # 재실행 대상의 이전 결과 — 이전 프로토타입 진입 파일의 참조. T-B1만 채운다 — 기능정의서의 reworkInput
    # '기존 결과 + 문제가 된 내용' 자리(기준 문서는 원문 글자, 여기는 참조 — 결정 0023). T-B1이 tools.files로 읽는다.
    # 채우는 것은 흐름이 정한다(T-B1 재작성 대상 · 재수행만, 진입 파일이 없으면 비움). 이 산출물(재작성 입력 JSON)에만 있고
    # 기록 · 로그 · 사건 · 관리자 조회 · 예외 메시지 · 다시 쓰기 LLM 요청에는 싣지 않는다
    previous_source_file: FileRef | None = ext(None, note="참조형 — 기준 문서와 다름(결정 0023)")
    # 확장 — 목표 항목 (전략 · 작성 · 검증-1 연동, spec 4.7). 비어 있으면 첫 실행(모든 항목)이다
    target_items: dict[str, list[str]] = ext(
        default_factory=dict, note="다시 만들 항목 번호 → 그 항목의 문제 목록. 비면 모든 항목")
    redo_source: RedoSource | None = ext(None, note="재수행이 온 곳 — 검사 · 검증-1 (재작성 · 첫 실행은 None)")
    unit: ReworkUnit | None = ext(None, note="재수행 단위 표시 — 섹션 · 표 1건 · 차트 1건(그림)")
    fallback_items: list[str] = ext(default_factory=list, note="T-W3 표 대체 대상 항목 번호 (spec 4.10)")


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
