# -*- coding: utf-8 -*-
"""업종추출결과.html 에 넣을 데이터를 만든다 (파일만 읽음 · DB·LLM·유료 API 호출 없음).

실행(data-collection 폴더에서):
  .venv/Scripts/python.exe -X utf8 <이 파일 경로>

- 주 데이터: industry_results.default_run() (서비스가 읽는 final5)
- 비교용 요약: industry_llm_full_luna_20260928_final6 (있으면)
- 순위에 쓸 수 있는지: search.industry_rank.usable_sections (서비스와 같은 규칙)
- Codex 블라인드 판정(밀린 공고 34건): reports/label_pack_20260928/industry_*.jsonl
같은 폴더의 업종추출결과.html 안 /*DATA*/ … /*END*/ 사이를 바꿔 쓴다.
"""
import io
import json
import os
import re
import sys
from collections import Counter

DC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # data-collection (이 스크립트는 data-collection/share/ 에 있다)
sys.path.insert(0, DC)
os.chdir(DC)

from experiments.sql_semantic import industry_results as ir, industry_groups  # noqa: E402
from search import industry_rank as rk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '업종추출결과.html')
COMPARE = 'industry_llm_full_luna_20260928_final6'
ISTATUS = ['known', 'not_mentioned', 'excluded_only', 'no_limit', 'conditional', 'unknown']
# 순위에 못 쓰는 이유 (industry_rank.usable_sections 의 검사 순서와 같게)
WHY = ['incomplete', 'truncated', 'scope', 'branch', 'field']
KSIC = set('ABCDEFGHIJKLMNOPQRSTU')   # 표준 대분류만. X(분야·정책 범주)·ALL·? 는 따로


def raw_rows(name):
    path = os.path.join(ir.REPORTS, name, 'results.jsonl')
    out = {}
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                out[d['notice_id']] = d.get('llm') or {}
    return out


def rank_info(llm):
    """(순위에 쓸 대분류 목록 또는 None, 못 쓰는 이유 코드 또는 None). 업종 제한 있음이 아니면 이유 None."""
    if llm.get('industry_status') != 'known':
        return None, None
    if not llm.get('list_complete'):
        return None, 'incomplete'
    if llm.get('truncated'):
        return None, 'truncated'
    if llm.get('scope_unresolved'):
        return None, 'scope'
    if rk.branch_problem(llm):
        return None, 'branch'
    sec = industry_groups.allowed_sections([a.get('text') for a in llm.get('allowed') or []])
    if not sec:
        return None, 'field'
    assert rk.usable_sections(llm) == sec
    return sorted(sec), None


def summarize(name):
    d = ir.load_run(name)
    raw = raw_rows(name)
    rows = d['rows']
    usable = reasons = 0
    why = Counter()
    for r in rows:
        sec, w = rank_info(raw[r['id']])
        if sec:
            usable += 1
        if w:
            why[w] += 1
    table = rk.load(os.path.join(ir.REPORTS, name, 'results.jsonl'))
    assert len(table['notices']) == usable, (name, len(table['notices']), usable)
    return d, raw, {
        'run': name, 'total': len(rows),
        'istatus': {k: sum(1 for r in rows if r['istatus'] == k) for k in ISTATUS},
        'usable': usable, 'why': {k: why.get(k, 0) for k in WHY},
        'truncated': sum(1 for r in rows if r['truncated']),
        'scope': sum(1 for r in rows if r['scope_unresolved']),
        'known_trunc': sum(1 for r in rows if r['truncated'] and r['istatus'] == 'known'),
        'known_scope': sum(1 for r in rows if r['scope_unresolved'] and r['istatus'] == 'known'),
        'with_excluded': sum(1 for r in rows if r['excluded']),
        'run_at': d['meta'].get('run_at'), 'engine': d['meta'].get('engine'),
        'source_cost_usd': d['meta'].get('source_cost_usd'),
    }


def codex_marks():
    pack = os.path.join(ir.REPORTS, 'label_pack_20260928')
    items = {}
    with io.open(os.path.join(pack, 'industry_items.jsonl'), encoding='utf-8') as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                items[d['item_id']] = d['notice_id']
    marks = {}
    pairs = Counter()
    with io.open(os.path.join(pack, 'industry_labels.jsonl'), encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            nid = items[d['item_id']]
            ok = [s['code'] for s in d['sections'] if s['verdict'] == 'eligible']
            for s in d['sections']:
                pairs[s['verdict']] += 1
            m = marks.setdefault(nid, {'item': d['item_id'], 'ok': []})
            m['ok'] = sorted(set(m['ok']) | set(ok))
    return marks, pairs, len(items)


def main():
    name = ir.default_run()
    d, raw, s_main = summarize(name)
    compare = None
    if ir.run_path(COMPARE):
        compare = summarize(COMPARE)[2]
    marks, pairs, n_items = codex_marks()

    rows = d['rows']
    ex_count = Counter(t for r in rows for t in r['excluded'] if t)
    ex_list = [t for t, _ in ex_count.most_common()]
    ex_idx = {t: i for i, t in enumerate(ex_list)}

    known_rows = [r for r in rows if r['istatus'] == 'known']
    sec_known = Counter(c for r in known_rows for c in r['groups'])
    sec_usable = Counter()
    packed = []
    for r in rows:
        sec, why = rank_info(raw[r['id']])
        for c in sec or []:
            sec_usable[c] += 1
        flags = (1 if r['truncated'] else 0) | (2 if r['scope_unresolved'] else 0) | \
                (4 if r['complete'] else 0) | (8 if r['downgraded'] else 0)
        mk = marks.get(r['id'])
        packed.append([
            r['id'], r['title'], ISTATUS.index(r['istatus'] or 'unknown'),
            [a['text'] for a in r['allowed'] if a['text']],
            [ex_idx[t] for t in r['excluded'] if t],
            r['quote'], ''.join(sorted(c for c in r['groups'] if c in KSIC)),
            ''.join(sec) if sec else '', WHY.index(why) + 1 if why else 0, flags,
            (mk['item'] + ':' + ''.join(mk['ok'])) if mk else '', r['category'],
        ])

    missing = [nid for nid in marks if nid not in raw]
    sections = [(c, industry_groups.NAMES.get(c, c), n, sec_usable.get(c, 0))
                for c, n in sec_known.most_common() if c in KSIC]
    other_groups = [(c, industry_groups.NAMES.get(c, c), n) for c, n in sec_known.most_common()
                    if c not in KSIC]
    data = {
        'main': s_main, 'compare': compare,
        'meta': {k: d['meta'].get(k) for k in ('engine', 'prompt', 'profile', 'run_at', 'source_cost_usd',
                                               'db_writes', 'failures')},
        'merge': [{'n': h['override_count'], 'chars': h['override_max_chars']}
                  for h in d['meta'].get('merge_history') or []],
        'sections': sections, 'other_groups': other_groups,
        'known_with_group': sum(1 for r in known_rows if any(c in KSIC for c in r['groups'])),
        'known_total': len(known_rows),
        'sec_names': {c: n for c, n in industry_groups.NAMES.items() if c in KSIC},
        'ex': ex_list, 'ex_top': ex_count.most_common(10),
        'codex': {'items': n_items, 'notices': len(marks), 'flagged': sum(1 for m in marks.values() if m['ok']),
                  'pairs': dict(pairs), 'missing_in_run': missing},
        'rows': packed,
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    with io.open(OUT, encoding='utf-8') as f:
        html = f.read()
    new, n = re.subn(r'/\*DATA\*/.*?/\*END\*/', lambda m: '/*DATA*/' + blob + '/*END*/', html, flags=re.S)
    assert n == 1, n
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new)
    print('run', name, 'rows', len(rows), 'data bytes', len(blob.encode('utf-8')),
          'page bytes', len(new.encode('utf-8')))
    print(json.dumps({k: v for k, v in data.items() if k not in ('rows', 'ex', 'sec_names')},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
