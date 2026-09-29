# 공고팀 함수 설명서 — 조율 에이전트 개발자용

| 항목 | 내용 |
|---|---|
| 받는 사람 | 조율 에이전트(`agent-orchestration/`, SB-86) 개발자 |
| 보내는 사람 | 공고팀 이근준 (공고 데이터 · 매칭 · 자격 판정) |
| 작성일 | 2026-09-29 |
| 코드 위치 | `data-collection/` (브랜치 `feature/SB-46-data-collection`) |
| 확인 | 이 문서의 입출력 예시는 모두 **2026-09-29에 실제로 실행한 결과**다(공고 2,525건) |

공고팀은 조율 쪽 코드를 고치지 않는다. 조율 쪽이 공고팀 파이썬 함수를 **직접 import 해서 부른다.** 공고팀 서버를 따로 켤 필요는 없다.
이 문서는 그 함수들의 **파일 위치, 입력, 출력**을 정리한 것이다.

---

## 0. 한눈에 보기

| # | 하는 일 | 파일 | 부르는 법 | 넣는 것 | 받는 것 | 조율 쪽 어디에 쓰나 |
|---|---|---|---|---|---|---|
| ① | 준비 (한 번) | [search/app.py](../../search/app.py) | `app.boot()` | 없음 | 없음 | 서버 시작 때 |
| ② | **공고 추천** | [search/app.py](../../search/app.py) | `app.match(app.MatchRequest(...))` | 신청자 정보 + 아이디어 | 추천 공고 목록 (dict) | **T-C2 공고 매칭** |
| ③ | **공고 한 건 자격 확인** | [search/app.py](../../search/app.py) | `app.eligibility(app.GateRequest(...))` | 공고 ID + 신청자 유형 + 설립일 | 통과 여부 + 조건별 판정 (dict) | **G-01 자격요건 게이트** |
| ④ | 수집 상태 | [search/collection_status.py](../../search/collection_status.py) | `collection_status.check()` | 없음 | "정상" / "지연" / "실패" (dict) | T-C2의 `collectionStatus` |
| ⑤ | 공고 정보 한 건 | [search/app.py](../../search/app.py) | `app.STATE['rows'][공고ID]` | 공고 ID | 공고 정보 (dict) | 공고 공급 `announcements(id)` |

```text
[조율 서버 시작]  app.boot()                          ← ① 한 번
[사용자 입력 후]  collection_status.check()           ← ④ "정상"이 아니면 매칭 중단
                 app.match(MatchRequest(offset=0))   ← ② 추천 10건
[더 보기]        app.match(MatchRequest(offset=10))  ← ② 다음 10건
[공고 선택]      app.STATE['rows'][id]               ← ⑤ 공고 정보
                 app.eligibility(GateRequest(...))   ← ③ 신청 가능한지
```

---

## 1. 준비물

| 항목 | 내용 |
|---|---|
| 파이썬 | 3.12 (공고팀은 3.12.10) |
| 패키지 | `data-collection/requirements.txt`를 설치한다. 주요 패키지: PyMySQL, numpy, sentence-transformers(torch), chromadb, fastapi, pydantic |
| DB 접속 정보 | 공용 MySQL. Windows에서는 `data-collection/.env`, Linux에서는 `data-collection/ec2/.env`나 환경 변수를 읽는다. 키 이름은 `MYSQL_USER`, `MYSQL_PASSWORD` 등이다. **값은 공고팀에 따로 요청한다** |
| 벡터 색인 | Chroma 폴더. Windows는 `data-collection/data/vecstore/`, Linux는 `VECSTORE_PATH`(기본 `ec2/data/vecstore/chroma`) |
| 임베딩 모델 | `BAAI/bge-m3`. 처음 한 번 내려받는다(약 2GB) |

```python
import sys
sys.path.insert(0, r'<저장소>/data-collection')   # 공고팀 폴더를 import 경로에 넣는다
from search import app, collection_status
```

> 공고팀 패키지 이름이 `search`, `shared`처럼 흔하다. 조율 쪽에 같은 이름의 폴더를 만들지 않는다.

---

## 2. ① `app.boot()` — 준비

- **파일**: [search/app.py:108](../../search/app.py#L108)
- **넣는 것 / 받는 것**: 없음 / 없음 (`None`)
- **하는 일**: 공고 2,525건, 벡터 색인, 단어 검색(BM25) 색인, 판정표를 **메모리에 올린다**.
  - 공용 DB는 조회만 한다.
- **걸리는 시간과 메모리**: 16~22초, 약 **2.1GB**

```python
app.boot()      # 서버 시작 때 한 번만
```

**주의**
- 요청마다 부르지 않는다. 매번 20초가 걸린다.
- 프로세스마다 2.1GB가 든다. uvicorn `--workers`를 1로 둔다(EC2는 4GB).
- 공고는 매일 09:00 배치(약 12분)로 바뀐다. 새 공고는 **09:20 이후 서버를 재시작해야** 보인다.
- 벡터 DB가 고장 나도 예외를 내지 않고 켜진다. 이때는 단어 검색만으로 추천한다.
  문제는 `app.STATE['boot_errors']`에 적힌다(정상이면 `{}`).
- 공용 DB에 접속할 수 없으면 **예외가 난다.** 공고 정보가 없으면 추천을 할 수 없기 때문이다.

---

## 3. ② `app.match(req)` — 공고 추천 (T-C2)

- **파일**: [search/app.py:372](../../search/app.py#L372) (`match`), 입력 모델 [search/app.py:279](../../search/app.py#L279) (`MatchRequest`)
- **하는 일**:
  1. 신청할 수 없는 공고를 먼저 뺀다. 마감됨, 업력·신청자 유형이 확실히 안 맞음.
  2. 남은 공고 중 아이디어와 비슷한 공고를 찾는다(의미 검색 + 단어 검색).
  3. 지역 등으로 순서를 다듬어 돌려준다.
- **걸리는 시간**: 한 건 약 0.3초

```python
req = app.MatchRequest(applicant_type='예비창업자', idea='AI 기반 반려동물 건강관리 앱', region='서울')
out = app.match(req)            # dict
out['results'][0]['title']      # '2026년 제2회 반려동물 창업 아이디어 경진대회 참가자 모집 공고'
```

### 3.1 넣는 것 — `app.MatchRequest`

**꼭 넣는 칸**

| 이름 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `applicant_type` | str | `'예비창업자'` | `'예비창업자'`, `'개인사업자'`, `'법인'` 중 하나 |
| `idea` | str | `'AI 기반 반려동물 건강관리 앱'` | 아이템 설명. **추천 품질을 가장 크게 좌우한다.** 아이템 이름, 요약, 목표 고객, 핵심 기능을 이어 붙여 넣으면 된다 |

**넣으면 결과가 좋아지는 칸** (안 넣어도 된다)

| 이름 | 타입 | 기본값 | 예시 | 어떻게 쓰이나 |
|---|---|---|---|---|
| `founded_at` | str | `''` | `'2025-03-02'` | 설립일(`YYYY-MM-DD`). 사업자의 업력 계산에 쓴다. **비우면 업력으로 빼지 않는다** |
| `region` | str | `''` | `'서울'` | 16개 값 중 하나: 서울, 부산, 대구, 인천, 대전, 울산, 세종, 경기, 강원, 충북, 충남, 전북, **전남광주**, 경북, 경남, 제주. 다른 지역 전용 공고를 **뒤로 보낸다(빼지 않음)**. 목록에 없는 값이면 `''`로 보낸다 |
| `district` | str | `''` | `'강남구'` | 시·군·구. 같은 시·도의 다른 시·군·구 공고를 뒤로 보낸다 |
| `gender` | str | `''` | `'여성'` | `'여성'`이면 여성기업 대상 공고를 뒤로 보내지 않는다 |
| `certifications` | list[str] | `[]` | `['벤처기업']` | 보유 인증. 검색어로 쓰고, 해당 인증 대상 공고를 뒤로 보내지 않는다 |
| `first_startup` | bool 또는 None | `None` | `False` | `False`(재창업)면 재창업 공고를 뒤로 보내지 않는다 |
| `main_industry` | str | `''` | `'소프트웨어 개발'` | 업종 **이름**. 검색어로 쓴다. 코드(`J62`)만 있으면 넣지 않는 편이 낫다 |
| `hiring_plan` | bool | `False` | `True` | 채용 계획이 있으면 검색어에 "고용 계획 있음"을 붙인다 |
| `partners` | list[str] | `[]` | `['○○대학교']` | 협력 기관. 대상 집단 공고 판단에 쓴다 |
| `team` | list[{name, role, career}] | `[]` | `[{'career': '개발 5년'}]` | 팀 경력. 검색어로 쓴다 |
| `revenue` | list[{item, price}] | `[]` | `[{'item': '월 구독'}]` | 수익 모델. 검색어로 쓴다 |
| `top` | int | `10` | `10` | 몇 건 받을지 |
| `offset` | int | `0` | `10` | 몇 번째부터. 첫 조회 0, "더 보기" 10. **누적 최대 20건** |

**받아만 두고 결과에 영향이 없는 칸**
`owner_name`, `name`, `birth_date`, `equipment`, `budget_scale`, `business_no`, `self_funding`, `self_funding_budget`.
공고 데이터에 대응하는 정보가 없어서 쓰지 않는다. 넣어도 되고 안 넣어도 된다.

**건드리지 않는 칸 (평가용 스위치 — 기본값 그대로 둔다)**
`structured_filter`, `hide_expired`, `search`, `demote_region`, `demote_district`, `demote_groups`, `demote_industry`, `use_applicant_types`, `weights`.

### 3.2 받는 것 — dict

**주로 쓸 값**

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `results` | list[dict] | (아래 표) | 추천 공고. 최대 `top`건 |
| `count` | int | `10` | `results` 건수 |
| `has_more` | bool | `True` | "더 보기"로 더 받을 공고가 있는지 |
| `filtered_count` | int | `1594` | 1단계(신청 불가 빼기)를 통과한 공고 수 |
| `fallback_used` | bool | `False` | 검색 일부가 고장 나서 대체 방식을 썼는지 |
| `fallback_mode` | str 또는 None | `None` | `'BM25단독'`, `'임베딩단독'`, `'마감임박순'`, `None` |
| `filter` | dict | `{'total': 2525, 'excluded': {'접수 마감': 756, '예비창업자 불가(공고 본문)': 181}}` | 뺀 공고 수를 이유별로 |

그 밖의 키(`query`, `search_ms`, `demoted`, `region_demoted`, `industry`, `applicant_types`, `weights` 등)는 **진단·화면 설명용**이다. 조율 쪽에서는 쓰지 않아도 된다.

**`results`의 공고 한 건**

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `notice_id` | str | `'bizinfo:PBLN_000000000126505'` | **공고 ID**. `출처:원본ID` 형식. ③·⑤에 그대로 넣는다 |
| `title` | str | `'2026년 제2회 반려동물 창업 아이디어 경진대회 …'` | 공고 제목 |
| `organizer` | str | `'부산광역시'` | 기관(주관 → 소관 → 수행 순으로 채움). 빈 값 없음 |
| `source` | str | `'bizinfo'` | `'kstartup'`(K-Startup) 또는 `'bizinfo'`(기업마당) |
| `category` | str | `'창업'` | 공고 분류(출처마다 다름) |
| `target_category` | str 또는 None | `'창업벤처'` | 지원 대상 분류(원문 칸 그대로) |
| `apply_start` | str | `'2026-09-14'` | 접수 시작일. **없으면 `''`** |
| `apply_end` | str | `'2026-10-09'` | 접수 마감일. **없으면 `''`** (상시·예산 소진 시까지 등) |
| `apply_period_type` | str | `'fixed'` | `'fixed'`(기간 있음), `'budget_exhaustion'`(예산 소진 시까지), `'rolling'`(상시·수시), `'until_filled'`(선착순·모집 완료 시까지), `'unknown'` |
| `url` | str | `'https://www.bizinfo.go.kr/…'` | 원문 링크 |
| `rank` | int | `1` | 전체 순위. `offset=10`이면 11부터 |
| `display_type` | str | `'card'` | 상위 3건은 `'card'`, 나머지는 `'list'` |
| `fit_score` | float 또는 None | `1.0` | **적합도 0~1**. 검색 순위 점수(RRF) ÷ 이론 최대값(잠정). 대체 검색 `'마감임박순'`이면 `None` |
| `score` | float 또는 None | `0.5877` | 의미 검색 유사도(코사인). 정확도나 확률이 아니다 |
| `band` | str 또는 None | `'적합'` | `score`의 3단 표시: `'매우 적합'`(0.62 이상), `'적합'`(0.55 이상), `'참고'` |
| `region` | str | `'전국'` | 공고 대상 지역 |
| `region_match` | bool 또는 None | `True` | 신청자 지역이 대상인지. `None`은 모름 |
| `district_match` | bool 또는 None | `None` | 시·군·구 일치 여부. `None`은 모름 |
| `rules` | dict | `{'off_region': False, …}` | 뒤로 보낸 이유(추천 이유 문장을 만들 때 재료) |
| `dense_rank`, `bm25_rank`, `rrf_score` | int / int / float | `1`, `1`, `0.03279` | 진단용 |

### 3.3 주의
- **기준일은 실행한 날의 오늘 날짜**다. 날짜를 따로 넣는 칸이 없다.
- 검색이 고장 나도 **예외를 내지 않는다.** 대체 방식으로 결과를 주고 `fallback_used=True`로 알린다.
- 1단계를 통과한 공고가 0건이면 `results=[]`다(예외 아님).
- 입력 칸 형식이 틀리면 `MatchRequest(...)`를 만들 때 pydantic `ValidationError`가 난다.

---

## 4. ③ `app.eligibility(req)` — 공고 한 건 자격 확인 (G-01)

- **파일**: [search/app.py:813](../../search/app.py#L813) (`eligibility`), 입력 모델 [search/app.py:333](../../search/app.py#L333) (`GateRequest`)
- **하는 일**: 공고 하나에 이 신청자가 신청할 수 있는지 조건별로 판정한다.
  - 조건은 지원대상 유형, 업력, 접수기간, 모집 상태 네 가지다.
  - 규칙은 ② 매칭의 1단계와 같다. **확실히 안 되는 경우만 "안 됨"이고, 모르면 "?"(통과)다.**

```python
res = app.eligibility(app.GateRequest(notice_id='bizinfo:PBLN_000000000126505', applicant_type='예비창업자'))
res['passed']     # True
```

### 4.1 넣는 것 — `app.GateRequest`

| 이름 | 타입 | 필수 | 예시 | 설명 |
|---|---|---|---|---|
| `notice_id` | str | ○ | `'bizinfo:PBLN_000000000126505'` | ②의 `notice_id` |
| `applicant_type` | str | ○ | `'예비창업자'` | `'예비창업자'`, `'개인사업자'`, `'법인'` |
| `founded_at` | str | | `'2025-03-02'` | 설립일. 비우면 업력은 "?"(통과) |

### 4.2 받는 것 — dict

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `passed` | bool | `True` | **"안 됨"인 조건이 하나도 없으면 True.** "?"(모름)는 막지 않는다 |
| `unknown` | int | `1` | "?"인 조건 수. 0보다 크면 "원문을 확인하세요"를 띄우는 용도 |
| `checks` | list[dict] | (아래) | 조건별 판정 |
| `marks` | dict | `{'지원대상 유형': 'O', '업력': 'O', '접수기간': 'O', '모집 상태': '?'}` | 조건별 O / X / ? |
| `deadline_days` | int 또는 None | `10` | 마감까지 남은 날. 마감일이 없으면 `None` |
| `notice_id`, `title`, `url` | str | | 공고 정보 |

`checks`의 한 항목은 `{'조건', '요구', '내 값', '판정', '설명'}`이다.
- `판정`: `True`(됨), `False`(안 됨), `None`(모름)
- `설명`: 근거 문장이다. 없을 수도 있다.

```json
{"조건": "지원대상 유형", "요구": "예비창업자 신청 가능(공고 본문)", "내 값": "예비창업자", "판정": true,
 "설명": "근거: \"전국의 예비창업자(개인·팀) 또는 창업 10년 미만 기업(개인·법인)\""}
```

**G-01로 옮길 때**
- `GateResult.passed` ← `res['passed']`
- `GateResult.failed_conditions` ← `[c['조건'] for c in res['checks'] if c['판정'] is False]`
- `GateResult.undecidable` ← `False`
- `GateResult.missing_inputs` ← `[]`
- 공고팀 결정: 모름과 입력 누락은 통과로 처리한다.

### 4.3 주의
- **없는 공고 ID면 예외가 아니라 `JSONResponse`(404) 객체를 돌려준다.** 원래 화면 API 함수이기 때문이다. `isinstance(res, dict)`로 확인한다.
- **조율 쪽 G-01 입력(`G01In`)에는 공고 ID가 없어서 이 함수를 바로 부를 수 없다.**
  - 합의 ⑩(6절)이 되면 이 함수 하나로 끝난다.
  - 합의 전에는 7절의 `eligibility_of()` + `g01()` 예시를 쓴다. 같은 규칙이다.

---

## 5. ④ `collection_status.check()` — 수집 상태

- **파일**: [search/collection_status.py:133](../../search/collection_status.py#L133)
- **하는 일**: 공고 데이터가 믿을 만큼 새것인지 판정한다.
  - **24시간 넘게 새 저장이 없으면 "지연"**이다.
  - 최근 배치가 실패했거나, 출처 하나가 실패해 옛 데이터를 재사용했으면 "실패"다.
  - 부를 때마다 공용 DB 표 하나를 조회한다(SELECT 1회).

```python
collection_status.check()['status']     # '정상'
```

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `status` | str | `'정상'` | `'정상'`, `'지연'`, `'실패'` — 조율 쪽 `CollectionStatus`와 같은 값 |
| `block_matching` | bool | `False` | `status`가 정상이 아니면 True |
| `reasons` | list[str] | `[]` | 지연·실패 이유 |
| `last_run_at` | str | `'2026-09-29T00:00:05+00:00'` | 마지막 저장 시각(UTC) |
| `age_hours` | float | `0.5` | 마지막 저장 후 지난 시간 |

---

## 6. ⑤ `app.STATE['rows'][공고ID]` — 공고 정보 한 건

- **파일**: [search/app.py](../../search/app.py) `boot()`가 채우는 메모리 dict. 칸 목록은 `FIELDS`([search/app.py:47](../../search/app.py#L47))에 있다.
- 없는 ID면 `KeyError`가 난다. `app.STATE['rows'].get(id)`로 확인한다.

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `notice_id`, `title`, `url`, `source`, `category`, `target_category`, `region` | str | | ②와 같다 |
| `organizer`, `supervising_org`, `executing_org` | str 또는 None | `None`, `'부산광역시'`, `'한국반려동물산업협회'` | 주관, 소관, 수행 기관 |
| `apply_start`, `apply_end` | `datetime.date` 또는 None | `date(2026, 10, 9)` | **여기서는 날짜 객체다.** ②에서는 문자열이다 |
| `apply_period_type` | str | `'fixed'` | ②와 같다 |
| `recruitment_status` | str | `'unknown'` | `'open'`, `'closed'`, `'unknown'`. 기업마당은 모두 `'unknown'`(원문에 칸이 없음) |
| `age_condition_raw` | str 또는 None | `'예비창업자,3년미만'` | K-Startup 업력 원문. 기업마당은 None |
| `apply_url` | str | | 신청 페이지 |

공고 요약 벡터(1024차원)는 `app.STATE['collection'].get(ids=[공고ID], include=['embeddings'])`로 꺼낸다.
**지원 금액, 신청서 양식, 평가 항목은 여기에 없다**(7절 합의 ②·③).

---

## 7. 조율 규격에 끼우는 예시 (2026-09-29 실행 확인)

아래 코드를 실제로 실행해 확인했다.
- 조율 쪽 모델(`sbrain`, 커밋 `deb5c81`) 검사를 통과했다.
- 이 코드 블록을 그대로 조율 쪽 `build_stub_app()`에 `registry.bind`로 끼웠다.
  사전 입력 → T-C2 10건 → 더 보기 10건 → 공고 선택 → G-01 통과 → **"계획서작성"**까지 넘어갔다.
- G-01 규칙을 ② 매칭 1단계와 대조했다. 공고 2,525건 × 신청자 5가지 경우(예비창업자, 설립일 있는 개인사업자·법인 3가지, 설립일 없는 개인사업자)에서 **전부 같은 결론**이었다.

⚠ 표시가 붙은 값은 아래 합의 전의 임시값이다.

```python
from datetime import date
from sbrain.contracts import tasks as c
from sbrain.models.domain import AnnouncementCard, EligibilityRule, GateResult
from search import app, gate, collection_status, applicant_types as types_mod

PRE = '예비창업자'
SOURCE_NAME = {'kstartup': 'K-Startup', 'bizinfo': '기업마당'}


def tc2(inp: c.TC2In, tools) -> c.TC2Out:
    it, co = inp.item_spec, inp.company_info
    idea = '. '.join([it.item_name, it.one_line_summary, '목표 고객: ' + it.target_customer,
                      '핵심 기능: ' + ', '.join(it.core_features), '키워드: ' + ', '.join(it.keywords)])
    req = app.MatchRequest(
        applicant_type=co.applicant_type,
        founded_at=co.founded_at.isoformat() if co.founded_at else '',
        idea=idea, region=co.region if co.region in app.region_mod.REGIONS else '',
        gender=co.gender, certifications=co.certifications or [], first_startup=co.is_first_startup,
        top=inp.top_k, offset=inp.offset)
    status = collection_status.check()['status']
    out = tools.search('공고 매칭', lambda timeout: app.match(req))
    cards = [AnnouncementCard(
        announcement_id=r['notice_id'], title=r['title'], agency=r['organizer'] or '-',
        apply_end=date.fromisoformat(r['apply_end']) if r['apply_end'] else date(9999, 12, 31),  # ⚠ ①
        support_amount_max=0,                                                                   # ⚠ ②
        fit_score=r['fit_score'] or 0.0, rank=r['rank'], display_type=r['display_type'],
        match_reason='',                                                                        # ⚠ ⑤
        source_notice='본 AI 요약 정보는 %s 공고 내용을 바탕으로 생성되었습니다.' % SOURCE_NAME.get(r['source'], r['source']),
        original_url=r['url']) for r in out['results']]
    return c.TC2Out(candidates=cards, collection_status=status, filtered_count=out['filtered_count'],
                    fallback_used=out['fallback_used'], fallback_mode=out['fallback_mode'])


def eligibility_of(notice_id: str) -> tuple[EligibilityRule, bool]:
    """공고 공급(announcements)에서 Announcement.eligibility · eligibility_parsed 를 채울 때 쓴다.
    G01In 에 공고 ID 가 없어서, 공고팀 판정을 미리 EligibilityRule 로 바꿔 둔다(합의 ⑩ 전까지)."""
    row = app.STATE['rows'][notice_id]
    raw = row.get('age_condition_raw')
    understood = gate.understood(raw)
    pre_ok, cap_months = gate.parse_enyy(raw)
    verdict = types_mod.pre_founder(app.STATE.get('applicant_types') or {}, notice_id)
    pre_allowed = not (understood and not pre_ok)        # 업력 칸에 '예비창업자'가 없으면 불가
    if verdict == 'allowed':                             # 공고 본문 판정이 API 칸보다 우선
        pre_allowed = True
    elif verdict == 'blocked':
        pre_allowed = False
    business_allowed = not (understood and cap_months is None)   # '예비창업자'만 적힌 공고
    types = ([PRE] if pre_allowed else []) + (['개인사업자', '법인'] if business_allowed else [])
    rule = EligibilityRule(applicant_types=types,
                           business_age_max_years=cap_months / 12 if (understood and cap_months) else None)
    return rule, bool(understood or verdict in ('allowed', 'blocked'))


def g01(inp: c.G01In) -> c.G01Out:
    """확실히 안 되는 경우만 불합격. 모름·입력 누락(설립일 없음)은 통과 (공고팀 결정 2026-09-29)."""
    co, rule = inp.company_info, inp.eligibility
    failed = []
    if co.applicant_type == PRE:
        months = None
        if PRE not in rule.applicant_types:
            failed.append('지원대상 유형')
    else:
        months = gate.business_age_months(co.founded_at, inp.today)
        if months is not None:
            if co.applicant_type not in rule.applicant_types:
                failed.append('지원대상 유형')
            elif rule.business_age_max_years is not None and months >= rule.business_age_max_years * 12:
                failed.append('업력')          # 업력 조건은 "N년 미만"
    return c.G01Out(gate_result=GateResult(passed=not failed, failed_conditions=failed,
                                           missing_inputs=[], undecidable=False),
                    business_age_years=None if months is None else round(months / 12, 1))

# 조율 쪽 조립부(bootstrap)에서:
#   app.boot()
#   registry.bind("T-C2", tc2); registry.bind("G-01", g01)
#   announcements=lambda aid: Announcement(..., eligibility=eligibility_of(aid)[0],
#                                          eligibility_parsed=eligibility_of(aid)[1], ...)
```

---

## 8. 합의가 필요한 사항

번호로 답해 주면 된다.

| # | 사항 | 공고팀 데이터 현황 | 공고팀 제안 |
|---|---|---|---|
| ① | 카드·공고의 `apply_end`, `apply_start`가 필수다 | 2,525건 중 **985건 마감일 없음**. 예산 소진 시까지 678, 상시·수시 149, 선착순·모집 완료 시까지 94, 정보 없음 64. 원래 마감일이 없는 공고다. 흐름 시험에서도 상위 3건 중 2건이 여기에 해당했다 | 두 칸을 **선택(`None` 허용)**으로 바꾸고, `apply_period_type`을 함께 받기 |
| ② | 카드·공고의 `support_amount_max`가 필수 정수다 | 금액을 추출한 공고 **787건**(공용 DB `notice_conditions.amount_max_won`). 나머지는 공고문에 없거나 못 읽음 | **선택**으로 바꾸기. 계속 필수로 둔다면 0 = "금액 정보 없음"으로 약속 |
| ③ | 공고의 `form_spec`(신청서 양식)과 `evaluation_items`(평가 항목)가 필수다 | **공고팀 DB에 없다.** 첨부 문서에서 뽑아야 하는 정보다 | 누가 만들지 정하기. 작성(T-W1), 검증(T-V1), 검수(T-P1)가 이 값에 의존한다. 우선 공고 종류별 **기본 양식·평가 항목**을 상수로 두는 방법이 있다 |
| ④ | `support_field`가 "창업(06)"과 "기술개발(02)" 두 값만 허용한다 | 기업마당 8개 분야(경영, 기술, 수출, 금융, 인력, 내수, 창업, 기타)와 K-Startup 분류를 전부 수집한다 | 값 범위를 넓히거나 `str`로 바꾸기 |
| ⑤ | 카드의 `match_reason`(추천 이유) | 공고팀 결과에 이유 문장이 없다. 재료는 있다: `region_match`, `rules`, `fit_score` | 조율 쪽이 재료로 짧은 문장을 만들기. 공고팀이 결과에 문장을 추가해 주기를 원하면 알려 달라 |
| ⑥ | 공고의 `status`가 "모집중"/"마감" 두 값뿐이다 | 모집 상태 모름 **2,086건**(기업마당은 칸이 없음) | 모르면 "모집중"으로 두기. 마감이 지난 공고는 ②에서 이미 빠진다 |
| ⑦ | G-01 "통과했지만 확인 필요"를 담을 칸이 없다 | ③의 `unknown`에 "?" 수가 있다 | 필요하면 `GateResult`에 확장 칸(예: `unknown_conditions: list[str]`) 추가 |
| ⑧ | 수집 상태가 "지연"이어도 매칭 전체가 멈춘다 | 배치가 하루 늦으면 서비스가 멈춘다 | 기능정의서 R-3(24시간)을 따른다. 알고만 있어 달라 |
| ⑨ | `CompanyInfo.region` 값 | 공고팀은 3.1의 16개 값만 읽는다 | 같은 목록을 쓰기. 다른 값이면 지역 순위 조정이 꺼진다 |
| ⑩ | `G01In`에 공고 ID가 없다 | ③ `app.eligibility()`는 공고 ID로 판정한다 | `G01In`에 `announcement_id`를 추가하면 G-01이 **③ 호출 한 줄**로 끝난다. 7절의 `eligibility_of()` 변환이 필요 없어진다 |

---

## 9. 운영 정보와 문의

- **매일 09:00 배치**(공고팀 PC, 약 12분): 수집 → 임베딩 → 벡터·첨부 업로드 → 판정 추출 → 공용 DB 올리기.
  2026-09-29 기준 공고 2,525건이다.
- 이 문서의 함수 이름이나 입출력 칸을 바꾸게 되면 **이 문서를 먼저 고치고 알린다.**
- 문의: 이근준(공고팀).
