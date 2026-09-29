# 판정표 지문 재검수(3차) — Claude 응답과 재검수 요청 (2026-09-29)

대상: [Codex 3차 재검수](JUDGMENT_FRESHNESS_REVIEW_RECHECK2_20260929.md) **보류(P1 1)**. 반복 문구·단어 중간 공백·원문 없는 호출은 수정 확인됨.
Claude가 반례를 재현했다(첨부 `['예비', '창업']` → 발췌 끝 `예비\n\n창업`, `unread_pre_founder` None, 지문 같음). 사용자가 Claude 추천 방향을 승인했다.
결과 파일: 같은 폴더 `JUDGMENT_FRESHNESS_REVIEW_RECHECK3_20260929.md`. 코드·DB는 고치지 말고 결과 문서만 남겨 주세요.

## 1. 조치 — 발췌를 빈 줄로 나눈 조각마다 센다

- [unread_pre_founder()](../../../search/applicant_types.py): 발췌 횟수를 `document.split('\n\n')`의 조각마다 공백을 지워 세고 더한다. 원문 쪽은 예전처럼 출처(지원대상·본문·첨부)마다 센다.
- 근거 — [build_document()](../../../collect/extract_conditions.py)의 모양
  - 머리: `[지원대상 원문]\n…` 과 `[공고 개요]\n…`를 `\n\n`으로 잇고 2,000자에서 자른다. 각 부분은 공백을 합친 한 줄이다.
  - 머리와 첨부 발췌 사이: `\n\n[공고문 첨부 발췌]\n`.
  - 첨부 발췌: 첨부마다 `slice_conditions()` 조각을 `\n\n`으로 잇는다. 한 첨부 안의 구간들은 `\n---\n`으로 잇고 각 구간은 공백을 합친 한 줄이다.
  - 따라서 `\n\n`으로 나누면 한 조각은 **한 출처의 연속 부분**이거나, 글자 표시(`[…]`·`---`)로 떨어진 한 출처의 구간들이다. 서로 다른 출처가 한 조각에서 붙지 않는다.
  - 예외: 자격 구간을 못 찾으면 `slice_conditions()`가 원문 앞부분을 그대로 쓰므로 조각 안에 `\n\n`이 있을 수 있다. 이때는 한 출처가 둘로 쪼개져 발췌 횟수가 **줄어드는** 쪽이라 안전하다(확인 필요 쪽).
- 발췌를 만드는 함수는 바꾸지 않았다. 구분 글자를 발췌에 넣으면 2,525건 지문이 모두 바뀌어 전량 재판정이 되므로 피했다.
- 보여 줄 문장을 고를 때도 조각 사이에 `|`를 넣어 붙지 않게 했다.

## 2. 검증 (Claude)

- 사전 집계(공용 DB SELECT만): strong 불가 186건에서 예전 방식 2건 = 조각별 2건(같은 공고). 전체 공고 2,525건 중 첨부 경계에서 가짜 언급이 생기는 공고 **0건**.
- 새 테스트
  - `tests/test_judgments_source.py`: Codex 반례 그대로(서비스 `load_auto` → `pre_founder` None, 보여 줄 문장 "신청 가능"), 경계만 있고 안 읽은 언급이 없으면 그대로 blocked, `build_document` 조각이 두 출처를 잇지 않는다는 전제.
  - `tests/test_upload_judgments.py`: 같은 반례로 13단계 `type_rows()` → `pre_founder_verdict` NULL.
- 전체 unittest **663개 통과**(건너뜀 13).
- 공용 DB SELECT만: `load_auto` 같음 2,520 · 다름 5 · 발췌 밖 2 · 확인 못 함 0. `upload_judgments --plan`: 신청자 유형 바뀜 3, 업종 0(쓰기 없음). `orchestration_probe` D·A·B·C 통과, 필터 통과 1,596.
- 8000은 이번 수정으로 아직 재시작하지 않았다(사용자 확인 뒤).

## 3. 재검수 요청

1. Codex 반례(첨부 `['예비', '창업']` + 본문 뒤 허용 문장)의 서비스·13단계 결론이 확인 필요/NULL인지.
2. 조각별 발췌 횟수가 원문 횟수보다 많아지는 경로(서로 다른 출처가 한 조각에서 이어지는 경우)가 남았는지. 특히 머리 2,000자 자르기, `slice_conditions()`가 구간을 못 찾아 원문 앞부분을 쓰는 첨부, 첨부 조각이 예산에 걸려 잘리는 경우.
3. 앞 차수에서 확인된 동작(반복 문구, 단어 중간 공백, 원문 없는 호출, 지문 다름)이 그대로인지.

## 4. 다시 해 볼 명령 (`data-collection/`에서, 쓰기 없음)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_judgments_source tests.test_upload_judgments -v
.\.venv\Scripts\python.exe -X utf8 -m collect.upload_judgments --plan
```
