"""구현 · 검증-2 실구현 Task 등록 (spec 4.10) — 워커 조립(build_app)이 bind_partner_bv로 스텁을 바꿔 끼운다.

- T-B1 실행 파일 · T-B2 인포그래픽(engineering_agent/tasks.py) · T-V2 산출물층 검증(verification_agent/tasks.py) —
  담당자 tasks.py의 Task 함수를 지금 계약(파일 참조 FileRef · tools.files)으로 고친 것이다(VENDORED.md 4절).
- 스텁 조립 · 테스트 조립은 그대로 스텁이다(테스트는 bind_partner_bv(app.registry)로 바꿔 끼운다 — partner_sw와 같음).
- 워커 조립은 이 Task들의 LLM 호출을 실제 호출처로 보내고(bootstrap.TaskRoutedProvider — 호출 기록의 task_id가
  IMPLEMENTED_TASKS에 있으면 실제), 이미지 호출은 IMAGE_TASKS(T-B2 — 아이콘판)만 실제 이미지 호출처로 보낸다
  (bootstrap.TaskRoutedImageProvider).

두 담당자 패키지는 서로 import하지 않는다. 이 파일(우리 연결 코드)만 둘을 함께 불러 등록한다.
"""
from __future__ import annotations

from ...orchestrator.registry import TaskRegistry
from .engineering_agent.tasks import run_tb1, run_tb2
from .verification_agent.tasks import run_tv2

IMPLEMENTED = {"T-B1": run_tb1, "T-B2": run_tb2, "T-V2": run_tv2}
IMPLEMENTED_TASKS = frozenset(IMPLEMENTED)
IMAGE_TASKS = frozenset({"T-B2"})   # 이미지 호출(tools.image)을 하는 실구현 Task — 실제 이미지 호출처로 보낸다


def bind_partner_bv(registry: TaskRegistry) -> None:
    """구현 · 검증-2 실구현으로 스텁을 바꿔 끼운다."""
    for task_id, fn in IMPLEMENTED.items():
        registry.bind(task_id, fn)
