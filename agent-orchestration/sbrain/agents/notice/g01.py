"""실제 G-01 자격 확인 — 공고 서버의 공고 상세(API 3)와 자격 판정(API 4)을 한 단계에서 한다 (spec 4.3.2 · 4.4).

1. 공고 상세를 받아 `Announcement`로 바꾼다.
2. 사업자(개인사업자 · 법인)인데 설립일이 없으면 판정 API를 부르지 않는다 — passed=False, missingInputs=['foundedAt']
   (기준 문서 R-2 ①, E-G1-MISSING).
3. 그 밖에는 판정을 받는다. 보내는 값은 신청자 유형 · 설립일('YYYY-MM-DD' 또는 "") · 기준일(today)뿐이다.
4. 자격 결과 · 업력 · 선택 공고를 함께 돌려준다 — 흐름이 한 번에 저장한다.

- 판정 규칙(확실히 안 되는 경우만 불통과, 읽지 못한 조건은 통과 + 확인 필요, 접수기간 · 모집 상태 미판정)은 공고 서버에 있다.
- 공고 없음(상세 · 판정 어느 쪽이든)은 tools 안에서 값으로 받아(성공한 호출, 재시도 없음) 공용 예외 ResourceNotFound를
  올린다. 흐름이 X-C2-GONE으로 처리한다(4.3.4). 메시지에 공고 ID를 넣지 않는다.
- ToolCallExhausted는 받지 않고 올려 보낸다. 저장소 · DB · RunContext에 접근하지 않는다.
"""
from __future__ import annotations

import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Callable

from pydantic import ValidationError

from ...contracts.tasks import G01In, G01Out
from ...models import Announcement, CompanyInfo, EligibilityRule, GateResult
from ...orchestrator.errors import ResourceNotFound
from ...orchestrator.tools import Tools
from ..form_defaults import default_evaluation_items, default_form_spec
from .client import NOT_FOUND, NoticeClient
from .convert import (
    bad, first_text, from_validation, obj, opt_count, opt_date, opt_str, period_label, req, req_bool,
    req_str, req_str_list,
)

PRE_STARTUP = "예비창업자"
CONDITION_NAMES = frozenset({"지원대상 유형", "업력"})   # 판정 조건 이름 (spec 3.2.2)
# 모집 상태 (spec 4.4) — open → '모집중', closed → '마감', 그 밖(unknown 등) → '모집중' (기준 문서 v1.10 시트 4 Announcement.status)
STATUS_OPEN, STATUS_CLOSED = "모집중", "마감"


def business_age_years(months: int) -> float:
    """업력(년) = 업력 개월 / 12를 소수 한 자리로 반올림(사사오입, spec 4.3.2). round()는 짝수 맞춤이라 쓰지 않는다."""
    return float((Decimal(months) / Decimal(12)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def to_announcement(data: Any, notice_id: str) -> Announcement:
    """공고 상세 → Announcement (spec 4.4). 양식 · 평가 항목은 기본 양식(잠정), 요약 벡터는 받지 않는다([]).

    spec 3.2.1의 키는 모두 있어야 한다(값은 null일 수 있다). 키가 없어도 되는 것은 bonus_info · apply_period_type뿐.
    source · url · apply_url은 Announcement에 자리가 없어 쓰지 않지만 약속한 키라 있는지만 본다.
    """
    d = obj(data, "notice")
    if req_str(d, "notice_id", "notice", nonempty=True) != notice_id:
        raise bad("notice.notice_id (요청한 공고와 다름)")
    for key in ("source", "url", "apply_url"):
        req(d, key, "notice")
    el = obj(req(d, "eligibility", "notice"), "notice.eligibility")
    max_months = opt_count(el, "business_age_max_months", "notice.eligibility")
    status = req(d, "recruitment_status", "notice")
    try:
        return Announcement(
            announcement_id=notice_id,
            title=req_str(d, "title", "notice"),
            agency=first_text(d, ("organizer", "supervising_org", "executing_org"), "notice", "-"),
            support_field=opt_str(d, "category", "notice") or "",   # 분류 문자열 그대로 (기준 문서 두 값으로 바꾸지 않음)
            apply_start=opt_date(d, "apply_start", "notice"),
            apply_end=opt_date(d, "apply_end", "notice"),
            status=STATUS_CLOSED if status == "closed" else STATUS_OPEN,
            eligibility=EligibilityRule(
                applicant_types=req_str_list(el, "applicant_types", "notice.eligibility"),
                business_age_max_years=None if max_months is None else max_months / 12),
            eligibility_parsed=req_bool(el, "parsed", "notice.eligibility"),
            support_amount_max=opt_count(d, "support_amount_max_won", "notice"),
            support_amount_text=opt_str(d, "support_amount_text", "notice"),
            form_spec=default_form_spec(),
            evaluation_items=default_evaluation_items(),
            summary_embedding=[],
            bonus_info=opt_str(d, "bonus_info", "notice", missing_ok=True),   # 키가 없거나 null이면 null (4.4)
            apply_period_type=period_label(d.get("apply_period_type")),
        )
    except ValidationError as e:
        raise from_validation("notice", e) from None


def _conditions(d: dict[str, Any], key: str) -> list[str]:
    names = req_str_list(d, key, "eligibility")
    if any(n not in CONDITION_NAMES for n in names):
        raise bad(f"eligibility.{key}")
    return names


def to_gate(data: Any, *, business: bool) -> tuple[GateResult, float | None]:
    """자격 판정 → (GateResult, 업력(년)). missingInputs는 비고 undecidable은 늘 거짓이다.

    업력(년)은 예비창업자(business 거짓)면 null, 사업자면 business_age_months / 12(사사오입), 개월이 null이면 null.
    네 키(passed · failed_conditions · unknown_conditions · business_age_months)는 모두 있어야 한다.
    """
    d = obj(data, "eligibility")
    gate = GateResult(
        passed=req_bool(d, "passed", "eligibility"),
        failed_conditions=_conditions(d, "failed_conditions"),
        missing_inputs=[],
        undecidable=False,
        unknown_conditions=_conditions(d, "unknown_conditions"),
    )
    months = opt_count(d, "business_age_months", "eligibility")
    if not business or months is None:
        return gate, None
    try:
        years = business_age_years(months)
    except (InvalidOperation, OverflowError):        # 터무니없이 큰 개월 수 — 약속 밖
        raise bad("eligibility.business_age_months") from None
    if not math.isfinite(years):
        raise bad("eligibility.business_age_months")
    return gate, years


def eligibility_request(company: CompanyInfo, today: date) -> dict[str, str]:
    """자격 판정 요청 본문 — 신청자 유형 · 설립일 · 기준일뿐."""
    return {
        "applicant_type": company.applicant_type,
        "founded_at": company.founded_at.isoformat() if company.founded_at else "",
        "today": today.isoformat(),
    }


def make_g01(client: NoticeClient) -> Callable[[G01In, Tools], G01Out]:
    """공고 서버에 연결한 G-01 함수를 만든다 — registry.bind("G-01", make_g01(client))."""

    def run(inp: G01In, tools: Tools) -> G01Out:
        aid = inp.announcement_id

        def detail(timeout: float) -> Announcement | Any:
            data = client.notice(aid, timeout)
            return data if data is NOT_FOUND else to_announcement(data, aid)
        ann = tools.search("공고 상세", detail)
        if ann is NOT_FOUND:
            raise ResourceNotFound("공고 없음 — 공고 상세")
        company = inp.company_info
        business = company.applicant_type != PRE_STARTUP
        if business and company.founded_at is None:   # 판정 API를 부르지 않는다 (spec 4.3.2 ②)
            missing = GateResult(passed=False, failed_conditions=[], missing_inputs=["foundedAt"], undecidable=False)
            return G01Out(gate_result=missing, business_age_years=None, selected_announcement=ann)
        body = eligibility_request(company, inp.today)

        def judge(timeout: float) -> tuple[GateResult, float | None] | Any:
            data = client.eligibility(aid, body, timeout)
            return data if data is NOT_FOUND else to_gate(data, business=business)
        judged = tools.search("자격 판정", judge)
        if judged is NOT_FOUND:
            raise ResourceNotFound("공고 없음 — 자격 판정")
        gate, age = judged
        return G01Out(gate_result=gate, business_age_years=age, selected_announcement=ann)

    return run
