from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbrain.agents.stubs import StubScenario  # noqa: E402
from sbrain.bootstrap import App, build_stub_app  # noqa: E402
from sbrain.intake import ProjectInputRecord  # noqa: E402
from sbrain.models import PreInput  # noqa: E402


class Clock:
    def __init__(self, start: datetime = datetime(2026, 9, 26, 9, 0, 0)) -> None:
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(milliseconds=1)
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


def pre_input(**over) -> PreInput:
    base = dict(
        idea_text="동네 헬스장 회원 관리 서비스", applicant_type="법인", representative_name="김서준",
        representative_career=["헬스장 운영 5년"], founded_at=date(2025, 3, 2), revenue_unit_price=35000,
        development_period="6개월", team_careers=["개발자 1명"], birth_date=date(1990, 1, 1), gender="남",
        region="서울", industry_code="J62", hiring_plan="없음", facilities="없음", partners="없음",
        business_reg_no="123-45-67890", self_fund_amount=10_000_000,
    )
    base.update(over)
    return PreInput(**base)


def project_record(*, company: dict | None = None, project: dict | None = None,
                   plan: dict | None = None, **over) -> ProjectInputRecord:
    """create_project가 법인 신청자의 폼을 저장했을 때의 웹 DB 행 (app_schema.sql 컬럼)."""
    base = dict(
        project={**dict(project_id=101, company_id=11, description="동네 헬스장 회원 관리 서비스",
                        output_summary="회원 관리 웹 서비스 1종", tech_field="정보통신",
                        regional_priority_area=None, archived_at=None), **(project or {})},
        company={**dict(company_id=11, user_id=7, applicant_type="corp", biz_type="서비스업", ceo_name="김서준",
                        founded_at=date(2025, 3, 2), company_name="헬스온", business_reg_no="123-45-67890",
                        rep_type="단독"), **(company or {})},
        team_members=[dict(name="이하늘", role="개발", experience="웹 개발 3년"),
                      dict(name="박지우", role=None, experience=None)],
        pricing_items=[dict(service_name="월 구독", unit_price=Decimal("35000.00")),
                       dict(service_name="연 구독", unit_price=Decimal("350000.00"))],
        plan_input={**dict(
            ceo_birth_date=date(1990, 1, 1), ceo_gender="남", region_sido="서울특별시", region_sigungu="마포구",
            main_industry="정보·통신", main_industry_free=None, certifications=["노란우산공제"],
            ceo_careers=[{"type": "경력", "content": "OO피트니스 운영", "period": "5년", "proof": True}],
            ceo_capability="헬스장 운영 노하우", occupation=None,
            dev_start_month="2026-03", dev_end_month="2026-12", budget_scale_manwon=None,
            self_funding_allowed=True, self_cash_limit=10_000_000, self_in_kind_resources="사무실 1곳",
            no_hires=True, hires=[], no_equipment=False,
            equipment=[{"name": "태블릿", "status": "보유"}], no_partners=True, partners=[]), **(plan or {})},
    )
    base.update(over)
    return ProjectInputRecord.model_validate(base)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make_app(clock: Clock, scenario: StubScenario | None = None, **kw) -> App:
    return build_stub_app(scenario or StubScenario(), now=clock, **kw)


def start_and_select(app: App, account: str = "acc-1", announcement: str = "A01") -> str:
    res = app.orchestrator.start_run(account, pre_input())
    assert res.ok, res
    rid = res.run_id
    app.orchestrator.select_announcement(rid, announcement)
    app.orchestrator.advance(rid)
    return rid


def to_screen6(app: App, account: str = "acc-1") -> str:
    rid = start_and_select(app, account)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    return rid


def to_screen8(app: App, account: str = "acc-1") -> str:
    rid = to_screen6(app, account)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    return rid


def to_screen9(app: App, account: str = "acc-1") -> str:
    rid = to_screen8(app, account)
    app.orchestrator.decide(rid, 8, "진행")
    return rid


def executed(app: App, rid: str) -> list[str]:
    return [r.task_id for r in app.store.executions(rid)]
