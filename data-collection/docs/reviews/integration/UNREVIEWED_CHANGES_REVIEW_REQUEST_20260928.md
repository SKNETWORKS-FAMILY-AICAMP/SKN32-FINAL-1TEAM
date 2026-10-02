# Codex 검수 요청 — 2026-09-28 오후 미검수 변경 (커밋 전)

작성: Claude · 요청: 사용자(이근준) · 수행: Codex
Codex가 이미 본 것(정형 필터 선행 매칭 A, 통합 검수·재검수, 신청자 유형·업종 블라인드 판정)은 빼고, **그 뒤에 들어간 변경**만 정리했다.
커밋 전 검수다. 결과는 이 폴더에 `UNREVIEWED_CHANGES_REVIEW_20260928.md`로 남겨 달라.

## 1. 우선순위 높음 — 서비스 결과가 바뀌거나 비용이 드는 것

### 1-1. 매칭 D·E·H (`search/app.py` `match()`, `MatchRequest`)

- **D 후보 수**: `top` 기본 3 → 10, `offset` 추가, 누적 최대 `MAX_CANDIDATES=20`(offset을 쓸 때만 자름), 결과에 `rank`·`display_type`(1~3 card)·`has_more`.
- **E 대체 검색**: 질의 인코딩·Chroma·BM25를 각각 try로 잡는다. 임베딩 쪽 실패 → `BM25단독`, BM25 실패 → `임베딩단독`, 둘 다 → 필터 통과 공고 `마감임박순`(잠정). `fallback_used`·`fallback_mode`·`search_errors`, stderr 기록. 정형 필터는 모든 경로에서 유지. 유사도가 없으면 `score`·`band`가 None.
- **H 적합도**: `fit_score` = 이번 경로의 RRF ÷ 이론 최대값(하이브리드는 (w_dense+w_bm25)/(k+1)), 마감임박순은 None, `fit_basis`.
- 보고 싶은 것:
  - offset·top 경계(0, 10, 20, 음수, 큰 top)
  - 대체 경로에서 `ordered`·`ranks`·`candidates`의 dist None 처리와 규칙 정렬(score 방식 `base`) 누락
  - `has_more` 계산
  - 기본값 변경(3→10)이 다른 호출부(`web/app.html`, `eval/*`, `experiments/sql_semantic/industry_probe.py`, `compare_input.py`)에 주는 영향
- 테스트 `tests/test_match_deh.py`(9). `tests/test_query_ablation.py`의 기본값 기대값을 10으로 고쳤다(query_ablation은 top을 직접 넘김).

### 1-2. 신청자 유형 게이트 (`search/applicant_types.py` 신규, `search/app.py` `match()`·`eligibility()`)

- 사용자 결정: 판정 결과([결과 문서](../applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md))에서 믿을 만했던 것만 연결한다. **신청자가 예비창업자일 때만** 쓴다.
  - 본문 '예비창업자 불가' + strong + varies 아님 → 정형 필터에서 뺀다(이유 "예비창업자 불가(공고 본문)").
  - 본문 '가능' → `gate.prefilter`의 '업력·신청자 유형' 사유(K-Startup API 업력 칸)를 지워 되살린다.
  - '불가 추정' → 빼지 않고 뒤로. 정렬 키는 시·도 → 시·군·구 → **추정** → 업종 → 집단.
  - weak 불가와 개인/법인은 매칭에 쓰지 않는다.
- **등록 사업자 규칙**(`registered_only()`, [원문 대조](../applicant_type/APPLICANT_TYPE_AMBIGUOUS_CHECK_20260928.md)): LLM이 예비를 언급 없음·weak 불가로 둔 공고라도, 근거 문장에 등록 사업자 전용 표현이 있으면 불가 추정으로 올린다. "예비·없이·무관·예정"이 있으면 올리지 않는다. 2,476건 중 67건.
- `eligibility()`: '지원대상 유형'을 이 값으로 판정한다(예비: 불가=미달·가능=통과·추정/모름=확인 필요). 본문 가능이면 업력 미달을 통과로 바꾸고 요구 칸에 API 원문을 병기한다. 개인/법인은 근거만 표시한다.
- 보고 싶은 것:
  - 되살림이 '업력·신청자 유형' 외 사유(마감·모집 종료)까지 덮지 않는지
  - blocked가 이미 API로 빠진 공고와 중복 집계되지 않는지
  - 정규식이 잘못 올리는 문장 유형(과잉 매칭). 예: "사업자등록일로부터", "영업 중인" 같은 표현이 신청 자격이 아닌 문맥에서 쓰인 경우
  - 결과 파일에 없는 공고는 예전과 같은지
- 실제 서비스 확인(예비창업자·경기·친환경 생활용품): blocked 177, restored 9, 상위 10 중 2건 변경(둘 다 불가 추정). 테스트 `tests/test_applicant_types.py`(12).

### 1-3. 매일 배치 11단계 — 신청자 유형 추출 (`collect/applicant_type_daily.py` 신규, `collect/daily_pipeline.py`)

- **유료 API를 매일 자동으로 부른다.** 발췌 해시가 누적 결과와 다른 공고만 부르고, 하루 상한 300건(약 $0.25)이다. 누적은 `data/applicant_types/results.jsonl`, 성공 호출은 `checkpoint.jsonl`에 바로 적고 다음 실행이 반영한다. 실패가 없으면 체크포인트를 지운다.
  처음에는 전량 결과(`reports/applicant_type_llm_full_20260928T023916Z/`)로 시작한다.
- 서비스(`applicant_types.default_path`)는 환경 변수 → 누적 파일 → 전량 결과 순서로 읽는다.
- 보고 싶은 것:
  - 상한·재시도 없이 실패 공고가 매일 다시 불려 비용이 새지 않는지
  - 체크포인트 재반영의 해시·프롬프트 조건
  - `write_atomic`과 체크포인트 삭제 순서(중간 종료 시 결과 유실 여부)
  - 배치 잠금 안에서 스레드 4개 사용
  - 공고가 DB에서 사라졌을 때 누적 파일에 남는 것
  - `data/applicant_types/`가 Git 추적 대상으로 보인다(`.gitignore` 확인 필요, 결과 파일 약 4.7MB)
- 실제 단독 실행: 대상 2,476 · 호출 0 · $0. 테스트 `tests/test_applicant_type_daily.py`(5).

### 1-4. 업종 순위 기본 꺼짐 (`MatchRequest.demote_industry` True → False)

- 판정에서 부당 밀림이 11/34였기 때문이다. 코드·평가는 유지하고, 테스트는 규칙 시험 때 명시적으로 켠다. 기본 꺼짐 테스트를 1개 추가했다. 보고 싶은 것은 꺼진 상태에서 응답 `industry`·`industry_demoted`가 오해를 부르지 않는지다.

## 2. 우선순위 보통

| 변경 | 파일 | 보고 싶은 것 |
|---|---|---|
| 업종 순위: 허용 갈래 검사·KSIC 26 (재검수 응답 2) | `search/industry_rank.py` `branch_problem`, `industry_groups.py` | 이미 응답했다. 재검수 대기 중이면 함께 |
| 기획서 대조 B — 실험 경로가 지역·업종·규모를 빼지 않고 뒤로 | `experiments/sql_semantic/search.py`(`build_filter`·`evaluate`·`rank`), `fixtures.py`(0건 사례를 마감으로), `viewer.py` `drop_split`, `web/verify.html` | 옛 설계를 고정하던 테스트 7개를 고친 것이 타당한지(`tests/test_sql_semantic.py`), `evaluate` 반환값 변경(3→4)의 다른 호출부 |
| 수집 상태 판정(F, 매칭 미연결) | `search/collection_status.py`, `/api/collection-status`·`/collection-status` | `judge` 규칙(부분 실패 = 실패, 로그 시간대 KST 가정, 오래된 로그 무시 기준 10분), 기업마당 스냅샷 파일명 해석 |
| 판정 꾸러미·채점 | `experiments/sql_semantic/label_pack.py`, `label_score.py` | 이미 사용함. 채점 지표 정의만 |
| 신청자 유형 결과 화면 | `experiments/sql_semantic/applicant_type_results.py`, `web/applicant_types.html`, `/api/applicant-types*` | 읽기 전용·폴더 이름 검사 |
| 시험 화면(8000) | `web/app.html` | top 10, 카드 3 + 리스트 7, "10건 더 보기"(offset), 대체 검색 배너, 적합도 표시 |

## 3. 검증 방법

- 프로젝트 `.venv`: `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` → Claude 기록 **561개 통과(건너뜀 13)**.
  Codex 환경은 `.venv` 경로가 다르고 시스템 Python에 FastAPI가 없어, 이전처럼 대역을 쓰거나 해당 테스트만 골라 달라.
  `label_score.py`는 표준 라이브러리만 쓴다.
- 이번 요청 범위에서 **실제 DB·Chroma·유료 API를 새로 부를 필요는 없다.** 실제 서비스 확인 수치는 WORKLOG 2026-09-28 항목에 있다.
- 코드·DB는 고치지 말고 결과 문서만 남겨 달라. Git 스테이징·커밋·push는 하지 않는다(사용자가 한다).

## 4. 참고 문서

- 변경 이유와 실제 확인: [WORKLOG](../../WORKLOG.md) 2026-09-28 위쪽 항목들.
- 흐름: [FLOW](../../FLOW.md), 전체 흐름 화면 `http://127.0.0.1:8010/flow`.
- 방향: [기획서 대조](../../PLAN_ALIGNMENT_20260928.md) 3절 표(A·B·D·E·H 해결, F 판정만, G 예비창업자 연결).
