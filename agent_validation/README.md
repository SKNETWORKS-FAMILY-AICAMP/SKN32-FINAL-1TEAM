# Validation 1

`validation_1.py`가 F19를 수행한다. 필수 텍스트·항목 개수·줄 수·필수 필드·표 컬럼(표가 요청된 경우)·이미지 노드·원본 facts·출처 ID·원 단위 금액을 Python으로 검사한다. 구조 오류가 없을 때만 GPT-5.6 Terra로 원본 충실성·근거 관련성·논리·항목 요구조건을 검증한다.

실패 항목은 테스트 파이프라인에서 F16/F18로 최대 1회 재작성하고 재검증한다. 여전히 실패하면 초안과 오류를 보존하되 F20 최종 조립을 실행하지 않는다. 표 생성 제외 항목은 검증 대상에서도 제외한다. 분량·페이지 수는 실제 문서 렌더링 전 확정하지 않는다.

## 실행 위치와 연결 구조

검증 1의 판정 코드는 이 폴더의 `validation_1.py`에 별도 Agent 영역으로 관리한다. 전략·작성 Agent 코드에 검증 규칙을 복사해 넣지 않는다.

현재 개발·테스트 단계에서는 `agent_strategy/runtime/pipeline.py`가 F16/F17/F18 작성 결과를 만든 뒤 `agent_validation.validation_1.validate_section()`을 호출하는 방식으로 연결되어 있다. UI 요청과 실행 상태 관리는 `agent_strategy/testing/test_server.py`가 담당한다.

```text
agent_strategy/testing/test_server.py
        ↓
agent_strategy/runtime/pipeline.py
        ├─ 전략·작성 결과 생성
        └─ agent_validation.validation_1 호출
                ↓
        검증 1 결과(validation/issues/warnings)
```

따라서 현재 검증 1은 독립된 코드 영역을 유지하면서 전략·작성 테스트 파이프라인에 연결되어 실행된다. 추후 전체 `agent-orchestration` Supervisor가 연결되면 동일한 검증 1 인터페이스를 통해 조율 Agent의 실행 흐름에 편입한다.

검증 결과는 항목별 `results[].validation`, 전체 `validation1`, 별도 `validation_results` 배열에 기록하며, 실행 폴더에는 `validation.json`을 별도로 저장한다.
# 검증 1 Agent

## 커밋 규칙

검증 1 Agent 변경은 다음 형식을 사용한다.

```text
SB-127 [FEAT] 검증1 agent - <수행 내용>
```

유형별 접두사는 `[FEAT]`, `[FIX]`, `[DOCS]`, `[TEST]`, `[REFACTOR]`, `[CHORE]` 등을 사용한다. 전략·작성 Agent 변경은 `SB-127 [TYPE] 전략/작성 agent - <수행 내용>` 형식을 사용하며, 두 Agent의 변경을 한 커밋에 섞지 않는다.
