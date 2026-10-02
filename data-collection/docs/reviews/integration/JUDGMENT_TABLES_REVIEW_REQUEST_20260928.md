# Codex 검수 요청 — 저녁 수정 재검수 + 공고 판정 테이블·12·13단계·서비스 DB 읽기·업력 반영 (2026-09-28)

작성: Claude · 요청: 사용자(이근준) · 수행: Codex
결과는 이 폴더에 `JUDGMENT_TABLES_REVIEW_20260928.md`로 남겨 달라. **코드·DB는 고치지 말고**, Git 스테이징·커밋도 하지 않는다.
공용 DB는 **SELECT만** 해 달라. 이번 범위의 표·행은 이미 만들어져 있다.

## 0. 먼저 알아 둘 것

### 방향 (사용자 결정, 2026-09-28)

- 배치는 사용자 PC에서 계속 돌린다.
- 판정 결과(신청자 유형·업종·업력)는 **공용 DB에 올려** 팀원·EC2도 쓰게 한다.
- 기존 표는 건드리지 않고 **새 표 두 개**를 만든다(A안).

### 오늘 공용 DB(`s_brain`)에 실제로 쓴 것 — 모두 사용자 요청·확인 뒤

| 무엇 | 내용 | 누가 |
|---|---|---|
| 표 생성 | `db/mysql_migration_006_notice_judgments.sql`로 `notice_applicant_types`·`notice_industries`를 `CREATE TABLE IF NOT EXISTS`로 만들었다. 실행 전 같은 이름 표 없음 확인 | Claude |
| 칸 설명 수정 | 빈 `notice_industries.status`의 COMMENT를 실제 값 6종으로 `ALTER … MODIFY` | Claude |
| 첫 업로드 | `python -m collect.upload_judgments`로 두 표에 각 2,476행 | Claude |
| 업력 반영(C-3) | `python -m experiments.sql_semantic.age_rerun --apply …`로 `notice_conditions` 78행 업력 칸 UPDATE. 백업 `reports/age_rerun_luna_20260928T054509Z/applied_backup_20260928T074751Z.jsonl`. Claude 명령이 자동 권한 검사에서 막혀 **사용자가 직접 실행** | 사용자 |

### 지금 데이터 흐름

```
[배치 PC 09:00] … 10단계 자격요건(→ notice_conditions) → 11단계 신청자 유형(→ data/applicant_types/)
                → 12단계 업종(→ data/industries/, 신규) → 13단계 판정 올리기(→ 두 새 표, 신규)
[검색 서비스] 시작할 때 신청자 유형은 DB 먼저(없으면 파일), 업종은 파일(final5) 유지, 업력 근거는 DB + 재추출 파일
```

설계·사용법: [docs/guides/JUDGMENT_TABLES.md](../../guides/JUDGMENT_TABLES.md). 흐름 그림: `http://127.0.0.1:8010/flow` "⓪ 데이터 지도".

## 1. 우선순위 높음

### 1-1. [Codex 재검수](RECHECK_AND_EVENING_REVIEW_RECHECK_20260928.md) P2 3건 수정 확인

| 지적 | 조치 | 파일 |
|---|---|---|
| 혼합 근거에서 업력 구절이 있기만 하면 잘못 뽑은 숫자까지 통과 | ① `AGE_BENEFIT`(우대·가점·감면·금리·추천가능·우선 선정/선발, "최대/융자/지원/보증/대출 … 원", "… 원까지·이내·한도", "- 3천만원" 구간표)을 새로 두었다. 사람·의무 기간이나 우대·지원금 말이 **섞인** 근거는 깨끗한 업력 구절이 있어야 통과한다. ② 섞인 근거에서는 모델이 뽑은 연수가 **깨끗한 구절에 N년(또는 N×12개월)으로** 나와야 한다(`age_quote_problem(quote, values)`). 섞이지 않은 근거에는 연수 대조를 하지 않는다(개월 환산 등 회귀 방지). 자격 문장 속 금액("매출액 80백만 원 미만")은 우대로 보지 않는다 | `collect/extract_conditions.py` |
| varies 공고의 업력이 이미 True면 통과로 남음 | `pre_partial`을 True 건너뛰기보다 먼저 처리한다 | `search/app.py` `eligibility` |
| 옛 재추출 파일이 갱신된 DB 업력을 덮음 | **DB 우선.** 파일 값은 DB에 업력이 없고, DB `input_sha256`이 파일 `document_sha256`과 같을 때만 쓴다(DB를 못 읽었으면 파일만). DB 값에도 지금 검사를 적용해 걸린 행은 숨긴다(`hidden`) | `search/age_evidence.py` |

- 확인:
  - Codex 반례 4개가 모두 걸린다: 거주 2년을 하한으로 읽음, 금리 우대, 구간표, 우선선정.
  - 기존 DB 업력 225건 중 새 검사에 걸리는 것 **4건**(117214 추천가능 우대, 117634 융자 최대 5천만원, 117751 금리 감면 7년, 123754 우선선정). 서비스는 숨기고, **공용 DB 값은 아직 그대로다**(정리는 DB 쓰기라 사용자 결정).
  - 서비스 업력 근거 225 → **221**.
  - 8000 재시작: `kstartup:176208` 예비창업자는 유형·업력 모두 확인 필요, 반려동물 공고는 그대로 통과.
- 테스트: `test_extract_conditions_age`(반례), `test_age_evidence`(varies·K-Startup, DB 우선·해시·숨김). 전체 614개 통과.
- 보고 싶은 것: `AGE_BENEFIT`의 과잉·과소(특히 "지원"이 들어간 자격 문장), 섞인 근거에만 연수 대조를 한 선택.

### 1-2. 판정 테이블 설계 (`db/mysql_migration_006_notice_judgments.sql`, `docs/guides/JUDGMENT_TABLES.md`)

- 한 공고 한 행(PK `notice_id`). `notices.notice_id` 외래 키에 `ON DELETE CASCADE`, utf8mb4_bin. `notice_conditions`와 같은 형식이다.
- `notice_applicant_types`(21칸):
  - 서비스 결론 `pre_founder_verdict`(blocked·allowed·implied_no·NULL)
  - `registered_only_phrase`, `varies`
  - 유형별 status·strength·evidence, `reason`
  - 해시·버전·토큰
- `notice_industries`(21칸):
  - `status`(6종), `allowed_sections`(KSIC 대분류 JSON), `usable_for_rank`
  - `allowed`·`excluded` JSON, `list_complete`·`truncated`·`scope_unresolved`
  - `quote`·`quote_role`, `excerpt_chars`·`verify_profile`·`source_run`, 해시·버전
- 보고 싶은 것:
  - 칸 설계가 팀원이 오해 없이 쓰기에 충분한지. 특히 "빼기에 써도 되는 값"(`pre_founder_verdict='blocked'`)과 참고용 값의 구분이 문서·COMMENT에 분명한지.
  - `allowed_sections`·`usable_for_rank`·`pre_founder_verdict`는 **올릴 때의 코드 규칙으로 계산한 값**이다. 규칙이 바뀌면 13단계가 다시 올린다. 이 설계의 위험(예: 규칙 버전을 칸으로 남기지 않은 것).
  - 외래 키 때문에 `notices`에 없는 공고는 올리지 않는다(세기만 한다). 공고가 지워지면 판정도 지워진다.

### 1-3. 13단계 판정 올리기 (`collect/upload_judgments.py`, `collect/daily_pipeline.py`)

- 파일 → 행 변환:
  - `type_rows`: 서비스와 같은 `search/applicant_types.load`·`pre_founder`로 결론을 계산한다.
  - `industry_rows`: `industry_groups.allowed_sections`·`industry_rank.usable_sections`로 계산한다.
- 바뀐 것만: DB 현재 값을 모두 읽어 칸마다 비교(`normalize`: JSON 파싱, 불리언 0/1)하고, 다른 행만 `INSERT … ON DUPLICATE KEY UPDATE`(200행씩 커밋). DB에서 행을 지우지 않는다.
- 업종 원본 기본값: `data/industries/results.jsonl`(12단계 누적), 없으면 final6.
- 배치: 11·12단계 뒤에 13단계를 둔다. `--skip-judgments`로 끄고, `--skip-upload`도 따른다. 결과는 로그 `judgments_upload`, 실패는 `stage_warnings`와 종료 코드 4.
- 실제 확인: 첫 업로드 직후 `--plan`이 "같음 2,476 · 올릴 것 0"(실제 MySQL 값 형식에서도 비교가 맞다).
- 보고 싶은 것:
  - 비교 정규화에서 놓치는 형식(NULL과 빈 배열, JSON 키 순서, 정수/문자열).
  - 200행 단위 커밋 중간 실패 시 상태.
  - 파일에서 빠진 공고(예: 누적 파일 손상)의 DB 행이 남는 것.
  - 매일 전체 표를 읽어 비교하는 비용.
- 테스트: `tests/test_upload_judgments.py`(5, 가짜 DB), `tests/test_applicant_type_daily.py` `PipelineStatusTests`.

### 1-4. 검색 서비스가 판정을 DB에서 읽기 (`search/applicant_types.py`·`search/industry_rank.py` `load_db`·`load_auto`, `search/app.py` `boot`)

- 신청자 유형: `APPLICANT_TYPES_SOURCE`, 기본 `auto`. DB를 먼저 읽고, 표가 비었거나 읽기에 실패하면 파일을 쓰며 `note`에 이유를 남긴다. `db`·`file` 강제도 된다.
  - DB 행을 파일의 `llm` 모양으로 바꿔 같은 `_info()`를 쓴다. 등록 사업자 규칙은 DB 값에 지금 코드를 다시 적용한다.
- 업종: `INDUSTRY_SOURCE`, **기본 `file`**(final5). "Codex 재검수 뒤 final6·DB로 바꾼다"는 사용자 결정이다.
- `boot`: 연결 한 번으로 두 판정을 읽는다. 연결 실패는 `boot_errors.judgments_db`에 남기고 파일로 간다.
- 실제 확인:
  - DB와 파일 비교: 신청자 유형 2,476건 정보 동일, 서비스 결론 차이 0. 업종 순위 공고 217 동일.
  - 8000 재시작 로그 "신청자 유형 2476건 (db:notice_applicant_types)". 예비창업자 매칭 결과는 전과 같다(blocked 177·restored 9·뒤로 10).
- 보고 싶은 것:
  - DB와 파일이 **어긋날 때**(배치가 파일은 갱신했지만 13단계가 실패) 어느 쪽을 믿는지. 지금은 DB가 우선이다.
  - 서버는 시작할 때 한 번 읽는다. 배치 뒤 재시작 전까지 옛 값이다.
  - 업종 기본을 file로 둔 채 13단계가 DB에는 final6 기반 값을 올리는 비대칭.
- 테스트: `tests/test_judgments_source.py`(5), `tests/test_match_deh.py` 시작 테스트 대역.

### 1-5. 12단계 업종 매일 추출 (`collect/industry_daily.py`)

- 11단계와 같은 구조: 새·바뀐 공고만, 날짜당 300건(부르기 전 예약), 같은 문서 3회 실패 시 중단, `run.lock`.
- 누적 `data/industries/`, 시작은 final6 복사. 추출은 v3·rough·luna@medium이고 공고는 공용 DB에서 SELECT한다.
- 바뀐 공고 판정: `industry_llm_sample.only_new(items, out_dir, reports_dir)`. 18,000자로 다시 읽은 행은 `source_run` 폴더(reports/)의 `max_chars`로 문서를 다시 만들어 비교한다. 매일 행의 `source_run`은 `industry_daily_YYYYMMDD`이다.
- 검사 `verify_for(..., excerpt_cap=6000)` — 처음엔 None을 넘겨 잘림 판정이 꺼져 있던 것을 고쳤다.
- 실제 확인: `--plan` 부를 것 0, 단독 실행 1회로 호출 0·$0에 누적 파일을 만들었다. 13단계가 이 파일을 읽어 같음 2,476.
- 보고 싶은 것:
  - `only_new` 이후 한 번 더 해시로 거르는 중복 조건.
  - 새로 잘린 공고(6,000자)를 매일 다시 읽지 않는 정책.
  - 체크포인트 반영 조건(해시·프롬프트).
- 테스트: `tests/test_industry_daily.py`(5).

### 1-6. C-3 업력 반영 (`experiments/sql_semantic/age_rerun.py` `apply_plan`·`apply_to_db`)

- 원답에 지금의 `verify_age`를 적용해 값이 남고(하한 0년만 있는 값 제외), 공용 DB `input_sha256`이 재추출 문서 해시와 같은 행만 반영한다.
- 바꾸는 칸: `age_years_min`·`age_years_max`·`age_source_quote`·`age_rejected`(NULL), `uncertain`(옛 "업력 추출 버림" 메모를 빼고 "업력 출처: luna 재추출(폴더)"를 붙임).
- **`extractor_version`은 4o-mini 그대로 둔다.** 매일 10단계 `already_done`이 버전으로 걸러 다시 부르지 않게 하려는 것이다. UPDATE는 `WHERE notice_id AND input_sha256`으로 한다.
- 실제 결과:
  - 78행을 반영했다. 다시 `--plan`하면 반영 0·같음 78.
  - `notice_conditions` 업력 있음 147 → 225, 버림 233 → 155.
  - 반려동물 공고는 최대 10년이고, `already_done`에 남아 있다.
- 보고 싶은 것:
  - 한 행에 모델 출처가 섞인다. 업력은 luna, 나머지 칸은 4o-mini이고 구분은 `uncertain` 메모뿐이다.
  - 공고문이 바뀌면 10단계가 4o-mini로 다시 뽑아 luna 값이 사라지는 것(의도: 새 문서면 새로 뽑는다).
  - 백업 파일로 되돌리는 절차가 충분한지.
- 테스트: `tests/test_extract_conditions_age.py` `AgeApplyPlanTests`.

## 2. 우선순위 보통

- `search/age_evidence.py`: C-3 뒤로는 DB가 우선이라 재추출 파일은 거의 건너뛴다(75건 건너뜀). 파일 읽기를 아예 그만둘지.
- 업종 서비스 전환: `INDUSTRY_SOURCE`를 `auto`로 바꿔 DB(final6 기반)를 읽게 해도 되는지. final6·`--merge-append`·`only_new`의 정확성은 앞선 검수에서 확인됐고, 합침 원 실행 이름 보존은 저녁 수정에 들어갔다.
- 흐름 화면(`web/flow.html`) 데이터 지도 표의 "DB에서 읽음" 문구, `web/collection_status.html` 단계 이름(12·13단계).

## 3. 검증 방법

- 프로젝트 `.venv`: `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` → Claude 기록 **614개 통과(건너뜀 13)**.
- Codex 환경에서 FastAPI 없이 돌 만한 테스트:
  - `tests.test_upload_judgments`
  - `tests.test_industry_daily`
  - `tests.test_judgments_source`
  - `tests.test_extract_conditions_age`
  - `tests.test_applicant_type_daily`
  - `tests.test_industry_llm_sample`
- 공용 DB를 SELECT로 볼 만한 것:
  - 두 새 표의 행 수와 결론 분포.
  - `SHOW CREATE TABLE`.
  - `notice_conditions`에서 "업력 출처:" 메모가 있는 78행과 `extractor_version`.
- 실제 유료 API는 부를 필요가 없다.

## 4. 참고 문서

- 작업 이력: [WORKLOG](../../WORKLOG.md) 2026-09-28 맨 위 7개 항목(C-3부터 공고 판정 테이블 생성까지).
- 이전 검수: [저녁 요청](RECHECK_AND_EVENING_REVIEW_REQUEST_20260928.md) · [결과](RECHECK_AND_EVENING_REVIEW_20260928.md) · [응답](RECHECK_AND_EVENING_REVIEW_RESPONSE_20260928.md).
