# -*- coding: utf-8 -*-
"""Jev 채점 시험 결과를 화면(`/jev-probe`)에 보여 주기 위한 읽기 전용 모듈.

2026-09-28 사용자 요청 — "jev 로 한 것도 눈으로 확인 가능?". eval/jev_judge_probe.py 결과
(`reports/jev_judge_probe_*/summary.json · judgments.jsonl`)에 평가 파일(질의·공고 스냅샷·사람 판정·LLM 판정)을
붙여 쌍마다 사람·Jev·LLM 판정을 나란히 보인다. 파일만 읽는다 — DB·모델·Jev·LLM 을 부르지 않는다.
"""
import io
import json
import os
import re
import sys

from experiments.sql_semantic.industry_results import notice_url

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORTS = os.path.join(ROOT, 'reports')
EVAL = os.path.join(ROOT, 'eval')
RUN_NAME = re.compile(r'^jev_judge_probe_\d{8}T\d{6}Z$')     # 폴더 이름만 받는다(경로 이동 금지)
BINS = ((0.9, '0.9 이상'), (0.7, '0.7~0.9'), (0.0, '0.7 미만'))


def list_runs(reports=None):
    """결과 폴더 이름, 최신 먼저(이름이 UTC 시각이라 문자순 = 시간순)."""
    reports = reports or REPORTS
    if not os.path.isdir(reports):
        return []
    return sorted((n for n in os.listdir(reports) if RUN_NAME.match(n)
                   and os.path.exists(os.path.join(reports, n, 'summary.json'))), reverse=True)


def sources():
    """평가 파일에서 붙일 것. 테스트는 이 함수를 바꿔 끼운다."""
    if EVAL not in sys.path:
        sys.path.insert(0, EVAL)
    import common
    import jev_judge_probe
    from label_app import llm_latest
    human_rows = common.read_jsonl(common.HUMAN)
    truth, _ = jev_judge_probe.blind_truth(human_rows)
    reason = {}
    for h in human_rows:                       # 판정과 같은 규칙: 블라인드, 재확인이 있으면 재확인의 이유
        key = (h['qid'], h['notice_id'])
        if h['mode'] == 'blind' or (h['mode'] == 'recheck' and key in reason):
            reason[key] = h.get('reason') or ''
    llm = {}
    for key, runs in llm_latest().items():
        a = runs.get('A')
        if a and a.get('topic_rel') is not None:
            llm[key] = {'rel': a['topic_rel'], 'reason': a.get('reason') or '', 'model': a.get('model') or ''}
    queries = common.load_queries()
    return {'truth': truth, 'human_reason': reason, 'llm': llm,
            'persona': {qid: common.persona_text(q['payload']) for qid, q in queries.items()},
            'snapshot': common.load_snapshot()}


def _metrics(pairs):
    n = len(pairs)
    if not n:
        return None
    return {'n': n, 'exact': sum(a == b for a, b in pairs) / n}


def _bin(c):
    for lo, name in BINS:
        if c is not None and c >= lo:
            return name
    return None


def load_run(name='', reports=None, src=None):
    """화면에 보낼 데이터. name 이 없으면 최신. 없거나 형식이 틀리면 None."""
    reports = reports or REPORTS
    runs = list_runs(reports)
    name = name or (runs[0] if runs else '')
    if not RUN_NAME.match(name or '') or name not in runs:
        return None
    folder = os.path.join(reports, name)
    with io.open(os.path.join(folder, 'summary.json'), encoding='utf-8') as f:
        summary = json.load(f)
    rows = []
    path = os.path.join(folder, 'judgments.jsonl')
    if os.path.exists(path):
        with io.open(path, encoding='utf-8') as f:
            rows = [json.loads(line) for line in f if line.strip()]
    src = src or sources()
    pairs = []
    for r in sorted(rows, key=lambda r: (r['qid'], r['notice_id'])):
        key = (r['qid'], r['notice_id'])
        n = src['snapshot'].get(r['notice_id']) or {}
        llm = src['llm'].get(key) or {}
        pairs.append({
            'qid': r['qid'], 'notice_id': r['notice_id'],
            'title': n.get('title') or '', 'url': notice_url(r['notice_id']),
            'persona': src['persona'].get(r['qid'], ''),
            'human': src['truth'].get(key), 'human_reason': src['human_reason'].get(key, ''),
            'jev': r.get('topic_rel'), 'jev_conf': r.get('confidence'),
            'jev_probs': r.get('probabilities') or {}, 'jev_error': r.get('error'),
            'llm': llm.get('rel'), 'llm_reason': llm.get('reason', ''),
            'bin': _bin(r.get('confidence')),
        })
    # 확신도 구간마다 같은 쌍의 LLM 정확 일치 — "Jev 가 확신한 쌍이 원래 쉬운 쌍인지"를 가린다
    by_bin = {}
    for _lo, b in BINS:
        ps = [p for p in pairs if p['bin'] == b and p['human'] is not None and isinstance(p['jev'], int)]
        by_bin[b] = {'jev': _metrics([(p['human'], p['jev']) for p in ps]),
                     'llm': _metrics([(p['human'], p['llm']) for p in ps if p['llm'] is not None])}
    return {'run': name, 'runs': runs, 'summary': summary, 'pairs': pairs, 'by_bin': by_bin}
