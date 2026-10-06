"""워커 E2E 테스트용 로컬 MySQL 준비 — 웹 스키마(app_schema.sql) + 오케스트레이터 표(orchestrator_schema.sql)를 새로 만든다.

    python scripts/prepare_local_mysql.py                      # 기본: 127.0.0.1:3307 의 sbrain_e2e
    python scripts/prepare_local_mysql.py --url mysql+pymysql://root:비밀번호@127.0.0.1:3307/내_e2e_db?charset=utf8mb4

★ 그 DB의 테이블을 모두 지우고 새로 만든다. 그래서 로컬 호스트(127.0.0.1 · localhost) + DB 이름에 'e2e' 또는 'test'가 있는
  경우만 받는다 — 팀 공유 DB 주소를 넣어도 거부한다.
- 로컬 MySQL은 agent-orchestration 폴더에서 `docker compose -f docker/mysql-test.yml up -d --wait`로 띄운다(데이터는 메모리에만 있음).
- 공고 수집 파이프라인이 소유한 notices 표는 이 저장소에 없어서 notice_id만 있는 최소 표를 먼저 만든다(웹 스키마가 참조).
"""
import argparse
import pathlib
import sys

import pymysql
from sqlalchemy import make_url

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WEB_SCHEMA = REPO_ROOT / 'web' / 'backend' / 'app_schema.sql'
ORCH_SCHEMA = REPO_ROOT / 'agent-orchestration' / 'sql' / 'orchestrator_schema.sql'
DEFAULT_URL = 'mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}

TEST_NOTICES = """
CREATE TABLE IF NOT EXISTS notices (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    notice_id VARCHAR(320) NOT NULL,
    UNIQUE KEY uq_notices_notice_id (notice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""


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
            if ch == '\\' and i + 1 < n:
                buf.append(script[i + 1])
                i += 2
                continue
            if ch == quote:
                if script[i + 1:i + 2] == quote:
                    buf.append(quote)
                    i += 2
                    continue
                quote = None
        elif ch in ("'", '"', '`'):
            quote = ch
            buf.append(ch)
        elif script.startswith('--', i):
            j = script.find('\n', i)
            i = n if j < 0 else j
            continue
        elif ch == ';':
            stmt = ''.join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL, help='로컬 MySQL 접속 URL(DB 이름에 e2e 또는 test)')
    args = parser.parse_args()

    url = make_url(args.url)
    database = url.database or ''
    if url.host not in LOCAL_HOSTS or not ('e2e' in database or 'test' in database):
        print(f'거부: 로컬 호스트의 e2e/test DB만 받습니다 (호스트={url.host}, DB={database!r}) — 테이블을 모두 지우기 때문입니다.')
        return 2

    conn = pymysql.connect(host=url.host, port=url.port or 3306, user=url.username, password=url.password or '',
                           charset='utf8mb4', autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(f'CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
        cur.execute(f'USE `{database}`')
        cur.execute('SELECT table_name FROM information_schema.tables WHERE table_schema = %s', (database,))
        tables = [r[0] for r in cur.fetchall()]
        cur.execute('SET FOREIGN_KEY_CHECKS=0')
        for table in tables:
            cur.execute(f'DROP TABLE IF EXISTS `{table}`')
        cur.execute('SET FOREIGN_KEY_CHECKS=1')
        for stmt in split_sql(TEST_NOTICES) + split_sql(WEB_SCHEMA.read_text(encoding='utf-8')):
            cur.execute(stmt)  # 인자 없이 실행 — 문장 속 %를 형식 문자로 보지 않는다
        for stmt in split_sql(ORCH_SCHEMA.read_text(encoding='utf-8')):
            cur.execute(stmt)
        cur.execute('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s', (database,))
        count = cur.fetchone()[0]
    finally:
        conn.close()

    print(f'준비 완료: {url.host}:{url.port}/{database} — 표 {count}개(웹 + orch_). 다음은 워커 → E2E 스크립트 순서입니다.')
    print('  워커:  cd agent-orchestration  →  SBRAIN_DB_URL=<위 URL> python -m sbrain.worker   (OPENAI_API_KEY는 agent-orchestration/.env)')
    print('  E2E :  cd web/backend  →  python scripts/e2e_worker_flow.py --url <위 URL>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
