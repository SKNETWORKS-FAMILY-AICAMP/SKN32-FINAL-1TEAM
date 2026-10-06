-- [SB-247, 2026-10-06] 더미 파이프라인 테이블 · 컬럼 삭제 — 실행 건이 오케스트레이터(orch_ 테이블)로 넘어간 뒤 쓴다.
--
-- ★ 되돌릴 수 없다 ★ 아래 테이블의 데이터(더미 계획서 · 산출물 · 점수 · 실행 기록)가 모두 사라진다.
--   - 오케스트레이터 전환(SB-239 SB-241~246)이 배포된 뒤에, 더미 데이터를 버려도 된다고 합의한 DB에서만 실행한다.
--   - 팀 공유 DB에는 합의 전에 실행하지 않는다. 실행 전에 mysqldump로 백업한다.
--   - 반드시 001_proofread_logs_worker_table.sql 뒤에 실행한다(proofread_logs의 plan_id · section_id를 먼저 떼어 낸다).
--
-- 지우는 것:
--   테이블 13개: business_plans, plan_sections, plan_canonical_data, plan_score_reasons, artifacts,
--                artifact_score_reasons, verdicts, match_candidates, match_score_reasons, eligibility_checks,
--                format_findings, agent_executions, verification_score_history
--   컬럼: proofread_logs.plan_id · section_id, projects 진행 컬럼 13개(+ 외래 키 · 인덱스),
--         verification_policies.regenerate_cap, generation_failure_alerts.regenerate_exhausted
-- 남기는 것: projects.fit_score · reason(확인 전), project_budget_items · project_schedule_items · project_partners.
--
-- 몇 번을 실행해도 안전하다(없는 것은 건너뛴다). MySQL 8 기준.
--
-- 실행: mysql -u <계정> -p <DB 이름> < migrations/002_drop_dummy_pipeline.sql

DELIMITER $$

DROP PROCEDURE IF EXISTS _sb247_drop_fks $$
CREATE PROCEDURE _sb247_drop_fks(IN p_table VARCHAR(64), IN p_column VARCHAR(64))
BEGIN
    -- p_table.p_column에 걸린 외래 키를 이름과 상관없이 모두 지운다
    DECLARE v_name VARCHAR(64);
    DECLARE v_done INT DEFAULT 0;
    DECLARE c CURSOR FOR
        SELECT DISTINCT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
          AND REFERENCED_TABLE_NAME IS NOT NULL;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;
    OPEN c;
    read_loop: LOOP
        FETCH c INTO v_name;
        IF v_done = 1 THEN LEAVE read_loop; END IF;
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` DROP FOREIGN KEY `', v_name, '`');
        PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END LOOP;
    CLOSE c;
END $$

DROP PROCEDURE IF EXISTS _sb247_drop_col $$
CREATE PROCEDURE _sb247_drop_col(IN p_table VARCHAR(64), IN p_column VARCHAR(64))
BEGIN
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
    ) THEN
        CALL _sb247_drop_fks(p_table, p_column);
        -- 이 컬럼만으로 이뤄진 인덱스 · 컬럼이 들어간 복합 인덱스는 컬럼과 함께 정리된다(MySQL이 컬럼 삭제 때 처리)
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` DROP COLUMN `', p_column, '`');
        PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;
END $$

DROP PROCEDURE IF EXISTS _sb247_drop_dummy_pipeline $$
CREATE PROCEDURE _sb247_drop_dummy_pipeline()
BEGIN
    -- 1. proofread_logs가 더미 테이블을 가리키는 컬럼 떼기 (001 이후)
    CALL _sb247_drop_col('proofread_logs', 'plan_id');
    CALL _sb247_drop_col('proofread_logs', 'section_id');

    -- 2. 더미 테이블 삭제 (자식 → 부모 순서). 외래 키 검사를 잠시 끄고 지운다.
    SET FOREIGN_KEY_CHECKS = 0;
    DROP TABLE IF EXISTS verification_score_history;
    DROP TABLE IF EXISTS agent_executions;
    DROP TABLE IF EXISTS verdicts;
    DROP TABLE IF EXISTS format_findings;
    DROP TABLE IF EXISTS artifact_score_reasons;
    DROP TABLE IF EXISTS artifacts;
    DROP TABLE IF EXISTS plan_score_reasons;
    DROP TABLE IF EXISTS plan_canonical_data;
    DROP TABLE IF EXISTS plan_sections;
    DROP TABLE IF EXISTS business_plans;
    DROP TABLE IF EXISTS eligibility_checks;
    DROP TABLE IF EXISTS match_score_reasons;
    DROP TABLE IF EXISTS match_candidates;
    SET FOREIGN_KEY_CHECKS = 1;

    -- 3. projects 진행 컬럼 (notice_id의 외래 키 · ix_projects_notice / ix_projects_status / ix_projects_stage_claim 인덱스 포함)
    IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND INDEX_NAME = 'ix_projects_stage_claim') THEN
        ALTER TABLE projects DROP INDEX ix_projects_stage_claim;
    END IF;
    IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND INDEX_NAME = 'ix_projects_status') THEN
        ALTER TABLE projects DROP INDEX ix_projects_status;
    END IF;
    CALL _sb247_drop_col('projects', 'notice_id');   -- 외래 키 · ix_projects_notice도 함께
    CALL _sb247_drop_col('projects', 'status');
    CALL _sb247_drop_col('projects', 'stage');
    CALL _sb247_drop_col('projects', 'progress_percent');
    CALL _sb247_drop_col('projects', 'worker_claimed_at');
    CALL _sb247_drop_col('projects', 'failure_reason');
    CALL _sb247_drop_col('projects', 'last_error_kind');
    CALL _sb247_drop_col('projects', 'resume_count');
    CALL _sb247_drop_col('projects', 'retry_count');
    CALL _sb247_drop_col('projects', 'next_retry_at');
    CALL _sb247_drop_col('projects', 'resume_started_at');
    CALL _sb247_drop_col('projects', 'is_regenerating');
    CALL _sb247_drop_col('projects', 'regenerate_fail_streak');

    -- 4. "처음부터 다시 생성"(없는 기능) 컬럼
    CALL _sb247_drop_col('verification_policies', 'regenerate_cap');
    CALL _sb247_drop_col('generation_failure_alerts', 'regenerate_exhausted');

    SELECT 'SB-247 더미 파이프라인 삭제 완료' AS result;
END $$

DELIMITER ;

CALL _sb247_drop_dummy_pipeline();
DROP PROCEDURE _sb247_drop_dummy_pipeline;
DROP PROCEDURE _sb247_drop_col;
DROP PROCEDURE _sb247_drop_fks;
