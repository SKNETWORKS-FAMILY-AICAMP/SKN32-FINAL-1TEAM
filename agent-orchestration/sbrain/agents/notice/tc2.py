"""실제 T-C2 공고 매칭 — 공고 서버의 수집 상태(API 2) · 공고 추천(API 1)으로 후보 카드를 만든다 (spec 4.1).

1. 수집 상태를 받는다. '정상'이 아니면 매칭하지 않고 후보 0건 · 그 상태 · filtered_count 0 · 대체 경로 없음을 돌려준다.
2. 정상이면 공고 추천을 top = min(topK, 10) · offset(입력 그대로)으로 부르고 결과를 카드로 바꾼다.

- 보내는 값은 순위와 가산점 계산에 쓰이는 칸뿐이다(4.1.2 — 성별 · 보유 인증 · 첫 창업 여부는 공고팀 답변상 가산점
  계산에만 쓰인다). 대표자 이름 · 생년월일 · 사업자등록번호 · 자기부담금 · 희망 사업 규모 · 보유 시설 · 그 밖의 확장
  필드는 보내지 않는다. 가산점 스위치가 꺼져 있어도 보내는 칸은 같다.
- 가산점(bonus_score · bonus_items)은 가산점 스위치(orchestrator/settings.py BONUS_ENABLED, 잠정 · 기본 꺼짐)가
  켜져 있을 때만 읽고 검사한다. 꺼져 있으면 키를 읽지 않고 카드는 bonus_score=None · bonus_items=[]다 — 공고팀
  시험 단계의 값이 잘못된 모양이어도 공고 매칭이 실패하지 않는다.
- 결과 순서와 rank는 받은 그대로 둔다. 적합도 · 가산점으로 다시 정렬하지 않는다(사용자 결정).
- 대체 경로는 공고 서버가 안에서 한다 — 우리 쪽 대체 경로는 없고 ToolCallExhausted를 받지 않고 올려 보낸다.
  대체 경로 안내(E-C2-EMBED)는 흐름이 fallback_used를 보고 붙인다.
- 첫 조회와 겹치는 후보 · 내용 바뀜(contentChanged)은 흐름 규칙이다(4.2.2) — 여기서는 늘 False로 둔다.
- 저장소 · DB · RunContext에 접근하지 않는다. 외부 호출은 tools.search로만 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, get_args

from pydantic import ValidationError

from ...contracts.tasks import TC2In, TC2Out
from ...models import AnnouncementCard, BonusItem, CompanyInfo, ItemSpec
from ...models.base import CollectionStatus, FallbackMode
from ...orchestrator import settings
from ...orchestrator.tools import Tools
from .client import NoticeClient
from .convert import (
    bad, finite, first_text, from_validation, obj, opt_bool, opt_date, opt_number, opt_str, period_label, req,
    req_bool, req_int, req_list, req_str,
)

MAX_TOP = 10              # 공고 추천 한 번에 받는 최대 건수 (TC2Out.candidates 상한)
NONE_TEXT = "없음"        # 사전 정보 '해당 없음' (intake/mapping.py NONE_TEXT와 같은 값)

# 웹 시 · 도(region_sido 드롭다운 17개) → 공고팀 16개 값 (spec 4.1.2 — 웹 값 확인됨, 잠정 아님).
# 공고팀은 광주 · 전남을 '전남광주' 한 값으로 묶는다. 표에 없는 값은 ""(지역 순위 조정만 꺼진다).
REGION_MAP: dict[str, str] = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "전남광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "강원특별자치도": "강원",
    "충청북도": "충북",
    "충청남도": "충남",
    "전북특별자치도": "전북",
    "전라남도": "전남광주",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주특별자치도": "제주",
}

# 출처 고지 (spec 4.1.3) — 그 밖의 출처는 source 값 그대로
SOURCE_NAMES = {"kstartup": "K-Startup", "bizinfo": "기업마당"}
SOURCE_NOTICE = "본 AI 요약 정보는 {출처} 공고 내용을 바탕으로 생성되었습니다."

# 추천 이유 문장 틀 (잠정, spec 4.1.4 — orchestrator/settings.py PROVISIONAL announcement.matchReason).
# AI를 부르지 않는다. 앞 문장(band · 대체 경로)과 뒷말(지역)을 " · "로 잇는다.
REASON_BY_BAND = {
    "매우 적합": "아이템 설명과 공고 내용이 매우 비슷합니다",
    "적합": "아이템 설명과 공고 내용이 비슷합니다",
    "참고": "아이템 설명과 관련이 있는 공고입니다",
}
REASON_DEADLINE = "마감이 가까운 신청 가능 공고입니다"       # band가 null이고 대체 경로가 '마감임박순'
REASON_DEFAULT = "아이템 설명과 관련이 있는 공고입니다"       # band가 null인 그 밖의 경우
REASON_NATIONWIDE = "전국 대상 공고입니다"
REASON_REGION_MATCH = "희망 지역 대상 공고입니다"
REASON_REGION_OTHER = "다른 지역 대상 공고일 수 있습니다"
REASON_JOIN = " · "
DEADLINE_MODE = "마감임박순"

COLLECTION_STATUSES = frozenset(get_args(CollectionStatus))
FALLBACK_MODES = frozenset(get_args(FallbackMode))


# ── 보내는 값 (4.1.2) ──────────────────────────────────
def region_fields(region: str | None) -> tuple[str, str]:
    """사전 정보 region('시·도 시·군·구') → (공고팀 시 · 도, 시 · 군 · 구).

    첫 공백 앞이 시 · 도, 뒤 전체가 시 · 군 · 구다(워커가 웹 두 칸을 공백으로 이어 만든다). 시 · 군 · 구는 바꾸지 않는다.
    표에 없는 시 · 도이거나 region이 비었으면 둘 다 "".
    """
    sido, _, district = (region or "").strip().partition(" ")
    mapped = REGION_MAP.get(sido, "")
    return (mapped, district.strip()) if mapped else ("", "")


def idea_text(item: ItemSpec) -> str:
    """공고팀 설명서 5절의 아이템 설명 문장."""
    return (f"{item.item_name}. {item.one_line_summary}. 목표 고객: {item.target_customer}. "
            f"핵심 기능: {', '.join(item.core_features)}. 키워드: {', '.join(item.keywords)}")


def _has_value(text: str | None) -> bool:
    t = (text or "").strip()
    return bool(t) and t != NONE_TEXT


def match_request(item: ItemSpec, company: CompanyInfo, *, top: int, offset: int) -> dict[str, Any]:
    """공고 추천 요청 본문 — 순위와 가산점 계산에 쓰이는 칸만 (spec 4.1.2). 가산점 스위치와 상관없이 같다."""
    region, district = region_fields(company.region)
    partners = company.partners if _has_value(company.partners) else ""
    return {
        "applicant_type": company.applicant_type,
        "idea": idea_text(item),
        "founded_at": company.founded_at.isoformat() if company.founded_at else "",
        "region": region,
        "district": district,
        "gender": company.gender,
        "certifications": list(company.certifications or []),
        "first_startup": company.is_first_startup,
        "main_industry": company.industry_code,              # 웹 값이 업종 이름이라 그대로 보낸다
        "hiring_plan": _has_value(company.hiring_plan),
        "partners": [p.strip() for p in partners.split("; ") if p.strip()],
        "team": [{"career": career} for career in company.team_careers],
        "revenue": [{"item": r.service_name, "price": str(r.unit_price)} for r in company.revenue_items],
        "top": top,
        "offset": offset,
    }


# ── 받은 값 → 카드 (4.1.3 · 4.1.4) ─────────────────────
@dataclass(frozen=True)
class MatchResult:
    cards: list[AnnouncementCard]
    filtered_count: int
    fallback_used: bool
    fallback_mode: str | None


def parse_status(data: Any) -> str:
    status = req(obj(data, "collection_status"), "status", "collection_status")
    if not isinstance(status, str) or status not in COLLECTION_STATUSES:
        raise bad("collection_status.status")
    return status


def match_reason(band: str | None, region: str | None, region_match: bool | None, fallback_mode: str | None) -> str:
    if band is not None:
        head = REASON_BY_BAND[band]
    elif fallback_mode == DEADLINE_MODE:
        head = REASON_DEADLINE
    else:
        head = REASON_DEFAULT
    if region == "전국":
        tail = REASON_NATIONWIDE
    elif region_match is True:
        tail = REASON_REGION_MATCH
    elif region_match is False:
        tail = REASON_REGION_OTHER
    else:
        return head
    return head + REASON_JOIN + tail


def _bonus_items(r: dict[str, Any], where: str) -> list[BonusItem]:
    """가산점 항목 — 키가 없거나 null이면 빈 목록 (spec 4.1.3). 항목마다 name(문자열) · points(유한한 수)."""
    items = r.get("bonus_items")
    if items is None:
        return []
    if not isinstance(items, list):
        raise bad(f"{where}.bonus_items")
    out = []
    for i, it in enumerate(items):
        at = f"{where}.bonus_items[{i}]"
        it = obj(it, at)
        out.append(BonusItem(name=req_str(it, "name", at), points=finite(req(it, "points", at), f"{at}.points")))
    return out


def to_card(r: Any, where: str, fallback_mode: str | None) -> AnnouncementCard:
    """추천 결과 한 건 → 카드. 키가 없어도 되는 것은 content_version · bonus_score · bonus_items · apply_period_type뿐.

    가산점 키는 가산점 스위치가 켜져 있을 때만 읽고 검사한다(꺼져 있으면 None · 빈 목록).
    """
    r = obj(r, where)
    notice_id = req_str(r, "notice_id", where, nonempty=True)
    title = req_str(r, "title", where)
    source = req_str(r, "source", where, nonempty=True)
    url = req_str(r, "url", where)
    rank = req_int(r, "rank", where)
    display_type = req_str(r, "display_type", where)
    band = opt_str(r, "band", where)
    if band is not None and band not in REASON_BY_BAND:
        raise bad(f"{where}.band")
    region = opt_str(r, "region", where)
    region_match = opt_bool(r, "region_match", where)
    fit = opt_number(r, "fit_score", where)
    if settings.BONUS_ENABLED:                               # 부를 때마다 읽는다 (잠정, 기본 꺼짐)
        bonus_score, bonus_items = opt_number(r, "bonus_score", where, missing_ok=True), _bonus_items(r, where)
    else:                                                    # 공고팀 시험 단계 — 키를 읽지도 검사하지도 않는다
        bonus_score, bonus_items = None, []
    try:
        return AnnouncementCard(
            announcement_id=notice_id,
            title=title,
            agency=first_text(r, ("organizer",), where, "-"),
            apply_end=opt_date(r, "apply_end", where),
            support_amount_max=None,                         # 추천 결과에는 금액이 없다
            fit_score=0.0 if fit is None else fit,
            rank=rank,
            display_type=display_type,
            match_reason=match_reason(band, region, region_match, fallback_mode),
            source_notice=SOURCE_NOTICE.replace("{출처}", SOURCE_NAMES.get(source, source)),
            original_url=url,
            apply_period_type=period_label(r.get("apply_period_type")),
            content_changed=False,                           # 추가 조회 겹침에서만 흐름이 참으로 바꾼다 (4.2.2)
            content_version=opt_str(r, "content_version", where, missing_ok=True),
            bonus_score=bonus_score,
            bonus_items=bonus_items,
        )
    except ValidationError as e:                             # 적합도 0~1 · 순위 1~20 밖 등
        raise from_validation(where, e) from None


def parse_match(data: Any, top: int) -> MatchResult:
    d = obj(data, "match")
    results = req_list(d, "results", "match")
    filtered_count = req_int(d, "filtered_count", "match")
    fallback_used = req_bool(d, "fallback_used", "match")
    mode = req(d, "fallback_mode", "match")                  # 키는 있어야 한다 (대체 경로가 없으면 null)
    if mode is not None and (not isinstance(mode, str) or mode not in FALLBACK_MODES):
        raise bad("match.fallback_mode")
    if len(results) > top:
        raise bad("match.results (요청보다 많음)")
    cards = [to_card(r, f"match.results[{i}]", mode) for i, r in enumerate(results)]
    return MatchResult(cards, filtered_count, fallback_used, mode)


# ── Task 함수 ─────────────────────────────────────────
def make_tc2(client: NoticeClient) -> Callable[[TC2In, Tools], TC2Out]:
    """공고 서버에 연결한 T-C2 함수를 만든다 — registry.bind("T-C2", make_tc2(client))."""

    def run(inp: TC2In, tools: Tools) -> TC2Out:
        status = tools.search("수집 상태", lambda timeout: parse_status(client.collection_status(timeout)))
        if status != "정상":        # 매칭하지 않는다 — 후보 0건 (기준 문서 T-C2 ②, spec 4.1.1)
            return TC2Out(candidates=[], collection_status=status, filtered_count=0, fallback_used=False)
        top = min(inp.top_k, MAX_TOP)
        body = match_request(inp.item_spec, inp.company_info, top=top, offset=inp.offset)
        result = tools.search("공고 매칭", lambda timeout: parse_match(client.match(body, timeout), top))
        return TC2Out(candidates=result.cards, collection_status=status, filtered_count=result.filtered_count,
                      fallback_used=result.fallback_used, fallback_mode=result.fallback_mode)

    return run
