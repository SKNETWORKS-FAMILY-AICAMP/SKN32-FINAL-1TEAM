"""시트 4 실행 상태 타입 — Run · RunState · AttemptRef · Notification.

Run의 확장 필드는 Orchestrator가 재개 지점을 잃지 않기 위해 쓰는 값이다(ext).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, computed_field, model_validator

from .base import (
    Category, ErrorKind, FailureScope, KeptSide, NotificationKind, RunPhase, RunProgress,
    RunStep, SBModel, ScreenStatus, Trigger, ext,
)
from .clock import as_utc
from .rework import BundleUsage, ReworkComparison

SCREEN_STATUS: dict[str, ScreenStatus] = {
    "실행": "진행 중",
    "재개대기": "진행 중",
    "사용자대기": "확인 필요",
    "실패": "문제 발생",
    "완료": "완료",
    "중단": "중단됨",
}

# 이어하기 복귀 화면 번호 (시트 4 RunState.resumeStep)
RESUME_STEP: dict[str, int] = {
    "공고선택": 3, "자격확인": 3, "계획서작성": 5, "문서평가": 6,
    "프로토타입제작": 7, "산출물확인": 8, "종합평가": 9, "표현검수": 10, "결과물": 11,
}

ACTIVE_PROGRESS = ("실행", "재개대기", "사용자대기")
FAILURE_REASON_MAX = 500   # 실패 사유 길이 상한 (잠정)


class RunState(SBModel):
    step: RunStep
    progress: RunProgress
    resume_step: int

    @model_validator(mode="before")
    @classmethod
    def _drop_computed(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k not in ("screenStatus", "screen_status")}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def screen_status(self) -> ScreenStatus:
        """저장하지 않고 progress에서 계산한다."""
        return SCREEN_STATUS[self.progress]


def make_state(step: RunStep, progress: RunProgress, rework_screen: int | None = None) -> RunState:
    return RunState(step=step, progress=progress, resume_step=rework_screen or RESUME_STEP[step])


class AttemptRef(SBModel):
    task_id: str
    attempt: int = Field(ge=1)
    trigger: Trigger
    bundle_id: str | None = None
    result_ref: str
    created_at: datetime


class Notification(SBModel):
    run_id: str
    kind: NotificationKind
    failure_scope: FailureScope | None = None
    target_step: int | None = None
    channel: str = "화면"
    created_at: datetime
    read_at: datetime | None = None
    notification_id: str = ext(note="알림 식별자")


class Notice(SBModel):
    """확장 — 화면에 함께 보여줄 안내(시트 6 오류코드 문구)."""
    code: str
    message: str
    at: datetime


class RedoState(SBModel):
    """확장 — 진행 중인 단계의 재수행 · 재개 위치."""
    task_id: str
    redo_count: int = 0
    trigger: Trigger = "첫실행"
    rework_input_ref: str | None = None
    pending_execution_id: str | None = None
    bundle_id: str | None = None
    rework_role: str | None = None
    instruction_ref: str | None = ext(
        None, note="재작성 · 재수행 때 다시 쓴 지시문 산출물 '<taskId>.instruction@버전'. 같은 재작성 · 재수행 입력으로 "
                   "재개하면 다시 쓰지 않고 이 지시문을 쓴다. 새 입력이면 새 진행 위치라 비어 있다 (T-C3 spec 5.5)")
    partial_ref: str | None = ext(
        None, note="재시도 소진으로 재개를 예약할 때 Task가 받은 결과 '<taskId>.partial@버전'. 재개하면 PARTIAL로 연결한 "
                   "입력에 넣는다. 단계 성공 · 재수행 · 다른 단계 · 실행 실패 · 중단이면 재개 위치와 함께 사라진다(산출물은 남음)")


class CycleState(SBModel):
    """확장 — 진행 중인 재작성 사이클.

    collect_until이 있으면 그 시각까지는 '모으는 중'이다: 같은 화면의 재작성 요청을 이 사이클에 더하고
    (counted_bundles = 지금까지 모인 묶음), 워커는 이 실행 건을 가져가지 않는다. 시각이 지나면 워커가 진행한다.
    """
    cycle_id: str
    screen: int
    snapshot: dict[str, int]
    counted_bundles: list[str]
    selected_orders_ref: str
    orders_by_task: dict[str, dict[str, Any]]
    layers: list[str]
    started_at: datetime
    comparisons: list[ReworkComparison] = Field(default_factory=list)
    rescored_layers: list[str] = Field(default_factory=list)
    collect_until: datetime | None = None   # 재작성 요청을 모으는 시간이 끝나는 시각 (첫 요청 + 잠정 2초)


ReworkResultStatus = Literal["진행중", "완료", "실패"]


class ReworkSummary(SBModel):
    """확장 — 마지막 재작성 한 건의 결과 요약 (재작성 결과 조회가 읽는다).

    재작성을 시작할 때(첫 요청 접수) '진행중'으로 새로 만든다 — 이전 재작성의 결과는 마지막으로 남지 않는다.
    전후 비교 뒤 남긴 쪽 · 전후 점수 · 바뀐 산출물 참조를 채우고, 끝나면 '완료'.
    실패(재개 상한 초과 · 영구 오류)로 되돌렸으면 '실패' — 되돌림 · 돌려준 묶음 · 안내 코드만 남기고 전후 내용은 비운다.
    """
    cycle_id: str
    screen: int
    bundles: list[str]                       # 모은 묶음 (요청 순서)
    status: ReworkResultStatus
    started_at: datetime
    ended_at: datetime | None = None
    # 완료
    kept: KeptSide | None = None             # 남긴 쪽 (전 · 후)
    basis: str | None = None                 # 비교 기준: document · artifact · total
    before_score: float | None = None
    after_score: float | None = None
    before_refs: list[str] = Field(default_factory=list)   # 바뀐 산출물의 재작성 전 '이름@버전'
    after_refs: list[str] = Field(default_factory=list)    # 바뀐 산출물의 재작성 후 '이름@버전'
    # 실패
    rolled_back: bool = False
    refunded_bundles: list[str] = Field(default_factory=list)
    failure_reason: str | None = None        # 재개상한초과 · 영구오류 · 운영오류 (내용 없음)
    notice_code: str | None = None           # 사용자 안내 (E-RUN-ROLLBACK)


def collecting(run: Run, now: datetime) -> bool:
    """재작성 요청을 모으는 중인지 — '실행'이고 사이클의 모으는 시간이 아직 끝나지 않았다 (now의 시간대가 없으면 UTC)."""
    cyc = run.cycle
    return (run.state.progress == "실행" and cyc is not None and cyc.collect_until is not None
            and as_utc(now) < cyc.collect_until)


class Run(SBModel):
    run_id: str
    account_id: str
    state: RunState
    announcement_id: str | None = None
    current_phase: RunPhase
    attempts: list[AttemptRef] = Field(default_factory=list)
    settings_snapshot: dict[str, Any]
    rework_usage: list[BundleUsage] = Field(default_factory=list)
    rework_screen: int | None = None
    current_task: str | None = None
    retry_count: int = 0
    resume_count: int = 0
    next_resume_at: datetime | None = None
    last_error_kind: ErrorKind | None = None
    updated_at: datetime
    # 확장 (project_id 하나는 기준 문서 v1.10 Run에 들어갔다 — 저장 순서를 지키려 자리를 옮기지 않는다)
    created_at: datetime = ext()
    project_id: str | None = None  # 사전 정보 입력의 출처 — 웹 DB projects 행 (create_project가 저장)
    segment: str | None = ext(None, note="현재 구간(WRITE · PROTO · REWORK6 …)")
    queue: list[str] = ext(default_factory=list, note="남은 단계 ID. 재개 지점")
    segment_total: int = ext(0, note="진행률 계산용 구간 단계 수")
    redo_state: RedoState | None = ext(None)
    cycle: CycleState | None = ext(None)
    last_rework: ReworkSummary | None = ext(None, note="마지막 재작성 한 건의 결과 요약 (진행중 · 완료 · 실패)")
    resume_window_started_at: datetime | None = ext(None, note="재개 총 대기 상한 계산 시작 시각")
    admin_alert: bool = ext(False, note="영구 오류로 실패 — 관리자 알림 대상")
    decision_ref: str | None = ext(None, note="현재 구간을 연 사용자 명령 산출물@버전")
    check_refs: dict[str, str] = ext(default_factory=dict, note="이번 구간 · 사이클의 Task별 최종 check@버전")
    more_used: bool = ext(False, note="공고 추가 조회 사용 여부")
    blocked_announcement_ids: list[str] = ext(
        default_factory=list,
        note="막힌 공고 ID — 자격 불통과(E-G1-REJECT)가 나온 공고. 공고 선택 명령이 거절한다(ANNOUNCEMENT_BLOCKED). "
             "G-01 결과 저장과 같은 저장에서 넣고, 추가 조회에서 내용이 바뀌면 뺀다 (spec 4.3.6)")
    notices: list[Notice] = ext(default_factory=list)
    ended_at: datetime | None = ext(None)
    failure_reason: str | None = ext(None, note="실패 사유 '<Task>: <사유> — <오류 요약>' (웹 실패 알림에도 쓴다)")
    category: Category | None = ext(
        None, note="카테고리(원페이지 · 웹개발 · AI_API) — 기록 통계 줄의 category. 완전 삭제 · 12개월 처리가 지우지 않는다")
    stats_parts: int = ext(
        0, note="실행 기록을 통계 줄로 옮긴 횟수. 옮길 때마다 통계 줄 part = 이 값 + 1. 이 값을 쓰는 저장은 "
                "마지막 활동 시각(updatedAt)을 바꾸지 않는다")
    proofread_base_ref: str | None = ext(None, note="표현 검수(화면 10) 전 계획서 산출물 '이름@버전'")
    attempt_max: dict[str, int] = ext(default_factory=dict, note="Task별 마지막 시도 번호 (Task ID → 시도 번호)")


def progress_percent(run: Run) -> int:
    """진행률(%) — 진행 중(실행 · 재개대기)이면 지금 구간에서 끝난 단계 비율, 완료 100, 그 밖(대기 · 실패 · 중단) 0.

    화면 상태(view)가 쓴다(웹 projects.progress_percent에는 쓰지 않는다). 실패 · 중단은 대기열을 비우므로
    구간 비율로 세면 100이 되어 0으로 둔다 (잠정).
    """
    if run.state.progress == "완료":
        return 100
    total = run.segment_total
    if run.state.progress in ("실행", "재개대기") and total:
        return int(round((total - len(run.queue)) / total * 100))
    return 0
