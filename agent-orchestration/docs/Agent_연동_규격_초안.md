# Agent 연동 규격 초안 (잠정 규격)

| 항목 | 내용 |
|---|---|
| 상태 | **잠정 규격 — 타 팀 합의 전.** 합의 결과에 따라 바뀔 수 있다 |
| 작성일 | 2026-09-26 |
| 기준 문서 | S-Brain Agent 기능정의서 v1.9 (시트 2 · 3 · 4 · 5 · 7) |
| 코드 위치 | `sbrain/` — 입출력 규격 `contracts/tasks.py`, 공통 타입 `models/`, 호출 도구 `orchestrator/tools.py` |
| 검증 방식 | 7개 Agent를 스텁으로 두고 Orchestrator가 20단계를 끝까지 도는 테스트로 검증했다. 2026-09-29 조율 T-C1을 실제 구현으로 바꿨다 (`tests/`, 75건 통과) |
| 독자 | 전략 · 작성 · 구현 · 검증-1 · 검증-2 · 검수 Agent 구현 담당, 공고팀(G-01 · T-C2), 웹팀(명령 창구 연동) |

---

## 1. 목적

각 Agent의 Task를 Orchestrator(뼈대)에 끼워 넣을 때 지켜야 할 규격을 정한다. 이 문서의 규격을 지키면 Task 함수를 `registry.bind(task_id, fn)` 한 줄로 스텁과 바꿔 끼울 수 있다.

## 2. 용어 — 조율 Agent와 Orchestrator

조율은 7개 Agent 중 하나이고, Orchestrator는 조율을 포함한 모든 Agent를 같은 방식으로 등록하고 호출하는 뼈대다. Orchestrator는 Agent가 아니며 Agent 수(7)에 들어가지 않는다.

기준 문서는 흐름 제어를 "조율이 맡는다"고 적었다. 구현에서는 아래와 같이 나눈다. 원본 문서는 고치지 않는다.

| 기준 문서 표현 | 구현 담당 | 근거 |
|---|---|---|
| 재수행 루프(횟수 세기와 다시 부르기)는 조율이 | Orchestrator | 시트 1 R31, 시트 7 R23 |
| R-9 실행 상태 관리 · 이어하기 · 동시 실행 제한 | Orchestrator | 시트 5 R-9 |
| R-11 호출 실패 처리(재시도 · 재개) | 재시도는 tools, 재개는 Orchestrator | 시트 5 R-11 |
| 재작성 실행(고른 묶음만 다시 돌리기 · 되돌리기 · 기회 반환) | Orchestrator | 시트 5 R-6 |
| 재작성 판정(점수 환산 · 다음 동작 · 재작성 목록) | 조율 Agent (G-02a · G-02b) | 시트 5 R-6 |
| T-C1 · T-C3 · T-C4 · G-04 · 합치기 4종 · R-8 | 조율 Agent | 시트 2 |
| T-C2 · G-01 | 조율 Agent 소속, 공고팀 구현 | 팀 분업 |
| T-P1의 "formatSpec 미주입 → 조율에 재요청" | Orchestrator가 공고의 formSpec.formatSpec을 주입한다 | 시트 2 T-P1 |

## 3. Task 함수 규격

```python
# LLM · 검색을 호출하는 Task
def run(inp: TS1In, tools: Tools) -> TS1Out: ...

# 규칙 단계 · 합치기 (tools를 받지 않는다)
def run(inp: G01In) -> G01Out: ...
```

- 입력 · 출력 모델은 `contracts/tasks.py`에 Task마다 있다. 필드 이름은 시트 3 변수명이며, 파이썬에서는 snake_case, JSON에서는 camelCase다.
- 동기 함수로 만든다. 병렬 처리는 Orchestrator가 한다(T-P2).
- 입력은 Orchestrator가 산출물 저장소에서 모아 넘긴다. Task는 저장소나 DB에 직접 접근하지 않는다.
- 출력이 규격과 맞지 않으면 규격 위반(운영 오류)으로 실행이 실패한다.
- **시트 3과 다른 점:** T-V1 · T-P2의 `temperature` 입력은 Task 입력에서 뺐다. 온도는 tools가 적용한다(T-V1 고정 0, T-P2 0.2 이하). 같은 값을 두 곳에 두면 어긋날 수 있기 때문이다.

## 4. tools 규격 (잠정)

### 4.1 반드시 지킬 규칙

> **Task 안의 LLM · 검색 호출은 반드시 tools로 한다.** HTTP 클라이언트나 SDK를 Task 안에서 직접 부르지 않는다.

tools를 거치지 않으면 재시도 · 제한 시간 · 오류 분류 · 호출 기록이 빠지고, 재개와 관리자 화면이 동작하지 않는다.

### 4.2 인터페이스 (합의 전까지 최소한으로 둔다)

| 함수 | 용도 |
|---|---|
| `tools.llm(messages, *, schema=None, parse=None, purpose="")` | LLM 호출. `schema`(pydantic 모델)가 있으면 JSON을 그 모델로 검사해 돌려준다. `parse`가 있으면 결과를 넘겨 받은 값을 돌려준다 |
| `tools.search(purpose, fn)` | LLM이 아닌 호출(임베딩 검색 · BM25 등)을 감싼다. `fn(timeout_sec)` 형태로 부른다 |

- 모델 · 호출처 · 온도 · 제한 시간은 담당 Agent 설정(관리자 설정값)과 Task 설정에서 tools가 입힌다. Task가 정하지 않는다.
- `purpose`는 호출 로그에 남는 짧은 설명이다. 프롬프트 · 응답 내용은 로그에 남지 않는다.

### 4.3 tools가 하는 일

| 항목 | 동작 | 값 |
|---|---|---|
| 재시도 | 호출 한 건마다 따로 센다. 호출 실패 · 응답 지연 · 형식 오류면 같은 호출을 다시 보낸다 | 재시도 횟수 5회, 재시도 간격 2초(잠정) |
| 제한 시간 | 호출처(HTTP 클라이언트)의 timeout으로 건다. 동기 호출은 강제로 끊을 수 없기 때문이다 | Task별 (7절 표, 잠정) |
| 형식 오류 | ① `schema` 검사 실패 ② `parse`가 `FormatError`를 올림 — 둘 다 재시도 | — |
| 오류 분류 | 재시도를 다 쓴 뒤 재개할지(일시) 실패로 끝낼지(입력 · 운영)를 가른다 | 아래 표 |
| 호출 기록 | 호출마다 시도별 결과 · 오류 종류 · 모델 · 온도를 남긴다. 재시도는 새 산출물 버전을 만들지 않는다 | — |
| 동시성 | 여러 스레드에서 동시에 써도 안전하다 | — |

| 상황 | 오류 | 오류 종류 |
|---|---|---|
| 시간 초과 (`TimeoutError`) | 응답지연 | 일시 |
| 응답 코드 408 · 429 · 5xx, 연결 오류 | 호출실패 | 일시 |
| 응답 코드 400 · 413 · 422 (입력 한도 초과 등) | 호출실패 | 입력 |
| 응답 코드 401 · 403 · 404 등 (인증 · 설정) | 호출실패 | 운영 |
| 스키마 불일치 · `FormatError` | 형식오류 | 일시 (잠정) |

기준 문서 문구대로 호출 실패는 오류 종류와 관계없이 재시도 횟수까지 다시 보낸다.

### 4.4 재시도를 다 쓰면

tools가 `ToolCallExhausted(error, error_kind, tries, call_id)`를 올린다.

| Task | 받는 쪽 | 처리 |
|---|---|---|
| T-C2 공고 매칭 | Task 함수가 받는다 | 대체 경로: 임베딩 오류 → BM25 단독, BM25 오류 → 임베딩 단독, 둘 다 → 마감 임박순(잠정). `fallbackUsed` · `fallbackMode`를 채운다 |
| T-V2 프로토타입 검증 | Task 함수가 받는다 | 보조 LLM 실패 → 문자열 대조 결과만으로 점수 산출 |
| T-P2 한국어 문장 윤문 | Orchestrator | 그 문장만 원문 유지(`keptReason='호출실패'`). 실패 비율이 기준을 넘으면 재개 |
| 그 밖의 Task | **받지 말고 그대로 올려 보낸다** | Orchestrator가 Task 단위로 재개한다(일시 오류만). 재개 상한을 넘기거나 영구 오류면 실행 실패, 재작성 중이면 재작성 실패 |

T-C1은 아직 실행 건이 없어 재개하지 않고 진입 전 상태로 되돌린다(E-C1-TIMEOUT).

### 4.5 호출처 어댑터 (Orchestrator 쪽에서 준비)

```python
class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> str: ...
```

- `request.timeout_sec`를 HTTP 클라이언트 timeout으로 건다.
- 시간 초과는 `TimeoutError`, 응답 코드 오류는 `ProviderError(status=...)`로 올린다.
- 조율은 OpenAI, 검수는 자체 GPU 서버처럼 Agent마다 호출처가 다를 수 있다. 호출처 이름은 Agent 등록부(관리자 설정값)에 있다.

## 5. 검사 결과와 다시 만들기

### 5.1 check (검사 미통과 재수행)

대상 Task: T-S1 · T-S2 · T-W1 · T-W2 · T-W3 · T-B1 · T-B2. 출력에 `check: CheckResult`를 담는다.

1. Task가 스스로 검사해 `check.passed`와 `check.failures`를 채운다.
2. `passed=false`면 Orchestrator가 `ReworkInput`을 실어 같은 Task를 다시 부른다(재수행 횟수 2회).
   - `mode='재수행'`, `issues`=직전 `check.failures`, `previousResultRef`=직전 결과 위치, `isFinalAttempt`=마지막 시도 여부
   - 지시문(`instruction`) 끝에 문제가 된 내용이 덧붙는다
3. **마지막 시도(`isFinalAttempt=true`)에서도 통과하지 못하면**
   - 확정 동작 예외 여섯 곳(T-S1 · T-S2 · T-W1 · T-W2 · T-W3 · T-P2)은 확정 동작을 적용한 결과를 돌려주고 `check.finalAction`에 적용 내용을 적는다.
   - 나머지 Task는 그대로 돌려준다(그대로 보냄).
   - 예외 여섯 곳에서 `finalAction`이 비어 있으면 Orchestrator가 규격 위반으로 기록한다.

| Task | 확정 동작 (시트 7) |
|---|---|
| T-S1 | itemSpec.coreFeatures를 승계해 featureList 확정 |
| T-S2 | 출처 없는 수치 제거, 정성 서술만 |
| T-W1 | 입력에 없는 경력 서술 · 지원규모 상한 초과 금액 서술 삭제, 사용자 알림(E-W1-REMOVED) |
| T-W2 | 해당 차트 폐기 + 본문의 차트 참조 문구 제거 |
| T-W3 | 표 제거 후 본문 서술로 대체 |
| T-P2 | 해당 문장만 원문 유지 |

### 5.2 사용자 재작성

사용자가 화면 6 · 8 · 9에서 묶음을 고르면 Orchestrator가 대상 Task에 `ReworkInput(mode='재작성', order=<고른 묶음의 ReworkOrder>)`를 넘긴다. `order.reason`과 `order.instructionDelta`가 지시문에 덧붙는다. 같은 Task에 묶음 여러 개가 걸리면 한 번의 호출로 합친다.

### 5.3 featureList는 바꾸지 않는다

T-S1이 확정한 featureList는 첫 버전 이후 바뀌지 않는다. T-W1이 다른 값을 돌려주면 변경분은 무시되고 기록만 남는다(시트 2 T-W1 L③).

## 6. Task별 입출력 (코드에서 생성)

출처 표기: 이름만 있으면 산출물(현재 버전), `a.b`는 산출물의 속성, `setting:`은 설정 스냅샷, `run:`은 실행 건 필드, `cmd:`는 사용자 명령, `const:`는 상수, `flow:`는 워크플로가 만드는 값이다.

| ID | 입력 (필드 ← 출처) | 출력 (필드 → 산출물 키) |
|---|---|---|
| R-8 | attachments ← formInput.attachments | reference_docs → referenceDocs |
| T-C1 | form_input ← formInput<br>reference_docs ← referenceDocs (선택) | item_spec → itemSpec<br>category → category<br>company_info → companyInfo<br>category_reason → categoryReason<br>confidence → confidence<br>reference_summary → referenceSummary |
| T-C2 | item_spec ← itemSpec<br>company_info ← companyInfo<br>today ← 기준일자<br>top_k ← const:topK<br>offset ← cmd:offset | candidates → candidates<br>collection_status → collectionStatus<br>filtered_count → filteredCount<br>fallback_used → fallbackUsed<br>fallback_mode → fallbackMode |
| G-01 | company_info ← companyInfo<br>eligibility ← selectedAnnouncement.eligibility<br>eligibility_parsed ← selectedAnnouncement.eligibility_parsed<br>today ← 기준일자 | gate_result → gateResult<br>business_age_years → businessAgeYears |
| T-C3 | selected_announcement ← selectedAnnouncement<br>item_spec ← itemSpec<br>gate_result ← gateResult<br>company_info ← companyInfo<br>reference_summary ← referenceSummary (선택) | task_plan → taskPlan<br>task_count → taskCount<br>instruction_set → instructionSet |
| T-S1 | item_spec ← itemSpec<br>selected_announcement ← selectedAnnouncement<br>instruction ← 지시문(taskPlan)<br>rework_input ← 재작성·재수행 입력 | requirement_analysis → requirementAnalysis<br>feature_list → featureList<br>check → T-S1.check |
| T-S2 | item_spec ← itemSpec<br>requirement_analysis ← requirementAnalysis<br>selected_announcement ← selectedAnnouncement<br>instruction ← 지시문(taskPlan)<br>rework_input ← 재작성·재수행 입력 | market_analysis → marketAnalysis<br>numeric_tokens → numericTokens<br>check → T-S2.check |
| T-W1 | requirement_analysis ← requirementAnalysis<br>market_analysis ← marketAnalysis<br>selected_announcement ← selectedAnnouncement<br>company_info ← companyInfo<br>form_spec ← selectedAnnouncement.form_spec<br>instruction ← 지시문(taskPlan)<br>rework_input ← 재작성·재수행 입력 | plan_doc → planDoc<br>sections → sections<br>feature_list → featureList<br>check → T-W1.check |
| T-W2 | plan_doc ← planDoc<br>market_analysis ← marketAnalysis<br>instruction ← 지시문(taskPlan)<br>rework_input ← 재작성·재수행 입력 | charts → charts<br>check → T-W2.check |
| T-W3 | plan_doc ← planDoc<br>company_info ← companyInfo<br>selected_announcement ← selectedAnnouncement<br>instruction ← 지시문(taskPlan)<br>rework_input ← 재작성·재수행 입력 | tables → tables<br>check → T-W3.check |
| M-1 | plan_doc ← planDoc<br>charts ← charts<br>tables ← tables<br>chart_check ← T-W2.check (선택)<br>table_check ← T-W3.check (선택) | plan_doc → planDoc |
| T-V1 | plan_doc ← planDoc<br>evaluation_items ← selectedAnnouncement.evaluation_items<br>rubric ← const:rubric | doc_score → docScore<br>items → T-V1.items<br>variance_flag → varianceFlag |
| G-02a | doc_score ← docScore<br>threshold ← setting:scoring.threshold<br>rework_usage ← run:rework_usage<br>selected_orders ← cmd:selectedOrders<br>checks ← 이번 구간 check 목록<br>user_action ← cmd:userAction<br>cycle_info ← flow:cycleInfo (확장)<br>settings_snapshot ← run:settings_snapshot (확장)<br>rubric_version ← flow:rubricVersion (확장) | score_report → scoreReport.document<br>failed_task_ids → G-02a.failedTaskIds<br>rework_orders → G-02a.reworkOrders<br>next_action → G-02a.nextAction |
| T-B1 | feature_list ← featureList<br>item_spec ← itemSpec<br>category ← category<br>instruction ← 지시문(taskPlan)<br>rework_input ← 재작성·재수행 입력 | prototype → prototype<br>implemented_features → implementedFeatures<br>entry_file_path → entryFilePath<br>check → T-B1.check |
| T-B2 | plan_doc ← planDoc<br>item_spec ← itemSpec<br>category ← category<br>instruction ← 지시문(taskPlan)<br>rework_input ← 재작성·재수행 입력 | infographic → infographic<br>check → T-B2.check |
| M-2 | infographic ← infographic<br>item_spec ← itemSpec<br>feature_list ← featureList | prototype → prototype |
| G-04 | prototype ← prototype<br>infographic ← infographic<br>item_spec ← itemSpec<br>announcement ← selectedAnnouncement | readme_path → readmePath |
| M-3 | prototype ← prototype<br>readme_path ← readmePath (선택) | prototype → prototype |
| T-V2 | prototype ← prototype<br>infographic ← infographic<br>feature_list ← featureList | artifact_score → artifactScore<br>code_check → codeCheck<br>feature_match → featureMatch |
| G-02b | doc_score ← docScore<br>artifact_score ← artifactScore<br>threshold ← setting:scoring.threshold<br>rework_usage ← run:rework_usage<br>selected_orders ← cmd:selectedOrders<br>checks ← 이번 구간 check 목록<br>user_action ← cmd:userAction<br>cycle_info ← flow:cycleInfo (확장)<br>settings_snapshot ← run:settings_snapshot (확장)<br>rubric_version ← flow:rubricVersion (확장) | score_report → scoreReport.overall<br>failed_task_ids → G-02b.failedTaskIds<br>rework_orders → G-02b.reworkOrders<br>next_action → G-02b.nextAction<br>rework_diff → reworkDiff |
| G-03 | plan_doc ← planDoc<br>announcement ← selectedAnnouncement<br>company_info ← companyInfo<br>feature_list ← featureList<br>reference_summary ← referenceSummary (선택)<br>numeric_tokens ← numericTokens | protected_tokens → protectedTokens |
| T-P1 | plan_doc ← planDoc<br>format_spec ← selectedAnnouncement.form_spec.format_spec<br>protected_tokens ← protectedTokens | format_findings → formatFindings<br>target_sentence_ids → targetSentenceIds |
| T-P2 | 문장마다 `TP2In(sentence, protectedTokens, formatFindings(이 문장), formatSpec, redoHint, redoCount)` | 문장별 출력을 모아 sentenceResults (확장) |
| M-4 | plan_doc ← planDoc<br>sentence_results ← sentenceResults<br>target_sentence_ids ← targetSentenceIds<br>model_version ← setting:agents.검수.model | plan_doc → planDoc<br>proofread_log → proofreadLog |
| T-C4 | plan_doc ← planDoc<br>prototype ← prototype<br>infographic ← infographic<br>score_report ← scoreReport.overall<br>proofread_log ← proofreadLog | deliverable → deliverable<br>user_message → userMessage |

## 7. Task별 실행 설정 (코드에서 생성)

| 순서 | ID | 이름 | 담당 Agent | 종류 | tools | 제한 시간(초, 잠정) | 온도 | 실패 정책 | 재수행 | 확정 동작 예외 | 14개 계상 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| — | R-8 | 첨부 문서 텍스트 추출 | 조율 | rule | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 1 | T-C1 | 요구사항 해석 | 조율 | task | 받음 | 120 | Agent 기본 | 재개 없음 | — | — | ○ |
| 2 | T-C2 | 공고 매칭 | 조율 | task | 받음 | 30 | Agent 기본 | Task 안 대체 경로, 재개 없음 | — | — | ○ |
| 3 | G-01 | 자격요건 게이트 | 조율 | rule | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 4 | T-C3 | 작업 분해 | 조율 | task | 받음 | 120 | Agent 기본 | Task 단위 재개 | — | — | ○ |
| 5 | T-S1 | 요구사항 분석 | 전략 | task | 받음 | 120 | Agent 기본 | Task 단위 재개 | ○ | ○ | ○ |
| 6 | T-S2 | 목표 시장 분석 | 전략 | task | 받음 | 120 | Agent 기본 | Task 단위 재개 | ○ | ○ | ○ |
| 7 | T-W1 | 사업계획서 본문 작성 | 작성 | task | 받음 | 300 | Agent 기본 | Task 단위 재개 | ○ | ○ | ○ |
| 8 | T-W2 | 그래프 생성 | 작성 | task | 받음 | 120 | Agent 기본 | Task 단위 재개 | ○ | ○ | ○ |
| 9 | T-W3 | 표 생성 | 작성 | task | 받음 | 120 | Agent 기본 | Task 단위 재개 | ○ | ○ | ○ |
| — | M-1 | 합치기① 차트 · 표를 계획서에 합침 | 조율 | merge | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 10 | T-V1 | 사업계획서 검증 | 검증-1 | task | 받음 | 120 | 고정 0 | Task 단위 재개 | — | — | ○ |
| 11 | G-02a | 문서 평가 판정 | 조율 | rule | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 12 | T-B1 | 실행 파일(HTML) 제작 | 구현 | task | 받음 | 300 | Agent 기본 | Task 단위 재개 | ○ | — | ○ |
| 13 | T-B2 | 인포그래픽 제작 | 구현 | task | 받음 | 300 | Agent 기본 | Task 단위 재개 | ○ | — | ○ |
| — | M-2 | 합치기② 원페이지 산출물을 Prototype으로 감쌈 | 조율 | merge | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 14 | G-04 | 실행 안내 문서 생성 | 조율 | rule | — | — | — | 오류 시 계속 | — | — | — |
| — | M-3 | 합치기③ readmePath를 Prototype에 기입 | 조율 | merge | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 15 | T-V2 | 프로토타입 검증 | 검증-2 | task | 받음 | 120 | Agent 기본 | Task 안 대체 경로, Task 단위 재개 | — | — | ○ |
| 16 | G-02b | 종합 평가 판정 | 조율 | rule | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 17 | G-03 | 보호 토큰 추출 | 검수 | rule | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 18 | T-P1 | 사업계획서 문장 형식 검수 | 검수 | task | 받음 | 120 | Agent 기본 | Task 단위 재개 | — | — | ○ |
| 19 | T-P2 | 한국어 문장 윤문 | 검수 | task | 받음 | 60 | 0.2 이하 | 실패 문장 원문 유지, 비율 초과 시 재개 | ○ | ○ | ○ |
| — | M-4 | 합치기④ 검수 결과를 계획서에 반영 · 검수 로그 집계 | 조율 | merge | — | — | — | 오류 시 실패(잠정) | — | — | — |
| 20 | T-C4 | 결과 통합 · 전달 | 조율 | task | 받음 | 120 | Agent 기본 | Task 단위 재개 | — | — | — |

- M-1 ~ M-4 · R-8은 기준 문서에 Task ID가 없어 붙인 구현용 ID다. 합치기는 조율 소속 규칙 단계이며 LLM을 쓰지 않고 14개 Task에 계상하지 않는다.
- 규칙 단계(G-01 · G-02a · G-02b · G-03 · G-04)와 합치기는 tools를 받지 않는다. 담당 Agent는 기록용이다.
- "오류 시 실패(잠정)": 규칙 단계 · 합치기에서 오류가 나면 운영 오류로 실행 실패, 재작성 중이면 재작성 실패로 처리한다. 기준 문서에 처리 규칙이 없어 둔 기본값이다. G-04만 기준 문서대로 계속 진행한다.
- T-C4는 LLM 사용 여부가 기준 문서에 없어 tools를 받게 두었다(미정).

## 8. Task별 특례

| Task | 특례 |
|---|---|
| T-C1 | `formInput`은 명령 창구가 웹 DB에서 읽어 넣는다(`start_run_for_project`). 필수 항목이 비면 T-C1을 실행하지 않는다(E-C1-REQUIRED). 카테고리 판정 실패 시 `categoryDefaulted`(확장)를 참으로 내면 Orchestrator가 추적 기록에 남긴다. 자세한 내용은 `docs/T-C1_요구사항해석_구현.md` |
| T-C2 | `topK=10`, 추가 조회는 `offset=10`으로 1회. 대체 경로는 Task 안에서 처리한다. Task 자체가 예외를 올리면 실행 건을 만들지 않고 다시 시도를 안내한다(확장 코드 X-C2-FAIL, 잠정) |
| G-01 | `eligibility` · `eligibilityParsed`는 선택 공고에서 꺼내 넘긴다 |
| T-V1 | `rubric`은 상수 공급처에서 넘긴다. 공급처는 기준 문서에 명시가 없다(검증 파트와 확인 필요) |
| T-V2 | 보조 LLM 실패 시 문자열 대조만으로 산출한다(Task 안에서 처리) |
| G-02a · G-02b | 재작성 사이클이면 `cycleInfo`(확장)로 전후 비교 결과 · 재채점한 층 · 승계한 층 · 재작성 전 점수를 받는다. 전후 비교(높은 쪽 선택과 되돌리기)는 Orchestrator가 먼저 하고, G-02는 그 결과를 `scoreReport.comparisons` · `carriedOverLayer` · `reworkDiff`에 담는다 |
| T-P1 | `formatSpec`은 Orchestrator가 선택 공고의 양식에서 주입한다 |
| T-P2 | 문장 하나당 한 번 호출된다. `redoHint` · `redoCount`는 Orchestrator가 채운다. 출력의 `adopted`는 R-5 보호 토큰 검사 결과로 정한다. 위반이면 `nextRedoHint`(확장)에 위반 유형별 지시를 담는다. Orchestrator가 누적해 다음 호출의 `redoHint`로 넘기고, 같은 출력이 반복되면 조기 중단한다 |
| featureList | 첫 버전 이후 바뀌지 않는다(5.3) |

## 9. 확장 필드 (기준 문서에 없음)

코드에서는 `ext()`로 선언되어 JSON 스키마에 `x-extension`이 붙는다.

| 타입 | 확장 필드 | 용도 |
|---|---|---|
| ReworkInput | sourceRefs, feedbackId | 피드백 출처 추적 |
| ReworkComparison | cycleId, screen, basis, comparedAt | 어느 재작성 사이클 · 화면 · 비교 기준인지 |
| AttemptRef → ExecutionRecord | executionId, runId, agent, stepKind, model, provider, temperature, inputs, outputs, outputMeta, status, cycleId, reworkRole, redoCount, resumeCount, feedbackIn, error, errorKind, startedAt, endedAt | 실행 추적 |
| Run | createdAt, projectId, segment, queue, segmentTotal, redoState, cycle, resumeWindowStartedAt, adminAlert, decisionRef, checkRefs, moreUsed, notices, endedAt | 재개 지점 · 재작성 사이클 상태 |
| Notification | notificationId | 알림 식별 |
| G02aIn · G02bIn | cycleInfo, settingsSnapshot, rubricVersion | 전후 비교 결과 전달, 판정 설정값 · rubric 버전 기록 |
| TP2Out | nextRedoHint | 위반 유형별 재수행 지시 |
| TC1Out | categoryDefaulted | 카테고리 판정 실패로 기본값(웹개발)을 썼는지 — 추적 기록용 |
| PreInput · CompanyInfo | revenueItems, companyName, bizType, representativeType, outputSummary, techField, regionalPriorityArea, occupation, representativeCapability, selfInKindResources | 기준 문서에 자리가 없는 웹 입력값(사용자 결정 2026-09-30). T-C1이 companyInfo로 그대로 옮긴다. 수익모델은 `revenueItems`에 전부 있고 `revenueUnitPrice`는 호환용 첫 항목 단가다. 작성 Agent는 매출 추정에 `revenueItems`를 쓰기를 권한다 |
| (신규) RevenueItem | serviceName, unitPrice | 수익모델 항목 하나 (단가, 원) |
| ExecutionRecord · CallLog | reasoningEffort | 추론 모델의 추론 강도 기록 |
| (신규) SentenceResult · ReworkCycleInfo · M1~M4 입출력 | — | T-P2 결과 모음, 사이클 정보, 합치기 |

## 10. 합의가 필요한 사항

| 번호 | 사항 | 관련 팀 |
|---|---|---|
| 1 | "Task 안의 LLM · 검색 호출은 반드시 tools로" 규칙과 tools 인터페이스(`llm` · `search`) | 전 Agent 팀 |
| 2 | T-P2 문장 재수행 루프 소유와 `nextRedoHint` 출력 추가. 시트 3은 호출자가 루프를 도는 구조, 기획서 7-1은 문장 단위 재수행 로직을 검수 파트에 둔다 | 검수 |
| 3 | G-02 입력 확장(`cycleInfo` · `settingsSnapshot` · `rubricVersion`). 기준 문서의 G-02 입력에는 재작성 전 점수 · 설정값 · rubric 버전이 없는데, 출력에는 이를 기록하게 되어 있다 | 조율(사용자) |
| 4 | T-W2 · T-W3 확정 동작의 본문 수정 경로. "본문의 차트 참조 문구 제거", "표 제거 후 본문 서술로 대체"는 본문을 바꾸는데 두 Task의 출력은 charts · tables뿐이다. 특히 서술 대체는 글을 새로 써야 해서 규칙 합치기로는 할 수 없다 | 작성 |
| 5 | 종합 평가 계획서 재작성의 HTML 반영 방법(기준 문서 미확정). T-B1 입력에 planDoc이 없어, 지금은 `reworkInput.issues`에 반영할 계획서 버전만 알린다 | 구현 |
| 6 | rubric 공급처 (T-V1 입력 `rubric`: 상수) | 검증-1 |
| 7 | 호출처 어댑터의 오류 → `TimeoutError` · `ProviderError(status)` 변환. OpenAI는 구현했다(`orchestrator/openai_provider.py`). 자체 GPU 서버는 미정 | 검수 · 인프라 |
| 8 | Agent 설정에 추론 강도(`reasoningEffort`) 추가. 온도가 비어 있으면(추론 모델) Task별 온도 규칙(T-V1 0 고정, T-P2 0.2 이하)을 적용하지 않는다(잠정). 추론 모델을 쓰는 Agent는 이 점을 확인한다 | 검증-1 · 검수 |
