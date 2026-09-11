-- S-Brain 서비스 앱 스키마 (schema_version=2).
-- "SK 네트웍스 Family AI 32기 1팀 데이터베이스_저장소 설계 문서"(정재희·하정원, 2026-09-09,
-- 최종 수정 2026-09-09)의 논리/물리 데이터 모델을 그대로 DDL로 옮긴 것이다.
-- mysql_schema.sql(공고 수집 파이프라인 — notices/notice_attachments/import_runs)에 이어서 붙인다.
-- 기존 테이블은 절대 재정의하지 않고, 없는 테이블만 생성한다(CREATE TABLE IF NOT EXISTS).
-- 실행 순서: mysql_schema.sql 먼저 적용 → 이 파일. notices(notice_id UNIQUE)를 FK로 참조하기 때문.
--
-- [주의 — 설계 문서와 실제 수집 스키마의 차이]
-- 설계 문서의 notices 테이블은 notice_id(VARCHAR(320))를 PK로 그린 단순화된 논리 모델이지만,
-- 실제 mysql_schema.sql은 id(BIGINT AUTO_INCREMENT)가 PK이고 notice_id는 별도 UNIQUE 컬럼이다.
-- notice_id가 UNIQUE 인덱스이므로 FK 대상으로는 문제없이 쓸 수 있어, 이 파일의 모든 notices 참조는
-- notices(notice_id)를 그대로 가리키게 했다. 다만 설계 문서에는 있는 embedding_status/
-- embedding_updated_at/embedding_fail_reason 컬럼은 실제 notices 테이블에는 아직 없다 —
-- 이 앱에서 추가하지 않았으니, 임베딩 상태 추적이 필요해지면 수집 파이프라인 쪽에서 별도 반영이 필요하다.

-- ---------------------------------------------------------------------------
-- 사용자
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사용자 고유 식별자',
    email VARCHAR(255) NOT NULL COMMENT '로그인 이메일(Google 계정)',
    name VARCHAR(100) NOT NULL COMMENT '사용자 이름',
    google_sub VARCHAR(255) NOT NULL COMMENT 'Google OAuth 식별자(sub)',
    notify_enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT '유사 공고 알림 on/off 전역 설정',
    role VARCHAR(20) NOT NULL DEFAULT 'user' COMMENT '권한(user/admin)',
    status VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT '계정 상태(active/suspended/dormant)',
    face_verified_at DATETIME(6) NULL COMMENT '관리자 권한 전환 시 얼굴 등록 완료 일시(NULL 가능)',
    UNIQUE KEY uq_users_email (email),
    UNIQUE KEY uq_users_google_sub (google_sub)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 회사(예비창업자/기업 프로필) / 아이템(지원 아이템) 및 하위 정보
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    company_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '예비창업자/기업 프로필 고유 식별자',
    user_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES users(user_id)',
    start_type VARCHAR(32) NOT NULL COMMENT '시작 유형(온라인/오프라인/전자상거래 등)',
    biz_type VARCHAR(100) NULL COMMENT '업종',
    ceo_name VARCHAR(100) NULL COMMENT '대표자명',
    founded_at DATE NULL COMMENT '설립일(예비창업자는 NULL 가능)',
    KEY ix_companies_user (user_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS items (
    item_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '지원 아이템(사업 아이디어) 고유 식별자',
    company_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES companies(company_id)',
    description TEXT NOT NULL COMMENT '아이템 설명(사용자가 입력한 사업 아이디어 서술)',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '등록 일시',
    notify_region VARCHAR(32) NOT NULL COMMENT '유사 공고 알림 대상 소재 지역',
    notify_industry VARCHAR(32) NOT NULL COMMENT '유사 공고 알림 대상 업종',
    KEY ix_items_company (company_id),
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS item_attachments (
    attachment_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '첨부파일 고유 식별자',
    item_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES items(item_id)',
    file_name VARCHAR(255) NOT NULL COMMENT '첨부파일 원본 파일명',
    file_url VARCHAR(500) NOT NULL COMMENT '첨부파일 저장 경로/URL',
    KEY ix_item_attachments_item (item_id),
    FOREIGN KEY (item_id) REFERENCES items(item_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS team_members (
    member_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '팀원 고유 식별자',
    item_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES items(item_id)',
    name VARCHAR(100) NOT NULL COMMENT '팀원 이름',
    role VARCHAR(100) NULL COMMENT '담당 역할',
    experience TEXT NULL COMMENT '경력/역량 서술(자유 서술, NULL 가능)',
    KEY ix_team_members_item (item_id),
    FOREIGN KEY (item_id) REFERENCES items(item_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS pricing_items (
    pricing_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '단가 항목 고유 식별자',
    item_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES items(item_id)',
    service_name VARCHAR(255) NOT NULL COMMENT '서비스/상품명',
    unit_price DECIMAL(12,2) NULL COMMENT '단가(원, NULL 가능)',
    KEY ix_pricing_items_item (item_id),
    FOREIGN KEY (item_id) REFERENCES items(item_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 유사 공고 알림 / 매칭 / 자격요건 게이트
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notice_alerts (
    alert_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '유사 공고 알림 고유 식별자',
    item_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES items(item_id)',
    notice_id VARCHAR(320) NOT NULL COMMENT 'REFERENCES notices(notice_id)',
    similarity_score DECIMAL(5,2) NOT NULL COMMENT '임베딩 기반 유사도 점수',
    detected_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '알림 감지 일시',
    KEY ix_notice_alerts_item (item_id),
    KEY ix_notice_alerts_notice (notice_id),
    FOREIGN KEY (item_id) REFERENCES items(item_id) ON DELETE CASCADE,
    FOREIGN KEY (notice_id) REFERENCES notices(notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS match_results (
    match_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '매칭 결과 고유 식별자',
    item_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES items(item_id)',
    notice_id VARCHAR(320) NOT NULL COMMENT 'REFERENCES notices(notice_id)',
    fit_score DECIMAL(5,2) NULL COMMENT '매칭 적합도 점수',
    reason TEXT NULL COMMENT '매칭 사유/근거 서술',
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress' COMMENT '프로젝트 진행 상태(in_progress/completed/halted)',
    archived_at DATETIME(6) NULL COMMENT '사용자가 프로젝트를 삭제해 보관 처리된 일시(NULL 가능)',
    archived_by VARCHAR(20) NULL COMMENT "보관 처리 주체('user' 고정, NULL 가능)",
    KEY ix_match_results_item (item_id),
    KEY ix_match_results_notice (notice_id),
    FOREIGN KEY (item_id) REFERENCES items(item_id) ON DELETE CASCADE,
    FOREIGN KEY (notice_id) REFERENCES notices(notice_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS eligibility_checks (
    check_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '자격요건 게이트 결과 고유 식별자',
    match_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES match_results(match_id)',
    passed BOOLEAN NOT NULL COMMENT '자격요건 통과 여부',
    checked_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '검증 일시',
    KEY ix_eligibility_checks_match (match_id),
    FOREIGN KEY (match_id) REFERENCES match_results(match_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 사업계획서(문서층) 및 산출물(산출물층), 최종 판정
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS business_plans (
    plan_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사업계획서 고유 식별자',
    match_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES match_results(match_id)',
    doc_score DECIMAL(5,2) NULL COMMENT '문서 적합도 점수(작성 Agent 산출)',
    threshold DECIMAL(5,2) NULL COMMENT '통과 기준 점수',
    KEY ix_business_plans_match (match_id),
    FOREIGN KEY (match_id) REFERENCES match_results(match_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS plan_sections (
    section_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '계획서 섹션 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    tag VARCHAR(16) NOT NULL COMMENT 'PSST 구분(P/S/S/T)',
    title VARCHAR(255) NOT NULL COMMENT '섹션 제목',
    body LONGTEXT NULL COMMENT '섹션 본문',
    KEY ix_plan_sections_plan (plan_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS plan_score_reasons (
    reason_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사유 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    reason_text TEXT NOT NULL COMMENT '문서 적합도 판단 사유',
    KEY ix_plan_score_reasons_plan (plan_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '산출물(구현 Agent 결과) 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    category VARCHAR(32) NOT NULL COMMENT '산출물 카테고리(onepage/webdev/aiapi)',
    infographic_path VARCHAR(500) NOT NULL COMMENT '인포그래픽 파일 경로',
    executable_path VARCHAR(500) NULL COMMENT '실행 파일 경로(원페이지형은 NULL)',
    artifact_score DECIMAL(5,2) NULL COMMENT '산출물 적합도 점수',
    KEY ix_artifacts_plan (plan_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS artifact_score_reasons (
    reason_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사유 고유 식별자',
    artifact_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES artifacts(artifact_id)',
    reason_text TEXT NOT NULL COMMENT '산출물 적합도 판단 사유',
    KEY ix_artifact_score_reasons_artifact (artifact_id),
    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '최종 판정 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    artifact_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES artifacts(artifact_id)',
    overall_passed BOOLEAN NOT NULL COMMENT '문서층·산출물층 통과 여부 종합 판정',
    model_version VARCHAR(50) NOT NULL COMMENT '검수(표현) 자체 파인튜닝 모델 버전(v1/v2/v3)',
    first_pass_passed BOOLEAN NOT NULL COMMENT '재시도 없이 1차 검수에서 통과했는지 여부',
    KEY ix_verdicts_plan (plan_id),
    KEY ix_verdicts_artifact (artifact_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- FAQ
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS faqs (
    faq_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT 'FAQ 고유 식별자',
    user_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES users(user_id)',
    question TEXT NOT NULL COMMENT '질문 원문',
    answer TEXT NULL COMMENT '답변 원문(NULL 가능, 답변 전)',
    is_visible BOOLEAN NOT NULL DEFAULT FALSE COMMENT '노출 여부(답변 저장 전에는 전환 불가)',
    answered_at DATETIME(6) NULL COMMENT '답변 저장 일시(NULL 가능)',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '질문 등록 일시',
    KEY ix_faqs_user (user_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 에이전트 실행 로그 (관리자 대시보드 "에이전트 테스크" 탭)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_executions (
    execution_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '에이전트 실행 세션 고유 식별자',
    match_id BIGINT UNSIGNED NULL COMMENT 'REFERENCES match_results(match_id), nullable',
    agent_name VARCHAR(50) NOT NULL COMMENT '실행 Agent 이름(조율/전략/작성/구현/검증-1/검증-2/검수)',
    model_used VARCHAR(50) NOT NULL COMMENT '사용 모델명(Claude Opus/Sonnet/Haiku 또는 자체 파인튜닝 모델 버전)',
    rerun_type VARCHAR(20) NOT NULL COMMENT '최초 실행/선별 재수행/전체 재실행 구분',
    token_usage INT UNSIGNED NOT NULL COMMENT '실행에 사용된 토큰 수',
    status VARCHAR(20) NOT NULL COMMENT '실행 결과 상태(성공/실패)',
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '실행 시작 일시',
    KEY ix_agent_executions_match (match_id),
    FOREIGN KEY (match_id) REFERENCES match_results(match_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 검증 정책 (admin-dashboard.html 검증 정책 탭)
-- ---------------------------------------------------------------------------
-- 설계 문서 6번 표: "단일 행 제약 — 운영 중 정책은 1행만 유지, 변경 시 UPDATE로 반영".
-- DB 레벨 CHECK는 명시돼 있지 않아 걸지 않았고(문서 원안 그대로), 앱 레벨에서
-- 항상 policy_id 최솟값(=최초 생성된 1행)만 조회/갱신하도록 라우터에서 강제한다.
CREATE TABLE IF NOT EXISTS verification_policies (
    policy_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '검증 정책 설정 고유 식별자',
    doc_weight DECIMAL(5,2) NOT NULL DEFAULT 70 COMMENT '2차 검증 배점 - 문서층',
    code_weight DECIMAL(5,2) NOT NULL DEFAULT 15 COMMENT '2차 검증 배점 - 코드 기준 자동 검증',
    plan_weight DECIMAL(5,2) NOT NULL DEFAULT 15 COMMENT '2차 검증 배점 - 계획서 대조',
    pass_threshold DECIMAL(5,2) NOT NULL DEFAULT 70 COMMENT '통과 Threshold(100점 만점 기준)',
    rerun_cap INT UNSIGNED NOT NULL DEFAULT 3 COMMENT 'Threshold 미달 시 자동 재수행 최대 횟수',
    deviation_cap DECIMAL(5,2) NOT NULL DEFAULT 5 COMMENT '문서층 재채점 편차 상한(경고 알림 기준)',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '정책 마지막 수정 일시'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO verification_policies (policy_id)
SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM verification_policies);

CREATE TABLE IF NOT EXISTS verification_checklist_items (
    check_item_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '코드 기준 자동 검증 항목 고유 식별자',
    name VARCHAR(100) NOT NULL COMMENT '검증 항목명(예: 실행 파일 정상 로드)',
    method TEXT NOT NULL COMMENT '판정 방식 설명(파싱/계산 기준)',
    category VARCHAR(20) NOT NULL COMMENT '구분(정적분석/실행검증)',
    weight DECIMAL(5,2) NOT NULL COMMENT '가중치 점수',
    enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT '사용 여부(해제 시 채점에서 제외)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO verification_checklist_items (name, method, category, weight, enabled)
SELECT * FROM (SELECT
    '실행 파일 정상 로드' AS name, '파일 존재 여부 + 브라우저 렌더링 성공 여부 확인' AS method, '정적분석' AS category, 30.00 AS weight, TRUE AS enabled
    UNION ALL SELECT '반응형 레이아웃 구현', 'viewport meta·media query 존재 여부 파싱', '정적분석', 20.00, TRUE
    UNION ALL SELECT '접근성 기본 준수', 'alt 속성·시맨틱 태그·명도 대비 파싱', '정적분석', 20.00, TRUE
    UNION ALL SELECT '콘솔 에러 없음', '브라우저 콘솔 로그 스캔', '실행검증', 20.00, TRUE
    UNION ALL SELECT '인포그래픽 포함 여부', '이미지·SVG 파일 존재 여부 파싱', '정적분석', 10.00, FALSE
) seed
WHERE NOT EXISTS (SELECT 1 FROM verification_checklist_items);

CREATE TABLE IF NOT EXISTS verification_score_history (
    history_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '점수 이력 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    layer VARCHAR(20) NOT NULL COMMENT '채점 층 구분(doc/code/plan)',
    score DECIMAL(5,2) NOT NULL COMMENT '해당 회차 점수',
    is_rerun BOOLEAN NOT NULL DEFAULT FALSE COMMENT '재수행에 의한 재채점 여부',
    scored_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '채점 일시',
    KEY ix_verification_score_history_plan (plan_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;