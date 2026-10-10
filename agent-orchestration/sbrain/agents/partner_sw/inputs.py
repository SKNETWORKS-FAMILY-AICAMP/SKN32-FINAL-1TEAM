"""담당자 입력 만들기 — LLM으로 보내는 칸(spec 4.4) · 표 원본 행(tableData) · 울타리(4.5) · 입력 없음(4.9).

담당자 normalize_back_input은 쓰지 않고 담당자 입력 모양(2_지금_입력받는값)을 우리 값으로 직접 만든다. 보내는 칸은 spec 4.4
표뿐이다 — 대표자 이름 · 생년월일 · 성별 · 사업자등록번호 · 기업명 · 지역 · 인증 · 수익모델 · 희망 사업 규모 · 자기부담금 ·
직업 · 지방우대 지역 · 업종(biz_type) · 대표자 유형 · 팀원 이름 · 공고 제목 · 공고 ID는 여기서 꺼내지 않는다. 칸을 늘리려면
사용자에게 먼저 묻는다.
"""
from __future__ import annotations

import re
from typing import Any

from ...models import BudgetItem, CompanyInfo, ScheduleItem
from .contract import EARLY_STARTUP, PRE_STARTUP

APPLICANT_PRE_STARTUP = "예비창업자"   # 우리 신청자 유형 — 예비창업자 → 담당자 pre_startup, 나머지 → early_startup
CONFIRM = "확인 필요"                  # 담당자 코드의 빈 값 표기
UNDECIDED = "미정"                     # 빈 추진기간 표기 (담당자 코드와 같음)
NONE_TEXT = "없음"                     # 채용 · 장비 · 협력에서 '없음'을 골랐을 때의 한 줄 값 (intake와 같은 글자)
TARGET_CUSTOMER = CONFIRM              # 원본 사실의 목표 고객 — 늘 '확인 필요' (담당자와 같음, spec 2절)
TARGET_HINT_KEY = "targetCustomerHint"  # F02 요청에만 싣는 참고값 칸 (spec 4.4 — 원본 사실 아님)
ITEM_KEYS = ("description", "output_summary", "tech_field", "target_customer")

SCHEDULE_LABEL = "추진 일정"           # 입력 없음 안내 이름 (spec 4.9)
BUDGET_LABEL = "사업비 집행계획"
PHASE_1, PHASE_2 = "1단계", "2단계"

# 예비창업 울타리의 deadlineScope 문구 — 담당자 normalize_back_input 그대로 (spec 4.5)
DEADLINE_SCOPE = ("협약 종료 기한. 협약기간 일정(implementationSchedule)에만 적용하며, 협약 이후 전체 사업단계 일정"
                  "(fullScaleSchedule)은 이 기한을 넘어도 위반이 아님")

_MONTH = re.compile(r"(20\d{2})\s*[-./년]?\s*(\d{1,2})")


def document_type(applicant_type: str) -> str:
    """신청자 유형 → 담당자 문서 유형 (spec 4.6)."""
    return PRE_STARTUP if applicant_type == APPLICANT_PRE_STARTUP else EARLY_STARTUP


# ── 개발 기간 (developmentPeriod 'YYYY-MM ~ YYYY-MM') ───────────
def _month(text: str) -> str | None:
    m = _MONTH.search(text or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def dev_months(period: str | None) -> tuple[str | None, str | None]:
    """개발 시작월 · 종료월. '~' 앞뒤를 나눠 읽고, 읽을 수 없으면 None."""
    if not period or "~" not in period:
        return None, None
    start, end = period.split("~", 1)
    return _month(start), _month(end)


def duration_months(start: str | None, end: str | None) -> int:
    """개발 개월 수 — 담당자 run_pipeline과 같은 셈. 없거나 종료가 시작보다 빠르면 0."""
    if not start or not end:
        return 0
    (sy, sm), (ey, em) = (map(int, start.split("-")), map(int, end.split("-")))
    months = (ey - sy) * 12 + em - sm + 1
    return months if months >= 1 else 0


# ── 담당자 입력 칸 (spec 4.4) ─────────────────────────────
def project_body(description: str, company: CompanyInfo) -> dict[str, Any]:
    """POST_projects_body — 아이디어 설명 · 산출물 · 전문기술분야(없으면 주 업종) · 목표 고객('확인 필요')."""
    return {"description": description, "output_summary": company.output_summary,
            "tech_field": company.tech_field or company.industry_code, "target_customer": TARGET_CUSTOMER}


def team_input(company: CompanyInfo) -> dict[str, Any]:
    """대표자 역량 · 경력과 팀원 역할 · 경력(teamRoleCareers — 이름 없음). '역할: 경력'이 아니면 그 한 줄을 역할로 본다."""
    members = []
    for line in company.team_role_careers:
        role, sep, experience = str(line).partition(": ")
        members.append({"role": role.strip() or None, "experience": experience.strip() or None if sep else None})
    return {"representative": {"capabilities": company.representative_capability,
                               "careers": list(company.representative_career)},
            "members": members}


def _resource(text: str | None) -> tuple[bool, list[str]]:
    value = (text or "").strip()
    if value == NONE_TEXT:
        return True, []
    return False, ([value] if value else [])


def resource_input(company: CompanyInfo) -> dict[str, Any]:
    """채용 · 장비 · 협력 한 줄 문자열(‘없음’이면 no_* 참)과 현물 자기부담 자원."""
    no_hires, hires = _resource(company.hiring_plan)
    no_equipment, equipment = _resource(company.facilities)
    no_partners, partners = _resource(company.partners)
    return {"no_hires": no_hires, "hires": hires, "no_equipment": no_equipment, "equipment": equipment,
            "no_partners": no_partners, "partners": partners,
            "self_in_kind_resources": company.self_in_kind_resources}


def budget_rows(company: CompanyInfo, kind: str) -> list[dict[str, Any]]:
    """F14에 넘기는 정규화 행(project_budget_items — 담당자 영문 키). None 금액은 담당자 _won처럼 0으로 계산하고, 총사업비가
    세 금액의 합과 다르면 합으로 다시 내며, 총사업비가 0인 행은 뺀다(표 행에는 남는다, spec 4.4)."""
    rows = []
    for b in company.budget_items:
        gov, cash, in_kind = b.government_amount or 0, b.self_cash_amount or 0, b.self_in_kind_amount or 0
        total = b.total_amount or 0
        if total and gov + cash + in_kind != total:
            total = gov + cash + in_kind
        if not total:
            continue
        row: dict[str, Any] = {"category": b.category or CONFIRM, "execution_plan": b.execution_plan or "",
                               "total_amount": total, "government_amount": gov, "self_cash_amount": cash,
                               "self_in_kind_amount": in_kind}
        if kind == PRE_STARTUP and b.phase:
            row["phase"] = b.phase
        rows.append(row)
    return rows


def _schedule_row(s: ScheduleItem) -> dict[str, str]:
    """일정 표 원본 행(한글 열). 추진기간이 비면 '미정', 나머지 빈 칸은 '확인 필요'."""
    return {"구분": s.category or CONFIRM, "추진내용": s.content or CONFIRM, "추진기간": s.period or UNDECIDED,
            "세부내용": s.detail or CONFIRM}


def schedule_rows(company: CompanyInfo) -> list[dict[str, Any]]:
    """project_schedule_items — 협약기간 일정 다음 협약 이후 일정, 담당자 정규화와 같은 칸(_schedule_scope · category · task ·
    period · details)."""
    rows = []
    for scope in ("agreement", "roadmap"):
        for s in company.schedule_items:
            if s.scope != scope:
                continue
            row = {**_schedule_row(s), "_schedule_scope": scope}
            rows.append({**row, "category": row["구분"], "task": row["추진내용"], "period": row["추진기간"],
                         "details": row["세부내용"]})
    return rows


def _won(value: int | None) -> str:
    return CONFIRM if value is None else f"{value:,}원"


def _budget_table_row(b: BudgetItem, kind: str) -> dict[str, str]:
    """사업비 표 원본 행(한글 열). 금액은 '15,000,000원' 꼴, None이면 '확인 필요'. 예비창업은 자기부담금 = 현금 + 현물."""
    row = {"비목": b.category or CONFIRM, "집행계획": b.execution_plan or CONFIRM,
           "총사업비": _won(b.total_amount), "정부지원사업비": _won(b.government_amount)}
    if kind == PRE_STARTUP:
        both = None if b.self_cash_amount is None or b.self_in_kind_amount is None else (
            b.self_cash_amount + b.self_in_kind_amount)
        row["자기부담금"] = _won(both)
    else:
        row["자기부담_현금"] = _won(b.self_cash_amount)
        row["자기부담_현물"] = _won(b.self_in_kind_amount)
    return row


def table_data(company: CompanyInfo, kind: str) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    """담당자 F17(table_arguments)이 읽는 tableData(한글 키 · 한글 열)와 예비창업 단계 미지정 사업비 행 (spec 4.4).

    예비창업: phase '1단계' → budgetPlanStep1, '2단계' → budgetPlanStep2, None → 어느 표에도 넣지 않고 돌려준다
    (2.5.3 표의 rules.unassignedOriginalRows로 보존). 초기창업은 단계 구분이 없다."""
    agreement = [_schedule_row(s) for s in company.schedule_items if s.scope == "agreement"]
    roadmap = [_schedule_row(s) for s in company.schedule_items if s.scope == "roadmap"]
    if kind == PRE_STARTUP:
        step1 = [_budget_table_row(b, kind) for b in company.budget_items if b.phase == PHASE_1]
        step2 = [_budget_table_row(b, kind) for b in company.budget_items if b.phase == PHASE_2]
        unassigned = [_budget_table_row(b, kind) for b in company.budget_items if b.phase is None]
        return ({"implementationSchedule": agreement, "fullScaleSchedule": roadmap,
                 "budgetPlanStep1": step1, "budgetPlanStep2": step2}, unassigned)
    return ({"실현가능성_일정": agreement, "성장전략_일정": roadmap,
             "사업비_집행계획": [_budget_table_row(b, kind) for b in company.budget_items]}, [])


def _suffix(code: str) -> str:
    return ".".join(code.split(".")[1:])


def table_source_rows(kind: str, code: str, data: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    """그 표 항목의 사용자 원본 행 — 담당자 table_arguments와 같은 키 고르기(5.2 · 6.2 · 5.3 · 5.4)."""
    suffix = _suffix(code)
    if kind == PRE_STARTUP:
        keys = {"5.2": ["implementationSchedule"], "6.2": ["implementationSchedule", "fullScaleSchedule"],
                "5.3": ["budgetPlanStep1"], "5.4": ["budgetPlanStep2"]}.get(suffix, [])
    else:
        keys = {"5.2": ["실현가능성_일정"], "6.2": ["실현가능성_일정", "성장전략_일정"],
                "5.3": ["사업비_집행계획"]}.get(suffix, [])
    return [row for key in keys for row in data.get(key, [])]


def is_budget_table(code: str) -> bool:
    return _suffix(code) in ("5.3", "5.4")


def missing_inputs(company: CompanyInfo, kind: str, table_codes: list[str]) -> dict[str, str]:
    """입력 없음 표 항목 → 안내 이름(사업비 집행계획 · 추진 일정) (spec 4.9).

    그 표의 사용자 원본 행이 비었거나, 예비창업 사업비에 단계 미지정 행이 있으면(1 · 2단계 표에 넣을 수 없음 —
    2.5.3 · 2.5.4 둘 다, 잠정 · 웹 phase 컬럼 대기) 입력 없음이다."""
    data, unassigned = table_data(company, kind)
    out: dict[str, str] = {}
    for code in table_codes:
        budget = is_budget_table(code)
        if not table_source_rows(kind, code, data) or (budget and kind == PRE_STARTUP and unassigned):
            out[code] = BUDGET_LABEL if budget else SCHEDULE_LABEL
    return out


# ── 울타리 (spec 4.5) ─────────────────────────────────────
def strategy_limits(kind: str, end_month: str | None, support_max: int | None, features: list[str]) -> dict[str, Any]:
    """deadline = 개발 종료월(없으면 칸 없음), supportLimit = 선택 공고 지원 금액 상한(없으면 칸 없음 — 상한 검사를 하지
    않는다), featureList, 예비창업이면 deadlineScope."""
    limits: dict[str, Any] = {}
    if end_month:
        limits["deadline"] = end_month
    if support_max is not None:
        limits["supportLimit"] = support_max
    limits["featureList"] = list(features)
    if kind == PRE_STARTUP and limits.get("deadline"):
        limits["deadlineScope"] = DEADLINE_SCOPE
    return limits
