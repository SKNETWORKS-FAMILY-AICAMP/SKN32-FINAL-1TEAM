"""S3 오류 바꾸기 — S3 저장소 밖으로는 아래 종류만 나간다(바꾸는 곳은 translate_error 한 곳).

| S3 쪽 | 올리는 예외 | tools에서 | 파일 삭제 대기열 |
|---|---|---|---|
| 객체 없음 — 오류 코드 NoSuchKey(상태 404만으로 가르지 않는다) | 저장소가 먼저 가른다(is_no_such_key): read → FileMissing, meta → None, write의 메타 읽기 → 없음 | 입력 | — |
| 연결 오류 · 응답 본문을 읽다 끊김 · 상태 408 · 429 · 5xx · 상태 없음 · 일시 코드(TEMPORARY_ERROR_CODES) · 자격 증명을 얻지 못함 | S3TemporaryError(ConnectionError) | 일시(늘리는 간격) | 일시 |
| 연결 · 읽기 시간 초과 | S3TimeoutError(TimeoutError) | 일시(응답지연) | 일시 |
| 그 밖의 4xx — 권한 없음(403) · 버킷 없음(NoSuchBucket, 404지만 영구) · 잘못된 요청 등 | ProviderError(status, code) | 입력 · 운영(재시도 없음) | 운영 |

- 가르는 순서: 오류 코드가 NoSuchKey면 없음 → 속도 제한 · 일시 코드 · 일시 상태면 일시 → 나머지 응답은 영구.
- 여러 객체 지우기의 일부 실패(delete_errors_problem): 하나라도 일시 코드면 일시, 아니면 AccessDenied는 ProviderError(403),
  그 밖은 일시(대기열이 다시 시도한다).
- 응답이 아닌 AWS 라이브러리 오류 중 위 표에 없는 것(요청 인자 검사 등 — 코드 오류로 본다)은 S3StoreError(unexpected,
  RuntimeError)다 — tools가 다시 보내지 않고 Task 오류(운영)로 끝난다. 응답 본문 확인(체크섬) 실패는 일시다.
- 오류 코드는 S3 낱말 모양(AccessDenied)을 소문자 밑줄(access_denied)로 바꿔 넘긴다(s3_error_code) — orchestrator.errors의
  모양 검사(clean_error_code)를 통과해야 시도 설명(status=403 code=access_denied) · 운영 로그에 남는다. 통과하지 못하면 코드 없이.
- 예외 메시지에 버킷 · 객체 이름 · ARN · 접두어 · 리전 · 원래 AWS 메시지를 넣지 않는다(AWS 권한 오류 메시지에는 객체 이름이 든
  ARN이 있다). 메시지는 'S3 일시 오류(<종류>)' · 'S3 오류(status=N)'처럼 종류 · 상태 · 코드뿐이고, 원래 예외는 잇지 않는다
  (부르는 쪽이 raise … from None).
- AWS 라이브러리(botocore)는 오류를 가를 때만 늦게 불러온다 — 이 모듈을 불러와도 불러오지 않는다.
"""
from __future__ import annotations

import functools
import re
from types import ModuleType
from typing import Any

from ..orchestrator.errors import ProviderError, clean_error_code

__all__ = ["KIND_CHECKSUM", "KIND_CONNECTION", "KIND_CREDENTIALS", "KIND_LISTING", "KIND_PARTIAL_DELETE",
           "KIND_SERVER", "KIND_STREAM", "KIND_THROTTLE", "KIND_TIMEOUT", "TEMPORARY_ERROR_CODES",
           "THROTTLING_ERROR_CODES", "TRANSIENT_ERROR_CODES", "S3StoreError", "S3TemporaryError", "S3TimeoutError",
           "delete_errors_problem", "is_credential_error", "is_no_such_key", "s3_error_code", "status_code_text",
           "translate_error"]

# 일시 오류 종류 — 메시지 · 시작 확인 결과에 그대로 나간다(값 없음)
KIND_CONNECTION = "연결 오류"
KIND_TIMEOUT = "시간 초과"
KIND_STREAM = "응답 본문을 읽다 끊김"
KIND_CREDENTIALS = "자격 증명을 얻지 못함"
KIND_THROTTLE = "속도 제한"
KIND_SERVER = "서버 일시 오류"
KIND_PARTIAL_DELETE = "일부 객체를 지우지 못함"
KIND_CHECKSUM = "응답 본문 확인 실패"
KIND_LISTING = "목록 응답에 다음 쪽 표시 없음"

# 일시로 보는 S3 오류 코드 (잠정) — 설치된 botocore 1.43.114 표준 재시도(botocore/retries/standard.py)가 일시
# (TransientRetryableChecker)와 속도 제한(ThrottledRetryableChecker)으로 보는 코드 목록과 같게 둔다. 판을 올리면
# tests/test_store_s3.py가 달라진 것을 알려 준다
TRANSIENT_ERROR_CODES: frozenset[str] = frozenset({
    "RequestTimeout", "RequestTimeoutException", "PriorRequestNotComplete",
})
THROTTLING_ERROR_CODES: frozenset[str] = frozenset({
    "Throttling", "ThrottlingException", "ThrottledException", "RequestThrottledException",
    "TooManyRequestsException", "ProvisionedThroughputExceededException", "TransactionInProgressException",
    "RequestLimitExceeded", "BandwidthLimitExceeded", "LimitExceededException", "RequestThrottled", "SlowDown",
    "PriorRequestNotComplete", "EC2ThrottledException",
})
TEMPORARY_ERROR_CODES: frozenset[str] = TRANSIENT_ERROR_CODES | THROTTLING_ERROR_CODES

NO_SUCH_KEY = "NoSuchKey"
ACCESS_DENIED = "AccessDenied"

# 자격 증명을 얻지 못한 AWS 라이브러리 예외 이름 (botocore/exceptions.py) — 일시로 보고 클라이언트를 버린다.
# EC2에서 서버 역할 자격을 메타데이터로 받지 못하면 대개 NoCredentialsError(서명할 때) · MetadataRetrievalError다
_CREDENTIAL_ERROR_NAMES = (
    "NoCredentialsError", "PartialCredentialsError", "CredentialRetrievalError", "MetadataRetrievalError",
    "TokenRetrievalError", "NoAuthTokenError", "RefreshWithMFAUnsupportedError", "SSOError", "LoginError",
)


def status_code_text(status: int | None, code: str | None) -> str:
    """메시지 꼬리의 'status=N code=X'(값이 있는 것만, 둘 다 없으면 빈 글) — 오류 · 시작 확인 메시지가 함께 쓴다."""
    parts = [f"status={status}"] if status is not None else []
    if code:
        parts.append(f"code={code}")
    return " ".join(parts)


class S3TemporaryError(ConnectionError):
    """일시 저장소 오류 (ConnectionError — tools가 일시로 다시 보내고, 대기열은 '일시'로 다시 시도한다).

    kind: 종류(KIND_*) · status: 응답 상태(없으면 None) · code: 소문자 밑줄 오류 코드(없으면 None) ·
    credentials: 자격 증명을 얻지 못해 난 오류인지(저장소가 클라이언트를 버리고 다음 호출 때 다시 만든다).
    메시지는 'S3 일시 오류(<종류>) (status=N code=X)'뿐이다."""

    def __init__(self, kind: str, *, status: int | None = None, code: str | None = None,
                 credentials: bool = False) -> None:
        code = clean_error_code(code)
        tail = status_code_text(status, code)
        super().__init__(f"S3 일시 오류({kind})" + (f" ({tail})" if tail else ""))
        self.kind = kind
        self.status = status
        self.code = code
        self.credentials = credentials


class S3TimeoutError(TimeoutError):
    """시간 초과 (TimeoutError — tools가 '응답지연'으로 다시 보낸다). 속성은 S3TemporaryError와 같은 이름이다."""

    def __init__(self, kind: str = KIND_TIMEOUT) -> None:
        super().__init__(f"S3 일시 오류({kind})")
        self.kind = kind
        self.status: int | None = None
        self.code: str | None = None
        self.credentials = False


class S3StoreError(RuntimeError):
    """S3 저장소를 만들거나 쓸 수 없음 — 설정 오류 · 코드 오류(영구, OSError가 아니다: tools가 다시 보내지 않는다).

    kind: LIBRARY(AWS 라이브러리 없음 — 패키지를 다시 설치) · REGION(리전 값 없음 · 모양 틀림) · BUCKET · PREFIX(모양 틀림) ·
    CLIENT(클라이언트를 만들지 못함 — 자격 증명 외 이유) · UNEXPECTED(표에 없는 라이브러리 오류). 메시지에 값을 넣지 않는다."""

    LIBRARY = "library"
    REGION = "region"
    BUCKET = "bucket"
    PREFIX = "prefix"
    CLIENT = "client"
    UNEXPECTED = "unexpected"

    MESSAGES = {
        LIBRARY: "AWS 라이브러리(boto3 · botocore)를 불러오지 못함 — 패키지를 다시 설치",
        REGION: "S3 리전 값을 쓸 수 없음",
        BUCKET: "S3 버킷 이름 모양이 틀림",
        PREFIX: "S3 접두어 모양이 틀림",
        CLIENT: "S3 클라이언트를 만들지 못함 — 리전 · AWS 설정을 확인",
        UNEXPECTED: "S3 오류(라이브러리)",
    }

    def __init__(self, kind: str, detail: str | None = None) -> None:
        text = self.MESSAGES.get(kind, "S3 저장소 오류")
        super().__init__(f"{text} — {detail}" if detail else text)
        self.kind = kind


@functools.cache
def _botocore() -> ModuleType | None:
    """botocore.exceptions (늦게 불러옴). 설치되어 있지 않으면 None."""
    try:
        from botocore import exceptions
    except ImportError:
        return None
    return exceptions


def _classes(*names: str) -> tuple[type, ...]:
    bx = _botocore()
    if bx is None:
        return ()
    return tuple(c for c in (getattr(bx, n, None) for n in names) if isinstance(c, type))


def _client_error_fields(e: BaseException) -> tuple[str | None, int | None] | None:
    """ClientError면 (원래 오류 코드, 상태 코드), 아니면 None."""
    if not isinstance(e, _classes("ClientError")):
        return None
    response = getattr(e, "response", None)
    response = response if isinstance(response, dict) else {}
    error = response.get("Error")
    raw = error.get("Code") if isinstance(error, dict) else None
    meta = response.get("ResponseMetadata")
    status = meta.get("HTTPStatusCode") if isinstance(meta, dict) else None
    return (raw if isinstance(raw, str) else None,
            status if isinstance(status, int) and not isinstance(status, bool) else None)


_CAMEL_WORD = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_EDGE = re.compile(r"([a-z0-9])([A-Z])")


def s3_error_code(raw: Any) -> str | None:
    """S3 오류 코드(AccessDenied)를 소문자 밑줄(access_denied)로. 결과가 clean_error_code를 통과하지 못하면 None."""
    if not isinstance(raw, str) or not raw:
        return None
    return clean_error_code(_CAMEL_EDGE.sub(r"\1_\2", _CAMEL_WORD.sub(r"\1_\2", raw)).lower())


def is_no_such_key(e: BaseException) -> bool:
    """객체 없음 — 오류 코드 NoSuchKey인 응답만(상태 404만으로 가르지 않는다)."""
    fields = _client_error_fields(e)
    return fields is not None and fields[0] == NO_SUCH_KEY


def is_credential_error(e: BaseException) -> bool:
    """자격 증명을 얻지 못한 AWS 라이브러리 예외인가."""
    return isinstance(e, _classes(*_CREDENTIAL_ERROR_NAMES))


def _from_response(raw: str | None, status: int | None) -> Exception:
    code = s3_error_code(raw)
    if raw in THROTTLING_ERROR_CODES or status == 429:
        return S3TemporaryError(KIND_THROTTLE, status=status, code=code)
    if raw in TRANSIENT_ERROR_CODES or status is None or status == 408 or status >= 500:
        return S3TemporaryError(KIND_SERVER, status=status, code=code)
    return ProviderError(f"S3 오류(status={status})", status=status, code=code)


def translate_error(e: BaseException) -> Exception:
    """S3 클라이언트 쪽 예외를 저장소 밖으로 내보낼 예외로 바꾼다(표). 이미 바꾼 예외는 그대로 돌려준다.
    NoSuchKey는 부르는 쪽이 먼저 가른다(is_no_such_key) — 여기로 오면 다른 응답처럼 영구(ProviderError 404)다."""
    if isinstance(e, (S3TemporaryError, S3TimeoutError, S3StoreError, ProviderError)):
        return e
    fields = _client_error_fields(e)
    if fields is not None:
        return _from_response(*fields)
    if is_credential_error(e):
        return S3TemporaryError(KIND_CREDENTIALS, credentials=True)
    if isinstance(e, _classes("ReadTimeoutError", "ConnectTimeoutError")):
        return S3TimeoutError()
    if isinstance(e, _classes("ResponseStreamingError", "IncompleteReadError")):
        return S3TemporaryError(KIND_STREAM)
    if isinstance(e, _classes("ConnectionError", "HTTPClientError")):   # botocore의 연결 · HTTP 오류(끊김 포함)
        return S3TemporaryError(KIND_CONNECTION)
    if isinstance(e, _classes("ChecksumError", "FlexibleChecksumError")):
        return S3TemporaryError(KIND_CHECKSUM)
    if isinstance(e, TimeoutError):
        return S3TimeoutError()
    if isinstance(e, OSError):
        return S3TemporaryError(KIND_CONNECTION)
    return S3StoreError(S3StoreError.UNEXPECTED, type(e).__name__)


def delete_errors_problem(errors: list[Any]) -> Exception:
    """여러 객체 지우기 응답의 Errors(일부가 지워지지 않음) → 올릴 예외. 하나라도 일시 코드면 일시, 아니면 AccessDenied는
    ProviderError(403), 그 밖은 일시(대기열이 다시 시도한다). 객체 이름 · 메시지는 싣지 않는다."""
    codes = [err.get("Code") for err in errors if isinstance(err, dict)]
    codes = [c for c in codes if isinstance(c, str)]
    temporary = next((c for c in codes if c in TEMPORARY_ERROR_CODES), None)
    if temporary is not None:
        return S3TemporaryError(KIND_PARTIAL_DELETE, code=s3_error_code(temporary))
    if ACCESS_DENIED in codes:
        return ProviderError("S3 오류(status=403)", status=403, code=s3_error_code(ACCESS_DENIED))
    return S3TemporaryError(KIND_PARTIAL_DELETE, code=s3_error_code(codes[0]) if codes else None)
