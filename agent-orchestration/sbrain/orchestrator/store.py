"""저장 인터페이스.

- 상태 '관리'(규칙)는 Orchestrator 코드가, 저장소는 그 결과를 '저장'한다.
- Task 하나가 끝나면 산출물 버전 · 현재 버전 포인터 · 실행 상태 · 추적 기록을 CommitBatch 하나로 한 번에 저장한다.
  중간에 멈춰도 재개 지점이 어긋나지 않게 하기 위해서다.
- 같은 실행을 두 곳에서 동시에 진행하지 않도록 실행 점유(acquire · release)를 둔다.
  저장(commit)은 점유한 쪽만 할 수 있다.
- 산출물 내용은 산출물 저장소에만 있고, 추적 기록은 참조만 갖는다(기획서 6-7).
- 사전 단계 시작 요청(StartRequest, 확장): 웹이 요청을 넣고(add_start_request) 워커가 점유해(acquire_start_request)
  사전 단계를 돈 뒤, 실행 건 생성과 요청 '완료'를 한 번에 저장한다(create_run_for_request).
- 반려된 시도(RejectedAttempt, 확장): 내용을 담은 기록이라 실행 건의 주인 계정이 학습 데이터 편입에 동의했을 때만
  저장한다. 동의 여부는 저장하는 순간 저장소가 확인한다(SQL은 웹 users, 메모리는 set_training_consent로 받은 값).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field

from ..models import Notice, Notification, RejectedAttempt, ReworkComparison, Run
from ..models.base import SBModel
from .trace import CallLog, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent

StartRequestStatus = Literal["대기", "처리중", "완료", "실패", "취소"]
PENDING_REQUEST = ("대기", "처리중")
# create_run_for_request 결과: 만듦 · 취소 요청이 있어 만들지 않음 · 진행 중 실행 건이 있음 · 점유를 잃음
CreateOutcome = Literal["완료", "취소", "동시실행", "점유잃음"]
# cancel_start_request 결과: 대기 중이라 바로 취소 · 처리 중이라 취소 요청만 남김 · 이미 끝나 할 일 없음
CancelOutcome = Literal["취소", "취소요청", ""]


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
    # 반려된 시도 (확장) — 실행 건에 프로젝트가 있고 주인이 학습에 동의했을 때만 저장된다
    rejected_attempts: list[RejectedAttempt] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.run or self.versions or self.pointers or self.pointer_events or self.executions
                    or self.call_logs or self.feedback or self.comparisons or self.events or self.notifications
                    or self.rejected_attempts)


@dataclass(frozen=True)
class ExecutionFilter:
    """관리자 실행 기록 조회 조건 (확장). 시각은 시작 시각 기준 — since 이상, until 미만. limit이 None이면 모두."""
    project_id: int | str | None = None
    task_id: str | None = None
    status: str | None = None
    agent: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int | None = 50
    offset: int = 0
    order: Literal["desc", "asc"] = "desc"


@dataclass(frozen=True)
class RunFilter:
    """여러 실행 건 조회 조건 (확장) — 관리자 실행 건 목록 · 운영 요약 · 여러 프로젝트 보기.

    마지막 갱신 시각(updatedAt) 순(같으면 run_id 순). project_ids가 있으면 그 프로젝트들의 실행 건만(빈 묶음이면 없음).
    limit이 None이면 모두.
    """
    project_ids: tuple[int | str, ...] | None = None
    progress: str | None = None
    step: str | None = None
    limit: int | None = 50
    offset: int = 0
    order: Literal["desc", "asc"] = "desc"


@dataclass(frozen=True)
class ExecutionRow:
    """여러 실행 건을 거르는 조회의 한 줄 — 실행 기록과 그 실행 건의 프로젝트."""
    project_id: str | None
    record: ExecutionRecord


class StartRequest(SBModel):
    """확장 — 사전 단계 시작 요청. 웹 요청 안에서 검사를 통과하면 '대기'로 쌓이고, 워커가 처리한다."""
    request_id: str
    project_id: str | None          # 웹 projects.project_id. 테스트 · 시연용 직접 시작은 없음
    account_id: str
    status: StartRequestStatus
    form: dict[str, Any] | None = None          # 검사를 통과한 PreInput (JSON). 완전 삭제 때 지운다
    result_code: str | None = None              # 실패 코드 (시트 6)
    result_message: str | None = None
    result_detail: dict[str, Any] | None = None  # 진행 중인 작업 등
    notices: list[Notice] = Field(default_factory=list)
    run_id: str | None = None
    cancel_requested: bool = False
    claim_count: int = 0
    lease_owner: str | None = None
    lease_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class Store(Protocol):
    # ── 실행 건 ───────────────────────────────────────
    def create_run(self, run: Run, batch: CommitBatch, *, max_active: int = 1) -> bool:
        """동시 실행 제한을 확인하고 실행 건과 첫 기록을 원자적으로 만든다. 제한에 걸리면 False.

        프로젝트에 이미 실행 건이 있으면 ProjectRunExists (프로젝트 1건에 실행 건 최대 1건).
        """

    def load_run(self, run_id: str) -> Run: ...

    def list_runs(self, account_id: str) -> list[Run]: ...

    def find_active_run(self, account_id: str) -> Run | None:
        """계정의 진행 중 · 확인 필요 실행 (progress: 실행 · 재개대기 · 사용자대기)."""

    def find_run_by_project(self, project_id: int | str) -> Run | None:
        """프로젝트의 실행 건 (확장 — 웹은 project_id만 안다)."""

    def runs_due_for_resume(self, now: datetime) -> list[str]: ...

    def query_runs(self, f: RunFilter) -> list[Run]:
        """여러 실행 건을 거른다 (확장 — 관리자 실행 건 목록 · 운영 요약 · 여러 프로젝트 보기)."""

    def find_active_work(self, account_id: str) -> Run | StartRequest | None:
        """계정의 진행 중인 작업 (확장) — add_start_request와 같은 기준으로 센 것 중 막는 것 하나.

        진행 중 · 확인 필요 실행 건(먼저 만든 것)이 우선이고, 없으면 대기 · 처리중 시작 요청(먼저 넣은 것). 잠금 없이 읽는다.
        """

    # ── 사전 단계 시작 요청 (확장) ─────────────────────
    def add_start_request(self, req: StartRequest, *, max_active: int = 1) -> Run | StartRequest | None:
        """계정 잠금 안에서 진행 중 실행 건 · 대기 · 처리중 요청을 세고, 제한 안이면 요청을 넣는다.

        넣었으면 None, 막혔으면 막은 실행 건(우선) 또는 요청을 돌려준다(E-RUN-CONCURRENT 안내용).
        """

    def get_start_request(self, request_id: str) -> StartRequest: ...

    def latest_start_request(self, project_id: int | str) -> StartRequest | None:
        """프로젝트의 마지막 시작 요청."""

    def latest_start_requests(self, project_ids: Iterable[int | str]) -> dict[str, StartRequest]:
        """여러 프로젝트의 마지막 시작 요청 (확장). 키는 project_id 문자열, 요청이 없는 프로젝트는 빠진다."""

    def acquire_start_request(self, request_id: str, owner: str, lease_sec: float) -> bool:
        """'대기' 요청, 또는 점유가 만료됐거나 같은 점유자인 '처리중' 요청을 '처리중'으로 점유한다."""

    def finish_start_request(self, request_id: str, owner: str, *, status: StartRequestStatus,
                             code: str | None = None, message: str | None = None,
                             detail: dict[str, Any] | None = None, notices: list[Notice] | None = None) -> bool:
        """점유한 요청을 끝낸다(실패 · 취소). 점유를 잃었으면 False."""

    def create_run_for_request(self, run: Run, batch: CommitBatch, request_id: str, owner: str, *,
                               max_active: int = 1) -> CreateOutcome:
        """실행 건 생성과 요청 '완료'(+run_id · 안내)를 한 트랜잭션으로. 직전에 취소 요청을 확인한다."""

    def cancel_start_request(self, request_id: str) -> CancelOutcome: ...

    def pending_start_requests(self, project_id: int | str) -> list[StartRequest]:
        """프로젝트의 대기 · 처리중 시작 요청 (중단용)."""

    def clear_start_request_forms(self, project_id: int | str) -> int:
        """프로젝트 시작 요청의 입력 사본(form)을 지운다 (완전 삭제용). 지운 요청 수."""

    # ── 워커 가져가기 · 점유 연장 (확장) ────────────────
    # 후보 한 건을 고르고 같은 트랜잭션에서 점유를 기록한다. MySQL은 SKIP LOCKED로 다른 워커가 고르는 행을 건너뛴다.
    def claim_start_request(self, owner: str, lease_sec: float) -> str | None:
        """'대기' 요청 또는 점유가 만료된 '처리중' 요청 하나 (오래된 순)."""

    def claim_ready_run(self, owner: str, lease_sec: float) -> str | None:
        """점유가 비어 있는 '실행' 실행 건 하나 (오래 기다린 순).

        재작성 요청을 모으는 중인 실행 건(Run.cycle.collect_until이 지금보다 뒤)은 그 시각이 지날 때까지 가져가지 않는다.
        """

    def claim_due_resume(self, owner: str, lease_sec: float, now: datetime) -> str | None:
        """재개 시각이 된 '재개대기' 실행 건 하나 (재개 시각 순)."""

    def renew(self, run_id: str, owner: str, lease_sec: float) -> bool:
        """하트비트 — 지금 점유자일 때만 점유를 연장한다. 놓친 점유를 새로 잡지 않는다."""

    def renew_start_request(self, request_id: str, owner: str, lease_sec: float) -> bool: ...

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
        """실행 건 삭제 때 산출물(버전 · 현재 버전 포인터)을 함께 지운다. 추적 기록은 참조만 있어 남는다(6-7)."""

    # ── 추적 기록 조회 ────────────────────────────────
    def executions(self, run_id: str) -> list[ExecutionRecord]: ...

    def call_logs(self, run_id: str) -> list[CallLog]: ...

    def feedback(self, run_id: str) -> list[FeedbackLink]: ...

    def comparisons(self, run_id: str) -> list[ReworkComparison]: ...

    def pointer_events(self, run_id: str) -> list[PointerEvent]: ...

    def events(self, run_id: str) -> list[TraceEvent]: ...

    def notifications(self, run_id: str) -> list[Notification]: ...

    def rejected_attempts(self, run_id: str) -> list[RejectedAttempt]:
        """저장된 반려된 시도 (확장 — 저장한 순서). 동의하지 않았거나 프로젝트가 없어 저장하지 않은 것은 없다."""

    # ── 관리자 조회 (확장) ─────────────────────────────
    def list_executions(self, f: ExecutionFilter) -> list[ExecutionRow]:
        """여러 실행 건의 실행 기록을 시작 시각 순으로 거른다 (같은 시각은 기록 순서)."""

    def count_executions(self, f: ExecutionFilter) -> int:
        """list_executions와 같은 조건에 맞는 실행 기록 수 (limit · offset · order는 보지 않는다)."""

    def execution_calls(self, execution_id: str) -> list[CallLog]: ...
