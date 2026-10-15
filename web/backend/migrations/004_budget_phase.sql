-- [SB-328, 2026-10-10] project_budget_items에 단계(phase) 컬럼 추가 — 예비창업 사업비를 1단계 · 2단계로 나누기 위한 값.
--
-- 오케스트레이터(request_start)가 이 컬럼을 읽는다. 컬럼이 없으면 없는 것으로 보고 돌아가고(오류 아님), 예비창업 사업비는
-- 단계를 알 수 없어 1 · 2단계 표에 들어가지 못한다.
--
-- 값: '1단계' · '2단계'(예비창업) 또는 NULL(초기창업 · 개인사업자 · 법인). 기존 행은 모두 NULL로 남는다(데이터를 바꾸지 않는다).
--
-- 번호 안내: 003은 feature/sb-269-web-final의 checklist_items 마이그레이션이다. 이 브랜치에는 아직 없으므로 병합 때
--   001 → 002 → 003 → 004 순서로 적용한다. 004는 003과 서로 의존하지 않는다.
--
-- 몇 번을 실행해도 안전하다(이미 있으면 건너뛴다). MySQL 8 기준.
--
-- 실행: mysql -u <계정> -p <DB 이름> < migrations/004_budget_phase.sql

SET @sb328_has_phase := (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'project_budget_items' AND COLUMN_NAME = 'phase'
);

SET @sb328_sql := IF(
    @sb328_has_phase = 0,
    'ALTER TABLE project_budget_items ADD COLUMN phase VARCHAR(10) NULL COMMENT ''사업비 단계(예비창업: 1단계/2단계, 그 밖은 NULL)'' AFTER item_order',
    'SELECT 1'
);

PREPARE sb328_stmt FROM @sb328_sql;
EXECUTE sb328_stmt;
DEALLOCATE PREPARE sb328_stmt;
