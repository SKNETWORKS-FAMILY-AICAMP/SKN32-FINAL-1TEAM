# 수집한 자료를 개발에 쓰는 법

공고·첨부 본문·첨부 원본 파일·임베딩 벡터가 모두 **공용 MySQL** 에 있습니다.
배치가 도는 PC 가 켜져 있는지와 무관하게 쓸 수 있습니다.

접속 정보는 `.env.example` 을 참고해 각자 `.env` 를 만드세요.
`MYSQL_SSL_CA=data/ec2-ca.pem` 이 필요합니다. 서버가 평문 연결을 거부합니다.

```python
import store_mysql
connection = store_mysql.connect()
```

---

## 테이블 다섯 개

```
notices              공고 본문·기간·기관·지역 · 벡터        2,050행
notice_attachments   첨부 링크 (URL·파일명·역할)            2,908행
attachment_texts     첨부에서 뽑은 본문 텍스트              1,701행
attachment_files     첨부 원본 파일 그 자체                 1,646개 620MB
import_runs          배치 실행 이력
```

관계는 이렇게 이어집니다.

```
notices.id  ──<  notice_attachments.notice_fk
                 notice_attachments.id  ──  attachment_texts.attachment_fk
                                            attachment_texts.content_sha256
                                                    │ (같은 값)
                                            attachment_files.content_sha256
```

`content_sha256` 은 **파일 바이트의 해시**입니다. 그래서 같은 파일을 여러 공고가
첨부해도 `attachment_files` 에는 한 번만 있습니다.

---

## 1. 첨부 원본 파일 꺼내기

파서를 개선하거나 OCR·표 추출을 붙일 때 쓰는 것입니다.

```python
import store_mysql, doctext

connection = store_mysql.connect()
with connection.cursor() as cursor:
    cursor.execute("""
        SELECT na.name, f.ext, f.bytes
          FROM notices n
          JOIN notice_attachments na ON na.notice_fk = n.id
          JOIN attachment_texts   at ON at.attachment_fk = na.id
          JOIN attachment_files    f ON f.content_sha256 = at.content_sha256
         WHERE n.notice_id = %s
    """, ('bizinfo:PBLN_000000000117059',))
    for name, ext, blob in cursor.fetchall():
        data = bytes(blob)
        print(name, doctext.sniff(data))
        text = doctext.extract_bytes(data, suffix='.' + ext)
        print(len(text), '자')
```

**파일로 저장하고 싶으면** 바이트를 그대로 쓰면 됩니다. 가공하지 않았습니다.

```python
open('내려받은것.' + ext, 'wb').write(bytes(blob))
```

### 형식별 개수

```
pdf   880    hwp   515    hwpx  192    img   58    docx  1
```

평균 386KB · 중간 190KB · 최대 9.29MB.

### 파서 개발에 쓸 만한 것

추출이 실패한 것만 골라 볼 수 있습니다. 여기가 개선 여지입니다.

```sql
SELECT at.last_status, at.last_kind, COUNT(*)
  FROM attachment_texts at
 GROUP BY at.last_status, at.last_kind
 ORDER BY COUNT(*) DESC;
```

`image_only` 는 글자가 없는 스캔 이미지입니다. OCR 대상입니다.
`parse_error` 는 형식은 맞는데 추출이 깨진 것입니다.

주의할 점이 하나 있습니다. **실패한 첨부는 `content_sha256` 이 NULL 입니다.**
성공했을 때만 채우기 때문입니다. 그래서 위 조인으로는 실패 건의 파일을 못 찾습니다.
그런 파일도 `attachment_files` 에는 올라가 있으니(로컬 1,646개 전부 올림), 해시를
모를 때는 `ext` 로 훑으세요.

```sql
SELECT content_sha256, ext, byte_size FROM attachment_files WHERE ext = 'img';
```

---

## 2. 이미 뽑아둔 본문 텍스트 쓰기

파일을 다시 파싱할 필요가 없다면 이게 빠릅니다.

```sql
SELECT n.notice_id, n.title, at.extracted_text, at.text_chars
  FROM notices n
  JOIN notice_attachments na ON na.notice_fk = n.id
  JOIN attachment_texts   at ON at.attachment_fk = na.id
 WHERE at.last_status = 'ok' AND n.notice_id = %s;
```

`extracted_text` 는 **마지막 성공 본문**입니다. 그 뒤 재시도가 실패해도 보존됩니다.
그래서 `last_status` 가 실패여도 `extracted_text` 가 있을 수 있습니다.

---

## 3. 의미 검색 (임베딩 벡터)

`notices.embedding` 에 벡터가 들어 있습니다. **Chroma 같은 벡터 DB 가 필요 없습니다.**
2,050건이면 numpy 행렬곱 한 번이 10ms 입니다.

```python
import numpy as np, store_mysql, embed

connection = store_mysql.connect()
with connection.cursor() as cursor:
    cursor.execute('SELECT notice_id, title, embedding FROM notices '
                   'WHERE embedding IS NOT NULL')
    rows = cursor.fetchall()

ids    = [r[0] for r in rows]
titles = [r[1] for r in rows]
M = np.vstack([np.frombuffer(r[2], dtype='<f4') for r in rows])   # (2050, 1024)

vectors, _, _ = embed.encode(['청년 창업 초기기업 자금 지원'])
q = np.asarray(vectors[0], dtype='<f4')

scores = M @ q                      # 정규화돼 있어 내적이 곧 코사인 유사도
for i in np.argsort(-scores)[:5]:
    print(round(float(scores[i]), 4), ids[i], titles[i][:40])
```

### 형식

```
바이트 순서   float32 리틀엔디안. np.frombuffer(blob, dtype='<f4')
차원          1024 (notices.embedding_dim)
길이          정확히 4,096 바이트
정규화        되어 있음. 노름이 1.0 이다
모델          BAAI/bge-m3 · 512토큰 · 6필드 입력
```

질의도 **같은 모델로** 인코딩해야 합니다. `embed.encode()` 를 쓰면 맞습니다.
`embed.encode()` 는 `(vectors, token_counts, over_limit)` 세 개를 돌려줍니다.

첫 호출은 모델 로딩에 13초쯤 걸리고 2.2GB 를 읽습니다. RAM 4GB 이상을 권합니다.
질의 인코딩 없이 공고끼리 유사도만 볼 거라면 모델이 필요 없습니다.

### 벡터가 없는 공고

`embedding IS NULL` 인 공고는 검색 결과에 안 나옵니다. 유사도를 잴 것이 없기 때문입니다.
배치가 매일 채우지만, 그날 들어온 공고는 배치가 돌기 전까지 비어 있습니다.

```sql
SELECT COUNT(*) FROM notices WHERE embedding IS NULL;
```

---

## ⚠ `SELECT *` 를 쓰지 마세요 (notices)

`notices` 에 벡터 컬럼이 생겼습니다. **행마다 4KB 짜리 BLOB 이 따라옵니다.**

```
SELECT * FROM notices LIMIT 200        57ms
SELECT notice_id, title, apply_end ...  20ms     ← 2.8배 차이
```

2,050건 전체를 `SELECT *` 로 뽑으면 벡터 8MB 가 그냥 딸려 옵니다. 목록·상세
화면처럼 벡터가 필요 없는 곳은 **컬럼을 명시**하세요.

벡터가 필요할 때만 `embedding` 을 넣고, 그때도 전체를 한 번에 읽지 말고
필요한 공고만 골라 읽는 쪽이 낫습니다.

```sql
-- 목록 화면
SELECT notice_id, title, organizer, apply_start, apply_end, recruitment_status
  FROM notices WHERE recruitment_status = 'open';

-- 검색할 때만
SELECT notice_id, embedding FROM notices WHERE embedding IS NOT NULL;
```

`attachment_files` 도 같습니다. `bytes` 를 빼면 목록 조회가 1,646개에 29ms 입니다.

```sql
SELECT content_sha256, ext, byte_size FROM attachment_files;   -- bytes 제외
```

---

## 4. 공고 자체

컬럼 뜻은 `information_schema` 의 COMMENT 에 전부 한국어로 적혀 있습니다.

```sql
SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT
  FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = 's_brain' AND TABLE_NAME = 'notices'
 ORDER BY ORDINAL_POSITION;
```

자주 걸리는 것 몇 개만 미리 말해둡니다.

| 컬럼 | 주의 |
|---|---|
| `apply_end` | NULL 이면 **마감일 없음이 아니라** 고정 종료일이 없거나 해석 불가입니다. `apply_period_type` 을 함께 보세요 |
| `recruitment_status` | API 가 준 값입니다. 날짜로 추정하지 않았습니다 |
| `age_condition_raw` | 없다고 **업력 제한이 없다는 뜻이 아닙니다.** 알 수 없음입니다 |
| `region` | 기관명으로 추정하지 않았습니다. 없으면 NULL |
| `body` | API 사업개요입니다. **첨부 전문이 아닙니다.** 전문은 `attachment_texts` |
| `raw` | 출처 API 원본 전체입니다. 정규화가 의심되면 여기와 대조하세요 |

---

## 갱신 주기

배치가 하루 한 번 돌면서 9단계를 지납니다. 자세한 것은 [FLOW.md](FLOW.md).

```
1~4  공고 수집·정규화·저장
5    첨부 받아 본문 추출
6~7  임베딩·색인
8    벡터를 이 DB 로
9    첨부 원본 파일을 이 DB 로
```

5·6·8·9 단계는 **바뀐 것만** 처리합니다. 첨부 파일도 해시가 같으면 다시 올리지
않으므로, 첫 실행만 620MB 이고 그 뒤로는 그날 새로 받은 것뿐입니다.

배치가 하루 빠지면 그날 공고가 없는 것이고, 다음 실행이 따라잡습니다.
데이터가 사라지지는 않습니다.
