"""T-B1(실행 파일 HTML 제작) 자체 검열 게이트.

이 모듈은 채점 모듈(verification_agent, R-4 8항목)의 일부가 아니다.
T-B1이 자기 출력을 Supervisor에게 반환하기 전에 스스로 거르는 사전 검열이며,
"만드는 쪽이 자기 기준으로 자기 점수를 매기는" 구조를 피하기 위해 채점 로직과
물리적으로 분리해 둔다(CLAUDE.md의 verification_agent/engineering_agent 분리 원칙 참고).
verification_agent는 여기서 절대 import하지 않는다.
"""
import re

# 외부 스킴 판정: http:, https:, 프로토콜 상대(//)로 시작하면 외부.
# data: URI와 상대경로(./foo.png, foo.js 등)는 허용 대상이라 이 정규식에 안 걸려야 한다.
_EXTERNAL_SCHEME_RE = re.compile(r'^(?:https?:)?//|^https?:', re.IGNORECASE)

# 인라인 <style> 블록만 골라내 그 안에서 @import를 찾는다 — @import url(...)은
# CSS 문법상 <style> 태그 안에서만 등장하므로, 블록 밖 텍스트(예: 주석·본문)에
# 우연히 같은 문자열이 있어도 오탐하지 않도록 범위를 좁힌다.
_STYLE_BLOCK_RE = re.compile(r'<style\b[^>]*>(.*?)</style>', re.IGNORECASE | re.DOTALL)
_IMPORT_URL_RE = re.compile(r'@import\s+url\(\s*["\']?([^"\')]+)["\']?\s*\)', re.IGNORECASE)

_SCRIPT_SRC_RE = re.compile(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_LINK_STYLESHEET_RE = re.compile(
    r'<link\b(?=[^>]*\brel\s*=\s*["\']stylesheet["\'])[^>]*\bhref\s*=\s*["\']([^"\']+)["\']'
    r'|<link\b(?=[^>]*\bhref\s*=\s*["\']([^"\']+)["\'])[^>]*\brel\s*=\s*["\']stylesheet["\']',
    re.IGNORECASE,
)
_IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


# --- E-B1-SANDBOX: sandbox iframe에서 죽는 API 검출 --------------------------
# 프론트는 결과 HTML을 sandbox="allow-scripts" iframe에 띄운다(front/src/features/
# workflow/ArtifactResult.jsx · shared.jsx). allow-same-origin이 없어 origin이 opaque이므로
# 스토리지 접근은 예외를 던져 스크립트 전체를 멈추고, allow-modals/allow-forms가 없어
# 모달과 submit은 조용히 무시된다. 어느 쪽이든 "동작을 확인할 수 있는 실행 파일"이라는
# 산출물 조건이 깨지므로, 프롬프트로 지시하는 것에 더해 코드로 막는다.
# (검출 범위를 <script> 블록과 on* 이벤트 핸들러 속성으로 좁혀, 본문 글에 같은 낱말이
#  섞였을 때 오탐하지 않게 한다.)
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


def check_sandbox_api_gate(html_content: str) -> tuple[bool, list[str]]:
    """E-B1-SANDBOX: sandbox iframe에서 동작을 깨뜨리는 API 사용을 막는다.

    반환: (통과여부, 위반 목록). 첫 위반에서 멈추지 않고 전부 모아 돌려준다 —
    상위 Supervisor가 한 번의 재수행 지시로 모두 고치게 해야 하기 때문.
    """
    scripts = _SCRIPT_BLOCK_RE.findall(html_content)
    handlers = [m.group(1) for m in _EVENT_ATTR_RE.finditer(html_content)]
    code = "\n".join(scripts + handlers)

    violations: list[str] = []
    for pattern, label in _SANDBOX_FORBIDDEN:
        if pattern.search(code):
            violations.append(label)
    return not violations, violations


def _is_external(url: str) -> bool:
    """data: URI와 상대경로는 허용, http(s):// 및 // 는 위반."""
    url = url.strip().strip('\'"')
    if url.lower().startswith('data:'):
        return False
    return bool(_EXTERNAL_SCHEME_RE.match(url))


def check_entry_file_gate(files: dict[str, str], entry_filename: str) -> tuple[bool, str]:
    """E-B1-ENTRY: LLM이 다른 파일명을 지어내 진입 파일 자체가 없는 상태로
    성공을 자처하는 경우를 막는 최소 게이트. 반환: (통과여부, 실패시 사유)
    """
    if entry_filename not in files:
        return False, f"진입 파일 '{entry_filename}'이 생성된 파일 목록에 없음: {sorted(files.keys())}"
    if not files[entry_filename].strip():
        return False, f"진입 파일 '{entry_filename}' 내용이 비어 있음"
    return True, ""


def check_external_dependency_gate(html_content: str) -> tuple[bool, list[str]]:
    """E-B1-DEP: "외부 빌드 도구 없이 동작하는 단일 HTML"이라는 산출물 제약을
    코드로 강제한다. script src / link stylesheet href / img src / 인라인 스타일 안
    @import 중 외부 스킴(http:, https:, //)이 하나라도 있으면 위반.
    첫 위반에서 멈추지 않고 전부 모아서 반환한다 — 상위 Supervisor가 한 번에 재시도
    지시를 만들 수 있어야 하기 때문.
    """
    violations: list[str] = []

    for m in _SCRIPT_SRC_RE.finditer(html_content):
        url = m.group(1)
        if _is_external(url):
            violations.append(f'script: {url}')

    for m in _LINK_STYLESHEET_RE.finditer(html_content):
        url = m.group(1) or m.group(2)
        if _is_external(url):
            violations.append(f'stylesheet link: {url}')

    for m in _IMG_SRC_RE.finditer(html_content):
        url = m.group(1)
        if _is_external(url):
            violations.append(f'img: {url}')

    for style_block in _STYLE_BLOCK_RE.findall(html_content):
        for m in _IMPORT_URL_RE.finditer(style_block):
            url = m.group(1)
            if _is_external(url):
                violations.append(f'@import: {url}')

    return len(violations) == 0, violations
