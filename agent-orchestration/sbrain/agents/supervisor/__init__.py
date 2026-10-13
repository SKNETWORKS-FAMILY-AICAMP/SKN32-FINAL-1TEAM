"""조율 Agent 구현. LLM Task T-C1(요구사항 해석) · T-C3(작업 분해)과 규칙 단계(판정 G-02a · G-02b, 안내 문서 G-04, 합치기
M-1 ~ M-4)가 있고 나머지 조율 Task(R-8 · T-C4)는 스텁을 쓴다. T-C2 · G-01은 공고 서버 연결(agents/notice)이다.

조율은 7개 Agent 중 하나다. Orchestrator(뼈대)가 아니다.

- IMPLEMENTED: LLM을 부르는 실구현 Task — 워커 조립(build_app)이 이 Task만 실제 호출처(OpenAI)로 보낸다.
- RULES: 규칙 단계 실구현(LLM 없음, tools를 받지 않음 — G-04만 파일 창구를 받는다). 워커 조립과 스텁 조립이 같은 한 벌을 쓴다
  (스텁 조립은 테스트용 실패 흉내만 감싼다 — agents/stubs.py D14). 호출처 나누기 대상이 아니다.
"""
from __future__ import annotations

from typing import Callable

from ...orchestrator.registry import TaskRegistry
from . import judge, merge, readme, tc1, tc3  # noqa: F401

# 실제로 구현된 조율 Task — 워커 조립(build_app)이 이 Task만 실제 호출처(OpenAI)로 보낸다
IMPLEMENTED = {"T-C1": tc1.run, "T-C3": tc3.run}
IMPLEMENTED_TASKS = frozenset(IMPLEMENTED)

# 규칙 단계 실구현 (LLM 없음) — 단계 ID → 함수
RULES: dict[str, Callable] = {
    "G-02a": judge.run_g02a, "G-02b": judge.run_g02b, "G-04": readme.run,
    "M-1": merge.run_m1, "M-2": merge.run_m2, "M-3": merge.run_m3, "M-4": merge.run_m4,
}
RULE_TASKS = frozenset(RULES)


def bind_rules(registry: TaskRegistry) -> None:
    """규칙 단계 실구현을 묶는다."""
    for task_id, fn in RULES.items():
        registry.bind(task_id, fn)


def bind_supervisor(registry: TaskRegistry) -> None:
    """구현된 조율 Task(LLM Task + 규칙 단계)로 스텁을 바꿔 끼운다."""
    for task_id, fn in IMPLEMENTED.items():
        registry.bind(task_id, fn)
    bind_rules(registry)
