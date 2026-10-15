"""OpenAI 글 · 이미지 어댑터 — 응답 코드 오류에서 본문 오류 코드 · Retry-After 헤더를 읽어 ProviderError에 싣는다
(spec 2.3 · 3절). 가짜 클라이언트와 직접 만든 SDK 예외로 본다 (네트워크 · 실제 대기 없음)."""
from __future__ import annotations

from types import SimpleNamespace

import httpx2
import openai
import pytest

from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import ProviderError, ToolCallExhausted
from sbrain.orchestrator.openai_image import OpenAIImageProvider
from sbrain.orchestrator.openai_provider import OpenAIProvider
from sbrain.orchestrator.tools import CallSink, ImageRequest, LLMRequest, Tools, ToolsConfig, ToolsContext

REQ = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
SECRET = "SECRET-BODY-TEXT"   # 본문 메시지 — 예외 메시지 · 기록 어디에도 나오면 안 된다


def status_error(status: int = 429, *, body: object = None, headers: dict | None = None,
                 cls: type = openai.APIStatusError) -> openai.APIStatusError:
    """SDK가 만드는 꼴 그대로 — 메시지에는 본문 내용이 들어 있다(어댑터가 옮기지 않아야 한다)."""
    response = httpx2.Response(status, request=REQ, headers=headers or {})
    return cls(f"Error code: {status} - {SECRET}", response=response, body=body)


def err_body(code: object) -> dict:
    """SDK가 넘기는 본문 — 응답의 error 객체(SDK가 'error' 안을 꺼내 넘긴다)."""
    return {"message": SECRET, "type": "insufficient_quota", "param": None, "code": code}


# ── 가짜 클라이언트 ───────────────────────────────────────
class FakeCompletions:
    def __init__(self, outcomes: list) -> None:
        self.outcomes, self.calls = list(outcomes), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out),
                                                        finish_reason="stop")], usage=None)


class FakeImages:
    def __init__(self, outcomes: list) -> None:
        self.outcomes, self.calls = list(outcomes), []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    edit = generate


def text_adapter(outcomes: list):
    comp = FakeCompletions(outcomes)
    return OpenAIProvider(SimpleNamespace(chat=SimpleNamespace(completions=comp))), comp


def image_adapter(outcomes: list):
    images = FakeImages(outcomes)
    return OpenAIImageProvider(SimpleNamespace(images=images)), images


def call_text(p: OpenAIProvider):
    return p.complete(LLMRequest(provider="openai", model="gpt-test", temperature=None,
                                 messages=[{"role": "user", "content": "프롬프트"}], timeout_sec=12.0,
                                 response_schema=None, metadata={"task_id": "T-C1"}))


def call_image(p: OpenAIImageProvider):
    return p.create(ImageRequest(provider="openai", model="gpt-image-test", prompt="그려라", image=None,
                                 size=None, quality=None, timeout_sec=120.0, metadata={"task_id": "T-B2"}))


ADAPTERS = {"글": (text_adapter, call_text), "이미지": (image_adapter, call_image)}


def raised(kind: str, error: Exception) -> ProviderError:
    make, call = ADAPTERS[kind]
    p, _ = make([error])
    with pytest.raises(ProviderError) as e:
        call(p)
    return e.value


both = pytest.mark.parametrize("kind", list(ADAPTERS))


# ── 오류 코드 ─────────────────────────────────────────────
@both
def test_code_from_sdk_body(kind):
    e = raised(kind, status_error(429, body=err_body("insufficient_quota"), cls=openai.RateLimitError))
    assert (e.status, e.code) == (429, "insufficient_quota")


@both
def test_code_from_nested_error_body(kind):
    # 본문이 바깥 객체 그대로 와도({"error": {...}}) 읽는다 — SDK의 e.code는 None이다
    err = status_error(503, body={"error": err_body("server_is_overloaded")})
    assert err.code is None
    e = raised(kind, err)
    assert (e.status, e.code) == (503, "server_is_overloaded")


@both
@pytest.mark.parametrize("body", [None, {}, {"code": None}, {"error": None}, "그냥 글자 본문", ["x"], {"error": "x"}])
def test_code_absent(kind, body):
    e = raised(kind, status_error(500, body=body))
    assert e.status == 500 and e.code is None


@both
@pytest.mark.parametrize("code", ["Insufficient_Quota", "a" * 65, "rate-limit", "코드", "", "x y"])
def test_invalid_code_dropped(kind, code):
    e = raised(kind, status_error(429, body=err_body(code)))
    assert e.status == 429 and e.code is None


@both
def test_code_at_limit_length_kept(kind):
    e = raised(kind, status_error(400, body=err_body("a" * 64)))
    assert e.code == "a" * 64


# ── Retry-After ───────────────────────────────────────────
@both
@pytest.mark.parametrize("headers, expected", [
    ({"retry-after-ms": "1500", "retry-after": "7"}, 1.5),      # 밀리초 쪽이 우선
    ({"retry-after-ms": "250"}, 0.25),
    ({"retry-after": "7"}, 7.0),
    ({"Retry-After": "3"}, 3.0),                                # 헤더 이름 대소문자 무관
    ({"RETRY-AFTER-MS": "2000"}, 2.0),
    ({"retry-after": "2.5"}, 2.5),
    ({"retry-after": " 4 "}, 4.0),
    ({"retry-after": "0"}, 0.0),
    ({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # 날짜 형식은 무시
    ({"retry-after": "soon"}, None),
    ({"retry-after": ""}, None),
    ({"retry-after": "-1"}, None),
    ({"retry-after": "nan"}, None),
    ({"retry-after": "inf"}, None),
    ({"retry-after-ms": "-5"}, None),
    ({"retry-after-ms": "abc", "retry-after": "4"}, 4.0),       # 밀리초 값이 잘못되면 초 헤더를 본다
    ({}, None),
])
def test_retry_after_headers(kind, headers, expected):
    e = raised(kind, status_error(429, body=err_body("rate_limit_exceeded"), headers=headers))
    assert e.retry_after_sec == expected
    assert e.code == "rate_limit_exceeded"


# ── 읽다가 나는 오류는 None — 어댑터가 다른 예외를 내지 않는다 ──
class Exploding:
    def get(self, *_a, **_k):
        raise RuntimeError("헤더 읽기 실패")

    def __getitem__(self, _k):
        raise RuntimeError("헤더 읽기 실패")


class BadCode:
    def __str__(self) -> str:
        raise RuntimeError("코드 읽기 실패")


@both
def test_extraction_errors_become_none(kind):
    err = status_error(429, body=err_body("insufficient_quota"))
    err.response = SimpleNamespace(headers=Exploding())   # 헤더 읽기가 터진다
    err.code = BadCode()                                    # 글자가 아닌 코드
    err.body = {"error": Exploding()}                       # 본문도 이상하다
    e = raised(kind, err)
    assert (e.status, e.code, e.retry_after_sec) == (429, None, None)


@both
def test_missing_response_attribute(kind):
    err = status_error(502, body=None)
    del err.response
    e = raised(kind, err)
    assert (e.status, e.code, e.retry_after_sec) == (502, None, None)


# ── 메시지에 본문 · 헤더 값이 없다 ────────────────────────────
@both
def test_message_has_status_only(kind):
    err = status_error(429, body=err_body("insufficient_quota"),
                       headers={"retry-after": "37", "x-request-id": "req-SECRET-ID"}, cls=openai.RateLimitError)
    e = raised(kind, err)
    text = str(e)
    assert SECRET not in text and "37" not in text and "insufficient_quota" not in text and "req-SECRET" not in text
    assert text == ("OpenAI 오류 429" if kind == "글" else "OpenAI 이미지 오류 429")
    assert e.__cause__ is None and e.__suppress_context__   # from None
    assert SECRET not in repr(e)


# ── 시간 초과 · 연결 오류 변환은 그대로 ────────────────────────
@both
@pytest.mark.parametrize("error, expected", [
    (openai.APITimeoutError(request=REQ), TimeoutError),
    (openai.APIConnectionError(request=REQ), ConnectionError),
])
def test_transport_mapping_unchanged(kind, error, expected):
    make, call = ADAPTERS[kind]
    p, _ = make([error])
    with pytest.raises(expected):
        call(p)


# ── 어댑터 + tools: 한도 · Retry-After가 tools 규칙으로 이어진다 ──
def tools_with(text=None, image=None) -> tuple[Tools, CallSink, list]:
    sink, sleeps = CallSink(), []
    cfg = ToolsConfig(agent="조율", provider="openai", model="gpt-test", temperature=None, timeout_sec=12,
                      retry_count=5, retry_interval_sec=2.0, image_provider="openai", image_model="gpt-image-test")
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-X", providers={"openai": text} if text else {},
                       sink=sink, now=utc_now, sleep=sleeps.append, rand=lambda: 0.0,
                       image_providers={"openai": image} if image else {})
    return Tools(cfg, ctx), sink, sleeps


def run_through_tools(kind: str, outcomes: list):
    make, _ = ADAPTERS[kind]
    p, fake = make(outcomes)
    t, sink, sleeps = tools_with(text=p) if kind == "글" else tools_with(image=p)
    call = (lambda: t.llm([{"role": "user", "content": "x"}], purpose="시험")) if kind == "글" \
        else (lambda: t.image("그려라", purpose="시험"))
    return call, fake, sink, sleeps


@both
def test_billing_code_through_tools_one_try(kind):
    err = status_error(429, body=err_body("insufficient_quota"), headers={"retry-after": "5"},
                       cls=openai.RateLimitError)
    call, fake, sink, sleeps = run_through_tools(kind, [err, err, err])
    with pytest.raises(ToolCallExhausted) as e:
        call()
    x = e.value
    assert (x.tries, x.error_kind, x.billing_limit, x.code) == (1, "일시", True, "insufficient_quota")
    assert len(fake.calls) == 1 and sleeps == []
    [log] = sink.drain()
    assert log.tries[0].detail == "status=429 code=insufficient_quota"
    assert SECRET not in log.model_dump_json() and SECRET not in str(x)


@both
def test_retry_after_through_tools(kind):
    err = status_error(429, body=err_body("rate_limit_exceeded"), headers={"retry-after-ms": "9000"},
                       cls=openai.RateLimitError)
    ok = "답" if kind == "글" else SimpleNamespace(data=[SimpleNamespace(b64_json="iVBORw0KGgo=")], usage=None)
    call, fake, sink, sleeps = run_through_tools(kind, [err, ok])
    call()
    assert sleeps == [9.0] and len(fake.calls) == 2          # 계산 간격 2초보다 긴 Retry-After를 따른다
    [log] = sink.drain()
    assert log.tries[0].detail == "status=429 code=rate_limit_exceeded"
