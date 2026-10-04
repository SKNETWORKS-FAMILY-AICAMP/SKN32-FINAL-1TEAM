"""조율 Agent 구현. 지금은 T-C1(요구사항 해석) · T-C3(작업 분해)이 있고 나머지 조율 Task는 스텁을 쓴다.

조율은 7개 Agent 중 하나다. Orchestrator(뼈대)가 아니다.
"""
from __future__ import annotations

from ...orchestrator.registry import TaskRegistry
from . import tc1, tc3  # noqa: F401

# 실제로 구현된 조율 Task — 워커 조립(build_app)이 이 Task만 실제 호출처(OpenAI)로 보낸다
IMPLEMENTED = {"T-C1": tc1.run, "T-C3": tc3.run}
IMPLEMENTED_TASKS = frozenset(IMPLEMENTED)


def bind_supervisor(registry: TaskRegistry) -> None:
    """구현된 조율 Task로 스텁을 바꿔 끼운다."""
    for task_id, fn in IMPLEMENTED.items():
        registry.bind(task_id, fn)
