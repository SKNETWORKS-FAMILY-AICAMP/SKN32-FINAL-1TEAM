# 공고팀 함수 설명서 — 조율 에이전트 개발자용

공고팀 이근준 → 조율 에이전트(`agent-orchestration/`, SB-86) 개발자 · 2026-09-29 4차 개정

조율 쪽이 공고팀 파이썬 함수를 **직접 import 해서 부른다.** 공고팀 서버는 따로 켜지 않는다.
이 문서의 예시와 수치는 모두 2026-09-29 실제 실행 결과다. 공고는 2,525건이다.
개정 이유는 [Codex 검수](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_20260929.md) 반영이다(맨 끝 "개정 기록").

---

## 1. 빠른 시작 — 이것만 보면 된다

```python
# 빠른 시작
import sys
sys.path.insert(0, 'data-collection')          # 저장소 루트 기준. 공고팀 폴더를 import 경로에 넣는다
from search import app, collection_status

app.boot()                                     # ① 서버 켤 때 한 번 (약 20초, 메모리 약 2GB)


def recommend(applicant_type, idea, region=''):
    """추천 공고 목록. 조율 흐름과 같게, 수집 상태가 '정상'이 아니면 추천하지 않는다."""
    conn = app._connect()                      # ② 수집 상태 — boot 와 같은 접속 정보를 쓰게 연결을 넘긴다
    try:
        status = collection_status.check(connection=conn)['status']   # '정상' | '지연' | '실패'
    finally:
        conn.close()
    if status != '정상':
        return status, []                      #    조율: E-C2-STALE "공고 정보를 갱신하는 중입니다"
    out = app.match(app.MatchRequest(          # ③ 공고 추천 (약 0.3초)
        applicant_type=applicant_type, idea=idea, region=region))
    return status, out['results']              #    빈 목록이면 조율: E-C2-NOMATCH "지금 신청 가능한 공고가 없습니다"


status, cards = recommend('예비창업자', 'AI 기반 반려동물 건강관리 앱', '서울')
if cards:
    first = cards[0]                           #    추천 공고 10건 중 1위
    print(status, first['notice_id'], first['title'], first['fit_score'])
    row = app.STATE['rows'][first['notice_id']]    # ④ 고른 공고의 정보
    print(row['apply_end'], row['url'])
else:
    print('추천 없음:', status)                 #    수집 상태가 정상이 아니거나, 조건에 맞는 공고가 0건
```

| # | 하는 일 | 파일 | 부르는 법 | 조율 쪽 어디에 |
|---|---|---|---|---|
| ① | 준비 (한 번) | [search/app.py](../../search/app.py) | `app.boot()` | 서버 시작 |
| ② | 수집 상태 | [search/collection_status.py](../../search/collection_status.py) | `collection_status.check(connection=…)` | T-C2 `collectionStatus` |
| ③ | **공고 추천** | [search/app.py](../../search/app.py) | `app.match(app.MatchRequest(…))` | **T-C2** |
| ④ | 공고 정보 | [search/app.py](../../search/app.py) | `app.STATE['rows'][공고ID]` | 공고 공급 `announcements(id)` |
| ⑤ | **자격 판정** | 이 문서 5절의 `eligibility_of()` + `g01()` | — | **G-01** |

- G-01은 공고팀 함수 하나로 끝나지 않는다. 5절 예시 코드(20줄)를 그대로 쓰면 된다.
- 5절 예시는 매칭 1단계와 **같은 결론**을 낸다. 공고 2,525건 × 신청자 5가지 경우 전부를 대조했다.

---

## 2. 연결 전에 꼭 합의할 것

아래 네 가지가 정해지지 않으면 **실제 연결이 동작하지 않거나, 사용자에게 잘못된 안내가 나간다.**

### ① 마감일 없는 공고 — `apply_end`·`apply_start`
- **현황**: 2,525건 중 **985건**은 마감일이 없다. 원래 마감일이 없는 공고다.
  - 예산 소진 시까지 678, 상시·수시 149, 선착순·모집 완료 시까지 94, 정보 없음 64.
  - 추천 상위 3건 중 2건이 이런 공고인 경우도 있었다.
- **문제**: 조율 모델은 마감일을 **두 곳에서** 필수로 요구한다.
  - 공고 정보 `Announcement.apply_start`·`apply_end`([sbrain/models/domain.py:161-162](../../../agent-orchestration/sbrain/models/domain.py))
  - 추천 카드 `AnnouncementCard.apply_end`([domain.py:178](../../../agent-orchestration/sbrain/models/domain.py))
  - 모델만 `None` 허용으로 바꾸면 마감일을 쓰는 코드가 **오류로 멈춘다.**
    - 조율 화면 상태 [sbrain/flow/service.py:259](../../../agent-orchestration/sbrain/flow/service.py)의 `ann.apply_end < 오늘`
    - 스텁 작업 분해(T-C3, [stubs.py:247](../../../agent-orchestration/sbrain/agents/stubs.py))와 보호 토큰(G-03, [stubs.py:392](../../../agent-orchestration/sbrain/agents/stubs.py))의 `apply_end.isoformat()`
    - 실제 T-C3·G-03을 구현할 때도 같은 처리가 필요하다.
  - 예시 코드의 `9999-12-31`은 카드 형식 검사만 통과시키는 임시값이다. 마감 판정을 대신하지 못한다.
- **제안**: 아래를 **한 번에** 바꾼다.
  - 위 세 칸(`Announcement` 둘, `AnnouncementCard` 하나)을 `date | None`으로 바꾼다.
  - 마감 형태 `apply_period_type`을 **새 칸으로 추가**한다. 지금은 `Announcement`에도 `AnnouncementCard`에도 이 칸이 없다([domain.py:156-185](../../../agent-orchestration/sbrain/models/domain.py)). 모델이 모르는 칸을 거부하므로(`extra="forbid"`) 합의 전에는 공고팀 예시(5절 `tc2()`)도 이 값을 넣을 수 없다.
    - 값: `'fixed'`(기간 있음), `'budget_exhaustion'`(예산 소진 시까지), `'rolling'`(상시·수시), `'until_filled'`(선착순·모집 완료 시까지), `'unknown'`(정보 없음).
    - 공고팀 출처: 추천 결과 `r['apply_period_type']`(4.2), 공고 정보 `app.STATE['rows'][id]['apply_period_type']`(4.4).
    - 화면은 마감일이 없으면 이 값으로 "예산 소진 시까지"·"상시 접수" 등을 표시한다. **카드(추천 목록)와 공고 상세 둘 다** 표시하도록 합의한다.
  - 마감일을 쓰는 곳에 빈 값 처리를 넣는다. 예: 259행 `ann.apply_end and ann.apply_end < 오늘`, `isoformat()` 호출 앞에 `None` 확인.

### ② 지원 금액 — `support_amount_max`
- **현황**: 금액을 추출한 공고는 **787건**뿐이다(공용 DB `notice_conditions.amount_max_won`). 나머지는 공고문에 없거나 못 읽었다.
- **제안**: 선택(`int | None`)으로 바꾼다. 계속 필수로 둔다면 "0 = 금액 정보 없음"으로 약속하고 화면에서 그렇게 표시한다.

### ③ 신청서 양식·평가 항목 — `form_spec`·`evaluation_items`
- **현황**: **공고팀 DB에 없다.** 공고 첨부 문서에서 뽑아야 하는 정보다.
- **문제**: 조율 흐름의 작성(T-W1), 검증(T-V1), 검수(T-P1)가 이 값을 쓴다. 이 값 없이는 `Announcement`를 만들 수 없다.
- **제안**: 누가 만들지부터 정한다. 당장은 공고 종류별 **기본 양식·평가 항목**을 상수로 두는 방법이 있다.
- 참고로 공고팀의 흐름 시험(`experiments/orchestration_probe.py` C)은 조율 쪽 스텁 공고의 양식·평가 항목·금액을 빌려 썼다. **실제 공고 공급은 아직 검증되지 않았다.**

### ⑦ "확인 필요" 표시 — `GateResult`
- **공고팀 결정(2026-09-29)**: G-01은 확실히 안 되는 경우만 불합격이다. **모름과 입력 누락(예: 설립일 없는 사업자)은 통과**다.
  - 조율 흐름은 `undecidable`·`missing_inputs`가 있으면 계획서 작성을 막는다.
  - 그대로 두면 정보가 적은 공고 대부분(주로 기업마당)이 막힌다.
- **대가**: 지금 `GateResult`에는 "통과했지만 확인 필요"를 담을 칸이 없다.
  - 정보가 부족한 공고도 **아무 안내 없이** 계획서 작성으로 넘어간다.
  - 모집 상태 모름 2,086건, 마감일 없음 985건이 여기에 해당할 수 있다.
  - `E-G1-UNPARSED`·`E-G1-MISSING` 안내는 나오지 않는다.
- **제안**: `GateResult`에 확장 칸 `unknown_conditions`를 추가한다. **그리고 계획서 작성 화면이 이 값을 사용자에게 보여 준다**는 것까지 합의한다.
  - **조건 이름만 줄지, 이유 문장도 줄지** 함께 정한다. 공고팀 권장은 **이유까지** 주는 것이다. 이름만으로는 사용자가 무엇을 확인할지 모른다.
    - 이름만: `list[str]` — 예: `['업력', '모집 상태']`
    - 이유까지(권장): `list[{"condition": str, "reason": str}]` — 예: `[{"condition": "모집 상태", "reason": "모집 상태 정보 없음"}]`. 이유는 4.5의 `c.get('설명') or c['요구']`로 만든다.
  - 칸만 추가하고 화면에 안 보이면 효과가 없다. 지금 조율의 화면 상태 `RunView`([service.py:42-51](../../../agent-orchestration/sbrain/flow/service.py))에는 G-01 결과(`gateResult`)가 없다. 화면이 그 산출물을 읽게 하거나 `RunView`에 표시용 칸을 더하는 경로도 함께 정한다.
  - 조율 모델은 모르는 칸을 거부하므로(`extra="forbid"`) 합의 전에는 공고팀이 채울 수 없다.
- **목록을 어디서 만드나 — 이것도 합의 대상이다.**
  - 지금 `G01In`에는 신청자 정보·자격 조건·날짜만 있다([tasks.py:99-103](../../../agent-orchestration/sbrain/contracts/tasks.py)). 공고 ID·모집 상태·마감 형태는 없다.
  - 그래서 5절의 `g01()`만으로는 "모집 상태를 모른다"는 사실을 알 수 없다.

  | 방식 | 방법 | 비고 |
  |---|---|---|
  | **가. G-01에 공고 ID를 넘긴다 (공고팀 권장)** | `G01In`에 `announcement_id`를 추가하고, **G-01 입력 연결([catalog.py:55-58](../../../agent-orchestration/sbrain/flow/catalog.py))에도 공고 ID를 넣는다**(6절 ⑩과 같은 변경 — 연결을 빠뜨리면 값이 비어 입력 검증에서 실패한다). G-01 안에서 합격/불합격은 5절 `g01()` 규칙으로 정하고, 확인 필요 목록은 `app.eligibility()`의 `checks`에서 **`판정`이 `None`인 조건**을 모은다. 이때 **접수기간 줄은 뺀다**(4.5) | 공고팀 판정을 한 곳(공고팀 코드)에서 가져온다. `app.eligibility()`는 날짜 인자가 없어 실행한 날을 기준으로 한다 |
  | 나. 공고 공급 단계에서 미리 계산한다 | `announcements(id)`가 `Announcement`의 확장 칸(예: `unknown_conditions`)에 목록을 담고, G-01 입력으로 연결한다 | 신청자 정보(유형·설립일)에 따라 목록이 달라진다. 그런데 공고 공급에는 신청자 정보가 들어오지 않아 **신청자별로 정확히 만들 수 없다** |

- **숫자로 본 규모** (2026-09-29, 고를 수 있는 공고 기준, 접수기간 제외):
  - 예비창업자는 1,594건 중 **1,492건(94%)**에 확인 필요 조건이 하나 이상 있다.
  - 사업자는 **100%**다(법인 2024-12 설립 1,757건, 설립일 없는 개인사업자 1,769건). 개인/법인 구분 데이터가 없어 "지원대상 유형"이 항상 모름이기 때문이다.
  - 그래서 "확인 필요 있음/없음" 한 칸으로는 **거의 모든 공고에 표시가 붙어 의미가 없다.** 화면에는 **어떤 조건이 확인 필요인지 조건 이름을 그대로** 보여 주고, 원문 링크로 이어지게 하는 것을 권한다.

### 공고팀이 정한 것 (참고)
- **접수 시작 전 공고는 고를 수 있다**(2026-09-29). 매칭 1단계도 이런 공고를 남긴다. 그래서 G-01은 접수기간을 보지 않는다.
- **업종·지역은 순위 신호로만 쓴다**(기획서 4-2·5-3). 게이트에서 빼는 데 쓰지 않는다.

---

## 3. 준비물과 운영 주의

### 3.1 준비물

| 항목 | 내용 |
|---|---|
| 파이썬 | 3.12 (공고팀은 3.12.10). 가상환경 `.venv`는 **PC마다 새로 만든다.** 다른 PC에서 복사한 `.venv`는 원래 PC의 파이썬 설치 경로를 가리켜 실행되지 않는다: `python -m venv .venv` → `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| 패키지 | `data-collection/requirements.txt` — PyMySQL, numpy, sentence-transformers(torch), chromadb, fastapi, pydantic |
| DB 접속 정보 | 공용 MySQL. 키 이름은 `MYSQL_USER`, `MYSQL_PASSWORD` 등이다. **값은 공고팀에 따로 요청한다.** 읽는 위치는 3.2 |
| 벡터 색인 | Chroma 폴더. Windows는 `data-collection/data/vecstore/`, Linux는 `VECSTORE_PATH`(기본 `data-collection/ec2/data/vecstore/chroma`) |
| 임베딩 모델 | `BAAI/bge-m3`. 처음 한 번 내려받는다(약 2GB) |

> 공고팀 패키지 이름이 `search`, `shared`처럼 흔하다. 조율 쪽에 같은 이름의 폴더를 만들지 않는다.

### 3.2 DB 접속 정보를 읽는 곳 — Windows와 Linux가 다르다

| 누가 | Windows | Linux(EC2) |
|---|---|---|
| `app.boot()`, `app._connect()` | `shared/store_mysql` → `data-collection/.env` 또는 `data-collection/shared/.env` | `ec2/ec2_vecstore` → 환경 변수, 없으면 `data-collection/ec2/.env` |
| `collection_status.check()`를 **연결 없이** 부를 때 | `data-collection/.env` | **`ec2/.env`를 읽지 않는다** → 접속 정보 없음으로 실패할 수 있다 |

그래서 1절처럼 **`app._connect()`로 얻은 연결을 `check(connection=…)`에 넘긴다.** 이렇게 하면 두 운영체제 모두 `boot()`와 같은 접속 정보를 쓴다.
환경 변수로 접속 정보를 공통 설정해도 된다. Linux 실행은 공고팀이 아직 시험하지 않았다.

### 3.3 운영 주의
1. `boot()`는 **서버 시작 때 한 번만** 부른다. 요청마다 부르면 매번 20초가 걸린다.
2. **프로세스 하나에 약 2GB**가 든다. uvicorn `--workers`는 1로 둔다(EC2는 4GB + 스왑 2GB).
3. 공고는 **매일 09:00 배치**(약 12분)로 바뀐다. `boot()`가 읽은 공고는 메모리에 남아 있어서 저절로 바뀌지 않는다.
   - 새 공고를 보려면 **09:20 이후 재시작**한다. 방법은 메모리 여유에 따라 고른다.
     - **여유가 넉넉할 때**: 새 프로세스를 먼저 띄우고, 준비가 끝나면 옛 프로세스와 바꾼다. 멈춤 없이 바뀐다. 다만 바꾸는 동안 **2GB짜리 두 개(약 4GB 이상)**가 함께 돈다. OS·DB·다른 서비스 메모리도 더해지므로, 미리 여유를 확인한다(Linux `free -m`).
     - **여유가 모자랄 때**(예: 4GB 서버, 같은 서버에 MySQL): 옛 프로세스를 **먼저 끄고** 새로 켠다. `boot()`가 끝날 때까지 **약 20~30초 동안 추천이 멈춘다.** 사용자가 적은 시간에 한다.
     - 두 프로세스의 동시 구동은 공고팀이 측정하지 않았다. EC2 4GB에서는 두 번째 방법이 안전하다.
   - 실행 중에 `boot()`를 다시 부르지 않는다. 불러오는 도중 요청이 들어와도 안전한지 확인하지 않았다.
4. 여러 스레드에서 `app.match()`를 동시에 불러도 안전한지는 **확인하지 않았다.** 확인 전까지는 호출을 한 번에 하나씩 처리하거나(잠금) 순서대로 부르기를 권한다.
5. `boot()`가 멈추는 경우:
   - **공용 DB 접속 실패**면 예외가 난다. 공고 정보가 없으면 추천할 수 없기 때문이다.
   - 벡터 DB 장애는 예외 없이 넘어간다. 대신 단어 검색만으로 추천한다(`app.STATE['boot_errors']`에 기록, 정상이면 `{}`).
   - **알려진 문제**: 신청자 유형 결과 파일(`data/applicant_types/results.jsonl`)이 깨져 있으면 DB가 정상이어도 `boot()`가 멈출 수 있다([9/28 재검수](../reviews/integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md) P1, 공고팀 수정 대기).
     이 파일은 배치 PC에만 있다. 파일이 없는 곳에서는 해당하지 않는다.

---

## 4. 함수 상세

### 4.1 `app.boot()` — 준비
- **파일**: [search/app.py:108](../../search/app.py#L108)
- **넣는 것 / 받는 것**: 없음 / 없음
- **하는 일**: 공고 2,525건, 벡터 색인, 단어 검색(BM25) 색인, 판정표를 메모리에 올린다. 공용 DB는 조회만 한다.
- **걸리는 시간과 메모리**: 16~22초, 약 2.1GB. 주의 사항은 3.3.

### 4.2 `app.match(req)` — 공고 추천 (T-C2)
- **파일**: [search/app.py:372](../../search/app.py#L372) (`match`), 입력 모델 [search/app.py:279](../../search/app.py#L279) (`MatchRequest`)
- **하는 일**:
  1. 신청할 수 없는 공고를 먼저 뺀다. 마감됨, 업력·신청자 유형이 확실히 안 맞음.
  2. 남은 공고 중 아이디어와 비슷한 공고를 찾는다(의미 검색 + 단어 검색).
  3. 지역 등으로 순서만 다듬는다.

#### 넣는 것 — `app.MatchRequest`

**꼭 넣는 칸**

| 이름 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `applicant_type` | str | `'예비창업자'` | `'예비창업자'`, `'개인사업자'`, `'법인'` |
| `idea` | str | `'AI 기반 반려동물 건강관리 앱'` | 아이템 설명. **추천 품질을 가장 크게 좌우한다.** 아이템 이름, 요약, 목표 고객, 핵심 기능을 이어 붙여 넣는다 |

**넣으면 결과가 좋아지는 칸** (안 넣어도 된다)

| 이름 | 타입 | 기본값 | 예시 | 어떻게 쓰이나 |
|---|---|---|---|---|
| `founded_at` | str | `''` | `'2025-03-02'` | 설립일(`YYYY-MM-DD`). 사업자의 업력 계산에 쓴다. 비우면 업력으로 빼지 않는다 |
| `region` | str | `''` | `'서울'` | 16개 값 중 하나: 서울, 부산, 대구, 인천, 대전, 울산, 세종, 경기, 강원, 충북, 충남, 전북, **전남광주**, 경북, 경남, 제주. 다른 지역 전용 공고를 **뒤로 보낸다(빼지 않음)**. 목록에 없는 값이면 `''`로 보낸다 |
| `district` | str | `''` | `'강남구'` | 시·군·구. 같은 시·도의 다른 시·군·구 공고를 뒤로 보낸다 |
| `gender` | str | `''` | `'여성'` | `'여성'`이면 여성기업 대상 공고를 뒤로 보내지 않는다 |
| `certifications` | list[str] | `[]` | `['벤처기업']` | 보유 인증. 검색어로 쓰고, 해당 인증 대상 공고를 뒤로 보내지 않는다 |
| `first_startup` | bool 또는 None | `None` | `False` | `False`(재창업)면 재창업 공고를 뒤로 보내지 않는다 |
| `main_industry` | str | `''` | `'소프트웨어 개발'` | 업종 **이름**. 검색어로 쓴다. **코드(`J62`)는 이해하지 못한다** — 6절 ⑫ |
| `hiring_plan` | bool | `False` | `True` | 채용 계획이 있으면 검색어에 "고용 계획 있음"을 붙인다. 조율 쪽 `CompanyInfo.hiring_plan`은 **글(str)**이라 변환 규칙이 필요하다 — 6절 ⑫ |
| `partners` | list[str] | `[]` | `['○○대학교']` | 협력 기관. 대상 집단 공고 판단에 쓴다(조율 쪽은 str) |
| `team` | list[{name, role, career}] | `[]` | `[{'career': '개발 5년'}]` | 팀 경력. 검색어로 쓴다 |
| `revenue` | list[{item, price}] | `[]` | `[{'item': '월 구독'}]` | 수익 모델. 검색어로 쓴다 |
| `top` | int | `10` | `10` | 몇 건 받을지. **10 이하로 둔다**(조율 카드 최대 10건) |
| `offset` | int | `0` | `10` | 몇 번째부터. 첫 조회 0, "더 보기" 10. 조율 카드 `rank`는 1~20이라 **0 또는 10만 쓴다** |

**추천 순위에 영향이 없는 칸**: `owner_name`, `name`, `birth_date`, `equipment`, `budget_scale`, `business_no`, `self_funding`, `self_funding_budget`.
응답의 진단 값 `stored_only`에만 나타난다.

**건드리지 않는 칸**(평가용 스위치): `structured_filter`, `hide_expired`, `search`, `demote_region`, `demote_district`, `demote_groups`, `demote_industry`, `use_applicant_types`, `weights`.

#### 받는 것 — dict

**주로 쓸 값**

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `results` | list[dict] | (아래 표) | 추천 공고. 최대 `top`건 |
| `count` | int | `10` | `results` 건수 |
| `has_more` | bool | `True` | "더 보기"로 더 받을 공고가 있는지 |
| `filtered_count` | int | `1594` | 1단계(신청 불가 빼기)를 통과한 공고 수 |
| `fallback_used` | bool | `False` | 검색 일부가 고장 나서 대체 방식을 썼는지 |
| `fallback_mode` | str 또는 None | `None` | `'BM25단독'`, `'임베딩단독'`, `'마감임박순'`, `None`. 조율 쪽 `FallbackMode`와 같은 값 |
| `filter` | dict | `{'total': 2525, 'excluded': {'접수 마감': 756, '예비창업자 불가(공고 본문)': 181}}` | 뺀 공고 수를 이유별로 |

그 밖의 키(`query`, `search_ms`, `demoted`, `region_demoted`, `industry`, `applicant_types`, `stored_only` 등)는 진단·화면 설명용이다.

**`results`의 공고 한 건**

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `notice_id` | str | `'bizinfo:PBLN_000000000126505'` | **공고 ID**. `출처:원본ID` 형식 |
| `title` | str | `'2026년 제2회 반려동물 창업 아이디어 경진대회 …'` | 공고 제목 |
| `organizer` | str | `'부산광역시'` | 기관(주관 → 소관 → 수행 순으로 채움). 빈 값 없음 |
| `source` | str | `'bizinfo'` | `'kstartup'`(K-Startup) 또는 `'bizinfo'`(기업마당) |
| `category` | str | `'창업'` | 공고 분류(출처마다 다름) |
| `target_category` | str 또는 None | `'창업벤처'` | 지원 대상 분류(원문 칸 그대로) |
| `apply_start` | str | `'2026-09-14'` | 접수 시작일. **없으면 `''`**. 시작 전 공고도 나온다 |
| `apply_end` | str | `'2026-10-09'` | 접수 마감일. **없으면 `''`** |
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
| `rules` | dict | `{'off_region': False, …}` | 뒤로 보낸 이유(추천 이유 문장의 재료) |
| `dense_rank`, `bm25_rank`, `rrf_score` | int / int / float | `1`, `1`, `0.03279` | 진단용 |

#### 주의
- **기준일은 실행한 날의 오늘 날짜**다. `TC2In.today`를 넘길 칸이 없다. 자정 무렵이나 다시 실행할 때 결과가 달라질 수 있다.
- 검색이 고장 나도 예외를 내지 않는다. 대체 방식으로 결과를 주고 `fallback_used=True`로 알린다.
- 1단계를 통과한 공고가 0건이면 `results=[]`다.
- 직접 호출에는 HTTP API(`/api/match`)의 "누적 20건" 자르기가 걸리지 않는다. 위 표의 `top`·`offset` 범위를 지킨다.
- 입력 칸 형식이 틀리면 `MatchRequest(...)`를 만들 때 pydantic `ValidationError`가 난다.

### 4.3 `collection_status.check(connection=…)` — 수집 상태
- **파일**: [search/collection_status.py:133](../../search/collection_status.py#L133)
- **넣는 것**: `connection` — **`app._connect()`로 얻은 연결을 넘긴다**(3.2).
  - 넘긴 연결은 이 함수가 닫지 않는다. 호출한 쪽이 닫는다.
- **하는 일**: 공고 데이터가 믿을 만큼 새것인지 판정한다. 부를 때마다 DB 표 하나를 조회한다(SELECT 1회).
  - **24시간 넘게 새 저장이 없으면 "지연"**이다.
  - 최근 배치가 실패했거나, 출처 하나가 실패해 옛 데이터를 재사용했으면 "실패"다.
  - 조율 흐름은 "정상"이 아니면 매칭을 시작하지 않는다(`E-C2-STALE`). 배치가 하루 늦으면 서비스가 멈춘다.

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `status` | str | `'정상'` | `'정상'`, `'지연'`, `'실패'` — 조율 쪽 `CollectionStatus`와 같은 값 |
| `block_matching` | bool | `False` | `status`가 정상이 아니면 True |
| `reasons` | list[str] | `[]` | 지연·실패 이유 |
| `last_run_at` | str | `'2026-09-29T00:00:05+00:00'` | 마지막 저장 시각(UTC) |
| `age_hours` | float | `0.5` | 마지막 저장 후 지난 시간 |

### 4.4 `app.STATE['rows'][공고ID]` — 공고 정보 한 건
- **파일**: [search/app.py](../../search/app.py) `boot()`가 채우는 메모리 dict. 칸 목록은 `FIELDS`([search/app.py:47](../../search/app.py#L47))에 있다.
- 없는 ID면 `KeyError`가 난다. `app.STATE['rows'].get(id)`로 확인한다.

| 키 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `notice_id`, `title`, `url`, `source`, `category`, `target_category`, `region` | str | | 4.2와 같다 |
| `organizer`, `supervising_org`, `executing_org` | str 또는 None | `None`, `'부산광역시'`, `'한국반려동물산업협회'` | 주관, 소관, 수행 기관 |
| `apply_start`, `apply_end` | `datetime.date` 또는 None | `date(2026, 10, 9)` | **여기서는 날짜 객체다.** 4.2에서는 문자열이다 |
| `apply_period_type` | str | `'fixed'` | 4.2와 같다 |
| `recruitment_status` | str | `'unknown'` | `'open'`, `'closed'`, `'unknown'`. 기업마당은 모두 `'unknown'`(원문에 칸이 없음) |
| `age_condition_raw` | str 또는 None | `'예비창업자,3년미만'` | K-Startup 업력 원문. 기업마당은 None |
| `apply_url` | str | | 신청 페이지 |

**공고 요약 벡터**(`Announcement.summary_embedding`, 1024차원)를 꺼내는 곳은 두 군데다.
- 벡터 색인: `app.STATE['collection'].get(ids=[공고ID], include=['embeddings'])`.
  **벡터 DB 장애로 `STATE['collection']`이 `None`이면 쓸 수 없다.**
- 공용 DB: `SELECT embedding FROM notices WHERE notice_id=%s` → `numpy.frombuffer(값, dtype='<f4')`.
  배치가 같은 벡터를 올려 둔다(`collect/upload_vectors.py`). 벡터 DB 장애 때의 대체 경로로 쓴다.

**지원 금액, 신청서 양식, 평가 항목은 여기에 없다**(2절 ②·③).

### 4.5 `app.eligibility(req)` — 화면용 자격 확인 (G-01에 그대로 쓰지 않는다)
- **파일**: [search/app.py:813](../../search/app.py#L813), 입력 `app.GateRequest(notice_id, applicant_type, founded_at='')` ([search/app.py:333](../../search/app.py#L333))
- **하는 일**: 공고팀 시험 화면의 "자격 확인" 버튼이 쓰는 함수다. 조건 네 가지를 O/X/?로 보여 준다: 지원대상 유형, 업력, 접수기간, 모집 상태.
- **G-01에 그대로 쓰면 안 되는 이유**:
  - **접수 시작 전 공고를 "X"로 판정한다.** 매칭과 G-01(5절)은 이런 공고를 남기고 고를 수 있게 한다(2절 결정). 그대로 쓰면 추천해 놓고 고르면 막힌다.
  - 날짜 인자가 없어 실행한 날을 쓴다(`G01In.today`를 반영할 수 없음).
  - 없는 ID면 예외 대신 `JSONResponse`(404) 객체를 돌려준다.
- 대신 **확인 필요 목록과 그 이유 문장**의 재료로 쓸 수 있다(2절 ⑦ 가 방식). 다만 **조건별로 골라서** 쓴다.

  | 조건 줄 | 쓸 것 | 쓰지 않을 것 |
  |---|---|---|
  | 지원대상 유형, 업력 | `판정`이 `None`이면 확인 필요로 올린다. 이유 문장은 **`c.get('설명') or c['요구']`**로 만든다. `설명` 칸은 지원대상 유형 줄에만 항상 있다. 업력 줄에는 근거가 있을 때만 있다(공고문 업력 근거 또는 본문 예비창업자 근거, [search/app.py:844-870](../../search/app.py#L844)). `c['설명']`으로 바로 꺼내면 대부분의 업력 줄에서 `KeyError`가 난다 | — |
  | 모집 상태 | `판정`이 `None`이면 확인 필요로 올린다(기업마당은 모두 `None`). 이 줄에는 `설명` 칸이 **없다**. 이유는 `c['요구']`("모집 상태 정보 없음")를 쓴다 | — |
  | **접수기간** | **쓰지 않는다.** 시작 전 공고는 따로 **"접수 예정 (시작일 YYYY-MM-DD)"**로 표시한다. 판단 기준: `start = app.STATE['rows'][id]['apply_start']`로 꺼낸 뒤 **`start is not None and start > 오늘`**이면 접수 예정이다. **시작일이 없는 공고 985건**(모두 마감일도 없음: 예산 소진·상시·선착순·정보 없음)은 접수 예정이 아니다. 이 공고들은 ①처럼 `apply_period_type`으로 "예산 소진 시까지" 등을 표시한다. `None`을 확인하지 않고 비교하면 `TypeError`가 난다. G-01 안에서 계산하면 `오늘`은 `inp.today`를 쓴다 | 이 줄의 `X`와 `설명`. 고를 수 있게 한 결정(2절)과 **모순되는 안내**가 된다 |

  - 2026-09-29 확인: 고를 수 있는 공고에서 이 함수가 `X`를 준 경우는 **접수기간 줄뿐**이었다. 예비창업자 17건, 사업자 21건이고, 모두 접수 시작 전 공고다.
  - 이 함수로 합격/불합격을 정하지 않는다. 그것은 5절 `g01()`이 정한다.

```python
res = app.eligibility(app.GateRequest(notice_id='bizinfo:PBLN_000000000126505', applicant_type='예비창업자'))
res['marks']   # {'지원대상 유형': 'O', '업력': 'O', '접수기간': 'O', '모집 상태': '?'}
res['checks'][0]['설명']   # '근거: "전국의 예비창업자(개인·팀) 또는 창업 10년 미만 기업(개인·법인)"'

# 확인 필요 목록 (2절 ⑦ 가 방식) — 접수기간 줄은 빼고, 설명이 없으면 요구 문구를 쓴다
unknown = [(c['조건'], c.get('설명') or c['요구'])
           for c in res['checks'] if c['판정'] is None and c['조건'] != '접수기간']
# 이 공고는 [('모집 상태', '모집 상태 정보 없음')]
```

---

## 5. 조율 규격에 끼우는 예시 (2026-09-29 실행 확인)

[experiments/orchestration_probe.py](../../experiments/orchestration_probe.py)가 **이 코드 블록을 그대로 꺼내** 확인한다.

| 확인 | 결과 |
|---|---|
| A | T-C2 `offset` 0·10 각 10건(순위 1~10, 11~20)이 조율 쪽 `TC2Out` 검사를 통과. 수집 상태가 "지연"이면(대역): 첫 조회(offset 0)는 추천을 부르지 않고 빈 카드 + "지연"을 돌려줌, 더 보기(offset 10)는 카드를 그대로 줌 |
| B | G-01 결과가 매칭 1단계(`app.eligible_with_types`, 마감 제외)와 공고 2,525건 × 신청자 5가지 경우에서 **전부 같음**. 5가지: 예비창업자 / 개인사업자 2025-03 설립 / 법인 2019-01 설립 / 법인 2024-12 설립 / 개인사업자 설립일 없음 |
| C | 조율 쪽 `build_stub_app()`에 `registry.bind`로 끼워 `start_run` → 더 보기 → 선택 → G-01 → "계획서작성"까지 감. 여섯 가지를 검사한다: 첫 조회 1~10위, 더 보기 **새 결과 저장**, 11~20위, 더 보기 실패 알림(`X-C2-FAIL`) 없음, G-01 통과, 계획서작성 진입. **C′**는 더 보기에 시간 초과를 일부러 넣어, 이 검사가 실패를 **실패로 잡는지** 확인한다. **단, 공고 공급의 양식·평가 항목·금액은 스텁 값이다**(2절 ③) |
| D | 1절 "빠른 시작" 코드가 그대로 실행됨. 대역으로 두 경로도 확인: 수집 상태 "지연"이면 추천을 부르지 않고 `('지연', [])`, 추천 0건이면 오류 없이 `('정상', [])` |

⚠ 표시가 붙은 값은 합의 전의 임시값이다(①② 2절, ⑤ 6절).

```python
from datetime import date
from sbrain.contracts import tasks as c
from sbrain.models.domain import AnnouncementCard, EligibilityRule, GateResult
from search import app, gate, collection_status, applicant_types as types_mod

PRE = '예비창업자'
SOURCE_NAME = {'kstartup': 'K-Startup', 'bizinfo': '기업마당'}


def collection_status_now() -> str:
    conn = app._connect()                     # boot 와 같은 접속 정보 (Linux 의 ec2/.env 포함, 3.2)
    try:
        return collection_status.check(connection=conn)['status']
    finally:
        conn.close()


def tc2(inp: c.TC2In, tools) -> c.TC2Out:
    it, co = inp.item_spec, inp.company_info
    idea = '. '.join([it.item_name, it.one_line_summary, '목표 고객: ' + it.target_customer,
                      '핵심 기능: ' + ', '.join(it.core_features), '키워드: ' + ', '.join(it.keywords)])
    req = app.MatchRequest(
        applicant_type=co.applicant_type,
        founded_at=co.founded_at.isoformat() if co.founded_at else '',
        idea=idea, region=co.region if co.region in app.region_mod.REGIONS else '',
        gender=co.gender, certifications=co.certifications or [], first_startup=co.is_first_startup,
        top=min(inp.top_k, 10), offset=inp.offset)     # 카드 최대 10건 · rank 1~20 (4.2)
    status = collection_status_now()
    if inp.offset == 0 and status != '정상':   # 첫 조회만: 조율 흐름이 E-C2-STALE 로 멈춘다(service.py:103)
        return c.TC2Out(candidates=[], collection_status=status, filtered_count=0, fallback_used=False)
    # 더 보기(offset 10)에서는 빈 카드를 주지 않는다. 조율 흐름이 더 보기 뒤에는 수집 상태를 보지 않아서
    # (sbrain_flow.py:196) 안내 없이 0건이 되고 '더 보기' 기회만 사라진다(service.py:120). 첫 조회와 같은 메모리 공고라 그대로 준다
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
    G01In 에 공고 ID 가 없어서, 공고팀 판정을 미리 EligibilityRule 로 바꿔 둔다."""
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
    """확실히 안 되는 경우만 불합격. 모름·입력 누락(설립일 없음)은 통과, 접수기간은 보지 않는다(2절)."""
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
#                                          eligibility_parsed=eligibility_of(aid)[1], ...)   # 나머지 칸은 2절 합의 후
```

---

## 6. 그 밖의 합의 사항

2절 ①②③⑦이 가장 급하다. 아래는 그다음이다. 번호로 답해 주면 된다.

| # | 사항 | 공고팀 데이터 현황 | 공고팀 제안 |
|---|---|---|---|
| ④ | `support_field`가 "창업(06)"과 "기술개발(02)" 두 값만 허용한다 | 기업마당 8개 분야(경영, 기술, 수출, 금융, 인력, 내수, 창업, 기타)와 K-Startup 분류를 전부 수집한다 | 값 범위를 넓히거나 `str`로 바꾸기 |
| ⑤ | 카드의 `match_reason`(추천 이유) | 결과에 이유 문장이 없다. 재료는 있다: `region_match`, `rules`, `fit_score` | 조율 쪽이 재료로 짧은 문장을 만들기. 공고팀이 문장을 추가해 주기를 원하면 알려 달라 |
| ⑥ | 공고의 `status`가 "모집중"/"마감" 두 값뿐이다 | 모집 상태 모름 **2,086건**(기업마당은 칸이 없음) | 모르면 "모집중"으로 두기. 마감이 지난 공고는 추천에서 이미 빠진다. ⑦의 확인 필요 표시와 함께 쓰기 |
| ⑧ | 수집 상태가 "지연"이어도 매칭 전체가 멈춘다. 반대로 **더 보기**에서는 수집 상태를 보지 않는다 | 배치가 하루 늦으면 서비스가 멈춘다. 첫 조회 뒤 상태가 바뀌어도 더 보기는 그대로 진행된다([sbrain_flow.py:196](../../../agent-orchestration/sbrain/flow/sbrain_flow.py)) | 기능정의서 R-3(24시간)을 따른다. 알고만 있어 달라. 공고팀 예시는 더 보기에서 빈 카드를 주지 않는다(5절). 더 보기에서도 막아야 한다고 보면, 조율 흐름이 MORE 구간 끝에서 수집 상태를 보고 `E-C2-STALE`을 알리고 `more_used`를 되돌려야 한다 |
| ⑨ | `CompanyInfo.region` 값 | 공고팀은 4.2의 16개 값만 읽는다 | 같은 목록을 쓰기. 다른 값이면 지역 순위 조정이 꺼진다 |
| ⑩ | `G01In`에 공고 ID가 없다 | 그래서 5절은 공고 공급 단계에서 `eligibility_of()`로 미리 변환한다 | 공고 ID를 넣어 준다(2절 ⑦ **가** 방식과 같은 변경). **바꿀 곳은 두 군데다**: `G01In` 모델에 `announcement_id` 칸, G-01 입력 연결([catalog.py:55-58](../../../agent-orchestration/sbrain/flow/catalog.py))에 선택 공고의 ID. 그다음은 둘 중 하나를 고른다.<br>**(ㄱ) 확인 필요 목록만 추가**(작은 변경): `eligibility`·`eligibility_parsed`는 지금처럼 필수로 두고, 공고 공급의 `eligibility_of()`도 **그대로 둔다**. G-01은 공고 ID로 `app.eligibility()`를 불러 확인 필요 목록만 만든다.<br>**(ㄴ) 공고 공급까지 단순화**: 위 두 칸을 `Announcement`와 `G01In`에서 선택으로 바꾸거나 빼고, 입력 연결에서도 뺀다. 그 뒤 G-01 안에서 `eligibility_of(공고ID)`로 합격/불합격을 정한다.<br>**공고 ID 칸만 추가하고 공급 단계의 `eligibility_of()`를 없애면 필수 칸이 비어 실패한다.** 어느 쪽이든 **합격/불합격을 `app.eligibility()`로 정하지는 않는다**(4.5) |
| ⑪ | 벡터 DB 장애 때 `summary_embedding` | 벡터 색인이 없으면 꺼낼 수 없다 | 공용 DB `notices.embedding`에서 읽기(4.4). 또는 이 칸을 선택으로 바꾸기 |
| ⑫ | 입력 칸 변환 | `industry_code`(예: `J62`)는 공고팀이 쓰는 업종 **이름**이 아니다. `hiring_plan`은 조율 쪽 str ↔ 공고팀 bool. `TC2In.today`는 반영되지 않는다(4.2) | 업종 코드 → 이름 변환은 조율 쪽 입력 단계에서 하기(업종 순위는 현재 꺼져 있어 영향 작음). `hiring_plan`은 "없음"·빈 값이 아니면 True처럼 규칙을 정하기 |

---

## 7. 운영 정보와 문의

- **매일 09:00 배치**(공고팀 PC, 약 12분): 수집 → 임베딩 → 벡터·첨부 업로드 → 판정 추출 → 공용 DB 올리기. 2026-09-29 기준 공고 2,525건이다.
- 이 문서의 함수 이름이나 입출력 칸을 바꾸게 되면 **이 문서를 먼저 고치고 알린다.**
- 확인하는 법(공고팀·검수용):
  ```powershell
  # data-collection 폴더에서. 조율 코드는 저장소 루트 agent-orchestration/ 에 있다(main 머지본, deb5c81 과 같다)
  .\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration
  ```
  - `.venv`가 실행되지 않으면 그 PC에서 가상환경을 새로 만든다(3.1). 공용 DB 접속 정보(`.env`)와 메모리 약 2GB가 필요하다.
- 문의: 이근준(공고팀).

## 개정 기록

- **2026-09-29 4차 개정** ([Codex 3차 재검수](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK3_20260929.md) 반영)
  - ⑦ 가·⑩: 공고 ID는 `G01In` 모델과 G-01 입력 연결(`catalog.py:55-58`) **두 곳**을 바꿔야 한다고 적었다. (ㄱ) 확인 필요 목록만 추가 — `eligibility_of()` 유지, (ㄴ) 공급까지 단순화 — 두 필수 칸도 바꿈으로 나눴다.
  - ⑦: 화면 상태 `RunView`에 G-01 결과가 없으니 표시 경로도 함께 정하자고 적었다.
- **2026-09-29 3차 개정** ([Codex 2차 재검수](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_20260929.md) 반영)
  - ① 마감 형태 `apply_period_type`을 `Announcement`·`AnnouncementCard` **두 모델에 새 칸으로** 추가하는 계약을 적었다(값 목록·공고팀 출처·카드와 상세 둘 다 표시).
  - ⑦ 확인 필요를 조건 이름만 줄지 이유까지 줄지 정하도록 했다(이유까지 권장, `{condition, reason}` 목록).
  - 3.1·7절에 `.venv`는 PC마다 새로 만든다는 안내를 넣었다.
  - 검증 스크립트: C가 더 보기 **새 결과(11~20위) 저장과 실패 알림 없음**까지 검사하고, C′(더 보기 시간 초과 주입)로 그 검사가 실패를 잡는지 확인한다. A는 순위를 정확히 검사한다. D는 계약 검사와 오늘 데이터 참고 출력을 나눴다.
- **2026-09-29 2차 개정** ([Codex 재검수](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_20260929.md) P2 반영)
  - 빠른 시작을 `recommend()`로 바꿨다. 수집 상태가 "정상"이 아니면 추천하지 않고, 0건이면 안내만 한다. 5절 `tc2()`도 같은 분기를 넣었다.
  - ⑦에 "확인 필요 목록을 어디서 만드나"(가·나 방식, 가 권장)와 규모(예비창업자 94%, 사업자 100%)를 넣었다.
  - 4.5에 조건 줄별 재사용 범위를 적었다. 접수기간 줄은 쓰지 않고 "접수 예정"으로 따로 표시한다.
  - ①에 `AnnouncementCard.apply_end`와 스텁 T-C3·G-03의 `isoformat()`을 추가했다. 3.3에 재시작 방식별 메모리 조건을 적었다.
  - 공고팀 내부 교차 검토(Claude 보조 에이전트 16개, 지적 13건 중 반박을 견딘 8건 = 실제 6건)를 반영했다.
    - "접수 예정" 판단식에 `None` 확인을 넣었다(시작일 없는 985건에서 `TypeError`).
    - 확인 필요 이유는 `c.get('설명') or c['요구']`로 쓴다(업력·모집 상태 줄에 `설명` 칸이 없는 경우가 많음).
    - `tc2()`의 수집 상태 분기를 **첫 조회에만** 적용했다. 더 보기에서 빈 카드를 주면 조율 흐름이 안내 없이 0건을 보여 주고 더 보기 기회만 사라진다. ⑧에도 적었다.
    - 확인하는 법을 저장소 안 `..\agent-orchestration`으로 바꿨다(SB-86 브랜치는 머지 후 삭제). 절 번호 참조를 바로잡았다.
- **2026-09-29 개정** ([Codex 검수](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_20260929.md) 반영)
  - 맨 앞을 "빠른 시작" 코드로 바꿨다.
  - "연결 전에 꼭 합의할 것"(①②③⑦)을 앞으로 옮겼다.
  - 수집 상태는 `app._connect()` 연결을 넘기도록 고쳤다(Linux `ec2/.env` 문제).
  - 합의 ⑩의 "`app.eligibility()` 한 줄로 끝난다" 권고를 **철회**했다. 그 함수는 접수 시작 전 공고를 막아 매칭과 어긋난다.
  - "접수 시작 전 공고는 고를 수 있다" 결정, 벡터 대체 경로(⑪), 입력 변환(⑫), 운영 주의(재시작·동시 호출·알려진 시작 실패)를 추가했다.
  - T-C2 예시에 `top` 10 상한을 넣었다.
- 2026-09-29 첫판: 커밋 `aac4093`.
