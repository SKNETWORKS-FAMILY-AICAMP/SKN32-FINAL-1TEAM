# -*- coding: utf-8 -*-
"""검색 먼저 vs 정형 필터 먼저 비교 결과를 화면(`/filter-first-eval`)에 보여 주기 위한 읽기 전용 모듈.

2026-09-28 사용자 요청 — eval/filter_first_eval.py 결과를 사이트에서 직접 확인한다.
`reports/filter_first_eval_*/results.json` 만 읽는다. DB·모델·LLM 을 부르지 않는다.
"""
import io
import json
import os
import re

from experiments.sql_semantic.industry_results import notice_url

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORTS = os.path.join(ROOT, 'reports')
RUN_NAME = re.compile(r'^filter_first_eval_\d{8}T\d{6}Z$')     # 폴더 이름만 받는다(경로 이동 금지)


def list_runs(reports=None):
    """결과 폴더 이름, 최신 먼저(이름이 UTC 시각이라 문자순 = 시간순)."""
    reports = reports or REPORTS
    names = [n for n in os.listdir(reports) if RUN_NAME.match(n)
             and os.path.exists(os.path.join(reports, n, 'results.json'))] if os.path.isdir(reports) else []
    return sorted(names, reverse=True)


def load_run(name='', reports=None):
    """화면에 보낼 데이터. name 이 없으면 최신. 없거나 형식이 틀리면 None."""
    reports = reports or REPORTS
    runs = list_runs(reports)
    name = name or (runs[0] if runs else '')
    if not RUN_NAME.match(name or '') or name not in runs:
        return None
    with io.open(os.path.join(reports, name, 'results.json'), encoding='utf-8') as f:
        data = json.load(f)
    notices = data.get('notices') or {}          # 2026-09-28 첫 실행(004448Z)에는 없다 — ID 만 보인다
    for nid in {n for lst in data['lists'] for n in lst['ranked']}:
        notices.setdefault(nid, {'title': '', 'apply_end': '', 'age_condition': ''})
        notices[nid]['url'] = notice_url(nid)
    data['notices'] = notices
    data['queries'] = data.get('queries') or [{'qid': q} for q in sorted({l['qid'] for l in data['lists']})]
    data['run'] = name
    data['runs'] = runs
    return data
