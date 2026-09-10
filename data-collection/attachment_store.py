"""첨부 추출 시도 저장. 전용 연결에서 한 시도당 트랜잭션을 소유한다."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import store_mysql

STATUSES = {'ok', 'image_only', 'unsupported', 'download_fail', 'parse_error', 'empty_text'}
KINDS = {'pdf', 'hwp', 'hwpx', 'docx', 'image', 'zip', 'rtf', 'unknown'}
SUCCESS_KINDS = {'pdf', 'hwp', 'hwpx', 'docx'}
LAST_COLUMNS = (
    'last_status', 'last_kind', 'last_attempt_started_at', 'last_attempted_at',
    'last_source_updated_at', 'last_extractor_version', 'last_error', 'last_result_sha256',
)
SUCCESS_COLUMNS = (
    'extracted_text', 'text_chars', 'text_kind', 'extracted_at',
    'text_source_updated_at', 'text_extractor_version', 'content_sha256',
)


def safe_error(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('error는 문자열 또는 NULL이어야 합니다.')
    # 요청 URL의 쿼리·사용자정보를 저장하지 않는다.
    value = re.sub(r'https?://\S+', '[URL omitted]', value, flags=re.I)
    value = re.sub(r'(?i)(password|servicekey|crtfcKey|api[_-]?key)\s*[:=]\s*[^\s,;]+', r'\1=[redacted]', value)
    for key in ('MYSQL_PASSWORD', 'KSTARTUP_KEY', 'BIZINFO_KEY', 'OPENAI_API_KEY'):
        secret = store_mysql.config.get(key)
        if secret:
            value = value.replace(secret, '[redacted]')
    return value[:4000]


def validate_result(result):
    if not isinstance(result, dict):
        raise ValueError('시도 결과는 객체여야 합니다.')
    required = {'status', 'kind', 'text', 'attempt_started_at', 'attempted_at',
                'source_updated_at', 'extractor_version', 'content_sha256', 'error'}
    if not required.issubset(result):
        raise ValueError('필수 시도 필드 누락: ' + ','.join(sorted(required - result.keys())))
    row = {key: result[key] for key in required}
    fk = result.get('attachment_fk')
    if fk is not None and (type(fk) is not int or not 0 < fk < 2**64):
        raise ValueError('attachment_fk는 양의 정수여야 합니다.')
    identity = ('notice_id', 'role', 'url')
    supplied = [result.get(key) is not None for key in identity]
    if any(supplied) and not all(supplied):
        raise ValueError('대체 식별자는 notice_id, role, url을 모두 전달하세요.')
    if fk is None and not all(supplied):
        raise ValueError('attachment_fk 또는 대체 식별자가 필요합니다.')
    for key in identity:
        if result.get(key) is not None and (not isinstance(result[key], str) or not result[key]):
            raise ValueError('대체 식별자가 잘못되었습니다.')
        row[key] = result.get(key)
    row['attachment_fk'] = fk
    if (not isinstance(row['status'], str) or row['status'] not in STATUSES
            or (row['kind'] is not None and (not isinstance(row['kind'], str) or row['kind'] not in KINDS))):
        raise ValueError('허용되지 않은 status 또는 kind입니다.')
    try:
        started = store_mysql.utc_datetime(row['attempt_started_at'])
        finished = store_mysql.utc_datetime(row['attempted_at'])
    except (ValueError, AttributeError, TypeError):
        raise ValueError('시도 시각은 시간대가 있는 ISO 날짜 문자열이어야 합니다.') from None
    if finished < started:
        raise ValueError('완료 시각이 시작 시각보다 이릅니다.')
    row['attempt_started_at'], row['attempted_at'] = started, finished
    version = row['extractor_version']
    if not isinstance(version, str) or not version.strip() or len(version) > 64:
        raise ValueError('extractor_version은 1~64자 문자열이어야 합니다.')
    if row['source_updated_at'] is not None and not isinstance(row['source_updated_at'], str):
        raise ValueError('source_updated_at은 원문 문자열 또는 NULL이어야 합니다.')
    sha = row['content_sha256']
    if sha is not None:
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', sha):
            raise ValueError('content_sha256 형식 오류')
        row['content_sha256'] = sha.lower()
    if row['status'] == 'ok':
        if row['kind'] not in SUCCESS_KINDS or not isinstance(row['text'], str) or not row['text'].strip():
            raise ValueError('ok는 지원 형식과 비어 있지 않은 본문이 필요합니다.')
        if row['content_sha256'] is None or row['error'] is not None:
            raise ValueError('ok는 파일 해시가 필요하며 error는 NULL이어야 합니다.')
    elif row['text'] is not None:
        raise ValueError('실패 결과의 text는 NULL이어야 합니다.')
    row['error'] = safe_error(row['error'])
    return row


def init_schema(connection):
    """기존 DB에 첨부 추출 테이블만 생성한다. 기존 테이블 ALTER 없음."""
    schema = Path(__file__).with_name('mysql_schema.sql').read_text(encoding='utf-8')
    start = schema.index('CREATE TABLE IF NOT EXISTS attachment_texts (')
    statement = schema[start:].split(';', 1)[0]
    with connection.cursor() as cursor:
        cursor.execute(statement)
    connection.commit()


def _resolve(cursor, row):
    if row['attachment_fk'] is not None:
        cursor.execute('SELECT notice_fk FROM notice_attachments WHERE id=%s', (row['attachment_fk'],))
    else:
        key = store_mysql.attachment_key({'role': row['role'], 'url': row['url']})
        cursor.execute('SELECT a.notice_fk,a.id FROM notice_attachments a JOIN notices n ON n.id=a.notice_fk '
                       'WHERE n.notice_id=%s AND a.attachment_key=%s', (row['notice_id'], key))
    found = cursor.fetchone()
    if not found:
        raise ValueError('연결할 첨부가 없습니다. 공고·첨부 목록을 먼저 저장하세요.')
    notice_fk = found[0]
    attachment_fk = row['attachment_fk'] if row['attachment_fk'] is not None else found[1]
    # 공고 저장기와 동일하게 부모 공고 → 첨부 순으로 잠가 교착 가능성을 줄인다.
    cursor.execute('SELECT notice_id,source_updated_at_raw FROM notices WHERE id=%s FOR UPDATE', (notice_fk,))
    parent = cursor.fetchone()
    cursor.execute('SELECT role,url FROM notice_attachments WHERE id=%s FOR UPDATE', (attachment_fk,))
    attachment = cursor.fetchone()
    if not parent or not attachment:
        raise ValueError('공고 또는 첨부 연결이 사라졌습니다.')
    if row['notice_id'] is not None and (parent[0], attachment[0], attachment[1]) != (row['notice_id'], row['role'], row['url']):
        raise ValueError('attachment_fk와 대체 식별자가 일치하지 않습니다.')
    source_version = json.loads(parent[1])
    return attachment_fk, source_version


def save_attachment_result(connection, result):
    """전용 연결 필요. 한 시도를 commit/rollback하며 저장 또는 skip 사유를 반환한다."""
    row = validate_result(result)
    try:
        connection.begin()
        with connection.cursor() as cursor:
            fk, current_version = _resolve(cursor, row)
            if current_version != row['source_updated_at']:
                connection.rollback()
                return {'status': 'skipped_source_changed', 'attachment_fk': fk}
            digest_data = {key: value for key, value in row.items() if key not in ('attachment_fk', 'notice_id', 'role', 'url')}
            digest = hashlib.sha256(json.dumps(digest_data, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
            cursor.execute('SELECT last_attempt_started_at,last_attempted_at,last_result_sha256 FROM attachment_texts WHERE attachment_fk=%s FOR UPDATE', (fk,))
            old = cursor.fetchone()
            order = (row['attempt_started_at'], row['attempted_at'])
            if old and order < old[:2]:
                connection.rollback()
                return {'status': 'skipped_older_attempt', 'attachment_fk': fk}
            if old and order == old[:2]:
                if digest != old[2]:
                    raise ValueError('같은 시각의 시도에 서로 다른 결과가 있습니다.')
                connection.rollback()
                return {'status': 'unchanged', 'attachment_fk': fk}
            columns = LAST_COLUMNS
            values = (row['status'], row['kind'], *order, row['source_updated_at'], row['extractor_version'], row['error'], digest)
            if row['status'] == 'ok':
                columns += SUCCESS_COLUMNS
                values += (row['text'], len(row['text']), row['kind'], row['attempted_at'],
                           row['source_updated_at'], row['extractor_version'], row['content_sha256'])
            sql = ('INSERT INTO attachment_texts (attachment_fk,' + ','.join(columns) + ') VALUES ('
                   + ','.join(['%s'] * (len(values) + 1)) + ') ON DUPLICATE KEY UPDATE '
                   + ','.join(column + '=%s' for column in columns))
            cursor.execute(sql, (fk,) + values + values)
        connection.commit()
        return {'status': 'saved', 'attachment_fk': fk, 'extraction_status': row['status']}
    except Exception:
        connection.rollback()
        raise


def load_results(path):
    content = Path(path).read_text(encoding='utf-8-sig')
    if Path(path).suffix.lower() == '.jsonl':
        return [json.loads(line) for line in content.splitlines() if line.strip()]
    payload = json.loads(content)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get('results'), list):
        return payload['results']
    return [payload]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, nargs='?', help='한 시도 / 배열 / results 배열 JSON 또는 JSONL')
    parser.add_argument('--init-schema', action='store_true')
    parser.add_argument('--check', action='store_true', help='입력 필드만 검사, DB 미접속')
    args = parser.parse_args()
    if not args.input and not args.init_schema:
        parser.error('입력 파일 또는 --init-schema가 필요합니다.')
    connection = None
    try:
        results = load_results(args.input) if args.input else []
        for item in results:
            validate_result(item)
        if args.check:
            print('검증 성공: %d건 (FK/원본 버전 일치는 실제 저장 시 확인)' % len(results))
            return 0
        connection = store_mysql.connect()
        if args.init_schema:
            init_schema(connection)
        counts = {}
        for item in results:
            response = save_attachment_result(connection, item)
            counts[response['status']] = counts.get(response['status'], 0) + 1
        print(json.dumps({'processed': sum(counts.values()), 'results': counts}, ensure_ascii=False))
        return 0
    except Exception as exc:
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        message = str(exc) if isinstance(exc, ValueError) else '%s code=%s' % (type(exc).__name__, code)
        print('저장 중단(이전 시도 커밋은 유지): ' + safe_error(message), file=sys.stderr)
        return 1
    finally:
        if connection:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
