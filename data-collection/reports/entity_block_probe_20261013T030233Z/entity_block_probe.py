# -*- coding: utf-8 -*-
"""개인사업자·법인 '강한 불가' 걸러내기 1단계 — 지금 서비스 그대로 평가 질의를 개인사업자·법인으로 돌려,
상위 3·10·20건에 공고 본문상 그 유형이 확실히 불가인 공고가 몇 번 뜨는지 센다. 코드는 그대로, 공용 DB SELECT 만.

'확실한 불가' = LLM 판정 not_allowed · strong · varies 아님(예비창업자 정형 필터와 같은 기준).
안전장치 가정 = 예비창업자의 발췌 밖 확인(unread_pre_founder)과 같은 방식으로, 판정에 쓰지 않은 원문에 그 유형 말이
더 많이 나오면 '확인 필요'로 낮춘다. 말은 좁게(개인사업자·개인기업 / 법인사업자·법인기업 …)와 넓게(개인사업 / 법인) 두 가지로 센다.
"""
import collections
import json
import os
import re
import sys
from datetime import date

ROOT = r'C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection'
sys.path.insert(0, ROOT)
os.chdir(ROOT)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'entity_block_probe.json')

from search import app, applicant_types as types_mod  # noqa: E402
from shared import store_mysql  # noqa: E402

KEY = {'개인사업자': 'sole_proprietor', '법인': 'corporation'}
WORDS = {'sole_proprietor': {'좁게': ('개인사업자', '개인기업'), '넓게': ('개인사업',)},
         'corporation': {'좁게': ('법인사업자', '법인기업', '법인만', '법인에한'), '넓게': ('법인',)}}


def flat(t):
    return re.sub(r'\s+', '', t or '')


def unread(item, words):
    """판정 발췌 밖 원문에 words 가 더 많이 나오나(unread_pre_founder 와 같은 횟수 비교)."""
    texts = [item.get('target_text') or '', item.get('body') or ''] + list(item.get('attachments') or [])
    chunks = [flat(c) for c in (item.get('document') or '').split('\n\n')]
    full = sum(flat(t).count(w) for t in texts for w in words)
    read = sum(c.count(w) for c in chunks for w in words)
    return full > read


app.boot()
print('boot_errors', list(app.STATE['boot_errors']))
table = app.STATE.get('applicant_types') or {}
notices = table.get('notices') or {}
conn = store_mysql.connect()
try:
    documents = types_mod.current_documents(conn)
finally:
    conn.close()

rows = app.STATE['rows']
blocked = {}           # key -> {nid: {'narrow': bool, 'broad': bool, 'evidence': ...}}
for key in KEY.values():
    blocked[key] = {}
    for nid, info in notices.items():
        c = info[key]
        if c['status'] == 'not_allowed' and c['strength'] == 'strong' and not info['varies'] and nid in rows:
            item = documents.get(nid)
            same = item is not None and item.get('document_sha256') == info.get('document_sha256')
            blocked[key][nid] = {
                'title': rows[nid].get('title', '')[:50], 'evidence': (c['evidence'] or '')[:120],
                'unverified': not same,
                'unread_narrow': bool(same and unread(item, WORDS[key]['좁게'])),
                'unread_broad': bool(same and unread(item, WORDS[key]['넓게'])),
            }
for key, d in blocked.items():
    print('%s 강한 불가(서버가 들고 있는 공고) %d건 · 원문 확인 못 함 %d · 발췌 밖 언급(좁게) %d · (넓게) %d'
          % (key, len(d), sum(v['unverified'] for v in d.values()), sum(v['unread_narrow'] for v in d.values()),
             sum(v['unread_broad'] for v in d.values())))

queries = [json.loads(l) for l in open('eval/queries.jsonl', encoding='utf-8')]
queries = [q for q in queries if q.get('kind') == 'normal']
stats = {t: collections.Counter() for t in KEY}
seen = {t: collections.Counter() for t in KEY}
examples = []
for q in queries:
    for t, key in KEY.items():
        payload = dict(q['payload'], applicant_type=t)
        if not payload.get('founded_at'):
            payload['founded_at'] = '2022-01-01'
        res = app.match(app.MatchRequest(**dict(payload, top=20)))['results'][:20]
        ids = [r['notice_id'] for r in res]
        for k in (3, 10, 20):
            hit = [n for n in ids[:k] if n in blocked[key]]
            safe = [n for n in hit if not (blocked[key][n]['unverified'] or blocked[key][n]['unread_broad'])]
            stats[t]['질의_상위%d에_있음' % k] += bool(hit)
            stats[t]['칸_상위%d' % k] += len(hit)
            stats[t]['칸_상위%d_안전장치뒤' % k] += len(safe)
        for i, n in enumerate(ids, 1):
            if n in blocked[key]:
                seen[t][n] += 1
                examples.append({'qid': q['qid'], 'type': t, 'rank': i, 'notice_id': n, 'title': blocked[key][n]['title'],
                                 'evidence': blocked[key][n]['evidence']})

print('\n질의 %d개 × (개인사업자, 법인) · 상위 20 · 기준일 %s(지금 열린 공고)' % (len(queries), date.today()))
for t in KEY:
    print(t, dict(stats[t]))
    for n, c in seen[t].most_common(8):
        print('   %s %d회 | %s' % (n[-6:], c, blocked[KEY[t]][n]['title']))
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'queries': len(queries), 'blocked': blocked, 'stats': {t: dict(s) for t, s in stats.items()},
               'seen': {t: dict(s) for t, s in seen.items()}, 'examples': examples}, f, ensure_ascii=False, indent=1)
print('저장', OUT)
