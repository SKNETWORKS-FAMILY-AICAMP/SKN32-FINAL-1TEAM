"""전략 · 작성 · 검증-1 실구현 Task 등록 (spec 4.15) — 워커 조립(build_app)이 bind_partner_sw로 스텁을 바꿔 끼운다.

스텁 조립 · 테스트 조립은 그대로 스텁이다. 워커 조립은 이 Task들의 LLM 호출을 실제 호출처로 보낸다(bootstrap.TaskRoutedProvider —
호출 기록의 task_id가 IMPLEMENTED_TASKS에 있으면 실제). T-W3는 LLM을 부르지 않는다(규칙 코드).
"""
from __future__ import annotations

from ...orchestrator.registry import TaskRegistry
from .strategy import run_ts1, run_ts2
from .verify import run_tv1
from .writing import run_tw1, run_tw2, run_tw3

IMPLEMENTED = {"T-S1": run_ts1, "T-S2": run_ts2, "T-W1": run_tw1, "T-W2": run_tw2, "T-W3": run_tw3, "T-V1": run_tv1}
IMPLEMENTED_TASKS = frozenset(IMPLEMENTED)


def bind_partner_sw(registry: TaskRegistry) -> None:
    """전략 · 작성 · 검증-1 실구현으로 스텁을 바꿔 끼운다."""
    for task_id, fn in IMPLEMENTED.items():
        registry.bind(task_id, fn)
