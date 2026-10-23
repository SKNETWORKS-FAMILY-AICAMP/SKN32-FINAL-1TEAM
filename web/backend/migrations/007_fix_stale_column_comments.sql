-- [SB-420, 2026-10-21] 낡은 DB 칸 설명(COMMENT) 정리 — 이미 지운 옛 파이프라인 표를 가리키던 칸 설명 4곳을 고친다.
--
-- 왜: 마이그레이션 002에서 business_plans · artifacts · artifact_score_reasons · plan_score_reasons 같은 표를 지웠는데,
--   살아 있는 표의 칸 설명에는 그 이름이 남아 있다. 관리자 화면 · ERD · 설계 문서가 DB 칸 설명을 그대로 옮겨 쓰므로
--   없는 표 이름이 문서까지 퍼진다.
--
-- 바꾸는 것(칸 설명만):
--   proofread_logs.score                      "… — business_plans.doc_score와 같은 형식"        → 같은 형식 언급 삭제
--   verification_checklist_items.item_code    "artifact_score_reasons.item_code와 매칭 …"        → 산출물 점수 보고서의 항목 코드와 매칭
--   verification_checklist_items.category     "… artifacts.category의 webdev/aiapi · onepage"    → 웹개발 · AI API / 원페이지 카테고리
--   rubric_items.item_code                    "plan_score_reasons.item_code와 매칭 …"            → 계획서 점수 보고서의 항목 코드와 매칭
--
-- 타입 · NULL 여부 · 기본값 · 인덱스(UNIQUE 포함)와 데이터는 바뀌지 않는다. MODIFY가 현재 정의(app_schema.sql과 같음)를 그대로 다시 적는다.
-- 새 문구는 app_schema.sql의 칸 설명과 같다(tests/test_schema_comments.py가 둘이 같은지 본다).
--
-- 몇 번을 실행해도 안전하다 — 옛 이름이 남아 있는 칸만 고치고, 이미 고쳤거나 칸이 없으면 건너뛴다. MySQL 8 기준.
-- 새 DB는 app_schema.sql에 이미 새 문구가 들어 있어 이 파일이 아무것도 바꾸지 않는다.
--
-- 실행: mysql -u <계정> -p <DB 이름> < migrations/007_fix_stale_column_comments.sql
-- 확인: SELECT TABLE_NAME, COLUMN_NAME, COLUMN_COMMENT FROM INFORMATION_SCHEMA.COLUMNS
--        WHERE TABLE_SCHEMA = DATABASE() AND (COLUMN_COMMENT LIKE '%business_plans%' OR COLUMN_COMMENT LIKE '%artifact_score_reasons%'
--              OR COLUMN_COMMENT LIKE '%plan_score_reasons%' OR COLUMN_COMMENT LIKE '%artifacts.category%');   -- 0행이면 정리 끝

-- 1) proofread_logs.score
SET @sb420_sql := IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'proofread_logs' AND COLUMN_NAME = 'score'
        AND LOCATE('business_plans', COLUMN_COMMENT) > 0) = 1,
    'ALTER TABLE proofread_logs MODIFY COLUMN score DECIMAL(5,2) NOT NULL DEFAULT 100.00 COMMENT ''이 시도의 윤문 품질 점수(0~100, 소수 둘째 자리까지)''',
    'SELECT 1'
);
PREPARE sb420_stmt FROM @sb420_sql;
EXECUTE sb420_stmt;
DEALLOCATE PREPARE sb420_stmt;

-- 2) verification_checklist_items.item_code
SET @sb420_sql := IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'verification_checklist_items' AND COLUMN_NAME = 'item_code'
        AND LOCATE('artifact_score_reasons', COLUMN_COMMENT) > 0) = 1,
    'ALTER TABLE verification_checklist_items MODIFY COLUMN item_code VARCHAR(50) NOT NULL COMMENT ''산출물 채점 결과(점수 보고서)의 항목 코드와 매칭되는 항목 코드''',
    'SELECT 1'
);
PREPARE sb420_stmt FROM @sb420_sql;
EXECUTE sb420_stmt;
DEALLOCATE PREPARE sb420_stmt;

-- 3) verification_checklist_items.category
SET @sb420_sql := IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'verification_checklist_items' AND COLUMN_NAME = 'category'
        AND LOCATE('artifacts.category', COLUMN_COMMENT) > 0) = 1,
    'ALTER TABLE verification_checklist_items MODIFY COLUMN category VARCHAR(20) NOT NULL COMMENT "산출물 카테고리: ''html''(웹개발·AI API 카테고리) | ''svg''(원페이지 카테고리)"',
    'SELECT 1'
);
PREPARE sb420_stmt FROM @sb420_sql;
EXECUTE sb420_stmt;
DEALLOCATE PREPARE sb420_stmt;

-- 4) rubric_items.item_code
SET @sb420_sql := IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rubric_items' AND COLUMN_NAME = 'item_code'
        AND LOCATE('plan_score_reasons', COLUMN_COMMENT) > 0) = 1,
    'ALTER TABLE rubric_items MODIFY COLUMN item_code VARCHAR(50) NOT NULL COMMENT ''계획서 채점 결과(점수 보고서)의 항목 코드와 매칭되는 항목 코드''',
    'SELECT 1'
);
PREPARE sb420_stmt FROM @sb420_sql;
EXECUTE sb420_stmt;
DEALLOCATE PREPARE sb420_stmt;
