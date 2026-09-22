# -*- coding: utf-8 -*-
"""업종 LLM 추출 결과를 화면(`/industry-results`)에 보여 주기 위한 읽기 전용 모듈.

2026-09-22 사용자 요청 — luna 전량(1,852건) 결과에서 "어떤 업종이 됐는지" 직접 눈으로 본다.
`reports/industry_llm_*` 폴더의 `results.jsonl`·`meta.json` 만 읽는다. DB·LLM 을 부르지 않는다.

원문 링크는 공고 ID 로 만든다(기업마당·K-Startup 의 상세 주소 형식). 결과 파일에는 URL 칸이 없다.
"""
import io
import json
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORTS = os.path.join(ROOT, 'reports')
DEFAULT_RUN = 'industry_llm_full_luna_20260922'
# 화면을 처음 열 때 고르는 순서. 있으면 러프 재검사 결과를 먼저 보여 준다(2026-09-22 사용자 요청)
DEFAULT_ORDER = ('industry_llm_full_luna_20260922_final4', 'industry_llm_full_luna_20260922_final3', 'industry_llm_full_luna_20260922_final2', 'industry_llm_full_luna_20260922_final', 'industry_llm_full_luna_20260922_rough_split',
                 'industry_llm_full_luna_20260922_rough', 'industry_llm_full_luna_20260922_strict', DEFAULT_RUN)


def default_run(reports=None):
    for name in DEFAULT_ORDER:
        if run_path(name, reports):
            return name
    return DEFAULT_RUN


# 매칭용 판정 이름 (industry_llm_sample.INDUSTRY_STATUS 와 같게)
ISTATUS_NAMES = {'known': '업종 제한 있음', 'no_limit': '제한 없음(명시)', 'not_mentioned': '제한 없음(언급 없음·추정)',
                 'excluded_only': '제외 업종만', 'conditional': '조건부·세부사업별', 'unknown': '확인 필요'}
RUN_NAME = re.compile(r'^industry_llm_[A-Za-z0-9_]+$')     # 폴더 이름만 받는다(경로 이동 금지)


def notice_url(notice_id):
    nid = notice_id or ''
    if nid.startswith('bizinfo:'):
        return 'https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=' + nid.split(':', 1)[1]
    if nid.startswith('kstartup:'):
        return ('https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn='
                + nid.split(':', 1)[1])
    return ''


def list_runs(reports=None):
    """결과 폴더 목록(최신 먼저). results.jsonl·meta.json 이 있는 것만."""
    reports = reports or REPORTS
    out = []
    for name in sorted(os.listdir(reports), reverse=True) if os.path.isdir(reports) else []:
        path = os.path.join(reports, name)
        if RUN_NAME.match(name) and os.path.exists(os.path.join(path, 'results.jsonl')) \
                and os.path.exists(os.path.join(path, 'meta.json')):
            with io.open(os.path.join(path, 'meta.json'), encoding='utf-8') as f:
                meta = json.load(f)
            out.append({'name': name, 'engine': meta.get('engine') or meta.get('model') or 'gpt-4o-mini',
                        'prompt': meta.get('prompt'), 'take_all': bool(meta.get('take_all')),
                        'sample': meta.get('sample')})
    return out


def run_path(name, reports=None):
    """폴더 이름 → 경로. 이름 형식이 틀리거나 없으면 None."""
    reports = reports or REPORTS
    if not name or not RUN_NAME.match(name):
        return None
    path = os.path.join(reports, name)
    return path if os.path.exists(os.path.join(path, 'results.jsonl')) else None


def _row(r):
    from experiments.sql_semantic import industry_groups
    llm = r.get('llm') or {}
    if 'allowed' in llm:                                   # v3 형식
        allowed = [{'text': a.get('text'), 'label': a.get('label') or '', 'basis': a.get('label_basis') or ''}
                   for a in llm.get('allowed') or []]
        excluded = [e.get('text') for e in llm.get('excluded') or []]
    else:                                                  # v1·v2 형식
        allowed = [{'text': t, 'label': t, 'basis': 'exact'} for t in llm.get('industries') or []] + \
                  [{'text': t, 'label': '', 'basis': ''} for t in llm.get('other_industries') or []]
        excluded = list(llm.get('excluded_industries') or [])
    for a in allowed:
        a['groups'] = industry_groups.group_of(a['text'])
    return {'groups': industry_groups.groups_of([a['text'] for a in allowed]),
            'id': r['notice_id'], 'title': r.get('title') or '', 'url': notice_url(r['notice_id']),
            'category': r.get('category') or '',
            'status': llm.get('status') or 'unknown', 'llm_status': llm.get('llm_status') or llm.get('status'),
            # 매칭용 판정(2026-09-22) — 없는 옛 결과는 None
            'istatus': llm.get('industry_status'), 'istatus_why': llm.get('industry_status_why') or '',
            'source_run': r.get('source_run') or '', 'truncated': bool(llm.get('truncated')),
            'allowed': allowed, 'excluded': excluded,
            'complete': llm.get('list_complete'), 'quote': llm.get('quote') or '',
            'reason': llm.get('reason') or '', 'downgraded': llm.get('downgraded') or '',
            'dropped': [d.get('text') for d in llm.get('dropped') or [] if d.get('kind') == 'allowed'] +
                       [a.get('text') for a in llm.get('raw_allowed') or []],
            'regex': (r.get('regex') or {}).get('status') or 'unknown'}


def load_run(name, reports=None):
    """화면에 보낼 데이터: meta 요약·집계·공고 행."""
    path = run_path(name, reports)
    if path is None:
        return None
    with io.open(os.path.join(path, 'meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    rows = []
    with io.open(os.path.join(path, 'results.jsonl'), encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(_row(json.loads(line)))
    # 다른 검사 강도 결과(meta.counterpart)가 있으면 공고별 상태를 붙인다 — "러프에서 새로 살아난 것" 보기
    counter = meta.get('counterpart')
    counter_path = run_path(counter, reports) if counter else None
    if counter_path:
        other = {}
        with io.open(os.path.join(counter_path, 'results.jsonl'), encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    other[d['notice_id']] = d
        for r in rows:
            o = other.get(r['id'])
            r['counter_status'] = ((o or {}).get('llm') or {}).get('status') if o else None
    status = Counter(r['status'] for r in rows)
    known = [r for r in rows if r['status'] == 'known']
    texts = Counter(a['text'] for r in known for a in r['allowed'] if a['text'])
    labels = Counter(a['label'] for r in known for a in r['allowed'] if a['label'] and a['basis'] == 'exact')
    excluded = Counter(t for r in rows for t in r['excluded'] if t)
    from experiments.sql_semantic import industry_groups
    groups = Counter(code for r in known for code in r['groups'])
    unmapped = Counter(a['text'] for r in known for a in r['allowed'] if a['text'] and not a['groups'])
    standard = [r for r in known if any(c not in ('X', 'ALL') for c in r['groups'])]
    return {
        'run': name,
        'meta': {k: meta.get(k) for k in ('engine', 'model', 'prompt', 'run_at', 'take_all', 'sample', 'population',
                                          'tokens_in', 'tokens_out', 'tokens_reasoning', 'cost_usd', 'cost_basis',
                                          'failures', 'db_writes', 'profile', 'reverified_from', 'counterpart',
                                          'source_cost_usd', 'merged_from', 'merge_history')},
        'istatus_names': ISTATUS_NAMES,
        'summary': {'total': len(rows), 'known': status.get('known', 0), 'no_limit': status.get('no_limit', 0),
                    'unknown': status.get('unknown', 0),
                    'complete': sum(1 for r in known if r['complete']),
                    'downgraded': sum(1 for r in rows if r['downgraded']),
                    'with_excluded': sum(1 for r in rows if r['excluded']),
                    'istatus': dict(Counter(r['istatus'] for r in rows if r['istatus'])) or None,
                    'newly_known': sum(1 for r in rows if r['status'] == 'known'
                                       and r.get('counter_status') not in (None, 'known')) if counter_path else None},
        # 큰 묶음(KSIC 대분류) — 공고 수 기준. 이름은 industry_groups.NAMES
        'top_groups': [(code, industry_groups.NAMES.get(code, code), n) for code, n in groups.most_common()],
        'group_coverage': {'known': len(known), 'standard': len(standard),
                           'only_field_or_all': sum(1 for r in known if r['groups']
                                                    and all(c in ('X', 'ALL') for c in r['groups'])),
                           'none': sum(1 for r in known if not r['groups'])},
        'unmapped': unmapped.most_common(30),
        'group_names': industry_groups.NAMES,
        'top_texts': texts.most_common(40),
        'top_labels': labels.most_common(),
        'top_excluded': excluded.most_common(20),
        'rows': rows,
    }
