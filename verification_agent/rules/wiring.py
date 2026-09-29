"""버튼 등 조작 요소에 이벤트가 실제로 연결됐는지 판정한다.

코드 점검 1번(동작 연결)과 계획서 대조(HTML)가 같은 판정을 쓴다. 둘이 다르게 판정하면
"동작 연결은 만점인데 대조에서는 연결 안 됨" 같은 모순이 생긴다.
"""
from __future__ import annotations

import re

_SELECTOR = (r"""(?:getElementById\(\s*['"]([\w-]+)['"]\s*\)"""
             r"""|querySelector\(\s*['"]#([\w-]+)['"]\s*\))""")
_BIND = r"\s*(?:\?\.|\.)\s*(?:addEventListener\s*\(|on[a-z]+\s*=(?!=))"
_DIRECT_RE = re.compile(r"document\s*\." + _SELECTOR + _BIND)
_ASSIGN_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\s*\." + _SELECTOR)
ID_REF_RE = re.compile(r"""(?:getElementById\(\s*['"]([\w-]+)['"]\s*\)"""
                     r"""|querySelector(?:All)?\(\s*['"]#([\w-]+)['"]\s*\))""")


def wired_ids(script: str) -> set[str]:
    """이벤트 핸들러가 **그 요소에 직접** 붙은 id.

    예전 판정은 "id가 스크립트 어딘가에 나오고, 스크립트 어딘가에 addEventListener가
    한 번이라도 있으면" 연결로 쳤다. 그러면 버튼 하나에만 리스너를 달아도 id가 문자열로
    등장하는 모든 버튼이 동작하는 것으로 채점됐다. 이제는 두 형태만 인정한다.
      document.getElementById('x').addEventListener(...)   (onclick = ... 도 같음)
      const b = document.getElementById('x'); b.addEventListener(...)
    이벤트 위임(document에 리스너 하나)과 querySelectorAll 반복문은 인정하지 않는다.
    생성 프롬프트(T-B1 규칙 9)가 직접 연결을 지시한다.
    """
    found = {a or b for a, b in _DIRECT_RE.findall(script)}
    for name, a, b in _ASSIGN_RE.findall(script):
        if re.search(r"(?<![\w$.])" + re.escape(name) + _BIND, script):
            found.add(a or b)
    return found


def is_wired(control: dict, wired: set[str]) -> bool:
    if control["inline"] or (control["id"] and control["id"] in wired):
        return True
    form = control["form"]
    # 폼 안의 제출 버튼은 폼에 submit 리스너가 붙어 있으면 동작한다.
    return bool(control["submits"] and form
                and (form["handler"] or (form["id"] and form["id"] in wired)))


def control_label(control: dict) -> str:
    return (control["feature"] or "".join(control["text"]).strip() or control["aria"]
            or control["value"] or control["id"] or f"<{control['tag']}>")
