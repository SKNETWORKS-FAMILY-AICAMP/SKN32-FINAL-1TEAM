"""파일 참조(FileRef) · 파일 저장소 · 파일 창구(tools.files) · 엔진의 출력 참조 확인 (spec 4.1 ~ 4.4 · 4.9).

- 이름 · 키 · 형식 · 크기 규칙(Windows 예약 이름 포함)
- 저장소 두 개(메모리 · 로컬 폴더): 같은 키 같은 내용은 성공, 다른 내용은 거절, 없는 키, 접두어째 지우기(여러 번 안전)
- 파일 창구: 넣기 거절(저장소를 부르지 않음) · 실행 상태 확인 · 같은 키 재시도 안전 · 다른 실행 건 읽기 거절 · sha256 대조 ·
  없는 키(입력 오류, 재시도 없음) · 호출 기록에 내용 · 이름 · 키 없음
- 엔진: 출력 안 FileRef 확인(남의 실행 건 키 · 없는 키 · 값 위조 → 규격 위반, 이전 실행 기록 참조 넘기기 → 통과),
  파일을 쓰는 규칙 단계는 run(inp, files), 표시 없는 규칙 단계는 run(inp)
엔진 시험은 메모리 · SQLite 실행 저장소와 메모리 · 로컬 폴더 파일 저장소를 섞어 돈다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from conftest import Clock, x_settings

from sbrain.models import FileRef, Run
from sbrain.models.base import SBModel
from sbrain.models.files import (
    ALLOWED_MEDIA_TYPES, MAX_FILE_BYTES, file_key_problem, file_name_problem,
)
from sbrain.models.clock import utc_now
from sbrain.models.run import RedoState, make_state
from sbrain.orchestrator import ArtifactTypes, Engine
from sbrain.orchestrator.errors import FileRejected, ToolCallExhausted
from sbrain.orchestrator.files import (
    FileConflict, FileMeta, FileMissing, FileStore, LocalFolderFileStore, MemoryFileStore,
)
from sbrain.orchestrator.registry import FailurePolicy, TaskRegistry, TaskSpec, art
from sbrain.orchestrator.store import CommitBatch, Store
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

HTML = "text/html"
SHA_ZERO = "0" * 64


# ── 이름 · 키 · 형식 · 크기 ───────────────────────────────────

def test_allowed_media_types_and_size_limit():
    assert set(ALLOWED_MEDIA_TYPES) == {
        "text/html", "image/svg+xml", "image/png", "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/x-hwp", "application/hwp+zip", "application/json",
    }
    assert len(ALLOWED_MEDIA_TYPES) == 8
    assert MAX_FILE_BYTES == 30 * 1024 * 1024 == 31_457_280


@pytest.mark.parametrize("name", ["index.html", "onepage.svg", "README.md", "plan.docx", "a-b_c.1.json", "x",
                                  "a" * 100, "con1.html", "COM10.txt", "console.md"])
def test_valid_names(name):
    assert file_name_problem(name) is None


@pytest.mark.parametrize("name", ["", "a" * 101, ".hidden", "trail.", "a/b.html", "a\\b.html", "a b.html",
                                  "한글.md", "x:y", "..", ".", "CON", "con.txt", "Prn.html", "aux", "NUL.tar.gz",
                                  "com1.html", "COM9", "lpt1.md", "LPT9.svg"])
def test_invalid_names(name):
    problem = file_name_problem(name)
    assert problem is not None
    if name:
        assert name not in problem   # 거절 사유에 이름을 넣지 않는다


@pytest.mark.parametrize("key", ["r1/e1/u1/index.html", "run-1/exec_2/abc.def/README.md", "r1/x.png"])
def test_valid_keys(key):
    assert file_key_problem(key) is None


@pytest.mark.parametrize("key", ["", "index.html", "/r1/e1/index.html", "r1//index.html", "r1/../index.html",
                                 "r1/./index.html", "C:/r1/index.html", "r1\\e1\\index.html", "r1/e1/CON",
                                 "r1/e 1/index.html", "r1/e1/", "r1/e1/.secret"])
def test_invalid_keys(key):
    problem = file_key_problem(key)
    assert problem is not None
    if key:
        assert key not in problem


def _ref(**kw) -> dict:
    base = {"key": "r1/e1/u1/index.html", "name": "index.html", "mediaType": HTML, "size": 3, "sha256": SHA_ZERO}
    base.update(kw)
    return base


def test_file_ref_json_names_and_validation():
    ref = FileRef.model_validate(_ref())
    assert ref.dump() == _ref()
    for bad in (_ref(sha256="A" * 64), _ref(sha256="0" * 63), _ref(size=-1), _ref(size=MAX_FILE_BYTES + 1),
                _ref(mediaType="text/plain"), _ref(name="other.html"), _ref(key="r1//index.html"),
                _ref(key="r1/e1/u1/CON", name="CON"), _ref(extra=1)):
        with pytest.raises(ValueError):
            FileRef.model_validate(bad)
    assert FileRef.model_validate(_ref(size=MAX_FILE_BYTES)).size == MAX_FILE_BYTES


# ── 저장소 ──────────────────────────────────────────────────

@pytest.fixture(params=["memory", "local"])
def file_store(request, tmp_path) -> FileStore:
    if request.param == "memory":
        return MemoryFileStore()
    return LocalFolderFileStore(tmp_path / "artifacts", create=True)


def _meta(data: bytes, name: str = "index.html", media: str = HTML) -> FileMeta:
    return FileMeta(name=name, media_type=media, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def test_store_write_read_meta_and_same_key(file_store):
    data = b"<html></html>"
    file_store.write("r1/e1/u1/index.html", data, _meta(data))
    assert file_store.read("r1/e1/u1/index.html") == data
    assert file_store.meta("r1/e1/u1/index.html") == _meta(data)
    file_store.write("r1/e1/u1/index.html", data, _meta(data))           # 같은 키 같은 내용 — 재시도는 성공
    with pytest.raises(FileConflict):
        file_store.write("r1/e1/u1/index.html", b"other", _meta(b"other"))   # 같은 키 다른 내용 — 불변
    assert file_store.read("r1/e1/u1/index.html") == data
    assert file_store.meta("r1/e1/u1/nothing.html") is None
    with pytest.raises(FileMissing):
        file_store.read("r1/e1/u1/nothing.html")


def test_store_delete_prefix_is_idempotent(file_store):
    for key in ("r1/e1/u1/a.html", "r1/e2/u2/b.png", "r10/e1/u1/c.html", "r2/e1/u1/d.md"):
        file_store.write(key, b"x", _meta(b"x", key.rsplit("/", 1)[1]))
    file_store.delete_prefix("r1/")
    assert file_store.meta("r1/e1/u1/a.html") is None and file_store.meta("r1/e2/u2/b.png") is None
    assert file_store.meta("r10/e1/u1/c.html") is not None                 # 접두어가 비슷한 다른 실행 건은 남는다
    assert file_store.meta("r2/e1/u1/d.md") is not None
    file_store.delete_prefix("r1/")                                         # 이미 없으면 성공
    file_store.delete_prefix("r9/")


def test_store_rejects_bad_keys_before_touching_anything(file_store):
    for key in ("../escape/x.html", "r1/../../x.html", "/abs/x.html", "r1\\x.html"):
        with pytest.raises(ValueError) as e:
            file_store.write(key, b"x", _meta(b"x", "x.html"))
        assert key not in str(e.value)
        with pytest.raises(ValueError):
            file_store.read(key)
    with pytest.raises(ValueError):
        file_store.delete_prefix("../")


def test_local_store_layout_and_root(tmp_path):
    root = tmp_path / "files"
    store = LocalFolderFileStore(root, create=True)
    data = b"# readme"
    store.write("r1/e1/u1/README.md", data, _meta(data, "README.md", "text/markdown"))
    assert (root / "r1" / "e1" / "u1" / "README.md").read_bytes() == data
    names = sorted(p.name for p in (root / "r1" / "e1" / "u1").iterdir())
    assert all(n == "README.md" or n.startswith(".") for n in names)      # 옆 파일은 점으로 시작 — 파일 이름과 겹치지 않는다
    assert not [n for n in names if n.endswith(".tmp")]                   # 임시 파일이 남지 않는다
    again = LocalFolderFileStore(root)                                    # 다른 프로세스가 같은 폴더를 연다
    assert again.read("r1/e1/u1/README.md") == data
    assert again.meta("r1/e1/u1/README.md") == _meta(data, "README.md", "text/markdown")
    with pytest.raises(ValueError) as e:
        LocalFolderFileStore(Path("relative/files"))
    assert "relative" not in str(e.value)


# ── 파일 창구 tools.files ─────────────────────────────────────

class FlakyStore:
    """처음 n번 쓰기는 실제로 쓴 뒤 OSError를 올린다(쓰기 뒤 끊김) — 같은 키 재시도가 안전한지 본다."""

    def __init__(self, inner: FileStore, fail_writes: int = 1, fail_reads: int = 0) -> None:
        self.inner, self.fail_writes, self.fail_reads = inner, fail_writes, fail_reads
        self.writes: list[str] = []

    def write(self, key, data, meta):
        self.writes.append(key)
        self.inner.write(key, data, meta)
        if self.fail_writes > 0:
            self.fail_writes -= 1
            raise OSError("디스크 끊김")

    def read(self, key):
        if self.fail_reads > 0:
            self.fail_reads -= 1
            raise OSError("디스크 끊김")
        return self.inner.read(key)

    def meta(self, key):
        return self.inner.meta(key)

    def delete_prefix(self, prefix):
        self.inner.delete_prefix(prefix)


class CountingStore(FlakyStore):
    def __init__(self, inner: FileStore) -> None:
        super().__init__(inner, 0, 0)


def file_tools(store: FileStore | None, *, progress: str | None = "실행", retry: int = 2,
               run_id: str = "r1", execution_id: str = "e1") -> tuple[Tools, CallSink]:
    sink = CallSink()
    cfg = ToolsConfig(agent="구현", provider=None, model=None, temperature=None, timeout_sec=5,
                      retry_count=retry, retry_interval_sec=0)
    ctx = ToolsContext(run_id=run_id, execution_id=execution_id, task_id="T-B1", providers={}, sink=sink,
                       now=utc_now, sleep=lambda s: None, files=store, run_progress=lambda: progress)
    return Tools(cfg, ctx), sink


def _no_secret(sink_logs, *secrets: str | bytes) -> None:
    text = json.dumps([log.dump() for log in sink_logs], ensure_ascii=False)
    for s in secrets:
        assert (s.decode() if isinstance(s, bytes) else s) not in text


def test_put_returns_ref_and_logs_without_content(file_store):
    tools, sink = file_tools(file_store)
    data = "<html>비밀 내용</html>".encode()
    ref = tools.files.put("index.html", data, HTML)
    assert ref.key.startswith("r1/e1/") and ref.key.endswith("/index.html") and len(ref.key.split("/")) == 4
    assert (ref.name, ref.media_type, ref.size, ref.sha256) == ("index.html", HTML, len(data),
                                                               hashlib.sha256(data).hexdigest())
    assert file_store.read(ref.key) == data
    assert tools.files.get(ref) == data
    logs = sink.drain()
    assert [(l.call_type, l.purpose, l.final_outcome) for l in logs] == [("file", "put", "성공"), ("file", "get", "성공")]
    assert all(l.provider is None and l.model is None and l.input_tokens is None for l in logs)
    _no_secret(logs, data, "비밀", ref.key, "index.html", ref.sha256)
    again = tools.files.put("index.html", data, HTML)                    # 같은 내용 · 같은 이름이라도 새 키
    assert again.key != ref.key


@pytest.mark.parametrize(("name", "size", "media"), [
    ("../x.html", 1, HTML), ("CON.html", 1, HTML), ("a b.html", 1, HTML),
    ("x.txt", 1, "text/plain"), ("big.png", MAX_FILE_BYTES + 1, "image/png"),
])
def test_put_rejects_before_store(name, size, media):
    data = b"\0" * size
    store = CountingStore(MemoryFileStore())
    tools, sink = file_tools(store)
    with pytest.raises(FileRejected) as e:
        tools.files.put(name, data, media)
    assert store.writes == [] and sink.drain() == []                     # 저장소를 부르지 않는다 · 재시도 없음
    assert name not in str(e.value)


def test_put_accepts_exact_limit_and_all_types():
    tools, _ = file_tools(MemoryFileStore())
    assert tools.files.put("big.png", b"\0" * MAX_FILE_BYTES, "image/png").size == MAX_FILE_BYTES
    for i, media in enumerate(sorted(ALLOWED_MEDIA_TYPES)):
        assert tools.files.put(f"f{i}.bin", b"{}", media).media_type == media
    assert tools.files.put("empty.json", b"", "application/json").size == 0


@pytest.mark.parametrize("progress", ["중단", "실패", "완료", "사용자대기", "재개대기", None])
def test_put_refused_unless_run_is_running(progress):
    store = CountingStore(MemoryFileStore())
    tools, sink = file_tools(store, progress=progress)
    with pytest.raises(FileRejected):
        tools.files.put("index.html", b"x", HTML)
    assert store.writes == [] and sink.drain() == []


def test_put_same_key_retry_is_safe(file_store):
    store = FlakyStore(file_store, fail_writes=1)
    tools, sink = file_tools(store)
    ref = tools.files.put("index.html", b"<html/>", HTML)
    assert store.writes == [ref.key, ref.key]                             # 재시도는 같은 키
    assert file_store.read(ref.key) == b"<html/>"
    [log] = sink.drain()
    assert [t.outcome for t in log.tries] == ["호출실패", "성공"] and log.tries[0].error_kind == "일시"
    _no_secret([log], ref.key, "디스크 끊김")


def test_put_disk_errors_exhaust_as_temporary():
    store = FlakyStore(MemoryFileStore(), fail_writes=10)
    tools, sink = file_tools(store, retry=2)
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.put("index.html", b"x", HTML)
    assert (e.value.error_kind, e.value.tries) == ("일시", 3)
    assert "index.html" not in str(e.value)


def test_get_rejects_other_run_and_checks_hash(file_store):
    other, _ = file_tools(file_store, run_id="r2")
    theirs = other.files.put("index.html", b"theirs", HTML)
    tools, sink = file_tools(file_store)
    with pytest.raises(FileRejected) as e:
        tools.files.get(theirs)                                           # 다른 실행 건의 파일은 읽지 못한다
    assert theirs.key not in str(e.value) and sink.drain() == []

    mine = tools.files.put("index.html", b"mine", HTML)
    sink.drain()
    forged = mine.model_copy(update={"sha256": hashlib.sha256(b"other").hexdigest()})
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.get(forged)                                           # 내용이 참조와 다름 — 형식 오류(재시도)
    assert (e.value.error, e.value.error_kind, e.value.tries) == ("형식오류", "일시", 3)

    missing = FileRef(key="r1/e1/zz/none.html", name="none.html", media_type=HTML, size=1, sha256=SHA_ZERO)
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.get(missing)                                          # 없는 키 — 입력 오류, 재시도하지 않는다
    assert (e.value.error_kind, e.value.tries) == ("입력", 1)
    logs = sink.drain()
    assert [l.purpose for l in logs] == ["get", "get"]
    _no_secret(logs, mine.key, missing.key, "none.html", "mine")


def test_get_retries_disk_errors():
    inner = MemoryFileStore()
    tools, _ = file_tools(inner)
    ref = tools.files.put("a.md", b"# a", "text/markdown")
    flaky, sink = file_tools(FlakyStore(inner, fail_writes=0, fail_reads=1))
    assert flaky.files.get(ref) == b"# a"
    [log] = sink.drain()
    assert [t.outcome for t in log.tries] == ["호출실패", "성공"]


def test_files_outside_execution_is_an_error():
    tools, _ = file_tools(None)
    with pytest.raises(RuntimeError):
        tools.files.put("index.html", b"x", HTML)
    with pytest.raises(RuntimeError):
        tools.files.get(FileRef(key="r1/e1/u/a.html", name="a.html", media_type=HTML, size=0, sha256=SHA_ZERO))


# ── 엔진 — 출력 참조 확인 · 규칙 단계 파일 창구 ────────────────────

class NoIn(SBModel):
    n: int = 0


class OneFile(SBModel):
    file: FileRef


class Holder(SBModel):
    inner: list[FileRef]
    extra: dict[str, FileRef] = {}


class Wrapped(SBModel):
    holder: Holder
    note: str = ""


class FileIn(SBModel):
    file: FileRef


class TinyFlow:
    """Flow 인터페이스의 최소 구현 — 대기열이 비면 사용자대기로."""

    def __init__(self) -> None:
        self.failed: list[str] = []

    def custom_step(self, step_id):
        return None

    def initial_redo_state(self, ctx, spec):
        return RedoState(task_id=spec.task_id)

    def build_instruction(self, ctx, spec, task, rework_input, rs, tools_for):
        return task.instruction, []

    def today(self, ctx):
        return date(2026, 10, 8)

    def constant(self, ctx, name):
        raise KeyError(name)

    def value(self, ctx, name, spec):
        raise KeyError(name)

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


@pytest.fixture(params=["memory", "local"])
def files_for_engine(request, tmp_path) -> FileStore:
    if request.param == "memory":
        return MemoryFileStore()
    return LocalFolderFileStore(tmp_path / "engine-files", create=True)


def build(clock: Clock, files: FileStore, specs: list[tuple[TaskSpec, object]]):
    registry = TaskRegistry()
    for spec, fn in specs:
        registry.register(spec)
        registry.bind(spec.task_id, fn)
    flow = TinyFlow()
    store = clock.backend.make_store(clock)
    engine = Engine(store=store, registry=registry, flow=flow, providers={},
                    types=ArtifactTypes(registry.artifact_types()), now=clock, sleep=lambda s: None, files=files)
    return engine, flow, store


def start(store: Store, clock: Clock, queue: list[str], run_id: str = "run1") -> str:
    now = clock()
    run = Run(run_id=run_id, account_id="acc", state=make_state("프로토타입제작", "실행"), current_phase="artifact",
              settings_snapshot=x_settings(), updated_at=now, created_at=now, queue=queue, segment="S",
              segment_total=len(queue))
    assert store.create_run(run, CommitBatch())
    return run.run_id


def task(task_id: str, out_model, out_field: str = "file", in_model=NoIn, inputs=None, kind: str = "task",
         writes_files: bool = False) -> TaskSpec:
    return TaskSpec(task_id, task_id, "구현", kind, in_model, out_model, inputs or {},
                    {out_field: f"{task_id}.{out_field}"}, out_field,
                    failure=FailurePolicy(resumable=False), writes_files=writes_files)


def put_task(name: str = "index.html", data: bytes = b"<html/>"):
    def fn(inp, tools):
        return OneFile(file=tools.files.put(name, data, HTML))
    return fn


def test_output_ref_made_by_put_is_stored(clock, files_for_engine):
    engine, flow, store = build(clock, files_for_engine, [(task("X", OneFile), put_task())])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "사용자대기"
    [rec] = store.executions(rid)
    assert rec.status == "성공"
    ctx = engine.open_context(store.load_run(rid))
    ref = ctx.get("X.file")
    assert isinstance(ref, FileRef) and ref.key.startswith(f"{rid}/{rec.execution_id}/")
    assert files_for_engine.read(ref.key) == b"<html/>"
    logs = store.call_logs(rid)
    assert [(l.call_type, l.purpose, l.task_id) for l in logs] == [("file", "put", "X")]
    _no_secret(logs, ref.key, "index.html", "<html/>")
    assert rec.input_tokens is None                                         # 파일 호출은 토큰이 없다


def _forge(kind: str):
    def fn(inp, tools):
        if kind == "other_run":
            data = b"theirs"
            key = "otherrun/e9/u9/index.html"
            meta = FileMeta(name="index.html", media_type=HTML, size=len(data),
                            sha256=hashlib.sha256(data).hexdigest())
            fn.store.write(key, data, meta)
            return OneFile(file=FileRef(key=key, name="index.html", media_type=HTML, size=meta.size,
                                        sha256=meta.sha256))
        real = tools.files.put("index.html", b"<html/>", HTML)
        if kind == "missing":
            return OneFile(file=real.model_copy(update={"key": real.key.rsplit("/", 2)[0] + "/zz/index.html"}))
        if kind == "size":
            return OneFile(file=real.model_copy(update={"size": real.size + 1}))
        if kind == "sha":
            return OneFile(file=real.model_copy(update={"sha256": SHA_ZERO}))
        if kind == "media":
            return OneFile(file=real.model_copy(update={"media_type": "image/svg+xml"}))
        raise AssertionError(kind)
    return fn


@pytest.mark.parametrize("kind", ["other_run", "missing", "size", "sha", "media"])
def test_output_ref_violations_are_contract_errors(clock, files_for_engine, kind):
    fn = _forge(kind)
    fn.store = files_for_engine
    engine, flow, store = build(clock, files_for_engine, [(task("X", OneFile), fn)])
    rid = start(store, clock, ["X"])
    assert engine.advance(rid) == "실패"
    [rec] = store.executions(rid)
    assert rec.status == "실패" and rec.error.startswith("ContractError")
    assert "index.html" not in rec.error and "otherrun" not in rec.error and rid + "/" not in rec.error
    assert flow.failed == ["운영오류"]
    events = json.dumps([e.dump() for e in store.events(rid)], ensure_ascii=False)
    assert "index.html" not in events and "/zz/" not in events


def test_previous_execution_ref_passes_and_nested_refs_are_checked(clock, files_for_engine):
    def wrap(inp: FileIn, tools) -> Wrapped:
        own = tools.files.put("README.md", b"# r", "text/markdown")
        return Wrapped(holder=Holder(inner=[inp.file, own], extra={"x": inp.file}))   # 앞 실행 기록의 참조를 그대로 넘긴다

    y = task("Y", Wrapped, out_field="holder", in_model=FileIn, inputs={"file": art("X.file")})
    engine, flow, store = build(clock, files_for_engine, [(task("X", OneFile), put_task()), (y, wrap)])
    rid = start(store, clock, ["X", "Y"])
    assert engine.advance(rid) == "사용자대기"
    assert [r.status for r in store.executions(rid)] == ["성공", "성공"]

    def forged_nested(inp: FileIn, tools) -> Wrapped:
        bad = inp.file.model_copy(update={"size": inp.file.size + 5})
        return Wrapped(holder=Holder(inner=[inp.file], extra={"bad": bad}))   # 사전 안 깊은 곳의 위조도 잡는다

    engine, flow, store = build(clock, files_for_engine, [(task("X", OneFile), put_task()), (y, forged_nested)])
    rid = start(store, clock, ["X", "Y"], run_id="run2")
    assert engine.advance(rid) == "실패"
    assert store.executions(rid)[-1].error.startswith("ContractError")


def test_rule_step_with_files_flag_gets_file_tool(clock, files_for_engine):
    seen: list[int] = []

    def g04(inp: NoIn, files) -> OneFile:
        seen.append(1)
        return OneFile(file=files.put("README.md", b"# guide", "text/markdown"))

    def plain(inp: NoIn) -> OneFile:   # 표시 없는 규칙 단계는 지금처럼 입력 하나만 받는다
        seen.append(2)
        return OneFile(file=fake)

    spec = task("G", OneFile, kind="rule", writes_files=True)
    engine, flow, store = build(clock, files_for_engine, [(spec, g04)])
    rid = start(store, clock, ["G"])
    assert engine.advance(rid) == "사용자대기"
    [rec] = store.executions(rid)
    assert rec.status == "성공" and rec.model is None and rec.step_kind == "rule"
    [log] = store.call_logs(rid)
    assert (log.call_type, log.purpose, log.task_id, log.execution_id, log.model) == (
        "file", "put", "G", rec.execution_id, None)
    assert seen == [1]

    fake = FileRef(key="run3/e/u/README.md", name="README.md", media_type="text/markdown", size=1, sha256=SHA_ZERO)
    engine, flow, store = build(clock, files_for_engine, [(task("P", OneFile, kind="rule"), plain)])
    rid = start(store, clock, ["P"], run_id="run3")
    assert engine.advance(rid) == "실패"                                    # 단계는 불렸고 위조 참조는 규격 위반
    assert seen == [1, 2]
    assert store.executions(rid)[0].error.startswith("ContractError")


def test_rule_step_file_tool_uses_plain_timeout_and_retry(clock, files_for_engine):
    def g04(inp: NoIn, files) -> OneFile:
        return OneFile(file=files.put("README.md", b"# g", "text/markdown"))

    settings = x_settings()
    settings["taskTimeouts"]["G"] = 7.0
    engine, flow, store = build(clock, files_for_engine, [(task("G", OneFile, kind="rule", writes_files=True), g04)])
    now = clock()
    run = Run(run_id="run4", account_id="acc", state=make_state("프로토타입제작", "실행"), current_phase="artifact",
              settings_snapshot=settings, updated_at=now, created_at=now, queue=["G"], segment="S", segment_total=1)
    assert store.create_run(run, CommitBatch())
    assert engine.advance("run4") == "사용자대기"                          # Task 설정 표에 G 항목이 없어도 된다
    [log] = store.call_logs("run4")
    assert (log.timeout_sec, log.model, log.provider) == (7.0, None, None)


def test_put_refused_when_stored_run_is_not_running(clock, files_for_engine, monkeypatch):
    """넣기는 저장소의 진행 상태를 다시 읽는다 — 단계가 도는 사이 실행 건이 중단되면(다른 프로세스) 쓰지 않는다."""
    watched = CountingStore(files_for_engine)

    def fn(inp, tools):
        real = store.load_run

        def stopped(run_id: str) -> Run:
            run = real(run_id)
            run.state = make_state(run.state.step, "중단")
            return run
        monkeypatch.setattr(store, "load_run", stopped)
        return OneFile(file=tools.files.put("index.html", b"x", HTML))

    engine, flow, store = build(clock, watched, [(task("X", OneFile), fn)])
    rid = start(store, clock, ["X"])
    engine.advance(rid)
    monkeypatch.undo()
    [rec] = store.executions(rid)
    assert rec.status == "실패" and rec.error.startswith("FileRejected")
    assert watched.writes == []


def test_pre_stage_context_has_no_file_tool(clock, files_for_engine):
    engine, flow, store = build(clock, files_for_engine, [(task("X", OneFile), put_task())])
    now = clock()
    run = Run(run_id="pre", account_id="acc", state=make_state("공고선택", "실행"), current_phase="setup",
              settings_snapshot=x_settings(), updated_at=now, created_at=now, queue=["X"])
    ctx = engine.open_context(run, provisional=True)
    spec = engine.registry.get("X")
    rec = engine.open_execution(ctx, spec, RedoState(task_id="X"))
    tools = engine.make_tools(ctx, spec, rec, engine.tools_config(ctx, spec), CallSink())
    with pytest.raises(RuntimeError):
        tools.files.put("index.html", b"x", HTML)


def test_stub_app_has_memory_file_store():
    from sbrain.bootstrap import build_stub_app
    app = build_stub_app()
    assert isinstance(app.engine.files, MemoryFileStore)
