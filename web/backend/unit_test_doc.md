# 웹 백엔드 단위 테스트 문서

웹 백엔드(`web/backend`)의 단위 테스트가 무엇을 확인하는지 정리한 문서입니다. 테스트를 추가하거나 고치면 이 문서의 해당 표도 같은 커밋에서 고칩니다.

- 실행 방법과 E2E 스크립트는 [`testing_guide.md`](testing_guide.md)가 설명합니다. 이 문서는 "어떤 테스트가 무엇을 확인하는지"만 다룹니다.
- 통과 건수 · 커버리지 같은 측정값은 브랜치마다 달라서 여기에 적지 않습니다. 아래 명령으로 그때그때 잽니다.

```
pytest -q                                   # 전체 실행 (약 1분)
pytest --collect-only -q | tail -1          # 테스트 건수
pytest --cov=app --cov-branch -q            # 구문 · 분기 커버리지
ruff check .                                # 정적 검사
```

## 1. 방식

- 서버 · 워커 · MySQL · LLM 없이 도는 단위 테스트입니다. 실제 오케스트레이터(`sbrain`)와 연동되는 부분은 가짜(`tests/orch_fakes.py`의 `FakeOrch`)로 대신합니다.
- 가짜가 실제와 어긋나지 않는지는 `test_orch_fake_contract.py`가 실제 `sbrain` 모델과 필드를 대조해 확인합니다(`sbrain`이 설치돼 있어야 실행). 오케스트레이터 쪽 계약이 바뀌면 이 테스트가 먼저 깨집니다.
- DB는 테스트마다 임시 SQLite(`conftest.py`의 fixture)를 씁니다. 팀 공유 MySQL에는 접속하지 않습니다.
- 공통 fixture: `client`(비로그인), `authed_client`(로그인한 사용자), `login_as(email)`(계정 전환), `db_session`(직접 조회), `orch`(가짜 오케스트레이터에 응답을 주입하고 호출 기록을 확인).
- 단위 테스트가 닿지 못하는 곳(실제 MySQL · 워커 · 실제 LLM 호출)은 `scripts/e2e_*.py`와 `scripts/rehearse_migration.py`가 확인합니다.

## 2. 영역별 테스트 파일

### 오케스트레이터 연동 계층 (`app/orch`)

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_orch_gateway.py` | 웹이 부를 수 있는 함수 허용 목록, 오류 변환, 초기화 |
| `test_orch_errors.py` | 오케스트레이터 오류 코드 → HTTP 상태 · `{detail, code}` 응답 변환 |
| `test_orch_mapping.py` | 오케스트레이터 값 → 웹 응답 대응표(묶음 이름, 출력 필드 변환) |
| `test_orch_command_log.py` | 웹이 넣은 상태 변경 명령을 웹 로그에 한 줄씩 남김 (SB-303) |
| `test_orch_fake_contract.py` | 가짜 오케스트레이터가 실제 `sbrain` 필드와 어긋나지 않는지, gateway 허용 함수가 실제로 있는지 |

### 단계별 흐름 · 결과 · 재작성

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_orch_stages.py` | 공고 선택 → 자격 확인 → 계획서 · 프로토타입 · 종합 평가 · 검수 시작 |
| `test_orch_result.py` | `GET /projects/{id}/result` — 계획서 · 판정 · 산출물 · 재작성 기회를 응답으로 변환 |
| `test_orch_rework.py` | 재작성 접수(`POST /retry-task`)와 전후 비교(`GET /rework-result`) |
| `test_match_candidates.py` | 공고 후보 조회 · 다시 찾기 · 선택 |
| `test_pipeline_stages.py` · `test_classify_error_kind.py` | 상태 표시 변환과 오류 종류 분류(순수 함수) |

### 산출물 파일

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_artifact_files.py` | 산출물 파일 내려 주기 — 소유자만(관리자 제외), 형식 · 보안 헤더 |
| `test_artifact_urls.py` | 산출물 경로 → 웹 주소 변환 |
| `test_artifact_cleanup.py` | 산출물 폴더 삭제와 고아 청소 |

### 프로젝트 생성 · 사전 정보 입력

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_project_plan_input.py` | `POST /projects`가 사업 계획 입력을 저장하고 조회로 그대로 돌려줌 |
| `test_attachment_limits.py` | 첨부파일 개수 · 용량 상한 |
| `test_company_per_project_fix.py` | 회사 프로필 계정당 1건 제한 해제, 동시 실행 1건 제한 분리 |
| `test_plan_document_endpoint.py` | 계획서 내려받기(`.docx`)가 공식 양식 구조로 나오고 본문이 채워짐 |
| `test_budget_phase_column.py` | `project_budget_items.phase` 컬럼(VARCHAR(10), NULL 허용, '1단계' · '2단계') (SB-328) |
| `test_budget_schedule_schema.py` | 사업비 · 일정의 요청 · 응답 모양, 허용값, 행 수 상한, 응답 순서 (SB-329) |
| `test_budget_schedule_validation.py` | 필수 · 금액 · 합계 · 유형별 단계 · 일정 필수 칸과 연도 검사, 오류 위치(표 · 줄 번호 · 칸) (SB-330) |
| `test_budget_schedule_saving.py` | 보낸 순서대로 저장, `request_start` 전에 커밋, 시작 거절 시 함께 삭제 (SB-331) |
| `test_budget_schedule_required.py` | 필수 조건 계산, 스위치(`REQUIRE_BUDGET_SCHEDULE`) 꺼짐 · 켜짐, `E-C1-REQUIRED`와 `missing` 이름 (SB-332) |

### 관리자 · 인증 · 프로필 · 부가 기능

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_admin.py` | 관리자 API와 권한(실행 목록 · 설정 · 알림 · FAQ 등) |
| `test_auth_consent.py` | 구글 로그인의 동의 상태, 재로그인 시 동의값 유지, 신규 여부 계산 |
| `test_profile.py` | 마이페이지 프로필(슬롯형) 저장 · 조회 |
| `test_biz_check.py` | 사업자등록번호 검증 |
| `test_faqs.py` | FAQ · AI 학습 동의 저장 |
| `test_notifications.py` | 알림 목록 · 읽음 표시 |

### 삭제 · 탈퇴 · 보관

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_projects.py` | `DELETE /projects/{id}`(보관) |
| `test_project_permanent_delete.py` | 완전 삭제 — 오케스트레이터 데이터 먼저, 휴지통 보관 |
| `test_account_deletion.py` | 계정 삭제(탈퇴)의 삭제 순서 |
| `test_account_withdrawing.py` | 탈퇴 중인 계정은 새 실행을 시작할 수 없음 (SB-298) |
| `test_proofread_retention.py` · `test_review_fixes.py` | 검수 회수 문단 보관 규칙, 완료 · 보관 · 삭제 회귀 |

### 동시 실행 · 오류 · 대기

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_concurrency_and_errors.py` | 동시 실행 1건 제한, 시작 요청 거절(`E-RUN-CONCURRENT` · `E-C1-REQUIRED` · `E-AUTH-PROFILE`) 처리 |
| `test_db_connection_during_wait.py` | 워커를 기다리는 동안 DB 연결을 붙잡지 않음 (SB-266) |

### 로그 · 시각 · 기본 점검

| 테스트 파일 | 확인하는 것 |
|---|---|
| `test_logging_config.py` · `test_request_logging.py` | 일 단위 로그 회전, 요청 로깅 |
| `test_utc_timestamps.py` | 응답 시각은 항상 UTC · 끝에 Z (SB-264) |
| `test_health.py` | 테스트 기반(fixture) 점검 |

## 3. 한계

- 실제 오케스트레이터 · 워커 · LLM은 단위 테스트에서 연결하지 않습니다. 연결된 상태의 동작은 `scripts/e2e_*.py`(로컬 MySQL + 워커)와 실제 Agent 연결 뒤의 E2E가 확인합니다.
- `startup.py`(실제 `sbrain` 연결 초기화)와 `pdf_export.py`(LibreOffice 변환)는 단위 테스트가 거의 닿지 않습니다.
- 가짜 오케스트레이터는 `test_orch_fake_contract.py`가 필드를 대조하지만, 값의 의미(점수 계산 등)까지 같은지는 확인하지 못합니다.
