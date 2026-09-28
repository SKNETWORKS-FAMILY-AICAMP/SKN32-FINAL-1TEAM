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

-- [2026-09-22 신규] 생성 작업(계획서/프로토타입) 비동기화 — DB 클레임 컬럼 하나로
-- Redis 없이 재시작·다중 워커에 대응한다(app/routers/projects.py _try_claim_and_run 참고).
CALL _add_col_if_missing('match_results', 'worker_claimed_at', "DATETIME(6) NULL COMMENT '생성 작업을 처리 중인 워커의 마지막 클레임/하트비트 시각'");
CALL _add_col_if_missing('match_results', 'failure_reason', "TEXT NULL COMMENT '마지막 실패 사유(에러 메시지) — status=waiting_resume/failed일 때 값 있음'");

-- [2026-09-23 신규, 2026-09-26 정정] 실패 시 자동 재개(최대 5회, 15->30->60->120->240분
-- 백오프, 총 대기 상한 12시간) — 공식 기능정의서 v1.9(R-11) 기준. app/routers/projects.py
-- GENERATION_RESUME_MAX_ATTEMPTS/GENERATION_RESUME_TOTAL_CAP_SECONDS 참고.
CALL _add_col_if_missing('match_results', 'retry_count', "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '자동 재개 소진 횟수(최대 5)'");
CALL _add_col_if_missing('match_results', 'next_retry_at', "DATETIME(6) NULL COMMENT '다음 자동 재개 예정 시각(waiting_resume 전용)'");
CALL _add_col_if_missing('match_results', 'resume_started_at', "DATETIME(6) NULL COMMENT '이번 실패 스트릭 시작 시각(재개 총 대기 상한 12시간 계산용)'");

-- [2026-09-27 신규, SB-133] retry_count(위에서 만든 컬럼)는 사실 스펙의 Run.resumeCount
-- (재개 횟수)였다 — Run.retryCount(개별 호출 즉시 재시도 횟수)와 이름이 겹쳐 혼동을
-- 일으키므로 resume_count로 바로잡고, 진짜 retry_count는 새로 만든다(지금은 파이프라인이
-- 100% 더미라 항상 0 — 실제 Agent 호출 계층이 생기면 그때 채운다). 순서 중요: 먼저
-- 개명하고, 그다음에 비어진 retry_count 이름으로 새 컬럼을 추가한다.
CALL _rename_col_if_needed('match_results', 'retry_count', 'resume_count', "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '자동 재개 소진 횟수(최대 5)'");
CALL _add_col_if_missing('match_results', 'retry_count', "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '개별 호출 즉시 재시도 횟수(현재 미사용, 항상 0)'");

-- [2026-09-27 신규, SB-134] 실패 원인 분류(일시/입력/운영) — 공식 기능정의서 v1.9
-- Run.lastErrorKind, R-11. app/pipeline_stages.py classify_error_kind 참고.
CALL _add_col_if_missing('match_results', 'last_error_kind', "ENUM('일시','입력','운영') NULL COMMENT '마지막 실패 원인 분류(NULL=실패 이력 없음/초기화됨)'");

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
UPDATE agent_executions SET status = 'completed' WHERE status = 'success';
ALTER TABLE match_results
    MODIFY COLUMN status ENUM('in_progress','waiting_resume','user_waiting','failed','completed','halted')
    NOT NULL DEFAULT 'in_progress' COMMENT '서비스 내부 상태(실행/재개대기/사용자대기/실패/완료/중단)';
ALTER TABLE agent_executions
    MODIFY COLUMN status ENUM('in_progress','waiting_resume','user_waiting','failed','completed','halted')
    NOT NULL COMMENT '서비스 내부 상태(실행/재개대기/사용자대기/실패/완료/중단) — match_results.status와 같은 enum';

-- [2026-09-23 신규] 자동 재시도 5회 소진 후 확정 실패할 때마다 쌓는 관리자 알림 로그
-- (app/models.py GenerationFailureAlert 참고) — 새 테이블이라 CREATE TABLE IF NOT EXISTS로
-- 충분하다(컬럼 추가 마이그레이션 절차 불필요).
CREATE TABLE IF NOT EXISTS generation_failure_alerts (
    alert_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '알림 고유 식별자',
    match_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES match_results(match_id)',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    stage VARCHAR(30) NOT NULL COMMENT '실패가 확정된 시점의 stage',
    resume_count TINYINT UNSIGNED NOT NULL COMMENT '확정 시점까지 소진한 자동 재개 횟수',
    failure_reason TEXT NULL COMMENT '마지막 실패 사유',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    acknowledged_at DATETIME(6) NULL COMMENT '관리자 확인 처리 시각(NULL이면 미확인)',
    KEY ix_generation_failure_alerts_match (match_id),
    KEY ix_generation_failure_alerts_unacked (acknowledged_at),
    FOREIGN KEY (match_id) REFERENCES match_results(match_id) ON DELETE CASCADE,
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

-- [2026-09-27 신규, SB-141] 사용자용 작업 알림(화면 헤더 종모양) — 새 테이블이라
-- CREATE TABLE IF NOT EXISTS로 충분하다(컬럼 추가 마이그레이션 절차 불필요).
CREATE TABLE IF NOT EXISTS notifications (
    notification_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '알림 고유 식별자',
    match_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES match_results(match_id)',
    project_id BIGINT UNSIGNED NOT NULL COMMENT 'REFERENCES projects(project_id)',
    kind ENUM('문서평가','산출물확인','표현검수','실패') NOT NULL COMMENT '완료된 단계 또는 실패',
    failure_scope ENUM('실행','재작성') NULL COMMENT "kind='실패'일 때만: 실행 실패 또는 재작성 실패",
    target_step TINYINT UNSIGNED NULL COMMENT '알림을 누르면 들어갈 화면 번호(실패는 NULL — 이어하기 목록으로 연결)',
    channel VARCHAR(10) NOT NULL DEFAULT '화면' COMMENT '알림 경로. 지금은 화면 하나뿐(메일은 향후 도입)',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    read_at DATETIME(6) NULL COMMENT '사용자가 읽은 시각(NULL이면 안읽음)',
    KEY ix_notifications_project (project_id),
    KEY ix_notifications_match (match_id),
    FOREIGN KEY (match_id) REFERENCES match_results(match_id) ON DELETE CASCADE,
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

DROP PROCEDURE IF EXISTS _add_col_if_missing;

-- 복구 루프가 10초마다 WHERE stage=X AND (worker_claimed_at IS NULL OR 오래됨)을 도는데,
-- 인덱스 없이 두면 테이블이 커질수록 매번 풀스캔이 된다(app_schema.sql 주석 참고).
CALL _add_index_if_missing('match_results', 'ix_match_results_stage_claim', '(stage, worker_claimed_at)');

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

-- 최종 확인용 — 실행 후 이 두 개를 결과로 같이 보내주시면 더 빠지는 컬럼이 있는지 바로 확인 가능합니다.
SHOW COLUMNS FROM companies;
SHOW COLUMNS FROM projects;
