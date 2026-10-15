"""웹 DB 행 → PreInput (시트 4 PreInput, 시트 6 E-C1-REQUIRED).

- 값을 옮기기만 한다. 요약 · 보완 · 추정하지 않는다 (4-6: 수익모델 단가 · 경력은 사용자 입력만 쓴다).
- 필수 항목이 비어 있으면 MissingRequired를 올린다. 호출한 쪽은 E-C1-REQUIRED로 안내하고
  T-C1을 실행하지 않는다. 폼 제출 단계(웹)의 검사를 다시 한 번 확인하는 자리다.
- DB 구조와 PreInput 필드가 1:1이 아닌 곳의 변환 규칙은 기준 문서에 없어 잠정이다.
  목록은 docs/T-C1_요구사항해석_구현.md 4절에 있다.
- PreInput에 자리가 없는 웹 입력값은 확장 필드(FormExtension)로 그대로 싣는다.
- 목록 입력(대표자 이력 · 채용 계획 · 장비 · 협력 기관)은 웹 코드(user-input-example.py의
  PlanCareerIn · PlanHireIn · PlanEquipmentIn · PlanPartnerIn)의 키 이름으로 한 줄을 만든다.
  모르는 키만 있는 항목은 값만 순서대로 잇는다.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Callable

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
PROOF_TEXT = "증빙 있음"  # 대표자 이력에 증빙이 있을 때 붙인다 (사용자 결정 2026-09-30)

# 목록 입력 항목의 키 (웹 코드 user-input-example.py)
CAREER_KEYS = ("type", "title", "period", "has_proof")           # PlanCareerIn — 구분 · 내용 · 기간 · 증빙여부
HIRE_KEYS = ("job", "headcount", "required_skill", "hire_month")  # PlanHireIn — 직무 · 인원 · 요구역량 · 채용 시기
NAMED_KEYS = ("name", "status")                                   # PlanEquipmentIn · PlanPartnerIn — 이름 · 상태


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
        "representative_career": _describe_all(plan.ceo_careers, _career_item),
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
        "hiring_plan": _none_or_list(plan.no_hires, plan.hires, _hire_item),
        "facilities": _none_or_list(plan.no_equipment, plan.equipment, _named_item),
        "partners": _none_or_list(plan.no_partners, plan.partners, _named_item),
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
    """키 이름을 모르는 항목을 한 줄로 — 값만 순서대로 잇는다 (잠정).

    참 · 거짓 값은 이름 없이 옮기면 뜻이 없어 뺀다.
    """
    if isinstance(item, bool):
        return None
    if isinstance(item, dict):
        return _join(*(_describe(v) for v in item.values()), sep=" · ") or None
    if isinstance(item, (list, tuple)):
        return _join(*(_describe(v) for v in item), sep=", ") or None
    return _text(item)


def _describe_all(items: list[Any] | None, describe: Callable[[Any], str | None] = _describe) -> list[str]:
    return [s for s in (describe(i) for i in items or []) if s]


def _keyed(item: Any, keys: tuple[str, ...], fmt: Callable[[dict[str, Any]], str | None]) -> str | None:
    """키 이름을 아는 항목은 fmt로 한 줄을 만든다 (잠정).

    아는 키가 하나도 없으면 값만 잇기(_describe)로 돌아간다. 아는 키와 모르는 키가 섞여 있으면
    모르는 키의 값을 뒤에 ` · `로 이어 사용자 입력을 버리지 않는다.
    """
    if not isinstance(item, dict) or not any(k in item for k in keys):
        return _describe(item)
    rest = _describe({k: v for k, v in item.items() if k not in keys})
    return _join(fmt(item), rest, sep=" · ") or None


def _with_notes(head: str | None, notes: list[str]) -> str | None:
    """'머리 (덧붙임, 덧붙임)'. 덧붙일 것이 없으면 괄호를 생략한다."""
    if not notes:
        return head
    note = ", ".join(notes)
    return f"{head} ({note})" if head else note


def _career(c: dict[str, Any]) -> str | None:
    """대표자 이력 — '구분: 내용 (기간, 증빙 있음)' (잠정).

    구분이 없으면 '내용 (기간)', 기간 · 증빙이 없으면 괄호를 생략한다. 증빙은 참일 때만 붙인다
    (사용자 결정 2026-09-30). 증빙 말고는 값이 없는 항목은 뜻이 없어 뺀다.
    """
    kind, title, period = _describe(c.get("type")), _describe(c.get("title")), _describe(c.get("period"))
    if not (kind or title or period):
        return None
    head = f"{kind}: {title}" if kind and title else (title or kind)
    notes = [s for s in (period, PROOF_TEXT if c.get("has_proof") is True else None) if s]
    return _with_notes(head, notes)


def _hire(h: dict[str, Any]) -> str | None:
    """채용 계획 — '직무 인원 · 요구역량: … · 채용 시기: …' (잠정).

    인원(headcount)은 문자열이다. 숫자만 있으면 '명'을 붙이고 아니면 그대로 쓴다. 빈 값은 생략한다.
    """
    job, count = _describe(h.get("job")), _describe(h.get("headcount"))
    if count and re.fullmatch(r"[0-9]+", count):
        count += "명"
    skill, month = _describe(h.get("required_skill")), _describe(h.get("hire_month"))
    return _join(_join(job, count), f"요구역량: {skill}" if skill else None,
                 f"채용 시기: {month}" if month else None, sep=" · ") or None


def _named(item: dict[str, Any]) -> str | None:
    """장비 · 시설, 협력 기관 — '이름 (상태)' (잠정). 상태가 없으면 괄호를 생략한다."""
    name, status = _describe(item.get("name")), _describe(item.get("status"))
    return _with_notes(name, [status] if status else [])


def _career_item(item: Any) -> str | None:
    return _keyed(item, CAREER_KEYS, _career)


def _hire_item(item: Any) -> str | None:
    return _keyed(item, HIRE_KEYS, _hire)


def _named_item(item: Any) -> str | None:
    return _keyed(item, NAMED_KEYS, _named)


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


def _none_or_list(none_selected: bool | None, items: list[Any] | None,
                  describe: Callable[[Any], str | None]) -> str | None:
    """'없음'을 골랐으면 '없음', 아니면 항목을 '; '로 이은 한 줄 (잠정)."""
    if none_selected:
        return NONE_TEXT
    return "; ".join(_describe_all(items, describe)) or None


def _self_fund(plan: PlanInputRow) -> int | None:
    """자기부담금(원) — 현금 자기부담 가능액(self_cash_limit, 원 단위 — 웹팀 확인 2026-09-30).

    자기부담을 하지 않으면 0 (잠정). app_schema.sql 주석의 '만원'은 웹 쪽 주석 수정 대상이다.
    """
    if plan.self_funding_allowed is False:
        return 0
    return plan.self_cash_limit
