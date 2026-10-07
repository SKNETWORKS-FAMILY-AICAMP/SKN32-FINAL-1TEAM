# 지켜야 할 규칙

어기면 배치·서버가 깨지거나, 팀 데이터가 틀어지거나, 사용자와의 약속이 깨지는 것만 적는다.

## 1. Git과 남의 변경

- **git commit·push는 사용자만 한다.** AI는 실행하지 않는다. 사용자가 따로 요청하지 않으면 `git add`(스테이징)도 하지 않는다. 상태·차이·이력 조회는 해도 된다.
- 이미 있는 수정·스테이징·미추적 파일을 자기 작업으로 보지 않는다. 되돌리거나 지우거나 덮어쓰지 않는다. 같은 파일을 고쳐야 하면 쓰기 직전에 다시 읽고 자기 변경만 넣는다.
- 기본 작업 범위는 `data-collection/`이다. 다른 팀원 폴더(`agent-orchestration/`·`web/` 등)는 읽기만 한다. 저장소 루트 `deploy/`의 배치 구성(`batch.Dockerfile`·`batch-requirements.txt`·`run_batch.sh`·compose의 `batch`)은 이 폴더 배치를 돌리는 것이라 함께 다룰 수 있다.
- 작업 브랜치는 `feature/SB-189-data-collection`이다. 팀 규칙상 커밋 메시지·PR 제목에 이슈 키(`SB-189 …`, `[SB-12] …`)를 넣는다(PR 제목은 CI가 검사한다).

## 2. 실행 방식

- 항상 `data-collection/`에서 패키지 모듈로 부른다: `.\.venv\Scripts\python.exe -X utf8 -m <패키지.모듈>`. 파일을 직접 실행하면 `from shared import …`가 깨진다(평가·공유 스크립트 중 파일 경로로 부르는 것은 각 머리말을 따른다).
- 윈도우에서는 `-X utf8`을 붙인다. 빼면 한글 출력·파일 읽기가 깨진다.
- 사용자에게 알려 줄 명령은 PowerShell 5.1 기준으로 쓴다(`&&` 없음). 파일에 덧붙일 때 `echo >>`는 UTF-16이 되므로 `Add-Content -Encoding ascii`(또는 utf8)를 쓴다.

## 3. 의존성

- `requirements.txt` = 배치 + 공고 서버. `requirements-ml.txt` = 학습 전용(torch는 GPU 판을 따로 설치). 학습 패키지를 `requirements.txt`에 넣지 않는다.
- 배치 서버 이미지(`deploy/batch-requirements.txt`)는 배치 PC와 **같은 버전으로 고정**한다. 배치에 새 패키지를 쓰면 두 파일을 함께 고친다.
- `shared/config.py`는 표준 라이브러리만 쓴다(python-dotenv 등 추가 금지). `--skip-embed`이면 torch·chromadb·sentence-transformers 없이도 배치가 돌아야 한다(이 패키지들은 함수 안에서 import한다).

## 4. 폴더 경계

- `shared/`는 다른 폴더를 import하지 않는다.
- `experiments/sql_semantic`의 `applicant_type_llm`·`industry_llm_sample`·`industry_groups`는 **배치(11·12·13단계)와 공고 서버(신청자 유형·업종 판정 해석)가 import한다.** 이 모듈들을 옮기거나 이름·함수 모양을 바꾸면 배치와 서버를 함께 고친다. `experiments/`를 "실험이라 지워도 되는 폴더"로 다루지 않는다.
- `search/notice_api.py`는 `search/app.py`를 import하지 않는다. 서버는 `python -m search.app`으로 켜져 `app.py`가 `__main__`이므로, import하면 `STATE`가 빈 두 번째 사본이 생긴다. 상태와 DB 연결 함수는 `build_router(STATE, connect)`로 넘긴다.
- 서비스와 평가는 **같은 규칙 함수**를 쓴다. 정형 필터는 `gate.prefilter` + `app.eligible_with_types`, 재정렬은 `rank_rules`, 자격 판정은 `search/eligibility.py` 한 곳, 공고 검색 입력은 `shared/embed.build_input` 한 곳(BM25·평가 코퍼스도 같은 입력). 규칙을 복사해 두 곳에 두지 않는다.
- 공고 서버는 DB에 쓰지 않는다(SELECT만).

## 5. 판정 값 처리

- 판정은 참·거짓·없음 3값이다. 없음을 거짓으로 바꾸는 코드(`not verdict`, `bool(verdict)` 등으로 뭉개기)를 쓰지 않는다. 표시에는 `gate.mark`(O·X·?)를 쓴다.
- 날짜·숫자로 사용자 입력을 바꿀 때 예외를 던지지 않는다(달력에 없는 날짜 포함). 던지면 요청 전체가 500으로 끝난다. 못 읽으면 None으로 돌려준다.
- 이 원칙을 바꾸는 변경에는 시험을 함께 넣는다(`tests/test_gate.py`·`test_notice_api.py`·`test_match_rules.py`가 지금 원칙을 고정한다).

## 6. 매일 배치 단계

- 새 단계는 4단계(저장) 성공 뒤에만 돈다(`stored`). 단계 예외는 잡아서 결과의 `error`로 남기고 다음 단계로 간다. 단계 실패가 앞 단계 결과를 되돌리지 않게 한다.
- 공용 DB에 쓰는 단계는 `--skip-<단계>`와 함께 `--skip-upload`도 따른다.
- LLM 후처리 단계의 실패·경고는 `stage_warnings_of`에 넣어 종료 코드 4로 알린다. 배치 `status`를 `partial`로 바꾸지 않는다(바꾸면 수집 상태가 '실패'가 되어 매칭이 막힌다).
- 종료 코드 0·1·2·3·4의 뜻을 바꾸지 않는다. `run_daily.bat`·`deploy/run_batch.sh`·수집 상태 판정이 이 값을 읽는다.
- 증분 처리: 입력 해시가 같으면 건너뛴다. LLM 단계는 하루 상한을 **부르기 전에** 센다. 같은 문서로 3번 실패하면 그 문서는 멈춘다.

## 7. 버전 값

| 값 | 바꿀 때 해야 할 일 |
|---|---|
| 내용 지문 접두어 `cv2-` (`search/content_version.py`) | 넣는 칸·방식을 바꾸면 접두어를 올린다(`cv3-`). 접두어를 그대로 두고 방식만 바꾸지 않는다 |
| 가점 추출기 버전 `EXTRACTOR_VERSION` (`collect/extract_bonus.py`) | 올리면 기존 `notice_bonus` 행이 모두 무시된다(가산점 null). 재추출 비용·일정을 사용자와 정한 뒤 올린다 |
| 임베딩 설정(모델·리비전·입력 버전·토큰 상한·차원·자료형·정규화) | 하나라도 바뀌면 전량 재임베딩이다. BGE-M3 리비전은 `5617a9f…`로 고정한다 |
| 정규화 `schema_version` | 지금 1만 받는다. 바꾸면 저장 검증·DB가 함께 바뀌어야 한다 |

## 8. DB 변경

- 테이블 변경은 `db/mysql_migration_NNN_<내용>.sql` 새 파일로 쓴다. `CREATE TABLE IF NOT EXISTS`·칸 추가처럼 **기존 테이블·행을 지우거나 바꾸지 않는 형태**로 쓴다. 번호는 이어서 붙인다(지금 008까지).
- 변경 SQL을 자동으로 적용하는 코드는 없다. 공용 DB 적용은 사용자 승인 뒤 손으로 한다. 배치 서버·팀 EC2에 적용됐는지 따로 확인한다.
- 실험 테이블을 공용 DB에 만들지 않는다.

## 9. 공고 서버 응답

- 공개 HTTP 경로의 `/api/match`는 누적 20건을 넘지 않게 `_public()`으로 자른다. 평가 도구만 `match()`를 직접 불러 제한 없이 받는다.
- `Weights` 기본값은 서비스 동작 그 자체다. 기본값(가산점 세기 0, `demote_industry=false` 포함)을 바꾸려면 평가 근거와 사용자 결정이 먼저다.
- 조율 쪽과 맞춘 응답 키·코드(`NOTICE_NOT_FOUND`, 수집 상태 값 등)를 바꾸기 전에 조율 담당에게 알릴 문서를 먼저 고친다. 조율 쪽은 우리가 커밋·push한 시점의 코드를 기준으로 붙는다.

## 10. 검증 관문

- 완료라고 보고하기 전에 `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests`를 돌려 실패 0을 확인한다. 2026-10-07 기준 884개 중 868개 통과·16개 건너뜀(`reports/unit_test_20261007T024611Z/`).
- MySQL 통합 시험은 `MYSQL_INTEGRATION_TEST=1`일 때만 돈다. 건너뛴 시험은 "확인 안 함"으로 보고한다.
- 저장소 CI는 data-collection 시험을 돌리지 않는다. 로컬 실행이 유일한 관문이다.
- 실행한 명령·조건·결과를 기록하고, 실행하지 않은 것은 이유와 함께 적는다. 과거 문서의 수치나 이전 AI의 보고를 이번 실행 결과처럼 쓰지 않는다.

## 11. 결과·평가 기록

- `reports/` 결과는 새 폴더(`<주제>_<UTC 시각>Z`)로 만든다. **기존 결과 폴더를 덮어쓰거나 고치지 않는다**(옛 링크가 남아도 그대로 둔다).
- 검색 비교를 할 때는 질의·공고 데이터 기준, 모델·색인 상태, 기준 날짜, 후보 수와 Top-K, 검색 방식(`dense`·`hybrid`), RRF 가중치, 마감·지역·지원대상 처리, 리랭커 사용 여부를 남긴다. 평가 정답의 버전, 사람/LLM 판정 여부, 미판정 비율을 구분한다. 검색 자체의 결과와 후처리 뒤 최종 노출 결과를 구분한다. 코사인 유사도를 정확도나 확률로 쓰지 않는다.
- 평가 데이터를 학습·시험으로 나눌 때는 **질의 단위**로 나눈다. 사람 판정 143쌍이 49개 질의에 흩어져 있어, 판정 단위로 나누면 같은 질의가 양쪽에 걸친다.
- Codex·LLM 판정은 "AI 참고 정답"으로 표기하고 사람 정답 칸에 넣지 않는다. 판정을 본 뒤 그 판정에 맞춰 프롬프트를 고친 결과를 성능 근거로 쓰지 않는다.

## 12. 작업 기록 (진행 일지)

- 실작업(파일 수정·실험)을 시작하면 `docs/STATUS.md` 진행 중 항목에 담당 AI·목적·수정 예정 파일·다음 단계를 적는다. 긴 작업은 단계마다 갱신하고, 중단되면 실행 중인 명령·완료 범위·남은 일·재개 방법을 남긴다.
- 여러 AI가 동시에 일하면 항목을 따로 둔다. 다른 AI의 항목을 지우거나 완료로 바꾸지 않는다.
- 작업이 끝나면 `docs/WORKLOG.md` 기록 구역 맨 위에 한 건을 더한다(이유·전후 차이·검증 근거, 대화 전문·전체 diff는 넣지 않음). 과거 기록은 지우지 않고, 정정은 새 항목에서 한다.
- 기능 흐름이 바뀌면 `docs/FLOW.md`, 실행 방법·구조가 바뀌면 `README.md`, 범위 대비 진행이 바뀌면 `docs/tracking/status.md`, 규칙·원칙·구조·창구가 바뀌면 `docs/`의 해당 문서를 함께 고친다.
- 사용자가 요청하지 않은 과거 작업을 다시 실행하거나 완료 처리하지 않는다. 예정 작업은 실행 허가가 아니다.

## 13. 문서 위치

- `docs/` 맨 위에는 진행 일지(STATUS·WORKLOG·FLOW·최신 인계서), 지난 결정 기록 PLAN_ALIGNMENT, 문서 지도(`docs/README.md`), 그리고 구조·원칙·보안·규칙·함정·운영·창구 문서 7개만 둔다. 범위 대비 진행·결정·미해결 문제는 `docs/tracking/`에 둔다.
- 검수 요청(`…_REVIEW_REQUEST_YYYYMMDD.md`)·결과(`…_REVIEW_YYYYMMDD.md`)·작업 지시(`…_TASK_YYYYMMDD.md`)는 `docs/reviews/<주제>/` 한 폴더에 둔다. 조율 창구 작업 기록은 `docs/notice_api/0N_<작업>/`에 둔다(코드는 기존 자리).
- 새 인계서는 `docs/NEXT_SESSION_HANDOFF_YYYYMMDD.md`로 맨 위에 두고 이전 것은 `docs/archive/`로 옮긴다. 문서를 옮기거나 만들면 `docs/README.md` 표를 함께 고친다.
- `docs/specs/`(기획서·기능정의서)와 `docs/deliverables/`(제출본)는 고치지 않는다.
- 공용 문서에 API 키·비밀번호·접속 문자열·실제 신청자 개인정보를 적지 않는다.
