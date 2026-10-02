"""구현 T-B1(HTML)·T-B2(SVG 인포그래픽) 시험 채점 — calls.jsonl 을 읽어 후보별 지표를 계산한다. API 호출 없음.

산출물층 30점 구조(기획서 4-5): 코드 검증 15점(v5_builder/checks.py) + 계획서 대조 15점(기능 누락 하나당 -4점).
T-B1: 웹개발·AI API 아이템 6건의 HTML. T-B2: 8건 모두의 SVG 인포그래픽(코드 검증만, 대조는 원페이지 아이템 2건에서만 산출물 본체라서 셈).
전부 정적 파싱이라 결과가 같은 입력에서 항상 같다. 화면이 실제로 예쁜지·동작하는지는 재지 못한다 — 리포트 미리보기로 눈으로 본다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from v5_builder import checks


def load_calls(path: Path) -> list[dict]:
    """같은 key 가 여러 줄이면(실패 뒤 재개) 마지막 줄만 쓴다."""
    latest: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row['key']] = row
    return list(latest.values())


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def evaluate(row: dict, case: dict) -> dict:
    """호출 한 건의 자동 판정. 코드를 못 꺼내면 valid=False(형식 오류)."""
    if not row.get('ok'):
        return {'valid': False, 'why': row.get('error')}
    kind = 'html' if row['task'] == 'b1' else 'svg'
    src = checks.extract_code(row['data']['text'], kind)
    if not src:
        return {'valid': False, 'why': '응답에서 %s 코드를 찾지 못함' % kind.upper()}
    r = checks.html_checks(src, case) if kind == 'html' else checks.svg_checks(src, case, case['item_spec']['category'])
    onepage = case['item_spec']['category'] == '원페이지'
    match = r['features']['score'] if (kind == 'html' or onepage) else None
    return {'valid': True, 'src': src, 'chars': len(src), 'checks': r['checks'], 'code': r['code'], 'match': match,
            'missing': r['features']['missing'] if match is not None else [], 'external': r.get('external', []),
            'info': r.get('info', []), 'total': r['code'] + (match or 0)}


def compute(rows: list[dict], cases: dict[str, dict]) -> dict[str, dict]:
    by = defaultdict(list)
    for r in rows:
        by[r['candidate']].append(r)
    out = {}
    for cand, rs in by.items():
        ev = [(r, evaluate(r, cases[r['case']])) for r in rs]
        b1 = [e for r, e in ev if r['task'] == 'b1' and e['valid']]
        b2 = [e for r, e in ev if r['task'] == 'b2' and e['valid']]
        ms = [r['usage']['ms'] for r in rs if r.get('ok')]
        b1_calls = sum(1 for r, _ in ev if r['task'] == 'b1')
        b2_calls = sum(1 for r, _ in ev if r['task'] == 'b2')

        def passrate(pool, no):
            vals = [next(c for c in e['checks'] if c['no'] == no)['ok'] for e in pool]
            return _mean([1 if v else 0 for v in vals])
        out[cand] = {
            'calls': len(rs), 'ok': sum(1 for r in rs if r.get('ok')), 'valid': sum(1 for _, e in ev if e['valid']),
            'b1_calls': b1_calls, 'b1_valid': len(b1), 'b1_code': _mean([e['code'] for e in b1]), 'b1_match': _mean([e['match'] for e in b1]),
            'b1_total': _mean([e['total'] for e in b1]), 'b1_external': sum(1 for e in b1 if e['external']),
            'b1_entry_fail': sum(1 for e in b1 if e['code'] == 0), 'b1_chars': _mean([e['chars'] for e in b1]),
            'b1_full_features': _mean([1 if not e['missing'] else 0 for e in b1]),
            'b1_rates': {n: passrate(b1, n) for n in range(1, 9)},
            'b2_calls': b2_calls, 'b2_valid': len(b2), 'b2_code': _mean([e['code'] for e in b2]),
            'b2_match': _mean([e['match'] for e in b2 if e['match'] is not None]),
            'b2_rates': {n: passrate(b2, n) for n in range(1, 9)},
            'b2_info': _mean([sum(1 for i in e['info'] if i['ok']) / 6 for e in b2 if e['info']]),
            'sec': (_mean(ms) / 1000) if ms else None, 'cost': sum(r.get('cost', 0) or 0 for r in rs),
            'reasoning': _mean([r['usage'].get('reasoning') for r in rs if r.get('ok') and r['usage'].get('reasoning') is not None]),
        }
    return out


def _f(x, n=1):
    return '-' if x is None else '%.*f' % (n, x)


def _pct(x):
    return '-' if x is None else '%.0f%%' % (100 * x)


def summarize(rows: list[dict], cases: dict[str, dict]) -> str:
    m = compute(rows, cases)
    L = ['# 구현 T-B1·T-B2 모델 비교 결과', '',
         '전부 정적 파싱 자동 판정이다(기획서 5-4 코드 검증 + 기능 대조). 화면이 예쁜지·실제로 동작하는지는 재지 못했다 — 리포트의 미리보기로 눈으로 확인한다.',
         '코드 검증 15점 중 "실행 안내(README)"·"열람 안내"는 규칙 모듈이 만들어 모델 몫이 아니라 자동 만점이므로 모델이 얻을 수 있는 최대는 14점이다. 진입 파일이 미충족이면 코드 점수는 0이다.', '',
         '## T-B1 HTML 실행 파일 (웹개발·AI API 아이템 6건)', '',
         '| 후보 | 호출 | 형식 통과 | 코드 검증(15) | 기능 대조(15) | 합(30) | 모든 기능 구현 | 진입 파일 실패 | 외부 의존 | 평균 글자 수 |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %d | %s | %s | %s | %s | %d | %d | %s |' % (c, v['b1_calls'], v['b1_valid'], _f(v['b1_code']), _f(v['b1_match']), _f(v['b1_total']),
                                                                 _pct(v['b1_full_features']), v['b1_entry_fail'], v['b1_external'], _f(v['b1_chars'], 0)))
    L += ['', '### T-B1 코드 검증 항목별 통과율', '', '| 후보 | ' + ' | '.join(checks.HTML_NAMES) + ' |', '|---|' + '---:|' * 8]
    for c, v in m.items():
        L.append('| %s | %s |' % (c, ' | '.join(_pct(v['b1_rates'][n]) for n in range(1, 9))))
    L += ['', '## T-B2 SVG 인포그래픽 (8건)', '', '| 후보 | 호출 | 형식 통과 | 코드 검증(15) | 핵심 정보 6항목 | 기능 대조(원페이지 2건) |', '|---|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %d | %s | %s | %s |' % (c, v['b2_calls'], v['b2_valid'], _f(v['b2_code']), _pct(v['b2_info']), _f(v['b2_match'])))
    L += ['', '### T-B2 코드 검증 항목별 통과율', '', '| 후보 | ' + ' | '.join(checks.SVG_NAMES) + ' |', '|---|' + '---:|' * 8]
    for c, v in m.items():
        L.append('| %s | %s |' % (c, ' | '.join(_pct(v['b2_rates'][n]) for n in range(1, 9))))
    L += ['', '## 비용·시간', '', '| 후보 | 호출 | 시간(s) | 추론 토큰 | 비용($) |', '|---|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %s | %s | %.3f |' % (c, v['calls'], _f(v['sec']), _f(v['reasoning'], 0), v['cost']))
    failed = [(r, evaluate(r, cases[r['case']])) for r in rows]
    failed = [(r, e) for r, e in failed if not e['valid']]
    if failed:
        L += ['', '## 실패·형식 불량', ''] + ['- %s / %s / %s / rep%s: %s' % (r['candidate'], r['task'], r['case'], r['rep'], e['why']) for r, e in failed]
    return '\n'.join(L) + '\n'
