"""추적 기록.

원칙
- 기준 문서의 AttemptRef를 확장한다(ExecutionRecord). 기준 문서에 없는 필드는 ext()로 표시한다.
- 기록에는 산출물 내용을 복사하지 않고 '산출물명@버전' 참조와 요약 메타만 남긴다(기획서 6-7).
- 규칙 단계 · 합치기도 기록한다.
- 재시도는 새 버전을 만들지 않고 호출 로그(CallLog)에 따로 남긴다.
- 되돌리기는 현재 버전 포인터만 옮기고(PointerEvent) 기록은 지우지 않는다.
- T-P2는 호출 로그는 문장별(itemKey), 입력 · 출력 이력은 Task 단위로 남긴다.
- 토큰 사용량(확장): 시도마다 응답의 사용량을 남기고(CallTry), 호출(CallLog) · 실행(ExecutionRecord)에 합계를 둔다.
  입력은 캐시 입력을 포함한 전체이고 캐시 입력은 그 일부다. 출력은 추론을 포함한 전체이고 추론은 그 일부다.
  사용량을 주지 않는 호출처면 None이다. 비용(원 · 달러)은 계산하지 않는다.
- 파일 호출(확장, call_type 'file'): 목적(put · get) · 시도별 결과 · 오류 종류 · 시각만 남긴다. 토큰은 없다.
  파일 내용 · 이름 · 키는 남기지 않는다(칸을 늘리지 않는다).
- 이미지 호출 토큰(확장): 호출 기록(call_type 'image')에는 지금 칸에 남기고, 실행 기록에서는 글 토큰 합계에 더하지 않고
  image_input_tokens · image_output_tokens에 따로 더한다 — 단가가 달라 합치면 토큰 수로 비용을 가늠할 수 없다.
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
    # 산출물층 채점의 항목별 점수 — 관리자 점수 이력 · 운영 요약이 산출물을 읽지 않고(완전 삭제 뒤에도) 쓴다
    code_check_score: float | None = None
    feature_match_score: float | None = None


TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")
IMAGE_CALL = "image"   # 이미지 호출의 call_type
FILE_CALL = "file"     # 파일 창구(tools.files) 호출의 call_type (확장) — 목적 put · get, 토큰 없음. 크기 · 형식 · 이름 · 키는 남기지 않는다
# 이미지 호출 기록의 토큰 칸 → 실행 기록의 이미지 토큰 칸 (캐시 · 추론은 따로 두지 않는다)
IMAGE_TOKEN_FIELDS = (("input_tokens", "image_input_tokens"), ("output_tokens", "image_output_tokens"))


def _token(what: str):
    return ext(None, note=f"토큰 — {what}")


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
    input_tokens: int | None = _token("이 실행의 호출 합계, 입력 (캐시 입력 포함)")
    cached_input_tokens: int | None = _token("이 실행의 호출 합계, 캐시 입력")
    output_tokens: int | None = _token("이 실행의 호출 합계, 출력 (추론 포함)")
    reasoning_tokens: int | None = _token("이 실행의 호출 합계, 추론")
    image_input_tokens: int | None = _token("이 실행의 이미지 호출 합계, 입력 (글 토큰 합계와 따로)")
    image_output_tokens: int | None = _token("이 실행의 이미지 호출 합계, 출력 (글 토큰 합계와 따로)")


class CallTry(SBModel):
    """확장 — 호출 한 건 안의 시도 하나 (재시도 포함)."""
    no: int
    started_at: datetime
    ended_at: datetime
    outcome: str                    # 성공 · 호출실패 · 응답지연 · 형식오류
    error_kind: ErrorKind | None = None
    detail: str | None = None       # 오류 종류 설명만 (응답 내용 없음)
    input_tokens: int | None = _token("이 시도의 응답, 입력 (캐시 입력 포함)")
    cached_input_tokens: int | None = _token("이 시도의 응답, 캐시 입력")
    output_tokens: int | None = _token("이 시도의 응답, 출력 (추론 포함)")
    reasoning_tokens: int | None = _token("이 시도의 응답, 추론")


class CallLog(SBModel):
    """확장 — LLM · 검색 호출 한 건. 재시도는 tries에 쌓이고 새 버전을 만들지 않는다."""
    call_id: str
    run_id: str
    execution_id: str
    task_id: str
    agent: str
    call_type: str                  # llm · search · image · file
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
    input_tokens: int | None = _token("시도 합계, 입력 (캐시 입력 포함)")
    cached_input_tokens: int | None = _token("시도 합계, 캐시 입력")
    output_tokens: int | None = _token("시도 합계, 출력 (추론 포함)")
    reasoning_tokens: int | None = _token("시도 합계, 추론")


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


def add_tokens(target: Any, sources: list[Any]) -> None:
    """sources(시도 · 호출 기록)의 토큰을 target(호출 · 실행 기록)에 더한다. 기록이 하나도 없는 항목은 그대로 둔다.

    이미지 호출 기록(call_type 'image')은 글 토큰 칸에 더하지 않는다. target에 이미지 토큰 칸이 있으면(실행 기록) 거기에 더한다.
    """
    images = [s for s in sources if getattr(s, "call_type", None) == IMAGE_CALL]
    texts = [s for s in sources if getattr(s, "call_type", None) != IMAGE_CALL]
    _sum_into(target, texts, [(f, f) for f in TOKEN_FIELDS])
    if images and hasattr(target, IMAGE_TOKEN_FIELDS[0][1]):
        _sum_into(target, images, list(IMAGE_TOKEN_FIELDS))


def _sum_into(target: Any, sources: list[Any], pairs: list[tuple[str, str]]) -> None:
    for src, dst in pairs:
        values = [v for v in (getattr(s, src, None) for s in sources) if v is not None]
        if values:
            setattr(target, dst, (getattr(target, dst) or 0) + sum(values))


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
    code_check, feature_match = outputs.get("code_check"), outputs.get("feature_match")
    if code_check is not None:
        meta.code_check_score = getattr(code_check, "total", None)
    if feature_match is not None:
        meta.feature_match_score = getattr(feature_match, "score", None)
    return meta
