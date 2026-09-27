"""시트 4 실행 상태 타입 — Run · RunState · AttemptRef · Notification.

Run의 확장 필드는 Orchestrator가 재개 지점을 잃지 않기 위해 쓰는 값이다(ext).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, computed_field, model_validator

from .base import (
    ErrorKind, FailureScope, NotificationKind, RunPhase, RunProgress,
    RunStep, SBModel, ScreenStatus, Trigger, ext,
)
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


class CycleState(SBModel):
    """확장 — 진행 중인 재작성 사이클."""
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
    # 확장
    created_at: datetime = ext()
    segment: str | None = ext(None, note="현재 구간(WRITE · PROTO · REWORK6 …)")
    queue: list[str] = ext(default_factory=list, note="남은 단계 ID. 재개 지점")
    segment_total: int = ext(0, note="진행률 계산용 구간 단계 수")
    redo_state: RedoState | None = ext(None)
    cycle: CycleState | None = ext(None)
    resume_window_started_at: datetime | None = ext(None, note="재개 총 대기 상한 계산 시작 시각")
    admin_alert: bool = ext(False, note="영구 오류로 실패 — 관리자 알림 대상")
    decision_ref: str | None = ext(None, note="현재 구간을 연 사용자 명령 산출물@버전")
    check_refs: dict[str, str] = ext(default_factory=dict, note="이번 구간 · 사이클의 Task별 최종 check@버전")
    more_used: bool = ext(False, note="공고 추가 조회 사용 여부")
    notices: list[Notice] = ext(default_factory=list)
    ended_at: datetime | None = ext(None)
