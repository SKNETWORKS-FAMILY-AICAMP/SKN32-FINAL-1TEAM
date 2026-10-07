# web/ — 시험·검토용 화면 HTML

## 맡는 것
화면 파일 HTML. 서버가 파일을 그대로 읽어 내려 준다(빌드 단계 없음).

| 파일 | 내려 주는 서버 · 경로 |
|---|---|
| `app.html` | 공고 서버 8000 `/` — 신청자 입력 → 추천(카드 3 + 리스트 7, "10건 더 보기", 공고마다 가산점 표시) → 자격 확인(+ 가산점 항목·공고문 가점 원문) |
| `weights.html` | 8000 `/weights` — 가중치 비교(`/api/match_compare`) |
| `review.html` | 8000 `/review` — 자격요건 추출 검토(`/api/conditions`) |
| `demo.html` | 8000 `/demo` — 리랭커 시연(`/api/match_rerank`, 내부 검토용) |
| `classify.html` | 8000 `/classify` — 업력 문장 분류기 시연(`/api/classify`) |
| `verify.html`·`compare.html`·`compare_selftest.html`·`flow.html`·`collection_status.html`·`applicant_types.html`·`industry_probe.html`·`industry_results.html`·`filter_first_eval.html`·`jev_probe.html` | 검증 화면 8010(`experiments/sql_semantic/viewer`) |

## 맡지 않는 것
- 실제 서비스 프론트엔드(저장소 루트 `web/frontend`, 다른 팀원). 이 폴더 화면은 내부 시험용이며 배포 대상이 아니다.
- 판정·점수 계산. 화면은 API 응답을 보여 주기만 한다. 규칙을 자바스크립트로 다시 구현하지 않는다.

## 항상 지켜야 할 것
- 판정 3값을 화면에서도 O·X·?로 구분한다. ?(확인할 수 없음)를 X로 보이지 않게 한다. "확인 필요"는 "자격 충족"이 아니라는 문구를 유지한다.
- 점수를 0~100점·퍼센트로 바꿔 보이지 않는다. 유사도는 원값과 3단 라벨(매우 적합·적합·참고)만.
- 매칭에 쓰이지 않는 입력 칸은 응답의 `stored_only`·`why_not_used`로 "받기만 함"을 보여 준다. 쓰이는 것처럼 보이게 하지 않는다.
- fixture·시연 데이터에는 "실제 검색 결과 아님"을 표시한다. 알려진 문제를 숨기지 않는다.
- 파일 이름을 바꾸면 그 파일을 읽는 서버 코드(`search/app.py` 또는 `viewer.py`)와 화면 시험을 함께 고친다.

## 이 폴더의 방식
- 한 파일 안에 HTML·CSS·자바스크립트를 함께 둔다. 외부 라이브러리는 쓰지 않거나 최소로 한다.
- API 주소는 같은 서버의 상대 경로(`/api/...`)로 부른다.

## 시험
- 관련 시험: `tests/test_verify_ui.py`, `test_viewer_nav.py`, `test_filter_first_ui.py`, `test_industry_results_ui.py`, `test_jev_probe_ui.py`, `test_applicant_type_ui.py`(화면 문구·구조·경로).
- 화면을 고치면 해당 서버를 켜고 브라우저로 직접 확인한다(8000·8010을 켜거나 끄기 전에 사용자에게 확인).
