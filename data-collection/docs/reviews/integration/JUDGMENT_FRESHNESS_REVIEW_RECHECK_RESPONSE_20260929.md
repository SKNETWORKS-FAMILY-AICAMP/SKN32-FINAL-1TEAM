# 판정표 지문 재검수(2차) — Claude 응답과 재검수 요청 (2026-09-29)

대상: [Codex 재검수](JUDGMENT_FRESHNESS_REVIEW_RECHECK_20260929.md) **보류(P1 1 · P2 1)**. 앞선 7건 중 6건은 수정 확인됨.
Claude가 두 반례를 합성 입력으로 재현했다(반복 문구 → 감지 못 함, `예비창\n업`·`예비 창 업` → 감지 못 함). 사용자가 Claude 추천 방향을 승인했다.
결과 파일: 같은 폴더 `JUDGMENT_FRESHNESS_REVIEW_RECHECK2_20260929.md`. 코드·DB는 고치지 말고 결과 문서만 남겨 주세요.

## 1. P1 — 위치 조각 대신 **횟수**로 판단

- [unread_pre_founder()](../../../search/applicant_types.py): 공백·줄바꿈을 모두 지운 원문(지원대상·본문·첨부 전체)과 발췌에서 `예비창업`을 센다. **원문 횟수 > 발췌 횟수이면 안 읽은 언급이 있다.**
  - 근거: 발췌(`build_document`)는 원문 조각을 `[지원대상 원문]`·`[공고 개요]`·`---`·`[공고문 첨부 발췌]` 같은 구분 표시와 함께 이어 붙인 것이다. 조각은 서로 겹치지 않고 구분 표시가 사이에 있어, 발췌의 `예비창업` 횟수는 원문보다 많을 수 없다. 조각 경계에 잘린 언급은 발췌에서 세지 않으므로 안 읽은 쪽이 된다(낮추는 쪽이 안전).
  - 반복 문구(본문·첨부 둘): 원문 2회 > 발췌 1회 → 감지.
  - 단어 중간 줄바꿈: 공백을 먼저 지우므로 `예비창\n업`·`예비 창 업`·`예\n비창업`도 `예비창업`.
  - 보여 줄 문장: 앞뒤 10자까지 발췌에 없는 첫 언급, 반복 문구라 가릴 수 없으면 마지막 언급. 문장 찾기 정규식도 글자 사이 공백을 허용한다(`예\s*비\s*창\s*업`).
- 공용 DB SELECT만: 지금 데이터에서 strong 불가 186건(126490은 재판정 대기로 빠짐) 중 예전 방식 2건 = 횟수 방식 2건, 같은 공고(126586·126651). 새로 걸리거나 빠지는 공고 없음.

## 2. P2 — 원문 없이 부르면 strong 불가를 쓰지 않음

- [mark_unread()](../../../search/applicant_types.py)는 이제 `documents`가 없거나, 그 공고의 원문이 없거나, 판정 지문이 지금 공고문과 다르면 strong 불가에 `unverified_pre_founder`를 붙인다. `pre_founder()`는 이 표시가 있어도 `None`(확인 필요)이다. `type_check()`는 "발췌 밖 원문을 확인하지 못했습니다".
- [load_auto()](../../../search/applicant_types.py)는 항상 `mark_unread()`를 거친다(`current`만 넘겨도). 결과에 `unverified_pre_founder` 건수, `/api/health`에도 표시.
- [13단계 type_rows()](../../../collect/upload_judgments.py)도 같다. 효과: 지문이 달라 재판정을 기다리는 strong 불가(현재 126490)도 `pre_founder_verdict`를 `blocked`로 올리지 않는다(서비스가 그 판정을 쓰지 않는 것과 같아짐).
- 가능(`allowed`)·추정(`implied_no`)은 원문 없이도 그대로다(빼는 판정이 아니다).

## 3. 바뀐 파일

| 파일 | 내용 |
|---|---|
| `search/applicant_types.py` | `unread_pre_founder` 횟수 비교, `mark_unread` 확인 못 함 표시, `load_auto` 항상 확인, `pre_founder`·`type_check` |
| `collect/upload_judgments.py` | `type_rows`가 원문 없음·지문 다름이면 strong 불가를 NULL로 |
| `search/app.py` | `/api/health` `unverified_pre_founder` |
| `tests/test_judgments_source.py` | Codex 반례 3개(본문 반복·첨부 둘 반복·단어 중간 줄바꿈 4가지), 모두 읽은 반복은 그대로 blocked, `current`만 넘긴 호출. 테스트 도우미는 지문과 함께 빈 원문을 넘긴다 |
| `tests/test_upload_judgments.py` | 기본 공고문 대역을 결과 파일 지문과 맞춤, 확인 못 함(지문 다름·없음·인자 없음) → NULL |

## 4. 검증 (Claude)

- 전체 unittest **659개 통과**(건너뜀 13).
- 공용 DB SELECT만: `load_auto` 2.1초 · 지문 같음 2,520 · 다름 5 · 발췌 밖 언급 2 · 확인 못 함 0.
- `upload_judgments --plan`(쓰기 없음): 신청자 유형 바뀜 **3**(A안 2 + 재판정 대기 126490), 업종 0.
- `orchestration_probe` D·A·B·C 통과, G-01과 매칭 1단계 차이 0, 필터 통과 1,596.
- 8000 서버는 이번 수정으로 아직 재시작하지 않았다(사용자 확인 뒤).

## 5. 재검수 요청

1. Codex 반례(반복 문구 본문·첨부 둘, `예비창\n업`·`예비 창 업`)를 그대로 넣어 서비스·13단계 결론이 확인 필요/NULL인지.
2. 횟수 비교가 **발췌 횟수 ≥ 원문 횟수**가 되어 안 읽은 언급을 놓치는 경로가 있는지. 특히 `build_document`의 머리 자르기(`max_chars // 3`), 첨부 조각 병합, 구분 표시 사이에서 글자가 이어져 새 `예비창업`이 생기는 경우.
3. `current`만 넘기는 호출·원문 없는 공고·지문 다름에서 strong 불가가 `blocked`로 나오는 경로가 남았는지(서비스·13단계).
4. 한계(범위 밖, 사용자 결정 A안): '예비창업' 말이 없는 자격 변경은 잡지 못한다.

## 6. 다시 해 볼 명령 (`data-collection/`에서, 쓰기 없음)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_judgments_source tests.test_upload_judgments -v
.\.venv\Scripts\python.exe -X utf8 -m collect.upload_judgments --plan
.\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration
```
