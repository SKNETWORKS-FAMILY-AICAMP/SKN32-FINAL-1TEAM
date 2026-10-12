# 단위 테스트 결과 — 2026-10-12T02:07:43.106393+00:00

전체 965개 · 통과 949 · 실패 0 · 오류 0 · 건너뜀 16
범위 안 줄 커버리지 69.5% (7566줄 중 5258줄 실행)

## 이번 판에 대해

- 요청: 매칭 관련 단위 테스트를 다시 진행하고 기록을 남긴다(2026-10-12, 사용자). 방식은 10/7 판(`../unit_test_20261007T062019Z/`)과 같다. 시험을 더하거나 운영 코드·시험을 고치지 않고, 지금 코드 그대로 다시 쟀다.
- 명령(저장소 `data-collection/`에서, `PYTHONPATH`=이 폴더):
  `.\.venv\Scripts\python.exe -X utf8 -m coverage run --data-file=<이 폴더>\.coverage -m run_unit <이 폴더>\tests.json` → `python cov_summary.py <이 폴더>` → `python compare_prev.py ../unit_test_20261007T062019Z <이 폴더>`
- 환경: Python 3.12.10, coverage 7.16.2, Windows 11. 외부 API·공용 DB·OpenAI는 부르지 않음. 실행 7.8초.
- 기능 배정: 10/7 판 그대로 + 그 뒤 생긴 `test_model_options`를 ⑤에 넣음. `test_backup_db`(백업 도구)·`test_bonus_boostable`·`test_bonus_rank_cases`(평가 도구)는 서비스 기능이 아니라 범위 밖으로 셈(통과는 함).
- 건너뜀 16개는 모두 MySQL 통합 시험(②6·③10, `MYSQL_INTEGRATION_TEST=1`일 때만 돎) — **확인 안 함**. 매칭 쪽(⑦~⑩)에는 건너뛴 시험이 없다.
- 이전 판과의 차이는 `compare_prev.md`. 요약: 시험 884 → 965(+81, 없어진 시험 0), 범위 커버리지 67.6% → 69.5%. 늘어난 것은 가산점 규칙(결정 0016~0020, `search/bonus.py` 239 → 610줄, 시험 28 → 67)과 gpt-6-luna 전환(결정 0013, ⑤ 시험 +13).

## 매칭 쪽(⑦~⑩) 요약

| 기능 | 시험 | 통과 | 커버리지 | 10/7 판 |
|---|---|---|---|---|
| ⑦ 정형 필터·자격 판정 | 97 | 97 | 96.7% | 97개 · 96.7% |
| ⑧ 검색·순위 | 84 | 84 | 78.0% | 83개 · 77.3% |
| ⑨ 조율 창구 | 41 | 41 | 80.8% | 41개 · 80.8% |
| ⑩ 가산점 | 67 | 67 | 98.0% | 28개 · 99.2% |
| 합계 | 289 | 289 | | 249개 |

- ⑧이 78%에 머무는 주된 이유는 `search/app.py`(70.7%)에서 실행 안 된 206줄이다. 대부분 추천 흐름 밖 — 추출 결과 검토용 `/api/conditions`(1014~1082줄), 시연용 리랭커·업력 분류기 창구(`/api/match_rerank`·`/api/classify`, 서비스 미연결, 1124~1253줄), `/api/health`, 서버 시작 `main`.
- ⑨: `search/content_version.py`(63.5%)는 명령줄 저장·비교(107~132줄), `search/collection_status.py`(75.2%)는 화면 참고용 `history`(162~181줄)가 시험 밖이다. 조율 창구 응답을 만드는 `search/notice_api.py`는 100%.
- ⑩ `search/bonus.py`에서 실행 안 된 12줄은 흩어진 한 줄짜리 분기다(207·226·275·…·839줄).
- ⑩은 코드가 2.5배로 늘었는데도 98% — 새 규칙마다 시험이 함께 들어왔다.

## 전체 표(자동 생성)

| 기능 | 시험 | 통과 | 건너뜀 | 실패 | 커버리지 |
|---|---|---|---|---|---|
| ① 공고 수집 | 9 | 9 | 0 | 0 | 64.7% |
| ② 정규화·공용 DB 저장 | 29 | 23 | 6 | 0 | 57.5% |
| ③ 첨부 본문 추출 | 78 | 68 | 10 | 0 | 56.7% |
| ④ 임베딩·벡터 공유 | 21 | 21 | 0 | 0 | 43.3% |
| ⑤ AI 추출·판정 올리기 | 222 | 222 | 0 | 0 | 71.0% |
| ⑥ 매일 배치 흐름 | 17 | 17 | 0 | 0 | 51.9% |
| ⑦ 정형 필터·자격 판정 | 97 | 97 | 0 | 0 | 96.7% |
| ⑧ 검색·순위 | 84 | 84 | 0 | 0 | 78.0% |
| ⑨ 조율 창구 | 41 | 41 | 0 | 0 | 80.8% |
| ⑩ 가산점 | 67 | 67 | 0 | 0 | 98.0% |
| ⑪ 공통 설정 | 9 | 9 | 0 | 0 | 20.1% |

| 파일 | 줄 | 실행 | 커버리지 |
|---|---|---|---|
| collect/daily_job.py | 147 | 87 | 59.2% |
| collect/fetch.py | 43 | 42 | 97.7% |
| collect/fetch_bizinfo.py | 39 | 13 | 33.3% |
| collect/job_lock.py | 26 | 23 | 88.5% |
| collect/normalize.py | 183 | 152 | 83.1% |
| shared/store_mysql.py | 226 | 83 | 36.7% |
| collect/attachment_pipeline.py | 221 | 193 | 87.3% |
| collect/attachment_store.py | 179 | 67 | 37.4% |
| collect/doctext.py | 180 | 87 | 48.3% |
| collect/hwp5.py | 113 | 46 | 40.7% |
| shared/embed.py | 144 | 55 | 38.2% |
| collect/upload_vectors.py | 81 | 74 | 91.4% |
| collect/upload_attachments.py | 98 | 67 | 68.4% |
| search/vecstore.py | 218 | 38 | 17.4% |
| collect/extract_conditions.py | 353 | 143 | 40.5% |
| collect/applicant_type_daily.py | 172 | 141 | 82.0% |
| collect/industry_daily.py | 183 | 143 | 78.1% |
| collect/upload_judgments.py | 174 | 158 | 90.8% |
| collect/extract_bonus.py | 444 | 281 | 63.3% |
| experiments/sql_semantic/applicant_type_llm.py | 249 | 109 | 43.8% |
| experiments/sql_semantic/industry_llm_sample.py | 938 | 772 | 82.3% |
| experiments/sql_semantic/industry_groups.py | 137 | 135 | 98.5% |
| collect/daily_pipeline.py | 351 | 182 | 51.9% |
| search/gate.py | 104 | 104 | 100.0% |
| search/eligibility.py | 38 | 38 | 100.0% |
| search/applicant_types.py | 252 | 241 | 95.6% |
| search/age_evidence.py | 85 | 80 | 94.1% |
| search/app.py | 703 | 497 | 70.7% |
| search/hybrid.py | 55 | 52 | 94.5% |
| search/memvec.py | 58 | 57 | 98.3% |
| search/rank_rules.py | 21 | 16 | 76.2% |
| search/industry_rank.py | 99 | 91 | 91.9% |
| search/applicant.py | 51 | 51 | 100.0% |
| shared/region.py | 75 | 64 | 85.3% |
| search/notice_api.py | 100 | 100 | 100.0% |
| search/collection_status.py | 113 | 85 | 75.2% |
| search/content_version.py | 74 | 47 | 63.5% |
| search/bonus.py | 610 | 598 | 98.0% |
| shared/config.py | 47 | 46 | 97.9% |
| ec2/ec2_vecstore.py | 182 | 0 | 0.0% |
