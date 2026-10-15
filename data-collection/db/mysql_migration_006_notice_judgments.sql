-- 006: LLM 이 공고문에서 읽은 판정(신청자 유형·업종)을 팀이 함께 쓰도록 보관한다 (2026-09-28).
--
-- 배경. 신청자 유형(예비창업자·개인사업자·법인)과 업종 판정은 배치 PC 의 파일
-- (data/applicant_types/results.jsonl, reports/industry_llm_full_luna_*/results.jsonl)에만 있어
-- 팀원·EC2 서비스가 쓸 수 없었다. 8단계가 벡터를 공용 DB 로 올리는 것과 같은 방식으로 올린다.
-- 설계 설명: docs/guides/JUDGMENT_TABLES.md
--
-- notices·notice_conditions 를 건드리지 않고 새 테이블로 두는 이유.
--   · 기존 테이블을 읽는 web·배치 코드에 영향이 없다(칸이 늘지 않는다).
--   · 판정은 추출기·프롬프트를 바꾸면 다시 만든다. 그때 이 테이블만 다시 채우면 된다.
--   · 공고가 지워지면 판정도 함께 지워진다(외래 키 ON DELETE CASCADE).
--
-- **판정은 LLM 추출이다.** 사람 정답으로 검증하지 않았다. 어떤 칸을 매칭의 "빼기"에 쓸 수 있는지는
-- 각 칸 설명에 적었다(현재 서비스 기준). 나머지는 순서 조정·참고 표시용이다.
-- 모든 행은 근거 문장(evidence·quote)을 함께 싣는다. 근거 없이 값만 쓰지 않는다.

CREATE TABLE IF NOT EXISTS notice_applicant_types (
    notice_id VARCHAR(320) NOT NULL PRIMARY KEY
        COMMENT '대상 공고. notices.notice_id 와 같은 값',

    -- 서비스가 쓰는 결론 --------------------------------------------------
    pre_founder_verdict VARCHAR(16) NULL
        COMMENT '예비창업자 신청자에 대한 서비스 판정: blocked(명시 불가·빼기) · allowed(본문 가능) · implied_no(불가 추정·뒤로) · NULL(모름). search/applicant_types.pre_founder() 결과',
    registered_only_phrase VARCHAR(120) NULL
        COMMENT '등록 사업자 전용 표현 규칙에 걸린 표현("사업자 미등록 업체" 등). implied_no 로 올린 근거. 없으면 NULL',
    varies BOOLEAN NOT NULL DEFAULT FALSE
        COMMENT '세부사업마다 신청 가능 유형이 다르다. TRUE 면 공고 전체를 한 값으로 판정하지 않는다',

    -- LLM 이 읽은 유형별 값 ------------------------------------------------
    pre_founder_status VARCHAR(16) NOT NULL
        COMMENT '예비창업자: allowed · not_allowed · implied_no · not_mentioned',
    pre_founder_strength VARCHAR(8) NULL
        COMMENT '근거 강도: strong(명시) · weak(간접). 없으면 NULL',
    pre_founder_evidence TEXT NULL
        COMMENT '예비창업자 판정의 근거 문장 원문(코드로 원문 존재 확인)',
    sole_proprietor_status VARCHAR(16) NOT NULL
        COMMENT '개인사업자: allowed · not_allowed · implied_no · not_mentioned. 매칭에 쓰지 않는다(참고)',
    sole_proprietor_strength VARCHAR(8) NULL COMMENT '근거 강도',
    sole_proprietor_evidence TEXT NULL COMMENT '근거 문장 원문',
    corporation_status VARCHAR(16) NOT NULL
        COMMENT '법인: allowed · not_allowed · implied_no · not_mentioned. 매칭에 쓰지 않는다(참고)',
    corporation_strength VARCHAR(8) NULL COMMENT '근거 강도',
    corporation_evidence TEXT NULL COMMENT '근거 문장 원문',
    reason TEXT NULL COMMENT 'LLM 이 적은 판단 이유(설명용)',

    -- 재추출 판단용 -------------------------------------------------------
    document_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
        COMMENT 'LLM 에 보낸 공고문 발췌의 SHA-256. 같으면 다시 추출하지 않는다',
    prompt_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL
        COMMENT '프롬프트·스키마의 SHA-256',
    extractor_version VARCHAR(64) NOT NULL
        COMMENT '추출기와 모델. 예: applicant_type_llm gpt-5.6-luna@medium',
    prompt_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 입력 토큰',
    completion_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 출력 토큰(추론 포함)',
    uploaded_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        COMMENT '처음 올린 시각(UTC)',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '행 마지막 변경 시각(UTC)',

    KEY ix_types_pre_verdict (pre_founder_verdict),
    KEY ix_types_version (extractor_version),
    CONSTRAINT fk_types_notice FOREIGN KEY (notice_id)
        REFERENCES notices (notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS notice_industries (
    notice_id VARCHAR(320) NOT NULL PRIMARY KEY
        COMMENT '대상 공고. notices.notice_id 와 같은 값',

    -- 서비스가 쓰는 결론 --------------------------------------------------
    status VARCHAR(16) NOT NULL
        COMMENT '코드 검사 뒤 업종 판정: known(허용 업종 확인) · no_limit(업종 무관 명시) · excluded_only(제외 업종만) · conditional(조건부) · not_mentioned(언급 없음) · unknown(판단 불가)',
    allowed_sections JSON NULL
        COMMENT '허용 업종을 KSIC 대분류(A~U)로 묶은 배열. 예: ["C","J"]. 묶을 수 없으면 NULL (industry_groups.allowed_sections)',
    usable_for_rank BOOLEAN NOT NULL DEFAULT FALSE
        COMMENT '업종 순위 신호에 쓸 수 있는가(목록 완전·잘림 없음·갈래 문제 없음 등, search/industry_rank.py 기준). 업종 순위는 2026-09-28 기본 꺼짐',

    -- LLM 이 읽은 값 -------------------------------------------------------
    allowed JSON NULL
        COMMENT '허용 업종 배열 [{"text":원문 표현,"label":어휘 라벨,"evidence":근거 문장}]',
    excluded JSON NULL
        COMMENT '제외 업종 배열(같은 모양). 제외 표현과 같은 절에서 연결된 것만',
    list_complete BOOLEAN NULL
        COMMENT '허용 목록이 전부인가. 별표·"등"·누락이 보이면 FALSE',
    quote TEXT NULL COMMENT '업종 판정의 근거가 된 신청 자격 문장 원문',
    quote_role VARCHAR(16) NULL COMMENT '근거 문장의 역할: eligibility(신청 자격) 등',
    truncated BOOLEAN NOT NULL DEFAULT FALSE
        COMMENT 'LLM 에 보낸 발췌가 상한에서 잘렸다. TRUE 면 목록이 불완전할 수 있다',
    scope_unresolved BOOLEAN NOT NULL DEFAULT FALSE
        COMMENT '업종 조건이 어느 세부사업에 붙는지 정하지 못했다',
    excerpt_chars INT UNSIGNED NULL COMMENT '발췌 상한(자). 6000 또는 긴 공고 18000',
    verify_profile VARCHAR(16) NULL COMMENT '코드 검사 강도: rough · strict',

    -- 재추출 판단용 -------------------------------------------------------
    document_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
        COMMENT 'LLM 에 보낸 공고문 발췌의 SHA-256',
    prompt_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL
        COMMENT '프롬프트의 SHA-256',
    extractor_version VARCHAR(64) NOT NULL
        COMMENT '추출기와 모델. 예: industry_llm v3 gpt-5.6-luna@medium',
    source_run VARCHAR(80) NULL
        COMMENT '이 값을 만든 결과 폴더 이름(reports/ 아래). 추적용',
    prompt_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 입력 토큰',
    completion_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 출력 토큰(추론 포함)',
    uploaded_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        COMMENT '처음 올린 시각(UTC)',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '행 마지막 변경 시각(UTC)',

    KEY ix_industries_status (status),
    KEY ix_industries_rank (usable_for_rank),
    KEY ix_industries_version (extractor_version),
    CONSTRAINT fk_industries_notice FOREIGN KEY (notice_id)
        REFERENCES notices (notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
