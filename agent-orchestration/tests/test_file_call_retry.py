"""파일 호출 재시도 간격 · 엔진의 출력 파일 확인 재시도.

- 재시도 간격: 파일 호출(tools.files 넣기 · 읽기)에서 연결 오류 · 시간 초과(ConnectionError · TimeoutError 계열)는 늘리는 간격
  (2 · 4 · 8 · 16 · 32초 × (1 + 무작위)), 형식 오류(sha256 불일치) · 그 밖의 OSError(로컬 디스크 오류)는 2초 고정.
  search(backoff=False)는 그대로 고정. 대기 합 상한도 같은 규칙.
- 출력 파일 확인: 엔진의 출력 파일 확인(Engine.check_file_refs)도 파일 호출과 같은 재시도 · 기록을 거친다 — 참조 하나마다 파일 호출 하나
  (목적 check). 일시 오류 뒤 성공이면 그대로 저장, 다 쓰면 재개 대기(Task · 파일을 쓰는 규칙 단계 각각), 영구 오류면 실행 실패
  ('계속' 규칙 단계도 계속하지 않음). 확인 호출 기록은 그 실행 기록의 저장 묶음과 after_execution의 호출 목록에 들어간다.
  없는 파일 · 값 다름은 지금처럼 규격 위반이다.
가짜 저장소는 메모리 파일 저장소를 감싸 실패를 넣는다. 흐름 시험은 메모리 · SQLite 두 저장소에서 돈다(clock 픽스처).
네트워크 · 실제 대기 없음(sleep · rand 주입).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest
from conftest import Clock, make_app, to_screen6, x_settings
from flow_helpers import records_of_task, state

from sbrain.models import FileRef, Run
from sbrain.models.base import SBModel
from sbrain.models.clock import utc_now
from sbrain.models.run import RedoState, make_state
from sbrain.orchestrator import ArtifactTypes, Engine
from sbrain.orchestrator.errors import ProviderError, ToolCallExhausted
from sbrain.orchestrator.files import FileMeta, FileStore, MemoryFileStore
from sbrain.orchestrator.registry import FailurePolicy, TaskRegistry, TaskSpec
from sbrain.orchestrator.store import CommitBatch, Store
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

HTML = "text/html"
MD = "text/markdown"
BACKOFF = [2.0, 4.0, 8.0, 16.0, 32.0]


class FaultyStore:
    """메모리 파일 저장소를 감싸 정한 차례의 실패를 넣는다 — 연산(write · read · meta)마다 올릴 예외 목록.
    suffix를 주면 그 이름으로 끝나는 키에만 넣는다. 목록을 다 쓰면 안쪽 저장소를 그대로 부른다."""

    def __init__(self, inner: FileStore | None = None, *, suffix: str | None = None, **errors: list[Exception]) -> None:
        self.inner = inner if inner is not None else MemoryFileStore()
        self.suffix = suffix
        self.errors = {op: list(v) for op, v in errors.items()}
        self.meta_calls = 0

    def _fault(self, op: str, key: str) -> None:
        if self.suffix is not None and not key.endswith(self.suffix):
            return
        queue = self.errors.get(op)
        if queue:
            raise queue.pop(0)

    def write(self, key, data, meta):
        self._fault("write", key)
        self.inner.write(key, data, meta)

    def read(self, key):
        self._fault("read", key)
        return self.inner.read(key)

    def meta(self, key):
        self.meta_calls += 1
        self._fault("meta", key)
        return self.inner.meta(key)

    def delete_prefix(self, prefix):
        self.inner.delete_prefix(prefix)


def _no_secret(logs, *secrets: str) -> None:
    text = json.dumps([log.dump() for log in logs], ensure_ascii=False)
    for s in secrets:
        assert s not in text


# ── 파일 호출의 재시도 간격 (tools) ───────────────────────────────
def file_tools(store: FileStore, *, rand=lambda: 0.0, **over) -> tuple[Tools, CallSink, list[float]]:
    sink, sleeps = CallSink(), []
    cfg = ToolsConfig(**{"agent": "구현", "provider": None, "model": None, "temperature": None, "timeout_sec": 30,
                         "retry_count": 5, "retry_interval_sec": 2.0, **over})
    ctx = ToolsContext(run_id="r1", execution_id="e1", task_id="T-B1", providers={}, sink=sink, now=utc_now,
                       sleep=sleeps.append, rand=rand, files=store, run_progress=lambda: "실행")
    return Tools(cfg, ctx), sink, sleeps


def stored_ref(store: FileStore) -> FileRef:
    """읽기 시험용 — 이 실행 건(r1)의 파일 하나를 실패 없이 넣는다."""
    tools, _, _ = file_tools(store)
    return tools.files.put("a.md", b"# a", MD)


def call(op: str, store: FaultyStore, tools: Tools) -> None:
    if op == "put":
        tools.files.put("index.html", b"<html/>", HTML)
    else:
        tools.files.get(stored_ref(store.inner))


NETWORK = [ConnectionError(), TimeoutError(), ConnectionResetError()]


@pytest.mark.parametrize("op", ["put", "get"])
@pytest.mark.parametrize("error", NETWORK, ids=lambda e: type(e).__name__)
def test_file_network_errors_back_off(op, error):
    store = FaultyStore(**{"write" if op == "put" else "read": [error] * 6})
    tools, sink, sleeps = file_tools(store, rand=lambda: 0.0)
    with pytest.raises(ToolCallExhausted) as e:
        call(op, store, tools)
    assert (e.value.tries, e.value.error_kind) == (6, "일시")
    assert e.value.error == ("응답지연" if isinstance(error, TimeoutError) else "호출실패")   # 분류는 그대로
    assert sleeps == BACKOFF
    [log] = sink.drain()
    assert (log.call_type, log.purpose, log.final_outcome) == ("file", op, "소진")


@pytest.mark.parametrize("op", ["put", "get"])
def test_file_network_errors_back_off_with_jitter_then_succeed(op):
    values = iter([0.5, 0.2])
    store = FaultyStore(**{"write" if op == "put" else "read": [ConnectionError(), TimeoutError()]})
    tools, sink, sleeps = file_tools(store, rand=lambda: next(values))
    call(op, store, tools)
    assert sleeps == pytest.approx([2.0 * 1.125, 4.0 * 1.05])
    [log] = sink.drain()
    assert [t.outcome for t in log.tries] == ["호출실패", "응답지연", "성공"]


@pytest.mark.parametrize("op", ["put", "get"])
@pytest.mark.parametrize("error", [OSError("disk"), PermissionError("denied"), IsADirectoryError()],
                         ids=lambda e: type(e).__name__)
def test_file_disk_errors_wait_fixed(op, error):
    store = FaultyStore(**{"write" if op == "put" else "read": [error] * 6})
    tools, _, sleeps = file_tools(store, rand=lambda: 0.9)
    with pytest.raises(ToolCallExhausted) as e:
        call(op, store, tools)
    assert (e.value.tries, e.value.error, e.value.error_kind) == (6, "호출실패", "일시")
    assert sleeps == [2.0] * 5


def test_file_hash_mismatch_waits_fixed():
    inner = MemoryFileStore()
    tools, _, sleeps = file_tools(inner, rand=lambda: 0.9)
    ref = stored_ref(inner)
    forged = ref.model_copy(update={"sha256": hashlib.sha256(b"other").hexdigest()})
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.get(forged)
    assert e.value.error == "형식오류" and sleeps == [2.0] * 5


def test_file_retry_number_counts_all_failures():
    """n은 앞 시도의 실패 종류와 관계없이 센다 — 디스크 오류(2초 고정) 뒤 연결 오류면 4초."""
    store = FaultyStore(write=[OSError("disk"), ConnectionError()])
    tools, _, sleeps = file_tools(store, rand=lambda: 0.0)
    tools.files.put("index.html", b"<html/>", HTML)
    assert sleeps == [2.0, 4.0]


def test_file_wait_cap_applies():
    store = FaultyStore(write=[TimeoutError()] * 6)
    tools, _, sleeps = file_tools(store, wait_cap_sec=45.0)
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.put("index.html", b"<html/>", HTML)
    assert e.value.tries == 5 and sleeps == [2.0, 4.0, 8.0, 16.0]                # 30 + 32 > 45


def test_file_permanent_provider_error_is_not_retried():
    store = FaultyStore(write=[ProviderError("거부", status=403, code="access_denied")] * 6)
    tools, sink, sleeps = file_tools(store)
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.put("index.html", b"<html/>", HTML)
    assert (e.value.tries, e.value.error_kind, e.value.code) == (1, "운영", "access_denied") and sleeps == []
    assert [t.detail for t in sink.drain()[0].tries] == ["status=403 code=access_denied"]


def test_search_without_backoff_stays_fixed():
    tools, _, sleeps = file_tools(MemoryFileStore(), rand=lambda: 0.9)
    errors = [TimeoutError(), ConnectionError()] * 3

    def fn(timeout):
        raise errors.pop(0)
    with pytest.raises(ToolCallExhausted):
        tools.search("검색", fn, backoff=False)
    assert sleeps == [2.0] * 5


# ── 엔진의 출력 파일 확인 — 작은 흐름 ─────────────────────────────
class NoIn(SBModel):
    n: int = 0


class OneFile(SBModel):
    file: FileRef


class MiniFlow:
    """Flow 인터페이스의 최소 구현 — 대기열이 비면 사용자대기로. after_execution이 받은 호출 목록을 남긴다."""

    def __init__(self) -> None:
        self.failed: list[str] = []
        self.after: list[tuple[str, str, list[tuple[str, str]]]] = []

    def custom_step(self, step_id):
        return None

    def initial_redo_state(self, ctx, spec):
        return RedoState(task_id=spec.task_id)

    def build_instruction(self, ctx, spec, task, rework_input, rs, tools_for):
        return task.instruction, []

    def today(self, ctx):
        return date(2026, 10, 17)

    def constant(self, ctx, name):
        raise KeyError(name)

    def value(self, ctx, name, spec):
        raise KeyError(name)

    def after_execution(self, ctx, spec, rec, calls):
        self.after.append((spec.task_id, rec.execution_id, [(c.call_type, c.purpose) for c in calls]))

    def after_step(self, ctx, step_id, outcome):
        pass

    def on_queue_empty(self, ctx):
        ctx.run.state = make_state("결과물", "사용자대기")
        ctx.run.segment = None

    def on_unresumable(self, ctx, step_id, outcome):
        ctx.run.queue = []

    def on_rescue(self, ctx, step_id, failure):
        pass

    def on_abort(self, ctx):
        pass

    def on_run_failed(self, ctx, reason):
        self.failed.append(reason)

    def on_cycle_failed(self, ctx, reason):
        pass


FILE_NAME = {"task": "index.html", "rule": "README.md"}


def step(kind: str, task_id: str = "X") -> tuple[TaskSpec, object]:
    """kind 'task' — tools.files로 넣는 Task(재개할 수 있음), 'rule' — 파일을 쓰는 규칙 단계(오류 나도 계속 — G-04와 같은 정책)."""
    if kind == "task":
        spec = TaskSpec(task_id, task_id, "구현", "task", NoIn, OneFile, {}, {"file": f"{task_id}.file"}, "file")

        def fn(inp, tools):
            return OneFile(file=tools.files.put(FILE_NAME["task"], b"<html/>", HTML))
    else:
        spec = TaskSpec(task_id, task_id, "조율", "rule", NoIn, OneFile, {}, {"file": f"{task_id}.file"}, "file",
                        failure=FailurePolicy(on_step_error="continue"), writes_files=True)

        def fn(inp, files):
            return OneFile(file=files.put(FILE_NAME["rule"], b"# guide", MD))
    return spec, fn


def build(clock: Clock, files: FileStore | None, specs: list[tuple[TaskSpec, object]]):
    registry = TaskRegistry()
    for spec, fn in specs:
        registry.register(spec)
        registry.bind(spec.task_id, fn)
    flow, sleeps = MiniFlow(), []
    store = clock.backend.make_store(clock)
    engine = Engine(store=store, registry=registry, flow=flow, providers={},
                    types=ArtifactTypes(registry.artifact_types()), now=clock, sleep=sleeps.append, files=files)
    return engine, flow, store, sleeps


def start(store: Store, clock: Clock, queue: list[str], run_id: str = "run1") -> str:
    now = clock()
    run = Run(run_id=run_id, account_id="acc", state=make_state("프로토타입제작", "실행"), current_phase="artifact",
              settings_snapshot=x_settings(), updated_at=now, created_at=now, queue=queue, segment="S",
              segment_total=len(queue))
    assert store.create_run(run, CommitBatch())
    return run.run_id


def backoff_ok(sleeps: list[float], n: int) -> None:
    """엔진의 tools는 기본 난수를 쓴다 — 늘리는 간격의 범위(계산 값 ~ 1.25배)만 본다."""
    assert len(sleeps) == n
    for wait, base in zip(sleeps, BACKOFF):
        assert base <= wait <= base * 1.25


KINDS = ["task", "rule"]


@pytest.mark.parametrize("kind", KINDS)
def test_check_transient_then_success_is_stored_and_recorded(clock, kind):
    files = FaultyStore(meta=[ConnectionError(), TimeoutError()])
    engine, flow, store, sleeps = build(clock, files, [step(kind)])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "사용자대기"
    [rec] = store.executions(rid)
    assert rec.status == "성공" and rec.input_tokens is None
    ref = engine.open_context(store.load_run(rid)).get("X.file")
    assert files.inner.meta(ref.key) is not None
    logs = store.call_logs(rid)
    assert [(l.call_type, l.purpose, l.final_outcome) for l in logs] == [("file", "put", "성공"),
                                                                       ("file", "check", "성공")]
    check = logs[1]
    assert [t.outcome for t in check.tries] == ["호출실패", "응답지연", "성공"]
    assert (check.task_id, check.execution_id, check.item_key, check.provider, check.model) == (
        "X", rec.execution_id, None, None, None)
    assert [l.purpose for l in store.execution_calls(rec.execution_id)] == ["put", "check"]   # 그 실행 기록의 저장 묶음
    assert flow.after == [("X", rec.execution_id, [("file", "put"), ("file", "check")])]   # 이번 호출 목록에도
    backoff_ok(sleeps, 2)
    _no_secret(logs, ref.key, FILE_NAME[kind], ref.sha256)


@pytest.mark.parametrize("kind", KINDS)
def test_check_exhausted_waits_for_resume(clock, kind):
    files = FaultyStore(meta=[ConnectionError()] * 6)
    engine, flow, store, sleeps = build(clock, files, [step(kind)])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "재개대기"
    run = store.load_run(rid)
    assert (run.current_task, run.last_error_kind) == ("X", "일시")
    [rec] = store.executions(rid)
    assert (rec.status, rec.error, rec.error_kind) == ("재개대기", "호출실패", "일시")
    [put, check] = store.call_logs(rid)
    assert (put.purpose, check.purpose, check.final_outcome, len(check.tries)) == ("put", "check", "소진", 6)
    kinds = [e.kind for e in store.events(rid)]
    assert "재개예약" in kinds and "단계오류계속" not in kinds and "단계오류" not in kinds   # 단계 오류 처리로 가지 않는다
    assert flow.after == [] and flow.failed == []
    backoff_ok(sleeps, 5)

    clock.advance(minutes=16)                                                     # 재개 — 같은 실행 기록을 이어 써서 성공
    assert engine.tick(clock.t) == [rid]
    assert store.load_run(rid).state.progress == "사용자대기"
    [again] = store.executions(rid)
    assert (again.execution_id, again.status, again.resume_count) == (rec.execution_id, "성공", 1)
    assert [l.purpose for l in store.execution_calls(rec.execution_id)] == ["put", "check", "put", "check"]


@pytest.mark.parametrize("kind", KINDS)
def test_check_permanent_error_fails_run_without_continuing(clock, kind):
    files = FaultyStore(meta=[ProviderError("거부 설명", status=403, code="access_denied")] * 3)
    engine, flow, store, sleeps = build(clock, files, [step(kind)])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "실패"
    run = store.load_run(rid)
    assert run.admin_alert is True and run.last_error_kind == "운영"
    [rec] = store.executions(rid)
    assert (rec.status, rec.error, rec.error_kind) == ("실패", "호출실패", "운영")
    assert flow.failed == ["영구오류"]
    kinds = [e.kind for e in store.events(rid)]
    assert "단계오류계속" not in kinds                                              # '계속' 규칙 단계도 계속하지 않는다
    [_, check] = store.call_logs(rid)
    assert (check.purpose, check.final_outcome) == ("check", "소진")
    assert [t.detail for t in check.tries] == ["status=403 code=access_denied"] and sleeps == []
    assert "거부 설명" not in json.dumps([l.dump() for l in store.call_logs(rid)], ensure_ascii=False)


def test_check_disk_errors_wait_fixed_then_resume(clock):
    """로컬 폴더의 디스크 오류(연결 · 시간 초과가 아닌 OSError)도 같은 규칙 — 2초 고정으로 다시 하고, 다 쓰면 재개 대기."""
    files = FaultyStore(meta=[PermissionError("denied")] * 6)
    engine, flow, store, sleeps = build(clock, files, [step("task")])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "재개대기"
    assert sleeps == [2.0] * 5
    [rec] = store.executions(rid)
    assert (rec.error, rec.error_kind) == ("호출실패", "일시")


@pytest.mark.parametrize("case", ["missing", "size", "sha"])
def test_missing_or_changed_ref_is_still_contract_error(clock, case):
    def fn(inp, tools):
        real = tools.files.put("index.html", b"<html/>", HTML)
        if case == "missing":
            return OneFile(file=real.model_copy(update={"key": real.key.rsplit("/", 2)[0] + "/zz/index.html"}))
        if case == "size":
            return OneFile(file=real.model_copy(update={"size": real.size + 1}))
        return OneFile(file=real.model_copy(update={"sha256": "0" * 64}))

    spec, _ = step("task")
    engine, flow, store, _ = build(clock, FaultyStore(), [(spec, fn)])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "실패"
    [rec] = store.executions(rid)
    assert rec.error.startswith("ContractError") and flow.failed == ["운영오류"]
    assert "index.html" not in rec.error and "/zz/" not in rec.error
    assert [(l.purpose, l.final_outcome) for l in store.call_logs(rid)] == [("put", "성공"), ("check", "성공")]


def test_other_run_ref_and_missing_store_make_no_check_call(clock):
    other = FileRef(key="otherrun/e9/u9/index.html", name="index.html", media_type=HTML, size=1, sha256="0" * 64)
    spec = TaskSpec("X", "X", "구현", "rule", NoIn, OneFile, {}, {"file": "X.file"}, "file")
    files = FaultyStore()
    engine, flow, store, _ = build(clock, files, [(spec, lambda inp: OneFile(file=other))])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "실패"                                          # 다른 실행 건 — 저장소를 보지 않는다
    assert store.call_logs(rid) == [] and files.meta_calls == 0

    mine = other.model_copy(update={"key": "run2/e9/u9/index.html"})
    engine, flow, store, _ = build(clock, None, [(spec, lambda inp: OneFile(file=mine))])
    rid = start(store, clock, ["X"], run_id="run2")
    assert engine.advance(rid) == "실패"                                          # 저장소 없음 — 그대로 규격 위반
    [rec] = store.executions(rid)
    assert rec.error.startswith("ContractError") and "파일 저장소 없음" in rec.error
    assert store.call_logs(rid) == []


def test_direct_check_records_into_given_execution(clock):
    """store_outputs를 거치지 않는 전용 실행이 직접 부르는 길 — check_file_refs(ctx, spec, out, rec).
    sink를 주지 않으면 확인 호출을 그 실행 기록의 저장 묶음으로 옮기고, 주면 거기에만 남긴다."""
    files = FaultyStore(meta=[ConnectionError()])
    spec, fn = step("task")
    engine, flow, store, sleeps = build(clock, files, [(spec, fn)])
    rid = start(store, clock, [])
    ctx = engine.open_context(store.load_run(rid))
    rec = engine.open_execution(ctx, spec, RedoState(task_id="X"))
    data = b"<html/>"
    key = f"{rid}/{rec.execution_id}/u1/index.html"
    files.inner.write(key, data, FileMeta(name="index.html", media_type=HTML, size=len(data),
                                          sha256=hashlib.sha256(data).hexdigest()))
    out = OneFile(file=FileRef(key=key, name="index.html", media_type=HTML, size=len(data),
                               sha256=hashlib.sha256(data).hexdigest()))
    engine.check_file_refs(ctx, spec, out, rec)
    [log] = ctx.batch.call_logs
    assert (log.purpose, log.execution_id, [t.outcome for t in log.tries]) == ("check", rec.execution_id,
                                                                               ["호출실패", "성공"])
    sink = CallSink()
    engine.check_file_refs(ctx, spec, out, rec, sink=sink)
    assert len(ctx.batch.call_logs) == 1 and [l.purpose for l in sink.drain()] == ["check"]


def test_one_check_call_per_ref(clock):
    class Two(SBModel):
        first: FileRef
        more: list[FileRef]

    def fn(inp, tools):
        a = tools.files.put("a.html", b"a", HTML)
        b = tools.files.put("b.md", b"b", MD)
        return Two(first=a, more=[b, a])

    spec = TaskSpec("X", "X", "구현", "task", NoIn, Two, {}, {"first": "X.first", "more": "X.more"}, "first")
    engine, flow, store, _ = build(clock, FaultyStore(), [(spec, fn)])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "사용자대기"
    assert [l.purpose for l in store.call_logs(rid)] == ["put", "put", "check", "check", "check"]


# ── 출력 파일 확인 — S-Brain 흐름 (스텁 조립) ─────────────────────
def faulty_app(clock: Clock, suffix: str, errors: list[Exception]):
    app = make_app(clock)
    files = FaultyStore(app.engine.files, suffix=suffix, meta=errors)
    app.engine.files = files                                                     # 읽기(orchestrator.files)는 같은 안쪽 저장소
    return app, files


def to_artifacts(app) -> str:
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    return rid


# T-B1 출력은 진입 파일 참조를 두 칸(prototype.entryFile · entryFile)에 싣는다 — 참조 하나마다 확인 호출 하나라 성공 때 둘
@pytest.mark.parametrize("task_id, suffix, outcomes", [("T-B1", "/index.html", ["소진", "성공", "성공"]),
                                                       ("G-04", "/README.md", ["소진", "성공"])])
def test_sbrain_check_exhausted_resumes(clock, task_id, suffix, outcomes):
    app, _ = faulty_app(clock, suffix, [ConnectionError()] * 6)
    rid = to_artifacts(app)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.current_task) == ("재개대기", task_id)
    [rec] = records_of_task(app, rid, task_id)
    assert (rec.status, rec.error_kind) == ("재개대기", "일시")
    clock.advance(minutes=16)
    app.orchestrator.tick(clock.t)
    assert state(app, rid) == ("산출물확인", "사용자대기")
    [rec] = records_of_task(app, rid, task_id)
    assert (rec.status, rec.resume_count) == ("성공", 1)
    checks = [l for l in app.store.execution_calls(rec.execution_id) if l.purpose == "check"]
    assert [c.final_outcome for c in checks] == outcomes


def test_sbrain_g04_check_permanent_error_fails_run(clock):
    app, _ = faulty_app(clock, "/README.md", [ProviderError("거부", status=403)] * 3)
    rid = to_artifacts(app)
    assert app.store.load_run(rid).state.progress == "실패"
    [rec] = records_of_task(app, rid, "G-04")
    assert (rec.status, rec.error_kind) == ("실패", "운영")
    assert "단계오류계속" not in [e.kind for e in app.store.events(rid)]
