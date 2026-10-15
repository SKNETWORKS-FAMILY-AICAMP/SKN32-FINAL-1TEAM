# 판정표 지문 신선도 수정 재검수 (2026-09-29)

대상: [Claude 응답·재검수 요청](JUDGMENT_FRESHNESS_REVIEW_RESPONSE_20260929.md), [앞선 Codex 검수](JUDGMENT_FRESHNESS_REVIEW_20260929.md) 7건. 코드·DB·기존 문서는 수정하지 않았다. 공용 DB에는 SELECT만 실행했고 유료 API 호출, 스테이징, 커밋은 하지 않았다.

## 결론

**재검수 보류 — P1 1건(A안의 두 경계 사례), P2 1건.** 앞선 7건 중 6건의 수정은 확인했다. P1-2는 기본 재현 입력에서 `blocked`를 확인 필요로 낮추지만, 같은 문구가 두 위치에 반복되거나 `창업` 두 글자 사이에서 줄이 바뀌면 발췌 밖의 새 허용 문장을 놓친다. 합성 입력에서 서비스와 13단계 업로드 결론이 다시 `blocked`가 되는 경로를 확인했다. 현재 DB의 오판을 입증한 것은 아니다.

## 앞선 7건의 처리 상태

| 앞선 지적 | 이번 확인 |
|---|---|
| P1-1 비활성 첨부 | **수정 확인.** 10단계 [pick_targets()](../../../collect/extract_conditions.py), 11단계·서비스 [load_population()](../../../experiments/sql_semantic/applicant_type_llm.py), 12단계 [두 조회](../../../experiments/sql_semantic/industry_llm_sample.py)에 `na.active`가 들어갔다. 업력 재추출 `age_rerun.py`는 `pick_targets()`, `label_pack.py`는 `load_population()`을 호출하므로 같은 규칙을 따른다. 현재 지문 불일치 5건은 서비스가 사용하지 않는다. 그중 옛 강한 차단 1건도 제외된다. |
| P1-2 발췌 밖 변경 | **부분 수정.** 원래 합성 입력의 `예비창업자도 신청 가능`은 [mark_unread()](../../../search/applicant_types.py)에 의해 확인 필요가 된다. 아래 P1 반례가 남았다. |
| P1-3 `file` 모드 무검사 | **수정 확인.** [load_auto()](../../../search/applicant_types.py)는 `auto`·`db`·`file` 모두 현재 지문을 먼저 구한다. 연결이나 지문이 없으면 기능을 끄고, 옛 파일 지문은 사용하지 않는다. |
| P1-4 구조 오류 줄의 부팅 예외 | **수정 확인.** [load()](../../../search/applicant_types.py)는 배열·객체·빈 공고 ID를 줄 단위 `bad_lines`로 센다. [app.boot()](../../../search/app.py)는 로더의 예상 밖 `RuntimeError`를 주입해도 부팅을 끝내고 `boot_errors['applicant_types']`에 기록했다. |
| P2-1 같은 길이 첨부 순서 | **수정 확인.** 첨부 조회는 `text_chars DESC, na.id`까지 정렬한다. 현재 DB에서 활성 첨부의 같은 길이 동률 그룹은 0건이다. |
| P2-2 오류·경고 동시 | **수정 확인.** [stage_warnings_of()](../../../collect/daily_pipeline.py)에 원래 가짜 결과를 넣으니 오류 1개와 경고 1개가 모두 나왔다. |
| P2-3 빈 표 이유 없음 | **수정 확인.** 쓸 판정 0건이면 `error`에 건수와 이유가 들어가며, 부팅은 이를 `boot_errors`에 기록한다. |

## 남은 문제

### P1. A안이 발췌 밖의 예비창업자 언급을 놓쳐 옛 `blocked`를 유지한다

[unread_pre_founder()](../../../search/applicant_types.py)는 원문의 `예비\s*창업` 각 발생 위치에서 앞뒤 10자 조각을 뽑아, 공백을 제거한 발췌 문자열 **어딘가에 같은 조각이 있는지**만 확인한다(194~216행). 발생 횟수와 원문 위치는 비교하지 않는다.

1. **반복 문구:** 아래 합성 공고의 `old`와 `new`는 발췌 지문이 같다. `new` 끝의 “신청 가능”은 발췌에 없다. 그러나 앞의 “신청 불가” 문구와 `예비창업` 앞뒤 10자가 같아 `unread_pre_founder(new)`가 `None`을 돌려준다. DB의 옛 strong 불가 판정에 `load_auto(..., documents={'n1': new})`를 적용해도 `pre_founder('n1') == 'blocked'`였고, 임시 JSONL을 넣은 `upload_judgments.type_rows(..., documents)`의 `pre_founder_verdict`도 `'blocked'`였다.

   ```python
   p = '공고 자격요건 참고문구와 상황 설명: 예비창업자 신청 관련 별도 안내: '
   old = '지원대상: 법인사업자만 신청 가능. ' + p + '신청 불가. ' + 'A' * 2100
   new = old + ' ' + p + '신청 가능.'
   # atl.prepare(old/new)의 document_sha256 동일; unread_pre_founder(new) is None
   ```

   첨부 둘에서도 같은 결과를 재현했다. 첫 첨부에 `p + '신청 불가'`, 둘째 첨부의 6,500자 뒤에 `p + '신청 가능'`을 두면 둘째 문구는 6,000자 발췌에 없고 이전·현재 지문이 같은데도 `unread_pre_founder()`는 `None`, 최종 판정은 `blocked`였다.

2. **단어 중간 줄바꿈:** 원래 재현 입력의 끝을 `예비\n창업자도 신청 가능`으로 쓰면 확인 필요로 낮춘다. 같은 뜻의 `예비창\n업자도 신청 가능` 또는 `예비 창 업자도 신청 가능`은 정규식 `_PRE_MENTION = re.compile(r'예비\s*창업')`에 걸리지 않는다(194행). 합성 공고에서 이전·현재 지문은 같았고 두 입력 모두 `pre_founder('n1') == 'blocked'`였다. 요청서가 확인해 달라고 한 공백·줄바꿈 경계에 해당한다.

두 경우 모두 **현재 서비스 부팅 경로(`documents`를 DB에서 읽는 경로)**에서도 발생하므로 단순 테스트용 인자 문제가 아니다. 원문의 각 언급이 실제 발췌에 포함됐는지 발생 위치나 발생 횟수로 비교하고, `창업` 내부의 줄바꿈·공백도 정규화한 뒤 앞선 합성 입력과 두 첨부 입력으로 다시 확인할 필요가 있다. 사용자 결정 A안이 명시적으로 범위 밖에 둔 “예비창업”이라는 말이 전혀 없는 자격 변경은 이 지적에 포함하지 않는다.

### P2. `load_auto(current=...)`만 넘기는 호출은 A안 검사를 건너뛴다

[load_auto()](../../../search/applicant_types.py)는 `current` 지문 사전이 있으면 `current_documents()`를 호출하지 않고, `documents`가 없으면 `mark_unread()`도 실행하지 않는다(288~320행). 원래 합성 입력(본문 2,100자 뒤 `예비창업자도 신청 가능`)에 같은 DB 판정을 넣었을 때 `documents={'n1': 현재 문서}` 경로는 `None`, `current={'n1': 현재 지문}` 경로는 `blocked`였다. 저장소의 실제 서비스 호출은 두 인자를 모두 생략해 문서를 읽으므로 **현재 운영 경로의 재현은 아니다**. 다만 공개된 인자 조합으로 A안 보호를 우회할 수 있어, 외부 직접 호출이나 향후 최적화 시에는 원문 제공을 필수로 하거나 차단 판정을 보수적으로 처리해야 한다.

## 실행 결과와 범위

| 검사 | 독립 재검수 결과 |
|---|---|
| 단위 테스트 | 번들 Python 3.12에 `.venv/Lib/site-packages`를 넣어 전체 discover 실행: **654개 실행, 실패·오류 0, 건너뜀 13**. 관련 4개 모듈만 실행: **54개 통과**. 위 P1 반례는 기존 테스트에 없다. |
| 모드·실패 조합 | 임시 JSONL과 가짜 연결 사용. `auto`·`db`·`file` 각각에서 옛 지문이면 `active=False`·판정 `None`, 연결 없음과 지문 계산 실패 시 `active=False`+`error`. `auto`의 DB 판정 읽기 실패+지문이 같은 파일에서는 파일 판정을 사용했다. |
| 공용 DB SELECT | 공고 문서·판정 각 2,525건, 지문 불일치 **5건**, 그중 기존 strong 차단 **1건**. 실제 `app.boot()` 경로에서는 사용 판정 2,520건·발췌 밖 언급으로 확인 필요 2건. 비활성 성공 첨부는 7개/공고 6건, 활성 첨부 길이 동률 그룹 0건. |
| 배치 계획(쓰기 없음) | 10단계 `pick_targets`+기존 입력 해시 SELECT 대조: 재추출 **5건**. `collect.applicant_type_daily --plan`: **5건**(예상 $0.004). `collect.industry_daily --plan`: **5건**(예상 $0.006). `collect.upload_judgments --plan`: 신청자 유형 변경 **2건**, 업종 변경 0건. 계획 명령에서 LLM을 부르거나 업로드하지 않았다. |
| 13단계 공고문 읽기 실패 | `current_documents()`가 예외를 내도록 한 기존 단위 테스트에서 신청자 유형 표는 오류를 남기고 업로드하지 않았으며, 업종 표는 계속 처리했다. `upload_judgments.run()`의 실제 분기도 같은 순서다. |
| 조율 프로브 | `experiments.orchestration_probe --sbrain ..\agent-orchestration`의 D·A·B·C 통과. G-01과 매칭 1단계는 2,525건 × 신청자 5가지에서 차이 0건. 현재 필터 통과 1,596건. 실패 주입 C′도 실패를 감지했다. 이 시험은 위 합성 P1 입력을 포함하지 않는다. |

Linux/EC2 부팅, 9/30 실제 배치·13단계 업로드, 8000/8010 브라우저 화면은 실행하지 않았다. 사용자 지시가 결과 문서만 허용하므로 STATUS·WORKLOG·문서 지도도 수정하지 않았다.
