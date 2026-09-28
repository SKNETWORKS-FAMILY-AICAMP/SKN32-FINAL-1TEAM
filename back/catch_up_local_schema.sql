-- [본인 로컬 MySQL 전용, 2026-09-17] "Unknown column 'applicant_type' in 'field list'" 원인 —
--
-- app_schema.sql은 전부 `CREATE TABLE IF NOT EXISTS`라서, 테이블이 이미 있으면 새로 추가된
-- 컬럼이 자동으로 반영되지 않는다(이 세션 동안 companies/projects에 여러 컬럼을 추가했는데,
-- 하정원님 로컬 DB는 그 전에 이미 테이블이 만들어져 있어서 계속 옛날 구조 그대로였다).
--
-- 이 스크립트는 몇 번을 실행해도 안전하다 — 컬럼이 이미 있으면 건너뛰고, 없으면 추가한다
-- (MySQL 버전에 상관없이 동작하도록 information_schema로 직접 확인하는 방식을 썼다).
--
-- 실행: mysql -u <계정> -p s_brain < catch_up_local_schema.sql
-- (팀 공유 AWS MySQL에는 절대 실행하지 마세요 — 거긴 아직 이 스키마 자체가 안 올라갔을 수 있음.)

DELIMITER $$

DROP PROCEDURE IF EXISTS _add_col_if_missing $$
CREATE PROCEDURE _add_col_if_missing(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_coldef TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_coldef);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT(p_table, '.', p_column, ' 추가함') AS result;
    ELSE
        SELECT CONCAT(p_table, '.', p_column, ' 이미 있음 — 건너뜀') AS result;
    END IF;
END $$

DELIMITER $$

-- [2026-09-22 신규] 인덱스용 — 컬럼과 달리 MySQL엔 `ADD INDEX IF NOT EXISTS`가 없어서
-- (버전 상관없이 동작하게) 컬럼과 똑같은 information_schema 확인 패턴을 쓴다.
DROP PROCEDURE IF EXISTS _add_index_if_missing $$
CREATE PROCEDURE _add_index_if_missing(
    IN p_table VARCHAR(64), IN p_index VARCHAR(64), IN p_indexdef TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND INDEX_NAME = p_index
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD INDEX `', p_index, '` ', p_indexdef);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT(p_table, '.', p_index, ' 추가함') AS result;
    ELSE
        SELECT CONCAT(p_table, '.', p_index, ' 이미 있음 — 건너뜀') AS result;
    END IF;
END $$

-- [2026-09-27 신규] 컬럼 개명용(SB-133: retry_count -> resume_count) — 옛 이름이 아직
-- 있고 새 이름은 아직 없을 때만 RENAME한다(몇 번을 돌려도 안전). p_coldef에는 RENAME
-- 대상 컬럼의 전체 타입 정의(예: "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '...'")를
-- 그대로 넣어야 한다 — MySQL의 CHANGE COLUMN 문법이 타입을 다시 요구하기 때문.
DROP PROCEDURE IF EXISTS _rename_col_if_needed $$
CREATE PROCEDURE _rename_col_if_needed(
    IN p_table VARCHAR(64), IN p_old_column VARCHAR(64), IN p_new_column VARCHAR(64), IN p_coldef TEXT
)
BEGIN
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_old_column
    ) AND NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_new_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` CHANGE COLUMN `', p_old_column, '` `', p_new_column, '` ', p_coldef);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT(p_table, '.', p_old_column, ' -> ', p_new_column, ' 개명함') AS result;
    ELSE
        SELECT CONCAT(p_table, '.', p_new_column, ' 이미 처리됨 — 건너뜀') AS result;
    END IF;
END $$

DELIMITER ;

-- companies: applicant_type이 없다는 건 [2026-09-17 신규] 이후 컬럼들이 통째로 안 들어가
-- 있다는 뜻이라, 그 뒤에 추가한 나머지도 같이 확인한다.
CALL _add_col_if_missing('companies', 'applicant_type', "VARCHAR(20) NULL COMMENT '신청자 유형: preliminary/individual/corp'");
CALL _add_col_if_missing('companies', 'company_name', "VARCHAR(255) NULL COMMENT '기업명/법인명(상호)'");
CALL _add_col_if_missing('companies', 'business_reg_no', "VARCHAR(32) NULL COMMENT '사업자등록번호'");
CALL _add_col_if_missing('companies', 'rep_type', "VARCHAR(20) NULL COMMENT '대표자 유형(단독/공동/각자대표)'");
CALL _add_col_if_missing('companies', 'biz_reg_lookup_raw', "JSON NULL COMMENT '사업자등록번호 오픈API 자동조회 원본 응답 캐시'");
CALL _add_col_if_missing('companies', 'biz_reg_lookup_checked_at', "DATETIME(6) NULL COMMENT '위 자동조회를 마지막으로 수행한 일시'");
CALL _add_col_if_missing('companies', 'is_saved_profile', "BOOLEAN NOT NULL DEFAULT FALSE COMMENT '마이페이지에 저장해 다음 프로젝트에도 재사용할 프로필인지'");

-- projects: 계획서 양식(별첨1) 추가 항목 3개.
CALL _add_col_if_missing('projects', 'output_summary', "TEXT NULL COMMENT '산출물(협약기간 내 목표 — 형태·수량)'");
CALL _add_col_if_missing('projects', 'tech_field', "VARCHAR(100) NULL COMMENT '전문기술분야'");
CALL _add_col_if_missing('projects', 'regional_priority_area', "VARCHAR(100) NULL COMMENT '지방우대 지역 해당여부(해당 시 지역명)'");

-- [2026-09-28 삭제, SB-152 정리] 여기 있던 match_results 컬럼 추가/개명 6건(worker_claimed_at/
-- failure_reason/retry_count/next_retry_at/resume_started_at/last_error_kind, 2026-09-22~27
-- 사이 추가됨)을 지웠다 — projects/match_results 통합(SB-118) 이후 match_results 테이블
-- 자체가 없어져서, 이미 통합이 끝난 DB에서 이 CALL들이 "Table 'match_results' doesn't
-- exist"(Error 1146)로 실패하는 걸 실제로 확인했다(하정원님). 아직 통합 전인(=match_results가
-- 남아있는) DB는 없다고 보고 안전하게 지운다 — 혹시 있다면 _migrate_match_results_into_
-- projects()가 이 컬럼들 없이 UPDATE를 시도해 실패할 텐데, 그건 이 컬럼들을 여기서 되살리는
-- 것보다 먼저 어떤 DB인지 확인하는 게 맞다.

-- [2026-09-27 신규] 필수 동의(이용약관/개인정보) — 공식 기능정의서 v1.9 E-AUTH-CONSENT
-- 대비 갭. 예전엔 프론트 체크박스로만 가입 진행을 막고 서버는 동의 여부를 전혀
-- 몰랐다. 의도적으로 백필하지 않는다 — 기존 계정도 실제로 동의한 적이 없으므로
-- NULL(미동의)로 두고, PATCH /auth/consent로 다시 동의해야 새 실행을 시작할 수 있게
-- 한다(app/routers/projects.py create_project 참고).
CALL _add_col_if_missing('users', 'terms_agreed_at', "DATETIME(6) NULL COMMENT '이용약관 동의 시각(NULL=미동의)'");
CALL _add_col_if_missing('users', 'privacy_agreed_at', "DATETIME(6) NULL COMMENT '개인정보 수집·이용 동의 시각(NULL=미동의)'");

-- [2026-09-23 신규] match_results.status/agent_executions.status를 서비스 내부 상태
-- 6종(실행/재개대기/사용자대기/실패/완료/중단) 실제 MySQL ENUM으로 강제한다
-- (app/models.py _GenerationStatus, app/pipeline_stages.py GENERATION_STATUSES 참고).
-- agent_executions.status는 예전에 'success'라는 다른 이름을 썼어서(seed_dummy_pipeline.py),
-- ENUM으로 바꾸기 전에 기존 값을 'completed'로 먼저 맞춰야 한다 — 안 그러면 ENUM에
-- 없는 값이 남아있는 행에서 ALTER 자체가 막힌다. 두 ALTER 다 몇 번을 다시 실행해도
-- 안전하다(이미 ENUM이어도 같은 정의로 다시 MODIFY할 뿐).
-- [2026-09-28 삭제, SB-152 정리] 여기 있던 `ALTER TABLE match_results MODIFY COLUMN
-- status ...`를 지웠다 — match_results 테이블 자체가 없어져서(SB-118) 이제 이 ALTER는
-- 무조건 "Table 'match_results' doesn't exist"로 실패한다. projects.status는 아래
-- _migrate_match_results_into_projects() 섹션이 처음부터 이 ENUM 정의로 컬럼을 만든다.
UPDATE agent_executions SET status = 'completed' WHERE status = 'success';
ALTER TABLE agent_executions
    MODIFY COLUMN status ENUM('in_progress','waiting_resume','user_waiting','failed','completed','halted')
    NOT NULL COMMENT '서비스 내부 상태(실행/재개대기/사용자대기/실패/완료/중단) — match_results.status와 같은 enum';

-- [2026-09-23 신규] 자동 재시도 5회 소진 후 확정 실패할 때마다 쌓는 관리자 알림 로그
-- (app/models.py GenerationFailureAlert 참고) — 새 테이블이라 CREATE TABLE IF NOT EXISTS로
-- 충분하다(컬럼 추가 마이그레이션 절차 불필요).
-- [2026-09-28 수정, SB-152 정리] match_id 컬럼/FK 제거 — notifications와 같은 이유
-- (match_results 테이블 소멸, 위 참고).
CREATE TABLE IF NOT EXISTS generation_failure_alerts (
    alert_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '알림 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    stage VARCHAR(30) NOT NULL COMMENT '실패가 확정된 시점의 stage',
    resume_count TINYINT UNSIGNED NOT NULL COMMENT '확정 시점까지 소진한 자동 재개 횟수',
    failure_reason TEXT NULL COMMENT '마지막 실패 사유',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    acknowledged_at DATETIME(6) NULL COMMENT '관리자 확인 처리 시각(NULL이면 미확인)',
    KEY ix_generation_failure_alerts_project (project_id),
    KEY ix_generation_failure_alerts_unacked (acknowledged_at),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-27 신규, SB-133] 위 CREATE TABLE IF NOT EXISTS는 테이블이 이미 있으면 컬럼을
-- 안 건드리므로, 이 테이블이 옛 이름(retry_count)으로 이미 만들어져 있던 환경은 여기서
-- 개명해야 한다.
CALL _rename_col_if_needed('generation_failure_alerts', 'retry_count', 'resume_count', "TINYINT UNSIGNED NOT NULL COMMENT '확정 시점까지 소진한 자동 재개 횟수'");

-- [2026-09-27 신규, SB-134] last_error_kind — 최종 스키마는 NOT NULL이지만, 이 테이블에
-- 이미 쌓여있는 옛 행은 이 개념 자체가 없던 시절 것이라 값을 채울 수 없다. 일단 NULL
-- 허용으로 추가하고, 기존 행은 '일시'(가장 낙관적인 기본값 — 재개 상한 소진으로 실패한
-- 옛 행들의 실제 원인은 알 수 없음)로 채운 뒤 NOT NULL로 고정한다. 두 단계 다 몇 번을
-- 다시 실행해도 안전하다.
CALL _add_col_if_missing('generation_failure_alerts', 'last_error_kind', "ENUM('일시','입력','운영') NULL COMMENT '실패 확정 시점의 원인 분류'");
UPDATE generation_failure_alerts SET last_error_kind = '일시' WHERE last_error_kind IS NULL;
ALTER TABLE generation_failure_alerts
    MODIFY COLUMN last_error_kind ENUM('일시','입력','운영') NOT NULL COMMENT '실패 확정 시점의 원인 분류';

-- [2026-09-28 뒤늦게 추가] plan_canonical_data(2026-09-22 신규, Strategy Agent F01~F15
-- 중간 산출물 저장소) — app_schema.sql에는 있었는데 이 카드업 스크립트에 반영이 안 돼
-- 있어서 팀 공유 AWS MySQL에 이 테이블 자체가 없는 상태로 남아 있었다(2026-09-28 프론트
-- 보고, GET/POST /projects 500 OperationalError 원인 중 하나). 새 테이블이라
-- CREATE TABLE IF NOT EXISTS로 충분하다.
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

-- [2026-09-27 신규, SB-141] 사용자용 작업 알림(화면 헤더 종모양) — 새 테이블이라
-- CREATE TABLE IF NOT EXISTS로 충분하다(컬럼 추가 마이그레이션 절차 불필요).
-- [2026-09-28 수정, SB-152 정리] match_id 컬럼/FK 제거 — projects/match_results 통합
-- (SB-118) 이후 match_results 테이블 자체가 없어져서, notifications가 아직 없는 DB에
-- 이 블록을 그대로 실행하면 없는 테이블을 참조하는 FK 때문에 바로 실패한다. 이미
-- notifications가 있는 DB(=지금 이 CREATE TABLE IF NOT EXISTS가 no-op인 경우)는 그
-- 아래 _migrate_match_results_into_projects() 섹션이 match_id 컬럼을 따로 드롭해준다.
CREATE TABLE IF NOT EXISTS notifications (
    notification_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '알림 고유 식별자',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    kind ENUM('문서평가','산출물확인','표현검수','실패') NOT NULL COMMENT '완료된 단계 또는 실패',
    failure_scope ENUM('실행','재작성') NULL COMMENT "kind='실패'일 때만: 실행 실패 또는 재작성 실패",
    target_step TINYINT UNSIGNED NULL COMMENT '알림을 누르면 들어갈 화면 번호(실패는 NULL — 이어하기 목록으로 연결)',
    channel VARCHAR(10) NOT NULL DEFAULT '화면' COMMENT '알림 경로. 지금은 화면 하나뿐(메일은 향후 도입)',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    read_at DATETIME(6) NULL COMMENT '사용자가 읽은 시각(NULL이면 안읽음)',
    KEY ix_notifications_project (project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- [2026-09-22 신규, 2026-09-23 재시딩 추가] verification_checklist_items v1.8 구조
-- 교체(카테고리별 8항목·15점). 예전 5항목/100점 데이터는 item_code/item_no가 있을 자리
-- 자체가 없어서 컬럼만 추가해선 값을 못 채운다 — 이 테이블은 사용자 데이터가 아니라
-- 관리자 기준표라 안전하게 통째로 비우고 다시 심는다.
--
-- [2026-09-23 수정] 예전엔 여기서 비우고 나서 `python seed_dummy_admin_data.py`를 다시
-- 돌리라고 안내했는데, 그 스크립트는 DB_BACKEND=sqlite가 아니면 스스로 거부하도록
-- 만들어져 있어서(팀 공유 AWS MySQL에 더미 프로젝트 데이터가 새는 걸 막으려는 안전장치,
-- seed_dummy_admin_data.py 8번째 줄 참고) 정작 MySQL엔 절대 못 돌린다 — MySQL로 켜서
-- 관리자 체크리스트 화면을 열면 데이터가 하나도 없어서 안 뜨는 원인이 바로 이거였다
-- (프론트 담당자 협의사항 스크린샷, 하정원님이 실제로 겪음). 이건 사용자별 더미 데이터가
-- 아니라 전체 팀이 같이 쓰는 채점 기준표라 seed_dummy_admin_data.py가 아니라 이 마이그레이션
-- 스크립트 자신이 다시 심어야 맞다 — 그래서 app_schema.sql의 INSERT 블록을 그대로 옮겨왔다.
DELETE FROM verification_checklist_items;
ALTER TABLE verification_checklist_items AUTO_INCREMENT = 1;
CALL _add_col_if_missing('verification_checklist_items', 'item_code', "VARCHAR(50) NOT NULL UNIQUE COMMENT 'artifact_score_reasons.item_code와 매칭되는 항목 코드'");
CALL _add_col_if_missing('verification_checklist_items', 'item_no', "TINYINT UNSIGNED NOT NULL COMMENT '카테고리 안에서의 순번(1~8)'");

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

-- [2026-09-28 신규] agent_executions에 실패 상세(오류 분류/사유)를 추가한다 — 관리자
-- "에이전트 테스크" 탭이 status='failed' 행의 원인과 재시도 가능 여부(error_kind='일시')를
-- 보여주려면 필요하다(app/models.py AgentExecution, app/routers/admin.py list_agent_executions).
CALL _add_col_if_missing('agent_executions', 'error_kind', "ENUM('일시','입력','운영') NULL COMMENT '실패 원인 분류(status=failed일 때만)'");
CALL _add_col_if_missing('agent_executions', 'error_reason', "TEXT NULL COMMENT '실패 사유 원문(status=failed일 때만)'");

-- [2026-09-28 신규, SB-148] Task I/O 확장 검토 결과 — 원본 프롬프트/응답 대신 산출물
-- 참조({table,id})만 남긴다(app/models.py AgentExecution.output_ref 참고).
CALL _add_col_if_missing('agent_executions', 'output_ref', "JSON NULL COMMENT '이 실행이 만들거나 바꾼 산출물 참조({table,id} 또는 리스트) — 프롬프트/응답 원문은 저장하지 않음'");
CALL _add_col_if_missing('project_plan_inputs', 'main_industry_free', "VARCHAR(100) NULL COMMENT '주업종(예비창업자 전용 자유 텍스트)'");

-- [2026-09-28 신규] 프론트 요청 1·2(재시도 상한) — "재작성"(사용자, POST .../retry-task)
-- 상한을 rerun_cap(시스템 자동 재수행)과 분리한다(app/models.py VerificationPolicy 참고).
CALL _add_col_if_missing('verification_policies', 'rework_cap', "INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '재작성(사용자가 POST /projects/{id}/retry-task로 묶음을 다시 만드는 것) 최대 횟수 — 묶음마다 1회, 첫 실행은 안 세고 실패하면 환불(rerun_cap과 별개, 2026-09-28 신규)'");

-- [2026-09-28 신규, 프론트 답변 반영 — bundle_id 버그 수정] task_key='writing' 하나가
-- 화면상 묶음 3개(본문/그래프/표)를 가리켜서, rework_cap 소진 여부를 task_key만으로
-- 정확히 셀 수 없다(app/models.py AgentExecution.bundle_id 참고).
CALL _add_col_if_missing('agent_executions', 'bundle_id', "VARCHAR(50) NULL COMMENT '재작성 묶음 이름(writing만 사용 — 예: 사업계획서 본문 작성/그래프 생성/표 생성)'");

DROP PROCEDURE IF EXISTS _add_col_if_missing;

-- [2026-09-28 신규] rerun_cap은 기획서 5-6절 확정값(2)로 맞춘다 — rework_cap과 분리되기
-- 전 기본값 3이 그대로 남아있는 행만 건드린다(운영 중 정책은 1행만 유지 — app_schema.sql
-- 주석). 이미 관리자가 3이 아닌 값으로 직접 바꿔둔 행은 건드리지 않는다.
UPDATE verification_policies SET rerun_cap = 2 WHERE rerun_cap = 3;

-- [2026-09-28 삭제, SB-152 정리] 여기 있던 match_results용 인덱스 추가 CALL도 같은 이유로
-- 지웠다(위 컬럼 CALL들과 동일 — 테이블 자체가 없어져 Error 1146). 같은 역할의 인덱스는
-- 아래 _migrate_match_results_into_projects() 섹션에서 projects에 이미 걸어준다
-- (ix_projects_stage_claim).

DROP PROCEDURE IF EXISTS _add_index_if_missing;

-- [2026-09-23 삭제] start_type/notify_region/notify_industry는 2026-09-18에 컬럼 자체가
-- 완전히 삭제됐다(app_schema.sql 67/100번째 줄 주석 참고) — 지금 스키마엔 이 컬럼들이
-- 아예 없어서 "NULL 허용으로 바꾸는" ALTER 자체가 "Unknown column" 에러만 낸다. 이미 이
-- 컬럼들이 없는 DB(=현재 스키마와 일치)에서 이 스크립트를 실행하면 여기서 막힌다는 걸
-- 실제로 확인해서(하정원님) 지웠다 — 그 앞의 CALL들은 전부 이 줄보다 먼저 실행되므로
-- 안전했다.

-- [2026-09-28 신규] plan_sections.tag를 실제 MySQL ENUM으로 강제한다(app/models.py
-- _PlanSectionTag, app/pipeline_stages.py PLAN_SECTION_TAGS 참고). 기존 값은 agents.py가
-- 이미 쓰던 '1-1'/'2-1'/'3-1'뿐이라 ENUM에 없는 값 정리 없이 바로 MODIFY해도 안전하다.
-- 몇 번을 다시 실행해도 안전하다(이미 ENUM이어도 같은 정의로 다시 MODIFY할 뿐).
ALTER TABLE plan_sections
    MODIFY COLUMN tag ENUM('1-1','2-1','3-1','G-01','G-02','G-03','G-04')
    NOT NULL COMMENT '양식 항목 코드 — 예비/초기(1-1/2-1/3-1) + 일반(G-01~G-04, PartⅡ 4섹션)';

-- [2026-09-28 신규] user_profiles.biz_status_cd — 국세청 사업자상태조회 응답 코드를 실제
-- MySQL ENUM으로 강제한다(app/models.py _BizStatusCd 참고). POST /biz-check가 쓰는 값만
-- 이 컬럼에 들어가므로(app/routers/profile.py) 기존 값 정리 없이 바로 MODIFY해도 안전하다.
ALTER TABLE user_profiles
    MODIFY COLUMN biz_status_cd ENUM('01','02','03') NULL COMMENT '01 계속사업자 / 02 휴업자 / 03 폐업자 (국세청 사업자상태조회 API 코드)';

-- [2026-09-28 신규] project_plan_inputs.main_industry(주업종)를 실제 MySQL ENUM으로
-- 강제한다(app/models.py _MainIndustry, app/pipeline_stages.py MAIN_INDUSTRIES 참고) —
-- 프론트 드롭다운 9종(개인/법인 전용). 예비창업자는 자유 텍스트를 입력하므로 별도
-- 컬럼(main_industry_free)으로 분리한다. 기존에 이 9종 밖의 자유 텍스트 값이 이미
-- 저장돼 있으면(과거엔 컬럼 하나였으므로) ENUM으로 바로 MODIFY하면 실패하니, 그런
-- 값은 먼저 main_industry_free로 옮기고 main_industry는 비운다.
UPDATE project_plan_inputs
SET main_industry_free = main_industry, main_industry = NULL
WHERE main_industry IS NOT NULL
  AND main_industry NOT IN ('제조','지식서비스','기계·소재','전기·전자','정보·통신','화공·섬유','바이오·의료·생명','에너지·자원','공예·디자인');
ALTER TABLE project_plan_inputs
    MODIFY COLUMN main_industry ENUM('제조','지식서비스','기계·소재','전기·전자','정보·통신','화공·섬유','바이오·의료·생명','에너지·자원','공예·디자인')
    NULL COMMENT '주업종(개인/법인 전용, 프론트 드롭다운 9종)';

-- =====================================================================
-- [2026-09-28, match_results 테이블 통합] project(1):match_results(N)로 나뉘어 있던
-- 예전 설계를 project(1):1로 합쳤다 — 실제 형제 저장소 agent-orchestration의 Run
-- 개념(아이디어·회사정보·공고선택·진행상태를 전부 담는 자기완결 단위 하나)과 우리
-- SB-138 "중단 후 새로 시작"(기존 프로젝트를 archive하고 새 프로젝트를 만드는 방식)
-- 패턴을 보면 project 한 행이 곧 실행 시도 하나이기 때문이다. 실제로 1:N이 쓰이는
-- 곳은 POST /projects/{id}/generate 하나뿐이었고, 그마저 그 함수 자체 docstring에
-- "[2026-09-15, 프론트 통합 임시 구현]"이라고 명시된 임시 데모 우회였다
-- (app/routers/projects.py generate_pipeline_result 참고).
--
-- *** 공유 AWS MySQL에 실행하기 전 사람이 반드시 먼저 확인할 것 ***
-- 아래 UPDATE는 한 project_id에 match_results가 여러 건 있으면(과거 데모 엔드포인트가
-- 호출할 때마다 새 세트를 쌓던 동작 탓) match_id가 가장 큰(=가장 최근) 행 하나만
-- projects로 옮기고 나머지는 조용히 버린다 — 병합 후에는 되돌릴 방법이 없다. 실행
-- 전에 반드시 아래 쿼리로 그런 프로젝트가 몇 건이나 있는지 먼저 확인해서 사람에게
-- 보고할 것:
--
--     SELECT project_id, COUNT(*) AS match_count
--     FROM match_results
--     GROUP BY project_id
--     HAVING COUNT(*) > 1;
--
-- 이 섹션은 로컬/스테이징에서 검증하는 용도로만 이 파일에 작성돼 있다 — 이 리팩터
-- 작업의 일부로 이 SQL을 공유 DB에 대해 직접 실행하지 않았다(그건 사람이 위 확인을
-- 거친 뒤 별도로 결정할 일이다).
-- =====================================================================

DELIMITER $$

-- 이 섹션 전용 헬퍼 — 위쪽 _add_col_if_missing은 이미 DROP돼 있으므로(줄 266) 여기서
-- 필요한 것만 다시 만들고, 섹션 끝에서 다시 DROP한다.
DROP PROCEDURE IF EXISTS _mr_add_col_if_missing $$
CREATE PROCEDURE _mr_add_col_if_missing(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_coldef TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_coldef);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT(p_table, '.', p_column, ' 추가함') AS result;
    ELSE
        SELECT CONCAT(p_table, '.', p_column, ' 이미 있음 — 건너뜀') AS result;
    END IF;
END $$

-- match_id를 참조하는 FK를 컬럼명 기준으로 찾아서 지운다 — CREATE TABLE에서 FK에
-- 이름을 안 줘서(app_schema.sql 참고) MySQL이 자동 생성한 이름(예: xxx_ibfk_1)이라
-- 하드코딩할 수 없다. 이미 지워졌으면(재실행) 아무 것도 안 한다.
DROP PROCEDURE IF EXISTS _mr_drop_fk_on_column_if_exists $$
CREATE PROCEDURE _mr_drop_fk_on_column_if_exists(IN p_table VARCHAR(64), IN p_column VARCHAR(64))
BEGIN
    DECLARE v_fk_name VARCHAR(64) DEFAULT NULL;
    SELECT CONSTRAINT_NAME INTO v_fk_name
    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
      AND REFERENCED_TABLE_NAME IS NOT NULL
    LIMIT 1;
    IF v_fk_name IS NOT NULL THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` DROP FOREIGN KEY `', v_fk_name, '`');
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT(p_table, '.', v_fk_name, ' FK 삭제함') AS result;
    ELSE
        SELECT CONCAT(p_table, '.', p_column, ' FK 없음 — 건너뜀') AS result;
    END IF;
END $$

DROP PROCEDURE IF EXISTS _mr_drop_col_if_exists $$
CREATE PROCEDURE _mr_drop_col_if_exists(IN p_table VARCHAR(64), IN p_column VARCHAR(64))
BEGIN
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` DROP COLUMN `', p_column, '`');
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT(p_table, '.', p_column, ' 컬럼 삭제함') AS result;
    ELSE
        SELECT CONCAT(p_table, '.', p_column, ' 이미 없음 — 건너뜀') AS result;
    END IF;
END $$

-- 위쪽 _add_index_if_missing도 이미 DROP돼 있으므로(줄 272) 이 섹션 전용으로 다시 만든다.
DROP PROCEDURE IF EXISTS _mr_add_index_if_missing $$
CREATE PROCEDURE _mr_add_index_if_missing(
    IN p_table VARCHAR(64), IN p_index VARCHAR(64), IN p_indexdef TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND INDEX_NAME = p_index
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD INDEX `', p_index, '` ', p_indexdef);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT(p_table, '.', p_index, ' 추가함') AS result;
    ELSE
        SELECT CONCAT(p_table, '.', p_index, ' 이미 있음 — 건너뜀') AS result;
    END IF;
END $$

-- 전체 이관을 한 프로시저로 감싼다 — match_results 테이블이 이미 없으면(=이전에 이미
-- 이 마이그레이션을 돌렸거나, 애초에 이 스키마 버전으로 새로 설치된 DB) 통째로
-- 건너뛴다. 그래서 이 스크립트를 여러 번 실행해도, match_results가 사라진 뒤에
-- 실행해도 안전하다(조용한 no-op).
DROP PROCEDURE IF EXISTS _migrate_match_results_into_projects $$
CREATE PROCEDURE _migrate_match_results_into_projects()
BEGIN
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'match_results'
    ) THEN
        -- (1) match_results가 소유했던 컬럼들을 projects에 추가한다(app_schema.sql의
        -- projects CREATE TABLE 정의, 컬럼 코멘트까지 동일하게 맞춘다).
        CALL _mr_add_col_if_missing('projects', 'notice_id', "VARCHAR(320) NULL COMMENT 'REFERENCES notices(notice_id). NULL이면 아직 공고를 선택하기 전(=아직 매칭 전)'");
        CALL _mr_add_col_if_missing('projects', 'fit_score', "DECIMAL(5,2) NULL COMMENT '매칭 적합도 점수'");
        CALL _mr_add_col_if_missing('projects', 'reason', "TEXT NULL COMMENT '매칭 사유/근거 서술'");
        CALL _mr_add_col_if_missing('projects', 'status', "ENUM('in_progress','waiting_resume','user_waiting','failed','completed','halted') NULL COMMENT '서비스 내부 상태(실행/재개대기/사용자대기/실패/완료/중단). NULL이면 아직 매칭 전'");
        CALL _mr_add_col_if_missing('projects', 'stage', "VARCHAR(30) NULL COMMENT '이어하기용 세부 진행 단계(app/pipeline_stages.py의 STAGE_* 상수 중 하나)'");
        CALL _mr_add_col_if_missing('projects', 'progress_percent', "TINYINT UNSIGNED NULL COMMENT 'stage 안에서도 오래 걸리는 구간의 진행률 0~100'");
        CALL _mr_add_col_if_missing('projects', 'worker_claimed_at', "DATETIME(6) NULL COMMENT '생성 작업을 처리 중인 워커의 마지막 클레임/하트비트 시각'");
        CALL _mr_add_col_if_missing('projects', 'failure_reason', "TEXT NULL COMMENT '마지막 실패 사유(에러 메시지)'");
        CALL _mr_add_col_if_missing('projects', 'last_error_kind', "ENUM('일시','입력','운영') NULL COMMENT '마지막 실패 원인 분류(NULL=실패 이력 없음/초기화됨)'");
        CALL _mr_add_col_if_missing('projects', 'resume_count', "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '자동 재개 소진 횟수(최대 5)'");
        CALL _mr_add_col_if_missing('projects', 'retry_count', "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '개별 호출 즉시 재시도 횟수(현재 미사용, 항상 0)'");
        CALL _mr_add_col_if_missing('projects', 'next_retry_at', "DATETIME(6) NULL COMMENT '다음 자동 재개 예정 시각(waiting_resume 전용)'");
        CALL _mr_add_col_if_missing('projects', 'resume_started_at', "DATETIME(6) NULL COMMENT '이번 실패 스트릭 시작 시각(재개 총 대기 상한 12시간 계산용)'");
        CALL _mr_add_col_if_missing('projects', 'archived_at', "DATETIME(6) NULL COMMENT '사용자가 프로젝트를 삭제해 보관 처리된 일시(NULL 가능)'");
        CALL _mr_add_col_if_missing('projects', 'archived_by', "VARCHAR(20) NULL COMMENT \"보관 처리 주체('user' 고정, NULL 가능)\"");

        -- (2) match_results 값을 projects로 옮긴다. *** 위 실행 전 확인 사항 참고 ***:
        -- project_id당 match_id 최댓값(가장 최근 매칭) 행만 명시적으로 골라 옮긴다 —
        -- 여러 건이 있으면 그 나머지는 이 UPDATE로 유실된다.
        UPDATE projects p
        JOIN (
            SELECT m1.*
            FROM match_results m1
            JOIN (
                SELECT project_id, MAX(match_id) AS max_match_id
                FROM match_results
                GROUP BY project_id
            ) latest ON latest.project_id = m1.project_id AND latest.max_match_id = m1.match_id
        ) m ON m.project_id = p.project_id
        SET
            p.notice_id = m.notice_id,
            p.fit_score = m.fit_score,
            p.reason = m.reason,
            p.status = m.status,
            p.stage = m.stage,
            p.progress_percent = m.progress_percent,
            p.worker_claimed_at = m.worker_claimed_at,
            p.failure_reason = m.failure_reason,
            p.last_error_kind = m.last_error_kind,
            p.resume_count = m.resume_count,
            p.retry_count = m.retry_count,
            p.next_retry_at = m.next_retry_at,
            p.resume_started_at = m.resume_started_at,
            p.archived_at = m.archived_at,
            p.archived_by = m.archived_by;

        -- projects.notice_id도 match_results.notice_id처럼 notices(notice_id)를 참조해야
        -- 한다(app_schema.sql projects 정의 참고). 이 IF 분기는 match_results가 있을 때
        -- 딱 한 번만 들어오므로(재실행 시 이 분기 자체가 건너뛰어짐) FK 중복 추가 걱정 없이
        -- 바로 추가한다.
        ALTER TABLE projects ADD CONSTRAINT fk_projects_notice FOREIGN KEY (notice_id) REFERENCES notices(notice_id) ON DELETE RESTRICT;

        -- (3) match_id -> project_id로 이름이 바뀌는 4개 자식 테이블(match_score_reasons/
        -- eligibility_checks/business_plans/agent_executions): project_id 컬럼을 추가하고
        -- match_results를 거쳐 backfill한 뒤, match_id의 FK와 컬럼을 지운다. 반드시
        -- match_results가 아직 있는 지금 이 시점에 처리해야 한다(백필 조인 대상이라서).
        CALL _mr_add_col_if_missing('match_score_reasons', 'project_id', "BIGINT UNSIGNED NULL COMMENT 'REFERENCES projects(project_id)'");
        UPDATE match_score_reasons t JOIN match_results m ON t.match_id = m.match_id SET t.project_id = m.project_id;
        CALL _mr_drop_fk_on_column_if_exists('match_score_reasons', 'match_id');
        CALL _mr_drop_col_if_exists('match_score_reasons', 'match_id');
        ALTER TABLE match_score_reasons MODIFY COLUMN project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)';
        CALL _mr_add_index_if_missing('match_score_reasons', 'ix_match_score_reasons_project', '(project_id)');
        ALTER TABLE match_score_reasons ADD CONSTRAINT fk_match_score_reasons_project FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE;

        CALL _mr_add_col_if_missing('eligibility_checks', 'project_id', "BIGINT UNSIGNED NULL COMMENT 'REFERENCES projects(project_id)'");
        UPDATE eligibility_checks t JOIN match_results m ON t.match_id = m.match_id SET t.project_id = m.project_id;
        CALL _mr_drop_fk_on_column_if_exists('eligibility_checks', 'match_id');
        CALL _mr_drop_col_if_exists('eligibility_checks', 'match_id');
        ALTER TABLE eligibility_checks MODIFY COLUMN project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)';
        CALL _mr_add_index_if_missing('eligibility_checks', 'ix_eligibility_checks_project', '(project_id)');
        ALTER TABLE eligibility_checks ADD CONSTRAINT fk_eligibility_checks_project FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE;

        CALL _mr_add_col_if_missing('business_plans', 'project_id', "BIGINT UNSIGNED NULL COMMENT 'REFERENCES projects(project_id)'");
        UPDATE business_plans t JOIN match_results m ON t.match_id = m.match_id SET t.project_id = m.project_id;
        CALL _mr_drop_fk_on_column_if_exists('business_plans', 'match_id');
        CALL _mr_drop_col_if_exists('business_plans', 'match_id');
        ALTER TABLE business_plans MODIFY COLUMN project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)';
        CALL _mr_add_index_if_missing('business_plans', 'ix_business_plans_project', '(project_id)');
        ALTER TABLE business_plans ADD CONSTRAINT fk_business_plans_project FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE;

        -- agent_executions.match_id는 nullable이었다 — project_id도 nullable로 유지.
        CALL _mr_add_col_if_missing('agent_executions', 'project_id', "BIGINT UNSIGNED NULL COMMENT 'REFERENCES projects(project_id), nullable'");
        UPDATE agent_executions t JOIN match_results m ON t.match_id = m.match_id SET t.project_id = m.project_id;
        CALL _mr_drop_fk_on_column_if_exists('agent_executions', 'match_id');
        CALL _mr_drop_col_if_exists('agent_executions', 'match_id');
        CALL _mr_add_index_if_missing('agent_executions', 'ix_agent_executions_project_task', '(project_id, task_key, attempt_no)');
        ALTER TABLE agent_executions ADD CONSTRAINT fk_agent_executions_project FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE SET NULL;

        -- (4) project_id와 match_id를 둘 다 갖고 있던 2개 테이블(generation_failure_alerts/
        -- notifications): project_id는 이미 채워져 있으므로 이제 불필요해진 match_id
        -- 컬럼과 그 FK만 지우면 된다.
        CALL _mr_drop_fk_on_column_if_exists('generation_failure_alerts', 'match_id');
        CALL _mr_drop_col_if_exists('generation_failure_alerts', 'match_id');
        CALL _mr_drop_fk_on_column_if_exists('notifications', 'match_id');
        CALL _mr_drop_col_if_exists('notifications', 'match_id');

        -- (5) match_results 테이블 자체를 지운다 — 위에서 이 테이블을 참조하던 FK를
        -- 전부 지웠으므로 이제 안전하게 DROP할 수 있다.
        DROP TABLE match_results;

        SELECT 'match_results -> projects 이관 완료' AS result;
    ELSE
        SELECT 'match_results 테이블이 이미 없음 — 이관 완료된 상태로 보고 건너뜀' AS result;
    END IF;
END $$

DELIMITER ;

-- 컬럼(stage/worker_claimed_at/status/notice_id)이 아직 없는 첫 실행에서는 이 인덱스들을
-- 걸 수 없으므로, 반드시 _migrate_match_results_into_projects()로 컬럼을 다 채운 뒤에
-- 실행해야 한다 — 순서를 바꾸면 "Unknown column" 에러로 바로 막힌다.
CALL _migrate_match_results_into_projects();

-- app_schema.sql과 동일한 인덱스(stage+worker_claimed_at/status/notice_id)를 projects에도
-- 걸어준다 — match_results에 있던 ix_match_results_stage_claim/ix_match_results_status/
-- ix_match_results_notice와 같은 역할.
CALL _mr_add_index_if_missing('projects', 'ix_projects_stage_claim', '(stage, worker_claimed_at)');
CALL _mr_add_index_if_missing('projects', 'ix_projects_status', '(status)');
CALL _mr_add_index_if_missing('projects', 'ix_projects_notice', '(notice_id)');

DROP PROCEDURE IF EXISTS _migrate_match_results_into_projects;
DROP PROCEDURE IF EXISTS _mr_drop_col_if_exists;
DROP PROCEDURE IF EXISTS _mr_drop_fk_on_column_if_exists;
DROP PROCEDURE IF EXISTS _mr_add_index_if_missing;
DROP PROCEDURE IF EXISTS _mr_add_col_if_missing;

-- [2026-09-28 신규] 프론트 요청 4 — 완전 삭제 최소 감사 로그. 새 테이블이라
-- CREATE TABLE IF NOT EXISTS로 충분하다(app/models.py PermanentDeletionLog 참고).
CREATE TABLE IF NOT EXISTS permanent_deletion_log (
    log_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '완전 삭제 로그 고유 식별자',
    deleted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '완전 삭제 처리 일시 — 식별자 없음(프로젝트/계정과 연결 안 됨)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 최종 확인용 — 실행 후 이 두 개를 결과로 같이 보내주시면 더 빠지는 컬럼이 있는지 바로 확인 가능합니다.
SHOW COLUMNS FROM companies;
SHOW COLUMNS FROM projects;
