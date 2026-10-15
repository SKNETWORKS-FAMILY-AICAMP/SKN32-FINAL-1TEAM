-- 정형 필터 + 의미 검색 실험용 로컬 스키마.
-- 기존 공용 스키마(db/mysql_schema.sql)와 별개이며, 이 파일은 실험 DB에만 적용한다.
--
-- 세 조각으로 나눈다.
--   lab_notices     원문 스냅샷 (읽어 온 시점·내용 해시 포함)
--   lab_conditions  정형 조건 (값 + 상태 + 근거). 값 없음과 제한 없음을 구분한다
--   lab_vectors     새 입력 계약으로 만든 벡터

CREATE TABLE IF NOT EXISTS lab_notices (
  notice_id        VARCHAR(100) NOT NULL,
  source           VARCHAR(20)  NOT NULL,
  title            TEXT,
  body             MEDIUMTEXT,
  target_text      MEDIUMTEXT,
  target_category  TEXT,
  category         TEXT,
  subcategory      TEXT,
  organizer        TEXT,
  region_raw       TEXT,
  age_condition_raw TEXT,
  apply_start      DATE NULL,
  apply_end        DATE NULL,
  apply_period_type VARCHAR(30),
  recruitment_status VARCHAR(20),
  url              TEXT,
  snapshot_at      DATETIME     NOT NULL,   -- 소스에서 읽어 온 시각
  content_sha256   CHAR(64)     NOT NULL,   -- 스냅샷 당시 내용 해시
  PRIMARY KEY (notice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 정형 조건. 한 공고에 여러 줄(필드별 한 줄)이 들어간다.
--   status  known        값을 확인했다
--           no_limit     제한이 없다고 공고가 밝혔다 (예: 전국)
--           unknown      공고에서 확인할 수 없다  ← 값 없음과 구분하는 핵심
--   value_* 는 필드 성격에 맞는 칸만 채운다. 나머지는 NULL 이다.
CREATE TABLE IF NOT EXISTS lab_conditions (
  notice_id     VARCHAR(100) NOT NULL,
  field         VARCHAR(40)  NOT NULL,   -- region · industry · company_size · business_age ...
  status        VARCHAR(20)  NOT NULL,
  value_text    TEXT,                    -- 표준화한 값 (여러 개면 쉼표)
  -- BIGINT 인 이유: 업력은 개월(작은 수)이지만 support_amount 는 **원 단위**라
  -- 30억원 = 3,000,000,000 처럼 INT 상한(21억)을 넘는다. 첫 적재에서 실제로 막혔다.
  value_min     BIGINT NULL,
  value_max     BIGINT NULL,
  bound_note    VARCHAR(40),             -- 'max_exclusive' 등 경계 포함 여부
  evidence      TEXT,                    -- 원문 근거 (없으면 NULL)
  extractor     VARCHAR(40)  NOT NULL,   -- 어떤 규칙으로 뽑았는지
  PRIMARY KEY (notice_id, field),
  CONSTRAINT fk_lab_conditions FOREIGN KEY (notice_id)
    REFERENCES lab_notices (notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE INDEX idx_lab_conditions_field ON lab_conditions (field, status);

-- 새 입력 계약으로 만든 벡터. 기존 NPZ·Chroma 와 섞지 않는다.
CREATE TABLE IF NOT EXISTS lab_vectors (
  notice_id      VARCHAR(100) NOT NULL,
  contract       VARCHAR(60)  NOT NULL,  -- 입력 계약 버전
  model          VARCHAR(80)  NOT NULL,
  model_revision VARCHAR(80),
  dim            INT          NOT NULL,
  dtype          VARCHAR(20)  NOT NULL,  -- float32
  normalized     TINYINT(1)   NOT NULL,
  input_sha256   CHAR(64)     NOT NULL,  -- 임베딩에 넣은 텍스트의 해시
  truncated      TINYINT(1)   NOT NULL DEFAULT 0,
  token_count    INT NULL,
  vector         LONGBLOB     NOT NULL,
  created_at     DATETIME     NOT NULL,
  PRIMARY KEY (notice_id, contract),
  CONSTRAINT fk_lab_vectors FOREIGN KEY (notice_id)
    REFERENCES lab_notices (notice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 실행 기록. 어떤 스냅샷·계약으로 만들었는지 남긴다.
CREATE TABLE IF NOT EXISTS lab_runs (
  run_id        CHAR(32)    NOT NULL,
  started_at    DATETIME    NOT NULL,
  finished_at   DATETIME NULL,
  kind          VARCHAR(30) NOT NULL,   -- snapshot · conditions · embed
  as_of_date    DATE NULL,
  note          TEXT,
  PRIMARY KEY (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 이미 INT 로 만들어진 실험 DB 를 위한 보정. 여러 번 실행해도 안전하다.
ALTER TABLE lab_conditions MODIFY value_min BIGINT NULL;
ALTER TABLE lab_conditions MODIFY value_max BIGINT NULL;
