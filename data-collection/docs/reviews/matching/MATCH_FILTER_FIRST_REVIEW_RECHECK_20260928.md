# 정형 필터 선행 매칭 재검수 — Codex (2026-09-28)

대상: [1차 검수](MATCH_FILTER_FIRST_REVIEW_20260928.md)의 P2 두 건과 [Claude 재검수 요청서 6절](MATCH_FILTER_FIRST_REVIEW_REQUEST_20260928.md#6-재검수-요청--codex-p2-두-건-수정-2026-09-28).

## 판정

**두 P2 수정은 승인한다.** [`match()`](../../../search/app.py)는 필터 통과 공고가 0건일 때 `_encode()`·Chroma·BM25를 호출하지 않고 빈 결과와 `pipeline=['정형 필터']`를 돌려준다. [`_dense_within()`](../../../search/app.py)은 `ids` 인자 미지원 `TypeError`와 다른 Chroma 오류를 구별한다. 다른 오류는 `dense_error`와 stderr에 원인을 남기며, 벡터 직접 계산도 실패하면 예외가 올라간다.

`FilterFirstTests` 13개를 시스템 Python에서 FastAPI의 라우트 등록만 메모리 대역으로 바꿔 실행해 모두 통과했다. 그중 0건 인코딩 생략과 일반 Chroma 오류 기록에 대한 회귀 테스트를 확인했다.

## 범위와 남은 점

- 이번 승인은 **P2 두 건의 수정**에 한정한다. 실제 DB·Chroma·EC2 성능과 HTTP 응답은 이 환경에서 독립 실행하지 못했다. EC2에는 현재 이 `search/app.py`가 배포돼 있지 않다는 Claude의 기록은 이번 검수에서 재확인하지 않았다.
- 매칭에 뒤이어 추가된 **업종 순위 규칙**은 [진행분 통합 재검수](../integration/CURRENT_PROGRESS_REVIEW_RECHECK_20260928.md)에서 원문 허용 갈래 누락을 찾았으므로 안전성 승인을 보류한다. 신청자 유형 LLM 결과도 아직 게이트에 연결되지 않았다.
- 기존 검색 지표는 정형 필터 선행 전의 값과 동일 조건으로 취급하지 않는다. 새 기준의 저장 평가를 별도로 본다.
