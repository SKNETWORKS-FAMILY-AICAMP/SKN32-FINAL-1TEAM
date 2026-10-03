"""실제 T-C2 · G-01 (공고 서버 연결, spec 4.1 · 4.3.2 · 4.4) — 가짜 전송으로 시험한다. 네트워크에 나가지 않는다.

- T-C2: 수집 상태 먼저, 보내는 칸(4.1.2) · 시 · 도 바꾸기, 카드 변환(4.1.3) · 추천 이유(4.1.4), 받은 순서 그대로.
- G-01: 상세 → Announcement(4.4), 설립일 없는 사업자는 판정을 부르지 않음, 판정 → GateResult · 업력(사사오입),
  공고 없음 → ResourceNotFound(흐름이 X-C2-GONE으로 처리).
- 모든 호출은 tools.search로 한다. ToolCallExhausted는 받지 않고 올려 보낸다.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime
from typing import Any

import pytest
from conftest import executed, make_app, pre_input, project_for

from sbrain.agents.form_defaults import default_evaluation_items, default_form_spec
from sbrain.agents.notice import (
    NoticeClient, bind_notice, business_age_years, make_g01, make_tc2, match_request, region_fields,
)
from sbrain.contracts import tasks as c
from sbrain.models import BonusItem, CompanyInfo, EligibilityRule, ItemSpec, RevenueItem
from sbrain.orchestrator.errors import ResourceNotFound, ToolCallExhausted, message
from sbrain.orchestrator.settings import PROVISIONAL
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

FAKE_URL = "http://example.invalid:8000"
NOT_FOUND = (404, json.dumps({"code": "NOTICE_NOT_FOUND"}).encode())
SECRET = "응답비밀표식"

SPEC_KEYS = {"applicant_type", "idea", "founded_at", "region", "district", "gender", "certifications",
             "first_startup", "main_industry", "hiring_plan", "partners", "team", "revenue", "top", "offset"}

# 웹 시 · 도 17개 → 공고팀 16개 (spec 4.1.2)
REGIONS = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "전남광주",
    "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라남도": "전남광주", "경상북도": "경북",
    "경상남도": "경남", "제주특별자치도": "제주",
}


# ── 가짜 공고 서버 (전송) ───────────────────────────────
def result(nid: str, rank: int, /, **over) -> dict[str, Any]:
    """공고 추천 결과 한 건 (API 1 results[])."""
    base = {"notice_id": nid, "title": f"창업지원 {nid}", "organizer": "중소벤처기업부", "source": "kstartup",
            "apply_end": "2026-10-31", "apply_period_type": "fixed", "url": f"https://notice.example.invalid/{rank}",
            "rank": rank, "display_type": "card", "fit_score": 0.8, "band": "적합", "region": "서울",
            "region_match": True, "content_version": f"v-{nid}", "bonus_score": 1.0,
            "bonus_items": [{"name": "청년 창업자", "points": 1.0}]}
    base.update(over)
    return base


def detail(nid: str, **over) -> dict[str, Any]:
    """공고 상세 (API 3, spec 3.2.1)."""
    base = {"notice_id": nid, "title": f"창업지원 {nid}", "organizer": "중소벤처기업부", "supervising_org": "창업진흥원",
            "executing_org": None, "source": "kstartup", "category": "사업화", "apply_start": "2026-09-01",
            "apply_end": "2026-10-31", "apply_period_type": "fixed", "recruitment_status": "open",
            "url": "https://notice.example.invalid/d", "apply_url": "https://notice.example.invalid/apply",
            "support_amount_max_won": 100_000_000, "support_amount_text": "최대 1억원", "bonus_info": "청년 창업자 가점 1점",
            "eligibility": {"applicant_types": ["예비창업자", "개인사업자", "법인"], "business_age_max_months": 84,
                            "parsed": True}}
    base.update(over)
    return base


def gate(**over) -> dict[str, Any]:
    """자격 판정 (API 4)."""
    base = {"passed": True, "failed_conditions": [], "unknown_conditions": [], "business_age_months": 18}
    base.update(over)
    return base


class FakeNoticeServer:
    """가짜 전송 — 공고 서버 네 API를 흉내 낸다. 받은 요청(메서드 · 경로 · 본문)과 제한 시간을 남긴다."""

    def __init__(self, ids: tuple[str, ...] = ("kstartup:A01", "bizinfo:B02", "kstartup:A03")) -> None:
        self.status: Any = {"status": "정상"}
        self.match: Any = {"results": [result(nid, i + 1) for i, nid in enumerate(ids)],
                           "filtered_count": 42, "fallback_used": False, "fallback_mode": None}
        self.details: dict[str, Any] = {}
        self.gates: dict[str, Any] = {}
        self.not_found: set[str] = set()          # 상세가 공고 없음인 공고
        self.gate_not_found: set[str] = set()     # 판정이 공고 없음인 공고
        self.raw: dict[tuple[str, str], Any] = {}  # (메서드, 경로) → (상태, 본문) 또는 올릴 예외
        self.calls: list[tuple[str, str, Any]] = []
        self.urls: list[str] = []
        self.timeouts: list[float] = []

    def paths(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.calls]

    def __call__(self, method: str, url: str, body: bytes | None, timeout: float) -> tuple[int, bytes]:
        assert url.startswith(FAKE_URL + "/")
        path = url[len(FAKE_URL):]
        self.urls.append(url)
        self.timeouts.append(timeout)
        self.calls.append((method, path, json.loads(body.decode("utf-8")) if body else None))
        if (method, path) in self.raw:
            r = self.raw[(method, path)]
            if isinstance(r, Exception):
                raise r
            return r
        if (method, path) == ("GET", "/api/collection_status"):
            return self._ok(self.status)
        if (method, path) == ("POST", "/api/match"):
            return self._ok(self.match)
        parts = path.split("/")                    # ['', 'api', 'notices', '<id>'(, 'eligibility')]
        nid = urllib.parse.unquote(parts[3])
        if method == "GET" and len(parts) == 4:
            return NOT_FOUND if nid in self.not_found else self._ok(self.details.get(nid, detail(nid)))
        if method == "POST" and len(parts) == 5 and parts[4] == "eligibility":
            return NOT_FOUND if nid in self.gate_not_found else self._ok(self.gates.get(nid, gate()))
        return 404, b""

    @staticmethod
    def _ok(value: Any) -> tuple[int, bytes]:
        return 200, json.dumps(value, ensure_ascii=False).encode("utf-8")


# ── Task 단위 도움 ─────────────────────────────────────
def item() -> ItemSpec:
    return ItemSpec(item_name="헬스온 매니저", one_line_summary="동네 헬스장 회원 관리 서비스", target_customer="소규모 헬스장",
                    core_features=["회원 등록·조회", "수업 예약"], category="웹개발", keywords=["헬스장", "회원관리"])


def company(**over) -> CompanyInfo:
    base = dict(representative_name="김서준", representative_career=["헬스장 운영 5년"], founded_at=date(2025, 3, 2),
                applicant_type="법인", revenue_unit_price=35000, team_careers=["이하늘(개발): 웹 개발 3년", "박지우"],
                region="서울특별시 마포구", industry_code="정보·통신", birth_date=date(1990, 1, 1), gender="남성",
                certifications=["벤처기업"], hiring_plan="없음", facilities="태블릿 보유", partners="없음",
                business_reg_no="123-45-67890", self_fund_amount=10_000_000, desired_scale="5천만원",
                revenue_items=[RevenueItem(service_name="월 구독", unit_price=35000),
                               RevenueItem(service_name="연 구독", unit_price=350000)],
                company_name="상호표식주식회사", representative_capability="헬스장 운영 노하우")
    base.update(over)
    return CompanyInfo(**base)


def tools_for(task_id: str, retries: int = 1) -> tuple[Tools, CallSink]:
    sink = CallSink()
    cfg = ToolsConfig(agent="조율", provider="openai", model="gpt-6-luna", temperature=None, timeout_sec=30.0,
                      retry_count=retries, retry_interval_sec=0)
    ctx = ToolsContext(run_id="r1", execution_id="e1", task_id=task_id, providers={}, sink=sink,
                       now=datetime.now, sleep=lambda s: None)
    return Tools(cfg, ctx), sink


def run_tc2(server: FakeNoticeServer, *, top_k: int = 10, offset: int = 0, **company_over) -> c.TC2Out:
    tools, _ = tools_for("T-C2")
    inp = c.TC2In(item_spec=item(), company_info=company(**company_over), today=date(2026, 9, 26),
                  top_k=top_k, offset=offset)
    return make_tc2(NoticeClient(FAKE_URL, transport=server))(inp, tools)


def run_g01(server: FakeNoticeServer, aid: str = "kstartup:A01", *, tools: Tools | None = None,
            **company_over) -> c.G01Out:
    tools = tools or tools_for("G-01")[0]
    inp = c.G01In(company_info=company(**company_over), today=date(2026, 9, 26), announcement_id=aid)
    return make_g01(NoticeClient(FAKE_URL, transport=server))(inp, tools)


def one_card(**over):
    server = FakeNoticeServer(ids=())
    server.match["results"] = [result("kstartup:A01", 1, **over)]
    return run_tc2(server).candidates[0]


def card_error(**over) -> ToolCallExhausted:
    """카드 변환이 FormatError를 내면 tools가 재시도하고, 다 쓰면 ToolCallExhausted가 그대로 올라온다."""
    server = FakeNoticeServer(ids=())
    server.match["results"] = [result("kstartup:A01", 1, **over)]
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert e.value.error == "형식오류"
    return e.value


# ── T-C2: 보내는 값 (4.1.2) ─────────────────────────────
def test_match_request_has_exactly_the_spec_fields():
    body = match_request(item(), company(), top=10, offset=0)
    assert body == {
        "applicant_type": "법인",
        "idea": "헬스온 매니저. 동네 헬스장 회원 관리 서비스. 목표 고객: 소규모 헬스장. "
                "핵심 기능: 회원 등록·조회, 수업 예약. 키워드: 헬스장, 회원관리",
        "founded_at": "2025-03-02", "region": "서울", "district": "마포구", "gender": "남성",
        "certifications": ["벤처기업"], "first_startup": None, "main_industry": "정보·통신", "hiring_plan": False,
        "partners": [], "team": [{"career": "이하늘(개발): 웹 개발 3년"}, {"career": "박지우"}],
        "revenue": [{"item": "월 구독", "price": "35000"}, {"item": "연 구독", "price": "350000"}],
        "top": 10, "offset": 0,
    }


def test_match_request_sends_no_personal_fields():
    sent = json.dumps(match_request(item(), company(), top=10, offset=0), ensure_ascii=False)
    for value in ("김서준", "1990-01-01", "1990", "123-45-67890", "10000000", "5천만원", "태블릿", "상호표식",
                  "헬스장 운영 노하우", "헬스장 운영 5년"):
        assert value not in sent, value                                           # 이름 · 생년월일 · 사업자번호 등


@pytest.mark.parametrize("plan, expected", [("없음", False), ("", False), ("  ", False), (" 없음 ", False),
                                            ("개발자 1명 (2026-03)", True)])
def test_hiring_plan_flag(plan, expected):
    assert match_request(item(), company(hiring_plan=plan), top=10, offset=0)["hiring_plan"] is expected


@pytest.mark.parametrize("partners, expected", [("없음", []), ("", []), ("  ", []),
                                                ("A대학교; B연구소", ["A대학교", "B연구소"]),
                                                ("C협회", ["C협회"])])
def test_partners_split(partners, expected):
    assert match_request(item(), company(partners=partners), top=10, offset=0)["partners"] == expected


def test_optional_company_values():
    body = match_request(item(), company(founded_at=None, certifications=None, is_first_startup=True,
                                         team_careers=[], revenue_items=[], applicant_type="예비창업자"),
                         top=10, offset=10)
    assert (body["founded_at"], body["certifications"], body["first_startup"]) == ("", [], True)
    assert (body["team"], body["revenue"], body["applicant_type"], body["offset"]) == ([], [], "예비창업자", 10)


@pytest.mark.parametrize("sido", list(REGIONS))
def test_region_map_all_17_web_values(sido):
    assert region_fields(f"{sido} 마포구") == (REGIONS[sido], "마포구")
    assert region_fields(sido) == (REGIONS[sido], "")                           # 시 · 군 · 구 없음


def test_region_map_edge_cases():
    assert len(set(REGIONS.values())) == 16                                       # 광주 · 전남은 전남광주 하나
    assert region_fields("경기도 수원시 영통구") == ("경기", "수원시 영통구")          # 첫 공백 뒤 전체가 시 · 군 · 구
    assert region_fields("서울 마포구") == ("", "")                               # 표에 없는 시 · 도 → 둘 다 ""
    assert region_fields("서울특별시청 마포구") == ("", "")
    assert region_fields("") == ("", "")
    assert region_fields(None) == ("", "")


def test_top_is_capped_at_10_and_offset_passed():
    server = FakeNoticeServer()
    run_tc2(server, top_k=15, offset=10)
    body = server.calls[1][2]
    assert (body["top"], body["offset"]) == (10, 10)
    server = FakeNoticeServer(ids=("k:1",))
    run_tc2(server, top_k=5)
    assert server.calls[1][2]["top"] == 5


def test_tc2_sends_the_spec_body_through_tools():
    server = FakeNoticeServer()
    tools, sink = tools_for("T-C2")
    inp = c.TC2In(item_spec=item(), company_info=company(), today=date(2026, 9, 26), top_k=10, offset=0)
    make_tc2(NoticeClient(FAKE_URL, transport=server))(inp, tools)
    assert server.paths() == [("GET", "/api/collection_status"), ("POST", "/api/match")]
    assert server.calls[1][2] == match_request(item(), company(), top=10, offset=0)
    assert set(server.calls[1][2]) == SPEC_KEYS
    assert server.timeouts == [30.0, 30.0]                                        # tools의 제한 시간을 건다
    logs = sink.drain()
    assert [(g.purpose, g.call_type, g.final_outcome, len(g.tries)) for g in logs] == [
        ("수집 상태", "search", "성공", 1), ("공고 매칭", "search", "성공", 1)]


# ── T-C2: 수집 상태 (4.1.1) ─────────────────────────────
@pytest.mark.parametrize("status", ["지연", "실패"])
def test_no_match_call_when_collection_not_normal(status):
    server = FakeNoticeServer()
    server.status = {"status": status}
    out = run_tc2(server)
    assert (out.candidates, out.collection_status, out.filtered_count, out.fallback_used, out.fallback_mode) == (
        [], status, 0, False, None)
    assert server.paths() == [("GET", "/api/collection_status")]                 # 매칭 API를 부르지 않는다


@pytest.mark.parametrize("bad", [{"status": "모름"}, {}, {"status": None}, ["정상"], "정상"])
def test_bad_collection_status_is_format_error(bad):
    server = FakeNoticeServer()
    server.status = bad
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert e.value.error == "형식오류" and e.value.tries == 2
    assert server.paths() == [("GET", "/api/collection_status")] * 2


# ── T-C2: 카드 변환 (4.1.3) ─────────────────────────────
def test_card_conversion():
    out = run_tc2(FakeNoticeServer())
    assert (out.collection_status, out.filtered_count, out.fallback_used, out.fallback_mode) == ("정상", 42, False, None)
    card = out.candidates[0]
    assert card.dump() == {
        "announcementId": "kstartup:A01", "title": "창업지원 kstartup:A01", "agency": "중소벤처기업부",
        "applyEnd": "2026-10-31", "supportAmountMax": None, "fitScore": 0.8, "rank": 1, "displayType": "card",
        "matchReason": "아이템 설명과 공고 내용이 비슷합니다 · 희망 지역 대상 공고입니다",
        "sourceNotice": "본 AI 요약 정보는 K-Startup 공고 내용을 바탕으로 생성되었습니다.",
        "originalUrl": "https://notice.example.invalid/1", "applyPeriodType": "기간 있음", "contentChanged": False,
        "contentVersion": "v-kstartup:A01", "bonusScore": 1.0, "bonusItems": [{"name": "청년 창업자", "points": 1.0}],
    }


def test_card_empty_values():
    card = one_card(organizer="", apply_end="", fit_score=None, apply_period_type=None)
    assert (card.agency, card.apply_end, card.fit_score, card.apply_period_type) == ("-", None, 0.0, "모름")
    card = one_card(organizer=None)
    assert card.agency == "-"


@pytest.mark.parametrize("value, label", [("fixed", "기간 있음"), ("budget_exhaustion", "예산 소진 시까지"),
                                          ("rolling", "상시·수시"), ("until_filled", "선착순·모집 완료 시까지"),
                                          ("weekly", "모름"), (None, "모름")])
def test_card_period_type_labels(value, label):
    assert one_card(apply_period_type=value).apply_period_type == label


def test_card_period_type_missing_key():
    server = FakeNoticeServer(ids=())
    r = result("k:1", 1)
    del r["apply_period_type"]
    server.match["results"] = [r]
    assert run_tc2(server).candidates[0].apply_period_type == "모름"


@pytest.mark.parametrize("source, name", [("kstartup", "K-Startup"), ("bizinfo", "기업마당"), ("smes24", "smes24")])
def test_card_source_notice(source, name):
    assert one_card(source=source).source_notice == f"본 AI 요약 정보는 {name} 공고 내용을 바탕으로 생성되었습니다."


@pytest.mark.parametrize("over, reason", [
    ({"band": "매우 적합", "region": "전국"}, "아이템 설명과 공고 내용이 매우 비슷합니다 · 전국 대상 공고입니다"),
    ({"band": "적합", "region": "서울", "region_match": True}, "아이템 설명과 공고 내용이 비슷합니다 · 희망 지역 대상 공고입니다"),
    ({"band": "참고", "region": "부산", "region_match": False},
     "아이템 설명과 관련이 있는 공고입니다 · 다른 지역 대상 공고일 수 있습니다"),
    ({"band": "적합", "region": "전국", "region_match": False}, "아이템 설명과 공고 내용이 비슷합니다 · 전국 대상 공고입니다"),
    ({"band": None, "region": None, "region_match": None}, "아이템 설명과 관련이 있는 공고입니다"),
    ({"band": "참고", "region": "서울", "region_match": None}, "아이템 설명과 관련이 있는 공고입니다"),
])
def test_match_reason_template(over, reason):
    assert one_card(**over).match_reason == reason


def test_provisional_notice_entries():
    """잠정 목록 (spec 10) — 추천 이유 틀, 호출 하나씩 · 운영 워커 1대. 시 · 도 바꾸기 표는 잠정이 아니다."""
    assert "announcement.matchReason" in PROVISIONAL and "noticeServer.serialCalls" in PROVISIONAL
    assert not any("region" in key.lower() for key in PROVISIONAL)


def test_match_reason_deadline_fallback_and_fields():
    server = FakeNoticeServer(ids=())
    server.match = {"results": [result("k:1", 1, band=None, fit_score=None, region_match=None, region="경기")],
                    "filtered_count": 7, "fallback_used": True, "fallback_mode": "마감임박순"}
    out = run_tc2(server)
    assert (out.fallback_used, out.fallback_mode, out.filtered_count) == (True, "마감임박순", 7)
    card = out.candidates[0]
    assert (card.match_reason, card.fit_score) == ("마감이 가까운 신청 가능 공고입니다", 0.0)
    server.match["fallback_mode"] = "BM25단독"
    assert run_tc2(server).candidates[0].match_reason == "아이템 설명과 관련이 있는 공고입니다"


@pytest.mark.parametrize("mode", ["마감순", "", 3])
def test_unknown_fallback_mode_is_format_error(mode):
    server = FakeNoticeServer()
    server.match["fallback_mode"] = mode
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert e.value.error == "형식오류"


def test_content_version_rules():
    assert one_card(content_version="abc123").content_version == "abc123"
    assert one_card(content_version=None).content_version is None
    server = FakeNoticeServer(ids=())
    r = result("k:1", 1)
    del r["content_version"]
    server.match["results"] = [r]
    assert run_tc2(server).candidates[0].content_version is None
    for bad in (123, ["v1"], {"v": 1}, True):
        card_error(content_version=bad)


def test_bonus_rules():
    card = one_card(bonus_score=2.5, bonus_items=[{"name": "청년 창업자", "points": 1.5}, {"name": "여성 기업", "points": 1}])
    assert card.bonus_score == 2.5
    assert card.bonus_items == [BonusItem(name="청년 창업자", points=1.5), BonusItem(name="여성 기업", points=1.0)]
    card = one_card(bonus_score=0, bonus_items=[])                                # 해당 가점 없음 — 0과 빈 목록
    assert (card.bonus_score, card.bonus_items) == (0.0, [])
    card = one_card(bonus_score=None, bonus_items=None)                           # 계산하지 못함 — null과 빈 목록
    assert (card.bonus_score, card.bonus_items) == (None, [])
    server = FakeNoticeServer(ids=())
    r = result("k:1", 1)
    del r["bonus_score"], r["bonus_items"]
    server.match["results"] = [r]
    card = run_tc2(server).candidates[0]
    assert (card.bonus_score, card.bonus_items) == (None, [])


@pytest.mark.parametrize("over", [
    {"bonus_score": "2"}, {"bonus_score": True}, {"bonus_score": [1]},
    {"bonus_items": {"name": "x", "points": 1}}, {"bonus_items": "x"},
    {"bonus_items": [{"points": 1}]}, {"bonus_items": [{"name": "x"}]}, {"bonus_items": [{"name": 1, "points": 1}]},
    {"bonus_items": [{"name": "x", "points": "1"}]}, {"bonus_items": [{"name": "x", "points": None}]},
    {"bonus_items": ["x"]},
])
def test_bad_bonus_is_format_error(over):
    card_error(**over)


@pytest.mark.parametrize("over", [
    {"notice_id": None}, {"notice_id": ""}, {"title": None}, {"source": None}, {"url": None}, {"rank": "1"},
    {"rank": 0}, {"rank": 21}, {"rank": True}, {"display_type": None}, {"fit_score": "0.8"}, {"fit_score": 1.5},
    {"apply_end": "31/10/2026"}, {"apply_end": 20261031}, {"band": "높음"}, {"region_match": "yes"}, {"region": 1},
    {"organizer": 3},
])
def test_out_of_contract_card_values_are_format_errors(over):
    card_error(**over)


def format_detail(e: ToolCallExhausted) -> str:
    """재시도를 다 쓴 형식 오류의 마지막 상세 — FormatError 메시지(키 경로만)."""
    assert e.error == "형식오류"
    return e.detail


# 키가 없어도 되는 것 (spec 4.1.3 · 4.4 — "키가 없거나 null" · "그 밖의 값 · 없음")
CARD_MAY_OMIT = ("content_version", "bonus_score", "bonus_items", "apply_period_type")
CARD_MUST_HAVE = ("notice_id", "title", "organizer", "source", "apply_end", "url", "rank", "display_type",
                  "fit_score", "band", "region", "region_match")


@pytest.mark.parametrize("key", CARD_MUST_HAVE)
def test_missing_card_key_is_format_error(key):
    """값이 null일 수 있는 키도 키 자체는 있어야 한다 (spec 3.3 "필요한 키가 없거나")."""
    assert set(CARD_MUST_HAVE) | set(CARD_MAY_OMIT) == set(result("k:1", 1))
    server = FakeNoticeServer(ids=())
    r = result("k:1", 1)
    del r[key]
    server.match["results"] = [r]
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert format_detail(e.value) == f"공고 서버 응답 형식 오류: match.results[0].{key}"   # 키 경로만


def test_card_keys_allowed_missing():
    server = FakeNoticeServer(ids=())
    r = result("k:1", 1)
    for key in CARD_MAY_OMIT:
        del r[key]
    server.match["results"] = [r]
    card = run_tc2(server).candidates[0]
    assert (card.content_version, card.bonus_score, card.bonus_items, card.apply_period_type) == (None, None, [], "모름")


@pytest.mark.parametrize("key", ["results", "filtered_count", "fallback_used", "fallback_mode"])
def test_missing_match_envelope_key_is_format_error(key):
    server = FakeNoticeServer()
    del server.match[key]                                                         # fallback_mode는 null이어도 키는 있어야 한다
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert format_detail(e.value) == f"공고 서버 응답 형식 오류: match.{key}"


def test_missing_collection_status_key_is_format_error():
    server = FakeNoticeServer()
    server.status = {"state": "정상"}
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert format_detail(e.value) == "공고 서버 응답 형식 오류: collection_status.status"


# ── 유한한 수만 (1e400은 inf로 읽힌다) ──────────────────────
BIG = "__큰수__"


def with_literal(value: Any, literal: str) -> tuple[int, bytes]:
    """JSON 본문의 BIG 자리에 수 표기를 그대로 넣는다 (json.dumps로는 1e400을 만들 수 없다)."""
    text = json.dumps(value, ensure_ascii=False).replace(json.dumps(BIG, ensure_ascii=False), literal)
    return 200, text.encode("utf-8")


@pytest.mark.parametrize("literal", ["1e400", "-1e400", "1" + "0" * 400])
@pytest.mark.parametrize("field", ["bonus_score", "points", "fit_score"])
def test_non_finite_numbers_are_format_errors(field, literal):
    server = FakeNoticeServer(ids=())
    over = {"bonus_items": [{"name": "청년 창업자", "points": BIG}]} if field == "points" else {field: BIG}
    server.match["results"] = [result("k:1", 1, **over)]
    server.raw[("POST", "/api/match")] = with_literal(server.match, literal)
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    path = "bonus_items[0].points" if field == "points" else field
    assert format_detail(e.value) == f"공고 서버 응답 형식 오류: match.results[0].{path}"


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


@pytest.mark.parametrize("bad", [{"filtered_count": 1, "fallback_used": False}, {"results": "x", "filtered_count": 1,
                                 "fallback_used": False}, {"results": [], "fallback_used": False},
                                 {"results": [], "filtered_count": "1", "fallback_used": False},
                                 {"results": [], "filtered_count": 1, "fallback_used": "no"}, [], "x"])
def test_bad_match_envelope_is_format_error(bad):
    server = FakeNoticeServer()
    server.match = bad
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert e.value.error == "형식오류"


def test_more_results_than_requested_is_format_error():
    server = FakeNoticeServer(ids=tuple(f"k:{i}" for i in range(6)))
    with pytest.raises(ToolCallExhausted):
        run_tc2(server, top_k=5)


def test_format_error_detail_has_key_names_only():
    server = FakeNoticeServer(ids=())
    server.match["results"] = [result("k:1", 1, title=12345, organizer=SECRET, url=SECRET)]
    tools, sink = tools_for("T-C2")
    inp = c.TC2In(item_spec=item(), company_info=company(), today=date(2026, 9, 26), top_k=10, offset=0)
    with pytest.raises(ToolCallExhausted) as e:
        make_tc2(NoticeClient(FAKE_URL, transport=server))(inp, tools)
    [_, match_log] = sink.drain()
    details = [t.detail for t in match_log.tries]
    assert all("title" in d for d in details)
    assert SECRET not in "".join(details) + str(e.value) and "12345" not in "".join(details)


def test_order_and_rank_kept_as_received():
    server = FakeNoticeServer(ids=())
    server.match["results"] = [
        result("k:3", 3, fit_score=0.9, bonus_score=0.0), result("k:1", 1, fit_score=0.2, bonus_score=3.0),
        result("k:2", 2, fit_score=0.5, bonus_score=None)]
    cards = run_tc2(server).candidates
    assert [(cd.announcement_id, cd.rank) for cd in cards] == [("k:3", 3), ("k:1", 1), ("k:2", 2)]  # 다시 정렬하지 않음


def test_tc2_does_not_catch_exhaustion():
    server = FakeNoticeServer()
    server.raw[("POST", "/api/match")] = TimeoutError()
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    assert (e.value.error, e.value.error_kind) == ("응답지연", "일시")
    assert server.paths().count(("POST", "/api/match")) == 2                      # 첫 시도 + 재시도 1회
    server = FakeNoticeServer()
    server.raw[("GET", "/api/collection_status")] = (503, b"")
    with pytest.raises(ToolCallExhausted):
        run_tc2(server)


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
                                           (0, 0.0), (6, 0.5), (33, 2.8), (100, 8.3)])
def test_business_age_years_rounds_half_up(months, years):
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


# ── 흐름 안에서 (메모리 · SQLite) ─────────────────────────
def notice_app(clock, server: FakeNoticeServer):
    app = make_app(clock)
    bind_notice(app.registry, NoticeClient(FAKE_URL, transport=server))
    return app


def started(app) -> str:
    res = app.orchestrator.start_run("acc-1", pre_input(region="경기도 수원시 영통구"), project_id=project_for(app))
    assert res.ok, res
    return res.run_id


def select(app, rid: str, aid: str) -> None:
    app.orchestrator.select_announcement(rid, aid)
    app.orchestrator.advance(rid)


def test_real_tasks_run_through_the_flow(clock):
    server = FakeNoticeServer()
    server.gates["bizinfo:B02"] = gate(business_age_months=18)
    app = notice_app(clock, server)
    rid = started(app)
    pid = app.store.load_run(rid).project_id
    s3 = app.orchestrator.screen(pid, 3)
    assert [cd.announcement_id for cd in s3.candidates] == ["kstartup:A01", "bizinfo:B02", "kstartup:A03"]
    assert (s3.collection_status, s3.filtered_count) == ("정상", 42)
    assert server.calls[1][2]["region"] == "경기" and server.calls[1][2]["district"] == "수원시 영통구"
    select(app, rid, "bizinfo:B02")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.announcement_id) == ("계획서작성", "사용자대기", "bizinfo:B02")
    ctx = app.engine.open_context(run)
    assert ctx.get("selectedAnnouncement").title == "창업지원 bizinfo:B02" and ctx.get("businessAgeYears") == 1.5
    calls = app.store.call_logs(rid)
    assert [(cl.task_id, cl.purpose) for cl in calls] == [
        ("T-C1", "카테고리 판정"), ("T-C2", "수집 상태"), ("T-C2", "공고 매칭"), ("G-01", "공고 상세"), ("G-01", "자격 판정")]
    dump = "".join(r.model_dump_json() for r in app.store.executions(rid)) + "".join(
        cl.model_dump_json() for cl in calls)
    assert "창업지원" not in dump and "김서준" not in dump and "example.invalid" not in dump


def test_real_g01_unknown_conditions_only_on_screen4(clock):
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = gate(unknown_conditions=["지원대상 유형", "업력"])
    app = notice_app(clock, server)
    rid = started(app)
    pid = app.store.load_run(rid).project_id
    select(app, rid, "kstartup:A01")
    assert app.store.load_run(rid).state.step == "계획서작성"
    s4 = app.orchestrator.screen(pid, 4)
    assert s4.gate_result.unknown_conditions == ["지원대상 유형", "업력"] and s4.can_start_writing
    assert [(n.code, n.message) for n in s4.notices] == [("E-G1-UNPARSED", message("E-G1-UNPARSED"))]
    assert "E-G1-UNPARSED" not in [n.code for n in app.store.load_run(rid).notices]


@pytest.mark.parametrize("where", ["상세", "판정"])
def test_real_g01_not_found_goes_back_with_gone(clock, where):
    server = FakeNoticeServer()
    (server.not_found if where == "상세" else server.gate_not_found).add("kstartup:A01")
    app = notice_app(clock, server)
    rid = started(app)
    select(app, rid, "kstartup:A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.notices[-1].code, run.announcement_id) == (
        "공고선택", "사용자대기", "X-C2-GONE", None)
    assert run.blocked_announcement_ids == []
    server.not_found.clear()
    server.gate_not_found.clear()                                                  # 다시 생겼다
    select(app, rid, "kstartup:A01")
    assert app.store.load_run(rid).announcement_id == "kstartup:A01"
    assert executed(app, rid).count("G-01") == 2


def test_real_tc2_stale_collection_ends_start_request(clock):
    server = FakeNoticeServer()
    server.status = {"status": "지연"}
    app = notice_app(clock, server)
    res = app.orchestrator.start_run("acc-1", pre_input())
    assert (res.ok, res.code) == (False, "E-C2-STALE")
    assert ("POST", "/api/match") not in server.paths()
