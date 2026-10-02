"""저장소 계약 — 메모리 · SqlStore(SQLite) · SqlStore(MySQL 8)가 같은 동작인지.

MySQL은 SBRAIN_TEST_MYSQL_URL(환경 변수 또는 .env)이 있을 때만 돈다. 여러 테스트가 같은 MySQL DB를 쓰므로
계정 · 실행 건 ID는 테스트마다 새로 만든다.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

import pytest
from conftest import Backend, Clock
from webdb import new_project

from sbrain.models import CycleState, Notice, Notification, RejectedAttempt, ReworkComparison, Run
from sbrain.models.run import make_state
from sbrain.orchestrator.errors import ProjectRunExists, StoreConflict
from sbrain.orchestrator.store import ArtifactVersion, CommitBatch, ExecutionFilter, RunFilter, StartRequest, Store
from sbrain.orchestrator.trace import CallLog, CallTry, ExecutionRecord, FeedbackLink, PointerEvent, TraceEvent
from sbrain.store_sql import SqlStore


@pytest.fixture
def env(any_backend: Backend):
    clock = Clock()
    return any_backend.make_store(clock), clock


def uid() -> str:
    return uuid.uuid4().hex[:12]


def project(store: Store, *, agreed: bool = False) -> str:
    """프로젝트 ID. SqlStore면 웹 projects 행(주인 계정의 학습 동의 = agreed)을 만든다."""
    if isinstance(store, SqlStore):
        return str(new_project(store.engine, agreed=agreed))
    pid = uid()
    store.set_training_consent(pid, agreed)
    return pid


def new_run(clock: Clock, account: str, *, project_id: str | None = None, progress: str = "실행",
            step: str = "공고선택", **over) -> Run:
    now = clock()
    return Run(run_id=uid(), account_id=account, state=make_state(step, progress), current_phase="setup",
               settings_snapshot={"note": "test"}, updated_at=now, created_at=now, project_id=project_id, **over)


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


def rejected(run: Run, no: int) -> RejectedAttempt:
    return RejectedAttempt(run_id=run.run_id, original_text="원문 (1억원)", corrected_text=f"반려 {no}",
                           reason="보호 토큰 검사 불통과 (빠짐 1건)", attempt_no=no, violation_type="수치·금액",
                           violation_note="빠짐: 1억원", model_version="미정")


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
    assert store.clear_start_request_forms(pid) == 2                              # 끝난 요청의 입력 사본도 지운다
    assert store.get_start_request(failed.request_id).form is None
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
