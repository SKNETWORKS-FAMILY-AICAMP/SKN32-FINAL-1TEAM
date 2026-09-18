# -*- coding: utf-8 -*-
"""자격(업력·접수기간·모집상태) 기준으로 상위 3칸을 센다.

  python -X utf8 eval/gate_eval.py

지역에서 한 것과 같은 질문을 업력에도 던진다 — **추천한 공고를 신청할 수는 있나.**
주제 적합도(P@3)는 이걸 보지 않는다. "주제는 맞지만 업력이 안 되는 공고"를 만점으로 센다.

판정은 서비스와 같은 gate.py 를 쓴다. 질의의 설립일(payload.founded_at)과 기준일
(as_of_date)로 업력을 계산하므로, 질의마다 신청자가 다르다.

세는 것 (정상 52질의 × 상위 3칸)
  업력 불가칸    gate 가 업력 미달로 판정한 칸           ← 줄이고 싶은 것
  업력 모름칸    공고에 업력 조건이 없거나 해석 못한 칸    ← 업력 뽑기로 줄여야 할 것
  기간·상태 불가칸  마감됐거나 모집이 끝난 칸
  자격 불가칸    위 중 하나라도 미달인 칸
  쓸모칸(2)     자격 미달이 아니면서 주제도 딱 맞는 칸
"""
import os
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import evaluate as ev  # noqa: E402
import gate  # noqa: E402

SYSTEM = 'rrf'
FIELDS = ('notice_id', 'age_condition_raw', 'apply_start', 'apply_end',
          'apply_period_type', 'recruitment_status')


def load_notices():
    import store_mysql
    c = store_mysql.connect()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT ' + ','.join(FIELDS) + ' FROM notices')
            return {r[0]: dict(zip(FIELDS, (str(v) if v is not None else None for v in r)))
                    for r in cur.fetchall()}
    finally:
        c.close()


def main():
    queries = {qid: q for qid, q in common.load_queries().items() if q['kind'] == 'normal'}
    qrels = {}
    for r in common.read_jsonl(common.QRELS):
        qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
    notices = load_notices()
    systems = ev.Systems()

    per = []
    reasons = Counter()
    examples = []
    for qid, q in queries.items():
        payload = q['payload']
        as_of = date.fromisoformat(q['as_of_date'])
        months = gate.business_age_months(payload.get('founded_at') or '', as_of)
        top3 = [n for n, _ in systems.run(SYSTEM, q, k=3)]
        rels = qrels.get(qid, {})
        row = Counter()
        for nid in top3:
            notice = notices.get(nid)
            if notice is None:
                continue
            verdicts = {c['조건']: c['판정'] for c in gate.judge(notice, months, as_of)['checks']}
            age = verdicts['업력']
            row['age_no'] += age is False
            row['age_unknown'] += age is None
            row['period_no'] += verdicts['접수기간'] is False or verdicts['모집 상태'] is False
            blocked = any(v is False for v in verdicts.values())
            row['blocked'] += blocked
            row['ok_rec'] += (not blocked) and rels.get(nid) == 2
            if blocked:
                reasons[' · '.join(k for k, v in verdicts.items() if v is False)] += 1
                if age is False and len(examples) < 5:
                    examples.append((qid, '%s (내 업력 %s)' % (
                        notice.get('age_condition_raw'),
                        '예비창업자' if months is None else '%d년' % (months // 12)), nid))
        per.append({k: row[k] / 3 for k in
                    ('age_no', 'age_unknown', 'period_no', 'blocked', 'ok_rec')})

    n = len(per)
    mean = lambda k: sum(r[k] for r in per) / n
    print('정상 %d질의 · 검색 %s · 상위 3칸 %d개' % (n, SYSTEM, n * 3))
    print('\n%-16s %s' % ('업력 불가칸', '%.3f' % mean('age_no')))
    print('%-16s %s' % ('업력 모름칸', '%.3f' % mean('age_unknown')))
    print('%-16s %s' % ('기간·상태 불가칸', '%.3f' % mean('period_no')))
    print('%-16s %s' % ('자격 불가칸(합계)', '%.3f' % mean('blocked')))
    print('%-16s %s' % ('쓸모칸(2)', '%.3f' % mean('ok_rec')))
    if reasons:
        print('\n불가 사유별 칸 수')
        for why, cnt in reasons.most_common():
            print('  %-20s %d' % (why, cnt))
    if examples:
        print('\n업력으로 막힌 예')
        for qid, why, nid in examples:
            print('  %s  %s  %s' % (qid, why, nid))
    return 0


if __name__ == '__main__':
    sys.exit(main())
