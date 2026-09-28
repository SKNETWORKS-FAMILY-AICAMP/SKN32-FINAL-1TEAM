-- 004: 공고문에서 뽑아낸 자격요건을 보관한다.
--
-- 배경. 공고 API 는 지원금액을 주지 않고, 사업자 형태(개인/법인) 구분도 주지
-- 않는다. 그 정보는 첨부 공고문(PDF·HWP) 본문에 문장으로만 있다. LLM 으로
-- 한 번 읽어 구조화해 두고, 그 뒤로는 SQL 로 판정한다.
--
-- notices 를 건드리지 않고 별도 테이블로 두는 이유.
--   · 추출은 실패할 수 있고 나중에 다시 할 수도 있다. 원본과 섞지 않는다.
--   · 추출기 버전을 올리면 전량 재추출한다. 그때 이 테이블만 비우면 된다.
--   · web 이 읽는 notices 의 컬럼 수가 늘어나지 않는다.
--
-- 실측(표본 90건)으로 확인한 판정률
--   지원금액    51%    근거 대조로 교정 4건 · 폐기 6건
--   사업자 형태  44%
--   업력         7%    ← LLM 이 낸 21건 중 15건이 오답이었다(나이·근속·개월 혼동)
--
-- **업력은 판정에 쓰지 않는다.** 참고용으로만 보관한다. 자격요건은 틀리면
-- 사용자가 헛수고하는 영역이라 7% 를 얻으려고 오답 위험을 지지 않는다.
-- 업력 판정은 K-Startup 이 정형으로 주는 notices.age_condition_raw 를 쓴다
-- (gate.py 가 그렇게 한다).
CREATE TABLE IF NOT EXISTS notice_conditions (
    notice_id VARCHAR(320) NOT NULL PRIMARY KEY
        COMMENT '대상 공고. notices.notice_id 와 같은 값',

    -- 판정에 쓰는 값 ------------------------------------------------------
    amount_max_won BIGINT UNSIGNED NULL
        COMMENT '기업 1곳이 받는 최대 지원금(원). 사업 총예산·매출 기준과 구분한 값. 미확보 시 NULL',
    business_type JSON NULL
        COMMENT '신청 가능한 사업자 형태 배열: ["개인사업자","법인","예비창업자","비영리","기타"]. 특정 못 하면 빈 배열',
    pre_startup_allowed BOOLEAN NULL
        COMMENT '예비창업자(사업자등록 전) 신청 가능 여부. 알 수 없으면 NULL',

    -- 참고용. 판정에 쓰지 않는다 -------------------------------------------
    age_years_max SMALLINT UNSIGNED NULL
        COMMENT '업력 상한(년). 오답률이 높아 판정에 쓰지 않는다. 참고용',
    age_years_min SMALLINT UNSIGNED NULL
        COMMENT '업력 하한(년). 참고용',
    age_source_quote TEXT NULL
        COMMENT '업력 값의 근거 문장 원문. 값이 버려졌으면 근거만 남는다',
    no_age_limit BOOLEAN NOT NULL DEFAULT FALSE
        COMMENT '문서가 업력 제한 없음을 명시했는가. 못 찾은 것과 구분한다',

    -- 근거와 신뢰도 -------------------------------------------------------
    source_quote TEXT NULL
        COMMENT '금액·형태 값의 근거 문장 원문. 없으면 값을 신뢰할 수 없다',
    uncertain JSON NULL
        COMMENT '판단하지 못한 것과 검증에서 버린 이유 배열',
    amount_corrected JSON NULL
        COMMENT '금액을 근거와 대조해 고친 기록 {"from":..,"to":..}. 안 고쳤으면 NULL',
    age_rejected VARCHAR(80) NULL
        COMMENT '업력 값을 버린 이유. 버리지 않았으면 NULL',

    -- 재추출 판단용 -------------------------------------------------------
    input_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
        COMMENT 'LLM 에 보낸 문서의 SHA-256. 같으면 다시 추출하지 않는다',
    extractor_version VARCHAR(64) NOT NULL
        COMMENT '추출기와 모델 버전. 바뀌면 전량 재추출 대상',
    prompt_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 입력 토큰',
    completion_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 출력 토큰',
    extracted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        COMMENT '추출 시각(UTC)',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '행 마지막 변경 시각(UTC)',

    KEY ix_conditions_amount (amount_max_won),
    KEY ix_conditions_version (extractor_version),
    CONSTRAINT fk_conditions_notice FOREIGN KEY (notice_id)
        REFERENCES notices (notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
