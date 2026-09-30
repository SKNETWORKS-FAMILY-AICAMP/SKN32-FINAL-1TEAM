"""인포그래픽 세 템플릿이 공유하는 색과 카테고리 표기."""
from __future__ import annotations


# 3개 템플릿이 공유하는 브랜드 컬러 팔레트.
# 값 하나 바꾸면 3개 카테고리 전부에 일관되게 반영되도록 상수로만 정의한다.
BRAND_COLORS = {
    "bg": "#F8FAFC",
    "surface": "#FFFFFF",
    "primary": "#2563EB",
    "secondary": "#10B981",
    "accent": "#F59E0B",
    "text": "#0F172A",
    "text_muted": "#64748B",
    "border": "#E2E8F0",
}

# 카테고리별 강조색 — 배지·플로우 박스 테두리 등 카테고리를 한눈에 구분하는 용도.
CATEGORY_ACCENT = {
    "원페이지": "#1D4ED8",
    "웹개발": "#7C3AED",
    "AI_API": "#0F766E",
}

CATEGORY_LABEL = {
    "원페이지": "원페이지",
    "웹개발": "웹개발",
    "AI_API": "AI API",
}

CATEGORY_TEMPLATE_FILE = {
    "원페이지": "onepage_template.svg",
    "웹개발": "webdev_template.svg",
    "AI_API": "ai_api_template.svg",
}
