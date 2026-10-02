"""실행 Context — 산출물 버전 관리와 한 번에 저장할 기록 모음.

- 산출물은 이름별로 버전을 쌓고, 현재 버전 포인터가 '지금 쓰는 값'을 가리킨다.
- 되돌리기는 포인터만 옮긴다. 이전 버전과 기록은 지우지 않는다.
- 불변 산출물(featureList)은 첫 버전 이후 값이 바뀌지 않는다. 같은 값이면 기존 버전을 가리키고,
  다른 값이면 ImmutableArtifactError를 올려 기록만 남긴다(시트 2 T-W1 L③).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from pydantic import TypeAdapter

from ..models import AttemptRef, Notification, RejectedAttempt, ReworkComparison, Run
from .settings import Settings
from .store import ArtifactVersion, CommitBatch, Store
from .trace import ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent

_MISSING = object()


class ImmutableArtifactError(Exception):
    pass


class ArtifactTypes:
    """산출물 키 → 타입. 정확히 맞는 키가 없으면 접미 규칙을 본다."""

    def __init__(self, exact: dict[str, Any], suffix: dict[str, Any] | None = None) -> None:
        self._exact = {k: TypeAdapter(t) for k, t in exact.items()}
        self._suffix = {k: TypeAdapter(t) for k, t in (suffix or {}).items()}
        self._any = TypeAdapter(Any)

    def adapter(self, key: str) -> TypeAdapter:
        if key in self._exact:
            return self._exact[key]
        for suf, ad in self._suffix.items():
            if key.endswith(suf) or key.startswith(suf):
                return ad
        return self._any


def parse_ref(ref: str) -> tuple[str, int]:
    key, _, ver = ref.rpartition("@")
    return key, int(ver)


class RunContext:
    def __init__(
        self,
        store: Store,
        run: Run,
        owner: str,
        types: ArtifactTypes,
        now: Callable[[], datetime],
        immutable_keys: frozenset[str] = frozenset(),
        provisional: bool = False,
    ) -> None:
        self.store = store
        self.run = run
        self.owner = owner
        self.types = types
        self.now = now
        self.immutable_keys = immutable_keys
        self.provisional = provisional
        rid = run.run_id
        self.pointers: dict[str, int] = {} if provisional else store.get_pointers(rid)
        self.latest: dict[str, int] = {} if provisional else store.get_latest_versions(rid)
        self._pending: dict[tuple[str, int], ArtifactVersion] = {}
        self._cache: dict[tuple[str, int], Any] = {}
        self._attempts: dict[str, int] = {}
        if not provisional:
            for rec in store.executions(rid):
                self._attempts[rec.task_id] = max(self._attempts.get(rec.task_id, 0), rec.attempt)
        self._settings: Settings | None = None
        self.batch = CommitBatch()
        # 사전 단계(실행 건 생성 전)는 저장하지 않고 모아 두었다가 실행 건 생성 때 한 번에 저장한다
        self.provisional_batch = CommitBatch() if provisional else None

    # ── 설정 ─────────────────────────────────────────
    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = Settings.model_validate(self.run.settings_snapshot)
        return self._settings

    # ── 산출물 읽기 ───────────────────────────────────
    def has(self, key: str) -> bool:
        return key in self.pointers

    def version(self, key: str) -> int | None:
        return self.pointers.get(key)

    def ref(self, key: str) -> str:
        return f"{key}@{self.pointers[key]}"

    def get(self, key: str, version: int | None = None, default: Any = _MISSING) -> Any:
        if version is None:
            if key not in self.pointers:
                if default is _MISSING:
                    raise KeyError(f"산출물 없음: {key}")
                return default
            version = self.pointers[key]
        ck = (key, version)
        if ck not in self._cache:
            av = self._pending.get(ck) or self.store.get_artifact(self.run.run_id, key, version)
            self._cache[ck] = self.types.adapter(key).validate_python(av.value)
        return self._cache[ck]

    def get_ref(self, ref: str) -> Any:
        key, ver = parse_ref(ref)
        return self.get(key, ver)

    def producer_of(self, ref: str) -> str:
        """산출물 버전을 만든 쪽 (실행 ID 또는 'user:…' · 'orchestrator:…')."""
        key, ver = parse_ref(ref)
        av = self._pending.get((key, ver)) or self.store.get_artifact(self.run.run_id, key, ver)
        return av.producer

    # ── 산출물 쓰기 ───────────────────────────────────
    def put(self, key: str, value: Any, producer: str) -> str:
        adapter = self.types.adapter(key)
        json_value = adapter.dump_python(value, mode="json", by_alias=True)
        if key in self.immutable_keys and key in self.pointers:
            current = adapter.dump_python(self.get(key), mode="json", by_alias=True)
            if current == json_value:
                return self.ref(key)
            raise ImmutableArtifactError(key)
        version = self.latest.get(key, 0) + 1
        av = ArtifactVersion(self.run.run_id, key, version, json_value, producer, self.now())
        self._pending[(key, version)] = av
        self.latest[key] = version
        self.pointers[key] = version
        self.batch.versions.append(av)
        self.batch.pointers[key] = version
        return av.ref

    def move_pointer(self, key: str, to_version: int, reason: str, cycle_id: str | None = None) -> None:
        before = self.pointers.get(key)
        if before == to_version:
            return
        self.pointers[key] = to_version
        self.batch.pointers[key] = to_version
        self.batch.pointer_events.append(PointerEvent(
            run_id=self.run.run_id, key=key, from_version=before, to_version=to_version,
            reason=reason, cycle_id=cycle_id, at=self.now()))

    # ── 기록 ─────────────────────────────────────────
    def next_attempt(self, task_id: str) -> int:
        self._attempts[task_id] = self._attempts.get(task_id, 0) + 1
        return self._attempts[task_id]

    def find_execution(self, execution_id: str) -> ExecutionRecord | None:
        if execution_id in self.batch.executions:
            return self.batch.executions[execution_id]
        if self.provisional:
            return None
        for rec in self.store.executions(self.run.run_id):
            if rec.execution_id == execution_id:
                return rec.model_copy(deep=True)
        return None

    def record_execution(self, rec: ExecutionRecord) -> None:
        self.batch.executions[rec.execution_id] = rec

    def record_attempt(self, rec: ExecutionRecord) -> None:
        self.run.attempts.append(AttemptRef(
            task_id=rec.task_id, attempt=rec.attempt, trigger=rec.trigger,
            bundle_id=rec.bundle_id, result_ref=rec.result_ref, created_at=rec.created_at))

    def add_feedback(self, link: FeedbackLink) -> None:
        self.batch.feedback.append(link)

    def add_comparison(self, comp: ReworkComparison) -> None:
        self.batch.comparisons.append(comp)

    def add_event(self, kind: str, detail: str, refs: list[str] | None = None,
                  execution_id: str | None = None) -> None:
        self.batch.events.append(TraceEvent(
            run_id=self.run.run_id, kind=kind, detail=detail, refs=refs or [],
            execution_id=execution_id,
            cycle_id=self.run.cycle.cycle_id if self.run.cycle else None, at=self.now()))

    def notify(self, notification: Notification) -> None:
        self.batch.notifications.append(notification)

    def add_rejected_attempt(self, attempt: RejectedAttempt) -> None:
        """반려된 시도 — 저장소가 주인 계정의 학습 동의를 확인해 같은 저장에서 쓴다 (내용 포함, 기록 · 로그와 별도)."""
        self.batch.rejected_attempts.append(attempt)

    # ── 한 번에 저장 ──────────────────────────────────
    def commit(self) -> None:
        self.run.updated_at = self.now()
        if self.provisional:
            self._merge_into_provisional()
            return
        self.batch.run = self.run
        self.store.commit(self.run.run_id, self.owner, self.batch)
        self._pending.clear()
        self.batch = CommitBatch()

    def _merge_into_provisional(self) -> None:
        pb, b = self.provisional_batch, self.batch
        assert pb is not None
        pb.versions += b.versions
        pb.pointers.update(b.pointers)
        pb.pointer_events += b.pointer_events
        pb.executions.update(b.executions)
        pb.call_logs += b.call_logs
        pb.feedback += b.feedback
        pb.comparisons += b.comparisons
        pb.events += b.events
        pb.notifications += b.notifications
        pb.rejected_attempts += b.rejected_attempts
        self.batch = CommitBatch()

    def take_provisional(self) -> CommitBatch:
        self._merge_into_provisional()
        assert self.provisional_batch is not None
        return self.provisional_batch
