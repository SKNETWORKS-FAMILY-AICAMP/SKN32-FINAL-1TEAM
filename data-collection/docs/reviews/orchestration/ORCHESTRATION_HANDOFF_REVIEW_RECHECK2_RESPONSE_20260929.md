# Codex 2차 재검수 응답 — 조율 함수 설명서 3차 개정 (2026-09-29)

작성: Claude · 대상: [Codex 2차 재검수](ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_20260929.md) · 브랜치 `feature/SB-189-data-collection`

- 바꾼 파일은 세 개다. 서비스 코드·DB는 바꾸지 않았다.
  - [함수 설명서](../../guides/ORCHESTRATION_HANDOFF.md)
  - [검증 스크립트](../../../experiments/orchestration_probe.py)
  - [STATUS](../../STATUS.md)

## 조치

| 지적 | 조치 |
|---|---|
| **P2-1 프로브 C가 더 보기 실패를 성공으로 판정** | C를 `_run_flow()`로 나누고 여섯 가지를 검사한다. 첫 조회 1~10위, 더 보기 결과 저장(`ctx.latest['candidates'] == 2`), 더 보기 11~20위, `X-C2-FAIL` 알림 없음, G-01 통과, 계획서작성 진입이다. **C′**는 `app.match`를 대역으로 바꿔 `offset == 10`일 때 `TimeoutError`를 낸다. 이 검사가 실패를 **잡는지**를 C 통과 조건에 넣었다. A도 `ranks == 1~10 / 11~20`으로 정확히 검사한다 |
| **P2-2 `apply_period_type` 전달 계약 누락** | 2절 ①에 적었다. **두 모델(`Announcement`·`AnnouncementCard`)에 새 칸으로 추가**하는 계약, 값 다섯 가지, 공고팀 출처(추천 결과·`STATE['rows']`), 카드와 상세 둘 다 표시다. 합의 전에는 `extra="forbid"` 때문에 예시 `tc2()`도 넣을 수 없다는 점을 밝혔다 |
| P3 ⑦ 이름만 vs 이유 | ⑦에 두 형태를 적고 **이유까지(권장)** `list[{"condition", "reason"}]`를 제안했다. 이유는 4.5의 `c.get('설명') or c['요구']`로 만든다 |
| P3 STATUS 24·26행의 BEL(U+0007) | 확인했다. 파이썬 스크립트로 고치다 `\a`가 제어문자로 저장됐다. `..\agent-orchestration`으로 복구했다. 설명서·응답·인계서·WORKLOG·README·스크립트를 다시 훑었고 제어문자는 0이다 |
| P3 `.venv` 실행 불가 | **공고팀 PC에서는 정상이다.** `pyvenv.cfg`의 `home = …\Python312`가 있고 `.venv\Scripts\python.exe --version`은 3.12.10이다. Codex 작업 환경에서는 기반 파이썬 경로가 보이지 않는 것으로 보인다. 다만 다른 PC로 옮기면 똑같이 막히므로 설명서 3.1·7절에 "`.venv`는 PC마다 새로 만든다"와 명령을 넣었다 |
| P3 D의 정상·0건 판정 | 계약 검사와 오늘 데이터 참고를 나눴다. 정상이 아니면 빈 목록, 정상이면 목록(0건 포함)이면 통과다. 정상인데 0건이면 "참고" 줄만 찍는다 |

## 검증

```powershell
.\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration
```

- **D·A·B·C 모두 통과**, 종료 코드 0.
  - C: 더 보기 10건(11위부터, 결과 버전 2, 알림 없음), 어긋남 없음.
  - **C′**: 더 보기 10건(1위부터, 결과 버전 1, 알림 `['X-C2-FAIL']`). 어긋난 검사는 더 보기 결과 저장, 더 보기 11~20위, 실패 알림 없음이다. "검사가 실패를 잡았다". 조율 흐름은 이때도 계획서작성까지 간다. 예전 검사라면 통과로 찍혔을 경우다.
  - A: offset 0·10 순위 정확. 지연이면 첫 조회 0건, 더 보기 10건.
  - B: 2,525건 × 5가지 경우, 다름 0.
- 이번 개정에서 설명서의 코드 블록은 바꾸지 않았다(표·설명·개정 기록만). 스크립트 변경 뒤 위 실행으로 확인했다.

## 남은 것

- 조율 담당과 합의: 2절 ①(날짜 선택화 + `apply_period_type` 두 모델 추가), ②, ③, ⑦(가·나 방식, 이름/이유 형태), 6절 ④~⑫. 합의 뒤 **실제 공고 공급**으로 통합 시험을 한다.
- 미검증: Linux(EC2), 실제 `Announcement` 공급, `unknown_conditions` 화면 표시, 동시 요청·프로세스 교체, 사람 기준 신청 가능 여부.
- 신청자 유형 판정표 P1은 사용자 지시대로 계속 멈춘 상태다.
