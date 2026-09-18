-- 002: notices 에 공고 요약 임베딩 컬럼 추가.
--
-- 배경. 지금까지 벡터는 배치가 도는 PC 의 data/embeddings_v1.npz 에만 있었다.
-- 그래서 화면을 팀에 공개하면 의미 검색이 그 PC 밖에서는 되지 않았다.
-- 벡터를 공용 DB 로 옮겨 web 이 읽을 수 있게 한다.
--
-- 크기. 2,050건 × 1024차원 × float32 = 8.0MB. 1건당 정확히 4,096 바이트다.
-- MEDIUMBLOB(최대 16MB)를 쓰는 이유는 BLOB(64KB)로도 충분하지만
-- 차원이 늘어나는 모델로 갈아탈 여지를 남기기 위함이다.
--
-- 바이트 배열. float32 리틀엔디안을 그대로 이어 붙인 것이다. 압축하지 않는다.
-- numpy 로는 np.frombuffer(blob, dtype='<f4') 로 바로 돌아온다.
-- embeddings_v1.npz 의 meta.byte_order = "little" 과 같은 약속이다.
--
-- 기존 컬럼과 행을 건드리지 않는다. 컬럼 추가만 하므로 web 의 기존 SELECT 는 깨지지 않는다.
ALTER TABLE notices
    ADD COLUMN embedding MEDIUMBLOB NULL
        COMMENT '공고 요약 임베딩. float32 리틀엔디안 연속 바이트, 정규화됨. 미생성 시 NULL',
    ADD COLUMN embedding_dim SMALLINT UNSIGNED NULL
        COMMENT '임베딩 차원 수. 현재 1024, 바이트 길이는 이 값의 4배여야 한다',
    ADD COLUMN embedding_input_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL
        COMMENT '벡터를 만든 입력 텍스트의 SHA-256. 공고가 바뀌었는지 판정하는 기준',
    ADD COLUMN embedding_fingerprint CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL
        COMMENT '인코딩 설정 지문(model·revision·input_version·max_tokens·dim·dtype·normalized). 다르면 재생성 대상',
    ADD COLUMN embedding_updated_at DATETIME(6) NULL
        COMMENT '이 벡터를 마지막으로 올린 시각(UTC)';

-- 아직 안 올라간 것 · 설정이 바뀐 것을 빨리 찾기 위한 색인.
-- embedding 자체는 색인하지 않는다. MySQL 8.0 에 벡터 색인이 없어 의미가 없다.
CREATE INDEX ix_notice_embed_fp ON notices (embedding_fingerprint);
