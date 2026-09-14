# -*- coding: utf-8 -*-
"""EC2 MySQL 백업 — mysqldump 없이 파이썬으로.

  python backup_db.py                     기본 4개 테이블 (약 40MB)
  python backup_db.py --include-files     첨부 파일 테이블도 (약 660MB)
  python backup_db.py --out path.sql

기본값에서 `attachment_files` 를 빼는 이유. 631MB 인데 **다시 만들 수 있는
데이터**다. 로컬 `data/attachments/` 에 같은 파일 1,646개가 있고
`upload_attachments.py` 로 언제든 올릴 수 있다. 내려받는 데 시간이 걸리는 것을
매번 감수할 이유가 없다. 로컬 파일이 사라진 상황까지 대비하려면
`--include-files` 를 쓴다.

출력은 표준 SQL 이다. 어떤 MySQL 클라이언트로도 복원된다.

  mysql -h <host> -u <user> -p s_brain < backup.sql
"""
import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

import store_mysql

CORE_TABLES = ('import_runs', 'notices', 'notice_attachments', 'attachment_texts')
HEAVY_TABLES = ('attachment_files',)
CHUNK = 200


def literal(connection, value):
    """값 하나를 SQL 리터럴로. pymysql 의 이스케이프를 그대로 쓴다."""
    if value is None:
        return 'NULL'
    if isinstance(value, (bytes, bytearray)):
        # BLOB 은 16진 리터럴로 넣는다. 따옴표 이스케이프 사고가 없다.
        return "0x" + bytes(value).hex() if value else "''"
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return "'%s'" % value.isoformat(sep=' ')
    if isinstance(value, date):
        # date 는 isoformat 에 sep 인자를 받지 않는다. datetime 보다 뒤에서 검사한다.
        return "'%s'" % value.isoformat()
    if isinstance(value, timedelta):
        return "'%s'" % value
    return connection.escape(str(value))


def dump_table(connection, name, out, say):
    with connection.cursor() as cursor:
        cursor.execute('SHOW CREATE TABLE `%s`' % name)
        ddl = cursor.fetchone()[1]
        cursor.execute('SELECT COUNT(*) FROM `%s`' % name)
        total = cursor.fetchone()[0]

    out.write('\n--\n-- %s (%d행)\n--\n' % (name, total))
    out.write('DROP TABLE IF EXISTS `%s`;\n' % name)
    out.write(ddl + ';\n')
    if not total:
        return 0

    # 한 행씩 서버에서 받아온다. 631MB 테이블을 통째로 메모리에 올리지 않는다.
    import pymysql.cursors
    written = 0
    started = time.time()
    with connection.cursor(pymysql.cursors.SSCursor) as cursor:
        cursor.execute('SELECT * FROM `%s`' % name)
        columns = [d[0] for d in cursor.description]
        head = 'INSERT INTO `%s` (%s) VALUES\n' % (
            name, ','.join('`%s`' % c for c in columns))
        batch = []
        for row in cursor:
            batch.append('(' + ','.join(literal(connection, v) for v in row) + ')')
            if len(batch) >= CHUNK:
                out.write(head + ',\n'.join(batch) + ';\n')
                written += len(batch)
                batch = []
                say('    %d/%d' % (written, total))
        if batch:
            out.write(head + ',\n'.join(batch) + ';\n')
            written += len(batch)
    say('  %s %d행 · %.1f초' % (name, written, time.time() - started))
    return written


def main():
    ap = argparse.ArgumentParser(description='EC2 MySQL 백업')
    ap.add_argument('--out', help='출력 파일. 기본은 data/backup_<시각>.sql')
    ap.add_argument('--include-files', action='store_true',
                    help='attachment_files 도 포함(약 660MB)')
    args = ap.parse_args()

    tables = CORE_TABLES + (HEAVY_TABLES if args.include_files else ())
    path = args.out or os.path.join(
        'data', 'backup_%s.sql' % datetime.now().strftime('%Y%m%dT%H%M%S'))
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

    connection = store_mysql.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE(), @@hostname, VERSION()')
            dbname, host, version = cursor.fetchone()
        print('백업 대상 %s @ %s (MySQL %s)' % (dbname, host, version))
        print('테이블 %s' % ', '.join(tables))
        if not args.include_files:
            print('  attachment_files 제외 — data/attachments/ 로 재생성 가능')
        print('출력 %s\n' % path)

        with open(path, 'w', encoding='utf-8', newline='\n') as out:
            out.write('-- s_brain 백업 · %s UTC\n'
                      % datetime.utcnow().isoformat(timespec='seconds'))
            out.write('-- 서버 %s · MySQL %s\n' % (host, version))
            out.write('SET NAMES utf8mb4;\n')
            out.write('SET FOREIGN_KEY_CHECKS = 0;\n')
            out.write('SET UNIQUE_CHECKS = 0;\n')
            for name in tables:
                dump_table(connection, name, out, say=print)
            out.write('\nSET FOREIGN_KEY_CHECKS = 1;\n')
            out.write('SET UNIQUE_CHECKS = 1;\n')
    finally:
        connection.close()

    size = os.path.getsize(path)
    print('\n완료 %s · %.1f MB' % (path, size / 1048576))
    print('복원:  mysql -h <host> -u <user> -p %s < %s' % (dbname, path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
