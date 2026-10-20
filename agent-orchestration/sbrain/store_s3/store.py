"""S3 파일 저장소 — orchestrator.files의 FileStore 약속(쓰기 · 읽기 · 메타데이터 · 접두어째 지우기)을 S3로 지킨다.

| 창구 | S3에서 |
|---|---|
| 키 → 객체 | 객체 이름 = 접두어 + 키. 메타데이터는 같은 마디의 옆 객체 '<접두어><runId>/<executionId>/<고유값>/.<name>.meta.json'
|            | (로컬 폴더의 옆 파일과 같은 이름 · 같은 JSON — FileMeta.to_json). 키 규칙은 저장소에서 다시 검사한다 |
| write      | ① 메타 객체를 읽어 이미 있으면 같으면 성공(재시도 안전), 다르면 FileConflict ② 없으면 내용 객체(Content-Type =
|            | media_type) → 메타 객체(JSON) 순서로 쓴다. 메타 객체가 있어야 '있는 파일'이다 |
| read       | 메타 객체가 없으면 FileMissing, 내용 객체가 없어도 FileMissing |
| meta       | 메타 객체가 없으면 None |
| delete_prefix | 접두어 규칙을 메모리 · 로컬 폴더와 같게 검사하고, 접두어 + prefix 아래 객체를 목록(쪽 나눔)으로 받아 1,000개씩 지운다.
|            | 이미 없으면 성공. 일부가 지워지지 않았으면 오류(errors.delete_errors_problem — 대기열이 다시 시도한다) |
| 읽기 전용  | write · delete_prefix → FileStoreReadOnly(S3를 부르지 않음) |

- 메타 · 내용 읽기는 HEAD가 아니라 객체 읽기(GetObject)다 — HEAD 응답에는 오류 코드 본문이 없어 NoSuchKey와 NoSuchBucket을
  가를 수 없다. 메타 객체가 없을 때 None이 되려면 버킷 목록 권한(s3:ListBucket)이 필요하다(없으면 S3가 없는 객체에도 403).
- 오류는 errors.translate_error 표로만 바꿔 올린다(raise … from None). 저장소 안에서 기다리거나 다시 부르지 않는다 —
  재시도 규칙은 tools 한 곳이다.
- 클라이언트: 저장소를 만들 때는 만들지 않는다(S3 · EC2 메타데이터에 닿지 않음). 처음 쓸 때 client.make_s3_client(모듈 속성으로
  찾음 — 테스트가 바꿔 끼움)로 잠금 안에서 한 번 만들고 여러 스레드가 함께 쓴다(S3 클라이언트는 스레드 안전). 자격 증명을 얻지 못해
  실패하면 그 클라이언트를 버리고 다음 호출 때 다시 만든다. 시험용으로 주입한 클라이언트는 버리지 않는다.
  - 처음 쓸 때 클라이언트 만들기가 실패하면: ImportError → S3StoreError(library), 자격 증명 예외 → S3TemporaryError(자격 증명,
    일시 — 다음 호출 때 다시 만듦), 그 밖(설정 파일 · 프로필 오류 등) → S3StoreError(client). S3StoreError는 RuntimeError라
    tools가 다시 보내지 않고 Task 오류(운영)로, 대기열은 '운영'으로 끝난다. 워커 시작 확인(probe.check_s3_store)은 영구 문제로 돌려준다.
- 만들 때 확인(S3StoreError로 올림 — 조립이 잡는다): 버킷 이름 · 접두어 모양, 리전 값 없음. 클라이언트를 주입하지 않았으면
  AWS 라이브러리를 늦게 불러오고(없으면 library) 리전 값 모양을 라이브러리 검사로 미리 본다(클라이언트는 만들지 않음).
- 객체 이름 길이: 접두어 200자 + 키(마디 100자 이하 넷) + 옆 객체 꼬리 — S3 상한(1,024바이트) 안이다.
- 메시지 · repr에 버킷 · 접두어 · 리전 · 키를 넣지 않는다.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable, TypeVar

from ..models.files import file_key_problem, file_prefix_problem
from ..orchestrator.files import FileConflict, FileMeta, FileMissing, FileStoreReadOnly, LocalFolderFileStore
from . import client as _factory
from .address import bucket_name_problem, normalize_prefix, prefix_problem, split_s3_address
from .errors import (
    KIND_CREDENTIALS, KIND_LISTING, S3StoreError, S3TemporaryError, delete_errors_problem, is_credential_error,
    is_no_such_key, translate_error,
)

__all__ = ["S3FileStore"]

T = TypeVar("T")


class S3FileStore:
    """S3 파일 저장소. S3FileStore(버킷, 접두어, 리전, *, read_only=False, client=None).

    - 접두어는 정리해 둔다('app/artifacts' → 'app/artifacts/', 없으면 '' = 버킷 맨 위). 속성 bucket · prefix · region · read_only.
    - client: 시험용으로 주입하는 클라이언트(tests/s3_fake.py FakeS3Client). 주입하면 AWS 라이브러리를 부르지 않는다.
    """

    META_SUFFIX = LocalFolderFileStore.META_SUFFIX   # 로컬 폴더 옆 파일과 같은 꼬리 '.meta.json'
    META_CONTENT_TYPE = "application/json"          # 메타 객체의 형식 표시 (잠정)
    DELETE_BATCH = 1000                             # 여러 객체 지우기 한 번의 상한 (S3 API 값)

    def __init__(self, bucket: str, prefix: str = "", region: str | None = None, *, read_only: bool = False,
                 client: Any = None) -> None:
        problem = bucket_name_problem(bucket)
        if problem is not None:
            raise S3StoreError(S3StoreError.BUCKET, problem)
        problem = prefix_problem(prefix)
        if problem is not None:
            raise S3StoreError(S3StoreError.PREFIX, problem)
        if not isinstance(region, str) or not region.strip():
            raise S3StoreError(S3StoreError.REGION, "값 없음")
        if client is None:
            try:
                _factory.load_library()
            except ImportError:
                raise S3StoreError(S3StoreError.LIBRARY) from None
            if not _factory.region_shape_ok(region):
                raise S3StoreError(S3StoreError.REGION, "모양이 틀림")
        self.bucket = bucket
        self.prefix = normalize_prefix(prefix)
        self.region = region
        self.read_only = read_only
        self._client = client
        self._injected = client is not None
        self._lock = threading.Lock()

    @classmethod
    def from_address(cls, address: str, region: str | None, *, read_only: bool = False,
                     client: Any = None) -> "S3FileStore":
        """'s3://<버킷>[/<접두어>]'로 만든다. S3 주소 모양이 아니면 ValueError, 버킷 · 접두어 모양이 틀리면 S3StoreError."""
        bucket, path = split_s3_address(address)
        return cls(bucket, path, region, read_only=read_only, client=client)

    def __repr__(self) -> str:
        return f"S3FileStore(read_only={self.read_only})"

    # ── 클라이언트 ─────────────────────────────────────
    def _client_now(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = self._new_client()
            return self._client

    def _new_client(self) -> Any:
        try:
            return _factory.make_s3_client(self.region)   # 모듈 속성으로 찾는다 — 테스트가 바꿔 끼운다
        except ImportError:
            raise S3StoreError(S3StoreError.LIBRARY) from None
        except Exception as e:
            if is_credential_error(e):
                raise S3TemporaryError(KIND_CREDENTIALS, credentials=True) from None
            raise S3StoreError(S3StoreError.CLIENT) from None

    def _drop_client(self, client: Any) -> None:
        """자격 증명 실패 뒤 — 그 클라이언트를 버린다(다른 스레드가 이미 바꿨으면 그대로). 주입한 클라이언트는 버리지 않는다."""
        if self._injected:
            return
        with self._lock:
            if self._client is client:
                self._client = None

    def _call(self, fn: Callable[[Any], T], *, missing_ok: bool = False) -> T | None:
        """클라이언트 호출 하나. 실패는 표대로 바꿔 올린다(원래 예외를 잇지 않음). missing_ok면 NoSuchKey는 None."""
        client = self._client_now()
        try:
            return fn(client)
        except Exception as e:
            if missing_ok and is_no_such_key(e):
                return None
            err = translate_error(e)
            if isinstance(err, S3TemporaryError) and err.credentials:
                self._drop_client(client)
            raise err from None

    # ── 객체 (이 패키지 안 — 시작 확인도 쓴다) ─────────────────
    def _get_object(self, name: str) -> bytes | None:
        """객체 내용. 없으면(NoSuchKey) None. 응답 본문을 읽다 나는 오류도 같은 표를 따른다."""
        def op(c: Any) -> bytes:
            body = c.get_object(Bucket=self.bucket, Key=name)["Body"]
            try:
                return bytes(body.read())
            finally:
                try:
                    body.close()
                except Exception:   # 닫기 실패는 읽은 결과와 관계없다
                    pass
        return self._call(op, missing_ok=True)

    def _put_object(self, name: str, data: bytes, content_type: str) -> None:
        self._call(lambda c: c.put_object(Bucket=self.bucket, Key=name, Body=data, ContentType=content_type))

    def _delete_object(self, name: str) -> None:
        self._call(lambda c: c.delete_object(Bucket=self.bucket, Key=name))

    def _list(self, head: str) -> list[str]:
        """head로 시작하는 객체 이름 전부(쪽 나눔)."""
        names: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": head}
            if token is not None:
                kwargs["ContinuationToken"] = token
            page = self._call(lambda c: c.list_objects_v2(**kwargs)) or {}
            names.extend(o["Key"] for o in page.get("Contents") or []
                         if isinstance(o.get("Key"), str) and o["Key"].startswith(head))
            if not page.get("IsTruncated"):
                return names
            token = page.get("NextContinuationToken")
            if not token:   # 다음 쪽이 있다면서 표시가 없음 — 끝없이 돌지 않게 일시 오류로(대기열이 다시 시도)
                raise S3TemporaryError(KIND_LISTING)

    # ── 이름 ─────────────────────────────────────────
    def _object_name(self, key: str) -> str:
        problem = file_key_problem(key)
        if problem is not None:
            raise ValueError(f"키 규칙 위반 — {problem}")
        return self.prefix + key

    def _meta_name(self, key: str) -> str:
        head, name = key.rsplit("/", 1)
        return f"{self.prefix}{head}/.{name}{self.META_SUFFIX}"

    def _read_meta(self, key: str) -> FileMeta | None:
        raw = self._get_object(self._meta_name(key))
        if raw is None:
            return None
        return FileMeta.from_json(json.loads(raw.decode("utf-8")))

    def _check_writable(self) -> None:
        if self.read_only:
            raise FileStoreReadOnly("읽기 전용 파일 저장소 — 웹 프로세스는 파일을 쓰거나 지우지 않는다")

    # ── 창구 ─────────────────────────────────────────
    def write(self, key: str, data: bytes, meta: FileMeta) -> None:
        self._check_writable()
        name = self._object_name(key)
        existing = self._read_meta(key)
        if existing is not None:
            if existing == meta:
                return
            raise FileConflict("같은 키에 다른 내용")
        self._put_object(name, bytes(data), meta.media_type)   # 내용 객체의 형식 표시 = 넣을 때 정한 형식 (잠정)
        self._put_object(self._meta_name(key), json.dumps(meta.to_json(), ensure_ascii=False).encode("utf-8"),
                         self.META_CONTENT_TYPE)

    def read(self, key: str) -> bytes:
        name = self._object_name(key)
        if self._read_meta(key) is None:
            raise FileMissing("없는 파일")
        data = self._get_object(name)
        if data is None:
            raise FileMissing("없는 파일")
        return data

    def meta(self, key: str) -> FileMeta | None:
        self._object_name(key)
        return self._read_meta(key)

    def delete_prefix(self, prefix: str) -> None:
        self._check_writable()
        problem = file_prefix_problem(prefix)   # 메모리 · 로컬 폴더 저장소와 같은 규칙 하나(models.files)
        if problem is not None:
            raise ValueError(f"접두어 규칙 위반 — {problem}")
        head = self.prefix + (prefix if prefix.endswith("/") else prefix + "/")
        names = self._list(head)
        for start in range(0, len(names), self.DELETE_BATCH):
            chunk = [{"Key": n} for n in names[start:start + self.DELETE_BATCH]]
            reply = self._call(lambda c: c.delete_objects(Bucket=self.bucket,
                                                          Delete={"Objects": chunk, "Quiet": True})) or {}
            errors = reply.get("Errors") or []
            if errors:
                raise delete_errors_problem(errors) from None
