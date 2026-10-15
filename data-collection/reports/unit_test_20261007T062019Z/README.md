# 단위 테스트 결과 — 2026-10-07T06:20:20.247359+00:00

전체 884개 · 통과 868 · 실패 0 · 오류 0 · 건너뜀 16
범위 안 줄 커버리지 67.6% (7140줄 중 4824줄 실행)

| 기능 | 시험 | 통과 | 건너뜀 | 실패 | 커버리지 |
|---|---|---|---|---|---|
| ① 공고 수집 | 9 | 9 | 0 | 0 | 64.7% |
| ② 정규화·공용 DB 저장 | 29 | 23 | 6 | 0 | 57.5% |
| ③ 첨부 본문 추출 | 78 | 68 | 10 | 0 | 56.7% |
| ④ 임베딩·벡터 공유 | 21 | 21 | 0 | 0 | 43.3% |
| ⑤ AI 추출·판정 올리기 | 209 | 209 | 0 | 0 | 70.0% |
| ⑥ 매일 배치 흐름 | 17 | 17 | 0 | 0 | 51.9% |
| ⑦ 정형 필터·자격 판정 | 97 | 97 | 0 | 0 | 96.7% |
| ⑧ 검색·순위 | 83 | 83 | 0 | 0 | 77.3% |
| ⑨ 조율 창구 | 41 | 41 | 0 | 0 | 80.8% |
| ⑩ 가산점 | 28 | 28 | 0 | 0 | 99.2% |
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
| collect/extract_conditions.py | 350 | 132 | 37.7% |
| collect/applicant_type_daily.py | 163 | 132 | 81.0% |
| collect/industry_daily.py | 163 | 127 | 77.9% |
| collect/upload_judgments.py | 175 | 159 | 90.9% |
| collect/extract_bonus.py | 442 | 274 | 62.0% |
| experiments/sql_semantic/applicant_type_llm.py | 249 | 103 | 41.4% |
| experiments/sql_semantic/industry_llm_sample.py | 938 | 771 | 82.2% |
| experiments/sql_semantic/industry_groups.py | 137 | 135 | 98.5% |
| collect/daily_pipeline.py | 351 | 182 | 51.9% |
| search/gate.py | 104 | 104 | 100.0% |
| search/eligibility.py | 38 | 38 | 100.0% |
| search/applicant_types.py | 252 | 241 | 95.6% |
| search/age_evidence.py | 85 | 80 | 94.1% |
| search/app.py | 681 | 474 | 69.6% |
| search/hybrid.py | 55 | 52 | 94.5% |
| search/memvec.py | 58 | 57 | 98.3% |
| search/rank_rules.py | 21 | 16 | 76.2% |
| search/industry_rank.py | 99 | 91 | 91.9% |
| search/applicant.py | 51 | 51 | 100.0% |
| shared/region.py | 75 | 63 | 84.0% |
| search/notice_api.py | 100 | 100 | 100.0% |
| search/collection_status.py | 113 | 85 | 75.2% |
| search/content_version.py | 74 | 47 | 63.5% |
| search/bonus.py | 239 | 237 | 99.2% |
| shared/config.py | 47 | 46 | 97.9% |
| ec2/ec2_vecstore.py | 182 | 0 | 0.0% |
