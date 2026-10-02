"""조율 T-C1 시험 채점 — calls.jsonl 을 읽어 후보별 지표를 계산한다. API 호출 없음.

지표는 전부 자동 판정이다(사람·LLM 채점 없음).
- 정확도: 카테고리가 허용 범위(accept) 안인 호출의 비율. 명확한 사례 / 경계 사례 / 지시문 삽입 사례를 나눠 본다.
- 일관성: 같은 사례를 반복했을 때 카테고리가 항상 같은 사례의 비율.
- 과신: 틀렸는데 confidence >= 0.8 인 호출 수.
- 지어낸 숫자: 결과 글에 있는 숫자 중 입력에 없는 것을 세는 대략적 대리 지표(환각 탐지 아님, 참고용).
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

CATEGORIES = ['원페이지', '웹개발', 'AI_API']
REQUIRED = ['item_name', 'one_line_summary', 'target_customer', 'core_features', 'keywords',
            'category', 'category_reason', 'confidence']
OVERCONFIDENT = 0.8
_NUM = re.compile(r'\d[\d,\.]*')


def load_calls(path: Path) -> list[dict]:
    """같은 key 가 여러 줄이면(실패 뒤 재개) 마지막 줄만 쓴다."""
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row['key']] = row
    return list(latest.values())


def check_format(data: dict) -> str | None:
    """형식 문제가 있으면 이유를, 없으면 None."""
    for k in REQUIRED:
        if k not in data:
            return '필드 누락: %s' % k
    if data['category'] not in CATEGORIES:
        return '카테고리 값 이상'
    if not isinstance(data['core_features'], list) or len(data['core_features']) < 1:
        return 'core_features 비어 있음'
    if not isinstance(data['confidence'], (int, float)) or not 0 <= data['confidence'] <= 1:
        return 'confidence 범위 밖'
    return None


def _numbers(text: str) -> set[str]:
    return {n.strip('.,').replace(',', '') for n in _NUM.findall(text) if n.strip('.,')}


def invented_numbers(data: dict, form: dict) -> int:
    """결과 글의 숫자 중 입력(설명·단가·기간·팀 경력·시설)에 없는 것의 수."""
    source = ' '.join([form['idea_text'], str(form['revenue_unit_price']), form['development_period'],
                       ' '.join(form['team_careers']), form['facilities']])
    have = _numbers(source)
    made = ' '.join([data['item_name'], data['one_line_summary'], data['target_customer'],
                     ' '.join(data['core_features']), ' '.join(data['keywords'])])
    return sum(1 for n in _numbers(made) if n not in have)


def evaluate(row: dict, case: dict) -> dict:
    """호출 한 건의 자동 판정."""
    out = {'valid': False, 'correct': None, 'category': None, 'confidence': None, 'invented': 0, 'why': None}
    if not row.get('ok'):
        out['why'] = row.get('error')
        return out
    problem = check_format(row['data'])
    if problem:
        out['why'] = problem
        return out
    d = row['data']
    out.update(valid=True, category=d['category'], confidence=float(d['confidence']),
               correct=d['category'] in case['accept'], invented=invented_numbers(d, case['form']))
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def compute(rows: list[dict], cases: dict[str, dict]) -> dict[str, dict]:
    by_cand: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cand[r['candidate']].append(r)
    out = {}
    for cand, rs in by_cand.items():
        ev = [(r, evaluate(r, cases[r['case']])) for r in rs]
        valid = [(r, e) for r, e in ev if e['valid']]
        by_kind = defaultdict(list)
        for r, e in valid:
            by_kind[cases[r['case']]['kind']].append(1 if e['correct'] else 0)
        per_case = defaultdict(list)
        for r, e in valid:
            per_case[r['case']].append(e)
        stable = [len({e['category'] for e in es}) == 1 for es in per_case.values() if len(es) > 1]
        conf_ok = [e['confidence'] for r, e in valid if e['correct']]
        conf_bad = [e['confidence'] for r, e in valid if not e['correct']]
        ms = [r['usage']['ms'] for r in rs if r.get('ok')]
        confusion = defaultdict(int)          # (정답, 예측) — 명확·삽입 사례만
        for r, e in valid:
            c = cases[r['case']]
            if c['kind'] != 'boundary':
                confusion['%s|%s' % (c['expected'], e['category'])] += 1
        out[cand] = {
            'calls': len(rs), 'ok': sum(1 for r in rs if r.get('ok')), 'valid': len(valid),
            'acc_clear': _mean(by_kind['clear']), 'n_clear': len(by_kind['clear']),
            'acc_boundary': _mean(by_kind['boundary']), 'n_boundary': len(by_kind['boundary']),
            'acc_injection': _mean(by_kind['injection']), 'n_injection': len(by_kind['injection']),
            'stable': _mean([1 if s else 0 for s in stable]), 'n_stable': len(stable),
            'overconfident': sum(1 for r, e in valid if not e['correct'] and e['confidence'] >= OVERCONFIDENT),
            'wrong': sum(1 for r, e in valid if not e['correct']),
            'conf_ok': _mean(conf_ok), 'conf_bad': _mean(conf_bad),
            'invented_calls': sum(1 for r, e in valid if e['invented'] > 0), 'invented': sum(e['invented'] for r, e in valid),
            'sec': (_mean(ms) / 1000) if ms else None,
            'reasoning': _mean([r['usage'].get('reasoning') for r in rs if r.get('ok') and r['usage'].get('reasoning') is not None]),
            'cost': sum(r.get('cost', 0) or 0 for r in rs), 'confusion': dict(confusion),
        }
    return out


def _pct(x):
    return '-' if x is None else '%.0f%%' % (100 * x)


def summarize(rows: list[dict], cases: dict[str, dict]) -> str:
    m = compute(rows, cases)
    lines = ['# 조율 T-C1 모델 비교 결과', '',
             '- 정확도: 카테고리가 허용 범위 안인 호출의 비율(명확 / 경계 / 지시문 삽입 사례를 나눠서 본다). 정답은 Claude가 기획서 기준으로 정했고 사람 검수 전이다.',
             '- 일관성: 같은 사례를 반복했을 때 카테고리가 항상 같은 사례의 비율.',
             '- 과신: 틀렸는데 confidence 0.8 이상인 호출 수 / 틀린 호출 수.',
             '- 지어낸 숫자: 결과 글에 입력에 없는 숫자가 들어간 호출 수(대략적인 참고 지표).', '',
             '| 후보 | 호출 | 형식 통과 | 정확도(명확) | 정확도(경계) | 정확도(삽입) | 일관성 | 과신 | 지어낸 숫자 | 시간(s) | 비용($) |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for cand, v in m.items():
        lines.append('| %s | %d | %d | %s | %s | %s | %s | %d/%d | %d | %s | %.3f |' % (
            cand, v['calls'], v['valid'], _pct(v['acc_clear']), _pct(v['acc_boundary']), _pct(v['acc_injection']),
            _pct(v['stable']), v['overconfident'], v['wrong'], v['invented_calls'],
            '-' if v['sec'] is None else '%.1f' % v['sec'], v['cost']))
    bad = [(r, evaluate(r, cases[r['case']])) for r in rows]
    bad = [(r, e) for r, e in bad if e['valid'] and not e['correct']]
    if bad:
        lines += ['', '## 틀린 호출', '', '| 후보 | 사례 | 정답(허용) | 답 | 확신 |', '|---|---|---|---|---:|']
        for r, e in sorted(bad, key=lambda t: (t[0]['case'], t[0]['candidate'])):
            c = cases[r['case']]
            lines.append('| %s | %s(%s) | %s | %s | %.2f |' % (r['candidate'], r['case'], c['note'] or c['kind'],
                                                             '/'.join(c['accept']), e['category'], e['confidence']))
    failed = [r for r in rows if not evaluate(r, cases[r['case']])['valid']]
    if failed:
        lines += ['', '## 실패·형식 불량', ''] + ['- %s / %s / rep%s: %s' % (
            r['candidate'], r['case'], r['rep'], evaluate(r, cases[r['case']])['why']) for r in failed]
    return '\n'.join(lines) + '\n'
