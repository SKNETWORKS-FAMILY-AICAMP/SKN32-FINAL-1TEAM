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
--
-- [2026-09-17 인덱싱 개정 — 읽기 위주 구조 반영]
-- 이 서비스는 쓰기(등록/갱신)보다 읽기(목록·대시보드·재시도 조회)가 훨씬 잦다. app/routers/*.py
-- 전체를 grep해서 실제 order_by()/filter() 패턴을 확인하고, 그 패턴을 못 커버하던 컬럼에만
-- 인덱스를 추가/교체했다(무작정 다 걸지 않음 — 쓰기 비용과 트레이드오프). 상세 근거는 각 테이블
-- 정의 옆 주석 참고. 요약: projects(company_id+created_at 복합, created_at 단일 추가),
-- plan_sections(plan_id+tag 복합), agent_executions(match_id+task_key+attempt_no 복합),
-- faqs(is_visible+created_at 복합 신규), match_results(status 단일 신규). match_id/plan_id/
-- artifact_id 등 "FK로 필터 + PK로 정렬"류는 InnoDB가 보조 인덱스 리프에 PK를 항상 포함하는
-- 특성상 기존 단일 컬럼 인덱스만으로 이미 커버돼서 손대지 않았다.

-- ---------------------------------------------------------------------------
-- 사용자
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사용자 고유 식별자',
    email VARCHAR(255) NOT NULL COMMENT '로그인 이메일(Google 계정)',
    name VARCHAR(100) NOT NULL COMMENT '사용자 이름',
    google_sub VARCHAR(255) NOT NULL COMMENT 'Google OAuth 식별자(sub)',
    notify_enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT '유사 공고 알림 on/off 전역 설정',
    ai_training_agreed BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'AI 학습 데이터 활용 동의(연동합의서 #3) — 로그인마다 갱신',
    role VARCHAR(20) NOT NULL DEFAULT 'user' COMMENT '권한(user/admin)',
    status VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT '계정 상태(active/suspended/dormant)',
    -- [2026-09-17] 얼굴 인증(face_verified_at) 게이트를 팀 결정으로 완전히 뺐다(admin.py
    -- 참고) — AWS 공유 DB에 아직 이 스키마가 올라가지 않은 시점이라 컬럼 자체를 지웠다.
    UNIQUE KEY uq_users_email (email),
    UNIQUE KEY uq_users_google_sub (google_sub)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-18 신규] Access Token(JWT, 세션 쿠키)과 분리된 Refresh Token 저장소 — app/models.py
-- RefreshToken 클래스 주석 참고. Access Token만으로는 로그아웃해도 만료 전까지 여전히 유효해서
-- 서버가 무효화할 방법이 없었다 — 이 테이블에 해시로 저장해두면 로그아웃 시 실제로 폐기 가능.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT 'Refresh Token 고유 식별자',
    user_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES users(user_id)',
    token_hash CHAR(64) NOT NULL COMMENT '토큰 원문의 SHA-256 해시(원문 자체는 저장하지 않음)',
    issued_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '발급 시각',
    expires_at DATETIME(6) NOT NULL COMMENT '만료 시각',
    revoked_at DATETIME(6) NULL COMMENT '폐기(로그아웃/회전) 시각 — NULL이면 아직 유효',
    rotated_to_id BIGINT UNSIGNED NULL COMMENT '재발급(회전) 시 이 토큰을 대체한 새 토큰의 token_id — 이미 회전된 토큰 원문이 재사용되면 탈취 의심 단서가 됨',
    UNIQUE KEY uq_refresh_tokens_hash (token_hash),
    KEY ix_refresh_tokens_user (user_id) COMMENT '로그인 상태 조회·전체 세션 폐기 등에서 계정 기준 조회',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (rotated_to_id) REFERENCES refresh_tokens(token_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 회사(예비창업자/기업 프로필) / 아이템(지원 아이템) 및 하위 정보
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    company_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '예비창업자/기업 프로필 고유 식별자',
    user_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES users(user_id)',
    -- [2026-09-18 삭제] start_type(시작 유형: 온라인/오프라인/전자상거래 등) 컬럼 자체를
    -- 뺐다 — API가 2026-09-17부터 이 값을 받지 않아 모든 행이 NULL로만 남아 있었고, ORM
    -- 모델(app/models.py Company)에서도 이미 매핑을 지운 상태였다(정합성 점검으로 발견).
    -- [2026-09-17 배선] IntakeForm.jsx가 "신청자 유형(예비창업자/개인사업자/법인)"을 필수로
    -- 물어보고 제출을 막기까지 하는데, 정작 POST /projects 요청 바디에 실려 오지도 않고 저장할
    -- 컬럼도 없어서 화면에서 고른 값이 그냥 버려지고 있었다(하정원님 지적으로 발견). 기능정의서
    -- v1.5의 매칭·게이트 입력 companyInfo가 요구하는 3개 필드(applicantType, foundedAt,
    -- 대표자명) 중 하나이기도 해서 실제로 필요한 값이다.
    applicant_type VARCHAR(20) NULL COMMENT '신청자 유형: preliminary/individual/corp',
    biz_type VARCHAR(100) NULL COMMENT '업종',
    ceo_name VARCHAR(100) NULL COMMENT '대표자명',
    founded_at DATE NULL COMMENT '설립일(예비창업자는 NULL 가능)',
    -- [2026-09-17 신규] 마이페이지(프로필 저장/재사용, 사업자등록번호 자동조회) 지원용.
    -- company_name/business_reg_no/rep_type은 초기창업패키지 공식 양식(별첨1)의 기업명·
    -- 사업자등록번호·대표자 유형 항목인데, 지금까지 저장할 컬럼이 없어서 계획서 다운로드 시
    -- '○○○' 플레이스홀더로 나가고 있었다(app/routers/projects.py _build_plan_document_data
    -- 참고). AWS 공유 DB엔 아직 이 스키마가 올라가지 않은 시점이라 바로 반영한다.
    company_name VARCHAR(255) NULL COMMENT '기업명/법인명(상호)',
    business_reg_no VARCHAR(32) NULL COMMENT '사업자등록번호',
    rep_type VARCHAR(20) NULL COMMENT '대표자 유형(단독/공동/각자대표)',
    -- [2026-09-18 삭제] is_saved_profile/biz_reg_lookup_raw/biz_reg_lookup_checked_at은
    -- "마이페이지 프로필 저장/재사용"을 이 테이블에 붙이려던 예전 설계 흔적 — 별도 API 없이
    -- 방치돼 있다가 user_profiles(v2, app/routers/profile.py)로 완전히 다르게 구현되면서
    -- 영구 미아가 됨. 어디서도 안 읽고 안 써서 제거.
    KEY ix_companies_user (user_id) COMMENT '[2026-09-15 개정] 계정당 회사 프로필 1건 UNIQUE 제약을 제거했다 — 프로젝트마다 다른 신청자 정보로 회사 프로필을 새로 만들 수 있게 하기 위함(동시 실행 1건 제한은 이제 users 행을 잠그는 방식으로 분리, app/routers/projects.py 참고). 조회는 여전히 잦아 인덱스는 유지',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS projects (
    project_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '프로젝트(지원 아이템/사업 아이디어) 고유 식별자',
    company_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES companies(company_id)',
    description TEXT NOT NULL COMMENT '아이템 설명(사용자가 입력한 사업 아이디어 서술)',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '등록 일시',
    -- [2026-09-18 삭제] notify_region/notify_industry(유사 공고 알림 대상 지역/업종) 컬럼
    -- 자체를 뺐다 — API가 2026-09-17부터 이 값을 받지 않아 모든 행이 NULL로만 남아 있었다
    -- (정합성 점검으로 발견, app/routers/projects.py _build_plan_document_data의 대체 문구도
    -- 함께 정리했다).
    -- [2026-09-17 신규] 계획서 공식 양식(별첨1)이 요구하는데 저장할 곳이 없던 나머지 항목.
    output_summary TEXT NULL COMMENT '산출물(협약기간 내 목표 — 형태·수량)',
    tech_field VARCHAR(100) NULL COMMENT '전문기술분야',
    regional_priority_area VARCHAR(100) NULL COMMENT '지방우대 지역 해당여부(해당 시 지역명, 비해당이면 NULL)',
    -- [2026-09-17 인덱싱 개정] 읽기 위주 접근 패턴 반영. projects.py list_projects()가
    -- "company_id로 필터 + created_at DESC 정렬"을 한다(companies.user_id 1건이 아니게
    -- 되면서 한 유저가 여러 company를 가질 수 있어 이 조회가 더 잦아졌다) — 선두 컬럼이
    -- company_id인 복합 인덱스라 company_id 단독 조회(FK 체크 등)도 그대로 커버하므로
    -- 기존 ix_projects_company(company_id 단일)를 대체한다. admin.py list_all_projects()는
    -- company_id 필터 없이 전체를 created_at으로만 정렬하므로 별도 단일 컬럼 인덱스가 필요.
    KEY ix_projects_company_created (company_id, created_at),
    KEY ix_projects_created (created_at),
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS project_attachments (
    attachment_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '첨부파일 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    file_name VARCHAR(255) NOT NULL COMMENT '첨부파일 원본 파일명',
    file_url VARCHAR(500) NOT NULL COMMENT '첨부파일 저장 경로/URL',
    -- [2026-09-17 신규] 멘토링 피드백 "원본 파일과 파싱 결과를 별도 저장(재시도 안정성
    -- 확보), 파싱 결과는 마크다운화해 재사용" 반영. 공고 수집 파이프라인(이근준님)의
    -- attachment_files/attachment_texts 분리 패턴과 같은 방향 — 원본(file_url)은 그대로
    -- 두고, 파싱 결과만 이 두 컬럼에 캐싱해서 재시도할 때마다 원본을 다시 파싱하지 않게 한다.
    parsed_markdown LONGTEXT NULL COMMENT '첨부파일에서 추출해 마크다운화한 본문 — 있으면 재파싱 없이 재사용',
    parse_status VARCHAR(20) NULL COMMENT '파싱 처리 상태(pending/ok/parse_error/image_only) — NULL이면 아직 파싱 시도 전',
    KEY ix_project_attachments_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS team_members (
    member_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '팀원 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    name VARCHAR(100) NOT NULL COMMENT '팀원 이름',
    role VARCHAR(100) NULL COMMENT '담당 역할',
    experience TEXT NULL COMMENT '경력/역량 서술(자유 서술, NULL 가능)',
    KEY ix_team_members_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS pricing_items (
    pricing_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '단가 항목 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    service_name VARCHAR(255) NOT NULL COMMENT '서비스/상품명',
    unit_price DECIMAL(12,2) NULL COMMENT '단가(원, NULL 가능)',
    KEY ix_pricing_items_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-17 신규] pricing_items와 헷갈리지 않게 구분: pricing_items는 "사업 아이템 자체의
-- 수익모델 단가"(서비스명/단가)이고, 아래 project_budget_items는 완전히 다른 개념인
-- "지원사업 사업비 집행계획"(정부지원금을 비목별로 어떻게 쓸지 — 정부지원사업비/자기부담금
-- 구분)이다. plan_document_export.py의 BudgetLineItem과 1:1 대응.
CREATE TABLE IF NOT EXISTS project_budget_items (
    budget_item_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사업비 집행계획 항목 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    item_order TINYINT UNSIGNED NULL COMMENT '표시 순서',
    category VARCHAR(100) NULL COMMENT '비목(인건비/재료비/외주용역비 등)',
    execution_plan TEXT NULL COMMENT '집행계획 서술',
    total_amount DECIMAL(14,2) NULL COMMENT '총사업비(원)',
    government_amount DECIMAL(14,2) NULL COMMENT '정부지원사업비(원)',
    self_cash_amount DECIMAL(14,2) NULL COMMENT '자기부담금-현금(원)',
    self_in_kind_amount DECIMAL(14,2) NULL COMMENT '자기부담금-현물(원)',
    KEY ix_project_budget_items_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-17 신규] 계획서 양식의 "실현가능성 추진일정"/"성장전략 추진일정"(ScheduleRow) —
-- 두 섹션 다 구조가 똑같아서 section 컬럼으로만 구분하고 테이블은 하나로 합쳤다.
CREATE TABLE IF NOT EXISTS project_schedule_items (
    schedule_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '추진일정 항목 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    section VARCHAR(20) NOT NULL COMMENT '소속 섹션(feasibility=실현가능성 / growth=성장전략)',
    item_order TINYINT UNSIGNED NULL COMMENT '표시 순서',
    category VARCHAR(100) NULL COMMENT '구분',
    content TEXT NULL COMMENT '추진내용',
    period VARCHAR(50) NULL COMMENT '추진기간',
    detail TEXT NULL COMMENT '세부내용',
    KEY ix_project_schedule_items_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-17 신규] 계획서 양식의 "협력기관"(PartnerRow).
CREATE TABLE IF NOT EXISTS project_partners (
    partner_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '협력기관 항목 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    item_order TINYINT UNSIGNED NULL COMMENT '표시 순서',
    partner_name VARCHAR(255) NULL COMMENT '파트너명',
    capability TEXT NULL COMMENT '보유역량',
    collaboration_plan TEXT NULL COMMENT '협업방안',
    collaboration_timing VARCHAR(100) NULL COMMENT '협력시기',
    KEY ix_project_partners_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-22 신규, 하정원님] IntakeForm.jsx가 2026-09-18 정재희님 커밋(병합 시점 담당자
-- 인수인계 불가로 확인 — front/src/features/workflow/ProjectPlanFields.jsx는 그 커밋의
-- 사용부만 보고 재구성했다)에서 새로 받기 시작한 "사업 계획" 입력을 담는다. App.jsx의
-- intakeDetailPayload가 이미 이 컬럼명 그대로(snake_case) 보내고 있었는데
-- ProjectCreateRequest에 대응 필드가 없어 조용히 버려지고 있었다.
-- project_partners/project_budget_items/project_schedule_items와는 다른 개념 — 그 셋은
-- 계획서 문서(별첨1 양식)가 "만들어진 뒤" 채워지고, 이 테이블은 그 전 사전 정보 입력
-- 화면에서 받은 원본이다(project당 1행).
-- hires/equipment/partners/ceo_careers는 user_profiles.basic_json/capability_json과 같은
-- 이유로 JSON에 프론트 항목 모양 그대로 저장한다 — 필드 구성이 아직 팀 논의 중이라
-- (채용예정인력·협업회사 필수입력 전환 제안) 컬럼을 미리 쪼개면 논의가 정리될 때마다
-- 마이그레이션이 필요해진다.
CREATE TABLE IF NOT EXISTS project_plan_inputs (
    input_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사업 계획 입력 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id), project당 1행',
    ceo_birth_date DATE NULL COMMENT '대표자 생년월일',
    ceo_gender VARCHAR(10) NULL COMMENT '대표자 성별',
    region_sido VARCHAR(20) NULL COMMENT '사업장 소재지/창업 예정 지역 — 시/도',
    region_sigungu VARCHAR(50) NULL COMMENT '사업장 소재지/창업 예정 지역 — 시/군/구',
    main_industry VARCHAR(100) NULL COMMENT '주업종',
    certifications JSON NULL COMMENT '보유 인증·가입(문자열 배열)',
    ceo_careers JSON NULL COMMENT '대표자 이력(구분/내용/기간/증빙여부 객체 배열)',
    ceo_capability TEXT NULL COMMENT '기술력 · 노하우 · 인적 네트워크 서술',
    occupation VARCHAR(100) NULL COMMENT '예비창업자 직업(직장명 기재 불가) — 계획서 양식 "일반현황" 항목',
    dev_start_month VARCHAR(7) NULL COMMENT '개발 시작월(YYYY-MM)',
    dev_end_month VARCHAR(7) NULL COMMENT '개발 종료월(YYYY-MM)',
    budget_scale_manwon INT UNSIGNED NULL COMMENT '희망 사업화 자금 규모(만원, 예비창업자 전용, 0~2000)',
    self_funding_allowed BOOLEAN NULL COMMENT '자기부담금 가능 여부(개인사업자·법인 전용, 미입력이면 NULL)',
    self_cash_limit INT UNSIGNED NULL COMMENT '현금 자기부담 가능액(만원)',
    self_in_kind_resources TEXT NULL COMMENT '현물 자원(보유 장비·공간 등) 서술',
    no_hires BOOLEAN NOT NULL DEFAULT FALSE COMMENT '채용 계획 없음 체크 여부',
    hires JSON NULL COMMENT '채용 계획(직무/인원/요구역량/채용시기 객체 배열)',
    no_equipment BOOLEAN NOT NULL DEFAULT FALSE COMMENT '필요 장비·시설 없음 체크 여부',
    equipment JSON NULL COMMENT '장비·시설(이름/상태 객체 배열)',
    no_partners BOOLEAN NOT NULL DEFAULT FALSE COMMENT '협력 기관 없음 체크 여부',
    partners JSON NULL COMMENT '협력 기관(기관명·협력내용/상태 객체 배열) — project_partners(계획서 별첨용)와는 다른 테이블',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '입력 등록 일시',
    UNIQUE KEY ux_project_plan_inputs_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 유사 공고 알림 / 매칭 / 자격요건 게이트
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notice_alerts (
    alert_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '유사 공고 알림 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    notice_id VARCHAR(320) NOT NULL COMMENT 'REFERENCES notices(notice_id)',
    similarity_score DECIMAL(5,2) NOT NULL COMMENT '임베딩 기반 유사도 점수',
    detected_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '알림 감지 일시',
    KEY ix_notice_alerts_project (project_id),
    KEY ix_notice_alerts_notice (notice_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (notice_id) REFERENCES notices(notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS match_candidates (
    candidate_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '매칭 후보 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    notice_id VARCHAR(320) NOT NULL COMMENT 'REFERENCES notices(notice_id)',
    batch SMALLINT NOT NULL COMMENT '1=첫 매칭, 2=재실행(프로젝트당 1회)',
    bonus_score DECIMAL(4,1) NOT NULL COMMENT '공고별 가산점(만점 기준 없음)',
    reason TEXT NOT NULL COMMENT '매칭 근거 서술',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '후보 생성 일시',
    KEY ix_match_candidates_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (notice_id) REFERENCES notices(notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS match_results (
    match_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '매칭 결과 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    notice_id VARCHAR(320) NOT NULL COMMENT 'REFERENCES notices(notice_id)',
    fit_score DECIMAL(5,2) NULL COMMENT '매칭 적합도 점수',
    reason TEXT NULL COMMENT '매칭 사유/근거 서술',
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress' COMMENT '프로젝트 진행 상태(in_progress/completed/halted)',
    stage VARCHAR(30) NULL COMMENT '이어하기용 세부 진행 단계(app/pipeline_stages.py의 STAGE_* 상수 중 하나). NULL이면 아직 매칭만 되고 계획서 작성 전',
    progress_percent TINYINT UNSIGNED NULL COMMENT 'stage 안에서도 오래 걸리는 구간(계획서 작성/프로토타입 제작)의 진행률 0~100. 해당 없는 stage에서는 NULL',
    -- [2026-09-22 신규] 생성 작업 클레임 시각 — Redis 등 별도 브로커 없이 이 컬럼 하나로
    -- "지금 이 stage를 어떤 워커가 처리 중인지"를 표현한다(app/routers/projects.py
    -- _try_claim_and_run 참고). NULL이거나 GENERATION_CLAIM_STALE_SECONDS보다 오래됐으면
    -- "아무도 처리 안 함"으로 보고 새로 클레임할 수 있다 — 서버 재시작·다중 워커 대응.
    worker_claimed_at DATETIME(6) NULL COMMENT '생성 작업(plan_writing/prototype_building)을 처리 중인 워커의 마지막 클레임/하트비트 시각',
    -- [2026-09-22 신규, 프론트 전달사항 4번] 생성 작업 실패 처리 — status='failed'로
    -- 표시하고 stage는 실패한 단계 그대로 둔다. 실패는 복구 루프가 자동 재시도하지 않고
    -- 사용자가 "다시 시도"를 눌러야(_start_generation 재호출) 재개된다.
    failure_reason TEXT NULL COMMENT '생성 작업이 실패한 사유(에러 메시지) — status=failed일 때만 값 있음',
    archived_at DATETIME(6) NULL COMMENT '사용자가 프로젝트를 삭제해 보관 처리된 일시(NULL 가능)',
    archived_by VARCHAR(20) NULL COMMENT "보관 처리 주체('user' 고정, NULL 가능)",
    -- [참고] project.py 전역에서 "WHERE project_id=X ORDER BY match_id DESC" 패턴이 매우
    -- 잦은데, InnoDB 보조 인덱스는 리프에 PK(match_id)를 항상 포함해서 물리적으로
    -- (project_id, match_id) 순으로 정렬돼있다 — ix_match_results_project 단일 컬럼
    -- 인덱스만으로 이미 이 정렬까지 커버되므로 별도 복합 인덱스를 추가하지 않았다.
    KEY ix_match_results_project (project_id),
    KEY ix_match_results_notice (notice_id),
    -- [2026-09-17 신규 인덱스] 프로젝트 시작 시 "진행 중(in_progress) 매칭이 있는지" 동시성
    -- 체크(projects.py)가 status로 필터한다.
    KEY ix_match_results_status (status),
    -- [2026-09-22 신규 인덱스] _recover_orphaned_generations_once가 10초(기본)마다 영원히
    -- "WHERE stage=X AND (worker_claimed_at IS NULL OR 오래됨)"을 도는데, 이 두 컬럼에
    -- 인덱스가 없으면 매번 테이블 풀스캔이 된다 — 지금 규모에선 체감 안 되지만 테이블이
    -- 커질수록/공유 DB 부하가 쌓일수록 그냥 두면 안 되는 debt이라 처음부터 넣는다.
    KEY ix_match_results_stage_claim (stage, worker_claimed_at),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (notice_id) REFERENCES notices(notice_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-17 신규] 멘토링 피드백 "매칭 근거는 정성적 설명보다 '+2점' 같은 정량 점수로
-- 표시하는 게 더 설득력 있음" 반영. match_results.reason(자유 텍스트 하나)만으로는 항목별
-- 점수를 못 보여주니, plan_score_reasons/artifact_score_reasons와 똑같은 모양(item_code/
-- score/max_score/evidence_locator)으로 매칭 단계에도 항목별 채점 근거 테이블을 둔다.
CREATE TABLE IF NOT EXISTS match_score_reasons (
    reason_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사유 고유 식별자',
    match_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES match_results(match_id)',
    reason_text TEXT NOT NULL COMMENT '매칭 적합도 판단 사유',
    item_code VARCHAR(50) NULL COMMENT '채점 항목 코드',
    score DECIMAL(5,2) NULL COMMENT '해당 항목 획득 점수(예: +2.00)',
    max_score DECIMAL(5,2) NULL COMMENT '해당 항목 배점',
    evidence_locator VARCHAR(500) NULL COMMENT '근거 위치(공고문 내 위치 등)',
    KEY ix_match_score_reasons_match (match_id),
    FOREIGN KEY (match_id) REFERENCES match_results(match_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS eligibility_checks (
    check_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '자격요건 게이트 결과 고유 식별자',
    match_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES match_results(match_id)',
    passed BOOLEAN NOT NULL COMMENT '자격요건 통과 여부',
    failed_conditions JSON NULL COMMENT '불통과 사유 목록(문자열 배열) — undecidable=TRUE면 의미 없음',
    missing_inputs JSON NULL COMMENT '판정에 필요한데 빠진 입력값 목록(되묻기 대상)',
    undecidable BOOLEAN NOT NULL DEFAULT FALSE COMMENT '공고문 정형화 실패 등으로 판정 자체가 불가능한 경우(E-G1-UNPARSED) — TRUE면 passed 값은 무시',
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
    -- [2026-09-17 인덱싱 개정] projects.py의 초안 저장이 "이 plan_id 안에 같은 tag(PSST 중 하나)
    -- 섹션이 이미 있는지"를 매번 확인한다(plan_id, tag 동시 필터) — 복합 인덱스로 교체.
    -- 선두 컬럼이 plan_id라 plan_id 단독 조회도 그대로 커버.
    KEY ix_plan_sections_plan_tag (plan_id, tag),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-22 신규] Strategy Agent(구글 드라이브 "전략/작성/검증1" 시트 F01~F15)의 중간
-- 산출물("canonical data") 저장소 — market_analysis/development_plan/team_capability 등
-- 여러 섹션이 재사용하는 구조화된 데이터. plan_sections(완성된 최종 문단)와 다른 층으로,
-- 이게 없으면 최종 텍스트만 복붙해 재사용을 흉내낼 수밖에 없었다(models.py PlanCanonicalData
-- 참고). data_json 내부 구조는 여기서 정하지 않는다 — Strategy Agent 담당자 몫.
CREATE TABLE IF NOT EXISTS plan_canonical_data (
    data_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '캐노니컬 데이터 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    data_key VARCHAR(50) NOT NULL COMMENT '블록 이름: item_spec/market_analysis/competitor_analysis/team_capability/development_goal/development_method/development_plan/production_plan/marketing_strategy/business_model/growth_strategy/resource_plan/budget/schedule/web_data 등(시트 그대로)',
    data_json JSON NOT NULL COMMENT 'F01~F15 각 함수의 실제 output — 내부 구조는 Strategy Agent 담당자가 정함',
    source_function VARCHAR(10) NULL COMMENT '이 데이터를 만든 F-함수 번호(예: F03) — 재시도 대상 식별·디버깅용',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_plan_canonical_data_plan_key (plan_id, data_key),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS plan_score_reasons (
    reason_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '사유 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    reason_text TEXT NOT NULL COMMENT '문서 적합도 판단 사유',
    item_code VARCHAR(50) NULL COMMENT '채점 항목 코드 — rubric_items.item_code와 매칭(FK로 강제하지 않음)',
    score DECIMAL(5,2) NULL COMMENT '해당 항목 획득 점수',
    max_score DECIMAL(5,2) NULL COMMENT '해당 항목 배점',
    evidence_locator VARCHAR(500) NULL COMMENT '근거 위치(계획서 원문 내 위치) — 없으면 감점 무효(E-V1-EVIDENCE)',
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
    item_code VARCHAR(50) NULL COMMENT '채점/체크 항목 코드',
    score DECIMAL(5,2) NULL COMMENT '해당 항목 획득 점수',
    max_score DECIMAL(5,2) NULL COMMENT '해당 항목 배점',
    evidence_locator VARCHAR(500) NULL COMMENT '근거 위치(코드 경로, 화면 위치 등)',
    KEY ix_artifact_score_reasons_artifact (artifact_id),
    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS format_findings (
    finding_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT 'T-P1(문장 형식 검수) 지적 사항 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    section_id BIGINT UNSIGNED NULL COMMENT 'REFERENCES plan_sections(section_id), nullable',
    finding_type VARCHAR(50) NOT NULL COMMENT '문제 유형(punctuation/spacing/tone_mismatch 등)',
    location VARCHAR(500) NULL COMMENT '근거 위치(문단/문장 스니펫 등)',
    message TEXT NOT NULL COMMENT '지적 내용 설명',
    severity VARCHAR(20) NULL COMMENT '심각도(info/warning 등)',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '생성 일시',
    KEY ix_format_findings_plan (plan_id),
    KEY ix_format_findings_section (section_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES plan_sections(section_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-18 확장] attempt_no/passed/violation_note 3컬럼 추가 — "1차 시도 반려(보호
-- 토큰 위반) → 2차 시도 통과" 같은 시도별 판정을 표현하는 데 필요하다(app/models.py
-- ProofreadLog 클래스 주석 참고). 공유 MySQL엔 이미 이 테이블이 있어 ALTER TABLE로
-- 반영해야 한다(back/app_schema.sql은 새 설치 기준 CREATE만 갱신).
CREATE TABLE IF NOT EXISTS proofread_logs (
    log_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT 'T-P2(윤문) 교정 기록 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    section_id BIGINT UNSIGNED NULL COMMENT 'REFERENCES plan_sections(section_id), nullable',
    original_text LONGTEXT NOT NULL COMMENT '윤문 전 원문',
    corrected_text LONGTEXT NOT NULL COMMENT '윤문 후 교정문(passed=FALSE면 반려된 시도안)',
    reason TEXT NULL COMMENT '교정 사유',
    attempt_no INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '같은 plan_id+section_id 안에서 몇 번째 시도인지(1=최초)',
    score DECIMAL(5,2) NOT NULL DEFAULT 100.00 COMMENT '이 시도의 윤문 품질 점수(0~100) — business_plans.doc_score와 같은 형식',
    passed BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'FALSE면 보호 토큰(수치·날짜·고유명사·기능명) 위반으로 반려된 시도',
    violation_note TEXT NULL COMMENT '반려 사유(passed=FALSE일 때만) — 어떤 보호 토큰이 어떻게 바뀌었는지',
    violation_type VARCHAR(20) NULL COMMENT '위반 종류: 날짜/수치·금액/고유명사/기능명 (passed=FALSE일 때만)',
    recovery_status VARCHAR(20) NULL COMMENT '"검수 회수 문단" 탭 라벨링 상태: pending/labeled/excluded (passed=FALSE일 때만)',
    recovery_label TEXT NULL COMMENT '라벨링 완료 시 사람이 정리한 정답 문장',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '생성 일시',
    KEY ix_proofread_logs_plan (plan_id),
    KEY ix_proofread_logs_section (section_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES plan_sections(section_id) ON DELETE SET NULL
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
    -- [2026-09-17 신규 인덱스] 공개 FAQ 목록(faqs.py)이 "is_visible=TRUE인 것만, created_at
    -- DESC로" 매번 조회한다 — 기존엔 이 두 컬럼에 인덱스가 없어 전체 스캔+정렬이었다.
    KEY ix_faqs_visible_created (is_visible, created_at),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 마이페이지 프로필 (계정 단위 — SB-59)
-- ---------------------------------------------------------------------------
-- [2026-09-17 신규] 마이페이지 입력값이 지금까지 브라우저(localStorage)에만 남아 다른
-- 기기에서 로그인하면 안 보이던 문제를 고쳐, 계정별로 서버에 저장/조회한다. companies
-- 테이블은 쓰지 않는다 — companies는 "프로젝트를 새로 만들 때마다 그 프로젝트의 스냅샷으로
-- 같이 생기는" 성격이고, 이 테이블은 "계정 자체에 딸린, 프로젝트와 무관한" 프로필이라
-- 성격이 달라 별도 테이블로 둔다.
-- [2026-09-18 v2] 계정당 최대 3개 슬롯(app/routers/profile.py에서 강제) — v1(계정당 1행,
-- user_id UNIQUE, 판정용 컬럼 + history_json)은 정재희님의 새 프론트(다중 슬롯, 재창업
-- 이력 추적 안 함)와 안 맞아 DROP 후 재생성했다(마이그레이션 시점 0행, 데이터 손실 없음).
CREATE TABLE IF NOT EXISTS user_profiles (
    profile_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '정보 슬롯 고유 식별자',
    user_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES users(user_id), 계정당 최대 3행',
    name VARCHAR(50) NOT NULL DEFAULT '정보 1' COMMENT '슬롯 이름(사용자가 직접 지음, 예: 두 번째 아이템)',
    -- 화면 전용 원본: basic/capability를 통째로 그대로 저장한다(프론트 스토어
    -- front/src/store/useMyPageStore.js의 profile.basic/profile.capability와 1:1 모양 —
    -- 변환 코드 불필요). 판정용 컬럼(v1에 있던 applicant_type/birth_date/... )은 실제로
    -- 매칭·자격요건 판정 코드에서 읽힌 적이 없어 v2에서 뺐다(app/models.py UserProfile 참고).
    basic_json JSON NOT NULL COMMENT '기본 정보 탭 원본',
    capability_json JSON NOT NULL COMMENT '역량·팀 탭 원본',
    -- 국세청 사업자등록정보 상태조회 결과: POST /biz-check가 profile_id를 받아 그 슬롯에만
    -- 채운다. PUT 바디에 실려 와도 무시한다(app/routers/profile.py) — 클라이언트가
    -- "계속사업자" 상태를 조작해서 보낼 수 없게 하기 위함. 저장한 bizNo가 이 biz_checked_no와
    -- 달라지면(재조회 전까지는) 아래 4개 컬럼을 NULL로 비운다.
    biz_checked_no CHAR(10) NULL COMMENT '조회에 실제로 쓰인 사업자등록번호(숫자만)',
    biz_status_cd CHAR(2) NULL COMMENT '01 계속사업자 / 02 휴업자 / 03 폐업자',
    biz_tax_type VARCHAR(50) NULL COMMENT '과세유형(예: 부가가치세 일반과세자)',
    biz_checked_at DATETIME(6) NULL COMMENT '조회 시각',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '슬롯 생성 일시',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '마지막 저장 일시',
    KEY ix_user_profiles_user (user_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ---------------------------------------------------------------------------
-- 에이전트 실행 로그 (관리자 대시보드 "에이전트 테스크" 탭)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_executions (
    execution_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '에이전트 실행 세션 고유 식별자',
    match_id BIGINT UNSIGNED NULL COMMENT 'REFERENCES match_results(match_id), nullable',
    agent_name VARCHAR(50) NOT NULL COMMENT '실행 Agent 이름(조율/전략/작성/구현/검증-1/검증-2/검수)',
    task_key VARCHAR(50) NULL COMMENT 'app/models.py FIXED_TASK_SEQUENCE의 세부 Task 키 — 같은 agent_name이 여러 Task를 맡을 때 구분용',
    attempt_no INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '같은 task_key 안에서 몇 번째 실행인지(1=최초, 2=재시도 1회차, ...)',
    model_used VARCHAR(50) NOT NULL COMMENT '사용 모델명(Claude Opus/Sonnet/Haiku 또는 자체 파인튜닝 모델 버전)',
    rerun_type VARCHAR(20) NOT NULL COMMENT '최초 실행/선별 재수행/전체 재실행 구분',
    token_usage INT UNSIGNED NOT NULL COMMENT '실행에 사용된 토큰 수',
    status VARCHAR(20) NOT NULL COMMENT '실행 결과 상태(성공/실패)',
    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '실행 시작 일시',
    -- [2026-09-17 인덱싱 개정] "이 매칭의 이 task_key 최근 시도가 몇 번째인지" 조회가
    -- 재시도/이어하기 로직에서 자주 호출된다(projects.py 재시도 처리, admin.py 에이전트
    -- 테스크 탭의 match_id 필터). 복합 인덱스 선두가 match_id라 match_id 단독 필터
    -- (admin.py)도 그대로 커버하므로 기존 ix_agent_executions_match(단일)를 대체한다.
    KEY ix_agent_executions_match_task (match_id, task_key, attempt_no),
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
    pass_threshold DECIMAL(5,2) NOT NULL DEFAULT 80 COMMENT '통과 Threshold(100점 만점 기준) — 기능명세 G-02 기준으로 80 확정(2026-09-13, 이전엔 70이었음)',
    rerun_cap INT UNSIGNED NOT NULL DEFAULT 3 COMMENT 'Threshold 미달 시 자동 재수행 최대 횟수',
    deviation_cap DECIMAL(5,2) NOT NULL DEFAULT 5 COMMENT '문서층 재채점 편차 상한(경고 알림 기준)',
    token_retry_cap INT UNSIGNED NOT NULL DEFAULT 2 COMMENT '검수(표현) Task 내부 보호 토큰 위반 문단 재시도 최대 횟수(rerun_cap과 별개)',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '정책 마지막 수정 일시'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO verification_policies (policy_id)
SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM verification_policies);

-- [2026-09-22 구조 교체, 프론트 전달사항 10번] 기획서 v1.8 5-4 기준(카테고리별 8항목·
-- 15점 만점)으로 바꿨다 — category는 이제 산출물 카테고리('html'=웹개발·AI API,
-- 'svg'=원페이지) 의미이고, item_no(카테고리 안 1~8번)·item_code(artifact_score_reasons.
-- item_code와 매칭)를 새로 추가했다(models.py VerificationChecklistItem 참고).
CREATE TABLE IF NOT EXISTS verification_checklist_items (
    check_item_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '코드 기준 자동 검증 항목 고유 식별자',
    item_code VARCHAR(50) NOT NULL UNIQUE COMMENT 'artifact_score_reasons.item_code와 매칭되는 항목 코드',
    item_no TINYINT UNSIGNED NOT NULL COMMENT '카테고리 안에서의 순번(1~8) — 1번은 진입 파일 존재 여부, 미충족 시 해당 카테고리 자동 검증 점수 전체 0점(검증 에이전트가 적용)',
    category VARCHAR(20) NOT NULL COMMENT "산출물 카테고리: 'html'(웹개발·AI API, artifacts.category의 webdev/aiapi) | 'svg'(원페이지, artifacts.category의 onepage)",
    name VARCHAR(100) NOT NULL COMMENT '검증 항목명(예: 진입 파일 존재 여부)',
    method TEXT NOT NULL COMMENT '판정 방식 설명(파싱/계산 기준)',
    weight DECIMAL(5,2) NOT NULL COMMENT '가중치 점수 — 카테고리별 8항목 합계 15점',
    enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT '사용 여부(해제 시 채점에서 제외)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO verification_checklist_items (item_code, item_no, category, name, method, weight, enabled)
SELECT * FROM (
    -- 웹개발·AI API(HTML) — 8항목, 합계 15점
    SELECT 'CHECK-HTML-ENTRY-FILE' AS item_code, 1 AS item_no, 'html' AS category, '진입 파일 존재 여부' AS name, '산출물 루트에 지정된 진입 파일(index.html 등)이 실제로 있는지 확인' AS method, 3.00 AS weight, TRUE AS enabled
    UNION ALL SELECT 'CHECK-HTML-ALT-TEXT', 2, 'html', 'img·svg 대체 텍스트', 'img/svg 요소에 alt(또는 대체 텍스트 접근법)가 있는지 파싱', 2.00, TRUE
    UNION ALL SELECT 'CHECK-HTML-INPUT-LABEL', 3, 'html', 'input label 연결', 'input 요소가 label(for/aria-label 등)로 연결돼 있는지 파싱', 2.00, TRUE
    UNION ALL SELECT 'CHECK-HTML-LANG-ATTR', 4, 'html', 'html lang 속성', '<html> 태그에 lang 속성이 있는지 확인', 1.00, TRUE
    UNION ALL SELECT 'CHECK-HTML-CONTRAST', 5, 'html', '명도 대비 4.5:1', '주요 텍스트·배경 색상 조합의 명도 대비가 4.5:1 이상인지 계산', 2.00, TRUE
    UNION ALL SELECT 'CHECK-HTML-HEADING', 6, 'html', '제목 계층', 'h1~h6 제목 태그가 순서를 건너뛰지 않고 계층적으로 쓰였는지 확인', 2.00, TRUE
    UNION ALL SELECT 'CHECK-HTML-README', 7, 'html', '실행·열람 안내 문서', '실행 방법을 설명하는 안내 문서(README 등)가 있는지 확인', 1.00, TRUE
    UNION ALL SELECT 'CHECK-HTML-SECRET', 8, 'html', '하드코딩된 비밀값', 'API 키·비밀번호 등이 코드에 하드코딩돼 있는지 패턴 스캔', 2.00, TRUE
    -- 원페이지(SVG) — 8항목, 합계 15점
    UNION ALL SELECT 'CHECK-SVG-ENTRY-FILE', 1, 'svg', '진입 파일 존재 여부', '산출물 루트에 지정된 진입 파일(svg 등)이 실제로 있는지 확인', 3.00, TRUE
    UNION ALL SELECT 'CHECK-SVG-ALT-TEXT', 2, 'svg', '대체 텍스트', '이미지·아이콘 요소에 대체 텍스트가 있는지 파싱', 2.00, TRUE
    UNION ALL SELECT 'CHECK-SVG-KEY-INFO', 3, 'svg', '핵심 정보 항목 포함', '계획서가 요구하는 핵심 정보 항목이 실제로 담겨 있는지 확인', 2.00, TRUE
    UNION ALL SELECT 'CHECK-SVG-CONTRAST', 4, 'svg', '명도 대비 4.5:1', '주요 텍스트·배경 색상 조합의 명도 대비가 4.5:1 이상인지 계산', 2.00, TRUE
    UNION ALL SELECT 'CHECK-SVG-INFO-HIERARCHY', 5, 'svg', '정보 계층', '정보가 중요도 순으로 시각적 계층을 이루는지 확인', 2.00, TRUE
    UNION ALL SELECT 'CHECK-SVG-TEXT-REALNESS', 6, 'svg', '텍스트 실재성', '텍스트가 이미지가 아니라 실제 선택 가능한 텍스트 요소인지 확인', 2.00, TRUE
    UNION ALL SELECT 'CHECK-SVG-MIN-FONT-SIZE', 7, 'svg', '최소 글자 크기', '본문 텍스트가 정책상 최소 글자 크기 이상인지 확인', 1.00, TRUE
    UNION ALL SELECT 'CHECK-SVG-README', 8, 'svg', '열람 안내 문서', '결과물 열람 방법을 설명하는 안내 문서가 있는지 확인', 1.00, TRUE
) seed
WHERE NOT EXISTS (SELECT 1 FROM verification_checklist_items);

-- T-V1(문서층 채점)이 참조하는 전역 고정 채점 기준표. verification_checklist_items와
-- 달리 이쪽은 산출물(코드)이 아니라 계획서 문서를 채점하는 기준이다.
CREATE TABLE IF NOT EXISTS rubric_items (
    rubric_item_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '채점 기준 항목 고유 식별자',
    item_code VARCHAR(50) NOT NULL UNIQUE COMMENT 'plan_score_reasons.item_code와 매칭되는 항목 코드',
    category VARCHAR(50) NOT NULL COMMENT '분류(예: 문제인식/실현가능성/성장전략)',
    criterion TEXT NOT NULL COMMENT '채점 기준 설명',
    max_score DECIMAL(5,2) NOT NULL COMMENT '배점',
    enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT '사용 여부(해제 시 채점에서 제외)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS verification_score_history (
    history_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '점수 이력 고유 식별자',
    plan_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES business_plans(plan_id)',
    layer VARCHAR(20) NOT NULL COMMENT '채점 층 구분(doc/code/plan)',
    score DECIMAL(5,2) NOT NULL COMMENT '해당 회차 점수',
    is_rerun BOOLEAN NOT NULL DEFAULT FALSE COMMENT '재수행에 의한 재채점 여부',
    policy_id BIGINT UNSIGNED NULL COMMENT 'REFERENCES verification_policies(policy_id) — 참고용, verification_policies는 단일 행 UPDATE라 재현 근거는 아래 스냅샷 컬럼이 진짜',
    applied_weight DECIMAL(5,2) NULL COMMENT '판정 당시 이 layer에 적용된 weight 스냅샷',
    applied_pass_threshold DECIMAL(5,2) NULL COMMENT '판정 당시 pass_threshold 스냅샷',
    applied_rerun_cap INT UNSIGNED NULL COMMENT '판정 당시 rerun_cap 스냅샷',
    scored_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '채점 일시',
    KEY ix_verification_score_history_plan (plan_id),
    FOREIGN KEY (plan_id) REFERENCES business_plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (policy_id) REFERENCES verification_policies(policy_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
