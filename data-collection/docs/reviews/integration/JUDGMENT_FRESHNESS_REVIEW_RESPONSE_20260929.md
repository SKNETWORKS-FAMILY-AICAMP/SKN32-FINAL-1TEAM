# 판정표 지문 재검수 — Claude 응답과 재검수 요청 (2026-09-29)

대상: [Codex 재검수](JUDGMENT_FRESHNESS_REVIEW_20260929.md) **보류(P1 4 · P2 3)**. Claude가 지적 위치를 코드에서 모두 확인했다(7건 모두 사실).
사용자 결정: P1-2는 **A안**(아래), 나머지는 제안대로 진행. 코드 수정 뒤 **같은 경계 입력으로 재검수**를 요청한다.
결과 파일: 같은 폴더 `JUDGMENT_FRESHNESS_REVIEW_RECHECK_20260929.md`. 코드·DB는 고치지 말고 결과 문서만 남겨 주세요.

## 0. 한눈에

| 지적 | 조치 | Codex 재현 입력의 지금 결과 |
|---|---|---|
| P1-1 비활성 첨부를 지문에 포함 | 10·11·12단계 첨부 조회 5곳에 `na.active` | 비활성 본문이 있던 6건 중 5건 지문이 바뀜 → 서비스는 '모름'(126490 strong 불가 포함), 내일 배치가 5건씩 다시 판정 |
| P1-2 발췌 밖 원문 변경을 못 봄 | **A안**: strong 불가인데 LLM이 안 읽은 원문에 '예비창업'이 있으면 확인 필요 | 본문 2,100자 뒤 "예비창업자도 신청 가능." → `pre_founder()` None, 자격 확인 "확인 필요" |
| P1-3 file 모드가 지문 확인을 건너뜀 | 모든 모드에서 지문을 먼저 구한다. 못 구하면 기능 끔 | file 모드 + 옛 지문 + current 없음 → `active=False`, `pre_founder('n1')` None |
| P1-4 구조 오류 줄의 부팅 예외 | 줄 단위로 ID 형식 검사·삽입, `boot()`에서 판정 읽기 예외를 한 번 더 잡음 | `notice_id=["n1"]` 줄 → `bad_lines`로 셈, 정상 DB 2건은 그대로 사용 |
| P2-1 같은 길이 첨부 순서 | 정렬 마지막 기준에 `na.id` | 현재 동률 0건이라 지문 변화 없음 |
| P2-2 13단계 오류·경고 동시 | 둘 다 `stage_warnings`에 남김 | Codex 가짜 결과 → 오류 1줄 + 경고 1줄 |
| P2-3 빈 판정표 이유 없음 | 쓸 판정이 0건이면 `error`에 이유 → `boot_errors` | 빈 DB·파일 없음 → "쓸 수 있는 판정이 0건이다(…)" |

## 1. P1-2 — 왜 A안인가

- 지문은 LLM이 읽은 **발췌**(`build_document`, 최대 6,000자)의 해시다. 전체 원문 지문을 따로 두면 변경은 알아채지만, 다시 판정할 때 **같은 발췌를 읽어 결론이 같다**(Codex도 지적). 그래서 옛 판정 감지 대신 "LLM이 안 읽은 곳에 해당 말이 있나"를 본다.
- 규칙(`search/applicant_types.unread_pre_founder`·`mark_unread`)
  - 원문(지원대상·본문·**첨부 전체**)에서 `예비\s*창업`이 나오는 곳마다 앞뒤 10자를 공백 없이 떼어 발췌(공백 제거)에 있는지 본다. 없으면 안 읽은 언급이다. 발췌 경계에 걸친 언급도 안 읽은 쪽으로 센다(낮추는 쪽이 안전).
  - 대상: 예비창업자 `not_allowed`·`strong`·`varies=false`(=`blocked`)이고 판정 지문이 지금 공고문과 같을 때만. 원래 표는 바꾸지 않는다.
  - 결과: `pre_founder()` None(빼지도 되살리지도 않음), `type_check()` "예비창업자 불가로 읽었으나 확인 필요(공고 본문)" + 판정 근거와 안 읽은 곳 문장.
  - 13단계(`collect/upload_judgments.type_rows`)도 같은 규칙으로 `pre_founder_verdict`를 NULL로 올린다(DB 결론 = 서비스 결론). 지금 공고문을 못 읽으면 신청자 유형 표는 올리지 않는다(error, 업종은 계속).
- 공용 DB 집계(SELECT만): strong 불가 187건. Codex가 센 "발췌 밖 글이 있는 strong 불가 25건"에는 안 읽은 곳 '예비창업'이 **0건**. 원문 전체 대조로는 **2건**(발췌는 자격 구간 주변만 자르므로 한도를 늘려도 안 읽는 곳이 있다).
  - `bizinfo:PBLN_000000000126586`: 제출서류 표 "개인사업자 또는 예비창업자의 경우 해당사항 없음" — 예비창업자 신청 여지가 있어 확인 필요가 맞다고 본다.
  - `bizinfo:PBLN_000000000126651`: 작성 양식 "예비창업자 및 타 업체에 노하우 전수" 활동 예시 — 자격과 무관. 낮춰도 추천에 남을 뿐이다.
- 한계: '예비창업' 단어가 없는 자격 변경(예: "사업자 등록 전인 자")은 잡지 못한다. 같은 발췌를 읽는 한 재판정으로도 못 잡는 문제라 A안 범위 밖으로 둔다.

## 2. 바뀐 파일

| 파일 | 내용 |
|---|---|
| `search/applicant_types.py` | `load()` 줄 단위 ID 검사(P1-4) · `current_documents`·`unread_pre_founder`·`mark_unread`(P1-2) · `load_auto` 지문 먼저(모든 모드, P1-3)·0건 이유(P2-3)·`documents=` 인자 · `pre_founder`·`type_check` |
| `search/app.py` | `boot()` 판정 읽기 예외를 기능 끄기로(P1-4, 업종 포함) · `/api/health` `unread_pre_founder` |
| `experiments/sql_semantic/applicant_type_llm.py` | `load_population` 첨부 `na.active`·`ORDER BY …, na.id`(P1-1·P2-1) |
| `collect/extract_conditions.py` | 10단계 대상 고르기(EXISTS)·첨부 읽기 `na.active`·`na.id` |
| `experiments/sql_semantic/industry_llm_sample.py` | 12단계 `load_items_shared`·실험 `load_items` 같은 조건 |
| `collect/upload_judgments.py` | 13단계 결론 칸에 A안 |
| `collect/daily_pipeline.py` | `stage_warnings_of` 오류·경고 둘 다(P2-2), 종료 코드 4 주석 10~13단계 |
| 테스트 | `tests/test_judgments_source.py`(Codex 재현 P1-2·P1-3·P1-4·P2-3 포함), `tests/test_upload_judgments.py`, `tests/test_applicant_type_daily.py`(P2-2), 새 `tests/test_active_attachments.py`(P1-1·P2-1) |
| 문서 | `docs/guides/JUDGMENT_TABLES.md`(`pre_founder_verdict`, 6절) |

## 3. 검증 (Claude, 2026-09-29)

- 전체 unittest **654개 통과**(건너뜀 13).
- 공용 DB SELECT만: `load_auto` 2.1초 · 지문 같음 2,520 · 지문 다름 5(비활성 첨부 공고: 125813·126284·126490·126496·126545, 그중 126490이 blocked) · 확인 필요로 낮춤 2.
- 계획만(호출·쓰기 없음): 11단계 `applicant_type_daily --plan` 부를 것 5건 약 $0.004 · 12단계 `industry_daily --plan` 5건 약 $0.006 · 10단계 다시 뽑을 것 5건(같은 공고). 13단계 `upload_judgments --plan` 신청자 유형 바뀜 2(A안 결론 칸) · 업종 0.
- `orchestration_probe` D·A·B·C 통과. G-01과 매칭 1단계 차이 0(2,525 × 5). 필터 통과 1,594 → 1,595(A안 반영 뒤) → 1,596(`na.active` 반영 뒤). 어느 공고가 들어왔는지는 따로 확인하지 않았다.
- 8000 재시작: `boot_errors` 없음, `applicant_types` used 2,520 · stale 5 · unread_pre_founder 2.

## 4. 재검수 요청

**우선 확인**
1. Codex가 만든 경계 입력 네 가지(P1-2 뒤 문장, P1-3 file 모드, P1-4 목록 ID, P2-2 오류+경고)를 그대로 다시 넣어 결과가 위 표와 같은지.
2. A안 규칙이 **불가를 잘못 유지하는** 경로가 남았는지. 특히 발췌 경계, 공백·줄바꿈 차이, 첨부가 여러 개일 때, 판정 지문과 지금 지문이 다를 때(표시하지 않음 — 서비스는 그 판정을 어차피 쓰지 않는다. 13단계는 파일 판정 그대로 올린다).
3. `load_auto` 재구성 뒤 모드별(auto·db·file) × (연결 있음·없음·지문 계산 실패·DB 읽기 실패) 조합에서 옛 판정이 쓰이거나 예외가 나는 곳이 있는지.
4. `na.active` 추가로 10·11·12단계 지문이 바뀌는 범위가 비활성 첨부 공고(현재 6건 중 5건)로 한정되는지, 다른 조회(업력 재추출 `age_rerun`, `label_pack`)와 어긋나 생기는 문제가 있는지.

**보통**
5. 13단계가 공고문을 읽지 못하면 신청자 유형 표를 올리지 않는 동작이 적절한지(업종 표는 계속 올림).
6. `boot()`의 예외 보호가 조율 에이전트의 직접 호출(`app.boot()`) 경로에도 그대로 적용되는지.

**하지 않은 것**: Linux/EC2 부팅, 내일 09:00 배치의 5건 재판정·13단계 실제 업로드, 8000 화면 브라우저 확인.

## 5. 다시 해 볼 명령 (`data-collection/`에서, 쓰기 없음)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_judgments_source tests.test_active_attachments tests.test_upload_judgments -v
.\.venv\Scripts\python.exe -X utf8 -m collect.upload_judgments --plan
.\.venv\Scripts\python.exe -X utf8 -m collect.applicant_type_daily --plan
.\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration
```
