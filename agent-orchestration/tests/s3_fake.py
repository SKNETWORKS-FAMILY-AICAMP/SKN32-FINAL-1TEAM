"""가짜 S3 클라이언트 — S3 파일 저장소(sbrain.store_s3.S3FileStore) 시험용 도움 모듈.

- 저장소가 부르는 클라이언트 메서드만 흉내 낸다: get_object · put_object · delete_object · delete_objects ·
  list_objects_v2(쪽 나눔 포함). 객체는 메모리에 둔다. 네트워크 · ~/.aws에 닿지 않는다(실제 클라이언트를 만들지 않는다).
- 정한 호출에서 AWS 라이브러리의 진짜 오류 타입(botocore.exceptions.ClientError 등)을 정한 횟수만큼 올린다(inject).
  오류 메시지에는 일부러 버킷 · 객체 이름 · ARN · 주소를 넣는다 — 저장소 밖으로 값이 새지 않는지 시험하려는 것이다.
- 실제 S3처럼: 없는 객체 읽기는 NoSuchKey(404) — 목록 권한이 없으면(list_permission=False) AccessDenied(403),
  없는 버킷은 NoSuchBucket(404), 여러 개 지우기는 1,000개를 넘으면 MalformedXML(400).
- 여러 스레드에서 함께 써도 된다(잠금).

쓰는 법:
    store, fake = fake_s3_store()                       # 가짜 클라이언트를 주입한 저장소 (접두어 PREFIX)
    fake.inject("put_object", "access_denied")          # 다음 put_object 한 번이 403
    fake.inject("get_object", "slow_down", times=2, match=".meta.json")
    fake.inject("read_body", "streaming")               # 응답 본문을 읽다 끊김
    fake.tamper_reads(b"other")                         # 다음 get_object 한 번이 다른 내용을 돌려줌
    fake.fail_in_delete("AccessDenied")                 # 다음 delete_objects 한 번에서 첫 객체가 지워지지 않음
    fake.fail_in_delete("AccessDenied", "SlowDown")     # 앞의 두 객체가 각각 그 코드로 지워지지 않음
    regions = patch_client_factory(monkeypatch, fake)   # 주입 없이 만든 저장소가 처음 쓸 때 이 가짜를 받게 함
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from botocore import exceptions as bx

from sbrain.store_s3 import S3FileStore

BUCKET = "sbrain-test-bucket"
PREFIX = "app/artifacts/"
REGION = "ap-northeast-2"
ACCOUNT_ARN = "arn:aws:iam::123456789012:role/sbrain-worker"

# 이름 → (S3 오류 코드, 상태 코드). ClientError로 만든다
CLIENT_ERRORS: dict[str, tuple[str, int]] = {
    "no_such_key": ("NoSuchKey", 404),
    "access_denied": ("AccessDenied", 403),
    "no_such_bucket": ("NoSuchBucket", 404),
    "invalid_request": ("InvalidRequest", 400),
    "internal_error": ("InternalError", 500),
    "service_unavailable": ("ServiceUnavailable", 503),
    "slow_down": ("SlowDown", 503),
    "request_timeout": ("RequestTimeout", 400),       # S3의 RequestTimeout은 400이지만 일시 코드다
    "throttling": ("Throttling", 400),
    "status_408": ("Unknown408", 408),
    "status_429": ("TooManyRequests", 429),
    "malformed_xml": ("MalformedXML", 400),
}
# 이름 → 그 밖의 라이브러리 오류
OTHER_ERRORS = ("connection", "connect_timeout", "read_timeout", "connection_closed", "streaming", "incomplete",
                "no_credentials", "partial_credentials", "credential_retrieval", "metadata_retrieval",
                "param_validation")


def _endpoint(bucket: str, key: str | None) -> str:
    return f"https://{bucket}.s3.{REGION}.amazonaws.com/{key or ''}"


def client_error(code: str, status: int | None, *, operation: str = "GetObject", bucket: str = BUCKET,
                 key: str | None = None, message: str | None = None) -> bx.ClientError:
    """botocore ClientError — 메시지에 ARN(버킷 · 객체 이름)을 넣는다(실제 권한 오류 메시지와 같은 모양)."""
    resource = f"arn:aws:s3:::{bucket}/{key}" if key else f"arn:aws:s3:::{bucket}"
    text = message or (f"User: {ACCOUNT_ARN} is not authorized to perform: s3:{operation} "
                       f"on resource: \"{resource}\" because no identity-based policy allows the action")
    error: dict[str, Any] = {"Code": code, "Message": text, "BucketName": bucket}
    if key:
        error["Key"] = key
    meta: dict[str, Any] = {"HTTPHeaders": {"x-amz-bucket-region": REGION}, "RequestId": "REQ123"}
    if status is not None:
        meta["HTTPStatusCode"] = status
    return bx.ClientError({"Error": error, "ResponseMetadata": meta}, operation)


def make_error(kind: str, *, bucket: str = BUCKET, key: str | None = None,
               operation: str = "GetObject") -> BaseException:
    """이름으로 진짜 botocore 오류를 만든다. 메시지 · 속성에 버킷 · 객체 이름 · 주소가 들어 있다."""
    if kind in CLIENT_ERRORS:
        code, status = CLIENT_ERRORS[kind]
        return client_error(code, status, operation=operation, bucket=bucket, key=key)
    url = _endpoint(bucket, key)
    if kind == "connection":
        return bx.EndpointConnectionError(endpoint_url=url)
    if kind == "connect_timeout":
        return bx.ConnectTimeoutError(endpoint_url=url)
    if kind == "read_timeout":
        return bx.ReadTimeoutError(endpoint_url=url)
    if kind == "connection_closed":
        return bx.ConnectionClosedError(endpoint_url=url)
    if kind == "streaming":
        return bx.ResponseStreamingError(error=f"Connection broken while reading {url}")
    if kind == "incomplete":
        return bx.IncompleteReadError(actual_bytes=3, expected_bytes=10)
    if kind == "no_credentials":
        return bx.NoCredentialsError()
    if kind == "partial_credentials":
        return bx.PartialCredentialsError(provider="env", cred_var="aws_secret_access_key")
    if kind == "credential_retrieval":
        return bx.CredentialRetrievalError(provider="iam-role", error_msg=f"{ACCOUNT_ARN} 자격 증명을 받지 못함")
    if kind == "metadata_retrieval":
        return bx.MetadataRetrievalError(error_msg=f"IMDS 응답 없음 — {ACCOUNT_ARN}")
    if kind == "param_validation":
        return bx.ParamValidationError(report=f"Invalid bucket name \"{bucket}\" key \"{key}\"")
    raise KeyError(kind)


@dataclass
class _Fault:
    method: str
    error: Any                      # 이름 · 예외 · (key) -> 예외
    times: int
    match: Callable[[str | None], bool]


@dataclass
class _Stored:
    data: bytes
    content_type: str | None


class FakeBody:
    """get_object 응답의 Body — read() · close()만. 읽다가 오류를 낼 수 있다."""

    def __init__(self, data: bytes, error: BaseException | None = None) -> None:
        self._data, self._error = data, error
        self.closed = False

    def read(self, amt: int | None = None) -> bytes:
        if self._error is not None:
            raise self._error
        return self._data

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeS3Client:
    """가짜 S3 클라이언트. objects: {버킷: {객체 이름: _Stored}}. calls: (메서드, 객체 이름 · 접두어 · 개수) 순서 기록."""

    buckets: tuple[str, ...] = (BUCKET,)
    page_size: int = 1000           # list_objects_v2 한 쪽의 최대 개수(MaxKeys와 작은 쪽)
    list_permission: bool = True    # 거짓이면 없는 객체 읽기가 AccessDenied(403) — 목록 권한 없는 버킷
    objects: dict[str, dict[str, _Stored]] = field(default_factory=dict)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._faults: list[_Fault] = []
        self._tampered: list[tuple[bytes, int, Callable[[str | None], bool]]] = []
        self._delete_failures: list[tuple[tuple[str, ...], int]] = []   # (앞 객체마다의 코드, 남은 횟수)
        for b in self.buckets:
            self.objects.setdefault(b, {})

    # ── 시험 조작 ─────────────────────────────────────
    def inject(self, method: str, error: Any, *, times: int = 1, match: str | Callable[[str | None], bool] | None = None
               ) -> None:
        """method 호출(또는 'read_body' — 응답 본문 읽기)에서 error를 times번 올린다. match는 객체 이름에 든 글자 또는 판정 함수."""
        if isinstance(match, str):
            text = match
            pred: Callable[[str | None], bool] = lambda key: key is not None and text in key   # noqa: E731
        else:
            pred = match or (lambda key: True)
        with self._lock:
            self._faults.append(_Fault(method, error, times, pred))

    def tamper_reads(self, data: bytes, *, times: int = 1, match: str | None = None) -> None:
        """다음 get_object times번이 저장된 내용 대신 data를 돌려준다(읽은 내용이 다름)."""
        pred = (lambda key: key is not None and match in key) if match else (lambda key: True)
        with self._lock:
            self._tampered.append((data, times, pred))

    def fail_in_delete(self, *codes: str, times: int = 1) -> None:
        """다음 delete_objects times번에서 앞의 객체들을 지우지 않고 Errors에 차례로 codes로 돌려준다(일부 실패)."""
        with self._lock:
            self._delete_failures.append((tuple(codes), times))

    def keys(self, bucket: str = BUCKET) -> list[str]:
        with self._lock:
            return sorted(self.objects.get(bucket, {}))

    def put_raw(self, key: str, data: bytes, content_type: str | None = None, bucket: str = BUCKET) -> None:
        with self._lock:
            self.objects.setdefault(bucket, {})[key] = _Stored(bytes(data), content_type)

    def remove_raw(self, key: str, bucket: str = BUCKET) -> None:
        with self._lock:
            self.objects.get(bucket, {}).pop(key, None)

    def stored(self, key: str, bucket: str = BUCKET) -> _Stored | None:
        with self._lock:
            return self.objects.get(bucket, {}).get(key)

    def methods(self) -> list[str]:
        with self._lock:
            return [m for m, _ in self.calls]

    # ── 안 ───────────────────────────────────────────
    def _take_fault(self, method: str, key: str | None, bucket: str, operation: str) -> BaseException | None:
        with self._lock:
            for f in self._faults:
                if f.method == method and f.times > 0 and f.match(key):
                    f.times -= 1
                    err = f.error
                    if isinstance(err, BaseException):
                        return err
                    if isinstance(err, str):
                        return make_error(err, bucket=bucket, key=key, operation=operation)
                    return err(key)
        return None

    def _check_bucket(self, bucket: str, operation: str) -> dict[str, _Stored]:
        if bucket not in self.objects:
            raise client_error("NoSuchBucket", 404, operation=operation, bucket=bucket,
                               message=f"The specified bucket does not exist: {bucket}")
        return self.objects[bucket]

    # ── 클라이언트 메서드 ───────────────────────────────
    def get_object(self, *, Bucket: str, Key: str, **kw: Any) -> dict[str, Any]:
        with self._lock:
            self.calls.append(("get_object", Key))
            fault = self._take_fault("get_object", Key, Bucket, "GetObject")
            if fault is not None:
                raise fault
            found = self._check_bucket(Bucket, "GetObject").get(Key)
            if found is None:
                if self.list_permission:
                    raise client_error("NoSuchKey", 404, bucket=Bucket, key=Key,
                                       message=f"The specified key does not exist: {Key}")
                raise client_error("AccessDenied", 403, bucket=Bucket, key=Key)
            data = found.data
            for i, (alt, times, pred) in enumerate(self._tampered):
                if times > 0 and pred(Key):
                    self._tampered[i] = (alt, times - 1, pred)
                    data = alt
                    break
            body_error = self._take_fault("read_body", Key, Bucket, "GetObject")
        return {"Body": FakeBody(data, body_error), "ContentType": found.content_type, "ContentLength": len(data)}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str | None = None,
                   **kw: Any) -> dict[str, Any]:
        with self._lock:
            self.calls.append(("put_object", Key))
            fault = self._take_fault("put_object", Key, Bucket, "PutObject")
            if fault is not None:
                raise fault
            self._check_bucket(Bucket, "PutObject")[Key] = _Stored(bytes(Body), ContentType)
        return {"ETag": "\"etag\""}

    def delete_object(self, *, Bucket: str, Key: str, **kw: Any) -> dict[str, Any]:
        with self._lock:
            self.calls.append(("delete_object", Key))
            fault = self._take_fault("delete_object", Key, Bucket, "DeleteObject")
            if fault is not None:
                raise fault
            self._check_bucket(Bucket, "DeleteObject").pop(Key, None)
        return {}

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any], **kw: Any) -> dict[str, Any]:
        names = [o["Key"] for o in Delete.get("Objects", [])]
        with self._lock:
            self.calls.append(("delete_objects", len(names)))
            fault = self._take_fault("delete_objects", names[0] if names else None, Bucket, "DeleteObjects")
            if fault is not None:
                raise fault
            bucket = self._check_bucket(Bucket, "DeleteObjects")
            if not names or len(names) > 1000:
                raise client_error("MalformedXML", 400, operation="DeleteObjects", bucket=Bucket)
            failing: dict[str, str] = {}
            for i, (codes, times) in enumerate(self._delete_failures):
                if times > 0:
                    self._delete_failures[i] = (codes, times - 1)
                    failing = dict(zip(names, codes))
                    break
            errors = []
            for name in names:
                if name in failing:
                    errors.append({"Key": name, "Code": failing[name],
                                   "Message": f"Access Denied for arn:aws:s3:::{Bucket}/{name}"})
                else:
                    bucket.pop(name, None)
        return {"Errors": errors} if errors else {}

    def list_objects_v2(self, *, Bucket: str, Prefix: str = "", ContinuationToken: str | None = None,
                        MaxKeys: int = 1000, **kw: Any) -> dict[str, Any]:
        with self._lock:
            self.calls.append(("list_objects_v2", Prefix))
            fault = self._take_fault("list_objects_v2", Prefix, Bucket, "ListObjectsV2")
            if fault is not None:
                raise fault
            names = sorted(k for k in self._check_bucket(Bucket, "ListObjectsV2") if k.startswith(Prefix))
        start = int(ContinuationToken.removeprefix("tok-")) if ContinuationToken else 0
        size = min(MaxKeys, self.page_size)
        page = names[start:start + size]
        out: dict[str, Any] = {"KeyCount": len(page), "IsTruncated": start + size < len(names), "Prefix": Prefix}
        if page:   # 실제 S3처럼 비면 Contents가 없다
            out["Contents"] = [{"Key": k, "Size": len(self.objects[Bucket][k].data)} for k in page]
        if out["IsTruncated"]:
            out["NextContinuationToken"] = f"tok-{start + size}"
        return out


def fake_s3_store(fake: FakeS3Client | None = None, *, prefix: str = PREFIX, read_only: bool = False,
                  bucket: str = BUCKET, region: str = REGION) -> tuple[S3FileStore, FakeS3Client]:
    """가짜 클라이언트를 주입한 S3 저장소와 그 가짜."""
    fake = fake or FakeS3Client()
    return S3FileStore(bucket, prefix, region, read_only=read_only, client=fake), fake


def patch_client_factory(monkeypatch: Any, make: FakeS3Client | Callable[[str], Any]) -> list[str]:
    """sbrain.store_s3.client.make_s3_client를 바꿔 끼운다 — 주입 없이 만든 저장소가 처음 쓸 때 이것을 부른다.

    make가 가짜 클라이언트면 그것을, 함수면 make(region)의 결과를 돌려준다. 돌려준 목록에 부를 때마다 리전이 쌓인다."""
    from sbrain.store_s3 import client as s3_client

    regions: list[str] = []

    def factory(region: str) -> Any:
        regions.append(region)
        return make(region) if callable(make) else make
    monkeypatch.setattr(s3_client, "make_s3_client", factory)
    return regions
