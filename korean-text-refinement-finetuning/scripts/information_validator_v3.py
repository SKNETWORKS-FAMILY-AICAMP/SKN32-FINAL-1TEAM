"""Grounded information-preservation review signals. Keeps frozen v2 unchanged.

Still a heuristic, body-only reviewer, never a semantic acceptance classifier.
Low-specificity lexical/marker observations are retained separately from alerts.
"""
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re
import sys

import information_validator as v2

VERSION = 'information_validator_v3'
REPLACED = {'new_content', 'new_purpose', 'subject_relation', 'quantity_binding'}
NOUN = {'NNG', 'NNP', 'SL', 'SH'}
# Generic grammatical support vocabulary, not institution or case-specific names.
SUPPORT = {'일', '것', '수', '등', '한편', '각각', '해당', '경우',
           '측면', '안', '내부', '아래', '시일', '하', '되', '있', '없',
           '이루어지', '통하', '위하', '지니', '갖추'}
ELABORATION = {'방식', '과정', '기준', '목적', '구성', '참여'}
EQUIVALENCES = {'신설': '설치', '조속하': '빠르', '조속히': '빠르', '조속': '빠르',
                '다양': '여러', '제고': '높이', '경감': '덜',
                '지속': '계속', '확대': '넓히', '늘리': '넓히'}


def signal(code, detail, a, b):
    return {'code': code, 'detail': detail, 'reference_evidence': a, 'candidate_evidence': b}


def compact(text):
    return re.sub(r'[^가-힣a-zA-Z0-9]', '', text)


@lru_cache(maxsize=4096)
def content(text):
    return frozenset(EQUIVALENCES.get(t.form, t.form) for t in v2.tokenize(text)
                     if (t.tag in v2.LEXICAL or t.form == '계속') and t.form not in SUPPORT)


def differences(a, b):
    wa, wb = set(content(a)), set(content(b))
    # Re-tokenizing compounds must not create new facts. Only multi-character
    # forms can be matched as a surface substring; single syllables are unsafe.
    ca, cb = compact(a), compact(b)
    def compound_parts(text, other):
        ts = list(v2.tokenize(text))
        covered = set()
        for i in range(len(ts)):
            parts = []
            for t in ts[i:i + 4]:
                if t.tag not in NOUN:
                    break
                parts.append(t.form)
                if len(parts) >= 2 and ''.join(parts) in other:
                    covered.update(parts)
        return covered
    added = {w for w in wb - wa if not (len(w) >= 2 and w in ca)} - compound_parts(b, ca)
    removed = {w for w in wa - wb if not (len(w) >= 2 and w in cb)} - compound_parts(a, cb)
    return added, removed


def noun_phrase_before(tokens, index):
    forms = []
    for t in reversed(tokens[:index]):
        if t.tag in NOUN or t.tag in {'SN', 'NR', 'XSN'}:
            forms.append(t.form)
        elif t.tag in {'JC', 'JKG'}:
            continue
        else:
            break
    return tuple(reversed(forms))


def predicate_forms(tokens):
    result = []
    for i, t in enumerate(tokens):
        if t.tag in {'VV', 'VA'} and t.form not in SUPPORT:
            result.append(t.form)
        elif t.tag in {'XSV', 'XSA'} and i and tokens[i - 1].tag in NOUN:
            result.append(tokens[i - 1].form)
    return result


def same_argument(a, b):
    aa, bb = ''.join(a), ''.join(b)
    return set(a) <= set(b) or set(b) <= set(a) or (len(aa) >= 2 and len(bb) >= 2 and (aa.endswith(bb) or bb.endswith(aa)))


def particle_frames(text):
    frames = defaultdict(set)
    # A line/sentence is the upper scope; conjunctive predicate ends delimit the
    # nearest predicate associated with an explicit particle.
    for clause in [piece for c in v2.clauses(text) for piece in re.split(r',(?=\D)', c)]:
        ts = list(v2.tokenize(clause))
        for i, t in enumerate(ts):
            role = ('subject' if t.tag == 'JKS' or (t.tag == 'JX' and t.form in {'은', '는'})
                    else 'object' if t.tag == 'JKO' else None)
            if not role:
                continue
            np = noun_phrase_before(ts, i)
            if not np:
                continue
            tail = []
            for after in ts[i + 1:]:
                if after.tag == 'EC' and after.form in {'고', '며', '면서', '지만'}:
                    break
                tail.append(after)
            # If another subject introduces an embedded attributive clause,
            # the earlier subject belongs to the predicate after that clause.
            if role == 'subject':
                next_subject = next((j for j, t in enumerate(tail) if t.tag == 'JKS'), None)
                if next_subject is not None:
                    end = next((j for j, t in enumerate(tail) if j > next_subject and t.tag == 'ETM'), None)
                    if end is not None:
                        tail = tail[end + 1:]
            # A purpose/means or attributive support verb must not bind the
            # object's NP to a later, unrelated predicate.
            first = next((t for t in tail if t.tag in {'VV', 'VA', 'XSV', 'XSA'}), None)
            if first is not None and first.tag in {'VV', 'VA'} and first.form in SUPPORT:
                continue
            preds = predicate_forms(tail)
            if preds:
                frames[(role, preds[0])].add(np)
    return frames


def subject_signals(a, b):
    fa, fb = particle_frames(a), particle_frames(b)
    result = []
    for key in sorted(fa.keys() & fb.keys()):
        missing = {x for x in fa[key] if not any(same_argument(x, y) for y in fb[key])}
        added = {y for y in fb[key] if not any(same_argument(x, y) for x in fa[key])}
        # Requiring an actual replacement avoids treating omitted arguments
        # becoming explicit as a role swap.
        if missing and added:
            result.append(signal('argument_binding', '같은 술어에 연결된 명시적 주체·대상 변화',
                                 {'role': key[0], 'predicate': key[1], 'arguments': sorted(fa[key])},
                                 {'role': key[0], 'predicate': key[1], 'arguments': sorted(fb[key])}))
    return result


def local_left(text):
    # Drop earlier parallel clauses; retain an entire noun phrase as purpose.
    text = re.sub(r'^\s*[ㅇ◦-]?\s*\([^)]*\)\s*', '', text)
    return re.split(r'\n|[;,]|(?:통해|하여|반영하여)\s', text)[-1].strip()


def goal_words(text):
    return set(content(text)) - {'목적', '대상', '목표'}


def explicit_purposes(text):
    result = []
    for clause in v2.clauses(text):
        for m in re.finditer(r'위해|위한|위하여', clause):
            left, right = local_left(clause[:m.start()]), clause[m.end():]
            goal = goal_words(left)
            means = goal_words(right)
            if goal and means:
                result.append({'goal': goal, 'means': means, 'left': left, 'right': right, 'clause': clause})
    return result


def matching_goal(a, b):
    # Goals with substantially different anchor words are not the same goal.
    def covered(word, other):
        if word in other:
            return True
        # Segment a compound against full tokens, preserving order, rather
        # than concatenating an unordered set of tokens.
        reached = {0}
        for i in range(len(word)):
            if i in reached:
                reached.update(i + len(t) for t in other if word.startswith(t, i))
        return len(word) in reached
    ca = sum(covered(w, b) or any(w in x for x in b if len(w) >= 2) for w in a)
    cb = sum(covered(w, a) or any(w in x for x in a if len(w) >= 2) for w in b)
    # Compound segmentation and moving a modifier do not by themselves prove
    # different goals. Use substantial coverage on at least the smaller side.
    return bool(a and b) and min(ca / len(a), cb / len(b)) >= .70


def compatible_means(a, b):
    # Added surrounding parallel material may expand the extracted frame;
    # require the smaller frame to remain largely intact, not exact identity.
    return bool(a and b) and (matching_goal(a, b) or len(a & b) / min(len(a), len(b)) >= .80)


def implicit_equivalent(reference, purpose):
    goal, means = purpose['goal'], purpose['means']
    for clause in v2.clauses(reference):
        # 명사구의 '확대 기반' -> '확대를 위한 기반': no new proposition.
        local_goal = re.split(r'(?:하고|하며)\s', purpose['left'])[-1]
        goal_nouns = [t.form for t in v2.tokenize(local_goal) if t.tag in NOUN]
        right_nouns = [t.form for t in v2.tokenize(purpose['right']) if t.tag in NOUN]
        if goal_nouns and right_nouns:
            if ''.join(goal_nouns) + right_nouns[0] in compact(clause):
                return True
        # A source means/result construction already links the same anchors.
        for m in re.finditer(r'통해|통한|하여|해서|함으로써|으로|로(?=\s)', clause):
            left = goal_words(local_left(clause[:m.start()]))
            right = goal_words(clause[m.end():])
            if goal <= right and len(means & left) >= min(2, len(means)):
                return True
        # 대응하여 X 교육 -> 대응하기 위한 교육 is a local modifier expansion.
        if '대응' in goal and '대응하여' in clause and goal <= goal_words(clause):
            if any(w in means for w in {'교육', '훈련', '대책'}):
                return True
    return False


def purpose_signals(a, b):
    pa, pb = explicit_purposes(a), explicit_purposes(b)
    out = []
    for candidate in pb:
        matches = [x for x in pa if matching_goal(x['goal'], candidate['goal'])]
        if matches and any(compatible_means(x['means'], candidate['means']) for x in matches):
            continue
        if implicit_equivalent(a, candidate):
            continue
        out.append(signal('purpose_binding', '기존 관계로 확인되지 않는 목적·수단 연결 또는 목적의 변경',
                          [{'goal': sorted(p['goal']), 'means': sorted(p['means'])} for p in pa] or a,
                          {'goal': sorted(candidate['goal']), 'means': sorted(candidate['means']), 'text': candidate['clause']}))
    # Purpose converted to a causal trigger on the wrong side of 하여/통해.
    for reference in pa:
        if any(matching_goal(reference['goal'], x['goal']) for x in pb):
            continue
        if implicit_equivalent(b, reference):
            continue
        for clause in v2.clauses(b):
            for m in re.finditer(r'하여|통해|해서', clause):
                left, right = goal_words(local_left(clause[:m.start()])), goal_words(clause[m.end():])
                if reference['goal'] <= left and len(reference['means'] & right) >= 2:
                    out.append(signal('purpose_direction', '목적이 선행 원인·수단처럼 연결됨', reference['clause'], clause))
    return out


def lexical_signals(a, b):
    added, removed = differences(a, b)
    out = []
    # A lexical amount threshold is used only for unexplained substantive nouns;
    # function/verb replacement below also handles one-word semantic changes.
    bn = {EQUIVALENCES.get(t.form, t.form) for t in v2.tokenize(b) if t.tag in NOUN}
    new_nouns = added & bn - ELABORATION
    if len(new_nouns) >= 2 and len(added) >= len(removed) + 2:
        out.append(signal('new_content', '정규화 후에도 남은 새 내용·행위 후보', sorted(removed), sorted(added)))
    an = {EQUIVALENCES.get(t.form, t.form) for t in v2.tokenize(a) if t.tag in NOUN}
    if len(removed & an - ELABORATION) >= 2 and len(removed) > len(added):
        out.append(signal('lost_content_aligned', '정규화 후에도 대응하지 않는 기능·내용 누락 후보', sorted(removed), sorted(added)))
    contrasts = [({'해소', '해결', '제거', '근절'}, {'덜', '완화', '줄이', '감소'}, 'strength_change'),
                 ({'운영'}, {'운행'}, 'action_scope'),
                 ({'방영'}, {'편성'}, 'action_scope'),
                 ({'알림'}, {'관리'}, 'function_scope'),
                 ({'기준'}, {'방식'}, 'scope_change')]
    for strong, other, code in contrasts:
        if (removed & strong and added & other) or (removed & other and added & strong):
            out.append(signal(code, '문맥상 동등하다고 보장할 수 없는 강도·행위·기능 범위 치환',
                              sorted(removed & (strong | other)), sorted(added & (strong | other))))
    inability = r'못(?:하|했|해|한|할|함)|못\s|불가능'
    ordinary_negative = r'않|안\s'
    if bool(re.search(inability, a)) != bool(re.search(inability, b)):
        if re.search(inability, a) and re.search(ordinary_negative, b) or re.search(inability, b) and re.search(ordinary_negative, a):
            out.append(signal('negation_mode', '불능·실패와 단순 부정의 구분이 바뀜', a, b))
    return out


def validate(reference_text, candidate_text):
    original = v2.validate(reference_text, candidate_text)  # validates inputs too
    a, b = v2.normalize(reference_text), v2.normalize(candidate_text)
    signals = [s for s in original['signals'] if s['code'] not in REPLACED]
    signals += subject_signals(a, b) + purpose_signals(a, b) + lexical_signals(a, b)
    from validator_v3_relations import collect_signals
    signals += collect_signals(a, b)
    # Keep broad legacy observations available, never silently erase evidence.
    observations = [{**s, 'status': 'surface_difference_reassessed_by_v3'}
                    for s in original['signals'] if s['code'] in REPLACED]
    unique = {json.dumps(s, ensure_ascii=False, sort_keys=True): s for s in signals}
    signals = list(unique.values())
    return {'version': VERSION, 'flagged': bool(signals), 'signals': signals,
            'observations': observations, 'semantic_verdict': 'uncertain',
            'routing': 'review_signals' if signals else 'semantic_review_still_required',
            'semantic_acceptance_enabled': False}


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: information_validator_v3.py input.jsonl output.jsonl')
    source, output = map(Path, sys.argv[1:])
    if source.resolve() == output.resolve():
        raise ValueError('Output must differ from input')
    records = [json.loads(s) for s in source.read_text(encoding='utf-8').splitlines() if s.strip()]
    results = [{**r, 'validation_v3': validate(r['reference_text'], r['candidate_text'])} for r in records]
    output.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in results), encoding='utf-8')


if __name__ == '__main__':
    main()
