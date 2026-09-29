"""Orchestration의 T-B1/T-B2 계약에 맞춘 구현 Task."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from engineering_agent.builder_html import build_prototype_html
from engineering_agent.infographic import (
    generate_infographic_content,
    overflow_fields,
    render_infographic,
)

if TYPE_CHECKING:
    from sbrain.contracts.tasks import TB1In, TB1Out, TB2In, TB2Out
    from sbrain.orchestrator.tools import Tools


def _instruction(base: str, rework) -> str:
    if rework is None:
        return base
    details = [base, *rework.issues]
    if rework.order is not None:
        details.append(rework.order.instruction_delta)
    return "\n".join(part for part in details if part)


def run_tb1(inp: TB1In, tools: Tools) -> TB1Out:
    from sbrain.contracts.tasks import TB1Out
    from sbrain.models import CheckResult, Prototype

    result = build_prototype_html(
        inp.feature_list, inp.item_spec.dump(), inp.category,
        _instruction(inp.instruction, inp.rework_input), tools,
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
_PLACEHOLDER_VALUES = {"정보 없음", "미정", "해당 없음", "n/a", "na", "-", "tbd", "없음"}


def _is_blank(value: str) -> bool:
    text = str(value).strip()
    return not text or text.casefold() in _PLACEHOLDER_VALUES


def _numbers(text: str) -> list[str]:
    """숫자 토큰만 뽑는다. 천 단위 구분 쉼표와 소수점은 한 덩이로 본다."""
    return [m.group(0).rstrip(",._") for m in _NUMBER_RE.finditer(str(text))]


def _unbacked_numbers(value: str, plan_text: str) -> list[str]:
    """값에 든 숫자 중 계획서 원문에서 확인되지 않는 것.

    기능정의서 T-B2 Failure ①의 "도식 수치 불일치"를 구현한다. 값 전체 문자열이
    원문과 같은지는 보지 않는다 — LLM이 원문을 발췌·축약하는 것은 정상이고, 전체
    일치를 요구하면 정상 산출물까지 상시 실패한다. 반면 지면에 적힌 **수치**는
    계획서에 근거가 있어야 하며, 없으면 지어낸 값이다.
    """
    plan_numbers = set(_numbers(plan_text))
    return [n for n in _numbers(value) if n not in plan_numbers]


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

    # ItemSpec에서 그대로 옮겨 담은 값 — 사용자 입력이라 LLM이 지어낼 수 없다.
    # 비었는지만 본다. 수치 대조를 걸면 사용자가 적은 숫자를 지어낸 값으로 몰게 된다.
    given: list[tuple[str, str]] = [("아이템명", content.get("item_name", ""))]
    # LLM이 계획서에서 뽑아 채운 값 — 여기가 수치를 지어낼 수 있는 자리다.
    extracted: list[tuple[str, str]] = []

    if category == "원페이지":
        given.append(("목표 고객", content.get("target_users", "")))
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

    for label, value in given + extracted:
        if _is_blank(value):
            failures.append(f"{label} 누락")

    for label, value in extracted:
        if _is_blank(value):
            continue
        unbacked = _unbacked_numbers(value, plan_text)
        if unbacked:
            failures.append(f"{label}: 계획서에 없는 수치 {', '.join(unbacked)}")

    for field in overflow_fields(category, content):
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


def run_tb2(inp: TB2In, tools: Tools) -> TB2Out:
    from sbrain.contracts.tasks import TB2Out
    from sbrain.models import CheckResult, Infographic

    plan_text = _plan_text(inp.plan_doc)
    content = generate_infographic_content(
        inp.category, f"아이템명: {inp.item_spec.item_name}\n목표 고객: {inp.item_spec.target_customer}\n"
        f"기능 목록: {', '.join(inp.plan_doc.feature_list)}\n{plan_text}\n"
        f"작업 지시: {_instruction(inp.instruction, inp.rework_input)}", tools,
    )
    content["item_name"] = inp.item_spec.item_name
    content["target_users"] = inp.item_spec.target_customer
    content["features"] = inp.plan_doc.feature_list
    if inp.category == "원페이지":
        # LLM이 준 설명을 기능 목록 순서에 맞춰 문자열로 편다. 이름이 목록과 다른 항목은
        # 버린다 — 검증-2가 기능명으로 설명을 찾으므로 어긋난 이름은 없는 설명과 같다.
        by_name = {str(d.get("name", "")).strip(): str(d.get("detail", "")).strip()
                   for d in content.get("feature_details") or []}
        content["feature_details"] = [by_name.get(f, "") for f in inp.plan_doc.feature_list]

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
