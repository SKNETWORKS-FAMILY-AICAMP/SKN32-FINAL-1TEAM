"""S3 파일 저장소 sbrain.store_s3 — 가짜 S3 클라이언트(tests/s3_fake.py)로만 시험한다.

- 주소 해석(s3://<버킷>[/<접두어>]) — AWS 라이브러리 없이 불러와 돈다
- 키 → 객체 이름 · 메타 객체 이름, 쓰기 순서(메타 확인 → 내용 → 메타), 같은 내용 다시 쓰기 · 다른 내용, 없는 키 · 메타 없음
- 접두어째 지우기(1,000개 넘음 · 쪽 나눔 · 일부 실패 → 오류 · 이미 없음 · 접두어 규칙), 읽기 전용, 키 규칙 위반
- 오류 바꾸기 표(없음 · 일시 · 영구)와 오류 코드 소문자 밑줄, 메시지에 버킷 · 키 · 접두어 · ARN 없음, tools · 대기열 분류
- 클라이언트: 저장소를 만들 때는 만들지 않음, 처음 쓸 때 한 번, 자격 증명 실패 뒤 다시 만듦, 주입한 것은 버리지 않음,
  라이브러리 설정 값(재시도 끔 · 시간 제한) — 실제 클라이언트는 만들지 않는다
- 시작 확인(성공 · 영구 · 일시 경우 전부), 여러 스레드
테스트는 네트워크에 나가지 않고 실제 AWS 클라이언트를 만들지 않는다(conftest 자동 장치가 막는다).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from botocore import exceptions as bx
from conftest import REAL_MAKE_S3_CLIENT
from s3_fake import (
    BUCKET, PREFIX, REGION, FakeS3Client, client_error, fake_s3_store, make_error, patch_client_factory,
)

from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import ProviderError, ToolCallExhausted, clean_error_code
from sbrain.orchestrator.file_deletion import error_kind_of
from sbrain.orchestrator.files import FileConflict, FileMeta, FileMissing, FileStoreReadOnly, MemoryFileStore
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext
from sbrain.store_s3 import (
    PREFIX_MAX_LEN, PROBE_DIR, S3Address, S3CheckResult, S3FileStore, S3StartupCheckFailed, S3StoreError,
    S3TemporaryError, S3TimeoutError, TEMPORARY_ERROR_CODES, bucket_name_problem, check_s3_store, is_s3_address,
    normalize_prefix, parse_s3_address, prefix_problem, s3_address_problem, s3_error_code,
)
from sbrain.store_s3 import client as s3_client
from sbrain.store_s3 import errors as s3_errors
from sbrain.store_s3 import probe as s3_probe

CODE_DIR = Path(__file__).resolve().parent.parent
ORCHESTRATOR_DIR = CODE_DIR / "sbrain" / "orchestrator"
HTML = "text/html"
KEY = "r1/e1/u1/index.html"


def _meta(data: bytes, name: str = "index.html", media: str = HTML) -> FileMeta:
    return FileMeta(name=name, media_type=media, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def _no_values(e: BaseException, *extra: str) -> None:
    """예외 글 · repr에 버킷 · 객체 이름 · 접두어 · ARN · 주소가 없고, 원래 예외를 잇지 않았다."""
    text = f"{e} {e!r} {e.args!r}"
    for secret in (BUCKET, "r1/e1", "u1/index", PREFIX.rstrip("/"), "arn:", "amazonaws", "123456789012", *extra):
        assert secret not in text, secret
    assert e.__cause__ is None and (e.__context__ is None or e.__suppress_context__)


# ── 주소 해석 ───────────────────────────────────────────────

@pytest.mark.parametrize(("value", "bucket", "prefix"), [
    ("s3://sbrain-bucket", "sbrain-bucket", ""),
    ("s3://sbrain-bucket/", "sbrain-bucket", ""),
    ("s3://sbrain-bucket///", "sbrain-bucket", ""),
    ("s3://sbrain-deploybucket-abc/app/artifacts/", "sbrain-deploybucket-abc", "app/artifacts/"),
    ("s3://sbrain-deploybucket-abc/app/artifacts", "sbrain-deploybucket-abc", "app/artifacts/"),
    ("s3://a.b-c/x//", "a.b-c", "x/"),
    ("s3://abc//lead/trail//", "abc", "lead/trail/"),
    ("s3://123/A_b.c-D/.hidden", "123", "A_b.c-D/.hidden/"),
    ("s3://" + "a" * 63 + "/p", "a" * 63, "p/"),
])
def test_parse_s3_address(value, bucket, prefix):
    assert is_s3_address(value)
    assert s3_address_problem(value) is None
    addr = parse_s3_address(value)
    assert (addr.bucket, addr.prefix) == (bucket, prefix)
    assert bucket not in repr(addr) and (not prefix or prefix not in repr(addr))   # repr에 값을 싣지 않는다


@pytest.mark.parametrize("value", [
    "s3://", "s3:///app", "s3://ab", "s3://" + "a" * 64, "s3://Bucket", "s3://-abc", "s3://abc-", "s3://.abc",
    "s3://abc.", "s3://a..bc", "s3://a_bc", "s3://ab c", "s3://abc/a//b", "s3://abc/a/../b", "s3://abc/./b",
    "s3://abc/..", "s3://abc/a b", "s3://abc/한글", "s3://abc/a\\b", "s3://abc/a:b",
    "s3://abc/" + "p" * (PREFIX_MAX_LEN + 1),
])
def test_bad_s3_addresses(value):
    assert is_s3_address(value)
    problem = s3_address_problem(value)
    assert problem is not None
    rest = value.removeprefix("s3://")
    for part in (rest, rest.split("/", 1)[0]):
        if len(part) >= 3:
            assert part not in problem                                      # 문제 종류만 — 값은 싣지 않는다
    with pytest.raises(ValueError) as e:
        parse_s3_address(value)
    assert str(e.value) == problem


@pytest.mark.parametrize("value", ["S3://sbrain-bucket", "s3:/sbrain-bucket", "/var/sbrain/artifacts", "C:/x",
                                   "relative/path", "", None, 3, " s3://sbrain-bucket"])
def test_not_s3_addresses(value):
    assert not is_s3_address(value)                                        # 스킴은 소문자 s3://만
    assert s3_address_problem(value) is not None
    with pytest.raises(ValueError):
        parse_s3_address(value)


def test_prefix_rules_and_length_limit():
    assert normalize_prefix("") == "" and normalize_prefix("/") == ""
    assert normalize_prefix("/a/b/") == "a/b/" and normalize_prefix("a") == "a/"
    exact = "/".join(["p" * 99, "q" * 99])                                  # 99 + 1 + 99 + 끝 '/' = 200
    assert normalize_prefix(exact) == exact + "/" and len(exact + "/") == PREFIX_MAX_LEN
    assert prefix_problem(exact + "x") is not None                          # 201자
    for bad in ("a//b", "./a", "a/..", "a b", "a+b", "a%2Fb"):
        assert prefix_problem(bad) is not None
        with pytest.raises(ValueError):
            normalize_prefix(bad)
    assert prefix_problem("ok/prefix") is None


def test_bucket_name_rules():
    for good in ("abc", "a-b.c", "1bucket9", "x" * 63, "my.bucket.name"):
        assert bucket_name_problem(good) is None
    for bad in ("", "ab", "x" * 64, "Abc", "a_b", "-ab", "ab-", ".ab", "ab.", "a..b", "a b", None, 5):
        assert bucket_name_problem(bad) is not None


def test_address_is_frozen_value():
    addr = parse_s3_address("s3://sbrain-bucket/app")
    assert addr == S3Address(bucket="sbrain-bucket", prefix="app/")
    with pytest.raises(AttributeError):
        addr.bucket = "other"   # type: ignore[misc]


def test_package_import_does_not_load_aws_library():
    """패키지를 불러오고 주소를 해석해도 AWS 라이브러리(boto3 · botocore)를 불러오지 않는다 — 새 프로세스에서 본다."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import sbrain.store_s3 as s; "
            "a = s.parse_s3_address('s3://sbrain-bucket/app/artifacts'); "
            "print(a.bucket == 'sbrain-bucket', a.prefix == 'app/artifacts/', s.is_s3_address('/x'), "
            "sorted(m for m in sys.modules if m.split('.')[0] in ('boto3', 'botocore', 's3transfer')))")
    out = subprocess.run([sys.executable, "-c", code, str(CODE_DIR)], capture_output=True, text=True,
                         timeout=120, cwd=str(CODE_DIR))
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "True True False []"


def test_engine_folder_does_not_import_aws_library():
    # 엔진 폴더는 AWS 라이브러리도 S3 저장소 패키지도 불러오지 않는다(S3를 고르는 곳은 조립뿐)
    pattern = re.compile(r"^\s*(?:import|from)\s+(?:boto3|botocore|s3transfer|sbrain\.store_s3|\.\.store_s3)\b"
                         r"|^\s*from\s+(?:\.\.|sbrain)\s+import\s+[^\n]*\bstore_s3\b"
                         r"|^\s*import\s+[^\n]*\bsbrain\.store_s3\b", re.M)
    found = [f.name for f in ORCHESTRATOR_DIR.rglob("*.py") if pattern.search(f.read_text(encoding="utf-8"))]
    assert found == []


# ── 키 → 객체 · 쓰기 · 읽기 ───────────────────────────────────

def test_objects_are_prefix_plus_key_and_side_meta():
    store, fake = fake_s3_store()
    data = b"<html></html>"
    store.write(KEY, data, _meta(data))
    content = fake.stored(PREFIX + KEY)
    meta_obj = fake.stored(PREFIX + "r1/e1/u1/.index.html.meta.json")      # 로컬 폴더 옆 파일과 같은 이름
    assert content is not None and content.data == data and content.content_type == HTML
    assert meta_obj is not None and meta_obj.content_type == "application/json"
    assert json.loads(meta_obj.data.decode("utf-8")) == _meta(data).to_json()
    assert fake.keys() == [PREFIX + "r1/e1/u1/.index.html.meta.json", PREFIX + KEY]
    assert store.read(KEY) == data and store.meta(KEY) == _meta(data)


def test_bucket_top_when_prefix_is_empty():
    store, fake = fake_s3_store(prefix="")
    store.write("r1/x.png", b"png", _meta(b"png", "x.png", "image/png"))     # 마디 둘인 키도 같은 규칙
    assert fake.keys() == ["r1/.x.png.meta.json", "r1/x.png"]
    assert store.prefix == ""


def test_write_order_meta_check_then_content_then_meta():
    store, fake = fake_s3_store()
    data = b"<p/>"
    store.write(KEY, data, _meta(data))
    meta_name = PREFIX + "r1/e1/u1/.index.html.meta.json"
    assert fake.calls == [("get_object", meta_name), ("put_object", PREFIX + KEY), ("put_object", meta_name)]


def test_same_content_again_is_success_other_content_conflicts():
    store, fake = fake_s3_store()
    data = b"<p/>"
    store.write(KEY, data, _meta(data))
    fake.calls.clear()
    store.write(KEY, data, _meta(data))                                     # 재시도 안전 — 메타만 읽고 끝
    assert fake.methods() == ["get_object"]
    with pytest.raises(FileConflict) as e:
        store.write(KEY, b"other", _meta(b"other"))
    _no_values_light(e.value)
    assert fake.methods() == ["get_object", "get_object"]                   # 다른 내용은 쓰지 않는다
    assert store.read(KEY) == data


def _no_values_light(e: BaseException) -> None:
    text = f"{e} {e!r}"
    assert BUCKET not in text and "r1/e1" not in text and "index.html" not in text


def test_retry_after_meta_write_failure_writes_again():
    store, fake = fake_s3_store()
    fake.inject("put_object", "slow_down", match=".meta.json")             # 내용은 썼지만 메타 쓰기가 실패
    with pytest.raises(S3TemporaryError):
        store.write(KEY, b"x", _meta(b"x"))
    assert store.meta(KEY) is None                                          # 메타가 없으면 '없는 파일'
    with pytest.raises(FileMissing):
        store.read(KEY)
    store.write(KEY, b"x", _meta(b"x"))                                     # 같은 키로 다시 — 성공
    assert store.read(KEY) == b"x"


def test_missing_key_meta_and_content():
    store, fake = fake_s3_store()
    assert store.meta(KEY) is None
    with pytest.raises(FileMissing) as e:
        store.read(KEY)
    _no_values_light(e.value)
    store.write(KEY, b"x", _meta(b"x"))
    fake.remove_raw(PREFIX + KEY)                                           # 메타는 있고 내용 객체가 없음
    with pytest.raises(FileMissing):
        store.read(KEY)
    fake.put_raw(PREFIX + "r1/e1/u2/a.html", b"x")                          # 내용만 있고 메타가 없음
    assert store.meta("r1/e1/u2/a.html") is None
    with pytest.raises(FileMissing):
        store.read("r1/e1/u2/a.html")


@pytest.mark.parametrize("key", ["../escape/x.html", "r1/../../x.html", "/abs/x.html", "r1\\x.html", "x.html",
                                 "r1//x.html", "r1/e1/.meta", "r1/CON"])
def test_key_rule_checked_before_any_call(key):
    store, fake = fake_s3_store()
    for call in (lambda: store.write(key, b"x", _meta(b"x", "x.html")), lambda: store.read(key),
                 lambda: store.meta(key)):
        with pytest.raises(ValueError) as e:
            call()
        assert key not in str(e.value)
    assert fake.calls == []


def test_read_only_store():
    store, fake = fake_s3_store()
    store.write(KEY, b"x", _meta(b"x"))
    ro, _ = fake_s3_store(fake, read_only=True)
    fake.calls.clear()
    with pytest.raises(FileStoreReadOnly):
        ro.write("r1/e1/u2/a.html", b"x", _meta(b"x", "a.html"))
    with pytest.raises(FileStoreReadOnly):
        ro.delete_prefix("r1/")
    assert fake.calls == []                                                 # 쓰기 · 지우기는 S3를 부르지 않는다
    assert ro.read(KEY) == b"x" and ro.meta(KEY) == _meta(b"x")
    assert ro.read_only and not store.read_only


# ── 접두어째 지우기 ─────────────────────────────────────────

def test_delete_prefix_over_1000_objects_with_pages():
    fake = FakeS3Client(page_size=400)
    store, _ = fake_s3_store(fake)
    for i in range(2500):
        fake.put_raw(f"{PREFIX}r1/e1/u{i:04d}/f.html", b"x")
    for other in ("r10/e1/u1/f.html", "r2/e1/u1/f.html"):
        fake.put_raw(PREFIX + other, b"x")
    fake.put_raw("other/r1/e1/u1/f.html", b"x")                              # 접두어 밖은 건드리지 않는다
    store.delete_prefix("r1/")
    assert fake.keys() == ["app/artifacts/r10/e1/u1/f.html", "app/artifacts/r2/e1/u1/f.html", "other/r1/e1/u1/f.html"]
    lists = [arg for m, arg in fake.calls if m == "list_objects_v2"]
    deletes = [arg for m, arg in fake.calls if m == "delete_objects"]
    assert lists == [PREFIX + "r1/"] * 7                                    # 400개씩 쪽 나눔 (2,500 → 7쪽)
    assert deletes == [1000, 1000, 500]                                     # 1,000개씩 지운다
    fake.calls.clear()
    store.delete_prefix("r1/")                                              # 이미 없으면 성공 — 지우기를 부르지 않는다
    assert fake.methods() == ["list_objects_v2"]
    store.delete_prefix("r9")                                               # 끝 '/'가 없어도 같은 규칙


def test_delete_prefix_written_files_and_bucket_top():
    store, fake = fake_s3_store(prefix="")
    for key in ("r1/e1/u1/a.html", "r1/e2/u2/b.png", "r10/e1/u1/c.html"):
        store.write(key, b"x", _meta(b"x", key.rsplit("/", 1)[1]))
    store.delete_prefix("r1/e1/")
    assert store.meta("r1/e1/u1/a.html") is None and store.meta("r1/e2/u2/b.png") is not None
    store.delete_prefix("r1/")
    assert fake.keys() == ["r10/e1/u1/.c.html.meta.json", "r10/e1/u1/c.html"]


@pytest.mark.parametrize(("codes", "expected", "code"), [
    (("AccessDenied",), ProviderError, "access_denied"),
    (("SlowDown",), S3TemporaryError, "slow_down"),
    (("InternalError",), S3TemporaryError, "internal_error"),
    (("AccessDenied", "SlowDown"), S3TemporaryError, "slow_down"),          # 하나라도 일시 코드면 일시
    (("AccessDenied", "InternalError"), ProviderError, "access_denied"),
])
def test_delete_prefix_partial_failure_is_error(codes, expected, code):
    store, fake = fake_s3_store()
    for i in range(5):
        fake.put_raw(f"{PREFIX}r1/e1/u{i}/f.html", b"x")
    fake.fail_in_delete(*codes)
    with pytest.raises(expected) as e:
        store.delete_prefix("r1/")
    assert e.value.code == code
    if expected is ProviderError:
        assert e.value.status == 403
    _no_values(e.value)
    assert len(fake.keys()) == len(codes)                                   # 지워지지 않은 객체가 남는다 — 대기열이 다시 시도
    store.delete_prefix("r1/")
    assert fake.keys() == []


@pytest.mark.parametrize("prefix", ["../", "", "/", "r1//", "a b/", "r1/../", ".hidden/", "r1/./", "CON/", "a\\b/"])
def test_delete_prefix_rejects_like_local_store(prefix):
    store, fake = fake_s3_store()
    with pytest.raises(ValueError):
        MemoryFileStore().delete_prefix(prefix)                             # 메모리 · 로컬 폴더와 같은 규칙
    with pytest.raises(ValueError) as e:
        store.delete_prefix(prefix)
    assert fake.calls == []
    if prefix.strip("/"):
        assert prefix.strip("/") not in str(e.value)


def test_delete_prefix_listing_errors():
    store, fake = fake_s3_store()
    fake.inject("list_objects_v2", "access_denied")
    with pytest.raises(ProviderError) as e:
        store.delete_prefix("r1/")
    assert (e.value.status, e.value.code) == (403, "access_denied")
    _no_values(e.value)
    missing, _ = fake_s3_store(FakeS3Client(buckets=("another-bucket",)))
    with pytest.raises(ProviderError) as e:
        missing.delete_prefix("r1/")
    assert (e.value.status, e.value.code) == (404, "no_such_bucket")       # 버킷 없음은 404지만 영구
    _no_values(e.value)


# ── 오류 바꾸기 ─────────────────────────────────────────────

ERROR_TABLE = [
    # (가짜 오류 이름, 올라오는 예외, 상태, 오류 코드, 자격 증명 표시)
    ("access_denied", ProviderError, 403, "access_denied", False),
    ("no_such_bucket", ProviderError, 404, "no_such_bucket", False),
    ("invalid_request", ProviderError, 400, "invalid_request", False),
    ("internal_error", S3TemporaryError, 500, "internal_error", False),
    ("service_unavailable", S3TemporaryError, 503, "service_unavailable", False),
    ("slow_down", S3TemporaryError, 503, "slow_down", False),
    ("request_timeout", S3TemporaryError, 400, "request_timeout", False),
    ("throttling", S3TemporaryError, 400, "throttling", False),
    ("status_408", S3TemporaryError, 408, "unknown408", False),
    ("status_429", S3TemporaryError, 429, "too_many_requests", False),
    ("connection", S3TemporaryError, None, None, False),
    ("connection_closed", S3TemporaryError, None, None, False),
    ("connect_timeout", S3TimeoutError, None, None, False),
    ("read_timeout", S3TimeoutError, None, None, False),
    ("no_credentials", S3TemporaryError, None, None, True),
    ("partial_credentials", S3TemporaryError, None, None, True),
    ("credential_retrieval", S3TemporaryError, None, None, True),
    ("metadata_retrieval", S3TemporaryError, None, None, True),
    ("param_validation", S3StoreError, None, None, False),
]


def _run_op(op: str, store: S3FileStore, fake: FakeS3Client, kind: str) -> None:
    if op == "read":
        store.write(KEY, b"x", _meta(b"x"))
        fake.inject("get_object", kind)
        store.read(KEY)
    elif op == "meta":
        fake.inject("get_object", kind)
        store.meta(KEY)
    elif op == "write":
        fake.inject("put_object", kind)
        store.write(KEY, b"x", _meta(b"x"))
    elif op == "delete":
        fake.put_raw(PREFIX + KEY, b"x")
        fake.inject("delete_objects", kind)
        store.delete_prefix("r1/")
    else:
        raise AssertionError(op)


@pytest.mark.parametrize("op", ["read", "meta", "write", "delete"])
@pytest.mark.parametrize(("kind", "expected", "status", "code", "credentials"), ERROR_TABLE)
def test_error_translation_table(op, kind, expected, status, code, credentials):
    store, fake = fake_s3_store()
    with pytest.raises(expected) as e:
        _run_op(op, store, fake, kind)
    err = e.value
    _no_values(err)
    assert not isinstance(err, bx.BotoCoreError | bx.ClientError)          # AWS 라이브러리 예외는 밖으로 나가지 않는다
    if expected is ProviderError:
        assert (err.status, err.code) == (status, code)
        assert str(err) == f"S3 오류(status={status})"
    elif expected is S3TemporaryError:
        assert isinstance(err, ConnectionError) and (err.status, err.code, err.credentials) == (status, code,
                                                                                               credentials)
        assert str(err).startswith("S3 일시 오류(")
    elif expected is S3TimeoutError:
        assert isinstance(err, TimeoutError) and str(err).startswith("S3 일시 오류(")
    else:
        assert err.kind == S3StoreError.UNEXPECTED and not isinstance(err, OSError)


@pytest.mark.parametrize(("kind", "expected"), [
    ("streaming", S3TemporaryError), ("incomplete", S3TemporaryError), ("read_timeout", S3TimeoutError),
    ("connection_closed", S3TemporaryError),
])
def test_body_read_errors_follow_table(kind, expected):
    store, fake = fake_s3_store()
    store.write(KEY, b"x", _meta(b"x"))
    fake.inject("read_body", kind, match="u1/index.html")                  # 메타는 읽고 내용 본문을 읽다 끊김
    with pytest.raises(expected) as e:
        store.read(KEY)
    _no_values(e.value)
    assert store.read(KEY) == b"x"


def test_404_without_no_such_key_code_is_not_missing():
    store, fake = fake_s3_store()
    fake.inject("get_object", client_error("NotFound", 404, key=PREFIX + KEY))
    with pytest.raises(ProviderError) as e:                                 # 상태 404만으로 '없음'이라 하지 않는다
        store.meta(KEY)
    assert (e.value.status, e.value.code) == (404, "not_found")
    fake.inject("get_object", client_error("NoSuchKey", 404, key=PREFIX + KEY))
    assert store.meta(KEY) is None


def test_client_error_without_status_is_temporary():
    store, fake = fake_s3_store()
    fake.inject("get_object", client_error("WeirdCode", None))
    with pytest.raises(S3TemporaryError) as e:
        store.meta(KEY)
    assert e.value.status is None and e.value.code == "weird_code"


def test_missing_bucket_on_read_and_write_is_permanent():
    store, _ = fake_s3_store(FakeS3Client(buckets=("another-bucket",)))
    for call in (lambda: store.meta(KEY), lambda: store.read(KEY), lambda: store.write(KEY, b"x", _meta(b"x"))):
        with pytest.raises(ProviderError) as e:
            call()
        assert (e.value.status, e.value.code) == (404, "no_such_bucket")
        _no_values(e.value)


def test_no_list_permission_makes_missing_object_forbidden():
    store, _ = fake_s3_store(FakeS3Client(list_permission=False))
    with pytest.raises(ProviderError) as e:                                 # 목록 권한이 없으면 없는 객체도 403
        store.meta(KEY)
    assert (e.value.status, e.value.code) == (403, "access_denied")


@pytest.mark.parametrize(("raw", "code"), [
    ("AccessDenied", "access_denied"), ("NoSuchBucket", "no_such_bucket"), ("SlowDown", "slow_down"),
    ("RequestTimeout", "request_timeout"), ("InternalError", "internal_error"),
    ("InvalidAccessKeyId", "invalid_access_key_id"), ("XAmzContentSHA256Mismatch", "x_amz_content_sha256_mismatch"),
    ("NoSuchKey", "no_such_key"), ("Throttling", "throttling"), ("404", "404"), ("already_snake", "already_snake"),
    ("Bad.Code", None), ("Bad-Code", None), ("", None), (None, None), (403, None), ("A" * 70, None), ("코드", None),
])
def test_error_code_lower_snake(raw, code):
    assert s3_error_code(raw) == code
    if code is not None:
        assert clean_error_code(code) == code                               # 시도 설명 · 운영 로그 모양 검사를 통과


def test_temporary_codes_match_aws_standard_retry():
    """일시로 보는 S3 오류 코드 목록이 설치된 botocore 표준 재시도(일시 · 속도 제한) 목록과 같다 (잠정 — 판이 바뀌면 다시 본다)."""
    from botocore.retries import standard

    expected = (set(standard.TransientRetryableChecker._TRANSIENT_ERROR_CODES)
                | set(standard.ThrottledRetryableChecker._THROTTLED_ERROR_CODES))
    assert set(TEMPORARY_ERROR_CODES) == expected
    assert set(s3_errors.THROTTLING_ERROR_CODES) == set(standard.ThrottledRetryableChecker._THROTTLED_ERROR_CODES)


def test_deletion_queue_error_kinds():
    assert error_kind_of(S3TemporaryError(s3_errors.KIND_CONNECTION)) == "일시"
    assert error_kind_of(S3TimeoutError(s3_errors.KIND_TIMEOUT)) == "일시"
    assert error_kind_of(ProviderError("S3 오류(status=403)", status=403, code="access_denied")) == "운영"
    assert error_kind_of(S3StoreError(S3StoreError.UNEXPECTED)) == "운영"


def s3_tools(store: S3FileStore, *, retry: int = 2) -> tuple[Tools, CallSink]:
    sink = CallSink()
    cfg = ToolsConfig(agent="구현", provider=None, model=None, temperature=None, timeout_sec=5,
                      retry_count=retry, retry_interval_sec=0)
    ctx = ToolsContext(run_id="r1", execution_id="e1", task_id="T-B1", providers={}, sink=sink,
                       now=utc_now, sleep=lambda s: None, files=store, run_progress=lambda: "실행")
    return Tools(cfg, ctx), sink


def test_tools_classification_of_s3_errors():
    store, fake = fake_s3_store()
    tools, sink = s3_tools(store)
    fake.inject("put_object", "slow_down")                                  # 일시 — tools가 다시 보낸다
    ref = tools.files.put("index.html", b"<p/>", HTML)
    fake.inject("get_object", "read_timeout")
    assert tools.files.get(ref) == b"<p/>"
    put_log, get_log = sink.drain()
    assert [(t.outcome, t.error_kind) for t in put_log.tries] == [("호출실패", "일시"), ("성공", None)]
    assert [t.outcome for t in get_log.tries] == ["응답지연", "성공"]

    fake.inject("put_object", "access_denied")                              # 영구 — 다시 보내지 않는다
    with pytest.raises(ToolCallExhausted) as e:
        tools.files.put("index.html", b"<p/>", HTML)
    assert (e.value.error_kind, e.value.tries, e.value.code) == ("운영", 1, "access_denied")
    [log] = sink.drain()
    assert log.tries[0].detail == "status=403 code=access_denied"
    text = json.dumps(log.dump(), ensure_ascii=False)
    assert BUCKET not in text and "arn:" not in text and PREFIX.rstrip("/") not in text

    missing = ref.model_copy(update={"key": "r1/e1/zz/index.html"})
    with pytest.raises(ToolCallExhausted) as e:                             # 없는 키 — 입력, 다시 보내지 않는다
        tools.files.get(missing)
    assert (e.value.error_kind, e.value.tries) == ("입력", 1)


# ── 클라이언트 ─────────────────────────────────────────────

def test_store_creation_does_not_make_client_first_use_does_once(monkeypatch):
    fake = FakeS3Client()
    regions = patch_client_factory(monkeypatch, fake)
    store = S3FileStore(BUCKET, PREFIX, REGION)
    assert regions == []                                                    # 만들 때는 S3 · 메타데이터에 닿지 않는다
    ro = S3FileStore(BUCKET, PREFIX, REGION, read_only=True)
    assert regions == [] and ro.read_only
    assert store.meta(KEY) is None
    store.write(KEY, b"x", _meta(b"x"))
    assert store.read(KEY) == b"x"
    assert regions == [REGION]


def test_conftest_blocks_real_client():
    assert s3_client.make_s3_client is not REAL_MAKE_S3_CLIENT
    store = S3FileStore(BUCKET, PREFIX, REGION)
    with pytest.raises(S3StoreError) as e:                                  # 막힌 공장 — 클라이언트를 만들지 못함
        store.meta(KEY)
    assert e.value.kind == S3StoreError.CLIENT
    _no_values(e.value)


def test_credential_failure_drops_client_and_remakes(monkeypatch):
    made: list[FakeS3Client] = []

    def make(region: str) -> FakeS3Client:
        made.append(FakeS3Client())
        return made[-1]
    regions = patch_client_factory(monkeypatch, make)
    store = S3FileStore(BUCKET, PREFIX, REGION)
    assert store.meta(KEY) is None
    made[0].inject("get_object", "no_credentials")
    with pytest.raises(S3TemporaryError) as e:
        store.meta(KEY)
    assert e.value.credentials and e.value.kind == s3_errors.KIND_CREDENTIALS
    _no_values(e.value)
    assert store.meta(KEY) is None                                          # 버린 클라이언트 대신 새로 만든다
    assert regions == [REGION, REGION] and len(made) == 2
    made[1].inject("get_object", "access_denied")                           # 자격 증명이 아닌 오류는 버리지 않는다
    with pytest.raises(ProviderError):
        store.meta(KEY)
    assert store.meta(KEY) is None and len(made) == 2


def test_credential_failure_while_making_client_tries_again(monkeypatch):
    fake = FakeS3Client()
    attempts: list[int] = []

    def make(region: str) -> FakeS3Client:
        attempts.append(1)
        if len(attempts) == 1:
            raise make_error("credential_retrieval")
        return fake
    patch_client_factory(monkeypatch, make)
    store = S3FileStore(BUCKET, PREFIX, REGION)
    with pytest.raises(S3TemporaryError) as e:
        store.meta(KEY)
    assert e.value.credentials
    _no_values(e.value)
    assert store.meta(KEY) is None and len(attempts) == 2


def test_injected_client_is_never_dropped(monkeypatch):
    regions = patch_client_factory(monkeypatch, FakeS3Client())
    store, fake = fake_s3_store()
    fake.inject("get_object", "no_credentials")
    with pytest.raises(S3TemporaryError):
        store.meta(KEY)
    assert store.meta(KEY) is None
    assert regions == [] and fake.methods() == ["get_object", "get_object"]


@pytest.mark.parametrize(("error", "kind"), [
    (bx.ProfileNotFound(profile="secret-profile"), S3StoreError.CLIENT),
    (bx.InvalidRegionError(region_name="bad region"), S3StoreError.CLIENT),
    (RuntimeError("anything ap-northeast-2"), S3StoreError.CLIENT),
    (ImportError("No module named 'boto3'"), S3StoreError.LIBRARY),
])
def test_client_creation_failures_are_setup_errors(monkeypatch, error, kind):
    def make(region: str):
        raise error
    patch_client_factory(monkeypatch, make)
    store = S3FileStore(BUCKET, PREFIX, REGION)
    with pytest.raises(S3StoreError) as e:
        store.meta(KEY)
    assert e.value.kind == kind and not isinstance(e.value, OSError)
    _no_values(e.value, "secret-profile", "bad region", REGION)
    if kind == S3StoreError.LIBRARY:
        assert "다시 설치" in str(e.value)


def test_construction_checks_without_client(monkeypatch):
    for bucket in ("Bad_Bucket", "", "ab"):
        with pytest.raises(S3StoreError) as e:
            S3FileStore(bucket, PREFIX, REGION)
        assert e.value.kind == S3StoreError.BUCKET and (not bucket or bucket not in str(e.value))
    with pytest.raises(S3StoreError) as e:
        S3FileStore(BUCKET, "a//b", REGION)
    assert e.value.kind == S3StoreError.PREFIX
    for region in (None, ""):
        with pytest.raises(S3StoreError) as e:
            S3FileStore(BUCKET, PREFIX, region)
        assert e.value.kind == S3StoreError.REGION
    with pytest.raises(S3StoreError) as e:                                  # 리전 모양 — 클라이언트 없이 라이브러리 검사로
        S3FileStore(BUCKET, PREFIX, "bad region!")
    assert e.value.kind == S3StoreError.REGION and "bad region" not in str(e.value)
    _no_values(e.value)
    store = S3FileStore(BUCKET, "/app/artifacts", REGION)                   # 접두어는 정리해 둔다
    assert (store.bucket, store.prefix, store.region) == (BUCKET, PREFIX, REGION)


def test_construction_without_aws_library(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)                         # 설치되어 있지 않은 것처럼
    with pytest.raises(S3StoreError) as e:
        S3FileStore(BUCKET, PREFIX, REGION)
    assert e.value.kind == S3StoreError.LIBRARY and "다시 설치" in str(e.value)
    _no_values(e.value)
    store, fake = fake_s3_store()                                           # 시험용으로 주입하면 라이브러리를 부르지 않는다
    assert store.meta(KEY) is None


def test_from_address():
    fake = FakeS3Client()
    store = S3FileStore.from_address(f"s3://{BUCKET}/app/artifacts", REGION, client=fake, read_only=True)
    assert (store.bucket, store.prefix, store.read_only) == (BUCKET, PREFIX, True)
    with pytest.raises(S3StoreError) as e:
        S3FileStore.from_address("s3://Bad", REGION, client=fake)
    assert e.value.kind == S3StoreError.BUCKET
    with pytest.raises(S3StoreError) as e:
        S3FileStore.from_address(f"s3://{BUCKET}/a//b", REGION, client=fake)
    assert e.value.kind == S3StoreError.PREFIX
    with pytest.raises(ValueError):
        S3FileStore.from_address("/local/path", REGION, client=fake)


def test_client_config_values():
    cfg = s3_client.client_config()
    assert cfg.retries == {"total_max_attempts": 1, "mode": "standard"}     # 라이브러리 재시도 끔 (max_attempts가 아님)
    assert (cfg.connect_timeout, cfg.read_timeout) == (10, 60)
    assert (s3_client.TOTAL_MAX_ATTEMPTS, s3_client.RETRY_MODE) == (1, "standard")
    assert (s3_client.CONNECT_TIMEOUT_SEC, s3_client.READ_TIMEOUT_SEC) == (10, 60)
    assert cfg.max_pool_connections == 10                                   # 연결 수는 라이브러리 기본값 (잠정)


def test_make_client_passes_region_and_config_only(monkeypatch):
    """실제 클라이언트를 만들지 않고 넘기는 값만 본다 — 세션 클래스를 가짜로 바꾼다."""
    import boto3

    made: list[tuple] = []

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            made.append(("session", args, kwargs))

        def client(self, service, **kwargs):
            made.append(("client", service, kwargs))
            return "the-client"
    monkeypatch.setattr(boto3.session, "Session", FakeSession)
    assert REAL_MAKE_S3_CLIENT(REGION) == "the-client"
    [(_, args, kwargs), (_, service, ckw)] = made
    assert args == () and kwargs == {}                                      # 키 · 프로필을 넘기지 않는다 (기본 자격 증명 순서)
    assert service == "s3" and set(ckw) == {"region_name", "config"} and ckw["region_name"] == REGION
    assert ckw["config"].retries == {"total_max_attempts": 1, "mode": "standard"}
    assert (ckw["config"].connect_timeout, ckw["config"].read_timeout) == (10, 60)


# ── 시작 확인 ─────────────────────────────────────────────

def _check_message_clean(result: S3CheckResult) -> None:
    for secret in (BUCKET, PREFIX.rstrip("/"), "arn:", "amazonaws", ".probe", REGION):
        assert secret not in result.message, secret


def test_startup_check_success_leaves_nothing():
    store, fake = fake_s3_store()
    result = check_s3_store(store)
    assert result.ok and not result.permanent and result.message == ""
    result.raise_if_failed()
    assert fake.keys() == []
    assert fake.methods() == ["get_object", "put_object", "get_object", "delete_object"]
    names = {arg for _, arg in fake.calls}
    [name] = names
    assert name.startswith(PREFIX + PROBE_DIR) and len(name) > len(PREFIX + PROBE_DIR)


def test_startup_check_probe_name_is_outside_run_keys():
    assert PROBE_DIR.startswith(".") and PROBE_DIR.endswith("/")
    store, fake = fake_s3_store(prefix="")
    assert check_s3_store(store).ok
    [name] = {arg for _, arg in fake.calls}
    assert name.startswith(PROBE_DIR)                                       # 버킷 맨 위면 '.probe/<고유값>'


@pytest.mark.parametrize(("setup", "step", "status", "code", "wrote"), [
    (lambda f: setattr(f, "list_permission", False), s3_probe.STEP_ABSENT, 403, "access_denied", False),
    (lambda f: f.inject("get_object", "access_denied"), s3_probe.STEP_ABSENT, 403, "access_denied", False),
    (lambda f: f.inject("put_object", "access_denied"), s3_probe.STEP_WRITE, 403, "access_denied", True),
    (lambda f: f.inject("get_object", "access_denied", match=lambda k: any(m == "put_object" for m in f.methods())),
     s3_probe.STEP_READ, 403, "access_denied", True),
    (lambda f: f.inject("delete_object", "access_denied"), s3_probe.STEP_DELETE, 403, "access_denied", True),
    (lambda f: f.inject("put_object", "no_such_bucket"), s3_probe.STEP_WRITE, 404, "no_such_bucket", True),
])
def test_startup_check_permanent_failures(setup, step, status, code, wrote):
    store, fake = fake_s3_store()
    setup(fake)
    result = check_s3_store(store)
    assert not result.ok and result.permanent and result.kind is None
    assert (result.step, result.status, result.code) == (step, status, code)
    assert result.message.startswith("설정 오류: S3 산출물 위치를 쓸 수 없음")
    if step == s3_probe.STEP_ABSENT:
        assert "목록 권한(s3:ListBucket)" in result.message                  # 목록 권한이 없으면 없는 객체도 403
    assert "권한 · 버킷 · 리전 · 접두어를 확인" in result.message
    assert result.message.endswith(f"(status={status} code={code})")
    _check_message_clean(result)
    assert fake.keys() == []                                                # 남은 시험 객체가 없다
    assert ("put_object" in fake.methods()) == wrote
    if wrote:
        assert fake.methods()[-1] == "delete_object"                        # 중간 실패면 지우기를 한 번 해 본다
    with pytest.raises(S3StartupCheckFailed) as e:
        result.raise_if_failed()
    assert e.value.permanent and str(e.value) == result.message and isinstance(e.value, RuntimeError)


def test_startup_check_missing_read_must_say_missing():
    store, fake = fake_s3_store()
    original = fake.get_object

    def get_object(**kw):                                                   # 없는 시험 객체가 '있다'고 나옴
        fake.put_raw(kw["Key"], b"stale")
        return original(**kw)
    fake.get_object = get_object                                            # type: ignore[method-assign]
    result = check_s3_store(store)
    assert result.permanent and result.step == s3_probe.STEP_ABSENT and result.status is None
    assert "없는 시험 객체가 있다고 나옴" in result.message
    _check_message_clean(result)
    assert "put_object" not in fake.methods()                               # 쓰지 않는다


def test_startup_check_content_differs():
    store, fake = fake_s3_store()
    fake.tamper_reads(b"other", match=".probe/")                            # 없음 확인(NoSuchKey)에는 닿지 않고 쓴 뒤 읽기에만
    result = check_s3_store(store)
    assert result.permanent and result.step == s3_probe.STEP_READ and result.status is None
    assert "읽은 내용이 다름" in result.message
    _check_message_clean(result)
    assert fake.keys() == []


@pytest.mark.parametrize(("setup", "kind"), [
    (lambda f: f.inject("get_object", "connection"), s3_errors.KIND_CONNECTION),
    (lambda f: f.inject("get_object", "no_credentials"), s3_errors.KIND_CREDENTIALS),
    (lambda f: f.inject("get_object", "metadata_retrieval"), s3_errors.KIND_CREDENTIALS),
    (lambda f: f.inject("put_object", "connect_timeout"), s3_errors.KIND_TIMEOUT),
    (lambda f: f.inject("put_object", "slow_down"), s3_errors.KIND_THROTTLE),
    (lambda f: f.inject("delete_object", "internal_error"), s3_errors.KIND_SERVER),
])
def test_startup_check_temporary_failures(setup, kind):
    store, fake = fake_s3_store()
    setup(fake)
    result = check_s3_store(store)
    assert not result.ok and not result.permanent and result.kind == kind
    assert result.message.startswith(f"S3 시작 확인 실패(일시) — {kind}")
    _check_message_clean(result)
    assert fake.keys() == []
    with pytest.raises(S3StartupCheckFailed) as e:
        result.raise_if_failed()
    assert not e.value.permanent


@pytest.mark.parametrize(("error", "kind", "words"), [
    (bx.ProfileNotFound(profile="secret-profile"), S3StoreError.CLIENT, "클라이언트를 만들지 못함"),
    (ImportError("No module named 'boto3'"), S3StoreError.LIBRARY, "패키지를 다시 설치"),
])
def test_startup_check_setup_failures_are_permanent(monkeypatch, error, kind, words):
    def make(region: str):
        raise error
    patch_client_factory(monkeypatch, make)
    store = S3FileStore(BUCKET, PREFIX, REGION)
    result = check_s3_store(store)
    assert result.permanent and result.kind == kind and result.step == s3_probe.STEP_CLIENT
    assert result.message.startswith("설정 오류: ") and words in result.message
    _check_message_clean(result)
    assert "secret-profile" not in result.message


def test_startup_check_credentials_at_client_creation_is_temporary(monkeypatch):
    def make(region: str):
        raise make_error("no_credentials")
    patch_client_factory(monkeypatch, make)
    result = check_s3_store(S3FileStore(BUCKET, PREFIX, REGION))
    assert not result.permanent and result.kind == s3_errors.KIND_CREDENTIALS


def test_startup_check_refuses_read_only_store():
    store, fake = fake_s3_store(read_only=True)
    with pytest.raises(ValueError):
        check_s3_store(store)
    assert fake.calls == []


def test_startup_check_cleanup_failure_is_ignored():
    store, fake = fake_s3_store()
    fake.inject("put_object", "internal_error")
    fake.inject("delete_object", "access_denied")                           # 정리 지우기도 실패 — 무시하고 처음 분류로 끝낸다
    result = check_s3_store(store)
    assert not result.permanent and result.kind == s3_errors.KIND_SERVER and result.step == s3_probe.STEP_WRITE


# ── 여러 스레드 ─────────────────────────────────────────────

def test_threads_share_one_store_and_client(monkeypatch):
    fake = FakeS3Client()
    regions = patch_client_factory(monkeypatch, fake)
    store = S3FileStore(BUCKET, PREFIX, REGION)

    def work(i: int) -> bool:
        for j in range(15):
            key, data = f"r{i}/e1/u{j}/f.html", f"{i}-{j}".encode()
            store.write(key, data, _meta(data, "f.html"))
            store.write(key, data, _meta(data, "f.html"))
            assert store.read(key) == data and store.meta(key) == _meta(data, "f.html")
        store.delete_prefix(f"r{i}/")
        return store.meta(f"r{i}/e1/u0/f.html") is None
    with ThreadPoolExecutor(8) as pool:
        assert all(pool.map(work, range(8)))
    assert regions == [REGION] and fake.keys() == []
