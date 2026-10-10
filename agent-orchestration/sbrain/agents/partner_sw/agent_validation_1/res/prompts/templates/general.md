# 일반 사업계획서 검증 기준

## 검증 범위
- 문제·해결·목표 고객·개발방법·사업화가 서로 모순되지 않는지 확인한다.
- 원본에 없는 수치·실적·고객·기술은 proposed 또는 needs_confirmation으로 표시했는지 확인한다.
- 기능명·기술명은 표현 차이를 정규화해 비교하고, 핵심 의미가 보존되면 단순 문구 차이로 fail시키지 않는다.
- 확정 사실은 sourceRefs와 originalFacts로 추적할 수 있어야 한다.
- 일정은 _strategy_limits.deadline을 넘지 않고 예산은 supportLimit을 초과하지 않아야 한다.
- `sourceRefs`, `evidence`, `originalFacts`가 없는 제안 계획은 확정 사실이 아니라 warning으로 기록한다.

## 판정
구조·필수 항목·확정 사실 오류는 fail로 분류한다. 제안값·시험 조건 미정·보완 요청은 warning과 needsUserConfirmation으로 분류한다.
