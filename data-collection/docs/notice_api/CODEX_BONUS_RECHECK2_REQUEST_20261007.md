# Codex 재검수 요청 (2차) — 가산점 재검수 지적 처리 (2026-10-07 오후)

| 항목 | 내용 |
|---|---|
| 요청자 | Claude (사용자 이근준 결정에 따라) |
| 대상 | 신청자별 가산점 계산 `search/bonus.py`(+ 공고 서버 기동 `search/app.py`), 가점 하루 호출 상한 `collect/extract_bonus.py` |
| 앞선 검수 | [CODEX_BONUS_RECHECK_20261007.md](CODEX_BONUS_RECHECK_20261007.md) — "추가 수정 후 재검수 필요. 가산점 화면 표시 승인 보류"(P1 3·P2 3·P3 1) |
| 사용자 결정(10/7 오후) | ① `bonus_score` = **확인된 가산점 부분합**(B-P2-2의 2안, 결정 [0012](../tracking/decisions/0012-bonus-confirmed-partial-sum.md)) ② 짚은 틈은 **모두 null로 막기** ③ AI 재호출·재추출 없음, 순위 반영 0 유지 |
| 하지 않은 것 | 가점 재추출(공용 DB `notice_bonus`·추출기 v4 그대로), 응답 키 변경, 순위 반영, 조율 담당에게 보내기(초안만), 서버 반영(명령만 준비) |

## 1. 지적별 처리

| 지적 | 처리 | 코드 |
|---|---|---|
| B-P1-1 `N점` 존재만 확인 | (가) 근거 문장에 **서로 다른 "N점" 값이 둘 이상**이면 점수 인정 안 함(같은 값 반복은 허용). (나) 근거 문장이 **지금 공고 원문에 공백만 다르고 그대로 이어져 있지 않으면** 그 항목은 모름(None). 원문 범위는 가점 추출과 같다(본문 + 지원대상 + active·ok 첨부). 공고 서버가 켤 때 `load()`가 found 행만 확인해 `item['in_document']`를 붙인다. 원문을 읽지 못하면 found 행 `document_check='failed'` → null, `boot_errors.bonus_documents`에 이유 | `bonus.points_supported`·`documents`·`_check_documents`·`item_hit`, `app.boot` |
| B-P1-2 group 오분류 | 한 범위 안에서 (가) 점수로 고른 항목 중 **group은 다른데 근거 문장(공백 무시)·점수가 같은 것**이 있으면 null, (나) 점수 있는 묶음에 항목이 둘 이상인데 근거에 **"각"**(앞뒤가 한글이 아닌 단독 글자)이 있으면 null. 같은 quote 일괄 병합으로 되돌리지 않았다 | `bonus._score_scope` |
| B-P1-3 상한 불확실 | found인데 **불확실 메모(uncertain)가 하나라도 있으면 null**. GAP_WORDS·DUP_WORDS 구분은 없앴다(단어 목록에 기대지 않음) | `bonus.score` |
| B-P2-1 숨은 추가 요건 | 항목 글(이름·설명·근거)에 `CONDITION_WORDS`(모두·이내·최근·이상·이하·미만·초과·기준·한함·한정·경우·단서·회당·"단,")가 있으면 해당 → 모름. `extra_conditions`가 비어도 본다. 청년의 "만 N세 이하·미만" 구절은 이 검사에서 뺀다. 해당 아님은 그대로 | `bonus.item_hit` |
| B-P2-2 부분합 vs 총합계 | 2안(부분합 유지 + 계약·화면 문구 명시). `docs/contracts.md`·`business-rules.md` 9절·결정 0012에 적었다. 조율 담당 알림 초안: [BONUS_NOTICE_DRAFT_20261007.md](BONUS_NOTICE_DRAFT_20261007.md)(사용자가 보냄) | 문서 |
| B-P2-3 동시 실행 상한 | `run_batch`가 잔여량 읽기 → `run_full`(호출 수 예약 `on_calls` 포함) → 기록을 **하루 기록 파일 옆 잠금 파일(`…json.lock`, `collect/job_lock`)** 안에서 한다. 이미 잡혀 있으면 부르지 않고 `{'error': 'bonus_busy: …', 'saved': 0}`(배치 경고 → 종료 코드 4). 손으로 돌리는 `--all --limit N`은 하루 상한을 쓰지 않으므로 범위 밖 | `extract_bonus.run_batch`·`_run_batch_locked` |
| B-P3-1 설명 불일치 | `bonus.py` 머리말을 지금 규칙으로 다시 썼다(부분합 정의, 세부사업은 "결과가 모두 같고 공통 항목만으로 같은 점수일 때만 꼬리표 없이"). 05 답변서의 "한도 적용 뒤 점수" 설명은 알림 초안에서 정정한다(답변서는 이미 전달돼 고치지 않음). `FUTURE_WORDS` "이전" 오탐은 과잉 null로 받아들인다고 기준 문서에 적었다 | `bonus.py`, 문서 |

규칙끼리는 모두 "해당 → 모름" 또는 "점수 → 없음/null" 방향이라, 새 규칙은 결과를 **양수 → null 쪽으로만** 움직인다(4·5절 확인).

## 2. 확인

### 2.1 단위 시험
`.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` → **884개 중 868개 통과·16개 건너뜀(MySQL 통합 시험), 실패 0**.

새 시험:
- `tests/test_bonus.py` `RecheckTests`: 재검수 6절 재현 입력 전부 — 2점·10점 섞인 전체 인용, 이어 붙인 인용(`in_document=False`), 벤처 g1·이노비즈 g2 분리 10점(→ null, 하나만 해당이면 10), 122309 "각 1점" 한 묶음, 117356 한도 불확실 8점, "가점표를 파악하지 못했음", 117356 "본사 및 사업장 모두", "최근 3년 이내 벤처", 청년 나이 구절, 깨끗한 공고는 그대로.
- `LoadTests`: 원문 이어짐 확인·조각 경계 넘는 일치 불인정·원문 읽기 실패 → found null·none 0 유지.
- `tests/test_extract_bonus.py` `test_daily_limit_holds_under_concurrent_runs`: 재검수 2.3 재현(시작 250·상한 300). 첫 실행이 잠금을 잡은 동안 둘째 실행은 `bonus_busy`, 최종 기록 **300**(전에는 350).

기대값을 바꾼 기존 시험(새 규칙이 일부러 바꾼 것):
- `ConservativeTests.test_independent_bonuses_in_one_sentence`: 123858 4점 → null(근거에 1점·3점이 섞임, "각"인데 한 묶음).
- `ConservativeTests.test_uncertain_reading`: "중복 인정 여부" 메모 + 1묶음 3점 → null.

### 2.2 실제 DB 전후 비교(공용 DB SELECT만)
`python -X utf8 -m eval.bonus_conservative_compare --old <10/7 오전 bonus.py>` → [`reports/bonus_conservative_20261007T024147Z/`](../../reports/bonus_conservative_20261007T024147Z/)(예전 계산 파일 `bonus_before.py` 함께 보관). 열린 공고 1,741건, 가점 행 2,077건(추출기 v4).

| 가상 신청자 | 10/7 오전 null · 0 · 있음 | 지금 null · 0 · 있음 |
|---|---|---|
| 속성 없음 | 719 · 1,022 · 0 | 719 · 1,022 · 0 |
| 여성 · 서울 | 706 · 1,035 · 0 | 707 · 1,034 · 0 |
| 여성기업 · 벤처기업 · 경기 성남시 | 701 · 1,033 · 7 | 706 · 1,032 · 3 |
| 남성 · 장애인기업 · 이노비즈 · 전남광주 | 701 · 1,033 · 7 | 706 · 1,032 · 3 |

바뀐 것은 "가산점 있음 → null"과 "0 → null"뿐이다. null → 양수, 점수 바뀜은 0건이다.

| 공고(접두어 `bizinfo:PBLN_000000000`) | 오전 → 지금 | 이유 |
|---|---|---|
| 117356 | 8·5 → null | 불확실 메모(한도 확인 불가) |
| 122057 | 10·10 → null | 불확실 메모(가점 합계 불일치) |
| 122309 | 4·1 → null | 불확실 메모(각 1점 묶음 처리) |
| 123858 | 4·1 → null | 근거에 1점·3점 섞임 |
| 117928 | 1 → 1 | 여성기업 1점, 근거가 원문에 그대로 있음 |
| 120481 | 10·10 → 10·10 | "벤처, 이노비즈, 메인비즈 기업 : 10점" 한 묶음 |
| 122147 | 1·1 → 1·1 | 벤처기업확인서(1점)·Inno-Biz 확인서(1점) |
| 126642 | 장애인기업 5 → 5 | "⑧ 여성기업 및 장애인 기업(5점)", 한도 5 |

### 2.3 계약 시험
이 PC 임시 서버(8030, 끝나고 끔)로 조율 쪽 실제 연결 코드(`origin/feature/SB-87-init-supervisor-integration`) `--all` → **16개 확인 실패 0**, 2,825건 형식 오류 0(`reports/notice_api_contract_20261007T024341Z/`). `/api/health` `boot_errors` 없음. 가점 2,077건 로드(내용이 바뀌어 뺌 1).

## 3. 봐 주셨으면 하는 것

1. 남은 양수 4곳(117928·120481·122147·126642)이 원문으로 정당한가.
2. 이번 규칙으로 막히지 않는 틀린 양수 경로가 남았는가. 특히:
   - 근거가 원문에 그대로 있고 "N점"도 하나뿐인데 다른 항목 배점인 경우(예: 표에서 이름 칸과 배점 칸이 같은 줄로 이어진 경우).
   - group이 다르고 근거도 다른데 실제로는 택1인 경우.
3. `CONDITION_WORDS`가 지나치게 넓거나 좁은가. 과잉 null은 받아들이는 방침이다.
4. 부분합 정의와 알림 초안 문구가 조율 계약 쪽에서 오해 없이 읽히는가.
5. 잠금 범위(`run_batch`만, 관리자용 `--all`은 밖)로 하루 상한 보장이 충분한가.

## 4. 바뀐 파일

- 코드: `search/bonus.py`, `search/app.py`(boot), `collect/extract_bonus.py`.
- 시험: `tests/test_bonus.py`, `tests/test_extract_bonus.py`.
- 평가 도구: `eval/bonus_conservative_compare.py`(`--old` 옵션, 관찰 공고 추가).
- 문서: `docs/contracts.md`, `docs/business-rules.md` 9절·용어표, 결정 0008·0012·목록, `search/AGENTS.md`, `docs/notice_api/README.md`, 이 요청서, 알림 초안.

결과는 같은 폴더에 `CODEX_BONUS_RECHECK2_20261007.md`로 남겨 주세요.
