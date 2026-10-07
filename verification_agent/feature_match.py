"""계획서 대조 15점: 계획서에 쓴 기능이 산출물에 실제로 있는가.

점수 = 15 × 인정된 기능 수 / 계획서 기능 수 (원페이지는 여기서 지어낸 수치 감점)

예전 공식 max(0, 15 - 4 × 누락)은 기능 수에 따라 뒤집혔다. 기능 1개를 하나도 안 만들면
11점, 기능 10개 중 6개를 만들면 0점이었다. 비례식은 구현 비율이 곧 점수다.

## 무엇을 근거로 인정하나

채점 근거는 생성 쪽이 스스로 붙인 표식이 아니라, 생성 쪽이 흉내 낼 수 없는 것이어야 한다.
- HTML: 화면에 기능명이 보이고, 그 기능의 조작 요소에 이벤트 핸들러가 **직접** 붙어 있다.
  data-feature 표식은 요소를 찾는 데만 쓰고, 그 요소가 동작하는지는 스크립트로 확인한다.
- 원페이지 SVG: T-B2는 기능명을 계획서 기능 목록에서 그대로 옮겨 적는다. 그래서 기능명이
  지면에 있는지를 보면 항상 만점이 나오는 자기 채점이 된다(이전 구현의 결함). 대신 기능마다
  적힌 **설명**이 계획서 원문(plan_doc)에 근거가 있는지를 본다. 계획서 원문이 오지 않으면
  근거를 확인할 수 없으므로 이름 비교로 되돌아가지 않고 0점으로 둔다.

## 규칙 → LLM 두 단계

규칙은 "이름이 화면에 있고 버튼에 이벤트가 붙었다"까지만 본다. 그 이벤트가 계획서가 말한 일을
하는지는 못 봐서, 구현 쪽이 규칙에 맞춰 만들면 늘 만점이 났다. 그래서 규칙을 넘긴 기능만
LLM이 기능마다 하나씩 충족 · 부분 · 미충족으로 다시 판정한다(llm_judge.py). 규칙을 넘기고 LLM이
충족이면 1, 부분이면 0.5, 미충족이면 0으로 센다(미충족만 누락 기능). 규칙에서 떨어진 기능은
LLM에 묻지 않는다. LLM 호출이 실패한 기능은 규칙 판정을 그대로 쓴다(T-V2 Failure ④).
점수 계산(15 × 인정 몫 ÷ 전체)과 원페이지의 지어낸 수치 감점은 규칙이 한다.

## 원페이지 핵심 칸

원페이지는 기능 설명에 더해 문제 정의 · 해결 방안 · 수익모델 단가 · 추진 일정 네 칸도 대조한다.
이 칸들은 모델이 계획서를 줄여 쓴 글인데, 코드 점검은 비어 있지 않은지만 봐서 내용이 틀려도
만점이었다. 칸마다 LLM이 계획서와 같은 뜻인지 판정하고, 분모는 기능 수 + 4가 된다. 네 칸은
누락 기능 목록(missing_features)에 넣지 않고 사유(findings)에만 적는다 — 조율은 그 목록의
이름을 기능으로 다룬다. LLM을 쓸 수 없으면 네 칸은 대조에 넣지 않는다(분모는 기능 수 그대로).
"""
from __future__ import annotations

import re
from typing import Callable
from xml.etree import ElementTree as ET

from verification_agent.rules.html_parser import parse_page
from verification_agent.rules.wiring import control_label, is_wired, wired_ids

TOTAL = 15.0
# 원페이지 지면에서 계획서에 없는 수치 한 건당 감점과 상한.
_NUMBER_PENALTY = 1.0
_NUMBER_PENALTY_CAP = 3.0

# 아이템명·목표 고객·한 줄 소개는 사용자 입력(ItemSpec)을 그대로 옮긴 값이라 계획서 대조 대상이 아니다.
_USER_INPUT_FIELDS = {"item_name", "target_users", "item_summary"}
_PLACEHOLDER_VALUES = {"정보 없음", "미정", "해당 없음", "n/a", "na", "-", "tbd", "없음"}
_NUMBER_RE = re.compile(r"\d[\d,._]*")
_TERM_RE = re.compile(r"[가-힣A-Za-z]{2,}")
# 낱말 끝의 조사·어미. 긴 것부터 떼어야 "으로"가 "로"보다 먼저 걸린다.
_SUFFIXES = ("으로써", "에서는", "으로", "에서", "에게", "까지", "부터", "보다", "처럼",
             "하는", "하고", "이다", "합니다", "한다", "은", "는", "이", "가", "을", "를",
             "에", "의", "로", "와", "과", "도", "만")


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _numbers(text: str) -> list[str]:
    """숫자 토큰. 천 단위 쉼표는 떼어 "10,000"과 "10000"을 같은 값으로 본다."""
    return [m.group(0).rstrip(",._").replace(",", "") for m in _NUMBER_RE.finditer(text)]


def _terms(text: str) -> list[str]:
    out: list[str] = []
    for raw in _TERM_RE.findall(text):
        term = raw.casefold()
        for suffix in _SUFFIXES:
            if term.endswith(suffix) and len(term) - len(suffix) >= 2:
                term = term[: -len(suffix)]
                break
        if term not in out:
            out.append(term)
    return out


# 기능 목록 → {기능: (얻은 몫 0 · 0.5 · 1, 이유) 또는 None(판정 실패)}. llm_judge.make_judge가 만든다.
Judge = Callable[[list[str]], dict[str, "tuple[float, str] | None"]]


def _apply_judge(judge: Judge | None, feature_list: list[str], missing: list[str],
                 findings: list[str], partial_out: list[str], failed_out: list[str]) -> tuple[float, str]:
    """규칙을 넘긴 기능을 LLM으로 다시 판정해 missing · findings를 고치고, 일부만 인정된 기능
    (몫이 0보다 크고 1보다 작음)을 partial_out에, LLM 판정에 실패한 기능을 failed_out에 넣는다.
    (인정 몫 합계, 요약 문구)를 돌려준다. judge가 없으면 규칙을 넘긴 기능 수 그대로다."""
    passed = [f for f in feature_list if f not in missing]
    if judge is None or not passed:
        return float(len(passed)), ""
    verdicts = judge(passed)
    failed = [f for f in passed if not verdicts.get(f)]
    judged = [f for f in passed if f not in failed]
    rejected = [f for f in judged if verdicts[f][0] == 0]
    partial = [f for f in judged if 0 < verdicts[f][0] < 1]
    for feature in rejected:
        missing.append(feature)
        findings.append(f"{feature}: {verdicts[feature][1]}")
    for feature in partial:
        findings.append(f"{feature}: 부분 인정 — {verdicts[feature][1]}")
    partial_out.extend(partial)
    failed_out.extend(failed)
    # 화면 · 결과 순서를 계획서 기능 순서에 맞춘다.
    missing.sort(key=feature_list.index)
    credit = len(failed) + sum(verdicts[f][0] for f in judged)
    note = (f" → LLM 확인 {len(judged)}건: 충족 {len(judged) - len(rejected) - len(partial)}"
            f" · 부분 {len(partial)} · 미충족 {len(rejected)}")
    if failed:
        note += f", LLM 판정 실패 {len(failed)}건은 규칙 결과로 대체"
    return credit, note


def _result(score: float, missing: list[str], findings: list[str], judged_by: str,
            extra: list[str] | None = None, partial: list[str] | None = None,
            withheld_reason: str | None = None, llm_failed: list[str] | None = None) -> dict:
    """FeatureMatchResult 모양 + llm_failed. 조율 흐름은 missing_features · partial_features · withheld로만
    가른다(findings 문구로 가르지 않는다). 두 목록에는 기능 목록의 이름만, 겹치지 않게 들어간다.
    llm_failed(LLM 판정에 실패해 규칙 결과로 대신한 기능 · 핵심 칸)는 계약 칸이 아니다 — run_tv2가 떼어
    diagnostics에 옮긴다."""
    return {"score": round(max(0.0, min(TOTAL, score)), 2), "missing_features": missing,
            "extra_features": extra or [], "findings": findings, "judged_by": judged_by,
            "partial_features": partial or [], "withheld": withheld_reason is not None,
            "withheld_reason": withheld_reason, "llm_failed": llm_failed or []}


# ── HTML ────────────────────────────────────────────────────────


def _match_html(feature_list: list[str], source: str, judge: Judge | None) -> dict:
    parser = parse_page(source)
    visible = _norm(" ".join(parser.visible))
    wired = wired_ids("\n".join(parser.script_chunks))
    live = [c for c in parser.controls if is_wired(c, wired)]

    missing: list[str] = []
    findings: list[str] = []
    for feature in feature_list:
        key = _norm(feature)
        on_screen = key in visible
        named = [c for c in parser.controls
                 if key in _norm(c["feature"]) or key in _norm("".join(c["text"]))
                 or key in _norm(c["aria"]) or key in _norm(c["value"])]
        acting = [c for c in named if c in live]
        if on_screen and acting:
            continue
        missing.append(feature)
        if not on_screen:
            findings.append(f"{feature}: 화면 문구에 없음")
        elif not named:
            findings.append(f"{feature}: 이 기능을 실행하는 조작 요소가 없음")
        else:
            findings.append(f"{feature}: 조작 요소({control_label(named[0])[:20]})에 "
                            "이벤트가 직접 연결되지 않음")

    known = {_norm(f) for f in feature_list}
    extra = list(dict.fromkeys(c["feature"] for c in parser.controls
                               if c["feature"] and _norm(c["feature"]) not in known))
    rule_ok = len(feature_list) - len(missing)
    partial: list[str] = []
    failed: list[str] = []
    ok, note = _apply_judge(judge, feature_list, missing, findings, partial, failed)
    findings.insert(0, f"인정 {round(ok, 2):g}/{len(feature_list)}개 (규칙: 화면 문구 + 직접 연결된 조작 요소 "
                       f"{rule_ok}건{note})")
    return _result(TOTAL * ok / len(feature_list), missing, findings, "htmlParse", extra, partial,
                   llm_failed=failed)


# ── 원페이지 SVG ───────────────────────────────────────────────


# 대조하는 핵심 칸: (지면 표식 data-field, 이름). 아이템명 · 목표 고객은 사용자 입력이라 대조하지 않는다.
_KEY_FIELDS = (("problem", "문제 정의"), ("solution", "해결 방안"),
               ("revenue_unit_price", "수익모델 단가"), ("timeline_baseline", "추진 일정"))
# 핵심 칸 판정 함수: {칸 이름: 지면 내용} → {칸 이름: (몫, 이유) 또는 None(판정 실패)}
FieldJudge = Callable[[dict[str, str]], dict[str, "tuple[float, str] | None"]]


def _key_fields(nodes: list) -> dict[str, str]:
    """핵심 칸마다 지면에 적힌 글. 한 칸이 여러 글자 노드로 나뉘어 있으면 이어 붙인다.
    비었거나 자리 채움 문구뿐인 칸은 빈 문자열이다."""
    out = {}
    for key, label in _KEY_FIELDS:
        parts = []
        for node in nodes:
            text = "".join(node.itertext()).strip().rstrip("…").strip()
            if node.get("data-field") == key and text and text.casefold() not in _PLACEHOLDER_VALUES \
                    and text not in parts:
                parts.append(text)
        out[label] = " / ".join(parts)
    return out


def _apply_field_judge(field_judge: FieldJudge | None, nodes: list,
                       findings: list[str], failed_out: list[str]) -> tuple[float, int, str]:
    """(핵심 칸 인정 몫 합계, 핵심 칸 수, 요약 문구). field_judge가 없으면 (0, 0, "").
    판정에 실패한 칸은 failed_out에 '핵심 칸 이름'으로 넣는다."""
    if field_judge is None:
        return 0.0, 0, ""
    fields = _key_fields(nodes)
    shown = {label: text for label, text in fields.items() if text}
    verdicts = field_judge(shown)
    credit, counts = 0.0, {"충족": 0, "부분": 0, "미충족": 0, "실패": 0}
    for label, text in fields.items():
        if not text:
            counts["미충족"] += 1
            findings.append(f"{label}: 지면에 없거나 자리 채움 문구")
            continue
        verdict = verdicts.get(label)
        if not verdict:          # 판정 실패는 감점하지 않는다
            credit += 1.0
            counts["실패"] += 1
            failed_out.append(f"핵심 칸 {label}")
            continue
        credit += verdict[0]
        if verdict[0] >= 1:
            counts["충족"] += 1
        elif verdict[0] > 0:
            counts["부분"] += 1
            findings.append(f"{label}: 부분 인정 — {verdict[1]}")
        else:
            counts["미충족"] += 1
            findings.append(f"{label}: {verdict[1]}")
    note = (f" · 핵심 칸 {round(credit, 2):g}/{len(fields)} (충족 {counts['충족']} · 부분 {counts['부분']}"
            f" · 미충족 {counts['미충족']}")
    note += f", LLM 판정 실패 {counts['실패']}건은 감점하지 않음)" if counts["실패"] else ")"
    return credit, len(fields), note


def _svg_texts(source: str) -> list:
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return []
    return [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "text"]


def _detail_verdict(feature: str, detail: str | None, plan_compact: str,
                    plan_numbers: set[str]) -> str | None:
    """기능 설명이 계획서에 근거가 있으면 None, 없으면 이유."""
    if detail is None:
        return "지면에 기능 설명이 없음"
    text = detail.rstrip("…").strip()
    if not text or text.casefold() in _PLACEHOLDER_VALUES:
        return "기능 설명이 비어 있거나 자리 채움 문구"
    unbacked = [n for n in _numbers(text) if n not in plan_numbers]
    if unbacked:
        return f"계획서에 없는 수치 {', '.join(unbacked)}"
    name_terms = set(_terms(feature))
    terms = [t for t in _terms(text) if t not in name_terms]
    if not terms:
        return "기능명을 되풀이할 뿐 설명이 없음"
    backed = [t for t in terms if t in plan_compact]
    if len(backed) * 2 < len(terms):
        return f"설명의 낱말 중 계획서에서 확인되는 것이 {len(backed)}/{len(terms)}개뿐"
    return None


def _match_onepage(feature_list: list[str], source: str, plan_text: str | None,
                   judge: Judge | None, field_judge: FieldJudge | None = None) -> dict:
    if plan_text is None:
        return _result(0.0, list(feature_list),
                       ["계획서 원문(plan_doc)이 전달되지 않아 근거 대조 불가 — 0점 처리",
                        "기능명만으로 대조하면 T-B2가 옮겨 적은 목록을 다시 찾는 자기 채점이 된다"],
                       "svgTextParse")

    plan_compact = _norm(plan_text + " " + " ".join(feature_list))
    plan_numbers = set(_numbers(plan_text + " " + " ".join(feature_list)))
    nodes = _svg_texts(source)
    details = {_norm(n.get("data-feature", "")): "".join(n.itertext()).strip()
               for n in nodes if n.get("data-field") == "feature_detail"}

    missing: list[str] = []
    findings: list[str] = []
    for feature in feature_list:
        reason = _detail_verdict(feature, details.get(_norm(feature)), plan_compact, plan_numbers)
        if reason:
            missing.append(feature)
            findings.append(f"{feature}: {reason}")

    shown = " ".join("".join(n.itertext()) for n in nodes
                     if n.get("data-field") not in _USER_INPUT_FIELDS)
    invented = list(dict.fromkeys(n for n in _numbers(shown) if n not in plan_numbers))
    penalty = min(_NUMBER_PENALTY_CAP, _NUMBER_PENALTY * len(invented))

    rule_ok = len(feature_list) - len(missing)
    partial: list[str] = []
    failed: list[str] = []
    ok, note = _apply_judge(judge, feature_list, missing, findings, partial, failed)
    field_ok, field_count, field_note = _apply_field_judge(field_judge, nodes, findings, failed)
    findings.insert(0, f"인정 {round(ok, 2):g}/{len(feature_list)}개 (규칙: 기능 설명이 계획서 원문에 근거 "
                       f"{rule_ok}건{note}){field_note}")
    if invented:
        findings.append(f"지면에 계획서에 없는 수치 {len(invented)}건 "
                        f"({', '.join(invented[:5])}) — {penalty:g}점 감점")
    score = TOTAL * (ok + field_ok) / (len(feature_list) + field_count) - penalty
    return _result(score, missing, findings, "svgTextParse", partial=partial, llm_failed=failed)


def match_features(feature_list: list[str], source: str, kind: str,
                   plan_text: str | None = None, judge: Judge | None = None,
                   field_judge: FieldJudge | None = None) -> dict:
    """source가 빈 문자열이면 통과 필수 조건을 못 넘긴 산출물이다 — 전부 누락으로 본다.
    judge가 없으면 규칙만으로 판정한다. field_judge는 원페이지 핵심 칸 판정(없으면 넣지 않는다)."""
    judged_by = "svgTextParse" if kind == "svg-onepage" else "htmlParse"
    if not feature_list:
        # 대조할 기준이 없다 — 0점이 아니라 판정 보류(E-V2-NOFEATURE)로 알린다. 조율이 0점으로 합산한다.
        return _result(0.0, [], ["계획서 기능 목록이 비어 있음 — 대조 보류"], judged_by,
                       withheld_reason="E-V2-NOFEATURE")
    if not source:
        return _result(0.0, list(feature_list),
                       ["산출물이 통과 필수 조건을 넘지 못해 대조 생략"], judged_by)
    if kind == "svg-onepage":
        return _match_onepage(feature_list, source, plan_text, judge, field_judge)
    return _match_html(feature_list, source, judge)
