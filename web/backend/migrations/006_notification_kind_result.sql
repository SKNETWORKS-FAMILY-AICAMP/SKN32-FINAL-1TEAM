-- [SB-396, 2026-10-15] notifications.kind ENUM에 '결과물' 추가 — 오케스트레이터가 검수(표현 검수 · 윤문)를 서비스 흐름에서 빼면서
-- 결과 통합이 끝나면 '결과물' 알림(target_step 11)을 INSERT한다.
--
-- ★ 반영 순서: 이 마이그레이션(웹 스키마) → 오케스트레이터 워커 새 코드. ENUM에 값이 없으면 워커의 알림 INSERT가 실패하고,
--   같은 트랜잭션으로 묶인 그 단계 저장 전체가 되돌려져 실행 건이 완료로 넘어가지 못한다.
--
-- 값: '문서평가' · '산출물확인' · '표현검수' · '결과물' · '실패'. '표현검수'는 지우지 않는다 — 검수 제거 전에 쌓인 옛 알림 행이 남아 있다.
-- 기존 행은 바뀌지 않는다(ENUM 값만 하나 더 생긴다).
--
-- 번호 안내: 003은 feature/sb-269-web-final의 checklist_items 마이그레이션이다. 이 브랜치에는 아직 없으므로 병합 때
--   001 → 002 → 003 → 004 → 005 → 006 순서로 적용한다. 006은 앞 번호들과 서로 의존하지 않는다.
--
-- 몇 번을 실행해도 안전하다(이미 '결과물'이 있으면 건너뛴다). MySQL 8 기준.
--
-- 실행: mysql -u <계정> -p <DB 이름> < migrations/006_notification_kind_result.sql

SET @sb396_has_result := (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notifications' AND COLUMN_NAME = 'kind'
      AND LOCATE('결과물', COLUMN_TYPE) > 0
);

SET @sb396_sql := IF(
    @sb396_has_result = 0,
    'ALTER TABLE notifications MODIFY COLUMN kind ENUM(''문서평가'',''산출물확인'',''표현검수'',''결과물'',''실패'') NOT NULL COMMENT ''완료된 단계 또는 실패(표현검수는 검수 제거 전 옛 알림, 결과물은 결과 통합 완료)''',
    'SELECT 1'
);

PREPARE sb396_stmt FROM @sb396_sql;
EXECUTE sb396_stmt;
DEALLOCATE PREPARE sb396_stmt;
