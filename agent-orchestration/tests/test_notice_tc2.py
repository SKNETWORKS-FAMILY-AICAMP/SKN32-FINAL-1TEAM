"""실제 T-C2 (공고 서버 연결, spec 4.1) — 가짜 전송으로 시험한다. 네트워크에 나가지 않는다.

- 수집 상태 먼저, 보내는 칸(4.1.2) · 시 · 도 바꾸기, 카드 변환(4.1.3) · 추천 이유(4.1.4), 받은 순서 그대로.
- 가산점 스위치 켜짐 · 꺼짐, 응답 형식 오류(상세에는 키 이름만).
- 모든 호출은 tools.search로 한다. ToolCallExhausted는 받지 않고 올려 보낸다.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from notice_fake import FAKE_URL, FakeNoticeServer, company, format_detail, item, result, run_tc2, tools_for

from sbrain.agents.notice import NoticeClient, make_tc2, match_request, region_fields
from sbrain.contracts import tasks as c
from sbrain.models import BonusItem
from sbrain.orchestrator.errors import ToolCallExhausted
from sbrain.orchestrator.settings import PROVISIONAL


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
def test_card_conversion(bonus_on):
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


def test_bonus_rules(bonus_on):
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


# 잘못된 모양의 가산점 값 — 켜져 있으면 형식 오류, 꺼져 있으면 읽지 않는다
BAD_BONUS = [
    {"bonus_score": "2"}, {"bonus_score": True}, {"bonus_score": [1]},
    {"bonus_items": {"name": "x", "points": 1}}, {"bonus_items": "x"},
    {"bonus_items": [{"points": 1}]}, {"bonus_items": [{"name": "x"}]}, {"bonus_items": [{"name": 1, "points": 1}]},
    {"bonus_items": [{"name": "x", "points": "1"}]}, {"bonus_items": [{"name": "x", "points": None}]},
    {"bonus_items": ["x"]},
]


@pytest.mark.parametrize("over", BAD_BONUS)
def test_bad_bonus_is_format_error(over, bonus_on):
    card_error(**over)


# ── T-C2: 가산점 스위치 꺼짐 (기본, 공고팀 시험 단계) ──────
def test_bonus_switch_is_off_by_default_and_provisional():
    from sbrain.orchestrator import settings
    assert settings.BONUS_ENABLED is False
    assert "announcement.bonusEnabled" in PROVISIONAL


def test_bonus_off_blanks_cards_but_keeps_keys(bonus_off):
    out = run_tc2(FakeNoticeServer())                                            # 공고 서버는 가산점 값을 준다
    assert [(cd.bonus_score, cd.bonus_items) for cd in out.candidates] == [(None, [])] * 3
    dumped = out.candidates[0].dump()
    assert (dumped["bonusScore"], dumped["bonusItems"]) == (None, [])           # 키는 그대로, 값만 비어 있다


@pytest.mark.parametrize("over", BAD_BONUS)
def test_bonus_off_ignores_bad_bonus(over, bonus_off):
    card = one_card(**over)                                                      # 형식 오류 없이 카드를 만든다
    assert (card.announcement_id, card.bonus_score, card.bonus_items) == ("kstartup:A01", None, [])


@pytest.mark.parametrize("field", ["bonus_score", "points"])
def test_bonus_off_ignores_non_finite_bonus(field, bonus_off):
    """1e400은 JSON 수라 클라이언트를 지나 inf로 읽힌다 — 꺼져 있으면 가산점 칸을 보지 않으므로 실패하지 않는다."""
    server = FakeNoticeServer(ids=())
    over = {"bonus_items": [{"name": "청년 창업자", "points": BIG}]} if field == "points" else {field: BIG}
    server.match["results"] = [result("k:1", 1, **over)]
    server.raw[("POST", "/api/match")] = with_literal(server.match, "1e400")
    card = run_tc2(server).candidates[0]
    assert (card.bonus_score, card.bonus_items) == (None, [])


def test_bonus_off_does_not_change_request_body(bonus_off):
    """보내는 칸은 그대로 — 성별 · 보유 인증 · 첫 창업 여부도 계속 보낸다."""
    server = FakeNoticeServer()
    run_tc2(server)
    [body] = [b for m, p, b in server.calls if p == "/api/match"]
    assert set(body) == SPEC_KEYS
    assert (body["gender"], body["certifications"]) == ("남성", ["벤처기업"]) and "first_startup" in body


@pytest.mark.parametrize("over", [
    {"notice_id": None}, {"notice_id": ""}, {"title": None}, {"source": None}, {"url": None}, {"rank": "1"},
    {"rank": 0}, {"rank": 21}, {"rank": True}, {"display_type": None}, {"fit_score": "0.8"}, {"fit_score": 1.5},
    {"apply_end": "31/10/2026"}, {"apply_end": 20261031}, {"band": "높음"}, {"region_match": "yes"}, {"region": 1},
    {"organizer": 3},
])
def test_out_of_contract_card_values_are_format_errors(over):
    card_error(**over)


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


def test_card_keys_allowed_missing(bonus_on):
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
def test_non_finite_numbers_are_format_errors(field, literal, bonus_on):
    server = FakeNoticeServer(ids=())
    over = {"bonus_items": [{"name": "청년 창업자", "points": BIG}]} if field == "points" else {field: BIG}
    server.match["results"] = [result("k:1", 1, **over)]
    server.raw[("POST", "/api/match")] = with_literal(server.match, literal)
    with pytest.raises(ToolCallExhausted) as e:
        run_tc2(server)
    path = "bonus_items[0].points" if field == "points" else field
    assert format_detail(e.value) == f"공고 서버 응답 형식 오류: match.results[0].{path}"


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


def test_order_and_rank_kept_as_received(bonus_on):
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
