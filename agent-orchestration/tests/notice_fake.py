"""가짜 공고 서버와 실제 T-C2 · G-01 실행 도움 — 공고 서버 연결 테스트가 함께 쓴다. 네트워크에 나가지 않는다.

FakeNoticeServer는 가짜 전송이다(공고 서버 네 API를 흉내 낸다). 주소는 가짜(FAKE_URL)만 쓴다.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import date
from typing import Any

from sbrain.agents.notice import NoticeClient, make_g01, make_tc2
from sbrain.contracts import tasks as c
from sbrain.models import CompanyInfo, ItemSpec, RevenueItem
from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import ToolCallExhausted
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext


FAKE_URL = "http://example.invalid:8000"
NOT_FOUND = (404, json.dumps({"code": "NOTICE_NOT_FOUND"}).encode())


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
                       now=utc_now, sleep=lambda s: None)
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


def format_detail(e: ToolCallExhausted) -> str:
    """재시도를 다 쓴 형식 오류의 마지막 상세 — FormatError 메시지(키 경로만)."""
    assert e.error == "형식오류"
    return e.detail
