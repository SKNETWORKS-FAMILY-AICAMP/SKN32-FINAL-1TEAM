"""호출 실패 처리 — 엔진 재시도 규칙(tools), 설정 칸, 운영 로그 errorCode, 가짜 호출처 결과 값, 스텁 T-V2 한도.

- 결제 · 한도 코드 6종은 상태 코드와 관계없이 재시도 없이 '일시'(재개 대기로).
- 입력 · 운영 응답 코드 오류는 재시도하지 않는다.
- 일시 오류는 늘리는 간격(2 · 4 · 8 · 16 · 32초 × (1 + 무작위 0 ~ 25%)), 형식 오류 · 파일 창구 · backoff=False 검색은 2초 고정.
- Retry-After는 계산 값과 그 값 중 큰 쪽(상한 60초), 한 호출의 대기 합은 90초(T-C1 45초 — 설정 키별) 안.
- 시도 설명 'status=N code=X', 정규식 밖 코드는 버림, 응답 메시지는 기록 · 예외에 없음.
네트워크 · 실제 대기 없음(sleep · rand 주입).
"""
from __future__ import annotations

import logging
import random
from types import SimpleNamespace

import pytest
from conftest import make_app, pre_input, start_and_select, to_screen6
from flow_helpers import records_of_task, state

from sbrain.agents.stubs import Ack, FakeImage, FakeLLM
from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import (
    BILLING_LIMIT_CODES, FormatError, ProviderError, ToolCallExhausted, clean_error_code,
)
from sbrain.orchestrator.files import MemoryFileStore
from sbrain.orchestrator.runlog import RUN_LOGGER
from sbrain.orchestrator.settings import PROVISIONAL, REWRITE_SETTING_KEY, RetrySettings, Settings
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

BILLING = sorted(BILLING_LIMIT_CODES)
SECRET = "응답 본문에 든 비밀 설명"


def make_tools(*, rand=lambda: 0.0, providers=None, files=None, **over) -> tuple[Tools, CallSink, list[float]]:
    sink, sleeps = CallSink(), []
    cfg = ToolsConfig(**{"agent": "작성", "provider": "p", "model": "m-1", "temperature": None, "timeout_sec": 30,
                         "retry_count": 5, "retry_interval_sec": 2.0, **over})
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-W1", providers=providers or {"p": FakeLLM()},
                       sink=sink, now=utc_now, sleep=sleeps.append, rand=rand,
                       files=files, run_progress=(lambda: "실행") if files is not None else None)
    return Tools(cfg, ctx), sink, sleeps


def failing(*errors):
    """차례로 예외를 올리고, 다 쓰면 'ok'를 돌려주는 search 함수."""
    queue = list(errors)

    def fn(timeout):
        if queue:
            raise queue.pop(0)
        return "ok"
    return fn


def exhaust(tools: Tools, *errors, **kw) -> ToolCallExhausted:
    with pytest.raises(ToolCallExhausted) as e:
        tools.search("검색", failing(*errors), **kw)
    return e.value


# ── 오류 코드 정리 · 예외 칸 ─────────────────────────────
def test_error_code_must_match_pattern():
    assert clean_error_code("insufficient_quota") == "insufficient_quota"
    assert clean_error_code("a" * 64) == "a" * 64
    for bad in ("a" * 65, "Bad", "rate-limit", "quota\n", "", " x", None, 429, "코드"):
        assert clean_error_code(bad) is None, bad
    assert ProviderError("x", status=429, code="Rate Limit!").code is None
    e = ProviderError("x", status=429, code="slow_down", retry_after_sec=3.5)
    assert (e.status, e.code, e.retry_after_sec) == (429, "slow_down", 3.5)
    assert ProviderError("x").code is None and ProviderError("x").retry_after_sec is None
    for bad in (-1, float("nan"), float("inf"), "3"):
        assert ProviderError("x", retry_after_sec=bad).retry_after_sec is None


def test_billing_codes_are_six():
    assert BILLING_LIMIT_CODES == frozenset({
        "credit_balance_exhausted", "organization_spend_limit_exceeded", "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded", "insufficient_quota", "billing_hard_limit_reached"})


def test_exhausted_defaults_and_message_shape():
    e = ToolCallExhausted(error="호출실패", error_kind="일시", tries=6, call_id="c", detail="status=503")
    assert (e.code, e.billing_limit, e.partial) == (None, False, None)
    assert str(e) == "호출실패/일시 after 6 tries: status=503"


# ── 결제 · 한도 · 입력 · 운영 ─────────────────────────────
@pytest.mark.parametrize("status", [429, 400])
@pytest.mark.parametrize("code", BILLING)
def test_billing_codes_stop_at_once_as_transient(code, status):
    tools, sink, sleeps = make_tools()
    e = exhaust(tools, ProviderError(SECRET, status=status, code=code))
    assert (e.error, e.error_kind, e.tries, e.code, e.billing_limit) == ("호출실패", "일시", 1, code, True)
    assert e.detail == f"status={status} code={code}" and sleeps == []
    [log] = sink.drain()
    assert log.final_outcome == "소진" and [t.detail for t in log.tries] == [f"status={status} code={code}"]
    assert log.error_kind == "일시"


@pytest.mark.parametrize("status, kind", [(400, "입력"), (413, "입력"), (422, "입력"),
                                          (401, "운영"), (403, "운영"), (404, "운영"), (409, "운영"),
                                          (302, "운영")])
def test_input_and_operation_errors_are_not_retried(status, kind):
    tools, sink, sleeps = make_tools()
    e = exhaust(tools, ProviderError(SECRET, status=status), ProviderError(SECRET, status=status))
    assert (e.error, e.error_kind, e.tries, e.billing_limit, e.code) == ("호출실패", kind, 1, False, None)
    assert e.detail == f"status={status}" and sleeps == []


def test_other_codes_are_kept_in_detail_and_last_try_code():
    tools, sink, sleeps = make_tools()
    e = exhaust(tools, ProviderError(SECRET, status=429, code="rate_limit_exceeded"),
                ProviderError(SECRET, status=503, code="server_is_overloaded"), *[TimeoutError()] * 4)
    assert e.tries == 6 and e.code is None and e.billing_limit is False      # 마지막 시도는 시간 초과 — 코드 없음
    [log] = sink.drain()
    assert [t.detail for t in log.tries][:3] == ["status=429 code=rate_limit_exceeded",
                                                 "status=503 code=server_is_overloaded", "timeout"]
    tools, sink, _ = make_tools()
    e = exhaust(tools, *[ProviderError(SECRET, status=503, code="server_is_overloaded")] * 6)
    assert e.code == "server_is_overloaded" and e.billing_limit is False
    assert e.detail == "status=503 code=server_is_overloaded"


def test_response_message_never_recorded():
    tools, sink, _ = make_tools()
    e = exhaust(tools, ProviderError(SECRET, status=429, code="insufficient_quota"))
    assert SECRET not in str(e) and SECRET not in repr(e)
    assert SECRET not in sink.drain()[0].model_dump_json()


# ── 대기 간격 ─────────────────────────────────────────
def test_backoff_intervals_exact_without_jitter():
    tools, _, sleeps = make_tools(rand=lambda: 0.0)
    e = exhaust(tools, *[ProviderError("x", status=503)] * 6)
    assert e.tries == 6 and sleeps == [2.0, 4.0, 8.0, 16.0, 32.0]


def test_backoff_jitter_with_injected_rand():
    values = iter([0.0, 0.4, 0.8, 0.2, 0.5])
    tools, _, sleeps = make_tools(rand=lambda: next(values))
    exhaust(tools, TimeoutError(), ConnectionError(), OSError(), ProviderError("x", status=None),
            ProviderError("x", status=429), ProviderError("x", status=502))
    assert sleeps == pytest.approx([2.0, 4.0 * 1.1, 8.0 * 1.2, 16.0 * 1.05, 32.0 * 1.125])


def test_backoff_jitter_range_with_default_random():
    sink, sleeps = CallSink(), []
    cfg = ToolsConfig(agent="작성", provider="p", model="m", temperature=None, timeout_sec=30, retry_count=5,
                      retry_interval_sec=2.0)
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T", providers={}, sink=sink, now=utc_now,
                       sleep=sleeps.append)
    assert ctx.rand is random.random
    with pytest.raises(ToolCallExhausted):
        Tools(cfg, ctx).search("검색", failing(*[TimeoutError()] * 6))
    for n, wait in enumerate(sleeps):
        base = 2.0 * 2 ** n
        assert base <= wait <= base * 1.25


def test_format_error_waits_fixed_two_seconds():
    tools, _, sleeps = make_tools(rand=lambda: 0.9)
    e = exhaust(tools, *[FormatError("빈 응답")] * 6)
    assert e.error == "형식오류" and sleeps == [2.0] * 5


def test_retry_number_counts_all_failures():
    """n은 앞 시도의 실패 종류와 관계없이 센다 — 형식 오류(2초 고정) 뒤 429면 4초 × (1 + 무작위)."""
    tools, _, sleeps = make_tools(rand=lambda: 0.4)
    assert tools.search("검색", failing(FormatError("빈 응답"), ProviderError("x", status=429))) == "ok"
    assert sleeps == pytest.approx([2.0, 4.4])


def test_search_without_backoff_waits_fixed():
    tools, _, sleeps = make_tools(rand=lambda: 0.9)
    e = exhaust(tools, *[ConnectionError()] * 3, *[ProviderError("x", status=503)] * 3, backoff=False)
    assert e.tries == 6 and sleeps == [2.0] * 5
    tools, _, sleeps = make_tools(rand=lambda: 0.0)
    exhaust(tools, *[ConnectionError()] * 3, retries=2)                     # 호출별 재시도 횟수에도 같은 규칙
    assert sleeps == [2.0, 4.0]


class BrokenStore(MemoryFileStore):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def write(self, key, data, meta):
        raise self.error


@pytest.mark.parametrize("error", [OSError("disk"), TimeoutError()])
def test_file_call_failures_wait_fixed(error):
    tools, sink, sleeps = make_tools(rand=lambda: 0.9, files=BrokenStore(error))
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.put("a.svg", b"<svg/>", "image/svg+xml")
    assert e.value.tries == 6 and sleeps == [2.0] * 5 and e.value.error_kind == "일시"


def test_zero_interval_does_not_sleep():
    tools, _, sleeps = make_tools(retry_interval_sec=0)
    exhaust(tools, *[TimeoutError()] * 6)
    assert sleeps == []


# ── Retry-After · 대기 합 상한 ─────────────────────────
def test_retry_after_larger_wins_and_is_capped():
    tools, _, sleeps = make_tools()
    assert tools.search("검색", failing(ProviderError("x", status=429, retry_after_sec=10.0),
                                        ProviderError("x", status=429, retry_after_sec=1.0),
                                        ProviderError("x", status=429, retry_after_sec=75.0))) == "ok"
    assert sleeps == [10.0, 4.0, 60.0]                                            # 큰 쪽, 상한 60초


def test_wait_cap_stops_remaining_retries():
    tools, sink, sleeps = make_tools()
    e = exhaust(tools, *[ProviderError("x", status=429, code="rate_limit_exceeded", retry_after_sec=60.0)] * 6)
    assert e.tries == 2 and sleeps == [60.0]                                      # 60 + 60 > 90 — 소진
    assert e.code == "rate_limit_exceeded" and e.error_kind == "일시"
    assert len(sink.drain()[0].tries) == 2


def test_first_wait_over_cap_exhausts_without_retry():
    tools, _, sleeps = make_tools(wait_cap_sec=45.0)
    e = exhaust(tools, *[ProviderError("x", status=503, retry_after_sec=50.0)] * 6)
    assert e.tries == 1 and sleeps == []


def test_tc1_cap_45_cuts_backoff():
    tools, _, sleeps = make_tools(wait_cap_sec=45.0)
    e = exhaust(tools, *[TimeoutError()] * 6)
    assert e.tries == 5 and sleeps == [2.0, 4.0, 8.0, 16.0]                      # 30 + 32 > 45


def test_tools_config_defaults():
    cfg = ToolsConfig(agent="a", provider=None, model=None, temperature=None, timeout_sec=1, retry_count=5,
                      retry_interval_sec=2.0)
    assert (cfg.backoff_multiplier, cfg.jitter_ratio, cfg.retry_after_cap_sec, cfg.wait_cap_sec) == (2.0, 0.25, 60.0,
                                                                                                    90.0)


# ── 설정 ─────────────────────────────────────────────
def test_retry_settings_defaults_and_old_snapshot():
    r = RetrySettings()
    assert (r.backoff_multiplier, r.jitter_ratio, r.retry_after_cap_sec, r.wait_cap_sec, r.wait_cap_by_key) == (
        2.0, 0.25, 60.0, 90.0, {"T-C1": 45.0})
    dumped = Settings().dump()["retry"]
    assert {"backoffMultiplier", "jitterRatio", "retryAfterCapSec", "waitCapSec", "waitCapByKey"} <= set(dumped)
    old = Settings.model_validate({"retry": {"retryCount": 5, "retryIntervalSec": 2.0}})   # 새 칸 없는 옛 사본
    assert old.retry.wait_cap_by_key == {"T-C1": 45.0} and old.retry.wait_cap_sec == 90.0
    again = Settings.model_validate(Settings().dump())
    assert again.retry == Settings().retry
    # 값은 기준 문서 시트 1 '재시도 간격'이 정해 잠정이 아니다 (기능정의서 v1.11)
    for key in ("retry.retryIntervalSec", "retry.backoffMultiplier", "retry.jitterRatio", "retry.retryAfterCapSec",
                "retry.waitCapSec", "retry.waitCapByKey"):
        assert key not in PROVISIONAL


def test_engine_copies_retry_settings_by_key(clock):
    app = make_app(clock)
    ctx = SimpleNamespace(settings=Settings())
    tc1 = app.engine.agent_tools_config(ctx, "조율", "T-C1")
    assert (tc1.wait_cap_sec, tc1.backoff_multiplier, tc1.jitter_ratio, tc1.retry_after_cap_sec) == (45.0, 2.0, 0.25,
                                                                                                      60.0)
    assert app.engine.agent_tools_config(ctx, "조율", "T-C3").wait_cap_sec == 90.0
    assert app.engine.agent_tools_config(ctx, "조율", REWRITE_SETTING_KEY).wait_cap_sec == 90.0
    custom = Settings()
    custom.retry.wait_cap_by_key["T-C2"] = 10.0
    custom.retry.jitter_ratio = 0.0
    plain = app.engine._plain_tools_config(SimpleNamespace(settings=custom), app.registry.get("T-C2"))
    assert (plain.wait_cap_sec, plain.jitter_ratio) == (10.0, 0.0)


# ── 가짜 호출처 결과 값 ─────────────────────────────────
def test_fake_providers_quota_and_coded_outcomes():
    llm = FakeLLM()
    llm.plan("T-W1", ["quota"])
    tools, _, _ = make_tools(providers={"p": llm})
    with pytest.raises(ToolCallExhausted) as e:
        tools.llm([], schema=Ack)
    assert (e.value.tries, e.value.code, e.value.billing_limit, e.value.error_kind) == (1, "insufficient_quota",
                                                                                       True, "일시")
    llm.plan("T-W1", ["rate_limit_wait", "overloaded", "ok"])
    tools, sink, sleeps = make_tools(providers={"p": llm})
    assert tools.llm([], schema=Ack).ok
    assert [t.detail for t in sink.drain()[0].tries[:2]] == ["status=429 code=rate_limit_exceeded",
                                                             "status=503 code=server_is_overloaded"]
    assert sleeps == [10.0, 4.0]                                                  # Retry-After 10초 · 늘리는 간격

    image = FakeImage()
    image.plan("T-W1", ["quota"])
    cfg = dict(image_provider="img", image_model="im-1")
    sink, sleeps = CallSink(), []
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-W1", providers={}, sink=sink, now=utc_now,
                       sleep=sleeps.append, rand=lambda: 0.0, image_providers={"img": image})
    tools = Tools(ToolsConfig(agent="a", provider=None, model=None, temperature=None, timeout_sec=1, retry_count=5,
                              retry_interval_sec=2.0, **cfg), ctx)
    with pytest.raises(ToolCallExhausted) as e:
        tools.image("그림")
    assert (e.value.tries, e.value.billing_limit) == (1, True)
    image.plan("T-W1", ["overloaded", "ok"])
    assert tools.image("그림") == FakeImage.PNG


# ── 흐름 · 운영 로그 ─────────────────────────────────────
class Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def runlog():
    logger = logging.getLogger(RUN_LOGGER)
    h, level = Lines(), logger.level
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    yield h.lines
    logger.removeHandler(h)
    logger.setLevel(level)


def pairs(line: str) -> tuple[str, list[str], dict[str, str]]:
    action, _, rest = line.partition(" ")
    kv = [p.split("=", 1) for p in rest.split(" ")]
    return action, [k for k, _ in kv], {k: v for k, v in kv}


def lines_of(lines: list[str], action: str) -> list[tuple[list[str], dict[str, str]]]:
    return [pairs(x)[1:] for x in lines if x.split(" ", 1)[0] == action]


def test_billing_limit_resumes_resumable_task_and_logs_code(clock, runlog):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-S2", ["quota"])
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기" and run.last_error_kind == "일시" and run.retry_count == 0
    [rec] = records_of_task(app, rid, "T-S2")
    assert (rec.status, rec.error, rec.error_kind) == ("재개대기", "호출실패", "일시")
    [call] = [c for c in app.store.call_logs(rid) if c.task_id == "T-S2"]
    assert [t.detail for t in call.tries] == ["status=429 code=insufficient_quota"]
    [(keys, end)] = [x for x in lines_of(runlog, "단계끝") if x[1]["step"] == "T-S2"]
    assert keys[keys.index("errorKind") + 1] == "errorCode" and end["errorCode"] == "insufficient_quota"
    [(keys, res)] = lines_of(runlog, "재개예약")
    assert keys == ["run", "project", "at", "errorKind", "errorCode"]
    assert (res["errorKind"], res["errorCode"]) == ("일시", "insufficient_quota")
    assert all(e["errorCode"] == "-" for _, e in lines_of(runlog, "단계끝") if e["step"] != "T-S2")
    clock.advance(minutes=16)                                                     # 충전 뒤 다음 재개 시각 — 하던 단계부터
    app.orchestrator.tick(clock.t)
    assert state(app, rid) == ("문서평가", "사용자대기")
    again = [e for _, e in lines_of(runlog, "단계끝") if e["step"] == "T-S2"]
    assert [e["errorCode"] for e in again] == ["insufficient_quota", "-"]


def test_transient_without_code_logs_dash(clock, runlog):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-S2", ["timeout"] * 6)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert state(app, rid)[1] == "재개대기"
    [(_, res)] = lines_of(runlog, "재개예약")
    assert res["errorCode"] == "-"
    end = [e for _, e in lines_of(runlog, "단계끝") if e["step"] == "T-S2"][-1]
    assert (end["errorKind"], end["errorCode"]) == ("일시", "-")


def test_operation_error_fails_after_one_try(clock, runlog):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-C3", ["auth"])
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert state(app, rid)[1] == "실패"
    calls = [c for c in app.store.call_logs(rid) if c.task_id == "T-C3" and c.final_outcome == "소진"]
    assert calls and all(len(c.tries) == 1 for c in calls)


def test_tc1_billing_limit_rolls_back_with_code_line(clock, runlog):
    """사전 단계 T-C1 — 한도 소진도 재개하지 않고 E-C1-TIMEOUT. 임시 Context의 단계끝 줄에도 errorCode가 나온다."""
    app = make_app(clock)
    app.llm.plan("T-C1", ["quota"])
    res = app.orchestrator.start_run("acc-1", pre_input())
    assert not res.ok and res.code == "E-C1-TIMEOUT"
    [(keys, end)] = [x for x in lines_of(runlog, "단계끝") if x[1]["step"] == "T-C1"]
    assert keys[keys.index("errorKind") + 1] == "errorCode"
    assert (end["status"], end["errorKind"], end["errorCode"]) == ("실패", "일시", "insufficient_quota")
    assert lines_of(runlog, "재개예약") == []


def test_stub_tv2_billing_limit_resumes(clock):
    app = make_app(clock)
    app.llm.plan("T-V2", ["quota"])
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기" and run.current_task == "T-V2"
    clock.advance(minutes=16)
    app.orchestrator.tick(clock.t)
    assert state(app, rid) == ("산출물확인", "사용자대기")
    [rec] = records_of_task(app, rid, "T-V2")
    assert (rec.status, rec.resume_count) == ("성공", 1)                          # 같은 실행 기록을 이어 써서 성공


def test_stub_tv2_non_billing_exhaustion_still_substitutes(clock):
    app = make_app(clock)
    app.llm.plan("T-V2", ["timeout"] * 6)
    rid = to_screen6(app)
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    assert state(app, rid) == ("산출물확인", "사용자대기")
