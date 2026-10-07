# -*- coding: utf-8 -*-
"""벡터 DB(Chroma) 방식과 메모리 벡터 방식을 **같은 벡터**로 나란히 비교한다 (2026-10-07).

  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.vector_db_compare

공고 서버는 2026-10-07부터 공용 DB 의 공고 벡터를 메모리에 올려 의미 검색을 직접 계산한다(search/memvec.py).
바꾸기 전 방식(Chroma)과 결과가 같은지 보려고, **같은 공용 DB 벡터로 임시 Chroma 를 새로 만들어** 둘을 같은 질의로 돌린다.
이 PC 의 옛 Chroma 색인(10/2 기준)을 쓰면 방식 차이가 아니라 공고 수 차이가 섞이기 때문이다.

  예전 방식   임시 Chroma(코사인, 시스템 임시 폴더 — 끝나면 지운다)
  새 방식     search.memvec.MemoryCollection (app.boot() 가 올린 것)

잰다
  1. 의미 검색만 — 정형 필터 통과 공고 안에서 상위 50(app._dense_within): 상위 10 겹침 · 상위 10 순서 같음 · 1위 같음
  2. 서비스 추천 전체 — app.match(기본 설정, 상위 10): 상위 3 같음 · 상위 10 같음 · 다른 질의의 공고 차이
  3. 시간 — 의미 검색 한 번 · match() 한 번 평균(ms)
질의: eval/queries.jsonl 60개. 공용 DB 는 SELECT 만, 유료 호출 없음.
결과: reports/vector_db_compare_<UTC 시각>Z/ (summary.md · results.json)
"""
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

QUERIES = os.path.join(HERE, 'queries.jsonl')
PASS_TOP3 = 0.90          # 서비스 추천 상위 3건이 같은 질의 비율이 이 이상이면 통과(조정 가능)


def load_queries(path=QUERIES):
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def build_chroma(col, tmpdir, batch=500):
    """메모리 묶음과 같은 벡터로 임시 Chroma 를 만든다(코사인 — 예전 서버 색인과 같은 설정)."""
    import chromadb
    client = chromadb.PersistentClient(path=tmpdir)
    chroma = client.create_collection('compare_v1', metadata={'hnsw:space': 'cosine'})
    for i in range(0, len(col.ids), batch):
        chroma.add(ids=col.ids[i:i + batch], embeddings=[v.tolist() for v in col.vectors[i:i + batch]])
    return client, chroma


def passed_ids(app, req, today):
    """match() 1단계와 같은 정형 필터 통과 공고(검색 전)."""
    from search import applicant_types as types_mod
    from search import gate
    age = gate.applicant_age(req.applicant_type, req.founded_at, today)
    table = app.STATE.get('applicant_types') or {}
    use_types = bool(req.use_applicant_types and req.structured_filter and table.get('active')
                     and req.applicant_type == types_mod.PRE_FOUNDER)
    out = []
    for nid, row in app.STATE['rows'].items():
        keep, _why, _change = app.eligible_with_types(nid, row, age, today, req.hide_expired,
                                                      table if use_types else None)
        if keep:
            out.append(nid)
    return out


def ms(fn):
    t0 = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - t0) * 1000


def run(say=print):
    from search import app, hybrid
    say('공고 서버와 같은 방식으로 올린다(app.boot) …')
    app.boot()
    mem = app.STATE['collection']
    if mem is None:
        raise SystemExit('메모리 벡터를 올리지 못했다: %s' % app.STATE['boot_errors'].get('vector_db'))
    import chromadb
    tmpdir = tempfile.mkdtemp(prefix='vector_db_compare_')
    try:
        say('임시 Chroma 만들기(%d건) …' % mem.count())
        client, chroma = build_chroma(mem, tmpdir)
        queries = load_queries()
        today = date.today()
        per = []
        for q in queries:
            req = app.MatchRequest(**q['payload'])
            qv = app._encode(app.build_query(req))
            ids = passed_ids(app, req, today)
            d_mem, t_dm = ms(lambda: app._dense_within(mem, qv, ids, hybrid.DEPTH))
            d_chr, t_dc = ms(lambda: app._dense_within(chroma, qv, ids, hybrid.DEPTH))
            top_mem = [n for n, _ in d_mem[0][:10]]
            top_chr = [n for n, _ in d_chr[0][:10]]
            app.STATE['collection'] = mem
            m_mem, t_mm = ms(lambda: app.match(req))
            app.STATE['collection'] = chroma
            m_chr, t_mc = ms(lambda: app.match(req))
            app.STATE['collection'] = mem
            r_mem = [r['notice_id'] for r in m_mem['results']]
            r_chr = [r['notice_id'] for r in m_chr['results']]
            per.append({
                'qid': q['qid'], 'kind': q.get('kind'), 'idea': q['payload'].get('idea', '')[:60],
                'filtered': len(ids),
                'dense_paths': [d_mem[1], d_chr[1]],
                'dense_top10_overlap': len(set(top_mem) & set(top_chr)) / max(1, len(top_mem)),
                'dense_top10_same_order': top_mem == top_chr,
                'dense_top1_same': top_mem[:1] == top_chr[:1],
                'match_top3_same': r_mem[:3] == r_chr[:3],
                'match_top10_same': r_mem == r_chr,
                'match_only_memory': [n for n in r_mem if n not in r_chr],
                'match_only_chroma': [n for n in r_chr if n not in r_mem],
                'ms': {'dense_memory': t_dm, 'dense_chroma': t_dc, 'match_memory': t_mm, 'match_chroma': t_mc},
            })
        del chroma, client
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    n = len(per)

    def avg(key):
        return sum(p['ms'][key] for p in per) / n
    summary = {
        'made_at': datetime.now(timezone.utc).isoformat(), 'today': today.isoformat(),
        'queries': n, 'vectors': mem.count(), 'vectors_info': app.STATE.get('vectors_info'),
        'chromadb': chromadb.__version__, 'loaded_store_at': str(app.STATE.get('loaded_store_at')),
        'dense_top10_overlap': sum(p['dense_top10_overlap'] for p in per) / n,
        'dense_top10_same_order': sum(p['dense_top10_same_order'] for p in per),
        'dense_top1_same': sum(p['dense_top1_same'] for p in per),
        'match_top3_same': sum(p['match_top3_same'] for p in per),
        'match_top10_same': sum(p['match_top10_same'] for p in per),
        'ms_avg': {k: round(avg(k), 2) for k in ('dense_memory', 'dense_chroma', 'match_memory', 'match_chroma')},
        'pass_rule': 'match_top3_same / queries >= %.2f' % PASS_TOP3,
    }
    summary['passed'] = summary['match_top3_same'] / n >= PASS_TOP3

    out = os.path.join(ROOT, 'reports', 'vector_db_compare_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out)
    with open(os.path.join(out, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'queries': per}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write(summary_md(summary, per))
    say(summary_md(summary, per))
    say('→ ' + out)
    return summary, out


def summary_md(s, per):
    n = s['queries']
    lines = [
        '# 벡터 DB(Chroma) vs 메모리 벡터 — 같은 벡터로 비교',
        '',
        '- 만든 시각 %s · 기준일 %s · 질의 %d개(`eval/queries.jsonl`) · 공고 벡터 %d건(공용 DB) · chromadb %s'
        % (s['made_at'], s['today'], n, s['vectors'], s['chromadb']),
        '- 예전 방식: 같은 벡터로 새로 만든 임시 Chroma(코사인). 새 방식: `search/memvec.py`(전부 비교)',
        '- 공용 DB SELECT 만, 유료 호출 없음',
        '',
        '| 지표 | 결과 |',
        '|---|---|',
        '| 의미 검색 상위 10 겹침(평균) | %.1f%% |' % (100 * s['dense_top10_overlap']),
        '| 의미 검색 상위 10 순서가 완전히 같은 질의 | %d / %d |' % (s['dense_top10_same_order'], n),
        '| 의미 검색 1위가 같은 질의 | %d / %d |' % (s['dense_top1_same'], n),
        '| **서비스 추천 상위 3이 같은 질의** | **%d / %d (%.1f%%)** |' % (s['match_top3_same'], n, 100 * s['match_top3_same'] / n),
        '| 서비스 추천 상위 10이 같은 질의 | %d / %d |' % (s['match_top10_same'], n),
        '| 의미 검색 한 번 평균 | 메모리 %.2fms · Chroma %.2fms |' % (s['ms_avg']['dense_memory'], s['ms_avg']['dense_chroma']),
        '| 추천 한 번 평균(match) | 메모리 %.1fms · Chroma %.1fms |' % (s['ms_avg']['match_memory'], s['ms_avg']['match_chroma']),
        '',
        '판정: %s (기준 %s)' % ('통과' if s['passed'] else '**미달**', s['pass_rule']),
        '',
        '## 서비스 추천 상위 3이 다른 질의',
        '',
    ]
    diff = [p for p in per if not p['match_top3_same']]
    if not diff:
        lines.append('없음')
    for p in diff:
        lines.append('- %s (%s) %s — 메모리에만 %s · Chroma 에만 %s'
                     % (p['qid'], p['kind'], p['idea'], p['match_only_memory'] or '-', p['match_only_chroma'] or '-'))
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    summary, _ = run()
    sys.exit(0 if summary['passed'] else 2)
