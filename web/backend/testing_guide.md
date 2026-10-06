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

- **재개 · 실패 경로 (SB-261)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_failure_resume.py` : 이 스크립트가 워커를 같은 프로세스에서 직접 돌리며 스텁 Agent에 시간 초과 · 공고 서버 오류 · 잘못된 요청을 끼워 넣는다(워커가 따로 떠 있으면 끈다 — 같은 DB를 두 워커가 가져가면 시험이 틀어진다). 사전 단계 실패, 공고 선택 실패 후 재시도, 일시 오류 → 재개 → 성공, 재개 상한 초과 → 실패(관리자 알림 · 사용자 알림), 영구 오류 → 즉시 실패를 본다. 재시도 · 재개 간격을 짧게 줄여 몇 분 안에 끝난다. 조율 T-C1 · T-C3는 실제 LLM이라 OpenAI 키가 필요하다.

- **삭제 · 탈퇴와 BUSY (SB-259)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_delete_withdraw.py` : 같은 프로세스에서 워커를 돌리며 계획서 작성 호출을 붙잡아 "단계를 도는 중"을 만든다. 영구 삭제(쉬는 중 · BUSY 409 → 재시도), 탈퇴(프로젝트 2개 중 하나가 진행 중일 때 BUSY → 재시도, 웹 행 · 산출물 · 실행 건 · 통계 줄), 탈퇴 뒤 재가입, 시작 요청 처리 중 탈퇴를 본다. 다시 돌려도 된다(계정이 매번 새로 만들어진다).

- **학습 동의 · 검수 회수 문단 (SB-262)** — 1~4 준비 뒤(워커는 띄우지 않는다) `python scripts/e2e_training_consent.py` : 워커를 같은 프로세스에서 돌리며 검수 스텁이 일부 문장을 반려하게 만들고, 동의한 계정에서 `proofread_logs`에 행이 쓰이는지, 관리자 라벨링 · 학습 반영(trained) 표시, 동의 철회 · 영구 삭제 · 탈퇴 때 반영 전 행만 지워지고 trained 행은 연결만 끊겨 남는지, 검수 시작 전에 동의를 철회하면 행이 안 쓰이는지를 본다. 프로젝트를 끝까지 세 번 돌려 2분쯤 걸린다. 다시 돌려도 된다(trained 행은 연결이 끊긴 채 남는다).

기존 DB에 스키마 변경을 적용하는 SQL은 `migrations/`에 있다(멱등, MySQL 8). 공유 DB 적용은 팀 합의 뒤에 한다.

---

## 3. 그 밖의 검증 스크립트

- `python tests/verify_profile_mysql_local.py` — 마이페이지 프로필 API를 로컬 MySQL에서 확인한다.
- 계획서 `.hwp` 내려받기는 `RHWP_BIN` 설정이 필요하다 — `scripts/README.md` 참고. 서버를 켠 뒤 Swagger(`/docs`)에서 `GET /projects/{id}/plan-document.hwp`를 직접 호출해도 된다.
