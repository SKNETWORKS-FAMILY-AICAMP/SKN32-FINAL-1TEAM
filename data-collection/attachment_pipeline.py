# -*- coding: utf-8 -*-
"""기업마당 공고문 첨부를 내려받아 본문을 뽑는다.

  python attachment_pipeline.py --plan          받을 대상만 세어 본다
  python attachment_pipeline.py --limit 20      20건만 해본다
  python attachment_pipeline.py                 전량
  python attachment_pipeline.py --store         결과를 DB 에 적재

**중간에 끊겨도 다시 실행하면 이어서 한다.** 한 건 끝날 때마다 결과를 파일 끝에
덧붙이므로, 전원이 나가도 그때까지 한 것은 남는다.

내려받은 원본은 내용 해시를 파일명으로 저장한다. 같은 공고문이 여러 공고에
붙어도 파일은 한 벌만 남는다.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import doctext
import store_mysql

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'data', 'attachment_results.jsonl')
HISTORY = os.path.join(HERE, 'data', 'history')
FILES = os.path.join(HERE, 'data', 'attachments')
KEEP_HISTORY = 14         # 보관할 결과 파일 수

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/125.0 Safari/537.36')
MAX_BYTES = 30 * 1024 * 1024
EMPTY_CHARS = 30          # 이보다 짧으면 본문이 없다고 본다
GIVE_UP = 20              # 연속 실패가 이 수를 넘으면 멈춘다

EXT = {'pdf': '.pdf', 'hwp': '.hwp', 'hwpx': '.hwpx', 'docx': '.docx',
       'image': '.img', 'zip': '.zip', 'rtf': '.rtf', 'unknown': '.bin'}

# 받을 대상. 세 경우만 고른다. 자세한 근거는 collaboration/work-log.md 참조.
TARGET_SQL = """
SELECT a.id, a.url, n.notice_id, JSON_UNQUOTE(n.source_updated_at_raw) AS src_updated
FROM notice_attachments a
JOIN notices n ON n.id = a.notice_fk
LEFT JOIN attachment_texts t ON t.attachment_fk = a.id
WHERE a.active = 1 AND a.role = 'notice' AND n.source = 'bizinfo'
  AND (
        t.attachment_fk IS NULL
     OR t.last_source_updated_at <=> JSON_UNQUOTE(n.source_updated_at_raw) IS NOT TRUE
     OR (t.last_status IN ('download_fail', 'parse_error')
         AND t.last_attempted_at < %s)
  )
ORDER BY a.id
"""


def now():
    return datetime.now(timezone.utc)


def stamp(moment):
    return moment.isoformat()


def targets(connection, retry_after_hours=24):
    cutoff = now() - timedelta(hours=retry_after_hours)
    with connection.cursor() as cursor:
        cursor.execute(TARGET_SQL, (cutoff.replace(tzinfo=None),))
        return [{'attachment_fk': row[0], 'url': row[1],
                 'notice_id': row[2], 'source_updated_at': row[3]}
                for row in cursor.fetchall()]


def done_already(path=RESULTS):
    """이미 처리한 첨부 번호. 깨진 줄은 건너뛴다(전원이 나가면 마지막 줄이 잘린다)."""
    seen = set()
    if not os.path.exists(path):
        return seen
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                fk = json.loads(line).get('attachment_fk')
            except ValueError:
                continue
            if fk is not None:
                seen.add(fk)
    return seen


def append(record, path=RESULTS):
    """한 건씩 즉시 기록하고 디스크까지 밀어낸다. 이어서 하기의 근거다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def store_file(data, kind):
    """내용 해시를 파일명으로 저장한다. 같은 내용이면 한 벌만 남는다."""
    digest = hashlib.sha256(data).hexdigest()
    folder = os.path.join(FILES, digest[:2])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, digest + EXT.get(kind, '.bin'))
    if not os.path.exists(path):
        with open(path, 'wb') as f:
            f.write(data)
    return digest, path


def download(session, url, timeout=60):
    """(bytes, None) 또는 (None, 사유). 주소는 사유에 넣지 않는다."""
    import requests
    try:
        response = session.get(url, timeout=timeout, stream=True)
    except requests.RequestException as exc:
        return None, 'HTTP 요청 실패: ' + type(exc).__name__
    with response:
        if response.status_code != 200:
            return None, 'HTTP %d' % response.status_code
        ctype = (response.headers.get('Content-Type') or '').lower()
        if 'html' in ctype:
            return None, '파일 대신 HTML 이 왔다'
        body = b''
        for chunk in response.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                return None, '%dMB 상한 초과' % (MAX_BYTES // 1024 // 1024)
    if not body:
        return None, '빈 응답'
    return body, None


def classify(data):
    """(status, kind, text, error). 판별 규칙은 work-log 에 적어 둔 그대로다."""
    kind = doctext.sniff(data)
    if kind == 'image':
        return 'image_only', 'image', None, '그림 파일이다. OCR 이 필요하다'
    if kind in ('zip', 'rtf', 'unknown'):
        return 'unsupported', kind, None, '지원하지 않는 형식: %s' % kind
    try:
        text, info = doctext.extract_bytes(data)
    except doctext.UnsupportedFormat as exc:
        return 'unsupported', None if kind == 'ole' else kind, None, str(exc)[:400]
    except Exception as exc:
        return 'parse_error', None if kind == 'ole' else kind, None, \
               '%s: %s' % (type(exc).__name__, str(exc)[:300])
    kind = info.get('kind') or kind
    if info.get('image_only'):
        # 구 HWP 인데 글자가 거의 없고 그림만 들어 있는 경우.
        return 'image_only', kind, None, '그림만 있는 문서다. OCR 이 필요하다'
    text = (text or '').strip()
    if len(text) < EMPTY_CHARS:
        # 글자가 없는데 파일이 크면 보여줄 것이 그림이나 도형으로 들어 있다는 뜻이다.
        # 실측: 한컴 PDF 가 글꼴을 곡선으로 바꿔 넣으면 글자 0자에 곡선 1,194개가 나온다.
        # 눈에는 글자가 보이므로 OCR 대상이다. 진짜 빈 문서는 이 크기가 나오지 않는다.
        if len(data) >= 50 * 1024:
            return 'image_only', kind, None, \
                   '글자 층이 없는 문서다(%dKB). OCR 이 필요하다' % (len(data) // 1024)
        return 'empty_text', kind, None, '본문이 %d자뿐이다' % len(text)
    return 'ok', kind, text, None


def process(session, target, version):
    started = now()
    record = {'attachment_fk': target['attachment_fk'],
              'notice_id': target['notice_id'], 'role': 'notice', 'url': target['url'],
              'source_updated_at': target['source_updated_at'],
              'extractor_version': version, 'attempt_started_at': stamp(started)}

    data, why = download(session, target['url'])
    if data is None:
        record.update(status='download_fail', kind=None, text=None,
                      content_sha256=None, error=why, attempted_at=stamp(now()))
        return record

    status, kind, text, error = classify(data)
    digest, _ = store_file(data, kind or 'unknown')
    record.update(status=status, kind=kind, text=text, error=error,
                  # 성공일 때만 계약상의 해시를 채운다. 파일 위치는 아래 키로 남긴다.
                  content_sha256=digest if status == 'ok' else None,
                  file_sha256=digest, bytes=len(data), attempted_at=stamp(now()))
    return record


def run(limit=None, interval=1.0, plan_only=False, say=print):
    connection = store_mysql.connect()
    try:
        pending = targets(connection)
    finally:
        connection.close()

    seen = done_already()
    todo = [t for t in pending if t['attachment_fk'] not in seen]
    say('받을 대상 %d건 · 이미 처리 %d건 · 이번에 할 것 %d건'
        % (len(pending), len(pending) - len(todo), len(todo)))
    if plan_only:
        return {'targets': len(pending), 'todo': len(todo)}
    if limit:
        todo = todo[:limit]
    if not todo:
        say('받을 것이 없다.')
        return {'targets': len(pending), 'todo': 0, 'counts': {}}

    import requests
    session = requests.Session()
    session.headers['User-Agent'] = UA
    version = doctext.version()
    say('간격 %.1f초 · 예상 %d분' % (interval, round(len(todo) * interval / 60) or 1))

    counts, streak = {}, 0
    try:
        for i, target in enumerate(todo, 1):
            record = process(session, target, version)
            append(record)
            counts[record['status']] = counts.get(record['status'], 0) + 1
            streak = streak + 1 if record['status'] == 'download_fail' else 0
            if i % 25 == 0 or i == len(todo):
                say('  %d/%d  %s' % (i, len(todo),
                                     ' · '.join('%s %d' % kv for kv in sorted(counts.items()))))
            if streak >= GIVE_UP:
                say('  연속 실패 %d건 — 상대 서버 문제로 보고 멈춘다.' % streak)
                break
            if i < len(todo):
                # 서버가 밀어내면 더 물러난다.
                time.sleep(interval * 4 if record['status'] == 'download_fail' else interval)
    except KeyboardInterrupt:
        say('\n중단했다. 다시 실행하면 이어서 한다.')
    return {'targets': len(pending), 'todo': len(todo), 'counts': counts}


def store(path=RESULTS, say=print):
    """모아둔 결과를 코덱스 저장기로 DB 에 넣고, 성공하면 결과 파일을 치운다.

    **치우는 것이 중요하다.** 결과 파일은 "이번 실행이 어디까지 했나" 만 알면 되고,
    "무엇을 받아야 하나" 는 DB 가 정한다. 파일을 남겨두면 실패한 첨부가 파일에
    기록돼 있다는 이유로 영영 다시 받아지지 않는다.
    """
    if not os.path.exists(path):
        say('적재할 결과가 없다.')
        return {}
    import attachment_store
    connection = store_mysql.connect()
    counts = {}
    try:
        with io.open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    response = attachment_store.save_attachment_result(
                        connection, json.loads(line))
                    key = response['status']
                except ValueError as exc:
                    key = 'rejected'
                    say('  거부: %s' % exc)
                counts[key] = counts.get(key, 0) + 1
    finally:
        connection.close()
    say('적재 결과: ' + ' · '.join('%s %d' % kv for kv in sorted(counts.items())))

    if counts.get('rejected'):
        say('거부된 결과가 있어 파일을 그대로 둔다: %s' % path)
        return counts
    archive = os.path.join(HISTORY, 'attachment_results_%s.jsonl'
                           % now().strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(HISTORY, exist_ok=True)
    os.replace(path, archive)
    say('결과 파일을 보관함으로 옮겼다 → %s' % os.path.basename(archive))
    prune_history()
    return counts


def prune_history(keep=KEEP_HISTORY):
    """보관한 결과 파일이 무한정 쌓이지 않게 한다."""
    if not os.path.isdir(HISTORY):
        return 0
    files = sorted(f for f in os.listdir(HISTORY)
                   if f.startswith('attachment_results_'))
    removed = 0
    for name in files[:-keep] if len(files) > keep else []:
        os.remove(os.path.join(HISTORY, name))
        removed += 1
    return removed


def daily(limit=None, interval=1.0, say=print):
    """배치용 — 받고 나서 바로 적재까지 한다. (요약, 종료코드)

    받을 것이 없으면 아무 일도 하지 않는다. 매일 도는 것을 전제로,
    첫 회처럼 양이 많을 때를 대비해 `limit` 으로 상한을 둘 수 있다.
    """
    summary = run(limit=limit, interval=interval, say=say)
    if not summary.get('todo'):
        return summary, 0
    counts = store(say=say)
    summary['stored'] = counts
    # 받아온 것이 있는데 하나도 못 넣었으면 실패로 본다.
    code = 0 if counts.get('saved') or counts.get('unchanged') else 1
    return summary, code


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--limit', type=int, help='이번 실행에서 처리할 건수')
    parser.add_argument('--interval', type=float, default=1.0, help='요청 간격(초). 기본 1.0')
    parser.add_argument('--plan', action='store_true', help='받을 대상만 세어 본다')
    parser.add_argument('--store', action='store_true', help='모아둔 결과를 DB 에 적재한다')
    parser.add_argument('--daily', action='store_true', help='배치용 — 받고 바로 적재한다')
    args = parser.parse_args()

    if args.store:
        store()
        return 0
    if args.daily:
        _, code = daily(limit=args.limit, interval=args.interval)
        return code
    summary = run(limit=args.limit, interval=args.interval, plan_only=args.plan)
    if summary.get('counts'):
        print('\n결과: ' + ' · '.join('%s %d' % kv for kv in sorted(summary['counts'].items())))
        print('결과 파일 %s' % RESULTS)
        print('DB 에 넣으려면  python attachment_pipeline.py --store')
    return 0


if __name__ == '__main__':
    sys.exit(main())
