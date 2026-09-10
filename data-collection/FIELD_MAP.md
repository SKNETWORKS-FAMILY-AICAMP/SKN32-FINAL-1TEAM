# API 필드 → DB 컬럼 대응표

두 오픈API 가 주는 필드를 `notices` 테이블의 어느 컬럼에 넣는지 정리했습니다.
변환은 전부 [`normalize.py`](normalize.py) 가 합니다.

**두 API 의 필드 이름이 완전히 다릅니다.** 같은 뜻인데 이름만 다른 것,
한쪽만 주는 것, 양쪽 다 안 주는 것이 섞여 있습니다.

```
K-Startup   30개 필드   창업진흥원 · 공공데이터포털
기업마당     22개 필드   중소벤처기업부
```

---

## 대응표

`—` 는 그 API 가 주지 않는다는 뜻입니다.

| DB 컬럼 | K-Startup | 기업마당 | 비고 |
|---|---|---|---|
| `notice_id` | — | — | `source:source_id` 로 우리가 만든다 |
| `source` | — | — | `kstartup` / `bizinfo` |
| `source_id` | `pbanc_sn` | `pblancId` | 출처가 준 고유 번호 |
| `title` | `biz_pbanc_nm` | `pblancNm` | |
| `body` | `pbanc_ctnt` | `bsnsSumryCn` | HTML 태그를 지운다 |
| `target_text` | `aply_trgt_ctnt` | **—** | 지원대상 서술 원문 |
| `target_category` | `aply_trgt` | `trgetNm` | **뜻이 다르다.** 아래 참조 |
| `exclude_text` | `aply_excl_trgt_ctnt` | **—** | 제외대상. 60건 중 34건에만 값이 있다 |
| `age_condition_raw` | `biz_enyy` | **—** | 업력 조건 |
| `region` | `supt_regin` | **—** | 지원 지역 |
| `category` | `supt_biz_clsfc` | `pldirSportRealmLclasCodeNm` | 분야 대분류 |
| `subcategory` | **—** | `pldirSportRealmMlsfcCodeNm` | 분야 중분류 |
| `organizer` | `pbanc_ntrp_nm` | **—** | 주관기관 |
| `supervising_org` | **—** | `jrsdInsttNm` | 소관기관 |
| `executing_org` | **—** | `excInsttNm` | 수행기관 |
| `apply_start` | `pbanc_rcpt_bgng_dt` | `reqstBeginEndDe` 앞부분 | 아래 「날짜」 참조 |
| `apply_end` | `pbanc_rcpt_end_dt` | `reqstBeginEndDe` 뒷부분 | |
| `apply_period_raw` | 위 두 값을 그대로 | `reqstBeginEndDe` 원문 | 해석 전 원본 |
| `apply_period_type` | — | — | 우리가 판정한다. 5종 |
| `recruitment_status` | `rcrt_prgs_yn` | **—** | `Y`→`open`, `N`→`closed` |
| `url` | `detl_pg_url` | `pblancUrl` | 공고 상세 페이지 |
| `apply_url` | `biz_aply_url` | `rceptEngnHmpgUrl` | K-Startup 은 값이 늘 비어 있다 |
| `source_updated_at_raw` | **—** | `updtPnttm` | 첨부 재수집 판별에 쓴다 |
| `target_text_status` | — | — | 우리가 만든 표시. `available`/`not_available` |
| `attachment_discovery_status` | — | — | `pending_crawl` / `api_links_available` |
| `issues` | — | — | 정규화 중 생긴 경고 목록 |
| `raw` | 응답 전체 | 응답 전체 | 원본을 통째로 보관 |
| `snapshot_at` | — | — | 수집 시각 |
| `last_import_id` | — | — | 어느 실행이 넣었나 |

### 첨부 (`notice_attachments`)

| 컬럼 | K-Startup | 기업마당 |
|---|---|---|
| `url` (공고문) | **—** | `printFlpthNm` |
| `name` (공고문) | **—** | `printFileNm` |
| `url` (신청서식) | **—** | `flpthNm` |
| `name` (신청서식) | **—** | `fileNm` |

**K-Startup API 는 첨부 주소를 전혀 주지 않습니다.** 상세 페이지를 크롤링해야 나오는데,
`robots.txt` 가 그 경로를 막고 있어 보류 중입니다. 그래서
`attachment_discovery_status` 가 `pending_crawl` 로 남아 있습니다.

기업마당은 신청서식(`flpthNm`)이 60건 중 22건에만 있습니다.

---

## 판정에 쓰는 컬럼이 한쪽에 몰려 있습니다

실제 채워진 비율입니다.

| 컬럼 | K-Startup | 기업마당 |
|---|---|---|
| `target_text` | 100% | **0%** |
| `age_condition_raw` | 100% | **0%** |
| `region` | 100% | **0%** |
| `exclude_text` | 41% | **0%** |
| `apply_start` · `apply_end` | 100% | **43%** |
| `subcategory` | **0%** | 100% |
| `executing_org` | **0%** | 100% |

**자격 판정에 쓰는 네 컬럼을 기업마당이 하나도 주지 않습니다.**
그런데 기업마당이 전체 공고의 83%입니다.

이것이 첨부 공고문(PDF·HWP)에서 본문을 뽑는 이유입니다.
API 에 없는 조건이 그 안에 적혀 있습니다.

---

## 같은 컬럼인데 뜻이 다른 것 — `target_category`

두 API 가 「지원대상」이라는 같은 이름으로 **다른 축**을 줍니다.

```
K-Startup  aply_trgt   누구인가
           청소년 · 대학생 · 일반인 · 대학 · 연구기관 · 일반기업 · 1인 창조기업

기업마당    trgetNm     어떤 기업인가
           중소기업 · 소상공인 · 창업벤처 · 사회적기업 · 장애인기업 · 여성기업
```

**섞어서 비교하면 안 됩니다.** 그리고 K-Startup 쪽은 266건 중 119건(44.7%)이
위 일곱 개를 전부 나열하고 있어 **사실상 「아무나」** 라는 뜻입니다. 변별력이 낮습니다.

---

## 날짜 — 형식이 아예 다릅니다

```
K-Startup   pbanc_rcpt_bgng_dt  "20241203"      두 칸으로 나뉜 8자리 숫자
            pbanc_rcpt_end_dt   "20261231"

기업마당     reqstBeginEndDe     "2020.01.01 ~ 2026.12.31"   한 칸에 둘 다
                                "2025-01-02 ~ 2027-12-31"   같은 소스인데 하이픈
                                "상시 접수"                  날짜가 아예 없다
```

**같은 기업마당 안에서도 `.` 과 `-` 가 섞입니다.** 그래서 `[-./]` 로 셋 다 받고,
`~` 앞뒤를 갈라 두 칸으로 나눠 넣습니다.

날짜가 없는 문구는 버리지 않고 종류를 구분해 `apply_period_type` 에 남깁니다.

```
fixed              917    날짜 두 개를 정확히 뽑았다
budget_exhaustion  626    "예산 소진 시까지"
rolling            142    "상시 접수"
until_filled        88    "선착순"
unknown             59    형식을 읽지 못했다
```

**「마감일이 없다」와 「읽지 못했다」를 구분합니다.** 섞으면 자격 판정이 틀립니다.

---

## 받지만 쓰지 않는 필드

### K-Startup (30개 중 12개 미사용)

| 필드 | 내용 | 왜 안 쓰나 |
|---|---|---|
| `aply_mthd_*_istc` (6개) | 온라인·이메일·팩스·방문·우편·기타 접수 안내 | 신청 방법. 매칭·판정에 안 쓴다 |
| `biz_gdnc_url` | 사업 안내 페이지 | `detl_pg_url` 로 충분 |
| `biz_prch_dprt_nm` | 담당 부서 | 연락처. 화면에 노출하지 않는다 |
| `prch_cnpl_no` | 담당 전화번호 | 〃 |
| `biz_trgt_age` | 대상 연령 | 개인 연령 조건. 현재 판정에 없다 |
| `intg_pbanc_yn` · `intg_pbanc_biz_nm` | 통합공고 여부·이름 | 아직 활용 안 함 |
| `sprv_inst` | 감독기관 | 아직 활용 안 함 |
| `id` | API 내부 일련번호 | `pbanc_sn` 을 쓴다 |
| `prfn_matr` | 유의사항 | 표본 60건 전부 비어 있음 |

### 기업마당 (22개 중 6개 미사용)

| 필드 | 내용 | 왜 안 쓰나 |
|---|---|---|
| `reqstMthPapersCn` | 신청 방법·제출 서류 | 매칭·판정에 안 쓴다 |
| `refrncNm` | 문의처 | 연락처 |
| `hashtags` | 해시태그 | 아직 활용 안 함. 검색 보강에 쓸 여지는 있다 |
| `inqireCo` | 조회수 | 인기도. 추천에 쓰면 편향이 생긴다 |
| `creatPnttm` | 등록 시각 | `updtPnttm` 만 쓴다 |
| `totCnt` | 전체 건수 | 응답 메타. 행마다 같은 값이 들어 있다 |

**안 쓰는 필드도 버리지 않습니다.** `raw` 컬럼에 응답 전체가 그대로 들어 있어서
나중에 필요해지면 컬럼을 추가해 꺼낼 수 있습니다.

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw, '$.hashtags'))
FROM notices WHERE source = 'bizinfo' LIMIT 5;
```

---

## 정규화가 손보는 것

이름만 바꾸는 게 아니라 값도 다듬습니다.

```
HTML 태그 제거          문단·목록·표의 줄바꿈은 살리고 script·style 은 버린다
연속 공백을 한 칸으로     빈 줄 제거
날짜를 ISO 8601 로       YYYY-MM-DD
상대 주소를 절대 주소로   /cmm/fms/... → https://www.bizinfo.go.kr/cmm/fms/...
XML 엔티티 복원         &amp; → &
빈 문자열을 NULL 로      "값 없음" 과 "빈 값" 을 구분한다
```

마지막이 중요합니다. **빈 문자열을 그대로 두면 「조건이 없다」와 「값을 못 받았다」가 섞입니다.**

---

## 실패했을 때 — `issues`

값을 해석하지 못하면 버리지 않고 경고를 남깁니다.

```json
[{"field": "apply_period_raw", "code": "unparsed_period"}]
```

| 코드 | 뜻 |
|---|---|
| `invalid_date` | 날짜 형식을 읽지 못했다 |
| `unparsed_period` | 접수기간 문구를 날짜로 바꾸지 못했다 |
| `invalid_url` | 주소가 형식에 맞지 않는다 |

**필수 항목(공고 ID·제목)이 없을 때만 행을 거부합니다.** 나머지는 NULL 로 두고 경고를 남깁니다.

```sql
-- 경고가 붙은 공고 보기
SELECT notice_id, issues FROM notices
WHERE JSON_LENGTH(issues) > 0 LIMIT 10;
```

---

## 직접 확인해보기

```sql
-- 어느 API 원본이 들어왔는지 통째로 보기
SELECT JSON_PRETTY(raw) FROM notices WHERE source = 'kstartup' LIMIT 1;

-- 컬럼별로 얼마나 채워졌는지
SELECT source,
       COUNT(*) AS 전체,
       COUNT(target_text)       AS 지원대상,
       COUNT(age_condition_raw) AS 업력,
       COUNT(region)            AS 지역,
       COUNT(apply_end)         AS 마감일
FROM notices GROUP BY source;
```
