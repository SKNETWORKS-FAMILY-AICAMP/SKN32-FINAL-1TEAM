# Codex 검수 요청 — 8건 재검수 + 저녁 추가 변경 (2026-09-28)

작성: Claude · 요청: 사용자(이근준) · 수행: Codex
결과는 이 폴더에 `RECHECK_AND_EVENING_REVIEW_20260928.md`로 남겨 달라. **코드·DB는 고치지 말고**, Git 스테이징·커밋도 하지 않는다.

이 문서 하나로 범위가 끝나도록 정리했다. 자세한 이유와 수치는 각 절의 링크(WORKLOG 항목·결과 폴더·코드 맨 위 설명)에 있다.

## 0. 먼저 알아 둘 것 — 데이터가 어디에 있나

- **공용 DB**(EC2 MySQL `s_brain`)는 조회만 했다. 오늘 Claude가 공용 DB에 쓴 것은 없다.
- 새로 만든 판정 결과(신청자 유형·업종·업력 재추출)는 **이 PC의 파일**(`data/`, `reports/`)에 있다.
- 매일 배치(`run_daily.bat` → `collect/daily_pipeline.py`)는 이 폴더의 작업 파일을 그대로 실행한다. 그래서 **아래 1-1은 내일(9/29) 09:00 배치부터 공용 DB 쓰기에 적용된다.**
- 흐름 그림: `http://127.0.0.1:8010/flow`의 "⓪ 데이터 지도", "③-1 매칭에 쓰는 입력" (`web/flow.html`).

## 1. 우선순위 높음

### 1-1. 매일 배치 10단계 — 업력 검사·프롬프트 변경 (`collect/extract_conditions.py`) ★ 내일 배치에 적용

- 배경: 기업마당 "반려동물 창업 아이디어 경진대회" 공고에서 업력이 "확인 필요"로 나왔다. 10단계가 "사업자등록 후 1년 이상 10년 미만"을 찾았는데 `verify_age`가 "근거에 업력 표현이 없음"으로 버렸다. 같은 이유로 버려진 공고가 204건이었다.
- 변경:
  - `AGE_EVIDENCE` 넓힘: 사업개시일, 사업자등록일·후·등록증 N년, 창업한 지, 설립된 지·연도·등기, 영업신고·개시, 가동 중·상태, 운영·영위 중, 영위한·하는, 기업경영, "N년 이내 창업기업·창업자"(`(?<!예비)창업(기업|자|한|팀)`) 등.
  - `AGE_DECOY_STRONG` 신설: 입사, 근무, "N년 … 근로자", 경력, 거주, 주민등록, 전입, 공적·활동·수공 기간, 운영하여야, 유지하여야, 지정기간, 수혜. 이 말이 있으면 업력 표현이 함께 있어도 버린다.
  - `SYSTEM` 규칙 9 추가:
    - 근무·경력·거주·의무 기간은 업력이 아니다.
    - 인정할 업력 표현 예시를 넣었다.
    - 예외·제외 조항 속 연수(예: "부채비율 500% 이상 제외, 단 7년 미만 창업기업은 예외")는 쓰지 않는다.
    - "예비창업자 또는 창업 N년 미만"이면 기업 쪽 조건으로 기록하고 `pre_startup_allowed=true`.
  - `EXTRACTOR_VERSION`은 **올리지 않았다.** 올리면 `already_done`이 1,864건 전부를 다시 부른다. 대신 같은 버전 안에 옛 규칙 결과와 새 규칙 결과가 섞인다.
- 확인한 것(저장된 근거 문장으로 새 검사만 돌림, 호출 없음):
  - 버려진 204건 중 92건이 통과로 바뀐다.
  - **기존 통과 147건 중 새로 떨어지는 것은 0건**이다. 처음엔 1건("상시 근로자 30인 미만")이 걸려 "근로자" 조건을 좁혔다.
- 보고 싶은 것:
  - **과잉 통과**: `창업(기업|자)`·`가동 상태`·`운영 중`이 업력이 아닌 문장을 통과시키는지. 예: 버려진 목록의 "창업기업 6개월 미만 - 3천만원 … 저신용기업 1년 이상"(대출 한도표)이 새 검사를 통과한다. 값 판단은 LLM에 맡기는 구조라 검사가 넓어진 만큼 LLM 오독이 그대로 저장될 수 있다.
  - **과잉 버림**: DECOY_STRONG이 실제 업력 문장을 버리는 경우.
  - 버전을 올리지 않은 판단과, 섞인 결과를 나중에 구별할 방법.
  - 프롬프트 규칙 9의 예외 조항 문구가 4o-mini에 역효과(업력을 아예 안 뽑음)를 낼 여지.
- 테스트: `tests/test_extract_conditions_age.py`(5). 기록: WORKLOG "업력 버림 204건 — 검사 보완(C-1)·luna 재추출(C-2)".

### 1-2. 자격 확인 업력 줄 — A(예비창업자)·B(공고문 추출 근거) (`search/app.py` `eligibility()`, `search/age_evidence.py` 신규)

- **A**: 신청자가 예비창업자이고 '지원대상 유형'이 본문 근거로 통과(`applicant_types.type_check` True)면, 업력 줄이 **모름(None)**일 때도 통과로 둔다. 요구 칸은 "예비창업자 신청 가능(공고 본문) — 업력 조건은 이미 창업한 기업에 붙는 조건"이다. 예전에는 미달(False)일 때만 덮었다.
- **B**: 그 밖에 업력이 모름이면 공고문 추출 업력을 요구·설명 칸에 **근거로만** 보여 준다. 판정은 None 그대로다.
  - 표시 예: "공고문 추출(추정): 업력 최대 10년", "내 업력 12년 8개월은 이 범위 밖입니다(참고)", 근거 문장.
  - 근거 출처: 공용 DB `notice_conditions` 업력 147건(boot 때 SELECT) + `reports/age_rerun_luna_*/results.jsonl`의 '살아남' 77건(파일이 덮음) = 224건.
  - 읽기에 실패해도 서버는 열고 `boot_errors.age_evidence`에 남긴다.
- 보고 싶은 것:
  - A가 넓지 않은지. 본문 '가능' 판정은 Codex 블라인드 9/9였다. 세부사업별로 예비 트랙과 기업 트랙이 갈리는 공고(varies)에서도 업력을 통과시키게 되는지.
  - B의 "참고 비교"가 판정처럼 읽히지 않는지(화면 `web/app.html` 자격 확인 표).
  - `age_evidence.rerun_path()`: 처음엔 `age_rerun_luna_*` 중 이름순 마지막을 골라, 표본 폴더(`age_rerun_luna_missing_…`)가 잡히는 버그가 있었다. 이 요청서를 쓰다 발견해 **`age_rerun_luna_2*`(날짜로 시작)만 고르게 고쳤고** 테스트를 추가했다. 서버는 그 전 시작이라 204건 폴더를 읽고 있었다. 더 단단한 선택 방법(meta의 `missing` 값 등)이 필요한지 봐 달라.
- 실제 서비스 확인(반려동물 공고 `bizinfo:PBLN_000000000126505`):
  - 예비창업자: 업력 통과.
  - 법인(2014년 설립): 확인 필요, 범위 밖(참고).
  - 개인(2023년 설립): 확인 필요, 범위 안(참고).
- 테스트: `tests/test_age_evidence.py`(8), `tests/test_match_deh.py` 서버 시작 테스트에 대역 추가.

### 1-3. 검수 지적 8건 재검수

- [Claude 응답](UNREVIEWED_CHANGES_REVIEW_RESPONSE_20260928.md)의 "재검수 요청" 절 그대로다. 요약:
  - P1: 서버 시작 장애 격리, 보조 벡터 조회 실패 시 `fallback_mode` None.
  - P2:
    - 11단계 실패를 status 대신 `stage_warnings`와 종료 코드 4로 알린다.
    - 날짜당 상한을 부르기 전에 예약한다.
    - 등록 사업자 규칙 66건으로 조정.
    - 공개 경로 20건 상한.
  - P3: `.gitignore`, "순위 점수" 표기.

## 2. 우선순위 보통

### 2-1. 업종 추출 입력을 실험 DB → 공용 DB(읽기만)로 (`experiments/sql_semantic/industry_llm_sample.py`)

- 사용자 결정: 실험 DB(9/21 사본 1,852건) 대신 공용 DB를 읽고, 결과는 파일에 둔다.
- 변경:
  - `--source shared`를 새 실행의 기본으로 했다. 재개·재검사는 처음 실행의 `meta.source`를 따르고, 없으면 lab이다.
  - `load_items_shared`: 정규식 판정을 `conditions.industry_condition()`으로 그 자리에서 계산한다.
  - `--only-new BASE`: 합친 결과는 공고마다 `source_run`의 `max_chars`로 문서를 다시 만들어 비교한다. 처음엔 이 처리가 없어 197건이 "바뀐 것"으로 잘못 잡혔다.
  - `--merge-append`: 기준에 없는 공고를 붙이고, `population`·`notice_ids`·`appended`·`source`를 갱신한다.
- 확인:
  - 같은 공고의 문서는 실험 DB와 공용 DB에서 글자까지 같다(40건 대조). 프롬프트·스키마 해시는 final5와 같다.
  - 부를 공고 626건 = 새 공고 624(기업마당 440·K-Startup 184) + 제목·본문 변경 2.
- **실행 완료**: `reports/industry_llm_new626_luna_20260928/`(626건 · 실패 0 · 약 $0.71) → `--merge-append`로 `reports/industry_llm_full_luna_20260928_final6/`(2,476건, 순위에 쓸 수 있는 공고 217).
  **사용자 결정(2026-09-28): 서비스가 읽는 파일(`search/industry_rank.py` 기본 final5)은 이 검수 뒤에 final6으로 바꾼다.** 잘린 새 공고 54건을 길게 다시 읽는 것은 업종 순위를 다시 켤 때 함께 한다.
- 보고 싶은 것:
  - `only_new`의 `source_run` → `max_chars` 해석(합치기가 여러 번 쌓인 결과).
  - `--merge-append` 뒤 meta가 서비스(`search/industry_rank.load`)와 화면(`industry_results.py`)에서 문제없는지.
  - 6,000자에서 잘린 새 공고 처리(이전에는 따로 길게 다시 읽었다).
- 테스트: `tests/test_industry_llm_sample.py`에 3개 추가(116).

### 2-2. 업력 재추출 스크립트 (`experiments/sql_semantic/age_rerun.py` 신규, DB 쓰기 없음)

- 10단계와 같은 문서·프롬프트·스키마로 모델만 luna@medium으로 바꿨다.
- 결과 1 — `reports/age_rerun_luna_20260928T054509Z/`: 버림 204건, $0.33. 살아남 77 · 업력 없음 85 · 다시 버림 42.
  - Claude가 77건을 읽어 보니 약 11건이 애매했다(AI 참고).
    - 세부사업 혼합: `117632`, `119636`, `125856`.
    - "또는" 조건: 수출초보 4건.
    - 우대 조건: `117751`, `126019`.
    - 신청 자격이 아닌 허용 조건: `117214`, `125882`.
- 결과 2 — `reports/age_rerun_luna_missing_20260928T061903Z/`: 4o-mini가 못 찾은 1,460건 중 표본 100건, $0.14. 97건이 여전히 업력 없음이라 전량 재추출은 하지 않기로 했다.
- 보고 싶은 것: 재개 검사(`run_spec.json`), 비교 표(`summary.md`), 공용 DB 반영(C-3) 때 `already_done`이 버전으로 걸러 4o-mini가 luna 결과를 덮는 문제(아직 반영 안 함).

### 2-3. 화면 (`web/flow.html`, `experiments/sql_semantic/viewer.py` `/api/flow`)

- "⓪ 데이터 지도"(SVG + 표 + 어긋나는 곳 4가지), "③-1 매칭에 쓰는 입력"을 추가했다. ② A는 "일부 — K-Startup만"으로 바꿨고 A2(10단계)를 추가했다.
- `/api/flow`는 신청자 유형 파일의 줄 수와 meta 시각을 돌려준다.
- 보고 싶은 것: 문구가 코드 사실과 맞는지(특히 ③-1 표와 `MatchRequest`·`build_query`·`applicant.py`).

## 3. 검증 방법

- 프로젝트 `.venv`: `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` → Claude 기록 **587개 통과(건너뜀 13)**.
- 지난 검수 때 Codex 환경에서는 `.venv`가 없는 Python 3.12 경로를 가리켰고 시스템 Python에 FastAPI가 없었다. FastAPI가 필요 없는 테스트는 다음과 같다.
  - `tests.test_extract_conditions_age`
  - `tests.test_industry_llm_sample`
  - `tests.test_applicant_type_daily`
  - `search.age_evidence`의 `LoadTests`
- 실제 DB·유료 API를 새로 부를 필요는 없다. 필요한 결과는 위 `reports/` 폴더에 있다.

## 4. 참고 문서

- 작업 이력: [WORKLOG](../../WORKLOG.md) 2026-09-28 위쪽 7개 항목(업종 공용 DB 전환부터 오후 변경 검수 지적 8건 수정까지).
- 이전 검수: [요청](UNREVIEWED_CHANGES_REVIEW_REQUEST_20260928.md) · [결과](UNREVIEWED_CHANGES_REVIEW_20260928.md) · [응답](UNREVIEWED_CHANGES_REVIEW_RESPONSE_20260928.md).
- 신청자 유형 근거: [판정 결과](../applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md) · [애매 8건 원문 대조](../applicant_type/APPLICANT_TYPE_AMBIGUOUS_CHECK_20260928.md).
