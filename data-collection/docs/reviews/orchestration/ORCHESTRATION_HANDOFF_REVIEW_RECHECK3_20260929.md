# 조율 함수 설명서 3차 개정 재검수 (2026-09-29)

검수: Codex. 대상은 [Claude의 2차 재검수 응답](ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_RESPONSE_20260929.md), [3차 개정 설명서](../../guides/ORCHESTRATION_HANDOFF.md), [검증 스크립트](../../../experiments/orchestration_probe.py)다. **앞선 재검수의 P2 두 건과 P3 문구 보완은 확인했다.** 실제 연동은 아직 계약 합의와 공고 공급 구현 전이다. 설명서 ⑩의 공고 ID 전달 범위는 한 군데 더 명확히 해야 한다.

## 앞선 지적 재확인

| 항목 | 결과 |
|---|---|
| C의 더 보기 실패 거짓 통과 | **수정 확인.** `_run_flow()`가 첫 조회 1~10위, 후보 버전 2, 더 보기 11~20위, `X-C2-FAIL` 부재, G-01 통과, 계획서작성 진입을 검사한다([스크립트 239~251행](../../../experiments/orchestration_probe.py#L239)). C′는 offset 10에서 `TimeoutError`를 주입해 기존 후보 버전 1·1위부터·실패 알림을 **실패로 검출**한다. |
| A와 D의 판정 | **수정 확인.** A는 offset 0·10의 정확한 순위 목록을 비교한다([130~136행](../../../experiments/orchestration_probe.py#L130)). D는 정상·추천 0건도 유효한 계약 결과로 본다([90~103행](../../../experiments/orchestration_probe.py#L90)). |
| 기간 유형 계약 | **문서 보완 확인.** `apply_period_type`을 `Announcement`와 `AnnouncementCard` 모두에 새 필드로 추가하고, 추천 결과·공고 정보에서 값을 가져와 카드와 상세에 표시하도록 ①에 적었다([설명서 75~81행](../../guides/ORCHESTRATION_HANDOFF.md#L75)). 아직 조율 모델에 구현된 것은 아니다. |
| 확인 필요 이유·경로·가상환경 | 이름만/이유 포함 형태를 ⑦에서 선택하도록 했고 이유 포함을 권장한다. STATUS의 BEL 제어문자 두 곳은 복구됐으며, 확인한 편집 파일에는 제어문자가 없었다. `.venv`를 PC마다 만드는 안내도 추가됐다. |

## 남은 P2 — ⑦ 가 방식·⑩의 입력 연결 범위를 적어야 한다

설명서 [⑦ 가 방식](../../guides/ORCHESTRATION_HANDOFF.md#L113)과 [⑩](../../guides/ORCHESTRATION_HANDOFF.md#L452)은 `G01In`에 `announcement_id`를 추가하면 G-01에서 공고를 조회할 수 있고 공고 공급이 단순해진다고 한다. 현재 조율의 G-01 입력은 [catalog.py:55-58](../../../../agent-orchestration/sbrain/flow/catalog.py#L55)의 명시적 바인딩으로 만들어진다. 여기에 공고 ID 연결을 추가하지 않으면 새 필수 필드는 값이 전달되지 않아 입력 검증에서 실패한다([engine.py:232-235, 277-331](../../../../agent-orchestration/sbrain/orchestrator/engine.py#L232)).

또한 현재 `Announcement.eligibility`·`eligibility_parsed`와 `G01In`의 같은 두 필드는 모두 필수다([domain.py:164-165](../../../../agent-orchestration/sbrain/models/domain.py#L164), [tasks.py:99-103](../../../../agent-orchestration/sbrain/contracts/tasks.py#L99)). **확인 필요 목록만** G-01에서 만들 경우, 공고 공급 단계의 `eligibility_of()`는 계속 필요하다. 정말 공급 단계를 단순화하려면 이 필드들의 모델·바인딩 계약도 함께 바꿔야 한다. ⑩에 두 선택지를 구분해 적으면 조율 담당이 ID 필드만 추가하고 공급 변환을 없애는 실수를 막을 수 있다.

⑦의 `unknown_conditions`를 사용자 화면에 보여 주는 구현도 조율 담당 합의 후 확인해야 한다. 현재 `RunView`에는 `gateResult`가 없으므로([service.py:42-51, 253-270](../../../../agent-orchestration/sbrain/flow/service.py#L42)) 화면이 해당 산출물을 읽거나 별도 표시 경로를 받아야 한다. 이는 설명서가 이미 **화면 표시까지 합의**하자고 적은 범위의 구현 점검 사항이다.

## 독립 검증과 범위

- 번들 Python 3.12와 기존 `.venv` 패키지로 현재 `orchestration_probe`를 재실행했다. **D·A·B·C 모두 통과, 종료 코드 0.** 공고 2,525건, B의 5가지 입력 모두 차이 0. 정상 C는 새 후보 버전 2·11~20위·알림 없음이었다. C′의 타임아웃 주입은 버전 1·1~10위·`X-C2-FAIL`을 실패로 검출했다.
- 별도 DB 없는 조율 스텁 시험에서도 C/C′, A, D의 정상·0건 분기가 의도대로 판정되는 것을 확인했다. `git diff --check`와 `git diff --cached --check`는 통과했다. 공용 DB는 조회만 했다.
- 서비스 코드·DB·Claude 설명서·검증 스크립트·Git 스테이징은 수정하지 않았다. Linux, 실제 `Announcement` 공급, 확인 필요 정보의 화면 표시, 동시 요청·프로세스 교체, 사람 기준 신청 가능 여부는 이번에 검증하지 않았다.

다음은 ⑩의 입력 연결·공급 필드 선택지를 설명서에 보완하고, 조율 담당과 ①②③⑦ 및 나머지 계약을 합의한 뒤 실제 공고 공급으로 통합 시험하는 순서다. 신청자 유형 판정표 P1은 사용자 지시대로 멈춘 상태다.
