# -*- coding: utf-8 -*-
"""EC2 에서 도는 벡터 색인 갱신 — MySQL 벡터로 Chroma 저장소를 만든다.

  python3 ec2_vecstore.py --plan        갱신 대상 건수만 센다
  python3 ec2_vecstore.py               증분 갱신 (매일 이것)
  python3 ec2_vecstore.py --rebuild     전체 재생성
  python3 ec2_vecstore.py --stat        색인 상태

왜 EC2 에서 도나. 검색을 EC2 가 서비스하려면 Chroma 저장소가 EC2 안에 있어야
한다. 그런데 저장소 파일을 PC 에서 전송하면 매일 수십 MB 를 보내야 하고, 보낸
것과 DB 가 어긋날 여지가 생긴다. 색인은 벡터에서 결정되는 파생물이므로
EC2 가 MySQL 을 읽어 직접 만드는 쪽이 간단하고 항상 일치한다. 실측 2,050건
1.3초 · 14.1MB 다.

이 스크립트는 임베딩 모델을 쓰지 않는다. 이미 만들어진 벡터를 MySQL 에서
읽어 옮기기만 한다. 그래서 torch·sentence-transformers 가 필요 없다.
필요한 것은 pymysql · numpy · chromadb 세 개뿐이다.

  질의를 벡터로 바꾸는 일(검색 시점)은 모델이 필요하다. 그건 이 스크립트가
  아니라 검색 앱의 몫이며 별도로 해결해야 한다.

갱신 방식. embedding_updated_at 이 색인에 기록된 마지막 시각보다 새로운
공고만 upsert 한다. 하루 수십 건이면 즉시 끝난다. 시각을 못 믿을 상황
(색인이 비었다·처음 만든다)에서는 전체를 넣는다.
"""
import argparse
import json
import os
import sys
from datetime import datetime

COLLECTION = 'notices_v1'
BATCH = 500
WATERMARK_ID = '__watermark__'

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.environ.get('VECSTORE_PATH', os.path.join(HERE, 'data', 'vecstore', 'chroma'))


_ENV_CACHE = None


def load_env(path=None):
    """이 파일 옆의 .env 를 읽는다. {키: 값}.

    EC2 에는 저장소 전체가 아니라 이 파일 하나만 둘 수 있어야 하므로
    config.py 에 의존하지 않고 스스로 읽는다.
    """
    global _ENV_CACHE
    if _ENV_CACHE is not None and path is None:
        return _ENV_CACHE
    target = path or os.path.join(HERE, '.env')
    values = {}
    try:
        with open(target, encoding='utf-8-sig') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                value = value.strip()
                # 값을 감싼 따옴표는 벗긴다. 비밀번호에 따옴표가 섞이는 실수를 막는다.
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                    value = value[1:-1]
                values[key.strip()] = value
    except OSError:
        pass
    if path is None:
        _ENV_CACHE = values
    return values


def setting(key, default=None):
    """환경변수를 먼저 보고, 없으면 .env 를 본다. 둘 다 없으면 default.

    환경변수를 우선하는 이유는 cron 이나 컨테이너에서 값 하나만 덮어쓰는 일이
    있기 때문이다. 빈 문자열은 '설정하지 않음' 과 구분해 그대로 돌려준다.
    """
    if key in os.environ:
        return os.environ[key]
    env = load_env()
    if key in env:
        return env[key]
    return default


def connect():
    """MySQL 접속. .env 또는 환경변수에서 접속 정보를 읽는다."""
    import pymysql
    get = setting

    user = get('MYSQL_USER')
    password = get('MYSQL_PASSWORD')
    # 비워두면 pymysql 이 OS 계정으로 붙으려 하고
    # "Access denied for user 'ubuntu'@'localhost'" 처럼 엉뚱한 오류가 난다.
    # 무엇이 빠졌는지 바로 알 수 있게 여기서 막는다.
    if not user or not password:
        missing = ' · '.join(n for n, v in (('MYSQL_USER', user),
                                            ('MYSQL_PASSWORD', password)) if not v)
        raise ValueError(
            '%s 가 비어 있다. %s 를 확인하세요.' % (missing, os.path.join(HERE, '.env')))

    kw = dict(host=get('MYSQL_HOST', '127.0.0.1'),
              port=int(get('MYSQL_PORT', '3306') or 3306),
              user=user,
              password=password,
              database=get('MYSQL_DATABASE', 's_brain'),
              charset='utf8mb4', autocommit=True,
              connect_timeout=10, read_timeout=60, write_timeout=60)
    context = ssl_context(get)
    if context is not None:
        kw['ssl'] = context
    return pymysql.connect(**kw)


def ssl_context(get):
    """TLS 설정. 필요 없으면 None. store_mysql.ssl_context() 와 같은 판단이다.

    원격 서버는 require_secure_transport=ON 이라 평문 연결을 거부한다.
    EC2 안에서 127.0.0.1 로 붙을 때는 평문이어도 되므로 설정이 있을 때만 켠다.
    """
    import ssl

    ca = get('MYSQL_SSL_CA')
    want = str(get('MYSQL_SSL', '') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    if not ca and not want:
        return None
    if ca:
        path = ca if os.path.isabs(ca) else os.path.join(HERE, ca)
        if not os.path.exists(path):
            raise ValueError('MYSQL_SSL_CA 경로에 파일이 없습니다: ' + path)
        context = ssl.create_default_context(cafile=path)
        # 서버 인증서에 IP 이름이 없다. store_mysql.py 와 같은 판단이다.
        context.check_hostname = False
        return context
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def open_store(create=False):
    import chromadb
    os.makedirs(STORE, exist_ok=True)
    client = chromadb.PersistentClient(path=STORE)
    try:
        return client.get_collection(COLLECTION)
    except Exception:
        if not create:
            return None
        # 코사인. 문서 벡터가 정규화돼 있어 내적과 같은 순위가 나온다.
        return client.create_collection(COLLECTION, metadata={'hnsw:space': 'cosine'})


def drop_store():
    import chromadb
    try:
        chromadb.PersistentClient(path=STORE).delete_collection(COLLECTION)
    except Exception:
        pass


def rows_since(connection, since=None):
    """갱신 대상 공고. since 가 None 이면 벡터가 있는 전부."""
    sql = ('SELECT notice_id, title, source, recruitment_status, apply_end, '
           'embedding_updated_at, embedding FROM notices WHERE embedding IS NOT NULL')
    args = ()
    if since is not None:
        sql += ' AND embedding_updated_at > %s'
        args = (since,)
    with connection.cursor() as cursor:
        cursor.execute(sql + ' ORDER BY embedding_updated_at', args)
        return cursor.fetchall()


def indexed_count(col):
    """색인된 공고 수. 기준시각 표시용 한 건은 빼고 센다."""
    if col is None:
        return 0
    return max(col.count() - 1, 0)


def watermark(col):
    """색인이 기억하는 마지막 갱신 시각. 없으면 None."""
    if col is None:
        return None
    try:
        got = col.get(ids=[WATERMARK_ID], include=['metadatas'])
        if got['ids']:
            return datetime.fromisoformat(got['metadatas'][0]['value'])
    except Exception:
        pass
    return None


def put_watermark(col, when, dim):
    """마지막 갱신 시각을 색인 안에 남긴다.

    별도 파일을 두지 않는 이유는 색인과 시각이 늘 함께 움직여야 하기 때문이다.
    색인을 지우면 시각도 같이 사라져 다음 실행이 전체를 다시 넣는다.
    검색 결과에 섞이지 않게 0 벡터로 둔다. 정규화된 질의와의 내적이 0 이다.
    """
    import numpy as np
    col.upsert(ids=[WATERMARK_ID],
               embeddings=[np.zeros(dim, dtype='float32').tolist()],
               metadatas=[{'value': when.isoformat(), 'kind': 'watermark'}])


def run(rebuild=False, plan_only=False, say=print):
    import numpy as np

    connection = connect()
    try:
        col = open_store(create=False)
        if rebuild:
            if col is not None:
                say('전체 재생성 — 기존 색인을 지운다')
                drop_store()
            col = None

        mark = None if col is None else watermark(col)
        rows = rows_since(connection, mark)
        before = indexed_count(col)

        say('색인 %d건 · 기준시각 %s · 갱신 대상 %d건'
            % (before, mark.isoformat() if mark else '(없음 · 전체)', len(rows)))
        if plan_only:
            return {'indexed': before, 'todo': len(rows), 'upserted': 0,
                    'watermark': mark.isoformat() if mark else None}
        if not rows:
            say('갱신할 것이 없다')
            return {'indexed': before, 'todo': 0, 'upserted': 0, 'missing': 0}

        if col is None:
            col = open_store(create=True)

        newest = None
        dim = 1024
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            vectors = [np.frombuffer(r[6], dtype='<f4') for r in chunk]
            dim = len(vectors[0])
            col.upsert(
                ids=[r[0] for r in chunk],
                embeddings=[v.tolist() for v in vectors],
                metadatas=[{'notice_id': r[0], 'title': (r[1] or '')[:300],
                            'source': r[2] or '', 'status': r[3] or '',
                            'apply_end': str(r[4]) if r[4] else ''} for r in chunk])
            for r in chunk:
                if r[5] is not None and (newest is None or r[5] > newest):
                    newest = r[5]
            if len(rows) > BATCH:
                say('  %d/%d' % (min(i + BATCH, len(rows)), len(rows)))

        if newest is not None:
            put_watermark(col, newest, dim)

        after = indexed_count(col)
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM notices WHERE embedding IS NOT NULL')
            total = cursor.fetchone()[0]
        say('Chroma %d건 넣음 · 색인 %d건 · DB 벡터 %d건' % (len(rows), after, total))
        # 색인에 없는 공고는 자격을 통과해도 검색 결과에 안 나온다. 조용히 빠지면
        # 제일 곤란해서 반드시 알린다. vecstore.py 와 같은 규칙이다.
        if after != total:
            say('⚠ 색인에 %d건이 없다. 검색 결과에서 빠진다.' % (total - after))
        return {'indexed': after, 'db_vectors': total, 'todo': len(rows),
                'upserted': len(rows), 'missing': total - after,
                'watermark': newest.isoformat() if newest else None}
    finally:
        connection.close()


def stat():
    col = open_store(create=False)
    mark = watermark(col)
    out = {'store': STORE, 'collection': COLLECTION,
           'indexed': indexed_count(col),
           'watermark': mark.isoformat() if mark else None}
    try:
        connection = connect()
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM notices WHERE embedding IS NOT NULL')
            out['db_vectors'] = cursor.fetchone()[0]
        connection.close()
        out['missing'] = out['db_vectors'] - out['indexed']
    except Exception as exc:
        out['db_error'] = '%s: %s' % (type(exc).__name__, str(exc)[:120])
    return out


def main():
    ap = argparse.ArgumentParser(description='MySQL 벡터 → EC2 Chroma 색인')
    ap.add_argument('--plan', action='store_true', help='갱신 대상 건수만 센다')
    ap.add_argument('--rebuild', action='store_true', help='전체 재생성')
    ap.add_argument('--stat', action='store_true', help='색인 상태')
    args = ap.parse_args()
    if args.stat:
        print(json.dumps(stat(), ensure_ascii=False, indent=1))
        return 0
    result = run(rebuild=args.rebuild, plan_only=args.plan)
    return 1 if result.get('missing') else 0


if __name__ == '__main__':
    sys.exit(main())
