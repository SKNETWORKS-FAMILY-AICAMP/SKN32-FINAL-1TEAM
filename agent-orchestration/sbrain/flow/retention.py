"""실행 로그 보관 기간 작업 (확장) — 마지막 활동이 12개월보다 오래된 실행 건 · 끝난 시작 요청의 기록을 식별자 없는
통계 줄(log_stats.py)로 옮기고 지운다.

- 기준 시각 = 지금(UTC)에서 달력 기준 12개월 전(retention_cutoff). 관리자 조회(reads.py admin_runs · admin_summary)도
  같은 함수로 범위를 정한다.
- 워커만 돌린다(웹 조립 · 웹 함수는 부르지 않는다). 작업 점유(orch_jobs, 작업 이름 log_retention)로 여러 워커 중 한 대가
  하루 한 번(24시간, 잠정) 돈다 — start_retention이 시작 조건 확인과 점유를 한 트랜잭션으로 한다(저장소).
- 실행 건 하나 = 그 실행 건의 점유를 잡고(못 잡으면 건너뜀) 다시 읽어 조건을 확인한 뒤, 통계 줄 쓰기와 기록 지우기를
  한 트랜잭션(retire_run)으로 하고 점유를 푼다.
  · 살아 있는 실행 건(포인터 있음): 여섯 기록 표의 줄만 지우고, 실행 건 줄 · 산출물 · 마지막 활동 시각은 그대로 둔다.
    통계 줄의 part = Run.stats_parts + 1이고 stats_parts를 1 올린다.
  · 완전 삭제된 실행 건(포인터 없음): 옮길 기록이 있으면 통계 줄을 쓰고, 기록 · 남은 산출물 · 실행 건 줄을 지운다.
  · 실행 · 재개대기는 건너뛴다(저장소가 대상에서 빼고, 점유를 잡은 뒤 다시 확인한다).
- 끝난 시작 요청(완료 · 실패 · 취소, updated_at < 기준 시각)은 묶음마다 (달 · 상태 · 코드)별 개수 줄을 쓰고 지운다(한
  트랜잭션).
- 종료 신호(stop)를 받으면 실행 건 · 묶음 사이에서 멈추고 작업 점유를 푼다(last_finished_at은 쓰지 않음 — 다음에 남은
  것부터). 끝까지 마치면 finish_job으로 last_finished_at · 개수 요약을 쓴다.
- 실행 건 하나가 실패하면(DB 오류 등) 그 트랜잭션만 되돌아가고 건너뛴 수에 센 뒤 다음으로 간다. 워커의 실행 건 오류
  처리(_do의 점유 다시 잡기)를 타지 않는다.
- 로그 · 요약 · 통계 줄에는 개수와 오류 종류 이름만 싣는다 — 실행 건 · 요청 · 계정 · 프로젝트 ID, 오류 메시지 같은 자유
  글을 싣지 않는다.
"""
from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from ..models import Run
from ..models.clock import as_utc
from ..orchestrator.store import BUSY_PROGRESS, LogStatsRow, Store
from .log_stats import RunRecords, run_stats_row, start_request_rows

JOB_NAME = "log_retention"          # orch_jobs.job_name
REASON = "12개월"                    # 통계 줄의 옮긴 까닭
RETENTION_MONTHS = 12               # 보관 기간 (달력 기준 달 수)
# 잠정값 (orchestrator/settings.py PROVISIONAL에도 적는다)
BATCH_SIZE = 100                    # 한 번에 가져오는 실행 건 · 시작 요청 수
INTERVAL_SEC = 24 * 3600.0          # 끝까지 마친 뒤 다시 시작하기까지의 간격 (24시간)
RUN_OWNER_SUFFIX = "/retention"     # 실행 건 점유자 = 작업 점유자 + 이 꼬리 (그 스레드의 다른 점유와 섞이지 않게)


def retention_cutoff(now: datetime, months: int = RETENTION_MONTHS) -> datetime:
    """기준 시각 — now(UTC로 바꾼 값)에서 달력 기준 months개월 전. 그 달에 같은 날이 없으면 그 달 마지막 날.

    예: 2026-03-31 → 2025-03-31, 2028-02-29 → 2027-02-28. 시간대 없는 값은 UTC로 본다. 시각(시 · 분 · 초)은 그대로.
    """
    now = as_utc(now)
    index = now.year * 12 + (now.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


@dataclass
class RetentionSummary:
    """작업 한 번의 개수 — orch_jobs.last_summary(고정 키)와 워커 로그에 싣는다."""
    runs: int = 0           # 기록을 옮긴(통계 줄을 쓴) 실행 건 수
    deleted_runs: int = 0   # 지운 실행 건 줄 수 (완전 삭제된 실행 건)
    requests: int = 0       # 옮긴(지운) 시작 요청 수
    skipped: int = 0        # 점유 · 오류 · 다시 확인 불일치로 건너뛴 실행 건 수

    def as_dict(self) -> dict[str, int]:
        return {"runs": self.runs, "deletedRuns": self.deleted_runs, "requests": self.requests,
                "skipped": self.skipped}


@dataclass(frozen=True)
class RetentionOutcome:
    summary: RetentionSummary = field(default_factory=RetentionSummary)
    finished: bool = False   # 끝까지 마쳐 last_finished_at을 썼는지 (멈춤 · 점유 잃음 · 오류면 거짓)


def _never() -> bool:
    return False


def _quiet(_line: str) -> None:
    return None


def start_retention(store: Store, owner: str, lease_sec: float, interval_sec: float = INTERVAL_SEC) -> bool:
    """작업 점유 — 점유가 비었거나 만료됐고, 마지막으로 끝까지 마친 지 interval_sec이 지났으면 owner가 잡는다."""
    return store.try_start_job(JOB_NAME, owner, lease_sec, interval_sec)


def run_retention(store: Store, owner: str, *, now: datetime, lease_sec: float,
                  stop: Callable[[], bool] = _never, log: Callable[[str], None] = _quiet,
                  batch_size: int = BATCH_SIZE) -> RetentionOutcome:
    """작업 점유를 잡은 owner가 부른다(start_retention). 끝까지 마치면 finish_job, 종료 신호면 release_job.

    now: 기준 시각을 계산할 지금(UTC). log에는 개수 · 오류 종류 이름만 넘긴다.
    작업 점유를 잃으면(다른 워커가 이어받음) 그 자리에서 멈추고 점유를 건드리지 않는다.
    """
    if batch_size < 1:
        raise ValueError("batch_size는 1 이상")
    summary = RetentionSummary()
    cutoff = retention_cutoff(now)
    run_owner = owner + RUN_OWNER_SUFFIX
    try:
        if not _retire_runs(store, owner, run_owner, cutoff, lease_sec, stop, log, batch_size, summary):
            return _halt(store, owner, summary, stop, log)
        if not _retire_requests(store, owner, cutoff, stop, log, batch_size, summary):
            return _halt(store, owner, summary, stop, log)
        if not store.finish_job(JOB_NAME, owner, summary.as_dict()):
            log("보관 작업 점유 잃음")
            return RetentionOutcome(summary, False)
        return RetentionOutcome(summary, True)
    except Exception as e:  # 대상 읽기 등 실행 건 밖의 오류 — 종류만 남기고 점유를 푼다 (다음 확인 때 다시)
        log(f"보관 작업 오류 {type(e).__name__}")
        _release_job(store, owner, log)
        return RetentionOutcome(summary, False)


def _halt(store: Store, owner: str, summary: RetentionSummary, stop: Callable[[], bool],
          log: Callable[[str], None]) -> RetentionOutcome:
    """중간에 멈춤 — 종료 신호면 점유를 풀고, 점유를 잃었으면 그대로 둔다. last_finished_at은 쓰지 않는다."""
    if stop():
        _release_job(store, owner, log)
    return RetentionOutcome(summary, False)


def _release_job(store: Store, owner: str, log: Callable[[str], None]) -> None:
    try:
        store.release_job(JOB_NAME, owner)
    except Exception as e:
        log(f"보관 작업 오류 점유 풀기 {type(e).__name__}")


def _job_held(store: Store, owner: str, log: Callable[[str], None]) -> bool:
    job = store.get_job(JOB_NAME)
    if job is None or job.lease_owner != owner:
        log("보관 작업 점유 잃음")
        return False
    return True


def _retire_runs(store: Store, owner: str, run_owner: str, cutoff: datetime, lease_sec: float,
                 stop: Callable[[], bool], log: Callable[[str], None], batch_size: int,
                 summary: RetentionSummary) -> bool:
    """실행 건을 묶음으로 가져와 하나씩 옮긴다. 끝까지 했으면 참, 멈췄거나 점유를 잃었으면 거짓.

    건너뛴 실행 건은 다시 대상으로 나올 수 있어, 이번 작업에서 이미 본 ID를 빼고 그만큼 더 가져온다(같은 실행 건을
    되풀이하며 멈추지 않는 일이 없게). 새 ID가 없으면 끝이다.
    """
    seen: set[str] = set()
    skipped_ids: set[str] = set()
    while True:
        if stop() or not _job_held(store, owner, log):
            return False
        ids = [i for i in store.retention_run_targets(cutoff, batch_size + len(skipped_ids)) if i not in seen]
        if not ids:
            return True
        for run_id in ids[:batch_size]:
            if stop():
                return False
            seen.add(run_id)
            try:
                result = _retire_one(store, run_id, run_owner, lease_sec, cutoff)
            except Exception as e:  # 이 실행 건의 트랜잭션만 되돌아간다 — 종류만 남기고 다음으로
                result = None
                log(f"보관 작업 오류 실행 건 {type(e).__name__}")
            finally:
                try:
                    store.release(run_id, run_owner)   # 점유자가 우리일 때만 풀린다 (못 잡았거나 지운 줄이면 할 일 없음)
                except Exception as e:
                    log(f"보관 작업 오류 점유 풀기 {type(e).__name__}")
            if result is None:
                summary.skipped += 1
                skipped_ids.add(run_id)
                continue
            moved, deleted = result
            summary.runs += int(moved)
            summary.deleted_runs += int(deleted)


def gather_run_stats(store: Store, run: Run, *, reason: str) -> LogStatsRow | None:
    """실행 건 하나의 통계 줄 — 저장소에서 여섯 기록 표 · 포인터 · (필요하면) 산출물 'category'를 읽어 run_stats_row에 넘긴다.

    12개월 처리(_retire_one)와 탈퇴(service._withdraw_run)가 함께 쓰는 한 곳이다. 실행 건 ID를 담는 기록 표를 새로
    만들면 여기(RunRecords)에 넣는다. 그 실행 건의 점유를 잡은 채로 부른다. 옮길 기록이 없으면 None(포인터를 읽지 않음).
    part = Run.stats_parts + 1. 카테고리 대신 값은 Run.category가 없던 기존 실행 건에서 글(str)일 때만 넘긴다.
    """
    run_id = run.run_id
    records = RunRecords(executions=store.executions(run_id), calls=store.call_logs(run_id),
                         events=store.events(run_id), feedback=store.feedback(run_id),
                         comparisons=store.comparisons(run_id), pointer_events=store.pointer_events(run_id))
    if records.is_empty():
        return None
    pointers = store.get_pointers(run_id)
    fallback = None
    if run.category is None and "category" in pointers:   # Run.category가 없던 기존 실행 건
        value = store.get_artifact(run_id, "category", pointers["category"]).value
        fallback = value if isinstance(value, str) else None
    return run_stats_row(run, records, pointers=pointers, reason=reason, part=run.stats_parts + 1,
                         category_fallback=fallback)


def _retire_one(store: Store, run_id: str, owner: str, lease_sec: float,
                cutoff: datetime) -> tuple[bool, bool] | None:
    """실행 건 하나 — (통계 줄을 썼는지, 실행 건 줄을 지웠는지). 점유를 못 잡았거나 더는 대상이 아니면 None."""
    if not store.acquire(run_id, owner, lease_sec):
        return None
    run = store.load_run(run_id)
    if as_utc(run.updated_at) >= cutoff or run.state.progress in BUSY_PROGRESS:
        return None
    deleted = not store.has_pointers(run_id)   # 포인터가 없으면 완전 삭제된 실행 건
    row = gather_run_stats(store, run, reason=REASON)
    if not deleted and row is None:            # 옮길 기록이 없는 살아 있는 실행 건
        return None
    store.retire_run(run_id, owner, stats=row, delete_run=deleted, bump_parts=not deleted and row is not None)
    return row is not None, deleted


def _retire_requests(store: Store, owner: str, cutoff: datetime, stop: Callable[[], bool],
                     log: Callable[[str], None], batch_size: int, summary: RetentionSummary) -> bool:
    """끝난 시작 요청을 묶음마다 개수 줄 + 지우기(한 트랜잭션)로. 실패한 묶음의 요청은 이번 작업에서 다시 보지 않는다."""
    failed: set[str] = set()
    while True:
        if stop() or not _job_held(store, owner, log):
            return False
        reqs = [r for r in store.retention_request_targets(cutoff, batch_size + len(failed))
                if r.request_id not in failed][:batch_size]
        if not reqs:
            return True
        ids = [r.request_id for r in reqs]
        try:
            summary.requests += store.retire_start_requests(ids, start_request_rows(reqs, REASON))
        except Exception as e:  # 그 묶음만 되돌아간다 — 종류만 남긴다
            failed.update(ids)
            log(f"보관 작업 오류 시작 요청 {type(e).__name__}")


__all__ = [
    "BATCH_SIZE", "INTERVAL_SEC", "JOB_NAME", "REASON", "RETENTION_MONTHS", "RetentionOutcome", "RetentionSummary",
    "gather_run_stats", "retention_cutoff", "run_retention", "start_retention",
]
