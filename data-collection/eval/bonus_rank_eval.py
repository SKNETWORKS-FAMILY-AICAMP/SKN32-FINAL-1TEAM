# -*- coding: utf-8 -*-
"""가산점 순위 반영 세기 비교 — 03_bonus 3-4 (2026-10-06). OpenAI 호출·DB 쓰기 없음.

  python -X utf8 -m eval.bonus_rank_eval            결과는 reports/bonus_rank_eval_<시각>/

질문: 가산점을 순위에 얹으면(weights.bonus) 아이템과 맞는 공고가 밀려나는가?
평가 질의(eval/queries.jsonl, 정상 66개)에는 성별·인증·지역이 없어 가산점이 거의 생기지 않는다. 그래서 질의마다
**가상 신청자 속성 세 가지**(PROFILES)를 덧붙여 돌린다. 관련도 정답(qrels)은 아이템 설명 기준이라 가산점을 모른다 —
그래서 이 비교는 "가산점이 맞는 공고를 얼마나 밀어내는가"(지표가 떨어지는가)만 본다. 가산점이 좋은 순위인지는 재지 못한다.

평가 조건은 eval/match_variants.py 와 같다(기준일 2026-09-15, 9/16 전 말뭉치, 상위 10, hybrid, 서비스 match() 최종 순위).
주의: 공고 가점(notice_bonus)은 2026-10-06 기준 **지금 열린 공고**만 추출했다. 9/16 전 말뭉치 중 그 뒤 닫힌 공고는 가점 행이 없어
가산점이 null(얹지 않음)이다 — 실제 서비스보다 효과가 작게 잡힌다. 그래서 '상위 10 중 가산점 있는 공고 수'도 함께 낸다.
"""
import json
import os
import sys
from datetime import date as real_date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import evaluate  # noqa: E402
import filter_first_eval as ffe  # noqa: E402

K, DEPTH = 10, 50
WEIGHTS = (0.0, 0.1, 0.2, 0.3)
PROFILES = {
    '여성·서울': {'gender': '여성', 'region': '서울', 'certifications': []},
    '여성기업·벤처·경기': {'gender': '여성', 'region': '경기', 'certifications': ['여성기업', '벤처기업']},
    '남성·장애인기업·전남광주': {'gender': '남성', 'region': '전남광주', 'certifications': ['장애인기업', '이노비즈']},
}
KEEP = ('ineligible_k', 'p3_lo', 'ndcg_k', 'usefulk_lo', 'unjudgedk')     # 표가 너무 넓어지지 않게 핵심만
METRICS = [m for m in ffe.METRICS if m[0] in KEEP]


def moved(base, other):
    """상위 K 안에서 자리가 바뀐 공고 수(새로 들어온 것 포함)."""
    return sum(1 for i, n in enumerate(other) if i >= len(base) or base[i] != n)


def main(argv=None):
    from search import app, gate, hybrid
    from search import applicant_types as types_mod
    from shared import embed
    started = datetime.now(timezone.utc)
    app.boot()
    corpus = ffe.corpus_rows(app)
    ids = set(corpus) & app.STATE['vector_ids']
    app.STATE['rows'] = {n: r for n, r in app.STATE['rows'].items() if n in ids}
    app.STATE['collection'] = ffe.CorpusCollection(app.STATE['collection'], ids)
    app.STATE['vector_ids'] = ids
    app.STATE['bm25'] = hybrid.BM25([(n, embed.build_input(corpus[n])) for n in sorted(ids) if embed.build_input(corpus[n])])
    bonus_rows = sum(1 for n in ids if n in app.STATE.get('bonus', {}))

    queries = [q for q in common.load_queries().values() if q['kind'] == 'normal']
    as_of = real_date.fromisoformat(queries[0]['as_of_date'])
    ffe.pin_today((app, gate), as_of)
    qrels = {}
    for r in common.read_jsonl(os.path.join(HERE, 'qrels.jsonl')):
        qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']

    cache, encode = {}, app._encode

    def cached(text):
        if text not in cache:
            cache[text] = encode(text)
        return cache[text]
    app._encode = cached

    rows, types_table = app.STATE['rows'], app.STATE.get('applicant_types') or {}
    per = {(prof, w): {} for prof in PROFILES for w in WEIGHTS}
    shift = {(prof, w): [] for prof in PROFILES for w in WEIGHTS}
    with_bonus = {prof: [] for prof in PROFILES}
    for q in queries:
        rels = qrels.get(q['qid'], {})
        for prof, extra in PROFILES.items():
            p = dict(q['payload'], **extra)
            age = gate.applicant_age(p.get('applicant_type'), p.get('founded_at'), as_of)
            use_types = bool(types_table.get('active')) and p.get('applicant_type') == types_mod.PRE_FOUNDER
            base_ranked = None
            for w in WEIGHTS:
                req = app.MatchRequest(**dict(p, top=DEPTH, search='hybrid', weights={'bonus': w}))
                results = app.match(req)['results']
                ranked = [r['notice_id'] for r in results][:K]
                if w == 0.0:
                    base_ranked = ranked
                    with_bonus[prof].append(sum(1 for r in results[:K] if (r.get('bonus_score') or 0) > 0))
                checks = {n: app.eligible_with_types(n, rows[n], age, as_of, True, types_table if use_types else None)[0]
                          for n in ranked}
                per[(prof, w)][q['qid']] = ffe.query_metrics(ranked, rels, checks)
                shift[(prof, w)].append(moved(base_ranked, ranked))

    qids = [q['qid'] for q in queries]
    summary = {}
    for prof in PROFILES:
        summary[prof] = {'top10_with_bonus_mean': ffe.mean(with_bonus[prof]), 'weights': {}}
        for w in WEIGHTS:
            entry = {'moved_mean': ffe.mean(shift[(prof, w)]), 'metrics': {}}
            for key, label, better in METRICS:
                base = [per[(prof, 0.0)][qid][key] for qid in qids]
                vals = [per[(prof, w)][qid][key] for qid in qids]
                entry['metrics'][key] = {'label': label, 'mean': ffe.mean(vals),
                                         'diff': None if w == 0.0 else evaluate.paired_diff(base, vals)}
            summary[prof]['weights'][str(w)] = entry

    out_dir = os.path.join(ROOT, 'reports', 'bonus_rank_eval_' + started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out_dir)
    meta = {'run_at': started.isoformat(timespec='seconds'), 'as_of': as_of.isoformat(), 'k': K, 'depth': DEPTH,
            'corpus_notices': len(ids), 'corpus_with_bonus_row': bonus_rows, 'queries': len(qids),
            'profiles': PROFILES, 'weights': WEIGHTS, 'qrels_pairs': sum(len(v) for v in qrels.values()),
            'openai_calls': 0, 'db_writes': 0}
    json.dump({'meta': meta, 'summary': summary}, open(os.path.join(out_dir, 'results.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    lines = ['# 가산점 순위 반영 세기 비교 (%s)' % meta['run_at'], '',
             '- 기준일 %s · 말뭉치 %d건(가점 행 있음 %d건) · 질의 %d · 상위 %d · qrels %d쌍 · OpenAI 0 · DB 쓰기 0'
             % (meta['as_of'], len(ids), bonus_rows, len(qids), K, meta['qrels_pairs']), '']
    for prof in PROFILES:
        s = summary[prof]
        lines += ['## %s — 세기 0 에서 상위 10 중 가산점 있는 공고 평균 %.2f건' % (prof, s['top10_with_bonus_mean']), '',
                  '| 세기 | 자리 바뀐 수(평균) | ' + ' | '.join(m[1] for m in METRICS) + ' |',
                  '|---|---|' + '---|' * len(METRICS)]
        for w in WEIGHTS:
            e = s['weights'][str(w)]
            cells = []
            for key, _label, _b in METRICS:
                m = e['metrics'][key]
                d = m['diff']
                if m['mean'] is None:
                    cells.append('-')
                    continue
                cells.append('%.3f' % m['mean'] if d is None else
                             '%.3f (%+.3f, 95%% %+.3f~%+.3f)' % (m['mean'], d[0], d[1], d[2]))
            lines.append('| %.1f | %.2f | %s |' % (w, e['moved_mean'], ' | '.join(cells)))
        lines.append('')
    open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8').write('\n'.join(lines))
    print('\n'.join(lines))
    print('결과:', out_dir)


if __name__ == '__main__':
    main()
