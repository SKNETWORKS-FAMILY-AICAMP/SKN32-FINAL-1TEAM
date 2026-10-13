-- [SB-382, 2026-10-13] project_plan_inputs에 목표 고객(target_customer) 컬럼 추가 — 사용자가 직접 입력하는 목표 고객(선택).
--
-- 오케스트레이터(request_start)가 이 컬럼을 읽어 작성 · 검증 AI에 넘긴다. 컬럼이 없으면 없는 것으로 보고 돌아가고(오류 아님),
-- 값이 비어 있으면 AI가 "확인 필요"로 쓴다. 웹 배포와 공유 DB 적용이 끝난 날부터 입력한 값이 들어간다.
--
-- 값: 사용자가 입력한 글(200자 이내) 또는 NULL. 기존 행은 모두 NULL로 남는다(데이터를 바꾸지 않는다).
--
-- 번호 안내: 003은 feature/sb-269-web-final의 checklist_items 마이그레이션이다. 이 브랜치에는 아직 없으므로 병합 때
--   001 → 002 → 003 → 004 → 005 순서로 적용한다. 005는 003 · 004와 서로 의존하지 않는다.
--
-- 몇 번을 실행해도 안전하다(이미 있으면 건너뛴다). MySQL 8 기준.
--
-- 실행: mysql -u <계정> -p <DB 이름> < migrations/005_target_customer.sql

SET @sb382_has_target_customer := (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'project_plan_inputs' AND COLUMN_NAME = 'target_customer'
);

SET @sb382_sql := IF(
    @sb382_has_target_customer = 0,
    'ALTER TABLE project_plan_inputs ADD COLUMN target_customer VARCHAR(200) NULL COMMENT ''목표 고객(사용자 입력, 선택) — 오케스트레이터가 작성 · 검증 AI에 넘김, 비면 AI가 "확인 필요"로 씀'' AFTER occupation',
    'SELECT 1'
);

PREPARE sb382_stmt FROM @sb382_sql;
EXECUTE sb382_stmt;
DEALLOCATE PREPARE sb382_stmt;
