# -*- coding: utf-8 -*-
"""지역 규칙(소재지가 다른 지역 전용 공고를 뒤로 보내기)의 효과를 잰다.

  python -X utf8 eval/region_eval.py
  python -X utf8 eval/region_eval.py --unjudged-out eval/runs/region_unjudged.jsonl

평가 질의(queries.jsonl)에는 소재지가 없다. 한 지역을 임의로 정해 주면 그 선택에
결과가 흔들리므로, **질의마다 16개 시·도를 전부 소재지로 넣어 보고 평균**을 낸다.
52질의 × 16지역 = 832번 검색한 셈이다. 검색 자체는 질의당 한 번이고(지역은 질의
문장에 들어가지 않는다), 지역 규칙은 그 결과의 순서만 바꾼다.

재는 것
  신청 불가칸   상위 3 중 다른 지역 전용 공고가 차지한 칸 비율      ← 이 규칙이 줄이려는 것
  지역 모름칸   상위 3 중 공고에 지역 정보가 없는 칸 비율
  P@3(2)·P@3≥1  주제 적합도. 규칙 때문에 좋은 공고가 밀려나면 떨어진다  ← 대가
  미판정@3      높으면 위 두 숫자를 믿지 않는다
  쓸모칸        신청 가능하면서 주제도 맞는 칸 비율 (2 / ≥1)      ← 사용자 입장의 지표

주제 적합도 정답(qrels)은 지역과 무관하게 매긴 것이다. 그래서 "주제는 맞지만
신청할 수 없는 공고"를 P@3 은 만점으로 센다 — 이 스크립트가 신청 불가칸을 따로 세는 이유다.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import evaluate as ev  # noqa: E402
import region  # noqa: E402  (common 이 ROOT 를 sys.path 에 넣는다)

SYSTEM = 'rrf'          # 서비스 기본 검색(하이브리드)
POOL_K = 30             # 규칙이 뒤에서 끌어올릴 수 있는 후보 수. app.py 는 이보다 넉넉하다


def load_regions():
    import store_mysql
    c = store_mysql.connect()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT notice_id, region FROM notices')
            return {nid: reg for nid, reg in cur.fetchall()}
    finally:
        c.close()


def slot_stats(top3, rels, regions, applicant):
    m = [region.matches(regions.get(n), applicant) for n in top3]
    return {
        'blocked': sum(1 for x in m if x is False) / 3,
        'unknown': sum(1 for n in top3 if not regions.get(n)) / 3,
        'p3_rec': sum(1 for n in top3 if rels.get(n) == 2) / 3,
        'p3_rel': sum(1 for n in top3 if (rels.get(n) or 0) >= 1) / 3,
        'unjudged3': sum(1 for n in top3 if n not in rels) / 3,
        # 신청할 수 있으면서(다른 지역 전용이 아니면서) 주제도 맞는 칸.
        # 사용자에게 실제로 쓸모 있는 칸이다
        'ok_rec': sum(1 for n, x in zip(top3, m) if x is not False and rels.get(n) == 2) / 3,
        'ok_rel': sum(1 for n, x in zip(top3, m) if x is not False and (rels.get(n) or 0) >= 1) / 3,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--unjudged-out', help='규칙 적용 후 상위 3 에 새로 올라온 미판정 쌍을 JSONL 로')
    args = ap.parse_args()

    queries = {qid: q for qid, q in common.load_queries().items() if q['kind'] == 'normal'}
    qrels = {}
    for r in common.read_jsonl(common.QRELS):
        qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
    regions = load_regions()
    systems = ev.Systems()

    before, after = {}, {}          # qid -> 지역 평균 지표
    per_region = {r: Counter() for r in region.REGIONS}
    unjudged = set()
    moved_any = 0
    for qid, q in queries.items():
        ranked = [n for n, _ in systems.run(SYSTEM, q, k=POOL_K)]
        rels = qrels.get(qid, {})
        b_sum, a_sum = Counter(), Counter()
        for reg in region.REGIONS:
            keep, moved = region.demote(ranked, reg, key=lambda n: regions.get(n))
            new_top = (keep + moved)[:3]
            b = slot_stats(ranked[:3], rels, regions, reg)
            a = slot_stats(new_top, rels, regions, reg)
            b_sum.update(b)
            a_sum.update(a)
            per_region[reg]['blocked_before'] += b['blocked']
            per_region[reg]['blocked_after'] += a['blocked']
            if new_top != ranked[:3]:
                moved_any += 1
            unjudged.update((qid, n) for n in new_top if n not in rels)
        before[qid] = {k: v / len(region.REGIONS) for k, v in b_sum.items()}
        after[qid] = {k: v / len(region.REGIONS) for k, v in a_sum.items()}

    n = len(queries)
    mean = lambda d, k: sum(v[k] for v in d.values()) / n
    fmt = lambda v: '%.3f' % v
    print('정상 %d질의 × 16지역 = %d번 · 검색 %s · 규칙이 상위 3을 바꾼 경우 %d번 (%.0f%%)'
          % (n, n * 16, SYSTEM, moved_any, moved_any / (n * 16) * 100))
    print('\n%-14s %-10s %-10s %-8s %-8s %-10s %-10s %-8s' % (
        '', '신청불가칸', '지역모름칸', 'P@3(2)', 'P@3≥1', '쓸모칸(2)', '쓸모칸(≥1)', '미판정@3'))
    for name, d in (('규칙 없음', before), ('지역 규칙', after)):
        print('%-14s %-10s %-10s %-8s %-8s %-10s %-10s %-8s' % (
            name, fmt(mean(d, 'blocked')), fmt(mean(d, 'unknown')),
            fmt(mean(d, 'p3_rec')), fmt(mean(d, 'p3_rel')),
            fmt(mean(d, 'ok_rec')), fmt(mean(d, 'ok_rel')), fmt(mean(d, 'unjudged3'))))

    print('\n짝지은 차이 (질의별, 95% 구간)')
    for key, label in (('blocked', '신청불가칸'), ('p3_rec', 'P@3(2)'), ('p3_rel', 'P@3≥1'),
                       ('ok_rec', '쓸모칸(2)'), ('ok_rel', '쓸모칸(≥1)')):
        d = ev.paired_diff([before[q][key] for q in queries], [after[q][key] for q in queries])
        print('  %-10s %+.3f  (%+.3f ~ %+.3f)' % (label, *d))

    print('\n소재지별 신청불가칸 (규칙 없음 → 지역 규칙)')
    for reg in region.REGIONS:
        c = per_region[reg]
        print('  %-6s %.3f → %.3f' % (reg, c['blocked_before'] / n, c['blocked_after'] / n))

    print('\n규칙 적용 후 상위 3의 미판정 쌍 %d개' % len(unjudged))
    if args.unjudged_out:
        known = {(p['qid'], p['notice_id']) for p in common.read_jsonl(common.POOL)}
        rows = [{'qid': q, 'notice_id': nid, 'rank': 0, 'system': 'rrf+region'}
                for q, nid in sorted(unjudged)]
        common.write_jsonl(args.unjudged_out, rows)
        print('  → %s (풀에 없는 쌍 %d개)' % (args.unjudged_out,
                                         sum(1 for r in rows if (r['qid'], r['notice_id']) not in known)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
