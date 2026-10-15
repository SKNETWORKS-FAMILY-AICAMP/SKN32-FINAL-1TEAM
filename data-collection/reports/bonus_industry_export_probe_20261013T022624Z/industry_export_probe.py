# -*- coding: utf-8 -*-
"""가산점 넓히기 1단계 — 열린 공고의 업종·수출 가점 항목이 몇 개이고, 신청자가 해당한다고 가정하면 지금 규칙을 통과하는지,
공고 단위 가산점이 어떻게 바뀌는지 계산만 한다. 공용 DB SELECT 만, 저장소 코드는 그대로(계산 중에만 _base_hit 을 감싼다)."""
import collections
import json
import os
import sys
from datetime import date

ROOT = r'C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection'
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from collect.extract_bonus import EXTRACTOR_VERSION  # noqa: E402
from eval.bonus_conservative_compare import APPLICANTS, applicant, open_ids  # noqa: E402
from search import bonus, content_version  # noqa: E402
from shared import store_mysql  # noqa: E402

KINDS = ('업종', '수출')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'industry_export_probe.json')

conn = store_mysql.connect()
try:
    versions = content_version.load(conn)
    table = bonus.load(conn, versions=versions, extractor_version=EXTRACTOR_VERSION)
    ids = open_ids(conn, date.today())
    with conn.cursor() as cur:
        cur.execute('SELECT notice_id, title FROM notices WHERE notice_id IN (%s)' % ','.join(['%s'] * len(ids)), list(ids))
        titles = dict(cur.fetchall())
finally:
    conn.close()

open_found = [n for n in ids if (table.get(n) or {}).get('status') == 'found']
print('열린 공고 %d건 · 가점 찾음(found) %d건' % (len(ids), len(open_found)))

# ── 항목 단위: 해당(True)이라고 가정하면 어디서 막히나 ──────────────────
orig = bonus._base_hit


def reason(item):
    """해당이라고 가정했을 때 처음 막히는 곳(item_hit 순서와 같게)."""
    if item.get('in_document') is False:
        return '원문에 근거 없음'
    if item.get('_memo_blocked'):
        return '불확실 메모'
    text = bonus._drop_benign_phrases(bonus._text(item), item)
    extra = item.get('extra_conditions')
    if extra and not bonus.benign_extra_strict(extra, item):
        return 'AI가 채운 추가 조건'
    if bonus.FUTURE_WORDS.search(text):
        return '앞으로의 조건'
    if bonus.condition_words_hit(text, item, None):
        return '확인할 수 없는 조건 말'
    if item.get('points') is None:
        return '점수 없음(우대만)'
    if not bonus.points_supported(item):
        return '점수를 근거에서 확인 못 함'
    bonus._base_hit = lambda it, req: True
    try:
        hit = bonus.item_hit(item, applicant())
    finally:
        bonus._base_hit = orig
    return '규칙 통과' if hit is True else '그 밖 규칙(결합·점수 주인 등)'


rows = []
for nid in open_found:
    entry = table[nid]
    memo_global = bool(entry.get('uncertain')) and not entry.get('memo_partial')
    for it in entry['items']:
        if it.get('kind') in KINDS:
            rows.append({'notice_id': nid, 'title': titles.get(nid, '')[:60], 'kind': it['kind'], 'name': it.get('name'),
                         'points': it.get('points'), 'group': it.get('group'), 'program': it.get('program'),
                         'extra': it.get('extra_conditions'), 'detail': it.get('detail'),
                         'quote': str(it.get('quote') or '')[:200], 'reason': reason(it)})

by_kind = collections.Counter(r['kind'] for r in rows)
print('\n업종·수출 항목: %s · 공고 %d건' % (dict(by_kind), len({r['notice_id'] for r in rows})))
for kind in KINDS:
    c = collections.Counter(r['reason'] for r in rows if r['kind'] == kind)
    print('  %s 항목이 막히는 곳: %s' % (kind, dict(c.most_common())))

# ── 공고 단위: 업종·수출을 모두 해당(True) / 모두 해당 아님(False)으로 두면 ──────────
def scores(force):
    def patched(item, req):
        if item.get('kind') in KINDS:
            return force
        return orig(item, req)
    bonus._base_hit = patched
    try:
        return {label: {n: bonus.score(table[n], applicant(**kw))[0] for n in open_found} for label, kw in APPLICANTS.items()}
    finally:
        bonus._base_hit = orig


def bucket(v):
    return 'null' if v is None else ('0' if v == 0 else '양수')


base = {label: {n: bonus.score(table[n], applicant(**kw))[0] for n in open_found} for label, kw in APPLICANTS.items()}
moves = {}
for force in (True, False):
    after = scores(force)
    for label in APPLICANTS:
        c = collections.Counter()
        changed = []
        for n in open_found:
            b, a = base[label][n], after[label][n]
            if b != a:
                c['%s→%s' % (bucket(b), bucket(a))] += 1
                changed.append({'notice_id': n, 'before': b, 'after': a, 'title': titles.get(n, '')[:50]})
        moves['%s · %s' % ('모두 해당' if force else '모두 해당 아님', label)] = {'counts': dict(c), 'changed': changed}
        print('%-8s %-32s 바뀐 공고 %s' % ('모두 해당' if force else '모두 해당아님', label, dict(c) or '없음'))

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'open': len(ids), 'open_found': len(open_found), 'items': rows, 'moves': moves},
              f, ensure_ascii=False, indent=1)
print('\n저장', OUT)
print('\n== 규칙 통과 항목 ==')
for r in rows:
    if r['reason'] == '규칙 통과':
        print('-', r['kind'], r['notice_id'][-6:], r['points'], '|', r['name'], '|', r['quote'][:90], '|', r['title'][:30])
