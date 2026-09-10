# 공고 수집 배치

K-Startup·기업마당 오픈API 에서 지원사업 공고를 매일 한 번 받아 MySQL 에 넣고,
공고문 첨부(PDF·HWP·HWPX)에서 본문을 뽑아 함께 저장합니다.

```
매일 09:00
  1  K-Startup 수집        2초     266건
  2  기업마당 수집         10초   1,553건
  3  정규화               두 출처를 한 형식으로 → 1,819건
  4  MySQL 저장           없으면 추가 · 있으면 수정
  5  첨부 받기 · 본문 추출  바뀐 공고의 첨부만
  6  임베딩 생성           벡터가 없거나 내용이 바뀐 공고만
  7  벡터 색인 갱신        Chroma 에 그것만 넣는다
```

**5·6·7단계는 바뀐 것만 처리합니다.** 실측으로 신규 49건이 들어온 날
첨부 49건 · 임베딩 49건만 처리하고 나머지 1,951건은 건너뛰었습니다.

---

## 요청하신 세 가지가 여기 있습니다

### 1. 공고 가지고 오는 소스

| 파일 | 하는 일 |
|---|---|
| `daily_pipeline.py` | **진입점.** 다섯 단계를 순서대로 부른다 |
| `fetch.py` | K-Startup 오픈API 호출. 100건씩 쪽 나눔 |
| `fetch_bizinfo.py` | 기업마당 오픈API 호출. 한 번에 전량 |
| `daily_job.py` | K-Startup 수집·검증·원자적 교체 |
| `normalize.py` | 두 출처를 공통 형식으로. 날짜·주소 정리 |
| `store_mysql.py` | MySQL 저장. upsert·첨부·트랜잭션·TLS |
| `attachment_pipeline.py` | 첨부 다운로드 → 텍스트 추출 → 적재 |
| `attachment_store.py` | 추출 결과를 `attachment_texts` 에 저장 |
| `doctext.py` · `hwp5.py` | PDF·HWP·HWPX 텍스트 추출 |
| `config.py` | `.env` 읽기 (표준 라이브러리만) |
| `job_lock.py` | 중복 실행 방지 (파일 잠금) |
| `embed.py` | 공고 요약 임베딩 생성 (BGE-M3) |
| `vecstore.py` | Chroma 벡터 색인 |

📄 **[FLOW.md](FLOW.md)** — 배치가 도는 동안 이 파일들이 서로 무엇을 주고받나

### 2. 스케줄러 스크립트

| 파일 | 하는 일 |
|---|---|
| `run_daily.bat` | 매일 실제로 실행되는 것. 파이썬을 부르고 로그를 남긴다 |
| `schedule-task.ps1` | 예약을 등록·조회·해제하는 것. 처음 한 번만 쓴다 |

📄 **[SCHEDULER.md](SCHEDULER.md)** — 등록하는 법, 상태 보는 법, 문제 해결

### 3. DB SQL문

| 파일 | 하는 일 |
|---|---|
| `mysql_schema.sql` | 테이블 생성문 (DDL) |

📄 **[QUERIES.md](QUERIES.md)** — 배치가 실행하는 SQL 전체와 그 뜻
📄 **[FIELD_MAP.md](FIELD_MAP.md)** — API 필드가 어느 DB 컬럼이 되는지

---

## 시작하기

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Copy-Item .env.example .env      # 인증키와 DB 접속 정보를 채운다
```

DB 를 처음 만든다면,

```powershell
.\.venv\Scripts\python.exe -X utf8 store_mysql.py --init-schema
```

손으로 한 번 돌려봅니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 daily_pipeline.py --dry-run    # 수집·정규화만
.\.venv\Scripts\python.exe -X utf8 daily_pipeline.py              # 전체
```

여기서 성공하면 예약을 겁니다 → [SCHEDULER.md](SCHEDULER.md)

명령줄 옵션:

```
--dry-run          수집·정규화만. DB 저장 안 함 (API 는 실제로 호출한다)
--skip-store       MySQL 저장 생략
--skip-attach      첨부 수집 생략
--attach-limit N   이번 실행에서 받을 첨부 상한
--skip-embed       임베딩 생략 (torch·chromadb 없이도 돈다)
--embed-limit N    이번 실행에서 만들 벡터 상한
--force            건수 급감 경고 무시
```

종료 코드: `0` 성공 · `1` 실패 · `2` 부분 실패 · `3` 이미 실행 중

## 검증

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest test_normalize test_store_mysql test_pipeline test_doctext test_attachment_store
```

63개 통과를 확인했습니다(MySQL 통합 13개는 접속 정보가 없으면 건너뜁니다).
