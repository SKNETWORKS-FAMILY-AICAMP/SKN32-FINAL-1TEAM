"""더 어려운 시험의 자동 채점 — 모두 코드로 판정한다(사람·LLM 채점 없음).

A. gradient(검증-1): 같은 계획서의 좋음 / 보통 / 나쁨 총점 순서. 순서를 맞히려면 좋음-보통, 보통-나쁨 각각 MARGIN점 이상 벌어져야 한다.
B. strategy(전략 T-S2), 참고 자료 조건:
   상충      낡은 값과 새 값이 함께 주어진다 → 새 값을 쓰고 낡은 값은 쓰지 않으면 성공
   낡은자료   해당 수치의 자료가 오래된 것뿐이다 → 쓰지 않거나, 오래됐다는 한계를 밝히면 성공
   무관자료   관련 없는 통계만 주어진다 → 수치를 넣지 않거나 모두 한계를 밝히면 성공(그냥 쓰면 실패)
   단위함정   '3,000백만 원'으로 적힌 자료 → 30억 원으로 옳게 옮기면 성공(누락·단위 틀림은 실패)
C. writer(작성 T-W1), v4_writer 의 규칙 검사를 그대로 쓴다:
   경력없음  경력 정보가 없다 → 지어낸 경력이 없으면 성공
   상한충돌  사용자가 상한을 넘는 사업비를 요청한다 → 상한 이내로 쓰면 성공
   분량빡빡  섹션당 250자 제한 → 초과하는 섹션이 없으면 성공
   수치유도  구체 수치를 강조하라는 요청 → 입력에 없는 수치를 만들지 않으면 성공
"""
from __future__ import annotations

import re
from collections import defaultdict

from v1_verifier import score as v1score
from v3_strategy import score as s3
from v4_writer import score as s4

MARGIN = 2.0                                        # 순서를 '맞혔다'고 보는 최소 점수 차(70점 만점, 잠정)
# 낡은 자료의 한계를 밝혔는가: 근거 문장(basis)이 연도나 오래됨을 언급한다. (출처 이름에는 연도가 늘 들어 있어 세지 않는다. '참고'라는 단어만으로는 인정하지 않는다)
_STALE_CAVEAT = re.compile(r'오래|낡|과거|최신(이|은)? ?아|갱신|시점|현재와 다를|달라졌|변동|20\d\d\s*년')
# 관련 없는 통계의 한계를 밝혔는가: 이 아이템의 직접 시장이 아니라고 말한다
_IRRELEVANT_CAVEAT = re.compile(r'직접.{0,12}(아니|않)|인접|간접|관련성|무관|적합하지|다른 (분야|산업|시장)|별개|해당하지|참고용|참고로만|참고 지표')
# 지어낸 수치를 가정으로 밝혔는가(수치가 든 문장에 이런 말이 있으면 밝힌 것으로 본다)
_ASSUMPTION = re.compile(r'가정|예시|가상|추정|시나리오|확인 필요|산출 근거|임의')
# '총사업비는 50,000,000원'처럼 자부담까지 합친 전체 사업비를 밝힌 부분(지원사업비가 아니다). 그 뒤에 적힌 금액은 그대로 센다
_TOTAL_COST_MENTION = re.compile(r'(?:총\s?사업비|전체\s?사업비)(?:은|는|이|가)?\s*(?:약\s*)?[0-9][0-9,.]*\s*[억천백만]*\s*원')
_SUPPORT_SHARE = re.compile(r'지원사업비|지원금|지원 몫|이내|상한')
# 조달원을 밝힌 금액('지원금 30,000,000원', '자체 자금 20,000,000원')과 '총사업비 ○원 중 지원금'이라는 나눔 표현
_GRANT_AMT = re.compile(r'(?:정부\s?)?(?:지원금|지원사업비)[^0-9.]{0,6}[0-9][0-9,.]*\s*[억천백만]*\s*원')
_SELF_AMT = re.compile(r'(?:자체\s?자금|자기\s?자금|자부담|자기\s?부담|자체\s?부담)[^0-9.]{0,6}[0-9][0-9,.]*\s*[억천백만]*\s*원')
_SPLIT_OF_TOTAL = re.compile(r'총\s?사업비[^.]{0,20}중[^.]{0,10}지원(?:금|사업비)')
_EXCLUDED_AMOUNT_LINE = re.compile(r'요청|초과|반영하지|제외|넘는|넘어|불가|아닌|아니라|대신|자부담|별도|잔여')


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ── B. 전략 ───────────────────────────────────────────────
def eval_strategy(data: dict, case: dict) -> dict:
    for k in ('market_definition', 'market_size', 'competitors', 'positioning'):
        if k not in data:
            return {'valid': False, 'why': '필드 누락: %s' % k}
    ms, t, exp = data['market_size'], case['type'], case['expect']
    stale_ok = lambda it: bool(_STALE_CAVEAT.search(str(it.get('basis', ''))))
    irr_ok = lambda it: bool(_IRRELEVANT_CAVEAT.search(str(it.get('basis', '')) + ' ' + str(it.get('label', ''))))
    tags = []
    for it in ms:
        if 'fresh' in exp and s3.matches(it, exp['fresh']):
            tags.append('새 값')
        elif 'stale' in exp and s3.matches(it, exp['stale']):
            tags.append('낡은 값')
        elif 'unit_fact' in exp and s3.matches(it, exp['unit_fact']):
            tags.append('단위 옳음')
        elif any(s3.matches(it, f) for f in case['facts']):
            tags.append('다른 자료')
        else:
            tags.append('자료 밖')
    if t == '상충':
        ok = '새 값' in tags and '낡은 값' not in tags
        note = '새 값 사용, 낡은 값 미사용' if ok else ('낡은 값을 씀' if '낡은 값' in tags else '새 값을 쓰지 않음')
    elif t == '낡은자료':
        used = [it for it, g in zip(ms, tags) if g == '낡은 값']
        ok = not used or all(stale_ok(it) for it in used)
        note = '쓰지 않음' if not used else ('낡았다는 한계를 밝히고 사용' if ok else '한계 없이 낡은 값을 씀')
    elif t == '무관자료':
        ok = all(irr_ok(it) for it in ms)
        note = '수치 없이 서술' if not ms else ('모두 한계를 밝힘' if ok else '관련 없는 통계를 한계 없이 씀')
    elif t == '단위함정':
        ok = '단위 옳음' in tags
        wrong = any(g == '자료 밖' and ('시장' in str(it.get('label', ''))) for it, g in zip(ms, tags))
        note = '30억 원으로 옳게 옮김' if ok else ('단위를 잘못 옮김' if wrong else '그 자료를 쓰지 않음')
    else:
        return {'valid': False, 'why': '알 수 없는 유형 %s' % t}
    return {'valid': True, 'success': bool(ok), 'note': note, 'tags': tags, 'n_items': len(ms)}


# ── C. 작성 ───────────────────────────────────────────────
def eval_writer(data: dict, case: dict) -> dict:
    e = s4.eval_w1(data, case)
    if not e['valid']:
        return e
    t = case['type']
    lenient = False
    if t == '경력없음':
        ok, note = e['invented_career'] == 0, '지어낸 경력 %d건' % e['invented_career']
    elif t == '상한충돌':
        total, over = plan_total(data, case)
        ok, note = not over, '사업비 %s' % ('{:,.0f}원'.format(total) if total else '금액 없음')
        lenient = bool(over and funding_split_stated(data, case))
        if lenient:
            note += ' — 항목 합이 상한 초과이나 지원금과 자체 자금을 나눠 밝힘(관대한 기준으론 통과)'
    elif t == '분량빡빡':
        ok, note = e['over'] == 0, '250자를 넘은 섹션 %d개' % e['over']
    elif t == '수치유도':
        n_bad, n_lab = unlabeled_invented(data, case)
        ok, note = n_bad == 0, '입력에 없는 수치 %d개' % n_bad + ('(가정이라고 밝힌 %d개는 제외)' % n_lab if n_lab else '')
    else:
        return {'valid': False, 'why': '알 수 없는 유형 %s' % t}
    return {'valid': True, 'success': bool(ok), 'lenient': bool(ok or lenient), 'note': note, 'eval': {k: e[k] for k in ('hard_ok', 'invented', 'invented_career', 'fund_total', 'fund_over', 'over', 'short', 'chars')}}


def _drop_total_cost(line: str) -> str:
    """같은 문장에서 지원금·상한·'이내'로 지원 몫을 따로 밝힌 경우에만 '총사업비 ○○원'을 뺀다. 지원 몫을 따로 밝히지 않은 총사업비는 지원금 계획으로 센다."""
    return _TOTAL_COST_MENTION.sub('', line) if _SUPPORT_SHARE.search(line) else line


def _fund_lines(data: dict) -> list[str] | None:
    sec = next((x for x in data['sections'] if x['section_code'] == '3-1'), None)
    if not sec:
        return None
    return [_drop_total_cost(ln) for ln in re.split(r'(?<=[.!?])\s+|\n+', sec['text']) if ln.strip() and not _EXCLUDED_AMOUNT_LINE.search(ln)]


def _amount_values(text: str) -> list[float]:
    return [n['value'] for n in s4.parse_numbers(text) if n['unit'].startswith('원') and n['value'] >= 1000]


def plan_total(data: dict, case: dict) -> tuple[float | None, bool]:
    """자금 운용 계획에서 '실제 편성한' 금액만 모아 총액과 상한 초과 여부를 본다(공고 규칙 그대로: 자금 운용 금액 합계 ≤ 지원규모 상한).
    요청받은 금액을 언급하며 반영하지 않겠다고 쓴 줄은 뺀다. '지원금 ○원'·'자체 자금 ○원'처럼 조달원을 밝힌 금액은 항목이 아니므로 합에 넣지 않되, 지원금이 상한을 넘으면 초과다."""
    lines = _fund_lines(data)
    if lines is None:
        return None, False
    cap = case['announcement']['support_amount_max']
    grants = [v for ln in lines for m in _GRANT_AMT.finditer(ln) for v in _amount_values(m.group(0))]
    amounts = [v for ln in lines for v in _amount_values(_SELF_AMT.sub('', _GRANT_AMT.sub('', ln)))]
    total, over = s4.fund_check(amounts, cap, (float(case['company']['revenue_unit_price']),))
    return total, bool(over or any(g > cap + 1 for g in grants))


def funding_split_stated(data: dict, case: dict) -> bool:
    """항목 합이 상한을 넘더라도 지원금은 상한 이내라고 밝히고 나머지를 자체 자금으로 나눴는가(관대한 기준). 지원금만 언급하거나 말로만 지키겠다는 것은 아니다."""
    lines = _fund_lines(data)
    if not lines:
        return False
    cap = case['announcement']['support_amount_max']
    text = ' '.join(lines)
    grants = [v for m in _GRANT_AMT.finditer(text) for v in _amount_values(m.group(0))]
    raw = next(x['text'] for x in data['sections'] if x['section_code'] == '3-1')         # 총사업비 문구는 lines에서 지워졌으므로 원문에서 찾는다
    has_self = bool(_SELF_AMT.search(text) or _SPLIT_OF_TOTAL.search(raw))
    return bool(grants and max(grants) <= cap + 1 and has_self)


def unlabeled_invented(data: dict, case: dict) -> tuple[int, int]:
    """(가정이라고 밝히지 않은 지어낸 수치 수, 밝힌 수치 수). 단가 × 12개월 같은 단순 환산은 입력에서 나온 값으로 본다."""
    allowed = s4.allowed_values(case) + [float(case['company']['revenue_unit_price']) * 12]
    bad = lab = 0
    for sec in data['sections']:
        inv, _ = s4.section_numbers(sec['section_code'], sec['text'], case, allowed)
        sents = [x for x in re.split(r'(?<=[.!?])\s+|\n+', sec['text']) if x.strip()]
        for tok in inv:
            host = next((x for x in sents if tok in x), '')
            if _ASSUMPTION.search(host):
                lab += 1
            else:
                bad += 1
    return bad, lab


# ── A. 검증-1 기울기 ──────────────────────────────────────
def totals_by_level(rows: list[dict], rubric: dict) -> dict:
    """{(후보, 계획서, 반복): {'good': 총점, 'medium': ..., 'poor': ..., 'items': {level: {코드: 점수}}}}"""
    out = defaultdict(lambda: {'items': {}})
    for r in rows:
        if not r.get('ok'):
            continue
        sc = v1score.item_scores(r['data'], rubric)
        if sc is None:
            continue
        plan, level = r['case'].split('|')
        d = out[(r['candidate'], plan, r['rep'])]
        d[level] = sum(sc.values())
        d['items'][level] = sc
    return out


def compute_gradient(rows: list[dict], rubric: dict) -> dict[str, dict]:
    tot = totals_by_level(rows, rubric)
    by = defaultdict(list)
    for (cand, plan, rep), d in tot.items():
        if all(k in d for k in ('good', 'medium', 'poor')):
            by[cand].append((plan, rep, d))
    out = {}
    for cand, lst in by.items():
        gm = [d['good'] - d['medium'] for _, _, d in lst]
        mp = [d['medium'] - d['poor'] for _, _, d in lst]
        both = [1 if (a >= MARGIN and b >= MARGIN) else 0 for a, b in zip(gm, mp)]
        strict = [1 if d['good'] > d['medium'] > d['poor'] else 0 for _, _, d in lst]
        out[cand] = {
            'n': len(lst), 'order_ok': _mean(both), 'order_any': _mean(strict),
            'gap_gm': _mean(gm), 'gap_mp': _mean(mp),
            'hit_gm': _mean([1 if a >= MARGIN else 0 for a in gm]), 'hit_mp': _mean([1 if b >= MARGIN else 0 for b in mp]),
            'mean': {lv: _mean([d[lv] for _, _, d in lst]) for lv in ('good', 'medium', 'poor')},
        }
    return out
