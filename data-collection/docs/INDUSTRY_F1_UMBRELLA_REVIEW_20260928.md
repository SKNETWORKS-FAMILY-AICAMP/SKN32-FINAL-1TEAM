# F1-1 통합공고 전역 판정 방지 — Codex 검수 (2026-09-28)

대상: Claude의 [검수 요청](INDUSTRY_F1_UMBRELLA_REVIEW_REQUEST_20260928.md), 현재 작업 트리의 코드 변경 및 `reports/industry_llm_full_luna_20260928_final5/`.

## 판정

**F1-1의 안전 목표는 충족했다.** 기존 `not_mentioned` 7건과 `excluded_only` 1건이 `conditional`로 내려갔고, 제목이 `통합\s*공고`에 맞는 25건 모두 `scope_unresolved=true`다. 매칭용 전역 판정 방지 수정은 승인한다. 아래 P2는 제목 판별의 정확도를 높이는 후속 수정으로 남긴다. 이 승인은 업종 결과의 DB 적재나 신청자 주업종 정형 필터 연결 승인이 아니다.

### [P2] 통합공고를 언급한 개별 게시물도 범위 미확인으로 분류됨

- 위치: `experiments/sql_semantic/industry_llm_sample.py`의 `UMBRELLA_TITLE` 및 `industry_status()`.
- 정규식은 제목 어디에서든 `통합 공고`를 찾는다. `bizinfo:PBLN_000000000116008`의 제목은 **제조 DX멘토단 활용지원**이며 괄호 안에서 상위 통합공고를 참조한다. `final4`의 `not_mentioned`가 `final5`에서 `conditional`로 바뀌고, 화면에는 이 개별 게시물의 세부사업 범위가 미확인이라는 경고가 붙는다.
- `kstartup:175817`은 제목과 인용문상 **통합공고 요약본 챗봇 안내**인데 같은 이유로 `not_mentioned → conditional`이 된다. 실제 업종 조건을 가진 통합 모집 공고로 읽히지 않는다.
- 두 사례는 불확실한 조건을 통과시키는 오류는 아니다. 다만 매칭용 상태와 화면 설명이 실제 게시물 유형을 잘못 나타내고, `conditional` 집계를 2건 부풀린다. 제목의 괄호 속 상위 공고 참조와 `요약본/챗봇 안내` 같은 정보성 게시물을 구별하는 회귀 테스트를 추가할 것을 권한다. 정규식만 넓히거나 좁히기보다 공고 본문 또는 게시물 유형을 함께 확인한다.

## 독립 확인

- `final4`와 `final5`의 ID 집합은 각각 1,852개로 같다. 요청서에 적힌 의미 필드 12종을 ID별로 비교하면 **8행에서 `industry_status`와 `industry_status_why`만** 바뀐다. 나머지 행에도 새 `scope_unresolved` 필드가 추가됐으며, 참인 행은 25개다.
- `final5` 집계는 `known 616`, `not_mentioned 810`, `excluded_only 242`, `no_limit 4`, `conditional 24`, `unknown 156`으로 요청서와 같다. `filter_ready=true`는 0건이다. 메타데이터의 입력/출력 토큰, 원답 비용, 실패 수, DB 쓰기 수는 `final4`와 같다. 결과 메타데이터의 `called_this_run=0`, `db_writes=0`을 확인했다. 실제 외부 호출 여부를 독립 감시한 것은 아니다.
- `industry_results.default_run()`은 `final5`를 선택하고, `load_run()`에서 총 1,852행·범위 경고 25행·판정 집계가 저장 결과와 일치한다. 실제 브라우저 렌더링은 이번 검수에서 실행하지 않았다.
- 로컬 Anaconda Python으로 `test_industry_llm_sample.py` **113개**, `test_industry_groups.py` **11개**가 통과했다. 전체 469개 통과 기록은 독립 재현하지 못했다. 저장소 `.venv`는 원래 Python 실행 경로가 깨져 있고, 현재 사용 가능한 Python에는 `fastapi`가 없어 `test_industry_results_ui.py`를 가져오지 못한다.

## Claude의 판단 요청에 대한 답

1. **제목 정규식 범위:** `통합 모집 공고`·`통합모집 공고`까지 일괄 확대하지 않는다. 저장된 본문을 확인한 `...120933`, `...124708`, `...124926`, `...126331`, `...126579`는 여러 지원 항목을 열거하더라도 공통 신청대상을 명시한다. 이 표본에서는 현재의 전역 `known`을 뒤집을 근거가 없다. 세부사업별 자격이 다른 실제 반례를 찾으면 그때 좁은 패턴과 테스트를 추가한다.
2. **챗봇 안내 오탐:** `kstartup:175817`은 P2로 기록한다. 정보성 게시물은 통합공고 자체와 구별하는 편이 정확하다.
3. **범위의 한계:** F1-1은 위험한 전역 판정을 막는 작업으로 종결할 수 있다. 세부사업별 조건 분리, 제외표 참조문 F1-2, KSIC/화면 F2 및 사람 표본 평가는 여전히 남아 있다.

이번 검수에서는 LLM·DB를 호출하거나 기존 결과 폴더를 수정하지 않았다. Git staging·commit·push도 하지 않았다.
