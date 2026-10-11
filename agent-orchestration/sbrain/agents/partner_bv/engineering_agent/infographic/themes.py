"""인포그래픽 색 테마. 사업 분야 낱말로 테마를 골라 지면 색을 바꾼다.

본문 builder(onepage.py · bodies.py)는 기본 테마(teal) 색으로 그리고, 저장 직전에
apply()가 기본 색을 고른 테마 색으로 바꾼다. 테마는 아이템명 · 한 줄 소개 · 목표 고객 ·
기능명의 낱말로 정하고, 맞는 낱말이 없으면 아이템명으로 정한다 — 같은 아이템은 다시
만들어도 같은 색이 나온다.

모든 테마의 글자색은 흰 패널 · 옅은 배경 위에서 명도 대비 4.5:1 이상이어야 한다
(검증-2 원페이지 3번). tests가 테마마다 확인한다.
"""
from __future__ import annotations

import zlib

# 바꿀 자리. 값은 기본 테마(teal)의 색이며 onepage.C · 템플릿 배경과 같아야 한다.
_ROLES = ("ink", "body", "muted", "accent", "accent_deep", "tint", "line", "bg")

THEMES: dict[str, dict[str, str]] = {
    "teal": {"ink": "#10302C", "body": "#1F3B37", "muted": "#46615C", "accent": "#0F766E",
             "accent_deep": "#115E59", "tint": "#E3F2EF", "line": "#D5E5E1", "bg": "#F3F7F6"},
    "orange": {"ink": "#3A1F10", "body": "#40291B", "muted": "#6B4A36", "accent": "#C2410C",
               "accent_deep": "#9A3412", "tint": "#FCEBDD", "line": "#F0DCCB", "bg": "#FBF6F1"},
    "steel": {"ink": "#0B2233", "body": "#1B3345", "muted": "#475B6B", "accent": "#0369A1",
              "accent_deep": "#075985", "tint": "#E0F0F8", "line": "#D2E2EC", "bg": "#F2F7FA"},
    "violet": {"ink": "#24133F", "body": "#2E2147", "muted": "#584C6E", "accent": "#6D28D9",
               "accent_deep": "#5B21B6", "tint": "#EEE7FB", "line": "#E1D9F2", "bg": "#F6F4FB"},
    "green": {"ink": "#102A19", "body": "#1D3526", "muted": "#48604F", "accent": "#15803D",
              "accent_deep": "#166534", "tint": "#E3F4E8", "line": "#D3E7D9", "bg": "#F3F8F4"},
    "rose": {"ink": "#3A1024", "body": "#42202F", "muted": "#6B4757", "accent": "#BE185D",
             "accent_deep": "#9D174D", "tint": "#FBE4EE", "line": "#F0D5E1", "bg": "#FBF4F7"},
    "blue": {"ink": "#0F1E3D", "body": "#1E2B45", "muted": "#4A5670", "accent": "#1D4ED8",
             "accent_deep": "#1E40AF", "tint": "#E4ECFB", "line": "#D6E0F3", "bg": "#F3F6FB"},
}
BASE = "teal"

# 위에서부터 먼저 맞는 테마를 쓴다. 사업 분야 낱말이 기술 낱말(AI · 데이터 · 자동화)보다 먼저다 —
# 기술 낱말을 앞에 두었더니 지원사업 계획서 대부분이 AI를 쓰므로 제조 · 반려동물 · 유통 계획서가
# 전부 보라 한 색으로 나왔다(실측: 예시 계획서 3개 모두 보라).
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("teal", ("스포츠", "선수", "구단", "전술", "스카우팅")),
    ("orange", ("반찬", "음식", "식당", "카페", "베이커리", "빵", "푸드", "요리", "밀키트", "식품",
                "배달", "도시락", "외식")),
    ("steel", ("제조", "공장", "설비", "부품", "산업", "기계", "공정", "물류")),
    ("green", ("농업", "농가", "스마트팜", "친환경", "재활용", "에너지", "탄소", "환경", "원예")),
    ("rose", ("건강", "의료", "병원", "헬스", "뷰티", "화장품", "돌봄", "반려", "펫", "육아")),
    # '학습'은 넣지 않는다 — 계획서에서는 대개 모델 학습(머신러닝) 뜻이다.
    ("blue", ("교육", "학생", "수업", "강의", "학원", "행정", "민원", "금융", "공공", "보험", "법률")),
    ("teal", ("재고", "발주", "유통", "매장", "판매", "커머스", "쇼핑", "POS", "도소매")),
    ("violet", ("AI", "인공지능", "데이터", "챗봇", "자동화", "머신러닝", "알고리즘")),
)


def pick(data: dict) -> str:
    text = " ".join([str(data.get("item_name", "")), str(data.get("item_summary", "")),
                     str(data.get("target_users", ""))]
                    + [str(f) for f in data.get("features") or []])
    for name, words in _KEYWORDS:
        if any(word in text for word in words):
            return name
    names = sorted(THEMES)
    return names[zlib.crc32(str(data.get("item_name", "")).encode("utf-8")) % len(names)]


def apply(svg: str, theme: str) -> str:
    """기본 테마 색을 theme 색으로 바꾼다."""
    if theme == BASE or theme not in THEMES:
        return svg
    base, target = THEMES[BASE], THEMES[theme]
    for role in _ROLES:
        svg = svg.replace(base[role], target[role])
    return svg
