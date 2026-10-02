# 공고 판정 테이블 — 신청자 유형 · 업종 (2026-09-28)

공용 MySQL(`s_brain`)에 새 테이블 두 개를 추가한다. SQL: [`db/mysql_migration_006_notice_judgments.sql`](../../db/mysql_migration_006_notice_judgments.sql)

## 1. 왜 만드나

공고 API는 "누가 신청할 수 있나"를 칸으로 주지 않는다. 예비창업자 가능 여부, 신청 가능 업종 같은 조건은 공고문 본문에 문장으로만 있다. 그래서 LLM(gpt-5.6-luna)이 공고문을 읽고 **근거 문장과 함께** 판정해 두었다.

지금은 이 판정이 **배치를 돌리는 PC의 파일에만** 있어서 팀원이나 EC2 서비스가 쓸 수 없다. 벡터를 공용 DB로 올리는 것(배치 8단계)과 같은 방식으로, 판정도 공용 DB에 올려 누구나 SQL로 읽게 한다.

| 판정 | 지금 있는 곳 | 올릴 테이블 |
|---|---|---|
| 신청자 유형 (예비창업자·개인사업자·법인) | `data/applicant_types/results.jsonl` (배치 11단계가 매일 갱신) | **`notice_applicant_types`** (새로) |
| 업종 | `reports/industry_llm_full_luna_20260928_final6/results.jsonl` | **`notice_industries`** (새로) |
| 업력 (luna 재추출분) | `reports/age_rerun_luna_20260928T054509Z/results.jsonl` | 기존 `notice_conditions`에 반영(별도 작업 C-3) |

## 2. 원칙

- **기존 테이블의 구조(스키마)는 건드리지 않는다.** `notices`·`notice_conditions`에 칸을 더하지 않는다. 기존 코드에 영향이 없다.
  단, 업력은 기존 `notice_conditions`의 **값**을 고친 적이 있다(2026-09-28 luna 재추출 78행, 7절).
- 한 공고에 한 행이다(`notice_id`가 기본 키). 공고가 지워지면 판정도 지워진다(외래 키 `ON DELETE CASCADE`).
- **쓰는 쪽은 배치 PC 하나.** 배치 13단계(예정)가 바뀐 행만 올린다(`document_sha256`으로 판단). 팀원은 읽기만 한다.
- 모든 값에 **근거 문장**이 함께 있다. 화면에 값을 보여 줄 때 근거도 함께 보여 주는 것을 권장한다.
- **LLM 판정이고 사람이 검증하지 않았다.** 매칭에서 "빼기"에 써도 되는 값은 아래 표에 따로 적었다.

## 3. `notice_applicant_types` — 신청자 유형

| 칸 | 뜻 | 쓰는 법 |
|---|---|---|
| `pre_founder_verdict` | 예비창업자 신청자에 대한 **서비스의 결론** | `blocked`는 빼도 된다(명시적 불가, Codex 판정 30/30. 현재 `varies=1`인 blocked 는 0건). `allowed`는 **`varies=0`일 때만** "신청 가능"이다 — `varies=1`인 allowed 23건은 일부 세부사업만 받으므로 "확인 필요"로 다룬다(서비스와 같다). `implied_no`는 뒤로만 보낸다(추정). `NULL`은 모름 |
| `varies` | 세부사업마다 대상이 다름 | TRUE면 공고 전체를 한 값으로 판정하지 않는다(예: "예비창업자(장인대학 운영사업에 한함)") |
| `registered_only_phrase` | "사업자 미등록 업체 제외" 같은 등록 사업자 전용 표현 | `implied_no`로 올린 이유 |
| `pre_founder_status` · `_strength` · `_evidence` | LLM이 읽은 예비창업자 값, 근거 강도, 근거 문장 | status: `allowed`·`not_allowed`·`implied_no`·`not_mentioned`, strength: `strong`·`weak` |
| `sole_proprietor_*` · `corporation_*` | 개인사업자·법인 값 | **매칭에 쓰지 않는다.** 참고 표시만(적용 범위 오판 위험) |
| `reason` | LLM이 적은 판단 이유 | 설명용 |
| `document_sha256` · `prompt_sha256` · `extractor_version` | 무엇을 어떤 추출기로 읽었나 | 다시 추출할지 판단 |

예: 예비창업자가 신청할 수 없는 공고를 빼고 검색하기

```sql
SELECT n.notice_id, n.title
  FROM notices n
  LEFT JOIN notice_applicant_types t ON t.notice_id = n.notice_id
 WHERE COALESCE(t.pre_founder_verdict, '') <> 'blocked';
```

예: 예비창업자가 **확실히** 신청할 수 있는 공고(세부사업별 공고 제외)

```sql
SELECT notice_id FROM notice_applicant_types
 WHERE pre_founder_verdict = 'allowed' AND varies = 0;
```

## 4. `notice_industries` — 업종

| 칸 | 뜻 | 쓰는 법 |
|---|---|---|
| `status` | 코드 검사 뒤 결론: `known`(허용 업종 확인) 830 · `not_mentioned`(언급 없음) 1,088 · `excluded_only`(제외 업종만) 287 · `unknown`(판단 불가) 240 · `conditional`(조건부) 26 · `no_limit`(업종 무관 명시) 5 — final6 기준 | `known`이 아닌 공고를 빼면 안 된다(대부분 업종 제한이 없거나 모름) |
| `allowed_sections` | 허용 업종을 KSIC 대분류(A~U)로 묶은 배열. 예: `["C","J"]` | **`usable_for_rank=1`인 행만** 신청자 업종과 비교한다. 값이 있어도 `usable_for_rank=0`인 행이 200건 있다(목록 불완전·잘림·세부사업 갈래 문제). `NULL`이면 묶을 수 없음. **업종으로 공고를 빼지 않는다** |
| `usable_for_rank` | 순위 신호로 써도 되는 행(목록 완전·잘림 없음·갈래 문제 없음) | 2,476건 중 217건. **업종 순위는 현재 기본 꺼짐**(부당 밀림 11/34) — 빼기에는 쓰지 않는다 |
| `allowed` · `excluded` | 허용·제외 업종 배열 `[{"text","label","evidence"}]` | 원문 표현 그대로와 근거 |
| `list_complete` · `truncated` · `scope_unresolved` | 목록이 전부인가, 발췌가 잘렸나, 어느 세부사업 조건인지 모름 | 하나라도 걸리면 조심해서 쓴다 |
| `quote` · `quote_role` | 신청 자격 근거 문장과 그 역할 | 표시용 |
| `excerpt_chars` · `verify_profile` · `source_run` | 발췌 길이, 검사 강도, 결과 폴더 | 추적용 |

`allowed_sections`·`usable_for_rank`는 **올릴 때의 코드 규칙**(`industry_groups.py`·`industry_rank.py`)으로 계산한 값이다. 규칙이 바뀌면 다시 올린다.

## 5. 갱신 흐름 (예정)

```
[배치 PC] 매일 09:00
   11단계 신청자 유형 추출 ─→ data/applicant_types/results.jsonl
   12단계 업종 추출        ─→ data/industries/results.jsonl
   13단계 공용 DB 올리기      ─→ notice_applicant_types · notice_industries (바뀐 행만 UPSERT)
[팀원·EC2 서비스] SELECT 로 읽기
```

- 올리는 코드: `collect/upload_judgments.py`(`--plan`은 세기만 한다). 매일 배치 13단계가 부른다(`--skip-judgments`로 끌 수 있다).
- 업종은 매일 배치 12단계(`collect/industry_daily.py`)가 새 공고·바뀐 공고만 추출해 `data/industries/results.jsonl`에 쌓는다(시작은 final6 2,476건). 13단계가 이 파일을 올린다.

## 6. 서비스가 읽는 곳 (2026-09-28)

- **신청자 유형**만 기본으로 공용 DB를 먼저 읽는다(`APPLICANT_TYPES_SOURCE` = `auto`(기본) · `db` · `file`).
  - DB 행이 서비스 공고 수의 95% 미만이면 업로드가 덜 끝난 것으로 보고 파일을 쓴다(파일이 없으면 DB를 쓰되 알린다).
  - 파일이 있는 곳(배치 PC)에서는 공고마다 문서 해시를 비교해, DB 값이 옛것이면 파일 값을 쓴다(13단계가 실패한 날 옛 `blocked` 방지).
  - `db`로 강제했는데 연결이 안 되면 파일로 넘어가지 않고 기능을 끈다.
- **업종**은 기본이 파일(final5)이다(`INDUSTRY_SOURCE` = `file`(기본) · `auto` · `db`). Codex 검수에서 DB 전환은 아직 승인되지 않았다(부당 밀림 11/34 사람 판정 필요). 파일이 없는 곳에서는 업종 순위가 꺼진다.
- DB에서 읽은 값과 파일에서 읽은 값은 2,476건 모두 같다(서비스 결론 차이 0건, 업종 순위 공고 217건 동일, 2026-09-28 확인). 파일이 없는 곳(EC2·팀원 PC)에서도 신청자 유형은 같은 판정으로 매칭할 수 있다.
- 서버는 시작할 때 한 번 읽는다. 배치 뒤 서버를 다시 켜야 새 판정이 반영된다.
- **알려진 한계**: `pre_founder_verdict`·`allowed_sections`·`usable_for_rank`는 올린 때의 코드 규칙으로 계산한 값이고, 규칙 버전 칸이 없다(`extractor_version`은 모델·프롬프트만). 규칙을 바꾸면 13단계가 다시 올리지만, 그 전까지 SQL 사용자는 옛 규칙 값을 본다. 업로드 세대·규칙 버전을 기록할 작은 표(예: `judgment_uploads`)를 제안해 두었다(미생성).

## 7. 만든 기록

- 2026-09-28: 사용자 결정(A — 새 테이블 두 개). 설계·SQL 작성, 테이블 생성.
- 2026-09-28: 사용자 확인 뒤 첫 업로드. `notice_applicant_types` 2,476행, `notice_industries` 2,476행. 다시 센 결과 같음 2,476·올릴 것 0. 매일 배치 13단계에 연결했다.
