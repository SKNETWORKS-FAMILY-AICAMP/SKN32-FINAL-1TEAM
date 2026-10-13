# -*- coding: utf-8 -*-
"""개인사업자·법인 '강한 불가' 걸러내기(결정 0021) 2단계 확인 — 새 코드로 boot() 한 뒤
  A. 공고 전체 × 신청자 6가지: 추천 정형 필터(마감 제외)와 조율용 자격 판정(notice_api.judge)의 결론이 같은가(10/6 13,825회와 같은 방식)
  B. 평가 정상 질의 58개 × 개인사업자·법인 상위 20 — 1단계(entity_block_probe)와 같은 조건으로 '강한 불가' 공고가 뜨는가
  C. 열린 공고에서 실제로 빠지는 수 · 확인 필요로 낮춘 수 · 공고 상세 허용 유형 분포
공용 DB SELECT 만, OpenAI 호출 없음."""
import collections
import json
import os
import sys
from datetime import date
from types import SimpleNamespace

ROOT = r'C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection'
sys.path.insert(0, ROOT)
os.chdir(ROOT)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'entity_block_after.json')

from search import app, applicant_types as types_mod, gate, notice_api  # noqa: E402

app.boot()
print('boot_errors', list(app.STATE['boot_errors']))
table = app.STATE.get('applicant_types') or {}
print('판정표:', table.get('note'))
rows = app.STATE['rows']
today = date.today()

# ── A. 결론 대조 ───────────────────────────────────────────
CASES = [('예비창업자', ''), ('개인사업자', '2024-03-02'), ('법인', '2016-01-01'),
         ('개인사업자', '2026-09-01'), ('법인', '2019-10-07'), ('개인사업자', '')]
diff, n = [], 0
for nid, row in rows.items():
    for kind, founded in CASES:
        age = gate.applicant_age(kind, founded, today)
        keep, _why, _ = app.eligible_with_types(nid, row, age, today, False, table, kind)
        body = SimpleNamespace(applicant_type=kind, founded_at=founded, today=today.isoformat())
        passed = notice_api.judge(row, nid, body, table)['passed']
        n += 1
        if keep != passed:
            diff.append((nid, kind, founded, keep, passed))
print('\nA. 결론 대조: %d회 중 다름 %d건' % (n, len(diff)), diff[:5])

# ── C. 열린 공고에서 빠지는 수 ─────────────────────────────────
open_ids = [nid for nid, row in rows.items() if gate.prefilter(row, gate.UNKNOWN_AGE, today)[0]]
blocked = {k: [nid for nid in open_ids if types_mod.entity(table, nid, k) == 'blocked'] for k in ('개인사업자', '법인')}
notices = table.get('notices') or {}
strong = {k: [nid for nid in open_ids if notices.get(nid) and types_mod._strong_no(notices[nid], types_mod.entity_key(k))]
          for k in ('개인사업자', '법인')}
print('\nC. 열린 공고(사업자 업력 모름 기준) %d건' % len(open_ids))
for k in ('개인사업자', '법인'):
    key = types_mod.entity_key(k)
    down = [nid for nid in strong[k] if nid not in blocked[k]]
    print('  %s: 강한 불가 %d → 실제로 뺌 %d · 확인 필요로 낮춤 %d %s' % (
        k, len(strong[k]), len(blocked[k]), len(down),
        [(nid[-6:], 'unread' if notices[nid].get('unread_' + key) else 'unverified') for nid in down]))
dist = collections.Counter(tuple(notice_api.allowed_types(rows[nid], nid, table)) for nid in open_ids)
print('  공고 상세 허용 유형 분포:', dict(dist))

# ── B. 상위 20 ────────────────────────────────────────────
before = json.load(open(r'reports/entity_block_probe_20261013T030233Z/entity_block_probe.json', encoding='utf-8'))
strong_any = {'개인사업자': set(before['blocked']['sole_proprietor']), '법인': set(before['blocked']['corporation'])}
queries = [json.loads(l) for l in open('eval/queries.jsonl', encoding='utf-8')]
queries = [q for q in queries if q.get('kind') == 'normal']
stats = {k: collections.Counter() for k in strong_any}
left = []
for q in queries:
    for kind in strong_any:
        payload = dict(q['payload'], applicant_type=kind)
        if not payload.get('founded_at'):
            payload['founded_at'] = '2022-01-01'
        out = app.match(app.MatchRequest(**dict(payload, top=20)))
        ids = [r['notice_id'] for r in out['results'][:20]]
        for k in (3, 10, 20):
            hit = [x for x in ids[:k] if x in strong_any[kind]]
            stats[kind]['질의_상위%d에_있음' % k] += bool(hit)
            stats[kind]['칸_상위%d' % k] += len(hit)
        for i, x in enumerate(ids, 1):
            if x in strong_any[kind]:
                left.append({'qid': q['qid'], 'type': kind, 'rank': i, 'notice_id': x})
        stats[kind]['정형필터_뺌_합'] += out['applicant_types']['blocked']
print('\nB. 질의 %d개 × 개인사업자·법인 · 상위 20 (1단계 강한 불가 목록 기준)' % len(queries))
for kind in strong_any:
    print('  %s 전 %s' % (kind, {k: v for k, v in before['stats'][kind].items() if '안전장치' not in k}))
    print('  %s 후 %s' % (kind, dict(stats[kind])))
print('  남은 것:', left)

json.dump({'consistency': {'checks': n, 'diff': diff}, 'open': len(open_ids),
           'blocked': {k: v for k, v in blocked.items()}, 'strong': strong,
           'detail_dist': {'|'.join(k): v for k, v in dist.items()},
           'top20_after': {k: dict(v) for k, v in stats.items()}, 'left': left,
           'table_note': table.get('note')}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('저장', OUT)
