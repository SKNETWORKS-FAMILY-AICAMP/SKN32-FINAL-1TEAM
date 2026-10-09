# collect/ — 매일 배치

## 맡는 것
- `daily_pipeline.py`: 진입점. 14단계를 순서대로 부르고 `data/collect_log.jsonl`에 한 줄, 종료 코드 0·1·2·3·4를 낸다. `data/collection.lock`으로 중복 실행을 막는다(`job_lock`).
- 수집: `daily_job.py`(K-Startup, 100건씩, 3회 재시도, 검증 뒤 `data/notices.json` 원자적 교체), `fetch.py`, `fetch_bizinfo.py`(한 번에 전량).
- 정규화: `normalize.py` — 두 출처 → `schema_version=1` 공통 형식, 날짜·주소·URL 정리, `issues`에 경고.
- 첨부: `attachment_pipeline.py`(기업마당 공고문 첨부만 받기 → 본문 추출, 끊겨도 이어서), `doctext.py`·`hwp5.py`(PDF·HWP·HWPX·DOCX), `attachment_store.py`(`attachment_texts`).
- 공용 DB로 올리기: `upload_vectors.py`(8단계), `upload_attachments.py`(9단계), `upload_judgments.py`(13단계).
- LLM 추출: `extract_conditions.py`(10단계, `gpt-4o-mini`), `applicant_type_daily.py`(11단계), `industry_daily.py`(12단계), `extract_bonus.py`(14단계) — 11·12·14단계는 `gpt-6-luna`·medium(2026-10-07 결정 0013, 전에는 `gpt-5.6-luna`). 11·12단계 결과는 행마다 `engine`을 적고, 엔진이 다르면 공고문이 같아도 다시 뽑는다(엔진 없는 옛 행 = `gpt-5.6-luna@medium`). 14단계는 모델이 `EXTRACTOR_VERSION`에 들어 있어 모델을 바꾸면 버전이 달라진 행을 다시 뽑는다.
- `backup_db.py`: 팀 DB에서 우리 테이블만 파이썬으로 덤프(기본: 공고 4개 + AI 판정 4개, `--include-files`면 첨부 원본까지). 읽기 전용 한 시점 스냅샷으로 읽고, 다른 팀 테이블(회원·토큰 등)은 넣지 않는다. 출력은 `data/backup_<시각>.sql`(Git 제외).

## 맡지 않는 것
- 공고 검색·순위·자격 판정(`search/`). 이 폴더는 판정을 **만들어 저장**할 뿐 쓰지 않는다.
- DB 접속·저장 SQL·임베딩 입력 정의(`shared/`). 여기서 SQL 연결 설정을 따로 만들지 않는다.
- 테이블 구조(`db/`). 새 칸이 필요하면 변경 SQL을 먼저 만든다.
- 서버 예약(저장소 루트 `deploy/run_batch.sh`, PC `run_daily.bat`·`schedule-task.ps1`).
- 신청자 유형·업종 LLM 프롬프트와 응답 해석 본체는 `experiments/sql_semantic`(`applicant_type_llm`·`industry_llm_sample`·`industry_groups`)에 있고, 여기서 import한다.

## 항상 지켜야 할 것
- 출처별로 따로 검증한다. 오늘 건수가 직전의 절반 미만이면 그 출처의 오늘 결과를 버리고 직전 데이터를 쓴다(`--force`만 예외). 두 출처를 합쳐 세지 않는다.
- 3단계가 실패하면 DB를 건드리지 않는다. 4단계는 한 트랜잭션이다(실패하면 전부 되돌림). 5단계 이후는 `stored`일 때만 돌고, 실패해도 앞 단계를 되돌리지 않는다.
- K-Startup 모집 종료 처리는 그날 새로 받았고 목록이 완전할 때만(`daily_job.is_complete`·`kstartup_listed`) 한다. 행은 지우지 않는다.
- K-Startup 첨부는 받지 않는다(첨부 대상 SQL이 `n.source = 'bizinfo'`로 묶여 있다 — 풀지 않는다).
- 증분: 입력 해시가 같으면 건너뛴다(첨부는 원본 수정 시각, 임베딩은 입력 SHA-256, LLM은 발췌·문서 해시와 추출기 버전·내용 지문).
- LLM 단계: 하루 상한을 **부르기 전에** 센다(신청자 유형·업종·가점 300건, 가점은 한국 날짜 기준 누적). 가점 기록 파일이 깨졌으면 그날은 부르지 않고, 기록은 임시 파일 → 바꿔치기로 쓴다. 같은 문서로 3번 실패하면 그 문서를 멈춘다. 키가 없으면 `{'error': 'no_api_key'}`로 돌려 종료 코드 4가 되게 한다.
- LLM 단계의 실패·경고는 결과 dict의 `error`·`failed`·`warning`으로만 알린다. 배치 `status`를 `partial`로 바꾸지 않는다.
- 공용 DB에 쓰는 단계(8·9·13·14)는 `--skip-upload`를 따른다. 11·12단계는 파일(`data/applicant_types/`·`data/industries/`)에만 쓴다.
- 못 찾은 조건을 "제한 없음"으로 저장하지 않는다. 근거 문장이 원문과 맞지 않는 값은 버린다(`amount_rejected`, 가점 `unverified`).
- 원본·정규화 스냅샷은 출처별 14개만 남긴다(`prune`). 첨부 원본은 내용 해시 이름으로 한 벌만 둔다.

## 이 폴더의 방식
- 중요한 길목마다 파일을 남긴다(`data/raw/`·`data/normalized/`·`attachment_results.jsonl`). 어제와 견주고, 어디서 틀렸는지 가리고, 끊기면 이어 하기 위해서다. 임시 파일에 쓴 뒤 바꿔치기로 저장한다.
- 단계 함수는 `say` 콜백으로 진행을 알리고, 결과를 dict로 돌려준다. 예외는 `daily_pipeline`이 잡아 `{'error': '<예외이름>: <앞 200자>'}`로 바꾼다.
- 단독 실행 명령은 `--plan`(대상·예상 비용만)을 먼저 둔다. 유료·DB 쓰기 옵션(`extract_bonus --all` 등)은 명시적으로만 켠다.
- 새 단계를 더하면: `_run` 인자·`main` 옵션(`--skip-X`, `--X-limit`)·`stage_warnings_of` 입력·`write_log` 키·README 옵션 목록을 함께 고친다.

## 시험
- 관련 시험: `tests/test_pipeline.py`(단계 순서·종료 코드·stage_warnings), `test_normalize.py`, `test_doctext.py`, `test_attachment_store.py`, `test_active_attachments.py`, `test_store_mysql.py`, `test_extract_conditions_age.py`, `test_applicant_type_daily.py`, `test_industry_daily.py`, `test_upload_judgments.py`, `test_extract_bonus.py`.
- 반드시 덮을 경우: 한 출처만 실패(다른 출처는 갱신·`partial`·종료 코드 2), 건수 급감(교체 거부), LLM 단계 예외·키 없음(`status` 그대로·종료 코드 4), 하루 상한(이미 쓴 만큼 줄어듦), 같은 해시 재실행(호출 0), K-Startup 목록 불완전(모집 종료 처리 건너뜀).
- 실제 API·OpenAI·공용 DB를 부르는 시험을 만들지 않는다. 가짜 응답·가짜 연결로 한다. MySQL 통합 시험은 `MYSQL_INTEGRATION_TEST=1`일 때만.
