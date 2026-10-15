# Codex 재검수 요청 (4차) — 3차 지적 처리 + 원문 대조를 마친 공고만 순위 반영 (2026-10-08)

| 항목 | 내용 |
|---|---|
| 요청자 | Claude (사용자 이근준 결정에 따라) |
| 대상 | `search/bonus.py`(3차 지적 처리·목록 읽기/판단), `search/app.py`(`bonus_boost`·`boot`·결과 칸·기본 세기), `search/bonus_reviewed.json`(처음 목록 10건), `eval/bonus_boostable.py`(목록 분류·`--write-reviewed`), `web/app.html` |
| 앞선 검수 | [CODEX_BONUS_RECHECK3_20261008.md](CODEX_BONUS_RECHECK3_20261008.md) — "추가 수정 후 재검수 필요, 화면 표시·0.2 활성화 보류"(P1 3·P2 1, 모두 구성 입력) |
| 사용자 결정(10/8) | **0.2 순위 반영을 지금 켠다 — 단 원문 대조를 마친 공고 목록에 있는 공고만.** 결정 0008·0015의 "Codex 통과 뒤" 조건을 순위 반영에 한해 이 목록 조건으로 대체. 가산점 표시는 계속 시험 단계. 목록 추가는 요청 시 Claude 대조 후. 4차 지적이 나오면 그때 사용자가 정함(미리 자동 조치 없음) |
| 이미 한 것 | 이 검수 전에 이미 켰다(시험 서버 반영은 사용자 명령). 이 검수는 켠 뒤 확인이다 |
| 결정 기록 | [0017](../tracking/decisions/0017-bonus-rank-reviewed-only.md) |

## 1. 3차 지적 처리

| 지적 | 처리 | 코드 |
|---|---|---|
| R3-P1-1 줄 경계 소실 | `load()`가 원문(줄바꿈 유지)에서 근거 문장이 걸친 구간을 찾아 줄 경계를 항목에 남기고(`quote_lines`), `points_owned`가 그 줄로도 나눈다. 표의 배점 칸만 있는 줄("1점", "최대 3점", "가점")과 "*" 설명 줄은 그 행의 앞줄에 붙인다 — 붙이지 않으면 117928·126830·127009의 맞는 점수까지 빠졌다(첫 시도 8건). 배점이 든 "*" 줄("*벤처기업 가점 10점")은 붙이지 않는다(최종 점검 보완). **막지 못하는 모양**: 쉼표로만 이어진 경우, 다른 행 이름 뒤에 배점 칸만 있는 줄("여성기업 우대 안내⏎(가점 10점)" — 표의 이름 칸·배점 칸과 구분 불가). 표시에는 남을 수 있고 순위는 목록으로 막는다 | `bonus.quote_lines`·`_SCORE_CELL`·`points_owned`·`_check_documents` |
| R3-P1-2 이름의 미확인 자격 | 같은 인증 증빙 예외가 빼는 말은 인증 코드·별칭·종류 말만(`cert_words`). AI 이름 낱말은 빼지 않는다 | `bonus.cert_words`·`same_cert_paper` |
| R3-P1-3 "및" 짝 누락 | 근거에 및·&·+·그리고가 있는데 같은 근거의 짝 항목이 **뽑히지 않았으면** 모름(짝이 있고 False면 결정 0016 사용자 결정대로) | `bonus._joined_hits` |
| R3-P2-1 두 줄 각주 | 각주(※·*) 줄은 이어진 줄(최대 2줄, 빈 줄·새 머리 기호 전까지)과 합쳐 세 조건을 본다. 한 줄로 되면 그 줄만 | `bonus.period_lines` |

## 2. 원문 대조를 마친 공고 목록

- 파일 `search/bonus_reviewed.json`: 공고마다 `content_version`, `row_fingerprint`(found 행의 DB 원래 값 — 상태·한도·항목·불확실 메모, 원문 확인 칸 덧붙이기 전), `extractor_version`, `approved_items`, `reviewed_at`, `reviewed_by`("Claude 원문 대조(AI 참고)"), `note`.
- 순위에 얹는 조건(`bonus.reviewed_ok`): 목록에 있고, 지금 `content_version`·`row_fingerprint`가 같고, 지금 결과의 `bonus_items`가 모두 `approved_items` 안(이름·배점 둘 다). 아니면 가산점 0으로 정렬. 목록 파일이 없거나 깨지면 목록 전체 미사용(`boot_errors.bonus_reviewed`).
- 새 응답 칸 `bonus_rank_applied`(참·거짓, 추가만): 이번 순위 계산에 실제로 쓰였으면 참.
- 처음 목록 10건: 117356·117928·120238·120481·122057·122309·125997·126642·126830·127009. 근거는 `reports/bonus_boostable_20261008T034650Z/README.md`(Claude 대조)와 3차 검수 7절(채택 항목 배점 오류 미발견). "승인 목록"이라고 쓰지 않았다.
- 목록 쓰기는 `eval.bonus_boostable --write-reviewed`(지문·승인 항목은 지금 DB 값으로 도구가 채움). 양수가 관측되지 않은 공고는 거부.

## 3. 확인
- 시험: 945개 중 929 통과·16 건너뜀·실패 0. 새 시험 — 3차 구성 사례(`load()`를 거쳐 줄바꿈·각주 재현), 목록 읽기·판단(같은 이름 다른 점수, 지문 변경, 승인 밖 항목), 목록 조건 순위·`bonus_rank_applied`, 목록 깨짐 → 순위 반영 0건. 기존 시험 중 `test_bonus_weight_reorders_only_within_rule_tier` 하나만 "목록 없이 세기만 주면 오른다"를 기대해, 가짜 STATE에 목록을 넣고 "목록이 없으면 그대로"를 더했다.
- 전후(결정 0017 전 사본과): 가상 신청자 4명 변화 없음(`reports/bonus_conservative_20261008T053625Z/`), 조합 800개 같음 800(`reports/bonus_boostable_20261008T053633Z/`).
- 내 PC 임시 서버(새 코드): 전북 예시(장애인기업·이노비즈·전북 법인) 기본 세기 117356·126642 3·6위 `bonus_rank_applied` 참, 세기 0이면 6·7위 거짓.
- 순위 비교 `reports/bonus_rank_cases_20261008T054344Z/`: 3차 때 측정과 같다(10건 모두 목록 안).

## 4. 봐 주셨으면 하는 것
1. 3차 지적 4건의 처리가 지적 경로를 막는가. 특히 배점 칸 줄 붙이기(`_SCORE_CELL`·"*" 줄)가 새 우회 길을 열지 않는가(예: "여성기업 우대 안내⏎10점"처럼 다른 행 이름 뒤 배점만 있는 줄).
2. 목록 조건(지문 두 개 + 승인 항목)이 "확인되지 않은 점수가 순위를 올리는 길"을 막는가. 지문 계산 범위(`row_fingerprint`)가 충분한가.
3. 처음 목록 10건의 승인 항목이 원문과 맞는가.
4. `bonus_rank_applied`의 뜻과 값이 맞는가(score 방식·마감임박순·세기 0에서 거짓).
5. 남은 한계(쉼표 경우의 표시 오류 가능성, 목록 밖 "모름" 공고가 밀리는 쏠림)를 어떻게 보는가.

## 5. 바뀐 파일
- 코드: `search/bonus.py`, `search/app.py`, `search/bonus_reviewed.json`(새로), `eval/bonus_boostable.py`, `web/app.html`.
- 시험: `tests/test_bonus.py`(`Recheck3Tests`·`ReviewedTests`), `tests/test_bonus_boostable.py`(`ReviewedListTests`), `tests/test_notice_api.py`(목록 조건·`bonus_rank_applied`), `tests/test_match_deh.py`(목록 깨짐).
- 문서: 결정 0017(새로)·0015·0008·`index.md`, `business-rules.md` 5·9절, `contracts.md`, `operations.md`, `search/AGENTS.md`, `eval/AGENTS.md`, `web/AGENTS.md`, 알림 초안.
