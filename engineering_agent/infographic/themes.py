"""인포그래픽 색 테마. 사업 분야 낱말로 테마를 골라 지면 색을 바꾼다.

본문 builder(onepage.py · bodies.py)는 기본 테마(teal) 색으로 그리고, 저장 직전에
apply()가 기본 색을 고른 테마 색으로 바꾼다. 테마는 아이템명 · 한 줄 소개 · 목표 고객 ·
기능명의 낱말로 정한다. 사업 분야 낱말이 없으면(기술 낱말만 맞거나 아무것도 안 맞으면)
decide()가 LLM에게 분야를 묻는다 — 여행 · 부동산 · 모빌리티 같은 분야가 AI 낱말에 걸려 보라로,
또는 이름 해시로 엉뚱한 색이 되던 것을 막는다. LLM 호출이 안 되면 낱말 · 이름 규칙으로 돌아간다.

모든 테마의 글자색은 흰 패널 · 옅은 배경 위에서 명도 대비 4.5:1 이상이어야 한다
(검증-2 원페이지 3번). tests가 테마마다 확인한다.
"""
from __future__ import annotations

import json
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


def _keyword_theme(data: dict) -> str | None:
    text = " ".join([str(data.get("item_name", "")), str(data.get("item_summary", "")),
                     str(data.get("target_users", ""))]
                    + [str(f) for f in data.get("features") or []])
    for name, words in _KEYWORDS:
        if any(word in text for word in words):
            return name
    return None


def _name_theme(data: dict) -> str:
    names = sorted(THEMES)
    return names[zlib.crc32(str(data.get("item_name", "")).encode("utf-8")) % len(names)]


def pick(data: dict) -> str:
    """이 지면의 테마. decide()가 정해 data['_theme']에 넣어 두었으면 그것을 쓴다(한 지면 안의 색 · 그림 ·
    구역 틀이 같은 테마를 보게). 없으면 낱말 → 이름 규칙."""
    chosen = data.get("_theme")
    if chosen in THEMES:
        return chosen
    return _keyword_theme(data) or _name_theme(data)


# LLM에게 물을 때의 분야 → 테마. 시험(아이템 9개 × 5번): 8개는 5번 모두 같은 답, 애매한 1개(체형 맞춤 의류)만 4:1.
_DOMAINS: dict[str, tuple[str, str]] = {
    "food": ("orange", "음식 · 외식 · 식품 · 배달"),
    "industry": ("steel", "제조 · 공장 · 설비 · 물류 · 건설 · 모빌리티"),
    "outdoor": ("green", "농업 · 환경 · 에너지 · 여행 · 관광 · 야외"),
    "care": ("rose", "건강 · 의료 · 뷰티 · 반려동물 · 육아 · 패션"),
    "public": ("blue", "교육 · 행정 · 공공 · 금융 · 보험 · 법률 · 부동산"),
    "commerce": ("teal", "유통 · 판매 · 매장 · 커머스 · 스포츠"),
    "tech": ("violet", "AI · 데이터 · 소프트웨어 · 게임 · 콘텐츠 · 미디어(분야가 기술 그 자체일 때만)"),
}
_DOMAIN_SYSTEM = ("사업 아이템의 분야를 아래 목록에서 하나만 고른다. 기술(AI · 데이터)을 쓰더라도 그 기술이 쓰이는 "
                  "사업 분야를 고른다.\n"
                  + "\n".join(f"- {key}: {desc}" for key, (_, desc) in _DOMAINS.items())
                  + '\n답은 JSON 객체 하나만: {"domain": "목록의 키"}')


def _parse_domain(text) -> str:
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    try:
        domain = json.loads(raw[start:end + 1]).get("domain") if 0 <= start < end else None
    except (ValueError, AttributeError):
        domain = None
    if domain not in _DOMAINS:
        # tools가 다시 부르게 형식 오류로 올린다(조율 FormatError가 있으면 그것, 없으면 ValueError).
        try:
            from sbrain.orchestrator.errors import FormatError
        except ImportError:
            raise ValueError("분야 판정 응답이 목록의 키가 아님") from None
        raise FormatError("분야 판정 응답이 목록의 키가 아님")
    return domain


def decide(data: dict, tools=None) -> str:
    """사업 분야 낱말이 맞으면 그 테마. 기술 낱말만 맞거나 아무것도 안 맞으면 LLM에게 분야를 묻는다.

    T-B1(HTML)과 T-B2(인포그래픽)가 각자 부른다. 질문에는 아이템명 · 한 줄 소개만 넣는다. 애매한 아이템은 두 답이
    갈려 HTML과 인포그래픽 색이 다를 수 있는데, 둘이 같을 필요는 없다(담당자, 2026-10-12).
    색은 꾸밈이라 호출이 실패하면 예외를 내지 않고 낱말 · 이름 규칙으로 돌아간다."""
    found = _keyword_theme(data)
    if found and found != "violet":
        return found
    if tools is not None and callable(getattr(tools, "llm", None)):
        item = f"아이템: {data.get('item_name', '')}\n한 줄 소개: {data.get('item_summary', '')}"
        try:
            domain = tools.llm([{"role": "system", "content": _DOMAIN_SYSTEM},
                                {"role": "user", "content": item}],
                               parse=_parse_domain, purpose="사업 분야 판정(색)")
            return _DOMAINS[domain][0]
        except Exception:  # noqa: BLE001 — 색 때문에 Task를 멈추지 않는다
            pass
    return found or _name_theme(data)


def apply(svg: str, theme: str) -> str:
    """기본 테마 색을 theme 색으로 바꾼다."""
    if theme == BASE or theme not in THEMES:
        return svg
    base, target = THEMES[BASE], THEMES[theme]
    for role in _ROLES:
        svg = svg.replace(base[role], target[role])
    return svg
