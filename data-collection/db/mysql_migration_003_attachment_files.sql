-- 003: 첨부 원본 파일을 공용 DB 에 보관한다.
--
-- 배경. 첨부 원본 1,646개 620MB 가 배치 PC 에만 있었다. 본문 텍스트는
-- attachment_texts 에 있고 원본 URL 도 notice_attachments 에 있지만, 팀원이
-- 파일 자체를 개발에 쓰려면(HWP 파서 개선·이미지 PDF OCR·레이아웃 분석 등)
-- 파일이 필요하다. 매번 원본 사이트에서 다시 받는 것은 느리고 상대 서버에 부담이다.
--
-- 왜 파일시스템이 아니라 DB 인가. 팀원 전원이 이미 이 DB 접속 정보를 가지고 있다.
-- 서버에 따로 파일 서버를 올리고 계정을 나눠주는 것보다 지금 당장 쓸 수 있다.
-- 파일이 GB 단위로 늘어나면 S3 같은 객체 저장소로 옮기는 것이 맞다.
--
-- 키를 content_sha256 으로 잡는 이유.
--   · 배치 PC 의 파일명이 그 값이다. data/attachments/9f/9f3a….pdf
--   · attachment_texts.content_sha256 과 그대로 조인된다
--   · 같은 파일을 여러 공고가 첨부해도 한 번만 저장된다 (실측 1,646개 중 중복 제거된 값)
--
-- 크기. 평균 386KB · 중간 190KB · 최대 9.29MB. max_allowed_packet(64MB)을
-- 넘는 파일은 없다. LONGBLOB 은 4GB 까지이므로 한 행이 부족할 일은 없다.
CREATE TABLE IF NOT EXISTS attachment_files (
    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY
        COMMENT '파일 바이트의 SHA-256. attachment_texts.content_sha256 과 조인되며 배치 PC 의 파일명과 같다',
    byte_size INT UNSIGNED NOT NULL
        COMMENT '파일 바이트 수. LENGTH(bytes) 와 같아야 한다',
    ext VARCHAR(16) NOT NULL
        COMMENT '내려받은 파일의 확장자: pdf, hwp, hwpx, docx, img',
    bytes LONGBLOB NOT NULL
        COMMENT '파일 원본 바이트. 가공하거나 압축하지 않은 그대로',
    uploaded_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        COMMENT '이 파일을 올린 시각(UTC)',
    KEY ix_attachment_file_ext (ext)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
