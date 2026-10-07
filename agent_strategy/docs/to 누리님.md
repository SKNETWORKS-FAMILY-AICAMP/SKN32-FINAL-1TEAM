# Supervisor Agent 전달용 API·기능 명세

작성일: 2026-10-07  
대상: 전략·작성 Agent `agent_strategy`  
목적: Supervisor Agent가 전략 분석, 본문·표·이미지 작성, 검증 1, 조립 및 재작성 API를 호출할 때 필요한 계약을 전달한다.

## 1. 실행 계층

전략·작성 Agent는 다음 순서로 동작한다.

```
back JSON
  → normalize_back_input
  → F01~F15 전략·조사·계획
  → F16 본문 / F17 표 / F18 이미지 명세
  → F19 검증 1
  → F20 문서 조립
```

F01~F15 결과는 Canonical Data와 `sourceRefs`, `evidence`, `originalFacts`로 보존한다. F16~F18에는 항목별 `sourceKeys`만 전달한다. F19는 해당 항목의 본문·표·이미지와 필요한 근거를 검증한다.

Supervisor가 직접 호출할 때는 내부 Python 함수를 직접 호출하기보다 아래 HTTP API를 사용한다.

## 2. HTTP API

기본 주소: `http://127.0.0.1:8765`

### 2.1 상태 확인

`GET /api/status`

- OpenAI API 키 설정 여부와 서버 상태를 반환한다.
- 모델 호출은 수행하지 않는다.

### 2.2 입력 예시 조회

`GET /api/examples`

- 일반·예비창업·초기창업의 back 입력 예시를 반환한다.
- 실제 실행 입력은 `POST /api/run`의 `input`으로 전달한다.

### 2.3 전체 실행 또는 전략·작성 실행

`POST /api/run`

요청:

```json
{
  "documentType": "early_startup",
  "input": {},
  "executionScope": "full"
}
```

- `documentType`: `general`, `pre_startup`, `early_startup`
- `input`: back에서 받은 원본 JSON
- `executionScope`:
  - `full`: F01~F18 → F19 → F20
  - `strategy_writing`: F01~F18만 실행하고 F19·F20은 실행하지 않음

응답은 즉시 `202`와 `jobId`를 반환한다.

### 2.4 실행 상태 조회

`GET /api/jobs/{jobId}`

반환 주요 필드:

- `status`: `running`, `done`, `error`
- `message`
- `completedCalls`
- `result`
- `outputDirectory`
- 오류 시 `error`, `errorType`, `errorTraceback`

Supervisor는 작업 완료 전까지 이 API를 polling하고, `status=done`일 때만 결과를 사용한다.

### 2.5 선택 항목 재작성

`POST /api/retry` 또는 `POST /api/retry-latest`

요청 예시:

```json
{
  "documentType": "early_startup",
  "sectionId": "3.3.1",
  "instruction": "원본 근거보다 강한 기술 표현을 제거하고 제안값 상태를 표시하세요."
}
```

- 선택 항목과 동일 Canonical Data를 사용하는 연관 작성 항목을 함께 재생성한다.
- F01~F15 전략 함수는 다시 호출하지 않고 기존 결과를 재사용한다.
- F16/F17/F18과 필요한 F19/F20을 실행한다.
- `retryHistory`에 선택 항목, 영향 범위, 요청사항, 결과 상태를 저장한다.
- 기본 재작성 횟수는 항목당 1회다. F17 표는 표 계약상 최대 1회 추가 재시도 후 fallback 처리한다.

### 2.6 기존 결과 검증·조립

`POST /api/validate-latest`

최신 저장 결과를 대상으로 선택 항목과 연관 항목을 F19 검증하고 필요하면 F20으로 조립한다.

`POST /api/validate-all-latest`

요청:

```json
{
  "documentType": "early_startup",
  "skipPassed": true
}
```

- `skipPassed=true`: 기존 `pass`와 `warning` 항목을 건너뛰고 나머지만 검증한다.
- 본문·표·이미지를 재생성하지 않는다.
- 기존 결과의 `contentHash`와 정책 버전이 같으면 검증 결과를 재사용하되 현재 구조 보정은 다시 적용한다.

### 2.7 이미지 전용 재작성

`POST /api/image-retry-latest`

요청:

```json
{
  "documentType": "early_startup",
  "sectionId": "3.3.6",
  "instruction": "USERFLOW와 서비스 구조도를 같은 디자인 시스템으로 재작성하고 계층과 연결 방향을 명확히 표시하세요."
}
```

- 허용 항목: `2.3.6`, `3.3.6`
- USERFLOW와 SERVICE_ARCHITECTURE 두 F18 명세를 생성한다.
- 본문·표·연관 항목은 실행하지 않는다.
- 사용자 지시문은 F18의 `retryInstruction`으로 전달한다.
- `visualStyle`의 `palette`, `background`, `accent`, `cardStyle`, `layout`을 SVG에 반영한다.
- 결과의 `retryHistory.mode`는 `image_only`다.

### 2.8 실행 중단

`POST /api/cancel`

요청:

```json
{
  "jobId": "작업 ID"
}
```

- 현재 작업에 중단 요청을 전달한다.
- 이미 진행 중인 OpenAI 요청은 즉시 취소되지 않을 수 있으며, 다음 함수 경계에서 중단된다.
- 완료된 부분 결과는 `cancelled_partial` 상태로 저장한다.

### 2.9 영향 범위 조회

`GET /api/impact?documentType=early_startup&sectionId=3.3.1`

- 선택 항목
- upstream 전략 함수
- downstream 작성 항목
- F19·F20 마무리 범위를 반환한다.
- 실제 재작성 시 F01~F15를 다시 호출하지 않는지 확인할 때 사용한다.

### 2.10 섹션 매핑

`GET /api/section-mapping`

- 사업계획서 항목 위치와 함수명
- `sourceKeys`, back 원본 경로
- 재작성 연쇄 실행 함수
- F16/F17/F18 입력 계약을 반환한다.

## 3. 내부 함수 대응표

| 함수 | 기능 | 주요 입력 | 주요 출력 |
| --- | --- | --- | --- |
| F01 `collect_web_data` | Web·첨부 조사 수집 | query, source_type, target_fields | web_data |
| F02 `analyze_item` | 아이템·기능 분석 | item_input, research_data | item_spec, featureList |
| F03 `analyze_market` | 시장 분석 | item, market_data, analysis_type | market_analysis |
| F04 `analyze_competitors` | 경쟁사 분석 | item, market_data, competitor_data | competitor_analysis |
| F05 `analyze_team_capability` | 팀 역량 분석 | team_data, item_requirements | team_capability |
| F06 `define_development_goal` | 목표·KPI 정의 | item_spec, duration, target_field | development_goal |
| F07 `define_development_method` | 개발방법 정의 | core_technologies, constraints | development_method |
| F08 `create_development_plan` | 단계별 개발계획 | goals, duration, phases | development_plan |
| F09 `create_production_plan` | 제품화·양산계획 | product, development_plan, phases | production_plan |
| F10 `create_marketing_strategy` | 마케팅 전략 | item, market, target_customer, stage | marketing_strategy |
| F11 `create_business_model` | 비즈니스 모델 | item, market, customer, strategy | business_model |
| F12 `create_growth_strategy` | 성장전략 | market, competitors, bm, investment, social_value | growth_strategy |
| F13 `create_resource_plan` | 자원·인력·협력계획 | item, required_capabilities, team, resource_type | resource_plan |
| F14 `calculate_budget` | 예산 계산 | items, quantity, unit_price, phase, rules | budget |
| F15 `create_schedule` | 일정 계산 | tasks, duration, milestones | schedule |
| F16 `generate_section` | 본문 작성 | section_spec, source_data, writing_rules | generatedText, sourceRefs, status |
| F17 `generate_table` | 원본 기반 표 생성 | columns, rows, rules | tables.columns, tables.rows |
| F18 `generate_image_spec` | 이미지 명세 생성 | item, architecture, flow_type | nodes, flowType, visualStyle |
| F19 `validate_section` | 검증 1 | section_spec, content, source_data | status, issues, warnings |
| F20 `assemble_document` | 문서 조립 | sections, tables, images | document |

## 4. 결과 계약

Supervisor가 성공 결과로 인정할 최소 조건:

```json
{
  "status": "validation1_passed",
  "results": [],
  "evaluationSummary": {
    "internalQualityScore": 95.1,
    "documentLayerScore": 66.6,
    "officialPoints": null,
    "estimatedPoints": {
      "score": 95.1,
      "isOfficial": false
    }
  },
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "document": {}
}
```

항목별 결과에는 다음을 확인한다.

- `sectionId`, `functionId`, `generatedText`
- `validation.status`, `issues`, `warnings`
- `evaluation.internalQualityScore`, `documentLayerScore`
- `functionOutput.sourceRefs`, `facts`, `status`
- F17의 `tables`
- F18의 `imageSpecs`, `images`
- `attempts`, `retryHistory`

## 5. 상태 처리 규칙

- `pass`: 구조·계약·의미 검증을 통과함
- `warning`: 제안값·근거 보완·확인 필요 사항이 있으나 자동 실패는 아님
- `fail`: 필수 구조 누락, 원본 확정 사실 위반, 마감일 초과, 예산 상한 초과 등 재작성 또는 사용자 확인 필요
- `validation1_passed`: 전체 항목에 fail이 없음. warning은 포함될 수 있음.
- `validation1_failed`: 하나 이상의 fail이 있음.
- `cancelled_partial`: 사용자 중단으로 완료된 결과만 저장됨.

## 6. Supervisor 연동 시 주의사항

1. `result.json`의 결과를 직접 수정하지 말고 재작성 API를 호출한다.
2. warning을 자동 재작성하지 않는다. fail 항목만 기본 1회 자동 재작성한다.
3. 재작성 후에도 fail이면 추가 재작성 제안을 사용자에게 표시한다.
4. F17 표가 두 번 실패하면 표를 임의로 성공 처리하지 않고 fallback 사유를 보존한다.
5. F18 이미지 변경은 `image-retry-latest`로만 수행해 본문·표 토큰을 낭비하지 않는다.
6. `requestedModel`과 실제 `model`, `usage`, `responseId`를 함께 보존한다.
7. F19 실패 상태에서 F20 최종 문서를 제출 가능 상태로 표시하지 않는다.
8. API 키와 전체 프롬프트 원문을 외부 로그에 남기지 않는다.

## 7. 실행·검수 사용 안내

### 7.1 서버 실행

프로젝트 루트에서 다음 명령으로 로컬 테스트 서버를 실행한다.

```cmd
cd D:\Personal\P-PJT\Sbrain
cmd /c agent_strategy\app\testing\start_function_test.cmd
```

실행 후 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)를 연다. HTML 파일을 `file://`로 직접 열 수도 있지만, API·결과 저장·이미지 반영을 위해 로컬 서버 사용을 권장한다.

### 7.2 입력과 결과

- 일반·예비창업·초기창업 탭은 back에서 전달된 유형별 샘플 JSON을 입력으로 사용한다.
- 실행 결과는 `res/back_output/runs/<실행시각>_<유형>_<runId>/result.json`에 저장한다.
- 화면에서 결과 JSON 다운로드와 결과 경로 복사를 제공한다.
- 결과 확인 시 `status`, `validation1`, `evaluationSummary`, `usage`, `retryHistory`, `document`를 함께 확인한다.

### 7.3 실행 범위

- 전체 실행: F01~F18 작성 후 F19 검증, F20 조립까지 수행한다.
- 전략·작성 실행: F01~F18만 수행하고 F19·F20은 실행하지 않는다.
- 기존 결과 검증·조립: 저장된 결과를 재사용해 F19·F20만 수행한다.
- 작성 영역은 F16 본문, F17 표, F18 이미지다. F01~F15 전략 분석 기록은 화면 하단에서 확인한다.

### 7.4 재작성과 비용

- 검증 `fail` 항목은 검증 실패 회귀 재작성으로 다시 작성할 수 있다.
- 기본 재작성 횟수는 비용 절약을 위해 1회로 둔다. 2~3회 재작성은 필요할 때만 설정한다.
- 사용자가 개선 제안을 수락하면 해당 제안이 재작성 요청사항으로 전달된다.
- 선택 항목에 동일 Canonical Data를 사용하는 연관 항목이 있으면 안정성을 위해 함께 재작성할 수 있다. F01~F15 전략 함수는 기존 결과를 재사용한다.
- `2.3.6`·`3.3.6`은 이미지 전용 재작성을 제공한다. 본문·표·연관 항목은 실행하지 않고 USERFLOW와 서비스 구조도만 재생성한다.
- 재작성 지시문은 함수에 전달되며 요청 내용과 결과 상태는 `retryHistory`에 저장한다.

### 7.5 점수와 화면 확인

- 내부 품질 점수는 100점 기준으로 표시한다.
- `documentLayerScore`는 내부 점수의 문서층 70점 환산값이다.
- `officialPoints`는 공식 세부 배점표가 없을 때 `null`이다.
- `estimatedPoints`는 공고 평가영역을 기반으로 한 내부 예상값이다.
- 화면 아래로 스크롤하면 항목별 본문·표·이미지·검증 상태·경고·근거·점수·재작성 이력을 확인할 수 있다.
- 표의 함수명·모델·입력 경로 등은 표시할 열 선택에서 필요한 열을 체크해 확인한다.

