"""Agent 등록부와 Task 등록부.

- Agent 등록부: 호출 설정 찾기. 값은 관리자 설정값의 Task별 설정(Settings.tasks, 키 = Task ID 등 흐름이 정한 설정 키)에서
  온다. 옛 설정 사본(tasks 없음)이면 Agent별 설정(Settings.agents)에서 Agent 이름으로 찾는다.
- Task 등록부: 담당 Agent, 입출력 규격, 실행 함수, 제한 시간, 온도 덮어쓰기,
  실패 정책, 재수행 여부 · 확정 동작 예외 여부, LLM 사용 여부, 입력 연결.
- Orchestrator는 Task를 부를 때 그 Task 설정(호출 기록의 Agent 이름은 담당 Agent)을 입힌 tools를 Task 함수에 넘긴다.
  규칙 단계 · 합치기는 tools를 받지 않으며 담당 Agent는 기록용이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from ..models.base import SBModel
from .settings import AgentSetting, Settings, TaskModelSetting

StepKind = Literal["task", "rule", "merge"]

AGENTS: tuple[str, ...] = ("조율", "전략", "작성", "구현", "검증-1", "검증-2", "검수")


@dataclass(frozen=True)
class TempRule:
    """온도 덮어쓰기. fixed가 있으면 그 값, max가 있으면 Agent 기본 온도를 그 값 이하로 자른다.

    Agent 설정에 온도가 없으면(추론 모델) 덮어쓰지 않고 None을 돌려준다 (잠정).
    """
    fixed: float | None = None
    max: float | None = None

    def apply(self, base: float | None) -> float | None:
        if base is None:
            return None
        if self.fixed is not None:
            return self.fixed
        if self.max is not None:
            return min(base, self.max)
        return base


@dataclass(frozen=True)
class FailurePolicy:
    """재시도를 다 쓴 뒤의 처리 (R-11)."""
    resumable: bool = True                   # Task 단위 재개 여부 (T-C1 · T-C2는 재개하지 않음)
    fallback_in_task: bool = False           # Task 함수가 tools 예외를 받아 대체 경로로 감 (T-C2 · T-V2)
    keep_original_per_item: bool = False     # 호출 실패 문장은 원문 유지 (T-P2)
    on_step_error: Literal["fail", "continue"] = "fail"
    # 규칙 단계 · 합치기의 오류 처리. 기본 'fail' = 운영 오류로 실행 실패, 재작성 중이면 재작성 실패 (잠정)
    # G-04는 오류 시 계속. 자체 검사 불통과는 재수행 횟수까지 다시 만들고 관리자 기록 후 계속 (점수 밖)
    rescue_segments: frozenset[str] = frozenset()
    # 실패를 흐름에 넘기는 구간 (확장). 실행 건의 구간(Run.segment)이 여기 있으면 이 단계가 어떤 오류로 끝나든
    # (재시도 소진 · 코드 오류 · 규격 위반 · 대상 없음) 재개 · 실행 실패 대신 Flow.on_rescue가 받아 처리한다.
    # 비어 있거나 다른 구간이면 위 정책 그대로다. 구간 이름은 워크플로가 정한다.


@dataclass(frozen=True)
class Bind:
    """Task 입력 하나를 어디서 가져오는지.

    kind:
      art      — 산출물(key, 선택적으로 속성 경로 path)
      setting  — 설정값 스냅샷 경로 (예: 'scoring.threshold')
      run      — Run 필드 (예: 'rework_usage')
      cmd      — 현재 구간을 연 사용자 명령 산출물의 필드
      instr    — 작업 계획(taskPlan)에서 이 Task의 지시문
      rework   — 이번 실행의 재작성 · 재수행 입력
      checks   — 이번 구간 · 사이클의 check 목록
      today    — 기준일자
      const    — 상수 공급처 (예: rubric)
      flow     — 워크플로가 만들어 주는 값 (예: cycleInfo)
      partial  — 재개 때 이어 쓸 받은 결과 (확장). 재개 위치(RedoState.partial_ref)에 저장된 결과가 있으면 그 값,
                 없으면 값을 넣지 않아 입력 모델의 기본값을 쓴다. 이 종류로 연결한 Task만 저장 · 재개 장치를 쓴다
    """
    kind: str
    key: str = ""
    path: str = ""
    optional: bool = False
    default: Any = None


def art(key: str, path: str = "", optional: bool = False) -> Bind:
    return Bind("art", key, path, optional)


def setting(path: str) -> Bind:
    return Bind("setting", path)


def run_field(name: str) -> Bind:
    return Bind("run", name)


def cmd(name: str, default: Any = None) -> Bind:
    return Bind("cmd", name, optional=True, default=default)


def const(name: str) -> Bind:
    return Bind("const", name)


def flow_value(name: str) -> Bind:
    return Bind("flow", name, optional=True)


INSTR = Bind("instr")
REWORK = Bind("rework", optional=True)
CHECKS = Bind("checks", optional=True)
TODAY = Bind("today")
# 재개 때 받은 결과 이어 쓰기 (확장) — 재시도 소진(ToolCallExhausted.partial)으로 재개를 예약할 때 '<taskId>.partial'로
# 저장하고 재개하면 이 연결의 입력에 넣는다. 산출물 타입은 워크플로가 접미 규칙으로 등록한다
PARTIAL = Bind("partial", optional=True)
PARTIAL_SUFFIX = ".partial"


def keeps_partial(spec: "TaskSpec") -> bool:
    """입력 하나를 PARTIAL 종류로 연결한 Task인지 (받은 결과를 재개 때 이어 쓰는 Task)."""
    return any(b.kind == "partial" for b in spec.inputs.values())


@dataclass
class TaskSpec:
    task_id: str
    name: str
    agent: str
    kind: StepKind
    input_model: type[SBModel]
    output_model: type[SBModel]
    inputs: dict[str, Bind]
    outputs: dict[str, str]                      # 출력 필드 → 산출물 키
    primary_output: str                          # AttemptRef.resultRef가 가리킬 출력 필드
    order: int | None = None                     # 시트 2 F열 실행 순서 (합치기 · R-8은 None)
    counted: bool = False                        # 기획서 4-4 고정 Task 14개에 계상되는지
    uses_llm: bool = False
    temperature: TempRule | None = None
    failure: FailurePolicy = field(default_factory=FailurePolicy)
    redo: bool = False                           # 검사 미통과 재수행 대상
    final_action_exception: bool = False         # 확정 동작 예외 여섯 곳
    fn: Callable[..., Any] | None = None         # 실행 함수 (bind로 교체)

    @property
    def receives_tools(self) -> bool:
        return self.kind == "task"


class AgentRegistry:
    """Agent 등록부 — 설정 스냅샷에서 호출 설정(호출처 · 모델 · 기본 온도 · 추론 강도 · 이미지 설정)을 꺼낸다."""

    def __init__(self, agents: tuple[str, ...] = AGENTS) -> None:
        self.agents = agents

    def lookup(self, settings: Settings, agent_name: str, key: str) -> TaskModelSetting | AgentSetting:
        """설정 키(key)의 Task별 설정. 옛 설정 사본(tasks가 None)이면 Agent 이름(agent_name)의 Agent별 설정.

        옛 Agent별 설정에는 이미지 설정이 없다. 항목이 없으면 KeyError로 크게 실패한다."""
        if settings.tasks is not None:
            if key not in settings.tasks:
                raise KeyError(f"Task 설정 없음: {key}")
            return settings.tasks[key]
        if not settings.agents or agent_name not in settings.agents:
            raise KeyError(f"Agent 설정 없음(옛 설정 사본): {agent_name}")
        return settings.agents[agent_name]


class TaskRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, TaskSpec] = {}

    def register(self, spec: TaskSpec) -> None:
        if spec.task_id in self._specs:
            raise ValueError(f"중복 등록: {spec.task_id}")
        if spec.outputs and spec.primary_output not in spec.outputs:
            raise ValueError(f"{spec.task_id}: primary_output이 outputs에 없음")
        self._specs[spec.task_id] = spec

    def bind(self, task_id: str, fn: Callable[..., Any]) -> None:
        self._specs[task_id].fn = fn

    def get(self, task_id: str) -> TaskSpec:
        return self._specs[task_id]

    def has(self, task_id: str) -> bool:
        return task_id in self._specs

    def specs(self) -> list[TaskSpec]:
        return list(self._specs.values())

    def artifact_types(self) -> dict[str, Any]:
        """산출물 키 → 타입 (저장소에서 JSON을 복원할 때 쓴다)."""
        types: dict[str, Any] = {}
        for spec in self._specs.values():
            for fname, key in spec.outputs.items():
                types[key] = spec.output_model.model_fields[fname].annotation
        return types
