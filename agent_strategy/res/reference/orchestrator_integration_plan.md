# 오케스트레이터 연동 계획

이 문서는 전략·작성 Agent와 검증 1을 `agent-orchestration`에 연결할 때의 작업 순서를 기록한다. 현재 로컬 F01~F20 실행 코드는 오케스트레이터 규격에 맞추기 위해 변경하지 않는다.

## 현재 유지 범위

로컬 테스트는 다음 흐름을 유지한다.

```text
F01~F15 전략·조사
→ F16/F17/F18 작성·표·이미지 명세
→ F19 검증 1
→ F20 문서 조립
```

이 결과는 문서층 테스트 결과이며, 산출물층 T-B1/T-B2/T-V2의 결과를 대신하지 않는다.

## 오케스트레이터 연결 시 필요한 어댑터

### 전략·작성 Agent

| 오케스트레이터 필드 | 로컬 결과와의 연결 |
|---|---|
| `plan_doc` | F16/F17/F20의 본문·표·조립 결과를 계획서 문서로 변환 |
| `feature_list` | F02의 전략 확정 기능 목록과 연결 |
| `item_spec` | F02 `item_spec` 연결 |
| `instruction` | 오케스트레이터가 합성한 `[작업 틀]·[작업 안내]·[참조 자료]`를 그대로 전달 |
| `rework_input` | F19 실패 사유, 재작성 횟수, 최종 시도 여부 전달 |
| `previous_source_text` | 재작성 대상의 이전 HTML 원문 전달 |

### 이미지 Agent

현재 F18은 USERFLOW와 SERVICE_ARCHITECTURE의 SVG 명세를 생성한다. 오케스트레이터 T-B2는 `tools.image()`를 사용해 PNG를 생성하므로 다음 변환을 별도로 둔다.

```text
F18 이미지 명세
→ T-B2 이미지 지시문
→ tools.image()
→ PNG 산출물
→ T-V2 검증
```

F18 SVG와 T-B2 PNG를 동일한 출력으로 취급하지 않는다.

### 검증 1

로컬 F19 호출 형식은 다음과 같다.

```python
validate_section(section_spec, content, source_data)
```

오케스트레이터 T-V1 연결 시에는 다음 변환을 추가한다.

```text
plan_doc
→ section별 content 분리
→ criteria_registry·validation_rubric 적용
→ F19 검증
→ T-V1의 doc_score·items·variance_flag 형식으로 변환
```

## 예외 처리 원칙

오케스트레이터 연결 시 `ToolCallExhausted`를 일반 Task가 임의로 성공 처리하지 않는다.

- T-S/T-W/T-B1/T-V1: 예외를 상위 Orchestrator로 전달
- T-B2: `tools.image` 실패에 한해 기본 아이콘 대체 가능
- T-B2의 글 호출 실패: 상위로 전달

현재 로컬 테스트 서버의 부분 결과 저장과 대체 모델 처리는 로컬 실행 범위에서만 유지한다.

## 지시문 중복 방지

오케스트레이터가 이미 재작성 문제 내용을 지시문에 포함하므로 Agent가 같은 문제를 다시 덧붙이지 않는다.

```text
[작업 틀]

[작업 안내]

[참조 자료]

[재작성 — 문제가 된 내용]
```

Agent는 전달받은 `instruction`을 그대로 사용하고, 별도 재작성 문구를 중복 생성하지 않는다.

## 연결 시점

다음 조건이 충족된 후 어댑터 코드를 구현한다.

1. 일반·예비·초기 유형의 F01~F20 결과 구조 확정
2. `result.json`의 `validation`, `evaluation`, `sourceRefs`, `evidence` 구조 확정
3. 검증 1의 규정 근거 저장 확인
4. `plan_doc`, `previous_source_text`, `partial_features` 매핑 설계 완료
5. 오케스트레이터 통합 테스트용 입력·출력 fixture 준비

그 전까지는 현재 로컬 실행 코드를 변경하지 않는다.

## 점수 경계

검증 1의 내부 문서 품질 점수와 오케스트레이터의 전체 점수를 혼용하지 않는다.

```text
문서층: T-V1/F19
산출물층: T-V2
전체 점수: 오케스트레이터가 문서층·산출물층을 조합
```

F20 조립 완료는 전체 서비스의 최종 제출 가능 판정이 아니다.
