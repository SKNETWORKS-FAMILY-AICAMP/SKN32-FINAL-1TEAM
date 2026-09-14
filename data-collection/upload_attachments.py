# -*- coding: utf-8 -*-
"""9단계 — 첨부 원본 파일을 공용 MySQL 로 올린다.

  python upload_attachments.py --plan       올릴 것이 몇 건·몇 MB 인지만 센다
  python upload_attachments.py --limit 30   30개만 (시험용)
  python upload_attachments.py              전부
  python upload_attachments.py --verify     올라간 것의 바이트를 대조한다

왜 필요한가. 첨부 원본은 배치가 도는 PC 에만 있었다. 본문 텍스트는
`attachment_texts` 에, 원본 URL 은 `notice_attachments` 에 이미 있지만 팀원이
파일 자체를 개발에 쓰려면(HWP 파서 개선·이미지 PDF OCR·표 추출 등) 파일이 필요하다.
원본 사이트에서 각자 다시 받으면 1,646건에 한 시간이 걸리고 상대 서버에도 부담이다.

키는 `content_sha256`. 배치 PC 의 파일명이 그 값이라 대조가 단순하고,
`attachment_texts.content_sha256` 과 그대로 조인된다.

**이미 올라간 것은 건너뛴다.** 해시가 곧 내용이므로 같은 해시가 DB 에 있으면
같은 파일이다. 그래서 중간에 끊겨도 다시 실행하면 이어서 올린다. 620MB 를
한 번에 보내다 끊기는 상황을 전제로 만들었다.

읽는 쪽은 이렇게 쓴다.

    SELECT f.ext, f.bytes
      FROM notices n
      JOIN notice_attachments na ON na.notice_fk = n.id
      JOIN attachment_texts   at ON at.attachment_fk = na.id
      JOIN attachment_files    f ON f.content_sha256 = at.content_sha256
     WHERE n.notice_id = %s
"""
import argparse
import hashlib
import os
import sys

import store_mysql

HERE = os.path.dirname(os.path.abspath(__file__))
ATTACH = os.path.join(HERE, 'data', 'attachments')

COMMIT_BYTES = 8 * 1024 * 1024   # 이만큼 모이면 커밋한다. 끊겼을 때 잃는 양의 상한


def local_files(root=ATTACH):
    """{content_sha256: (경로, 확장자, 바이트수)}. 파일명이 해시다."""
    out = {}
    for base, _, names in os.walk(root):
        for name in names:
            sha, ext = os.path.splitext(name)
            if len(sha) != 64:
                continue        # 해시 이름이 아닌 파일은 다루지 않는다
            path = os.path.join(base, name)
            out[sha.lower()] = (path, ext.lstrip('.').lower(), os.path.getsize(path))
    return out


def remote_hashes(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT content_sha256 FROM attachment_files')
        return {row[0] for row in cursor.fetchall()}


def run(limit=None, plan_only=False, connection=None, say=print):
    local = local_files()
    if not local:
        say('올릴 파일이 없다. data/attachments 가 비어 있다')
        return {'uploaded': 0, 'error': 'no_local_files'}

    own = connection is None
    if own:
        connection = store_mysql.connect()
    try:
        remote = remote_hashes(connection)
        todo = sorted(set(local) - remote)
        todo_bytes = sum(local[s][2] for s in todo)
        say('로컬 %d개 %.1fMB · DB %d개 · 올릴 것 %d개 %.1fMB'
            % (len(local), sum(v[2] for v in local.values()) / 1048576,
               len(remote), len(todo), todo_bytes / 1048576))
        if plan_only:
            return {'local': len(local), 'remote': len(remote),
                    'todo': len(todo), 'todo_mb': round(todo_bytes / 1048576, 1),
                    'uploaded': 0}
        if limit:
            todo = todo[:limit]

        done = sent = pending = mismatched = 0
        for sha in todo:
            path, ext, size = local[sha]
            with open(path, 'rb') as f:
                blob = f.read()
            # 읽은 바이트가 정말 그 해시인지 확인한다. 파일이 상했으면 올리지 않는다.
            if hashlib.sha256(blob).hexdigest() != sha:
                mismatched += 1
                continue
            with connection.cursor() as cursor:
                # 같은 해시가 이미 있으면 내용이 같다는 뜻이므로 덮어쓸 필요가 없다
                cursor.execute(
                    'INSERT INTO attachment_files '
                    '(content_sha256, byte_size, ext, bytes) VALUES (%s, %s, %s, %s) '
                    'ON DUPLICATE KEY UPDATE content_sha256 = content_sha256',
                    (sha, len(blob), ext, blob))
            done += 1
            sent += len(blob)
            pending += len(blob)
            if pending >= COMMIT_BYTES:
                connection.commit()
                pending = 0
                say('  %d/%d · %.0fMB' % (done, len(todo), sent / 1048576))
        connection.commit()
        if mismatched:
            say('  ⚠ 해시가 파일명과 다른 파일 %d개는 올리지 않았다' % mismatched)
        say('올렸다 %d개 %.1fMB' % (done, sent / 1048576))
        return {'local': len(local), 'remote': len(remote), 'todo': len(todo),
                'uploaded': done, 'sent_mb': round(sent / 1048576, 1),
                'hash_mismatch': mismatched}
    finally:
        if own:
            connection.close()


def verify(sample=None, say=print):
    """DB 에 올라간 바이트를 다시 해시해 대조한다."""
    local = local_files()
    connection = store_mysql.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*), SUM(byte_size), '
                           'SUM(byte_size <> LENGTH(bytes)) FROM attachment_files')
            count, total, wrong_len = cursor.fetchone()
            say('DB %d개 %.1fMB · byte_size 불일치 %d개'
                % (count, (total or 0) / 1048576, wrong_len or 0))

            cursor.execute('SELECT content_sha256, bytes FROM attachment_files'
                           + (' ORDER BY RAND() LIMIT %d' % sample if sample else ''))
            ok = bad = 0
            for sha, blob in cursor.fetchall():
                if hashlib.sha256(bytes(blob)).hexdigest() == sha:
                    ok += 1
                else:
                    bad += 1
            say('해시 재계산: 일치 %d개 · 불일치 %d개' % (ok, bad))
        missing = sorted(set(local) - remote_hashes(connection))
        if missing:
            say('아직 안 올라간 파일 %d개' % len(missing))
        return {'in_db': count, 'verified': ok, 'corrupt': bad,
                'wrong_length': wrong_len or 0, 'missing': len(missing)}
    finally:
        connection.close()


def main():
    ap = argparse.ArgumentParser(description='첨부 원본 파일을 공용 MySQL 로 올린다')
    ap.add_argument('--plan', action='store_true', help='올릴 건수·용량만 센다')
    ap.add_argument('--limit', type=int, help='이번 실행에서 올릴 개수 상한')
    ap.add_argument('--verify', action='store_true', help='올라간 바이트를 해시로 대조한다')
    ap.add_argument('--sample', type=int, help='--verify 에서 무작위 N개만 본다')
    args = ap.parse_args()
    if args.verify:
        result = verify(sample=args.sample)
        return 1 if result['corrupt'] or result['wrong_length'] else 0
    result = run(limit=args.limit, plan_only=args.plan)
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
