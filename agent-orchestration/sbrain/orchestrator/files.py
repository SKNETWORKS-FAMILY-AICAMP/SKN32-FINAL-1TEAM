"""파일 저장소 (확장) — 산출물 파일(실행 HTML · 원페이지 SVG · 그림 · 안내 문서 · 계획서 파일)을 두는 곳.

- 저장소 창구(FileStore)는 쓰기 · 읽기 · 메타데이터 보기 · 접두어째 지우기 넷이다. 구현은 메모리(테스트 · 스텁 조립)와
  로컬 폴더 둘이다. 운영은 S3 예정이고 같은 창구에 나중에 끼운다.
- 키는 models.files의 키 규칙을 따른다('<runId>/<executionId>/<고유값>/<name>'). 저장소도 키 규칙을 다시 검사한다 —
  로컬 폴더 밖으로 나가는 키를 막는다.
- 쓰기는 불변이다: 같은 키에 같은 내용(메타데이터가 같음)이면 성공(재시도 안전), 다른 내용이면 FileConflict.
- 없는 키 읽기는 FileMissing(LookupError — OSError가 아니다: tools가 일시 오류로 재시도하지 않게).
  디스크 오류(OSError)는 그대로 올린다 — tools가 일시 오류로 재시도한다.
- 접두어째 지우기는 여러 번 해도 안전하다(이미 없으면 성공). 파일 삭제는 워커만 한다.
- 오류 메시지에 키 · 이름 · 경로 · 내용을 넣지 않는다.
- Task 함수는 이 저장소에 직접 닿지 않는다 — tools.files(넣기 · 읽기)로만 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from ..models.files import file_key_problem, file_name_problem


@dataclass(frozen=True)
class FileMeta:
    """저장소가 파일과 함께 남기는 메타데이터 — 넣을 때 정한 이름 · 형식과 계산한 크기 · sha256."""
    name: str
    media_type: str
    size: int
    sha256: str

    def to_json(self) -> dict[str, object]:
        return {"name": self.name, "mediaType": self.media_type, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_json(cls, d: dict[str, object]) -> "FileMeta":
        return cls(name=str(d["name"]), media_type=str(d["mediaType"]), size=int(d["size"]),  # type: ignore[arg-type]
                   sha256=str(d["sha256"]))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FileMissing(LookupError):
    """저장소에 없는 키 (입력 오류 — 재시도하지 않는다). 메시지에 키를 넣지 않는다."""


class FileConflict(Exception):
    """같은 키에 다른 내용을 쓰려 함 (키는 불변). 메시지에 키를 넣지 않는다."""


class FileStoreReadOnly(RuntimeError):
    """읽기 전용으로 연 저장소에 쓰기 · 지우기를 함 (웹 조립 — 웹은 파일을 쓰지도 지우지도 않는다).

    OSError가 아니다 — 일시 오류로 재시도되지 않게. 메시지에 키 · 경로를 넣지 않는다."""


class FileStore(Protocol):
    """파일 저장소 창구. 여러 스레드 · 프로세스에서 함께 써도 안전해야 한다."""

    def write(self, key: str, data: bytes, meta: FileMeta) -> None:
        """키에 내용과 메타데이터를 쓴다. 같은 키에 같은 메타데이터면 성공, 다르면 FileConflict."""
        ...

    def read(self, key: str) -> bytes:
        """키의 내용. 없으면 FileMissing."""
        ...

    def meta(self, key: str) -> FileMeta | None:
        """키의 메타데이터. 없으면 None."""
        ...

    def delete_prefix(self, prefix: str) -> None:
        """접두어('<runId>/' 등) 아래를 통째로 지운다. 이미 없으면 성공."""
        ...


def _check_key(key: str) -> None:
    problem = file_key_problem(key)
    if problem is not None:
        raise ValueError(f"키 규칙 위반 — {problem}")


def _prefix_parts(prefix: str) -> list[str]:
    """접두어('<runId>/' 또는 '<runId>/<executionId>/')를 마디로 나눈다. 마디마다 이름 규칙을 지켜야 한다."""
    if not isinstance(prefix, str):
        raise ValueError("접두어 규칙 위반 — 글자가 아님")
    parts = (prefix[:-1] if prefix.endswith("/") else prefix).split("/")
    for seg in parts:
        problem = file_name_problem(seg)
        if problem is not None:
            raise ValueError(f"접두어 규칙 위반 — {problem}")
    return parts


class MemoryFileStore:
    """메모리 파일 저장소 — 테스트 · 스텁 조립(build_stub_app)의 기본. 스레드 안전."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, tuple[bytes, FileMeta]] = {}

    def write(self, key: str, data: bytes, meta: FileMeta) -> None:
        _check_key(key)
        with self._lock:
            existing = self._files.get(key)
            if existing is not None:
                if existing[1] == meta:
                    return
                raise FileConflict("같은 키에 다른 내용")
            self._files[key] = (bytes(data), meta)

    def read(self, key: str) -> bytes:
        _check_key(key)
        with self._lock:
            found = self._files.get(key)
        if found is None:
            raise FileMissing("없는 파일")
        return found[0]

    def meta(self, key: str) -> FileMeta | None:
        _check_key(key)
        with self._lock:
            found = self._files.get(key)
        return found[1] if found is not None else None

    def delete_prefix(self, prefix: str) -> None:
        head = "/".join(_prefix_parts(prefix)) + "/"
        with self._lock:
            for key in [k for k in self._files if k.startswith(head)]:
                del self._files[key]

    def keys(self) -> list[str]:
        """시험 · 확인용 — 저장된 키 목록."""
        with self._lock:
            return list(self._files)


@contextmanager
def _without_path() -> Iterator[None]:
    """디스크 오류(OSError)에서 경로를 뺀다 — 같은 종류로 다시 올려 tools가 일시 오류로 재시도하게 하되, 메시지에 키가 든
    경로가 실리지 않게 한다(예외 앞 200자는 실행 기록 · 사건에 남는다)."""
    try:
        yield
    except OSError as e:
        if e.filename is None and e.filename2 is None:
            raise
        raise type(e)(e.errno, e.strerror) from None


class LocalFolderFileStore:
    """로컬 폴더 파일 저장소 — 키 마디를 하위 폴더로 쓴다(root/<runId>/<executionId>/<고유값>/<name>).

    - 메타데이터는 옆 파일 '.<name>.meta.json'에 둔다. 파일 이름은 '.'으로 시작할 수 없어 옆 파일과 겹치지 않는다.
    - 쓰기는 원자적이다: 같은 폴더의 임시 파일('.'으로 시작)에 쓰고 이름을 바꾼다. 내용을 먼저, 메타데이터를 나중에 쓴다 —
      메타데이터 옆 파일이 있어야 '있는 파일'이다.
    - 키 규칙을 다시 검사하고, 풀린 경로가 폴더 안인지 확인한다.
    - root는 절대 경로만 받는다(상대 경로는 프로세스마다 다른 폴더로 풀린다). 웹과 모든 워커가 같은 폴더를 봐야 한다.
    - read_only(웹 조립)면 쓰기 · 접두어째 지우기가 FileStoreReadOnly다. 폴더를 만들지도 않는다(create와 함께 쓸 수 없다).
    """

    META_SUFFIX = ".meta.json"

    def __init__(self, root: str | Path, *, create: bool = False, read_only: bool = False) -> None:
        path = Path(root)
        if not path.is_absolute():
            raise ValueError("파일 저장소 폴더는 절대 경로여야 한다")
        if create and read_only:
            raise ValueError("읽기 전용 저장소는 폴더를 만들지 않는다")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        self.root = path.resolve()
        self.read_only = read_only

    def _check_writable(self) -> None:
        if self.read_only:
            raise FileStoreReadOnly("읽기 전용 파일 저장소 — 웹 프로세스는 파일을 쓰거나 지우지 않는다")

    # ── 경로 ─────────────────────────────────────────
    def _inside(self, path: Path) -> Path:
        if path == self.root or self.root not in path.parents:
            raise ValueError("키가 저장소 폴더 밖을 가리킴")
        return path

    def _path(self, key: str) -> Path:
        _check_key(key)
        return self._inside(self.root.joinpath(*key.split("/")))

    def _meta_path(self, path: Path) -> Path:
        return path.with_name(f".{path.name}{self.META_SUFFIX}")

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _read_meta(self, meta_path: Path) -> FileMeta | None:
        try:
            raw = meta_path.read_bytes()
        except FileNotFoundError:
            return None
        return FileMeta.from_json(json.loads(raw.decode("utf-8")))

    # ── 창구 ─────────────────────────────────────────
    def write(self, key: str, data: bytes, meta: FileMeta) -> None:
        self._check_writable()
        path = self._path(key)
        meta_path = self._meta_path(path)
        with _without_path():
            existing = self._read_meta(meta_path)
            if existing is not None:
                if existing == meta:
                    return
                raise FileConflict("같은 키에 다른 내용")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, bytes(data))
            self._atomic_write(meta_path, json.dumps(meta.to_json(), ensure_ascii=False).encode("utf-8"))

    def read(self, key: str) -> bytes:
        path = self._path(key)
        with _without_path():
            if self._read_meta(self._meta_path(path)) is None:
                raise FileMissing("없는 파일")
            try:
                return path.read_bytes()
            except FileNotFoundError:
                raise FileMissing("없는 파일") from None

    def meta(self, key: str) -> FileMeta | None:
        path = self._path(key)
        with _without_path():
            return self._read_meta(self._meta_path(path))

    def delete_prefix(self, prefix: str) -> None:
        self._check_writable()
        path = self._inside(self.root.joinpath(*_prefix_parts(prefix)))
        with _without_path():
            try:
                shutil.rmtree(path)
            except FileNotFoundError:
                pass
