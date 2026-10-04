"""재개 때 받은 결과 이어 쓰기 — 엔진 일반 장치(입력 연결 PARTIAL · ToolCallExhausted.partial · RedoState.partial_ref).

S-Brain 흐름 없이 작은 Flow와 Task 하나로 엔진 동작만 본다(메모리 · SQLite 저장소).
- 일시 오류로 재개를 예약할 때만 받은 결과를 <taskId>.partial로 저장하고 재개 위치에 참조를 적는다.
- 재개하면 연결한 입력에 그 값이 들어가고, 실행 기록의 입력 참조에 그 참조가 더해진다.
- 빈 결과 · 연결 없는 Task · 영구 오류 · 재개 상한 초과 · 재개 불가 · 흐름에 넘김에서는 저장하지 않는다.
- 받은 결과의 내용은 예외 str · repr, 실행 기록, 호출 기록, 추적 사건에 나오지 않는다.
"""
from __future__ import annotations

from datetime import date, timedelta

from conftest import Clock
from pydantic import Field

from sbrain.flow.catalog import artifact_types, build_registry
from sbrain.models import Run
from sbrain.models.base import SBModel
from sbrain.models.run import RedoState, make_state
from sbrain.orchestrator import ArtifactTypes, Engine, Settings
from sbrain.orchestrator.engine import is_internal_key
from sbrain.orchestrator.errors import ProviderError, ToolCallExhausted
from sbrain.orchestrator.registry import PARTIAL, PARTIAL_SUFFIX, FailurePolicy, TaskRegistry, TaskSpec
from sbrain.orchestrator.store import CommitBatch, Store

SECRET = "SECRET-PARTIAL"


class PIn(SBModel):
    n: int = 0
    done: dict[str, str] = Field(default_factory=dict)


class POut(SBModel):
    value: str


class MiniFlow:
    """Flow 인터페이스의 최소 구현."""

    def __init__(self) -> None:
        self.rescued: list[str] = []
        self.unresumable: list[str] = []
        self.failed: list[str] = []

    def custom_step(self, step_id):
        return None

    def initial_redo_state(self, ctx, spec):
        return RedoState(task_id=spec.task_id)

    def build_instruction(self, ctx, spec, task, rework_input, rs, tools_for):
        return task.instruction, []

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

    def on_rescue(self, ctx, step_id, failure):
        self.rescued.append(step_id)
        ctx.run.queue = []
        ctx.run.state = make_state("공고선택", "사용자대기")

    def on_abort(self, ctx):
        pass

    def on_run_failed(self, ctx, reason):
        self.failed.append(reason)

    def on_cycle_failed(self, ctx, reason):
        pass


def scripted(plan: list[tuple[str, dict | None]], seen: list[dict]):
    """호출마다 plan에서 하나씩 꺼낸다. ('일시' | '입력', partial) → 그 오류로 재시도 소진 뒤 partial을 실어 올림, ('ok', _) → 성공.

    받은 결과(inp.done)를 seen에 남긴다 — 받은 것에 새로 받은 것을 더해 싣는 일은 Task가 한다.
    """
    calls = iter(plan)

    def fn(inp: PIn, tools) -> POut:
        seen.append(dict(inp.done))
        kind, partial = next(calls)
        if kind == "ok":
            return POut(value="ok")
        status = 503 if kind == "일시" else 400

        def down(timeout: float) -> None:
            raise ProviderError("down", status=status)
        try:
            tools.search("외부 호출", down)
        except ToolCallExhausted as e:
            raise ToolCallExhausted(error=e.error, error_kind=e.error_kind, tries=e.tries, call_id=e.call_id,
                                    detail=e.detail, partial=partial) from None
        raise AssertionError("도달하지 않음")
    return fn


def engine_with(clock: Clock, fn, *, bind_partial: bool = True, policy: FailurePolicy | None = None):
    registry = TaskRegistry()
    inputs = {"done": PARTIAL} if bind_partial else {}
    registry.register(TaskSpec("X", "외부 조회", "조율", "task", PIn, POut, inputs, {"value": "x.value"}, "value",
                               failure=policy or FailurePolicy()))
    registry.bind("X", fn)
    flow = MiniFlow()
    store = clock.backend.make_store(clock)
    types = ArtifactTypes({}, {PARTIAL_SUFFIX: dict[str, str]})
    engine = Engine(store=store, registry=registry, flow=flow, providers={}, types=types,
                    now=clock, sleep=lambda s: None)
    return engine, flow, store


def new_run(store: Store, clock: Clock, *, segment: str = "S1", resume_count: int = 0) -> str:
    now = clock()
    run = Run(run_id=f"r-{segment}", account_id="acc", state=make_state("계획서작성", "실행"), current_phase="document",
              settings_snapshot=Settings().dump(), updated_at=now, created_at=now, queue=["X"], segment=segment,
              segment_total=1, resume_count=resume_count)
    assert store.create_run(run, CommitBatch())
    return run.run_id


def wake(engine: Engine, store: Store, clock: Clock, rid: str) -> None:
    clock.t = store.load_run(rid).next_resume_at + timedelta(seconds=1)
    assert engine.tick(clock.t) == [rid]


def no_secret_anywhere(store: Store, rid: str) -> None:
    for rec in store.executions(rid):
        assert SECRET not in rec.model_dump_json()
    for log in store.call_logs(rid):
        assert SECRET not in log.model_dump_json()
    for ev in store.events(rid):
        assert SECRET not in ev.model_dump_json()
    assert SECRET not in store.load_run(rid).model_dump_json()


def test_partial_saved_on_resume_and_fed_back(clock):
    seen: list[dict] = []
    first = {"a": f"{SECRET}-A"}
    bigger = {"a": f"{SECRET}-A", "b": f"{SECRET}-B"}
    engine, flow, store = engine_with(clock, scripted([("일시", first), ("일시", bigger), ("ok", None)], seen))
    rid = new_run(store, clock)
    assert engine.advance(rid) == "재개대기"
    run = store.load_run(rid)   # 다시 읽어도 재개 위치에 참조가 남는다
    assert run.redo_state.partial_ref == "X.partial@1"
    assert store.get_latest_versions(rid)["X.partial"] == 1
    art = store.get_artifact(rid, "X.partial", 1)
    [rec] = store.executions(rid)
    assert art.value == first and art.producer == rec.execution_id
    assert "X.partial@1" not in rec.inputs   # 첫 실행은 받은 결과 없이 — 입력 모델 기본값
    # 재개 1 — 받은 결과가 들어가고 다시 소진, 더 큰 결과로 참조가 바뀐다
    wake(engine, store, clock, rid)
    run = store.load_run(rid)
    assert run.state.progress == "재개대기" and run.redo_state.partial_ref == "X.partial@2"
    assert store.get_artifact(rid, "X.partial", 2).value == bigger
    # 재개 2 — 성공, 재개 위치와 함께 참조가 사라진다(산출물은 남는다)
    wake(engine, store, clock, rid)
    assert seen == [{}, first, bigger]
    run = store.load_run(rid)
    assert run.state.progress == "사용자대기" and run.redo_state is None
    assert store.get_latest_versions(rid)["X.partial"] == 2
    [rec] = store.executions(rid)
    assert rec.status == "성공" and rec.resume_count == 2 and "X.partial@2" in rec.inputs
    assert flow.failed == []
    no_secret_anywhere(store, rid)


def test_empty_partial_is_not_saved_and_keeps_existing_ref(clock):
    seen: list[dict] = []
    first = {"a": f"{SECRET}-A"}
    engine, _, store = engine_with(clock, scripted([("일시", {}), ("일시", first), ("일시", None), ("ok", None)], seen))
    rid = new_run(store, clock)
    assert engine.advance(rid) == "재개대기"
    assert store.load_run(rid).redo_state.partial_ref is None
    assert "X.partial" not in store.get_latest_versions(rid)
    wake(engine, store, clock, rid)
    assert store.load_run(rid).redo_state.partial_ref == "X.partial@1"
    wake(engine, store, clock, rid)   # 받은 결과 없음 — 기존 참조 그대로
    assert store.load_run(rid).redo_state.partial_ref == "X.partial@1"
    assert store.get_latest_versions(rid)["X.partial"] == 1
    wake(engine, store, clock, rid)
    assert seen == [{}, {}, first, first]
    assert store.load_run(rid).redo_state is None


def test_task_without_binding_does_not_save(clock):
    seen: list[dict] = []
    engine, _, store = engine_with(clock, scripted([("일시", {"a": SECRET}), ("ok", None)], seen), bind_partial=False)
    rid = new_run(store, clock)
    assert engine.advance(rid) == "재개대기"
    assert store.load_run(rid).redo_state.partial_ref is None
    assert "X.partial" not in store.get_latest_versions(rid)
    wake(engine, store, clock, rid)
    assert seen == [{}, {}]


def test_permanent_error_does_not_save(clock):
    engine, flow, store = engine_with(clock, scripted([("입력", {"a": SECRET})], []))
    rid = new_run(store, clock)
    assert engine.advance(rid) == "실패"
    assert flow.failed == ["영구오류"]
    assert "X.partial" not in store.get_latest_versions(rid)
    no_secret_anywhere(store, rid)


def test_resume_cap_exceeded_does_not_save(clock):
    engine, flow, store = engine_with(clock, scripted([("일시", {"a": SECRET})], []))
    rid = new_run(store, clock, resume_count=Settings().resume.max_count)
    assert engine.advance(rid) == "실패"
    assert flow.failed == ["재개상한초과"]
    assert "X.partial" not in store.get_latest_versions(rid)
    no_secret_anywhere(store, rid)


def test_unresumable_and_rescue_do_not_save(clock):
    engine, flow, store = engine_with(clock, scripted([("일시", {"a": SECRET})], []),
                                      policy=FailurePolicy(resumable=False))
    rid = new_run(store, clock)
    engine.advance(rid)
    assert flow.unresumable == ["X"] and "X.partial" not in store.get_latest_versions(rid)
    engine, flow, store = engine_with(clock, scripted([("일시", {"a": SECRET})], []),
                                      policy=FailurePolicy(rescue_segments=frozenset({"S1"})))
    rid = new_run(store, clock)
    engine.advance(rid)
    assert flow.rescued == ["X"] and "X.partial" not in store.get_latest_versions(rid)


def test_partial_not_in_exception_text():
    e = ToolCallExhausted(error="호출실패", error_kind="일시", tries=6, call_id="c1", detail="503",
                          partial={"a": SECRET})
    assert e.partial == {"a": SECRET}
    assert SECRET not in str(e) and SECRET not in repr(e)
    assert ToolCallExhausted(error="호출실패", error_kind="일시", tries=1, call_id="c2").partial is None


def test_old_redo_state_reads_without_partial_ref():
    rs = RedoState.model_validate({"taskId": "X", "redoCount": 1})
    assert rs.partial_ref is None


def test_partial_type_is_registered_and_internal():
    _, suffix = artifact_types(build_registry())
    assert suffix[PARTIAL_SUFFIX] == dict[str, str]
    assert PARTIAL_SUFFIX == ".partial"
    assert is_internal_key("T-X.partial")
