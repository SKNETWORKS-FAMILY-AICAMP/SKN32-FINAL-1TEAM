# S-Brain 웹 백엔드 테스트 방법 (2026-10-11 개정, SB-334)

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
- 사업비 · 추진 일정 입력(SB-327)은 `test_budget_phase_column.py`(phase 컬럼), `test_budget_schedule_schema.py`(요청 · 응답 모양), `test_budget_schedule_validation.py`(입력 검사 · 오류 위치), `test_budget_schedule_saving.py`(저장 순서 · 커밋 시점 · 정리), `test_budget_schedule_required.py`(필수 확인 · 스위치)가 본다. 아래 "사업비 · 추진 일정 입력"을 보라.
- 테스트 파일별로 무엇을 확인하는지는 [`unit_test_doc.md`](unit_test_doc.md)에 정리돼 있다(테스트를 추가하면 그 표도 같이 고친다).
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
5. **E2E** — `python scripts/e2e_worker_flow.py [--rework] [--cleanup]` : 프로젝트 생성 → 공고 후보 → 공고 선택 → 계획서 → 프로토타입 → 종합 평가 → (재작성) → 표현 검수 → 결과 → (영구 삭제)를 워커가 처리하길 기다리며 단계마다 `[OK]/[FAIL]`로 찍는다. 계획서 항목 구조(SB-335)도 본다 — 응답이 항목 번호 · 태그 · 종류를 따로 주는지, 점수 항목 `item_code`가 항목 번호와 맞는지, 그림 주소가 받아지는지, 재작성(`--rework`) 전후와 표현 검수 전후에 항목 구성(번호 · 태그 · 종류)과 그림이 그대로인지. **재작성이 고른 묶음(문제인식 = 태그 `1-1`)의 항목만 바꾸는지 · 바뀐 항목의 `tag` · `title`**은 문장이 실제로 바뀌어야 볼 수 있는데 스텁 작성 Agent는 다시 써도 문장이 같아, 바뀐 항목이 없으면 `[건너뜀]`으로 찍고 확인하지 않는다(통과로 세지 않음 — 실제 Agent로 돌릴 때 확인한다, SB-342).

- **동시 실행 제한 · 중단 (SB-260)** — 같은 준비(1~5) 뒤 `python scripts/e2e_concurrent_abort.py` : 요청 처리 중 · 실행 건이 있을 때의 새 프로젝트 409, 휴지통 중단 뒤 제한 해제, 요청 처리 중 · 단계 진행 중 중단까지 5개 시나리오를 한 계정으로 차례로 본다. 중단이 어느 경로(바로 중단 · 요청 취소 · 중단 요청 후 단계 사이 반영)를 탔는지까지 확인한다. 끝나도 진행 중인 작업은 남지 않아 DB를 다시 준비하지 않고 바로 다시 돌려도 된다(보관된 프로젝트만 쌓인다).

- **재개 · 실패 경로 (SB-261)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_failure_resume.py` : 이 스크립트가 워커를 같은 프로세스에서 직접 돌리며 스텁 Agent에 시간 초과 · 공고 서버 오류 · 잘못된 요청을 끼워 넣는다(워커가 따로 떠 있으면 끈다 — 같은 DB를 두 워커가 가져가면 시험이 틀어진다). 사전 단계 실패, 공고 선택 실패 후 재시도, 화면 5에서 다시 고른 공고 실패(SB-275 — `GET /eligibility?notice_id=`), 일시 오류 → 재개 → 성공, 재개 상한 초과 → 실패(관리자 알림 · 사용자 알림), 영구 오류 → 즉시 실패를 본다. **재작성 실패 경로(SB-277)**도 본다 — 화면 6에서 재작성이 영구 오류 · 재개 상한 초과로 실패하면 실행은 실패가 아니고(화면 6 그대로) 계획서가 요청 전과 같고 재작성 기회가 돌아오며 실패 알림(재작성)이 한 건 생기고 `E-RUN-ROLLBACK`이 오는지, 기회가 돌아와 다시 재작성하면 성공하는지. 재시도 · 재개 간격을 짧게 줄여 몇 분 안에 끝난다. 조율 T-C1 · T-C3는 실제 LLM이라 OpenAI 키가 필요하다.

- **삭제 · 탈퇴와 BUSY (SB-259)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_delete_withdraw.py` : 같은 프로세스에서 워커를 돌리며 계획서 작성 호출을 붙잡아 "단계를 도는 중"을 만든다. 영구 삭제(쉬는 중 · BUSY 409 → 재시도), 탈퇴(프로젝트 2개 중 하나가 진행 중일 때 BUSY → 재시도, 웹 행 · 산출물 · 실행 건 · 통계 줄), 탈퇴 뒤 재가입, 시작 요청 처리 중 탈퇴를 본다. 다시 돌려도 된다(계정이 매번 새로 만들어진다).

- **산출물 파일 (SB-295 · SB-320)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_artifact_files.py` : 워커를 같은 프로세스에서 돌리고 파일 저장소(`SBRAIN_ARTIFACT_ROOT`, 스크립트가 임시 폴더로 잡는다 — 웹과 워커가 같은 폴더를 본다)에 스텁 구현 Agent가 만든 자리채움 파일(`index.html` · `onepage.svg` · `infographic.svg` · `README.md` · `plan.docx`)로 흐름을 본다. 결과의 두 경로가 key 기반 웹 주소인지(SB-314), 받은 파일이 저장소 파일과 바이트가 같은지 · 헤더 · 형식(SB-315), 비로그인 401 · 다른 계정 · 관리자 · 바꾼 key · 경로 이동 · 다른 프로젝트 번호 404, 실행 파일 재작성의 전후 주소와 이전 파일 보존, 종합 평가 · 표현 검수를 마친 뒤 결과물 zip(SB-316), 영구 삭제 · 탈퇴 뒤 관리자 삭제 대기열에 줄이 생기고(SB-318) 워커가 처리하면 저장소 파일이 지워지는지(대기 10분은 이 시험에서만 0으로 줄인다), 원페이지의 두 참조(같은 `onepage.svg`)를 본다. 조율 T-C1이 실제 LLM이라 카테고리를 스스로 고르므로 스크립트가 웹개발 · 원페이지를 강제한다. 스텁 파일은 자리채움이라 내용 품질은 보지 않는다. 계정은 매번 새로 만들어져(탈퇴로 지워짐) 다시 돌려도 된다. 2분쯤 걸린다. 따로 띄운 워커로 `e2e_worker_flow.py`를 돌릴 때는 워커와 이 스크립트에 같은 `SBRAIN_ARTIFACT_ROOT`를 준다(워커는 이 값이 없으면 시작하지 않는다).
- **학습 동의 · 검수 회수 문단 (SB-262)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_training_consent.py` : 워커를 같은 프로세스에서 돌리며 검수 스텁이 일부 문장을 반려하게 만들고, 동의한 계정에서 `proofread_logs`에 행이 쓰이는지, 관리자 라벨링 · 학습 반영(trained) 표시, 동의 철회 · 영구 삭제 · 탈퇴 때 반영 전 행만 지워지고 trained 행은 연결만 끊겨 남는지, 검수 시작 전에 동의를 철회하면 행이 안 쓰이는지를 본다. 프로젝트를 끝까지 세 번 돌려 2분쯤 걸린다. 다시 돌려도 된다(trained 행은 연결이 끊긴 채 남는다).

- **마이그레이션 리허설 (SB-265)** — 로컬 MySQL만 있으면 된다(워커 불필요) `python scripts/rehearse_migration.py` : 옛 웹 스키마(기본 git `origin/main`의 `app_schema.sql`)로 DB를 만들고 시드 데이터를 넣은 뒤 `migrations/001` → `002` → `004`(SB-328, `project_budget_items.phase` 추가 — 003은 `feature/sb-269-web-final`에만 있어 병합 뒤 002와 004 사이에 넣는다)를 적용해 더미 표 13개가 사라지고 사업비 행의 `phase`가 NULL로 남고 데이터(사용자 · 프로젝트 · 알림 · 실패 알림 · 검수 기록)가 그대로인지, `proofread_logs`의 `project_id`가 채워졌는지, 마이그레이션을 다시 적용해도 오류가 없는지(멱등), 결과 스키마가 새 `app_schema.sql`과 같은지(표 · 열 형식 · NULL · 기본값 · 인덱스 · 외래 키)를 본다. **공유 DB 사본이 없어 옛 스키마를 git(main)으로 대신한 것**이라, 사본이 생기면 `mysqldump --no-data`로 뜬 스키마를 `--old-schema-file`로 넣어 같은 리허설을 다시 돈다. `--keep`으로 두 DB(`sbrain_test_mig_old` · `_new`)를 남겨 그 위에서 워커 E2E를 돌릴 수도 있다.

- **부하 · 타임아웃 (SB-266)** — 1~4 준비 뒤 **워커를 띄우지 않고** `python scripts/load_check.py` : 워커가 응답하지 않을 때 후보 · 자격 확인 조회가 쌓이면 다른 요청이 막히는지를 서버를 실제로 띄워 HTTP로 잰다(단계별 동시 대기 5 · 15 · 30 · 60개, 그동안 DB를 쓰는 `/auth/me`와 안 쓰는 `/docs`의 지연). 느려지면 종료 코드 1이다. 아래 "부하 · 타임아웃" 참고.

- **사업자 입력 (SB-296)** — 1~4 준비와 워커를 띄운 뒤(e2e_worker_flow.py와 같다) `python scripts/e2e_business_applicant.py` : 개인사업자 · 법인 입력으로 자격 확인 응답의 `business_age_years`가 설립일에서 계산한 값(오케스트레이터와 같은 계산)으로 오고 `can_start_writing`이 통과 여부와 같은지, POST · GET `/eligibility`가 같은지를 본다. 설립일 없는 사업자는 `E-C1-REQUIRED`(설립일자)로 거절되고 프로젝트가 남지 않는지, 예비창업자는 업력이 `None`인지도 본다. 개인사업자 · 법인의 주업종은 드롭다운 9종만 받는다(다른 값은 422).

- **관리자 화면 (SB-263)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_admin.py` : 워커를 같은 프로세스에서 돌리며 상태가 다른 프로젝트 네 개(매칭 전 · 실패 · 완료(재작성 포함) · 진행중)를 만들고, 진행 현황 · 정체 · 이력보기 · 보관/복원 · 에이전트 실행 기록 · Task별 보기 · 운영 지표 · 알림 · 사용자 정지 · 체크리스트를 부른다. 숫자는 오케스트레이터 표를 직접 센 값과 맞추고, 관리자 설정(합격선 · 재작성 횟수)이 새 실행에 반영되는지와 일반 사용자의 접근 거부(403)도 본다. 관리자 배점(60 · 10 · 30)을 바꾼 뒤 시작한 실행 건에서 층 만점 · 코드 점검 줄의 합 · 관리자 진행 현황 · 점수 이력의 만점이 그 실행 건 배점으로 오는지, 시작 뒤 배점을 다시 바꿔도 그대로인지, 배점 0은 합이 100이어도 422인지도 본다(문서층은 스텁 문서 점수 52가 들도록 60 이상으로 둔다). 바꾼 설정은 끝에 원래대로 돌린다. 2분쯤 걸리고 다시 돌려도 된다.

- **사업비 · 추진 일정 (SB-333)** — 1~4 준비 뒤 `python scripts/e2e_budget_schedule.py` : 예비창업 · 법인 입력으로 사업비 · 일정이 두 표에 보낸 순서(`item_order`) · 단계(`phase`) · 구분(`section`)과 함께 저장되고, 실제 오케스트레이터가 `request_start`에서 읽어 시작 요청(`orch_start_requests.form_json`)에 같은 사업비 · 일정을 단계 · 범위(`agreement` · `roadmap`)와 함께 담는지 본다. 이어서 오케스트레이터 스위치(`PLAN_TABLES_REQUIRED`)와 웹 스위치(`REQUIRE_BUDGET_SCHEDULE`)를 프로세스 안에서 켜고 끄며 필수 확인이 두 곳에서 같은 `missing` 이름으로 거절하는지(웹이 먼저, 오케스트레이터는 부르지 않음), 협약 이후 일정이 없어도 통과하는지, 예비창업 2단계만 빠지면 `사업비 집행계획(2단계)`로 거절하는지 확인한다(19단계). **워커는 필요 없다**(시작 요청까지만 보고, 대기 요청은 케이스마다 휴지통 삭제로 취소). 오케스트레이터가 이 두 표를 읽는 코드는 SB-310에 있어 **최신 SB-304를 합친 트리**에서 돌려야 한다. 시작 요청 뒤 T-C1 · 전략 · 작성 Agent가 이 값을 쓰는지는 워커와 LLM이 있어야 보이므로 실제 Agent를 연결한 뒤 다시 본다.
- **실제 OpenAI 없이 돌리기 (SB-343)** — 워커를 같은 프로세스에서 돌리는 스크립트(`e2e_artifact_files` · `e2e_admin` · `e2e_delete_withdraw` · `e2e_failure_resume` · `e2e_training_consent`)는 환경 변수 `E2E_STUB_PARTNER=1`을 주면 전략 · 작성 · 검증-1(T-S1 · T-S2 · T-W1 · T-W2 · T-W3 · T-V1)과 구현 · 검증-2(T-B1 · T-B2 · T-V2)를 실구현 대신 스텁으로 둔다(`e2e_worker_flow.use_stub_partner_agents` — 워커 조립이 실구현을 끼우는 곳을 비운다). 실구현은 OpenAI(LLM · 이미지)를 많이 불러(전략 · 작성 · 검증-1만 한 건에 약 76번 · 약 8분 30초) 시간 · 비용이 든다. 조율 T-C1 · T-C3는 그대로 실제 LLM이라 키가 필요하지만 호출은 몇 번뿐이다. 스텁 계획서는 모양(항목 번호 · 그림)만 같고 내용은 자리채움이라 "웹 ↔ 워커 배관 · 파일 · 문서 내려받기"만 확인한다. 실제 Agent 품질까지 보려면 이 변수를 빼고 돌린다(비용 · 시간 주의). 따로 띄운 워커를 쓰는 스크립트(`e2e_worker_flow` · `e2e_concurrent_abort` · `e2e_business_applicant`)는 워커를 `python -m sbrain.worker` 대신 `python scripts/stub_worker.py`로 띄운다(같은 환경 변수 `SBRAIN_DB_URL` · `SBRAIN_ARTIFACT_ROOT`, `E2E_STUB_PARTNER`는 같은 프로세스 워커에만 듣는다).
- **실제 호출에 의존하는 E2E가 시간 초과로 실패할 때** — 워커를 같은 프로세스에서 돌리는 E2E(`e2e_artifact_files` · `e2e_admin` · `e2e_delete_withdraw` · `e2e_failure_resume` · `e2e_training_consent`)와 따로 띄운 워커를 쓰는 E2E는 조율 T-C1 · T-C3가 실제 OpenAI를 부르므로, 호출이 시간 안에 끝나지 않으면 사전 단계가 `E-C1-TIMEOUT`으로 실패하고 스크립트가 "공고 후보를 못 받음"으로 멈춘다(2026-10-12 한 번의 전체 실행에서 4종이 이렇게 실패했고, 같은 스크립트를 다시 돌리자 모두 통과했다). 코드 문제가 아니라 외부 호출 지연으로 보이면 `prepare_local_mysql.py`로 DB를 초기화한 뒤 그 스크립트만 다시 돌린다.
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
| `E-AUTH-CONSENT` · `E-AUTH-PROFILE` · `E-C1-REQUIRED` | 필수 동의 · 프로필 · 필수 입력 누락. `E-C1-REQUIRED`는 오케스트레이터의 필수 확인과 웹의 사업비 · 일정 필수 확인(SB-332, `REQUIRE_BUDGET_SCHEDULE`을 켰을 때)이 같은 모양(`detail.missing`)으로 낸다 | 403 · 403 · 422 |
| `ACCOUNT_WITHDRAWING` | 탈퇴 중인 계정이 새 프로젝트를 시작하려 할 때(`POST /projects`) · 시작 실패 뒤 후보를 다시 읽을 때(`GET …/match-candidates`는 `status='failed'`로 같은 code) (SB-298) | 409 |
| `NOTICE_REQUIRED` · `STAGE_NOT_REACHED` · `PLAN_NOT_READY` · `NOT_REWORKABLE` · `NOT_REWORKED_YET` | 웹이 직접 내는 단계 · 입력 오류 | 400 · 404 · 422 |
| `UNAUTHORIZED` · `FORBIDDEN` · `NOT_FOUND` · `VALIDATION_ERROR` · `INTERNAL_ERROR` 등 | 그 밖의 오류(상태 코드별 기본 이름) | 401 · 403 · 404 · 422 · 500 |

`WEB_NOT_ALLOWED` · 모르는 오케스트레이터 코드 같은 내부 오류는 내부 이름을 내지 않고 `INTERNAL_ERROR`(500)로 답한다.

### 사업비 · 추진 일정 입력 (SB-327)

사전 정보 입력의 사업비 집행계획 · 추진 일정을 `POST /projects`(payload)로 받아 `project_budget_items` · `project_schedule_items`에 저장한다. 오케스트레이터가 `request_start` 때 이 두 표를 직접 읽는다(웹이 `formInput`으로 보내지 않는다). 단위 테스트는 가짜 오케스트레이터로 확인하고, 실제 오케스트레이터가 저장한 행을 읽는지는 `scripts/e2e_budget_schedule.py`(SB-333)가 확인한다 — 아래 "그 밖의 검증 스크립트".

- **모양** — 요청 payload와 `GET /projects/{id}` 응답에 같은 이름으로 `budget_items[]`(`phase` · `category` · `execution_plan` · `total_amount` · `government_amount` · `self_cash_amount` · `self_in_kind_amount`)와 `schedule_items[]`(`section` · `category` · `content` · `period` · `detail`)가 있다. 순서는 보낸 배열 순서(`item_order` 1부터)이고, 한 목록은 50줄까지다. `section`은 `feasibility`(협약기간 내) · `growth`(협약 이후 전체), `phase`는 `'1단계'` · `'2단계'`다. 금액은 원 단위 정수다.
- **입력 검사(422 `VALIDATION_ERROR`)** — 금액 네 칸 필수(0 허용, 총사업비만 1 이상, 음수 · 999,999,999,999원 초과 거부), `총사업비 = 정부지원 + 자기부담 현금 + 현물`, 비목 · 집행계획 필수, 일정은 구분 · 추진내용 · 추진기간 필수(세부내용은 비우면 `''`)에 추진기간에 연도 필수. 예비창업자는 줄마다 `phase`가 필요하고 자기부담은 현금 하나(현물 0), 개인사업자 · 법인은 `phase`가 없다. **오류 위치** `detail[].loc`는 표 이름 · 줄 번호(0부터) · 칸이다(예: `["budget_items", 2, "total_amount"]`) — `POST /projects`는 payload 폼 필드를 직접 검증해 `body`가 앞에 붙지 않는다.
- **저장 시점** — 행은 `request_start`를 부르기 전에 같은 트랜잭션으로 커밋된다(`test_budget_schedule_saving.py`가 별도 연결로 확인). 시작 요청이 거절되거나 탈퇴가 시작되면 프로젝트와 함께 지워진다.
- **필수 확인(SB-332)** — 환경 변수 `REQUIRE_BUDGET_SCHEDULE=1`일 때만 켜진다(기본 꺼짐). 입력 화면이 배포되기 전에 켜면 모든 계획서 작성이 막히므로 화면 배포 뒤 오케스트레이터의 필수 확인과 같은 시점에 켠다. 켜면 사업비 1건 이상, 예비창업은 1단계 · 2단계 각 1건 이상, 협약기간 내(`feasibility`) 일정 1건 이상이 없을 때 `E-C1-REQUIRED`(422)로 막고 `detail.missing`에 `사업비 집행계획` · `사업비 집행계획(1단계)` · `사업비 집행계획(2단계)` · `추진 일정(협약기간 내)`를 담는다. 협약 이후(`growth`) 일정은 선택이다.
- **협약기간 내 일정 ≤ 개발 종료월(SB-354)** — 개발 종료월(`dev_end_month`)이 있으면 협약기간 내(`feasibility`) 일정 줄의 끝나는 달(추진기간에서 `(20\d{2})[-./~년\s]*(\d{1,2})`로 읽은 가장 늦은 달 — 검증-1과 같은 규칙)이 그보다 늦을 때 프로젝트 생성을 422로 막고 오류 위치를 `schedule_items[i].period`로 준다. 검증-1이 같은 기준으로 그 항목을 '입력 오류'로 실패 처리하고 재작성으로도 고쳐지지 않기 때문이다. 협약 이후(`growth`) 일정 · 개발 종료월이 없는 요청은 검사하지 않는다. 협약기간 최대 개월 수(예비 8 · 초기 10)는 공고마다 달라 입력 때 막지 않는다(공고를 고르기 전에 입력하므로) — 공고마다 다른 값을 받아야 하는지는 오케스트레이터가 담당자에게 묻는 중이다.

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

### 산출물 파일 내려 주기 (SB-291 ~ SB-318)

산출물 파일(실행 HTML · 원페이지 SVG · 인포그래픽 · 안내 문서 · 계획서 파일)은 DB가 아니라 오케스트레이터의 파일 저장소에 있고, 결과에는 파일 참조(`FileRef` — `key` · `name` · `mediaType` · `size` · `sha256`)만 실린다(SB-311, 결정 0023). 웹은 파일 위치(폴더 · 경로)를 알지 못한다 — `key`를 풀지도 경로로 쓰지도 않고 `read_artifact_file`에 그대로 넘긴다(운영이 S3로 옮겨도 웹 코드는 그대로다). 예전의 폴더 방식(SB-292~295: `ARTIFACT_DIR`, 웹의 폴더 서빙 · 삭제 · 고아 청소)은 SB-313~317에서 없앴다.

- **환경 변수 `SBRAIN_ARTIFACT_ROOT` (SB-313)**: 파일 저장소 폴더의 **절대 경로**. 웹은 읽기 전용으로 열고(쓰기 · 삭제는 워커), 워커는 이 값이 없으면 시작하지 않는다. 웹과 모든 워커가 같은 폴더를 같은 절대 경로로 봐야 한다. 웹에 값이 없거나 상대 경로면 웹은 뜨지만 파일 내려받기만 503(`FILE_STORE_UNAVAILABLE`)이다. 새 오류 코드: `FILE_NOT_FOUND`(404 — 남의 파일 · 없는 파일 · 내용 불일치를 구분하지 않는다), `FILE_STORE_UNAVAILABLE`(503), `FILE_DELETION_NOT_FOUND`(404).
- **결과의 파일 칸 (SB-314)**: 결과(`GET /result`의 `infographic_path` · `executable_path`)와 재작성 결과(`files[]` · `changed`)의 응답 필드 이름은 그대로이고, 값만 `/projects/{id}/artifact-files/{key}` 주소로 채운다(`mapping.file_url`). 진입 파일이 `null`이면 실행 경로도 없다. 원페이지는 두 참조가 같은 `onepage.svg`라 인포그래픽 주소만 보이고 실행 경로는 없다(인포그래픽이 비어 와도 진입 파일을 인포그래픽으로 보여 준다). 테스트: `tests/test_artifact_urls.py` · `tests/test_orch_fake_contract.py`(실제 계약에 새 칸이 있는지).
- **`GET /projects/{project_id}/artifact-files/{key}` (SB-315)** — **프로젝트 소유자만** 받는다(관리자도 못 받는다, 기획서 6-7). 주인 확인 뒤 `read_artifact_file(project_id, key)`를 부르고, 소유자가 아니면 없는 파일과 같은 404를 준다. 내용과 형식(`Content-Type`)은 오케스트레이터가 파일을 넣을 때 기록한 값 그대로이고, `nosniff` · `no-store` · `Content-Security-Policy: sandbox allow-scripts` + 외부 요청 차단 헤더가 붙는다(프론트는 샌드박스 iframe에 넣어 열기 때문에 헤더는 주소를 직접 열 때의 안전장치다). 테스트: `tests/test_artifact_files.py`.
- **`GET /projects/{project_id}/deliverable.zip` (SB-316)** — 최종 결과물의 프로토타입(진입 파일 · 안내 문서 · 자산) · 인포그래픽은 파일마다 `read_artifact_file`로 받고, **계획서는 파일 참조(`planDocFile`, 자리채움 파일)가 아니라 계획서(`planDoc`)로 웹이 만든 .docx**(`plan/business-plan.docx`, `plan-document.docx`와 같은 파일 — SB-341)를 넣어 웹이 묶는다(폴더 `plan/` · `prototype/` · `infographic/`, 같은 이름은 `_2`). 계획서(`planDoc`)가 없으면 결과물이 있어도 404 `DELIVERABLE_NOT_READY`다. 소유자만. 결과물이 아직 없으면 404 `DELIVERABLE_NOT_READY`, 원본 합계가 100MB를 넘으면 413 `DELIVERABLE_TOO_LARGE`(잠정 — 오케스트레이터가 정한 제한이 아니다), 한 파일이라도 못 받으면 일부만 든 압축을 주지 않고 그 오류로 답한다. 테스트: `tests/test_deliverable_zip.py`.
- **삭제 (SB-317)**: 프로젝트 영구 삭제 · 탈퇴 때 웹은 파일을 지우지 않는다. 오케스트레이터가 같은 트랜잭션에서 삭제 대기열(`orch_file_deletions`)에 넣고 워커가 10분 뒤부터 지운다(잠정). 3번 실패하면 `포기`가 되고, 포기한 파일은 탈퇴 뒤에도 남을 수 있다(사용자가 인정한 예외). 웹의 폴더 삭제 · 고아 청소 스크립트는 없앴다.
- **`GET /admin/file-deletions` · `POST /admin/file-deletions/{id}/retry` (SB-318)** — 관리자만. 삭제 대기열 목록(`status`로 `대기` · `포기`, `limit` 1~200 · `offset`)과 `포기`한 줄 다시 시도(누른 관리자 ID는 `user_id` 문자열로 오케스트레이터에 남는다). 없는 줄은 404, 이미 `대기`인 줄은 409. 줄에는 메타데이터만 있다(키 · 파일 이름 · 오류 메시지 · 사용자 없음). 테스트: `tests/test_admin_file_deletions.py`.
- **호출 종류 `file` (SB-319)**: 웹에는 호출 기록(`admin_calls`)을 내주는 API가 없고 관리자 실행 기록 응답에도 호출 종류가 없어서 바꿀 코드가 없다.

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
- **계획서 내려받기가 계획서 문장을 양식에 채우는 방식(SB-339)** — SB-310 이후 계획서는 양식의 모든 항목을 항목 번호(예비창업자 `2.1.1` ~ `2.7.4`, 개인사업자 · 법인 `3.1.1` ~ `3.7.4`)로 담고, `app/plan_texts.py`가 뒤 두 자리로 별첨1의 글 칸에 옮긴다(`x.2.2` 산출물, `x.3.1` ~ `x.3.5` 요약, `x.4.1` · `x.5.1` · `x.6.1` 본문, `x.7.1` ~ `x.7.4` 팀 구성). 표는 웹에 저장된 입력 행으로 그리고, 표 항목의 서술 문장만 계획서에서 와서 docx는 표 아래, hwp는 그 절 본문 뒤에 들어간다(표를 글자로 옮긴 줄과 단계 미지정 원본 JSON은 뺀다). 항목 번호 모양이 아닌 옛 계획서(`1-1` ~ `4-1`)는 예전처럼 태그로 읽는다. 예비창업 사업비는 줄의 단계(`phase`, SB-327)로 1단계 · 2단계 표를 나눠 채운다(docx는 표 둘, hwp는 표12 · 표14, 단계 없는 줄은 1단계, 표 아래 서술도 단계별). `tests/test_plan_texts.py`가 매핑 · 서술 걸러 내기 · docx 내용을, `tests/test_budget_phase_export.py`가 단계 나누기를 본다.
- **결과의 계획서 응답 모양(SB-337)** — `GET /result`의 `plan`: `sections[]`는 항목 번호(`section_code`) · 웹 태그(`tag` — `1-1` ~ `4-1`, 일반현황 · 개요처럼 묶음이 없으면 `null`) · 종류(`content_type` — `section` · `table` · `image`)를 각각 다른 칸으로 준다(예전에는 `tag` 칸에 항목 번호가 들어갔다 — 프론트가 바꿨다). 옛 계획서(항목 4개, 번호가 곧 `1-1` ~ `4-1`)는 번호를 태그로 본다. `score_reasons[]`마다 `tag`가 붙는다(`item_code`가 계획서 항목 번호라 같은 번호 항목의 태그, 없으면 `null`) — 묶음별 합계 · 미달 사유용. `diagrams[]`는 그림(서비스 흐름도 → 서비스 구조도 순)의 `diagram_id` · `flow_type` · `title` · `source_ref` · `nodes` · `image_url`(`/projects/{id}/artifact-files/{key}` — 산출물 파일과 같은 방식, 소유자만 받는다)이다. 재작성 결과(`GET /rework-result`)의 `changed.sections`는 키가 항목 번호(예전에는 키가 곧 웹 태그 `1-1`이었다)이고, 항목마다 `before` · `after`(그대로)에 `tag`(웹 태그, 묶음이 없으면 `null`) · `title`을 덧붙여 화면이 묶음 이름을 보일 수 있다. `tests/test_plan_result_shape.py` · `tests/test_orch_rework.py`가 본다.
- **점수 환산 칸(오케스트레이터 2026-10-11)** — 오케스트레이터가 검증-2 원점수(코드 점검 15 + 계획서 대조 15)를 그 실행 건 배점으로 환산해 점수 보고서(`ScoreView`)에 싣는다(`doc_layer_max` · `code_check_score/max` · `feature_match_score/max` · `artifact_layer_score/max` · `code_check_items`). 웹은 지금 정책(`verification_policies`) 값을 만점으로 붙이지 않고 이 칸을 쓴다 — 관리자가 배점을 바꾼 뒤 '13/10'처럼 어긋나기 때문이다. `GET /result`: `verdict`의 층 점수 · 만점(`doc_max_score` · `code_score/max_score` · `plan_match_score/max_score`)과 새 `artifact_score` · `artifact_max_score`, `plan.doc_max_score`, `plan.artifacts[].artifact_score`(환산 값) · `artifact_max_score`, 코드 점검 줄(`CHECK-…`)은 환산 줄의 `earned`(부분 점수)로 `score`를 채우고 해당 없음이면 `applicable=false`(0 · 0)이다(항목 `score` 합 = `code_score`, `max_score` 합 = `code_max_score`). 환산 칸이 비어 있는 옛 실행 건만 예전처럼 원점수와 지금 정책을 쓴다. 관리자: `GET /admin/items`의 줄에 `doc_score` · `doc_max_score` · `artifact_score` · `artifact_max_score`, `GET /admin/items/{id}/score-history`에 `doc_max` · `code_max` · `plan_max`(그 실행 건 만점). 관리자 층별 배점은 세 칸 모두 0보다 커야 저장된다(0이면 환산 점수가 늘 0). `tests/test_score_scaling.py`(+ `tests/test_admin.py`)가 본다. 화면 8의 층 점수는 `outputs`의 종합 점수 보고서에서 읽는다(화면 8 모양에는 점수 보고서가 없다) — 웹의 `GET /result`는 이미 그렇게 읽는다.
- **표 대체 사유 · 점수 안내(SB-354)** — 표를 본문 서술로 바꾼 항목은 오케스트레이터가 `Outputs.table_fallbacks`(항목 번호 `section_code` · 담당자 판정 원문 `reason` · 사용자용 안내 `display_reason`)로 따로 준다. 웹은 `GET /result`의 `plan.table_fallbacks[]`로 전하되 사용자에게 보여 줄 `display_reason`만 싣고(원문 `reason`은 내부 진단용이라 싣지 않는다), 항목 번호로 계획서 항목을 찾아 `tag` · `title`을 덧붙인다(계획서에 없는 번호는 둘 다 `null`). 사유는 본문(`sections[].body`)에 섞이지 않고, 바꾼 표가 없으면 빈 목록이다. 점수 보고서의 안내('입력 확인 필요' · '입력 오류' 문구)는 문서 평가 보고서 것이 `plan.notices`(화면 6), 종합 평가 보고서 것이 `verdict.notices`(화면 9)로 간다. 단위 테스트(`test_plan_result_shape.py`)는 가짜 오케스트레이터로, 계약 테스트(`test_orch_fake_contract.py`)는 실제 `Outputs` · `TableFallback`과 필드가 같은지로 확인한다 — 실제 Agent가 만든 사유 · 안내 문구는 확인하지 않았다.
- **계획서 그림(SB-340)** — 그림 항목(예비 `2.3.6` · 초기 `3.3.6`)의 서비스 흐름도 · 서비스 구조도는 `planDoc.diagrams[].imageFile`(SVG 파일 참조)이다. 웹이 `read_artifact_file`로 받아 `resvg-py`로 PNG로 바꿔(`app/diagram_images.py`, 글꼴은 `app/assets/fonts`의 나눔스퀘어라운드 + 시스템 글꼴) docx는 개요(요약) 표 아래에, hwp는 맨 뒤에 새로 만든 쪽에(rhwp `insert-page-break` + `insert-image`) 넣고, 결과물 압축에는 원본 SVG를 `plan/diagrams/`에도 넣는다. 그림 하나를 못 받거나 못 바꾸면 그 그림만 빼고 문서는 만든다(로그에 남음). 화살표(→)는 시스템 글꼴이 그려서 글꼴이 거의 없는 서버에서는 화살표만 빠질 수 있다. `tests/test_diagram_images.py`가 변환 · 순서 · 누락 처리 · docx · zip · hwp 쪽 추가를 보고, 실제 hwp 확인 2건은 `RHWP_BIN`이 있을 때만 돈다.
- 계획서 `.hwp` 내려받기는 `RHWP_BIN` 설정이 필요하다 — `scripts/README.md` 참고. 서버를 켠 뒤 Swagger(`/docs`)에서 `GET /projects/{id}/plan-document.hwp`를 직접 호출해도 된다.
