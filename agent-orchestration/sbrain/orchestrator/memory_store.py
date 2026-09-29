"""저장 인터페이스의 메모리 구현 (뼈대 단계 · 테스트용). 재시작하면 사라진다.

MySQL 구현은 같은 인터페이스로 나중에 교체한다.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta

from ..models import Notification, ReworkComparison, Run
from ..models.run import ACTIVE_PROGRESS
from .errors import StoreConflict
from .store import ArtifactVersion, CommitBatch
from .trace import CallLog, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent


class MemoryStore:
    def __init__(self, now=datetime.now) -> None:
        self._now = now
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
        self._leases: dict[str, tuple[str, datetime]] = {}
        self._aborts: set[str] = set()

    # ── 실행 건 ───────────────────────────────────────
    def create_run(self, run: Run, batch: CommitBatch, *, max_active: int = 1) -> bool:
        with self._lock:
            if self._count_active(run.account_id) >= max_active:
                return False
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

    def _count_active(self, account_id: str) -> int:
        return sum(1 for r in self._runs.values()
                   if r["accountId"] == account_id and r["state"]["progress"] in ACTIVE_PROGRESS)

    def runs_due_for_resume(self, now: datetime) -> list[str]:
        with self._lock:
            due = []
            for rid, r in self._runs.items():
                if r["state"]["progress"] == "재개대기" and r.get("nextResumeAt"):
                    if datetime.fromisoformat(r["nextResumeAt"]) <= now:
                        due.append(rid)
            return due

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
            return bool(held and held[1] > now)

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
        self._call_logs[run_id].extend(batch.call_logs)
        self._feedback[run_id].extend(batch.feedback)
        self._comparisons[run_id].extend(batch.comparisons)
        self._events[run_id].extend(batch.events)
        self._notifications[run_id].extend(batch.notifications)

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
