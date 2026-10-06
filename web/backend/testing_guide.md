# S-Brain 웹 백엔드 테스트 방법 (2026-10-06 개정, SB-247)

`web/backend/`에서 실행하는 걸 기준으로 정리했다. 웹은 이제 오케스트레이터(`agent-orchestration`의 `sbrain`)를 통해서만 실행 건을 만들고 읽는다 —
예전의 더미 파이프라인(`seed_dummy_pipeline.py`, `app/agents.py`)과 이를 쓰던 `verify_*.py` 스크립트는 없어졌다.

---

## 0. 사전 준비 (한 번만)

```
cd web/backend
python -m venv venv
venv\Scripts\activate        # (WSL/맥이면 source venv/bin/activate)
pip install -r requirements-dev.txt
pip install -e ../../agent-orchestration   # 오케스트레이터 계약 테스트용(없으면 계약 테스트만 건너뜀)
```

`.env.example`을 복사해서 `.env`로 만든다.

---

## 1. 자동 테스트 (pytest) — 서버 · 워커 · MySQL 없이

```
pytest -q
```

- `tests/conftest.py`가 `DB_BACKEND=sqlite`로 자동 전환하고 `test.db`(개발용 `dev.db`와 별도)를 매 세션 새로 만든다. 팀 공유 AWS MySQL에는 절대 접속하지 않는다.
- 모든 테스트에는 가짜 오케스트레이터(`tests/orch_fakes.py`의 `FakeOrch`)가 gateway로 끼워진다. 테스트가 `orch.responses['함수 이름']`으로 원하는 상태를 만들고 `orch.calls`로 어떤 함수를 어떻게 불렀는지 확인한다.
- `tests/test_orch_fake_contract.py`는 가짜 결과의 필드가 실제 `sbrain`과 같은지, gateway 허용 목록의 함수가 실제로 있는지 확인한다(`sbrain`이 설치돼 있어야 실행).
- 관리자(`tests/test_admin.py`), 재작성(`test_orch_rework.py`), 단계 시작(`test_orch_stages.py`), 결과(`test_orch_result.py`), 삭제 · 보관 규칙(`test_project_permanent_delete.py`, `test_account_deletion.py`, `test_proofread_retention.py`) 등이 있다.

---

## 2. 실제 워커 + MySQL로 끝까지 돌려 보기 (로컬)

SQLite 개발 모드에서는 오케스트레이터를 쓸 수 없어 프로젝트 생성 · 단계 시작 · 결과 조회가 503으로 답한다. 실제 흐름은 MySQL + 워커가 필요하다.
워커의 Agent 중 조율 T-C1 · T-C3만 실제 구현이고 나머지는 스텁이라(agent-orchestration README 1.3), 이 테스트는 "웹 ↔ 워커 배관과 흐름"을 확인한다(결과물 품질은 보지 않는다).

1. **로컬 MySQL** — Docker Desktop을 켜고 `agent-orchestration/`에서 `docker compose -f docker/mysql-test.yml up -d --wait`(127.0.0.1:3307, 데이터는 메모리에만 있음).
2. **스키마 준비** — `python scripts/prepare_local_mysql.py` : `sbrain_e2e` DB를 지우고 웹 스키마 + orch_ 표를 새로 만든다. 로컬 호스트의 e2e/test DB만 받는다(팀 공유 DB 거부).
3. **OpenAI 키** — `agent-orchestration/.env`의 `OPENAI_API_KEY`(`.env.example` 참고, 커밋되지 않음).
4. **워커** — `agent-orchestration/`에서 `SBRAIN_DB_URL=mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4`를 주고 `python -m sbrain.worker`.
   공고 서버 주소(`SBRAIN_NOTICE_API_URL`)가 없으면 스텁 공고 · 스텁 자격 판정으로 돈다.
5. **E2E** — `python scripts/e2e_worker_flow.py [--rework] [--cleanup]` : 프로젝트 생성 → 공고 후보 → 공고 선택 → 계획서 → 프로토타입 → 종합 평가 → (재작성) → 표현 검수 → 결과 → (영구 삭제)를 워커가 처리하길 기다리며 단계마다 `[OK]/[FAIL]`로 찍는다.

- **동시 실행 제한 · 중단 (SB-260)** — 같은 준비(1~5) 뒤 `python scripts/e2e_concurrent_abort.py` : 요청 처리 중 · 실행 건이 있을 때의 새 프로젝트 409, 휴지통 중단 뒤 제한 해제, 요청 처리 중 · 단계 진행 중 중단까지 5개 시나리오를 한 계정으로 차례로 본다. 중단이 어느 경로(바로 중단 · 요청 취소 · 중단 요청 후 단계 사이 반영)를 탔는지까지 확인한다. 끝나도 진행 중인 작업은 남지 않아 DB를 다시 준비하지 않고 바로 다시 돌려도 된다(보관된 프로젝트만 쌓인다).

- **재개 · 실패 경로 (SB-261)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_failure_resume.py` : 이 스크립트가 워커를 같은 프로세스에서 직접 돌리며 스텁 Agent에 시간 초과 · 공고 서버 오류 · 잘못된 요청을 끼워 넣는다(워커가 따로 떠 있으면 끈다 — 같은 DB를 두 워커가 가져가면 시험이 틀어진다). 사전 단계 실패, 공고 선택 실패 후 재시도, 화면 5에서 다시 고른 공고 실패(SB-275 — `GET /eligibility?notice_id=`), 일시 오류 → 재개 → 성공, 재개 상한 초과 → 실패(관리자 알림 · 사용자 알림), 영구 오류 → 즉시 실패를 본다. **재작성 실패 경로(SB-277)**도 본다 — 화면 6에서 재작성이 영구 오류 · 재개 상한 초과로 실패하면 실행은 실패가 아니고(화면 6 그대로) 계획서가 요청 전과 같고 재작성 기회가 돌아오며 실패 알림(재작성)이 한 건 생기고 `E-RUN-ROLLBACK`이 오는지, 기회가 돌아와 다시 재작성하면 성공하는지. 재시도 · 재개 간격을 짧게 줄여 몇 분 안에 끝난다. 조율 T-C1 · T-C3는 실제 LLM이라 OpenAI 키가 필요하다.

- **삭제 · 탈퇴와 BUSY (SB-259)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_delete_withdraw.py` : 같은 프로세스에서 워커를 돌리며 계획서 작성 호출을 붙잡아 "단계를 도는 중"을 만든다. 영구 삭제(쉬는 중 · BUSY 409 → 재시도), 탈퇴(프로젝트 2개 중 하나가 진행 중일 때 BUSY → 재시도, 웹 행 · 산출물 · 실행 건 · 통계 줄), 탈퇴 뒤 재가입, 시작 요청 처리 중 탈퇴를 본다. 다시 돌려도 된다(계정이 매번 새로 만들어진다).

- **학습 동의 · 검수 회수 문단 (SB-262)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_training_consent.py` : 워커를 같은 프로세스에서 돌리며 검수 스텁이 일부 문장을 반려하게 만들고, 동의한 계정에서 `proofread_logs`에 행이 쓰이는지, 관리자 라벨링 · 학습 반영(trained) 표시, 동의 철회 · 영구 삭제 · 탈퇴 때 반영 전 행만 지워지고 trained 행은 연결만 끊겨 남는지, 검수 시작 전에 동의를 철회하면 행이 안 쓰이는지를 본다. 프로젝트를 끝까지 세 번 돌려 2분쯤 걸린다. 다시 돌려도 된다(trained 행은 연결이 끊긴 채 남는다).

- **마이그레이션 리허설 (SB-265)** — 로컬 MySQL만 있으면 된다(워커 불필요) `python scripts/rehearse_migration.py` : 옛 웹 스키마(기본 git `origin/main`의 `app_schema.sql`)로 DB를 만들고 시드 데이터를 넣은 뒤 `migrations/001` → `002`를 적용해 더미 표 13개가 사라지고 데이터(사용자 · 프로젝트 · 알림 · 실패 알림 · 검수 기록)가 그대로인지, `proofread_logs`의 `project_id`가 채워졌는지, 두 마이그레이션을 다시 적용해도 오류가 없는지(멱등), 결과 스키마가 새 `app_schema.sql`과 같은지(표 · 열 형식 · NULL · 기본값 · 인덱스 · 외래 키)를 본다. **공유 DB 사본이 없어 옛 스키마를 git(main)으로 대신한 것**이라, 사본이 생기면 `mysqldump --no-data`로 뜬 스키마를 `--old-schema-file`로 넣어 같은 리허설을 다시 돈다. `--keep`으로 두 DB(`sbrain_test_mig_old` · `_new`)를 남겨 그 위에서 워커 E2E를 돌릴 수도 있다.

- **부하 · 타임아웃 (SB-266)** — 1~4 준비 뒤 **워커를 띄우지 않고** `python scripts/load_check.py` : 워커가 응답하지 않을 때 후보 · 자격 확인 조회가 쌓이면 다른 요청이 막히는지를 서버를 실제로 띄워 HTTP로 잰다(단계별 동시 대기 5 · 15 · 30 · 60개, 그동안 DB를 쓰는 `/auth/me`와 안 쓰는 `/docs`의 지연). 느려지면 종료 코드 1이다. 아래 "부하 · 타임아웃" 참고.

- **사업자 입력 (SB-296)** — 1~4 준비와 워커를 띄운 뒤(e2e_worker_flow.py와 같다) `python scripts/e2e_business_applicant.py` : 개인사업자 · 법인 입력으로 자격 확인 응답의 `business_age_years`가 설립일에서 계산한 값(오케스트레이터와 같은 계산)으로 오고 `can_start_writing`이 통과 여부와 같은지, POST · GET `/eligibility`가 같은지를 본다. 설립일 없는 사업자는 `E-C1-REQUIRED`(설립일자)로 거절되고 프로젝트가 남지 않는지, 예비창업자는 업력이 `None`인지도 본다. 개인사업자 · 법인의 주업종은 드롭다운 9종만 받는다(다른 값은 422).

- **관리자 화면 (SB-263)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_admin.py` : 워커를 같은 프로세스에서 돌리며 상태가 다른 프로젝트 네 개(매칭 전 · 실패 · 완료(재작성 포함) · 진행중)를 만들고, 진행 현황 · 정체 · 이력보기 · 보관/복원 · 에이전트 실행 기록 · Task별 보기 · 운영 지표 · 알림 · 사용자 정지 · 체크리스트를 부른다. 숫자는 오케스트레이터 표를 직접 센 값과 맞추고, 관리자 설정(합격선 · 재작성 횟수)이 새 실행에 반영되는지와 일반 사용자의 접근 거부(403)도 본다. 바꾼 설정은 끝에 원래대로 돌린다. 2분쯤 걸리고 다시 돌려도 된다.

- **스크립트를 반복해서 돌릴 때** — E2E 스크립트는 대부분 같은 로컬 계정(`e2e@example.com`)을 쓰고 실행마다 프로필 슬롯을 하나씩 만든다(`e2e_delete_withdraw.py`는 탈퇴로 계정이 지워져 제외). 계정당 프로필은 3개까지라 같은 DB에서 3번 넘게 돌리면 `POST /profile`이 409로 답하고 스크립트가 첫 단계에서 멈춘다. 이때는 2번(`prepare_local_mysql.py`)을 다시 실행해 DB를 초기화한다. 워커를 따로 띄워 둔 채 초기화하면 남은 요청을 워커가 가져가 시험이 틀어지므로 워커를 끄고 → 초기화 → 워커를 다시 띄운다.

### 브라우저(프론트)로 돌려 보기

위 스크립트는 웹을 `TestClient`로 부르고 구글 로그인을 코드에서 가짜로 바꿔 두므로, 프론트 화면으로 처음부터 끝까지 보려면 웹 서버를 직접 띄워야 한다. 1~4(MySQL · 스키마 · OpenAI 키 · 워커)를 마친 뒤 `web/backend`에서:

```
DB_BACKEND=mysql MYSQL_USER=root MYSQL_PASSWORD=sbrain-test MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 MYSQL_DATABASE=sbrain_e2e \
SBRAIN_DB_URL="mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4" \
JWT_SECRET=아무값 GOOGLE_CLIENT_ID=<프론트가 로컬 개발에 쓰는 구글 클라이언트 ID> \
uvicorn app.main:app --port 8000
```

(PowerShell이면 `$env:이름='값'`으로 먼저 지정한다.) CORS는 `localhost:5174` · `127.0.0.1:5174`를 허용한다. 서버 기동(`/docs` 200)과 비로그인 요청의 401 응답까지는 확인했고, 구글 로그인으로 들어가 단계를 끝까지 도는 것은 브라우저로 아직 확인하지 않았다. 로그인은 `GOOGLE_CLIENT_ID`로 구글 토큰을 검증하며 개발용 로그인은 없다.

### 오류 응답 형식 (SB-273)

모든 오류 응답은 `{"detail": ..., "code": "..."}`다. `detail`은 화면에 보이는 문구(문자열)이거나, 확인 요청 · 진행 중 작업 안내처럼 객체이고, `code`로 분기한다.

| code | 어디서 | 상태 |
|---|---|---|
| 오케스트레이터 코드 그대로(`BUSY` · `ANNOUNCEMENT_BLOCKED` · `E-G2-LIMIT` · `RUN_NOT_VIEWABLE` · `INVALID_STATE` …) | 오케스트레이터가 거절한 요청 | 404 · 409 · 422 |
| `E-RUN-CONCURRENT` | 진행 중인 작업이 있을 때 새 프로젝트(`detail`에 `active_project_id` · 단계 · 화면) | 409 |
| `CONFIRMATION_REQUIRED` | `review/start`에서 기준 점수 미달 확인(`detail.confirmation_required` · `reason` · `items`) | 409 |
| `E-AUTH-CONSENT` · `E-AUTH-PROFILE` · `E-C1-REQUIRED` | 필수 동의 · 프로필 · 필수 입력 누락 | 403 · 403 · 422 |
| `ACCOUNT_WITHDRAWING` | 탈퇴 중인 계정이 새 프로젝트를 시작하려 할 때(`POST /projects`) · 시작 실패 뒤 후보를 다시 읽을 때(`GET …/match-candidates`는 `status='failed'`로 같은 code) (SB-298) | 409 |
| `NOTICE_REQUIRED` · `STAGE_NOT_REACHED` · `PLAN_NOT_READY` · `NOT_REWORKABLE` · `NOT_REWORKED_YET` | 웹이 직접 내는 단계 · 입력 오류 | 400 · 404 · 422 |
| `UNAUTHORIZED` · `FORBIDDEN` · `NOT_FOUND` · `VALIDATION_ERROR` · `INTERNAL_ERROR` 등 | 그 밖의 오류(상태 코드별 기본 이름) | 401 · 403 · 404 · 422 · 500 |

`WEB_NOT_ALLOWED` · 모르는 오케스트레이터 코드 같은 내부 오류는 내부 이름을 내지 않고 `INTERNAL_ERROR`(500)로 답한다.

### 부하 · 타임아웃 (SB-266)

후보 · 자격 확인 조회는 워커가 끝내길 최대 25초(`ORCH_WAIT_TIMEOUT_SEC`) 기다린 뒤 `pending`으로 답한다. 이 동안 요청 하나가 서버 작업 스레드와 DB 연결을 하나씩 쓴다. 워커가 느리거나 멈추면 이런 요청이 쌓인다.

`scripts/load_check.py`(워커 없음)로 측정한 결과 — 동시 대기 요청을 늘리며 DB를 쓰는 가벼운 요청(`/auth/me`)의 최대 지연(초):

| 동시 대기 | 수정 전 | 수정 후 |
|---|---|---|
| 5 | 0.1 | 0.0 |
| 15 | **6.1** | 0.2 |
| 30 | **12.2** | 0.3 |
| 60 | **36.6** (대기 요청 30개가 풀 시간 초과 500) | 0.4 (60개 모두 200) |

- **원인 1 — DB 연결**: 요청의 DB 세션이 쿼리를 한 번 하면 요청이 끝날 때까지 연결을 붙잡는다. 대기 동안에도 쥐고 있어 웹 DB 연결 풀(기본 5 + 초과 10 = 15개)이 대기 요청으로 찼다. 이제 대기 전에 `db.rollback()`으로 연결을 돌려준다(`projects._release_db`, `tests/test_db_connection_during_wait.py`).
- **원인 2 — 서버 작업 스레드**: 동기 엔드포인트는 anyio 스레드 풀(기본 40개)에서 돈다. 대기 요청이 40개를 넘으면 DB를 안 쓰는 동기 요청까지 줄을 선다(한도 40으로 되돌려 측정: 동시 대기 60에서 6.8초). 한도를 올려 둔다 — 환경변수 `WEB_THREAD_LIMIT`(기본 200).
- 워커가 정상이면 대기는 짧게 끝나 이 문제가 드러나지 않는다. 운영에서 워커 장애 때 웹 전체가 멈추지 않게 하려는 수정이다.
- 아직 점검하지 않은 것: 워커가 살아 있는 상태의 동시 사용자 수(조율이 실제 LLM이라 비용이 든다), 웹 서버를 여러 프로세스로 띄웠을 때의 DB 연결 총합(프로세스 수 × 15개 + 오케스트레이터 연결이 DB `max_connections`를 넘지 않는지), 프록시 · 게이트웨이 제한 시간(25초 대기가 그 안에 끝나는지). 배포 구성이 정해지면 확인한다.

### 응답 시각 (SB-264)

응답의 시각은 모두 **UTC · 끝에 `Z`**다(`2026-10-06T07:14:59Z`, 명세 11.1). 웹 표(DB)에서 읽은 시각은 시간대 표시가 없는 UTC(`utcnow()` · `CURRENT_TIMESTAMP`)라 응답 스키마(`schemas.UtcDatetime`)가 `Z`를 붙여 내보낸다. 화면의 한국 시간 변환은 프론트(`time.js`)가 한다.

- **DB 서버의 시간대가 UTC여야 한다.** `server_default=CURRENT_TIMESTAMP`로 쓰는 열(`created_at` 등)은 DB 시계를 쓴다. 서버가 UTC가 아니면 표시가 그만큼 어긋난다. 확인: `SELECT @@global.time_zone, @@session.time_zone, TIMEDIFF(NOW(), UTC_TIMESTAMP());` — 마지막 값이 `00:00:00`이어야 한다. 로컬 Docker MySQL은 UTC다(확인함). **공유 DB(AWS)는 접속 권한이 있는 사람이 위 쿼리로 확인해야 한다.**
- `scripts/e2e_worker_flow.py`가 프로젝트 · 알림 시각이 `Z`이고 실제 UTC 시계와 맞는지 본다(개발 컴퓨터가 한국 시간이어도 9시간 어긋나면 실패한다). `tests/test_utc_timestamps.py`는 형식(`Z` · 마이크로초 · 다른 시간대 → UTC)과 API 응답을 본다.
- 로그 파일의 앞쪽 시각은 서버 로컬 시간이다. 워커 로그(UTC)와 맞출 때는 웹 명령 로그의 `at=`(UTC)를 본다.

### 웹 명령 로그 (SB-303)

웹이 오케스트레이터에 넣은 상태 변경 명령(`request_start` · `abort_project` · `decide_for_project` 등 9개)은 끝날 때마다 웹 로그(`web/backend/logs/web-날짜.log`)에 `cmd`로 시작하는 한 줄을 남긴다. 워커 로그에 줄이 없는 웹 쪽 상태 변경(대기 지점 중단 · 화면 8 진행 …)을 워커 로그와 맞춰 보려는 것이다.

```
2026-10-06 16:14:59 | INFO    | cmd at=2026-10-06T07:14:59Z project_id=1 command=abort_project result=ok run_action=중단 step=공고선택 progress=중단 elapsed_ms=94
```

- `at`은 UTC(`Z`)다. 줄 앞의 시각은 서버 로컬 시간이라, 워커 로그(UTC)와 맞출 때는 `at`을 본다.
- `result`는 `ok` · `rejected`(시작 요청 거절) · `confirmation_required` · `error`(`code=오케스트레이터 오류 코드`) · `fail`(예상 못 한 예외)이다. `step` · `progress`는 명령 직후의 값이다.
- 계정 번호 · 산출물 · 입력 내용은 남기지 않는다. 읽기 함수(`view_project` · `screen` · `outputs` …)는 남기지 않는다.
- `scripts/e2e_worker_flow.py`(화면 8 진행)와 `scripts/e2e_concurrent_abort.py`(중단)가 로그 파일에 줄이 남았는지 확인한다.

기존 DB에 스키마 변경을 적용하는 SQL은 `migrations/`에 있다(멱등, MySQL 8). 공유 DB 적용은 팀 합의 뒤에 한다.

---

## 3. 그 밖의 검증 스크립트

- `python tests/verify_profile_mysql_local.py` — 마이페이지 프로필 API를 로컬 MySQL에서 확인한다.
- 계획서 `.hwp` 내려받기는 `RHWP_BIN` 설정이 필요하다 — `scripts/README.md` 참고. 서버를 켠 뒤 Swagger(`/docs`)에서 `GET /projects/{id}/plan-document.hwp`를 직접 호출해도 된다.
