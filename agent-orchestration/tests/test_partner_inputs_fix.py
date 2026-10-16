"""담당자 입력 바로잡기 — 창업아이템명 · 팀 구성현황(일반현황), 사용자 목표 고객, 흐름도 제목.

- 사전 정보 새 칸(targetCustomer · startupItemName · teamMemberRows)이 웹 DB 행에서 만들어져 회사 정보까지 온다(실구현 · 스텁 T-C1).
- 사용자 목표 고객이 있으면 T-C1 출력 itemSpec.targetCustomer가 그 값이고, T-C1 LLM 요청에는 싣지 않는다.
- 담당자 입력: 원본 사실 · F02 결과 · F10 · F11 · requirementAnalysis의 목표 고객, 일반현황 항목(2.1.1 · 3.1.1) 근거의 두 칸.
- 네트워크에 나가지 않는다(가짜 LLM · KIET 스위치 꺼짐).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import partner_sw_parts as sw   # 담당자 연결 테스트와 같이 쓰는 회사 정보 · 공고 · 비밀 값 부품
from conftest import make_app, pre_input, project_record
from fakes import ITEM as FAKE_ITEM, item_json
from partner_fake import PartnerProvider, partner_tools, payload

from sbrain.agents.form_defaults import select_form
from sbrain.agents.partner_sw import inputs as ins
from sbrain.agents.partner_sw import verify as verify_module
from sbrain.agents.partner_sw.diagram_svg import render as render_diagram
from sbrain.agents.partner_sw.strategy import run_ts1, run_ts2
from sbrain.agents.partner_sw.verify import run_tv1
from sbrain.agents.partner_sw.writing import run_tw1, run_tw2, run_tw3
from sbrain.agents.supervisor import bind_supervisor, tc1
from sbrain.contracts import tasks as c
from sbrain.intake import MemoryProjectInputSource, to_pre_input
from sbrain.intake.mapping import startup_item_name
from sbrain.models import CompanyInfo, ItemSpec, PreInput, TeamMemberEntry
from sbrain.orchestrator import settings
from sbrain.orchestrator.errors import ToolCallExhausted

USER_TARGET = "동네 소규모 헬스장 운영자(사용자입력)"
NAMES = ("이하늘", "박지우", "최가람", "정다온")


# ── 1. 사전 정보 ──────────────────────────────
@pytest.mark.parametrize("description, expected", [
    ("동네 헬스장 회원 관리 서비스", "동네 헬스장 회원 관리 서비스"),
    ("첫 줄 이름\n둘째 줄 설명\n셋째 줄", "첫 줄 이름"),                       # 여러 줄 — 첫 줄만
    ("윈도 줄바꿈\r\n둘째 줄", "윈도 줄바꿈"),
    ("가" * 61, "가" * 60),                                                  # 61자 이상 — 60자까지
    ("나" * 60, "나" * 60),
    ("   앞뒤 공백 이름   \n둘째", "앞뒤 공백 이름"),                         # 공백 정리
    ("\n\n  빈 줄 뒤 첫 줄  \n둘째", "빈 줄 뒤 첫 줄"),                      # 빈 줄로 시작 — 전체 공백 제거 뒤 첫 줄(잠정)
    ("", None), ("   \n  ", None), (None, None),                              # 빈 설명
])
def test_startup_item_name_first_line_60(description, expected):
    assert startup_item_name(description) == expected


def test_pre_input_gets_startup_item_name_and_team_rows_without_names():
    rec = project_record(
        project={"description": "  헬스온 — 회원 관리\n동네 헬스장 회원 관리 서비스입니다."},
        team_members=[dict(name="이하늘", role="  개발 ", experience="웹 개발 3년"),
                      dict(name="박지우", role=None, experience=None),            # 둘 다 비어도 한 행
                      dict(name="최가람", role="디자인", experience=" "),
                      dict(name="정다온", role=None, experience="마케팅 5년")])
    f = to_pre_input(rec)
    assert f.startup_item_name == "헬스온 — 회원 관리"
    assert f.team_member_rows == [TeamMemberEntry(role="개발", experience="웹 개발 3년"),
                                  TeamMemberEntry(role=None, experience=None),
                                  TeamMemberEntry(role="디자인", experience=None),
                                  TeamMemberEntry(role=None, experience="마케팅 5년")]   # 저장 순서
    dumped = json.dumps(f.dump()["teamMemberRows"], ensure_ascii=False)
    assert not any(n in dumped for n in NAMES)                                         # 이름 없음
    assert f.dump()["startupItemName"] == "헬스온 — 회원 관리"
    assert f.target_customer is None                                                   # 컬럼 없음 → None


def test_no_team_members_is_empty_list_not_none():
    f = to_pre_input(project_record(team_members=[]))
    assert f.team_member_rows == []


def test_target_customer_from_plan_row_is_trimmed():
    assert to_pre_input(project_record(plan={"target_customer": "  " + USER_TARGET + " "})).target_customer == USER_TARGET
    assert to_pre_input(project_record(plan={"target_customer": " "})).target_customer is None


def test_old_json_without_new_fields_reads_none():
    """옛 실행 건 · 옛 사본 — 칸이 없으면 목표 고객 · 창업아이템명 None, 팀원 표 행은 None(모름 — 빈 목록과 다름)."""
    old = pre_input().dump()
    for key in ("targetCustomer", "startupItemName", "teamMemberRows"):
        old.pop(key, None)
    f = PreInput.model_validate(old)
    assert (f.target_customer, f.startup_item_name, f.team_member_rows) == (None, None, None)
    company = CompanyInfo.model_validate({k: v for k, v in tc1.company_info_from(f).dump().items()
                                          if k not in ("targetCustomer", "startupItemName", "teamMemberRows")})
    assert (company.target_customer, company.startup_item_name, company.team_member_rows) == (None, None, None)


def test_company_info_copies_new_fields_without_sharing_objects():
    form = to_pre_input(project_record(plan={"target_customer": USER_TARGET}))
    company = tc1.company_info_from(form)
    assert (company.target_customer, company.startup_item_name, company.team_member_rows) == (
        form.target_customer, form.startup_item_name, form.team_member_rows)
    assert company.team_member_rows is not form.team_member_rows
    assert company.team_member_rows[0] is not form.team_member_rows[0]
    assert tc1.company_info_from(pre_input()).team_member_rows is None                # None은 None 그대로


# ── 2. 목표 고객 덮기 ─────────────────────────
def real_app(clock, **kw):
    app = make_app(clock, **kw)
    bind_supervisor(app.registry)
    return app


def artifact(app, run_id, key):
    return app.engine.open_context(app.store.load_run(run_id)).get(key)


def tc1_llm_text(app) -> str:
    return json.dumps([r.messages for r in app.llm.requests if r.metadata["task_id"] == "T-C1"], ensure_ascii=False)


STARTUP_NAME = "헬스온고유명칭 회원 관리"
TEAM_ROLE, TEAM_EXPERIENCE = "결제연동리드(고유역할)", "결제 모듈 구축 8년(고유경력)"


def records_text(app, run_id) -> str:
    """실행 기록 · 사건 · 호출 기록 · 관리자 조회 (test_tc4의 기록 확인과 같은 모음)."""
    return json.dumps([
        [x.dump() for x in app.store.executions(run_id)], [x.dump() for x in app.store.events(run_id)],
        [x.dump() for x in app.store.call_logs(run_id)], [x.dump() for x in app.orchestrator.admin_runs()],
        [x.dump() for x in app.orchestrator.admin_executions(limit=None)],
    ], ensure_ascii=False, default=str)


@pytest.mark.parametrize("real", [True, False], ids=["실구현", "스텁"])
def test_user_target_customer_overrides_item_spec_and_reaches_company_info(clock, real):
    source = MemoryProjectInputSource([project_record(
        plan={"target_customer": USER_TARGET},
        project={"description": f"{STARTUP_NAME}\n동네 헬스장 회원 관리 서비스"},
        team_members=[dict(name="이하늘", role=TEAM_ROLE, experience=TEAM_EXPERIENCE),
                      dict(name="박지우", role=None, experience=None)])])
    app = real_app(clock, project_inputs=source) if real else make_app(clock, project_inputs=source)
    if real:
        app.llm.respond("T-C1", lambda req: item_json())
    res = app.orchestrator.start_run_for_project("7", 101)
    assert res.ok, res
    item = artifact(app, res.run_id, "itemSpec")
    assert item.target_customer == USER_TARGET
    company = artifact(app, res.run_id, "companyInfo")
    assert company.target_customer == USER_TARGET
    assert company.startup_item_name == STARTUP_NAME
    assert company.team_member_rows == [TeamMemberEntry(role=TEAM_ROLE, experience=TEAM_EXPERIENCE),
                                        TeamMemberEntry(role=None, experience=None)]
    assert USER_TARGET not in tc1_llm_text(app)                                          # T-C1 LLM 요청에 없음
    if real:
        assert item.item_name == FAKE_ITEM["item_name"]                                  # 아이템 이름은 그대로
    # 사전 정보 새 칸의 값은 실행 기록 · 사건 · 호출 기록 · 관리자 조회에 없다
    dumped = records_text(app, res.run_id)
    for value in (USER_TARGET, STARTUP_NAME, TEAM_ROLE, TEAM_EXPERIENCE):
        assert value not in dumped, value


@pytest.mark.parametrize("real", [True, False], ids=["실구현", "스텁"])
def test_without_user_target_customer_item_spec_keeps_llm_value(clock, real):
    source = MemoryProjectInputSource([project_record()])
    app = real_app(clock, project_inputs=source) if real else make_app(clock, project_inputs=source)
    if real:
        app.llm.respond("T-C1", lambda req: item_json())
    res = app.orchestrator.start_run_for_project("7", 101)
    assert res.ok, res
    item = artifact(app, res.run_id, "itemSpec")
    assert item.target_customer == (FAKE_ITEM["target_customer"] if real else "소상공인")
    assert artifact(app, res.run_id, "companyInfo").target_customer is None


def test_override_function_is_shared_and_ignores_blank():
    item = ItemSpec(item_name="a", one_line_summary="b", target_customer="LLM 값", core_features=["x"],
                    category="웹개발", keywords=["k"])
    assert tc1.with_user_target_customer(item, pre_input()) is item
    assert tc1.with_user_target_customer(item, pre_input(target_customer="  ")).target_customer == "LLM 값"
    assert tc1.with_user_target_customer(item, pre_input(target_customer=USER_TARGET)).target_customer == USER_TARGET
    from sbrain.agents import stubs
    assert stubs.with_user_target_customer is tc1.with_user_target_customer


# ── 3 · 4. 담당자 입력 ──────────────────────
def chain(applicant: str = "법인", *, target: str | None = None, name: str | None = "헬스온 회원 관리",
          rows: list[TeamMemberEntry] | None = None, monkeypatch=None) -> SimpleNamespace:
    """T-S1 → T-S2 → T-W1 → T-W2 → T-W3 → T-V1 (test_partner_sw_tasks.run_chain과 같은 순서). T-C1이 덮은 뒤처럼
    회사 정보에 목표 고객이 있으면 itemSpec.targetCustomer도 같은 값으로 둔다. F19 근거는 validate_section을 감싸 모은다."""
    p = PartnerProvider()
    co = sw.company(applicant).model_copy(update={"target_customer": target, "startup_item_name": name,
                                                  "team_member_rows": rows})
    item = sw.ITEM.model_copy(update={"target_customer": target}) if target else sw.ITEM
    form = PreInput(**{**{k: getattr(co, k) for k in PreInput.model_fields if hasattr(co, k)},
                       "idea_text": sw.IDEA, "development_period": "2026-03 ~ 2026-12"})
    ann = sw.announcement()
    bundle = select_form(applicant)
    f19_sources: dict[str, dict] = {}
    if monkeypatch is not None:
        original = verify_module.py.validate_section

        def capture(*, section_spec, content, source_data):
            f19_sources[str(section_spec["sectionId"])] = json.loads(json.dumps(source_data, ensure_ascii=False, default=str))
            return original(section_spec=section_spec, content=content, source_data=source_data)
        monkeypatch.setattr(verify_module.py, "validate_section", capture)

    def tools(task_id):
        return partner_tools(p, task_id)[0]

    s1 = run_ts1(c.TS1In(item_spec=item, selected_announcement=ann, instruction=sw.INSTRUCTION, company_info=co,
                         form_input=form), tools("T-S1"))
    s2 = run_ts2(c.TS2In(item_spec=item, requirement_analysis=s1.requirement_analysis, selected_announcement=ann,
                         instruction=sw.INSTRUCTION, strategy_data=s1.strategy_data), tools("T-S2"))
    w1 = run_tw1(c.TW1In(requirement_analysis=s1.requirement_analysis, market_analysis=s2.market_analysis,
                         selected_announcement=ann, company_info=co, form_spec=bundle.form_spec,
                         instruction=sw.INSTRUCTION, strategy_data=s1.strategy_data,
                         market_strategy_data=s2.market_strategy_data, feature_list=s1.feature_list), tools("T-W1"))
    w2 = run_tw2(c.TW2In(plan_doc=w1.plan_doc, market_analysis=s2.market_analysis, instruction=sw.INSTRUCTION,
                         strategy_data=s1.strategy_data, feature_list=s1.feature_list), tools("T-W2"))
    w3 = run_tw3(c.TW3In(plan_doc=w1.plan_doc, company_info=co, selected_announcement=ann, instruction=sw.INSTRUCTION,
                         strategy_data=s1.strategy_data, form_spec=bundle.form_spec), tools("T-W3"))
    by_code = {s.section_code: s for s in w3.table_sections}
    plan = w1.plan_doc.model_copy(update={"sections": [by_code.get(s.section_code, s) for s in w1.plan_doc.sections],
                                          "tables": w3.tables, "diagrams": w2.diagrams, "charts": []})
    v1 = run_tv1(c.TV1In(plan_doc=plan, evaluation_items=bundle.evaluation_items, rubric=bundle.rubric,
                         strategy_data=s1.strategy_data, market_strategy_data=s2.market_strategy_data,
                         feature_list=s1.feature_list, form_spec=bundle.form_spec,
                         section_outputs=w1.section_outputs, table_outputs=w3.table_outputs,
                         diagram_outputs=w2.diagram_outputs, company_info=co, selected_announcement=ann),
                 tools("T-V1"))
    return SimpleNamespace(p=p, co=co, s1=s1, s2=s2, w1=w1, v1=v1, f19=f19_sources, bundle=bundle)


def by_purpose(r, purpose: str) -> list[dict]:
    return [payload(q) for q in r.p.requests if q.metadata["purpose"] == purpose]


@pytest.mark.parametrize("applicant", ["법인", "예비창업자"])
def test_user_target_customer_reaches_partner_inputs(applicant):
    r = chain(applicant, target=USER_TARGET)
    f02 = by_purpose(r, "F02")
    assert f02 and f02[0]["item_input"]["target_customer"] == USER_TARGET
    assert f02[0]["item_input"][ins.TARGET_HINT_KEY] == USER_TARGET                     # 참고값 = itemSpec(덮인 값)
    assert r.s1.strategy_data["original_facts"]["item"]["target_customer"] == USER_TARGET
    assert r.s1.strategy_data["item_spec"]["targetCustomer"] == USER_TARGET               # F02 결과(가짜 응답 '헬스장')를 덮음
    assert r.s1.requirement_analysis.target_customer == USER_TARGET
    assert by_purpose(r, "F10")[0]["target_customer"] == USER_TARGET
    assert by_purpose(r, "F11")[0]["customer"] == USER_TARGET
    # F02 다음 함수들(F06 · F09 · F13)이 받은 item_spec도 사용자 값
    assert by_purpose(r, "F06")[0]["item_spec"]["targetCustomer"] == USER_TARGET
    assert by_purpose(r, "F09")[0]["product"]["targetCustomer"] == USER_TARGET
    assert by_purpose(r, "F13")[0]["item"]["targetCustomer"] == USER_TARGET


@pytest.mark.parametrize("applicant", ["법인", "예비창업자"])
def test_without_user_target_customer_partner_inputs_are_unchanged(applicant):
    r = chain(applicant)
    f02 = by_purpose(r, "F02")[0]
    assert f02["item_input"]["target_customer"] == ins.CONFIRM == "확인 필요"
    assert f02["item_input"][ins.TARGET_HINT_KEY] == sw.ITEM.target_customer
    assert r.s1.strategy_data["original_facts"]["item"]["target_customer"] == "확인 필요"
    assert r.s1.strategy_data["item_spec"]["targetCustomer"] == "헬스장"                 # 담당자(가짜) 결과 그대로
    assert r.s1.requirement_analysis.target_customer == "헬스장"
    assert by_purpose(r, "F10")[0]["target_customer"] == "확인 필요"
    assert by_purpose(r, "F11")[0]["customer"] == "확인 필요"


def test_ts1_resume_reapplies_user_target_to_received_f02():
    """재개해 이어 쓴 F02 결과(덮기 전 값으로 받아 둔 것)에도 같게 적용된다."""
    co = sw.company().model_copy(update={"target_customer": USER_TARGET})
    item = sw.ITEM.model_copy(update={"target_customer": USER_TARGET})
    form = PreInput(**{**{k: getattr(co, k) for k in PreInput.model_fields if hasattr(co, k)},
                       "idea_text": sw.IDEA, "development_period": "2026-03 ~ 2026-12"})
    p = PartnerProvider()
    p.scripts["F06"] = ["timeout"] * 3
    tin = c.TS1In(item_spec=item, selected_announcement=sw.announcement(), instruction=sw.INSTRUCTION,
                  company_info=co, form_input=form)
    with pytest.raises(ToolCallExhausted) as e:
        run_ts1(tin, partner_tools(p, "T-S1")[0])
    partial = dict(e.value.partial)
    received_f02 = json.loads(partial["F02"])
    received_f02["targetCustomer"] = "담당자 결과 값"                                       # 받아 둔 결과가 덮기 전 값이라도
    partial["F02"] = json.dumps(received_f02, ensure_ascii=False)
    p2 = PartnerProvider()
    out = run_ts1(tin.model_copy(update={"prior_results": partial}), partner_tools(p2, "T-S1")[0])
    assert "F02" not in p2.purposes()
    assert out.strategy_data["item_spec"]["targetCustomer"] == USER_TARGET
    assert out.requirement_analysis.target_customer == USER_TARGET
    assert payload(next(q for q in p2.requests if q.metadata["purpose"] == "F06"))["item_spec"]["targetCustomer"] == (
        USER_TARGET)


ROWS = [TeamMemberEntry(role="개발", experience="웹 개발 3년"), TeamMemberEntry(role=None, experience=None),
        TeamMemberEntry(role=None, experience="마케팅 5년")]
WEB_TABLE = [{"직위": "개발", "담당업무": "개발", "보유역량": "웹 개발 3년"},
             {"직위": "팀원", "담당업무": "-", "보유역량": "-"},
             {"직위": "팀원", "담당업무": "-", "보유역량": "마케팅 5년"}]


@pytest.mark.parametrize("applicant,general", [("법인", "3.1.1"), ("예비창업자", "2.1.1")])
def test_general_status_facts_only_on_general_section(applicant, general, monkeypatch):
    r = chain(applicant, rows=ROWS, monkeypatch=monkeypatch)
    f16 = {q["section_spec"]["sectionId"]: q["source_data"] for q in by_purpose(r, "F16")}
    assert general in f16
    facts = f16[general]["originalFacts"]
    assert facts[ins.FACT_STARTUP_ITEM_NAME] == "헬스온 회원 관리"
    assert facts[ins.FACT_TEAM_STATUS] == WEB_TABLE
    for code, source in f16.items():                                                     # 다른 항목에는 없다
        if code != general:
            assert ins.FACT_STARTUP_ITEM_NAME not in (source.get("originalFacts") or {}), code
            assert ins.FACT_TEAM_STATUS not in (source.get("originalFacts") or {}), code
    # 검증-1(F19 — validate_section 근거)도 같은 두 칸, 다른 항목에는 없다
    assert r.f19[general]["originalFacts"][ins.FACT_TEAM_STATUS] == WEB_TABLE
    assert r.f19[general]["originalFacts"][ins.FACT_STARTUP_ITEM_NAME] == "헬스온 회원 관리"
    assert all(ins.FACT_TEAM_STATUS not in (s.get("originalFacts") or {}) for code, s in r.f19.items() if code != general)
    f19_requests = {q["section_spec"]["sectionId"]: q for q in by_purpose(r, "F19")}
    assert general in f19_requests, sorted(f19_requests)                                 # 일반현황 F19 요청이 있고 두 칸을 담는다
    f19_facts = f19_requests[general]["source_data"]["originalFacts"]
    assert f19_facts[ins.FACT_TEAM_STATUS] == WEB_TABLE
    assert f19_facts[ins.FACT_STARTUP_ITEM_NAME] == "헬스온 회원 관리"
    # 이름(대표자 · 팀원)은 어느 요청에도 없다
    sent = json.dumps([q.messages for q in r.p.requests], ensure_ascii=False)
    assert sw.SECRETS["대표자 이름"] not in sent and sw.SECRETS["팀원 이름"] not in sent


@pytest.mark.parametrize("applicant,general", [("법인", "3.1.1"), ("예비창업자", "2.1.1")])
def test_general_status_empty_team_and_missing_values(applicant, general, monkeypatch):
    r = chain(applicant, rows=[], name=None, monkeypatch=monkeypatch)
    facts = {q["section_spec"]["sectionId"]: q["source_data"] for q in by_purpose(r, "F16")}[general]["originalFacts"]
    assert facts[ins.FACT_TEAM_STATUS] == ins.TEAM_NONE_TEXT == "팀원 없음(대표자 단독)"
    assert ins.FACT_STARTUP_ITEM_NAME not in facts                                        # 창업아이템명 없음 → 칸 없음
    r_old = chain(applicant, rows=None, name=None, monkeypatch=monkeypatch)                  # 옛 실행 건 — 팀원 표 행 None
    old_facts = {q["section_spec"]["sectionId"]: q["source_data"]
                 for q in by_purpose(r_old, "F16")}[general]["originalFacts"]
    assert ins.FACT_TEAM_STATUS not in old_facts and ins.FACT_STARTUP_ITEM_NAME not in old_facts
    assert ins.FACT_TEAM_STATUS not in r_old.f19[general]["originalFacts"]


def test_general_status_section_is_exact_code_per_document_type():
    assert ins.is_general_status(ins.PRE_STARTUP, "2.1.1") and ins.is_general_status(ins.EARLY_STARTUP, "3.1.1")
    assert not ins.is_general_status(ins.PRE_STARTUP, "3.1.1") and not ins.is_general_status(ins.EARLY_STARTUP, "2.1.1")
    assert not ins.is_general_status(ins.PRE_STARTUP, "1.1.1") and not ins.is_general_status("general", "1.1.1")
    assert not ins.is_general_status(ins.EARLY_STARTUP, "3.1.2")


def test_general_status_sections_are_the_partner_web_sections():
    """담당자 양식에서 '창업아이템명과 팀구성현황은 web에서 수령됨'이라고 적은 항목이 이 둘뿐이다."""
    from sbrain.agents.partner_sw import contract
    found = {(kind, s["sectionId"]) for kind in (ins.PRE_STARTUP, ins.EARLY_STARTUP)
             for s in contract.document_specs(kind) if "팀구성현황은 web에서 수령" in s.get("title", "")}
    assert found == {(ins.PRE_STARTUP, "2.1.1"), (ins.EARLY_STARTUP, "3.1.1")}


# ── 5. 흐름도 제목 ────────────────────────────
def test_diagram_titles():
    flow = render_diagram({"nodes": ["가", "나", "다"], "flowType": "USER_FLOW"}).decode("utf-8")
    arch = render_diagram({"nodes": ["가", "나", "다"], "flowType": "SERVICE_ARCHITECTURE"}).decode("utf-8")
    assert 'font-weight="700" fill="#172033">서비스 흐름도</text>' in flow and "USERFLOW" not in flow
    assert 'font-weight="700" fill="#172033">서비스 구조도</text>' in arch


# ── 6. 잠정 (확장 표시는 test_basedoc_v110_markers.py) ──
def test_provisional_keys_name_rules_and_texts():
    p = settings.PROVISIONAL
    assert "60자" in p["intake.startupItemName"] and "첫 줄" in p["intake.startupItemName"]
    for text in ("팀원 없음(대표자 단독)", "'팀원'", "'-'", "2.1.1", "3.1.1", "확인 필요"):
        assert text in p["partnerSw.generalStatusFacts"], text
