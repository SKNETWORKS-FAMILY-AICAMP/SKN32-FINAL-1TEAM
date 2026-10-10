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
- 파일 창구(확장, 결정 0023): files.put(이름, 내용, 형식) -> FileRef, files.get(FileRef) -> 내용. 저장소 호출은 같은 재시도 ·
  오류 분류(_call)를 거치고 호출 기록은 call_type 'file' · 목적 put · get이다. 이름 · 형식 · 크기 위반, 실행 건이 '실행'이 아닌
  넣기, 다른 실행 건 파일 읽기는 저장소를 부르지 않고 FileRejected다. 파일 내용 · 이름 · 키는 기록 · 예외 메시지에 넣지 않는다.
- 목적별 모델(확장, 결정 0024): llm(purpose=p)는 ToolsConfig.purpose_models에 p가 있으면 그 모델로 부르고 호출 기록의
  model에도 그 모델을 남긴다. 호출처 · 온도 · 추론 강도 · 제한 시간 · 재시도는 Task 설정 그대로다. 목적 이름은 Task가 정하고
  tools · 엔진은 사전을 그대로 쓴다.
- JSON 객체 응답(확장, spec 4.1): llm(json_mode=True)는 요청(LLMRequest.json_mode)에 실어 보낸다. 호출 기록 칸은 늘리지 않는다.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..models.base import CallError, ErrorKind
from ..models.files import FileRef, file_name_problem, media_type_problem, size_problem
from .errors import FileRejected, FormatError, ProviderError, ToolCallExhausted
from .files import FileConflict, FileMeta, FileMissing, FileStore, sha256_hex
from .trace import FILE_CALL, CallLog, CallTry, add_tokens

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
    # 확장 — JSON 객체 응답 요청(스키마 없이). 호출처가 response_schema가 없을 때만 JSON 객체 응답 형식으로 요청한다.
    # 호출 기록에는 칸을 더하지 않는다 (spec 4.1)
    json_mode: bool = False


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
    # 확장 — 호출 목적 → 모델 (Task 설정의 purposeModels를 엔진이 그대로 옮긴다). 없는 목적은 model로 부른다
    purpose_models: Mapping[str, str] = field(default_factory=dict)

    def model_for(self, purpose: str) -> str | None:
        """이 목적의 LLM 모델 — 목적별 모델이 있으면 그 값, 없으면 Task 모델."""
        return self.purpose_models.get(purpose, self.model)


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
    # 확장 — 파일 저장소와 '이 실행 건의 지금 진행 상태 읽기'(저장소에서 다시 읽음, 실행 건이 없으면 None).
    # 둘 중 하나라도 없으면(사전 단계 · 실행 기록 밖) 파일 창구를 부르는 순간 RuntimeError다
    files: FileStore | None = None
    run_progress: Callable[[], str | None] | None = None


# 파일 창구의 시도 실패 설명 (내용 · 이름 · 키 없음)
FILE_MISSING = "없는 파일"
FILE_CONFLICT = "같은 키에 다른 내용"
FILE_HASH_MISMATCH = "sha256 불일치"


# 이미지 모델 설정이 없는 Task의 이미지 호출 — 기록의 설명 칸에 남기는 이유 (CallError 값은 늘리지 않는다)
NO_IMAGE_SETTING = "이미지 모델 설정 없음"
NO_LLM_SETTING = "LLM 설정 없음(LLM을 부르지 않는 단계)"


class _Immediate(Exception):
    """재시도하지 않고 바로 끝내는 호출 실패 (tools 안에서만 쓴다)."""

    def __init__(self, error: CallError, kind: ErrorKind, detail: str) -> None:
        super().__init__(detail)
        self.error, self.kind, self.detail = error, kind, detail


class FileTool:
    """파일 창구 (확장, 결정 0023) — tools.files. 파일을 쓰는 규칙 단계(G-04)는 이것을 두 번째 인자로 받는다.

    Task 함수(스텁 · 실구현)는 파일을 저장소 · 디스크에 직접 쓰거나 읽지 않고 이것으로만 한다.
    """

    def __init__(self, tools: "Tools") -> None:
        self._tools = tools

    def _store(self) -> tuple[FileStore, Callable[[], str | None]]:
        ctx = self._tools._ctx
        if ctx.files is None or ctx.run_progress is None:
            raise RuntimeError("파일 저장소 없음 — 실행 건의 실행 기록 밖(사전 단계 등)에서 파일 창구를 불렀다")
        return ctx.files, ctx.run_progress

    def put(self, name: str, data: bytes, media_type: str) -> FileRef:
        """파일을 넣고 참조를 돌려준다. 이름 · 형식 · 크기 위반이나 실행 건이 '실행'이 아니면 FileRejected(저장소를 부르지 않음).
        넣을 때마다 새 키다. 저장소 쓰기는 같은 키로 재시도한다(같은 내용이면 성공)."""
        store, progress = self._store()
        if not isinstance(data, (bytes, bytearray)):
            raise FileRejected("내용이 바이트가 아님")
        problem = file_name_problem(name) or media_type_problem(media_type) or size_problem(len(data))
        if problem is not None:
            raise FileRejected(f"파일 규칙 위반 — {problem}")
        if progress() != "실행":
            raise FileRejected("실행 건이 '실행'이 아님 — 파일을 넣지 않는다")
        ctx = self._tools._ctx
        data = bytes(data)
        meta = FileMeta(name=name, media_type=media_type, size=len(data), sha256=sha256_hex(data))
        key = f"{ctx.run_id}/{ctx.execution_id}/{uuid.uuid4().hex}/{name}"

        def once() -> None:
            try:
                store.write(key, data, meta)
            except FileConflict:   # 넣기마다 새 키라 일어나면 안 된다 — 재시도하지 않는다
                raise _Immediate("호출실패", "운영", FILE_CONFLICT) from None

        self._tools._call(FILE_CALL, "put", once)
        return FileRef(key=key, name=name, media_type=media_type, size=meta.size, sha256=meta.sha256)

    def get(self, ref: FileRef) -> bytes:
        """참조의 내용을 읽는다. 이 실행 건의 파일이 아니면 FileRejected(저장소를 부르지 않음). 없는 키는 입력 오류(재시도하지
        않음), 읽은 내용의 sha256이 참조와 다르면 형식 오류(재시도)다."""
        store, _ = self._store()
        if not isinstance(ref, FileRef):
            raise FileRejected("파일 참조가 아님")
        if ref.run_id != self._tools._ctx.run_id:
            raise FileRejected("다른 실행 건의 파일 — 읽지 않는다")

        def once() -> bytes:
            try:
                data = store.read(ref.key)
            except FileMissing:
                raise _Immediate("호출실패", "입력", FILE_MISSING) from None
            if sha256_hex(data) != ref.sha256:
                raise FormatError(FILE_HASH_MISMATCH)
            return data

        return self._tools._call(FILE_CALL, "get", once)


class Tools:
    """Task 함수에 넘기는 호출 도구 (잠정 규격: llm · search, 확장 image · files)."""

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

    @property
    def files(self) -> FileTool:
        """파일 창구 (확장) — put · get. 호출 기록은 이 tools의 실행 기록에 모인다."""
        return FileTool(self)

    # ── 공개 규격 ─────────────────────────────────────
    def llm(
        self,
        messages: list[dict[str, Any]],
        *,
        schema: type[BaseModel] | None = None,
        parse: Callable[[Any], Any] | None = None,
        purpose: str = "",
        json_mode: bool = False,
    ) -> Any:
        """LLM을 호출한다. schema가 있으면 JSON을 그 모델로 검사해 돌려주고,
        parse가 있으면 (검사한) 결과를 parse에 넘긴다. parse가 FormatError를 올리면 재시도한다.

        모델은 목적별 모델(purpose_models[purpose])이 있으면 그 값, 없으면 Task 모델이다 — 호출 기록의 model도 같다.
        json_mode(확장)가 참이면 요청에 실어 호출처가 스키마 없이 JSON 객체 응답 형식으로 요청하게 한다(schema가 있으면 schema 우선)."""
        cfg = self._config
        if cfg.model is None or cfg.provider is None:
            def refuse() -> Any:   # 호출처를 부르지 않는다 — 실패한 시도 하나만 남긴다
                raise _Immediate("호출실패", "운영", NO_LLM_SETTING)
            return self._call("llm", purpose, refuse)
        provider = self._ctx.providers.get(cfg.provider)
        model = cfg.model_for(purpose)
        request = LLMRequest(
            provider=cfg.provider,
            model=model,
            temperature=cfg.temperature,
            messages=messages,
            timeout_sec=cfg.timeout_sec,
            response_schema=schema.model_json_schema() if schema else None,
            reasoning_effort=cfg.reasoning_effort,
            json_mode=json_mode,
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

        return self._call("llm", purpose, once, usage=lambda: box["usage"], model=model)

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
              usage: Callable[[], TokenUsage | None] = lambda: None, model: str | None = None) -> T:
        """model은 LLM 호출이 실제로 쓴 모델(목적별 모델) — 없으면 Task 모델을 기록한다."""
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
            model=(model or cfg.model) if llm else cfg.image_model if image else None,
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
