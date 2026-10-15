-- 008: notice_bonus 에 공고 내용 지문(content_version)을 더한다 (2026-10-06, Codex 검수 P2-4).
--
-- 배경. 가점은 공고문에서 LLM 으로 뽑는다. 공고문이 바뀌었는데 다시 뽑기 전이면 옛 가점이 그대로 쓰였다.
-- 뽑을 때의 공고 내용 지문(search/content_version.py, 공고 칸 + 지금 달린 첨부 파일 지문)을 함께 저장하고,
-- 서버가 읽을 때 지금 지문과 다르면 그 가점을 쓰지 않는다(→ 가산점 null). 매일 배치도 지문이 바뀐 공고를 다시 뽑는다.
-- 작업 기록: docs/notice_api/03_bonus/README.md 의 "Codex 검수 반영"
--
-- 007 로 만든 표에 칸 하나만 더한다. 기존 행은 NULL 이 되고, NULL 인 행은 서버가 쓰지 않는다(다시 뽑아야 한다).

ALTER TABLE notice_bonus
    ADD COLUMN content_version VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL
        COMMENT '뽑을 때의 공고 내용 지문(search/content_version, cv2-…). 지금 지문과 다르면 서버가 이 가점을 쓰지 않는다'
        AFTER document_sha256;
