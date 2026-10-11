"""인포그래픽 아이콘. 24×24 선 아이콘을 SVG 조각으로 그린다.

아이콘은 글자가 아니라 도형이라 검증-2의 글자 판정(명도 대비 · 계획서에 없는 수치)에
들어가지 않는다. 어떤 아이콘을 쓸지는 기능명 · 수치 단위의 낱말로 정한다 — LLM에
고르게 하지 않아 같은 입력이면 같은 지면이 나온다.
"""
from __future__ import annotations

# 24×24 좌표. stroke만 쓰고 채움이 필요한 점은 dot으로 표시한다.
_ICONS: dict[str, str] = {
    "athlete": ('<circle cx="12" cy="5.5" r="2.5"/><path d="M8 20v-5l-3-3 4-3h6l4 3-3 3v5"/>'
                '<path d="M9 10v6h6v-6M9 16l-2 5M15 16l2 5"/>'),
    "whistle": ('<path d="M4 9h13l4 4-4 1v3H8a4 4 0 0 1-4-4z"/>'
                '<circle cx="9" cy="13" r="2"/><path d="M14 9V5M18 7l2-2M6 7 4 5"/>'),
    "tactics": ('<rect x="3" y="4" width="18" height="16" rx="1"/>'
                '<circle cx="7" cy="9" r="1.5"/><circle cx="17" cy="15" r="1.5"/>'
                '<path d="M9 10l6 4M14 8h4v3M5 15l3 3M8 15l-3 3"/>'),
    "funnel": '<path d="M3 5h18l-7 8v6l-4 2v-8z"/><path d="M3 5c0 2 18 2 18 0"/>',
    "clipboard": ('<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/>'
                  '<path d="M9 12l2 2 4-4M9 17h6"/>'),
    "users": ('<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5"/>'
              '<circle cx="17" cy="9" r="2.5"/><path d="M15.6 14.2c2.6.3 4.4 2.1 4.4 4.8"/>'),
    "alert": '<path d="M12 3.8 21 19.5H3z"/><path d="M12 10v4"/><circle cx="12" cy="16.9" r=".7" class="dot"/>',
    "bulb": ('<path d="M9 17h6M10 20.2h4"/>'
             '<path d="M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3z"/>'),
    "coin": ('<ellipse cx="12" cy="6" rx="7" ry="2.6"/>'
             '<path d="M5 6v5c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6V6"/>'
             '<path d="M5 11v5c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6v-5"/>'),
    "calendar": ('<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'
                 '<path d="M8 14h2M12 14h2M8 17h2"/>'),
    "chart": '<path d="M4 4v16h16"/><path d="M8.5 16v-4M12.5 16V9M16.5 16V6.5"/>',
    "growth": '<path d="M4 17l5-5 4 3 7-7"/><path d="M15 8h5v5"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3.2 2"/>',
    "target": ('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="5"/>'
               '<circle cx="12" cy="12" r="1.4" class="dot"/>'),
    "bell": '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5h4"/>',
    "tool": ('<path d="M14.8 4.2a4.5 4.5 0 0 0-4.1 5.9L4.6 16.2a2 2 0 0 0 2.8 2.8l6.1-6.1'
             'a4.5 4.5 0 0 0 5.9-4.1l-2.7 2.7-2.6-.6-.6-2.6z"/>'),
    "doc": '<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4M9.5 12h6M9.5 15.5h6"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5 20 20"/>',
    "shield": '<path d="M12 3.5 19 6v5.5c0 4.3-3 7.6-7 9-4-1.4-7-4.7-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "phone": '<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/>',
    "mic": '<rect x="9" y="3.5" width="6" height="10" rx="3"/><path d="M6 11a6 6 0 0 0 12 0M12 17v3.5"/>',
    "chat": '<path d="M4 5h16v11H9.5L5 19.5V16H4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    "ai": ('<rect x="7" y="7" width="10" height="10" rx="1.6"/><path d="M10 10.5h4v3h-4z"/>'
           '<path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3"/>'),
    "box": '<path d="M12 3.5 20 7.5v9L12 20.5 4 16.5v-9z"/><path d="M4 7.5l8 4 8-4M12 11.5v9"/>',
    "factory": '<path d="M3.5 20.5V10l5 3v-3l5 3V6h6v14.5z"/><path d="M3 20.5h18M16 10h1M16 14h1"/>',
    "pin": '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    "cart": ('<path d="M3.5 4.5H6l2 10.5h10l2-7.5H7"/><circle cx="10" cy="19.3" r="1.3"/>'
             '<circle cx="17" cy="19.3" r="1.3"/>'),
    "pie": '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5V12h8.5"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "flag": '<path d="M5.5 21V4M5.5 4H17l-2 4 2 4H5.5"/>',
}

# 낱말 → 아이콘. 위에서부터 먼저 맞는 것을 쓴다.
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("athlete", ("선수 평가", "선수 영입")),
    ("search", ("스카우팅",)),
    ("whistle", ("훈련",)),
    ("tactics", ("전술",)),
    ("shield", ("부상", "위험",)),
    ("clipboard", ("리포트",)),
    ("mic", ("음성", "통화", "녹음", "녹취")),
    ("chat", ("상담", "민원", "채팅", "메시지", "문의", "대화")),
    ("ai", ("AI", "인공지능", "자동 분류", "분류", "추천", "변환", "예측", "모델")),
    ("calendar", ("일정", "캘린더", "예약", "날짜", "기한", "스케줄")),
    ("bell", ("알림", "신고", "접수", "경보", "안내")),
    ("tool", ("점검", "수리", "정비", "설비", "부품", "교체", "유지")),
    ("chart", ("매출", "가동률", "통계", "분석", "지표", "리포트", "보고서", "대시보드")),
    ("doc", ("이력", "기록", "문서", "요약", "계약", "서류")),
    ("search", ("검색", "조회", "찾기", "탐색")),
    ("cart", ("주문", "구매", "장바구니")),
    ("coin", ("결제", "요금", "구독", "가격", "수익", "매출", "비용", "원")),
    ("box", ("재고", "상품", "배송", "픽업", "물류")),
    ("pin", ("위치", "지역", "지도", "주변")),
    ("shield", ("보안", "안전", "인증", "보호")),
    ("clock", ("시간", "대기", "분", "초")),
    ("factory", ("공장", "제조", "매장", "가게", "곳")),
    ("users", ("고객", "사용자", "회원", "직원", "담당", "명", "팀")),
    ("phone", ("모바일", "앱", "휴대폰")),
    ("growth", ("성장", "증가", "확대", "목표")),
)

# 수치 단위 → 아이콘 (낱말로 못 정했을 때).
_UNIT_ICONS: tuple[tuple[str, str], ...] = (
    ("%", "pie"), ("원", "coin"), ("분", "clock"), ("시간", "clock"), ("회", "alert"),
    ("건", "doc"), ("곳", "factory"), ("명", "users"), ("개", "box"),
)


def pick(text: str, default: str = "check") -> str:
    """낱말로 아이콘 이름을 고른다."""
    for name, words in _KEYWORDS:
        if any(word in text for word in words):
            return name
    return default


def pick_metric(value: str, label: str) -> str:
    """핵심 수치 아이콘. 단위를 먼저 본다 — 설명 낱말은 사업 분야 낱말(예: 점검)이
    겹쳐 세 카드가 같은 아이콘이 되기 쉽다."""
    for unit, name in _UNIT_ICONS:
        if unit in value:
            return name
    return pick(label, default="target")


def icon(name: str, cx: float, cy: float, size: float, color: str, width: float = 1.8) -> str:
    """(cx, cy)를 중심으로 size 크기의 아이콘."""
    scale = size / 24
    body = _ICONS.get(name, _ICONS["check"]).replace(
        'class="dot"', f'fill="{color}" stroke="none"')
    return (f'<g transform="translate({cx - size / 2:.1f},{cy - size / 2:.1f}) scale({scale:.3f})" '
            f'fill="none" stroke="{color}" stroke-width="{width / scale:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</g>')


def badge(name: str, cx: float, cy: float, r: float, fill: str, color: str) -> str:
    """옅은 원 배경 위 아이콘."""
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"/>'
            + icon(name, cx, cy, r * 1.1, color))
