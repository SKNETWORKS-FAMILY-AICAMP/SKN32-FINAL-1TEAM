"""기록 통계 줄 계산 (확장) — 옮겨 지우는 실행 기록 · 끝난 시작 요청을 식별자 없는 통계 줄(LogStatsRow)로 바꾼다.

- 순수 함수다. 저장소 · 시계를 부르지 않는다. 부르는 쪽(보관 기간 작업 · 탈퇴 처리)이 저장소에서 기록을 모아 넘기고,
  돌려받은 줄을 retire_run · retire_start_requests에 넘긴다.
- 줄에는 개수 · 점수 · 고정 값(Task ID · 계기 · 상태 · 오류 종류 이름 · 층 이름) · 달 · 카테고리만 싣는다. 실행 건 ·
  실행 · 호출 · 계정 · 프로젝트 · 공고 ID, 산출물 참조, 오류 요약 · 실패 사유 · 사건 설명 · 안내 문구 같은 자유 글,
  산출물 · 입력 내용은 어느 칸(data 안 포함)에도 싣지 않는다. 고정 값이 아닌 글이 오면 싣지 않거나 ValueError다
  (메시지에 그 값을 넣지 않는다).
- 층별 채점 출처(SCORE_LAYERS)와 현재 점수(current_scores)는 관리자 조회(reads.py)와 같은 정의 하나를 쓴다.
  산출물을 읽지 않고 실행 기록의 출력 요약 메타만 본다 — 완전 삭제 뒤에도 셀 수 있다.
"""
from __future__ import annotations

import typing
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..models import ReworkComparison, Run
from ..models.base import Category, ErrorKind, KeptSide, Trigger
from ..models.clock import UTC_MIN, kst_month
from ..orchestrator.errors import COMMAND_ERROR_CODES, ERROR_CODES
from ..orchestrator.store import FINISHED_REQUEST, LogStatsRow, StartRequest
from ..orchestrator.trace import CallLog, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent

# 층별 채점 출처 — (층 이름, 채점 Task, 실행 기록 출력 요약 필드). 산출물을 읽지 않고 실행 기록만 본다.
SCORE_LAYERS = (("docScore", "T-V1", "score"), ("codeCheck", "T-V2", "code_check_score"),
                ("featureMatch", "T-V2", "feature_match_score"))
# 산출물로 가르는 층 — (층 이름, 산출물 키). 그 산출물을 낸 성공 실행의 출력 요약 score(산출물 · 점수 보고서 total)
OUTPUT_SCORE_LAYERS = (("artifactScore", "artifactScore"), ("overall", "scoreReport.overall"))
# 현재 점수 — (결과 이름, 산출물 키). 관리자 실행 건 목록의 문서층 · 산출물층 · 총점
CURRENT_SCORE_KEYS = (("doc", "docScore"), ("artifact", "artifactScore"), ("total", "scoreReport.overall"))

KIND_RUN = "실행"
KIND_REQUEST = "시작요청"
REASONS = ("12개월", "탈퇴")   # 옮긴 까닭 — 보관 기간(12개월) 지남 · 계정 탈퇴
TRIGGERS: tuple[str, ...] = typing.get_args(Trigger)
ERROR_KINDS: tuple[str, ...] = typing.get_args(ErrorKind)
KEPT_SIDES: tuple[str, ...] = typing.get_args(KeptSide)
CATEGORIES: tuple[str, ...] = typing.get_args(Category)
# 실행 기록 상태 — 앞 네 개는 늘 싣고, '실행'(끝나지 않은 기록)은 있을 때만 싣는다
EXECUTION_STATUSES = ("성공", "실패", "재개대기", "생략")
EXTRA_STATUSES = ("실행",)
# 실행 기록 토큰 필드 → data_json 키 (없는 값은 0)
TOKEN_KEYS = (("input_tokens", "input"), ("cached_input_tokens", "cachedInput"), ("output_tokens", "output"),
              ("reasoning_tokens", "reasoning"))
# 이미지 호출 토큰 — tokens(글 토큰)와 따로 센다 (2026-10-05에 고정한 키 목록에 imageTokens 하나를 더했다, 2026-10-06)
IMAGE_TOKEN_KEYS = (("image_input_tokens", "input"), ("image_output_tokens", "output"))
REWORK_FAILED_EVENT = "재작성실패"   # 엔진 rollback_cycle이 남기는 추적 사건 종류


def current_scores(pointers: dict[str, int], records: list[ExecutionRecord]) -> dict[str, float | None]:
    """현재 버전(되돌리기 반영) 점수 — 포인터가 가리키는 버전을 만든 실행 기록의 출력 요약에서 읽는다."""
    meta = {ref: r.output_meta for r in records if r.status == "성공" for ref in r.outputs}

    def score(key: str) -> float | None:
        version = pointers.get(key)
        m = meta.get(f"{key}@{version}") if version is not None else None
        return m.score if m is not None else None
    return {name: score(key) for name, key in CURRENT_SCORE_KEYS}


@dataclass(frozen=True)
class RunRecords:
    """옮겨 지울 실행 건 하나의 기록 — 저장소의 여섯 기록 표(retire_run이 지우는 범위)와 같다.

    executions: Store.executions, calls: Store.call_logs, events: Store.events, feedback: Store.feedback,
    comparisons: Store.comparisons, pointer_events: Store.pointer_events.
    """
    executions: list[ExecutionRecord] = field(default_factory=list)
    calls: list[CallLog] = field(default_factory=list)
    events: list[TraceEvent] = field(default_factory=list)
    feedback: list[FeedbackLink] = field(default_factory=list)
    comparisons: list[ReworkComparison] = field(default_factory=list)
    pointer_events: list[PointerEvent] = field(default_factory=list)

    def is_empty(self) -> bool:
        """여섯 기록이 모두 비었는지 — 저장소의 옮길 대상 조건('여섯 기록 표에 옮길 줄이 있음')과 같다."""
        return not (self.executions or self.calls or self.events or self.feedback or self.comparisons
                    or self.pointer_events)


def _check_reason(reason: str) -> None:
    if reason not in REASONS:
        raise ValueError("옮긴 까닭은 12개월 · 탈퇴만 받는다")


def _counts(values: Iterable[str | None], keys: tuple[str, ...], extra: tuple[str, ...] = ()) -> dict[str, int]:
    """keys는 0이어도 싣고, extra는 있을 때만 싣는다. 그 밖의 값(정해지지 않은 글 · None)은 세지 않는다."""
    c = Counter(v for v in values if v is not None)
    out = {k: c.get(k, 0) for k in keys}
    out.update({k: c[k] for k in extra if c.get(k)})
    return out


def _scores(executions: list[ExecutionRecord]) -> dict[str, list[dict[str, Any]]]:
    """층별 채점 — 성공한 실행 기록의 출력 요약에서, 끝 시각 순(되돌린 채점 포함). 재작성 뒤 = 계기 '재작성'."""
    events: dict[str, list[tuple[Any, float, bool]]] = {
        layer: [] for layer in [*(lay for lay, _, _ in SCORE_LAYERS), *(lay for lay, _ in OUTPUT_SCORE_LAYERS)]}
    for r in executions:
        if r.status != "성공":
            continue
        after = r.trigger == "재작성"
        when = r.ended_at or UTC_MIN
        for layer, task, attr in SCORE_LAYERS:
            score = getattr(r.output_meta, attr) if r.task_id == task else None
            if score is not None:
                events[layer].append((when, float(score), after))
        keys = {ref.rsplit("@", 1)[0] for ref in r.outputs}
        for layer, key in OUTPUT_SCORE_LAYERS:
            if key in keys and r.output_meta.score is not None:
                events[layer].append((when, float(r.output_meta.score), after))
    return {layer: [{"score": s, "afterRework": a} for _, s, a in sorted(entries, key=lambda e: e[0])]
            for layer, entries in events.items()}


def _tasks(executions: list[ExecutionRecord], calls: list[CallLog]) -> dict[str, dict[str, Any]]:
    """Task별 개수 — 이번에 옮기는 실행 기록이 있는 Task만(규칙 단계 · 합치기 포함)."""
    by_task: dict[str, list[ExecutionRecord]] = {}
    for r in executions:
        by_task.setdefault(r.task_id, []).append(r)
    calls_by_task: dict[str, list[CallLog]] = {}
    for c in calls:
        calls_by_task.setdefault(c.task_id, []).append(c)
    out: dict[str, dict[str, Any]] = {}
    for task_id, recs in by_task.items():
        mine = calls_by_task.get(task_id, [])
        tries = [t for c in mine for t in c.tries]
        out[task_id] = {
            "runs": _counts((r.trigger for r in recs), TRIGGERS),
            "status": _counts((r.status for r in recs), EXECUTION_STATUSES, EXTRA_STATUSES),
            "resumes": sum(r.resume_count for r in recs),
            # 재시도 = 시도 수 − 호출 수. 시도가 없는 호출(끝나지 않은 호출)이 음수를 만들지 않게 호출마다 센다
            "retries": sum(max(len(c.tries) - 1, 0) for c in mine),
            "errorKinds": _counts((r.error_kind for r in recs), ERROR_KINDS),
            "callErrorKinds": _counts((t.error_kind for t in tries), ERROR_KINDS),
            "tokens": {key: sum(getattr(r, attr) or 0 for r in recs) for attr, key in TOKEN_KEYS},
            "imageTokens": {key: sum(getattr(r, attr) or 0 for r in recs) for attr, key in IMAGE_TOKEN_KEYS},
        }
    return out


def run_stats_row(run: Run, records: RunRecords, *, pointers: dict[str, int], reason: str, part: int,
                  category_fallback: str | None = None) -> LogStatsRow | None:
    """실행 건 하나의 통계 줄 (kind '실행', count 1). 옮길 기록(여섯 기록)이 하나도 없으면 None — 줄을 쓰지 않는다.

    run: 옮길 때의 실행 건. records: 이번에 지우는 기록만(이전에 옮긴 기록은 이미 지워져 다시 세지 않는다).
    pointers: Store.get_pointers — finalScores(관리자 실행 건 목록의 현재 점수와 같은 계산). 없으면(완전 삭제 뒤) 모두 None.
    part: Run.stats_parts + 1. category_fallback: Run.category가 없는 기존 실행 건의 산출물 'category' 현재 값
    (카테고리 값이 아니면 싣지 않는다).
    """
    _check_reason(reason)
    if part < 1:
        raise ValueError("part는 1 이상")
    if records.is_empty():
        return None
    category = run.category or (category_fallback if category_fallback in CATEGORIES else None)
    data: dict[str, Any] = {
        "step": run.state.step,
        "scores": _scores(records.executions),
        "finalScores": current_scores(pointers, records.executions),
        "tasks": _tasks(records.executions, records.calls),
        "rework": {
            "cycles": len({c.cycle_id for c in records.comparisons}),
            "kept": _counts((c.kept for c in records.comparisons), KEPT_SIDES),
            "failed": sum(1 for e in records.events if e.kind == REWORK_FAILED_EVENT),
        },
        "run": {"retryCount": run.retry_count, "resumeCount": run.resume_count,
                "lastErrorKind": run.last_error_kind if run.last_error_kind in ERROR_KINDS else None},
    }
    return LogStatsRow(kind=KIND_RUN, reason=reason, month=kst_month(run.created_at), category=category,
                       status=run.state.progress, part=part, count=1, data=data)


def _known_code(code: str | None) -> str | None:
    """시트 6 결과 코드 · 명령 오류 코드만 싣는다. 모르는 글은 None (자유 글이 줄에 들어가지 않게)."""
    return code if code in ERROR_CODES or code in COMMAND_ERROR_CODES else None


def start_request_rows(requests: list[StartRequest], reason: str) -> list[LogStatsRow]:
    """끝난 시작 요청(완료 · 실패 · 취소)을 (요청을 넣은 달(한국 날짜) · 상태 · 실패 코드)로 묶어 센 줄들.

    kind '시작요청', part 1, category · data 없음. 끝나지 않은 요청이 있으면 ValueError. 줄 순서는 처음 나온 묶음 순서.
    """
    _check_reason(reason)
    groups: Counter[tuple[str, str, str | None]] = Counter()
    for req in requests:
        if req.status not in FINISHED_REQUEST:
            raise ValueError("끝난 시작 요청(완료 · 실패 · 취소)만 옮긴다")
        groups[(kst_month(req.created_at), req.status, _known_code(req.result_code))] += 1
    return [LogStatsRow(kind=KIND_REQUEST, reason=reason, month=month, status=status, result_code=code, part=1,
                        count=count)
            for (month, status, code), count in groups.items()]


__all__ = [
    "CURRENT_SCORE_KEYS", "KIND_REQUEST", "KIND_RUN", "OUTPUT_SCORE_LAYERS", "REASONS", "SCORE_LAYERS", "RunRecords",
    "current_scores", "run_stats_row", "start_request_rows",
]
