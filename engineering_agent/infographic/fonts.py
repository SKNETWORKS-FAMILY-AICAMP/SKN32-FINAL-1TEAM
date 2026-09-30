"""인포그래픽 SVG에 디자인 글꼴(Pretendard)을 넣는다.

기본 글꼴(맑은 고딕)은 '자동으로 만든 문서' 인상을 준다. 미리 잘라 둔 Pretendard(KS X 1001
한글 2,350자 + 영문 · 숫자 · 자주 쓰는 기호, 모든 굵기)를 SVG 안 <style>에 data URI로 넣는다.
외부 글꼴을 불러오지 않으므로 <img>로 띄워도, 내려받아 열어도 같은 글꼴로 보인다. 글자는
그대로 <text>라 검증-2가 읽는다. 목록에 없는 드문 글자는 기본 글꼴로 대신 그려진다.

실행 때는 파일을 읽어 넣기만 한다(추가 패키지 없음). 글꼴 파일은 한 번 만들어 저장소에 둔다:
assets/pretendard-ksx1001.woff2 — Pretendard Variable 1.3.9에서 잘라 만듦(SIL OFL 1.1,
assets/LICENSE-Pretendard.txt). 파일이 없으면 넣지 않고 기본 글꼴로 둔다.
"""
from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

FONT_FILE = Path(__file__).resolve().parent / "assets" / "pretendard-ksx1001.woff2"
FAMILY = "Pretendard"
FALLBACK = "'Malgun Gothic','Apple SD Gothic Neo',sans-serif"


@lru_cache(maxsize=1)
def _style() -> str:
    try:
        data = FONT_FILE.read_bytes()
    except OSError:
        return ""
    uri = base64.b64encode(data).decode("ascii")
    return (f'<style>@font-face{{font-family:"{FAMILY}";font-weight:45 930;'
            f'src:url(data:font/woff2;base64,{uri}) format("woff2");}}</style>')


def embed(svg: str) -> str:
    """Pretendard를 넣고 지면 기본 글꼴을 바꾼다. 글꼴 파일이 없으면 원본 그대로."""
    style = _style()
    if not style:
        return svg
    svg = re.sub(r"(<svg\b[^>]*>)", lambda m: m.group(1) + style, svg, count=1)
    return re.sub(r"(<svg\b[^>]*?)font-family=\"[^\"]*\"",
                  lambda m: m.group(1) + f"font-family=\"'{FAMILY}',{FALLBACK}\"", svg, count=1)
