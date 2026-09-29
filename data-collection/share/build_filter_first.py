# -*- coding: utf-8 -*-
"""공유 페이지 "공고 매칭 방식 비교"(매칭방식비교.html)를 만든다.

  .\\.venv\\Scripts\\python.exe -X utf8 share\\build_filter_first.py [결과 폴더 이름]   (data-collection 에서)

eval/filter_first_eval.py 의 결과 폴더(reports/filter_first_eval_*)를 읽어 filter_first.template.html 의
/*DATA*/null 자리에 넣는다. 폴더 이름을 주지 않으면 2026-09-29 게시판과 같은 filter_first_eval_20260928T104212Z 를 쓴다.
파일만 읽는다(DB·모델·LLM 호출 없음). 섞인 질의 수와 이유별 건수는 결과 파일의 질의별 목록에서 다시 센다.
"""
import collections
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # data-collection (이 스크립트는 data-collection/share/ 에 있다)
DEFAULT_RUN = 'filter_first_eval_20260928T104212Z'
SYSTEMS = ('vector_only', 'legacy', 'filter_first')
EXAMPLE_QID = 'q001'                  # 예시 질의 — 처음 방식 상위 10건 중 신청 불가 6건
TEMPLATE = os.path.join(HERE, 'filter_first.template.html')
OUT = os.path.join(HERE, '매칭방식비교.html')


def build(run):
    with io.open(os.path.join(ROOT, 'reports', run, 'results.json'), encoding='utf-8') as f:
        d = json.load(f)
    out = {'meta': {k: d['meta'][k] for k in ('run_at', 'as_of', 'queries', 'k', 'corpus_notices', 'corpus_before',
                                                'qrels_pairs', 'legacy_commit')},
           'modes': {}}
    for mode in ('hybrid', 'dense'):
        summary = d['summary'][mode]
        lists = [x for x in d['lists'] if x['mode'] == mode]
        m = {'metrics': {k: {'label': v['label'], 'better': v['better'], 'vals': [v[s] for s in SYSTEMS],
                             'd_vec': v['diff_vs_vector'], 'd_old': v['diff']} for k, v in summary.items()},
             'mixed': [], 'why': []}
        for system in SYSTEMS:
            rows = [x for x in lists if x['system'] == system]
            m['mixed'].append(sum(1 for x in rows if x['ineligible']))
            m['why'].append(dict(collections.Counter(w for x in rows for n in x['ineligible']
                                                     for w in x['why'].get(n, []))))
        out['modes'][mode] = m
    notices = d['notices']
    query = [q for q in d['queries'] if q['qid'] == EXAMPLE_QID][0]
    example = {'idea': query['idea'], 'applicant': '%s · %s 설립' % (query['applicant_type'], query['founded_at']),
               'lists': {}}
    for system in ('vector_only', 'filter_first'):
        x = [x for x in d['lists'] if x['mode'] == 'hybrid' and x['system'] == system and x['qid'] == EXAMPLE_QID][0]
        example['lists'][system] = [{'t': notices[n]['title'], 'end': notices[n].get('apply_end') or '',
                                     'src': notices[n]['source'], 'why': x['why'].get(n, [])} for n in x['ranked']]
    out['example'] = example
    return out


def main(argv=None):
    run = (argv or sys.argv[1:] or [DEFAULT_RUN])[0]
    data = build(run)
    with io.open(TEMPLATE, encoding='utf-8') as f:
        page = f.read()
    if page.count('/*DATA*/null') != 1:
        raise SystemExit('틀에서 /*DATA*/null 자리를 찾지 못했다: %s' % TEMPLATE)
    blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    with io.open(OUT, 'w', encoding='utf-8', newline='') as f:
        f.write(page.replace('/*DATA*/null', blob))
    h = data['modes']['hybrid']
    print('만듦 %s · %s · 섞인 질의 %s · 신청 불가@10 %s' % (
        os.path.basename(OUT), run, h['mixed'], [round(v, 3) for v in h['metrics']['ineligible_k']['vals']]))


if __name__ == '__main__':
    main()
