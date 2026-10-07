# 문서 지도 (docs/)

이 폴더를 처음 여는 사람과 AI(Claude·Codex)를 위한 안내다. 2026-09-28에 폴더를 정리했다(아래 "정리 기록").
**어떤 문서가 지금 기준인지 헷갈리면 이 표를 먼저 본다.** 과거 문서의 수치·결론은 그 시점의 기록일 뿐이며, 지금 상태는 `STATUS.md`와 코드로 확인한다.

## 1. 먼저 읽을 것 (이 폴더 맨 위에 있는 다섯 개)

| 문서 | 무엇 | 언제 |
|---|---|---|
| [STATUS.md](STATUS.md) | 지금 상태. **맨 위 항목이 최신**이다 | 작업을 시작할 때 항상 |
| [NEXT_SESSION_HANDOFF_20261007.md](NEXT_SESSION_HANDOFF_20261007.md) | 최신 인계서. 검색에서 벡터 DB 빼기, 가산점 정리(확인된 부분합·재검수 지적 처리), 단위 테스트 결과서, 시험 화면 가산점 표시 (10/7). 이전 인계서는 `archive/` | 새 세션을 시작할 때 |
| [PLAN_ALIGNMENT_20260928.md](PLAN_ALIGNMENT_20260928.md) | 기획서·기능정의서와 대조한 결과와 **방향 결정**(업종·지역은 순위 신호, 제외 목록은 순위에 안 씀 등) | 매칭·업종 작업 전에 |
| [FLOW.md](FLOW.md) | 코드가 실제로 어떤 순서로 도는지 | 코드를 고치기 전에 |
| [WORKLOG.md](WORKLOG.md) | 작업 이력. **맨 위가 최신**, 과거 기록은 지우지 않는다 | 왜 이렇게 됐는지 찾을 때 |
| [WORK_SUMMARY_20260929.md](WORK_SUMMARY_20260929.md) | 9/29 하루 작업 정리(한 일·결과·남은 일) | 9/29에 무엇을 했는지 빠르게 볼 때 |

눈으로 보는 흐름도: 검증 화면 서버를 켜고 `http://127.0.0.1:8010/flow` (메뉴 "전체 흐름").

### 1-1. 바뀌지 않는 규칙·구조 문서 (2026-10-06 추가)

위 표가 **진행 일지**(날마다 쌓임)라면, 아래는 **기준 문서**(규칙·원칙·구조, 바뀔 때만 고침)다. 진입 안내는 [../AGENTS.md](../AGENTS.md)(`CLAUDE.md`와 같은 내용)이고 폴더마다 `AGENTS.md`가 있다.

| 문서 | 무엇 |
|---|---|
| [architecture.md](architecture.md) | 구성 요소, 어디서 무엇이 도는지, 배치·추천·서버 기동 흐름, 공용 DB 테이블 |
| [business-rules.md](business-rules.md) | 판정 원칙(모르면 빼지 않음), 정형 필터, 순위 규칙, 자격 판정, 수집·수집 상태, 내용 지문, 가산점 |
| [security.md](security.md) | 보호 대상, 누가 무엇을 해도 되는지, DB 접속·비밀값·비용·수집 예절 |
| [standards.md](standards.md) | 어기면 깨지는 규칙(Git, 실행, 폴더 경계, 배치 단계, 버전 값, DB 변경, 검증, 기록, 문서 위치) |
| [engineering-notes.md](engineering-notes.md) | 함정(증상 → 원인 → 대응)과 반복 점검 순서 |
| [operations.md](operations.md) | 설치·명령·환경 변수·서버 배치 운영·되돌리기 |
| [contracts.md](contracts.md) | 조율 에이전트용 HTTP 창구와 팀원용 DB 테이블 약속 |
| [tracking/status.md](tracking/status.md) · [tracking/decisions/](tracking/decisions/index.md) · [tracking/findings.md](tracking/findings.md) | 맡은 범위 대비 현황 · 결정 기록 · 아직 못 푼 문제 |

## 2. 하위 폴더

| 폴더 | 들어 있는 것 | 비고 |
|---|---|---|
| [specs/](specs/) | **기준 문서** — 프로젝트 기획서 v1.10(PDF), Agent 기능정의서 v1.9(xlsx) | 팀 문서. 고치지 않는다. 판단 기준은 기능정의서 |
| [guides/](guides/) | 운영·구조 참고 — API 필드 대응표, 배치 SQL, 예약 실행, 팀원용 데이터 사용법, 검증 화면 사용법, 구조도(HTML·SVG), [공고 판정 테이블 설계](guides/JUDGMENT_TABLES.md), **[공고팀 함수 설명서 — 조율 에이전트용](guides/ORCHESTRATION_HANDOFF.md)**(조율 개발자에게 전달) | 내용이 바뀌면 같은 파일을 고친다 |
| [notice_api/](notice_api/README.md) | **조율 에이전트가 부르는 공고 서버 API 작업**(2026-10-06~). 전체 계획·진행표와 작업별 폴더(`01_status_match/` · `02_detail_eligibility/` · `03_bonus/`)와 [Codex 검토 요청](notice_api/CODEX_REVIEW_REQUEST_20261006.md) → [결과](notice_api/CODEX_REVIEW_20261006.md) → [응답·재검수 요청](notice_api/CODEX_REVIEW_RESPONSE_20261006.md)(재검수 결과는 같은 폴더 `CODEX_REVIEW_RECHECK_20261006.md`). 가산점 10/7: [재검수 요청](notice_api/CODEX_BONUS_RECHECK_REQUEST_20261007.md) → [결과](notice_api/CODEX_BONUS_RECHECK_20261007.md) → [재재검수 요청](notice_api/CODEX_BONUS_RECHECK2_REQUEST_20261007.md) · [조율 담당 알림 초안](notice_api/BONUS_NOTICE_DRAFT_20261007.md). 코드는 `search/` 등 기존 자리에 있고, 각 작업 README에 바꾼 파일을 적는다 | 9/29 직접 import 설명서(`guides/ORCHESTRATION_HANDOFF.md`)를 대신하는 방식 |
| [reviews/](reviews/) | 작업 지시서·검수 요청서·검수 결과. 주제별 폴더 | 아래 3절 |
| [ml/](ml/) | 머신러닝(리랭커·업력 분류기) 설계·방향과 도식 | 서비스에 연결되지 않은 제출물용 |
| [deliverables/](deliverables/) | 제출한 보고서(docx)와 확인용 렌더링(`_qa/`). 10/7 `[단위 테스트] 공고 데이터·매칭 단위 테스트 결과서.docx` 추가(근거 `reports/unit_test_20261007T024611Z/` — 가산점 지적 처리 뒤 다시 만든 판) | 제출본이다. 고치지 않는다 |
| [archive/](archive/) | 지난 인계서(9/14, 9/22, 9/28) | **최신이 아니다.** 배경을 찾을 때만 읽는다 |

## 3. reviews/ — 주제별 검수 기록

| 폴더 | 문서 | 상태 (2026-09-28) |
|---|---|---|
| [reviews/matching/](reviews/matching/) | 매칭 코드 검토(9/18)·재검토, 정형 필터 선행 매칭 [재검수](reviews/matching/MATCH_FILTER_FIRST_REVIEW_RECHECK_20260928.md), [관련도 판정 지시](reviews/matching/RELEVANCE_LABEL_TASK_20260930.md)·[448쌍 AI 참고 판정 결과](reviews/matching/RELEVANCE_LABEL_RESULT_20260930.md) | 필터 선행 P2 두 건 승인. 9/30 블라인드 판정·채점 완료(대조군 정확 일치 50.0%), 사람 검토·qrels 병합 결정 필요 |
| [reviews/industry/](reviews/industry/) | 업종 LLM 추출 표본·전량 리뷰, 30건 판정 지시, 가중치 탐침 리뷰, F1-1 통합공고 검수 요청·결과 | F1-1 승인. 방향은 PLAN_ALIGNMENT 2절이 우선 |
| [reviews/search/](reviews/search/) | 임베딩 단독·하이브리드 비교 지시·리뷰, 검색어 구성 ablation 리뷰 | 완료 |
| [reviews/sql_semantic/](reviews/sql_semantic/) | 별도 로컬 DB 정형 필터·의미 검색 실험 지시·리뷰, F1·F2·F3 리뷰 | 완료(실험 경로) |
| [reviews/ui/](reviews/ui/) | 검증 UI 지시·리뷰, `/compare` 화면·입력 확장 지시·리뷰 | 완료 |
| [reviews/applicant_type/](reviews/applicant_type/) | 신청자 유형·업종 밀림 [Codex 판정 지시서](reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_TASK_20260928.md)와 [AI 참고 판정 결과](reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md) — 판정 꾸러미 `reports/label_pack_20260928/` | 블라인드 판정 완료 · 사람 검수 필요 |
| [reviews/chroma/](reviews/chroma/) | Chroma 실제 벡터 정합성 검사 지시·리뷰 | 완료 |
| [reviews/orchestration/](reviews/orchestration/) | 조율 에이전트용 [함수 설명서](guides/ORCHESTRATION_HANDOFF.md) · [검수 요청](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_REQUEST_20260929.md)·[Codex 결과](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_20260929.md)·[Claude 응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RESPONSE_20260929.md)·[Codex 재검수](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_20260929.md)·[재검수 응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_RESPONSE_20260929.md)·[Codex 2차 개정 재검수](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_20260929.md)·[2차 응답](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_RESPONSE_20260929.md)·[Codex 3차 개정 재검수](reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK3_20260929.md) | 프로브 C·기간 유형 계약 보완 확인. G-01 공고 ID 입력 연결 범위 문구 보완과 조율 담당 합의 대기 (2026-09-29) |
| [reviews/integration/](reviews/integration/) | [9/28 진행분 통합 검수](reviews/integration/CURRENT_PROGRESS_REVIEW_20260928.md)와 [재검수](reviews/integration/CURRENT_PROGRESS_REVIEW_RECHECK_20260928.md), [오후 변경 요청](reviews/integration/UNREVIEWED_CHANGES_REVIEW_REQUEST_20260928.md)·[검수 결과](reviews/integration/UNREVIEWED_CHANGES_REVIEW_20260928.md)·[Claude 응답](reviews/integration/UNREVIEWED_CHANGES_REVIEW_RESPONSE_20260928.md), [8건 재검수 + 저녁 변경 요청](reviews/integration/RECHECK_AND_EVENING_REVIEW_REQUEST_20260928.md)·[결과](reviews/integration/RECHECK_AND_EVENING_REVIEW_20260928.md)·[Claude 응답](reviews/integration/RECHECK_AND_EVENING_REVIEW_RESPONSE_20260928.md)·[재검수 결과](reviews/integration/RECHECK_AND_EVENING_REVIEW_RECHECK_20260928.md), **[판정 테이블·12·13단계·C-3 요청](reviews/integration/JUDGMENT_TABLES_REVIEW_REQUEST_20260928.md)·[Codex 검수 결과](reviews/integration/JUDGMENT_TABLES_REVIEW_20260928.md)**·[Claude 응답](reviews/integration/JUDGMENT_TABLES_REVIEW_RESPONSE_20260928.md) ·[Codex 재검수](reviews/integration/JUDGMENT_TABLES_REVIEW_RECHECK_20260928.md) · [9/29 P1 수정 검수 요청](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_REQUEST_20260929.md)(지문 대조)·[Codex 검수 결과](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_20260929.md)(보류 P1 4·P2 3)·[Claude 응답](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RESPONSE_20260929.md)·[Codex 2차 재검수](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK_20260929.md)(보류 P1 1·P2 1)·[Claude 2차 응답](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK_RESPONSE_20260929.md)·[Codex 3차 재검수](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK2_20260929.md)(보류 P1 1)·[Claude 3차 응답](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK2_RESPONSE_20260929.md)·**[Codex 4차 재검수 — 승인](reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK3_20260929.md)** | 9/29 판정표 지문 신선도 수정 **승인** |

2026-09-30 통합 검수 추가: [K-Startup 모집 종료 처리 요청](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_REQUEST_20260930.md) → [Codex 결과](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_20260930.md)(보류 P1 1·P2 2) → [Claude 수정 응답](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_RESPONSE_20260930.md) → **[Codex 재검수 승인](reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_RECHECK_20260930.md)**. 시간 순서 보호·ID 정규화·한국 날짜 SQL 수정 확인, 추가 지적 없음. 실제 첫 배치 반영 건수는 배치 뒤 확인한다.

## 4. 새 문서를 만들 때 (Claude·Codex 공통 규칙)

1. **파일 이름**: `주제_내용_YYYYMMDD.md` 대문자 영문(예: `MATCH_FILTER_FIRST_REVIEW_20260928.md`).
   검수 요청은 `…_REVIEW_REQUEST_날짜.md`, 검수 결과는 `…_REVIEW_날짜.md`, 작업 지시는 `…_TASK_날짜.md`.
2. **위치**: 검수 요청·검수 결과·작업 지시는 **`reviews/<주제>/`** 에 둔다. 요청서와 결과는 같은 폴더에 둔다.
   맞는 주제 폴더가 없으면 새 폴더를 만들고 3절 표에 한 줄 더한다. **`docs/` 맨 위에는 새 파일을 만들지 않는다**(1절 표의 문서 + 1-1절의 기준 문서 7개 + 이 README만 둔다. 범위 대비 현황·결정·미해결 문제는 `tracking/`).
3. **인계서**: 새 인계서는 `docs/NEXT_SESSION_HANDOFF_날짜.md`로 맨 위에 두고, 이전 인계서는 `archive/`로 옮긴다. 1절 표의 링크도 바꾼다.
4. **링크**: 상대 경로로 건다. `reviews/<주제>/`에서 STATUS는 `../../STATUS.md`, 코드는 `../../../search/app.py`.
5. 문서를 옮기거나 새로 만들면 이 README의 표를 함께 고친다.

## 5. 정리 기록

- 2026-09-28 · Claude · 사용자 요청으로 맨 위에 흩어져 있던 70여 개 파일을 위 폴더로 옮겼다. **지운 파일은 없다.**
  옮긴 파일을 가리키던 링크와 코드 주석의 `docs/…` 경로도 함께 고쳤다(WORKLOG 같은 날 항목). 옛 경로 → 새 경로:
  `docs/<이름>.md` → `docs/reviews/<주제>/<이름>.md`(검수·지시), `docs/guides/`(FIELD_MAP·QUERIES·SCHEDULER·TEAM_DATA·VERIFY_UI·구조도),
  `docs/ml/`(ML_*), `docs/archive/`(HANDOFF·9/22 인계), `docs/specs/`(기획서·기능정의서), `docs/deliverables/`(docx·`_qa_claude_*` → `_qa/`).
  과거 문서 본문에 이름만 적힌 문서(예: "`SEARCH_COMPARISON_TASK_20260918.md`")는 파일 이름이 그대로라 이 표에서 찾으면 된다.
  `reports/`의 과거 결과(예: `search_comparison_20260918T*`)에 남은 옛 `docs/…` 링크는 결과 보존 원칙상 고치지 않았다. 해당 폴더의 `DOCS_MOVED.md`에 새 위치를 적었다(Codex 통합 검수 P3).
