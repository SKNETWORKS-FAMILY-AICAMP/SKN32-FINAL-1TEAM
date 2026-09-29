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

지면이나 화면 문구가 계획서와 표현만 다른 경우(동의어)는 아직 누락으로 친다. 여기를
LLM 보조가 맡을 예정이다 — 규칙이 누락이라고 한 기능만 LLM에 묻고, 최종 판정은 규칙이
다시 한다. 검증-2용 모델은 조율의 통보를 기다리고 있다.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from verification_agent.rules.r4 import control_label, is_wired, parse_page, wired_ids

TOTAL = 15.0
# 원페이지 지면에서 계획서에 없는 수치 한 건당 감점과 상한.
_NUMBER_PENALTY = 1.0
_NUMBER_PENALTY_CAP = 3.0

# 아이템명·목표 고객은 사용자 입력(ItemSpec)을 그대로 옮긴 값이라 계획서 대조 대상이 아니다.
_USER_INPUT_FIELDS = {"item_name", "target_users"}
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


def _result(score: float, missing: list[str], findings: list[str], judged_by: str,
            extra: list[str] | None = None) -> dict:
    return {"score": round(max(0.0, min(TOTAL, score)), 2), "missing_features": missing,
            "extra_features": extra or [], "findings": findings, "judged_by": judged_by}


# ── HTML ────────────────────────────────────────────────────────


def _match_html(feature_list: list[str], source: str) -> dict:
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
    ok = len(feature_list) - len(missing)
    findings.insert(0, f"인정 {ok}/{len(feature_list)}개 (화면 문구 + 직접 연결된 조작 요소)")
    return _result(TOTAL * ok / len(feature_list), missing, findings, "htmlParse", extra)


# ── 원페이지 SVG ───────────────────────────────────────────────


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


def _match_onepage(feature_list: list[str], source: str, plan_text: str | None) -> dict:
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

    ok = len(feature_list) - len(missing)
    findings.insert(0, f"인정 {ok}/{len(feature_list)}개 (기능 설명이 계획서 원문에 근거)")
    if invented:
        findings.append(f"지면에 계획서에 없는 수치 {len(invented)}건 "
                        f"({', '.join(invented[:5])}) — {penalty:g}점 감점")
    return _result(TOTAL * ok / len(feature_list) - penalty, missing, findings, "svgTextParse")


def match_features(feature_list: list[str], source: str, kind: str,
                   plan_text: str | None = None) -> dict:
    """source가 빈 문자열이면 통과 필수 조건을 못 넘긴 산출물이다 — 전부 누락으로 본다."""
    judged_by = "svgTextParse" if kind == "svg-onepage" else "htmlParse"
    if not feature_list:
        return _result(0.0, [], ["계획서 기능 목록이 비어 있음"], judged_by)
    if not source:
        return _result(0.0, list(feature_list),
                       ["산출물이 통과 필수 조건을 넘지 못해 대조 생략"], judged_by)
    if kind == "svg-onepage":
        return _match_onepage(feature_list, source, plan_text)
    return _match_html(feature_list, source)
