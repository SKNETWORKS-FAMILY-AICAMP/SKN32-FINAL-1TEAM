"""조율 Agent 구현. 지금은 T-C1(요구사항 해석)만 있고 나머지 조율 Task는 스텁을 쓴다.

조율은 7개 Agent 중 하나다. Orchestrator(뼈대)가 아니다.
"""
from __future__ import annotations

from ...orchestrator.registry import TaskRegistry
from . import tc1  # noqa: F401


def bind_supervisor(registry: TaskRegistry) -> None:
    """구현된 조율 Task로 스텁을 바꿔 끼운다."""
    registry.bind("T-C1", tc1.run)
