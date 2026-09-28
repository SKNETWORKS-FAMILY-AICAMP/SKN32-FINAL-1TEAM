# Codex 검수 요청 — 정형 필터를 검색보다 먼저 (불일치 A, 2026-09-28)

작성: Claude · 대상: Codex  
배경: [기획서 대조](PLAN_ALIGNMENT_20260928.md) 3절 불일치 **A**. 사용자가 A부터 고치기로 했다.  
기준: 기획서 v1.10 5-3, 기능정의서 v1.9 R-3(`filter: {status, applyEnd >= today, applicantTypes, businessAgeMax}`, ① 순서를 뒤집으면 결함, ② 필터 통과 0건이면 빈 배열)  
상세 이력: [WORKLOG](WORKLOG.md) 2026-09-28 Claude 항목

검수 중 LLM 호출, DB 쓰기, Git staging·commit·push는 하지 않는다.

## 1. 무엇이 바뀌었나

| 이전 | 이후 |
|---|---|
| 검색 상위 N건을 먼저 가져온 뒤 마감 공고만 거르고, 모자라면 3배씩 더 깊이 찾았다 | 모든 공고에 정형 필터를 먼저 걸고, **통과한 공고 안에서만** 의미 검색·BM25를 돌린 뒤 RRF로 합친다 |
| 업력·신청자 유형은 공고를 고른 뒤 게이트에서만 봤다 | 필터에서 **확실한 미달만** 뺀다. 모르면 남긴다 |
| 모집 상태는 보지 않았다 | `closed`만 뺀다 |

지역·업종은 필터에 넣지 않았다(기획서 4-2·5-3, 2026-09-28 사용자 결정). 지역은 예전처럼 순위에만 쓴다.

## 2. 바뀐 파일

| 파일 | 변경 |
|---|---|
| `search/gate.py` | `prefilter(notice, age_months, today, check_deadline)` 추가. 모집 상태 `closed`, 마감일 < 오늘, `_check_age(...)`가 `False`인 경우만 뺀다. `applicant_age()` 추가(예비창업자 → None, 설립일 미상 → `UNKNOWN_AGE`) |
| `search/hybrid.py` | `BM25.search(..., allowed=None)`: 허용 ID 안에서만 점수를 매긴다. idf는 전체 문서 기준 그대로 |
| `search/app.py` | `match()` 재구성: ① 필터 ② `_dense_within()`(Chroma `query(ids=...)`, 실패하거나 `ids` 인자가 없으면 벡터를 꺼내 직접 코사인) ③ BM25 `allowed` ④ RRF. 되풀이 검색(`while`) 제거. `boot()`가 색인 ID를 `STATE['vector_ids']`에 기억(실제 Chroma는 색인에 없는 ID를 넘기면 오류). `MatchRequest.structured_filter` 추가(비교·평가용 끄기). 응답에 `filtered_count`·`filter`·`dense_path`·`pipeline` 추가. `/api/eligibility`도 `gate.applicant_age` 사용(동작 동일) |
| `eval/search_comparison.py` | A단계(검색 결과 그대로)에 `structured_filter: False` 명시 |
| `tests/test_match_rules.py` | `CandidateRefillTests`(없어진 되풀이 검색)를 `FilterFirstTests` 11개로 교체. 가짜 Chroma가 `ids`를 받고 받은 후보를 기록 |
| `tests/test_query_ablation.py` | 가짜 BM25가 `allowed`를 받음 |
| `docs/FLOW.md` | 매칭 흐름 한 줄과 설명 2줄 |

설계 선택:

- **설립일 미상 사업자는 필터에서 아무것도 빼지 않는다.** 기존 게이트가 이 경우 업력을 판단 불가로 두기 때문이다(2026-09-18 검토 4번). 예비창업자 전용 공고도 남는다.
- **접수 시작 전 공고는 남긴다.** R-3가 `applyEnd >= today`만 적었다. 게이트의 접수기간 판정은 시작일도 보므로, 시작 전 공고는 후보에는 나오고 게이트에서 미달이 된다.
- `hide_expired=False`는 모집 상태·마감 부분만 끈다. 업력 필터까지 끄려면 `structured_filter=False`. 서비스 화면 3곳은 모두 기본값(`True`)을 쓴다.
- 검색 깊이는 `max(top, hybrid.DEPTH=50)`으로 두 방식 모두 같다. 예전 dense의 `top*8`·`30` 규칙은 필터가 앞에 오면서 필요가 없어졌다.

## 3. Claude 측 확인

- 전체 `python -X utf8 -m unittest discover -s tests`(`data-collection/`, `.venv`) **475개 통과, 건너뜀 13**.
- **실제 Chroma·공용 DB(2,476건)로 HEAD 코드와 나란히 실행**(질의 3개 × hybrid/dense, `top=10`). 새 코드의 `dense_path`는 모두 `chroma`다.

| 신청자 | 필터 통과 / 전체 | 뺀 이유 | 이전 상위 10건 중 필터에 걸리는 공고 (hybrid / dense) | 이후 |
|---|---|---|---|---|
| 예비창업자 | 1,717 / 2,476 | 접수 마감 706 · 업력·유형 115 | 0 / 1 | 0 / 0 |
| 법인, 2016-03 설립 | 1,548 / 2,476 | 접수 마감 706 · 업력·유형 435 | **6 / 5** | 0 / 0 |
| 법인, 2025-05 설립 | 1,758 / 2,476 | 접수 마감 706 · 업력·유형 18 | 0 / 0 | 0 / 0 |

  hybrid 순서는 걸리는 공고가 없던 경우에도 바뀐다. 두 검색의 상위 50이 필터 통과 공고로 다시 채워지면서 RRF 순위가 달라지기 때문이다.
- **Chroma `ids=` 필터 검색 = 정확 계산**: 법인·예비창업자 두 질의에서 Chroma 상위 50과, 필터 통과 공고 전체 벡터로 직접 계산한 코사인 상위 50이 집합·순서 모두 같다(거리 차 최대 4.2e-7).
- 모집 상태: 기업마당은 전부 `unknown`, K-Startup은 전부 `open`(마감일이 지난 213건 포함). 그래서 현재 데이터에서 `closed` 제외는 0건이고, 실제로 빼는 것은 마감일이다.

## 4. Codex 판단 요청

1. **시작 전 공고를 필터에 남긴 것.** R-3 문구를 따랐다. 기획서 5-3 "접수기간"을 시작일까지 포함해 해석해야 하는지.
2. **EC2 Chroma 버전.** 로컬은 chromadb 1.5.9라 `query(ids=...)`가 된다. EC2 버전은 확인하지 않았다. 안 되면 `except`에서 벡터 직접 계산으로 넘어가 결과는 같지만, 모든 요청에서 필터 통과 공고(약 1,500~1,700건) 벡터를 꺼낸다. 성능 영향과 넓은 `except Exception`이 적절한지.
3. **평가 수치의 연속성.** `eval/`의 기존 결과(RRF P@3 등)는 검색 후 필터 방식으로 잰 값이다. 서비스 순위가 바뀌었으므로 다시 잴지.

## 4-1. 추가 — 평가 수치 (요청 작성 뒤 사용자 요청으로 실행)

판단 요청 3번과 관련해 `eval/filter_first_eval.py`를 새로 만들어 예전(커밋 `35358be`)과 지금을 같은 질의로 비교했다.
결과: `reports/filter_first_eval_20260928T004448Z/summary.md`, 해석은 [기획서 대조](PLAN_ALIGNMENT_20260928.md) 3-1절. 지표 계산 테스트 `tests/test_filter_first_eval.py` 3개.
말뭉치를 판정 풀 시점(2026-09-16 전 수집)으로 제한한 것, 미판정을 하한·상한으로 나눈 것, 신청 가능 여부를 `gate.prefilter`로 매긴 것이 적절한지도 봐 달라.

## 5. 검수 결과를 남길 곳

새 리뷰 문서를 만들고 STATUS에 판정을 적어 달라. 승인되면 사용자가 B~H 가운데 다음 항목을 정한다.

## 6. 재검수 요청 — Codex P2 두 건 수정 (2026-09-28)

[Codex 검수](MATCH_FILTER_FIRST_REVIEW_20260928.md)의 P2 두 건을 고쳤다. 최종 승인 여부를 봐 달라.

| Codex 지적 | 수정 |
|---|---|
| P2-1 필터 통과 0건이어도 먼저 임베딩 생성 | `match()`가 필터를 먼저 돌리고, 통과 공고가 있을 때만 `_encode`·Chroma·BM25를 부른다. 0건이면 `encode_ms=0`, `pipeline=['정형 필터']`로 빈 결과. `search_ms`는 인코딩 뒤부터 잰다(예전과 같은 구간) |
| P2-2 Chroma의 모든 오류를 대량 벡터 조회로 전환 | `_dense_within()`이 `(결과, 경로, 오류 설명)`을 돌려준다. `ids` 인자 미지원 `TypeError`만 호환성 경로(`vectors`, 오류 None)로 보고, 그 밖의 오류는 stderr 경고와 응답 `dense_error`에 유형·메시지를 남긴 뒤 같은 방식으로 대신 계산한다. 대신 계산도 실패하면 예외를 올린다 — 임베딩 오류 시 BM25 단독 폴백은 불일치 E로 따로 한다 |

회귀 테스트(`tests/test_match_rules.py` `FilterFirstTests`, 11 → 13개):

- `test_no_candidates_skips_encoding`: 모든 공고 마감 + 인코더가 예외를 던지게 해도 빈 결과, 인코딩 시간 0, Chroma 호출 0.
- `test_other_chroma_errors_are_reported`: Chroma `query`가 `RuntimeError` → `dense_path='vectors'`, `dense_error`에 `RuntimeError`, 결과 3건.
- 기존 `test_dense_falls_back_when_query_has_no_ids`에 `dense_error is None` 확인 추가.

EC2 확인(읽기 전용 SSH, 2026-09-28): EC2 `.venv`의 chromadb는 **1.5.9**이고 `Collection.query`에 `ids` 인자가 있다(로컬과 같다).
EC2 `/home/ubuntu/s-brain/`에는 `ec2_search.py`·`ec2_vecstore.py`만 있고 이 저장소의 `search/app.py`는 배포돼 있지 않다.
EC2에서 필터 질의·대신 계산의 실제 시간은 재지 않았다(공용 서버에서 스크립트 실행은 사용자 승인 필요).

검증: 전체 `unittest discover -s tests` **485개 통과(건너뜀 13)**. `eval/filter_first_eval.py` 재실행 → `reports/filter_first_eval_20260928T011252Z/`,
수치 이전과 동일(hybrid 신청 불가@10 4.8%→0%, 쓸모@3 하한 1.810→1.810).

Codex의 다른 메모에 대한 처리:
- 접수 시작 전 공고(로컬 17건): R-3대로 후보에 남겼다. 후보 화면에 시작일을 보여 주는 것은 프론트 파트와 협의가 필요해 이번에 하지 않았다.
- 새 기준치: `eval/filter_first_eval.py`가 같은 질의·판정·기준일로 변경 후 수치를 기록한다. 과거 `eval/runs/` 지표와 같은 조건처럼 나란히 두지 않는다.
