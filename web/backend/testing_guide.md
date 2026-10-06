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

## 2. 실제 오케스트레이터 + MySQL로 돌려 보기 (로컬)

SQLite 개발 모드에서는 오케스트레이터를 쓸 수 없어 프로젝트 생성 · 단계 시작 · 결과 조회가 503으로 답한다. 실제 흐름을 보려면 MySQL이 필요하다.

1. 로컬 MySQL 띄우기 — Docker Desktop을 켠 뒤 `agent-orchestration/docker/mysql-test.yml`(127.0.0.1:3307, 데이터는 메모리에만 있음).
2. 웹 스키마 + 오케스트레이터 테이블 준비 — `agent-orchestration/tests/mysqldb.py`의 `_prepared_engine(url)`이 `web/backend/app_schema.sql`과 `agent-orchestration/sql/orchestrator_schema.sql`을 적용한다(**테스트용 DB를 지우고 새로 만든다**).
3. 웹 서버(`DB_BACKEND=mysql`, `SBRAIN_DB_URL`)와 워커(`python -m sbrain.worker`, `OPENAI_API_KEY` 필요)를 따로 띄운다.

기존 DB에 스키마 변경을 적용하는 SQL은 `migrations/`에 있다(멱등, MySQL 8). 공유 DB 적용은 팀 합의 뒤에 한다.

---

## 3. 그 밖의 검증 스크립트

- `python tests/verify_profile_mysql_local.py` — 마이페이지 프로필 API를 로컬 MySQL에서 확인한다.
- 계획서 `.hwp` 내려받기는 `RHWP_BIN` 설정이 필요하다 — `scripts/README.md` 참고. 서버를 켠 뒤 Swagger(`/docs`)에서 `GET /projects/{id}/plan-document.hwp`를 직접 호출해도 된다.
