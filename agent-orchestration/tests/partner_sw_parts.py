"""전략 · 작성 · 검증-1 연결 테스트가 같이 쓰는 부품 — 회사 정보 · 아이템 사양 · 공고 · LLM 요청에 실리면 안 되는 값.

test_partner_sw_tasks.py · test_partner_inputs_fix.py가 가져다 쓴다(테스트 파일끼리 서로 가져다 쓰지 않으려고 모았다).
"""
from __future__ import annotations

from datetime import date

from sbrain.agents.stubs import make_announcement
from sbrain.models import BudgetItem, CompanyInfo, ItemSpec, RevenueItem, ScheduleItem

INSTRUCTION = "이번 Task 지시문"
IDEA = "AI 헬스장 회원 관리 시장 서비스"
ITEM = ItemSpec(item_name="헬스온", one_line_summary="헬스장 회원 관리 요약", target_customer="동네헬스장운영자힌트",
                core_features=["회원 등록·조회", "수업 예약"], category="웹개발", keywords=["헬스장"])

# LLM 요청에 실리면 안 되는 값 ('보내지 않는다')
SECRETS = {
    "대표자 이름": "홍길비밀", "생년월일": "1977-07-07", "성별": "비밀성별값", "사업자등록번호": "777-66-55555",
    "기업명": "비밀상호주식회사", "지역": "비밀특별시 숨김구", "인증": "비밀인증서", "수익모델": "비밀구독상품",
    "희망 사업 규모": "비밀규모값", "자기부담금": "98765432", "직업": "비밀직장명", "지방우대 지역": "비밀우대지역",
    "업종": "비밀업종값", "대표자 유형": "비밀공동대표", "팀원 이름": "팀원이름비밀", "공고 제목": "비밀공고제목",
    "공고 ID": "SECRET-ANN-ID",
}

SCHEDULE = [ScheduleItem(scope="agreement", category="개발", content="화면 개발", period="2026.03~2026.06", detail="웹"),
            ScheduleItem(scope="agreement", category="시험", content="시범 운영", period="2026.07~2026.12", detail=""),
            ScheduleItem(scope="roadmap", category="확산", content="지역 확대", period="2027.01~2027.06", detail="영업")]
EARLY_BUDGET = [BudgetItem(category="재료비", execution_plan="서버 임차", total_amount=12_000_000,
                           government_amount=9_000_000, self_cash_amount=2_000_000, self_in_kind_amount=1_000_000),
                BudgetItem(category="외주용역비", execution_plan="디자인", total_amount=None, government_amount=3_000_000,
                           self_cash_amount=None, self_in_kind_amount=None)]
PRE_BUDGET = [BudgetItem(category="재료비", execution_plan="부품", total_amount=10_000_000, government_amount=7_000_000,
                         self_cash_amount=2_000_000, self_in_kind_amount=1_000_000, phase="1단계"),
              BudgetItem(category="외주용역비", execution_plan="앱", total_amount=20_000_000, government_amount=14_000_000,
                         self_cash_amount=4_000_000, self_in_kind_amount=2_000_000, phase="2단계")]


def company(applicant: str = "법인", *, budget=None, schedule=None) -> CompanyInfo:
    return CompanyInfo(
        representative_name=SECRETS["대표자 이름"], representative_career=["헬스장 운영 5년"],
        founded_at=None if applicant == "예비창업자" else date(2025, 3, 2), applicant_type=applicant,
        revenue_unit_price=35000, team_careers=[f"{SECRETS['팀원 이름']} 개발 3년"], region=SECRETS["지역"],
        industry_code="J62", birth_date=date(1977, 7, 7), gender=SECRETS["성별"],
        certifications=[SECRETS["인증"]], hiring_plan="개발자 1명", facilities="없음", partners="없음",
        desired_scale=SECRETS["희망 사업 규모"], business_reg_no=SECRETS["사업자등록번호"],
        self_fund_amount=int(SECRETS["자기부담금"]),
        revenue_items=[RevenueItem(service_name=SECRETS["수익모델"], unit_price=35000)],
        company_name=SECRETS["기업명"], biz_type=SECRETS["업종"], representative_type=SECRETS["대표자 유형"],
        output_summary="회원 관리 웹 서비스 1종", tech_field="정보통신", regional_priority_area=SECRETS["지방우대 지역"],
        occupation=SECRETS["직업"], representative_capability="헬스장 운영 노하우", self_in_kind_resources="사무실 1곳",
        budget_items=list(EARLY_BUDGET if budget is None and applicant != "예비창업자" else
                          PRE_BUDGET if budget is None else budget),
        schedule_items=list(SCHEDULE if schedule is None else schedule),
        team_role_careers=["개발: 웹 개발 3년", "디자인"])


def announcement(support: int | None = None):
    return make_announcement("A01", date(2026, 9, 26)).model_copy(update={
        "announcement_id": SECRETS["공고 ID"], "title": SECRETS["공고 제목"], "support_amount_max": support})
