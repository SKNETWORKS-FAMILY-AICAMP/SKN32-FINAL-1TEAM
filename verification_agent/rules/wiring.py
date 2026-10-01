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


def _selectors(script: str) -> list[str]:
    """요소 하나를 id로 집는 식의 정규식 목록. 각 식은 id를 캡처 그룹 하나로 잡는다."""
    helpers = {m.group(1) for regex in _HELPER_RES for m in regex.finditer(script)}
    return [_BY_ID, _BY_QUERY] + [
        rf"""(?<![\w$.]){re.escape(name)}\(\s*['"]([\w-]+)['"]\s*\)""" for name in sorted(helpers)
    ]


def id_refs(script: str) -> set[str]:
    """스크립트가 id로 찾는 요소 전부(도우미 함수 호출 포함). 끊어진 참조 판정용."""
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
    """
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
