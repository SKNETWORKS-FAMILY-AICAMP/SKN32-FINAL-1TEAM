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
