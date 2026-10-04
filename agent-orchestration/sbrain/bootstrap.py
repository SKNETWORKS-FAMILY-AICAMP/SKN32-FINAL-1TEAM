"""구성 조립 — 저장소 · 등록부 · 워크플로 · 엔진 · 명령 창구를 한곳에서 묶는다.

| 함수 | 쓰는 곳 | 저장소 · 입력 · 설정 | Agent |
|---|---|---|---|
| build_stub_app | 테스트 · 시연 | 메모리(또는 주어진 저장소) · 기본 설정 | 전부 스텁, 가짜 LLM, 지시문 다시 쓰기 없음(덧붙이기만) |
| build_app | 워커 (sbrain/worker.py) | 공유 MySQL — SqlStore · SqlProjectInputSource · DbSettingsProvider | 조율 T-C1 · T-C3 실구현과 재작성 · 재수행 지시문 다시 쓰기(OpenAI), T-C2 · G-01은 SBRAIN_NOTICE_API_URL이 있으면 공고 서버 연결(실제 모드) · 없으면 스텁, 나머지 스텁 |
| build_web | 웹 서버 | 공유 MySQL — 같음 | 단계를 돌지 않는다 (명령 · 조회만). 공고 서버를 부르지 않는다 |

실제 Agent 구현이 나오면 registry.bind(task_id, fn)로 스텁을 교체한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .agents.notice import NoticeClient, Transport, bind_notice
from .agents.stubs import FakeLLM, StubScenario, bind_stubs, make_constants
from .agents.supervisor import IMPLEMENTED_TASKS, bind_supervisor
from .agents.supervisor.plan import PURPOSE_REWRITE
from .agents.supervisor.rewrite import rewrite_guidance
from .env import get_env
from .flow import IMMUTABLE_KEYS, SBrainFlow, SBrainOrchestrator, artifact_types, build_registry
from .flow.sbrain_flow import REWRITE_AGENT, GuidanceRewriter
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
    """구현이 들어온 호출만 실제 호출처로, 나머지(스텁 Task)는 가짜 호출처로 보낸다 (잠정, T-C3 spec 6.1).

    호출처는 Agent마다 정해지므로, 그대로 두면 스텁 Task도 실제 OpenAI를 부른다. 실제 호출처로 보내는 규칙:
    - 호출 기록의 task_id가 real_tasks(조율 구현 Task — T-C1 · T-C3)에 있으면 실제.
    - 조율 Agent의 지시문 다시 쓰기(agent = 조율, purpose = PURPOSE_REWRITE)면 실제. 다시 쓰기는 대상 Task의 실행 기록
      안에서 불려 task_id가 대상 Task(스텁 T-W1 등)이므로, Task ID만으로는 나눌 수 없어 agent · purpose로 본다.
    - 그 밖(스텁 Task 자신의 호출)은 가짜.
    각 Task 구현이 들어오면 real_tasks가 늘어난다.
    """

    def __init__(self, real: LLMProvider, fake: LLMProvider, real_tasks: frozenset[str]) -> None:
        self.real, self.fake, self.real_tasks = real, fake, real_tasks

    def is_real(self, request: LLMRequest) -> bool:
        meta = request.metadata
        if meta.get("task_id") in self.real_tasks:
            return True
        return meta.get("agent") == REWRITE_AGENT and meta.get("purpose") == PURPOSE_REWRITE

    def complete(self, request: LLMRequest):
        return (self.real if self.is_real(request) else self.fake).complete(request)


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
    notice_api_url: str | None = None,
    notice_transport: Transport | None = None,
) -> App:
    """워커 조립 — 공유 MySQL(SqlStore · SqlProjectInputSource · DbSettingsProvider), 조율 T-C1 · T-C3 실구현, OpenAI 호출처.

    - db_url이 없으면 SBRAIN_DB_URL(환경 변수 → .env)을 쓴다.
    - 흐름의 지시문 만들기에 조율 다시 쓰기(rewrite_guidance)를 끼운다 — 재작성 · 재수행 대상의 안내를 다시 쓴다.
    - 나머지 Agent는 스텁이다. 스텁 Task는 실제 호출처를 부르지 않는다(TaskRoutedProvider). 다시 쓰기 호출은 대상이
      스텁 Task여도 실제 호출처로 간다.
    - 공고 매칭(T-C2) · 자격 확인(G-01): 공고 서버 주소가 있으면 공고 서버 연결(agents/notice, 실제 모드), 없으면 스텁
      (스텁 모드 — 스텁 G-01이 스텁 공고를 만들고 판정한다, spec 3.1 · 4.6).
      주소는 notice_api_url, 주지 않으면(None) SBRAIN_NOTICE_API_URL(환경 변수 → .env). 빈 문자열이면 스텁이다.
      주소 형식이 틀리면 조립할 때 ValueError다(메시지에 주소를 싣지 않는다).
    - project_inputs · llm · notice_transport는 시험용으로 바꿔 끼울 때만 준다. llm이 없으면 OpenAIProvider(OPENAI_API_KEY),
      notice_transport가 없으면 표준 라이브러리 HTTP 전송.
    """
    from .intake.sql_source import SqlProjectInputSource
    from .orchestrator.openai_provider import OpenAIProvider
    from .store_sql import DbSettingsProvider, SqlStore, create_db_engine

    db = create_db_engine(_db_url(db_url))
    app = _assemble(
        store=SqlStore(db, now=now), settings=DbSettingsProvider(db, settings), scenario=StubScenario(), now=now,
        sleep=time.sleep, profile_count=lambda account_id: 1,   # 워커는 시작 확인(request_start)을 하지 않는다
        project_inputs=project_inputs or SqlProjectInputSource(db), stubs=True, rewriter=rewrite_guidance)
    bind_supervisor(app.registry)
    notice_url = get_env("SBRAIN_NOTICE_API_URL") if notice_api_url is None else notice_api_url
    if notice_url:   # 실제 모드 — 공고 서버 연결로 스텁 T-C2 · G-01을 바꾼다
        bind_notice(app.registry, NoticeClient(notice_url, transport=notice_transport))
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
              project_inputs: ProjectInputSource | None, stubs: bool,
              rewriter: GuidanceRewriter | None = None) -> App:
    registry = build_registry()
    llm = FakeLLM()
    if stubs:
        bind_stubs(registry, scenario, now=now)
        providers: dict[str, LLMProvider] = {name: llm for name in ("openai", "gpu-server", "미정")}
    else:
        providers = {name: NoProvider() for name in ("openai", "gpu-server", "미정")}
    # 지시문 다시 쓰기는 워커 조립만 끼운다. 없으면(스텁 · 웹 조립) 재작성 · 재수행 문제를 덧붙이기만 한다
    flow = SBrainFlow(registry, constants=make_constants(), now=now, rewriter=rewriter)
    exact, suffix = artifact_types(registry)
    engine = Engine(store=store, registry=registry, flow=flow, providers=providers,
                    types=ArtifactTypes(exact, suffix), immutable_keys=IMMUTABLE_KEYS, now=now, sleep=sleep)
    flow.engine = engine
    # 공고 선택 명령은 고른 ID만 남긴다 — 공고 상세는 워커의 G-01이 받는다 (명령 창구에 공고 공급처가 없다)
    orch = SBrainOrchestrator(
        engine=engine, flow=flow, settings=settings,
        profile_count=profile_count, project_inputs=project_inputs, now=now, sleep=sleep)
    return App(orch, engine, store, registry, llm, scenario, settings)
