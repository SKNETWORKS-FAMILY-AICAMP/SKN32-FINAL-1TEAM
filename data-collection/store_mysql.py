"""정규화 JSON을 MySQL에 저장한다. 기본 배치/추천 파일과 독립된 CLI."""
import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent
JSON_FIELDS = {'apply_period_raw', 'source_updated_at_raw', 'issues', 'raw'}
COLUMNS = (
    'notice_id', 'source', 'source_id', 'schema_version', 'title', 'body',
    'target_text', 'target_text_status', 'target_category', 'exclude_text',
    'age_condition_raw', 'region', 'category', 'subcategory', 'organizer',
    'supervising_org', 'executing_org', 'apply_start', 'apply_end',
    'apply_period_raw', 'apply_period_type', 'recruitment_status', 'url',
    'apply_url', 'attachment_discovery_status', 'source_updated_at_raw', 'issues', 'raw',
)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def utc_datetime(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('generated_at에는 시간대가 필요합니다.')
    return stamp.astimezone(timezone.utc).replace(tzinfo=None)


def validate_payload(payload):
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        raise ValueError('정규화 schema_version=1 파일이 필요합니다.')
    stamp = utc_datetime(payload.get('generated_at', ''))
    rows = payload.get('notices')
    if not isinstance(rows, list) or not rows:
        raise ValueError('저장할 공고 배열이 비어 있거나 없습니다.')
    if payload.get('rejected'):
        raise ValueError('격리된 행이 있습니다. 정규화 오류를 검토한 후 다시 생성하세요.')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or any(key not in row for key in COLUMNS):
            raise ValueError('공통 스키마 필드가 누락되었습니다.')
        if row['schema_version'] != 1 or row['source'] not in ('kstartup', 'bizinfo'):
            raise ValueError('지원하지 않는 공고 버전 또는 출처입니다.')
        for key in COLUMNS:
            if key not in JSON_FIELDS and key != 'schema_version':
                if row[key] is not None and not isinstance(row[key], str):
                    raise ValueError('문자열 필드의 자료형 오류: ' + key)
        if not row['source_id'] or len(row['source_id']) > 255 or not row['title']:
            raise ValueError('공고 ID 또는 제목이 잘못되었습니다.')
        if row['notice_id'] != row['source'] + ':' + row['source_id']:
            raise ValueError('출처와 공고 ID가 일치하지 않습니다.')
        if row['notice_id'] in seen:
            raise ValueError('입력에 중복 공고 ID가 있습니다.')
        seen.add(row['notice_id'])
        for field in ('apply_start', 'apply_end'):
            if row[field] is not None:
                parsed = date.fromisoformat(row[field])
                if parsed.isoformat() != row[field]:
                    raise ValueError('ISO 날짜가 필요합니다.')
        if row['apply_start'] and row['apply_end'] and row['apply_start'] > row['apply_end']:
            raise ValueError('접수기간이 역전되었습니다.')
        for field in ('target_text_status', 'apply_period_type', 'recruitment_status', 'attachment_discovery_status'):
            if not row[field] or len(row[field]) > 32:
                raise ValueError('상태 필드가 잘못되었습니다: ' + field)
        if not isinstance(row['issues'], list) or not isinstance(row['raw'], dict):
            raise ValueError('issues/raw 자료형이 잘못되었습니다.')
        attachments = row.get('attachments')
        if not isinstance(attachments, list):
            raise ValueError('첨부 배열이 필요합니다.')
        for item in attachments:
            if not isinstance(item, dict):
                raise ValueError('첨부는 객체여야 합니다.')
            for key in ('role', 'url', 'status'):
                if not isinstance(item.get(key), str) or not item[key]:
                    raise ValueError('첨부 필드가 잘못되었습니다: ' + key)
            if len(item['role']) > 32 or len(item['status']) > 32:
                raise ValueError('첨부 상태 또는 역할이 너무 깁니다.')
            if item.get('name') is not None and not isinstance(item['name'], str):
                raise ValueError('첨부 파일명은 문자열이어야 합니다.')
    dumps(payload)
    return stamp


def database_name():
    name = config.get('MYSQL_DATABASE', 's_brain_poc')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name or ''):
        raise ValueError('DB명은 영문자로 시작하는 영문·숫자·밑줄 64자 이내여야 합니다.')
    return name


def ssl_context():
    """TLS 설정을 만든다. 필요 없으면 None 을 돌려준다.

    원격 서버는 `require_secure_transport=ON` 이라 평문 연결을 거부한다.
    로컬은 지금까지대로 평문으로 붙어야 하므로 **설정이 있을 때만** TLS 를 켠다.

      MYSQL_SSL_CA   CA 인증서 경로. 서버 신원까지 검증한다
      MYSQL_SSL      1/true 면 검증 없이 암호화만 한다
    """
    import ssl

    ca = config.get('MYSQL_SSL_CA')
    want = str(config.get('MYSQL_SSL', '')).strip().lower() in ('1', 'true', 'yes', 'on')
    if not ca and not want:
        return None
    if ca:
        if not Path(ca).exists():
            raise ValueError('MYSQL_SSL_CA 경로에 파일이 없습니다: ' + ca)
        context = ssl.create_default_context(cafile=ca)
        # 서버 인증서에 IP 이름이 없다. 복사 도구와 같은 판단이다.
        context.check_hostname = False
        return context
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def connect(init_db=False):
    import pymysql
    name = database_name()
    user = config.get('MYSQL_USER')
    password = config.get('MYSQL_PASSWORD')
    if not user or password is None:
        raise ValueError('MYSQL_USER와 MYSQL_PASSWORD를 .env에 설정하세요.')
    extra = {}
    context = ssl_context()
    if context is not None:
        extra['ssl'] = context
    connection = pymysql.connect(
        host=config.get('MYSQL_HOST', '127.0.0.1'), port=int(config.get('MYSQL_PORT', '3306')),
        user=user, password=password, database=None if init_db else name,
        charset='utf8mb4', autocommit=False, connect_timeout=10, read_timeout=60,
        write_timeout=60, sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION',
        **extra,
    )
    try:
        if init_db:
            with connection.cursor() as cursor:
                cursor.execute('CREATE DATABASE IF NOT EXISTS `' + name + '` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
            connection.select_db(name)
        with connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")
        return connection
    except Exception:
        connection.close()
        raise


def init_schema(connection):
    # DDL은 암묵적으로 커밋되므로 데이터 저장 트랜잭션과 별도로 실행한다.
    sql = (HERE / 'mysql_schema.sql').read_text(encoding='utf-8')
    with connection.cursor() as cursor:
        for statement in sql.split(';'):
            if statement.strip():
                cursor.execute(statement)
    connection.commit()


def attachment_key(item):
    return hashlib.sha256((item['role'] + '\0' + item['url']).encode('utf-8')).hexdigest()


def upsert_sql():
    columns = COLUMNS + ('snapshot_at', 'last_import_id')
    # 식별자만 코드 상수로 조합하고 모든 외부 값은 파라미터로 전달한다.
    mutable = columns[3:]
    sql = ('INSERT INTO notices (' + ','.join(columns) + ') VALUES ('
           + ','.join(['%s'] * len(columns)) + ') ON DUPLICATE KEY UPDATE '
           + ','.join(column + '=%s' for column in mutable))
    return sql


def store_payload(connection, payload, input_sha256):
    stamp = validate_payload(payload)
    run_id = uuid.uuid4().hex
    counts = {'processed': 0, 'skipped_older': 0, 'attachment_links': 0, 'run_id': run_id}
    locked = False
    lock_name = None
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE()')
            db = cursor.fetchone()[0]
            lock_name = 'sbrain:' + hashlib.sha256(db.encode()).hexdigest()[:48]
            cursor.execute('SELECT GET_LOCK(%s, 0)', (lock_name,))
            locked = cursor.fetchone()[0] == 1
            if not locked:
                raise ValueError('이미 MySQL 저장 작업이 실행 중입니다.')
        connection.begin()
        with connection.cursor() as cursor:
            report = {key: value for key, value in payload.items() if key != 'notices'}
            cursor.execute('INSERT INTO import_runs (run_id,input_sha256,generated_at,notice_count,report) VALUES (%s,%s,%s,%s,%s)',
                           (run_id, input_sha256, stamp, len(payload['notices']), dumps(report)))
            for row in sorted(payload['notices'], key=lambda record: record['notice_id']):
                cursor.execute('SELECT id,snapshot_at FROM notices WHERE source=%s AND source_id=%s FOR UPDATE',
                               (row['source'], row['source_id']))
                old = cursor.fetchone()
                if old and old[1] > stamp:
                    counts['skipped_older'] += 1
                    continue
                values = tuple(dumps(row[key]) if key in JSON_FIELDS else row[key] for key in COLUMNS) + (stamp, run_id)
                cursor.execute(upsert_sql(), values + values[3:])
                cursor.execute('SELECT id FROM notices WHERE source=%s AND source_id=%s', (row['source'], row['source_id']))
                notice_fk = cursor.fetchone()[0]
                # 첨부 탐색 미완료/URL 오류는 기존 다운로드 자료를 비활성화할 근거가 아니다.
                attachment_errors = any(item.get('field') in ('printFlpthNm', 'flpthNm') for item in row['issues'])
                if row['attachment_discovery_status'] == 'api_links_available' and not attachment_errors:
                    cursor.execute('UPDATE notice_attachments SET active=FALSE WHERE notice_fk=%s', (notice_fk,))
                for item in row['attachments']:
                    cursor.execute(
                        'INSERT INTO notice_attachments (notice_fk,attachment_key,role,url,name,source_status) '
                        'VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE name=%s,source_status=%s,active=TRUE',
                        (notice_fk, attachment_key(item), item['role'], item['url'], item.get('name'), item['status'],
                         item.get('name'), item['status']))
                    counts['attachment_links'] += 1
                counts['processed'] += 1
            report['storage_result'] = counts
            cursor.execute('UPDATE import_runs SET report=%s WHERE run_id=%s', (dumps(report), run_id))
        connection.commit()
        return counts
    except Exception:
        connection.rollback()
        raise
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute('SELECT RELEASE_LOCK(%s)', (lock_name,))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path, help='normalize.py 출력 JSON 경로')
    ap.add_argument('--init-db', action='store_true', help='DB 및 없는 테이블 생성 (DDL 권한 필요)')
    ap.add_argument('--check', action='store_true', help='입력만 검증. DB 연결·변경 없음')
    args = ap.parse_args()
    connection = None
    try:
        content = args.input.read_bytes()
        payload = json.loads(content.decode('utf-8-sig'))
        validate_payload(payload)
        if args.check:
            print('입력 검증 성공: %d건' % len(payload['notices']))
            return 0
        connection = connect(args.init_db)
        if args.init_db:
            init_schema(connection)
        result = store_payload(connection, payload, hashlib.sha256(content).hexdigest())
        print(dumps(result))
        return 0
    except Exception as exc:
        # DB 예외는 SQL 값/비밀번호를 포함할 수 있어 원문을 출력하지 않는다.
        if isinstance(exc, ValueError):
            print('입력/설정 오류: ' + str(exc), file=sys.stderr)
        else:
            code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else 'N/A'
            print('저장 실패: %s (code=%s). 설정·권한·입력을 확인하세요.' % (type(exc).__name__, code), file=sys.stderr)
        return 1
    finally:
        if connection:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
