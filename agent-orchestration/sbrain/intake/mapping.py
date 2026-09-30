"""웹 DB 행 → PreInput (시트 4 PreInput, 시트 6 E-C1-REQUIRED).

- 값을 옮기기만 한다. 요약 · 보완 · 추정하지 않는다 (4-6: 수익모델 단가 · 경력은 사용자 입력만 쓴다).
- 필수 항목이 비어 있으면 MissingRequired를 올린다. 호출한 쪽은 E-C1-REQUIRED로 안내하고
  T-C1을 실행하지 않는다. 폼 제출 단계(웹)의 검사를 다시 한 번 확인하는 자리다.
- DB 구조와 PreInput 필드가 1:1이 아닌 곳의 변환 규칙은 기준 문서에 없어 잠정이다.
  목록은 docs/T-C1_요구사항해석_구현.md 4절에 있다.
- PreInput에 자리가 없는 웹 입력값은 확장 필드(FormExtension)로 그대로 싣는다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..models import PreInput, RevenueItem
from ..models.base import ApplicantType
from .record import PlanInputRow, PricingItemRow, ProjectInputRecord, TeamMemberRow

# 웹 폼의 신청자 유형 코드 → 시트 4 표기
APPLICANT_TYPE: dict[str, ApplicantType] = {
    "preliminary": "예비창업자",
    "individual": "개인사업자",
    "corp": "법인",
}

# E-C1-REQUIRED 안내에 쓰는 이름 (시트 4 PreInput 설명의 한글 이름)
LABELS: dict[str, str] = {
    "idea_text": "아이디어 설명",
    "applicant_type": "신청자 유형",
    "representative_name": "대표자 이름",
    "representative_career": "대표자 이력",
    "founded_at": "설립일자",
    "revenue_unit_price": "수익모델 단가",
    "development_period": "개발 기간",
    "team_careers": "팀 구성원",
    "birth_date": "대표자 생년월일",
    "gender": "성별",
    "region": "희망 지역",
    "industry_code": "주 업종",
    "hiring_plan": "채용 계획",
    "facilities": "장비 · 시설",
    "partners": "협력 파트너 · 기관",
    "desired_scale": "희망 사업 규모",
    "self_fund_amount": "자기부담금",
}

NONE_TEXT = "없음"  # '해당 없음'을 고른 항목 (시트 4 hiringPlan · facilities · partners)


class MissingRequired(Exception):
    """필수 항목 결측 (E-C1-REQUIRED)."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        self.labels = [LABELS[f] for f in fields]
        super().__init__(", ".join(self.labels))


def to_pre_input(record: ProjectInputRecord) -> PreInput:
    company, project, plan = record.company, record.project, record.plan_input or PlanInputRow()
    applicant = APPLICANT_TYPE.get(company.applicant_type or "")
    business = applicant in ("개인사업자", "법인")
    revenue = _revenue_items(record.pricing_items)
    values: dict[str, Any] = {
        "idea_text": _text(record.project.description),
        "applicant_type": applicant,
        "representative_name": _text(company.ceo_name),
        "representative_career": _describe_all(plan.ceo_careers),
        # 기준 문서는 단가 1개(int) — 호환용으로 첫 항목 단가, 전체는 확장 필드 revenue_items
        "revenue_unit_price": revenue[0].unit_price if revenue else None,
        "development_period": _period(plan.dev_start_month, plan.dev_end_month),
        # 팀원 없음은 team_members 0행 → 빈 목록. 웹이 '팀원 입력 또는 팀원 없음 선택'을 강제한다 (웹팀 확인)
        "team_careers": [s for s in (_member(m) for m in record.team_members) if s],
        "birth_date": plan.ceo_birth_date,
        "gender": _text(plan.ceo_gender),
        "region": _join(plan.region_sido, plan.region_sigungu) if _text(plan.region_sido) else None,
        "industry_code": _text(plan.main_industry) or _text(plan.main_industry_free),
        "certifications": _describe_all(plan.certifications) if plan.certifications is not None else None,
        "hiring_plan": _none_or_list(plan.no_hires, plan.hires),
        "facilities": _none_or_list(plan.no_equipment, plan.equipment),
        "partners": _none_or_list(plan.no_partners, plan.partners),
        # 유형별 항목 — 예비창업자는 설립일자 · 사업자 항목이 없다 (시트 4 foundedAt · businessRegNo)
        "founded_at": company.founded_at if business else None,
        "business_reg_no": _text(company.business_reg_no) if business else None,
        "self_fund_amount": _self_fund(plan) if business else None,
        # 희망 사업 규모 — budget_scale_manwon은 만원 단위 (웹팀 확인)
        "desired_scale": f"{plan.budget_scale_manwon}만원" if not business and plan.budget_scale_manwon is not None else None,
        # 첫 창업 여부 — 받지 않는다 (웹팀 확인 2026-09-30, 기준 문서 개정 대상)
        "is_first_startup": None,
        # 확장 — PreInput에 자리가 없는 웹 입력값
        "revenue_items": revenue or [],
        "company_name": _text(company.company_name),
        "biz_type": _text(company.biz_type),
        "representative_type": _text(company.rep_type),
        "output_summary": _text(project.output_summary),
        "tech_field": _text(project.tech_field),
        "regional_priority_area": _text(project.regional_priority_area),
        "occupation": _text(plan.occupation),
        "representative_capability": _text(plan.ceo_capability),
        "self_in_kind_resources": _text(plan.self_in_kind_resources),
    }
    # 팀 구성원은 '팀원 없음'을 고를 수 있어 필수에서 뺀다 (사용자 결정 · 웹팀 확인 2026-09-30)
    required = [
        "idea_text", "applicant_type", "representative_name", "representative_career", "revenue_unit_price",
        "development_period", "birth_date", "gender", "region", "industry_code",
        "hiring_plan", "facilities", "partners",
    ]
    if business:
        required += ["founded_at", "self_fund_amount"]
    elif applicant == "예비창업자":
        required += ["desired_scale"]
    missing = [f for f in required if values[f] in (None, "", [])]
    if missing:
        raise MissingRequired(missing)
    return PreInput(**values)


# ── 변환 규칙 (잠정) ──────────────────────────────────
def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _join(*parts: Any, sep: str = " ") -> str:
    return sep.join(s for s in (_text(p) for p in parts) if s)


def _describe(item: Any) -> str | None:
    """JSON 목록의 항목 하나를 한 줄로 — 키 이름을 모르므로 값만 순서대로 잇는다 (잠정).

    참 · 거짓 값(대표자 이력의 증빙여부 등)은 이름 없이 옮기면 뜻이 없어 뺀다.
    """
    if isinstance(item, bool):
        return None
    if isinstance(item, dict):
        return _join(*(_describe(v) for v in item.values()), sep=" · ") or None
    if isinstance(item, (list, tuple)):
        return _join(*(_describe(v) for v in item), sep=", ") or None
    return _text(item)


def _describe_all(items: list[Any] | None) -> list[str]:
    return [s for s in (_describe(i) for i in items or []) if s]


def _member(m: TeamMemberRow) -> str | None:
    """팀 구성원 한 명 → '이름(역할): 경력' (잠정)."""
    name, role, exp = _text(m.name), _text(m.role), _text(m.experience)
    head = f"{name}({role})" if name and role else (name or role or "")
    if exp:
        return f"{head}: {exp}" if head else exp
    return head or None


def _revenue_items(rows: list[PricingItemRow]) -> list[RevenueItem] | None:
    """수익모델 항목 전체(저장 순서). 항목이 없거나 단가가 빈 항목이 있으면 결측 (잠정).

    단가는 AI가 지어내면 안 되는 값이라(4-6), 단가 없는 항목을 버리지 않고 입력을 막는다.
    """
    if not rows or any(r.unit_price is None for r in rows):
        return None
    return [RevenueItem(service_name=_text(r.service_name) or "", unit_price=_won(r.unit_price)) for r in rows]


def _won(v: Decimal) -> int:
    """DECIMAL(12,2) 원 → 정수 원. 소수 부분이 있으면 반올림하지 않고 오류로 본다."""
    if v != v.to_integral_value():
        raise ValueError(f"수익모델 단가가 원 단위 정수가 아님: {v}")
    return int(v)


def _period(start: str | None, end: str | None) -> str | None:
    """개발 기간 — 'YYYY-MM ~ YYYY-MM'. 기준 문서는 형식 미정 (잠정)."""
    start, end = _text(start), _text(end)
    return f"{start} ~ {end}" if start and end else None


def _none_or_list(none_selected: bool | None, items: list[Any] | None) -> str | None:
    """'없음'을 골랐으면 '없음', 아니면 항목을 '; '로 이은 한 줄 (잠정)."""
    if none_selected:
        return NONE_TEXT
    return "; ".join(_describe_all(items)) or None


def _self_fund(plan: PlanInputRow) -> int | None:
    """자기부담금(원) — 현금 자기부담 가능액(self_cash_limit, 원 단위 — 웹팀 확인 2026-09-30).

    자기부담을 하지 않으면 0 (잠정). app_schema.sql 주석의 '만원'은 웹 쪽 주석 수정 대상이다.
    """
    if plan.self_funding_allowed is False:
        return 0
    return plan.self_cash_limit
