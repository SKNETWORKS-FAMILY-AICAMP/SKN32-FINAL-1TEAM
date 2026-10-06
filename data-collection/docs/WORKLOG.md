# 공용 작업 이력

현재 상태는 [STATUS.md](STATUS.md), 공통 절차는 [AGENTS.md](../AGENTS.md)를 참조한다.
새 기록은 아래 **작업 기록** 제목 바로 아래에 최신순으로 추가한다.
같은 날 여러 작업이면 구별되는 제목을 쓰고, 이전 기록을 정정할 때는 대상 항목을 명시한다.

## 기록 양식

```markdown
### YYYY-MM-DD · 담당 AI/작업자 · 작업명

- 요청·목적:
- 작업 전 상태: 기존 수정이나 관련 문제
- 변경 파일: 경로와 변경한 역할
- 전후 차이·선택 이유: 같은 입력에서 무엇이 달라지는지, 왜 이 방법인지
- 검증: 실행 명령·조건·결과·결과 파일. 실행하지 않았다면 이유
- 미검증·남은 문제:
- 다음 단계:
```

날짜는 한국 시간 기준으로 적는다. 수치에는 측정 조건과 근거를 붙인다.
과거 작업을 새로 수행한 것처럼 기록하지 않는다. 비밀정보와 개인정보는 적지 않는다.

## 작업 기록

### 2026-10-06 · Claude · 공고 서버 API — 05 답변서

- 요청·목적: 조율 담당 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`, 10/3·10/4)에 답하는 문서. 사용자 요청 "답변서를 써줘".
- 작업 전 상태: 01~04 완료·push 됨. 요청서는 04 계약 시험에 쓴 `b8e7f50` 이후 바뀌지 않음(원격 diff 없음, 10/6 확인).
- 변경 파일: 새 `docs/notice_api/05_reply/README.md`. 진행표 `docs/notice_api/README.md` 05 줄, STATUS, `docs/tracking/status.md`, `docs/contracts.md`(생년월일 답·업력 상한 null 두 뜻·503 본문).
- 전후 차이·선택 이유: 조율 쪽이 답변서를 그대로 믿고 코드·화면 문구를 고치므로, 정하지 않은 것(배포 위치·인증·재시작 방식·동시 호출·가산점 정리·함께 시험)은 "미정"으로 쓰고 날짜를 약속하지 않았다(사용자 선택). 개인정보 최소화로 생년월일은 "아직 보내지 말아 달라". 요청서가 다르게 읽는 값(업력 상한 null = 제한 없음, 공개 시험 서버 있음, `support_amount_text`)을 바로잡았다. 사실 확인 중 새로 알게 된 것: 지금 PC 시험 서버는 10/2 뒤 공고가 하이브리드 추천에 아예 안 나온다(벡터 없는 공고는 RRF 결과에서 빠짐, `search/app.py` 하이브리드 경로), 수집 상태의 "최근 배치 실패·출처 실패" 판정은 배치 일지가 있는 기계에서만 작동한다.
- 검증: 답변서의 사실 주장을 코드와 대조(`search/collection_status.py`·`notice_api.py`·`content_version.py`·`app.py`·`hybrid.py`·`bonus.py`·`applicant.py`, 02·04 기록 수치). 적합도 최솟값은 `RRF_K=60`·`DEPTH=50`으로 계산(하이브리드 약 0.277, 단독 경로 약 0.555). 계획 단계에서 독립 검토 2회(결정 누락 점검·실행 가능성 점검)를 거쳐 지적을 반영. 코드 변경은 없고, 확인용으로 `python -X utf8 -m unittest discover -s tests` → 758개 통과·16개 건너뜀(실패 0).
- 미검증·남은 문제: 동시 호출 안전성, 재시작 중 응답 불가(약 20~25초) 처리, 내용 버전 하루 비교(10/7).
- 다음 단계: 사용자가 답변서를 보낸다. 10/7 배치 뒤 내용 지문 비교 → 바뀌면 조율 담당에게 먼저 알린다.

### 2026-10-06 · Claude · 공고 서버 API — 재검수 지적 보류·K-Startup 첨부 확인·04 계약 시험

- 요청·목적: Codex 재검수 확인 → 사용자가 개선 보류 후 다음 작업 진행을 결정. K-Startup 가산점이 없는 이유 확인과 첨부 확보 가능성 조사. 04 계약 시험.
- 작업 전 상태: 01~03 v4(미커밋), 8000은 v4로 켜짐. Codex 재검수 결과 "추가 수정 후 재검수 필요".
- 변경 파일: 새 `experiments/notice_api_contract.py`, 새 `docs/notice_api/04_contract_test/README.md`, 진행표·결정(`docs/notice_api/README.md`)·STATUS. 결과 `reports/notice_api_contract_20261006T035438Z/`. 판정표 페이지(artifact, 비공개) 게시.
- 전후 차이·선택 이유: 서비스 코드 변경 없음. K-Startup은 robots.txt `Disallow: /afile*/`(첨부 목록·다운로드 경로) 때문에 자동 수집하지 않기로 했다(파이썬 robotparser는 별표를 해석하지 못해 '허용'으로 잘못 답함 — 규칙을 직접 읽어 판단). 공공데이터포털 `kisedKstartupService01` 4개 기능을 1건씩 호출해 공고 첨부 칸이 없음, `prfn_matr`(우대 사항) 열린 221건 모두 빈 값, 외부 안내 주소 186건은 구글 설문·각 기관 사이트로 파일 0건임을 확인. 04는 조율 쪽 코드를 작업 트리 밖 임시 폴더에 `git archive`로 풀어 우리 `.venv`로 불렀다(pydantic 같은 판).
- 검증: 계약 시험 16개 통과 — T-C2 8회(카드 10·rank·시·도 바꾸기), G-01 40회(업력 사사오입 일치), 공고 없음 `ResourceNotFound`, 경로 없음 `ProviderError(404)`, 설립일 없는 사업자 판정 생략, 모든 공고 G-01 2,765건 형식 오류 0(65초). 첫 실행에서 내 시험 코드가 한글 경로(`/없는경로`)를 써서 urllib 인코딩 오류가 났고 영문 경로로 고쳐 다시 돌렸다. OpenAI·DB 쓰기 없음.
- 미검증·남은 문제: 조율 쪽 흐름 전체(워커·저장소·웹)는 범위 밖. 조율 기준 커밋 `b8e7f50`(10/5). 가산점 정확성은 보류 중.
- 다음 단계: 05 답변서.

### 2026-10-06 · Claude · Codex 검수(공고 서버 API 01~03) 13건 반영 — 가산점 추출기 v4·전량 재추출

- 요청·목적: 사용자 "코덱스가 리뷰 남겼는데 확인 바랄게". [검수](notice_api/CODEX_REVIEW_20261006.md)를 확인하고 반영했다. 사용자가 비용은 덜 신경 써도 된다고 해서 재추출까지 진행했다.
- 작업 전 상태: 01~03 미커밋. 검수 결론은 "수정 후 재검수 필요"(P1 2·P2 8·P3 3). 13건 모두 코드에서 재확인했다. v3 결과에서 같은 근거 문장이 점수 항목 여러 개로 나뉜 공고는 103건이었다.
- 변경 파일
  - `collect/extract_bonus.py`: v4. `build_parts`, `locate_all`, `_points_in`, `_total_supported`, `verify(complete)`, `plan_work` 3중 비교, `run_batch` 하루 누적, `--ids`.
  - `search/bonus.py`: `load` 최신성, `item_hit` 추가 조건·전남/광주, `_groups`·`_score_scope`·세부사업.
  - `search/app.py`: boot 가점 최신성, `Weights.bonus` 0.
  - `search/notice_api.py`: `served_status`.
  - `search/content_version.py`: active, cv2.
  - `collect/daily_pipeline.py`: 설명.
  - 새 `db/mysql_migration_008_notice_bonus_content_version.sql`.
  - 시험: `tests/test_extract_bonus.py`·`test_bonus.py`·`test_match_deh.py`·`test_notice_api.py`.
  - 문서: [응답서](notice_api/CODEX_REVIEW_RESPONSE_20261006.md)·03 README·01 README·진행표·FLOW·문서 지도·STATUS.
- 전후 차이·선택 이유: 지적별 내용은 응답서 1절에 있다. 순위 세기는 근거가 부족해 0으로 내렸다. 결과의 `bonus_score`는 그대로 나간다. 지어내지 않는 쪽을 택해 null이 늘었다.
- 검증
  - 표본 30건(검수와 같은 공고) v4 재추출 3회, 약 $0.20. 첫 판의 묶음 오남용·괄호 숫자 누락·같은 문구 두 번을 고쳤다.
  - 공용 DB `notice_bonus`에 칸 추가(008, 사용자 진행 지시). 전량 재추출 2,078행(LLM 969, 실패 0, 약 $1.79, `reports/bonus_full_20261006T024214Z/`).
  - 서버 읽기에서 뺀 행 0. 가상 신청자 '여성기업·벤처·경기 성남시' 가산점 48건(v3 62).
  - 전체 시험 758 통과(건너뜀 16).
  - 10/7 비교 기준 `data/notice_api/content_version_20261006_cv2.json`(cv1 대비 첨부 지문이 바뀐 공고 8건).
- 미검증·남은 문제
  - 사람 정답 없음(표본은 Codex AI 판정과 대조).
  - `points_source`를 LLM이 빼면 점수 null.
  - 병합 표 해석은 LLM 몫.
  - 서버 배치 복사본 미갱신. 8000은 옛 코드.
- 다음 단계: 사용자가 Codex 재검수를 맡긴다 → 04·05. 사용자는 이 대화를 여기서 멈추고 다른 채팅에서 이어 간다.

### 2026-10-06 · Claude · 공고 서버 API 03-2~3-5 — 가점 전량 추출·신청자별 가산점·순위 반영·매일 배치

- 요청·목적: 사용자 "3-2 진행해줘"(공용 DB 표 생성·667건 추출 승인), "3번까지 마무리되면 Codex 검토". 03 나머지를 마치고 Codex 검토 요청서를 쓴다.
- 작업 전 상태: 3-1 완료(추출기·표본). `notice_bonus` 표 없음.
- 변경: 공용 DB에 `notice_bonus` 생성(생성 전 없음 확인)·2,057행 적재. 코드 `collect/extract_bonus.py`(no_mention·bonus_info 대조·`--all`·`run_batch`), 새 `search/bonus.py`, `search/app.py`(boot 가점·결과 가산점·`Weights.bonus` 기본 0.2·`bonus_boost`), `search/notice_api.py`(`bonus_info`), `collect/daily_pipeline.py`(14단계·`--skip-bonus`·`--bonus-limit`), 새 `eval/bonus_rank_eval.py`, 시험(`test_extract_bonus` 17·`test_bonus` 12·`test_notice_api` +3·`test_match_deh`), 문서 `docs/notice_api/03_bonus/`·진행표·[Codex 검토 요청](notice_api/CODEX_REVIEW_REQUEST_20261006.md)·문서 지도·FLOW·STATUS.
- 전후 차이·선택 이유: 추천 결과의 `bonus_score`·`bonus_items`가 신청자 성별·인증·지역에 따라 채워진다(0 = 해당 가점 없음, null = 계산 못 함). 공고 상세 `bonus_info`. 가산점이 있는 후보가 있으면 같은 규칙 묶음 안에서 순서가 바뀐다(세기 0.2). 가산점 후보가 없으면 순서는 전과 같다. 판정 규칙은 실제 데이터 무작위 점검에서 너무 후한 4가지(장애인표준사업장·연구소 조건·여성연구자/가족친화·지역 근거 없는 항목)와 중복 집계, 너무 엄격한 1가지(대표이사 여성)를 고친 결과다.
- 검증: 전량 추출 실패 0·약 $1.05(추정). 전체 시험 745 통과·건너뜀 16. 가상 신청자 4종 분포(예: 여성기업·벤처·경기 성남시 62건 가산점). 순위 측정(`reports/bonus_rank_eval_20261006T015155Z/`) 세기 0.1~0.3 관련도 지표 변화 0. 실제 `boot()` + `/api/match` 가산점 형식 어긋남 0, 속성 없는 신청자 세기 0·0.2 순서 동일. 8000 서버는 건드리지 않았다(10/6에 켠 01·02 코드 그대로).
- 미검증·남은 문제: 사람 정답 없음(AI 참고). K-Startup은 가산점 늘 null. 순위 측정은 가점 공고가 드물어 효과가 작게 잡힘. 서버 매일 배치는 복사본이라 14단계가 아직 돌지 않는다. 10/7 지문 하루 비교 남음.
- 다음 단계: 사용자가 Codex 검토를 맡긴다. 그 뒤 04(조율 쪽 코드로 불러 보기)·05(답변서).

### 2026-10-06 · Claude · 공고 서버 API 03-1 — 가점 추출기와 표본 30건

- 요청·목적: 조율 요청서 3.2(신청자별 가산점). 사용자 결정 "실제로 만든다". 03을 5단계로 나눠 첫 단계로 공고문 가점 추출기를 만들고 표본으로 품질을 본다.
- 작업 전 상태: 01·02 완료(미커밋). 가점 데이터 없음. 10/6 조사: 열린 공고 중 가점 언급 약 610~670건(거의 기업마당), K-Startup은 첨부 미수집.
- 변경 파일: 새 `collect/extract_bonus.py`, 새 `tests/test_extract_bonus.py`(13개), 새 `db/mysql_migration_007_notice_bonus.sql`(실행 안 함), 문서 `docs/notice_api/03_bonus/README.md`·진행표·STATUS. 결과 `reports/bonus_sample_20261006T011805Z/`·`…T012116Z/`.
- 전후 차이·선택 이유: 서비스 동작은 바뀌지 않는다(추출기만 추가). 기존 추출기와 같은 원칙(문서에 적힌 것만, 근거 원문 필수, 근거가 없으면 코드가 버림). v1 결과를 30건 모두 읽고 고쳤다: 선정 뒤 혜택을 가점으로 잡음 → 지시문 규칙, 표 칸이 끼어든 근거를 지어낸 것으로 오판 → "같은 순서·가까이" 대조, 표의 단위 없는 숫자 점수 → 인정, 지역 17곳 → 상한, 가점 없음/모름 구분 → status. 청년 고용을 청년(나이)으로 분류 → v3 지시문.
- 검증: v1 → v2 같은 표본 30건 비교(혜택 오인 3건 해소, 점수 있는 항목 16 → 31). 새 검사를 v1 원본에 다시 적용해 효과를 호출 없이 먼저 확인. 시험 13개 통과. 유료 호출 약 $0.08(추정). DB 쓰기 없음.
- 미검증·남은 문제: 사람 정답 검증 없음(AI 참고). 웹 입력으로 맞출 수 있는 가점 종류가 적어 가산점이 null(정보 없음)인 공고가 많을 것이다. "최대 N점, 1점당 1점" 항목 점수는 최대값으로 적힌다.
- 다음 단계: 3-2(공용 DB `notice_bonus` 표 생성 + 667건 추출, 약 $0.9) — 사용자 승인 필요.

### 2026-10-06 · Claude · 공고 서버 API 02 — 공고 상세·자격 판정 창구

- 요청·목적: 조율 요청서 2.4·2.5. 조율 에이전트가 후보 공고를 고를 때 부르는 공고 상세와 자격 판정 창구를 연다. 자격 판정은 추천의 정형 필터와 같은 규칙이어야 한다.
- 작업 전 상태: 01 완료 직후(미커밋). 화면용 `/api/eligibility`만 있었고 판정 코드가 app.py 안에 있었다.
- 변경 파일: 새 `search/eligibility.py`(app.py 판정 본문을 그대로 옮김, `today`·판정표를 인자로), `search/notice_api.py`(상세·판정 창구, 지원 금액 읽기), `search/app.py`(화면용 판정이 새 함수를 부름 · boot에서 지원 금액 읽기), `tests/test_notice_api.py`(11개 추가), `tests/test_match_deh.py`(가짜 DB 보강), 문서 `docs/notice_api/02_detail_eligibility/`·진행표·FLOW·STATUS.
- 전후 차이·선택 이유: 새 창구 두 개가 생겼다. 화면용 판정 결과는 바뀌지 않는다. 규칙을 복사하지 않고 한 함수로 모은 것은 요청서가 "추천과 판정이 한 곳의 규칙에서 나오게" 해 달라고 했기 때문이다. 새 판정은 지원대상 유형·업력만 보고 접수기간·모집 상태는 보지 않는다. 판정표가 꺼져 있으면 본문 유형을 쓰지 않는다(추천 필터와 같음). 근거·정의는 [02 기록](notice_api/02_detail_eligibility/README.md).
- 검증: 전체 시험 713 통과·건너뜀 16. 실제 `boot()` 후 2,765건 × 신청자 5가지 = 13,825회에서 추천 필터와 다른 결론 0건. 옛 app.py(`99a0bc9`)와 화면용 판정 16,590회 비교 다름 0건. 공고 상세 2,765건 형식 오류 0. 유료 호출·DB 쓰기 없음. 8000 서버는 건드리지 않았다.
- 미검증·남은 문제: 사업자 신청자는 모든 공고에서 "지원대상 유형"이 확인 필요로 나온다(개인·법인 자동 판정 안 함, 9/28 결정). `support_amount_text`는 null. 05 답변서에 적는다.
- 다음 단계: 03(가산점), 사용자가 시작을 정한다.

### 2026-10-06 · Claude · 공고 서버 API 01 — 수집 상태 창구·추천 결과 키

- 요청·목적: 조율 담당(4nchez)의 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`)에 따라 공고 서버에 HTTP 창구를 연다. 사용자가 작업을 01~05로 나눠 하나씩 진행하고, 작업별 기록은 `docs/notice_api/`에 두기로 했다. 이번은 01.
- 작업 전 상태: 깨끗한 작업 트리(`99a0bc9`). 수집 상태 판정 함수는 있었지만 HTTP 창구가 없었고, 추천 결과에 내용 버전·가산점 키가 없었다.
- 변경 파일: 새 `search/notice_api.py`(수집 상태 창구), 새 `search/content_version.py`(공고 내용 지문·하루 비교 명령), `search/app.py`(창구 연결·boot에서 저장 시각과 지문 읽기·결과 키 3개), 새 `tests/test_notice_api.py`(16개), `tests/test_match_deh.py`(boot 가짜 DB 보강), `.gitignore`(`data/notice_api/`), 문서 `docs/notice_api/`(새)·`docs/README.md`·`docs/FLOW.md`·STATUS.
- 전후 차이·선택 이유: `GET /api/collection_status`가 생겼다. DB 판정에 더해 **서버가 메모리에 올린 공고가 24시간을 넘으면 정상 → 지연**으로 내린다(서버를 다시 켜야 새 공고가 반영되기 때문). DB를 못 읽으면 503. 추천 결과 한 건에 `content_version`(원문 칸 + 첨부 파일 바이트 SHA-256, 수집 시각·LLM 값 제외), `bonus_score: null`, `bonus_items: []`가 붙는다. 순위·필터 등 기존 동작은 바뀌지 않는다. 자세한 근거는 [01 기록](notice_api/01_status_match/README.md).
- 검증: 전체 시험 702 통과·건너뜀 16. 실제 DB 지문 2,765건 0.2초·재계산 동일·충돌 0. 실제 `boot()`(25.4초) 후 TestClient로 수집 상태 200 `정상`, 가짜 신청 정보로 추천 offset 0·10 각각 10건·필수 키 누락 없음. 8000 서버는 건드리지 않았다. 유료 호출·DB 쓰기 없음.
- 미검증·남은 문제: 지문이 날마다 수집 잡음으로 바뀌지 않는지는 10/7 배치 뒤 `python -m search.content_version --compare data/notice_api/content_version_20261006.json`으로 확인해야 한다. 이 PC의 8000은 옛 코드라 다시 켜야 새 창구가 열린다.
- 다음 단계: 02(공고 상세·자격 판정), 사용자가 시작을 정한다.

### 2026-10-02 · Claude · 매일 수집 배치를 PC 에서 서버(EC2)로 전환

- 요청·목적: PC 를 꺼 둔 날(10/1 병가) 수집이 멈추는 문제를 없앤다. 웹 배포용으로 만든 개인 계정 EC2 `sbrain-web` 에서 배치만 돌린다(공고 매칭 8000 은 옮기지 않음). 사용자 결정: 시험 1~3단계 뒤 "전환해 줘".
- 작업 전 상태: 10/2 08:43 PC 배치가 밀린 실행으로 돌아 09:05 `exit=0`(공고 2,714건, K-Startup 모집 종료 292건 — 모두 마감일 지난 공고, 인계서의 "10/1 배치 뒤 닫은 건수 확인" 과제는 이것으로 확인). 09:00 정규 실행은 실행 중이라 무시됐다(`IgnoreNew`).
- 변경 파일(data-collection 코드는 고치지 않았다): 저장소 루트 `deploy/` 에 `batch.Dockerfile`·`batch.Dockerfile.dockerignore`·`batch-requirements.txt`(PC .venv 버전 고정, torch 는 CPU 판)·`run_batch.sh`(run_daily.bat 의 리눅스판, 같은 `data/run.log` 에 기록) 추가, `docker-compose.yml` 에 `batch` 서비스(profile) 추가, `deploy/README.md` 에 절차·시험 기록.
- 서버 배치: `~/sbrain/data-collection`(이 PC 작업 폴더 10:54 복사, `.venv`·`docs`·`ml`·`.env` 제외), `.env` 는 배치에 필요한 키 8개만(권한 600), DB CA 는 `~/sbrain/secrets/ec2-ca.pem`(compose 가 `MYSQL_SSL_CA` 를 덮음), BGE-M3 는 볼륨 `sbrain_hf_cache` 에 **리비전 `5617a9f…` 고정**(다르면 `shared/embed.fingerprint` 가 바뀌어 전량 재임베딩).
- 검증(DB 쓰기 0, LLM 0):
  - dry-run: AWS 에서 두 API 응답(K-Startup 215 = 서버 보고, 기업마당 1,444).
  - 예약과 같은 빈 환경 dry-run `exit=0`. 이때 `docker compose run` 이 표준입력을 삼켜 부른 쪽 스크립트가 끊기는 문제를 찾아 `run_batch.sh` 에 `< /dev/null` 을 붙였다.
  - 팀 DB 암호화 SELECT 2,714건 0.3초, `embed.run(plan_only=True)` "그대로 2,714 · 만들 것 0", 설정 지문 PC 와 같음.
  - 실제 공고 112건 임베딩(저장 안 함) 109.6초, 프로세스 최대 2,435MB, 서버 여유 메모리 최저 2,058MB / 3,811MB.
- 전환: PC 예약 작업 `Disable-ScheduledTask`(삭제 안 함) → 시험으로 바뀐 서버 `data/` 를 `~/sbrain/_old/data_test_20261002` 로 옮기고 PC `data/` 재복사(서버 run.log 마지막 줄이 PC 와 같은 09:05 `exit=0`) → crontab `0 0 * * *` 등록, cron active.
- 미검증·남은 문제: 서버에서의 실제 실행(DB 쓰기·LLM)은 아직 없다. 첫 실행은 10/3 09:00. 이 PC 의 8000 색인은 더 이상 갱신되지 않는다. 서버 코드는 복사본이라 PC 코드 수정이 자동 반영되지 않는다. 팀 EC2 의 09:10 Chroma 갱신과 겹치는 기존 문제(인계서 4절)는 그대로다.
- 다음 단계: 10/3 09:20 쯤 서버 run.log·DB 점검, 정상이면 `_old` 정리.

### 2026-09-30 · Claude · `model-eval/` Codex 채점 지시서 (사람 채점 대체)

- 요청·목적: 사용자가 도메인 지식이 얕아 사람 채점 도구로 직접 채점하기 어렵다고 해서, 검증-1 좋음/보통/나쁨 12편 채점을 Codex에게 맡기는 지시서와 꾸러미를 만들었다. 결과는 사람 정답이 아니라 AI 참고 점수다.
- 변경 파일: 신규 `model-eval/docs/CODEX_RATING_TASK_20260930.md`, `model-eval/human/codex_pack/`(`docs.jsonl` 12편·`rubric.json`·`meta.json`, 단계·정답 없음). `model-eval/v6_hard/human_tool.py`에 `check`(형식 검사, 정답 열쇠를 읽지 않음)와 결과 파일의 `rater` 표기를 추가하고, `tests/test_v6_hard.py`에 꾸러미·검사 테스트를 더했다(전체 91개 통과). `human/rating_tool.html`·`key.json`은 다시 만들어도 바이트 단위로 같다(사용자에게 보낸 도구와 열쇠가 맞는다). `data-collection` 코드는 수정하지 않았다.
- 검증: 꾸러미에 good/medium/poor·계획서 번호·case_id가 없는지 테스트로 확인. 검사 명령이 없는 파일에서 실패하는 것을 확인했다. Codex 실행은 아직 안 했다.
- 다음 단계: Codex가 `human/codex_pack/ratings.json`을 쓰면 `python -m v6_hard.human_tool check …` 후 `score human/codex_pack/ratings.json reports/v6_gradient_20260930T171201`로 모델 점수와 대조하고 결과를 인계서에 덧붙인다. 커밋은 하지 않았다.

### 2026-09-30 · Claude · `model-eval/` 더 어려운 시험 3종 (검증-1 미묘한 차이 · 전략 함정 · 작성 유혹)

- 요청·목적: 사용자가 "조금 더 어려운 시험은 안 했냐"고 물어 (1) 검증-1의 좋음/보통/나쁨 3단계 시험 + 사람 채점 도구, (2) 전략 T-S2와 작성 T-W1의 함정 시험을 만들고 실행. 지금까지 시험이 천장 효과(다들 100%)여서 모델 차이를 못 보았기 때문.
- 변경 파일: 신규 `model-eval/v6_hard/`(`cases.py`·`evaluate.py`·`run.py`·`report.py`·`report_template.html`·`human_tool.py`), `model-eval/human/`(사람 채점 도구·안내), `model-eval/tests/test_v6_hard.py`, `model-eval/build_index.py`(v6 표시), 인계서 3-7절·README·AGENTS 갱신. 기존 v1~v5 코드와 `data-collection`은 수정하지 않았다(`v4_writer/score.py`의 값 1 이하 수치 검사 제외 한 줄만 v6 오탐 때문에 고쳤고 v4 표는 재채점해도 그대로).
- 결과(후보 luna6-medium · luna-medium · gpt-4.1-mini, 반복 3, 호출 396건, 합계 $0.52): 검증-1 3단계는 luna 둘이 순서 100%(좋음-보통 14~16점), gpt-4.1-mini는 75%(좋음-보통 2.0점). 전략 함정 luna6 94% · luna-medium 73%(낡은 자료 0/12) · mini 56%(관련 없는 통계를 지시에도 10/12에서 사용). 작성 유혹 luna 둘 92% · mini 48%(관대한 상한 기준으론 67%); 수치유도에서 luna도 4/12를 지어냄.
- 검증: 테스트 90개 통과(v6 25개). 리포트 3개를 브라우저로 열어 표시·콘솔 오류 없음 확인. 채점 기준은 결과를 본 뒤 여러 번 고쳤다(대부분 오탐 제거, 한 곳은 더 엄격): 낡은/무관 자료 한계 문구, 반영하지 않겠다고 쓴 요청 금액, 총사업비 언급, 조달원(지원금·자체 자금) 금액, 가정이라 밝힌 수치. 상한충돌은 엄격(공고 규칙 그대로)·관대 두 기준을 함께 적었다. 자세한 내역은 인계서 3-7절.
- 미검증·남은 문제: 보통·나쁨 단계는 규칙으로 만든 것이라 사람 점수와의 일치는 미측정(사람 채점 도구 준비됨). 낡은자료·무관자료의 "한계를 밝혔다" 성공 기준은 기능정의서에 없는 내가 정한 기준이다. 상한충돌에서 "지원규모"가 지원금만 뜻하는지 항목 합 전체를 뜻하는지는 팀이 정할 일. 실험 누적 비용은 $6.60(v1~v6). 커밋은 하지 않았다.
- 다음 단계(사용자 결정): 사람 채점 도구 12편 채점 후 일치도 확인, 검증-2·검수 시험, 로컬 모델 추가.

### 2026-09-30 · Claude · `model-eval/` 팀 공유용 요약 문서

- 요청·목적: 사용자가 지금까지 Agent별 모델 시험 결과를 팀에 공유할 요약을 요청.
- 변경 파일: 신규 `model-eval/docs/TEAM_SUMMARY_20260930.md`(마크다운 원본)·`TEAM_SUMMARY_20260930.html`(시각 버전, 파일로 열림), `model-eval/docs/HANDOFF_20260930.md`·`model-eval/README.md`에 위치 안내 추가. `data-collection` 코드는 수정하지 않았다.
- 내용: 한 줄 결론(gpt-6-luna 가격 대비 최선), Agent별 추천·피할 모델, 발견 6가지, 팀 코드 제안 4가지(T-S1 기능 목록은 코드가 복사, T-S2는 자료 공급·걸러내기, 검증-1 온도 0 고정 불가·편차 감시, rubric 실제 공고 기준화), 한계(가상 샘플·사람 점수 미대조·기준 사후 수정). 실험 5종·호출 2,106건·$6.08은 결과 파일에서 다시 합산한 값이다.
- 검증: 수치를 인계서·요약표와 대조했고, HTML은 브라우저로 열어 표시(막대 라벨 잘림 1건 수정)를 확인했다. 실행·API 호출 없음.
- 미검증·남은 문제: 팀 결정이 아니라 한 사람의 자체 시험이라고 문서에 명시했다. 커밋은 하지 않았다.
- 다음 단계(사용자 결정): 요약을 Notion·PR 등 팀 채널에 올릴지, 구현 반복 추가·로컬 모델·사람 점수 대조 진행 여부.

### 2026-09-30 · Claude · `model-eval/` gpt-6-luna 추가 실행 (5개 실험 폴더)

- 요청·목적: 사용자가 "gpt-6-luna가 5.6보다 좋고 싸다"고 알려 줘서 확인하니 이 키로 gpt-6 계열이 이미 쓸 수 있었다(내 모델 목록 조회가 이름을 일부만 걸러 놓친 것). 요금 페이지 확인: gpt-6-luna $0.10/$0.50(5.6의 절반), gpt-6-sol·6.1-sol $2/$10, gpt-6-astra $10/$50. 사용자 결정으로 sol·astra·terra는 쓰지 않는다.
- 변경 파일: `model-eval/candidates.json`(luna6-medium 등록; sol6-medium은 등록했으나 실행하지 않음), `model-eval/clients/openai_compat.py`(`merge_candidates`: 이어서 실행할 때 기존 후보 유지), 다섯 `run.py`의 meta 후보 합치기, `model-eval/AGENTS.md`(비싼 모델 금지·목록 전체 조회 규칙). 결과는 기존 폴더 v1(plans4)·v2·v3·v4·v5에 `luna6-medium` 행이 추가됐다. `data-collection` 코드는 수정하지 않았다.
- 검증: 생성 호출 296건 실패 0, 비용 $0.18 + 작성 채점자 24건 $0.04. 테스트 65개 통과. 비교표는 `model-eval/docs/HANDOFF_20260930.md` 3-6절.
- 결과 요지: gpt-6-luna는 5.6과 대체로 같은 품질을 약 절반 가격에 낸다. 구현 HTML은 명도 대비 6/6으로 codex-5.3과 같은 30.0/30을 $0.045에 냈다(codex $0.90). 전략 T-S1의 기능 목록 유지는 75%로 5.6(88%)보다 나쁘다.
- 미검증·남은 문제: 반복 3회(구현 1회)·아이템 8건이라 작은 차이는 오차 범위. 작성 글 품질 채점자가 luna 5.6이라 5.6에 후할 수 있다.
- 다음 단계(사용자 결정): 구현 반복 추가(gpt-6-luna·codex), 팀 공유용 요약 문서, 로컬 모델. 커밋은 하지 않았다.

### 2026-09-30 · Claude · `model-eval/` 구현 T-B1·T-B2 실험 (반복 1회)

- 요청·목적: 사용자 지시("너무 계산하지 말고 그냥 쓰자")에 따라 구현 Agent 실험을 실행. 기획서 5-2의 "구현=코드 특화 모델" 방침에 맞춰 `gpt-5.3-codex`를 후보에 넣었다(Responses API 전용; 다른 codex 모델은 폐기).
- 변경 파일: 신규 `model-eval/v5_builder/`(정적 검사기 `checks.py`·프롬프트·채점·실행·리포트), `model-eval/clients/openai_compat.py`(Responses API·텍스트 호출 `call_text` 추가), `model-eval/candidates.json`(codex-5.3·gpt-5.4-mini·gpt-4.1 추가, 단가는 2026-09-30 요금 페이지에서 확인), `model-eval/build_index.py`(작성 v4·구현 v5 종류 등록), `model-eval/tests/test_v5_builder.py`. 결과 `model-eval/reports/v5_20260930T160751_builder/`. `data-collection` 코드는 수정하지 않았다.
- 검증: 5후보×70호출(HTML 6건+SVG 8건), 실패 0, 총 **$2.35**. 테스트 65개 통과. 결과 요약은 `model-eval/docs/HANDOFF_20260930.md` 3-5절.
- 결과 요지: 기능 대조와 대부분의 접근성 검사는 5개 모두 통과(천장), 차이는 명도 대비뿐이다. codex-5.3이 HTML 30.0/30(명도 대비 6/6)으로 최고, gpt-4.1이 28.3(1/6)로 최저. luna-medium은 codex의 약 1/10 비용에 28.7.
- **기준 수정 고지:** 결과를 보고 채점기를 세 번 고쳤다(SVG 문제 정의·목표 고객 판정을 이름표 기준으로, 그라데이션 배경 판정 제외, 그리고 실행 전 테스트가 잡은 T-B2 프롬프트의 아이템명 누락). 모두 오탐 제거이고 리포트·인계서에 명시했다. 또 **결과 목록 페이지에 작성(v4) 종류가 등록되지 않아** 작성 실험 카드가 화면에 안 나오던 오류를 발견해 고쳤다.
- 미검증·남은 문제: 반복 1회라 작은 차이는 오차 범위. 화면 동작·미관은 정적 파싱으로 못 재고 리포트 갤러리 미리보기로만 확인 가능. 명도 대비는 근사 판정.
- 다음 단계(사용자 결정): 반복 추가(회당 약 $2.3), 검증-1 사람 점수 대조, 로컬 모델 추가, 결과 요약 문서. 커밋은 하지 않았다.

### 2026-09-30 · Claude · `model-eval/` 작성 T-W1·T-W2·T-W3 실행 결과

- 요청·목적: 사용자 승인(terra 포함 5개 후보)으로 작성 Agent 실험을 실제 실행. 위 "작성 실험 준비" 항목의 후속이다.
- 변경 파일: 신규 결과 `model-eval/reports/v4_20260930T152438_writer/`(calls.jsonl·judge.jsonl·summary.md·report.html). 채점 기준 수정: `model-eval/v4_writer/score.py`·`report_template.html`·`tests/test_v4_writer.py`. `data-collection` 코드는 수정하지 않았다.
- 검증: 360호출 + 채점자 120호출, 실패·형식 오류 0, 총 **$1.44**(예상 $2.0). 테스트 49개 통과. 결과 요약은 `model-eval/docs/HANDOFF_20260930.md` 3-4절.
- 결과 요지: (1) 규칙 검사만 보면 5개 후보가 거의 같다. (2) gpt-4.1-mini는 본문이 짧고(평균 1,342자 대 약 2,300자) 채점자 점수가 가장 낮고(51.8 대 54.0~55.6), 입력된 개발 기간을 넘는 일정을 19/24에서 지어냈으며 그래프 통과율도 71%다. (3) luna 세 강도와 terra는 글 품질이 오차 범위인데 terra는 luna-medium의 약 9배 비용이다.
- **기준 수정 고지:** 첫 채점표에서 "지원금 상한 초과"가 후보별 4~16건이 나왔으나 응답을 읽어 보니 채점기 오탐이었다(상한 문구·단가·표 세부 내용 칸을 금액 합에 더함 등 6종). 모두 오탐을 없애는 수정이고 수정 전 숫자와 다르다. "일정이 개발 기간을 넘김"은 결과를 보다가 추가한 관찰 지표다. 리포트 하단에도 명시했다.
- 미검증·남은 문제: 아이템 8건·반복 3회. 글 품질 채점자(luna-medium)는 luna 계열과 같은 모델이다. 최소 분량·종결 형식은 잠정 기준. 일정표 날짜 기준선은 미검사.
- 다음 단계(사용자 결정): 구현 Agent(T-B1·T-B2) 실험, 또는 로컬 모델(집 PC 3060·RunPod) 추가, 또는 검증-1 사람 점수 대조. 커밋은 하지 않았다.

### 2026-09-30 · Claude · `model-eval/` 작성 T-W1·T-W2·T-W3 실험 준비

- 요청·목적: 사용자가 전략 다음으로 작성 Agent 실험을 요청했다(A). 기능정의서 v1.9 시트 2의 T-W1·T-W2·T-W3 정의(필수 섹션 1:1, 입력에 없는 경력 서술 금지, 지원규모 상한, 그래프 수치 재계산 대조, 표 합계·칸 수)를 자동 채점 기준으로 옮겼다.
- 변경 파일: 신규 `model-eval/v4_writer/`, `model-eval/fixtures/writer_cases.json`(전략 아이템 8건에 양식·공고·회사 정보·고정 계획서 추가), `model-eval/tests/test_v4_writer.py`. `data-collection` 코드는 수정하지 않았다.
- 전후 차이·선택 이유: 그래프·표는 입력을 코드가 만든 고정 계획서로 통일해 후보 간 공정하게 비교한다. 본문의 글 품질은 자동 채점이 안 되므로 검증-1에서 가장 나았던 luna-medium을 채점자로 재사용하되, luna 계열에 후할 수 있다고 리포트에 명시했다. 최소 분량 150자와 종결 형식 판정은 기능정의서에 값이 없어 정한 잠정 기준이다.
- 검증: 가짜 모델 테스트 44개 통과(검증-1 10·조율 9·전략 12·작성 13). 화면은 가짜 응답으로만 확인했다. **실제 API 호출은 하지 않았다.** 예상 비용 약 $2.0(후보 5×360호출 + 채점자 120호출).
- 미검증·남은 문제: 실제 결과 없음. 채점 기준은 실행 전에 고정했다(전략 실험처럼 결과를 본 뒤 고치지 않기 위해). 일정표 날짜 기준선은 검사하지 않는다.
- 다음 단계: 사용자 승인 뒤 `python -m v4_writer.run --execute --max-usd 3`. 커밋은 하지 않았다.

### 2026-09-30 · Claude · `model-eval/` 전략 T-S1·T-S2 실행 결과

- 요청·목적: 사용자 승인(전략 실험 실행) 후 5개 후보로 실제 실행. 위 "전략 T-S1·T-S2 실험 준비" 항목의 후속이다.
- 변경 파일: 신규 결과 `model-eval/reports/v3_20260930T150020_strategy/`(calls.jsonl·summary.md·report.html), 결과 목록 `model-eval/reports/index.html`(신규 `model-eval/build_index.py`가 실행마다 갱신). 채점 기준 수정: `model-eval/v3_strategy/score.py`·`report_template.html`·`tests/test_v3_strategy.py`. `data-collection` 코드는 수정하지 않았다.
- 검증: 후보 5×아이템 8×3종류×3회=360호출, 실패·형식 오류 0, 총 **$0.94**(예상 $1.3). 테스트 31개 통과(검증-1 10·조율 9·전략 12). 결과 요약은 `model-eval/docs/HANDOFF_20260930.md` 3-3절.
- 결과 요지: (1) T-S1은 gpt-4.1-mini만 기준 기능 목록을 24/24 그대로 유지, terra는 8/24에서 목록을 쪼개거나 풀어써 바꿈. (2) T-S2 참고 자료가 없을 때 gpt-4.1-mini는 24호출 모두 지어낸 듯한 출처의 수치를 넣었고 luna는 0개. (3) 참고 자료가 있을 때 luna-medium·terra가 자료 활용 94%로 최고, gpt-4.1-mini 76%와 콜센터 시장 3조 원을 30조 원으로 잘못 옮긴 오기(st08, 반복해서 발생). (4) terra는 luna의 약 10배 비용에 뚜렷한 이점 없음.
- **기준 수정 고지:** 결과를 본 뒤 채점 기준을 고쳤다(함정 사용의 한계 명시 여부, 자료를 곱해 만든 계산값을 구분). 응답을 읽어 보니 처음 기준이 정상적인 사용을 실패로 세고 있었다. 수정 전 숫자와 다르며 리포트·요약에도 명시했다.
- 미검증·남은 문제: 아이템 8건·반복 3회라 작은 차이는 오차 범위. 자료 없음 조건의 수치는 사실 여부를 검증하지 못했다. 글의 품질은 채점하지 않았다. 정답 기준은 Claude가 정했고 사람 검수 전이다.
- 다음 단계(사용자 결정): 작성 Agent(T-W1~W3) 실험, 또는 구현 Agent, 또는 로컬 모델(집 PC 3060·RunPod) 추가. 커밋은 하지 않았다.

### 2026-09-30 · Claude · `model-eval/` 전략 T-S1·T-S2 실험 준비

- 요청·목적: 사용자가 조율 다음으로 전략 Agent 실험을 요청했다(B). 기능정의서 v1.9 시트 2·3·4·7의 T-S1·T-S2 정의를 기준으로 삼았다.
- 변경 파일: 신규 `model-eval/v3_strategy/`, `model-eval/fixtures/strategy_cases.json`(가상 아이템 8건), `model-eval/tests/test_v3_strategy.py`. 공용 실행기 `model-eval/v1_verifier/run.py`에 "job의 추가 필드를 결과 행에 싣는" 한 줄을 보강했다(기존 동작 그대로). `data-collection` 코드는 수정하지 않았다.
- 전후 차이·선택 이유: T-S1은 "featureList가 coreFeatures를 누락 없이 포함"을 글자 그대로/뜻이 같으면 두 기준으로 자동 채점한다. T-S2는 모델에 검색 도구가 없어 출처 있는 수치를 만들 수 없으므로 참고 자료(통계 3건+함정 1건)를 주는 조건과 주지 않는 조건을 나눠 자료 활용·함정·자료 밖 수치를 자동 대조한다.
- 검증: 가짜 모델 테스트 30개 통과(검증-1 10·조율 9·전략 11). 화면은 가짜 응답으로만 확인했다. **실제 API 호출은 하지 않았다.** 예상 비용 후보 5×360호출 약 $1.3.
- 미검증·남은 문제: 실제 결과 없음. 글의 품질은 채점하지 않는다. 참고 자료 없음 조건의 수치는 사실 여부를 검증할 수 없다.
- 다음 단계: 사용자 승인 뒤 `python -m v3_strategy.run --execute --max-usd 2`. 커밋은 하지 않았다.

### 2026-09-30 · Claude · `model-eval/` 조율 T-C1 실험 준비 + 앞선 기록 정정

- 정정: 바로 아래 항목(검증-1)의 "저장소에 모델 배치 기준 문서가 없다"는 **틀렸다.** `data-collection/docs/specs/`의 기획서 v1.10 5-2절에 Agent별 모델 배치 방침이 있다(조율·전략·작성·검증-1은 추론 성능 우선, 구현은 코드 특화, 검증-2는 비용 효율, 검수는 자체 파인튜닝). 표는 `model-eval/docs/HANDOFF_20260930.md` 1절에 옮겼다. 그 항목의 다른 내용은 유효하다.
- 요청·목적: 사용자가 검증-1 다음으로 조율 Agent 실험을 요청했다(D). 기획서 5-1에서 T-C3(작업 분해)는 직접 구현 로직이라 대상이 아니고, LLM이 하는 조율의 핵심은 T-C1(요구사항 해석·카테고리 판정)이다.
- 변경 파일: 신규 `model-eval/v2_coordinator/`(프롬프트·채점·실행·리포트), `model-eval/fixtures/tc1_cases.json`(가상 아이템 32건: 명확 27·경계 3·지시문 삽입 2), `model-eval/tests/test_v2_coordinator.py`. `data-collection` 코드는 수정하지 않았다.
- 전후 차이·선택 이유: 카테고리 정답을 기획서 4-4 기준(원페이지=오프라인 매장·제조, 웹개발=플랫폼·중개·커머스, AI API=AI가 본체)으로 정해 자동 채점한다. 경계 사례는 두 카테고리를 허용하고, 설명 속에 끼워 넣은 지시문에 속는지도 본다. 정답은 Claude가 정했고 사람 검수 전이다.
- 검증: 가짜 모델 테스트 19개 통과(검증-1 10 + 조율 9). 사용자 승인 뒤 **실제 실행**: 후보 5(gpt-4.1-mini, luna low/medium/high, terra-medium)×32건×3회=480호출, 실패·형식 오류 0, 총 **$0.54**(예상 $1.2). 결과 `model-eval/reports/v2_20260930T142448_tc1/`.
- 결과: 명확·경계 사례는 5개 후보 모두 100%(천장 효과). 지시문 삽입 inj02에서 gpt-4.1-mini만 3/3 속음(확신 0.30). terra-medium은 luna-low의 약 10배 비용에 이점 없음. 시험이 너무 쉬워 후보를 가르지 못한다.
- 미검증·남은 문제: 정답은 Claude가 정했고 사람 검수 전이다. 사례가 모두 깨끗한 문장이라 실제 입력의 어려움을 반영하지 못한다. 아이템 명세 품질은 채점하지 않았다.
- 다음 단계: 더 어렵고 현실적인 사례 추가 또는 다음 Agent(전략·작성) 실험. 커밋은 하지 않았다.

### 2026-09-30 · Claude · Agent별 모델 비교 실험 시작 — `model-eval/` 검증-1

- 요청·목적: 사용자가 S-Brain Agent별로 어떤 모델이 좋은 성능을 내는지 자체 시험하려 한다. 기존 파일은 고치지 않고 새 파일로, GPT뿐 아니라 로컬 모델도 후보로 둔다(팀 결정 아님).
- 작업 전 상태: 팀 코드의 Agent 모델 설정은 대부분 "미정"(`agent-orchestration/sbrain/orchestrator/settings.py`). 저장소에 모델 배치 기준 문서가 없다.
- 변경 파일: 신규 폴더 `model-eval/` 전체(코드·픽스처·결과·문서). `data-collection`은 이 기록과 STATUS 항목만 추가했다. 로컬 `.claude/launch.json`(Git 제외)에 결과 열람용 서버 `eval-reports`(8020) 추가.
- 전후 차이·선택 이유: 원본 계획서와 일부러 망가뜨린 변형 5종을 채점시켜 사람 점수 없이 비교한다(정답이 미리 알려짐). 총점은 항목 점수를 코드가 합산한다. 모델 호출은 OpenAI 호환 어댑터 하나로 통일해 로컬 서버도 같은 코드로 붙는다.
- 검증: 가짜 모델 테스트 10개 통과. 실제 호출 3회 — 시험 6호출 $0.009, 1편×4후보×3회 72호출 $0.121, **4편×4후보×3회 288호출 $0.458**(모두 성공, 형식 오류 0). 결과 `model-eval/reports/v1_20260930T124257_plans4/`. 잠정: gpt-4.1-mini 부적합(없는 섹션에 점수), luna-medium 가성비 후보.
- 미검증·남은 문제: 계획서가 모두 가상 샘플이라 AI 채점 편향이 남고, **사람 점수 일치도는 측정하지 않았다**. 로컬 모델·Claude는 미시험. 단가는 9/22 기록 기준이며 실행 시점 재확인 못 함.
- 다음 단계: 사용자가 정한다 — 로컬 모델 추가(집 PC 3060), 사람 점수 10~20건 대조, 또는 조율 Agent(T-C1·C3) 실험. 자세한 내용은 `model-eval/docs/HANDOFF_20260930.md`. 커밋은 하지 않았다.

### 2026-09-30 · Claude · Codex 관련도 판정 확인, 후보 A~C 재측정

- [Codex 결과](reviews/matching/RELEVANCE_LABEL_RESULT_20260930.md): 448쌍 판정, 블라인드 절차 준수, `eval/qrels.jsonl` 변경 없음(지문 동일).
  - Claude가 `relevance_label_score`를 다시 돌려 같은 값을 확인했다.
  - **사람 대조군 40쌍 정확 일치 0.50, 선형 가중 카파 0.31**(기준 0.70·0.60 미달), 한 등급 이내 0.90, "2냐 아니냐" 0.775.
  - 사람 2 → Codex 2는 5/14였다. 대상 408쌍 라벨은 0 167 · 1 192 · 2 49로, **Codex가 기존 LLM 판정보다 엄격하다.**
- 재측정: `eval.match_variants --extra-qrels …/codex_qrels.jsonl` → [reports/match_variants_20260930T020435Z](../reports/match_variants_20260930T020435Z/summary.md). 미판정은 0이 됐다.
  - P@3(2): 개발용 base 0.686 · A 0.705 · B05 0.714 · C 0.686. 시험용 base 0.627 · A 0.569 · B05 0.627 · C 0.608.
  - nDCG 전체: base 0.662 · A 0.644 · B05 0.669 · C 0.663.
  - A는 개발용과 시험용 방향이 엇갈린다. C는 시험용 쓸모@10 −0.235 [−0.471, −0.059]. B05는 어디서도 나빠지지 않지만 모든 구간이 0을 걸친다.
- 해석 주의: 기존 판정(LLM, 너그러움)과 새 판정(Codex, 엄격함)의 기준이 다르다. 그래서 새 공고를 많이 올리는 방식(A)이 불리하게 나올 수 있다.
- 결정 필요(사용자): Codex 판정을 qrels에 합칠지, 같은 판정자(LLM)로 408쌍을 다시 매겨 기준을 맞출지(유료, 비용 확인 필요).

### 2026-09-30 · Codex · 매칭 관련도 448쌍 블라인드 판정·채점 완료

- 요청·목적: 사용자 요청으로 [Claude 지시서](reviews/matching/RELEVANCE_LABEL_TASK_20260930.md)의 topic-v2 판정을 수행했다. base 빈칸 284·변형 후보 빈칸 124·사람 대조 40쌍이며 결과는 AI 참고 정답이다.
- 작업 전 상태: Claude의 코드·문서·DB 스키마·시험 변경, 매칭 후보·분석 산출물과 기존 Codex 검수 기록은 보존했다. 검색 평가 재실행이나 병합은 요청 범위에 넣지 않았다.
- 변경 파일: reports/relevance_label_pack_20260930/labels.jsonl·score.json·score.md·codex_qrels.jsonl, [결과 문서](reviews/matching/RELEVANCE_LABEL_RESULT_20260930.md), 자신의 STATUS 항목·이 이력·문서 지도 matching 행.
- 판정: 전체 448(0=185·1=209·2=54·null=0, borderline=28), 대상 408(0=167·1=192·2=49, borderline=25). 지역·업력·규모·형태·마감은 제외하고 지원 내용·산업·특정 집단 근거를 대조했다. 첨부의 게임·수입상품 제외는 채점 전에 반영했다.
- 검증: hidden을 읽기 전에 독립 스키마 검사 통과(448행·ID 누락/중복/미등록 0·자료형·지원/이유 본문). labels 지문을 고정한 뒤 번들 Python(-B·바이트코드 방지, 프로젝트 site-packages)에서 eval.relevance_label_score 실행. 최초 score.json 쓰기 PermissionError 후 권한 검토를 거쳐 같은 판정으로 정상 종료했다. 모듈은 hidden을 자체 검사 전에 읽으므로 독립 검사를 선행했다.
- 채점: 사람 대조 40쌍 정확 일치 50.0%(20/40), 한 등급 이내 90.0%(36/40), 2점 여부 77.5%(31/40), 선형 가중 카파 0.3103448276. 과거 LLM/Jev 표본과 비교하지 않았다. 후보 408줄 출력·labels 및 기존 qrels 지문 불변을 확인했다.
- 미검증·남은 문제: 전체 첨부 원문·실제 신청 자격 검증, DB/API·유료 호출·검색 후보 재평가 없음. 분야·집단·명시된 필요 해석에서 대조군 20쌍 불일치. 통합공고 펨테크 갈래, 단계만 근거로 든 범용 교육 등의 수정 후보는 문서에만 남겼으며 labels를 고치지 않았다.
- 다음 단계: 사람 검토로 기준을 맞춘 뒤 사용자가 병합 여부·버전을 정한다. 원본 labels와 채점 결과는 고정 보존한다. 코드·DB·eval/qrels.jsonl·스테이징·커밋·push 변경 없음.

### 2026-09-30 · Claude · 공고팀 작업 지표 스크립트와 PDF 보고서

- 요청·목적: 사용자 요청(멘토가 지표를 중시). 수집부터 매칭·운영까지 다시 잴 수 있는 지표를 PDF로 만든다. Codex 판정을 기다리는 동안 했다.
- 변경 파일(신규)
  - `eval/metrics_report.py`: 지표 26개를 A 수집·운영, B 전처리, C LLM 추출, D 매칭, E 평가 신뢰도, F 서비스·개발로 나눴다. 공용 DB는 조회만 하고 결과 파일(9/28 평가, label_pack, jev)을 읽는다. `--latency`는 8000에 평가 질의 58개를 보내고, `--tests`는 unittest를 센다.
  - `eval/metrics_pdf.py`: HTML을 만들고 Edge headless로 PDF를 인쇄한다(새 패키지 없음). 지표마다 쉬운 설명을 붙이고 "약점과 다음 할 일" 절을 넣었다.
- 결과: `reports/metrics_20260930T105348/지표_보고서.pdf`(4쪽)와 `metrics.json`·`summary.md`.
  - 공고 2,603건. 배치 성공 20/20인데 가동일은 10/17일(58.8%)이다.
  - 첨부 본문 추출 91.6%, 판정표 적용 100%, 지문 신선도 100%. 예비창업자 명시 불가 정밀도 30/30.
  - 신청 불가@10은 0.243에서 0이 됐다. P@3(2) 하한은 0.494에서 0.621, nDCG는 0.60으로 그대로다.
  - 미판정 32.1%, LLM 판정자 일치 0.64. 응답 중앙값 345ms(p95 503ms), 테스트 686개.
- 검증: PDF 4쪽을 열어 한글·표를 확인했다. unittest 686개 통과.
- 미검증·남은 것: Codex 판정(448쌍)이 오면 E에 "Codex vs 사람" 줄이 자동으로 붙는다(`relevance_label_pack_20260930/score.json`). 자격요건 추출 비용은 로그에 금액이 없어 빠졌다.

### 2026-09-30 · Codex · K-Startup 모집 종료 처리 재검수 승인

- 요청·목적: 사용자 요청으로 [Claude 응답서](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_RESPONSE_20260930.md)의 기존 P1 1·P2 2 수정과 회귀 가능성을 재검수했다. 코드·DB 수정 없이 결과만 기록했다.
- 작업 전 상태: Claude의 미커밋 코드·문서 변경과 별도 매칭 평가 작업은 보존했다. 직전 Codex 검수의 보류 판정은 아래 과거 기록이며 이번 결과로 갱신한다.
- 변경 파일: [재검수 결과](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_RECHECK_20260930.md), 자신의 STATUS 항목, 이 WORKLOG, 문서 지도 결과 링크.
- 결과: **승인, 기존 세 건 해결·추가 지적 없음.** close_missing의 snapshot_at 조건·갱신과 last_import_id 갱신, normalize.text 공유, 한국 날짜 SQL을 확인했다.
- 검증: 번들 Python + 프로젝트 가상환경 패키지, 바이트코드 생성 방지·MYSQL_INTEGRATION_TEST=0. test_pipeline.py·test_store_mysql.py 34개 중 28개 통과·6개 건너뜀, 실패·오류 0. 표준입력 스크립트에서 실제 함수와 메모리 SQL 대역으로 종료 후 과거 재적재·최신 재개·과거/동일 시각 목록 보호·공백 ID·중복/잘못된 ID·rollback·한국 날짜 경계 8개 시나리오 그룹 통과.
- 미검증·남은 문제: DB 연결·쓰기·임시 DB 생성, API·실제 배치·서비스 재시작·예약 변경 없음. 전체 시험은 재실행하지 않았다. Claude의 전체 686개·실험용 MySQL 17개 통과와 235건 예상은 자신의 독립 결과로 사용하지 않았다. API 페이지 일관성 한계는 직전 검수와 같다.
- 다음 단계: 10/1 09:00 배치 뒤 로그와 import_runs.report.closed_missing으로 실제 반영 건수 확인. Git 스테이징·커밋·push는 하지 않았다.

### 2026-09-30 · Claude · K-Startup 모집 종료 Codex 보류 반영

- 요청·목적: [Codex 검수](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_20260930.md) 보류(P1 1·P2 2) 확인. 10/1 배치 전에 반영한다(사용자 요청: 검수 확인).
- 확인: 세 지적 모두 코드에서 재확인했다.
  - `close_missing`에 `stamp`·`run_id`가 없었다.
  - `is_complete`·`kstartup_listed`는 `str(pbanc_sn)`인데 저장은 `normalize.text`를 거쳤다.
  - `connect()`의 세션 시간대가 `+00:00`이다.
- 변경 파일
  - `shared/store_mysql.py`: `close_missing(cursor, listed, stamp, run_id)`. SELECT `snapshot_at < stamp`, UPDATE에 `snapshot_at`·`last_import_id`를 더했다.
  - `collect/daily_job.py`: `listed_id()`(`normalize.text`)를 추가했고 `is_complete`가 이를 쓴다.
  - `collect/daily_pipeline.py`: `kstartup_listed`가 `listed_id`를 쓴다.
  - 테스트: `tests/test_store_mysql.py`(가짜 커서 6개로 개편, 통합 2개 추가), `tests/test_pipeline.py`(2개).
  - 문서: `docs/guides/TEAM_DATA.md`(한국 날짜 SQL), `docs/guides/QUERIES.md`, `docs/FLOW.md`.
- 검증: 전체 unittest 686개 통과(건너뜀 16). 실험용 MySQL 통합 `tests.test_store_mysql` 17개 통과, 임시 DB 삭제 확인.
- 다음 단계: [응답·재검수 요청](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_RESPONSE_20260930.md) → Codex 재검수. 10/1 배치 뒤 닫은 건수 확인.

### 2026-09-30 · Codex · K-Startup 모집 종료 처리 검수

- 요청·목적: 사용자가 Claude의 검수를 요청해 [K-Startup 요청서](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_REQUEST_20260930.md)의 미커밋 변경을 검토했다. 코드·DB 수정 없이 지적만 남겼다.
- 변경 파일: [검수 결과](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_20260930.md), STATUS의 자신의 항목, 이 WORKLOG, 문서 지도에 결과 링크. 기존 Claude 변경과 스테이징은 보존했다.
- 결과: **보류(P1 1·P2 2)**. close_missing이 snapshot_at을 확인·갱신하지 않아 과거 재적재가 닫힌 공고를 열고 과거 목록이 최신 공고를 닫는다. 원본 ID의 str()와 저장 ID의 normalize.text() 불일치로 공백 ID를 잘못 닫는다. TEAM_DATA의 CURDATE()는 UTC 세션에서 한국 날짜와 어긋난다.
- 검증: 번들 Python + 프로젝트 가상환경 패키지, 바이트코드 생성 방지·MYSQL_INTEGRATION_TEST=0. test_pipeline.py·test_store_mysql.py 29개 실행, 실패·오류 0·건너뜀 4. 표준입력 스크립트로 실제 함수와 메모리 SQL 대역을 연결해 시간 순서 반례 2개·공백 ID·rollback·matchCount/totalCount 분기를 확인했다. 로컬 원본 242행의 ID 변환 차이 0. 전체 테스트·실제 DB 통합 시험은 수행하지 않았다.
- 미검증·남은 문제: 공용 DB 235건 영향은 Claude의 기록이며 이번에 재집계하지 않았다. API 호출, 실제 배치·서비스 재시작, DB 쓰기·임시 DB 생성은 하지 않았다. 다음 예약 배치를 중지하지 않았다.
- 다음 단계: Claude 수정 뒤 재검수. 10/1 09:00 배치 전 반영 여부 확인.

### 2026-09-30 · Claude · 매칭 개선 후보 A·B·C 스위치 — 판정 전 첫 측정, 꾸러미 448쌍으로 확장

- 요청·목적: 사용자 요청으로 실패 분석에서 나온 후보를 평가 스위치로 만들었다. 서비스 코드(`search/app.py`)는 바꾸지 않았다.
- 변경 파일
  - `eval/match_variants.py`(신규): 서비스 `match()` 최종 순위를 그대로 쓰고 스위치만 바꾼다. 9/21 질의 구성 비교의 Codex P1(검색 단계만 잼)을 피하려는 것이다.
    - A: BM25 질의를 아이디어 + `applicant.query_extras`로 줄인다. `STATE['bm25']`를 감싼다.
    - B05/B07: 서비스 `Weights.bm25`.
    - C: 제목 계열(첫 '사업'까지, 8자 미만은 안 묶음)이 같은 공고는 첫 건만 제자리에 두고 나머지는 끝으로 보낸다.
    - 개발용(train 35)·시험용(test 17)·전체 58로 나눠 base 대비 짝 차이와 95% 구간을 낸다. `--extra-qrels`로 Codex 판정을 덧붙일 수 있다(기존 판정은 덮지 않는다).
  - `tests/test_match_variants.py`(신규 8개).
  - `eval/relevance_label_pack.py`: 후보 비교 결과의 빈칸도 넣게 했다.
- 첫 측정: [reports/match_variants_20260930T010314Z](../reports/match_variants_20260930T010314Z/summary.md). 판정 1,617쌍, OpenAI 0, DB 쓰기 0.
  - 개발용 P@3(2) 하한은 base 0.667, A 0.638, B05 0.695, B07 0.667, C 0.667이다. **모든 차이의 95% 구간이 0을 걸친다.**
  - A는 미판정@10을 0.289에서 0.371로 올린다(새 공고를 올림). 그래서 하한은 내려가고 상한은 오른다. **판정 없이는 결론을 낼 수 없다.**
- 꾸러미 재생성(사용자 확인: Codex에 아직 넘기지 않음): 이전 324쌍을 지우고 **448쌍**(base 빈칸 284 + 후보가 새로 올린 빈칸 124 + 사람 대조 40)으로 다시 만들었다. 지시서 숫자를 고쳤다.
- 검증: 전체 unittest 681개 통과(건너뜀 14).
- 다음 단계: Codex 판정 → `relevance_label_score` → `match_variants --extra-qrels …/codex_qrels.jsonl`로 다시 잰다. 개발용으로 고르고 시험용으로 확인한다.

### 2026-09-30 · Claude · 매칭 성능 작업 시작 — 평가 빈칸 판정 꾸러미, 실패 분석

- 요청·목적: 사용자가 매칭 성능 개선에 집중하기로 했다. 결정(사용자): ① 평가 빈칸 채우기(Codex 판정)와 ② 실패 질의 분석을 같이 한다.
- ① 꾸러미
  - `eval/relevance_label_pack.py`(신규)로 `reports/relevance_label_pack_20260930/`을 만들었다. 9/28 평가의 지금 방식 hybrid·dense 상위 10 중 미판정 **284쌍**과 사람 판정 대조군 **40쌍**(2·1·0 = 14·13·13)을 섞어 324쌍이다.
  - 공고 설명은 `common.notice_text()`(LLM 판정과 같은 형식)로 만들었고, 공용 DB는 조회만 했다.
  - 채점은 `eval/relevance_label_score.py`(신규)가 한다. 형식 검사, 대조군 일치율·가중 카파, `codex_qrels.jsonl` 후보를 만든다. `qrels.jsonl`은 고치지 않는다. 임시 사본으로 시험했다(대조군 정답 입력 시 1.00).
  - 지시서: [RELEVANCE_LABEL_TASK_20260930.md](reviews/matching/RELEVANCE_LABEL_TASK_20260930.md).
- ② 분석: [reports/match_miss_analysis_20260930/summary.md](../reports/match_miss_analysis_20260930/summary.md)
  - 조건: `filter_first_eval`과 같다(9/15, 58질의). 서비스 `match()` 상위 50을 봤다.
  - 알려진 정답 725건 중 상위 10은 261, **11~50위 292**, 50위 밖 16, 필터로 빠짐 139, 말뭉치 밖 17이다.
  - 상위 10에서 BM25만 올린 칸은 판정분 중 정답 47%, 둘 다 올린 칸은 70%다.
  - 원인 세 가지: BM25가 질의의 곁가지 단어(팀 경력·"창업 N년차 법인")에 걸린다, 비슷한 공고가 상위를 채운다(27/580칸), 안내글이 올라온다.
- 코드 변경: 서비스 코드는 바꾸지 않았다. 새 파일은 `eval/` 스크립트 두 개뿐이다.
- 다음 단계: Codex 판정 → 채점 → qrels 합칠지 사용자 결정. 개선 후보(BM25 질의 줄이기, RRF 가중치, 비슷한 공고 묶기)는 개발용 40질의로 고치고 시험용 20질의로 확인한다.

### 2026-09-30 · Claude · Codex 조율 설명서 4차 재검수 승인 확인

- [Codex 결과](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK4_20260930.md): 요청 범위 승인, 직전 P2 닫음, 추가 P1·P2·P3 없음. 설명서를 조율 담당에게 넘겨 계약 합의를 진행해도 된다는 뜻이다(실제 공급·화면 표시는 미검증).
- Codex 독립 실행: 프로브 D·A·B·C 통과(공고 2,603건, 준비 27.1초, G-01 13,015회 차이 0), `test_judgments_source.py` 37개 통과. 줄 번호 링크 19개·코드 블록 3개 대조 일치. Codex는 결과 문서 외 파일을 바꾸지 않았다.
- K-Startup 모집 종료 처리 검수 결과는 아직 없다(요청서 09:42 최종 수정, Codex 결과 09:39). 10/1 배치 전에 받는 것이 좋다.

### 2026-09-30 · Claude · K-Startup 모집 종료 처리, Codex 요청서 2건

- 요청·목적: 사용자 승인으로 (1) 조율 설명서 4차 개정의 Codex 최종 확인 요청서, (2) K-Startup 조기 마감 수정. 조사는 보조 에이전트 1개(읽기 전용)로 하고, 판단에 쓰는 핵심 줄(`gate.py:243-247`, `fetch.py:36-58`, `QUERIES.md:108`)은 Claude가 직접 확인했다.
- 작업 전 상태: 입력에 없는 공고를 건드리는 코드가 없었다(`DELETE` 없음은 의도). 수집기는 받은 건수가 서버 보고보다 적어도 통과시켰다(`fetch_all`은 빈 쪽에서 멈춤, `validate`는 50%만 봄). 파이프라인은 K 수집이 실패해도 어제 `notices.json`을 저장했고, 저장 단계는 그것을 구별하지 못했다.
- 사용자 결정: A안(기존 칸에 `closed`). B안(목록에서 본 날짜 칸 추가, DDL)은 택하지 않았다.
- 변경 파일
  - `collect/daily_job.py`: `is_complete()` — 행 수와 고유 `pbanc_sn` 수가 모두 `total`과 같아야 True. `complete`를 파일·로그·dry-run 결과에 넣는다. 수집·교체 동작은 그대로다.
  - `collect/daily_pipeline.py`: `kstartup_listed()` — `status == 'ok'`이고 `complete`일 때만 방금 쓴 `notices.json`에서 번호 집합을 꺼낸다(파일의 `complete`·`reported_total`도 재확인). `store(..., listed)`. 진행 줄·요약·로그(`sources.kstartup.complete`).
  - `shared/store_mysql.py`: `missing_open()`·`close_missing()`, `store_payload(..., listed=None)` — upsert 뒤 같은 트랜잭션, `open` 행을 `FOR UPDATE`로 읽어 목록에 없는 것만 500건씩 `closed`. 결과 `closed_missing`, `import_runs.report.closed_missing`.
  - 테스트: `tests/test_store_mysql.py`(가짜 커서 4, 임시 DB 통합 1 — 기본 건너뜀), `tests/test_pipeline.py`(목록 넘김 조건 4, `is_complete` 경계 1).
  - 문서: `docs/FLOW.md` 4단계, `guides/QUERIES.md`, `guides/FIELD_MAP.md`, `guides/TEAM_DATA.md`(주의 표·목록 화면 예시 SQL), `db/mysql_schema.sql` 칸 주석(파일만, 공용 DB ALTER 없음), `share/테이블구조.html`(게시본 2판).
- 전후 차이: 같은 입력에서 달라지는 것은 K-Startup을 오늘 빠짐없이 받은 날의 저장 결과뿐이다. 목록에 없는 `open` K-Startup 공고가 `closed`가 된다. 목록에 다시 나오면 upsert가 `open`으로 되돌린다. 매칭 필터는 원래 `closed`를 뺀다.
- 선택 이유: 가드는 "오늘 받은 목록 = 서버 보고 건수(고유 번호 기준)" 하나로 충분하다고 봤다. 비율 상한을 두면 첫날 235건(49%)이 막힌다. 목록은 정규화 결과가 아니라 원본 번호에서 꺼내서, 정규화 거부 행이 잘못 닫히지 않는다.
- 검증: 전체 unittest 673개 통과(건너뜀 14). 공용 DB 조회로 첫날 영향 235건(마감일 지남 230 · 9/30 마감 5 — 175808·176937·178706·179096·179204).
- 조율 설명서: [응답·재검수 요청](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK3_RESPONSE_20260930.md). 9/30 데이터 2,603건으로 `orchestration_probe` D·A·B·C 통과(필터 통과 1,637, G-01 2,603×5 차이 0, C′ 실패 검출), 줄 번호 대조 일치.
- 통합 시험(사용자 승인, 같은 날 추가): 공용 서버는 팀 계정에 `CREATE DATABASE` 권한이 없어 시작 단계에서 실패했다(생성된 것 없음). 이 PC 실험용 MySQL(`SQL_LAB_*`)로 접속 대상을 바꿔 `tests.test_store_mysql` 13개 통과, 임시 DB 삭제 확인(`sbrain_test_%` 0개).
- 미검증·남은 문제: 공용 서버에서의 통합 시험(권한 없음). 실제 배치 첫 실행은 10/1. 8000 재시작 전까지 서비스는 옛 상태를 쓴다. EC2 Chroma의 `status` 메타데이터는 옛 값으로 남는다(거르는 코드 없음).
- 다음 단계: Codex 검수 2건([K-Startup](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_REQUEST_20260930.md), 조율 설명서). 10/1 배치 뒤 닫은 건수 확인.

### 2026-09-30 · Claude · 오늘 새 공고·수정 공고 집계, 공고 테이블 구조 페이지

- 요청·목적: 오늘 몇 건이 새로 왔고 몇 건이 수정됐는지 확인, 공고 관련 테이블 구조를 보기 쉽게(사용자 요청). 공용 DB는 SELECT만, 코드 변경 없음.
- 집계 방법: `notices.updated_at`은 쓸 수 없다. 4단계가 목록의 공고를 매일 모두 다시 저장해 9/30에 1,777행 전부 오늘 시각이다. 그래서 9/29·9/30 정규화 파일(`data/normalized/notices_20260929T000004664297Z.json`, `…20260930T000005328225Z.json`)을 공고 ID로 비교했다(`raw`·`issues` 제외).
- 결과
  - **새 공고 78건**(기업마당 40 · K-Startup 38). DB `created_at` 기준과 같다.
  - **내용이 바뀐 공고 1건**: `bizinfo:PBLN_000000000126760` — 제목에 "수정 공고", 첨부 hwpx → pdf 교체, API 수정 시각 9/23 → 9/29.
  - 원본(`raw`)만 바뀐 것은 조회수(`inqireCo`)·목록 총수(`totCnt`) 1,494건, K-Startup 목록 순번(`id`) 204건으로 내용 변경이 아니다.
  - 어제 목록에 있다가 빠진 공고 29건: 마감일 지남 26(기업마당 19 · K-Startup 7), **마감일이 오늘(9/30)인데 빠진 K-Startup 3건**(178706·179096·179204). DB에서는 셋 다 `open`이다. 인계서 4절 "K-Startup 조기 마감"의 실제 사례다.
  - 참고: DB에서 `open`인데 마감일이 지난 K-Startup 공고 230건, `apply_end` 없음 992건.
- 페이지: [공고 DB 테이블 구조](https://claude.ai/artifact/5iu7oSKGHENt3hdbcgtiLL)(비공개), 원본 `share/테이블구조.html`. 표 8개 관계도(SVG), 배치 13단계별 쓰는 곳과 9/30 건수, 알아 둘 것 7개, 표마다 칸 목록(DB 주석 그대로). 칸 목록은 `information_schema`에서 뽑아 넣었고, 페이지 만드는 스크립트는 저장소 밖 임시 폴더에 있다.
- 새로 확인한 사실: 첨부 표 3개와 `notice_conditions`에는 기업마당 공고만 있다(K-Startup은 `pending_crawl`). 본문 추출은 `role = notice` 첨부만. `attachment_files` 중 지금 본문 행과 이어지지 않는 파일 178개. 공용 DB 표는 42개이고 다른 팀 표 3개(`projects`·`match_candidates`·`notice_alerts`)가 `notices.notice_id`를 FK로 참조한다.
- 검증: 관계도 글자가 상자·그림 밖으로 나가는지 브라우저에서 계산으로 확인(1건 고친 뒤 0건). 비밀값·서버 주소 없음.

### 2026-09-30 · Claude · 9/30 매일 배치 점검 — 판정표 지문 수정 뒤 첫 배치

- 요청·목적: 판정표 지문 수정(9/29 Codex 승인) 뒤 첫 배치에서 재판정·업로드가 예상대로 됐는지 확인(사용자 요청). 코드·DB 변경 없음, 공용 DB는 SELECT만.
- 배치: 09:00:02 시작 → 09:13:44 `exit=0`(819.8초, 어제 723초). 경고 없음. K-Startup 신규 38건(어제 4건), 공고 2,525 → **2,603건**, 임베딩 새로 79건(신규 78 + 내용 바뀐 기존 1), 벡터 79건 한 묶음 업로드(100건 이하라 EC2 색인 누락 위험 해당 없음), 첨부 파일 41개 15.9MB.
- 10·11·12단계 재판정: 세 단계 모두 **예상한 5건(125813·126284·126490·126496·126545) + 126760**을 다시 판정했다. 126760은 9/27 공고로 오늘 00:07(UTC) 내용이 바뀌어 지문이 달라진 것이다(임베딩 "그대로 2524건"과 맞음). 11단계 84건 $0.0598, 12단계 84건 $0.0780, 10단계 46건(입력 195,481·출력 4,907 토큰), 실패 0.
- 13단계: 신청자 유형 새로 78·**바뀜 8**(재판정 6 + A안 126586·126651) · 올림 86, 업종 새로 78·바뀜 6 · 올림 84. `--plan` 예상 "바뀜 3"(126490·126586·126651)은 결론 칸 기준이고, 바뀜 8은 지문이 바뀐 재판정 행까지 센 행 기준이다.
- 결론 칸(`pre_founder_verdict`): 126490 `blocked`(재판정 뒤 `not_allowed strong`, 근거 문장이 지금 공고문에 있음 확인), 126586·126651 NULL(발췌 밖 '예비창업' 언급 → 확인 필요, A안대로).
- 검증(읽기만)
  - `load_auto(공용 DB)`: 지문 같은 판정 **2,603건(DB 2,603 · 파일 0) · 지문 다름 0 · 공고문 없음 0** · 발췌 밖 확인 필요 2 · 확인 못 함 0 · error 없음.
  - `collect.upload_judgments --plan`: 두 표 모두 새로 0 · 바뀜 0 · 같음 2,603(DB·파일 일치).
  - 확인 스크립트는 저장소 밖 임시 폴더에서 돌렸다(`updated_at >= 오늘 00:00 UTC AND uploaded_at/created_at < 오늘`로 기존 공고 재판정만 골라냄).
- 미검증·남은 문제: 8000·8010은 꺼져 있어 서비스 `/api/health`는 보지 않았다. 켜면 오늘 공고 2,603건을 읽는다.
- 다음 단계: 판정표 지문 수정 건은 끝. 남은 일은 인계서 4절(조율 담당 합의, 코드 과제, 작은 후속).

### 2026-09-29 · Claude · 조율 설명서 줄 번호 맞추기

- 요청·목적: 판정표 수정 검수가 끝나 미뤄 둔 `guides/ORCHESTRATION_HANDOFF.md`의 `search/app.py` 줄 번호를 맞췄다(사용자 요청).
- 변경: `match` 372→387, `MatchRequest` 279→294, `eligibility` 813→828, `GateRequest` 333→348, 업력 설명 구간 844-870→859-885. `boot` 108·`FIELDS` 47·`collection_status.check` 133과 조율 쪽 파일 번호는 그대로 맞았다. 3.3절 5번에 승인된 동작 두 줄(0건·예외 시 기능만 끔, 발췌 밖 '예비창업' 언급이면 확인 필요)을 보탰다. 함수 이름·입출력은 바뀌지 않았다.
- 검증: 새 번호 8곳을 `sed`로 열어 각 줄이 해당 정의인지 확인했다. 문서 링크 점검 깨진 링크 0.

### 2026-09-29 · Claude · 판정표 지문 수정 Codex 승인 확인

- [Codex 4차 재검수](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK3_20260929.md) 결과 **승인**을 확인했다(코드 수정 없음). 첨부 경계 반례 서비스 None·13단계 NULL, 전체 unittest 663개 통과, 공용 DB SELECT 결과(신선 2,520·다름 5·발췌 밖 2·확인 불가 0, `--plan` 바뀜 3)가 Claude 측정과 같다.
- 9/28 판정표 P1부터 이어진 지문 신선도 검수(요청 → 보류 → 1차·2차·3차 응답)가 끝났다. 남은 것: 9/30 배치 실제 재판정·업로드 확인, 조율 설명서 줄 번호.

### 2026-09-29 · Claude · Codex 3차 재검수 — 발췌 조각별 횟수

- 요청·목적: [Codex 3차 재검수](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK2_20260929.md) 보류(P1 1). 사용자가 추천 방향으로 진행하라고 했다.
- 원인: `build_document()`가 첨부 조각을 빈 줄로 잇는데, 발췌 전체의 공백을 지우고 세면 첨부 경계 "예비"+"창업"이 붙어 원문에 없는 언급 1회가 생긴다. Claude가 Codex 입력으로 재현했다(지문 같음, 감지 None).
- 변경 파일: `search/applicant_types.py`(`unread_pre_founder()` — 발췌를 `\n\n`(빈 줄)으로 나눈 조각마다 세서 더함, 문장 고르기도 조각 사이 `|`). 테스트: `tests/test_judgments_source.py`(Codex 반례, 경계만 있으면 blocked 유지, 조각이 두 출처를 잇지 않는다는 전제), `tests/test_upload_judgments.py`(같은 반례로 13단계 NULL). 문서: `guides/JUDGMENT_TABLES.md`, [3차 응답·재검수 요청](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK2_RESPONSE_20260929.md).
- 선택 이유: 발췌에 구분 글자를 넣으면 지문 2,525건이 모두 바뀌어 전량 재판정이 된다. 조각별 세기는 발췌 함수를 그대로 두고, 나누기가 틀려도 발췌 횟수가 줄어드는 쪽(확인 필요)이다.
- 검증: 사전 집계(SELECT만) 같은 2건·경계 가짜 언급 0건. unittest 663개 통과(건너뜀 13). load_auto 발췌 밖 2·확인 못 함 0, `upload_judgments --plan` 바뀜 3, probe D·A·B·C 통과.
- 미검증·남은 문제: 8000 재시작 안 함(사용자 확인 필요).
- 다음 단계: Codex 재검수 결과(`JUDGMENT_FRESHNESS_REVIEW_RECHECK3_20260929.md`).

### 2026-09-29 · Claude · Codex 2차 재검수 — A안 횟수 비교와 확인 못 한 불가 미사용

- 요청·목적: [Codex 2차 재검수](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK_20260929.md) 보류(P1 1·P2 1). 사용자가 설명을 듣고 Claude 추천 방향으로 진행하라고 했다.
- 재현(Claude, DB 없음): 반복 문구 → 지문 같고 `unread_pre_founder` None. `예비\n창업`은 잡지만 `예비창\n업`·`예비 창 업`은 못 잡음.
- 선택 이유: 위치 추적(발췌 함수가 자른 구간 기록)은 10·11·12단계 공용 함수를 건드려 지문 전체가 흔들릴 위험이 있고, 발췌가 원문을 다 못 담은 공고의 불가를 모두 푸는 방식은 정확한 불가(Codex 30/30)까지 버린다. 횟수 비교는 발췌 ⊂ 원문이라 "원문 > 발췌"가 안 읽은 언급의 확실한 증거이고, 틀려도 확인 필요 쪽이다.
- 변경 파일
  - `search/applicant_types.py`: `unread_pre_founder()` 횟수 비교(보여 줄 문장은 앞뒤까지 발췌에 없는 첫 언급, 없으면 마지막), 언급 찾기 정규식 `예\s*비\s*창\s*업`. `mark_unread()`는 원문 없음·지문 다름이면 `unverified_pre_founder`. `load_auto()`는 항상 `mark_unread()`, 결과에 `unverified_pre_founder`. `pre_founder()`·`type_check()`.
  - `collect/upload_judgments.py`: `type_rows()`도 항상 확인(원문 없음·지문 다름 → strong 불가 NULL).
  - `search/app.py`: health `unverified_pre_founder`.
  - 테스트: `tests/test_judgments_source.py`(반례 3개 + 모두 읽은 반복 + `current`만 넘긴 호출, 도우미가 빈 원문을 함께 넘김), `tests/test_upload_judgments.py`(기본 공고문 대역, 확인 못 함 → NULL).
  - 문서: `guides/JUDGMENT_TABLES.md`, [2차 응답·재검수 요청](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK_RESPONSE_20260929.md).
- 검증: 사전 집계(SELECT만) 횟수 방식도 같은 2건. unittest 659개 통과(건너뜀 13). load_auto 2.1초·발췌 밖 2·확인 못 함 0. `upload_judgments --plan` 신청자 유형 바뀜 3(126490 포함 — 재판정 전까지 DB 결론도 NULL). probe D·A·B·C 통과.
- 미검증·남은 문제: 8000 재시작 안 함(사용자 확인 필요). '예비창업' 말이 없는 자격 변경은 범위 밖.
- 다음 단계: Codex 재검수 결과(`JUDGMENT_FRESHNESS_REVIEW_RECHECK2_20260929.md`).

### 2026-09-29 · Claude · Codex 지문 재검수 나머지 6건(P1-1·P1-3·P1-4·P2 3건)

- 요청·목적: 사용자가 8000 재시작과 나머지 지적 진행을 요청했다(파일 모드 무검사 경로 제거·비활성 첨부로 인한 재판정 포함).
- 사전 집계(SELECT만): 비활성인데 본문이 있는 첨부 7개·공고 6건. 활성 첨부의 같은 공고·같은 길이 동률 0건.
- 변경 파일
  - `experiments/sql_semantic/applicant_type_llm.py`(`load_population`), `collect/extract_conditions.py`(`pick_targets` 두 조회), `experiments/sql_semantic/industry_llm_sample.py`(`load_items_shared`·`load_items`): 첨부 `na.active`, `ORDER BY text_chars DESC, na.id`.
  - `search/applicant_types.py`: `load()`는 공고 ID가 빈 값·문자열 아님이면 깨진 줄로 세고 삽입도 줄 단위 `try` 안에서. `load_auto()`는 지문(current·documents)을 모든 모드에서 먼저 구하고 그다음 모드별 출처(auto DB→파일, db, file). 쓸 판정 0건이면 `error`에 행 수·지문 다름·공고문 없음.
  - `search/app.py`: `boot()`가 두 판정 읽기를 감싸 예외 시 기능만 끄고 `boot_errors`에 남긴다.
  - `collect/daily_pipeline.py`: `stage_warnings_of` error/failed 뒤에 warning도 따로 남긴다. 종료 메시지는 단계 이름 중복 제거. 종료 코드 4 주석 10~13단계.
  - 테스트: `tests/test_judgments_source.py`(Codex 재현 P1-3 두 개·P1-4·P2-3, file 모드 테스트를 새 규칙으로), `tests/test_applicant_type_daily.py`(P2-2), 새 `tests/test_active_attachments.py`(가짜 연결로 실행 SQL 확인).
  - 문서: `guides/JUDGMENT_TABLES.md` 6절, [응답·재검수 요청](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RESPONSE_20260929.md), 인계서·문서 지도.
- 검증: unittest 654개 통과(건너뜀 13). 공용 DB SELECT만: load_auto 2.1초, 지문 같음 2,520·다름 5(125813·126284·126490·126496·126545 — 126490이 Codex가 짚은 blocked)·확인 필요 2. `--plan`(호출·쓰기 없음): 11단계 5건 약 $0.004, 12단계 5건 약 $0.006, 10단계 5건, 13단계 신청자 유형 바뀜 2·업종 0. `orchestration_probe` D·A·B·C 통과, 필터 통과 1,596. 8000 재시작 두 번(A안 뒤, 이번 수정 뒤) — boot_errors 없음, used 2,520·stale 5·unread 2.
- 미검증·남은 문제: EC2 부팅, 내일 09:00 배치의 재판정·업로드. 13단계는 지문이 달라진 5건의 옛 파일 판정을 재판정 전까지 그대로 올린다(서비스는 쓰지 않음, SQL 사용자는 하루 옛 값을 볼 수 있다).
- 다음 단계: Codex 재검수 결과(`JUDGMENT_FRESHNESS_REVIEW_RECHECK_20260929.md`) 확인.

### 2026-09-29 · Claude · Codex 지문 재검수 P1-2 — A안(발췌 밖 '예비창업' 언급이면 확인 필요)

- 요청·목적: Codex [재검수](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_20260929.md) 보류(P1 4·P2 3). 사용자가 P1-2를 먼저 25건 세어 보고 A안으로 진행하라고 했다.
- 판단: 지문은 LLM이 읽은 발췌의 해시다. 전체 원문 지문으로 바꾸면 변경은 알아채지만, 다시 판정해도 같은 발췌를 읽어 결론이 같다. 그래서 "안 읽은 곳에 해당 말이 있나"를 본다.
- 사전 집계(공용 DB SELECT만, 1.7초): 공고 2,525 · strong 불가 187 · Codex 기준 발췌 밖 글이 있는 불가 25건 중 안 읽은 곳 '예비창업' 0건 · 전체 불가 중 2건.
  - 126586: 제출서류 표 "개인사업자 또는 예비창업자의 경우 해당사항 없음" — 예비창업자 신청 여지가 있어 확인 필요가 맞다.
  - 126651: 작성 양식 "예비창업자 … 노하우 전수" 활동 예시 — 자격과 무관, 낮춰도 추천에 남을 뿐이다.
  - 25건이 0인 이유: 발췌는 자격 구간 주변만 잘라 오므로 한도를 늘려도 안 읽는 곳이 있다. 그래서 원문 전체와 대조했다.
- 변경 파일
  - `search/applicant_types.py`: `current_documents()`(지금 공고문 원문), `unread_pre_founder()`(원문의 '예비창업' 앞뒤 10자가 발췌에 없으면 그 조각), `mark_unread()`(strong 불가·지문 같음일 때만 표시, 원래 표는 안 바꿈). `load_auto(documents=)`, 결과에 `unread_pre_founder` 건수. `pre_founder()`는 표시가 있으면 None, `type_check()`는 "예비창업자 불가로 읽었으나 확인 필요"와 두 문장.
  - `collect/upload_judgments.py`: 13단계도 지금 공고문으로 같은 표시 → `pre_founder_verdict` NULL. 공고문을 못 읽으면 신청자 유형 표는 올리지 않는다(error, 업종은 계속).
  - `search/app.py`: `/api/health` applicant_types에 `unread_pre_founder`.
  - 테스트: `tests/test_judgments_source.py`(A안 6개, Codex 재현 포함, 대역을 `current_documents`로), `tests/test_upload_judgments.py`(4개, 가짜 DB용 대역).
  - 문서: `guides/JUDGMENT_TABLES.md`(`pre_founder_verdict` 설명, 6절).
- 검증: unittest 647개 통과(건너뜀 13). 실제 DB `load_auto` 1.9초, 낮춤 2건. `upload_judgments --plan`: 신청자 유형 바뀜 2·같음 2,523(쓰지 않음). `orchestration_probe` D·A·B·C 통과, G-01과 매칭 1단계 차이 0, 필터 통과 1,594 → 1,595.
- 미검증·남은 문제: 8000 서버는 이후 사용자 요청으로 재시작했다. `share/신청자유형.html`은 게시 당시 스냅샷이라 이 2건이 '불가'로 남아 있다. 나머지 Codex 지적(P1-1·P1-3·P1-4·P2 3건)은 사용자 결정 대기.
- 다음 단계: 남은 지적 수정 → Codex에 같은 경계 입력으로 재검수 요청.

### 2026-09-29 · Claude · 9/29 프로젝트 점검(읽기만)과 문서 정리

- 요청·목적: Codex 검수를 기다리는 동안 프로젝트 전체를 훑어 문제를 찾는다. 이어서 사용자가 문서 정리부터 하라고 했다.
- 점검 방법: 보조 에이전트 3개(코드·문서·보안 설정)가 읽기만 하며 살폈고, Claude가 주요 지적을 코드·파일에서 직접 확인했다.
- 정상 확인: unittest 637개 통과(건너뜀 13). 9/29 09:00 배치 13단계 성공·경고 0·12분·LLM 약 $0.13. 8000 `/api/health` 판정 2,525건 모두 최신. 추적 파일에 비밀번호·API 키 0건, `share/` HTML에 IP·키·개인 경로 없음. 요청값이 SQL에 문자열로 들어가는 곳 없음.
- 문서 정리(이번에 고침)
  - `README.md`: "다섯 단계" → 13단계, "5~11단계만 바뀐 것" → 5~13단계, `reports/`는 git에 올라간다고 정정, 빠진 배치 옵션 5개 추가, 종료 코드 4 = 10~13단계 경고, 테스트 81개 → 637개.
  - `share/build_jev.py` 4행: 설명 줄에 백스페이스 바이트(0x08)가 들어가 `shareuild`로 보이던 것을 옆 파일(`build_filter_first.py`)처럼 역슬래시 두 개로 고쳤다(`SyntaxWarning`도 사라짐).
  - `NEXT_SESSION_HANDOFF_20260929.md`: P1 "멈춤" → 수정 완료·재검수 대기, 점검에서 나온 코드 과제를 4절 4번에 추가, 테스트 수·서버 상태 갱신.
  - 깨진 링크 18개: 보관 폴더로 옮긴 `archive/NEXT_SESSION_HANDOFF_20260928.md`(16개), `WORKLOG.md`(1개), `reviews/integration/CURRENT_PROGRESS_REVIEW_20260928.md`(1개). `reports/search_comparison_20260918*`의 6개는 결과 보존 원칙대로 두었다.
  - `guides/JUDGMENT_TABLES.md`: 이미 연결된 13단계의 "(예정)" 삭제, 업종 파일 위치를 `data/industries/results.jsonl`로, 업종 규칙 파일 경로 명시.
- 검증: 링크 점검 스크립트 재실행 결과 깨진 링크 0개(`reports/` 제외). 고친 파일에 제어 문자 없음. `build_jev.py` 경고 없이 구문 분석됨.
- 미룬 것: Codex 검수 중인 파일과 엮인 곳 — `guides/ORCHESTRATION_HANDOFF.md`의 `search/app.py` 줄 번호(5줄 밀림), `collect/daily_pipeline.py` 종료 코드 4 주석. 검수 뒤 맞춘다.
- 코드 과제(손대지 않음, 인계서 4절 4번): EC2 색인 워터마크 누락 가능성, K-Startup 조기 마감 미반영, 백업에서 LLM 결과 표 누락, `daily_job.py`의 없는 모듈 `match_bge`. 보안: 옛 인계서 `archive/HANDOFF.md`에 DB 3306 "개방"·EC2 주소가 적혀 있다(저장소 공개 여부 확인 필요).
- 문제 아님으로 본 것: EC2 리랭커 API 메모리 위험(EC2에 torch가 없어 모델을 올리기 전에 끝남), PC의 DB 암호화 연결(CA 인증서 검증 방식).

### 2026-09-29 · Claude · 판정표 P1 — 지문(문서 해시)으로 신선도 확인

- 요청·목적: 사용자 — [9/28 재검수](reviews/integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md) P1 세 건 수정(멈춰 둔 작업 재개). 조율 에이전트가 `app.boot()`를 직접 부르게 되어 우선순위가 올라갔다.
- 사전 측정(읽기만)
  - 11단계와 같은 `applicant_type_llm.load_population`으로 지금 공고문 지문을 계산하면 2,525건 1.7초다.
  - 공용 DB 판정 2,525행 모두 지금 지문과 같았다.
  - 모듈 불러오기는 0.11초이고, 모델·API 라이브러리를 불러오지 않는다.
- 사용자 결정: 새 표 없이 지문 대조. 프롬프트 버전은 대조하지 않는다. 업종은 범위 밖.
- 변경 파일
  - `search/applicant_types.py`
    - `load()`는 예외를 내지 않는다(깨진 줄 `bad_lines`, 못 읽으면 error).
    - `current_document_hashes()`, `fresh_only()`를 새로 만들었다.
    - `load_auto()`를 다시 썼다(DB→파일 순서로 지문 같은 것만, 지문 못 구하면 기능 끔, 95% 규칙 삭제). 모듈 설명도 고쳤다.
  - `search/app.py`: boot가 기능 꺼짐을 `boot_errors.applicant_types`에 남긴다. `/api/health`에 `applicant_types`를 추가했다.
  - `collect/upload_judgments.py`: 중복 공고 줄이면 error(올리지 않음). 공고(현재 notices 기준 고유 ID)가 90% 미만이면 warning만 남기고 올린다.
  - `collect/daily_pipeline.py`: `warning` 집계, `stage_warnings_of`가 warning을 인식한다(종료 코드 4).
  - `web/collection_status.html`: 경고 표시.
  - 테스트
    - `tests/test_judgments_source.py`: 신청자 유형 부분을 새 규칙으로 바꾸고 15개로 늘렸다(옛 파일 vs 새 DB, 파일 없는 호스트의 옛 blocked, 깨진 파일, 지문 계산 실패, db·file 모드 등).
    - `tests/test_upload_judgments.py`: 90% 테스트를 경고로 바꾸고, 중복·살아 있는 공고만 세기를 추가했다.
    - `tests/test_applicant_type_daily.py`: warning 경고.
  - 문서: `guides/JUDGMENT_TABLES.md` 6절, `guides/ORCHESTRATION_HANDOFF.md` 3.3(알려진 문제 → 수정됨), `share/전체흐름.html` 두 곳, STATUS.
- 검증
  - 전체 unittest 637개 통과(건너뜀 13).
  - 실제 DB로 별도 프로세스에서 `app.boot()` 21.7초: 판정 2,525건 모두 신선(DB 2,525, 파일 0, 다름 0), `boot_errors` {}.
  - 매칭(예비창업자·반려동물 앱·서울): 필터 통과 1,594, 본문 불가 181, 접수 마감 756, 업력·유형 107, 되살림 9 — 전과 같다.
  - `experiments.orchestration_probe` D·A·B·C 통과, C′ 실패 검출.
- 미검증: Claude 내부 교차 검토 워크플로(권한 검사 일시 오류로 실행 못 함), Linux(EC2)에서의 boot, 실제 배치 13단계 경고 경로(내일 09:00 배치), 켜져 있는 8000 서버(옛 코드 — 재시작 전).
- 다음 단계: 교차 검토 재시도 또는 Codex 재검수. 8000 재시작(사용자 확인). `share/전체흐름.html` 재게시.

### 2026-09-29 · Claude · 8010 결과 화면 5장을 공유 페이지로 게시하고 저장소 share/에 보관

- 요청·목적: 사용자 — 8010 결과를 다른 사람도 보게 한다. 새 서버 대신 결과 페이지로 공유하는 방식을 택했다. 원본은 저장소에 넣는다.
- 만든 것
  - 매칭 방식 비교(Claude 직접 제작)
  - 전체 흐름, 업종 추출 결과, Jev 채점 시험, 신청자 유형 판정: 보조 에이전트 4개가 병렬로 만들었다. 저장소 쓰기는 금지했다.
  - Claude가 게시 전 확인한 것: 비밀정보·IP·금지 태그 없음, 제목. 5장 모두 claude.ai에 **비공개**로 게시했다. 링크는 [share/README.md](../share/README.md)와 STATUS에 있다.
- 변경 파일
  - `share/`(신규): HTML 5, `build_filter_first.py`(신규 — 대화 중 추출 과정을 스크립트화), `build_industry.py`, `build_jev.py`, `build_applicant_types.py`, 틀 3, README
  - `README.md` 폴더 목록 한 줄, STATUS
  - 서비스 코드·DB 변경 없음. 유료 API 없음.
- 전체 흐름: 옛 `web/flow.html`의 틀린 문구(Codex 지적)를 옮기지 않고 9/29 기준으로 새로 썼다. 업력 근거 225(9/28)·226(9/29 시작)은 날짜를 나눠 적었다.
- 검증
  - 그래프 색: 순서형 파랑이 dataviz 검증기에서 밝은·어두운 화면 모두 통과했다.
  - 수치: 에이전트별로 원본과 대조했다(업종 `industry_rank.load()` 174/217, Jev 22개, 신청자 유형 21개 일치).
  - 저장소로 옮긴 스크립트로 다시 만들었다. 업종·Jev·신청자 유형은 게시본과 바이트까지 같다. 매칭 방식 비교는 JSON 항목 순서 하나만 다르다(글자 수 같음).
- 미검증·한계: 결과가 자동 갱신되지 않는다(다시 만들어 다시 게시해야 함). 신청자 유형은 9/28 실행 2,476건 기준이다. 파일을 직접 열 때 한글이 깨지지 않도록 저장소 판 페이지·틀 첫 줄에 `<meta charset="utf-8">`을 더했다(게시본에는 영향 없음).
- 다음 단계: 사용자가 필요한 페이지를 Share 메뉴로 공유하고, `share/`를 커밋한다.

### 2026-09-29 · Claude · Codex 3차 재검수 반영 — 조율 설명서 4차 개정 (SB-189)

- 요청·목적: 사용자 — [Codex 3차 재검수](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK3_20260929.md) 확인·반영.
- 재검수 결과: 앞선 지적은 모두 수정 확인. D·A·B·C 통과, C′ 실패 검출. 남은 P2 하나(⑦ 가·⑩의 입력 연결 범위).
- 확인(읽기만): 조율 `catalog.py:55-58` G-01 입력은 칸별 명시 연결이다. `RunView`(`service.py:42-51`)에는 `gateResult`가 없다. 지적이 맞다.
- 변경 파일: [설명서](guides/ORCHESTRATION_HANDOFF.md)
  - ⑦ 가 행: 모델 + 입력 연결 두 곳
  - ⑦ 표시: `RunView` 경로
  - ⑩ 행: (ㄱ) 확인 필요만 추가·`eligibility_of()` 유지 / (ㄴ) 공급 단순화·필수 칸 변경
  - 4차 개정 기록
  - STATUS
- 코드 블록·검증 스크립트·서비스 코드 변경 없음. 그래서 검증을 다시 돌리지 않았다(직전 D·A·B·C 결과 유효).
- 다음 단계: 설명서 쪽 지적 정리 완료. 조율 담당 합의(①②③⑦) → 실제 공고 공급 통합 시험.

### 2026-09-29 · Codex · 조율 설명서 3차 개정 재검수

- 요청·목적: 사용자의 재검수 요청에 따라 Claude의 [2차 재검수 응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_RESPONSE_20260929.md), 설명서 3차 개정과 검증 스크립트를 확인했다.
- 작업 전 상태: Claude 변경은 미커밋·일부 스테이징 상태. 기존 변경과 스테이징을 보존했다.
- 변경 파일: [재검수 결과](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK3_20260929.md), 이 WORKLOG, [STATUS](STATUS.md), [문서 지도](README.md). 서비스 코드·DB·Claude 설명서·프로브는 수정하지 않았다.
- 결과: 앞선 P2 두 건과 P3 문구 보완 확인. C는 더 보기 새 결과 버전·11~20위·실패 알림 부재를 판정하고 C′가 시간 초과를 실패로 검출한다. 기간 유형의 두 모델 추가 계약과 확인 필요 이유 선택도 적혔다. 추가 P2는 ⑦ 가 방식·⑩의 공고 ID 입력 연결과 필수 자격 필드 변경 범위 누락이다.
- 검증: 번들 Python 3.12 + 기존 `.venv` 패키지로 `orchestration_probe` 독립 재실행. D·A·B·C 통과, 종료 코드 0; 공고 2,525건 × 5입력 G-01 차이 0. C 정상은 후보 버전 2·11~20위·알림 없음, C′ 타임아웃은 버전 1·1~10위·`X-C2-FAIL`로 실패 검출. 별도 DB 없는 대역 시험에서 C/C′·A·D 정상·0건 분기 확인. 편집 파일 제어문자 0, `git diff --check`·`git diff --cached --check` 통과. 공용 DB는 SELECT만 실행했다.
- 미검증·남은 문제: Linux, 실제 공고 공급, 확인 필요 화면, 동시 요청·재시작, 사람 기준 신청 가능 여부. 조율 담당과 ①②③⑦ 계약 합의가 필요하다. 판정표 P1은 사용자 지시대로 멈춘 상태다.
- 다음 단계: Claude가 ⑩의 입력 바인딩·자격 필드 범위를 문서에 보완하고 실제 공급 함수로 통합 시험한다.

### 2026-09-29 · Claude · Codex 2차 재검수 반영 — 조율 설명서 3차 개정 (SB-189)

- 요청·목적: 사용자 — [Codex 2차 재검수](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_20260929.md) 확인·반영.
- 변경 파일:
  - `experiments/orchestration_probe.py`
    - C를 `_run_flow()`로 나눴다. 검사 여섯 가지 + C′(offset 10 `TimeoutError` 주입)가 실패를 잡는지 확인한다.
    - A는 순위를 정확히 비교한다. D는 계약·참고를 나눴다.
  - [설명서](guides/ORCHESTRATION_HANDOFF.md)
    - ① `apply_period_type` 두 모델 추가 계약
    - ⑦ `{condition, reason}` 목록(권장)
    - 3.1·7절 `.venv` 재생성 안내, 5절 표 C, 3차 개정 기록
  - [STATUS](STATUS.md): 24·26행 `\a`→BEL 복구
  - [2차 응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_RESPONSE_20260929.md)(신규), 문서 지도(Codex가 고친 행에 응답 링크만 추가), 인계서
- 확인:
  - STATUS BEL은 사실이었다. 파이썬 스크립트로 고치다 생긴 Claude의 실수다.
  - `.venv` 실행 불가는 Codex 환경 한정이다. 이 PC는 `pyvenv.cfg` home이 있고 3.12.10으로 실행된다.
- 검증: `python -m experiments.orchestration_probe --sbrain ..\agent-orchestration` → D·A·B·C 통과, 종료 코드 0.
  - C: 결과 버전 2, 11위부터, 알림 없음.
  - C′: 결과 버전 1, 1위부터, `X-C2-FAIL` → 세 검사가 어긋나 **실패로 검출**.
  - 편집한 문서 7개에서 제어문자 0.
- 다음 단계: 조율 담당 합의(①②③⑦) → 실제 공고 공급 통합 시험.

### 2026-09-29 · Codex · 조율 설명서 2차 개정 재검수

- 요청·목적: 사용자 검토 요청에 따라 Claude의 [재검수 응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_RESPONSE_20260929.md), 설명서 2차 개정과 프로브를 실제 조율 계약·흐름에 대조했다.
- 작업 전 상태: Claude 변경은 미커밋·일부 스테이징 상태였다. 서비스 코드·DB는 바뀌지 않았다. 기존 변경을 보존했다.
- 변경 파일: [이번 재검수 결과](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_20260929.md), 이 WORKLOG, [STATUS](STATUS.md), [문서 지도](README.md). Claude의 설명서·프로브와 서비스 코드·DB·Git 스테이징은 수정하지 않았다.
- 결과: 앞선 P2 네 건의 설명서 반영은 확인했다. 새 P2는 프로브 C의 더 보기 실패 거짓 통과와 날짜 없는 공고의 기간 유형 전달 계약 누락이다. 확인 필요 이유의 전달 범위, STATUS 경로 제어문자, 검증 명령의 깨진 가상환경, D의 정상·0건 판정도 기록했다.
- 검증: 번들 Python 3.12 + 기존 `.venv` 패키지로 `orchestration_probe` 독립 재실행. D·A·B·C 통과, 종료 코드 0; 공고 2,525건, B 5입력 차이 0. 별도 DB 없는 MORE `TimeoutError` 주입에서 C가 더 보기를 1위부터 10건으로 잘못 출력하고 `True`를 반환했다. `git diff --check`·`git diff --cached --check` 통과. DB 조회는 SELECT만 실행, 유료 API 호출 없음.
- 미검증·남은 문제: Linux, 실제 `Announcement` 공급, 확인 필요 화면, 동시 요청·재시작, 사람 기준 신청 가능 여부. 조율 담당과 ①②③⑦ 계약 합의가 필요하다. 판정표 P1은 사용자 지시대로 멈춘 상태다.
- 다음 단계: Claude가 프로브 판정과 문서 계약을 보완한 뒤 실제 공고 공급으로 통합 시험한다.

### 2026-09-29 · Claude · Codex 재검수 P2 반영 — 조율 설명서 2차 개정 (SB-189)

- 요청·목적: 사용자 — [재검수](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_20260929.md) P2 네 건 반영.
- 변경 파일:
  - [설명서](guides/ORCHESTRATION_HANDOFF.md)
  - `experiments/orchestration_probe.py`: D·A 대역 검사, 거짓 통과 제거, 안내·절 번호, 도움말 `\a` 이스케이프
  - [재검수 응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_RESPONSE_20260929.md)(신규), 문서 지도, STATUS
  - 서비스 코드·DB 변경 없음.
- 전후 차이:
  - 빠른 시작이 `recommend()`가 됐다. "정상"이 아니면 `(status, [])`, 0건이면 안내한다.
  - `tc2()`는 **첫 조회에서만** 비정상 수집 시 빈 카드를 준다.
  - ⑦에 가·나 방식과 규모를 넣었다. SELECT 집계로 고를 수 있는 공고 기준, 접수기간 제외: 예비창업자 1,492/1,594, 법인 1,757/1,757, 개인사업자 설립일 없음 1,769/1,769.
  - 4.5 재사용 표: `c.get('설명') or c['요구']`, 접수 예정은 `start is not None and start > 오늘`.
  - ①에 필수 칸 세 곳과 `isoformat()` 사용처를 넣었다. 3.3에 재시작 두 방식을 넣었다.
  - 6절 ⑧에 "더 보기는 상태를 보지 않음"을 넣었다.
- 내부 교차 검토:
  - Workflow `handoff-p2-review`(에이전트 16, 약 8분, 읽기 전용). 구성은 검토자 3명(코드·계약·스크립트) + 지적별 반박 검증이다.
  - 13건 중 8건 확인(중복 제외 6건), 5건 기각. 상세는 응답 2절.
  - 핵심은 C3이다. 조율 `service.py:103`은 start_run에서만 수집 상태를 본다. MORE 구간(`sbrain_flow.py:196`)은 보지 않는다. 그래서 첫판 분기대로면 더 보기에서 안내 없이 0건이 되고 `more_used`만 소진된다.
- 검증:
  - `python -m experiments.orchestration_probe --sbrain ..\agent-orchestration` → D·A·B·C 통과, 종료 코드 0.
    - A: 지연 첫 조회 0건, 지연 더 보기 10건.
    - B: 5가지 경우 다름 0.
  - 4.5 예시 블록을 설명서에서 꺼내 실행했다: `[('모집 상태', '모집 상태 정보 없음')]`. 2,525건 × 개인사업자에서 목록·판단식 오류 0.
- 다음 단계: Codex 재검수, 조율 담당 합의(①②③⑦ — ⑦은 가·나 선택 포함).

### 2026-09-29 · Claude · 오전 작업 마무리와 인계

- 요청·목적: 사용자 — 작업을 마무리한다. PR #10 머지 뒤 `feature/SB-46-data-collection` 브랜치를 지울 예정이다.
- 확인(읽기만):
  - 로컬 HEAD `7e5e83f` = `origin/feature/SB-46-data-collection`(앞/뒤 0).
  - `origin/main`이 HEAD를 포함한다(PR #10 merge `7ab629c`). 작업 트리에 data-collection 미커밋 변경 없음. 루트 `.claude/`·`.idea/`만 미추적.
  - main의 `agent-orchestration/`은 검증 기준 `deb5c81`과 차이 0.
- 변경 파일:
  - [NEXT_SESSION_HANDOFF_20260929.md](NEXT_SESSION_HANDOFF_20260929.md) 신규
  - 9/28 인계서를 `archive/`로 이동(파일 이동만, 스테이징은 되돌림)
  - [문서 지도](README.md) 1·2절 링크, [STATUS](STATUS.md)
- 그 밖: 미리보기 서버 8000·8010 종료.
- 다음 단계: 새 인계서 4절(사용자가 순서 결정).

### 2026-09-29 · Codex · 조율 함수 설명서 개정 재검수

- 요청·목적: 사용자 재검수 요청에 따라 Claude의 [응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RESPONSE_20260929.md)과 개정된 함수 설명서·검증 스크립트를 앞선 검수 항목별로 확인한다.
- 작업 전 상태: 설명서 첫판은 `aac4093`에 있고 이번 개정과 Claude 기록은 미커밋이다. 조율 브랜치 기준 ref는 `deb5c81`; 서비스 코드·DB는 바뀌지 않았다.
- 변경 파일: [재검수 결과](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_20260929.md), 이 WORKLOG, [STATUS](STATUS.md), [문서 지도](README.md). 코드·DB·설명서·스테이징은 변경하지 않았다.
- 결과: Linux 수집 상태 연결은 `app._connect()` 연결 전달로, G-01의 `app.eligibility()` 한 줄 권고는 철회로 문서 오류 해결 확인. 실제 공고 공급과 확인 필요 표시는 한계·합의 사항으로 명시됐으나 기능은 미완료. 새 P2 네 건은 확인 필요 목록의 입력 출처, 빠른 시작의 지연·실패/빈 목록 처리, 화면용 자격 근거의 접수 시작 전 공고 오해 방지, 카드·공고 기간 계약과 EC2 프로세스 교체 메모리 조건이다.
- 검증: 번들 Python 3.12 + 기존 `.venv` 패키지로 `experiments.orchestration_probe` 독립 재실행. D·A·B·C 모두 통과, 종료 코드 0; A offset 0·10 각 10건, B 2,525건×5입력 차이 0, C 스텁 공고로 계획서작성. 개정 설명서 `git diff --check` 통과. 공용 DB는 probe의 SELECT만 실행, 유료 API 호출 없음.
- 미검증·남은 문제: Linux(EC2) 실제 실행, 실제 `Announcement` 공급, 확인 필요 표시, 비정상 수집 상태·빈 결과, 동시 요청·프로세스 교체, 사람 기준 신청 가능 여부. 전체 unittest는 서비스 코드 변경이 없어 재실행하지 않았다.
- 다음 단계: Claude가 P2 문구를 보완하고 조율 담당과 ①②③⑦ 및 입력 변환을 합의한 뒤 실제 공급 함수로 통합 검증한다. 신청자 유형 판정표 P1은 별도 사용자 지시 전까지 멈춘다.

### 2026-09-29 · Claude · Codex 검수 반영 — 조율 함수 설명서 개정

- 요청·목적: 사용자 — [Codex 검수](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_20260929.md) 반영(1번). 사용자 결정: 접수 시작 전 공고는 고를 수 있다.
- 작업 전 상태:
  - 설명서 첫판은 커밋 `aac4093`에 있었다(조율 담당이 머지했다면 옛 판).
  - Codex P1 두 건은 설명서의 잘못된 안내였다.
    - Linux에서 `collection_status.check()`가 `ec2/.env`를 읽지 않는다(`shared/config.py` CANDIDATES — 코드 대조로 확인).
    - `app.eligibility()`는 `gate._check_period`에서 시작 전 공고를 False로 판정한다(확인).
- 변경 파일:
  - [설명서](guides/ORCHESTRATION_HANDOFF.md) 전면 개편. 순서: 빠른 시작 → 연결 전 합의 → 준비물·운영 → 함수 상세 → 예시 → 기타 합의 → 운영·개정 기록.
  - `experiments/orchestration_probe.py`: 코드 블록을 내용으로 찾고, D(빠른 시작 실행)를 추가했다.
  - [응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RESPONSE_20260929.md)(신규), 문서 지도, STATUS.
- 전후 차이:
  - 수집 상태는 `app._connect()` 연결을 넘기는 `collection_status_now()`로 바꿨다.
  - ⑩ 권고를 철회했다. 4.5는 "화면용 — G-01에 그대로 쓰지 않는다"가 됐다.
  - ①은 `date | None` + `apply_period_type` + 조율 `service.py:259` 비교 수정을 묶음으로 제안한다.
  - ⑦은 `unknown_conditions` + 화면 표시 합의로 제안한다.
  - ⑪ 벡터 대체 경로 `notices.embedding` `'<f4'`와 ⑫ 입력 변환을 추가했다.
  - 운영 주의를 추가했다: 재시작은 새 프로세스로 교체, 동시 호출 미확인, 손상 파일 알려진 문제.
  - 예시 `top=min(top_k, 10)`.
- 검증: `python -m experiments.orchestration_probe --sbrain <세션 임시 폴더>\agent-orchestration` → D·A·B·C 통과, 종료 코드 0.
  - B: 5가지 경우 다름 0.
  - C: 공고 공급은 스텁 값.
  - 서비스 코드를 바꾸지 않아 전체 unittest는 돌리지 않았다.
- 미검증: Linux 실행, 실제 공고 공급, 재부팅·동시 호출.
- 다음 단계: Codex 재검수. 조율 담당과 ①②③⑦ 합의.

### 2026-09-29 · Codex · 조율 연동 설명서와 9/29 배치 독립 검수

- 요청·목적: Claude의 [검수 요청](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_REQUEST_20260929.md)에 따라 조율 개발자용 함수 설명서, 실제 코드 계약, 9/29 배치 점검을 독립 확인한다.
- 작업 전 상태: `ORCHESTRATION_HANDOFF.md`는 `aac4093`에 이미 포함되어 있었고, 요청서·검증 스크립트와 STATUS·WORKLOG·문서 지도 수정은 기존 미커밋 상태였다. 사용자 지시로 신청자 유형 판정표 P1 수정은 멈춰 있었다.
- 변경 파일: [검수 결과](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_20260929.md) 신규, 이 WORKLOG, [STATUS](STATUS.md), [문서 지도](README.md). 코드·DB·설명서·기존 스테이징은 변경하지 않았다.
- 결과: 예시 A·B·C 재실행 통과. Linux 설정 경로 불일치, G-01의 `app.eligibility()` 대체 시 접수 시작 전 공고 판정 차이(가상 공고로 재현), 실제 공고 공급의 필수 필드 미확정, “모름·입력 누락 통과”의 확인 필요 정보 소실을 P1으로 기록했다. 벡터 장애 시 필수 임베딩 공급과 동시 재시작 등의 조건도 기록했다.
- 검증: 로컬 원격 추적 ref `deb5c81`에서 조율 코드를 임시 폴더로 읽고, 번들 Python 3.12 + 기존 `.venv` 패키지로 `experiments.orchestration_probe` 실행(A offset 0·10 각 10건, B 2,525건×5입력 차이 0, C 스텁 흐름 계획서작성). 공용 DB SELECT에서 `notices`·판정표 각 2,525행, 마감 없음 985, 모집 상태 모름 2,086, 금액 787 확인. `upload_judgments --plan`에서 두 표 모두 같음 2,525·변경 0. 로그 `exit=0`, 11·12단계 각각 추출 50/실패 0, 13단계 각 올림 50 확인. `bizinfo:PBLN_000000000126783`의 업력 근거 “5년 이상”과 상한 5 불일치를 SELECT로 확인. DB 쓰기·유료 API 호출 없음.
- 미검증·남은 문제: Linux 실배포, 실제 Announcement 공급, 병렬 요청과 재시작 중 요청, 전체 unittest, 사람 기준 신청 가능 여부는 확인하지 않았다. `.venv` 실행 파일은 원래 Python 경로가 없어 직접 사용할 수 없었다.
- 다음 단계: Claude가 검수 결과에 따라 설명서와 합의안을 보완하고, 조율 담당이 필수 필드·확인 필요 표시를 결정한 뒤 실제 공고 공급으로 통합 검증한다. 멈춘 판정표 P1은 별도 지시 전까지 수정하지 않는다.

### 2026-09-29 · Claude · 조율 설명서 Codex 검수 요청 + 검증 스크립트

- 요청·목적: 사용자 — 지금 상황을 Codex에 전달한다. 사용자 전달: 조율 담당이 우리 브랜치를 다른 브랜치로 머지해 작업한다.
- 변경 파일:
  - [검수 요청서](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_REQUEST_20260929.md)(신규, 새 주제 폴더 `reviews/orchestration/`)
  - `experiments/orchestration_probe.py`(신규)
  - [문서 지도](README.md) 3절 한 줄, [STATUS](STATUS.md)
- 스크립트를 둔 이유: 지금까지의 확인은 세션 임시 폴더의 시험 코드로 했다. Codex가 같은 확인을 다시 돌릴 수 없어 저장소에 옮겼다.
  - 설명서 7절 코드 블록을 정규식으로 꺼내 실행한다. 문서와 시험 코드가 따로 놀지 않게 하려는 것이다.
  - 조율 코드 경로는 `--sbrain`으로 받는다(`git archive`로 꺼낸 폴더).
  - 읽기 전용이다. 조율 쪽 pytest 없이 돈다.
- 검증: `python -m experiments.orchestration_probe --sbrain <세션 임시 폴더>\agent-orchestration`
  - A: T-C2 offset 0·10 각 10건, 순위 1~10·11~20
  - B: G-01 5가지 경우 모두 다름 0
  - C: 흐름이 계획서작성까지 감
  - 문서 문자열의 `\.` SyntaxWarning을 raw 문자열로 고쳤다.
  - 전체 unittest는 서비스 코드 변경이 없어 돌리지 않았다.
- 다음 단계: Codex 검수 결과를 보고 설명서를 고친다. 가독성 개편(코드 예시를 맨 앞으로)도 그때 함께 한다. 멈춘 판정표 P1은 사용자 지시가 있을 때 재개한다.

### 2026-09-29 · Claude · 조율 안내서를 함수 설명서 형식으로 다시 씀

- 요청·목적: 사용자 — "어떤 파라미터를 받고 어떤 결과를 주는지, 어떤 파이썬 파일인지, 개발자가 원하는 문서를 알기 쉽게".
- 변경 파일: [guides/ORCHESTRATION_HANDOFF.md](guides/ORCHESTRATION_HANDOFF.md)를 다시 썼다. 코드 변경 없음.
- 문서 구성:
  - 0절 한눈에 보기: 함수 5개의 파일·부르는 법·넣는 것·받는 것·쓰는 곳
  - 2~6절 함수별 상세: 줄 번호 링크, 입력 칸 표(필수·선택·영향 없음·건드리지 말 것), 출력 키 표, 실제 예시
  - 7절 조율 규격에 끼우는 예시, 8절 합의 10건, 9절 운영
- 바뀐 점:
  - `app.eligibility(GateRequest)`를 G-01용 함수로 소개했다.
  - 없는 ID는 예외가 아니라 `JSONResponse` 404를 돌려준다는 점을 적었다.
  - 합의 ⑩(`G01In`에 공고 ID 추가)을 넣었다.
  - G-01 예시의 설립일 없는 사업자 처리를 "입력 누락 = 통과"로 바꿨다.
  - **바로 아래 항목의 "설립일 없는 개인사업자 14건 차이"는 이 수정으로 0이 됐다**(정정).
- 검증:
  - 예시 값은 모두 이번 실행 결과다(공고 2,525건).
  - G-01 대조: 5가지 경우 × 2,525건 전부 같음.
  - 문서 7절 코드 블록을 그대로 꺼내 조율 쪽 스텁 흐름에 끼웠다. `start_run` → 더 보기 → 선택 → G-01 통과 → 계획서작성.
  - 줄 번호는 `grep`으로 대조해 두 곳을 고쳤다.
- 다음 단계: 사용자가 조율 담당에게 전달한다.

### 2026-09-29 · Claude · 조율 에이전트 연결 안내서

- 요청·목적: 사용자 — 다른 팀원(4nchez)이 만든 조율 에이전트(`agent-orchestration/`, SB-86 `deb5c81`)에 공고팀 기능을 연결하려 한다. 공고팀은 코드를 끼우지 않고 전달만 한다.
- 작업 전 상태: Codex P1 수정 전(사용자 요청으로 멈춤). 조율 코드는 우리 브랜치에 없어 `git fetch` 후 `git archive`로 세션 임시 폴더에 꺼내 읽었다. 작업 트리는 바꾸지 않았다.
- 사용자 결정:
  - 연결은 **코드 직접 호출** — 조율 프로세스가 `search.app.boot()`를 한 번 부르고 `app.match()`를 쓴다. 우리 서버는 켜지 않는다.
  - G-01은 **판정 불가·입력 누락 모두 통과**다.
- 변경 파일: [guides/ORCHESTRATION_HANDOFF.md](guides/ORCHESTRATION_HANDOFF.md)(신규), [문서 지도](README.md) guides 행, [STATUS](STATUS.md), 이 WORKLOG. 코드·DB 변경 없음.
- 안내서 내용:
  - 준비물·불러오는 법, T-C2 입출력 변환표, 공고 공급 칸별 출처
  - `eligibility` 만드는 규칙(매칭 정형 필터와 같은 규칙), G-01 규칙
  - 합의 요청 9건, 검사를 통과한 예시 코드
- 검증 (모두 공고팀 PC · 공용 DB SELECT · 세션 임시 폴더):
  - `boot()` 16~22초, 메모리 약 2.1GB, `match()` 0.25~0.32초.
  - 예시 T-C2가 조율 쪽 `TC2Out` 검사를 통과했다(offset 0·10, 카드 10건, 수집 상태 정상).
  - G-01 규칙을 `app.eligible_with_types`(마감 제외)와 2,525건 × 5가지 경우로 대조했다. 4가지는 전부 같았다.
    설립일 없는 개인사업자만 14건이 달랐다(예비창업자 전용 공고). 매칭 필터는 `UNKNOWN_AGE`면 업력 판정을 건너뛰어 남기고, G-01은 뺀다. G-01 쪽이 맞다.
  - 안내서 7절 코드 블록을 그대로 꺼내 조율 쪽 `build_stub_app()`에 `registry.bind`로 끼웠다. `start_run` → `more_candidates` → `select_announcement` → G-01 통과 → "계획서작성/사용자대기"까지 확인했다.
    조율 쪽 pytest가 우리 가상환경에 없어 예시 입력만 옮겨 적었다. 우리 가상환경에는 아무것도 설치하지 않았다.
- 미검증·남은 문제:
  - EC2(Linux) 경로(`ec2/.env`·`VECSTORE_PATH`)로 불러오는 것
  - `boot()` 재호출 중 동시 요청
  - 조율 쪽 실제 LLM T-C1이 만든 입력
  - 합의 9건
  - 매칭 필터의 설립일 없는 사업자 × 예비창업자 전용 공고 14건(후속)
- 다음 단계: 사용자가 안내서를 조율 담당에게 전달한다.

### 2026-09-29 · Claude · 9/29 매일 배치 결과 점검 (Codex 점검표 3가지)

- 요청·목적: 사용자 — 오늘 09:00 배치 결과 파악. [Codex 재검수](reviews/integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md) 3절 점검표대로 확인.
- 변경 파일: 이 WORKLOG, [STATUS](STATUS.md)만. 코드·DB·결과 파일은 바꾸지 않았다(공용 DB는 SELECT만).
- 결과:
  1. 배치: 09:00:02~09:12:08, `exit=0`, `status ok`, `stage_warnings []`, `degraded []`. 신규 공고 49건(K-Startup 4·기업마당 45), 첨부 55건(ok 48·parse_error 5·image_only 2), 임베딩 51건(신규 49 + 본문 바뀜 2), 벡터·첨부 업로드 51건·47개.
     10단계 자격요건 44건, 11단계 신청자 유형 50건(약 $0.046), 12단계 업종 50건(약 $0.080). 두 단계 모두 `failed`·`deferred`·`gave_up` 0.
  2. 13단계: 두 표 모두 새로 49 · 바뀜 1(`bizinfo:PBLN_000000000126490`) · 올림 50 · `error null`.
     SELECT 기준 `notices`·두 판정표 각 2,525행·고유 ID 2,525, 판정 없는 공고 0. 파일도 각 2,525행·고유 2,525. `upload_judgments --plan` 다시 실행: 같음 2,525, 올릴 것 0.
  3. 서비스 읽기(서버 재시작 대신 `load_auto(conn, expected=2525)` 직접 호출): 신청자 유형 `db:notice_applicant_types`·`refreshed_from_file 0`, 업종은 파일 `final5`(1,852행 — 오늘 새 공고의 업종은 서비스에 없음. 업종 순위는 기본 꺼짐이라 매칭 영향 없음).
     8000·8010 서버는 켜져 있지 않았다.
- 새 공고 판정 분포(49건): 예비창업자 `implied_no` 33 · `allowed` 5 · `blocked` 4 · 없음 7. 전체 분포(implied_no 1,734/2,525)와 비슷하다.
  `blocked` 4건은 근거가 "법인‧단체"·"사업자등록" 요건이라 타당해 보인다(AI 참고 확인). `kstartup:179328`은 API 업력 칸에 "예비창업자"가 있는데 본문은 `implied_no` — 서비스는 빼지 않고 순위만 뒤로 보낸다.
- 발견(P2 후보): 10단계 업력 `bizinfo:PBLN_000000000126783` 근거 "5년 이상 영업"인데 `age_years_min=5, age_years_max=5`. 상한 5는 틀렸다.
  매칭 필터(`gate.prefilter`)는 API 업력 칸만 보므로 이 공고를 빼지 않지만, 자격 확인 업력 줄(`search/age_evidence.py`)에는 "5년 이하"처럼 보일 수 있다. 오늘 `age_quote_problem`이 이것을 거르지 못했다("이상"만 있는데 상한이 채워진 경우).
  그 밖에 "7년 이내 스타트업" 등 5건은 "업력 표현 없음"으로 버려졌다 — 모름으로 남겨 빼지 않으므로 안전한 쪽 오류.
- 미검증: 실제 서비스 재시작 후 `/api/match` 응답, EC2(파일 없는 경로). 새 공고 판정의 사람 검수.
- 다음 단계: 사용자 결정 — Codex P1(파일 신선도·손상 파일 격리) 수정, 126783류 업력 상한 검사 보완.

### 2026-09-28 · Claude · Jev(TypeSafe AI) 채점 시험

- 요청·목적: 사용자 — 새 모델 Jev(글 대신 정해진 보기 중 선택 + 확신도, 2026-09-15 공개)를 무료 크레딧($5)으로 시험. 평가 채점(주제 관련도 0·1·2)에 쓸 수 있는지.
- 변경 파일: `eval/jev_judge_probe.py`(신규 — 블라인드 사람 판정 143쌍을 같은 입력·같은 기준으로 Jev 에 채점시키고 merge_qrels 와 같은 지표로 비교). 가상환경에 `typesafe-sdk==0.7.2`(PyPI, TypeSafe AI 공식) 설치. 키는 사용자가 `.env` 의 `TYPESAFE_API_KEY` 에 넣었다.
  기존 `eval/llm_judgments.jsonl`·qrels·공용 DB 는 건드리지 않았다.
- 결과 ([reports/jev_judge_probe_20260928T110603Z](../reports/jev_judge_probe_20260928T110603Z/summary.md), jev-1.13.0, 143쌍 오류 0, 응답 중앙값 230ms, 입력 약 24.6만 토큰 ≈ $0.01):
  - 정확 일치 Jev 0.52 vs gpt-4.1-mini 0.64(같은 143쌍), 가중 카파 0.47 vs 0.62, 0↔2 뒤바뀜 7.7% vs 7.0%. **기존 LLM 보다 낮다.**
  - Jev 는 1 로 몰린다(1 을 59번 — 사람 36번). 사람 2 → Jev 1 이 23쌍.
  - 확신도 0.9 이상 25쌍은 정확 일치 0.84·0↔2 0% 지만, 같은 25쌍에서 LLM 도 0.80 — 쉬운 쌍이 몰린 것에 가깝다. 확신도 순서(0.84 → 0.61 → 0.40)는 맞게 나온다.
  - Jev 와 LLM 이 같은 답인 97쌍도 사람과 0.66 — 둘을 합쳐도 크게 나아지지 않는다.
  - 5쌍 시험(`…T110547Z`)은 형식 확인용.
- 화면: 8010 `/jev-probe`(메뉴 "Jev 채점 시험") — Jev vs LLM 막대, 확신도 구간별(같은 쌍 LLM 대조), 혼동표, 쌍별 사람·Jev(보기별 확률)·LLM(이유) 비교와 거르기(Jev만 틀림 28 · Jev만 맞음 11 · 둘 다 틀림 40).
  `experiments/sql_semantic/jev_probe_results.py`(파일만 읽음), `web/jev_probe.html`, `viewer.py` 경로·메뉴, `tests/test_jev_probe_ui.py` +3.
- 결론: 지금 형태로는 LLM 채점을 대신하지 못한다. 프롬프트를 이 143쌍에 맞춰 고치면 시험 문제로 공부하는 셈이라 수치를 믿을 수 없게 된다.
- 다음 단계: 없음(사용자 판단).

### 2026-09-28 · Claude · 매칭 방식 비교에 "처음(벡터만)" 추가 + 그래프

- 요청·목적: 사용자 — "처음에 공고를 임베딩해 벡터 DB 유사도만 보던 방식과 지금 방식을 숫자로 비교하고 시각적으로도 보고 싶다".
- 작업 전 상태: `/filter-first-eval` 은 9/22(검색 먼저, 이미 하이브리드·규칙 포함)와 지금(필터 먼저)만 비교했다. 처음 방식과의 수치는 없었다.
- 변경 파일:
  - `eval/filter_first_eval.py` — 세 번째 대상 `vector_only`(지금 코드에서 정형 필터·마감 제외·단어 검색·지역/집단/유형/업종 규칙을 모두 끈 재현, `VECTOR_ONLY`). 요약에 `vector_only`·`diff_vs_vector` 추가(기존 `diff` 는 그대로 지금−9/22).
    신청 불가 채점을 서비스와 같은 기준(`app.eligible_with_types`)으로 바꿨다 — API 업력 칸만 보면 본문으로 살린 공고(kstartup:179011, 본문 "여성 예비창업자")를 불가로 셌다.
  - `search/app.py` — 정형 필터 한 건 판정(`gate.prefilter` + 예비창업자 본문 판정 G)을 `eligible_with_types()` 로 분리. 매칭 동작은 같다.
  - `web/filter_first_eval.html` — 세 방식 막대그래프 6개(신청 불가 비율·섞인 질의 수·내용 적합도·쓸모@3·쓸모@10·순서 품질, 보수적~낙관적 빗금), 단계 비교표, 비교 기준 전환(벡터만/9/22 → 지금). vector_only 없는 예전 결과 폴더도 두 방식으로 열린다.
  - 메뉴 이름 "매칭 순서 비교" → "매칭 방식 비교"(`viewer.py` NAV, `web/flow.html` 링크 글자).
  - `tests/test_filter_first_eval.py` +2 — `VECTOR_ONLY` 키가 실제 요청 필드이고 켜진 스위치가 없음(오타면 pydantic 이 조용히 무시), 3열 요약·예전 요약 렌더.
- 결과 ([reports/filter_first_eval_20260928T104212Z](../reports/filter_first_eval_20260928T104212Z/summary.md), 기준일 9/15 · 정상 질의 58 · 말뭉치 2,084 · 정답 1,617쌍, 하이브리드):
  - 신청 불가@10 벡터만 24.3% → 9/22 5.5% → 지금 0.0%. 상위 10에 불가가 섞인 질의 50/58 → 22/58 → 0/58.
  - P@3(2) 하한 49.4% → 62.6% → 62.1% (지금−벡터만 +0.126 [+0.040, +0.213]). 쓸모@3 하한 1.10 → 1.81 → 1.86.
  - nDCG@10(판정분)은 세 방식 모두 약 0.60 으로 차이 없음.
  - 지금−9/22 는 신청 불가 외 대부분 구간이 0 포함(기존 결론과 같다). 9/22 신청 불가가 4.8%→5.5% 로 오른 것은 채점 기준 변경(본문 "불가" 공고도 불가로 셈) 때문이다.
- 검증: 전체 unittest 621개 통과(건너뜀 13). 8010 화면 — 새·예전 결과 폴더, 뜻 검색만 모드, 375px 폭 가로 넘침 없음 확인.
  채점 기준을 고치기 전 첫 실행(`…T103959Z`)은 결과 목록에서 빼 세션 임시 폴더로 옮겼다.
- 미검증·남은 문제: 정답 대부분이 LLM 판정(사람 일치 0.64), 질의 58개. 벡터만은 과거 커밋이 아니라 지금 코드의 스위치로 재현한 것이다(질의 문장 구성은 지금과 같다).
- 다음 단계: 없음(사용자 확인).

### 2026-09-28 · Codex · 판정 테이블 수정 재검수

- 요청·목적: [Claude 응답](reviews/integration/JUDGMENT_TABLES_REVIEW_RESPONSE_20260928.md)의 수정과 재검수 요청 3가지를 독립 확인한다.
- 작업 전 상태: Claude가 서비스 95%·파일 해시 보호, 업로드 90% 가드, 문서·체크포인트·C-3 보완을 적용했다. 기존 스테이징과 변경은 보존했다.
- 변경 파일: [재검수 결과](reviews/integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md), 이 WORKLOG, [STATUS](STATUS.md), [문서 지도](README.md)만. 코드·DB는 수정하지 않았다.
- 전후 차이·선택 이유: 가짜 DB·임시 파일로 옛 파일이 DB의 새 판정을 `blocked`로 덮고, 손상 파일이 정상 DB에도 `JSONDecodeError`를 발생시키며, 파일 없는 호스트에서 부분 DB의 `blocked`를 쓰는 P1 잔여를 확인했다. 90% 가드의 정상 범위 축소 차단·중복 통과와 흐름 화면의 옛 상태 문구도 기록했다.
- 검증: 공용 DB SELECT로 공고·두 표 각 2,476행, 두 파일의 각 2,476 고유 ID와 변경 0을 확인. 표적 테스트 156개 통과. 전체 테스트와 8000 재시작은 Python/가상환경 확장 모듈 불일치로 독립 재실행하지 않았다. 9/29 배치는 아직 실행 전이다.
- 미검증·남은 문제: 실제 9/29 배치의 stage_warnings·두 표 갱신·서비스 재시작 상태, EC2의 파일 없는 경로, 사람 기준 업종 판정. 코드·DB·Git 스테이징·커밋·유료 API 호출 없음.
- 다음 단계: Claude가 P1 파일 오류/신선도 보호를 보완하고, 업로드 완료 세대와 공고 해시를 연결하는 설계를 사용자에게 제시한다. 9/29 배치 뒤 결과 문서의 점검표를 실행한다.

### 2026-09-28 · Claude · 판정 테이블 검수 지적 수정(P1·P2)

- 요청·목적: [Codex 결과](reviews/integration/JUDGMENT_TABLES_REVIEW_20260928.md)(조건부 승인)의 지적을 고친다.
- 변경 파일:
  - `search/applicant_types.py` `load`·`load_db`(문서 해시), `load_auto`(완전성 95%·공고별 신선도·db 강제 error).
  - `search/industry_rank.py` `load_auto`(완전성·db 강제).
  - `search/app.py`: `expected` 전달.
  - `collect/upload_judgments.py`: 파일이 90% 미만이면 중단.
  - `search/age_evidence.py`: `db_read`.
  - `collect/industry_daily.py`: 체크포인트 스키마·엔진.
  - `experiments/sql_semantic/age_rerun.py`: 실제 반영 행 수·missed.
  - `docs/guides/JUDGMENT_TABLES.md`: varies·usable_for_rank·스키마 한정 문구·서비스 읽기·한계. `web/flow.html` 문구.
  - 테스트 3개 파일, [응답](reviews/integration/JUDGMENT_TABLES_REVIEW_RESPONSE_20260928.md).
- 검증:
  - 전체 619개 통과.
  - 8000 재시작: `db:notice_applicant_types`, 옛 값 교체 0, 매칭 결과 동일(177·9·10). DB 쓰기 없음.
- 남은 것: `judgment_uploads` 표 여부(사용자), 업종 DB 전환(사람 판정 뒤), 9/29 배치 확인.

### 2026-09-28 · Codex · 판정 테이블·12·13단계·업력 반영 검수

- 요청·목적: [Claude 요청서](reviews/integration/JUDGMENT_TABLES_REVIEW_REQUEST_20260928.md)에 따라 저녁 수정과 두 판정표, 일일 업종 추출·업로드, 서비스 DB 읽기, 업력 C-3 반영을 검수했다.
- 작업 전 상태: Claude 코드·문서 변경과 판정표 각 2,476행, 업력 78행 반영이 있었으며 다른 기존 변경과 스테이징은 보존했다.
- 변경 파일: [검수 결과](reviews/integration/JUDGMENT_TABLES_REVIEW_20260928.md), 이 WORKLOG, [STATUS](STATUS.md), [문서 지도](README.md)만. 코드·DB는 수정하지 않았다.
- 전후 차이·선택 이유: 현재 DB/파일 일치를 독립 확인하고, 13단계 부분 실패 후 DB 우선 읽기가 오래되거나 불완전한 판정을 사용할 수 있다는 P1과 사용 범위·출처·강제 DB 모드 P2를 기록했다. 업종 DB 기본 전환은 보류 권고했다.
- 검증: 공용 DB에 SELECT와 `information_schema` SELECT만 실행해 테이블·분포·FK·업력·백업을 확인했다. 두 결과 파일과 DB의 2,476행씩 전 열 비교에서 변경 0. 시스템 Python 표적 테스트 151개 통과. 전체 테스트는 현재 Python과 `.venv`의 `pydantic_core` 바이너리 불일치로 import 오류가 나 검증하지 못했다. API 호출·Git 스테이징·커밋 없음.
- 미검증·남은 문제: 실제 9/29 배치/서비스 재시작, 화면 표시, 사람 기준 업종 정확도. P1 신선도 보호와 P2 문서·규칙 출처를 보완한 뒤 재검수한다.
- 다음 단계: Claude가 결과 문서의 우선순위대로 수정하고 실패/누락 재현 테스트를 보강한다. 공용 DB 갱신은 별도 사용자 결정에 따른다.

### 2026-09-28 · Claude · Codex 재검수 P2 3건 수정 + 판정 테이블 검수 요청서

- 요청·목적:
  - [재검수](reviews/integration/RECHECK_AND_EVENING_REVIEW_RECHECK_20260928.md)의 P2를 9/29 배치 전에 고친다.
  - 오늘 만든 판정 테이블·12·13단계·서비스 DB 읽기·C-3를 Codex에 맡길 [요청서](reviews/integration/JUDGMENT_TABLES_REVIEW_REQUEST_20260928.md)를 만든다.
- 변경 파일:
  - `collect/extract_conditions.py`: `AGE_BENEFIT`, `_clean_age_clauses`, `_value_in`. `age_quote_problem(quote, values)` — 섞인 근거는 연수 대조를 하고, 우대·지원금 구간은 버린다.
  - `search/app.py` `eligibility`: pre_partial을 먼저 처리한다.
  - `search/age_evidence.py`: DB 우선, 파일은 해시가 같고 DB에 업력이 없을 때만 쓴다. DB 값도 지금 검사로 거른다(`hidden`·`file_skipped`).
  - 테스트 3개 파일.
- 확인:
  - 반례 4개 모두 걸림. DB 업력 225 중 새 검사에 걸리는 4건(서비스는 숨김, DB는 그대로).
  - 서비스 근거 221. 8000 재시작: `kstartup:176208` 유형·업력 확인 필요.
  - 전체 614개 통과.
- 남은 결정: 공용 DB 4건 정리(사용자). 새 프롬프트 4o-mini 소표본 무쓰기 실험(Codex 권고, 유료).

### 2026-09-28 · 사용자·Claude · C-3 업력 luna 재추출 78건 공용 DB 반영

- 코드: `experiments/sql_semantic/age_rerun.py --apply`(`apply_plan`·`apply_to_db`)와 `tests/test_extract_conditions_age.py` `AgeApplyPlanTests`.
  - 업력 칸(하한·상한·근거·버린 이유)과 `uncertain`의 출처 메모만 바꾼다.
  - `extractor_version`은 그대로 둔다. 매일 10단계 `already_done`이 다시 부르지 않게 하려는 것이다.
  - `input_sha256`이 재추출 문서와 같을 때만 바꾼다.
  - 바꾸기 전 값을 백업한다.
- Claude의 쓰기 명령은 자동 권한 검사에서 막혔다. **사용자가 직접 실행**했다: 반영 78행, 백업 `reports/age_rerun_luna_20260928T054509Z/applied_backup_20260928T074751Z.jsonl`(78줄).
- 확인(읽기만):
  - 다시 `--plan`: 반영 0 · 같음 78.
  - `notice_conditions` 업력 있음 147 → **225**, 버림 233 → 155. 버전은 전부 4o-mini 그대로이고, 출처 메모는 78행이다.
  - 반려동물 공고: 최대 10년, 버림 NULL. `already_done`에 남아 있어 배치가 다시 부르지 않는다.
  - DB만으로 읽은 업력 근거가 225건이다(파일 없이도 같은 값).

### 2026-09-28 · Claude · 검색 서비스가 판정을 공용 DB에서 읽기

- 요청·목적: 파일이 없는 곳(EC2·팀원 PC)에서도 같은 판정으로 매칭하게 한다.
- 변경 파일:
  - `search/applicant_types.py`: 행 해석을 `_info()`로 모았다. `load_db()`, `load_auto()`(환경 변수 `APPLICANT_TYPES_SOURCE`, 기본 auto: DB → 비었거나 실패하면 파일). 등록 사업자 규칙은 DB 값에 지금 코드를 다시 적용한다.
  - `search/industry_rank.py`: `load_db()`, `load_auto()`(`INDUSTRY_SOURCE`, **기본 file** — final5 유지 결정).
  - `search/app.py` `boot`: 연결 한 번으로 두 판정을 읽는다. 연결 실패는 `boot_errors.judgments_db`에 남기고 파일로 간다. 로그에 출처와 대체 이유를 찍는다.
  - `tests/test_judgments_source.py`(5), `tests/test_match_deh.py` 시작 테스트 대역, `web/flow.html` 데이터 지도 표, JUDGMENT_TABLES 6절.
- 확인:
  - DB와 파일 비교: 신청자 유형 2,476건 정보 동일, 서비스 결론 차이 0. 업종 순위 공고 217 동일.
  - 8000 재시작: "신청자 유형 2476건 (db:notice_applicant_types)", `boot_errors` {}.
  - 예비창업자·경기·친환경 매칭 결과는 전과 같다(blocked 177·restored 9·뒤로 10). 반려동물 공고 자격 확인도 같다.
  - 전체 611개 통과.
- 남은 것: 업종 서비스 전환(final5 → DB)은 Codex 재검수 뒤에 한다. 서비스는 시작할 때 한 번 읽으므로 배치 뒤 재시작이 필요하다(운영 자동화는 별도).

### 2026-09-28 · Claude · 매일 배치 12단계 — 업종 추출 (`collect/industry_daily.py`)

- 요청·목적: 업종 판정도 신청자 유형처럼 매일 채워 13단계가 공용 DB `notice_industries`에 올리게 한다.
- 변경 파일:
  - `collect/industry_daily.py` 신규.
    - 11단계와 같은 구조: 새·바뀐 공고만, 날짜당 300건(부르기 전 예약), 같은 문서 3회 실패 시 중단, `run.lock`.
    - 누적 `data/industries/`, 시작은 final6.
    - 추출은 전량 실행과 같다(v3·rough·luna@medium). 검사에 발췌 상한 6,000자를 넘긴다(None이면 잘림 판정이 꺼진다).
  - `industry_llm_sample.only_new`에 `reports_dir`를 추가했다(누적 파일의 `source_run` 폴더를 reports/에서 찾는다).
  - `collect/upload_judgments.py`: 업종 원본 기본값을 12단계 누적 파일로 바꿨다(없으면 final6).
  - `collect/daily_pipeline.py`에 12단계를 붙였다(`--skip-industries`·`--industries-limit`, 경고 `industries`).
  - `.gitignore`에 `data/industries/`를 추가했다. 수집 상태 화면 단계 이름, README, JUDGMENT_TABLES를 고쳤다.
  - `tests/test_industry_daily.py`(5).
- 확인:
  - `--plan`: 부를 것 0(final6이 최신).
  - 단독 실행 1회: 호출 0·$0으로 누적 파일을 만들었다.
  - 13단계 `--plan`: 업종 원본이 `data/industries/results.jsonl`로 바뀌었고 같음 2,476.
  - 전체 606개 통과.
- 비용 예상: 새 공고가 하루 수십 건이면 건당 약 $0.0011, 하루 $0.1 미만.
- 남은 것: 새로 잘린 공고(6,000자)를 길게 다시 읽는 것은 매일 하지 않는다(업종 순위를 다시 켤 때 결정).

### 2026-09-28 · Claude · 판정 첫 업로드(공용 DB)와 13단계 배치 연결

- **공용 DB 쓰기(사용자 확인)**: `python -m collect.upload_judgments`
  - `notice_applicant_types`에 2,476행을 올렸다. 결론은 implied_no 1,701 · allowed 289 · blocked 183 · NULL 303.
  - `notice_industries`에 2,476행을 올렸다. known 830(순위 사용 가능 217) · not_mentioned 1,088 · excluded_only 287 · unknown 240 · conditional 26 · no_limit 5.
  - 곧바로 `--plan`을 다시 돌려 같음 2,476·올릴 것 0을 확인했다(비교가 실제 DB 형식에서도 맞다).
- `collect/daily_pipeline.py`에 **13단계**를 11단계 뒤에 붙였다. `--skip-judgments`로 끌 수 있고 `--skip-upload`도 따른다. 결과는 로그 `judgments_upload`에 남고, 실패하면 `stage_warnings`로 종료 코드 4가 된다.
- 수집 상태 화면의 단계 이름, README 단계 목록, TEAM_DATA·JUDGMENT_TABLES를 고쳤다. 전체 601개 통과.
- 남은 것: 12단계(업종 매일 추출), 서비스가 DB에서 읽기, C-3(업력 luna 반영).

### 2026-09-28 · Claude · 13단계 판정 올리기 코드 (`collect/upload_judgments.py`) — 첫 업로드 전

- 요청·목적: 신청자 유형·업종 판정 파일을 공용 DB의 새 표 두 개로 올린다. 8단계 벡터 올리기와 같은 방식이다.
- 변경 파일:
  - `collect/upload_judgments.py` 신규.
    - 서비스 결론(`pre_founder_verdict`·`registered_only_phrase`)은 `search/applicant_types`의 같은 함수로 계산한다.
    - 업종 `allowed_sections`·`usable_for_rank`는 `industry_groups`·`industry_rank` 규칙으로 계산한다.
    - DB의 지금 값과 칸마다 비교해 바뀐 행만 UPSERT한다. `notices`에 없는 공고는 세기만 한다.
    - `--plan`은 쓰지 않는다.
  - `tests/test_upload_judgments.py`(5)에 가짜 DB를 넣었다.
  - `notice_industries.status`의 칸 설명을 실제 값(known·not_mentioned·excluded_only·unknown·conditional·no_limit)에 맞게 고쳤다. SQL 파일, 설계 문서, 빈 표의 `ALTER … COMMENT`.
- 확인(`--plan`, DB 읽기만): 두 표 모두 새로 2,476행, 공고 없음 0.
  - 신청자 유형 결론: implied_no 1,701 · blocked 183 · allowed 289 · 모름 303, varies 78.
  - 업종: known 830, 순위 사용 가능 217, 대분류가 묶인 공고 417.
- 검증: 전체 601개 통과(건너뜀 13).
- **아직 올리지 않았다. 매일 배치에도 넣지 않았다.** 넣으면 내일 09:00에 첫 업로드가 사용자 확인 없이 일어나기 때문이다. 첫 업로드를 확인받은 뒤 13단계로 연결한다.

### 2026-09-28 · Claude · 공고 판정 테이블 두 개 생성 (공용 DB)

- 요청·목적: 배치는 사용자 PC에서 돌리되, 판정 결과를 팀원·EC2도 쓰게 한다. 사용자 결정 A(새 테이블 두 개)로 설계와 생성을 요청했다.
- 변경 파일:
  - `db/mysql_migration_006_notice_judgments.sql`: `notice_applicant_types` 21칸, `notice_industries` 21칸. `notices.notice_id` 외래 키에 CASCADE, utf8mb4_bin — `notice_conditions`와 같은 형식이다.
  - `docs/guides/JUDGMENT_TABLES.md` 설계·사용법 신규.
  - `docs/guides/TEAM_DATA.md`·`README.md`·`docs/README.md`에 연결했다.
- **공용 DB 쓰기(사용자 요청)**: 위 SQL로 `CREATE TABLE IF NOT EXISTS` 두 개를 실행했다.
  - 실행 전: 같은 이름의 표가 없음을 확인했다.
  - 실행 후: 두 표 모두 0행이다. 기존 표·데이터는 건드리지 않았다.
- 다음 단계: 배치 13단계(판정 → 공용 DB 올리기, 바뀐 행만) 코드와 테스트, `--plan`으로 올릴 건수를 확인한다. 첫 업로드는 사용자 확인 뒤에 한다. 12단계(업종 매일 추출)도 남았다.

### 2026-09-28 · Codex · 저녁 변경 수정 재검수

- 요청·목적: [Claude 응답](reviews/integration/RECHECK_AND_EVENING_REVIEW_RESPONSE_20260928.md)의 수정과 재검수 요청 3가지(구절 분할, `varies` 매칭/자격, 원답 재검사)를 확인했다.
- 작업 전 상태: Claude가 P1·P2·P3 조치를 코드에 반영하고 업력 근거 225건·전체 596개 통과를 보고했다. 기존 스테이징과 수정 파일은 보존했다.
- 변경 파일: [재검수 결과](reviews/integration/RECHECK_AND_EVENING_REVIEW_RECHECK_20260928.md), [STATUS](STATUS.md), [문서 지도](README.md), 이 작업 이력. 코드·DB는 수정하지 않았다.
- 전후 차이·선택 이유: 손상 파일 오류 격리, 업력 경계 안내, 재개 문서 해시, 11단계 잠금 등은 수정 확인했다. 세 가지 재검수 요청에는 P2 세 건을 재현 근거와 함께 남겼다: 업력 구절 존재만으로 잘못 뽑은 숫자/우대 문맥이 통과함, `varies` K-Startup 5건의 API 업력 `True`가 남음, 옛 재추출 파일이 새 DB 업력을 덮을 수 있음.
- 검증: 시스템 Python에서 `tests.test_applicant_type_daily tests.test_industry_llm_sample` 127개와 업력 혼합/재개 표적 2개 통과. 순수 함수에 거주 2년/창업 7년·금리 우대/금액표 반례를 넣어 검사 통과 확인. 가짜 DB 새 5년과 파일 옛 10년을 넣어 파일 우선 덮어쓰기 재현. 실제 DB·유료 API 호출 없음.
- 미검증·남은 문제: 프로젝트 `.venv` 실행 경로 손상과 시스템 Python의 FastAPI 부재로 전체 테스트/실제 8000 응답은 독립 재실행하지 못했다. Claude의 596개 통과·서버 225건은 Claude 기록이다. 기존 final6 요약의 “lab_conditions” 문구도 남아 있다.
- 다음 단계: Claude가 P2 세 건을 수정하고, 9/29 배치 전 변경된 4o-mini 업력 추출을 무쓰기 표본으로 확인한 뒤 재검수한다. Git 스테이징·커밋은 사용자가 직접 한다.

### 2026-09-28 · Claude · 저녁 변경 검수 지적 수정 (P1 1·P2 5·P3)

- 요청·목적: [Codex 결과](reviews/integration/RECHECK_AND_EVENING_REVIEW_20260928.md)의 지적을 9/29 배치 전에 고친다.
- 변경 파일:
  - `search/age_evidence.py`: `load`가 예외를 내지 않는다. 원답을 지금 규칙으로 재검사하고, 경계 비교를 고쳤으며, 하한 0년만 있는 값은 뺀다.
  - `search/app.py`: `boot` 업력 근거 격리, `eligibility` varies 처리, `_rule_verdict` 통일.
  - `search/applicant_types.py`: `type_check` varies, `varies()`.
  - `collect/extract_conditions.py`: `age_quote_problem`, 혼합 구절 분할.
  - `collect/applicant_type_daily.py`: 실행 잠금.
  - `experiments/sql_semantic/age_rerun.py`: 재개 해시·조건 비교, `reusable`.
  - `experiments/sql_semantic/industry_llm_sample.py`: 합침 원 실행 이름, 요약 문구.
  - `web/app.html`: 부분 오류 배너.
  - 테스트 4개 파일, [응답](reviews/integration/RECHECK_AND_EVENING_REVIEW_RESPONSE_20260928.md).
- 검증:
  - 전체 596개 통과(건너뜀 13).
  - 저장 근거 회귀: 기존 통과 147건 중 새로 떨어지는 것 0건, 버린 204건 중 통과 92건, 재추출 살아남 77 → 79.
  - 8000 재시작: 업력 근거 225건. 126505 경계 안내, 126769 확인 필요, 117511 되살아남을 실제 응답으로 확인했다.
- 남은 문제: 새 프롬프트의 모델 성능(4o-mini 소표본)은 미검증이다. Codex 재검수를 기다린다.

### 2026-09-28 · Codex · 8건 재검수와 저녁 변경 검수

- 요청·목적: [Claude 요청서](reviews/integration/RECHECK_AND_EVENING_REVIEW_REQUEST_20260928.md)의 앞선 8건 수정과 업력 검사·표시, 업종 final6, 재추출·화면을 검수했다.
- 작업 전 상태: Claude의 코드/문서 수정과 결과 파일이 이미 존재했고, 새 626건 결과 및 final6 합침도 완료된 상태였다. 기존 스테이징·미추적 파일은 보존했다.
- 변경 파일: [검수 결과](reviews/integration/RECHECK_AND_EVENING_REVIEW_20260928.md), [STATUS](STATUS.md), [문서 지도](README.md), 이 작업 이력. 코드·DB는 수정하지 않았다.
- 전후 차이·선택 이유: 앞선 8건은 순차 실행 기준 수정 확인으로 기록하고, 새 P1(손상된 업력 근거 파일이 서버 시작을 막음)과 P2(혼합 문장 과잉 버림, 미만 경계, 세부사업 통과, 재개 문서 해시, 독립 실행 동시 상한)를 재현 근거와 함께 분리했다. 결과 문서의 링크를 문서 지도에 추가했다.
- 검증: 시스템 Python에서 `python -X utf8 -m unittest tests.test_extract_conditions_age tests.test_industry_llm_sample tests.test_applicant_type_daily` 130개 통과. 저장된 204건 업력 재추출 결과·final6 2,476행 및 `industry_rank.load()`의 적용 가능 217건·신청자 유형 66건을 파일로 확인. `age_evidence.compare()`의 10년 미만 경계와 손상 JSONL 예외를 순수 함수로 재현. DB·유료 API 호출 없음.
- 미검증·남은 문제: 프로젝트 `.venv\Scripts\python.exe`가 삭제된 Python 3.12 경로를 가리켜 전체 통합 테스트와 실제 웹 화면/배치를 재실행하지 못했다. Claude의 전체 587개 통과 기록은 이번 독립 검증이 아니다. 9/29 배치 전 P1·P2 조치와 무쓰기 소표본 검증 권고.
- 다음 단계: Claude가 결과 문서의 우선순위대로 수정한 뒤 해당 사례를 다시 검수한다. Git 스테이징·커밋은 사용자가 직접 한다.

### 2026-09-28 · Claude · 업종 추출 626건(공용 DB) → final6 합침 (A 방향 2단계)

- 실행: `reports/industry_llm_new626_luna_20260928/`(luna@medium · v3 · rough · `--source shared --only-new final5`).
  - 626건 호출·실패 0, 입력 1,572,215·출력 327,846 토큰, **약 $0.71**. 단일 모델이다.
  - 결과: known 216 · unknown 409 · no_limit 1. 6,000자 발췌에서 잘린 공고 54건.
- 합침: `reports/industry_llm_full_luna_20260928_final6/`(`--merge-append`, 호출 0).
  - 2,476건 = final5 1,852(바뀐 2건은 새 결과로 교체) + 새 공고 624.
  - known 848 · unknown 1,623 · no_limit 5. 잘린 공고 66건(final5에서 18,000자로 읽고도 남은 12 + 새 54).
  - `industry_rank.load` 기준 순위에 쓸 수 있는 공고 217건(final5 174).
- 서비스는 아직 final5를 읽는다(`search/industry_rank.py` 기본값·환경 변수 `INDUSTRY_RESULTS`). 바꿀지는 사용자가 확인한다. 업종 순위는 기본 꺼짐이라 매칭 결과에는 영향이 없다.
- 남은 것: 새로 잘린 54건을 길게(18,000자) 다시 읽을지 정한다(유료).

### 2026-09-28 · Claude · 업종 추출 입력을 실험 DB → 공용 DB(읽기만)로 (A 방향 1단계)

- 요청·목적: 실험 DB(9/21 사본 1,852건) 대신 공용 DB를 읽는다. 쓰기는 없고, 계산 결과는 파일에 둔다. 업종 결과에서 빠진 최근 공고를 채우는 것이 목적이다.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py`
  - `--source shared`를 새 실행의 기본으로 했다. 공용 DB `notices`를 SELECT하고, 정규식 업종 판정은 `conditions.industry_condition()`으로 그 자리에서 계산한다. 재개·재검사는 처음 실행의 `meta.source`를 따르고, 없으면 lab이다.
  - `--only-new BASE`: 기준 결과에 없거나 문서 해시가 달라진 공고만 부른다. 합친 결과는 공고마다 `source_run`의 발췌 상한으로 문서를 다시 만들어 비교한다. 18,000자로 다시 읽은 공고를 바뀐 것으로 잘못 세지 않기 위해서다.
  - `--merge-append`: 기준에 없던 공고를 합치기에 더한다.
  - 테스트 3개를 추가했다(`tests/test_industry_llm_sample.py` 116개 통과).
- 확인(읽기만):
  - 공용 DB 2,476건 중 실험 DB에 없는 공고는 624건(기업마당 440·K-Startup 184)이다. 실험 DB에만 있는 공고는 0건이다.
  - 같은 공고의 문서는 실험 DB와 공용 DB에서 글자까지 같다(40건 대조). 프롬프트·스키마 해시도 final5와 같다.
  - `--plan` 결과: 부를 공고 626건(새 공고 624 + 제목·본문이 바뀐 2), 예상 약 $1.67(보수적 추정), 호출 없음.
- 다음 단계: 사용자 승인 뒤 luna@medium·rough로 626건을 추출하고 final5에 `--merge-append`로 합친다. 6,000자에서 잘린 공고는 이전처럼 길게 다시 읽을지 따로 정한다.

### 2026-09-28 · Claude · 업력 "못 찾음" 1,460건 표본 100건 luna 재추출

- 요청·목적: 공용 DB `notice_conditions`에서 4o-mini가 업력을 못 찾은 공고(값 없음·버림 없음·"제한 없음" 명시 아님, 1,460건)를 새 규칙과 luna로 다시 읽으면 얼마나 달라지는지 본다. 전량 재추출(약 $2) 여부를 정하기 위해서다.
- 변경 파일: `experiments/sql_semantic/age_rerun.py`에 `--missing --sample N`을 추가했다(seed 20260928, 결과 폴더 `age_rerun_luna_missing_*`).
- 결과: `reports/age_rerun_luna_missing_20260928T061903Z/`. 100건 호출·실패 0, **약 $0.14**. DB 쓰기 없음.
  - **업력 없음 97건** — 두 모델 모두 업력 조건이 없다고 봤다.
  - 새로 찾음 1건(`125335` "3년이내 창업기업이 창업교육 수료 시 …" — 신청 자격보다 우대 조건에 가깝다).
  - 다시 버림 2건: "1-3년차 스타트업"은 업력이 맞지만 "년차"가 검사 목록에 없다. "영업 개시 후 6개월"은 개월 단위라 버렸다.
- 판단: 기업마당 공고의 업력이 비어 있는 것은 대부분 **공고에 업력 제한이 실제로 없어서**다. 전량 재추출로 얻을 것은 1~3% 정도로 보여 하지 않는 편이 낫다.
- 남은 문제: "N년차" 표현은 검사 목록에 없다. 추가할지는 사소한 문제다.

### 2026-09-28 · Claude · 흐름 화면에 "③-1 매칭에 쓰는 입력"

- 요청·목적: 매칭에 어떤 입력(파라미터)을 쓰는지 흐름 화면에 정리.
- 변경 파일: `web/flow.html`에 구역을 하나 추가했다. 내용은 거르기·검색 문장·순서 다듬기·저장만 네 용도의 입력표와 고정 설정값(하이브리드·RRF k=60·후보 50·결과 10/20·order)이다. 코드(`search/app.py MatchRequest`·`build_query`, `search/applicant.py`)와 같은 사실을 옮겼다.
- 검증: 8010에서 구역 제목과 표 23행이 표시되는 것을 확인했고, 가로 넘침은 없었다. `tests.test_viewer_nav` 통과.

### 2026-09-28 · Claude · 자격 확인 업력 줄 — A(예비창업자)·B(공고문 추출 근거)

- 요청·목적: 반려동물 창업 경진대회 공고(`bizinfo:PBLN_000000000126505`)에서 예비창업자의 업력이 "확인 필요"로 나오던 문제.
- 변경 파일:
  - `search/app.py` `eligibility()`
    - **A**: 본문에 예비창업자 가능(`type_check` 통과)이면, 업력이 모름일 때도 통과로 둔다. 요구 칸에는 "업력 조건은 이미 창업한 기업에 붙는 조건"이라고 적는다. 예전에는 업력이 미달일 때만 덮었다.
    - **B**: 그 밖에 업력이 모름이면 공고문 추출 업력을 **근거로만** 보여 준다. 판정은 확인 필요 그대로다.
    - `boot()`: 업력 근거를 읽는다. 실패해도 서버를 열고 `boot_errors.age_evidence`에 남긴다.
  - `search/age_evidence.py` 신규. 공용 DB `notice_conditions` 업력 147건(SELECT)에 재추출 파일에서 되찾은 77건을 더해 224건이다.
  - `tests/test_age_evidence.py`(7개) 신규. `tests/test_match_deh.py` 시작 테스트에 업력 근거 읽기를 대역으로 넣었다.
  - `web/flow.html` 데이터 지도 문구.
- 선택 이유: 추출 값 77건 중 약 11건이 세부사업 혼합, "또는" 조건, 우대 조건이라 숫자 하나로 판정하면 틀린다. 그래서 요구 칸에 "공고문 추출(추정): 업력 최대 10년"과 근거 문장을 두고, 신청자 업력과의 비교는 "(참고)"로만 적는다.
- 검증:
  - 전체 583개 통과(건너뜀 13).
  - 8000을 재시작했다. 서버 기록 "업력 근거 224건", `boot_errors` `{}`.
  - 반려동물 공고:
    - 예비창업자: 업력 **통과**.
    - 법인 2014년 설립: 확인 필요, "최대 10년 · 12년 8개월은 범위 밖(참고)".
    - 개인 2023년 설립: 확인 필요, "범위 안(참고)".
  - 시험 화면의 자격 확인 표에서 업력 통과를 확인했다.
- 남은 문제:
  - 모집 상태도 기업마당은 칸이 없어 확인 필요로 남는다.
  - 공용 DB 반영(C-3)은 미결이다. 결과 파일은 이 PC에만 있다.

### 2026-09-28 · Claude · 업력 버림 204건 — 검사 보완(C-1)·luna 재추출(C-2)

- 요청·목적: 반려동물 창업 경진대회 공고의 업력 "확인 필요"에서 출발했다. 10단계 자격요건 추출의 업력 검사가 "사업자등록 후 1년 이상 10년 미만" 같은 실제 조건을 버린 204건을 되살린다(사용자 선택: luna).
- 변경 파일:
  - `collect/extract_conditions.py`
    - `AGE_EVIDENCE`에 표현을 더했다: 사업개시일·사업자등록일/후·창업한 지·설립된 지·영업신고 후·가동 중·N년 이내 창업기업 등.
    - `AGE_DECOY_STRONG`을 새로 두었다: 입사·근무·경력·거주·의무 운영 기간 등은 업력이 아니다.
    - 프롬프트 규칙 9에 추가한 것: 예외 조항의 연수는 쓰지 않는다. "예비창업자 또는 N년 미만"이면 기업 쪽 조건으로 기록한다.
    - 추출기 버전(`extractor_version`)은 올리지 않았다. 올리면 매일 배치가 1,864건을 다시 부른다.
  - `tests/test_extract_conditions_age.py`(5개) 신규.
  - `experiments/sql_semantic/age_rerun.py` 신규(재추출, **DB 쓰기 없음**).
- 검증:
  - 저장된 근거로 새 검사를 미리 돌렸다. 204건 중 92건이 통과하고, 기존 통과 147건은 모두 그대로다(새로 떨어지는 것 0건).
  - 전체 테스트 576개 통과(건너뜀 13).
  - 재추출 `reports/age_rerun_luna_20260928T054509Z/`: 204건 호출·실패 0, 입력 925,266·출력 117,673 토큰, **약 $0.33**.
    - 살아남 77건(반려동물 공고 `126505`: 10년 미만·예비 가능 포함).
    - 업력 없음 85건, 다시 버림 42건(개월 단위 18건 등).
- 미검증·남은 문제:
  - 살아남은 77건을 Claude가 읽었다(AI 참고). 약 11건은 한 숫자에 담기 어렵다.
    - 세부사업 둘이 섞였다(`117632` 2~3년, `119636`·`125856` 3~3년).
    - "또는" 조건이다(수출초보 "창업 5년 이내 **또는** 수출실적 8천달러 이하" 4건).
    - 우대·혜택 조건이다(`117751` 금리 감면 7년, `126019` 항공료 50%).
  - 다시 버림 중 일부("운영실적 1년 이상" 6건, "영업자 시작일로부터 1년")는 실제 업력일 수 있다.
  - **공용 DB 반영(C-3)은 하지 않았다.** 반영하려면 사용자 승인이 필요하다. 또 매일 배치의 `already_done`이 추출기 버전으로 걸러, luna 결과를 4o-mini가 다시 덮어쓰지 않도록 함께 고쳐야 한다.
- 다음 단계: 반영 방식을 결정한다. 추천은 자격 판정(통과/미달)이 아니라 "근거 표시(B) + 추정"으로 쓰는 것이다.

### 2026-09-28 · Claude · 흐름 화면에 데이터 지도

- 요청·목적: 테스트하던 것(실험 DB·결과 파일)과 원래 DB가 어떻게 나뉘어 있는지 한눈에 보기. 계기는 기업마당 반려동물 경진대회 공고의 업력 "확인 필요"(API에 업력 칸 없음 + 10단계가 "사업자등록 후 1년 이상 10년 미만"을 찾았지만 검사에서 버림 + 서비스는 10단계 결과를 안 읽음).
- 변경 파일:
  - `web/flow.html`: ⓪ 데이터 지도 구역을 추가했다. 그림(SVG), 데이터별 표, 어긋나는 곳 4가지를 넣었다. 그 밖에 다음을 고쳤다.
    - ② A를 "일부 — K-Startup만"으로 바꿨다.
    - A2(10단계 자격요건, 연결 안 됨)를 추가했다.
    - 적합도 표기를 순위 점수로 바꾸고, 테스트 수를 571로 고쳤다.
  - `experiments/sql_semantic/viewer.py` `/api/flow`: 신청자 유형 파일의 줄 수와 마지막 배치 시각을 더했다(파일만 읽는다).
- 조회 수치(읽기만):
  - 공용 DB: 공고 2,476건(기업마당 2,041건은 API 업력 칸이 모두 빔), `notice_conditions` 1,864건(전부 gpt-4o-mini, 업력 버림 233건 중 "근거에 업력 표현이 없음" 204건).
  - 실험 DB: `lab_notices` 1,852건(마지막 실행 9/21).
- 검증: `tests.test_viewer_nav` 5개 통과. 8010을 재시작해 화면·실시간 숫자를 확인했고, 가로 넘침이 없었다.
- 남은 문제: 정본 결정(판정 결과를 DB에 저장할지, 파일로 복사할지)은 팀과 정한다. 업력 표시 A·B(비용 없음)와 10단계 재추출 C(luna 여부)는 사용자 결정을 기다린다.

### 2026-09-28 · Claude · 오후 변경 검수 지적 8건 수정

- 요청·목적: [Codex 검수 결과](reviews/integration/UNREVIEWED_CHANGES_REVIEW_20260928.md)의 P1 2·P2 4·P3 2를 커밋 전에 고친다.
- 작업 전 상태: 지적 8건을 코드에서 모두 사실로 확인했다.
- 변경 파일:
  - 검색 서비스: `search/app.py`(boot 장애 격리·보조 벡터 조회 예외·공개 경로 `_public`·health).
  - 신청자 유형: `search/applicant_types.py`(등록 사업자 규칙 문맥), `collect/applicant_type_daily.py`(날짜당 상한·실패 재시도 상한).
  - 매일 배치·수집 상태: `collect/daily_pipeline.py`(`stage_warnings`·종료 코드 4), `run_daily.bat`(주석), `search/collection_status.py`, `web/collection_status.html`.
  - 화면·Git: `web/app.html`(순위 점수 표기), `.gitignore`.
  - 테스트: `tests/test_match_deh.py`, `test_applicant_type_daily.py`, `test_applicant_types.py`.
  - 문서: [응답](reviews/integration/UNREVIEWED_CHANGES_REVIEW_RESPONSE_20260928.md).
- 전후 차이·선택 이유:
  - 벡터 DB·임베딩이 서버 시작 때 죽어 있어도 서버가 열리고 BM25 단독으로 답한다.
  - 11단계 실패는 status를 'partial'로 바꾸지 않는다. 바꾸면 수집 상태 판정이 매칭을 막기 때문이다. 대신 경고와 종료 코드 4로 알린다.
  - 등록 사업자 규칙 67건을 한 줄씩 읽었고, "마감일 내 등록 완료" 1건을 예외로 빼 66건이 됐다(AI 참고).
- 검증:
  - `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` → 571개 통과(건너뜀 13).
  - 실제 서비스(재시작 후) 예비창업자·경기·친환경 생활용품: `top=100`은 20건, `offset=10`은 10건, 기본은 10건. blocked 177·restored 9.
  - 시험 화면에 "순위 점수 0.86", 수집 상태 화면에 "후처리(LLM) 경고: 없음"이 나온다.
  - DB 쓰기·유료 호출 없음.
- 미검증·남은 문제:
  - 실제 장애(Chroma 중단) 상황의 서버 시작은 가짜 의존성 테스트로만 확인했다.
  - 11단계 실패 시 매칭을 막을지는 운영 결정이다.
- 다음 단계: Codex 재검수, 사용자 커밋.

### 2026-09-28 · Codex · 오후 변경 커밋 전 검수

- 요청·목적: [Claude 요청서](reviews/integration/UNREVIEWED_CHANGES_REVIEW_REQUEST_20260928.md)의 미검수 변경을 `data-collection/` 범위에서 검토.
- 변경 파일: [검수 결과](reviews/integration/UNREVIEWED_CHANGES_REVIEW_20260928.md), 문서 지도 `README.md`, 상태·이력 문서만 작성. 코드·DB·Git 스테이징/커밋 변경 없음.
- 판정: P1 2건, P2 4건, P3 2건. 매칭 초기화·보조 벡터 조회 예외와 일일 유료 호출 상한·실패 상태를 우선 수정할 필요가 있다. 구체적 재현·근거는 검수 결과 참조.
- 검증: `python -X utf8 -m unittest tests.test_applicant_type_daily tests.test_sql_semantic tests.test_applicant_type_llm tests.test_industry_groups tests.test_label_score` → 121개 통과. 임시 공고 5건·가짜 호출로 같은 날 `limit=2` 배치를 두 번 실행해 총 4호출 확인. 전체 테스트용 `.venv`는 없어진 Python 3.12 경로를 가리켰고, 시스템 Python에 FastAPI가 없어 서비스 통합 테스트를 실행하지 못했다. 실제 DB·Chroma·유료 API 호출 없음.
- 다음 단계: Claude 수정 후 특히 하이브리드 부분 장애·일일 호출 수·11단계 오류 기록의 회귀 검증.

### 2026-09-28 · Claude · 매일 배치 11단계 — 신청자 유형 추출

- 요청·목적: 오늘 전량 결과(2,476건) 뒤에 새로 수집되는 공고도 신청자 유형 판정을 갖게 한다.
- 변경:
  - `collect/applicant_type_daily.py` 신규. `run_batch()`는 출처 DB 공고의 발췌 해시를 누적 결과와 비교해 새 공고·바뀐 공고만 LLM을 부른다(전량 실행과 같은 문서·프롬프트·코드 검사).
    - 누적 파일 `data/applicant_types/results.jsonl`. 없으면 전량 결과로 시작해 같은 공고를 다시 부르지 않는다.
    - 성공한 호출은 `checkpoint.jsonl`에 바로 적고, 다음 실행이 반영한다. 하루 상한 300건(약 $0.25), 넘치면 다음 날로 미룬다. `--plan`은 호출 없이 할 일만 보여 준다. DB 쓰기 없음.
  - `collect/daily_pipeline.py`: 10단계(자격요건) 뒤 **11단계**. 옵션 `--skip-applicant-types`·`--applicant-types-limit`, 로그와 출력에 결과를 남긴다. 실패해도 앞 단계는 끝나 있다.
  - `search/applicant_types.py` `default_path()`: 환경 변수 → 매일 누적 파일 → 전량 결과 순서.
  - `README.md` 배치 단계·옵션, `docs/FLOW.md`, 전체 흐름 화면. `tests/test_applicant_type_daily.py` 신규 5개.
- 검증: 전체 561개 통과(건너뜀 13).
  - 실제로 11단계를 단독 실행했다: 대상 2,476 · 이미 있음 2,476 · 호출 0 · $0. 누적 파일이 생겼다.
  - 서비스가 누적 파일을 읽을 때 판정 분포가 전과 같았다(blocked 183 · allowed 289 · implied 1,702 · 모름 302, 등록 사업자 규칙 67).
- 주의: 누적 파일은 배치 PC의 `data/`에만 있다. 서비스는 서버를 켤 때 읽으므로, 배치 뒤 서버를 다시 켜야 반영된다(BM25와 같다). EC2 서비스에는 이 파일이 없어 기능이 꺼진다(배포 시 옮기거나 DB 저장 결정 필요).

### 2026-09-28 · Claude · 신청자 유형 애매·누락 8건 원문 대조와 등록 사업자 규칙

- 요청·목적: Codex가 지목한 애매 5건(P044·P047·P055·P086·P090)과 LLM이 놓친 3건(P084·P085·P089)을 원문과 대조했다. 이어서 사용자 승인으로 놓침을 줄이는 규칙을 넣었다.
- 대조 결과([문서](reviews/applicant_type/APPLICANT_TYPE_AMBIGUOUS_CHECK_20260928.md)):
  - 지금 게이트가 잘못 빼는 경우는 0건이다. P055는 뒤로만 보내며, 이것이 적절하다.
  - 놓침은 6건이다(P044·P047은 LLM이 맞았지만 weak, P084·P085·P086·P089는 LLM이 판정하지 못함). Codex 블라인드도 P044·P047·P086을 과소 판정했다.
- 변경: `search/applicant_types.py` `registered_only()`.
  - 예비창업자 판정이 언급 없음이나 weak 불가이고 varies가 아닌 공고에 적용한다.
  - 저장된 근거 문장에 등록 사업자 전용 표현(사업자등록증명원 상의 소재지·사업자 미등록 제외·정상가동 중·영업활동을 하고 있는·등록을 필한·신고서 제출 완료 등)이 있으면 **불가 추정(뒤로)**으로 올린다. 빼지 않는다.
  - "예비·없이·무관·예정"이 있으면 올리지 않는다. '가능' 판정은 바꾸지 않는다.
  - 자격 확인의 '지원대상 유형' 요구 칸에 "등록 사업자 대상으로 보임(추정 · 표현)"과 근거를 보여 준다.
  - `tests/test_applicant_types.py` +3(놓친 6건 문장, 올리면 안 되는 문장, 언급 없음·weak만 올림·가능/varies 불변).
- 결과: 2,476건 중 67건이 올라갔다(weak 불가 47 + 언급 없음 20). 놓친 6건이 모두 포함된다. 예비창업자 판정 분포는 blocked 183 · allowed 289 · implied_no 1,702 · 모름 302이다. LLM·DB 호출 0.
- 검증: 전체 556개 통과(건너뜀 13). 실제 서비스에서 `...117316` 의성군 운전자금 자격 확인이 "등록 사업자 대상으로 보임(추정)"과 근거를 표시하는 것을 확인했다.

### 2026-09-28 · Claude · 업종 순위 기본 끄기 · 신청자 유형(예비창업자) 게이트 연결

- 요청·목적: [Codex 블라인드 판정 결과](reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md)를 보고 사용자가 결정했다.
  ① 업종 순위는 끈다(가안). ② 신청자 유형은 추천대로 연결한다.
- ① `search/app.py` `MatchRequest.demote_industry` 기본 True → **False**. 판정에서 밀린 공고 34건 중 11건(업종 쌍 32개)이 부당하게 밀렸다. 허가·상품 조건·창업 예정 업종·역할 갈래를 신청자 업종 제한으로 읽은 경우다.
  코드와 평가(`eval/industry_rank_check.py`는 명시적으로 켜고 끔)는 그대로 두었다. `industry_rank.py` 머리말에 이유를 적었다. 테스트는 규칙 시험 시 명시적으로 켜게 했고, 기본 꺼짐 테스트 1개를 추가했다.
- ② `search/applicant_types.py` 신규. `reports/applicant_type_llm_full_20260928T023916Z/results.jsonl`(환경 변수 `APPLICANT_TYPES_RESULTS`)을 서버 시작 시 읽는다. 없으면 기능이 꺼진다.
  - 매칭(`/api/match`, 신청자가 **예비창업자**일 때만, `use_applicant_types` 기본 True):
    - 본문 '예비창업자 불가' + 강한 근거 + 세부사업 공통 → 정형 필터에서 뺀다(이유 "예비창업자 불가(공고 본문)"). Codex 30/30.
    - 본문 '가능' → API 업력 칸의 예비 불가를 덮어 되살린다. Codex 9/9.
    - '불가 추정' → 빼지 않고 뒤로 보낸다. 우선순위는 시·도 → 시·군·구 → **추정** → 업종 → 집단.
    - 약한 불가와 개인/법인은 쓰지 않는다. 응답에 `applicant_types`(blocked·restored·implied_demoted), 결과별 `rules.pre_founder_implied_no`.
  - 자격 확인(`/api/eligibility`): '지원대상 유형'을 이 값으로 판정한다. 예비창업자는 불가=미달·가능=통과·추정/모름=확인 필요이고, 근거 문장을 설명에 적는다.
    본문 가능이면 API 업력 미달을 통과로 바꾸고 요구 칸에 "공고 본문 우선 · API 업력 칸: …"을 적는다. 개인/법인은 근거만 참고로 보여 주고 판정은 하지 않는다.
  - `tests/test_applicant_types.py` 신규 9개.
- 검증: 전체 553개 통과(건너뜀 13).
  실제 서비스(8000, 예비창업자·경기·친환경 생활용품):
  - 본문 불가로 **177건 제외**, API 업력 칸을 덮어 **9건 되살림**(`kstartup:179011` 경기도여성창업보육센터 등), 불가 추정 24건을 뒤로 보냈다.
  - 필터 통과는 1,717 → 1,595건이고, 상위 10 중 2건이 바뀌었다. 빠진 2건은 모두 불가 추정(소상공인 대상, 섬유·의류 소재기업 대상)이었다.
  - `kstartup:179011` 자격 확인: 지원대상 유형 통과, 업력 통과(본문 우선), 접수기간 미달(9/15 마감).
- 남은 것:
  - Codex가 사후 점검에서 지목한 애매한 판정(P044·P047·P055·P086·P090)과 LLM이 놓친 명시 불가(P084·P085·P089)는 사람 검토 전이다.
  - 표본 기준 A 30/30은 183건 전량 보증이 아니다. 운영에서 빠진 공고와 근거를 관찰해야 한다.
  - 결과 파일 이후 새로 수집된 공고는 판정이 없다(예전처럼 동작한다). EC2에는 배포하지 않았다.

### 2026-09-28 · Claude · 기획서 대조 B — 실험 경로의 지역·업종·규모 제외를 순위 신호로

- 요청·목적: 실험 경로(`experiments/sql_semantic/search.py`)가 지역을 SQL `WHERE`로, 지역·업종·기업 규모 불충족을 파이썬에서 **제외**했다. 기획서 4-2·5-3과 기능정의서 R-2·R-3(게이트는 유형·업력·접수기간, 지역·업종은 순위)과 서비스(`search/app.py`)에 맞춘다.
- 변경:
  - `search.py`:
    - `build_filter`: 지역 조건을 없애 SQL은 마감만 거른다(지역 값은 계속 가져온다).
    - `evaluate`: 4값(checks, excluded, unsure, demote)을 돌려준다. `HARD_FIELDS`(업력·접수기간) NO만 제외하고, `SOFT_FIELDS`(지역→업종→규모) NO는 demote.
    - `rank`: 지역·업종·규모 불일치 순으로 뒤로 보내고 `rank_reason`에 "… 불일치 → 뒤로"를 적는다. 결과에 `demoted_by`, `counts.demoted`, `demoted_examples`.
  - `fixtures.py`: 후보 0건 사례(fx-case03)를 지역 불일치 대신 마감 지난 공고로 만든다.
  - `viewer.py` `drop_split`에 `demoted`, `web/verify.html` 단계표("조건 제외 (업력·접수기간)", "그중 뒤로 보냄").
  - `compare_input.py` 입력 쓰임 설명, `experiments/sql_semantic/README.md` 설계 원칙.
  - 테스트(`test_sql_semantic.py`): 옛 설계를 고정하던 7개를 새 설계로 고쳤다. 지역은 SQL 필터가 아니고, 지역·업종·규모 불일치는 남고 뒤로 가며, 0건은 마감으로 만든다. 지역 불일치 순위 테스트 1개를 추가했다.
- 검증: 전체 543개 통과(건너뜀 13). 검증 화면 fixture에서 fx-case01은 제외 1(업력)·뒤로 1(지역), fx-case03은 0건(접수기간)이다.
- 주의: 예전 결과 폴더(`reports/sql_semantic_*`)의 수치는 옛 방식(지역 제외)이다. 새로 돌리지 않았다(실험 DB 실행은 사용자 요청 시).

### 2026-09-28 · Codex · 신청자 유형·업종 밀림 블라인드 판정

- 요청·목적: Claude의 [판정 지시서](reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_TASK_20260928.md)에 따라 신청자 유형 게이트와 업종 순위의 안전성을 독립 평가한다. AI 참고 판정이며 사람 정답이 아니다.
- 작업 전 상태: `reports/label_pack_20260928/`의 공개 신청자 자료 93건·업종 자료 34건, 숨김 LLM 답이 분리되어 있었다. 관련 코드·DB와 기존의 다른 수정은 건드리지 않았다.
- 변경 파일: 같은 꾸러미에 `applicant_labels.jsonl`(93건), `industry_labels.jsonl`(34건), 채점기가 생성한 `score.md`·`score.json`; [결과 문서](reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md). `docs/README.md`·`docs/STATUS.md`에 위치와 상태를 반영했다.
- 전후 차이·선택 이유: 공개 자격 문장으로 두 라벨 파일을 먼저 확정했다. 이후 숨김 답을 열어 독립 판정과 LLM의 일치·불일치를 계산했다. 원 블라인드 라벨은 대조 후 수정하지 않아 판정 절차를 보존했다.
- 검증: ID·상태값·원문 근거 포함·업종 질문 코드 누락을 검사해 93/93·34/34 통과. `python -X utf8 experiments/sql_semantic/label_score.py reports/label_pack_20260928` 성공. 예비창업자 strong 불가 30/30, API 충돌 9/9, 업종 잘못 밀림 11개 공고·32개 업종쌍, 불명확 2쌍. 점수는 LLM과의 일치이지 사람 정답 대비 정확도가 아니다.
- 미검증·남은 문제: 사후 자체 점검에서 `P044`·`P047`·`P086` 등 원 판정 수정 후보 확인. `I003` 등 업종은 제품·허가 요건을 별도 확인해야 한다. 사람 검수 전 운영용 정답으로 확정하거나 업종 순위 안전성을 승인하지 않는다.
- 다음 단계: [결과 문서](reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md)의 수정 후보와 부당 밀림 목록을 사람이 판정한 뒤, 명시적 불가 게이트와 업종 순위의 적용 범위를 결정한다. 코드·DB·Git 스테이징/커밋은 변경하지 않았다.

### 2026-09-28 · Claude · 매칭 결과 기획서 맞춤 — D(10+10건)·E(대체 검색)·H(적합도)

- 요청·목적: 기획서 대조 D·E·H. 필터 선행 매칭(A)이 Codex 승인을 받아 `search/app.py`를 고칠 수 있게 됐다.
- 변경 파일: `search/app.py`
  - **D**: `MatchRequest.top` 기본 3 → 10, `offset` 추가, 누적 최대 `MAX_CANDIDATES=20`(offset을 쓸 때만 자름. 평가 스크립트의 큰 top은 그대로).
    결과마다 `rank`(전체 순위)·`display_type`(1~3 card, 나머지 list), 응답에 `offset`·`top`·`has_more`. 검색 깊이는 `max(offset+top, 50)`.
  - **E**: 질의 인코딩·Chroma 의미 검색·BM25를 각각 try로 감쌌다. 임베딩 쪽 실패는 `BM25단독`, BM25 실패는 `임베딩단독`, 둘 다 실패는 필터 통과 공고의 `마감임박순`(잠정)이다.
    응답에 `fallback_used`·`fallback_mode`·`search_errors`를 넣고 stderr에도 원인을 남긴다. dense 방식도 의미 검색이 실패하면 BM25로 간다. 정형 필터는 모든 경로에서 돈다. 유사도가 없는 경로는 `score`·`band`가 None이다.
  - **H**: `fit_score` = 이번 경로의 RRF 점수 ÷ 이론 최대값. 하이브리드는 (w_dense+w_bm25)/(k+1), 한쪽이면 그 한쪽의 1위 점수다. 마감임박순은 None. 응답 `fit_basis`에 기준을 적는다.
  - `web/app.html`(8000 시험 화면): `top:10`, 카드 3 + 리스트 7, "10건 더 보기"(offset), 대체 검색 안내 배너, 적합도 표시.
  - `tests/test_match_deh.py` 신규 9개: 쪽수·20건 상한·큰 top, 정상 경로 fit=1.0, 인코딩/Chroma/BM25/둘 다 실패, 대체 경로에서 필터 유지.
    `tests/test_query_ablation.py`의 기본값 안전장치 기대값을 3 → 10으로 고쳤다(query_ablation은 top을 직접 넘겨 수치 영향 없음).
  - 문서: `PLAN_ALIGNMENT` D·E·H 해결 표시, `FLOW.md`, 전체 흐름 화면.
- 검증: 전체 541개 통과(건너뜀 13).
  - 실제 서비스(8000, 로컬 DB·Chroma): 필터 통과 1,740건 중 첫 조회 10건(rank 1~10, card 3), `offset=10`은 11~20위(겹침 0), `has_more` false, `offset=20`은 0건, 1위 fit 0.898, 대체 경로 없음.
  - 화면에서 "제조 법인" 예시로 카드 3 + 리스트 7, "10건 더 보기" 뒤 리스트 04~20위, 버튼 사라짐을 확인했다.
  - 대체 경로는 실제 서버에서 오류를 일으켜 보지 않았다(단위 테스트로 확인).
- 남은 것: 수집 상태(F)를 매칭 앞에 연결하는 일은 배치 위치·24시간 기준 결정 뒤로 미룬다. EC2에는 배포하지 않았다(사용자 판단).

### 2026-09-28 · Claude · Codex 판정 지시서·꾸러미 (신청자 유형 · 업종 밀림)

- 요청·목적: 신청자 유형 게이트 연결과 업종 순위 안전성 판단에 쓸 독립 판정(AI 참고 정답)을 Codex에게 요청한다.
- 변경 파일:
  - `experiments/sql_semantic/label_pack.py` 신규: 판정 꾸러미를 만든다(DB 읽기만). 판정지에는 발췌만 넣고, LLM 답은 `answers_hidden.jsonl`에 따로 둔다(블라인드).
  - `experiments/sql_semantic/label_score.py` 신규: 표준 라이브러리만 쓰는 채점. 게이트 안전(예비 불가 strong의 정답률과 "가능" 오류), B 본문 우선, 약한 불가, 개인/법인, 불가 추정, 놓침, 업종 잘못 밀림을 계산한다.
  - `tests/test_label_score.py` 3개.
  - [지시서](reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_TASK_20260928.md) 신규, 문서 지도에 `reviews/applicant_type/` 추가.
- 꾸러미 `reports/label_pack_20260928/`: 신청자 유형 93건과 업종 34건.
  - 신청자 유형 묶음: A 30/183 · B 9/9 · C 15/87 · D 9/9 · E 20/1,632 · F 10/262. 93건 모두 LLM이 본 발췌와 같다(document_sha256).
  - D는 20건을 목표로 했지만, 개인/법인 불가 공고 대부분이 예비 불가(A)에 먼저 들어가 9건이다. A 안의 개인/법인 판정도 채점에 포함된다.
  - 업종 34건은 최신 평가 `industry_rank_check_20260928T031858Z`의 밀린 공고 전부다. 발췌는 지금 출처 DB로 다시 만들었다(9/18 스냅샷과 조금 다를 수 있음).
- 검증: 채점 테스트 3개 통과. OpenAI 0, DB 쓰기 0.
- 다음: Codex 판정 → `label_score.py` → 결과 문서(같은 폴더) → 게이트 연결 설계.

### 2026-09-28 · Claude · Codex 통합 재검수 새 P1(허용 갈래 누락) 수정

- 요청·목적: [통합 재검수](reviews/integration/CURRENT_PROGRESS_REVIEW_RECHECK_20260928.md)의 새 P1. LLM의 `list_complete`만 믿어, 원문에 있는 다른 허용 갈래("또는 수출 기업" 등)가 빠진 공고 5건이 업종 불일치로 밀렸다. 추가 확인 3건도 포함한다. 같은 재검수에서 필터 선행 매칭(A)의 P2 두 건은 **승인**됐다([재검수](reviews/matching/MATCH_FILTER_FIRST_REVIEW_RECHECK_20260928.md)).
- 변경: `search/industry_rank.py` `branch_problem()`. 허용값을 지운 근거 문장에 갈래 단서(또는·~의 경우·①② 등)나 다른 대상(농업인·소상공인·수출 등)이 남으면 순위에 쓰지 않는다. 소재지 "본사 또는 공장"은 예외다.
  `industry_groups.SECTION_PHRASES`에 KSIC 26·27 공식 명칭(C)을 추가했다. 테스트는 `test_industry_rank.py`에 반례 5건과 예외 1건, `test_industry_groups.py`에 1줄을 더했다.
- 결과: 순위 대상 255 → 174건. 지적 7건은 모두 비교 불가가 됐고, `...120877`은 `{C}`만 남았다. 재평가 `reports/industry_rank_check_20260928T031858Z/`(서비스 깊이 50)에서 불변식 위반 0건, 밀린 공고 58 → 34건.
- 정정: 신청자 유형 "API 불가인데 본문에 예비창업자 명시 9건"은 명시 8건과 "누구나" 1건(`kstartup:179162`)이다. 이전 항목의 표현을 이 기록으로 정정한다.
  P3은 "안내 보강만, `reports/` 원본 링크 6개는 여전히 깨져 있다"가 정확한 상태다.
- 검증: 전체 529개 통과(건너뜀 13). OpenAI 호출 0, DB 쓰기 0.
- 남은 것: 밀린 34건의 업종 추출 독립 판정(Codex 재검수 요청). 업종 순위의 안전성 승인은 그 뒤다.

### 2026-09-28 · Claude · 수집 상태 판정 (기획서 대조 F) — 매칭 연결 전

- 요청·목적: 기획서 대조 F. 기능정의서 R-1 ①("소스 응답 실패 → collectionStatus='실패', 조용한 실패 금지")과
  R-3 ②("'실패' 또는 최종 수집 24시간 초과 → 매칭을 진행하지 않고 수집 상태 경고", E-C2-STALE)를 구현한다.
  Codex 재검수 중이라 `search/app.py`는 건드리지 않고, 판정 모듈과 화면만 만들었다.
- 변경 파일: `search/collection_status.py` 신규.
  - `judge()`는 순수 함수다. 실패는 기록 없음·최근 배치 error·출처 partial·기업마당 스냅샷 재사용, 지연은 마지막 저장 24시간 초과, 그 밖은 정상이다. 실패·지연이면 `block_matching=True`.
  - `check()`는 공용 MySQL `import_runs` 최근 행(SELECT만)과 배치 로그 `data/collect_log.jsonl`의 최근 pipeline 행을 읽는다. 로그가 없으면 DB만으로 판정한다.
  - `history()`는 저장 이력과 "멈췄을" 구간을 계산한다.
  - `experiments/sql_semantic/viewer.py`: `/api/collection-status`·`/collection-status`, 메뉴 "수집 상태". `web/collection_status.html` 신규. 전체 흐름 화면 ① 구역에 지금 상태를 표시한다.
  - `tests/test_collection_status.py` 신규 11개. `docs/FLOW.md`에 한 줄 추가.
- 확인(실제 DB·로그, 읽기만): 지금은 **정상**이다. 마지막 저장은 2026-09-28 09:00 KST(3.3시간 전), 두 출처 모두 ok.
- 발견: 이 규칙을 `import_runs` 20회(9/8~9/28, 19.9일)에 적용하면 **매칭이 멈췄을 시간이 233.3시간(약 49%)**이다.
  간격은 9/10→9/14 89시간, 9/18→9/21 72시간, 9/22→9/28 144시간이다. 배치를 돌리는 PC가 꺼져 있던 기간으로 보인다(주말 등).
  또 매일 09:00 실행은 전날 저장과의 간격이 24시간을 몇 초 넘기도 한다(9/15→9/16 24시간 12초). 이 경우 몇 초씩 "지연"이 된다.
- 검증: 전체 528개 통과(건너뜀 13). 브라우저에서 `/collection-status` 내용·이력 표를 확인했고 콘솔 오류는 없었다.
- 남은 것(사용자·팀 결정):
  1. 배치를 계속 켜져 있는 곳(EC2 등)으로 옮길지. 옮기지 않으면 규칙대로 주말마다 매칭이 멈춘다.
  2. 24시간 기준에 예약 시각 흔들림을 흡수할 여유(예: 26시간)를 둘지. 기능정의서 수치를 바꾸는 일이라 팀 확인이 필요하다.
  3. `/api/match` 연결(재검수 뒤): 멈춤이면 매칭하지 않고 `collectionStatus`와 경고를 돌려준다.

### 2026-09-28 · Codex · Claude 수정 재검수와 업종 허용 갈래 누락 발견

- 요청·목적: Claude가 통합 검수와 정형 필터 선행 매칭 P2를 수정한 뒤 사용자 재검수 요청.
- 변경 파일: [통합 재검수](reviews/integration/CURRENT_PROGRESS_REVIEW_RECHECK_20260928.md), [매칭 재검수](reviews/matching/MATCH_FILTER_FIRST_REVIEW_RECHECK_20260928.md) 신규. 문서 지도와 STATUS에 판정·남은 문제를 반영했다. 서비스 코드·저장 결과는 수정하지 않았다.
- 확인: P1 재개 모드 거부를 완료된 전량 폴더(2,476 ID)로 직접 호출해 확인. 업종 평가 348쌍의 실제 서비스 깊이 50, 전체 후보 깊이 100000, `식품기업`의 순위 대상 제외를 확인. 업종 평가의 밀린 공고 58건을 근거 문장과 대조해 허용 갈래가 빠진 공고 5건(Top 10 이탈 22쌍)을 찾았다. 보고서의 "57건" 표기는 실제 58건과 다르다. 신청자 유형 전량 2,476행과 게이트용 192건·API 대조 363건/차이 68건을 읽기 전용 재계산했다.
- 검증: 시스템 Python에서 신청자 유형 7개·업종 분류 17개, FastAPI 라우트 메모리 대역으로 정형 필터 선행 13개·업종 순위 10개 통과. 전체 517개와 실제 DB·Chroma·HTTP·EC2는 이 환경의 Python 의존성 문제로 독립 재현하지 못했다. `git diff --check -- data-collection` 통과.
- 다음: Claude는 업종 허용 목록의 누락 갈래를 저장 원문으로 재검증하고 보수적으로 순위 대상에서 제외하거나 오프라인 후처리한 뒤 서비스 조건 평가를 다시 실행한다. 정형 필터 선행 P2 두 건은 승인. Git 스테이징·커밋·push는 하지 않았다.

### 2026-09-28 · Claude · Codex 통합 검수 P1·P2·P2·P3 수정

- 요청·목적: [통합 검수](reviews/integration/CURRENT_PROGRESS_REVIEW_20260928.md)의 수정 요청 네 건. 응답은 [응답서](reviews/integration/CURRENT_PROGRESS_REVIEW_RESPONSE_20260928.md).
- 변경:
  - `applicant_type_llm.py`: `run_spec.json`을 남기고, 재개 모드·대상 검사(`check_resume`)를 결과를 쓰기 전에 한다.
  - `eval/industry_rank_check.py`: 서비스 조건(top=10, 깊이 50)과 전체 후보 호출을 분리했다. 불변식 3을 추가하고 밀린 공고에 원문 근거를 붙였다.
  - `industry_groups.allowed_sections`: 제조업은 "제조·생산·가공…"이나 KSIC 코드가 있어야 순위에 쓴다. 순위 대상은 273 → 255건.
  - 인계서 경로를 고치고, `reports/search_comparison_*` 3곳에 `DOCS_MOVED.md`를 두었다.
  - 테스트: `test_applicant_type_llm.py` +2, `test_industry_groups.py` 반례를 추가했다.
- 검증: 전체 517개 통과(건너뜀 13). 재평가는 `reports/industry_rank_check_20260928T025746Z/`에 있고, 서비스 응답 깊이 50 × 348쌍, 불변식 위반 0건이다.
- 남은 것: 밀린 공고 57건의 업종 추출 정확성은 독립 판정 전이다. Codex 재검수를 요청했다.

### 2026-09-28 · Claude · 신청자 유형 LLM 추출 — 전량 2,476건과 결과 화면

- 요청·목적: 표본 뒤 사용자가 전량 실행과 "서버를 켜서 눈으로 확인할 수 있는 화면"을 요청했다.
- 실행: `applicant_type_llm.py --all --workers 8`(gpt-5.6-luna@medium). 2,476건(기업마당 2,041 · K-Startup 435) 성공, 실패 0.
  토큰 입력 5,791,539 · 출력 743,682, **약 $2.05**(단가 추정). 약 25분 걸렸다. DB 쓰기 0. 결과는 `reports/applicant_type_llm_full_20260928T023916Z/`.
- 결과(검사 후):

  | 유형 | 가능 | 불가 | 불가 추정 | 언급 없음 | 검사로 내림 |
  |---|---:|---:|---:|---:|---:|
  | 예비창업자 | 289 | 274(strong 185) | 1,635 | 278 | 184 |
  | 개인사업자 | 152 | 45(strong 30) | — | 2,279 | 33 |
  | 법인 | 200 | 25(strong 15) | — | 2,251 | 44 |

  세부사업별로 다름 78건. 게이트가 쓸 수 있는 "확실한 불가"(varies 아님 + strong)가 있는 공고는 **192건**이다.
- K-Startup API 업력 칸과 대조(LLM이 판정한 363건): 일치 295 · 불일치 68.
  - API는 가능인데 LLM은 불가 추정: 57건. 본문 대상이 "업력 N년 미만 창업기업"인 경우다.
  - API는 가능인데 LLM은 불가(명시): 2건.
  - **API는 불가인데 본문에 예비창업자가 명시(LLM 가능): 9건.** 지금 게이트가 예비창업자에게서 잘못 빼는 공고다. 예: 한라대 창업보육센터 "예비창업자 또는 창업 7년 미만", 달서구 중장년 기술창업센터, 앤틀러 "개인 예비 창업자".
- 눈 검토: strong 불가 표본은 근거가 맞았다. weak 불가에는 맞는 것("사업자 미등록 업체 제외")과 틀린 것("영리 및 비영리 법인사업자"를 법인 불가로, "예비창업자"를 법인 불가로)이 섞여 있어, 게이트용 값에서 weak를 빼는 설계가 필요하다.
  "근거에 사업자·창업 관련 말이 없음"으로 내린 114건 중 97건은 불가 추정이다. 농가·여행사·스타트업·소공인 같은 말이 검사 단어 목록에 없어서 내려갔다. 보수 쪽 오류이며, 목록을 넓힌 오프라인 재검사는 후속으로 남긴다.
- 화면: 검증 서버 `/applicant-types`(메뉴 "신청자 유형"). `experiments/sql_semantic/applicant_type_results.py`(읽기 전용), `web/applicant_types.html`, `viewer.py` `/api/applicant-types`·`/api/applicant-types/runs`, `tests/test_applicant_type_ui.py` 4개.
  숫자 칸 필터, 출처·예비창업자 판정·개인/법인 명시·게이트 사용 가능·API/기존값 불일치·검사로 내림 필터, 근거·판단 이유·원문 링크를 보여 준다. 실행 중인 폴더는 진행 건수를 보여 준다.
  전체 흐름 화면의 G 상자도 갱신했다.
- 남은 것: 게이트 연결은 하지 않았다. 연결은 명시 불가(strong)를 필터로, 불가 추정은 순위·확인 필요로, 본문의 "예비창업자 가능"이 API 업력 칸보다 우선하게 한다. 연결 전에 Codex 판정과 안전 확인이 필요하다.

### 2026-09-28 · Codex · 진행분 통합 검수 문서화

- 요청·목적: 사용자가 현재 진행분 리뷰를 Claude가 볼 수 있는 문서로 남기도록 요청했다.
- 변경 파일: [통합 검수 결과](reviews/integration/CURRENT_PROGRESS_REVIEW_20260928.md) 신규, 문서 지도·STATUS에 위치와 수정 대기 상태 추가. 서비스 코드·평가 결과·실행 중인 checkpoint는 수정하지 않았다.
- 검수: 신청자 유형 전량 재개 시 `--all` 누락으로 표본 결과를 같은 폴더에 쓸 수 있는 경로(P1), 업종 평가 `top=100000`과 실제 서비스 깊이 차이(P2), `식품기업`의 제조업 단정과 저장 평가의 5쌍 순위 변경(P2), 문서 이동 뒤 링크(P3)를 확인했다. 업종 분류 17개와 신청자 유형 검사 5개가 시스템 Python에서 통과했다. `git diff --check -- data-collection` 통과.
- 미검증·다음: `.venv` 실행 파일 불일치와 시스템 Python의 `fastapi` 부재로 서비스 통합 테스트를 독립 재현하지 못했다. Claude가 P1을 먼저 수정하고 P2를 수정·재평가한 뒤 재검수를 요청한다. Git 스테이징·커밋·push는 하지 않았다.

### 2026-09-28 · Claude · 신청자 유형(예비창업자·개인사업자·법인) LLM 추출 — 표본 60건

- 요청·목적: 기획서 대조 G(지원대상 유형 정형화)를 업종 때 방식으로 가져올 수 있는지. 사용자가 표본 60건 실행을 승인했다(잔액 약 $9, 필요하면 학원 지원 $300).
- 작업 전 발견: 매일 배치 추출기(`collect/extract_conditions.py`, gpt-4o-mini)가 이미 `notice_conditions.business_type`·`pre_startup_allowed`를 기업마당 1,864건에 채우고 있었다. 그러나 게이트는 이 값을 쓰지 않는다.
  근거가 공고당 한 문장(대개 지원 금액 문장)이라 확인할 수 없고, 표본에서 오판이 보였다("정선군 소재 중소 제조기업" → 법인만, "법인사업자이어야 함" → 예비창업자 가능).
  전체 첨부 본문 검색(DB 읽기)으로 보면 "법인에 한함" 30건 대부분이 제출 서류 설명이었다. 개인·법인을 실제로 가르는 공고는 드물다.
- 변경 파일: `experiments/sql_semantic/applicant_type_llm.py` 신규. 업종 v3처럼 유형마다 status(가능·불가·불가 추정[예비만]·언급 없음)와 원문 근거를 받고,
  코드가 근거 원문 존재·제출 서류 문맥·지원 내용 문맥을 검사한다(`industry_llm_sample`의 `loose_found`·`quote_role` 재사용).
  게이트용 값은 varies가 아니고, 자격·제외 머리말 아래(strong)의 "불가"만 쓴다. `tests/test_applicant_type_llm.py` 신규 5개.
- 실행: gpt-5.6-luna@medium, 기업마당 40 + K-Startup 20(seed 20260928). 성공 60 · 실패 0, 토큰 입력 138,075 · 출력 18,144, **약 $0.049**(단가 추정, 청구액 아님). DB 쓰기 0.
  결과는 `reports/applicant_type_llm_20260928T023631Z/`.
- 결과(사람 정답 없음, 눈 검토):
  - 예비창업자: 가능 11 · **불가(명시) 7** · 불가 추정 39 · 언급 없음 3. 명시 불가 7건은 모두 근거가 맞았다("사업자등록증 보유", "사업자등록을 하고 영업 중이어야만", "사업자 미등록 업체 제외" 등).
    그중 3건을 기존 4o-mini는 "예비창업자 가능"으로 적었다.
  - 개인사업자·법인: 60건 중 명시가 2건뿐이고 둘 다 "개인 또는 법인 모두 가능"이었다. **개인/법인을 가르는 제한은 표본에 없다.** G의 실익은 예비창업자 쪽이다.
  - K-Startup API 업력 칸과 대조하면 일치 12 · 불일치 6 · LLM 모름 2였다. 불일치 5건은 API가 "예비창업자"까지 나열했는데 본문 대상은 "업력 7년 미만 창업기업"이어서 LLM이 불가 추정으로 본 경우다.
    나머지 1건(`kstartup:179011` 경기도여성창업보육센터)은 반대였다. **API 업력 칸이 "3년미만"뿐이라 지금 게이트가 예비창업자에게서 빼는데, 본문에는 "여성 예비창업자"가 대상으로 명시돼 있다.** 지금 게이트가 잘못 빼는 사례다.
  - 불가 추정(39)은 "본사·공장이 소재한 중소기업"처럼 대부분 타당하다. 다만 "개인, 개인사업자, 작목반, 법인"(군산 로컬푸드)처럼 사업자가 아닌 개인이 포함된 경우도 불가 추정으로 봤다. 추정은 탈락 근거로 쓰지 않는다.
- 미검증·다음: Codex 판정 대조와 전량 실행(예상 약 $2)은 사용자 결정 대기. 게이트 연결 전에 안전 확인이 필요하다.

### 2026-09-28 · Claude · 업종 순위 반영 (허용 목록 밖이면 뒤로) — "가" 방식 안전 확인

- 요청·목적: F2와 A안 결정 뒤 업종을 매칭 순위에 반영. 효과 측정은 "가"(잘못된 순서가 생기지 않는지만)로 하기로 사용자가 정했다. 평가 질의 66개 중 업종이 들어간 질의가 6개뿐이라 효과를 잴 정답이 없다.
- 변경 파일:
  - `search/industry_rank.py` 신규 — 업종 결과 파일(기본 `reports/industry_llm_full_luna_20260928_final5/results.jsonl`, 환경 변수 `INDUSTRY_RESULTS`)을 서버를 켤 때 읽는다.
    known · 목록 완전 · 잘림 없음 · 통합공고 아님 · 허용값 전부 KSIC 대분류인 공고만 쓴다. 파일이 없으면 규칙이 꺼진다.
  - `search/app.py` — `MatchRequest.demote_industry`(기본 True), `Weights.penalty_industry`(score 방식, 잠정 0.5).
    order 방식 우선순위는 다른 시·도 → 다른 시·군·구 → **업종 목록 밖** → 대상 집단이다. LLM 추출이라 지역보다 약하게 뒀다.
    응답에 `industry`(신청자 대분류·활성 여부·출처·대상 공고 수), `industry_demoted`, 결과별 `rules.off_industry`를 추가했다. `boot()`가 업종 표를 읽는다.
  - `experiments/sql_semantic/industry_groups.py` `allowed_sections` — 분야·산업·관련·연관·유관·전후방·수출이 들어간 허용값이 있으면 비교 불가(None). 아래 확인에서 찾은 반례 때문이다.
  - `search/applicant.py` 설명 한 줄, `docs/FLOW.md` 매칭 흐름·우선순위.
  - 테스트: `tests/test_industry_rank.py` 신규 10개, `test_industry_groups.py` 반례 추가.
  - `eval/industry_rank_check.py` 신규 — 정상 질의 58개 × 대표 업종 6개(제조·음식점·정보통신·농업·건설·도소매)로 규칙을 끈 결과와 켠 결과를 비교한다(region_eval과 같은 방식).
- 확인 결과(실제 DB·Chroma, OpenAI 0, DB 쓰기 0):
  1. `industry_rank_check_20260928T021254Z` — **무효**. 응답을 `top=50`으로 받아 밀린 공고가 잘려 나가 "빠짐" 위반 324건으로 보였다. 스크립트 착오이며 폴더에 NOTE.md를 남겼다.
  2. `…T021723Z`(후보 전체를 받도록 수정) — 위반 0건. 순위 대상 329건. 밀린 공고를 눈으로 검토하다 오판 3종을 찾았다.
     "IT 서비스·솔루션 분야"(디캠프, J로만 읽혀 24쌍에서 밀렸고 그중 주제 판정 2가 10쌍), "의료·바이오 산업" → Q(실제는 의료기기 제조), "농림축산식품 수출업체" → C.
  3. `…T022212Z`(범위가 넓은 표현 제외 후, **현재 기준**) — **불변식 위반 0건**(빠지는 공고 없음, 밀린 공고는 모두 확실한 불일치). 순위 대상 273건 / 공고 2,476건.
     상위 10이 바뀐 (질의, 업종) 쌍은 업종별로 17~36쌍 / 58쌍(제조 17, 음식점 30, 정보통신 29, 농업 29, 건설 36, 도소매 29)이다. 밀린 공고는 여행업·음식점·제조기업·게임 등 업종이 분명히 적힌 공고였다.
- 미검증·남은 문제: 사람 정답이 없어 순위가 **좋아졌는지는 모른다**. 업종 추출 자체도 사람 검증 전이다.
  눈 검토에서 애매한 것 1건: `kstartup:179241` SDGs 소셜벤처 챔피언십 "1인 미디어 콘텐츠 창작자"(한 부문만일 가능성). 효과 측정("나" 방식: 평가 질의에 업종을 채우고 Codex 판정)은 하지 않았다.
- 검증: 전체 테스트 506개 통과(건너뜀 13). 서비스(8000)·EC2에는 배포하지 않았다(EC2에는 업종 결과 파일이 없어 배포해도 규칙이 꺼진다).

### 2026-09-28 · Claude · 전체 흐름 화면 (`/flow`)

- 요청·목적: 지금까지 만든 것의 흐름을 눈으로 확인하고 싶다는 사용자 요청.
- 변경 파일: `web/flow.html` 신규. `experiments/sql_semantic/viewer.py`에 `/flow`, `/api/flow`(업종 순위 신호 수·최신 평가 폴더, 파일만 읽음)를 추가하고, 메뉴 맨 앞에 "전체 흐름"을 넣었다. `tests/test_viewer_nav.py` +1.
- 화면 구성: ① 공고 모으기(매일 배치 5단계) ② 공고 조건 정리(업력·마감, LLM 업종, KSIC 묶음, 신청자 유형) ③ 매칭(`/api/match` 6단계와 뒤로 보내는 순서 4가지, 자격 확인) ④ 확인·평가(화면·스크립트·최근 결과) ⑤ 기획서 대비 남은 것(B~H·ML·검수 대기).
  상자마다 한 줄 설명, 담당 파일, 상태(완료·일부·연결 안 됨·미구현)를 적고, 9/28에 바뀐 곳은 파란 테두리로 표시했다. 좁은 화면에서는 세로로 쌓인다.
- 검증: 브라우저에서 `/flow`를 열어 확인했다. 숫자 연결, 상자 넘침 0, 가로 스크롤 없음, 콘솔 오류 없음. 긴 상태 표시가 상자 밖으로 넘치던 것을 고쳤다.
- 한계: 상태·설명은 손으로 적은 것이라 코드가 바뀌면 이 파일도 고쳐야 한다(`docs/FLOW.md`와 같은 원칙).

### 2026-09-28 · Claude · docs 폴더 정리와 문서 지도

- 요청·목적: docs 폴더가 지저분하다, 정리하고 Codex가 헷갈리지 않게 해 달라는 사용자 요청.
- 변경: `docs/` 맨 위에 흩어져 있던 49개 항목(파일·폴더)을 `specs/`(기획서·기능정의서), `guides/`(FIELD_MAP·QUERIES·SCHEDULER·TEAM_DATA·VERIFY_UI·구조도),
  `reviews/<matching|industry|search|sql_semantic|ui|chroma>/`(작업 지시·검수 요청·검수 결과), `ml/`, `deliverables/`(docx, `_qa_claude_*` → `_qa/`), `archive/`(9/14·9/22 인계서)로 옮겼다.
  맨 위에는 STATUS·WORKLOG·FLOW·PLAN_ALIGNMENT·최신 인계서만 남겼다. **지운 파일은 없다.**
- 링크: 스크립트로 저장소 안 `.md`·`.py`·`.html`의 상대 링크와 `docs/…` 경로 문자열 약 180곳을 새 위치로 고쳤다(`reports/`·`data/`는 결과 보존 원칙에 따라 손대지 않음).
  이동 뒤 깨진 링크를 검사해 0건을 확인했다. 이동 전부터 깨져 있던 `guides/FIELD_MAP.md` → `collect/normalize.py` 링크도 고쳤다.
- Codex 혼동 방지:
  - `docs/README.md`(문서 지도) 신규: 먼저 읽을 5개, 폴더별 내용, 주제별 검수 상태, 새 문서 이름·위치 규칙, 옛 경로 → 새 경로 안내.
  - `AGENTS.md`: 작업 시작 0단계로 문서 지도를 읽게 하고, "새 검수·지시 문서는 `docs/reviews/<주제>/`에, `docs/` 맨 위에는 만들지 않는다"는 문서 위치 규칙을 추가했다.
  - 재검수 대기 중인 [요청서](reviews/matching/MATCH_FILTER_FIRST_REVIEW_REQUEST_20260928.md) 끝에 이동 사실과 결과 파일 위치를 적었다. 인계서의 재검수 확인 경로도 새 위치로 고쳤다.
- 검증: 전체 테스트 506개 통과(건너뜀 13). 코드가 문서 파일을 실행 중에 읽는 곳은 없다(주석·문자열만 있음).
- 주의: Git에서는 삭제 + 추가로 보일 수 있다. 커밋할 때 `git add -A docs`로 올리면 이동으로 인식된다(사용자 판단).

### 2026-09-28 · Claude · 검증 화면(8010) 공통 메뉴

- 요청·목적: 진행했던 화면을 메뉴를 눌러 오가고 싶다는 사용자 요청.
- 변경 파일: `experiments/sql_semantic/viewer.py` — `NAV` 목록과 `page(filename, current)` 추가. 화면을 내려보낼 때 `<body>` 바로 뒤에 메뉴 막대를 끼운다.
  대상은 검증 화면(`/`)·검색 방식 비교(`/compare`)·매칭 순서 비교(`/filter-first-eval`)·업종 추출 결과(`/industry-results`)·업종 강조 실험(`/industry-probe`)이고, 현재 화면에 `aria-current="page"`를 단다.
  HTML 파일은 고치지 않았다. 자체 시험 화면(`/compare/selftest`)에는 메뉴를 넣지 않는다. 새 화면은 `NAV`에 한 줄만 더하면 된다.
  메뉴는 위에 고정(sticky)되고, 좁은 창에서는 다음 줄로 넘어간다.
- `tests/test_viewer_nav.py` 신규(4개).
- 검증: 전체 495개 통과(건너뜀 13). 브라우저에서 서버를 다시 켜 메뉴 클릭으로 `/`→`/industry-results` 이동과 현재 화면 표시를 확인했다. 다섯 화면 모두 메뉴 1개·현재 표시 1개, 콘솔 오류 없음.
- 남은 것: 일부 화면 본문의 옛 바로가기 링크(예: 업종 추출 결과의 "검증 화면 · 방식 비교 · 업종 강조 실험")는 그대로 두었다. 서비스(8000, `search/app.py`) 화면은 대상이 아니다.

### 2026-09-28 · Claude · 제외 업종 비교 방식 결정(A안) 기록과 '증기' 오분류 수정

- 요청·목적: F2에서 발견한 "제외 목록은 대분류로 비교하면 안 된다" 문제에 대한 사용자 결정.
- 조사(final5, 읽기만): 제외 목록이 있는 공고 370건(excluded_only 242, known 91, unknown 30, conditional 7). 주제별 공고 수는 사행·도박 174, 도소매 특정 품목(담배 중개·총포·모피 도매 등) 146, 유흥·주점 125, 사치·향락 포괄 122, 금융·보험·대부 89, 부동산 54.
  대부분 소상공인 정책자금 제외 업종 목록을 옮겨 적은 세부 업종이다. 대분류 이름 그대로인 제외값("부동산업", "숙박 및 음식점업")은 소수이고, "금융업"(KSIC 64)처럼 대분류 일부인 경우가 섞여 있다.
- **결정(사용자): A안 — 업종 순위에는 허용 목록만 쓰고 제외 목록은 쓰지 않는다.** B안(대분류 전체 제외만)·C안(세부 코드 비교)은 채택하지 않았다. 평가 뒤 필요하면 B안을 덧붙일 수 있다.
- 변경 파일: [PLAN_ALIGNMENT_20260928.md](PLAN_ALIGNMENT_20260928.md) 순위 반영 표의 `excluded_only` 행과 근거, `industry_groups.py` 머리말, STATUS.
- 수정: `industry_groups.py` D 핵심어 `'증기'` → `'증기공급'`. `신용보증 기관에서 보증을…`이 '보증기관'의 '증기'로 D가 되던 오류다. `전기, 가스, 증기 및 수도사업`은 공식 명칭 규칙으로 계속 D가 된다. 테스트 2줄 추가, `tests.test_industry_groups` 17개 통과.
- 영향: F1-2(제외표 참조문)는 순위와 무관해져 화면 정확도 문제로만 남는다.

### 2026-09-28 · Claude · F2 업종 코드 맞추기 (KSIC 대분류 규칙 보강·신청자 업종 변환)

- 요청·목적: 사용자가 업종 작업 중 F2부터 시작하기로 함. 업종 순위 반영([기획서 대조](PLAN_ALIGNMENT_20260928.md) 2절)은 신청자 주 업종과 공고 업종이 같은 코드여야 성립한다.
- 작업 전 상태: final5 허용값 1,798개 중 미분류 167개, 제외값 2,104개 중 미분류 611개. 공식 복합 명칭이 가운뎃점·및에서 쪼개져 M 을 잃음(`전문·과학 및 기술서비스업 → X`). 신청자 입력을 대분류로 바꾸는 함수 없음.
- 변경 파일: `experiments/sql_semantic/industry_groups.py`
  - 나누기 전에 공식·복합 명칭을 찾아 표시(`SECTION_PHRASES`) — 띄어쓰기·가운뎃점·쉼표 무시
  - KSIC 세부 번호(3~5자리, `390 …`, `(5616)`, `47811 중 …`)를 믿는다. 면적(`330평방미터`)·산재보험 코드·`100대`·연도 모양은 뺀다. 이름과 다른 대분류면 기존처럼 `?`
  - 괄호 밖 본문으로 대분류를 정하고, 괄호 안은 "…포함"일 때만 덧붙인다(`(전력)반도체 … 제조기업`이 D 를 얻지 않게)
  - 뜻이 분명한 핵심어 보강(측량·편의점·주점·노래방·카센터·금형·발전사업자·파견 등). `마트`·`슈퍼`·`법률`은 조각 전체일 때만(`스마트`, 법 이름). `청소`→`청소업`(청소년), `증기탕` S(기존 D 오류)
  - 새 함수 `applicant_section(text)`: 신청자 입력 → 대분류 하나 또는 None(대분류 문자 입력도 받음). `allowed_sections(texts)`: 공고 허용 목록 → 대분류 집합, 값 하나라도 표준 대분류가 아니면 None(비교 불가)
- `tests/test_industry_groups.py`: +6개(복합 명칭, 세부 번호, 미분류 보강, 걸리면 안 되는 부분 문자열, 신청자 변환, 허용 목록 비교 가능 여부).
- 전후 차이(final5 값 전체, 규칙만 다시 적용):

  | | 표준 대분류 | 분야 X | 미분류 | 모호 ? |
  |---|---:|---:|---:|---:|
  | 허용값 1,798 전 → 후 | 1,357 → 1,433 | 267 → 256 | 167 → 100 | 0 → 2 |
  | 제외값 2,104 전 → 후 | 1,445 → 1,842 | 24 → 13 | 611 → 211 | 0 → 14 |

  `known` 616건 중 허용 목록 전체가 표준 대분류로 바뀌는 공고 406 → 421, 그중 목록 완전·잘림 없음 428건 기준 322 → 329.
  이미 묶이던 값의 변화 약 50개를 하나씩 읽었다: 개선(예: `전문·과학 및 기술서비스업` X→M, `회계서비스업` X→M, `자동차학원` C→P, `증기탕` D→S, `(56212)` 번호로 I) 또는 번호·이름 충돌로 `?`(`3402 … 수리업`, `52992 화물운송 중개…`, `(91249)`, `(63999-1)`).
  남은 미분류 100개는 대부분 분야·모호 표현(`디스플레이`, `ADAS`, `수출`, `관련 기업`, `전∙후방 업종`)이라 규칙을 넣지 않았다.
- **설계상 발견 — 제외 목록은 대분류로 비교하면 안 된다**: 제외값은 `유흥주점업`·`약국`·`골프장`처럼 세부 업종이다. 대분류(I·G·R)로 올리면 일반 음식점·편의점·체육시설 신청자까지 "제외 목록 안"이 된다. 승인된 순위 규칙의 `excluded_only` 행은 세부 업종 수준 비교(글자·세부 KSIC 번호)가 필요하며, 이 결정은 사용자에게 남긴다. 허용 목록은 대분류 비교가 보수적이다(대분류가 같으면 감점하지 않는 쪽으로만 틀린다).
- 검증: `.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` → 491개 통과(건너뜀 13). LLM·DB·결과 폴더 쓰기 없음. `reports/`의 결과 파일은 바꾸지 않았다(묶음은 화면이 읽을 때 규칙으로 계산).
- 미검증·남은 문제: 사람 정답 없이 눈으로 읽은 검토뿐이다. F2-2(화면의 재독 수·"허용값 총수/미분류 값 수" 표시)는 하지 않았다. 순위 반영 자체는 미구현.
- 다음 단계: 제외 목록 비교 수준 결정 → F1-2 제외표 참조문 → 업종 순위 반영 구현·평가.

### 2026-09-28 · Claude · 종료 인계서 작성 (계정 전환 전)

- 요청·목적: 사용자가 Claude 계정을 바꿔(대화 맥락이 이어지지 않을 수 있음) 새 세션이 이어받을 문서가 필요하다고 판단.
- 변경 파일: [NEXT_SESSION_HANDOFF_20260928.md](archive/NEXT_SESSION_HANDOFF_20260928.md) 신규, STATUS 맨 위에 진입점 추가.
- 내용: 기준 문서·담당 범위, 사용자 결정 3가지, 오늘 작업과 검수 상태, 현재 매칭 동작, 남은 일(B~H·업종), 미커밋 변경 목록, 실행 방법, 금지 사항, 첫 요청문.
- 코드 변경·LLM·DB 호출 없음. Git은 사용자 담당.

### 2026-09-28 · Claude · 불일치 A — Codex 검수 P2 두 건 수정

- 요청·목적: [Codex 검수](reviews/matching/MATCH_FILTER_FIRST_REVIEW_20260928.md)가 최종 승인 전 수정으로 둔 P2 두 건.
- 변경 파일: `search/app.py`(`match()`가 필터 통과 공고가 있을 때만 인코딩·검색, 응답 `dense_error`·실행한 단계만 담은 `pipeline`;
  `_dense_within()`이 ids 미지원 TypeError 와 그 밖의 오류를 구분해 stderr·응답에 원인 기록), `tests/test_match_rules.py`(+2, 기존 1개 보강),
  [요청서](reviews/matching/MATCH_FILTER_FIRST_REVIEW_REQUEST_20260928.md) 6절 재검수 요청.
- 검증: 전체 485개 통과(건너뜀 13). `eval/filter_first_eval.py` 재실행 수치 동일(`reports/filter_first_eval_20260928T011252Z/`).
  EC2 읽기 전용 SSH: chromadb 1.5.9, `query`에 `ids` 인자 있음, `search/app.py` 미배포.
- 미검증: EC2에서 필터 질의·대신 계산 시간 측정(공용 서버 실행은 사용자 승인 필요). 임베딩 오류 시 BM25 단독 폴백은 불일치 E로 남음.
- 다음 단계: Codex 재검수. Git은 사용자 담당.

### 2026-09-28 · Claude · 매칭 순서 비교 화면에 쉬운 말 용어 전환

- 요청·목적: P@3·쓸모@3·미판정@3 같은 용어가 어렵다는 사용자 요청. 기존 용어는 그대로 두고 쉬운 이름 버전을 함께 제공.
- 변경 파일: `web/filter_first_eval.html` — 상단 "쉬운 말 / 전문 용어" 전환(기본 쉬운 말, 선택은 localStorage 에 기억, 실패해도 동작).
  쉬운 이름: 신청 못 하는 공고 비율 · 내용 적합도 · 쓸모 있는 추천 수 · 채점 못 한 비율 · 하한/상한 → 보수적/낙관적 · 95% 구간 → 믿을 수 있는 범위.
  전문 용어 모드는 서버 label(eval/filter_first_eval.py METRICS)을 그대로 쓴다.
- 검증: 브라우저에서 두 모드의 타일·표·질의 요약·설명 문구 전환 확인, 콘솔 오류 없음, 조사 어색함("공고은") 수정 후 0건. `tests/test_filter_first_ui.py` 통과.

### 2026-09-28 · Claude · 매칭 순서 비교 화면 (`/filter-first-eval`)

- 요청·목적: 검색 먼저 vs 필터 먼저 비교 결과를 사이트에서 직접 확인하고 싶다는 사용자 요청.
- 변경 파일: `eval/filter_first_eval.py`(results.json 에 질의 요약·공고 제목/마감/업력 조건·신청 불가 이유·판정값 추가),
  `experiments/sql_semantic/filter_first_results.py` 신규(읽기 전용, 폴더 이름 정규식 검사), `experiments/sql_semantic/viewer.py`
  (`/api/filter-first-eval`, `/filter-first-eval`), `web/filter_first_eval.html` 신규, `tests/test_filter_first_ui.py` 신규(4개).
- 화면: 비교 방식 설명 → 핵심 4지표 타일(95% 구간으로 개선/차이 없음/악화 표시) → 전체 지표표(쉬운 설명) →
  질의별 예전·지금 상위 10 나란히(신청 불가 이유, 내용 판정, 새로 들어옴/빠짐). 기본은 "예전에 신청 불가가 있던 질의" 21개.
- 재실행: 결과 → `reports/filter_first_eval_20260928T004842Z/`. 수치는 첫 실행(004448Z)과 같다(재현 확인). 첫 실행 폴더도 화면에서 ID만으로 열린다.
- 검증: 전체 테스트 483개 통과(건너뜀 13). 뷰어를 다시 켜서 화면 렌더링·콘솔 오류 없음·가로 넘침 없음 확인, 질의별 목록 DOM 확인
  (예: q001 예전 1위 "1인 창업가 캠프"는 업력 3년 미만 공고라 신청 불가 → 지금 목록에서 빠짐).
- 다음 단계: 없음. Git은 사용자 담당.

### 2026-09-28 · Claude · 검색 먼저 vs 필터 먼저 수치 비교 (A안, 판정 보충 없음)

- 요청·목적: 매칭 순서를 바꾼 것이 더 나은지 숫자로 보고 싶다는 사용자 요청. 미판정 공고를 LLM으로 채우지 않는 A안(비용 0)으로 먼저.
- 변경 파일: `eval/filter_first_eval.py` 신규(예전 코드를 `git show 35358be:.../search/app.py`로 불러와 같은 STATE·질의 벡터·기준일로 비교,
  말뭉치는 2026-09-16 전 수집 2,084건으로 제한, 지표: 신청 불가@10·P@3(2) 하한/상한·nDCG@10·쓸모@3/@10 하한/상한·미판정),
  `tests/test_filter_first_eval.py` 신규(3개), [기획서 대조](PLAN_ALIGNMENT_20260928.md) 3-1절, 검수 요청서 4-1절.
- 결과: `reports/filter_first_eval_20260928T004448Z/`. hybrid 신청 불가@10 4.8%→0% [−0.067, −0.029], P@3(2) 하한 62.6%→60.3%(구간 0 포함),
  쓸모@3 하한 1.810→1.810. dense 신청 불가@10 5.9%→0%, 쓸모@10 하한 +0.155 [+0.069, +0.276]. 미판정@3 10~12%.
  P@3 감소 2.3%p는 예전 상위 3에 있던 "내용 판정 2이지만 신청 불가" 4칸(174칸 중)과 같다.
- 검증: 지표 단위 테스트 통과. 실행은 실제 Chroma·공용 DB 읽기, OpenAI 0, DB 쓰기 0. 요약표의 `95%%` 오타는 코드와 결과 파일 모두 고쳤다.
- 미검증·남은 문제: 미판정@10(hybrid 31%)이 높아 @10 지표는 참고. 판정 기준(topic_rel)은 내용만 보므로 신청 가능 여부는 규칙(prefilter)으로 따로 매겼다.
  평가 질의 신청자가 대부분 업력이 짧아 신청 불가 비율이 낮게 나온다(앞선 10년 차 법인 사례는 상위 10 중 5~6건).
- 다음 단계: Codex 검수(요청서 4-1). 필요하면 B안(미판정 LLM 보충)은 비용 확인 후 사용자 결정.

### 2026-09-28 · Codex · Claude 필터 선행 매칭 검수

- 요청·목적: 사용자 요청과 [Claude 검수 요청](reviews/matching/MATCH_FILTER_FIRST_REVIEW_REQUEST_20260928.md)에 따라 불일치 A의 구현·계약·평가 영향을 독립 검토.
- 작업 전 상태: Claude의 `search/app.py`, `search/gate.py`, `search/hybrid.py` 및 관련 테스트·문서가 미커밋 상태. 기존 변경은 수정하지 않음.
- 변경 파일: [검수 결과](reviews/matching/MATCH_FILTER_FIRST_REVIEW_20260928.md) 신규, STATUS 판정 기록, WORKLOG 이 항목.
- 판단: 필터 통과 ID 안에서만 두 검색을 하는 핵심 구현은 확인. 통과 후보 0건이어도 인코더를 먼저 실행하는 P2, Chroma 오류를 모두 대량 벡터 조회로 전환하는 P2를 기록. 최종 승인은 수정·회귀 확인 뒤. 접수 시작 전 공고는 명시된 R-3의 종료일 기준과 일치한다.
- 검증: 로컬 Python에서 FastAPI 최소 대역으로 `FilterFirstTests` 11개 통과. 인코더 오류 대역과 전체 마감 공고로 빈 후보 계약 위반 재현. 로컬 정규화 스냅샷 1,734건 중 17건은 2026-09-28 이후 접수 시작.
- 미검증·남은 문제: 전체 475개, HTTP 테스트, 실 Chroma·DB 비교, EC2 버전·성능은 독립 재현하지 못함. 기존 검색 평가 수치는 새 파이프라인 기준으로 다시 측정할 필요가 있다.
- 다음 단계: Claude가 두 P2를 수정하고 빈 후보·예외 경로 테스트를 추가하면 재검토. Git staging·commit·push는 사용자 담당.

### 2026-09-28 · Claude · 업종 결과 화면의 결과 폴더 목록 정렬

- 요청·목적: `/industry-results`의 결과 폴더 목록이 섞여 있어 보기 힘들다는 사용자 요청.
- 원인: `list_runs()`가 폴더 이름을 거꾸로 된 문자순으로만 정렬해 표본·재독·전량·최종이 뒤섞였다.
- 변경 파일: `experiments/sql_semantic/industry_results.py`(`RUN_GROUPS`, `run_group()`, `list_runs()`가 묶음 → 만든 시각 최신순으로 정렬하고
  `run_at`·`group`·`group_label`·`current`를 돌려줌), `web/industry_results.html`(`fillRuns()`가 묶음마다 optgroup, 한국 시각·건수·★현재 기준 표시),
  `tests/test_industry_results_ui.py`(+1).
- 묶음 규칙: 합친 결과 중 이름이 `_final숫자`로 끝나면 최종, 나머지 합침은 중간 합침. 발췌 상한 6,000자 초과는 긴 원문 재독,
  전량은 전량, 그 밖은 표본. 실제 23개 폴더가 최종 5 · 전량 7 · 재독 6 · 중간 합침 1 · 표본 4로 나뉜다.
- 검증: 전체 테스트 476개 통과(건너뜀 13). 뷰어를 다시 켜고 화면의 optgroup 5개와 기본 선택 final5를 확인.
  API로 다른 폴더(long97_v3 97건, 표본 30건)가 불러와지는 것을 확인. 폴더 전환 후의 화면 렌더링은 브라우저 창이 닫혀 보지 못했다.
- 다음 단계: 없음. Git은 사용자 담당.

### 2026-09-28 · Claude · 불일치 A — 정형 필터를 검색보다 먼저 (서비스 매칭)

- 요청·목적: 사용자가 [기획서 대조](PLAN_ALIGNMENT_20260928.md)의 제안(업종 순위 반영 원칙)을 승인하고 불일치 A부터 고치라고 요청.
  기능정의서 R-3은 필터를 먼저 걸고 통과 집합 안에서만 순위를 매기며, 순서를 뒤집으면 결함으로 본다.
- 작업 전 상태: F1-1·기획서 대조 문서가 미커밋. 서비스 `match()`는 Chroma 상위 depth건 → 마감 제외 → 모자라면 depth×3 반복.
- 변경 파일: `search/gate.py`(`prefilter`, `applicant_age`), `search/hybrid.py`(`BM25.search(allowed=)`),
  `search/app.py`(`match()` 재구성, `_dense_within`, `boot()`의 `vector_ids`, `MatchRequest.structured_filter`, 응답 `filtered_count`·`filter`·`dense_path`·`pipeline`,
  `/api/eligibility`가 `applicant_age` 사용), `eval/search_comparison.py`(A단계 `structured_filter: False`),
  `tests/test_match_rules.py`(`CandidateRefillTests` → `FilterFirstTests` 11개), `tests/test_query_ablation.py`(가짜 BM25 `allowed`), `docs/FLOW.md`,
  [검수 요청](reviews/matching/MATCH_FILTER_FIRST_REVIEW_REQUEST_20260928.md) 신규, 대조 문서 A 해결·순위 원칙 확정 표시.
- 전후 차이·선택 이유: 필터는 확실한 미달만 뺀다(모집 상태 closed, 마감일 < 오늘, `_check_age` False). 설립일 미상 사업자는 게이트와 같이 아무것도 빼지 않는다.
  시작 전 공고는 R-3 문구(`applyEnd >= today`)대로 남긴다. 실제 Chroma는 색인에 없는 ID를 `query(ids=)`에 넘기면 `InternalError`를 내서(직접 재현)
  boot 때 색인 ID를 기억하고 교집합만 넘긴다. `ids` 인자가 없거나 실패하면 벡터를 꺼내 직접 코사인 계산.
- 검증:
  - `python -X utf8 -m unittest discover -s tests` **475개 통과(건너뜀 13)**.
  - 실제 Chroma(chromadb 1.5.9)·공용 DB 2,476건, HEAD `search/app.py`를 같은 프로세스에 올려 질의 3개 × hybrid/dense × top 10 비교.
    필터 통과: 예비창업자 1,717 · 2016년 설립 법인 1,548 · 2025년 설립 법인 1,758(접수 마감 706건 공통).
    이전 상위 10건 중 필터에 걸리는 공고: 2016년 법인 hybrid 6·dense 5, 예비창업자 dense 1 → 이후 모두 0. `dense_path`는 모두 `chroma`.
  - Chroma `ids=` 검색 상위 50 = 필터 통과 공고 전체 직접 계산 상위 50(두 질의, 집합·순서 동일, 거리 차 ≤ 4.2e-7).
  - DB 확인: 기업마당 모집 상태 전부 `unknown`, K-Startup 전부 `open`(마감 지난 213건 포함) → 현재 `closed` 제외는 0건.
- 미검증·남은 문제: 검색 서버·EC2에서 실행하지 않았다(EC2 chromadb 버전 미확인). `eval/` 기존 지표는 이전 순서로 잰 값이다.
  신청자 유형은 K-Startup 업력 필드의 '예비창업자' 표기로만 판정된다(불일치 G). 기본 `top=3`·10/20건은 불일치 D로 남음.
- 다음 단계: Codex 검수. 서버 재시작·배포는 사용자 판단. Git은 사용자 담당.

### 2026-09-28 · Claude · 기획서 v1.10·기능정의서 v1.9 대조, 업종 순위 신호 결정 기록

- 요청·목적: 사용자가 넣어 둔 기획서에서 이 폴더 담당 부분만 골라 현재 구현과 일치하는지 확인. 이어서 사용자가
  "기획서대로 업종은 순위 신호로" 결정하고 문서화를 요청.
- 작업 전 상태: F1-1 코드 변경·final5와 Codex 검수 문서가 미커밋. 사용자가 기획서 PDF·기능정의서 xlsx를 스테이징해 둠.
- 변경 파일: [기획서 대조](PLAN_ALIGNMENT_20260928.md) 신규, STATUS 최신 방향 항목 추가.
- 확인 방법: PDF는 `pdfplumber`로 47쪽 텍스트를 뽑아 7-1 R&R·4-2·5-3·6장·E 흐름을 읽음. xlsx는 `openpyxl`이 없어
  zip 안의 XML에서 셀 문자열을 뽑아 T-C2·G-01·R-1~R-3·오류코드·변경 이력을 읽음. 코드는 `search/app.py`·`search/gate.py`·
  `experiments/sql_semantic/search.py`·`web/app.html`을 읽고, 분야별 공고 수는 공용 MySQL `notices`를 읽기 전용으로 조회.
- 결과: 담당은 공고 데이터·매칭·자격 판정·인프라(공동). 일치 8항목, 불일치 A~H, 담당 불분명·미확정 항목을 문서 3절에 정리.
  업종 결정의 근거는 기획서 4-2·5-3과 기능정의서 R-2·R-3(담당자 협의 2026-09-22).
- 미검증: 불일치 항목은 코드 읽기로 판단했고 실행으로 재현하지 않았다. 기업마당 범위를 넓힌 결정이 문서 밖(팀 대화)에 있을 수 있다.
- 다음 단계: 순위 반영 방식 확정, 불일치 A~H 착수 순서 결정. 코드 변경·LLM·DB 쓰기 없음. Git은 사용자 담당.

### 2026-09-28 · Codex · Claude F1-1 통합공고 수정 검수

- 요청·목적: 사용자 요청과 [Claude 검수 요청](reviews/industry/INDUSTRY_F1_UMBRELLA_REVIEW_REQUEST_20260928.md)에 따라 코드·`final5`·화면 데이터 계약을 독립 검토.
- 작업 전 상태: Claude의 코드·문서 변경과 새 결과 폴더가 미커밋 상태. 기존 변경은 수정하지 않음.
- 변경 파일: [검수 결과](reviews/industry/INDUSTRY_F1_UMBRELLA_REVIEW_20260928.md) 신규 작성, STATUS에 판정과 다음 단계 기록, WORKLOG에 이 항목 추가.
- 판단: F1-1 전역 판정 방지 목표 승인. 제목에서 상위 통합공고를 참조하는 개별 공고와 챗봇 안내의 P2 오분류는 후속 수정 대상으로 기록. 업종 정형 필터 연결은 승인하지 않음.
- 검증: `final4/final5` 1,852개 ID와 의미 필드 12종 비교 → 8행의 판정·이유만 변화. 범위 표시 25행, 필터 사용 가능 0행. `industry_results.load_run()`의 기본 결과·집계 확인. 로컬 Python에서 업종 추출 113개, 업종 묶음 11개 테스트 통과.
- 미검증·남은 문제: `fastapi`가 없어 UI 테스트 및 전체 469개 통과는 독립 재현하지 못함. 브라우저 렌더링·외부 호출 감시는 하지 않음. F1-2, F2와 사람 표본 평가가 남음.
- 다음 단계: Claude의 F1-2 진행과 별도로 P2 제목 판별 반례를 테스트에 추가. Git staging·commit·push는 사용자 담당.

### 2026-09-28 · Claude · F1-1 통합공고 전역 판정 방지 + 오프라인 재검사(final5) — LLM 호출 0

- 요청·목적: [인계](archive/NEXT_SESSION_HANDOFF_20260922.md) F1-1 / [Codex 2차 후속 재검토](reviews/industry/INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md) F1.
  통합공고 보호가 `known` 분기 안에만 있어, 원답이 `unknown`+quote인 통합공고 7건은 `not_mentioned`, 1건은 `excluded_only`로 공고 전체 판정이 됐다.
- 작업 전 상태: Git 변경 없음(`.claude/`, `.idea/` 미추적만). 최신 결과 final4.
- 변경 파일:
  - `experiments/sql_semantic/industry_llm_sample.py` — `industry_status()`가 먼저 범위 무관 판정(`_status_ignoring_scope`, 기존 로직)을 내고,
    제목이 `UMBRELLA_TITLE`이면 `out['scope_unresolved']=True`를 적은 뒤 `known·no_limit·not_mentioned·excluded_only`를 `conditional`로 내린다.
    이유 문구는 `UMBRELLA_WHY`에 판정별로 둔다. `unknown`·`conditional`은 그대로 둔다(이미 통과 조건이 아니고, unknown의 이유가 더 구체적).
    제외값·허용값 자체는 지우지 않는다(어느 세부사업 것인지 모를 뿐 원문 근거는 있다).
  - `experiments/sql_semantic/industry_results.py` — 행에 `scope_unresolved` 전달. 화면 기본 결과를 `final5`로.
  - `web/industry_results.html` — 판정 칸에 `세부사업 범위 미확인` 경고 표시.
  - 테스트: `tests/test_industry_llm_sample.py` +4(raw unknown+quote, 제외값만, no_limit, 이미 unknown인 통합공고의 이유 보존), 기존 known 통합공고 테스트에 `scope_unresolved` 확인 추가.
    `tests/test_industry_results_ui.py` +1(화면 전달·옛 결과는 False).
- 선택 이유: 리뷰는 "최소 unknown, 가능하면 conditional + scope_unresolved"를 제시했다. 라벨 "조건부·세부사업별(확인 필요)"이 통합공고의 실제 뜻과 맞고,
  unknown은 "추출 실패"로 읽히므로 conditional을 택했다. 두 값 모두 통과 조건이 아니므로 매칭 안전성은 같다.
- 재검사(LLM 0, 저장 checkpoint, 기존 폴더 덮어쓰지 않음, `--profile rough`):
  1. `industry_llm_full_luna_20260922` → `reports/industry_llm_full_luna_20260928_rough_umbrella/`(counterpart strict)
  2. `industry_llm_long97_luna_20260922` → `reports/industry_llm_long97_luna_20260928_umbrella/`
  3. `industry_llm_long104_luna_20260922` → `reports/industry_llm_long104_luna_20260928_umbrella/`
  4. 합침 1+2 → `…20260928_umbrella_m1`, 합침 m1+3 → **`reports/industry_llm_full_luna_20260928_final5/`**
- 검증:
  - 테스트: 업종 3종 134개 통과. 전체 `python -X utf8 -m unittest discover -s tests` **469개 통과(건너뜀 13)**.
  - final4 ↔ final5(의미 필드 12종 비교): 1,852행·ID 집합 동일, **바뀐 행 8건이며 모두 제목이 통합공고**, 바뀐 필드는 `industry_status(_why)`뿐.
    바뀐 8건: `bizinfo:PBLN_000000000116008·119737·119738·122433·124502`, `kstartup:175783·175817`(not_mentioned→conditional),
    `bizinfo:PBLN_000000000116975`(excluded_only→conditional).
  - 출처 base 1,651 + long97 97 + long104 104(폴더 이름만 새 재검사 폴더), 토큰 6,394,949/1,472,128·원답 비용 $3.0455 final4와 동일,
    `called_this_run=0`, `db_writes=0`, `filter_ready=true` 0건, 상태/값 불변식 위반 0건.
  - final5 판정: 제한 있음 616 · 언급 없음 810 · 제외만 242 · 명시 4 · **조건부 24** · 확인 필요 156.
    통합공고 25건 = 조건부 18 · 확인 필요 7, `scope_unresolved=true` 25건(= 제목 일치 25건).
  - 화면: `verify-viewer` 실행 후 `/industry-results`가 final5를 기본 선택, 집계 타일 숫자 위와 일치, "통합" 검색 시 통합공고 행마다
    `세부사업 범위 미확인` 표시를 DOM 텍스트로 확인. 스크린샷은 창이 가려져 비어 있어 증거로 쓰지 않았다.
- 미검증·Codex 판단 요청:
  1. 제목 정규식은 `통합\s*공고`만 잡는다. `통합 모집 공고`(예: `…120933`, `…124708`, `…124926 통합 상시 모집 공고`)는 잡지 않는다.
     이들이 실제로 여러 세부사업을 묶었는지는 확인하지 않았다 — 넓힐지 판단 필요.
  2. `kstartup:175817`은 통합공고 요약본 챗봇 안내라 엄밀한 통합공고는 아니지만 제목에 걸려 conditional이 됐다(보수 쪽 오차).
  3. 세부사업별 업종을 실제로 분리하는 것(재추출)은 하지 않았다. 이번 수정은 "전역 판정을 막는 것"까지다.
- 다음 단계: Codex 검수([검수 요청서](reviews/industry/INDUSTRY_F1_UMBRELLA_REVIEW_REQUEST_20260928.md)) → F1-2 제외표 참조문 분리. Git commit·push는 사용자가 한다.

### 2026-09-22 · Codex · final4 2차 후속 리뷰 및 다음 세션 인계

- 요청·목적: Claude 세션 종료 전에 현재 업종 추출 작업을 다음 주에 바로 재개할 수 있도록 정리.
- 확인: final4 1,852건·고유 ID 1,852, 출처 base 1,651 + long97 97 + long104 104, 실패 0,
  토큰 6,394,949/1,472,128, 원답 비용 약 $3.0455. final3→final4는 long104 104건만 의미적으로 변경.
- 해결 확인: dropped 후보가 남은 `not_mentioned` 0건, 104건 재독 완료, 대표 KSIC 반례 5개 수정,
  merge 이력·토큰·비용 정상. 업종 추출·묶음 테스트 120개 통과. `/industry-results` final4 화면 직접 확인.
- 남은 리뷰: F1 통합공고 25건 중 `not_mentioned` 7·`excluded_only` 1, F1 구체 업종 없이 제외표 참조문만 가진
  `excluded_only` 25건, F2 공식 복합 명칭 분리로 M 누락 및 값 단위 미분류 167개, F2 화면의 고정 “97건 재독” 문구.
- 변경 파일: [전량 리뷰](reviews/industry/INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md)에 2차 후속 재검토 추가,
  [다음 세션 인수인계](archive/NEXT_SESSION_HANDOFF_20260922.md) 신규 작성, STATUS 최신 진입점 갱신.
- 다음 단계: 인수인계 문서의 F1-1 → F1-2 → F2 순서. 저장 checkpoint 오프라인 재검사, 새 폴더 합치기,
  화면 확인, 사람 표본 평가 전까지 DB·정형 필터 연결 금지. LLM·DB 호출, 코드 수정, Git commit·push는 이번 정리에서 하지 않음.

### 2026-09-22 · Claude · 잘린 104건 18,000자 재독 + 최종 합침(final4)

- 요청·목적: Codex 후속 리뷰 F2 — 6,000자에서 잘렸는데 긴 원문으로 다시 읽지 않은 104건. 사용자가 재독 후 Codex 재검토를 받기로 결정.
- 코드: `merge_runs` 가 여러 번 합쳐도 출처를 지키게 — 기준 행의 기존 `source_run` 유지, `merge_history` 누적. 화면은 `merge_history` 로 "다시 읽음" 표시.
  테스트 +1(두 번 합쳐도 출처·이력 유지). 전체 **464개 통과(건너뜀 13)**.
- 실행(사용자 승인, 추정 약 $0.25~0.40): final3 에서 `truncated` 이고 97건 재독에 들어가지 않은 **104건**(known 63 · excluded_only 14 · conditional 7 · unknown 20)
  → `--ids-file …/final3/truncated_6000_ids.txt --max-chars 18000 --profile rough` → `reports/industry_llm_long104_luna_20260922/`.
  호출 104·실패 0, 입력 758,173 · 출력 186,385 토큰, **토큰 기준 약 $0.375**(앞서 말한 $0.27 보다 많다 — 업종 제한이 있는 긴 공고라 추론 토큰이 늘었다).
- 합침(LLM 0): final3 + long104 → **`reports/industry_llm_full_luna_20260922_final4/`** (화면 기본). 합친 이력: long97_v3 → long104.
  토큰 6,394,949 / 1,472,128 · 원답 비용 합 약 **$3.05**.
- 결과(final4): 제한 있음 616(33.3%) · 명시 4 · 언급 없음 817(44.1%) · 제외 업종만 243(13.1%) · 조건부 16 · **확인 필요 156(8.4%)**.
  104건 변화: known 유지 46(그중 9건은 업종이 늘어남 — 예: 태백 13개 전부) · unknown 유지 14 · excluded_only 유지 12 · conditional 유지 6 ·
  known → unknown 10 · known → excluded_only 5 · unknown → known 4 · 그 밖 소수. 18,000자에서도 잘린 것 8.
- **known → unknown 10건은 모두 LLM 원답이 known 인데 검사가 내렸다**(9건 "근거 문장이 원문에 없음", 1건 규모 정의). 긴 원문에서 LLM 이 여러 줄을
  이어 붙여 근거를 만든 것으로 보인다. 규칙은 고치지 않고 Codex 재검토 항목으로 남긴다.
- 다음: Codex 재검토. DB 쓰기 없음.

### 2026-09-22 · Claude · 제외 목록 머리말 규칙(rough) — 확인 필요 333 → 150 (LLM 호출 없음)

- 요청·목적: final2 의 확인 필요 333건 중 248건이 "제외 업종 후보가 있으나 검사를 통과하지 못함". 표본을 보니 LLM 근거가 제외 목록의 **한 줄**이고
  "□ 지원 제외 대상" 머리말은 윗줄에 있었다. 사용자가 제외 머리말 규칙부터 하자고 결정.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py` — `exclusion_by_header()`: 근거 앞 원문 600자(공백 제외)에서 머리말 사건
  (`_header_events` 의 자격·지원 내용·다른 구역 + `EXCLUSION_HEADER_RE` 제외 머리말: 지원/신청/참여/융자/보증/가입 … + 제외/제한/불가, 제외·제한 + 대상/업종)
  중 **가장 가까운 것이 제외 머리말**이면 인정. 근거에 포함·허용 표현이 있으면 인정하지 않는다. **rough 에서만**, 문장 단위 연결 검사를 먼저 하고 실패할 때만.
  인정된 값에 `linked_by: header`(문장 연결은 `clause`). 테스트 +6(목록 줄 인정·strict 미적용·사이의 다른 구역·포함 표현·자격 머리말이 더 가까움·제한 머리말 어휘).
  전체 **463개 통과(건너뜀 13)**.
- 재처리(LLM 0): `…_rough_split3` + `industry_llm_long97_luna_20260922_v3` → 합침 **`reports/industry_llm_full_luna_20260922_final3/`**.
  제한 있음 628 · 명시 4 · 언급 없음 814(44.0%) · **제외 업종만 239(12.9%)** · 조건부 17 · **확인 필요 150(8.1%)**.
  확인 필요 이유: 제외 후보 미통과 65 · 검사가 내림 56 · 자격 문장 못 찾음 21 · 허용 후보 7 · 18,000자 잘림 1.
  머리말 규칙으로 인정된 제외 값 1,831개(공고 269). 제외 업종 상위: 잎담배 도매업 · 도박기계 제조업 · 담배 중개업 · 성인용품 판매점 · 금융업 ·
  보험 및 연금업 · 부동산업 · 유흥주점업 · 모피제품 도매업 — 정책자금 공고의 표준 제외 업종 목록과 같은 모양.
- 눈 확인: 머리말 규칙 인정 공고 10건 무작위 — 9건은 "지원제외업종"·"지원제외대상"·"특례보증제한업체" 같은 실제 머리말 아래 목록. 1건은
  "국가연구개발사업 참여제한에 해당하는 경우"라는 **문장 속 표현**을 머리말로 잡았다(값 "단순 유통업"은 실제 제한 대상으로 보여 결과는 맞음).
  → 한계: 제외 머리말 정규식은 문장 속 "제한"도 잡을 수 있다. 정확도는 재지 않았다(Codex 30건 표본은 제외 업종 판정이 적다).
- 화면: 새 결과(`_final3`)를 기본으로. DB 쓰기 없음.
- 남은 선택지: 잘린 104건 재독(약 $0.25) · 통합공고 세부사업 분리(재추출) · 새 표본 검증(Codex 판정).

### 2026-09-22 · Claude · Codex 후속 리뷰(러프·KSIC·매칭용 판정) F1×3·F2×2 반영 — LLM 호출 없음

- 근거: [전량 리뷰 후속 재검토](reviews/industry/INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md#후속-재검토--러프-검사ksic-묶음매칭용-판정18000자-재독-2026-09-22).
- 변경 파일:
  - `experiments/sql_semantic/industry_llm_sample.py` `industry_status()`:
    F1 — 제외 업종 **후보**(검사에서 빠진 것 포함)나 허용 업종 후보가 있었으면 `not_mentioned` 로 올리지 않고 `unknown`.
    F1 — 새 판정 **`conditional`(조건부·세부사업별)**: 제목에 "통합공고"가 있는 known, "전 업종"이 구체 업종과 섞인 known. 전역 필터로 쓰지 않는다.
    F2 — 발췌가 상한에 닿았으면 판정과 상관없이 `truncated=True`·`list_complete=False`, 이유에 잘림을 적는다. `verify_v3`·`verify_for` 에 `title` 전달.
    F2 — `merge_runs` 가 토큰도 합산하고 prompt/schema 해시·모델·검사 강도가 다르면 거부, 응답 모델 합집합으로 `mixed_models`.
  - `experiments/sql_semantic/industry_groups.py` F1: 분류 번호는 KSIC·분류번호·산업분류가 밝혀졌거나 "C24"형일 때만 믿는다("(72)" 무시).
    "및·또는·쉼표·가운뎃점"으로 나눈 조각마다 **가장 뒤 핵심어**로 대분류 하나. 수산 양식(양식장·양식업·패류 양식·어가) → A.
    번호와 이름이 다르면 `?`(모호). 구 규칙(제조업 관련 서비스업·산업용 기계 수리)은 나누기 전에 본다.
  - `industry_results.py`·`web/industry_results.html`: `conditional` 판정·"발췌 잘림" 표시, 새 최종 결과(`_final2`)를 기본으로.
  - 테스트 +12(제외 후보 → unknown, 허용 후보 → unknown, 통합공고 → conditional, 조건부 전 업종, 잘린 known 표시, 합치기 토큰·모델 거부,
    KSIC 반례 6·번호 문맥·모호·머리 핵심어). 전체 **457개 통과(건너뜀 13)**.
- 재처리(LLM 0): `…_rough_split2`(전량 재검사) + `industry_llm_long97_luna_20260922_v2`(97건 재검사) → 합침 **`reports/industry_llm_full_luna_20260922_final2/`**.
  토큰 5,636,776 / 1,285,743 · 원답 비용 합 $2.6702 · 혼합 모델 아님.
- 결과(final2): 제한 있음 628(33.9%) · 명시 없음 4 · **언급 없음 814(44.0%)** · 제외 업종만 56 · **조건부 17** · **확인 필요 333(18.0%)**.
  확인 필요 이유: 제외 업종 후보가 검사를 못 넘음 **248** · 검사가 내림 56 · 자격 문장 못 찾음 21 · 허용 후보 7 · 18,000자에서도 잘림 1.
  발췌 잘림 표시 108건(known 63 · excluded_only 12 · conditional 7 · unknown 26).
- 판단: 이전 final 의 "언급 없음 1,065 / 확인 필요 82"는 제외 업종 후보를 무시해 낙관적이었다(Codex 지적이 맞다). 확인 필요가 다시 18%로 늘었다.
  248건 표본을 보니 LLM 근거가 **제외 목록의 한 줄**("사치향락업종(골프장, 무도장)", "주점업 등 소비향락업체, 부동산업 …")이고
  "지원 제외 대상:" 머리말은 **그 위 줄**에 있다. 지금 제외 연결 검사는 근거 문장 안에서만 제외 표현을 찾아 이를 놓친다.
- 다음 단계(사용자 결정): ① 제외 근거 바로 앞 원문의 **가장 가까운 머리말이 제외 머리말**이면 인정하는 규칙(quote 역할 판정과 같은 방식, 비용 0)
  ② 잘린 108건 중 긴 원문으로 아직 안 읽은 104건 재독(약 $0.25 추정) ③ 통합공고 세부사업 분리(데이터 모델 변경, 재추출 필요). DB 쓰기 없음.

### 2026-09-22 · Claude · 업종 매칭용 판정 나누기 + 잘린 97건 18,000자 재독 + 합친 최종 결과

- 요청·목적: 사용자가 "확인 불가가 절반 이상이라 문제, 업종을 어떻게 잘 세팅할까"를 물었다. 러프 결과의 확인 불가 1,206건을 원인별로 나눠 보니
  **1,080건(90%)이 "신청 자격 문장은 찾았는데 업종 언급이 없음"** — 추출 실패가 아니라 업종을 가리지 않는 공고였다. Codex 30건 판정도 unknown 17건 중
  15건의 메모가 "규모·지역 조건만 있고 업종 제한 없음"이었다. 사용자가 판정을 나누고 잘린 97건을 다시 읽자고 결정했다.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py`
  - 매칭용 판정 `industry_status`(+ 이유 `industry_status_why`): known · no_limit · **not_mentioned**(자격 문장은 있고 업종 언급 없음 — 추정) ·
    **excluded_only**(제외 업종만) · unknown(검사가 내림 / 자격 문장 못 찾음 / **발췌가 상한에서 잘림**). 기존 `status` 는 그대로 둔다.
    not_mentioned 는 명시된 no_limit 과 **다른 값**이다(값 없음과 제한 없음을 뭉개지 않는다는 conditions.py 원칙).
  - `--ids-file`(이 공고만), `--max-chars`(발췌 상한, 기본 6,000), `--profile` 을 실행에도 적용, `--merge-base/--merge-override`(LLM 호출 없는 합치기,
    공고마다 `source_run`). 재개 시 발췌 상한이 다르면 거부. 재검사는 원 실행의 발췌 상한으로 문서를 다시 만든다.
  - `industry_results.py`·`web/industry_results.html`: 매칭용 판정 타일·필터·판정 이유·"다시 읽음" 표시, 최종 결과를 기본으로 연다.
  - 테스트 +11(판정 나누기 6 · 합치기·ID 파일·발췌 상한 재개 4 · 결과 화면 1). 전체 **449개 통과(건너뜀 13)**.
- 실행:
  1. 재검사(LLM 0) `reports/industry_llm_full_luna_20260922_rough_split/` — 제한 있음 642 · 명시 4 · 언급 없음 983 · 제외만 52 · 확인 필요 171(그중 잘림 97).
     잘린 97건 목록 `truncated_ids.txt`.
  2. 97건 재독(사용자 승인, 추정 $0.26~0.36): `--ids-file … --max-chars 18000 --profile rough` → `reports/industry_llm_long97_luna_20260922/`.
     입력 663,662 · 출력 92,821 토큰, **토큰 기준 약 $0.244**, 실패 0. 평균 발췌 9,110자, 여전히 상한에 닿는 것 4건.
     결과: 제한 있음 3 · **언급 없음 82** · 제외만 4 · 확인 필요 8 — 잘린 부분에 업종 조건이 숨어 있던 경우는 드물었다.
  3. 합치기(LLM 0) → **`reports/industry_llm_full_luna_20260922_final/`**: 제한 있음 **645(34.8%)** · 제한 없음(명시) 4 · **제한 없음(언급 없음) 1,065(57.5%)** ·
     제외 업종만 56(3.0%) · **확인 필요 82(4.4%)**(검사가 내림 56 · 자격 문장 못 찾음 24 · 18,000자에서도 잘림 2). 원답 비용 합 약 $2.67.
- 화면 확인: 최종 결과 기본 선택, 타일 645 · 1,065 · 56 · 4 · 82, "확인 필요" 82건·"언급 없음" 1,065건 필터, 펼치면 판정 이유. 콘솔 오류 없음.
- **한계(중요)**: "언급 없음"은 **자격 문장에 업종이 안 적혔다**는 뜻이다. 사업 이름·목적이 사실상 업종을 정하는 경우 — 예: "제조 DX멘토단(스마트 제조혁신 지원사업)" —
  도 언급 없음으로 들어간다. 매칭에서 "누구나 통과"로 쓰면 비제조 신청자가 이런 공고를 받을 수 있다. 제목·사업 분류로 암묵적 업종을 보조 표시하는 방법을 검토할 만하다.
  품질은 여전히 Codex 30건(사람 정답 아님) 기준. DB 쓰기 없음.

### 2026-09-22 · Claude · 업종 원문 표현 → 큰 묶음(KSIC 대분류) 규칙 + 결과 화면 "큰 묶음" 보기 — LLM 호출 없음

- 요청·목적: 사용자가 ③ "큰 묶음으로 묶기"를 요청. Codex 전량 리뷰 F1(공통 분류 체계 없음 — known 의 68%가 원문 표현뿐)에 대한 답이기도 하다.
- 선택: **한국표준산업분류(KSIC) 대분류 A~U** 를 공통 어휘로 쓴다(신청자 업종도 같은 함수로 묶을 수 있다). 표준 업종이 아닌 분야·정책 범주(바이오·AI·주력산업·
  지식서비스 등)는 `X`, "전 업종"은 `ALL`. 규칙만 쓰고 LLM 은 부르지 않았다(못 묶은 것이 적어 luna 분류 $0.05 는 제안하지 않음).
- 변경 파일:
  - `experiments/sql_semantic/industry_groups.py`(신규): `group_of(text)`·`groups_of(texts)`. 순서 — ① 표현 안의 분류 번호("(24)", "C24", "분류번호 G")
    ② 전 업종 ③ 이름이 헷갈리는 것(정보통신공사업·전기공사업·소방시설업 → F, 폐기물·재활용 → E, 부동산 → L, 의료기기 → C, 산업용 기계 수리 → C(KSIC 34),
    그 밖 수리·정비 → S, 건축기술·엔지니어링 → M, 식품접객 → I, 제조업 관련 서비스업 → X) ④ 대분류 핵심어 전부(여러 개 가능) ⑤ 분야 핵심어 → X.
  - `industry_results.py`·`web/industry_results.html`: 공고·값마다 묶음, 묶음별 공고 수(`top_groups`), 묶임 비율(`group_coverage`), 못 묶은 표현 목록.
    화면 첫 보기를 "큰 묶음"으로, 막대를 누르면 그 묶음 공고만, 표의 허용 업종 아래에 묶음 표시, 규칙 설명을 안내에 추가.
  - 테스트: `tests/test_industry_groups.py`(신규 8개 — 같은 뜻 다른 표기, 헷갈리는 이름, 분류 번호, 여러 묶음, ALL·X, 양식/양식업, 못 묶음),
    결과 화면 +1. 전체 **438개 통과(건너뜀 13)**.
- 결과(러프 재검사, 업종 확인 642건): 값 1,776개 중 **91% 묶임**. 공고 기준 표준 대분류 1개 이상 **557건(87%)** · 분야 범주/전 업종만 71 · 못 묶음 14.
  묶음별 공고: C 제조업 379 · X 분야 172(다른 표준 묶음과 함께 있는 공고 포함) · J 정보통신 93 · G 도소매 67 · I 숙박·음식 67 · A 농림어업 50 · N 사업지원(여행) 45 ·
  S 개인서비스 37 · M 전문과학 33 · H 운수 32 · F 건설 24 · E 폐기물 17 · R 여가 16 · Q 보건 15 · ALL 7 · D 5 · K 4 · P 3 · B 3 · L 2.
- 화면 확인: 첫 보기가 큰 묶음, "F 건설업" 누르면 24건(경북 운전자금 공고의 정보통신공사업·전기공사업·소방시설업이 F 로), 원문 표현 전환·X 필터 172건 동작.
- 한계: 규칙 정확도는 재지 않았다(화면으로 눈 확인). 한 공고 허용 목록에 "전업종"과 구체 업종이 섞인 경우(창원·춘천)가 있다 — ALL 과 다른 묶음이 함께 붙는다.
  분야 범주(X)는 신청자 업종과 바로 비교할 수 없다. DB 쓰기 없음.
- 다음 단계: 신청자 `main_industry` 에도 `group_of` 를 적용하면 공고 묶음과 비교할 수 있다(참고 표시부터). 새 표본 검증·실험 DB 적재는 사용자 결정.

### 2026-09-22 · Claude · 업종 검사 "러프" 강도 + Codex 전량 리뷰 F1(상태·값 불변식)·F2(폴더 재사용·규모 단어) 반영 — LLM 호출 없음

- 요청·목적: [Codex 전량 리뷰](reviews/industry/INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md) 확인 후, 사용자가 "업종을 너무 빡세게 잡는다, 러프하게도 가능한가"를 물었고
  세 방법(① 검사 완화 ② 분야 한정도 업종으로 — LLM 재실행 ③ 큰 묶음) 중 **① 검사 완화부터** 하기로 했다.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py`
  - `verify_v3(..., profile)` — `strict`(기존) / `rough`. rough 는 원문 대조에서 공백·글머리표·가운뎃점·괄호·원문자 차이를 무시하고
    (`_loose`), 근거 문장이 80% 이상 이어서 같으면 인정(`loose_found`). quote 역할은 **지원 내용·제외 목록으로 확실할 때만** 내린다(unclear 허용).
    규모 정의 하향·제한 없음 명시 확인·제외 업종 연결 확인은 strict 와 같다.
  - 두 강도 공통: 허용 값이 규모·형태 단어뿐이면 뺀다(`SIZE_FORM_WORDS` — Codex F2 "사회적기업" 오염). **불변식**: 최종 known 이 아니면
    `allowed=[]`·후보는 `raw_allowed`, 최종 no_limit 이 아니면 `no_limit_text=''`(Codex F1, 기존 결과에서 111건 어긋남).
  - `run_calls(reuse=)`·새 실행이 이미 결과가 있는 `--out` 폴더를 쓰면 거부(Codex F2).
  - `--reverify <폴더> --profile strict|rough --out <새 폴더> [--counterpart <비교 폴더>]`: 저장된 checkpoint 원답에 검사만 다시 적용.
    DB 는 문서를 다시 만들려고 SELECT 만 하고, 원답을 받을 때의 `document_sha256` 과 하나라도 다르면 멈춘다. LLM 호출 0.
  - `experiments/sql_semantic/industry_results.py`·`web/industry_results.html`: 검사 강도 표시, `raw_allowed` 를 "검사에서 뺀 업종"으로,
    `counterpart` 가 있으면 공고별 비교 판정과 "비교 결과 대비 새로 업종 확인" 타일. 처음 열면 러프 결과를 기본으로 고른다.
  - 테스트: 업종 LLM +11(러프 공백·서식·unclear·support 거부·규모 단어·원문 밖 값·불변식·퍼지 대조·재검사·문서 바뀜 거부·폴더 재사용 거부),
    결과 화면 +2. 전체 **429개 통과(건너뜀 13)**.
- 재검사 실행(LLM 호출 0): `reports/industry_llm_full_luna_20260922_strict`(known 538 · 검사가 내림 157 — 원 결과와 같다),
  `…_rough`(**known 642(35%)** · no_limit 4 · unknown 1,206 · 검사가 내림 53 · 목록완전 439). 러프에서 새로 known 104건.
- Codex 30건 대조(`compare_codex_labels.py` 에 추가): 상태 일치 **전량 러프 26** · 표본 luna 24 · 전량 엄격 23 · v2 23 /30.
  러프도 **Codex 가 unknown 인데 known 이라 한 것 0건**, 값 정밀도 0.97(한 값 불일치). 남은 4건(농식품 수출기업·충북 주력산업·대구 5대 신산업·
  국방분야)은 luna 원답부터 unknown — 검사가 아니라 프롬프트(② 분야 한정) 쪽이다.
- 화면 확인: 러프가 기본 선택, 타일 1,852 · 642 · 4 · 1,206 · 439 · 53 · 119 · 새로 확인 104. "새로 확인" 예: 김해 "축산농가", 부천 "중소 제조기업",
  경남 "제조업종", 태백 업종 목록. 춘천 공고는 허용 값에 "전업종"이 함께 들어가 제한 없음과 섞인 경우 — 눈으로 볼 만하다.
- 한계: 러프 규칙은 서식 차이 같은 일반 규칙이지만, 태백·안동 사례를 알고 만든 것이라 같은 30건 비교는 낙관적일 수 있다. 새 표본 검증이 필요하다.
  Codex 판정은 사람 정답이 아니다. DB 쓰기 없음.
- 다음 단계(사용자 결정): 화면으로 러프 결과 확인 → ③ 큰 묶음 / ② 분야 한정 / 새 표본 검증 / 실험 DB 적재 중 선택.

### 2026-09-22 · Claude · 업종 추출 결과 화면 `/industry-results` (읽기 전용, 기존 화면 안 건드림)

- 요청·목적: 사용자가 luna 전량 결과에서 "어떤 업종이 됐는지" 직접 눈으로 보고 싶다고 요청.
- 변경 파일:
  - `experiments/sql_semantic/industry_results.py`(신규): `reports/industry_llm_*` 의 `results.jsonl`·`meta.json` 만 읽어 요약·업종 순위
    (원문 표현 / 12개 표준 이름 exact)·제외 업종 순위·공고 행을 만든다. 폴더 이름은 `industry_llm_[영숫자_]` 형식만 받는다(경로 이동 금지).
    원문 링크는 공고 ID 로 만든다(결과 파일에 URL 칸이 없다). v1·v2 형식 결과도 읽는다.
  - `experiments/sql_semantic/viewer.py`: `GET /api/industry-results?run=`·`GET /industry-results` 두 라우트만 추가. 기존 라우트는 그대로.
  - `web/industry_results.html`(신규): 결과 폴더 선택, 요약 타일(누르면 필터), 업종 순위 막대(원문 표현/표준 이름 전환, 누르면 그 업종만),
    제외 업종 순위, 판정·목록 완전·검색 필터, 50건씩 쪽 나눔, 행을 누르면 근거 문장·LLM 설명·검사가 내린 이유·뺀 업종·정규식 판정.
    "참고용, DB 미적재, 품질은 Codex 판정 30건 기준" 안내를 위에 적었다. 외부 스크립트 없음, 결과 문자열은 모두 escape, 링크는 http(s) 만.
  - `tests/test_industry_results_ui.py`(신규, 5개): 요약·순위 집계, 원문 링크, 폴더 이름 제한(../ 거부), 목록, API·페이지.
- 검증(2026-09-22, 작업 PC): 전체 **416개 통과(건너뜀 13)**. 뷰어 재시작 후 `/`·`/compare`·`/industry-probe`·`/api/health`·`/industry-results` 모두 200.
  브라우저에서 luna 전량을 열어 타일(전체 1,852 · 업종 확인 538 · 제한 없음 4 · 확인 불가 1,310 · 목록 완전 390 · 검사가 내림 157 · 제외 업종 있음 118),
  업종 막대(제조업 91 · 제조기업 40 · 제조 28 …), "무역업" 누르면 10건, "검사가 내림" 157건, 표준 이름 보기(제조업 161 …), 행 펼치기, 검색("관광" 64건),
  쪽 넘김을 DOM 으로 확인. 콘솔 오류 없음. 화면 캡처는 앱 창이 가려져 실패해 찍지 못했다.
- 다음 단계: 사용자가 화면을 보고 판단. 이어서 새 30건 Codex 검증·실험 DB 적재 여부 결정.

### 2026-09-22 · Claude · 업종 추출 gpt-5.6-luna(medium) 전량 1,852건 (DB 쓰기 없음)

- 요청·목적: 사용자가 luna 전량 실행을 요청. "전량"은 실험 DB `lab_notices` 1,852건(9/18 접수 중 스냅샷)으로 정했다 — 업종 조건이 쓰일 곳이
  실험 DB 이고 표본도 여기서 뽑았다. 이후 늘어난 공고(전체 2,390)는 실험 DB 재적재가 먼저 필요하다.
- 코드: `industry_llm_sample.py` 에 `--all`(실험 DB 공고 전부) 추가. 전량 실행을 표본으로 재개하거나 그 반대면 거부, `--all` 과 `--previous` 동시 사용 거부.
  테스트 +2 → 이 기능 76개, 전체 **411개 통과(건너뜀 13)**.
- 실행: `--prompt v3 --model gpt-5.6-luna --reasoning-effort medium --all --workers 10 --out reports/industry_llm_full_luna_20260922`
  (백그라운드, 1분 간격 비용 감시, 환산 $4 초과 시 중단 조건 — 발동 안 함). 호출 1,852·실패 0, 응답 모델 `gpt-5.6-luna`(혼합 아님),
  입력 4,973,114 · 출력 1,192,922(추론 553,181) 토큰, **토큰 × 기록 단가 약 $2.43**(청구액 아님). 약 30분.
- 결과(검사 후): known **538(29.0%)** · no_limit 4 · unknown 1,310. LLM 원답은 known 692·no_limit 7. known 중 목록완전 390, 제외 업종이 있는 공고 118.
  정확 라벨 상위: 제조업 161 · 건설업 16 · 운수업 9 · 음식점업 9 · 서비스업 7 · 숙박업 7. 원문 표현은 제조업·제조기업·제조 외에
  여행업·외식업·무역업·세탁업·전기공사업·정보통신공사업·소방시설업·호텔업 등 12개 어휘 밖 표현이 많다. 규모 표현 값 1개.
- 검사가 내린 157건: quote 역할 규칙 96 · 근거 문장 불일치 54 · 허용 값 없음 2 · 규모 정의 2 · no_limit 표현 아님 3.
  표본 대조에서 이 유형 일부는 LLM 이 맞고 검사가 틀렸다(전량에서도 태백·안동이 그랬다). 원답은 `checkpoint.jsonl` 에 남아 있어 다시 부르지 않고 재검사할 수 있다.
- 반복성: 표본 30건의 전량 실행 결과는 상태 27/30 이 표본 실행과 같다. 바뀐 3건 중 2건(태백·안동)은 LLM 원답은 같았고 검사가 내렸다.
  Codex 일치는 23(표본 실행 24).
- 미검증·남은 문제: 전량 품질은 표본 30건(Codex 판정, 사람 정답 아님)으로만 짐작한다. "분야 한정"을 업종으로 볼지 미정. **DB 에 쓰지 않았다.**
- 다음 단계(사용자 결정): ① 전량 결과에서 표본과 겹치지 않는 새 무작위 30건을 Codex 가 판정 ② 실험 DB `lab_conditions` 에 정규식 값을 덮어쓰지 않는
  별도 추출기(`luna_v3`)로 적재해 검증 화면·새 방식에서 "참고"로 보이기 ③ 검사 완화(근거 문장 근사 일치 등)를 저장된 원답에 오프라인 재적용.

### 2026-09-22 · Claude · 업종 추출 — 모델 선택 옵션 + gpt-5.6-luna(medium) 30건 실행·Codex 대조

- 요청·목적: 사용자가 더 강한 모델을 요청했고, 조회해 보니 이 키로 `gpt-5.6-sol`·`gpt-5.6-terra`·`gpt-5.6-luna`를 쓸 수 있었다(모델 목록 API, 비용 없음).
  요금 페이지(2026-09-22): sol $4.00/$20.00 · terra $2.00/$12.00 · luna $0.20/$1.20 (1M 토큰당 입력/출력). 셋 다 추론 모델(reasoning effort
  none~max, 기본 medium). luna 는 "비용 민감 대량 작업용, 예전 nano 등급". 전량 환산 시 sol 은 크레딧을 넘어서(약 $110 추정) 사용자가 luna 를 골랐다.
- 코드 변경(`experiments/sql_semantic/industry_llm_sample.py`): `--model`(PRICES 에 있는 모델만)·`--reasoning-effort`. 추론 모델에는 temperature 를
  보내지 않는다. 재개 키·meta 의 모델 이름은 `모델@추론강도`(`engine`), 다른 모델로 재개하면 거부. 응답의 추론 토큰을 따로 기록. 단가는 모델별.
  기본값은 `gpt-4o-mini` 그대로. 테스트 +4(요청 옵션·엔진별 체크포인트 분리·기본값·다른 모델 재개 거부) → 이 기능 74개, 전체 **409개 통과(건너뜀 13)**.
- 실행(사용자 승인, 추정 $0.08): `--prompt v3 --model gpt-5.6-luna --reasoning-effort medium --previous …050255Z` →
  `reports/industry_llm_sample_20260922T060314Z/`. 호출 30·실패 0, 응답 모델 `gpt-5.6-luna`, 입력 79,008 · 출력 17,947(추론 8,531) 토큰,
  **토큰 × 기록 단가 약 $0.037**(청구액 아님). v3(gpt-4o-mini)와 문서 해시까지 같아 비교 등급 `exact`.
- 결과: LLM 원답 known 8 / unknown 22(gpt-4o-mini 원답은 26건을 known·no_limit 로 답했다). 검사 후 known 7, 검사가 내린 것 1.
- Codex 판정 대조(`compare_codex_labels.py` 에 luna 추가 → `codex_comparison.md`):
  상태 일치 **luna 24** · v2 23 · v1 21 · v3 20 · 정규식 17 /30. luna 는 **Codex 가 unknown 인데 known 이라 한 것이 0건**, 규모 표현 값 0,
  둘 다 known 인 7건에서 값 정밀도·재현율 1.00, 목록완전 일치 6/7. 놓친 6건은 모두 "분야·산업군 한정"(농식품 수출기업, 충북 주력산업,
  대구 5대 신산업, 제조 AI 8개 분야, 충남 주축산업(Codex 확신도 낮음), 국방분야) — 이 중 1건(제조 AI)은 LLM 원답이 맞았는데 quote 역할 검사가 내렸다.
  **luna 는 Codex 판정 이후에 실행했으므로 Codex 가 luna 답을 봤을 가능성은 없다**(v3 와 달리 이 비교는 블라인드).
- 판단(Codex 기준, 사람 정답 아님): luna(medium)는 지금까지 중 가장 가깝고, 틀리는 방향이 "없는 업종을 지어냄"이 아니라 "애매한 분야 한정을
  unknown 으로 둠"이라 탈락 필터에 넣어도 멀쩡한 신청자를 잘못 떨어뜨릴 위험이 가장 작다. 전량 환산 비용 약 $2.3(실험 DB 1,852건)~$3.0(2,390건).
- 남은 쟁점: ① "분야 한정(바이오 분야·주력산업)"을 업종으로 볼지는 설계 결정이다(신청자 업종과 맞춰 보려면 공통 분류가 필요). ② 30건 표본이라
  비율은 거칠다. ③ Codex 판정은 AI 참고 정답이다. ④ 전량 실행·DB 적재는 사용자 결정 전 하지 않는다.

### 2026-09-22 · Claude · 업종 추출 정규식·v1·v2·v3 ↔ Codex 판정 대조 (AI 참고 정답, 사람 정답 아님)

- 입력: `reports/industry_llm_sample_20260922T050255Z/label_sheet_codex.csv`(Codex 30건: known 13·unknown 17, 확신도 낮음 3).
  30행·문서 해시가 v3 입력과 일치함을 확인. **Codex 는 판정 전 v3 요약 일부가 노출됐다고 기록 — 완전한 블라인드 아님.**
- 도구: 같은 폴더 `compare_codex_labels.py`(파일만 읽음, LLM·DB 없음) → `codex_comparison.md`·`.json`.
  값 대조는 공백·가운뎃점 제거 후 포함 관계, 어휘 라벨은 두 글자 이상 어간 포함도 인정.
- 결과(30건, Codex 기준): 상태 일치 **정규식 17 · v1 21 · v2 23 · v3 20**. 정규식은 전부 unknown 이라 "항상 unknown" 기준선이 17이다.
  값 정밀도/재현율(둘 다 known 인 건): v1 0.50/0.36 · v2 0.83/0.50 · v3 0.92/0.46. v3 에만 규모 표현 값 6개.
  v3 목록완전 대조(둘 다 known 8건): 일치 5, 불일치 3. 확신도 높음 27건만 봐도 순서는 같다(v2 21 > v1 19 > v3 18 > 정규식 16).
- v3 원인 분석:
  - v3 LLM **원답**은 30건 중 26건을 known/no_limit 으로 답했다(Codex 기준 일치 15). 검사 후 일치 20 — 검사가 과잉 known 을 크게 줄였다.
  - 검사 후에도 남은 v3 만 known 5건은 모두 규모·기관 유형 표현이다: "중소기업"(직무발명) · "기업·농가·소상공인"(충북 일자리) ·
    "소상공인"(서귀포) · "전통시장"(부산 시설현대화) · "수출입 중소기업"(부산 원부자재, Codex 확신도 낮음). 코드가 값이 원문·quote 에
    있는지만 보고 **값의 종류**를 보지 않아서다.
  - Codex known 인데 v3 unknown 5건 중 4건은 **LLM 원답이 맞았는데 검사가 떨어뜨렸다**: 대구 5대 신산업·제조 AI 8개 분야(quote 역할 규칙),
    뷰티·헬스케어·IT·SW(LLM 이 quote 를 한두 글자 바꿔 써서 "근거 문장이 원문에 없음"). 1건(국방)은 LLM 값이 "중소ㆍ벤처기업"이라 떨어진 게 맞다.
- 판단(Codex 기준, 사람 정답 아님): **어느 방식도 공고 업종을 정형 조건으로 채울 만큼 믿을 수 없다.** v2 가 가장 가깝지만 Codex known 13건 중
  6건을 놓친다. v3 는 값을 원문 그대로 보존해 정밀도는 가장 높지만, gpt-4o-mini 가 규모 표현 금지를 따르지 않고 검사 규칙은 맞는 답도 떨어뜨린다.
  업종은 탈락 필터가 아니라 근거와 함께 "확인 필요/참고"로만 보여 주는 기존 결론을 유지한다. 전량 실행·DB 적재는 하지 않는다.
- 다음 단계 후보(사용자 결정): ① 더 강한 모델(예: gpt-4.1-mini)로 같은 v3 프롬프트·같은 30건을 돌려 Codex 판정과 비교(모델이 지시를 따르는지)
  ② 저장된 v3 원답에 "규모·형태 단어뿐인 값 제거"·quote 근사 일치를 오프라인 적용(비용 0) — 다만 같은 30건에 맞춘 규칙은 과적합이라 **새 표본**으로 확인해야 한다
  ③ 여기서 멈추고 발표에 "LLM 업종 추출은 아직 불안정"으로 정리.

### 2026-09-22 · Codex · 업종 30건 AI 참고 판정

- 요청·목적: 사용자가 도메인을 직접 판정하기 어렵다고 결정해, 동일 발췌 30건을 Codex가 읽고 Claude 비교용 참고 판정을 작성했다.
- 작업 전 상태: 사람용 `label_sheet.csv`는 비어 있었고, Codex 전용 출력 지시서와 동일 입력 발췌가 준비돼 있었다.
- 변경 파일: `reports/industry_llm_sample_20260922T050255Z/label_sheet_codex.csv` 신규 작성, `docs/STATUS.md`와 이 기록 갱신. 사람용 `label_sheet.csv`는 수정하지 않았다.
- 결과: 30건 중 `known` 13, `unknown` 17, `no_limit` 0. 확신도 낮음 3건이며 모든 행의 판정자는 `codex`다. 이 결과는 **Codex 판정(AI 참고 정답)** 이고 사람 정답이 아니다.
- 검증: UTF-8 BOM, 데이터 30행·13열, 원본 번호·notice_id·링크·document_sha256 및 행 순서 보존, 상태·확신도·목록완전 허용값, 근거 문구의 발췌 원문 포함 여부를 검사했다. 수식 오류 검색 0건.
- 미검증·남은 문제: 판정 시작 전 기존 Claude v3 요약 일부가 도구 출력에 노출돼 완전한 블라인드라고 보장할 수 없다. 그 뒤에는 지시된 입력 두 파일만으로 판정했으며, 이 오염 가능성을 비교 보고서에 함께 표시해야 한다.
- 다음 단계: Claude가 정규식·v1·v2·v3를 이 결과와 대조하되, 사람 정확도가 아니라 두 AI의 일치도로 보고한다. LLM/API 호출·DB 쓰기·Git 작업은 하지 않았다.

### 2026-09-22 · Claude · 업종 LLM v3 30건 실행 + 사람 정답 양식

- 요청·목적: Codex 4차 결론(규칙 보강 중단 → v3 30건 → 사람 정답)에 따라 사용자가 v3 실행을 승인.
- 실행: `--prompt v3 --previous reports/industry_llm_sample_20260922T023053Z` → `reports/industry_llm_sample_20260922T050255Z/`.
  같은 seed 30건, 호출 30·실패 0, 응답 모델 `gpt-4o-mini-2024-07-18`(혼합 아님), 토큰 × 기록 단가 기준 약 **$0.016**(청구액 아님),
  이전 v2 와 비교 등급 `limited`(v2 에 문서 해시 없음). DB 쓰기 0.
- 결과: known 정규식 0 → v2 8 → **v3 13**, 검사에서 내린 것 15, known 중 `list_complete` 5.
- Claude 가 known 13건을 읽은 결과(사람 정답 아님):
  - 맞고 완전 2: 진주 "여행사, 관광숙박업소, 관광체험관"(v2 의 누락을 채움) · 청주 "바이오 분야 중소기업".
  - 맞지만 불완전(코드가 list_complete=False 로 표시) 4: 태백(LLM 은 12개를 다 뽑았으나 quote 가 잘리고 "지식ㆍ정보"의 점 문자를
    바꿔 써서 11개가 검사에서 빠짐) · 안동(LLM 이 원문 "제조"를 "제조업"으로 바꿔 써서 빠짐, 무역업만 남음) · 강화군(별표) · 수출 조사(농식품 수출기업).
  - **틀림 4 — 규모·형태 표현을 업종으로 받음**: 직무발명 "중소기업"(list_complete=True) · 충남 "중소기업"(list_complete=True) ·
    서귀포 "소상공인" · 충북 일자리 "기업·농가·소상공인". 프롬프트가 금지했지만 LLM 이 따르지 않았고, 코드 검사는 값이 원문·quote 에
    있는지만 봐서 막지 못했다.
  - 애매 3: 충북 기술닥터 "충북 주력산업 영위기업" · 부산 "수출입 중소기업" · 부산 "전통시장"(list_complete=True).
  - v2 대비 잃은 것 1: 제조 AI "(수요기업) … 제조기업" — quote 역할 검사에서 가장 가까운 머리말이 미등록 구역으로 잡혀 unknown.
- 판단: v3 는 원문 표현 보존으로 목록 누락이 줄었지만(진주), 규모 표현 오답이 새로 늘었고 `list_complete=True` 5건 중 2건이 오답이다.
  **v2 보다 낫다고 말할 수 없다.** 명백한 보완 후보(허용 값이 규모·형태 단어뿐이면 빼기)는 있지만, Codex 결론대로 규칙을 더 붙이기 전에
  사람 정답으로 오판 유형과 비율을 먼저 잰다.
- 사람 정답 양식(블라인드 — LLM 답을 넣지 않음): 같은 폴더의 `label_sheet.csv`(30행, 정답 칸 비움, UTF-8 BOM) ·
  `label_documents.md`(LLM 이 받은 것과 같은 발췌와 판단 기준). 문서 해시가 v3 결과와 일치함을 확인했다. 만든 스크립트는 `make_label_sheet.py`.
- 다음 단계: 사용자가 `label_sheet.csv` 를 채운다 → Claude 가 정규식·v1·v2·v3 를 정답과 대조(상태 일치, 허용 업종 정밀도·재현율,
  list_complete 정확도, 규모 표현 오답 수)해 보고 → 규칙 보완·전량 여부는 그 뒤에 결정.

### 2026-09-22 · Claude · 업종 LLM 표본 — Codex 4차 후속 리뷰 F1(제외 머리말) 반영 (LLM 호출 없음)

- 요청·목적: [4차 후속 재검토](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md#4차-후속-재검토--구역-경계제외-목록복합-업종-반영-2026-09-22) —
  "제외업종:"·"지원제외 업종:"·"비대상 업종:"이 이름의 업종·대상 때문에 자격 머리말로 분류돼, 제외 값을 allowed 로 잘못 받으면 known 이 되던 문제.
- 변경: `_header_events()` 가 콜론 머리말 이름에서 **제외 머리말(`EXCLUSION_HEADERS` + 제외·불가·비대상·금지·제한·배제·미해당)을 먼저** 보고
  `X` 로 둔다. 가장 가까운 머리말이 `X` 면 `quote_role` = `exclusion` → known 불가. 테스트 +2(리뷰 반례 세 건의 quote_role·verify_v3,
  자격 머리말 뒤 제외 머리말).
- 검증: 이 기능 테스트 70개, 전체 **405개 통과(건너뜀 13)**. 2차 known 8건의 역할 판정은 변화 없음(7 eligibility, 수출 조사 1 unclear).
  실데이터 plan 은 아래 기록. DB 쓰기 없음.
- Codex 결론에 따라 규칙 보강은 여기서 멈추고, 다음은 v3 30건 실행(사용자 승인 필요) → 사람 정답 30건으로 오판율·목록 완전성 측정.

### 2026-09-22 · Codex · 업종 LLM 4차 후속 재검토

- 요청·목적: Claude가 3차 리뷰의 구역 상속·제외 목록 오인·복합 업종 절단을 수정한 뒤 사용자 재검토 요청.
- 판정: 직전 세 반례는 해결. 제외 머리말을 자격 머리말로 분류하는 F1 한 건 때문에 v3 실제 호출은 보류.
- 확인한 해결: 모든 quote occurrence 역할 충돌 시 unclear, 미등록 구역 경계, 제외 목록의 절 전체 항목·새 주어 검사,
  `금융ㆍ보험업`·`숙박·음식점업` 값 보호.
- 새 반례: 일반 콜론 머리말에 `업종/대상`이 있으면 eligibility로 두는 분기가 `제외업종: 유흥업`,
  `지원제외 업종: 금융ㆍ보험업`, `비대상 업종: 도박업`까지 자격 구역으로 인정한다.
  각 값을 allowed로 넣으면 `verify_v3()`가 실제로 `known`을 반환했다.
- 변경 파일: [상세 리뷰](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md#4차-후속-재검토--구역-경계제외-목록복합-업종-반영-2026-09-22),
  `STATUS.md`, 이 기록. 구현·테스트·결과 데이터는 수정하지 않았다.
- 검증: 전용 68개와 프로젝트 Python 3.12 전체 **403개 통과·13개 건너뜀**을 독립 확인했다.
  기존 `search_comparison.py`의 닫히지 않은 파일 ResourceWarning은 출력됐지만 종료코드는 0이었다.
  위 세 새 반례 재현. LLM 호출·DB 쓰기·Git staging/commit/push 없음.
- 다음 단계: exclusion header를 eligibility보다 먼저 판정하고 세 반례를 고정한 뒤 v3 30건 실행→사람 정답 30건 평가로 넘어간다.

### 2026-09-22 · Claude · 업종 LLM 표본 — Codex 3차 후속 리뷰 F1×2·F2 반영 (LLM 호출 없음)

- 요청·목적: [3차 후속 재검토](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md#3차-후속-재검토--quote-역할제외-관계-휴리스틱-반영-2026-09-22)의 세 반례.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py`, `tests/test_industry_llm_sample.py`.
  - F1(구역 상속): `quote_role()` 이 머리말 "사건"을 모아 가장 가까운 것을 본다. 등록된 자격/지원 머리말 외에
    **콜론으로 끝나는 모든 머리말**("기타 안내:")과 새 구역 글머리(□■◆◎▶)를 `O`(등록 안 된 구역)로 두어 앞 자격 문맥을 끊는다.
    콜론 머리말 이름에 대상·자격·요건·업종이 있으면 자격으로 본다("참여업종:"). ○·❍·ㅇ·- 같은 하위 글머리는 끊지 않는다.
    **같은 quote 가 문서에 여러 번 나오면 모든 위치의 역할을 보고, 갈리면 `unclear`**. `build_document()` 가 줄바꿈을 공백으로
    합치므로 줄 단위 경계는 쓸 수 없어 머리말 기준으로 끊었다. 프롬프트에 "머리말부터 포함해 복사, 짧은 조각 금지"를 추가.
  - F1(목록 오인): 쉼표 목록으로 제외를 넘기려면 값이 **절 전체 항목**이어야 한다(값 뒤에 `LIST_TAIL_WORDS`(등·및·또는) 외의 말이 없어야).
    목록 끝 절의 제외 표현 앞에 새 주어("제조업은")가 있으면 인정하지 않는다("등은/등이"는 목록 끝으로 허용).
    그래서 "유흥업 교육, 제조업은 지원 제외"·"유흥업 관련 사업, …"의 유흥업은 빠진다. "유흥업, 제조업은 지원 제외"의 유흥업도
    새 주어 때문에 빠진다(보수적으로 놓치는 쪽 — 기록해 둔다).
  - F2(값 안 구분기호): 절을 나누기 전에 값을 자리표시로 바꾼다(글자 사이 공백 허용). "금융ㆍ보험업은 지원 제외",
    "숙박·음식점업은 지원 불가", "지원제외 업종: 금융ㆍ보험업, 사행산업" 모두 인정.
- 실데이터 확인(SELECT 만, LLM 없음): 2차 근거 문장 23개의 역할 판정은 직전과 같고 `기업부설연구소` 1건만 eligibility → unclear
  (업종 표현이 없어 결과에는 영향 없음). 태백·안동·청주·제조 AI·진주·강화군은 계속 eligibility.
- 검증(2026-09-22, 작업 PC, Python 3.12.10): 새 테스트 68개(추가 10: 리뷰 반례 세 건 + 같은 역할 반복 · □ 구역 · 하위 글머리 ·
  "참여업종:" · 새 주어 · 값 안 공백 · 콜론 목록의 구분기호 값) 통과(ResourceWarning 오류 취급). 전체 **403개 통과, 13개 건너뜀**.
  DB 쓰기 없음.
- 판단: 규칙 후처리는 세 차례 보강으로 리뷰 반례를 모두 막았지만, 휴리스틱이라 새 경계 반례는 계속 나올 수 있다.
  후처리의 역할은 "LLM 오독이 집계를 크게 오염시키지 않게 하는 것"이고, 실제 오판율은 사람 정답 30건으로 재야 한다.
- 다음 단계: Codex 재검토 → (사용자 승인 시) v3 30건 실행 → 사람 정답 30건.

### 2026-09-22 · Codex · 업종 LLM quote 역할·제외 관계 3차 후속 재검토

- 요청·목적: Claude가 2차 리뷰의 quote 역할 F1과 제외 관계 F2를 반영하고 기록을 남긴 뒤 사용자 재검토 요청.
- 판정: 직전 두 반례는 해결. 새 휴리스틱의 false-positive 두 건과 false-negative 한 건 때문에 최종 승인 및 v3 호출은 보류.
- 확인한 해결: 지원내용의 `대상` 단어만으로 known이 되지 않음, 제외 cue가 다른 업종에 붙은 직전 반례 차단,
  기업마당 `☞` 구간·자격/지원 머리말·콜론 제외 목록 테스트 추가.
- 새 반례: (1) `지원대상: 도내 중소기업. 기타 안내: 제조업 기업 우대 프로그램`에서 기타 안내 quote가 앞의 자격 머리말을 상속해 known,
  (2) `유흥업 교육, 제조업은 지원 제외`에서 유흥업을 쉼표 제외 목록으로 오인,
  (3) `금융ㆍ보험업은 지원 제외`는 값 내부 `ㆍ`를 먼저 분리해 제외 관계를 찾지 못함.
- 변경 파일: [상세 리뷰](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md#3차-후속-재검토--quote-역할제외-관계-휴리스틱-반영-2026-09-22),
  `STATUS.md`, 이 기록. 구현·테스트·결과 데이터는 수정하지 않았다.
- 검증: 전용 58개 통과. 프로젝트 Python 3.12로 전체 **393개 통과·13개 건너뜀**을 독립 확인했다.
  전체 실행에서 업종 작업과 무관한 기존 `search_comparison.py` 닫히지 않은 파일 ResourceWarning이 출력됐지만 종료코드는 0이었다.
  추가 세 반례는 모두 재현했다. LLM 호출·DB 쓰기·Git staging/commit/push 없음.
- 다음 단계: quote의 모든 occurrence/구역 경계를 판정하고 제외 목록의 문법적 연결 및 값 내부 구분기호를 보존한 뒤 재검토한다.

### 2026-09-22 · Claude · 업종 LLM 표본 — Codex 2차 후속 리뷰 F1(quote 역할)·F2(제외 관계) 반영 (LLM 호출 없음)

- 요청·목적: [2차 후속 재검토](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md#2차-후속-재검토--값별-evidence재개-provenance-반영-2026-09-22)가
  재개(F2)는 승인하고, 두 반례를 막은 뒤 v3 를 호출하라고 했다.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py`, `tests/test_industry_llm_sample.py`.
  - F1 `quote_role()`: '대상' 같은 단어 하나(`ELIGIBILITY_CUES`, 삭제)를 증거로 쓰지 않는다. quote 와 원문의 바로 앞 80자에서
    **가장 가까운 머리말**을 본다 — 지원 내용 머리말(지원내용·사업내용·사업목적·지원분야 …)이 더 가까우면 `support`,
    자격 머리말(지원대상·신청자격·모집대상·지원가능 …, 컨소시엄의 `(수요기업)`·`(공급기업)` 등)이 더 가까우면 `eligibility`,
    머리말이 없으면 quote 안의 제한 서술어(기업만·영위하는·에 한함 …)가 있을 때만 `eligibility`. known 은 `eligibility` 여야 한다.
  - **기업마당 요약 형식 반영**: 실제 2차 근거 문장으로 새 규칙을 시험해 보니, 맞아 보였던 안동("제조 및 무역업")·청주("바이오 분야")가
    머리말이 없어 `unclear` 로 떨어졌다. 원문을 보니 기업마당 본문(`bsnsSumryCn`)은 "개요 ☞ 지원대상 ☞ 지원내용" 형식이다
    (실험 DB 기업마당 1,601건 모두 ☞ 2개 이상, 첫 구간이 신청 주체 명사로 끝남 1,428건, 둘째 구간에 '지원' 1,548건 — Claude 집계).
    ☞ 가 2개 이상인 문서는 첫 ☞ 를 자격 머리말, 둘째 ☞ 를 지원 내용 머리말로 읽는다.
  - F2 `excluded_linked()`: 제외 값은 ① 값 바로 뒤 같은 절(쉼표·가운뎃점 기준)에 제외 표현이 있고 그 사이에 포함·허용 표현이 없거나
    ② 값 앞에 **콜론으로 목록을 여는** 제외 머리말("지원제외 업종:")이 있고 그 사이가 목록 항목뿐이거나
    ③ 값이 쉼표 목록의 앞 항목이고 목록이 제외 표현으로 끝날 때만 남긴다. 처음에는 앞 절의 "지원 제외"를 머리말로 잘못 읽어
    "유흥업은 지원 제외, 제조업 교육 포함"의 제조업을 남겼다 — 콜론 조건으로 고쳤다.
- 실데이터 확인(SELECT 만, LLM 없음): 2차 결과의 근거 문장 23개를 `quote_role` 에 넣었을 때 태백·안동·청주·제조 AI(수요기업)·
  진주·강화군은 `eligibility`. 수출 조사 "농식품 수출기업 및 농가"는 첫 ☞ 앞 개요의 인사 문장이라 `unclear`(자격으로 보지 않는 것이 맞다고 판단).
  충북 "대상 - (사업장) 도내 … 의료기관"은 지원 내용 구간이라 `support`.
- 검증(2026-09-22, 작업 PC, `.venv` = Python 3.12.10): 새 테스트 58개(추가 17: 리뷰 반례 두 건과 순서 반대 반례, 머리말 거리,
  기업마당 ☞ 첫·둘째 구간, 개요 인사 문장, ☞ 1개 문서, 수요기업 표시, 쉼표·가운뎃점 목록, 콜론 머리말, 콜론 없는 "지원 제외",
  목록 중간에 다른 서술) 통과(ResourceWarning 오류 취급). 전체 **393개 통과, 13개 건너뜀**.
  실데이터 `--prompt v3 --plan` 추정 $0.0157. DB 쓰기 없음.
  참고: Codex 는 자기 환경의 `.venv` 실행기 문제로 전체 테스트를 재현하지 못했다고 기록했다. 이 PC 의 `.venv` 는
  `C:\Users\playdata2\AppData\Local\Programs\Python\Python312\python.exe`(3.12.10)를 가리키며 정상 동작한다.
- 미검증·남은 문제: 머리말·제한 서술어·포함 표현 목록은 휴리스틱이다. 머리말이 80자보다 멀거나 다른 형식이면 맞는 문장도 `unclear` 로
  떨어질 수 있고(보수적 방향), 목록에 없는 포함 표현은 제외 관계를 잘못 인정할 수 있다. 오판율은 사람 정답으로만 잰다.
- 다음 단계: Codex 재검토 → (사용자 승인 시) v3 30건 실행.

### 2026-09-22 · Codex · 업종 LLM 값별 evidence·재개 provenance 2차 후속 재검토

- 요청·목적: Claude가 직전 후속 리뷰의 F1(값별 근거)·F2(재개 provenance)를 반영한 뒤 사용자 재검토 요청.
- 판정: 재개 provenance는 해결·승인. evidence 필드는 추가됐지만 관계 검증 두 건이 남아 v3 실제 호출은 보류.
- 확인한 해결: `--resume`의 previous·등급 보존, 다른 previous와 prompt/schema hash 변경 거부,
  schema hash가 포함된 재개 키, 혼합 응답 모델 경고, main 수준 부분 실패→재개 테스트.
- 남은 문제: (1) `ELIGIBILITY_CUES`의 `대상` 등 단어가 지원내용 문장에 있기만 해도 신청 자격으로 인정되어
  `지원내용: 제조업을 대상으로 디지털 전환 비용 지원`이 `known/list_complete=True`로 통과한다.
  (2) excluded text와 제외 cue가 같은 evidence에 따로 존재하기만 하면 관계를 인정해
  `유흥업 교육 포함, 제조업은 지원 제외`에서 유흥업이 제외 업종으로 남는다.
- 변경 파일: [상세 리뷰](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md#2차-후속-재검토--값별-evidence재개-provenance-반영-2026-09-22),
  `STATUS.md`, 이 기록. 구현·테스트·결과 데이터는 수정하지 않았다.
- 검증: 전용 41개 통과, 위 두 추가 반례 재현. 전체 테스트는 `.venv`가 없는 Python 3.12 실행기를 가리키고
  현재 Python과 프로젝트 네이티브 패키지 버전이 달라 수집 단계에서 중단되어 Claude의 376개 통과를 독립 확인하지 못했다.
  LLM 호출·DB 쓰기·Git staging/commit/push 없음.
- 다음 단계: 신청 자격 문맥과 제외 cue의 값별 관계를 검증하고 두 반례를 테스트로 고정한 뒤 재검토한다.

### 2026-09-22 · Claude · 업종 LLM 표본 — Codex 후속 리뷰 F1(값별 근거)·F2(재개 provenance) 반영 (LLM 호출 없음)

- 요청·목적: [후속 재검토](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md#후속-재검토--v3-코드-반영-2026-09-22)가 v3 호출 전 수정을 요구.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py`, `tests/test_industry_llm_sample.py`.
  - F1: v3 스키마의 `allowed[]`·`excluded[]` 에 `evidence`(원문 근거 문장)를 **필수**로 추가하고 프롬프트에 "quote 는 신청 자격 문장,
    허용 업종은 모두 quote 안에" 를 명시. `verify_v3` 는 값마다 ① evidence 가 원문에 있고 ② 값이 evidence 안에 있을 때만 남기고,
    허용 값은 ③ **신청 자격 quote 안에 있어야** 한다(밖이면 `신청 자격 근거(quote) 밖의 업종` 으로 뺌). 제외 값은 evidence 에
    제외 표현(`conditions.NEGATION_HINTS` + 금지·배제)이 있어야 한다. known 의 quote 에는 신청 자격 표시(대상·자격·신청·한함·영위·업종 등)가
    있어야 한다. 값을 하나라도 빼면 `list_complete=False`. 검사 순서는 규모 정의 → 자격 표시 → 허용 값 유무.
  - F2: 재개 키에 `schema_sha256` 추가, 체크포인트 행에 프롬프트·스키마·문서 해시 기록. `--resume` 은 meta 의 previous·등급을
    이어받고, 다른 `--previous` 를 주거나 이전 비교 없이 시작한 폴더에 `--previous` 를 주거나 프롬프트/스키마 해시가 바뀌면 거부.
    재개 중 이전 비교 등급이 바뀌면 거부. 응답 모델이 여러 개면 `mixed_models=True` 와 보고서 경고. meta 에 `resume_count`.
    DB 없이 시험할 수 있게 `build_parser()`·`run_experiment()` 로 나누고 새 실행 폴더를 정하는 `--out` 추가.
- 검증(2026-09-22, 작업 PC): 새 테스트 41개(추가 12: 리뷰 재현 입력 "지원 내용의 제조업·유흥업" · evidence 없음 · 값이 근거 밖 ·
  자격 표시 없는 quote · 제외 표현 있는 제외 값 · 스키마 필수 칸 · 재개 키의 스키마 해시 · `run_experiment` 수준의
  일부 실패 → `--resume` → 이전 비교 열·등급·resume_count 보존 · 다른 previous 거부 · 스키마 해시 변경 거부 · 혼합 모델 경고 ·
  plan 은 호출 함수를 만들지 않음) 통과(ResourceWarning 오류 취급). 전체 **376개 통과, 13개 건너뜀**.
  실데이터 `--prompt v3 --plan --previous …023053Z` → 30건, 추정 $0.0157, 비교 등급 `limited`. **LLM 호출 없음.** DB 쓰기 없음.
- 미검증·남은 문제: 자격 표시 단어 목록은 휴리스틱이라 지원 내용 문장에 "대상"이 들어가면 통과할 수 있다. 의미 판정은 여전히 사람 정답으로만 잰다.
  v3 프롬프트가 evidence·list_complete 를 실제로 잘 채우는지는 실행 전이라 모른다.
- 다음 단계: Codex 재검토 → (사용자 승인 시) `--prompt v3 --previous reports/industry_llm_sample_20260922T023053Z` 30건 실행.

### 2026-09-22 · Codex · 업종 LLM v3 코드 반영 재검토

- 요청·목적: Claude가 [업종 LLM 리뷰](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md)의 F1·F2·F3를 반영한 뒤 재검토.
- 판정: 대부분 해결. 프롬프트 필수·legacy 차단, no_limit/규모 정의 반례, 원문 값 보존, 목록 완전성,
  `filter_ready=False`, 실행 지문, 체크포인트·재개, 비용 문구와 29개 테스트를 확인했다.
- 남은 F1: 각 allowed/excluded 값에 별도 근거 span이 없다. 값이 quote가 아닌 문서 다른 위치에 있어도
  `known/list_complete=True`로 통과하는 반례를 재현했다. v1식 지원 주제→업종 제한 오독을 아직 막지 못한다.
- 남은 F2: 안내된 `--resume` 명령에 `--previous`가 없으면 기존 meta의 이전 비교 정보를 복원하지 않고
  완료 meta를 `previous=None`으로 덮어써 v2↔v3 비교 열과 등급이 사라진다.
- 검증: 신규 **29개 통과**(ResourceWarning 오류 조건), 전체 **364개 통과·13개 건너뜀**, Python compile 통과.
  실제 DB 읽기 전용 v3 plan은 30건·첨부 23건·예상 약 $0.0151·비교 등급 limited. LLM 호출·DB 쓰기 없음.
- 다음 단계: 값별 evidence 연결과 resume provenance를 수정한 뒤 v3 30건 실제 호출 여부를 다시 판단한다.

### 2026-09-22 · Claude · 업종 LLM 표본 코드 — Codex 리뷰 F1·F2·F3 반영 (LLM 호출 없음)

- 요청·목적: 사용자가 [업종 LLM 리뷰](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md)의 코드 수정부터 하라고 요청.
- 변경 파일:
  - `experiments/sql_semantic/industry_llm_sample.py`(재작성). v1·v2 프롬프트와 v2 검사는 저장된 두 결과 재현용으로
    그대로 두고(`verify_legacy`, 이전 이름 `verify` 유지) **v3** 를 추가했다.
    - F1 검사: 업종을 **원문 표현 그대로 값마다**(`allowed[].text`, `excluded[].text`) 받고 각각 문서와 대조해 없으면 뺀다.
      어휘 라벨은 원문에 업종명(또는 두 글자 이상 어간, 예: 제조)이 있을 때만 `exact`, 뜻으로 옮긴 것(농가 → 농업)은
      `alias` 로 따로 둔다. `no_limit` 은 `no_limit_text` 가 문서에 있고 `conditions.INDUSTRY_NO_LIMIT_RE` 에 맞을 때만.
      "상시근로자"는 정의 표시(정의·기본법·에 의한 소상공인 등)와 함께 있을 때만 내리고 실제 복합 조건은 남긴다.
      `list_complete` 를 따로 받고, 원문에 없는 허용 표현을 뺐거나 별표·붙임·"등" 표시가 있으면 코드가 false 로 내린다.
      모든 결과에 `filter_ready=False` — 사람 정답 전에는 탈락 필터에 쓰지 않는다.
    - F2 지문: 공고마다 `document_sha256`·첨부 지문, meta 에 `prompt_sha256`(실제 보낸 system 메시지)·`schema_sha256`·
      `code_sha256`·API 가 돌려준 실제 모델명. `--previous` 는 문서 해시가 같으면 `exact`, 옛 결과처럼 해시가 없으면
      `limited`(ID·문자 수·첨부 수만 대조), 해시나 길이가 다르면 거부.
    - F2 기본값: `--prompt` 필수. v1·v2 는 `--allow-legacy` 없이는 거부한다.
    - F2 체크포인트: 성공한 호출은 바로 `checkpoint.jsonl`, 실패는 `failures.jsonl`. 재개 키 `(notice_id, document_sha256,
      prompt_sha256, model)`. `--resume <폴더>` 는 체크포인트에 있는 공고를 다시 부르지 않는다. 실패가 있으면 종료코드 3.
    - F3 비용: 보고서·meta 에 "API 보고 토큰 × 기록 단가, 청구액 아님"과 단가 기준을 적는다.
  - `tests/test_industry_llm_sample.py`(신규, 29개): 리뷰 F1 반례 4개(가짜 no_limit · 농가 별칭 · 상시근로자 복합 조건 ·
    제외 업종 미검사)와 규모 정의 하향, 원문 표현 보존(지식·정보 관련업·무역업·여행사), 별표·"등" 목록 불완전,
    `--prompt` 필수·legacy 거부, 해시 차이, 이전 실행 비교 등급, 부분 실패 후 재개(실패한 1건만 다시 부름), 보고서 표시.
- 검증(2026-09-22, 작업 PC): 새 테스트 29개 통과(ResourceWarning 을 오류로 취급해도 통과). 전체 **364개 통과, 13개 건너뜀**
  (기존 335 + 29). 실데이터 `--prompt v3 --plan --previous …023053Z` → 30건·첨부 23건, 추정 $0.0151, 비교 등급 `limited`.
  `--prompt v1 --plan` 은 거부 메시지로 멈춤. **LLM 은 호출하지 않았다.** DB 쓰기 없음.
- 미검증·남은 문제: v3 프롬프트가 실제로 원문 표현·목록 완전성을 잘 채우는지는 아직 모른다(실행 전).
  코드 검사는 여전히 **의미**를 판정하지 못한다 — 예: "기업·농가·소상공인 등"의 `농가` 는 원문에 있으므로 known 으로 남고
  목록 불완전·alias 로만 표시된다. 오판율은 사람 정답으로만 잴 수 있다.
- 다음 단계: Codex 재검토 → (사용자 승인 시) `--prompt v3 --previous reports/industry_llm_sample_20260922T023053Z` 로
  같은 30건 실행(추정 약 $0.015) → 사용자가 30건 정답을 달면 정규식·v1·v2·v3 비교.

### 2026-09-22 · Claude · 정정 — 업종 탐침·업종 LLM 표본 기록의 틀린 서술 (Codex 리뷰 두 건의 F2)

- 근거: [업종 탐침 리뷰](reviews/industry/INDUSTRY_WEIGHT_PROBE_REVIEW_20260922.md) F2, [업종 LLM 리뷰](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md) F2·F3.
  아래 수치는 Claude 가 저장 결과(`per_query.jsonl`, `qrels.jsonl`)로 다시 세어 Codex 수치와 일치함을 확인했다.
- **업종 강조 탐침**(아래 "업종(main_industry) 강조 탐침" 항목 정정):
  - "qrels +340쌍·정답 340건"은 틀렸다. 340은 LLM 원시 호출(170쌍 × A/B)이고, qrels 에 채택된 것은 **131쌍**(A/B 불일치 39쌍)이다.
  - "업종 반복은 그대로와 완전히 같은 순위"는 틀렸다. 하이브리드에서 P@3 만 같고 Top 3 가 **2칸·2질의** 바뀌었으며 nDCG 0.510 → 0.500.
  - "dense 는 네 변형이 완전히 같은 결과·최근접 순위가 안 바뀌었다"는 틀렸다. P@3 만 0.389 로 같고
    업종 없음 1칸·반복 1칸·앞배치 **4칸(3질의)** 이 바뀌었다. 반복 nDCG 0.451 → 0.422. 하이브리드 업종 없음은 7칸·6질의가 바뀌었다.
  - 하이브리드 업종 앞배치는 P@3 점 추정 −0.056 이므로 "나빠지지 않았다"는 서술도 틀렸다.
  - **결론 정정: "업종 가중치를 반영할 근거가 없다" → "평가 설계 보완 필요"**. 평가 풀이 기준 검색어로만 만들어져 변형별 미판정 범위가 다르고,
    판정자에게 주업종을 보여주지 않았으며, 새 질의 아이디어가 이미 업종을 드러낸다(리뷰 F1 두 건, 미반영).
- **업종 LLM 표본 v2**(아래 "업종 LLM 추출 v2" 항목 정정):
  - "불완전 목록 3건"은 **최소 4건**이다. 태백시(`bizinfo:PBLN_000000000117600`)도 근거의 "②지식·정보 관련업"이 최종 목록에서 빠졌다 —
    v2 코드 검사가 `정보통신업`을 표면어 불일치로 빼면서 원문 표현을 other 로 보존하지 않았다(Claude 의 검사가 만든 누락).
    8건 판독은 `그럴듯 최대 3 · 불완전 최소 4 · 오판 1`.
  - "과잉 추론이 크게 줄었다"는 사람 정답 없이 쓸 수 없는 표현이다. **"known 출력이 20 → 8 로 줄었다"** 로만 읽는다.
  - v2 후처리는 "엄격 검증"이 아니다. 문자열 존재만 보므로 가짜 `no_limit`·넓은 별칭(농가 → 농업)을 통과시키고,
    "상시근로자"가 들어간 실제 복합 조건을 내리며, 제외 업종은 검사하지 않는다(리뷰 F1, 미반영).
  - `$0.0116`·`$0.0133`·`$0.317` 은 청구액이 아니라 **API 보고 토큰 × 코드에 적은 단가**로 계산한 값이다.
  - v1↔v2 는 ID·문자 수·첨부 수만 같다고 확인했고 문서 해시는 기록하지 않았다.
- 변경 파일: 이 항목과 `STATUS.md` 의 Claude 항목 문구만. 코드·데이터·결과는 고치지 않았다.

### 2026-09-22 · Codex · 업종 LLM 추출 v1·v2 리뷰

- 요청·목적: Claude의 업종 원문 추출 30건 v1·v2 코드와 저장 결과 재검토.
- 판정: [상세 리뷰](reviews/industry/INDUSTRY_LLM_SAMPLE_REVIEW_20260922.md). 30건 탐색과 “탈락 필터가 아닌 참고/확인 필요로만 사용” 결론은 승인한다.
  v2 추출값 자체의 운영 필터·전량 적재 사용은 승인하지 않는다.
- F1: 후처리가 quote 포함과 표면어만 확인해 가짜 `no_limit`·`농가→농업`을 통과시키고,
  실제 제조업 조건도 `상시근로자`가 있다는 이유로 내리는 반례를 재현했다. 제외 업종은 원문 검증도 없다.
- F2: v2 known 8건 중 불완전 목록은 기록한 3건이 아니라 최소 4건이다. 태백시 결과에서 근거의
  `지식·정보 관련업`이 최종 목록에서 누락됐다. 사람 정답 전에는 “오류 감소” 대신 `known 20→8`로만 표현한다.
- F2: v1↔v2는 ID만 대조해 문서 동일성을 증명하지 못하고, 기본 실행은 여전히 v1이며,
  부분 실패 체크포인트와 새 모듈 테스트가 없다. 비용 수치는 실제 청구액이 아닌 토큰 단가 계산값이다.
- 검증: 두 보고서 ID·문자 수·첨부 수와 집계 대조, v2 검증 반례 실행, Python compile,
  전체 **335개 통과·13개 건너뜀**. LLM 추가 호출·DB 쓰기·실험 코드 수정 없음.

### 2026-09-22 · Claude · 업종 LLM 추출 v2(엄격 프롬프트) — 같은 30건 재비교

- 요청·목적: 사용자가 v1 에서 본 과잉 추론을 막도록 프롬프트를 좁혀 같은 30건으로 다시 돌리라고 요청.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py` — v1 프롬프트는 그대로 두고 `--prompt v2`, `--previous` 추가.
  v2 는 프롬프트 규칙(업종 이름이 글자로 있어야 known, 규모 표현·기술 분야 금지, 넓은 분류 남용 금지, 소상공인 정의의
  인원 기준 제외, 넓게 열어 둔 대상 문장 제외)에 더해 **코드 검사** 두 가지를 한다: 고른 업종의 글자(`SURFACE`)가 근거 문장에
  없으면 그 업종을 빼고, 근거에 "상시근로자"가 있으면 규모 정의로 보고 unknown 으로 내린다.
- 실행: `--prompt v2 --previous reports/industry_llm_sample_20260922T022756Z` → `reports/industry_llm_sample_20260922T023053Z/`.
  같은 seed·같은 30건(이전 실행과 ID 대조 통과). 추정 $0.0155 → 실제 **$0.0133**. DB 쓰기 0.
- 결과: known 정규식 0 → v1 20 → **v2 8**. 검사에서 내린 것 16건(대부분 "근거 문장에 업종 글자가 없음").
- Claude 가 v2 known 8건의 근거를 읽은 결과(사람 판정 아님):
  - 맞아 보임 4: 태백시(업종 목록 그대로) · 청주 "바이오 분야 중소기업"(other) · 제조 AI Agent "제조기업" · 수출 조사 "농식품 수출기업 및 농가".
  - **목록이 불완전 3**: 안동 "제조 및 무역업" → 제조업만(무역업 누락) · 진주 "여행사, 관광숙박업소 및 관광체험관" → 숙박업만 ·
    강화군 "[별표1] 생활밀접업종·100대 생활업종·택시 및 화물 운송업" → 운수업만.
  - 틀림 1: 충북 "도내 기업·농가·소상공인 등" → 농업(넓게 열어 둔 대상인데 LLM 이 known 으로 답했고 "농가" 글자가 있어 코드 검사도 통과).
  - 새로 놓침 1: 안산 "IT·SW 및 이에 준하는 기술분야" — v1 은 정보통신업으로 잡았는데 v2 는 기술 분야 규칙 때문에 unknown.
- 판단: v1 의 과잉 추론(절반가량 오류)은 크게 줄었다. 대신 **허용 업종 목록을 일부만 뽑는 문제**가 드러났다.
  허용 목록이 불완전하면 필터에서 목록 밖 신청자(예: 무역업체·여행사)를 떨어뜨린다 — 과잉 추론보다 더 해롭다.
  원인 중 하나는 12개 고정 어휘로 맞추게 한 설계다(무역업·여행사·관광체험관이 어휘에 없다).
- 미검증·남은 문제: 사람 정답 없음. 30건 중 known 이 8건뿐이라 비율 추정이 거칠다. 전량 실행·DB 적재는 하지 않았다.
- 다음 단계(사용자 결정): 업종을 **탈락 필터로 쓰지 말고** 근거 문장과 함께 "확인 필요/참고"로만 보여 주는 것을 권한다.
  필터로 쓰려면 ① 고정 어휘 대신 원문 업종 표현을 그대로 저장 ② "이 목록이 전부인가(complete)"를 따로 받고
  complete 가 아니면 필터에 쓰지 않기 ③ 사람 정답 30건으로 정확도 측정 — 이 세 가지가 먼저다.

### 2026-09-22 · Claude · 업종 LLM 추출 30건 표본 (DB 쓰기 없음)

- 요청·목적: 사용자가 "업종을 LLM 으로 넣은 것 아니었나"를 물었다. 확인 결과 업종을 LLM 으로 뽑는 경로는 없었다
  (`collect/extract_conditions.py` 는 업력만, `experiments/sql_semantic/conditions.py` 는 정규식). 사용자가 30건 표본을 요청.
- 변경 파일: `experiments/sql_semantic/industry_llm_sample.py`(신규). `collect/extract_conditions.py` 의 `build_document()`
  (지원대상 원문 + 공고 개요 + 첨부의 자격요건 구간)를 가져다 쓰고 그 파일은 고치지 않았다.
  응답은 JSON 스키마로 받고, 업종은 `conditions.py` 어휘 12개 중에서 고르게 했다(어휘 밖은 `other_industries`).
  근거 문장이 입력에 그대로 없으면 known/no_limit 을 unknown 으로 내린다.
- 입력: 실험 DB `lab_notices` 1,852건에서 seed 20260922 로 30건. 첨부는 출처 DB 에서 SELECT(23건에 첨부 있음).
  실험 DB·출처 DB 모두 SELECT 만, 쓰기 0건.
- 비용: `gpt-4o-mini`, 사전 추정 $0.0134 → 실제 **$0.0116**(입력 67,728 · 출력 2,379 토큰). 진행 전 사용자 승인.
- 결과(`reports/industry_llm_sample_20260922T022756Z/`): 정규식 known 0 / unknown 30 → LLM known 20 / unknown 10.
  근거 문장 불일치로 내린 것 6건(검증이 작동했다).
- **그러나 known 20건의 근거 문장을 Claude 가 읽어 보니 절반가량은 업종 제한이 아니었다(사람 판정 아님, Claude 의 읽기).**
  - 그럴듯한 예: 태백시 "지원가능 업종 ①제조업 ②지식·정보 관련업…", 안산 "IT·SW 및 이에 준하는 기술분야" → 정보통신업,
    청주 "바이오 분야 중소기업" → 바이오(단 농업을 함께 붙인 것은 틀림).
  - 과잉 추론 예: "중소기업" → 제조업(직무발명), "기업부설연구소" → 서비스업, "수출입 중소기업" → 제조업,
    "노동조합 설치 사업장" → 서비스업, "소상공인, 중소·중견기업, 의료기관" → 업종 10개,
    "대구 5대 신산업(헬스케어·로봇…)" → 제조업·서비스업.
  - 오독 유형: ① "중소기업·소상공인" 같은 규모 표현을 업종으로 바꿈 ② 기술 분야·사업 주제를 업종으로 바꿈
    ③ 고정 어휘에서 가장 가까운 것을 억지로 고름(특히 서비스업을 만능으로 씀) ④ 소상공인 정의의 업종별 인원 기준을 업종 제한으로 읽음.
- 전량 비용 추정: 30건 $0.0116 → 2,390건 약 $0.9 (같은 프롬프트·문서 길이 가정).
- 미검증·남은 문제: 사람 정답이 없어 정확도를 잴 수 없다. 위 분류는 Claude 의 읽기다. 프롬프트가 규모·분야 표현을
  업종으로 추론하는 것을 막지 못했다. 전량 실행·DB 적재는 하지 않았다.
- 다음 단계(사용자 결정): ① 프롬프트를 좁혀(근거 문장에 업종명이 직접 있어야 known, 규모 표현·기술 분야 금지,
  서비스업 같은 넓은 분류는 원문에 그 말이 있을 때만) 같은 30건으로 다시 비교(약 $0.012) ② 사람이 30건 정답을 달아
  정확도를 잰다. 두 가지 없이 전량을 돌리면 틀린 업종 조건이 필터에 들어가 멀쩡한 신청자를 떨어뜨릴 수 있다.
- 별도로 남은 일: [Codex 업종 탐침 리뷰](reviews/industry/INDUSTRY_WEIGHT_PROBE_REVIEW_20260922.md)의 F1 2건·F2 3건은 아직 반영하지 않았다.

### 2026-09-22 · Codex · 업종 가중치 탐침·화면 리뷰

- 요청·목적: Claude가 추가한 업종 강조 평가와 `/industry-probe` 화면의 코드·저장 결과·평가 계약 재검토.
- 판정: 화면은 탐색용으로 사용할 수 있으나, 현재 수치로 운영 결론을 확정하면 안 된다.
  상세 근거와 수정 기준은 [업종 가중치 탐침·화면 리뷰](reviews/industry/INDUSTRY_WEIGHT_PROBE_REVIEW_20260922.md)에 기록했다.
- 필수 수정 F1: 기준 검색어로만 만든 후보 풀을 네 변형의 최종 Top 3 채점에 사용해 변형별 미판정이 다르다.
  하이브리드 18칸 중 풀 밖은 그대로/없음/반복/앞배치 각각 2/3/0/2칸, 미판정은 5/5/3/6칸이다.
- 필수 수정 F1: LLM 판정용 신청자 설명에 `main_industry`가 없고, 새 아이디어 문장 자체가 업종을 직접 드러내
  명시 업종 필드의 추가 효과를 분리하지 못한다.
- 보완 F2: 실제 증분은 원시 LLM 340행(170쌍 × A/B), qrels 채택 131쌍, A/B 불일치 39쌍이다.
  P@3가 같아도 Top 3와 nDCG는 바뀌었으므로 “완전히 같은 순위/결과” 기록을 정정해야 한다.
- 보완 F2: 실행 지문과 새 탐침·API·화면 전용 회귀 테스트가 없다.
- 검증: 올바른 Python 3.12 환경에서 전체 **335개 통과, 13개 건너뜀**. qid·pool·qrels 중복 없음.
  구현·평가 데이터·서비스는 수정하거나 재실행하지 않았고 리뷰 문서만 남겼다. Git staging·commit·push 안 함.

### 2026-09-22 · Claude · 업종 강조 실험 화면 `/industry-probe` (기존 화면은 안 건드림)

- 요청·목적: 사용자가 업종 강조 탐침(위 항목) 결과를 "눈으로 직접 확인"하고 싶다고 요청.
  기존 `/verify`·`/compare` 화면은 그대로 두고 새 화면만 추가해 달라고 명시.
- 변경 파일(모두 신규, 기존 파일은 항목 하나만 추가):
  - `experiments/sql_semantic/industry_probe.py`(신규): 그대로·업종 없음·업종 반복·업종 앞배치
    네 변형을 **지금 실제 데이터**(운영 Chroma·BM25·MySQL, 읽기 전용)로 계산한다.
    `search/app.py` 파일은 고치지 않았다 — 이 모듈이 **자기 프로세스(뷰어) 안에서 서비스를 한 번 더
    부팅**해서 `app.build_query` 를 요청 처리 동안만 바꿔치기했다가 되돌린다. 8000 포트의 실제 서비스
    프로세스에는 영향이 없다. 동시 요청에 대비해 락으로 직렬화했다.
  - `web/industry_probe.html`(신규): 가짜 예시 6개(제조업·음식점업·정보통신업·농업·건설업·도소매업,
    `eval/industry_weight_probe.py` 의 q053~q058과 동일한 값) + 네 변형 결과를 나란히 보여준다.
    업종 칸이 비면 네 변형이 같아진다는 것을 화면에서 미리 알린다. 아무것도 저장하지 않는다.
  - `experiments/sql_semantic/viewer.py`(+29행만 추가): `GET /industry-probe`, `POST /api/industry-probe`
    두 라우트만 새로 붙였다. 기존 `/`·`/compare`·`/compare/selftest`·`/api/*` 는 코드를 건드리지 않았다.
- 검증(2026-09-22, 작업 PC): 뷰어 재시작 후 기존 `/`·`/compare`·`/api/health` 모두 200 확인(회귀 없음).
  `/api/industry-probe` 를 제조업 예시로 직접 호출 → 네 변형이 서로 다른 검색어·다른 Top 5 순서를 돌려줌
  (예: 그대로 1위 0.5045, 업종 앞배치는 순서가 바뀌어 다른 공고가 1위 0.5253) — 실제로 결과가 갈리는 것을
  확인했다. 브라우저에서 제조업 예시 버튼 → 검색 → 네 열 렌더링 확인. 단위 테스트는 추가하지 않았다
  (기존 `tests/test_verify_ui.py` 스위트에 이번 화면은 포함되지 않는다).
- 미검증·남은 문제: 이 화면은 자기 프로세스 안에서 서비스를 다시 부팅하므로 뷰어 메모리 사용량이 늘고
  첫 요청이 느리다(모델·BM25 재적재, 약 1~2분). 새 화면 전용 자동화 테스트는 없다 — 사람이 눈으로 보는 용도다.
- 다음 단계: 필요하면 `tests/test_verify_ui.py` 에 `/api/industry-probe` 회귀 테스트를 추가한다.
  결론(업종 강조 유의미한 차이 없음)은 위 탐침 결과 그대로이며, 이 화면이 그 결론을 바꾸지 않는다.

### 2026-09-22 · Claude · 업종(main_industry) 강조 탐침 — 새 질의 6개 + LLM 판정

- 요청·목적: 사용자가 "신청자 입력 중 주업종 같은 항목에 가중치를 주면 좋지 않을까"를 제안.
  확인해보니 기존 평가 질의 60개(`eval/queries.jsonl`)에 `main_industry` 가 채워진 질의가 **0개**라
  업종 강조 효과를 잴 정답 자체가 없었다. 사용자가 "업종 있는 시나리오를 새로 만들고 LLM 판정"(방법 B)을 선택했다.
- 작업 전 상태: `eval/queries.jsonl` 60개(정상 52·부정 8), `eval/qrels.jsonl` 1,277쌍. 기존 52개 질의는 이번에 건드리지 않았다.
- 변경 파일:
  - `eval/queries.jsonl`(+6행, q053~q058): 제조업·음식점업·정보통신업·농업·건설업·도소매업 각 1건.
    기존 60행은 그대로 두고 뒤에 이어 붙였다.
  - `eval/pool.jsonl`(+170쌍), `eval/llm_judgments.jsonl`(+340행), `eval/qrels.jsonl`(+340쌍, 1,617쌍) —
    `build_pool.py --qids q053..q058` → `judge_llm.py --qids q053..q058` → `merge_qrels.py` 로 만들었다.
    기존 54개 질의의 판정은 손대지 않았다(재확인만 됐고 값은 그대로).
  - `eval/industry_weight_probe.py`(신규): `eval/query_ablation.py`(수정 안 함)의 `Pipeline`·`pinned_today`·
    `metrics`·`summarize`·`load_qrels` 를 재사용해 `app.build_query` 를 실행 중에만 바꿔 끼운다.
    `search/app.py`·`eval/query_ablation.py` 는 고치지 않았다.
- 비용: LLM 판정 340호출(`gpt-4.1-mini`), 사전 추정 $0.38 → 실제 **$0.317**(진행 전 사용자 승인받음).
- 변형 4가지 (검색어 문장만 바꾼다, 입력 자체는 그대로): 그대로(지금 서비스와 동일, "업종: X" 1회) ·
  업종 없음(그 조각을 뺀다) · 업종 반복(한 번 더 붙인다) · 업종 앞배치(문장 맨 앞으로 옮긴다).
- 검증: `python -X utf8 eval/industry_weight_probe.py` → `reports/industry_weight_probe_20260922T020705Z/`.
  결과(P@3(2), 새 질의 6개, 서비스 기본인 **하이브리드** 기준, 그대로=0.444):
  - 업종 없음 −0.056 (95% −0.222~+0.111) · 업종 반복 +0.000(그대로와 완전히 같은 순위) · 업종 앞배치 −0.056 (95% −0.167~+0.000).
  - **95% 구간이 전부 0을 포함한다 — "강조하면 좋아진다"는 근거가 없다.** 점 추정은 오히려 반복·앞배치가
    그대로보다 낫거나 같지 나빠지지 않는 정도이고, 없앴을 때만 소폭 하락(유의하지 않음)했다.
  - 의미 검색만(dense) 기준으로는 네 변형이 **완전히 같은 결과**를 냈다(P@3 0.389 동일) — 이 후보군 규모(28~30건)에서는
    업종 문구를 넣거나 빼거나 반복해도 최근접 순위 자체가 안 바뀌었다.
- 미검증·남은 문제: 질의 6개뿐이라 신뢰구간이 넓다. 정답은 340건 모두 LLM 잠정 판정(사람 검수 없음, 기존 qrels와 같은 한계).
  업종 텍스트를 "굵게" 다루는 방법(예: BM25 자체 필드 가중치)은 시도하지 않았다 — 검색어 문장 조합만 바꿨다.
- 다음 단계: 지금 근거로는 업종 가중치(강조)를 서비스에 반영할 이유가 없다. 필요하면 질의를 더 늘리고
  사람 판정을 받아야 결론을 낼 수 있다. `search/app.py`는 이번에도 그대로다.

### 2026-09-22 · Claude · Chroma 정합성 재검사 (공고 2,390건)

- 요청·목적: 9/22 아침 수집 배치로 공고가 2,328 → 2,390건으로 늘어, 새 공고까지 Chroma 가 맞는지 사용자가 재검사를 요청했다.
- 실행: `python -X utf8 eval/search_comparison.py --check-only` → **통과, 종료코드 0**, `chroma_content_verified = True`
  (`reports/chroma_integrity_20260922T002708Z/`). DB 는 SELECT 만, Chroma 는 복사본만 열었다.
- 결과: DB↔NPZ 2,390건 통과 · 메타데이터 통과 · NPZ↔Chroma 2,390건 모두 허용 이내(바이트 일치 1,824 · 재정규화 일치 566 ·
  최대 차이 1.49e-8) · 검사 중 변경 없음. 어제 재동기화한 `kstartup:179193` 도 계속 맞다.
- 변경 파일: 없음(보고서 폴더만 새로 생김). 이 PC 의 Chroma 만 봤다 — EC2 쪽 벡터는 여전히 확인하지 않았다.

### 2026-09-21 · Codex · Claude 입력 확장·검색어 ablation 수정 재검토

- 요청·목적: Claude가 Codex의 `/compare` 입력 확장 리뷰와 검색어 ablation 리뷰를 반영한 뒤 사용자 재검토 요청.
- 작업 전 상태: Claude 보고상 전체 335개 통과, `/compare/selftest` 14개 통과, ablation을 실제 서비스 `match()` 경로로 재실행한 상태.
- 변경 파일: [입력 확장 리뷰](reviews/ui/COMPARE_INPUT_EXPANSION_REVIEW_20260921.md)와
  [ablation 리뷰](reviews/search/QUERY_ABLATION_REVIEW_20260921.md)에 후속 판정 추가, `STATUS.md`와 이 기록 갱신.
  구현·테스트·검색 결과는 수정하지 않았다.
- 전후 차이·선택 이유: `/compare` 기존 P1·P2×4·P3는 해결로 승인했다. 검색어 실험의 최종 경로와
  “차이를 말할 수 없다”는 해석도 승인했지만, DB 지문이 `notice_id|apply_end`만 해시해 실제 검색 문서와 규칙 필드 변경을
  놓치는 재현성 P2를 새로 기록했다. 검증 오류 뒤 예시 적용 시 이전 오류 상태줄이 남는 `/compare` P3도 기록했다.
- 검증: 관련 43개 통과. 전체 **335개 통과, 13개 건너뜀**. 날짜 뒤 문자열 거부, 반복 행 20개 승인·21개 거부,
  새 방식 `district` 미전달을 별도 확인. 실제 브라우저 `/compare/selftest` **14개 통과·0 실패**,
  일반 `/compare`에서 인증 초기화·유형 전환·결과 무효화 확인. 저장 해시 3개 일치, `per_query.jsonl` 1,200행,
  NPZ 2,328개 × 1,024차원 확인.
- 미검증·남은 문제: `/compare` 상태줄 P3. ablation DB 지문 P2. 대표자/팀원 이력 분리 평가와 채용 계획 보유 질의는 아직 없다.
- 다음 단계: Claude는 상태줄 회귀 시험을 추가하고, DB의 BM25·최종 규칙 사용 필드 전체를 해시하도록 manifest를 고친 뒤
  ablation을 재실행한다. 운영 `build_query()`는 사람 판정 확대 전까지 바꾸지 않는다. Git staging·commit·push는 하지 않았다.

### 2026-09-21 · Claude · 검색어 구성 비교 재실행 — 서비스 match() 통과 (Codex ablation 리뷰 반영)

- 요청·목적: [Codex ablation 리뷰](reviews/search/QUERY_ABLATION_REVIEW_20260921.md) P1·P2·P2 반영. 첫 실행(`081116Z`)은 검색 직후 순위만 쟀고
  입력에서 팀 칸을 지워 대상 집단 규칙에서도 빠졌다 — **운영 결정 근거로 쓰지 않는다(정정).**
- 변경 파일:
  - `eval/query_ablation.py`(재작성): 서비스 `search/app.match()` 를 **그대로** 부른다. 입력은 그대로 두고 `build_query` 만 바꿔 끼워
    검색어 문장만 바꾼다(팀 경력은 규칙에 계속 쓰인다). 벡터는 Chroma 대신 같은 벡터 파일을 읽는 `NumpyCollection` 대역
    (count·query·get). '오늘' 은 평가 기준일 2026-09-15 로 고정. 원시 Top 3(검색 직후)과 **최종 Top 3(match)** 를 나눠 저장.
    manifest 에 질의·qrels·NPZ 해시, 모델 리비전, DB 공고 수·(ID|마감일) 지문, BM25 문서 수, 후보 깊이·Top-K·RRF·규칙 방식,
    서비스 기본값, 평가셋 구성(팀 35 · 수익 51 · 채용 0)을 남기고 per_query 에 같은 run_at 을 적는다. 변형 이름을 `-팀경력` 으로 정정.
  - `tests/test_query_ablation.py`(신규 9개): 검색어만 바뀌고 입력은 보존, 규칙이 팀 경력을 계속 봄, 최종 경로가 마감 숨김·다른 지역 뒤로 보냄,
    하이브리드에서 검색어 변화가 BM25 까지 감, 기준일 고정, 서비스 기본값(top 3·마감 숨김·규칙 켬·hybrid·RRF 1/1/60·order·깊이 50) 고정, 보고서 형식.
- 실행: `python -X utf8 eval/query_ablation.py` → `reports/query_ablation_20260921T083240Z/` (서비스 코드 수정 없음, OpenAI 호출 없음).
- 결과 — **최종 Top 3 · 하이브리드**(서비스 기본, 전체 0.564):
  -팀경력 −0.013 (−0.064~+0.038) · -수익모델 −0.026 (−0.083~+0.026) · -팀경력-수익모델 −0.032 (−0.083~+0.019) ·
  +채용계획 −0.019 (−0.071~+0.026). **모두 95% 구간이 0 을 포함.** 미판정은 0.212 → 0.244~0.282 로 늘었다.
  첫 실행(원시)에서 약간 +였던 -수익모델이 최종에서는 −로 뒤집혔다 — 검색 직후 순위로 판단하면 안 된다는 리뷰 지적과 맞다.
  사람 판정은 하이브리드 최종 Top 3 156칸 중 16~19칸뿐이다.
- 결론: **이 데이터로는 빼도 된다·안 된다 어느 쪽도 말할 수 없다.** 점 추정은 최종 기준 모두 소폭 마이너스지만 오차 범위 안이고
  미판정 증가(0점 처리)의 영향도 섞여 있다. 운영 변경 전에 사람 판정 범위를 넓혀야 한다. 서비스 코드는 그대로다.
- 남은 것: 대표자 이력과 팀원 이력을 나눈 평가셋이 없다. 채용 계획이 있는 평가 질의가 없다.

### 2026-09-21 · Claude · /compare 입력 확장 리뷰 반영 (P1·P2×4·P3)

- 요청·목적: [Codex 입력 확장 리뷰](reviews/ui/COMPARE_INPUT_EXPANSION_REVIEW_20260921.md) 반영.
- 변경 파일:
  - `web/compare.html`: P1 `resetForm()` — 예시 적용 전에 모든 입력·체크박스·반복 행·조건부 값을 지운다(몇 개씩은 유지).
    P2 결과 무효화 — 제출한 입력 복사본을 페이지 메모리에만 두고 지금 입력과 다르면 결과·사용 여부 표를 지우고
    `입력이 바뀌었습니다. 다시 검색하세요` 안내. 검색 중 입력이 바뀌면 세대 번호로 늦은 응답을 버린다.
    P2 행 제한 — 20행에서 추가 버튼을 막고 이유를 글로 알린다. P2 접근성 — 수익모델·팀 묶음 `role="group"`·이름·오류 설명 연결,
    행 입력에 `aria-required`(수익모델)·`aria-describedby`, 오류 행 입력에 `aria-invalid` 와 초점, 서버 오류 행 번호를 화면 행으로 옮김.
    자체 시험용 `window.__compare` 손잡이.
  - `web/compare_selftest.html`(신규) + `viewer.py` `GET /compare/selftest`: 브라우저 동작 자체 시험 14개. 이 PC 에 jsdom 등 DOM 시험 도구가
    없어 새로 내려받지 않고 브라우저에서 도는 시험 페이지로 만들었다.
  - `compare_input.py`: P2 날짜는 정확히 `YYYY-MM-DD` 만(뒤 글자·`19800101`·없는 날짜 거부, 윤년 허용).
    P2 수익모델·팀 21개 이상은 **자르기 전에** 400. P3 새 방식에 시·군·구를 넘기지 않는다.
  - `tests/test_verify_ui.py` (+4): 날짜 경계, 20개 승인·21개 거부, 새 방식 시·군·구 미전달, 자체 시험 페이지·손잡이.
- 검증(2026-09-21, 작업 PC): 전체 **335개 통과(건너뜀 13) 3회**. 실제 8010 에서 `/compare/selftest` **14개 통과·0 실패**, 콘솔 오류 없음.
  첫 실행에서 1개가 실패했는데 **시험 기대가 틀렸다** — 빈 팀 행 추가는 보낼 내용이 같아 결과를 유지하는 게 맞다.
  시험을 "빈 행은 유지, 내용 있는 행 추가·삭제·예시 전환은 무효화" 로 고쳤다.
  접근성: 브라우저 도구의 접근성 트리는 역할·이름만 보여 줘서, 수익모델 묶음 role=group·이름·설명과 오류 입력의
  ariaRequired=true·ariaInvalid=true·설명·초점을 ARIA 속성 값으로 확인했다.
- 다음 단계: Codex 재검토.

### 2026-09-21 · Codex · 최신 Claude 작업 재검토

- 요청·목적: `/compare` 신청자 입력 확장과 함께 추가된 검색어 구성 ablation을 독립 검토하고 Claude가 읽을 문서로 남긴다.
- 변경 파일: 리뷰 문서 [COMPARE_INPUT_EXPANSION_REVIEW_20260921.md](reviews/ui/COMPARE_INPUT_EXPANSION_REVIEW_20260921.md),
  [QUERY_ABLATION_REVIEW_20260921.md](reviews/search/QUERY_ABLATION_REVIEW_20260921.md), 상태 인계 문서만 갱신. 구현·테스트·데이터는 수정하지 않았다.
- 확인 결과: `/compare` 전용 30개와 전체 322개 통과(13개 건너뜀). 큰 입력 계약은 맞지만 실제 브라우저에서
  예시 미초기화로 이전 인증이 섞이고 입력 변경 뒤 이전 결과가 남는 문제를 확인했다. 서버는 날짜 뒤 문자열을 승인하고
  반복 행 21개를 오류 없이 20개로 줄였다. ablation 저장 수치는 맞지만 실제 서비스의 마감 필터·규칙 재정렬 전 순위다.
- 미검증·남은 문제: Claude가 위 리뷰의 P1·P2를 수정한 뒤 UI 상태 전이와 서비스 최종 순위 기준으로 재검토·재실행한다.
- Git staging·commit·push는 하지 않았다.

### 2026-09-21 · Claude · 검색어 구성 비교 (이력·수익모델·채용 계획 넣음 vs 뺌)

- 요청·목적: 사용자가 대표자·팀 이력, 수익모델 항목, 채용 계획을 매칭에서 빼는 게 맞는지 비교를 요청했다.
  보유 인증·성별은 자격·우대와 관련돼 남긴다(사용자 확인). 협력기관은 결정 전.
- 변경 파일: `eval/query_ablation.py`(신규). 서비스의 `build_query` 를 그대로 부르고 입력에서 칸만 뺀다. 서비스 코드 수정 없음.
  의미 검색은 벡터 파일(numpy 엔진)로 — Chroma 원본을 열지 않는다. BM25 는 DB(SELECT)에서 메모리로. OpenAI 호출 없음.
- 실행(2026-09-21, 작업 PC): `python -X utf8 eval/query_ablation.py` → `reports/query_ablation_20260921T081116Z/`.
  정답 human 143 · llm 473 · llm_old 870 쌍(judges=all), 정상 질의 52개.
- 결과 (P@3(2), 서비스 기본인 **하이브리드** 기준, 전체 0.583):
  - -이력 −0.013 (95% −0.058~+0.038) · -수익모델 +0.019 (−0.038~+0.077) · -이력-수익모델 +0.006 (−0.051~+0.064)
    → **세 변형 모두 95% 구간이 0 을 포함 — 품질 차이가 있다고 말할 수 없다.** 상위 3 중 바뀐 칸은 156칸 중 30~53칸.
  - 의미 검색만: -수익모델 +0.051 (−0.006~+0.109)로 가장 컸지만 역시 0 을 포함.
  - 판정칸만 값은 뺀 쪽이 약간 높았다(하이브리드 0.696 → 0.731/0.737). 미판정은 조금 늘었다(0.179 → 0.186~0.205).
  - +채용계획(모든 질의에 켬): 하이브리드 −0.045 (−0.083~−0.006), 상위 3 중 27칸 바뀜.
    **평가 질의 60개 중 채용 계획이 있는 신청자가 0명**이라 품질 비교가 아니다 — 채용 계획이 없는 사람에게
    '고용 계획 있음' 을 붙이면 결과가 그쪽으로 끌려간다는 영향 크기만 보여 준다.
- 한계: 대부분 LLM 잠정 판정(사람 일치율 0.64 < 0.70), 질의 52개, 미판정은 0점 처리. 사람 판정 없음.
- 다음 단계: 사용자 결정 — 서비스 검색어에서 이력·수익모델을 뺄지(뺀다면 `search/app.py` 수정 = 운영 매칭 변경),
  채용 계획을 검색어 대신 다른 방식으로 쓸지.

### 2026-09-21 · Claude · /compare 신청자 입력 확장

- 요청·목적: [Codex 지시서](reviews/ui/COMPARE_INPUT_EXPANSION_TASK_20260921.md) — 사용자가 정한 신청자 정보 전체를 /compare 에서 받고,
  세 방식에 넘기는 값과 실제 사용 여부를 구분해 보여 준다.
- 사용자 결정(2026-09-21): **설립일은 개인사업자·법인만 필수**(업력 판정에 필요, 예비창업자는 받지 않음) ·
  **성별은 여성/남성/응답 안 함 중 필수**('응답 안 함' 은 성별 규칙 미적용).
- 변경 파일:
  - `experiments/sql_semantic/compare_input.py`(신규): Pydantic 입력 모델 + `validate()`(필수·조건부 필수·형식, 오류에 값 미포함,
    유형에 맞지 않는 칸 제거) · `service_payload()` · `lab_applicant()`(업종 어휘 변환) · `input_summary()`(개인정보 제외) · `field_usage()`.
    Pydantic 기본 오류는 입력값을 되돌려주므로 칸 이름만 남기도록 바꿔 담았다.
  - `viewer.py`: `api_compare` 를 입력 계약으로 교체, 응답의 `input`(입력 전체 되돌림)을 없애고 `input_summary`·`usage` 추가,
    `GET /api/compare/form`(시·도·시군구·인증 선택지 — 서비스 화면과 같은 모듈의 어휘).
  - `web/compare.html`: 7개 묶음 폼(유형 → 대표자 → 사업 → 이력 → 아이디어·수익모델 → 선택 → 실행), 필수는 글자 `* 필수` +
    `required`/`aria-required`, 칸별 오류(`aria-invalid`·`aria-describedby`)와 첫 오류로 초점, 유형 전환 시 조건부 칸 숨김·값 삭제,
    수익모델·팀 반복 행, 가짜 예시 3개, 결과 아래 사용 여부 표. 브라우저 저장소·주소창 사용 없음.
  - `tests/test_verify_ui.py`: 기존 /compare 13개를 전체 가짜 입력으로 바꾸고, 입력 확장 17개 추가(지시서 필수 테스트 1~13).
- 서비스(`search/`, `web/app.html`) 코드는 바꾸지 않았다. 서비스 메인 화면이 직전 입력을 localStorage 에 저장하는 동작은
  이번 범위가 아니라 점검만 하고 고치지 않았다(아래 남은 것).
- 검증(2026-09-21, 작업 PC): 전체 **322개 통과(건너뜀 13) 3회**. 실제 8000·8010 에서 브라우저 확인:
  빈 제출 → 9개 칸 오류·첫 칸 초점·상태 공지 / 법인 예시에서 예비창업자로 바꾸면 사업자번호·설립일 칸이 숨고 값이 비며 요청에서 빠짐 /
  법인 가짜 예시 검색 → 세 열 15건·사용 여부 표 19행, 새 방식에 업종 "제조업" 전달 / localStorage 비어 있음, 주소 변화 없음, 콘솔 오류 없음 /
  8000·8010 서버 출력에 가짜 이름·사업자번호·생년월일 0건.
- 남은 것: 새 방식은 업종 조건이 공고 쪽에서 거의 모두 '정보 없음'이라 업종을 넘겨도 대부분 '확인 필요'로 나온다(데이터 한계).
  서비스 메인 화면(`web/app.html`)은 이름·생년월일·사업자번호를 포함한 직전 입력을 localStorage 에 저장한다 — 별도 판단 필요.
- 다음 단계: Codex 재검토.

### 2026-09-21 · Claude · /compare Codex 승인 기록

- [Codex 후속 재검토](reviews/ui/COMPARE_UI_REVIEW_20260921.md#후속-재검토--p2p3-반영-결과-2026-09-21): P2 2건·P3 3건 해결 확인, **/compare 승인**. 새 차단 결함 없음.
  Codex 독립 확인: /compare 테스트 13개·전체 305개 통과, 실행 중 8010 에서 잘못된 top → 400, 외식 예시 세 방식 Top 5 공통 2건, 콘솔 오류 없음.
- 유지되는 한계: 두 방식의 공고 집합·검색어가 다르고 사람 판정이 없어 이 화면으로 품질 우위를 말하지 않는다.
- 비차단으로 남은 것: `eval/search_comparison.py` 와 기존 테스트의 ResourceWarning(이전 리뷰에서 기록).

### 2026-09-21 · Claude · /compare 리뷰 반영 (P2 2건 · P3 3건)

- 요청·목적: [Codex /compare 리뷰](reviews/ui/COMPARE_UI_REVIEW_20260921.md) 반영. 리뷰는 세 검색 실행·표시 기본 동작을 정상으로 봤다.
- 변경 파일:
  - `experiments/sql_semantic/viewer.py`
    - P2 Top N 범위: 겹침은 세 방식의 **Top N 목록 안에서만** 센다는 것을 응답에 `top`·`overlap_scope` 로 명시.
    - P2 낡은 캐시: `lab_notice_ids()` 를 **요청마다 새로 SELECT** 한다(영구 캐시 제거). 읽기 실패 시 비교는 계속하고
      `lab_ids_error` 로 배지를 못 붙인 이유를 돌려준다.
    - P3 입력 검증: `parse_top()` — 정수만 받아 1~10 으로 자르고 `'abc'`·`1.5`·`true` 는 **400**(예전엔 500 또는 조용히 1로 잘림).
  - `web/compare.html`: 배지를 `이 방식 Top N에만` · `… Top N에도` · `세 방식 Top N 공통` 으로, 상태 문구와 결과 위에 범위 설명.
    링크는 `http:`·`https:` 만(`safeUrl`), 상태 영역 `role="status"`·`aria-live="polite"`. 안내에 Top N 범위 항목 추가.
  - `tests/test_verify_ui.py` (+6): Top 5 단독 → Top 10 겹침과 범위 문구, 범위 없는 독점 문구 금지,
    **같은 프로세스에서 두 번째 요청이 바뀐 실험 DB 목록을 읽음**, ID 읽기 실패 안내, 잘못된 top 은 400·검색 미호출, 링크·상태 공지.
- 검증(2026-09-21, 작업 PC): 전체 **305개 통과(건너뜀 13) 3회**. 실제 8010 재기동 후
  `top='abc'` → 400. 제조 예시 Top 5 에서 `kstartup:178831` 은 hybrid 만, Top 10 에서는 hybrid·dense —
  리뷰의 반례가 그대로 재현되고 이제 범위가 붙어 표시된다. 실험 DB 목록 1,852건을 요청마다 읽음.
- 다음 단계: Codex 재검토.

### 2026-09-21 · Claude · 직접 검색 비교 화면 (/compare)

- 요청·목적: 사용자가 공고 검색을 직접 해 보며 기존 방식과 새 방식 결과를 비교하고 싶어 했다.
  8000 서비스에 직접 넣는 안과 별도 화면 안을 제시했고, 사용자가 **별도 비교 화면**을 골랐다
  (8000 코드는 EC2 에도 배포되므로 실험 DB 를 부르는 코드를 섞지 않는다).
- 변경 파일:
  - `experiments/sql_semantic/viewer.py`: `POST /api/compare`, `GET /compare`. 기존 서비스 `/api/match` 를 hybrid·dense 로 두 번
    HTTP 호출하고, 새 방식은 `search.run`(실험 DB SELECT, 모델은 첫 요청에 한 번 올림)으로 돌린다. 세 결과에 어느 방식에 같이
    나왔는지·새 방식 데이터에 있는 공고인지 표시. 서비스·실험 DB 실패는 그 열에 이유로 보여 주고 죽지 않는다. top 은 1~10.
  - `web/compare.html`(신규): 입력 폼·예시 3개·세 열 결과·비교 한계 안내. 외부 자원 없음.
  - `web/verify.html`: 비교 화면 링크. `tests/test_verify_ui.py` +7(페이지·필수 입력·세 열과 겹침 표시·서비스 꺼짐·새 방식 실패·top 제한·링크).
  - `docs/guides/VERIFY_UI.md`: 사용법.
- 서비스 코드(`search/`, `web/app.html`)는 바꾸지 않았다.
- 검증(2026-09-21, 작업 PC): 전체 **299개 통과(건너뜀 13)**. 8000(기존 서비스, 오늘 켬)과 8010 을 띄우고 실제 비교 1회:
  20초(모델 첫 로드 포함), 오류 없음. 제조 예시에서 세 방식 모두에 나온 공고 0건, 새 방식은 SQL 762 → 조건 740 → 반환 5.
  브라우저에서 세 열이 뜨고 콘솔 오류 없음을 확인했다.
- 한계: 두 방식은 공고 집합·검색어가 달라 결과 차이를 방식의 우열로 읽을 수 없다. 사람 판정 없음(사용자 결정으로 보류).

### 2026-09-21 · Claude · `kstartup:179193` Chroma 한 건 재동기화 (사용자 승인)

- 요청·목적: Codex 가 승인한 검사 도구로 찾은 유일한 불일치를 고친다. 사용자가 **백업 후 진행**을 승인했다.
- 대상: 이 PC 의 `data/vecstore/chroma` 만. EC2 벡터 저장소·DB·NPZ 는 건드리지 않았다. 모델을 돌리지 않았다.
- 실행(2026-09-21, 작업 PC):
  1. 백업 `data/vecstore/chroma_backup_20260921T_before_179193_sync/`(14MB, Git 제외 폴더 안) — 원본과 파일 6개 크기·sha256 일치,
     복사 중 원본 변경 없음. 원본 지문은 `..._fingerprint.json` 에 남겼다.
  2. `vecstore.sync(['kstartup:179193'])` → `{'upserted': 1, 'indexed': 2328, 'vectors': 2328, 'missing': 0}`.
  3. `search_comparison.py --check-only` → **통과, 종료코드 0**, `chroma_content_verified = True`
     (`reports/chroma_integrity_20260921T050045Z/`). DB↔NPZ 2,328건 통과 · 메타 통과 ·
     NPZ↔Chroma 바이트 일치 1,776(+1) · 재정규화 일치 552 · 최대 차이 1.49e-8.
  4. 백업 ↔ 현재 Chroma 전 벡터 대조: ID 집합 같음, **값이 바뀐 공고는 `kstartup:179193` 한 건뿐**, 컬렉션 메타데이터 같음.
     179193 의 현재 Chroma 벡터는 NPZ 와 차이 0.0.
- 변경 파일: `viewer.py`(Chroma 상태 `통과 · 검사 도구 Codex 승인`), `tests/test_verify_ui.py`(상태 문구),
  `reports/chroma_integrity_20260921T031931Z/investigation.md`(후속 기록 추가).
- 되돌리기: `data/vecstore/chroma` 를 백업 폴더로 교체하면 재동기화 전 상태가 된다.
- 하지 않은 것: dense/hybrid 비교(40검색) 재실행 — 이제 사전 검사를 통과하므로 돌리면 서버를 켜고 새 결과 폴더를 만든다. 요청이 없어 돌리지 않았다.
  EC2 에 올라간 벡터(`vector_upload`)에 같은 문제가 있는지는 확인하지 않았다. 과거 `054314Z` 정합성은 소급 보증하지 않는다.
  179193 이 왜 어긋났는지(경로)는 여전히 확정하지 못했다.

### 2026-09-21 · Claude · Chroma 검사 도구 Codex 승인 반영

- [Codex 후속 재검토](reviews/chroma/CHROMA_INTEGRITY_REVIEW_20260921.md#후속-재검토--사전-검사-재사용-조건-보완-2026-09-21): **검사 도구 승인.**
  46개·전체 292개 통과와 실제 일반 비교의 부팅 전 중단을 독립 확인했다.
- 도구는 승인됐지만 **데이터는 아직 통과가 아니다** — `kstartup:179193` 한 건의 NPZ↔Chroma 불일치가 남아 있다.
- 변경: `viewer.py` Chroma 상태를 `검사 도구 Codex 승인 · 데이터 불일치 1건` 으로.
- 비차단 관찰(고치지 않음): `search_comparison.py` 의 HTML·INVALID.md 쓰기에서 ResourceWarning,
  사전 검사 뒤 NPZ 가 지워지는 경쟁 상황에서 지문 계산이 FileNotFoundError 로 끝날 수 있음(거짓 통과는 아님).
- 다음 단계: 179193 재동기화(Chroma 쓰기) **사용자 승인 대기** → `--check-only` 로 세 부분 모두 통과·`chroma_content_verified=True` 확인.

### 2026-09-21 · Claude · Chroma 사전 검사 재사용 조건 보완 (Codex 후속 리뷰 P2)

- 요청·목적: [Codex 후속 재검토](reviews/chroma/CHROMA_INTEGRITY_REVIEW_20260921.md#후속-재검토--1차-리뷰-반영-결과-2026-09-21)의 P2 를 고친다.
  재검토는 앞선 P1·P2·P2·낮음 2건을 **해결로 확인**했고, 최신 실제 검사(`034104Z`)를 신뢰할 수 있다고 봤다.
- 문제: `data_check(preflight)` 가 DB 해시만 같으면 사전 검사 결과를 재사용했다. 사전 검사 뒤 `app.boot()` 나 동시 배치가
  NPZ·Chroma 벡터만 바꾸면(ID 는 그대로) 옛 통과 판정으로 검색할 수 있었다. 지금은 사전 검사에서 이미 멈추므로 실제로 일어나지는 않았다.
- 변경 파일:
  - `eval/search_comparison.py`: `preflight_reuse_problem()` — 사전 검사가 통과했고, DB 해시·NPZ 파일 sha256·Chroma 원본 폴더 전체 지문이
    사전 검사 **종료 시점**과 모두 같을 때만 재사용한다. 하나라도 다르면 이유를 남기고 지금 상태로 다시 검사한다.
    `data_fingerprint()` — 검색 직전 데이터 지문(DB 해시·NPZ 해시·Chroma 폴더 지문 해시·양쪽 벡터 집합 해시)을
    `chroma_content` 에 넣어 manifest 에 남긴다. `preflight_reused`·`recheck_reason` 도 함께 기록한다.
  - `tests/test_chroma_integrity.py` (40 → 46): 실제 `check()` 로 통과한 사전 검사를 만든 뒤
    변경 없음(재사용)·DB 변경·**NPZ 벡터 값만 변경(ID 동일)**·**Chroma 파일만 변경**·실패/지문 없는 사전 검사·manifest 지문.
- 참고: `app.boot()` 는 원본 Chroma 를 열기 때문에 부팅 뒤 Chroma 폴더 지문이 바뀔 수 있다. 그 경우 재사용하지 않고 다시 검사한다
  (느려질 뿐 안전한 쪽). 실제 부팅 뒤 지문이 바뀌는지는 현재 사전 검사가 불일치로 멈춰 확인하지 못했다.
- 검증: 전체 **292개 통과(건너뜀 13) 3회**. Chroma 테스트 46개는 ResourceWarning 을 오류로 바꿔도 통과.
  실제 일반 비교 재실행 → 사전 검사에서 종료코드 2, 새 결과 폴더 없음, 원본 `chroma.sqlite3` 수정 시각 12:13:27 그대로.
- 다음 단계: Codex 재검토. `kstartup:179193` 재동기화(Chroma 쓰기)는 사용자 승인 대기.

### 2026-09-21 · Claude · Chroma 검사 도구 리뷰 3건 반영과 재실행

- 요청·목적: [Codex Chroma 리뷰](reviews/chroma/CHROMA_INTEGRITY_REVIEW_20260921.md)의 P1·P2·P2 와 낮은 우선순위 2건을 고친다.
  리뷰는 **불일치 1건 발견 자체는 타당**(독립 재현)하다고 봤고, 도구의 거짓 통과·중단 순서를 지적했다.
- 변경 파일:
  - `eval/chroma_integrity.py`
    - P1: NPZ·Chroma **양쪽** 벡터를 1차원·기대 차원·유한값으로 검증한 뒤에만 비교한다(`validate`).
      NPZ 이상은 `npz_broken`, Chroma 이상은 `broken` 으로 출처를 나눠 보고한다. 비교식을 `not diff <= atol` 로 바꿔 NaN 이 통과로 새지 않게 했다.
      기대 차원은 NPZ meta 가 아니라 현재 설정에서 가져온다. NPZ 파일 없음·키 없음·배열 길이 불일치는 traceback 대신 `확인 실패` 보고서를 남긴다.
    - P2: `chroma_content_verified` 는 `db_npz`·`npz_chroma`·`meta` 가 모두 통과하고 변경이 없을 때만 참이다.
    - 낮음: `summary.md` 를 `with` 로 닫는다. `code_sha256` 에 `eval/search_comparison.py` 를 넣었다.
  - `eval/search_comparison.py` (P2): `preflight_check()` 를 **`app.boot()` 전에** 부른다. 통과하지 않으면 서버·모델을 켜지 않고 종료코드 2.
    통과하면 부팅 뒤 `data_check(preflight)` 가 DB·BM25·행 검사를 계속한다. 사전 검사 뒤 DB 해시가 바뀌었으면 Chroma 검사를 다시 한다.
  - `tests/test_chroma_integrity.py` (27 → 40): NPZ NaN·Inf·잘못된 차원·출처 구분, DB stale/missing/extra·DB 읽기 실패 시 플래그 false,
    NPZ 파일 없음·키 없음·길이 불일치, 확인 실패 보고서 작성, **사전 검사 실패 시 `app.boot`·`app._encode`·`app.match`·`data_check` 미호출**,
    통과 시 `preflight → boot → data_check` 순서. 테스트 안의 미닫힌 파일도 닫았다.
  - `tests/test_search_comparison.py`: 사전 검사 통과 픽스처 추가, `data_check` 가짜가 인자를 받게 수정, docstring raw 처리.
  - `experiments/sql_semantic/viewer.py`: Chroma 항목의 근거 폴더를 최신 결과로.
- 검증(2026-09-21, 작업 PC):
  - 전체 **286개 통과(건너뜀 13) 3회**. Chroma 테스트는 ResourceWarning 을 오류로 바꿔도 통과.
  - 실제 `--check-only` 재실행 → `reports/chroma_integrity_20260921T034104Z/`, 종료코드 2. **DB 접속 정상**(Codex 재검토 때는 실패했었다).
    DB↔NPZ 통과(2,328) · 메타 통과 · NPZ↔Chroma 는 여전히 `kstartup:179193` 1건만 불일치(코사인 0.9866), NPZ 이상 0건, 검사 중 변경 없음.
  - 실제 일반 비교 `python eval/search_comparison.py` → 사전 검사에서 **종료코드 2**로 멈춤, 새 결과 폴더 없음.
    원본 `chroma.sqlite3` 수정 시각이 12:13:27 그대로 — `app.boot()`(원본 Chroma 를 연다)가 불리지 않았다는 실제 근거.
- 남은 것: Codex 권고 순서 2단계까지 왔다(수정 → DB 정상 시 재검사에서 179193 한 건만 불일치 확인).
  3단계 `vecstore.sync(['kstartup:179193'])`(Chroma 쓰기)는 사용자 승인 대기. 과거 `054314Z` 는 소급 검증하지 않는다.

### 2026-09-21 · Claude · Chroma 실제 벡터 내용 검증

- 요청·목적: [지시서](reviews/chroma/CHROMA_INTEGRITY_TASK_20260918.md)대로 DB 공고 → NPZ → Chroma 실제 벡터의 내용 정합성을 읽기 전용으로 확인하고,
  확인되지 않으면 비교 실행이 멈추게 한다.
- 작업 전 상태: `search_comparison.data_check()` 는 Chroma 의 ID·건수만 보고 `chroma_content_verified: False` 로 기록했다.
- 변경 파일:
  - `eval/chroma_integrity.py`(신규): ① DB↔NPZ 입력 해시 ② NPZ↔Chroma 벡터 **원소 단위**(ID 로 맞춤, 순서 무관)
    ③ Chroma `embed_meta`·NPZ `meta`·현재 설정 8칸 대조. 판정 `통과/불일치/확인 실패`, 종료코드 0/2/4.
    허용 오차 float32 · atol 1e-6 · rtol 0(결과 보기 전에 정함). 바이트 일치·재정규화 일치를 따로 센다.
    검사 전후 NPZ sha256·Chroma 원본 폴더 전체 파일 해시·DB 입력 해시 집합을 비교해 변경을 감지한다.
    **Chroma 원본은 열지 않고 임시 폴더 복사본을 연다** — 원본을 한 번 열었을 때 읽기만 했는데도
    `chroma.sqlite3` 수정 시각이 바뀌는 것을 확인했기 때문이다(12:13, 이 조사 중 한 번).
  - `eval/search_comparison.py`: `--check-only`(app.boot·워밍업·검색 없이 검사만), `data_check()` 에 실제 내용 검사 연결,
    `integrity_failures()` 가 `chroma_content_verified` 가 참이 아니면 사유와 함께 멈춘다.
  - `tests/test_chroma_integrity.py`(신규 27개): 순서 무관 통과, 벡터 변경·허용 오차 이내/초과, 코사인만 높은 경우,
    추가·누락·중복, 벡터 없음·차원·NaN, 길이 불일치, 메타 불일치·누락·파싱 실패, 조회 실패, 검사 중 DB 변경,
    원본 폴더 미변경(open_copy), 검사 전용 모드에서 검색·인코딩·색인 생성 미호출, 비교 실행 중단.
  - `tests/test_search_comparison.py`: 정상 픽스처에 Chroma 검사 통과 값을 넣었다(기존 날짜·중단 테스트 유지).
  - `eval/README.md`: 실행 명령 추가.
- 실행(2026-09-21, 작업 PC): `python -X utf8 eval/search_comparison.py --check-only` → 종료코드 2.
  결과 `reports/chroma_integrity_20260921T031931Z/` (첫 실행 `031731Z` 는 재정규화 분류 전 보고서로 보존).
  - ① DB↔NPZ **통과** — DB 공고 2,328건 모두 NPZ 입력 해시와 같다.
  - ③ 메타데이터 **통과** — 모델·리비전 `5617a9f6…`·입력 버전·토큰 상한·차원·dtype·정규화·바이트 순서 모두 같다.
  - ② NPZ↔Chroma **불일치 1건**: `kstartup:179193`(한전KPS 창업벤처 육성, 연장) 최대 차이 0.0193 · 코사인 0.9866.
    나머지 2,327건은 허용 이내 — 바이트 일치 1,775 · 재정규화 일치 552 · 그 외 0, 최대 차이 1.5e-8.
  - 검사 중 변경 없음. 원본 `chroma.sqlite3` 수정 시각은 검사 뒤에도 12:13:27 그대로.
- 원인 조사(읽기 전용, `investigation.md`): 179193 은 DB 상 벡터 9/14 생성·공고 9/15 수정이고,
  배치 로그 24건의 `changed_ids` 에 한 번도 없다. **Chroma 가 옛 벡터를 들고 있을 가능성이 높지만 경로는 확정하지 못했다.**
  552건은 코사인 색인의 재정규화로 설명된다(모두 NPZ/‖NPZ‖ 와 일치).
  처음 코드 주석의 "왕복은 비트까지 같아야 정상" 전제는 틀려서 고쳤다. 허용 오차는 바꾸지 않았다.
- 검증: 전체 273개 통과(건너뜀 13).
- 고치지 않은 것: 179193 의 Chroma 벡터(지시서상 색인 쓰기 금지). 고치려면 `vecstore.sync(['kstartup:179193'])` 한 건(쓰기, 승인 필요).
  EC2 에 올라간 벡터의 같은 문제 여부는 확인하지 않았다. 과거 `054314Z` 실행 당시의 정합성 증명이 아니다.
- 다음 단계: 사용자 결정(179193 재동기화 여부) → Codex 재검토.

### 2026-09-21 · Claude · F2·F3 Codex 승인 반영

- 요청·목적: [Codex F2·F3 재검토](reviews/sql_semantic/SQL_SEMANTIC_F2_F3_REVIEW_20260921.md) 결과를 화면·기록에 반영한다.
- 재검토 결과: **F2 승인, F3 승인.** 새 결함 없음. Codex 가 전체 246개 통과를 독립 실행으로 확인했고,
  실험 DB `lab_vectors` 1,852건을 SELECT 로 **전수 대조**해 메타데이터가 모두 현재와 같고 재생성 대상이 0건임을 확인했다
  (Claude 는 검색 한 건만 확인했었다).
- 변경 파일: `viewer.py`(F2·F3 `해결 · Codex 승인`, F2 설명에 캐시 경로 주의 추가),
  `web/verify.html`(맨 위 제목 `알려진 문제와 상태`, '고치지 않았다' 문구 교체, D 구역 `F2 해결`),
  `tests/test_verify_ui.py`(F1~F3 모두 승인 문구 확인), `tests/test_sql_semantic.py`(docstring 을 raw 로 바꿔
  Codex 가 지적한 invalid escape SyntaxWarning 제거 — 동작 변화 없음).
- Codex 가 남긴 운영 주의: 현재 리비전은 로컬 Hugging Face 기본 캐시의 `refs/main` 으로 찾는다. 다른 캐시 경로를 쓰는 PC 에서는
  리비전을 못 찾아 **모든 벡터가 stale 로 빠진다**(안전한 실패). 다른 PC 에서 돌리기 전에 리비전이 잡히는지 먼저 본다.
- 남긴 것: `eval/search_comparison.py` 의 미닫힌 파일 ResourceWarning 은 이번 범위 밖이라 고치지 않았다.
- 검증: 전체 246개 통과(건너뜀 13). SyntaxWarning 을 오류로 바꿔 컴파일해도 통과.
- 현재 상태: F1·F2·F3 모두 Codex 승인. 남은 한계는 Chroma 내용 미검증·사람 관련성 판정 없음.

### 2026-09-21 · Claude · F2·F3 수정 — 모델 리비전 대조와 벡터 메타데이터 갱신

- 요청·목적: 사용자 지시로 [리뷰 F2·F3](reviews/sql_semantic/SQL_SEMANTIC_REVIEW_20260918.md#남은-수정-사항)를 고친다.
- 작업 전 상태: 실제 `lab_vectors` 1,852건은 모두 모델 `BAAI/bge-m3` · 리비전 `5617a9f6…` · 1024 · float32 · 정규화로
  현재 인코더와 같다. 즉 두 문제 모두 **지금 결과를 틀리게 만들지는 않았고**, 모델이 바뀔 때 드러나는 문제다.
- 변경 파일:
  - `search.py` (F2): 저장 벡터의 `model_revision` 을 질의 인코더 리비전과 대조한다. 다르면
    `다른 모델 리비전`, 어느 쪽이든 없으면 `모델 리비전 확인 불가` 로 stale 처리하고 사유를 남긴다.
    정책: **모르면 쓰지 않는다**(입력 해시가 같다는 것만으로 호환된다고 보지 않는다).
    응답에 `encoder`(모델·리비전·계약)를 기록한다.
  - `prepare.py` (F3): 벡터 UPSERT 를 `VECTOR_SQL` 상수로 만들고 **키를 뺀 모든 칸**을 UPDATE 한다
    (예전에는 model·dim·dtype·normalized 누락). 재생성 판정을 `needs_vector()` 로 분리하고 dtype·정규화까지 본다.
    `build_vectors` 가 연결·모델을 주입받을 수 있게 했다(테스트용).
  - `tests/test_sql_semantic.py`: F2 4개(리뷰 재현 그대로·저장 리비전 없음·현재 리비전 없음·같은 리비전 통과),
    F3 3개(UPDATE 절 칸 확인·**불일치 행 재생성 → 검색 통과 → 다음 생성 건너뜀**·재생성 판정).
    F3 가짜 테이블은 실제 `VECTOR_SQL` 의 UPDATE 절에 적힌 칸만 바꾸므로 SQL 에서 칸이 빠지면 깨진다.
    `RunTests` 는 리비전을 고정해 모델 캐시 유무와 무관하게 돈다.
  - `fixtures.py`: 고정 가짜 리비전(`fixture-revision`) 사용, 다른 리비전 벡터 `fx-007` 추가.
  - `viewer.py`·`web/verify.html`·`tests/test_verify_ui.py`: F2·F3 상태 `수정함 · 재검토 대기`,
    D 구역의 '리비전 검사 안 함' 문구 교체.
- 검증(2026-09-21, 작업 PC):
  - 전체 **246개 통과(건너뜀 13) 3회 연속**. 검증 화면 35 · SQL 실험 87.
  - 실제 실험 DB 로 case01(필터 켬) 한 건을 다시 검색(SELECT 만): 인코더 리비전 `5617a9f6…`,
    stale 0 · broken 0, Top-5 가 `20260921T024014Z` 저장 결과와 같다. **리비전 검사가 멀쩡한 벡터를 빼지 않는다.**
  - 실제 DB 에서 `--embed` 는 돌리지 않았다. 1,852건 모두 현재 조건과 맞아 만들 대상이 없고, F3 는 가짜 테이블로 검증했다.
- 미검증·남은 문제: 실제로 다른 리비전 모델을 받아 재생성하는 경로는 돌려 보지 않았다(모델을 바꿀 계획이 없다).
  Codex 재검토 전이다. Chroma 내용 미검증·사람 판정 없음은 그대로다.
- 다음 단계: Codex 재검토.

### 2026-09-21 · Claude · 조건 재적재(sql_lab_v2)와 비교 재실행

- 요청·목적: Codex 가 승인한 F1 수정을 실제 검색 결과에 반영한다. 사용자와 **EC2 운영 DB 는 건드리지 않는** 방식으로 합의했다.
- 작업 전 상태: 실험 DB 의 `lab_conditions` 16,668줄과 `083852Z` 결과는 수정 전 추출(표시상 `sql_lab_v1`)이었다.
  기존 `prepare --snapshot` 은 EC2 에서 공고를 다시 읽어 9/18 이후 공고가 섞이므로 쓰지 않았다.
- 변경 파일:
  - `conditions.py`: `EXTRACTOR` 를 `sql_lab_v2` 로 올렸다(버전 이력 주석).
  - `prepare.py`: `--reextract` 추가. 이 PC 실험 DB 의 `lab_notices` 에서 조건만 다시 뽑는다.
    소스 연결을 열지 않고, 덮어쓰기 전에 `lab_conditions_bak_<시각>` 으로 복사하며 줄 수가 다르면 멈춘다.
    조건 UPSERT SQL 을 `COND_SQL` 상수로 올려 스냅샷 적재와 공유한다.
  - `tests/test_sql_semantic.py`: 재추출 3개(소스 미접속·백업 선행·백업 부족 시 중단).
  - `viewer.py`: 저장 실행 목록에 추출기 버전 표시, F1 설명에 재실행 결과 반영. `tests/test_verify_ui.py` +1.
- 실행(2026-09-21, 작업 PC, 이 PC 의 `notice_match_sql_lab` 만 사용):
  1. `prepare --reextract` → 백업 `lab_conditions_bak_20260921113943`(16,668줄, 전부 `sql_lab_v1`),
     재추출 1,852건 · 16,668줄 전부 `sql_lab_v2`. `lab_runs` 에 kind=`reextract` 기록.
     `lab_notices` 1,852건·`lab_vectors` 1,852건은 그대로(벡터 마지막 생성 2026-09-18 17:37).
  2. `compare --as-of 2026-09-18` → `reports/sql_semantic_20260921T024014Z/`. 기존과 같은 10입력·기준일·모델 리비전.
- 결과 — **두 실행이 사실상 같다.** 20응답 모두 Top-5 순서 동일, 후보 수(SQL·조건·비교·반환) 동일,
  같은 공고의 유사도 동일, Top-5 공고의 조건 판정 문구 변화 0건.
  원인: 10개 사례의 신청자 입력에 **기업 규모·업종이 없다**(`compare.applicant_from` 은 지역·설립일·예비창업만 넘긴다).
  그래서 규모·업종 판정은 새 결과에서도 50칸 모두 `확인 필요 · 신청자 미입력`이다. 업종 no_limit 1건은 Top-5 에 없었다.
  즉 F1 수정은 **이 10개 비교의 결과를 바꾸지 않는다.** 수정 전 오해석이 이 결과에 끼친 영향도 없었다는 뜻이다
  (2026-09-18 Codex 리뷰가 "이번 저장 결과에서 실제 발생했다고 주장하지 않는다"고 한 것과 일치한다).
  바뀐 것은 DB 의 조건 값이다 — 규모 known 1,608 → 1,556, unknown 244 → 296, 업종 no_limit 0 → 1.
- 검증: 전체 237개 통과(건너뜀 13) 3회 연속. 검증 화면 33 · SQL 실험 80.
- 미검증·남은 문제: F1 수정의 효과를 결과로 보려면 **기업 규모·업종을 적은 신청자 사례**가 필요하다.
  기존 입력에 없는 정보를 임의로 지어 넣지 않았다. F2·F3 미해결. 사람 판정 없음.
- 되돌리는 법: `lab_conditions` 를 비우고 `lab_conditions_bak_20260921113943` 에서 복사하면 v1 로 돌아간다.
- 다음 단계: 규모·업종 입력이 있는 사례를 추가할지 결정, 또는 F2·F3.

### 2026-09-21 · Claude · F1 Codex 승인 반영

- 요청·목적: [Codex F1 재검토](reviews/sql_semantic/SQL_SEMANTIC_F1_REVIEW_20260921.md#2차-수정-재검토-결과-2026-09-21) 결과를 화면·기록에 반영한다.
- 재검토 결과: **F1 승인.** 교차 필드 반례 4건과 표현 변형, 실제 1,852건 수치(54건 변경·업종 no_limit 1건),
  전체 233개 통과를 Codex 가 독립 실행으로 확인했다. 새 F1 결함 없음.
- 변경 파일: `experiments/sql_semantic/viewer.py`(F1 상태 `해결 · Codex 승인`),
  `tests/test_verify_ui.py`(승인 문구와 '저장 결과는 수정 전 추출' 한계 문구를 확인).
- 의견 차이 기록: `kstartup:179038`('산업군 무관')을 Claude 는 모집 트랙 설명이라 애매하다고 봤고,
  Codex 는 필드 문맥이 명확하다고 봤다. 둘 다 사람 정답 판정은 아니다.
- 검증: 전체 233개 통과(건너뜀 13).
- 남은 것: 저장된 `lab_conditions`·`083852Z` 결과는 수정 전 추출이다. 검색 결과에 반영됐다고 말하려면
  조건 재추출·재적재와 비교 재실행이 필요하다(Codex 도 데이터 갱신 절차로 분류). F2·F3 미해결.

### 2026-09-21 · Claude · F1 2차 수정 — 다른 조건의 '제한 없음'이 새던 문제

- 요청·목적: [Codex F1 리뷰](reviews/sql_semantic/SQL_SEMANTIC_F1_REVIEW_20260921.md) P1 을 고친다.
- 작업 전 상태: 1차 수정의 `_says_no_limit` 이 지원대상 전체에서 '제한 없'·'무관'·'누구나'·'모든 기업'을
  찾아 **규모와 업종 모두**에 적용했다. "지역 제한 없음", "업력 무관", "연령제한 없음" 이
  규모·업종의 제한 없음이 되어 "업종 제한 없이 중소기업만" 공고에서 **대기업 신청자가 충족**이 됐다.
  1차 보고의 `업종 unknown→no_limit 28건`은 개선이 아니라 대부분 이 오류였다. **1차 보고를 정정한다.**
  리뷰 재현 4건을 모두 직접 재현했다.
- 변경 파일:
  - `experiments/sql_semantic/conditions.py`: 필드별 정규식으로 바꿨다. '제한 없음' 표현 **바로 앞에
    그 필드 이름**이 있어야 인정한다 — 규모는 `기업 규모/기업 형태`, 업종은 `업종/업태/산업군/산업 분야`
    또는 `전 업종`. '누구나'·'모든 기업'처럼 어느 조건인지 모르는 말은 쓰지 않는다(→ unknown).
    맨 '규모'는 '지원 규모'(금액)와 겹쳐 뺐다. 같은 필드에 '제한 없음'과 명시 제한이 함께 있으면 unknown.
    근거에는 전체 문장 대신 **실제로 걸린 문구**를 남긴다.
  - `tests/test_sql_semantic.py`: 리뷰 최소 재현 4건 + 실제 공고 표현(지역·연령 제한 없음, 누구나 등)
    + 같은 필드 충돌 = 6개 추가. 두 건은 판정(`judge_list`)까지 불충족인지 확인한다.
  - `fixtures.py`: 교차 필드 반례 2건 추가(지역 제한 없음 → 업종 제한 없음 아님, 업종 제한 없음 → 규모 유지).
  - `viewer.py`: F1 상태를 `수정함 · 재검토 대기`로 고치고, 1차 수정의 누수와 저장 결과가 옛 판정이라는
    점을 적었다. `tests/test_verify_ui.py` 는 이 문구를 확인한다.
  - `reports/verify_ui/f1_impact_20260921.json`: 다시 쟀다. `no_limit` 사례 전체 목록도 넣었다.
- 검증(2026-09-21, 작업 PC):
  - 전체 **233개 통과(건너뜀 13) 3회 연속**. 검증 화면 32 · SQL 실험 77.
  - 리뷰 재현: "업종 제한 없이 중소기업만" → 규모 중소기업, **대기업 신청자 불충족**.
    "기업 규모 제한 없이 제조업만" → 업종 제조업, **서비스업 신청자 불충족**.
    "업력 무관, 제조업·중소기업만" → 둘 다 known. "규모 제한 없음 + 제조업 제외" → 업종 unknown.
  - 실제 1,852건 재측정(SELECT 만): 바뀐 건 **107 → 54건**.
    업종 no_limit **28 → 1건**, 규모 no_limit **28 → 0건**. 규모 known→unknown 52건의 이유는
    지원대상에 규모 단어가 없고 제목·분류에만 있던 29건, 다른 칸이 다른 규모를 말한 19건,
    제외·거래상대 문장 4건. 목록이 좁아진 1건(`kstartup:177864`)은 "※ 대기업 제외" 때문이다.
  - 남은 업종 no_limit 1건(`kstartup:179038`)을 원문으로 확인했다. "Vertical AI Agent (산업군 무관)" 은
    **모집 트랙의 설명**이라 신청 기업의 업종 제한이 없다는 뜻인지 애매하다. 사람 판단이 필요하다.
- 미검증·남은 문제: 사람 자격 판정 정답이 없어 54건이 모두 맞는지는 확정하지 못했다. 위 1건은 경계 사례다.
  저장된 `lab_conditions`와 `083852Z` 결과는 여전히 수정 전 값이다(재적재·재실행 안 함).
  F2·F3 미해결. 단어 목록 기반 한계는 그대로다.
- 다음 단계: Codex 재검토 → 통과하면 조건 재적재·재실행 여부 결정 → F2·F3.

### 2026-09-21 · Claude · F1 수정 — 자격 문구 오해석 (규모·업종)

- 요청·목적: 사용자 지시로 [리뷰 F1](reviews/sql_semantic/SQL_SEMANTIC_REVIEW_20260918.md#남은-수정-사항)을 고친다.
  F2·F3 는 이번 범위가 아니며 화면에서 계속 `미해결` 이다.
- 작업 전 상태: 제목·사업 분류까지 뒤져 규모/업종 단어가 보이면 제한으로 단정했다.
  "규모 제한 없이 모든 기업" → 대기업 전용, "제조업은 제외" → 제조업만 가능으로 뒤집혔다.
  둘 다 **신청할 수 있는 사람을 떨어뜨리는** 방향의 오류였다.
- 변경 파일:
  - `experiments/sql_semantic/conditions.py`: 지원대상 칸(`target_text`·`target_category`)만 읽는다.
    문장을 잘라 ① 제외·부정 문장의 단어는 허용 목록에 넣지 않고 ② 거래 상대를 말하는 문장
    (계약·판로·수요·납품 등)의 규모도 자격으로 보지 않으며 ③ "제한 없음"은 `no_limit` 으로 구분한다.
    추가로 **지원대상 목록을 좁게 믿지 않는다** — 제목 등 다른 칸이 다른 규모를 말하면 목록이
    전부라고 단정하지 않고 `unknown`(확인 필요)으로 남긴다.
  - `experiments/sql_semantic/search.py`: `judge_list` 가 `no_limit` 을 **충족**으로 본다(지역과 같은 처리).
    신청자 값을 몰라도 공고가 제한 없다고 밝혔으면 확인 필요로 미루지 않는다.
  - `tests/test_sql_semantic.py`: `F1RegressionTests` 9개 추가(가상 반례 + 실제 공고 반례 2건).
  - `experiments/sql_semantic/fixtures.py`·`viewer.py`·`web/verify.html`·`tests/test_verify_ui.py`:
    반례 기대값을 `기대대로` 로 바꾸고 화면의 F1 상태를 `수정함(2026-09-21)` 으로 고쳤다.
    검사는 지우지 않았다 — 같은 오해석이 다시 들어오면 B 구역이 바로 빨개진다.
  - `reports/verify_ui/f1_impact_20260921.json`(신규), `reports/verify_ui/test_result.json` 갱신.
- 전후 차이·선택 이유: 애매하면 `unknown` 으로 남긴다. 남기면 '확인 필요'가 되어 후보로 살아 있고
  사람이 확인하면 된다. 잘못 탈락시키는 것보다 낫다는 판단이다. 확보율은 일부러 낮아진다.
- 검증(2026-09-21, 작업 PC):
  - 전체 테스트 **227개 통과(건너뜀 13)를 3회 연속** 확인. 검증 화면 32 · SQL 실험 71.
  - **실제 공고 1,852건에 새 추출기를 돌려 저장값과 대조**(실험 DB 는 SELECT 만, 저장값 변경 없음):
    바뀐 건 **107건**. 규모 known→확인 필요 50, 업종 확인 불가→제한 없음 28,
    규모 known→제한 없음 14, 규모 확인 불가→제한 없음 14, 규모 목록 좁아짐 1.
    허용 목록이 좁아진 1건(`kstartup:177864`)은 공고에 "※ 대기업 제외"가 있어 맞는 좁힘이다.
    새 분포: 규모 known 1,544 · no_limit 28 · unknown 280 / 업종 no_limit 28 · unknown 1,824.
    결과는 `reports/verify_ui/f1_impact_20260921.json`.
  - 수정 과정에서 **새 오류 2건을 스스로 찾아 고쳤다.** ① 지원대상만 좁게 믿어 목록이 줄면
    소상공인 같은 신청자를 떨어뜨림(실제 공고 `bizinfo:PBLN_000000000117096`).
    ② "대기업과 계약 실적" 의 대기업을 신청 자격으로 읽음(`kstartup:179258`). 둘 다 회귀 테스트로 남겼다.
  - 화면 확인: `/api/conditions/cases` 의 `reproduced` 가 빈 목록, B 구역 4건 모두 `기대대로`.
- 미검증·남은 문제: **저장된 검색 결과(`sql_semantic_20260918T083852Z`)는 수정 전 추출로 만든 것이다.**
  화면의 저장 실행 숫자는 옛 판정이며, 새 추출로 다시 돌리지 않았다(벡터 재생성은 필요 없지만
  조건 적재와 재실행이 필요하다). F2·F3 는 그대로 미해결. 업종은 여전히 known 0건이다.
  단어 목록 기반이라는 한계도 그대로다 — 목록에 없는 표현은 여전히 못 읽는다.
- 다음 단계: 조건 재적재 + 비교 재실행 여부를 정한다. 이후 F2·F3 수정. Codex 재검토.

### 2026-09-21 · Claude · 검증 화면 리뷰 2건 반영 (flaky 테스트·SQL 단계 제외 분리)

- 요청·목적: [Codex 리뷰](reviews/ui/VERIFY_UI_REVIEW_20260921.md)의 P1·P2를 수정한다.
- 작업 전 상태: 이전 기록의 **`210개 통과`는 틀렸다.** 전체 테스트를 반복 실행하면
  `FixtureTests.test_same_every_time` 이 실행마다 통과·실패가 갈렸다(3회 중 2회 실패 재현).
  한 번 통과한 결과만 보고 `reports/verify_ui/test_result.json` 에 적은 것이 원인이다.
- 변경 파일:
  - `tests/test_verify_ui.py`: 결정성 비교에서 `timing_ms` 만 제외한다. 나머지(결과 ID·순위·유사도·
    조건 판정·탈락 사유·벡터 상태)는 그대로 비교하며, 시간이 응답에서 사라지지 않았는지도 따로 확인한다.
    SQL 단계 제외 계산의 회귀 테스트 5개 추가.
  - `experiments/sql_semantic/viewer.py`: `drop_split(response, baseline_response)` 로 바꿔
    `total_candidates · sql_dropped · dropped_by_conditions · dropped_by_vector` 를 나눠 계산한다.
    기준이 없거나 더 작으면 음수를 만들지 않고 `None` 과 이유를 돌려준다.
  - `web/verify.html`: `전체 후보 → SQL 제외 → SQL 통과 → 조건 제외 → 조건 통과 → 벡터 제외 →
    유사도 비교 → 반환` 표로 표시한다. 계산할 수 없는 칸은 `계산 안 함`과 이유를 적는다.
  - `docs/guides/VERIFY_UI.md`, `reports/verify_ui/test_result.json` 갱신.
- 전후 차이·선택 이유: 실패한 테스트를 지우거나 검증을 약하게 하지 않았다. 비결정적인 것은
  실행 시간뿐이므로 그 칸만 비교에서 뺐다. SQL 제외 수는 사람이 두 칸을 빼서 구해야 했는데
  화면이 직접 계산해 보여 준다.
- 검증(2026-09-21, 작업 PC):
  - `.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_*.py"` →
    **216개 통과(건너뜀 13)를 5회 연속** 확인. 수정 전에는 같은 명령에서 3회 중 2회 실패했다.
  - 저장 실행 case01 의 단계별 수치를 API 와 브라우저에서 확인:
    전체 1,852 → SQL 제외 **1,033** → SQL 통과 819 → 조건 제외 25 → 조건 통과 794 →
    벡터 제외 0 → 비교 794 → 반환 5. 리뷰가 계산한 1,033과 같다.
  - 필터 끔을 자기 자신과 비교하면 SQL 제외 0, 기준 없음·기준이 더 작은 입력은 `계산 안 함`으로 나온다.
- 미검증·남은 문제: **F1·F2·F3 는 그대로 미해결이다**(이번에도 표시만 했다). SQL 단계의 조건별
  (마감/지역) 제외 사유는 저장돼 있지 않아 총건수만 보여 준다. 실험 DB 에서 근거 문장을 읽는 경로는
  이번에도 화면에서 실행해 보지 않았다. Chroma 내용 미검증·사람 판정 없음도 그대로다.
- 다음 단계: Codex 재검토 → F1~F3 수정과 회귀 확인.

### 2026-09-21 · Claude · 사람이 눈으로 확인하는 검증 화면 추가

- 요청·목적: [지시서](reviews/ui/CLAUDE_UI_VERIFICATION_TASK_20260921.md)에 따라 실행 상태·정형 조건 판정·
  검색 결과·벡터 상태를 로컬 브라우저에서 직접 확인할 수 있게 한다.
  사용자 선택으로 **F1~F3 수정은 이번에 하지 않고 화면에 `미해결`로 표시**한다.
  화면 데이터는 **저장된 결과 + fixture** 로 한다(실제 DB·모델 재실행 없음).
- 작업 전 상태: 실험 결과는 `reports/sql_semantic_20260918T083852Z/` 의 JSONL·manifest 와
  생성된 `comparison.html` 로만 볼 수 있었다. 조건 불충족·벡터 손상·후보 0건 같은 상태는
  실제 10개 입력에서 한 번도 나오지 않아 눈으로 확인할 방법이 없었다.
- 변경 파일:
  - `experiments/sql_semantic/fixtures.py`(신규): 가짜 공고·가짜 연결·고정 벡터.
    **조건 추출과 `search.run` 은 진짜 코드를 그대로 부른다.** 문제를 감추지 않기 위해서다.
  - `experiments/sql_semantic/viewer.py`(신규): 읽기 전용 FastAPI 앱(기본 127.0.0.1:8010).
    저장 결과 폴더·fixture 목록, 실행 상태, 사례별 필터 켬/끔 비교, 벡터 상태, 조건 반례,
    실험 DB 에서 근거 문장만 SELECT 로 읽는 경로.
  - `web/verify.html`(신규): 화면. 외부 스크립트·글꼴을 받아오지 않고 데이터를 밖으로 보내지 않는다.
  - `tests/test_verify_ui.py`(신규 25개), `docs/guides/VERIFY_UI.md`(신규 실행·확인 절차),
    `experiments/sql_semantic/README.md`(뷰어 안내), `reports/verify_ui/test_result.json`(테스트 요약).
- 전후 차이·선택 이유: 기존 서비스(`search/app.py`, 8000)와 **다른 앱·다른 포트**로 분리해
  운영 검색 결과와 섞이지 않게 했다. 기존 실험 코드·저장 결과·Chroma·NPZ 는 읽기만 했다.
  fixture 를 따로 둔 이유는 실제 10개 입력에 없는 상태(불충족·손상 벡터·후보 0건·신청자 정보 없음)를
  사람이 봐야 하기 때문이다. fixture 화면에는 `DEMO/FIXTURE — 실제 검색 결과 아님`을 띄운다.
- 검증(2026-09-21, 작업 PC):
  - `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p "test_*.py"` →
    **210개 통과(건너뜀 13)**. 이 중 검증 화면 25개. 실제 DB·모델은 부르지 않았다.
  - 브라우저에서 직접 확인: 저장 실행(`sql_semantic_20260918T083852Z`)의 A~D 구역,
    case01 의 필터 켬/끔 순위 이동(공통 2건 ▲2·▲3, 켬 전용 3건, 끔 전용 3건),
    fixture 의 벡터 없음/손상/낡음 개별 사유, `fx-case03` 후보 0건 화면, F1 반례 2건이
    `문제 재현됨`으로 표시되는 것까지 화면에서 봤다.
  - 조건 반례 결과: 규모 `제한 없이 모든 기업` → **대기업으로 읽음**,
    `제조업 제외` → **제조업만 가능으로 뒤집힘**. 두 건 모두 F1 이 살아 있음을 화면에서 재현했다.
- 미검증·남은 문제: **F1·F2·F3 는 고치지 않았다(표시만 함).** 반례에서 재현된다는 것과
  실제 공고 1,852건에서 몇 건이 그런지는 세지 않았다. Chroma 실제 벡터 내용 미검증,
  사람 관련성 판정 없음은 그대로다. 근거 문장은 저장 결과에 없어 실험 DB 가 있을 때만 읽히며,
  이번에 실험 DB 로 근거를 읽는 경로는 **화면에서 실행해 보지 않았다**(설정 없을 때의 안내만 테스트로 확인).
  화면 캡처 파일은 저장하지 않았고 확인한 화면 목록만 남겼다.
- 다음 단계: F1~F3 수정과 회귀 테스트(수정 후 B 구역 반례가 `기대대로`로 바뀌는지 같은 화면에서 확인),
  저장 결과의 조건별 제외 전수 집계, 사람 판정(B) 진행.

### 2026-09-18 · Codex · SQL 실험 후속 리뷰 — 083852Z 검증·남은 3건

- 요청·목적: Claude가 수정 후 작성한 코드·작업 기록·비교 산출물을 확인한다.
- 작업 전 상태: Claude는 리뷰 5건 수정·벡터 1,852건 생성 완료·토큰 메타데이터 보정·비교 실행을 보고했다.
  STATUS에는 이전 실행 대기 상태가 남아 있어 최신 WORKLOG/저장 결과와 구분해 갱신했다.
- 변경 파일: `docs/reviews/sql_semantic/SQL_SEMANTIC_REVIEW_20260918.md` 후속 확인 1 추가, STATUS, 이 WORKLOG.
  구현·테스트·기존 보고서·DB·벡터에는 쓰지 않았다.
- 판단: 최초 3번 혼합 차원과 4번 시작일 수정 확인, 5번 잘림 계산/보정 코드 확인.
  1번 자격 추출·2번 벡터 호환 검사는 부분 해결. 남은 P2 3건은 F1 자격/제외 문구의 허용 목록 오변환,
  F2 검색의 모델 리비전 미검사, F3 재생성 UPSERT의 model/dim/dtype/normalized 갱신 누락이다.
- 검증: 번들 Python + 프로젝트 site-packages로 `python -B -X utf8 -m unittest discover -s tests -p test_sql_semantic.py`
  → **61개 통과**. 제목의 대기업 언급으로 중소기업 탈락, 제조업 제외 문구의 반대 판정,
  낡은 리비전 통과를 가상 입력으로 재현했다. 가짜 연결/인코더로 재생성 UPDATE 절을 확인했고,
  가짜 tokenizer의 512/513 토큰 경계도 확인했다. 실제 DB나 모델은 실행하지 않았다.
- 저장 결과: `sql_semantic_20260918T083852Z` 입력은 기존 054314Z와 바이트 일치, manifest 코드 해시는 현재 코드와 일치.
  10입력/20응답·각 5건·날짜·순위·중복·후보 수 관계 확인. 필터 끔 후보 18,520 → 켬 SQL 후보 15,255 →
  Python 통과 14,618. SQL 단계 차이 3,265와 Python 제외 637을 구분했다(사례별 합계).
  Top-5 순서 동일 7/10, 나머지 case01~03의 공통 공고 2/3/1건. 누락/낡음/손상 카운터 모두 0.
  필터 켬 50칸에서 업종·규모 각각 50칸, 업력 45칸 확인 필요. 이번 결과가 업종·규모 필터 성능을 검증하지는 않는다.
- 미검증: 라이브 DB 현재 상태·전체 185개 테스트·실제 잘림 2건은 이번에 재측정하지 않았다.
  사람 판정 없음. 비교 HTML 보완·SQL 조건별 제외 집계·스냅샷 식별 근거도 남아 있다.
- 다음 단계: F1~F3와 최소 회귀 사례 수정 후 결과물 보완. 새 방식 우위 결론은 보류한다.
  Git 스테이징·커밋·push는 하지 않았다.

### 2026-09-18 · Claude · 실험 리뷰 5건 수정 + 전량 적재·비교 실행

- 요청·목적: Codex 리뷰 [SQL_SEMANTIC_REVIEW_20260918.md](reviews/sql_semantic/SQL_SEMANTIC_REVIEW_20260918.md) 의 P2 5건을
  고치고, 전량 임베딩을 마친 뒤 필터 켬/끔 비교까지 실행한다. 사용자 지시로 진행 중이던 벡터 생성은 두고(A안)
  메타데이터는 재임베딩 없이 보정했다.
- **이전 기록 정정**: 2026-09-18 Claude '정형 필터 + 의미 검색 실험 구현' 항목에서
  "업종·규모도 선호라 SQL 에서 거르지 않는다" 고 적은 것은 **지시서 해석 오류**다.
  지시서 5절이 선호로 분류한 것은 지원 내용·희망 금액·희망 지원 방식이며 업종·규모는 자격이다.
  같은 항목의 "industry 100%" 도 틀렸다 — 그 값은 지원 분야(`category/subcategory`)였다.
- 변경 파일:
  - `conditions.py`: `purpose`(지원 분야) 필드 신설, `industry` 는 지원대상 문구에 업종 제한이
    명시된 경우만 known. 단어가 스쳐 나온 것은 제한으로 보지 않는다.
  - `search.py`: 업종·기업 규모 3값 판정 추가(명시적 불일치만 제외, 미입력·미확인은 확인 필요),
    접수 시작 전 공고를 `ok` 대신 `check 접수 시작 예정` 으로, 저장 벡터의 **입력 해시·계약·모델**을
    다시 계산해 대조하고 불일치는 `stale_vector` 로 제외, 차원·dtype 을 **후보별로** 검사해
    한 건이 이상해도 검색 전체가 죽지 않게 함. CLI 에 `--industry`·`--company-size` 추가.
  - `embedding.py`: `token_info()` — 실제 토크나이저로 토큰 수·상한 초과 여부 계산.
  - `prepare.py`: 벡터 저장 시 토큰 수·잘림 기록, 재사용 조건에 모델·리비전·차원 포함,
    기존 행 보정용 `--fix-token-meta`(재임베딩 없음), 스키마 적용 멱등화.
  - `tests/test_sql_semantic.py`: 42 → **61개**(리뷰 5건 회귀 포함).
- 검증(2026-09-18, 작업 PC · 로컬 MySQL `notice_match_sql_lab`):
  - 전체 테스트 **185개 통과**(건너뜀 13).
  - 전량 임베딩 완료: 벡터 1,852건(생성 1,802 + 시험 50). 공고 1,852건 중 **벡터 없음 0**.
  - 토큰 보정 1,852건: 토큰 최소 52 · 최대 618 · 평균 191, **상한(512) 초과 2건**.
  - 정합성 검사: 차원/자료형 이상 0 · 입력 해시 불일치 0 · 다른 모델 0.
  - 조건 재추출 후 확보율: region 100% · purpose 100% · target 100% · application_period 96.8% ·
    company_size 86.8% · support_type 52.5% · support_amount 19.3% · business_age 13.6% ·
    **industry 0%**(엄격한 규칙 적용 결과. 이전 100% 는 지원 분야였다).
  - 필터 켬/끔 비교 실행 → `reports/sql_semantic_20260918T083852Z/`.
    10사례 합계 SQL 후보 15,255 → 조건 통과 14,618(조건 제외 637). 필터 끔은 18,520 전부 후보.
    상위 5가 완전히 같은 사례 7/10. 소재지를 넣은 3사례(case01~03)에서만 상위 5가 달라졌다.
    낡음·손상·벡터 없음 0건.
- 미검증·남은 문제: **사람 판정 없음** — 어느 방식이 낫다고 말하지 않는다.
  업종 확보율 0% 라 업종 자격 판정은 사실상 항상 '확인 필요' 다. business_age 13.6% 도 마찬가지다.
  SQL 제외 건수(지역·마감)와 Python 조건 제외(637)는 아직 응답에서 분리해 세지 않았다(Codex 인계 3번).
  비교 HTML 에 공고 ID·원문 링크·공통/전용·순위 이동 보완이 남았다(인계 4번).
  기존 dense/hybrid 열은 계속 참고용이다(공고 집합·계약·기준일 다름, Chroma 내용 미검증).
- 다음 단계: 인계 3·4번(집계 분리·HTML 보완) 후 Codex 재검토.

### 2026-09-18 · Codex · SQL 의미 검색 실험 리뷰 — 수정 필요 5건

- 요청·목적: 사용자가 전달한 Claude 구현 보고에 따라 새 실험 코드·테스트·작업 기록을 지시서와 대조했다.
- 작업 전 상태: 아래 Claude ‘실제 실행은 대기’ 기록보다 최신 사용자 보고는 로컬 1,852건 적재·50건 임베딩 시험·
  실제 검색 성공·전량 임베딩 진행 중이다. 해당 실행 수치는 전달받은 값이며 Codex가 실제 DB에서 재측정하지 않았다.
- 변경 파일: `docs/reviews/sql_semantic/SQL_SEMANTIC_REVIEW_20260918.md` 신규 작성, `docs/STATUS.md` 최신 인계, 이 작업 이력.
  구현·테스트·기존 보고서는 수정하지 않았다.
- 확인 사항: 업종에 지원 분야를 저장하고 업종·규모 자격 판정이 빠져 있음, 저장 벡터의 현재 입력 해시 미검사,
  모델과 다른 차원에서 전체 검색 실패, 미래 접수 시작일 미판정, truncated=0 상수 저장. 각각 근거·재현·수정 기준을 리뷰에 기록했다.
  아래 Claude 기록의 ‘업종·규모도 선호’는 지시서 해석 오류이며, industry 100%는 실제 업종 자격 확보율이 아니다.
- 검증: 번들 Python 3.12 + 프로젝트 site-packages로
  `python -B -X utf8 -m unittest discover -s tests -p test_sql_semantic.py` → **42개 통과**.
  기존 FakeConnection과 가짜 벡터로 업종 오변환·규모 불일치 통과·시작 전 ok·임의 해시 허용·혼합 차원 예외의 추가 5개 사례를 확인했다.
  BIGINT·DDL 중복 오류 처리·JOIN 계약 파라미터 순서 수정은 코드에서 확인했다.
- 미검증·남은 문제: 실제 MySQL SQL/DDL 의미·전량 생성 완료·실데이터 벡터 정합성·검색 품질은 미검증.
  전체 166개 통과는 Claude 보고이며 이번에 재실행하지 않았다. 비교 HTML의 원문 링크/ID·순위 대조와
  SQL 단계 제외 집계·스냅샷 식별 근거도 결과 생성 때 보완하도록 남겼다.
- 다음 단계: Claude가 수정 5건·회귀 검증 후 생성 완료와 벡터 무결성을 확인하고 필터 켬/끔 결과를 만든다.
  기존 dense/hybrid는 참고용으로 유지하며 사람 판정 전 우위를 주장하지 않는다.
- 진행 중 생성·DB·Chroma·NPZ에 개입하지 않았고 Git 스테이징·커밋·push를 하지 않았다.

### 2026-09-18 · Claude · 정형 필터 + 의미 검색 실험 구현 (실제 실행은 대기)

- 요청·목적: [지시서](reviews/sql_semantic/SQL_SEMANTIC_EXPERIMENT_TASK_20260918.md) 대로 기존 구현·DB·결과를 보존한 채
  별도 로컬 MySQL 에서 `정형 필터(SQL) → 후보 벡터 직접 비교 → 규칙 정렬 → Top N` 경로를 만든다.
- 작업 전 상태: 기존 서비스는 dense+BM25 하이브리드. 실험용 로컬 DB·코드·스키마는 없었다.
  사용자 선택으로 **로컬 MySQL 계정 없이 코드·가상 테스트까지 먼저** 진행했다.
- 변경 파일(모두 신규):
  - `experiments/sql_semantic/config.py` — 실험 DB 설정 분리. `SQL_LAB_*` 가 없으면 **소스로 대체하지 않고 중단**,
    비로컬 호스트·소스와 같은 DB 이름 거부, 비밀번호는 기록·출력하지 않음.
  - `experiments/sql_semantic/schema.sql` — `lab_notices`(스냅샷·내용 해시) · `lab_conditions`(값+상태+근거) ·
    `lab_vectors`(벡터 바이트·dtype·차원·정규화·입력 해시) · `lab_runs`.
  - `experiments/sql_semantic/conditions.py` — 원문 → 정형 조건. `known / no_limit / unknown` 세 값으로
    **값 없음과 제한 없음을 구분**. 업력 해석은 서비스 `search/gate.py` 를 재사용.
  - `experiments/sql_semantic/embedding.py` — 새 입력 계약(제목 → 지원 분야 → 지원 내용 → 신청 자격),
    출처·대체 규칙 기록, 벡터 pack/unpack 검사(차원·NaN), 코사인.
  - `experiments/sql_semantic/search.py` — SQL 필터(확실한 불일치만) → 후보 **전체** 코사인 → 고정 규칙 정렬.
    조건별 `충족/불충족/확인 필요`와 사유, 벡터 없음·손상 건수를 응답에 담는다. `--no-filter` 대조군 제공.
  - `experiments/sql_semantic/prepare.py`(스냅샷·정형화·임베딩), `compare.py`(기존 결과와 비교표), `README.md`.
  - `tests/test_sql_semantic.py`(신규 40개).
- 전후 차이·선택 이유: 기존 `search/`·`shared/`·배치·공용 스키마는 **한 줄도 바꾸지 않았다**(git status 로 확인).
  업종·규모·지원 방식을 SQL 에서 거르지 않은 이유는 지시서 5절대로 자격이 아니라 선호이기 때문이다.
  업력은 경계(미만/이하)와 예비창업자 처리가 얽혀 SQL 에서 값만 가져오고 파이썬에서 3값으로 판정했다.
- 검증(2026-09-18, 작업 PC · 프로젝트 `.venv`):
  - `python -m unittest discover -s tests -k test_sql_semantic`: **40개 통과**. 전체 **164개 통과**(건너뜀 13).
    포함 항목: 설정 누락 시 소스 대체 거부·비로컬/동일 DB 거부·비밀번호 미노출, 전국/복수/미확인 지역,
    업력 경계(83개월 통과·84개월 탈락)·예비창업자 전용·설립일 미상, 마감 경계·상시·미확인,
    후보 0개·N개 미만, SQL 파라미터 사용(문자열 조립 아님), 벡터 왕복·차원 오류·NaN·코사인·동점 정렬,
    실행 중 SELECT 외 문장을 보내지 않음.
  - 설정 없이 `prepare.py --schema` 실행 → 종료코드 2, 소스 DB 로 대체하지 않고 필요한 `.env` 키를 안내.
  - 소스 DB **읽기 전용**으로 접수 중 공고 1,852건의 정형 조건 확보율 측정:
    region 100%(known 1,222 · 전국 630) · industry 100% · target 100% · application_period 97% ·
    company_size 87% · support_type 52% · support_amount 19% · **business_age 14%**(known 251 · unknown 1,601).
  - 금액 규칙 첫 시험에서 "기업당 최대 5,000만원 … 총사업비 30억원" 을 총액으로 오인해 버리는 버그를 발견,
    총액 표현을 **앞쪽 문맥만** 보도록 고치고 네 가지 문장으로 재확인했다.
- 미검증·남은 문제: **실제 로컬 MySQL 실행을 하지 못했다**(`.env` 에 `SQL_LAB_*` 없음).
  따라서 스키마 적용·스냅샷 적재·벡터 생성·검색·비교표는 **아직 한 번도 실제로 돌지 않았다.**
  테스트는 가짜 연결·가짜 모델 기반이라 실제 SQL 의미(FIND_IN_SET·LEFT JOIN 조합)는 검증되지 않았다.
  업력 확보율이 14%라 정형 필터의 업력 조건은 대부분 '확인 필요'로 남을 것으로 보인다(실행 후 확인 필요).
  환경 준비: 로컬 MySQL 8.0 이 127.0.0.1:3306 에서 실행 중이고 BGE-M3 캐시는 있다. 계정만 있으면 된다.
- 다음 단계: 사용자가 `.env` 에 `SQL_LAB_*` 5줄을 추가하면 README 순서대로 실행한다.
  벡터 생성은 접수 중 1,852건 기준 CPU 로 약 1.5시간 예상(추정). 실행 후 `reports/sql_semantic_<시각>/` 생성.

### 2026-09-18 · Codex · 새 로컬 검색 실험 지시서 작성

- 요청·목적: 사용자가 기존 것을 비교용으로 보존하고 별도 로컬 DB에서 새로운 검색 형식을 Claude에게 구현시키도록 요청했다.
- 작업 전 상태: 기존 A–E 작업은 중지된 상태이며 팀의 SQL 선필터→임베딩→규칙→Top N 제안을 검토했다.
  현재 데이터/벡터 BLOB 규약·연결 설정·검색 흐름을 읽어 지시서에 반영했다.
- 변경 파일: `docs/reviews/sql_semantic/SQL_SEMANTIC_EXPERIMENT_TASK_20260918.md` 신규, STATUS·WORKLOG.
  기존 코드·DB·색인·실험 결과·사람 판정 파일은 수정하지 않았다.
- 전후 차이·선택 이유: 검토 단계에서 Claude가 실행할 수 있는 별도 실험 범위로 구체화했다.
  신규 로컬 MySQL과 `experiments/sql_semantic/` 격리, 소스 읽기 전용/대상 쓰기 구분,
  조건별 원문 근거와 unknown 보존, 새 임베딩 계약·DB 저장·직접 코사인 비교,
  설명 가능한 규칙 및 SQL 필터 켬/끔 대조·과거 결과의 비교 가능성 구분을 명시했다.
  새 임베딩 생성과 신규 검색 실행은 포함하되 기존 경로 변경·BM25 추가·검색엔진 전환은 제외했다.
- 검증: 공통 규칙·최근 검토·현행 스키마/설정/임베딩 규약과 대조하고 문서 로컬 링크·공백 오류를 확인했다.
  문서 작업이므로 모델·DB·검색·테스트는 실행하지 않았다.
- 미검증·남은 문제: 새 로컬 DB 환경과 새 검색 품질은 미검증이며 Claude의 구현·실행도 아직 시작하지 않았다.
- 다음 단계: 사용자가 지시서 시작 문구를 Claude에게 전달한다. Claude가 구현·테스트·실데이터 결과를 기록하면 Codex가 재검토한다.
  Git 스테이징·커밋·push와 외부 메시지 전송은 하지 않았다.

### 2026-09-18 · Codex · 기존 작업 중지와 팀 검색 구조 제안 검토

- 요청·목적: 기존 작업을 잠시 멈추고 MySQL 정형 필터→임베딩 유사도→규칙/수식→Top N,
  별도 로컬 DB 실험 구상을 검토한다.
- 변경 파일: STATUS·WORKLOG. 기존 A–E 계획을 일시 중지로 표시하고 검토 내용만 기록했다.
- 확인 근거: 현재 검색은 dense/BM25 후보 검색 후 마감·지역·집단 규칙을 적용한다.
  `shared/embed.py`의 입력은 title/body/target_text/target_category/category/subcategory 6필드다.
  `db/mysql_migration_004_notice_conditions.sql`은 추출 업력을 참고용으로 명시한다.
- 판단: VectorDB 없는 후보 벡터 직접 계산은 실험 가능하나, 정형 조건의 정확도·미확인 처리와 BM25의 가치는 별도 검증해야 한다.
  Elasticsearch/OpenSearch로 엔진을 바꾸는 것 자체가 조건 추출이나 검색 품질을 해결하지는 않는다.
  임베딩 입력 변경과 검색 방식 변경을 나눠 비교하는 것이 적절하다.
- 참고: [Sentence Transformers 의미 검색](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html),
  [Elastic 하이브리드 검색](https://www.elastic.co/docs/solutions/search/hybrid-search) 공식 문서를 확인했다.
- 실행 범위: 코드·스키마 읽기와 기술 검토만 수행. DB 생성/복사/변경, 검색·임베딩·테스트 실행은 하지 않았다.
  기존 작업을 재개하지 않았으며 Git 스테이징·커밋·push도 하지 않았다.
- 다음 단계: 사용자와 필터 조건·새 로컬 실험 범위를 정한다. 아직 구현 착수 지시서로 간주하지 않는다.

### 2026-09-18 · Codex · 제출·발표 기준 우선순위 추천

- 요청·목적: 사용자가 A Chroma 검증/B 사람 판정/C 무관 차단/D 업력 추출/E 발표 준비의 가치·비용과 순서를 요청했다.
  제출까지 시간이 짧고 주간 AI 사용량이 73%라는 사용자 제공 조건을 반영했다(사용량 직접 조회는 하지 않음).
- 작업 전 상태: 바로 앞 지시서는 A를 다음 작업으로 제안했지만 원래 목적에 필요한 사람 판정은 전무했다.
- 변경 파일: `docs/STATUS.md`, `docs/WORKLOG.md`. 코드·지시서 원문·판정 CSV·실험 결과는 보존했다.
- 전후 차이·선택 이유: **B→E→A→C→D**로 추천을 변경했다. 기본 제출 목표는 B 최소 판정과 E 완료이며,
  A는 신뢰 보강용 선택 작업, C·D는 검증/구현 비용 때문에 보류 추천이다. A 우선 인계 문구도 최신 추천에 맞춰 정리했다.
- 검증: 표준 Python csv로 최신 `054314Z/human_review.csv`를 읽어 200행의 관련성 판정이 모두 비어 있음을 확인했다.
  B단계 Top-3는 60행·중복 제외 신청자–공고 50쌍, Top-5는 100행·80쌍이다.
  문서 로컬 링크와 diff 공백 오류도 확인했다. 검색·DB·모델·테스트 실행은 하지 않았다.
- 미검증·남은 문제: 실제 마감일과 사용자 판정 속도는 알 수 없으므로 비용은 상대 추정이다.
  Chroma 미검증 상태는 그대로이며, 사람 판정도 정합성 보증이나 전체 품질 우위 증명으로 확대하지 않는다.
- 다음 단계: Claude가 B의 최소 판정 준비와 E 구성 정리를 우선 지원하고, 사람이 작성한 결과만 집계한다.
  사람 판정·발표 제작·개발 착수는 이번 턴에 실행하지 않았다. 스테이징·커밋·push는 하지 않았다.

### 2026-09-18 · Codex · Claude용 Chroma 정합성 검증 지시서 작성

- 요청·목적: 사용자가 다음 Claude 작업을 문서로 작성해 전달하도록 요청했다.
- 작업 전 상태: 날짜 경계 문제는 해결 확인됐고 Chroma 실제 벡터 내용은 미검증으로 남아 있었다.
  기존 코드·실험 결과·문서 수정과 미추적 `docs/guides/hybrid_flow.html`은 보존했다.
- 변경 파일: `docs/reviews/chroma/CHROMA_INTEGRITY_TASK_20260918.md` 신규, `docs/STATUS.md`, `docs/WORKLOG.md`.
- 전후 차이·선택 이유: DB 입력 해시→NPZ→실제 Chroma 벡터 대조를 후속 작업으로 명시했다.
  검사 전용 실행, 모델 추론·검색·색인 변경 제외, 메타데이터 대조, 실패 시 검색 중단,
  관련 테스트·새 검사 보고서·과거 실행에 소급 적용 금지까지 완료 기준을 정했다.
  기존 `app.boot()`의 워밍업과 `vecstore.stat()`의 메타데이터 대체 동작을 피하도록 코드 근거를 반영했다.
- 검증: 공통 규칙·최근 리뷰·현재 검사와 색인/임베딩 메타데이터 코드에 대조해 지시서를 작성했다.
  문서 로컬 링크 대상과 수정 파일 공백 오류를 확인했다. 문서 작업이므로 테스트·DB·색인·모델 실행은 하지 않았다.
- 미검증·남은 문제: Chroma 내용 일치 여부는 그대로 미검증이다. Claude의 실행을 직접 시작하거나 외부 메시지를 전송하지 않았다.
- 다음 단계: 사용자가 지시서의 시작 문구를 Claude에게 전달하면 구현·읽기 전용 검사 후 기록을 남기고 Codex가 재검토한다.
  스테이징·커밋·push는 하지 않았다.

### 2026-09-18 · Codex · 날짜 변경 무효 처리 해결 확인

- 요청·목적: Claude의 날짜 경계 추가 P2 수정과 최신 `reports/search_comparison_20260918T054314Z/`를 재검토한다.
- 작업 전 상태: 비교 도구·신규 날짜 회귀 테스트·네 번째 결과 폴더·상태/이력의 기존 변경이 있었다. 보존했다.
- 변경 파일: `docs/reviews/search/SEARCH_COMPARISON_REVIEW_20260918.md` 후속 확인 2, STATUS·WORKLOG.
  서비스·비교 코드·테스트·실험 결과 파일은 수정하지 않았다.
- 전후 차이·선택 이유: 날짜 변경 시 정상 발행하던 P2를 해결로 변경했다.
  호출 전후·실행 시작/종료 날짜를 검증하고, 혼합되면 종료코드 3과 진단용 원본만 남긴다.
- 검증: 번들 Python 3.12, `PYTHONPATH=.venv/Lib/site-packages`에서
  `python -B -X utf8 -m unittest discover -s tests -p test_search_comparison.py -v`: 7개 통과.
  추가 가상 날짜 경계 4종(첫 검색 전/도중, 마지막 검색 후, 종료 전 시계 되돌림) 모두
  실제 main/run_case에서 코드 3과 INVALID.md·inputs·responses만 생성함을 확인했다.
  최신 40응답·20비교 집계/요청/날짜/설정, 110개 스냅샷 ID, 200행 빈 판정 CSV,
  HTML 재생성 일치·비교 코드 해시 일치를 확인했다. 직전 실행 대비 순위 목록 40/40 동일.
- 미검증·남은 문제: Chroma 실제 벡터 대조는 이번 Claude 수정 범위에 없어 미검증 상태 그대로다.
  실제 DB·모델 검색·전체 테스트·브라우저 시각 확인·사람 판정은 이번에 수행하지 않았다.
  일부 파일의 명시적 close 누락 ResourceWarning이 있었으나 검증 실패나 결과 누락은 관찰되지 않았다.
  이번 수정 범위에서 추가 기능 오류는 발견하지 않았다.
- 다음 단계: 최신 비교표로 사람 판정 진행 가능. 전체 내용 정합성까지 보장하려면 Chroma↔NPZ 벡터 대조가 남아 있다.
  스테이징·커밋·push는 하지 않았다.

### 2026-09-18 · Claude · 날짜 경계 무효 처리(재검토 추가 P2)와 최종 재실행

- 요청·목적: Codex 재검토([리뷰 문서](reviews/search/SEARCH_COMPARISON_REVIEW_20260918.md) 후속 확인)의 추가 [P2] —
  실행 중 로컬 날짜가 바뀌어도 경고만 남기고 혼합된 결과를 성공으로 저장한다.
- 작업 전 상태: 이전 수정에서 날짜 경고만 넣었다. 종료코드 0 으로 끝나고 비교표·manifest·HTML 이 모두 저장돼,
  나중에 그 표를 하루치 기준으로 읽을 수 있었다. Codex 가 가상 날짜 변경으로 재현했다.
- 변경 파일:
  - `eval/search_comparison.py`: 검색 호출 **직전·직후** 날짜를 각각 기록(`applied_date`,
    `applied_date_after`). 시작일을 저장하고 `date_problems()` 로 종료일·응답 날짜 혼합·호출 중 변경을 판정한다.
    하나라도 걸리면 **무효 실행**으로 처리해 종료코드 3 으로 끝나고, 원본 응답만
    `…_INVALID_date_changed/` 에 `INVALID.md` 와 함께 남긴다. 비교표·판정 양식·manifest 는 만들지 않는다.
    정상 실행의 manifest 에는 `run_end_date` 와 `date_consistent: true` 를 남긴다.
  - `tests/test_search_comparison.py`(신규 7개): 날짜 판정 규칙 4개와, `main()` 이 실제로
    무효 처리(코드 3)·정합성 중단(코드 2)·정상 저장(코드 0)을 하는지 확인한다. 검색은 가짜로 대체한다.
  - `reports/search_comparison_20260918T054314Z/`(최종 실행)과 `summary.md`.
    직전 폴더 `…T053148Z` 에 대체 표시 `NOTE.md` 추가.
- 전후 차이·선택 이유: 경고를 무효 처리로 올린 이유는, 경고는 로그에만 남고 결과 파일에는 남지 않아
  나중에 인용할 때 사라지기 때문이다. 원본을 지우지 않고 `INVALID.md` 와 함께 남겨 진단은 가능하게 했다.
- 검증(2026-09-18, 작업 PC · 프로젝트 `.venv`):
  - `date_problems()` 4가지 상황(정상·종료일 다름·응답 날짜 섞임·호출 도중 변경) 판정 확인.
  - `main()` 에 가짜 시계를 넣어 20번째 검색부터 날짜가 바뀌게 했더니 **종료코드 3**,
    `…_INVALID_date_changed/` 에 `INVALID.md`·`responses.jsonl` 만 생성, `comparison.html`·
    `human_review.csv` 는 생성되지 않음을 확인.
  - 정합성 실패(ID 불일치) 주입 시 **종료코드 2**, `run_case` 가 한 번도 호출되지 않고 폴더도 남지 않음.
  - 전체 테스트 `python -m unittest discover -s tests`: **124개 통과**(건너뜀 13). 이전 117 → 신규 7.
  - 최종 재실행: 정합성 통과(ID 집합 동일 · BM25 내용 불일치 0 · 벡터 해시 불일치 0 · 누락 0),
    `date_consistent: true`, 40응답 모두 호출 전후 날짜 2026-09-18.
    직전 실행(`…T053148Z`)과 **상위 5가 40개 모두 동일** — 이번 수정은 순위를 바꾸지 않았다.
- 미검증·남은 문제: **Chroma 실제 벡터 내용은 여전히 검증하지 않는다**(`chroma_content_verified: false`).
  Codex 가 제안한 `get(include=['embeddings'])` 로 NPZ 와 벡터를 직접 대조하는 읽기 전용 검사는
  이번 범위에 넣지 않았다. 실제 자정을 넘는 상황에서의 동작은 가짜 시계로만 확인했다.
  사람 판정(`human_review.csv`)은 여전히 비어 있다.
- 다음 단계: Codex 재검토. 이후 사용자 판정 또는 Chroma 벡터 대조 검사 추가.

### 2026-09-18 · Codex · 검색 비교 수정 재검토

- 요청·목적: Claude가 이전 리뷰 4건을 반영한 코드와 `reports/search_comparison_20260918T053148Z/`를 재검토한다.
- 작업 전 상태: Claude의 비교 도구·새 결과 폴더·NOTE·STATUS·WORKLOG 수정이 존재했다. 기존 수정은 보존했다.
- 변경 파일: `docs/reviews/search/SEARCH_COMPARISON_REVIEW_20260918.md`에 후속 확인 추가, STATUS·WORKLOG 갱신.
  서비스·비교 코드·결과물·색인·판정 데이터는 변경하지 않았다.
- 전후 차이·선택 이유: 기존 기준일 표시·규칙 수치·깊이 요약 3건은 해결 확인.
  내용 검사는 NPZ·BM25 및 오류 중단까지 보강됐으나 실제 Chroma 내용은 미검증으로 부분 해결 처리했다.
  추가 P2: 실행 중 날짜가 바뀌어도 경고만 남기고 혼합 결과를 성공으로 저장한다.
- 검증: 번들 Python 3.12에 기존 `.venv/Lib/site-packages`를 연결해 `-B -X utf8` 오프라인 스크립트 실행.
  40응답·20비교의 쌍/질의/설정/집계, HTML 40표·200행의 ID·순위·제목·URL·코사인·순위/RRF·강조,
  스냅샷 ID 110개, CSV 200행·빈 판정 칸 확인. HTML 임시 재생성과 비교 코드의 manifest 해시도 일치.
  정합성 오류 7종을 실제 main에 주입해 검색 없이 종료코드 2 확인.
  가상 날짜 변경은 경고 후 종료코드 0·혼합 응답 저장·HTML 기준일 일괄 표시를 재현했다.
  ID가 같고 내용이 다른 Chroma를 조회하지 않는 경로도 가상 데이터로 확인했다.
- 결과 해석: 이번 실제 40응답은 모두 9/18이며 날짜 경계 오류의 영향은 확인되지 않았다.
  A 공통 18/50·B 공통 20/50 유지, 이전 실행 대비 순위 목록 39/40 동일(case01/B/hybrid만 다름).
  이번 규칙 후보 예시의 시군구 누적은 dense 1·hybrid 2이며 최종 노출 플래그는 모두 0이다.
- 미검증·남은 문제: 실제 DB·Chroma·모델 호출이나 검색 재실행, 브라우저 시각 확인, 사람 판정은 하지 않았다.
  서비스 코드 변경이 없어 앞서 통과한 회귀 21개는 반복하지 않았다. 실제 색인이 낡았다고 단정하지 않는다.
- 다음 단계: 날짜 변경 시 결과 무효화·비정상 종료를 보완한다. Chroma 내용 검증 전까지 한계 표시를 유지한다.
  새 비교표를 통한 사람 판정은 가능하다. 스테이징·커밋·push는 하지 않았다.

### 2026-09-18 · Claude · 검색 비교 리뷰 4건 반영과 재실행 (이전 기록 정정 포함)

- 요청·목적: Codex 리뷰 [SEARCH_COMPARISON_REVIEW_20260918.md](reviews/search/SEARCH_COMPARISON_REVIEW_20260918.md)
  의 P2 3건·P3 1건을 고치고, 보완된 조건으로 다시 실행한다.
- 작업 전 상태: 첫 실행(`reports/search_comparison_20260918T051606Z/`)의 집계는 원본과 일치했으나
  날짜 표시·규칙 수치 해석·정합성 검사·깊이 요약에 문제가 있었다. Claude 가 산출물로 4건을 모두 재현했다.
- 변경 파일:
  - `eval/search_comparison.py`: ① 실제 적용 날짜(`applied_date`)와 원본 질의 날짜(`query_as_of_date`)를
    응답에 나눠 담고 HTML 에도 구분해 표시. 실행 중 날짜가 바뀌면 경고. ② 내용 기준 정합성 검사 추가 —
    BM25 토큰 집계를 DB 내용과 대조, 벡터 파일의 입력 해시와 DB 해시 대조, Chroma 는 내용 확인 불가로 명시
    (`chroma_content_verified: false`). ③ 검사 실패 시 검색을 시작하지 않고 종료코드 2로 중단
    (`integrity_failures`). 색인을 자동 재생성하지 않는다. ④ 모델 리비전·미커밋 파일 해시를 manifest 에 기록.
    ⑤ `git status --short` 출력의 선행 공백을 보존(`ocs/STATUS.md` 로 잘리던 문제).
  - `reports/search_comparison_20260918T053148Z/`(최종 실행) · 같은 폴더 `summary.md`(정정본).
  - 이전 두 실행 폴더에 `NOTE.md` 를 넣어 대체됨과 미검증 사항을 표시(결과 파일은 보존).
- 전후 차이·선택 이유: 원본 응답을 고치지 않고 **새 폴더에 다시 실행**했다. 첫 실행은 증거로 남긴다.
  중단 조건을 넣은 이유는, 색인이 어긋난 상태에서 나온 비교를 나중에 사실처럼 인용하지 않기 위해서다.
- **이전 기록 정정**(2026-09-18 Claude · 검색 비교 실행 항목):
  - 깊이는 모두 50이 아니다. **A dense 6 · B dense 40 · hybrid 50 · 라운드 모두 1**이다.
  - 규칙 수치(지역 15/15 · 시군구 2/3 · 집단 9/16)는 최종 노출 건수가 아니라
    **규칙에 걸린 후보 예시의 누적(응답·규칙별 최대 5개)** 이다.
    최종 상위 5에 남은 규칙 플래그는 dense·hybrid 모두 0건이다.
  - 실행 Git 리비전은 `0a72706` 이 아니라 **`ab38ddf`** 다(manifest 기준). 이전 기록의 값이 틀렸다.
  - 첫 실행은 **내용 정합성 미검증**으로 표시했다.
- 검증(2026-09-18, 작업 PC · 프로젝트 `.venv`):
  - 리뷰 4건을 산출물에서 직접 재현: 깊이 표, 최종 플래그 0, manifest 날짜·경로 문자열.
  - 최종 실행 정합성: ID 집합 동일 · BM25 내용 불일치 0건 · 벡터 입력 해시 불일치 0건·누락 0건 ·
    Chroma 내용은 확인 불가로 기록. 모델 리비전 `5617a9f6…` 기록됨.
  - 중단 동작: `integrity_failures()` 에 가짜 값 5종을 넣어 ID 불일치·BM25 불일치·벡터 낡음·
    벡터 확인 실패가 각각 중단 사유로 잡히는지 확인(정상 입력은 빈 목록).
  - `git_info()` 재실행: 미커밋 파일 8개 경로가 잘리지 않고 기록됨.
  - 첫 실행과 최종 실행의 상위 5는 **40개 중 39개 동일**. 1개 차이는 Chroma 근사 검색의 흔들림으로 보이며
    단정하지 않는다.
- 미검증·남은 문제: **Chroma 색인 내용 자체는 여전히 확인할 수 없다**(색인에 입력 해시가 없다).
  사람 판정은 아직 없다. 무관 질의 차단 장치가 없다는 점은 그대로다.
  실행 중 날짜 변경 경고 경로는 실제로 날짜가 바뀌는 상황에서 검증하지 못했다.
- 다음 단계: Codex 재검토 → 사용자 `human_review.csv` 작성.
  Chroma 메타데이터에 입력 해시를 넣으면 내용 정합성을 직접 확인할 수 있다(별도 작업).

### 2026-09-18 · Codex · Claude 검색 비교 결과 리뷰

- 요청·목적: Claude가 실행한 임베딩 단독·하이브리드 비교를 작업 지시서와 실제 코드·산출물에 대조한다.
- 작업 전 상태: `eval/search_comparison.py`와 `reports/search_comparison_20260918T051606Z/`가 미추적 파일로 존재했다.
  STATUS·WORKLOG의 기존 Claude 수정과 결과물은 보존했다.
- 변경 파일: `docs/reviews/search/SEARCH_COMPARISON_REVIEW_20260918.md` 신규, `docs/STATUS.md`, `docs/WORKLOG.md`.
  서비스·비교 도구·원본 산출물·가중치·qrels는 수정하지 않았다.
- 전후 차이·선택 이유: 핵심 집계는 확인했지만 해석에 영향을 주는 P2 3건과 P3 1건을 구분해 인계했다.
  P2는 HTML 기준일 9/15와 실제 실행일 9/18의 불일치, 규칙 후보 예시를 최종 노출 건수로 오해,
  ID만 비교해 내용이 낡은 색인을 검출하지 못하는 검사다. P3는 모든 깊이가 50이라는 요약 오류다.
- 검증: 번들 Python 3.12와 기존 가상환경 패키지로 `python -B -X utf8 -m unittest discover -s tests -p test_match_rules.py` 실행, 21개 통과.
  이전 검색시간 P3 회귀도 통과했다. 별도 오프라인 Python 대조로 40응답의 쌍·설정·질의,
  비교 20건의 공통·신규·순위 이동, HTML 40표·200행의 ID·순위·제목·URL·코사인·초록 표시,
  스냅샷 110개 ID 포함 여부와 CSV 200행·빈 판정 칸 일치를 확인했다.
  `bs4` import는 설치되지 않아 실패했고, 설치 없이 표준 `html.parser`로 전환해 대조를 완료했다.
- 이전 Claude 실행 기록 정정: A dense 깊이는 6, B dense는 40, hybrid는 모두 50이며 라운드는 모두 1이다.
  규칙 예시 합계는 최종 노출 통계가 아니며 B 결과의 세 규칙 플래그는 양쪽 모두 0건이다.
  실행 Git 리비전은 이전 기록 `0a72706`과 manifest `ab38ddf`가 달라 확인이 필요하다.
- 미검증·남은 문제: DB·Chroma·임베딩 검색 재실행, 내용 일치의 실DB 검증, 전체 테스트,
  브라우저 시각 확인·원문 방문·사람 판정은 하지 않았다. 실제 색인이 낡았다고 단정하지 않는다.
- 다음 단계: Claude가 리뷰의 4건과 재현 정보를 보완하고 수정 결과를 기록한다.
  당시 상태를 입증할 수 없으면 미검증으로 표시하고 새 실행을 이전 결과와 구분한다. 스테이징·커밋·push는 하지 않았다.

### 2026-09-18 · Claude · 임베딩 단독·하이브리드 검색 비교 실행

- 요청·목적: Codex 가 남긴 [검색 비교 작업 지시서](reviews/search/SEARCH_COMPARISON_TASK_20260918.md) 대로
  같은 입력에서 dense 와 hybrid 가 어떤 공고를 추천하는지 실제 데이터로 비교한다.
  결과를 좋게 만들기 위한 코드 수정·가중치 튜닝은 범위에 넣지 않았다.
- 작업 전 상태: 기존 평가(`eval/evaluate.py`)는 마감·지역·집단 규칙 없이 재는 경로라
  사용자에게 실제로 보이는 결과와 달랐다. 서비스 조건에서의 비교 기록이 없었다.
- 변경 파일:
  - `eval/search_comparison.py`(신규): 서비스 `app.match()` 를 그대로 부르는 얇은 실행 도구.
    입력 선정 → 40개 응답 수집 → 정합성 확인 → 결과물 생성까지 한 번에 한다.
  - `reports/search_comparison_20260918T051606Z/`(약 500KB): manifest·inputs·responses·
    notices·comparison·comparison.html·human_review.csv·summary.md.
    **`reports/` 는 Git 제외 대상이 아니다**(`git check-ignore` 확인). 커밋 여부는 사용자가 정한다.
  - 서비스 코드·가중치·qrels·색인은 건드리지 않았다.
- 전후 차이·선택 이유: 입력은 **결과를 보기 전에 규칙으로** 골랐다(분야 8종의 qid 최솟값 + 무관 2건).
  소재지가 질의 파일에 없어 3건에만 가상 소재지를 더하고 그 사실을 입력 파일과 비교표에 표시했다.
  단계 A(후처리 전부 끔)와 B(서비스 조건)를 나눠, 차이가 검색 방식에서 왔는지 규칙에서 왔는지 구분되게 했다.
- 검증(2026-09-18, 작업 PC · 프로젝트 `.venv` · 공고 2,285건 · git 0a72706 + 미커밋 수정):
  - 정합성: DB·Chroma·BM25·서버 표시용 정보의 **공고 ID 집합이 모두 동일**(건수 비교가 아니라 집합 비교).
  - 40개 응답 모두 5건을 채웠고, 각 쌍의 요청은 `search` 값만 달랐다(자동 확인).
  - 비교표 집계(공통/신규/순위 이동)가 원본 응답과 일치.
  - 결과 요약: A 단계 공통 18/50칸·hybrid 에만 32건, B 단계 공통 20/50칸·hybrid 에만 30건.
    10개 사례 모두 상위 5가 달랐다. 검색 깊이 50·1라운드.
  - HTML 을 실제로 열어 한국어 표시·원문 링크·초록 표시(반대쪽 미노출)를 확인했다.
- 미검증·남은 문제: **사람 판정이 없다**(`human_review.csv` 는 빈 양식). 사례 10개로는 우열·유의성을 말할 수 없다.
  무관 질의 2건에서 두 방식 모두 그럴듯한 공고 5건을 돌려준다(차단 장치 없음).
  소재지가 없는 7개 입력에서는 지역 규칙이 실질적으로 작동하지 않았다.
  "이 단어 때문에 올라왔다" 류의 설명은 순위 정보에서 읽은 추정이며 단어 기여도를 계산하지 않았다.
- 다음 단계: 사용자가 `human_review.csv` 를 채우면 이 10개 사례에 한해 사람 기준 비교가 가능하다.
  Codex 후속 리뷰 대상: `eval/search_comparison.py` 와 결과 폴더.

### 2026-09-18 · Codex · Claude용 검색 비교 작업 지시서 작성

- 요청·목적: 사용자가 실제 임베딩 단독·하이브리드 공고 비교를 Claude에게 맡길 수 있도록 지시서를 문서로 남긴다.
- 작업 전 상태: 원 검토 2번·3번 수정은 Codex가 확인했고, 마지막 검색시간 P3는 Claude의 수정·검증 기록이 있다.
  이번에는 새 비교를 실행하지 않고 최신 코드의 설정과 기존 평가 경로 차이를 확인했다.
- 변경 파일: `docs/reviews/search/SEARCH_COMPARISON_TASK_20260918.md`, `docs/STATUS.md`, `docs/WORKLOG.md`.
- 전후 차이·선택 이유: 대표 입력 10개(정상 8·무관 2)에 대해 후처리 제외/서비스 조건 두 단계에서
  dense/hybrid를 비교하도록 정의했다. 검색 방식의 차이와 최종 규칙의 영향을 구분해 보고할 수 있게 했다.
  원본 응답·공고 근거·메타데이터·정적 HTML 비교표·빈 사람 판정 양식·요약을 결과물로 지정했다.
- 검증: 지시서와 상태·이력의 로컬 링크 27개, 현재 API 설정과 완료 조건을 확인했다.
  STATUS·WORKLOG의 `git diff --check`도 통과했다. 문서 작업이므로 검색·DB·모델 호출이나 테스트 실행은 하지 않았다.
- 미검증·남은 문제: 실제 검색 결과는 아직 없다. Claude에게 직접 메시지를 전송하거나 실행을 시작하지 않았다.
  지시서에는 기존 판정의 잠정성, 데이터 정합성, 기준 날짜, 비용·변경 범위와 후속 리뷰 기준을 명시했다.
- 다음 단계: 사용자가 지시서를 Claude에게 전달하면 해당 범위로 비교를 실행하고 결과·기록을 갱신한다.
  Git 스테이징·커밋·push는 실행하지 않았다.

### 2026-09-18 · Claude · 검색 시간 표시 보완(P3)

- 요청·목적: Codex 후속 검토 [FOLLOWUP](reviews/matching/MATCHING_REVIEW_20260918_FOLLOWUP.md) 의 [P3] —
  `search_ms` 에 벡터 추가 조회·RRF 결합 시간이 빠져 화면에 실제보다 짧게 찍힌다.
- 작업 전 상태: 2·3번을 고치며 `search_ms = dense_ms + bm25_ms` 로 바꿨다. 두 값은 Chroma 질의와
  BM25 검색만 재므로, 그 사이의 `_fill_distances()`(단어 검색에서만 올라온 공고의 벡터를 꺼내는 호출)와
  순위 결합 시간이 어느 항목에도 들어가지 않았다. 후보를 여러 번 찾으면 누락도 쌓인다.
- 변경 파일:
  - `search/app.py`: 검색 반복 구간 전체를 바깥에서 재도록 `search_started` 기준으로 바꿨다.
    dense·BM25 세부 시간은 "어디에 시간이 쓰였나" 를 보려고 그대로 둔다.
  - `tests/test_match_rules.py`: `SearchTimingTests` 추가. 시간은 눈으로 확인할 수 없어
    **모의 시계**로 각 단계에 값을 부여하고(질의 10ms·BM25 20ms·벡터 조회 250ms) 합이 담기는지 본다.
- 전후 차이·선택 이유: 같은 조건에서 이전 `search_ms` 30ms → 지금 280ms(모의 시계 기준).
  순위 결과는 바뀌지 않는다. 표시용 수치만 정확해진다.
  구간 전체를 재는 방식은 2·3번 수정 이전 구현과 같고, 세부 시간을 남겨 두면 원인 파악도 된다.
- 검증(2026-09-18, 작업 PC):
  - `SearchTimingTests`: 모의 시계 280ms 를 그대로 보고. 수정 전 코드로는 30ms 였다.
  - `python -m unittest discover -s tests`: 117개 통과(건너뜀 13). 수정 전 116개 → 신규 1개.
  - 실서버 질의 3종: 검색 22~27ms, 그중 세부 합계 14~23ms. 차이(약 4ms)가 벡터 추가 조회·결합 시간이며
    이제 표시에 포함된다. 깊이 50·1회 검색.
- 미검증·남은 문제: 실제 사용자 부하에서의 지연은 측정하지 않았다. `web/demo.html` 의 리랭커 시연 화면은
  이 값을 그대로 쓰므로 표시가 함께 정확해지지만 별도로 확인하지는 않았다.
- 다음 단계: 원 검토 4건과 날짜 오류, P3 까지 모두 처리했다. 남은 검토 지적 없음.

### 2026-09-18 · Codex · 원 검토 2번·3번 수정 확인

- 요청·목적: Claude의 점수 혼용·후보 미보충 수정 리뷰.
- 작업 전 상태: `search/app.py`와 `tests/test_match_rules.py` 변경을 Git diff 및 최신 Claude 기록으로 확인했다.
- 변경 파일: 이번 Codex 작업은 `docs/STATUS.md`, `docs/WORKLOG.md`, `docs/reviews/matching/MATCHING_REVIEW_20260918_FOLLOWUP.md`만 갱신했다.
- 전후 차이·선택 이유: 2번은 하이브리드에서 RRF만 사용하고, 3번은 충분한 후보 또는 색인 끝에 도달할 때까지 검색 깊이를 늘려 해결했다.
  이전 네 건의 재현과 날짜 오류 해결 상태를 유지하며 확인 기록을 추가했다.
- 검증: 관련 세 테스트 파일 53개 통과. 별도 가상 시나리오 12개(점수 방식, dense/hybrid 보충,
  4회 반복, 전부 마감, 유효 후보 1건, watermark, 메타데이터 없는 후보, BM25 전용 후보)도 통과했다.
  번들 Python 3.12.14 + 기존 가상환경 패키지 사용. DB·모델·외부 서버·전체 테스트 호출 없음.
- 미검증·남은 문제: 원 검토 2번·3번은 해결 확인. 새 P3는 검색시간 표시에서 벡터 추가 조회·RRF 처리가 빠지는 문제다.
  모의 시간으로 총 280ms 중 `search_ms`가 30ms만 보고함을 확인했다. 실제 서비스 속도 측정 결과는 아니다.
- 다음 단계: 검색 구간 전체 시간을 별도로 측정하면 성능 표시를 보완할 수 있다.
  서비스 코드를 수정하지 않고 검토로 종료했다. Git 스테이징·커밋·push는 실행하지 않았다.

### 2026-09-18 · Claude · 검토 2번·3번 수정(후보 보충과 점수 체계 통일)

- 요청·목적: Codex 검토 [MATCHING_REVIEW_20260918.md](reviews/matching/MATCHING_REVIEW_20260918.md) 의
  2번(score 방식이 RRF 점수와 코사인 유사도를 섞음)과 3번(마감 제외 후 후보 미보충)을 고친다.
- 작업 전 상태: 후보를 고정 깊이(하이브리드 50)로 한 번만 가져오고, 마감 공고를 걸러 건수가 모자라면
  **의미 검색 51위 이하를 꼬리로 붙였다.** 그 꼬리에는 RRF 점수가 없어 코사인 유사도로 대신했다.
  두 문제의 원인이 같아 한 번에 고쳤다.
- 변경 파일:
  - `search/app.py`: 검색을 반복 구조로 바꿨다. 후보를 걸러낸 뒤 요청 건수에 못 미치면 깊이를
    3배로 늘려 다시 검색한다(색인 전체에 닿으면 멈춘다). 꼬리를 붙이는 코드를 삭제했다.
    score 방식의 기준 점수에서 코사인 대체를 없애 **하이브리드면 RRF, 의미 검색만이면 유사도** 한 가지만 쓴다.
    응답에 `depth`·`search_rounds` 를 추가해 몇 번·얼마나 깊이 찾았는지 보이게 했다.
  - `tests/test_match_rules.py`: `CandidateRefillTests`(5개), `ScoreModeTests`(3개) 추가.
- 전후 차이·선택 이유:
  - 3번: 공고 60건 중 앞 51건이 마감이고 뒤 9건이 접수 중일 때 이전 `count=0` → 지금 `count=3`
    (n052·n053·n054). 전부 마감이면 색인 끝까지 찾고 0건으로 끝난다(무한 반복 없음).
  - 2번: 감점을 모두 0 으로 준 score 방식이 이전에는 `n051, n001, n002`(1위 점수 0.55 = 코사인)
    → 지금 `n001, n002, n003`(1위 0.03279 = RRF)로 order 방식과 같아졌다.
  - 두 검색에 마감 조건을 먼저 거는 방법(정형 필터)도 있으나, 지금은 마감 정보가 없는 공고
    (기간 미상·상시 모집)를 살려 두는 정책이라 후처리 유지 + 깊이 확장을 택했다.
- 검증(2026-09-18, 작업 PC · 프로젝트 `.venv` · 공고 2,285건):
  - 재현 스크립트: 네 건 모두 '문제 없음'.
  - `python -m unittest discover -s tests`: 116개 통과(건너뜀 13). 수정 전 108개 → 신규 8개.
  - 실서버 `/api/match`(경기·수원시, 하이브리드, top=3): 3건 · 깊이 50 · 라운드 1 · 306ms.
    평소 질의는 한 번에 끝나 속도에 영향이 없다.
  - `/api/match_compare` 기본 가중치: `identical=true`.
  - 규칙을 끄고 비교하면 감점 0 인 score 방식과 order 방식의 상위 5가 같다.
    규칙을 켜면 다르다 — 감점 0 은 '규칙을 쓰지 않는다' 는 뜻이므로 의도된 차이다.
  - 평가: `eval/evaluate.py` dense 0.468 / rrf 0.603, 짝지은 차이 +0.135(95% +0.051~+0.224).
    `eval/gate_eval.py` 업력 모름 0.647 · 쓸모칸 0.481. 모두 기존 범위(±0.007 흔들림) 안이다.
    평가는 마감 공고를 걸러내지 않으므로 이번 수정의 영향을 받지 않는다.
- 미검증·남은 문제: 깊이를 3배로 늘리는 계수와 최대 반복 횟수는 근거 있는 값이 아니라
  "한두 번이면 대개 채워진다" 는 판단이다. 실제 데이터에서 반복이 얼마나 일어나는지는 측정하지 않았다.
  마감이 아주 많은 질의에서는 검색이 두세 번 돌아 응답이 느려질 수 있다.
- 다음 단계: 원 검토 4건이 모두 해결됐다. 운영 중 `search_rounds` 가 1보다 큰 경우가 잦으면
  초기 깊이를 올리거나 정형 필터를 검토한다.

### 2026-09-18 · Codex · 무효 날짜 오류 수정 확인

- 요청·목적: Claude의 추가 수정이 지난 재검토에서 발견한 날짜 HTTP 500을 해결했는지 확인한다.
- 작업 전 상태: `search/gate.py`의 `parse_ymd()`가 날짜 생성의 `ValueError`를 잡고 None을 반환하도록 변경됐고,
  `tests/test_match_rules.py`에 날짜 경계·HTTP 회귀 테스트가 추가돼 있었다.
- 변경 파일: 이번 Codex 작업은 `docs/STATUS.md`, `docs/WORKLOG.md`,
  `docs/reviews/matching/MATCHING_REVIEW_20260918_FOLLOWUP.md`의 확인 기록만 갱신했다. 서비스·테스트 코드는 수정하지 않았다.
- 전후 차이·선택 이유: 기존 지적은 해결 확인. 이전 검토 증거는 보존하고 같은 검토 문서 뒤에 해결 확인을 추가했다.
- 검증: `test_gate.py` 18개 + `test_applicant.py` 15개 + `test_match_rules.py` 12개 = 45개 통과, 건너뜀 없음.
  별도 TestClient에서 무효 날짜·빈 값 8종과 정상 날짜 3종을 두 API로 보내 22건 모두 200을 확인했다.
  자격 판정이 무효 입력에는 '설립일 미상/판단 불가', 정상 입력에는 정상 업력 판정을 반환함을 확인했다.
  윤년 정상 날짜의 두 표기와 공고의 무효 시작일·마감일 파싱도 확인했다.
- 미검증·남은 문제: 이번 수정 범위에서 추가 발견 사항 없음. 원 검토 2번 점수 혼용·3번 후보 미보충은 수정 범위 밖이며 남아 있다.
  번들 Python 3.12.14와 기존 가상환경 패키지로 검증했으며 실제 DB·모델·외부 서버·전체 테스트는 실행하지 않았다.
- 다음 단계: 날짜 오류 지적은 해결로 기록한다. 이번 리뷰는 완료했으며 Git 스테이징·커밋·push는 실행하지 않았다.

### 2026-09-18 · Claude · 재검토 지적 수정(달력에 없는 설립일이 HTTP 500 이 되던 문제)

- 요청·목적: Codex 재검토 [MATCHING_REVIEW_20260918_FOLLOWUP.md](reviews/matching/MATCHING_REVIEW_20260918_FOLLOWUP.md) 의
  [P2] 지적 — 형식은 맞지만 달력에 없는 날짜(`2026-02-30` 등)가 여전히 HTTP 500 을 낸다.
- 작업 전 상태: 같은 날 앞선 수정에서 `business_age_months()` 가 `parse_ymd()` 의 None 만 처리하게 했다.
  형식 검사를 통과한 값은 날짜 생성까지 들어가므로 실제로 없는 날짜면 예외가 그대로 올라갔다.
  Claude 가 직접 재현: `2026-02-30` `20260230` `2026-13-01` `2025-02-29` 네 종 모두 ValueError.
- 변경 파일:
  - `search/gate.py`: `parse_ymd()` 에서 `ValueError` 를 잡아 None 을 돌려준다. 방어를 한 단계 아래로 내려
    공고 쪽 날짜(`apply_start`·`apply_end`)도 같은 보호를 받는다.
  - `tests/test_match_rules.py`: 달력에 없는 날짜 5종, `parse_ymd` 가 예외를 내지 않음,
    `HttpErrorTests`(FastAPI TestClient 로 `/api/match`·`/api/eligibility` × 잘못된 날짜 6종 = 12개 응답).
- 전후 차이·선택 이유: 이전에는 `business_age_months()` 에서만 막아 호출 경로마다 같은 방어가 필요했다.
  날짜를 실제로 만드는 `parse_ymd()` 에서 막으면 한 곳으로 끝난다. 값은 '설립일 미상'(판단 불가)이 된다.
  4xx 로 돌려주는 방법도 있으나 현재 API 는 자격을 3값으로 다루므로 '모른다' 로 잇는 편이 일관된다.
- 검증(2026-09-18, 작업 PC · 프로젝트 `.venv`):
  - `gate.business_age_months`: 위 4종 + `설립일` + 빈 값 + None → 모두 None. 정상 날짜 2종은 값 반환.
  - `python -m unittest discover -s tests`: 108개 통과(건너뜀 13). 수정 전 105개 → 신규 3개.
  - Codex 가 재검토 문서에 적은 재현 코드를 그대로 실행: 잘못된 날짜 6종 × API 2개 모두 200
    (재검토 시점에는 네 종이 500 이었다).
- 미검증·남은 문제: 원 검토 2번(score 방식 점수 혼용)·3번(마감 제외 후 후보 미보충)은 여전히 미수정이다.
  이번 확인은 TestClient 와 가짜 색인으로만 했고 실제 서버·DB 는 쓰지 않았다.
- 다음 단계: 2번·3번 수정 여부를 사용자와 정한다.

### 2026-09-18 · Codex · Claude의 1번·4번 수정 재검토

- 요청·목적: Claude가 수정한 지역 규칙 우선순위와 설립일 미상 처리를 리뷰한다.
- 작업 전 상태: Claude는 최초 리뷰 1번·4번만 수정하고 회귀 테스트 9개를 추가했다. 2번·3번은 수정 범위 밖이다.
- 변경 파일: `docs/reviews/matching/MATCHING_REVIEW_20260918_FOLLOWUP.md`, `docs/STATUS.md`, `docs/WORKLOG.md`만 작성·갱신.
  서비스 코드·테스트 코드는 수정하지 않았다.
- 전후 차이·선택 이유: 지역 순서가 dense/hybrid 모두 수원→성남→서울로 나오는 것을 확인했다.
  설립일 빈 값과 일반 문자열은 판단 불가로 처리하나, `2026-02-30`처럼 형식에 맞는 무효 날짜는 예외가 남아 있음을 발견했다.
- 검증: 관련 세 테스트 파일 합계 42개 통과. 가상 데이터로 이전 재현을 다시 실행했다.
  내부 FastAPI TestClient로 날짜 7종×API 2개를 확인해, 유효하지 않은 날짜 4종이 두 API 모두 HTTP 500을 반환함을 검증했다.
  번들 Python 3.12.14 + 기존 가상환경 패키지 사용. 설치·환경 파일 변경·DB·모델·외부 네트워크 호출 없음.
- 미검증·남은 문제: 새 P2는 달력상 유효하지 않은 설립일의 예외 미처리. 기존 2번·3번도 여전히 재현된다.
  전체 테스트, 실서버, 실제 검색 품질 평가는 실행하지 않았다.
- 다음 단계: 날짜 오류 방어에 `ValueError` 처리 및 무효 날짜 회귀 테스트를 보완한다.
  검토로 종료하며 Git 스테이징·커밋·push는 실행하지 않았다.

### 2026-09-18 · Claude · 검토 지적 4번·1번 수정(자격 판정·규칙 우선순위)

- 요청·목적: Codex 검토 [MATCHING_REVIEW_20260918.md](reviews/matching/MATCHING_REVIEW_20260918.md) 의 4번(설립일 미상 오판정)과
  1번(시·군·구 규칙이 시·도 우선순위를 덮어씀)을 고친다. 2번·3번은 이번 범위가 아니다.
- 작업 전 상태: Codex 가 코드 수정 없이 네 건을 보고한 상태. 검토자가 쓴 재현 조건과 별개로
  Claude 가 `app.match()`·`app.eligibility()` 를 가짜 색인으로 직접 불러 네 건이 모두 재현됨을 확인했다.
- 변경 파일:
  - `search/gate.py`: `UNKNOWN_AGE` 도입(설립일 미상 ≠ 미설립), `_check_age` 가 이 값을 판단 불가로 처리.
    `business_age_months()` 가 형식이 잘못된 날짜에 예외를 던지지 않고 None 을 돌려주도록 변경.
  - `search/app.py`: `/api/eligibility` 가 사업자인데 설립일이 없거나 읽을 수 없으면 `UNKNOWN_AGE` 를 넘긴다.
    규칙 세 개를 차례로 밀어내던 코드를 **우선순위를 명시한 한 번의 정렬**로 교체
    (시·도 → 시·군·구 → 집단 → 원래 검색 순서). `*_demoted` 목록은 정렬 후 표시용으로 만든다.
  - `tests/test_match_rules.py`(신규 9개): 두 사례의 회귀 테스트.
- 전후 차이·선택 이유:
  - 4번: 법인사업자 + 설립일 빈 값 → 이전 '예비창업자 (미설립)' · 판정 False(신청 불가)
    → 지금 '설립일 미상' · 판정 None(판단 불가). 예비창업자 판정은 그대로다.
  - 1번: 후보 순서 성남시 → 서울 → 수원시, 신청자 경기 수원시일 때
    이전 최종 순서 수원시 → 서울 → 성남시 → 지금 수원시 → 성남시 → 서울.
  - 순차 밀어내기 대신 한 번 정렬을 택한 이유: 규칙이 늘어날 때마다 "나중 규칙이 앞 규칙을 덮는" 문제가
    반복된다. 우선순위를 정렬 키 한 줄에 적어 두면 코드를 읽고 순서를 알 수 있다.
  - `business_age_months` 예외는 회귀 테스트를 쓰다가 발견했다. API 로 들어온 문자열이 그대로 전달되므로
    형식이 틀리면 요청이 500 으로 끝난다.
- 검증(2026-09-18, 작업 PC):
  - 재현 스크립트 재실행: 1번·4번 '문제 없음', 2번·3번은 그대로 재현(수정 범위 밖).
  - `python -m unittest discover -s tests`: 105개 통과(건너뜀 13). 수정 전 96개 → 신규 9개.
  - 실서버 `/api/eligibility`: 설립일 빈 값·형식 오류 모두 '설립일 미상 · 판단 불가',
    예비창업자는 '예비창업자 (미설립)' 유지. 500 오류 없음.
  - `/api/match`(경기·수원시, 하이브리드): 정상 3건 응답.
  - `eval/evaluate.py --systems rrf`: P@3(2) 0.596, `eval/gate_eval.py`: 업력 모름 0.647 · 불가 0.051.
    수정 전과 같은 범위이며 이 수정은 지역·자격 규칙만 건드려 검색 지표에 영향이 없다.
- 미검증·남은 문제: 검토 2번(score 방식이 RRF 점수와 코사인 유사도를 섞음)과
  3번(마감 제외 후 후보 미보충)은 **수정하지 않았다.** 사용자 지시 대기.
  2번 때문에 `/weights` 화면의 score 방식 결과는 감점 효과와 점수 혼용이 섞여 있어 그대로 해석하면 안 된다.
  시·군·구 규칙의 오프라인 효과 측정은 여전히 하지 않았다.
- 다음 단계: 2번·3번 수정 여부를 사용자와 정한다. 3번은 후보 깊이 재검색이라 구조 변경이 필요하다.

### 2026-09-18 · Codex · 공고 매칭 코드 검토

- 요청·목적: Claude가 구현한 정형 조건과 하이브리드 검색을 확인한다.
- 작업 전 상태: Claude의 하이브리드·지역·신청자 입력·가중치 관련 작업 기록과 기존 수정 상태를 읽었다.
- 변경 파일: `docs/reviews/matching/MATCHING_REVIEW_20260918.md`(검토 근거·재현 조건·수정 방향),
  `docs/STATUS.md`(진행·완료 및 미수정 문제), `docs/WORKLOG.md`(이번 기록). 서비스·테스트 코드는 수정하지 않았다.
- 전후 차이·선택 이유: 검색 전에 정형 필터를 거는 구조가 아니라 검색 후 마감 제외·규칙 재정렬을 하는 구조임을 확인했다.
  시도/시군구 우선순위 역전, score 모드 점수 혼용, 마감 제외 후 후보 미보충, 설립일 누락 오판정 4건을 가상 데이터로 재현했다.
- 검증: `unittest discover -s tests -p test_applicant.py -v` 15개 및 `-p test_gate.py -v` 18개 통과.
  실제 `app.match()`/`app.eligibility()`를 가상 색인·공고·질의 벡터로 호출하고 네 결과를 assert로 확인했다.
  프로젝트 `.venv` 실행기는 접근 제한으로 실패하여 번들 Python 3.12.14에 기존 가상환경 패키지를 연결했다.
  설치나 환경 파일 변경은 없으며, 상세 명령·조건은 검토 문서에 적었다.
- 미검증·남은 문제: 네 문제는 아직 수정하지 않았다. 실제 DB·모델·HTTP 서버, 전체 테스트, 실제 검색 품질 비교는 실행하지 않았다.
- 다음 단계: 후속 수정 시 네 사례의 회귀 테스트와 함께 후보 필터·규칙 우선순위·점수 체계·누락 입력 처리를 정리한다.
  이번 요청은 검토로 완료했다. Git 스테이징·커밋·push는 실행하지 않았다.

### 2026-09-18 · Claude · 검색 가중치 시험 경로 추가

- 요청·목적: 지금 설정은 그대로 두고, 가중치를 적용한 결과를 나란히 확인할 수 있게 해 달라.
- 작업 전 상태: 섞는 비율은 RRF 1:1 고정, 규칙(집단·지역)은 "걸리면 맨 뒤" 한 가지 방식뿐이었다.
- 변경 파일:
  - `search/hybrid.py`: `rrf()` 에 `k`·`weights` 인자. 기본 `None` 은 전부 1.0 이라 기존과 동일.
  - `search/app.py`: `Weights` 모델(dense·bm25·rrf_k·mode·penalty 3종), 규칙 판정을 한 곳으로 모음,
    `mode='score'` 일 때 감점 방식 정렬, `POST /api/match_compare`, `GET /weights`.
  - `web/weights.html`: 기본 설정과 조정 가중치를 나란히 비교하는 화면(신규).
  - `eval/weight_eval.py`: 조합별 P@3·nDCG·미판정과 기준선 대비 짝지은 차이(신규).
- 전후 차이·선택 이유: `weights` 를 넘기지 않으면 결과가 이전과 같다(비교 API 의 `identical=true` 로 확인).
  규칙을 점수로 바꾸는 `score` 방식은 곱셈 감점(점수 × (1−감점))으로 했다. 덧셈은 RRF 점수(0.01~0.05)와
  단위가 맞지 않아 값을 정하기 어렵다. 감점 1.0 = 사실상 배제라 기존 order 방식과 연속적으로 이어진다.
- 검증(2026-09-18, 로컬 서버 · 공고 2,285건 · Chroma 2,285건 · qrels 2026-09-17 보충 판정 반영):
  - `POST /api/match_compare` 기본값: `identical=true` (질의: 스마트공장 구축·품질 검사 자동화, 경기 수원시, top=5).
  - 의미 2배: 상위 5 변화 없음. 단어 2배: 3칸 이동·1건 신규. score 방식(집단 0.4·시도 0.8·시군구 0.25):
    군포시 공고가 25% 감점 후에도 1위로 올라옴(order 방식에서는 맨 뒤).
  - `eval/weight_eval.py` (정상 52질의, LLM 잠정 판정 포함): 1:1 P@3(2) 0.596 / 2:1 0.590 / 1:2 0.615 /
    3:1 0.596 / 1:3 0.590. 기준선 대비 짝지은 차이의 95% 구간이 모두 0 을 걸쳐 **판단 불가**.
  - `python -m unittest discover -s tests`: 96개 통과(건너뜀 13).
- 미검증·남은 문제: 감점 기본값(0.5·1.0·0.3)은 근거 없는 임시값이다. score 방식은 오프라인 평가에
  포함하지 않았다(질의에 소재지가 없어 지역 규칙을 함께 재려면 `eval/region_eval.py` 방식이 필요).
  조합을 여럿 재면 과적합 위험이 있어 현재 수치로 기본값을 바꿀 근거는 없다.
- 다음 단계: 기본값 1:1·order 유지. 바꾸려면 질의 수를 늘린 뒤 다시 측정한다.

### 2026-09-18 · Claude · 신청자 입력 항목 확장(성별·시군구·인증 등)

- 요청·목적: 사용자가 정리한 새 입력 항목(공통/예비창업자/사업자)을 테스트할 수 있게 해 달라.
  성별을 받는 이유는 여성 우대 공고, 지역은 시·군·구까지 받아야 한다는 요구.
- 작업 전 상태: 입력은 유형·설립일·아이디어·팀경력·수익모델·소재지(시·도)뿐이었다.
- 변경 파일:
  - `search/applicant.py`(신규): 항목을 세 갈래로 나눔 — 질의 문장에 넣는 것(업종·인증·채용계획),
    규칙에만 쓰는 것(성별·재창업·인증·협력기관), 받아만 두는 것(이름·생년월일·사업자번호·자기부담금·예산·장비).
  - `shared/region.py`: 표준 시·군·구 228개(`DISTRICTS`), 제목에서 찾기, `district_matches()` 3값 판정.
  - `search/app.py`: 입력 16항목 추가(모두 선택), `GET /api/form`, 시·군·구 규칙, 결과에 `rules`·`district_match`,
    응답에 `rule_words`·`stored_only`·`why_not_used`.
  - `web/app.html`: 입력 화면 재구성(유형별 칸 분기), 결과에 "매칭에 쓴 것 / 받아만 둔 것" 표시.
  - `tests/test_applicant.py`(신규 16개).
- 전후 차이·선택 이유: 성별·재창업·인증은 **질의 문장이 아니라 규칙에만** 넣었다. 질의 문장을 바꾸면
  임베딩 검색 결과가 통째로 달라져 기존 평가와 비교가 끊긴다. 시·군·구는 공고 지역 칸에 없어
  제목에서 찾는다(실측 2,285건 중 596건 인식). 사업자번호는 응답에 되돌려주지 않고 '입력함' 으로만 표시한다.
- 검증(2026-09-18, 로컬 서버):
  - 새 항목을 비우면 질의 문장이 이전과 문자 단위로 동일(`test_applicant.QueryTests`).
  - 성별 '여성' 입력 시 여성기업 공고가 집단 규칙에서 빠짐, 재창업·인증도 동일하게 동작(단위 테스트).
  - 경기·수원시로 검색 시 성남시·고양시·시흥시 공고가 뒤로 이동(실제 API 응답).
  - `python -m unittest discover -s tests`: 96개 통과(건너뜀 13).
- 미검증·남은 문제: 시·군·구 목록은 표준 행정구역을 직접 입력한 것이라 누락 가능성이 있다
  (제목에서 추출된 이름과 대조해 남은 33종은 모두 오탐임을 확인). 나이·자기부담금·예산·장비는
  공고 쪽에 대응 칸이 없어 매칭에 쓰지 못한다. 시·군·구 규칙의 효과는 오프라인으로 측정하지 않았다.
- 다음 단계: 나이 조건과 업력 조건을 공고에서 뽑아내면 받아 둔 항목을 매칭에 쓸 수 있다.

### 2026-09-18 · Claude · 폴더 정리 2단계(파이썬 패키지 분리)

- 요청·목적: 루트에 파이썬 34개가 섞여 있어 역할을 알기 어렵다. 기능 변경 없이 폴더만 나눈다.
- 작업 전 상태: 1단계(문서·SQL·테스트·화면 분리) 직후. 모든 파이썬 파일이 루트 평면 구조.
- 변경 파일: `collect/`(14) `search/`(6) `shared/`(4) `ec2/`(3) `scripts/`(1) 신설 및 이동(git mv),
  import 94곳, `data/`·`db/`·`web/` 경로 12곳(ROOT 기준으로 변경), `run_daily.bat`(-m 실행),
  문서 9개, 노트북 2개와 생성기 2개, 테스트 3곳.
- 전후 차이·선택 이유: 패키지 실행(`python -m collect.daily_pipeline`)으로 바꿨다. 스크립트 직접 실행을
  유지하려면 진입점 20여 개에 sys.path 조작을 넣어야 해 더 지저분하다. `ec2/` 는 서버에 평면으로 배포돼
  있어 저장소에서만 이동했다(크론 영향 없음).
- 검증(2026-09-18):
  - `python -m unittest discover -s tests`: 81개 통과(당시 기준, 건너뜀 13).
  - `run_daily.bat --dry-run`: exit=0, 정규화 1,830건(수집 API 는 실제 호출, DB 저장 없음).
  - 서버 `python -m search.app`: `/` `/review` `/demo` `/classify` `/api/health` 모두 200,
    하이브리드·지역 규칙 동작 확인.
  - `eval/evaluate.py`, `eval/gate_eval.py` 정상 실행.
- 미검증·남은 문제: EC2 배포본은 갱신하지 않았다(서버는 평면 구조 그대로). 평가 수치는 같은 코드로
  두 번 돌려도 P@3 기준 ±0.007 흔들린다(Chroma 근사 검색). 정리 전후 비교로 쓸 수 없다.
- 다음 단계: EC2 에 새로 올릴 때 경로 규칙을 맞춘다.

### 2026-09-18 · Claude · 폴더 정리 1단계(문서·SQL·테스트·화면 분리)

- 요청·목적: 루트 파일 55개를 정리한다. import 가 깨지지 않는 범위부터.
- 변경 파일: `docs/`(문서 8·ARCHITECTURE.svg·architecture.html), `db/`(SQL 5), `tests/`(6), `web/`(HTML 4) 이동.
  경로 참조 수정(`search/app.py`, `shared/store_mysql.py`, `collect/attachment_store.py`),
  테스트에 부모 경로 추가, 문서 링크·실행 명령 갱신, README 에 폴더 설명 추가.
- 전후 차이·선택 이유: 코드 내용은 바꾸지 않고 위치만 옮겨 git 이 이름 변경으로 인식하게 했다.
- 검증: 테스트 81개 통과, 서버 화면 4개 200, 배치 `--dry-run` 정상, 평가 정상 실행.
- 미검증·남은 문제: 이 단계에서 `collect/attachment_store.py` 의 스키마 경로 수정에 괄호 오류를 넣었고
  2단계 시작 시 발견해 고쳤다(`(Path(...) / 'db' / '...').read_text()`). 해당 함수는 테스트에서
  건너뛰는 MySQL 통합 경로라 테스트로 잡히지 않았다.
- 다음 단계: 2단계(파이썬 패키지 분리).

### 2026-09-17 · Claude · 지역 정규화와 소재지 규칙

- 요청·목적: 공고의 지역을 칸으로 뽑아 소재지와 맞지 않는 공고를 뒤로 보낸다.
- 작업 전 상태: `region` 칸은 K-Startup 376건만 있고 기업마당 1,822건은 비어 있었다.
- 변경 파일: `shared/region.py`(신규, 어휘·정규화·3값 판정·demote), `collect/normalize.py`(수집 시 지역 추출),
  `scripts/backfill_region.py`(신규, 기존 공고 소급 적용), `search/app.py`·`web/app.html`(소재지 입력·규칙·표시),
  `eval/region_eval.py`(신규, 16개 시·도를 모두 넣어 보는 측정).
- 전후 차이·선택 이유: 기업마당은 `hashtags` 에 지역이 섞여 들어와 그것을 파싱하고, 태그가 빠뜨린 경우
  제목 앞머리로 보완했다. 16개 시·도를 모두 나열한 538건은 '전국' 으로 줄였다. 광주·전남은 두 출처 모두
  `전남광주` 표기를 써서 그 어휘로 통일했다. 지역 정보가 없으면 뒤로 보내지 않는다(3값 판정).
  임베딩 입력(`embed.FIELDS`)에는 넣지 않아 기존 평가 수치가 흔들리지 않게 했다.
- 검증(2026-09-17, 공고 2,198건 기준):
  - 제목에 지역이 적힌 1,272건 중 1,271건이 추출 결과와 일치(불일치 1건은 제목 보완으로 해결).
  - `backfill_region.py`: 1,822건 채움, 빈 값 0건. K-Startup 376건은 값 변화 없음.
  - `eval/region_eval.py`(정상 52질의 × 16지역 = 832회, 검색 rrf, qrels 보충 판정 반영):
    신청 불가칸 0.502 → 0.002, 쓸모칸(2) 0.282 → 0.498(+0.215, 95% +0.163~+0.272),
    쓸모칸(≥1) 0.337 → 0.620. 기존 지표 P@3(2) 는 0.635 → 0.500 으로 내려간다.
  - 다음 날 배치 검증: 정규화 결과와 DB 값이 1,777건 전부 일치, 새 공고 87건도 빈 값 없이 채워짐.
- 미검증·남은 문제: P@3 가 내려가는 것은 주제 판정이 지역을 보지 않기 때문이다. 두 지표를 함께 봐야 한다.
  시·군·구는 이 작업에 포함하지 않았다(다음 작업에서 추가).
- 다음 단계: 업력·나이 등 다른 자격 칸도 같은 방식으로 뽑는다.

### 2026-09-17 · Claude · 하이브리드·지역 상위 결과 보충 판정(LLM)

- 요청·목적: 새 검색 방식이 위로 올린 공고가 미판정이라 0점 처리되는 문제를 해소한다.
- 변경 파일: `eval/judge_llm.py`(`--pairs` 옵션 — 지정한 쌍만 채점), `eval/llm_judgments.jsonl`,
  `eval/pool.jsonl`, `eval/pool_meta.json`, `eval/qrels.jsonl`, `eval/runs/*_20260917.jsonl`.
- 전후 차이·선택 이유: `--pairs` 없이 돌리면 이전 프롬프트로 판정한 쌍까지 다시 호출해 비용이 늘어난다.
  사용자에게 예상 비용을 확인받고 실행했다(gpt-4.1-mini, A/B 순서 교차).
- 검증: 하이브리드 상위 5 미판정 64쌍 → 호출 112회, 실제 $0.102. 지역 규칙 상위 3 미판정 51쌍 → 62회, $0.063.
  적용 후 미판정@3 0.244 → 0.109(하이브리드), 쓸모칸(2) 0.480 → 0.498(지역).
- 미검증·남은 문제: 남은 미판정 29쌍은 A/B 순서를 바꿨을 때 판정이 갈린 쌍이라 LLM 으로 채울 수 없다.
  LLM 판정은 사람 판정과 정확 일치 0.64 로 기준(0.70) 미달이므로 모든 수치는 **LLM 잠정 판정 기준**이다.
- 다음 단계: 사람 판정 범위를 넓히거나 질의 수를 늘린다.

### 2026-09-17 · Claude · 하이브리드 서치 적용(의미 검색 + BM25 + RRF)

- 요청·목적: 팀 논의에서 하이브리드 서치가 좋겠다는 의견이 나와, 평가에만 있던 방식을 서비스에 적용한다.
- 작업 전 상태: `/api/match` 는 Chroma 의미 검색만 사용. BM25·RRF 는 `eval/` 안에만 있었다.
- 변경 파일: `search/hybrid.py`(신규, BM25+RRF 를 서비스와 평가가 공유), `eval/bm25.py`(연결만 남김),
  `eval/evaluate.py`(rrf 계산을 `hybrid.rrf` 로 교체), `search/app.py`(서버 시작 시 BM25 색인,
  기본 검색 hybrid, `search='dense'` 로 이전 방식 사용 가능), `web/app.html`(소요 시간 표시).
- 전후 차이·선택 이유: 서비스와 평가가 같은 코드를 쓰게 해 평가 수치와 실제 동작이 어긋나지 않게 했다.
  응답 형식은 유지하고 `dense_rank`·`bm25_rank`·`rrf_score` 만 추가했다.
- 검증(2026-09-17, 공고 2,198건):
  - 평가 질의 60개에 대해 서비스 `/api/match` 와 `eval/evaluate.py` 의 상위 10 순서가 60/60 일치.
  - 정상 52질의(LLM 잠정 판정): P@3(2) dense 0.500 → rrf 0.635, 짝지은 차이 +0.135(95% +0.038~+0.224).
  - 속도 실측: BM25 색인 0.4초(서버 시작 1회), 검색 의미 5ms·단어 15ms(60질의 평균, 작업 PC).
- 미검증·남은 문제: BM25 색인은 서버 시작 시 만들어 배치 후 재시작 전까지 새 공고가 반영되지 않는다.
  EC2 에서의 메모리·속도는 측정하지 않았다.
- 다음 단계: 배치 후 서버 재시작 방법을 정한다.

### 2026-09-18 · Codex · 공용 작업 기록 체계 구축

- 요청·목적: 사용자가 Claude와 Codex 등 여러 AI의 작업 흐름을 함께 추적하도록 공용 규칙·현재 상태·변경 이력을 요청했다.
- 작업 전 상태: 폴더 정리 및 검색 기능 확장으로 다수의 이동·수정·미추적 파일이 있었다.
  기존 `FLOW.md`와 `HANDOFF.md`는 존재했으나 이 폴더의 `AGENTS.md`, `CLAUDE.md`, `STATUS.md`, `WORKLOG.md`는 없었다.
- 변경 파일:
  - `AGENTS.md`: 시작·진행·종료 절차, 기록 기준, 동시 작업 시 보존 원칙, 사용자 직접 커밋·push 규칙.
  - `CLAUDE.md`: 공통 규칙과 상태·이력 문서를 읽는 진입 안내.
  - `docs/STATUS.md`: 현재 코드 확인 내용, 기존 변경, 미검증 사항, 추후 검색 비교 요청을 기다리는 상태.
  - `docs/WORKLOG.md`: 공용 기록 양식과 이번 작업 이력.
  - `README.md`: 공용 기록 문서로 가는 안내.
  - `docs/FLOW.md`: 공용 기록으로 가는 안내 및 수집·검색 흐름의 읽기 시작점.
- 전후 차이·선택 이유: 대화창별로 흩어진 진행 상황을 저장소 파일에서 이어받을 수 있게 했다.
  규칙은 `AGENTS.md` 한 곳에서 관리하고, 최신 상태와 누적 이력을 분리했다.
- 검증: 공용 문서와 안내를 포함한 6개 Markdown 파일의 로컬 링크 32개가 모두 존재함을 확인했다.
  `git diff --check -- data-collection/README.md data-collection/docs/FLOW.md`도 통과했다.
  문서만 변경했으므로 수집·검색·DB·모델 실행 및 애플리케이션 테스트는 하지 않았다.
- 미검증·남은 문제: 기존 코드의 실행 성공 여부와 과거 문서 전체의 최신성은 검증하지 않았다.
  각 AI 도구의 자동 지침 로딩 여부도 검증하지 않았으며, 새 대화용 읽기 지시를 함께 제공했다.
- 다음 단계: 다음 실작업부터 시작 시 상태를 읽고, 진행·종료 시 기록을 갱신한다.
  임베딩 단독/하이브리드 검색 비교는 사용자가 요청하면 진행한다. Git 커밋·push는 실행하지 않았다.
