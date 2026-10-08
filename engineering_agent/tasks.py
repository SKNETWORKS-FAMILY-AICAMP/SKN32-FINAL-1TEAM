"""Orchestration의 T-B1/T-B2 계약에 맞춘 구현 Task."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from engineering_agent.builder_html import build_prototype_html
from engineering_agent.infographic import artsheet, design
from engineering_agent.infographic.compose_guide import FIX_HINT, RETRY_HINT
from engineering_agent.infographic import (
    generate_infographic_content,
    overflow_fields,
    render_infographic,
)

if TYPE_CHECKING:
    from sbrain.contracts.tasks import TB1In, TB1Out, TB2In, TB2Out
    from sbrain.orchestrator.tools import Tools


# 재실행 때 rework_input의 issues · instruction_delta는 지시문에 다시 붙이지 않는다. 조율이 이미
# 지시문 끝에 [재수행 — 문제가 된 내용] · [재작성] 블록으로 붙여서 넘긴다(T-C3 다시 쓰기).


def run_tb1(inp: TB1In, tools: Tools) -> TB1Out:
    from sbrain.contracts.tasks import TB1Out
    from sbrain.models import CheckResult, Prototype

    # plan_doc은 확장 필드다. 조율은 늘 채우지만 타입은 None을 허용한다 — 없으면 기능 이름만으로 만든다.
    # previous_source_text는 T-B1이 재작성 대상이거나 재수행일 때만 온다 — 오면 그 HTML을 고쳐 만든다.
    previous = inp.rework_input.previous_source_text if inp.rework_input is not None else None
    result = build_prototype_html(
        inp.feature_list, inp.item_spec.dump(), inp.category,
        inp.instruction, tools,
        plan_text=_plan_text(inp.plan_doc) if inp.plan_doc is not None else "",
        previous_html=previous or "",
    )
    passed = result["status"] == "success"
    failures = [] if passed else [result["summary"]]
    path = result["entryFilePath"] or ""
    prototype = Prototype(
        entry_file_path=path, kind="html", source_text=result.get("sourceText", ""),
        asset_paths=[], readme_path=None,
        implemented_features=result["implementedFeatures"],
    )
    return TB1Out(
        prototype=prototype, implemented_features=prototype.implemented_features,
        entry_file_path=path,
        check=CheckResult(passed=passed, failures=failures),
    )


_NUMBER_RE = re.compile(r"\d[\d,._]*")

# 값 자리에만 들어앉은 문구. 지면에 글자는 있어도 사실이 없는 상태이므로 미충족으로 본다
# (verification_agent/rules/r4_onepage.py의 _PLACEHOLDER_VALUES와 같은 목록).
_PLACEHOLDER_VALUES = {"정보 없음", "미정", "해당 없음", "n/a", "na", "-", "tbd", "없음",
                       "확인 필요", "확인필요", "추후 확인", "추후 결정", "미입력"}

# run_tb2가 item_spec에서 그대로 옮겨 넣는 지면 값. LLM이 고쳐 쓰지 않는다.
_INPUT_FIELDS = {"item_name", "item_summary", "target_users"}


def _norm_name(value) -> str:
    return re.sub(r"\s+", "", str(value)).casefold()


def _is_blank(value: str) -> bool:
    text = str(value).strip()
    return not text or text.casefold() in _PLACEHOLDER_VALUES


def _numbers(text: str) -> list[str]:
    """숫자 토큰만 뽑는다. 천 단위 구분 쉼표와 소수점은 한 덩이로 보고, 쉼표는 떼어
    "10,000"과 "10000"을 같은 값으로 본다(verification_agent/feature_match.py의 _numbers와 같은 규칙)."""
    return [m.group(0).rstrip(",._").replace(",", "") for m in _NUMBER_RE.finditer(str(text))]


def _unbacked_numbers(value: str, plan_text: str) -> list[str]:
    """값에 든 숫자 중 계획서 원문에서 확인되지 않는 것.

    기능정의서 T-B2 Failure ①의 "도식 수치 불일치"를 구현한다. 값 전체 문자열이
    원문과 같은지는 보지 않는다 — LLM이 원문을 발췌·축약하는 것은 정상이고, 전체
    일치를 요구하면 정상 산출물까지 상시 실패한다. 반면 지면에 적힌 **수치**는
    계획서에 근거가 있어야 하며, 없으면 지어낸 값이다.
    """
    plan_numbers = set(_numbers(plan_text))
    return [n for n in _numbers(value) if n not in plan_numbers]


def _block_texts(content: dict) -> list[tuple[str, str]]:
    """블록 구성(composer)에 들어가는 구절들. 지면에 그대로 찍히므로 계획서에 없는 숫자를 본다."""
    out: list[tuple[str, str]] = []
    for key in ("outcome", "tagline"):
        if str(content.get(key, "")).strip():
            out.append((key, str(content[key])))
    for key in ("before_after", "market_levels", "effects"):
        for row in content.get(key) or []:
            if isinstance(row, dict):
                out += [(key, str(v)) for v in row.values() if str(v).strip()]
    comparison = content.get("comparison") or {}
    if isinstance(comparison, dict):
        out += [("comparison", str(comparison.get("others", "")))] if comparison.get("others") else []
        for row in comparison.get("rows") or []:
            if isinstance(row, dict):
                out += [("comparison", str(v)) for v in row.values() if str(v).strip()]
    flow = content.get("revenue_flow") or {}
    if isinstance(flow, dict):
        out += [("revenue_flow", str(v)) for v in flow.values() if str(v).strip()]
    for m in content.get("key_metrics") or []:
        if isinstance(m, dict) and str(m.get("before", "")).strip():
            out.append(("핵심 수치 이전 값", str(m["before"])))
    for b in content.get("layout") or []:
        if isinstance(b, dict) and str(b.get("title", "")).strip():
            out.append(("블록 제목", str(b["title"])))
    return out


# 계획서 원문에 금액 · 날짜 표현이 있는지. 하나도 없으면 그 칸은 계획서에 원래 없는 정보다.
_MONEY_RE = re.compile(r"\d[\d,.]*\s*(?:천|만|억|조)?\s*원")
_DATE_IN_PLAN_RE = re.compile(r"\d{4}\s*년|\d{4}\s*[./-]\s*\d{1,2}|\d+\s*(?:개월|분기|주차)|[1-4]\s*분기")


def _absent_in_plan(plan_text: str) -> set[str]:
    """계획서 원문에 아예 없는 정보의 칸 이름. 재수행해도 채워지지 않으므로 '누락'을 재수행 사유로 쓰지 않는다.

    실측: 일반 기술개발 양식 계획서(general)는 금액 · 날짜 표현이 0개라 수익모델 단가 · 추진 일정이 늘 비고,
    그때마다 이미지 호출이 든 재수행이 쓸모없이 돌았다. 원문에 하나라도 있는데 못 뽑은 경우는 그대로 사유다
    (다시 뽑으면 채워질 수 있다). 빈 칸은 검증-2 원페이지 핵심 정보 6항목에서 그대로 깎인다."""
    absent = set()
    if not _MONEY_RE.search(plan_text):
        absent.add("수익모델 단가")
    if not _DATE_IN_PLAN_RE.search(plan_text):
        absent.add("추진 일정 기준선")
    return absent


def _check_content(category: str, content: dict, plan_text: str) -> list[str]:
    """T-B2 자체 검사. 기능정의서 T-B2 Failure ①(이미지 미생성 · altText 공백 ·
    도식 수치 불일치)에 대응하는 실패 목록을 만든다.

    실패가 있어도 산출물은 그대로 렌더링해 넘긴다 — 재수행 상한을 넘기면 "그대로
    보내고 미충족을 점수에 반영한다"가 기능정의서의 규정이고, 파일을 내보내지 않으면
    원페이지는 진입 파일 미존재로 산출물층 30점 전체를 잃는다(기획서 5-4).
    """
    failures: list[str] = []
    if not content.get("features"):
        failures.append("계획서 기능 목록이 비어 있음")

    # ItemSpec에서 그대로 옮겨 담은 값(아이템명 · 목표 고객)은 보지 않는다 — 사용자 입력이라 LLM이 지어낼 수 없고,
    # 비어 있어도 재수행으로 채워지지 않는다(아래). 수치 대조를 걸면 사용자가 적은 숫자를 지어낸 값으로 몬다.
    # LLM이 계획서에서 뽑아 채운 값 — 여기가 수치를 지어낼 수 있는 자리다.
    extracted: list[tuple[str, str]] = []

    if category == "원페이지":
        extracted += [
            ("문제 정의", content.get("problem", "")),
            ("해결 방안", content.get("solution", "")),
            ("수익모델 단가", content.get("revenue_unit_price", "")),
            ("추진 일정 기준선", content.get("timeline_baseline", "")),
        ]
        # 기능 설명은 검증-2 계획서 대조의 판정 대상이다. 비면 그 기능이 대조에서 빠진다.
        details = content.get("feature_details") or []
        extracted += [(f"기능 설명({name})", details[i] if i < len(details) else "")
                      for i, name in enumerate(content.get("features") or [])]
    elif category == "웹개발":
        steps = content.get("flow_steps") or []
        if not steps:
            failures.append("사용자 화면 흐름 누락")
        extracted += [(f"화면 흐름 {i + 1}단계", s) for i, s in enumerate(steps)]
    else:  # AI_API
        pipeline = content.get("pipeline") or {}
        for key, label in (("input", "입력"), ("process", "처리"), ("output", "출력")):
            extracted.append((f"{label} 단계", pipeline.get(key, "")))

    # 아이템명 · 목표 고객은 조율이 준 입력값이라 재수행해도 채워지지 않는다(실측: 실제 예시 계획서 셋의 목표 고객이
    # 모두 '확인 필요'). 실패로 올리면 이미지 호출이 든 재수행만 쓸모없이 돈다 — 넘침(_INPUT_FIELDS)과 같은 이유로
    # 사유에서 뺀다. 빈 값은 검증-2 원페이지 핵심 정보 6항목에서 그대로 깎인다.
    absent = _absent_in_plan(plan_text)
    for label, value in extracted:
        if _is_blank(value) and label not in absent:
            failures.append(f"{label} 누락")

    # 블록 구성 재료 — 선택 항목이라 비어도 누락이 아니다. 숫자 대조만 한다.
    extracted += _block_texts(content)

    # 아래는 선택 항목이라 비어도 누락이 아니다. 숫자 대조만 한다.
    # 핵심 수치 카드(원페이지)와 웹개발 · AI API 지면의 기능 설명.
    if category == "원페이지":
        extracted += [(f"핵심 수치({m.get('label', '')})", str(m.get("value", "")))
                      for m in content.get("key_metrics") or [] if isinstance(m, dict)]
        extracted += [(f"해결 절차 {i + 1}단계", str(step))
                      for i, step in enumerate(content.get("solution_steps") or [])]
        # 수치 카드의 설명에 목표/실적 기간 등 숫자가 들어갈 수도 있다.
        extracted += [("핵심 수치 설명", str(m.get("label", "")))
                      for m in content.get("key_metrics") or [] if isinstance(m, dict)]
    else:
        details = content.get("feature_details") or []
        extracted += [(f"기능 설명({name})", details[i])
                      for i, name in enumerate(content.get("features") or [])
                      if i < len(details) and not _is_blank(details[i])]

    for label, value in extracted:
        if _is_blank(value):
            continue
        unbacked = _unbacked_numbers(value, plan_text)
        if unbacked:
            failures.append(f"{label}: 계획서에 없는 수치 {', '.join(unbacked)}")

    for field in overflow_fields(category, content):
        # 아이템명 · 한 줄 소개 · 목표 고객은 조율이 준 입력값이라 재수행해도 짧아지지 않는다.
        # 실패로 올리면 같은 결과를 내는 재수행(이미지 호출 포함)만 반복되므로 사유로 쓰지 않는다.
        if field in _INPUT_FIELDS:
            continue
        failures.append(f"{field}: 지면 폭을 넘겨 잘라 넣음 — 더 짧은 문장이 필요함")
    return failures


def _plan_text(plan_doc) -> str:
    sections = "\n".join(
        f"{section.title}\n" + "\n".join(sentence.text for sentence in section.sentences)
        for section in plan_doc.sections
    )
    tables = "\n".join(
        f"{table.title}\n" + "\n".join(" | ".join(row) for row in table.rows)
        for table in plan_doc.tables
    )
    return f"{sections}\n{tables}"


# 사용자가 고칠 문제 없이 재작성을 고르면 조율은 사유 · 지시 칸을 이 문구로 채운다(조율 sbrain_flow.REWORK_DEFAULT_REASON).
# 조율이 이 문구를 바꾸면 새 구성 요청을 알아보지 못하고 '문제만 고치기'로 처리한다 — 구성이 유지될 뿐 실패하지는 않는다.
_USER_ONLY_REASON = "사용자가 이 묶음의 재작성을 요청했습니다."


def _wants_redesign(rework_input) -> bool:
    """새 구성으로 다시 만들지(결정 0010).
    - 재수행(검사 미통과): 새 구성. 기능정의서 v1.10 T-B2 "재수행 때는 지면 구성 뼈대와 아이콘이 달라진다".
    - 미달 사유가 있는 재작성: 구성을 지키고 문제만 고친다(기획서 5-6 '문제가 된 곳만 고치고 잘 된 부분은 지킨다').
    - 고칠 문제 없이 사용자가 고른 재작성(사유가 기능정의서 고정 문구뿐): 다르게 만들어 달라는 요청으로 보고 새 구성."""
    if rework_input is None:
        return False
    if rework_input.mode == "재수행":
        return True
    issues = [str(i).strip() for i in rework_input.issues if str(i).strip()]
    return all(i == _USER_ONLY_REASON for i in issues)


def run_tb2(inp: TB2In, tools: Tools) -> TB2Out:
    from sbrain.contracts.tasks import TB2Out
    from sbrain.models import CheckResult, Infographic

    plan_text = _plan_text(inp.plan_doc)
    redesign = _wants_redesign(inp.rework_input)
    # 재수행은 구성이 바뀌어도 문제(검사 사유)를 고치는 실행이다. '다시 만들기를 눌렀다'는 사유 없는 재작성만.
    rework = inp.rework_input
    hint = ("" if rework is None else RETRY_HINT if redesign and rework.mode == "재작성" else FIX_HINT)
    content = generate_infographic_content(
        inp.category, f"아이템명: {inp.item_spec.item_name}\n목표 고객: {inp.item_spec.target_customer}\n"
        f"기능 목록: {', '.join(inp.plan_doc.feature_list)}\n{plan_text}\n"
        f"작업 지시: {inp.instruction}" + (f"\n{hint}" if hint else ""), tools,
    )
    content["item_name"] = inp.item_spec.item_name
    content["target_users"] = inp.item_spec.target_customer
    content["item_summary"] = inp.item_spec.one_line_summary
    content["features"] = inp.plan_doc.feature_list
    # LLM이 준 설명을 기능 목록 순서에 맞춰 문자열로 편다. 이름이 목록과 다른 항목은
    # 버린다 — 검증-2가 기능명으로 설명을 찾으므로 어긋난 이름은 없는 설명과 같다.
    # 이름은 공백 · 대소문자를 무시하고 맞춘다(검증-2 feature_match._norm과 같은 기준).
    # 정규화하면 같아지는 이름이 둘 이상이면 어느 설명인지 알 수 없으므로 합치지 않고 버린다.
    by_name: dict[str, str | None] = {}
    for d in content.get("feature_details") or []:
        key, detail = _norm_name(d.get("name", "")), str(d.get("detail", "")).strip()
        by_name[key] = None if key in by_name and by_name[key] != detail else detail
    keys = [_norm_name(f) for f in inp.plan_doc.feature_list]
    content["feature_details"] = ["" if keys.count(k) > 1 else by_name.get(k) or "" for k in keys]
    # 지면 구성 · 대표 그림 · 그림체를 재료가 보여 주는 관계로 정한다(design.py). 입력값을 옮겨 담은 뒤에
    # 정해야 목표 고객 · 기능 수가 판단에 들어간다. 그림(artsheet)보다 먼저 — 그림 칸이 구성을 따른다.
    content = design.apply(inp.category, content, redesign=redesign)

    # 맞춤 아이콘(선택 재료). 이미지 호출 통로(tools.image)가 없거나 실패하면 None이고 지면은 기본
    # 아이콘으로 나간다. 아이콘이 있으면 지면 모양이 달라져 글자 칸 폭도 달라지므로, 넘침 검사
    # (_check_content)보다 먼저 만든다.
    content["_art"] = artsheet.generate(inp.category, content, tools)

    failures = _check_content(inp.category, content, plan_text)
    # 검사에 걸려도 파일은 만든다. 기획서 5-4가 원페이지 6항목에 부분 점수를 둔 이유가
    # "한 항목 누락에 2점이 통째로 날아가면 결과 화면의 설명력이 떨어진다"인데, 산출물을
    # 아예 내보내지 않으면 진입 파일 미존재로 산출물층 30점 전체가 0이 되어 그 부분 점수
    # 경로에 도달할 수 없다. 기능정의서 T-B2도 재수행 상한을 넘기면 "그대로 보내고
    # 미충족을 점수에 반영한다"이므로, 미달 사실은 CheckResult로만 알린다.
    saved = render_infographic(inp.category, content)
    infographic = Infographic(
        image_path=saved["file_path"], format="svg", alt_text=saved["alt_text"]
    )
    return TB2Out(
        infographic=infographic,
        check=CheckResult(passed=not failures, failures=failures),
    )
