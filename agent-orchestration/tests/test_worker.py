"""워커 — 가져가기 · 점유 · 하트비트 · 종료 신호, 웹 프로세스와 워커가 같은 DB를 쓰는 조립.

여러 워커는 같은 DB 파일을 쓰는 앱(프로세스 하나에 해당) 여러 개로 흉내 낸다.
"""
from __future__ import annotations

import signal
import threading
import time
from datetime import datetime

import pytest
from conftest import Clock, pre_input, project_record
from mysqldb import require_mysql
from test_tc1 import item_json
from webdb import create_web_tables, new_project

from sbrain import env
from sbrain.agents.stubs import FakeLLM, StubScenario
from sbrain.bootstrap import App, build_app, build_stub_app, build_web
from sbrain.intake import MemoryProjectInputSource
from sbrain.orchestrator.errors import CommandError
from sbrain.store_sql import DbSettingsProvider, SqlStore, create_orchestrator_tables, create_sqlite_engine
from sbrain.worker import Worker, WorkerConfig, install_signal_handlers, main


@pytest.fixture
def db(tmp_path):
    engine = create_sqlite_engine(tmp_path / "worker.db", fast=True)
    create_orchestrator_tables(engine)
    create_web_tables(engine)
    return engine


def projects(n: int, engine=None) -> MemoryProjectInputSource:
    """계정 n개에 프로젝트 하나씩 (MySQL은 웹 projects 행도 만든다)."""
    source = MemoryProjectInputSource()
    for i in range(n):
        pid = new_project(engine) if engine is not None and engine.dialect.name == "mysql" else 201 + i
        source.add(project_record(project={"project_id": pid}, company={"user_id": 9000 + i}))
    return source


def app_on(engine, source, now=datetime.now, scenario: StubScenario | None = None) -> App:
    return build_stub_app(scenario, now=now, store=SqlStore(engine, now=now), project_inputs=source)


def worker(app: App, logs: list[str] | None = None, **cfg) -> Worker:
    return Worker(app, WorkerConfig(**cfg), log=(logs.append if logs is not None else lambda line: None),
                  name=f"w{id(app) % 1000}")


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


def start(app: App, source: MemoryProjectInputSource) -> list[str]:
    ids = []
    for pid, rec in source._records.items():
        check = app.orchestrator.request_start(str(rec.company.user_id), pid)
        assert check.ok, check
        ids.append(check.request_id)
    return ids


# ── 여러 워커 ──────────────────────────────────────────
@pytest.fixture(params=["sqlite", "mysql"])
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
    assert not app.store.is_locked(rid, datetime.now())                          # 점유를 풀었다
    app.llm.responders.clear()
    worker(app).run_once("next")                                                  # 다른 워커가 이어받는다
    assert app.store.load_run(rid).state.step == "문서평가"


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


# ── 조립 (워커 · 웹) ───────────────────────────────────
def test_build_app_routes_only_real_tasks_to_real_llm(tmp_path, db):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    source = projects(1)
    real = FakeLLM()
    real.respond("T-C1", lambda r: item_json())
    app = build_app(url, project_inputs=source, llm=real)
    assert isinstance(app.store, SqlStore) and isinstance(app.settings, DbSettingsProvider)
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source)
    [req] = start(web, source)                                                    # 웹: 요청만 넣는다
    w = worker(app)
    w.run_once("w")
    rid = web.orchestrator.start_status(201).run_id
    assert rid and web.orchestrator.view(rid).step == "공고선택"
    web.orchestrator.select_announcement(rid, "A01")
    assert web.engine.advance(rid) == "실행" and len(web.store.executions(rid)) == 2   # 웹은 단계를 돌지 않는다
    w.run_once("w")
    assert web.orchestrator.view(rid).step == "계획서작성"
    assert {q.metadata["task_id"] for q in real.requests} == {"T-C1"}              # 실제 호출처는 T-C1만
    assert "T-C1" not in {q.metadata["task_id"] for q in app.llm.requests}


def test_build_web_refuses_pre_stage_and_leaves_request(tmp_path, db):
    """웹 조립의 run_start_request는 시작 요청을 점유 · 변경하지 않고 바로 WEB_NOT_ALLOWED (spec 3.4)."""
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    source = projects(1)
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source)
    [req] = start(web, source)
    before = web.store.get_start_request(req)
    for call in (lambda: web.orchestrator.run_start_request(req, owner="web"),
                 lambda: web.orchestrator.start_run_for_project("9000", 201)):   # 동기 경로도 사전 단계를 돈다
        with pytest.raises(CommandError) as e:
            call()
        assert e.value.code == "WEB_NOT_ALLOWED"
    after = web.store.get_start_request(req)
    assert after == before and (after.status, after.claim_count, after.lease_owner) == ("대기", 0, None)
    assert web.store.latest_start_request(201).request_id == req                 # 새 요청도 넣지 않았다
    worker(app_on(db, source)).run_once("w")                                      # 워커는 그대로 처리한다
    assert web.orchestrator.start_status(201).status == "완료"
    assert build_stub_app().orchestrator.start_run("acc-x", pre_input()).ok        # 스텁 조립은 지금처럼


def test_build_web_needs_db_url(monkeypatch, tmp_path):
    monkeypatch.delenv("SBRAIN_DB_URL", raising=False)
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", tmp_path / "없음.env")
    with pytest.raises(RuntimeError, match="SBRAIN_DB_URL"):
        build_web(profile_count=lambda a: 1)


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


def test_pyproject_matches_requirements():
    """웹 프로세스가 설치하는 패키지 의존성 = requirements.txt (pytest는 test 선택 의존성)."""
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = [ln.strip() for ln in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]
    assert sorted(project["dependencies"] + project["optional-dependencies"]["test"]) == sorted(pins)
