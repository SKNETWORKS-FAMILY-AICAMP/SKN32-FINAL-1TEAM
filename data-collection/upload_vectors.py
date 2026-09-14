# -*- coding: utf-8 -*-
"""8단계 — 로컬 벡터를 공용 MySQL 로 올린다.

  python upload_vectors.py --plan     올릴 것이 몇 건인지만 센다
  python upload_vectors.py            올린다
  python upload_vectors.py --limit N  이번 실행 상한

왜 필요한가. 6단계가 만든 벡터는 `data/embeddings_v1.npz`, 즉 배치가 도는
PC 에만 있다. 그 상태로는 web 이 의미 검색을 할 수 없다. 여기서 공용 DB 로
옮겨 팀 전체가 같은 벡터를 쓰게 한다.

무엇을 올리나. float32 리틀엔디안 연속 바이트를 그대로 넣는다. 1건 4,096 바이트.
압축하지 않는다. 읽는 쪽은 np.frombuffer(blob, dtype='<f4') 한 줄이면 된다.

**바뀐 것만 올린다.** 판정 기준은 6단계와 같은 두 값이다.

    embedding_input_sha256   공고 내용이 바뀌었나
    embedding_fingerprint    인코딩 설정이 바뀌었나

둘 다 같으면 이미 올라간 것이므로 건너뛴다. 그래서 매일 드는 비용은
그날 새로 만들어진 수십 건뿐이다.

실패해도 괜찮다. 다음 실행이 DB 와 npz 를 대조해 빠진 것을 다시 고른다.
5·6·7단계가 쓰는 방식과 같다.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import embed
import store_mysql

HERE = os.path.dirname(os.path.abspath(__file__))
NPZ = os.path.join(HERE, 'data', 'embeddings_v1.npz')

BATCH = 100     # 한 트랜잭션에 담을 건수. 4KB × 100 = 400KB, packet 64MB 에 여유가 많다


def load_local(path=NPZ):
    """npz 에서 {notice_id: (입력해시, 바이트)} 와 설정 지문."""
    import numpy as np
    if not os.path.exists(path):
        return {}, None
    data = np.load(path, allow_pickle=False)
    vectors = data['vectors']
    if vectors.dtype != np.dtype('float32'):
        raise ValueError('벡터 dtype 이 float32 가 아니다: %s' % vectors.dtype)
    out = {}
    for nid, sha, vec in zip(data['notice_ids'], data['input_sha256'], vectors):
        # astype('<f4') 로 바이트 순서를 못 박는다. 빅엔디안 기계에서도 같은 바이트가 나온다.
        out[str(nid)] = (str(sha), vec.astype('<f4').tobytes())
    _, fingerprint = embed.load_existing(path)
    return out, fingerprint


def load_remote(connection):
    """DB 에 이미 올라간 것. {notice_id: (입력해시, 지문)}."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, embedding_input_sha256, embedding_fingerprint '
                       'FROM notices WHERE embedding IS NOT NULL')
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def plan(local, remote, fingerprint):
    """올릴 notice_id 목록. 세 경우에 올린다.

    ① DB 에 벡터가 없다          아직 안 올라갔다
    ② 입력 해시가 다르다          공고 내용이 바뀌어 벡터를 다시 만들었다
    ③ 지문이 다르다              인코딩 설정이 바뀌었다
    """
    todo = []
    for nid, (sha, _) in local.items():
        found = remote.get(nid)
        if found is None or found[0] != sha or found[1] != fingerprint:
            todo.append(nid)
    return sorted(todo)


def run(limit=None, plan_only=False, connection=None, say=print):
    local, fingerprint = load_local()
    if not local:
        say('벡터 파일이 없다. 6단계를 먼저 돌린다')
        return {'uploaded': 0, 'error': 'no_local_vectors'}
    if fingerprint != embed.fingerprint():
        say('경고: npz 지문(%s)이 현재 코드 설정(%s)과 다르다'
            % (fingerprint, embed.fingerprint()))

    own = connection is None
    if own:
        connection = store_mysql.connect()
    try:
        remote = load_remote(connection)
        todo = plan(local, remote, fingerprint)
        say('로컬 %d건 · DB %d건 · 올릴 것 %d건' % (len(local), len(remote), len(todo)))
        if plan_only:
            return {'local': len(local), 'remote': len(remote),
                    'todo': len(todo), 'uploaded': 0}
        if limit:
            todo = todo[:limit]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        dim = len(next(iter(local.values()))[1]) // 4
        done = missing = 0
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            rows = [(local[n][1], dim, local[n][0], fingerprint, now, n) for n in chunk]
            with connection.cursor() as cursor:
                # 공고가 DB 에 없으면 0행이 갱신된다. 공고를 새로 만들지 않는다.
                cursor.executemany(
                    'UPDATE notices SET embedding=%s, embedding_dim=%s, '
                    'embedding_input_sha256=%s, embedding_fingerprint=%s, '
                    'embedding_updated_at=%s WHERE notice_id=%s', rows)
                affected = cursor.rowcount
            connection.commit()
            done += affected
            missing += len(chunk) - affected
            if len(todo) > BATCH:
                say('  %d/%d' % (min(start + BATCH, len(todo)), len(todo)))
        if missing:
            say('  공고가 DB 에 없어 건너뛴 벡터 %d건' % missing)
        say('올렸다 %d건 (차원 %d · 1건 %d바이트)' % (done, dim, dim * 4))
        return {'local': len(local), 'remote': len(remote), 'todo': len(todo),
                'uploaded': done, 'skipped_no_notice': missing, 'dim': dim}
    finally:
        if own:
            connection.close()


def main():
    ap = argparse.ArgumentParser(description='로컬 벡터를 공용 MySQL 로 올린다')
    ap.add_argument('--plan', action='store_true', help='올릴 건수만 센다')
    ap.add_argument('--limit', type=int, help='이번 실행 상한')
    args = ap.parse_args()
    result = run(limit=args.limit, plan_only=args.plan)
    return 1 if result.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
