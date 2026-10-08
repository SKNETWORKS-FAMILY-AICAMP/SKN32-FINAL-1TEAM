"""호출 도구(tools) — 잠정 규격.

Task 안의 LLM · 검색 호출은 반드시 tools로 한다(팀 간 규격, 합의 전 잠정).
tools는 호출마다 재시도 · 제한 시간 · 오류 종류 분류를 맡고, 재시도를 다 쓰면 ToolCallExhausted를 올린다.

- 제한 시간: 동기 호출은 강제로 끊을 수 없으므로 호출처(HTTP 클라이언트)의 timeout으로 건다.
  tools는 timeout_sec를 요청에 실어 넘기고, 호출처는 시간이 넘으면 TimeoutError를 올린다.
- 형식 오류: tools가 기대 스키마(schema)로 검사하고, Task의 parse 함수가 FormatError를 올려도 재시도한다.
- 여러 스레드에서 동시에 써도 안전하다(T-P2). 재시도 기록은 호출별로 따로 센다.
- 기준 문서 문구대로 호출 실패는 오류 종류와 관계없이 재시도 횟수까지 다시 보낸다.
  오류 종류는 재시도를 다 쓴 뒤 재개할지(일시) 실패로 끝낼지(입력 · 운영)를 가른다.
- 토큰 사용량(확장): 호출처가 LLMResponse(text, usage)를 돌려주면 시도마다 사용량을 CallTry에 남긴다.
  스키마 검사 · parse 전에 남겨 형식 오류로 버린 응답의 비용도 기록된다. 호출 합계는 CallLog에 둔다.
  호출처는 문자열만 돌려줘도 된다(사용량 없음).
- 이미지 호출(확장): image()는 ImageProvider로 그림(PNG)을 그린다. 재시도 · 제한 시간 · 오류 종류 분류는 llm과 같다.
  제한 시간은 Task 설정의 이미지 제한 시간(image_timeout_sec), 호출 기록은 call_type 'image' · 이미지 호출처 · 이미지 모델.
  이미지 모델 설정이 없는 Task가 부르면 호출처를 부르지 않고 바로 실패한 호출 하나를 기록하고 ToolCallExhausted를 올린다.
  지시문 · 입력 그림 · 결과 그림은 어떤 기록 · 예외 메시지에도 남기지 않는다(repr에서도 뺀다).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..models.base import CallError, ErrorKind
from .errors import FormatError, ProviderError, ToolCallExhausted
from .trace import CallLog, CallTry, add_tokens

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


@dataclass(frozen=True)
class TokenUsage:
    """확장 — 응답 하나의 토큰 사용량. 입력은 캐시 입력을 포함한 전체, 출력은 추론을 포함한 전체."""
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    """확장 — 호출처 응답: 본문과 토큰 사용량."""
    text: str
    usage: TokenUsage | None = None


class LLMProvider(Protocol):
    """LLM 호출처 어댑터. timeout_sec를 HTTP 클라이언트 timeout으로 걸고,
    시간 초과는 TimeoutError, 응답 코드 오류는 ProviderError(status=...)로 올린다.
    본문만(str) 돌려주거나, 토큰 사용량을 함께 LLMResponse로 돌려준다."""

    def complete(self, request: LLMRequest) -> str | LLMResponse: ...


@dataclass(frozen=True)
class ImageRequest:
    """확장 — 이미지 호출 요청. image가 있으면 그 그림을 바탕으로 그리고(편집), 없으면 새로 그린다.
    size · quality가 None이면 호출처가 싣지 않는다(모델 기본값). 지시문 · 그림은 repr에 넣지 않는다."""
    provider: str
    model: str
    prompt: str = field(repr=False)
    image: bytes | None = field(repr=False)
    size: str | None
    quality: str | None
    timeout_sec: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ImageResponse:
    """확장 — 이미지 호출처 응답: 결과 그림(PNG 바이트)과 토큰 사용량(없으면 None)."""
    png: bytes = field(repr=False)
    usage: TokenUsage | None = None


class ImageProvider(Protocol):
    """이미지 호출처 어댑터 (확장). timeout_sec를 HTTP 클라이언트 timeout으로 걸고,
    시간 초과는 TimeoutError, 응답 코드 오류는 ProviderError(status=...)로 올린다 (LLMProvider와 같다).
    그림을 받지 못한 응답은 FormatError(사용량을 실어)로 올린다."""

    def create(self, request: ImageRequest) -> ImageResponse: ...


@dataclass(frozen=True)
class ToolsConfig:
    """Task 설정을 입힌 호출 설정. agent는 호출 기록에 남는 Agent 이름(Task의 담당 Agent)이다.

    image_*는 이미지 호출 설정(확장)이다 — image_model이 None이면 이미지 호출을 쓸 수 없다.
    image_timeout_sec은 이미지 호출 한 번의 제한 시간이다.
    """
    agent: str
    provider: str | None   # None = LLM을 부르지 않는 단계(Task 설정 표를 보지 않는다) — llm 호출은 바로 실패한다
    model: str | None
    temperature: float | None
    timeout_sec: float
    retry_count: int
    retry_interval_sec: float
    reasoning_effort: str | None = None
    image_provider: str | None = None
    image_model: str | None = None
    image_quality: str | None = None
    image_size: str | None = None
    image_timeout_sec: float = 120.0


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
    image_providers: dict[str, ImageProvider] = field(default_factory=dict)   # 확장 — 이미지 호출처 (없으면 이미지 호출 실패)


# 이미지 모델 설정이 없는 Task의 이미지 호출 — 기록의 설명 칸에 남기는 이유 (CallError 값은 늘리지 않는다)
NO_IMAGE_SETTING = "이미지 모델 설정 없음"
NO_LLM_SETTING = "LLM 설정 없음(LLM을 부르지 않는 단계)"


class _Immediate(Exception):
    """재시도하지 않고 바로 끝내는 호출 실패 (tools 안에서만 쓴다)."""

    def __init__(self, error: CallError, kind: ErrorKind, detail: str) -> None:
        super().__init__(detail)
        self.error, self.kind, self.detail = error, kind, detail


class Tools:
    """Task 함수에 넘기는 호출 도구 (잠정 규격: llm · search, 확장 image)."""

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
        if cfg.model is None or cfg.provider is None:
            def refuse() -> Any:   # 호출처를 부르지 않는다 — 실패한 시도 하나만 남긴다
                raise _Immediate("호출실패", "운영", NO_LLM_SETTING)
            return self._call("llm", purpose, refuse)
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

        box: dict[str, TokenUsage | None] = {"usage": None}   # 이 시도의 사용량 (호출마다 따로 — 스레드 안전)

        def once() -> Any:
            box["usage"] = None
            if provider is None:
                raise ProviderError(f"호출처 없음: {cfg.provider}", status=404)
            try:
                reply = provider.complete(request)
            except FormatError as e:   # 응답은 받았지만 쓸 수 없음 — 사용량은 남긴다
                box["usage"] = e.usage
                raise
            text, box["usage"] = (reply.text, reply.usage) if isinstance(reply, LLMResponse) else (reply, None)
            value: Any = text
            if schema is not None:
                try:
                    value = schema.model_validate_json(text)
                except ValidationError as e:
                    raise FormatError(f"스키마 불일치: {e.error_count()}건") from None
            if parse is not None:
                value = parse(value)
            return value

        return self._call("llm", purpose, once, usage=lambda: box["usage"])

    def search(self, purpose: str, fn: Callable[[float], T]) -> T:
        """LLM이 아닌 호출(임베딩 검색 · BM25 등)을 감싼다. fn은 timeout_sec를 받는다."""
        return self._call("search", purpose, lambda: fn(self._config.timeout_sec))

    def image(
        self,
        prompt: str,
        *,
        image: bytes | None = None,
        size: str | None = None,
        quality: str | None = None,
        purpose: str = "",
    ) -> bytes:
        """그림을 그려 PNG 바이트를 돌려준다(확장). image가 있으면 그 그림을 바탕으로 그린다(편집).
        size · quality가 None이면 Task 설정의 image_size · image_quality를 쓴다.
        재시도를 다 쓰거나 이미지 모델 설정이 없으면 ToolCallExhausted를 올린다."""
        cfg = self._config
        if cfg.image_model is None:
            def refuse() -> bytes:   # 호출처를 부르지 않는다 — 실패한 시도 하나만 남긴다
                raise _Immediate("호출실패", "운영", NO_IMAGE_SETTING)
            return self._call("image", purpose, refuse)
        provider = self._ctx.image_providers.get(cfg.image_provider or "")
        request = ImageRequest(
            provider=cfg.image_provider or "",
            model=cfg.image_model,
            prompt=prompt,
            image=image,
            size=size if size is not None else cfg.image_size,
            quality=quality if quality is not None else cfg.image_quality,
            timeout_sec=cfg.image_timeout_sec,
            metadata={
                "run_id": self._ctx.run_id,
                "task_id": self._ctx.task_id,
                "agent": cfg.agent,
                "purpose": purpose,
                "item_key": self._item_key,
            },
        )

        box: dict[str, TokenUsage | None] = {"usage": None}   # 이 시도의 사용량 (호출마다 따로 — 스레드 안전)

        def once() -> bytes:
            box["usage"] = None
            if provider is None:
                raise ProviderError(f"이미지 호출처 없음: {cfg.image_provider}", status=404)
            try:
                reply = provider.create(request)
            except FormatError as e:   # 응답은 받았지만 그림이 없음 — 사용량은 남긴다
                box["usage"] = e.usage
                raise
            box["usage"] = reply.usage
            if not reply.png:
                raise FormatError("빈 그림")
            return reply.png

        return self._call("image", purpose, once, usage=lambda: box["usage"])

    # ── 재시도 ────────────────────────────────────────
    def _call(self, call_type: str, purpose: str, once: Callable[[], T],
              usage: Callable[[], TokenUsage | None] = lambda: None) -> T:
        cfg, ctx = self._config, self._ctx
        llm, image = call_type == "llm", call_type == "image"
        log = CallLog(
            call_id=ctx.new_id(),
            run_id=ctx.run_id,
            execution_id=ctx.execution_id,
            task_id=ctx.task_id,
            agent=cfg.agent,
            call_type=call_type,
            purpose=purpose,
            item_key=self._item_key,
            provider=cfg.provider if llm else cfg.image_provider if image else None,
            model=cfg.model if llm else cfg.image_model if image else None,
            temperature=cfg.temperature if llm else None,
            reasoning_effort=cfg.reasoning_effort if llm else None,
            timeout_sec=cfg.image_timeout_sec if image else cfg.timeout_sec,
        )
        error: CallError = "호출실패"
        kind: ErrorKind = "일시"
        detail = ""
        total = 1 + cfg.retry_count
        for no in range(1, total + 1):
            started = ctx.now()
            try:
                result = once()
            except _Immediate as e:   # 재시도하지 않는다
                error, kind, detail = e.error, e.kind, e.detail
                log.tries.append(CallTry(no=no, started_at=started, ended_at=ctx.now(),
                                         outcome=error, error_kind=kind, detail=detail))
                break
            except FormatError as e:
                error, kind, detail = "형식오류", "일시", str(e)
            except TimeoutError:
                error, kind, detail = "응답지연", "일시", "timeout"
            except ProviderError as e:
                error, kind, detail = "호출실패", classify_status(e.status), f"status={e.status}"
            except (ConnectionError, OSError) as e:
                error, kind, detail = "호출실패", "일시", type(e).__name__
            else:
                log.tries.append(CallTry(no=no, started_at=started, ended_at=ctx.now(), outcome="성공",
                                         **_usage_fields(usage())))
                log.final_outcome = "성공"
                add_tokens(log, log.tries)
                ctx.sink.add(log)
                return result
            log.tries.append(CallTry(no=no, started_at=started, ended_at=ctx.now(),
                                     outcome=error, error_kind=kind, detail=detail, **_usage_fields(usage())))
            if no < total and cfg.retry_interval_sec > 0:
                ctx.sleep(cfg.retry_interval_sec)
        log.final_outcome = "소진"
        log.error, log.error_kind = error, kind
        add_tokens(log, log.tries)
        ctx.sink.add(log)
        raise ToolCallExhausted(error=error, error_kind=kind, tries=len(log.tries),
                                call_id=log.call_id, detail=detail)


def _usage_fields(usage: TokenUsage | None) -> dict[str, int | None]:
    return asdict(usage) if usage is not None else {}
