# -*- coding: utf-8 -*-
"""벡터만(처음) vs 검색 먼저(9/22) vs 정형 필터 먼저(2026-09-28) — 같은 평가 질의로 수치 비교. OpenAI 호출 없음.

  python -X utf8 eval/filter_first_eval.py            DB·Chroma 읽기만. 결과는 reports/filter_first_eval_<시각>/

2026-09-28 사용자 요청: 매칭 순서를 바꿨는데 더 나은지 숫자로 보고 싶다.
기획서 대조 [PLAN_ALIGNMENT_20260928.md](../docs/PLAN_ALIGNMENT_20260928.md) 불일치 A.

세 방식
  vector_only   처음 방식 재현 — 지금 search/app.py 에서 정형 필터·마감 제외·단어 검색·규칙(지역·시군구·집단·
                신청자 유형·업종)을 모두 끄고 부른다. 공고 벡터와 질의 벡터의 유사도 순서 그대로 상위 K.
                검색 방식(hybrid·dense)과 상관없이 늘 같은 결과라 두 표에 같은 값으로 들어간다.
                (2026-09-28 사용자 요청: "처음에 벡터 DB 유사도만 쓰던 방식과 지금 방식을 숫자로 비교")
  legacy        커밋 LEGACY_COMMIT 의 search/app.py 를 그대로 불러온다(검색 상위 → 마감 제외 → 모자라면 더 깊이)
  filter_first  지금 search/app.py (정형 필터 → 통과 공고 안에서만 검색)
  legacy·filter_first 는 같은 Chroma·같은 질의 벡터·같은 BM25·같은 규칙(rank_rules)·같은 기준일을 쓴다.

말뭉치
  판정(qrels)은 2026-09-15 에 만든 풀에서 나왔다. 그 뒤에 수집된 공고는 판정이 있을 수 없으므로,
  CORPUS_BEFORE 전에 들어온 공고만 두 방식에 똑같이 보여 준다(Chroma 는 CorpusCollection 으로 감싼다).

지표 (정상 질의, 상위 K=10, 두 검색 방식 hybrid·dense 각각)
  신청 불가@10   상위 10 중 확실히 신청할 수 없는 공고 비율(마감·업력·유형). 판정 불필요.
                 서비스와 같은 기준(app.eligible_with_types = gate.prefilter + 예비창업자면 공고 본문 신청자 유형 판정)으로
                 세 방식을 똑같이 채점한다(2026-09-28 — API 업력 칸만 보면 본문으로 살린 공고를 불가로 잘못 셌다)
  P@3(2)         상위 3 중 topic_rel=2 비율(evaluate.py 주 지표). 미판정은 0 으로 센 하한과 2 로 센 상한을 같이 낸다
  nDCG@10        판정된 공고만으로 계산(evaluate.ndcg, condensed)
  쓸모@3·@10     "내용이 맞고(topic_rel=2) + 신청 가능"한 공고 수. 하한(미판정=아님)·상한(미판정=맞음)
  미판정@3·@10   판정이 없는 칸 비율. 높으면 그 숫자를 덜 믿는다

topic_rel 은 "지역·업력·마감은 무시하고 내용만" 본 판정이다(eval/README). 그래서 신청 가능 여부는 따로 곱한다.
"""
import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
from datetime import date as real_date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import evaluate  # noqa: E402

LEGACY_COMMIT = '35358be'            # 필터 먼저로 바꾸기 직전 커밋(2026-09-22)
CORPUS_BEFORE = '2026-09-16'         # 이 날짜 전에 수집된 공고만(판정 풀 기준일 2026-09-15)
K = 10
MODES = ('hybrid', 'dense')
SYSTEMS = ('vector_only', 'legacy', 'filter_first')
# 처음 방식(벡터 유사도만)을 지금 코드로 재현하는 스위치. 과거 커밋을 불러오지 않고 끌 수 있는 것을 모두 끈다
VECTOR_ONLY = {'search': 'dense', 'structured_filter': False, 'hide_expired': False, 'demote_region': False,
               'demote_groups': False, 'demote_district': False, 'demote_industry': False,
               'use_applicant_types': False}


# ── 지표 (순수 함수 — tests/test_filter_first_eval.py) ─────────────────────────
def query_metrics(ranked, rels, eligible):
    """한 질의·한 시스템의 지표. ranked 공고 ID 목록(상위 K), rels {공고: topic_rel}, eligible {공고: bool}."""
    top3, topk = ranked[:3], ranked[:K]
    judged = lambda n: n in rels
    rel2 = lambda n: rels.get(n) == 2

    def useful(ids, unjudged_counts):
        return sum(1 for n in ids if eligible.get(n, True) and (rel2(n) or (unjudged_counts and not judged(n))))

    return {
        'returned': len(topk),
        'ineligible_k': (sum(1 for n in topk if not eligible.get(n, True)) / len(topk)) if topk else None,
        'p3_lo': sum(1 for n in top3 if rel2(n)) / 3,
        'p3_hi': sum(1 for n in top3 if rel2(n) or not judged(n)) / 3,
        'ndcg_k': evaluate.ndcg(topk, rels, K),
        'useful3_lo': useful(top3, False), 'useful3_hi': useful(top3, True),
        'usefulk_lo': useful(topk, False), 'usefulk_hi': useful(topk, True),
        'unjudged3': sum(1 for n in top3 if not judged(n)) / 3,
        'unjudgedk': (sum(1 for n in topk if not judged(n)) / len(topk)) if topk else None,
    }


def mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


METRICS = (('ineligible_k', '신청 불가@10', 'lower'), ('p3_lo', 'P@3(2) 하한', 'higher'),
           ('p3_hi', 'P@3(2) 상한', 'higher'), ('ndcg_k', 'nDCG@10(판정분)', 'higher'),
           ('useful3_lo', '쓸모@3 하한', 'higher'), ('useful3_hi', '쓸모@3 상한', 'higher'),
           ('usefulk_lo', '쓸모@10 하한', 'higher'), ('usefulk_hi', '쓸모@10 상한', 'higher'),
           ('unjudged3', '미판정@3', 'info'), ('unjudgedk', '미판정@10', 'info'), ('returned', '반환 건수', 'info'))


# ── 실행 준비 ───────────────────────────────────────────────────────────────
class CorpusCollection:
    """실제 Chroma 를 감싸 말뭉치 밖 공고를 보이지 않게 한다. 두 방식에 똑같이 적용된다."""

    def __init__(self, col, corpus):
        self.col, self.corpus, self.members = col, sorted(corpus), set(corpus)

    def count(self):
        return len(self.corpus)

    def query(self, query_embeddings, n_results, ids=None):
        ids = self.corpus if ids is None else [n for n in ids if n in self.members]
        return self.col.query(query_embeddings=query_embeddings, ids=ids, n_results=min(n_results, len(ids)))

    def get(self, ids=None, include=None):
        return self.col.get(ids=ids, include=include or [])


def load_legacy(app_module):
    """LEGACY_COMMIT 의 search/app.py 를 별도 모듈로 올린다. 저장소 파일은 바꾸지 않는다."""
    src = subprocess.run(['git', 'show', '%s:data-collection/search/app.py' % LEGACY_COMMIT],
                         cwd=ROOT, capture_output=True, check=True).stdout.decode('utf-8')
    spec = importlib.util.spec_from_loader('search_app_legacy', loader=None)
    legacy = importlib.util.module_from_spec(spec)
    legacy.__file__ = os.path.join(ROOT, 'search', 'app_legacy_%s.py' % LEGACY_COMMIT)
    exec(compile(src, legacy.__file__, 'exec'), legacy.__dict__)
    legacy.STATE = app_module.STATE
    return legacy


def pin_today(modules, as_of):
    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return as_of
    for m in modules:
        m.date = FixedDate


def corpus_rows(app_module):
    from shared import embed, store_mysql
    cols = ('notice_id',) + embed.FIELDS
    con = store_mysql.connect()
    try:
        with con.cursor() as cur:
            cur.execute('SELECT ' + ','.join(cols) + ' FROM notices WHERE created_at < %s', (CORPUS_BEFORE,))
            return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='결과 폴더 (기본 reports/filter_first_eval_<시각>)')
    args = ap.parse_args(argv)

    from search import app, gate, hybrid
    from shared import embed
    started = datetime.now(timezone.utc)
    app.boot()
    corpus = corpus_rows(app)
    corpus_ids = set(corpus) & app.STATE['vector_ids']
    app.STATE['rows'] = {n: r for n, r in app.STATE['rows'].items() if n in corpus_ids}
    app.STATE['collection'] = CorpusCollection(app.STATE['collection'], corpus_ids)
    app.STATE['vector_ids'] = corpus_ids
    app.STATE['bm25'] = hybrid.BM25([(n, embed.build_input(corpus[n])) for n in sorted(corpus_ids)
                                     if embed.build_input(corpus[n])])
    legacy = load_legacy(app)

    queries = [q for q in common.load_queries().values() if q['kind'] == 'normal']
    as_ofs = {q['as_of_date'] for q in queries}
    if len(as_ofs) != 1:
        raise SystemExit('질의 기준일이 여러 개다: %s' % sorted(as_ofs))
    as_of = real_date.fromisoformat(as_ofs.pop())
    pin_today((app, legacy, gate), as_of)

    qrels = {}
    for r in common.read_jsonl(common.QRELS):
        qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']

    cache, encode = {}, app._encode

    def cached(text):
        if text not in cache:
            cache[text] = encode(text)
        return cache[text]
    app._encode = legacy._encode = cached

    rows = app.STATE['rows']
    from search import applicant_types as types_mod
    types_table = app.STATE.get('applicant_types') or {}
    per = {m: {s: [] for s in SYSTEMS} for m in MODES}
    lists, shown = [], set()
    for q in queries:
        age = gate.applicant_age(q['payload'].get('applicant_type'), q['payload'].get('founded_at'), as_of)
        rels = qrels.get(q['qid'], {})
        # 벡터만은 검색 방식과 무관하다 — 한 번만 부르고 두 표에 같은 결과를 넣는다
        vector_ranked = [r['notice_id'] for r in app.match(app.MatchRequest(**dict(q['payload'], top=K, **VECTOR_ONLY)))['results']]
        for mode in MODES:
            for name, module in (('vector_only', None), ('legacy', legacy), ('filter_first', app)):
                if module is None:
                    ranked = vector_ranked
                else:
                    req = module.MatchRequest(**dict(q['payload'], top=K, search=mode))
                    ranked = [r['notice_id'] for r in module.match(req)['results']]
                use_types = bool(types_table.get('active')) and q['payload'].get('applicant_type') == types_mod.PRE_FOUNDER
                checks = {n: app.eligible_with_types(n, rows[n], age, as_of, True, types_table if use_types else None)[:2]
                          for n in ranked}
                eligible = {n: ok for n, (ok, _why) in checks.items()}
                m = query_metrics(ranked, rels, eligible)
                per[mode][name].append(m)
                shown.update(ranked)
                lists.append({'qid': q['qid'], 'mode': mode, 'system': name, 'ranked': ranked,
                              'ineligible': [n for n in ranked if not eligible[n]],
                              'why': {n: why for n, (ok, why) in checks.items() if not ok},
                              'rels': {n: rels.get(n) for n in ranked},
                              'unjudged': [n for n in ranked if n not in rels], 'metrics': m})

    summary = {}
    for mode in MODES:
        summary[mode] = {}
        for key, label, better in METRICS:
            v = [m[key] for m in per[mode]['vector_only']]
            a = [m[key] for m in per[mode]['legacy']]
            b = [m[key] for m in per[mode]['filter_first']]
            # diff 는 예전 결과 폴더와 같은 뜻(지금 − 9/22)으로 둔다. 벡터만과의 차이는 diff_vs_vector
            summary[mode][key] = {'label': label, 'better': better, 'vector_only': mean(v), 'legacy': mean(a),
                                  'filter_first': mean(b), 'diff': evaluate.paired_diff(a, b),
                                  'diff_vs_vector': evaluate.paired_diff(v, b)}

    out_dir = args.out or os.path.join(ROOT, 'reports', 'filter_first_eval_' + started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out_dir, exist_ok=False)
    meta = {'run_at': started.isoformat(timespec='seconds'), 'legacy_commit': LEGACY_COMMIT,
            'corpus_before': CORPUS_BEFORE, 'corpus_notices': len(corpus_ids), 'as_of': as_of.isoformat(),
            'queries': len(queries), 'k': K, 'modes': list(MODES), 'qrels_pairs': sum(len(v) for v in qrels.values()),
            'judges': 'all (human·llm·llm_old)', 'openai_calls': 0, 'db_writes': 0,
            'systems': list(SYSTEMS), 'vector_only_settings': VECTOR_ONLY}
    with io.open(os.path.join(out_dir, 'results.json'), 'w', encoding='utf-8') as f:
        # 화면(/filter-first-eval)이 DB 없이 보여 줄 수 있게 질의·공고 요약을 함께 남긴다
        json.dump({'meta': meta, 'summary': summary, 'lists': lists,
                   'queries': [{'qid': q['qid'], 'category': q.get('category'), 'idea': q['payload'].get('idea'),
                                'applicant_type': q['payload'].get('applicant_type'),
                                'founded_at': q['payload'].get('founded_at') or ''} for q in queries],
                   'notices': {n: {'title': rows[n].get('title') or '', 'source': rows[n].get('source'),
                                   'apply_end': str(rows[n].get('apply_end') or ''),
                                   'age_condition': rows[n].get('age_condition_raw') or ''}
                               for n in sorted(shown)}}, f, ensure_ascii=False, indent=1)
    lines = render(meta, summary)
    with io.open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print('결과 → %s' % out_dir)
    return 0


def fmt(v, key):
    if v is None:
        return '-'
    return '%.1f%%' % (v * 100) if key in ('ineligible_k', 'p3_lo', 'p3_hi', 'unjudged3', 'unjudgedk') else '%.3f' % v


def render(meta, summary):
    lines = ['# 벡터만 vs 검색 먼저 vs 정형 필터 먼저 — 수치 비교', '',
             '- 기준일 %s · 정상 질의 %d개 · 상위 %d · 말뭉치 %d건(%s 전 수집) · 예전 코드 커밋 `%s`'
             % (meta['as_of'], meta['queries'], meta['k'], meta['corpus_notices'], meta['corpus_before'],
                meta['legacy_commit']),
             '- 정답: qrels %d쌍(%s). OpenAI 호출 0 · DB 쓰기 0' % (meta['qrels_pairs'], meta['judges']),
             '- 벡터만 = 처음 방식 재현(정형 필터·마감 제외·단어 검색·규칙 모두 끔). 검색 방식과 무관해 두 표에 같은 값', '']
    for mode, rows in summary.items():
        lines += ['## %s' % mode, '',
                  '| 지표 | 벡터만(처음) | 9/22(검색 먼저) | 지금(필터 먼저) | 지금−벡터만 [95% 구간] | 지금−9/22 [95% 구간] | 좋은 쪽 |',
                  '|---|---:|---:|---:|---|---|---|']
        span = lambda d: '-' if not d else ('%+.3f [%+.3f, %+.3f]' % tuple(d))
        for key, s in rows.items():
            lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (
                s['label'], fmt(s.get('vector_only'), key), fmt(s['legacy'], key), fmt(s['filter_first'], key),
                span(s.get('diff_vs_vector')), span(s['diff']),
                {'lower': '낮을수록', 'higher': '높을수록', 'info': '참고'}[s['better']]))
        lines.append('')
    return lines


if __name__ == '__main__':
    sys.exit(main())
