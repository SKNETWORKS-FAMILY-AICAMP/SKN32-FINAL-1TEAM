"""저장 인터페이스의 메모리 구현 (테스트 · 시연용). 재시작하면 사라진다.

MySQL 구현(sbrain/store_sql/store.py SqlStore)과 같은 동작이다. 흐름 테스트를 두 저장소로 함께 돌려 확인한다.

- 시각은 시간대 있는 UTC로 다룬다. 실행 건 JSON의 시각 문자열(옛 값은 시간대 없음 = UTC)은 as_utc로 읽어 비교한다.
- 반려된 시도는 실행 건에 프로젝트가 있고 그 주인이 학습 데이터 편입에 동의했을 때만 남긴다. 동의 여부는
  웹 DB 대신 set_training_consent로 받은 값을 저장하는 순간 본다(없으면 동의 안 함).
"""
from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

from typing import Any

from ..models import Notice, Notification, RejectedAttempt, ReworkComparison, Run
from ..models.clock import UTC_MIN, as_utc, utc_clock, utc_now
from ..models.run import ACTIVE_PROGRESS
from .errors import FileDeletionNotFound, FileDeletionNotGivenUp, ProjectRunExists, StoreConflict
from .file_deletion import FIRST_DELAY_SEC
from .store import (
    ACCOUNT_LOCK_TIMEOUT_SEC, BUSY_PROGRESS, FINISHED_REQUEST, PENDING_REQUEST, ArtifactVersion, CancelOutcome,
    CommitBatch, CreateOutcome, ExecutionFilter, ExecutionRow, FileDeletion, JobState, LogStatsRow, RunFilter,
    StartRequest, StartRequestStatus, check_summary, file_key_prefix,
)
from .trace import CallLog, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent


def _page(rows: list, limit: int | None, offset: int) -> list:
    return rows[offset:] if limit is None else rows[offset:offset + limit]


def _time(value: str) -> datetime:
    """실행 건 JSON의 시각 문자열 → 시간대 있는 UTC (옛 JSON의 시간대 없는 값은 UTC로 본다)."""
    return as_utc(datetime.fromisoformat(value))


def _collecting(run_json: dict, now: datetime) -> bool:
    """재작성 요청을 모으는 시간이 아직 끝나지 않은 실행 건 (Run.cycle.collectUntil > now) — 가져가지 않는다."""
    until = (run_json.get("cycle") or {}).get("collectUntil")
    return bool(until) and _time(until) > now


class MemoryStore:
    def __init__(self, now=utc_now) -> None:
        self._now = utc_clock(now)
        self._lock = threading.RLock()
        self._runs: dict[str, dict] = {}                         # run_id → Run JSON
        self._artifacts: dict[tuple[str, str, int], ArtifactVersion] = {}
        self._pointers: dict[str, dict[str, int]] = defaultdict(dict)
        self._latest: dict[str, dict[str, int]] = defaultdict(dict)
        self._executions: dict[str, dict[str, ExecutionRecord]] = defaultdict(dict)
        self._call_logs: dict[str, list[CallLog]] = defaultdict(list)
        self._feedback: dict[str, list[FeedbackLink]] = defaultdict(list)
        self._comparisons: dict[str, list[ReworkComparison]] = defaultdict(list)
        self._pointer_events: dict[str, list[PointerEvent]] = defaultdict(list)
        self._events: dict[str, list[TraceEvent]] = defaultdict(list)
        self._notifications: dict[str, list[Notification]] = defaultdict(list)
        self._rejected: dict[str, list[RejectedAttempt]] = defaultdict(list)
        self._training_consent: dict[str, bool] = {}            # project_id → 주인의 학습 데이터 편입 동의
        self._leases: dict[str, tuple[str, datetime]] = {}
        self._aborts: set[str] = set()
        self._requests: dict[str, StartRequest] = {}             # request_id → 시작 요청 (넣은 순서)
        self._exec_seq: dict[str, int] = {}                      # execution_id → 처음 기록된 순서 (전체)
        self._stats: list[LogStatsRow] = []                      # 통계 줄 (쓴 순서)
        self._jobs: dict[str, JobState] = {}                     # 주기 작업 상태
        self._account_locks: dict[str, threading.RLock] = {}     # 계정 잠금 (SQL의 GET_LOCK · 프로세스 잠금과 같은 뜻)
        self._account_guard = threading.Lock()
        self.account_lock_timeout: float = ACCOUNT_LOCK_TIMEOUT_SEC
        # 파일 삭제 대기열 (확장, 결정 0023) — deletion_id → 줄. 실행 건이 지워져도 남는다(기록 표가 아니다)
        self._file_deletions: dict[str, FileDeletion] = {}
        self.file_deletion_delay_sec: float = FIRST_DELAY_SEC   # 넣은 뒤 첫 시도까지 (잠정)

    # ── 실행 건 ───────────────────────────────────────
    def create_run(self, run: Run, batch: CommitBatch, *, max_active: int = 1) -> bool:
        with self._account(run.account_id), self._lock:
            if self._count_active(run.account_id) >= max_active:
                return False
            if run.project_id is not None and self._by_project(run.project_id) is not None:
                raise ProjectRunExists(run.project_id)
            self._runs[run.run_id] = run.dump()
            batch.run = None
            self._apply(run.run_id, batch)
            return True

    def load_run(self, run_id: str) -> Run:
        with self._lock:
            return Run.model_validate(self._runs[run_id])

    def list_runs(self, account_id: str) -> list[Run]:
        with self._lock:
            return [Run.model_validate(r) for r in self._runs.values() if r["accountId"] == account_id]

    def find_active_run(self, account_id: str) -> Run | None:
        with self._lock:
            for r in self._runs.values():
                if r["accountId"] == account_id and r["state"]["progress"] in ACTIVE_PROGRESS:
                    return Run.model_validate(r)
            return None

    def find_run_by_project(self, project_id: int | str) -> Run | None:
        with self._lock:
            r = self._by_project(project_id)
            return Run.model_validate(r) if r is not None else None

    def _by_project(self, project_id: int | str) -> dict | None:
        return next((r for r in self._runs.values() if r.get("projectId") == str(project_id)), None)

    def _count_active(self, account_id: str) -> int:
        return sum(1 for r in self._runs.values()
                   if r["accountId"] == account_id and r["state"]["progress"] in ACTIVE_PROGRESS)

    def set_training_consent(self, project_id: int | str, agreed: bool) -> None:
        """프로젝트 주인의 학습 데이터 편입 동의 (웹 users.ai_training_agreed 대신 — 테스트 · 시연용)."""
        with self._lock:
            self._training_consent[str(project_id)] = agreed

    def runs_due_for_resume(self, now: datetime) -> list[str]:
        now = as_utc(now)
        with self._lock:
            due = []
            for rid, r in self._runs.items():
                if r["state"]["progress"] == "재개대기" and r.get("nextResumeAt"):
                    if _time(r["nextResumeAt"]) <= now:
                        due.append(rid)
            return due

    def query_runs(self, f: RunFilter) -> list[Run]:
        with self._lock:
            pids = None if f.project_ids is None else {str(p) for p in f.project_ids}
            rows = [r for r in self._runs.values()
                    if (pids is None or r.get("projectId") in pids)
                    and (f.progress is None or r["state"]["progress"] == f.progress)
                    and (f.step is None or r["state"]["step"] == f.step)
                    and (f.updated_since is None or _time(r["updatedAt"]) >= f.updated_since)]
            rows.sort(key=lambda r: (_time(r["updatedAt"]), r["runId"]), reverse=f.order == "desc")
            return [Run.model_validate(r) for r in _page(rows, f.limit, f.offset)]

    def find_active_work(self, account_id: str) -> Run | StartRequest | None:
        with self._lock:
            active = self.find_active_run(account_id)
            if active is not None:
                return active
            pending = [r for r in self._requests.values()
                       if r.account_id == account_id and r.status in PENDING_REQUEST]
            return pending[0].model_copy(deep=True) if pending else None

    # ── 사전 단계 시작 요청 ────────────────────────────
    def add_start_request(self, req: StartRequest, *, max_active: int = 1) -> Run | StartRequest | None:
        with self._account(req.account_id), self._lock:
            active = self.find_active_run(req.account_id)
            pending = [r for r in self._requests.values()
                       if r.account_id == req.account_id and r.status in PENDING_REQUEST]
            if self._count_active(req.account_id) + len(pending) >= max_active:
                return active or pending[0].model_copy(deep=True)
            self._requests[req.request_id] = req.model_copy(deep=True)
            return None

    def get_start_request(self, request_id: str) -> StartRequest:
        with self._lock:
            return self._requests[request_id].model_copy(deep=True)

    def latest_start_request(self, project_id: int | str) -> StartRequest | None:
        with self._lock:
            mine = [r for r in self._requests.values() if r.project_id == str(project_id)]
            return mine[-1].model_copy(deep=True) if mine else None

    def latest_start_requests(self, project_ids: Iterable[int | str]) -> dict[str, StartRequest]:
        with self._lock:
            wanted = {str(p) for p in project_ids}
            latest: dict[str, StartRequest] = {}
            for r in self._requests.values():   # 넣은 순서 — 뒤의 것이 마지막
                if r.project_id in wanted:
                    latest[r.project_id] = r
            return {pid: r.model_copy(deep=True) for pid, r in latest.items()}

    def existing_projects(self, project_ids: Iterable[int]) -> set[int]:
        with self._lock:
            wanted = {str(p): p for p in project_ids}
            found = {r.project_id for r in self._requests.values() if r.status in PENDING_REQUEST}
            found |= {r.get("projectId") for r in self._runs.values()}
            return {p for key, p in wanted.items() if key in found}

    def acquire_start_request(self, request_id: str, owner: str, lease_sec: float) -> bool:
        with self._lock:
            now = self._now()
            r = self._requests.get(request_id)
            if r is None or not (r.status == "대기" or (r.status == "처리중" and (
                    r.lease_owner == owner or r.lease_until is None or r.lease_until <= now))):
                return False
            if r.lease_owner != owner:
                r.claim_count += 1
            r.status, r.lease_owner, r.lease_until, r.updated_at = "처리중", owner, now + timedelta(seconds=lease_sec), now
            return True

    def finish_start_request(self, request_id: str, owner: str, *, status: StartRequestStatus,
                             code: str | None = None, message: str | None = None,
                             detail: dict[str, Any] | None = None, notices: list[Notice] | None = None) -> bool:
        with self._lock:
            r = self._requests.get(request_id)
            if r is None or r.status != "처리중" or r.lease_owner != owner:
                return False
            self._close_request(r, status, code=code, message=message, detail=detail, notices=notices)
            return True

    def create_run_for_request(self, run: Run, batch: CommitBatch, request_id: str, owner: str, *,
                               max_active: int = 1) -> CreateOutcome:
        with self._account(run.account_id), self._lock:
            r = self._requests.get(request_id)
            if r is None or r.status != "처리중" or r.lease_owner != owner:
                return "점유잃음"
            if r.cancel_requested:
                self._close_request(r, "취소")
                return "취소"
            if not self.create_run(run, batch, max_active=max_active):
                return "동시실행"
            self._close_request(r, "완료", notices=run.notices, run_id=run.run_id)
            return "완료"

    def cancel_start_request(self, request_id: str) -> CancelOutcome:
        with self._lock:
            r = self._requests.get(request_id)
            if r is not None and r.status == "대기":
                self._close_request(r, "취소")
                return "취소"
            if r is not None and r.status == "처리중":
                r.cancel_requested, r.updated_at = True, self._now()
                return "취소요청"
            return ""

    # ── 워커 가져가기 · 점유 연장 ──────────────────────
    def claim_start_request(self, owner: str, lease_sec: float) -> str | None:
        with self._lock:
            now = self._now()
            for r in self._requests.values():   # 넣은 순서 = 오래된 순
                if r.status == "대기" or (r.status == "처리중" and (r.lease_until is None or r.lease_until <= now)):
                    self.acquire_start_request(r.request_id, owner, lease_sec)
                    return r.request_id
            return None

    def claim_ready_run(self, owner: str, lease_sec: float) -> str | None:
        with self._lock:
            now = self._now()
            ready = [r for r in self._runs.values()
                     if r["state"]["progress"] == "실행" and not _collecting(r, now)]
            return self._claim_first(sorted(ready, key=lambda r: _time(r["updatedAt"])), owner, lease_sec)

    def claim_due_resume(self, owner: str, lease_sec: float, now: datetime) -> str | None:
        now = as_utc(now)
        with self._lock:
            due = [r for r in self._runs.values() if r["state"]["progress"] == "재개대기" and r.get("nextResumeAt")
                   and _time(r["nextResumeAt"]) <= now]
            return self._claim_first(sorted(due, key=lambda r: _time(r["nextResumeAt"])), owner, lease_sec)

    def _claim_first(self, runs: list[dict], owner: str, lease_sec: float) -> str | None:
        now = self._now()
        for r in runs:
            held = self._leases.get(r["runId"])
            if held is None or held[1] <= now:
                self._leases[r["runId"]] = (owner, now + timedelta(seconds=lease_sec))
                return r["runId"]
        return None

    def renew(self, run_id: str, owner: str, lease_sec: float) -> bool:
        with self._lock:
            held = self._leases.get(run_id)
            if held is None or held[0] != owner:
                return False
            self._leases[run_id] = (owner, self._now() + timedelta(seconds=lease_sec))
            return True

    def renew_start_request(self, request_id: str, owner: str, lease_sec: float) -> bool:
        with self._lock:
            r = self._requests.get(request_id)
            if r is None or r.status != "처리중" or r.lease_owner != owner:
                return False
            r.lease_until = self._now() + timedelta(seconds=lease_sec)
            return True

    def pending_start_requests(self, project_id: int | str) -> list[StartRequest]:
        with self._lock:
            return [r.model_copy(deep=True) for r in self._requests.values()
                    if r.project_id == str(project_id) and r.status in PENDING_REQUEST]

    def clear_start_request_forms(self, project_id: int | str) -> int:
        with self._lock:
            mine = [r for r in self._requests.values() if r.project_id == str(project_id) and r.form is not None]
            for r in mine:
                r.form, r.updated_at = None, self._now()
            return len(mine)

    def _close_request(self, r: StartRequest, status: StartRequestStatus, *, code: str | None = None,
                       message: str | None = None, detail: dict[str, Any] | None = None,
                       notices: list[Notice] | None = None, run_id: str | None = None) -> None:
        now = self._now()
        r.status, r.result_code, r.result_message, r.result_detail = status, code, message, detail
        r.form = None   # 요청이 끝나면 입력 사본을 같은 변경에서 비운다 (실행 건에는 formInput 산출물로 남는다)
        r.notices, r.run_id = [n.model_copy() for n in notices or []], run_id
        r.lease_owner, r.lease_until, r.finished_at, r.updated_at = None, None, now, now

    # ── 실행 점유 ─────────────────────────────────────
    def acquire(self, run_id: str, owner: str, lease_sec: float) -> bool:
        with self._lock:
            now = self._now()
            held = self._leases.get(run_id)
            if held and held[0] != owner and held[1] > now:
                return False
            self._leases[run_id] = (owner, now + timedelta(seconds=lease_sec))
            return True

    def release(self, run_id: str, owner: str) -> None:
        with self._lock:
            held = self._leases.get(run_id)
            if held and held[0] == owner:
                del self._leases[run_id]

    def is_locked(self, run_id: str, now: datetime) -> bool:
        with self._lock:
            held = self._leases.get(run_id)
            return bool(held and held[1] > as_utc(now))

    # ── 한 번에 저장 ──────────────────────────────────
    def commit(self, run_id: str, owner: str, batch: CommitBatch) -> None:
        with self._lock:
            held = self._leases.get(run_id)
            if not held or held[0] != owner:
                raise StoreConflict(f"점유하지 않은 실행에 저장: {run_id}")
            self._apply(run_id, batch)

    def _apply(self, run_id: str, batch: CommitBatch) -> None:
        if batch.run is not None:
            self._runs[run_id] = batch.run.dump()
        for v in batch.versions:
            self._artifacts[(run_id, v.key, v.version)] = v
            self._latest[run_id][v.key] = max(self._latest[run_id].get(v.key, 0), v.version)
        self._pointers[run_id].update(batch.pointers)
        self._pointer_events[run_id].extend(batch.pointer_events)
        for rec in batch.executions.values():
            self._executions[run_id][rec.execution_id] = rec.model_copy(deep=True)
            self._exec_seq.setdefault(rec.execution_id, len(self._exec_seq))
        self._call_logs[run_id].extend(batch.call_logs)
        self._feedback[run_id].extend(batch.feedback)
        self._comparisons[run_id].extend(batch.comparisons)
        self._events[run_id].extend(batch.events)
        self._notifications[run_id].extend(batch.notifications)
        pid = self._runs.get(run_id, {}).get("projectId")
        if batch.rejected_attempts and pid is not None and self._training_consent.get(pid, False):
            self._rejected[run_id].extend(a.model_copy() for a in batch.rejected_attempts)

    # ── 중단 요청 ─────────────────────────────────────
    def request_abort(self, run_id: str) -> None:
        with self._lock:
            self._aborts.add(run_id)

    def is_abort_requested(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._aborts

    # ── 산출물 ────────────────────────────────────────
    def get_pointers(self, run_id: str) -> dict[str, int]:
        with self._lock:
            return dict(self._pointers[run_id])

    def get_latest_versions(self, run_id: str) -> dict[str, int]:
        with self._lock:
            return dict(self._latest[run_id])

    def get_artifact(self, run_id: str, key: str, version: int) -> ArtifactVersion:
        with self._lock:
            return self._artifacts[(run_id, key, version)]

    def delete_artifacts(self, run_id: str) -> None:
        with self._lock:
            for k in [k for k in self._artifacts if k[0] == run_id]:
                del self._artifacts[k]
            self._pointers.pop(run_id, None)
            self._latest.pop(run_id, None)
            self._enqueue_file_deletion(run_id)

    # ── 추적 기록 조회 ────────────────────────────────
    def executions(self, run_id: str) -> list[ExecutionRecord]:
        with self._lock:
            return list(self._executions[run_id].values())  # 처음 기록된 순서

    def call_logs(self, run_id: str) -> list[CallLog]:
        with self._lock:
            return list(self._call_logs[run_id])

    def feedback(self, run_id: str) -> list[FeedbackLink]:
        with self._lock:
            return list(self._feedback[run_id])

    def comparisons(self, run_id: str) -> list[ReworkComparison]:
        with self._lock:
            return list(self._comparisons[run_id])

    def pointer_events(self, run_id: str) -> list[PointerEvent]:
        with self._lock:
            return list(self._pointer_events[run_id])

    def events(self, run_id: str) -> list[TraceEvent]:
        with self._lock:
            return list(self._events[run_id])

    def notifications(self, run_id: str) -> list[Notification]:
        with self._lock:
            return list(self._notifications[run_id])

    def rejected_attempts(self, run_id: str) -> list[RejectedAttempt]:
        with self._lock:
            return list(self._rejected[run_id])

    # ── 관리자 조회 ───────────────────────────────────
    def list_executions(self, f: ExecutionFilter) -> list[ExecutionRow]:
        with self._lock:
            rows = self._matching_executions(f)
            rows.sort(key=lambda r: (r.record.started_at or UTC_MIN, self._exec_seq[r.record.execution_id]),
                      reverse=f.order == "desc")
            return _page(rows, f.limit, f.offset)

    def count_executions(self, f: ExecutionFilter) -> int:
        with self._lock:
            return len(self._matching_executions(f))

    def _matching_executions(self, f: ExecutionFilter) -> list[ExecutionRow]:
        rows = []
        for run_id, recs in self._executions.items():
            pid = self._runs.get(run_id, {}).get("projectId")
            for rec in recs.values():
                if ((f.project_id is None or pid == str(f.project_id))
                        and (f.task_id is None or rec.task_id == f.task_id)
                        and (f.status is None or rec.status == f.status)
                        and (f.agent is None or rec.agent == f.agent)
                        and (f.since is None or (rec.started_at is not None and rec.started_at >= f.since))
                        and (f.until is None or (rec.started_at is not None and rec.started_at < f.until))):
                    rows.append(ExecutionRow(pid, rec.model_copy(deep=True)))
        return rows

    def execution_calls(self, execution_id: str) -> list[CallLog]:
        with self._lock:
            return [c for logs in self._call_logs.values() for c in logs if c.execution_id == execution_id]

    # ── 기록 옮기기 · 보관 기간 · 탈퇴 (확장) ──────────
    @contextmanager
    def _account(self, account_id: str) -> Iterator[None]:
        """계정 잠금 — 같은 스레드는 다시 잡을 수 있다(RLock). 기다리는 시간을 넘기면 StoreConflict."""
        with self._account_guard:
            lock = self._account_locks.setdefault(account_id, threading.RLock())
        if not lock.acquire(timeout=self.account_lock_timeout):
            raise StoreConflict("계정 잠금을 얻지 못함 (대기 시간 초과)")
        try:
            yield
        finally:
            lock.release()

    def account_guard(self, account_id: str):
        return self._account(account_id)

    def list_start_requests(self, account_id: str) -> list[StartRequest]:
        with self._lock:
            return [r.model_copy(deep=True) for r in self._requests.values() if r.account_id == account_id]

    def _record_maps(self) -> tuple[dict, ...]:
        """여섯 기록 표 — 실행 기록 · 호출 기록 · 추적 사건 · 피드백 연결 · 재작성 전후 비교 · 포인터 이동."""
        return (self._executions, self._call_logs, self._events, self._feedback, self._comparisons,
                self._pointer_events)

    def _has_records(self, run_id: str) -> bool:
        return any(m.get(run_id) for m in self._record_maps())

    def has_pointers(self, run_id: str) -> bool:
        with self._lock:
            return bool(self._pointers.get(run_id))

    def retire_run(self, run_id: str, owner: str, *, stats: LogStatsRow | None = None, delete_run: bool = False,
                   bump_parts: bool = False) -> None:
        with self._lock:
            held = self._leases.get(run_id)
            if run_id not in self._runs or not held or held[0] != owner:
                raise StoreConflict("점유하지 않은 실행 건의 기록을 옮기려 함")
            if stats is not None:
                self._stats.append(replace(stats, created_at=self._now()))
            for m in self._record_maps():
                m.pop(run_id, None)
            if delete_run:
                for k in [k for k in self._artifacts if k[0] == run_id]:
                    del self._artifacts[k]
                self._pointers.pop(run_id, None)
                self._latest.pop(run_id, None)
                del self._runs[run_id]
                self._leases.pop(run_id, None)
                self._aborts.discard(run_id)
                self._enqueue_file_deletion(run_id)
            elif bump_parts:
                # 실행 건 JSON의 옮긴 횟수만 바꾼다 — updatedAt 등 다른 값은 그대로
                stored = self._runs[run_id]
                stored["statsParts"] = int(stored.get("statsParts") or 0) + 1

    def retire_start_requests(self, request_ids: list[str], stats: list[LogStatsRow]) -> int:
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("같은 시작 요청이 두 번 들어 있음")
        with self._lock:
            reqs = [self._requests.get(i) for i in request_ids]
            if any(r is None or r.status not in FINISHED_REQUEST for r in reqs):
                raise StoreConflict("없거나 끝나지 않은 시작 요청이 섞여 있음")
            now = self._now()
            self._stats.extend(replace(row, created_at=now) for row in stats)
            for i in request_ids:
                del self._requests[i]
            return len(request_ids)

    def retention_run_targets(self, cutoff: datetime, limit: int) -> list[str]:
        cutoff = as_utc(cutoff)
        with self._lock:
            now = self._now()
            rows = []
            for rid, r in self._runs.items():
                held = self._leases.get(rid)
                if (_time(r["updatedAt"]) < cutoff and r["state"]["progress"] not in BUSY_PROGRESS
                        and (held is None or held[1] <= now)
                        and (self._has_records(rid) or not self._pointers.get(rid))):
                    rows.append(r)
            rows.sort(key=lambda r: (_time(r["updatedAt"]), r["runId"]))
            return [r["runId"] for r in rows[:limit]]

    def retention_request_targets(self, cutoff: datetime, limit: int) -> list[StartRequest]:
        cutoff = as_utc(cutoff)
        with self._lock:
            rows = [r for r in self._requests.values() if r.status in FINISHED_REQUEST and r.updated_at < cutoff]
            rows.sort(key=lambda r: (r.updated_at, r.request_id))
            return [r.model_copy(deep=True) for r in rows[:limit]]

    def log_stats(self, kind: str | None = None) -> list[LogStatsRow]:
        with self._lock:
            return [r for r in self._stats if kind is None or r.kind == kind]

    # ── 주기 작업 점유 (확장) ─────────────────────────
    def try_start_job(self, job_name: str, owner: str, lease_sec: float, interval_sec: float) -> bool:
        with self._lock:
            now = self._now()
            job = self._jobs.setdefault(job_name, JobState(job_name, None, None, None, None, None))
            free = job.lease_owner is None or job.lease_until is None or job.lease_until <= now
            due = job.last_finished_at is None or job.last_finished_at <= now - timedelta(seconds=interval_sec)
            if not (free and due):
                return False
            self._jobs[job_name] = replace(job, lease_owner=owner, lease_until=now + timedelta(seconds=lease_sec),
                                           last_started_at=now)
            return True

    def _held_job(self, job_name: str, owner: str) -> JobState | None:
        job = self._jobs.get(job_name)
        return job if job is not None and job.lease_owner == owner else None

    def renew_job(self, job_name: str, owner: str, lease_sec: float) -> bool:
        with self._lock:
            job = self._held_job(job_name, owner)
            if job is None:
                return False
            self._jobs[job_name] = replace(job, lease_until=self._now() + timedelta(seconds=lease_sec))
            return True

    def finish_job(self, job_name: str, owner: str, summary: dict[str, int]) -> bool:
        summary = check_summary(summary)
        with self._lock:
            job = self._held_job(job_name, owner)
            if job is None:
                return False
            self._jobs[job_name] = replace(job, lease_owner=None, lease_until=None, last_finished_at=self._now(),
                                           last_summary=summary)
            return True

    def release_job(self, job_name: str, owner: str) -> bool:
        with self._lock:
            job = self._held_job(job_name, owner)
            if job is None:
                return False
            self._jobs[job_name] = replace(job, lease_owner=None, lease_until=None)
            return True

    def get_job(self, job_name: str) -> JobState | None:
        with self._lock:
            job = self._jobs.get(job_name)
            if job is None or job.last_summary is None:
                return job
            return replace(job, last_summary=dict(job.last_summary))

    # ── 파일 삭제 대기열 (확장, 결정 0023) ──────────────
    def _enqueue_file_deletion(self, run_id: str) -> None:
        """산출물을 지우는 같은 잠금 안에서 부른다 — 줄이 없으면 넣고, '포기'면 '대기'로 되돌리고, '대기'면 그대로."""
        now = self._now()
        next_at = now + timedelta(seconds=self.file_deletion_delay_sec)
        row = self._deletion_of_run(run_id)
        if row is None:
            did = uuid.uuid4().hex
            self._file_deletions[did] = FileDeletion(
                deletion_id=did, run_id=run_id, key_prefix=file_key_prefix(run_id), status="대기", attempts=0,
                last_error_kind=None, created_at=now, next_at=next_at)
        elif row.status == "포기":
            self._file_deletions[row.deletion_id] = replace(row, status="대기", attempts=0, next_at=next_at,
                                                            gave_up_at=None)

    def _deletion_of_run(self, run_id: str) -> FileDeletion | None:
        return next((r for r in self._file_deletions.values() if r.run_id == run_id), None)

    def claim_file_deletions(self, limit: int, hold_sec: float) -> list[FileDeletion]:
        with self._lock:
            now = self._now()
            due = sorted((r for r in self._file_deletions.values() if r.status == "대기" and r.next_at <= now),
                         key=lambda r: (r.next_at, r.deletion_id))[:limit]
            claimed = []
            for r in due:
                held = replace(r, next_at=now + timedelta(seconds=hold_sec))
                self._file_deletions[r.deletion_id] = held
                claimed.append(held)
            return claimed

    def _held_deletion(self, deletion_id: str, claimed_next_at: datetime) -> FileDeletion | None:
        r = self._file_deletions.get(deletion_id)
        return r if r is not None and r.status == "대기" and r.next_at == as_utc(claimed_next_at) else None

    def finish_file_deletion(self, deletion_id: str, claimed_next_at: datetime) -> bool:
        with self._lock:
            if self._held_deletion(deletion_id, claimed_next_at) is None:
                return False
            del self._file_deletions[deletion_id]
            return True

    def fail_file_deletion(self, deletion_id: str, claimed_next_at: datetime, error_kind: str, *, retry_sec: float,
                           max_attempts: int) -> FileDeletion | None:
        with self._lock:
            r = self._held_deletion(deletion_id, claimed_next_at)
            if r is None:
                return None
            now = self._now()
            attempts = r.attempts + 1
            if attempts >= max_attempts:
                r = replace(r, status="포기", attempts=attempts, last_error_kind=error_kind, last_tried_at=now,
                            gave_up_at=now)
            else:
                r = replace(r, attempts=attempts, last_error_kind=error_kind, last_tried_at=now,
                            next_at=now + timedelta(seconds=retry_sec))
            self._file_deletions[deletion_id] = r
            return r

    def get_file_deletion(self, deletion_id: str) -> FileDeletion | None:
        with self._lock:
            return self._file_deletions.get(deletion_id)

    def file_deletion_for_run(self, run_id: str) -> FileDeletion | None:
        with self._lock:
            return self._deletion_of_run(run_id)

    def list_file_deletions(self, status: str | None = None, limit: int | None = 50,
                            offset: int = 0) -> list[FileDeletion]:
        with self._lock:
            rows = [r for r in self._file_deletions.values() if status is None or r.status == status]
            rows.sort(key=lambda r: (r.created_at, r.deletion_id), reverse=True)
            return _page(rows, limit, offset)

    def retry_file_deletion(self, deletion_id: str, admin_id: str) -> FileDeletion:
        with self._lock:
            r = self._file_deletions.get(deletion_id)
            if r is None:
                raise FileDeletionNotFound("없는 파일 삭제 대기열 줄")
            if r.status != "포기":
                raise FileDeletionNotGivenUp("포기가 아닌 줄은 다시 시도하지 않는다")
            now = self._now()
            r = replace(r, status="대기", attempts=0, next_at=now, gave_up_at=None, retried_by=str(admin_id),
                        retried_at=now, retry_count=r.retry_count + 1)
            self._file_deletions[deletion_id] = r
            return r
