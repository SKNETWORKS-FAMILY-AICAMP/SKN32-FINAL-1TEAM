-- 007: LLM 이 공고문에서 읽은 가점(가산점) 조건을 보관한다 (2026-10-06, 조율 요청서 3.2).
--
-- 배경. 조율 에이전트가 공고 추천 결과마다 신청자별 가산점(bonus_score·bonus_items)과
-- 공고 상세의 가점 원문(bonus_info)을 요청했다. 공고마다 가점 조건을 미리 뽑아 두고, 추천할 때
-- 신청자 정보와 맞춰 점수를 계산한다(search/ 쪽 3-3 단계). 작업 기록: docs/notice_api/03_bonus/
--
-- notices·notice_conditions 를 건드리지 않고 새 테이블로 두는 이유(006 과 같다).
--   · 기존 테이블을 읽는 web·배치 코드에 영향이 없다.
--   · 추출기·프롬프트를 바꾸면 다시 만든다. 그때 이 테이블만 다시 채우면 된다.
--   · 공고가 지워지면 가점도 함께 지워진다(외래 키 ON DELETE CASCADE).
--
-- **가점은 LLM 추출이다.** 사람 정답으로 검증하지 않았다. 항목마다 근거 원문(quote)을 싣고,
-- 근거가 공고문에 없으면 저장 전에 버린다(collect/extract_bonus.verify). 점수는 근거 구간에 숫자로 있을 때만 남긴다.
-- 행이 없는 공고는 "가점 없음"이 아니라 "아직 읽지 않음"이다(K-Startup 은 첨부 공고문을 수집하지 않아 행이 없다).

CREATE TABLE IF NOT EXISTS notice_bonus (
    notice_id VARCHAR(320) NOT NULL PRIMARY KEY
        COMMENT '대상 공고. notices.notice_id 와 같은 값',

    status VARCHAR(16) NOT NULL
        COMMENT 'none(LLM 이 가점 없다고 봄) · found(검사를 통과한 항목이 있음) · unverified(가점을 찾았으나 근거가 문서와 맞지 않아 모두 버림 — 없음이 아니라 모름) · no_mention(첨부 공고문을 읽었으나 가점·가산점 말이 없음 — LLM 을 부르지 않음)',
    max_total_points DECIMAL(6,2) NULL
        COMMENT '가점 합계 한도(예: 최대 5점). 문서에 없으면 NULL',
    bonus_info TEXT NULL
        COMMENT '가점 조건이 적힌 부분의 원문(800자 이내). 공고 상세 창구의 bonus_info',
    items JSON NOT NULL
        COMMENT '항목 배열 [{name, points(숫자|null), kind, certs[], regions[], detail, quote}]. kind 는 collect/extract_bonus.KINDS',
    uncertain JSON NOT NULL
        COMMENT 'LLM 이 판단하지 못한 것(중복 인정 여부 등) 문자열 배열',
    problems JSON NOT NULL
        COMMENT '코드 검사에서 고친 것(근거 없어 버림·점수 null 로 낮춤 등) 문자열 배열',

    document_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
        COMMENT 'LLM 에 보낸 발췌의 SHA-256. 같으면 다시 부르지 않는다',
    extractor_version VARCHAR(64) NOT NULL
        COMMENT '추출기·프롬프트·모델 버전(extract_bonus/v3 gpt-5.6-luna medium 등). 바뀌면 전량 재추출 대상',
    prompt_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 입력 토큰',
    completion_tokens INT UNSIGNED NULL COMMENT '이 건에 쓴 출력 토큰(추론 포함)',
    extracted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        COMMENT '추출 시각(UTC)',
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '행 마지막 변경 시각(UTC)',

    KEY ix_bonus_status (status),
    KEY ix_bonus_version (extractor_version),
    CONSTRAINT fk_bonus_notice FOREIGN KEY (notice_id)
        REFERENCES notices (notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
