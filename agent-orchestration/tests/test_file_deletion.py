"""파일 삭제 대기열 (spec 4.6) — 저장소 계약(메모리 · SQLite · MySQL 8), 흐름의 넣기, 워커 처리.

- 넣기: 완전 삭제(delete_artifacts) · 12개월 정리(retire_run(delete_run=True)) · 탈퇴가 같은 트랜잭션에서 넣는다.
  실행 건 하나에 줄 하나 — '대기'면 그대로, '포기'면 '대기'로 되돌린다. 동시에 넣어도 오류가 아니다.
- 워커: 넣은 뒤 10분(잠정)이 지나야 지우고, 성공하면 줄을 지운다. 3번 실패하면 '포기'. 여러 워커가 같은 줄을 처리하지 않는다.
- 운영 로그 줄에는 실행 건 · 대기열 줄 번호까지만 — 키 · 파일 이름은 없다.

여러 테스트가 같은 MySQL DB를 쓰므로 실행 건 ID는 테스트마다 새로 만들고, 목록은 자기 줄만 보고 확인한다.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

import pytest
from conftest import TIMING, Clock, make_app, start_and_select
from store_helpers import new_run, uid
from worker_helpers import app_on, projects, worker

from sbrain.flow.retention import run_retention, start_retention
from sbrain.orchestrator.errors import FileDeletionNotFound, FileDeletionNotGivenUp
from sbrain.orchestrator.file_deletion import (
    BATCH_SIZE, FIRST_DELAY_SEC, MAX_ATTEMPTS, RETRY_SEC, error_kind_of, process_file_deletions,
)
from sbrain.orchestrator.files import FileMeta, LocalFolderFileStore, MemoryFileStore, sha256_hex
from sbrain.orchestrator.memory_store import MemoryStore
from sbrain.orchestrator.runlog import RUN_LOGGER
from sbrain.orchestrator.settings import PROVISIONAL
from sbrain.orchestrator.store import CommitBatch, FileDeletion, Store

DELAY = timedelta(seconds=FIRST_DELAY_SEC)


@pytest.fixture
def env(any_backend):
    clock = Clock()
    return any_backend.make_store(clock), clock


@pytest.fixture
def runlog():
    """sbrain.run 로거에 목록 처리기를 단다 (테스트가 끝나면 뗀다)."""
    logger = logging.getLogger(RUN_LOGGER)
    lines: list[str] = []

    class Lines(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(record.getMessage())
    h, level = Lines(logging.INFO), logger.level
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    yield lines
    logger.removeHandler(h)
    logger.setLevel(level)


def row_of(store: Store, run_id: str) -> FileDeletion:
    row = store.file_deletion_for_run(run_id)
    assert row is not None
    return row


def claim_one(store: Store, run_id: str, hold: float = RETRY_SEC) -> FileDeletion:
    """그 실행 건의 줄을 가져간다 (MySQL은 다른 테스트의 줄도 가져갈 수 있어 자기 줄만 고른다)."""
    mine = [r for r in store.claim_file_deletions(1000, hold) if r.run_id == run_id]
    assert len(mine) == 1
    return mine[0]


def give_up(store: Store, clock: Clock, run_id: str) -> FileDeletion:
    """그 실행 건의 줄을 MAX_ATTEMPTS번 실패시켜 '포기'로 만든다."""
    row = row_of(store, run_id)
    clock.t = max(clock.t, row.next_at)
    for i in range(MAX_ATTEMPTS):
        held = claim_one(store, run_id)
        row = store.fail_file_deletion(held.deletion_id, held.next_at, "일시", retry_sec=RETRY_SEC,
                                       max_attempts=MAX_ATTEMPTS)
        assert row is not None and row.attempts == i + 1
        clock.advance(seconds=RETRY_SEC + 1)
    assert row.status == "포기"
    return row


def held_run(store: Store, clock: Clock, owner: str = "w1"):
    run = new_run(clock, uid(), progress="완료")
    assert store.create_run(run, CommitBatch()) and store.acquire(run.run_id, owner, 60)
    return run


# ── 넣기 ──────────────────────────────────────────────
def test_delete_artifacts_enqueues_one_waiting_row(env):
    store, clock = env
    rid = uid()
    store.delete_artifacts(rid)                                                   # 산출물이 없어도 넣는다
    row = row_of(store, rid)
    assert (row.status, row.attempts, row.key_prefix, row.retry_count) == ("대기", 0, f"{rid}/", 0)
    assert row.next_at == row.created_at + DELAY                                  # 첫 시도는 넣은 시각 + 10분
    assert row.last_error_kind is row.last_tried_at is row.gave_up_at is row.retried_by is row.retried_at is None
    assert store.get_file_deletion(row.deletion_id) == row
    clock.advance(seconds=30)
    store.delete_artifacts(rid)                                                   # '대기' 줄이 있으면 그대로
    assert row_of(store, rid) == row
    assert [r for r in store.list_file_deletions(limit=None) if r.run_id == rid] == [row]   # 실행 건 하나에 줄 하나


def test_retire_run_delete_run_enqueues_and_row_outlives_run(env):
    store, clock = env
    kept, deleted = held_run(store, clock), held_run(store, clock)
    store.retire_run(kept.run_id, "w1", bump_parts=True)                          # 실행 건을 남기는 정리는 넣지 않는다
    assert store.file_deletion_for_run(kept.run_id) is None
    store.retire_run(deleted.run_id, "w1", delete_run=True)
    with pytest.raises(KeyError):
        store.load_run(deleted.run_id)
    row = row_of(store, deleted.run_id)                                           # 실행 건 줄이 지워져도 남는다
    assert row.status == "대기" and row.key_prefix == f"{deleted.run_id}/"


def test_given_up_row_goes_back_to_waiting_on_enqueue(env):
    store, clock = env
    rid = uid()
    store.delete_artifacts(rid)
    first = give_up(store, clock, rid)
    retried = store.retry_file_deletion(first.deletion_id, "admin-7")
    give_up(store, clock, rid)                                                    # 다시 시도한 뒤에도 포기
    clock.advance(seconds=5)
    store.delete_artifacts(rid)                                                   # 다시 넣으면 '대기'로 되돌린다
    row = row_of(store, rid)
    assert row.deletion_id == first.deletion_id and row.status == "대기" and row.attempts == 0
    assert row.gave_up_at is None and row.created_at == first.created_at
    assert row.next_at == clock.t + DELAY                                         # 다시 넣은 지금 + 첫 시도 지연
    assert (row.retried_by, row.retried_at, row.retry_count) == ("admin-7", retried.retried_at, 1)   # 그대로
    assert row.last_error_kind == "일시"


@TIMING
def test_concurrent_enqueue_is_not_an_error(env):
    """동시에 여러 곳이 같은 실행 건을 넣어도 고유 제약 오류가 없고 줄은 하나다."""
    store, _ = env
    rid = uid()
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def go() -> None:
        barrier.wait()
        try:
            store.delete_artifacts(rid)
        except BaseException as e:   # noqa: BLE001 — 오류가 없어야 한다
            errors.append(e)
    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len([r for r in store.list_file_deletions(limit=None) if r.run_id == rid]) == 1


# ── 가져가기 · 성공 · 실패 · 포기 ────────────────────────
def test_claim_waits_for_delay_and_holds_row(env):
    store, clock = env
    rid = uid()
    store.delete_artifacts(rid)
    assert all(r.run_id != rid for r in store.claim_file_deletions(1000, RETRY_SEC))   # 10분 전에는 가져가지 않는다
    clock.t = row_of(store, rid).next_at
    held = claim_one(store, rid)
    assert held.next_at > clock.t and row_of(store, rid).next_at == held.next_at  # 가져가며 next_at을 미룬다
    assert all(r.run_id != rid for r in store.claim_file_deletions(1000, RETRY_SEC))   # 다른 워커는 가져가지 못한다
    assert not store.finish_file_deletion(held.deletion_id, held.next_at - timedelta(seconds=1))   # 표시가 다르면 못 지움
    assert store.finish_file_deletion(held.deletion_id, held.next_at)            # 성공 → 줄을 지운다
    assert store.file_deletion_for_run(rid) is None and store.get_file_deletion(held.deletion_id) is None
    assert not store.finish_file_deletion(held.deletion_id, held.next_at)


def test_failures_retry_then_give_up_at_three(env):
    store, clock = env
    rid = uid()
    store.delete_artifacts(rid)
    clock.t = row_of(store, rid).next_at
    held = claim_one(store, rid)
    row = store.fail_file_deletion(held.deletion_id, held.next_at, "일시", retry_sec=RETRY_SEC,
                                   max_attempts=MAX_ATTEMPTS)
    assert (row.status, row.attempts, row.last_error_kind) == ("대기", 1, "일시")
    assert row.next_at == row.last_tried_at + timedelta(seconds=RETRY_SEC) and row_of(store, rid) == row
    assert all(r.run_id != rid for r in store.claim_file_deletions(1000, RETRY_SEC))   # 다시 시도 간격 전에는 안 가져감
    clock.advance(seconds=RETRY_SEC + 1)
    held = claim_one(store, rid)
    row = store.fail_file_deletion(held.deletion_id, held.next_at, "입력", retry_sec=RETRY_SEC,
                                   max_attempts=MAX_ATTEMPTS)
    assert (row.status, row.attempts, row.last_error_kind) == ("대기", 2, "입력")
    clock.advance(seconds=RETRY_SEC + 1)
    held = claim_one(store, rid)
    row = store.fail_file_deletion(held.deletion_id, held.next_at, "운영", retry_sec=RETRY_SEC,
                                   max_attempts=MAX_ATTEMPTS)
    assert (row.status, row.attempts) == ("포기", 3) and row.gave_up_at == row.last_tried_at
    assert row_of(store, rid) == row
    clock.advance(days=30)
    assert all(r.run_id != rid for r in store.claim_file_deletions(1000, RETRY_SEC))   # 포기한 줄은 가져가지 않는다


def test_lost_claim_cannot_record(env):
    """가져간 줄을 미룬 시간이 지나 다른 워커가 이어받으면 먼저 가져간 쪽은 성공 · 실패를 적지 못한다."""
    store, clock = env
    rid = uid()
    store.delete_artifacts(rid)
    clock.t = row_of(store, rid).next_at
    first = claim_one(store, rid, hold=60)
    clock.advance(seconds=61)
    second = claim_one(store, rid, hold=60)
    assert store.fail_file_deletion(first.deletion_id, first.next_at, "일시", retry_sec=RETRY_SEC,
                                    max_attempts=MAX_ATTEMPTS) is None
    assert not store.finish_file_deletion(first.deletion_id, first.next_at)
    assert row_of(store, rid).attempts == 0
    assert store.finish_file_deletion(second.deletion_id, second.next_at)


@TIMING
def test_concurrent_claims_take_each_row_once(env):
    store, clock = env
    rids = [uid() for _ in range(8)]
    for rid in rids:
        store.delete_artifacts(rid)
    clock.advance(seconds=FIRST_DELAY_SEC + 1)
    taken: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def go() -> None:
        barrier.wait()
        while True:   # 빌 때까지 (MySQL은 다른 테스트가 남긴 줄도 함께 가져간다)
            got = store.claim_file_deletions(2, RETRY_SEC)
            if not got:
                return
            with lock:
                taken.extend(r.run_id for r in got)
    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    mine = [r for r in taken if r in rids]
    assert sorted(mine) == sorted(rids)                                           # 줄마다 한 번만


# ── 관리자 목록 · 다시 시도 ──────────────────────────────
def test_list_newest_first_with_status_filter(env):
    store, clock = env
    rids = [uid() for _ in range(3)]
    for rid in rids:
        store.delete_artifacts(rid)
        clock.advance(seconds=1)
    gave_up = give_up(store, clock, rids[1])
    mine = set(rids)
    rows = [r for r in store.list_file_deletions(limit=None) if r.run_id in mine]
    assert [r.run_id for r in rows] == rids[::-1]                                 # created_at 최근 순
    assert [r.run_id for r in store.list_file_deletions("포기", limit=None) if r.run_id in mine] == [rids[1]]
    assert [r.run_id for r in store.list_file_deletions("대기", limit=None) if r.run_id in mine] == [rids[2], rids[0]]
    assert gave_up in store.list_file_deletions("포기", limit=None)
    everyone = store.list_file_deletions(limit=None)
    assert store.list_file_deletions(limit=2, offset=1) == everyone[1:3]


def test_retry_records_admin_and_rejects_waiting_or_missing(env):
    store, clock = env
    rid = uid()
    store.delete_artifacts(rid)
    waiting = row_of(store, rid)
    with pytest.raises(FileDeletionNotGivenUp) as e:
        store.retry_file_deletion(waiting.deletion_id, "admin-1")                 # '대기' 줄은 받지 않는다
    assert waiting.deletion_id not in str(e.value) and row_of(store, rid) == waiting
    with pytest.raises(FileDeletionNotFound) as e:
        store.retry_file_deletion("없는줄", "admin-1")
    assert "없는줄" not in str(e.value)
    give_up(store, clock, rid)
    row = store.retry_file_deletion(waiting.deletion_id, "admin-1")
    assert (row.status, row.attempts, row.retried_by, row.retry_count) == ("대기", 0, "admin-1", 1)
    assert row.next_at == row.retried_at and row.gave_up_at is None and row_of(store, rid) == row
    assert claim_one(store, rid).deletion_id == row.deletion_id                   # 바로 가져갈 수 있다
    give_up(store, clock, rid)
    again = store.retry_file_deletion(waiting.deletion_id, "admin-2")
    assert (again.retried_by, again.retry_count) == ("admin-2", 2)                # 마지막으로 누른 관리자 · 횟수


# ── 흐름: 완전 삭제 · 탈퇴 · 12개월 정리 ──────────────────
def test_project_delete_and_withdrawal_enqueue(clock):
    app = make_app(clock)
    rid = start_and_select(app, "acc-del")
    pid = app.store.load_run(rid).project_id
    app.orchestrator.delete_project_data(pid)                                     # 완전 삭제
    row = row_of(app.store, rid)
    assert row.status == "대기"
    other = start_and_select(app, "acc-out")
    app.orchestrator.abort_project(app.store.load_run(other).project_id)
    app.orchestrator.delete_account_data("acc-out")                               # 탈퇴 (완전 삭제를 빠뜨려도)
    assert row_of(app.store, other).status == "대기"
    app.orchestrator.delete_account_data("acc-del")                               # 이미 '대기'면 그대로
    assert row_of(app.store, rid) == row


def test_retention_of_deleted_run_resets_given_up_row(clock):
    app = make_app(clock)
    rid = start_and_select(app, "acc-ret")
    app.orchestrator.delete_project_data(app.store.load_run(rid).project_id)
    give_up(app.store, clock, rid)
    clock.advance(days=400)
    assert start_retention(app.store, "w", 60)
    out = run_retention(app.store, "w", now=clock(), lease_sec=60)
    assert out.summary.deleted_runs == 1                                          # 완전 삭제된 실행 건 정리
    row = row_of(app.store, rid)
    assert (row.status, row.attempts, row.gave_up_at) == ("대기", 0, None)


# ── 처리 함수 · 워커 ──────────────────────────────────────
def put(files, key: str, data: bytes = b"<html></html>") -> None:
    files.write(key, data, FileMeta(name=key.rsplit("/", 1)[1], media_type="text/html", size=len(data),
                                    sha256=sha256_hex(data)))


def test_worker_deletes_prefix_after_delay_and_logs_ids_only(db, runlog):
    clock = Clock()
    app = app_on(db, projects(0), clock)
    files = app.engine.files
    assert isinstance(files, MemoryFileStore)
    rid, other = uid(), uid()
    put(files, f"{rid}/e1/u1/index.html")
    put(files, f"{rid}/e2/u2/secret-name.html")
    put(files, f"{other}/e1/u1/index.html")
    app.store.delete_artifacts(rid)
    logs: list[str] = []
    w = worker(app, logs, lease_sec=60, job_check_sec=0)
    w.run_once("w")
    assert len(files.keys()) == 3 and runlog == []                                # 10분 전에는 지우지 않는다
    clock.advance(seconds=FIRST_DELAY_SEC + 1)
    w.run_once("w")
    assert files.keys() == [f"{other}/e1/u1/index.html"]                          # 그 실행 건 접두어 아래만
    assert app.store.file_deletion_for_run(rid) is None                           # 성공 → 줄을 지운다
    row_id = [line for line in runlog if line.startswith("파일삭제 ")]
    assert len(row_id) == 1 and row_id[0].startswith(f"파일삭제 run={rid} deletion=")
    assert not any("index.html" in x or "secret-name" in x or f"{rid}/" in x for x in runlog + logs)
    w.run_once("w")
    assert sum(x.startswith("파일삭제") for x in runlog) == 1                       # 다시 지우지 않는다


class FlakyFiles(MemoryFileStore):
    """접두어 지우기가 fail_times번 실패한 뒤 된다 (디스크 오류 흉내 — 메시지에 경로를 싣는다)."""

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.calls = 0

    def delete_prefix(self, prefix: str) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise PermissionError(13, "거부", f"C:/root/{prefix}secret-name.html")
        super().delete_prefix(prefix)


def test_worker_failures_give_up_then_admin_retry_succeeds(db, runlog):
    clock = Clock()
    app = app_on(db, projects(0), clock)
    files = FlakyFiles(fail_times=MAX_ATTEMPTS)
    app.engine.files = files
    rid = uid()
    put(files, f"{rid}/e1/u1/index.html")
    app.store.delete_artifacts(rid)
    w = worker(app, lease_sec=60, job_check_sec=0)
    for _ in range(MAX_ATTEMPTS + 1):
        clock.advance(seconds=FIRST_DELAY_SEC + 1)
        w.run_once("w")
    assert files.calls == MAX_ATTEMPTS                                            # 포기한 뒤에는 가져가지 않는다
    row = row_of(app.store, rid)
    assert (row.status, row.attempts, row.last_error_kind) == ("포기", MAX_ATTEMPTS, "일시")
    failed = [x for x in runlog if x.startswith("파일삭제실패 ")]
    assert [x.rsplit("attempts=", 1)[1] for x in failed] == ["1", "2", "3"]
    assert all(f"run={rid} deletion={row.deletion_id} errorKind=일시 error=PermissionError" in x for x in failed)
    assert [x for x in runlog if x.startswith("파일삭제포기 ")] == [
        f"파일삭제포기 run={rid} deletion={row.deletion_id} attempts=3"]
    assert not any("secret-name" in x or "C:/root" in x or "거부" in x for x in runlog)   # 메시지 · 경로 없음
    app.store.retry_file_deletion(row.deletion_id, "admin-9")
    w.run_once("w")
    assert files.keys() == [] and app.store.file_deletion_for_run(rid) is None
    assert runlog[-1] == f"파일삭제 run={rid} deletion={row.deletion_id}"


def test_two_workers_never_delete_the_same_row(db):
    clock = Clock()
    source = projects(0)
    a, b = app_on(db, source, clock), app_on(db, source, clock)
    counting = FlakyFiles(fail_times=0)
    a.engine.files = b.engine.files = counting
    rids = [uid() for _ in range(5)]
    for rid in rids:
        a.store.delete_artifacts(rid)
    clock.advance(seconds=FIRST_DELAY_SEC + 1)
    held = a.store.claim_file_deletions(2, RETRY_SEC)                             # 워커 A가 두 줄을 가져가 처리 중
    out = process_file_deletions(b.store, counting)                               # 워커 B는 나머지만
    assert out.deleted == 3 and counting.calls == 3
    assert {r.run_id for r in a.store.list_file_deletions(limit=None)} == {r.run_id for r in held}
    for r in held:
        assert a.store.finish_file_deletion(r.deletion_id, r.next_at)


def test_local_folder_prefix_deleted(tmp_path):
    """로컬 폴더 저장소 — 실행 건 폴더째 지우고 다른 실행 건 폴더는 남긴다. 이미 없으면 성공."""
    clock = Clock()
    store = MemoryStore(now=clock)
    files = LocalFolderFileStore(tmp_path / "artifacts", create=True)
    rid, other = uid(), uid()
    put(files, f"{rid}/e1/u1/index.html")
    put(files, f"{other}/e1/u1/index.html")
    store.delete_artifacts(rid)
    store.delete_artifacts(uid())                                                 # 파일이 없는 실행 건
    clock.advance(seconds=FIRST_DELAY_SEC + 1)
    out = process_file_deletions(store, files)
    assert out.deleted == 2 and store.list_file_deletions(limit=None) == []
    assert not (tmp_path / "artifacts" / rid).exists() and (tmp_path / "artifacts" / other).is_dir()


def test_error_kinds_and_constants():
    assert error_kind_of(PermissionError()) == "일시" and error_kind_of(TimeoutError()) == "일시"
    assert error_kind_of(ValueError()) == "입력" and error_kind_of(RuntimeError()) == "운영"
    assert MAX_ATTEMPTS == 3                                                      # 잠정 목록에 없다
    assert {"fileDeletion.firstDelaySec", "fileDeletion.retrySec", "fileDeletion.batchSize"} <= set(PROVISIONAL)
    assert not any("maxAttempts" in k or "giveUp" in k for k in PROVISIONAL)
    assert FIRST_DELAY_SEC > 120 and BATCH_SIZE >= 1                              # 워커 점유 시간보다 길게
    assert "파일삭제포기" in PROVISIONAL["workerLog.actions"]
