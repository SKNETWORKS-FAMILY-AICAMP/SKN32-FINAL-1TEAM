"""이미지 호출 tools.image — 재시도 · 제한 시간 · 오류 종류, 편집 / 새로 그리기, 크기 · 품질 기본값, 이미지 설정 없는 Task,
호출 기록 · 이미지 토큰(글 토큰과 따로), 관리자 조회, 기록에 지시문 · 그림 없음, OpenAI 이미지 어댑터(가짜 클라이언트).
조립의 이미지 호출처 나누기는 test_bootstrap.py가 본다.

실제 OpenAI는 부르지 않는다 — 가짜 이미지 호출처(FakeImage)와 가짜 SDK 클라이언트만 쓴다.
"""
from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx2
import openai
import pytest
from conftest import make_app, start_and_select, tok
from sqlalchemy import text

from sbrain.agents.stubs import FakeImage
from sbrain.models.clock import utc_now
from sbrain.orchestrator import Settings
from sbrain.orchestrator.errors import FormatError, ProviderError, ToolCallExhausted
from sbrain.orchestrator.openai_image import OpenAIImageProvider
from sbrain.orchestrator.tools import (
    CallSink, ImageRequest, ImageResponse, TokenUsage, Tools, ToolsConfig, ToolsContext,
)
from sbrain.orchestrator.trace import CallLog, ExecutionRecord, add_tokens
from sbrain.store_sql import SqlStore


PROMPT = "IMG-SECRET-PROMPT 아이콘을 그려라"


INPUT = b"INPUT-IMAGE-MARKER-BYTES"


IU = TokenUsage(input_tokens=50, output_tokens=4000)          # 이미지 호출 한 번의 사용량


TU = TokenUsage(input_tokens=7, cached_input_tokens=None, output_tokens=3, reasoning_tokens=None)


def make_tools(fake: FakeImage | None = None, *, retry: int = 5, model: str | None = "img-model",
               size: str | None = "1024x1536", quality: str | None = "medium",
               providers: dict | None = None) -> tuple[Tools, CallSink, list, FakeImage]:
    fake = fake or FakeImage()
    sink, sleeps = CallSink(), []
    cfg = ToolsConfig(agent="구현", provider="openai", model="text-model", temperature=0.3, timeout_sec=300,
                      retry_count=retry, retry_interval_sec=2.0, reasoning_effort="low",
                      image_provider="openai" if model else None, image_model=model, image_quality=quality,
                      image_size=size, image_timeout_sec=77.0)
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-B2", providers={}, sink=sink, now=utc_now,
                       sleep=sleeps.append,
                       image_providers={"openai": fake} if providers is None else providers)
    return Tools(cfg, ctx), sink, sleeps, fake


# ── tools.image: 재시도 · 제한 시간 · 오류 종류 ─────────────
def test_retry_then_success_returns_png_and_logs_image_call():
    fake = FakeImage()
    fake.plan("T-B2", ["timeout", "rate_limit", "ok"])
    t, sink, sleeps, _ = make_tools(fake)
    png = t.image(PROMPT, purpose="아이콘")
    assert png == FakeImage.PNG and png.startswith(b"\x89PNG\r\n\x1a\n")
    [log] = sink.drain()
    assert [x.outcome for x in log.tries] == ["응답지연", "호출실패", "성공"]
    assert [x.error_kind for x in log.tries] == ["일시", "일시", None]
    assert sleeps == [2.0, 2.0]
    assert (log.call_type, log.provider, log.model, log.temperature, log.reasoning_effort) == (
        "image", "openai", "img-model", None, None)
    assert log.timeout_sec == 77.0 and log.final_outcome == "성공" and log.purpose == "아이콘"
    assert all(r.timeout_sec == 77.0 for r in fake.requests)               # 제한 시간은 '<Task>.image'
    assert fake.requests[0].model == "img-model" and fake.requests[0].provider == "openai"
    assert fake.requests[0].metadata["task_id"] == "T-B2" and fake.requests[0].metadata["purpose"] == "아이콘"


@pytest.mark.parametrize("outcome, error, kind", [
    ("bad_request", "호출실패", "입력"), ("auth", "호출실패", "운영"), ("timeout", "응답지연", "일시"),
    ("rate_limit", "호출실패", "일시"), ("empty", "형식오류", "일시"),
])
def test_exhausted_raises_with_kind(outcome, error, kind):
    fake = FakeImage()
    fake.plan("T-B2", [outcome] * 3)
    t, sink, _, _ = make_tools(fake, retry=2)
    with pytest.raises(ToolCallExhausted) as e:
        t.image(PROMPT)
    assert (e.value.error, e.value.error_kind, e.value.tries) == (error, kind, 3)
    [log] = sink.drain()
    assert log.final_outcome == "소진" and (log.error, log.error_kind) == (error, kind) and len(fake.requests) == 3


def test_missing_image_provider_is_operation_failure():
    t, sink, _, _ = make_tools(providers={}, retry=1)                       # 웹 조립처럼 이미지 호출처가 없다
    with pytest.raises(ToolCallExhausted) as e:
        t.image(PROMPT)
    assert (e.value.error, e.value.error_kind) == ("호출실패", "운영")


# ── 편집 / 새로 그리기, 크기 · 품질 기본값 ─────────────────
def test_edit_when_image_given_and_generate_otherwise():
    t, _, _, fake = make_tools()
    t.image(PROMPT)
    t.image(PROMPT, image=INPUT)
    assert fake.requests[0].image is None and fake.requests[1].image == INPUT
    assert [fake.requests[0].prompt, fake.requests[1].prompt] == [PROMPT, PROMPT]


def test_size_quality_default_from_task_entry_or_given():
    t, _, _, fake = make_tools()
    t.image(PROMPT)
    t.image(PROMPT, size="1024x1024", quality="high")
    t.image(PROMPT, size="1536x1024")
    assert [(r.size, r.quality) for r in fake.requests] == [
        ("1024x1536", "medium"), ("1024x1024", "high"), ("1536x1024", "medium")]


# ── 이미지 설정 없는 Task — 즉시 실패 ───────────────────────
def test_task_without_image_model_fails_immediately():
    fake = FakeImage()
    t, sink, sleeps, _ = make_tools(fake, model=None)
    with pytest.raises(ToolCallExhausted) as e:
        t.image(PROMPT, purpose="아이콘")
    assert (e.value.error, e.value.error_kind, e.value.tries) == ("호출실패", "운영", 1)
    assert e.value.detail == "이미지 모델 설정 없음"
    assert fake.requests == [] and sleeps == []                           # 호출처를 부르지 않고 재시도도 없다
    [log] = sink.drain()
    assert (log.call_type, log.final_outcome, log.error, log.error_kind) == ("image", "소진", "호출실패", "운영")
    assert e.value.call_id == log.call_id and log.model is None
    [only] = log.tries
    assert (only.outcome, only.error_kind, only.detail) == ("호출실패", "운영", "이미지 모델 설정 없음")


# ── 토큰 · 스레드 · 내용 없음 ─────────────────────────────
def test_call_tokens_per_try_and_total():
    fake = FakeImage()
    fake.usage["T-B2"] = IU
    fake.plan("T-B2", ["empty", "ok"])                                    # 빈 그림도 비용은 남는다
    t, sink, _, _ = make_tools(fake)
    t.image(PROMPT)
    [log] = sink.drain()
    assert [tok(x) for x in log.tries] == [(50, None, 4000, None)] * 2
    assert tok(log) == (100, None, 8000, None)
    t2, sink2, _, _ = make_tools(FakeImage())                             # 사용량 없는 응답 → None
    t2.image(PROMPT)
    assert tok(sink2.drain()[0]) == (None,) * 4


def test_thread_safe_for_item_calls():
    fake = FakeImage()
    fake.plan("T-B2", ["timeout", "ok"], item_key="i-1")
    t, sink, _, _ = make_tools(fake)
    with ThreadPoolExecutor(4) as pool:
        out = list(pool.map(lambda k: t.for_item(k).image(PROMPT), [f"i-{n}" for n in range(8)]))
    assert out == [FakeImage.PNG] * 8
    logs = {log.item_key: log for log in sink.drain()}
    assert len(logs) == 8 and len(logs["i-1"].tries) == 2 and len(logs["i-2"].tries) == 1


def test_no_prompt_or_image_in_log_or_exception():
    fake = FakeImage()
    fake.plan("T-B2", ["ok", "bad_request", "bad_request"])
    t, sink, _, _ = make_tools(fake, retry=1)
    png = t.image(PROMPT, image=INPUT)
    with pytest.raises(ToolCallExhausted) as e:
        t.image(PROMPT, image=INPUT)
    blob = json.dumps([log.dump() for log in sink.drain()], ensure_ascii=False) + str(e.value) + repr(e.value)
    for secret in secrets_of(png):
        assert secret not in blob
    assert "IMG-SECRET" not in repr(fake.requests[0]) and "INPUT-IMAGE" not in repr(fake.requests[0])


def secrets_of(png: bytes) -> list[str]:
    return ["IMG-SECRET", "INPUT-IMAGE-MARKER", base64.b64encode(INPUT).decode()[:16],
            base64.b64encode(png).decode()[:24], png.hex()[:24], repr(png)[:24]]


# ── 실행 기록 합계 ───────────────────────────────────────
def log_of(call_type: str, usage: TokenUsage) -> CallLog:
    return CallLog(call_id=call_type, run_id="r", execution_id="e", task_id="T-B2", agent="구현", call_type=call_type,
                   purpose="", timeout_sec=1, input_tokens=usage.input_tokens,
                   cached_input_tokens=usage.cached_input_tokens, output_tokens=usage.output_tokens,
                   reasoning_tokens=usage.reasoning_tokens)


def test_execution_totals_keep_image_tokens_apart():
    rec = ExecutionRecord(execution_id="e", run_id="r", task_id="T-B2", attempt=1, trigger="첫실행", agent="구현",
                          step_kind="task", result_ref="x@1", created_at=utc_now())
    assert (rec.image_input_tokens, rec.image_output_tokens) == (None, None)
    add_tokens(rec, [log_of("search", TokenUsage())])
    assert tok(rec) == (None,) * 4 and rec.image_input_tokens is None     # 이미지 호출이 없으면 None
    add_tokens(rec, [log_of("llm", TU), log_of("image", IU), log_of("image", IU)])
    assert tok(rec) == (7, None, 3, None)                                 # 글 합계에 이미지 토큰을 더하지 않는다
    assert (rec.image_input_tokens, rec.image_output_tokens) == (100, 8000)
    add_tokens(rec, [log_of("image", TokenUsage(input_tokens=1))])        # 재개 — 이어서 더한다
    assert (rec.image_input_tokens, rec.image_output_tokens) == (101, 8000)


# ── 흐름: 실행 기록 · 재개 · 관리자 조회 · 저장 ─────────────
def image_settings() -> Settings:
    s = Settings()
    s.tasks["T-S2"].image_provider = "openai"
    s.tasks["T-S2"].image_model = "img-test"
    s.tasks["T-S2"].image_quality = "low"
    s.tasks["T-S2"].image_size = "1024x1024"
    s.task_timeouts["T-S2.image"] = 33.0
    return s


def with_image_call(app, task_id: str = "T-S2") -> list:
    """Task 함수 앞에서 이미지를 한 번(편집) 그린다 — 받은 그림 바이트를 모은다."""
    base, got = app.registry.get(task_id).fn, []

    def fn(inp, tools):
        got.append(tools.image(PROMPT, image=INPUT, purpose="아이콘"))
        return base(inp, tools)
    app.registry.bind(task_id, fn)
    return got


def everything_stored(app, rid: str) -> str:
    """저장된 기록 · 관리자 조회를 모두 글로 — 지시문 · 그림이 어디에도 없어야 한다."""
    o, s = app.orchestrator, app.store
    parts = [r.dump() for r in s.executions(rid)] + [c.dump() for c in s.call_logs(rid)]
    parts += [e.dump() for e in s.events(rid)] + [f.dump() for f in s.feedback(rid)]
    parts += [r.dump() for r in o.admin_executions(limit=500)] + [o.admin_summary().dump()]
    parts += [c.dump() for r in s.executions(rid) for c in o.admin_calls(r.execution_id)]
    return json.dumps(parts, ensure_ascii=False, default=str)


def test_flow_image_call_records_and_admin_views(clock):
    app = make_app(clock, settings=image_settings())
    app.llm.usage["T-S2"] = TU
    app.image.usage["T-S2"] = IU
    got = with_image_call(app)
    rid = start_and_select(app)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert got == [FakeImage.PNG]
    [req] = app.image.requests
    assert (req.model, req.size, req.quality, req.timeout_sec, req.image) == ("img-test", "1024x1024", "low", 33.0, INPUT)
    rec = next(r for r in app.store.executions(rid) if r.task_id == "T-S2")
    calls = [c for c in app.store.call_logs(rid) if c.execution_id == rec.execution_id]
    [img] = [c for c in calls if c.call_type == "image"]
    assert (img.provider, img.model, img.temperature, img.reasoning_effort) == ("openai", "img-test", None, None)
    assert tok(img) == (50, None, 4000, None)
    text_calls = [c for c in calls if c.call_type == "llm"]
    assert tok(rec) == (7 * len(text_calls), None, 3 * len(text_calls), None)      # 글 토큰만
    assert (rec.image_input_tokens, rec.image_output_tokens) == (50, 4000)
    [row] = [r for r in app.orchestrator.admin_executions(task_id="T-S2") if r.execution_id == rec.execution_id]
    dumped = row.dump()
    assert (dumped["imageInputTokens"], dumped["imageOutputTokens"]) == (50, 4000)
    assert dumped["tokens"]["inputTokens"] == rec.input_tokens
    admin_img = [c for c in app.orchestrator.admin_calls(rec.execution_id) if c.call_type == "image"]
    assert [(c.model, c.tokens.input_tokens, c.tokens.output_tokens) for c in admin_img] == [("img-test", 50, 4000)]
    summary = app.orchestrator.admin_summary().dump()
    every = app.store.executions(rid)
    assert summary["totalTokens"] == sum((r.input_tokens or 0) + (r.output_tokens or 0) for r in every)
    assert summary["totalImageTokens"] == 4050
    others = [r for r in every if r.task_id != "T-S2"]
    assert all(r.image_input_tokens is None and r.image_output_tokens is None for r in others)
    blob = everything_stored(app, rid)
    for secret in secrets_of(FakeImage.PNG):
        assert secret not in blob
    if isinstance(app.store, SqlStore):                                   # 조회용 칸에도 이미지 합계가 있다
        with app.store.engine.connect() as conn:
            cols = conn.execute(text("SELECT input_tokens, image_input_tokens, image_output_tokens "
                                     "FROM orch_executions WHERE execution_id = :e"),
                                {"e": rec.execution_id}).one()
            ctype = conn.execute(text("SELECT call_type, model FROM orch_call_logs WHERE call_id = :c"),
                                 {"c": img.call_id}).one()
            raw = " ".join(str(v) for v in conn.execute(text(
                "SELECT record_json FROM orch_executions WHERE run_id = :r"), {"r": rid}).scalars())
            raw += " ".join(str(v) for v in conn.execute(text(
                "SELECT tries FROM orch_call_logs WHERE run_id = :r"), {"r": rid}).scalars())
        assert tuple(cols) == (rec.input_tokens, 50, 4000) and tuple(ctype) == ("image", "img-test")
        assert "IMG-SECRET" not in raw and "INPUT-IMAGE" not in raw


def test_flow_resume_keeps_summing_image_tokens(clock):
    app = make_app(clock, settings=image_settings())
    app.image.usage["T-S2"] = IU
    with_image_call(app)
    rid = start_and_select(app)
    app.llm.plan("T-S2", ["timeout"] * 6)                                 # 이미지 뒤 글 호출이 재시도를 다 쓴다
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "재개대기"
    [rec] = [r for r in app.store.executions(rid) if r.task_id == "T-S2"]
    assert (rec.image_input_tokens, rec.image_output_tokens) == (50, 4000)
    clock.advance(minutes=16)
    assert app.orchestrator.tick(clock.t) == [rid]
    [rec] = [r for r in app.store.executions(rid) if r.task_id == "T-S2"]
    assert rec.status == "성공" and rec.resume_count == 1
    assert (rec.image_input_tokens, rec.image_output_tokens) == (100, 8000)   # 재개 때 이어서 더한다
    assert tok(rec) == (None,) * 4                                        # 글 호출은 사용량 없음 (가짜)


def test_flow_task_without_image_setting_records_failed_call(clock):
    app = make_app(clock)                                                 # 기본 설정 — T-S2는 이미지 설정 없음
    seen = []
    base = app.registry.get("T-S2").fn

    def fn(inp, tools):
        try:
            tools.image(PROMPT)
        except ToolCallExhausted as e:
            seen.append((e.error, e.error_kind, e.detail))
        return base(inp, tools)
    app.registry.bind("T-S2", fn)
    rid = start_and_select(app)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert seen == [("호출실패", "운영", "이미지 모델 설정 없음")] and app.image.requests == []
    [img] = [c for c in app.store.call_logs(rid) if c.call_type == "image"]
    assert (img.final_outcome, img.error, img.error_kind, len(img.tries)) == ("소진", "호출실패", "운영", 1)
    assert img.tries[0].detail == "이미지 모델 설정 없음"


# ── OpenAI 이미지 어댑터 (가짜 클라이언트) ──────────────────
REQ = httpx2.Request("POST", "https://api.openai.com/v1/images/generations")


PNG = b"\x89PNG\r\n\x1a\nfake-png-bytes"


class FakeImages:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.generate_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    def _reply(self):
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return self._reply()

    def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return self._reply()


def images_response(png: bytes | None = PNG, usage=None):
    data = [SimpleNamespace(b64_json=base64.b64encode(png).decode() if png is not None else None, url=None)]
    return SimpleNamespace(data=data, usage=usage)


def adapter(outcomes: list) -> tuple[OpenAIImageProvider, FakeImages]:
    images = FakeImages(outcomes)
    return OpenAIImageProvider(SimpleNamespace(images=images)), images


def oa_request(**over) -> ImageRequest:
    base = dict(provider="openai", model="gpt-image-test", prompt="그려라", image=None, size="1024x1536",
                quality="medium", timeout_sec=120.0, metadata={"task_id": "T-B2"})
    return ImageRequest(**{**base, **over})


def test_openai_generate_args_and_png():
    p, images = adapter([images_response()])
    reply = p.create(oa_request())
    assert isinstance(reply, ImageResponse) and reply.png == PNG and reply.usage is None
    [call] = images.generate_calls
    assert images.edit_calls == []
    assert call == {"model": "gpt-image-test", "prompt": "그려라", "size": "1024x1536", "quality": "medium",
                    "timeout": 120.0}


def test_openai_edit_args_and_usage():
    usage = SimpleNamespace(input_tokens=300, output_tokens=4160, total_tokens=4460,
                            input_tokens_details=SimpleNamespace(image_tokens=200, text_tokens=100))
    p, images = adapter([images_response(usage=usage)])
    reply = p.create(oa_request(image=INPUT, size=None, quality=None))
    assert reply.png == PNG and reply.usage == TokenUsage(input_tokens=300, output_tokens=4160)
    [call] = images.edit_calls
    assert images.generate_calls == []
    assert call["model"] == "gpt-image-test" and call["prompt"] == "그려라" and call["timeout"] == 120.0
    assert "size" not in call and "quality" not in call                   # 값이 없으면 싣지 않는다
    name, data, mime = call["image"]
    assert data == INPUT and name.endswith(".png") and mime == "image/png"


@pytest.mark.parametrize("error, expected", [
    (openai.APITimeoutError(request=REQ), TimeoutError),
    (openai.APIConnectionError(request=REQ), ConnectionError),
])
def test_openai_image_transport_errors(error, expected):
    p, _ = adapter([error])
    with pytest.raises(expected):
        p.create(oa_request())


def test_openai_image_status_error_keeps_status_and_no_prompt():
    p, _ = adapter([openai.BadRequestError("bad", response=httpx2.Response(400, request=REQ), body=None)])
    with pytest.raises(ProviderError) as e:
        p.create(oa_request(prompt="IMG-SECRET-PROMPT"))
    assert e.value.status == 400 and "IMG-SECRET" not in str(e.value)


def test_openai_image_empty_is_format_error_with_usage():
    usage = SimpleNamespace(input_tokens=10, output_tokens=0)
    p, _ = adapter([images_response(png=None, usage=usage), SimpleNamespace(data=[], usage=None)])
    with pytest.raises(FormatError) as e:
        p.create(oa_request())
    assert e.value.usage == TokenUsage(input_tokens=10, output_tokens=0)
    with pytest.raises(FormatError):
        p.create(oa_request())


def test_openai_image_through_tools_retry():
    p, images = adapter([openai.APITimeoutError(request=REQ), images_response()])
    t, sink, _, _ = make_tools(providers={"openai": p})
    assert t.image(PROMPT) == PNG
    assert [x.outcome for x in sink.drain()[0].tries] == ["응답지연", "성공"] and len(images.generate_calls) == 2
