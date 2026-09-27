"""저장 인터페이스.

- 상태 '관리'(규칙)는 Orchestrator 코드가, 저장소는 그 결과를 '저장'한다.
- Task 하나가 끝나면 산출물 버전 · 현재 버전 포인터 · 실행 상태 · 추적 기록을 CommitBatch 하나로 한 번에 저장한다.
  중간에 멈춰도 재개 지점이 어긋나지 않게 하기 위해서다.
- 같은 실행을 두 곳에서 동시에 진행하지 않도록 실행 점유(acquire · release)를 둔다.
  저장(commit)은 점유한 쪽만 할 수 있다.
- 산출물 내용은 산출물 저장소에만 있고, 추적 기록은 참조만 갖는다(기획서 6-7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from ..models import Notification, ReworkComparison, Run
from .trace import CallLog, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent


@dataclass(frozen=True)
class ArtifactVersion:
    run_id: str
    key: str
    version: int
    value: Any              # JSON 호환 값
    producer: str           # 만든 실행 ID 또는 'user:…' · 'orchestrator:…'
    created_at: datetime

    @property
    def ref(self) -> str:
        return f"{self.key}@{self.version}"


@dataclass
class CommitBatch:
    run: Run | None = None
    versions: list[ArtifactVersion] = field(default_factory=list)
    pointers: dict[str, int] = field(default_factory=dict)
    pointer_events: list[PointerEvent] = field(default_factory=list)
    executions: dict[str, ExecutionRecord] = field(default_factory=dict)   # execution_id → 기록 (덮어쓰기)
    call_logs: list[CallLog] = field(default_factory=list)
    feedback: list[FeedbackLink] = field(default_factory=list)
    comparisons: list[ReworkComparison] = field(default_factory=list)
    events: list[TraceEvent] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.run or self.versions or self.pointers or self.pointer_events or self.executions
                    or self.call_logs or self.feedback or self.comparisons or self.events or self.notifications)


class Store(Protocol):
    # ── 실행 건 ───────────────────────────────────────
    def create_run(self, run: Run, batch: CommitBatch, *, max_active: int = 1) -> bool:
        """동시 실행 제한을 확인하고 실행 건과 첫 기록을 원자적으로 만든다. 제한에 걸리면 False."""

    def load_run(self, run_id: str) -> Run: ...

    def list_runs(self, account_id: str) -> list[Run]: ...

    def find_active_run(self, account_id: str) -> Run | None:
        """계정의 진행 중 · 확인 필요 실행 (progress: 실행 · 재개대기 · 사용자대기)."""

    def runs_due_for_resume(self, now: datetime) -> list[str]: ...

    # ── 실행 점유 ─────────────────────────────────────
    def acquire(self, run_id: str, owner: str, lease_sec: float) -> bool: ...

    def release(self, run_id: str, owner: str) -> None: ...

    def is_locked(self, run_id: str, now: datetime) -> bool: ...

    # ── 한 번에 저장 ──────────────────────────────────
    def commit(self, run_id: str, owner: str, batch: CommitBatch) -> None: ...

    # ── 중단 요청 (Task 사이에서 확인) ─────────────────
    def request_abort(self, run_id: str) -> None: ...

    def is_abort_requested(self, run_id: str) -> bool: ...

    # ── 산출물 ────────────────────────────────────────
    def get_pointers(self, run_id: str) -> dict[str, int]: ...

    def get_latest_versions(self, run_id: str) -> dict[str, int]: ...

    def get_artifact(self, run_id: str, key: str, version: int) -> ArtifactVersion: ...

    def delete_artifacts(self, run_id: str) -> None:
        """실행 건 삭제 때 산출물을 함께 지운다. 추적 기록은 참조만 있어 남는다(6-7)."""

    # ── 추적 기록 조회 ────────────────────────────────
    def executions(self, run_id: str) -> list[ExecutionRecord]: ...

    def call_logs(self, run_id: str) -> list[CallLog]: ...

    def feedback(self, run_id: str) -> list[FeedbackLink]: ...

    def comparisons(self, run_id: str) -> list[ReworkComparison]: ...

    def pointer_events(self, run_id: str) -> list[PointerEvent]: ...

    def events(self, run_id: str) -> list[TraceEvent]: ...

    def notifications(self, run_id: str) -> list[Notification]: ...
