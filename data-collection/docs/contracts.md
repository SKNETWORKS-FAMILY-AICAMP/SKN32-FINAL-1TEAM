# 바깥과의 약속 (창구 계약)

이 폴더를 쓰는 쪽은 둘이다. **조율 에이전트**(다른 팀원, `agent-orchestration/`)는 공고 서버 HTTP 창구를, **팀원**은 공용 DB 테이블을 읽는다. 조율 쪽 요청서는 `origin/feature/SB-87-init-supervisor-integration:agent-orchestration/docs/공고서버_API요청_공고팀전달.md`(2026-10-03, 10-04 보완)다.

## 1. 공통 약속 (공고 서버)

- 주소: 지금은 사용자 PC `http://127.0.0.1:8000`. 배포 주소는 미정. 조율 쪽은 `SBRAIN_NOTICE_API_URL`을 넣어야 연결이 켜진다(아직 꺼짐).
- 인증: 없음(정책 미정). 바깥에 공개하지 않는 것을 전제로 한다.
- 본문은 JSON, 글자는 UTF-8. 한글 값(`'정상'`, `'예비창업자'`, `'임베딩단독'` 등)은 정확히 그 글자로 비교한다.
- 공고 ID는 경로에 **퍼센트 인코딩**해서 넣는다(`kstartup%3A179323`). `/`가 든 ID도 받는다.
- 요청 형식이 틀리면 422(FastAPI 검증 오류 본문).
- **공고가 없으면 404 + 본문 최상위 `{"code": "NOTICE_NOT_FOUND"}`.** 본문 `code`가 없는 404는 경로가 틀린 것이다 — 둘을 구분한다.
- 날짜는 `YYYY-MM-DD` 문자열, 시각은 ISO 8601(UTC, 시간대 포함).
- "모름"은 null(또는 빈 목록)이다. 0·false·빈 문자열을 모름의 뜻으로 쓰지 않는다.
- 응답에 약속 밖의 키가 더 있을 수 있다(참고용). 소비 쪽은 약속한 키만 쓴다.
- 서버 데이터는 서버를 켠 시각 기준이다. 배치 뒤 서버를 다시 켜기 전까지 새 공고는 응답에 없다.

## 2. `GET /api/collection_status` — 수집 상태

| | 내용 |
|---|---|
| 입력 | 없음 |
| 출력 200 | `status`: `'정상'`·`'지연'`·`'실패'` 중 하나 (**약속 키는 이것뿐**). 참고 키: `reasons`(문장 목록), `db_status`(DB 기준 판정), `last_run_at`, `loaded_store_at`(서버가 올린 공고의 저장 시각), `checked_at` |
| 오류 503 | `{"code": "COLLECTION_STATUS_UNAVAILABLE", "error": "<예외 이름>: 수집 상태를 읽지 못했다"}` — DB를 못 읽음. 상태를 지어내지 않는다. 다시 부르면 된다. DB 주소·오류 원문은 싣지 않는다 |

- `실패`: 저장 기록 없음 / 최근 배치 실패 / 최근 배치에서 출처 하나 이상 실패 / 기업마당 스냅샷 재사용.
- `지연`: 마지막 저장이 24시간 초과, 또는 **서버가 올린 공고가 24시간 초과이거나 그 시각을 모름**.
- 추천을 멈출지는 소비 쪽(조율)이 이 값으로 정한다. 추천 창구는 상태와 관계없이 답한다.

## 3. `POST /api/match` — 공고 추천

입력(조율 쪽이 쓰는 칸):

| 칸 | 형식 | 비고 |
|---|---|---|
| `applicant_type` | `'예비창업자'`·`'개인사업자'`·`'법인'` | 필수 |
| `idea` | 문자열 | 필수 |
| `founded_at` | `'YYYY-MM-DD'` 또는 `''` | 사업자 업력 계산. 빈 값이면 업력 모름 |
| `top` · `offset` | 정수, 기본 10 · 0 | 추가 조회는 `offset=10`. **누적 20건 상한**에서 잘린다 |
| `region` · `district` | 시·도 이름(16개 중 하나) 또는 `''` · 시·군·구 | 순위에만 씀 |
| `gender`, `certifications`(목록), `main_industry`, `first_startup`(참·거짓·null), `birth_date`, `team`, `revenue`, `hiring_plan`, `partners` | | 질의·규칙·가산점. 받기만 하는 칸은 응답 `stored_only`에 드러난다 |
| `certifications` | 문자열 목록 | **`[]`는 "확인된 없음"**으로 계산한다(모름이 아니다) |

출력 200 — 결과 목록 `results`의 한 건:

| 키 | 뜻 |
|---|---|
| `notice_id`, `title`, `organizer`, `source`, `target_category`, `category`, `apply_start`·`apply_end`(빈 문자열 가능), `apply_period_type`, `url`, `region` | 공고 카드 정보 |
| `rank` | 전체 기준 순위(추가 조회면 11~20) |
| `display_type` | 1~3위 `'card'`, 나머지 `'list'` |
| `score` · `band` | 코사인 유사도(소수 4자리) · `'매우 적합'`·`'적합'`·`'참고'`. 벡터를 못 구한 공고는 둘 다 null |
| `fit_score` | 0~1(소수 3자리). 정상 결과에서는 0이 되지 않는다. 대체 경로 `마감임박순`이면 null |
| `region_match` · `district_match` | 참·거짓·null(모름) |
| `content_version` | `'cv2-…'` 공고 내용 지문, 계산 못 하면 null. **같은지만 비교한다**(크기·순서 의미 없음) |
| `bonus_score` | 숫자(0 = 받을 가산점 없음) 또는 null(계산하지 못함). **시험 단계 값이다** |
| `bonus_items` | `[{"name", "points"}]` — `points`는 공고 합계 한도 적용 **뒤** 실제 더한 점수, 합이 `bonus_score`와 같다. 계산하지 못하면 `[]` |
| `rules` | 이 공고에 걸린 재정렬 규칙(`groups`·`off_region`·`off_district`·`off_industry`·`pre_founder_implied_no`) |

출력 200 — 응답 최상위(조율 쪽이 쓰는 키): `results`, `count`, `has_more`, `offset`, `top`, `max_candidates`(20), `filtered_count`(정형 필터 통과 수), `fallback_used`(참·거짓), `fallback_mode`(null·`'임베딩단독'`·`'BM25단독'`·`'마감임박순'`), `search_errors`(오류가 난 검색별 `{where, error}`), `fit_basis`, `filter.excluded`(뺀 이유별 건수), `pipeline`.

- 필터 통과 0건이면 `results: []`, `pipeline: ['정형 필터']`.
- 오류: 입력 형식 422. 검색 실패는 오류가 아니라 대체 경로로 200을 준다.

## 4. `GET /api/notices/{notice_id}` — 공고 상세

| 키 | 뜻 |
|---|---|
| `notice_id`, `title`, `organizer`·`supervising_org`·`executing_org`(없으면 null), `source`, `url`·`apply_url`, `category` | |
| `apply_start`·`apply_end` | `YYYY-MM-DD` 또는 null |
| `apply_period_type` | `fixed`·`budget_exhaustion`·`rolling`·`until_filled`·`unknown` |
| `recruitment_status` | `open`·`closed`·`unknown`(그 밖 값은 `unknown`) |
| `support_amount_max_won` | 기업 1곳 최대 지원금(원, 양의 정수) 또는 null. 지원 금액은 일부 공고에만 있다(약 31%) |
| `support_amount_text` | 늘 null(원문 금액 표기를 따로 저장하지 않음) |
| `support_amount_evidence` | 금액 근거 문장(참고용) 또는 null |
| `bonus_info` | 가점 원문(가점을 찾은 공고만), 없거나 못 읽으면 null. K-Startup은 늘 null |
| `eligibility.applicant_types` | 신청 가능 유형 목록(세 유형 중 유형만으로 확실히 안 되는 것을 뺌) |
| `eligibility.business_age_max_months` | 업력 상한(개월) 또는 null |
| `eligibility.parsed` | 업력 칸을 읽었는지. **false면 상한 null은 "제한 없음"이 아니라 "모름"** |

오류: 404 `NOTICE_NOT_FOUND`.

## 5. `POST /api/notices/{notice_id}/eligibility` — 자격 판정

입력:

| 칸 | 형식 |
|---|---|
| `applicant_type` | `'예비창업자'`·`'개인사업자'`·`'법인'` (그 밖 422) |
| `founded_at` | `'YYYY-MM-DD'` 또는 `''` (그 밖 422) |
| `today` | `'YYYY-MM-DD'` 필수 — 업력 기준일 |

출력 200:

| 키 | 뜻 |
|---|---|
| `passed` | `지원대상 유형`·`업력` 두 조건에 확실한 미달이 없으면 true. **확인할 수 없는 조건은 통과로 본다** |
| `failed_conditions` | 확실한 미달 조건 이름 목록 (`'지원대상 유형'`·`'업력'`) |
| `unknown_conditions` | 확인할 수 없는 조건 이름 목록 |
| `business_age_months` | 사업자 업력(개월). 예비창업자·설립일 모름은 null |
| `details` | 참고용 `[{condition, verdict(true·false·null), need, note}]` |

- 접수기간·모집 상태는 판정하지 않는다(접수 시작 전 공고도 통과할 수 있다).
- 같은 공고·신청자면 추천의 정형 필터와 결론이 같다.
- 오류: 404 `NOTICE_NOT_FOUND`, 422 형식 오류.

## 6. 공용 DB (팀원이 읽는 테이블)

- 접속: 팀 MySQL `s_brain`, TLS(CA 검증). 읽기 전용으로 쓴다. 쓰기는 매일 배치만 한다.
- `notices`: 공고 1건 1행, 키 `notice_id`(`출처:원본ID`). `recruitment_status`는 API 값(K-Startup은 목록에서 빠지면 `closed`). `age_condition_raw`가 null이면 "제한 없음"이 아니다. 임베딩 칸(BGE-M3, 1024차원 정규화)이 들어 있다.
- `notice_attachments`(`active`가 지금 달린 첨부) · `attachment_texts`(추출 본문·파일 해시) · `attachment_files`(원본 바이트, 해시 기준 한 벌).
- `notice_conditions`: `amount_max_won`은 `amount_rejected IS NULL`인 행만 믿는다. 업력 상한 칸은 참고용이다.
- `notice_applicant_types` · `notice_industries` · `notice_bonus`: LLM 판정(AI 참고값). 판정 당시 문서 지문·추출기 버전 칸과 지금 공고를 대조해 쓴다.
- `import_runs`: 저장 1회 1행, `imported_at`(UTC)이 마지막 수집 시각.

## 7. 계약 변경

- 위 키·값·코드를 바꾸기 전에 조율 담당에게 보낼 문서를 먼저 고치고 알린다. 조율 쪽은 우리가 커밋·push한 코드를 기준으로 붙는다.
- 실제 연결을 켜기 전 조건: 가산점을 고치거나 `bonus_score`를 모두 null로 내보낸다, 공고 서버를 내부망에 배포한다.
- 조율 쪽 실제 연결 코드로 이 계약을 시험하는 스크립트가 `experiments/notice_api_contract.py`다(2026-10-06: 16개 확인 통과, 모든 공고 2,765건 자격 판정 형식 오류 0).
