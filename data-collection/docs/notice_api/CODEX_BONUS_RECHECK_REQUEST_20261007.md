# Codex 재검수 요청 — 가산점 "확실한 것만 남기기" (2026-10-07)

| 항목 | 내용 |
|---|---|
| 요청자 | Claude (사용자 이근준 결정에 따라) |
| 대상 | 신청자별 가산점 계산 `search/bonus.py`, 가점 하루 호출 기록 `collect/extract_bonus.py` |
| 앞선 검수 | [CODEX_REVIEW_RECHECK_20261006.md](CODEX_REVIEW_RECHECK_20261006.md) — "추가 수정 후 재검수 필요"(P1 1·P2 6·P3 2) |
| 사용자 결정(10/7) | AI를 다시 부르지 않고 **계산 규칙만 줄여 "확실한 경우만 점수, 나머지는 모름(null)"**. 순위 반영 세기 0 유지. 이 재검수를 통과하면 조율 쪽에 "화면에 써도 된다"고 알린다 |
| 하지 않은 것 | 가점 재추출(공용 DB `notice_bonus`·추출기 v4·`EXTRACTOR_VERSION` 그대로), 응답 키 변경, 순위 반영 |

## 1. 지적별 처리

| 지적 | 처리 | 코드 |
|---|---|---|
| R-P1-1 다른 항목 배점·연번 승인 | 근거 문장(`quote`) 안에 그 점수가 "N점"으로 직접 있을 때만 점수 인정. `points_source`가 있으면(떨어진 칸에서 가져옴) 점수 없음. 숫자만 있으면(연번 가능) 점수 없음 | `bonus.points_supported` |
| R-P2-1 같은 quote 독립 가점 합침 | 묶음은 같은 `group` 이름일 때만. quote 동일성으로는 묶지 않음(이름·quote가 같은 중복 추출만 하나로) | `bonus._groups` |
| R-P2-2 비어 있는 extra_conditions로 이전 조건 무시 | 항목 글(이름·설명·근거)에 `FUTURE_WORDS`(이전·이주·유치·예정·희망·신규 채용·신규 고용)가 있으면 해당이어도 None | `bonus.item_hit` |
| R-P2-3 complete=true여도 표 누락·none 과확정 | `uncertain`을 읽는다. `none` + 불확실 사항 있음 → null. `found` + 불확실 사항에 `GAP_WORDS`(누락·빠짐·발췌·일부·잘림·확인 불가·확인할 수 없·불명확·표 전체) → null. `found` + "중복" → 점수 있는 해당 묶음 2개 이상이면 null | `bonus.load`·`bonus.score` |
| R-P2-4 세부사업 최대값 | 세부사업별 결과가 **모두 같을 때만** 그 값(공통 항목만으로 같은 점수면 꼬리표 없이), 다르면 null | `bonus.score` |
| R-P2-5 항목 한도를 전체 한도로 | 합이 `max_total_points`를 넘으면 자르지 않고 null. 이하면 그대로. 그래서 `bonus_items.points`는 원문 배점 그대로 | `bonus._score_scope` |
| R-P2-6 호출 기록 손상 시 0 | 파일이 없으면 0, **있는데 못 읽으면 `DailyRecordError` → 그날 호출 안 함**(`{'error': 'daily_record_unreadable…'}`, 종료 코드 4). 쓰기는 임시 파일 → fsync → `os.replace` | `extract_bonus._read_daily`·`_daily_used`·`_daily_add`·`run_batch` |
| R-P3-1 certifications 미입력/없음 | 계약 문구로 처리: `[]`·키 없음 모두 "확인된 없음"(10/6 답변서에 적어 전달함). 코드 변경 없음 | — |
| R-P3-2 같은 점수 선택지 순서 | 묶음 안 같은 점수면 이름순 첫 항목 | `bonus._score_scope` |

공고 합계는 "점수 있는 해당 묶음의 합"이다 — 다른 묶음이 모름이어도 확인된 묶음만 더한다(확인된 부분합). 이 정의는 바꾸지 않았다. 판단 단어(`FUTURE_WORDS`·`GAP_WORDS`·`DUP_WORDS`)는 `search/bonus.py` 상수다.

## 2. 확인한 것

- 시험 `python -X utf8 -m unittest discover -s tests` → **778개 통과·16개 건너뜀**. 새 시험 `tests/test_bonus.py` `ConservativeTests`(재검수 재현 입력: "여성기업 가점 2점. 벤처기업 가점 10점."의 points_source 10점 불인정, "1 여성기업 가점" 연번 불인정, 123858 "벤처·이노비즈·메인비즈 각 1점, 여성기업 3점" → 벤처+여성기업 4점, 117751 공장 이전 → None, none+uncertain → null, 누락 uncertain → null, 중복 uncertain + 2묶음 → null, 같은 점수 이름순), 기존 시험 기대값 갱신(세부사업 다름 → null, 한도 초과 → null), `tests/test_extract_bonus.py`(깨진 기록 → 호출 안 함, 원자적 저장·깨진 파일 보존).
- 전후 비교 `python -X utf8 -m eval.bonus_conservative_compare`(공용 DB SELECT만, 예전 = git HEAD `search/bonus.py`) → `reports/bonus_conservative_20261007T013412Z/`. 열린 공고 1,741건:

| 가상 신청자 | 예전 null · 0 · 있음 | 새 null · 0 · 있음 |
|---|---|---|
| 속성 없음 | 707 · 1,034 · 0 | 719 · 1,022 · 0 |
| 여성 · 서울 | 694 · 1,047 · 0 | 706 · 1,035 · 0 |
| 여성기업 · 벤처기업 · 경기 성남시 | 670 · 1,045 · 26 | 701 · 1,033 · 7 |
| 남성 · 장애인기업 · 이노비즈 · 전남광주 | 675 · 1,045 · 21 | 701 · 1,033 · 7 |

  - 실제 공고: 123858 벤처기업·여성기업 신청자 3 → **4점**, 117751 충남 천안시·여성기업 신청자 10 → **null**, 126504(none + "구체적 점수 없음" 불확실) 0 → **null**, 125856·125935·126562는 null 유지.
- 이 PC 임시 서버(8030)로 조율 쪽 실제 연결 코드 계약 시험 `--all` → 16/16, 2,825건 형식 오류 0(`reports/notice_api_contract_20261007T013609Z/`).

## 3. 봐 주셨으면 하는 것

1. 이 규칙에서 **틀린 양수 점수**가 나가는 경로가 남았는가(특히 표 형식 공고, `group`을 AI가 잘못 나눈 경우, "N점"이 근거에 있지만 다른 항목 것인 경우).
2. `FUTURE_WORDS`·`GAP_WORDS`가 너무 넓거나 좁은가(예: "이전 실적"의 "이전"은 고용·실적 항목이라 원래 모름이지만, 지역·인증 항목에서 오탐이 있는지).
3. "확인된 부분합" 정의(다른 묶음이 모름이어도 확인된 묶음만 더함)가 조율 쪽 계약("이 신청자가 그 공고에서 받을 수 있는 가산점 합계")과 어긋나는지 — 어긋나면 어떻게 알릴지.
4. 하루 호출 기록 보호가 동시 실행에서도 충분한지.

## 4. 바뀐 파일

`search/bonus.py`, `collect/extract_bonus.py`, `tests/test_bonus.py`, `tests/test_extract_bonus.py`, `tests/test_match_deh.py`(가짜 DB 행에 `uncertain` 칸), `tests/test_notice_api.py`(근거 문장에 "N점"), 새 `eval/bonus_conservative_compare.py`, 기준 문서(판정 원칙 9절·창구 약속·결정 0008·현황·미해결·함정·폴더 안내).

결과는 같은 폴더에 `CODEX_BONUS_RECHECK_20261007.md`로 남겨 주세요.
