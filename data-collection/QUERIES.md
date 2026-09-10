# 배치가 실행하는 SQL

2026-09-10 기준. 실행 순서대로 적었다.
필드가 어느 API 에서 왔는지는 [FIELD_MAP.md](FIELD_MAP.md) 를 본다.
`%s` 는 PyMySQL 자리표시자다. **값은 전부 파라미터로 넘긴다 — 문자열로 잇지 않는다.**

한 번 실행에 나가는 SQL 은 대략 이 정도다.

```
고정          5개   잠금 · 실행기록 · 결과반영 · 잠금해제 · 임베딩 입력 조회
공고당 반복    4개 × 1,819건 ≒ 7,300개
첨부당 반복    5개 × 처리 건수 (보통 수십)

임베딩(6·7단계)은 **읽기만** 합니다. 벡터는 DB 가 아니라 파일과 Chroma 에 저장합니다.
```

---

## 0. 연결 직후

```sql
SET time_zone = '+00:00';
```

모든 시각을 UTC 로 다룬다. 서버·PC 시간대가 달라도 값이 흔들리지 않는다.

---

## 1. 중복 실행 차단

```sql
SELECT GET_LOCK(%s, 0);
-- %s = 'sbrain:' + SHA256(DB명)[:48]
```

`0` 이 돌아오면 다른 실행이 이미 돌고 있다는 뜻이라 예외를 던지고 끝낸다.
두 번째 인자 `0` 은 **기다리지 않는다**는 뜻이다.

끝날 때:

```sql
SELECT RELEASE_LOCK(%s);
```

파일 잠금과 별개다. **다른 PC 에서 같은 DB 에 동시에 쓰는 것**을 막는다.

---

## 2. 실행 기록 남기기

```sql
INSERT INTO import_runs (run_id, input_sha256, generated_at, notice_count, report)
VALUES (%s, %s, %s, %s, %s);
```

| 자리 | 값 |
|---|---|
| `run_id` | UUID 32자 |
| `input_sha256` | 정규화 결과 JSON 파일의 해시 |
| `generated_at` | 정규화 시각 |
| `notice_count` | 입력 건수 |
| `report` | 집계·거부 목록 JSON |

`input_sha256` 덕분에 **같은 파일을 두 번 넣었는지** 나중에 확인할 수 있다.

---

## 3. 공고 한 건마다 (1,819회 반복)

### 3-1. 기존 행 잠그고 시각 대조

```sql
SELECT id, snapshot_at FROM notices
WHERE source = %s AND source_id = %s
FOR UPDATE;
```

`snapshot_at > 이번 수집 시각` 이면 **더 최근 데이터가 이미 있다**는 뜻이라 건너뛴다
(`skipped_older`). 늦게 끝난 옛 실행이 새 데이터를 덮어쓰는 것을 막는다.

### 3-2. 없으면 추가 · 있으면 수정

```sql
INSERT INTO notices (
  notice_id, source, source_id, schema_version, title, body,
  target_text, target_text_status, target_category, exclude_text,
  age_condition_raw, region, category, subcategory,
  organizer, supervising_org, executing_org,
  apply_start, apply_end, apply_period_raw, apply_period_type,
  recruitment_status, url, apply_url, attachment_discovery_status,
  source_updated_at_raw, issues, raw, snapshot_at, last_import_id
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
  schema_version = %s, title = %s, body = %s,
  target_text = %s, target_text_status = %s, target_category = %s,
  exclude_text = %s, age_condition_raw = %s, region = %s,
  category = %s, subcategory = %s,
  organizer = %s, supervising_org = %s, executing_org = %s,
  apply_start = %s, apply_end = %s, apply_period_raw = %s,
  apply_period_type = %s, recruitment_status = %s,
  url = %s, apply_url = %s, attachment_discovery_status = %s,
  source_updated_at_raw = %s, issues = %s, raw = %s,
  snapshot_at = %s, last_import_id = %s;
```

**`DELETE` 가 없다.** API 목록에서 사라진 공고도 DB 에는 남는다.
API 가 일시적으로 빠뜨렸을 때 데이터를 잃지 않기 위함이다.

갱신 목록에서 앞 세 컬럼(`notice_id`·`source`·`source_id`)이 빠져 있다.
**신원이라 바뀌면 안 된다.**

`issues`·`raw`·`source_updated_at_raw`·`apply_period_raw` 는 JSON 컬럼이다.

### 3-3. 내부 키 조회

```sql
SELECT id FROM notices WHERE source = %s AND source_id = %s;
```

첨부를 붙이려면 `notices.id` 가 필요하다.

### 3-4. 첨부 링크 교체

```sql
-- 이 공고의 첨부를 일단 전부 끈다
UPDATE notice_attachments SET active = FALSE WHERE notice_fk = %s;
```

**조건부로만 실행된다** — `attachment_discovery_status = 'api_links_available'` 이고
URL 정규화 오류가 없을 때만. 주소가 깨져서 온 응답으로 기존 첨부를 끄지 않기 위함이다.

```sql
-- 이번 응답에 있는 것만 다시 켠다
INSERT INTO notice_attachments
  (notice_fk, attachment_key, role, url, name, source_status)
VALUES (%s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE name = %s, source_status = %s, active = TRUE;
```

**여기만 교체 방식이다.** 공고에서 첨부가 내려가면 우리도 내려야 한다.
행을 지우지는 않고 `active = FALSE` 로 둔다 — 이미 받아둔 본문이 딸려 있기 때문이다.

`attachment_key` 는 `역할 + URL` 의 SHA-256 이다. 한 공고 안에서 같은 첨부가
중복 등록되는 것을 막는다.

---

## 4. 결과 반영

```sql
UPDATE import_runs SET report = %s WHERE run_id = %s;
```

**2번부터 4번까지가 하나의 트랜잭션이다.** 중간에 실패하면 전부 되돌린다.

---

## 5. 첨부 받을 대상 고르기

```sql
SELECT a.id, a.url, n.notice_id,
       JSON_UNQUOTE(n.source_updated_at_raw) AS src_updated
FROM notice_attachments a
JOIN notices n               ON n.id = a.notice_fk
LEFT JOIN attachment_texts t ON t.attachment_fk = a.id
WHERE a.active = 1
  AND a.role = 'notice'
  AND n.source = 'bizinfo'
  AND (
        t.attachment_fk IS NULL
     OR t.last_source_updated_at <=> JSON_UNQUOTE(n.source_updated_at_raw) IS NOT TRUE
     OR (t.last_status IN ('download_fail', 'parse_error')
         AND t.last_attempted_at < %s)
  )
ORDER BY a.id;
-- %s = 지금 - 24시간 (UTC)
```

세 조건이 각각 이렇다.

```
t.attachment_fk IS NULL              ① 한 번도 안 받아본 첨부
last_source_updated_at <=> ... 불일치  ② 공고가 고쳐졌다 → 첨부도 바뀌었을 수 있다
last_status 가 실패 + 하루 지남        ③ 일시적 오류 재시도
```

`ok`·`image_only`·`unsupported`·`empty_text` 는 **원본이 바뀌지 않는 한 다시 받지 않는다.**
실측으로 1,616건 중 매일 수십 건만 대상이 된다.

`<=>` 는 NULL 안전 비교다. `IS NOT TRUE` 를 붙여 **한쪽이 NULL 이어도 「다르다」로 본다.**
`=` 를 쓰면 NULL 비교가 NULL 이 되어 조건에서 조용히 빠진다.

`role = 'notice'` — 공고문만 받는다. 신청서식(`form`)은 빈 양식이라 자격 조건이 없다.

---

## 6. 첨부 본문 저장 (한 건마다)

`attachment_store.save_attachment_result()` 가 **시도마다 별도 트랜잭션**으로 처리한다.
다운로드·추출이 끝난 뒤에 부른다. 받는 동안 DB 행을 잠그지 않는다.

### 6-1. 대상 찾기

```sql
SELECT notice_fk FROM notice_attachments WHERE id = %s;
```

FK 를 모르면 대체 식별자로 찾는다.

```sql
SELECT a.notice_fk, a.id FROM notice_attachments a
JOIN notices n ON n.id = a.notice_fk
WHERE n.notice_id = %s AND a.role = %s AND a.url = %s;
```

**없는 공고·첨부를 새로 만들지 않는다.**

### 6-2. 원본이 그새 바뀌었는지 확인

```sql
SELECT notice_id, source_updated_at_raw FROM notices WHERE id = %s FOR UPDATE;
SELECT role, url FROM notice_attachments WHERE id = %s FOR UPDATE;
```

시도 시작 때 관측한 수정 시각과 다르면 `skipped_source_changed` 로 돌려준다.
**받는 사이에 공고가 고쳐졌다는 뜻**이라 다시 받아야 한다.

### 6-3. 기존 결과와 견주기

```sql
SELECT last_attempt_started_at, last_attempted_at, last_result_sha256
FROM attachment_texts WHERE attachment_fk = %s FOR UPDATE;
```

- 더 최근 시도가 있으면 → `skipped_older_attempt`
- 같은 시각·같은 결과면 → `unchanged` (DB 안 건드림)
- 같은 시각인데 결과가 다르면 → 예외

### 6-4. 저장

```sql
INSERT INTO attachment_texts (
  attachment_fk,
  last_status, last_kind, last_attempt_started_at, last_attempted_at,
  last_source_updated_at, last_extractor_version, last_error, last_result_sha256
  -- status='ok' 일 때만 아래 7개가 더 붙는다
  , extracted_text, text_chars, text_kind, extracted_at
  , text_source_updated_at, text_extractor_version, content_sha256
) VALUES (%s, ...)
ON DUPLICATE KEY UPDATE
  last_status = %s, last_kind = %s, ... ;
```

**성공했을 때만 `text_*` 와 `extracted_text` 를 건드린다.**
오늘 재시도가 실패해도 어제 뽑아둔 본문은 남는다.

돌려주는 상태는 넷이다.

```
saved                   저장됨
unchanged               같은 결과 재전송. DB 변경 없음
skipped_older_attempt   더 최근 시도가 이미 있다
skipped_source_changed  시도하는 사이 원본이 바뀌었다 → 재수집 후 다시
```

---

## 7. 임베딩 입력 읽기 (6단계)

```sql
SELECT notice_id, title, body, target_text, target_category, category, subcategory
FROM notices
ORDER BY notice_id;
```

**여섯 필드만 읽습니다.** 이 조합이 임베딩 입력의 계약이며 `embed.py` 의
`build_input()` 이 유일한 정의입니다.

`match.notice_text()` 는 여기에 `organizer`·`executing_org` 를 더한 여덟 필드로
**다른 계약**입니다. TF-IDF 와 비교 실험이 그것을 쓰므로 섞지 않습니다.

읽은 뒤 필드를 이어붙여 SHA-256 을 구하고, 이미 만들어둔 해시와 견줍니다.

```
해시가 없다   → 새 공고다.       만든다
해시가 다르다 → 내용이 바뀌었다.  다시 만든다
해시가 같다   → 그대로다.        건너뛴다
```

**이 비교는 DB 가 아니라 `data/embeddings_v1.npz` 에서 합니다.**
`notices` 에 임베딩 컬럼이 아직 없기 때문입니다.

### 컬럼이 생기면 이렇게 바뀝니다

설계는 합의됐고 DDL 은 아직 반영 전입니다.

```sql
ALTER TABLE notices
  ADD COLUMN embedding              BLOB        NULL,
  ADD COLUMN embedding_input_sha256 CHAR(64)    NULL,
  ADD COLUMN embedded_at            DATETIME(6) NULL,
  ADD COLUMN embedding_meta         JSON        NULL;
```

그러면 대상 선정이 SQL 한 번으로 끝납니다.

```sql
SELECT notice_id, title, body, target_text, target_category, category, subcategory
FROM notices
WHERE embedding IS NULL
   OR embedding_input_sha256 <> %s              -- 지금 계산한 입력 해시
   OR JSON_UNQUOTE(JSON_EXTRACT(embedding_meta, '$.model')) <> %s
   OR JSON_UNQUOTE(JSON_EXTRACT(embedding_meta, '$.input_version')) <> %s;
```

저장은 네 컬럼을 한 트랜잭션으로 씁니다.

```sql
UPDATE notices
SET embedding = %s, embedding_input_sha256 = %s,
    embedded_at = %s, embedding_meta = %s
WHERE notice_id = %s;
```

**저장 직전에 행을 잠그고 입력 해시를 다시 확인해야 합니다.**
인코딩하는 사이에 수집기가 같은 공고를 고쳤을 수 있습니다.

---

## 8. 벡터 색인 갱신 (7단계)

**SQL 이 아닙니다.** Chroma 는 파일 기반이라 DB 를 건드리지 않습니다.

```python
col.upsert(ids=[...], embeddings=[...], metadatas=[{'notice_id': ...}])
```

같은 `notice_id` 를 다시 넣으면 건수는 그대로고 벡터만 바뀝니다.
6단계가 만든 것만 넣으므로 보통 하루 수십 건입니다.

검색할 때는 자격 게이트를 통과한 목록을 넘겨 그 안에서만 찾게 합니다.

```python
col.query(query_embeddings=[질의벡터], n_results=10,
          where={'notice_id': {'$in': [통과한 공고번호들]}})
```

---

## 상태 확인용

배치가 실행하는 건 아니지만 같은 DB 에서 바로 볼 수 있다.

```sql
-- 마지막 실행이 언제였나
SELECT run_id, generated_at, notice_count
FROM import_runs ORDER BY generated_at DESC LIMIT 5;

-- 출처별 공고 수
SELECT source, COUNT(*) FROM notices GROUP BY source;

-- 첨부 본문 처리 현황
SELECT last_status, COUNT(*) FROM attachment_texts GROUP BY last_status;

-- 임베딩 입력이 만들어지는 공고 수 (여섯 필드가 모두 비어 있으면 제외된다)
SELECT COUNT(*) FROM notices
WHERE COALESCE(title, body, target_text, target_category, category, subcategory) IS NOT NULL;

-- 공고 → 첨부 → 본문을 한 번에
SELECT n.title, t.last_status, t.text_chars, LEFT(t.extracted_text, 100)
FROM notices n
JOIN notice_attachments a ON a.notice_fk = n.id AND a.role = 'notice' AND a.active
JOIN attachment_texts   t ON t.attachment_fk = a.id
WHERE t.last_status = 'ok'
LIMIT 10;
```

---

## 알아둘 것 하나

**3번이 공고 한 건마다 SQL 을 네 번 실행한다.** 1,819건이면 왕복이 7,000번을 넘는다.

```
로컬 DB     8.7초
EC2 원격    85초
```

차이는 계산이 아니라 **네트워크 왕복**이다. 지금은 일 1회라 문제가 아니지만,
줄이려면 배치를 EC2 에서 돌리거나 여러 건을 묶어 보내면 된다.
