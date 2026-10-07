# Codex 검수 요청 — 판정표 P1 수정: 지문(문서 해시)으로 신선도 확인 (2026-09-29)

작성: Claude · 요청: 사용자(이근준) · 수행: Codex · 브랜치 `feature/SB-189-data-collection`

- 결과는 이 폴더에 `JUDGMENT_FRESHNESS_REVIEW_20260929.md`로 남겨 달라.
- **코드·DB는 고치지 않는다.** Git 스테이징·커밋도 하지 않는다. 공용 DB는 **SELECT만** 한다. 유료 API 호출은 없다.
- 고칠 것이 있으면 결과 문서에 적는다. 수정은 Claude가 한다.

## 0. 먼저 알아 둘 것

### 무엇을 고쳤나
[9/28 재검수](JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md)에서 남은 P1 세 건과 13단계 P2를 고쳤다. 9/29 오전에는 사용자 요청으로 멈췄다가 오후에 다시 시작했다.

| # | 재검수 지적 | 고친 방식 |
|---|---|---|
| P1-① | 파일 지문이 DB와 다르면 파일이 새것이라고 가정해 DB를 덮는다. 옛 파일이 `blocked`를 되살릴 수 있다 | 공고마다 **지금 공고문의 지문**과 같은 쪽을 쓴다(DB → 파일 순서). 둘 다 다르면 쓰지 않는다('모름') |
| P1-② | 결과 파일 한 줄이 깨지면 `JSONDecodeError`가 `load_auto()` 밖으로 나와 `app.boot()`가 멈춘다 | `load()`가 예외를 내지 않는다. 깨진 줄은 건너뛰고 `bad_lines`로 센다. 파일을 못 읽으면 error만 남긴다 |
| P1-③ | 파일이 없는 호스트(EC2·조율 에이전트)가 DB에 남은 오래된 `blocked`를 쓴다. 95%는 완전성의 근거가 아니다 | 파일이 없어도 DB만으로 같은 지문 대조를 한다. 95% 완전성 규칙은 없앴다 |
| P2 | 13단계 90% 가드가 정상 범위 축소를 막고, 중복 줄은 통과시킨다 | 같은 공고가 파일에 두 번 이상 있으면 그 표를 올리지 않는다(error). 현재 `notices`에 있는 고유 공고 수가 90% 미만이면 **경고만** 남기고 맞는 행은 올린다 |

### 사용자 결정 (2026-09-29)
- **새 표(`judgment_uploads` 등 DDL)는 만들지 않는다.** 판정 행마다 이미 있는 `document_sha256`을 지금 공고문과 대조하는 것으로 신선도를 증명한다.
- **프롬프트 버전(`prompt_sha256`)은 대조하지 않는다.** 프롬프트를 바꿔도 다시 판정할 때까지 옛 판정을 쓴다.
- **업종 판정(`search/industry_rank.py`)은 이번 범위 밖**이다. 순위 기능이 기본으로 꺼져 있다.

### 지문은 어떻게 구하나
- 서비스가 켜질 때 11단계가 쓰는 **같은 함수** `experiments/sql_semantic/applicant_type_llm.load_population(connection)`으로 공고 문서를 만들고 해시를 얻는다. 입력은 공고 본문, 지원대상, 첨부 본문이다.
  - 11단계 `collect/applicant_type_daily.py`도 이 함수로 대상을 만든다.
- 측정(9/29, 공용 DB SELECT만): 2,525건에 1.7초, 모듈 불러오기 0.11초(모델·API 라이브러리 없음).
- 공용 DB 판정 2,525행 모두 지금 지문과 같았다.
- 지문을 계산하지 못하면 **판정을 하나도 쓰지 않는다**(`active False` + error). 이때 결과는 이 기능이 생기기 전과 같다. 즉 예비창업자 본문 판정으로 공고를 빼지도, 되살리지도 않는다.

## 1. 바뀐 파일

| 파일 | 바뀐 것 |
|---|---|
| `search/applicant_types.py` | `load()` 예외 없음(`bad_lines`) · 새 함수 `current_document_hashes()`·`fresh_only()` · `load_auto()` 다시 씀(`current` 인자 추가, `COMPLETE_RATIO` 삭제, 반환에 `fresh_from_db`·`refreshed_from_file`·`stale`·`no_document`·`bad_lines`) · 모듈 설명 |
| `search/app.py` | `boot()`: 신청자 유형 기능이 꺼지면 `boot_errors['applicant_types']`를 남긴다 · `/api/health`에 `applicant_types` 신선도 항목 추가 |
| `collect/upload_judgments.py` | `run()`: 중복 공고 줄은 error(표를 올리지 않음), 공고 수 90% 미만은 warning(올림) · `MIN_FILE_RATIO` 설명 |
| `collect/daily_pipeline.py` | 13단계 `warning` 집계 · `stage_warnings_of()`가 `warning`을 인식한다(종료 코드 4) |
| `web/collection_status.html` | 수집 상태 화면에 경고(`warning`) 표시 |
| `tests/test_judgments_source.py` | 신청자 유형 부분을 새 규칙으로 바꾸고 15개로 늘렸다 |
| `tests/test_upload_judgments.py` | 90% 테스트를 경고로 바꿨다 · 중복 테스트, 살아 있는 공고만 세는 테스트를 추가했다 |
| `tests/test_applicant_type_daily.py` | `warning` 경고 |
| 문서 | `docs/guides/JUDGMENT_TABLES.md` 6절 · `docs/guides/ORCHESTRATION_HANDOFF.md` 3.3 · `share/전체흐름.html` 두 곳 · STATUS · WORKLOG |

변경은 `git diff -- data-collection/search data-collection/collect data-collection/web data-collection/tests`로 볼 수 있다. 모두 미커밋 상태다.

## 2. 우선순위 높음 — P1이 정말 해결됐나

1. **옛 판정으로 신청 가능한 공고가 빠지는 경로가 남았는가.**
   - 확인할 곳: `fresh_only()`·`load_auto()`, 그리고 판정을 쓰는 곳(`search/app.py` `eligible_with_types`·`match`·`eligibility`, `applicant_types.pre_founder`·`type_check`)
   - 모드별로 본다: `auto`·`db`·`file`, 연결 없음, DB 읽기 실패 + 파일 있음, 지문 계산 실패
2. **서버 시작이 예외로 멈출 경로가 남았는가.** 예외가 나는 곳은 `boot_errors`로만 가야 한다.
   - 살펴볼 후보: `load_db`, `current_document_hashes`(`load_population`의 SQL·문서 만들기), 파일 권한·인코딩·폴더, `_info()`에 이상한 값
   - `search/app.py` `boot()`에서 `load_auto` 호출은 try 안이지만 except가 없다(finally만 있음). `load_auto`가 정말 예외를 내지 않는지 봐 달라.
3. **서비스와 11단계의 지문이 정말 같은 값인가.**
   - 판정 뒤 공고문이 바뀌지 않았는데 "다름"이 나올 수 있는 경우를 찾아 달라. 이런 경우가 있으면 판정을 쓰지 않아 기능이 조용히 줄어든다.
   - 후보:
     - 첨부 본문 순서(SQL `ORDER BY at.text_chars DESC`에서 같은 길이일 때)
     - `notice_conditions`의 `legacy` 값이 문서에 섞이는지(`load_population`이 읽는다)
     - 첨부 추가·재추출 시점
     - `build_document`의 잘림
   - 공용 DB SELECT로 다시 대조해 봐도 된다(9/29 Claude 측정: 2,525 모두 같음).
4. **이 기능이 꺼질 때 조율 연결에 문제가 없는가.**
   - `docs/guides/ORCHESTRATION_HANDOFF.md`의 G-01 예시 `eligibility_of()`는 `types_mod.pre_founder(app.STATE.get('applicant_types') or {}, notice_id)`를 쓴다.
   - 판정이 비거나 꺼진 표에서도 예외 없이 "모름"으로 동작하는지 봐 달라.

## 3. 우선순위 보통 — 회귀와 13단계

1. **`load_auto` 반환 모양이 바뀌었다.**
   - 쓰는 곳: `eval/filter_first_eval.py`(boot 뒤 판정 사용), `experiments/*`, `collect/upload_judgments.py`(`type_rows`가 쓰는 applicant_types 함수), 화면(8010 `/applicant-types` 등), 테스트
   - 이 중 깨지거나 뜻이 바뀌는 곳이 있는지 본다.
   - `APPLICANT_TYPES_SOURCE=file`·`db` 모드의 의미 변화가 문서(`JUDGMENT_TABLES.md` 6절)와 맞는지 본다.
2. **13단계 중복 검사가 정상 파일을 잘못 막을 수 있는가.**
   - 11단계(`applicant_type_daily.py`)와 12단계(`industry_daily.py`)의 누적 파일이 정말 공고당 한 줄인지 확인해 달라. 재시도·재개·다시 판정할 때 한 공고가 두 줄이 되는지도 본다.
   - 업종 표에도 같은 검사를 거는 것이 맞는지 본다.
3. **90% 경고가 평소에 오탐이 되는가.**
   - 예: `notices`에서 공고가 빠지는 날, 12단계가 하루 상한(300)으로 미룬 날
   - 경고로 바꾼 뒤에도 손상된 파일이 DB를 망칠 경로가 있는가. 예: 잘못된 내용의 행이 `changed`로 올라가는 경우
4. `stage_warnings_of()`의 `warning`이 종료 코드 4, `collect_log.jsonl`, 수집 상태 화면에 맞게 이어지는가.

## 4. 검증 방법

```powershell
# data-collection 에서
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests            # Claude 9/29: 637개 통과(건너뜀 13)
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_judgments_source tests.test_upload_judgments tests.test_applicant_type_daily
.\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration   # D·A·B·C 통과
.\.venv\Scripts\python.exe -X utf8 -m collect.upload_judgments --plan      # DB 읽기만
```

- 가상환경이 Codex 환경에서 실행되지 않으면 지난번처럼 번들 Python 3.12에 `.venv/Lib/site-packages`를 붙여 써도 된다.
- **Claude 실측 (9/29, 공용 DB SELECT만)**:
  - 별도 프로세스에서 `app.boot()`: 21.7초, `boot_errors` `{}`
  - 신청자 유형: DB 2,525 · 파일 0 · 지문 다름 0 · 깨진 줄 0
  - 매칭(예비창업자 · "AI 기반 반려동물 건강관리 앱" · 서울): 필터 통과 1,594, 본문 불가 181, 접수 마감 756, 업력·유형 107, 되살림 9 — 고치기 전과 같다
- 켜져 있는 8000 서버는 새 코드로 재시작했다.
  - `/api/health` → `applicant_types: {active: true, source: db:notice_applicant_types, used: 2525, fresh_from_db: 2525, refreshed_from_file: 0, stale: 0, bad_lines: 0, error: null}`
- **하지 못한 것**
  - Claude 보조 에이전트 교차 검토: 권한 검사 일시 오류로 실행하지 못했다.
  - Linux(EC2)에서의 boot
  - 실제 배치 13단계의 경고 경로: 2026-09-30 09:00 배치가 처음이다.

## 5. 결과 문서에 남겨 달라

- 지적마다 P1(틀린 결과·장애) / P2(오해·누락) / P3(문구)로 나누고 **재현 근거**를 붙인다. 근거는 명령, 가짜 데이터, 코드 위치다.
- 확인하지 못한 것은 이유와 함께 따로 적는다.
- 관례대로 [STATUS](../../STATUS.md), [WORKLOG](../../WORKLOG.md), [문서 지도](../../README.md)에 한 줄씩 남긴다.

## 6. 참고 문서

- [9/28 판정 테이블 재검수](JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md) — 이번에 고친 P1의 출처
- [판정 테이블 설계](../../guides/JUDGMENT_TABLES.md) 6절 — 새 읽기 규칙
- [조율 함수 설명서](../../archive/ORCHESTRATION_HANDOFF.md) 3.3 — 서버 시작 주의(알려진 문제 → 수정)
- [STATUS](../../STATUS.md) 맨 위 · [WORKLOG](../../WORKLOG.md) "판정표 P1 — 지문(문서 해시)으로 신선도 확인"
