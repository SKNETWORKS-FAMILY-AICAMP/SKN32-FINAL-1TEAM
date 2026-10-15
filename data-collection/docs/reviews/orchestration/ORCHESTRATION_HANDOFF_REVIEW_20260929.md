# 조율 에이전트 함수 설명서 · 9/29 배치 독립 검수 (2026-09-29)

검수: Codex. 대상은 [검수 요청](ORCHESTRATION_HANDOFF_REVIEW_REQUEST_20260929.md), [함수 설명서](../../archive/ORCHESTRATION_HANDOFF.md), 현재 공고팀 코드와 조율 브랜치 `origin/feature/SB-86-orchestration-flow` (`deb5c81`)다. **현재 예시 A·B·C와 9/29 배치 수치는 확인했다. 실제 조율 연결은 아래 P1이 해결되기 전에는 승인하지 않는다.** 코드·DB·설명서는 수정하지 않았고 공용 DB에는 SELECT만 했다.

## P1 — 연결 전에 해결할 것

### 1. Linux에서 `ec2/.env`만 두면 수집 상태 조회가 실패한다

- 설명서 1절 43행은 Linux 접속 정보가 `data-collection/ec2/.env` 또는 환경 변수에 있으면 된다고 한다. `app.boot()`의 공고 조회는 `search/app.py:57-61`의 `ec2_vecstore.connect()`를 써서 `ec2/.env`를 읽는다.
- 그러나 T-C2 예시의 `collection_status.check()`는 `search/collection_status.py:133-142`에서 **`shared.store_mysql.connect()`를 새로 호출**한다. 이 경로의 `shared/config.py:22-25`는 `shared/.env`와 `data-collection/.env`만 찾는다. `ec2/.env`만 있는 Linux 배치에서는 boot가 성공해도 T-C2가 DB 접속 정보 없음으로 실패할 수 있다.
- 수정 제안: 조율 프로세스에서 환경 변수를 공통으로 설정하거나, `app._connect()`로 얻은 연결을 `collection_status.check(connection=...)`에 넘기는 예시를 제공한다. EC2 실환경은 이번에 실행하지 않았다.

### 2. 합의 ⑩의 `app.eligibility()` 대체는 현재 G-01과 같은 결론이 아니다

- 설명서 4.3·8절 ⑩은 공고 ID만 `G01In`에 더하면 G-01이 `app.eligibility()` 호출로 끝난다고 권한다. 현재 7절의 `g01()`은 매칭의 `gate.prefilter`와 같이 **접수 시작 전 공고를 남긴다**. 반면 `app.eligibility()`는 `gate.judge()`의 접수기간 검사에서 시작일이 미래면 `passed=False`다.
- DB 없이 재현: `apply_start=오늘+3일`, `apply_end=오늘+20일`, `recruitment_status='open'`, 업력 정보 없음인 공고와 예비창업자 입력을 넣으면 `gate.prefilter()`는 `(True, [])`, `app.eligibility()`는 `passed=False`(접수기간 X)였다. 근거: `search/gate.py:226-250`, `search/gate.py:184-196`, `search/app.py:813-827`.
- `G01In.today`는 예시 `g01()`에서 쓰지만 `app.eligibility()`에는 날짜 인자가 없어 실행일을 사용한다. 실제 합의 시 접수 시작 전 공고를 선택하게 할지, 게이트에서 막을지 먼저 정하고 어댑터를 만든다. `JSONResponse` 404 검사와 `GateResult` 변환도 필요하므로 문자 그대로 한 줄 호출은 아니다.

### 3. 공고 공급의 실제 연결은 스텁 시험으로 검증되지 않았다

- `experiments/orchestration_probe.py:check_flow()`는 조율 쪽 `make_announcement()`의 **양식·평가 항목·기간·금액·벡터 임시값**을 가져오고 제목과 자격만 실제 공고 값으로 바꾼다. 따라서 C 통과는 실제 `announcements(id) -> Announcement` 구현 검증이 아니다.
- 조율 `sbrain/models/domain.py:156-170`은 `apply_start`, `apply_end`, `support_amount_max`, `form_spec`, `evaluation_items`, `summary_embedding`을 필수로 요구한다. 공고팀 메모리 행에는 양식·평가 항목·금액이 없고, 마감일 없는 공고는 **985/2,525건**이다. 설명서 8절 ①~③에 현황은 적었으나 합의 없이 실제 객체를 만들 수 없다. 조율 흐름은 `form_spec`·`evaluation_items`를 후속 Task에 사용한다(`sbrain/flow/catalog.py:78,95,148`).
- 특히 ①의 `apply_end=None` 제안만 적용하면 `sbrain/flow/service.py:259`의 `ann.apply_end < 오늘`에서 예외가 난다. 카드에 쓰는 `9999-12-31` 임시값은 실제 마감 판정을 대신하지 않는다. 모델·흐름·표시 규칙을 함께 정해야 한다.

### 4. “모름·입력 누락 = 통과”가 확인 필요 정보를 지운다 (사용자 결정의 운영 위험)

- 설명서 7절 `g01()`은 확실한 미달이 없으면 `passed=True, undecidable=False, missing_inputs=[]`를 반환한다. 원래 `app.eligibility()`의 `unknown`/`checks`는 `GateResult`에 없다. 조율 `sbrain/flow/sbrain_flow.py:198-207`은 이 세 값만 보고 즉시 **계획서작성**으로 보낸다. E-G1-UNPARSED·E-G1-MISSING 안내도 발생하지 않는다.
- 업력·지원대상 정보가 없거나 해석되지 않은 공고, 설립일 없는 사업자, 마감 정보가 없고 모집 상태도 모르는 공고가 실제 신청 가능 여부를 확인하지 못한 채 작성 단계에 간다. 9/29 DB 기준 모집 상태 모름은 **2,086건**, 마감일 없음은 **985건**이다. 실제 불가 공고의 수는 사람 원문 판정 없이 셀 수 없다.
- 사용자 결정을 바꾸라는 뜻은 아니다. 8절 ⑦의 `unknown_conditions` 제안은 **조율 화면/후속 작성 단계가 그 값을 보존·표시한다는 합의와 함께** 확정해야 충분하다. `passed=True`만 전달하면 확인 필요를 복원할 수 없다.

## P2 — 설명·운영 조건을 보완할 것

1. **벡터 장애와 공고 공급**: 2절은 Chroma가 열리지 않아도 BM25로 추천한다고 설명한다. 그러나 6절은 `app.STATE['collection'].get(..., include=['embeddings'])`로 필수 `summary_embedding`을 꺼내라고 한다. `boot()`의 벡터 장애 경로에서는 `STATE['collection']=None`(`search/app.py:112-125`)이므로 실제 공급 함수는 여기서 실패한다. 벡터가 없을 때의 `Announcement` 계약 또는 대체값을 합의해야 한다.
2. **신청자 입력 누락**: 7절 `tc2()`는 `CompanyInfo.industry_code`·`hiring_plan`을 `MatchRequest.main_industry`·`hiring_plan`으로 옮기지 않는다. 공고팀은 업종 *이름*으로 검색하고 업종 코드만 받은 경우는 현재 변환할 수 없으며 업종 감점도 기본 꺼짐이다. 조율 개발자에게 이 제한을 명시하고 코드→이름 매핑 책임을 정한다. `TC2In.today`도 무시되고 `app.match()`는 `date.today()`를 사용하므로 재실행·날짜 경계에서 결과가 달라질 수 있다.
3. **직접 호출의 경계**: `app.match()` 직접 호출은 HTTP의 `_public()` 20건 상한을 거치지 않는다(`search/app.py:340-350,372-374`). 예시는 `top_k=10`, `offset=0|10`에서 `TC2Out.candidates` 최대 10과 `AnnouncementCard.rank` 1~20을 만족했다. 조율 쪽 입력 제한이 바뀌면 어댑터에서 `top_k<=10`, `offset∈{0,10}`을 검증해야 한다.
4. **재부팅·동시 요청**: worker 1개여도 여러 스레드가 있을 수 있다. `boot()`는 `STATE`를 단계별로 덮고, `match()`는 여러 단계에서 읽는다. 재부팅 중 요청의 일관성·Chroma 동시 조회 안전성은 확인하지 않았다. 09:20 재시작 권고와 함께 요청 배수·드레인 또는 새 프로세스 교체 방식을 문서화한다.
5. **이미 알려진 시작 실패**: 2절의 “벡터 DB가 고장 나도 켜진다”는 벡터 장애 범위에서는 맞다. 그러나 [9/28 재검수](../integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md)의 손상된 신청자 유형 파일은 정상 DB가 있어도 `boot()`를 중단시킬 수 있다. 멈춘 P1이 해결되기 전까지 일반적인 “서버 시작 안전” 보증으로 읽히지 않게 주의를 붙인다.

## P3 — 문구와 전달 상태

- 4.3절의 “합의 ⑩(6절)”은 **8절**이다. 3.1절 “받아만 두고 결과에 영향이 없는 칸”은 추천 순위에는 영향이 없지만 `stored_only` 진단 응답은 바뀌므로 범위를 명확히 한다.
- 사용자 의견대로 맨 앞은 최소 호출 예시(`boot` → 상태 → `match` → ID 조회/게이트)와 **P1 합의 필요 항목**을 먼저 두는 편이 연결 담당자가 읽기 쉽다. 상세 입력·출력 표와 10건 합의는 뒤에 둔다.
- 요청서 0절의 “오늘 바꾼 파일 모두 미커밋”은 현재 Git 상태와 다르다. 함수 설명서는 `aac4093`에 이미 포함됐고, 검수 요청서·검증 스크립트 및 STATUS/WORKLOG/문서 지도 수정은 미커밋이다. 검수 중 기존 상태를 바꾸지 않았다.

## 9/29 배치 점검 재확인

| 항목 | 독립 확인 |
|---|---|
| 배치 | `data/run.log` 마지막 행 `exit=0`. `data/collect_log.jsonl` 마지막 행 `status=ok`, `stage_warnings=[]`, `degraded=[]`, 723.3초. 11·12단계 각각 추출 50·실패/미룸/포기 0, 13단계 각 신규 49·변경 1·올림 50·오류 null. |
| DB·파일 | 공용 DB SELECT에서 `notices`·두 판정표 각각 2,525행/고유 ID 2,525. 로컬 두 파일과 `upload_judgments --plan` 재대조: 두 표 각각 같음 2,525, 신규·변경·공고 없음 0. 마감 없음 985(예산 소진 678·상시 149·선착순 94·정보 없음 64), 모집 상태 모름 2,086, 금액 있는 공고 787. |
| 업력 오류 후보 | DB SELECT에서 `bizinfo:PBLN_000000000126783`의 `age_years_min=5`, `age_years_max=5`, 근거 “5년 이상 영업”을 확인했다. 상한 5는 근거와 어긋난다. |
| 서비스 | 읽기 전용 `orchestration_probe`의 `app.boot()`가 공고 2,525건, 신청자 유형 DB 2,525건, 업종 파일 final5 순위 신호 174건을 읽고 A·B·C를 통과했다. `refreshed_from_file=0`이나 이 결과만으로 판정 신선도가 증명되지는 않는다. |

## 검증 범위와 다음 단계

- 검증 스크립트: 번들 Python 3.12 + 기존 `.venv` 패키지로 A(offset 0·10 각 10건), B(2,525건 × 5가지 입력 모두 차이 0), C(스텁 공고로 계획서작성 진입) 통과. `.venv` 실행 파일은 원래 Python 경로가 사라져 직접 실행하지 못했다. 조율 코드는 로컬 원격 추적 ref `deb5c81`에서 임시 폴더로 읽었다. 유료 API 호출과 DB 쓰기는 없었다.
- **미검증**: Linux 실배포, 실제 `Announcement` 공급 및 양식·평가 항목, 재부팅 중 요청, 동시 요청, G-01의 추가 입력 조합 전체, 사람 기준 신청 가능 여부. 전체 unittest는 서비스 코드를 바꾸지 않아 재실행하지 않았다.
- Claude가 P1의 설명·계약 제안을 보완하고 조율 담당과 필수 필드/확인 필요 표시를 합의한 뒤, 실제 공고 공급을 넣은 통합 시험을 다시 한다. 멈춘 신청자 유형 판정표 P1은 별도 사용자 지시 전까지 수정하지 않는다.
