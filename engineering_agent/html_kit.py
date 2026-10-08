"""T-B1 HTML의 기본 디자인 CSS. 사업 팔레트(infographic.themes)로 색을 채운다.

말로만 디자인을 지시했더니 글꼴 · 간격 · 버튼 · 카드가 매번 평범한 기본 모양이었고, 색도 모델이 새로 만들다가
명도 대비를 어기곤 했다. 검증된 CSS를 주고 "이걸 그대로 쓰고 필요한 것만 더해라"로 지시한다(인포그래픽에서 배치를
코드가 맡은 것과 같은 방식).

검증-2 코드 점검 기준을 미리 지킨다.
- 4번 명도 대비: 글자가 놓이는 셀렉터마다 color와 background-color를 같은 블록에 실제 값으로 적는다(CSS 변수 · background
  단축 속성 금지, T-B1 규칙 8). 모든 짝이 4.5:1 이상이다 — tests/test_builder_html_plan.py가 색 테마마다 확인한다.
- 6번 폭: width · min-width는 1440px을 넘지 않는다(max-width만 쓴다).
- 외부 글꼴 · 이미지를 부르지 않는다(E-B1-DEP).
"""
from __future__ import annotations

import base64
import re
from functools import lru_cache

from engineering_agent.infographic import fonts, icons

DANGER, DANGER_TINT, DANGER_INK = "#B91C1C", "#FEE2E2", "#991B1B"

# 모델에게 알려 줄 아이콘(이름 → 뜻). 인포그래픽 기본 아이콘(infographic/icons.py)을 그대로 쓴다.
ICON_NAMES = {
    "users": "사용자 · 고객", "cart": "주문 · 장바구니", "box": "재고 · 상품", "factory": "공장 · 매장",
    "doc": "문서 · 발주서", "clipboard": "점검표 · 목록", "chart": "통계 · 그래프", "growth": "성장 · 증가",
    "pie": "비율", "coin": "결제 · 금액", "calendar": "일정 · 예약", "clock": "시간 · 대기",
    "bell": "알림", "alert": "경고 · 위험", "check": "완료 · 확인", "target": "목표", "search": "검색 · 분석",
    "ai": "AI 처리", "chat": "상담 · 메시지", "phone": "전화 · 모바일", "mic": "음성", "shield": "보안 · 안전",
    "tool": "설정 · 정비", "pin": "위치", "flag": "단계 · 시작", "bulb": "아이디어 · 해결", "funnel": "필터",
}
_KIT_FONT_RE = re.compile(r'<style data-kit="font">.*?</style>', re.S)
_KIT_ICONS_RE = re.compile(r'<svg data-kit="icons".*?</svg>', re.S)
_USE_SVG_RE = re.compile(r'<svg\b(?P<attrs>[^>]*)>(?P<inner>\s*<use\b[^>]*href="#i-(?P<name>[\w-]+)"[^>]*/?>)')
WARN_TINT, WARN_INK = "#FEF3C7", "#92400E"

# 화면 틀 클래스. 프롬프트의 '화면 틀' 지시와 짝이다.
FRAMES = {
    "frame-app": ("일반 이용자 서비스(앱) — 바깥 `app-layout` 안에 왼쪽은 폭 480px 앱 화면(`frame-app`: 위에서 아래로 단계, "
                  "아래 탭), 오른쪽은 `app-side` 패널(지금 단계에서 일어나는 일, 결과 상세, 이 화면이 보여 주는 계획서 기능). "
                  "데스크톱 폭을 비워 두지 않는다"),
    "frame-board": "매장 · 현장 담당자 업무 — 위 메뉴 + 처리할 일 목록(카드 · 표)과 상태 변경",
    "frame-admin": "데이터 · 거래처 관리 — 왼쪽 메뉴 + 표 · 그래프 중심 본문",
    "frame-compare": "비교 · 선택 — 후보를 나란히 놓는 비교 격자",
}


def base_css(p: dict[str, str]) -> str:
    """p: themes.THEMES의 색(ink · body · muted · accent · accent_deep · tint · line · bg)."""
    ink, body, muted, accent, deep, tint, line, bg = (
        p["ink"], p["body"], p["muted"], p["accent"], p["accent_deep"], p["tint"], p["line"], p["bg"])
    return f"""/* ── 기본 디자인 (그대로 두고 아래에 필요한 것만 더한다) ── */
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: {ink}; background-color: {bg}; font-family: "Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; font-size: 15px; line-height: 1.6; }}
h1 {{ margin: 0 0 6px; font-size: 26px; font-weight: 800; letter-spacing: -0.4px; }}
h2 {{ margin: 0 0 12px; font-size: 20px; font-weight: 700; }}
h3 {{ margin: 0 0 8px; font-size: 16px; font-weight: 700; }}
p {{ margin: 0 0 10px; }}
.muted {{ color: {muted}; background-color: {bg}; font-size: 14px; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
.card {{ color: {ink}; background-color: #FFFFFF; border: 1px solid {line}; border-radius: 14px; padding: 20px; margin-bottom: 16px; }}
.card .muted {{ color: {muted}; background-color: #FFFFFF; }}
.row {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.btn {{ color: #FFFFFF; background-color: {accent}; border: 0; border-radius: 10px; padding: 11px 18px; font: inherit; font-weight: 700; cursor: pointer; }}
.btn:hover {{ color: #FFFFFF; background-color: {deep}; }}
.btn-secondary {{ color: {deep}; background-color: {tint}; border: 0; border-radius: 10px; padding: 11px 18px; font: inherit; font-weight: 700; cursor: pointer; }}
.btn-ghost {{ color: {deep}; background-color: #FFFFFF; border: 1px solid {line}; border-radius: 10px; padding: 10px 16px; font: inherit; cursor: pointer; }}
.btn-danger {{ color: #FFFFFF; background-color: {DANGER}; border: 0; border-radius: 10px; padding: 11px 18px; font: inherit; font-weight: 700; cursor: pointer; }}
button:disabled {{ color: {muted}; background-color: {tint}; cursor: not-allowed; }}
label {{ display: block; margin: 12px 0 6px; font-weight: 700; font-size: 14px; }}
input, select, textarea {{ width: 100%; color: {ink}; background-color: #FFFFFF; border: 1px solid {line}; border-radius: 10px; padding: 10px 12px; font: inherit; }}
.field-error {{ margin-top: 6px; color: {DANGER}; background-color: #FFFFFF; font-size: 13px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ color: {ink}; background-color: {tint}; text-align: left; padding: 10px 12px; font-size: 14px; }}
td {{ color: {body}; background-color: #FFFFFF; padding: 10px 12px; border-bottom: 1px solid {line}; }}
.badge {{ display: inline-block; color: {deep}; background-color: {tint}; border-radius: 999px; padding: 3px 10px; font-size: 13px; font-weight: 700; }}
.badge-warn {{ display: inline-block; color: {WARN_INK}; background-color: {WARN_TINT}; border-radius: 999px; padding: 3px 10px; font-size: 13px; font-weight: 700; }}
.badge-danger {{ display: inline-block; color: {DANGER_INK}; background-color: {DANGER_TINT}; border-radius: 999px; padding: 3px 10px; font-size: 13px; font-weight: 700; }}
.demo-tag {{ display: inline-block; color: {deep}; background-color: {tint}; border-radius: 6px; padding: 2px 8px; font-size: 12px; }}
.steps {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.step {{ flex: 1; color: {muted}; background-color: #FFFFFF; border: 1px solid {line}; border-radius: 999px; padding: 8px 10px; text-align: center; font-size: 13px; font-weight: 700; }}
.step.active {{ color: #FFFFFF; background-color: {accent}; border-color: {accent}; }}
.step.done {{ color: {deep}; background-color: {tint}; border-color: {tint}; }}
.loading {{ color: {deep}; background-color: {tint}; border-radius: 10px; padding: 12px 14px; font-weight: 700; }}
.spinner {{ display: inline-block; width: 16px; height: 16px; margin-right: 8px; border: 3px solid {line}; border-top-color: {accent}; border-radius: 50%; vertical-align: -3px; animation: spin .8s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.empty {{ color: {muted}; background-color: {tint}; border-radius: 12px; padding: 24px; text-align: center; }}
.result {{ color: {ink}; background-color: {tint}; border-radius: 12px; padding: 16px; }}
.toast {{ position: fixed; right: 24px; bottom: 24px; max-width: 360px; color: #FFFFFF; background-color: {deep}; border-radius: 12px; padding: 14px 18px; font-weight: 700; box-shadow: 0 6px 20px rgba(0, 0, 0, .18); }}
.toast.error {{ color: #FFFFFF; background-color: {DANGER}; }}
.hidden {{ display: none; }}
/* 화면 틀 — 하나만 고른다 */
.app-layout {{ display: grid; grid-template-columns: 480px 1fr; gap: 24px; align-items: start; max-width: 1200px; margin: 24px auto; padding: 0 24px; }}
.frame-app {{ max-width: 480px; margin: 0; color: {ink}; background-color: #FFFFFF; border: 8px solid {ink}; border-radius: 32px; padding: 20px; box-shadow: 0 10px 30px rgba(0, 0, 0, .12); }}
.app-side {{ position: sticky; top: 24px; color: {ink}; background-color: #FFFFFF; border: 1px solid {line}; border-radius: 14px; padding: 20px; }}
.app-side h2 {{ font-size: 18px; }}
.app-side .muted {{ color: {muted}; background-color: #FFFFFF; }}
.app-tabs {{ display: flex; gap: 6px; margin-top: 16px; border-top: 1px solid {line}; padding-top: 10px; }}
.app-tabs button {{ flex: 1; color: {muted}; background-color: #FFFFFF; border: 0; padding: 10px 4px; font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; }}
.app-tabs button.active {{ color: {deep}; background-color: {tint}; border-radius: 10px; }}
.topbar {{ color: {ink}; background-color: #FFFFFF; border-bottom: 1px solid {line}; padding: 14px 24px; }}
.topbar nav {{ display: flex; gap: 6px; }}
.topbar nav button {{ color: {body}; background-color: #FFFFFF; border: 0; border-radius: 8px; padding: 8px 14px; font: inherit; font-weight: 700; cursor: pointer; }}
.topbar nav button.active {{ color: {deep}; background-color: {tint}; }}
.frame-admin {{ display: grid; grid-template-columns: 240px 1fr; max-width: 1280px; margin: 0 auto; min-height: 100vh; }}
.sidenav {{ color: {ink}; background-color: #FFFFFF; border-right: 1px solid {line}; padding: 20px 14px; }}
.sidenav button {{ display: block; width: 100%; text-align: left; color: {body}; background-color: #FFFFFF; border: 0; border-radius: 10px; padding: 10px 12px; margin-bottom: 4px; font: inherit; font-weight: 700; cursor: pointer; }}
.sidenav button.active {{ color: {deep}; background-color: {tint}; }}
.frame-admin main {{ padding: 24px; }}
.compare-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
.compare-grid .card.picked {{ color: {ink}; background-color: {tint}; border-color: {accent}; }}
.icon {{ width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; vertical-align: -4px; }}
.icon-lg {{ width: 32px; height: 32px; }}
"""


# ── 생성 뒤 코드가 끼워 넣는 것(글꼴 · 아이콘). 모델이 옮겨 쓸 수 없는 데이터라 코드가 넣는다 ──


@lru_cache(maxsize=1)
def font_style() -> str:
    """인포그래픽과 같은 Pretendard(KS X 1001 부분, 약 430KB)를 data URI로. 파일이 없으면 빈 문자열."""
    try:
        data = fonts.FONT_FILE.read_bytes()
    except OSError:
        return ""
    uri = base64.b64encode(data).decode("ascii")
    return (f'<style data-kit="font">@font-face{{font-family:"{fonts.FAMILY}";font-weight:45 930;'
            f'src:url(data:font/woff2;base64,{uri}) format("woff2");}}</style>')


@lru_cache(maxsize=1)
def icon_sprite() -> str:
    """숨긴 아이콘 묶음. 쓰는 쪽은 <svg class="icon" aria-label="뜻"><use href="#i-이름"/></svg>."""
    symbols = "".join(
        f'<symbol id="i-{name}" viewBox="0 0 24 24">'
        + icons._ICONS[name].replace('class="dot"', 'fill="currentColor" stroke="none"') + "</symbol>"
        for name in ICON_NAMES if name in icons._ICONS)
    return (f'<svg data-kit="icons" aria-label="아이콘 모음" xmlns="http://www.w3.org/2000/svg" '
            f'style="display:none">{symbols}</svg>')


def _label_icons(html: str) -> str:
    """대체 텍스트가 없는 아이콘 svg에 아이콘 뜻을 aria-label로 붙인다(검증-2 2번: 모든 svg에 title 또는 aria-label)."""
    def fix(m: re.Match) -> str:
        attrs = m.group("attrs")
        if "aria-label" in attrs or "<title" in m.group("inner"):
            return m.group(0)
        label = ICON_NAMES.get(m.group("name"), "아이콘").split(" · ")[0]
        return f'<svg{attrs} aria-label="{label}">{m.group("inner")}'
    return _USE_SVG_RE.sub(fix, html)


def decorate(html: str) -> str:
    """자체 검사를 통과한 HTML에 글꼴 · 아이콘 묶음을 넣는다. 이미 들어 있으면 다시 넣지 않는다."""
    html = strip(html)
    font = font_style()
    if font:
        html = re.sub(r"</head>", font + "</head>", html, count=1, flags=re.I) if re.search(r"</head>", html, re.I) \
            else html
    html = re.sub(r"(<body\b[^>]*>)", lambda m: m.group(1) + icon_sprite(), html, count=1, flags=re.I)
    return _label_icons(html)


def strip(html: str) -> str:
    """끼워 넣은 글꼴 · 아이콘 묶음을 뺀다. 재실행 때 이전 HTML을 프롬프트에 실을 때 쓴다(글꼴만 약 580KB)."""
    return _KIT_ICONS_RE.sub("", _KIT_FONT_RE.sub("", html))
