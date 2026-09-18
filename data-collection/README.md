# 공고 수집 배치

## AI와 함께 작업할 때

시작 전에 [공통 작업 규칙](AGENTS.md) → [현재 상태](docs/STATUS.md) →
[최근 작업 이력](docs/WORKLOG.md)을 읽습니다. Claude의 진입 안내는 [CLAUDE.md](CLAUDE.md)입니다.
기능 연결은 [FLOW.md](docs/FLOW.md)에서 확인하고, 작업 후에는 상태와 이력을 갱신합니다.
**Git 커밋과 push는 사용자가 직접 합니다. AI는 실행하지 않습니다.**

아래 수집 건수·시간 및 기존 문서의 수치는 기록 당시 값입니다. 현재 상태는 실제 코드와 실행 결과로 확인합니다.

## 수집 개요

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
  8  벡터 업로드           공용 MySQL 로. 팀이 같은 벡터를 쓴다
  9  첨부 파일 업로드      공용 MySQL 로. 팀이 파일로 개발한다
```

**5·6·7·8·9단계는 바뀐 것만 처리합니다.** 실측으로 신규 49건이 들어온 날
첨부 49건 · 임베딩 49건만 처리하고 나머지 1,951건은 건너뛰었습니다.

---

## 폴더

```
collect/      공고를 모아 DB 에 넣는 배치 (매일 09:00)
search/       공고를 찾아 보여주는 검색·매칭 (app.py · 하이브리드 서치 · 자격 판정)
shared/       둘이 함께 쓰는 것 (설정 · DB · 임베딩 입력 · 지역 어휘)
ec2/          EC2 에서만 도는 것 (벡터 색인 갱신 등)
scripts/      가끔 한 번 돌리는 도구
db/           테이블 생성문과 변경 이력 (.sql)
web/          시험용 화면 (search/app.py 가 내려줍니다)
tests/        시험 코드
docs/         문서 · 제출물
eval/         검색 품질 평가 (질의·판정·지표)
ml/           리랭커·업력 분류기 학습 (서비스 미연결)
data/         산출물 — 원본 스냅샷·벡터·첨부 (git 제외)
reports/      배치 실행 기록 (git 제외)
```

**패키지라서 파일을 직접 부르지 않고 `-m` 으로 부릅니다.** 항상 이 폴더에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline   # 배치
.\.venv\Scripts\python.exe -X utf8 -m search.app               # 검색 화면 (127.0.0.1:8000)
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

---

## 요청하신 세 가지가 여기 있습니다

### 1. 공고 가지고 오는 소스

| 파일 | 하는 일 |
|---|---|
| `collect/daily_pipeline.py` | **진입점.** 다섯 단계를 순서대로 부른다 |
| `collect/fetch.py` | K-Startup 오픈API 호출. 100건씩 쪽 나눔 |
| `collect/fetch_bizinfo.py` | 기업마당 오픈API 호출. 한 번에 전량 |
| `collect/daily_job.py` | K-Startup 수집·검증·원자적 교체 |
| `collect/normalize.py` | 두 출처를 공통 형식으로. 날짜·주소 정리 |
| `shared/store_mysql.py` | MySQL 저장. upsert·첨부·트랜잭션·TLS |
| `collect/attachment_pipeline.py` | 첨부 다운로드 → 텍스트 추출 → 적재 |
| `collect/attachment_store.py` | 추출 결과를 `attachment_texts` 에 저장 |
| `collect/doctext.py` · `collect/hwp5.py` | PDF·HWP·HWPX 텍스트 추출 |
| `shared/config.py` | `.env` 읽기 (표준 라이브러리만) |
| `collect/job_lock.py` | 중복 실행 방지 (파일 잠금) |
| `shared/embed.py` | 공고 요약 임베딩 생성 (BGE-M3) |
| `search/vecstore.py` | Chroma 벡터 색인 |
| `collect/upload_vectors.py` | 벡터를 공용 MySQL 로 올린다 |
| `collect/upload_attachments.py` | 첨부 원본 파일을 공용 MySQL 로 올린다 |

📄 **[FLOW.md](docs/FLOW.md)** — 배치가 도는 동안 이 파일들이 서로 무엇을 주고받나

### 2. 스케줄러 스크립트

| 파일 | 하는 일 |
|---|---|
| `run_daily.bat` | 매일 실제로 실행되는 것. 파이썬을 부르고 로그를 남긴다 |
| `schedule-task.ps1` | 예약을 등록·조회·해제하는 것. 처음 한 번만 쓴다 |

📄 **[SCHEDULER.md](docs/SCHEDULER.md)** — 등록하는 법, 상태 보는 법, 문제 해결

### 3. DB SQL문

| 파일 | 하는 일 |
|---|---|
| `db/mysql_schema.sql` | 테이블 생성문 (DDL) |
| `db/mysql_migration_002_embedding.sql` | `notices` 에 임베딩 컬럼 5개 추가 |
| `db/mysql_migration_003_attachment_files.sql` | 첨부 원본 파일 보관 테이블 |

📄 **[QUERIES.md](docs/QUERIES.md)** — 배치가 실행하는 SQL 전체와 그 뜻
📄 **[FIELD_MAP.md](docs/FIELD_MAP.md)** — API 필드가 어느 DB 컬럼이 되는지
📄 **[TEAM_DATA.md](docs/TEAM_DATA.md)** — **팀원용.** 공고·첨부 파일·벡터를 개발에 쓰는 법

---

## 시작하기

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Copy-Item .env.example .env      # 인증키와 DB 접속 정보를 채운다
```

DB 를 처음 만든다면,

```powershell
.\.venv\Scripts\python.exe -X utf8 -m shared.store_mysql --init-schema
```

손으로 한 번 돌려봅니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline --dry-run    # 수집·정규화만
.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline              # 전체
```

여기서 성공하면 예약을 겁니다 → [SCHEDULER.md](docs/SCHEDULER.md)

명령줄 옵션:

```
--dry-run          수집·정규화만. DB 저장 안 함 (API 는 실제로 호출한다)
--skip-store       MySQL 저장 생략
--skip-attach      첨부 수집 생략
--attach-limit N   이번 실행에서 받을 첨부 상한
--skip-embed       임베딩 생략 (torch·chromadb 없이도 돈다)
--embed-limit N    이번 실행에서 만들 벡터 상한
--skip-upload      벡터를 공용 DB 로 올리지 않는다
--skip-files       첨부 원본 파일을 올리지 않는다
--force            건수 급감 경고 무시
```

종료 코드: `0` 성공 · `1` 실패 · `2` 부분 실패 · `3` 이미 실행 중

## 검증

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

81개 통과를 확인했습니다(MySQL 통합 13개는 접속 정보가 없으면 건너뜁니다).
