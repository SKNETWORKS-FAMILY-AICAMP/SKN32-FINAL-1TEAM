"""SQLAlchemy 엔진/세션. 기존 수집 파이프라인의 config.py 를 그대로 재사용한다.

repo 루트에서 `uvicorn app.main:app --reload` 로 띄우는 것을 전제로,
repo 루트의 config.py 를 import 한다(별도 .env 파서를 새로 만들지 않는다).
"""
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# repo 루트를 sys.path 에 보장 (app/ 하위에서 실행되는 경우 대비)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
import config as pipeline_config  # noqa: E402 -- repo 루트를 sys.path 에 넣은 뒤라야 import 가능


def _database_url() -> str:
    user = pipeline_config.require('MYSQL_USER')
    password = pipeline_config.require('MYSQL_PASSWORD')
    host = pipeline_config.get('MYSQL_HOST', '127.0.0.1')
    port = pipeline_config.get('MYSQL_PORT', '3306')
    database = pipeline_config.require('MYSQL_DATABASE')
    # store_mysql.py 와 동일하게 PyMySQL 드라이버를 쓴다 (새 의존성 추가하지 않음)
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


engine = create_engine(
    _database_url(),
    pool_pre_ping=True,   # MySQL wait_timeout 으로 끊긴 커넥션 자동 감지
    pool_recycle=1800,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI Depends 용 세션 제너레이터."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()