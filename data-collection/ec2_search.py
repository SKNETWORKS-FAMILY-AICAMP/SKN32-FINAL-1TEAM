# -*- coding: utf-8 -*-
"""EC2 안에서 공고를 검색한다. 벡터 DB(Chroma) 에서 가져온다.

  .venv/bin/python ec2_search.py                       대화형. 빈 줄이면 종료
  .venv/bin/python ec2_search.py "청년 창업 자금"
  .venv/bin/python ec2_search.py "..." --top 5 --hide-expired
  .venv/bin/python ec2_search.py "..." --json          API 응답 형태로 출력

경로는 이렇다.

  검색어 → BGE-M3 로 벡터 → Chroma 색인에서 유사한 것 찾기 → MySQL 에서 상세

**모델을 한 번만 올리고 재사용한다.** 실측으로 로딩 40초 · 첫 질의 20초 ·
그 뒤 0.3초다. 질의마다 새로 올리면 매번 40초가 걸린다. API 도 같은 구조여야 한다.

ec2_vecstore.py 의 connect() · open_store() 를 그대로 쓴다. 접속 정보와 색인
경로가 한 곳에만 적혀 있게 하려는 것이다.
"""
import argparse
import json
import sys
import time
from datetime import date

import ec2_vecstore

FIELDS = ('notice_id', 'title', 'organizer', 'supervising_org', 'executing_org',
          'apply_start', 'apply_end', 'apply_period_type', 'recruitment_status',
          'category', 'region', 'url')

WATERMARK = ec2_vecstore.WATERMARK_ID


class Search:
    def __init__(self, say=print):
        self.say = say
        self.rows = {}
        self.collection = None
        self.model = None
        self._open()

    def _open(self):
        started = time.time()
        self.collection = ec2_vecstore.open_store(create=False)
        if self.collection is None:
            raise SystemExit('Chroma 색인이 없다. 먼저 ec2_vecstore.py 를 돌린다.')
        count = ec2_vecstore.indexed_count(self.collection)

        connection = ec2_vecstore.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM notices')
                for row in cursor.fetchall():
                    self.rows[row[0]] = dict(zip(FIELDS, row))
        finally:
            connection.close()
        self.say('Chroma 색인 %d건 · 공고 정보 %d건 · %.0fms'
                 % (count, len(self.rows), (time.time() - started) * 1000))

        started = time.time()
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer('BAAI/bge-m3')
        self.model.max_seq_length = 512
        self.say('모델 로딩 %.1f초' % (time.time() - started))

    def warmup(self):
        started = time.time()
        self.search('워밍업', top=1)
        self.say('워밍업 %.1f초 — 이제부터 빠릅니다' % (time.time() - started))

    def _expired(self, notice_id, today):
        """마감일이 지났나.

        recruitment_status 로 거르지 않는다. 기업마당이 그 값을 주지 않아
        1,700건이 'unknown' 이고, open 만 남기면 전체의 83%가 사라진다.
        apply_end 가 NULL 인 것은 고정 종료일이 없다는 뜻(예산 소진까지·상시)
        이라 아직 받고 있을 수 있다. 그래서 남긴다.
        """
        end = self.rows.get(notice_id, {}).get('apply_end')
        return end is not None and str(end) < today

    def search(self, query, top=3, hide_expired=False):
        today = date.today().isoformat()

        t0 = time.time()
        vectors = self.model.encode([query], normalize_embeddings=True,
                                    show_progress_bar=False)
        encode_ms = (time.time() - t0) * 1000

        t0 = time.time()
        # 마감 지난 것을 뺄 때를 대비해 넉넉히 받아 온 뒤 여기서 거른다.
        want = top * 6 if hide_expired else top + 1
        found = self.collection.query(
            query_embeddings=[vectors[0].tolist()],
            n_results=min(want, self.collection.count()))
        hits = []
        for nid, dist in zip(found['ids'][0], found['distances'][0]):
            if nid == WATERMARK:
                continue
            if hide_expired and self._expired(nid, today):
                continue
            hits.append((nid, 1.0 - dist))
            if len(hits) >= top:
                break
        search_ms = (time.time() - t0) * 1000

        results = []
        for nid, score in hits:
            row = dict(self.rows.get(nid, {'notice_id': nid}))
            for key in ('apply_start', 'apply_end'):
                if row.get(key) is not None:
                    row[key] = str(row[key])
            row['score'] = round(score, 4)
            results.append(row)
        return {'query': query, 'count': len(results),
                'encode_ms': round(encode_ms, 1), 'search_ms': round(search_ms, 2),
                'source': 'chroma', 'results': results}


def show(payload):
    print('\n"%s"  ·  인코딩 %.0fms + 벡터DB %.1fms  ·  %d건'
          % (payload['query'], payload['encode_ms'],
             payload['search_ms'], payload['count']))
    if not payload['results']:
        print('  (없음)')
        return
    for rank, row in enumerate(payload['results'], 1):
        org = row.get('organizer') or row.get('supervising_org') or '-'
        period = '%s ~ %s' % (row.get('apply_start') or '?',
                              row.get('apply_end') or '?')
        print('  %d. %.4f  %s' % (rank, row['score'], (row.get('title') or '')[:56]))
        print('       %s · %s' % (org[:24], period))
        if row.get('url'):
            print('       %s' % row['url'][:76])


def main():
    ap = argparse.ArgumentParser(description='EC2 벡터DB 공고 검색')
    ap.add_argument('query', nargs='?', help='검색어. 없으면 대화형')
    ap.add_argument('--top', type=int, default=3)
    ap.add_argument('--hide-expired', action='store_true', help='마감 지난 공고 제외')
    ap.add_argument('--json', action='store_true', help='API 응답 형태로 출력')
    ap.add_argument('--no-warmup', action='store_true')
    args = ap.parse_args()

    engine = Search()
    if not args.no_warmup:
        engine.warmup()

    if args.query:
        payload = engine.search(args.query, top=args.top,
                                hide_expired=args.hide_expired)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            show(payload)
        return 0

    print('\n검색어를 입력하세요. 빈 줄이면 종료합니다.')
    while True:
        try:
            query = input('\n> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            break
        show(engine.search(query, top=args.top, hide_expired=args.hide_expired))
    return 0


if __name__ == '__main__':
    sys.exit(main())
