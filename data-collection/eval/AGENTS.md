# eval/ — 검색 품질 평가

## 맡는 것
- 평가셋(topic-v1): `queries.jsonl`(질의 60 — 정상 52·무관 8, `MatchRequest` 모양 + `as_of_date`), `pool.jsonl`(판정 후보, Dense@20 ∪ BM25@10), `llm_judgments.jsonl`, `human_judgments.jsonl`(덧붙이기만), `qrels.jsonl`(최종 정답, `judge` = human / llm / llm_unreviewed), `splits.json`.
- 만들기·판정: `build_pool.py`, `judge_llm.py`(`--plan`으로 비용 먼저), `merge_qrels.py`(qrels + 블라인드 일치율), `label_app.py`·`label.html`(사람 판정 화면, 127.0.0.1:8001, 내부 전용), `relevance_label_pack.py`·`relevance_label_score.py`(Codex 판정 꾸러미·채점).
- 지표·비교: `evaluate.py`, `metrics_report.py`·`metrics_pdf.py`, `filter_first_eval.py`(정형 필터 선행 전후), `query_ablation.py`(입력 칸 빼기), `weight_eval.py`·`industry_weight_probe.py`, `bonus_rank_eval.py`, `gate_eval.py`, `region_eval.py`, `match_variants.py`, `search_comparison.py`, `chroma_integrity.py`(DB·npz·Chroma 정합성, 읽기 전용), `jev_judge_probe.py`(외부 채점 시험).
- 공용 함수: `common.py`(질의 문장 등), `bm25.py`.

## 맡지 않는 것
- 서비스 동작. 평가는 서비스와 **같은 함수**(`search.app.match`·`rank_rules`·`eligible_with_types`)를 불러 잰다. 규칙을 이 폴더에 복사해 따로 두지 않는다.
- 서비스 기본값 바꾸기. 평가 결과는 근거일 뿐, 기본값 변경은 사용자 결정이다.
- 공용 DB 쓰기. 이 폴더는 SELECT와 로컬 파일만 쓴다.

## 항상 지켜야 할 것
- `topic_rel`은 2·1·0·null. **null·미판정은 0이 아니다** — 지표에서 뺀다. 무관 질의도 자동 0이 아니라 똑같이 판정한다.
- 판정 기준은 "지원 내용과 분야만" 본다(지역·업력·나이·규모·신청자 형태·마감은 무시). 신청 가능 여부는 별도 지표(신청 불가@K)로 잰다.
- 블라인드 판정은 LLM 답을 보기 전에 한다. 사람 판정은 덧붙이기만 하고 고치지 않는다.
- 학습·시험 분할은 **질의 단위**다(사람 판정 143쌍이 49개 질의에 흩어져 있다).
- Codex·LLM 판정은 "AI 참고 정답"이다. `human` 칸에 넣지 않는다. 판정을 본 뒤 그 판정에 맞춰 프롬프트를 고친 결과를 성능 근거로 쓰지 않는다.
- 새 검색 방식이 미판정 공고를 상위에 올리면 `build_pool.py`에 그 방식을 넣어 쌍을 **추가**하고 같은 `label_version`으로 보충한 뒤 모든 방식을 다시 잰다.
- 결과는 `reports/<주제>_<UTC 시각>Z/` 새 폴더에 남긴다. 기존 결과 폴더를 덮지 않는다.
- 결과에 질의·공고 데이터 기준, 색인 상태·기준일, Top-K, 검색 방식, RRF 가중치, 마감·지역·지원대상 처리, 리랭커 여부, 정답 버전·판정 출처·미판정 비율을 남긴다. 코사인을 정확도로 쓰지 않는다. 차이는 95% 구간과 함께 쓰고, 구간이 0을 포함하면 "차이를 말할 수 없다"고 쓴다.
- `search_comparison.py`는 정합성 검사가 통과해야 검색을 시작한다. 불일치면 색인을 자동으로 다시 만들지 않고 멈춘다(종료 코드 0 통과·2 불일치·4 확인 실패).

## 이 폴더의 방식
- 대부분 파일 경로로 실행한다: `.\.venv\Scripts\python.exe -X utf8 eval\<파일>.py`. 유료 호출이 있는 스크립트는 `--plan`이 있다.
- `as_of_date`로 "창업 N년차"를 고정한다(서비스 코드는 고치지 않음).
- 평가용 `NumpyCollection`은 Chroma 없이 벡터를 메모리에서 계산한다(`ids` 인자 없음 → 서비스의 `'vectors'` 경로). 서비스 자체도 2026-10-07부터 `search/memvec.MemoryCollection`(공용 DB 벡터)을 쓴다. 예전 방식(Chroma)과 같은 벡터로 비교하는 도구는 `vector_db_compare.py`.

## 시험
- 관련 시험: `tests/test_filter_first_eval.py`, `test_query_ablation.py`, `test_match_variants.py`, `test_search_comparison.py`, `test_chroma_integrity.py`, `test_label_score.py`.
- 반드시 덮을 경우: null 판정 제외, 평가와 서비스가 같은 필터·규칙 결과를 내는지, 정합성 불일치 시 중단.
