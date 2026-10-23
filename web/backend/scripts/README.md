# scripts

웹 백엔드의 로컬 준비 · 검증 스크립트 모음입니다. 모두 `web/backend/`에서 실행합니다. 시험 순서와 설명은 [`../testing_guide.md`](../testing_guide.md)를 참고하세요.

## 스크립트 목록

| 파일 | 용도 | 전제 |
|---|---|---|
| `prepare_local_mysql.py` | 워커 E2E용 로컬 MySQL 준비 — 웹 스키마(`app_schema.sql`) + 오케스트레이터 표를 새로 생성. 로컬 호스트의 e2e/test DB만 허용 | 로컬 MySQL |
| `stub_worker.py` | 전략 · 작성 · 검증-1을 스텁으로 둔 워커. 따로 띄운 워커가 필요한 E2E(`e2e_worker_flow` · `e2e_concurrent_abort` · `e2e_business_applicant`)에 사용 | 로컬 MySQL |
| `e2e_worker_flow.py` | 실제 워커 + 로컬 MySQL로 웹 → 오케스트레이터 전체 흐름을 끝까지 실행 (공고 선택 → 계획서 → 프로토타입 → 종합 평가 → 재작성) | 로컬 MySQL + 워커 |
| `e2e_concurrent_abort.py` | 동시 실행 1건 제한과 중단 (SB-260) | 로컬 MySQL + 워커 |
| `e2e_business_applicant.py` | 개인사업자 · 법인 입력으로 자격 확인 응답의 업력이 값으로 오는지 (SB-296) | 로컬 MySQL + 워커 |
| `e2e_failure_resume.py` | 재개 · 실패 경로 (SB-261) — 워커를 스크립트 안에서 직접 돌려 실패를 끼워 넣음 | 로컬 MySQL |
| `e2e_delete_withdraw.py` | 영구 삭제 · 계정 탈퇴와 BUSY (SB-259) | 로컬 MySQL |
| `e2e_artifact_files.py` | 산출물 파일 흐름 (SB-295 · SB-320) | 로컬 MySQL |
| `e2e_training_consent.py` | 학습 동의와 검수 회수 문단 (SB-262, SB-400) | 로컬 MySQL |
| `e2e_budget_schedule.py` | 사업비 · 추진 일정 입력이 저장 → 시작 요청까지 이어지는지 (SB-333) | 로컬 MySQL |
| `e2e_admin.py` | 관리자 화면 API를 실제 워커가 만든 데이터로 확인 (SB-263) | 로컬 MySQL |
| `load_check.py` | 워커가 응답하지 않을 때 대기 요청이 쌓여도 다른 요청이 막히지 않는지 (SB-266) | 로컬 MySQL, 워커는 띄우지 않음 |
| `rehearse_migration.py` | 옛 웹 스키마에 `migrations/001 · 002 · 004 · 005 · 006`을 적용해 `app_schema.sql`과 같아지는지 (SB-265). **003 · 007은 포함하지 않음** | 로컬 MySQL |
| `clean_hwp_template.py` | 양식 `.hwp`의 표 안 파란 예시 상자를 지운 템플릿 생성 — `app/assets/hwp_templates/*_정리.hwp`가 이 스크립트의 결과 | rhwp |

각 스크립트의 인자와 판정 기준은 파일 상단 주석에 있습니다. 위 "전제"는 상단 주석을 기준으로 정리했으며, 실행 전에 해당 주석을 한 번 확인하세요.

## rhwp 설치와 확인

사업계획서 `.hwp` 다운로드(`app/hwp_export.py`)는 외부 CLI인 [rhwp](https://github.com/edwardkim/rhwp)로 `.hwp` 원본 양식에 내용을 채웁니다. 실행 파일은 용량 때문에 git에 없으므로 각자 공식 릴리즈에서 받습니다. rhwp 없이도 서버는 정상 동작하고 `.hwp` 다운로드만 500입니다.

> AWS 서버에는 배포 스크립트가 rhwp v0.8.6을 자동으로 설치합니다(못 받으면 `.hwp`만 비활성). 아래는 내 PC에서 직접 확인할 때의 절차입니다.

### 1. 다운로드

https://github.com/edwardkim/rhwp/releases/tag/v0.8.6 에서 `rhwp-v0.8.6-windows-x86_64.zip`을 받아 압축을 풀고, 안의 실행 파일을 `web/backend/rhwp.exe`로 저장합니다(파일명 · 위치를 그대로 맞춥니다).

### 2. `.env`에 경로 설정

`web/backend/.env`(없으면 `.env.example`을 복사)에 다음 줄을 추가하거나 확인합니다.

```bash
RHWP_BIN=./rhwp.exe
```

절대 경로(`C:\...\web\backend\rhwp.exe`)도 됩니다. PATH에 `rhwp`가 등록되어 있으면 비워 두어도 기본값 `rhwp`로 PATH에서 찾습니다.

### 3. 확인

서버(`uvicorn app.main:app --reload`)를 켠 뒤 Swagger(`/docs`, `.env`에 `ENABLE_API_DOCS=1`이 있어야 열림)에서 `GET /projects/{id}/plan-document.hwp`를 직접 호출합니다.

| 응답 | 의미 |
|---|---|
| 200 | 정상 |
| 500 | `RHWP_BIN` 경로가 잘못되었거나 rhwp가 없음 |
| 504 (`HWP_CONVERSION_TIMEOUT`) | 변환이 `RHWP_TIMEOUT_SECONDS`(기본 120초)를 초과 — 다시 요청하거나 값을 조정 |

rhwp가 없으면 `tests/`의 rhwp 실제 확인 시험(예: `test_hwpx_fit.py`의 일부)은 건너뜁니다(`skipped`, 실패 아님).
