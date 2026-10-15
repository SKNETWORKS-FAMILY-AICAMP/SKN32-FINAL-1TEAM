# -*- coding: utf-8 -*-
"""EC2 MySQL 백업 — mysqldump 없이 파이썬으로.

  python -m collect.backup_db                     공고·판정 테이블 8개 (2026-10 기준 약 95MB)
  python -m collect.backup_db --include-files     첨부 원본 파일 테이블도 (약 800MB 더)
  python -m collect.backup_db --out path.sql

공용 DB 를 읽기만 한다. 우리 배치가 쓰는 테이블만 담는다 — 같은 DB 의 다른 팀 테이블
(웹·조율, 회원·로그인 토큰 포함)은 넣지 않는다.

판정 테이블(자격요건·신청자 유형·업종·가점)은 AI 를 불러 만든 결과라 다시 만들려면 비용이 든다.
그래서 기본 백업에 넣는다. 모든 테이블을 한 시점 기준(읽기 전용 일관 스냅샷)으로 읽는다.

기본값에서 `attachment_files` 를 빼는 이유. 수백 MB 인데 **다시 만들 수 있는
데이터**다. 로컬 `data/attachments/` 에 같은 파일 1,646개가 있고
`upload_attachments.py` 로 언제든 올릴 수 있다. 내려받는 데 시간이 걸리는 것을
매번 감수할 이유가 없다. 로컬 파일이 사라진 상황까지 대비하려면
`--include-files` 를 쓴다.

출력은 표준 SQL 이다. 어떤 MySQL 클라이언트로도 복원된다.

  mysql -h <host> -u <user> -p s_brain < backup.sql
"""
import argparse
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from shared import store_mysql

CORE_TABLES = ('import_runs', 'notices', 'notice_attachments', 'attachment_texts',
               # 배치 10·13·14단계가 쓰는 AI 판정 결과 (2026-10-07 추가)
               'notice_conditions', 'notice_applicant_types', 'notice_industries', 'notice_bonus')
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


# 되살릴 수 있는 테이블 — AI 판정 결과만. 공고·첨부 표는 되살리지 않는다(그사이 매일 배치가 넣은 새 공고를 지우지 않게)
RESTORABLE = ('notice_conditions', 'notice_applicant_types', 'notice_industries', 'notice_bonus')
_SECTION_RE = re.compile(r'^-- ([a-z_]+) \((\d+)행\)$')


def _scan(path, tables, on_statement=None):
    """백업 파일을 줄 단위로 읽어(1.7GB 를 메모리에 올리지 않는다) 고른 테이블 구역의 문장을 센다.
    on_statement 를 주면 문장마다 (테이블, 문장)으로 부른다. 돌려주는 값: {테이블: {'rows', 'statements'}}"""
    found = {}
    current, buf = None, []
    with open(path, encoding='utf-8') as f:
        for line in f:
            stripped = line.rstrip('\n')
            head = _SECTION_RE.match(stripped)
            if head:
                current = head.group(1) if head.group(1) in tables else None
                if current:
                    found[current] = {'rows': int(head.group(2)), 'statements': 0}
                buf = []
                continue
            if current is None or (not buf and (stripped == '--' or not stripped)):
                continue
            if not buf and stripped.startswith(('SET FOREIGN_KEY_CHECKS', 'SET UNIQUE_CHECKS')):
                current = None                 # 파일 끝의 설정 줄 — 구역이 끝났다
                continue
            buf.append(line)
            if stripped.endswith(';'):
                statement = ''.join(buf).strip()[:-1]
                buf = []
                found[current]['statements'] += 1
                if on_statement is not None:
                    on_statement(current, statement)
    return found


def restore(path, tables, apply=False, connection=None, say=print):
    """백업 파일에서 고른 AI 판정 테이블만 되살린다(2026-10-07 결정 0013 되돌리기용).

    파일은 테이블마다 `-- 이름 (N행)` 머리 → DROP TABLE → CREATE TABLE → INSERT 다. 먼저 파일 전체를 훑어 고른 테이블이
    모두 있는지 확인하고(없으면 아무것도 하지 않는다), apply=True 일 때만 그 구역의 문장을 실행한다.
    DROP·CREATE 는 MySQL 에서 되돌릴 수 없으므로 실행은 사용자 승인 뒤에만 한다.
    """
    bad = [t for t in tables if t not in RESTORABLE]
    if bad or not tables:
        raise SystemExit('되살릴 수 있는 테이블은 %s 뿐이다 (받은 것: %s)' % (', '.join(RESTORABLE), ', '.join(tables)))
    found = _scan(path, tables)
    missing = [t for t in tables if t not in found or not found[t]['statements']]
    if missing:
        raise SystemExit('백업 파일에 없는 테이블: %s (아무것도 하지 않았다)' % ', '.join(missing))
    if apply:
        cursor = connection.cursor()
        cursor.execute('SET NAMES utf8mb4')
        cursor.execute('SET FOREIGN_KEY_CHECKS = 0')
        try:
            _scan(path, tables, on_statement=lambda _t, sql: cursor.execute(sql))
            connection.commit()
        finally:
            cursor.execute('SET FOREIGN_KEY_CHECKS = 1')
    for name in tables:
        info = found[name]
        say('  %s — 백업 %d행 · 문장 %d개%s' % (name, info['rows'], info['statements'], ' 실행함' if apply else ''))
    return found


def main():
    ap = argparse.ArgumentParser(description='EC2 MySQL 백업')
    ap.add_argument('--out', help='출력 파일. 기본은 data/backup_<시각>.sql')
    ap.add_argument('--include-files', action='store_true',
                    help='attachment_files 도 포함(약 800MB 더)')
    ap.add_argument('--restore', metavar='FILE',
                    help='백업 파일에서 --tables 의 AI 판정 테이블만 되살린다(기본은 계획만, --apply 로 실제 실행)')
    ap.add_argument('--tables', help='되살릴 테이블(쉼표로). %s 중에서' % ', '.join(RESTORABLE))
    ap.add_argument('--apply', action='store_true', help='--restore 를 실제로 실행한다(공용 DB 를 바꾼다)')
    args = ap.parse_args()

    if args.restore:
        tables = [t.strip() for t in (args.tables or '').split(',') if t.strip()]
        print('되살리기 %s — %s%s' % (args.restore, ', '.join(tables) or '(없음)', '' if args.apply else ' (계획만)'))
        connection = store_mysql.connect() if args.apply else None
        try:
            restore(args.restore, tables, apply=args.apply, connection=connection)
        finally:
            if connection is not None:
                connection.close()
        if not args.apply:
            print('실제로 되살리려면 --apply 를 붙인다(공용 DB 를 바꾼다 — 사용자 승인 뒤에만)')
        return 0

    tables = CORE_TABLES + (HEAVY_TABLES if args.include_files else ())
    path = args.out or os.path.join(
        'data', 'backup_%s.sql' % datetime.now().strftime('%Y%m%dT%H%M%S'))
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

    connection = store_mysql.connect()
    try:
        with connection.cursor() as cursor:
            # 테이블마다 다른 시각의 상태가 섞이지 않게 한 시점 기준으로 읽는다(쓰지 않음)
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            cursor.execute('SELECT DATABASE(), @@hostname, VERSION()')
            dbname, host, version = cursor.fetchone()
        print('백업 대상 %s @ %s (MySQL %s)' % (dbname, host, version))
        print('테이블 %s' % ', '.join(tables))
        if not args.include_files:
            print('  attachment_files 제외 — data/attachments/ 로 재생성 가능')
        print('출력 %s\n' % path)

        with open(path, 'w', encoding='utf-8', newline='\n') as out:
            out.write('-- s_brain 백업 · %s UTC\n'
                      % datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds'))
            out.write('-- 서버 %s · MySQL %s\n' % (host, version))
            out.write('SET NAMES utf8mb4;\n')
            out.write('SET FOREIGN_KEY_CHECKS = 0;\n')
            out.write('SET UNIQUE_CHECKS = 0;\n')
            for name in tables:
                dump_table(connection, name, out, say=print)
            out.write('\nSET FOREIGN_KEY_CHECKS = 1;\n')
            out.write('SET UNIQUE_CHECKS = 1;\n')
        connection.rollback()   # 읽기 전용 스냅샷을 닫는다
    finally:
        connection.close()

    size = os.path.getsize(path)
    print('\n완료 %s · %.1f MB' % (path, size / 1048576))
    print('복원:  mysql -h <host> -u <user> -p %s < %s' % (dbname, path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
