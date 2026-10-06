# experiments/ — 검증 화면·실험, 그리고 배치·서버가 쓰는 LLM 해석 함수

## 맡는 것
- **배치·서버가 import하는 모듈**(실험 폴더에 있지만 운영 코드다):
  - `sql_semantic/applicant_type_llm.py` — 신청자 유형 LLM 호출·응답 해석·판정 규칙. 배치 11·13단계와 공고 서버(`search/applicant_types`)가 쓴다.
  - `sql_semantic/industry_llm_sample.py` — 업종 LLM 호출·응답 해석. 배치 11·12단계가 쓴다.
  - `sql_semantic/industry_groups.py` — 업종 → KSIC 대분류(`allowed_sections`). 배치 13단계와 공고 서버(`search/industry_rank`)가 쓴다.
- 검증 화면 `sql_semantic/viewer.py`(127.0.0.1:8010): 실행 상태·조건 판정·검색 결과·벡터 상태·판정 결과·전체 흐름(`/flow`)을 사람이 본다. `/compare`는 공고 서버 `/api/match`를 HTTP로 부른다(`SERVICE_URL`). 읽기 전용.
- 별도 로컬 실험 DB 경로(`sql_semantic/prepare`·`search`·`compare`·`conditions`·`embedding`·`schema.sql`): SQL 정형 필터 + 전체 코사인 방식 비교.
- 판정 꾸러미·채점(`label_pack`·`label_score`), 결과 보기용 모듈(`*_results.py`, `jev_probe_results`).
- `notice_api_contract.py`: 조율 쪽 실제 연결 코드로 8000을 HTTP로 불러 보는 계약 시험(결과 `reports/notice_api_contract_<시각>/`). `orchestration_probe.py`: 9/29 직접 import 방식 설명서의 예시 코드 검증(지난 방식).

## 맡지 않는 것
- 운영 추천 경로. 실험 DB 방식은 서비스와 섞지 않는다(다른 앱·다른 포트·다른 DB).
- 공용 DB 쓰기. 실험 경로는 공용 DB를 SELECT만 하고, 쓰기는 로컬 실험 DB에만 한다.
- 조율 쪽 코드(`agent-orchestration/`) 수정. 계약 시험은 작업 폴더 **밖** 임시 폴더에 풀어 쓰고, 작업 트리를 바꾸지 않는다.

## 항상 지켜야 할 것
- 위 운영 모듈 셋은 이름·위치·함수 모양을 바꾸면 배치와 공고 서버가 깨진다. 바꾸면 `collect/`·`search/`의 import 쪽과 시험을 함께 고친다. 폴더 정리 때 지우지 않는다.
- 실험 DB 설정(`sql_semantic/config.py`): `SQL_LAB_*`가 하나라도 없으면 연결하지 않는다. 운영 `MYSQL_*`로 대체하지 않는다. 호스트가 로컬이 아니거나 운영 DB와 host·port·database가 같으면 거부한다. 이 안전 장치를 풀지 않는다.
- 비밀번호·접속 문자열을 로그·결과·화면에 내지 않는다(`describe()`는 비밀번호를 뺀다).
- 검증 화면은 읽기 전용이다. DB에 쓰지 않고, `/compare` 결과도 저장하지 않는다. fixture 결과에는 "실제 검색 결과 아님"을 표시한다.
- 화면에서 알려진 문제(`KNOWN_ISSUES`)를 숨기지 않는다. 검수 승인 전에는 "해결"로 적지 않는다.
- LLM 판정 결과는 "AI 참고 정답"으로 표시한다.

## 이 폴더의 방식
- `-m experiments.sql_semantic.<모듈>`로 부른다. 쓰기가 있는 명령은 `--plan`으로 먼저 확인하고, 단계별 옵션(`--schema`·`--snapshot` …)으로 나눠 실행한다.
- 결과는 `reports/sql_semantic_*`·`reports/<주제>_<시각>Z/`에 새로 남긴다.
- 검증 화면이 보는 결과 폴더 이름은 각 `*_results.py`·`viewer.py`에 적혀 있다. 결과 폴더를 옮기거나 지우면 화면이 빈다.

## 시험
- 관련 시험: `tests/test_sql_semantic.py`, `test_applicant_type_llm.py`, `test_industry_llm_sample.py`, `test_industry_groups.py`, `test_label_score.py`, `test_verify_ui.py`, `test_viewer_nav.py`, `test_filter_first_ui.py`, `test_industry_results_ui.py`, `test_jev_probe_ui.py`, `test_applicant_type_ui.py`.
- 반드시 덮을 경우: 실험 DB 설정 누락·원격 호스트·운영과 같은 DB(연결 거부), 신청자 유형 응답 해석의 강한/약한 불가·세부사업별 허용, 업종 대분류 매핑의 경계(통합공고·잘림·KSIC 아닌 값).
