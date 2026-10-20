"""구현 · 검증-2 실구현을 흐름에 끼워 돌린다.

스텁 조립에 bind_partner_bv, 가짜 LLM은 목적별 응답(bv_fake), 가짜 이미지는 스텁 조립의 것(1×1 그림 → 칸 수 불일치) 또는
EchoImage. 메모리 · SQLite 두 저장소(store_backend)에서 돈다. 네트워크 없음. 워커 조립의 호출처 나누기도 여기서 본다.

다음 작업(실구현 판정)이 이 파일의 앱 흐름 시험을 그대로 다시 통과시켜야 한다.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from bv_fake import BV_TASKS, ELEMENTS, HTML, MARK, VARIANTS, EchoImage, respond_bv
from conftest import make_app, pre_input, project_for, to_screen8
from flow_helpers import ctx_of, records_of_task, rework, state
from worker_helpers import projects

from sbrain.agents.partner_bv.tasks import IMPLEMENTED as BV_IMPLEMENTED
from sbrain.agents.partner_bv.tasks import IMPLEMENTED_TASKS, bind_partner_bv
from sbrain.agents.stubs import FakeImage, FakeLLM
from sbrain.bootstrap import TaskRoutedImageProvider, TaskRoutedProvider, build_app, build_stub_app
from sbrain.flow.sbrain_flow import EVENT_IMAGE_FALLBACK, ICON_FALLBACK_DETAIL, IMAGE_FALLBACK_DETAIL
from sbrain.models import Sentence
from sbrain.orchestrator.tools import ImageRequest, LLMRequest
from sbrain.orchestrator.trace import CALL_LOG_TEXT_MAX

FEATURES = ["회원 등록·조회", "수업 예약"]


def bv_app(clock, html=HTML, **kw):
    app = make_app(clock, **kw)
    bind_partner_bv(app.registry)
    respond_bv(app.llm, html=html)
    return app


def bv_requests(app, task_id: str | None = None) -> list[LLMRequest]:
    return [q for q in app.llm.requests if q.metadata["task_id"] in ((task_id,) if task_id else BV_TASKS)]


def with_feature_lines(app, features: list[str] | None = None) -> None:
    """스텁 T-W1 계획서 첫 항목에 기능을 정의한 줄을 더한다 — T-V2가 확인 요소를 뽑는다(정의 줄이 있어야 뽑는다)."""
    base = app.registry.get("T-W1").fn

    def tw1(inp, tools):
        out = base(inp, tools)
        names = features or list(out.plan_doc.feature_list)
        first = next(s for s in out.plan_doc.sections if s.content_type == "section")
        extra = [Sentence(sentence_id=f"def-{n}", text=f"{f}: 정보를 입력하면 결과를 화면에 보여 준다.", is_title=False,
                          paragraph_no=90 + n) for n, f in enumerate(names)]
        changed = first.model_copy(update={"sentences": list(first.sentences) + extra})
        sections = [changed if s is first else s for s in out.plan_doc.sections]
        return out.model_copy(update={"plan_doc": out.plan_doc.model_copy(update={"sections": sections}),
                                      "sections": sections})
    app.registry.bind("T-W1", tw1)


def with_features(app, features: list[str]) -> None:
    """스텁 T-C1의 핵심 기능을 바꾼다 — 기능 목록(featureList)이 이 값으로 흐른다."""
    base = app.registry.get("T-C1").fn

    def tc1(inp, tools):
        out = base(inp, tools)
        return out.model_copy(update={"item_spec": out.item_spec.model_copy(update={"core_features": features})})
    app.registry.bind("T-C1", tc1)


def recorded(app, rid: str) -> str:
    s, o = app.store, app.orchestrator
    parts = [r.dump() for r in s.executions(rid)] + [c.dump() for c in s.call_logs(rid)]
    parts += [e.dump() for e in s.events(rid)] + [f.dump() for f in s.feedback(rid)]
    parts += [r.dump() for r in o.admin_executions(limit=500)]
    parts += [c.dump() for r in s.executions(rid) for c in o.admin_calls(r.execution_id)]
    return json.dumps(parts, ensure_ascii=False, default=str)


# ── 흐름 연결 ──────────────────────────────────────────────
def test_bv_tasks_run_in_flow_to_screen8(clock):
    app = bv_app(clock)
    assert all(app.registry.get(t).fn is fn for t, fn in BV_IMPLEMENTED.items())
    rid = to_screen8(app)
    assert state(app, rid) == ("산출물확인", "사용자대기")
    ctx = ctx_of(app, rid)
    proto, info = ctx.get("prototype"), ctx.get("infographic")
    html = app.engine.files.read(proto.entry_file.key).decode("utf-8")
    assert proto.entry_file.name == "index.html" and 'data-kit="font"' in html and MARK in html
    assert proto.readme_file is not None                                                 # M-3이 채웠다
    assert info.image_file.name == "infographic.svg" and info.format == "svg"
    assert app.engine.files.read(info.image_file.key).lstrip().startswith(b"<svg")
    score = ctx.get("artifactScore")
    assert score.code_check.gate_failures == [] and score.total > 0
    assert all(ch.earned is not None for ch in score.code_check.checks)
    purposes = {q.metadata["purpose"] for q in bv_requests(app)}
    assert {"T-B1 HTML 생성", "T-B2 인포그래픽 정보 추출"} <= purposes
    assert {p for p in purposes if p.startswith("계획서 대조: ")} == {f"계획서 대조: {f}" for f in FEATURES}
    blob = recorded(app, rid)
    assert MARK not in blob                                                              # 산출물 내용이 기록에 없다
    for ref in (proto.entry_file, info.image_file, proto.readme_file):                  # 파일 이름 · 키도 없다
        assert ref.name not in blob and ref.key not in blob and ref.key.split("/")[2] not in blob


def test_tb1_gate_failure_redo_passes_previous_source_then_tv2_scores_it(clock):
    """검사에 걸린 HTML도 진입 파일이다 — 재수행 때 이전 원문으로 넘어가고(끼워 넣은 것을 빼고 LLM에 실림), 끝내 못 고치면
    T-V2가 그 HTML을 채점한다. 샌드박스 무시 계열(alert)은 7번만 감점."""
    app = bv_app(clock, html=VARIANTS["ignored"])
    rid = to_screen8(app)
    tb1 = records_of_task(app, rid, "T-B1")
    assert len(tb1) >= 2                                                                 # 첫 실행 + 재수행
    reqs = bv_requests(app, "T-B1")
    assert len(reqs) == len(tb1)
    assert "<이전HTML>" not in reqs[0].messages[-1]["content"]
    for req in reqs[1:]:
        user = req.messages[-1]["content"]
        assert "<이전HTML>" in user and MARK in user and "data:font/woff2" not in user
    ctx = ctx_of(app, rid)
    last = ctx.get_ref(tb1[-1].result_ref)
    assert not ctx.get_ref(next(r for r in tb1[-1].outputs if r.startswith("T-B1.check@"))).passed
    assert last.entry_file is not None and ctx.get("prototype").entry_file == last.entry_file   # M-3 뒤에도 같은 진입 파일
    score = ctx.get("artifactScore")
    assert score.code_check.gate_failures == []
    [seventh] = [ch for ch in score.code_check.checks if ch.no == 7]
    assert not seventh.passed and score.total > 0
    # 시험 비밀값 전체로 찾는다 — 'abcd'만 찾으면 무작위 16진수 ID(호출 · 실행 ID)에 우연히 들어가 가끔 실패했다
    assert "abcd1234efgh5678" not in recorded(app, rid) and MARK not in recorded(app, rid)


def test_tb1_unfixed_external_dependency_loses_item_7(clock):
    """외부 의존(E-B1-DEP)을 끝내 못 고친 HTML은 T-V2 코드 점검 7번에서 감점한다(담당자 10-12 회신). 통과 필수 조건은 아니다."""
    app = bv_app(clock, html=VARIANTS["dependency"])
    rid = to_screen8(app)
    score = ctx_of(app, rid).get("artifactScore")
    assert score.code_check.gate_failures == []
    [seventh] = [ch for ch in score.code_check.checks if ch.no == 7]
    assert not seventh.passed and seventh.applicable and seventh.earned == 0
    assert "외부 의존 1개" in seventh.detail and score.total > 0


@pytest.mark.parametrize("variant,code", [("halting", "sandbox"), ("secret", "secret")])
def test_tb1_unfixed_storage_or_secret_scores_zero(clock, variant, code):
    app = bv_app(clock, html=VARIANTS[variant])
    rid = to_screen8(app)
    score = ctx_of(app, rid).get("artifactScore")
    assert score.code_check.gate_failures == [code] and score.total == 0
    diag = [e for e in app.store.events(rid) if e.kind == "검증2진단"]
    assert diag and any("통과 필수 조건 실패" in e.detail for e in diag)
    assert all("index.html" not in e.detail and "abcd1234efgh5678" not in e.detail for e in diag)


# ── T-B2 기본 아이콘 대체 · '이미지대체' 사건 ──────────────────
@pytest.mark.parametrize("mode", ["count_mismatch", "parse_error", "image_exhausted", "custom"])
def test_image_fallback_event_once_per_tb2_execution(clock, mode):
    app = bv_app(clock)
    if mode == "parse_error":
        app.engine.image_providers["openai"] = EchoImage(default="garbage")
    elif mode == "custom":
        app.engine.image_providers["openai"] = EchoImage()
    elif mode == "image_exhausted":
        app.image.plan("T-B2", ["timeout"] * 60)
    rid = to_screen8(app)
    tb2 = records_of_task(app, rid, "T-B2")
    events = [e for e in app.store.events(rid) if e.kind == EVENT_IMAGE_FALLBACK]
    ctx = ctx_of(app, rid)
    if mode == "custom":
        assert events == [] and all(not ctx.get_ref(r.result_ref).icon_fallback for r in tb2)
        return
    assert sorted(e.execution_id for e in events) == sorted(r.execution_id for r in tb2)   # 실행 기록마다 하나
    detail = IMAGE_FALLBACK_DETAIL if mode == "image_exhausted" else ICON_FALLBACK_DETAIL
    assert {e.detail for e in events} == {detail}
    assert all(ctx.get_ref(r.result_ref).icon_fallback for r in tb2)
    shown = json.dumps([n.dump() for n in app.store.load_run(rid).notices], ensure_ascii=False)
    assert detail not in shown and "아이콘" not in shown                                 # 사용자 화면에 알리지 않는다


# ── T-V2 확인 요소 목록 이어받기 ─────────────────────────────
def test_next_tv2_receives_previous_feature_elements(clock):
    app = bv_app(clock)
    with_feature_lines(app)
    rid = to_screen8(app)
    first = ctx_of(app, rid).get("featureElements")
    assert len(first) == 2 and all(v == ELEMENTS for v in first.values())
    extracted = [q for q in bv_requests(app, "T-V2") if q.metadata["purpose"].startswith("계획서 대조 요소: ")]
    assert len(extracted) == 2
    n = len(app.llm.requests)
    rework(app, clock, rid, "실행 파일")
    tv2 = records_of_task(app, rid, "T-V2")
    assert len(tv2) == 2
    assert "featureElements@1" in tv2[1].inputs                                         # 직전 목록을 받았다
    later = [q for q in app.llm.requests[n:] if q.metadata["task_id"] == "T-V2"]
    assert later and not [q for q in later if q.metadata["purpose"].startswith("계획서 대조 요소: ")]
    assert ctx_of(app, rid).get("featureElements") == first
    assert all(v[0] not in recorded(app, rid) for v in first.values())                  # 요소 목록은 기록에 없다


# ── 보안: 보내는 칸 · 기록 칸 길이 ─────────────────────────────
SECRET_FORM = dict(representative_name="홍길비밀", birth_date=date(1977, 7, 7), gender="비밀성별값",
                   business_reg_no="777-66-55555", company_name="비밀상호주식회사", region="비밀특별시 숨김구")
SECRET_VALUES = ["홍길비밀", "1977-07-07", "1977", "비밀성별값", "777-66-55555", "비밀상호주식회사", "비밀특별시", "숨김구"]


def test_bv_llm_requests_carry_no_applicant_identity(clock):
    app = bv_app(clock)
    with_feature_lines(app)
    res = app.orchestrator.start_run("acc-1", pre_input(**SECRET_FORM), project_id=project_for(app))
    rid = res.run_id
    app.orchestrator.select_announcement(rid, "A01")
    app.orchestrator.advance(rid)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    assert state(app, rid) == ("산출물확인", "사용자대기")
    reqs = bv_requests(app)
    assert {q.metadata["task_id"] for q in reqs} == set(BV_TASKS)
    sent = json.dumps([q.messages for q in reqs], ensure_ascii=False)
    for value in SECRET_VALUES:
        assert value not in sent, value
    prompts = " ".join(q.prompt for q in app.image.requests)
    assert app.image.requests and all(value not in prompts for value in SECRET_VALUES)


def test_long_feature_name_is_clipped_in_call_logs(clock):
    long_name = "수업 예약 " + "긴기능이름" * 50
    assert len(long_name) > 250
    app = bv_app(clock, html=HTML.replace("수업 예약", long_name))
    with_features(app, [FEATURES[0], long_name])
    with_feature_lines(app)
    rid = to_screen8(app)
    assert state(app, rid) == ("산출물확인", "사용자대기")
    logs = app.store.call_logs(rid)
    assert all(len(log.purpose) <= CALL_LOG_TEXT_MAX and len(log.item_key or "") <= CALL_LOG_TEXT_MAX for log in logs)
    clipped = [log for log in logs if log.task_id == "T-V2" and len(log.purpose) == CALL_LOG_TEXT_MAX]
    assert clipped and {log.purpose[:7] for log in clipped} <= {"계획서 대조 ", "계획서 대조:"}
    full = [q for q in bv_requests(app, "T-V2") if len(q.metadata["purpose"]) > CALL_LOG_TEXT_MAX]
    assert full                                                                          # 요청 메타데이터는 원래 목적


# ── 조립: 워커는 실구현 · 실제 호출처, 스텁 조립은 스텁 ───────────
def _llm_request(task_id: str) -> LLMRequest:
    return LLMRequest(provider="openai", model="m", temperature=None, messages=[], timeout_sec=1, response_schema=None,
                      metadata={"run_id": "r", "task_id": task_id, "agent": "구현", "purpose": "p", "item_key": None})


def _image_request(task_id: str) -> ImageRequest:
    return ImageRequest(provider="openai", model="m", prompt="그림", image=None, size=None, quality=None,
                        timeout_sec=1, metadata={"task_id": task_id})


def test_worker_routes_bv_llm_and_tb2_image_to_real(tmp_path, db):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    real, real_image = FakeLLM(), FakeImage()
    app = build_app(url, project_inputs=projects(1), llm=real, image=real_image)
    assert all(app.registry.get(t).fn is fn for t, fn in BV_IMPLEMENTED.items())
    router, images = app.engine.providers["openai"], app.engine.image_providers["openai"]
    assert isinstance(router, TaskRoutedProvider) and IMPLEMENTED_TASKS <= router.real_tasks
    assert isinstance(images, TaskRoutedImageProvider) and "T-B2" in images.real_tasks
    for task_id in BV_TASKS:
        router.complete(_llm_request(task_id))
    for task_id in ("T-P1", "T-P2"):                                                     # 남은 스텁 Task는 가짜
        router.complete(_llm_request(task_id))
    assert [q.metadata["task_id"] for q in real.requests] == list(BV_TASKS)
    assert [q.metadata["task_id"] for q in app.llm.requests] == ["T-P1", "T-P2"]
    images.create(_image_request("T-B2"))
    images.create(_image_request("T-W2"))
    assert [q.metadata["task_id"] for q in real_image.requests] == ["T-B2"]
    assert [q.metadata["task_id"] for q in app.image.requests] == ["T-W2"]
    stub = build_stub_app()
    assert {stub.registry.get(t).fn.__module__ for t in BV_TASKS} == {"sbrain.agents.stubs"}
