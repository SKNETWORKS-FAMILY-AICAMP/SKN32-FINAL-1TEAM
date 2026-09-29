# 8건 재검수 + 저녁 변경 검수 (2026-09-28, Codex)

대상: [Claude 요청서](RECHECK_AND_EVENING_REVIEW_REQUEST_20260928.md)의 현재 작업 파일과 저장 결과. `data-collection/`만 검토했다. 코드·DB·Git 스테이징/커밋은 바꾸지 않았다. 아래의 “재현”은 로컬 파일 또는 순수 함수 기준이며, 실제 9/29 배치나 유료 API를 실행한 결과가 아니다.

## 결론

- 앞선 [검수 지적 8건](UNREVIEWED_CHANGES_REVIEW_20260928.md)은 **순차 실행과 현재 화면 경로 기준으로 수정 확인**했다. 특히 벡터 시작 장애와 보조 조회 500을 막는 경로, 공개 API 20건 제한, 단계 경고와 종료 코드 4를 코드에서 확인했다. 아래에 남은 동시 실행 조건은 별도 보완 사항이다.
- 저녁 변경은 **조건부 승인**이다. 새 업력 검사가 실제 업력을 되살리는 것은 확인했지만, 내일 배치에 적용되기 전에 아래의 혼합 근거 과잉 버림(P2)을 고치는 편이 안전하다. 업력 근거 파일의 서버 시작 오류(P1)와 자격 확인 표시 문제도 서비스 수정이 필요하다. 업종 final6은 파일 생성·건수·서비스 로더 해석까지 확인했으며 서비스 기본값 전환은 아직 별도 결정이다.

## 수정이 필요한 사항

### P1 · 선택 기능인 업력 근거 파일이 손상되면 서버 시작이 다시 멈춘다

[`search/app.py:150-159`](../../../search/app.py)의 첫 `age_evidence.load(connection)`이 실패하면 예외 절에서 `age_evidence.load(None)`을 다시 호출한다. [`age_evidence.load():50-64`](../../../search/age_evidence.py)는 두 호출 모두 동일한 최신 `results.jsonl`을 파싱하므로 파일의 JSON 한 줄이 손상된 경우 두 번째 예외가 밖으로 빠진다. 임시 JSONL에 `{broken`을 넣고 `load(None, rerun=...)`을 두 번 호출하니 모두 `JSONDecodeError`였다. 따라서 “업력 근거 읽기 실패해도 서버는 연다”는 보장은 DB 읽기 실패 중 **파일은 정상인 경우**에만 성립한다. 파일 실패도 격리하고 빈 근거 표와 `boot_errors.age_evidence`로 시작하도록 해야 한다. 실제 운영 파일이 손상됐다는 뜻은 아니다.

### P2 · 새 업력 검사가 업력과 거주 조건이 한 근거에 있으면 업력까지 버린다

[`collect/extract_conditions.py:163-204`](../../../collect/extract_conditions.py)의 `AGE_DECOY_STRONG`은 근거 **전체**에 `거주`·`주민등록` 등이 있는지만 본다. 저장된 [204건 재추출 결과](../../../reports/age_rerun_luna_20260928T054509Z/results.jsonl)의 `bizinfo:PBLN_000000000117511`은 “진안군에 주민등록을 두고 실제 거주하며, **1년 이상 해당사업을 운영 중인 소상공인**”에 대해 모델이 업력 하한 1년을 냈지만 `근무·경력·거주·의무 기간`으로 버렸다. 같은 형태가 `...120618`, `...125410`에도 있다. 독립 재현 문장 “창업 7년 이내이며 관내 거주 1년 이상인 기업”도 업력 상한 7년이 지워졌다. 기존 통과 147건에서 새로 떨어진 것이 0건이라는 검사는 **기존 결과에 대한 회귀**만 확인하며, 버려진 집합 속 이 과잉 버림을 잡지 못한다. 숫자가 어떤 구절에 붙는지 보거나, 혼합 문장은 `uncertain`으로 분리하는 편이 낫다.

### P2 · 업력 “미만”의 경계를 “범위 안”으로 잘못 안내한다

[`search/age_evidence.py:69-85`](../../../search/age_evidence.py)는 `age_years_max=10`이면 `years <= 10`으로 비교하고 “최대 10년”이라고 표시한다. 근거가 “창업 **10년 미만**”인데 신청자 업력이 정확히 10년이면 `내 업력 10년 0개월은 이 범위 안입니다(참고)`가 재현된다. 실제로는 경계 밖이다. 현재 판정은 `None`을 유지하므로 자동 통과 오류는 아니지만, 사용자가 바로 읽는 안내가 반대다. 추출 스키마에 `미만/이하`가 없으므로 원문 경계 해석을 추가하거나 경계에선 안/밖 비교를 생략해야 한다.

### P2 · 세부사업별 예비창업자 허용을 공고 전체의 업력 통과로 표시한다

[`search/applicant_types.py:121-135`](../../../search/applicant_types.py)의 `pre_founder()`는 `varies=True`여도 한 갈래에서 `allowed`면 `allowed`를 반환한다. [`search/app.py:809-821`](../../../search/app.py)는 이 값 하나로 업력 `None/False`를 `True`로 바꾸고 “업력 조건은 이미 창업한 기업에 붙는 조건”이라고 단정한다. 현재 유형 결과 2,476건에서 `varies=True`이면서 예비 `allowed`인 공고가 **23건**이다. 예를 들어 `bizinfo:PBLN_000000000126769`의 근거는 “예비창업자(**장인대학 운영사업에 한함**)”이다. 신청 세부사업을 고르지 않은 자격 확인 화면에서 이 공고 전체에 “업력 통과”를 표시할 근거는 부족하다. `varies`이면 해당 갈래를 확인 필요로 두거나, 허용 갈래와 적용 범위를 요구 칸에 명시해야 한다.

### P2 · 업력 재추출 재개는 같은 ID의 문서 변경을 검출하지 못한다

[`age_rerun.py:215-260`](../../../experiments/sql_semantic/age_rerun.py)의 재개 검사는 `notice_ids`와 `prompt_sha256`만 비교한다. `checkpoint.jsonl`에는 ID·모델 원답만 있고 원래 `document_sha256`이 없다. 중단 뒤 같은 ID의 공고문이 바뀌어도 저장된 옛 원답을 재사용하고, 결과 행에는 **새 문서 해시**를 붙인다. 모델·`missing`·`sample` 값도 `run_spec.json`에 기록하지만 재개 비교에는 쓰지 않는다. 이번 완성된 204건은 `old.same_document=True` 204/204로 확인했으므로 지금 파일이 오염됐다는 증거는 없다. 다음 재개 전에 문서 해시와 실행 조건을 체크포인트/사양에 묶어야 한다.

### P2 · 하루 호출 상한은 독립 실행 두 개가 동시에 돌면 초과할 수 있다

[`applicant_type_daily.py:123-164`](../../../collect/applicant_type_daily.py)는 날짜별 `attempted`를 읽고 남은 수를 계산한 뒤 상태 파일에 예약한다. 순차 재실행에 대한 원래 지적은 수정됐다. [`daily_pipeline.run()`](../../../collect/daily_pipeline.py)은 `job_lock`을 사용하지만 `python -m collect.applicant_type_daily` 진입점은 이 잠금을 사용하지 않는다. 독립 프로세스 두 개가 같은 `attempted=0`을 읽으면 각각 최대 300건을 골라 호출하고 상태 파일의 마지막 쓰기만 남을 수 있다. 날짜별 비용 상한을 절대 보장해야 한다면 11단계 자체의 프로세스 잠금 또는 원자적 예약이 필요하다. 동시 실행은 이번에 실제로 수행하지 않았다.

## 8건 재검수 결과

| 앞선 지적 | 현재 판정과 근거 |
|---|---|
| P1 서버 시작 벡터·임베딩 장애 | **수정 확인**: `boot()`가 벡터 DB·ID 조회와 임베딩 모델/워밍업 오류를 `boot_errors`로 격리하고, `match()`는 BM25 경로로 간다. DB 공고/BM25 자체 실패는 계속 시작 실패로 두는 설계다. 위 새 P1은 업력 파일 경로다. |
| P1 보조 벡터 조회 실패 500 | **수정 확인**: `_fill_distances()` 예외 시 RRF 순서를 보존하고 BM25 전용 결과에 거리 `None`을 준다. 순위는 하이브리드이므로 `fallback_mode=None` 판단은 맞다. 다만 `web/app.html:576-577`은 `fallback_used`만 보고 배너를 띄우므로 일부 유사도가 비어도 사용자에게 장애 안내가 없다(표시 개선 권고). |
| P2 11단계 실패를 정상 종료로 기록 | **수정 확인**: `stage_warnings_of()`가 10·11단계 오류/실패를 모으고, 수집이 `ok`이어도 CLI가 종료 코드 4를 낸다. `status=partial`로 바꾸면 [수집 상태 판정](../../../search/collection_status.py)이 매칭을 막으므로 분리한 판단은 타당하다. 순수 함수에 `error`·`failed`를 넣어 두 경고가 나옴을 확인했다. |
| P2 날짜별 300건 상한 | **순차 실행 수정 확인, 동시 실행 보완 필요**: 호출 전 `attempted` 저장 및 같은 해시 3회 실패 제한을 확인했다. 위 동시 실행 P2 참조. |
| P2 등록 사업자 규칙 | **수정 확인**: 서류 문장 제외와 “예비창업자 제외” 처리를 순수 함수로 확인했다. 현 결과 파일의 자동 추정은 **66건**이다. 66개 원문 판정의 사람 정답 여부까지 승인하는 의미는 아니다. |
| P2 공개 API 최대 20건 | **수정 확인**: `/api/match`·비교·리랭크 경로가 `_public()`에서 `top <= 20-offset`으로 제한된다. 내부 `match()`는 평가용으로 그대로다. FastAPI 서버 통합 호출은 이번 환경에서 하지 못했다. |
| P3 결과 파일 Git 무시 | **수정 확인**: `git check-ignore -v data-collection/data/applicant_types/results.jsonl`이 `.gitignore:27`을 가리킨다. |
| P3 적합도 퍼센트 표시 | **수정 확인**: `web/app.html`에 “순위 점수”와 확률이 아니라는 설명이 있다. 브라우저에서 새로 렌더링한 검증은 하지 않았다. |

## 업종·업력 결과와 화면

- [새 626건 결과](../../../reports/industry_llm_new626_luna_20260928/meta.json)는 626호출·실패 0으로 완료됐고, [final6](../../../reports/industry_llm_full_luna_20260928_final6/meta.json)은 **2,476행·새 624건 추가**다. `industry_rank.load(final6)`을 DB 없이 실행하니 2,476행 중 순위에 쓸 수 있는 공고 217건으로 읽혔다. 서비스 기본 경로는 여전히 final5이고, 업종 순위 스위치는 기본 꺼짐이다. 새 626건 중 54건은 6,000자 발췌에서 잘렸다. 따라서 final6 생성이 곧 업종 순위 품질 승인이나 서비스 전환은 아니다.
- `only_new()`는 현재 final6에서 보존된 원 실행 `source_run`을 따라 각 공고의 `max_chars`를 읽는다. **현재 합침에는 맞다.** 다만 [`merge_runs():1488-1492`](../../../experiments/sql_semantic/industry_llm_sample.py)는 향후 합친 폴더를 `override`로 다시 합칠 때 모든 덮은 행의 출처를 그 합친 폴더 이름으로 바꾼다. 그 폴더 meta에는 단일 `max_chars`가 없어 `only_new()`가 6,000자로 되돌아가며 18,000자 재독 행을 불필요하게 “변경”으로 잡을 수 있다. 다음 다단 합침 전 원 행의 `source_run`을 보존해야 한다.
- [final6 요약](../../../reports/industry_llm_full_luna_20260928_final6/summary.md)의 정규식 행 제목은 “lab_conditions”지만 `--source shared` 실행은 [`conditions.industry_condition()`](../../../experiments/sql_semantic/industry_llm_sample.py)을 즉석 계산한다. 숫자의 출처 설명만 잘못된 P3 문구다. 서비스 로더는 `results.jsonl`만 읽으므로 메타 합침 때문에 바로 깨지지 않는다.
- [업력 재추출 204건 meta](../../../reports/age_rerun_luna_20260928T054509Z/meta.json)의 살아남 77·업력 없음 85·다시 버림 42를 확인했다. 77건 중 우대·추천 자격이 업력으로 남은 예가 있다: `...117214`의 “설립연도 3년 미만 기업은 **추천가능**”이 `max=3`, `...117751`의 7년은 대출금리 감면 조건이다. B가 자동 판정을 `None`으로 둔 선택은 필요하다. 다만 “범위 안/밖”은 확인 필요 문구보다 판정처럼 읽힐 수 있으니 위 경계 문제와 함께 표현을 조정하는 편이 낫다.
- [`age_evidence.rerun_path()`](../../../search/age_evidence.py)의 `age_rerun_luna_2*` 필터는 지금의 missing 표본 폴더를 제외한다. 미래의 이름상 최신 폴더가 미완료/손상됐을 때 `meta.missing=false`, `failed=0`, 대상 문서 해시 등을 확인하지 않고 고른다는 한계는 남는다. 10단계 `EXTRACTOR_VERSION`을 유지한 것은 1,864건 재호출을 피하지만 기존 행의 규칙 세대는 구별할 수 없다. C-3에서 luna 결과를 DB에 반영할 때는 [`already_done()`](../../../collect/extract_conditions.py)의 버전/해시 재처리 조건도 함께 설계해야 한다.
- [`/flow`의 ③-1 표](../../../web/flow.html)는 `MatchRequest`, `build_query()`, `applicant.py`의 입력 사용처와 대체로 맞는다. `/api/flow`는 신청자 유형 파일 줄 수와 meta 시각만 읽고 모델/DB를 부르지 않는다. 다만 내부 분류기 시연 [`_rule_verdict()`](../../../search/app.py)는 새 `AGE_DECOY_STRONG` 검사를 빠뜨려 10단계와 서로 다른 판정을 보인다(P3 문구·시연 불일치).

## 검증 범위와 다음 순서

- 로컬 시스템 Python으로 `python -X utf8 -m unittest tests.test_extract_conditions_age tests.test_industry_llm_sample tests.test_applicant_type_daily`: **130개 통과**. 순수 함수·저장 JSONL·메타·Git 무시 규칙을 별도로 조회했다. 프로젝트 `.venv\Scripts\python.exe --version`은 삭제된 Python 3.12 경로를 가리켜 시작 실패했다. 따라서 Claude의 전체 **587개 통과(13개 건너뜀)**는 Claude의 기록이며 이번 독립 검증 결과가 아니다. FastAPI 통합 테스트/실제 화면/DB/LLM 호출은 수행하지 않았다.
- 9/29 배치 전에 **업력 파일 실패 격리(P1)**와 **혼합 근거 과잉 버림(P2)**을 고치고 가짜 파일·혼합 문장 테스트를 추가한다. 자격 확인의 “미만” 경계와 세부사업 표시를 바로잡는다. 이후 변경된 업력 프롬프트를 4o-mini로 소규모 무쓰기 실험해, 204건 중 실제 자격 업력의 회수와 추천·우대·금액표 오독을 함께 비교하는 것이 좋다. 현재 92건 회수 수치는 저장 근거에 **검사만** 적용한 값이지 새 프롬프트의 모델 성능은 아니다.
