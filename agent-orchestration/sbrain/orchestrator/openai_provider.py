"""OpenAI 호출처 어댑터 — LLMProvider 구현 (조율 Agent가 쓴다, 기획서 5-2).

- 재시도는 tools가 한다. SDK 자체 재시도는 끈다(max_retries=0).
- request.timeout_sec를 요청 timeout으로 건다.
- 시간 초과 → TimeoutError, 연결 오류 → ConnectionError, 응답 코드 오류 → ProviderError(status).
  빈 응답(거부 포함)은 형식 오류로 보고 tools가 재시도한다.
- response_schema가 있으면 JSON 스키마 응답 형식(strict=False)으로 요청한다. 검사는 tools가 다시 한다.
- 온도(temperature)와 추론 강도(reasoning_effort)는 요청에 값이 있을 때만 싣는다.
  추론 모델(gpt-5-mini · gpt-5.6-luna · gpt-6-luna 등)은 Agent 설정에서 온도를 비우고 추론 강도를 준다.
- API 키는 환경 변수 OPENAI_API_KEY에서 읽는다(SDK 기본 동작). 코드 · 설정 파일에 넣지 않는다.
"""
from __future__ import annotations

import re
from typing import Any

import openai

from .errors import FormatError, ProviderError
from .tools import LLMRequest


class OpenAIProvider:
    def __init__(self, client: Any | None = None, **client_kwargs: Any) -> None:
        self._client = client if client is not None else openai.OpenAI(max_retries=0, **client_kwargs)

    def complete(self, request: LLMRequest) -> str:
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
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError:  # APIConnectionError의 하위라 먼저 받는다
            raise TimeoutError("OpenAI 응답 지연") from None
        except openai.APIConnectionError as e:
            raise ConnectionError(f"OpenAI 연결 실패: {type(e).__name__}") from None
        except openai.APIStatusError as e:
            raise ProviderError(f"OpenAI 오류 {e.status_code}", status=e.status_code) from None
        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice is not None else None
        if not content:
            raise FormatError("빈 응답")
        return content


def _schema_name(schema: dict[str, Any]) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(schema.get("title") or "response"))[:64]
