"""웹 DB 행 → PreInput 매핑과 SQL 공급처 (웹 스키마 web/backend/app_schema.sql)."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Text, create_engine, insert,
)

from conftest import project_record
from sbrain.intake import MissingRequired, to_pre_input
from sbrain.intake.sql_source import SchemaMismatch, SqlProjectInputSource


# ── 매핑 ─────────────────────────────────────────────
def test_corp_record_maps_to_pre_input():
    f = to_pre_input(project_record())
    assert f.idea_text == "동네 헬스장 회원 관리 서비스"
    assert f.applicant_type == "법인"
    assert f.representative_name == "김서준"
    assert f.representative_career == ["경력: OO피트니스 운영 (5년, 증빙 있음)"]
    assert f.revenue_unit_price == 35000                                   # 호환용 — 첫 항목
    assert [(i.service_name, i.unit_price) for i in f.revenue_items] == [("월 구독", 35000), ("연 구독", 350000)]
    assert f.development_period == "2026-03 ~ 2026-12"
    assert f.team_careers == ["이하늘(개발): 웹 개발 3년", "박지우"]
    assert (f.birth_date, f.gender) == (date(1990, 1, 1), "남")
    assert (f.region, f.industry_code) == ("서울특별시 마포구", "정보·통신")
    assert f.certifications == ["노란우산공제"]
    assert (f.hiring_plan, f.facilities, f.partners) == ("없음", "태블릿 (보유)", "없음")
    assert (f.founded_at, f.business_reg_no, f.self_fund_amount) == (date(2025, 3, 2), "123-45-67890", 10_000_000)
    assert f.desired_scale is None and f.is_first_startup is None and f.attachments is None


def test_extension_fields_carry_web_inputs():
    f = to_pre_input(project_record())
    assert (f.company_name, f.biz_type, f.representative_type) == ("헬스온", "서비스업", "단독")
    assert (f.output_summary, f.tech_field, f.regional_priority_area) == ("회원 관리 웹 서비스 1종", "정보통신", None)
    assert (f.representative_capability, f.self_in_kind_resources, f.occupation) == (
        "헬스장 운영 노하우", "사무실 1곳", None)
    dumped = f.dump()
    assert dumped["revenueItems"] == [{"serviceName": "월 구독", "unitPrice": 35000},
                                      {"serviceName": "연 구독", "unitPrice": 350000}]
    assert dumped["representativeCapability"] == "헬스장 운영 노하우"


def test_preliminary_record_drops_business_fields():
    rec = project_record(company={"applicant_type": "preliminary", "business_reg_no": "999"},
                         plan={"main_industry": None, "main_industry_free": "헬스 · 피트니스",
                               "budget_scale_manwon": 2000, "self_cash_limit": 5, "occupation": "회사원"})
    f = to_pre_input(rec)
    assert f.applicant_type == "예비창업자"
    assert f.founded_at is None and f.business_reg_no is None and f.self_fund_amount is None
    assert f.industry_code == "헬스 · 피트니스"
    assert f.desired_scale == "2000만원"
    assert f.occupation == "회사원"


def test_no_team_members_is_allowed():
    f = to_pre_input(project_record(team_members=[]))       # 웹에서 '팀원 없음'을 고름
    assert f.team_careers == []


def test_self_funding_not_allowed_is_zero():
    f = to_pre_input(project_record(plan={"self_funding_allowed": False, "self_cash_limit": None}))
    assert f.self_fund_amount == 0


def test_json_columns_given_as_strings():
    rec = project_record(plan={"certifications": json.dumps(["벤처기업"]),
                               "ceo_careers": json.dumps([{"a": "가", "b": "나", "c": False}])})
    f = to_pre_input(rec)
    assert f.certifications == ["벤처기업"] and f.representative_career == ["가 · 나"]


# ── 목록 입력 키 이름 변환 (웹 코드 user-input-example.py의 PlanCareerIn 등) ──
def careers(*items: dict) -> list[str]:
    return to_pre_input(project_record(plan={"ceo_careers": list(items)})).representative_career


def career(type=None, title=None, period=None, has_proof=False) -> dict:
    return dict(type=type, title=title, period=period, has_proof=has_proof)


@pytest.mark.parametrize("item, expected", [
    (career("경력", "OO피트니스 운영", "5년", True), "경력: OO피트니스 운영 (5년, 증빙 있음)"),
    (career(None, "OO피트니스 운영", "5년"), "OO피트니스 운영 (5년)"),              # 구분 없음
    (career("학력", "OO대학교 체육학과"), "학력: OO대학교 체육학과"),               # 기간 · 증빙 없음 → 괄호 생략
    (career("자격", "생활스포츠지도사", " ", True), "자격: 생활스포츠지도사 (증빙 있음)"),
    (career("경력", None, "3년"), "경력 (3년)"),                                    # 내용 없음
])
def test_career_by_keys(item, expected):
    assert careers(item) == [expected]


def test_career_proof_only_when_true_and_not_alone():
    # 증빙은 참일 때만 붙고, 증빙 말고는 값이 없는 항목은 뺀다
    assert careers(career("경력", "OO", "5년", False), career(has_proof=True)) == ["경력: OO (5년)"]


def test_hires_by_keys():
    hires = [dict(job="개발자", headcount="2", required_skill="React", hire_month="2026-06"),
             dict(job="디자이너", headcount="1~2명", required_skill=None, hire_month=None),
             dict(job="영업", headcount=None, required_skill="B2B 영업", hire_month="2026-09"),
             dict(job=None, headcount=3, required_skill=None, hire_month=None)]
    f = to_pre_input(project_record(plan={"no_hires": False, "hires": hires}))
    assert f.hiring_plan == ("개발자 2명 · 요구역량: React · 채용 시기: 2026-06; 디자이너 1~2명; "
                             "영업 · 요구역량: B2B 영업 · 채용 시기: 2026-09; 3명")


def test_equipment_and_partners_by_keys():
    f = to_pre_input(project_record(plan={
        "equipment": [dict(name="태블릿", status="보유"), dict(name="POS 단말기", status=None)],
        "no_partners": False, "partners": [dict(name="OO대학교", status="협의 중")]}))
    assert (f.facilities, f.partners) == ("태블릿 (보유); POS 단말기", "OO대학교 (협의 중)")


def test_unknown_keys_fall_back_to_values():
    # 아는 키가 하나도 없으면 지금처럼 값만 잇는다
    f = to_pre_input(project_record(plan={
        "ceo_careers": [{"구분": "경력", "내용": "OO", "증빙": True}],
        "no_hires": False, "hires": [{"role": "개발", "count": 2}],
        "equipment": ["태블릿"]}))
    assert f.representative_career == ["경력 · OO"]
    assert (f.hiring_plan, f.facilities) == ("개발 · 2", "태블릿")


def test_unknown_keys_next_to_known_keys_are_kept():
    # 웹이 키를 더하면 그 값은 버리지 않고 뒤에 잇는다
    assert careers({**career("경력", "OO", "5년"), "org": "OO헬스"}) == ["경력: OO (5년) · OO헬스"]


def test_missing_required_items_are_listed():
    rec = project_record(pricing_items=[dict(service_name="월 구독", unit_price=35000),
                                        dict(service_name="무료 체험", unit_price=None)],
                         plan={"dev_end_month": None, "no_hires": False, "hires": [], "self_cash_limit": None})
    with pytest.raises(MissingRequired) as e:
        to_pre_input(rec)
    # 단가가 빈 항목이 하나라도 있으면 수익모델 단가 결측 (AI가 지어내면 안 되는 값)
    assert e.value.labels == ["수익모델 단가", "개발 기간", "채용 계획", "자기부담금"]


def test_missing_plan_row_and_unknown_type():
    with pytest.raises(MissingRequired) as e:
        to_pre_input(project_record(company={"applicant_type": None}, plan_input=None, pricing_items=[]))
    assert {"신청자 유형", "대표자 생년월일", "수익모델 단가"} <= set(e.value.labels)


def test_fractional_unit_price_is_rejected():
    with pytest.raises(ValueError, match="원 단위 정수"):
        to_pre_input(project_record(pricing_items=[dict(service_name="월 구독", unit_price=Decimal("9900.50"))]))


# ── SQL 공급처 (SQLite로 웹 DB 흉내 — app_schema.sql의 기본키 · 컬럼 이름) ──
def web_db(*, drop_column: str | None = None):
    engine = create_engine("sqlite://")
    meta = MetaData()
    Table("companies", meta, Column("company_id", Integer, primary_key=True), Column("user_id", Integer),
          Column("applicant_type", String(20)), Column("biz_type", String(100)), Column("ceo_name", String(100)),
          Column("founded_at", Date), Column("company_name", String(255)), Column("business_reg_no", String(32)),
          Column("rep_type", String(20)))
    Table("projects", meta, Column("project_id", Integer, primary_key=True), Column("company_id", Integer),
          Column("description", Text), Column("created_at", DateTime), Column("output_summary", Text),
          Column("tech_field", String(100)), Column("regional_priority_area", String(100)),
          Column("notice_id", String(320)), Column("status", String(20)), Column("archived_at", DateTime))
    Table("team_members", meta, Column("member_id", Integer, primary_key=True), Column("project_id", Integer),
          Column("name", String(100)), Column("role", String(100)), Column("experience", Text))
    Table("pricing_items", meta, Column("pricing_id", Integer, primary_key=True), Column("project_id", Integer),
          Column("service_name", String(255)), Column("unit_price", Numeric(12, 2)))
    plan_cols = [Column("input_id", Integer, primary_key=True), Column("project_id", Integer),
                 Column("ceo_birth_date", Date), Column("ceo_gender", String(10)), Column("region_sido", String(20)),
                 Column("region_sigungu", String(50)), Column("main_industry", String(20)),
                 Column("main_industry_free", String(100)), Column("certifications", JSON),
                 Column("ceo_careers", JSON), Column("ceo_capability", Text), Column("occupation", String(100)),
                 Column("dev_start_month", String(7)), Column("dev_end_month", String(7)),
                 Column("budget_scale_manwon", Integer), Column("self_funding_allowed", Boolean),
                 Column("self_cash_limit", Integer), Column("self_in_kind_resources", Text),
                 Column("no_hires", Boolean), Column("hires", JSON), Column("no_equipment", Boolean),
                 Column("equipment", JSON), Column("no_partners", Boolean), Column("partners", JSON),
                 Column("created_at", DateTime)]
    Table("project_plan_inputs", meta, *[c for c in plan_cols if c.name != drop_column])
    meta.create_all(engine)
    rec = project_record()
    with engine.begin() as conn:
        conn.execute(insert(meta.tables["companies"]).values(**rec.company.model_dump()))
        conn.execute(insert(meta.tables["projects"]).values(**rec.project.model_dump()))
        conn.execute(insert(meta.tables["projects"]).values(project_id=102, company_id=11, description="보관됨",
                                                            archived_at=datetime(2026, 9, 1)))
        for m in rec.team_members:
            conn.execute(insert(meta.tables["team_members"]).values(project_id=101, **m.model_dump()))
        # 기본키 순서와 입력 순서를 다르게 넣어 '저장 순서'가 기본키 순인지 본다
        conn.execute(insert(meta.tables["pricing_items"]).values(pricing_id=9, project_id=101,
                                                                 service_name="연 구독", unit_price=350000))
        conn.execute(insert(meta.tables["pricing_items"]).values(pricing_id=3, project_id=101,
                                                                 service_name="월 구독", unit_price=35000))
        plan = {k: v for k, v in rec.plan_input.model_dump().items() if k != drop_column}
        conn.execute(insert(meta.tables["project_plan_inputs"]).values(project_id=101, **plan))
    return engine


def test_sql_source_reads_saved_project():
    src = SqlProjectInputSource(web_db())
    rec = src.load(101)
    assert rec is not None
    assert [p.service_name for p in rec.pricing_items] == ["월 구독", "연 구독"]
    assert rec.plan_input.equipment == [{"name": "태블릿", "status": "보유"}]
    assert to_pre_input(rec) == to_pre_input(project_record())


def test_sql_source_archived_or_missing_project():
    src = SqlProjectInputSource(web_db())
    assert src.load(102) is None     # 보관 처리된 프로젝트
    assert src.load(999) is None


def test_sql_source_reports_schema_mismatch():
    src = SqlProjectInputSource(web_db(drop_column="ceo_capability"))
    with pytest.raises(SchemaMismatch, match="ceo_capability"):
        src.load(101)
