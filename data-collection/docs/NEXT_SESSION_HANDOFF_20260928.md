# 다음 세션 인수인계 — 기획서 정렬·필터 선행 매칭 (2026-09-28)

기준 시점: 2026-09-28 작업 종료 (Claude, 계정 전환 전)  
작업 범위: `data-collection/`만  
이 문서가 **최신 진입점**이다. 이전 [2026-09-22 인계](archive/NEXT_SESSION_HANDOFF_20260922.md)는 업종 작업의 세부 배경으로만 읽는다.

> **같은 날 오후에 이어진 작업(이 문서 작성 뒤)**: F2 업종 코드 맞추기, 제외 목록은 순위에 안 씀(A안), 업종 순위 반영 구현,
> docs 폴더 정리(문서 위치 변경 — [문서 지도](README.md)), 검증 화면 공통 메뉴·전체 흐름 화면(`/flow`).
> 요약은 [STATUS](STATUS.md) 맨 위, 상세는 [WORKLOG](WORKLOG.md) 2026-09-28 위쪽 항목들. 아래 7절 "커밋되지 않은 변경"은 오전 기준이다(오전분은 커밋 `eb62206`).

## 1. 새 세션이 가장 먼저 할 것

1. 이 문서를 끝까지 읽는다.
2. [현재 상태](STATUS.md) 맨 위 항목과 [WORKLOG](WORKLOG.md)의 2026-09-28 항목들을 읽는다.
3. `docs/reviews/matching/`에 `MATCH_FILTER_FIRST_REVIEW_*`로 시작하는 Codex의 **재검수 결과**가 새로 생겼는지 확인한다(아래 4절). 2026-09-28 정리 전 위치인 `docs/` 맨 위도 함께 본다.
4. 사용자는 이근준이다. 커밋·push는 사용자가 직접 한다. 설명은 비유 먼저, 쉬운 말로 한다.

## 2. 기준 문서와 담당 범위

- 기준: [프로젝트 기획서 v1.10](specs/프로젝트_기획서_v1.10.pdf)(2026-09-23), [Agent 기능정의서 v1.9](specs/S-Brain_Agent_기능정의서_v1.9.xlsx).
  xlsx는 `openpyxl`이 `.venv`에 없어 zip 안의 XML로 읽었다.
- 기획서 7-1에서 이근준의 담당은 **공고 데이터 · 매칭·자격 판정 · 인프라·배포(신누리와 공동)**다. 기능정의서 규칙으로는 R-1·R-2·R-3이다.
- 대조 결과와 결정은 [기획서 대조](PLAN_ALIGNMENT_20260928.md)에 있다. 이 문서가 방향의 기준이다.

## 3. 2026-09-28에 정한 것 (사용자 결정)

| 결정 | 내용 |
|---|---|
| 업종·지역은 **순위 신호** | 신청자 주 업종·희망 지역은 매칭 순위에만 쓴다. 정형 필터·자격 게이트에는 쓰지 않는다(기획서 4-2·5-3, 기능정의서 R-2·R-3). 2026-09-22 인계의 "주업종 정형 게이트" 목표는 폐기됐다 |
| 업종 순위 반영 원칙 | 확실한 불일치(known + 완전한 목록 밖, 구체 제외 목록 안)만 뒤로 보낸다. 불확실한 판정은 건드리지 않는다. **구현 전**이다. F2(업종 코드 맞추기)를 먼저 해야 한다 |
| 불일치 A부터 수정 | 서비스 매칭을 "검색 먼저 → 필터"에서 "**정형 필터 먼저 → 통과 공고 안에서만 검색**"으로 바꿨다 |

## 4. 오늘 한 일과 검수 상태

| 작업 | 상태 | 근거 |
|---|---|---|
| F1-1 통합공고 전역 판정 방지 → `final5` | ✅ **Codex 승인**. P2(괄호 참조 개별 공고·챗봇 안내 오분류 2건)는 후속 | [검수](reviews/industry/INDUSTRY_F1_UMBRELLA_REVIEW_20260928.md) |
| 기획서 대조, 업종 순위 신호 결정 | ✅ 문서화 | [대조](PLAN_ALIGNMENT_20260928.md) |
| 불일치 A: 필터 선행 매칭 | ⏳ **Codex 재검수 대기**. 1차 검수의 P2 두 건은 고쳤다 | [1차 검수](reviews/matching/MATCH_FILTER_FIRST_REVIEW_20260928.md), [요청서 6절](reviews/matching/MATCH_FILTER_FIRST_REVIEW_REQUEST_20260928.md) |
| 검색 먼저 vs 필터 먼저 수치 비교 | ✅ hybrid 신청 불가@10 4.8% → 0%, 쓸모@3 1.81 → 1.81(유지). 사용자에게 "새 방식이 낫다"고 설명함 | `reports/filter_first_eval_20260928T011252Z/` |
| 비교 화면 `/filter-first-eval` | ✅ 쉬운 말/전문 용어 전환 포함 | `web/filter_first_eval.html` |
| 업종 결과 화면 폴더 목록 정렬 | ✅ 묶음(최종·전량·재독·중간 합침·표본) → 최신순 | `industry_results.list_runs()` |

Codex 재검수가 승인이면 A는 끝난다. 추가 지적이 있으면 그것부터 고친다.

## 5. 매칭 서비스의 현재 동작 (`search/app.py` `/api/match`)

```text
신청자 입력
  → gate.prefilter: 모집 상태 closed · 마감일 < 오늘 · 업력/신청자 유형이 확실히 미달인 공고만 뺀다(모르면 남긴다)
  → 통과 0건이면 인코딩도 검색도 하지 않고 빈 결과
  → 통과 공고 안에서만 Chroma query(ids=) + BM25 search(allowed=) → RRF
  → 지역·시군구·대상 집단 규칙으로 순서만 조정(빼지 않음)
```

- 응답에 `filtered_count`·`filter.excluded`·`pipeline`·`dense_path`·`dense_error`가 있다.
- `boot()`가 Chroma 색인 ID를 `STATE['vector_ids']`에 기억한다. 실제 Chroma는 색인에 없는 ID를 `ids=`로 넘기면 오류를 낸다.
- `structured_filter=False`·`hide_expired=False`는 비교·평가용 스위치다. 서비스 화면은 쓰지 않는다.
- 설립일을 모르는 사업자는 업력으로 아무것도 빼지 않는다(게이트와 같은 원칙). 접수 시작 전 공고는 R-3 문구대로 남긴다.
- EC2: chromadb 1.5.9, `ids` 지원(읽기 전용 확인). **이 `search/app.py`는 EC2에 배포돼 있지 않다.** 배포는 사용자 판단이다.

## 6. 남은 일 (사용자가 순서를 정한다)

기획서와 어긋난 곳([대조](PLAN_ALIGNMENT_20260928.md) 3절):

| # | 내용 | 메모 |
|---|---|---|
| B | 실험 경로 `experiments/sql_semantic/search.py`가 지역을 SQL로 제외 | 서비스 경로는 이미 순위 방식 |
| C | 기업마당을 8개 분야 전부 수집 (기획: 창업 06·기술 02만, 기술은 창업기업 신청 가능 2차 조건) | 범위를 넓힌 결정 기록은 없다. 팀 확인 필요할 수 있음 |
| D | 첫 조회 10건·추가 10건·최대 20건 미구현 (지금 `top=3`) | |
| E | 임베딩 오류 시 BM25 단독 폴백·`fallbackMode` 없음 | Codex P2-2와 연결 |
| F | 수집 지연·실패 시 매칭 중단(24시간 초과 경고) 없음 | 관리자 화면은 프론트 파트 |
| G | 지원대상 유형(개인/법인) 데이터 없음 → 게이트 '확인 필요' | 정형화 보강 |
| H | `filteredCount`는 추가됨. `fitScore`(RRF ÷ 이론 최대) 없음 | 기능정의서도 잠정 |

업종 작업: **F2 KSIC 복합 명칭·미분류 167개 → F1-2 제외표 참조문 25건** 순서를 제안했다. 그다음 업종 순위 반영을 구현한다.
F1-1 P2(제목 판별 2건)는 작다. 상세는 [2026-09-22 인계](archive/NEXT_SESSION_HANDOFF_20260922.md) 6절, [업종 리뷰](reviews/industry/INDUSTRY_LLM_FULL_LUNA_REVIEW_20260922.md) 끝을 본다.

## 7. 커밋되지 않은 변경 (2026-09-28 기준 HEAD `35358be`)

사용자가 Codex 재검수 뒤 커밋할 예정이다. 새 세션은 이 변경을 되돌리지 않는다.

- 수정: `search/app.py`·`gate.py`·`hybrid.py`, `experiments/sql_semantic/industry_llm_sample.py`·`industry_results.py`·`viewer.py`,
  `eval/search_comparison.py`, `web/industry_results.html`, 테스트 4개, `docs/FLOW.md`·`STATUS.md`·`WORKLOG.md`.
- 신규: `eval/filter_first_eval.py`, `experiments/sql_semantic/filter_first_results.py`, `web/filter_first_eval.html`,
  `tests/test_filter_first_eval.py`·`test_filter_first_ui.py`, 문서 6개(대조·검수 요청·검수 결과·이 인계서), `reports/`의 새 결과 폴더 8개.
- 사용자가 스테이징한 것: 기획서 PDF, 기능정의서 xlsx.

## 8. 확인·실행 방법 (`data-collection/`에서)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests          # 485개 통과, 건너뜀 13 (2026-09-28)
.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.viewer     # http://127.0.0.1:8010
.\.venv\Scripts\python.exe -X utf8 eval\filter_first_eval.py              # 비교 평가 재실행 (OpenAI 0, DB 읽기만)
```

- 화면: `/filter-first-eval`(매칭 순서 비교), `/industry-results`(업종 추출, 기본 `final5`).
- Claude Code 데스크톱의 미리보기 설정은 저장소 루트 `.claude/launch.json`(`verify-viewer`, `search-service`)에 있다.

## 9. 하지 말 것

- 업종·지역을 정형 필터나 게이트에 넣지 않는다(3절 결정).
- 기존 `reports/` 결과 폴더를 덮어쓰지 않는다. 새 폴더로 만든다.
- 코드 후처리만 바꿨을 때 Luna 1,852건을 다시 호출하지 않는다. 저장된 checkpoint로 `--reverify`한다.
- 사용자 요청 없이 DB 쓰기, EC2 배포·스크립트 실행, Git commit·push를 하지 않는다.
- 유료 API 호출 전에는 비용을 먼저 확인받는다.

## 10. 새 세션 첫 요청문 예시

> data-collection/AGENTS.md와 docs/NEXT_SESSION_HANDOFF_20260928.md를 읽어줘.
> Codex 재검수 결과(docs/reviews/matching/MATCH_FILTER_FIRST_REVIEW_*)와 통합 검수(docs/reviews/integration/)가 있으면 확인하고, 추가 지적이 있으면 고쳐줘.
> 커밋과 push는 내가 한다.
