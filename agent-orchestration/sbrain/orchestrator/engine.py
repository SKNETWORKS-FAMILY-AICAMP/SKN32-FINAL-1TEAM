"""실행 엔진 — Agent 종류와 무관한 공통 장치.

- 대기열(Run.queue)의 단계를 순서대로 실행하고, 단계가 끝날 때마다 한 번에 저장한다.
- 재수행 루프: check.passed=false면 횟수를 세고 문제 내용(ReworkInput)을 실어 같은 Task를 다시 부른다.
- 재시도는 tools가 호출 단위로 하고, 재시도를 다 쓰면 Task 단위로 재개한다(R-11).
- 실패를 흐름에 넘기기(확장): 실패 정책의 rescue_segments에 지금 구간이 있으면, 그 단계가 어떤 오류로 끝나든
  재개 · 실행 실패 대신 Flow.on_rescue가 받는다(StepFailure — 대상없음 · 재시도소진 · 오류).
- 재작성 사이클: 시작 시점 포인터를 스냅샷으로 남기고, 전후 점수로 높은 쪽을 남기며,
  실패하면 스냅샷으로 되돌리고 기회를 돌려준다(R-6의 실행 부분). 모으는 시각(collect_until)까지는 묶음을 더할 수
  있고 진행하지 않는다. 마지막 재작성 한 건의 결과는 Run.last_rework에 요약한다.
- 지시문 입력은 Flow.build_instruction이 만든다(재작성 · 재수행 때 덧붙이기 · 다시 쓰기). 엔진은 실행 건 맥락 · 단계 정보 ·
  원래 지시 · 재작성 · 재수행 입력 · 진행 위치(RedoState) 객체와, 지금 실행 기록에 호출이 남는 tools를 만드는 수단을 넘기고,
  돌려받은 산출물 참조를 그 실행 기록의 입력 참조에 더한다. 입력을 만들며 부른 호출도 Task 함수의 호출처럼 그 실행 기록에
  모인다(성공 · 재시도 소진 모두). 어느 Agent 설정으로 무엇을 부를지는 Flow가 정한다.
- S-Brain 고유 규칙(구간 · 대기 지점 · 재작성 경로 · 알림)은 Flow가 맡는다.
- 선택 확장 지점(흐름에 없으면 기본 동작): Flow.redo_rework_input — 재수행 입력을 저장하기 전에 흐름이 칸을 채운다(기본: 그대로),
  Flow.after_execution — 실행 기록이 성공으로 저장되는 같은 묶음에서 그 실행의 호출 기록을 본다(기본: 아무것도 안 함),
  Flow.allows_redo — 검사 불통과일 때 재수행을 걸지 정한다(기본: 건다).
- 시각은 시간대 있는 UTC다. 주입한 시계 · tick(now)의 시간대 없는 값은 UTC로 본다.
- 파일(확장, 결정 0023): 엔진은 파일 저장소를 받아(선택) Task의 tools.files와 파일을 쓰는 규칙 단계(writes_files)의 파일 창구에
  넘긴다. 출력을 저장하기 전에 출력 안의 모든 FileRef(중첩 모델 · 목록 · 사전 포함)를 저장소와 대조한다 — 키 첫 마디가 이 실행
  건, 저장소에 있음, 형식 · 크기 · sha256 · 이름이 같음. 어기면 규격 위반(ContractError)이고 메시지에는 수와 규칙 종류만 적는다.
- 운영 로그 줄(runlog, 로거 sbrain.run): 실행 기록마다 단계시작 · 단계끝, 실행 건의 대기 · 실행끝 · 재개예약. 단계 ID와 실행 건 ·
  실행 기록 값만 쓴다. 처리기는 워커만 단다 — 그 밖에서는 아무것도 나가지 않는다.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ValidationError

from ..models import BundleUsage, CycleState, FileRef, ReworkComparison, ReworkInput, Run, TaskInstruction
from ..models.base import ErrorKind
from ..models.clock import as_utc, utc_clock, utc_now
from ..models.run import FAILURE_REASON_MAX, RedoState, ReworkSummary, collecting, make_state
from .context import ArtifactTypes, ImmutableArtifactError, RunContext
from .errors import ContractError, ResourceNotFound, ToolCallExhausted
from .files import FileStore
from . import runlog
from .registry import PARTIAL_SUFFIX, AgentRegistry, TaskRegistry, TaskSpec, keeps_partial
from .settings import TaskModelSetting
from .store import Store
from .tools import CallSink, ImageProvider, LLMProvider, Tools, ToolsConfig, ToolsContext
from .trace import CallLog, ExecutionRecord, FeedbackLink, add_tokens, output_meta_of

# 재작성 비교 · 되돌리기에서 제외하는 산출물 (Orchestrator가 만든 입력 — 사용자 명령 · 재작성 · 재수행 입력 · 다시 쓴 지시문 ·
# 재개 때 이어 쓸 받은 결과)
INTERNAL_PREFIXES = ("decision",)
INTERNAL_SUFFIXES = (".reworkInput", ".instruction", PARTIAL_SUFFIX)

# 지금 실행 기록에 호출이 남는 tools를 만드는 수단 — (호출 기록에 남길 Agent 이름, 설정 키) → Tools
ToolsFactory = Callable[[str, str], Tools]
# 이미지 호출 한 번의 제한 시간 키 접미 — task_timeouts['<설정 키>.image']
IMAGE_TIMEOUT_SUFFIX = ".image"


def is_internal_key(key: str) -> bool:
    return key.startswith(INTERNAL_PREFIXES) or key.endswith(INTERNAL_SUFFIXES)


# 흐름에 넘긴 실패의 종류: 대상없음(ResourceNotFound) · 재시도소진(ToolCallExhausted) · 오류(그 밖 — 코드 오류 · 규격 위반)
FailureKind = Literal["대상없음", "재시도소진", "오류"]


@dataclass
class StepFailure:
    """흐름에 넘기는 단계 실패 (확장, FailurePolicy.rescue_segments). 실행 기록은 이미 '실패'로 남았다."""
    kind: FailureKind
    error: Exception
    record: ExecutionRecord


@dataclass
class Outcome:
    status: str                      # ok · resume_wait · failed · rework_failed · unresumable · rescued
    outputs: dict[str, Any] = field(default_factory=dict)
    record: ExecutionRecord | None = None
    error: ToolCallExhausted | None = None
    skipped: bool = False
    failure: StepFailure | None = None   # rescued — 흐름이 받아 처리한 실패


class Flow(Protocol):
    """워크플로(S-Brain 고유 규칙)가 엔진에 제공하는 것."""

    def custom_step(self, step_id: str) -> Callable[["Engine", RunContext], Outcome] | None: ...
    def initial_redo_state(self, ctx: RunContext, spec: TaskSpec) -> RedoState: ...
    def build_instruction(self, ctx: RunContext, spec: TaskSpec, task: TaskInstruction,
                          rework_input: ReworkInput | None, rs: RedoState,
                          tools_for: ToolsFactory) -> tuple[str, list[str]]:
        """이번 실행의 지시문 입력과, 그 실행 기록의 입력 참조에 더할 산출물 참조('이름@버전')를 돌려준다.

        task는 taskPlan의 이 Task 지시, rs는 지금 진행 위치 객체 그 자체다 — 흐름이 여기에 쓴 값은 재개 예약 때 그대로
        저장된다. tools_for(Agent 이름, 설정 키)로 만든 tools의 호출은 이 실행 기록에 남고 토큰이 합계에 더해진다 — 설정 키로
        Task별 설정(모델 등)과 제한 시간을 찾고, Agent 이름은 호출 기록에 남긴다(옛 설정 사본이면 이 이름으로 설정을 찾는다).
        여기서 올린 ToolCallExhausted는 Task 함수의 것과 같게 재개 · 실패로 처리된다."""
        ...
    def today(self, ctx: RunContext) -> Any: ...
    def constant(self, ctx: RunContext, name: str) -> Any: ...
    def value(self, ctx: RunContext, name: str, spec: TaskSpec) -> Any: ...
    def setting_value(self, ctx: RunContext, path: str) -> Any:
        """설정값 연결(setting)의 값 — 옛 설정 사본처럼 경로가 바뀐 값을 흐름이 찾아 준다. 흐름에 없으면 엔진이 설정
        사본에서 경로 그대로 찾는다(선택)."""
        ...
    def redo_rework_input(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord,
                          rework_input: ReworkInput) -> ReworkInput:
        """검사 불통과 재수행의 재작성 입력을 저장하기 전에 흐름이 칸을 채워 돌려준다(선택). rec는 방금 끝난(불통과) 실행이다.
        흐름에 없으면 엔진이 만든 그대로 저장한다. 재개 때는 저장한 것을 다시 쓰고 다시 부르지 않는다."""
        ...
    def after_execution(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, calls: list[CallLog]) -> None:
        """실행 기록 하나가 성공으로 저장된 직후, 같은 저장 묶음에서 그 실행의 이번 호출 기록(calls — 재개면 재개 뒤 호출만)을
        흐름에 보여 준다(선택). 재수행은 실행 기록마다 저장 묶음을 비우므로 실행 기록마다 따질 일은 여기서 한다.
        흐름에 없으면 아무것도 하지 않는다. 사건은 ctx.add_event로 같은 묶음에 넣는다."""
        ...
    def allows_redo(self, ctx: RunContext, spec: TaskSpec, check: Any) -> bool:
        """검사(check)가 불통과이고 재수행 횟수가 남았을 때 재수행을 걸지(선택). 거짓이면 그 결과로 단계를 끝낸다.
        흐름에 없으면 늘 건다."""
        ...
    def after_step(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None: ...
    def on_queue_empty(self, ctx: RunContext) -> None: ...
    def on_unresumable(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None: ...
    def on_rescue(self, ctx: RunContext, step_id: str, failure: StepFailure) -> None:
        """실패 정책이 흐름에 넘기도록 정한 구간의 단계 실패를 받는다. 실행 건을 그 단계가 다시 돌지 않는 상태
        (대기 지점 등)로 옮겨야 한다 — 그대로 두면 엔진이 오류를 올린다."""
        ...
    def on_abort(self, ctx: RunContext) -> None: ...
    def on_run_failed(self, ctx: RunContext, reason: str) -> None: ...
    def on_cycle_failed(self, ctx: RunContext, reason: str) -> None: ...


def _no_tools(agent_name: str, key: str) -> Tools:
    raise RuntimeError("호출 도구 없음 — 실행 기록 밖에서 지시문 입력을 만들었다")


def _collect_file_refs(obj: Any, found: list[FileRef]) -> None:
    """값 안의 FileRef를 모두 모은다 — 모델 필드 · 목록 · 튜플 · 집합 · 사전 값을 재귀로 훑는다(등록부 칸 이름을 보지 않는다)."""
    if isinstance(obj, FileRef):
        found.append(obj)
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            _collect_file_refs(getattr(obj, name), found)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_file_refs(v, found)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            _collect_file_refs(v, found)


def _dig(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


class Engine:
    def __init__(
        self,
        *,
        store: Store,
        registry: TaskRegistry,
        flow: Flow,
        providers: dict[str, LLMProvider],
        types: ArtifactTypes,
        agents: AgentRegistry | None = None,
        immutable_keys: frozenset[str] = frozenset(),
        now: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
        new_id: Callable[[], str] | None = None,
        owner: str = "worker",
        lease_sec: float = 3600,
        image_providers: dict[str, ImageProvider] | None = None,
        files: FileStore | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.flow = flow
        self.providers = providers
        # 이미지 호출처 (확장) — 이름은 Task 설정의 image_provider. 없으면 이미지 호출은 '운영' 실패다
        self.image_providers: dict[str, ImageProvider] = image_providers if image_providers is not None else {}
        # 파일 저장소 (확장) — 없으면 파일 창구를 부르는 순간 오류, 출력에 FileRef가 있으면 규격 위반
        self.files = files
        self.types = types
        self.agents = agents or AgentRegistry()
        self.immutable_keys = immutable_keys
        self.now = utc_clock(now)
        self.sleep = sleep
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:12])
        self.owner = owner
        self.lease_sec = lease_sec
        # 워커 종료 신호 — 참이면 단계 사이에서 멈춘다. 실행 건은 '실행'으로 남아 다른 워커가 이어받는다
        self.stop_requested: Callable[[], bool] = lambda: False
        # 운영 로그 단계끝의 걸린 시간 — 실행 기록 ID → 이번에 연 시각 (스레드마다 다른 실행 기록이라 키가 겹치지 않는다)
        self._step_marks: dict[str, datetime] = {}
        # 운영 로그 재개예약의 오류 종류 — 실행 건 ID → 재개를 예약한 오류 종류 (저장 뒤 줄을 남기며 지운다)
        self._resume_kinds: dict[str, str] = {}

    # ── Context ──────────────────────────────────────
    def open_context(self, run: Run, provisional: bool = False, owner: str | None = None) -> RunContext:
        return RunContext(self.store, run, owner or self.owner, self.types, self.now,
                          self.immutable_keys, provisional)

    # ── 진행 ─────────────────────────────────────────
    def advance(self, run_id: str, owner: str | None = None, lease_sec: float | None = None) -> str:
        """다음 대기 지점까지 진행한다. 다른 곳이 점유 중이면 'busy'.

        워커는 스레드마다 다른 점유자(owner)로 부른다. 끝나면(오류 포함) 점유를 푼다.
        """
        owner = owner or self.owner
        if not self.store.acquire(run_id, owner, lease_sec or self.lease_sec):
            return "busy"
        try:
            run = self.store.load_run(run_id)
            if run.state.progress != "실행":
                return run.state.progress
            if collecting(run, self.now()):
                return run.state.progress   # 재작성 요청을 모으는 중 — 모으는 시간이 지난 뒤 진행한다
            ctx = self.open_context(run, owner=owner)
            self.drain(ctx)
            return ctx.run.state.progress
        finally:
            self.store.release(run_id, owner)

    def resume(self, run_id: str, owner: str | None = None, lease_sec: float | None = None) -> str | None:
        """재개대기 실행 건 하나를 깨워 다음 대기 지점까지 진행한다. 진행 상태를 돌려준다.

        다른 곳이 점유 중이거나 재개대기가 아니면 None. 재개 시각은 부르는 쪽(tick · 워커 가져가기)이 확인한다.
        """
        owner = owner or self.owner
        if not self.store.acquire(run_id, owner, lease_sec or self.lease_sec):
            return None
        try:
            run = self.store.load_run(run_id)
            if run.state.progress != "재개대기":
                return None
            run.state = make_state(run.state.step, "실행", run.rework_screen)
            run.next_resume_at = None
            ctx = self.open_context(run, owner=owner)
            ctx.add_event("재개", f"{run.current_task} 재개 ({run.resume_count}번째)")
            ctx.commit()
            self.drain(ctx)
            return ctx.run.state.progress
        finally:
            self.store.release(run_id, owner)

    def tick(self, now: datetime | None = None) -> list[str]:
        """재개 시각이 된 실행을 모두 깨워 진행한다 (테스트 · 시연용 — 워커는 한 건씩 resume을 부른다)."""
        now = as_utc(now) if now is not None else self.now()
        return [rid for rid in self.store.runs_due_for_resume(now) if self.resume(rid) is not None]

    def drain(self, ctx: RunContext) -> Outcome | None:
        """대기열이 빌 때까지 진행한다. 마지막으로 성공하지 못한 결과를 돌려준다."""
        last: Outcome | None = None
        while ctx.run.state.progress == "실행":
            if not ctx.provisional and self.store.is_abort_requested(ctx.run.run_id):
                self.flow.on_abort(ctx)
                ctx.commit()
                self._log_progress(ctx)
                return last
            if not ctx.provisional and self.stop_requested():
                return last   # 워커 종료 — 하던 단계는 저장됐다. 남은 대기열은 다른 워커가 이어받는다
            if not ctx.run.queue:
                before = (ctx.run.state.step, ctx.run.state.progress, ctx.run.segment)
                self.flow.on_queue_empty(ctx)
                ctx.commit()
                self._log_progress(ctx)
                after = (ctx.run.state.step, ctx.run.state.progress, ctx.run.segment)
                if not ctx.run.queue and before == after:
                    raise RuntimeError(f"구간 종료 처리 없음: {ctx.run.segment}")
                continue
            step_id = ctx.run.queue[0]
            outcome = self.run_step(ctx, step_id)
            if outcome.status == "ok":
                ctx.run.queue.pop(0)
                self.flow.after_step(ctx, step_id, outcome)
            else:
                last = outcome
                if outcome.status == "unresumable":
                    self.flow.on_unresumable(ctx, step_id, outcome)
            ctx.commit()
            self._log_progress(ctx)
            if ctx.provisional and outcome.status != "ok":
                return last
        return last

    def _log_progress(self, ctx: RunContext) -> None:
        """저장 뒤 실행 건이 대기 지점에 멈췄거나 · 재개를 예약했거나 · 끝났으면 운영 로그 한 줄."""
        progress = ctx.run.state.progress
        kind = self._resume_kinds.pop(ctx.run.run_id, None)
        if progress == "재개대기":
            runlog.resume_scheduled(ctx.run, kind or ctx.run.last_error_kind)
        elif progress == "사용자대기":
            runlog.wait(ctx.run)
        elif progress in ("완료", "실패", "중단"):
            runlog.run_end(ctx.run)

    def _log_step_end(self, ctx: RunContext, rec: ExecutionRecord | None) -> None:
        """실행 기록 하나의 끝 줄. 이번에 연 시각부터 잰다. 줄은 그 기록이 저장된 뒤에 남긴다(저장 실패면 남기지 않는다)."""
        if rec is None:
            return
        started = self._step_marks.pop(rec.execution_id, None)
        sec = (self.now() - started).total_seconds() if started else None
        run, snap = ctx.run, rec.model_copy()   # 끝난 때의 값 그대로
        ctx.after_commit(lambda: runlog.step_end(run, snap, sec))

    # ── 단계 실행 ─────────────────────────────────────
    def run_step(self, ctx: RunContext, step_id: str) -> Outcome:
        ctx.run.current_task = step_id
        custom = self.flow.custom_step(step_id)
        if custom is not None:   # 흐름 전용 실행기 — 실행 기록이 있으면 그 끝 줄, 없으면 끝 줄만
            began = self.now()
            outcome = custom(self, ctx)
            if outcome.record is not None:
                self._log_step_end(ctx, outcome.record)
            else:
                run, sec = ctx.run, (self.now() - began).total_seconds()
                ctx.after_commit(lambda: runlog.step_end_without_record(run, step_id, sec))
            return outcome
        spec = self.registry.get(step_id)
        rs = ctx.run.redo_state
        if rs is None or rs.task_id != step_id:
            rs = self.flow.initial_redo_state(ctx, spec)
        limit = ctx.settings.redo.redo_count
        while True:
            rec = self.open_execution(ctx, spec, rs)
            try:
                outputs = self._invoke(ctx, spec, rec, rs)
            except ToolCallExhausted as e:
                outcome = self._on_exhausted(ctx, spec, rec, rs, e)
                self._log_step_end(ctx, rec)
                return outcome
            except Exception as e:  # 규칙 단계 오류 · 규격 위반 · Agent 코드 오류
                outcome = self.on_step_error(ctx, spec, rec, e)
                self._log_step_end(ctx, rec)
                return outcome
            else:
                self._log_step_end(ctx, rec)
            finally:
                self._step_marks.pop(rec.execution_id, None)   # 처리 중 예외가 새도 시작 시각을 남기지 않는다
            check = outputs.get("check")
            if check is not None:
                ctx.run.check_refs[spec.task_id] = ctx.ref(spec.outputs["check"])
            if (spec.redo and check is not None and not check.passed and rs.redo_count < limit
                    and self._redo_allowed(ctx, spec, check)):
                rs = self._schedule_redo(ctx, spec, rec, rs, limit)
                ctx.run.redo_state = rs
                ctx.commit()
                continue
            if (spec.final_action_exception and check is not None and not check.passed
                    and rs.redo_count >= limit and not check.final_action):
                ctx.add_event("확정동작누락", f"{spec.task_id} 마지막 재수행이 불통과인데 finalAction이 없음",
                              refs=[ctx.ref(spec.outputs["check"])], execution_id=rec.execution_id)
            ctx.run.redo_state = None
            self._reset_resume_episode(ctx)
            return Outcome("ok", outputs, rec)

    def open_execution(self, ctx: RunContext, spec: TaskSpec, rs: RedoState) -> ExecutionRecord:
        """실행 기록을 연다. 재개면 같은 기록을 이어 쓰고, 재수행이면 미리 정한 ID로 새로 만든다."""
        if rs.pending_execution_id:
            existing = ctx.find_execution(rs.pending_execution_id)
            if existing is not None:
                existing.resume_count += 1
                existing.status = "실행"
                self._step_marks[existing.execution_id] = self.now()
                runlog.step_start(ctx.run, existing, resumed=True)
                return existing
        now = self.now()
        rec = ExecutionRecord(
            task_id=spec.task_id, attempt=ctx.next_attempt(spec.task_id), trigger=rs.trigger,
            bundle_id=rs.bundle_id, result_ref="", created_at=now,
            execution_id=rs.pending_execution_id or self.new_id(), run_id=ctx.run.run_id,
            agent=spec.agent, step_kind=spec.kind,
            cycle_id=ctx.run.cycle.cycle_id if ctx.run.cycle else None,
            rework_role=rs.rework_role, redo_count=rs.redo_count, started_at=now,
        )
        if rs.rework_input_ref:
            ri = ctx.get_ref(rs.rework_input_ref)
            if ri.feedback_id:
                rec.feedback_in.append(ri.feedback_id)
        self._step_marks[rec.execution_id] = now
        runlog.step_start(ctx.run, rec, resumed=False)
        return rec

    def _invoke(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, rs: RedoState) -> dict[str, Any]:
        # 이 실행 기록의 호출 — 입력을 만들며 부른 호출(지시문 다시 쓰기 등)과 Task 함수의 호출. 성공 · 실패 모두 모은다
        sink = CallSink()
        calls: list[CallLog] = []
        try:
            values, refs = self.resolve_inputs(ctx, spec, rs, tools_for=self._tools_factory(ctx, spec, rec, sink))
            rec.inputs = refs
            try:
                model_in = spec.input_model.model_validate(values)
            except ValidationError as e:
                raise ContractError(f"{spec.task_id} 입력 규격 불일치: {e.error_count()}건") from None
            if spec.fn is None:
                raise ContractError(f"{spec.task_id} 실행 함수 없음")
            if spec.receives_tools:
                cfg = self.tools_config(ctx, spec)
                rec.model, rec.provider, rec.temperature = cfg.model, cfg.provider, cfg.temperature
                rec.reasoning_effort = cfg.reasoning_effort
                out = spec.fn(model_in, self.make_tools(ctx, spec, rec, cfg, sink))
            elif spec.writes_files:
                # 파일을 쓰는 규칙 단계 — 파일 창구만 넘긴다. 설정은 LLM을 부르지 않는 Task와 같다(제한 시간 · 재시도만)
                out = spec.fn(model_in, self.make_tools(ctx, spec, rec, self._plain_tools_config(ctx, spec), sink).files)
            else:
                out = spec.fn(model_in)
        finally:
            calls = self.collect_calls(ctx, rec, sink)
        outputs = self.store_outputs(ctx, spec, rec, out)
        hook = getattr(self.flow, "after_execution", None)   # 선택 확장 지점 — 이 실행 기록과 같은 저장 묶음
        if hook is not None:
            hook(ctx, spec, rec, calls)
        return outputs

    def store_outputs(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, out: Any) -> dict[str, Any]:
        if not isinstance(out, spec.output_model):
            try:
                out = spec.output_model.model_validate(out)
            except ValidationError as e:
                raise ContractError(f"{spec.task_id} 출력 규격 불일치: {e.error_count()}건") from None
        self.check_file_refs(ctx, spec, out)
        outputs = {name: getattr(out, name) for name in spec.output_model.model_fields}
        out_refs = []
        for fname, key in spec.outputs.items():
            try:
                out_refs.append(ctx.put(key, outputs[fname], producer=rec.execution_id))
            except ImmutableArtifactError:
                ctx.add_event("불변산출물변경시도", f"{spec.task_id}가 {key}를 바꾸려 함 — 변경분 무시",
                              refs=[ctx.ref(key)], execution_id=rec.execution_id)
                out_refs.append(ctx.ref(key))
        rec.outputs = out_refs
        rec.result_ref = ctx.ref(spec.outputs[spec.primary_output])
        rec.output_meta = output_meta_of(outputs)
        rec.status = "성공"
        rec.ended_at = self.now()
        ctx.record_execution(rec)
        ctx.record_attempt(rec)
        return outputs

    def check_file_refs(self, ctx: RunContext, spec: TaskSpec, out: Any) -> None:
        """출력 안의 모든 FileRef를 저장소와 대조한다(spec 4.4). 하나라도 어기면 ContractError — 메시지에는 어긴 참조 수와
        규칙 종류만 적는다(키 · 이름 없음). 같은 실행 건의 앞 실행 기록이 만든 참조를 그대로 넘기는 것은 된다."""
        refs: list[FileRef] = []
        _collect_file_refs(out, refs)
        if not refs:
            return
        problems: list[str] = []
        for ref in refs:
            if ref.run_id != ctx.run.run_id:
                problems.append("다른 실행 건")
                continue
            if self.files is None:
                problems.append("파일 저장소 없음")
                continue
            meta = self.files.meta(ref.key)
            if meta is None:
                problems.append("없는 파일")
            elif (meta.name, meta.media_type, meta.size, meta.sha256) != (ref.name, ref.media_type, ref.size, ref.sha256):
                problems.append("저장 값과 다름")
        if problems:
            kinds = sorted(set(problems))
            raise ContractError(f"{spec.task_id} 출력 파일 참조 위반: {len(problems)}건 ({', '.join(kinds)})")

    def resolve_inputs(self, ctx: RunContext, spec: TaskSpec, rs: RedoState | None,
                       tools_for: ToolsFactory | None = None) -> tuple[dict[str, Any], list[str]]:
        values: dict[str, Any] = {}
        refs: list[str] = []

        def add_ref(r: str) -> None:
            if r not in refs:
                refs.append(r)

        rework_input = ctx.get_ref(rs.rework_input_ref) if rs and rs.rework_input_ref else None
        for fname, b in spec.inputs.items():
            if b.kind == "art":
                if not ctx.has(b.key):
                    if b.optional:
                        values[fname] = None
                        continue
                    raise ContractError(f"{spec.task_id} 입력 산출물 없음: {b.key}")
                val = ctx.get(b.key)
                add_ref(ctx.ref(b.key))
                values[fname] = _dig(val, b.path) if b.path else val
            elif b.kind == "setting":
                lookup = getattr(self.flow, "setting_value", None)
                values[fname] = lookup(ctx, b.key) if lookup is not None else _dig(ctx.settings, b.key)
            elif b.kind == "run":
                values[fname] = getattr(ctx.run, b.key)
            elif b.kind == "cmd":
                if ctx.run.decision_ref:
                    decision = ctx.get_ref(ctx.run.decision_ref)
                    add_ref(ctx.run.decision_ref)
                    values[fname] = decision.get(b.key, b.default)
                else:
                    values[fname] = b.default
            elif b.kind == "instr":
                plan = ctx.get("taskPlan")
                add_ref(ctx.ref("taskPlan"))
                task = next((t for t in plan.tasks if t.task_id == spec.task_id), None)
                if task is None:
                    raise ContractError(f"taskPlan에 {spec.task_id} 지시문 없음")
                text, extra = self.flow.build_instruction(
                    ctx, spec, task, rework_input, rs if rs is not None else RedoState(task_id=spec.task_id),
                    tools_for or _no_tools)
                values[fname] = text
                for r in extra:   # 흐름이 만든 산출물(다시 쓴 지시문 등)도 이 실행의 입력 참조다
                    add_ref(r)
            elif b.kind == "rework":
                values[fname] = rework_input
                if rs and rs.rework_input_ref:
                    add_ref(rs.rework_input_ref)
            elif b.kind == "checks":
                check_refs = [r for t, r in ctx.run.check_refs.items() if t != spec.task_id]
                for r in check_refs:
                    add_ref(r)
                values[fname] = [ctx.get_ref(r) for r in check_refs] or None
            elif b.kind == "today":
                values[fname] = self.flow.today(ctx)
            elif b.kind == "const":
                values[fname] = self.flow.constant(ctx, b.key)
            elif b.kind == "flow":
                values[fname] = self.flow.value(ctx, b.key, spec)
            elif b.kind == "partial":
                # 재개 위치에 저장된 받은 결과가 있을 때만 넣는다 — 없으면 입력 모델 기본값(엔진은 필드 타입을 모른다)
                if rs and rs.partial_ref:
                    values[fname] = ctx.get_ref(rs.partial_ref)
                    add_ref(rs.partial_ref)
            else:
                raise ContractError(f"알 수 없는 입력 연결: {b.kind}")
        return values, refs

    def tools_config(self, ctx: RunContext, spec: TaskSpec) -> ToolsConfig:
        """Task의 호출 설정 — 설정 키는 Task ID, Agent 이름은 담당 Agent. Task 온도 규칙(TempRule)을 위에 씌운다.
        LLM을 부르지 않는 Task(uses_llm=False — T-C2 · G-01 · T-C4 · T-W3)는 Task 설정 표를 보지 않고 모델 없이 제한 시간 ·
        재시도만 입힌다. 그래서 실행 기록의 모델 · 호출처 · 온도도 비고, 옛 설정 사본에 그 Task 항목이 있어도 쓰지 않는다."""
        if not spec.uses_llm:
            return self._plain_tools_config(ctx, spec)
        cfg = self.agent_tools_config(ctx, spec.agent, spec.task_id)
        if spec.temperature:
            cfg = replace(cfg, temperature=spec.temperature.apply(cfg.temperature))
        return cfg

    @staticmethod
    def _plain_tools_config(ctx: RunContext, spec: TaskSpec) -> ToolsConfig:
        """Task 설정 표를 보지 않는 호출 설정 — 모델 없이 제한 시간(task_timeouts[단계 ID], 없으면 120초) · 재시도만.
        LLM을 부르지 않는 Task와 파일을 쓰는 규칙 단계의 파일 창구가 쓴다."""
        s = ctx.settings
        return ToolsConfig(agent=spec.agent, provider=None, model=None, temperature=None,
                           timeout_sec=s.task_timeouts.get(spec.task_id, 120.0),
                           retry_count=s.retry.retry_count, retry_interval_sec=s.retry.retry_interval_sec)

    def agent_tools_config(self, ctx: RunContext, agent_name: str, key: str) -> ToolsConfig:
        """설정 키(key)의 설정(호출처 · 모델 · 기본 온도 · 추론 강도 · 이미지 설정)과 제한 시간을 입힌 호출 설정 (Task 온도 규칙
        없음). 호출 기록의 Agent 이름은 agent_name이다. 옛 설정 사본(tasks 없음)이면 agent_name의 Agent별 설정을 쓴다.
        제한 시간은 task_timeouts[key](없으면 120초), 이미지 호출 한 번의 제한 시간은 task_timeouts['<key>.image']다.
        목적별 모델(Task 설정의 purpose_models, 확장)은 목적 이름을 보지 않고 그대로 옮긴다 — 옛 Agent별 설정에는 없다(빈 사전)."""
        s = ctx.settings
        conf = self.agents.lookup(s, agent_name, key)
        image = conf if isinstance(conf, TaskModelSetting) else None
        return ToolsConfig(
            agent=agent_name, provider=conf.provider, model=conf.model, temperature=conf.temperature,
            timeout_sec=s.task_timeouts.get(key, 120.0),
            retry_count=s.retry.retry_count, retry_interval_sec=s.retry.retry_interval_sec,
            reasoning_effort=conf.reasoning_effort,
            image_provider=image.image_provider if image else None,
            image_model=image.image_model if image else None,
            image_quality=image.image_quality if image else None,
            image_size=image.image_size if image else None,
            image_timeout_sec=s.task_timeouts.get(f"{key}{IMAGE_TIMEOUT_SUFFIX}", 120.0),
            purpose_models=dict(image.purpose_models) if image else {},
        )

    def _tools_factory(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, sink: CallSink) -> ToolsFactory:
        """지금 실행 기록(rec)에 호출이 남는 tools를 만드는 수단 — 호출 기록의 task_id는 이 단계, Agent는 넘긴 Agent 이름,
        호출처 · 모델 · 추론 강도 · 제한 시간은 넘긴 설정 키의 설정이다. Flow.build_instruction에 넘긴다."""
        def make(agent_name: str, key: str) -> Tools:
            return self.make_tools(ctx, spec, rec, self.agent_tools_config(ctx, agent_name, key), sink)
        return make

    @staticmethod
    def collect_calls(ctx: RunContext, rec: ExecutionRecord, sink: CallSink) -> list[CallLog]:
        """호출 기록을 저장 묶음에 옮기고 그 토큰을 실행 기록 합계에 더한다(재개하면 이어서 더한다). 옮긴 기록을 돌려준다."""
        logs = sink.drain()
        ctx.batch.call_logs.extend(logs)
        add_tokens(rec, logs)
        return logs

    def make_tools(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord,
                   cfg: ToolsConfig, sink: CallSink) -> Tools:
        run_id = ctx.run.run_id
        # 사전 단계(임시 Context)에는 파일 창구가 없다 — 부르는 순간 RuntimeError (저장된 실행 건이 아니다)
        files = None if ctx.provisional else self.files
        return Tools(cfg, ToolsContext(
            run_id=run_id, execution_id=rec.execution_id, task_id=spec.task_id,
            providers=self.providers, sink=sink, now=self.now, sleep=self.sleep, new_id=self.new_id,
            image_providers=self.image_providers, files=files,
            run_progress=lambda: self._stored_progress(run_id)))

    def _stored_progress(self, run_id: str) -> str | None:
        """저장소에서 다시 읽은 실행 건의 진행 상태 (파일 넣기 전 확인). 실행 건이 없으면(완전 삭제 등) None."""
        try:
            return self.store.load_run(run_id).state.progress
        except KeyError:
            return None

    # ── 재수행 ────────────────────────────────────────
    def _redo_allowed(self, ctx: RunContext, spec: TaskSpec, check: Any) -> bool:
        """검사 불통과일 때 재수행을 걸지 — 흐름의 선택 확장 지점 allows_redo가 정한다(없으면 늘 건다)."""
        hook = getattr(self.flow, "allows_redo", None)
        return True if hook is None else bool(hook(ctx, spec, check))

    def _schedule_redo(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord,
                       rs: RedoState, limit: int) -> RedoState:
        check_ref = ctx.ref(spec.outputs["check"])
        check = ctx.get_ref(check_ref)
        next_id, fid = self.new_id(), self.new_id()
        ri = ReworkInput(
            mode="재수행", previous_result_ref=rec.result_ref, issues=list(check.failures),
            order=None, is_final_attempt=rs.redo_count + 1 >= limit,
            source_refs=[check_ref], feedback_id=fid,
        )
        fill = getattr(self.flow, "redo_rework_input", None)   # 선택 확장 지점 — 흐름이 칸을 채운다 (엔진은 Task를 모른다)
        if fill is not None:
            ri = fill(ctx, spec, rec, ri)
        ri_ref = ctx.put(f"{spec.task_id}.reworkInput", ri, producer=f"orchestrator:{rec.execution_id}")
        ctx.add_feedback(FeedbackLink(
            feedback_id=fid, run_id=ctx.run.run_id, kind="재수행", source_execution_id=rec.execution_id,
            source_refs=[check_ref], target_task_id=spec.task_id, target_execution_id=next_id,
            via_ref=ri_ref, cycle_id=ctx.run.cycle.cycle_id if ctx.run.cycle else None, created_at=self.now()))
        return RedoState(task_id=spec.task_id, redo_count=rs.redo_count + 1, trigger="재수행",
                         rework_input_ref=ri_ref, pending_execution_id=next_id,
                         bundle_id=rs.bundle_id, rework_role=rs.rework_role)

    # ── 실패 · 재개 ───────────────────────────────────
    def _on_exhausted(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord,
                      rs: RedoState, e: ToolCallExhausted) -> Outcome:
        rec.status, rec.error, rec.error_kind, rec.ended_at = "실패", e.error, e.error_kind, self.now()
        ctx.record_execution(rec)
        ctx.run.retry_count = max(e.tries - 1, 0)
        ctx.run.last_error_kind = e.error_kind
        if self._rescues(ctx, spec):
            return self._rescue(ctx, spec, rec, StepFailure("재시도소진", e, rec))
        if not spec.failure.resumable:
            ctx.run.redo_state = None
            return Outcome("unresumable", record=rec, error=e)
        rs.pending_execution_id = rec.execution_id
        partial = e.partial if keeps_partial(spec) else None
        return self.schedule_resume(ctx, rec, rs, e.error_kind, partial=partial)

    def can_resume(self, ctx: RunContext) -> timedelta | None:
        """재개할 수 있으면 기다릴 시간을, 재개 횟수 · 재개 총 대기 상한을 넘으면 None."""
        run, s, now = ctx.run, ctx.settings.resume, self.now()
        start = run.resume_window_started_at or now
        wait = timedelta(minutes=s.first_interval_min * (s.multiplier ** run.resume_count))
        if run.resume_count < s.max_count and (now + wait - start) <= timedelta(hours=s.total_cap_hours):
            return wait
        return None

    def schedule_resume(self, ctx: RunContext, rec: ExecutionRecord, rs: RedoState | None,
                        kind: ErrorKind, *, partial: dict[str, Any] | None = None) -> Outcome:
        """일시 오류고 재개할 수 있으면 '재개대기'를 예약하고, 아니면 실패로 간다.

        partial(받은 결과)은 재개를 실제로 예약할 때만 '<taskId>.partial'(만든 쪽 = 이 실행 기록)로 저장하고 그 참조를
        재개 위치에 적는다 — 같은 저장에 남는다. 비어 있으면 저장하지 않고 재개 위치의 기존 참조를 그대로 둔다.
        """
        run, now = ctx.run, self.now()
        if kind == "일시":
            start = run.resume_window_started_at or now
            wait = self.can_resume(ctx)
            if wait is not None:
                run.resume_window_started_at = start
                run.resume_count += 1
                run.next_resume_at = now + wait
                # rs 없이 부르는 곳(흐름의 재개 예약)은 partial을 넘기지 않는다 — 진행 위치가 없으면 이어 쓸 곳도 없다
                if partial and rs is not None:
                    rs.partial_ref = ctx.put(f"{rec.task_id}{PARTIAL_SUFFIX}", partial, producer=rec.execution_id)
                run.redo_state = rs
                run.state = make_state(run.state.step, "재개대기", run.rework_screen)
                rec.status = "재개대기"
                ctx.record_execution(rec)
                ctx.add_event("재개예약", f"{rec.task_id} {wait} 뒤 재개", execution_id=rec.execution_id)
                self._resume_kinds[run.run_id] = kind   # 재개예약 줄은 저장 뒤 남긴다 (_log_progress)
                return Outcome("resume_wait", record=rec)
            reason = "재개상한초과"
        else:
            reason = "영구오류"
        return self.fail(ctx, rec, reason, permanent=kind != "일시")

    def fail(self, ctx: RunContext, rec: ExecutionRecord | None, reason: str, *, permanent: bool) -> Outcome:
        run = ctx.run
        run.redo_state = None
        run.next_resume_at = None
        if run.cycle is not None:
            self.rollback_cycle(ctx, reason)
            self.flow.on_cycle_failed(ctx, reason)
            self._reset_resume_episode(ctx)
            return Outcome("rework_failed", record=rec)
        run.queue = []
        run.admin_alert = permanent
        run.ended_at = self.now()
        run.state = make_state(run.state.step, "실패")
        task = rec.task_id if rec else run.current_task
        summary = f" — {rec.error}" if rec and rec.error else ""
        run.failure_reason = f"{task}: {reason}{summary}"[:FAILURE_REASON_MAX]
        ctx.add_event("실행실패", reason, execution_id=rec.execution_id if rec else None)
        self.flow.on_run_failed(ctx, reason)
        return Outcome("failed", record=rec)

    def on_step_error(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, exc: Exception) -> Outcome:
        rec.status, rec.error_kind, rec.ended_at = "실패", "운영", self.now()
        rec.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        ctx.record_execution(rec)
        ctx.run.last_error_kind = "운영"
        if self._rescues(ctx, spec):
            kind: FailureKind = "대상없음" if isinstance(exc, ResourceNotFound) else "오류"
            return self._rescue(ctx, spec, rec, StepFailure(kind, exc, rec))
        if spec.kind in ("rule", "merge") and spec.failure.on_step_error == "continue":
            ctx.add_event("단계오류계속", f"{spec.task_id} 오류 — 기준 문서대로 계속 진행", execution_id=rec.execution_id)
            ctx.run.redo_state = None
            return Outcome("ok", record=rec, skipped=True)
        ctx.add_event("단계오류", f"{spec.task_id}: {rec.error}", execution_id=rec.execution_id)
        return self.fail(ctx, rec, "운영오류", permanent=True)

    @staticmethod
    def _rescues(ctx: RunContext, spec: TaskSpec) -> bool:
        """실패 정책이 지금 구간의 실패를 흐름에 넘기도록 정했는지."""
        return ctx.run.segment is not None and ctx.run.segment in spec.failure.rescue_segments

    def _rescue(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, failure: StepFailure) -> Outcome:
        """실행을 실패시키지 않고 흐름에 넘긴다 — 재개 · 실행 실패 · 재작성 되돌리기를 하지 않는다.

        흐름은 실행 건을 그 단계가 다시 돌지 않는 상태로 옮겨야 한다(대기 지점 등). 같은 단계가 여전히 다음 차례면
        같은 실패를 되풀이하므로 오류를 올린다.
        """
        ctx.run.redo_state = None
        ctx.add_event("단계실패흐름처리", f"{spec.task_id} {failure.kind} — 실행을 실패시키지 않고 흐름이 처리",
                      execution_id=rec.execution_id)
        self.flow.on_rescue(ctx, spec.task_id, failure)
        run = ctx.run
        if run.state.progress == "실행" and run.queue[:1] == [spec.task_id]:
            raise RuntimeError(f"실패 처리 없음: {spec.task_id}")
        return Outcome("rescued", record=rec, failure=failure,
                       error=failure.error if isinstance(failure.error, ToolCallExhausted) else None)

    def _reset_resume_episode(self, ctx: RunContext) -> None:
        # 재개 횟수는 실패한 지점이 성공하면 다시 센다 (잠정 — 기준 문서에 세는 범위 없음)
        run = ctx.run
        run.resume_count = 0
        run.resume_window_started_at = None
        run.retry_count = 0

    # ── 재작성 사이클 ─────────────────────────────────
    def start_cycle(self, ctx: RunContext, *, screen: int, selected_orders_ref: str,
                    orders_by_task: dict[str, dict], counted_bundles: list[tuple[str, str]],
                    layers: list[str], collect_until: datetime | None = None) -> CycleState:
        """재작성 사이클을 연다 — 지금 포인터를 스냅샷으로 남기고 묶음 기회를 쓴다. 마지막 재작성 요약을 새로 만든다.

        collect_until을 주면 그 시각까지 '모으는 중'이다: extend_cycle로 묶음을 더할 수 있고, 진행(advance)과
        워커 가져가기는 그 시각이 지난 뒤에 한다.
        """
        run = ctx.run
        self._use_bundles(ctx, counted_bundles)
        now = self.now()
        cycle = CycleState(
            cycle_id=self.new_id(), screen=screen, snapshot=dict(ctx.pointers),
            counted_bundles=[b for b, _ in counted_bundles], selected_orders_ref=selected_orders_ref,
            orders_by_task=orders_by_task, layers=layers, started_at=now, collect_until=collect_until)
        run.cycle = cycle
        run.rework_screen = screen
        run.check_refs = {}
        run.last_rework = ReworkSummary(cycle_id=cycle.cycle_id, screen=screen,
                                        bundles=list(cycle.counted_bundles), status="진행중", started_at=now)
        ctx.add_event("재작성시작", f"화면 {screen}, 묶음 {cycle.counted_bundles}", refs=[selected_orders_ref])
        return cycle

    def extend_cycle(self, ctx: RunContext, *, selected_orders_ref: str, orders_by_task: dict[str, dict],
                     counted_bundles: list[tuple[str, str]], layers: list[str]) -> CycleState:
        """모으는 중인 사이클에 묶음을 더한다 (첫 단계를 돌기 전에만). 새로 더한 묶음만 기회를 쓴다.

        스냅샷은 첫 요청 때 것을 그대로 쓴다 — 그 뒤로 바뀐 것은 내부 산출물(decision)뿐이다.
        """
        cycle = ctx.run.cycle
        assert cycle is not None
        added = [(b, layer) for b, layer in counted_bundles if b not in cycle.counted_bundles]
        self._use_bundles(ctx, added)
        cycle.counted_bundles += [b for b, _ in added]
        cycle.selected_orders_ref = selected_orders_ref
        cycle.orders_by_task = orders_by_task
        cycle.layers = layers
        summary = self._summary(ctx)
        if summary is not None:
            summary.bundles = list(cycle.counted_bundles)
        ctx.add_event("재작성묶음추가", f"화면 {cycle.screen}, 묶음 {[b for b, _ in added]}",
                      refs=[selected_orders_ref])
        return cycle

    @staticmethod
    def _use_bundles(ctx: RunContext, counted_bundles: list[tuple[str, str]]) -> None:
        run = ctx.run
        usage = {u.bundle_id: u for u in run.rework_usage}
        for bundle_id, layer in counted_bundles:
            if bundle_id not in usage:
                u = BundleUsage(bundle_id=bundle_id, layer=layer, used_count=0,
                                remaining=ctx.settings.rework.per_bundle)
                run.rework_usage.append(u)
                usage[bundle_id] = u
            u = usage[bundle_id]
            u.used_count += 1
            u.remaining -= 1

    @staticmethod
    def _summary(ctx: RunContext) -> ReworkSummary | None:
        """지금 사이클의 마지막 재작성 요약 (다른 사이클의 것이면 None)."""
        s, cycle = ctx.run.last_rework, ctx.run.cycle
        return s if s is not None and cycle is not None and s.cycle_id == cycle.cycle_id else None

    def changed_since_snapshot(self, ctx: RunContext) -> dict[str, tuple[int | None, int]]:
        snap = ctx.run.cycle.snapshot if ctx.run.cycle else {}
        return {k: (snap.get(k), v) for k, v in ctx.pointers.items()
                if snap.get(k) != v and not is_internal_key(k)}

    def compare_and_keep(self, ctx: RunContext, *, before: float, after: float, basis: str) -> str:
        """전후 점수를 비교해 높은 쪽을 남긴다. 동점이면 재작성 결과('후')를 남긴다(잠정)."""
        cycle = ctx.run.cycle
        assert cycle is not None
        changed = self.changed_since_snapshot(ctx)
        before_refs = [f"{k}@{old}" for k, (old, _) in changed.items() if old is not None]
        after_refs = [f"{k}@{new}" for k, (_, new) in changed.items()]
        kept = "후" if after >= before else "전"
        for bundle in cycle.counted_bundles or ["(반영)"]:
            comp = ReworkComparison(
                bundle_id=bundle, before_refs=before_refs, after_refs=after_refs,
                before_score=before, after_score=after, kept=kept,
                cycle_id=cycle.cycle_id, screen=cycle.screen, basis=basis, compared_at=self.now())
            cycle.comparisons.append(comp)
            ctx.add_comparison(comp)
        if kept == "전":
            for k, (old, _) in changed.items():
                if old is not None:
                    ctx.move_pointer(k, old, "재작성 되돌리기 (점수 하락)", cycle.cycle_id)
        summary = self._summary(ctx)
        if summary is not None:
            summary.kept, summary.basis, summary.before_score, summary.after_score = kept, basis, before, after
            summary.before_refs, summary.after_refs = before_refs, after_refs
        ctx.add_event("전후비교", f"{basis} {before} → {after}, 남김={kept}", refs=before_refs + after_refs)
        return kept

    def rollback_cycle(self, ctx: RunContext, reason: str) -> None:
        """재작성 실패 — 요청 전 결과로 되돌리고 그 묶음의 기회를 돌려준다."""
        cycle = ctx.run.cycle
        assert cycle is not None
        for k, (old, _) in self.changed_since_snapshot(ctx).items():
            if old is not None:
                ctx.move_pointer(k, old, f"재작성 실패 되돌리기 ({reason})", cycle.cycle_id)
        for u in ctx.run.rework_usage:
            if u.bundle_id in cycle.counted_bundles:
                u.used_count -= 1
                u.remaining += 1
        summary = self._summary(ctx)
        if summary is not None:   # 실패는 되돌림 · 돌려준 묶음만 남긴다 — 산출물은 요청 전 그대로다
            summary.status, summary.rolled_back, summary.failure_reason = "실패", True, reason
            summary.refunded_bundles = list(cycle.counted_bundles)
            summary.kept = summary.basis = summary.before_score = summary.after_score = None
            summary.before_refs, summary.after_refs, summary.ended_at = [], [], self.now()
        ctx.add_event("재작성실패", reason)
        ctx.run.queue = []

    def end_cycle(self, ctx: RunContext) -> None:
        summary = self._summary(ctx)
        if summary is not None and summary.status == "진행중":
            summary.status, summary.ended_at = "완료", self.now()
        ctx.add_event("재작성종료", f"화면 {ctx.run.rework_screen}")
        ctx.run.cycle = None
        ctx.run.rework_screen = None
