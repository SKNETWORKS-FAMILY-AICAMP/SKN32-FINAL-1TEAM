"""추적 기록.

원칙
- 기준 문서의 AttemptRef를 확장한다(ExecutionRecord). 기준 문서에 없는 필드는 ext()로 표시한다.
- 기록에는 산출물 내용을 복사하지 않고 '산출물명@버전' 참조와 요약 메타만 남긴다(기획서 6-7).
- 규칙 단계 · 합치기도 기록한다.
- 재시도는 새 버전을 만들지 않고 호출 로그(CallLog)에 따로 남긴다.
- 되돌리기는 현재 버전 포인터만 옮기고(PointerEvent) 기록은 지우지 않는다.
- T-P2는 호출 로그는 문장별(itemKey), 입력 · 출력 이력은 Task 단위로 남긴다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ..models import AttemptRef
from ..models.base import CallError, ErrorKind, SBModel, ext


class OutputMeta(SBModel):
    """확장 — 출력 요약 메타 (내용 없이)."""
    check_passed: bool | None = None
    failure_count: int | None = None
    final_action_applied: bool | None = None
    score: float | None = None
    passed: bool | None = None
    note: str | None = None


class ExecutionRecord(AttemptRef):
    """AttemptRef 확장 — 단계 실행 한 번의 기록."""
    execution_id: str = ext(note="실행 식별자")
    run_id: str = ext()
    agent: str = ext(note="담당 Agent (규칙 단계 · 합치기는 기록용)")
    step_kind: str = ext(note="task · rule · merge")
    model: str | None = ext(None, note="실제로 쓴 모델. tools를 받지 않는 단계는 없음")
    provider: str | None = ext(None)
    temperature: float | None = ext(None, note="실제로 쓴 온도 (Task 덮어쓰기 적용 후)")
    reasoning_effort: str | None = ext(None, note="실제로 쓴 추론 강도 (추론 모델)")
    inputs: list[str] = ext(default_factory=list, note="입력 산출물명@버전 (모든 실행)")
    outputs: list[str] = ext(default_factory=list, note="출력 산출물명@버전")
    output_meta: OutputMeta = ext(default_factory=OutputMeta)
    status: str = ext("실행", note="실행 · 성공 · 실패 · 재개대기 · 생략")
    cycle_id: str | None = ext(None, note="재작성 사이클")
    rework_role: str | None = ext(None, note="재작성 사이클 안의 역할: 대상 · 반영 · 합치기 · 재채점 · 판정")
    redo_count: int = ext(0, note="이 실행이 몇 번째 재수행인지 (첫 실행 0)")
    resume_count: int = ext(0, note="이 실행에서 재개한 횟수")
    feedback_in: list[str] = ext(default_factory=list, note="이 실행으로 들어온 FeedbackLink 식별자")
    error: str | None = ext(None)
    error_kind: ErrorKind | None = ext(None)
    started_at: datetime | None = ext(None)
    ended_at: datetime | None = ext(None)


class CallTry(SBModel):
    """확장 — 호출 한 건 안의 시도 하나 (재시도 포함)."""
    no: int
    started_at: datetime
    ended_at: datetime
    outcome: str                    # 성공 · 호출실패 · 응답지연 · 형식오류
    error_kind: ErrorKind | None = None
    detail: str | None = None       # 오류 종류 설명만 (응답 내용 없음)


class CallLog(SBModel):
    """확장 — LLM · 검색 호출 한 건. 재시도는 tries에 쌓이고 새 버전을 만들지 않는다."""
    call_id: str
    run_id: str
    execution_id: str
    task_id: str
    agent: str
    call_type: str                  # llm · search
    purpose: str
    item_key: str | None = None     # T-P2 문장 ID 등
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    timeout_sec: float
    tries: list[CallTry] = Field(default_factory=list)
    final_outcome: str = "진행"
    error: CallError | None = None
    error_kind: ErrorKind | None = None


class FeedbackLink(SBModel):
    """확장 — 검사 · 검증 피드백 전달.

    재수행: check.failures → 같은 Task의 다음 실행
    재작성: reworkOrders(+사용자 선택) → 대상 Task의 실행
    """
    feedback_id: str
    run_id: str
    kind: str                       # 재수행 · 재작성 · 재작성반영
    source_execution_id: str | None
    source_refs: list[str]          # 어느 결과(산출물@버전)에서 왔는지
    target_task_id: str
    target_execution_id: str        # 전달 대상 실행
    via_ref: str | None             # 전달 수단 (reworkInput@버전)
    cycle_id: str | None = None
    created_at: datetime


class PointerEvent(SBModel):
    """확장 — 현재 버전 포인터 이동 (되돌리기)."""
    run_id: str
    key: str
    from_version: int | None
    to_version: int
    reason: str
    cycle_id: str | None = None
    at: datetime


class TraceEvent(SBModel):
    """확장 — 그 밖의 추적 사건 (규격 위반, 확정 동작 누락, 사이클 시작 · 종료 등)."""
    run_id: str
    kind: str
    detail: str
    refs: list[str] = Field(default_factory=list)
    execution_id: str | None = None
    cycle_id: str | None = None
    at: datetime


def output_meta_of(outputs: dict[str, Any]) -> OutputMeta:
    """출력에서 요약 메타만 뽑는다 (내용 복사 없음)."""
    meta = OutputMeta()
    check = outputs.get("check")
    if check is not None:
        meta.check_passed = check.passed
        meta.failure_count = len(check.failures)
        meta.final_action_applied = check.final_action is not None
    for key in ("score_report", "doc_score", "artifact_score"):
        obj = outputs.get(key)
        if obj is not None:
            meta.score = getattr(obj, "total", None)
            if hasattr(obj, "passed"):
                meta.passed = obj.passed
            break
    gate = outputs.get("gate_result")
    if gate is not None:
        meta.passed = gate.passed
    return meta
