"""Task별 모델 설정 (Settings.tasks) — spec 2 · 12-3 'Task별 설정'.

- 키 집합 = 카탈로그의 task 단계 + '지시문 다시 쓰기'. 규칙 단계 · 합치기에는 항목이 없다.
- Task마다 자기 항목의 모델이 실행 기록에 남고, 온도 덮어쓰기(TempRule)는 그대로 위에 씌운다.
- 다시 쓰기는 '지시문 다시 쓰기' 항목의 모델 · 제한 시간을 쓴다(T-C3 값을 빌리지 않는다). Agent 이름은 조율이다.
- M-4 model_version은 T-P2 항목 값이다.
- 옛 설정 사본(tasks 없이 agents만)인 실행 건은 사본의 Agent 값 그대로 이어서 돈다(재개 포함).
- 워커 호출처 나누기: 다시 쓰기는 실제, 스텁 Task(호출처가 openai로 바뀐 T-B1 · T-B2 · T-V2 포함)는 가짜.
흐름 테스트는 clock · store_backend 장치로 메모리 · SQLite 두 저장소에서 돈다.
"""
from __future__ import annotations

import json

from conftest import make_app, to_screen6, to_screen9
from test_worker import by_purpose, db, real_worker_app, worker, worker_to_screen6  # noqa: F401 — db는 장치

from sbrain.agents.stubs import StubScenario
from sbrain.agents.supervisor.plan import PURPOSE_REWRITE
from sbrain.agents.supervisor.rewrite import rewrite_guidance
from sbrain.flow.catalog import build_registry
from sbrain.orchestrator import Settings
from sbrain.orchestrator.settings import PROVISIONAL, SettingsProvider, TaskModelSetting

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


def run_review(app, rid):
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)


def records(app, rid) -> dict:
    return {r.task_id: r for r in app.store.executions(rid)}


def rewrite_logs(app, rid) -> list:
    return [c for c in app.store.call_logs(rid) if c.purpose == PURPOSE_REWRITE]


def task_ids() -> set[str]:
    return {s.task_id for s in build_registry().specs() if s.kind == "task"}


# ── 모양 · 기본값 ──────────────────────────────────────
def test_task_keys_match_catalog_task_steps():
    s = Settings()
    assert set(s.tasks) == task_ids() | {REWRITE_KEY}
    rule_steps = {sp.task_id for sp in build_registry().specs() if sp.kind != "task"}
    assert rule_steps and not rule_steps & set(s.tasks)        # 규칙 단계 · 합치기에는 항목이 없다
    assert all(isinstance(v, TaskModelSetting) for v in s.tasks.values())
    assert len({id(v) for v in s.tasks.values()}) == len(s.tasks)   # 항목마다 따로 만든다 (한 항목을 바꿔도 다른 항목은 그대로)


def test_default_values():
    t = Settings().tasks
    row = lambda k: (t[k].provider, t[k].model, t[k].temperature, t[k].reasoning_effort)  # noqa: E731
    for k in ("T-C1", "T-C2", "G-01", "T-C3", "T-C4", REWRITE_KEY):
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


def legacy_snapshot(**agent_models: str) -> dict:
    """옛 설정 사본 — tasks 없이 Agent 7개(agents), 제한 시간에 새 키 없음, T-C3 제한 시간은 다른 값."""
    snap = Settings().dump()
    del snap["tasks"]
    for k in (REWRITE_KEY, "T-B2.image"):
        del snap["taskTimeouts"][k]
    snap["taskTimeouts"]["T-C3"] = 45.0
    agents = {
        "조율": {"provider": "openai", "model": "gpt-6-luna", "temperature": None, "reasoningEffort": "low"},
        "전략": {"provider": "미정", "model": "미정", "temperature": 0.7, "reasoningEffort": None},
        "작성": {"provider": "미정", "model": "미정", "temperature": 0.7, "reasoningEffort": None},
        "구현": {"provider": "미정", "model": "미정", "temperature": 0.7, "reasoningEffort": None},
        "검증-1": {"provider": "미정", "model": "미정", "temperature": 0.0, "reasoningEffort": None},
        "검증-2": {"provider": "미정", "model": "미정", "temperature": 0.0, "reasoningEffort": None},
        "검수": {"provider": "gpu-server", "model": "미정", "temperature": 0.2, "reasoningEffort": None},
    }
    for agent, model in agent_models.items():
        agents[agent]["model"] = model
    snap["agents"] = agents
    return snap


def test_legacy_snapshot_reads_without_filling_tasks():
    s = Settings.model_validate(legacy_snapshot(전략="옛 전략"))
    assert s.tasks is None and s.agents["전략"].model == "옛 전략"
    dumped = s.dump()
    assert "tasks" not in dumped and dumped["agents"]["전략"]["model"] == "옛 전략"
    assert Settings.model_validate(dumped).tasks is None                   # 다시 읽어도 옛 사본 그대로


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


# ── 옛 실행 건 ────────────────────────────────────────
def test_legacy_snapshot_run_continues_with_agent_values(clock):
    app = with_rewriter(make_app(clock, StubScenario(check_fail_times={"T-S1": 1}, tp1_targets=2)))
    legacy = legacy_snapshot(조율="옛-조율", 전략="옛-전략", 구현="옛-구현", 검수="옛-검수")
    app.settings.snapshot = lambda: json.loads(json.dumps(legacy))
    app.llm.plan("T-S1", ["ok", "ok"] + ["timeout"] * 6)    # 첫 실행 · 다시 쓰기는 성공, 재수행 Task 호출이 재시도를 다 쓴다
    rid = to_screen6(app)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.current_task) == ("재개대기", "T-S1")
    assert "tasks" not in run.settings_snapshot and "agents" in run.settings_snapshot

    clock.advance(minutes=16)
    assert app.orchestrator.tick(clock.t) == [rid]
    assert app.store.load_run(rid).state.step == "문서평가"
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 8, "진행")
    run_review(app, rid)

    recs = records(app, rid)
    assert recs["T-S1"].model == "옛-전략" and recs["T-S1"].temperature == 0.7
    assert recs["T-C3"].model == "옛-조율" and recs["T-C3"].reasoning_effort == "low"
    assert (recs["T-B1"].provider, recs["T-B1"].model, recs["T-B1"].temperature) == ("미정", "옛-구현", 0.7)
    assert (recs["T-V2"].provider, recs["T-V2"].model, recs["T-V2"].temperature) == ("미정", "미정", 0.0)
    assert recs["T-P2"].model == "옛-검수"
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert ctx.get("proofreadLog").model_version == "옛-검수"
    rws = rewrite_logs(app, rid)
    assert rws and {(c.agent, c.model, c.timeout_sec) for c in rws} == {("조율", "옛-조율", 120.0)}
    snap = app.store.load_run(rid).settings_snapshot
    assert "tasks" not in snap and snap["agents"]["전략"]["model"] == "옛-전략"   # 사본을 새 기본값으로 바꾸지 않는다


# ── 워커 호출처 나누기 ────────────────────────────────
def test_worker_routes_rewrite_real_and_stub_tasks_fake(tmp_path, db):  # noqa: F811
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
