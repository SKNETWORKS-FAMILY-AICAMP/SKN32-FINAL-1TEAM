"""파일 참조 FileRef (확장 타입) — 산출물 파일을 DB 글자 칸에 담지 않고 파일 저장소에 두며, 계약 칸에는 참조만 싣는다.

- 기준 문서 타입에 담을 곳이 없는 참조 타입이라 새 타입으로 둔다(결정 0023 — docs/standards.md 7절 예외).
- FileRef는 Orchestrator가 파일을 넣을 때(tools.files.put) 만들어 돌려준다. Agent는 받은 값을 그대로 출력에 싣는다.
  엔진이 저장 전에 출력 안의 FileRef를 저장소와 대조한다(실행 건 · 있음 · 형식 · 크기 · sha256).
- 허용 형식 8종 · 파일 하나 30MB는 사용자가 정한 값이다(잠정이 아님).
- 규칙을 어긴 사유 문구에는 이름 · 키 · 내용을 넣지 않는다(어긴 규칙 종류만).
"""
from __future__ import annotations

import re

from pydantic import ConfigDict, field_validator, model_validator

from .base import SBModel

__all__ = ["ALLOWED_MEDIA_TYPES", "MAX_FILE_BYTES", "MAX_NAME_LEN", "FileRef", "file_key_problem",
           "file_name_problem", "media_type_problem", "size_problem"]

# 허용 형식 (spec 4.2) — 바꾸려면 이 목록에 더한다
ALLOWED_MEDIA_TYPES: frozenset[str] = frozenset({
    "text/html",                                                                  # HTML
    "image/svg+xml",                                                              # SVG
    "image/png",                                                                  # PNG
    "text/markdown",                                                              # 마크다운(실행 안내 문서)
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",    # 워드(계획서 파일)
    "application/x-hwp",                                                          # 한글 hwp
    "application/hwp+zip",                                                        # 한글 hwpx
    "application/json",                                                           # JSON (내용 검사는 하지 않는다)
})
MAX_FILE_BYTES = 30 * 1024 * 1024   # 파일 하나 30MB (31,457,280바이트)
MAX_NAME_LEN = 100                  # 파일 이름 · 키 마디 하나의 길이 상한

_ALLOWED = re.compile(r"[A-Za-z0-9._-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# Windows 예약 이름 — 확장자를 뺀 이름(첫 '.' 앞)이 이것이면 Windows에서 그 이름의 파일을 만들 수 없다 (대소문자 무시)
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})


def _segment_problem(seg: str) -> str | None:
    """이름 · 키 마디 하나의 규칙. 어기면 규칙 종류를, 맞으면 None."""
    if not seg:
        return "빈 이름"
    if len(seg) > MAX_NAME_LEN:
        return f"이름 길이 초과({len(seg)}자)"
    if not _ALLOWED.fullmatch(seg):
        return "허용하지 않는 글자"
    if seg.startswith(".") or seg.endswith("."):
        return "점으로 시작하거나 끝남"
    if seg.split(".", 1)[0].upper() in _RESERVED:
        return "Windows 예약 이름"
    return None


def file_name_problem(name: str) -> str | None:
    """파일 이름 규칙(spec 4.1) — 경로가 아닌 이름 하나, 1 ~ 100자, 영문 · 숫자 · '.' · '-' · '_'만, '.'으로 시작 · 끝나지 않음,
    확장자를 뺀 이름이 Windows 예약 이름이 아님. 어기면 규칙 종류(이름 없음), 맞으면 None."""
    if not isinstance(name, str):
        return "이름이 글자가 아님"
    return _segment_problem(name)


def file_key_problem(key: str) -> str | None:
    """키 규칙(spec 4.1) — '/'로 나눈 마디가 둘 이상이고(첫 마디 = 실행 건 ID, 마지막 마디 = 파일 이름), 마디마다 이름 규칙을
    지킨다. 절대 경로 · '..' · '.' · 빈 마디 · 역슬래시 · 드라이브 표시는 이 규칙에 걸린다. 어기면 규칙 종류(키 없음), 맞으면 None."""
    if not isinstance(key, str) or not key:
        return "빈 키"
    parts = key.split("/")
    if len(parts) < 2:
        return "키 마디 부족"
    for seg in parts:
        problem = _segment_problem(seg)
        if problem is not None:
            return f"키 마디 — {problem}"
    return None


def media_type_problem(media_type: str) -> str | None:
    return None if media_type in ALLOWED_MEDIA_TYPES else "허용하지 않는 형식"


def size_problem(size: int) -> str | None:
    if size < 0:
        return "크기가 음수"
    if size > MAX_FILE_BYTES:
        return f"크기 초과({size}바이트 > {MAX_FILE_BYTES}바이트)"
    return None


class FileRef(SBModel):
    """확장 타입 — 파일 참조 (결정 0023). JSON 이름: key · name · mediaType · size · sha256.

    key       저장소 안 위치. Orchestrator가 짓는다: '<runId>/<executionId>/<고유값>/<name>'
    name      파일 이름 (예: index.html · onepage.svg · README.md)
    mediaType 허용 형식 8종 중 하나
    size      바이트 수, 0 이상 30MB 이하
    sha256    내용의 SHA-256, 소문자 16진수 64자
    """
    model_config = ConfigDict(hide_input_in_errors=True)   # 검사 오류에 키 · 이름 값을 싣지 않는다

    key: str
    name: str
    media_type: str
    size: int
    sha256: str

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        problem = file_key_problem(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        problem = file_name_problem(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("media_type")
    @classmethod
    def _media(cls, v: str) -> str:
        problem = media_type_problem(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("size")
    @classmethod
    def _size(cls, v: int) -> int:
        problem = size_problem(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("sha256")
    @classmethod
    def _sha(cls, v: str) -> str:
        if not _SHA256.fullmatch(v):
            raise ValueError("sha256 형식 아님")
        return v

    @model_validator(mode="after")
    def _key_ends_with_name(self) -> "FileRef":
        if self.key.rsplit("/", 1)[-1] != self.name:
            raise ValueError("키의 마지막 마디가 이름과 다름")
        return self

    @property
    def run_id(self) -> str:
        """키의 첫 마디 — 이 파일을 넣은 실행 건 ID."""
        return self.key.split("/", 1)[0]
