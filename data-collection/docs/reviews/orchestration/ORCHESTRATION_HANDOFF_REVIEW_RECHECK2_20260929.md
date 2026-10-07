# 조율 함수 설명서 2차 개정 재검수 (2026-09-29)

검수: Codex. 대상은 [Claude 재검수 응답](ORCHESTRATION_HANDOFF_REVIEW_RECHECK_RESPONSE_20260929.md), [함수 설명서](../../archive/ORCHESTRATION_HANDOFF.md), [검증 스크립트](../../../experiments/orchestration_probe.py)다. 조율 코드는 현재 저장소 `agent-orchestration/`을 기준으로 대조했다. **이전 재검수의 P2 네 건은 설명서에 반영됐다.** 다만 검증 스크립트가 더 보기 실패를 통과로 판정할 수 있고, 실제 기간 표시 계약은 아직 완결되지 않았다. 실제 연결 완료 판정은 보류한다.

## 이전 P2 네 건의 반영

| 항목 | 재검수 결과 |
|---|---|
| P2-1 확인 필요 목록 출처 | ⑦에 공고 ID를 G-01에 넘기는 가 방식과 공급 단계에서 계산하는 나 방식을 적고, 가 방식을 권장했다. 현재 `G01In`과 `GateResult`에는 필요한 칸이 없으므로 **합의안**이지 구현 결과는 아니다. `app.eligibility()`가 실행일을 기준으로 판정한다는 제한도 명시했다. |
| P2-2 수집 비정상·빈 결과 | 빠른 시작 `recommend()`가 비정상 상태에 `(status, [])`, 정상·0건에 `('정상', [])`를 돌려준다. D의 두 대역 경로도 실행됐다. `tc2()`는 현재 조율 `start_run`만 상태를 차단하고 MORE는 차단하지 않는 흐름에 맞춰 첫 조회에서만 빈 카드를 준다. 더 보기 중 지연을 차단하려면 조율 흐름도 함께 바꿔야 한다는 점을 설명했다. |
| P2-3 접수 시작 전 공고 | 4.5절에서 접수기간의 `X`를 확인 필요 목록에서 빼고, `start is not None and start > 오늘`일 때만 접수 예정으로 표시한다. 이유 문장의 `설명` 누락에는 `c.get('설명') or c['요구']`를 쓴다. |
| P2-4 기간 필드·운영 메모리 | 필수 날짜 칸 세 곳과 `service.py` 비교, 스텁 `isoformat()` 사용처를 적었다. 4GB 서버에서는 기존 프로세스를 먼저 종료하는 재시작 방식을 권한다. 동시 프로세스 교체는 메모리 측정 후 선택하도록 고쳤다. |

## 보완할 사항

### P2-1. 프로브 C가 더 보기 실패를 성공으로 판정한다

[검증 스크립트 200~211행](../../../experiments/orchestration_probe.py#L200)은 `more_candidates()`·`advance()` 뒤 읽은 후보가 **새 결과인지** 확인하지 않고, 첫 조회 후보를 선택해 `view.step == '계획서작성'`이면 통과한다. 조율 흐름은 MORE의 T-C2가 실패하면 기존 후보를 남기고 공고선택으로 돌아간다([sbrain_flow.py:233-239](../../../../agent-orchestration/sbrain/flow/sbrain_flow.py#L233)).

DB 없이 MORE 조회에 `TimeoutError`를 주입해 재현했다. 실제 더 보기는 실패했는데 출력은 `더 보기 10건(1위부터)`였고 `check_flow()`는 `True`를 반환했다. C의 통과 조건에 새 후보의 순위가 11위부터인지, 새 결과가 저장됐는지, MORE 실패 알림이 없는지를 넣어야 한다. A도 [130행](../../../experiments/orchestration_probe.py#L130)에서 `>0`만 검사하므로 설명서의 “offset 0·10 각 10건”을 검증 조건으로 삼으려면 정확한 건수와 순위를 확인해야 한다.

### P2-2. `apply_period_type`을 카드와 공고 상세로 보내는 계약이 빠졌다

설명서 [① 75~78행](../../archive/ORCHESTRATION_HANDOFF.md#L75)은 날짜 없는 985건을 `apply_period_type`으로 표시하자고 제안한다. 현재 조율 `Announcement`와 `AnnouncementCard`에는 이 필드가 없고([domain.py:156-185](../../../../agent-orchestration/sbrain/models/domain.py#L156)), 예시 `tc2()`도 카드에 넣지 않는다([설명서 375~384행](../../archive/ORCHESTRATION_HANDOFF.md#L375)). 날짜 필드를 선택으로 바꾸는 합의에 **기간 유형을 두 모델과 화면에 어떻게 전달할지**까지 포함해야 제안한 표시가 가능하다.

### P3. 설명 문구와 재현 경로

- ⑦의 `unknown_conditions: list[str]`는 조건 **이름만** 전달한다([설명서 98행](../../archive/ORCHESTRATION_HANDOFF.md#L98)). 4.5절은 `(조건, 이유)`를 만드는 예시와 이유 문장 재사용을 안내한다([304~323행](../../archive/ORCHESTRATION_HANDOFF.md#L304)). 화면에 이름만 보여 줄지, 이유도 보여 줄지 정하고 후자면 전달 칸을 추가해야 한다.
- [STATUS.md 24·26행](../../STATUS.md#L24)의 `..\agent-orchestration` 경로는 실제 파일에서 `\a`가 BEL 제어문자(U+0007)로 저장되어 있다. 설명서·응답·인계서의 경로는 정상이다. STATUS의 두 줄은 수정이 필요하다.
- 설명서 [7절 명령](../../archive/ORCHESTRATION_HANDOFF.md#L456)의 `.venv\Scripts\python.exe`는 현재 PC에서 원래 Python 설치 경로가 없어 실행되지 않는다(`pyvenv.cfg`의 base executable이 없음). 이번 독립 실행은 번들 Python 3.12에 기존 `.venv/Lib/site-packages`를 넣어 진행했다. 팀원이 재실행할 수 있도록 가상환경 재생성 또는 사용 가능한 Python 경로를 준비해야 한다.
- 프로브 D의 [90행](../../../experiments/orchestration_probe.py#L90)은 정상 상태와 카드 0건을 유효하게 처리하는 빠른 시작과 달리, 실제 DB가 정상·0건이면 실패로 판정한다. 정상 데이터 스모크 검사와 0건 분기 계약 검사를 구분하면 결과가 덜 혼란스럽다.

## 독립 검증과 남은 범위

- 번들 Python 3.12 + 기존 `.venv` 패키지로 현 저장소의 `orchestration_probe` 실행: **D·A·B·C 모두 통과, 종료 코드 0**. 공고 2,525건, A offset 0·10 각 10건(1~10위, 11~20위), 지연 대역에서 첫 조회 0건·더 보기 10건, B의 2,525건 × 5입력 차이 0, C는 실제 이번 실행에서 더 보기 11위부터 10건이었다. 공용 DB는 SELECT만 했다.
- 별도 **DB 없는 실패 주입 시험**에서 MORE `TimeoutError`에도 C가 `True`를 돌려주는 거짓 통과를 확인했다. `git diff --check`와 `git diff --cached --check`는 통과했다.
- 서비스 코드·DB·설명서·스테이징은 수정하지 않았다. Linux(EC2), 실제 `Announcement` 공급, `unknown_conditions`의 화면 표시, 동시 요청·프로세스 교체, 사람 기준 신청 가능 여부는 이번에 검증하지 않았다.

다음은 Claude가 프로브 판정 조건과 문서의 두 계약 범위를 보완하고, 조율 담당과 ①②③⑦을 합의한 뒤 **실제 공고 공급**으로 통합 시험하는 순서다. 신청자 유형 판정표의 별도 P1은 사용자 지시대로 멈춘 상태다.
