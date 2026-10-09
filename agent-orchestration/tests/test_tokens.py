"""토큰 사용량 — 시도별 기록(형식 오류 응답 포함) · 호출 합계 · 실행 합계, OpenAI usage 옮기기, 관리자 조회."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import make_app, pre_input, to_screen9, tok
from pydantic import BaseModel
from sqlalchemy import text

from sbrain.agents.stubs import StubScenario
from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import FormatError, ToolCallExhausted
from sbrain.orchestrator.openai_provider import OpenAIProvider
from sbrain.orchestrator.tools import (
    CallSink, LLMRequest, LLMResponse, TokenUsage, Tools, ToolsConfig, ToolsContext,
)
from sbrain.store_sql import SqlStore

U = TokenUsage(input_tokens=100, cached_input_tokens=40, output_tokens=30, reasoning_tokens=10)
V = TokenUsage(input_tokens=7, cached_input_tokens=None, output_tokens=3, reasoning_tokens=None)


class Ack(BaseModel):
    ok: bool


class Script:
    """정한 순서대로 응답하는 호출처 (예외면 올린다)."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)

    def complete(self, request: LLMRequest):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tools(provider, retry: int = 2) -> tuple[Tools, CallSink]:
    cfg = ToolsConfig(agent="조율", provider="p", model="m", temperature=None, timeout_sec=10, retry_count=retry,
                      retry_interval_sec=0)
    sink = CallSink()
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-C1", providers={"p": provider}, sink=sink,
                       now=utc_now, sleep=lambda s: None)
    return Tools(cfg, ctx), sink


# ── tools: 시도별 · 호출 합계 ────────────────────────────
def test_success_records_usage_per_try_and_total():
    t, sink = tools(Script(LLMResponse('{"ok": true}', U)))
    assert t.llm([{"role": "user", "content": "x"}], schema=Ack).ok
    [log] = sink.drain()
    assert tok(log.tries[0]) == tok(log) == (100, 40, 30, 10)


def test_format_error_response_cost_is_kept():
    """형식 오류로 버린 응답의 사용량도 남긴다 — 스키마 검사 전에 기록."""
    t, sink = tools(Script(LLMResponse("not json", U), LLMResponse('{"ok": true}', V)))
    t.llm([{"role": "user", "content": "x"}], schema=Ack)
    [log] = sink.drain()
    assert [(x.outcome, tok(x)) for x in log.tries] == [("형식오류", (100, 40, 30, 10)), ("성공", (7, None, 3, None))]
    assert tok(log) == (107, 40, 33, 10)                                        # 없는 항목은 있는 것만 더한다


def test_exhausted_call_sums_every_try():
    t, sink = tools(Script(*[LLMResponse("not json", U)] * 3))
    with pytest.raises(ToolCallExhausted):
        t.llm([{"role": "user", "content": "x"}], schema=Ack)
    [log] = sink.drain()
    assert log.final_outcome == "소진" and tok(log) == (300, 120, 90, 30)


def test_parse_error_and_provider_format_error_keep_usage():
    calls = []

    def parse(value):
        calls.append(value)
        if len(calls) == 1:
            raise FormatError("parse 실패")
        return value
    t, sink = tools(Script(FormatError("빈 응답", usage=V), LLMResponse("a", U), LLMResponse("b", U)))
    assert t.llm([{"role": "user", "content": "x"}], parse=parse) == "b"
    [log] = sink.drain()
    assert [tok(x)[0] for x in log.tries] == [7, 100, 100]                      # 빈 응답 · parse 오류도 비용 기록


def test_provider_without_usage_and_timeouts_stay_none():
    t, sink = tools(Script(TimeoutError(), '{"ok": true}'))                     # 문자열만 돌려주는 호출처
    t.llm([{"role": "user", "content": "x"}], schema=Ack)
    [log] = sink.drain()
    assert [tok(x) for x in log.tries] == [(None,) * 4, (None,) * 4] and tok(log) == (None,) * 4


# ── OpenAI usage 옮기기 ───────────────────────────────────
def openai_with(content, usage):
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=usage)
    comp = SimpleNamespace(create=lambda **kw: resp)
    return OpenAIProvider(SimpleNamespace(chat=SimpleNamespace(completions=comp)))


def request() -> LLMRequest:
    return LLMRequest(provider="openai", model="gpt-6-luna", temperature=None, messages=[], timeout_sec=10,
                      response_schema=None, metadata={"task_id": "T-C1"})


def test_openai_usage_mapping():
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=50,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=100),
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=20))
    reply = openai_with("답", usage).complete(request())
    assert reply.text == "답" and reply.usage == TokenUsage(120, 100, 50, 20)
    bare = SimpleNamespace(prompt_tokens=5, completion_tokens=1, prompt_tokens_details=None,
                           completion_tokens_details=None)
    assert openai_with("답", bare).complete(request()).usage == TokenUsage(5, None, 1, None)
    assert openai_with("답", None).complete(request()).usage is None
    with pytest.raises(FormatError) as e:                                        # 빈 응답도 비용은 남긴다
        openai_with(None, usage).complete(request())
    assert e.value.usage == TokenUsage(120, 100, 50, 20)


# ── 실행 합계 · 관리자 조회 · 저장 ─────────────────────────
def test_execution_total_and_admin_views(clock):
    app = make_app(clock)
    app.llm.usage["T-C1"] = U
    app.llm.plan("T-C1", ["bad_json", "ok"])                                    # 형식 오류 뒤 성공
    res = app.orchestrator.start_run("acc-1", pre_input(), project_id="701")
    rec = next(r for r in app.store.executions(res.run_id) if r.task_id == "T-C1")
    assert tok(rec) == (200, 80, 60, 20)
    [row] = app.orchestrator.admin_executions(task_id="T-C1")
    assert tok(row.tokens) == (200, 80, 60, 20)
    [call] = app.orchestrator.admin_calls(rec.execution_id)
    assert [tok(t.tokens) for t in call.tries] == [(100, 40, 30, 10)] * 2 and tok(call.tokens) == (200, 80, 60, 20)
    t2 = next(r for r in app.store.executions(res.run_id) if r.task_id == "T-C2")
    assert tok(t2) == (None,) * 4                                                # 검색 호출 — 사용량 없음
    if isinstance(app.store, SqlStore):                                          # 조회용 컬럼에도 합계가 있다
        with app.store.engine.connect() as conn:
            cols = conn.execute(text("SELECT input_tokens, cached_input_tokens, output_tokens, reasoning_tokens "
                                     "FROM orch_executions WHERE execution_id = :e"), {"e": rec.execution_id}).one()
            calls = conn.execute(text("SELECT input_tokens FROM orch_call_logs WHERE execution_id = :e"),
                                 {"e": rec.execution_id}).scalar()
        assert tuple(cols) == (200, 80, 60, 20) and calls == 200


def test_proofread_sentences_are_summed(clock):
    app = make_app(clock, StubScenario(tp1_targets=4))
    app.llm.usage["T-P2"] = V
    rid = to_screen9(app)
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    tp2 = next(r for r in app.store.executions(rid) if r.task_id == "T-P2")
    calls = [c for c in app.store.call_logs(rid) if c.task_id == "T-P2"]
    assert len({c.item_key for c in calls}) == 4                                # 문장별 호출 (병렬)
    assert tp2.input_tokens == sum(c.input_tokens for c in calls) == 7 * sum(len(c.tries) for c in calls)
    assert tp2.cached_input_tokens is None
