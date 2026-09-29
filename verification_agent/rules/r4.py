"""HTML 프로토타입(웹개발 · AI_API) 코드 점검 8항목.

기획서 5-4의 초기 배점표는 검증-2 담당이 재구성했다(2026-09-29). 바뀐 이유는
`기획서_개정안_산출물층_검증.md`에 있다. 요약하면:
- 정상 산출물이면 항상 통과하던 진입 파일·안내 문서·비밀값은 점수에서 빼고 통과 필수
  조건(rules/gates.py)으로 옮겼다. lang 속성은 생성 지시로 고정돼 뺐다.
- 그 자리에 "화면이 실제로 동작하는가"를 보는 항목(동작 연결, 끊어진 참조, 1440px 폭,
  임시 문구)을 넣었다.

| No | 항목 | 배점 |
|:-:|---|:-:|
| 1 | 동작 연결 | 3 |
| 2 | img·svg 대체 텍스트 | 2 |
| 3 | input label 연결 | 2 |
| 4 | 명도 대비 4.5:1 | 2 |
| 5 | 제목 계층 | 1 |
| 6 | 1440px 폭 안에 들어옴 | 2 |
| 7 | 끊어진 id 참조 없음 | 2 |
| 8 | 임시 문구 없음 | 1 |

전부 순수 함수다 — 같은 입력이면 몇 번을 돌려도 같은 결과가 나와야 채점이 재현된다.
HTML 파싱은 표준 라이브러리 html.parser.HTMLParser만 쓴다.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from verification_agent.rules.items import item

# 닫는 태그 없이도 끝나는 요소들 — 스택에 올리면 짝이 맞는 </...>가 영영 오지 않아
# 스택이 오염된다.
_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

_EXCLUDED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}
_CONTROL_INPUT_TYPES = {"button", "submit", "image"}
_HIDDEN_TAGS = ("script", "style", "template")
_SIZED_TAGS = {"img", "svg", "canvas", "table", "iframe", "video", "div", "section"}

# 프론트가 iframe에 띄우는 폭(프론트_연동_가이드.md).
PAGE_WIDTH_PX = 1440


class _PageParser(HTMLParser):
    """한 번의 파싱으로 8항목과 계획서 대조에 필요한 것을 모두 모은다.

    검사마다 새 인스턴스를 만들므로 호출 간 상태 공유가 없다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_attrs: dict[str, str] | None = None
        self.img_records: list[dict] = []
        self.svg_records: list[dict] = []
        self.input_records: list[dict] = []
        self.label_for_targets: set[str] = set()
        self.headings: list[int] = []
        self.style_chunks: list[str] = []
        self.inline_styles: list[str] = []
        self.wide_attrs: list[str] = []
        self.script_chunks: list[str] = []
        self.visible: list[str] = []
        self.ids: set[str] = set()
        self.controls: list[dict] = []

        self._stack: list[str] = []  # input의 <label> 중첩 판정용 열린 태그 스택
        self._svg_stack: list[dict] = []
        self._forms: list[dict] = []
        self._open_controls: list[tuple[str, dict]] = []
        self._title_capture: list[str] | None = None
        self._in_style = False
        self._in_script = False
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self_closing=True)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        a = {name: (value if value is not None else "") for name, value in attrs}
        has_handler = any(name.startswith("on") for name in a)

        if a.get("id"):
            self.ids.add(a["id"])
        if a.get("style"):
            self.inline_styles.append(a["style"])
        if tag in _SIZED_TAGS and a.get("width"):
            try:
                if float(a["width"].rstrip("px")) > PAGE_WIDTH_PX:
                    self.wide_attrs.append(f'<{tag} width="{a["width"]}">')
            except ValueError:
                pass

        if tag == "form":
            self._forms.append({"id": a.get("id", ""), "handler": has_handler})

        input_type = (a.get("type") or "text").strip().lower() if tag == "input" else ""
        is_control = (tag == "button"
                      or (tag == "input" and input_type in _CONTROL_INPUT_TYPES)
                      or "data-feature" in a or a.get("role") == "button"
                      or (has_handler and tag not in ("body", "form", "html")))
        if is_control:
            button_type = (a.get("type") or "submit").strip().lower()
            record = {
                "tag": tag, "id": a.get("id", ""), "feature": a.get("data-feature", ""),
                "aria": a.get("aria-label", ""), "value": a.get("value", ""),
                "text": [], "inline": has_handler,
                "form": self._forms[-1] if self._forms else None,
                "submits": (tag == "button" and button_type == "submit")
                           or input_type in ("submit", "image"),
            }
            self.controls.append(record)
            if not self_closing and tag not in _VOID_ELEMENTS:
                self._open_controls.append((tag, record))

        if tag == "html" and self.html_attrs is None:
            self.html_attrs = a
        elif tag == "img":
            self.img_records.append({"alt": a.get("alt")})
        elif tag == "svg":
            record = {"aria_label": a.get("aria-label"), "has_title": False}
            self.svg_records.append(record)
            if not self_closing:
                self._svg_stack.append(record)
        elif tag == "title" and self._svg_stack:
            # svg 내부의 title만 캡처한다 — <head><title>은 svg 대체텍스트와 무관하다.
            self._title_capture = []
        elif tag == "label":
            if a.get("for"):
                self.label_for_targets.add(a["for"])
        elif tag == "input":
            self.input_records.append({
                "id": a.get("id"), "type": input_type,
                "aria_label": a.get("aria-label"),
                "aria_labelledby": a.get("aria-labelledby"),
                "nested_in_label": "label" in self._stack,
            })
        elif tag in _HEADING_TAGS:
            self.headings.append(int(tag[1]))

        if tag in _HIDDEN_TAGS and not self_closing:
            self._hidden += 1
            self._in_style = tag == "style"
            self._in_script = tag == "script" and "src" not in a

        if not self_closing and tag not in _VOID_ELEMENTS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_capture is not None:
            if "".join(self._title_capture).strip() and self._svg_stack:
                self._svg_stack[-1]["has_title"] = True
            self._title_capture = None
        if tag == "svg" and self._svg_stack:
            self._svg_stack.pop()
        if tag == "form" and self._forms:
            self._forms.pop()
        if tag in _HIDDEN_TAGS:
            self._hidden = max(0, self._hidden - 1)
            self._in_style = self._in_script = False
        for i in range(len(self._open_controls) - 1, -1, -1):
            if self._open_controls[i][0] == tag:
                del self._open_controls[i]
                break

        # 닫는 태그 누락에도 스택이 무한히 자라지 않도록 가장 안쪽 같은 이름까지 걷어낸다.
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self._title_capture is not None:
            self._title_capture.append(data)
        if self._in_style:
            self.style_chunks.append(data)
        if self._in_script:
            self.script_chunks.append(data)
        if not self._hidden:
            self.visible.append(data)
            for _, record in self._open_controls:
                record["text"].append(data)


def parse_page(html_content: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html_content)
    return parser


# ── 동작 연결 판정 (1번 항목과 계획서 대조가 같이 쓴다) ─────────────

_SELECTOR = (r"""(?:getElementById\(\s*['"]([\w-]+)['"]\s*\)"""
             r"""|querySelector\(\s*['"]#([\w-]+)['"]\s*\))""")
_BIND = r"\s*(?:\?\.|\.)\s*(?:addEventListener\s*\(|on[a-z]+\s*=(?!=))"
_DIRECT_RE = re.compile(r"document\s*\." + _SELECTOR + _BIND)
_ASSIGN_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\s*\." + _SELECTOR)
_REF_RE = re.compile(r"""(?:getElementById\(\s*['"]([\w-]+)['"]\s*\)"""
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


def check_action_wiring(parser: _PageParser) -> dict:
    """1. 동작 연결: 버튼·조작 요소 중 핸들러가 직접 붙은 비율로 부분 점수."""
    controls = parser.controls
    if not controls:
        return item(1, "동작 연결", 3, False, "조작 요소(button 등) 0개 — 동작하는 화면이 없음")
    wired = wired_ids("\n".join(parser.script_chunks))
    dead = [control_label(c) for c in controls if not is_wired(c, wired)]
    ok = len(controls) - len(dead)
    evidence = f"조작 요소 {ok}/{len(controls)}개 연결"
    if dead:
        evidence += f" — 연결 없음: {', '.join(repr(d[:20]) for d in dead[:3])}"
        if len(dead) > 3:
            evidence += f" 외 {len(dead) - 3}개"
    return item(1, "동작 연결", 3, not dead, evidence, earned=3 * ok / len(controls))


# ── 2. 대체 텍스트 ───────────────────────────────────────────────


def _alt_failures(parser: _PageParser, prefix: str = "") -> tuple[int, list[str]]:
    failures: list[str] = []
    for rec in parser.img_records:
        if rec.get("alt") is None or rec["alt"].strip() == "":
            failures.append(f"{prefix}img alt 누락 또는 공백")
    for rec in parser.svg_records:
        if not rec.get("has_title") and not (rec.get("aria_label") or "").strip():
            failures.append(f"{prefix}svg title 자식/aria-label 모두 없음")
    return len(parser.img_records) + len(parser.svg_records), failures


def check_alt_text(parser: _PageParser, infographic_svg: str | None = None) -> dict:
    """2. img·svg 대체 텍스트. T-B2 인포그래픽도 같이 본다 — 인포그래픽 대체 텍스트
    미충족은 T-B2 재수행으로 이어진다(기능정의서 오류→재수행 매핑)."""
    count, failures = _alt_failures(parser)
    if infographic_svg:
        info_count, info_failures = _alt_failures(parse_page(infographic_svg), "[인포그래픽] ")
        count += info_count
        failures += info_failures
    if not count:
        return item(2, "img·svg 대체 텍스트", 2, True, "이미지 0개", applicable=False)
    evidence = f"검사 대상 {count}건 전부 통과" if not failures else "; ".join(failures)
    return item(2, "img·svg 대체 텍스트", 2, not failures, evidence)


# ── 3. input label ────────────────────────────────────────────


def check_input_label(parser: _PageParser) -> dict:
    """3. id-for / aria-label(-by) / label 중첩 중 하나면 된다. input이 없으면 해당 없음."""
    failures: list[str] = []
    checked = 0
    for rec in parser.input_records:
        if rec["type"] in _EXCLUDED_INPUT_TYPES:
            continue
        checked += 1
        id_match = bool(rec.get("id")) and rec["id"] in parser.label_for_targets
        aria_match = bool((rec.get("aria_label") or "").strip()
                          or (rec.get("aria_labelledby") or "").strip())
        if not (id_match or aria_match or rec.get("nested_in_label")):
            failures.append(f"input(id={rec.get('id')!r}) 라벨 연결 수단 없음")
    if not checked:
        return item(3, "input label 연결", 2, True, "입력 요소 0개", applicable=False)
    evidence = f"검사 대상 input {checked}개 전부 통과" if not failures else "; ".join(failures)
    return item(3, "input label 연결", 2, not failures, evidence)


# ── 4. 명도 대비 ──────────────────────────────────────────────

# CSS Level 1 기본 색상 이름 + 생성 산출물에서 흔히 쓰이는 몇 가지.
_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "lime": (0, 255, 0), "aqua": (0, 255, 255),
    "teal": (0, 128, 128), "navy": (0, 0, 128), "fuchsia": (255, 0, 255),
    "purple": (128, 0, 128), "orange": (255, 165, 0), "pink": (255, 192, 203),
    "brown": (165, 42, 42),
}

_HEX_RE = re.compile(r"^#([0-9a-f]{3,8})$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*[\d.]+\s*)?\)$"
)


def _parse_color(value: str) -> tuple[int, int, int] | None:
    """hex/rgb/rgba/기본 명명색만 지원한다. HSL 등은 판정불가로 처리."""
    v = value.strip().lower()
    if v in _NAMED_COLORS:
        return _NAMED_COLORS[v]

    hex_match = _HEX_RE.match(v)
    if hex_match:
        hex_part = hex_match.group(1)
        if len(hex_part) in (3, 4):
            hex_part = "".join(ch * 2 for ch in hex_part[:3])
        elif len(hex_part) in (6, 8):
            hex_part = hex_part[:6]
        else:
            return None
        try:
            return (int(hex_part[0:2], 16), int(hex_part[2:4], 16), int(hex_part[4:6], 16))
        except ValueError:
            return None

    rgb_match = _RGB_RE.match(v)
    if rgb_match:
        try:
            r, g, b = (min(255, max(0, round(float(rgb_match.group(i))))) for i in (1, 2, 3))
            return (r, g, b)
        except ValueError:
            return None
    return None


def _srgb_channel_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_channel_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    l1 = _relative_luminance(rgb_a)
    l2 = _relative_luminance(rgb_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _background_shorthand_color(value: str) -> str | None:
    """background 단축 속성에서 색상 토큰만 뽑는다. url()·그라디언트는 판정 밖."""
    if "url(" in value.lower() or "gradient" in value.lower():
        return None
    for token in re.split(r"\s+", value.strip()):
        if token and _parse_color(token) is not None:
            return token
    return None


def _extract_paired_declarations(css_text: str) -> list[tuple[str, dict[str, str]]]:
    """같은 셀렉터 블록 안에 글자색과 배경색이 함께 명시된 것만 추린다.

    캐스케이드·상속 계산은 브라우저 스타일 엔진이 필요하다 — 이 모듈은 "같은 셀렉터에
    명시적으로 짝지어 선언된 경우"만 검사 범위로 못박아 재현성을 지킨다.
    """
    css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    pairs: list[tuple[str, dict[str, str]]] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = match.group(1).strip()
        if not selector or selector.startswith("@"):
            continue
        declared: dict[str, str] = {}
        shorthand_bg: str | None = None
        for decl in match.group(2).split(";"):
            if ":" not in decl:
                continue
            prop, _, val = decl.partition(":")
            prop = prop.strip().lower()
            if prop in ("color", "background-color"):
                declared[prop] = val.strip()
            elif prop == "background":
                shorthand_bg = _background_shorthand_color(val)
        if "background-color" not in declared and shorthand_bg is not None:
            declared["background-color"] = shorthand_bg
        if "color" in declared and "background-color" in declared:
            pairs.append((selector, declared))
    return pairs


def check_contrast(parser: _PageParser) -> dict:
    """4. 명도 대비 4.5:1. 판정 대상(색상 짝) 0개면 해당 없음이 아니라 미통과다 —
    생성 지시(T-B1 규칙 8)가 짝 선언을 요구하므로, 없으면 지시를 어긴 것이다."""
    pairs = _extract_paired_declarations("".join(parser.style_chunks))
    if not pairs:
        return item(4, "명도 대비 4.5:1", 2, False,
                    "color/background-color가 함께 명시된 셀렉터 없음(판정 대상 0개)")
    failures: list[str] = []
    for selector, decl in pairs:
        fg, bg = _parse_color(decl["color"]), _parse_color(decl["background-color"])
        if fg is None or bg is None:
            failures.append(f"{selector}: 색상값 해석 불가({decl['color']} / {decl['background-color']})")
            continue
        ratio = _contrast_ratio(fg, bg)
        if ratio < 4.5:
            failures.append(f"{selector}: 대비비 {ratio:.2f} < 4.5")
    evidence = f"검사 대상 {len(pairs)}쌍 전부 통과" if not failures else "; ".join(failures)
    return item(4, "명도 대비 4.5:1", 2, not failures, evidence)


# ── 5. 제목 계층 ──────────────────────────────────────────────


def check_heading_hierarchy(parser: _PageParser) -> dict:
    """5. h1 정확히 1개 + 내려갈 때 레벨 건너뛰기 금지(올라가는 건 허용)."""
    headings = parser.headings
    skip_at: int | None = None
    for idx in range(1, len(headings)):
        if headings[idx] > headings[idx - 1] + 1:
            skip_at = idx
            break
    passed = headings.count(1) == 1 and skip_at is None
    evidence = f"h1 개수={headings.count(1)}, 문서순서={headings}, 건너뛰기위치={skip_at}"
    return item(5, "제목 계층", 1, passed, evidence)


# ── 6. 1440px 폭 ──────────────────────────────────────────────

# max-width는 넘침을 막는 쪽이라 제외한다(앞 글자가 '-'면 매치하지 않음).
_WIDTH_RE = re.compile(r"(?<![-\w])((?:min-)?width)\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)


def check_layout_width(parser: _PageParser) -> dict:
    """6. 고정 폭이 1440px을 넘는 선언이 없는지. 넘으면 프론트 iframe에서 가로 스크롤이
    생기고 화면 오른쪽이 잘린다."""
    css = "\n".join(parser.style_chunks + parser.inline_styles)
    wide = [f"{prop}:{value}px" for prop, value in _WIDTH_RE.findall(css)
            if float(value) > PAGE_WIDTH_PX]
    wide += parser.wide_attrs
    evidence = (f"{PAGE_WIDTH_PX}px 초과 고정 폭 없음" if not wide
                else f"{PAGE_WIDTH_PX}px 초과: {', '.join(wide[:3])}")
    return item(6, f"{PAGE_WIDTH_PX}px 폭 안에 들어옴", 2, not wide, evidence)


# ── 7. 끊어진 참조 ────────────────────────────────────────────


def check_broken_refs(parser: _PageParser) -> dict:
    """7. 스크립트가 찾는 id가 문서에 실제로 있는지. 없으면 null에 메서드를 부르다
    스크립트가 멈춘다. 스크립트가 id를 하나도 찾지 않으면 해당 없음."""
    script = "\n".join(parser.script_chunks)
    refs = {a or b for a, b in _REF_RE.findall(script)}
    if not refs:
        return item(7, "끊어진 id 참조 없음", 2, True, "스크립트의 id 참조 0개", applicable=False)
    broken = sorted(refs - parser.ids)
    evidence = (f"참조 {len(refs)}개 전부 문서에 있음" if not broken
                else f"문서에 없는 id {len(broken)}개: {', '.join(broken[:5])}")
    return item(7, "끊어진 id 참조 없음", 2, not broken, evidence)


# ── 8. 임시 문구 ──────────────────────────────────────────────

_PLACEHOLDER_TEXT_RE = [
    re.compile(r"lorem\s+ipsum", re.IGNORECASE),
    re.compile(r"\bTODO\s*:"),
    re.compile(r"\bFIXME\b"),
    re.compile(r"\bTBD\b"),
    re.compile(r"샘플\s*텍스트"),
    re.compile(r"예시\s*텍스트"),
    re.compile(r"여기에\s*(?:내용|텍스트)"),
    re.compile(r"[(\[]\s*(?:내용|텍스트)\s*[)\]]"),
]


def check_placeholder_text(parser: _PageParser) -> dict:
    """8. 화면에 보이는 글자에 덜 만든 흔적이 없는지. input의 placeholder 속성은
    보이는 글자가 아니므로 보지 않는다."""
    visible = " ".join(parser.visible)
    hits = [m.group(0) for pattern in _PLACEHOLDER_TEXT_RE
            for m in [pattern.search(visible)] if m]
    evidence = "임시 문구 없음" if not hits else f"임시 문구: {', '.join(repr(h) for h in hits)}"
    return item(8, "임시 문구 없음", 1, not hits, evidence)


ITEM_DEFS: tuple[tuple[int, str, float], ...] = (
    (1, "동작 연결", 3), (2, "img·svg 대체 텍스트", 2), (3, "input label 연결", 2),
    (4, "명도 대비 4.5:1", 2), (5, "제목 계층", 1),
    (6, f"{PAGE_WIDTH_PX}px 폭 안에 들어옴", 2), (7, "끊어진 id 참조 없음", 2),
    (8, "임시 문구 없음", 1),
)


def check_html(html_content: str, infographic_svg: str | None = None) -> list[dict]:
    parser = parse_page(html_content)
    return [
        check_action_wiring(parser),
        check_alt_text(parser, infographic_svg),
        check_input_label(parser),
        check_contrast(parser),
        check_heading_hierarchy(parser),
        check_layout_width(parser),
        check_broken_refs(parser),
        check_placeholder_text(parser),
    ]
