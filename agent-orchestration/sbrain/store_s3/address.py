"""S3 주소 해석 — SBRAIN_ARTIFACT_ROOT의 S3 모양 's3://<버킷>[/<접두어>]'.

- 'S3 주소인가'는 스킴 's3://'(소문자만)으로 시작하는지로만 본다. 그 밖(절대 · 상대 경로, 'S3://')은 조립이 지금처럼 다룬다.
- 버킷 이름: S3 이름 규칙 모양만 본다(잠정) — 소문자 · 숫자 · '.' · '-', 3 ~ 63자, 소문자 · 숫자로 시작 · 끝, '..' 없음.
  실제로 있는지는 워커의 시작 확인(probe.check_s3_store)이 본다.
- 접두어: 버킷 뒤 경로 전체. 앞뒤 '/'를 정리하고 끝에 '/' 하나를 붙인다('app/artifacts' → 'app/artifacts/'). 없으면 버킷 맨
  위('')다. 마디는 영문 · 숫자 · '.' · '-' · '_'만, '.' · '..' · 빈 마디 금지, 정리한 접두어(끝 '/' 포함) 200자 이하(잠정).
- 문제 종류 글에는 값(주소 · 버킷 · 접두어)을 넣지 않는다 — 설정 오류 메시지 · 로그에 그대로 쓸 수 있게.
- 이 모듈은 AWS 라이브러리 없이 불러오고 돈다(조립이 로컬 폴더 값일 때도 부른다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["PREFIX_MAX_LEN", "S3_SCHEME", "S3Address", "bucket_name_problem", "is_s3_address", "normalize_prefix",
           "parse_s3_address", "prefix_problem", "s3_address_problem", "split_s3_address"]

S3_SCHEME = "s3://"
PREFIX_MAX_LEN = 200   # 정리한 접두어(끝 '/' 포함)의 최대 길이 (잠정)

# 버킷 이름 모양 (잠정 — S3 범용 버킷 이름 규칙의 모양만)
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_PREFIX_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


@dataclass(frozen=True)
class S3Address:
    """해석한 S3 주소 — 버킷과 정리한 접두어(빈 값 또는 '/'로 끝남). repr에 값을 싣지 않는다."""
    bucket: str
    prefix: str

    def __repr__(self) -> str:   # 직접 정의하면 dataclass가 만들지 않는다
        return "S3Address(bucket=…, prefix=…)"


def is_s3_address(value: object) -> bool:
    """값이 S3 주소 모양('s3://'로 시작 — 스킴은 소문자만)인가. 모양이 맞는지는 s3_address_problem이 본다."""
    return isinstance(value, str) and value.startswith(S3_SCHEME)


def bucket_name_problem(bucket: object) -> str | None:
    """버킷 이름 모양 규칙(잠정). 어기면 문제 종류(값 없음), 맞으면 None."""
    if not isinstance(bucket, str) or not bucket:
        return "버킷 이름 없음"
    if not 3 <= len(bucket) <= 63:
        return "버킷 이름 길이(3 ~ 63자)가 아님"
    if not _BUCKET.fullmatch(bucket):
        return "버킷 이름에 쓸 수 없는 글자 · 모양(소문자 · 숫자 · '.' · '-', 소문자 · 숫자로 시작 · 끝)"
    if ".." in bucket:
        return "버킷 이름에 '..'이 있음"
    return None


def _prefix_or_problem(path: object) -> tuple[str | None, str | None]:
    if not isinstance(path, str):
        return None, "접두어가 글자가 아님"
    body = path.strip("/")
    if not body:
        return "", None
    for seg in body.split("/"):
        if not seg:
            return None, "접두어에 빈 마디가 있음"
        if seg in (".", ".."):
            return None, "접두어에 '.' · '..' 마디가 있음"
        if not _PREFIX_SEGMENT.fullmatch(seg):
            return None, "접두어에 쓸 수 없는 글자가 있음(영문 · 숫자 · '.' · '-' · '_'만)"
    prefix = body + "/"
    if len(prefix) > PREFIX_MAX_LEN:
        return None, f"접두어 길이 초과({len(prefix)}자 > {PREFIX_MAX_LEN}자)"
    return prefix, None


def prefix_problem(path: object) -> str | None:
    """접두어 규칙. 어기면 문제 종류(값 없음), 맞으면 None."""
    return _prefix_or_problem(path)[1]


def normalize_prefix(path: str) -> str:
    """접두어를 정리한다 — 앞뒤 '/'를 떼고 끝에 '/' 하나(없으면 ''). 규칙을 어기면 ValueError(문제 종류)."""
    prefix, problem = _prefix_or_problem(path)
    if problem is not None or prefix is None:
        raise ValueError(problem or "접두어 규칙 위반")
    return prefix


def split_s3_address(value: str) -> tuple[str, str]:
    """'s3://<버킷>[/<경로>]'를 검사 없이 (버킷, 경로)로 나눈다. S3 주소 모양이 아니면 ValueError."""
    if not is_s3_address(value):
        raise ValueError("S3 주소가 아님('s3://'로 시작하지 않음)")
    bucket, _, path = value[len(S3_SCHEME):].partition("/")
    return bucket, path


def s3_address_problem(value: object) -> str | None:
    """S3 주소의 문제 종류(값 없음). 맞는 S3 주소면 None. 'S3 주소인가'는 is_s3_address로 먼저 가른다."""
    if not is_s3_address(value):
        return "S3 주소가 아님('s3://'로 시작하지 않음)"
    bucket, path = split_s3_address(value)   # type: ignore[arg-type]
    return bucket_name_problem(bucket) or prefix_problem(path)


def parse_s3_address(value: str) -> S3Address:
    """S3 주소를 버킷 · 정리한 접두어로 나눈다. 모양이 틀리면 ValueError(문제 종류 — 값 없음)."""
    problem = s3_address_problem(value)
    if problem is not None:
        raise ValueError(problem)
    bucket, path = split_s3_address(value)
    return S3Address(bucket=bucket, prefix=normalize_prefix(path))
