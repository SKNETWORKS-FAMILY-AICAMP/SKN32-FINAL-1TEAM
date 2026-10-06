"""DB 접속 엔진 만들기.

- 운영: 공유 MySQL 8. 접속 URL은 환경 변수 · .env에서 받는다(예: SBRAIN_DB_URL). 코드에 넣지 않는다.
  격리 수준은 READ COMMITTED (잠정) — 할 일 가져가기(SKIP LOCKED)와 계정 잠금 뒤 개수 세기가
  항상 최신 확정 값을 보게 하고, 범위 잠금으로 인한 대기를 줄인다.
- 테스트: SQLite 파일 DB. 쓰기 교착을 피하려고 모든 트랜잭션을 BEGIN IMMEDIATE로 시작한다
  (SQLAlchemy 문서의 pysqlite 트랜잭션 처리 방식). 메모리 DB(sqlite://)는 연결마다 따로라 쓰지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event


def create_db_engine(url: str, **kwargs: Any) -> Engine:
    if url.startswith("sqlite"):
        return create_sqlite_engine(url)
    kwargs.setdefault("pool_pre_ping", True)
    kwargs.setdefault("pool_recycle", 3600)
    kwargs.setdefault("isolation_level", "READ COMMITTED")
    return create_engine(url, **kwargs)


def create_sqlite_engine(path: str | Path, *, fast: bool = False) -> Engine:
    """SQLite 파일 DB. fast=True면 디스크 동기화를 끈다(테스트 전용)."""
    url = str(path) if str(path).startswith("sqlite") else f"sqlite:///{Path(path).as_posix()}"
    if url in ("sqlite://", "sqlite:///:memory:"):
        raise ValueError("SQLite 메모리 DB는 연결마다 따로라 저장소로 쓸 수 없다 — 파일 DB를 쓴다")
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn, _record) -> None:
        dbapi_conn.isolation_level = None   # 드라이버의 자동 BEGIN을 끄고 아래 begin에서 직접 연다
        if fast:
            dbapi_conn.execute("PRAGMA synchronous=OFF")

    @event.listens_for(engine, "begin")
    def _begin(conn) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine
