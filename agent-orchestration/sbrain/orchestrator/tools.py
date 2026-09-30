"""호출 도구(tools) — 잠정 규격.

Task 안의 LLM · 검색 호출은 반드시 tools로 한다(팀 간 규격, 합의 전 잠정).
tools는 호출마다 재시도 · 제한 시간 · 오류 종류 분류를 맡고, 재시도를 다 쓰면 ToolCallExhausted를 올린다.

- 제한 시간: 동기 호출은 강제로 끊을 수 없으므로 호출처(HTTP 클라이언트)의 timeout으로 건다.
  tools는 timeout_sec를 요청에 실어 넘기고, 호출처는 시간이 넘으면 TimeoutError를 올린다.
- 형식 오류: tools가 기대 스키마(schema)로 검사하고, Task의 parse 함수가 FormatError를 올려도 재시도한다.
- 여러 스레드에서 동시에 써도 안전하다(T-P2). 재시도 기록은 호출별로 따로 센다.
- 기준 문서 문구대로 호출 실패는 오류 종류와 관계없이 재시도 횟수까지 다시 보낸다.
  오류 종류는 재시도를 다 쓴 뒤 재개할지(일시) 실패로 끝낼지(입력 · 운영)를 가른다.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..models.base import CallError, ErrorKind
from .errors import FormatError, ProviderError, ToolCallExhausted
from .trace import CallLog, CallTry

T = TypeVar("T")


@dataclass(frozen=True)
class LLMRequest:
    provider: str
    model: str
    temperature: float | None            # None이면 호출처가 싣지 않는다 (추론 모델)
    messages: list[dict[str, Any]]
    timeout_sec: float
    response_schema: dict[str, Any] | None
    metadata: dict[str, Any]
    reasoning_effort: str | None = None  # 추론 모델의 추론 강도


class LLMProvider(Protocol):
    """LLM 호출처 어댑터. timeout_sec를 HTTP 클라이언트 timeout으로 걸고,
    시간 초과는 TimeoutError, 응답 코드 오류는 ProviderError(status=...)로 올린다."""

    def complete(self, request: LLMRequest) -> str: ...


@dataclass(frozen=True)
class ToolsConfig:
    """담당 Agent 설정을 입힌 호출 설정."""
    agent: str
    provider: str
    model: str
    temperature: float | None
    timeout_sec: float
    retry_count: int
    retry_interval_sec: float
    reasoning_effort: str | None = None


def classify_status(status: int | None) -> ErrorKind:
    if status is None or status in (408, 429) or status >= 500:
        return "일시"
    if status in (400, 413, 422):
        return "입력"
    return "운영"


class CallSink:
    """호출 로그를 모으는 곳. 여러 스레드에서 동시에 쓴다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logs: list[CallLog] = []

    def add(self, log: CallLog) -> None:
        with self._lock:
            self._logs.append(log)

    def drain(self) -> list[CallLog]:
        with self._lock:
            logs, self._logs = self._logs, []
            return logs


@dataclass
class ToolsContext:
    run_id: str
    execution_id: str
    task_id: str
    providers: dict[str, LLMProvider]
    sink: CallSink
    now: Callable[[], datetime]
    sleep: Callable[[float], None] = time.sleep
    new_id: Callable[[], str] = field(default=lambda: uuid.uuid4().hex[:12])


class Tools:
    """Task 함수에 넘기는 호출 도구 (잠정 규격: llm · search 두 가지)."""

    def __init__(self, config: ToolsConfig, ctx: ToolsContext, item_key: str | None = None) -> None:
        self._config = config
        self._ctx = ctx
        self._item_key = item_key

    @property
    def config(self) -> ToolsConfig:
        return self._config

    def for_item(self, item_key: str) -> "Tools":
        """같은 설정 · 같은 로그로 항목(문장 등)별 호출 도구를 만든다."""
        return Tools(self._config, self._ctx, item_key)

    # ── 공개 규격 ─────────────────────────────────────
    def llm(
        self,
        messages: list[dict[str, Any]],
        *,
        schema: type[BaseModel] | None = None,
        parse: Callable[[Any], Any] | None = None,
        purpose: str = "",
    ) -> Any:
        """LLM을 호출한다. schema가 있으면 JSON을 그 모델로 검사해 돌려주고,
        parse가 있으면 (검사한) 결과를 parse에 넘긴다. parse가 FormatError를 올리면 재시도한다."""
        cfg = self._config
        provider = self._ctx.providers.get(cfg.provider)
        request = LLMRequest(
            provider=cfg.provider,
            model=cfg.model,
            temperature=cfg.temperature,
            messages=messages,
            timeout_sec=cfg.timeout_sec,
            response_schema=schema.model_json_schema() if schema else None,
            reasoning_effort=cfg.reasoning_effort,
            metadata={
                "run_id": self._ctx.run_id,
                "task_id": self._ctx.task_id,
                "agent": cfg.agent,
                "purpose": purpose,
                "item_key": self._item_key,
            },
        )

        def once() -> Any:
            if provider is None:
                raise ProviderError(f"호출처 없음: {cfg.provider}", status=404)
            text = provider.complete(request)
            value: Any = text
            if schema is not None:
                try:
                    value = schema.model_validate_json(text)
                except ValidationError as e:
                    raise FormatError(f"스키마 불일치: {e.error_count()}건") from None
            if parse is not None:
                value = parse(value)
            return value

        return self._call("llm", purpose, once)

    def search(self, purpose: str, fn: Callable[[float], T]) -> T:
        """LLM이 아닌 호출(임베딩 검색 · BM25 등)을 감싼다. fn은 timeout_sec를 받는다."""
        return self._call("search", purpose, lambda: fn(self._config.timeout_sec))

    # ── 재시도 ────────────────────────────────────────
    def _call(self, call_type: str, purpose: str, once: Callable[[], T]) -> T:
        cfg, ctx = self._config, self._ctx
        log = CallLog(
            call_id=ctx.new_id(),
            run_id=ctx.run_id,
            execution_id=ctx.execution_id,
            task_id=ctx.task_id,
            agent=cfg.agent,
            call_type=call_type,
            purpose=purpose,
            item_key=self._item_key,
            provider=cfg.provider if call_type == "llm" else None,
            model=cfg.model if call_type == "llm" else None,
            temperature=cfg.temperature if call_type == "llm" else None,
            reasoning_effort=cfg.reasoning_effort if call_type == "llm" else None,
            timeout_sec=cfg.timeout_sec,
        )
        error: CallError = "호출실패"
        kind: ErrorKind = "일시"
        detail = ""
        total = 1 + cfg.retry_count
        for no in range(1, total + 1):
            started = ctx.now()
            try:
                result = once()
            except FormatError as e:
                error, kind, detail = "형식오류", "일시", str(e)
            except TimeoutError:
                error, kind, detail = "응답지연", "일시", "timeout"
            except ProviderError as e:
                error, kind, detail = "호출실패", classify_status(e.status), f"status={e.status}"
            except (ConnectionError, OSError) as e:
                error, kind, detail = "호출실패", "일시", type(e).__name__
            else:
                log.tries.append(CallTry(no=no, started_at=started, ended_at=ctx.now(), outcome="성공"))
                log.final_outcome = "성공"
                ctx.sink.add(log)
                return result
            log.tries.append(CallTry(no=no, started_at=started, ended_at=ctx.now(),
                                     outcome=error, error_kind=kind, detail=detail))
            if no < total and cfg.retry_interval_sec > 0:
                ctx.sleep(cfg.retry_interval_sec)
        log.final_outcome = "소진"
        log.error, log.error_kind = error, kind
        ctx.sink.add(log)
        raise ToolCallExhausted(error=error, error_kind=kind, tries=len(log.tries),
                                call_id=log.call_id, detail=detail)
