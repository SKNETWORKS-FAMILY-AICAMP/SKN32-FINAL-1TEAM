"""표 대체 안내(displayReason) — T-W3 연결 코드가 정해 tableOutputs에 저장하고, 화면 조회(flow/reads.py)는 옮기기만 한다.

- 분류(담당자 fallbackReason 낱말 → 다섯 가지 안내 문구)는 agents/partner_sw/writing.py 한 곳이다. flow/에는 문장 판별이 없다.
- 표 결과에서 남길 칸(TABLE_KEYS · TABLE_DEFAULTS)에 displayReason이 있어 pick이 버리지 않는다.
- 칸이 없는 옛 값(스텁 T-W3 포함)은 다섯째 일반 문구로 보인다.
T-W3는 LLM을 부르지 않는 규칙 코드라 tools 없이 직접 부른다(네트워크 없음).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sbrain.agents.form_defaults import select_form
from sbrain.agents.partner_sw import outputs, writing
from sbrain.agents.partner_sw.agent_strategy.functions import python_functions as partner_py
from sbrain.agents.stubs import make_announcement
from sbrain.contracts import tasks as c
from sbrain.flow import reads
from sbrain.models import BudgetItem, CompanyInfo, PlanDoc, ScheduleItem

LIMIT = "입력한 정부지원사업비가 지원 상한을 초과해 표 대신 설명으로 표시합니다. 사업비를 확인해 주세요."
SCHEDULE_MISMATCH = "작성된 표 일정이 원본 협약 일정과 맞지 않아 설명으로 표시합니다. 일정 입력과 표 내용을 확인해 주세요."
PERIOD = "입력한 협약 일정이 허용 기간을 벗어나 표 대신 설명으로 표시합니다. 일정 입력을 확인해 주세요."
STRUCTURE = "표의 필수 항목을 검증 기준에 맞추지 못해 설명으로 표시합니다. 표 내용을 확인해 주세요."
GENERAL = "표를 검증 기준에 맞춰 완성하지 못해 설명으로 표시합니다. 입력 내용과 생성 결과를 확인해 주세요."


# ── 분류 (T-W3 연결 코드) ─────────────────────────────────
def test_display_reason_five_cases_keep_their_words():
    cases = {
        "정부지원사업비 1억이 지원규모 상한 초과": LIMIT,
        "정부지원사업비가 공고 금액을 초과함": LIMIT,
        "개발계획 표 종료월이 다름": SCHEDULE_MISMATCH,
        "원본 협약 일정과 다른 행": SCHEDULE_MISMATCH,
        "협약기간 일정 10개월이 최대 8개월 조건을 초과함": PERIOD,
        "협약기간 일정 종료월이 개발 종료월 이후": PERIOD,
        "필수 표 컬럼 누락": STRUCTURE,
        "행 길이와 열 수 불일치 · 행 누락": STRUCTURE,
        "표 구조 문제": STRUCTURE,
        "아무 글": GENERAL,
        "": GENERAL,
    }
    for reason, expected in cases.items():
        assert writing.table_display_reason(reason) == expected, reason
    assert writing.table_display_reason("협약기간 일정만") == GENERAL           # '초과' · '이후'가 없으면 일반 문구
    assert writing.TABLE_DISPLAY_DEFAULT == reads.TABLE_FALLBACK_DISPLAY_DEFAULT == GENERAL


def test_table_keys_keep_display_reason():
    assert "displayReason" in outputs.TABLE_KEYS
    assert outputs.TABLE_DEFAULTS["displayReason"] == ""
    note = c.TW3Out.model_json_schema(by_alias=True)["properties"]["tableOutputs"].get("x-note", "")
    assert "fallbackReason · displayReason" in note                              # 계약 설명도 같은 칸


def _company() -> CompanyInfo:
    return CompanyInfo(
        representative_name="대표", representative_career=["운영 5년"], founded_at=date(2025, 3, 2),
        applicant_type="법인", revenue_unit_price=35000, team_careers=[], region="서울특별시", industry_code="J62",
        birth_date=date(1980, 1, 1), gender="남", hiring_plan="", facilities="", partners="",
        budget_items=[BudgetItem(category="재료비", execution_plan="서버 임차", total_amount=12_000_000,
                                 government_amount=9_000_000, self_cash_amount=2_000_000,
                                 self_in_kind_amount=1_000_000)],
        schedule_items=[ScheduleItem(scope="agreement", category="개발", content="화면 개발", period="2026.03~2026.06",
                                     detail="웹")])


def _run_tw3(**extra) -> c.TW3Out:
    form = select_form("법인").form_spec
    plan = PlanDoc(sections=[], feature_list=[], charts=[], tables=[], protected_tokens=[])
    inp = c.TW3In(plan_doc=plan, company_info=_company(), selected_announcement=make_announcement("A01", date(2026, 9, 26)),
                  instruction="", strategy_data={}, form_spec=form, **extra)
    return writing.run_tw3(inp, None)   # T-W3는 tools를 쓰지 않는다


def test_tw3_stores_display_reason_when_table_falls_back(monkeypatch):
    original = partner_py.generate_table

    def broken(columns, rows, rules):
        out = original(columns, rows, rules)
        if rules.get("sectionId") == "3.5.2":
            out["tables"][0]["columns"] = columns[:1]
        return out
    monkeypatch.setattr(partner_py, "generate_table", broken)
    out = _run_tw3()
    fb = out.table_outputs["3.5.2"]
    assert fb["tableFallbackUsed"] is True and fb["fallbackReason"] == "필수 표 컬럼 누락"
    assert fb["displayReason"] == STRUCTURE
    kept = [code for code, o in out.table_outputs.items() if not o["tableFallbackUsed"]]
    assert kept and all(out.table_outputs[code]["displayReason"] == "" for code in kept)
    # 화면 조회는 저장된 칸을 옮기기만 한다
    [view] = reads._table_fallbacks(out.table_outputs)
    assert (view.section_code, view.reason, view.display_reason) == ("3.5.2", "필수 표 컬럼 누락", STRUCTURE)


# ── 화면 조회 (flow/reads.py) ─────────────────────────────
def test_reads_copies_stored_display_reason_and_old_values_get_general_text():
    original = "협약기간 일정 10개월이 최대 8개월 조건을 초과함"
    stored = reads._table_fallbacks({"2.6.2": {"tableFallbackUsed": True, "fallbackReason": original,
                                               "displayReason": PERIOD}})[0].dump()
    assert stored == {"sectionCode": "2.6.2", "reason": original, "displayReason": PERIOD}
    # 칸이 없는 옛 값 — 낱말로 고르지 않고 일반 문구
    old = reads._table_fallbacks({"2.6.2": {"tableFallbackUsed": True, "fallbackReason": original}})[0]
    assert old.display_reason == GENERAL
    empty = reads._table_fallbacks({"2.5.3": {"tableFallbackUsed": True, "fallbackReason": "필수 표 컬럼 누락",
                                              "displayReason": ""}})[0]
    assert empty.display_reason == GENERAL


def test_flow_has_no_partner_sentence_classification():
    flow_dir = Path(reads.__file__).parent
    words = ("지원규모 상한", "필수 표", "개발계획 표 종료월", "원본 협약 일정", "협약기간 일정")
    for f in flow_dir.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not [w for w in words if w in text], f.name
    assert not hasattr(reads, "_table_fallback_display_reason")
