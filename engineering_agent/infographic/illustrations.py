"""인포그래픽 머리말의 대표 일러스트. 사람이 그린 CC0 일러스트를 사업 낱말로 골라 넣는다.

일러스트는 assets/illustrations/<장면>.svg (Lukasz Adam, CC0 — assets/illustrations/LICENSE.txt).
SVG를 data URI <image>로 넣어 안쪽 도형이 지면 글자 판정(명도 대비 등)에 섞이지 않게 한다.
일러스트에는 글자가 없다. 검증-2 원페이지 7번은 <image> 면적을 지면의 10% 이하로 보므로
머리말 한 자리에만 작게 쓴다. 파일이 없으면 넣지 않는다.
"""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "assets" / "illustrations"

# 위에서부터 먼저 맞는 장면을 쓴다. 사업을 가장 잘 보여주는 낱말을 앞에 둔다.
SCENES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ai", ("AI", "인공지능", "머신러닝", "데이터 분석", "요약", "분류")),
    ("conversation", ("상담", "민원", "고객 응대", "채팅", "문의", "콜센터")),
    ("maintenance", ("점검", "설비", "정비", "수리", "유지보수", "부품")),
    ("workers", ("공장", "제조", "생산", "현장 작업")),
    ("cook", ("요리", "식당", "레스토랑", "밀키트", "도시락", "주방")),
    ("store", ("가게", "매장", "상점", "반찬", "카페", "베이커리", "점포", "상권", "소상공인")),
    ("delivery", ("배달", "퀵", "라이더")),
    ("package", ("배송", "물류", "재고", "택배", "포장", "유통")),
    ("robot", ("자동화", "로봇", "스마트팩토리")),
    ("video", ("원격", "화상", "온라인 수업", "비대면")),
    ("presentation", ("교육", "학습", "강의", "학생", "코칭")),
    ("city", ("지역", "지자체", "도시", "공공", "행정", "관광")),
    ("mobile", ("앱", "모바일", "예약", "알림")),
    ("sales", ("판매", "매출", "마케팅", "홍보", "광고")),
    ("monitor", ("플랫폼", "대시보드", "관리", "웹서비스")),
    ("dev", ("개발", "소프트웨어", "SaaS", "API")),
)
DEFAULT = "growth"


def pick(category: str, data: dict) -> str:
    text = " ".join([str(data.get("item_name", "")), str(data.get("item_summary", "")),
                     str(data.get("target_users", ""))] + [str(f) for f in data.get("features") or []])
    for key, words in SCENES:
        if any(word in text for word in words):
            return key
    return "ai" if category == "AI_API" else DEFAULT


@lru_cache(maxsize=32)
def _uri(key: str) -> str:
    try:
        raw = (DIR / f"{key}.svg").read_bytes()
    except OSError:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


def image(key: str, x: float, y: float, w: float, h: float) -> str:
    """일러스트 <image>. 파일이 없으면 빈 문자열."""
    uri = _uri(key) or _uri(DEFAULT)
    if not uri:
        return ""
    return (f'<image x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'preserveAspectRatio="xMidYMid meet" href="{uri}"/>')
