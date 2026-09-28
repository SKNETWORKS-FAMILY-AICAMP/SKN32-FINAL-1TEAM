# Codex 검수 요청 — F1-1 통합공고 전역 판정 방지 (2026-09-28)

작성: Claude · 대상: Codex  
기준 리뷰: [업종 Luna 전량 리뷰](INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md)의 `2차 후속 재검토` → `[F1] 통합공고 보호가 known에만 적용되어 8건은 여전히 전역 판정처럼 보임`  
상세 이력: [WORKLOG](WORKLOG.md) 2026-09-28 Claude 항목

검수 중 LLM·DB 호출, 기존 결과 폴더 덮어쓰기, Git staging·commit·push는 하지 않는다.

## 1. 요청 요약

리뷰의 수정 기준 세 가지를 반영했다. 코드·재검사 결과·화면이 기준을 만족하는지, 그리고 아래 4절의 판단 요청 세 가지를 검토해 달라.

| 리뷰 수정 기준 | 반영 내용 |
|---|---|
| 1. 통합공고 guard를 `known` 분기 밖에서 먼저 적용 | `industry_status()`가 범위 무관 판정(`_status_ignoring_scope`)을 먼저 내고, 제목이 통합공고면 그 뒤에 guard를 적용 |
| 2. 범위 미복원 통합공고의 `not_mentioned/excluded_only`는 최소 `unknown`, 가능하면 `conditional + scope_unresolved=true` | `known·no_limit·not_mentioned·excluded_only` → `conditional`. 통합공고는 모두 `scope_unresolved=true` |
| 3. known, raw unknown+quote, 제외값만 있는 통합공고 회귀 테스트 | 테스트 4개 추가, 기존 known 테스트 보강(2절) |

## 2. 바뀐 파일

| 파일 | 변경 |
|---|---|
| `experiments/sql_semantic/industry_llm_sample.py` | `UMBRELLA_WHY`(판정별 이유), `industry_status()` 재구성, `_status_ignoring_scope()`(기존 로직 분리, 동작 동일) |
| `experiments/sql_semantic/industry_results.py` | 행에 `scope_unresolved` 전달, `DEFAULT_ORDER` 맨 앞에 final5 |
| `web/industry_results.html` | 판정 칸에 `세부사업 범위 미확인` 경고 |
| `tests/test_industry_llm_sample.py` | `test_umbrella_raw_unknown_with_quote_is_not_not_mentioned`, `test_umbrella_with_excluded_only_is_not_excluded_only`, `test_umbrella_no_limit_is_conditional`, `test_umbrella_unknown_keeps_its_reason` 추가, `test_umbrella_notice_is_conditional`에 `scope_unresolved` 확인 추가 |
| `tests/test_industry_results_ui.py` | `test_scope_unresolved_passed_to_page` 추가 |

설계 선택:

- `unknown`과 `conditional`은 바꾸지 않는다. 이미 통과 조건이 아니고, `unknown`에 붙은 이유(검사가 내림 등)가 더 구체적이다.
- 허용·제외 값은 지우지 않는다. 원문 근거는 있고, 어느 세부사업의 값인지만 모른다.
- `unknown` 대신 `conditional`을 택했다. 라벨 "조건부·세부사업별(확인 필요)"이 통합공고의 실제 뜻과 맞고, `unknown`은 "추출 실패"로 읽힌다. 두 값 모두 통과 조건이 아니다.

## 3. 결과와 Claude 측 확인

재검사(LLM 0, 저장 checkpoint, `--profile rough`, 모두 새 폴더):

```text
industry_llm_full_luna_20260922   → industry_llm_full_luna_20260928_rough_umbrella
industry_llm_long97_luna_20260922 → industry_llm_long97_luna_20260928_umbrella
industry_llm_long104_luna_20260922 → industry_llm_long104_luna_20260928_umbrella
합침 rough_umbrella + long97 → industry_llm_full_luna_20260928_umbrella_m1
합침 umbrella_m1 + long104  → industry_llm_full_luna_20260928_final5   ← 새 기준
```

Claude 측 확인(검수에서 독립 재현 부탁):

- 전체 `python -X utf8 -m unittest discover -s tests`(`data-collection/`에서) 469개 통과, 건너뜀 13.
- final4 ↔ final5: 1,852행, ID 집합 동일. `status, allowed, excluded, dropped, raw_allowed, list_complete, truncated, no_limit_text, industry_status, industry_status_why, downgraded, filter_ready` 비교 시 **바뀐 행 8건, 모두 제목이 통합공고, 바뀐 필드는 `industry_status(_why)`뿐**.
  - not_mentioned → conditional: `bizinfo:PBLN_000000000116008`, `…119737`, `…119738`, `…122433`, `…124502`, `kstartup:175783`, `kstartup:175817`
  - excluded_only → conditional: `bizinfo:PBLN_000000000116975`
- 출처 1,651/97/104, 토큰 6,394,949/1,472,128, 원답 비용 $3.0455가 final4와 같다. `called_this_run=0`, `db_writes=0`, `filter_ready=true` 0건, 상태/값 불변식 위반 0건.
- final5: 제한 있음 616 · 언급 없음 810 · 제외만 242 · 명시 4 · 조건부 24 · 확인 필요 156. 통합공고 25건 = 조건부 18 · 확인 필요 7, `scope_unresolved=true` 25건.
- `/industry-results`: final5가 기본 선택되고, "통합"으로 검색하면 통합공고 행에 경고가 뜨는 것을 DOM 텍스트로 확인했다(스크린샷은 창이 가려져 비어 있음).

## 4. Codex 판단 요청

1. **제목 정규식 범위.** `통합\s*공고`만 잡는다. `통합 모집 공고`(`bizinfo:PBLN_000000000120933`, `…124708`), `통합 상시 모집 공고`(`…124926`)는 잡지 않는다. 이들이 실제로 여러 세부사업을 묶었는지는 확인하지 않았다. 넓힐지, 넓히면 오탐(`세대통합형`, `통합관`, `통합홍보물` 등)을 어떻게 막을지 판단해 달라.
2. **챗봇 안내 오탐.** `kstartup:175817`(통합공고 요약본 챗봇 안내)은 엄밀한 통합공고가 아니지만 제목에 걸려 conditional이 됐다. 보수 쪽 오차로 두어도 되는지 판단해 달라.
3. **범위의 한계.** 세부사업별 업종을 실제로 나누는 재추출은 하지 않았다. 이번 수정은 전역 판정을 막는 데까지다. F1-1 종결 기준으로 충분한지 판단해 달라.

## 5. 검수 결과를 남길 곳

[업종 Luna 전량 리뷰](INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md) 맨 아래에 새 절로 추가하거나 새 리뷰 문서를 만들고, STATUS에 판정을 적어 달라.
승인되면 Claude는 F1-2(제외표 참조문 분리)로 넘어간다.
