"""작성 Agent T-W1(본문)·T-W2(그래프)·T-W3(표) 시험 채점 — calls.jsonl(+judge.jsonl)을 읽어 후보별 지표를 계산한다. API 호출 없음.

전부 자동 판정이다. 글의 품질만 검증-1 채점자(judge.jsonl)의 점수를 따로 붙인다.

T-W1: 필수 섹션 1:1 · 최소 분량(150자, 잠정) · 분량 제한 · 금지 표현 · 단정형 종결 · 지어낸 수치 · 지어낸 경력 ·
      지원금 상한 · 기준 기능 목록 유지 · 기능·시장 자료 활용.
T-W2: 그래프의 수치가 본문·시장 분석에 적힌 값과 일치(재계산 대조) · 축 이름 · 근거 섹션.
T-W3: 행 칸 수 · 자금 운용표(합계 = 항목 합, 상한 이내, 본문 금액 그대로) · 일정표 존재.
수치 파서는 '1만 1천', '380만', '5천만 원', '11,000곳', '82%'를 값으로 바꾼다. 날짜(2026-11-30)와 시간 단위(개월·차)는 뺀다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from v3_strategy.score import _bigrams, reachable_values  # noqa: E402

MIN_CHARS = 150                       # 섹션 최소 분량(잠정, 기능정의서에 값이 없다)
TOL = 0.01                            # 수치 일치 허용 오차(1%)
_UNITS = {'조': 1e12, '억': 1e8, '천': 1e3, '백': 1e2, '만': 1e4}
_PHRASE = re.compile(r'(\d[\d,]*\.?\d*)\s*((?:조|억|만|천|백)+)?(?:\s+(\d[\d,]*\.?\d*)\s*((?:억|만|천|백)+))?')
_DATE = re.compile(r'\d{4}\s*[-./]\s*\d{1,2}(?:\s*[-./]\s*\d{1,2})?|\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?')
_TIME_UNITS = ('개월', '주', '차', '월', '일', '단계', '회', '가지', '시간', '분', '초', '위', '번', '호', '개년')
_COUNT_UNITS = ('%', '원', '곳', '가구', '개사', '만', '억')          # 한 자리 수는 이 단위일 때만 검사('1명', '1건'은 제외)
_END_BAD = re.compile(r'(다|요)\.?$')


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


def _scale(units: str | None) -> float:
    if not units:
        return 1.0
    s = 1.0
    for ch in units:
        s *= _UNITS[ch]
    return s


def parse_numbers(text: str) -> list[dict]:
    """글 속 수치를 {value, unit}으로 뽑는다. 날짜는 먼저 지운다."""
    text = _DATE.sub(' ', text)
    out = []
    for m in _PHRASE.finditer(text):
        v = float(m.group(1).replace(',', '')) * _scale(m.group(2))
        if m.group(3):
            v += float(m.group(3).replace(',', '')) * _scale(m.group(4))
        rest = text[m.end():m.end() + 6].lstrip()
        unit = re.match(r'[가-힣%A-Za-z]*', rest).group(0) if rest else ''
        if rest.startswith('%'):
            unit = '%'
        out.append({'value': v, 'unit': unit})
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOL * max(abs(b), 1e-9)


def _skippable(n: dict) -> bool:
    """검사에서 뺄 수치: 시간 단위(개월·차 등)와, 단위 없는 한 자리 수(항목 번호 등)."""
    if n['value'] <= 1:                         # '1곳당', '1건'처럼 단위당 표현의 1은 사실 주장이 아니다
        return True
    if n['unit'].startswith(_TIME_UNITS):
        return True
    if n['unit'].startswith('년'):
        return n['value'] >= 1900              # 연도. 경력 연수(8년)는 남긴다
    if n['value'] < 10 and not n['unit'].startswith(_COUNT_UNITS):
        return True
    return False


def allowed_values(case: dict) -> list[float]:
    """입력에 들어 있는 수치: 양식·아이템·자료·회사 정보·공고 + 자료로 계산할 수 있는 값."""
    spec = case['item_spec']
    texts = [json.dumps(spec, ensure_ascii=False), case['differentiator'], ' '.join(case['company']['representative_career']),
             ' '.join(case['company']['team_careers']), case['company']['development_period'],
             '{:,}'.format(case['company']['revenue_unit_price']), '{:,}'.format(case['announcement']['support_amount_max'])]
    for f in case['facts']:
        texts += [f['display'], f['label']]
    vals = [n['value'] for t in texts for n in parse_numbers(t)]
    vals += [float(f['value']) for f in case['facts']]
    vals += reachable_values(case)
    vals.append(float(case['company']['revenue_unit_price']))
    vals.append(float(case['announcement']['support_amount_max']))
    return vals


def _grounded(v: float, allowed: list[float]) -> bool:
    return any(_close(v, a) for a in allowed)


def sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+|\n+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def fund_check(amounts: list[float], max_amount: float, exclude: tuple = ()) -> tuple[float | None, bool]:
    """자금 운용 계획 글의 금액 목록 → (총액, 상한 초과 여부).
    가장 큰 금액을 '총액 또는 상한 언급'으로 보는 경우: 나머지 항목 합과 같거나, 지원규모 상한과 같거나, 두 번 이상 나온 경우.
    그때 항목 합은 나머지의 합이고, 아니면 모든 금액이 항목이다. 항목 합과 언급된 총액 중 하나라도 상한을 넘으면 초과."""
    amounts = [a for a in amounts if not any(abs(a - x) <= 1 for x in exclude)]        # 수익모델 단가 등은 사업비 항목이 아니다
    amounts = [a for a in amounts if abs(a - max_amount) > 1] + ([max_amount] if amounts and all(abs(a - max_amount) <= 1 for a in amounts) else [])   # 상한과 같은 금액은 상한 언급
    if not amounts:
        return None, False
    big = max(amounts)
    rest = [a for a in amounts if a != big]
    if not rest:                                                                       # 같은 금액만(상한·총액 언급)
        return big, bool(big > max_amount)
    if (abs(big - sum(rest)) <= 1 or big == max_amount or amounts.count(big) >= 2):
        items, stated = sum(rest), big
    else:
        items, stated = sum(amounts), None
    total = stated if stated is not None else items
    return total, bool(items > max_amount or (stated is not None and stated > max_amount))


def schedule_over(text: str, dev_period: str) -> bool:
    """추진 일정에 적힌 개월 수가 입력된 개발 기간(예: '8개월')을 넘으면 True. 기능정의서 필수 규칙은 아니고 관찰 지표다."""
    m = re.search(r'\d+', dev_period)
    if not m:
        return False
    months = [int(x) for x in re.findall(r'(\d+)\s*개월', text)]
    return bool(months and max(months) > int(m.group(0)))


# ── T-W1 ──────────────────────────────────────────────────
def section_numbers(code: str, text: str, case: dict, allowed: list[float] | None = None) -> tuple[list[str], list[str]]:
    """섹션 하나에서 입력에 없는 수치와 경력 연수를 찾는다. (지어낸 수치 표기들, 지어낸 경력 표기들). 자금 운용 계획(3-1)은 건너뛴다."""
    if code == '3-1':
        return [], []
    allowed = allowed if allowed is not None else allowed_values(case)
    career_years = [n['value'] for t in case['company']['representative_career'] + case['company']['team_careers'] for n in parse_numbers(t)]
    inv, car = [], []
    plain = _DATE.sub(' ', text)
    for m in _PHRASE.finditer(plain):
        v = float(m.group(1).replace(',', '')) * _scale(m.group(2))
        if m.group(3):
            v += float(m.group(3).replace(',', '')) * _scale(m.group(4))
        tail = plain[m.end():m.end() + 6]
        rest = tail.lstrip()
        unit = '%' if rest.startswith('%') else (re.match(r'[가-힣%A-Za-z]*', rest).group(0) if rest else '')
        n = {'value': v, 'unit': unit}
        label = plain[m.start():m.end() + (len(tail) - len(rest)) + len(unit)].strip()      # 본문에 그대로 있는 조각
        if unit.startswith('년') and code == '4-1' and v < 1900:
            if not _grounded(v, career_years):
                car.append(label)
            continue
        if _skippable(n) or re.match(r'\s*[~∼-]\s*\d', plain[m.end():m.end() + 4]):      # '11~12개월차'의 11
            continue
        if not _grounded(v, allowed):
            inv.append(label)
    return inv, car


def eval_w1(data: dict, case: dict) -> dict:
    if not isinstance(data.get('sections'), list) or not isinstance(data.get('feature_list'), list):
        return {'valid': False, 'why': '필드 형식 이상'}
    form = case['form']
    codes = [s['code'] for s in form['sections']]
    got = [s['section_code'] for s in data['sections']]
    missing = [c for c in codes if c not in got]
    extra = [c for c in got if c not in codes]
    dup = len(got) - len(set(got))
    by = {s['section_code']: s for s in data['sections']}
    body = [by[c] for c in codes if c in by]
    short = sum(1 for s in body if len(s['text']) < MIN_CHARS)
    mx = form['max_chars_per_section']
    over = sum(1 for s in body if mx and len(s['text']) > mx)
    full = '\n'.join(s['text'] for s in data['sections'])
    banned = sum(full.count(b) for b in form['format']['banned_expressions'])
    sents = [x for s in body for x in sentences(s['text'])]
    bad_end = sum(1 for x in sents if _END_BAD.search(x))
    # 지어낸 수치·경력 (자금 운용 계획 섹션은 금액 계획이라 따로 본다)
    invented, invented_career = 0, 0
    for s in body:
        inv, car = section_numbers(s['section_code'], s['text'], case)
        invented += len(inv)
        invented_career += len(car)
    # 지원금 상한
    fund = by.get('3-1')
    amounts = [n['value'] for n in parse_numbers(fund['text']) if n['unit'].startswith('원') and n['value'] >= 1000] if fund else []
    total, fund_over = fund_check(amounts, case['announcement']['support_amount_max'], (float(case['company']['revenue_unit_price']),))
    # 기준 기능 목록·자료 활용
    core = case['item_spec']['core_features']
    fl = data['feature_list']
    list_same = sorted(x.strip() for x in fl) == sorted(x.strip() for x in core)
    sent_bg = [_bigrams(x) for x in sents]
    covered = sum(1 for c in core if any(len(_bigrams(c) & b) / len(_bigrams(c)) >= 0.75 for b in sent_bg))
    doc_vals = [n['value'] for n in parse_numbers(full)]
    used_facts = sum(1 for f in case['facts'] if any(_close(v, float(f['value'])) for v in doc_vals))
    cited = sum(1 for f in case['facts'] if f['source'].split()[0] in full)
    sched = by.get('3-3')
    sched_over = bool(sched and schedule_over(sched['text'], case['company']['development_period']))
    hard = (not missing and not extra and not dup and not fund_over and list_same and invented_career == 0)
    return {'valid': True, 'missing': len(missing), 'extra': len(extra), 'dup': dup, 'short': short, 'over': over,
            'banned': banned, 'bad_end_rate': (bad_end / len(sents)) if sents else 0.0, 'n_sent': len(sents),
            'invented': invented, 'invented_career': invented_career, 'fund_total': total, 'fund_over': fund_over,
            'list_same': list_same, 'coverage': covered / len(core), 'facts_used': used_facts / len(case['facts']),
            'facts_cited': cited / len(case['facts']), 'chars': len(full), 'hard_ok': hard, 'sched_over': sched_over}


# ── T-W2 ──────────────────────────────────────────────────
def doc_values(case: dict) -> list[float]:
    text = '\n'.join(s['text'] for s in case['fixed_doc'])
    return [n['value'] for n in parse_numbers(text)] + [float(f['value']) for f in case['facts']]


def chart_values(case: dict) -> list[float]:
    """그래프 수치로 인정하는 값: 본문·자료의 수치 + 비율(%)의 나머지(100 - x, 원형 그래프용)."""
    vals = doc_values(case)
    pcts = [float(f['value']) for f in case['facts'] if f['unit'] == '%']
    return vals + [100 - p for p in pcts]


def eval_w2(data: dict, case: dict) -> dict:
    charts = data.get('charts')
    if not isinstance(charts, list):
        return {'valid': False, 'why': 'charts 형식 이상'}
    vals = chart_values(case)
    codes = [s['section_code'] for s in case['fixed_doc']]
    pts = invented = bad_axis = bad_ref = empty = 0
    for ch in charts:
        ax = ch.get('axis_labels') or []
        if len(ax) != 2 or not all(str(a).strip() for a in ax):
            bad_axis += 1
        m = re.search(r'\d+-\d+', str(ch.get('source_ref', '')))          # '2-1', '[2-1]', '섹션 2-1' 모두 인정
        if not m or m.group(0) not in codes:
            bad_ref += 1
        if not ch.get('series'):
            empty += 1
        for p in ch.get('series', []):
            pts += 1
            if not any(_close(float(p['value']), v) for v in vals):
                invented += 1
    ok = len(charts) >= 1 and not (invented or bad_axis or bad_ref or empty)
    return {'valid': True, 'n_charts': len(charts), 'points': pts, 'invented': invented, 'bad_axis': bad_axis,
            'bad_ref': bad_ref, 'empty': empty, 'ok': ok}


# ── T-W3 ──────────────────────────────────────────────────
def _money_cells(row: list[str]) -> list[float]:
    return [n['value'] for c in row for n in parse_numbers(c) if n['unit'].startswith('원') and n['value'] >= 1000]


def eval_w3(data: dict, case: dict) -> dict:
    tables = data.get('tables')
    if not isinstance(tables, list):
        return {'valid': False, 'why': 'tables 형식 이상'}
    row_bad = sum(1 for t in tables for r in t.get('rows', []) if len(r) != len(t.get('headers', [])))
    fund = next((t for t in tables if '자금' in t.get('title', '') or any('금액' in h for h in t.get('headers', []))), None)
    sched = next((t for t in tables if '일정' in t.get('title', '')), None)
    line_amounts = [float(f['amount']) for f in case['funds']]
    max_amount = case['announcement']['support_amount_max']
    ev = {'valid': True, 'n_tables': len(tables), 'row_bad': row_bad, 'has_fund': fund is not None, 'has_sched': sched is not None,
          'sum_mismatch': False, 'over': False, 'invented_amounts': 0, 'lines_found': 0.0, 'fund_total': None}
    if fund:
        total_row, items = None, []
        heads = fund.get('headers', [])
        col = next((i for i, h in enumerate(heads) if '금액' in h or '비용' in h), None)     # 금액 열이 있으면 그 칸을 본다
        for r in fund.get('rows', []):
            amt = _money_cells([r[col]]) if col is not None and col < len(r) else _money_cells(r)
            if not amt:
                continue
            if any(('합계' in c or c.strip() == '총계' or '총액' in c) for c in r):
                total_row = amt[0]
            else:
                items.append(amt[0])
        total = total_row if total_row is not None else (sum(items) if items else None)
        ev['fund_total'] = total
        ev['sum_mismatch'] = bool(total_row is not None and items and abs(total_row - sum(items)) > 1)
        ev['over'] = bool(total is not None and total > max_amount)
        ev['invented_amounts'] = sum(1 for a in items if not any(_close(a, x) for x in line_amounts))
        ev['lines_found'] = sum(1 for x in line_amounts if any(_close(x, a) for a in items)) / len(line_amounts)
    ev['ok'] = bool(fund and sched and not row_bad and not ev['sum_mismatch'] and not ev['over'] and not ev['invented_amounts'])
    return ev


def evaluate(row: dict, case: dict) -> dict:
    if not row.get('ok'):
        return {'valid': False, 'why': row.get('error')}
    return {'w1': eval_w1, 'w2': eval_w2, 'w3': eval_w3}[row['task']](row['data'], case)


# ── 집계 ─────────────────────────────────────────────────
def judge_scores(judge_rows: list[dict], rubric: dict) -> dict[str, dict]:
    """judge.jsonl → {원본 W1 호출 key: {'total': 합, 'items': {코드: 점수}}}."""
    from v1_verifier import score as v1score
    out = {}
    for r in judge_rows:
        if r.get('ok'):
            sc = v1score.item_scores(r['data'], rubric)
            if sc is not None:
                out[r['src']] = {'total': sum(sc.values()), 'items': sc}
    return out


def compute(rows: list[dict], cases: dict[str, dict], judge: dict[str, dict] | None = None) -> dict[str, dict]:
    judge = judge or {}
    by = defaultdict(list)
    for r in rows:
        by[r['candidate']].append(r)
    out = {}
    for cand, rs in by.items():
        ev = [(r, evaluate(r, cases[r['case']])) for r in rs]

        def sel(t):
            return [(r, e) for r, e in ev if r['task'] == t and e['valid']]
        w1, w2, w3 = sel('w1'), sel('w2'), sel('w3')
        ms = [r['usage']['ms'] for r in rs if r.get('ok')]
        js = [judge[r['key']]['total'] for r, _ in w1 if r['key'] in judge]

        def rate(pairs, f):
            return _mean([1 if f(e) else 0 for _, e in pairs])
        out[cand] = {
            'calls': len(rs), 'ok': sum(1 for r in rs if r.get('ok')), 'valid': sum(1 for _, e in ev if e['valid']),
            'w1_n': len(w1), 'w1_hard_ok': rate(w1, lambda e: e['hard_ok']), 'w1_missing_calls': sum(1 for _, e in w1 if e['missing'] or e['extra'] or e['dup']),
            'w1_short_calls': sum(1 for _, e in w1 if e['short']), 'w1_over_calls': sum(1 for _, e in w1 if e['over']),
            'w1_banned_calls': sum(1 for _, e in w1 if e['banned']), 'w1_bad_end': _mean([e['bad_end_rate'] for _, e in w1]),
            'w1_invented_calls': sum(1 for _, e in w1 if e['invented']), 'w1_invented': _mean([e['invented'] for _, e in w1]),
            'w1_career_calls': sum(1 for _, e in w1 if e['invented_career']), 'w1_sched_over': sum(1 for _, e in w1 if e['sched_over']), 'w1_fund_over': sum(1 for _, e in w1 if e['fund_over']),
            'w1_list_same': rate(w1, lambda e: e['list_same']), 'w1_coverage': _mean([e['coverage'] for _, e in w1]),
            'w1_facts_used': _mean([e['facts_used'] for _, e in w1]), 'w1_facts_cited': _mean([e['facts_cited'] for _, e in w1]),
            'w1_chars': _mean([e['chars'] for _, e in w1]), 'judge': _mean(js), 'judge_n': len(js),
            'w2_n': len(w2), 'w2_ok': rate(w2, lambda e: e['ok']), 'w2_charts': _mean([e['n_charts'] for _, e in w2]),
            'w2_invented_calls': sum(1 for _, e in w2 if e['invented']), 'w2_none': sum(1 for _, e in w2 if e['n_charts'] == 0),
            'w2_bad': sum(1 for _, e in w2 if e['bad_axis'] or e['bad_ref'] or e['empty']),
            'w3_n': len(w3), 'w3_ok': rate(w3, lambda e: e['ok']), 'w3_missing_table': sum(1 for _, e in w3 if not (e['has_fund'] and e['has_sched'])),
            'w3_row_bad': sum(1 for _, e in w3 if e['row_bad']), 'w3_over': sum(1 for _, e in w3 if e['over']),
            'w3_sum_bad': sum(1 for _, e in w3 if e['sum_mismatch']), 'w3_invented': sum(1 for _, e in w3 if e['invented_amounts']),
            'sec': (_mean(ms) / 1000) if ms else None,
            'cost': sum(r.get('cost', 0) or 0 for r in rs),
        }
    return out


def _pct(x):
    return '-' if x is None else '%.0f%%' % (100 * x)


def _f(x, n=1):
    return '-' if x is None else '%.*f' % (n, x)


def summarize(rows: list[dict], cases: dict[str, dict], judge: dict[str, dict] | None = None, judge_cost: float = 0.0) -> str:
    m = compute(rows, cases, judge)
    L = ['# 작성 T-W1·T-W2·T-W3 모델 비교 결과', '',
         '전부 자동 판정이고, 글의 품질만 검증-1 채점자(luna-medium)의 점수를 따로 붙였다. 아이템·회사·수치는 모두 시험용 가상 값이다.', '',
         '## T-W1 사업계획서 본문', '',
         '- 필수 규칙 통과 = 섹션이 양식과 1:1 · 지원금 상한 이내 · 기준 기능 목록을 글자 그대로 유지 · 지어낸 경력 없음.',
         '- 지어낸 수치: 입력·참고 자료·자료로 계산 가능한 값 밖의 수치를 쓴 호출(자금 계획 섹션은 제외). 종결 위반: 문장 중 "~다/~요"로 끝난 비율.',
         '- 채점자 점수: 검증-1 rubric(70점 만점). **채점자도 luna-medium이라 luna 계열을 후하게 볼 수 있다.**', '',
         '| 후보 | 호출 | 필수 규칙 통과 | 섹션 어긋남 | 상한 초과 | 목록 유지 | 지어낸 경력 | 지어낸 수치 호출 | 종결 위반 | 금지 표현 | 분량 초과 | 자료 활용 | 채점자 점수 |',
         '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %s | %d | %d | %s | %d | %d | %s | %d | %d | %s | %s |' % (
            c, v['w1_n'], _pct(v['w1_hard_ok']), v['w1_missing_calls'], v['w1_fund_over'], _pct(v['w1_list_same']), v['w1_career_calls'],
            v['w1_invented_calls'], _pct(v['w1_bad_end']), v['w1_banned_calls'], v['w1_over_calls'], _pct(v['w1_facts_used']), _f(v['judge'])))
    L += ['', '- 관찰 지표(필수 규칙 아님): 추진 일정이 입력된 개발 기간을 넘긴 호출 — ' + ', '.join('%s %d/%d' % (c, v['w1_sched_over'], v['w1_n']) for c, v in m.items()) + '. 결과를 본 뒤 추가한 지표다.']
    L += ['', '## T-W2 그래프', '', '- 통과 = 그래프가 1개 이상이고, 모든 수치가 본문·시장 분석에 적힌 값과 일치하며, 축 이름 2개·근거 섹션이 채워짐.', '',
          '| 후보 | 호출 | 통과 | 그래프 수(호출당) | 지어낸 수치 호출 | 필드 불량 호출 | 그래프 없음 |', '|---|---:|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %s | %s | %d | %d | %d |' % (c, v['w2_n'], _pct(v['w2_ok']), _f(v['w2_charts']), v['w2_invented_calls'], v['w2_bad'], v['w2_none']))
    L += ['', '## T-W3 표', '', '- 통과 = 자금 운용표·일정표가 있고, 행 칸 수가 맞고, 합계 행이 항목 합과 같고, 상한 이내이고, 금액이 본문에 적힌 것만임.', '',
          '| 후보 | 호출 | 통과 | 표 누락 | 칸 수 불일치 | 합계 불일치 | 상한 초과 | 지어낸 금액 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %s | %d | %d | %d | %d | %d |' % (c, v['w3_n'], _pct(v['w3_ok']), v['w3_missing_table'], v['w3_row_bad'],
                                                           v['w3_sum_bad'], v['w3_over'], v['w3_invented']))
    L += ['', '## 비용·시간', '', '| 후보 | 호출 | 형식 통과 | 본문 평균 글자 수 | 시간(s) | 비용($) |', '|---|---:|---:|---:|---:|---:|']
    for c, v in m.items():
        L.append('| %s | %d | %d | %s | %s | %.3f |' % (c, v['calls'], v['valid'], _f(v['w1_chars'], 0), _f(v['sec']), v['cost']))
    if judge_cost:
        L.append('\n채점자(luna-medium) 호출 비용은 별도로 $%.3f.' % judge_cost)
    failed = [(r, evaluate(r, cases[r['case']])) for r in rows]
    failed = [(r, e) for r, e in failed if not e['valid']]
    if failed:
        L += ['', '## 실패·형식 불량', ''] + ['- %s / %s / %s / rep%s: %s' % (r['candidate'], r['task'], r['case'], r['rep'], e['why']) for r, e in failed]
    return '\n'.join(L) + '\n'
