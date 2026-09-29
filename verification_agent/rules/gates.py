"""통과 필수 조건. 점수가 아니라 채점 자격이다.

예전 8항목 중 진입 파일(3점)·비밀값(2점)은 정상 산출물이면 사실상 항상 통과해서 품질과
무관한 점수였다. 둘은 어기면 산출물로 쓸 수 없는 조건이므로 점수 칸에서 빼고 여기로
옮겼다. 하나라도 어기면 산출물층 30점 전체가 0이다.

실행 안내 문서(README)는 필수 조건이 아니다. README는 구현 Agent가 아니라 조율의 규칙
모듈(G-04, R-10)이 만들고, R-10은 "생성 실패 시 해당 항목만 미충족, 파이프라인은 계속"으로
정한다. 남의 모듈 실패로 산출물 점수 전체가 0이 되면 안 되므로, README 결함은 점수에
넣지 않고 경고(readme_warnings)로만 남긴다. 같은 이유로 비밀값 검사도 산출물 원문만 본다.

sandbox 금지 API는 engineering_agent.gates에도 같은 목록이 있지만 import하지 않는다
(ADR 0001 — 만드는 쪽과 채점하는 쪽을 코드로 섞지 않는다). 목록이 바뀌면 양쪽을 같이 고친다.
"""
from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

# ── 비밀값 ─────────────────────────────────────────────────────

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]([^'\"]{8,})['\"]"),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
]

_PLACEHOLDER_MARKERS = (
    "your_api_key", "your-api-key", "yourapikey", "xxx", "xxxxx",
    "<your-key>", "example", "test", "dummy", "placeholder",
)
_TEMPLATE_RE = re.compile(r"^\{\{.*\}\}$")


def _is_placeholder(value: str) -> bool:
    v = value.strip().strip("'\"").lower()
    if _TEMPLATE_RE.match(v):
        return True
    return any(marker in v for marker in _PLACEHOLDER_MARKERS)


def find_secret(*texts: str | None) -> str | None:
    """의심되는 비밀값 하나를 돌려준다. 없으면 None. 플레이스홀더는 오탐으로 거른다."""
    combined = "\n".join(t for t in texts if t)
    for pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(combined):
            # key=value 형태는 따옴표 안 값(group 2)을, 나머지는 매치 전체를 본다.
            candidate = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(0)
            if _is_placeholder(candidate) or _is_placeholder(match.group(0)):
                continue
            return match.group(0)[:50]
    return None


# ── sandbox 금지 API ───────────────────────────────────────────

_SCRIPT_BLOCK_RE = re.compile(r'<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>',
                              re.IGNORECASE | re.DOTALL)
_EVENT_ATTR_RE = re.compile(r'\bon[a-z]+\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)

_SANDBOX_FORBIDDEN: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r'\b(?:window\s*\.\s*)?localStorage\b'), 'localStorage'),
    (re.compile(r'\b(?:window\s*\.\s*)?sessionStorage\b'), 'sessionStorage'),
    (re.compile(r'\bdocument\s*\.\s*cookie\b'), 'document.cookie'),
    (re.compile(r'\b(?:window\s*\.\s*)?indexedDB\b'), 'indexedDB'),
    (re.compile(r'\b(?:window\s*\.\s*)?alert\s*\('), 'alert()'),
    (re.compile(r'\b(?:window\s*\.\s*)?confirm\s*\('), 'confirm()'),
    (re.compile(r'\b(?:window\s*\.\s*)?prompt\s*\('), 'prompt()'),
    (re.compile(r'\b(?:window\s*\.\s*)?open\s*\('), 'window.open()'),
    (re.compile(r'\blocation\s*(?:\.\s*href)?\s*='), '페이지 이동(location)'),
    (re.compile(r'\.\s*submit\s*\(\s*\)'), 'form.submit()'),
)


def sandbox_violations(html_content: str) -> list[str]:
    """script 블록과 on* 속성만 본다. 본문 글에 같은 낱말이 있어도 오탐하지 않는다."""
    scripts = _SCRIPT_BLOCK_RE.findall(html_content)
    handlers = [m.group(1) for m in _EVENT_ATTR_RE.finditer(html_content)]
    code = "\n".join(scripts + handlers)
    return [label for pattern, label in _SANDBOX_FORBIDDEN if pattern.search(code)]


# ── 조건 묶음 ──────────────────────────────────────────────────

_README_KEYWORDS_KO = ("실행", "열람", "사용법", "시작하기")
_README_KEYWORDS_EN = ("run", "getting started")


def _entry_matches(path: str, source: str, suffix: str) -> str | None:
    file = Path(path) if path else None
    if file is None or not file.is_file():
        return f"진입 파일 없음 ({path!r})"
    if file.suffix.lower() != suffix:
        return f"진입 파일 확장자가 {suffix}가 아님 ({file.name})"
    if not source.strip():
        return "진입 파일 원문이 비어 있음"
    if file.read_text(encoding="utf-8") != source:
        return "진입 파일과 Prototype.source_text 원문 불일치"
    return None


def html_gates(entry_file_path: str, source: str) -> list[str]:
    failures: list[str] = []
    entry = _entry_matches(entry_file_path, source, ".html")
    if entry:
        failures.append(entry)
    secret = find_secret(source)
    if secret:
        failures.append(f"하드코딩된 비밀값 의심: {secret!r}")
    blocked = sandbox_violations(source)
    if blocked:
        failures.append(f"sandbox에서 동작하지 않는 API: {', '.join(blocked)}")
    return failures


def svg_gates(entry_file_path: str, source: str) -> list[str]:
    failures: list[str] = []
    entry = _entry_matches(entry_file_path, source, ".svg")
    if entry:
        failures.append(entry)
    else:
        try:
            root = ET.fromstring(source)
            if root.tag.rsplit("}", 1)[-1] != "svg":
                failures.append("SVG 루트 요소가 아님")
        except ET.ParseError as exc:
            failures.append(f"SVG 파싱 실패: {exc}")
    secret = find_secret(source)
    if secret:
        failures.append(f"하드코딩된 비밀값 의심: {secret!r}")
    return failures


def readme_warnings(readme: str | None, kind: str) -> list[str]:
    """README 결함. 점수에는 넣지 않는다(모듈 docstring 참고). kind는 Prototype.kind."""
    if not readme or not readme.strip():
        return ["실행 안내 문서(README) 없음 — G-04 재실행 필요"]
    if kind == "svg-onepage":
        ok = "열람" in readme and "인쇄" in readme
        return [] if ok else ["README에 열람·인쇄 안내가 없음 — G-04 재실행 필요"]
    ok = (any(k in readme for k in _README_KEYWORDS_KO)
          or any(k in readme.lower() for k in _README_KEYWORDS_EN))
    return [] if ok else ["README에 실행·열람 안내가 없음 — G-04 재실행 필요"]
