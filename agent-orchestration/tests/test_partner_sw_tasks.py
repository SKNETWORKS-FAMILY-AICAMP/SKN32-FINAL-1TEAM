"""전략 · 작성 · 검증-1 실구현 Task (T-S1 · T-S2 · T-W1 · T-W2 · T-W3 · T-V1) — 연결 코드 (spec 4.4 · 4.5 · 4.7 · 4.8 · 4.9 ·
4.13 · 4.14 · 4.17, 7절 2번).

Task 함수를 가짜 tools(목적 = F번호별 가짜 응답, 메모리 파일 저장소)로 직접 부른다. 네트워크 없음.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import TIMING
from partner_fake import BODY_MARK, PartnerProvider, partner_tools, payload

from sbrain.agents.form_defaults import select_form
from sbrain.agents.partner_sw import common, inputs, verify, writing
from sbrain.agents.partner_sw.agent_strategy.functions import python_functions as partner_py
from sbrain.agents.partner_sw.agent_strategy.runtime import research_context
from sbrain.agents.partner_sw.contract import SCORE_POLICY_VERSION
from sbrain.agents.partner_sw.diagram_svg import NOTICE
from sbrain.agents.partner_sw.strategy import FINAL_TS1, run_ts1, run_ts2
from sbrain.agents.partner_sw.verify import run_tv1
from sbrain.agents.partner_sw.writing import FINAL_TW3, run_tw1, run_tw2, run_tw3
from sbrain.agents.stubs import make_announcement
from sbrain.contracts import tasks as c
from sbrain.models import (
    BudgetItem, CompanyInfo, ItemSpec, PreInput, ReworkInput, ReworkOrder, RevenueItem, ScheduleItem,
)
from sbrain.orchestrator.errors import ToolCallExhausted

INSTRUCTION = "이번 Task 지시문"
IDEA = "AI 헬스장 회원 관리 시장 서비스"
ITEM = ItemSpec(item_name="헬스온", one_line_summary="헬스장 회원 관리 요약", target_customer="동네헬스장운영자힌트",
                core_features=["회원 등록·조회", "수업 예약"], category="웹개발", keywords=["헬스장"])

# LLM 요청에 실리면 안 되는 값 (spec 4.4 '보내지 않는다')
SECRETS = {
    "대표자 이름": "홍길비밀", "생년월일": "1977-07-07", "성별": "비밀성별값", "사업자등록번호": "777-66-55555",
    "기업명": "비밀상호주식회사", "지역": "비밀특별시 숨김구", "인증": "비밀인증서", "수익모델": "비밀구독상품",
    "희망 사업 규모": "비밀규모값", "자기부담금": "98765432", "직업": "비밀직장명", "지방우대 지역": "비밀우대지역",
    "업종": "비밀업종값", "대표자 유형": "비밀공동대표", "팀원 이름": "팀원이름비밀", "공고 제목": "비밀공고제목",
    "공고 ID": "SECRET-ANN-ID",
}

SCHEDULE = [ScheduleItem(scope="agreement", category="개발", content="화면 개발", period="2026.03~2026.06", detail="웹"),
            ScheduleItem(scope="agreement", category="시험", content="시범 운영", period="2026.07~2026.12", detail=""),
            ScheduleItem(scope="roadmap", category="확산", content="지역 확대", period="2027.01~2027.06", detail="영업")]
EARLY_BUDGET = [BudgetItem(category="재료비", execution_plan="서버 임차", total_amount=12_000_000,
                           government_amount=9_000_000, self_cash_amount=2_000_000, self_in_kind_amount=1_000_000),
                BudgetItem(category="외주용역비", execution_plan="디자인", total_amount=None, government_amount=3_000_000,
                           self_cash_amount=None, self_in_kind_amount=None)]
PRE_BUDGET = [BudgetItem(category="재료비", execution_plan="부품", total_amount=10_000_000, government_amount=7_000_000,
                         self_cash_amount=2_000_000, self_in_kind_amount=1_000_000, phase="1단계"),
              BudgetItem(category="외주용역비", execution_plan="앱", total_amount=20_000_000, government_amount=14_000_000,
                         self_cash_amount=4_000_000, self_in_kind_amount=2_000_000, phase="2단계")]


def company(applicant: str = "법인", *, budget=None, schedule=None) -> CompanyInfo:
    return CompanyInfo(
        representative_name=SECRETS["대표자 이름"], representative_career=["헬스장 운영 5년"],
        founded_at=None if applicant == "예비창업자" else date(2025, 3, 2), applicant_type=applicant,
        revenue_unit_price=35000, team_careers=[f"{SECRETS['팀원 이름']} 개발 3년"], region=SECRETS["지역"],
        industry_code="J62", birth_date=date(1977, 7, 7), gender=SECRETS["성별"],
        certifications=[SECRETS["인증"]], hiring_plan="개발자 1명", facilities="없음", partners="없음",
        desired_scale=SECRETS["희망 사업 규모"], business_reg_no=SECRETS["사업자등록번호"],
        self_fund_amount=int(SECRETS["자기부담금"]),
        revenue_items=[RevenueItem(service_name=SECRETS["수익모델"], unit_price=35000)],
        company_name=SECRETS["기업명"], biz_type=SECRETS["업종"], representative_type=SECRETS["대표자 유형"],
        output_summary="회원 관리 웹 서비스 1종", tech_field="정보통신", regional_priority_area=SECRETS["지방우대 지역"],
        occupation=SECRETS["직업"], representative_capability="헬스장 운영 노하우", self_in_kind_resources="사무실 1곳",
        budget_items=list(EARLY_BUDGET if budget is None and applicant != "예비창업자" else
                          PRE_BUDGET if budget is None else budget),
        schedule_items=list(SCHEDULE if schedule is None else schedule),
        team_role_careers=["개발: 웹 개발 3년", "디자인"])


def form_input(applicant: str = "법인") -> PreInput:
    co = company(applicant)
    fields = {k: getattr(co, k) for k in PreInput.model_fields if hasattr(co, k)}
    return PreInput(**{**fields, "idea_text": IDEA, "development_period": "2026-03 ~ 2026-12"})


def announcement(support: int | None = None):
    return make_announcement("A01", date(2026, 9, 26)).model_copy(update={
        "announcement_id": SECRETS["공고 ID"], "title": SECRETS["공고 제목"], "support_amount_max": support})


def run_chain(applicant: str = "법인", provider: PartnerProvider | None = None, *, support: int | None = None,
              budget=None, schedule=None, doc_layer_max: float | None = None) -> SimpleNamespace:
    """T-S1 → T-S2 → T-W1 → T-W2 → T-W3 → (합치기) → T-V1 을 차례로 부른다."""
    p = provider or PartnerProvider()
    co = company(applicant, budget=budget, schedule=schedule)
    ann = announcement(support)
    bundle = select_form(applicant)
    sinks, stores = {}, {}

    def tools(task_id):
        t, sinks[task_id], stores[task_id] = partner_tools(p, task_id)
        return t

    s1 = run_ts1(c.TS1In(item_spec=ITEM, selected_announcement=ann, instruction=INSTRUCTION, company_info=co,
                         form_input=form_input(applicant)), tools("T-S1"))
    s2 = run_ts2(c.TS2In(item_spec=ITEM, requirement_analysis=s1.requirement_analysis, selected_announcement=ann,
                         instruction=INSTRUCTION, strategy_data=s1.strategy_data), tools("T-S2"))
    w1_in = c.TW1In(requirement_analysis=s1.requirement_analysis, market_analysis=s2.market_analysis,
                    selected_announcement=ann, company_info=co, form_spec=bundle.form_spec, instruction=INSTRUCTION,
                    strategy_data=s1.strategy_data, market_strategy_data=s2.market_strategy_data,
                    feature_list=s1.feature_list)
    w1 = run_tw1(w1_in, tools("T-W1"))
    w2 = run_tw2(c.TW2In(plan_doc=w1.plan_doc, market_analysis=s2.market_analysis, instruction=INSTRUCTION,
                         strategy_data=s1.strategy_data, feature_list=s1.feature_list), tools("T-W2"))
    w3 = run_tw3(c.TW3In(plan_doc=w1.plan_doc, company_info=co, selected_announcement=ann, instruction=INSTRUCTION,
                         strategy_data=s1.strategy_data, form_spec=bundle.form_spec), tools("T-W3"))
    by_code = {s.section_code: s for s in w3.table_sections}
    plan = w1.plan_doc.model_copy(update={"sections": [by_code.get(s.section_code, s) for s in w1.plan_doc.sections],
                                          "tables": w3.tables, "diagrams": w2.diagrams, "charts": []})
    v1_in = c.TV1In(plan_doc=plan, evaluation_items=bundle.evaluation_items, rubric=bundle.rubric,
                    strategy_data=s1.strategy_data, market_strategy_data=s2.market_strategy_data,
                    feature_list=s1.feature_list, form_spec=bundle.form_spec, section_outputs=w1.section_outputs,
                    table_outputs=w3.table_outputs, diagram_outputs=w2.diagram_outputs, company_info=co,
                    selected_announcement=ann, doc_layer_max=doc_layer_max)
    v1 = run_tv1(v1_in, tools("T-V1"))
    return SimpleNamespace(p=p, co=co, ann=ann, bundle=bundle, s1=s1, s2=s2, w1=w1, w1_in=w1_in, w2=w2, w3=w3,
                           plan=plan, v1=v1, v1_in=v1_in, sinks=sinks, stores=stores)


def llm_logs(sink):
    return [log for log in sink.drain() if log.call_type == "llm"]


def requests_of(p: PartnerProvider, task_id: str):
    return [r for r in p.requests if r.metadata["task_id"] == task_id]


# ── 연결 (예비창업 · 초기창업) ─────────────────────────────
@pytest.mark.parametrize("applicant,kind,count", [("법인", "early_startup", 24), ("예비창업자", "pre_startup", 25)])
def test_chain_calls_partner_functions_and_fills_contracts(applicant, kind, count):
    r = run_chain(applicant)
    p = r.p
    assert r.s1.strategy_data["document_type"] == kind
    assert set(r.s1.strategy_data) >= {"web_data", "item_spec", "team_capability", "development_goal",
                                       "development_method", "architecture", "development_plan", "production_plan",
                                       "resource_plan", "budget", "schedule", "feasibility_plan", "research",
                                       "original_facts", "strategy_limits", "document_type"}
    assert set(r.s2.market_strategy_data) == {"market_analysis", "competitor_analysis", "marketing_strategy",
                                              "business_model", "growth_strategy"}
    # Task별 담당자 함수 (spec 2절 Task ↔ 함수)
    assert {q.metadata["purpose"] for q in requests_of(p, "T-S1")} == {
        "F01", "F02", "F05", "F06", "F07", "F08", "F09", "F13", "F14", "F15"}
    assert [q.metadata["purpose"] for q in requests_of(p, "T-S2")] == ["F03", "F04", "F10", "F11", "F12"]
    assert {q.metadata["purpose"] for q in requests_of(p, "T-W1")} == {"F16"}
    assert sorted(q.metadata["purpose"] for q in requests_of(p, "T-W2")) == ["F18", "F18"]
    assert {q.metadata["purpose"] for q in requests_of(p, "T-V1")} == {"F19"}
    assert requests_of(p, "T-W3") == []                                            # T-W3는 LLM을 부르지 않는다
    assert all(q.json_mode is True and q.response_schema is None for q in p.requests)   # 담당자처럼 json_object
    assert all(f"<작업지시>\n{INSTRUCTION}\n</작업지시>" in q.messages[0]["content"]
               for q in p.requests if q.metadata["task_id"] != "T-V1")
    # 계약 출력
    assert r.s1.feature_list == ["회원 등록·조회", "수업 예약"] and r.s1.check.passed
    assert r.s1.requirement_analysis.problem_statement == ITEM.one_line_summary
    assert r.s2.market_analysis.competitors == ["경쟁 서비스"] and r.s2.market_analysis.market_size == []
    codes = r.bundle.form_spec.section_codes
    assert len(codes) == count
    assert [s.section_code for s in r.w1.plan_doc.sections] == codes                # 모든 항목 · 양식 순서
    assert [(s.content_type, s.tag) for s in r.w1.plan_doc.sections] == list(
        zip(r.bundle.form_spec.section_kinds, r.bundle.form_spec.section_tags))
    body = [s for s in r.w1.plan_doc.sections if s.content_type == "section"]
    assert all(s.sentences and s.sentences[0].sentence_id == f"s-{s.section_code}-1" for s in body)
    assert all(not s.sentences for s in r.w1.plan_doc.sections if s.content_type == "image")
    assert list(r.w1.section_outputs) == [s.section_code for s in body]
    assert all(set(v) == {"generatedText", "facts", "sourceRefs", "needsUserConfirmation", "issues"}
               for v in r.w1.section_outputs.values())
    tables = [code for code, k in zip(codes, r.bundle.form_spec.section_kinds) if k == "table"]
    assert [s.section_code for s in r.w3.table_sections] == tables == list(r.w3.table_outputs)
    assert [t.source_ref for t in r.w3.tables] == tables and r.w3.check.passed
    assert [x.section_code for x in r.v1.section_results] == codes
    assert r.v1.variance_flag is False and r.v1.score_policy_version == SCORE_POLICY_VERSION
    assert r.w2.charts == []


def test_purpose_models_are_logged_per_function():
    r = run_chain()
    logs = {log.purpose: log.model for log in llm_logs(r.sinks["T-S1"])}
    assert (logs["F02"], logs["F05"], logs["F06"], logs["F07"], logs["F14"]) == (
        "gpt-5.6-terra", "gpt-6-luna", "gpt-5.6-sol", "gpt-6.1-sol", "gpt-6-luna")
    s2 = {log.purpose: log.model for log in llm_logs(r.sinks["T-S2"])}
    assert (s2["F03"], s2["F04"], s2["F12"]) == ("gpt-6.1-sol", "gpt-5.6-terra", "gpt-6.1-sol")
    assert {log.model for log in llm_logs(r.sinks["T-W1"])} == {"gpt-5.6-sol"}
    assert {log.model for log in llm_logs(r.sinks["T-W2"])} == {"gpt-6-luna"}
    assert r.sinks["T-W3"].drain() == []                                              # 호출 기록도 없다


def test_retrieve_goes_through_tools_search():
    r = run_chain()
    searches = [log for log in r.sinks["T-S1"].drain() if log.call_type == "search"]
    assert len(searches) == 4 and {log.purpose for log in searches} == {"자료 검색"}     # F01 안 1회 + 3회
    assert all(log.final_outcome == "성공" and log.model is None for log in searches)
    with pytest.raises(RuntimeError, match="호출 수단 없음"):
        research_context.retrieve(IDEA)


# ── 보내는 칸 (spec 4.4) ───────────────────────────────────
@pytest.mark.parametrize("applicant", ["법인", "예비창업자"])
def test_llm_requests_carry_no_forbidden_values(applicant):
    r = run_chain(applicant, support=50_000_000)
    sent = [m["content"] for q in r.p.requests for m in q.messages]
    for name, value in SECRETS.items():
        assert not any(value in text for text in sent), name
    hinted = [q for q in r.p.requests if "targetCustomerHint" in q.messages[-1]["content"]]
    assert hinted and {q.metadata["purpose"] for q in hinted} == {"F02"}            # F02 요청에만
    assert not any(ITEM.target_customer in m["content"] for q in r.p.requests if q.metadata["purpose"] != "F02"
                   for m in q.messages)
    assert payload(hinted[0])["item_input"]["target_customer"] == "확인 필요"
    assert r.s1.strategy_data["original_facts"]["item"]["target_customer"] == "확인 필요"
    assert "targetCustomerHint" not in json.dumps(r.s1.strategy_data, ensure_ascii=False)
    f02 = payload(hinted[0])["item_input"]
    assert f02["description"] == IDEA and f02["tech_field"] == "정보통신"


# ── 울타리 (spec 4.5) ─────────────────────────────────────
def test_strategy_limits_deadline_support_and_feature_list():
    p = PartnerProvider({"F02": {"coreFeatures": [{"name": "기능A"}, "기능B"], "targetCustomer": "고객",
                                 "deliverables": [], "differentiation": ""}})
    r = run_chain("예비창업자", p)
    limits = r.s1.strategy_data["strategy_limits"]
    assert limits["deadline"] == "2026-12" and "supportLimit" not in limits and "deadlineScope" in limits
    assert limits["featureList"] == ITEM.core_features                               # T-S1 = itemSpec.coreFeatures
    assert r.s1.feature_list == ["기능A", "기능B"]
    f16 = payload(requests_of(r.p, "T-W1")[0])
    assert f16["source_data"]["strategy_limits"]["featureList"] == ["기능A", "기능B"]  # 뒤 Task = T-S1 featureList
    assert r.s1.strategy_data["original_facts"]["period"] == {"start": "2026-03", "end": "2026-12",
                                                                "durationMonths": 10}
    with_support = run_chain(support=50_000_000)
    assert with_support.s1.strategy_data["strategy_limits"]["supportLimit"] == 50_000_000
    assert "deadlineScope" not in with_support.s1.strategy_data["strategy_limits"]


# ── 표 원본 행 (spec 4.4) ─────────────────────────────────
def test_table_data_maps_rows_to_partner_keys():
    data, unassigned = inputs.table_data(company("법인"), "early_startup")
    assert set(data) == {"실현가능성_일정", "성장전략_일정", "사업비_집행계획"} and unassigned == []
    assert data["실현가능성_일정"][1] == {"구분": "시험", "추진내용": "시범 운영", "추진기간": "2026.07~2026.12",
                                       "세부내용": "확인 필요"}
    assert data["사업비_집행계획"][0] == {"비목": "재료비", "집행계획": "서버 임차", "총사업비": "12,000,000원",
                                       "정부지원사업비": "9,000,000원", "자기부담_현금": "2,000,000원",
                                       "자기부담_현물": "1,000,000원"}
    assert data["사업비_집행계획"][1]["총사업비"] == "확인 필요"                         # None 금액 → 확인 필요
    rows = inputs.budget_rows(company("법인"), "early_startup")
    assert [row["category"] for row in rows] == ["재료비"]               # 총사업비 None → 0 → F14 입력에서 뺀다
    mismatch = BudgetItem(category="기타", execution_plan="x", total_amount=9, government_amount=5,
                          self_cash_amount=None, self_in_kind_amount=2)
    [row] = inputs.budget_rows(company("법인", budget=[mismatch]), "early_startup")
    assert (row["total_amount"], row["self_cash_amount"]) == (7, 0)                # None → 0, 합으로 다시 냄
    pre, _ = inputs.table_data(company("예비창업자"), "pre_startup")
    assert set(pre) == {"implementationSchedule", "fullScaleSchedule", "budgetPlanStep1", "budgetPlanStep2"}
    assert pre["budgetPlanStep1"][0]["자기부담금"] == "3,000,000원" and len(pre["budgetPlanStep2"]) == 1


def test_pre_startup_unassigned_phase_rows():
    unassigned = BudgetItem(category="인건비", execution_plan="개발자", total_amount=5_000_000,
                            government_amount=5_000_000, self_cash_amount=0, self_in_kind_amount=0)
    r = run_chain("예비창업자", budget=[*PRE_BUDGET, unassigned])
    out = r.w3.table_outputs["2.5.3"]
    assert out["tables"][0]["rules"]["unassignedOriginalRows"][0]["비목"] == "인건비"
    assert "단계 미지정 원본 (단계별 합계에 미포함)" in out["generatedText"]
    assert all(row.get("비목") != "인건비" for t in r.w3.tables for row in [dict(zip(t.headers, x)) for x in t.rows])
    results = {x.section_code: x for x in r.v1.section_results}
    assert results["2.5.3"].input_missing and results["2.5.4"].input_missing             # 두 항목 입력 없음 (잠정)
    assert results["2.5.3"].status == "warning" and results["2.5.3"].issues == []
    assert results["2.5.3"].warnings[0] == "입력 확인 필요 — 사업비 집행계획"
    assert not results["2.5.2"].input_missing


def test_empty_inputs_are_input_missing_warnings():
    r = run_chain("법인", budget=[], schedule=[])
    results = {x.section_code: x for x in r.v1.section_results}
    for code, label in (("3.5.2", "추진 일정"), ("3.6.2", "추진 일정"), ("3.5.3", "사업비 집행계획")):
        assert results[code].input_missing and results[code].status == "warning", code
        assert results[code].warnings[0] == f"입력 확인 필요 — {label}" and results[code].issues == []
    assert not any(x.input_missing for x in r.v1.section_results if x.content_type != "table")


# ── 그림 (spec 4.6) ───────────────────────────────────────
def test_diagrams_are_svg_files_in_tools_files():
    r = run_chain()
    image_code = next(s.section_code for s in r.w1.plan_doc.sections if s.content_type == "image")
    assert [(d.diagram_id, d.flow_type, d.image_file.name) for d in r.w2.diagrams] == [
        (f"{image_code}-USER_FLOW", "USER_FLOW", "userflow.svg"),
        (f"{image_code}-SERVICE_ARCHITECTURE", "SERVICE_ARCHITECTURE", "architecture.svg")]
    store = r.stores["T-W2"]
    for d in r.w2.diagrams:
        svg = store.read(d.image_file.key).decode("utf-8")
        assert d.image_file.media_type == "image/svg+xml" and d.image_file.run_id == "run-1"
        assert svg.startswith("<svg") and NOTICE in svg and "href" not in svg and "<image" not in svg
        assert all(node in svg for node in d.nodes)
    out = r.w2.diagram_outputs[image_code]
    assert out["imageTypes"] == ["USER_FLOW", "SERVICE_ARCHITECTURE"]
    assert [x["flowType"] for x in out["imageSpecs"]] == ["USER_FLOW", "SERVICE_ARCHITECTURE"]
    assert not {"model", "responseId", "usage", "status", "functionId"} & set(out)


# ── 점수 (spec 4.9) ───────────────────────────────────────
@pytest.mark.parametrize("d", [None, 60.0])
def test_score_items_sum_to_total(d):
    r = run_chain(doc_layer_max=d)
    base = 70.0 if d is None else d
    items, results = r.v1.items, r.v1.section_results
    n = len(results)
    assert r.v1.doc_score.items == items and [i.item_code for i in items] == [x.section_code for x in results]
    assert r.v1.doc_score.total == float(sum(Decimal(str(i.score)) for i in items))    # 항목 합 = 총점
    mean = sum(x.score for x in results) / n
    assert abs(r.v1.doc_score.total - mean * base / 100) <= n * 0.005 + 1e-9
    assert abs(sum(i.max_score for i in items) - base) < 1e-9
    assert all(i.score == round(x.score * base / 100 / n, 2) for i, x in zip(items, results))
    assert all(i.comment for i in items) and r.v1.variance_flag is False


# ── 자체 검사 · 확정 동작 (spec 4.8) ─────────────────────────
def test_ts1_empty_core_features_inherits_item_spec_in_same_attempt():
    p = PartnerProvider({"F02": {"coreFeatures": [], "targetCustomer": "", "deliverables": [], "differentiation": ""}})
    tools, _, _ = partner_tools(p, "T-S1")
    out = run_ts1(c.TS1In(item_spec=ITEM, selected_announcement=announcement(), instruction=INSTRUCTION,
                          company_info=company(), form_input=form_input()), tools)
    assert out.feature_list == ITEM.core_features                                   # 빈 featureList를 내지 않는다
    assert (out.check.passed, out.check.final_action) == (False, FINAL_TS1)
    assert out.requirement_analysis.feature_list == ITEM.core_features
    assert out.requirement_analysis.target_customer == ITEM.target_customer


def test_tw3_table_check_failure_falls_back_in_same_attempt(monkeypatch):
    r = run_chain()
    original = partner_py.generate_table

    def broken(columns, rows, rules):
        out = original(columns, rows, rules)
        if rules.get("sectionId") == "3.5.2":
            out["tables"][0]["columns"] = columns[:1]
        return out
    monkeypatch.setattr(partner_py, "generate_table", broken)
    tools, sink, _ = partner_tools(r.p, "T-W3")
    out = run_tw3(c.TW3In(plan_doc=r.w1.plan_doc, company_info=r.co, selected_announcement=r.ann, instruction="",
                          strategy_data=r.s1.strategy_data, form_spec=r.bundle.form_spec), tools)
    assert (out.check.passed, out.check.final_action) == (False, FINAL_TW3)
    assert list(out.check.failed_items) == ["3.5.2"] and out.check.failed_items["3.5.2"] == ["필수 표 컬럼 누락"]
    assert "3.5.2" not in [t.source_ref for t in out.tables]
    fb = out.table_outputs["3.5.2"]
    assert fb["tableFallbackUsed"] is True and fb["tables"] == [] and fb["fallbackReason"] == "필수 표 컬럼 누락"
    sec = next(s for s in out.table_sections if s.section_code == "3.5.2")
    assert sec.sentences[0].text.startswith("표 구조 검증에 실패하여 본문 설명으로 대체함")
    assert sink.drain() == []


def test_tw3_fallback_items_from_verify1():
    r = run_chain()
    tools, _, _ = partner_tools(r.p, "T-W3")
    ri = ReworkInput(mode="재수행", previous_result_ref="tables@1", issues=["표 판정 문제"], is_final_attempt=True,
                     redo_source="검증-1", unit="표 1건", target_items={"3.5.2": ["행 누락", "기간 오류"]},
                     fallback_items=["3.5.2"])
    out = run_tw3(c.TW3In(plan_doc=r.w1.plan_doc, company_info=r.co, selected_announcement=r.ann, instruction="",
                          rework_input=ri, strategy_data=r.s1.strategy_data, form_spec=r.bundle.form_spec,
                          base_tables=r.w3.tables, base_table_sections=r.w3.table_sections,
                          base_table_outputs=r.w3.table_outputs), tools)
    assert out.check.passed                                                          # 판정은 흐름이 fail로 둔다
    assert out.table_outputs["3.5.2"]["fallbackReason"] == "행 누락 · 기간 오류"
    assert [t.source_ref for t in out.tables] == [t.source_ref for t in r.w3.tables if t.source_ref != "3.5.2"]
    assert out.table_outputs["3.6.2"] == r.w3.table_outputs["3.6.2"]                   # 나머지는 직전 그대로


# ── 목표 항목만 다시 (spec 4.7 · 4.9) ────────────────────────
def test_tw1_rebuilds_only_target_items_with_feedback():
    r = run_chain()
    p = PartnerProvider()
    tools, _, _ = partner_tools(p, "T-W1")
    order = ReworkOrder(task_id="T-W1", unit="묶음", targets=["문제인식"], reason="r", instruction_delta="보완 지시",
                        layer="document")
    ri = ReworkInput(mode="재작성", previous_result_ref="planDoc@3", issues=[], order=order, is_final_attempt=False,
                     target_items={"3.4.1": ["근거 부족"]})
    out = run_tw1(r.w1_in.model_copy(update={"rework_input": ri, "base_plan_doc": r.w1.plan_doc,
                                             "base_section_outputs": r.w1.section_outputs}), tools)
    [q] = p.requests
    rules = payload(q)["writing_rules"]
    assert q.metadata["item_key"] == "3.4.1"
    assert rules["validationFeedback"] == ["근거 부족"] and rules["retryInstruction"] == "보완 지시"
    assert rules["previousText"] == r.w1.section_outputs["3.4.1"]["generatedText"]
    assert {k: v for k, v in out.section_outputs.items() if k != "3.4.1"} == {
        k: v for k, v in r.w1.section_outputs.items() if k != "3.4.1"}
    assert [s.section_code for s in out.plan_doc.sections] == r.bundle.form_spec.section_codes
    redo = ri.model_copy(update={"mode": "재수행", "order": None, "redo_source": "검증-1", "unit": "섹션"})
    p2 = PartnerProvider()
    run_tw1(r.w1_in.model_copy(update={"rework_input": redo, "base_section_outputs": r.w1.section_outputs}),
            partner_tools(p2, "T-W1")[0])
    assert payload(p2.requests[0])["writing_rules"]["retryInstruction"] == ""         # 재수행은 빈 문자열


def test_tw2_keeps_base_when_image_not_targeted():
    r = run_chain()
    p = PartnerProvider()
    ri = ReworkInput(mode="재작성", previous_result_ref="planDoc@3", issues=[], is_final_attempt=False,
                     target_items={"3.4.1": []})
    out = run_tw2(c.TW2In(plan_doc=r.w1.plan_doc, market_analysis=r.s2.market_analysis, instruction="",
                          rework_input=ri, strategy_data=r.s1.strategy_data, feature_list=r.s1.feature_list,
                          base_diagrams=r.w2.diagrams, base_diagram_outputs=r.w2.diagram_outputs),
                  partner_tools(p, "T-W2")[0])
    assert p.requests == [] and out.diagrams == r.w2.diagrams and out.diagram_outputs == r.w2.diagram_outputs


def test_tv1_reverifies_only_targets_and_keeps_base_results():
    r = run_chain()
    p = PartnerProvider()
    ri = ReworkInput(mode="재수행", previous_result_ref="planDoc@3", issues=[], is_final_attempt=True,
                     redo_source="검증-1", unit="섹션", target_items={"3.4.1": ["문제"]})
    out = run_tv1(r.v1_in.model_copy(update={"rework_input": ri, "base_section_results": r.v1.section_results,
                                             "plan_doc_ref": "planDoc@7"}), partner_tools(p, "T-V1")[0])
    assert {q.metadata["item_key"] for q in p.requests} <= {"3.4.1"}
    by = {x.section_code: x for x in out.section_results}
    assert by["3.4.1"].verified_ref == "planDoc@7"
    assert all(x == y for x, y in zip(out.section_results, r.v1.section_results) if x.section_code != "3.4.1")
    assert all(x.verified_ref == "planDoc" for x in out.section_results if x.section_code != "3.4.1")
    assert out.doc_score.total == float(sum(Decimal(str(i.score)) for i in out.items))


# ── 재개 이어 쓰기 (spec 4.13) ──────────────────────────────
def test_ts1_resume_continues_after_received_functions():
    p = PartnerProvider()
    p.scripts["F06"] = ["timeout"] * 3
    tin = c.TS1In(item_spec=ITEM, selected_announcement=announcement(), instruction=INSTRUCTION,
                  company_info=company(), form_input=form_input())
    with pytest.raises(ToolCallExhausted) as e:
        run_ts1(tin, partner_tools(p, "T-S1")[0])
    assert e.value.error_kind == "일시" and set(e.value.partial) == {"F01", "F02", "F05"}
    assert all(isinstance(v, str) for v in e.value.partial.values())
    assert BODY_MARK not in str(e.value) and "partial" not in str(e.value)
    p2 = PartnerProvider()
    out = run_ts1(tin.model_copy(update={"prior_results": e.value.partial}), partner_tools(p2, "T-S1")[0])
    assert p2.purposes()[0] == "F06" and not {"F01", "F02", "F05"} & set(p2.purposes())
    assert out.feature_list == ["회원 등록·조회", "수업 예약"]


def test_ts1_non_transient_exhaustion_has_no_partial():
    p = PartnerProvider()
    p.scripts["F05"] = ["bad_request"] * 3
    with pytest.raises(ToolCallExhausted) as e:
        run_ts1(c.TS1In(item_spec=ITEM, selected_announcement=announcement(), instruction=INSTRUCTION,
                        company_info=company(), form_input=form_input()), partner_tools(p, "T-S1")[0])
    assert e.value.error_kind == "입력" and e.value.partial is None


def test_tw1_resume_calls_only_missing_items():
    r = run_chain()
    p = PartnerProvider()
    p.scripts[("F16", "3.4.1")] = ["timeout"] * 3
    with pytest.raises(ToolCallExhausted) as e:
        run_tw1(r.w1_in, partner_tools(p, "T-W1")[0])
    body = list(r.w1.section_outputs)
    assert set(e.value.partial) == set(body) - {"3.4.1"}
    p2 = PartnerProvider()
    out = run_tw1(r.w1_in.model_copy(update={"prior_results": e.value.partial}), partner_tools(p2, "T-W1")[0])
    assert [q.metadata["item_key"] for q in p2.requests] == ["3.4.1"]
    assert list(out.section_outputs) == body


def test_tv1_resume_calls_only_missing_items():
    r = run_chain()
    p = PartnerProvider()
    p.scripts[("F19", "3.4.1")] = ["timeout"] * 3
    with pytest.raises(ToolCallExhausted) as e:
        run_tv1(r.v1_in, partner_tools(p, "T-V1")[0])
    codes = r.bundle.form_spec.section_codes
    assert set(e.value.partial) == set(codes) - {"3.4.1"}
    p2 = PartnerProvider()
    out = run_tv1(r.v1_in.model_copy(update={"prior_results": e.value.partial}), partner_tools(p2, "T-V1")[0])
    assert {q.metadata["item_key"] for q in p2.requests} == {"3.4.1"}
    assert out.section_results == r.v1.section_results


def test_concurrent_failure_order_prefers_non_exhausted_error():
    r = run_chain()
    p = PartnerProvider()
    p.scripts[("F16", "3.1.1")] = ["timeout"] * 3
    p.scripts[("F16", "3.4.1")] = ["bad_request"] * 3
    with pytest.raises(ToolCallExhausted) as e:
        run_tw1(r.w1_in, partner_tools(p, "T-W1")[0])
    assert e.value.error_kind == "입력" and e.value.partial is None                    # ② 일시가 아닌 재시도 소진


# ── 동시 호출 (spec 4.14) ──────────────────────────────────
def test_concurrency_constants_are_used(monkeypatch):
    seen: list[tuple[str, int]] = []
    real = common.gather

    def spy(keys, one, workers, received, encode_value=common.encode, name="partner"):
        seen.append((name, workers))
        return real(keys, one, workers, received, encode_value, name)
    monkeypatch.setattr(writing, "gather", spy)
    monkeypatch.setattr(verify, "gather", spy)
    run_chain()
    assert dict(seen) == {"tw1": 4, "tw2": 2, "tv1": 4}
    assert (common.TW1_CONCURRENCY, common.TV1_CONCURRENCY, common.TW2_CONCURRENCY) == (4, 4, 2)


@TIMING
@pytest.mark.parametrize("workers", [4, 2])
def test_gather_runs_at_most_workers_at_once(workers):
    lock, active, peak = threading.Lock(), [0], [0]
    barrier = threading.Barrier(workers, timeout=10)

    def one(key):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        barrier.wait()                       # workers개가 함께 돈다
        time.sleep(0.01)
        with lock:
            active[0] -= 1
        return key
    keys = [f"k{i}" for i in range(workers * 2)]
    assert common.gather(keys, one, workers, {}) == {k: k for k in keys}            # 결과는 키 순서
    assert peak[0] == workers


# ── 기록 · 예외 메시지에 내용 없음 (spec 4.17) ─────────────────
def test_call_logs_and_errors_carry_no_content():
    r = run_chain()
    dumped = " ".join(log.model_dump_json() for sink in r.sinks.values() for log in sink.drain())
    for value in (BODY_MARK, IDEA, INSTRUCTION, "회원 등록·조회", *SECRETS.values()):
        assert value not in dumped
    p = PartnerProvider()
    p.scripts[("F16", "3.4.1")] = [f'{{"generatedText": "{BODY_MARK}"'] * 3          # 읽을 수 없는 응답
    tools, sink, _ = partner_tools(p, "T-W1")
    with pytest.raises(ToolCallExhausted) as e:
        run_tw1(r.w1_in, tools)
    assert BODY_MARK not in str(e.value) and BODY_MARK not in repr(e.value)
    assert all(BODY_MARK not in log.model_dump_json() for log in sink.drain())
