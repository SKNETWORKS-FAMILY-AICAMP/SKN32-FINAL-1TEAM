# Validation 1

`validation_1.py`가 F19를 수행한다. 필수 텍스트·항목 개수·줄 수·필수 필드·표 컬럼(표가 요청된 경우)·이미지 노드·원본 facts·출처 ID·원 단위 금액을 Python으로 검사한다. 구조 오류가 없을 때만 GPT-5.6 Terra로 원본 충실성·근거 관련성·논리·항목 요구조건을 검증한다.

실패 항목은 테스트 파이프라인에서 F16/F18로 최대 1회 재작성하고 재검증한다. 여전히 실패하면 초안과 오류를 보존하되 F20 최종 조립을 실행하지 않는다. 표 생성 제외 항목은 검증 대상에서도 제외한다. 분량·페이지 수는 실제 문서 렌더링 전 확정하지 않는다.

## 실행 위치와 연결 구조

검증 1의 판정 코드는 이 폴더의 `validation_1.py`에 별도 Agent 영역으로 관리한다. 전략·작성 Agent 코드에 검증 규칙을 복사해 넣지 않는다.

현재 개발·테스트 단계에서는 `agent_strategy/runtime/pipeline.py`가 F16/F17/F18 작성 결과를 만든 뒤 `agent_validation_1.validation_1.validate_section()`을 호출하는 방식으로 연결되어 있다. UI 요청과 실행 상태 관리는 `agent_strategy/app/testing/test_server.py`가 담당한다.

```text
agent_strategy/app/testing/test_server.py
        ↓
agent_strategy/runtime/pipeline.py
        ├─ 전략·작성 결과 생성
        └─ agent_validation_1.validation_1 호출
                ↓
        검증 1 결과(validation/issues/warnings)
```

따라서 현재 검증 1은 독립된 코드 영역을 유지하면서 전략·작성 테스트 파이프라인에 연결되어 실행된다. 추후 전체 `agent-orchestration` Supervisor가 연결되면 동일한 검증 1 인터페이스를 통해 조율 Agent의 실행 흐름에 편입한다.

검증 결과는 항목별 `results[].validation`, 전체 `validation1`, 별도 `validation_results` 배열에 기록하며, 실행 폴더에는 `validation.json`을 별도로 저장한다.

전략·작성 Agent와의 입력·출력 계약과 회귀 재작성 흐름은 [`agent_strategy/res/reference/agent_validation_integration.md`](../agent_strategy/res/reference/agent_validation_integration.md)에 정의한다. 검증 1은 이 계약에 따라 `section_spec`, `content`, `source_data`를 받고 `status`, `issues`, `warnings`, `needsUserConfirmation`, `contentHash`, `policyVersion`을 반환한다.

예비·초기창업패키지의 관리기준과 질의응답 원문은 `res/prompts/reference/validation_sources.json`에 경로를 등록한다. F19 프롬프트는 문서 유형에 맞는 원문 JSON을 제한된 길이로 읽어 공고의 지원 대상·협약기간·사업비·성과 기준을 참고한다. 원문 전체를 결과에 복사하지 않고 출처 경로와 필요한 발췌만 전달한다.

## 평가 점수 서비스

`scoring.py`는 검증 1의 판정과 분리된 결정론적 평가기다. `res/prompts/evaluation_rubric.json`의 유형별 가중치와 내부 규정 근거 경로를 사용해 각 항목에 0~100점을 계산한다. 구조·작성 목적·근거 추적·내용 일관성·표현 명확성을 평가하며, `issues`, `warnings`, `needsUserConfirmation`의 원인과 감점 내역을 함께 반환한다.

점수는 임베딩 유사도나 임의의 정부 평가점수가 아니다. 규정에 없는 기준을 만들어내지 않고, 검증 결과와 관찰 가능한 계약만 계산한다. 실제 제출용 평가지표로 사용하려면 해당 공고의 공식 배점표를 `evaluation_rubric.json`에 추가하고 근거 파일을 함께 등록해야 한다.

## 판정·평가 기준의 분리

- `validation_1.py`는 필수 구조, 원본과 다른 확정 사실, 마감일·지원금 한도, 필수 기능·표·이미지 누락을 `fail`로 판정한다.
- 계획·제안·확인 필요 문구, 시험 조건 미확정, 직접 근거가 약한 출처는 `warning` 또는 `needsUserConfirmation`으로 분류한다.
- `semantic_review.py`는 의미 검증 결과를 재검토할 때 표현 차이만으로 실패시키지 않고, 구조 검증 결과와 충돌할 때만 재판정을 요청한다.
- 기능명·기술명·단계명·날짜·금액은 정규화하여 괄호, 구분자, 공백, 표기 형식 차이로 인한 오탐을 줄인다.
- 성능지표·서비스 개요에는 `featureList` 전체 반복 검사를 적용하지 않고, 실제 기능·개발방법·개발계획 항목에만 기능 불변식을 적용한다.

## 공고 유형별 기준과 한도

일반 사업계획서는 사용자 입력과 실행 계약을 중심으로 평가한다. 예비·초기창업패키지는 `res/reference/regulations`의 원문 JSON을 `validation_sources.json`으로 연결해 지원 대상, 협약 기간, 사업비 집행, 성과·실증 기준을 참고한다. 규정 원문에 없는 조건을 임의로 만들지 않으며, 자료가 없으면 확인 필요 경고로 남긴다.

전략·작성 Agent가 back JSON에 넣은 `_strategy_limits.deadline`, `_strategy_limits.supportLimit`, `_strategy_limits.featureList`는 검증 1이 동일하게 받아 일정 초과, 지원금 합계 초과, 확정 기능 목록 변경을 판정한다. 날짜·금액 표기는 월·숫자로 정규화하고, 제안값은 계획 수립을 위한 값으로 표시된 경우 실패가 아닌 경고로 처리한다.

## 결과 저장과 회귀 흐름

각 실행 항목에는 `validation`, `evaluation`, `contentHash`, `policyVersion`이 저장된다. 실행 폴더의 `validation.json`에는 검증 결과만 별도로 보존하고, `result.json`에는 전체 결과와 `evaluationSummary`를 함께 저장한다. 동일 본문과 동일 정책 버전이면 기존 판정을 재사용해 불필요한 LLM 호출을 줄인다.

검증 실패 회귀 재작성은 실패 항목과 검증 사유를 전략·작성 Agent에 전달하고, 동일 Canonical Data를 사용하는 연관 항목만 재생성한 뒤 F19를 다시 호출한다. 자동 회귀는 항목별 최대 횟수에 도달하면 중지하며, 각 시도와 중지 사유를 history에 기록한다. API·크레딧·토큰 오류가 발생해도 이미 완료된 항목과 trace를 `error_partial` 결과로 보존한다.

## 현재 검증 범위와 한계

회귀 테스트 17개와 Python 문법 검사를 통과했다. 점수는 정부기관 공식 배점이 아니라 내부 계약·규정 근거 기반 품질 지표이며, 실제 공고의 공식 배점표가 제공되면 `evaluation_rubric.json`에 별도 반영해야 한다. 규정 자료가 갱신되면 원문 JSON, `validation_sources.json`, rubric 정책 버전을 함께 갱신한다.
# 검증 1 Agent

## 커밋 규칙

검증 1 Agent 변경은 다음 형식을 사용한다.

```text
SB-127 [FEAT] 검증1 agent - <수행 내용>
```

유형별 접두사는 `[FEAT]`, `[FIX]`, `[DOCS]`, `[TEST]`, `[REFACTOR]`, `[CHORE]` 등을 사용한다. 전략·작성 Agent 변경은 `SB-127 [TYPE] 전략/작성 agent - <수행 내용>` 형식을 사용하며, 두 Agent의 변경을 한 커밋에 섞지 않는다.


## 초기창업 전용 기준 보완

초기창업 템플릿에 개발계획·단계별 사업비·전체 일정·USERFLOW/서비스 구조도 검증 조건을 추가했다. 2025년 초기창업패키지 세부관리기준은 `validation_sources.json`으로 연결되어 있으며, `_strategy_limits`의 deadline·supportLimit·featureList와 함께 사용한다. 제안 KPI·시험조건·수량·단가 미확정은 warning으로 남기고, 확정 사실 불일치·한도 초과·마감일 초과·필수 계약 누락만 fail로 판정한다.

### 초기창업 매핑 기반 검증 보완

초기창업 항목별 매핑이 단순 표시용 경로에 그치지 않도록 3.3.6 이미지 유형·nodes 범위, 3.5.2 개발계획 표 컬럼·서술문 최소 분량, 3.5.3·3.5.4 단계 선택·미구분 중복 금지, 3.6.2 개발·성장전략 일정 병합과 마감일 검증 메타데이터를 연결했다. 검증 1은 이 메타데이터와 원본 JSON을 함께 참고해 초기창업 누락을 판정한다.

### 초기창업 규정 자료 확장

초기창업 검증 자료에 2026년 초기창업패키지 일반형 모집공고문과 사업계획서 양식 JSON을 추가로 보관하고 `validation_sources.json`에 연결했다. 세부관리기준은 집행·협약·성과 기준에, 모집공고는 지원 대상·기간·지원 규모에, 양식 JSON은 필수 섹션·표 구조 확인에 사용한다. 세 자료가 서로 다른 연도나 목적을 갖는 경우 원문 경로와 문서 유형을 결과에 남기고, 충돌하는 조건은 임의로 합치지 않고 확인 필요로 분류한다.


### 초기창업 표 계약 재점검

초기창업 3.5.2·3.5.3·3.5.4·3.6.2의 매핑 대상을 실제 표 생성 계약과 일치시켰다. 검증 1은 해당 항목에서 필수 컬럼·행을 `tables` 구조로 확인하며, 본문에 JSON 배열만 있는 경우 표 계약 누락으로 판정한다.

### 45. 초기창업 F18·표·featureList 판정 보완

초기창업 F18 검증은 USERFLOW와 SERVICE_ARCHITECTURE 두 이미지 명세를 모두 대상으로 하며, 각 명세의 `nodes`와 `flowType`을 확인한다. 작성 단계에서 두 이미지가 저장되도록 전략 파이프라인이 보장하고, 한 이미지의 검증 상태 때문에 다른 이미지가 누락되지 않도록 한다.

단계가 미지정인 사업비는 1·2단계 표에 중복 배분하지 않는다. `unassignedOriginalRows`가 보존된 빈 단계 표는 원본 입력 부족에 따른 확인 필요 warning으로 분류하며, 임의 금액을 생성하지 않는다. 3.6.2는 개발·검증·출시 일정과 성장전략 일정을 합친 결과를 검증한다.

`featureList`는 개별 일정표의 모든 기능 반복을 요구하지 않는다. 실제 기능·핵심기술·개발방법 항목에서만 핵심 토큰 일치 여부를 확인하며, 일정·예산 표의 기능 미반복은 그 자체로 fail 처리하지 않는다.
### 초기창업 사업비 검증 항목 정정 (2026-10-02)

초기창업패키지는 단일 사업비 집행계획 표를 사용하므로 검증 1은 초기창업 `3.5.3`의 원본 행·산출근거·지원금 합계·상한을 확인한다. 예비창업 전용 1·2단계 항목인 `3.5.4`는 초기창업 계약과 검증 대상에서 제거했다. 단계 미지정 원본을 별도 단계에 임의 배분하지 않는다.
## 초기창업 검증 보완 이력

- 초기창업 원문 양식에 맞춰 단일 사업비 표 `3.5.3`만 검증하고, 예비창업 전용 `3.5.4`는 초기창업 검증 대상에서 제외했다.
- `3.5.3`은 원본 사업비 행, 산출근거, 정부지원사업비 합계와 `_strategy_limits.supportLimit`을 확인한다.
- `3.5.2`와 `3.6.2`는 일정표의 필수 컬럼·행·기간을 확인하며 `featureList` 전체 반복 여부를 실패 조건으로 사용하지 않는다.
- `3.3.6`은 USER_FLOW와 SERVICE_ARCHITECTURE 두 이미지 명세와 각 명세의 3~6개 nodes를 확인한다.
- F19 LLM 응답이 실제 저장 구조와 불일치할 때 구조 검증 결과를 우선한다. 실제 표가 저장됐으면 표 누락 진단을 제거하고, 두 이미지 명세가 저장됐으면 이미지 구조 누락 진단을 제거한다.
- 제안값·확인 필요·시험조건 미확정은 warning으로 남기며, 필수 구조·마감일 초과·예산 상한 초과만 fail로 유지한다.

초기창업 계약에 `3.5.4`가 다시 들어오는 것을 방지하는 회귀 테스트를 포함해 총 18개 테스트가 통과했다.
### 검증 정책 버전 및 구조 재검토 보완 (2026-10-02)

- 검증 결과 재사용 조건은 `contentHash`와 `policyVersion`의 일치 여부로 관리한다. 판정 규칙을 수정하면 `validation_rubric.json` 버전을 올려 기존 결과를 반드시 재검증한다.
- 실제 표의 필수 컬럼·행이 존재하는데 F19가 `필수 표 없음`, `content.tables 없음`, `표 형식 텍스트만`으로 판정하는 경우 구조 검증을 기준으로 오탐을 제거한다.
- 실제 `imageSpecs`에 USER_FLOW·SERVICE_ARCHITECTURE가 모두 존재하면 서비스 구조도 누락을 실패로 처리하지 않는다.
- 이 보정은 전체 실행뿐 아니라 기존 결과 검증·조립 API와 선택 항목 검증에도 적용된다.
- 현재 정책 버전은 `2026-10-02.12`이다. 제안값·근거 보완·시험조건 미확정은 warning으로 남기고, 실제 구조·한도·마감일 위반만 fail로 유지한다.
