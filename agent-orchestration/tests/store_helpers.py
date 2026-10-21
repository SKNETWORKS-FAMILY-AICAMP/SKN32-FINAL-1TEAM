"""저장소 시험 도움 — 저장소 계약 테스트와 SqlStore 테스트가 함께 쓰는 실행 건 만들기, 한 시점 읽기 구간 시험 도움.

여러 테스트가 같은 MySQL DB를 쓰므로 계정 · 실행 건 ID는 uid()로 테스트마다 새로 만든다.

한 시점 읽기 구간(Store.read_snapshot) 시험 도움 (성능 측정 C 후속, 2026-10-20):
- count_sql(engine): SQL 엔진에서 한 구간 동안 보낸 SELECT 문장 수와 연결 꺼내기 수를 센다.
- write_during_snapshot(store, write): 구간의 첫 창구 읽기 직후 다른 스레드에서 쓰기 하나를 끼운다.
- SQL_STORES · sql_backend: SQL 저장소(SQLite · MySQL)에서만 도는 시험(문장 수 · 연결 수)의 매개변수와 장치. 쓰는 테스트
  파일은 `from store_helpers import sql_backend`로 장치를 가져다 쓴다(pytest가 모듈에 있는 장치를 찾는다).
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from conftest import Backend, Clock
from mysqldb import MYSQL
from sqlalchemy import Engine, event

from sbrain.models import Run
from sbrain.models.run import make_state


def uid() -> str:
    return uuid.uuid4().hex[:12]


def new_run(clock: Clock, account: str, *, project_id: str | None = None, progress: str = "실행",
            step: str = "공고선택", **over) -> Run:
    now = clock()
    return Run(run_id=uid(), account_id=account, state=make_state(step, progress), current_phase="setup",
               settings_snapshot={"note": "test"}, updated_at=now, created_at=now, project_id=project_id, **over)


# ── SQL 저장소만 도는 시험 ───────────────────────────────
# 메모리 저장소는 SQL 문장이 없어 뺀다. MySQL 매개변수는 MySQL 묶음이다
SQL_STORES = ("sql", pytest.param("mysql", marks=MYSQL))


@pytest.fixture(params=SQL_STORES)
def sql_backend(request, tmp_path) -> Backend:
    """SQL 저장소만 (SQLite · MySQL) — 문장 수 · 연결 수를 세는 시험."""
    return Backend(request.param, tmp_path)


# ── SQL 문장 · 연결 세기 ────────────────────────────────
@dataclass
class SqlCounts:
    """count_sql이 센 값 — 구간이 끝난 뒤에도 그대로 남는다."""
    selects: int = 0                                     # SELECT로 시작하는 문장 수
    checkouts: int = 0                                   # 풀에서 연결을 꺼낸 수
    statements: list[str] = field(default_factory=list)  # 센 동안 보낸 문장 전부(SELECT 아닌 것 포함 — 확인용)

    @property
    def others(self) -> int:
        """SELECT가 아닌 문장 수 (SQLite의 BEGIN IMMEDIATE 등)."""
        return len(self.statements) - self.selects


@contextmanager
def count_sql(engine: Engine) -> Iterator[SqlCounts]:
    """with 구간 동안 engine이 보낸 SQL 문장과 연결 꺼내기를 센다.

    쓰는 법:
        with count_sql(store.engine) as counts:
            admin_runs(orch)                       # 세고 싶은 호출
        assert counts.selects == 3 and counts.checkouts == 1

    - 문장은 SQLAlchemy 'before_cursor_execute' 이벤트로, 연결 꺼내기는 풀 'checkout' 이벤트로 센다. 같은 엔진에 겹쳐 걸어도
      된다(바깥 · 안쪽이 따로 센다).
    - 세지 않는 것: 드라이버 커서로 바로 보내는 문장 — MySQL 연결의 격리 수준 문장(SET SESSION TRANSACTION … · COMMIT —
      한 시점 구간이 그 연결만 REPEATABLE READ로 바꾸고 돌려줄 때 되돌리는 것), 트랜잭션 끝(rollback · commit은 드라이버
      호출), 연결 확인(pool_pre_ping은 드라이버 ping). SQLite의 'BEGIN IMMEDIATE'는 세지만 SELECT가 아니라 others에 든다.
    - 한 번만 나가는 문장은 세기 전에 같은 호출을 한 번 불러 데워 뺀다: 웹 표 구조 읽기(WebTables가 저장소마다 처음 쓸 때
      한 번 — SQLite PRAGMA · sqlite_master SELECT, MySQL SHOW · information_schema 문장 등), MySQL 첫 연결 설정 문장
      (SELECT DATABASE() · SHOW VARIABLES 등 — 엔진이 처음 연결할 때 한 번). 데운 뒤 두 번째 호출을 센다.
    - 다른 스레드가 같은 엔진으로 보낸 문장도 센다 — 세는 동안 다른 스레드가 같은 엔진을 쓰지 않게 한다.
    """
    counts = SqlCounts()

    def on_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        counts.statements.append(statement)
        if statement.lstrip().upper().startswith("SELECT"):
            counts.selects += 1

    def on_checkout(dbapi_connection, connection_record, connection_proxy) -> None:
        counts.checkouts += 1

    event.listen(engine, "before_cursor_execute", on_execute)
    event.listen(engine, "checkout", on_checkout)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
        event.remove(engine, "checkout", on_checkout)


# ── 구간 안에 다른 스레드의 쓰기 끼우기 ─────────────────────
HOLD_SEC = 1.0          # 메모리 · SQLite — 첫 창구 읽기 뒤 쓰기를 기다리는 시간. 쓰기는 구간 끝까지 기다리므로 늘 이만큼 지난 뒤 구간을 이어 간다
MYSQL_HOLD_SEC = 10.0   # MySQL — 쓰기가 끝나기를 기다리는 최대 시간. 쓰기가 끝나면 바로 이어 가므로 평소 비용은 없다
                        # (탈퇴 · 12개월 처리처럼 트랜잭션이 여러 개인 쓰기가 바쁜 PC에서 1초를 넘긴 일이 있어 늘림)
JOIN_SEC = 60.0         # 구간이 끝난 뒤 쓰기 스레드를 기다리는 최대 시간 (SQLite 쓰기는 잠금을 30초까지 기다린다)


def _is_mysql_store(store: Any) -> bool:
    engine = getattr(store, "engine", None)
    return getattr(getattr(engine, "dialect", None), "name", None) == "mysql"


@dataclass
class SnapshotWrite:
    """write_during_snapshot의 결과 — 구간이 끝난 뒤(with 블록 안쪽 구간을 닫은 뒤) 채워진다."""
    started: bool = False                       # 쓰기를 끼웠다(창구 읽기가 있었다)
    after: str | None = None                    # 쓰기를 끼운 창구 읽기 이름
    finished_in_snapshot: bool | None = None    # 구간을 이어 갈 때 쓰기가 이미 끝났나 — MySQL은 참(기다리지 않음),
                                                # 메모리 · SQLite는 거짓(쓰기가 구간 끝을 기다림)
    finished: bool = False                      # 구간이 끝난 뒤 쓰기가 끝났다
    result: Any = None                          # 쓰기 함수가 돌려준 값
    error: BaseException | None = None          # 쓰기 함수가 올린 예외 (쓰기 스레드가 끝나지 않으면 TimeoutError)


class _HookedSnapshot:
    """구간 창구를 감싸 — 읽기가 끝나면 hook(읽기 이름)을 부른다. 값 · 예외는 창구 그대로다."""

    def __init__(self, view: Any, hook: Callable[[str], None]) -> None:
        self._view = view
        self._hook = hook

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._view, name)
        if name.startswith("_") or not callable(value):
            return value

        def read(*args: Any, **kwargs: Any) -> Any:
            out = value(*args, **kwargs)
            self._hook(name)
            return out
        return read

    def __dir__(self) -> list[str]:
        return dir(self._view)


@contextmanager
def write_during_snapshot(store: Any, write: Callable[[], Any], *, after: str | None = None,
                          hold_sec: float | None = None, join_sec: float = JOIN_SEC) -> Iterator[SnapshotWrite]:
    """with 블록 동안 store.read_snapshot()을 감싸, 구간의 첫 창구 읽기(after를 주면 그 이름의 첫 읽기)가 끝난 직후
    다른 스레드에서 write()를 한 번 부른다.

    쓰는 법 (저장소 시험 · 흐름 함수 시험 모두):
        def write():                               # 다른 스레드에서 돈다 — 저장소 일반 메서드로 새 버전 · 포인터 저장 등
            save(store, run, versions=[v2], pointers={"planDoc": 2})
        with write_during_snapshot(store, write) as outcome:
            rows = admin_runs(orch)                # 안에서 orch.store.read_snapshot()을 연다 (같은 store 객체여야 한다)
        assert outcome.started and outcome.finished and outcome.error is None
        assert outcome.finished_in_snapshot is (kind == "mysql")   # 메모리 · SQLite는 쓰기가 구간 끝을 기다린다
        # rows는 쓰기 전 순간의 값이어야 한다

    - 끼우는 방식: store 객체의 read_snapshot을 이 블록 동안 감싼 것으로 바꿔 끼우고(인스턴스 속성), 감싼 구간이 돌려주는
      창구의 읽기가 끝날 때 쓰기 스레드를 시작한다. 블록이 끝나면 원래대로 되돌린다. 쓰기는 블록 안에서 처음 연 구간의
      첫 읽기(또는 after 읽기) 뒤 한 번만 끼운다 — 뒤의 구간 · 읽기는 그대로 지나간다.
    - 기다림: 쓰기를 시작한 뒤 쓰기가 끝나거나(MySQL — 일관된 읽기라 쓰기가 기다리지 않는다) hold_sec이 지나면(메모리 —
      저장소 잠금, SQLite — BEGIN IMMEDIATE 잠금을 쓰기가 기다린다) 구간을 이어 간다. hold_sec을 주지 않으면 MySQL 저장소는
      MYSQL_HOLD_SEC(끝나면 바로 이어 감), 메모리 · SQLite는 HOLD_SEC이다. 구간이 끝난 뒤(잠금 · 연결을 놓은 뒤) 쓰기
      스레드를 join_sec까지 기다려 결과를 채운다.
    - 쓰기는 반드시 다른 스레드다 — 같은 스레드에서 쓰면 메모리 저장소의 RLock이 다시 들어가 쓰기가 구간 안에 섞인다.
      write 안에서 구간을 연 스레드가 쓰는 값(시계 등)을 같이 부르지 않게, 쓸 값은 미리 만들어 둔다.
    - 이 장치는 시간에 기대므로 이 장치를 쓰는 테스트는 TIMING 묶음(MySQL이면 MySQL 묶음)에 넣는다.
    """
    if hold_sec is None:
        hold_sec = MYSQL_HOLD_SEC if _is_mysql_store(store) else HOLD_SEC
    outcome = SnapshotWrite()
    done = threading.Event()
    worker: list[threading.Thread] = []
    original = store.read_snapshot

    def run_write() -> None:
        try:
            outcome.result = write()
        except BaseException as e:   # 결과로 돌려준다 — 부른 쪽이 본다
            outcome.error = e
        finally:
            done.set()

    def hook(name: str) -> None:
        if outcome.started or (after is not None and name != after):
            return
        outcome.started, outcome.after = True, name
        thread = threading.Thread(target=run_write, name="snapshot-write", daemon=True)
        worker.append(thread)
        thread.start()
        outcome.finished_in_snapshot = done.wait(hold_sec)

    def join() -> None:
        if not worker or outcome.finished:
            return
        worker[0].join(join_sec)
        outcome.finished = done.is_set()
        if not outcome.finished and outcome.error is None:
            outcome.error = TimeoutError("쓰기 스레드가 끝나지 않음")

    @contextmanager
    def hooked_snapshot() -> Iterator[Any]:
        try:
            with original() as view:
                yield _HookedSnapshot(view, hook)
        finally:
            join()   # 구간을 닫은 뒤(잠금 · 연결을 놓은 뒤) 쓰기 스레드를 기다린다

    own = "read_snapshot" in vars(store)   # 이미 바꿔 끼운 것이 있으면 그것으로 되돌린다
    store.read_snapshot = hooked_snapshot
    try:
        yield outcome
    finally:
        if own:
            store.read_snapshot = original
        else:
            del store.read_snapshot   # 클래스의 read_snapshot으로 되돌린다
        join()
