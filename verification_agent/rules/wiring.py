"""버튼 등 조작 요소에 이벤트가 실제로 연결됐는지 판정한다.

코드 점검 1번(동작 연결)과 계획서 대조(HTML)가 같은 판정을 쓴다. 둘이 다르게 판정하면
"동작 연결은 만점인데 대조에서는 연결 안 됨" 같은 모순이 생긴다.
"""
from __future__ import annotations

import re

_NAME = r"[A-Za-z_$][\w$]*"
_BY_ID = r"""document\s*\.\s*getElementById\(\s*['"]([\w-]+)['"]\s*\)"""
_BY_QUERY = r"""document\s*\.\s*querySelector\(\s*['"]#([\w-]+)['"]\s*\)"""
_BIND = r"\s*(?:\?\.|\.)\s*(?:addEventListener\s*\(|on[a-z]+\s*=(?!=))"
# 인자를 그대로 getElementById에 넘기기만 하는 도우미 함수. 모델이 흔히 만든다.
#   const $ = id => document.getElementById(id);
#   function byId(id) { return document.getElementById(id); }
#   const $ = function (id) { return document.getElementById(id); };
_HELPER_RES = (
    re.compile(rf"\b(?:const|let|var)\s+({_NAME})\s*=\s*function\s*\(\s*({_NAME})\s*\)\s*\{{\s*"
               rf"return\s+document\s*\.\s*getElementById\(\s*\2\s*\)"),
    re.compile(rf"\b(?:const|let|var)\s+({_NAME})\s*=\s*\(?\s*({_NAME})\s*\)?\s*=>\s*"
               rf"(?:\{{\s*return\s+)?document\s*\.\s*getElementById\(\s*\2\s*\)"),
    re.compile(rf"\bfunction\s+({_NAME})\s*\(\s*({_NAME})\s*\)\s*\{{\s*"
               rf"return\s+document\s*\.\s*getElementById\(\s*\2\s*\)"),
)
_ID_REF_RE = re.compile(r"""(?:getElementById\(\s*['"]([\w-]+)['"]\s*\)"""
                        r"""|querySelector(?:All)?\(\s*['"]#([\w-]+)['"]\s*\))""")


# 문자열 안에서 남겨 두는 값: 선택자 인자로 쓰이는 id 한 덩이('send', '#send', 'click').
# 이 밖의 글자가 든 문자열은 실행 코드가 아니므로 비운다.
_KEEP_STRING_RE = re.compile(r"#?[\w-]+")
# 이 글자 뒤의 '/'는 나눗셈이 아니라 정규식 리터럴의 시작이다.
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_AFTER_WORDS = ("return", "typeof", "case", "do", "else", "in", "of", "void", "yield")


def code_only(script: str) -> str:
    """주석 · 문자열 · 정규식 리터럴 속 글자를 공백으로 바꾼 스크립트(길이는 그대로).

    연결 판정 정규식은 실행 코드에만 걸어야 한다. 그러지 않으면
    `const s = \\`document.getElementById("x").addEventListener(...)\\`;`처럼 문자열이나
    주석에 적힌 호출이 실제 연결로 인정된다. 템플릿 문자열의 `${...}`는 실행식이므로 남긴다.
    JavaScript 전체를 해석하는 것이 아니라 주석 · 문자열의 경계만 가르는 최소 어휘 분석이다.
    """
    out = list(script)
    n = len(script)
    # 템플릿의 ${...} 안에 들어가 있으면 그 중괄호 깊이를 쌓는다.
    template_depths: list[int] = []
    depth = 0
    last = ""  # 마지막으로 본 공백 아닌 코드 글자(정규식 · 나눗셈 구별용)
    word = ""  # 마지막으로 본 낱말

    def blank(start: int, end: int) -> None:
        for k in range(start, end):
            if out[k] != "\n":
                out[k] = " "

    def template(i: int) -> int:
        """`i`는 여는 ` 또는 }의 다음 자리. ${를 만나면 그 뒤 자리를, 닫는 `면 그 뒤 자리를 낸다."""
        start = i
        while i < n:
            ch = script[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                blank(start, i)
                template_depths.pop()
                return i + 1
            if ch == "$" and i + 1 < n and script[i + 1] == "{":
                blank(start, i)
                return i + 2
            i += 1
        blank(start, n)
        return n

    i = 0
    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            end = script.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
            continue
        if ch == "/" and nxt == "*":
            end = script.find("*/", i + 2)
            end = n if end < 0 else end + 2
            blank(i, end)
            i = end
            continue
        if ch in "'\"":
            j = i + 1
            while j < n and script[j] != ch and script[j] != "\n":
                j += 2 if script[j] == "\\" else 1
            body = script[i + 1:min(j, n)]
            if not _KEEP_STRING_RE.fullmatch(body):
                blank(i + 1, min(j, n))
            i, last, word = j + 1, ch, ""
            continue
        if ch == "`":
            template_depths.append(depth)
            i = template(i + 1)
            last, word = "`", ""
            continue
        if ch == "/" and (last == "" or last in _REGEX_AFTER or word in _REGEX_AFTER_WORDS):
            j, in_class = i + 1, False
            while j < n and script[j] != "\n":
                c = script[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                j += 1
            if j < n and script[j] == "/":  # 같은 줄에서 닫히면 정규식 리터럴
                blank(i + 1, j)
                i, last, word = j + 1, "/", ""
                continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            if template_depths and depth == template_depths[-1]:
                i = template(i + 1)
                last, word = "`", ""
                continue
            depth -= 1
        if ch.isalnum() or ch in "_$":
            prev = script[i - 1] if i else ""
            word = word + ch if prev and (prev.isalnum() or prev in "_$") else ch
        elif not ch.isspace():
            word = ""
        if not ch.isspace():
            last = ch
        i += 1
    return "".join(out)


def _selectors(script: str) -> list[str]:
    """요소 하나를 id로 집는 식의 정규식 목록. 각 식은 id를 캡처 그룹 하나로 잡는다."""
    helpers = {m.group(1) for regex in _HELPER_RES for m in regex.finditer(script)}
    return [_BY_ID, _BY_QUERY] + [
        rf"""(?<![\w$.]){re.escape(name)}\(\s*['"]([\w-]+)['"]\s*\)""" for name in sorted(helpers)
    ]


def id_refs(script: str) -> set[str]:
    """스크립트가 id로 찾는 요소 전부(도우미 함수 호출 포함). 끊어진 참조 판정용."""
    script = code_only(script)
    found = {a or b for a, b in _ID_REF_RE.findall(script)}
    for selector in _selectors(script)[2:]:
        found.update(re.findall(selector, script))
    return found


def wired_ids(script: str) -> set[str]:
    """이벤트 핸들러가 **그 요소에 직접** 붙은 id.

    예전 판정은 "id가 스크립트 어딘가에 나오고, 스크립트 어딘가에 addEventListener가
    한 번이라도 있으면" 연결로 쳤다. 그러면 버튼 하나에만 리스너를 달아도 id가 문자열로
    등장하는 모든 버튼이 동작하는 것으로 채점됐다. 이제는 두 형태만 인정한다.
      document.getElementById('x').addEventListener(...)   (onclick = ... 도 같음)
      const b = document.getElementById('x'); b.addEventListener(...)
    document.getElementById 자리에는 querySelector('#x')와, 인자를 getElementById에
    그대로 넘기는 도우미 함수 호출($('x'))도 올 수 있다 — 요소 하나를 집는 것은 같다.
    이벤트 위임(document에 리스너 하나)과 querySelectorAll 반복문은 인정하지 않는다.
    생성 프롬프트(T-B1 규칙 9)가 직접 연결을 지시한다.
    주석 · 문자열에 적힌 호출은 실행되지 않으므로 보지 않는다(code_only).
    """
    script = code_only(script)
    found: set[str] = set()
    for selector in _selectors(script):
        found.update(re.findall(selector + _BIND, script))
        for name, target in re.findall(rf"\b(?:const|let|var)\s+({_NAME})\s*=\s*{selector}", script):
            if re.search(r"(?<![\w$.])" + re.escape(name) + _BIND, script):
                found.add(target)
    return found


def is_wired(control: dict, wired: set[str]) -> bool:
    if control["inline"] or (control["id"] and control["id"] in wired):
        return True
    form = control["form"]
    # 폼 안의 제출 버튼은 폼에 submit 리스너가 붙어 있으면 동작한다.
    return bool(control["submits"] and form
                and (form["handler"] or (form["id"] and form["id"] in wired)))


_FIELD_TAGS = {"input", "select", "textarea"}


def is_used(control: dict, wired: set[str], refs: set[str]) -> bool:
    """조작 요소가 화면 동작에 쓰이는지. 버튼은 이벤트가 직접 붙어야 하고(is_wired),
    입력칸(input · select · textarea)은 스크립트가 그 id로 값을 읽어 가면 쓰이는 것으로 본다.

    입력칸은 보통 자기 이벤트가 없다. "등록" 버튼의 핸들러가 getElementById('title').value로
    값을 읽는다. 이것을 연결 없음으로 치면 입력 화면이 많은 프로토타입일수록 점수가 깎인다
    (실측: 버튼 12개가 모두 동작하는 화면이 12/23으로 채점됨).
    """
    if is_wired(control, wired):
        return True
    return control["tag"] in _FIELD_TAGS and bool(control["id"]) and control["id"] in refs


def control_label(control: dict) -> str:
    return (control["feature"] or "".join(control["text"]).strip() or control["aria"]
            or control["value"] or control["id"] or f"<{control['tag']}>")
