"""웹 DB에 저장된 사전 정보 입력 — 웹 스키마(web/backend/app_schema.sql) 기준.

웹 백엔드의 create_project(user-input-example.py, 저장소 미포함)가 폼을 받아 저장한 행을
T-C1 입력으로 옮기기 전에 그대로 담는 그릇이다. 필드 이름은 테이블 컬럼 이름과 같다.

- JSON 컬럼(ceo_careers · hires · equipment · partners)은 스키마에 키 이름이 없다(프론트 항목 모양
  그대로 저장). 키 이름은 웹 코드(user-input-example.py의 PlanCareerIn 등)에서 확인했고, 여기서는
  안쪽 구조를 검사하지 않고 그대로 담는다. 키 이름으로 옮기는 일은 mapping.py가 한다.
- 첨부(project_attachments)는 R-8과 함께 다룬다. 지금은 읽지 않는다.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _json_list(v: Any) -> Any:
    """JSON 컬럼 값. 드라이버가 문자열로 돌려주면 풀어서 쓴다."""
    if isinstance(v, (str, bytes)):
        v = json.loads(v) if v else None
    return v


class CompanyRow(_Row):
    """companies — 프로젝트를 만들 때마다 그 프로젝트의 스냅샷으로 생기는 신청자 정보."""
    company_id: int | str
    user_id: int | str
    applicant_type: str | None = None      # preliminary · individual · corp
    biz_type: str | None = None
    ceo_name: str | None = None
    founded_at: date | None = None
    company_name: str | None = None
    business_reg_no: str | None = None
    rep_type: str | None = None


class ProjectRow(_Row):
    project_id: int | str
    company_id: int | str
    description: str | None = None
    output_summary: str | None = None
    tech_field: str | None = None
    regional_priority_area: str | None = None
    archived_at: datetime | None = None


class TeamMemberRow(_Row):
    name: str | None = None
    role: str | None = None
    experience: str | None = None


class PricingItemRow(_Row):
    service_name: str | None = None
    unit_price: Decimal | None = None      # DECIMAL(12,2), 원


class PlanInputRow(_Row):
    """project_plan_inputs — 사전 정보 입력 화면의 '사업 계획' 원본, project당 1행."""
    ceo_birth_date: date | None = None
    ceo_gender: str | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    main_industry: str | None = None       # 개인사업자 · 법인 (드롭다운 9종)
    main_industry_free: str | None = None  # 예비창업자 (자유 입력)
    certifications: list[Any] | None = None
    ceo_careers: list[Any] | None = None   # type · title · period · has_proof (구분 · 내용 · 기간 · 증빙여부)
    ceo_capability: str | None = None
    occupation: str | None = None
    dev_start_month: str | None = None
    dev_end_month: str | None = None
    budget_scale_manwon: int | None = None     # 만원 (웹팀 확인 2026-09-30)
    self_funding_allowed: bool | None = None
    self_cash_limit: int | None = None     # 원 (웹팀 확인 2026-09-30)
    self_in_kind_resources: str | None = None
    no_hires: bool | None = None
    hires: list[Any] | None = None         # job · headcount · required_skill · hire_month (직무 · 인원 · 요구역량 · 채용 시기)
    no_equipment: bool | None = None
    equipment: list[Any] | None = None     # name · status (이름 · 상태)
    no_partners: bool | None = None
    partners: list[Any] | None = None      # name · status (기관명 · 상태)

    _parse_json = field_validator(
        "certifications", "ceo_careers", "hires", "equipment", "partners", mode="before",
    )(_json_list)


class ProjectInputRecord(_Row):
    """프로젝트 1건의 사전 정보 입력 (웹 DB 원본 값)."""
    project: ProjectRow
    company: CompanyRow
    team_members: list[TeamMemberRow] = []     # 0행이면 '팀원 없음' (웹이 입력 또는 선택을 강제)
    pricing_items: list[PricingItemRow] = []   # 저장 순서(기본키 순)
    plan_input: PlanInputRow | None = None
