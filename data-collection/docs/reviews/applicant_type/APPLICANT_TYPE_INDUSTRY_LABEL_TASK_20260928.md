# Codex 판정 지시서 — 신청자 유형 · 업종 밀림 (2026-09-28)

작성: Claude · 요청: 사용자(이근준) · 수행: Codex
판정 결과는 **AI 참고 정답**이다. 사람 정답이 아니며, 문서·화면에도 그렇게 표시한다.

## 1. 왜 필요한가

LLM(gpt-5.6-luna)이 공고 2,476건에서 신청자 유형(예비창업자·개인사업자·법인)을 뽑았다(`reports/applicant_type_llm_full_20260928T023916Z/`).
업종 순위 규칙은 업종 추출 결과로 공고를 뒤로 보낸다(`reports/industry_rank_check_20260928T031858Z/`).
둘 다 매칭에 연결하기 전에 **독립 판정**으로 다음을 정해야 한다.

| 묶음 | 대상 | 건수 | 이 판정으로 정할 것 |
|---|---|---:|---|
| A | LLM "예비창업자 불가"(강한 근거, 세부사업 구분 없음) | 30 / 183 | 게이트에서 예비창업자에게 이 공고를 **빼도** 되는가. 틀리면 신청 가능한 공고가 사라진다 |
| B | K-Startup API 업력 칸은 "예비창업자 불가", LLM은 "가능" | 9 / 9 | 본문 판정을 API 칸보다 우선해도 되는가 |
| C | LLM "예비창업자 불가"(약한 근거) | 15 / 87 | 약한 근거도 쓸 수 있는가 |
| D | LLM "개인사업자 또는 법인 불가"(강한 근거) | 9 / 9 | 개인/법인 게이트를 둘 만한가(A 묶음 안의 개인/법인 판정도 함께 본다) |
| E | LLM "예비창업자 불가 추정" | 20 / 1,632 | 순위 신호로 써도 되는가 |
| F | LLM 세 유형 모두 "언급 없음" | 10 / 262 | 놓친 제한이 있는가 |
| 업종 | 업종 순위 규칙으로 서비스 상위 10에서 밀린 공고 | 34 / 34 | 그 업종 신청자가 **확실히** 신청할 수 없는가 |

## 2. 파일 (`reports/label_pack_20260928/`)

| 파일 | 내용 |
|---|---|
| `applicant_items.jsonl` | 판정할 신청자 유형 93건. `document`가 LLM이 본 것과 같은 발췌(6,000자)다(`same_document=true`). B 묶음은 `api_age_condition`도 있다 |
| `industry_items.jsonl` | 판정할 업종 34건. `asked_sections`는 이 공고 때문에 뒤로 밀린 신청자 대분류다. 발췌는 지금 출처 DB로 다시 만든 것이다(LLM이 본 9/18 스냅샷과 조금 다를 수 있다) |
| `answers_hidden.jsonl` | LLM 답. **판정을 모두 끝낸 뒤에만 연다**(블라인드) |
| `meta.json` | 표본 설계·seed |

만들어진 경위: `python -X utf8 -m experiments.sql_semantic.label_pack --out reports/label_pack_20260928` (DB 읽기만).

## 3. 신청자 유형 판정 방법

`document`의 **신청 자격 문장**(지원대상·신청자격·참여대상·지원제외 등)만 본다. 지원 내용·우대·제출서류로 판단하지 않는다.
발췌만으로 판단할 수 없으면 추측하지 말고 `not_mentioned`, `note`에 이유를 적는다.

| 값 | 뜻 | 예 |
|---|---|---|
| `allowed` | 그 유형이 신청할 수 있다고 적혀 있다 | "예비창업자 및 창업 7년 이내 기업", "개인 또는 법인사업자" |
| `not_allowed` | 그 유형은 안 된다고 **명시**돼 있다 | "사업자등록증 보유"·"사업자 미등록 업체 제외" → 예비창업자 불가. "법인사업자에 한함" → 개인사업자·예비창업자 불가 |
| `implied_no` | (예비창업자만) 대상이 이미 사업하는 기업·업체·사업장으로만 적혀 있고 예비창업자를 받는다는 말이 없다 | "도내 본사·공장이 있는 중소 제조기업" |
| `not_mentioned` | 판단할 문장이 없다 | "중소기업·소상공인"만으로는 개인/법인을 판단하지 않는다 |

세부사업·과제마다 자격이 다르면 `varies=true`로 하고, 가장 넓게 허용되는 쪽으로 적는다.

`reports/label_pack_20260928/applicant_labels.jsonl` — 한 줄에 한 건:

```json
{"item_id": "P001", "pre_founder": "not_allowed", "sole_proprietor": "allowed", "corporation": "allowed",
 "varies": false, "evidence": "원문 그대로 짧게", "note": "", "judge": "codex"}
```

## 4. 업종 판정 방법

질문: **"`asked_sections`의 업종으로 사업하는 신청자는 이 공고에 확실히 신청할 수 없는가?"**

- 원문의 신청 자격에서 **허용 대상 갈래를 모두** 적는다(`allowed_branches`, 원문 그대로). "또는", "①·②", "~의 경우", 추가 대상(농업인·소상공인·수출기업 등)을 빠뜨리지 않는다.
- 대분류마다 판정한다.
  - `ineligible`: 그 업종 신청자는 어느 갈래에도 해당하지 않는다(맞게 밀림).
  - `eligible`: 어느 갈래로든 신청할 수 있다(**잘못 밀림**).
  - `unclear`: 발췌로 판단할 수 없다.
- 업종 제한 자체가 없다고 보면 `restricted=false`로 하고, 모든 대분류를 `eligible`로 둔다.

대분류 코드: A 농업·임업·어업, C 제조업, F 건설업, G 도매·소매, I 숙박·음식점, J 정보통신, N 사업지원·임대(여행 포함), 그 밖은 KSIC 대분류.

`reports/label_pack_20260928/industry_labels.jsonl` — 한 줄에 한 건:

```json
{"item_id": "I001", "restricted": true, "allowed_branches": ["원문 갈래 1", "원문 갈래 2"],
 "sections": [{"code": "I", "verdict": "ineligible"}, {"code": "G", "verdict": "eligible"}],
 "evidence": "원문 그대로", "note": "", "judge": "codex"}
```

## 5. 끝난 뒤

1. 두 판정 파일을 모두 쓴 뒤 채점한다(표준 라이브러리만 쓰므로 `.venv` 없이 돈다).
   `python -X utf8 experiments/sql_semantic/label_score.py reports/label_pack_20260928`
   → 같은 폴더에 `score.md`·`score.json`
2. `answers_hidden.jsonl`과 대조해 LLM이 틀린 유형(예: 제출서류를 자격으로 읽음, 조건문을 전체 대상으로 읽음)을 정리한다.
3. 결과 문서를 **이 폴더**에 `APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md`로 남긴다. 들어갈 것은 다음과 같다.
   - 묶음별 수치
   - 게이트에 써도 되는 조건에 대한 의견
   - 업종의 잘못 밀림 목록
4. 판정 파일은 결과 폴더에만 쓴다. 코드·DB는 고치지 않는다. Git 스테이징·커밋·push는 하지 않는다.

## 6. 읽기만 할 것

- LLM 프롬프트와 검사: `experiments/sql_semantic/applicant_type_llm.py`(SYSTEM, verify)
- 업종 순위 규칙: `search/industry_rank.py`(branch_problem, usable_sections)
- 판정 결과를 받아 Claude가 할 일: 신청자 유형 게이트 연결(명시 불가만 필터, 추정은 순위, 본문 가능이 API보다 우선)과 업종 순위 안전성 판단.
