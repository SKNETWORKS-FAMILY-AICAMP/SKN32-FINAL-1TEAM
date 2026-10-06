# 전략/작성 Agent · 검증 1 호출 규격

이 문서는 다른 Agent가 Sbrain의 전략/작성 Agent와 검증 1을 호출할 때 사용하는 현재 계약을 설명한다. 함수 입력 타입과 반환 구조를 임의로 바꾸지 않는다.

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

## 4. 검증 1 호출

### `validate_section(section_spec, content, source_data)`

사업계획서 한 항목을 검증한다.

- `section_spec`: 실행 계약의 항목 규칙
- `content`: `generatedText`, `tables`, `nodes`, `facts`, `sourceRefs` 등
- `source_data`: 원본 사실, 전략 결과, `strategy_limits`, 근거 자료
- 반환 상태: `pass`, `warning`, `fail`
- 반환 주요 필드: `issues`, `warnings`, `needsUserConfirmation`, `contentHash`, `policyVersion`

`warning`은 합격으로 저장하며 내부 재작성 대상이 아니다. 필수 구조 누락, 확정 사실 불일치, 마감일 초과, 지원금 상한 초과만 `fail`로 처리한다.

## 5. 재작성 규칙

- 전체 실행은 항목을 한 번만 생성하고 검증 결과를 반환한다.
- 재작성은 UI의 통합 회귀 재작성 정책에서만 수행하며 항목별 최대 1·2·3회를 선택한다.
- 통과 항목과 최대 횟수에 도달한 항목은 자동 대상에서 제외한다.
- 수동 재작성은 `mode='manual'`, 자동은 `mode='auto'`, 이미지 전용은 `mode='image_only'`로 기록한다.
- 모든 실행은 결과 JSON의 `retryHistory`에 시각·모드·항목·상태를 누적한다.

## 6. Orchestrator T-C3 연동

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

## 7. 호출 시 주의사항

- `document_type`은 세 값만 허용한다.
- F16에는 전체 사업계획서가 아니라 항목별 `sourceKeys` 범위만 전달한다.
- F17은 `tables.columns`와 `tables.rows`를 반환한다.
- F18은 `USER_FLOW`, `SERVICE_ARCHITECTURE` 명세를 각각 반환한다.
- 결과 JSON의 `status`, `validation`, `evaluationSummary`를 함께 확인한다.
- `error_partial` 결과도 이미 완료된 항목과 trace를 보존하므로 후속 검증에 활용할 수 있다.

