# search/ — 공고 서버

## 맡는 것
- `app.py`: FastAPI 앱. `boot()`가 공고·색인·판정표·가점을 메모리(`STATE`)에 올리고, `/api/match`(추천)·`/api/eligibility`(화면용 자격 확인)·`/api/health`·`/api/conditions`·`/api/form`·`/api/match_compare`·`/api/match_rerank`·`/api/classify`와 시험 화면(`web/*.html`)을 낸다. `python -m search.app`으로 켠다(PC 127.0.0.1, 리눅스 0.0.0.0, `PORT`).
- `notice_api.py`: 조율 창구 — `/api/collection_status`, `/api/notices/{id}`, `/api/notices/{id}/eligibility`. `build_router(STATE, connect)`로 붙는다.
- `gate.py`: 업력·접수기간·모집 상태 판정, 정형 필터 `prefilter`, 업력 계산. LLM 없음.
- `eligibility.py`: 자격 판정 네 줄을 만드는 **유일한** 곳(화면용·조율용 공용).
- `applicant_types.py`: 공고 본문 신청자 유형 판정 읽기(DB→파일, 지문 확인)와 해석. `industry_rank.py`: 업종 판정 읽기·허용 목록 밖 판정. `age_evidence.py`: 업력 근거(설명용).
- `hybrid.py`: BM25와 RRF(`RRF_K=60`, `DEPTH=50`). `memvec.py`: 공용 DB 공고 벡터를 메모리에 올린 의미 검색 묶음(count·query·get — Chroma와 같은 모양, 전부 비교). `vecstore.py`: PC 질의 임베딩(`embed_query`)과 배치 7단계 로컬 Chroma 동기화(공고 서버 검색에는 안 씀). `rank_rules.py`: 대상 집단 규칙(서비스·평가 공용). `applicant.py`: 신청자 입력의 질의·규칙·받기만 갈래, 인증 목록.
- `collection_status.py`: 수집 상태 판정(순수 함수 `judge`, 읽기 전용). `content_version.py`: 공고 내용 지문(`cv2-`)과 하루 비교 명령. `bonus.py`: 공고 가점 × 신청자 → 가산점.

## 맡지 않는 것
- 데이터 만들기·DB 쓰기 일체(`collect/`). 이 폴더 코드는 DB에 SELECT만 한다.
- 임베딩 입력 정의(`shared/embed.build_input`)와 DB 접속(`shared/store_mysql`, 리눅스는 `ec2/ec2_vecstore`).
- 신청자 유형·업종 판정의 LLM 응답 해석 본체(`experiments/sql_semantic`, 여기서 import).
- 화면 HTML 본문(`web/`). 조율 에이전트 쪽 코드(`agent-orchestration/`, 다른 팀원 — 고치지 않는다).

## 항상 지켜야 할 것
- `match()` 순서: 정형 필터(모든 공고) → 필터 통과 공고 안에서만 검색 → 규칙 재정렬 → 자르기. 필터를 검색 뒤로 옮기지 않는다. 대체 경로에서도 필터를 건너뛰지 않는다. 통과 0건이면 인코딩·검색을 하지 않는다.
- 정형 필터가 빼는 이유는 `모집 마감`·`접수 마감`·`업력·신청자 유형`·`예비창업자 불가(공고 본문)` 넷뿐이다. 지역·업종·대상 집단·가산점은 순서만 바꾼다.
- 판정 값은 True·False·None 3값이다. None을 False로 바꾸지 않는다. 자격 판정 `passed`는 "False 없음"이다.
- 같은 공고·신청자면 `eligible_with_types`(추천 필터)와 `eligibility.conditions`(자격 판정)의 결론이 같아야 한다. 판정 규칙은 `eligibility.py`·`gate.py`에서만 고친다.
- 조율용 자격 판정은 `지원대상 유형`·`업력` 두 줄만 쓴다(접수기간·모집 상태 줄은 버린다). 기준일은 요청의 `today`.
- `notice_api.py`는 `app.py`를 import하지 않는다(`__main__` 이중 사본으로 `STATE`가 비어 버린다).
- 재정렬은 한 번의 정렬 키로: 다른 시·도 → 다른 시·군·구 → 예비창업자 불가 추정 → 업종(기본 꺼짐) → 대상 집단 → (가산점 세기 > 0일 때) 가산점 반영 점수 → 검색 순서.
- `Weights()` 기본값 = 서비스 동작. `bonus` **0.2**(2026-10-08 결정 0017 — 원문 대조를 마친 공고 목록 `bonus_reviewed.json`에 있는 공고만 얹는다), `demote_industry` false, `mode='order'`. 기본값을 바꾸지 않는다(평가 근거·사용자 결정 전).
- 가산점 순위 반영은 `bonus_boost`가 `bonus.reviewed_ok`(목록에 있고 `content_version`·`row_fingerprint`가 대조 당시와 같고 결과 항목이 모두 `approved_items` 안)일 때만 한다. 결과 칸 `bonus_verified`(결정 0018)는 세기·경로와 상관없이 목록과 맞으면 참(`app.bonus_verified` — 목록 판단 예외는 거짓으로, 검색을 멈추지 않음), `bonus_rank_applied`는 실제로 얹은 공고만 참(대조됨일 때만). 목록은 지문 세 개(`content_version`·`row_fingerprint`·`evidence_fingerprint`, 가점 행에 원문 지문이 없으면 대조 안 됨)와 승인 항목으로 비교하고, `load_reviewed`가 값 모양(점수는 유한한 양수 등)을 검사해 어긋나면 전체 거부한다. `boot()`가 목록을 못 읽으면 `boot_errors.bonus_reviewed`·목록 전체 미사용. 목록은 `eval.bonus_boostable --write-reviewed`로만 고친다.
- HTTP `/api/match`는 `_public()`으로 누적 20건(`MAX_CANDIDATES`)을 넘지 않게 자른다. 상위 3건(`CARD_COUNT`)이 `card`.
- 점수를 0~100으로 바꾸지 않는다. `band` 기준 0.62·0.55, `fit_score`는 RRF ÷ 그 경로 이론 최대값(마감임박순 null).
- `boot()`: 공고 정보·BM25 실패만 서버를 멈춘다. 벡터 DB·임베딩·지문·금액·가점·판정표 실패는 그 기능만 끄고 `boot_errors`에 남긴다. 저장 시각(`loaded_store_at`)은 공고보다 **먼저** 읽는다.
- 가산점(`bonus.py`)은 **확인된 가산점 부분합**(결정 0012)이고 "확실한 것만"이다: 근거 문장에 그 "N점"이 직접 있고 다른 "N점"이 섞이지 않아야 점수 인정(`points_supported`), 근거가 지금 원문에 그대로 이어져 있어야 함(`load`가 found 행마다 `in_document` 확인 — 원문을 못 읽으면 found 는 null·`boot_errors.bonus_documents`), 묶음은 group 이름으로만·묶음 오분류 가능성(다른 묶음 같은 근거·점수, 한 묶음인데 "각")이면 null, 앞으로의 조건(`FUTURE_WORDS`)·확인할 수 없는 조건 말(`CONDITION_WORDS`)·추가 조건이면 해당을 모름으로(단 증빙 서류·유효기간·"중소기업"처럼 뜻이 안 바뀌는 추가 조건은 예외 — `benign_extra`, `BENIGN_PAPER`·`BENIGN_VALID`·`RISKY_WORDS`, 결정 0014), found 에 불확실 메모가 있으면 null(결정 0020부터는 전체 메모만 — 부분 메모는 가리키는 항목만 모름), 세부사업 결과가 다르면 null, 합이 한도를 넘으면 null. 결정 0016(Codex 재재검수): ① "및·&"로 묶인 짝을 확인할 수 없으면 모름(짝을 안 가진 것이 확실하면 "둘 중 하나") ② 원문 한 줄에 증빙+기간+가점·인정이 있으면 인증 항목 모름(`load`가 `period_lines` 표시) ③ 결정 0014 예외는 같은 인증 증빙만(`same_cert_paper`) ④ "N점"이 항목 대상 말과 같은 조각에 있어야(`points_owned`) ⑤ 원문 택1 말 + 두 묶음 이상이면 null(`selection`) ⑥ 나이 구절 제거는 청년만. 결정 0017(Codex 3차): ③ 대상 말은 인증 코드·별칭·종류 말만(`cert_words`), ① "및" 짝이 안 뽑혀도 모름, ④ 원문 줄 경계(`quote_lines`, 배점 칸·"*" 줄은 앞줄에 붙임), ② 각주 이어진 줄, found 행 `row_fingerprint`. 결정 0018(Codex 4차): 배점 없는 "*" 줄은 앞줄에 자격 이름(`_QUALIFICATION_WORDS`)이 없을 때만 붙임, found 행 `evidence_fingerprint`(원문 조각 정렬·줄바꿈 통일). 결정 0019(표 배점 칸): 근거에 "N점"이 없어도 원문 근거 앞 1,500자 안에 "배점" 머리(`score_header`)가 있고 단위 없는 숫자가 하나면 점수(`_table_cell`), 점수 주인은 숫자 줄 앞 줄들을 행 이름으로 합쳐 짝 자격(`table_mates`)만 있을 때 — 두 표시는 `row_fingerprint`에 넣지 않는다. 결정 0020: 부분 메모는 가리키는 항목만 모름(`memo_is_global`), 자격만 말하는 "경우"는 조건 아님(`condition_words_hit`), 같은 숫자 반복·아니오(0)(`bare_numbers`), 한 문장 속 여러 N점의 쉼표 조각 주인(`points_supported`), 다른 묶음의 "각 N점"은 더함, 짝은 `cert_words`(`quote_mates`)·행 이름은 숫자 줄 바로 앞 줄 + 잇는 말, "배점" 머리는 같은 표만(`score_header`), 자격 이름은 띄어쓰기를 지우지 않고 찾는다(`qualification_words`). `score`는 이전 계산(`_score(strict=False)`)이 null이면 null, 이전보다 크면 null — 새 규칙이 null을 풀지 않는다. 판단 단어는 모듈 상수(조정 가능)다. 결과는 양수 → null(또는 더 작은 양수) 쪽으로만 움직여야 한다(결정 0014·0019·0020 예외만 null → 양수 — `bonus_boostable --old`는 이것을 "모름→양수"로 따로 센다) — 바꾼 뒤 `python -m eval.bonus_conservative_compare --old <이전 bonus.py>`와 조합 단위 `python -m eval.bonus_boostable --old <이전 bonus.py>`로 확인한다.
- 가점은 추출 당시 내용 지문과 `EXTRACTOR_VERSION`이 지금과 같은 행만 쓴다. 내용 지문을 계산하지 못하면 가점을 하나도 쓰지 않는다. 신청자 유형 판정도 지금 공고문 지문과 같은 것만 쓰고, 지문을 모르면 기능 전체를 끈다.
- 조율 창구 응답 모양: 공고 없음은 404 `{"code": "NOTICE_NOT_FOUND"}`, 수집 상태 DB 실패는 503 `{"code": "COLLECTION_STATUS_UNAVAILABLE"}`(상태를 지어내지 않음, DB 주소·오류 원문을 싣지 않음). 키·값을 바꾸면 조율 쪽이 깨진다.
- 신청자 입력을 파일·DB·로그에 쓰지 않는다. 사업자번호 값은 응답에 내지 않는다.
- 검색 오류는 `_describe`로 표준 오류 출력과 응답 `search_errors`에 남긴다. 조용히 삼키지 않는다.

## 이 폴더의 방식
- 무거운 import(numpy·sentence-transformers·ec2·판정 모듈)는 함수 안에서 한다. 공고 서버는 chromadb를 import하지 않는다. 패키지가 없어도 서버의 나머지가 뜨게 하기 위해서다.
- 판정 읽기 함수(`applicant_types.load_auto`, `industry_rank.load_auto`, `age_evidence.load`)는 예외를 내지 않고 `{'active': False, 'error': …}`를 돌려준다. 새 판정표도 같은 모양으로 만든다.
- 응답에 "무엇이 쓰였고 무엇이 안 쓰였는지"를 함께 싣는다(`filter.excluded`, `pipeline`, `stored_only`, `why_not_used`, 규칙별 `*_demoted`).
- 의미 검색은 `col.query(ids=통과 공고)`(정상 경로 `dense_path='memory'`). 벡터가 없는 공고는 미리 뺀다. `ids`를 모르는 묶음(평가용 `NumpyCollection` 등)은 벡터를 꺼내 직접 코사인(`'vectors'` 경로)으로 대신한다.
- 공고 벡터는 `_collection()`이 공용 DB에서 읽는다(1,024차원·4,096바이트만). 0건·DB 오류는 예외 → `boot()`가 의미 검색 없이 연다. 지문이 질의 인코더와 다르면 `boot_errors['vector_fingerprint']` 경고만 남긴다. `STATE['collection']`·`STATE['vector_ids']` 이름·모양은 평가 도구가 감싸 쓰므로 바꾸지 않는다.
- 질의 벡터는 `np.asarray(…, dtype='float32').tolist()`로 넘긴다.

## 시험
- 관련 시험: `tests/test_gate.py`, `test_match_rules.py`, `test_match_deh.py`(정형 필터·대체 경로·후보 수·boot), `test_notice_api.py`(창구·지문·수집 상태), `test_bonus.py`, `test_applicant_types.py`, `test_applicant.py`, `test_industry_rank.py`, `test_age_evidence.py`, `test_collection_status.py`, `test_judgments_source.py`, `test_match_variants.py`, `test_verify_ui.py`.
- 반드시 덮을 경우: 업력 칸 빈 값·못 읽는 값(None), 예비창업자 전용 ↔ 사업자, 설립일 없는 사업자(UNKNOWN_AGE ≠ 예비창업자), 달력에 없는 날짜(예외 없이 None), 접수 시작 전 공고(필터 통과·화면용 접수기간 False·조율용 판정 무관), 본문 "가능"이 API 업력 불가를 덮음, 세부사업별 예비창업자 허용(업력 None), 판정표 지문 불일치(쓰지 않음), 임베딩·BM25·둘 다 실패(대체 경로 3종), 통과 0건, offset 10·누적 20, 가산점 0·null 구분과 한도·묶음·세부사업, 404·503 본문.
- 시험에서는 `STATE`와 `_connect`를 가짜로 바꿔 끼운다(`app.include_router`가 `lambda: _connect()`로 감싼 이유). 실제 공용 DB·모델을 부르지 않는다.
