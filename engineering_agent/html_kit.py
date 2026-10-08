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

DANGER, DANGER_TINT, DANGER_INK = "#B91C1C", "#FEE2E2", "#991B1B"
WARN_TINT, WARN_INK = "#FEF3C7", "#92400E"

# 화면 틀 클래스. 프롬프트의 '화면 틀' 지시와 짝이다.
FRAMES = {
    "frame-app": "일반 이용자 서비스 — 가운데 폭 480px 앱 화면, 위에서 아래로 단계, 아래 탭",
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
.frame-app {{ max-width: 480px; margin: 24px auto; color: {ink}; background-color: #FFFFFF; border-radius: 24px; padding: 20px; box-shadow: 0 10px 30px rgba(0, 0, 0, .08); }}
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
"""
