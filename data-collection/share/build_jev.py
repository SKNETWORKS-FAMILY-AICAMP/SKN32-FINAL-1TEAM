# -*- coding: utf-8 -*-
"""Jev 채점 시험 공유 페이지(Jev채점시험.html)를 만든다.

  .\\.venv\\Scripts\\python.exe -X utf8 share\\build_jev.py   (data-collection 에서)

- 저장소 파일은 읽기만 한다(DB·Jev·LLM 호출 없음).
- 데이터: experiments.sql_semantic.jev_probe_results.load_run(RUN) — 원래 8010 /jev-probe 화면과 같은 함수.
- 수치는 쌍 목록에서 다시 계산하고 summary.json · WORKLOG 문서 값과 대조해 출력한다.
- 틀(jev_template.html)의 /*DATA*/null 자리에 JSON 을 넣어 저장한다.
"""
import io
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # data-collection (이 스크립트는 data-collection/share/ 에 있다)
RUN = 'jev_judge_probe_20260928T110603Z'   # 본 실행(143쌍). …T110547Z 는 5쌍 형식 확인용이라 쓰지 않는다
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'jev_template.html')
OUT = os.path.join(HERE, 'Jev채점시험.html')

os.chdir(ROOT)
sys.path.insert(0, ROOT)
from experiments.sql_semantic import jev_probe_results as J  # noqa: E402

TRUST = {'exact': 0.70, 'kappa': 0.60, 'swap02': 0.03}   # eval/merge_qrels.TRUST (잠정 기준)
BIN_NAMES = [b for _lo, b in J.BINS]


def qwk(pairs, k=3):
    """이차 가중 카파(eval/merge_qrels.weighted_kappa 와 같은 식을 다시 씀)."""
    n = len(pairs)
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        obs[a][b] += 1
    ra = [sum(obs[i]) for i in range(k)]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = lambda i, j: (i - j) ** 2 / (k - 1) ** 2
    po = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w(i, j) * ra[i] * rb[j] for i in range(k) for j in range(k)) / n / n
    return None if pe == 0 else 1 - po / pe


def metrics(pairs):
    n = len(pairs)
    if not n:
        return None
    c = Counter(pairs)
    return {'n': n,
            'exact': sum(a == b for a, b in pairs) / n,
            'kappa': qwk(pairs),
            'swap02': sum({a, b} == {0, 2} for a, b in pairs) / n,
            'binary': sum((a >= 1) == (b >= 1) for a, b in pairs) / n,
            'conf': [[c.get((h, x), 0) for x in range(3)] for h in range(3)]}   # conf[사람][채점기]


def idea_of(persona):
    for line in (persona or '').splitlines():
        if line.startswith('사업 아이디어:'):
            return line.split(':', 1)[1].strip()
    return ''


def main():
    d = J.load_run(RUN)
    assert d and d['run'] == RUN, 'run not found'
    s = d['summary']
    P = [p for p in d['pairs'] if p['human'] is not None]
    assert len(P) == len(d['pairs']) == 143, len(d['pairs'])
    assert all(isinstance(p['jev'], int) and p['llm'] is not None for p in P)

    jev = metrics([(p['human'], p['jev']) for p in P])
    llm = metrics([(p['human'], p['llm']) for p in P])
    by_bin = []
    for b in BIN_NAMES:
        ps = [p for p in P if p['bin'] == b]
        by_bin.append({'name': b, 'jev': metrics([(p['human'], p['jev']) for p in ps]),
                       'llm': metrics([(p['human'], p['llm']) for p in ps])})
    dist = {k: [sum(p[k] == v for p in P) for v in range(3)] for k in ('human', 'jev', 'llm')}
    same = [p for p in P if p['jev'] == p['llm']]
    same_exact = sum(p['jev'] == p['human'] for p in same) / len(same)
    groups = Counter()
    for p in P:
        jr, lr = p['jev'] == p['human'], p['llm'] == p['human']
        groups['jev_only_wrong' if (not jr and lr) else 'jev_only_right' if (jr and not lr)
               else 'both_wrong' if (not jr and not lr) else 'both_right'] += 1

    # 사람 기준값 중 재확인으로 바뀐 쌍 수(파일만 읽음)
    sys.path.insert(0, os.path.join(ROOT, 'eval'))
    import common
    import jev_judge_probe
    with_re, blind = jev_judge_probe.blind_truth(common.read_jsonl(common.HUMAN))
    keys = [(p['qid'], p['notice_id']) for p in P]
    rechecked = sum(with_re.get(k) != blind.get(k) for k in keys)
    assert all(with_re.get((p['qid'], p['notice_id'])) == p['human'] for p in P)   # 페이지 정답 = 재확인 반영 값
    blind_only = metrics([(blind[(p['qid'], p['notice_id'])], p['jev']) for p in P])

    # ---- 대조: 다시 계산한 값 vs summary.json vs 문서(WORKLOG 2026-09-28 Jev 항목) ----
    sj, sl = s['same_pairs']['jev'], s['same_pairs']['llm_gpt41mini_A']
    checks = [
        ('정확 일치 Jev', jev['exact'], sj['exact'], 0.52),
        ('정확 일치 LLM', llm['exact'], sl['exact'], 0.64),
        ('가중 카파 Jev', jev['kappa'], sj['kappa'], 0.47),
        ('가중 카파 LLM', llm['kappa'], sl['kappa'], 0.62),
        ('0↔2 뒤바뀜 Jev', jev['swap02'], sj['swap02'], 0.077),
        ('0↔2 뒤바뀜 LLM', llm['swap02'], sl['swap02'], 0.070),
        ('관련 여부 일치 Jev', jev['binary'], sj['binary'], None),
        ('관련 여부 일치 LLM', llm['binary'], sl['binary'], None),
        ('확신 0.9↑ 쌍 수', by_bin[0]['jev']['n'], s['jev_by_confidence'][BIN_NAMES[0]]['n'], 25),
        ('확신 0.9↑ Jev', by_bin[0]['jev']['exact'], s['jev_by_confidence'][BIN_NAMES[0]]['exact'], 0.84),
        ('확신 0.9↑ LLM', by_bin[0]['llm']['exact'], d['by_bin'][BIN_NAMES[0]]['llm']['exact'], 0.80),
        ('확신 0.7~0.9 Jev', by_bin[1]['jev']['exact'], s['jev_by_confidence'][BIN_NAMES[1]]['exact'], 0.61),
        ('확신 0.7 미만 Jev', by_bin[2]['jev']['exact'], s['jev_by_confidence'][BIN_NAMES[2]]['exact'], 0.40),
        ('Jev가 1을 준 횟수', dist['jev'][1], None, 59),
        ('사람이 1을 준 횟수', dist['human'][1], None, 36),
        ('사람2→Jev1', jev['conf'][2][1], s['same_pairs']['jev']['confusion'].get('2>1'), 23),
        ('Jev=LLM 쌍 수', len(same), None, 97),
        ('Jev=LLM 쌍 사람 일치', same_exact, None, 0.66),
        ('처음 점수 기준 Jev', blind_only['exact'], s['jev_vs_human_blind_only']['exact'], 0.44),
        ('Jev만 틀림', groups['jev_only_wrong'], None, 28),
        ('Jev만 맞음', groups['jev_only_right'], None, 11),
        ('둘 다 틀림', groups['both_wrong'], None, 40),
    ]
    for name, mine, summ, doc in checks:
        ok_s = summ is None or abs(mine - summ) < 1e-9
        tol = 0.0051 if isinstance(doc, float) and doc < 1 else 0.5
        if name.startswith('0↔2'):
            tol = 0.00051
        ok_d = doc is None or abs(mine - doc) < tol
        print('%-18s 재계산 %-8s summary %-8s 문서 %-6s %s' % (
            name, round(mine, 4), '-' if summ is None else round(summ, 4), '-' if doc is None else doc,
            'OK' if ok_s and ok_d else '** 다름 **'))
    # confusion 전체 대조
    for key, mine in (('jev', jev), ('llm_gpt41mini_A', llm)):
        cs = s['same_pairs'][key]['confusion']
        assert all(mine['conf'][h][x] == cs.get('%d>%d' % (h, x), 0) for h in range(3) for x in range(3)), key
    print('혼동표 Jev·LLM: summary.json 과 같음')
    print('질의 수', len(set(p['qid'] for p in P)), '· 재확인으로 사람 값이 바뀐 쌍', rechecked,
          '· 사람 메모 있는 쌍', sum(bool(p['human_reason']) for p in P))

    # ---- 페이지 데이터(짧은 키) ----
    queries = {}
    for p in P:
        queries.setdefault(p['qid'], p['persona'])
    pairs = []
    for p in P:
        pr = p['jev_probs'] or {}
        row = {'q': p['qid'], 'id': p['notice_id'], 't': p['title'], 'u': p['url'],
               'h': p['human'], 'j': p['jev'], 'c': p['jev_conf'],
               'p': [pr.get('2', 0), pr.get('1', 0), pr.get('0', 0), pr.get('unknown', 0)],
               'l': p['llm'], 'lr': p['llm_reason'], 'b': BIN_NAMES.index(p['bin'])}
        if p['human_reason']:
            row['hr'] = p['human_reason']
        pairs.append(row)
    m = s['meta']
    data = {
        'meta': {'run': RUN, 'run_at': m['run_at'], 'pairs': m['pairs'], 'answered': m['answered'],
                 'errors': m['errors'], 'model': ', '.join(m['models']), 'median_ms': m['median_ms'],
                 'queries': len(queries), 'rechecked': rechecked},
        'trust': TRUST,
        'jev': {k: v for k, v in jev.items()}, 'llm': {k: v for k, v in llm.items()},
        'bins': [{'name': b['name'], 'n': b['jev']['n'], 'jev': b['jev']['exact'], 'llm': b['llm']['exact']} for b in by_bin],
        'dist': dist, 'same': {'n': len(same), 'exact': same_exact},
        'blind_only_exact': blind_only['exact'],
        'groups': dict(groups), 'queries': queries, 'pairs': pairs,
    }
    js = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    with io.open(TEMPLATE, encoding='utf-8') as f:
        tpl = f.read()
    assert tpl.count('/*DATA*/null') == 1
    html = tpl.replace('/*DATA*/null', js)
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    print('저장', OUT, len(html.encode('utf-8')), 'bytes')


if __name__ == '__main__':
    main()
