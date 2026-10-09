# 공용 작업 이력

현재 상태는 [STATUS.md](STATUS.md), 공통 절차는 [AGENTS.md](../AGENTS.md)를 참조한다.
새 기록은 아래 **작업 기록** 제목 바로 아래에 최신순으로 추가한다.
같은 날 여러 작업이면 구별되는 제목을 쓰고, 이전 기록을 정정할 때는 대상 항목을 명시한다.

## 기록 양식

```markdown
### YYYY-MM-DD · 담당 AI/작업자 · 작업명

- 요청·목적:
- 작업 전 상태: 기존 수정이나 관련 문제
- 변경 파일: 경로와 변경한 역할
- 전후 차이·선택 이유: 같은 입력에서 무엇이 달라지는지, 왜 이 방법인지
- 검증: 실행 명령·조건·결과·결과 파일. 실행하지 않았다면 이유
- 미검증·남은 문제:
- 다음 단계:
```

날짜는 한국 시간 기준으로 적는다. 수치에는 측정 조건과 근거를 붙인다.
과거 작업을 새로 수행한 것처럼 기록하지 않는다. 비밀정보와 개인정보는 적지 않는다.

## 작업 기록

### 2026-10-08 · Claude · 가산점 계산 완화·Codex 6차 조이기·목록 27건(결정 0020)

- 요청·목적: 사용자 "가점 너무 빡빡하게 안 해도 될 것 같다" — A 4가지(메모 범위·"경우"·같은 숫자 반복·한 문장 속 여러 점수) + "각 N점"을 풀고, Codex 6차 P2 두 곳을 조인다. 늘어난 공고는 원문 대조 뒤 목록 추가. 서버 반영은 0019와 함께 한 번에.
- 작업 전 상태: 결정 0019 코드(시험 서버 미반영). 고치기 전 사본 `bonus.py`·`bonus_reviewed.json`을 세션 임시 폴더 `pre0020/`에.
- 변경 파일: `search/bonus.py`(상수 `MEMO_GLOBAL_WORDS`·`_MEMO_TARGET`·`_CLAUSE_VERBS`·`_CLAUSE_BOUNDARY`·`_NO_ZERO_BEFORE`·`_SERIAL_BEFORE`·`_LABEL_FILLER`·`_LABEL_JOIN`·`_HEADER_PARTICLE`, 함수 `memo_is_global`·`condition_words_hit`·`_qualification_clause`·`qualification_words`·`bare_numbers`·`quote_mates`, `score_header`·`table_mates`·`points_owned`·`points_supported`·`_table_cell`·`item_hit`·`_joined_hits`·`_score_scope`·`_score` 수정, 머리 설명), `search/bonus_reviewed.json`(6건 추가), `tests/test_bonus.py`(`Relax0020Tests` 7개, 기존 기대값 그대로), 문서: 결정 0020·목록·0019 한 줄, `business-rules.md` 9절, `search/AGENTS.md`, Codex 7차 요청서, 인계서 ⑱, `tracking/status.md`, AGENTS=CLAUDE(0020까지), R6-P3-1 정정(`reports/bonus_boostable_20261008T073942Z/README.md`).
- 검증: 시험 965개 중 949 통과·16 건너뜀·실패 0(마지막 점검(10/8) 보완 — 메모 대상 판정을 좁힘(일반 말만 가리키는 "가점 항목 일부 누락"·"'우대' 조건"·"⑱ 근거가 끊김"은 전체 메모, "⑮·⑯ 항목"처럼 번호로 집은 항목은 대상), R4 조각에 자격 말 밖의 말("법인")이 남으면 인정 안 함, "배점⏎다음 줄" 조사 오판 수정 — 다시 잰 값 같음(`reports/bonus_boostable_20261008T090430Z/`·`reports/bonus_conservative_20261008T090548Z/`), 124300 계산은 8 → 5(여전히 아님)). `-m eval.bonus_boostable --old <pre0020>`: 같음 757·모름→양수 43·그 밖 0, 목록 21건 그대로, 양수 공고 29(`reports/bonus_boostable_20261008T084903Z/`). `-m eval.bonus_conservative_compare --old`: 모름→양수만 +4·+4(`reports/bonus_conservative_20261008T085037Z/`). 구현 중 "소재 기업"이 "재기"로 읽히던 문제(119727 양수→모름)를 찾아 `qualification_words`로 고침. 원문 대조(AI 참고) 맞음 6·아님 2 → `--write-reviewed` 6건, 목록 27·기존 21건 그대로(`reports/bonus_boostable_20261008T085000Z/`).
- 남은 일: 시험 서버 반영(0019+0020, 사용자 명령)과 확인. Codex 7차는 사용자 판단. 남는 한계는 결정 0020.

### 2026-10-08 · Claude · 가산점 표 "배점" 칸 인정·원문 대조 목록 21건(결정 0019)

- 요청·목적: 괴산군 117554 표 "배점" 칸의 "10"이 걸러진 것을 살린다(사용자). 새로 점수가 나는 공고는 원문 대조 뒤 목록 추가, Codex 6차 요청서만, 서버 반영은 사용자 명령.
- 작업 전 상태: 결정 0018 코드(시험 서버 반영됨). 고치기 전 사본(`bonus.py`·`bonus_reviewed.json`)을 세션 임시 폴더에. 흉내 계산(`.dryforge/sim/`)으로 기준값 754·46·12를 다시 확인.
- 변경 파일: `search/bonus.py`(`SCORE_HEADER_WORDS`·`SCORE_HEADER_WINDOW`·`_BARE_NUMBER`, `score_header`·`table_mates`, `_check_documents`가 두 표시를 닮, `row_fingerprint` 제외 목록, `points_supported`·`points_owned` 표 경로, 머리 설명), `eval/bonus_boostable.py`(`movement_detail`), `search/bonus_reviewed.json`(11건 추가), 시험(`test_bonus.py` `TableScoreCellTests` 7개, `test_bonus_boostable.py` 1개 — 추가만), 문서: 결정 0019·목록·0016 한 줄, `business-rules.md` 9절, `search/AGENTS.md`, Codex 6차 요청서, 인계서 ⑰, `tracking/status.md`, AGENTS=CLAUDE(0019까지).
- 검증: 시험 958개 중 942 통과·16 건너뜀·실패 0(마지막 점검 지적으로 띄운 단위 "10 일자리"·연번 "1 여성기업 가점" 보완과 시험 2개 추가 — 다시 잰 값 같음, `reports/bonus_boostable_20261008T080203Z/`·`reports/bonus_conservative_20261008T080221Z/`). `-m eval.bonus_boostable --old <사본>`: 같음 754·모름→양수 46·그 밖 0, 양수 공고 22, 목록 안 10·새 후보 12(`reports/bonus_boostable_20261008T073942Z/`). `-m eval.bonus_conservative_compare --old <사본>`: 모름→양수만(+9·+7, `reports/bonus_conservative_20261008T074003Z/`). 원문 대조(AI 참고) 맞음 11·아님 1(119727 — "고도화 컨설팅" 표에만 가점) → `--write-reviewed` 11건, 목록 21·기존 10건 그대로(`reports/bonus_boostable_20261008T074204Z/`).
- 남은 일: 시험 서버 반영(사용자 명령)과 확인. Codex 6차는 사용자 판단.

### 2026-10-08 · Claude · 가산점 화면 사용 허용(원문 대조된 공고만)·Codex 4차 처리(결정 0018)

- 요청·목적: Codex 4차 지적 4건 수정. 사용자: 이번에 화면 사용도 허용(원문 대조된 공고만, 0·null은 표시 없음), 5차는 요청서만, 서버 반영은 바로.
- 작업 전 상태: 결정 0017 코드(시험 서버 미반영). 고치기 전 사본 4개(`bonus.py`·`app.py`·`app.html`·`bonus_reviewed.json`)를 세션 임시 폴더에.
- 변경 파일: `search/bonus.py`(`evidence_fingerprint`·`_has_qualification`·`_QUALIFICATION_WORDS`, `load_reviewed` 값 검사, `reviewed_ok` 원문 지문 비교), `search/app.py`(`bonus_verified` 함수·결과 칸, `bonus_boost`가 그것을 씀), `search/bonus_reviewed.json`(원문 지문), `web/app.html`, `eval/bonus_boostable.py`(목록 쓰기에 원문 지문), `eval/bonus_conservative_compare.py`(예전 파일에 `__file__`), 시험(`test_bonus.py` `Recheck4Tests`, `test_notice_api.py` 추가, 가짜 목록·가짜 가점 행에 원문 지문 — spec 허용), 문서: 결정 0018·0017·0008·목록, `contracts.md`, `business-rules.md` 9절, `operations.md`, `search/`·`web/AGENTS.md`, 알림 초안(화면 허용·새 칸 두 개, 보내지 않음), Codex 5차 요청서, 인계서 ⑯, `tracking/status.md`, AGENTS=CLAUDE(0018까지).
- 전후 차이·선택 이유: 화면 위험을 대조 품질로 한정하려고 순위용 칸과 별도로 `bonus_verified`(세기·경로와 무관)를 둠. 원문 지문은 줄 경계를 판단에 쓰므로 공백을 지우지 않고 줄바꿈 표기만 통일, 첨부 읽는 순서 영향을 없애려 정렬.
- 검증: `python -X utf8 -m unittest discover -s tests` → 948개 중 932 통과·16 건너뜀·실패 0. `-m eval.bonus_conservative_compare --old <0018 전 사본>` → `reports/bonus_conservative_20261008T064030Z/` 변화 없음. `-m eval.bonus_boostable --old <사본> --write-reviewed <10건>` → `reports/bonus_boostable_20261008T064049Z/` 같음 800·목록 안 10, 목록의 승인 항목·가점 행 지문은 전과 같음. 내 PC 임시 서버 8030: `boot_errors` 없음, 전북 예시 기본 3·6위 `bonus_verified`·`bonus_rank_applied` 참, 세기 0이면 6·7위 `bonus_verified` 참·`bonus_rank_applied` 거짓, 화면 "원문 대조됨 · 순위 반영됨", 콘솔 오류 없음(임시 서버는 끔).
- 최종 점검 보완: 가점 행에 원문 지문이 없으면(원문을 못 읽음 등) 대조 안 됨으로 봄(`reviewed_ok`), 시험의 가짜 가점 행·목록에 원문 지문 더함. 다시 돌린 결과 목록 안 10 그대로, 시험 948개 중 932 통과.
- 미검증·남은 문제: 시험 서버 반영·계약 시험은 사용자 명령 뒤. 표시 계산의 쉼표 경우 등은 막지 못함(조율 화면에는 대조된 공고만).
- 시험 서버 반영(10/8, 사용자 실행, 이전 파일 `~/_old/bonus_before_0018_20261008.tgz`): 해시 4개 일치, `boot_errors` 없음, 전북 예시 기본 117356·126642 3·6위 `bonus_verified`·`bonus_rank_applied` 참(세기 0이면 6·7위, 대조됨 참·순위 반영 거짓), 조율 쪽 계약 시험 16/16(`reports/notice_api_contract_20261008T065442Z/`).
- 다음 단계: 사용자 알림 발송 → (원하면) Codex 5차.

### 2026-10-08 · Claude · 가산점 순위 반영 0.2 켬 — 원문 대조를 마친 공고만(결정 0017)

- 요청·목적: Codex 3차 "보류"(P1 3·P2 1) → 사용자 A 방향. 3차 지적 처리 + 0.2를 지금 켜되 원문 대조를 마친 공고만, 목록 추가는 요청 시 Claude 대조 후, 순위 반영 표시(새 칸), 처음 한 번만 조율 알림, 4차 지적은 그때 정함.
- 작업 전 상태: 결정 0016 `search/bonus.py`(시험 서버 미반영). 고치기 전 사본 3개(`bonus.py`·`app.py`·`app.html`)를 세션 임시 폴더에.
- 변경 파일: `search/bonus.py`(`cert_words`, "및" 짝 누락 → 모름, `quote_lines`·`_SCORE_CELL`, 각주 이어진 줄, `row_fingerprint`, `load_reviewed`·`reviewed_ok`), `search/app.py`(`Weights.bonus` 0.2, `bonus_boost` → (점수, 얹은 공고), `bonus_rank_applied`, `boot` 목록), 새 `search/bonus_reviewed.json`, `eval/bonus_boostable.py`(`approved_items`·`review_status`·`write_reviewed`·`--write-reviewed`), `web/app.html`, 시험 4개 파일(추가, 예외 1건), 문서: 결정 0017·0015·0008·목록, `business-rules.md` 5·9절, `contracts.md`, `operations.md`, `search/`·`eval/`·`web/AGENTS.md`, 알림 초안, Codex 4차 요청서, 인계서 ⑮, `tracking/status.md`, AGENTS=CLAUDE(0017까지).
- 전후 차이·선택 이유: 줄 경계로만 나누면 표의 배점 칸이 따로 줄이라 117928·126830·127009의 맞는 점수까지 빠져(첫 시도 8건) 배점 칸·"*" 설명 줄은 앞줄에 붙이도록 다듬음. 기존 시험 `test_bonus_weight_reorders_only_within_rule_tier`만 목록 없이 오른다고 기대해 가짜 STATE에 목록을 넣음(spec 6절 예외).
- 검증: `python -X utf8 -m unittest discover -s tests` → 945개 중 929 통과·16 건너뜀·실패 0. `-m eval.bonus_conservative_compare --old <0017 전 사본>` → `reports/bonus_conservative_20261008T053625Z/` 변화 없음. `-m eval.bonus_boostable --old <사본>` → `reports/bonus_boostable_20261008T053633Z/` 같음 800·관측 10건, `--write-reviewed` 10건 → `reports/bonus_boostable_20261008T053841Z/`(목록 안 10·다시 대조 0·새 후보 0). 내 PC 임시 서버 8030(새 코드): `boot_errors` 없음, 전북 예시 기본 117356·126642 3·6위 참, 세기 0이면 6·7위 거짓, 화면 "순위 반영됨" 표시·콘솔 오류 없음(임시 서버는 끔). `-m eval.bonus_rank_cases` → `reports/bonus_rank_cases_20261008T054344Z/`(3차 측정과 같음).
- 최종 점검 보완(같은 날): 기준 문서 9절의 옛 "세기 0·대기" 문장 정리, 배점이 든 "*" 줄은 앞줄에 붙이지 않음(시험 추가 단언), 화면 문구 "세기 0이라 / 원문 대조 목록 밖이라 순위 미반영", 약속 문서에 "계산에 쓰였다" 뜻 보충. 다시 돌린 결과 같음(`reports/bonus_boostable_20261008T055224Z/` 같음 800·목록 안 10), 시험 945개 중 929 통과.
- 미검증·남은 문제: 시험 서버 반영·계약 시험은 사용자 명령 뒤. 쉼표로만 이어진 문장, 다른 행 이름 뒤 배점 칸만 있는 줄은 표시에서 못 막음(순위는 목록이 막음). 목록 근거는 AI 참고.
- 다음 단계: 시험 서버 반영·확인 → 사용자 조율 알림 → Codex 4차.

### 2026-10-08 · Claude · Codex 재재검수 지적 처리(결정 0016)

- 요청·목적: Codex 재재검수 "추가 수정 후 재검수 필요, 0.2 보류"(P1 5·P2 2) → 사용자 A 방향(실제 2건 + 쉬운 것 고치고 ④⑤는 보수적 null, 다시 검수). ① "및·&" 짝을 확인 못 하면 모름·짝을 안 가진 것이 확실하면 "둘 중 하나", ② "가점·인정 줄만", 시험 서버 반영, 순위 비교 측정 포함.
- 작업 전 상태: 고치기 전 `search/bonus.py` 사본을 세션 임시 폴더에 둠(비교·서버 해시 확인용). `search/app.py`·`web/app.html`은 바꾸지 않음(해시 315071ab…·a836977d… 그대로).
- 변경 파일: `search/bonus.py`(①~⑥, 공통 규칙 `score` = 이전·새 계산, `document_parts`·`period_lines`, `load`가 `period_lines`·`selection` 표시), `tests/test_bonus.py`(`Recheck2Tests` 8개, 기존 33개 기대값 그대로), `eval/bonus_boostable.py`("전부" 표현 → 탐색 관측, `trial_inputs`·`movement`·`compare_old`, `--old`), `tests/test_bonus_boostable.py`(+2), 새 `eval/bonus_rank_cases.py`·`tests/test_bonus_rank_cases.py`. 문서: 결정 0016·0014·0015 정정·목록, `business-rules.md` 9절, `search/AGENTS.md`, `eval/AGENTS.md`, 알림 초안 숫자, 3차 요청서 `docs/notice_api/CODEX_BONUS_RECHECK3_REQUEST_20261008.md`, 인계서 ⑭, `tracking/status.md`, AGENTS=CLAUDE(0016까지).
- 전후 차이·선택 이유: 모두 더 엄격하게만. 항목을 내리면 한도 초과 검사가 풀려 null → 양수가 되는 길(120238 5+5+1)을 점검 중 찾아 공통 규칙으로 막음. ①의 "또는·쉼표·등" 나열은 뜻이 분명해 제외(126830·122309, Codex도 원문과 맞다고 봄).
- 검증: `python -X utf8 -m unittest discover -s tests` → 936개 중 920 통과·16 건너뜀·실패 0(최종 점검 보완 뒤). `-m eval.bonus_conservative_compare --old <사본>` → `reports/bonus_conservative_20261008T034533Z/`: 여성기업·벤처·성남 8→7, 장애인기업·이노비즈·전남광주 8→7(둘 다 126819 5→null). `-m eval.bonus_boostable --old <사본>` → `reports/bonus_boostable_20261008T034650Z/`: 조합 800개 같음 783·양수→null 9·양수→더 작은 양수 8·그 밖 0, 관측 공고 10건, README 원문 대조 맞음 10·틀림 0. 꼭 바뀌어야 할 것(120238 청년친화·가족친화 → null, 사회적 5 유지, 126819 → null, 117356·126642 여성 5 유지) 직접 확인. `-m eval.bonus_rank_cases` → `reports/bonus_rank_cases_20261008T035007Z/`: 제목 그대로 10건 모두 1위, 분야 문장 모두 20위 밖, 제목 핵심어 4건 2위 중 120238·125997이 0.2에서 1위(앞질린 공고는 가산점 "모름").
- 최종 점검 보완(같은 날): ③을 근거 문장에도 적용(추가 조건 칸이 비어도 다른 자격 서류면 모름), ① 짝 찾기에서 이름·종류가 모두 같은 중복만 제외, ⑤ 고르기 말 보강(1개 항목만·중복 수혜 불가·높은 점수 1개), 청년 대상 말 '세' → '세 이하·세 미만'. 다시 돌린 결과는 같다 (`reports/bonus_conservative_20261008T035945Z/`, `reports/bonus_boostable_20261008T035949Z/` — 조합 800개 같음 783·양수→null 9·양수→더 작은 양수 8·그 밖 0, 관측 10건).
- 미검증·남은 문제: ④⑤는 보수적 규칙(원문 관계 해석 아님 — ④는 쉼표로만 이어진 문장을 못 나눔). 탐색은 800개 조합 관측. 원문 대조는 AI 참고. 시험 서버 반영은 사용자 명령 뒤 확인.
- 다음 단계: 시험 서버 반영·확인 → Codex 3차 검수(사용자) → 결정 0015 켤지 결정.

### 2026-10-08 · Claude · 가산점 순위 반영 0.2 준비(결정 0015, 대기)

- 요청·목적: 멘토 의견으로 가산점을 순위에 반영(세기 0.2). 사용자: Codex 재재검수 뒤 켜고, 오늘은 확인·준비만. 원문 대조는 "가능한 조합 전부", 검색 성적 비교는 참고만(한계 명시), 문제가 나오면 멈추고 보고, 조율 알림은 켜고 나서.
- 작업 전 상태: `Weights.bonus = 0`(결정 0008). 시험 화면에 세기 선택(0·0.2·0.5·1.0)이 있음. `search/app.py`·`web/app.html`·`search/bonus.py`·`search/AGENTS.md`에 커밋 안 된 변경이 있어 작업 전후 해시로 "안 바뀜"을 확인.
- 변경 파일: 새 도구 `eval/bonus_boostable.py`(열린 공고 중 어떤 입력 조합으로든 가산점이 양수가 되는 공고 전부 + 예시 조합·항목·근거 주변 원문) · 시험 `tests/test_bonus_boostable.py`(8개) · `eval/AGENTS.md` 한 줄. 결정 `0015-bonus-rank-weight-0-2.md`·목록, `business-rules.md` 9절 한 줄, 재재검수 요청서 7번, 알림 초안 "순위 반영" 줄(보내지 않음), `tracking/status.md`, 인계서 ⑬, AGENTS=CLAUDE(0015까지).
- 전후 차이·선택 이유: 서비스 동작은 그대로(기본값 0). 켜는 절차를 결정 문서에 적어 두어 재재검수 뒤 그대로 따라 한다. 원문 대조를 가상 신청자가 아니라 조합 전부로 넓힌 것은 실제 신청자 조합을 모르기 때문(사용자 선택).
- 검증: `-m eval.bonus_boostable` → `reports/bonus_boostable_20261008T025339Z/`: 열린 공고 1,748건·가점 찾음 317건 중 양수 가능 11건(기업마당 11, 조합 800개 시도), 빠뜨림 확인(가상 신청자 4+5명의 양수 공고 10건) 통과, README에 Claude 원문 대조 표(맞음 11·틀림 0·애매 1항목 — 120238 가족친화 1점). `-m eval.bonus_rank_eval` → `reports/bonus_rank_eval_20261008T025137Z/`: 기준일 9/15·말뭉치 2,084건·질의 58·상위 10, 세 속성 모두 세기 0.1~0.3 자리 바뀐 수 0·지표 변화 +0.000(구간 0~0) — 멈춤 기준 안 걸림, 다만 잴 수 없음. `python -X utf8 -m unittest discover -s tests` → 920개 중 904 통과·16 건너뜀·실패 0. 네 파일 해시 작업 전후 같음.
- 미검증·남은 문제: 원문 대조는 AI 참고(사람 정답 아님). 세 개 이상을 동시에 맞혀야만 양수가 되는 공고는 도구가 놓칠 수 있음(한계 기록).
- 다음 단계: Codex 재재검수(사용자) → 결과를 보고 켤지 결정 → 결정 0015 "켜는 절차" 1~9.

### 2026-10-08 · Claude · 시험 화면에 가산점 순위 반영 세기 선택

- 요청·목적: 멘토가 가산점도 중요하다고 함 → 가중치를 줘서 순위를 바꿔야 하나 고민. 먼저 사용자가 직접 비교해 보고 싶다.
- 사전 측정(시험 서버 `/api/match`에 `weights.bonus` 0·0.2·0.5·1.0, 가상 신청자 5명, 상위 20위, 읽기만): 순위가 바뀐 것은 전북 장애인기업 예시뿐(+5점 공고 6·7위 → 0.2: 3·6위, 0.5: 2·4위, 1.0: 1·2위). 김포·충남은 이미 위쪽이라 그대로, 평범한 아이디어 문장 2명은 20위 안에 가산점 공고가 없어 변화 0. 막히는 곳은 세기보다 "가산점이 확인된 공고 수"(열린 공고 1,748건 중 신청자당 0~8건).
- 변경: `web/app.html` 결과 화면에 "가산점 순위 반영 세기"(0 지금 서비스·0.2·0.5·1.0). 바꾸면 같은 입력으로 다시 검색(`weights: {bonus}`만 보내고 나머지는 서버 기본값), 세기 > 0이면 세기 0으로 한 번 더 불러 자리가 바뀐 공고를 "n위 → m위"로 적음. 가산점 요약 문구도 세기에 맞게. 서비스 기본값(`Weights.bonus = 0`)은 그대로.
- 검증: 임시 서버 8031(고친 화면 + 시험 서버 API)에서 전북 예시 — 세기 0.5: 전북 육성자금 7위 → 3위, 1.0: 7위 → 1위. 콘솔 오류 없음. 시험 132개 통과. 임시 서버는 끔.
- 다음: 사용자가 시험 서버에서 직접 비교한 뒤 세기를 기본값으로 켤지 결정(켜면 결정 기록·조율 담당 알림·올라가는 공고 원문 확인).

### 2026-10-08 · Claude · 시험 화면에 가산점 확인용 예시 버튼

- 요청·목적: 8000 시험 화면에서 버튼 하나로 예시 입력을 채워 가산점을 바로 확인하고 싶다.
- 변경: `web/app.html` — "가산점 확인용 (누르면 바로 매칭)" 줄에 버튼 3개(벤처기업·경기 김포 / 장애인기업·전북 / 여성기업·충남). 가짜 신청자 3명을 `SAMPLES`에 더하고, `data-run` 버튼은 채운 뒤 바로 매칭을 누른다. 점수는 화면에서 계산하지 않고 응답 그대로 보여 준다. `web/AGENTS.md` 표 한 줄.
- 검증: 고친 화면을 내 PC 임시 서버(8031, `/api/*`는 시험 서버로 넘김)에서 눌러 봄 — 김포: 1·2위 김포 육성자금 공고 +10점 / 전북: 7위 전북 육성자금 +5점 / 충남: 5위 중소기업 마케팅지원사업 +1점, 1위 수원메가쇼·4위 전용판매장은 "모름"(결정 0014 `search/bonus.py`가 시험 서버에 아직 안 올라감 — 올리면 +5·+1 예상). 임시 서버는 끔. 시험 `test_notice_api`·`test_bonus`·`test_verify_ui` 132개 통과.
- 남은 것: 시험 서버에 `web/app.html`·`search/bonus.py`를 올리는 것은 사용자 명령. 공고가 마감되면 예시가 가리키는 공고가 결과에서 빠질 수 있다(그때 예시 아이디어 문장을 바꾼다).

### 2026-10-08 · Claude · 가산점 추가 조건 완화(A, 결정 0014)

- 요청·목적: 가산점이 너무 엄격하다 → 관문 넷 가운데 "뜻이 안 바뀌는 추가 조건 허용"만 반영(사용자 선택). 시뮬레이션에서 +1~2곳임을 알고 고름.
- 변경: `search/bonus.py` — 추가 조건을 `;`·`/`로 나눈 조각이 모두 증빙 서류(`BENIGN_PAPER`)·유효기간(`BENIGN_VALID`)이고 위험 말(`RISKY_WORDS`)이 없거나 "중소기업" 단독이면 모름으로 내리지 않음(`benign_extra`). 조건 말 검사 전에 위험 말 없는 증빙·유효기간 구절을 뺌(`_drop_benign_phrases`). 머리말에 예외. 시험 `tests/test_bonus.py` `BenignExtraTests` 5개(허용·불허·해당 아님 유지·구절 빼기·점수 계산). 기준 문서 `business-rules.md` 9절(예외 한 줄·원칙 문장·10/8 수치), `search/AGENTS.md`, `tracking/status.md`, 결정 0014·목록, AGENTS=CLAUDE(0014까지), 알림 초안(숫자·설명, 보내지 않음), 재재검수 요청서 6번.
- 검증: 시험 912개 중 896 통과·16 건너뜀. `-m eval.bonus_conservative_compare`(예전 = git HEAD) → `reports/bonus_conservative_20261008T013308Z/`: null → 점수만(여성기업·벤처·성남 647·1095·6 → 645·1095·8, 장애인기업·이노비즈·전남광주 646·1095·7 → 645·1095·8). 시뮬레이션과 같음.
- 시험 서버 반영(사용자 실행, 이전 파일 `~/_old/app_bonus_before_20261008.tgz`): `/api/health` `boot_errors` 없음, `/api/match` 충남 여성기업 예시 126819 +5·125997 +1(전에는 null), 계약 시험 16/16 → `reports/notice_api_contract_20261008T022607Z/`.

### 2026-10-08 · Claude · gpt-6-luna 전환 (2부, 결정 0013)

- 사용자 결정(10/7): 3단계(신청자 유형·업종·가점)만 전환, 자격요건 유지, 배치 서버 키, 오늘 바로.
- 변경: `experiments/sql_semantic/applicant_type_llm.py`·`collect/industry_daily.py`·`collect/extract_bonus.py`의 `MODEL` → `gpt-6-luna`. `collect/applicant_type_daily.py`·`industry_daily.py` — 결과 행마다 `engine`, `LEGACY_ENGINE`(`gpt-5.6-luna@medium`), 엔진이 다르면 다시 뽑기(`plan(engine=)`, `other_engine()` — 업종은 기존 결과와 같은 발췌 길이), 체크포인트 재사용도 엔진 확인, 미리 보기(`--plan`)도 같은 기준. `experiments/sql_semantic/industry_llm_sample.only_new`는 행의 `excerpt_cap`을 먼저 본다(길게 읽은 공고를 새 엔진으로 다시 뽑아도 매일 다시 부르지 않게). `collect/upload_judgments.py` — 행마다의 엔진으로 추출기 버전. `collect/backup_db.py` — `--restore FILE --tables … [--apply]`(AI 판정 4개 표만, 먼저 전체를 훑어 없으면 아무것도 안 함). 시험: `test_industry_daily`(엔진·같은 길이·다음 날 다시 안 부름), `test_applicant_type_daily`, `test_upload_judgments`, `test_backup_db`(되살리기 4개). 기준 문서(`collect/AGENTS.md`, `architecture.md`, `FLOW.md`, `guides/JUDGMENT_TABLES.md`, `notice_api/03_bonus/README.md`, `operations.md` 전환·되돌리기 방법, AGENTS=CLAUDE 결정 0013까지).
- 실행(사용자, 배치 서버): 코드 묶음 복사 → 백업(`~/sbrain/_old/*6luna*`) → `applicant_type_daily --limit 3500`(2,825·실패 0·$1.20) → `industry_daily --limit 3500`(2,825·실패 0) → 10/8 09:00 매일 배치가 판정 올리기 2,861·2,861과 가점 300건 → `extract_bonus --all`(707·실패 0·$0.73). 처음 `--plan`이 엔진 기준을 안 써서 0건으로 보였다 → 고쳐 다시 올림. 시험 서버: 코드 백업 → 반영 → 재시작(처음 백업 명령은 시험 서버에 `db/`가 없어 멈춤, 있는 폴더만으로 다시).
- 검증: 공용 DB 버전별 행 수(위 STATUS), 시험 서버 `/api/health` `boot_errors` 없음, `/api/match` 가산점 나옴(120481·122057 +10), 계약 시험 16/16(`reports/notice_api_contract_20261008T010543Z/`), 시험 907개 중 891 통과·16 건너뜀. 작업 사본 CRLF 정리(내용 변화 없는 파일은 `git checkout`으로 원상태).
- 남은 것: 10/9 매일 배치 확인. 가산점 있는 공고가 늘어난 원인 확인은 하지 않았다.

### 2026-10-07 · Claude · gpt-6-luna 전환 전 표본 비교 (1부)

- 요청·목적: 배치 AI 4단계를 gpt-6-luna(medium)로 바꾸고 싶다. 비용·문제점을 먼저 본다. 사용자 결정: 표본 비교 → 보고 → 승인 뒤 전환, 4단계 모두, 전량 한 번에, 업종 순위 파일 유지, 배치 서버에서 사용자가 실행, 직전 백업 두 가지, 팀원 알림 없음.
- 변경: `experiments/sql_semantic/industry_llm_sample.py`(`PRICES`에 gpt-6-luna, `REASONING_PREFIXES`에 `gpt-6`), `collect/extract_conditions.py`(`ask`에 모델·생각 강도 인자, `request_options` — gpt-4o-mini는 지금처럼 `temperature=0`), `collect/extract_bonus.py`(`ask`·`run_one`에 모델 인자, `extractor_version()`, 단가). 기본 모델은 그대로. 새 시험 `tests/test_model_options.py`(9개). 비교 도구 `eval/model_switch_compare.py`(같은 문서만 비교, 업종은 기존 결과와 같은 길이로 읽음, 가점은 서버 규칙으로 최종 점수 비교).
- 실행: `--plan`(예상 $0.24) → 실제 `--workers 6`. 첫 실행은 업종 비교 코드 오류(`allowed_sections`가 None)로 중간에 멈춰 고친 뒤 다시 돌렸다(미완성 폴더는 지움). 결과 `reports/model_switch_6luna_20261007T073852Z/` — 160건 성공·실패 0, $0.11.
- 결과 요지: 가점 상태·최종 가산점 40/40 같음. 신청자 유형 117/120칸. 업종 대분류 39/40(상태 차이 15건은 대부분 순위에 안 쓰는 "언급 없음 ↔ 알 수 없음"). 자격요건 업력 40/40, 지원 금액 34/40, 사업자 유형·예비창업자 26/40 — 새 모델이 빈 값을 많이 내고 근거 검사에서 버려지는 값이 9건. 전량 추정 $5.37(자격요건 1.51·신청자 유형 1.12·업종 1.75·가점 1.00). 자격요건은 출력 토큰이 5배라 비용이 지금과 비슷.
- 검증: 시험 899개 중 883 통과·16 건너뜀·실패 0. 공용 DB 쓰기 0(비교 도구는 SELECT만).
- 다음: 사용자 승인 대기(단계별 전환 여부·키·날짜). 승인 전에는 기본 모델·DB·서버를 바꾸지 않는다.

### 2026-10-07 · Claude · 공용 DB 백업 도구 보강과 새 백업

- 요청·목적: 지금 프로젝트에서 백업이 필요한 곳 점검 → DB가 가장 중요. 마지막 전체 백업이 9/14였고, 그 뒤 생긴 AI 판정 표(자격요건·신청자 유형·업종·가점)는 백업 도구 기본 범위에도 없었다. 사용자 결정: 우리 표 전부 + 첨부 원본, 도구도 고침, 끝나면 9/14 백업 삭제.
- 변경: `collect/backup_db.py` 기본 테이블에 `notice_conditions`·`notice_applicant_types`·`notice_industries`·`notice_bonus` 추가, 읽기 전용 한 시점 스냅샷(`START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY`, 끝나면 rollback), 다른 팀 테이블은 넣지 않음을 머리말에 적음, `utcnow` 경고 제거. 새 시험 `tests/test_backup_db.py`(6개: 범위·다른 팀 표 제외·값 변환·SELECT/SHOW만·스냅샷·첨부 옵션). `collect/AGENTS.md`, `docs/operations.md` 5절.
- 실행: 접속 확인(information_schema SELECT, 공용 DB 약 890MB, 우리 표 외 다른 팀 표 33개 1MB 미만) → `-m collect.backup_db --include-files` 종료 코드 0. `data/backup_20261007T153141.sql` 1,747MB, 9개 표(행 수: import_runs 28·notices 2,825·notice_attachments 3,985·attachment_texts 2,294·notice_conditions 2,096·notice_applicant_types 2,825·notice_industries 2,825·notice_bonus 2,078·attachment_files 2,234), 파일 끝 `SET UNIQUE_CHECKS = 1;`까지 확인, Git 무시 확인.
- 9/14 백업(`data/backup_20260914T160825.sql`, 47MB)은 사용자 요청으로 **휴지통으로 보냄**(영구 삭제 아님).
- 검증: 전체 시험 890개 중 874 통과·16 건너뜀·실패 0(백업 시험 6개 늘어 884 → 890).
- 남은 것: 다른 팀 표·팀 EC2 전체 백업(AWS 스냅샷)은 팀에 확인할 일. 배치 서버 `data/`는 서버에만 있음.

### 2026-10-07 · Claude · 단위 테스트 다시 재기(정리 뒤 개정판)

- 요청·목적: 단위 테스트를 다시 진행. 오전 결과서(제출함) 뒤 폴더 정리로 코드가 바뀌어 숫자를 지금 코드로 맞춘다. 사용자 결정: 시험 추가 없음, MySQL 통합 시험 건너뜀, 같은 파일 덮기 + 개정판 표시, 처음 판 → 이번 비교와 이유.
- 실행: 새 폴더 `reports/unit_test_20261007T062019Z/`에 오전 판 스크립트(`run_unit.py`·`cov_summary.py`, 범위 목록 그대로)를 복사해 `coverage run -m run_unit`(PYTHONPATH=새 폴더, COVERAGE_FILE=새 폴더/.coverage) → `cov_summary.py`. 옛 폴더 두 개는 읽기만.
- 결과: 884개 중 868 통과·16 건너뜀·실패 0·오류 0(종료 코드 0). 범위 67.5% → 67.6%(7,153 → 7,140줄, 실행 4,827 → 4,824줄). 기능 ① 공고 수집 62.7% → 64.7%, 나머지 기능 같음. 바뀐 파일은 `collect/daily_job.py`(160 → 147줄, 실행 90 → 87줄)뿐 — `git diff e170642..HEAD`로 확인한 정리 변경(쓰이지 않던 임베딩 코드·`skip_embed` 삭제).
- 결과서: `build_report.js`를 새 폴더로 복사해 고침 — 셋째 인자로 처음 판 폴더를 받아 비교 표를 만들고, 바뀐 파일마다 확인한 이유가 없으면 멈추게 함. 표지 개정판 표시, 결과 요약 처음 판/이번 표, "처음 제출한 판과 달라진 점", 기능별 표 "처음 → 이번", "10/7 오전에 더한 시험 7개 파일", 원칙 문장 사실대로, 범위 밖 설명에서 지운 파일 뺌, 5.5에 재측정 사실. node `docx` 9.9.0은 저장소 밖(세션 임시 폴더)에 설치.
- 검증: 워드를 글자로 다시 읽어 개정판 표시·67.5%/67.6%·7,140/4,824·① 비교·지운 파일 문구 없음·옛 원칙 문장 없음 확인.
- 기록: `standards.md` 10절, `tracking/status.md`, `docs/README.md` deliverables 줄, 인계서 ④·5-1을 새 숫자·새 폴더로.

### 2026-10-07 · Claude · data-collection 정리 ("다른 사람이 봐도 헷갈리지 않게")

- 요청·목적: 폴더가 복잡해 처음 보는 사람이 헷갈린다. 안 쓰는 파일·문서를 정리한다. 사용자 결정: 1~5단계 모두 진행, Chroma 코드 제거는 나중(문서에 "안 씀"만 표시).
- 조사: 코드 import 정적 분석·`reports/` 폴더 이름 참조 대조·문서 링크 대조(읽기만, 하위 AI 두 개).
- ① 지움(Git 무시 파일, 약 41MB): 루트 `__pycache__/`(옛 평면 구조 pyc), `data/conditions_sample_*.json` 5개(쓰기만 하고 읽는 곳 없음), `data/vecstore/`의 `qdrant`·`faiss.index*`·`chroma_backup_20260921T…`(9/10·9/21 실험 잔재). `.pytest_cache`는 권한 때문에 못 지움(빈 폴더). `data/vecstore/chroma`는 평가 도구가 읽어 남김.
- ② 지움(Git 추적, 약 12MB):
  - `reports/` 7개 — 코드·문서 어디에서도 이름이 안 나오는 것: `_codex_docx_qa`, `_template_codex`, `industry_rank_check_20260928T021723Z`·`T022212Z`, `bonus_sample_20261006T023723Z`, `industry_weight_probe_20260922T020621Z`, `chroma_integrity_20260921T031731Z`.
  - `reports/`의 9/16 전처리 결과서 초안 생성기 3개와 초안 docx 2개(최종본은 `docs/deliverables/`).
  - `search/search_local.py`(옛 시험 CLI), `scripts/`(`backfill_region.py` 일회성 + `__init__.py`).
  - `collect/daily_job.py`의 없는 모듈 `match_bge` 임베딩 코드와 `skip_embed`·`--skip-embed`(배치는 늘 건너뛰어 닿지 않던 길). `daily_pipeline.py` 호출을 맞춤. 로그의 `embedded`·`embed_error` 키도 빠짐(읽는 곳 없음).
  - 남김: `industry_llm_full_luna_20260922_rough_split2/3`, `search_comparison_20260918T053021Z` — 다른 결과의 meta·manifest가 출처로 가리킨다.
- ③ `docs/archive/`로 옮김: `guides/ORCHESTRATION_HANDOFF.md`(9/29 직접 import), `guides/SCHEDULER.md`(PC 예약), `guides/architecture.html`·`ARCHITECTURE.svg`·`hybrid_flow.html`·`pipeline_flow.html`(Chroma·PC 시절 그림), `WORK_SUMMARY_20260929.md`. 가리키던 링크(README·STATUS·WORKLOG·reviews/orchestration 등 70여 개)와 `experiments/orchestration_probe.py` 경로를 고쳤다. archive 인계서 2개의 깨진 상대 링크 26개도 고쳤다. `share/전체흐름.html`·`web/flow.html`(9/28~29 그림) 맨 위에 "지난 기준" 안내를 붙였다.
- ④ 입구 문서: `README.md`를 새로 썼다(13단계·PC 예약·Chroma 설명 → 14단계·서버 배치·메모리 벡터, 무엇이 어디서 도는지 표). `docs/README.md` 1·2·3·5절, `FLOW.md`(맨 위 "지금 바뀐 것 세 가지", 7단계 "공고 서버는 안 씀"), `guides/QUERIES.md`·`TEAM_DATA.md`, `notice_api/README.md` 진행표(+ 연결 지도 HTML·API 사용법 엑셀), `AGENTS.md`=`CLAUDE.md`(결정 0012까지), `standards.md` 13절, `tracking/status.md` 기준일, `eval/README.md`(Chroma 시절 도구 표시), `collect/AGENTS.md`·`search/AGENTS.md`(지운 파일 줄).
- ⑤ 진행 일지 나누기: `STATUS.md` 216행~끝(9/14~9/30 항목과 옛 고정 절) → `archive/STATUS_202609.md`, `WORKLOG.md` 206행~끝(9/17~9/30) → `archive/WORKLOG_202609.md`. 내용은 그대로, 상대 링크만 새 위치에 맞춤(149·170개). STATUS 160KB → 27KB, WORKLOG 436KB → 34KB.
- 검증: 시험 884개 중 868 통과·16 건너뜀·실패 0(정리 전과 같음). 문서 링크 점검(.md 상대 링크): 남은 52개는 정리 전부터 있던 것 — Codex 검수 문서의 `파일:줄번호` 표기와 결과 보존 원칙상 고치지 않는 `reports/` 안 옛 링크.
- 하지 않은 것: Chroma 코드 제거(배치 7단계·EC2 00:10 예약·`ec2_vecstore`의 Chroma 함수·평가 도구) — 서버 작업이 따라와 나중. `run_daily.bat`·`schedule-task.ps1`(되돌리기용), `data/backup_20260914T160825.sql`(유일한 전체 백업), `reviews/`(지표 코드가 셈), `PLAN_ALIGNMENT`(코드 주석이 가리킴)는 그대로.

### 2026-10-07 · Claude · 시험 화면(8000 `/`)에 가산점 표시

- 요청·목적: 가산점을 `/docs`가 아닌 8000번 시험 화면에서도 시험할 수 있게 한다.
- 작업 전 상태: `web/app.html`은 `bonus_score`를 받지만 보여 주지 않았다.
- 변경 파일: `web/app.html`(카드·목록의 가산점 줄, 결과 위 집계, 자격 확인 화면의 가산점 칸 + `/api/notices/{id}` 가점 원문), `web/AGENTS.md`.
- 전후 차이·선택 이유: 화면 표시만 늘었다. 문구는 조율 담당 알림 초안과 같은 "확인된 가산점(일부)"을 쓴다. 0은 "가산점 없음", null은 "가산점 모름"으로 구분한다. 순위·응답은 그대로다.
- 검증: 이 PC 8030 임시 서버에서 여성기업·벤처·경기 성남시(아이디어 = 김포시 공고 제목)로 검색해 20건을 확인했다.
  - 화면: 확인된 가산점 1(120481 +10점)·없음 7·모름 12. 120481 자격 확인 화면에 "벤처기업 10점"과 가점 원문이 나왔다. 브라우저 오류는 없었다.
  - 시험: 884개 중 868 통과·16 건너뜀.
  - 화면 그림(스크린샷)은 앱 창이 그려지지 않아 찍지 못했다. 글자·구조로 확인했다.
- 미검증·남은 문제: 시험 서버 반영은 사용자 몫이다(명령은 STATUS).

### 2026-10-07 · Claude · 가산점 재검수 지적 처리

- 요청·목적: Codex 가산점 재검수(10/7, P1 3·P2 3·P3 1) 지적을 처리한다. 사용자 결정은 다음과 같다.
  - `bonus_score` = 확인된 가산점 부분합(결정 0012).
  - 짚은 틈은 모두 null로 막는다.
  - AI 재호출·재추출 없음, 공용 DB 쓰기 없음, 순위 반영 0.
- 작업 전 상태: 10/7 오전판(확실한 것만 남기기). "가산점 있음"은 열린 공고 1,741건 중 신청자마다 7곳이었고, 재검수가 10점 → 20점(묶음 분리), 8점(한도 불확실), 이어 붙인 근거 10점 경로를 재현했다.
- 변경 파일: `search/bonus.py`(규칙·원문 확인·머리말), `search/app.py`(boot 오류 칸), `collect/extract_bonus.py`(하루 상한 잠금), `tests/test_bonus.py`(`RecheckTests`·`LoadTests`), `tests/test_extract_bonus.py`(동시 실행), `eval/bonus_conservative_compare.py`(`--old`·관찰 공고), 문서(contracts·business-rules 9절·결정 0008·0012·목록·`search/AGENTS.md`·`notice_api/README.md`), 새 `docs/notice_api/CODEX_BONUS_RECHECK2_REQUEST_20261007.md`·`BONUS_NOTICE_DRAFT_20261007.md`.
- 전후 차이·선택 이유: 새 규칙은 "해당 → 모름", "점수 → 없음/null" 방향뿐이라 결과가 양수 → null 쪽으로만 움직인다. 전체 합계 대신 부분합으로 정한 이유는 다음과 같다. 오전에 점수가 나온 8곳이 모두 모르는 묶음을 함께 갖고 있어, 전체 합계로 정하면 0곳이 되기 때문이다.
  - 기대값을 바꾼 기존 시험: `test_independent_bonuses_in_one_sentence`(123858 4점 → null), `test_uncertain_reading`("중복" 메모 1묶음 3점 → null).
- 검증:
  - `python -X utf8 -m unittest discover -s tests` → 884개 중 868 통과·16 건너뜀·실패 0.
  - `python -X utf8 -m eval.bonus_conservative_compare --old <오전판>` → `reports/bonus_conservative_20261007T024147Z/`(신청자 4명: 있음 0·0·7·7 → 0·0·3·3, null로만 이동).
  - 8030 임시 서버 계약 시험 `--all` → 16개 실패 0, 2,825건 형식 오류 0, `boot_errors` 없음(`reports/notice_api_contract_20261007T024341Z/`).
  - 커버리지 다시 잼 → `reports/unit_test_20261007T024611Z/`(범위 621개, 67.5%). 결과서는 새 숫자로 다시 만들고 글자로 대조함(부록 621행 = 통과 605 + 건너뜀 16).
- 미검증·남은 문제: Codex 재재검수 전. 서버 반영은 사용자 몫(명령은 STATUS). 조율 담당 알림은 사용자가 보낸다. 남은 양수 4곳(117928·120481·122147·126642)은 사람이 원문으로 확인하지 않았다. 결과서는 워드 창을 닫은 뒤 바꿔 넣었다.
- 다음 단계: 서버 반영 → Codex 재검수 → 통과하면 "화면에 써도 됨" 알림.

### 2026-10-07 · Claude · 단위 테스트 보강과 워드 결과서

- 요청·목적: 맡은 역할(서비스에 쓰이는 11개 기능)을 단위 테스트로 점검하고 제출용 워드 결과서를 만든다(사용자 결정: 보강 + 결과서, 커버리지 포함, 기능별 요약 + 대표 사례).
- 작업 전 상태: 시험 778개(통과 762·건너뜀 16). `fetch`·`attachment_pipeline`·`hwp5`·`upload_vectors`·`upload_attachments`·`config`·`eligibility`는 직접 검사하는 시험이 없었다.
- 변경 파일: 새 시험 `tests/test_fetch.py`(9)·`test_attachment_pipeline.py`(32)·`test_hwp5.py`(11)·`test_upload_vectors.py`(13)·`test_upload_attachments.py`(8)·`test_config.py`(9)·`test_eligibility.py`(16). 새 결과서 `docs/deliverables/[단위 테스트] 공고 데이터·매칭 단위 테스트 결과서.docx`. 기록 `docs/STATUS.md`·`docs/README.md`·`docs/tracking/status.md`·`docs/standards.md`. 운영 코드·기존 시험 기대값은 바꾸지 않았다.
- 전후 차이·선택 이유: 시험만 더했다. 가짜 응답·가짜 연결·임시 폴더로만 시험해 비용 0, 공용 데이터 무변경.
- 검증: `python -X utf8 -m coverage run -m run_unit`(= `unittest discover -s tests`) → 876개, 통과 860·실패 0·오류 0·건너뜀 16(`MYSQL_INTEGRATION_TEST` 끔). 범위 시험 613개, 범위 줄 커버리지 67.2%(7,095줄 중 4,771줄). 결과 `reports/unit_test_20261007T021113Z/`(README·coverage_summary.json·tests.json·coverage_report.txt·run.log·측정 스크립트). 결과서는 글자로 다시 추출해 요약 숫자·부록 행 수(613, 통과 597·건너뜀 16)를 대조했다.
- 미검증·남은 문제: MySQL 통합 시험 16개(시험용 DB 없음), 실제 외부 API·첨부 샘플·HWP 파일 시험 없음. 커버리지 낮은 곳 `ec2/ec2_vecstore.py` 0%·`search/vecstore.py` 17.4%. 시험 작성 중 기본 경로가 정의 때 묶이는 함정으로 `data/attachment_results.jsonl`에 가짜 37줄이 생겨 지움(실제 기록 없던 새 파일).
- 다음 단계: 사용자가 결과서 검토·제출.

### 2026-10-07 · Claude · 가산점 "확실한 것만 남기기"

- 요청·목적: 10/6 Codex 재검수 지적(P1 1·P2 6·P3 2) 처리 방식을 사용자가 정함 — 재추출 없이 계산만 줄이기.
- 변경 파일: `search/bonus.py`, `collect/extract_bonus.py`, `tests/test_bonus.py`·`test_extract_bonus.py`·`test_match_deh.py`·`test_notice_api.py`, 새 `eval/bonus_conservative_compare.py`, 새 `docs/notice_api/CODEX_BONUS_RECHECK_REQUEST_20261007.md`, 기준 문서(판정 9절·창구·결정 0008·현황·미해결·함정·`search`/`collect` 안내), 진행표.
- 전후 차이·선택 이유: 틀린 점수보다 "모름"이 낫다는 사용자 원칙. 합계 한도는 범위를 확인할 수 없어 자르지 않고 null로 바꿨다 — `bonus_items.points`가 "한도 적용 뒤"에서 "원문 배점"으로 바뀐다(답변서 문구와 달라짐 → 재검수 통과 뒤 알림에 포함). 공고 합계의 "확인된 부분합" 정의는 그대로(재검수에 판단 요청).
- 검증: 시험 778 통과·16 건너뜀(처음 5건 실패 — 근거에 N점이 없는 가짜 항목·옛 기대값·가짜 DB 칸 수 — 모두 시험 쪽을 새 규칙에 맞춤). `python -X utf8 -m eval.bonus_conservative_compare` → 열린 공고(모집 마감 아님 + 마감일 안 지남) 1,741건 전후 표, 재현 공고 값. 처음 실행은 `recruitment_status='open'`만 세어 221건(기업마당은 unknown)이라 버리고 조건을 고쳐 다시 실행. 8030 임시 서버 boot 오류 없음, 계약 시험 `--all` 16/16.
- 미검증·남은 문제: Codex 재검수, 서버 두 곳 반영(사용자), 배치 서버의 첫 14단계 실행(내일 09:00).
- 다음 단계: 재검수 → 조율 담당 알림.

### 2026-10-07 · Claude · 공고 서버 검색에서 벡터 DB(Chroma) 빼기

- 요청·목적: 10/6 결정(벡터 DB 미사용, 결과서 제출)을 코드에 반영하고, 결과가 같은지 확인.
- 작업 전 상태: `search/app.py`가 PC는 `data/vecstore/chroma`, 리눅스는 `ec2/data/vecstore/chroma`(또는 `VECSTORE_PATH`)를 열었다. PC 색인은 10/2분(2,714건)이라 그 뒤 공고가 의미 검색에서 빠졌다.
- 변경 파일: 새 `search/memvec.py`(MemoryCollection — Chroma와 같은 count·query(ids)·get 모양, 거리 1−내적, 같은 거리면 공고 ID 순; 공용 DB 읽기 `load`, 1,024차원·4,096바이트만, 지문 경고), `search/app.py`(`_collection`이 공용 DB 벡터를 올림·0건이면 예외, `boot` 출력·지문 경고, `dense_path` 정상 `memory`, `source` `vectors+bm25`, `/api/health` `vectors`, 머리말), 새 `tests/test_memvec.py`, `tests/test_match_rules.py`(기대값 `memory`), 새 `eval/vector_db_compare.py`, 기준 문서·폴더 안내.
- 전후 차이·선택 이유: 벡터 출처를 공용 DB로 정해(사용자 선택) PC·팀 EC2가 같은 최신 벡터를 쓴다. 인터페이스 모양을 유지해 평가 도구(`CorpusCollection` 등)가 고치지 않고 돈다. 비교는 같은 벡터로 임시 Chroma를 새로 만들어(사용자 선택) 방식 차이만 보이게 했다.
- 검증: `python -X utf8 -m unittest discover -s tests` → 771 통과·16 건너뜀. 처음 1건 실패(`test_boot_normal_has_no_errors` — 가짜 `_collection`이라 지문 정보가 비어 경고가 남) → 벡터 쪽 지문 정보가 없으면 판단하지 않게 고침. `python -X utf8 -m eval.vector_db_compare` → 질의 66, 벡터 2,825, chromadb 1.5.9: 의미 검색 상위 10 겹침 99.5%·순서 같음 63/66·1위 66/66, 추천 상위 3 같음 62/66(93.9%)·상위 10 같음 51/66, 의미 검색 6.58ms vs 7.55ms, `match` 384ms vs 395ms. 다른 4개 질의 중 2개는 상위 3 구성이 같고 순서만 다름. `PORT=8030 python -m search.app`(이 PC, 켤 때 34.9초) → `/api/health` 벡터 2,825·`boot_errors` 없음, 계약 시험 `--url http://127.0.0.1:8030 --all` 16/16, 2,825건 형식 오류 0, 건당 24ms. 임시 서버는 끔.
- 미검증·남은 문제: 팀 EC2 시험 서버 반영 전(사용자 실행). 배치 7단계·EC2 09:10 예약·Chroma 정합성 도구 정리는 이번 범위 밖. `search/app.py` 머리말의 `\.venv` 표기가 SyntaxWarning을 낸다(기존, 동작 무관).
- 다음 단계: 시험 서버 반영 → 바깥에서 `/api/health`·계약 시험.

### 2026-10-07 · Claude · 공고 내용 지문 하루 비교

- 요청·목적: 10/6에 정한 내용 지문(`cv2-`)이 수집 잡음 없이 내용이 바뀔 때만 바뀌는지 하루 지나 확인.
- 변경 파일: STATUS·`docs/tracking/status.md`(현황·남은 일 갱신). 코드 변경 없음.
- 검증: `.\.venv\Scripts\python.exe -X utf8 -m search.content_version --compare data/notice_api/content_version_20261006_cv2.json`(공용 DB 읽기만) → 이전 저장 10/6 00:00:04 UTC → 지금 10/7 00:00:03 UTC, common 2,765 · changed 14 · added 60 · removed 0, by_field `recruitment_status` 13 · `title` 1. 변화 공고를 DB에서 확인: `kstartup:176218`·`179190` 등은 `closed`(K-Startup 목록에서 빠져 모집 종료), `kstartup:179350` 제목 끝 "(수정)". 첨부·링크·접수기간 원본 같은 칸의 잡음 변화 0.
- 결론: `cv2-` 그대로 확정. 접두어를 올리지 않는다.
- 다음 단계: 조율 담당에게 "내용 버전 잠정 → 확정" 알림(사용자).

### 2026-10-06 · Claude · 팀 EC2 시험 서버 안내·확인과 답변서 주소 반영

- 요청·목적: 조율 담당에게 줄 공고 서버 주소. "답변서 공개 시험 서버 없음에서 해당 주소로 변경".
- 작업 전 상태: 팀 EC2 8000에 아무것도 없었음(사용자 `ss -ltn` 확인). 9/15 이후 그 서버에는 색인 갱신용 `~/s-brain`만 있었다.
- 변경: 서버 쪽은 사용자가 직접 했다(코드 복사·패키지·systemd·cron·보안그룹 — 단계는 STATUS 같은 날 항목). 저장소 쪽은 `docs/notice_api/05_reply/README.md`(머리 표·0절·질문 1·3·8·9·3절·4절·5절)와 STATUS.
- 전후 차이·선택 이유: 답변서가 "주소 없음"이던 것을 시험 서버 주소와 접속 조건(시험 기간만 전체 공개·인증 없음·가짜 신청 정보로만, 실제 연결 전 IP 제한)으로 바꿨다. 같은 문서 안에서 어긋나던 문장(함께 시험 미정, PC 색인 10/2 문제, PC 응답 시간)을 함께 맞췄다. 운영 위치·인증·동시 호출·가산점 정리는 그대로 미정.
- 검증: 바깥에서 `GET /api/health` 200(공고 2,765·색인 2,766(워터마크 포함)·`boot_errors` 없음), `/api/collection_status` 정상. 계약 시험 `python -m experiments.notice_api_contract --sbrain <임시>gent-orchestration --url http://43.201.90.238:8000` → 15개 통과(`reports/notice_api_contract_20261006T084646Z/`). systemd 로그로 재시작 반복(65회, 원인 8000 선점) 확인 후 해소. 참고: PowerShell에서 `git archive … | tar -x`는 파이프가 바이너리를 망가뜨려 실패 → `git archive -o 파일` 뒤 `tar -xf`로 해야 한다.
- 미검증·남은 문제: 동시 호출 안전성, 서버 재부팅 직후 첫 기동 시간, 메모리 여유(4GB에 MySQL과 공존).
- 다음 단계: 기준 문서 갱신, 실제 연결 전 IP 제한.

### 2026-10-06 · Claude · 공고 서버 API — 05 답변서

- 요청·목적: 조율 담당 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`, 10/3·10/4)에 답하는 문서. 사용자 요청 "답변서를 써줘".
- 작업 전 상태: 01~04 완료·push 됨. 요청서는 04 계약 시험에 쓴 `b8e7f50` 이후 바뀌지 않음(원격 diff 없음, 10/6 확인).
- 변경 파일: 새 `docs/notice_api/05_reply/README.md`. 진행표 `docs/notice_api/README.md` 05 줄, STATUS, `docs/tracking/status.md`, `docs/contracts.md`(생년월일 답·업력 상한 null 두 뜻·503 본문).
- 전후 차이·선택 이유: 조율 쪽이 답변서를 그대로 믿고 코드·화면 문구를 고치므로, 정하지 않은 것(배포 위치·인증·재시작 방식·동시 호출·가산점 정리·함께 시험)은 "미정"으로 쓰고 날짜를 약속하지 않았다(사용자 선택). 개인정보 최소화로 생년월일은 "아직 보내지 말아 달라". 요청서가 다르게 읽는 값(업력 상한 null = 제한 없음, 공개 시험 서버 있음, `support_amount_text`)을 바로잡았다. 사실 확인 중 새로 알게 된 것: 지금 PC 시험 서버는 10/2 뒤 공고가 하이브리드 추천에 아예 안 나온다(벡터 없는 공고는 RRF 결과에서 빠짐, `search/app.py` 하이브리드 경로), 수집 상태의 "최근 배치 실패·출처 실패" 판정은 배치 일지가 있는 기계에서만 작동한다.
- 검증: 답변서의 사실 주장을 코드와 대조(`search/collection_status.py`·`notice_api.py`·`content_version.py`·`app.py`·`hybrid.py`·`bonus.py`·`applicant.py`, 02·04 기록 수치). 적합도 최솟값은 `RRF_K=60`·`DEPTH=50`으로 계산(하이브리드 약 0.277, 단독 경로 약 0.555). 계획 단계에서 독립 검토 2회(결정 누락 점검·실행 가능성 점검)를 거쳐 지적을 반영. 코드 변경은 없고, 확인용으로 `python -X utf8 -m unittest discover -s tests` → 758개 통과·16개 건너뜀(실패 0).
- 미검증·남은 문제: 동시 호출 안전성, 재시작 중 응답 불가(약 20~25초) 처리, 내용 버전 하루 비교(10/7).
- 다음 단계: 사용자가 답변서를 보낸다. 10/7 배치 뒤 내용 지문 비교 → 바뀌면 조율 담당에게 먼저 알린다.

### 2026-10-06 · Claude · 공고 서버 API — 재검수 지적 보류·K-Startup 첨부 확인·04 계약 시험

- 요청·목적: Codex 재검수 확인 → 사용자가 개선 보류 후 다음 작업 진행을 결정. K-Startup 가산점이 없는 이유 확인과 첨부 확보 가능성 조사. 04 계약 시험.
- 작업 전 상태: 01~03 v4(미커밋), 8000은 v4로 켜짐. Codex 재검수 결과 "추가 수정 후 재검수 필요".
- 변경 파일: 새 `experiments/notice_api_contract.py`, 새 `docs/notice_api/04_contract_test/README.md`, 진행표·결정(`docs/notice_api/README.md`)·STATUS. 결과 `reports/notice_api_contract_20261006T035438Z/`. 판정표 페이지(artifact, 비공개) 게시.
- 전후 차이·선택 이유: 서비스 코드 변경 없음. K-Startup은 robots.txt `Disallow: /afile*/`(첨부 목록·다운로드 경로) 때문에 자동 수집하지 않기로 했다(파이썬 robotparser는 별표를 해석하지 못해 '허용'으로 잘못 답함 — 규칙을 직접 읽어 판단). 공공데이터포털 `kisedKstartupService01` 4개 기능을 1건씩 호출해 공고 첨부 칸이 없음, `prfn_matr`(우대 사항) 열린 221건 모두 빈 값, 외부 안내 주소 186건은 구글 설문·각 기관 사이트로 파일 0건임을 확인. 04는 조율 쪽 코드를 작업 트리 밖 임시 폴더에 `git archive`로 풀어 우리 `.venv`로 불렀다(pydantic 같은 판).
- 검증: 계약 시험 16개 통과 — T-C2 8회(카드 10·rank·시·도 바꾸기), G-01 40회(업력 사사오입 일치), 공고 없음 `ResourceNotFound`, 경로 없음 `ProviderError(404)`, 설립일 없는 사업자 판정 생략, 모든 공고 G-01 2,765건 형식 오류 0(65초). 첫 실행에서 내 시험 코드가 한글 경로(`/없는경로`)를 써서 urllib 인코딩 오류가 났고 영문 경로로 고쳐 다시 돌렸다. OpenAI·DB 쓰기 없음.
- 미검증·남은 문제: 조율 쪽 흐름 전체(워커·저장소·웹)는 범위 밖. 조율 기준 커밋 `b8e7f50`(10/5). 가산점 정확성은 보류 중.
- 다음 단계: 05 답변서.

### 2026-10-06 · Claude · Codex 검수(공고 서버 API 01~03) 13건 반영 — 가산점 추출기 v4·전량 재추출

- 요청·목적: 사용자 "코덱스가 리뷰 남겼는데 확인 바랄게". [검수](notice_api/CODEX_REVIEW_20261006.md)를 확인하고 반영했다. 사용자가 비용은 덜 신경 써도 된다고 해서 재추출까지 진행했다.
- 작업 전 상태: 01~03 미커밋. 검수 결론은 "수정 후 재검수 필요"(P1 2·P2 8·P3 3). 13건 모두 코드에서 재확인했다. v3 결과에서 같은 근거 문장이 점수 항목 여러 개로 나뉜 공고는 103건이었다.
- 변경 파일
  - `collect/extract_bonus.py`: v4. `build_parts`, `locate_all`, `_points_in`, `_total_supported`, `verify(complete)`, `plan_work` 3중 비교, `run_batch` 하루 누적, `--ids`.
  - `search/bonus.py`: `load` 최신성, `item_hit` 추가 조건·전남/광주, `_groups`·`_score_scope`·세부사업.
  - `search/app.py`: boot 가점 최신성, `Weights.bonus` 0.
  - `search/notice_api.py`: `served_status`.
  - `search/content_version.py`: active, cv2.
  - `collect/daily_pipeline.py`: 설명.
  - 새 `db/mysql_migration_008_notice_bonus_content_version.sql`.
  - 시험: `tests/test_extract_bonus.py`·`test_bonus.py`·`test_match_deh.py`·`test_notice_api.py`.
  - 문서: [응답서](notice_api/CODEX_REVIEW_RESPONSE_20261006.md)·03 README·01 README·진행표·FLOW·문서 지도·STATUS.
- 전후 차이·선택 이유: 지적별 내용은 응답서 1절에 있다. 순위 세기는 근거가 부족해 0으로 내렸다. 결과의 `bonus_score`는 그대로 나간다. 지어내지 않는 쪽을 택해 null이 늘었다.
- 검증
  - 표본 30건(검수와 같은 공고) v4 재추출 3회, 약 $0.20. 첫 판의 묶음 오남용·괄호 숫자 누락·같은 문구 두 번을 고쳤다.
  - 공용 DB `notice_bonus`에 칸 추가(008, 사용자 진행 지시). 전량 재추출 2,078행(LLM 969, 실패 0, 약 $1.79, `reports/bonus_full_20261006T024214Z/`).
  - 서버 읽기에서 뺀 행 0. 가상 신청자 '여성기업·벤처·경기 성남시' 가산점 48건(v3 62).
  - 전체 시험 758 통과(건너뜀 16).
  - 10/7 비교 기준 `data/notice_api/content_version_20261006_cv2.json`(cv1 대비 첨부 지문이 바뀐 공고 8건).
- 미검증·남은 문제
  - 사람 정답 없음(표본은 Codex AI 판정과 대조).
  - `points_source`를 LLM이 빼면 점수 null.
  - 병합 표 해석은 LLM 몫.
  - 서버 배치 복사본 미갱신. 8000은 옛 코드.
- 다음 단계: 사용자가 Codex 재검수를 맡긴다 → 04·05. 사용자는 이 대화를 여기서 멈추고 다른 채팅에서 이어 간다.

### 2026-10-06 · Claude · 공고 서버 API 03-2~3-5 — 가점 전량 추출·신청자별 가산점·순위 반영·매일 배치

- 요청·목적: 사용자 "3-2 진행해줘"(공용 DB 표 생성·667건 추출 승인), "3번까지 마무리되면 Codex 검토". 03 나머지를 마치고 Codex 검토 요청서를 쓴다.
- 작업 전 상태: 3-1 완료(추출기·표본). `notice_bonus` 표 없음.
- 변경: 공용 DB에 `notice_bonus` 생성(생성 전 없음 확인)·2,057행 적재. 코드 `collect/extract_bonus.py`(no_mention·bonus_info 대조·`--all`·`run_batch`), 새 `search/bonus.py`, `search/app.py`(boot 가점·결과 가산점·`Weights.bonus` 기본 0.2·`bonus_boost`), `search/notice_api.py`(`bonus_info`), `collect/daily_pipeline.py`(14단계·`--skip-bonus`·`--bonus-limit`), 새 `eval/bonus_rank_eval.py`, 시험(`test_extract_bonus` 17·`test_bonus` 12·`test_notice_api` +3·`test_match_deh`), 문서 `docs/notice_api/03_bonus/`·진행표·[Codex 검토 요청](notice_api/CODEX_REVIEW_REQUEST_20261006.md)·문서 지도·FLOW·STATUS.
- 전후 차이·선택 이유: 추천 결과의 `bonus_score`·`bonus_items`가 신청자 성별·인증·지역에 따라 채워진다(0 = 해당 가점 없음, null = 계산 못 함). 공고 상세 `bonus_info`. 가산점이 있는 후보가 있으면 같은 규칙 묶음 안에서 순서가 바뀐다(세기 0.2). 가산점 후보가 없으면 순서는 전과 같다. 판정 규칙은 실제 데이터 무작위 점검에서 너무 후한 4가지(장애인표준사업장·연구소 조건·여성연구자/가족친화·지역 근거 없는 항목)와 중복 집계, 너무 엄격한 1가지(대표이사 여성)를 고친 결과다.
- 검증: 전량 추출 실패 0·약 $1.05(추정). 전체 시험 745 통과·건너뜀 16. 가상 신청자 4종 분포(예: 여성기업·벤처·경기 성남시 62건 가산점). 순위 측정(`reports/bonus_rank_eval_20261006T015155Z/`) 세기 0.1~0.3 관련도 지표 변화 0. 실제 `boot()` + `/api/match` 가산점 형식 어긋남 0, 속성 없는 신청자 세기 0·0.2 순서 동일. 8000 서버는 건드리지 않았다(10/6에 켠 01·02 코드 그대로).
- 미검증·남은 문제: 사람 정답 없음(AI 참고). K-Startup은 가산점 늘 null. 순위 측정은 가점 공고가 드물어 효과가 작게 잡힘. 서버 매일 배치는 복사본이라 14단계가 아직 돌지 않는다. 10/7 지문 하루 비교 남음.
- 다음 단계: 사용자가 Codex 검토를 맡긴다. 그 뒤 04(조율 쪽 코드로 불러 보기)·05(답변서).

### 2026-10-06 · Claude · 공고 서버 API 03-1 — 가점 추출기와 표본 30건

- 요청·목적: 조율 요청서 3.2(신청자별 가산점). 사용자 결정 "실제로 만든다". 03을 5단계로 나눠 첫 단계로 공고문 가점 추출기를 만들고 표본으로 품질을 본다.
- 작업 전 상태: 01·02 완료(미커밋). 가점 데이터 없음. 10/6 조사: 열린 공고 중 가점 언급 약 610~670건(거의 기업마당), K-Startup은 첨부 미수집.
- 변경 파일: 새 `collect/extract_bonus.py`, 새 `tests/test_extract_bonus.py`(13개), 새 `db/mysql_migration_007_notice_bonus.sql`(실행 안 함), 문서 `docs/notice_api/03_bonus/README.md`·진행표·STATUS. 결과 `reports/bonus_sample_20261006T011805Z/`·`…T012116Z/`.
- 전후 차이·선택 이유: 서비스 동작은 바뀌지 않는다(추출기만 추가). 기존 추출기와 같은 원칙(문서에 적힌 것만, 근거 원문 필수, 근거가 없으면 코드가 버림). v1 결과를 30건 모두 읽고 고쳤다: 선정 뒤 혜택을 가점으로 잡음 → 지시문 규칙, 표 칸이 끼어든 근거를 지어낸 것으로 오판 → "같은 순서·가까이" 대조, 표의 단위 없는 숫자 점수 → 인정, 지역 17곳 → 상한, 가점 없음/모름 구분 → status. 청년 고용을 청년(나이)으로 분류 → v3 지시문.
- 검증: v1 → v2 같은 표본 30건 비교(혜택 오인 3건 해소, 점수 있는 항목 16 → 31). 새 검사를 v1 원본에 다시 적용해 효과를 호출 없이 먼저 확인. 시험 13개 통과. 유료 호출 약 $0.08(추정). DB 쓰기 없음.
- 미검증·남은 문제: 사람 정답 검증 없음(AI 참고). 웹 입력으로 맞출 수 있는 가점 종류가 적어 가산점이 null(정보 없음)인 공고가 많을 것이다. "최대 N점, 1점당 1점" 항목 점수는 최대값으로 적힌다.
- 다음 단계: 3-2(공용 DB `notice_bonus` 표 생성 + 667건 추출, 약 $0.9) — 사용자 승인 필요.

### 2026-10-06 · Claude · 공고 서버 API 02 — 공고 상세·자격 판정 창구

- 요청·목적: 조율 요청서 2.4·2.5. 조율 에이전트가 후보 공고를 고를 때 부르는 공고 상세와 자격 판정 창구를 연다. 자격 판정은 추천의 정형 필터와 같은 규칙이어야 한다.
- 작업 전 상태: 01 완료 직후(미커밋). 화면용 `/api/eligibility`만 있었고 판정 코드가 app.py 안에 있었다.
- 변경 파일: 새 `search/eligibility.py`(app.py 판정 본문을 그대로 옮김, `today`·판정표를 인자로), `search/notice_api.py`(상세·판정 창구, 지원 금액 읽기), `search/app.py`(화면용 판정이 새 함수를 부름 · boot에서 지원 금액 읽기), `tests/test_notice_api.py`(11개 추가), `tests/test_match_deh.py`(가짜 DB 보강), 문서 `docs/notice_api/02_detail_eligibility/`·진행표·FLOW·STATUS.
- 전후 차이·선택 이유: 새 창구 두 개가 생겼다. 화면용 판정 결과는 바뀌지 않는다. 규칙을 복사하지 않고 한 함수로 모은 것은 요청서가 "추천과 판정이 한 곳의 규칙에서 나오게" 해 달라고 했기 때문이다. 새 판정은 지원대상 유형·업력만 보고 접수기간·모집 상태는 보지 않는다. 판정표가 꺼져 있으면 본문 유형을 쓰지 않는다(추천 필터와 같음). 근거·정의는 [02 기록](notice_api/02_detail_eligibility/README.md).
- 검증: 전체 시험 713 통과·건너뜀 16. 실제 `boot()` 후 2,765건 × 신청자 5가지 = 13,825회에서 추천 필터와 다른 결론 0건. 옛 app.py(`99a0bc9`)와 화면용 판정 16,590회 비교 다름 0건. 공고 상세 2,765건 형식 오류 0. 유료 호출·DB 쓰기 없음. 8000 서버는 건드리지 않았다.
- 미검증·남은 문제: 사업자 신청자는 모든 공고에서 "지원대상 유형"이 확인 필요로 나온다(개인·법인 자동 판정 안 함, 9/28 결정). `support_amount_text`는 null. 05 답변서에 적는다.
- 다음 단계: 03(가산점), 사용자가 시작을 정한다.

### 2026-10-06 · Claude · 공고 서버 API 01 — 수집 상태 창구·추천 결과 키

- 요청·목적: 조율 담당(4nchez)의 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`)에 따라 공고 서버에 HTTP 창구를 연다. 사용자가 작업을 01~05로 나눠 하나씩 진행하고, 작업별 기록은 `docs/notice_api/`에 두기로 했다. 이번은 01.
- 작업 전 상태: 깨끗한 작업 트리(`99a0bc9`). 수집 상태 판정 함수는 있었지만 HTTP 창구가 없었고, 추천 결과에 내용 버전·가산점 키가 없었다.
- 변경 파일: 새 `search/notice_api.py`(수집 상태 창구), 새 `search/content_version.py`(공고 내용 지문·하루 비교 명령), `search/app.py`(창구 연결·boot에서 저장 시각과 지문 읽기·결과 키 3개), 새 `tests/test_notice_api.py`(16개), `tests/test_match_deh.py`(boot 가짜 DB 보강), `.gitignore`(`data/notice_api/`), 문서 `docs/notice_api/`(새)·`docs/README.md`·`docs/FLOW.md`·STATUS.
- 전후 차이·선택 이유: `GET /api/collection_status`가 생겼다. DB 판정에 더해 **서버가 메모리에 올린 공고가 24시간을 넘으면 정상 → 지연**으로 내린다(서버를 다시 켜야 새 공고가 반영되기 때문). DB를 못 읽으면 503. 추천 결과 한 건에 `content_version`(원문 칸 + 첨부 파일 바이트 SHA-256, 수집 시각·LLM 값 제외), `bonus_score: null`, `bonus_items: []`가 붙는다. 순위·필터 등 기존 동작은 바뀌지 않는다. 자세한 근거는 [01 기록](notice_api/01_status_match/README.md).
- 검증: 전체 시험 702 통과·건너뜀 16. 실제 DB 지문 2,765건 0.2초·재계산 동일·충돌 0. 실제 `boot()`(25.4초) 후 TestClient로 수집 상태 200 `정상`, 가짜 신청 정보로 추천 offset 0·10 각각 10건·필수 키 누락 없음. 8000 서버는 건드리지 않았다. 유료 호출·DB 쓰기 없음.
- 미검증·남은 문제: 지문이 날마다 수집 잡음으로 바뀌지 않는지는 10/7 배치 뒤 `python -m search.content_version --compare data/notice_api/content_version_20261006.json`으로 확인해야 한다. 이 PC의 8000은 옛 코드라 다시 켜야 새 창구가 열린다.
- 다음 단계: 02(공고 상세·자격 판정), 사용자가 시작을 정한다.

### 2026-10-02 · Claude · 매일 수집 배치를 PC 에서 서버(EC2)로 전환

- 요청·목적: PC 를 꺼 둔 날(10/1 병가) 수집이 멈추는 문제를 없앤다. 웹 배포용으로 만든 개인 계정 EC2 `sbrain-web` 에서 배치만 돌린다(공고 매칭 8000 은 옮기지 않음). 사용자 결정: 시험 1~3단계 뒤 "전환해 줘".
- 작업 전 상태: 10/2 08:43 PC 배치가 밀린 실행으로 돌아 09:05 `exit=0`(공고 2,714건, K-Startup 모집 종료 292건 — 모두 마감일 지난 공고, 인계서의 "10/1 배치 뒤 닫은 건수 확인" 과제는 이것으로 확인). 09:00 정규 실행은 실행 중이라 무시됐다(`IgnoreNew`).
- 변경 파일(data-collection 코드는 고치지 않았다): 저장소 루트 `deploy/` 에 `batch.Dockerfile`·`batch.Dockerfile.dockerignore`·`batch-requirements.txt`(PC .venv 버전 고정, torch 는 CPU 판)·`run_batch.sh`(run_daily.bat 의 리눅스판, 같은 `data/run.log` 에 기록) 추가, `docker-compose.yml` 에 `batch` 서비스(profile) 추가, `deploy/README.md` 에 절차·시험 기록.
- 서버 배치: `~/sbrain/data-collection`(이 PC 작업 폴더 10:54 복사, `.venv`·`docs`·`ml`·`.env` 제외), `.env` 는 배치에 필요한 키 8개만(권한 600), DB CA 는 `~/sbrain/secrets/ec2-ca.pem`(compose 가 `MYSQL_SSL_CA` 를 덮음), BGE-M3 는 볼륨 `sbrain_hf_cache` 에 **리비전 `5617a9f…` 고정**(다르면 `shared/embed.fingerprint` 가 바뀌어 전량 재임베딩).
- 검증(DB 쓰기 0, LLM 0):
  - dry-run: AWS 에서 두 API 응답(K-Startup 215 = 서버 보고, 기업마당 1,444).
  - 예약과 같은 빈 환경 dry-run `exit=0`. 이때 `docker compose run` 이 표준입력을 삼켜 부른 쪽 스크립트가 끊기는 문제를 찾아 `run_batch.sh` 에 `< /dev/null` 을 붙였다.
  - 팀 DB 암호화 SELECT 2,714건 0.3초, `embed.run(plan_only=True)` "그대로 2,714 · 만들 것 0", 설정 지문 PC 와 같음.
  - 실제 공고 112건 임베딩(저장 안 함) 109.6초, 프로세스 최대 2,435MB, 서버 여유 메모리 최저 2,058MB / 3,811MB.
- 전환: PC 예약 작업 `Disable-ScheduledTask`(삭제 안 함) → 시험으로 바뀐 서버 `data/` 를 `~/sbrain/_old/data_test_20261002` 로 옮기고 PC `data/` 재복사(서버 run.log 마지막 줄이 PC 와 같은 09:05 `exit=0`) → crontab `0 0 * * *` 등록, cron active.
- 미검증·남은 문제: 서버에서의 실제 실행(DB 쓰기·LLM)은 아직 없다. 첫 실행은 10/3 09:00. 이 PC 의 8000 색인은 더 이상 갱신되지 않는다. 서버 코드는 복사본이라 PC 코드 수정이 자동 반영되지 않는다. 팀 EC2 의 09:10 Chroma 갱신과 겹치는 기존 문제(인계서 4절)는 그대로다.
- 다음 단계: 10/3 09:20 쯤 서버 run.log·DB 점검, 정상이면 `_old` 정리.

---

2026-09-30 이전 기록은 [archive/WORKLOG_202609.md](archive/WORKLOG_202609.md)로 옮겼다(2026-10-07).
