"""워커 — 가져가기 · 점유 · 하트비트 · 종료 신호 · 재개 · 보관 기간 작업, 워커 실행 입구(main).

여러 워커는 같은 DB 파일을 쓰는 앱(프로세스 하나에 해당) 여러 개로 흉내 낸다. 조립은 test_bootstrap.py가 본다.
"""
from __future__ import annotations

import signal
import threading
import time

import pytest
from conftest import TIMING, Clock
from mysqldb import MYSQL, require_mysql
from worker_helpers import app_on, projects, start, worker

from sbrain import env
from sbrain.bootstrap import App, build_stub_app, build_web
from sbrain.flow.retention import JOB_NAME, start_retention
from sbrain.intake import MemoryProjectInputSource
from sbrain.models.clock import utc_now
from sbrain.worker import Worker, WorkerConfig, install_signal_handlers, main


def run_until_idle(workers: list[Worker], threads: int = 2) -> None:
    """워커마다 스레드 여러 개로, 두 바퀴 연속 할 일이 없을 때까지 돈다."""
    def go(w: Worker, i: int) -> None:
        idle = 0
        while idle < 2:
            idle = 0 if w.run_once(w.owner(i)) else idle + 1
    ts = [threading.Thread(target=go, args=(w, i)) for w in workers for i in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=120)
    assert not any(t.is_alive() for t in ts)


# ── 여러 워커 ──────────────────────────────────────────
@pytest.fixture(params=[pytest.param("sqlite", marks=TIMING), pytest.param("mysql", marks=MYSQL)])
def shared_db(request, db):
    return db if request.param == "sqlite" else require_mysql()


def test_two_workers_never_do_the_same_work(shared_db):
    source = projects(6, shared_db)
    web = app_on(shared_db, source)
    apps = [app_on(shared_db, source), app_on(shared_db, source)]
    requests = start(web, source)
    run_until_idle([worker(a) for a in apps])
    reqs = [web.store.get_start_request(r) for r in requests]
    assert [(r.status, r.claim_count) for r in reqs] == [("완료", 1)] * 6        # 한 번씩만 가져갔다
    tc1_calls = [q for a in apps for q in a.llm.requests if q.metadata["task_id"] == "T-C1"]
    assert len(tc1_calls) == 6                                                   # 사전 단계도 한 번씩
    run_ids = [r.run_id for r in reqs]
    for rid in run_ids:
        web.orchestrator.select_announcement(rid, "A01")                        # 웹 명령 → '실행'
    run_until_idle([worker(a) for a in apps])
    for rid in run_ids:
        run = web.store.load_run(rid)
        assert (run.state.step, run.state.progress) == ("계획서작성", "사용자대기")
        assert [e.task_id for e in web.store.executions(rid)] == ["T-C1", "T-C2", "G-01"]


# ── 점유 만료 · 이어받기 ────────────────────────────────
def test_dead_worker_lease_expires_and_other_takes_over(db):
    clock = Clock()
    source = projects(1)
    a, b = app_on(db, source, clock), app_on(db, source, clock)
    rid = a.orchestrator.run_start_request(start(a, source)[0])
    a.orchestrator.select_announcement(rid.run_id, "A01")
    run_until_idle([worker(a)], threads=1)
    a.orchestrator.start_writing(rid.run_id)
    a.store.release = lambda run_id, owner: None                                # 프로세스가 죽어 점유를 못 푼다

    def die(_request):
        raise SystemExit("워커 프로세스 종료")
    a.llm.respond("T-S1", die)
    with pytest.raises(SystemExit):
        worker(a, lease_sec=60).run_once("dead")                                 # T-C3 저장 뒤 T-S1 도중에 죽음
    wb = worker(b, lease_sec=60)
    assert wb.run_once("alive") == []                                            # 점유가 남아 있는 동안은 못 가져간다
    clock.advance(seconds=61)
    assert wb.run_once("alive") == ["진행 " + rid.run_id + " 사용자대기"]
    run = b.store.load_run(rid.run_id)
    assert (run.state.step, run.state.progress) == ("문서평가", "사용자대기")
    done = [e.task_id for e in b.store.executions(rid.run_id)]
    assert done.count("T-C3") == 1 and done.count("T-S1") == 1
    calls = [q.metadata["task_id"] for app in (a, b) for q in app.llm.requests]
    assert calls.count("T-S1") == 2                                              # 단계 한 번 더 호출 (허용)


def test_start_request_taken_over_and_capped(db):
    clock = Clock()
    source = projects(2)
    app = app_on(db, source, clock)
    first, second = start(app, source)
    assert app.store.claim_start_request("dead", 60) == first
    w = worker(app, lease_sec=60)
    w.run_once("alive")                                                           # 둘째 요청만 처리
    assert app.store.get_start_request(second).status == "완료"
    assert app.store.get_start_request(first).status == "처리중"
    for owner in ("dead-2", "dead-3"):                                            # 또 죽은 워커 두 번
        clock.advance(seconds=61)
        assert app.store.claim_start_request(owner, 60) == first
    clock.advance(seconds=61)
    before = len(app.llm.requests)
    w.run_once("alive")
    st = app.store.get_start_request(first)
    assert (st.status, st.result_code, st.claim_count) == ("실패", "E-C1-TIMEOUT", 4)   # 가져간 횟수 상한
    assert len(app.llm.requests) == before                                        # 다시 돌지 않았다


# ── 단계 사이 · 종료 신호 ───────────────────────────────
def to_writing(app: App, source: MemoryProjectInputSource) -> str:
    rid = app.orchestrator.run_start_request(start(app, source)[0]).run_id
    app.orchestrator.select_announcement(rid, "A01")
    run_until_idle([worker(app)], threads=1)
    app.orchestrator.start_writing(rid)
    return rid


def test_abort_request_applies_between_steps(db):
    source = projects(1)
    app = app_on(db, source)
    rid = to_writing(app, source)

    def abort_during(_request):
        app.orchestrator.abort(rid, confirmed=True)                              # 워커가 점유 중 → 중단 요청만 남는다
        return '{"ok": true}'
    app.llm.respond("T-S1", abort_during)
    worker(app).run_once("w")
    run = app.store.load_run(rid)
    assert run.state.progress == "중단"
    assert [e.task_id for e in app.store.executions(rid)][-1] == "T-S1"          # 하던 단계는 끝냈다


def test_stop_finishes_current_step_and_leaves_rest(db):
    source = projects(1)
    app = app_on(db, source)
    rid = to_writing(app, source)
    w = worker(app)

    def stop_during(_request):
        w.stop()                                                                  # 종료 신호
        return '{"ok": true}'
    app.llm.respond("T-S1", stop_during)
    assert w.run_once("w") == [f"진행 {rid} 실행"]
    run = app.store.load_run(rid)
    assert run.state.progress == "실행" and run.queue[0] == "T-S2"               # 남은 단계는 '실행'으로 남는다
    assert not app.store.is_locked(rid, utc_now())                          # 점유를 풀었다
    app.llm.responders.clear()
    worker(app).run_once("next")                                                  # 다른 워커가 이어받는다
    assert app.store.load_run(rid).state.step == "문서평가"


@TIMING
def test_signal_handler_stops_worker():
    w = Worker(build_stub_app(), WorkerConfig(), log=lambda line: None)
    saved = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        install_signal_handlers(w)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert w.stopping.is_set()
    finally:
        for s, h in saved.items():
            signal.signal(s, h)


@TIMING
def test_run_loop_with_heartbeat_and_clean_shutdown(db):
    source = projects(1)
    app = app_on(db, source)
    logs: list[str] = []
    w = worker(app, logs, poll_sec=0.05, threads=2, lease_sec=2.0)
    beats = []
    renew = app.store.renew_start_request
    app.store.renew_start_request = lambda *a: beats.append(a) or renew(*a)
    app.llm.respond("T-C1", lambda r: time.sleep(0.7) or '{"ok": true}')        # 하트비트(0.5초)가 한 번은 돈다
    [req] = start(app, source)
    t = threading.Thread(target=w.run)
    t.start()
    deadline = time.time() + 30
    while app.store.get_start_request(req).status != "완료" and time.time() < deadline:
        time.sleep(0.05)
    w.stop()
    t.join(timeout=10)
    assert not t.is_alive() and app.store.get_start_request(req).status == "완료"
    assert beats and beats[0][0] == req
    text = "\n".join(logs)
    assert f"가져감 시작요청 {req}" in text and "끝 시작요청" in text and text.rstrip().endswith("끝")
    assert "헬스장" not in text                                                   # 입력 · 응답 내용은 남기지 않는다


# ── 한 바퀴 · 재개 ─────────────────────────────────────
def test_request_to_wait_points_through_worker(db):
    source = projects(1)
    app = app_on(db, source)
    w = worker(app)
    [req] = start(app, source)
    [line] = w.run_once("w")
    assert line.startswith(f"시작요청 {req} 완료 run=")
    rid = app.store.get_start_request(req).run_id
    assert app.orchestrator.view(rid).step == "공고선택"
    app.orchestrator.select_announcement(rid, "A01")
    assert w.run_once("w") == [f"진행 {rid} 사용자대기"]
    app.orchestrator.start_writing(rid)
    w.run_once("w")
    view = app.orchestrator.view(rid)
    assert (view.step, view.progress) == ("문서평가", "사용자대기")
    assert [n.kind for n in view.notifications] == ["문서평가"]                    # 웹 notifications에 쓰였다
    assert w.run_once("w") == []                                                  # 사용자 대기 — 할 일 없음


def test_resume_waits_until_due(db):
    clock = Clock()
    source = projects(1)
    app = app_on(db, source, clock)
    rid = to_writing(app, source)
    app.llm.plan("T-S1", ["timeout"] * 6)
    w = worker(app, lease_sec=60)
    w.run_once("w")
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기"
    assert w.run_once("w") == []                                                  # 재개 시각 전
    clock.t = run.next_resume_at
    assert w.run_once("w") == [f"재개 {rid} 사용자대기"]
    assert app.store.load_run(rid).state.step == "문서평가"


def test_worker_waits_for_rework_collecting_window(db):
    clock = Clock()
    source = projects(1)
    app = app_on(db, source, clock)
    rid = to_writing(app, source)
    w = worker(app, lease_sec=60)
    assert w.run_once("w") == [f"진행 {rid} 사용자대기"]                         # 계획서 작성 → 화면 6 대기
    pid = app.store.load_run(rid).project_id
    acc = app.orchestrator.request_rework_for_project(pid, "문제인식")          # 웹: 접수만 하고 바로 돌아온다
    assert app.orchestrator.request_rework_for_project(pid, "팀 구성").cycle_id == acc.cycle_id
    assert w.run_once("w") == []                                                  # 모으는 동안은 가져가지 않는다
    assert app.store.load_run(rid).state.progress == "실행"
    clock.t = acc.collect_until
    assert w.run_once("w") == [f"진행 {rid} 사용자대기"]                         # 시간이 지나면 가져가 진행한다
    run = app.store.load_run(rid)
    assert (run.state.step, run.last_rework.status, run.last_rework.bundles) == (
        "문서평가", "완료", ["문제인식", "팀 구성"])
    assert [r.task_id for r in app.store.executions(rid) if r.cycle_id == acc.cycle_id] == [
        "T-W1", "T-W2", "T-W3", "M-1", "T-V1", "G-02a"]


def test_error_outside_steps_backs_off(db):
    clock = Clock()
    source = projects(1)
    app = app_on(db, source, clock)
    rid = to_writing(app, source)
    logs: list[str] = []
    w = worker(app, logs, lease_sec=60)
    drain = app.engine.drain

    def broken(ctx):
        app.engine.drain = drain
        raise RuntimeError("DB 연결 끊김")
    app.engine.drain = broken
    assert w.run_once("w") == [f"진행 {rid} 오류 RuntimeError"]
    assert any("오류 진행" in line and "DB 연결 끊김" in line for line in logs)
    assert w.run_once("w") == []                                                  # 점유 시간 동안 다시 가져가지 않는다
    clock.advance(seconds=61)
    assert w.run_once("w") == [f"진행 {rid} 사용자대기"]


# ── ④ 보관 기간 작업 ───────────────────────────────────
def test_loop_runs_retention_job_and_logs_only_counts(db):
    clock = Clock()
    source = projects(1)
    app = app_on(db, source, clock)
    rid = to_writing(app, source)
    logs: list[str] = []
    w = worker(app, logs, lease_sec=60, job_check_sec=0)
    assert w.run_once("w") == [f"진행 {rid} 사용자대기"]                         # 작업은 돌려주는 목록에 넣지 않는다
    assert app.store.get_job(JOB_NAME).last_summary["runs"] == 0                 # 한 바퀴에서 작업을 확인 · 돌았다
    clock.advance(days=400)
    logs.clear()
    assert w.run_once("w") == []
    job = app.store.get_job(JOB_NAME)
    assert job.lease_owner is None and job.last_summary == {"runs": 1, "deletedRuns": 0, "requests": 1, "skipped": 0}
    assert app.store.executions(rid) == [] and len(app.store.log_stats("실행")) == 1
    assert [line.split(" ", 3)[3] for line in logs] == [
        "보관 작업 시작", "보관 작업 끝 — 옮긴 실행 건 1 · 지운 실행 건 0 · 옮긴 시작 요청 1 · 건너뜀 0"]
    assert all(line[:19].count(":") == 2 and line[19] == "Z" for line in logs)   # 시각은 UTC (끝의 Z)
    assert rid not in "\n".join(logs)                                             # 실행 건 ID를 남기지 않는다
    logs.clear()
    w.run_once("w")
    assert logs == []                                                             # 24시간 안에는 다시 돌지 않는다


def test_retention_checked_once_per_check_interval(db):
    clock = Clock()
    app = app_on(db, projects(0), clock)
    logs: list[str] = []
    w = worker(app, logs)                                                         # 확인 주기 10분 (잠정)
    w.run_once("w")
    first = app.store.get_job(JOB_NAME).last_finished_at
    clock.advance(days=2)
    w.run_once("w")
    assert app.store.get_job(JOB_NAME).last_finished_at == first                  # 주기 전에는 확인하지 않는다
    assert sum("보관 작업 시작" in line for line in logs) == 1
    w.stop()
    w._next_job_check = 0
    assert w.run_once("w") == [] and app.store.get_job(JOB_NAME).last_finished_at == first   # 멈추면 돌지 않는다


def test_retention_stop_signal_between_runs(db):
    clock = Clock()
    source = projects(2)
    app = app_on(db, source, clock)
    rids = [app.orchestrator.run_start_request(r).run_id for r in start(app, source)]
    clock.advance(days=400)
    w = worker(app, lease_sec=60, job_check_sec=0)
    retire = app.store.retire_run

    def retire_then_stop(*a, **kw):
        retire(*a, **kw)
        w.stop()                                                                  # 종료 신호 — 실행 건 사이에서 멈춘다
    app.store.retire_run = retire_then_stop
    w.run_once("w")
    job = app.store.get_job(JOB_NAME)
    assert job.last_finished_at is None and job.lease_owner is None
    assert sorted(len(app.store.executions(r)) == 0 for r in rids) == [False, True]


def test_heartbeat_extends_job_lease(db):
    clock = Clock()
    app = app_on(db, projects(0), clock)
    w = worker(app, lease_sec=60)
    assert start_retention(app.store, "w", 60)
    before = app.store.get_job(JOB_NAME).lease_until
    clock.advance(seconds=30)
    w._held[("작업", JOB_NAME)] = "w"
    w.heartbeat()
    assert app.store.get_job(JOB_NAME).lease_until > before
    assert not start_retention(app.store, "other", 60)


def test_build_web_never_runs_retention(tmp_path, db):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    source = projects(1)
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source)
    start(web, source)
    web.orchestrator.admin_summary()
    web.orchestrator.admin_runs()
    assert web.store.get_job(JOB_NAME) is None                                    # 웹 조립 · 웹 함수는 작업을 돌지 않는다
    worker(app_on(db, source)).run_once("w")
    assert web.store.get_job(JOB_NAME).last_finished_at is not None              # 워커만 돈다


# ── 실행 입구 (main) ──────────────────────────────────
def test_main_checks_settings_and_runs_once(monkeypatch, tmp_path, db, capsys):
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", tmp_path / "없음.env")
    monkeypatch.delenv("SBRAIN_DB_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["--once"]) == 2
    assert "SBRAIN_DB_URL, OPENAI_API_KEY" in capsys.readouterr().err
    monkeypatch.setenv("SBRAIN_DB_URL", f"sqlite:///{(tmp_path / 'worker.db').as_posix()}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")                      # 할 일이 없어 호출하지 않는다
    assert main(["--once"]) == 0
    assert "할 일 없음" in capsys.readouterr().out
