from __future__ import annotations

import itertools
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mysqldb import require_mysql  # noqa: E402
from webdb import create_web_tables, new_project, set_training_consent  # noqa: E402

from sbrain import env  # noqa: E402
from sbrain.agents.stubs import StubScenario  # noqa: E402
from sbrain.bootstrap import App, build_stub_app  # noqa: E402
from sbrain.intake import ProjectInputRecord  # noqa: E402
from sbrain.models import PreInput  # noqa: E402
from sbrain.orchestrator import MemoryStore  # noqa: E402
from sbrain.orchestrator.store import Store  # noqa: E402
from sbrain.store_sql import SqlStore, create_orchestrator_tables, create_sqlite_engine  # noqa: E402

# ── 공고 서버 격리 ─────────────────────────────────────
# 개발 PC의 환경 변수나 agent-orchestration/.env에 SBRAIN_NOTICE_API_URL이 있어도 테스트가 실제 공고 서버를 부르지 않게,
# 모든 테스트에서 이 키 하나만 없는 것으로 본다. 다른 키(SBRAIN_TEST_MYSQL_URL 등)는 지금처럼 읽는다.
# 실제 모드를 시험할 때는 build_app(notice_api_url=…, notice_transport=가짜 전송)으로 넘기거나 그 테스트 안에서
# monkeypatch.setenv로 가짜 주소(http://example.invalid:8000)를 넣고 가짜 전송을 함께 준다.
NOTICE_URL_KEY = "SBRAIN_NOTICE_API_URL"


def isolate_notice_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경 변수와 .env의 SBRAIN_NOTICE_API_URL을 없는 것으로 본다 (테스트가 끝나면 monkeypatch가 되돌린다)."""
    monkeypatch.delenv(NOTICE_URL_KEY, raising=False)
    original = env.read_env_file
    if getattr(original, "without_notice_url", False):
        return

    def read_env_file(path=None) -> dict[str, str]:
        values = original(path)
        values.pop(NOTICE_URL_KEY, None)
        return values
    read_env_file.without_notice_url = True
    monkeypatch.setattr(env, "read_env_file", read_env_file)


@pytest.fixture(autouse=True)
def _no_real_notice_server(monkeypatch):
    isolate_notice_api(monkeypatch)


# ── 저장소 선택 ────────────────────────────────────────
# 흐름 테스트(clock을 쓰는 테스트)는 메모리 저장소와 SqlStore(SQLite)로 한 번씩 돈다.
# 저장소 계약 테스트(any_backend)는 MySQL 8도 돈다 — SBRAIN_TEST_MYSQL_URL이 없으면 건너뜀.
FLOW_STORES = ("memory", "sql")
CONTRACT_STORES = ("memory", "sql", "mysql")


def pytest_generate_tests(metafunc):
    if "store_backend" in metafunc.fixturenames:
        metafunc.parametrize("store_backend", FLOW_STORES, indirect=True)
    if "any_backend" in metafunc.fixturenames:
        metafunc.parametrize("any_backend", CONTRACT_STORES, indirect=True)


class Backend:
    """memory: MemoryStore · sql: SqlStore + SQLite 임시 파일 DB(웹 테이블 최소 정의 포함) · mysql: SqlStore + MySQL 8."""

    def __init__(self, kind: str, tmp_path: Path) -> None:
        self.kind = kind
        self._tmp = tmp_path
        self._count = 0
        if kind == "mysql":
            require_mysql()

    def make_store(self, now) -> Store:
        if self.kind == "memory":
            return MemoryStore(now=now)
        if self.kind == "mysql":
            return SqlStore(require_mysql(), now=now)
        self._count += 1   # 앱마다 따로인 DB (메모리 저장소와 같게)
        engine = create_sqlite_engine(self._tmp / f"sbrain-{self._count}.db", fast=True)
        create_orchestrator_tables(engine)
        create_web_tables(engine)
        return SqlStore(engine, now=now)


@pytest.fixture
def store_backend(request, tmp_path) -> Backend:
    return Backend(request.param, tmp_path)


@pytest.fixture
def any_backend(request, tmp_path) -> Backend:
    return Backend(request.param, tmp_path)


_memory_projects = itertools.count(5001)


def project_for(app: App, *, agreed: bool = False) -> str:
    """흐름 테스트용 프로젝트 ID. SqlStore면 웹 projects 행을 만든다(알림이 웹 notifications에 쓰이도록).

    agreed: 프로젝트 주인의 학습 데이터 편입 동의 (웹 users.ai_training_agreed, 메모리 저장소는 따로 기억).
    """
    if isinstance(app.store, SqlStore):
        return str(new_project(app.store.engine, agreed=agreed))
    pid = str(next(_memory_projects))
    app.store.set_training_consent(pid, agreed)
    return pid


def set_consent(app: App, rid: str, agreed: bool = True) -> None:
    """실행 건 프로젝트 주인의 학습 데이터 편입 동의를 바꾼다 (웹이 로그인마다 갱신하는 값)."""
    pid = app.store.load_run(rid).project_id
    if isinstance(app.store, SqlStore):
        set_training_consent(app.store.engine, int(pid), agreed)
    else:
        app.store.set_training_consent(pid, agreed)


class Clock:
    """고정 시계 — 부를 때마다 1밀리초씩 간다. 기본 시작은 2026-09-26 09:00 UTC(한국 18:00, 같은 날)."""

    def __init__(self, start: datetime = datetime(2026, 9, 26, 9, 0, 0, tzinfo=timezone.utc),
                 backend: Backend | None = None) -> None:
        self.t = start
        self.backend = backend

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
            ceo_careers=[{"type": "경력", "title": "OO피트니스 운영", "period": "5년", "has_proof": True}],
            ceo_capability="헬스장 운영 노하우", occupation=None,
            dev_start_month="2026-03", dev_end_month="2026-12", budget_scale_manwon=None,
            self_funding_allowed=True, self_cash_limit=10_000_000, self_in_kind_resources="사무실 1곳",
            no_hires=True, hires=[], no_equipment=False,
            equipment=[{"name": "태블릿", "status": "보유"}], no_partners=True, partners=[]), **(plan or {})},
    )
    base.update(over)
    return ProjectInputRecord.model_validate(base)


@pytest.fixture
def clock(store_backend) -> Clock:
    return Clock(backend=store_backend)


def make_app(clock: Clock, scenario: StubScenario | None = None, **kw) -> App:
    if "store" not in kw and clock.backend is not None:
        kw["store"] = clock.backend.make_store(clock)
    return build_stub_app(scenario or StubScenario(), now=clock, **kw)


def start_and_select(app: App, account: str = "acc-1", announcement: str = "A01") -> str:
    res = app.orchestrator.start_run(account, pre_input(), project_id=project_for(app))
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
