"""HTML 프로토타입을 한 번 읽어 검사에 필요한 것을 모으는 파서.

코드 점검 8항목(r4.py)과 계획서 대조(feature_match.py)가 같은 파서 결과를 쓴다.
표준 라이브러리 html.parser만 쓴다. 검사마다 새 인스턴스를 만들므로 호출 간 상태 공유가 없다.
"""
from __future__ import annotations

from html.parser import HTMLParser

# 닫는 태그 없이도 끝나는 요소들 — 스택에 올리면 짝이 맞는 </...>가 영영 오지 않아
# 스택이 오염된다.
_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

EXCLUDED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}
_CONTROL_INPUT_TYPES = {"button", "submit", "image"}
_HIDDEN_TAGS = ("script", "style", "template")
_SIZED_TAGS = {"img", "svg", "canvas", "table", "iframe", "video", "div", "section"}

# 프론트가 iframe에 띄우는 폭(프론트_연동_가이드.md).
PAGE_WIDTH_PX = 1440


class PageParser(HTMLParser):
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


def parse_page(html_content: str) -> PageParser:
    parser = PageParser()
    parser.feed(html_content)
    return parser
