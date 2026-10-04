"""워커 — 가져가기 · 점유 · 하트비트 · 종료 신호, 웹 프로세스와 워커가 같은 DB를 쓰는 조립.

여러 워커는 같은 DB 파일을 쓰는 앱(프로세스 하나에 해당) 여러 개로 흉내 낸다.
"""
from __future__ import annotations

import json
import signal
import threading
import time
from datetime import datetime

import pytest
from conftest import Clock, isolate_notice_api, pre_input, project_record
from mysqldb import require_mysql
from test_notice_tasks import FAKE_URL, FakeNoticeServer, result
from test_tc1 import item_json
from webdb import create_web_tables, new_project

from sbrain import env
from sbrain.agents.stubs import FakeLLM, StubScenario
from sbrain.agents.supervisor import IMPLEMENTED, IMPLEMENTED_TASKS, tc3
from sbrain.agents.supervisor.plan import PURPOSE_REWRITE, PURPOSE_WRITE
from sbrain.agents.supervisor.rewrite import rewrite_guidance
from sbrain.bootstrap import App, TaskRoutedProvider, build_app, build_stub_app, build_web
from sbrain.intake import MemoryProjectInputSource
from sbrain.orchestrator.errors import CommandError
from sbrain.orchestrator.tools import LLMRequest
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


# ── 워커 조립: 실제 T-C3 · 다시 쓰기는 실제 호출처, 스텁 Task는 가짜 (T-C3 spec 6.1) ──
REWRITE_TARGETS = ("T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "T-B1", "T-B2")


def _guidance_reply(request: LLMRequest) -> str:
    """실제 T-C3(항목 키 = 지시 대상)와 다시 쓰기(task_id = 대상) 호출 모두 안내 하나로 답한다."""
    target = request.metadata.get("item_key") or request.metadata["task_id"]
    return json.dumps({"guidance": f"{target} 안내 — {request.metadata['purpose']}"}, ensure_ascii=False)


def real_worker_app(tmp_path, clock=datetime.now) -> tuple[App, App, FakeLLM, MemoryProjectInputSource]:
    """워커 조립(build_app) + 웹 조립. 실제 호출처는 가짜 LLM — T-C1 · T-C3 · 다시 쓰기 호출에 답한다 (네트워크 없음)."""
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    source = projects(1)
    real = FakeLLM()
    real.respond("T-C1", lambda r: item_json())
    real.respond("T-C3", _guidance_reply)
    for task_id in REWRITE_TARGETS:                                              # 다시 쓰기 호출의 task_id는 대상 Task
        real.respond(task_id, _guidance_reply)
    app = build_app(url, project_inputs=source, llm=real, now=clock)
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source, now=clock)
    return app, web, real, source


def worker_to_screen6(app: App, web: App, source: MemoryProjectInputSource) -> str:
    start(web, source)
    w = worker(app, lease_sec=60)
    w.run_once("w")
    rid = web.orchestrator.start_status(201).run_id
    web.orchestrator.select_announcement(rid, "A01")
    w.run_once("w")
    web.orchestrator.start_writing(rid)
    w.run_once("w")
    run = web.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("문서평가", "사용자대기")
    return rid


def by_purpose(llm: FakeLLM, purpose: str) -> list[LLMRequest]:
    return [q for q in llm.requests if q.metadata["purpose"] == purpose]


def test_build_app_routes_real_tc3_to_real_llm(tmp_path, db):
    """T-C3까지 진행 — 실제 T-C3 호출(지시 대상 7개)은 실제 호출처, 스텁 Task 호출은 가짜 호출처. 첫 실행은 다시 쓰지 않는다."""
    app, web, real, source = real_worker_app(tmp_path)
    assert app.registry.get("T-C3").fn is tc3.run
    rid = worker_to_screen6(app, web, source)
    tc3_calls = [q for q in real.requests if q.metadata["task_id"] == "T-C3"]
    assert len(tc3_calls) == 7 and {q.metadata["purpose"] for q in tc3_calls} == {PURPOSE_WRITE}
    assert {q.metadata["task_id"] for q in real.requests} == {"T-C1", "T-C3"}
    fake_tasks = {q.metadata["task_id"] for q in app.llm.requests}
    assert not fake_tasks & {"T-C1", "T-C3"}
    assert {"T-S1", "T-S2", "T-W1", "T-W2", "T-W3"} <= fake_tasks                # 스텁 Task는 가짜로
    assert by_purpose(real, PURPOSE_REWRITE) == by_purpose(app.llm, PURPOSE_REWRITE) == []
    assert "T-C3" in [e.task_id for e in web.store.executions(rid)]


def test_build_app_routes_redo_rewrite_to_real_llm(tmp_path, db):
    """재수행 — 다시 쓰기 호출(task_id = 대상 T-S1)은 실제 호출처, 대상 스텁 T-S1의 호출은 가짜 호출처."""
    app, web, real, source = real_worker_app(tmp_path)
    app.scenario.check_fail_times["T-S1"] = 1                                     # 첫 실행 불통과 → 재수행 한 번
    rid = worker_to_screen6(app, web, source)
    [rw] = by_purpose(real, PURPOSE_REWRITE)
    assert (rw.metadata["task_id"], rw.metadata["agent"]) == ("T-S1", "조율")
    assert by_purpose(app.llm, PURPOSE_REWRITE) == []
    assert [q.metadata["task_id"] for q in app.llm.requests].count("T-S1") == 2   # 첫 실행 + 재수행
    assert "T-S1" not in {q.metadata["task_id"] for q in real.requests if q.metadata["purpose"] != PURPOSE_REWRITE}
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert "T-S1 안내" in ctx.get("T-S1.instruction")                              # 실제 호출처의 안내로 다시 썼다


def test_build_app_routes_rework_rewrite_to_real_llm(tmp_path, db):
    """재작성(문서층) — T-W1 · T-W2 · T-W3 다시 쓰기는 실제 호출처, 대상 스텁 Task의 호출은 가짜 호출처."""
    clock = Clock()
    app, web, real, source = real_worker_app(tmp_path, clock)
    rid = worker_to_screen6(app, web, source)
    before = {t: [q.metadata["task_id"] for q in app.llm.requests].count(t) for t in ("T-W1", "T-W2", "T-W3")}
    pid = web.store.load_run(rid).project_id
    acc = web.orchestrator.request_rework_for_project(pid, "문제인식")
    clock.t = acc.collect_until
    assert worker(app, lease_sec=60).run_once("w") == [f"진행 {rid} 사용자대기"]
    rws = by_purpose(real, PURPOSE_REWRITE)
    assert [q.metadata["task_id"] for q in rws] == ["T-W1", "T-W2", "T-W3"]
    assert {q.metadata["agent"] for q in rws} == {"조율"}
    assert by_purpose(app.llm, PURPOSE_REWRITE) == []
    after = {t: [q.metadata["task_id"] for q in app.llm.requests].count(t) for t in ("T-W1", "T-W2", "T-W3")}
    assert all(after[t] > before[t] for t in after)                               # 재작성 실행은 가짜로
    assert not {q.metadata["task_id"] for q in real.requests} & {"T-V1", "M-1", "G-02a"}


def test_task_routed_provider_rule():
    """실제 호출처로 가는 것: 구현 Task의 호출, 또는 조율의 '지시문 다시 쓰기' 호출(대상 Task와 관계없이)."""
    real, fake = FakeLLM(), FakeLLM()
    router = TaskRoutedProvider(real, fake, IMPLEMENTED_TASKS)

    def req(task_id: str, agent: str, purpose: str | None) -> LLMRequest:
        return LLMRequest(provider="openai", model="m", temperature=None, messages=[], timeout_sec=1,
                          response_schema=None, metadata={"run_id": "r", "task_id": task_id, "agent": agent,
                                                          "purpose": purpose, "item_key": None})
    cases = [("T-C1", "조율", None, real), ("T-C3", "조율", PURPOSE_WRITE, real),
             ("T-W1", "조율", PURPOSE_REWRITE, real), ("T-B2", "조율", PURPOSE_REWRITE, real),
             ("T-W1", "작성", None, fake), ("T-W1", "조율", PURPOSE_WRITE, fake),
             ("T-W1", "작성", PURPOSE_REWRITE, fake), ("T-S1", "설계", None, fake)]
    for task_id, agent, purpose, target in cases:
        before = len(target.requests)
        router.complete(req(task_id, agent, purpose))
        assert len(target.requests) == before + 1, (task_id, agent, purpose)
    assert len(real.requests) == 4 and len(fake.requests) == 4


def test_only_worker_assembly_has_rewriter(tmp_path, db):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    assert "T-C3" in IMPLEMENTED_TASKS and IMPLEMENTED["T-C3"] is tc3.run
    assert build_app(url, project_inputs=projects(1), llm=FakeLLM()).engine.flow.rewriter is rewrite_guidance
    assert build_stub_app().engine.flow.rewriter is None
    assert build_web(url, profile_count=lambda a: 1, project_inputs=projects(1)).engine.flow.rewriter is None


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


STUB_MODULE = "sbrain.agents.stubs"


def notice_fns(app: App) -> tuple[str, str]:
    return tuple(app.registry.get(t).fn.__module__ for t in ("T-C2", "G-01"))


def test_build_app_without_notice_url_binds_stub_notice_tasks(tmp_path, db):
    """공고 서버 주소가 없으면 스텁 T-C2 · G-01 (spec 3.1)."""
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    app = build_app(url, project_inputs=projects(1), llm=FakeLLM())
    assert notice_fns(app) == (STUB_MODULE, STUB_MODULE)


def test_build_app_with_notice_url_binds_real_notice_tasks(tmp_path, db):
    """주소가 있으면 실제 T-C2 · G-01 — 가짜 전송으로 워커 한 바퀴를 돈다(네트워크 없음). 웹 조립은 공고 서버를 부르지 않는다."""
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    source = projects(1)
    real = FakeLLM()
    real.respond("T-C1", lambda r: item_json())
    server = FakeNoticeServer()
    app = build_app(url, project_inputs=source, llm=real, notice_api_url=FAKE_URL, notice_transport=server)
    assert notice_fns(app) == ("sbrain.agents.notice.tc2", "sbrain.agents.notice.g01")
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source)
    [req] = start(web, source)
    w = worker(app)
    w.run_once("w")
    rid = web.orchestrator.start_status(201).run_id
    assert rid and web.orchestrator.view(rid).step == "공고선택"
    assert [c.announcement_id for c in web.orchestrator.screen(201, 3).candidates] == [
        "kstartup:A01", "bizinfo:B02", "kstartup:A03"]
    web.orchestrator.select_announcement(rid, "bizinfo:B02")
    assert server.paths() == [("GET", "/api/collection_status"), ("POST", "/api/match")]   # 웹은 부르지 않는다
    w.run_once("w")
    run = web.store.load_run(rid)
    assert (run.state.step, run.announcement_id) == ("계획서작성", "bizinfo:B02")
    assert server.paths()[2:] == [("GET", "/api/notices/bizinfo%3AB02"),
                                  ("POST", "/api/notices/bizinfo%3AB02/eligibility")]
    body = server.calls[1][2]
    assert (body["region"], body["district"]) == ("서울", "마포구")                      # 웹 값 서울특별시 마포구
    assert "birth" not in json.dumps(body) and "1990" not in json.dumps(body)
    assert all(u.startswith(FAKE_URL + "/api/") for u in server.urls)


def test_real_notice_tasks_with_more_lookup_block_and_gone(tmp_path, db):
    """실제 T-C2 · G-01이 흐름 규칙(추가 조회 겹침 · 내용 바뀜 · 막힌 공고 · 공고 없음)과 함께 도는지 — 가짜 전송, 네트워크 없음."""
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    source = projects(1)
    real = FakeLLM()
    real.respond("T-C1", lambda r: item_json())
    server = FakeNoticeServer()
    app = build_app(url, project_inputs=source, llm=real, notice_api_url=FAKE_URL, notice_transport=server)
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source)
    start(web, source)
    w = worker(app)
    w.run_once("w")
    rid = web.orchestrator.start_status(201).run_id
    # 불통과 → 막힘 (spec 4.3.6)
    server.gates["kstartup:A03"] = {"passed": False, "failed_conditions": ["업력"], "unknown_conditions": [],
                                    "business_age_months": 90}
    web.orchestrator.select_announcement(rid, "kstartup:A03")
    w.run_once("w")
    run = web.store.load_run(rid)
    assert (run.state.step, run.notices[-1].code, run.blocked_announcement_ids) == (
        "공고선택", "E-G1-REJECT", ["kstartup:A03"])
    # 추가 조회: A03이 내용(내용 버전)이 바뀌어 겹쳐 나오고, C04가 새로 나온다 (spec 4.2.2)
    server.match = {"results": [result("kstartup:A03", 1, content_version="v-new", fit_score=0.5),
                                result("bizinfo:C04", 2)],
                    "filtered_count": 40, "fallback_used": False, "fallback_mode": None}
    web.orchestrator.more_candidates(rid)
    w.run_once("w")
    screen = web.orchestrator.screen(201, 3)
    a03 = next(c for c in screen.candidates if c.announcement_id == "kstartup:A03")
    assert [c.announcement_id for c in screen.candidates] == ["kstartup:A01", "bizinfo:B02", "kstartup:A03"]
    assert (a03.rank, a03.content_changed, a03.fit_score, a03.content_version) == (3, True, 0.5, "v-new")
    assert [c.announcement_id for c in screen.more_candidates] == ["bizinfo:C04"]
    assert screen.blocked_announcement_ids == []                                   # 내용이 바뀌어 풀렸다
    assert server.calls[-1][2]["offset"] == 10
    # 공고 없음 → X-C2-GONE, 고르기 전 대기 지점 · 선택 공고 그대로 (spec 4.3.4)
    server.not_found.add("bizinfo:C04")
    web.orchestrator.select_announcement(rid, "bizinfo:C04")
    w.run_once("w")
    run = web.store.load_run(rid)
    assert (run.state.step, run.notices[-1].code, run.announcement_id) == ("공고선택", "X-C2-GONE", "kstartup:A03")
    assert run.blocked_announcement_ids == []                                      # 공고 없음은 막지 않는다
    server.not_found.clear()                                                       # 다시 생기면 정상으로 진행
    web.orchestrator.select_announcement(rid, "bizinfo:C04")
    w.run_once("w")
    run = web.store.load_run(rid)
    assert (run.state.step, run.announcement_id) == ("계획서작성", "bizinfo:C04")


def test_build_app_reads_notice_url_with_get_env(tmp_path, db, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    monkeypatch.setenv("SBRAIN_NOTICE_API_URL", FAKE_URL)
    server = FakeNoticeServer()
    app = build_app(url, project_inputs=projects(1), llm=FakeLLM(), notice_transport=server)
    assert notice_fns(app) == ("sbrain.agents.notice.tc2", "sbrain.agents.notice.g01")
    off = build_app(url, project_inputs=projects(1), llm=FakeLLM(), notice_api_url="")   # 빈 값 = 끔
    assert notice_fns(off) == (STUB_MODULE, STUB_MODULE)
    web = build_web(url, profile_count=lambda a: 1, project_inputs=projects(1))   # 웹 조립은 그대로
    assert web.registry.get("T-C2").fn is None and web.registry.get("G-01").fn is None
    assert notice_fns(build_stub_app()) == (STUB_MODULE, STUB_MODULE)             # 테스트 · 시연 조립은 스텁
    assert server.calls == []


def test_bad_notice_url_fails_assembly_without_echo(tmp_path, db):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    with pytest.raises(ValueError) as e:
        build_app(url, project_inputs=projects(1), llm=FakeLLM(), notice_api_url="example.invalid:8000")
    assert "example.invalid" not in str(e.value)


def test_tests_never_see_notice_url_from_environment_or_env_file(monkeypatch, tmp_path):
    """개발 PC의 환경 변수나 agent-orchestration/.env에 SBRAIN_NOTICE_API_URL이 있어도 테스트는 실제 공고 서버를 부르지 않는다.

    conftest의 자동 장치(isolate_notice_api)가 이 키만 없는 것으로 본다. 다른 키는 그대로 읽는다.
    """
    db_url = f"sqlite:///{(tmp_path / 'from-file.db').as_posix()}"
    engine = create_sqlite_engine(tmp_path / "from-file.db", fast=True)
    create_orchestrator_tables(engine)
    create_web_tables(engine)
    env_file = tmp_path / ".env"
    env_file.write_text(f"SBRAIN_NOTICE_API_URL={FAKE_URL}\nSBRAIN_DB_URL={db_url}\n"
                        "SBRAIN_ENV_TEST_KEY=파일\n", encoding="utf-8")
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", env_file)
    for key in ("SBRAIN_DB_URL", "SBRAIN_ENV_TEST_KEY"):                          # 이 시험의 .env 값만 보이게
        monkeypatch.delenv(key, raising=False)
    assert env.get_env("SBRAIN_NOTICE_API_URL") is None                          # 자동 장치가 이미 켜져 있다
    monkeypatch.setenv("SBRAIN_NOTICE_API_URL", FAKE_URL)                         # 개발 PC 환경 변수
    isolate_notice_api(monkeypatch)                                               # 테스트 시작 때 자동 장치가 하는 일
    assert env.get_env("SBRAIN_NOTICE_API_URL") is None
    assert env.get_env("SBRAIN_DB_URL") == db_url and env.get_env("SBRAIN_ENV_TEST_KEY") == "파일"
    assert env.read_env_file(env_file) == {"SBRAIN_DB_URL": db_url, "SBRAIN_ENV_TEST_KEY": "파일"}
    app = build_app(project_inputs=projects(1), llm=FakeLLM())                    # DB 주소는 .env에서 읽는다
    assert notice_fns(app) == (STUB_MODULE, STUB_MODULE)


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
