"""구성 조립 — 저장소 · 등록부 · 워크플로 · 엔진 · 명령 창구를 한곳에서 묶는다.

실제 Agent 구현이 나오면 registry.bind(task_id, fn)로 스텁을 교체한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .agents.stubs import FakeLLM, StubScenario, bind_stubs, make_announcement, make_constants
from .flow import IMMUTABLE_KEYS, SBrainFlow, SBrainOrchestrator, artifact_types, build_registry
from .intake import ProjectInputSource
from .orchestrator import ArtifactTypes, Engine, MemoryStore, Settings, SettingsProvider
from .orchestrator.registry import TaskRegistry


@dataclass
class App:
    orchestrator: SBrainOrchestrator
    engine: Engine
    store: MemoryStore
    registry: TaskRegistry
    llm: FakeLLM
    scenario: StubScenario
    settings: SettingsProvider


def build_stub_app(
    scenario: StubScenario | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], datetime] = datetime.now,
    profile_count: Callable[[str], int] = lambda account_id: 1,
    project_inputs: ProjectInputSource | None = None,
) -> App:
    """스텁 Agent와 메모리 저장소로 뼈대 전체를 조립한다 (테스트 · 시연용).

    project_inputs를 주면 start_run_for_project로 웹 DB에 저장된 사전 정보를 읽어 시작할 수 있다.
    """
    scenario = scenario or StubScenario()
    store = MemoryStore(now=now)
    registry = build_registry()
    bind_stubs(registry, scenario, now=now)
    llm = FakeLLM()
    providers = {name: llm for name in ("openai", "gpu-server", "미정")}
    flow = SBrainFlow(registry, constants=make_constants(), now=now)
    exact, suffix = artifact_types(registry)
    engine = Engine(store=store, registry=registry, flow=flow, providers=providers,
                    types=ArtifactTypes(exact, suffix), immutable_keys=IMMUTABLE_KEYS,
                    now=now, sleep=lambda s: None)
    flow.engine = engine
    provider = SettingsProvider(settings)
    orch = SBrainOrchestrator(
        engine=engine, flow=flow, settings=provider,
        announcements=lambda aid: make_announcement(aid, now().date(), eligible=aid not in scenario.gate_fail_ids),
        profile_count=profile_count, project_inputs=project_inputs, now=now)
    return App(orch, engine, store, registry, llm, scenario, provider)
