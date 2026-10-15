# 임베딩 CPU/GPU 비교용 입력을 만든다. 공용 DB는 SELECT만 한다(쓰기 없음).
#   cd data-collection && .venv\Scripts\python.exe <이 파일> <출력.json>
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.getcwd())
from shared import embed, store_mysql  # noqa: E402
from search.app import MatchRequest, build_query  # noqa: E402

out = sys.argv[1]
conn = store_mysql.connect()
try:
    rows = embed.load_rows(conn)
finally:
    conn.close()

texts_all = [(r['notice_id'], embed.build_input(r)) for r in rows]
texts_all = [(n, t) for n, t in texts_all if t]
# 고르게 300건: notice_id 순서에서 일정 간격으로 뽑는다(늘 같은 표본)
step = max(1, len(texts_all) // 300)
sample = texts_all[::step][:300]

queries = []
with open(os.path.join('eval', 'queries.jsonl'), encoding='utf-8') as f:
    for line in f:
        q = json.loads(line)
        queries.append(build_query(MatchRequest(**q['payload'])))

json.dump({'total_notices': len(texts_all),
           'all_lengths': [len(t) for _, t in texts_all],
           'notice_ids': [n for n, _ in sample],
           'texts': [t for _, t in sample],
           'queries': queries},
          open(out, 'w', encoding='utf-8'), ensure_ascii=False)
lens = sorted(len(t) for _, t in sample)
print('전체 공고', len(texts_all), '| 표본', len(sample), '| 표본 글자수 중앙값', lens[len(lens) // 2],
      '| 검색어', len(queries), '| 검색어 글자수 중앙값', sorted(map(len, queries))[len(queries) // 2])
