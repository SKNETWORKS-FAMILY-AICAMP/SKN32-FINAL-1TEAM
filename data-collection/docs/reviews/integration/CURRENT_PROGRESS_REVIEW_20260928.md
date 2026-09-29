# 2026-09-28 진행분 통합 검수 — Codex

범위: `data-collection/`의 현재 작업본 중 업종 순위 반영·평가, 신청자 유형 LLM 추출·결과 화면, 문서 이동을 확인했다. 이 문서는 **수정 요청**이며 코드·결과 파일을 고치거나 Git에 올리지는 않았다. 정형 필터 선행 매칭의 기존 재검수 요청은 [별도 요청서](../matching/MATCH_FILTER_FIRST_REVIEW_REQUEST_20260928.md#6-재검수-요청--codex-p2-두-건-수정-2026-09-28)에 남아 있다.

## 수정 필요

### P1. 전량 추출을 `--resume`만으로 재개하면 표본 결과로 덮일 수 있음

- 위치: [`applicant_type_llm.py`](../../../experiments/sql_semantic/applicant_type_llm.py) `main()`의 `--all`·`--resume` 처리(328~360행), `write_report()`(269~276행).
- 재현 경로: 전량 실행 폴더 `reports/applicant_type_llm_full_.../`에 checkpoint가 있을 때, 모듈 머리말의 `--resume <폴더>` 예시처럼 `--all` 없이 실행한다. `take_all` 기본값이 `False`라 `items`는 60건 표본이 된다. 이어서 같은 전량 폴더의 checkpoint를 읽고, 최종 `results.jsonl`·`meta.json`은 그 60건으로 다시 쓴다. checkpoint 자체는 남아도 전량 결과가 표본으로 표시될 수 있다.
- 요청: 재개 폴더의 실행 모드·대상 ID 집합을 저장해 재개 시 일치 여부를 검사하고, 불일치면 결과를 쓰기 전에 중단한다. 전량 재개 명령에는 `--all`을 명시하도록 안내도 고친다. 진행 중인 전량 실행이나 checkpoint를 삭제하지 않는다.

### P2. 업종 평가의 `top=100000`이 서비스 검색 깊이까지 바꿈

- 위치: [`industry_rank_check.py`](../../../eval/industry_rank_check.py) 69~93행, [`app.py`](../../../search/app.py) 298~300행·506~530행.
- 평가 스크립트는 후보를 잘리지 않게 받으려고 `top=100000`으로 호출한다. 서비스의 깊이는 `max(req.top, _hybrid_depth())`이므로 이 호출은 깊이 50이 아니라 필터 통과 공고 전체를 검색한다. 그러나 결과 `meta.depth`와 요약에는 별도로 구한 50을 기록한다.
- 따라서 보고된 상위 10 변화(업종별 17~36/58쌍)는 실제 서비스의 `top=10`, 검색 깊이 50 조건을 측정한 수치가 아니다. 또한 “근거 없는 밀림 0건” 검사는 순위 규칙이 사용한 **같은 업종 표**와 다시 비교하므로 업종 추출·대분류 변환이 맞는지 확인하지 못한다.
- 요청: 서비스 조건의 Top 10 비교를 별도로 실행하고 실제 응답 `depth`를 기록한다. 후보 집합 불변식 검사는 별도 전체 후보 경로에서 수행한다. 업종 판정의 안전성은 공고 근거 문장에 대한 독립 판정으로 확인한다.

### P2. 넓은 `식품기업` 표현을 제조업 전용으로 단정함

- 위치: [`industry_groups.py`](../../../experiments/sql_semantic/industry_groups.py) `allowed_sections()`(317~333행), [`industry_rank.py`](../../../search/industry_rank.py) `usable_sections()`·`off_industry()`(36~42행·73~78행).
- 실제 결과 `bizinfo:PBLN_000000000125847`의 허용값은 `식품기업`이고 근거는 “2026년 식품기업 창업프로그램 지원사업 수혜기업(20개사)”이다. 여기에는 제조업 대분류 `C`만 허용한다는 근거가 없다. 현재 `allowed_sections(['식품기업'])`은 `{'C'}`를 반환하고, 다른 업종 신청자를 `off_industry=True`로 만든다.
- 저장된 평가의 `q044`에서 이 공고는 음식점업·정보통신업·농업·건설업·도소매업 5쌍에서 상위 10 밖으로 밀렸다. 다섯 쌍 모두 주제 적합 판정 2였다. 주제 적합 판정이 신청 자격의 정답은 아니지만, 순위 변화가 실제로 발생했음을 보여 준다.
- 요청: 제조업만 허용한다고 확정할 수 없는 포괄 표현은 `None`(비교 불가)로 두고, 해당 공고를 포함한 회귀 사례를 추가한다. 그 뒤 업종 순위 평가를 다시 실행한다.

### P3. 문서 이동 뒤 남은 경로

- [최신 인계서](../../NEXT_SESSION_HANDOFF_20260928.md) 111행의 새 세션 요청문은 옛 `docs/MATCH_FILTER_FIRST_REVIEW_*` 위치를 가리킨다. 실제 위치는 `docs/reviews/matching/`이다.
- `reports/search_comparison_20260918T*/summary.md`와 한 `NOTE.md`의 Markdown 링크 6개가 옛 `../../docs/SEARCH_COMPARISON_*` 위치를 가리켜 열리지 않는다. 결과 보존 원칙 때문에 원본을 그대로 둘 경우, 새 위치를 안내하는 방법이 필요하다. JSON manifest의 과거 경로·해시는 당시 실행 기록이므로 이 문제와 구분한다.

## 독립 확인과 한계

- 문서 이동: 기존 위치에서 사라진 추적 파일 70개 모두 새 `docs/` 하위에서 같은 이름을 확인했다. 새 문서와 관련 Markdown 상대 링크 272개는 유효했다. 위 `reports/` 링크는 그 검사 범위 밖이며 따로 확인했다.
- `python -m unittest discover -s tests -p test_industry_groups.py -q`: 17개 통과.
- `python -m unittest discover -s tests -p test_applicant_type_llm.py -q`: 5개 통과.
- 실제 final5 파일을 읽어 업종 순위 대상 273건과 위 `식품기업` 공고의 `{'C'}`·`off_industry=True`를 재현했다. 저장된 평가 결과에서 해당 공고의 5쌍 순위 변경도 확인했다.
- 통합 테스트는 이 환경의 `.venv`가 없는 Python 3.12 실행 파일을 가리켜 시작되지 않았고, 시스템 Python에는 `fastapi`가 없어 실행하지 못했다. Claude가 기록한 전체 506개 통과를 이번 검수에서 독립 재현한 것으로 보지 않는다.
- DB·Chroma·유료 API를 새로 호출하지 않았다. 전량 추출 실행 중인 폴더와 checkpoint는 읽기만 했다.
