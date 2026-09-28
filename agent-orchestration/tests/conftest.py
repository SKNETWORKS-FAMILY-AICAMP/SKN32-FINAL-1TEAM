from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbrain.agents.stubs import StubScenario  # noqa: E402
from sbrain.bootstrap import App, build_stub_app  # noqa: E402
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
