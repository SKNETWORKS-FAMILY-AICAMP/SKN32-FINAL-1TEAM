"""구현 담당자(engineering_agent) 자료 파일 — 불러올 때 한 번 읽어 둔 상수 (패키지 자료 예외와 같은 방식).

담당자 코드는 글꼴 · 대표 그림 SVG · 인포그래픽 템플릿을 Task 실행 중에 디스크에서 읽었다(`lru_cache` · `read_bytes` ·
`read_text`). 우리 규칙은 Task 실행 중 디스크에 닿지 않는 것이라, 이 모듈이 처음 불러올 때 아래 파일을 모두 읽어 두고
담당자 코드(`infographic/fonts.py` · `infographic/illustrations.py` · `infographic/render.py` · `html_kit.py`)는 이 상수만
쓰게 바꿨다(`[S-Brain]` 주석, VENDORED.md 3절).

- FONT: Pretendard 부분 글꼴(`infographic/assets/pretendard-ksx1001.woff2`, SIL OFL 1.1) 바이트. 없으면 b"" — 담당자 동작대로
  글꼴을 넣지 않고 기본 글꼴로 둔다.
- ILLUSTRATIONS: 장면 이름 → 대표 그림 SVG 바이트(`infographic/assets/illustrations/<장면>.svg`, CC0). 없는 장면은 사전에 없다.
- TEMPLATES: 파일 이름 → 인포그래픽 템플릿 SVG 글자(`infographic_templates/*.svg`, utf-8). `template(name)`으로 읽는다 —
  없으면 FileNotFoundError(메시지에 이름 · 경로를 넣지 않는다).

엔지니어링 자료만 둔다. 검증-2(verification_agent)는 이 모듈을 쓰지 않는다(두 담당자 패키지 분리). 산출물이 아니라 코드의
일부다 — 내용을 기록 · 로그 · 예외 메시지에 넣지 않는다.
"""
from __future__ import annotations

from pathlib import Path

_ENG = Path(__file__).parent / "engineering_agent"
_ASSETS = _ENG / "infographic" / "assets"
_ILLUSTRATIONS_DIR = _ASSETS / "illustrations"
_TEMPLATES_DIR = _ENG / "infographic_templates"


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _load_illustrations() -> dict[str, bytes]:
    if not _ILLUSTRATIONS_DIR.is_dir():
        return {}
    out = {}
    for file in sorted(_ILLUSTRATIONS_DIR.glob("*.svg")):
        data = _read_bytes(file)
        if data:
            out[file.stem] = data
    return out


def _load_templates() -> dict[str, str]:
    if not _TEMPLATES_DIR.is_dir():
        return {}
    return {file.name: file.read_text(encoding="utf-8") for file in sorted(_TEMPLATES_DIR.glob("*.svg"))}


# 불러올 때 한 번
FONT: bytes = _read_bytes(_ASSETS / "pretendard-ksx1001.woff2")
ILLUSTRATIONS: dict[str, bytes] = _load_illustrations()
TEMPLATES: dict[str, str] = _load_templates()


def template(name: str) -> str:
    """읽어 둔 템플릿 글자 (`(_TEMPLATE_DIR / name).read_text(encoding='utf-8')` 대신). 없으면 FileNotFoundError."""
    try:
        return TEMPLATES[name]
    except KeyError:
        raise FileNotFoundError("구현 담당자 템플릿 파일 없음") from None
