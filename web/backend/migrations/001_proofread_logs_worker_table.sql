-- [SB-246, 2026-10-05] proofread_logs — 오케스트레이터 워커가 INSERT하는 테이블로 바꾼다.
--
-- 왜: 이 표는 원래 business_plans 기준(plan_id NOT NULL)이었다. 워커는 plan 없이 project_id로 행을 쓰고,
--     학습에 반영된(recovery_status='trained') 행은 프로젝트를 지워도 남겨야 한다
--     (agent-orchestration/docs/웹연동_변경사항_웹팀전달.md 4.1 · 11.7).
--
-- 바뀌는 것:
--   1. plan_id          NOT NULL → NULL 허용, 외래 키를 ON DELETE CASCADE → ON DELETE SET NULL
--                       (더미 시절 plan 행이 지워질 때 trained 행이 같이 지워지지 않게)
--   2. project_id       새 컬럼 — projects(project_id), NULL 허용 + ON DELETE SET NULL, 인덱스
--   3. model_version    새 컬럼 — 그 시도를 만든 검수 모델 이름
--   4. 기존 행 채우기    project_id ← business_plans.project_id, model_version ← 그 plan의 마지막 verdicts.model_version
--
-- 몇 번을 실행해도 안전하다(이미 바뀐 부분은 건너뛴다). 002를 적용한 뒤에 다시 실행해도 안전하다(plan_id · business_plans가 없으면
-- 1 · 4를 건너뛴다 — 마이그레이션을 모두 다시 적용하는 배포 방식에서도 오류가 나지 않는다, SB-265 리허설로 확인). MySQL 8 기준.
--
-- 실행: mysql -u <계정> -p <DB 이름> < migrations/001_proofread_logs_worker_table.sql
-- 순서: 웹 스키마(app_schema.sql)가 먼저 있어야 하고, 이 스크립트는 orch_ 테이블 적용(sql/orchestrator_schema.sql)보다
--       먼저 실행한다. 공유 DB 적용은 팀 합의 뒤에 한다(적용 전에는 워커가 이 표 쓰기만 건너뛴다 — 검수 · 실행은 정상).

DELIMITER $$

DROP PROCEDURE IF EXISTS _sb246_migrate_proofread_logs $$
CREATE PROCEDURE _sb246_migrate_proofread_logs()
BEGIN
    DECLARE v_fk VARCHAR(64);
    DECLARE v_done INT DEFAULT 0;
    DECLARE v_has_plan INT DEFAULT 0;
    DECLARE c_fk CURSOR FOR
        SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs'
          AND COLUMN_NAME = 'plan_id' AND REFERENCED_TABLE_NAME = 'business_plans';
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;

    -- 002 뒤에 다시 실행하는 경우 plan_id · business_plans가 이미 없다 — 그 부분(1 · 4)은 건너뛴다
    SELECT COUNT(*) INTO v_has_plan FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs' AND COLUMN_NAME = 'plan_id';

    -- 1. plan_id: 기존 외래 키(ON DELETE CASCADE)를 지우고 NULL 허용으로 바꾼 뒤 ON DELETE SET NULL로 다시 건다
    IF v_has_plan > 0 THEN
    IF EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
          ON k.CONSTRAINT_SCHEMA = rc.CONSTRAINT_SCHEMA AND k.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
        WHERE rc.CONSTRAINT_SCHEMA = DATABASE() AND rc.TABLE_NAME = 'proofread_logs'
          AND k.COLUMN_NAME = 'plan_id' AND rc.DELETE_RULE <> 'SET NULL'
    ) THEN
        OPEN c_fk;
        FETCH c_fk INTO v_fk;
        CLOSE c_fk;
        IF v_fk IS NOT NULL THEN
            SET @ddl = CONCAT('ALTER TABLE proofread_logs DROP FOREIGN KEY `', v_fk, '`');
            PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
        END IF;
    END IF;

    ALTER TABLE proofread_logs MODIFY plan_id BIGINT UNSIGNED NULL;

    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs'
          AND COLUMN_NAME = 'plan_id' AND REFERENCED_TABLE_NAME = 'business_plans'
    ) THEN
        ALTER TABLE proofread_logs
            ADD CONSTRAINT fk_proofread_logs_plan FOREIGN KEY (plan_id)
            REFERENCES business_plans(plan_id) ON DELETE SET NULL;
    END IF;
    END IF;

    -- 2. project_id
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs' AND COLUMN_NAME = 'project_id'
    ) THEN
        ALTER TABLE proofread_logs ADD COLUMN project_id BIGINT UNSIGNED NULL AFTER plan_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs' AND INDEX_NAME = 'ix_proofread_logs_project'
    ) THEN
        ALTER TABLE proofread_logs ADD KEY ix_proofread_logs_project (project_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs'
          AND COLUMN_NAME = 'project_id' AND REFERENCED_TABLE_NAME = 'projects'
    ) THEN
        ALTER TABLE proofread_logs
            ADD CONSTRAINT fk_proofread_logs_project FOREIGN KEY (project_id)
            REFERENCES projects(project_id) ON DELETE SET NULL;
    END IF;

    -- 3. model_version
    IF NOT EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs' AND COLUMN_NAME = 'model_version'
    ) THEN
        ALTER TABLE proofread_logs ADD COLUMN model_version VARCHAR(50) NULL AFTER recovery_label;
    END IF;

    -- 4. 기존 행 채우기 (더미 시절 행 — 이미 값이 있으면 건드리지 않는다)
    IF v_has_plan > 0 AND EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'business_plans'
    ) THEN
        UPDATE proofread_logs pl
            JOIN business_plans bp ON bp.plan_id = pl.plan_id
            SET pl.project_id = bp.project_id
            WHERE pl.project_id IS NULL;

        IF EXISTS (
            SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'verdicts'
        ) THEN
            UPDATE proofread_logs pl
                SET pl.model_version = (
                    SELECT v.model_version FROM verdicts v WHERE v.plan_id = pl.plan_id ORDER BY v.verdict_id DESC LIMIT 1
                )
                WHERE pl.model_version IS NULL AND pl.plan_id IS NOT NULL;
        END IF;
    END IF;

    SELECT 'proofread_logs 마이그레이션 완료' AS result;
END $$

DELIMITER ;

CALL _sb246_migrate_proofread_logs();
DROP PROCEDURE _sb246_migrate_proofread_logs;
