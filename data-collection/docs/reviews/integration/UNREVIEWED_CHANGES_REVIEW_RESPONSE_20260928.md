# 2026-09-28 오후 변경 통합 검수 — Claude 응답

대상: [Codex 검수 결과](UNREVIEWED_CHANGES_REVIEW_20260928.md). 지적 8건 모두 코드에서 사실로 확인했고 모두 고쳤다.
DB 쓰기·유료 API 호출·Git 스테이징/커밋은 하지 않았다.

## 지적별 조치

| 지적 | 조치 | 파일 | 테스트 |
|---|---|---|---|
| P1 서버 시작 중 임베딩·Chroma 장애 | `boot()`에서 벡터 DB 연결·ID 목록·임베딩 모델 올리기·워밍업을 각각 잡는다. 실패하면 `STATE['boot_errors']`에 남기고 서버는 연다. 벡터 DB가 없으면 `match()`가 의미 검색을 건너뛰고 `BM25단독`으로 간다(`search_errors.embedding`에 시작 때 원인). 공고 정보(DB)·BM25 실패는 정형 필터·대체 검색의 바탕이라 그대로 멈춘다. `/api/health`에 `boot_errors`, `indexed`는 모르면 None | `search/app.py` `boot`·`match`·`health` | `test_match_deh` `BootTests` 2개, `test_vector_db_closed_at_boot_goes_to_bm25` |
| P1 하이브리드 보조 벡터 조회 실패 → 500 | `_fill_distances()`를 잡는다. 실패하면 `search_errors.embedding`(where '벡터 추가 조회')에 남기고 RRF 순서는 그대로 쓰며, BM25에서만 찾은 공고는 유사도 없이(score·band None) 보여 준다. 순위는 하이브리드 그대로라 `fallback_mode`는 None | `search/app.py` | `test_extra_vector_lookup_failure_keeps_hybrid_order_without_500` |
| P2 하루 300건이 실행당 300건 | 상한을 **날짜(한국 시간)당**으로 바꿨다. 부르기 **전에** 이번 호출 수를 `data/applicant_types/daily_state.json`의 `attempted`에 더한다(성공·실패·중간 종료 모두 센다). 재시도 정책: 같은 발췌 해시로 `MAX_FAILURES=3`번 실패하면 더 부르지 않고, 공고문이 바뀌면 다시 부른다. 결과에 `attempted_today`·`daily_limit`·`gave_up` | `collect/applicant_type_daily.py` | 같은 날 2회 실행 합 2건, 실패 호출도 상한에 포함, 3번 실패 뒤 멈춤·문서 변경 시 재호출 |
| P2 11단계 실패가 정상 종료로 기록 | 로그에 `stage_warnings`([{stage, error 또는 failed}])를 남긴다(10단계 자격요건도 같이). **status는 바꾸지 않는다** — Codex가 짚은 대로 'partial'이면 수집 상태 판정이 매칭을 막는데, 공고 데이터는 새것이고 LLM 후처리만 늦은 것이라 막을 일이 아니라고 판단했다. 대신 CLI 종료 코드 **4**(run_daily.bat이 `data/run.log`에 exit=4)와 수집 상태 화면의 "후처리(LLM) 경고" 줄로 드러낸다. 매칭 차단 여부는 운영 결정으로 남긴다 | `collect/daily_pipeline.py`, `run_daily.bat`(주석), `search/collection_status.py`, `web/collection_status.html` | `PipelineStatusTests` |
| P2 등록 사업자 규칙 문맥 | ① 제출 서류 문장("제출서류·구비서류·확인 서류·서류:·사본·첨부")은 올리지 않는다. 단 "신청 자격·지원 대상·자격"이 같이 있으면 자격 문장으로 본다. "증명원"은 넣지 않았다("사업자등록증명원 상의 소재지"는 자격 문장이다). ② "예비창업자 제외/불가/신청 불가"는 지운 뒤 "예비"를 찾는다. ③ 67건 근거를 한 줄씩 읽었다(아래). 1건이 "공고 마감일 내 사업자등록 완료"로 예비창업자도 신청할 수 있어, "마감일 내·협약 전·선정 후" 예외를 추가했다 → **66건** | `search/applicant_types.py` | Codex 두 예문 포함 4개 추가 |
| P2 공개 API `top` 상한 | 공개 경로 `/api/match`(와 `/api/match_compare`·`/api/match_rerank`)는 `_public()`으로 `top ≤ 20 − offset`을 적용한다. 평가 도구는 HTTP가 아니라 `app.match()`를 직접 부르므로 지금처럼 후보 전체를 받는다(저장소 안 평가 도구 모두 직접 호출 확인) | `search/app.py` | `test_public_route_never_returns_more_than_twenty` |
| P3 결과 파일 Git 무시 | `.gitignore`에 `data/applicant_types/` 추가. `git check-ignore`로 확인. 파일은 지우거나 옮기지 않았다 | `.gitignore` | — |
| P3 "적합도 N%" | 화면 표기를 **"순위 점수 0.86"**(소수 둘째 자리)으로 바꾸고, 마우스를 올리면 "검색 순위로 만든 상대 점수(0~1). 두 검색에서 모두 1위면 1.00 — 확률이나 합격 가능성이 아닙니다"를 보여 준다. API 필드 `fit_score`·`fit_basis`는 기능정의서 이름이라 그대로 둔다 | `web/app.html` | 화면 확인 |

## 등록 사업자 규칙 67건 검토 (Claude, AI 참고)

저장된 근거 문장 67개를 읽었다. LLM 근거는 원문에 있는지 코드로 이미 확인된 문장이다.

- 66건은 등록 사업자 요건이 맞다. 유형별로 보면:
  - "사업자 미등록 업체" 제외 조항 22건
  - "사업자등록(증명원)상 소재지/사업장" 9건
  - "여행업·공장·건설업 등록을 필한/해야" 11건
  - "사업자등록을 하지 않거나 휴·폐업" 제외 7건
  - "…영업 중인/영업활동을 하고 있는/개업일로부터" 7건
  - "사업자등록 완료/보유/되어 있는", 신고서 제출 완료 10건
- 1건(`...125901` "공고 마감일 내 사업자등록 완료한 콘텐츠 관련 기업")은 신청 뒤 등록해도 되므로 예외로 뺐다.
- 제출 서류 문장이 걸린 사례는 67건에 없었다. ①의 보완은 앞으로 들어올 공고에 대한 방어다.

## 검증

- 프로젝트 `.venv`로 전체 테스트: **571개 통과(건너뜀 13)**. 이전 561에서 이번 수정 테스트 10개가 늘었다.
  Codex 환경에서 `.venv`가 깨져 보인 것은 그 환경의 경로 문제로 보인다. 이 PC에서는 정상 실행된다.
- 실제 서비스(8000, 재시작 후):
  - `/api/health`의 `boot_errors`는 `{}`다.
  - 예비창업자·경기·친환경 생활용품으로 확인했다.
    - `top=100` → 20건, `has_more` False.
    - `top=100, offset=10` → 10건.
    - 기본 → 10건, `has_more` True.
  - `blocked 177 · restored 9`는 이전과 같다.
  - 불가 추정으로 밀린 공고(`implied_demoted`)는 10건이다.
- 시험 화면: 카드와 리스트에 "순위 점수 0.86" 형태로 나온다.
- 수집 상태 화면(8010, 재시작 후): "후처리(LLM) 경고: 없음"이 나온다.
- 오늘 아침 배치 로그에는 `stage_warnings` 키가 없다(이전 형식). 없으면 빈 목록으로 읽는다.

## 재검수 요청

- P1: 시작 장애와 보조 조회 장애의 처리 방식. 특히 보조 조회 실패 시 `fallback_mode`를 None으로 둔 판단(순위는 하이브리드 그대로, 유사도만 없음).
- P2:
  - 11단계 실패를 status 대신 `stage_warnings`와 종료 코드 4로 둔 판단.
  - 날짜당 상한을 "부르기 전 예약" 방식으로 센 것.
- 앞선 업종 허용 갈래 P1 수정(재검수 응답 2)은 Codex가 이번 검수 "확인한 부분"에서 7개 ID 제외를 확인했다. 따로 남은 것이 없으면 종료로 봐도 되는지.
