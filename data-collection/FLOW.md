# 배치가 도는 동안 무슨 일이 일어나나

매일 09:00 에 한 번, 파이썬 파일 열두 개가 순서대로 일합니다.
이 문서는 **그 사이에 무엇이 오가는지**를 봅니다.

먼저 알아둘 것이 하나 있습니다. 파일끼리 주고받는 방식이 두 가지입니다.

```
함수 호출    메모리에서 바로 넘긴다. 빠르고 흔적이 안 남는다
파일 경유    디스크에 쓰고 다음 단계가 읽는다. 느리지만 나중에 볼 수 있다
```

**중요한 길목마다 일부러 파일을 만듭니다.** 왜 그런지는 맨 아래에 적었습니다.

---

## 한 장으로 보기

```
                        config.py     .env 를 읽어 모두에게 준다
                        job_lock.py   두 번 겹쳐 돌지 않게 잡는다
                             │
     run_daily.bat ──→ daily_pipeline.py          ← 지휘자
                             │
        ┌──────────┬─────────┴────────┬──────────────┐
        ▼          ▼                  ▼              ▼
   daily_job   fetch_bizinfo      normalize     store_mysql
        │          │                  │              │
     fetch         │                  │              │
        │          │                  │              │
        ▼          ▼                  ▼              ▼
  notices.json  raw/bizinfo   normalized/notices   MySQL
        └──────────┴──────────→ ─────┘                │
                                                       ▼
                                          attachment_pipeline
                                             │           │
                                        doctext     attachment_store
                                             │           │
                                        hwp5             ▼
                                             │         MySQL
                                             ▼
                                     data/attachments/

                        ─────────────────────────────────────
                             embed.py  ──→  vecstore.py
                                │                │
                                ▼                ▼
                       embeddings_v1.npz   data/vecstore/chroma/
```

`daily_pipeline.py` 는 **직접 일하지 않습니다.** 순서를 정하고 결과를 받아 기록만 합니다.

---

## 1단계 — K-Startup 공고 받기

```
daily_pipeline
   │  daily_job._run() 을 부른다
   ▼
daily_job.py
   │  fetch.fetch_all(키) 를 부른다
   ▼
fetch.py           오픈API 를 100건씩 세 번 호출
   │
   └─ 공고 리스트를 그대로 돌려준다        ← 함수 호출. 파일 안 거침
   ▼
daily_job.py
   │  건수를 어제와 견주어 검증한다
   │
   ├─→  data/notices.json                  556KB · 266건
   └─→  data/history/notices_20260910.json  어제 것을 여기로 옮긴다
```

**교체는 한 번에 일어납니다.** 임시 파일에 다 쓴 뒤 마지막에 이름을 바꿉니다. 중간에 전원이 나가도 반쯤 쓰다 만 파일이 남지 않습니다.

`daily_pipeline` 이 돌려받는 것:

```python
{'status': 'ok', 'count': 266, 'new_count': 18, 'archived': 'notices_20260910.json'}
```

---

## 2단계 — 기업마당 공고 받기

```
daily_pipeline
   │  fetch_bizinfo.fetch_snapshot() 을 부른다
   ▼
fetch_bizinfo.py    오픈API 를 한 번 호출 → 1,553건이 통째로 온다
   │
   └─→  data/raw/bizinfo_20260910T012502283113Z.json      3.5MB
   ▼
   (경로, 건수) 를 돌려준다              ← 데이터가 아니라 경로만 넘긴다
```

1단계와 다릅니다. **응답 원문을 한 글자도 손대지 않고 그대로 저장**합니다.

```python
with path.open('xb') as f:      # 'x' = 이미 있으면 실패. 덮어쓰지 않는다
    f.write(content)
```

나중에 "그때 API 가 정확히 뭘 줬나" 를 확인할 수 있게 하려는 것입니다.

파일 이름에 붙은 `20260910T012502283113Z` 는 받은 시각(UTC)입니다. 매번 새 파일이 생기고, 오래된 것은 14개만 남기고 지웁니다.

---

## 3단계 — 두 출처를 한 형식으로

```
daily_pipeline
   │  1·2단계가 만든 파일 두 개를 읽는다
   │  normalize.normalize_sources(...) 를 부른다
   ▼
normalize.py
   │  날짜 형식 통일 · 필드 이름 통일 · 주소 검사 · 중복 제거
   │
   └─→  data/normalized/notices_20260910T012502762949Z.json    8.6MB · 1,819건
```

**입력 두 파일 → 출력 한 파일.** 이 파일 안에서는 두 출처가 같은 모양을 하고 있습니다.

크기가 8.6MB 로 커진 이유는 **API 원본을 `raw` 필드에 그대로 함께 넣기 때문**입니다. 정규화가 뭘 잘못했을 때 원본과 바로 대조할 수 있습니다.

돌려받는 것:

```python
{'accepted_count': 1819, 'rejected_count': 0,
 'same_source_duplicate_count': 0, 'cross_source_candidate_groups': 3}
```

---

## 4단계 — MySQL 에 넣기

```
daily_pipeline
   │  정규화 파일을 바이트로 읽어 SHA-256 을 계산한다
   │  store_mysql.store_payload(연결, 내용, 해시) 를 부른다
   ▼
store_mysql.py
   │  config.py 에서 접속 정보를 읽어 EC2 에 붙는다 (TLS)
   │  공고 한 건마다 SQL 을 네 번 실행한다
   ▼
   MySQL      notices · notice_attachments · import_runs
```

해시를 같이 넘기는 이유는 **같은 파일을 두 번 넣었는지** 나중에 알기 위함입니다. `import_runs.input_sha256` 에 남습니다.

돌려받는 것:

```python
{'processed': 1819, 'skipped_older': 0, 'attachment_links': 2719,
 'run_id': '53d77efaeaf643d0856567cabbf2fa8d'}
```

---

## 5단계 — 첨부 받아 본문 뽑기

여기부터는 **파일이 아니라 DB 를 통해 이야기합니다.**

```
daily_pipeline
   │  attachment_pipeline.daily() 를 부른다
   ▼
attachment_pipeline.py
   │
   ① MySQL 에 물어본다 — "뭘 받아야 하지?"
   │     방금 4단계가 넣은 데이터를 근거로 고른다
   │     한 번도 안 받은 것 · 공고가 고쳐진 것 · 어제 실패한 것
   │
   ② 한 건씩 내려받는다 (1초 간격)
   │     doctext.py  →  hwp5.py       형식 판별 · 본문 추출
   │
   ③  data/attachments/9f/9f3a2b…c41.pdf      ← 내용 해시가 파일명
   │
   ④  data/attachment_results.jsonl           ← 한 건 끝날 때마다 한 줄
   │
   ⑤ attachment_store.save_attachment_result() → MySQL
   │
   ⑥  결과 파일을 data/history/ 로 치운다
```

### ④번이 「이어서 하기」의 핵심입니다

한 건 끝날 때마다 파일에 쓰고 **디스크까지 밀어냅니다**(`fsync`). 전원이 나가도 그때까지 한 것은 남고, 다시 실행하면 이어서 합니다.

### ⑥번을 왜 치우나

결과 파일이 남아 있으면 다음 실행이 "이건 이미 했네" 하고 건너뜁니다. **실패한 첨부도 건너뛰어서 영영 다시 안 받아집니다.**

역할을 이렇게 나눴습니다.

```
MySQL      무엇을 받아야 하는지 안다          ← 판단은 여기서만
결과 파일   이번 실행이 어디까지 했는지 안다     ← 중단 복구용
```

---

## 6단계 — 공고 요약을 벡터로

```
daily_pipeline
   │  embed.run() 을 부른다
   ▼
embed.py
   │
   ① MySQL 에서 공고를 읽는다
   │
   ② 여섯 필드를 이어붙여 입력을 만든다        ← build_input() 이 유일한 정의
   │     title · body · target_text
   │     target_category · category · subcategory
   │
   ③ 입력의 SHA-256 을 기존 것과 견준다
   │     해시가 없다   → 새 공고다.       만든다
   │     해시가 다르다 → 내용이 바뀌었다.  다시 만든다
   │     해시가 같다   → 그대로다.        건너뛴다
   │
   ④ 걸린 것만 BGE-M3 로 인코딩한다
   │
   └─→  data/embeddings_v1.npz     기존 것과 합쳐서 통째로 다시 쓴다
```

**매번 전부 만들지 않습니다.** 실측으로 신규 49건이 들어온 날 1,951건은
건너뛰고 49건만 53초에 처리했습니다. 전부 만들면 32분입니다.

저장은 임시 파일에 쓴 뒤 마지막에 바꿔칩니다. 중간에 끊겨도 반쯤 쓰다 만 파일이
남지 않습니다.

돌려받는 것:

```python
{'total': 2000, 'kept': 1951, 'made': 49,
 'changed_ids': ['kstartup:179102', 'bizinfo:PBLN_...', ...]}
```

`changed_ids` 가 다음 단계로 넘어갑니다.

### 설정이 바뀌면 전부 다시 만듭니다

내용이 그대로여도 **인코딩 조건이 달라지면** 옛 벡터와 섞을 수 없습니다.

```
model · revision · input_version · max_tokens · dim · dtype · normalized
```

이 일곱 개를 묶어 지문을 만들고, 지문이 다르면 전량 재생성합니다.
지금 지문은 `0a803d170f58c36e` 입니다.

---

## 7단계 — 벡터 색인 갱신

```
daily_pipeline
   │  vecstore.sync(changed_ids=6단계가 준 목록) 을 부른다
   ▼
vecstore.py
   │
   └─→  data/vecstore/chroma/       Chroma · HNSW · 코사인
```

**`upsert` 라서 바뀐 것만 넣으면 됩니다.**

```
새 notice_id      →  색인에 추가된다
있는 notice_id    →  건수는 그대로, 벡터만 덮어쓴다
나머지            →  손대지 않는다
```

`changed_ids` 를 주지 않으면 **색인과 벡터 파일을 대조해 빠진 것을 찾아** 넣습니다.
임베딩이 실패했던 날 다음에 저절로 복구됩니다.

### 건수가 어긋나면 알립니다

```
Chroma 49건 넣음 · 색인 2000건 · 벡터 파일 2000건
```

두 숫자가 다르면 경고를 냅니다.

```
⚠ 색인에 N건이 없다. 검색 결과에서 빠진다.
```

**색인에 없는 공고는 자격을 통과해도 검색 결과에 안 나옵니다.**
유사도를 잴 벡터가 없기 때문입니다. 조용히 빠지는 것이 제일 곤란해서 반드시 알립니다.

### 벡터는 MySQL 에 들어가지 않습니다

`notices` 에 임베딩 컬럼이 아직 없습니다. 그래서 벡터는 **배치가 도는 PC 에만** 있습니다.

```
EC2 MySQL     공고 · 첨부 · 본문        팀 공용
배치 PC       벡터 파일 · Chroma        여기에만
```

지금은 검색 화면도 로컬이라 문제가 없습니다. 화면을 팀에 공개할 때 다시 정합니다.

---

## 파일이 사는 곳

```
data/
  notices.json                  K-Startup 최신본          556KB
  raw/bizinfo_*.json            기업마당 응답 원본          3.5MB × 14개
  normalized/notices_*.json     두 출처 통합본             8.6MB × 14개
  attachments/9f/9f3a….pdf      첨부 원본                 612MB · 1,607개
  embeddings_v1.npz             공고 요약 벡터             7.4MB · 2,000건
  vecstore/chroma/              Chroma 색인               14MB
  history/                      어제 것들 · 처리 끝난 결과 파일
  collect_log.jsonl             실행마다 한 줄
  run.log                       배치 시작·종료 기록
  collection.lock               도는 동안만 존재
```

`raw` 와 `normalized` 는 **소스별 14개만 남기고 자동으로 지웁니다.**

---

## 왜 굳이 파일을 거치나

바로 DB 에 넣지 않고 중간에 세 번 파일을 만듭니다. 셋 다 이유가 있습니다.

**하나. 어제와 견줄 수 있습니다.**

건수가 어제의 절반 이하로 오면 API 가 망가진 것으로 보고 **오늘 받은 것을 쓰지 않습니다.** 어제 파일이 없으면 비교할 대상이 없습니다.

**둘. 어디서 틀렸는지 찾을 수 있습니다.**

```
DB 값이 이상하다
  → normalized 를 본다      정규화가 잘못했나?
  → raw 를 본다             API 가 그렇게 준 건가?
```

파일이 없으면 "API 가 이상했나 우리가 이상했나" 를 가릴 수 없습니다.

**셋. 중간에 끊겨도 이어서 합니다.**

첨부 1,616건을 받는 데 처음엔 한 시간이 걸립니다. 55분에서 끊겼을 때 처음부터 다시 하면 안 됩니다.

---

## 실패하면 어디까지 남나

```
1단계 실패 → 3번 재시도 후 어제 notices.json 유지
2단계 실패 → 어제 bizinfo 스냅샷을 그대로 3단계에 넘긴다
3단계 실패 → 여기서 멈춘다. DB 는 안 건드린다
4단계 실패 → 트랜잭션 전체를 되돌린다. DB 는 어제 상태
5단계 실패 → 공고는 이미 저장됐다. 첨부만 내일 다시
6단계 실패 → 벡터 파일은 그대로. 다음 실행이 못 만든 것을 다시 고른다
7단계 실패 → 벡터는 만들어졌다. 다음 실행이 색인의 빠진 것을 찾아 넣는다
```

**한 출처가 죽어도 나머지는 갱신됩니다.** 그 경우 상태가 `partial` 로 기록되고 종료 코드 `2` 가 나옵니다.

---

## 직접 확인해보기

```powershell
# 저장 없이 1~3단계만
.\.venv\Scripts\python.exe -X utf8 daily_pipeline.py --dry-run

# 첨부만 따로, 대상만 세어 보기
.\.venv\Scripts\python.exe -X utf8 attachment_pipeline.py --plan

# 임베딩을 만들 것이 몇 건인지
.\.venv\Scripts\python.exe -X utf8 embed.py --plan

# 색인 상태
.\.venv\Scripts\python.exe -X utf8 vecstore.py --stat
```

`--dry-run` 도 **API 는 실제로 호출합니다.** 무부작용 검사가 아닙니다.

실행 기록은 `data/collect_log.jsonl` 에 한 줄씩 쌓입니다.

```json
{"status": "ok", "job": "pipeline",
 "sources": {"kstartup": {"status": "ok", "count": 266, "new_count": 18},
             "bizinfo":  {"status": "ok", "count": 1553}},
 "normalized_count": 1819, "stored": true, "elapsed_sec": 72.5}
```
