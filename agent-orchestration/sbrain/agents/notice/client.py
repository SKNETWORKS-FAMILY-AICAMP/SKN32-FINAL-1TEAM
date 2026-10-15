"""공고 서버 HTTP 클라이언트 (spec 3.2 · 3.3) — 파이썬 표준 라이브러리(urllib)만 쓴다. 새 패키지를 넣지 않는다.

| # | API | 메서드 |
|---|---|---|
| 1 | `POST /api/match` | `match(body, timeout)` |
| 2 | `GET /api/collection_status` | `collection_status(timeout)` |
| 3 | `GET /api/notices/{notice_id}` | `notice(notice_id, timeout)` |
| 4 | `POST /api/notices/{notice_id}/eligibility` | `eligibility(notice_id, body, timeout)` |

- Task 안에서 `tools.search(목적, fn)`의 `fn(timeout_sec)`로 부른다. 받은 제한 시간을 HTTP timeout에 건다.
  재시도 · 호출 기록은 tools가 맡는다. 성공 응답의 키 · 값 검사는 받는 쪽(tc2 · g01)이 한다.
- 오류는 tools가 분류할 수 있는 예외로 바꾼다 (spec 3.3).

| 상황 | 올리는 예외 |
|---|---|
| 시간 초과 | `TimeoutError` |
| 연결 실패(거절 · 끊김 · 이름 풀이 실패 등) | `ConnectionError` |
| HTTP 오류 코드(2xx 밖, 3xx 포함 — 다른 주소로 따라가지 않는다) | `ProviderError(status=코드)` |
| 성공 응답이 JSON이 아님 | `FormatError` |
| 404 + 본문 `{"code": "NOTICE_NOT_FOUND"}` (3번 · 4번만) | 예외가 아니라 `NOT_FOUND` 값 — tools가 성공한 호출로 기록하고 재시도하지 않는다 |

- 본문 코드가 없는 404(경로가 아직 없는 경우 등)는 일반 오류 `ProviderError(404)`다. 1번 · 2번의 404도 그렇다.
- 예외 메시지에는 주소 · 호스트 · 요청 본문 · 응답 본문을 넣지 않는다(오류 종류 · 상태 코드뿐). 원래 예외(주소가 들어
  있을 수 있다)는 잇지 않는다(`from None`). 공고 서버 주소는 비밀 값처럼 다룬다(spec 7) — `repr`에도 싣지 않는다.
- 워커 프로세스 안에서는 공고 서버 호출을 한 번에 하나씩 보낸다 (잠정, spec 3.3) — 네 API 모두, 클라이언트가 여럿이어도
  같은 프로세스 공용 잠금. 프로세스끼리는 막지 않으므로 운영 워커는 1대다(공고팀이 동시 호출 안전성을 확인하기 전까지).
- 시스템 프록시 설정을 쓰지 않는다(신청자 정보가 설정한 주소 말고 다른 곳을 거치지 않게).
- 전송(`Transport`)은 바꿔 끼울 수 있다. 시험은 가짜 전송으로 네트워크 없이 돈다.
"""
from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from ...orchestrator.errors import FormatError, ProviderError

NOT_FOUND_CODE = "NOTICE_NOT_FOUND"

# 공고 서버 호출을 프로세스 안에서 하나씩 (잠정 — orchestrator/settings.py PROVISIONAL noticeServer.serialCalls)
_CALL_LOCK = threading.Lock()


class NotFound:
    """공고 없음 (404 + NOTICE_NOT_FOUND) — 예외가 아닌 호출 결과 값. `NOT_FOUND` 하나만 쓴다."""

    _instance: "NotFound | None" = None

    def __new__(cls) -> "NotFound":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "NOT_FOUND"


NOT_FOUND = NotFound()


class Transport(Protocol):
    """HTTP 요청 하나를 보내고 (상태 코드, 응답 본문)을 돌려준다. HTTP 오류 코드도 예외가 아니라 값으로 돌려준다.

    시간 초과는 `TimeoutError`, 연결 실패는 `ConnectionError`로 올린다. 메시지에 주소 · 본문을 넣지 않는다.
    """

    def __call__(self, method: str, url: str, body: bytes | None, timeout: float) -> tuple[int, bytes]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None   # 따라가지 않는다 — 3xx는 HTTP 오류 코드(ProviderError)가 된다


class UrllibTransport:
    """표준 라이브러리 urllib 전송. 프록시 · 다른 주소로 다시 보내기를 쓰지 않는다."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def __call__(self, method: str, url: str, body: bytes | None, timeout: float) -> tuple[int, bytes]:
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:          # HTTP 오류 코드 — 본문(공고 없음 코드)을 읽어 돌려준다
            try:
                data = e.read()
            except (OSError, http.client.HTTPException):
                data = b""
            finally:
                e.close()
            return e.code, data
        except urllib.error.URLError as e:           # 연결 단계 실패 — 원인이 시간 초과면 TimeoutError
            if isinstance(e.reason, TimeoutError):
                raise TimeoutError("공고 서버 응답 시간 초과") from None
            raise ConnectionError(f"공고 서버 연결 실패: {type(e.reason).__name__}") from None
        except TimeoutError:                          # 응답을 읽는 중 시간 초과
            raise TimeoutError("공고 서버 응답 시간 초과") from None
        except (OSError, http.client.HTTPException) as e:   # 응답 도중 끊김 등
            raise ConnectionError(f"공고 서버 연결 실패: {type(e).__name__}") from None
        except ValueError as e:                       # 주소를 쓸 수 없음 (메시지에 주소가 들어 있어 버린다)
            raise ConnectionError(f"공고 서버 연결 실패: {type(e).__name__}") from None


class NoticeClient:
    """공고 서버 네 API. 결과는 JSON 값(검사 전) 또는 `NOT_FOUND`(3번 · 4번)."""

    def __init__(self, base_url: str, *, transport: Transport | None = None) -> None:
        self._base = _check_base_url(base_url)
        self._transport: Transport = transport if transport is not None else UrllibTransport()

    def __repr__(self) -> str:
        return "NoticeClient(<주소 생략>)"

    def collection_status(self, timeout: float) -> Any:
        """API 2 — 수집 상태."""
        return self._call("GET", "/api/collection_status", None, timeout)

    def match(self, body: dict[str, Any], timeout: float) -> Any:
        """API 1 — 공고 추천."""
        return self._call("POST", "/api/match", body, timeout)

    def notice(self, notice_id: str, timeout: float) -> Any:
        """API 3 — 공고 상세. 공고 없음이면 NOT_FOUND."""
        return self._call("GET", f"/api/notices/{_segment(notice_id)}", None, timeout, not_found=True)

    def eligibility(self, notice_id: str, body: dict[str, Any], timeout: float) -> Any:
        """API 4 — 자격 판정. 공고 없음이면 NOT_FOUND."""
        return self._call("POST", f"/api/notices/{_segment(notice_id)}/eligibility", body, timeout, not_found=True)

    def _call(self, method: str, path: str, body: dict[str, Any] | None, timeout: float, *,
              not_found: bool = False) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        with _CALL_LOCK:
            status, raw = self._transport(method, self._base + path, data, timeout)
        if 200 <= status < 300:
            return _parse_json(raw)
        if status == 404 and not_found and _is_not_found(raw):
            return NOT_FOUND
        raise ProviderError(f"공고 서버 HTTP 오류: {status}", status=status)


def _segment(notice_id: str) -> str:
    """경로 한 칸 — 공고 ID를 퍼센트 인코딩한다(ID에 ':'가 있다. '/'도 칸을 나누지 않게)."""
    if not isinstance(notice_id, str) or not notice_id:
        raise ValueError("공고 ID가 비었다")
    return urllib.parse.quote(notice_id, safe="")


def _reject_constant(name: str) -> Any:
    raise ValueError("JSON 밖의 수 표기")   # NaN · Infinity — 약속 밖 값


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        raise FormatError("공고 서버 응답이 JSON이 아님") from None


def _is_not_found(raw: bytes) -> bool:
    try:
        value = _parse_json(raw)
    except FormatError:
        return False
    return isinstance(value, dict) and value.get("code") == NOT_FOUND_CODE


def _check_base_url(url: str) -> str:
    """http(s)://호스트[:포트][/경로] 꼴만 받는다. 오류 메시지에 주소를 싣지 않는다."""
    bad = ValueError("SBRAIN_NOTICE_API_URL 형식 오류 — http(s)://호스트[:포트][/경로] 꼴이어야 한다")
    text = url.strip() if isinstance(url, str) else ""
    if not text or any(ch.isspace() or ord(ch) < 32 for ch in text):
        raise bad
    try:
        parts = urllib.parse.urlsplit(text)
        parts.port   # noqa: B018 — 포트가 숫자 · 범위 안인지 확인 (아니면 ValueError)
    except ValueError:
        raise bad from None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise bad
    return text.rstrip("/")
