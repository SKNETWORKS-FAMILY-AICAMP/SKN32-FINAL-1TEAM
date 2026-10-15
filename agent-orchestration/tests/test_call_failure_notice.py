"""공고 서버 호출 실패 처리 (spec 2.2 · 2.3) — 실제 T-C2 · G-01의 네 API(수집 상태 · 공고 매칭 · 공고 상세 · 자격 판정).

- 408 · 429를 뺀 4xx와 3xx는 한 번만 보낸다(입력 · 운영 — 분류표 그대로).
- 408 · 429 · 5xx · 시간 초과 · 연결 오류는 재시도 간격(2초) 고정으로 최대 6번 — 늘리는 간격 · 무작위 지연 없음(backoff=False).
- 공고 없음(404 + NOTICE_NOT_FOUND)은 값으로 받는 성공 호출이다(재시도 없음).

가짜 전송(tests/notice_fake.py)만 쓴다. 네트워크 · 실제 대기 없음(sleep · rand 주입).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from notice_fake import FAKE_URL, NOT_FOUND, FakeNoticeServer, company, item

from sbrain.agents.notice import NoticeClient, make_g01, make_tc2
from sbrain.contracts import tasks as c
from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import ResourceNotFound, ToolCallExhausted
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

INTERVAL = 2.0
AID = "kstartup:A01"
AID_PATH = "/api/notices/kstartup%3AA01"

# (어느 Task, 목적, 메서드, 경로)
APIS = [
    ("T-C2", "수집 상태", "GET", "/api/collection_status"),
    ("T-C2", "공고 매칭", "POST", "/api/match"),
    ("G-01", "공고 상세", "GET", AID_PATH),
    ("G-01", "자격 판정", "POST", AID_PATH + "/eligibility"),
]
API_IDS = [a[1] for a in APIS]


class Waits:
    """주입한 sleep — 기다린 초를 남긴다(실제로 기다리지 않는다)."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, sec: float) -> None:
        self.waits.append(sec)


def make_tools(task_id: str, waits: Waits) -> tuple[Tools, CallSink]:
    """운영 기본값과 같은 재시도(5번 · 간격 2초). 무작위는 늘 최대에 가깝게 — 고정 간격이면 더해지지 않아야 한다."""
    sink = CallSink()
    cfg = ToolsConfig(agent="조율", provider=None, model=None, temperature=None, timeout_sec=30.0,
                      retry_count=5, retry_interval_sec=INTERVAL)
    ctx = ToolsContext(run_id="r1", execution_id="e1", task_id=task_id, providers={}, sink=sink,
                       now=utc_now, sleep=waits, rand=lambda: 0.99)
    return Tools(cfg, ctx), sink


def run_task(task_id: str, transport: Any, tools: Tools) -> Any:
    """실제 T-C2 또는 G-01을 가짜 전송으로 돌린다."""
    client = NoticeClient(FAKE_URL, transport=transport)
    if task_id == "T-C2":
        inp = c.TC2In(item_spec=item(), company_info=company(), today=date(2026, 9, 26), top_k=10, offset=0)
        return make_tc2(client)(inp, tools)
    inp = c.G01In(company_info=company(), today=date(2026, 9, 26), announcement_id=AID)
    return make_g01(client)(inp, tools)


def exhausted(task_id: str, method: str, path: str, failure: Any) -> tuple[ToolCallExhausted, FakeNoticeServer,
                                                                           Waits, CallSink]:
    server = FakeNoticeServer()
    server.raw[(method, path)] = failure
    waits = Waits()
    tools, sink = make_tools(task_id, waits)
    with pytest.raises(ToolCallExhausted) as e:
        run_task(task_id, server, tools)
    return e.value, server, waits, sink


def sent(server: FakeNoticeServer, method: str, path: str) -> int:
    return server.paths().count((method, path))


# ── 한 번만 보내는 실패 ────────────────────────────────
@pytest.mark.parametrize("status, kind", [
    (400, "입력"), (413, "입력"), (422, "입력"),
    (401, "운영"), (403, "운영"), (404, "운영"), (409, "운영"),
    (301, "운영"), (302, "운영"), (307, "운영"),
])
@pytest.mark.parametrize("task_id, purpose, method, path", APIS, ids=API_IDS)
def test_input_and_operation_errors_are_sent_once(task_id, purpose, method, path, status, kind):
    e, server, waits, sink = exhausted(task_id, method, path, (status, b""))
    assert e.tries == 1
    assert e.error == "호출실패"
    assert e.error_kind == kind
    assert e.billing_limit is False
    assert sent(server, method, path) == 1
    assert waits.waits == []
    log = [g for g in sink.drain() if g.purpose == purpose][0]
    assert log.call_type == "search"
    assert log.final_outcome == "소진"
    assert len(log.tries) == 1


# ── 2초 고정으로 6번 보내는 실패 ────────────────────────
TRANSIENT = [
    pytest.param((408, b""), "호출실패", id="408"),
    pytest.param((429, b""), "호출실패", id="429"),
    pytest.param((500, b""), "호출실패", id="500"),
    pytest.param((502, b""), "호출실패", id="502"),
    pytest.param((503, b""), "호출실패", id="503"),
    pytest.param(ConnectionError("공고 서버 연결 실패: ConnectionRefusedError"), "호출실패", id="연결오류"),
    pytest.param(TimeoutError("공고 서버 응답 시간 초과"), "응답지연", id="시간초과"),
    pytest.param((200, b"not json"), "형식오류", id="형식오류"),
]


@pytest.mark.parametrize("failure, error", TRANSIENT)
@pytest.mark.parametrize("task_id, purpose, method, path", APIS, ids=API_IDS)
def test_transient_errors_retry_six_times_with_fixed_interval(task_id, purpose, method, path, failure, error):
    e, server, waits, sink = exhausted(task_id, method, path, failure)
    assert e.tries == 6
    assert e.error == error
    assert e.error_kind == "일시"
    assert sent(server, method, path) == 6
    # 늘리지 않고 무작위도 더하지 않는다 — rand가 0.99여도 정확히 2초
    assert waits.waits == [INTERVAL] * 5
    log = [g for g in sink.drain() if g.purpose == purpose][0]
    assert log.final_outcome == "소진"
    assert len(log.tries) == 6


@pytest.mark.parametrize("task_id, purpose, method, path", APIS, ids=API_IDS)
def test_transient_then_success_waits_fixed_interval(task_id, purpose, method, path):
    """두 번 실패(429 · 503) 뒤 성공 — 두 번 모두 2초씩 기다리고 결과는 정상."""
    server = FakeNoticeServer()
    failures = [(429, b""), (503, b"")]
    original = server.__call__

    def transport(m: str, url: str, body: bytes | None, timeout: float) -> tuple[int, bytes]:
        if (m, url[len(FAKE_URL):]) == (method, path) and failures:
            server.calls.append((m, url[len(FAKE_URL):], None))
            return failures.pop(0)
        return original(m, url, body, timeout)

    waits = Waits()
    tools, sink = make_tools(task_id, waits)
    out = run_task(task_id, transport, tools)
    if task_id == "T-C2":
        assert out.collection_status == "정상"
        assert len(out.candidates) == 3
    else:
        assert out.gate_result.passed is True
    assert waits.waits == [INTERVAL, INTERVAL]
    log = [g for g in sink.drain() if g.purpose == purpose][0]
    assert log.final_outcome == "성공"
    assert len(log.tries) == 3


# ── 공고 없음은 값으로 받는 성공 호출 ──────────────────────
@pytest.mark.parametrize("purpose, method, path", [
    ("공고 상세", "GET", AID_PATH),
    ("자격 판정", "POST", AID_PATH + "/eligibility"),
])
def test_not_found_is_a_successful_call_without_retry(purpose, method, path):
    server = FakeNoticeServer()
    server.raw[(method, path)] = NOT_FOUND
    waits = Waits()
    tools, sink = make_tools("G-01", waits)
    with pytest.raises(ResourceNotFound):
        run_task("G-01", server, tools)
    assert sent(server, method, path) == 1
    assert waits.waits == []
    log = [g for g in sink.drain() if g.purpose == purpose][0]
    assert log.final_outcome == "성공"
    assert len(log.tries) == 1


def test_tc2_success_path_unchanged():
    """정상 응답이면 대기 없이 한 번씩 — 수집 상태 → 공고 매칭 순서."""
    server = FakeNoticeServer()
    waits = Waits()
    tools, sink = make_tools("T-C2", waits)
    out = run_task("T-C2", server, tools)
    assert server.paths() == [("GET", "/api/collection_status"), ("POST", "/api/match")]
    assert waits.waits == []
    assert len(out.candidates) == 3
    assert [g.final_outcome for g in sink.drain()] == ["성공", "성공"]


def test_g01_success_path_unchanged():
    server = FakeNoticeServer()
    waits = Waits()
    tools, sink = make_tools("G-01", waits)
    out = run_task("G-01", server, tools)
    assert server.paths() == [("GET", AID_PATH), ("POST", AID_PATH + "/eligibility")]
    assert waits.waits == []
    assert out.gate_result.passed is True
    assert [g.final_outcome for g in sink.drain()] == ["성공", "성공"]
