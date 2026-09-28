# SQL 의미 검색 검증 UI 리뷰

2026-09-21 · Codex · 구현 변경 없이 코드·테스트·브라우저 화면 검토

대상:

- `experiments/sql_semantic/viewer.py`
- `experiments/sql_semantic/fixtures.py`
- `web/verify.html`
- `tests/test_verify_ui.py`
- `docs/VERIFY_UI.md`
- `reports/verify_ui/test_result.json`

기준: [Claude UI 작업 지시서](CLAUDE_UI_VERIFICATION_TASK_20260921.md).

## 판단

읽기 전용 검증 UI의 기본 목적은 달성됐다. 실제 브라우저에서 저장된 SQL 의미 검색 실행과
fixture를 구분해 볼 수 있고, F1~F3·Chroma 미검증·사람 판정 없음도 숨기지 않고 표시한다.
공고 ID·원문 링크·필터 켬/끔 결과·순위 이동·조건별 상태·벡터 상태도 확인할 수 있다.

다만 아래 두 건을 보완하기 전에는 저장된 `210개 통과` 기록과 지시서의 SQL/Python 단계별 제외
표시가 완료됐다고 보기 어렵다.

## 수정 필요

### 1. [P1] 전체 테스트에서는 fixture 결정성 테스트가 실패함

- 위치: `tests/test_verify_ui.py:36-42`, `experiments/sql_semantic/search.py`의 `timing_ms` 반환.
- UI 전용 테스트 25개를 단독 실행하면 통과하지만, 전체 테스트 210개를 실행하면
  `FixtureTests.test_same_every_time`가 실패했다.
- 테스트는 두 번 생성한 `responses` 전체를 JSON 문자열로 비교한다. 응답에는 실제 실행 시간인
  `timing_ms.sql/encode/compare/total`이 포함되므로 동일한 fixture라도 실행마다 값이 달라질 수 있다.
- 별도 재현에서도 검색 결과·순위·조건·벡터 상태는 같았고 차이는 `timing_ms`뿐이었다.
  예를 들어 한 실행의 `compare/total`이 `0.0/0.0`, 다음 실행이 `1.0/1.0`으로 달랐다.
- 따라서 fixture 화면의 핵심 결과가 비결정적인 것이 아니라, 비결정적인 실행 시간을 결정성 비교에
  포함한 테스트 문제다. 실행 환경과 타이밍에 따라 통과하거나 실패하는 flaky 테스트가 된다.
- `reports/verify_ui/test_result.json`의 `210개 통과`는 이번 Codex 재실행 결과와 일치하지 않는다.
  수정 후 전체 테스트를 다시 실행해 파일을 갱신해야 한다.

수정 기준:

1. 결정성 검증에서 `timing_ms`를 제외하고 사례·모드·후보 수·탈락 사유·벡터 상태·결과 ID·순위·점수를 비교하거나,
   fixture 경로에 한해서 시간을 고정 주입한다.
2. 단순히 실패한 테스트를 삭제하거나 fixture 결과 검증을 약화시키지 않는다.
3. 전체 테스트를 반복 실행해 같은 결과가 나오는지 확인한다.
4. `test_result.json`에는 실제 마지막 전체 실행 결과만 기록한다.

재현 명령:

```powershell
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_*.py"
```

Codex 검증 환경에서는 프로젝트 가상환경의 패키지를 번들 Python에 연결해 같은 테스트를 실행했다.
결과는 `Ran 210 tests`, `FAILED (failures=1, skipped=13)`이었다.

### 2. [P2] SQL 단계 제외 건수를 UI가 명시적으로 계산해 보여주지 않음

- 위치: `experiments/sql_semantic/viewer.py:219-238`, `web/verify.html`의 필터 켬/끔 집계 표시.
- `drop_split()`의 설명은 SQL 단계와 Python 조건 단계를 나눈다고 되어 있지만 반환값에는
  `rows_from_sql`, `dropped_by_conditions`, `after_conditions`만 있고 `sql_dropped`가 없다.
- 화면에서 필터 켬과 필터 끔의 `rows_from_sql`을 각각 확인하면 사람이 차이를 계산할 수는 있다.
  예를 들어 case01은 필터 끔 1,852줄과 필터 켬 819줄이므로 SQL 단계 제외는 1,033줄이다.
  하지만 화면은 `SQL 단계 제외 1,033`을 직접 표시하지 않는다.
- 작업 지시서는 “SQL 단계에서 제외된 수와 Python 조건에서 제외된 수를 분리”해 보여주도록 요구했다.
  현재 화면의 `SQL이 돌려준 줄 → 조건 통과`만으로는 이 요구를 충분히 충족하지 않는다.

수정 기준:

1. 같은 사례의 필터 끔 `rows_from_sql`을 기준 후보 수로 두고
   `sql_dropped = filter_off.rows_from_sql - filter_on.rows_from_sql`을 명시적으로 계산한다.
2. 화면에 최소한 `전체 후보 → SQL 제외 → SQL 통과 → Python 조건 제외 → 유효 벡터 비교 → 반환`을 표시한다.
3. 각 수치가 사례별 행 수 합계인지 고유 공고 수인지 설명을 유지한다.
4. SQL 조건별 제외 사유가 저장되지 않아 전체 세부 집계를 만들 수 없다면, 총건수와 예시 기반 사유를 구분한다.
5. 필터 끔 응답이 없거나 기준 후보 수가 더 작은 비정상 입력에서도 음수나 오해를 유발하는 숫자를 표시하지 않는다.
6. 계산과 빈 값 처리에 대한 회귀 테스트를 추가한다.

## 확인한 정상 동작

- 브라우저에서 `http://127.0.0.1:8010/`을 열어 실제 화면을 확인했다.
- 저장 실행 `sql_semantic_20260918T083852Z`가 기본 선택되고 fixture와 명확히 구분된다.
- F1·F2·F3는 `미해결`, Chroma는 `미검증`, 사람 판정은 `없음`으로 표시된다.
- 공고 1,852건·벡터 1,852건, 모델·리비전·차원·계약, 조건 확보율과 결과 파일 해시가 표시된다.
- F1 반례 두 건은 `문제 재현됨`, 지원 분야/업종 구분과 업력 미확인 반례는 `기대대로`로 표시된다.
- 필터 켬/끔의 공고 ID·제목·원문 링크·순위·순위 이동·코사인 유사도·조건 상태를 확인했다.
- 벡터 입력 해시·계약/모델·차원/dtype 검사와 F2 미해결 표시가 분리돼 있다.
- `/api/health`, `/api/runs`, fixture 실행, fixture 사례 상세, 조건 반례, 근거 조회 라우트가 HTTP 200을 반환했다.
- UI 전용 테스트 25개는 단독 실행에서 통과했다.
- fixture와 실제 저장 결과를 혼동시키는 표시, 코사인을 정확도·확률로 바꾸는 표시, 비밀정보 노출은 발견하지 못했다.

## 검증 범위와 한계

- 실제 SQL 의미 검색을 다시 실행하거나 DB·벡터·임베딩 모델을 변경하지 않았다.
- 저장된 `083852Z` 결과의 수치와 현재 UI 표시를 확인했지만 라이브 DB에서 다시 측정하지 않았다.
- 외부 원문 링크의 내용과 사람 관련성 판정은 검증하지 않았다.
- Chroma 실제 벡터 내용은 이번 UI와 리뷰 범위 밖이며 계속 미검증이다.
- 이번 리뷰에서는 구현·테스트·보고서·STATUS·WORKLOG를 수정하지 않았다. 이 리뷰 문서만 추가했다.
- Git 스테이징·커밋·push는 하지 않았다.

## Claude에게 전달할 후속 작업

1. 결정성 테스트에서 `timing_ms`를 분리하거나 고정해 전체 테스트의 flaky 실패를 제거한다.
2. 전체 테스트를 다시 실행하고 실제 결과로 `reports/verify_ui/test_result.json`을 갱신한다.
3. SQL 단계 제외와 Python 조건 제외를 화면에서 숫자로 명확히 분리하고 회귀 테스트를 추가한다.
4. 수정 후 변경 파일·검증 결과를 STATUS·WORKLOG에 남겨 Codex 재검토로 인계한다.
5. F1~F3를 UI 수정과 함께 해결했다고 처리하지 않는다. 별도 코드 수정과 회귀 검증이 있을 때만 상태를 바꾼다.

