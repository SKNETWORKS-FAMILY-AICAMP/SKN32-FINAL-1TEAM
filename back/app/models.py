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
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as MySQLBigInteger
from sqlalchemy.dialects.mysql import INTEGER as MySQLInteger
from sqlalchemy.dialects.mysql import LONGTEXT, MEDIUMBLOB
from sqlalchemy.dialects.mysql import SMALLINT as MySQLSmallInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# app_schema.sql엔 MySQL 전용 타입(LONGTEXT, INT UNSIGNED)으로 선언된 컬럼이 있는데,
# 이 타입들을 그대로 쓰면 SQLite(tests/conftest.py가 만드는 테스트 DB)에서 컴파일 에러가 난다.
# with_variant()로 "MySQL에서는 이 타입, 그 외 방언에서는 원래 제네릭 타입"으로 갈라줘서
# 운영(MySQL)에선 app_schema.sql과 정확히 일치하고, 테스트(SQLite)에선 그대로 동작하게 한다.
_LongText = Text().with_variant(LONGTEXT, 'mysql')
_UnsignedInt = Integer().with_variant(MySQLInteger(unsigned=True), 'mysql')
_UnsignedSmallInt = SmallInteger().with_variant(MySQLSmallInteger(unsigned=True), 'mysql')
_UnsignedBigInt = BigInteger().with_variant(MySQLBigInteger(unsigned=True), 'mysql')
_MediumBlob = LargeBinary().with_variant(MEDIUMBLOB, 'mysql')


# ---------------------------------------------------------------------------
# 공고 수집 스키마 — 읽기 전용 매핑 (mysql_schema.sql 이 정본, 공고 수집 파이프라인팀 소유)
# ---------------------------------------------------------------------------
class Notice(Base):
    """[2026-09-17 정합성 점검 보고서 반영 — embedding 3컬럼 복원] 앞서(같은 날 1차 재검증)
    이근준님의 실제 수집 파이프라인 레포(https://github.com/geunlee00/skn32_test)의
    mysql_schema.sql 원본을 확인해 embedding/embedding_fingerprint/embedding_input_sha256
    3개 컬럼을 "실제 스키마엔 없다"는 이유로 뺐었다. 그런데 기획서 v1.7·요구사항 정의서 v2·
    수집 데이터 보고서(2026-09-16) 3개 원본 문서를 직접 대조하는 정합성 점검을 진행하면서,
    이근준님이 직접 작성한 수집 데이터 보고서(2026-09-16) 원문에 이 3개 컬럼이 실제로
    존재하고 이미 2,153건 전량(결측 0건) 채워져 있으며 공고 매칭·관심 공고 알림에 쓰인다고
    명시돼 있는 것을 확인했다 — GitHub 레포 스냅샷이 이 시점 기준 최신이 아니었던 것으로
    판단해 3개 컬럼을 다시 복원한다.

    이번에 함께 복원/추가한 것:
    - embedding(MEDIUMBLOB), embedding_fingerprint(VARCHAR(128)), embedding_input_sha256
      (CHAR(64)) 3개 컬럼 복원.
    - source_id/schema_version/target_text_status/target_category/region/apply_period_raw/
      apply_url/attachment_discovery_status/source_updated_at_raw/snapshot_at/last_import_id/
      created_at/updated_at 13개는 1차 재검증에서 이미 추가된 상태 그대로 유지.

    앱 코드 어디서도(routers/*.py) Notice.embedding*를 아직 실제로 읽고 쓰지 않는다(grep
    확인, 2026-09-17) — 실제 임베딩 기반 매칭(정형 필터 → BM25 키워드 → 임베딩 유사도 결합
    순위)은 아직 구현되지 않은 상태이고, 이 컬럼이 복원되어야 비로소 그 구현에 착수할 수
    있다."""

    __tablename__ = 'notices'

    # [주의] 실제 mysql_schema.sql에는 source_id/schema_version/target_text_status/
    # attachment_discovery_status/snapshot_at/last_import_id가 NOT NULL(기본값 없음)이다.
    # 하지만 우리 앱은 이 테이블에 절대 쓰지 않는 읽기 전용 소비자이고(파일 상단 docstring
    # 참고), 우리 로컬 테스트/시드 스크립트가 이 값들 없이 최소 필드만으로 Notice를 만드는
    # 기존 관행이 많아서, 매핑에서는 nullable=True로 완화해뒀다 — 실제 운영 DB에서 읽어올
    # 때는 항상 값이 채워져 있을 것이므로 문제가 되지 않는다.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notice_id: Mapped[str] = mapped_column(String(320), unique=True)  # 통합 식별자: source:원본ID
    source: Mapped[str] = mapped_column(String(32))       # kstartup 또는 bizinfo
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)   # 출처 API 원본 공고 ID (source와 함께 unique)
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 정규화 데이터 구조 버전
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(_LongText, nullable=True)  # 사업 개요(HTML 태그 제거 후 저장)
    target_text: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    target_text_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # available 또는 not_available
    target_category: Mapped[str | None] = mapped_column(Text, nullable=True)  # API 제공 지원대상 분류
    exclude_text: Mapped[str | None] = mapped_column(_LongText, nullable=True)  # 제외대상
    age_condition_raw: Mapped[str | None] = mapped_column(Text, nullable=True)  # 업력 조건 원문
    region: Mapped[str | None] = mapped_column(Text, nullable=True)       # API 지원 지역 값
    category: Mapped[str | None] = mapped_column(Text, nullable=True)     # 대분류
    subcategory: Mapped[str | None] = mapped_column(Text, nullable=True)  # 중분류
    # 매칭결과 응답의 "org" 관련 필드 — source에 따라 셋 중 일부만 채워짐(백엔드 결정 8번 참고)
    organizer: Mapped[str | None] = mapped_column(Text, nullable=True)        # K-Startup 공고만
    supervising_org: Mapped[str | None] = mapped_column(Text, nullable=True)  # 기업마당 소관기관
    executing_org: Mapped[str | None] = mapped_column(Text, nullable=True)    # 기업마당 수행기관
    apply_start: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    apply_end: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    apply_period_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 접수기간 원본(JSON)
    apply_period_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # fixed/budget_exhaustion/rolling/until_filled/unknown
    recruitment_status: Mapped[str] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # 지원사업 신청 페이지 URL
    attachment_discovery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # pending_crawl/api_links_available/not_available
    source_updated_at_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # API 원본 수정 시각(JSON)
    issues: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)  # 정규화 경고 목록
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)            # 수집 API 원본 응답 전체
    # [2026-09-17 복원] 정합성 점검 보고서 반영 — 수집 데이터 보고서(2026-09-16) 근거로 복원.
    embedding: Mapped[bytes | None] = mapped_column(_MediumBlob, nullable=True)  # 공고 요약 임베딩(float32 1024차원, 4096바이트)
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 모델·입력구성·차원 지문(예: bge-m3/v1/1024)
    embedding_input_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 임베딩 입력 텍스트 해시(같으면 재계산 안 함)
    snapshot_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)  # 마지막 반영 정규화 파일 생성 시각(UTC)
    last_import_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 마지막 저장한 import_runs.run_id
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class NoticeCondition(Base):
    """[2026-09-17 최종 확인] 하정원님이 실제 공유 DB에서 이 테이블의 컬럼 목록을
    스크린샷으로 직접 확인해줬다 — 더 이상 추정이 아니다. 바로 앞 시도에서
    (https://github.com/geunlee00/skn32_test)의 mysql_schema.sql "main 브랜치" 원본엔
    이 테이블이 안 보여서 "존재 자체가 불확실"이라고 적어놨었는데, 실제로는 존재한다
    (그 레포의 main 브랜치 스냅샷에 반영이 안 됐던 것으로 보인다 — 별도 마이그레이션이나
    다른 브랜치에 있는 듯).

    실제로는 우리가 짐작했던 것보다 훨씬 세밀한 LLM(gpt-4o-mini 추정) 추출 테이블이다 —
    단순 판정값뿐 아니라 "판정 불가/거부된 원문"(age_rejected/amount_rejected), "보정된
    금액"(amount_corrected), "업력 제한 없음" 명시 플래그(no_age_limit), LLM 토큰 사용량
    (prompt_tokens/completion_tokens), 추출 메타데이터(extracted_at/extractor_version/
    input_sha256 — 실제 mysql_schema.sql의 attachment_texts와 같은 패턴)까지 같이 기록한다.
    [2026-09-17 DESCRIBE notice_conditions; 결과로 최종 확정] 정합성 점검 보고서가 uncertain
    타입을 스크린샷(JSON)과 수집 데이터 보고서(TINYINT)가 서로 다르게 말한다고 지적한
    직후, 하정원님이 실제 DESCRIBE notice_conditions; 결과 스크린샷을 받아왔다 — uncertain은
    json(YES, 기본값 NULL)으로 확정. 수집 데이터 보고서 쪽 설명(TINYINT)이 틀렸던 것으로
    결론.

    PK도 이 DESCRIBE 결과로 확정됐다 — notice_id 행의 Key 컬럼에 PRI가 명시되어 있어
    notice_id 자체가 PK라는 점이 더 이상 추정이 아니다(예전엔 키 아이콘/제약조건 표시가
    안 보여 "100% 확정은 아님"이라고 적어뒀었음).

    덤으로 amount_max_won의 Key 컬럼에 MUL(비고유 인덱스)이 걸려 있는 것도 이번에 처음
    확인해서 아래 컬럼에 index=True로 반영했다.

    실제로는 우리가 짐작했던 것보다 훨씬 세밀한 LLM(gpt-4o-mini 추정) 추출 테이블이다 —
    단순 판정값뿐 아니라 "판정 불가/거부된 원문"(age_rejected/amount_rejected), "보정된
    금액"(amount_corrected), "업력 제한 없음" 명시 플래그(no_age_limit), LLM 토큰 사용량
    (prompt_tokens/completion_tokens), 추출 메타데이터(extracted_at/extractor_version/
    input_sha256 — 실제 mysql_schema.sql의 attachment_texts와 같은 패턴)까지 같이 기록한다."""

    __tablename__ = 'notice_conditions'

    notice_id: Mapped[str] = mapped_column(String(320), primary_key=True)  # REFERENCES notices(notice_id) — notices 1건당 1:1. [2026-09-17 DESCRIBE로 확정] PK
    amount_max_won: Mapped[int | None] = mapped_column(_UnsignedBigInt, index=True, nullable=True)  # 최대 지원금액(원). [2026-09-17 확인] DESCRIBE상 MUL(비고유 인덱스)
    amount_rejected: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 금액 조건 판정 불가/거부 사유 원문
    amount_corrected: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # LLM이 원문 대비 보정한 금액 값(JSON)
    business_type: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 신청 가능 사업자 형태
    pre_startup_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 예비창업자 신청 가능 여부
    age_years_min: Mapped[int | None] = mapped_column(_UnsignedSmallInt, nullable=True)
    age_years_max: Mapped[int | None] = mapped_column(_UnsignedSmallInt, nullable=True)
    age_rejected: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 업력 조건 판정 불가/거부 사유 원문
    age_source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)  # 업력 조건 근거 원문(source_quote와 별도)
    no_age_limit: Mapped[bool] = mapped_column(Boolean, default=False)  # 업력 제한 없음이 명시적으로 확인됐는지
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)  # 전체 판정 근거 원문
    uncertain: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # [2026-09-17 DESCRIBE로 확정] json, YES — 필드별 확신도 낮음 표시
    prompt_tokens: Mapped[int | None] = mapped_column(_UnsignedInt, nullable=True)  # LLM 추출 호출의 입력 토큰 수
    completion_tokens: Mapped[int | None] = mapped_column(_UnsignedInt, nullable=True)  # LLM 추출 호출의 출력 토큰 수
    extractor_version: Mapped[str] = mapped_column(String(64))  # 추출기/프롬프트 버전
    input_sha256: Mapped[str] = mapped_column(String(64))  # 추출 입력(공고 원문 등)의 해시 — 재추출 필요 여부 판단용
    extracted_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class ImportRun(Base):
    """[2026-09-18 신규] 공고 수집 파이프라인(mysql_schema.sql, 다른 팀원 소유)이 배치마다
    남기는 실행 기록 — Notice/NoticeCondition과 같은 이유로 읽기 전용 매핑만 한다(이
    앱에서 이 테이블에 쓰지 않음). 관리자 대시보드 "공고 관리" 탭의 "공고 수집 현황"/
    "최근 수집 실행 이력"이 이 테이블을 읽어 실제 배치 결과(출처별 입력 건수, 데이터
    품질 이슈 집계)를 보여준다(app/routers/admin.py list_collection_status 참고)."""

    __tablename__ = 'import_runs'

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    input_sha256: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    imported_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    notice_count: Mapped[int] = mapped_column(_UnsignedInt)
    report: Mapped[dict] = mapped_column(JSON)


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
    # [2026-09-17] 얼굴 인증(face_verified_at) 게이트를 팀 결정으로 완전히 뺐다 — AWS
    # 공유 DB에 아직 이 스키마가 올라가지 않은 시점이라 컬럼 자체를 지웠다(예전엔 로직만
    # 빼고 컬럼은 호환성 때문에 남겨뒀었음). admin.py에서 role='admin' 전환에 더 이상
    # 아무 조건도 걸지 않는다.

    companies: Mapped[list['Company']] = relationship(back_populates='user')
    faqs: Mapped[list['Faq']] = relationship(back_populates='user')


class RefreshToken(Base):
    """Access Token(JWT, security.py의 sbrain_session 쿠키)과 분리된 Refresh Token 저장소.
    Access Token은 stateless JWT라 서버가 만료 전엔 무효화할 방법이 없어서, 로그아웃이
    "쿠키만 지우기"에 그쳤었다(토큰 자체는 만료 전까지 여전히 유효) — Refresh Token을 여기
    DB에 저장해두면 로그아웃 시 이 행을 revoked_at으로 막아 재발급(POST /auth/refresh)을
    실제로 끊을 수 있다. 토큰 원문은 저장하지 않고 SHA-256 해시만 저장한다(DB가 유출돼도
    원문 재구성 불가, security.py의 _hash_token 참고).

    재발급마다 이전 토큰은 즉시 revoke하고 새 토큰을 발급하는 회전(rotation) 방식을 쓴다 —
    rotated_to_id로 교체 이력을 남겨두면, 이미 폐기된(rotated) 토큰 원문이 다시 쓰이는
    경우(탈취 후 재사용 시도) 나중에 감지할 단서가 된다."""
    __tablename__ = 'refresh_tokens'

    token_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.user_id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 hex digest
    issued_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    rotated_to_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey('refresh_tokens.token_id'), nullable=True
    )

    user: Mapped['User'] = relationship()


# ---------------------------------------------------------------------------
# 회사(예비창업자/기업 프로필) / 아이템(지원 아이템)
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = 'companies'

    company_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # [2026-09-15 개정] 예전엔 여기 unique=True를 걸어 "계정당 회사 프로필 1건"을 DB로
    # 강제하고, 그 유일한 행을 POST /projects 동시 실행 제한(기획서 4-7, backend_decisions.md
    # #11)의 락 대상으로도 같이 썼다 — 그런데 그러면 프로젝트마다 다른 신청자 유형/대표자명/
    # 설립일자를 입력해도 두 번째 프로젝트부터 값이 조용히 무시되는 부작용이 있었다(회사
    # 프로필이 project 1건과 매칭되는 게 아니라 계정과 매칭되니까). 동시 실행 제한은 이제
    # User 행 자체를 잠그는 방식으로 분리했으므로(app/routers/projects.py의 create_project),
    # 여기 unique 제약은 더 이상 그 락의 전제조건이 아니다 — 프로젝트마다 회사 프로필을
    # 새로 만들 수 있도록 제거한다. user_id로 조회는 여전히 자주 하니 인덱스는 남긴다.
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.user_id'), index=True)
    # [2026-09-17 삭제] IntakeForm.jsx에 이 값을 물어보는 입력칸이 아예 없어서 App.jsx가
    # 항상 '온라인' 고정값을 채워 보내고 있었다(하정원님 지적으로 발견, "지워" 지시에 따라
    # ProjectCreateRequest에서 필드 삭제) — 컬럼은 남겨두되 NULL을 허용해서 기존 행/코드가
    # 깨지지 않게 했다. 나중에 진짜 입력칸이 생기면 다시 required로 되돌리면 된다.
    # [2026-09-17 배선] IntakeForm.jsx가 필수로 물어보는 "신청자 유형"이 요청 바디에도
    # 안 실리고 컬럼도 없어서 그동안 화면에서 고른 값이 저장 안 되고 버려지고 있었다.
    applicant_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # preliminary/individual/corp
    biz_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ceo_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    founded_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)

    # [2026-09-17 신규] 마이페이지(프로필 저장/재사용, 사업자등록번호 자동조회) 지원용 —
    # app_schema.sql의 companies 테이블 주석 참고.
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_reg_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rep_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 단독/공동/각자대표
    # [2026-09-18 삭제] is_saved_profile/biz_reg_lookup_raw/biz_reg_lookup_checked_at은
    # "마이페이지 프로필 저장/재사용"을 companies 테이블에 붙이려던 예전 설계의 흔적이다 —
    # 그 기능은 실제로 별도 API 없이 방치돼 있었고(schemas.py에 "후속 작업"이라고만 적혀
    # 있었음), 이번에 완전히 다른 테이블(user_profiles v2, app/routers/profile.py)로
    # 구현되면서 이 3개 컬럼은 영구 미아가 됐다 — 어디서도 읽거나 쓰지 않아 제거.

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

    # [2026-09-17 신규] 계획서 공식 양식(별첨1)이 요구하는데 저장할 곳이 없던 나머지 항목 —
    # app_schema.sql의 projects 테이블 주석 참고.
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tech_field: Mapped[str | None] = mapped_column(String(100), nullable=True)
    regional_priority_area: Mapped[str | None] = mapped_column(String(100), nullable=True)

    company: Mapped['Company'] = relationship(back_populates='projects')
    attachments: Mapped[list['ProjectAttachment']] = relationship(back_populates='project')
    team_members: Mapped[list['TeamMember']] = relationship(back_populates='project')
    pricing_items: Mapped[list['PricingItem']] = relationship(back_populates='project')
    budget_items: Mapped[list['ProjectBudgetItem']] = relationship(back_populates='project')
    schedule_items: Mapped[list['ProjectScheduleItem']] = relationship(back_populates='project')
    partners: Mapped[list['ProjectPartner']] = relationship(back_populates='project')
    matches: Mapped[list['MatchResult']] = relationship(back_populates='project')


class ProjectAttachment(Base):
    __tablename__ = 'project_attachments'

    attachment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(500))

    # [2026-09-17 신규] 원본(file_url)과 파싱 결과를 분리 — app_schema.sql의
    # project_attachments 테이블 주석 참고 (재시도 안정성 + 마크다운화 재사용).
    parsed_markdown: Mapped[str | None] = mapped_column(_LongText, nullable=True)
    parse_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

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


class ProjectBudgetItem(Base):
    """pricing_items(사업 아이템 자체의 수익모델 단가)와는 다른 개념이다 — 이건 지원사업
    사업비를 비목별로 어떻게 집행할지(정부지원사업비/자기부담금 구분)를 담는다.
    plan_document_export.py의 BudgetLineItem과 1:1 대응 (app_schema.sql 주석 참고)."""

    __tablename__ = 'project_budget_items'

    budget_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    item_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 비목
    execution_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    government_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    self_cash_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    self_in_kind_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    project: Mapped['Project'] = relationship(back_populates='budget_items')


class ProjectScheduleItem(Base):
    """계획서 양식의 "실현가능성 추진일정"/"성장전략 추진일정"(ScheduleRow) — 두 섹션 다
    구조가 같아서 section으로만 구분하고 테이블은 하나로 합쳤다."""

    __tablename__ = 'project_schedule_items'

    schedule_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    section: Mapped[str] = mapped_column(String(20))  # feasibility=실현가능성 / growth=성장전략
    item_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 구분
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 추진내용
    period: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 추진기간
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # 세부내용

    project: Mapped['Project'] = relationship(back_populates='schedule_items')


class ProjectPartner(Base):
    """계획서 양식의 "협력기관"(PartnerRow)."""

    __tablename__ = 'project_partners'

    partner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    item_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capability: Mapped[str | None] = mapped_column(Text, nullable=True)  # 보유역량
    collaboration_plan: Mapped[str | None] = mapped_column(Text, nullable=True)  # 협업방안
    collaboration_timing: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 협력시기

    project: Mapped['Project'] = relationship(back_populates='partners')


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


class MatchCandidate(Base):
    """GET /projects/{id}/match-candidates 가 보여준 공고 후보. 한 번 뽑은 후보를 저장해 두어야
    새로고침해도 같은 목록이 나오고, 재실행(batch=2)을 서버가 프로젝트당 1회로 강제할 수 있다."""

    __tablename__ = 'match_candidates'

    candidate_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('projects.project_id'))
    notice_id: Mapped[str] = mapped_column(String(320), ForeignKey('notices.notice_id'))
    batch: Mapped[int] = mapped_column(SmallInteger)  # 1=첫 매칭, 2=재실행
    bonus_score: Mapped[decimal.Decimal] = mapped_column(Numeric(4, 1))  # 공고별 가산점(만점 기준 없음)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


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
    score_reasons: Mapped[list['MatchScoreReason']] = relationship(back_populates='match')


class MatchScoreReason(Base):
    """멘토링 피드백 "매칭 근거는 정성적 설명보다 '+2점' 같은 정량 점수로 표시하는 게 더
    설득력 있음" 반영. PlanScoreReason/ArtifactScoreReason과 똑같은 모양이다 — match_results.
    reason(자유 텍스트 하나)만으로는 항목별 점수를 못 보여줘서 매칭 단계에도 이 테이블을 둔다."""

    __tablename__ = 'match_score_reasons'

    reason_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('match_results.match_id'))
    reason_text: Mapped[str] = mapped_column(Text)
    item_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    evidence_locator: Mapped[str | None] = mapped_column(String(500), nullable=True)

    match: Mapped['MatchResult'] = relationship(back_populates='score_reasons')


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
    "문제를 지적"한다면 이쪽은 "실제로 고친 기록"이라 원문/수정문을 통째로 담는다.

    [2026-09-18 확장] "1차 시도 반려 → 2차 시도 통과" 같은 시도별 판정을 표현 검수 화면에
    보여주려면(사용자가 보여준 화면 예시 — p-09처럼 원문의 수치·날짜가 훼손된 1차 시도가
    반려되고, 그 값을 그대로 보존한 2차 시도가 통과하는 과정) 시도 번호·통과 여부·반려
    사유가 필요한데 기존 컬럼(original_text/corrected_text/reason)만으로는 "이 행이 몇
    번째 시도였는지", "왜 반려됐는지"를 구분할 수 없었다. attempt_no는 AgentExecution과
    같은 패턴(같은 plan_id+section_id 안에서 1부터 증가) — 재시도할 때마다 기존 행을
    덮어쓰지 않고 새 행을 추가해 이력을 보존한다(app/routers/projects.py retry_task
    참고). passed=False인 행은 corrected_text에 "반려된 시도안"이 담기고, violation_note에
    반려 사유(보호 토큰 중 무엇이 어떻게 바뀌었는지)가 채워진다 — 검수 통과본이 아니라는
    뜻이므로 실제 계획서 본문 갱신에는 반영하지 않는다.

    violation_type/recovery_status/recovery_label 3컬럼은 관리자 대시보드 "검수 회수
    문단" 탭용이다 — passed=False인 행(보호 토큰 위반으로 반려된 시도)이 곧 그 탭의
    라벨링 대상 후보다. violation_type은 위반 종류(날짜/수치·금액/고유명사/기능명),
    recovery_status는 사람이 그 반려 사례를 검토했는지(pending/labeled/excluded),
    recovery_label은 라벨링 완료 시 사람이 정리해 남긴 정답 문장이다. passed=True인
    행에는 이 3컬럼이 다 NULL이다(라벨링 대상이 아니므로).

    [2026-09-18 추가] score — 그동안 passed(통과/반려) 불리언만 있어서 "재시도할수록
    실제로 나아지고 있는지"를 숫자로 확인할 방법이 없었다(하정원님 지적). business_plans.
    doc_score/artifacts.artifact_score와 같은 형식(0~100, 소수 둘째 자리까지)으로 맞춘다."""
    __tablename__ = 'proofread_logs'

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('business_plans.plan_id'))
    section_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('plan_sections.section_id'), nullable=True)
    original_text: Mapped[str] = mapped_column(_LongText)  # app_schema.sql: LONGTEXT
    corrected_text: Mapped[str] = mapped_column(_LongText)  # app_schema.sql: LONGTEXT
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 왜 고쳤는지(윤문 사유)
    attempt_no: Mapped[int] = mapped_column(_UnsignedInt, default=1)  # 같은 plan_id+section_id 안에서 몇 번째 시도인지(1=최초)
    score: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), default=decimal.Decimal('100'))
    passed: Mapped[bool] = mapped_column(Boolean, default=True)  # False면 보호 토큰 위반으로 반려된 시도
    violation_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 반려 사유(passed=False일 때만) — 예: "'2026년 10월 16일' 누락, '1억원'이 '100,000,000원'으로 표기 변경됨"
    violation_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 날짜/수치·금액/고유명사/기능명 (passed=False일 때만)
    recovery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pending/labeled/excluded (passed=False일 때만)
    recovery_label: Mapped[str | None] = mapped_column(Text, nullable=True)  # 라벨링 완료 시 사람이 정리한 정답 문장
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
# 마이페이지 프로필 (계정 단위, 슬롯형 — SB-59 v2)
# ---------------------------------------------------------------------------
class UserProfile(Base):
    """[2026-09-18 v2, 정재희님 프론트 커밋(front/src/store/useMyPageStore.js) 반영] 계정당
    최대 3개까지 독립된 정보 슬롯을 둘 수 있게 바뀌었다(예: 아이템별로 다른 신청자 정보) —
    v1(계정당 1행, user_id UNIQUE)은 이 다중 슬롯 구조와 근본적으로 안 맞아 DROP 후 재생성
    했다(마이그레이션 시점 0행이라 데이터 손실 없음). 최대 개수(3)는 여기서 강제하지 않고
    app/routers/profile.py에서 체크한다(단순 COUNT 쿼리라 컬럼/제약보다 여기서 보는 게 쉬움).

    v1에 있던 applicant_type/birth_date/gender/biz_no/opened_at/start_type/home_sido/
    hq_sido "판정용 컬럼"은 실제로 매칭·자격요건 판정 코드 어디에서도 읽힌 적이 없어서(grep
    확인 — company.applicant_type과는 별개) v2에서 뺐다. 필요해지면 그때 basic_json에서
    뽑아 컬럼화하면 된다. history_json(재창업 이력)도 마찬가지로 뺐다 — 새 프론트가 재창업
    이력을 더 이상 추적하지 않는다(신청자 유형 하나로만 화면이 갈림, useMyPageStore.js 주석).

    companies 테이블은 쓰지 않는다 — companies는 프로젝트마다 새로 생기는 스냅샷이고, 이
    테이블은 프로젝트와 무관하게 계정 자체에 딸린 프로필이라 성격이 다르다.

    basic_json/capability_json은 프론트 스토어의 profile.basic/profile.capability를
    원본 그대로 저장한다(변환 코드 불필요).

    biz_checked_no/biz_status_cd/biz_tax_type/biz_checked_at 4개는 POST /biz-check(국세청
    상태조회) 성공 시에만, 그 조회가 어느 슬롯에서 일어났는지(profile_id) 요청 바디로 받아
    해당 슬롯에만 서버가 채운다 — PUT 바디의 basic에 bizStatus가 섞여 와도 무시한다
    (클라이언트가 "계속사업자" 상태를 조작해서 보낼 수 없게). 저장한 bizNo가 이
    biz_checked_no와 달라지면 재조회 전까지 이 4개 컬럼을 NULL로 비운다.
    """
    __tablename__ = 'user_profiles'

    profile_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.user_id'))
    name: Mapped[str] = mapped_column(String(50), default='정보 1', server_default='정보 1')

    basic_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    capability_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    biz_checked_no: Mapped[str | None] = mapped_column(String(10), nullable=True)
    biz_status_cd: Mapped[str | None] = mapped_column(String(2), nullable=True)  # 01 계속/02 휴업/03 폐업
    biz_tax_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    biz_checked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped['User'] = relationship()


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