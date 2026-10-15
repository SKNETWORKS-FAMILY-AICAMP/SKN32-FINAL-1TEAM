"""OpenAI 이미지 호출처 어댑터 — ImageProvider 구현 (확장).

- 입력 그림(request.image)이 있으면 images.edit, 없으면 images.generate를 부른다.
- 결과는 첫 그림의 b64_json을 풀어 PNG 바이트로 돌려준다(모델 기본 출력 형식이 PNG). 그림이 없으면 형식 오류.
- size · quality는 요청에 값이 있을 때만 싣는다. request.timeout_sec를 요청 timeout으로 건다.
- 재시도는 tools가 한다. SDK 자체 재시도는 끈다(max_retries=0).
- 시간 초과 → TimeoutError, 연결 오류 → ConnectionError, 응답 코드 오류 → ProviderError(status). 글 어댑터와 같다.
  오류 메시지에 지시문 · 그림을 싣지 않는다.
- 토큰 사용량: usage.input_tokens → 입력, usage.output_tokens → 출력. 캐시 · 추론은 없다(None). 사용량이 없으면 None.
- 클라이언트는 처음 호출할 때 만든다 — 워커 조립 때 키가 없어도 조립이 깨지지 않게(이미지 호출을 쓰는 구현 Task가
  아직 없다). API 키는 OPENAI_API_KEY(환경 변수 → .env)에서 읽는다(sbrain/env.py). 코드에 넣지 않는다.
"""
from __future__ import annotations

import base64
import binascii
import threading
from typing import Any

import openai

from ..env import get_env
from .errors import FormatError, ProviderError
from .tools import ImageRequest, ImageResponse, TokenUsage

EDIT_FILE_NAME = "input.png"   # images.edit에 올리는 입력 그림의 파일 이름 (내용 형식을 알리는 용도)


class OpenAIImageProvider:
    def __init__(self, client: Any | None = None, **client_kwargs: Any) -> None:
        self._client = client
        self._client_kwargs = client_kwargs
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is None:
                kwargs = dict(self._client_kwargs)
                kwargs.setdefault("api_key", get_env("OPENAI_API_KEY"))   # 없으면 None — SDK가 '키 없음' 오류를 낸다
                self._client = openai.OpenAI(max_retries=0, **kwargs)
            return self._client

    def create(self, request: ImageRequest) -> ImageResponse:
        kwargs: dict[str, Any] = {"model": request.model, "prompt": request.prompt, "timeout": request.timeout_sec}
        if request.size is not None:
            kwargs["size"] = request.size
        if request.quality is not None:
            kwargs["quality"] = request.quality
        images = self._get_client().images
        try:
            if request.image is not None:
                response = images.edit(image=(EDIT_FILE_NAME, request.image, "image/png"), **kwargs)
            else:
                response = images.generate(**kwargs)
        except openai.APITimeoutError:  # APIConnectionError의 하위라 먼저 받는다
            raise TimeoutError("OpenAI 이미지 응답 지연") from None
        except openai.APIConnectionError as e:
            raise ConnectionError(f"OpenAI 이미지 연결 실패: {type(e).__name__}") from None
        except openai.APIStatusError as e:
            raise ProviderError(f"OpenAI 이미지 오류 {e.status_code}", status=e.status_code) from None
        usage = _usage(getattr(response, "usage", None))
        data = getattr(response, "data", None) or []
        encoded = getattr(data[0], "b64_json", None) if data else None
        if not encoded:
            raise FormatError("빈 그림", usage=usage)
        try:
            png = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise FormatError("그림 해독 실패", usage=usage) from None
        return ImageResponse(png, usage)


def _usage(u: Any) -> TokenUsage | None:
    if u is None:
        return None
    return TokenUsage(input_tokens=getattr(u, "input_tokens", None), output_tokens=getattr(u, "output_tokens", None))
