"""저장소 계약 — 메모리 · SqlStore(SQLite) · SqlStore(MySQL 8)가 같은 동작인지.

MySQL은 SBRAIN_TEST_MYSQL_URL(환경 변수 또는 .env)이 있을 때만 돈다. 여러 테스트가 같은 MySQL DB를 쓰므로
계정 · 실행 건 ID는 테스트마다 새로 만든다.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest
from conftest import TIMING, Backend, Clock
from sqlalchemy import select
from store_helpers import new_run, rejected, uid
from webdb import new_project

from sbrain.models import CycleState, Notice, Notification, ReworkComparison, Run
from sbrain.models.run import make_state
from sbrain.orchestrator.errors import ProjectRunExists, StoreConflict
from sbrain.orchestrator.store import (
    ArtifactVersion, CommitBatch, ExecutionFilter, LogStatsRow, RunFilter, StartRequest, Store,
)
from sbrain.orchestrator.trace import CallLog, CallTry, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent
from sbrain.store_sql import SqlStore
from sbrain.store_sql.schema import RUNS


@pytest.fixture
def env(any_backend: Backend):
    clock = Clock()
    return any_backend.make_store(clock), clock


def project(store: Store, *, agreed: bool = False) -> str:
    """프로젝트 ID. SqlStore면 웹 projects 행(주인 계정의 학습 동의 = agreed)을 만든다."""
    if isinstance(store, SqlStore):
        return str(new_project(store.engine, agreed=agreed))
    pid = uid()
    store.set_training_consent(pid, agreed)
    return pid


def created(store: Store, clock: Clock, account: str | None = None, **kw) -> Run:
    run = new_run(clock, account or uid(), **kw)
    assert store.create_run(run, CommitBatch())
    return run


def save(store: Store, run: Run, owner: str = "w1", **batch) -> None:
    assert store.acquire(run.run_id, owner, 60)
    store.commit(run.run_id, owner, CommitBatch(run=run, **batch))
    store.release(run.run_id, owner)


def execution(clock: Clock, run: Run, task: str = "T-C1", status: str = "실행", eid: str | None = None):
    now = clock()
    return ExecutionRecord(task_id=task, attempt=1, trigger="첫실행", result_ref="", created_at=now,
                           execution_id=eid or uid(), run_id=run.run_id, agent="조율", step_kind="task",
                           status=status, started_at=now)


# ── 점유 ─────────────────────────────────────────────
def test_lease_contention_and_expiry(env):
    store, clock = env
    run = created(store, clock)
    assert store.acquire(run.run_id, "A", 60)
    assert not store.acquire(run.run_id, "B", 60)
    assert store.acquire(run.run_id, "A", 60)                # 같은 점유자는 다시 잡을 수 있다
    assert store.is_locked(run.run_id, clock.t)
    clock.advance(seconds=61)
    assert not store.is_locked(run.run_id, clock.t)
    assert store.acquire(run.run_id, "B", 60)                # 만료되면 다른 점유자가 잡는다
    store.release(run.run_id, "A")                           # 점유자가 아니면 풀지 못한다
    assert store.is_locked(run.run_id, clock.t)
    store.release(run.run_id, "B")
    assert not store.is_locked(run.run_id, clock.t)


def test_commit_requires_lease(env):
    store, clock = env
    run = created(store, clock)
    with pytest.raises(StoreConflict):
        store.commit(run.run_id, "A", CommitBatch(run=run))
    assert store.acquire(run.run_id, "A", 60)
    with pytest.raises(StoreConflict):
        store.commit(run.run_id, "B", CommitBatch(run=run))
    run.current_task = "T-C1"
    store.commit(run.run_id, "A", CommitBatch(run=run))
    assert store.load_run(run.run_id).current_task == "T-C1"


# ── 실행 건 ───────────────────────────────────────────
def test_active_run_limit_per_account(env):
    store, clock = env
    account = uid()
    first = created(store, clock, account)
    assert not store.create_run(new_run(clock, account), CommitBatch())          # 진행 중 1건 제한
    created(store, clock)                                                         # 다른 계정은 된다
    assert store.find_active_run(account).run_id == first.run_id
    first.state = make_state("공고선택", "완료")
    save(store, first)
    assert store.find_active_run(account) is None
    second = created(store, clock, account)
    assert [r.run_id for r in store.list_runs(account)] == [first.run_id, second.run_id]


@TIMING
def test_concurrent_create_run_allows_one(env):
    store, clock = env
    account = uid()
    runs = [new_run(clock, account) for _ in range(6)]
    results: list[bool] = []
    barrier = threading.Barrier(len(runs))

    def go(run: Run) -> None:
        barrier.wait()
        results.append(store.create_run(run, CommitBatch()))
    threads = [threading.Thread(target=go, args=(r,)) for r in runs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 5 + [True]
    assert len(store.list_runs(account)) == 1


def test_one_run_per_project(env):
    store, clock = env
    pid = project(store)
    run = created(store, clock, project_id=pid)
    run.state = make_state("공고선택", "중단")
    save(store, run)
    with pytest.raises(ProjectRunExists):                                         # 새로 시작은 새 프로젝트로
        store.create_run(new_run(clock, run.account_id, project_id=pid), CommitBatch())
    assert store.find_run_by_project(pid).run_id == run.run_id
    assert store.find_run_by_project(project(store)) is None


def test_runs_due_for_resume(env):
    store, clock = env
    due = created(store, clock)
    later = created(store, clock)
    other = created(store, clock)
    for run, at in ((due, clock.t - timedelta(minutes=1)), (later, clock.t + timedelta(hours=1))):
        run.state, run.next_resume_at = make_state("계획서작성", "재개대기"), at
        save(store, run)
    listed = store.runs_due_for_resume(clock.t)
    assert due.run_id in listed and later.run_id not in listed and other.run_id not in listed


def claimable(store: Store, limit: int = 1000) -> list[str]:
    """지금 가져갈 수 있는 '실행' 실행 건을 모두 가져간다 (MySQL은 다른 테스트가 남긴 실행 건도 함께 나온다)."""
    got = []
    for _ in range(limit):
        rid = store.claim_ready_run("w-claim", 60)
        if rid is None:
            break
        got.append(rid)
    return got


def test_claim_skips_collecting_run_until_window_end(env):
    store, clock = env
    run = created(store, clock, progress="사용자대기", step="산출물확인")
    # 재작성 요청을 모으는 중 — 저장(commit) 경로로 모으는 시간이 끝나는 시각을 남긴다
    run.state = make_state("산출물확인", "실행", 8)
    run.cycle = CycleState(cycle_id=uid(), screen=8, snapshot={}, counted_bundles=["실행 파일"],
                           selected_orders_ref="decision@1", orders_by_task={}, layers=["artifact"],
                           started_at=clock(), collect_until=clock.t + timedelta(seconds=2))
    save(store, run)
    assert run.run_id not in claimable(store)                                   # 모으는 동안은 가져가지 않는다
    assert store.load_run(run.run_id).cycle.collect_until == run.cycle.collect_until
    clock.advance(seconds=3)
    assert run.run_id in claimable(store)                                       # 시간이 지나면 가져간다


def test_abort_request_survives_commit(env):
    store, clock = env
    run, other = created(store, clock), created(store, clock)
    store.request_abort(run.run_id)
    save(store, run)
    assert store.is_abort_requested(run.run_id) and not store.is_abort_requested(other.run_id)


# ── 산출물 ────────────────────────────────────────────
def version(clock: Clock, run: Run, key: str, v: int, value) -> ArtifactVersion:
    return ArtifactVersion(run.run_id, key, v, value, "exec-1", clock())


def test_pointer_overwrite_and_latest(env):
    store, clock = env
    run = created(store, clock)
    v1 = {"z": 1, "a": [1, 2], "가": "값"}                      # 키 순서를 그대로 돌려줘야 한다
    save(store, run, versions=[version(clock, run, "planDoc", 1, v1)], pointers={"planDoc": 1})
    save(store, run, versions=[version(clock, run, "planDoc", 2, None)], pointers={"planDoc": 2})
    ev = PointerEvent(run_id=run.run_id, key="planDoc", from_version=2, to_version=1, reason="되돌리기",
                      cycle_id="c1", at=clock())
    save(store, run, pointers={"planDoc": 1}, pointer_events=[ev])
    assert store.get_pointers(run.run_id) == {"planDoc": 1}
    assert store.get_latest_versions(run.run_id) == {"planDoc": 2}
    got = store.get_artifact(run.run_id, "planDoc", 1)
    assert list(got.value) == ["z", "a", "가"] and got.value == v1 and got.producer == "exec-1"
    assert store.get_artifact(run.run_id, "planDoc", 2).value is None
    assert store.pointer_events(run.run_id) == [ev]
    with pytest.raises(KeyError):
        store.get_artifact(run.run_id, "planDoc", 3)


def test_delete_artifacts_keeps_records(env):
    store, clock = env
    run = created(store, clock)
    rec = execution(clock, run, status="성공")
    save(store, run, versions=[version(clock, run, "formInput", 1, {"a": 1})], pointers={"formInput": 1},
         executions={rec.execution_id: rec})
    store.delete_artifacts(run.run_id)
    assert store.get_pointers(run.run_id) == {} and store.get_latest_versions(run.run_id) == {}
    assert [r.execution_id for r in store.executions(run.run_id)] == [rec.execution_id]
    assert store.load_run(run.run_id).run_id == run.run_id


# ── 추적 기록 ─────────────────────────────────────────
def test_execution_record_is_overwritten_in_place(env):
    store, clock = env
    run = created(store, clock)
    first, second = execution(clock, run, "T-C1"), execution(clock, run, "T-C2")
    save(store, run, executions={first.execution_id: first, second.execution_id: second})
    done = first.model_copy(update={"status": "성공", "ended_at": clock(), "outputs": ["category@1"]})
    save(store, run, executions={done.execution_id: done})
    assert store.executions(run.run_id) == [done, second]                         # 처음 기록된 순서 유지


def test_records_round_trip(env):
    store, clock = env
    run = created(store, clock, project_id=project(store))
    rec = execution(clock, run)
    t0 = clock()
    call = CallLog(call_id=uid(), run_id=run.run_id, execution_id=rec.execution_id, task_id="T-C1", agent="조율",
                   call_type="llm", purpose="아이템 사양", item_key=None, provider="openai", model="gpt-6-luna",
                   temperature=None, reasoning_effort="low", timeout_sec=120.0, final_outcome="성공",
                   tries=[CallTry(no=1, started_at=t0, ended_at=clock(), outcome="응답지연", error_kind="일시",
                                  detail="timeout"),
                          CallTry(no=2, started_at=clock(), ended_at=clock(), outcome="성공")])
    fb = FeedbackLink(feedback_id=uid(), run_id=run.run_id, kind="재수행", source_execution_id=rec.execution_id,
                      source_refs=["T-S1.check@1"], target_task_id="T-S1", target_execution_id=uid(),
                      via_ref="T-S1.reworkInput@1", cycle_id=None, created_at=clock())
    comp = ReworkComparison(bundle_id="1-1", before_refs=["planDoc@1"], after_refs=["planDoc@2"], before_score=70.5,
                            after_score=81.0, kept="후", cycle_id="c1", screen=6, basis="document",
                            compared_at=clock())
    ev = TraceEvent(run_id=run.run_id, kind="재개", detail="T-S1 재개", refs=["a@1"], execution_id=rec.execution_id,
                    at=clock())
    note = Notification(run_id=run.run_id, kind="실패", failure_scope="재작성", target_step=6,
                        created_at=clock(), notification_id="n-1")
    save(store, run, executions={rec.execution_id: rec}, call_logs=[call], feedback=[fb], comparisons=[comp],
         events=[ev], notifications=[note])
    assert store.call_logs(run.run_id) == [call]
    assert store.feedback(run.run_id) == [fb]
    assert store.comparisons(run.run_id) == [comp]
    assert store.events(run.run_id) == [ev]
    [got] = store.notifications(run.run_id)
    assert got.model_copy(update={"notification_id": "n-1"}) == note                 # ID는 저장소가 정한다
    assert store.load_run(run.run_id) == run


def test_run_without_project_has_no_web_notifications(env, any_backend):
    """project_id가 없는 실행 건(테스트 · 시연용 직접 시작)은 웹 notifications에 쓰지 않는다."""
    store, clock = env
    run = created(store, clock)
    note = Notification(run_id=run.run_id, kind="문서평가", target_step=6, created_at=clock(), notification_id="n")
    save(store, run, notifications=[note])
    expected = [] if any_backend.kind != "memory" else [note]
    assert store.notifications(run.run_id) == expected


def test_rejected_attempts_need_project_and_consent(env):
    """반려된 시도는 프로젝트 주인이 학습에 동의한 실행 건만, 쓴 순서대로 남는다 (웹 proofread_logs)."""
    store, clock = env
    agreed = created(store, clock, project_id=project(store, agreed=True))
    refused = created(store, clock, project_id=project(store))
    no_project = created(store, clock)
    for run in (agreed, refused, no_project):
        save(store, run, rejected_attempts=[rejected(run, 1), rejected(run, 2)])
    save(store, agreed, rejected_attempts=[rejected(agreed, 3)])
    assert store.rejected_attempts(agreed.run_id) == [rejected(agreed, n) for n in (1, 2, 3)]
    assert store.rejected_attempts(refused.run_id) == []
    assert store.rejected_attempts(no_project.run_id) == []


# ── 사전 단계 시작 요청 ────────────────────────────────
def start_request(clock: Clock, account: str, project_id: str | None = None) -> StartRequest:
    now = clock()
    return StartRequest(request_id=uid(), project_id=project_id, account_id=account, status="대기",
                        form={"ideaText": "아이디어", "b": 1, "a": 2}, created_at=now, updated_at=now)


def test_start_request_lifecycle(env):
    store, clock = env
    account, pid = uid(), project(store)
    req = start_request(clock, account, pid)
    assert store.add_start_request(req) is None
    blocker = store.add_start_request(start_request(clock, account))         # 대기 요청이 막는다
    assert isinstance(blocker, StartRequest) and blocker.request_id == req.request_id
    assert store.acquire_start_request(req.request_id, "A", 60)
    assert not store.acquire_start_request(req.request_id, "B", 60)
    assert store.acquire_start_request(req.request_id, "A", 60)               # 같은 점유자는 횟수를 세지 않는다
    assert store.get_start_request(req.request_id).claim_count == 1
    clock.advance(seconds=61)
    assert store.acquire_start_request(req.request_id, "B", 60)               # 만료 → 이어받음
    got = store.get_start_request(req.request_id)
    assert (got.status, got.lease_owner, got.claim_count) == ("처리중", "B", 2)
    assert list(got.form) == ["ideaText", "b", "a"]
    assert not store.finish_start_request(req.request_id, "A", status="실패")  # 점유를 잃은 쪽은 끝내지 못한다
    run = new_run(clock, account, project_id=pid)
    run.notices = [Notice(code="E-C2-EMBED", message="안내", at=clock())]
    assert store.create_run_for_request(run, CommitBatch(), req.request_id, "B") == "완료"
    done = store.latest_start_request(pid)
    assert (done.status, done.run_id, done.lease_owner) == ("완료", run.run_id, None)
    assert done.notices == run.notices and done.finished_at is not None
    assert store.find_run_by_project(pid).run_id == run.run_id
    assert not store.acquire_start_request(req.request_id, "B", 60)           # 끝난 요청은 다시 잡지 않는다
    blocker = store.add_start_request(start_request(clock, account))         # 이제 실행 건이 막는다
    assert isinstance(blocker, Run) and blocker.run_id == run.run_id


def test_start_request_cancel_and_concurrency(env):
    store, clock = env
    account = uid()
    waiting = start_request(clock, account)
    store.add_start_request(waiting)
    assert store.cancel_start_request(waiting.request_id) == "취소"
    assert store.get_start_request(waiting.request_id).status == "취소"
    processing = start_request(clock, account)
    assert store.add_start_request(processing) is None                       # 취소된 요청은 막지 않는다
    assert store.acquire_start_request(processing.request_id, "A", 60)
    assert store.cancel_start_request(processing.request_id) == "취소요청"
    assert store.create_run_for_request(new_run(clock, account), CommitBatch(), processing.request_id, "A") == "취소"
    assert store.list_runs(account) == [] and store.cancel_start_request(processing.request_id) == ""
    late = start_request(clock, account)
    store.add_start_request(late)
    assert store.acquire_start_request(late.request_id, "A", 60)
    created(store, clock, account)                                           # 다른 경로로 생긴 실행 건
    assert store.create_run_for_request(new_run(clock, account), CommitBatch(), late.request_id, "A") == "동시실행"
    assert store.finish_start_request(late.request_id, "A", status="실패", code="E-RUN-CONCURRENT",
                                      detail={"active": {"runId": "x"}})
    failed = store.get_start_request(late.request_id)
    assert (failed.status, failed.result_code, failed.result_detail) == ("실패", "E-RUN-CONCURRENT",
                                                                         {"active": {"runId": "x"}})


# ── 관리자 조회 ────────────────────────────────────────
def test_list_executions_and_calls(env):
    store, clock = env
    agent = uid()                                                                # 다른 테스트의 기록과 섞이지 않게
    pa = project(store)
    a, b = created(store, clock, project_id=pa), created(store, clock)
    recs = []
    for run, task, status in ((a, "T-C1", "성공"), (b, "T-C1", "실패"), (a, "T-C2", "성공")):
        rec = execution(clock, run, task, status).model_copy(update={"agent": agent})
        save(store, run, executions={rec.execution_id: rec})
        recs.append(rec)
    e0, e1, e2 = (r.execution_id for r in recs)

    def rows(**kw):
        return [(r.project_id, r.record.execution_id) for r in store.list_executions(ExecutionFilter(agent=agent, **kw))]
    assert rows() == [(pa, e2), (None, e1), (pa, e0)]                            # 시작 시각 최근 순
    assert rows(order="asc", limit=2, offset=1) == [(None, e1), (pa, e2)]
    assert rows(project_id=pa, order="asc") == [(pa, e0), (pa, e2)]
    assert rows(status="실패") == [(None, e1)] and rows(task_id="T-C2") == [(pa, e2)]
    assert rows(since=recs[1].started_at, until=recs[2].started_at) == [(None, e1)]
    assert store.list_executions(ExecutionFilter(agent=agent, limit=1))[0].record == recs[2]
    call = CallLog(call_id=uid(), run_id=a.run_id, execution_id=e0, task_id="T-C1", agent=agent, call_type="llm",
                   purpose="아이템 사양", timeout_sec=120.0, final_outcome="성공",
                   tries=[CallTry(no=1, started_at=clock(), ended_at=clock(), outcome="성공")])
    save(store, a, call_logs=[call])
    assert store.execution_calls(e0) == [call] and store.execution_calls(e1) == []


def test_project_requests_and_form_clearing(env):
    store, clock = env
    account, pid = uid(), project(store)
    failed = start_request(clock, account, pid)
    store.add_start_request(failed)
    assert store.acquire_start_request(failed.request_id, "A", 60)
    assert store.finish_start_request(failed.request_id, "A", status="실패", code="E-C1-TIMEOUT")
    waiting = start_request(clock, account, pid)
    assert store.add_start_request(waiting) is None
    assert [r.request_id for r in store.pending_start_requests(pid)] == [waiting.request_id]
    assert store.get_start_request(failed.request_id).form is None               # 끝날 때 이미 비웠다
    assert store.clear_start_request_forms(pid) == 1                              # 남은 대기 요청의 입력 사본
    assert store.get_start_request(waiting.request_id).form is None
    assert store.clear_start_request_forms(pid) == 0


# ── 여러 실행 건 · 여러 프로젝트 조회 (확장 — 웹 연동 함수 · 관리자 조회) ─────────
def test_query_runs_filters_order_and_paging(env):
    store, clock = env
    pids = [project(store) for _ in range(4)]
    a = created(store, clock, project_id=pids[0], progress="사용자대기", step="공고선택")
    b = created(store, clock, project_id=pids[1], progress="실행", step="계획서작성")
    c = created(store, clock, project_id=pids[2], progress="사용자대기", step="문서평가")
    loose = created(store, clock)                                                # 프로젝트 없음
    a.updated_at = clock()                                                       # a가 가장 최근에 갱신됨
    save(store, a)

    def ids(**kw):
        return [r.run_id for r in store.query_runs(RunFilter(project_ids=tuple(pids), **kw))]
    assert ids() == [a.run_id, c.run_id, b.run_id]                               # 마지막 갱신 최근 순
    assert ids(order="asc") == [b.run_id, c.run_id, a.run_id]
    assert ids(progress="사용자대기") == [a.run_id, c.run_id]
    assert ids(step="계획서작성") == [b.run_id] and ids(progress="완료") == []
    assert ids(limit=1, offset=1) == [c.run_id] and ids(limit=None, offset=2) == [b.run_id]
    assert store.query_runs(RunFilter(project_ids=tuple(pids), limit=1))[0] == store.load_run(a.run_id)
    assert store.query_runs(RunFilter(project_ids=(pids[3],))) == []             # 실행 건이 없는 프로젝트
    assert store.query_runs(RunFilter(project_ids=())) == []
    everything = [r.run_id for r in store.query_runs(RunFilter(limit=None))]     # MySQL은 다른 테스트 것도 나온다
    mine = [rid for rid in everything if rid in {a.run_id, b.run_id, c.run_id, loose.run_id}]
    assert mine == [a.run_id, loose.run_id, c.run_id, b.run_id]


def test_latest_start_requests_by_project(env):
    store, clock = env
    p1, p2, p3 = project(store), project(store), project(store)
    acc = uid()
    first = start_request(clock, acc, p1)
    store.add_start_request(first)
    assert store.cancel_start_request(first.request_id) == "취소"
    second = start_request(clock, acc, p1)
    assert store.add_start_request(second) is None
    other = start_request(clock, uid(), p2)
    assert store.add_start_request(other) is None
    got = store.latest_start_requests([p1, p2, p3])
    assert {k: v.request_id for k, v in got.items()} == {p1: second.request_id, p2: other.request_id}
    assert got[p1] == store.latest_start_request(p1) and got[p2] == store.latest_start_request(p2)
    assert store.latest_start_requests([]) == {}


def test_find_active_work_counts_like_add_start_request(env):
    store, clock = env
    acc = uid()
    assert store.find_active_work(acc) is None
    req = start_request(clock, acc)
    assert store.add_start_request(req) is None
    got = store.find_active_work(acc)                                            # 대기 요청
    assert isinstance(got, StartRequest) and got.request_id == req.request_id
    assert store.add_start_request(start_request(clock, acc)).request_id == got.request_id   # 같은 것이 막는다
    assert store.acquire_start_request(req.request_id, "A", 60)
    assert store.find_active_work(acc).request_id == req.request_id              # 처리중도 센다
    assert store.find_active_work(uid()) is None
    run = new_run(clock, acc, progress="사용자대기")
    assert store.create_run_for_request(run, CommitBatch(), req.request_id, "A") == "완료"
    got = store.find_active_work(acc)                                            # 확인 필요 실행 건
    assert isinstance(got, Run) and got == store.load_run(run.run_id)
    run.state = make_state("공고선택", "완료")
    save(store, run)
    assert store.find_active_work(acc) is None


def test_count_executions_and_unlimited_list(env):
    store, clock = env
    agent = uid()
    a, b = created(store, clock), created(store, clock)
    for run, task, status in ((a, "T-C1", "성공"), (b, "T-C1", "실패"), (a, "T-C2", "성공")):
        rec = execution(clock, run, task, status).model_copy(update={"agent": agent})
        save(store, run, executions={rec.execution_id: rec})
    assert store.count_executions(ExecutionFilter(agent=agent)) == 3
    assert store.count_executions(ExecutionFilter(agent=agent, status="성공", limit=1, offset=1)) == 2   # 쪽 무시
    assert store.count_executions(ExecutionFilter(agent=agent, task_id="T-C2")) == 1
    assert store.count_executions(ExecutionFilter(agent=uid())) == 0
    rows = store.list_executions(ExecutionFilter(agent=agent, limit=None))
    assert [(r.record.run_id, r.record.task_id) for r in rows] == [
        (a.run_id, "T-C2"), (b.run_id, "T-C1"), (a.run_id, "T-C1")]
    assert len(store.list_executions(ExecutionFilter(agent=agent, limit=None, offset=1))) == 2


# ── 기록 옮기기 · 12개월 처리 · 탈퇴용 저장소 기능 (확장) ─────────────────
STATS_RECORD_KINDS = ("executions", "call_logs", "feedback", "comparisons", "events", "pointer_events")


def records_of(clock: Clock, run: Run, kinds=STATS_RECORD_KINDS) -> dict:
    """여섯 기록 표에 한 줄씩 넣을 저장 묶음 (kinds에 든 것만)."""
    rec = execution(clock, run, status="성공")
    batch: dict = {}
    if "executions" in kinds:
        batch["executions"] = {rec.execution_id: rec}
    if "call_logs" in kinds:
        batch["call_logs"] = [CallLog(call_id=uid(), run_id=run.run_id, execution_id=rec.execution_id, task_id="T-C1",
                                      agent="조율", call_type="llm", purpose="아이템 사양", timeout_sec=120.0,
                                      final_outcome="성공",
                                      tries=[CallTry(no=1, started_at=clock(), ended_at=clock(), outcome="성공")])]
    if "feedback" in kinds:
        batch["feedback"] = [FeedbackLink(feedback_id=uid(), run_id=run.run_id, kind="재수행",
                                          source_execution_id=rec.execution_id, source_refs=["T-S1.check@1"],
                                          target_task_id="T-S1", target_execution_id=uid(),
                                          via_ref="T-S1.reworkInput@1", cycle_id=None, created_at=clock())]
    if "comparisons" in kinds:
        batch["comparisons"] = [ReworkComparison(bundle_id="1-1", before_refs=["planDoc@1"], after_refs=["planDoc@2"],
                                                 before_score=70.0, after_score=80.0, kept="후", cycle_id="c1",
                                                 screen=6, basis="document", compared_at=clock())]
    if "events" in kinds:
        batch["events"] = [TraceEvent(run_id=run.run_id, kind="재개", detail="사건", at=clock())]
    if "pointer_events" in kinds:
        batch["pointer_events"] = [PointerEvent(run_id=run.run_id, key="planDoc", from_version=2, to_version=1,
                                                reason="되돌리기", cycle_id="c1", at=clock())]
    return batch


def record_counts(store: Store, run_id: str) -> list[int]:
    return [len(store.executions(run_id)), len(store.call_logs(run_id)), len(store.feedback(run_id)),
            len(store.comparisons(run_id)), len(store.events(run_id)), len(store.pointer_events(run_id))]


def with_artifacts_and_records(store: Store, clock: Clock, run: Run, kinds=STATS_RECORD_KINDS) -> None:
    save(store, run, versions=[version(clock, run, "formInput", 1, {"a": 1}),
                               version(clock, run, "planDoc", 1, {"b": 2})],
         pointers={"formInput": 1, "planDoc": 1}, **records_of(clock, run, kinds))


def stats_row(**over) -> LogStatsRow:
    base = dict(kind="실행", reason="12개월", month="2026-09", category="웹개발", status="완료", part=1, count=1,
                data={"marker": uid(), "tasks": {"T-C1": {"성공": 1}}})
    base.update(over)
    return LogStatsRow(**base)


def marked(store: Store, row: LogStatsRow) -> list[LogStatsRow]:
    """저장된 통계 줄 중 이 테스트가 쓴 것 (MySQL은 다른 테스트 줄도 있다 — data.marker로 가른다)."""
    return [r for r in store.log_stats() if (r.data or {}).get("marker") == (row.data or {}).get("marker")]


def updated_column(store: Store, run_id: str):
    """orch_runs.updated_at 컬럼 값 (메모리는 실행 건 JSON 값)."""
    if isinstance(store, SqlStore):
        with store.engine.connect() as conn:
            return conn.execute(select(RUNS.c.updated_at).where(RUNS.c.run_id == run_id)).scalar_one()
    return store.load_run(run_id).updated_at


def test_retire_run_moves_records_and_keeps_run_artifacts_and_updated_at(env):
    store, clock = env
    run = created(store, clock, project_id=project(store), progress="사용자대기")
    other = created(store, clock, progress="사용자대기")
    with_artifacts_and_records(store, clock, run)
    with_artifacts_and_records(store, clock, other)
    before, column_before = store.load_run(run.run_id), updated_column(store, run.run_id)
    pointers, latest = store.get_pointers(run.run_id), store.get_latest_versions(run.run_id)
    assert record_counts(store, run.run_id) == [1] * 6 and before.stats_parts == 0
    clock.advance(hours=1)
    row = stats_row()
    assert store.acquire(run.run_id, "keeper", 60)
    store.retire_run(run.run_id, "keeper", stats=row, bump_parts=True)
    assert record_counts(store, run.run_id) == [0] * 6                       # 여섯 기록 표에서 지웠다
    assert record_counts(store, other.run_id) == [1] * 6                     # 다른 실행 건은 그대로
    after = store.load_run(run.run_id)                                        # 실행 건 줄 · 산출물은 남는다
    assert after.stats_parts == 1 and after.model_copy(update={"stats_parts": 0}) == before
    assert after.updated_at == before.updated_at and updated_column(store, run.run_id) == column_before
    assert store.get_pointers(run.run_id) == pointers and store.get_latest_versions(run.run_id) == latest
    assert store.get_artifact(run.run_id, "planDoc", 1).value == {"b": 2} and store.has_pointers(run.run_id)
    [got] = marked(store, row)                                                # 통계 줄 왕복 (쓴 시각은 저장소가)
    assert (got.kind, got.reason, got.month, got.category, got.status, got.result_code, got.part, got.count,
            got.data) == (row.kind, row.reason, row.month, row.category, row.status, None, 1, 1, row.data)
    assert got.created_at is not None and got.created_at.tzinfo is not None and got.created_at <= clock.t
    assert store.is_locked(run.run_id, clock.t)                              # 점유는 부른 쪽이 푼다
    store.retire_run(run.run_id, "keeper", stats=stats_row(part=2), bump_parts=True)
    assert store.load_run(run.run_id).stats_parts == 2
    store.retire_run(run.run_id, "keeper")                                    # 통계 줄 없이 · 횟수 그대로
    assert store.load_run(run.run_id).stats_parts == 2
    store.release(run.run_id, "keeper")


def test_retire_run_requires_lease_and_changes_nothing_without_it(env):
    store, clock = env
    run = created(store, clock, progress="완료")
    with_artifacts_and_records(store, clock, run)
    row = stats_row()
    with pytest.raises(StoreConflict):
        store.retire_run(run.run_id, "keeper", stats=row, bump_parts=True)    # 점유 없음
    assert store.acquire(run.run_id, "someone", 60)
    with pytest.raises(StoreConflict):
        store.retire_run(run.run_id, "keeper", stats=row, delete_run=True)    # 다른 점유자
    assert record_counts(store, run.run_id) == [1] * 6 and marked(store, row) == []
    assert store.load_run(run.run_id).stats_parts == 0 and store.has_pointers(run.run_id)
    with pytest.raises(StoreConflict):
        store.retire_run(uid(), "keeper")                                     # 없는 실행 건


def test_retire_run_with_delete_removes_everything_of_that_run_only(env):
    store, clock = env
    pid = project(store)
    run = created(store, clock, project_id=pid, progress="완료")
    other = created(store, clock, progress="완료")
    with_artifacts_and_records(store, clock, run)
    with_artifacts_and_records(store, clock, other)
    store.delete_artifacts(run.run_id)                                         # 완전 삭제 = 포인터가 하나도 없음
    assert not store.has_pointers(run.run_id) and store.has_pointers(other.run_id)
    row = stats_row(reason="탈퇴")
    assert store.acquire(run.run_id, "keeper", 60)
    store.retire_run(run.run_id, "keeper", stats=row, delete_run=True)
    with pytest.raises(KeyError):
        store.load_run(run.run_id)
    assert record_counts(store, run.run_id) == [0] * 6
    assert store.get_pointers(run.run_id) == {} and store.get_latest_versions(run.run_id) == {}
    assert store.find_run_by_project(pid) is None and len(marked(store, row)) == 1
    assert record_counts(store, other.run_id) == [1] * 6 and store.get_pointers(other.run_id)
    live = created(store, clock, progress="완료")                              # 산출물이 남은 실행 건도 함께 지운다
    with_artifacts_and_records(store, clock, live)
    assert store.acquire(live.run_id, "keeper", 60)
    store.retire_run(live.run_id, "keeper", delete_run=True)                  # 통계 줄 없이
    assert store.get_pointers(live.run_id) == {} and store.get_latest_versions(live.run_id) == {}
    with pytest.raises(KeyError):
        store.get_artifact(live.run_id, "planDoc", 1)
    with pytest.raises(KeyError):
        store.load_run(live.run_id)


def aged_run(store: Store, clock: Clock, at: datetime, *, progress: str = "완료", kinds=STATS_RECORD_KINDS,
             artifacts: bool = True) -> Run:
    """마지막 활동 시각이 at인 실행 건 (기록은 kinds에 든 표만)."""
    run = created(store, clock, progress=progress, step="계획서작성" if progress == "재개대기" else "공고선택")
    batch = records_of(clock, run, kinds) if kinds else {}
    if artifacts:
        batch.update(versions=[version(clock, run, "formInput", 1, {"a": 1})], pointers={"formInput": 1})
    run.updated_at = at
    save(store, run, **batch)
    return run


def test_retention_run_targets(env):
    store, clock = env
    old = clock.t - timedelta(days=400)
    cutoff = clock.t - timedelta(days=365)
    picked = {
        "done": aged_run(store, clock, old),
        "waiting": aged_run(store, clock, old, progress="사용자대기"),
        "failed": aged_run(store, clock, old, progress="실패"),
        "deleted": aged_run(store, clock, old, kinds=(), artifacts=False),      # 완전 삭제 — 옮길 기록 없어도
        "just_before": aged_run(store, clock, cutoff - timedelta(milliseconds=1)),
        "expired_lease": aged_run(store, clock, old),
        **{f"only_{k}": aged_run(store, clock, old, kinds=(k,)) for k in STATS_RECORD_KINDS},
    }
    skipped = {
        "running": aged_run(store, clock, old, progress="실행"),
        "resume_wait": aged_run(store, clock, old, progress="재개대기"),
        "leased": aged_run(store, clock, old),
        "nothing_to_move": aged_run(store, clock, old, kinds=()),               # 이미 옮김 — 대상 묶음을 채우지 않는다
        "at_cutoff": aged_run(store, clock, cutoff),
        "recent": aged_run(store, clock, clock.t),
    }
    assert store.acquire(skipped["leased"].run_id, "someone", 3600)
    assert store.acquire(picked["expired_lease"].run_id, "dead", 1)
    clock.advance(seconds=2)
    got = store.retention_run_targets(cutoff, limit=100000)
    ids = set(got)
    assert {r.run_id for r in picked.values()} <= ids, sorted(k for k, r in picked.items() if r.run_id not in ids)
    assert not ids & {r.run_id for r in skipped.values()}, sorted(k for k, r in skipped.items() if r.run_id in ids)
    assert len(store.retention_run_targets(cutoff, limit=2)) == 2
    mine = [rid for rid in got if rid in {r.run_id for r in picked.values()}]
    assert mine[-1] == picked["just_before"].run_id                           # 마지막 활동이 오래된 순


def closed_request(store: Store, clock: Clock, account: str, how: str) -> StartRequest:
    req = start_request(clock, account)
    assert store.add_start_request(req, max_active=100) is None
    if how == "취소":
        assert store.cancel_start_request(req.request_id) == "취소"
    elif how == "실패":
        assert store.acquire_start_request(req.request_id, "w", 60)
        assert store.finish_start_request(req.request_id, "w", status="실패", code="E-C1-TIMEOUT")
    elif how == "완료":
        assert store.acquire_start_request(req.request_id, "w", 60)
        assert store.create_run_for_request(new_run(clock, account, progress="완료"), CommitBatch(),
                                            req.request_id, "w", max_active=100) == "완료"
    elif how == "처리중":
        assert store.acquire_start_request(req.request_id, "w", 60)
    return store.get_start_request(req.request_id)


def test_finished_requests_lose_form_and_pending_keep_it(env):
    store, clock = env
    account = uid()
    for how in ("완료", "실패", "취소"):
        assert closed_request(store, clock, account, how).form is None, how
    waiting = closed_request(store, clock, account, "대기")
    processing = closed_request(store, clock, account, "처리중")
    assert waiting.form is not None and processing.form is not None
    assert store.cancel_start_request(processing.request_id) == "취소요청"
    assert store.get_start_request(processing.request_id).form is not None   # 취소 요청만 — 아직 처리중
    assert store.create_run_for_request(new_run(clock, account), CommitBatch(), processing.request_id, "w",
                                        max_active=100) == "취소"
    assert store.get_start_request(processing.request_id).form is None


def test_retention_request_targets_and_retire(env):
    store, clock = env
    account = uid()
    old = [closed_request(store, clock, account, how) for how in ("완료", "실패", "취소")]
    clock.advance(seconds=10)
    cutoff = clock.t
    pending = [closed_request(store, clock, account, how) for how in ("대기", "처리중")]
    new = closed_request(store, clock, account, "실패")
    got = store.retention_request_targets(cutoff, limit=100000)
    ids = [r.request_id for r in got]
    assert {r.request_id for r in old} <= set(ids)
    assert not set(ids) & {r.request_id for r in pending + [new]}
    assert len(store.retention_request_targets(cutoff, limit=1)) == 1
    boundary = store.retention_request_targets(old[1].updated_at, limit=100000)
    assert old[0].request_id in {r.request_id for r in boundary}
    assert old[1].request_id not in {r.request_id for r in boundary}          # 같은 시각은 대상이 아니다
    mine = {r.request_id: r for r in got if r.request_id in {o.request_id for o in old}}
    assert {r.status for r in mine.values()} == {"완료", "실패", "취소"} and all(r.form is None for r in mine.values())

    marker = uid()
    rows = [LogStatsRow(kind="시작요청", reason="12개월", month="2026-09", status=s, result_code=c, count=1,
                        data={"marker": marker}) for s, c in (("완료", None), ("실패", "E-C1-TIMEOUT"), ("취소", None))]
    with pytest.raises(StoreConflict):                                        # 끝나지 않은 요청이 섞이면 아무것도 안 함
        store.retire_start_requests([old[0].request_id, pending[0].request_id], rows)
    with pytest.raises(StoreConflict):                                        # 없는 요청
        store.retire_start_requests([old[0].request_id, uid()], rows)
    assert store.get_start_request(old[0].request_id).status == "완료"
    assert [r for r in store.log_stats() if (r.data or {}).get("marker") == marker] == []
    assert store.retire_start_requests([r.request_id for r in old], rows) == 3
    for r in old:
        with pytest.raises(KeyError):
            store.get_start_request(r.request_id)
    written = [r for r in store.log_stats() if (r.data or {}).get("marker") == marker]
    assert [(r.kind, r.status, r.result_code, r.part, r.count, r.category) for r in written] == [
        ("시작요청", "완료", None, 1, 1, None), ("시작요청", "실패", "E-C1-TIMEOUT", 1, 1, None),
        ("시작요청", "취소", None, 1, 1, None)]
    assert store.get_start_request(pending[0].request_id).status == "대기"
    assert store.retire_start_requests([], []) == 0


def test_list_start_requests_of_account(env):
    store, clock = env
    account, other = uid(), uid()
    reqs = [closed_request(store, clock, account, how) for how in ("완료", "취소", "대기")]
    closed_request(store, clock, other, "대기")
    assert [r.request_id for r in store.list_start_requests(account)] == [r.request_id for r in reqs]
    assert store.list_start_requests(uid()) == []


@TIMING
def test_account_guard_blocks_add_start_request(env):
    store, clock = env
    account = uid()
    held, release, done = threading.Event(), threading.Event(), threading.Event()
    result: list = []

    def guard() -> None:
        with store.account_guard(account):
            held.set()
            release.wait(10)

    def add() -> None:
        result.append(store.add_start_request(start_request(clock, account)))
        done.set()
    holder = threading.Thread(target=guard)
    holder.start()
    assert held.wait(10)
    adder = threading.Thread(target=add)
    adder.start()
    assert not done.wait(0.5)                                                  # 잠금을 잡은 동안 기다린다
    assert store.add_start_request(start_request(clock, uid())) is None       # 다른 계정은 기다리지 않는다
    release.set()
    holder.join(10)
    adder.join(10)
    assert done.is_set() and result == [None]


@TIMING
def test_account_guard_timeout_is_store_conflict(env):
    store, clock = env
    account = uid()
    store.account_lock_timeout = 1
    held, release = threading.Event(), threading.Event()

    def guard() -> None:
        with store.account_guard(account):
            held.set()
            release.wait(10)
    holder = threading.Thread(target=guard)
    holder.start()
    try:
        assert held.wait(10)
        with pytest.raises(StoreConflict):
            store.add_start_request(start_request(clock, account))
    finally:
        release.set()
        holder.join(10)
    assert store.add_start_request(start_request(clock, account)) is None


def test_job_lease(env):
    store, clock = env
    job = "job-" + uid()
    assert store.get_job(job) is None
    assert store.try_start_job(job, "A", 60, interval_sec=3600)              # 줄이 없으면 만든다
    st = store.get_job(job)
    assert (st.lease_owner, st.last_finished_at, st.last_summary) == ("A", None, None)
    assert st.last_started_at is not None and st.lease_until > st.last_started_at
    assert not store.try_start_job(job, "B", 60, interval_sec=3600)          # 점유 중
    assert not store.try_start_job(job, "A", 60, interval_sec=3600)          # 같은 점유자도 다시 시작하지 않는다
    assert not store.renew_job(job, "B", 60) and store.renew_job(job, "A", 120)
    assert store.get_job(job).lease_until > st.lease_until
    assert not store.release_job(job, "B")
    assert store.release_job(job, "A")                                        # 종료 신호 — 마친 시각은 쓰지 않는다
    st = store.get_job(job)
    assert (st.lease_owner, st.lease_until, st.last_finished_at) == (None, None, None)
    assert store.try_start_job(job, "B", 60, interval_sec=3600)              # 끝까지 마친 적이 없으니 바로
    summary = {"runs": 3, "deletedRuns": 1, "requests": 5, "skipped": 0}
    with pytest.raises(ValueError):
        store.finish_job(job, "B", {"runs": "3"})                            # 개수만
    assert not store.finish_job(job, "A", summary)
    assert store.finish_job(job, "B", summary)
    st = store.get_job(job)
    assert (st.lease_owner, st.lease_until, st.last_summary) == (None, None, summary)
    assert st.last_finished_at is not None
    assert not store.try_start_job(job, "C", 60, interval_sec=3600)          # 간격이 지나지 않음
    clock.advance(seconds=3601)
    assert store.try_start_job(job, "C", 60, interval_sec=3600)
    clock.advance(seconds=61)                                                 # C가 멈춤 — 점유 만료
    assert not store.renew_job(job, "D", 60)
    assert store.try_start_job(job, "D", 60, interval_sec=3600)              # 만료된 점유는 이어받는다
    assert not store.finish_job(job, "C", summary) and not store.renew_job(job, "C", 60)
    assert store.get_job(job).lease_owner == "D"


@TIMING
def test_job_concurrent_start_allows_one(env):
    store, clock = env
    job = "job-" + uid()
    results: list[bool] = []
    barrier = threading.Barrier(6)

    def go(i: int) -> None:
        barrier.wait()
        results.append(store.try_start_job(job, f"w{i}", 60, interval_sec=3600))
    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 5 + [True]


def test_query_runs_updated_since(env):
    store, clock = env
    pids = [project(store) for _ in range(3)]
    runs = [created(store, clock, project_id=p) for p in pids]
    since = runs[1].updated_at

    def ids(**kw):
        return [r.run_id for r in store.query_runs(RunFilter(project_ids=tuple(pids), order="asc", **kw))]
    assert ids(updated_since=since) == [runs[1].run_id, runs[2].run_id]       # 이상 (같은 시각 포함)
    assert ids(updated_since=since.replace(tzinfo=None)) == ids(updated_since=since)   # 시간대 없는 값은 UTC
    assert ids(updated_since=clock.t + timedelta(days=1)) == []
