"""전략 Agent T-S1·T-S2 시험 채점 — calls.jsonl 을 읽어 후보별 지표를 계산한다. API 호출 없음. 전부 자동 판정이다.

T-S1(요구사항 분석)
- 엄격 포함: item_spec.core_features 가 feature_list 에 글자 그대로 모두 들어 있다(기능정의서: "누락 0").
- 느슨 포함: 띄어쓰기·기호를 무시하거나 글자쌍이 거의 같으면 같은 기능으로 본다. 엄격은 실패인데 느슨은 통과면 '말만 바꿔 쓴 것'이다.
- 덧붙인 기능: feature_list 항목 중 어떤 core_feature 와도 같지 않은 것의 수(확정 뒤 못 바꾸는 기준 목록이 부풀려지는 위험).

T-S2(목표 시장 분석) — 조건 두 가지
- facts(참고 자료 있음): market_size 각 항목의 값이 자료의 수치와 맞는지(2% 이내, 만·억·조 단위 해석) 대조한다.
  '자료 사용'(맞음) / '함정 사용'(다른 분야 통계를 끌어옴) / '자료에 없는 수치'(직접 계산했거나 지어냄)로 나눈다.
- open(참고 자료 없음): 모델은 기억에 의존해야 한다. 수치 개수·출처 없는 수치·불확실 표시(추정/가정)를 센다.
  출처 이름을 댔다고 사실은 아니다 — 이 조건의 수치는 검증하지 못한다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

_NUM = re.compile(r'\d[\d,]*\.?\d*')
_YEAR = re.compile(r'^(19|20)\d\d$')
_HEDGE = re.compile(r'추정|가정|예상|가상|확인 필요|근거 없|참고용|대략|개략')
_SCALES = [('조', 1e12), ('억', 1e8), ('천만', 1e7), ('백만', 1e6), ('만', 1e4), ('천', 1e3)]


def load_calls(path: Path) -> list[dict]:
    """같은 key 가 여러 줄이면(실패 뒤 재개) 마지막 줄만 쓴다."""
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row['key']] = row
    return list(latest.values())


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _norm(s: str) -> str:
    return re.sub(r'[\s\W_]+', '', s)


def _bigrams(s: str) -> set:
    s = _norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def same_feature(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if na == nb or na in nb or nb in na:
        return True
    ba, bb = _bigrams(a), _bigrams(b)
    return len(ba & bb) / len(ba | bb) >= 0.6


def digit_tokens(text: str) -> set[str]:
    out = set()
    for t in _NUM.findall(text):
        t = t.strip('.,').replace(',', '')
        if t and not _YEAR.match(t):
            out.add(t)
    return out


# ── T-S1 ──────────────────────────────────────────────────
def eval_s1(data: dict, case: dict) -> dict:
    for k in ('problem_statement', 'target_customer', 'feature_list', 'differentiator', 'use_cases'):
        if k not in data:
            return {'valid': False, 'why': '필드 누락: %s' % k}
    fl = data['feature_list']
    if not isinstance(fl, list) or not fl:
        return {'valid': False, 'why': 'feature_list 비어 있음'}
    core = case['item_spec']['core_features']
    strict = all(c.strip() in [f.strip() for f in fl] for c in core)
    lenient = all(any(same_feature(c, f) for f in fl) for c in core)
    extras = [f for f in fl if not any(same_feature(c, f) for c in core)]
    spec = json.dumps(case['item_spec'], ensure_ascii=False) + case['differentiator']
    made = ' '.join([data['problem_statement'], data['target_customer'], data['differentiator'], ' '.join(data['use_cases'])])
    invented = len(digit_tokens(made) - digit_tokens(spec))
    return {'valid': True, 'strict': strict, 'lenient': lenient, 'paraphrased': (not strict) and lenient,
            'missing': sum(1 for c in core if not any(same_feature(c, f) for f in fl)),
            'extras': len(extras), 'invented': invented, 'n_features': len(fl)}


# ── T-S2 ──────────────────────────────────────────────────
def value_candidates(item: dict) -> list[float]:
    """모델이 적은 (value, unit)을 기본 단위 수치 후보로 바꾼다. 3800000/가구 와 380/만 가구 를 모두 인정한다."""
    v = float(item['value'])
    cands = [v]
    unit = str(item.get('unit', '')).strip().lstrip('약')
    for word, scale in _SCALES:
        if unit.startswith(word):
            cands.append(v * scale)
            break
    if '%' in unit and 0 < v <= 1:
        cands.append(v * 100)
    return cands


def matches(item: dict, fact: dict) -> bool:
    return any(abs(c - fact['value']) <= 0.02 * abs(fact['value']) for c in value_candidates(item))


_DISCLAIM = re.compile(r'직접.{0,12}(아니|않)|인접|전방|간접|참고|맥락|배경|비교|상위 시장|아니라')


def reachable_values(case: dict, rounds: int = 2) -> list[float]:
    """자료의 수치로 계산해 만들 수 있는 값: (개수 × 비율%) 와 (개수 × (1 - 비율%)), 연쇄 2단계까지.
    예) 79만 × 84% = 66만 3,600, 여기에 11%를 다시 적용한 값. 함정 자료는 계산 재료로 쓰지 않는다."""
    base = [float(f['value']) for f in case['facts'] if f['unit'] != '%']
    pcts = [float(f['value']) for f in case['facts'] if f['unit'] == '%']
    seen = list(base)
    for _ in range(rounds):
        new = []
        for a in seen:
            for p in pcts:
                new += [a * p / 100, a * (1 - p / 100)]
        seen += new
    return seen


def classify_items(ms: list[dict], case: dict) -> list[dict]:
    """market_size 항목마다 참고 자료와 대조한 결과.
    status: used(자료의 수치) / trap(함정 통계; disclaimed=한계를 밝힘) / derived(자료로 계산한 값) / other(설명 안 되는 수치)."""
    out = []
    reach = reachable_values(case)
    for it in ms:
        m = next((f for f in case['facts'] if matches(it, f)), None)
        if m is not None:
            key = m['source'].split()[0]                        # 기관명 (예: 통계청)
            out.append({'status': 'used', 'label': m['label'], 'source_ok': key in str(it.get('source_name', ''))})
        elif matches(it, case['trap']):
            out.append({'status': 'trap', 'label': case['trap']['label'], 'source_ok': False,
                        'disclaimed': bool(_DISCLAIM.search(str(it.get('basis', ''))))})
        elif any(abs(c - r) <= 0.01 * abs(r) for c in value_candidates(it) for r in reach):      # 계산값은 정확해야 하므로 1%
            out.append({'status': 'derived', 'label': None, 'source_ok': False})
        else:
            out.append({'status': 'other', 'label': None, 'source_ok': False})
    return out


def eval_s2(data: dict, case: dict, cond: str) -> dict:
    for k in ('market_definition', 'market_size', 'competitors', 'positioning'):
        if k not in data:
            return {'valid': False, 'why': '필드 누락: %s' % k}
    ms = data['market_size']
    if not isinstance(ms, list):
        return {'valid': False, 'why': 'market_size 형식 이상'}
    out = {'valid': True, 'n_items': len(ms), 'unsourced': sum(1 for i in ms if not str(i.get('source_name', '')).strip()),
           'hedged': sum(1 for i in ms if _HEDGE.search(str(i.get('basis', '')))), 'used': 0, 'trap': 0, 'trap_plain': 0,
           'derived': 0, 'other': 0,
           'misattributed': 0, 'unlisted_numbers': 0}
    texts = [data['market_definition'], data['positioning'], ' '.join(data['competitors'])]
    texts += [' '.join(str(i.get(k, '')) for k in ('label', 'unit', 'source_name', 'basis')) for i in ms]
    prose = digit_tokens(' '.join(texts))
    if cond == 'facts':
        facts = case['facts']
        cls = classify_items(ms, case)
        out['used'] = len({c['label'] for c in cls if c['status'] == 'used'})
        out['trap'] = sum(1 for c in cls if c['status'] == 'trap')
        out['trap_plain'] = sum(1 for c in cls if c['status'] == 'trap' and not c['disclaimed'])
        out['derived'] = sum(1 for c in cls if c['status'] == 'derived')
        out['other'] = sum(1 for c in cls if c['status'] == 'other')
        out['misattributed'] = sum(1 for c in cls if c['status'] == 'used' and not c['source_ok'])
        allowed = set()
        for f in facts + [case['trap']]:
            allowed |= digit_tokens(f['display']) | {str(int(f['value'])) if float(f['value']).is_integer() else str(f['value'])}
            allowed |= digit_tokens(f['source'])
        allowed |= digit_tokens(json.dumps(case['item_spec'], ensure_ascii=False))
        out['unlisted_numbers'] = len(prose - allowed)
    else:
        spec = digit_tokens(json.dumps(case['item_spec'], ensure_ascii=False))
        out['unlisted_numbers'] = len(prose - spec)
    return out


def evaluate(row: dict, case: dict) -> dict:
    if not row.get('ok'):
        return {'valid': False, 'why': row.get('error')}
    return eval_s1(row['data'], case) if row['task'] == 's1' else eval_s2(row['data'], case, row['cond'])


def compute(rows: list[dict], cases: dict[str, dict]) -> dict[str, dict]:
    by = defaultdict(list)
    for r in rows:
        by[r['candidate']].append(r)
    out = {}
    for cand, rs in by.items():
        ev = [(r, evaluate(r, cases[r['case']])) for r in rs]

        def sel(task, cond=None):
            return [e for r, e in ev if r['task'] == task and (cond is None or r['cond'] == cond) and e['valid']]
        s1, sf, so = sel('s1'), sel('s2', 'facts'), sel('s2', 'open')
        ms = [r['usage']['ms'] for r in rs if r.get('ok')]
        out[cand] = {
            'calls': len(rs), 'ok': sum(1 for r in rs if r.get('ok')), 'valid': sum(1 for _, e in ev if e['valid']),
            's1_n': len(s1), 's1_strict': _mean([1 if e['strict'] else 0 for e in s1]),
            's1_lenient': _mean([1 if e['lenient'] else 0 for e in s1]),
            's1_paraphrased': sum(1 for e in s1 if e['paraphrased']), 's1_changed': sum(1 for e in s1 if not e['strict']), 's1_extras': _mean([e['extras'] for e in s1]),
            's1_invented_calls': sum(1 for e in s1 if e['invented']),
            'f_n': len(sf), 'f_items': sum(e['n_items'] for e in sf), 'f_used': sum(e['used'] for e in sf),
            'f_used_rate': _mean([e['used'] / 3 for e in sf]), 'f_trap': sum(e['trap'] for e in sf),
            'f_trap_calls': sum(1 for e in sf if e['trap']), 'f_other': sum(e['other'] for e in sf),
            'f_trap_plain_calls': sum(1 for e in sf if e['trap_plain']), 'f_derived_calls': sum(1 for e in sf if e['derived']),
            'f_other_calls': sum(1 for e in sf if e['other']), 'f_unsourced': sum(e['unsourced'] for e in sf),
            'f_misattr': sum(e['misattributed'] for e in sf), 'f_unlisted_calls': sum(1 for e in sf if e['unlisted_numbers']),
            'o_n': len(so), 'o_items': sum(e['n_items'] for e in so), 'o_items_mean': _mean([e['n_items'] for e in so]),
            'o_zero_calls': sum(1 for e in so if e['n_items'] == 0), 'o_unsourced': sum(e['unsourced'] for e in so),
            'o_hedged': sum(e['hedged'] for e in so), 'o_unlisted_calls': sum(1 for e in so if e['unlisted_numbers']),
            'sec': (_mean(ms) / 1000) if ms else None,
            'reasoning': _mean([r['usage'].get('reasoning') for r in rs if r.get('ok') and r['usage'].get('reasoning') is not None]),
            'cost': sum(r.get('cost', 0) or 0 for r in rs),
        }
    return out


def _pct(x):
    return '-' if x is None else '%.0f%%' % (100 * x)


def summarize(rows: list[dict], cases: dict[str, dict]) -> str:
    m = compute(rows, cases)
    L = ['# 전략 T-S1·T-S2 모델 비교 결과', '',
         '전부 자동 판정이다(사람·LLM 채점 없음). 아이템·참고 자료는 모두 시험용 가상 값이다.', '',
         '## T-S1 요구사항 분석', '',
         '- 엄격: core_features 가 feature_list 에 글자 그대로 모두 들어 있음. 느슨: 말만 바꿔 써도 인정. 말 바꿈 = 엄격 실패 & 느슨 통과.',
         '- 덧붙임: core_features 에 없는 기능을 feature_list 에 더한 개수(호출당 평균).', '',
         '| 후보 | 호출 | 엄격 포함 | 느슨 포함 | 말 바꿈 | 목록을 바꾼 호출 | 덧붙임 | 지어낸 숫자 호출 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %s | %s | %d | %d | %s | %d |' % (c, v['s1_n'], _pct(v['s1_strict']), _pct(v['s1_lenient']),
                                                       v['s1_paraphrased'], v['s1_changed'], '-' if v['s1_extras'] is None else '%.2f' % v['s1_extras'], v['s1_invented_calls']))
    L += ['', '## T-S2 목표 시장 분석 — 참고 자료 있음', '',
          '- 자료 사용: 자료 3건 중 쓴 비율. 함정: 다른 분야 통계를 끌어옴(그중 "그냥 사용"은 한계를 밝히지 않은 경우). 계산: 자료의 수치를 곱해 만든 값(연쇄 2단계까지). 설명 안 됨: 자료로도 계산으로도 설명되지 않는 수치.',
          '- 2026-09-30 기준 수정: 처음에는 함정·계산을 구분하지 않고 모두 "자료에 없는 수치"로 셌다. 결과를 보고 구분했다(수정 전 숫자와 다르다).', '',
          '| 후보 | 호출 | 자료 사용 | 함정 호출 | 함정 그냥 사용 | 계산 수치 호출 | 설명 안 되는 수치 호출 | 출처 누락 항목 | 기관 오표기 |',
          '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %s | %d | %d | %d | %d | %d | %d |' % (c, v['f_n'], _pct(v['f_used_rate']), v['f_trap_calls'], v['f_trap_plain_calls'],
                                                              v['f_derived_calls'], v['f_other_calls'], v['f_unsourced'], v['f_misattr']))
    L += ['', '## T-S2 목표 시장 분석 — 참고 자료 없음 (기억에 의존)', '',
          '- 수치 항목 수는 많을수록 좋은 것이 아니다. 이 조건의 수치는 사실인지 검증하지 못했다. 0개면 정성 서술만 한 것(규칙상 안전).', '',
          '| 후보 | 호출 | 수치 항목(호출당) | 수치 0개 호출 | 출처 누락 항목 | 불확실 표시 항목 | 입력에 없는 숫자 호출 |', '|---|---:|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %s | %d | %d | %d | %d |' % (c, v['o_n'], '-' if v['o_items_mean'] is None else '%.1f' % v['o_items_mean'],
                                                       v['o_zero_calls'], v['o_unsourced'], v['o_hedged'], v['o_unlisted_calls']))
    L += ['', '## 비용·시간', '', '| 후보 | 호출 | 형식 통과 | 시간(s) | 비용($) |', '|---|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %d | %s | %.3f |' % (c, v['calls'], v['valid'], '-' if v['sec'] is None else '%.1f' % v['sec'], v['cost']))
    failed = [(r, evaluate(r, cases[r['case']])) for r in rows]
    failed = [(r, e) for r, e in failed if not e['valid']]
    if failed:
        L += ['', '## 실패·형식 불량', ''] + ['- %s / %s / %s / rep%s: %s' % (r['candidate'], r['task'], r['case'], r['rep'], e['why']) for r, e in failed]
    return '\n'.join(L) + '\n'
