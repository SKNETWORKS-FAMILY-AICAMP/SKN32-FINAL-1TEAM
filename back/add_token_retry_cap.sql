-- 검증 정책에 token_retry_cap(검수(표현) Task 내부 보호 토큰 위반 문단 재시도 상한) 컬럼 추가.
-- 이미 예전 app_schema.sql(이 컬럼 없는 버전)로 AWS에 테이블을 만들어둔 사람만 실행하면 된다.
-- 새로 테이블을 만드는 거면 app_schema.sql 최신 버전에 이미 포함돼 있어서 필요 없음.
--
-- 2026-09-14 정재희님과 논의 후 컬럼 추가 확정 — admin-dashboard.html 목업엔 있었지만
-- (검증 정책 탭 "보호 토큰 재시도 상한", 기본값 2) 스키마엔 없던 필드였다. rerun_cap
-- (Task 단위 재수행 상한)과는 별개로 관리되는 값이라 기존 rerun_cap을 재사용하지 않고
-- 새 컬럼으로 뺐다.
--
-- ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT 2 는 MySQL에서 기존 행에도 기본값
-- 2를 자동으로 채워 넣으므로 별도 UPDATE 문이 필요 없다.

ALTER TABLE verification_policies
    ADD COLUMN token_retry_cap INT UNSIGNED NOT NULL DEFAULT 2
        COMMENT '검수(표현) Task 내부 보호 토큰 위반 문단 재시도 최대 횟수(rerun_cap과 별개)'
        AFTER deviation_cap;
