"""조립 (sbrain/bootstrap.py) — 워커 조립(build_app) · 웹 조립(build_web) · 시연 조립(build_stub_app).

- 실제 호출처로 가는 것: 구현 Task(T-C1 · T-C3)의 호출과 조율의 '지시문 다시 쓰기' 호출. 스텁 Task는 가짜 호출처로.
- 다시 쓰기 함수는 워커 조립에만 붙는다. 웹 조립은 사전 단계 · 공고 서버 · 이미지 호출을 하지 않는다.
- 공고 서버 주소(SBRAIN_NOTICE_API_URL)가 있으면 실제 T-C2 · G-01, 없거나 빈 값이면 스텁. 가짜 전송만 쓴다(네트워크 없음).
- 이미지 호출처: 구현 Task만 실제로, 키 없이 조립해도 실제 클라이언트를 만들지 않는다.
"""
from __future__ import annotations

import json

import openai
import pytest
from conftest import Clock, pre_input
from fakes import item_json
from notice_fake import FAKE_URL, FakeNoticeServer, result
from worker_helpers import (
    STUB_MODULE, app_on, by_purpose, empty_features_once, notice_fns, projects, real_worker_app, start, worker,
    worker_to_screen6,
)

from sbrain import env
from sbrain.agents.partner_sw.tasks import IMPLEMENTED as PARTNER_IMPLEMENTED
from sbrain.agents.partner_sw.tasks import IMPLEMENTED_TASKS as PARTNER_TASKS
from sbrain.agents.stubs import FakeImage, FakeLLM
from sbrain.agents.supervisor import IMPLEMENTED, IMPLEMENTED_TASKS, tc3
from sbrain.agents.supervisor.plan import PURPOSE_REWRITE, PURPOSE_WRITE
from sbrain.agents.supervisor.rewrite import rewrite_guidance
from sbrain.bootstrap import TaskRoutedImageProvider, TaskRoutedProvider, build_app, build_stub_app, build_web
from sbrain.intake import MemoryProjectInputSource
from sbrain.orchestrator.errors import CommandError
from sbrain.orchestrator.openai_image import OpenAIImageProvider
from sbrain.orchestrator.tools import ImageRequest, LLMRequest
from sbrain.store_sql import DbSettingsProvider, SqlStore


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
def test_build_app_routes_real_tc3_to_real_llm(tmp_path, db):
    """T-C3까지 진행 — 실제 T-C3 호출(지시 대상 7개)과 전략 · 작성 · 검증-1 실구현 호출은 실제 호출처, 스텁 Task 호출은 가짜
    호출처. 첫 실행은 다시 쓰지 않는다."""
    app, web, real, source = real_worker_app(tmp_path)
    assert app.registry.get("T-C3").fn is tc3.run
    assert all(app.registry.get(t).fn is fn for t, fn in PARTNER_IMPLEMENTED.items())   # 워커 조립은 실구현 (spec 4.15)
    rid = worker_to_screen6(app, web, source)
    tc3_calls = [q for q in real.requests if q.metadata["task_id"] == "T-C3"]
    assert len(tc3_calls) == 7 and {q.metadata["purpose"] for q in tc3_calls} == {PURPOSE_WRITE}
    assert {q.metadata["task_id"] for q in real.requests} == {"T-C1", "T-C3", "T-S1", "T-S2", "T-W1", "T-W2", "T-V1"}
    assert {q.metadata["purpose"] for q in real.requests if q.metadata["task_id"] == "T-V1"} == {"F19"}
    fake_tasks = {q.metadata["task_id"] for q in app.llm.requests}
    assert not fake_tasks & ({"T-C1", "T-C3"} | PARTNER_TASKS)                     # 실구현 호출은 가짜로 가지 않는다
    assert "T-W3" not in fake_tasks | {q.metadata["task_id"] for q in real.requests}   # T-W3는 LLM을 부르지 않는다
    assert by_purpose(real, PURPOSE_REWRITE) == by_purpose(app.llm, PURPOSE_REWRITE) == []
    assert "T-C3" in [e.task_id for e in web.store.executions(rid)]


def test_build_app_routes_redo_rewrite_to_real_llm(tmp_path, db):
    """재수행 — 다시 쓰기 호출(task_id = 대상 T-S1)과 실구현 T-S1의 호출 모두 실제 호출처."""
    app, web, real, source = real_worker_app(tmp_path)
    empty_features_once(real)                                                     # 첫 실행 불통과 → 재수행 한 번
    rid = worker_to_screen6(app, web, source)
    [rw] = by_purpose(real, PURPOSE_REWRITE)
    assert (rw.metadata["task_id"], rw.metadata["agent"]) == ("T-S1", "조율")
    assert by_purpose(app.llm, PURPOSE_REWRITE) == []
    assert len(by_purpose(real, "F02")) == 2                                      # 첫 실행 + 재수행
    assert "T-S1" not in {q.metadata["task_id"] for q in app.llm.requests}
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert "T-S1 안내" in ctx.get("T-S1.instruction")                              # 실제 호출처의 안내로 다시 썼다


def test_build_app_routes_rework_rewrite_to_real_llm(tmp_path, db):
    """재작성(문서층) — 다시 쓰기와 실구현 T-W1의 호출 모두 실제 호출처. 실현가능성 묶음은 본문 · 표 항목이라
    T-W1 · T-W3만 돌고, T-W3(LLM 없음)는 다시 쓰지 않는다 (spec 4.11)."""
    clock = Clock()
    app, web, real, source = real_worker_app(tmp_path, clock)
    rid = worker_to_screen6(app, web, source)
    before = len(by_purpose(real, "F16"))
    tw3_before = [e.task_id for e in web.store.executions(rid)].count("T-W3")
    pid = web.store.load_run(rid).project_id
    acc = web.orchestrator.request_rework_for_project(pid, "실현가능성")
    clock.t = acc.collect_until
    assert worker(app, lease_sec=60).run_once("w") == [f"진행 {rid} 사용자대기"]
    rws = by_purpose(real, PURPOSE_REWRITE)
    assert [q.metadata["task_id"] for q in rws] == ["T-W1"]
    assert {q.metadata["agent"] for q in rws} == {"조율"}
    assert by_purpose(app.llm, PURPOSE_REWRITE) == []
    assert len(by_purpose(real, "F16")) > before                                  # 재작성 실행(실구현)도 실제로
    assert not {q.metadata["task_id"] for q in app.llm.requests} & PARTNER_TASKS
    # T-W3는 LLM을 부르지 않는 Task라 호출 없이 다시 돈다 (spec 4.2) — 지시문 다시 쓰기 호출도 없다
    assert [e.task_id for e in web.store.executions(rid)].count("T-W3") > tw3_before
    assert "T-W3" not in {q.metadata["task_id"] for q in app.llm.requests + real.requests
                          if q.metadata["purpose"] != PURPOSE_REWRITE}
    assert not {q.metadata["task_id"] for q in real.requests} & {"M-1", "G-02a"}


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


def test_build_app_routes_partner_tasks_real_and_stub_app_keeps_stubs(tmp_path, db):
    """워커 조립은 전략 · 작성 · 검증-1을 실구현으로 묶고 그 호출을 실제 호출처로 보낸다. 스텁 조립은 그대로 스텁 (spec 4.15)."""
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    app = build_app(url, project_inputs=projects(1), llm=FakeLLM())
    router = app.engine.providers["openai"]
    assert isinstance(router, TaskRoutedProvider) and PARTNER_TASKS <= router.real_tasks
    assert "T-W3" in PARTNER_TASKS and {app.registry.get(t).fn.__module__ for t in PARTNER_TASKS} <= {
        "sbrain.agents.partner_sw.strategy", "sbrain.agents.partner_sw.writing", "sbrain.agents.partner_sw.verify"}
    for task_id in ("T-S1", "T-W1", "T-V1"):
        req = LLMRequest(provider="openai", model="m", temperature=None, messages=[], timeout_sec=1,
                         response_schema=None, metadata={"task_id": task_id, "agent": "전략", "purpose": "F02"})
        assert router.is_real(req), task_id
    stub = build_stub_app()
    assert {stub.registry.get(t).fn.__module__ for t in PARTNER_TASKS} == {STUB_MODULE}


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


# ── 조립: 공고 서버 주소 ─────────────────────────────────
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


def test_build_web_needs_db_url(monkeypatch, tmp_path):
    monkeypatch.delenv("SBRAIN_DB_URL", raising=False)
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", tmp_path / "없음.env")
    with pytest.raises(RuntimeError, match="SBRAIN_DB_URL"):
        build_web(profile_count=lambda a: 1)


# ── 조립: 이미지 호출처 ─────────────────────────────────
PROMPT = "IMG-SECRET-PROMPT 아이콘을 그려라"


def image_request(task_id: str) -> ImageRequest:
    return ImageRequest(provider="openai", model="m", prompt=PROMPT, image=None, size=None, quality=None,
                        timeout_sec=1.0, metadata={"task_id": task_id, "agent": "구현", "purpose": ""})


def test_router_sends_only_implemented_tasks_to_real():
    real, fake = FakeImage(), FakeImage()
    router = TaskRoutedImageProvider(real, fake, IMPLEMENTED_TASKS)
    implemented = sorted(IMPLEMENTED_TASKS)[0]
    router.create(image_request(implemented))
    router.create(image_request("T-B2"))                                  # T-B2는 아직 스텁 — 가짜로
    assert len(real.requests) == 1 and len(fake.requests) == 1
    assert fake.requests[0].metadata["task_id"] == "T-B2" and "T-B2" not in IMPLEMENTED_TASKS


def test_assemblies(tmp_path):
    stub = build_stub_app()
    assert set(stub.engine.image_providers) >= {"openai"} and stub.engine.image_providers["openai"] is stub.image
    url = f"sqlite:///{(tmp_path / 'img.db').as_posix()}"
    from sbrain.store_sql import create_orchestrator_tables, create_sqlite_engine
    create_orchestrator_tables(create_sqlite_engine(tmp_path / "img.db"))
    real = FakeImage()
    worker = build_app(url, project_inputs=MemoryProjectInputSource(), llm=FakeLLM(), image=real)
    router = worker.engine.image_providers["openai"]
    assert isinstance(router, TaskRoutedImageProvider) and router.real is real and router.fake is worker.image
    web = build_web(url, profile_count=lambda a: 1, project_inputs=MemoryProjectInputSource())
    assert web.engine.image_providers == {}                               # 웹은 이미지 호출처를 두지 않는다


def test_worker_default_image_adapter_does_not_build_client_at_assembly(tmp_path, monkeypatch):
    """키 없이 조립해도 실제 클라이언트를 만들지 않는다 — 실제 이미지 호출이 처음 나갈 때 만든다."""
    built = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: built.append(kw))
    from sbrain.store_sql import create_orchestrator_tables, create_sqlite_engine
    create_orchestrator_tables(create_sqlite_engine(tmp_path / "img.db"))
    url = f"sqlite:///{(tmp_path / 'img.db').as_posix()}"
    app = build_app(url, project_inputs=MemoryProjectInputSource(), llm=FakeLLM())
    assert isinstance(app.engine.image_providers["openai"].real, OpenAIImageProvider) and built == []
