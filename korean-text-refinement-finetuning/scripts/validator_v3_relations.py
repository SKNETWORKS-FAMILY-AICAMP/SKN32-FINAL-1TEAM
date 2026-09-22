"""Conservative local relation signals for v3 (never semantic verdicts).

These rules compare text-derived argument bindings, not dataset IDs or labels.
They require stable anchors on both sides and intentionally abstain when Korean
ellipsis, synonym substitution or nested arguments cannot be resolved locally.
"""
from collections import Counter, defaultdict
import re

from information_validator import quantities, tokenize, words

NOUNS = {'NNG', 'NNP', 'SL'}
HELPERS = {'하', '되', '있', '위하', '목표', '계획', '예정', '상태', '작업',
           '추진', '수행', '것', '중', '방향', '경우', '여부', '않', '못하', '아니'}
STATUS = re.compile(r'완료|종료|마무리|(?:개발|진행|협의|검토|공사|운영)\s*중')


def local_clauses(text):
    """Split coordinate predicates; keep purpose/means subordination intact."""
    cuts = {0, len(text)}
    for match in re.finditer(r'\n|[;!?]|,(?!\d)|\.(?=\s|$)', text):
        cuts.update((match.start(), match.end()))
    for token in tokenize(text):
        if token.tag == 'EC' and token.form in {'고', '며', '으며', '지만'}:
            cuts.add(token.start + token.len)
    cuts = sorted(cuts)
    return [text[start:end].strip() for start, end in zip(cuts, cuts[1:])
            if words(text[start:end])]


def _noun_set(text):
    return {t.form for t in tokenize(text) if t.tag in NOUNS} - HELPERS


def _topic_before(text, offset):
    """Recover the closest explicit topic/subject NP, not a suffix substring."""
    toks = [t for t in tokenize(text) if t.start + t.len <= offset]
    for i in range(len(toks) - 1, -1, -1):
        token = toks[i]
        if not (token.tag == 'JKS' or (token.tag == 'JX' and token.form in {'은', '는'})):
            continue
        phrase = []
        for before in reversed(toks[:i]):
            if before.tag in NOUNS or before.tag == 'XSN':
                phrase.append(before.form)
            else:
                break
        if phrase:
            return ''.join(reversed(phrase))
    # Nominal tables omit particles: join the complete adjacent noun compound
    # so 해솔반 and 다온반 do not collapse onto the shared final head 반.
    while toks and toks[-1].form in {'월', '연', '매월', '매년'}:
        toks.pop()
    phrase = []
    for token in reversed(toks):
        if token.tag in NOUNS or token.tag == 'XSN':
            phrase.append(token.form)
        else:
            break
    return ''.join(reversed(phrase)) or None


def _topic_quantities(text):
    result = defaultdict(Counter)
    for clause in local_clauses(text):
        for quantity in quantities(clause):
            topic = _topic_before(clause, quantity['start'])
            if topic:
                result[topic][(quantity['value'], quantity['unit'])] += 1
    return result


def _task_states(text):
    by_word = defaultdict(set)
    for clause in local_clauses(text):
        for match in STATUS.finditer(clause):
            task = _noun_set(clause[:match.start()])
            # Attribute a status only to its local task, with future/negation
            # distinguished from accomplished status when explicitly written.
            state = re.sub(r'\s+', '', match[0])
            tail = clause[match.end():]
            connective = next((t for t in tokenize(tail) if t.tag == 'EC'), None)
            if connective and connective.form in {'면', '으면'}:
                tail = tail[:connective.start]
                state = 'conditional:' + state
            elif re.match(r'\s*시(?:\s|$)', tail):
                state = 'conditional:' + state
                tail = ''
            if re.search(r'않|못|안\s|미완료', tail):
                state = 'negative:' + state
            elif re.match(r'(?:할|될|를|을)?\s*(?:예정|계획|목표)', tail):
                state = 'planned:' + state
            for anchor in task:
                by_word[anchor].add(state)
    return {word: next(iter(states)) for word, states in by_word.items()
            if len(states) == 1}


def _action_frame(clause):
    """Last overt lexical predicate, allowing '답변을 목표로 함'."""
    toks = tokenize(clause)
    actions = []
    for i, token in enumerate(toks):
        if token.tag == 'VV' and token.form not in HELPERS:
            actions.append(token)
        elif (token.tag in NOUNS and token.form not in HELPERS and i + 1 < len(toks)
              and toks[i + 1].tag == 'XSV'):
            actions.append(token)
    if actions:
        action = actions[-1]
    else:
        # Nominal reports and goal descriptions often omit 하다 entirely.
        candidates = [t for t in toks if t.tag in NOUNS and t.form not in HELPERS
                      and t.form not in {'월', '일', '년', '이내', '이상', '이하', '후', '전'}]
        if not candidates:
            return None
        action = candidates[-1]
    return action.form, _noun_set(clause[:action.start]), clause[:action.start]


def _time_bindings(text):
    result = defaultdict(Counter)
    for clause in local_clauses(text):
        frame = _action_frame(clause)
        if not frame:
            continue
        action, _, before = frame
        clocks = [(m[1].zfill(2), m[2]) for m in re.finditer(r'(\d{1,2}):(\d{2})', before)]
        durations = [(q['value'], q['unit']) for q in quantities(before)
                     if q['unit'] in {'시간', '분', '일', '월', '년'}]
        for value in clocks:
            result[action][('clock', *value)] += 1
        for value in durations:
            result[action][('duration', *value)] += 1
    return result


def _event_arguments(text):
    result = defaultdict(list)
    for clause in local_clauses(text):
        frame = _action_frame(clause)
        if frame:
            action, nouns, _ = frame
            result[action].append(nouns - {action})
    # Repeated same-action statements are ambiguous without full parsing.
    return {action: args[0] for action, args in result.items() if len(args) == 1}


def _threshold_bindings(text):
    result = defaultdict(Counter)
    for clause in local_clauses(text):
        frame = _action_frame(clause)
        if not frame:
            continue
        action, _, before = frame
        for quantity in quantities(before):
            operator = re.match(r'\s*(이상|이하|미만|초과|이내|이외)', before[quantity['end']:])
            if operator:
                result[action][(quantity['value'], quantity['unit'], operator[1])] += 1
    return result


def _predicate_polarities(text):
    result = defaultdict(set)
    for clause in local_clauses(text):
        frame = _action_frame(clause)
        if not frame:
            continue
        action, anchors, before = frame
        tail_tokens = tokenize(clause[len(before):])
        negative = any(t.form in {'않', '못', '못하', '없', '아니'} for t in tail_tokens)
        # The pre-verbal adverbs 안/못 negate the predicate, but a negative
        # relative clause earlier in the noun argument does not.
        before_tokens = tokenize(before)
        if before_tokens and before_tokens[-1].form in {'안', '못'}:
            negative = True
        for anchor in anchors:
            result[(action, anchor)].add('negative' if negative else 'positive')
    return {key: next(iter(states)) for key, states in result.items() if len(states) == 1}


def _marker_arguments(text, pattern):
    result = []
    for clause in local_clauses(text):
        for match in re.finditer(pattern, clause):
            prefix = clause[:match.start()]
            # The marker argument follows the last topic/object separator;
            # retain object particles immediately before 통해 (협업을 통해).
            separators = [t.start + t.len for t in tokenize(prefix)
                          if t.tag == 'JKS' or (t.tag == 'JX' and t.form in {'은', '는'})]
            if separators:
                prefix = prefix[separators[-1]:]
            argument = _noun_set(prefix)
            effect = words(clause[match.end():]) - HELPERS
            if argument and effect:
                result.append((argument, effect, clause))
    return result


def _binding_changes(left, right):
    return [(key, left[key], right[key]) for key in sorted(left.keys() & right.keys())
            if left[key] != right[key]]


def collect_signals(reference_text, candidate_text):
    """Return bounded review evidence. Absence of evidence is not preservation."""
    signals = []

    def add(code, detail, before, after):
        signals.append({'code': code, 'detail': detail,
                        'reference_evidence': before, 'candidate_evidence': after})

    qa = Counter((q['value'], q['unit']) for q in quantities(reference_text))
    qb = Counter((q['value'], q['unit']) for q in quantities(candidate_text))
    if qa == qb:
        for topic, before, after in _binding_changes(_topic_quantities(reference_text),
                                                   _topic_quantities(candidate_text)):
            if before.total() == after.total():
                add('quantity_topic_binding', '같은 명시적 대상에 연결된 수치·단위가 달라짐',
                    {topic: list(before.elements())}, {topic: list(after.elements())})
        for action, before, after in _binding_changes(_time_bindings(reference_text),
                                                     _time_bindings(candidate_text)):
            if before and after:
                add('temporal_action_binding', '같은 행위에 연결된 시간·기한이 달라짐',
                    {action: list(before.elements())}, {action: list(after.elements())})

    # Completion used as a future means can be rephrased as a condition. This
    # helper checks reassignment of distinct lexical states (e.g. 완료/개발중),
    # leaving tense, negation and conditional realization to the main validator.
    changed_states = [(key, before, after) for key, before, after in
                      _binding_changes(_task_states(reference_text), _task_states(candidate_text))
                      if before.split(':')[-1] != after.split(':')[-1]]
    if changed_states:
        add('task_status_binding', '같은 과제의 명시적 완료·진행·계획 상태가 달라짐',
            {key: before for key, before, _ in changed_states},
            {key: after for key, _, after in changed_states})

    thresholds_a = _threshold_bindings(reference_text)
    thresholds_b = _threshold_bindings(candidate_text)
    total_a = sum(thresholds_a.values(), Counter())
    total_b = sum(thresholds_b.values(), Counter())
    if total_a and total_a == total_b:
        for action, before, after in _binding_changes(thresholds_a, thresholds_b):
            if before.total() == after.total():
                add('condition_action_binding', '같은 행위에 적용되는 수치 조건·한계 방향이 달라짐',
                    {action: list(before.elements())}, {action: list(after.elements())})

    polarities = _binding_changes(_predicate_polarities(reference_text),
                                 _predicate_polarities(candidate_text))
    if polarities:
        add('predicate_polarity_binding', '같은 대상·행위에 연결된 긍정·부정 상태가 달라짐',
            [{'action': key[0], 'anchor': key[1], 'polarity': before} for key, before, _ in polarities],
            [{'action': key[0], 'anchor': key[1], 'polarity': after} for key, _, after in polarities])

    ea, eb = _event_arguments(reference_text), _event_arguments(candidate_text)
    shared_actions = sorted(ea.keys() & eb.keys())
    # Require reciprocal movement of at least two exclusive anchors between
    # two stable actions. A mere omitted noun or clause reorder cannot satisfy it.
    for i, first in enumerate(shared_actions):
        for second in shared_actions[i + 1:]:
            first_to_second = (ea[first] - ea[second] - eb[first]) & eb[second]
            second_to_first = (ea[second] - ea[first] - eb[second]) & eb[first]
            if len(first_to_second) >= 2 and len(second_to_first) >= 2:
                add('event_argument_binding', '서로 다른 행위에 붙은 대상·조건 내용어가 교차 이동함',
                    {first: sorted(first_to_second), second: sorted(second_to_first)},
                    {first: sorted(second_to_first), second: sorted(first_to_second)})

    wa, wb = words(reference_text), words(candidate_text)
    for kind, marker in [('dependence', r'따라'), ('means', r'통해|통한')]:
        left = _marker_arguments(reference_text, marker)
        right = _marker_arguments(candidate_text, marker)
        # Match by effect, independent of clause order. Only compare uniquely
        # best effect matches; multiple equally good attachments are ambiguous.
        for arg_b, effect_b, evidence_b in right:
            scored = [(len(effect_a & effect_b), arg_a, effect_a, evidence_a)
                      for arg_a, effect_a, evidence_a in left]
            if not scored:
                continue
            best_score = max(item[0] for item in scored)
            best = [item for item in scored if item[0] == best_score]
            if best_score < 1 or len(best) != 1:
                continue
            _, arg_a, _, evidence_a = best[0]
            removed, added = arg_a - arg_b, arg_b - arg_a
            if (removed and added and removed <= wb and added <= wa
                    and len(arg_a & arg_b) < min(len(arg_a), len(arg_b)) / 2):
                add('relation_argument_' + kind,
                    '동일한 결과에 붙은 의존 조건·수단의 내용어가 달라짐', evidence_a, evidence_b)
    return signals
