"""OpenAI 호출처 어댑터 — SDK 클라이언트를 가짜로 바꿔 요청 모양과 오류 변환을 본다 (네트워크 없음)."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import httpx2
import openai
import pytest

from sbrain.agents.supervisor.tc1 import ItemDraft
from sbrain.orchestrator.errors import FormatError, ProviderError, ToolCallExhausted
from sbrain.orchestrator.openai_provider import OpenAIProvider
from sbrain.orchestrator.tools import CallSink, LLMRequest, Tools, ToolsConfig, ToolsContext

REQ = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


class FakeCompletions:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out))])


def provider(outcomes: list, **kw) -> tuple[OpenAIProvider, FakeCompletions]:
    comp = FakeCompletions(outcomes)
    return OpenAIProvider(SimpleNamespace(chat=SimpleNamespace(completions=comp)), **kw), comp


def request(schema: dict | None = None, **over) -> LLMRequest:
    base = dict(provider="openai", model="gpt-test", temperature=0.3,
                messages=[{"role": "user", "content": "안녕"}], timeout_sec=12.0,
                response_schema=schema, metadata={"task_id": "T-C1"})
    return LLMRequest(**{**base, **over})


def test_request_shape_with_json_schema():
    p, comp = provider(['{"a": 1}'])
    schema = ItemDraft.model_json_schema()
    assert p.complete(request(schema)).text == '{"a": 1}'
    call = comp.calls[0]
    assert (call["model"], call["temperature"], call["timeout"]) == ("gpt-test", 0.3, 12.0)
    assert "reasoning_effort" not in call
    assert call["messages"] == [{"role": "user", "content": "안녕"}]
    rf = call["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["name"] == "ItemDraft"
    assert rf["json_schema"]["schema"] == schema and rf["json_schema"]["strict"] is False


def test_reasoning_model_request_has_effort_and_no_temperature():
    p, comp = provider(["답"])
    assert p.complete(request(model="gpt-6-luna", temperature=None, reasoning_effort="low")).text == "답"
    call = comp.calls[0]
    assert call["model"] == "gpt-6-luna" and call["reasoning_effort"] == "low"
    assert "response_format" not in call and "temperature" not in call


@pytest.mark.parametrize("error, expected", [
    (openai.APITimeoutError(request=REQ), TimeoutError),
    (openai.APIConnectionError(request=REQ), ConnectionError),
])
def test_transport_errors(error, expected):
    p, _ = provider([error])
    with pytest.raises(expected):
        p.complete(request())


def test_status_error_keeps_status():
    p, _ = provider([openai.RateLimitError("rate", response=httpx2.Response(429, request=REQ), body=None)])
    with pytest.raises(ProviderError) as e:
        p.complete(request())
    assert e.value.status == 429


def test_empty_content_is_format_error():
    p, _ = provider([None])
    with pytest.raises(FormatError):
        p.complete(request())


def test_through_tools_retry_and_classification():
    bad = openai.BadRequestError("bad", response=httpx2.Response(400, request=REQ), body=None)
    p, comp = provider([None, bad, bad])
    cfg = ToolsConfig(agent="조율", provider="openai", model="gpt-test", temperature=0.3, timeout_sec=12,
                      retry_count=2, retry_interval_sec=0)
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-C1", providers={"openai": p}, sink=CallSink(),
                       now=datetime.now, sleep=lambda s: None)
    with pytest.raises(ToolCallExhausted) as e:
        Tools(cfg, ctx).llm([{"role": "user", "content": "x"}], purpose="시험")
    assert e.value.error_kind == "입력" and len(comp.calls) == 3
    assert [t.outcome for t in ctx.sink.drain()[0].tries] == ["형식오류", "호출실패", "호출실패"]
