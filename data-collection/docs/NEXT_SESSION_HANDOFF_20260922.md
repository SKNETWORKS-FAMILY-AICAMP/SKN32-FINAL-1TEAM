# 다음 세션 인수인계 — 업종 추출·정형 매칭

기준 시점: 2026-09-22 작업 종료  
작업 범위: `data-collection/`만 사용  
담당 목표: 공고 데이터 수집·정형화와 `MySQL 정형 필터 → Embedding similarity → Rule/수식 → Top N`

## 1. 다음 세션이 가장 먼저 읽을 것

1. 이 문서
2. [업종 Luna 전량 리뷰](INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md)의 맨 아래
   `2차 후속 재검토 — 제외 머리말·남은 104건 재독·final4`
3. [현재 상태](STATUS.md)의 `2026-09-22 종료 인계`
4. 세부 실행 이력이 필요할 때만 [WORKLOG](WORKLOG.md) 최신 항목

과거 `final`, `final2`, `final3`은 변경 과정을 확인하기 위한 보존본이다. 새 작업의 기준 결과는 반드시 `final4`다.

## 2. 현재 목표와 역할

- 공고 데이터: K-Startup·기업마당 수집, 지원대상 정형화, 기술 분야 조건 판별, 공고 요약 임베딩, 수집 상태 확인.
- 매칭·자격 판정: 정형 필터, 임베딩 유사도, 규칙/수식 순위, 첫 조회 10건·최대 20건 후보 기준.
- 업종 처리의 목적은 신청자의 `주업종`과 공고의 허용·제외 업종을 안전하게 비교하는 것이다.
- 불확실한 값은 후보에서 조용히 제거하지 않는다. 확실한 불일치만 정형 게이트로 제외하는 원칙을 유지한다.

## 3. 현재 구현 흐름

```text
공고 원문·첨부
  → Luna가 허용 업종 / 제외 업종 / 근거 / 목록 완전성 추출
  → 코드 검증(원문 근거, 자격 문장 역할, 제외 문맥)
  → 매칭용 판정
     known / no_limit / not_mentioned / excluded_only / conditional / unknown
  → 업종 원문 표현을 KSIC 대분류 A~U, X, ALL로 규칙 매핑
  → /industry-results에서 결과·근거·묶음·잘림 여부 확인
```

이 결과는 아직 DB에 적재하지 않았고 `filter_ready=true`도 0건이다. 즉 실험·검수 단계이며 실제 자동 탈락 필터가 아니다.

## 4. 최신 기준 결과 final4

- 결과 폴더: `reports/industry_llm_full_luna_20260922_final4/`
- 화면: `http://127.0.0.1:8010/industry-results`
- 모델: `gpt-5.6-luna@medium`
- 공고 1,852건, 고유 ID 1,852개, API 실패 0, DB 쓰기 0.
- 출처: 기본 1,651건 + 18,000자 재독 97건 + 추가 재독 104건.
- 토큰: 입력 6,394,949 / 출력 1,472,128.
- 기록 단가 기준 원답 비용 합: 약 `$3.0455`.

| 매칭용 판정 | 건수 |
|---|---:|
| 업종 제한 있음 | 616 |
| 제한 없음(언급 없음·추정) | 817 |
| 제외 업종만 | 243 |
| 제한 없음(명시) | 4 |
| 조건부·세부사업별 | 16 |
| 확인 필요 | 156 |

- 18,000자에서도 상한에 닿은 행은 최종 결과 전체에서 12건이며 모두 `truncated=true`, `list_complete=false`다.
- 상한 도달 12건 중 3건은 `known`, 1건은 `excluded_only`다. 향후 필터는 status만 보지 말고 완전성까지 확인해야 한다.
- final3→final4 비교에서 long104의 104건만 의미적으로 바뀌었고 나머지 1,748건은 같다.

## 5. 이번까지 해결된 것

- 최종 상태가 `known`이 아니면 `allowed`를 비우는 상태/값 불변식.
- 규모·형태 표현(`사회적기업` 등)을 업종값에서 제거.
- dropped 허용·제외 후보가 있는데 `not_mentioned`로 올라가던 문제. final4의 `not_mentioned` 중 dropped/raw allowed 잔존은 0건.
- 6,000자에서 잘린 나머지 104건까지 18,000자로 재독.
- 여러 번 합쳐도 `source_run`, `merge_history`, 토큰, 비용을 누적하는 merge.
- 대표 KSIC 반례:
  - `정보서비스업(72) → J`
  - `양식장`, `패류 양식 어가 → A`
  - `음식료품 도매업 → G`
  - `건설업 및 제조업 → F,C`
- `/industry-results`에서 final4 기본 선택, 판정·업종 묶음·목록 완전성·발췌 잘림 표시.
- Codex 독립 실행 기준 업종 추출·묶음 테스트 120개 통과.
- Claude 기록 기준 전체 테스트 464개 통과(건너뜀 13). Codex 환경에서는 FastAPI 의존성이 없어 전체 수치는 독립 재현하지 못했다.

## 6. 다음 주에 먼저 고칠 것

### F1-1. 통합공고의 전역 판정 방지

- 파일: `experiments/sql_semantic/industry_llm_sample.py`, `industry_status()`.
- 현재 `통합 공고` 보호가 raw `known`에만 적용된다.
- 제목이 통합공고인 25건 중 `conditional` 10, `unknown` 7, `not_mentioned` 7, `excluded_only` 1건이다.
- 세부사업 범위를 보존하지 못한 통합공고 7건을 “업종 언급 없음”, 1건을 “제외 업종만”으로 전역 해석하면 안 된다.

완료 기준:

1. 통합공고 guard를 `known` 분기 밖에서 적용한다.
2. 범위를 복원하지 못한 `not_mentioned/excluded_only` 통합공고는 최소 `unknown`, 가능하면
   `conditional + scope_unresolved=true`로 둔다.
3. known, raw unknown+quote, 제외값만 있는 통합공고를 각각 테스트한다.

### F1-2. 제외표 참조문과 실제 제외 업종 분리

- 파일: `experiments/sql_semantic/industry_llm_sample.py`, 제외값 검사 부분.
- `지원제외 업종`, `정책자금 융자제외 대상 업종`, `창업에서 제외되는 업종` 같은 목록 제목·붙임 참조도 실제 업종처럼 저장된다.
- final4에서 `excluded_only`이면서 이런 일반 참조문만 가진 행이 보수적으로 25건이다.
- 예: `bizinfo:PBLN_000000000119739`, `...120031`, `...124560`, `...126566`.

완료 기준:

1. 구체 업종명/KSIC 코드와 `제외표 참조`를 구분한다.
2. 참조된 붙임·법령의 업종표를 추출하지 못하면 `unknown` 또는 `excluded_reference_only`로 둔다.
3. 구체 업종 없이 참조문만 있는 결과는 매칭 통과값으로 쓰지 않는다.

### F2-1. KSIC 복합 명칭과 실제 미분류값 보강

- 파일: `experiments/sql_semantic/industry_groups.py`.
- `및·쉼표·가운뎃점`을 먼저 나눠 공식 복합 명칭이 깨진다.
- 실제 반례:
  - `전문· 과학·기술 → []`
  - `전문·과학 및 기술서비스업 → X`이지만 기대는 M
  - `측량업`, `농작물 재배업`, `종합 또는 일반테마파크업`
  - `390 환경정화 및 복원업`, `714 시장조사 및 여론조사업`, `창업·경영컨설팅`
- final4 허용값 1,798개 중 값 단위 미분류는 167개다.

완료 기준:

1. KSIC 공식 대분류명과 자주 나오는 복합 구를 split보다 먼저 처리한다.
2. 위 반례를 회귀 테스트에 추가한다.
3. 새 규칙은 다른 분류를 훼손하지 않는지 실제 final4 전체 값으로 전후 집계한다.

### F2-2. 화면 안내와 coverage 지표 정정

- 파일: `web/industry_results.html`, `experiments/sql_semantic/industry_results.py`.
- 화면은 아직 “97건 재독”이라고만 적혀 있지만 final4는 총 201건을 재독했다.
- 최종 18,000자 상한 도달은 12건이다.
- “못 묶음 14건”은 공고 전체에 묶음이 하나도 없는 경우만 세므로 부분 미분류 167개가 드러나지 않는다.

완료 기준:

1. 재독 수는 `merge_history`, 잔여 잘림은 결과 행에서 계산한다.
2. 공고 단위 coverage와 함께 `허용값 총수 / 미분류 값 수`를 표시한다.

## 7. 권장 재개 순서

1. 위 F1 두 건의 테스트를 먼저 추가하고 코드를 수정한다.
2. F2 KSIC 반례와 화면 지표를 수정한다.
3. 저장된 checkpoint를 사용해 검사만 오프라인으로 다시 적용한다. **검증기·묶음·화면 수정에는 Luna 재호출이 필요 없다.**
4. 6,000자 기준 전량 결과, long97, long104를 각각 새 폴더로 재검사한 뒤 순서대로 합친다. 기존 결과 폴더는 덮어쓰지 않는다.
5. 최종 행 수·ID·출처·토큰·비용·상태/값 불변식을 다시 확인한다.
6. `/industry-results`에서 통합공고, 제외표 참조, M 복합 명칭, 잘림 행을 직접 확인한다.
7. 새 결과를 DB나 정형 필터에 연결하기 전에 별도의 사람 검증 표본으로 status·허용값·제외값·목록 완전성을 평가한다.

## 8. 다음 주에 하지 말아야 할 것

- 과거 `final/final2/final3`을 최신 결과로 되돌리지 않는다.
- 기존 결과 폴더를 덮어쓰지 않는다.
- 코드 후처리만 바꿨는데 Luna 1,852건을 다시 호출하지 않는다.
- `not_mentioned`를 명시적 제한 없음과 같은 강한 통과 조건으로 쓰지 않는다.
- `excluded_only`라는 상태만 보고 구체 제외 목록이 완전하다고 가정하지 않는다.
- `industry_status`만 보고 잘린 `known`을 필터에 쓰지 않는다.
- 사람 정답셋 없이 “정확도 검증 완료” 또는 “운영 적용 가능”이라고 결론 내리지 않는다.
- 사용자 요청 없이 DB 적재, Git commit, push를 하지 않는다.

## 9. 검증·화면 진입점

- 핵심 코드:
  - `experiments/sql_semantic/industry_llm_sample.py`
  - `experiments/sql_semantic/industry_groups.py`
  - `experiments/sql_semantic/industry_results.py`
  - `web/industry_results.html`
- 핵심 테스트:
  - `tests/test_industry_llm_sample.py`
  - `tests/test_industry_groups.py`
  - `tests/test_industry_results_ui.py`
- 결과 리뷰: `docs/INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md`
- 상세 변경 이력: `docs/WORKLOG.md`
- 로컬 검증 화면 서버가 종료돼 있으면 의존성이 갖춰진 프로젝트 Python으로
  `python -X utf8 -m experiments.sql_semantic.viewer`를 `data-collection/`에서 실행한다.

## 10. 재개 시 첫 요청문 예시

> `data-collection/docs/NEXT_SESSION_HANDOFF_20260922.md`와 업종 Luna 리뷰 문서의 마지막 재검토를 먼저 읽어라.
> final4를 기준으로 F1-1 통합공고 전역 판정과 F1-2 제외표 참조문 문제부터 테스트 주도로 수정하라.
> 기존 결과를 덮어쓰거나 Luna API를 재호출하거나 DB에 쓰지 말고, 저장 checkpoint 오프라인 재검사까지 수행한 뒤
> 결과와 화면을 검증하고 WORKLOG에 기록하라.

## 11. 이번 종료 시점의 결론

현재 결과는 이전보다 크게 개선됐고 데이터·출처 무결성도 정상이다. 그러나 통합공고 범위와 제외표 참조문 두 F1 때문에
신청자 주업종 정형 게이트로는 아직 승인하지 않는다. 다음 주의 첫 목표는 새 기능 추가가 아니라 이 두 의미 오류를 제거하고,
그 결과를 사람 표본으로 검증 가능한 상태까지 만드는 것이다.
