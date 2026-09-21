# 정형 필터 + 의미 검색 (실험)

지시서: [docs/SQL_SEMANTIC_EXPERIMENT_TASK_20260918.md](../../docs/SQL_SEMANTIC_EXPERIMENT_TASK_20260918.md)

기존 서비스(dense + BM25 하이브리드)는 **그대로 둔다.** 이 폴더는 별도 로컬 MySQL 에서
다른 방식을 시험한다. VectorDB·BM25 를 쓰지 않는다.

```
공고 읽기(읽기 전용) → 로컬 실험 DB 에 스냅샷 + 정형 조건 저장
                     → 새 입력 계약으로 공고 벡터 생성·저장

신청자 입력 → SQL 정형 필터 → 남은 후보 전체와 코사인 비교 → 규칙 정렬 → Top N
```

## 준비 — `.env` 에 다섯 줄 추가

소스(운영) DB 설정과 **분리한다.** 값이 없으면 실행이 멈추고, 소스 DB 로 대체하지 않는다.

```
SQL_LAB_HOST=127.0.0.1
SQL_LAB_PORT=3306
SQL_LAB_USER=...
SQL_LAB_PASSWORD=...
SQL_LAB_DATABASE=notice_match_sql_lab
```

호스트가 로컬이 아니거나 DB 이름이 소스와 같으면 거부한다(`config.guard`).

## 재현 순서

```powershell
# 0. 무엇을 할지만 확인 (아무것도 쓰지 않음)
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.prepare --plan

# 1. 실험 DB·테이블 만들기
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.prepare --schema

# 2. 공고 스냅샷 + 정형 조건 (소스는 SELECT 만)
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.prepare --snapshot

# 3. 새 계약으로 벡터 생성 (CPU 기준 공고 1건당 약 3초)
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.prepare --embed --limit 50   # 먼저 소량
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.prepare --embed              # 전체

# 4. 한 건 검색해 보기
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.search `
    --idea "중소 제조기업의 스마트공장 구축" --region 경기 --founded-at 2023-03-01 --top 5

# 5. 기존 결과와 비교표 만들기 (필터 켬/끔 포함)
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.compare
```

테스트(외부 DB·모델 없이):

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_sql_semantic
```

## 파일

| 파일 | 하는 일 |
|---|---|
| `config.py` | 실험 DB 설정·안전장치(로컬만·소스와 분리·비밀번호 미출력) |
| `schema.sql` | `lab_notices` · `lab_conditions` · `lab_vectors` · `lab_runs` |
| `conditions.py` | 원문 → 정형 조건. `known` / `no_limit` / `unknown` 세 값 |
| `embedding.py` | 새 입력 계약(제목 → 지원 분야 → 지원 내용 → 신청 자격), 벡터 저장 규약 |
| `search.py` | SQL 필터 → 후보 전체와 코사인 → 규칙 정렬 → Top N |
| `compare.py` | 기존 결과와 나란히 보는 HTML·manifest·데이터 품질 |
| `fixtures.py` | 검증 화면용 가짜 데이터. 실제 추출기·검색 로직에 넣어 문제 사례를 재현한다 |
| `viewer.py` | 검증 화면 서버(읽기 전용, 기본 8010). 절차는 [VERIFY_UI.md](../../docs/VERIFY_UI.md) |

## 설계에서 지킨 것

- **모르는 조건은 탈락시키지 않는다.** `충족 / 불충족 / 확인 필요` 세 값으로 다루고,
  확인 필요는 후보로 남긴다. 남겼다고 자격이 보장되는 것은 아니다.
- **SQL 에서 거르는 것은 두 가지뿐이다** — 마감이 지난 공고, 지역이 확인됐는데 다른 지역 전용.
  업종·규모·지원 방식은 자격이 아니라 선호로 다룬다.
- **전체 Top-K 를 먼저 자르지 않는다.** SQL 로 거른 후보 **전체**와 유사도를 계산한다.
- 값은 파라미터로 넘긴다. 사용자 입력으로 SQL 문자열을 만들지 않는다.
- 코사인과 규칙을 섞어 하나의 '적합 확률'로 만들지 않는다. 순위가 바뀐 이유를 공고마다 남긴다.
- 벡터가 없거나 손상된 후보를 조용히 버리지 않고 건수로 보고한다.

## 아직 아닌 것

- 기존 `shared/embed.py` 6필드 계약·기존 NPZ·Chroma 는 건드리지 않는다.
- BM25 추가, 리랭커, 가중치 튜닝, 조건 추출 고도화는 이번 범위가 아니다.
- 사람 판정 없이 어느 방식이 낫다고 말하지 않는다.

## 눈으로 확인하기

저장된 결과와 fixture 를 브라우저에서 본다. 읽기 전용이라 검색을 새로 돌리거나 DB 에 쓰지 않는다.

```
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.viewer
```

→ http://127.0.0.1:8010 · 화면 설명과 확인 절차는 [docs/VERIFY_UI.md](../../docs/VERIFY_UI.md).
