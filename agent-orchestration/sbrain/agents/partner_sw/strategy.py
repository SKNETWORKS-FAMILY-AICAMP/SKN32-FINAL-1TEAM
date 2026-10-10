"""T-S1 요구사항 분석 · T-S2 목표 시장 분석 — 담당자 전략 함수(F01 ~ F15)를 담당자 run_pipeline 순서대로 부른다 (spec 4.7).

- T-S1 = F01 · F02 · F05 ~ F09 · F13 ~ F15(+ 로컬 자료 검색), T-S2 = F03 · F04 · F10 ~ F12 (담당자 워크플로우 3.1.1).
  앞 함수 결과를 쓰므로 차례로 부른다(spec 4.14). 담당자 run_pipeline의 단계 함수 호출 · 결과 정리(compact ·
  _annotate_status · _attach_provenance · 예비창업 단계별 예산)를 그대로 쓰고, 파이프라인을 통째로 부르지 않는다.
- 호출은 모두 partner_call 블록 안 — LLM은 tools.llm(purpose=F번호, json_mode=True), 자료 검색은 tools.search('자료 검색').
  지시문(T-C3 instruction)은 그 Task의 모든 LLM 호출에 같은 것을 싣는다.
- 재개(4.13): 받은 결과 키는 F번호다. 재개 때 받은 F번호는 다시 부르지 않고 다음부터 이어 간다. 자료 검색은 값이 정해져
  있어 받은 결과로 남기지 않고 다시 한다.
- 자체 검사(4.8): T-S1은 F02 coreFeatures가 비면 그 시도에서 바로 itemSpec.coreFeatures를 featureList로 내고 check 불통과
  (final_action 'itemSpec.coreFeatures 승계'). T-S2는 담당자 규칙 검사가 없어 늘 통과.
"""
from __future__ import annotations

from typing import Any, Callable

from ...contracts.tasks import TS1In, TS1Out, TS2In, TS2Out
from ...models import CheckResult
from ...orchestrator.tools import Tools
from . import inputs as ins
from .agent_strategy.functions import gpt_functions as gpt
from .agent_strategy.functions import python_functions as py
from .agent_strategy.runtime.llm_runtime import compact
from .agent_strategy.runtime.pipeline import _annotate_status, _attach_provenance, _pre_startup_budget_phases, _provenance
from .agent_strategy.runtime.research_context import retrieve
from .calls import partner_call
from .common import Steps
from .outputs import market_analysis, names, numeric_tokens, requirement_analysis
from .purposes import F01, F02, F03, F04, F05, F06, F07, F08, F09, F10, F11, F12, F13, F14, F15

FINAL_TS1 = "itemSpec.coreFeatures 승계"   # T-S1 확정 동작 (spec 4.8)
NO_FEATURES = "F02 coreFeatures 없음"       # T-S1 검사 불통과 사유 (내용 없음)
EMPTY_EVIDENCE: dict[str, Any] = {"sources": [], "issues": []}


def _call(fid: str, fn: Callable[..., dict], provenance: dict[str, Any] | None = None, **kwargs: Any) -> dict:
    """담당자 run_pipeline의 call()과 같다 — 함수를 부르고 F02 ~ F15 결과에 상위 근거 · 원본 사실을 붙인다.
    provenance를 주면 원본 사실을 그 값으로 붙인다(F02 — 참고값 targetCustomerHint가 원본 사실에 들어가지 않게)."""
    value = fn(**kwargs)
    return _attach_provenance(fid, value, kwargs if provenance is None else provenance)


# ── T-S1 ─────────────────────────────────────────────
def run_ts1(inp: TS1In, tools: Tools) -> TS1Out:
    company = inp.company_info
    kind = ins.document_type(company.applicant_type)
    form = inp.form_input
    description = (form.idea_text if form is not None else "") or inp.item_spec.one_line_summary
    start, end = ins.dev_months(form.development_period if form is not None else None)
    duration = ins.duration_months(start, end)
    limits = ins.strategy_limits(kind, end, inp.selected_announcement.support_amount_max, inp.item_spec.core_features)
    project = ins.project_body(description, company)
    item_input = {k: project.get(k) for k in ins.ITEM_KEYS}
    f02_input = {**item_input, ins.TARGET_HINT_KEY: inp.item_spec.target_customer}   # F02 요청에만 (spec 4.4)
    team = ins.team_input(company)
    resources = ins.resource_input(company)
    budgets = ins.budget_rows(company, kind)
    schedules = ins.schedule_rows(company)
    tech_field = project.get("tech_field") or ""
    steps = Steps(inp.prior_results)

    with partner_call(tools, inp.instruction):
        query = project["description"] + " " + tech_field
        web = steps.run(F01, lambda: _call(F01, py.collect_web_data, query=query, source_type="attached_crawling",
                                           target_fields=["market", "development", "design"]))
        market_ev = steps.run(None, lambda: retrieve(query, domains=("market",), limit=4, char_budget=5500))
        competitor_ev = steps.run(None, lambda: retrieve(query + " 경쟁사 경쟁 비교", domains=("market",), limit=4,
                                                         char_budget=4500))
        dev_ev = steps.run(None, lambda: retrieve(query, domains=("development",), limit=3, char_budget=3000))
        evidence = {s["sourceRef"]: s for ctx in (web, market_ev, competitor_ev, dev_ev) for s in ctx["sources"]}
        c: dict[str, Any] = {"web_data": {"sources": web["sources"], "issues": web["issues"]}}
        c["item_spec"] = steps.run(F02, lambda: _annotate_status(F02, compact(_call(
            F02, gpt.analyze_item, provenance={"item_input": item_input, "research_data": dev_ev},
            item_input=f02_input, research_data=dev_ev)),
            {"item_input": item_input, "research_data": dev_ev}))   # 상태 표시도 원본 사실만 — 참고값으로 확정값을 만들지 않는다
        requirements = c["item_spec"].get("coreFeatures") or [tech_field]
        c["team_capability"] = steps.run(F05, lambda: compact(_call(
            F05, gpt.analyze_team_capability, team_data=team, item_requirements=requirements)))
        c["development_goal"] = steps.run(F06, lambda: _annotate_status(F06, compact(_call(
            F06, gpt.define_development_goal, item_spec=c["item_spec"], duration=duration, target_field=tech_field)),
            {"item_spec": c["item_spec"], "duration": duration, "target_field": tech_field}))
        c["development_method"] = steps.run(F07, lambda: compact(_call(
            F07, gpt.define_development_method,
            core_technologies=c["development_goal"].get("core_technologies", requirements),
            constraints={"duration": duration, "research": dev_ev})))
        c["architecture"] = c["development_method"].get("architecture", {})
        c["development_plan"] = steps.run(F08, lambda: _annotate_status(F08, compact(_call(
            F08, gpt.create_development_plan, goals=c["development_goal"], duration=duration, phases=schedules)),
            {"goals": c["development_goal"], "duration": duration, "phases": schedules}))
        c["production_plan"] = steps.run(F09, lambda: _annotate_status(F09, compact(_call(
            F09, gpt.create_production_plan, product=c["item_spec"], development_plan=c["development_plan"],
            phases=schedules)),
            {"product": c["item_spec"], "development_plan": c["development_plan"], "phases": schedules}))
        c["resource_plan"] = steps.run(F13, lambda: compact(_call(
            F13, gpt.create_resource_plan, item=c["item_spec"], required_capabilities=requirements,
            team={"analysis": c["team_capability"], "originalFacts": resources},
            resource_type=["장비", "채용", "협력기관"])))

        def budget() -> dict:
            value = compact(_call(F14, py.calculate_budget, items=budgets, quantity=[1] * len(budgets),
                                  unit_price=[r["total_amount"] for r in budgets], phase="미구분",
                                  rules={"self_funding_allowed": None}))
            return _pre_startup_budget_phases(value, budgets) if kind == ins.PRE_STARTUP else value
        c["budget"] = steps.run(F14, budget)
        c["schedule"] = steps.run(F15, lambda: compact(_call(
            F15, py.create_schedule, tasks=[r["category"] for r in schedules], duration=duration,
            milestones=schedules)))
    c["feasibility_plan"] = {"goal": c["development_goal"], "development": c["development_plan"],
                             "budget": c["budget"]}
    original = {
        "item": item_input, "period": {"start": start, "end": end, "durationMonths": duration},
        "strategy_limits": limits, "team": team, "resources": resources,
        "budget": {k: c["budget"].get(k) for k in ("items", "total", "government_amount", "self_cash_amount",
                                                   "self_in_kind_amount", "phase")},
        "schedule": schedules,
        "strategyOutputs": {k: _provenance(v) for k, v in c.items() if not k.startswith("_")},
    }
    research = {"sources": list(evidence.values()), "market": market_ev, "competitor": competitor_ev,
                "development": dev_ev, "availableFiles": web.get("availableFiles", []),
                "issues": market_ev["issues"] + competitor_ev["issues"] + dev_ev["issues"]}

    features = names(c["item_spec"].get("coreFeatures"))
    check = CheckResult(passed=True, failures=[])
    if not features:   # 확정 동작 — 그 시도에서 바로 승계, 빈 featureList를 내지 않는다 (spec 4.8)
        features = list(inp.item_spec.core_features)
        check = CheckResult(passed=False, failures=[NO_FEATURES], final_action=FINAL_TS1)
    strategy_data = {**c, "research": research, "original_facts": original, "strategy_limits": limits,
                     "document_type": kind}
    return TS1Out(requirement_analysis=requirement_analysis(inp.item_spec, c["item_spec"], features),
                  feature_list=features, check=check, strategy_data=strategy_data)


# ── T-S2 ─────────────────────────────────────────────
def run_ts2(inp: TS2In, tools: Tools) -> TS2Out:
    sd = inp.strategy_data or {}
    item = sd.get("item_spec") or {}
    research = sd.get("research") if isinstance(sd.get("research"), dict) else {}
    market_ev = research.get("market") or EMPTY_EVIDENCE
    competitor_ev = research.get("competitor") or EMPTY_EVIDENCE
    target = ins.TARGET_CUSTOMER
    steps = Steps(inp.prior_results)
    with partner_call(tools, inp.instruction):
        market = steps.run(F03, lambda: compact(_call(
            F03, gpt.analyze_market, item=item, market_data=market_ev, analysis_type="need_and_trend")))
        competitors = steps.run(F04, lambda: compact(_call(
            F04, gpt.analyze_competitors, item=item, market_data=market, competitor_data=competitor_ev)))
        marketing = steps.run(F10, lambda: compact(_call(
            F10, gpt.create_marketing_strategy, item=item, market=market, target_customer=target, stage="초기시장")))
        bm = steps.run(F11, lambda: compact(_call(
            F11, gpt.create_business_model, item=item, market=market, customer=target, strategy=marketing)))
        growth = steps.run(F12, lambda: compact(_call(
            F12, gpt.create_growth_strategy, market=market, competitors=competitors, bm=bm, investment={},
            social_value={})))
    data = {"market_analysis": market, "competitor_analysis": competitors, "marketing_strategy": marketing,
            "business_model": bm, "growth_strategy": growth}
    return TS2Out(market_analysis=market_analysis(market, competitors, growth),
                  numeric_tokens=numeric_tokens(market, competitors, marketing, bm, growth),
                  check=CheckResult(passed=True, failures=[]), market_strategy_data=data)
