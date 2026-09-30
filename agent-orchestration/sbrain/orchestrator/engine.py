"""실행 엔진 — Agent 종류와 무관한 공통 장치.

- 대기열(Run.queue)의 단계를 순서대로 실행하고, 단계가 끝날 때마다 한 번에 저장한다.
- 재수행 루프: check.passed=false면 횟수를 세고 문제 내용(ReworkInput)을 실어 같은 Task를 다시 부른다.
- 재시도는 tools가 호출 단위로 하고, 재시도를 다 쓰면 Task 단위로 재개한다(R-11).
- 재작성 사이클: 시작 시점 포인터를 스냅샷으로 남기고, 전후 점수로 높은 쪽을 남기며,
  실패하면 스냅샷으로 되돌리고 기회를 돌려준다(R-6의 실행 부분).
- S-Brain 고유 규칙(구간 · 대기 지점 · 재작성 경로 · 알림)은 Flow가 맡는다.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from pydantic import ValidationError

from ..models import BundleUsage, CycleState, ReworkComparison, ReworkInput, Run
from ..models.base import ErrorKind
from ..models.run import RedoState, make_state
from .context import ArtifactTypes, ImmutableArtifactError, RunContext
from .errors import ContractError, ToolCallExhausted
from .registry import AgentRegistry, TaskRegistry, TaskSpec
from .store import Store
from .tools import CallSink, LLMProvider, Tools, ToolsConfig, ToolsContext
from .trace import ExecutionRecord, FeedbackLink, output_meta_of

# 재작성 비교 · 되돌리기에서 제외하는 산출물 (Orchestrator가 만든 입력)
INTERNAL_PREFIXES = ("decision",)
INTERNAL_SUFFIXES = (".reworkInput",)


def is_internal_key(key: str) -> bool:
    return key.startswith(INTERNAL_PREFIXES) or key.endswith(INTERNAL_SUFFIXES)


@dataclass
class Outcome:
    status: str                      # ok · resume_wait · failed · rework_failed · unresumable
    outputs: dict[str, Any] = field(default_factory=dict)
    record: ExecutionRecord | None = None
    error: ToolCallExhausted | None = None
    skipped: bool = False


class Flow(Protocol):
    """워크플로(S-Brain 고유 규칙)가 엔진에 제공하는 것."""

    def custom_step(self, step_id: str) -> Callable[["Engine", RunContext], Outcome] | None: ...
    def initial_redo_state(self, ctx: RunContext, spec: TaskSpec) -> RedoState: ...
    def build_instruction(self, base: str, rework_input: ReworkInput | None) -> str: ...
    def today(self, ctx: RunContext) -> Any: ...
    def constant(self, ctx: RunContext, name: str) -> Any: ...
    def value(self, ctx: RunContext, name: str, spec: TaskSpec) -> Any: ...
    def after_step(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None: ...
    def on_queue_empty(self, ctx: RunContext) -> None: ...
    def on_unresumable(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None: ...
    def on_abort(self, ctx: RunContext) -> None: ...
    def on_run_failed(self, ctx: RunContext, reason: str) -> None: ...
    def on_cycle_failed(self, ctx: RunContext, reason: str) -> None: ...


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
        now: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
        new_id: Callable[[], str] | None = None,
        owner: str = "worker",
        lease_sec: float = 3600,
    ) -> None:
        self.store = store
        self.registry = registry
        self.flow = flow
        self.providers = providers
        self.types = types
        self.agents = agents or AgentRegistry()
        self.immutable_keys = immutable_keys
        self.now = now
        self.sleep = sleep
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:12])
        self.owner = owner
        self.lease_sec = lease_sec

    # ── Context ──────────────────────────────────────
    def open_context(self, run: Run, provisional: bool = False) -> RunContext:
        return RunContext(self.store, run, self.owner, self.types, self.now,
                          self.immutable_keys, provisional)

    # ── 진행 ─────────────────────────────────────────
    def advance(self, run_id: str) -> str:
        """다음 대기 지점까지 진행한다. 다른 곳이 점유 중이면 'busy'."""
        if not self.store.acquire(run_id, self.owner, self.lease_sec):
            return "busy"
        try:
            run = self.store.load_run(run_id)
            if run.state.progress != "실행":
                return run.state.progress
            ctx = self.open_context(run)
            self.drain(ctx)
            return ctx.run.state.progress
        finally:
            self.store.release(run_id, self.owner)

    def tick(self, now: datetime | None = None) -> list[str]:
        """재개 시각이 된 실행을 깨워 진행한다."""
        now = now or self.now()
        resumed = []
        for run_id in self.store.runs_due_for_resume(now):
            if not self.store.acquire(run_id, self.owner, self.lease_sec):
                continue
            try:
                run = self.store.load_run(run_id)
                if run.state.progress != "재개대기":
                    continue
                run.state = make_state(run.state.step, "실행", run.rework_screen)
                run.next_resume_at = None
                ctx = self.open_context(run)
                ctx.add_event("재개", f"{run.current_task} 재개 ({run.resume_count}번째)")
                ctx.commit()
                self.drain(ctx)
                resumed.append(run_id)
            finally:
                self.store.release(run_id, self.owner)
        return resumed

    def drain(self, ctx: RunContext) -> Outcome | None:
        """대기열이 빌 때까지 진행한다. 마지막으로 성공하지 못한 결과를 돌려준다."""
        last: Outcome | None = None
        while ctx.run.state.progress == "실행":
            if not ctx.provisional and self.store.is_abort_requested(ctx.run.run_id):
                self.flow.on_abort(ctx)
                ctx.commit()
                return last
            if not ctx.run.queue:
                before = (ctx.run.state.step, ctx.run.state.progress, ctx.run.segment)
                self.flow.on_queue_empty(ctx)
                ctx.commit()
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
            if ctx.provisional and outcome.status != "ok":
                return last
        return last

    # ── 단계 실행 ─────────────────────────────────────
    def run_step(self, ctx: RunContext, step_id: str) -> Outcome:
        ctx.run.current_task = step_id
        custom = self.flow.custom_step(step_id)
        if custom is not None:
            return custom(self, ctx)
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
                return self._on_exhausted(ctx, spec, rec, rs, e)
            except Exception as e:  # 규칙 단계 오류 · 규격 위반 · Agent 코드 오류
                return self.on_step_error(ctx, spec, rec, e)
            check = outputs.get("check")
            if check is not None:
                ctx.run.check_refs[spec.task_id] = ctx.ref(spec.outputs["check"])
            if spec.redo and check is not None and not check.passed and rs.redo_count < limit:
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
        return rec

    def _invoke(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, rs: RedoState) -> dict[str, Any]:
        values, refs = self.resolve_inputs(ctx, spec, rs)
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
            sink = CallSink()
            tools = self.make_tools(ctx, spec, rec, cfg, sink)
            try:
                out = spec.fn(model_in, tools)
            finally:
                ctx.batch.call_logs.extend(sink.drain())
        else:
            out = spec.fn(model_in)
        return self.store_outputs(ctx, spec, rec, out)

    def store_outputs(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, out: Any) -> dict[str, Any]:
        if not isinstance(out, spec.output_model):
            try:
                out = spec.output_model.model_validate(out)
            except ValidationError as e:
                raise ContractError(f"{spec.task_id} 출력 규격 불일치: {e.error_count()}건") from None
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

    def resolve_inputs(self, ctx: RunContext, spec: TaskSpec, rs: RedoState | None) -> tuple[dict[str, Any], list[str]]:
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
                values[fname] = _dig(ctx.settings, b.key)
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
                base = next((t.instruction for t in plan.tasks if t.task_id == spec.task_id), None)
                if base is None:
                    raise ContractError(f"taskPlan에 {spec.task_id} 지시문 없음")
                values[fname] = self.flow.build_instruction(base, rework_input)
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
            else:
                raise ContractError(f"알 수 없는 입력 연결: {b.kind}")
        return values, refs

    def tools_config(self, ctx: RunContext, spec: TaskSpec) -> ToolsConfig:
        s = ctx.settings
        agent = self.agents.config(s, spec.agent)
        temperature = spec.temperature.apply(agent.temperature) if spec.temperature else agent.temperature
        return ToolsConfig(
            agent=spec.agent, provider=agent.provider, model=agent.model, temperature=temperature,
            timeout_sec=s.task_timeouts.get(spec.task_id, 120.0),
            retry_count=s.retry.retry_count, retry_interval_sec=s.retry.retry_interval_sec,
            reasoning_effort=agent.reasoning_effort,
        )

    def make_tools(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord,
                   cfg: ToolsConfig, sink: CallSink) -> Tools:
        return Tools(cfg, ToolsContext(
            run_id=ctx.run.run_id, execution_id=rec.execution_id, task_id=spec.task_id,
            providers=self.providers, sink=sink, now=self.now, sleep=self.sleep, new_id=self.new_id))

    # ── 재수행 ────────────────────────────────────────
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
        if not spec.failure.resumable:
            ctx.run.redo_state = None
            return Outcome("unresumable", record=rec, error=e)
        rs.pending_execution_id = rec.execution_id
        return self.schedule_resume(ctx, rec, rs, e.error_kind)

    def can_resume(self, ctx: RunContext) -> timedelta | None:
        """재개할 수 있으면 기다릴 시간을, 재개 횟수 · 재개 총 대기 상한을 넘으면 None."""
        run, s, now = ctx.run, ctx.settings.resume, self.now()
        start = run.resume_window_started_at or now
        wait = timedelta(minutes=s.first_interval_min * (s.multiplier ** run.resume_count))
        if run.resume_count < s.max_count and (now + wait - start) <= timedelta(hours=s.total_cap_hours):
            return wait
        return None

    def schedule_resume(self, ctx: RunContext, rec: ExecutionRecord, rs: RedoState | None,
                        kind: ErrorKind) -> Outcome:
        run, now = ctx.run, self.now()
        if kind == "일시":
            start = run.resume_window_started_at or now
            wait = self.can_resume(ctx)
            if wait is not None:
                run.resume_window_started_at = start
                run.resume_count += 1
                run.next_resume_at = now + wait
                run.redo_state = rs
                run.state = make_state(run.state.step, "재개대기", run.rework_screen)
                rec.status = "재개대기"
                ctx.record_execution(rec)
                ctx.add_event("재개예약", f"{rec.task_id} {wait} 뒤 재개", execution_id=rec.execution_id)
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
        ctx.add_event("실행실패", reason, execution_id=rec.execution_id if rec else None)
        self.flow.on_run_failed(ctx, reason)
        return Outcome("failed", record=rec)

    def on_step_error(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, exc: Exception) -> Outcome:
        rec.status, rec.error_kind, rec.ended_at = "실패", "운영", self.now()
        rec.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        ctx.record_execution(rec)
        ctx.run.last_error_kind = "운영"
        if spec.kind in ("rule", "merge") and spec.failure.on_step_error == "continue":
            ctx.add_event("단계오류계속", f"{spec.task_id} 오류 — 기준 문서대로 계속 진행", execution_id=rec.execution_id)
            ctx.run.redo_state = None
            return Outcome("ok", record=rec, skipped=True)
        ctx.add_event("단계오류", f"{spec.task_id}: {rec.error}", execution_id=rec.execution_id)
        return self.fail(ctx, rec, "운영오류", permanent=True)

    def _reset_resume_episode(self, ctx: RunContext) -> None:
        # 재개 횟수는 실패한 지점이 성공하면 다시 센다 (잠정 — 기준 문서에 세는 범위 없음)
        run = ctx.run
        run.resume_count = 0
        run.resume_window_started_at = None
        run.retry_count = 0

    # ── 재작성 사이클 ─────────────────────────────────
    def start_cycle(self, ctx: RunContext, *, screen: int, selected_orders_ref: str,
                    orders_by_task: dict[str, dict], counted_bundles: list[tuple[str, str]],
                    layers: list[str]) -> CycleState:
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
        cycle = CycleState(
            cycle_id=self.new_id(), screen=screen, snapshot=dict(ctx.pointers),
            counted_bundles=[b for b, _ in counted_bundles], selected_orders_ref=selected_orders_ref,
            orders_by_task=orders_by_task, layers=layers, started_at=self.now())
        run.cycle = cycle
        run.rework_screen = screen
        run.check_refs = {}
        ctx.add_event("재작성시작", f"화면 {screen}, 묶음 {cycle.counted_bundles}", refs=[selected_orders_ref])
        return cycle

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
        ctx.add_event("재작성실패", reason)
        ctx.run.queue = []

    def end_cycle(self, ctx: RunContext) -> None:
        ctx.add_event("재작성종료", f"화면 {ctx.run.rework_screen}")
        ctx.run.cycle = None
        ctx.run.rework_screen = None
