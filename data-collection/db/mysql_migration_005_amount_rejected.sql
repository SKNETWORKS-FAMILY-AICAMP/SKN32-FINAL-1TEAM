-- 005: notice_conditions 에 금액 폐기 사유 컬럼 추가.
--
-- 004 에서 age_rejected 만 만들고 금액 쪽 대칭을 놓쳤다. 검산이 금액을 버릴 때
-- 이유를 남길 곳이 없어 왜 NULL 인지 구분할 수 없었다.
--   · 애초에 LLM 이 못 찾음
--   · 근거와 대조해 버림
--   · 기업당 지원금으로 보기 어려운 금액이라 버림
-- 셋을 구분해야 나중에 추출기를 개선할 때 어디를 고쳐야 하는지 알 수 있다.
ALTER TABLE notice_conditions
    ADD COLUMN amount_rejected VARCHAR(120) NULL
        COMMENT '금액 값을 버린 이유. 버리지 않았으면 NULL'
        AFTER amount_corrected;
