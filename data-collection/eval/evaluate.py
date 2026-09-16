# -*- coding: utf-8 -*-
"""검색 평가 · 개선안 비교. qrels.jsonl 기준. OpenAI 호출 없음.

  python -X utf8 eval/evaluate.py                                   현재 방식
  python -X utf8 eval/evaluate.py --systems dense idea idea+B idea+B+C
  python -X utf8 eval/evaluate.py --judges human                    사람 판정만 정답으로
  python -X utf8 eval/evaluate.py --systems idea+B --unjudged       새로 올라온 미판정 쌍 목록

시스템 이름 = 질의 방식 [+보정...]. **모든 방식이 Chroma 후보에서 출발한다**(HANDOFF 2절).

  dense   현재 /api/match 와 같은 질의 (build_query: 아이디어·수익모델·신청자 유형·연차·팀 경력)
  idea    개선안 A — 신청자 유형·연차를 뺀 질의. 유형은 자격 판정(gate)에만 쓴다
  +B      개선안 B — 특정 대상 집단(장애인·체육인 등) 공고인데 신청자 입력에 그 집단
          단어가 없으면 후보 맨 뒤로 보낸다
  +C      개선안 C — 허브 보정(CSLS). 점수 = 2·cos(질의, 공고) − r(공고)
          r = 그 공고와 가장 가까운 공고 10건의 평균 코사인. 두루 가까운 공고일수록 깎인다
  bm25, rrf   오프라인 비교용 기준선

지표

  P@3(2)     **주 지표.** 상위 3건 중 topic_rel=2(추천할 만함) 비율. 분모 3 고정
  P@3(≥1)    관련 비율
  nDCG@3     보조. 미판정 공고를 빼고 계산(condensed)
  미판정@3   상위 3 중 정답이 없는 비율. 높으면 그 시스템 숫자를 믿지 않는다
  (판정 없이 재는 것)
  공고 종류   정상 질의 52개 상위 3 = 156칸에 나온 서로 다른 공고 수 — 적을수록 같은 공고 반복
  최다 반복   한 공고가 몇 개 질의의 상위 3에 들었나
  집단 칸     특정 대상 집단 공고가 (신청자 입력에 근거 없이) 상위 3을 차지한 칸 수

질의 수가 적다(정상 52). 차이는 부트스트랩 95% 구간과 같이 본다.
"""
import argparse
import json
import math
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

JUDGE_LEVELS = {'human': {'human'}, 'llm': {'human', 'llm'},
                'all': {'human', 'llm', 'llm_old'}}

# 개선안 B 규칙은 서비스(app.py)와 같은 rank_rules.py 를 쓴다.
import rank_rules  # noqa: E402

CSLS_K = 10
CANDIDATES = 50


def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg(ranked, rels, k):
    ranked = [n for n in ranked if n in rels]
    gains = [rels[n] for n in ranked[:k]]
    ideal = sorted(rels.values(), reverse=True)[:k]
    return None if not ideal or ideal[0] == 0 else dcg(gains) / dcg(ideal)


def bootstrap(values, rounds=2000, seed=7):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(rounds))
    return means[int(rounds * 0.025)], means[int(rounds * 0.975)]


def paired_diff(a, b, rounds=2000, seed=11):
    """질의별 짝지은 차이(b − a)의 평균과 95% 구간"""
    d = [y - x for x, y in zip(a, b) if x is not None and y is not None]
    if len(d) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(rounds))
    return sum(d) / len(d), means[int(rounds * 0.025)], means[int(rounds * 0.975)]


def idea_text(q):
    """개선안 A — build_query 에서 신청자 유형·연차만 뺀다. 나머지 순서·형식은 같다."""
    p = q['payload']
    parts = [p.get('idea', '').strip()]
    items = [r.get('item', '').strip() for r in p.get('revenue') or [] if r.get('item', '').strip()]
    if items:
        parts.append('수익모델: ' + ', '.join(items))
    careers = [m.get('career', '').strip() for m in p.get('team') or [] if m.get('career', '').strip()]
    if careers:
        parts.append('팀 경력: ' + ', '.join(careers))
    return '. '.join(x for x in parts if x)


class Systems:
    def __init__(self):
        self._bm25 = None
        self._csls = None
        self._notices = None

    def notices(self):
        if self._notices is None:
            import store_mysql
            c = store_mysql.connect()
            try:
                with c.cursor() as cur:
                    cur.execute('SELECT notice_id, title, target_category FROM notices')
                    self._notices = {r[0]: {'title': r[1] or '', 'target_category': r[2] or ''}
                                     for r in cur.fetchall()}
            finally:
                c.close()
        return self._notices

    def is_group(self, nid, applicant_text):
        n = self.notices().get(nid, {})
        return bool(rank_rules.groups_not_matched(n.get('title'), n.get('target_category'),
                                                  applicant_text))

    def csls(self):
        """공고별 r = 가장 가까운 공고 K건 평균 코사인. 벡터 파일에서 한 번 계산.
        서비스에 넣는다면 이 값을 Chroma 메타데이터로 저장해 두면 된다."""
        if self._csls is None:
            import numpy as np
            import vecstore
            ids, vecs, _ = vecstore.load_vectors()
            sims = vecs @ vecs.T
            np.fill_diagonal(sims, -1)
            top = np.sort(sims, axis=1)[:, -CSLS_K:]
            self._csls = dict(zip(ids, top.mean(axis=1).tolist()))
        return self._csls

    def bm25(self):
        if self._bm25 is None:
            from bm25 import BM25
            from build_pool import corpus
            docs, _, _ = corpus()
            self._bm25 = BM25(docs)
        return self._bm25

    def dense(self, text, k):
        import vecstore
        hits, _ = vecstore.search(text, top=k + 1, engine='chroma')
        return [(n, float(s)) for n, s in hits if n != '__watermark__'][:k]

    def run(self, name, q, k=30):
        if name == 'bm25':
            return self.bm25().search(common.query_text(q), top=k)
        if name == 'rrf':
            text = common.query_text(q)
            fused = {}
            for hits in (self.dense(text, 50), self.bm25().search(text, top=50)):
                for rank, (n, _) in enumerate(hits, 1):
                    fused[n] = fused.get(n, 0) + 1 / (60 + rank)
            return sorted(fused.items(), key=lambda x: (-x[1], x[0]))[:k]

        base, *flags = name.split('+')
        text = {'dense': common.query_text, 'idea': idea_text}[base](q)
        hits = self.dense(text, CANDIDATES)
        if 'C' in flags:
            r = self.csls()
            hits = sorted(((n, 2 * s - r.get(n, 0)) for n, s in hits), key=lambda x: -x[1])
        if 'B' in flags:
            p = q['payload']
            applicant = ' '.join([p.get('idea', '')] + [m.get('career', '') for m in p.get('team') or []])
            hits = ([h for h in hits if not self.is_group(h[0], applicant)] +
                    [h for h in hits if self.is_group(h[0], applicant)])
        return hits[:k]


def evaluate(name, queries, qrels, systems):
    per = []
    for qid, q in queries.items():
        hits = systems.run(name, q)
        ranked = [n for n, _ in hits]
        rels = qrels.get(qid, {})
        top3 = ranked[:3]
        p = q['payload']
        applicant = ' '.join([p.get('idea', '')] + [m.get('career', '') for m in p.get('team') or []])
        per.append({
            'qid': qid, 'kind': q['kind'], 'category': q['category'],
            'top1_score': hits[0][1] if hits else None,
            'top3': [{'notice_id': n, 'topic_rel': rels.get(n)} for n in top3],
            'p3_rec': sum(1 for n in top3 if rels.get(n) == 2) / 3,
            'p3_rel': sum(1 for n in top3 if (rels.get(n) or 0) >= 1) / 3,
            # 판정된 칸만으로 본 2 의 비율. 미판정이 많은 시스템이 P@3(2) 에서 억울하게
            # 깎이는지 확인용. 판정 칸이 없으면 None
            'p3_rec_judged': (lambda j: sum(1 for n in j if rels[n] == 2) / len(j) if j else None)(
                [n for n in top3 if n in rels]),
            'ndcg3': ndcg(ranked, rels, 3),
            'unjudged3': sum(1 for n in top3 if n not in rels) / 3,
            'group3': sum(1 for n in top3 if systems.is_group(n, applicant)),
        })
    return per


def summarize(name, per):
    normal = [r for r in per if r['kind'] == 'normal']
    mean = lambda key: (lambda v: sum(v) / len(v) if v else None)(
        [r[key] for r in normal if r[key] is not None])
    slots = Counter(t['notice_id'] for r in normal for t in r['top3'])
    s = {'system': name, 'queries': len(normal)}
    for key in ('p3_rec', 'p3_rec_judged', 'p3_rel', 'ndcg3', 'unjudged3'):
        s[key] = mean(key)
    s['p3_rec_ci95'] = bootstrap([r['p3_rec'] for r in normal])
    s['distinct_top3'] = len(slots)
    s['max_repeat'] = slots.most_common(1)[0] if slots else None
    s['group_slots'] = sum(r['group3'] for r in normal)
    neg = [r for r in per if r['kind'] == 'negative']
    s['negative_group_slots'] = sum(r['group3'] for r in neg)
    return s


def print_table(summaries, base):
    fmt = lambda v: '  -  ' if v is None else '%.3f' % v
    print('\n%-10s %-6s %-13s %-8s %-7s %-7s %-7s %-5s %-5s %-5s' %
          ('시스템', 'P@3(2)', '95%', '판정칸만', 'P@3≥1', 'nDCG@3', '미판정@3', '종류', '최다', '집단칸'))
    for s in summaries:
        ci = s['p3_rec_ci95']
        print('%-12s %s  %-13s %s    %s   %s   %s    %3d   %2d   %3d' % (
            s['system'], fmt(s['p3_rec']), '%.2f~%.2f' % ci if ci else '-', fmt(s['p3_rec_judged']),
            fmt(s['p3_rel']), fmt(s['ndcg3']), fmt(s['unjudged3']),
            s['distinct_top3'], s['max_repeat'][1] if s['max_repeat'] else 0, s['group_slots']))
    print('  (종류: 정상 52질의 상위3 156칸 중 서로 다른 공고 수 · 최다: 한 공고 최다 반복 · 집단칸: 근거 없는 특정 집단 공고)')
    if base:
        print('\n기준 대비 P@3(2) 짝지은 차이 (질의별, 95% 구간이 0 을 넘어야 개선이라 본다)')
        for s in summaries:
            if s['system'] == base['system']:
                continue
            d = paired_diff([r['p3_rec'] for r in base['_per'] if r['kind'] == 'normal'],
                            [r['p3_rec'] for r in s['_per'] if r['kind'] == 'normal'])
            if d:
                print('  %-12s %+.3f  (%+.3f ~ %+.3f)' % (s['system'], *d))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--systems', nargs='*', default=['dense'])
    ap.add_argument('--judges', default='all', choices=list(JUDGE_LEVELS))
    ap.add_argument('--unjudged', action='store_true', help='시스템별 상위 3의 미판정 쌍 목록')
    ap.add_argument('--no-save', action='store_true')
    args = ap.parse_args()

    queries = common.load_queries()
    allowed = JUDGE_LEVELS[args.judges]
    qrels, used = {}, Counter()
    for r in common.read_jsonl(common.QRELS):
        if r['judge'] in allowed:
            qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
            used[r['judge']] += 1
    if not used:
        raise SystemExit('qrels.jsonl 이 비었다. merge_qrels.py 를 먼저 돌린다.')
    print('정답 %s (judges=%s)' % (dict(used), args.judges))

    systems = Systems()
    summaries = []
    os.makedirs(common.RUNS, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    for name in args.systems:
        per = evaluate(name, queries, qrels, systems)
        s = summarize(name, per)
        s['_per'] = per
        summaries.append(s)
        if args.unjudged:
            miss = [(r['qid'], t['notice_id']) for r in per for t in r['top3'] if t['topic_rel'] is None]
            print('\n[%s] 상위 3 미판정 %d쌍' % (name, len(miss)))
        if not args.no_save:
            path = os.path.join(common.RUNS, '%s_%s_%s.json' % (name.replace('+', '_'), args.judges, stamp))
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'summary': {k: v for k, v in s.items() if k != '_per'}, 'per_query': per,
                           'judges': args.judges, 'qrels_pairs': dict(used),
                           'label_version': common.LABEL_VERSION}, f, ensure_ascii=False, indent=1)
    print_table(summaries, summaries[0] if len(summaries) > 1 else None)
    return 0


if __name__ == '__main__':
    sys.exit(main())
