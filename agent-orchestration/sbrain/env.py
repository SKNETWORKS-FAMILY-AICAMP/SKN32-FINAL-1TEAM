"""환경 변수를 .env 파일에서도 읽는다 (사용자 요청 2026-10-01).

- 찾는 순서: 프로세스 환경 변수 → .env → 기본값. 이미 설정된 환경 변수가 이긴다.
  운영 서버는 환경 변수로, 개발 PC는 .env로 줄 수 있다.
- .env 위치는 코드 폴더(sbrain 패키지가 있는 폴더)의 .env. 다른 파일은 path로 넘긴다.
  상위 폴더를 거슬러 올라가며 찾지 않는다.
- 빈 값(`KEY=`)은 설정하지 않은 것으로 본다.
- 값은 적힌 그대로 읽는다(`${VAR}` 치환 없음) — 비밀번호에 `$`가 있어도 바뀌지 않게.
- os.environ을 바꾸지 않는다. 값을 로그에 남기지 않는다.
- .env는 Git · 저장소 사본에 올리지 않는다. 적을 항목은 .env.example에 있다.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def read_env_file(path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """.env 파일의 값(빈 값 제외). 파일이 없으면 빈 dict."""
    p = Path(path) if path is not None else DEFAULT_ENV_FILE
    if not p.is_file():
        return {}
    # utf-8-sig: 메모장 · PowerShell이 붙이는 BOM이 첫 키 이름에 섞이지 않게
    values = dotenv_values(p, interpolate=False, encoding="utf-8-sig")
    return {k: v for k, v in values.items() if v}


def get_env(name: str, default: str | None = None, *,
            path: str | os.PathLike[str] | None = None) -> str | None:
    """환경 변수 → .env → default 순서로 값을 찾는다."""
    value = os.environ.get(name)
    if value:
        return value
    return read_env_file(path).get(name, default)
