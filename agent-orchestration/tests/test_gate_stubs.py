"""스텁 공고 · 스텁 G-01 · 스텁 T-C2 (spec 4.6) — 공고 서버가 없을 때 · 테스트에서 쓰는 판정 규칙과 상황 조절."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from conftest import pre_input

from sbrain.agents.stubs import (
    StubScenario, bind_stubs, business_age_months, business_age_years, make_announcement, stub_gate,
)
from sbrain.contracts import tasks as c
from sbrain.flow.catalog import build_registry
from sbrain.models import BonusItem, CompanyInfo, EligibilityRule, ItemSpec
from sbrain.orchestrator.errors import ResourceNotFound, ToolCallExhausted
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

TODAY = date(2026, 9, 26)


def company(**over) -> CompanyInfo:
    form = pre_input(**over)
    return CompanyInfo(**{k: getattr(form, k) for k in CompanyInfo.model_fields if hasattr(form, k)})


def tools() -> Tools:
    cfg = ToolsConfig(agent="조율", provider="openai", model="m", temperature=None, timeout_sec=30,
                      retry_count=5, retry_interval_sec=0)
    return Tools(cfg, ToolsContext(run_id="r", execution_id="e", task_id="X", providers={}, sink=CallSink(),
                                   now=datetime.now, sleep=lambda s: None))


def stub(sc: StubScenario, task_id: str):
    registry = build_registry()
    bind_stubs(registry, sc)
    return registry.get(task_id).fn


def tc2(sc: StubScenario, offset: int = 0) -> c.TC2Out:
    item = ItemSpec(item_name="헬스장", one_line_summary="회원 관리", target_customer="소상공인",
                    core_features=["회원 관리"], category="웹개발", keywords=["헬스장"])
    return stub(sc, "T-C2")(c.TC2In(item_spec=item, company_info=company(), today=TODAY, top_k=10, offset=offset),
                            tools())


def g01(sc: StubScenario, aid: str = "A01", **form) -> c.G01Out:
    return stub(sc, "G-01")(c.G01In(company_info=company(**form), today=TODAY, announcement_id=aid), tools())


# ── 스텁 공고 · 판정 규칙 ────────────────────────────────
def test_stub_announcement_has_no_age_cap():
    ann = make_announcement("A01", TODAY)
    assert ann.eligibility.business_age_max_years is None and ann.apply_period_type == "기간 있음"
    assert ann.eligibility_parsed and ann.status == "모집중" and ann.apply_end is not None


@pytest.mark.parametrize(("founded", "months"), [
    (date(2025, 3, 2), 18), (date(2025, 3, 26), 18), (date(2025, 3, 27), 17), (date(2026, 9, 27), 0),
    (date(2027, 1, 1), 0), (date(2020, 9, 26), 72),
])
def test_business_age_months_counts_like_notice_team(founded, months):
    assert business_age_months(founded, TODAY) == months


@pytest.mark.parametrize(("months", "years"), [(0, 0.0), (3, 0.3), (15, 1.3), (27, 2.3), (18, 1.5), (13, 1.1)])
def test_business_age_years_rounds_half_up(months, years):
    assert business_age_years(months) == years                                  # 반올림(사사오입), 짝수 맞춤이 아니다


def test_stub_gate_rules():
    corp = company()                                                             # 법인 · 18개월
    base = make_announcement("A01", TODAY)

    def judge(rule: EligibilityRule | None = None, parsed: bool = True, who: CompanyInfo = corp):
        ann = base.model_copy(update={"eligibility": rule or base.eligibility, "eligibility_parsed": parsed})
        return stub_gate(who, ann, TODAY)
    gate, age = judge()
    assert (gate.passed, gate.failed_conditions, gate.unknown_conditions, age) == (True, [], [], 1.5)  # 상한 없음
    types = ["예비창업자", "개인사업자", "법인"]
    gate, _ = judge(EligibilityRule(applicant_types=types, business_age_max_years=1.5))
    assert (gate.passed, gate.failed_conditions) == (False, ["업력"])           # 18개월 ≥ 1.5년 × 12
    gate, _ = judge(EligibilityRule(applicant_types=types, business_age_max_years=2))
    assert gate.passed
    gate, _ = judge(EligibilityRule(applicant_types=["예비창업자"], business_age_max_years=1))
    assert (gate.passed, gate.failed_conditions) == (False, ["지원대상 유형", "업력"])
    gate, _ = judge(EligibilityRule(applicant_types=[], business_age_max_years=1), parsed=False)
    assert (gate.passed, gate.failed_conditions, gate.unknown_conditions) == (True, [], ["지원대상 유형", "업력"])
    gate, age = judge(EligibilityRule(applicant_types=[], business_age_max_years=1), parsed=False,
                      who=company(applicant_type="예비창업자", founded_at=None))
    assert (gate.passed, gate.unknown_conditions, age) == (True, ["지원대상 유형"], None)
    gate, age = judge(EligibilityRule(applicant_types=["예비창업자"], business_age_max_years=0.1),
                      who=company(applicant_type="예비창업자", founded_at=None))
    assert (gate.passed, age) == (True, None)                                   # 예비창업자는 업력을 보지 않는다
    gate, age = judge(who=company(founded_at=None))
    assert (gate.passed, gate.missing_inputs, gate.failed_conditions, gate.undecidable, age) == (
        False, ["foundedAt"], [], False, None)
    for g in (judge()[0], judge(parsed=False)[0]):
        assert g.undecidable is False                                           # 판정 불가는 쓰지 않는다


def test_stub_g01_builds_announcement_and_follows_knobs():
    sc = StubScenario(gate_fail_ids={"A02"}, unknown_ids={"A03"}, closed_ids={"A04"}, no_deadline_ids={"A04"},
                      no_amount_ids={"A04"}, not_found_ids={"A05"})
    out = g01(sc, "A01")
    assert out.selected_announcement.announcement_id == "A01" and out.gate_result.passed
    assert out.business_age_years == 1.5
    assert g01(sc, "A02").gate_result.failed_conditions == ["지원대상 유형"]
    assert g01(sc, "A03").gate_result.unknown_conditions == ["지원대상 유형", "업력"]
    ann = g01(sc, "A04").selected_announcement
    assert (ann.status, ann.apply_end, ann.apply_period_type, ann.support_amount_max, ann.support_amount_text) == (
        "마감", None, "상시·수시", None, None)
    with pytest.raises(ResourceNotFound) as e:
        g01(sc, "A05")
    assert "A05" not in str(e.value)                                            # 예외 메시지에 입력 값을 넣지 않는다
    sc.not_found_ids.discard("A05")                                             # 테스트 중에 다시 생긴다
    assert g01(sc, "A05").selected_announcement.announcement_id == "A05"
    assert g01(sc, "A01", applicant_type="예비창업자", founded_at=None).business_age_years is None
    with pytest.raises(ToolCallExhausted):
        g01(StubScenario(exhaust_in={"G-01"}))


# ── 스텁 T-C2 ──────────────────────────────────────────
def test_stub_cards_fill_extension_fields():
    out = tc2(StubScenario(null_bonus_ids={"A02"}, no_deadline_ids={"A03"}, no_version_ids={"A04"}))
    a1, a2, a3, a4 = out.candidates[:4]
    assert (a1.content_version, a1.content_changed, a1.apply_period_type) == ("A01-v1", False, "기간 있음")
    assert a1.bonus_score == 1.0 and a1.bonus_items == [BonusItem(name="가점 항목", points=1.0)]
    assert sum(i.points for i in a1.bonus_items) == a1.bonus_score
    assert (a2.bonus_score, a2.bonus_items) == (None, [])                        # 계산하지 못한 가산점
    assert (a3.apply_end, a3.apply_period_type) == (None, "상시·수시")
    assert a4.content_version is None
    assert [x.rank for x in out.candidates] == list(range(1, 11))


def test_stub_tc2_collection_status_returns_no_candidates():
    out = tc2(StubScenario(collection_status="지연"))
    assert (out.candidates, out.collection_status, out.filtered_count, out.fallback_used) == ([], "지연", 0, False)
    sc = StubScenario(more_collection_status="실패")                            # 추가 조회에서만 비정상
    assert len(tc2(sc).candidates) == 10
    more = tc2(sc, offset=10)
    assert (more.candidates, more.collection_status) == ([], "실패")


def test_stub_tc2_deadline_fallback_has_zero_fit():
    out = tc2(StubScenario(deadline_fallback=True))
    assert (out.fallback_used, out.fallback_mode) == (True, "마감임박순")
    assert {x.fit_score for x in out.candidates} == {0.0}


def test_stub_more_lookup_overlap_and_changes():
    sc = StubScenario(more_ids=["A03", "A04", "A05", "A06", "A07", "A11"],
                      more_changes={"A03": {"정보"}, "A04": {"버전"}, "A05": {"적합도"}, "A06": {"가산점"}})
    first = {x.announcement_id: x for x in tc2(sc).candidates}
    more = tc2(sc, offset=10)
    assert [x.announcement_id for x in more.candidates] == ["A03", "A04", "A05", "A06", "A07", "A11"]
    assert [x.rank for x in more.candidates] == list(range(11, 17))
    by_id = {x.announcement_id: x for x in more.candidates}

    def diff(aid: str) -> set[str]:
        a, b = first[aid].dump(), by_id[aid].dump()
        return {k for k in a if a[k] != b[k]} - {"rank", "displayType"}
    assert diff("A03") == {"title"}
    assert diff("A04") == {"contentVersion"}
    assert diff("A05") == {"fitScore", "matchReason"}
    assert diff("A06") == {"bonusScore", "bonusItems"}
    assert diff("A07") == set()                                                 # 내용 그대로 겹침
    assert all(not x.content_changed for x in more.candidates)                  # 표시는 흐름(Orchestrator)이 정한다


def test_stub_more_lookup_only_errors():
    for kind, exc in (("코드오류", RuntimeError), ("재시도소진", ToolCallExhausted)):
        sc = StubScenario(more_error=kind)
        assert len(tc2(sc).candidates) == 10                                    # 첫 조회는 정상
        with pytest.raises(exc):
            tc2(sc, offset=10)
    for sc in (StubScenario(raise_in={"T-C2"}), StubScenario(exhaust_in={"T-C2"})):
        for offset in (0, 10):
            with pytest.raises((RuntimeError, ToolCallExhausted)):
                tc2(sc, offset=offset)
