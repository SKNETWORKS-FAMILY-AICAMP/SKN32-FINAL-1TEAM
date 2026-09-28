"""의미 보존 검증을 층별로 구현하고, 어느 층에서 어떤 오류가 잡히는지 측정한다.

층 구성 (멘토 조언: 룰 → 토크나이저 → 임베딩 → LLM judge 순으로 가능한 지점을 찾는다)
  L1 규칙        : 숫자 다중집합, 보호 문자열 등장 횟수, 줄 수와 글머리표
  L2 토크나이저  : Kiwi 형태소 기준 — 수치 등장 순서, 수치와 결합한 명사, 상태·부정 표지, 내용어 손실
  L3 임베딩      : 미구현
  L4 LLM judge   : 미구현

평가 대상
  양성(통과해야 함) : data/pilot/*_reviewed.jsonl 의 input_text → target_text
  음성(탈락해야 함) : data/pilot/validator_challenges_8.jsonl 의 input_text → candidate_output

사용법:
  python scripts/semantic_layers.py            # 요약표
  python scripts/semantic_layers.py --detail   # 사례별 사유까지 출력
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from kiwipiepy import Kiwi

BASE = Path(__file__).resolve().parents[1]
PILOT = BASE / "data" / "pilot"

NUMBER = re.compile(r"\d+")
MARKER = re.compile(r"^\s*([ㅇ□◦○\-·※①-⑳]+)")

NUM_TAGS = {"SN", "NR"}
UNIT_TAGS = {"NNB", "SW"}
NOT_UNITS = {"중", "등", "것", "수", "때", "내", "외", "간", "여"}
NOUN_TAGS = {"NNG", "NNP"}
CONTENT_TAGS = {"NNG", "NNP", "NR", "SN", "SL", "SH", "VV", "VA", "MAG", "XR"}

# 상태 표지. 윤문이 바꾸면 사실이 달라지는 말들을 성격별로 나눈다.
CONDITION_WORDS = {"이상", "이하", "미만", "초과", "별도", "포함", "모두", "이내", "각각", "이후", "이전"}
DONE_WORDS = {"완료", "체결", "달성", "확보", "종료", "출시"}
PLAN_WORDS = {"계획", "예정", "목표", "추진", "검토", "협의", "방침", "예상"}
NEGATION_FORMS = {"안", "못", "아니", "않", "없", "아직"}

# 개조식에서 허용하는 종결. Kiwi는 명사형 'ᆷ/음'도 EF로 태깅하므로 형태로 구분한다.
NOMINAL_ENDINGS = {"ᆷ", "음", "ㅁ"}


kiwi = Kiwi()


def tokens(text: str) -> list:
    return kiwi.tokenize(text)


def markers(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        m = MARKER.match(line)
        out.append(m.group(1) if m else "")
    return out


def number_units(toks: list) -> list[str]:
    """'12명', '2천만원', '95%' 처럼 수치와 단위를 붙여 등장 순서대로 돌려준다."""
    out: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i].tag in NUM_TAGS:
            parts = []
            while i < len(toks) and toks[i].tag in NUM_TAGS:
                parts.append(toks[i].form)
                i += 1
            if i < len(toks) and toks[i].tag in UNIT_TAGS and toks[i].form not in NOT_UNITS:
                parts.append(toks[i].form)
                i += 1
            out.append("".join(parts))
        else:
            i += 1
    return out


def number_bindings(toks: list) -> dict[str, set[str]]:
    """수치마다 앞쪽 가장 가까운 명사를 찾아 '수치 → 명사 집합'으로 돌려준다.

    윤문이 수식어를 지우면 앞 명사가 사라질 수 있으므로, 명사를 찾지 못한 경우는 비교에서 뺀다.
    '자금 2천만원'이 '지원금 2천만원'으로 바뀐 경우처럼 양쪽 모두 명사가 있고 서로 다를 때만 문제로 본다.
    """
    out: dict[str, set[str]] = {}
    i = 0
    while i < len(toks):
        if toks[i].tag in NUM_TAGS:
            start = i
            parts = []
            while i < len(toks) and toks[i].tag in NUM_TAGS:
                parts.append(toks[i].form)
                i += 1
            if i < len(toks) and toks[i].tag in UNIT_TAGS and toks[i].form not in NOT_UNITS:
                parts.append(toks[i].form)
                i += 1
            noun = ""
            for j in range(start - 1, max(start - 4, -1), -1):
                if toks[j].tag in NOUN_TAGS:
                    noun = toks[j].form
                    break
            if noun:
                out.setdefault("".join(parts), set()).add(noun)
        else:
            i += 1
    return out


def state_counts(toks: list) -> dict[str, dict[str, int]]:
    """상태 표지를 성격별로 센다."""
    counts = {"조건": {}, "완료": {}, "계획": {}, "부정": {}}
    for t in toks:
        if t.form in CONDITION_WORDS:
            counts["조건"][t.form] = counts["조건"].get(t.form, 0) + 1
        elif t.form in DONE_WORDS:
            counts["완료"][t.form] = counts["완료"].get(t.form, 0) + 1
        elif t.form in PLAN_WORDS:
            counts["계획"][t.form] = counts["계획"].get(t.form, 0) + 1
        elif t.form in NEGATION_FORMS or (t.tag in NOUN_TAGS and t.form.startswith("미") and len(t.form) > 1):
            counts["부정"][t.form] = counts["부정"].get(t.form, 0) + 1
    return counts


def content_words(toks: list) -> list[str]:
    return [t.form for t in toks if t.tag in CONTENT_TAGS]


def noun_phrases(toks: list) -> list[str]:
    """붙어 나오는 명사를 묶어 복합명사로 돌려준다. '주문 통합 조회' 같은 기능명을 잡기 위한 것."""
    phrases, buffer = [], []
    for t in toks:
        if t.tag in NOUN_TAGS:
            buffer.append(t.form)
        else:
            if len(buffer) >= 2:
                phrases.append("".join(buffer))
            buffer = []
    if len(buffer) >= 2:
        phrases.append("".join(buffer))
    return phrases


def layer1_rule(source: str, result: str, protected: list[str]) -> list[str]:
    problems = []

    src_numbers, res_numbers = sorted(NUMBER.findall(source)), sorted(NUMBER.findall(result))
    if src_numbers != res_numbers:
        problems.append(f"숫자 다중집합 변화 {src_numbers} → {res_numbers}")

    for span in protected or []:
        if source.count(span) != result.count(span):
            problems.append(f"보호 문자열 '{span}' 횟수 {source.count(span)} → {result.count(span)}")

    src_markers, res_markers = markers(source), markers(result)
    if len(src_markers) != len(res_markers):
        problems.append(f"줄 수 변화 {len(src_markers)} → {len(res_markers)}")
    elif src_markers != res_markers:
        problems.append(f"글머리표 변화 {src_markers} → {res_markers}")

    return problems


def layer2_token(source: str, result: str, repeated_terms: bool = False) -> list[str]:
    """repeated_terms=True면 '원문에서 반복된 복합명사는 보존한다' 규칙을 함께 적용한다.

    이 규칙은 기능명 변형(N05)을 잡지만, 중복 표현을 지우는 정상 윤문을 오탐한다.
    """
    problems = []
    src_toks, res_toks = tokens(source), tokens(result)

    src_units, res_units = number_units(src_toks), number_units(res_toks)
    if sorted(src_units) == sorted(res_units) and src_units != res_units:
        problems.append(f"수치 등장 순서 뒤바뀜 {src_units} → {res_units}")
    elif sorted(src_units) != sorted(res_units):
        problems.append(f"수치·단위 변화 {src_units} → {res_units}")

    src_bind, res_bind = number_bindings(src_toks), number_bindings(res_toks)
    for number, src_nouns in src_bind.items():
        res_nouns = res_bind.get(number)
        if res_nouns and not (src_nouns & res_nouns):
            problems.append(f"'{number}'에 붙은 명사 변화 {sorted(src_nouns)} → {sorted(res_nouns)}")

    src_state, res_state = state_counts(src_toks), state_counts(res_toks)
    for kind in ("조건", "부정"):
        if src_state[kind] != res_state[kind]:
            problems.append(f"{kind} 표지 변화 {src_state[kind]} → {res_state[kind]}")
    for word, count in res_state["완료"].items():
        if count > src_state["완료"].get(word, 0):
            problems.append(f"완료 표지 '{word}' 증가 {src_state['완료'].get(word, 0)} → {count}")
    if src_state["계획"] and not res_state["계획"]:
        problems.append(f"계획 표지가 모두 사라짐 {src_state['계획']} → 없음")

    # 원문에서 두 번 이상 반복된 복합명사는 그 문서의 용어(기능명·고유명사)로 보고 등장 횟수를 지킨다.
    # 한 번만 나온 명사구는 윤문이 다듬는 대상일 수 있어 건드리지 않는다.
    if repeated_terms:
        src_phrases, res_phrases = noun_phrases(src_toks), noun_phrases(res_toks)
        res_joined = " ".join(res_phrases)
        for phrase in set(src_phrases):
            src_count = src_phrases.count(phrase)
            if src_count < 2:
                continue
            res_count = res_joined.count(phrase)
            if res_count < src_count:
                problems.append(f"반복 용어 '{phrase}' 등장 횟수 {src_count} → {res_count}")

    # 개조식 종결을 지켰는지 본다. '~합니다', '~한다'가 남으면 서술형 잔존이다.
    for line in result.split("\n"):
        line_toks = tokens(line)
        if not line_toks:
            continue
        last = line_toks[-1]
        if last.tag == "EF" and last.form not in NOMINAL_ENDINGS:
            problems.append(f"서술형 종결 '{last.form}' 잔존: {line.strip()[:30]}")

    src_content = content_words(src_toks)
    res_content = content_words(res_toks)
    lost = [w for w in set(src_content) - set(res_content)]
    if src_content and len(lost) / len(set(src_content)) > 0.3:
        problems.append(f"내용어 30% 넘게 사라짐: {sorted(lost)}")

    return problems


def load_jsonl(name: str) -> list[dict]:
    with (PILOT / name).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_cases() -> list[dict]:
    cases = []
    for name in ("refinement_pairs_6_reviewed.jsonl", "business_plan_pairs_12_reviewed.jsonl"):
        for row in load_jsonl(name):
            cases.append(
                {
                    "case_id": row["pair_id"],
                    "case_type": "정상 윤문",
                    "expected": "통과",
                    "source": row["input_text"],
                    "result": row["target_text"],
                    "protected": row.get("protected_spans", []),
                    "reason": row.get("issue_type") or row.get("edit_type", ""),
                }
            )
    for name, default_type in (
        ("validator_challenges_8.jsonl", "값·조건·용어 변형(v1)"),
        ("validator_challenges_v2.jsonl", ""),
    ):
        if not (PILOT / name).exists():
            continue
        for row in load_jsonl(name):
            cases.append(
                {
                    "case_id": row["challenge_id"],
                    "case_type": row.get("case_type") or default_type,
                    "expected": "탈락",
                    "source": row["input_text"],
                    "result": row["candidate_output"],
                    "protected": row.get("protected_spans", []),
                    "reason": row.get("reason", ""),
                }
            )
    return cases


def run(cases: list[dict], use_protected: bool, repeated_terms: bool) -> list[dict]:
    rows = []
    for case in cases:
        l1 = layer1_rule(case["source"], case["result"], case["protected"] if use_protected else [])
        l2 = layer2_token(case["source"], case["result"], repeated_terms=repeated_terms)
        verdict = "탈락" if (l1 or l2) else "통과"
        rows.append({**case, "l1": l1, "l2": l2, "verdict": verdict})
    return rows


def report(title: str, rows: list[dict], detail: bool) -> None:
    negatives = [r for r in rows if r["expected"] == "탈락"]
    positives = [r for r in rows if r["expected"] == "통과"]
    caught = [r for r in negatives if r["verdict"] == "탈락"]
    missed = [r["case_id"] for r in negatives if r["verdict"] == "통과"]
    false_alarm = [r for r in positives if r["verdict"] == "탈락"]

    print(f"\n== {title} ==")
    print(f"오류 탐지 {len(caught)}/{len(negatives)} · 정답 쌍 통과 {len(positives) - len(false_alarm)}/{len(positives)}")

    by_type: dict[str, list[dict]] = {}
    for r in negatives:
        by_type.setdefault(r["case_type"], []).append(r)
    print(f"  {'유형':18} {'탐지':>7} {'L1만':>6} {'L2만':>6}")
    for case_type, group in by_type.items():
        hit = sum(1 for r in group if r["verdict"] == "탈락")
        l1_only = sum(1 for r in group if r["l1"] and not r["l2"])
        l2_only = sum(1 for r in group if r["l2"] and not r["l1"])
        print(f"  {case_type:18} {hit:>3}/{len(group):<3} {l1_only:>6} {l2_only:>6}")

    if missed:
        print(f"  두 층 모두 놓친 사례: {', '.join(missed)}")
    for r in false_alarm:
        print(f"  오탐 {r['case_id']} ({r['reason']}): " + " · ".join(r["l1"] + r["l2"]))

    if detail:
        for r in rows:
            if r["l1"] or r["l2"]:
                print(f"  [{r['case_id']}] 기대 {r['expected']} → 판정 {r['verdict']}")
                for p in r["l1"]:
                    print(f"     L1 {p}")
                for p in r["l2"]:
                    print(f"     L2 {p}")


def main() -> None:
    detail = "--detail" in sys.argv[1:]
    cases = build_cases()
    negatives = sum(1 for c in cases if c["expected"] == "탈락")
    positives = len(cases) - negatives
    print(f"대상: 오류 사례 {negatives}개 · 사람 검수를 통과한 정답 쌍 {positives}개")

    report("A. 보호 문자열 사용 + 기본 규칙", run(cases, True, False), detail)
    report("B. 보호 문자열 없이 + 기본 규칙 (새 데이터에 가까운 조건)", run(cases, False, False), detail)
    report("C. 보호 문자열 없이 + 반복 용어 보존 규칙 추가", run(cases, False, True), detail)

    print(
        "\n읽는 법: A는 사람이 보호 문자열을 달아준 상태, B는 달지 않은 상태다."
        "\nC의 반복 용어 규칙은 기능명 변형을 잡지만 중복 표현을 지우는 정상 윤문을 오탐한다."
    )


if __name__ == "__main__":
    main()
