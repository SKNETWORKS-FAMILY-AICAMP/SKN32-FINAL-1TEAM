# -*- coding: utf-8 -*-
"""검색 가중치를 바꿔 가며 질의 52개로 잰다. 화면의 /weights 가 눈으로 보는 것을 숫자로 본다.

  python -X utf8 eval/weight_eval.py                      기본 조합 몇 가지
  python -X utf8 eval/weight_eval.py --sweep              의미:단어 비율 훑기
  python -X utf8 eval/weight_eval.py --pairs 2:1 1:2 --k 30 60 120

**주의 — 여기서 가장 좋게 나온 값을 그대로 서비스에 넣으면 안 된다.**
질의가 52개뿐이라, 조합을 여러 개 재면 그중 하나는 우연히 좋아 보인다(과적합).
차이의 95% 구간이 0 을 넘고, 그 폭이 넉넉할 때만 바꿀 근거가 된다.
지금 서비스 값은 1:1 · k=60 이며, 기준선으로 항상 함께 찍는다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import evaluate as ev  # noqa: E402
from search import hybrid  # noqa: E402

BASE = (1.0, 1.0, hybrid.RRF_K)


def run(systems, queries, qrels, dense_w, bm25_w, k):
    """가중치 한 조합으로 질의 전체를 돌려 질의별 지표를 돌려준다."""
    per = []
    for qid, q in queries.items():
        text = common.query_text(q)
        fused = hybrid.rrf(systems.dense(text, hybrid.DEPTH),
                           systems.bm25().search(text, top=hybrid.DEPTH),
                           k=k, weights=(dense_w, bm25_w))
        ranked = [n for n, _ in fused]
        rels = qrels.get(qid, {})
        top3 = ranked[:3]
        per.append({
            'qid': qid,
            'p3_rec': sum(1 for n in top3 if rels.get(n) == 2) / 3,
            'p3_rel': sum(1 for n in top3 if (rels.get(n) or 0) >= 1) / 3,
            'ndcg3': ev.ndcg(ranked, rels, 3),
            'unjudged3': sum(1 for n in top3 if n not in rels) / 3,
            'top3': top3,
        })
    return per


def mean(per, key):
    vals = [r[key] for r in per if r[key] is not None]
    return sum(vals) / len(vals) if vals else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pairs', nargs='*', default=['1:1', '2:1', '1:2', '3:1', '1:3'],
                    help='의미:단어 비율 (예: 2:1)')
    ap.add_argument('--k', nargs='*', type=int, default=[hybrid.RRF_K])
    ap.add_argument('--sweep', action='store_true', help='0.5 ~ 3.0 을 촘촘히 훑는다')
    args = ap.parse_args()

    combos = []
    if args.sweep:
        for w in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
            combos.append((w, 1.0, hybrid.RRF_K))
    else:
        for pair in args.pairs:
            d, b = (float(x) for x in pair.split(':'))
            for k in args.k:
                combos.append((d, b, k))
    if BASE not in combos:
        combos.insert(0, BASE)

    queries = {qid: q for qid, q in common.load_queries().items() if q['kind'] == 'normal'}
    qrels = {}
    for r in common.read_jsonl(common.QRELS):
        qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
    systems = ev.Systems()

    print('정상 %d질의 · 기준선 의미:단어 %.1f:%.1f · k=%d (지금 서비스)'
          % (len(queries), BASE[0], BASE[1], BASE[2]))
    base_per = None
    print('\n%-18s %-8s %-8s %-8s %-8s %-8s' %
          ('의미:단어 · k', 'P@3(2)', 'P@3≥1', 'nDCG@3', '미판정', '상위3 변화'))
    for combo in combos:
        per = run(systems, queries, qrels, *combo)
        if base_per is None:
            base_per = per
        changed = sum(1 for a, b in zip(base_per, per) if a['top3'] != b['top3'])
        label = '%.2f:%.2f · %d' % combo
        print('%-18s %-8.3f %-8.3f %-8.3f %-8.3f %d질의' % (
            label + (' ←기준' if combo == BASE else ''),
            mean(per, 'p3_rec'), mean(per, 'p3_rel'), mean(per, 'ndcg3'),
            mean(per, 'unjudged3'), changed))
        if combo != BASE:
            d = ev.paired_diff([r['p3_rec'] for r in base_per], [r['p3_rec'] for r in per])
            if d:
                verdict = '개선' if d[1] > 0 else ('악화' if d[2] < 0 else '판단 불가')
                print('%-18s   P@3(2) 차이 %+.3f (%+.3f ~ %+.3f) → %s'
                      % ('', d[0], d[1], d[2], verdict))
    print('\n구간이 0 을 걸치면 "그 조합이 더 낫다" 고 말할 수 없다. 기본값을 유지한다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
