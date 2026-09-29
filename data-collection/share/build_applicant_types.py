# -*- coding: utf-8 -*-
"""8010 '신청자 유형' 화면을 서버 없는 공유 페이지(신청자유형.html)로 만든다 (2026-09-29).

읽기만 한다: reports/applicant_type_llm_* 의 results.jsonl·meta.json (applicant_type_results.load_run)
서비스 판정은 search/applicant_types.py 의 _info()·pre_founder() 를 그대로 불러 계산한다. DB·LLM 호출 없음.

실행(data-collection 폴더에서):
  .venv/Scripts/python.exe -X utf8 <이 파일 경로>
템플릿 applicant_types.template.html 의 /*DATA*/null 자리에 데이터를 넣어 신청자유형.html 을 쓴다.
"""
import io
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)   # data-collection (이 스크립트는 data-collection/share/ 에 있다)
sys.path.insert(0, REPO)
os.chdir(REPO)

from experiments.sql_semantic import applicant_type_results as atr  # noqa: E402
from search import applicant_types as types_mod  # noqa: E402

TYPES = atr.TYPES
ST = {'allowed': 'a', 'not_allowed': 'n', 'implied_no': 'i', 'not_mentioned': 'm'}
SVC = {'blocked': 'x', 'allowed': 'a', 'implied_no': 'd', None: '-'}


def service_verdict(r):
    """서비스가 예비창업자 신청자에게 쓰는 결론 — search/applicant_types.pre_founder() 그대로."""
    llm = {'varies': r['varies']}
    for t in TYPES:
        llm[t] = {k: r['types'][t][k] for k in ('status', 'strength', 'evidence')}
    info = types_mod._info(llm)
    table = {'notices': {r['id']: info}}
    return types_mod.pre_founder(table, r['id']), info.get('registered_only')


def build():
    run = atr.default_run()
    d = atr.load_run(run)
    pool, index = [''], {'': 0}

    def p(s):
        s = s or ''
        if s not in index:
            index[s] = len(pool)
            pool.append(s)
        return index[s]

    rows = []
    for r in d['rows']:
        verdict, reg = service_verdict(r)
        svc = SVC[verdict]
        if verdict == 'allowed' and r['api_pre'] is False:
            svc = 'r'   # API 업력 칸은 예비창업자 불가인데 본문이 가능 → 되살림 (search/app.py eligible_with_types)
        codes = ('b' if r['source'] == 'bizinfo' else 'k')
        for t in TYPES:
            c = r['types'][t]
            codes += ST[c['status']] + {'strong': 's', 'weak': 'w'}.get(c['strength'], '-')
        codes += '1' if r['varies'] else '0'
        codes += {True: '1', False: '0', None: '-'}[r['api_pre']]
        codes += svc
        drops = [[i, ST.get(r['types'][t]['raw_status'], 'm'), p(r['types'][t]['dropped'])]
                 for i, t in enumerate(TYPES) if r['types'][t]['dropped']]
        row = [r['id'].split(':', 1)[1], r['title'], codes, p(r['target_category']), p(r['age_condition_raw']),
               p(r['types']['pre_founder']['evidence']), p(r['types']['sole_proprietor']['evidence']),
               p(r['types']['corporation']['evidence']), r['reason'] or '', drops or 0,
               p(reg['phrase']) if reg else 0]
        while row and row[-1] in (0, ''):   # 끝의 빈 칸은 뺀다(크기 절약)
            row.pop()
        rows.append(row)

    m = d['meta']
    data = {
        'meta': {'run': run, 'run_at': m['run_at'], 'engine': m['engine'], 'n': m['n'],
                 'n_bizinfo': m['n_bizinfo'], 'n_kstartup': m['n_kstartup'], 'failures': m['failures'],
                 'cost_usd': m['cost_usd']},
        'pool': pool, 'rows': rows,
    }
    return d, data


def main():
    d, data = build()
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    with io.open(os.path.join(HERE, 'applicant_types.template.html'), encoding='utf-8') as f:
        tpl = f.read()
    assert tpl.count('/*DATA*/null') == 1
    out = tpl.replace('/*DATA*/null', blob)
    path = os.path.join(HERE, '신청자유형.html')
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(out)
    svc = Counter(r[2][-1] for r in data['rows'])
    print('rows', len(data['rows']), 'pool', len(data['pool']), 'data bytes', len(blob.encode('utf-8')),
          'page bytes', os.path.getsize(path))
    print('service', dict(svc))


if __name__ == '__main__':
    main()
