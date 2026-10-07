# Codex 검수 요청 — 조율 에이전트용 함수 설명서 · 9/29 배치 점검 (2026-09-29)

작성: Claude · 요청: 사용자(이근준) · 수행: Codex

- 결과는 이 폴더에 `ORCHESTRATION_HANDOFF_REVIEW_20260929.md`로 남겨 달라.
- **코드·DB는 고치지 않는다.** Git 스테이징·커밋도 하지 않는다. 공용 DB는 **SELECT만** 한다. 유료 API 호출은 없다.
- 고칠 것이 있으면 결과 문서에 적는다. 수정은 Claude가 한다.

## 0. 먼저 알아 둘 것

### 상황

- 다른 팀원(4nchez)이 만든 **조율 에이전트**에 공고팀 기능을 연결하는 중이다.
  - 조율 에이전트 위치: 브랜치 `origin/feature/SB-86-orchestration-flow`, 커밋 `deb5c81`, 폴더 `agent-orchestration/`.
  - 조율 담당자는 **우리 브랜치를 다른 브랜치로 머지해서** 작업한다(사용자 전달, 2026-09-29).
- 공고팀 몫은 조율 규격의 부품 세 개다.
  - **T-C2 공고 매칭**
  - **G-01 자격요건 게이트**
  - **공고 공급** `announcements(id) -> Announcement`
  - 규격: 조율 쪽 `agent-orchestration/docs/Agent_연동_규격_초안.md`, `sbrain/contracts/tasks.py`, `sbrain/models/domain.py`
- 조율 코드는 우리 브랜치에 없다. 읽으려면 아래처럼 꺼낸다(작업 트리는 바뀌지 않는다).
  ```powershell
  git fetch origin
  git archive origin/feature/SB-86-orchestration-flow agent-orchestration | tar -x -C <임시 폴더>
  ```

### 사용자 결정 (2026-09-29)

| 결정 | 내용 |
|---|---|
| 연결 방식 | **코드 직접 호출.** 조율 프로세스가 `search.app.boot()`를 한 번 부르고, 이후 `app.match()` 등을 부른다. 공고팀 서버(8000)는 따로 켜지 않는다 |
| 공고팀 역할 | **코드를 조율 쪽에 끼우지 않고 설명서만 전달한다.** 연결 코드는 조율 담당이 쓴다 |
| G-01 판정 불가 | **통과.** 조율 흐름은 `undecidable=True`이면 계획서 작성을 막는다. 그대로 두면 조건 정보가 적은 기업마당 공고 대부분이 막힌다 |
| G-01 입력 누락 | **통과.** 예: 설립일 없는 사업자. `missing_inputs=[]`로 둔다 |

### 멈춰 둔 작업 — 이번 범위 아님

- [판정 테이블 재검수](../integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md)의 P1 세 건은 **수정 착수 전에 사용자 요청으로 멈췄다.**
  - 옛 파일이 DB를 `blocked`로 덮는 문제
  - 손상 파일이 서버 시작을 막는 문제
  - 파일 없는 호스트가 오래된 `blocked`를 쓰는 문제
- 코드는 그 재검수 때와 같다.

### 오늘 바꾼 파일 (모두 미커밋)

| 파일 | 무엇 |
|---|---|
| [docs/guides/ORCHESTRATION_HANDOFF.md](../../archive/ORCHESTRATION_HANDOFF.md) | **신규 — 이번 검수 대상.** 조율 개발자에게 줄 함수 설명서 |
| [experiments/orchestration_probe.py](../../../experiments/orchestration_probe.py) | **신규.** 설명서 7절 코드 블록을 그대로 꺼내 A·B·C(3절)를 확인한다. 읽기 전용 |
| `docs/STATUS.md`, `docs/WORKLOG.md`, `docs/README.md` | 기록 |

서비스 코드(`search/`, `collect/`, `shared/`)는 **오늘 바꾸지 않았다.**

## 1. 우선순위 높음 — 함수 설명서 검수

대상: [ORCHESTRATION_HANDOFF.md](../../archive/ORCHESTRATION_HANDOFF.md). 조율 개발자가 이 문서만 보고 연결한다. **틀린 설명이 곧 연결 버그가 된다.**

### 1-1. 설명이 코드와 맞는가

| 확인할 것 | 설명서 위치 | 코드 |
|---|---|---|
| 함수 5개의 파일·줄 번호·부르는 법 | 0절 표, 2~6절 머리 | `search/app.py` `boot`(108) · `MatchRequest`(279) · `GateRequest`(333) · `match`(372) · `eligibility`(813) · `FIELDS`(47), `search/collection_status.py` `check`(133) |
| `MatchRequest` 칸 분류가 맞는지: 꼭 넣을 칸 / 결과가 좋아지는 칸 / 받아만 두는 칸 / 건드리지 말 칸. 특히 "받아만 두는 칸"이 정말 결과에 영향이 없는지 | 3.1 | `search/applicant.py` `rule_words`·`query_extras`·`stored_only`, `app.build_query`, `search/rank_rules.py` |
| `match()` 출력 키 설명, "주로 쓸 값"과 "진단용" 구분 | 3.2 | `app.match` 끝부분 |
| **예외 동작 주장**: ① `boot()`는 벡터 DB 장애에는 예외 없이 켜지고, 공용 DB 장애에는 예외를 낸다 ② `match()`는 검색이 고장 나도 예외 없이 대체 결과를 준다 ③ 통과 공고 0건이면 `results=[]` ④ `eligibility()`는 없는 ID면 예외 대신 `JSONResponse`(404)를 돌려준다 ⑤ `STATE['rows']`는 없는 ID면 `KeyError` | 2절, 3.3, 4.3, 6절 | 각 함수 |
| 날짜 타입: `match()` 결과는 문자열(없으면 `''`), `STATE['rows']`는 `datetime.date` 또는 None | 3.2, 6절 | `app.match`, `boot` |
| `collection_status.check()`는 부를 때마다 SELECT 1회만 하고, `status` 값이 조율 쪽 `CollectionStatus`와 같다 | 5절 | `search/collection_status.py` |
| 준비물: Windows와 Linux의 경로·접속 정보 차이 | 1절 | `app._connect`·`_collection`(`ON_EC2`), `ec2/ec2_vecstore.py`, `shared/store_mysql.py` |

### 1-2. G-01 규칙이 매칭 1단계와 같은가

- 설명서 7절의 `eligibility_of()`(공고 → `EligibilityRule`)와 `g01()`을 매칭 1단계 `app.eligible_with_types(…, check_deadline=False)`와 대조했다.
  - 공고 2,525건 × 신청자 5가지 경우에서 **전부 같았다**(3절 B).
  - 5가지 경우: 예비창업자 / 개인사업자 2025-03 설립 / 법인 2019-01 설립 / 법인 2024-12 설립 / 개인사업자 설립일 없음.
- **5가지 밖의 반례를 찾아 달라.** 후보는 다음과 같다.
  - K-Startup 업력 칸이 "예비창업자"만 있는 공고 + 설립일 있는 사업자
  - `varies=1`이면서 `allowed`인 공고
  - 본문 `allowed`로 되살린 공고(`restored`)
  - 업력 칸이 해석 불가인 공고(`understood=False`인데 값이 있음)
  - 업력 상한 경계(정확히 N년 = N×12개월)
- `app.eligibility()`(4절, 화면용)와 `eligible_with_types`(매칭용)의 `passed`가 같은 기준인지 확인해 달라.
  - `eligibility()`는 접수기간·모집 상태도 보고, 개인사업자·법인 줄은 자동 판정하지 않는다.
  - 설명서는 합의 ⑩이 되면 G-01을 `app.eligibility()` 한 줄로 바꾸라고 권한다. 그 권고가 매칭 결과와 어긋나지 않는지 봐 달라.

### 1-3. "모름·입력 누락 = 통과" 결정의 위험

- 결정 자체는 사용자가 정했다. **바꾸라는 요청이 아니라 위험을 알려 달라는 요청이다.**
- 이 결정으로 조율 흐름에서 "계획서 작성"까지 가게 되는 경우가 어떤 것인지 정리해 달라.
  - 특히 실제로는 신청할 수 없는데 통과되는 유형이 있는지 본다.
  - 조율 쪽 안내 문구가 사라지는 문제도 포함한다: `E-G1-UNPARSED`·`E-G1-MISSING`이 더는 나오지 않는다.
- 설명서 8절 ⑦(확인 필요 칸 추가 제안)이 충분한지도 봐 달라.

### 1-4. 합의 요청 10건(8절)

- 수치를 SELECT로 다시 세어 달라.
  - 마감일 없음 985건과 그 분포(678·149·94·64)
  - 금액 있는 공고 787건
  - 모집 상태 모름 2,086건
- 조율 쪽 모델(`AnnouncementCard`·`Announcement`·`EligibilityRule`·`GateResult`·`TC2In/Out`·`G01In/Out`)과 대조해, **설명서가 놓친 불일치**가 있는지 봐 달라.
  - 예: 필드 제약 `rank` 1~20, `fit_score` 0~1, `candidates` 최대 10건
  - 예: `Announcement.summary_embedding` 크기
- 조율 흐름(`sbrain/flow/service.py`·`sbrain_flow.py`)에서 T-C2 결과를 쓰는 곳도 본다.
  - 수집 상태 "정상"이 아니면 시작을 막는다.
  - 후보 0건이면 `E-C2-NOMATCH`, 대체 검색을 쓰면 `E-C2-EMBED`를 낸다.
  - 설명서 3.2의 값 의미와 맞는지 확인한다.

### 1-5. 운영 주의(2절)가 충분한가

- 측정값: `boot()` 16~22초, 메모리 약 2.1GB, `match()` 0.25~0.32초. 모두 공고팀 PC 기준이다.
- 설명서가 권하는 것: worker 1개, 매일 09:20 이후 재시작.
- 아래는 **확인하지 않았다.**
  - `boot()`를 다시 부르는 동안 들어온 요청이 안전한지
  - 여러 스레드에서 `match()`를 동시에 불러도 안전한지(조율 엔진 T-P2는 병렬로 돈다)
  - Linux(EC2) 경로
- 코드로 알 수 있는 범위에서 위험을 적어 달라.

### 1-6. 읽기 쉬운가

- 사용자 의견: "처음 부분이 복잡하다."
- Claude 제안: 맨 앞을 코드 몇 줄로 시작하고, 머리 표·흐름도·준비물은 뒤로 보낸다. 아직 반영하지 않았다.
- 조율 개발자 입장에서 순서·분량·빠진 설명에 대한 의견을 달라. 고치는 것은 Claude가 한다.

## 2. 우선순위 보통 — 9/29 배치 점검 결과 확인

[판정 테이블 재검수](../integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md) 3절의 점검표를 Claude가 오늘 실행했다(상세는 [WORKLOG](../../WORKLOG.md) "9/29 매일 배치 결과 점검"). 독립적으로 다시 확인해 달라.

| 점검 | Claude 결과 (2026-09-29 09:12 배치) |
|---|---|
| 배치 로그 | `exit=0`, `status ok`, `stage_warnings []`, `degraded []`. 신규 공고 49건 |
| 11·12단계 | 신청자 유형·업종 각각 `extracted 50`, `failed`·`deferred`·`gave_up` 0 |
| 13단계 | 두 표 각각 새로 49 · 바뀜 1(`bizinfo:PBLN_000000000126490`) · 올림 50 · `error null` |
| DB·파일 대조 | `notices`와 두 판정표 각 2,525행·고유 2,525. 판정 없는 공고 0. 파일도 각 2,525행·고유 2,525. `upload_judgments --plan` 결과 올릴 것 0 |
| 서비스 읽기 | 서버 재시작 대신 `load_auto(conn, expected=2525)`를 직접 호출했다. 신청자 유형 `db:notice_applicant_types`, `refreshed_from_file 0`. 업종 파일 `final5`(1,852행 — 오늘 새 공고 없음, 업종 순위 기본 꺼짐) |
| P2 후보 | 10단계 업력 `bizinfo:PBLN_000000000126783`: 근거는 "5년 이상 영업"인데 `age_years_min=5, age_years_max=5`로 저장됐다. 매칭 필터는 API 업력 칸만 봐서 이 공고를 빼지 않는다. 하지만 자격 확인 업력 줄에는 틀리게 보일 수 있다. `age_quote_problem`이 "이상"만 있는데 상한이 채워진 경우를 거르지 못한다 |

- 재검수 문서가 지적했듯이 `refreshed_from_file 0`은 정상의 충분조건이 아니다.
- 오늘 결과에서 그 한계로 놓친 것이 있는지 봐 달라.

## 3. 검증 방법

```powershell
# data-collection 에서. 조율 코드는 0절 방법으로 <임시 폴더>에 꺼낸 뒤
.\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain <임시 폴더>\agent-orchestration
```

- 설명서 7절 코드 블록을 그대로 꺼내 확인한다.
  - **A** T-C2 `offset` 0·10이 `TC2Out` 검사를 통과하는지
  - **B** G-01이 공고 전체 × 5가지 경우에서 매칭 1단계와 같은지
  - **C** 조율 쪽 `build_stub_app()`에 끼워 `start_run` → 더 보기 → 선택 → G-01 → "계획서작성"까지 가는지
- Claude 실행 결과(2026-09-29): `A 통과 · B 통과(5가지 모두 다름 0) · C 통과`. 필터 통과는 예비창업자 1,594건, 법인 예시 1,757건.
- 필요한 것:
  - 공용 DB 접속(`.env`), 임베딩 모델 캐시, 메모리 약 2GB
  - 조율 쪽 `pytest`는 필요 없다. 예시 입력을 옮겨 적었다.
- **전체 unittest는 오늘 돌리지 않았다.** 서비스 코드를 바꾸지 않았기 때문이다. 새 파일 `experiments/orchestration_probe.py`는 `test_*` 이름이 아니라서 unittest가 찾지 않는다.

## 4. 결과 문서에 남겨 달라

- 지적마다 P1(연결하면 틀린 결과나 장애) / P2(오해·누락) / P3(문구)로 나누고, **재현 근거**를 붙인다. 근거는 명령, 공고 ID, 코드 위치다.
- 1-2에서 반례를 찾으면 신청자 입력·공고 ID·두 함수의 결론을 적는다.
- 확인하지 못한 것은 이유와 함께 따로 적는다.
- 관례대로 [STATUS](../../STATUS.md)·[WORKLOG](../../WORKLOG.md)·[문서 지도](../../README.md)에 한 줄씩 남긴다.

## 5. 참고 문서

- [함수 설명서](../../archive/ORCHESTRATION_HANDOFF.md) — 검수 대상
- [판정 테이블 설계](../../guides/JUDGMENT_TABLES.md)
- [판정 테이블 재검수](../integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md) — 멈춘 P1과 9/29 점검표
- [기획서 대조](../../PLAN_ALIGNMENT_20260928.md) — 업종·지역은 순위 신호, 수집 범위(C)
- [STATUS](../../STATUS.md) 맨 위 세 항목 · [WORKLOG](../../WORKLOG.md) 2026-09-29 항목들
