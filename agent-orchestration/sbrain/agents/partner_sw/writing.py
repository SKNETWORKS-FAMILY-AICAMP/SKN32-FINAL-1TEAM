"""T-W1 본문 작성(F16) · T-W2 그림(F18) · T-W3 표(F17) — 담당자 run_pipeline의 항목 반복을 Task 단위로 나눠 부른다 (spec 4.7).

- 항목마다 담당자 section_source(근거 · 원본 사실 · 울타리)를 만들고 담당자 함수 · 정리 함수(_strip_section_heading ·
  _normalize_section_output · _normalize_image_output · table_arguments · _table_fallback_text)를 그대로 쓴다.
- 목표 항목(ReworkInput.targetItems)이 있으면 그 항목만 다시 만들고 나머지는 직전 결과(base…)를 그대로 싣는다. 직전 결과가
  없는 항목은 목표 밖이어도 만든다. 다시 만들 때 담당자 함수에 validationFeedback = 그 항목의 문제 목록, retryInstruction =
  재작성 보완 지시(재수행이면 빈 문자열), previousText = 직전 본문(T-W1)을 넘긴다.
- T-W1 · T-W2는 동시에 부른다(4개 · 2개, spec 4.14). 결과는 양식 순서로 모은다. 재개 때 받은 결과(키 = 항목 번호 · 그림 ID)는
  다시 부르지 않는다(4.13).
- T-W3는 규칙 코드다(LLM 없음 — tools를 받지만 llm을 부르지 않는다). 표 검사(requiredColumns · 행 길이)에 걸리면 그 시도에서 바로
  표를 지우고 본문 서술로 대체하고 check 불통과 + final_action(4.8). fallbackItems(검증-1 재수행 뒤에도 fail인 표)도 같은 대체를
  한다(4.10).
- 그림 SVG는 tools.files로만 넣는다(diagram_svg — 담당자 flow_image 그리기). 출력 charts는 빈 목록이다.
"""
from __future__ import annotations

from typing import Any

from ...contracts.tasks import TW1In, TW1Out, TW2In, TW2Out, TW3In, TW3Out
from ...models import CheckResult, DiagramSpec, PlanDoc, PlanSection, TableSpec
from ...orchestrator.tools import Tools
from . import diagram_svg, inputs as ins
from .agent_strategy.functions import gpt_functions as gpt
from .agent_strategy.functions import python_functions as py
from .agent_strategy.runtime.pipeline import (
    _normalize_image_output, _normalize_section_output, _strip_section_heading, _table_fallback_text,
    _writing_criteria, section_source, table_arguments,
)
from .calls import partner_call
from .common import (
    TW1_CONCURRENCY, TW2_CONCURRENCY, canonical_of, form_items, gather, kind_of, made_items, original_of, pick,
    received_from, research_of, retry_instruction, section_specs, spec_for, targets_of,
)
from .outputs import (
    DIAGRAM_OUTPUT_KEYS, IMAGE_SPEC_KEYS, SECTION_KEYS, TABLE_DEFAULTS, TABLE_KEYS, sentences,
)

FLOWS = ("USER_FLOW", "SERVICE_ARCHITECTURE")   # 그림 항목 하나의 두 그림 (담당자 F18)
FINAL_TW3 = "표 제거 · 본문 서술 대체"           # T-W3 확정 동작 (spec 4.8)
TABLE_FAIL_DEFAULT = "표 필수 구조 검증 실패"     # 대체 사유가 없을 때 (담당자 코드와 같은 글자)
STATUS_POLICY = ["provided", "proposed", "needs_confirmation"]


# ── T-W1 본문 (F16) ──────────────────────────────────────
def run_tw1(inp: TW1In, tools: Tools) -> TW1Out:
    kind = kind_of(inp.strategy_data, inp.company_info.applicant_type)
    specs = section_specs(kind)
    items = form_items(inp.form_spec, kind)
    codes = [code for code, _, _, k in items if k == "section"]
    rework = inp.rework_input
    targets = targets_of(rework)
    base = dict(inp.base_section_outputs or {})
    base_sections = {s.section_code: s for s in (inp.base_plan_doc.sections if inp.base_plan_doc else [])}
    made = made_items(codes, targets, lambda c: c in base)
    canonical = canonical_of(inp.strategy_data, inp.market_strategy_data)
    original = original_of(inp.strategy_data, inp.feature_list)
    research = research_of(inp.strategy_data)
    received = received_from(inp.prior_results, made)

    def previous_text(code: str) -> str | None:
        if code in base:
            return base[code].get("generatedText")
        sec = base_sections.get(code)
        return "\n".join(s.text for s in sec.sentences) if sec is not None else None

    def one(code: str) -> dict[str, Any]:
        spec = spec_for(specs, code)
        source = section_source(spec, canonical, original, research)
        rules: dict[str, Any] = {"documentType": kind, "sectionCriteria": _writing_criteria(kind, code),
                                 "tableGenerationEnabled": False}
        if rework is not None:
            rules["retryInstruction"] = retry_instruction(rework)
        rules.update(validationFeedback=list(targets.get(code, [])) if rework is not None else [],
                     previousText=previous_text(code) if rework is not None else None,
                     preserveProvenance=True, statusPolicy=list(STATUS_POLICY))
        with partner_call(tools.for_item(code), inp.instruction):
            output = gpt.generate_section(section_spec=spec, source_data=source, writing_rules=rules)
        output["generatedText"] = _strip_section_heading(output.get("generatedText", ""), spec)
        output = _normalize_section_output(output, spec, source, kind)
        return pick(output, SECTION_KEYS)

    todo = [c for c in made if c not in received]
    got = gather(todo, one, TW1_CONCURRENCY, {k: inp.prior_results[k] for k in received}, name="tw1")
    outputs = {c: (got[c] if c in got else received[c] if c in received else base[c]) for c in codes}

    sections: list[PlanSection] = []
    for code, title, tag, k in items:
        if k == "section":
            text = outputs[code].get("generatedText") or ""
            sections.append(PlanSection(section_code=code, title=title, sentences=sentences(code, text), tag=tag,
                                        content_type="section"))
        elif k == "table" and code in base_sections:   # 표 서술은 T-W3가 만들고 M-1이 바꾼다 — 직전 것을 그대로 둔다
            sections.append(base_sections[code].model_copy(update={"title": title, "tag": tag, "content_type": "table"}))
        else:
            sections.append(PlanSection(section_code=code, title=title, sentences=[], tag=tag, content_type=k))
    plan = PlanDoc(sections=sections, feature_list=list(inp.feature_list), charts=[], tables=[], protected_tokens=[])
    return TW1Out(plan_doc=plan, sections=sections, feature_list=list(inp.feature_list),
                  check=CheckResult(passed=True, failures=[]), section_outputs=outputs)


# ── T-W2 그림 (F18) ──────────────────────────────────────
def run_tw2(inp: TW2In, tools: Tools) -> TW2Out:
    kind = kind_of(inp.strategy_data)
    specs = section_specs(kind)
    codes = [s.section_code for s in inp.plan_doc.sections if s.content_type == "image"]
    rework = inp.rework_input
    targets = targets_of(rework)
    base_outputs = dict(inp.base_diagram_outputs or {})
    base_diagrams = list(inp.base_diagrams or [])

    def has_base(code: str) -> bool:
        return code in base_outputs and {d.flow_type for d in base_diagrams if d.source_ref == code} >= set(FLOWS)

    made = made_items(codes, targets, has_base)
    keys = [f"{code}-{flow}" for code in made for flow in FLOWS]
    canonical = canonical_of(inp.strategy_data, None)
    original = original_of(inp.strategy_data, inp.feature_list)
    research = research_of(inp.strategy_data)
    received = received_from(inp.prior_results, keys)

    def one(key: str) -> dict[str, Any]:
        code, flow = key.rsplit("-", 1)          # 그림 ID '<항목 번호>-<flowType>'
        spec = spec_for(specs, code)
        source = section_source(spec, canonical, original, research)
        architecture: dict[str, Any] = {"design": source.get("architecture", {}),
                                        "validationFeedback": list(targets.get(code, [])) if rework is not None else []}
        if rework is not None:
            architecture["retryInstruction"] = retry_instruction(rework)
        with partner_call(tools.for_item(key), inp.instruction):
            output = gpt.generate_image_spec(item=source.get("item_spec"), architecture=architecture, flow_type=flow)
        return pick(_normalize_image_output(output, flow), IMAGE_SPEC_KEYS)

    todo = [k for k in keys if k not in received]
    got = gather(todo, one, TW2_CONCURRENCY, {k: inp.prior_results[k] for k in received}, name="tw2")
    specs_by_key = {**received, **got}

    diagrams: list[DiagramSpec] = []
    outputs: dict[str, dict[str, Any]] = {}
    for code in codes:
        if code not in made:
            outputs[code] = base_outputs[code]
            diagrams.extend(d for flow in FLOWS for d in base_diagrams if d.source_ref == code and d.flow_type == flow)
            continue
        image_specs = [specs_by_key[f"{code}-{flow}"] for flow in FLOWS]
        outputs[code] = pick({**image_specs[0], "imageSpecs": image_specs, "imageTypes": list(FLOWS)},
                             DIAGRAM_OUTPUT_KEYS)
        for flow, spec_out in zip(FLOWS, image_specs):
            ref = tools.files.put(diagram_svg.FILE_NAMES[flow], diagram_svg.render(spec_out), diagram_svg.SVG_TYPE)
            style = spec_out.get("visualStyle") if isinstance(spec_out.get("visualStyle"), dict) else {}
            diagrams.append(DiagramSpec(diagram_id=f"{code}-{flow}", flow_type=flow, nodes=list(spec_out["nodes"]),
                                        visual_style=style, source_ref=code, image_file=ref))
    return TW2Out(charts=[], check=CheckResult(passed=True, failures=[]), diagrams=diagrams,
                  diagram_outputs=outputs)


# ── T-W3 표 (F17, 규칙 코드) ──────────────────────────────
def _cell(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return ins.CONFIRM
    return str(value)


def _table_spec(code: str, title: str, spec: dict[str, Any], output: dict[str, Any]) -> TableSpec | None:
    tables = output.get("tables") or []
    table = tables[0] if tables and isinstance(tables[0], dict) else None
    if table is None:
        return None
    headers = [str(h) for h in (spec.get("rules", {}).get("requiredColumns") or table.get("columns") or [])]
    rows = [[_cell(row.get(h)) for h in headers] for row in table.get("rows") or [] if isinstance(row, dict)]
    return TableSpec(table_id=f"table-{code}", title=title, headers=headers, rows=rows, source_ref=code)


def _table_problems(spec: dict[str, Any], output: dict[str, Any], table: TableSpec | None) -> list[str]:
    """담당자 표 검사 — 표마다 requiredColumns가 모두 있고 행 길이 = 열 수 (spec 4.8). 문구에 내용 없음."""
    required = [str(c) for c in spec.get("rules", {}).get("requiredColumns") or []]
    tables = [t for t in output.get("tables") or [] if isinstance(t, dict)]
    problems = []
    if required and not tables:
        problems.append("필수 표 없음")
    for t in tables:
        if set(required) - {str(c) for c in t.get("columns") or []}:
            problems.append("필수 표 컬럼 누락")
            break
    if table is not None and any(len(r) != len(table.headers) for r in table.rows):
        problems.append("행 길이와 열 수 불일치")
    return problems


def _fallback(output: dict[str, Any], spec: dict[str, Any], reason: str) -> dict[str, Any]:
    """표를 지우고 본문 서술로 대체한다 — 담당자 run_pipeline의 표 대체 그대로."""
    output["generatedText"] = _table_fallback_text(output, spec)
    output["tables"] = []
    output["tableFallbackUsed"] = True
    output["fallbackReason"] = reason or TABLE_FAIL_DEFAULT
    return output


def run_tw3(inp: TW3In, tools: Tools) -> TW3Out:
    """tools는 등록부 모양 때문에 받지만 쓰지 않는다(LLM을 부르지 않는 Task — uses_llm=False)."""
    company = inp.company_info
    kind = kind_of(inp.strategy_data, company.applicant_type)
    specs = section_specs(kind)
    items = form_items(inp.form_spec, kind)
    table_items = [(code, title, tag) for code, title, tag, k in items if k == "table"]
    rework = inp.rework_input
    targets = targets_of(rework)
    fallback_items = set(rework.fallback_items) if rework is not None else set()
    base_outputs = dict(inp.base_table_outputs or {})
    base_sections = {s.section_code: s for s in inp.base_table_sections or []}
    base_tables = {t.source_ref: t for t in inp.base_tables or []}
    data, unassigned = ins.table_data(company, kind)
    raw = {"tableData": data}
    canonical = canonical_of(inp.strategy_data, None)
    wanted = set(targets) | fallback_items
    made = made_items([c for c, _, _ in table_items], wanted, lambda c: c in base_outputs and c in base_sections)

    tables: list[TableSpec] = []
    sections: list[PlanSection] = []
    outputs: dict[str, dict[str, Any]] = {}
    failed: dict[str, list[str]] = {}
    for code, title, tag in table_items:
        if code not in made:
            outputs[code] = base_outputs[code]
            sections.append(base_sections[code])
            if code in base_tables and not base_outputs[code].get("tableFallbackUsed"):
                tables.append(base_tables[code])
            continue
        spec = spec_for(specs, code)
        args = table_arguments(raw, kind, spec, canonical)
        if kind == ins.PRE_STARTUP and code.endswith(".5.3") and unassigned:
            # 예비창업 단계 미지정 행 — 어느 단계 표에도 넣지 않고 2.5.3 표의 규칙으로 보존한다 (spec 4.4, 잠정)
            args["rules"].update(unassignedOriginalRows=[dict(r) for r in unassigned],
                                 note="단계 미지정 원본은 별도 보존. 각 단계에 중복 배정하지 않음")
        output = py.generate_table(**args)
        table = _table_spec(code, title, spec, output)
        problems = _table_problems(spec, output, table)
        if problems:   # 확정 동작 — 그 시도에서 바로 표 → 본문 서술 대체 (spec 4.8)
            failed[code] = problems
            output = _fallback(output, spec, " · ".join(problems))
        elif code in fallback_items:   # 검증-1 재수행 뒤에도 fail인 표 (spec 4.10) — 판정은 fail 그대로
            reason = " · ".join(targets.get(code) or (rework.issues if rework is not None else []))
            output = _fallback(output, spec, reason)
        output.setdefault("tableFallbackUsed", False)
        output.setdefault("fallbackReason", "")
        outputs[code] = pick(output, TABLE_KEYS, TABLE_DEFAULTS)
        sections.append(PlanSection(section_code=code, title=title, sentences=sentences(code, output["generatedText"]),
                                    tag=tag, content_type="table"))
        if not output.get("tableFallbackUsed") and table is not None:
            tables.append(table)
    check = CheckResult(passed=True, failures=[])
    if failed:
        check = CheckResult(passed=False, failures=[f"표 검사 불통과 {code}: {', '.join(p)}" for code, p in failed.items()],
                            final_action=FINAL_TW3, failed_items=failed)
    return TW3Out(tables=tables, check=check, table_sections=sections, table_outputs=outputs)
