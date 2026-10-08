# 전략/작성 Agent · 검증 1 호출 규격

이 문서는 다른 Agent가 Sbrain의 전략/작성 Agent와 검증 1을 호출할 때 사용하는 현재 계약을 설명한다. 함수 입력 타입과 반환 구조를 임의로 바꾸지 않는다.

F01~F20의 기본 모델 ID와 함수별 입력·출력은 [실행 계약](../runtime/execution_contract.json)에 정의되어 있다. 실제 모델은 `STRATEGY_MODEL_{FID}` 환경변수로 함수별 재지정될 수 있으며, 실행 trace의 `model`이 실제 호출 모델을 나타낸다. 이 API 명세는 외부 호출자가 사용하는 Python 함수와 HTTP API 계약에 집중한다.

## 1. 실행 순서

```text
back JSON
  → normalize_back_input()
  → F01~F15 전략·조사
  → F16 본문 작성 / F17 표 생성 / F18 이미지 명세
  → F19 검증 1
  → F20 조립
```

전략·작성 실행만 요청하면 F01~F18까지 실행하고 F19·F20은 실행하지 않는다. 전체 실행은 F19 검증 후 fail이 없을 때 F20을 호출한다.

## 2. 주요 Python 함수

### `normalize_back_input(raw, document_type)`

back에서 받은 JSON을 내부 표준 입력으로 변환한다.

- `raw`: 사용자·공고 데이터가 담긴 JSON 객체
- `document_type`: `general`, `pre_startup`, `early_startup`
- 반환: `2_지금_입력받는값.POST_projects_body`, `project_plan_inputs`, `project_budget_items`, `project_schedule_items`, `team_members`, `_back_source`

### `run_pipeline(raw, document_type, progress=None, render_image=None, max_rewrites=1, execution_scope='full')`

전략·작성·검증·조립 파이프라인을 실행한다.

- `execution_scope='strategy_writing'`: F01~F18
- `execution_scope='full'`: F01~F20
- 반환: `runId`, `status`, `results[]`, `trace[]`, `validation1[]`, `evaluationSummary`, `usage`, `document`, `startedAt`, `completedAt`, `elapsedSeconds`

### `retry_sections(raw, prior_result, section_id, retry_instruction='', ...)`

선택 항목과 동일 Canonical Data를 사용하는 연관 항목을 재작성하고 F19를 다시 호출한다.

- `section_id`: 예 `1.2.1`, `2.5.3`, `3.3.6`
- `retry_instruction`: 사용자 보완 지시 또는 검증 실패 사유
- 반환: 갱신된 `results`, `evaluationSummary`, `retry`, `retryHistory`

## 3. 결과 항목 구조

각 `results[]` 항목은 다음 필드를 사용한다.

| 필드 | 설명 |
|---|---|
| `sectionId` | 사업계획서 항목 위치 |
| `functionId` | `F16`, `F17`, `F18` 등 |
| `generatedText` | 생성 본문 |
| `tables` | F17 표의 `columns`, `rows` |
| `images` | F18 SVG 결과 |
| `functionOutput` | 함수 원본 출력과 모델·토큰 정보 |
| `validation` | 검증 1 결과 |
| `evaluation` | 항목별 점수와 감점 사유 |
| `attempts` | 해당 실행 시도 이력 |

모델 호출별 토큰은 `trace[].usage`와 `functionOutput.usage`, 전체 합계는 최상위 `usage`에 기록한다. 입력 payload 문자 수(`inputChars`)와 `contextMetrics`의 문자 수 비교도 제공한다. 프로세스 RAM 사용량이나 최대 메모리(RSS/peak memory)는 현재 측정·기록하지 않는다.

## 4. 검증 1 호출

### `validate_section(section_spec, content, source_data)`

사업계획서 한 항목을 검증한다.

- `section_spec`: 실행 계약의 항목 규칙
- `content`: `generatedText`, `tables`, `nodes`, `facts`, `sourceRefs` 등
- `source_data`: 원본 사실, 전략 결과, `strategy_limits`, 근거 자료
- 반환 상태: `pass`, `warning`, `fail`
- 반환 주요 필드: `issues`, `warnings`, `needsUserConfirmation`, `contentHash`, `policyVersion`

`warning`은 조립 가능한 보완 상태로 저장하며 자동 재작성 대상이 아니다. 필수 구조 누락, 확정 사실 불일치, 일정·예산 상한 위반은 대표적인 `fail` 사유이며, 의미 검증도 유형별 rubric의 필수 조건 위반을 `fail`로 판정할 수 있다.

## 5. 재작성 규칙

- 전체 실행은 F16/F18 항목을 한 번 생성한다. F17은 F19가 fail이면 로컬 표 생성 함수를 한 번 더 호출하며, 두 번째에도 fail이면 fallback 설명을 기록한다.
- 재작성은 UI의 통합 회귀 재작성 정책에서만 수행하며 항목별 최대 1·2·3회를 선택한다.
- 통과 항목과 최대 횟수에 도달한 항목은 자동 대상에서 제외한다.
- 수동 재작성은 `mode='manual'`, 자동은 `mode='auto'`, 이미지 전용은 `mode='image_only'`로 기록한다.
- 재작성 요청이 성공한 결과에는 결과 JSON의 `retryHistory`에 시각·모드·항목·상태를 누적한다. 함수 호출별 시도 횟수와 검증 결과는 항목별 `attempts` 및 `validation.json`에 저장한다. 예외·취소로 재작성 함수가 결과를 반환하지 못하면 새 `retryHistory` 이벤트가 남지 않을 수 있다.

## 6. 테스트 UI HTTP API

아래 API는 함수 실행 테스트 UI에서 사용하는 로컬 서버 계약이다. JSON 다운로드, 경로 복사, 평가 요약 표시, 개선 제안 구성은 별도 서버 API가 아니라 `/api/latest-results` 응답을 브라우저에서 처리한다.

| Method | 경로 | 요청 주요 필드 | 동작 |
|---|---|---|---|
| GET | `/api/latest-results` | 없음 | 유형별 최신 `result.json` 내용과 결과 경로를 반환. 항목별 `validation`·`evaluation`, 전체 `evaluationSummary`, `retryHistory` 포함 |
| GET | `/api/section-mapping` | 없음 | 작성 항목과 함수 매핑, 재작성 관계 반환 |
| GET | `/api/impact?documentType={kind}&sectionId={id}` | 유형·선택 항목 | `impact_plan`에 따른 선택·연관 항목 반환 |
| GET | `/api/jobs/{jobId}` | 작업 ID | 비동기 작업 상태, 진행, 결과 조회 |
| POST | `/api/run` | `documentType`, `input`, `executionScope` | `strategy_writing`은 F01~F18, `full`은 F19 검증과 조건부 F20 조립까지 수행 |
| POST | `/api/retry` | `parentJobId`, `sectionId`, `instruction` | 진행 중이 아닌 완료 작업 결과를 기준으로 선택·연관 항목을 재작성하고 F19 재검증, 통과 시 F20 조립 |
| POST | `/api/retry-latest` | `documentType`, `sectionId`, `instruction`, 선택적 `mode` | 최신 저장 결과 기준 재작성. `mode`는 이력용 메타데이터이며 `writing_only`도 F19와 조건부 F20을 생략하지 않음. 현재 구현은 실행 당시 입력 대신 유형별 예시 JSON을 재작성 입력으로 사용 |
| POST | `/api/validate-latest` | `documentType`, `sectionId` | 저장된 선택·연관 항목만 F19 검증. 생성 결과 변경·전체 조립은 하지 않음 |
| POST | `/api/validate-all-latest` | `documentType`, 선택적 `skipPassed` | 전체 또는 Pass·Warning을 건너뛴 나머지를 F19 검증하고, Fail이 없으면 F20 조립 |
| POST | `/api/image-retry-latest` | `documentType`, `sectionId`, `instruction` | 지정 이미지 항목의 F18 명세와 렌더링 산출물 갱신 |
| POST | `/api/cancel` | `jobId` | 실행 중 작업에 취소 요청 |

`/api/run`은 `input` 객체에 비어 있지 않은 `tableData`가 있거나 `2_지금_입력받는값.POST_projects_body.description`이 있어야 사용자 입력을 유효한 것으로 본다. 둘 다 없으면 선택 유형의 예시 back JSON으로 대체 실행한다. 빈 객체도 이 동작을 유발한다.

회귀 재작성은 자동·수동 모두 `/api/retry-latest` 또는 `/api/retry`를 호출한다. 전체 실행 뒤 자동 회귀 여부와 항목별 최대 시도 횟수(기본 1회, UI에서 1~3회 선택)는 UI 설정에 따르며, warning은 자동 재작성하지 않는다. 재작성 요청별 모드·항목·지시·영향 범위·상태·시각은 결과 JSON `retryHistory`에 저장하고, 함수 호출별 시도 횟수·검증 결과는 항목별 `attempts`에 저장한다. 재작성으로 F20 조립까지 진행하려면 저장된 다른 작성 항목도 pass/warning/skipped여야 하므로, F19를 건너뛴 strategy_writing 결과에서는 먼저 전체 검증 API를 실행해야 한다.

F19 검증 API는 구조·원본 검사를 먼저 수행한다. 저비용 검사에서 issues가 생기면 의미 검증 호출을 생략하고, 통과하면 의미 검증 LLM을 호출할 수 있다. 기존 pass/fail 결과의 contentHash와 policyVersion이 일치하면 검증 결과를 재사용할 수 있으며, `skipPassed: true`는 기존 Pass·Warning 항목을 건너뛴다. 따라서 매 요청마다 모델 호출이 발생하지는 않는다.

평가 요약과 항목별 평가는 `evaluationSummary` 및 `results[].evaluation`에 포함한다. UI의 평가 결과 JSON 다운로드는 전체 최신 결과 객체를 다른 파일명으로 브라우저 저장하는 동작이며 별도 평가서 API는 없다. 점수 개선 제안은 현재 결과의 감점·경고를 바탕으로 UI가 구성하고, 수락 이력은 유형별 브라우저 `localStorage` 최근 50건에 저장한다. 제안 수락 이력은 서버 `retryHistory`와 별개다.

현재 입력 JSON 다운로드도 브라우저의 입력 textarea를 저장하므로 서버 endpoint가 없다.

## 7. Orchestrator T-C3 연동

Orchestrator가 만드는 `instruction`과 `rework_input`의 타입은 변경하지 않는다. `instruction`은 다음 세 부분을 포함할 수 있다.

```text
[작업 틀]
고정 규칙

[작업 안내]
아이템·공고별 조율 안내

[참조 자료]
Task에 배정된 근거 자료
```

작업 틀의 규칙을 최우선으로 적용한다. 재작성·재수행 시 Orchestrator가 작업 안내만 교체하고 문제 원문을 덧붙이며, 전략/작성 Agent는 지시문을 임의로 재조립하지 않는다.

## 8. 호출 시 주의사항

- `document_type`은 세 값만 허용한다.
- F16에는 전체 사업계획서가 아니라 항목별 `sourceKeys` 범위만 전달한다.
- F17은 `tables.columns`와 `tables.rows`를 반환한다.
- F18은 `USER_FLOW`, `SERVICE_ARCHITECTURE` 명세를 각각 반환한다.
- 결과 JSON의 `status`, `validation`, `evaluationSummary`를 함께 확인한다.
- `error_partial` 결과도 이미 완료된 항목과 trace를 보존하므로 후속 검증에 활용할 수 있다.

