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

-- [2026-09-23 신규] 실패 시 자동 재시도(최대 5회, 15->30->60->120->240초 백오프) —
-- app/routers/projects.py GENERATION_RETRY_MAX_ATTEMPTS 참고.
CALL _add_col_if_missing('match_results', 'retry_count', "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '자동 재시도 소진 횟수(최대 5)'");
CALL _add_col_if_missing('match_results', 'next_retry_at', "DATETIME(6) NULL COMMENT '다음 자동 재시도 예정 시각(waiting_resume 전용)'");

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
    retry_count TINYINT UNSIGNED NOT NULL COMMENT '확정 시점까지 소진한 자동 재시도 횟수',
    failure_reason TEXT NULL COMMENT '마지막 실패 사유',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    acknowledged_at DATETIME(6) NULL COMMENT '관리자 확인 처리 시각(NULL이면 미확인)',
    KEY ix_generation_failure_alerts_match (match_id),
    KEY ix_generation_failure_alerts_unacked (acknowledged_at),
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

-- 최종 확인용 — 실행 후 이 두 개를 결과로 같이 보내주시면 더 빠지는 컬럼이 있는지 바로 확인 가능합니다.
SHOW COLUMNS FROM companies;
SHOW COLUMNS FROM projects;
