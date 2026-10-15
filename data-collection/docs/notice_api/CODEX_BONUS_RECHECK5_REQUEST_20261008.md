# Codex 재검수 요청 (5차) — 4차 지적 처리 + 원문 대조된 가산점만 화면 사용 (2026-10-08)

| 항목 | 내용 |
|---|---|
| 요청자 | Claude (사용자 이근준 결정에 따라) — 보낼지는 사용자가 정한다 |
| 대상 | `search/bonus.py`, `search/app.py`, `search/bonus_reviewed.json`, `eval/bonus_boostable.py`, `eval/bonus_conservative_compare.py`, `web/app.html` |
| 앞선 검수 | [CODEX_BONUS_RECHECK4_20261008.md](CODEX_BONUS_RECHECK4_20261008.md) — P1 0, P2 3·P3 1, 목록 10건·31개 항목 오류 없음 |
| 사용자 결정(10/8) | 4건 수정 + **조율 쪽 화면에 가산점 사용 허용 — 원문 대조된 공고만**(새 칸 `bonus_verified`), 0·null은 화면에 아무것도 안 보임. 결정 0008·약속 문서의 "Codex 통과 뒤 화면 사용"을 이 조건으로 대체 |
| 이미 한 것 | 이 요청 전에 시험 서버 반영(사용자 명령)과 알림 발송을 할 수 있다 — 켠 뒤 확인이다 |
| 결정 기록 | [0018](../tracking/decisions/0018-bonus-display-verified-only.md) |

## 1. 4차 지적 처리

| 지적 | 처리 | 코드 |
|---|---|---|
| R4-P2-1 배점 없는 "*" 줄 | 앞줄에 자격 이름(`CERT_ALIASES` 인증 이름·별칭, `KIND_WORDS` 종류 말)이 없을 때만 붙임. "벤처기업 가점 10점⏎* 여성기업 우대 안내"의 여성기업 10점 → null, 127009 "혁신형 중소기업⏎1점⏎* 이노비즈…" 그대로 | `bonus._has_qualification`·`quote_lines` |
| R4-P2-2 목록 값 → HTTP 500 | `load_reviewed`가 지문 세 개·승인 항목 이름(비어 있지 않은 글자)·점수(참거짓 아닌 유한한 양수)를 검사, 어긋나면 전체 거부. 요청 중 목록 판단 예외는 그 공고를 대조 안 됨으로(500 없음) | `bonus.load_reviewed`, `app.bonus_verified` |
| R4-P2-3 첨부 글 변경 미감지 | 원문 지문 `evidence_fingerprint`(본문·지원대상·지금 달린 추출 성공 첨부 글, 줄바꿈 표기 통일, 정렬, 구분 글자로 이음, found 행만)를 목록에 저장·비교 | `bonus.evidence_fingerprint`·`_check_documents`·`reviewed_ok` |
| R4-P3-1 화면 문구 | 대조됨: "원문 대조됨" + "순위 반영됨 / 세기 0이라 순위 미반영 / 이번 검색에서는 순위 미반영", 대조 안 됨: "원문 대조 전"만 | `web/app.html` |

## 2. 화면 사용 허용
- 새 칸 `bonus_verified`(참·거짓, 추가만): 목록에 있고 지문 세 개가 같고 결과 항목이 모두 승인 항목 안이고 가산점 > 0. 세기·경로와 상관없다. `bonus_rank_applied`는 이것이 참일 때만 참.
- 조율 쪽 안내(약속 문서·알림 초안): `bonus_verified` 참인 공고만 "확인된 가산점 +N점(일부)" + "전체 가산점은 공고문 확인", 거짓이면 표시 없음.

## 3. 확인
- 시험 948개 중 932 통과·16 건너뜀·실패 0. 기존 시험은 가짜 목록·가짜 가점 행에 원문 지문을 더한 것만 바꿈.
- 전후(결정 0018 전 사본): 가상 신청자 4명 변화 없음(`reports/bonus_conservative_20261008T064030Z/`), 조합 800개 같음 800(`reports/bonus_boostable_20261008T064049Z/`). 목록 10건을 원문 지문을 더해 다시 씀(같은 공고·승인 항목·가점 행 지문).
- 내 PC 임시 서버: 전북 예시 기본 117356·126642 3·6위 `bonus_verified`·`bonus_rank_applied` 참, 세기 0이면 6·7위 `bonus_verified` 참·`bonus_rank_applied` 거짓.

## 4. 봐 주셨으면 하는 것
1. 4차 지적 4건 처리가 지적 경로를 막는가. 원문 지문의 범위·정규화가 충분한가(줄바꿈 표기만 통일, 정렬).
2. `bonus_verified`가 "화면에 써도 되는 가산점"의 기준으로 충분한가(조율 쪽 화면 위험을 대조 품질로 한정).
3. 남는 한계(표시 계산의 쉼표 경우·배점 칸 줄·앞줄이 일반 말인 "*" 줄 — 화면에는 대조된 공고만 나감)를 어떻게 보는가.
