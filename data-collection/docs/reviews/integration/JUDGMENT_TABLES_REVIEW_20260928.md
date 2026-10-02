# 공고 판정 테이블·12·13단계·업력 반영 검수 (2026-09-28)

검수: Codex · 기준: [Claude 요청서](JUDGMENT_TABLES_REVIEW_REQUEST_20260928.md) · 범위: `data-collection/`만. **조건부 승인**이다. 현재 저장된 두 판정표와 결과 파일은 일치하지만, 다음 배치에서 업로드가 일부만 끝나거나 실패하면 서비스가 오래되거나 불완전한 DB 판정을 우선 사용할 수 있다. 아래 P1을 해결하고 배치 후 재확인하는 편이 안전하다. 코드·DB 수정, API 호출, Git 스테이징·커밋은 하지 않았다.

## 확인한 사실

| 항목 | 독립 확인 결과 |
|---|---|
| 테이블 | 공용 DB에서 `notice_applicant_types`, `notice_industries` 각 **2,476행**, 각 21열, `utf8mb4_bin`, `notices.notice_id` 외래 키와 `ON DELETE CASCADE` 확인. 고아 행 0건. `information_schema` 및 SELECT만 사용했다. |
| 신청자 유형 | `pre_founder_verdict`: blocked 183, allowed 289, implied_no 1,701, NULL 303. `varies=1`인 allowed **23건**, implied_no 33건, NULL 22건. blocked와 varies가 함께 있는 행은 0건. |
| 업종 | `known` 830(순위 사용 217), `not_mentioned` 1,088, `excluded_only` 287, `unknown` 240, `conditional` 26, `no_limit` 5. `allowed_sections`가 있지만 `usable_for_rank=0`인 행 **200건**. |
| DB ↔ 파일 | 현재 `data/applicant_types/results.jsonl`과 `data/industries/results.jsonl`을 행으로 다시 만들어 DB 값과 전체 열 비교. 양쪽 모두 2,476행 중 같음 2,476, 신규·변경·공고 없음 0. 읽기 전용 대조이며 `upload_judgments.run()`은 실행하지 않았다. |
| 업력 C-3 | `notice_conditions` 1,864행 중 업력 값 225행, `age_rejected` 비NULL 155행. `uncertain`의 `업력 출처:` 메모 **78행**은 모두 `extract_conditions/1.0 gpt-4o-mini` 버전이다. 백업 `reports/age_rerun_luna_20260928T054509Z/applied_backup_20260928T074751Z.jsonl`은 고유 78행이며 현재 DB의 78행과 문서 해시·버전이 전부 같다. 현재 업력 검사로 225행을 확인하면 4행(`117214`, `117634`, `117751`, `123754`)이 숨겨져 표시 가능 221행이다. |
| 테스트 | 현재 시스템 Python에서 DB 접속 없이 실행 가능한 요청 범위의 표적 테스트 **151개 통과**. `test_extract_conditions_age.VerifyAgeTests.test_classify_demo_uses_same_check`는 FastAPI 의존성 때문에 제외했다. 전체 테스트는 실행을 시도했으나 현재 Python과 `.venv`의 `pydantic_core` 바이너리가 맞지 않아 **289개 중 import 오류 17, 건너뜀 13**이었다. Claude의 614개 통과 기록을 이번 검수 결과로 취급하지 않는다. |

## 우선 수정할 사항

### P1 · DB 일부 업로드/오래된 행을 정상 판정으로 받아들임

`collect/upload_judgments.py`의 `upsert()`는 200행마다 커밋하고 유형 표 다음에 업종 표를 올린다. 중간 실패 후 재실행하면 바뀐 행을 이어 올릴 수 있는 구조는 맞다. 그러나 `run()`은 파일에서 빠진 ID를 DB에서 지우지 않고, 서비스 `search/applicant_types.py::load_auto()`는 **DB에 한 행만 있어도** 파일 전체 대신 DB를 택한다. `search/industry_rank.py::load_auto()`도 `auto` 전환 시 같다. 새 수집 공고가 바뀌었거나 11단계 성공·13단계 실패 후 서버가 시작되면, 예전 `blocked` 판정으로 신청 가능한 공고를 뺄 수 있다. `stage_warnings`와 종료 코드 4는 배치를 알려 주지만 서비스의 DB 우선 읽기를 막지 않는다. 반대로 첫 업로드 중 200행만 성공하면 나머지 파일 판정을 서비스가 잃는다. **현재 DB와 파일은 전량 일치하므로 현재 발생한 불일치는 아니다.**

권고: 업로드 완료 세대/건수와 소스 해시를 게시해 서비스가 완전한 세대만 채택하게 하거나, 공고별 현재 문서 해시와 판정 해시를 대조해 불일치 행을 보수적으로 무효화한다. 파일 누락을 허용할지 명시하고 예상 모집단·행 수가 급감하면 업로드를 중단한다. 배치 완료 후 서비스 재시작/갱신도 운영 절차에 넣는다. `search/app.py::boot()`는 시작 시 한 번만 읽으므로 DB가 갱신되어도 실행 중 서버의 판정은 그대로다.

### P2 · `allowed`와 업종 대분류의 사용 범위가 실제 행보다 넓게 읽힘

`docs/guides/JUDGMENT_TABLES.md` 3절은 `pre_founder_verdict='allowed'`를 “신청 가능”이라고 안내하지만, 실제 DB의 **23행은 `varies=1`**이다. 서비스는 `type_check()`와 `eligibility()`에서 세부사업별 확인 필요로 다루므로 SQL 사용자에게 `allowed` 단독 사용을 안내하면 서비스와 다른 결론이 된다. `blocked`는 현재 `varies=1` 행이 없어 제외 예시가 안전하다. `notice_industries.allowed_sections`는 **200행에서 `usable_for_rank=0`인데도 값이 있다**. 단독 비교 또는 제외 기준으로 쓰지 않도록 SQL 예시·COMMENT에 `varies=0`, `usable_for_rank=1`과 “업종은 제외에 쓰지 않음”을 더 분명히 적어야 한다.

### P2 · 계산된 결론의 규칙 버전과 DB/서비스 의미가 분리됨

`pre_founder_verdict`, `registered_only_phrase`, `allowed_sections`, `usable_for_rank`는 업로드 시점 코드로 계산된다. `extractor_version`은 모델/프롬프트만 표시하고 **판정 규칙 버전**은 없다. `search/applicant_types.py::load_db()`는 DB의 `pre_founder_verdict`와 `registered_only_phrase`를 읽지 않고 현재 코드로 재계산하지만, `search/industry_rank.py::load_db()`는 저장된 `usable_for_rank`와 `allowed_sections`를 그대로 쓴다. 코드만 배포하거나 13단계가 실패하면 SQL 사용자·신청자 유형 서비스·업종 서비스가 서로 다른 규칙 시점의 값을 볼 수 있다. 규칙 버전/계산 시각을 별도로 남기고, DB 재계산 완료를 배포/전환 조건으로 삼는 것이 좋다.

### P2 · 강제 `db` 모드에서 연결 자체가 실패하면 파일로 조용히 전환됨

두 `load_auto()` 모두 `if mode == 'file' or connection is None: return load(path)` 순서다. `APPLICANT_TYPES_SOURCE=db` 또는 `INDUSTRY_SOURCE=db`를 지정해도 `boot()`의 DB 연결이 실패하면 파일 경로를 쓴다. DB SELECT가 실패한 경우에는 `db` 모드 오류를 돌려주는데, 연결 실패는 다르게 처리된다. 강제 모드의 의미와 장애 표시를 일치시켜야 한다. 기본 `auto`의 파일 대체 자체는 의도대로다.

## 요청 항목별 판정과 보완

| 항목 | 판정·근거 |
|---|---|
| 재검수 P2: 혼합 업력 근거 | **수정 확인, 보수적 오탐 가능.** `AGE_BENEFIT`, 깨끗한 절·숫자 대조가 거주 기간/금리/지원금 숫자 혼동을 막는다. 순수 함수 반례에서 “지원대상: 창업 3년 이내 기업, 매출액 80백만 원 미만”은 통과하고, “신청자격: 창업 3년 이내 기업에 최대 1억원 지원”은 같은 절의 지원금 때문에 업력까지 버린다. 후자는 안전한 확인 필요 처리지만 정보 손실이므로 실제 표본에서 빈도를 관찰하고 절 분리를 보완할 수 있다. 섞이지 않은 근거에 숫자 대조를 생략한 것은 개월 환산 회귀를 피하는 합리적 선택이다. |
| 재검수 P2: 세부사업 업력 | **수정 확인.** `search/app.py::eligibility()`에서 `pre_partial` 처리가 이미 True인 업력 판정보다 앞에 있다. 세부사업별 예비 허용일 때 업력을 확인 필요로 돌린다. |
| 재검수 P2: 업력 근거 DB 우선 | **수정 확인, 경계 1건.** DB 업력이 있으면 재추출 파일이 덮지 않고, DB 값에도 현재 검사를 적용해 4행을 숨긴다. DB에 행은 있으나 업력이 없으면 `input_sha256`을 대조한다. 다만 DB를 정상 조회했는데 `notice_conditions`가 완전히 비어 `db_sha={}`가 되면 파일의 문서 해시를 확인할 DB 값이 없어도 파일을 받아들인다(`if db_sha and ...`). 새/빈 DB 환경에서는 파일의 신선도를 보장할 수 없으므로 이 경우를 명시적으로 처리하는 편이 좋다. |
| 테이블·외래 키 | **구조 확인.** 각 21열, PK/FK CASCADE와 현재 고아 행 0. 허용 값의 DB `CHECK` 제약은 없어 코드가 계약을 지키는 구조다. `pre_founder_verdict='blocked'`만 제외용이고 나머지는 순위/참고라는 구분은 기본적으로 쓰였으나 위의 `varies`와 업종 사용 범위를 보완해야 한다. |
| 13단계 비교·실패 | **현재 데이터 대조 통과.** JSON 문자열을 파싱하고 bool을 0/1로 맞추어 MySQL 실제 행과 2,476건씩 동일했다. JSON 객체 키 순서는 파싱 후 비교하므로 영향이 없다. `NULL`과 빈 배열은 같게 보지 않지만 행 생성에서 빈 `allowed`/`excluded`를 `NULL`로 만들며 현재 재업로드는 0건이다. 200행 커밋/파일 누락 위험은 P1. 전체 표를 매일 메모리에 읽는 비용은 현 2,476행에서는 문제를 재현하지 못했으며 규모 증가 시 시간·메모리를 계측하면 된다. 공고가 없는 파일 행은 세어 건너뛴다. |
| 12단계 업종 | **현 로직 수용.** `only_new()`가 원 실행의 18,000자 상한으로 해시를 다시 만들고 뒤의 동일 해시 필터는 중복 안전망이다. 6,000자에서 잘린 공고를 매일 자동으로 18,000자로 재추출하지 않는 정책은 `truncated`/순위 사용 불가와 일치한다. 체크포인트는 문서·프롬프트 해시를 검사한다. 다만 향후 모델/스키마 변경 시 이전 체크포인트를 재사용할 수 있으므로 그 키도 포함해야 한다. 상한 300·같은 문서 3회 실패·잠금은 코드와 표적 테스트에서 확인했다. 유료 호출은 하지 않았다. |
| 업력 C-3 | **78행 반영 사실 확인, 출처·복구 절차 보완 필요.** 실제 DB·백업의 ID/해시/버전은 모두 맞는다. 한 행의 다른 조건은 4o-mini, 업력은 luna인데 `extractor_version`은 4o-mini이므로 `uncertain` 메모를 읽지 않는 소비자는 출처를 오해한다. 백업은 있으나 문서화된 원복 절차/새 문서 덮어쓰기 방지 조건이 없다. `apply_to_db()`는 `executemany()` 후 실제 `rowcount`를 확인하지 않고 계획 수를 반영 수로 보고한다. 동시 문서 변경 시 `WHERE input_sha256`이 막은 행도 성공으로 셀 수 있다. 이번 78행은 현재 해시가 전부 같아 그런 불일치 증거는 없다. |

## 전환·문구에 대한 의견

- 업종 `INDUSTRY_SOURCE=auto` 전환은 **지금 승인하지 않는다.** DB의 217 순위 행은 파일과 일치하지만 이전 검수에서 사람 기준 부당 밀림 11/34가 남았고, 이번 범위에서는 그 문제를 해결하지 않았다. 서비스 기본은 final5 파일이며 DB는 final6 기반이다. 전환 전에 사람 검수 기준과 P1 신선도 보호를 확인해야 한다.
- 업력 재추출 파일 읽기는 당장은 유지하되 파일 행이 실제로 보충한 수를 계측하자. 현재 DB가 225행을 가지며 75건을 건너뛰지만, 파일은 DB에 업력이 없는 같은 문서의 보충 경로다. 완전 제거는 그 보충이 0인지 확인한 뒤 결정하면 된다.
- `docs/guides/JUDGMENT_TABLES.md`의 “기존 테이블은 건드리지 않는다”는 **스키마** 한정으로 쓰는 편이 정확하다. C-3는 기존 `notice_conditions` 데이터 78행을 UPDATE했다. “서비스가 공용 DB를 먼저 읽는다”, “결과 파일 없는 곳에서도 같은 판정”도 신청자 유형에만 기본 적용된다. 업종 기본은 final5 파일이고 파일이 없는 호스트에서는 순위가 꺼진다. `web/flow.html`의 “DB에서 읽음”도 이 구분을 반영해야 한다. `web/collection_status.html`의 12·13단계 이름은 코드의 실제 순서와 일치하는지 화면에서 재확인할 필요가 있다. 이번 환경에서는 화면을 띄우지 않았다.

## 재검수 조건

1. P1: 업로드 중단/파일 누락/문서 갱신을 가짜 DB로 재현해, 서비스가 불완전하거나 오래된 `blocked`를 사용하지 않는지 확인한다.
2. P2: `varies=1`의 allowed와 업종 `usable_for_rank=0`의 `allowed_sections`를 SQL 사용자에게 오해 없이 설명하고, 계산 규칙 버전·서비스 읽기 방식을 일치시킨다.
3. 9/29 배치 후 두 표의 행 수·파일 대조·stage_warnings·서비스 재시작 여부를 확인한다. 업종 DB 전환은 별도의 사람 판정 결과가 나온 뒤 결정한다.
