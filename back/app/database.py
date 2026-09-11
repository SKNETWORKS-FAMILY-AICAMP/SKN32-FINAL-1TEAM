"""SQLAlchemy 엔진/세션. 기존 수집 파이프라인의 config.py 를 그대로 재사용한다.

repo 루트에서 `uvicorn app.main:app --reload` 로 띄우는 것을 전제로,
repo 루트의 config.py 를 import 한다(별도 .env 파서를 새로 만들지 않는다).

DB_BACKEND=sqlite 로 로컬 SQLite 파일을 쓸 수도 있다 (.env, 개인 개발용).
기본값은 mysql — 팀이 공유하는 AWS MySQL을 쓴다.

주의: SQLite 모드는 app_schema.sql을 쓰지 않는다(그 파일은 MySQL 전용 문법이 섞여있음).
대신 아래 init_sqlite_dev_db() 가 models.py 정의 그대로 테이블을 만든다. 즉 SQLite에선
app_schema.sql/실제 MySQL과 타입이 100% 동일하다는 보장이 없다 — "일단 로직 돌려보는 용도"로만
쓰고, 스키마 자체를 검증하려면 여전히 MySQL(테스트 스위트의 pytest 방식 참고)을 써야 한다.
또한 notices 테이블은 공고 수집 파이프라인이 채워주는 건데, SQLite 모드에서는 빈 테이블로
새로 생기기만 하므로 매칭 등을 테스트하려면 직접 더미 행을 넣어야 한다.
"""
import os
import sys

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# repo 루트를 sys.path 에 보장 (app/ 하위에서 실행되는 경우 대비)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
import config as pipeline_config  # noqa: E402 -- repo 루트를 sys.path 에 넣은 뒤라야 import 가능


class Base(DeclarativeBase):
    pass


@compiles(BigInteger, 'sqlite')
def _bigint_as_sqlite_integer(element, compiler, **kw):
    # SQLite는 "INTEGER PRIMARY KEY" 만 rowid/AUTOINCREMENT 별칭으로 취급한다.
    # BigInteger를 그대로 두면 PK 자동증가가 안 먹으니 sqlite 방언에서만 INTEGER로 내려준다
    # (테스트 스위트의 conftest.py와 동일한 규칙 — MySQL 렌더링엔 영향 없음).
    return 'INTEGER'


def _database_url() -> str:
    backend = pipeline_config.get('DB_BACKEND', 'mysql').strip().lower()
    if backend == 'sqlite':
        path = pipeline_config.get('SQLITE_PATH') or os.path.join(_REPO_ROOT, 'dev.db')
        return f'sqlite:///{path}'
    user = pipeline_config.require('MYSQL_USER')
    password = pipeline_config.require('MYSQL_PASSWORD')
    host = pipeline_config.get('MYSQL_HOST', '127.0.0.1')
    port = pipeline_config.get('MYSQL_PORT', '3306')
    database = pipeline_config.require('MYSQL_DATABASE')
    # store_mysql.py 와 동일하게 PyMySQL 드라이버를 쓴다 (새 의존성 추가하지 않음)
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


_DATABASE_URL = _database_url()
IS_SQLITE = _DATABASE_URL.startswith('sqlite')

engine = create_engine(
    _DATABASE_URL,
    connect_args={'check_same_thread': False} if IS_SQLITE else {},
    pool_pre_ping=not IS_SQLITE,          # SQLite는 커넥션 풀 걱정이 없음
    pool_recycle=1800 if not IS_SQLITE else -1,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_sqlite_dev_db() -> None:
    """SQLite 로컬 개발 모드(DB_BACKEND=sqlite)일 때만 실제로 동작한다.
    app.main 이 기동 시 호출해서, models.py 에 정의된 테이블을 dev.db에 만들어준다.
    MySQL 모드에서는 아무 일도 하지 않는다(스키마는 app_schema.sql로 직접 적용)."""
    if not IS_SQLITE:
        return
    import app.models  # noqa: F401 -- Base.metadata 에 테이블들을 등록시키기 위한 import
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI Depends 용 세션 제너레이터."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()