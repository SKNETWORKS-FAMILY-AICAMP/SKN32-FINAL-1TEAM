# -*- coding: utf-8 -*-
"""공고 의미 검색 — 내 PC 에서 시험해 보는 용도.

  python search_local.py "청년 창업 자금"
  python search_local.py "청년 창업 자금" --top 5 --hide-expired
  python search_local.py                          대화형. 빈 줄이면 종료
  python search_local.py "..." --json             API 가 돌려줄 형태로 출력
  python search_local.py "..." --engine chroma    로컬 Chroma 색인 사용

무엇을 위한 파일인가. EC2 에 검색 API 를 올리기 전에 **응답에 어떤 필드가
필요한지 · 필터가 쓸 만한지**를 직접 만져보고 정하려는 것이다. 여기서 정해진
모양을 그대로 API 로 옮긴다.

두 가지 경로를 고를 수 있다.

  mysql   (기본)  EC2 MySQL 의 notices.embedding 을 읽어 numpy 로 계산한다.
                  EC2 의 실제 데이터를 쓴다. 서버에 아무것도 안 띄워도 된다.
  chroma          이 PC 의 data/vecstore/chroma 를 쓴다. 오프라인으로 된다.

둘의 결과는 같다. 실측으로 상위 5건의 순위와 점수가 소수점 4자리까지 같았다.
"""
import argparse
import json
import sys
import time

FIELDS = ('notice_id', 'title', 'organizer', 'supervising_org', 'executing_org',
          'apply_start', 'apply_end', 'apply_period_type', 'recruitment_status',
          'category', 'region', 'url')


class Index:
    """모델과 벡터를 한 번만 올려두고 여러 질의에 재사용한다.

    API 도 같은 구조여야 한다. 질의마다 모델을 올리면 매번 8초가 걸린다.
    """

    def __init__(self, engine='mysql', say=print):
        self.engine = engine
        self.say = say
        self.ids = []
        self.rows = {}
        self.matrix = None
        self.collection = None
        self._load()

    def _load(self):
        import numpy as np
        started = time.time()

        if self.engine == 'mysql':
            import store_mysql
            connection = store_mysql.connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        'SELECT ' + ','.join(FIELDS) + ', embedding FROM notices '
                        'WHERE embedding IS NOT NULL')
                    fetched = cursor.fetchall()
            finally:
                connection.close()
            self.ids = [r[0] for r in fetched]
            self.rows = {r[0]: dict(zip(FIELDS, r[:len(FIELDS)])) for r in fetched}
            self.matrix = np.vstack(
                [np.frombuffer(r[-1], dtype='<f4') for r in fetched])
            self.say('EC2 MySQL 에서 벡터 %d건 · %.0fms'
                     % (len(self.ids), (time.time() - started) * 1000))
        else:
            import vecstore
            self.collection = vecstore.open_chroma()
            self.say('로컬 Chroma 색인 %d건 · %.0fms'
                     % (self.collection.count(), (time.time() - started) * 1000))
            # 제목·기간 등은 색인에 없다. 보여줄 값은 MySQL 에서 채운다.
            self._fill_rows()

    def _fill_rows(self):
        import store_mysql
        connection = store_mysql.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM notices')
                for row in cursor.fetchall():
                    self.rows[row[0]] = dict(zip(FIELDS, row))
        finally:
            connection.close()

    def warmup(self):
        """첫 질의가 느린 문제를 미리 털어낸다.

        실측으로 EC2 첫 질의가 20.8초, 그 뒤가 0.3초였다. 워밍업을 안 하면
        첫 사용자가 그 20초를 기다린다. API 에도 반드시 넣어야 한다.
        """
        started = time.time()
        self.search('워밍업', top=1)
        self.say('워밍업 %.1f초' % (time.time() - started))

    def _expired(self, notice_id, today):
        """마감일이 이미 지났나.

        `recruitment_status` 로 거르면 안 된다. 기업마당이 그 값을 주지 않아
        1,700건이 'unknown' 이고, open 만 남기면 전체의 83%가 사라진다.

        `apply_end` 가 NULL 인 것은 마감이 없다는 뜻이 아니라 **고정 종료일이
        없다**는 뜻이다(예산 소진까지·상시·수시). 아직 받고 있을 가능성이
        높으므로 남긴다.
        """
        end = self.rows.get(notice_id, {}).get('apply_end')
        return end is not None and str(end) < today

    def search(self, query, top=3, hide_expired=False):
        import numpy as np
        import vecstore
        from datetime import date

        today = date.today().isoformat()

        t0 = time.time()
        qv = np.asarray(vecstore.embed_query(query), dtype='<f4')
        encode_ms = (time.time() - t0) * 1000

        t0 = time.time()
        if self.engine == 'mysql':
            scores = self.matrix @ qv
            hits = []
            for i in np.argsort(-scores):
                nid = self.ids[i]
                if hide_expired and self._expired(nid, today):
                    continue
                hits.append((nid, float(scores[i])))
                if len(hits) >= top:
                    break
        else:
            # 색인 쪽에서는 날짜 비교를 걸지 않는다. 넉넉히 받아 여기서 거른다.
            want = top * 6 if hide_expired else top
            found = self.collection.query(query_embeddings=[qv.tolist()],
                                          n_results=min(want, self.collection.count()))
            hits = []
            for nid, dist in zip(found['ids'][0], found['distances'][0]):
                if nid == '__watermark__':
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
                'results': results}


def show(payload):
    print('\n"%s"  ·  인코딩 %.0fms + 검색 %.2fms  ·  %d건'
          % (payload['query'], payload['encode_ms'],
             payload['search_ms'], payload['count']))
    if not payload['results']:
        print('  (없음)')
        return
    for rank, row in enumerate(payload['results'], 1):
        org = row.get('organizer') or row.get('supervising_org') or '-'
        period = '%s ~ %s' % (row.get('apply_start') or '?', row.get('apply_end') or '?')
        print('  %d. %.4f  %s' % (rank, row['score'], (row.get('title') or '')[:58]))
        print('       %s · %s · %s' % (org[:26], period, row.get('recruitment_status')))


def main():
    ap = argparse.ArgumentParser(description='공고 의미 검색 시험')
    ap.add_argument('query', nargs='?', help='검색어. 없으면 대화형')
    ap.add_argument('--top', type=int, default=3)
    ap.add_argument('--hide-expired', action='store_true',
                    help='마감일이 지난 공고를 뺀다')
    ap.add_argument('--engine', choices=('mysql', 'chroma'), default='mysql')
    ap.add_argument('--json', action='store_true', help='API 응답 형태로 출력')
    ap.add_argument('--no-warmup', action='store_true')
    args = ap.parse_args()

    index = Index(engine=args.engine)
    if not args.no_warmup:
        index.warmup()

    if args.query:
        payload = index.search(args.query, top=args.top, hide_expired=args.hide_expired)
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
        show(index.search(query, top=args.top, hide_expired=args.hide_expired))
    return 0


if __name__ == '__main__':
    sys.exit(main())
