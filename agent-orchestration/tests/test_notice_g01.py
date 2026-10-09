"""실제 G-01 (공고 서버 연결, spec 4.3.2 · 4.4) — 가짜 전송으로 시험한다. 네트워크에 나가지 않는다.

- 상세 → Announcement(4.4), 설립일 없는 사업자는 판정을 부르지 않음, 판정 → GateResult · 업력(사사오입),
  공고 없음 → ResourceNotFound(흐름이 X-C2-GONE으로 처리).
- 모든 호출은 tools.search로 한다. ToolCallExhausted는 받지 않고 올려 보낸다.
"""
from __future__ import annotations

from datetime import date

import pytest
from notice_fake import FakeNoticeServer, detail, format_detail, gate, run_g01, tools_for

from sbrain.agents.form_defaults import default_evaluation_items, default_form_spec
from sbrain.agents.notice import business_age_years
from sbrain.models import EligibilityRule
from sbrain.orchestrator.errors import ResourceNotFound, ToolCallExhausted


# ── G-01: 상세 → Announcement (4.4) ─────────────────────
def test_detail_to_announcement():
    out = run_g01(FakeNoticeServer())
    ann = out.selected_announcement
    assert (ann.announcement_id, ann.title, ann.agency, ann.support_field) == (
        "kstartup:A01", "창업지원 kstartup:A01", "중소벤처기업부", "사업화")
    assert (ann.apply_start, ann.apply_end, ann.status, ann.apply_period_type) == (
        date(2026, 9, 1), date(2026, 10, 31), "모집중", "기간 있음")
    assert ann.eligibility == EligibilityRule(applicant_types=["예비창업자", "개인사업자", "법인"], business_age_max_years=7.0)
    assert ann.eligibility_parsed is True
    assert (ann.support_amount_max, ann.support_amount_text, ann.bonus_info) == (100_000_000, "최대 1억원", "청년 창업자 가점 1점")
    assert ann.form_spec == default_form_spec() and ann.evaluation_items == default_evaluation_items()
    assert ann.summary_embedding == []


def g01_with_detail(**over):
    server = FakeNoticeServer()
    server.details["kstartup:A01"] = detail("kstartup:A01", **over)
    return run_g01(server).selected_announcement


@pytest.mark.parametrize("orgs, agency", [
    (("주관", "감독", "수행"), "주관"), (("", "감독", "수행"), "감독"), ((None, "", "수행"), "수행"),
    ((None, None, None), "-"), (("", " ", ""), "-")])
def test_detail_agency_fallback(orgs, agency):
    o, s, e = orgs
    assert g01_with_detail(organizer=o, supervising_org=s, executing_org=e).agency == agency


@pytest.mark.parametrize("value, status", [("open", "모집중"), ("closed", "마감"), ("unknown", "모집중"),
                                           (None, "모집중"), ("upcoming", "모집중")])
def test_detail_status(value, status):
    assert g01_with_detail(recruitment_status=value).status == status


def test_detail_empty_values():
    ann = g01_with_detail(category=None, apply_start=None, apply_end=None, support_amount_max_won=None,
                          support_amount_text=None, bonus_info=None, apply_period_type="budget_exhaustion",
                          eligibility={"applicant_types": [], "business_age_max_months": None, "parsed": False})
    assert (ann.support_field, ann.apply_start, ann.apply_end, ann.support_amount_max, ann.support_amount_text) == (
        "", None, None, None, None)
    assert (ann.bonus_info, ann.apply_period_type, ann.eligibility_parsed) == (None, "예산 소진 시까지", False)
    assert ann.eligibility == EligibilityRule(applicant_types=[], business_age_max_years=None)
    assert g01_with_detail(eligibility={"applicant_types": ["법인"], "business_age_max_months": 42,
                                        "parsed": True}).eligibility.business_age_max_years == 3.5


DETAIL_MAY_OMIT = ("bonus_info", "apply_period_type")
DETAIL_MUST_HAVE = ("notice_id", "title", "organizer", "supervising_org", "executing_org", "source", "category",
                    "apply_start", "apply_end", "recruitment_status", "url", "apply_url", "support_amount_max_won",
                    "support_amount_text", "eligibility")


def test_detail_keys_allowed_missing():
    server = FakeNoticeServer()
    d = detail("kstartup:A01")
    for key in DETAIL_MAY_OMIT:
        del d[key]
    server.details["kstartup:A01"] = d
    ann = run_g01(server).selected_announcement
    assert (ann.bonus_info, ann.apply_period_type) == (None, "모름")


@pytest.mark.parametrize("key", DETAIL_MUST_HAVE)
def test_missing_detail_key_is_format_error(key):
    assert set(DETAIL_MUST_HAVE) | set(DETAIL_MAY_OMIT) == set(detail("k:1"))
    server = FakeNoticeServer()
    d = detail("kstartup:A01")
    del d[key]
    server.details["kstartup:A01"] = d
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert format_detail(e.value) == f"공고 서버 응답 형식 오류: notice.{key}"


@pytest.mark.parametrize("key", ["applicant_types", "business_age_max_months", "parsed"])
def test_missing_detail_eligibility_key_is_format_error(key):
    server = FakeNoticeServer()
    d = detail("kstartup:A01")
    del d["eligibility"][key]
    server.details["kstartup:A01"] = d
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert format_detail(e.value) == f"공고 서버 응답 형식 오류: notice.eligibility.{key}"


@pytest.mark.parametrize("over", [
    {"notice_id": "kstartup:OTHER"}, {"notice_id": None}, {"title": None}, {"apply_end": "2026/10/31"},
    {"apply_start": 20260901}, {"support_amount_max_won": "1억"}, {"support_amount_max_won": True},
    {"support_amount_text": 1}, {"bonus_info": ["x"]}, {"category": 3}, {"eligibility": None},
    {"eligibility": {"applicant_types": "법인", "business_age_max_months": None, "parsed": True}},
    {"eligibility": {"applicant_types": [], "business_age_max_months": "84", "parsed": True}},
    {"eligibility": {"applicant_types": [], "business_age_max_months": None, "parsed": "yes"}},
    {"eligibility": {"applicant_types": [], "business_age_max_months": None}},
])
def test_bad_detail_is_format_error(over):
    server = FakeNoticeServer()
    server.details["kstartup:A01"] = detail("kstartup:A01", **over)
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert e.value.error == "형식오류"
    assert ("POST", "/api/notices/kstartup%3AA01/eligibility") not in server.paths()


# ── G-01: 판정 → GateResult · 업력 (4.3.2) ───────────────
@pytest.mark.parametrize("months, years", [(3, 0.3), (15, 1.3), (1, 0.1), (9, 0.8), (27, 2.3), (18, 1.5),
                                           (0, 0.0), (6, 0.5), (33, 2.8), (100, 8.3), (13, 1.1)])
def test_business_age_years_rounds_half_up(months, years):
    """업력(년) = 개월 ÷ 12를 소수 첫째 자리에서 사사오입 — 스텁 G-01도 이 함수를 쓴다.

    재현: 짝수 맞춤(round)이면 3 → 0.2 · 15 → 1.2 · 27 → 2.2처럼 내려간다 (스텁 G-01 업력 버그, 38beeb1).
    """
    assert business_age_years(months) == years                                    # round()의 짝수 맞춤을 쓰지 않는다


def test_gate_result_and_request():
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = gate(passed=True, unknown_conditions=["업력"], business_age_months=15)
    out = run_g01(server)
    g = out.gate_result
    assert (g.passed, g.failed_conditions, g.missing_inputs, g.undecidable, g.unknown_conditions) == (
        True, [], [], False, ["업력"])
    assert out.business_age_years == 1.3
    assert server.paths() == [("GET", "/api/notices/kstartup%3AA01"),
                              ("POST", "/api/notices/kstartup%3AA01/eligibility")]
    assert server.calls[1][2] == {"applicant_type": "법인", "founded_at": "2025-03-02", "today": "2026-09-26"}


def test_gate_rejected():
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = gate(passed=False, failed_conditions=["지원대상 유형", "업력"],
                                        unknown_conditions=[], business_age_months=90)
    out = run_g01(server, applicant_type="개인사업자")
    assert (out.gate_result.passed, out.gate_result.failed_conditions) == (False, ["지원대상 유형", "업력"])
    assert out.business_age_years == 7.5
    assert server.calls[1][2]["applicant_type"] == "개인사업자"


def test_gate_age_is_null_for_prestartup_or_null_months():
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = gate(business_age_months=None)
    assert run_g01(server).business_age_years is None
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = gate(business_age_months=12)
    out = run_g01(server, applicant_type="예비창업자", founded_at=None)
    assert out.business_age_years is None
    assert server.calls[1][2] == {"applicant_type": "예비창업자", "founded_at": "", "today": "2026-09-26"}


@pytest.mark.parametrize("applicant", ["개인사업자", "법인"])
def test_business_without_founded_at_skips_gate_api(applicant):
    server = FakeNoticeServer()
    tools, sink = tools_for("G-01")
    out = run_g01(server, applicant_type=applicant, founded_at=None, tools=tools)
    g = out.gate_result
    assert (g.passed, g.missing_inputs, g.failed_conditions, g.undecidable, g.unknown_conditions) == (
        False, ["foundedAt"], [], False, [])
    assert out.business_age_years is None and out.selected_announcement.announcement_id == "kstartup:A01"
    assert server.paths() == [("GET", "/api/notices/kstartup%3AA01")]             # 판정 API를 부르지 않는다
    assert [log.purpose for log in sink.drain()] == ["공고 상세"]


@pytest.mark.parametrize("bad", [
    gate(passed="true"), gate(failed_conditions="업력"), gate(unknown_conditions=None),
    gate(failed_conditions=["모집기간"]), gate(unknown_conditions=["지역"]), gate(failed_conditions=[1]),
    gate(business_age_months="18"), gate(business_age_months=1.5), gate(business_age_months=-1),
    gate(business_age_months=True), {"failed_conditions": [], "unknown_conditions": []}, [True],
])
def test_bad_gate_is_format_error(bad):
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = bad
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert e.value.error == "형식오류"


@pytest.mark.parametrize("key", ["passed", "failed_conditions", "unknown_conditions", "business_age_months"])
def test_missing_gate_key_is_format_error(key):
    """business_age_months는 null일 수 있지만 키는 있어야 한다."""
    server = FakeNoticeServer()
    g = gate()
    del g[key]
    server.gates["kstartup:A01"] = g
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert format_detail(e.value) == f"공고 서버 응답 형식 오류: eligibility.{key}"


# 유한한 수만 — 너무 큰 개월 수는 형식 오류
@pytest.mark.parametrize("months", [10 ** 400, 10 ** 30])
def test_huge_months_are_format_errors(months):
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = gate(business_age_months=months)
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert format_detail(e.value) == "공고 서버 응답 형식 오류: eligibility.business_age_months"
    server = FakeNoticeServer()
    server.details["kstartup:A01"] = detail("kstartup:A01", eligibility={
        "applicant_types": ["법인"], "business_age_max_months": 10 ** 400, "parsed": True})
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert format_detail(e.value) == "공고 서버 응답 형식 오류: notice.eligibility.business_age_max_months"


# ── G-01: 공고 없음 · 오류 ──────────────────────────────
def test_not_found_from_detail_raises_resource_not_found():
    server = FakeNoticeServer()
    server.not_found.add("kstartup:A01")
    tools, sink = tools_for("G-01")
    with pytest.raises(ResourceNotFound) as e:
        run_g01(server, tools=tools)
    assert "kstartup" not in str(e.value) and "A01" not in str(e.value)        # 메시지에 공고 ID가 없다
    assert server.paths() == [("GET", "/api/notices/kstartup%3AA01")]            # 재시도 · 판정 없음
    [log] = sink.drain()
    assert (log.purpose, log.final_outcome, len(log.tries)) == ("공고 상세", "성공", 1)   # 성공한 호출로 기록


def test_not_found_from_gate_raises_resource_not_found():
    server = FakeNoticeServer()
    server.gate_not_found.add("kstartup:A01")
    tools, sink = tools_for("G-01")
    with pytest.raises(ResourceNotFound) as e:
        run_g01(server, tools=tools)
    assert "A01" not in str(e.value)
    assert [(log.purpose, log.final_outcome, len(log.tries)) for log in sink.drain()] == [
        ("공고 상세", "성공", 1), ("자격 판정", "성공", 1)]


def test_404_without_code_is_retried_then_exhausted():
    server = FakeNoticeServer()
    server.raw[("GET", "/api/notices/kstartup%3AA01")] = (404, b'{"detail": "Not Found"}')
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert (e.value.error, e.value.error_kind, e.value.tries) == ("호출실패", "운영", 2)


def test_g01_connection_failure_is_retried_then_exhausted():
    server = FakeNoticeServer()
    server.raw[("POST", "/api/notices/kstartup%3AA01/eligibility")] = ConnectionError("공고 서버 연결 실패")
    with pytest.raises(ToolCallExhausted) as e:
        run_g01(server)
    assert (e.value.error, e.value.error_kind) == ("호출실패", "일시")
    assert server.paths().count(("POST", "/api/notices/kstartup%3AA01/eligibility")) == 2
