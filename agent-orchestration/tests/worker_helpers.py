"""워커 · 조립 도움 — 같은 DB 파일을 쓰는 워커 앱 · 웹 앱을 만들고 시작 요청을 넣는다. 네트워크에 나가지 않는다.

여러 워커는 같은 DB 파일을 쓰는 앱(프로세스 하나에 해당) 여러 개로 흉내 낸다.
실제 호출처는 가짜 LLM(FakeLLM)이고, 공고 서버 주소가 없으면 스텁 T-C2 · G-01이 붙는다.
"""
from __future__ import annotations

import json

from conftest import project_record
from fakes import item_json
from partner_fake import partner_reply
from webdb import new_project

from sbrain.agents.partner_sw.purposes import PURPOSES
from sbrain.agents.stubs import FakeLLM, StubScenario
from sbrain.bootstrap import App, build_app, build_stub_app, build_web
from sbrain.intake import MemoryProjectInputSource
from sbrain.models.clock import utc_now
from sbrain.orchestrator.tools import LLMRequest
from sbrain.store_sql import SqlStore
from sbrain.worker import Worker, WorkerConfig


# ── 워커 앱 · 시작 요청 ─────────────────────────────────
def projects(n: int, engine=None) -> MemoryProjectInputSource:
    """계정 n개에 프로젝트 하나씩 (MySQL은 웹 projects 행도 만든다)."""
    source = MemoryProjectInputSource()
    for i in range(n):
        pid = new_project(engine) if engine is not None and engine.dialect.name == "mysql" else 201 + i
        source.add(project_record(project={"project_id": pid}, company={"user_id": 9000 + i}))
    return source


def app_on(engine, source, now=utc_now, scenario: StubScenario | None = None) -> App:
    return build_stub_app(scenario, now=now, store=SqlStore(engine, now=now), project_inputs=source)


def worker(app: App, logs: list[str] | None = None, **cfg) -> Worker:
    return Worker(app, WorkerConfig(**cfg), log=(logs.append if logs is not None else lambda line: None),
                  name=f"w{id(app) % 1000}")


def start(app: App, source: MemoryProjectInputSource) -> list[str]:
    ids = []
    for pid, rec in source._records.items():
        check = app.orchestrator.request_start(str(rec.company.user_id), pid)
        assert check.ok, check
        ids.append(check.request_id)
    return ids


# ── 워커 조립 + 웹 조립: 실제 호출처는 가짜 LLM (T-C1 · T-C3 · 다시 쓰기에 답한다) ──
REWRITE_TARGETS = ("T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "T-B1", "T-B2")


def _guidance_reply(request: LLMRequest) -> str:
    """실제 T-C3(항목 키 = 지시 대상)와 다시 쓰기(task_id = 대상) 호출 모두 안내 하나로 답한다.
    전략 · 작성 · 검증-1 실구현(T4)의 담당자 함수 호출(목적 = F번호)에는 목적별 가짜 응답으로 답한다."""
    if request.metadata.get("purpose") in PURPOSES:
        return partner_reply(request)
    target = request.metadata.get("item_key") or request.metadata["task_id"]
    return json.dumps({"guidance": f"{target} 안내 — {request.metadata['purpose']}"}, ensure_ascii=False)


def real_worker_app(tmp_path, clock=utc_now) -> tuple[App, App, FakeLLM, MemoryProjectInputSource]:
    """워커 조립(build_app) + 웹 조립. 실제 호출처는 가짜 LLM — T-C1 · T-C3 · 다시 쓰기 호출과 전략 · 작성 · 검증-1
    실구현의 담당자 함수 호출에 답한다 (네트워크 없음)."""
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    source = projects(1)
    real = FakeLLM()
    real.respond("T-C1", lambda r: item_json())
    real.respond("T-C3", _guidance_reply)
    for task_id in (*REWRITE_TARGETS, "T-V1"):                                   # 다시 쓰기 호출의 task_id는 대상 Task
        real.respond(task_id, _guidance_reply)
    app = build_app(url, project_inputs=source, llm=real, now=clock)
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source, now=clock)
    return app, web, real, source


def empty_features_once(real: FakeLLM) -> None:
    """실제 T-S1의 첫 F02 응답만 기능 목록을 비운다 — 자체 검사 불통과(coreFeatures 승계) → 재수행 한 번 (spec 4.8)."""
    calls = {"F02": 0}

    def reply(request: LLMRequest) -> str:
        if request.metadata.get("purpose") == "F02":
            calls["F02"] += 1
            if calls["F02"] == 1:
                return partner_reply(request, {"F02": {"coreFeatures": [], "targetCustomer": "", "deliverables": [],
                                                       "differentiation": ""}})
        return _guidance_reply(request)
    real.respond("T-S1", reply)


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


# ── 공고 Task 묶임 ────────────────────────────────────
STUB_MODULE = "sbrain.agents.stubs"


def notice_fns(app: App) -> tuple[str, str]:
    return tuple(app.registry.get(t).fn.__module__ for t in ("T-C2", "G-01"))
