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
- 시작 요청이 끝나면(완료 · 실패 · 취소) 상태를 바꾸는 같은 변경에서 입력 사본(form)을 비운다. 대기 · 처리중은 남긴다.
- 기록 옮기기(확장): 보관 기간이 지난 실행 건의 기록을 식별자 없는 통계 줄(LogStatsRow)로 옮기고 지운다(retire_run ·
  retire_start_requests). 실행 건 점유를 잡은 쪽만 하고, 마지막 활동 시각을 바꾸지 않는다. 주기 작업은 작업 점유
  (try_start_job …)로 여러 워커 중 하나만 돈다.
"""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field

from ..models import Notice, Notification, RejectedAttempt, ReworkComparison, Run
from ..models.base import SBModel
from ..models.clock import as_utc
from .trace import CallLog, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent

StartRequestStatus = Literal["대기", "처리중", "완료", "실패", "취소"]
PENDING_REQUEST = ("대기", "처리중")
FINISHED_REQUEST = ("완료", "실패", "취소")
# 기록 옮기기 대상에서 빼는 진행 상태 — 워커가 단계를 돌거나 재개를 기다리는 실행 건
BUSY_PROGRESS = ("실행", "재개대기")
ACCOUNT_LOCK_TIMEOUT_SEC = 10   # 계정 잠금 대기 (잠정)
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
    """관리자 실행 기록 조회 조건 (확장). 시각은 시작 시각 기준 — since 이상, until 미만. limit이 None이면 모두.

    since · until은 시간대 있는 UTC로 바꿔 둔다 (웹이 넘기는 시간대 없는 값은 UTC로 본다).
    """
    project_id: int | str | None = None
    task_id: str | None = None
    status: str | None = None
    agent: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int | None = 50
    offset: int = 0
    order: Literal["desc", "asc"] = "desc"

    def __post_init__(self) -> None:
        object.__setattr__(self, "since", as_utc(self.since))
        object.__setattr__(self, "until", as_utc(self.until))


@dataclass(frozen=True)
class RunFilter:
    """여러 실행 건 조회 조건 (확장) — 관리자 실행 건 목록 · 운영 요약 · 여러 프로젝트 보기.

    마지막 갱신 시각(updatedAt) 순(같으면 run_id 순). project_ids가 있으면 그 프로젝트들의 실행 건만(빈 묶음이면 없음).
    updated_since가 있으면 마지막 갱신 시각이 그 시각 이상인 것만 (시간대 없는 값은 UTC로 본다).
    limit이 None이면 모두.
    """
    project_ids: tuple[int | str, ...] | None = None
    progress: str | None = None
    step: str | None = None
    limit: int | None = 50
    offset: int = 0
    order: Literal["desc", "asc"] = "desc"
    updated_since: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "updated_since", as_utc(self.updated_since))


@dataclass(frozen=True)
class LogStatsRow:
    """기록 통계 줄 한 줄 (확장 — orch_log_stats). 식별자 · 자유 글이 없는 개수 줄이다.

    값은 부르는 쪽이 정하고 저장소는 그대로 저장한다(뜻을 보지 않는다). created_at은 저장소가 쓴 시각(UTC)이고,
    넣을 때는 비워 둔다(읽을 때 채워진다).
    """
    kind: str                       # 줄 종류
    reason: str                     # 옮긴 까닭
    month: str                      # 'YYYY-MM'
    category: str | None = None
    status: str | None = None
    result_code: str | None = None
    part: int = 1                   # 같은 대상에서 몇 번째로 옮긴 기록인지
    count: int = 1
    data: dict[str, Any] | None = None   # 개수 묶음 (JSON)
    created_at: datetime | None = None


@dataclass(frozen=True)
class JobState:
    """주기 작업 상태 한 줄 (확장 — orch_jobs). last_summary는 개수만."""
    job_name: str
    lease_owner: str | None
    lease_until: datetime | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_summary: dict[str, int] | None


def check_summary(summary: dict[str, int]) -> dict[str, int]:
    """작업 요약은 개수만 — 키는 글자, 값은 정수(bool 아님). 아니면 ValueError (값은 메시지에 싣지 않는다)."""
    if not isinstance(summary, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) for k, v in summary.items()):
        raise ValueError("작업 요약은 {글자: 정수}만 받는다")
    return dict(summary)


FileDeletionStatus = Literal["대기", "포기"]
FILE_DELETION_STATUSES: tuple[str, ...] = ("대기", "포기")


@dataclass(frozen=True)
class FileDeletion:
    """파일 삭제 대기열 한 줄 (확장 — orch_file_deletions). 실행 건 하나의 파일 전체 삭제 요청.

    계정 · 프로젝트 ID, 파일 이름 · 키, 오류 메시지는 없다. 사람을 가리키는 값은 retried_by(관리자 ID)뿐이다.
    시각은 시간대 있는 UTC다. next_at은 워커가 가져가면 미뤄지고, 그 값이 가져간 표시(성공 · 실패 기록의 확인 값)다.
    """
    deletion_id: str
    run_id: str
    key_prefix: str                 # '<runId>/'
    status: FileDeletionStatus
    attempts: int                   # 이번 대기 이후 실패한 시도 수
    last_error_kind: str | None     # 일시 · 입력 · 운영
    created_at: datetime
    next_at: datetime
    last_tried_at: datetime | None = None
    gave_up_at: datetime | None = None
    retried_by: str | None = None
    retried_at: datetime | None = None
    retry_count: int = 0


def file_key_prefix(run_id: str) -> str:
    """실행 건의 파일 키 접두어 — 파일 키의 첫 마디가 실행 건 ID다(models.files 키 규칙)."""
    return f"{run_id}/"


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

    def existing_projects(self, project_ids: Iterable[int]) -> set[int]:
        """넘긴 프로젝트 중 실행 건이 있거나 끝나지 않은(대기 · 처리중) 시작 요청이 있는 것 (확장 — missing_projects용).

        실행 건은 find_run_by_project와 같은 기준(실행 건 줄의 project_id)으로 찾는다. 시작 요청을 먼저 보고 실행 건을
        나중에 본다 — 그 사이에 요청이 실행 건이 되어도 빠뜨리지 않는다. 잠금 없이 읽기만 한다. 개수 제한은 없다.
        """

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
        """실행 건 삭제 때 산출물(버전 · 현재 버전 포인터)을 함께 지운다. 추적 기록은 참조만 있어 남는다(6-7).

        같은 트랜잭션에서 그 실행 건의 파일 삭제 대기열 줄을 넣는다(enqueue 규칙은 아래 '파일 삭제 대기열'). 산출물이
        없어도 넣는다.
        """

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

    # ── 기록 옮기기 · 보관 기간 · 탈퇴 (확장) ──────────
    # 예외 메시지에 계정 · 프로젝트 · 실행 건 · 요청 ID를 넣지 않는다. 통계 줄 · 작업 요약 값은 부르는 쪽이 정하고
    # 저장소는 뜻을 보지 않고 저장한다.
    def list_start_requests(self, account_id: str) -> list[StartRequest]:
        """계정의 시작 요청 전부 (넣은 순서)."""

    def account_guard(self, account_id: str) -> AbstractContextManager[None]:
        """계정 잠금을 잡은 채로 있는 구간 — add_start_request · create_run · create_run_for_request와 같은 잠금.

        잡은 동안 그 계정의 add_start_request 등은 기다린다. 기다리는 시간(account_lock_timeout, 기본 10초 잠정)을
        넘기면 StoreConflict. 이 구간 안에서 같은 계정의 add_start_request · create_run · create_run_for_request를
        부르지 않는다(MySQL은 다른 연결이라 자기 잠금을 기다린다).
        """

    def retire_run(self, run_id: str, owner: str, *, stats: LogStatsRow | None = None, delete_run: bool = False,
                   bump_parts: bool = False) -> None:
        """실행 건 하나의 기록을 옮긴다 — 한 트랜잭션. 점유자(owner)가 아니면 StoreConflict(아무것도 바꾸지 않음).

        stats가 있으면 통계 줄 하나를 쓰고, 여섯 기록 표(실행 기록 · 호출 기록 · 추적 사건 · 피드백 연결 ·
        재작성 전후 비교 · 포인터 이동)에서 그 실행 건의 줄을 지운다.
        delete_run이면 산출물 버전 · 포인터와 실행 건 줄도 지우고(웹 테이블은 건드리지 않는다), 같은 트랜잭션에서 파일 삭제
        대기열 줄을 넣는다.
        아니면 실행 건 줄 · 산출물은 남기고, bump_parts면 Run.stats_parts만 1 올린다 — 마지막 활동 시각
        (updated_at 컬럼 · run_json의 updatedAt)과 점유는 바꾸지 않는다. 점유는 부른 쪽이 푼다.
        """

    def retire_start_requests(self, request_ids: list[str], stats: list[LogStatsRow]) -> int:
        """끝난 시작 요청(완료 · 실패 · 취소)을 지우고 통계 줄을 쓴다 — 한 트랜잭션. 지운 요청 수.

        넘긴 요청 중 하나라도 없거나 끝나지 않았으면 StoreConflict(아무것도 바꾸지 않음) — 다른 곳이 먼저 지웠으면
        개수가 두 번 세지지 않게.
        """

    def retention_run_targets(self, cutoff: datetime, limit: int) -> list[str]:
        """기록을 옮길 실행 건 ID (마지막 활동 시각이 오래된 순, 최대 limit).

        조건: 마지막 활동 시각(updated_at) < cutoff, 진행 상태가 실행 · 재개대기가 아님, 점유 중이 아님(비었거나 만료),
        그리고 (여섯 기록 표에 옮길 줄이 있음 또는 산출물 포인터가 하나도 없음). 잠금 없이 읽는다 — 부르는 쪽이
        점유를 잡고(acquire) 다시 확인한다.
        """

    def retention_request_targets(self, cutoff: datetime, limit: int) -> list[StartRequest]:
        """끝난 시작 요청(완료 · 실패 · 취소) 중 updated_at < cutoff인 것 (오래된 순, 최대 limit). 잠금 없이 읽는다."""

    def has_pointers(self, run_id: str) -> bool:
        """산출물 포인터가 하나라도 있는지 — 없으면 완전 삭제된 실행 건이다."""

    def log_stats(self, kind: str | None = None) -> list[LogStatsRow]:
        """저장된 통계 줄 (쓴 순서). 확인 · 테스트용 — 웹 함수가 아니다."""

    # ── 주기 작업 점유 (확장) ─────────────────────────
    def try_start_job(self, job_name: str, owner: str, lease_sec: float, interval_sec: float) -> bool:
        """시작 조건 확인과 점유 기록을 한 트랜잭션으로. 작업 줄이 없으면 만든다.

        조건: 점유가 비었거나 만료됐고, last_finished_at이 없거나 지금 − interval_sec 이전(이하). 시작하면
        lease_owner = owner, lease_until = 지금 + lease_sec, last_started_at = 지금. 같은 점유자라도 점유 중이면 False.
        """

    def renew_job(self, job_name: str, owner: str, lease_sec: float) -> bool:
        """하트비트 — 지금 점유자일 때만 연장한다. 만료됐어도 아직 아무도 이어받지 않았으면 연장된다."""

    def finish_job(self, job_name: str, owner: str, summary: dict[str, int]) -> bool:
        """끝까지 마침 — 점유자일 때만 last_finished_at = 지금, last_summary = summary(개수만), 점유를 푼다."""

    def release_job(self, job_name: str, owner: str) -> bool:
        """종료 신호 — 점유자일 때만 점유를 푼다. last_finished_at · last_summary는 그대로."""

    def get_job(self, job_name: str) -> JobState | None: ...

    # ── 파일 삭제 대기열 (확장) ──────────────
    # 넣기는 delete_artifacts · retire_run(delete_run=True)가 같은 트랜잭션에서 한다(따로 부르는 메서드 없음).
    #   줄이 없으면 '대기' 줄(next_at = 지금 + file_deletion_delay_sec), '대기' 줄이 있으면 그대로, '포기' 줄이면 '대기'로
    #   되돌린다(attempts=0, next_at = 지금 + 지연, gave_up_at 비움 — retried_by · retried_at · retry_count는 그대로).
    #   동시에 두 곳이 넣어 고유 제약(run_id)에 걸려도 오류가 아니다(있는 줄에 같은 규칙).
    # 저장소는 file_deletion_delay_sec(첫 시도 지연, 기본 600초 잠정) 속성을 갖는다.
    def claim_file_deletions(self, limit: int, hold_sec: float) -> list[FileDeletion]:
        """next_at이 지난 '대기' 줄을 최대 limit개 가져간다(next_at 순). 줄마다 조건부 갱신으로 next_at을 지금 + hold_sec로
        미뤄 한 워커만 가져간다. 돌려주는 줄의 next_at은 미룬 값이다(성공 · 실패 기록의 확인 값)."""

    def finish_file_deletion(self, deletion_id: str, claimed_next_at: datetime) -> bool:
        """파일을 지웠다 — 가져간 그대로인 줄(대기 · next_at 같음)이면 줄을 지운다. 아니면 False(다른 워커가 이어받음)."""

    def fail_file_deletion(self, deletion_id: str, claimed_next_at: datetime, error_kind: str, *, retry_sec: float,
                           max_attempts: int) -> FileDeletion | None:
        """파일 지우기 실패 — attempts +1, last_error_kind · last_tried_at을 적고 next_at = 지금 + retry_sec.
        attempts가 max_attempts에 이르면 status='포기' · gave_up_at = 지금. 가져간 그대로인 줄이 아니면 None."""

    def get_file_deletion(self, deletion_id: str) -> FileDeletion | None: ...

    def file_deletion_for_run(self, run_id: str) -> FileDeletion | None:
        """실행 건의 대기열 줄 (실행 건 하나에 많아야 하나)."""

    def list_file_deletions(self, status: str | None = None, limit: int | None = 50,
                            offset: int = 0) -> list[FileDeletion]:
        """대기열 줄 목록 — created_at 최근 순(같으면 deletion_id 역순). status로 '대기' · '포기'를 거른다. limit이 None이면 모두."""

    def retry_file_deletion(self, deletion_id: str, admin_id: str) -> FileDeletion:
        """'포기' 줄을 다시 시도 — 한 트랜잭션으로 status='대기', attempts=0, next_at = 지금, gave_up_at 비움,
        retried_by = admin_id, retried_at = 지금, retry_count +1. 바뀐 줄을 돌려준다.
        없는 줄이면 FileDeletionNotFound, '포기'가 아니면 FileDeletionNotGivenUp (아무것도 바꾸지 않음)."""
