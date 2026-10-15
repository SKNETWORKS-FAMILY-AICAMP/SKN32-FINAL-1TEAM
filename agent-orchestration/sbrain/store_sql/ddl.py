"""Orchestrator 테이블의 MySQL DDL 파일을 만든다.

    python -m sbrain.store_sql.ddl        # sql/orchestrator_schema.sql 갱신

- 정의는 schema.py 하나다. 이 파일은 그것을 MySQL 문으로 옮기기만 한다.
- MySQL 8은 CREATE INDEX IF NOT EXISTS가 없어서 인덱스를 CREATE TABLE 안의 KEY로 넣는다.
  그래서 파일 전체가 CREATE TABLE IF NOT EXISTS뿐이고, 여러 번 적용해도 안전하다.
- 공유 DB에 적용하는 일은 사용자가 한다. 테스트가 파일과 생성 결과가 같은지 확인한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import Index, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from .schema import ORCH_TABLES

DDL_PATH = Path(__file__).resolve().parents[2] / "sql" / "orchestrator_schema.sql"

HEADER = """\
-- S-Brain Orchestrator 테이블 (MySQL 8 이상)
--
-- 이 파일은 코드에서 만든다. 직접 고치지 않는다.
--   정의: sbrain/store_sql/schema.py
--   생성: python -m sbrain.store_sql.ddl
--
-- 적용 순서: 웹 스키마(app_schema.sql) 다음. orch_runs.project_id가 projects(project_id)를 참조한다.
-- CREATE TABLE IF NOT EXISTS만 있다. 이미 있는 테이블은 바꾸지 않는다.
-- 웹 테이블 구조는 바꾸지 않는다. Orchestrator는 웹 테이블 중 notifications, generation_failure_alerts,
-- proofread_logs에 INSERT만 하고, verification_policies와 학습 동의(users.ai_training_agreed)를 읽는다.
"""


def _key(index: Index, dialect) -> str:
    prep = dialect.identifier_preparer
    cols = ", ".join(prep.quote(c.name) for c in index.columns)
    kind = "UNIQUE KEY" if index.unique else "KEY"
    return f"{kind} {prep.quote(index.name)} ({cols})"


def render_table(table: Table) -> str:
    dialect = mysql.dialect()
    sql = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip()
    keys = [_key(i, dialect) for i in sorted(table.indexes, key=lambda i: i.name)]
    if keys:
        head, sep, tail = sql.rpartition("\n)")
        sql = head + "".join(f", \n\t{k}" for k in keys) + sep + tail
    return sql + ";"


def render() -> str:
    return HEADER + "".join(f"\n{render_table(t)}\n" for t in ORCH_TABLES)


def main() -> None:
    DDL_PATH.parent.mkdir(exist_ok=True)
    DDL_PATH.write_text(render(), encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(errors="replace")
    print(f"썼다: {DDL_PATH} (테이블 {len(ORCH_TABLES)}개)")


if __name__ == "__main__":
    main()
