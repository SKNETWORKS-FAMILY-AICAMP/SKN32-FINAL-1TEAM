"""MySQL 8 통합 테스트용 DB 준비 (로컬 Docker — docker/mysql-test.yml).

- 환경 변수(또는 .env) SBRAIN_TEST_MYSQL_URL이 있을 때만 쓴다. 없으면 MySQL 테스트는 건너뛴다.
- 안전장치: 호스트가 로컬(127.0.0.1 · localhost)이고 DB 이름에 test가 들어간 경우만 쓴다.
  테스트는 그 DB의 테이블을 모두 지우고 새로 만들기 때문이다. 공유 DB로는 절대 돌리지 않는다.
- 준비 순서: 테스트 전용 최소 notices → 웹 스키마(app_schema.sql, 읽기만) → 테스트 전용 proofread_logs 변경 →
  sql/orchestrator_schema.sql.
  app_schema.sql은 공고 수집 스키마의 notices를 외래 키로 참조하는데 그 스키마는 이 프로젝트에 없어
  notice_id(UNIQUE)만 있는 notices를 먼저 만든다.
- proofread_logs는 웹 스키마가 아직 business_plans 기준(plan_id NOT NULL)이라, 웹팀이 바꿀 모양을 테스트 DB에서만
  흉내 낸다: plan_id NULL 허용 · business_plans/plan_sections 외래 키 제거, project_id(→ projects, NULL 허용 ·
  ON DELETE SET NULL) · model_version 추가. created_at은 웹 스키마에 이미 있다(Orchestrator가 저장 시각을 넣는다).
  app_schema.sql 파일은 고치지 않는다. 옛 모양은 old_proofread_logs()로 잠시 되돌려 시험한다.
- app_schema.sql 위치: 환경 변수(또는 .env) SBRAIN_TEST_WEB_SCHEMA가 있으면 그 파일, 없으면 이 폴더 두 단계 위에서
  web/backend/app_schema.sql(웹과 같은 저장소에 둔 배치) → 01_원본/web/backend/app_schema.sql(작업 공간 배치) 순서로 찾는다.
- MySQL 묶음: 테스트는 기본으로 여러 프로세스에서 동시에 돈다(pytest.ini). MySQL 테스트는 표를 처음 한 번만 새로 만들어
  함께 쓰고, 남긴 일을 끝에 정리하는 규칙이 한 프로세스 안에서만 맞으므로 모두 MYSQL 묶음(xdist_group "mysql")에 넣어
  한 프로세스에서 하나씩 돌린다. 넣는 법: 매개변수면 pytest.param("mysql", marks=MYSQL), 파일 전체면 pytestmark = MYSQL.
  require_mysql()은 실행 중인 테스트가 그 묶음에만 들었는지 먼저 확인하고, 아니면 (DB가 없어 건너뛸 때도) 실패시킨다.
"""
from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Engine, make_url

from sbrain.env import get_env
from sbrain.store_sql import create_db_engine
from sbrain.store_sql.ddl import DDL_PATH

URL_ENV = "SBRAIN_TEST_MYSQL_URL"
WEB_SCHEMA_ENV = "SBRAIN_TEST_WEB_SCHEMA"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_BASE = Path(__file__).resolve().parents[2]
WEB_SCHEMA_CANDIDATES = (_BASE / "web" / "backend" / "app_schema.sql",              # 웹과 같은 저장소
                         _BASE / "01_원본" / "web" / "backend" / "app_schema.sql")  # 작업 공간

TEST_NOTICES = """
CREATE TABLE IF NOT EXISTS notices (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    notice_id VARCHAR(320) NOT NULL,
    UNIQUE KEY uq_notices_notice_id (notice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""


def mysql_url() -> str | None:
    return get_env(URL_ENV)


def web_schema() -> Path:
    """웹 스키마 파일 (읽기만). 환경 변수가 가리키는 파일이 없거나 후보 어디에도 없으면 테스트 실패."""
    given = get_env(WEB_SCHEMA_ENV)
    candidates = (Path(given),) if given else WEB_SCHEMA_CANDIDATES
    for path in candidates:
        if path.is_file():
            return path
    pytest.fail(f"웹 스키마 app_schema.sql을 찾지 못함 ({', '.join(str(p) for p in candidates)}) — "
                f"{WEB_SCHEMA_ENV}에 파일 경로를 넣는다")


MYSQL_GROUP = "mysql"
MYSQL = pytest.mark.xdist_group(MYSQL_GROUP)
_current_test: pytest.Item | None = None   # conftest.py의 pytest_runtest_protocol이 테스트마다 넣고 뺀다


def set_current_test(item: pytest.Item | None) -> None:
    global _current_test
    _current_test = item


def group_name(mark: pytest.Mark) -> str:
    """xdist_group 표시 하나의 묶음 이름."""
    return str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))


def xdist_groups(item: pytest.Item) -> set[str]:
    """테스트가 든 동시 실행 묶음(xdist_group) 이름들 — 매개변수 · 함수 · 파일에 붙은 표시를 모두 본다."""
    return {group_name(m) for m in item.iter_markers("xdist_group")}


def check_mysql_group() -> None:
    """실행 중인 테스트가 MySQL 묶음에만 들었는지 확인한다. 아니면 크게 실패 (테스트 밖에서 부르면 확인 안 함)."""
    item = _current_test
    if item is not None and xdist_groups(item) != {MYSQL_GROUP}:
        pytest.fail(f"MySQL에 닿는 테스트는 MySQL 묶음(mysqldb.MYSQL)에만 넣어야 함 — {item.nodeid} "
                    f"(지금 묶음: {sorted(xdist_groups(item)) or '없음'})", pytrace=False)


def require_mysql() -> Engine:
    check_mysql_group()                    # DB가 없어 건너뛸 때도 먼저 확인한다
    url = mysql_url()
    if not url:
        pytest.skip(f"{URL_ENV} 없음 — MySQL 통합 테스트 건너뜀 (docker/mysql-test.yml 참고)")
    return _prepared_engine(url)


@functools.cache
def _prepared_engine(url: str) -> Engine:
    u = make_url(url)
    if u.host not in LOCAL_HOSTS or "test" not in (u.database or ""):
        pytest.fail(f"{URL_ENV}는 로컬 테스트 DB여야 함 (호스트 {u.host}, DB {u.database}) — 테이블을 모두 지우므로 거부")
    engine = create_db_engine(url)
    _reset(engine, u.database)
    return engine


def _reset(engine: Engine, database: str) -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (database,))
        tables = [r[0] for r in cur.fetchall()]
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for t in tables:
            cur.execute(f"DROP TABLE IF EXISTS `{t}`")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        for stmt in split_sql(TEST_NOTICES) + split_sql(web_schema().read_text(encoding="utf-8")):
            cur.execute(stmt)   # 인자 없이 실행 — 문장 속 %를 형식 문자로 보지 않는다
        _proofread_logs_test_change(cur, database)
        for stmt in split_sql(DDL_PATH.read_text(encoding="utf-8")):
            cur.execute(stmt)
        raw.commit()
    finally:
        raw.close()


def _proofread_logs_test_change(cur, database: str) -> None:
    """테스트 전용 — proofread_logs를 웹 스키마 변경 뒤 모양으로 (project_id 기준, plan_id 없어도 됨)."""
    cur.execute("SELECT constraint_name FROM information_schema.referential_constraints "
                "WHERE constraint_schema = %s AND table_name = 'proofread_logs'", (database,))
    for (name,) in cur.fetchall():
        cur.execute(f"ALTER TABLE proofread_logs DROP FOREIGN KEY `{name}`")
    cur.execute(
        "ALTER TABLE proofread_logs "
        "MODIFY plan_id BIGINT UNSIGNED NULL, "
        "ADD COLUMN project_id BIGINT UNSIGNED NULL AFTER log_id, "
        "ADD COLUMN model_version VARCHAR(50) NULL, "
        "ADD KEY ix_proofread_logs_project (project_id), "
        "ADD CONSTRAINT fk_proofread_logs_project_test FOREIGN KEY (project_id) "
        "REFERENCES projects(project_id) ON DELETE SET NULL")


def _old_proofread_logs_ddl() -> str:
    return next(s for s in split_sql(web_schema().read_text(encoding="utf-8"))
                if s.startswith("CREATE TABLE IF NOT EXISTS proofread_logs"))


@contextmanager
def old_proofread_logs(engine: Engine) -> Iterator[None]:
    """테스트 동안 proofread_logs를 app_schema.sql 그대로의 옛 모양(plan_id NOT NULL, project_id 없음)으로 둔다."""
    _execute(engine, "RENAME TABLE proofread_logs TO proofread_logs_t1_saved", _old_proofread_logs_ddl())
    try:
        yield
    finally:
        _execute(engine, "DROP TABLE proofread_logs", "RENAME TABLE proofread_logs_t1_saved TO proofread_logs")


def _execute(engine: Engine, *stmts: str) -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for stmt in stmts:
            cur.execute(stmt)
        raw.commit()
    finally:
        raw.close()


def split_sql(script: str) -> list[str]:
    """SQL 스크립트를 문장으로 나눈다. 따옴표 안의 ; · -- 는 건드리지 않고, -- 주석은 지운다."""
    stmts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(script)
    while i < n:
        ch = script[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(script[i + 1])
                i += 2
                continue
            if ch == quote:
                if script[i + 1:i + 2] == quote:   # '' · "" 이스케이프
                    buf.append(quote)
                    i += 2
                    continue
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
        elif script.startswith("--", i):
            j = script.find("\n", i)
            i = n if j < 0 else j
            continue
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    stmt = "".join(buf).strip()
    if stmt:
        stmts.append(stmt)
    return stmts
