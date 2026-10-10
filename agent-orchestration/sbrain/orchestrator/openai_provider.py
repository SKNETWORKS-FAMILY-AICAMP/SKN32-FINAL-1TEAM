"""OpenAI 호출처 어댑터 — LLMProvider 구현 (조율 Agent와 전략 · 작성 · 검증-1 Task가 쓴다, 기획서 5-2).

- 재시도는 tools가 한다. SDK 자체 재시도는 끈다(max_retries=0).
- request.timeout_sec를 요청 timeout으로 건다.
- 시간 초과 → TimeoutError, 연결 오류 → ConnectionError, 응답 코드 오류 → ProviderError(status).
  빈 응답(거부 포함)은 형식 오류로 보고 tools가 재시도한다.
- 응답 형식: response_schema가 있으면 JSON 스키마 응답 형식(strict=False)으로 요청한다(json_mode보다 우선). 검사는 tools가
  다시 한다. 스키마가 없고 json_mode(확장)가 참이면 JSON 객체 응답 형식(response_format={"type": "json_object"})으로
  요청한다 — 전략 · 작성 · 검증-1 담당자 llm_runtime.request_json과 같다(spec 4.1). 둘 다 없으면 응답 형식을 싣지 않는다.
- 길이 한도로 잘린 응답(finish_reason == 'length')은 json_mode와 상관없이 늘 성공으로 보지 않는다 — FormatError(내용 없는
  메시지, 사용량 실음)로 올려 tools가 재시도한다(담당자 request_json과 같게, T-C1 · T-C3 · 다시 쓰기 호출에도 적용).
- 온도(temperature)와 추론 강도(reasoning_effort)는 요청에 값이 있을 때만 싣는다.
  추론 모델(gpt-5-mini · gpt-5.6-luna · gpt-6-luna 등)은 Agent 설정에서 온도를 비우고 추론 강도를 준다.
- API 키는 환경 변수 OPENAI_API_KEY에서, 없으면 .env 파일에서 읽는다(sbrain/env.py). 코드에 넣지 않는다.
- 토큰 사용량을 LLMResponse로 함께 돌려준다(확장). 빈 응답도 사용량을 FormatError에 실어 비용이 남게 한다.
  usage.prompt_tokens → 입력 (캐시 입력을 포함한 전체), prompt_tokens_details.cached_tokens → 캐시 입력 (입력의 일부),
  usage.completion_tokens → 출력 (추론을 포함한 전체), completion_tokens_details.reasoning_tokens → 추론 (출력의 일부).
"""
from __future__ import annotations

import re
from typing import Any

import openai

from ..env import get_env
from .errors import FormatError, ProviderError
from .tools import LLMRequest, LLMResponse, TokenUsage


class OpenAIProvider:
    def __init__(self, client: Any | None = None, **client_kwargs: Any) -> None:
        if client is None:
            # 키가 어디에도 없으면 None — SDK가 '키 없음' 오류를 낸다
            client_kwargs.setdefault("api_key", get_env("OPENAI_API_KEY"))
            client = openai.OpenAI(max_retries=0, **client_kwargs)
        self._client = client

    def complete(self, request: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "timeout": request.timeout_sec,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.reasoning_effort is not None:
            kwargs["reasoning_effort"] = request.reasoning_effort
        if request.response_schema is not None:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": _schema_name(request.response_schema),
                "schema": request.response_schema,
                "strict": False,
            }}
        elif request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError:  # APIConnectionError의 하위라 먼저 받는다
            raise TimeoutError("OpenAI 응답 지연") from None
        except openai.APIConnectionError as e:
            raise ConnectionError(f"OpenAI 연결 실패: {type(e).__name__}") from None
        except openai.APIStatusError as e:
            raise ProviderError(f"OpenAI 오류 {e.status_code}", status=e.status_code) from None
        usage = _usage(getattr(response, "usage", None))
        choice = response.choices[0] if response.choices else None
        if choice is not None and getattr(choice, "finish_reason", None) == "length":
            raise FormatError("길이 한도로 잘린 응답", usage=usage)   # 응답 내용 · 길이는 싣지 않는다
        content = choice.message.content if choice is not None else None
        if not content:
            raise FormatError("빈 응답", usage=usage)
        return LLMResponse(content, usage)


def _usage(u: Any) -> TokenUsage | None:
    if u is None:
        return None
    prompt, completion = getattr(u, "prompt_tokens_details", None), getattr(u, "completion_tokens_details", None)
    return TokenUsage(
        input_tokens=getattr(u, "prompt_tokens", None),
        cached_input_tokens=getattr(prompt, "cached_tokens", None),
        output_tokens=getattr(u, "completion_tokens", None),
        reasoning_tokens=getattr(completion, "reasoning_tokens", None),
    )


def _schema_name(schema: dict[str, Any]) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(schema.get("title") or "response"))[:64]
