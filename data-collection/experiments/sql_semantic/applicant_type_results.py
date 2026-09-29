# -*- coding: utf-8 -*-
"""신청자 유형 LLM 추출 결과를 화면(`/applicant-types`)에 보여 주는 읽기 전용 모듈 (2026-09-28 사용자 요청).

`reports/applicant_type_llm_*` 폴더의 results.jsonl · meta.json 만 읽는다. DB·LLM 을 부르지 않는다.
아직 도는 실행(체크포인트만 있고 results.jsonl 이 없음)은 진행 건수만 보여 준다.
"""
import io
import json
import os
import re
from collections import Counter

from experiments.sql_semantic.industry_results import notice_url

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORTS = os.path.join(ROOT, 'reports')
RUN_NAME = re.compile(r'^applicant_type_llm_[A-Za-z0-9_]+$')
TYPES = ('pre_founder', 'sole_proprietor', 'corporation')
TYPE_KO = {'pre_founder': '예비창업자', 'sole_proprietor': '개인사업자', 'corporation': '법인'}
STATUS_KO = {'allowed': '가능', 'not_allowed': '불가', 'implied_no': '불가 추정', 'not_mentioned': '언급 없음'}


def _read_json(path):
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def _count_lines(path):
    if not os.path.exists(path):
        return 0
    with io.open(path, encoding='utf-8') as f:
        return sum(1 for line in f if line.strip())


def list_runs(reports=None):
    """결과 폴더 목록. 전량 먼저, 그다음 표본. 각 묶음 안에서 최신순. 실행 중인 폴더는 running=True."""
    reports = reports or REPORTS
    out = []
    for name in os.listdir(reports) if os.path.isdir(reports) else []:
        path = os.path.join(reports, name)
        if not (RUN_NAME.match(name) and os.path.isdir(path)):
            continue
        done = os.path.exists(os.path.join(path, 'results.jsonl')) and os.path.exists(os.path.join(path, 'meta.json'))
        meta = _read_json(os.path.join(path, 'meta.json')) if done else {}
        out.append({'name': name, 'full': '_full_' in name, 'running': not done,
                    'progress': _count_lines(os.path.join(path, 'checkpoint.jsonl')),
                    'n': meta.get('n'), 'run_at': meta.get('run_at') or name.rsplit('_', 1)[-1],
                    'cost_usd': meta.get('cost_usd')})
    out.sort(key=lambda r: r['run_at'], reverse=True)
    out.sort(key=lambda r: (not r['full']))
    return out


def default_run(reports=None):
    runs = [r for r in list_runs(reports) if not r['running']]
    return runs[0]['name'] if runs else None


def run_path(name, reports=None):
    reports = reports or REPORTS
    if not name or not RUN_NAME.match(name):
        return None
    path = os.path.join(reports, name)
    return path if os.path.isdir(path) else None


def _api_pre(row):
    """K-Startup API 업력 칸이 말하는 예비창업자 가능 여부. 없으면 None."""
    raw = row.get('age_condition_raw')
    if row.get('source') != 'kstartup' or not raw:
        return None
    from search import gate
    return gate.parse_enyy(raw)[0]


def _llm_pre(status):
    return {'allowed': True, 'not_allowed': False, 'implied_no': False}.get(status)


def _row(r):
    llm = r.get('llm') or {}
    types = {}
    for t in TYPES:
        c = llm.get(t) or {}
        types[t] = {'status': c.get('status') or 'not_mentioned', 'strength': c.get('strength'),
                    'dropped': c.get('dropped'), 'raw_status': c.get('raw_status'), 'evidence': c.get('evidence')}
    gate = [] if llm.get('varies') else [t for t in TYPES if types[t]['status'] == 'not_allowed'
                                         and types[t]['strength'] == 'strong']
    api = _api_pre(r)
    llm_pre = _llm_pre(types['pre_founder']['status'])
    legacy = r.get('legacy') or None
    legacy_pre = legacy.get('pre_startup_allowed') if legacy else None
    return {'id': r['notice_id'], 'title': r.get('title') or '', 'source': r.get('source') or '',
            'url': notice_url(r['notice_id']), 'target_category': r.get('target_category') or '',
            'age_condition_raw': r.get('age_condition_raw') or '', 'types': types,
            'varies': bool(llm.get('varies')), 'reason': llm.get('reason') or '', 'gate': gate,
            'api_pre': api, 'api_diff': api is not None and llm_pre is not None and api != llm_pre,
            'legacy': legacy, 'legacy_diff': legacy_pre is not None and llm_pre is not None and legacy_pre != llm_pre,
            'failed': not llm}


def load_run(name, reports=None):
    path = run_path(name, reports)
    if not path:
        return None
    if not os.path.exists(os.path.join(path, 'results.jsonl')):
        return {'run': name, 'running': True, 'progress': _count_lines(os.path.join(path, 'checkpoint.jsonl'))}
    meta = _read_json(os.path.join(path, 'meta.json'))
    rows = []
    with io.open(os.path.join(path, 'results.jsonl'), encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(_row(json.loads(line)))
    ok = [r for r in rows if not r['failed']]
    by_type = {t: dict(Counter(r['types'][t]['status'] for r in ok)) for t in TYPES}
    summary = {
        'total': len(rows), 'ok': len(ok), 'failed': len(rows) - len(ok),
        'by_source': dict(Counter(r['source'] for r in rows)),
        'by_type': by_type,
        'pre_strong_no': sum(1 for r in ok if 'pre_founder' in r['gate']),
        'gate_any': sum(1 for r in ok if r['gate']),
        'varies': sum(1 for r in ok if r['varies']),
        'dropped': sum(1 for r in ok for t in TYPES if r['types'][t]['dropped']),
        'api_compared': sum(1 for r in ok if r['api_pre'] is not None and _llm_pre(r['types']['pre_founder']['status']) is not None),
        'api_diff': sum(1 for r in ok if r['api_diff']),
        'legacy_compared': sum(1 for r in ok if r['legacy'] and r['legacy'].get('pre_startup_allowed') is not None
                               and _llm_pre(r['types']['pre_founder']['status']) is not None),
        'legacy_diff': sum(1 for r in ok if r['legacy_diff']),
        'biz_explicit': sum(1 for r in ok if any(r['types'][t]['status'] != 'not_mentioned'
                                                 for t in ('sole_proprietor', 'corporation'))),
        'biz_no': sum(1 for r in ok if any(r['types'][t]['status'] == 'not_allowed'
                                           for t in ('sole_proprietor', 'corporation'))),
    }
    return {'run': name, 'running': False, 'meta': {k: meta.get(k) for k in (
                'run_at', 'engine', 'n', 'n_bizinfo', 'n_kstartup', 'tokens_in', 'tokens_out', 'cost_usd',
                'failures', 'take_all', 'price_basis')},
            'summary': summary, 'rows': rows, 'type_names': TYPE_KO, 'status_names': STATUS_KO}
