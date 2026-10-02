# -*- coding: utf-8 -*-
"""매칭 개선 후보 A·B·C 비교 — 서비스 match() 최종 순위를 그대로 쓰고 스위치만 바꾼다(2026-09-30). OpenAI 호출 없음.

  python -X utf8 -m eval.match_variants                          DB·Chroma 읽기만. 결과는 reports/match_variants_<시각>/
  python -X utf8 -m eval.match_variants --extra-qrels reports/relevance_label_pack_20260930/codex_qrels.jsonl

2026-09-30 사용자 요청. 근거는 reports/match_miss_analysis_20260930/summary.md.

스위치 (search/app.py 는 바꾸지 않는다 — 효과가 확인된 것만 나중에 서비스에 옮긴다)
  A  단어 검색(BM25) 질의를 아이디어 + 업종·인증 등(applicant.query_extras)으로 줄인다.
     수익모델·"창업 N년차 법인"·팀 경력을 뺀다. 의미 검색 질의·규칙에 쓰는 입력은 그대로다.
     구현: STATE['bm25'] 를 감싸 match() 가 넘긴 질의 대신 줄인 질의로 찾는다.
  B  RRF 무게. 서비스 Weights(dense·bm25·rrf_k)를 그대로 넘긴다. B05 = 단어 검색 0.5, B07 = 0.7.
  C  비슷한 공고 묶기. 제목에서 [지역]·시군구·연도·차수·수정/변경 등을 지우고 첫 '사업'까지(없으면 앞 14자)가
     같으면 같은 계열로 본다. 8자 미만("창업지원사업")은 묶지 않는다.
     계열마다 가장 위 한 건만 제자리에 두고 나머지는 후보 끝으로 보낸다(빼지 않는다). match() 상위 DEPTH 에 적용한다.

평가 조건은 eval/filter_first_eval.py 와 같다(기준일 2026-09-15, 9/16 전 말뭉치, 정상 질의, 상위 10, 지금 방식 hybrid).
분할: eval/splits.json 의 train=개발용, test=시험용. **스위치는 개발용 수치로 고르고 시험용은 확인에만 쓴다.**
지표는 filter_first_eval.query_metrics 와 같다. 차이는 기준(base) 대비 질의별 짝 차이와 95% 부트스트랩 구간.
"""
import argparse
import json
import os
import re
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

K = 10
DEPTH = 50
VARIANTS = {
    'base': {},
    'A': {'bm25_query': True},
    'B05': {'weights': {'bm25': 0.5}},
    'B07': {'weights': {'bm25': 0.7}},
    'C': {'collapse': True},
    'A+B07': {'bm25_query': True, 'weights': {'bm25': 0.7}},
    'A+C': {'bm25_query': True, 'collapse': True},
    'A+B07+C': {'bm25_query': True, 'weights': {'bm25': 0.7}, 'collapse': True},
}
METRICS = [m for m in ffe.METRICS if m[0] != 'returned']


# ── 순수 함수 (tests/test_match_variants.py) ──────────────────────────────
def lexical_query(payload):
    """A — 단어 검색 질의. 아이디어 + applicant.query_extras(업종·인증·고용 계획)."""
    from search import applicant
    parts = [payload.idea.strip()] + applicant.query_extras(payload)
    return '. '.join(p for p in parts if p)


def family_key(title):
    """C — 같은 사업의 시군별·수정 공고를 한 계열로 묶는 제목 열쇠."""
    t = re.sub(r'\[[^\]]*\]', '', title or '')
    t = re.sub(r'\([^)]*\)|「|」|『|』', '', t)
    t = re.sub(r'[가-힣]+(시|군|구)\s', '', t)
    t = re.sub(r'(수정|변경|연장|추가|재|정정)\s*(공고|모집)?', '', t)
    t = re.sub(r'20\d\d년?|\d+차|\d+기|하반기|상반기', '', t)
    t = re.sub(r'[\sㆍ·,.\-]', '', t)
    # 사업 이름(첫 '사업'까지)을 열쇠로 한다. 뒤의 "참여업체 모집"·"참여 점포 모집" 같은 꼬리 차이를 무시한다.
    # 너무 짧으면("창업지원사업") 서로 다른 사업이 묶이므로 묶지 않는다(빈 열쇠)
    m = re.match(r'(.{4,}?사업)', t)
    key = m.group(1) if m else t[:14]
    return key if len(key) >= 8 else ''


def collapse(ranked, title_of):
    """C — 계열마다 첫 건만 제자리, 나머지는 원래 순서대로 끝에 붙인다."""
    seen, head, tail = set(), [], []
    for nid in ranked:
        key = family_key(title_of(nid))
        (tail if key and key in seen else head).append(nid)
        seen.add(key)
    return head + tail


class SwitchableBM25:
    """match() 가 부르는 STATE['bm25'].search 의 질의만 갈아 끼운다. override 가 None 이면 그대로다."""

    def __init__(self, inner):
        self.inner, self.override = inner, None

    def search(self, query, **kw):
        return self.inner.search(self.override or query, **kw)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def load_qrels(extra=None):
    qrels = {}
    for r in common.read_jsonl(common.QRELS):
        qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
    added = 0
    for path in extra or []:
        for r in common.read_jsonl(path):
            if r.get('topic_rel') is None or r['notice_id'] in qrels.get(r['qid'], {}):
                continue                                  # 기존 판정을 덮지 않는다
            qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
            added += 1
    return qrels, added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='결과 폴더 (기본 reports/match_variants_<시각>)')
    ap.add_argument('--extra-qrels', action='append', default=[], help='덧붙일 판정 jsonl (qrels.jsonl 은 고치지 않는다)')
    args = ap.parse_args(argv)

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
    bm25 = SwitchableBM25(hybrid.BM25([(n, embed.build_input(corpus[n])) for n in sorted(ids)
                                       if embed.build_input(corpus[n])]))
    app.STATE['bm25'] = bm25

    queries = [q for q in common.load_queries().values() if q['kind'] == 'normal']
    as_of = real_date.fromisoformat(queries[0]['as_of_date'])
    ffe.pin_today((app, gate), as_of)
    qrels, added = load_qrels(args.extra_qrels)
    splits = json.load(open(os.path.join(HERE, 'splits.json'), encoding='utf-8'))
    split_of = {qid: s for s in ('train', 'test') for qid in splits[s]}

    cache, encode = {}, app._encode

    def cached(text):
        if text not in cache:
            cache[text] = encode(text)
        return cache[text]
    app._encode = cached

    rows = app.STATE['rows']
    types_table = app.STATE.get('applicant_types') or {}
    title_of = lambda n: (rows.get(n) or {}).get('title') or ''
    per, lists = {v: {} for v in VARIANTS}, []
    for q in queries:
        p = q['payload']
        age = gate.applicant_age(p.get('applicant_type'), p.get('founded_at'), as_of)
        use_types = bool(types_table.get('active')) and p.get('applicant_type') == types_mod.PRE_FOUNDER
        rels = qrels.get(q['qid'], {})
        for name, sw in VARIANTS.items():
            req = app.MatchRequest(**dict(p, top=DEPTH, search='hybrid', weights=sw.get('weights', {})))
            bm25.override = lexical_query(req) if sw.get('bm25_query') else None
            try:
                ranked = [r['notice_id'] for r in app.match(req)['results']]
            finally:
                bm25.override = None
            if sw.get('collapse'):
                ranked = collapse(ranked, title_of)
            ranked = ranked[:K]
            checks = {n: app.eligible_with_types(n, rows[n], age, as_of, True, types_table if use_types else None)[0]
                      for n in ranked}
            m = ffe.query_metrics(ranked, rels, checks)
            per[name][q['qid']] = m
            lists.append({'qid': q['qid'], 'variant': name, 'ranked': ranked,
                          'rels': {n: rels.get(n) for n in ranked}})

    groups = {'dev': [q['qid'] for q in queries if split_of.get(q['qid']) == 'train'],
              'test': [q['qid'] for q in queries if split_of.get(q['qid']) == 'test'],
              'all': [q['qid'] for q in queries]}
    summary = {}
    for g, qids in groups.items():
        summary[g] = {}
        for key, label, better in METRICS:
            base = [per['base'][qid][key] for qid in qids]
            summary[g][key] = {'label': label, 'better': better, 'values': {}, 'diff': {}}
            for name in VARIANTS:
                vals = [per[name][qid][key] for qid in qids]
                summary[g][key]['values'][name] = ffe.mean(vals)
                if name != 'base':
                    summary[g][key]['diff'][name] = evaluate.paired_diff(base, vals)

    out_dir = args.out or os.path.join(ROOT, 'reports', 'match_variants_' + started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out_dir, exist_ok=False)
    meta = {'run_at': started.isoformat(timespec='seconds'), 'as_of': as_of.isoformat(), 'k': K, 'depth': DEPTH,
            'corpus_before': ffe.CORPUS_BEFORE, 'corpus_notices': len(ids), 'mode': 'hybrid',
            'queries': {g: len(v) for g, v in groups.items()}, 'variants': VARIANTS,
            'qrels_pairs': sum(len(v) for v in qrels.values()), 'extra_qrels': args.extra_qrels,
            'extra_added': added, 'openai_calls': 0, 'db_writes': 0}
    json.dump({'meta': meta, 'summary': summary, 'lists': lists}, open(os.path.join(out_dir, 'results.json'), 'w',
              encoding='utf-8'), ensure_ascii=False, indent=1)
    md = render(meta, summary)
    open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8').write(md)
    print(md)
    print('결과:', out_dir)


def render(meta, summary):
    names = list(VARIANTS)
    lines = ['# 매칭 개선 후보 A·B·C 비교', '',
             '- 기준일 %s · 말뭉치 %d건(%s 전) · hybrid · 상위 %d (match 상위 %d에 C 적용)'
             % (meta['as_of'], meta['corpus_notices'], meta['corpus_before'], meta['k'], meta['depth']),
             '- 질의: 개발용 %(dev)d · 시험용 %(test)d · 전체 %(all)d' % meta['queries'],
             '- 판정 %d쌍%s · OpenAI 호출 0 · DB 쓰기 0'
             % (meta['qrels_pairs'], (' (덧붙인 판정 %d쌍: %s)' % (meta['extra_added'], ', '.join(meta['extra_qrels'])))
                                     if meta['extra_qrels'] else ''),
             '- 스위치: A 단어 검색 질의 줄이기 · B05/B07 단어 검색 무게 0.5/0.7 · C 비슷한 공고 묶기',
             '- **개발용으로 고르고 시험용은 확인에만 쓴다.** 차이는 base 대비 [95% 구간]', '']
    for g, title in (('dev', '개발용'), ('test', '시험용'), ('all', '전체')):
        lines += ['## %s' % title, '', '| 지표 | ' + ' | '.join(names) + ' |', '|---|' + '---:|' * len(names)]
        for key, s in summary[g].items():
            cells = []
            for name in names:
                v = s['values'][name]
                cell = '-' if v is None else ('%.3f' % v)
                d = s['diff'].get(name)
                if d:
                    cell += '<br>%+.3f [%+.3f, %+.3f]' % d
                cells.append(cell)
            lines.append('| %s | %s |' % (s['label'], ' | '.join(cells)))
        lines.append('')
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
