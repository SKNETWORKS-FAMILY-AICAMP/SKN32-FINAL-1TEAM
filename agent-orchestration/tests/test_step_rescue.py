"""엔진의 실패를 살리는 장치 — 실패 정책 rescue_segments에 든 구간에서는 어떤 오류든 Flow.on_rescue가 받는다.

S-Brain 흐름 없이 작은 Flow와 Task 하나로 엔진 동작만 본다(메모리 · SQLite 저장소).
- 정한 구간: 코드 오류 · 규격 위반 · 대상 없음(ResourceNotFound) · 재시도 소진 모두 흐름이 받고, 실행은 실패하지 않는다.
- 정하지 않은 구간: 지금 처리 그대로(코드 오류 → 실행 실패, 재개하지 않는 재시도 소진 → on_unresumable).
- 흐름이 아무것도 하지 않으면(같은 단계가 대기열 맨 앞에 남으면) 엔진이 오류를 올린다.
"""
from __future__ import annotations

from datetime import date

import pytest
from conftest import Clock

from sbrain.models import Run
from sbrain.models.base import SBModel
from sbrain.models.run import RedoState, make_state
from sbrain.orchestrator import ArtifactTypes, Engine, Settings
from sbrain.orchestrator.engine import StepFailure
from sbrain.orchestrator.errors import ProviderError, ResourceNotFound
from sbrain.orchestrator.registry import FailurePolicy, TaskRegistry, TaskSpec
from sbrain.orchestrator.store import CommitBatch, Store


class XIn(SBModel):
    n: int = 0


class XOut(SBModel):
    value: str


class MiniFlow:
    """Flow 인터페이스의 최소 구현 — 받은 실패를 기록하고 대기 지점으로 돌린다."""

    def __init__(self, handle: bool = True) -> None:
        self.handle = handle
        self.rescued: list[tuple[str, str, str | None, str]] = []
        self.unresumable: list[str] = []
        self.failed: list[str] = []

    def custom_step(self, step_id):
        return None

    def initial_redo_state(self, ctx, spec):
        return RedoState(task_id=spec.task_id)

    def build_instruction(self, base, rework_input):
        return base

    def today(self, ctx):
        return date(2026, 9, 26)

    def constant(self, ctx, name):
        raise KeyError(name)

    def value(self, ctx, name, spec):
        raise KeyError(name)

    def after_step(self, ctx, step_id, outcome):
        pass

    def on_queue_empty(self, ctx):
        ctx.run.state = make_state("공고선택", "사용자대기")
        ctx.run.segment = None

    def on_unresumable(self, ctx, step_id, outcome):
        self.unresumable.append(step_id)
        ctx.run.queue = []
        ctx.run.state = make_state("공고선택", "사용자대기")

    def on_rescue(self, ctx, step_id, failure: StepFailure):
        self.rescued.append((step_id, failure.kind, ctx.run.segment, type(failure.error).__name__))
        assert failure.record.status == "실패"
        if self.handle:
            ctx.run.queue = []
            ctx.run.state = make_state("공고선택", "사용자대기")

    def on_abort(self, ctx):
        pass

    def on_run_failed(self, ctx, reason):
        self.failed.append(reason)

    def on_cycle_failed(self, ctx, reason):
        pass


def _down(timeout: float) -> None:
    raise ProviderError("down", status=503)


def failing(kind: str):
    """kind: 오류(코드 오류) · 대상없음 · 규격위반 · 소진(재시도 소진) · 정상."""
    def fn(inp: XIn, tools) -> XOut:
        if kind == "오류":
            raise RuntimeError("스텁 오류")
        if kind == "대상없음":
            raise ResourceNotFound("대상 없음")
        if kind == "규격위반":
            return {"wrong": 1}   # type: ignore[return-value]
        if kind == "소진":
            tools.search("외부 호출", _down)
        return XOut(value="ok")
    return fn


def engine_with(clock: Clock, fn, *, segments: frozenset[str] = frozenset({"S1"}), handle: bool = True):
    registry = TaskRegistry()
    registry.register(TaskSpec("X", "외부 조회", "조율", "task", XIn, XOut, {}, {"value": "x.value"}, "value",
                               failure=FailurePolicy(resumable=False, rescue_segments=segments)))
    registry.bind("X", fn)
    flow = MiniFlow(handle)
    store = clock.backend.make_store(clock)
    engine = Engine(store=store, registry=registry, flow=flow, providers={}, types=ArtifactTypes({}),
                    now=clock, sleep=lambda s: None)
    return engine, flow, store


def run_in(store: Store, clock: Clock, segment: str) -> str:
    now = clock()
    run = Run(run_id=f"r-{segment}", account_id="acc", state=make_state("자격확인", "실행"), current_phase="setup",
              settings_snapshot=Settings().dump(), updated_at=now, created_at=now, queue=["X"], segment=segment,
              segment_total=1)
    assert store.create_run(run, CommitBatch())
    return run.run_id


@pytest.mark.parametrize(("kind", "expected", "error", "recorded"), [
    ("오류", "오류", "RuntimeError", "RuntimeError"),
    ("규격위반", "오류", "ContractError", "ContractError"),
    ("대상없음", "대상없음", "ResourceNotFound", "ResourceNotFound"),
    ("소진", "재시도소진", "ToolCallExhausted", "호출실패"),
])
def test_any_error_in_rescue_segment_goes_to_flow(clock, kind, expected, error, recorded):
    engine, flow, store = engine_with(clock, failing(kind))
    rid = run_in(store, clock, "S1")
    assert engine.advance(rid) == "사용자대기"
    assert flow.rescued == [("X", expected, "S1", error)]
    assert flow.failed == [] and flow.unresumable == []
    run = store.load_run(rid)
    assert (run.state.progress, run.failure_reason, run.queue, run.redo_state) == ("사용자대기", None, [], None)
    [rec] = store.executions(rid)
    assert rec.status == "실패" and rec.error.startswith(recorded)
    assert any(e.kind == "단계실패흐름처리" and "X" in e.detail for e in store.events(rid))


def test_other_segments_keep_default_failure_handling(clock):
    engine, flow, store = engine_with(clock, failing("오류"))
    rid = run_in(store, clock, "S2")
    assert engine.advance(rid) == "실패"                        # 코드 오류 → 운영 오류로 실행 실패 (지금 그대로)
    assert flow.rescued == [] and flow.failed == ["운영오류"]
    engine, flow, store = engine_with(clock, failing("소진"))
    rid = run_in(store, clock, "S2")
    engine.advance(rid)
    assert flow.rescued == [] and flow.unresumable == ["X"]     # 재개하지 않는 재시도 소진 → on_unresumable (지금 그대로)
    engine, flow, store = engine_with(clock, failing("오류"), segments=frozenset())
    rid = run_in(store, clock, "S1")
    assert engine.advance(rid) == "실패" and flow.rescued == []   # 정책에 구간이 없으면 흐름이 받지 않는다


def test_success_is_untouched(clock):
    engine, flow, store = engine_with(clock, failing("정상"))
    rid = run_in(store, clock, "S1")
    assert engine.advance(rid) == "사용자대기" and flow.rescued == []
    assert store.executions(rid)[0].status == "성공"


def test_flow_must_move_the_run_on_rescue(clock):
    engine, flow, store = engine_with(clock, failing("오류"), handle=False)
    rid = run_in(store, clock, "S1")
    with pytest.raises(RuntimeError, match="실패 처리 없음"):
        engine.advance(rid)
