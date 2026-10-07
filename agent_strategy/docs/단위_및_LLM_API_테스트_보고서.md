# 전략·작성 Agent 단위 및 LLM API 테스트 보고서

- 테스트 일자: 2026-10-07
- 대상: `agent_strategy` 전략·작성 실행 범위
- 실행 환경: Python 3.11 계열, Windows, `OPENAI_API_KEY` 설정 환경

## 1. 단위 테스트

실행 명령:

```cmd
python -B -m unittest discover -s agent_strategy/testing -p "test_*.py" -q
```

결과:

- 총 19개 테스트 실행
- 성공 19개
- 실패 0개
- 결과: **Pass**

검증 범위는 함수별 입력 계약, 정규화된 back 입력, F14 예산 계산, F15 일정 생성, F17 원본 행 기반 표 생성, F18 이미지 명세 구조, F19 검증 결과 연결과 파이프라인 결과 구조를 포함합니다.

추가 문법 검사도 통과했습니다.

```cmd
python -B -m py_compile agent_strategy/runtime/pipeline.py agent_strategy/app/testing/test_server.py agent_validation_1/validation_1.py
node --check agent_strategy/res/js/strategy_writing_agent.js
```

## 2. 실제 LLM API 호출 테스트

F16 `generate_section`을 최소 입력으로 1회 호출하여 실제 OpenAI 응답을 확인했습니다. 전체 사업계획서 실행은 호출하지 않고 단일 항목만 호출해 비용을 제한했습니다.

확인 결과:

- 요청 모델: `gpt-5.6-sol`
- 실제 사용 모델: `gpt-5.6-sol`
- 응답 함수: `generate_section`
- 응답 상태: 정상 반환
- `generatedText`: 정상 생성
- `sourceRefs`, `facts`, `needsUserConfirmation`: JSON 계약 필드 반환
- 사용량: 입력 6,020토큰, 출력 316토큰, 합계 6,336토큰
- 결과: **Pass**

실제 생성 결과는 서비스 개요, 목표 고객 제안, 핵심 기능 제안으로 구성되었고, 확정되지 않은 고객 정보는 확인 필요 상태로 표현되었습니다.

## 3. 결론 및 제한사항

단위 테스트와 실제 단일 LLM 호출은 정상입니다. 다만 이번 API 테스트는 F16 한 항목의 최소 호출이므로, 일반·예비창업·초기창업 전체 유형의 F01~F20 통합 실행 성공을 의미하지 않습니다. 전체 실행은 모델 호출량과 비용이 크므로 유형별 최종 테스트가 필요할 때만 수행합니다.

F17 표·F18 이미지·F19 검증·F20 조립은 단위 테스트에서 계약 구조를 확인했으며, 실제 전체 실행 결과는 별도 `result.json`의 `validation1`, `evaluationSummary`, `usage`를 기준으로 확인합니다.

## 4. 최근 보완 항목별 검증 결과

### 4.1 F17 표 생성

- 필수 열(`columns`)과 행(`rows`)을 갖춘 표 생성 결과를 확인했습니다.
- 표 계약이 실패하는 경우 최대 1회 재시도하도록 확인했습니다.
- 재시도 후에도 실패하면 표를 성공 결과로 저장하지 않고 `tableFallbackUsed`, `fallbackReason`을 기록하며 본문 설명으로 대체합니다.
- F19가 실제 표를 `tables.columns`·`tables.rows` 누락으로 오판한 경우 저장 구조를 우선해 보정합니다.
- 표가 없거나 필수 열이 실제로 누락된 경우에는 `fail`을 유지합니다.

### 4.2 F18 이미지 재작성

- `2.3.6`·`3.3.6` 선택 시 이미지 전용 지시문 입력칸이 표시됩니다.
- 사용자 지시문은 USERFLOW와 SERVICE_ARCHITECTURE 양쪽 F18 호출에 전달됩니다.
- 이미지 전용 실행은 본문·표·연관 사업계획서 항목을 다시 실행하지 않습니다.
- 결과에는 두 이미지가 모두 저장되고, `retryHistory.mode`는 `image_only`로 기록됩니다.
- F18의 `visualStyle`에 포함된 `palette`, `background`, `accent`, `cardStyle`, `layout`을 SVG 렌더러가 우선 사용합니다.
- 잘못된 색상값은 기본값으로 대체하여 SVG가 깨지지 않도록 합니다.

### 4.3 검증 캐시 및 점수 구조

- 동일 `contentHash`의 검증 결과를 재사용하더라도 현재 표 구조 보정 로직을 다시 적용합니다.
- 기존 캐시의 표 누락 오탐이 그대로 유지되지 않도록 수정했습니다.
- 평가 결과에 다음 필드를 저장합니다.

| 필드 | 의미 |
| --- | --- |
| `internalQualityScore` | 내부 품질 평가 100점 환산값 |
| `documentLayerScore` | 내부 품질 점수의 70% 환산값 |
| `officialPoints` | 공식 세부 배점표가 없을 때 `null` |
| `estimatedPoints` | 공고 평가영역 기반 내부 예상 배점 |

## 5. 실행 결과 확인 기준

실행 결과 JSON은 다음 항목을 함께 확인합니다.

- `status`: `validation1_passed`, `validation1_failed` 또는 부분 실행 상태
- `validation1`: 항목별 F19 상태·이슈·경고
- `evaluationSummary`: 평균·최저 점수와 점수 구조 필드
- `results[].functionOutput`: F16 본문, F17 표, F18 이미지 명세
- `results[].images`: 렌더링된 SVG 두 개 여부
- `retryHistory`: 자동·수동·이미지 전용 재작성 이력
- `usage`: 입력·출력·총 토큰 사용량
- `document`: F20 조립 결과 존재 여부

예시 확인 명령:

```cmd
python -B -c "import json; p=r'agent_strategy/res/back_output/runs/<run>/result.json'; d=json.load(open(p,encoding='utf-8')); print(d['status']); print(d['evaluationSummary']); print(d['usage'])"
```

## 6. 비용·재현성 제한

- 실제 LLM API 테스트는 최소 1개 항목 호출로 제한했습니다.
- 전체 F01~F20 실행은 유형별 최종 확인 때만 수행해야 하며, 재작성·검증 캐시를 활용해 불필요한 호출을 줄입니다.
- 코드·계약·렌더링 테스트의 통과는 실제 모델 응답의 모든 의미 품질을 보장하지 않습니다.
- 전체 실행 결과는 실행 시점의 모델 응답, API 사용량, 입력 JSON에 따라 달라질 수 있으므로 결과 파일의 `model`, `requestedModel`, `usage`, `responseId`를 함께 보존해야 합니다.

## 7. 테스트 판정 기준과 실패 확인 순서

| 확인 대상 | Pass 기준 | 실패 시 확인할 필드 |
| --- | --- | --- |
| 전략 함수 F01~F15 | 함수 호출·출력 계약·근거 보존 | `trace[].functionId`, `trace[].status`, `functionOutput.sourceRefs` |
| 본문 F16 | `generatedText` 존재, 항목 규칙 충족, 제안값 상태 구분 | `results[].generatedText`, `validation.issues`, `validation.warnings` |
| 표 F17 | 필수 `columns`·`rows` 존재 | `functionOutput.tables`, `tableFallbackUsed`, `fallbackReason` |
| 이미지 F18 | USER_FLOW·SERVICE_ARCHITECTURE 명세와 SVG 2개 존재 | `functionOutput.imageSpecs`, `images`, `imageTypes` |
| 검증 F19 | 구조 검증 후 의미 검증 완료 | `validation.status`, `semanticCalled`, `contentHash`, `policyVersion` |
| 조립 F20 | 검증 실패가 없을 때 `document` 생성 | `document`, `status`, `message` |

실패 결과는 먼저 `validation.issues`와 `warnings`를 구분해 확인합니다. 표 구조·필수 필드·마감일·예산 상한 위반은 코드 계약 문제인지 입력 문제인지 확인하고, 제안값·근거 보완·시험조건 미확정은 warning인지 확인합니다. 의미 검증 결과가 이전 결과와 동일하게 반복되면 `contentHash`, `policyVersion`, `reused`를 확인해 캐시 재사용 여부를 판단합니다.

## 8. 테스트 범위의 명확한 한계

현재 보고서의 19개 회귀 테스트는 로컬 계약·라우팅·정규화·렌더링을 검증합니다. 실제 API 단위 테스트는 F16 최소 호출 1회이며, 일반·예비창업·초기창업 각각의 모든 항목을 실제 모델로 호출한 결과를 의미하지 않습니다. 따라서 유형별 최종 결과를 보고할 때는 해당 실행의 `result.json` 경로와 총 토큰 사용량을 함께 기록해야 합니다.

## 9. 실행 기록과 보안 확인

- API 키는 `OPENAI_API_KEY` 환경 변수에서 읽으며 결과 JSON·trace·보고서에 저장하지 않습니다.
- 모델 식별은 `requestedModel`과 실제 `model`을 분리해 기록합니다. fallback이 발생하면 `fallbackUsed`와 `fallbackReason`도 함께 확인합니다.
- 실행 결과는 유형·실행 시각·runId별 `result.json`으로 보존하며, 검증·재작성 이력은 `retryHistory`에서 확인합니다.
- 결과를 공유하거나 보고서에 인용할 때는 API 키, 원문 개인정보, 불필요한 전체 프롬프트를 포함하지 않고 결과 경로·상태·사용량·모델 식별값만 기록합니다.
- 동일 결과를 재현하려면 입력 JSON, 실행 범위, 코드 버전, 정책 버전, 요청 모델, 실제 모델, 사용량을 함께 보존해야 합니다.

## 10. 변경 버전 추적

이번 보고서에 반영된 주요 변경 커밋은 다음과 같습니다.

- `SB-50 [FEAT] 전략/작성 agent - F17 표 fallback 및 점수 구조 표시`
- `SB-50 [FIX] 전략/작성 agent - 검증 캐시 재사용 보정`
- `SB-50 [FEAT] 전략/작성 agent - 이미지 재작성 프롬프트와 스타일 명세`

테스트 결과를 재현할 때는 위 커밋이 포함된 코드와 함께 실행 시점의 입력 JSON, `VALIDATION_POLICY_VERSION`, 요청 모델·실제 모델, `result.json`의 `usage`를 보존합니다. 보고서의 단위 테스트 결과는 이 실행 기준에서 Python 문법 검사, JavaScript 문법 검사, 회귀 테스트 19개를 모두 통과한 결과입니다.
