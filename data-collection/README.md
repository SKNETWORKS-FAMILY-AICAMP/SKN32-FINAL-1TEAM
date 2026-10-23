# data-collection — 공고 데이터 · 매칭 · 자격 판정

S-Brain에서 **정부지원사업 공고를 모으고, 신청자에게 맞는 공고를 고르고, 신청할 수 있는지 판정하는** 부분입니다.
비유하면 도서관과 같습니다. 매일 아침 새 책(공고)을 서가(공용 DB)에 꽂고(매일 배치), 사서(공고 서버)가 손님에게 맞는 책을 골라 줍니다.

- 담당: 이근준
- **처음이면 여기부터:** [문서 지도](docs/README.md) → [구성](docs/architecture.md) → [실제 실행 순서](docs/FLOW.md)
- 다른 팀원이 쓰는 법: 조율 에이전트는 [공고 서버 HTTP 창구](docs/contracts.md)([사용법 엑셀](docs/notice_api/공고서버_API_사용법.xlsx) · [연결 지도](docs/notice_api/공고매칭_조율연결_지도.html)), 팀원은 [공용 DB 테이블](docs/guides/TEAM_DATA.md)
- 코드를 고치기 전에: [어기면 깨지는 규칙](docs/standards.md) · [자주 빠지는 함정](docs/engineering-notes.md). **Git 커밋과 push는 사용자가 직접 합니다.**

문서 속 건수·시간은 기록 당시 값입니다. 지금 상태는 코드와 실행 결과로 확인합니다.

---

## 무엇이 어디서 도는가

| 무엇 | 어디서 | 언제 |
|---|---|---|
| **매일 배치** (`collect/daily_pipeline.py`, 14단계) | AWS 공고 서버 EC2 — systemd `notice-batch.timer` | 매일 한국 09:00. 끝나면(성공 · 실패 모두) 공고 서버를 다시 띄움 |
| **공용 DB** (MySQL `s_brain`) | AWS RDS. 사설망이라 웹 서버 · 공고 서버에서만 닿음 | 늘 |
| **공고 서버** (`search/app.py`, :8000) — 조율 에이전트(워커)가 부르는 창구 4개 | AWS 공고 서버 EC2 (사설 주소 `10.20.11.10`) — systemd `notice-server`. 웹 서버에서 오는 요청만 받음 | 늘. 배치가 끝나면 다시 떠서 새 공고를 올림 |
| 검증 화면 (:8010) · 평가 · 학습 | 이 PC | 손으로 켤 때만 |

서버 · DB는 저장소 루트 [infra/aws](../infra/aws/README.md)의 `up.sh`로 만들고, 공고 서버와 매일 배치는 [infra/aws/notice](../infra/aws/notice/README.md)의 `deploy-notice.sh`로 올립니다. 서버 상태 · 배치 기록을 보는 명령도 그 문서에 있습니다. 10/19까지 쓰던 개인 서버(13.125.40.88)와 팀 EC2(43.201.90.238)는 더 쓰지 않습니다.

자세한 그림과 흐름은 [docs/architecture.md](docs/architecture.md), PC에서 쓰는 명령과 환경 변수는 [docs/operations.md](docs/operations.md).

## 매일 배치 14단계

```
 1  K-Startup 수집              모집 중 목록 전체
 2  기업마당 수집               한 번에 전량
 3  정규화                      두 출처를 한 형식으로
 4  공용 DB 저장                없으면 추가 · 있으면 수정 · 목록에서 빠진 K-Startup 공고는 모집 종료
 5  첨부 받기 · 본문 추출        기업마당 공고문 첨부만 (K-Startup 첨부는 robots.txt 금지)
 6  임베딩 생성 (BGE-M3)         내용이 바뀐 공고만
 7  로컬 벡터 색인 (Chroma)      공고 서버는 더 쓰지 않음. 평가 도구용으로 남아 있음
 8  벡터 올리기                  공용 DB notices.embedding — 공고 서버가 이것을 메모리에 올려 검색
 9  첨부 원본 올리기              공용 DB attachment_files
10  자격요건 추출 (LLM)           지원 금액 · 업력 → notice_conditions
11  신청자 유형 추출 (LLM)        예비창업자 · 개인사업자 · 법인
12  업종 추출 (LLM)              신청 가능 업종
13  판정 올리기                  11 · 12 결과 → notice_applicant_types · notice_industries
14  가점 추출 (LLM)              가점 · 우대 문구 → notice_bonus
```

5단계부터는 바뀐 것만 처리합니다. 종료 코드: `0` 성공 · `1` 실패 · `2` 부분 실패(출처 하나 이상 실패) · `3` 이미 실행 중 · `4` 수집은 성공, 5~14단계 경고.
단계마다 파일이 주고받는 것은 [docs/FLOW.md](docs/FLOW.md).

## 폴더

```
collect/      매일 배치 14단계
search/       공고 서버 — 정형 필터 · 하이브리드 검색 · 순위 규칙 · 자격 판정 · 가산점 · 조율 창구
shared/       함께 쓰는 것 — 설정 · DB 저장 · 임베딩 입력 · 지역 어휘
ec2/          리눅스 서버에서 쓰던 DB 접속 · 점검 도구. 옛 Chroma 색인 갱신 스크립트도 아직 여기 있음
db/           테이블 생성문과 변경 SQL
web/          공고 서버가 내려 주는 시험 화면과 검증 화면(8010) HTML
experiments/  검증 화면(8010) · 계약 시험 · 배치가 쓰는 LLM 추출 함수
eval/         검색 품질 평가 (질의 · 판정 · 지표)
ml/           리랭커 · 업력 분류기 학습 (제출물, 서비스 미연결)
tests/        시험 코드
docs/         문서 · 제출물 — 무엇이 어디 있는지는 docs/README.md
reports/      실험 · 평가 결과 (Git에 올라감, 기존 폴더는 덮어쓰지 않음)
data/         원본 스냅샷 · 벡터 · 첨부 (Git 제외)
```

## 시작하기

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env      # 인증키와 DB 접속 정보를 채운다
```

LLM 추출(배치 10~14단계)을 돌리려면 `.env`에 `OPENAI_API_KEY`도 넣습니다. `.env.example`에는 이 줄이 없고, 없으면 그 단계를 건너뜁니다.

**패키지라서 파일을 직접 부르지 않고 `-m`으로 부릅니다.** 항상 이 폴더에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests          # 시험
.\.venv\Scripts\python.exe -X utf8 -m search.app                          # 공고 서버 127.0.0.1:8000 (창구 시험 화면 /docs)
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.viewer     # 검증 화면 127.0.0.1:8010
.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline --dry-run    # 배치: 수집 · 정규화만
```

배치 명령줄 옵션은 `-m collect.daily_pipeline --help`로 봅니다. 각 단계를 건너뛰는 `--skip-…`과 상한 `--…-limit`이 있습니다.
**배치를 이 PC에서 전체로 돌리면 `.env`의 `MYSQL_*`가 가리키는 DB에 씁니다.** 실제 매일 배치는 공고 서버에서 돌므로 PC에서는 `--dry-run`이나 `--skip-store`로 시험합니다.

## 참고 문서

| 문서 | 내용 |
|---|---|
| [docs/guides/QUERIES.md](docs/guides/QUERIES.md) | 배치가 실행하는 SQL과 그 뜻 |
| [docs/guides/FIELD_MAP.md](docs/guides/FIELD_MAP.md) | API 필드가 어느 DB 칸이 되는지 |
| [docs/guides/TEAM_DATA.md](docs/guides/TEAM_DATA.md) | **팀원용.** 공고 · 첨부 파일 · 벡터를 개발에 쓰는 법 |
| [docs/guides/JUDGMENT_TABLES.md](docs/guides/JUDGMENT_TABLES.md) | 공고 판정 테이블 설계 |
| [db/](db/) | 테이블 생성문 `mysql_schema.sql`과 변경 SQL `mysql_migration_*.sql` |
