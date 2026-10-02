# 실패 질의 분석: filter_first_eval 과 같은 조건으로 상위 50, 알려진 정답(2)의 위치·제외 이유를 본다. DB 읽기만.
import json
import os
import sys
from collections import Counter
from datetime import date as real_date

ROOT = r'C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection'
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from eval import common, filter_first_eval as ffe  # noqa
from search import app, gate, hybrid  # noqa
from shared import embed  # noqa

OUT = sys.argv[1]
DEPTH = 50

app.boot()
corpus = ffe.corpus_rows(app)
ids = set(corpus) & app.STATE['vector_ids']
app.STATE['rows'] = {n: r for n, r in app.STATE['rows'].items() if n in ids}
app.STATE['collection'] = ffe.CorpusCollection(app.STATE['collection'], ids)
app.STATE['vector_ids'] = ids
app.STATE['bm25'] = hybrid.BM25([(n, embed.build_input(corpus[n])) for n in sorted(ids) if embed.build_input(corpus[n])])
queries = [q for q in common.load_queries().values() if q['kind'] == 'normal']
as_of = real_date.fromisoformat(queries[0]['as_of_date'])
ffe.pin_today((app, gate), as_of)
qrels = {}
for r in common.read_jsonl(common.QRELS):
    qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
rows = app.STATE['rows']
types_table = app.STATE.get('applicant_types') or {}
from search import applicant_types as types_mod  # noqa

out = []
where = Counter()
for q in queries:
    p = q['payload']
    age = gate.applicant_age(p.get('applicant_type'), p.get('founded_at'), as_of)
    use_types = bool(types_table.get('active')) and p.get('applicant_type') == types_mod.PRE_FOUNDER
    res = {}
    for mode in ('hybrid', 'dense'):
        r = app.match(app.MatchRequest(**dict(p, top=DEPTH, search=mode)))
        res[mode] = r['results']
    query_text = app.build_query(app.MatchRequest(**dict(p, top=10)))
    allowed = {n for n in rows if app.eligible_with_types(n, rows[n], age, as_of, True, types_table if use_types else None)[0]}
    bm = [n for n, _ in app.STATE['bm25'].search(query_text, top=500, allowed=allowed)]
    hy = [x['notice_id'] for x in res['hybrid']]
    de = [x['notice_id'] for x in res['dense']]
    rels = qrels.get(q['qid'], {})
    good = []
    for nid, rel in rels.items():
        if rel != 2:
            continue
        if nid not in rows:
            status = 'corpus_out'
        else:
            keep, why, _ = app.eligible_with_types(nid, rows[nid], age, as_of, True, types_table if use_types else None)
            if not keep:
                status = 'filtered:' + '/'.join(why)
            elif nid in hy[:10]:
                status = 'top10'
            elif nid in hy:
                status = 'rank11_50'
            else:
                status = 'beyond50'
        where[status.split(':')[0] if not status.startswith('filtered') else 'filtered'] += 1
        good.append({'notice_id': nid, 'title': (rows.get(nid) or {}).get('title', '')[:50], 'status': status,
                     'hy': hy.index(nid) + 1 if nid in hy else None, 'de': de.index(nid) + 1 if nid in de else None,
                     'bm': bm.index(nid) + 1 if nid in bm else None})
    out.append({'qid': q['qid'], 'category': q['category'], 'idea': p['idea'], 'applicant_type': p.get('applicant_type'),
                'query_text': query_text, 'passed': len(allowed),
                'top': [{'rank': i + 1, 'notice_id': x['notice_id'], 'title': x.get('title', '')[:60],
                         'rel': rels.get(x['notice_id']), 'dense_rank': x.get('dense_rank'), 'bm25_rank': x.get('bm25_rank')}
                        for i, x in enumerate(res['hybrid'][:15])],
                'known_good': good,
                'good_total': sum(1 for v in rels.values() if v == 2)})
json.dump({'as_of': str(as_of), 'where_known_good': dict(where), 'queries': out},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('알려진 정답(2) 위치:', dict(where))
