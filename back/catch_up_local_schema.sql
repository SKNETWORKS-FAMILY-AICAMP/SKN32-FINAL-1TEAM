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
CALL _add_col_if_missing('match_results', 'failure_reason', "TEXT NULL COMMENT '생성 작업이 실패한 사유(에러 메시지) — status=failed일 때만 값 있음'");

-- [2026-09-22 신규] verification_checklist_items v1.8 구조 교체(카테고리별 8항목·15점).
-- 예전 5항목/100점 데이터는 item_code/item_no가 있을 자리 자체가 없어서 컬럼만 추가해선
-- 값을 못 채운다 — 이 테이블은 사용자 데이터가 아니라 관리자 기준표라 안전하게 통째로
-- 비우고 다시 심는다. 이 스크립트 실행 후 `python seed_dummy_admin_data.py`를 다시
-- 돌리면(또는 app_schema.sql을 재적용하면) 새 v1.8 16항목이 채워진다.
DELETE FROM verification_checklist_items;
CALL _add_col_if_missing('verification_checklist_items', 'item_code', "VARCHAR(50) NOT NULL UNIQUE COMMENT 'artifact_score_reasons.item_code와 매칭되는 항목 코드'");
CALL _add_col_if_missing('verification_checklist_items', 'item_no', "TINYINT UNSIGNED NOT NULL COMMENT '카테고리 안에서의 순번(1~8)'");

DROP PROCEDURE IF EXISTS _add_col_if_missing;

-- 복구 루프가 10초마다 WHERE stage=X AND (worker_claimed_at IS NULL OR 오래됨)을 도는데,
-- 인덱스 없이 두면 테이블이 커질수록 매번 풀스캔이 된다(app_schema.sql 주석 참고).
CALL _add_index_if_missing('match_results', 'ix_match_results_stage_claim', '(stage, worker_claimed_at)');

DROP PROCEDURE IF EXISTS _add_index_if_missing;

-- start_type/notify_region/notify_industry를 이미 NULL 허용으로 바꿔두셨다면 아래 3줄은
-- 각각 "already NULL"이어도 에러 없이 그냥 다시 적용될 뿐이라 안전하다(아직 안 하셨다면 이걸로 처리됨).
ALTER TABLE companies MODIFY start_type VARCHAR(32) NULL;
ALTER TABLE projects MODIFY notify_region VARCHAR(32) NULL, MODIFY notify_industry VARCHAR(32) NULL;

-- 최종 확인용 — 실행 후 이 두 개를 결과로 같이 보내주시면 더 빠지는 컬럼이 있는지 바로 확인 가능합니다.
SHOW COLUMNS FROM companies;
SHOW COLUMNS FROM projects;
