"""담당자 자료 파일 — 불러올 때 한 번 읽어 둔 상수 (spec 4.1 · 2절 '자료 파일').

담당자 코드는 작성 규칙 · 검증 기준 · 공고 규정 · 시장 자료 JSON · MD를 호출할 때마다 디스크에서 읽었다. 우리 규칙은
Task 실행 중 디스크에 닿지 않는 것이라, 이 모듈이 처음 불러올 때 아래 폴더의 .json · .md를 모두 읽어 두고 담당자 코드는
`path.exists()` → `exists(path)`, `path.read_text(...)` → `read(path)`로만 바꿨다(경로 계산은 담당자 코드 그대로).

- 키는 partner_sw 폴더 기준 상대 경로다. 담당자 코드가 `Path(__file__).resolve()`로 만든 경로와 그렇지 않은 경로를
  모두 받는다(폴더 밖 경로는 없는 파일).
- 없는 파일(시장 자료 `keyword_history.json` 등)은 `exists`가 거짓, `read`가 FileNotFoundError(OSError)다 — 담당자 코드의
  '파일 없음 · 읽기 실패' 처리가 그대로 돈다.
- 글자는 utf-8-sig로 읽는다(BOM이 있으면 뗀다 — 담당자 코드는 대부분 utf-8-sig, 몇 곳은 utf-8로 읽었다).
- 산출물이 아니라 코드의 일부다. 내용을 기록 · 로그 · 예외 메시지에 넣지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

_HERE = Path(__file__).parent
# 담당자 코드가 만드는 두 가지 경로 모양(resolve 한 것 · 안 한 것)의 기준 폴더
_ROOTS: tuple[str, ...] = tuple(dict.fromkeys(
    os.path.normcase(os.path.abspath(p)) for p in (_HERE, _HERE.resolve())))

# 읽어 둘 폴더 (partner_sw 기준) — 담당자 자료가 있는 곳
DATA_DIRS: tuple[str, ...] = ("agent_strategy/res", "agent_strategy/runtime", "agent_validation_1/res")
DATA_SUFFIXES: tuple[str, ...] = (".json", ".md")


def _rel(path: str | os.PathLike[str]) -> str | None:
    """partner_sw 기준 상대 경로(대소문자 · 구분자 맞춤). 폴더 밖이면 None. 디스크를 보지 않는다."""
    full = os.path.normcase(os.path.abspath(os.fspath(path)))
    for root in _ROOTS:
        if full.startswith(root + os.sep):
            return full[len(root) + 1:]
    return None


def _load() -> dict[str, str]:
    texts: dict[str, str] = {}
    for folder in DATA_DIRS:
        base = _HERE / folder
        if not base.is_dir():
            continue
        for file in sorted(base.rglob("*")):
            if file.suffix.lower() in DATA_SUFFIXES and file.is_file():
                key = _rel(file)
                if key is not None:
                    texts[key] = file.read_text(encoding="utf-8-sig")
    return texts


# 상대 경로 → 글자 (불러올 때 한 번)
TEXTS: dict[str, str] = _load()


def exists(path: str | os.PathLike[str]) -> bool:
    """읽어 둔 자료 파일인지 (`Path.exists()` 대신)."""
    key = _rel(path)
    return key is not None and key in TEXTS


def read(path: str | os.PathLike[str]) -> str:
    """읽어 둔 자료 파일의 글자 (`Path.read_text()` 대신). 없으면 FileNotFoundError — 메시지에 경로를 넣지 않는다."""
    key = _rel(path)
    if key is None or key not in TEXTS:
        raise FileNotFoundError("담당자 자료 파일 없음")
    return TEXTS[key]
