"""SQLAlchemy 2.x ORM 모델. app_schema.sql(설계 문서 기준 23테이블)과 1:1로 대응한다.

Notice 는 공고 수집 파이프라인(mysql_schema.sql)이 소유한 테이블이라
여기서는 읽기 전용으로 필요한 컬럼만 매핑한다(마이그레이션은 이 앱에서 만들지 않음).
"""
import datetime
import decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import INTEGER as MySQLInteger
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# app_schema.sql엔 MySQL 전용 타입(LONGTEXT, INT UNSIGNED)으로 선언된 컬럼이 있는데,
# 이 타입들을 그대로 쓰면 SQLite(tests/conftest.py가 만드는 테스트 DB)에서 컴파일 에러가 난다.
# with_variant()로 "MySQL에서는 이 타입, 그 외 방언에서는 원래 제네릭 타입"으로 갈라줘서
# 운영(MySQL)에선 app_schema.sql과 정확히 일치하고, 테스트(SQLite)에선 그대로 동작하게 한다.
_LongText = Text().with_variant(LONGTEXT, 'mysql')
_UnsignedInt = Integer().with_variant(MySQLInteger(unsigned=True), 'mysql')


# ---------------------------------------------------------------------------
# 공고 수집 스키마 — 읽기 전용 매핑 (mysql_schema.sql 이 정본)
# ---------------------------------------------------------------------------
class Notice(Base):
    __tablename__ = 'notices'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notice_id: Mapped[str] = mapped_column(String(320), unique=True)
    source: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 매칭결과 응답의 "org" 관련 필드 — source에 따라 셋 중 일부만 채워짐(백엔드 결정 8번 참고)
    organizer: Mapped[str | None] = mapped_column(Text, nullable=True)        # K-Startup 공고만
    supervising_org: Mapped[str | None] = mapped_column(Text, nullable=True)  # 기업마당 소관기관
    executing_org: Mapped[str | None] = mapped_column(Text, nullable=True)    # 기업마당 수행기관
    apply_start: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    apply_end: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    recruitment_status: Mapped[str] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 아래 3개는 2026-09-11 시점 실제 mysql_schema.sql엔 아직 없는 컬럼이다(확인 완료).
    # 이근준님께 notices 테이블에 추가해달라고 요청한 상태를 가정하고 활성화해둔 "있는
    # 버전" — 실제로 컬럼이 반영됐는지 다시 확인 전까지는 이 3줄을 주석 처리해서
    # "없는 버전"으로 되돌려야 실제 DB와 어긋나지 않는다.
    embedding_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    embedding_updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    embedding_fail_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 사용자
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = 'users'

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    google_sub: Mapped[str] = mapped_column(String(255), unique=True)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(20), default='user')
    status: Mapped[str] = mapped_column(String(20), default='active')
    face_verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    companies: Mapped[list['Company']] = relationship(back_populates='user')
    faqs: Mapped[list['Faq']] = relationship(back_populates='user')


# ---------------------------------------------------------------------------
# 회사(예비창업자/기업 프로필) / 아이템(지원 아이템)
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = 'companies'

    company_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.user_id'))
    start_type: Mapped[str] = mapped_column(String(32))
    biz_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ceo_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    founded_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)

    user: Mapped['User'] = relationship(back_populates='companies')
    items: Mapped[list['Item']] = relationship(back_populates='company')


class Item(Base):
    __tablename__ = 'items'

    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('companies.company_id'))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    notify_region: Mapped[str] = mapped_column(String(32))
    notify_industry: Mapped[str] = mapped_column(String(32))

    company: Mapped['Company'] = relationship(back_populates='items')
    attachments: Mapped[list['ItemAttachment']] = relationship(back_populates='item')
    team_members: Mapped[list['TeamMember']] = relationship(back_populates='item')
    pricing_items: Mapped[list['PricingItem']] = relationship(back_populates='item')
    matches: Mapped[list['MatchResult']] = relationship(back_populates='item')


class ItemAttachment(Base):
    __tablename__ = 'item_attachments'

    attachment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('items.item_id'))
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(500))

    item: Mapped['Item'] = relationship(back_populates='attachments')


class TeamMember(Base):
    __tablename__ = 'team_members'

    member_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('items.item_id'))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experience: Mapped[str | None] = mapped_column(Text, nullable=True)

    item: Mapped['Item'] = relationship(back_populates='team_members')


class PricingItem(Base):
    __tablename__ = 'pricing_items'

    pricing_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('items.item_id'))
    service_name: Mapped[str] = mapped_column(String(255))
    unit_price: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    item: Mapped['Item'] = relationship(back_populates='pricing_items')


# ---------------------------------------------------------------------------
# 유사 공고 알림 / 매칭 / 자격요건 게이트
# ---------------------------------------------------------------------------
class NoticeAlert(Base):
    __tablename__ = 'notice_alerts'

    alert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('items.item_id'))
    notice_id: Mapped[str] = mapped_column(String(320), ForeignKey('notices.notice_id'))
    similarity_score: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class MatchResult(Base):
    __tablename__ = 'match_results'

    match_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('items.item_id'))
    notice_id: Mapped[str] = mapped_column(String(320), ForeignKey('notices.notice_id'))
    fit_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='in_progress')
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    archived_by: Mapped[str | None] = mapped_column(String(20), nullable=True)

    item: Mapped['Item'] = relationship(back_populates='matches')
    eligibility_checks: Mapped[list['EligibilityCheck']] = relationship(back_populates='match')
    business_plans: Mapped[list['BusinessPlan']] = relationship(back_populates='match')


class EligibilityCheck(Base):
    __tablename__ = 'eligibility_checks'

    check_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('match_results.match_id'))
    passed: Mapped[bool] = mapped_column(Boolean)
    checked_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    match: Mapped['MatchResult'] = relationship(back_populates='eligibility_checks')


# ---------------------------------------------------------------------------
# 사업계획서(문서층) / 산출물(산출물층) / 최종 판정
# ---------------------------------------------------------------------------
class BusinessPlan(Base):
    __tablename__ = 'business_plans'

    plan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('match_results.match_id'))
    doc_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    threshold: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    match: Mapped['MatchResult'] = relationship(back_populates='business_plans')
    sections: Mapped[list['PlanSection']] = relationship(back_populates='plan')
    score_reasons: Mapped[list['PlanScoreReason']] = relationship(back_populates='plan')
    artifacts: Mapped[list['Artifact']] = relationship(back_populates='plan')
    score_history: Mapped[list['VerificationScoreHistory']] = relationship(back_populates='plan')


class PlanSection(Base):
    __tablename__ = 'plan_sections'

    section_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    tag: Mapped[str] = mapped_column(String(16))  # P / S / S / T
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(_LongText, nullable=True)  # app_schema.sql: LONGTEXT

    plan: Mapped['BusinessPlan'] = relationship(back_populates='sections')


class PlanScoreReason(Base):
    __tablename__ = 'plan_score_reasons'

    reason_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    reason_text: Mapped[str] = mapped_column(Text)

    plan: Mapped['BusinessPlan'] = relationship(back_populates='score_reasons')


class Artifact(Base):
    __tablename__ = 'artifacts'

    artifact_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    category: Mapped[str] = mapped_column(String(32))  # onepage | webdev | aiapi
    infographic_path: Mapped[str] = mapped_column(String(500))
    executable_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artifact_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    plan: Mapped['BusinessPlan'] = relationship(back_populates='artifacts')
    score_reasons: Mapped[list['ArtifactScoreReason']] = relationship(back_populates='artifact')


class ArtifactScoreReason(Base):
    __tablename__ = 'artifact_score_reasons'

    reason_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('artifacts.artifact_id'))
    reason_text: Mapped[str] = mapped_column(Text)

    artifact: Mapped['Artifact'] = relationship(back_populates='score_reasons')


class Verdict(Base):
    __tablename__ = 'verdicts'

    verdict_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    artifact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('artifacts.artifact_id'))
    overall_passed: Mapped[bool] = mapped_column(Boolean)
    model_version: Mapped[str] = mapped_column(String(50))  # v1 | v2 | v3
    first_pass_passed: Mapped[bool] = mapped_column(Boolean)


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------
class Faq(Base):
    __tablename__ = 'faqs'

    faq_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.user_id'))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    answered_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped['User'] = relationship(back_populates='faqs')


# ---------------------------------------------------------------------------
# 에이전트 실행 로그 (관리자 대시보드 "에이전트 테스크" 탭)
# ---------------------------------------------------------------------------
# 고정 Task 14단계(기획서 4-4) — agent_executions 를 이 순서대로 14행 남긴다.
# 테이블 자체에는 task_name 컬럼이 없으므로(설계 문서 원안), agent_name 만 기록되고
# 같은 agent 가 여러 단계를 맡으면 그만큼 여러 행이 남는다(예: 검증-1 이 2행).
FIXED_TASK_SEQUENCE = [
    ('coordinate_intake', '조율'),
    ('strategy', '전략'),
    ('writing', '작성'),
    ('verify1_rubric', '검증-1'),
    ('verify1_evidence', '검증-1'),
    ('user_decision_doc', '조율'),
    ('implement_prototype', '구현'),
    ('implement_infographic', '구현'),
    ('verify2_static', '검증-2'),
    ('verify2_crosscheck', '검증-2'),
    ('user_decision_final', '조율'),
    ('review_expression', '검수'),
    ('review_token_check', '검수'),
    ('coordinate_finalize', '조율'),
]


class AgentExecution(Base):
    __tablename__ = 'agent_executions'

    execution_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('match_results.match_id'), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(50))
    model_used: Mapped[str] = mapped_column(String(50))
    rerun_type: Mapped[str] = mapped_column(String(20))
    token_usage: Mapped[int] = mapped_column(_UnsignedInt)  # app_schema.sql: INT UNSIGNED
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 검증 정책 (admin-dashboard.html 검증 정책 탭과 대응)
# ---------------------------------------------------------------------------
class VerificationPolicy(Base):
    __tablename__ = 'verification_policies'

    policy_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_weight: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=70)
    code_weight: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=15)
    plan_weight: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=15)
    pass_threshold: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=70)
    rerun_cap: Mapped[int] = mapped_column(_UnsignedInt, default=3)  # app_schema.sql: INT UNSIGNED
    deviation_cap: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=5)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class VerificationChecklistItem(Base):
    __tablename__ = 'verification_checklist_items'

    check_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    method: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20))
    weight: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class VerificationScoreHistory(Base):
    __tablename__ = 'verification_score_history'

    history_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    layer: Mapped[str] = mapped_column(String(20))  # doc | code | plan
    score: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    is_rerun: Mapped[bool] = mapped_column(Boolean, default=False)
    scored_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped['BusinessPlan'] = relationship(back_populates='score_history')