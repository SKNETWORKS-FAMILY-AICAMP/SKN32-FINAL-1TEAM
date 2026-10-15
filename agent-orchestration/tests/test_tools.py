"""tools — 호출 단위 재시도, 오류 분류, 형식 오류 두 경로, 스레드 안전, 기록에 내용 없음."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from sbrain.agents.stubs import Ack, FakeLLM
from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import FormatError, ProviderError, ToolCallExhausted
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext, classify_status


def make_tools(llm: FakeLLM, retry: int = 5) -> tuple[Tools, CallSink, list]:
    sink, sleeps = CallSink(), []
    cfg = ToolsConfig(agent="작성", provider="p", model="m-1", temperature=0.3, timeout_sec=42,
                      retry_count=retry, retry_interval_sec=2.0)
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-W1", providers={"p": llm}, sink=sink,
                       now=utc_now, sleep=sleeps.append, rand=lambda: 0.0)   # 무작위 지연 0 — 간격을 정확히 본다
    return Tools(cfg, ctx), sink, sleeps


def test_retry_then_success_logs_tries_without_content():
    llm = FakeLLM()
    llm.plan("T-W1", ["timeout", "rate_limit", "ok"])
    tools, sink, sleeps = make_tools(llm)
    assert tools.llm([{"role": "user", "content": "비밀 본문"}], schema=Ack).ok
    [log] = sink.drain()
    assert [t.outcome for t in log.tries] == ["응답지연", "호출실패", "성공"]
    assert sleeps == [2.0, 4.0]                                            # 일시 오류는 늘리는 간격
    assert "비밀 본문" not in log.model_dump_json()
    assert llm.requests[0].timeout_sec == 42 and llm.requests[0].temperature == 0.3


def test_exhausted_raises_with_kind():
    llm = FakeLLM()
    llm.plan("T-W1", ["bad_request"])
    tools, sink, sleeps = make_tools(llm)
    with pytest.raises(ToolCallExhausted) as e:
        tools.llm([], schema=Ack)
    assert (e.value.error, e.value.error_kind, e.value.tries) == ("호출실패", "입력", 1)   # 입력 오류는 재시도하지 않는다
    assert sink.drain()[0].final_outcome == "소진" and sleeps == []
    llm.plan("T-W1", ["timeout"] * 6)
    with pytest.raises(ToolCallExhausted) as e:
        tools.llm([], schema=Ack)
    assert (e.value.error, e.value.error_kind, e.value.tries) == ("응답지연", "일시", 6)


def test_format_error_by_schema_and_by_task_parse():
    llm = FakeLLM()
    llm.plan("T-W1", ["bad_json", "ok"])
    tools, sink, _ = make_tools(llm)
    assert tools.llm([], schema=Ack).ok
    assert [t.outcome for t in sink.drain()[0].tries] == ["형식오류", "성공"]

    calls = {"n": 0}

    def parse(value):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FormatError("Task가 파싱 실패를 알림")
        return value
    tools.llm([], parse=parse)
    assert [t.outcome for t in sink.drain()[0].tries] == ["형식오류", "성공"]


def test_search_wraps_non_llm_calls_and_passes_timeout():
    tools, sink, _ = make_tools(FakeLLM())
    seen = []
    state = {"n": 0}

    def fn(timeout):
        seen.append(timeout)
        state["n"] += 1
        if state["n"] == 1:
            raise ProviderError("down", status=503)
        return ["A01"]
    assert tools.search("임베딩", fn) == ["A01"]
    log = sink.drain()[0]
    assert log.call_type == "search" and log.model is None and seen == [42, 42]


def test_search_retries_option_applies_to_that_call_only():
    """search(retries=n)는 그 호출만 처음 포함 n + 1번 시도한다. 주지 않으면 설정 재시도 횟수(retry_count) 그대로다."""
    tools, sink, sleeps = make_tools(FakeLLM(), retry=5)
    attempts = {"짧게": 0, "기본": 0}

    def down(name):
        def fn(timeout):
            attempts[name] += 1
            raise ConnectionError("down")
        return fn
    with pytest.raises(ToolCallExhausted) as e:
        tools.search("짧게", down("짧게"), retries=2)
    assert e.value.tries == 3 and attempts["짧게"] == 3 and sleeps == [2.0, 4.0]   # 연결 오류 — 늘리는 간격
    [log] = sink.drain()
    assert log.final_outcome == "소진" and len(log.tries) == 3
    with pytest.raises(ToolCallExhausted) as e:
        tools.search("기본", down("기본"))
    assert e.value.tries == 6 and attempts["기본"] == 6 and tools.config.retry_count == 5
    with pytest.raises(ToolCallExhausted) as e:
        tools.search("없음", down("기본"), retries=0)
    assert e.value.tries == 1


def test_thread_safe_per_call_counts():
    llm = FakeLLM()
    for i in range(20):
        llm.plan("T-W1", ["timeout", "ok"], item_key=f"s{i}")
    tools, sink, _ = make_tools(llm)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: tools.for_item(f"s{i}").llm([], schema=Ack), range(20)))
    logs = sink.drain()
    assert len(logs) == 20
    assert all(len(l.tries) == 2 for l in logs)
    assert {l.item_key for l in logs} == {f"s{i}" for i in range(20)}


def test_classify_status():
    assert classify_status(None) == classify_status(429) == classify_status(503) == "일시"
    assert classify_status(400) == classify_status(413) == "입력"
    assert classify_status(401) == classify_status(404) == "운영"
