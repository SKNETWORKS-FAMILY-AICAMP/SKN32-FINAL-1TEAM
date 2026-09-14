"""SQLAlchemy 2.x ORM 모델. app_schema.sql(설계 문서 기준 23테이블)과 1:1로 대응한다.

Notice 는 공고 수집 파이프라인(mysql_schema.sql)이 소유한 테이블이라
여기서는 읽기 전용으로 필요한 컬럼만 매핑한다(마이그레이션은 이 앱에서 만들지 않음).
"""
import datetime
import decimal

from sqlalchemy import (
    JSON,
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

from app.database import IS_SQLITE, Base

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

    # ── 아래 3개는 실제 mysql_schema.sql(AWS 공유 DB)엔 없는 컬럼이다 — 2026-09-11 재확인 결과도
    # 여전히 없음. 이근준님께 추가를 요청한 상태지만 아직 반영 전이라, MySQL 모드에서는 이
    # 3개를 아예 컬럼으로 만들지 않는다 — 그래야 items.py의 db.query(Notice)가 실제 AWS
    # MySQL에서 "Unknown column 'notices.embedding_status'" 에러로 죽는 사고를 막는다.
    #
    # 다만 로컬 SQLite 개발 모드(DB_BACKEND=sqlite)는 dev.db를 매번 모델 그대로 새로 만드는
    # 거라 실제 DB와 어긋날 일이 없어서, 여기서만 이 3개를 켜둔다 — embedding_status 기반
    # 매칭/필터링 로직을 미리 로컬에서 짜보고 싶을 때 쓰라고. IS_SQLITE가 False인 MySQL
    # 모드에서는 클래스 본문이 아예 실행 안 되니 컬럼 자체가 없는 걸로 취급된다.
    # 이근준님이 실제로 컬럼을 추가해주면, 이 if 블록을 지우고 들여쓰기 없이 항상 켜진
    # 상태로 바꿀 것 (backend_decisions.md #16 참고).
    if IS_SQLITE:
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
    ai_training_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
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
    # unique=True: "계정당 회사 프로필 1건" 가정을 주석이 아니라 DB 제약으로 강제한다.
    # POST /projects의 동시 실행 제한 로직(backend_decisions.md #11)이 이 가정 위에서
    # 동작하므로, 동시 요청으로 회사 프로필이 2건 생기면 그 가정이 깨져 제한 로직도
    # 같이 무력화된다 — 그래서 유니크 제약 + 코드의 insert-then-catch 패턴으로 막는다.
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.user_id'), unique=True)
    start_type: Mapped[str] = mapped_column(String(32))
    biz_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ceo_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    founded_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)

    user: Mapped['User'] = relationship(back_populates='companies')
    projects: Mapped[list['Project']] = relationship(back_populates='company')


class Project(Base):
    """DB 테이블/컬럼 이름까지 전부 'project'로 통일했다 (backend_decisions.md #5 개정).
    원래는 '설계문서 그대로 items 테이블 유지, URL만 /projects'로 정했었는데, API
    표면(URL, 응답 필드)과 DB 이름이 다르면 헷갈린다는 이유로 DB까지 다 바꾸기로 했다.
    이미 AWS에 예전 이름(items/item_id)으로 스키마를 적용했다면, app_schema.sql 을
    이 버전으로 다시 적용하기 전에 rename_items_to_projects.sql 로 먼저 이름을 바꾸거나,
    drop_tables.sql 로 지우고 새로 적용해야 한다."""
    __tablename__ = 'projects'

    project_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('companies.company_id'))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    notify_region: Mapped[str] = mapped_column(String(32))
    notify_industry: Mapped[str] = mapped_column(String(32))

    company: Mapped['Company'] = relationship(back_populates='projects')
    attachments: Mapped[list['ProjectAttachment']] = relationship(back_populates='project')
    team_members: Mapped[list['TeamMember']] = relationship(back_populates='project')
    pricing_items: Mapped[list['PricingItem']] = relationship(back_populates='project')
    matches: Mapped[list['MatchResult']] = relationship(back_populates='project')


class ProjectAttachment(Base):
    __tablename__ = 'project_attachments'

    attachment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(500))

    project: Mapped['Project'] = relationship(back_populates='attachments')


class TeamMember(Base):
    __tablename__ = 'team_members'

    member_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experience: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped['Project'] = relationship(back_populates='team_members')


class PricingItem(Base):
    __tablename__ = 'pricing_items'

    pricing_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    service_name: Mapped[str] = mapped_column(String(255))
    unit_price: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    project: Mapped['Project'] = relationship(back_populates='pricing_items')


# ---------------------------------------------------------------------------
# 유사 공고 알림 / 매칭 / 자격요건 게이트
# ---------------------------------------------------------------------------
class NoticeAlert(Base):
    __tablename__ = 'notice_alerts'

    alert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    notice_id: Mapped[str] = mapped_column(String(320), ForeignKey('notices.notice_id'))
    similarity_score: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class MatchResult(Base):
    __tablename__ = 'match_results'

    match_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    notice_id: Mapped[str] = mapped_column(String(320), ForeignKey('notices.notice_id'))
    fit_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='in_progress')
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    archived_by: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 이어하기(기획서 4-7절 p.20, 8케이스) 대응 — existing_user_resume_test_report.md에서
    # 확인한 대로, 기존 컬럼(자식 행 존재 여부)만으로는 8케이스 중 6개가 서로 구분되지
    # 않았다. stage는 app/pipeline_stages.py의 상수 중 하나(또는 아직 파이프라인 시작
    # 전이라 match_results 행 자체가 없으면 NULL이 아니라 행 자체가 없음)이고,
    # progress_percent는 stage='plan_writing'/'prototype_building'처럼 한 단계 안에서도
    # 오래 걸리는 구간의 진행률(0~100)을 담는다 — 실제 Agent 파이프라인이 각 Task를
    # 처리할 때마다 이 두 컬럼을 갱신하게 될 자리다.
    stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped['Project'] = relationship(back_populates='matches')
    eligibility_checks: Mapped[list['EligibilityCheck']] = relationship(back_populates='match')
    business_plans: Mapped[list['BusinessPlan']] = relationship(back_populates='match')


class EligibilityCheck(Base):
    __tablename__ = 'eligibility_checks'

    check_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('match_results.match_id'))
    passed: Mapped[bool] = mapped_column(Boolean)

    # db_review_response.md 2장 (B)-1 대응. 기능정의서의 GateResult는 passed 하나로는
    # 못 담는 두 가지를 요구한다:
    #   - undecidable: 공고문 자체가 정형화 실패라 "판정 불가"인 경우(E-G1-UNPARSED).
    #     이건 "불통과"(E-G1-REJECT, 진짜 자격 미달)와 사용자에게 보여줄 문구도 후속
    #     처리도 달라야 해서, undecidable=True일 땐 passed 값은 의미 없는 값(False)으로
    #     채워 넣고 이 플래그로 구분한다 — 기존 passed 컬럼 타입은 그대로 둬서(bool),
    #     이미 passed만 보고 있던 기존 코드를 깨지 않는다.
    #   - failed_conditions / missing_inputs: 불통과 사유 목록과 되묻기 대상 목록.
    #     MySQL/SQLite 둘 다 되는 JSON 컬럼으로 저장 — 예: failed_conditions는
    #     ["ageMax 초과", "regionCodes 불일치"] 같은 문자열 리스트를 그대로 넣는다.
    failed_conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing_inputs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    undecidable: Mapped[bool] = mapped_column(Boolean, default=False)

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
    proofread_logs: Mapped[list['ProofreadLog']] = relationship(back_populates='plan')
    format_findings: Mapped[list['FormatFinding']] = relationship(back_populates='plan')


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

    # db_review_response.md 2장 (B)-2 대응. T-V1 성공 조건은 "모든 채점 항목에 점수와
    # evidenceLocator가 함께 출력"이고, E-V1-EVIDENCE는 "evidenceLocator 없는 감점은
    # 무효 처리하고 점수를 복원한다"고 명시한다 — 즉 evidence_locator는 감점의 유효성을
    # 좌우하는 값이라 reason_text(자유 텍스트)만으로는 부족하다. 항목 단위로 쪼갠다.
    #   - item_code: rubric_items.item_code(아래 RubricItem)와 1:1 대응하는 채점 항목 코드.
    #     지금 당장은 어느 RubricItem인지 FK로 강제하지 않고 문자열만 둔다 — rubric_items가
    #     이번에 막 생겨서 기존 문항 코드 체계가 아직 안 잡혀 있기 때문(넣고 싶으면 나중에
    #     FK 추가). 기존 reason_text 전용 행(항목 단위로 안 쪼개는 경우)도 계속 쓸 수 있게
    #     전부 nullable로 둔다.
    item_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    evidence_locator: Mapped[str | None] = mapped_column(String(500), nullable=True)

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

    # PlanScoreReason과 같은 이유(db_review_response.md 2장 (B)-2) — 여기서는 T-B2
    # FeatureMatchResult.missingFeatures(계획서엔 있는데 프로토타입엔 없는 기능)처럼
    # 항목 단위 근거가 필요하다. item_code에 어떤 기능/체크 항목인지, evidence_locator에
    # 어디서 그렇게 판단했는지(코드 경로, 화면 위치 등)를 넣는다.
    item_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    evidence_locator: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
# 표현 검수 (화면 10 — STAGE_REVIEWING, 기능정의서 T-P1/T-P2)
# ---------------------------------------------------------------------------
# db_review_response.md에서 짚었던 대로, 검수 단계(T-P1 문장 형식 검수, T-P2 윤문)의
# 산출물을 담을 테이블이 아예 없었다. 둘 다 business_plans 문서를 대상으로 하고,
# 어느 섹션에서 나온 결과인지 알면 좋아서 plan_sections에도 nullable FK를 걸어둔다
# (Agent가 섹션 단위로 결과를 못 주면 그냥 NULL로 두면 됨).
class FormatFinding(Base):
    """T-P1(문장 형식 검수) 결과 — 문장부호/띄어쓰기/문체 불일치 같은 "형식" 문제를
    지적만 하고 고치지는 않는 항목. 실제로 고친 결과는 ProofreadLog 쪽에 남는다."""
    __tablename__ = 'format_findings'

    finding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    section_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('plan_sections.section_id'), nullable=True)
    finding_type: Mapped[str] = mapped_column(String(50))  # 예: 'punctuation' | 'spacing' | 'tone_mismatch'
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 근거 위치(문단/문장 스니펫 등)
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 예: 'info' | 'warning'
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped['BusinessPlan'] = relationship(back_populates='format_findings')


class ProofreadLog(Base):
    """T-P2(윤문) 결과 — 실제로 문장을 고친 전/후 텍스트 쌍을 남긴다. FormatFinding이
    "문제를 지적"한다면 이쪽은 "실제로 고친 기록"이라 원문/수정문을 통째로 담는다."""
    __tablename__ = 'proofread_logs'

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    section_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('plan_sections.section_id'), nullable=True)
    original_text: Mapped[str] = mapped_column(_LongText)  # app_schema.sql: LONGTEXT
    corrected_text: Mapped[str] = mapped_column(_LongText)  # app_schema.sql: LONGTEXT
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 왜 고쳤는지(윤문 사유)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped['BusinessPlan'] = relationship(back_populates='proofread_logs')


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

    # 재시도 로그 구분 문제 대응 — FIXED_TASK_SEQUENCE(위)엔 '구현', '검증-1', '검증-2'
    # 처럼 같은 agent_name이 두 번씩 나온다. agent_name만으로는 "구현(프로토타입)이
    # 재시도됐는지 구현(인포그래픽)이 재시도됐는지" 구분이 안 됐던 문제(existing_user_
    # resume_test_report.md에서 지적)를, FIXED_TASK_SEQUENCE의 첫 번째 값(task_key,
    # 예: 'implement_prototype')을 그대로 같이 남기는 걸로 해결한다. 기존 행엔 이 값이
    # 없을 수 있어 nullable로 둔다.
    task_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 같은 task_key 안에서 몇 번째 실행인지(1=최초, 2=재시도 1회차, ...). rerun_type이
    # 'initial'/'rerun'만 구분해서 재시도가 여러 번(verification_policies.rerun_cap
    # 기본 3까지 허용) 있었을 때 서로 구분이 안 됐던 것까지 같이 해결한다.
    attempt_no: Mapped[int] = mapped_column(_UnsignedInt, default=1)

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
    # 기본값 80 — 기능명세 G-02 기준으로 팀 확정(2026-09-13). 예전엔 70으로 돼 있었는데
    # 실제 배포된 DB에 이미 70으로 만들어진 행이 있다면 이 default는 새로 INSERT되는
    # 행에만 적용되니, 기존 행은 관리자 화면(admin-dashboard.html 검증 정책 탭)이나
    # UPDATE verification_policies SET pass_threshold = 80 WHERE ...; 로 직접 맞춰야 한다.
    pass_threshold: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=80)
    rerun_cap: Mapped[int] = mapped_column(_UnsignedInt, default=3)  # app_schema.sql: INT UNSIGNED
    deviation_cap: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=5)
    # 검수(표현) Task 내부에서 보호 토큰(수치/날짜/고유명사/기능명) 위반 문단을 재시도하는
    # 최대 횟수 — rerun_cap(Task 단위 재수행 상한)과는 별개로 관리된다. admin-dashboard.html
    # 목업 기본값 2를 그대로 따름. 2026-09-14 정재희님과 논의 후 컬럼 추가 확정.
    token_retry_cap: Mapped[int] = mapped_column(_UnsignedInt, default=2)  # app_schema.sql: INT UNSIGNED
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class VerificationChecklistItem(Base):
    """R-4(코드 8항목 자동 검증)가 쓰는 체크리스트 — LLM 없이 기계적으로 통과/실패만
    판정하는 항목들(진입 파일 존재 여부 등). 아래 RubricItem과 헷갈리기 쉬운데, 이쪽은
    산출물층(코드) 검증용이고 RubricItem은 문서층(계획서) 채점용으로 대상이 다르다."""
    __tablename__ = 'verification_checklist_items'

    check_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    method: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20))
    weight: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RubricItem(Base):
    """db_review_response.md 2장 (A) 대응 — T-V1(문서층 채점)이 참조하는 "여기에 없는
    기준으로 감점하면 무효"인 고정 채점 기준표. 공고마다 달라지는 값이 아니라 전역
    고정값이라(기능정의서 원문: "Rubric은 전역 고정값") verification_policies와
    비슷한 성격으로 우리 쪽에 둔다 — EligibilityRule/FormSpec/EvalItem(공고별로 달라지는
    값)과 달리 공고 수집팀과 소유권을 따로 맞출 필요가 없어서 이번에 바로 추가했다.

    plan_score_reasons.item_code가 이 테이블의 item_code를 가리키는 게 원칙이지만,
    아직 문항 체계가 막 생긴 단계라 지금 당장 FK로 강제하진 않는다(문자열만 맞추면 됨)."""
    __tablename__ = 'rubric_items'

    rubric_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_code: Mapped[str] = mapped_column(String(50), unique=True)  # plan_score_reasons.item_code와 매칭
    category: Mapped[str] = mapped_column(String(50))  # 예: '문제인식' | '실현가능성' | '성장전략'
    criterion: Mapped[str] = mapped_column(Text)  # 채점 기준 설명
    max_score: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class VerificationScoreHistory(Base):
    __tablename__ = 'verification_score_history'

    history_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    layer: Mapped[str] = mapped_column(String(20))  # doc | code | plan
    score: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2))
    is_rerun: Mapped[bool] = mapped_column(Boolean, default=False)

    # db_review_response.md 2장 (B)-3 대응. G-02/R-6: "층별 배점·Threshold·재수행 상한은
    # 관리자 설정값이므로 판정 시점의 설정값을 함께 기록해야 한다 — 없으면 과거 점수를
    # 재현할 수 없다". db_review_response.md는 policy_id FK 하나면 될 거라고 봤는데,
    # verification_policies는 "운영 중 정책은 1행만 유지, 변경 시 UPDATE로 반영"하는
    # 설계라(app_schema.sql 주석) FK만 걸면 나중에 그 행이 UPDATE될 때 과거 기록이 같이
    # 바뀐 것처럼 보이는 문제가 있다 — FK는 참고용으로만 남기고, 실제로 재현 가능하려면
    # 판정 당시 값 자체를 이 행에 그대로 복사(스냅샷)해둬야 한다.
    policy_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('verification_policies.policy_id'), nullable=True)
    applied_weight: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # layer에 해당하는 weight
    applied_pass_threshold: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    applied_rerun_cap: Mapped[int | None] = mapped_column(_UnsignedInt, nullable=True)

    scored_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    plan: Mapped['BusinessPlan'] = relationship(back_populates='score_history')