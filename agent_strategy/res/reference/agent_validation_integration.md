# 전략·작성 Agent ↔ 검증 1 통신 계약

## 책임 분리

- 전략·작성 Agent는 back 입력을 정규화하고 F01~F15 전략 결과와 F16~F18 작성 결과를 만든다.
- 검증 1 Agent는 생성 결과의 구조, 원본 근거, 공고 기준, 일정·예산 한도와 의미를 판정한다.
- 전략·작성 Agent는 검증 규칙을 복사해 판정하지 않고 검증 1의 결과를 재작성·조립 흐름에 사용한다.

## 호출 흐름

```text
back JSON
  → normalize_back_input
  → F01~F15 전략·조사
  → 항목별 sourceKeys 선택
  → F16 본문 / F17 표 / F18 이미지 명세
  → agent_validation_1.validate_section (F19)
  → pass면 F20 조립, fail이면 선택 항목 회귀 재작성
```

## F19 입력 계약

```json
{
  "section_spec": "section_mapping.json의 항목 계약",
  "content": {
    "generatedText": "생성 본문",
    "tables": [],
    "images": [],
    "sourceRefs": [],
    "facts": []
  },
  "source_data": {
    "originalFacts": {},
    "strategyProvenance": {},
    "sourceRefs": [],
    "_strategy_limits": {
      "deadline": "공고별 마감월",
      "supportLimit": "공고별 지원금 상한",
      "featureList": []
    }
  }
}
```

## F19 출력 계약

```json
{
  "agent": "검증 1",
  "status": "pass | warning | fail",
  "issues": [],
  "warnings": [],
  "needsUserConfirmation": [],
  "sourceRefs": [],
  "contentHash": "검증 대상 해시",
  "policyVersion": "validation rubric 버전"
}
```

- `fail`: 필수 계약·확정 사실·마감일·지원금 상한 위반. F20 조립을 막고 재작성 대상으로 남긴다.
- `warning`: 제안값·근거 보완·시험조건 미확정. 조립은 가능하지만 평가 점수에 감점으로 반영한다.
- `pass`: 현재 계약과 검증 기준을 충족한다.

## 회귀 재작성

사용자가 특정 항목을 선택하면 `/api/retry` 또는 `/api/retry-latest`가 호출된다. `impact_plan`이 동일 Canonical Data를 사용하는 연관 항목을 계산하고, 필요한 F16~F18만 재실행한 뒤 F19를 다시 호출한다. F01~F15 전략 함수는 자동으로 반복하지 않는다.

검증 정책이 변경되면 `policyVersion`이 달라져 기존 검증 결과를 재사용하지 않는다. 본문이 변경되면 `contentHash`가 달라져 해당 항목을 다시 검증한다.

## 결과 전달

실행 폴더의 `result.json`에는 항목별 `validation`, `evaluation`, 전체 `validation1`, `evaluationSummary`가 저장된다. 별도 `validation.json`에는 검증 결과를 분리 저장한다. 전략·작성 Agent는 이 결과를 back이 읽을 수 있는 실행 폴더에 보존한다.
## Orchestrator T-C3 지시문 연동 (2026-10-06)

Orchestrator T-C3의 `instruction`과 `rework_input` 입력 타입은 기존 Task 계약과 동일하게 문자열·기존 재작성 입력 구조를 유지한다. 전략·작성 Agent는 지시문을 임의로 분해하거나 머리말을 변경하지 않고 전달받은 문자열을 그대로 사용한다.

Orchestrator가 전달하는 지시문은 다음 세 부분을 순서대로 포함할 수 있다.

1. `[작업 틀]`: 기준 문서의 고정 규칙
2. `[작업 안내]`: 아이템·공고에 맞춘 조율 안내
3. `[참조 자료]`: 해당 Task에 배정된 근거 자료

전략·작성 Agent는 작업 틀의 규칙을 최우선으로 적용하고, 작업 안내와 참조 자료는 그 범위 안에서 사용한다. 재작성·재수행 시에는 Orchestrator가 작업 안내만 교체하고 문제 원문을 끝에 덧붙이므로, Agent 쪽에서 기존 지시문을 새 틀로 다시 조립하지 않는다. 로컬 테스트 서버의 직접 실행 경로는 Orchestrator가 없으므로 기존 `instruction` 문자열을 사용하며, 실제 통합 실행에서는 T-C3가 만든 지시문을 그대로 전달받는다.

## 기획서 v1.10의 2층 검증과 현재 구현의 경계

기획서의 2층 구조는 전체 서비스 기준이다. 문서층은 전략·작성 결과를 검증 1(T-V1/F19)이 평가하고, 산출물층은 프로토타입·인포그래픽을 검증 2(T-V2)가 코드 규칙과 기능 대조로 평가한다. `agent_strategy`의 로컬 테스트 서버는 문서층 범위(F01~F20)를 검증하는 독립 테스트 경로이므로 검증 2나 프로토타입 생성을 대신하지 않는다.

전체 서비스 실행에서는 `agent-orchestration`이 다음 사용자 판단 경계를 관리한다.

```text
전략·작성 → F19/검증 1 → 사용자 판단 → 구현·프로토타입 → 검증 2 → 사용자 판단 → 검수·최종 조립
```

로컬 전략·작성 테스트의 `F20`은 F19가 실패한 항목이 없을 때만 문서 조립을 수행한다. 이 조립 완료를 전체 서비스의 최종 제출 가능 판정으로 해석하지 않으며, 프로토타입이 생성된 뒤에는 반드시 T-V2의 산출물층 결과와 종합 점수를 사용한다. 문서층 점수는 내부 품질 평가이며, 기획서의 문서층 70점·산출물층 30점 총점과 직접 혼용하지 않는다.

F19는 완전한 LLM 단독 판정이 아니라 구조·계약·한도 사전 검사와 의미 검증을 결합한 문서층 검증이다. 구조 검사는 필수 표·이미지·항목 수·원본 대조·마감일·예산 상한을 먼저 확인하고, 통과 가능한 항목에만 의미 검증을 호출한다. 이 차이를 기획서의 `LLM 판정(검증-1)` 설명에 반영해야 하며, 실제 구현은 재현 가능한 저비용 규칙 검사를 함께 사용한다.

## 규정 근거의 결과 기록

규정 파일의 내용을 사업계획서 본문에 기계적으로 삽입하지 않는다. 항목별 기준은 작성 제약과 F19 검증 기준으로 사용하고, 결과 JSON의 `validation.criteria`에 `criteriaApplied`, `sourceMappings`, `sourceRefs`를 남긴다. 따라서 `어떤 파일의 어떤 주제·검색어를 적용했는지`를 provenance로 확인할 수 있으며, 본문은 제출 양식에 맞는 자연스러운 문체를 유지한다.

`validation.criteria.evidence`에는 각 규정 파일의 경로, 검색 키워드, 해당 키워드 주변의 짧은 근거 문자열이 저장된다. 이 발췌는 F19 프롬프트에도 전달되므로 판정 근거를 파일 단위로 추적할 수 있다. 파일 전체를 전송하지 않고 파일별 발췌 수를 제한해 토큰 사용량을 통제한다.
