"""Information-preservation review signals, v2. No signal is NOT an acceptance.

Input: reference_text, candidate_text (no labels, IDs or dataset-specific term list).
CLI: python scripts/information_validator.py input.jsonl output.jsonl
"""
from collections import Counter
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import re
import sys

VERSION = 'information_validator_v2'
NUMBER = r'[+-]?\d[\d,]*(?:\.\d+)?'
QUANTITY = re.compile(rf'({NUMBER})\s*(천만|백만|십만|억|만|천|백)?\s*(원|명|개|회|분|시간|대|세|%|년|월|일)?')
SCALE = {'': 1, '백': 100, '천': 1000, '만': 10000, '십만': 100000, '백만': 1000000, '천만': 10000000, '억': 100000000}
# Whole constructions, not substring counts (e.g. 미디어 is not a negation).
CONCEPTS = {
    'possibility': r'가능|[을ㄹ]\s*수\s*(?:있|없)|할\s*수\s*(?:있|없)',
    'forecast': r'전망|예상|것으로\s*(?:보|보이)',
    'plan': r'계획|예정|목표|[하가]려[고는]',
    'consideration': r'검토|고려',
    'guarantee': r'보장|확정|확실시|반드시',
    'progress': r'진행\s*중|개발\s*중|협의\s*중',
    'imminence': r'임박|마무리\s*단계',
    'tax_excluded': r'부가세\s*별도|부가세\s*제외',
    'tax_included': r'부가세\s*포함',
}
CONDITION = re.compile(r'이상|이하|미만|초과|이내|경우에만|경우|달성\s*시|미선정\s*시|조건|에\s*한해')
LEXICAL = {'NNG', 'NNP', 'VV', 'VA', 'SL'}


@lru_cache(maxsize=4096)
def tokenize(text):
    from semantic_layers import tokens
    return tuple(tokens(text))


def normalize(text):
    text = text.translate(str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"'}))
    # Expand only explicit abbreviated dates; never infer the century.
    text = re.sub(r"'(\d{2})\.(\d{1,2})\.?(~)?", lambda m: f'{m[1]}년 {m[2]}월' + ('부터' if m[3] else ''), text)
    text = re.sub(r"'(\d{2})(?!\d)(?:년)?", r'\1년', text)
    return text


def quantities(text):
    result = []
    for m in QUANTITY.finditer(text):
        value = Decimal(m[1].replace(',', '')) * SCALE[m[2] or '']
        result.append({'value': str(value.normalize()), 'unit': m[3] or '',
                       'start': m.start(), 'end': m.end(), 'text': m[0]})
    return result


def words(text):
    return {t.form for t in tokenize(text) if t.tag in LEXICAL}


def clauses(text):
    return [x.strip() for x in re.split(r'\n|[;!?]|(?<=[다함임])\.(?:\s|$)', text) if x.strip()]


def negations(text):
    result = set()
    for t in tokenize(text):
        if t.form in {'않', '없', '못', '못하', '아니'}:
            result.add('negative')
        if t.form == '미' and t.tag.startswith('XPN'):
            result.add('negative')
    if re.search(r'미(?:체결|선정|확보|완료|달성)|불가능', text):
        result.add('negative')
    return result


def bindings(text, qs):
    """Nearest noun phrase preceding a quantity; compare only shared stable heads."""
    result = {}
    toks = tokenize(text)
    for q in qs:
        before = [t for t in toks if t.start + t.len <= q['start'] and t.tag in {'NNG', 'NNP'}]
        if before:
            t = before[-1]
            if q['start'] - (t.start + t.len) < 12:
                result.setdefault(t.form, []).append((q['value'], q['unit']))
    return {k: Counter(v) for k, v in result.items()}


def validate(reference_text, candidate_text):
    if not isinstance(reference_text, str) or not isinstance(candidate_text, str):
        raise TypeError('Both texts must be strings')
    if not reference_text.strip() or not candidate_text.strip():
        raise ValueError('Both texts must be nonempty')
    a, b = normalize(reference_text), normalize(candidate_text)
    signals = []

    def add(code, detail, before, after):
        signals.append({'code': code, 'detail': detail, 'reference_evidence': before, 'candidate_evidence': after})

    qa, qb = quantities(a), quantities(b)
    ca = Counter((q['value'], q['unit']) for q in qa)
    cb = Counter((q['value'], q['unit']) for q in qb)
    if ca != cb:
        add('quantity', '수치·단위 또는 등장 횟수 변화', [q['text'] for q in qa], [q['text'] for q in qb])
    ba, bb = bindings(a, qa), bindings(b, qb)
    for head in sorted(ba.keys() & bb.keys()):
        if ba[head] != bb[head] and ca == cb and ba[head].total() == bb[head].total():
            add('quantity_binding', '같은 대상에 연결된 수치 변화', {head: list(ba[head].elements())}, {head: list(bb[head].elements())})
    # Directed ranges are unaffected by reordering independent clauses.
    range_pattern = re.compile(r'(\d+)\s*(년|월|일|세|명|개)?\s*(부터|에서|중)\s*(?:\d+년\s*)?(\d+)\s*(년|월|일|세|명|개)?')
    ra = Counter((m[1], m[2], m[3], m[4], m[5]) for m in range_pattern.finditer(a))
    rb = Counter((m[1], m[2], m[3], m[4], m[5]) for m in range_pattern.finditer(b))
    if ra and rb and ra != rb:
        add('directed_range', '범위·모집단의 방향 변화', list(ra.elements()), list(rb.elements()))

    for name, pattern in CONCEPTS.items():
        ma, mb = re.findall(pattern, a), re.findall(pattern, b)
        if bool(ma) != bool(mb):
            add('concept_' + name, '상태·주장 강도·가격 조건의 의미 표지 변화', ma, mb)
    na, nb = negations(a), negations(b)
    # 미흡 / 충분하지 못함 are equivalent limitation constructions.
    if '미흡' in a:
        na.add('negative')
    if '미흡' in b:
        nb.add('negative')
    if na != nb:
        add('negation', '부정 상태 변화', sorted(na), sorted(nb))
    coa, cob = Counter(CONDITION.findall(a)), Counter(CONDITION.findall(b))
    if coa != cob:
        add('condition', '조건·한계 표지 변화', dict(coa), dict(cob))

    wa, wb = words(a), words(b)
    # Evidence for new claims: content overlap alone is never an acceptance.
    added = wb - wa
    removed = wa - wb
    added_nouns = {t.form for t in tokenize(b) if t.tag in {'NNG', 'NNP'}} - wa
    if len(added_nouns) >= 2 and len(added) >= len(removed) + 2:
        add('new_content', '여러 새 내용어: 주장·기능 추가인지 의미 검토 필요', sorted(removed), sorted(added))
    if len(removed) >= 3 and len(removed) > 2 * len(added) and len(removed) / max(len(wa), 1) >= .30:
        add('lost_content', '여러 내용어 소실: 동의 표현인지 정보 누락인지 확인', sorted(removed), sorted(added))

    # Predicate-to-subject changes using explicit particles. Require stable nouns
    # on both sides to avoid treating omitted particles as relation changes.
    subjects = re.compile(r'([가-힣]+(?:\s+[가-힣]+){0,2}?)(?:은|는|이|가)\s')
    sa = {tuple(sorted(words(m[1]))) for m in subjects.finditer(a)}
    sb = {tuple(sorted(words(m[1]))) for m in subjects.finditer(b)}
    if sa and sb and sa != sb and wa == wb:
        add('subject_relation', '내용어는 같지만 명시된 주체·주제 연결 변화', sorted(sa), sorted(sb))

    # Compare argument placement around causality markers, not marker counts.
    for marker, pattern in [('purpose', r'위해|위한'), ('condition_role', r'경우'),
                            ('dependence', r'따라'), ('means', r'통해')]:
        for x in clauses(a):
            mx = re.search(pattern, x)
            if not mx:
                continue
            left, right = words(x[:mx.start()]), words(x[mx.end():])
            if not left or not right:
                continue
            for y in clauses(b):
                my = re.search(pattern, y)
                if not my:
                    continue
                yl, yr = words(y[:my.start()]), words(y[my.end():])
                # Two or more anchor words crossing each side is a review signal.
                crossed = len(left & yr) + len(right & yl)
                straight = len(left & yl) + len(right & yr)
                if len(left & yr) >= 2 and len(right & yl) >= 2 and crossed > straight:
                    add('relation_' + marker, '수단·목적·조건의 양쪽 정보가 뒤바뀜', x, y)

    # A new explicit purpose connecting previously parallel statements.
    if not re.search(r'위해|위한|목적', a) and re.search(r'위해|위한|목적', b):
        add('new_purpose', '원문에 없던 목적 관계가 명시됨', a, b)
    return {'version': VERSION, 'flagged': bool(signals), 'signals': signals,
            'semantic_verdict': 'uncertain',
            'routing': 'review_signals' if signals else 'semantic_review_still_required'}


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: information_validator.py input.jsonl output.jsonl')
    source, output = map(Path, sys.argv[1:])
    if source.resolve() == output.resolve():
        raise ValueError('Output must differ from input')
    rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines() if line.strip()]
    results = [{**r, 'validation_v2': validate(r['reference_text'], r['candidate_text'])} for r in rows]
    output.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in results), encoding='utf-8')


if __name__ == '__main__':
    main()
