"""HTML 프로토타입(웹개발 · AI_API) 코드 점검 8항목.

기획서 5-4의 초기 배점표는 검증-2 담당이 재구성했다(2026-09-29). 바뀐 이유는
`기획서_개정안_산출물층_검증.md`에 있다. 요약하면:
- 정상 산출물이면 항상 통과하던 진입 파일·비밀값은 점수에서 빼고 통과 필수
  조건(rules/gates.py)으로 옮겼다. lang 속성은 생성 지시로 고정돼 뺐다.
- 그 자리에 "화면이 실제로 동작하는가"를 보는 항목(동작 연결, 스크립트 동작 오류,
  1440px 폭, 임시 문구)을 넣었다.

| No | 항목 | 배점 |
|:-:|---|:-:|
| 1 | 동작 연결 | 3 |
| 2 | img·svg 대체 텍스트 | 2 |
| 3 | input label 연결 | 2 |
| 4 | 명도 대비 4.5:1 | 2 |
| 5 | 제목 계층 | 1 |
| 6 | 1440px 폭 안에 들어옴 | 2 |
| 7 | 스크립트 동작 오류 없음 | 2 |
| 8 | 임시 문구 없음 | 1 |

전부 순수 함수다 — 같은 입력이면 몇 번을 돌려도 같은 결과가 나와야 채점이 재현된다.
HTML 파싱은 표준 라이브러리 html.parser.HTMLParser만 쓴다.
"""

from __future__ import annotations

import re

from verification_agent.rules.color import contrast_ratio, extract_paired_declarations, parse_color
from verification_agent.rules.gates import ignored_apis
from verification_agent.rules.html_parser import (
    EXCLUDED_INPUT_TYPES,
    PAGE_WIDTH_PX,
    PageParser,
    parse_page,
)
from verification_agent.rules.items import item
from verification_agent.rules.wiring import ID_REF_RE, control_label, is_wired, wired_ids

def check_action_wiring(parser: PageParser) -> dict:
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


def _alt_failures(parser: PageParser, prefix: str = "") -> tuple[int, list[str]]:
    failures: list[str] = []
    for rec in parser.img_records:
        if rec.get("alt") is None or rec["alt"].strip() == "":
            failures.append(f"{prefix}img alt 누락 또는 공백")
    for rec in parser.svg_records:
        if not rec.get("has_title") and not (rec.get("aria_label") or "").strip():
            failures.append(f"{prefix}svg title 자식/aria-label 모두 없음")
    return len(parser.img_records) + len(parser.svg_records), failures


def check_alt_text(parser: PageParser, infographic_svg: str | None = None) -> dict:
    """2. img·svg 대체 텍스트. T-B2 인포그래픽도 같이 본다 — 인포그래픽 대체 텍스트
    미충족은 T-B2 재수행으로 이어진다(기능정의서 오류→재수행 매핑)."""
    count, failures = _alt_failures(parser)
    sources = ["prototype"] if failures else []
    if infographic_svg:
        info_count, info_failures = _alt_failures(parse_page(infographic_svg), "[인포그래픽] ")
        count += info_count
        failures += info_failures
        if info_failures:
            sources.append("infographic")
    if not count:
        return item(2, "img·svg 대체 텍스트", 2, True, "이미지 0개", applicable=False)
    evidence = f"검사 대상 {count}건 전부 통과" if not failures else "; ".join(failures)
    return item(2, "img·svg 대체 텍스트", 2, not failures, evidence, defect_sources=sources)


# ── 3. input label ────────────────────────────────────────────


def check_input_label(parser: PageParser) -> dict:
    """3. id-for / aria-label(-by) / label 중첩 중 하나면 된다. input이 없으면 해당 없음."""
    failures: list[str] = []
    checked = 0
    for rec in parser.input_records:
        if rec["type"] in EXCLUDED_INPUT_TYPES:
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

def check_contrast(parser: PageParser) -> dict:
    """4. 명도 대비 4.5:1. 판정 대상(색상 짝) 0개면 해당 없음이 아니라 미통과다 —
    생성 지시(T-B1 규칙 8)가 짝 선언을 요구하므로, 없으면 지시를 어긴 것이다."""
    pairs = extract_paired_declarations("".join(parser.style_chunks))
    if not pairs:
        return item(4, "명도 대비 4.5:1", 2, False,
                    "color/background-color가 함께 명시된 셀렉터 없음(판정 대상 0개)")
    failures: list[str] = []
    for selector, decl in pairs:
        fg, bg = parse_color(decl["color"]), parse_color(decl["background-color"])
        if fg is None or bg is None:
            failures.append(f"{selector}: 색상값 해석 불가({decl['color']} / {decl['background-color']})")
            continue
        ratio = contrast_ratio(fg, bg)
        if ratio < 4.5:
            failures.append(f"{selector}: 대비비 {ratio:.2f} < 4.5")
    evidence = f"검사 대상 {len(pairs)}쌍 전부 통과" if not failures else "; ".join(failures)
    return item(4, "명도 대비 4.5:1", 2, not failures, evidence)


# ── 5. 제목 계층 ──────────────────────────────────────────────


def check_heading_hierarchy(parser: PageParser) -> dict:
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


def check_layout_width(parser: PageParser) -> dict:
    """6. 고정 폭이 1440px을 넘는 선언이 없는지. 넘으면 프론트 iframe에서 가로 스크롤이
    생기고 화면 오른쪽이 잘린다."""
    css = "\n".join(parser.style_chunks + parser.inline_styles)
    wide = [f"{prop}:{value}px" for prop, value in _WIDTH_RE.findall(css)
            if float(value) > PAGE_WIDTH_PX]
    wide += parser.wide_attrs
    evidence = (f"{PAGE_WIDTH_PX}px 초과 고정 폭 없음" if not wide
                else f"{PAGE_WIDTH_PX}px 초과: {', '.join(wide[:3])}")
    return item(6, f"{PAGE_WIDTH_PX}px 폭 안에 들어옴", 2, not wide, evidence)


# ── 7. 스크립트 동작 오류 ─────────────────────────────────────


def check_script_errors(parser: PageParser, html_content: str) -> dict:
    """7. 스크립트가 의도대로 돌지 못하게 하는 원인 두 가지.

    - 끊어진 id 참조: 스크립트가 찾는 id가 문서에 없으면 null에 메서드를 부르다 멈춘다.
    - sandbox에서 무시되는 API: alert() · confirm() · window.open() · 페이지 이동 ·
      form 전송은 iframe(allow-scripts만)에서 조용히 무시되거나 막혀 그 동작만 안 된다.
      스크립트 전체를 멈추는 스토리지 API는 여기가 아니라 통과 필수 조건이다(rules/gates.py).
    id 참조도 무시되는 API도 없으면 해당 없음.
    """
    script = "\n".join(parser.script_chunks)
    refs = {a or b for a, b in ID_REF_RE.findall(script)}
    ignored = ignored_apis(html_content)
    if not refs and not ignored:
        return item(7, "스크립트 동작 오류 없음", 2, True, "스크립트의 id 참조 · 막히는 API 0개",
                    applicable=False)
    broken = sorted(refs - parser.ids)
    problems = []
    if broken:
        problems.append(f"문서에 없는 id {len(broken)}개: {', '.join(broken[:5])}")
    if ignored:
        problems.append(f"sandbox에서 무시되는 API: {', '.join(ignored)}")
    evidence = "; ".join(problems) if problems else f"id 참조 {len(refs)}개 전부 문서에 있음"
    return item(7, "스크립트 동작 오류 없음", 2, not problems, evidence)


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


def check_placeholder_text(parser: PageParser) -> dict:
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
    (6, f"{PAGE_WIDTH_PX}px 폭 안에 들어옴", 2), (7, "스크립트 동작 오류 없음", 2),
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
        check_script_errors(parser, html_content),
        check_placeholder_text(parser),
    ]
