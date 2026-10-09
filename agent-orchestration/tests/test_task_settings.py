"""Task별 모델 설정 (Settings.tasks) — spec 2 · 12-3 'Task별 설정'.

- 키 집합 = 카탈로그의 task 단계 + '지시문 다시 쓰기'. 규칙 단계 · 합치기에는 항목이 없다.
- Task마다 자기 항목의 모델이 실행 기록에 남고, 온도 덮어쓰기(TempRule)는 그대로 위에 씌운다.
- 다시 쓰기는 '지시문 다시 쓰기' 항목의 모델 · 제한 시간을 쓴다(T-C3 값을 빌리지 않는다). Agent 이름은 조율이다.
- M-4 model_version은 T-P2 항목 값이다.
- 설정 사본은 실행 시작 때 고정된다 — 시작 뒤 설정을 바꿔도 그 실행 건은 시작 때 값으로 돈다.
- 워커 호출처 나누기: 다시 쓰기는 실제, 스텁 Task(호출처가 openai로 바뀐 T-B1 · T-B2 · T-V2 포함)는 가짜.
흐름 테스트는 clock · store_backend 장치로 메모리 · SQLite 두 저장소에서 돈다.
"""
from __future__ import annotations

import json

import pytest

from conftest import make_app, pre_input, to_screen6, to_screen9
from flow_helpers import run_review
from worker_helpers import by_purpose, real_worker_app, worker, worker_to_screen6

from sbrain.agents.stubs import StubScenario
from sbrain.agents.supervisor.plan import PURPOSE_REWRITE
from sbrain.agents.supervisor.rewrite import rewrite_guidance
from sbrain.flow.catalog import build_registry
from sbrain.models.clock import utc_now
from sbrain.orchestrator import Settings
from sbrain.orchestrator.settings import PROVISIONAL, SettingsProvider, TaskModelSetting
from sbrain.orchestrator.errors import ToolCallExhausted
from sbrain.orchestrator.tools import NO_LLM_SETTING, CallSink, Tools, ToolsConfig, ToolsContext

REWRITE_KEY = "지시문 다시 쓰기"
INSTRUCTED = ("T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "T-B1", "T-B2")


# ── 도움 ─────────────────────────────────────────────
def reply(request) -> str:
    if request.metadata["purpose"] == PURPOSE_REWRITE:
        return json.dumps({"guidance": f"새 안내 {request.metadata['task_id']}"}, ensure_ascii=False)
    return '{"ok": true}'


def with_rewriter(app):
    app.engine.flow.rewriter = rewrite_guidance
    for task_id in INSTRUCTED:
        app.llm.respond(task_id, reply)
    return app


def records(app, rid) -> dict:
    return {r.task_id: r for r in app.store.executions(rid)}


def rewrite_logs(app, rid) -> list:
    return [c for c in app.store.call_logs(rid) if c.purpose == PURPOSE_REWRITE]


def task_ids() -> set[str]:
    """LLM을 부르는 Task — Task 설정 표에 항목이 있는 단계."""
    return {s.task_id for s in build_registry().specs() if s.kind == "task" and s.uses_llm}


NO_LLM_TASKS = {"T-C2", "G-01", "T-C4"}   # LLM을 부르지 않는 Task — 모델 항목이 없다 (사용자 결정 2026-10-08)


# ── 모양 · 기본값 ──────────────────────────────────────
def test_task_keys_match_catalog_task_steps():
    s = Settings()
    assert set(s.tasks) == task_ids() | {REWRITE_KEY}
    assert {sp.task_id for sp in build_registry().specs() if sp.kind == "task" and not sp.uses_llm} == NO_LLM_TASKS
    assert not NO_LLM_TASKS & set(s.tasks)                     # LLM을 부르지 않는 Task에는 항목이 없다
    rule_steps = {sp.task_id for sp in build_registry().specs() if sp.kind != "task"}
    assert rule_steps and not rule_steps & set(s.tasks)        # 규칙 단계 · 합치기에는 항목이 없다
    assert all(isinstance(v, TaskModelSetting) for v in s.tasks.values())
    assert len({id(v) for v in s.tasks.values()}) == len(s.tasks)   # 항목마다 따로 만든다 (한 항목을 바꿔도 다른 항목은 그대로)


def test_default_values():
    t = Settings().tasks
    row = lambda k: (t[k].provider, t[k].model, t[k].temperature, t[k].reasoning_effort)  # noqa: E731
    for k in ("T-C1", "T-C3", REWRITE_KEY):
        assert row(k) == ("openai", "gpt-6-luna", None, "low"), k
    for k in ("T-S1", "T-S2", "T-W1", "T-W2", "T-W3"):
        assert row(k) == ("미정", "미정", 0.7, None), k
    assert row("T-V1") == ("미정", "미정", 0.0, None)
    for k in ("T-B1", "T-B2", "T-V2"):
        assert row(k) == ("openai", "gpt-6-luna", None, None), k
    for k in ("T-P1", "T-P2"):
        assert row(k) == ("gpu-server", "미정", 0.2, None), k
    b2 = t["T-B2"]
    assert (b2.image_provider, b2.image_model, b2.image_quality, b2.image_size) == (
        "openai", "gpt-image-2.5-flare", "medium", "1024x1536")
    others = [v for k, v in t.items() if k != "T-B2"]
    assert all(v.image_provider is v.image_model is v.image_quality is v.image_size is None for v in others)


def test_timeouts_and_provisional():
    s = Settings()
    assert s.task_timeouts[REWRITE_KEY] == 120.0 and s.task_timeouts["T-B2.image"] == 120.0
    assert "tasks" in PROVISIONAL and "agents" not in PROVISIONAL
    assert f"taskTimeouts.{REWRITE_KEY}" in PROVISIONAL and "taskTimeouts.T-B2.image" in PROVISIONAL


def test_new_snapshot_has_tasks_and_no_agents():
    snap = SettingsProvider().snapshot()
    assert "tasks" in snap and "agents" not in snap
    assert snap["tasks"]["T-B2"]["imageModel"] == "gpt-image-2.5-flare"
    back = Settings.model_validate(snap)
    assert back.agents is None and back.tasks["T-S1"].model == "미정"


# ── 설정 사본: 실행 시작 때 고정 ───────────────────────────
def test_settings_snapshot_fixed_at_start(clock):
    app = make_app(clock)
    res = app.orchestrator.start_run("acc-1", pre_input())
    s = app.settings.current().model_copy(deep=True)
    s.scoring.threshold = 50
    s.tasks["T-S1"].model = "바뀐 모델"
    app.settings.update(s)
    app.orchestrator.select_announcement(res.run_id, "A01")
    app.orchestrator.advance(res.run_id)
    app.orchestrator.start_writing(res.run_id)
    app.orchestrator.advance(res.run_id)
    recs = {r.task_id: r for r in app.store.executions(res.run_id)}
    assert recs["T-S1"].model == "미정"  # 실행 시작 시점 값
    ctx = app.engine.open_context(app.store.load_run(res.run_id))
    assert ctx.get("scoreReport.document").threshold == 80
    assert ctx.get("scoreReport.document").settings_snapshot["scoring"]["threshold"] == 80


# ── 흐름: 실행 기록 · 온도 규칙 · M-4 ─────────────────────
def test_each_task_records_its_own_entry(clock):
    s = Settings()
    for key, v in s.tasks.items():
        v.model = f"m-{key}"
        v.provider = "미정"
    s.tasks["T-V1"].temperature = 0.7          # TempRule fixed 0 → 0.0
    s.tasks["T-P2"].temperature = 0.9          # TempRule max 0.2 → 0.2
    s.tasks["T-S2"].reasoning_effort = "high"
    app = make_app(clock, StubScenario(tp1_targets=2), settings=s)
    rid = to_screen9(app)
    run_review(app, rid)
    recs = records(app, rid)
    for tid in task_ids():
        assert recs[tid].model == f"m-{tid}", tid
        assert recs[tid].provider == "미정", tid
    assert recs["T-V1"].temperature == 0.0
    assert recs["T-P2"].temperature == 0.2
    assert recs["T-S2"].reasoning_effort == "high" and recs["T-S1"].reasoning_effort is None
    assert recs["T-S1"].agent == "전략" and recs["T-B2"].agent == "구현"     # Agent는 Task의 담당 Agent 그대로
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.get("proofreadLog").model_version == "m-T-P2"                 # M-4는 T-P2 항목 값
    for tid in NO_LLM_TASKS:                   # LLM을 부르지 않는 Task는 모델 · 호출처 · 온도가 빈다
        assert (recs[tid].model, recs[tid].provider, recs[tid].temperature) == (None, None, None), tid


def test_no_llm_task_ignores_old_snapshot_entry_and_keeps_timeout(clock):
    """옛 설정 사본에 T-C2 · G-01 · T-C4 항목이 있어도 쓰지 않는다. 제한 시간 · 재시도는 그대로 입힌다."""
    s = Settings()
    for k in NO_LLM_TASKS:
        s.tasks[k] = TaskModelSetting(provider="openai", model="gpt-6-luna", temperature=None)
    s.task_timeouts["G-01"] = 12.5
    app = make_app(clock, StubScenario(tp1_targets=2), settings=s)
    rid = to_screen9(app)
    run_review(app, rid)
    recs = records(app, rid)
    for tid in NO_LLM_TASKS:
        assert (recs[tid].model, recs[tid].provider) == (None, None), tid
    spec = next(sp for sp in build_registry().specs() if sp.task_id == "G-01")
    cfg = app.engine.tools_config(app.engine.open_context(app.store.load_run(rid)), spec)
    assert (cfg.model, cfg.provider, cfg.timeout_sec, cfg.retry_count) == (None, None, 12.5, s.retry.retry_count)


def test_llm_call_without_model_fails_at_once():
    """모델이 없는 호출 설정으로 llm을 부르면 호출처에 보내지 않고 바로 실패한다(재시도하지 않음)."""
    cfg = ToolsConfig(agent="조율", provider=None, model=None, temperature=None, timeout_sec=1.0,
                      retry_count=3, retry_interval_sec=0.0)
    sink, sleeps = CallSink(), []
    tools = Tools(cfg, ToolsContext(run_id="r", execution_id="e", task_id="G-01", providers={}, sink=sink,
                                    now=utc_now, sleep=sleeps.append))
    with pytest.raises(ToolCallExhausted) as e:
        tools.llm([{"role": "user", "content": "x"}], purpose="시험")
    assert (e.value.error, e.value.error_kind, e.value.detail) == ("호출실패", "운영", NO_LLM_SETTING)
    assert sleeps == []                                                   # 재시도하지 않는다
    [log] = sink.drain()
    assert (log.call_type, log.final_outcome, log.model, log.provider, len(log.tries)) == ("llm", "소진", None, None, 1)


def test_rewrite_uses_its_own_entry(clock):
    s = Settings()
    s.tasks[REWRITE_KEY].model = "다시쓰기-모델"
    s.tasks[REWRITE_KEY].reasoning_effort = "medium"
    s.tasks["T-C3"].model = "작업분해-모델"
    s.task_timeouts[REWRITE_KEY] = 77.0
    app = with_rewriter(make_app(clock, StubScenario(check_fail_times={"T-W1": 1}), settings=s))
    rid = to_screen6(app)
    [rw] = rewrite_logs(app, rid)
    assert (rw.task_id, rw.agent, rw.provider, rw.model, rw.reasoning_effort, rw.temperature, rw.timeout_sec) == (
        "T-W1", "조율", "openai", "다시쓰기-모델", "medium", None, 77.0)
    assert records(app, rid)["T-C3"].model == "작업분해-모델"


# ── 워커 호출처 나누기 ────────────────────────────────
def test_worker_routes_rewrite_real_and_stub_tasks_fake(tmp_path, db):
    app, web, real, source = real_worker_app(tmp_path)
    app.scenario.check_fail_times["T-S1"] = 1
    rid = worker_to_screen6(app, web, source)
    web.orchestrator.decide(rid, 6, "진행")
    worker(app, lease_sec=60).run_once("w")
    assert web.store.load_run(rid).state.step != "문서평가"
    [rw] = by_purpose(real, PURPOSE_REWRITE)
    assert (rw.metadata["task_id"], rw.metadata["agent"]) == ("T-S1", "조율")
    real_tasks = {q.metadata["task_id"] for q in real.requests if q.metadata["purpose"] != PURPOSE_REWRITE}
    assert real_tasks == {"T-C1", "T-C3"}
    fake_tasks = {q.metadata["task_id"] for q in app.llm.requests}
    assert {"T-B1", "T-B2", "T-V2"} <= fake_tasks                           # 호출처가 openai여도 스텁이면 가짜로
    recs = records(web, rid)
    assert {recs[t].provider for t in ("T-B1", "T-B2", "T-V2")} == {"openai"}
