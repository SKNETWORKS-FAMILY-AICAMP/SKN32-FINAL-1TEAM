# -*- coding: utf-8 -*-
"""10/7 06:20 판과 이번 판을 기능별·파일별·시험별로 비교해 compare_prev.md 를 만든다.

  python compare_prev.py <이전 폴더> <이번 폴더>
"""
import collections
import io
import json
import os
import sys


def load(folder):
    with open(os.path.join(folder, 'coverage_summary.json'), encoding='utf-8') as f:
        s = json.load(f)
    with open(os.path.join(folder, 'tests.json'), encoding='utf-8') as f:
        t = json.load(f)
    return s, t


def main(prev, cur):
    ps, pt = load(prev)
    cs, ct = load(cur)
    lines = ['# 이전 판과 비교', '',
             '- 이전: `%s` (%s)' % (os.path.basename(prev.rstrip('\\/')), ps['run']['started_at']),
             '- 이번: `%s` (%s)' % (os.path.basename(cur.rstrip('\\/')), cs['run']['started_at']), '',
             '| 항목 | 이전 | 이번 |', '|---|---|---|',
             '| 전체 시험 | %d | %d |' % (ps['run']['total'], cs['run']['total']),
             '| 통과·건너뜀·실패 | %d·%d·%d | %d·%d·%d |' % (
                 ps['run']['total'] - ps['run']['skipped'] - ps['run']['failures'] - ps['run']['errors'],
                 ps['run']['skipped'], ps['run']['failures'] + ps['run']['errors'],
                 cs['run']['total'] - cs['run']['skipped'] - cs['run']['failures'] - cs['run']['errors'],
                 cs['run']['skipped'], cs['run']['failures'] + cs['run']['errors']),
             '| 범위 안 줄 | %d | %d |' % (ps['scope_coverage']['statements'], cs['scope_coverage']['statements']),
             '| 범위 커버리지 | %.1f%% | %.1f%% |' % (ps['scope_coverage']['percent'], cs['scope_coverage']['percent']),
             '', '## 기능별', '', '| 기능 | 시험 이전→이번 | 커버리지 이전→이번 |', '|---|---|---|']
    pf = {f['feature']: f for f in ps['features']}
    for f in cs['features']:
        p = pf.get(f['feature'], {})
        lines.append('| %s %s | %s → %d | %s → %.1f%% |' % (
            f['feature'], f['name'], p.get('tests', '-'), f['tests'],
            ('%.1f%%' % p['percent']) if p else '-', f['percent']))

    lines += ['', '## 바뀐 파일(줄 수 또는 커버리지가 달라진 것)', '',
              '| 파일 | 줄 이전→이번 | 실행 이전→이번 | 커버리지 이전→이번 |', '|---|---|---|---|']
    pfile = {f['file']: f for f in ps['files']}
    for f in cs['files']:
        p = pfile.get(f['file'])
        if p and (p['statements'], p['covered']) == (f['statements'], f['covered']):
            continue
        lines.append('| %s | %s → %d | %s → %d | %s → %.1f%% |' % (
            f['file'], p['statements'] if p else '-', f['statements'],
            p['covered'] if p else '-', f['covered'],
            ('%.1f%%' % p['percent']) if p else '-', f['percent']))

    pid = {r['id'] for r in pt['tests']}
    cid = {r['id'] for r in ct['tests']}
    added = collections.Counter()
    for r in ct['tests']:
        if r['id'] not in pid:
            added[(r.get('feature') or '범위 밖', r['id'].split('.')[1] if r['id'].startswith('tests.') else r['id'].split('.')[0])] += 1
    removed = sorted(pid - cid)
    lines += ['', '## 새로 생긴 시험 (%d개)' % sum(added.values()), '', '| 기능 | 시험 파일 | 개수 |', '|---|---|---|']
    for (feat, mod), n in sorted(added.items()):
        lines.append('| %s | %s | %d |' % (feat, mod, n))
    lines += ['', '## 없어진 시험 (%d개)' % len(removed), '']
    lines += ['- `%s`' % r for r in removed] or ['- 없음']

    out = os.path.join(cur, 'compare_prev.md')
    with io.open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
