"""구성 조립 — 저장소 · 등록부 · 워크플로 · 엔진 · 명령 창구를 한곳에서 묶는다.

| 함수 | 쓰는 곳 | 저장소 · 입력 · 설정 | Agent |
|---|---|---|---|
| build_stub_app | 테스트 · 시연 | 메모리(또는 주어진 저장소) · 기본 설정 | 전부 스텁, 가짜 LLM |
| build_app | 워커 (sbrain/worker.py) | 공유 MySQL — SqlStore · SqlProjectInputSource · DbSettingsProvider | 조율 T-C1 실구현(OpenAI), 나머지 스텁 |
| build_web | 웹 서버 | 공유 MySQL — 같음 | 단계를 돌지 않는다 (명령 · 조회만) |

실제 Agent 구현이 나오면 registry.bind(task_id, fn)로 스텁을 교체한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .agents.stubs import FakeLLM, StubScenario, bind_stubs, make_announcement, make_constants
from .agents.supervisor import IMPLEMENTED_TASKS, bind_supervisor
from .env import get_env
from .flow import IMMUTABLE_KEYS, SBrainFlow, SBrainOrchestrator, artifact_types, build_registry
from .intake import ProjectInputSource
from .orchestrator import ArtifactTypes, Engine, MemoryStore, Settings, SettingsProvider
from .orchestrator.registry import TaskRegistry
from .orchestrator.store import Store
from .orchestrator.tools import LLMProvider, LLMRequest


@dataclass
class App:
    orchestrator: SBrainOrchestrator
    engine: Engine
    store: Store
    registry: TaskRegistry
    llm: FakeLLM
    scenario: StubScenario
    settings: SettingsProvider


class TaskRoutedProvider:
    """구현이 들어온 Task만 실제 호출처로, 나머지(스텁)는 가짜 호출처로 보낸다 (잠정).

    조율 Agent는 T-C1만 구현됐다. 호출처는 Agent마다 정해지므로, 그대로 두면 같은 Agent의 스텁 Task(T-C3 등)도
    실제 OpenAI를 부른다. 각 Task 구현이 들어오면 real_tasks가 늘어난다.
    """

    def __init__(self, real: LLMProvider, fake: LLMProvider, real_tasks: frozenset[str]) -> None:
        self.real, self.fake, self.real_tasks = real, fake, real_tasks

    def complete(self, request: LLMRequest):
        target = self.real if request.metadata.get("task_id") in self.real_tasks else self.fake
        return target.complete(request)


class NoProvider:
    """웹 프로세스용 — LLM을 부르지 않는다. 단계 진행은 워커가 한다."""

    def complete(self, request: LLMRequest):
        raise RuntimeError("웹 프로세스는 LLM을 부르지 않는다 — 사전 단계 · 진행 · 재개는 워커가 한다")


def build_stub_app(
    scenario: StubScenario | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], datetime] = datetime.now,
    profile_count: Callable[[str], int] = lambda account_id: 1,
    project_inputs: ProjectInputSource | None = None,
    store: Store | None = None,
) -> App:
    """스텁 Agent와 메모리 저장소로 뼈대 전체를 조립한다 (테스트 · 시연용).

    project_inputs를 주면 start_run_for_project로 웹 DB에 저장된 사전 정보를 읽어 시작할 수 있다.
    store를 주면 그 저장소를 쓴다(예: SqlStore). 없으면 메모리 저장소.
    """
    return _assemble(
        store=store if store is not None else MemoryStore(now=now), settings=SettingsProvider(settings),
        scenario=scenario or StubScenario(), now=now, sleep=lambda s: None, profile_count=profile_count,
        project_inputs=project_inputs, stubs=True)


def build_app(
    db_url: str | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], datetime] = datetime.now,
    project_inputs: ProjectInputSource | None = None,
    llm: LLMProvider | None = None,
) -> App:
    """워커 조립 — 공유 MySQL(SqlStore · SqlProjectInputSource · DbSettingsProvider), 조율 T-C1 실구현, OpenAI 호출처.

    - db_url이 없으면 SBRAIN_DB_URL(환경 변수 → .env)을 쓴다.
    - 나머지 Agent는 스텁이다. 스텁 Task는 실제 호출처를 부르지 않는다(TaskRoutedProvider).
    - 공고 조회(선택한 공고 · 자격 조건)는 공고팀 연동 전까지 스텁 공고를 쓴다 (잠정).
    - project_inputs · llm은 시험용으로 바꿔 끼울 때만 준다. llm이 없으면 OpenAIProvider(OPENAI_API_KEY).
    """
    from .intake.sql_source import SqlProjectInputSource
    from .orchestrator.openai_provider import OpenAIProvider
    from .store_sql import DbSettingsProvider, SqlStore, create_db_engine

    db = create_db_engine(_db_url(db_url))
    app = _assemble(
        store=SqlStore(db, now=now), settings=DbSettingsProvider(db, settings), scenario=StubScenario(), now=now,
        sleep=time.sleep, profile_count=lambda account_id: 1,   # 워커는 시작 확인(request_start)을 하지 않는다
        project_inputs=project_inputs or SqlProjectInputSource(db), stubs=True)
    bind_supervisor(app.registry)
    app.engine.providers["openai"] = TaskRoutedProvider(llm or OpenAIProvider(), app.llm, IMPLEMENTED_TASKS)
    return app


def build_web(
    db_url: str | None = None,
    *,
    profile_count: Callable[[str], int],
    settings: Settings | None = None,
    now: Callable[[], datetime] = datetime.now,
    project_inputs: ProjectInputSource | None = None,
) -> App:
    """웹 서버 조립 — 명령 · 조회 함수만 쓰는 SBrainOrchestrator. LLM 호출처가 없고 단계를 돌지 않는다.

    profile_count: 계정의 필수 항목을 채운 프로필 수 (0이면 E-AUTH-PROFILE). 웹은 compute_has_profile을 넘긴다(참 = 1).
    웹은 request_start · start_status · 명령 · 조회 · 중단만 부른다. run_start_request · advance · tick은 워커가 부른다.
    사전 단계를 막는 장치: run_start_request(와 동기 경로 start_run · start_run_for_project)는 시작 요청을 건드리지 않고
    바로 CommandError("WEB_NOT_ALLOWED")다 (allow_pre_stage = False).
    """
    from .intake.sql_source import SqlProjectInputSource
    from .store_sql import DbSettingsProvider, SqlStore, create_db_engine

    db = create_db_engine(_db_url(db_url))
    app = _assemble(
        store=SqlStore(db, now=now), settings=DbSettingsProvider(db, settings), scenario=StubScenario(), now=now,
        sleep=time.sleep, profile_count=profile_count, project_inputs=project_inputs or SqlProjectInputSource(db),
        stubs=False)
    app.engine.stop_requested = lambda: True   # 실수로 advance를 불러도 단계를 돌지 않는다
    app.orchestrator.allow_pre_stage = False   # 사전 단계(run_start_request)는 WEB_NOT_ALLOWED — 워커가 돈다
    return app


def _db_url(db_url: str | None) -> str:
    url = db_url or get_env("SBRAIN_DB_URL")
    if not url:
        raise RuntimeError("SBRAIN_DB_URL이 없다 — 환경 변수 또는 agent-orchestration/.env에 공유 MySQL 접속 URL을 넣는다")
    return url


def _assemble(*, store: Store, settings: SettingsProvider, scenario: StubScenario, now: Callable[[], datetime],
              sleep: Callable[[float], None], profile_count: Callable[[str], int],
              project_inputs: ProjectInputSource | None, stubs: bool) -> App:
    registry = build_registry()
    llm = FakeLLM()
    if stubs:
        bind_stubs(registry, scenario, now=now)
        providers: dict[str, LLMProvider] = {name: llm for name in ("openai", "gpu-server", "미정")}
    else:
        providers = {name: NoProvider() for name in ("openai", "gpu-server", "미정")}
    flow = SBrainFlow(registry, constants=make_constants(), now=now)
    exact, suffix = artifact_types(registry)
    engine = Engine(store=store, registry=registry, flow=flow, providers=providers,
                    types=ArtifactTypes(exact, suffix), immutable_keys=IMMUTABLE_KEYS, now=now, sleep=sleep)
    flow.engine = engine
    orch = SBrainOrchestrator(
        engine=engine, flow=flow, settings=settings,
        # 공고 조회 — 공고팀 연동 전까지 스텁 공고 (잠정)
        announcements=lambda aid: make_announcement(aid, now().date(), eligible=aid not in scenario.gate_fail_ids),
        profile_count=profile_count, project_inputs=project_inputs, now=now, sleep=sleep)
    return App(orch, engine, store, registry, llm, scenario, settings)
