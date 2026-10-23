"""한 시점 읽기 구간(Store.read_snapshot)과 구간 창구의 읽기 — 성능 측정 C 후속 (2026-10-20).

- 값이 같음(계약 — 메모리 · SQLite · MySQL): 창구의 새 읽기가 실행 건 하나씩 지금 메서드로 읽은 값과 같다. 창구의 같은
  이름 읽기(load_run 등)도 Store 메서드와 같은 값이다. 참조값은 구간 밖에서 구한다 — SQLite는 구간 동안 다른 연결의
  트랜잭션(읽기 포함)이 기다리므로 구간 안에서 저장소 일반 메서드를 부르지 않는다.
- 범위판(updated_since)은 MySQL 테스트 DB를 모든 MySQL 테스트가 함께 써서 다른 테스트의 행도 섞인다 — 자기 실행 건만 보지
  않고 같은 DB 전체에서 지금 메서드(query_runs · get_pointers · list_executions)로 구한 참조값과 비교한다.
- 문장 수 · 연결 수(SQL): 실행 건 수와 관계없이 같은 SELECT 수, PROJECT_CHUNK마다 한 문장, 빈 입력은 문장 없음, 구간 하나에
  연결 하나.
- 같은 순간: 구간 안 첫 읽기 뒤 다른 스레드가 쓰면 구간의 다음 읽기는 앞 순간이다(메모리 · SQLite는 쓰기가 기다리고 MySQL은
  기다리지 않는다). 구간 안 예외는 그대로 올라가고 다음 구간 · 일반 메서드는 정상이다.
- 격리(MySQL): 구간의 연결만 REPEATABLE READ, 돌려준 뒤 그 연결은 READ COMMITTED.

MySQL 테스트 DB에 워커가 가져갈 일을 남기지 않게 실행 건은 '완료'로 만들고, 시작 요청은 끝에 취소한다.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta

import pytest
from conftest import TIMING, Backend, Clock
from mysqldb import MYSQL, mysql_url, require_mysql
from sqlalchemy import event
from store_helpers import count_sql, new_run, sql_backend, uid, write_during_snapshot  # noqa: F401 — sql_backend는 pytest 장치
from webdb import new_project

from sbrain.models import Notification, Run
from sbrain.orchestrator.store import (
    ArtifactVersion, CommitBatch, ExecutionFilter, ExecutionTotals, RunFilter, SnapshotReads, StartRequest, Store,
    TriggerTotals,
)
from sbrain.orchestrator.trace import ExecutionRecord
from sbrain.store_sql import SqlStore, create_db_engine
from sbrain.store_sql import store as store_sql_store

SCORED = ("T-V1", "T-V2")   # 이 시험의 채점 Task 목록 — 흐름이 만들어 넘기는 값의 자리


@pytest.fixture
def env(any_backend: Backend):
    clock = Clock()
    return any_backend.make_store(clock), clock


@pytest.fixture
def sql_env(sql_backend: Backend):
    """SQL 저장소만 (SQLite · MySQL — 매개변수는 store_helpers의 sql_backend) — 문장 수를 세는 시험."""
    clock = Clock()
    return sql_backend.make_store(clock), clock


def project(store: Store) -> str:
    """프로젝트 ID. SqlStore면 웹 projects 행을 만든다."""
    if isinstance(store, SqlStore):
        return str(new_project(store.engine))
    return uid()


def created(store: Store, clock: Clock, *, with_project: bool = True) -> Run:
    """'완료' 실행 건 (워커가 가져가지 않는다). 계정은 실행 건마다 새로."""
    run = new_run(clock, uid(), progress="완료", project_id=project(store) if with_project else None)
    assert store.create_run(run, CommitBatch())
    return run


def save(store: Store, run: Run, owner: str = "w1", **batch) -> None:
    """실행 건 줄은 그대로(updated_at 포함) 두고 묶음을 저장한다."""
    assert store.acquire(run.run_id, owner, 60)
    store.commit(run.run_id, owner, CommitBatch(run=run, **batch))
    store.release(run.run_id, owner)


def version(clock: Clock, run: Run, key: str, v: int, value=None) -> ArtifactVersion:
    return ArtifactVersion(run.run_id, key, v, value, "exec-1", clock())


def execution(clock: Clock, run: Run, task: str = "T-V1", status: str = "성공", *, attempt: int = 1,
              trigger: str = "첫실행", **over) -> ExecutionRecord:
    now = clock()
    return ExecutionRecord(**{**dict(task_id=task, attempt=attempt, trigger=trigger, result_ref="", created_at=now,
                                     execution_id=uid(), run_id=run.run_id, agent="검증", step_kind="task",
                                     status=status, started_at=now), **over})


def note(clock: Clock, run: Run, kind: str = "문서평가") -> Notification:
    return Notification(run_id=run.run_id, kind=kind, target_step=6, created_at=clock(), notification_id="n")


def records(*recs: ExecutionRecord) -> dict[str, ExecutionRecord]:
    return {r.execution_id: r for r in recs}


def start_request(clock: Clock, account: str, project_id: str) -> StartRequest:
    now = clock()
    return StartRequest(request_id=uid(), project_id=project_id, account_id=account, status="대기",
                        form={"ideaText": "아이디어"}, created_at=now, updated_at=now)


# ── 창구 모양 ────────────────────────────────────────────
READ_NAMES = {name for name in vars(SnapshotReads) if not name.startswith("_")}


def test_snapshot_window_has_reads_only(env):
    store, _ = env
    assert READ_NAMES == {
        "load_run", "find_run_by_project", "query_runs", "latest_start_request", "latest_start_requests",
        "notifications_for_runs", "current_artifacts", "pointers_for_runs", "scored_executions",
        "scored_executions_since", "last_attempts", "pointers_since", "execution_totals_since"}
    with store.read_snapshot() as snap:
        assert {name for name in dir(snap) if not name.startswith("_")} == READ_NAMES   # 쓰기 메서드가 없다


# ── 같은 이름 읽기 = Store 메서드 ───────────────────────────
def test_named_reads_match_store_methods(env):
    store, clock = env
    a, b = created(store, clock), created(store, clock)
    loose = created(store, clock, with_project=False)
    nobody = project(store)                                                      # 실행 건 · 요청이 없는 프로젝트
    acc = uid()
    requests = [start_request(clock, acc, pid) for pid in (a.project_id, a.project_id, b.project_id)]
    for req in requests:
        assert store.add_start_request(req, max_active=9) is None
    filters = [RunFilter(project_ids=(a.project_id, b.project_id), limit=None), RunFilter(project_ids=()),
               RunFilter(project_ids=(b.project_id, a.project_id), order="asc"),
               RunFilter(limit=3, updated_since=a.updated_at)]
    pids = [a.project_id, b.project_id, nobody]
    want = dict(
        runs=[store.load_run(r.run_id) for r in (a, b, loose)],
        by_project=[store.find_run_by_project(p) for p in pids],
        latest=[store.latest_start_request(p) for p in pids],
        queried=[store.query_runs(f) for f in filters],
        latests=store.latest_start_requests(pids))
    try:
        with store.read_snapshot() as snap:
            got = dict(
                runs=[snap.load_run(r.run_id) for r in (a, b, loose)],
                by_project=[snap.find_run_by_project(p) for p in pids],
                latest=[snap.latest_start_request(p) for p in pids],
                queried=[snap.query_runs(f) for f in filters],
                latests=snap.latest_start_requests(iter(pids)))
            with pytest.raises(KeyError):
                snap.load_run(uid())                                             # 없는 실행 건 — 창구는 계속 쓴다
            after_error = (snap.latest_start_requests([]), snap.load_run(a.run_id))
    finally:
        for req in requests:                                                      # 워커가 가져갈 요청을 남기지 않는다
            assert store.cancel_start_request(req.request_id) == "취소"
    assert got == want and after_error == ({}, want["runs"][0])
    assert got["latest"][0].request_id == requests[1].request_id and got["by_project"][2] is None


# ── 새 묶어 읽기 = 실행 건 하나씩 읽은 값 ─────────────────────
def test_pointers_and_current_artifacts_match_one_by_one(env, monkeypatch):
    store, clock = env
    monkeypatch.setattr(store_sql_store, "PROJECT_CHUNK", 2)                    # 여러 번 나눠 읽는다
    rolled, plain, other_key, bare = (created(store, clock) for _ in range(4))
    save(store, rolled, versions=[version(clock, rolled, "planDoc", 1, {"z": 1, "a": [1, 2], "가": "값"})],
         pointers={"planDoc": 1})
    save(store, rolled, versions=[version(clock, rolled, "planDoc", 2, {"v": 2}),
                                  version(clock, rolled, "formInput", 1, {"f": 1})],
         pointers={"planDoc": 2, "formInput": 1})
    save(store, rolled, pointers={"planDoc": 1})                                 # 되돌린 포인터 — 최신이 아니라 현재 버전
    save(store, plain, versions=[version(clock, plain, "planDoc", 1, None)], pointers={"planDoc": 1})
    save(store, other_key, versions=[version(clock, other_key, "formInput", 1, {"f": 2})], pointers={"formInput": 1})
    ids = [rolled.run_id, plain.run_id, rolled.run_id, uid(), other_key.run_id, bare.run_id]   # 중복 · 없는 실행 건
    pointers = {rid: store.get_pointers(rid) for rid in dict.fromkeys(ids)}
    current = {key: {rid: store.get_artifact(rid, key, p[key]) for rid, p in pointers.items() if key in p}
               for key in ("planDoc", "formInput")}
    with store.read_snapshot() as snap:
        got_pointers = snap.pointers_for_runs(ids)
        got_current = {key: snap.current_artifacts(key, ids) for key in ("planDoc", "formInput")}
        empty = (snap.pointers_for_runs([]), snap.current_artifacts("planDoc", []),
                 snap.current_artifacts("없는키", ids))
    assert got_pointers == pointers                                                 # 넘긴 실행 건은 모두 키로 (없으면 빈 dict)
    assert got_pointers[bare.run_id] == {} and got_pointers[ids[3]] == {}
    assert got_current == current
    assert set(got_current["planDoc"]) == {rolled.run_id, plain.run_id}            # 그 key의 포인터가 있는 실행 건만
    first = got_current["planDoc"][rolled.run_id]
    assert first.version == 1 and list(first.value) == ["z", "a", "가"]          # 키 순서 그대로
    assert got_current["planDoc"][plain.run_id].value is None
    assert empty == ({}, {}, {})


def test_current_artifacts_with_missing_version_row_is_key_error(env):
    """포인터는 있는데 그 버전 행이 없으면(깨진 데이터) 두 저장소 모두 KeyError — get_artifact의 KeyError와 같은 모양."""
    store, clock = env
    key = "selectedAnnouncement"
    ok, broken = created(store, clock), created(store, clock)
    save(store, ok, versions=[version(clock, ok, key, 1, {"id": "A01"})], pointers={key: 1})
    save(store, broken, pointers={key: 2})                                       # 버전 행 없이 포인터만
    with pytest.raises(KeyError) as one:
        store.get_artifact(broken.run_id, key, 2)
    want_ok = {ok.run_id: store.get_artifact(ok.run_id, key, 1)}
    with store.read_snapshot() as snap:
        with pytest.raises(KeyError) as many:
            snap.current_artifacts(key, [ok.run_id, broken.run_id])
        assert snap.current_artifacts(key, [ok.run_id]) == want_ok                # 구간은 계속 쓴다
    assert many.value.args == one.value.args == ((broken.run_id, key, 2),)


def test_notifications_for_runs_match_one_by_one(env, monkeypatch):
    store, clock = env
    monkeypatch.setattr(store_sql_store, "PROJECT_CHUNK", 2)
    runs = [created(store, clock) for _ in range(3)]
    loose = created(store, clock, with_project=False)                           # 프로젝트 없음 — SQL은 알림을 쓰지 않는다
    quiet = created(store, clock)                                               # 알림 없음
    for i, run in enumerate([*runs, loose]):
        save(store, run, notifications=[note(clock, run), note(clock, run, "실패")][:1 + i % 2])
    save(store, runs[0], notifications=[note(clock, runs[0], "산출물확인")])    # 나중에 쌓인 알림 — 알림 ID 순
    missing = uid()
    ids = [*(r.run_id for r in runs), loose.run_id, quiet.run_id, runs[1].run_id, missing]
    want = {rid: store.notifications(rid) for rid in dict.fromkeys(ids)}
    with store.read_snapshot() as snap:
        got = snap.notifications_for_runs(ids)
        assert snap.notifications_for_runs([]) == {}
    assert got == want                                                           # 넘긴 실행 건은 모두 키로
    assert [n.kind for n in got[runs[0].run_id]] == ["문서평가", "산출물확인"]
    assert len(got[runs[1].run_id]) == 2 and got[quiet.run_id] == [] and got[missing] == []


def test_scored_executions_and_last_attempts_match_one_by_one(env, monkeypatch):
    store, clock = env
    monkeypatch.setattr(store_sql_store, "PROJECT_CHUNK", 2)
    a, b, c, none = (created(store, clock) for _ in range(4))
    first = execution(clock, a, "T-V1", "실행")
    save(store, a, executions=records(first))
    later = [execution(clock, a, "T-V2"), execution(clock, a, "T-W1"), execution(clock, a, "T-V1", "실패", attempt=2)]
    save(store, a, executions=records(*later))
    done = first.model_copy(update={"status": "성공", "ended_at": clock()})
    save(store, a, executions=records(done))                                     # 덮어쓴 기록 — 처음 기록된 자리 그대로
    save(store, b, executions=records(execution(clock, b, "T-V1", attempt=3)))
    save(store, c, executions=records(execution(clock, c, "T-S1", attempt=2)))   # 채점 Task가 아님
    ids = [a.run_id, b.run_id, c.run_id, none.run_id, a.run_id, uid()]
    unique = list(dict.fromkeys(ids))
    want_scored = {rid: [r for r in store.executions(rid) if r.status == "성공" and r.task_id in SCORED]
                   for rid in unique}
    want_last = {rid: recs[-1].attempt for rid in unique if (recs := store.executions(rid))}
    with store.read_snapshot() as snap:
        scored = snap.scored_executions(ids, SCORED)
        no_tasks = snap.scored_executions(ids, [])
        last = snap.last_attempts(ids)
        empty = (snap.scored_executions([], SCORED), snap.last_attempts([]))
    assert scored == want_scored
    assert [r.execution_id for r in scored[a.run_id]] == [first.execution_id, later[0].execution_id]
    assert scored[a.run_id][0] == done and scored[c.run_id] == [] and scored[none.run_id] == []
    assert no_tasks == {rid: [] for rid in unique}
    assert last == want_last == {a.run_id: 2, b.run_id: 3, c.run_id: 2}      # 실행 기록이 없는 실행 건은 키가 없다
    assert empty == ({}, {})


# ── 범위판 = 같은 DB 전체의 참조값 ──────────────────────────
def _text(r: ExecutionRecord) -> int:
    return (r.input_tokens or 0) + (r.output_tokens or 0)


def _image(r: ExecutionRecord) -> int:
    return (r.image_input_tokens or 0) + (r.image_output_tokens or 0)


def totals_from(recs: list[ExecutionRecord]) -> ExecutionTotals:
    """실행 기록 JSON에서 센 집계 (참조값)."""
    by_trigger = {}
    for trig in dict.fromkeys(r.trigger for r in recs):
        mine = [r for r in recs if r.trigger == trig]
        by_trigger[trig] = TriggerTotals(count=len(mine), text_tokens=sum(map(_text, mine)),
                                         runs=len({r.run_id for r in mine}))
    return ExecutionTotals(by_trigger=by_trigger, text_tokens=sum(map(_text, recs)), image_tokens=sum(map(_image, recs)),
                           runs_with_executions=len({r.run_id for r in recs}))


def whole_db_reference(store: Store, since) -> tuple[dict, list[ExecutionRecord], ExecutionTotals]:
    """지금 메서드로 구한 범위의 참조값 — 포인터 · 채점 기록(시작 시각 · 기록 순) · 집계."""
    runs = store.query_runs(RunFilter(limit=None, updated_since=since))
    scope = {r.run_id for r in runs}
    recs = [row.record for row in store.list_executions(ExecutionFilter(limit=None, order="asc"))
            if row.record.run_id in scope]
    pointers = {r.run_id: store.get_pointers(r.run_id) for r in runs}
    scored = [r for r in recs if r.status == "성공" and r.task_id in SCORED]
    return pointers, scored, totals_from(recs)


def test_range_reads_match_whole_db_reference(env):
    store, clock = env
    before, at, after = (created(store, clock) for _ in range(3))               # 마지막 활동 순서대로
    since = at.updated_at
    save(store, before, versions=[version(clock, before, "planDoc", 1, {"b": 1})], pointers={"planDoc": 1},
         executions=records(execution(clock, before, input_tokens=5, output_tokens=6)))
    save(store, at, versions=[version(clock, at, "planDoc", 1, {"a": 1})], pointers={"planDoc": 1}, executions=records(
        execution(clock, at, input_tokens=10, output_tokens=20, cached_input_tokens=4, reasoning_tokens=3),
        execution(clock, at, "T-V2", trigger="재작성", output_tokens=7, image_input_tokens=100,
                  image_output_tokens=200),
        execution(clock, at, "T-W2", trigger="재수행", image_output_tokens=50),
        execution(clock, at, "T-V1", "실패", trigger="재작성")))                 # 토큰이 없는 기록
    save(store, after, executions=records(
        execution(clock, after, "T-V2", started_at=clock.t - timedelta(hours=1)),   # 시작 시각이 더 이르다
        execution(clock, after, "T-V1", trigger="재작성", started_at=None, input_tokens=1)))   # 시작 시각 없음
    pointers, scored, totals = whole_db_reference(store, since)
    with store.read_snapshot() as snap:
        got = (snap.pointers_since(since), snap.scored_executions_since(since, SCORED),
               snap.execution_totals_since(since))
        naive = (snap.pointers_since(since.replace(tzinfo=None)),
                 snap.scored_executions_since(since.replace(tzinfo=None), iter(SCORED)),
                 snap.execution_totals_since(since.replace(tzinfo=None)))            # 시간대 없는 값은 UTC
        no_tasks = snap.scored_executions_since(since, [])
    assert got == (pointers, scored, totals) and naive == got
    assert no_tasks == []
    # 경계 — 같은 시각은 들고 그 전은 빠진다. 포인터가 없는 실행 건도 키로 있다
    assert got[0][at.run_id] == {"planDoc": 1} and got[0][after.run_id] == {} and before.run_id not in got[0]
    mine = [r.run_id for r in got[1] if r.run_id in {before.run_id, at.run_id, after.run_id}]
    assert mine == [after.run_id, after.run_id, at.run_id, at.run_id]           # (시작 시각, 기록 순)
    assert got[2].by_trigger["재작성"].runs >= 2 and got[2].image_tokens >= 350


# ── 문장 수 · 연결 수 (SQL) ────────────────────────────────
PER_CHUNK = {"notifications_for_runs": 2, "current_artifacts": 1, "pointers_for_runs": 1, "scored_executions": 1,
             "last_attempts": 1}
FIXED = {"pointers_since": 1, "scored_executions_since": 1, "execution_totals_since": 2}


def select_counts(store: SqlStore, ids: list[str], since) -> tuple[dict[str, int], int, int]:
    """구간 하나에서 읽기마다 보낸 SELECT 수, 구간 전체의 연결 꺼내기 수 · SELECT가 아닌 문장 수."""
    out: dict[str, int] = {}
    with count_sql(store.engine) as whole:
        with store.read_snapshot() as snap:
            reads = {"notifications_for_runs": lambda: snap.notifications_for_runs(ids),
                     "current_artifacts": lambda: snap.current_artifacts("planDoc", ids),
                     "pointers_for_runs": lambda: snap.pointers_for_runs(ids),
                     "scored_executions": lambda: snap.scored_executions(ids, SCORED),
                     "last_attempts": lambda: snap.last_attempts(ids),
                     "pointers_since": lambda: snap.pointers_since(since),
                     "scored_executions_since": lambda: snap.scored_executions_since(since, SCORED),
                     "execution_totals_since": lambda: snap.execution_totals_since(since)}
            for name, read in reads.items():
                with count_sql(store.engine) as one:
                    read()
                out[name] = one.selects
    return out, whole.checkouts, whole.others


def test_select_count_does_not_grow_with_runs(sql_env, monkeypatch):
    store, clock = sql_env
    runs = [created(store, clock) for _ in range(5)]
    for run in runs:
        save(store, run, versions=[version(clock, run, "planDoc", 1, {"p": 1})], pointers={"planDoc": 1},
             executions=records(execution(clock, run)), notifications=[note(clock, run)])
    ids = [r.run_id for r in runs]
    since = runs[0].updated_at
    select_counts(store, ids[:1], since)                 # 데우기 — 웹 표 구조 읽기 · 첫 연결 설정 문장을 뺀다
    two = select_counts(store, ids[:2], since)
    five = select_counts(store, ids, since)
    assert two == five == ({**PER_CHUNK, **FIXED}, 1, two[2])                 # 연결은 구간 하나에 한 번
    monkeypatch.setattr(store_sql_store, "PROJECT_CHUNK", 2)                    # 5건 = 묶음 3개
    chunked, conns, _ = select_counts(store, ids, since)
    assert chunked == {**{k: v * 3 for k, v in PER_CHUNK.items()}, **FIXED} and conns == 1


def test_empty_ids_send_no_statements(env):
    store, clock = env
    run = created(store, clock)
    counting = count_sql(store.engine) if isinstance(store, SqlStore) else nullcontext()
    with store.read_snapshot() as snap:
        snap.load_run(run.run_id)                                                 # 구간을 연 뒤에 센다
        with counting as counts:
            got = (snap.notifications_for_runs([]), snap.current_artifacts("planDoc", []), snap.pointers_for_runs([]),
                   snap.scored_executions([], SCORED), snap.scored_executions([run.run_id], []),
                   snap.last_attempts(iter([])), snap.latest_start_requests([]),
                   snap.query_runs(RunFilter(project_ids=())))
    assert got == ({}, {}, {}, {}, {run.run_id: []}, {}, {}, [])
    if counts is not None:
        assert counts.statements == [] and counts.checkouts == 0


# ── 예외 · 같은 순간 ──────────────────────────────────────
def test_exception_in_snapshot_is_raised_and_store_keeps_working(env):
    store, clock = env
    run = created(store, clock)
    boom = LookupError("구간 안 오류")
    with pytest.raises(LookupError) as info:
        with store.read_snapshot() as snap:
            snap.pointers_for_runs([run.run_id])
            raise boom
    assert info.value is boom                                                    # 그 예외 그대로
    with pytest.raises(RuntimeError):
        snap.pointers_for_runs([run.run_id])                                      # 끝난 구간의 창구로는 읽지 않는다
    save(store, run, versions=[version(clock, run, "planDoc", 1, {"p": 1})], pointers={"planDoc": 1})   # 쓰기가 정상
    with store.read_snapshot() as again:
        assert again.pointers_for_runs([run.run_id]) == {run.run_id: {"planDoc": 1}}
    assert store.get_pointers(run.run_id) == {"planDoc": 1}


@TIMING
def test_write_from_other_thread_after_first_read_is_not_seen(env, any_backend):
    store, clock = env
    run = created(store, clock)
    rid, since = run.run_id, run.updated_at
    first = execution(clock, run, input_tokens=3)
    save(store, run, versions=[version(clock, run, "planDoc", 1, {"v": 1})], pointers={"planDoc": 1},
         executions=records(first))
    with store.read_snapshot() as snap:
        totals_before = snap.execution_totals_since(since)
    v2, second = version(clock, run, "planDoc", 2, {"v": 2}), execution(clock, run, attempt=2, input_tokens=4)

    def write() -> None:                                                          # 다른 스레드 — 새 버전 · 포인터 · 실행 기록
        save(store, run, versions=[v2], pointers={"planDoc": 2}, executions=records(second))

    with write_during_snapshot(store, write) as outcome:
        with store.read_snapshot() as snap:
            pointers = snap.pointers_for_runs([rid])                              # 첫 읽기 — 이 뒤에 다른 스레드가 쓴다
            seen = dict(pointers=snap.pointers_for_runs([rid]), current=snap.current_artifacts("planDoc", [rid]),
                        scored=snap.scored_executions([rid], SCORED), last=snap.last_attempts([rid]),
                        ranged=snap.pointers_since(since).get(rid), totals=snap.execution_totals_since(since),
                        run=snap.load_run(rid))
    assert outcome.started and outcome.after == "pointers_for_runs"
    assert outcome.error is None and outcome.finished
    assert outcome.finished_in_snapshot is (any_backend.kind == "mysql")        # 메모리 · SQLite는 쓰기가 기다린다
    assert pointers == seen["pointers"] == {rid: {"planDoc": 1}}                 # 구간의 다음 읽기는 앞 순간
    assert seen["current"][rid].version == 1 and seen["ranged"] == {"planDoc": 1}
    assert [r.execution_id for r in seen["scored"][rid]] == [first.execution_id] and seen["last"] == {rid: 1}
    assert seen["totals"] == totals_before
    with store.read_snapshot() as snap:                                          # 구간 뒤에는 새 순간
        assert snap.pointers_for_runs([rid]) == {rid: {"planDoc": 2}} and snap.last_attempts([rid]) == {rid: 2}
        totals_after = snap.execution_totals_since(since)
    assert totals_after.by_trigger["첫실행"].count == totals_before.by_trigger["첫실행"].count + 1
    assert totals_after.text_tokens == totals_before.text_tokens + 4


@TIMING
def test_write_during_snapshot_after_named_read_and_restores_store(env, any_backend):
    """시험 도움 장치 — after로 고른 읽기 뒤에 끼우고, 뒤의 구간은 그대로 지나가며, 끝나면 read_snapshot을 되돌린다."""
    store, clock = env
    run = created(store, clock)
    rid = run.run_id
    save(store, run, versions=[version(clock, run, "planDoc", 1, {"v": 1})], pointers={"planDoc": 1})
    v2 = version(clock, run, "planDoc", 2, {"v": 2})

    def write() -> str:
        save(store, run, versions=[v2], pointers={"planDoc": 2})
        return "저장함"

    with write_during_snapshot(store, write, after="current_artifacts") as outcome:
        with store.read_snapshot() as snap:
            assert snap.pointers_for_runs([rid]) == {rid: {"planDoc": 1}}
            assert not outcome.started                                            # 고른 읽기 전에는 끼우지 않는다
            assert snap.current_artifacts("planDoc", [rid])[rid].version == 1
            assert outcome.started and snap.pointers_for_runs([rid]) == {rid: {"planDoc": 1}}
        with store.read_snapshot() as later:                                     # 뒤의 구간은 그대로 (쓰기는 끝났다)
            assert later.pointers_for_runs([rid]) == {rid: {"planDoc": 2}}
    assert outcome.after == "current_artifacts" and outcome.result == "저장함" and outcome.finished
    assert outcome.finished_in_snapshot is (any_backend.kind == "mysql")
    assert "read_snapshot" not in vars(store)                                     # 클래스의 read_snapshot으로 되돌렸다


# ── 격리 (MySQL) ──────────────────────────────────────────
def _isolation(dbapi_connection) -> str:
    cur = dbapi_connection.cursor()
    try:
        cur.execute("SELECT @@transaction_isolation")
        return cur.fetchone()[0]
    finally:
        cur.close()


@MYSQL
def test_mysql_snapshot_connection_is_repeatable_read_only_inside():
    shared = require_mysql()                                                       # 표 준비 · 묶음 확인
    engine = create_db_engine(mysql_url(), pool_size=1, max_overflow=0)            # 같은 시험 DB — 연결 하나짜리 풀
    seen: list = []
    event.listen(engine, "checkout", lambda dbapi_connection, record, proxy: seen.append(dbapi_connection))
    try:
        store = SqlStore(engine, now=Clock())
        with store.read_snapshot() as snap:
            snap.query_runs(RunFilter(limit=1))
            assert len(seen) == 1 and _isolation(seen[0]) == "REPEATABLE-READ"   # 구간의 연결만
            with shared.connect() as other:                                       # 풀의 다른 연결은 그대로
                assert other.exec_driver_sql("SELECT @@transaction_isolation").scalar() == "READ-COMMITTED"
        with engine.connect() as again:                                           # 구간에서 쓴 바로 그 연결
            assert again.connection.dbapi_connection is seen[0]
            assert again.exec_driver_sql("SELECT @@transaction_isolation").scalar() == "READ-COMMITTED"
    finally:
        engine.dispose()
