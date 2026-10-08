"""저장 인터페이스(Store)의 SQL 구현 — 공유 MySQL 8(운영) · SQLite(테스트).

메모리 구현(orchestrator/memory_store.py)과 같은 동작이다. 흐름 테스트를 두 저장소로 함께 돌려 확인한다.

| 메서드 | 동작 |
|---|---|
| create_run | 계정 잠금(MySQL GET_LOCK, SQLite는 프로세스 잠금) 안에서 진행 중 실행 건 수를 세고, 실행 건과 첫 기록을 한 트랜잭션으로 저장 |
| acquire · release | 조건부 UPDATE(점유자가 없거나 같거나 만료된 경우만). 영향 행 수로 성공 판정 |
| commit | 한 트랜잭션: 점유 확인(아니면 StoreConflict) → 실행 건 행 갱신 + 점유 연장 → 산출물 버전 · 포인터 → 실행 기록(같은 ID는 덮어씀) → 호출 기록 · 피드백 · 비교 · 포인터 이동 · 추적 사건 → 웹 notifications → 학습 동의면 웹 proofread_logs → 실패로 바뀌었으면 generation_failure_alerts |
| notifications | 웹 notifications에서 실행 건의 project_id로 읽는다 |
| rejected_attempts | 웹 proofread_logs에서 실행 건의 project_id로 반려된 시도를 읽는다 |
| add_start_request | 계정 잠금 안에서 진행 중 실행 건 · 대기 · 처리중 요청을 세고 '대기' 요청을 넣는다 |
| acquire_start_request | 조건부 UPDATE로 '처리중' 점유 ('대기', 또는 점유 만료 · 같은 점유자) |
| create_run_for_request | 계정 잠금 + 한 트랜잭션: 요청 점유 · 취소 요청 확인 → 실행 건 생성 → 요청 '완료'(+run_id) |
| claim_* | 후보 한 건을 SELECT … FOR UPDATE SKIP LOCKED로 고르고 같은 트랜잭션에서 조건부 UPDATE로 점유. SQLite는 BEGIN IMMEDIATE로 직렬화되어 조건부 UPDATE만으로 같은 결과. claim_ready_run은 재작성 요청을 모으는 중(collect_until > now)인 실행 건을 건너뛴다 |
| renew · renew_start_request | 하트비트 — 지금 점유자일 때만 점유 연장 |
| query_runs · latest_start_requests · find_active_work · count_executions | 여러 실행 건 · 여러 프로젝트 · 동시 실행 확인 · 실행 기록 수 조회 (잠금 없이 읽기만, 확장) |
| existing_projects | 실행 건 줄 또는 대기 · 처리중 시작 요청이 있는 프로젝트 — PROJECT_CHUNK개씩 IN으로 나눠 묻고, 한 연결에서 요청을 먼저 · 실행 건을 나중에 본다 (잠금 없이 읽기만, 확장) |
| finish_start_request · create_run_for_request · cancel_start_request | 요청을 끝내는(완료 · 실패 · 취소) 같은 UPDATE에서 입력 사본 form_json을 NULL로 비운다 |
| account_guard | 계정 잠금(add_start_request와 같은 잠금)을 잡은 채로 있는 구간 — 탈퇴용 (확장) |
| retire_run | 한 트랜잭션: 점유 확인(SELECT … FOR UPDATE, 아니면 StoreConflict) → 통계 줄 → 여섯 기록 표 삭제 → (delete_run) 산출물 · 실행 건 줄 삭제 / (bump_parts) run_json의 statsParts만 +1 — updated_at은 그대로 (확장) |
| retire_start_requests | 한 트랜잭션: 넘긴 요청이 모두 끝났는지 잠가서 확인(FOR UPDATE, 아니면 StoreConflict) → 통계 줄 → 요청 삭제 (확장) |
| retention_run_targets · retention_request_targets | 12개월 처리 대상 (잠금 없이 읽기만 — 부르는 쪽이 실행 건 점유를 잡고 다시 본다, 확장) |
| try_start_job · renew_job · finish_job · release_job | orch_jobs 점유 — 작업 줄이 없으면 만들고(INSERT … ON DUPLICATE KEY/ON CONFLICT) 같은 트랜잭션에서 조건부 UPDATE (확장) |

- 알림은 웹 notifications에 쓴다. 기준 문서 Notification의 runId 자리에 project_id를 쓰고, project_id가 없는
  실행 건(테스트 · 시연용 직접 시작)은 웹 테이블에 쓰지 않는다. 웹 테이블에 쓸 project_id는 실행 건 행의
  컬럼 값을 쓴다 — 완전 삭제로 NULL이 된 프로젝트에는 쓰지 않는다.
- 웹 projects에는 쓰지 않는다(진행 컬럼 5개 포함). 웹 테이블 쓰기는 notifications · proofread_logs ·
  generation_failure_alerts INSERT뿐이고, 모두 단계 저장과 같은 트랜잭션이다.
- 반려된 시도는 그 프로젝트 주인이 저장하는 순간 학습 데이터 편입에 동의했을 때만(users.ai_training_agreed)
  proofread_logs에 쓴다. proofread_logs 구조가 아직 바뀌지 않았으면(필요한 컬럼 없음 등) 쓰기만 건너뛰고
  추적 사건 '검수회수기록생략'을 실행 건마다 한 번 남긴다 — 단계 저장은 되돌리지 않는다.
- 저장된 진행 상태가 실패가 아니었는데 이번에 실패면 generation_failure_alerts에 한 행을 쌓는다.
- 점유 시각은 주입한 시계(now)로 잰다. 여러 서버가 같은 DB를 쓰면 서버 시계가 맞아야 한다(잠정).
- 시각은 시간대 있는 UTC로 다루고, DB 칸에는 시간대 없는 UTC로 넣는다(schema.UtcDateTime · 웹 표는 web_tables).
  주입한 시계 · 인자의 시간대 없는 값은 UTC로 본다.
- 계정 잠금 대기 10초 (잠정).
"""
from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import (
    Connection, Engine, Row, Select, Table, and_, case, delete, exists, func, insert, or_, select, text, update,
)
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..models import Notice, Notification, RejectedAttempt, ReworkComparison, Run
from ..models.clock import as_utc, utc_clock, utc_now
from ..models.run import ACTIVE_PROGRESS
from ..orchestrator.errors import ProjectRunExists, StoreConflict
from ..orchestrator.store import (
    ACCOUNT_LOCK_TIMEOUT_SEC, BUSY_PROGRESS, FINISHED_REQUEST, PENDING_REQUEST, ArtifactVersion, CancelOutcome,
    CommitBatch, CreateOutcome, ExecutionFilter, ExecutionRow, JobState, LogStatsRow, RunFilter, StartRequest,
    StartRequestStatus, check_summary,
)
from ..orchestrator.trace import (
    IMAGE_TOKEN_FIELDS, TOKEN_FIELDS, CallLog, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent,
)
from .schema import (
    ARTIFACT_POINTERS, ARTIFACT_VERSIONS, CALL_LOGS, EXECUTIONS, FEEDBACK_LINKS, JOBS, LOG_STATS, POINTER_EVENTS,
    RECORD_TABLES, REWORK_COMPARISONS, RUNS, START_REQUESTS, TRACE_EVENTS,
)
from .web_tables import WebTables

PROJECT_CHUNK = 500   # existing_projects가 IN 하나에 싣는 프로젝트 수 (잠정)
PROOFREAD_SKIPPED = "검수회수기록생략"   # 웹 proofread_logs 구조가 맞지 않아 반려된 시도를 쓰지 않음 (실행 건마다 한 번)


def project_key(project_id: int | str | None) -> int | None:
    """Run.projectId(문자열) → 웹 projects.project_id(정수)."""
    if project_id is None:
        return None
    try:
        return int(project_id)
    except ValueError:
        raise ValueError(f"project_id는 웹 projects.project_id(정수)여야 함: {project_id!r}") from None


class SqlStore:
    def __init__(self, engine: Engine, *, now: Callable[[], datetime] = utc_now,
                 web: WebTables | None = None) -> None:
        self.engine = engine
        self.web = web or WebTables()
        self._now = utc_clock(now)
        self._mysql = engine.dialect.name == "mysql"
        self._local_locks: dict[str, threading.Lock] = {}
        self._local_guard = threading.Lock()
        self._lease_sec: dict[tuple[str, str], float] = {}   # 이 프로세스가 잡은 점유의 길이 (저장 때 연장)
        self.account_lock_timeout: float = ACCOUNT_LOCK_TIMEOUT_SEC   # 계정 잠금 대기 (잠정)

    # ── 실행 건 ───────────────────────────────────────
    def create_run(self, run: Run, batch: CommitBatch, *, max_active: int = 1) -> bool:
        with self.engine.connect() as conn, self.account_lock(conn, run.account_id):
            with conn.begin():
                return self._insert_run(conn, run, batch, max_active)

    def _insert_run(self, conn: Connection, run: Run, batch: CommitBatch, max_active: int) -> bool:
        """계정 잠금 · 트랜잭션 안에서 부른다. 동시 실행 제한에 걸리면 False."""
        pid = project_key(run.project_id)
        active = conn.execute(
            select(func.count()).select_from(RUNS)
            .where(RUNS.c.account_id == run.account_id, RUNS.c.progress.in_(ACTIVE_PROGRESS))).scalar_one()
        if active >= max_active:
            return False
        if pid is not None and conn.execute(select(RUNS.c.run_id).where(RUNS.c.project_id == pid)).first() is not None:
            raise ProjectRunExists(run.project_id)
        conn.execute(insert(RUNS).values(run_id=run.run_id, account_id=run.account_id, project_id=pid,
                                         abort_requested=False, **_run_values(run)))
        batch.run = None
        self._apply(conn, run.run_id, batch, pid, self._now())
        self._alert_on_failure(conn, run, pid, before=None)
        return True

    def load_run(self, run_id: str) -> Run:
        with self.engine.connect() as conn:
            row = conn.execute(select(RUNS.c.run_json).where(RUNS.c.run_id == run_id)).first()
        if row is None:
            raise KeyError(run_id)
        return Run.model_validate(row.run_json)

    def list_runs(self, account_id: str) -> list[Run]:
        return self._runs_where(RUNS.c.account_id == account_id)

    def find_active_run(self, account_id: str) -> Run | None:
        runs = self._runs_where(RUNS.c.account_id == account_id, RUNS.c.progress.in_(ACTIVE_PROGRESS), limit=1)
        return runs[0] if runs else None

    def find_run_by_project(self, project_id: int | str) -> Run | None:
        runs = self._runs_where(RUNS.c.project_id == project_key(project_id), limit=1)
        return runs[0] if runs else None

    def runs_due_for_resume(self, now: datetime) -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(RUNS.c.run_id)
                                .where(RUNS.c.progress == "재개대기", RUNS.c.next_resume_at <= now)
                                .order_by(RUNS.c.next_resume_at, RUNS.c.run_id)).all()
        return [r.run_id for r in rows]

    def query_runs(self, f: RunFilter) -> list[Run]:
        conds: list[Any] = []
        if f.project_ids is not None:
            pids = [project_key(p) for p in f.project_ids]
            if not pids:
                return []
            conds.append(RUNS.c.project_id.in_(pids))
        if f.progress is not None:
            conds.append(RUNS.c.progress == f.progress)
        if f.step is not None:
            conds.append(RUNS.c.step == f.step)
        if f.updated_since is not None:
            conds.append(RUNS.c.updated_at >= f.updated_since)
        order = ([RUNS.c.updated_at.desc(), RUNS.c.run_id.desc()] if f.order == "desc"
                 else [RUNS.c.updated_at, RUNS.c.run_id])
        stmt = _paged(select(RUNS.c.run_json).where(*conds).order_by(*order), f.limit, f.offset)
        with self.engine.connect() as conn:
            return [Run.model_validate(r.run_json) for r in conn.execute(stmt)]

    def find_active_work(self, account_id: str) -> Run | StartRequest | None:
        """add_start_request와 같은 기준 · 같은 순서 (잠금 없이 한 번 읽는다)."""
        t = START_REQUESTS
        with self.engine.connect() as conn:
            active = conn.execute(select(RUNS.c.run_json).where(
                RUNS.c.account_id == account_id, RUNS.c.progress.in_(ACTIVE_PROGRESS))
                .order_by(RUNS.c.created_at, RUNS.c.run_id).limit(1)).first()
            if active is not None:
                return Run.model_validate(active.run_json)
            pending = conn.execute(select(t).where(t.c.account_id == account_id, t.c.status.in_(PENDING_REQUEST))
                                   .order_by(t.c.created_at, t.c.request_id).limit(1)).first()
        return _request_of(pending) if pending is not None else None

    def _runs_where(self, *conds: Any, limit: int | None = None) -> list[Run]:
        stmt = select(RUNS.c.run_json).where(*conds).order_by(RUNS.c.created_at, RUNS.c.run_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        with self.engine.connect() as conn:
            return [Run.model_validate(r.run_json) for r in conn.execute(stmt)]

    # ── 사전 단계 시작 요청 ────────────────────────────
    def add_start_request(self, req: StartRequest, *, max_active: int = 1) -> Run | StartRequest | None:
        t = START_REQUESTS
        with self.engine.connect() as conn, self.account_lock(conn, req.account_id):
            with conn.begin():
                active = conn.execute(select(RUNS.c.run_json).where(
                    RUNS.c.account_id == req.account_id, RUNS.c.progress.in_(ACTIVE_PROGRESS))
                    .order_by(RUNS.c.created_at, RUNS.c.run_id)).all()
                pending = conn.execute(select(t).where(t.c.account_id == req.account_id,
                                                       t.c.status.in_(PENDING_REQUEST))
                                       .order_by(t.c.created_at, t.c.request_id)).all()
                if len(active) + len(pending) >= max_active:
                    return Run.model_validate(active[0].run_json) if active else _request_of(pending[0])
                conn.execute(insert(t).values(**_request_values(req)))
                return None

    def get_start_request(self, request_id: str) -> StartRequest:
        t = START_REQUESTS
        with self.engine.connect() as conn:
            row = conn.execute(select(t).where(t.c.request_id == request_id)).first()
        if row is None:
            raise KeyError(request_id)
        return _request_of(row)

    def latest_start_request(self, project_id: int | str) -> StartRequest | None:
        t = START_REQUESTS
        with self.engine.connect() as conn:
            row = conn.execute(select(t).where(t.c.project_id == project_key(project_id))
                               .order_by(t.c.created_at.desc(), t.c.request_id.desc()).limit(1)).first()
        return _request_of(row) if row is not None else None

    def latest_start_requests(self, project_ids: Iterable[int | str]) -> dict[str, StartRequest]:
        t = START_REQUESTS
        pids = sorted({project_key(p) for p in project_ids})
        if not pids:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(select(t).where(t.c.project_id.in_(pids))
                                .order_by(t.c.created_at.desc(), t.c.request_id.desc())).all()
        latest: dict[str, StartRequest] = {}
        for row in rows:   # 최근 순 — 프로젝트마다 처음 나온 것이 마지막 요청
            latest.setdefault(str(row.project_id), _request_of(row))
        return latest

    def existing_projects(self, project_ids: Iterable[int]) -> set[int]:
        t = START_REQUESTS
        pids = sorted({project_key(p) for p in project_ids})
        found: set[int] = set()
        with self.engine.connect() as conn:
            for i in range(0, len(pids), PROJECT_CHUNK):
                part = pids[i:i + PROJECT_CHUNK]
                # 요청을 먼저 · 실행 건을 나중에 — 그 사이에 요청이 실행 건이 되어도 둘 중 하나에서 보인다
                found.update(conn.execute(select(t.c.project_id).where(
                    t.c.project_id.in_(part), t.c.status.in_(PENDING_REQUEST))).scalars())
                found.update(conn.execute(select(RUNS.c.project_id).where(RUNS.c.project_id.in_(part))).scalars())
        return found

    def acquire_start_request(self, request_id: str, owner: str, lease_sec: float) -> bool:
        t, now = START_REQUESTS, self._now()
        with self.engine.begin() as conn:
            free = or_(_request_free(now), and_(t.c.status == "처리중", t.c.lease_owner == owner))
            n = conn.execute(_take_request(request_id, free, owner, lease_sec, now)).rowcount
        return n == 1

    # ── 워커 가져가기 · 점유 연장 ──────────────────────
    def claim_start_request(self, owner: str, lease_sec: float) -> str | None:
        t, now = START_REQUESTS, self._now()
        with self.engine.begin() as conn:
            rid = conn.execute(select(t.c.request_id).where(_request_free(now))
                               .order_by(t.c.created_at, t.c.request_id).limit(1)
                               .with_for_update(skip_locked=True)).scalar()
            if rid is None:
                return None
            n = conn.execute(_take_request(rid, _request_free(now), owner, lease_sec, now)).rowcount
        return rid if n == 1 else None

    def claim_ready_run(self, owner: str, lease_sec: float) -> str | None:
        # 재작성 요청을 모으는 중(collect_until이 지금보다 뒤)인 실행 건은 그 시각이 지날 때까지 가져가지 않는다
        now = self._now()
        return self._claim_run(owner, lease_sec,
                               [RUNS.c.progress == "실행",
                                or_(RUNS.c.collect_until.is_(None), RUNS.c.collect_until <= now)],
                               [RUNS.c.updated_at, RUNS.c.run_id])

    def claim_due_resume(self, owner: str, lease_sec: float, now: datetime) -> str | None:
        return self._claim_run(owner, lease_sec, [RUNS.c.progress == "재개대기", RUNS.c.next_resume_at <= now],
                               [RUNS.c.next_resume_at, RUNS.c.run_id])

    def _claim_run(self, owner: str, lease_sec: float, conds: list[Any], order: list[Any]) -> str | None:
        now = self._now()
        free = or_(RUNS.c.lease_owner.is_(None), RUNS.c.lease_until <= now)
        with self.engine.begin() as conn:
            rid = conn.execute(select(RUNS.c.run_id).where(*conds, free).order_by(*order).limit(1)
                               .with_for_update(skip_locked=True)).scalar()
            if rid is None:
                return None
            n = conn.execute(update(RUNS).where(RUNS.c.run_id == rid, free)
                             .values(lease_owner=owner, lease_until=now + timedelta(seconds=lease_sec))).rowcount
        if n != 1:
            return None
        self._lease_sec[(rid, owner)] = lease_sec
        return rid

    def renew(self, run_id: str, owner: str, lease_sec: float) -> bool:
        with self.engine.begin() as conn:
            n = conn.execute(update(RUNS).where(RUNS.c.run_id == run_id, RUNS.c.lease_owner == owner)
                             .values(lease_until=self._now() + timedelta(seconds=lease_sec))).rowcount
        return n == 1

    def renew_start_request(self, request_id: str, owner: str, lease_sec: float) -> bool:
        t = START_REQUESTS
        with self.engine.begin() as conn:
            n = conn.execute(update(t).where(t.c.request_id == request_id, t.c.status == "처리중",
                                             t.c.lease_owner == owner)
                             .values(lease_until=self._now() + timedelta(seconds=lease_sec))).rowcount
        return n == 1

    def finish_start_request(self, request_id: str, owner: str, *, status: StartRequestStatus,
                             code: str | None = None, message: str | None = None,
                             detail: dict[str, Any] | None = None, notices: list[Notice] | None = None) -> bool:
        t = START_REQUESTS
        with self.engine.begin() as conn:
            n = conn.execute(update(t).where(t.c.request_id == request_id, t.c.status == "처리중",
                                             t.c.lease_owner == owner)
                             .values(**self._closing(status, code=code, message=message, detail=detail,
                                                     notices=notices))).rowcount
        return n == 1

    def create_run_for_request(self, run: Run, batch: CommitBatch, request_id: str, owner: str, *,
                               max_active: int = 1) -> CreateOutcome:
        t = START_REQUESTS
        with self.engine.connect() as conn, self.account_lock(conn, run.account_id):
            with conn.begin():
                row = conn.execute(select(t.c.status, t.c.lease_owner, t.c.cancel_requested)
                                   .where(t.c.request_id == request_id).with_for_update()).first()
                if row is None or row.status != "처리중" or row.lease_owner != owner:
                    return "점유잃음"
                where = t.c.request_id == request_id
                if row.cancel_requested:
                    conn.execute(update(t).where(where).values(**self._closing("취소")))
                    return "취소"
                if not self._insert_run(conn, run, batch, max_active):
                    return "동시실행"
                conn.execute(update(t).where(where).values(
                    **self._closing("완료", notices=run.notices, run_id=run.run_id)))
                return "완료"

    def cancel_start_request(self, request_id: str) -> CancelOutcome:
        t = START_REQUESTS
        with self.engine.begin() as conn:
            status = conn.execute(select(t.c.status).where(t.c.request_id == request_id).with_for_update()).scalar()
            if status == "대기":
                conn.execute(update(t).where(t.c.request_id == request_id).values(**self._closing("취소")))
                return "취소"
            if status == "처리중":
                conn.execute(update(t).where(t.c.request_id == request_id)
                             .values(cancel_requested=True, updated_at=self._now()))
                return "취소요청"
            return ""

    def pending_start_requests(self, project_id: int | str) -> list[StartRequest]:
        t = START_REQUESTS
        with self.engine.connect() as conn:
            rows = conn.execute(select(t).where(t.c.project_id == project_key(project_id),
                                                t.c.status.in_(PENDING_REQUEST))
                                .order_by(t.c.created_at, t.c.request_id)).all()
        return [_request_of(r) for r in rows]

    def clear_start_request_forms(self, project_id: int | str) -> int:
        t = START_REQUESTS
        with self.engine.begin() as conn:
            return conn.execute(update(t).where(t.c.project_id == project_key(project_id), t.c.form_json.is_not(None))
                                .values(form_json=None, updated_at=self._now())).rowcount

    def _closing(self, status: StartRequestStatus, *, code: str | None = None, message: str | None = None,
                 detail: dict[str, Any] | None = None, notices: list[Notice] | None = None,
                 run_id: str | None = None) -> dict[str, Any]:
        now = self._now()
        # 요청이 끝나면 입력 사본을 상태와 같은 UPDATE에서 비운다 (실행 건에는 formInput 산출물로 남는다)
        return dict(status=status, result_code=code, result_message=message, result_detail=detail,
                    notices=[n.dump() for n in notices or []], run_id=run_id, lease_owner=None, lease_until=None,
                    finished_at=now, updated_at=now, form_json=None)

    # ── 실행 점유 ─────────────────────────────────────
    def acquire(self, run_id: str, owner: str, lease_sec: float) -> bool:
        now = self._now()
        with self.engine.begin() as conn:
            n = conn.execute(
                update(RUNS)
                .where(RUNS.c.run_id == run_id,
                       or_(RUNS.c.lease_owner.is_(None), RUNS.c.lease_owner == owner, RUNS.c.lease_until <= now))
                .values(lease_owner=owner, lease_until=now + timedelta(seconds=lease_sec))).rowcount
        if n == 1:
            self._lease_sec[(run_id, owner)] = lease_sec
        return n == 1

    def release(self, run_id: str, owner: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(RUNS).where(RUNS.c.run_id == run_id, RUNS.c.lease_owner == owner)
                         .values(lease_owner=None, lease_until=None))
        self._lease_sec.pop((run_id, owner), None)

    def is_locked(self, run_id: str, now: datetime) -> bool:
        with self.engine.connect() as conn:
            until = conn.execute(select(RUNS.c.lease_until).where(RUNS.c.run_id == run_id)).scalar()
        return bool(until and until > as_utc(now))

    # ── 한 번에 저장 ──────────────────────────────────
    def commit(self, run_id: str, owner: str, batch: CommitBatch) -> None:
        now = self._now()
        with self.engine.begin() as conn:
            row = conn.execute(select(RUNS.c.lease_owner, RUNS.c.project_id, RUNS.c.progress)
                               .where(RUNS.c.run_id == run_id).with_for_update()).first()
            if row is None or row.lease_owner != owner:
                raise StoreConflict(f"점유하지 않은 실행에 저장: {run_id}")
            values: dict[str, Any] = _run_values(batch.run) if batch.run is not None else {}
            sec = self._lease_sec.get((run_id, owner))
            if sec is not None:
                values["lease_until"] = now + timedelta(seconds=sec)   # 점유 연장
            if values:
                conn.execute(update(RUNS).where(RUNS.c.run_id == run_id).values(**values))
            self._apply(conn, run_id, batch, row.project_id, now)
            self._alert_on_failure(conn, batch.run, row.project_id, before=row)

    def _apply(self, conn: Connection, run_id: str, batch: CommitBatch, project_id: int | None,
               now: datetime) -> None:
        """now = 이 저장 시각 (웹 proofread_logs.created_at에 넣는다)."""
        if batch.versions:
            conn.execute(insert(ARTIFACT_VERSIONS), [
                dict(run_id=run_id, artifact_key=v.key, version=v.version, value=v.value, producer=v.producer,
                     created_at=v.created_at) for v in batch.versions])
        self._upsert(conn, ARTIFACT_POINTERS, ["run_id", "artifact_key"], [
            dict(run_id=run_id, artifact_key=k, version=v) for k, v in batch.pointers.items()])
        self._insert(conn, POINTER_EVENTS, [
            dict(run_id=run_id, artifact_key=e.key, from_version=e.from_version, to_version=e.to_version,
                 reason=e.reason, cycle_id=e.cycle_id, at=e.at) for e in batch.pointer_events])
        self._upsert(conn, EXECUTIONS, ["execution_id"], [
            _execution_row(rec, run_id, project_id) for rec in batch.executions.values()])
        self._insert(conn, CALL_LOGS, [_call_row(log) for log in batch.call_logs])
        self._insert(conn, FEEDBACK_LINKS, [
            dict(feedback_id=f.feedback_id, run_id=run_id, kind=f.kind, cycle_id=f.cycle_id,
                 source_execution_id=f.source_execution_id, target_execution_id=f.target_execution_id,
                 created_at=f.created_at, record_json=f.dump()) for f in batch.feedback])
        self._insert(conn, REWORK_COMPARISONS, [
            dict(run_id=run_id, bundle_id=c.bundle_id, cycle_id=c.cycle_id, screen=c.screen, kept=c.kept,
                 basis=c.basis, compared_at=c.compared_at, record_json=c.dump()) for c in batch.comparisons])
        self._insert(conn, TRACE_EVENTS, [
            dict(run_id=run_id, kind=e.kind, execution_id=e.execution_id, cycle_id=e.cycle_id, at=e.at,
                 record_json=e.dump()) for e in batch.events])
        if batch.notifications and project_id is not None:
            self.web.insert_notifications(conn, project_id, batch.notifications)
        if batch.rejected_attempts and project_id is not None:
            self._write_rejected_attempts(conn, run_id, project_id, batch.rejected_attempts, now)

    def _write_rejected_attempts(self, conn: Connection, run_id: str, project_id: int,
                                 items: list[RejectedAttempt], now: datetime) -> None:
        """학습 동의 계정이면 웹 proofread_logs에 쓴다(created_at = 저장 시각 now). 구조가 맞지 않으면 건너뛰고
        사건을 실행 건마다 한 번 남긴다."""
        if not self.web.training_agreed(conn, project_id):
            return
        table, problem = self.web.proofread_logs(conn)
        if table is not None:
            self.web.insert_rejected_attempts(conn, table, project_id, items, now)
            return
        seen = conn.execute(select(TRACE_EVENTS.c.seq).where(
            TRACE_EVENTS.c.run_id == run_id, TRACE_EVENTS.c.kind == PROOFREAD_SKIPPED).limit(1)).first()
        if seen is None:
            ev = TraceEvent(run_id=run_id, kind=PROOFREAD_SKIPPED, at=now,
                            detail=f"웹 proofread_logs 구조가 맞지 않아 검수 회수 문단을 쓰지 않음 — {problem}")
            conn.execute(insert(TRACE_EVENTS).values(run_id=run_id, kind=ev.kind, execution_id=None, cycle_id=None,
                                                     at=now, record_json=ev.dump()))

    def _alert_on_failure(self, conn: Connection, run: Run | None, project_id: int | None,
                          before: Row | None) -> None:
        """실패로 바뀌었으면 실패 알림 한 행 (실행 건에 project_id가 있을 때만). before = 저장 전 실행 건 행."""
        if run is None or project_id is None:
            return
        if run.state.progress == "실패" and (before is None or before.progress != "실패"):
            self.web.insert_failure_alert(conn, project_id, run, self._now())

    @staticmethod
    def _insert(conn: Connection, table: Table, rows: list[dict[str, Any]]) -> None:
        if rows:
            conn.execute(insert(table), rows)

    def _upsert(self, conn: Connection, table: Table, keys: list[str], rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        cols = [c for c in rows[0] if c not in keys]
        if self._mysql:
            stmt = mysql_insert(table)
            stmt = stmt.on_duplicate_key_update({c: stmt.inserted[c] for c in cols})
        else:
            stmt = sqlite_insert(table)
            stmt = stmt.on_conflict_do_update(index_elements=keys, set_={c: stmt.excluded[c] for c in cols})
        conn.execute(stmt, rows)

    # ── 계정 잠금 ─────────────────────────────────────
    @contextmanager
    def account_lock(self, conn: Connection, account_id: str) -> Iterator[None]:
        """계정 단위 잠금 — 동시 실행 제한 확인과 생성을 한 곳에서만 하게 한다.

        MySQL은 이름 잠금(GET_LOCK, 연결 단위)을 쓴다. 잠금 뒤 트랜잭션을 새로 열어 최신 값을 센다.
        SQLite(테스트)는 프로세스 잠금으로 대신한다.
        """
        if not self._mysql:
            lock = self._local_lock(account_id)
            if not lock.acquire(timeout=self.account_lock_timeout):
                raise StoreConflict("계정 잠금을 얻지 못함 (대기 시간 초과)")
            try:
                yield
            finally:
                lock.release()
            return
        name = f"sbrain:acct:{account_id}"
        if len(name) > 64:   # MySQL 잠금 이름은 64자까지
            name = "sbrain:acct:" + hashlib.sha1(account_id.encode()).hexdigest()
        got = conn.execute(text("SELECT GET_LOCK(:n, :t)"), {"n": name, "t": self.account_lock_timeout}).scalar()
        conn.commit()
        if got != 1:
            raise StoreConflict("계정 잠금을 얻지 못함 (대기 시간 초과)")   # 계정 ID는 싣지 않는다
        try:
            yield
        finally:
            conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": name})
            conn.commit()

    def _local_lock(self, account_id: str) -> threading.Lock:
        with self._local_guard:
            return self._local_locks.setdefault(account_id, threading.Lock())

    @contextmanager
    def account_guard(self, account_id: str) -> Iterator[None]:
        """계정 잠금을 잡은 채로 있는 구간 (확장 — 탈퇴용). 잠금 전용 연결을 열어 끝날 때까지 쥔다.

        안에서 부르는 저장소 메서드는 각자 연결 · 트랜잭션을 연다. 같은 계정의 add_start_request · create_run ·
        create_run_for_request는 부르지 않는다(MySQL은 다른 연결이라 이 잠금을 기다린다).
        """
        with self.engine.connect() as conn, self.account_lock(conn, account_id):
            yield

    # ── 중단 요청 ─────────────────────────────────────
    def request_abort(self, run_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(RUNS).where(RUNS.c.run_id == run_id).values(abort_requested=True))

    def is_abort_requested(self, run_id: str) -> bool:
        with self.engine.connect() as conn:
            return bool(conn.execute(select(RUNS.c.abort_requested).where(RUNS.c.run_id == run_id)).scalar())

    # ── 산출물 ────────────────────────────────────────
    def get_pointers(self, run_id: str) -> dict[str, int]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(ARTIFACT_POINTERS.c.artifact_key, ARTIFACT_POINTERS.c.version)
                                .where(ARTIFACT_POINTERS.c.run_id == run_id))
            return {r.artifact_key: r.version for r in rows}

    def get_latest_versions(self, run_id: str) -> dict[str, int]:
        t = ARTIFACT_VERSIONS
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.c.artifact_key, func.max(t.c.version).label("v"))
                                .where(t.c.run_id == run_id).group_by(t.c.artifact_key))
            return {r.artifact_key: r.v for r in rows}

    def get_artifact(self, run_id: str, key: str, version: int) -> ArtifactVersion:
        t = ARTIFACT_VERSIONS
        with self.engine.connect() as conn:
            row = conn.execute(select(t.c.value, t.c.producer, t.c.created_at).where(
                t.c.run_id == run_id, t.c.artifact_key == key, t.c.version == version)).first()
        if row is None:
            raise KeyError((run_id, key, version))
        return ArtifactVersion(run_id, key, version, row.value, row.producer, row.created_at)

    def delete_artifacts(self, run_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(ARTIFACT_VERSIONS).where(ARTIFACT_VERSIONS.c.run_id == run_id))
            conn.execute(delete(ARTIFACT_POINTERS).where(ARTIFACT_POINTERS.c.run_id == run_id))

    # ── 추적 기록 조회 ────────────────────────────────
    def executions(self, run_id: str) -> list[ExecutionRecord]:
        return [ExecutionRecord.model_validate(j) for j in self._records(EXECUTIONS, run_id)]

    def call_logs(self, run_id: str) -> list[CallLog]:
        return self._call_logs_where(CALL_LOGS.c.run_id == run_id)

    def _call_logs_where(self, cond: Any) -> list[CallLog]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(CALL_LOGS).where(cond).order_by(CALL_LOGS.c.seq)).mappings().all()
        return [CallLog.model_validate({f: r[f] for f in CallLog.model_fields}) for r in rows]

    def feedback(self, run_id: str) -> list[FeedbackLink]:
        return [FeedbackLink.model_validate(j) for j in self._records(FEEDBACK_LINKS, run_id)]

    def comparisons(self, run_id: str) -> list[ReworkComparison]:
        return [ReworkComparison.model_validate(j) for j in self._records(REWORK_COMPARISONS, run_id)]

    def pointer_events(self, run_id: str) -> list[PointerEvent]:
        t = POINTER_EVENTS
        with self.engine.connect() as conn:
            rows = conn.execute(select(t).where(t.c.run_id == run_id).order_by(t.c.seq)).all()
        return [PointerEvent(run_id=run_id, key=r.artifact_key, from_version=r.from_version,
                             to_version=r.to_version, reason=r.reason, cycle_id=r.cycle_id, at=r.at) for r in rows]

    def events(self, run_id: str) -> list[TraceEvent]:
        return [TraceEvent.model_validate(j) for j in self._records(TRACE_EVENTS, run_id)]

    def notifications(self, run_id: str) -> list[Notification]:
        with self.engine.connect() as conn:
            pid = conn.execute(select(RUNS.c.project_id).where(RUNS.c.run_id == run_id)).scalar()
            if pid is None:
                return []
            return self.web.notifications(conn, pid, run_id)

    def rejected_attempts(self, run_id: str) -> list[RejectedAttempt]:
        with self.engine.connect() as conn:
            pid = conn.execute(select(RUNS.c.project_id).where(RUNS.c.run_id == run_id)).scalar()
            if pid is None:
                return []
            return self.web.rejected_attempts(conn, pid, run_id)

    # ── 관리자 조회 ───────────────────────────────────
    def list_executions(self, f: ExecutionFilter) -> list[ExecutionRow]:
        t = EXECUTIONS
        order = [t.c.started_at.desc(), t.c.seq.desc()] if f.order == "desc" else [t.c.started_at, t.c.seq]
        stmt = _paged(select(t.c.project_id, t.c.record_json).where(*_execution_conds(f)).order_by(*order),
                      f.limit, f.offset)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [ExecutionRow(None if r.project_id is None else str(r.project_id),
                             ExecutionRecord.model_validate(r.record_json)) for r in rows]

    def count_executions(self, f: ExecutionFilter) -> int:
        with self.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(EXECUTIONS)
                                .where(*_execution_conds(f))).scalar_one()

    def execution_calls(self, execution_id: str) -> list[CallLog]:
        return self._call_logs_where(CALL_LOGS.c.execution_id == execution_id)

    # ── 기록 옮기기 · 보관 기간 · 탈퇴 (확장) ──────────
    def list_start_requests(self, account_id: str) -> list[StartRequest]:
        t = START_REQUESTS
        with self.engine.connect() as conn:
            rows = conn.execute(select(t).where(t.c.account_id == account_id)
                                .order_by(t.c.created_at, t.c.request_id)).all()
        return [_request_of(r) for r in rows]

    def has_pointers(self, run_id: str) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(select(ARTIFACT_POINTERS.c.run_id)
                                .where(ARTIFACT_POINTERS.c.run_id == run_id).limit(1)).first() is not None

    def retire_run(self, run_id: str, owner: str, *, stats: LogStatsRow | None = None, delete_run: bool = False,
                   bump_parts: bool = False) -> None:
        now = self._now()
        with self.engine.begin() as conn:
            row = conn.execute(select(RUNS.c.lease_owner, RUNS.c.run_json)
                               .where(RUNS.c.run_id == run_id).with_for_update()).first()
            if row is None or row.lease_owner != owner:
                raise StoreConflict("점유하지 않은 실행 건의 기록을 옮기려 함")   # 실행 건 ID는 싣지 않는다
            if stats is not None:
                conn.execute(insert(LOG_STATS).values(**_stats_values(stats, now)))
            for table in RECORD_TABLES:
                conn.execute(delete(table).where(table.c.run_id == run_id))
            if delete_run:
                conn.execute(delete(ARTIFACT_VERSIONS).where(ARTIFACT_VERSIONS.c.run_id == run_id))
                conn.execute(delete(ARTIFACT_POINTERS).where(ARTIFACT_POINTERS.c.run_id == run_id))
                conn.execute(delete(RUNS).where(RUNS.c.run_id == run_id))
            elif bump_parts:
                # run_json의 옮긴 횟수만 바꾼다 — updated_at 컬럼 · run_json의 updatedAt · 점유는 그대로
                stored = dict(row.run_json)
                stored["statsParts"] = int(stored.get("statsParts") or 0) + 1
                conn.execute(update(RUNS).where(RUNS.c.run_id == run_id).values(run_json=stored))

    def retire_start_requests(self, request_ids: list[str], stats: list[LogStatsRow]) -> int:
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("같은 시작 요청이 두 번 들어 있음")
        t, now = START_REQUESTS, self._now()
        with self.engine.begin() as conn:
            if request_ids:
                found = conn.execute(select(t.c.request_id).where(t.c.request_id.in_(request_ids),
                                                                  t.c.status.in_(FINISHED_REQUEST))
                                     .with_for_update()).all()
                if len(found) != len(request_ids):
                    raise StoreConflict("없거나 끝나지 않은 시작 요청이 섞여 있음")
            self._insert(conn, LOG_STATS, [_stats_values(row, now) for row in stats])
            if not request_ids:
                return 0
            return conn.execute(delete(t).where(t.c.request_id.in_(request_ids))).rowcount

    def retention_run_targets(self, cutoff: datetime, limit: int) -> list[str]:
        now = self._now()
        has_records = or_(*[exists().where(table.c.run_id == RUNS.c.run_id) for table in RECORD_TABLES])
        no_pointers = ~exists().where(ARTIFACT_POINTERS.c.run_id == RUNS.c.run_id)
        stmt = (select(RUNS.c.run_id)
                .where(RUNS.c.updated_at < cutoff, RUNS.c.progress.not_in(BUSY_PROGRESS),
                       or_(RUNS.c.lease_owner.is_(None), RUNS.c.lease_until <= now),
                       or_(has_records, no_pointers))   # 옮길 기록이 있거나 완전 삭제된 것만
                .order_by(RUNS.c.updated_at, RUNS.c.run_id).limit(limit))
        with self.engine.connect() as conn:
            return list(conn.execute(stmt).scalars())

    def retention_request_targets(self, cutoff: datetime, limit: int) -> list[StartRequest]:
        t = START_REQUESTS
        with self.engine.connect() as conn:
            rows = conn.execute(select(t).where(t.c.status.in_(FINISHED_REQUEST), t.c.updated_at < cutoff)
                                .order_by(t.c.updated_at, t.c.request_id).limit(limit)).all()
        return [_request_of(r) for r in rows]

    def log_stats(self, kind: str | None = None) -> list[LogStatsRow]:
        t = LOG_STATS
        stmt = select(t).order_by(t.c.seq)
        if kind is not None:
            stmt = stmt.where(t.c.kind == kind)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [LogStatsRow(kind=r.kind, reason=r.reason, month=r.month, category=r.category, status=r.status,
                            result_code=r.result_code, part=r.part, count=r.count, data=r.data_json,
                            created_at=r.created_at) for r in rows]

    # ── 주기 작업 점유 (확장) ─────────────────────────
    def try_start_job(self, job_name: str, owner: str, lease_sec: float, interval_sec: float) -> bool:
        """작업 줄이 없으면 만들고, 같은 트랜잭션에서 조건부 UPDATE로 점유한다 (영향 행 수로 판정).

        MySQL은 다른 워커의 점유 UPDATE가 끝날 때까지 행 잠금을 기다린 뒤 최신 값으로 조건을 다시 본다.
        """
        t, now = JOBS, self._now()
        if self._mysql:
            ins = mysql_insert(t).values(job_name=job_name)
            ins = ins.on_duplicate_key_update(job_name=ins.inserted.job_name)
        else:
            ins = sqlite_insert(t).values(job_name=job_name).on_conflict_do_nothing(index_elements=["job_name"])
        free = or_(t.c.lease_owner.is_(None), t.c.lease_until.is_(None), t.c.lease_until <= now)
        due = or_(t.c.last_finished_at.is_(None), t.c.last_finished_at <= now - timedelta(seconds=interval_sec))
        with self.engine.begin() as conn:
            conn.execute(ins)
            n = conn.execute(update(t).where(t.c.job_name == job_name, free, due).values(
                lease_owner=owner, lease_until=now + timedelta(seconds=lease_sec), last_started_at=now)).rowcount
        return n == 1

    def _update_job(self, job_name: str, owner: str, **values: Any) -> bool:
        t = JOBS
        with self.engine.begin() as conn:
            n = conn.execute(update(t).where(t.c.job_name == job_name, t.c.lease_owner == owner)
                             .values(**values)).rowcount
        return n == 1

    def renew_job(self, job_name: str, owner: str, lease_sec: float) -> bool:
        return self._update_job(job_name, owner, lease_until=self._now() + timedelta(seconds=lease_sec))

    def finish_job(self, job_name: str, owner: str, summary: dict[str, int]) -> bool:
        summary = check_summary(summary)
        return self._update_job(job_name, owner, lease_owner=None, lease_until=None, last_finished_at=self._now(),
                                last_summary=summary)

    def release_job(self, job_name: str, owner: str) -> bool:
        return self._update_job(job_name, owner, lease_owner=None, lease_until=None)

    def get_job(self, job_name: str) -> JobState | None:
        t = JOBS
        with self.engine.connect() as conn:
            r = conn.execute(select(t).where(t.c.job_name == job_name)).first()
        if r is None:
            return None
        return JobState(r.job_name, r.lease_owner, r.lease_until, r.last_started_at, r.last_finished_at,
                        r.last_summary)

    def _records(self, table: Table, run_id: str) -> list[Any]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(table.c.record_json).where(table.c.run_id == run_id).order_by(table.c.seq))
            return [r.record_json for r in rows]


# ── 조회 조건 ─────────────────────────────────────────
def _execution_conds(f: ExecutionFilter) -> list[Any]:
    t = EXECUTIONS
    conds: list[Any] = []
    if f.project_id is not None:
        conds.append(t.c.project_id == project_key(f.project_id))
    for col, value in ((t.c.task_id, f.task_id), (t.c.status, f.status), (t.c.agent, f.agent)):
        if value is not None:
            conds.append(col == value)
    if f.since is not None:
        conds.append(t.c.started_at >= f.since)
    if f.until is not None:
        conds.append(t.c.started_at < f.until)
    return conds


def _paged(stmt: Select, limit: int | None, offset: int) -> Select:
    """limit이 None이면 모두. offset은 0이 아닐 때만 건다 (MySQL은 LIMIT 없는 OFFSET을 받지 않아 SQLAlchemy가 큰 LIMIT을 붙인다)."""
    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt.offset(offset) if offset else stmt


# ── 모델 → 행 ─────────────────────────────────────────
def _run_values(run: Run) -> dict[str, Any]:
    """실행 건 행에서 조회 · 정렬에 쓰는 컬럼과 Run 전체. project_id · 점유 · 중단 요청은 여기서 바꾸지 않는다."""
    return dict(
        step=run.state.step, progress=run.state.progress, resume_step=run.state.resume_step,
        current_phase=run.current_phase, announcement_id=run.announcement_id, rework_screen=run.rework_screen,
        current_task=run.current_task, retry_count=run.retry_count, resume_count=run.resume_count,
        next_resume_at=run.next_resume_at, last_error_kind=run.last_error_kind,
        failure_reason=getattr(run, "failure_reason", None),
        collect_until=run.cycle.collect_until if run.cycle is not None else None,
        run_json=run.dump(), created_at=run.created_at, updated_at=run.updated_at, ended_at=run.ended_at)


def _stats_values(row: LogStatsRow, now: datetime) -> dict[str, Any]:
    """통계 줄 → orch_log_stats 행. created_at은 저장 시각(넘긴 값은 쓰지 않는다)."""
    return dict(kind=row.kind, reason=row.reason, month=row.month, category=row.category, status=row.status,
                result_code=row.result_code, part=row.part, count=row.count, data_json=row.data, created_at=now)


def _request_free(now: datetime):
    """가져갈 수 있는 시작 요청 — '대기', 또는 점유가 만료된 '처리중'(워커가 처리 도중 멈춤)."""
    t = START_REQUESTS
    return or_(t.c.status == "대기",
               and_(t.c.status == "처리중", or_(t.c.lease_until.is_(None), t.c.lease_until <= now)))


def _take_request(request_id: str, free, owner: str, lease_sec: float, now: datetime):
    """시작 요청을 '처리중'으로 점유하는 조건부 UPDATE. 다른 점유자가 가져갈 때만 가져간 횟수를 센다.

    가져간 횟수를 맨 앞에서 바꾼다 — MySQL은 SET을 왼쪽부터 적용해 뒤의 식이 바뀐 점유자를 보기 때문.
    """
    t = START_REQUESTS
    return (update(t).where(t.c.request_id == request_id, free)
            .ordered_values(
                (t.c.claim_count, t.c.claim_count + case((t.c.lease_owner == owner, 0), else_=1)),
                (t.c.status, "처리중"), (t.c.lease_owner, owner),
                (t.c.lease_until, now + timedelta(seconds=lease_sec)), (t.c.updated_at, now)))


def _request_values(req: StartRequest) -> dict[str, Any]:
    return dict(
        request_id=req.request_id, project_id=project_key(req.project_id), account_id=req.account_id,
        status=req.status, form_json=req.form, result_code=req.result_code, result_message=req.result_message,
        result_detail=req.result_detail, notices=[n.dump() for n in req.notices], run_id=req.run_id,
        cancel_requested=req.cancel_requested, claim_count=req.claim_count, lease_owner=req.lease_owner,
        lease_until=req.lease_until, created_at=req.created_at, updated_at=req.updated_at,
        finished_at=req.finished_at)


def _request_of(row: Row) -> StartRequest:
    return StartRequest(
        request_id=row.request_id, project_id=None if row.project_id is None else str(row.project_id),
        account_id=row.account_id, status=row.status, form=row.form_json, result_code=row.result_code,
        result_message=row.result_message, result_detail=row.result_detail, notices=row.notices or [],
        run_id=row.run_id, cancel_requested=bool(row.cancel_requested), claim_count=row.claim_count,
        lease_owner=row.lease_owner, lease_until=row.lease_until, created_at=row.created_at,
        updated_at=row.updated_at, finished_at=row.finished_at)


def _execution_row(rec: ExecutionRecord, run_id: str, project_id: int | None) -> dict[str, Any]:
    return dict(
        execution_id=rec.execution_id, run_id=run_id, project_id=project_id, task_id=rec.task_id,
        attempt=rec.attempt, trigger=rec.trigger, bundle_id=rec.bundle_id, agent=rec.agent,
        step_kind=rec.step_kind, model=rec.model, provider=rec.provider, temperature=rec.temperature,
        reasoning_effort=rec.reasoning_effort, status=rec.status, error_kind=rec.error_kind, error=rec.error,
        cycle_id=rec.cycle_id, redo_count=rec.redo_count, resume_count=rec.resume_count,
        created_at=rec.created_at, started_at=rec.started_at, ended_at=rec.ended_at, record_json=rec.dump(),
        **{f: getattr(rec, f) for f in TOKEN_FIELDS},
        **{f: getattr(rec, f) for _, f in IMAGE_TOKEN_FIELDS})


def _call_row(log: CallLog) -> dict[str, Any]:
    """호출 기록은 필드마다 컬럼에 둔다(시도 목록은 JSON). 읽을 때 같은 이름으로 되돌린다."""
    row = {f: getattr(log, f) for f in CallLog.model_fields if f != "tries"}
    row["tries"] = [t.dump() for t in log.tries]
    row["started_at"] = log.tries[0].started_at if log.tries else None
    row["ended_at"] = log.tries[-1].ended_at if log.tries else None
    return row
