# S-Brain Agent Orchestration

S-Brain의 AI Agent 7개를 정해진 순서대로 부르고, 실패하거나 다시 만들어야 할 때의 처리를 맡는 **Orchestrator(실행 뼈대)** 코드입니다.

| 항목 | 내용 |
|---|---|
| 언어 · 버전 | Python 3.12 |
| 의존성 | `pydantic` (타입 검증 · JSON 변환), `SQLAlchemy` · `PyMySQL` (공유 MySQL — 저장소 · 웹 DB), `openai` (조율 Agent 호출처), `python-dotenv` (`.env` 읽기), `pytest` (테스트) |
| 구현 근거 | S-Brain Agent 기능정의서 v1.9 (기준 문서). 보조 참고: 프로젝트 기획서 v1.10 |
| 현재 상태 | 뼈대 완성. 조율 **T-C1 · T-C3와 재작성 · 재수행 지시문 다시 쓰기는 실제 구현**(2026-10-04 실제 OpenAI로 확인 — T-C3 지시문 작성을 동시 호출로 바꾼 뒤 작성 시작 → 화면 6이 52초 → 11초), 공고 매칭 **T-C2 · 자격 확인 G-01은 공고 서버(공고팀 HTTP API) 연결 코드 완료** — `SBRAIN_NOTICE_API_URL`을 넣어야 켜지며 공고팀 API를 기다리는 중이라 지금은 스텁. 나머지 Agent는 **스텁(가짜 구현)**. 저장소는 **메모리 · 공유 MySQL** 두 가지, **워커 프로세스**(실행 로그 12개월 처리 포함)와 **웹 연동 함수**(시작 요청 · 명령 · 재작성 묶음 요청 · 진행 상태 · 화면 · 결과 조회 · 관리자 조회 · 중단 · 완전 삭제 · 탈퇴)까지 구현. 웹 `projects`에는 쓰지 않는다(2026-10-02). 시각은 모두 UTC, '오늘'은 한국 날짜(2026-10-05). 2026-10-06: 모델 설정을 Task별로, 이미지 호출 `tools.image`, 산출물층 검증 반영(구현 · 검증-2 담당 합의), 워커 운영 로그 파일(선택). 테스트 1272건(MySQL 8 통합 47건 포함) — 2026-10-06 기준 MySQL 8.0 테스트 DB까지 켜고 1272 통과 · 건너뜀 0, MySQL 없이 1225 통과 · 47 건너뜀 |

> 이 문서의 파일 경로는 저장소 폴더(`agent-orchestration`) 기준입니다. 기능정의서 · 기획서는 저장소에 포함되지 않습니다.

---

## 목차

1. [이 코드가 하는 일](#1-이-코드가-하는-일)
2. [먼저 알아둘 용어](#2-먼저-알아둘-용어)
3. [설치와 테스트](#3-설치와-테스트)
4. [한 번 돌려 보기](#4-한-번-돌려-보기)
5. [전체 흐름](#5-전체-흐름)
6. [폴더 구조](#6-폴더-구조)
7. [내부 동작](#7-내부-동작)
8. [Agent 구현을 끼워 넣는 방법](#8-agent-구현을-끼워-넣는-방법)
9. [명령 창구 (웹 서버 연동)](#9-명령-창구-웹-서버-연동)
10. [설정값](#10-설정값)
11. [테스트](#11-테스트)
12. [아직 하지 않은 것 · 확인이 필요한 것](#12-아직-하지-않은-것--확인이-필요한-것)
13. [더 읽을 문서](#13-더-읽을-문서)

---

## 1. 이 코드가 하는 일

### 1.1 S-Brain은 어떤 서비스인가

S-Brain은 **정부지원사업 사업계획서와 프로토타입을 함께 만들어 주는 AI 서비스**입니다. 사용자가 창업 아이템 정보를 입력하면 다음 순서로 진행됩니다.

1. 지금 신청할 수 있는 정부지원사업 공고를 찾아 추천하고, 자격요건을 미리 확인합니다.
2. 선택한 공고에 맞춰 사업계획서(본문 · 표 · 그래프)를 씁니다.
3. 계획서를 바탕으로 프로토타입(HTML 실행 파일 또는 SVG 원페이지)과 인포그래픽을 만듭니다.
4. 계획서와 프로토타입을 채점하고, 문장을 다듬은 뒤 결과물을 내려받게 합니다.

이 작업은 역할이 나뉜 **Agent 7개**가 나눠 맡습니다.

| Agent | 맡는 일 |
|---|---|
| 조율 | 요구사항 해석, 공고 매칭, 자격 확인, 작업 분해, 결과 통합 |
| 전략 | 요구사항 분석, 목표 시장 분석 |
| 작성 | 사업계획서 본문 · 그래프 · 표 작성 |
| 구현 | 프로토타입(HTML 실행 파일) · 인포그래픽 제작 |
| 검증-1 | 사업계획서 채점 (문서층) |
| 검증-2 | 프로토타입 채점 (산출물층) |
| 검수 | 문장 형식 검수 · 한국어 윤문 |

### 1.2 Orchestrator는 무엇을 하는가

Orchestrator는 **7개 Agent를 같은 방식으로 등록하고 호출하는 뼈대**입니다. 오케스트라의 지휘자처럼 연주(각 Task의 내용)는 하지 않고, 누가 언제 연주할지와 문제가 생겼을 때의 처리를 맡습니다.

| Orchestrator가 하는 일 | Orchestrator가 하지 않는 일 (각 Agent 몫) |
|---|---|
| 단계를 정해진 순서대로 실행, 사용자 선택을 기다리는 지점에서 멈춤 | 계획서 · 프로토타입 등 실제 내용 생성 |
| 각 단계의 입력을 모아 넘기고 출력을 버전으로 보관 | 점수 계산, 재작성 대상 판정 |
| 호출 실패 시 재시도 · 재개 · 실패 처리 | 결과 검사(check) 자체 |
| 사용자가 고른 항목만 다시 만들기, 점수가 떨어지면 되돌리기 | |
| 실행 상태 · 알림 · 추적 기록 저장 | |

> **조율 Agent와 Orchestrator는 다릅니다.** 조율은 7개 Agent 중 하나이고, 다른 Agent와 똑같이 Orchestrator에 등록되어 호출됩니다. Orchestrator는 Agent 수에 들어가지 않습니다.

### 1.3 지금 어디까지 되어 있는가

- 20단계 전체 흐름, 사용자 대기 지점, 재수행 · 재개 · 재작성 · 되돌리기, 추적 기록이 동작합니다.
- **조율 T-C1(요구사항 해석)은 실제 구현**입니다(`agents/supervisor/tc1.py`). 나머지 Agent · 조율 Task는 스텁이며, 규격에 맞는 더미 결과를 돌려줍니다. 스텁 조립(`build_stub_app`)은 T-C1도 스텁을 쓰고, `bind_supervisor(app.registry)`로 바꿔 끼웁니다. 실제 OpenAI(`gpt-6-luna`)로 1회 호출에 성공했습니다(2026-09-30).
- **조율 T-C3(작업 분해)도 실제 구현**입니다(`agents/supervisor/tc3.py`). 지시 대상 7번(원페이지 6번)의 안내 호출을 한꺼번에 보내고, 재시도를 다 써 재개하면 받아 둔 안내는 두고 빠진 것만 부릅니다. T-C3 · 다시 쓰기는 2026-10-04 실제 OpenAI로 확인했습니다(순차 호출 때와 동시 호출로 바꾼 뒤 두 번 — 작성 시작 → 화면 6이 52.52초 → 11.26초). 신청자 유형으로 양식 · 평가항목 · 채점 기준표 묶음을 고르고(`agents/form_defaults.py`, 값은 담당자 회신 전까지 잠정), 지시문을 받는 Task마다 조율 LLM으로 안내를 써서 지시문(틀 · 안내 · 참조 자료 세 부분)을 만듭니다. 뒷 단계(T-W1 · T-V1 · T-P1 · T-P2 · G-02)는 선택 공고의 양식 필드 대신 이 결과를 읽습니다. 재작성 · 재수행 때는 조율 LLM이 대상 Task 지시문의 안내 부분만 다시 쓰고 문제 내용을 끝에 붙입니다(`agents/supervisor/rewrite.py`, 워커 조립에서만). 설명은 `docs/T-C3_작업분해_구현.md`.
- 사전 정보 입력은 웹 백엔드가 DB에 저장한 값을 **프로젝트 ID로 읽어** T-C1에 넣습니다(`intake/`, `start_run_for_project`). 테이블 · 컬럼은 웹 스키마(저장소의 `web/backend/app_schema.sql`)와 맞췄습니다. 기준 문서에 자리가 없는 웹 입력값(수익모델 항목 전체, 기업명, 산출물 목표 등)은 확장 필드로 싣습니다. 첨부 문서 텍스트 추출(R-8)은 아직입니다.
- **공고 매칭(T-C2) · 자격 확인(G-01)은 공고팀 공고 서버의 HTTP API를 부르는 연결 코드**입니다(`agents/notice/`). 추천 순위 · 대체 경로 · 자격 판정 규칙은 공고 서버에 있고, 우리 코드는 부르고 받은 값을 검사 · 변환만 합니다. 워커에 `SBRAIN_NOTICE_API_URL`이 있으면 이 연결로(실제 모드), 없으면 같은 흐름 · 같은 판정 원칙의 스텁으로(스텁 모드) 돕니다. 공고팀이 수집 상태 · 공고 상세 · 자격 판정 API를 아직 주지 않아 지금은 스텁 모드입니다. 켜는 조건은 아래 3절.
- 공고 선택은 고른 공고 ID만 남기고, 워커의 G-01이 공고 상세와 자격 판정을 함께 받아 한 번에 저장합니다. G-01 · 추가 조회가 어떤 오류로 끝나도 실행은 실패하지 않고 안내와 함께 대기 지점으로 돌아갑니다. 자격 불통과 공고는 그 실행 건에서 막고(`ANNOUNCEMENT_BLOCKED`), 추가 조회에서 내용이 바뀌면 풉니다. 웹 쪽 변화는 `docs/공고연동_변경사항_웹팀전달.md`, 공고팀에 요청한 API는 `docs/공고서버_API요청_공고팀전달.md`에 있습니다.
- OpenAI 호출처 어댑터가 있습니다(`orchestrator/openai_provider.py`). 조율 Agent는 `gpt-6-luna`, 추론 강도 low가 기본값입니다(온도는 보내지 않음). 응답마다 토큰 사용량(입력 · 캐시 입력 · 출력 · 추론)을 기록합니다.
- **저장소는 두 가지**입니다. 메모리 구현(`MemoryStore`, 테스트 · 시연)과 공유 MySQL 구현(`SqlStore`, `store_sql/`)이 같은 동작을 하며, 흐름 테스트 전체를 두 저장소로 돌려 확인합니다. MySQL 테이블 정의는 `sql/orchestrator_schema.sql`이고 공유 DB 적용은 담당자가 직접 합니다.
- **워커 프로세스**(`python -m sbrain.worker`)가 시작 요청 · 구간 진행 · 재개를 가져가 처리합니다. 웹 서버와 별도 프로세스로 같은 MySQL을 봅니다(웹팀 합의 2026-09-30).
- 웹 서버 코드는 웹팀 몫입니다. 웹이 부를 함수(시작 요청 · 명령 · 재작성 묶음 요청 · 진행 상태 · 화면 · 결과 · 재작성 결과 조회 · 관리자 조회 · 중단 · 완전 삭제)와 웹 프로세스 조립(`build_web`)까지 있습니다 — `docs/Orchestrator_웹연동_함수명세.md`. 이번 변경으로 웹이 할 일은 `docs/웹연동_변경사항_웹팀전달.md`에 있습니다.
- **진행 상태의 원본은 Orchestrator**입니다. 웹 `projects`의 진행 컬럼에는 쓰지 않고, 웹은 함수로 읽습니다. Orchestrator가 쓰는 웹 테이블은 알림(`notifications`) · 관리자 실패 알림(`generation_failure_alerts`) · 검수 회수 문단(`proofread_logs`) INSERT 셋뿐입니다.
- 표현 검수(T-P2)는 문장마다 **시도별 기록**을 남깁니다. 학습 데이터 편입에 동의한 계정이면 보호 토큰 검사를 통과하지 못한 시도를 웹 `proofread_logs`에 한 행씩 씁니다(웹 스키마 변경 전에는 건너뜀).
- **실행 로그 12개월 처리**(`flow/retention.py`, 2026-10-05): 워커가 하루 한 번(여러 대 중 한 대만 — 작업 상태 표 `orch_jobs`), 마지막 활동이 12개월보다 오래된 실행 건의 기록(실행 · 호출 기록 등 여섯 가지)과 끝난 시작 요청을 **식별자 없는 통계 줄**(`orch_log_stats`, 계산은 `flow/log_stats.py`)로 옮기고 지웁니다. 살아 있는 실행 건은 실행 건 줄 · 산출물을 남겨 화면 · 이어 쓰기가 그대로이고, 완전 삭제된 실행 건(포인터 0개)은 줄까지 지웁니다. 관리자 실행 건 목록 · 운영 요약은 최근 12개월만 셉니다.
- **탈퇴 함수** `delete_account_data(account_id)`(확장): 웹이 프로젝트마다 중단 · 완전 삭제를 마친 뒤 부르면, 그 계정의 실행 건 · 산출물 · 기록 · 시작 요청을 통계 줄(까닭 '탈퇴')로 옮긴 뒤 바로 모두 지웁니다. 처리 중인 일이 있으면 아무것도 지우지 않고 `BUSY`입니다.
- **시각**: 프로세스 안의 시각은 모두 시간대 있는 UTC(`models/clock.py`의 `utc_now()`)이고, 웹에 돌려주는 시각에도 시간대 표시가 붙습니다. DB 시각 칸에는 시간대 없는 UTC가 들어갑니다. 자격 판정 기준일 · 마감 안내처럼 '오늘'이 필요한 판단은 한국 날짜입니다. 시작 요청이 끝나면 입력 사본(`form_json`)을 바로 비웁니다.

---

## 2. 먼저 알아둘 용어

코드와 주석은 기준 문서의 용어를 그대로 씁니다.

| 용어 | 뜻 |
|---|---|
| **Task** | Agent가 수행하는 작업 하나. `T-S1`(요구사항 분석)처럼 ID로 부릅니다. LLM · 검색을 호출합니다 |
| **규칙 단계** | LLM을 쓰지 않고 코드로 계산하는 단계 (`G-02a` 문서 평가 판정, `G-03` 보호 토큰 추출 등). `G-01` 자격요건 게이트는 공고 서버를 부르므로 `tools`를 받는 Task로 바뀌었습니다(LLM은 쓰지 않음) |
| **공고 서버** | 공고팀의 HTTP 서버. 공고 추천 · 수집 상태 · 공고 상세 · 자격 판정을 줍니다. 워커만 부릅니다 |
| **실제 모드 · 스텁 모드** | 워커에 `SBRAIN_NOTICE_API_URL`이 있을 때 · 없을 때. 실제 모드면 T-C2 · G-01이 공고 서버를 부르고, 스텁 모드면 Orchestrator 안의 스텁 공고로 같은 흐름을 돕니다 |
| **합치기** | 앞 단계 결과들을 하나로 묶는 규칙 단계 (`M-1` ~ `M-4`). 기준 문서에 ID가 없어 구현용 ID를 붙였습니다 |
| **산출물** | 단계가 만든 결과. `planDoc@3`처럼 **이름@버전**으로 가리킵니다 |
| **실행 건 (Run)** | 사용자 한 명이 공고 하나로 진행하는 작업 한 건. 계정당 동시에 1건만 진행할 수 있습니다 |
| **대기 지점** | 사용자 선택을 기다리며 멈추는 화면 (공고 선택, 작성 시작, 문서 평가, 산출물 확인, 종합 평가) |
| **재시도** | 호출이 실패하거나 늦거나 응답 형식이 깨져서 **같은 호출을 바로 다시 보내는 것** (최대 5회) |
| **재개** | 재시도를 다 써서 멈춘 실행을 **시간을 두고 실패한 지점부터 다시 하는 것** (15분 → 30분 → … 최대 5번) |
| **재수행** | 결과가 **검사를 통과하지 못해 시스템이 다시 만드는 것** (최대 2회) |
| **재작성** | 사용자가 화면에서 **묶음을 골라 다시 만들게 하는 것** (묶음마다 1회). 묶음 이름은 문서층 `문제인식` · `실현가능성` · `성장전략` · `팀 구성`(임시), 산출물층 `실행 파일` · `인포그래픽`. 같은 화면에서 2초 안에 들어온 요청은 한 번에 실행 |
| **확정 동작** | 재수행을 다 해도 통과하지 못할 때 적용하는 정해진 처리 (예: 출처 없는 수치 제거) |
| **스텁** | 실제 구현 대신 끼워 둔 가짜 구현. 뼈대를 검증하려고 둡니다 |
| **잠정** | 기준 문서가 값을 정하지 않아 임시로 둔 값. 코드 주석과 문서에 `(잠정)`으로 표시합니다 |
| **확장** | 기준 문서에 없는 필드. 코드에서 `ext()`로 선언합니다 |

**단계 ID 읽는 법:** `T-C*` 조율 · `T-S*` 전략 · `T-W*` 작성 · `T-B*` 구현 · `T-V1` 검증-1 · `T-V2` 검증-2 · `T-P*` 검수 · `G-*` 규칙 단계 · `M-*` 합치기 · `R-8` 첨부 문서 텍스트 추출(규칙 모듈)

**주석의 출처 표기:** 코드 주석의 "시트 N"은 기준 문서(기능정의서)의 시트 번호, "기획서 N-M"은 기획서의 절 번호입니다.

| 기준 문서 시트 | 내용 | 해당 코드 |
|---|---|---|
| 1 개요 | 횟수 · 간격 설정값 | `sbrain/orchestrator/settings.py` |
| 2 Agent기능정의 | Task 실행 순서 · 호출 규칙 | `sbrain/flow/catalog.py`, `sbrain/flow/sbrain_flow.py` |
| 3 입출력변수명세 | Task별 입력 · 출력 | `sbrain/contracts/tasks.py` |
| 4 타입정의 | Agent 간 주고받는 공통 타입 | `sbrain/models/` |
| 5 규칙모듈 | LLM 없이 구현하는 규칙 (R-6 재작성, R-9 실행 상태, R-11 호출 실패 등) | `sbrain/orchestrator/engine.py`, `sbrain/flow/` |
| 6 오류코드 | 오류 코드와 사용자 안내 문구 | `sbrain/orchestrator/errors.py` |
| 7 재작성·재수행매핑 | 무엇을 다시 돌릴지의 대응표 | `sbrain/flow/rework_map.py` |

---

## 3. 설치와 테스트

모든 명령은 이 `agent-orchestration` 폴더에서 실행합니다. 패키지는 가상환경(`.venv`)에만 설치합니다.

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python --version                          # Python 3.12.x 인지 확인
python -m pip install -r requirements.txt
python -m pytest
```

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version                          # Python 3.12.x 인지 확인
python -m pip install -r requirements.txt
python -m pytest
```

정상이면 마지막 줄이 다음과 같습니다(MySQL 통합 테스트 47건은 아래 설정이 없으면 건너뜁니다).

```text
1225 passed, 47 skipped
```

테스트는 네트워크에 나가지 않습니다. `.env`에 `SBRAIN_NOTICE_API_URL`을 넣어 두어도 `tests/conftest.py`가 모든 테스트에서 그 값을 없는 것으로 봐서 실제 공고 서버를 부르지 않습니다.

**환경 변수와 `.env`**

OpenAI API 키 같은 값은 환경 변수로 주거나, 이 폴더의 `.env` 파일에 적습니다. `.env.example`을 `.env`로 복사해 값을 채우면 됩니다.

```powershell
copy .env.example .env     # macOS / Linux: cp .env.example .env
```

| 변수 | 쓰는 곳 |
|---|---|
| `OPENAI_API_KEY` | OpenAI 호출처 `OpenAIProvider` (8.4). 워커 필수 |
| `SBRAIN_DB_URL` | 공유 MySQL 접속 URL — 워커 · 웹 조립(`build_web`) 필수 |
| `SBRAIN_NOTICE_API_URL` | 공고 서버 기본 주소 `http(s)://호스트[:포트][/경로]` (선택) — 워커만 읽는다. 있으면 실제 모드, 비우면 스텁 모드. 실제 주소는 비밀 값처럼 다루고 문서 · 로그에 적지 않는다(예시는 `http://example.invalid:8000`) |
| `SBRAIN_WORKER_POLL_SEC` · `SBRAIN_WORKER_THREADS` · `SBRAIN_WORKER_LEASE_SEC` | 워커 설정 (선택, 기본 1초 · 4 · 120초, 잠정) |
| `SBRAIN_WORKER_LOG_DIR` · `SBRAIN_WORKER_LOG_KEEP_DAYS` | 워커 운영 로그 파일 (선택) — 폴더를 넣으면 화면과 같은 줄을 UTC 날짜 파일에도 쓴다(워커마다 다른 폴더). 일수 N을 넣으면 N일 넘은 로그 파일을 지운다(기본 지우지 않음, 운영은 366 이하 권장) |
| `SBRAIN_TEST_MYSQL_URL` | MySQL 8 통합 테스트용 **로컬** DB (선택) |
| `SBRAIN_TEST_WEB_SCHEMA` | MySQL 통합 테스트가 읽는 웹 스키마 `app_schema.sql` 경로 (선택 — 없으면 이 폴더 한 단계 위의 `web/backend/`에서 찾음) |

- 찾는 순서는 **환경 변수 → `.env` → 기본값**입니다. 이미 설정된 환경 변수가 이깁니다. 빈 값(`KEY=`)은 없는 것으로 봅니다.
- 값은 적힌 그대로 읽습니다(`${VAR}` 치환 없음). 공백이나 `#`이 들어가면 따옴표로 감쌉니다.
- 코드에서는 `sbrain.env.get_env("이름")`으로 읽습니다. `os.environ`은 바꾸지 않습니다.
- `.env`에는 비밀 값이 들어가므로 Git이나 저장소 사본에 올리지 않습니다.

**MySQL 8 통합 테스트 켜기**

로컬 Docker로 MySQL 8을 띄우고 접속 URL을 `.env`(또는 환경 변수)에 넣으면 MySQL 테스트도 돕니다.

```powershell
docker compose -f docker/mysql-test.yml up -d --wait     # mysql:8.0(공유 DB와 같은 8.0 계열), 127.0.0.1:3307, 데이터는 메모리에만
# .env:  SBRAIN_TEST_MYSQL_URL=mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_test?charset=utf8mb4
python -m pytest                                          # 건너뜀 없이 전체 1272건
docker compose -f docker/mysql-test.yml down              # 끄기
```

- 테스트가 그 DB의 테이블을 모두 지우고 새로 만듭니다. 그래서 **로컬 주소이고 DB 이름에 `test`가 들어간 URL만** 받습니다. 공유 DB 주소를 넣지 않습니다.
- 준비 순서: 테스트용 최소 `notices` → 웹 스키마(`app_schema.sql`, 읽기만 — 위치는 `SBRAIN_TEST_WEB_SCHEMA` 참고) → 테스트 DB에서만 `proofread_logs`를 웹팀이 바꿀 모양으로(`project_id`(NULL 허용, `projects` 삭제 때 SET NULL) · `model_version` 추가) → `sql/orchestrator_schema.sql`.
- 표를 지우고 새로 만드는 것은 pytest 프로세스에서 처음 한 번이고, 그 뒤 MySQL 테스트는 같은 표를 함께 씁니다. 대기 시작 요청처럼 워커가 가져갈 일을 남기는 MySQL 테스트는 끝에 취소해야 뒤의 워커 테스트가 깨지지 않습니다. MySQL 테스트를 고쳤으면 그 파일과 전체를 모두 돌립니다.

**워커 실행**

```powershell
python -m sbrain.worker          # Ctrl+C로 멈춤 — 하던 단계를 끝내고 점유를 푼다
python -m sbrain.worker --once   # 한 바퀴만 돌고 끝낸다 (점검용)
```

`SBRAIN_DB_URL` · `OPENAI_API_KEY`가 없으면 시작하지 않습니다. 로그는 표준 출력에 한 줄씩(가져간 일 · 끝난 상태, 단계마다 `단계시작` · `단계끝`, `대기` · `실행끝` · `재개예약`)이고 프롬프트 · 응답 내용 · 계정 번호는 남기지 않습니다. `SBRAIN_WORKER_LOG_DIR`을 넣으면 같은 줄을 그 폴더의 UTC 날짜 파일(`YYYY-MM-DD.log`, 20MB를 넘으면 `.1.log` …)에도 씁니다. 폴더 하나에 워커 하나라서 여러 대를 띄우면 워커마다 다른 폴더를 줍니다. 자동 삭제는 기본 꺼짐이라 파일이 기한 없이 남습니다(탈퇴 · 12개월 처리도 지우지 않음) — 운영에서는 `SBRAIN_WORKER_LOG_KEEP_DAYS`를 366 이하로 켜기를 권장합니다. 줄 앞 시각은 UTC입니다(끝에 `Z`, 예 `2026-09-26 09:00:05Z` = 한국 18:00:05).

워커는 시작 직후와 그 뒤 10분(잠정)마다 실행 로그 12개월 처리를 돌 때인지 확인합니다. 마지막으로 끝까지 마친 지 24시간(잠정)이 지났으면 여러 워커 중 한 대가 돌고, 로그에는 "보관 작업 시작" · "보관 작업 끝 — 옮긴 실행 건 N · 지운 실행 건 N · 옮긴 시작 요청 N · 건너뜀 N"만 남깁니다. `--once`도 때가 됐으면 이 처리를 돕니다.

**공고 서버 연결 켜기 (실제 모드)** — 주소 설정은 담당자가 직접 합니다. 다음이 모두 맞은 뒤에 워커 환경 변수(또는 `.env`)에 `SBRAIN_NOTICE_API_URL`을 넣고 워커를 다시 띄웁니다.

- 공고팀이 네 API(공고 추천 · 수집 상태 · 공고 상세 · 자격 판정)를 모두 제공했고 함께 확인했다. 하나라도 없으면 모든 시작 요청이나 자격 확인이 X-C2-FAIL로 끝납니다.
- 운영 공고 서버가 AWS 내부망에 있고 외부 접근이 막혀 있다(인증 없음 — 워커만 접근).
- 워커가 1대다. 공고 서버 호출은 워커 프로세스 안에서 한 번에 하나씩 보내며, 공고팀이 동시 호출 안전성을 확인하기 전에는 여러 대를 띄우지 않습니다.
- 공개된 공고팀 시험 서버에는 가짜 신청 정보만 흐르는 워커로만 연결한다.
- 스텁 ↔ 실제를 바꿀 때는 그 전에 만든 시험 실행 건을 중단하고 새 프로젝트로 새로 시작합니다(스텁 공고 ID는 공고 서버에 없다).
- 주소 형식이 틀리면 워커가 조립 단계에서 `ValueError`로 시작하지 않습니다(메시지에 주소는 없음). 어느 모드인지는 로그에 나오지 않습니다 — 화면 3 카드 제목이 `공고 A01`처럼 나오면 스텁 모드입니다.

**웹 서버에서 쓰기** — 웹 프로세스는 이 폴더를 패키지로 설치해 `build_web`으로 조립합니다(`pyproject.toml`). 함수 명세는 `docs/Orchestrator_웹연동_함수명세.md`.

```powershell
pip install -e <이 폴더>
```

**Orchestrator 테이블 DDL 다시 만들기** — 테이블 정의(`sbrain/store_sql/schema.py`)를 바꾸면 `python -m sbrain.store_sql.ddl`로 `sql/orchestrator_schema.sql`을 다시 만듭니다(테스트가 둘이 같은지 확인합니다). 테이블은 12개입니다. 2026-10-02에 `orch_runs.collect_until` 컬럼이, 2026-10-05에 표 2개(`orch_log_stats` · `orch_jobs`)와 인덱스 2개(`ix_orch_runs_updated` · `ix_orch_start_requests_status_updated`)가 늘었습니다. 그 전 DDL을 공유 DB에 이미 적용했다면 ALTER(와 새 DDL 다시 실행)가 필요합니다(아직 적용 전이면 DDL 파일만 쓰면 됩니다). 이 변경 전에 만든 개발 · 시연 DB는 시각이 로컬 시각으로 들어 있어(새 코드는 UTC로 읽음) `orch_` 표를 다시 만드는 편이 안전합니다.

---

## 4. 한 번 돌려 보기

가상환경을 켠 상태로 이 폴더에서 `python`을 실행하고, 아래 코드를 대화형 셸에 붙여 넣습니다. 스텁 Agent로 사전 정보 입력부터 결과물까지 한 바퀴를 돕니다.

```python
from datetime import date
from sbrain.bootstrap import build_stub_app
from sbrain.models import PreInput

app = build_stub_app()                     # 스텁 Agent + 메모리 저장소로 조립
orch = app.orchestrator                    # 웹 서버가 부를 명령 창구

form = PreInput(
    idea_text="동네 헬스장 회원 관리 서비스", applicant_type="법인", founded_at=date(2025, 3, 2),
    representative_name="홍길동", representative_career=["헬스장 운영 5년"],
    revenue_unit_price=35000, development_period="6개월", team_careers=["개발자 1명"],
    birth_date=date(1990, 1, 1), gender="남", region="서울", industry_code="J62",
    hiring_plan="없음", facilities="없음", partners="없음",
)

res = orch.start_run("acc-1", form)        # 화면 2: 사전 정보 제출 → 공고 후보 조회
run_id = res.run_id

orch.select_announcement(run_id, "A01")    # 화면 3: 공고 선택
orch.advance(run_id)                       #   → 자격요건 확인(G-01)
orch.start_writing(run_id)                 # 화면 5: 작성 시작
orch.advance(run_id)                       #   → 계획서 작성 ~ 문서 평가
orch.decide(run_id, 6, "진행")             # 화면 6: 문서 평가 → 진행
orch.advance(run_id)                       #   → 프로토타입 제작 ~ 검증
orch.decide(run_id, 8, "진행")             # 화면 8: 산출물 확인 → 진행
orch.decide(run_id, 9, "진행")             # 화면 9: 종합 평가 → 진행
orch.advance(run_id)                       #   → 표현 검수 ~ 결과물

v = orch.view(run_id)
print(v.step, v.progress, v.screen_status)
print([r.task_id for r in app.store.executions(run_id)])
```

출력:

```text
결과물 완료 완료
['T-C1', 'T-C2', 'G-01', 'T-C3', 'T-S1', 'T-S2', 'T-W1', 'T-W2', 'T-W3', 'M-1', 'T-V1', 'G-02a', 'T-B1', 'T-B2', 'G-04', 'M-3', 'T-V2', 'G-02b', 'G-03', 'T-P1', 'T-P2', 'M-4', 'T-C4']
```

**보는 법:** 명령(`select_announcement`, `start_writing`, `decide` 등)은 상태를 확인하고 **할 일을 대기열에 넣기만** 합니다. 실제 실행은 `advance`가 다음 대기 지점까지 합니다. 단, `start_run`은 사전 단계를 바로 실행하고, 화면 8의 '진행'은 실행할 단계 없이 화면 9로 넘어가므로 `advance`가 필요 없습니다. 재작성을 요청하면 **모으는 시간(2초, 잠정)** 이 지나야 `advance`가 단계를 돕니다(그 전에는 아무것도 하지 않음).

**운영에서는** 위의 `start_run` · `advance`를 웹이 부르지 않습니다. 웹은 `request_start`(시작 요청)와 `*_for_project` 명령 · 조회만 부르고, 사전 단계 · `advance` · 재개는 워커가 합니다(9절). `start_run`은 두 조각을 차례로 부르는 테스트 · 시연용 동기 경로이고, 웹 조립(`build_web`)에서 부르면 `WEB_NOT_ALLOWED`입니다.

**공유 MySQL과 실제 조율 Task로 조립하기:** `build_app(db_url)`(워커용)이 `SqlStore` · 웹 DB 입력 공급처 · DB 설정 입력 · OpenAI 호출처 · 조율 T-C1 · T-C3 실구현 · 지시문 다시 쓰기를 묶습니다. 다시 쓰기 호출은 대상 Task가 스텁이어도 실제 OpenAI로 갑니다. 공고 서버 주소가 있으면(`notice_api_url` 인자, 주지 않으면 `SBRAIN_NOTICE_API_URL`) T-C2 · G-01도 공고 서버 연결로 바꿉니다. 빈 문자열을 넘기면 환경 변수와 관계없이 스텁입니다. 시험할 때는 `notice_transport`로 가짜 전송을 함께 넘겨 네트워크에 나가지 않게 합니다. 나머지 Agent는 스텁이고, 스텁 Task는 실제 OpenAI를 부르지 않습니다.

**공고 선택 뒤 보는 법:** `select_announcement`는 고른 ID만 남깁니다. 선택 공고(`outputs.selectedAnnouncement`) · `view().announcement_id` · 자격 결과는 `advance`로 G-01이 돈 뒤에 함께 바뀝니다. 사업자(`개인사업자` · `법인`)인데 설립일(`founded_at`)이 없으면 G-01이 E-G1-MISSING으로 공고 선택에 돌려보내므로, 위 예처럼 설립일을 넣어야 작성 시작으로 넘어갑니다.

---

## 5. 전체 흐름

동그라미는 사용자 선택을 기다리는 **대기 지점**, 네모는 Orchestrator가 연속으로 실행하는 **구간**입니다.

```mermaid
flowchart TD
  PRE["PRE · 사전 단계<br/>(첨부 있으면 R-8) → T-C1 요구사항 해석 → T-C2 공고 매칭"]
  PRE -- "후보 1건 이상 → 실행 건 생성" --> S3(("화면 3<br/>공고 선택"))
  S3 -- "추가 조회 (1회)" --> MORE["MORE · T-C2 추가 10건"] --> S3
  S3 -- 공고 선택 --> GATE["GATE · G-01 자격요건 확인"]
  GATE -- 불통과 --> S3
  GATE -- 통과 --> S5(("화면 5<br/>작성 시작"))
  S5 --> WRITE["WRITE · 작업 분해 → 전략 → 작성 → 합치기 → 검증-1 → 문서 판정"]
  WRITE --> S6(("화면 6<br/>문서 평가"))
  S6 -- 재작성 --> S6
  S6 -- 진행 --> PROTO["PROTO · 구현 → 안내 문서 → 합치기 → 검증-2 → 종합 판정"]
  PROTO --> S8(("화면 8<br/>산출물 확인"))
  S8 -- 재작성 --> S8
  S8 -- 진행 --> S9(("화면 9<br/>종합 평가"))
  S9 -- 재작성 --> S9
  S9 -- "진행 (되돌릴 수 없음)" --> REVIEW["REVIEW · 보호 토큰 → 형식 검수 → 윤문 → 합치기 → 결과 통합"]
  REVIEW --> END(["화면 11 · 결과물"])
```

| 구간 | 실행하는 단계 (순서대로) | 끝나면 |
|---|---|---|
| PRE | `R-8`(첨부가 있을 때) → `T-C1` → `T-C2` | 후보가 있으면 실행 건을 만들고 화면 3 |
| MORE | `T-C2` (추가 10건, 1회, 최대 20건). 첫 조회와 겹친 공고는 빼고 첫 조회 카드를 새 내용으로 바꿈(내용 바뀜 표시) | 화면 3 (실패해도 화면 3 — 안내와 함께 기회를 돌려줌) |
| GATE | `G-01` (공고 상세 + 자격 판정, 한 번에 저장) | 통과면 화면 5, 불통과 · 입력 누락이면 화면 3. G-01이 실패하면 고르기 전 화면(3 또는 5) |
| WRITE | `T-C3` → `T-S1` → `T-S2` → `T-W1` → `T-W2` → `T-W3` → `M-1` → `T-V1` → `G-02a` | 화면 6 |
| PROTO | `T-B1`\* → `T-B2` → `M-2`\*\* → `G-04` → `M-3` → `T-V2` → `G-02b` | 화면 8 |
| REVIEW | `G-03` → `T-P1` → `T-P2` → `M-4` → `T-C4` | 화면 11 (완료) |
| REWORK6 · 8 · 9 | 사용자가 고른 묶음에 따라 다시 돌릴 단계(같은 화면에서 2초 안에 들어온 묶음 요청의 합집합). 문서층 묶음은 지금 임시로 계획서 전체(`T-W1` → `T-W2` → `T-W3`)를 다시 만든다 | 요청한 화면 |

\* 카테고리가 '원페이지'면 생략 &nbsp; \*\* '원페이지'일 때만

전체 단계 목록:

| ID | 이름 | 담당 Agent | 종류 |
|---|---|---|---|
| R-8 | 첨부 문서 텍스트 추출 | 조율 | 규칙 |
| T-C1 | 요구사항 해석 | 조율 | Task |
| T-C2 | 공고 매칭 | 조율 | Task (공고 서버 · LLM 없음) |
| G-01 | 자격요건 게이트 | 조율 | Task (공고 서버 · LLM 없음, 고정 Task 14개에 세지 않음) |
| T-C3 | 작업 분해 | 조율 | Task |
| T-S1 | 요구사항 분석 | 전략 | Task |
| T-S2 | 목표 시장 분석 | 전략 | Task |
| T-W1 | 사업계획서 본문 작성 | 작성 | Task |
| T-W2 | 그래프 생성 | 작성 | Task |
| T-W3 | 표 생성 | 작성 | Task |
| M-1 | 합치기① 차트 · 표를 계획서에 합침 | 조율 | 합치기 |
| T-V1 | 사업계획서 검증 | 검증-1 | Task |
| G-02a | 문서 평가 판정 | 조율 | 규칙 |
| T-B1 | 실행 파일(HTML) 제작 | 구현 | Task |
| T-B2 | 인포그래픽 제작 | 구현 | Task |
| M-2 | 합치기② 원페이지 산출물을 Prototype으로 감쌈 | 조율 | 합치기 |
| G-04 | 실행 안내 문서 생성 | 조율 | 규칙 |
| M-3 | 합치기③ readmePath를 Prototype에 기입 | 조율 | 합치기 |
| T-V2 | 프로토타입 검증 | 검증-2 | Task |
| G-02b | 종합 평가 판정 | 조율 | 규칙 |
| G-03 | 보호 토큰 추출 | 검수 | 규칙 |
| T-P1 | 사업계획서 문장 형식 검수 | 검수 | Task |
| T-P2 | 한국어 문장 윤문 | 검수 | Task |
| M-4 | 합치기④ 검수 결과 반영 · 검수 로그 집계 | 조율 | 합치기 |
| T-C4 | 결과 통합 · 전달 | 조율 | Task |

단계별 입력 · 출력, 제한 시간, 실패 정책은 `docs/Agent_연동_규격_초안.md` 6 · 7절에 표로 정리되어 있습니다.

---

## 6. 폴더 구조

```text
agent-orchestration/
├── README.md                  # 이 문서
├── .gitignore                 # Git 제외 목록
├── docs/                      # 설계 · 연동 문서 (13절 참고)
├── .env.example               # 환경 변수 예시 — .env로 복사해 값을 채운다 (.env는 올리지 않음)
├── requirements.txt           # 의존성 (pydantic, SQLAlchemy, PyMySQL, openai, python-dotenv, pytest)
├── pyproject.toml             # 패키지 정의 — 웹 프로세스가 설치해 쓴다, sbrain-worker 명령
├── pytest.ini                 # 테스트 설정 (tests 폴더, -q)
├── sql/
│   └── orchestrator_schema.sql  # Orchestrator 테이블 DDL (생성 파일 — 공유 DB 적용은 담당자)
├── docker/
│   └── mysql-test.yml         # MySQL 8 통합 테스트용 로컬 DB (Compose, mysql:8.0)
├── sbrain/
│   ├── bootstrap.py           # 구성 조립 — build_stub_app(테스트) · build_app(워커) · build_web(웹 서버)
│   ├── worker.py              # 워커 프로세스 (python -m sbrain.worker) — 일 가져가기 + 12개월 처리 확인
│   ├── worker_log.py          # 워커 운영 로그 — 화면 + 날짜 · 순번 파일, 폴더 잠금, 선택 자동 삭제
│   ├── env.py                 # 환경 변수 읽기 — 환경 변수 → .env 순서 (get_env)
│   ├── models/                # 공통 타입 (기준 문서 시트 4)
│   │   ├── base.py            #   공통 기반 SBModel(시각 필드를 UTC로 맞춤), 확장 표시 ext(), 열거형
│   │   ├── clock.py           #   시각 — utc_now() · as_utc · naive_utc · utc_clock · 한국 날짜 kst_today · kst_month
│   │   ├── domain.py          #   입력 · 공고 · 계획서 · 프로토타입 등 업무 타입
│   │   ├── rework.py          #   CheckResult · ReworkOrder · ReworkInput 등 다시 만들기 관련
│   │   ├── run.py             #   실행 건(Run), 실행 상태, 알림, 재작성 사이클 · 마지막 재작성 결과
│   │   └── scoring.py         #   점수 · 채점 결과
│   ├── contracts/
│   │   └── tasks.py           # Task별 입력 · 출력 규격 (기준 문서 시트 3), T-P2 문장 결과 · 시도 기록
│   ├── intake/                # 사전 정보 입력 연동 — 웹 DB → PreInput
│   │   ├── record.py          #   웹 DB 행 그릇 (잠정 규격)
│   │   ├── mapping.py         #   행 → PreInput 변환, 필수 항목 재확인 (E-C1-REQUIRED)
│   │   ├── source.py          #   공급처 인터페이스 · 메모리 구현
│   │   └── sql_source.py      #   공유 MySQL 구현 (SQLAlchemy)
│   ├── orchestrator/          # 범용 뼈대 — S-Brain 고유 규칙이 없음
│   │   ├── engine.py          #   실행 엔진: 대기열 실행, 재수행 · 재개 · 실패, 재작성 사이클
│   │   ├── registry.py        #   Agent 등록부(Task별 설정 찾기) · Task 등록부(TaskSpec), 입력 연결(Bind)
│   │   ├── tools.py           #   Task에 넘기는 호출 도구(글 · 검색 · 이미지): 재시도 · 제한 시간 · 오류 분류 · 호출 기록
│   │   ├── openai_provider.py #   OpenAI 호출처 어댑터 (LLMProvider 구현)
│   │   ├── openai_image.py    #   OpenAI 이미지 호출처 어댑터 (ImageProvider 구현, 확장)
│   │   ├── runlog.py          #   실행 로그 줄 — 로거 sbrain.run (워커만 처리기를 단다)
│   │   ├── context.py         #   실행 중 산출물 버전 관리, 한 번에 저장할 기록 모음
│   │   ├── store.py           #   저장소 인터페이스 (Store, CommitBatch, StartRequest)
│   │   ├── memory_store.py    #   저장소의 메모리 구현
│   │   ├── settings.py        #   설정값과 기본값(Task별 호출 설정 Settings.tasks), 잠정 항목 목록(PROVISIONAL)
│   │   ├── trace.py           #   추적 기록 타입 (실행 기록 · 호출 로그 · 피드백 연결 등)
│   │   └── errors.py          #   오류 코드(시트 6)와 예외
│   ├── flow/                  # S-Brain 고유 규칙
│   │   ├── catalog.py         #   S-Brain의 Task 등록부 (25개 단계)
│   │   ├── sbrain_flow.py     #   구간 · 대기 지점 · 재작성 경로 · 알림, 재작성 · 재수행 지시문(다시 쓰기 · 저장), T-P2 병렬 실행
│   │   ├── instruction.py     #   지시문 세 부분(틀 · 안내 · 참조 자료) 나누기 · 안내 바꾸기 · 문제 내용 덧붙이기
│   │   ├── rework_map.py      #   재작성 · 재수행 대응표 (시트 7), 재작성 묶음 이름
│   │   ├── service.py         #   명령 창구 SBrainOrchestrator — 시작 요청 · 명령 · 재작성 요청 · 진행 상태 · 중단 · 완전 삭제 · 탈퇴
│   │   ├── reads.py           #   화면 조회(모양 초안) · 지금까지 결과 · 재작성 결과 · 관리자 조회(최근 12개월 범위)
│   │   ├── log_stats.py       #   기록 → 식별자 없는 통계 줄 계산 (실행 줄 · 시작요청 줄), 관리자 현재 점수와 같은 정의
│   │   └── retention.py       #   실행 로그 12개월 처리 (워커가 하루 한 번, 작업 점유)
│   ├── store_sql/             # SQL 저장소 — 공유 MySQL 8 (테스트는 SQLite)
│   │   ├── schema.py          #   Orchestrator 테이블 12개 정의 (DDL의 단일 원본), 시각 형식 UtcDateTime
│   │   ├── ddl.py             #   MySQL DDL 파일 생성 (python -m sbrain.store_sql.ddl)
│   │   ├── db.py              #   접속 엔진 (MySQL · SQLite)
│   │   ├── store.py           #   SqlStore — 저장소 인터페이스 구현
│   │   ├── web_tables.py      #   Orchestrator가 읽고 쓰는 웹 테이블 (알림 · 실패 알림 · 검수 회수 문단 INSERT, 학습 동의 · 설정 읽기)
│   │   └── settings_source.py #   DbSettingsProvider — verification_policies를 설정 입력으로
│   └── agents/
│       ├── supervisor/        # 조율 Agent 구현 — T-C1 (tc1.py) · T-C3 (tc3.py) · 작업 계획 부품 (plan.py) · 지시문 다시 쓰기 (rewrite.py), bind_supervisor()
│       ├── notice/            # 공고 서버 연결 — 실제 T-C2 · G-01, bind_notice()
│       │   ├── client.py      #   HTTP 클라이언트 NoticeClient (표준 라이브러리, 호출 하나씩, 공고 없음 값)
│       │   ├── tc2.py         #   실제 T-C2 — 수집 상태 → 공고 추천 → 카드, 보내는 칸 · 시 · 도 바꾸기
│       │   ├── g01.py         #   실제 G-01 — 공고 상세 → Announcement, 자격 판정 → GateResult · 업력
│       │   └── convert.py     #   응답 키 · 값 검사 (약속 밖이면 FormatError)
│       ├── form_defaults.py   # 신청자 유형별 양식 · 평가항목 · 채점 기준표 묶음(FORM_TABLE), 선택 공고 자리 표시 양식 (모두 잠정)
│       └── stubs.py           # 스텁 Agent(스텁 T-C2 · G-01 포함), 가짜 LLM(FakeLLM), 시나리오(StubScenario)
└── tests/                     # pytest 테스트 (1272건) — conftest.py(저장소 선택 · 공고 서버 주소 격리) · webdb.py · mysqldb.py 도움 모듈
```

**설계 원칙:** `orchestrator/`에는 어떤 서비스에도 쓸 수 있는 범용 장치만 두고, 화면 번호 · 알림 대상 · 재작성 경로 같은 S-Brain 고유 규칙은 `flow/`에만 둡니다. 엔진은 `Flow` 인터페이스(`engine.py`)를 통해서만 S-Brain 규칙을 부릅니다.

---

## 7. 내부 동작

### 7.1 구성 요소의 관계

```mermaid
flowchart LR
  Web["웹 서버 (웹팀)<br/>build_web"] -->|"시작 요청 · 명령 · 조회"| Svc["SBrainOrchestrator<br/>flow/service.py · reads.py"]
  Wk["워커<br/>worker.py · build_app"] -->|"가져가기 → 사전 단계 · advance · resume"| Eng["Engine<br/>orchestrator/engine.py"]
  Svc -->|명령 · 상태| Store
  Eng <-->|S-Brain 고유 규칙| Flow["SBrainFlow<br/>flow/sbrain_flow.py"]
  Eng -->|단계 정보 조회| Reg["TaskRegistry<br/>flow/catalog.py"]
  Eng -->|"입력 모으기 · 출력 보관"| Ctx["RunContext<br/>orchestrator/context.py"]
  Ctx -->|"CommitBatch로 한 번에 저장"| Store[("Store<br/>MemoryStore · SqlStore(MySQL)")]
  Eng -->|호출| Fn["Task 함수<br/>agents/stubs.py · supervisor/tc1.py · tc3.py · notice/"]
  Fn -->|"llm · search"| Tools["Tools<br/>orchestrator/tools.py"]
  Tools --> Prov["LLMProvider<br/>FakeLLM · OpenAIProvider"]
  Tools -->|"search — 실제 모드만"| NS["공고 서버 (공고팀 HTTP)"]
```

`bootstrap.py`의 조립 함수(`build_stub_app` · `build_app` · `build_web`)가 이 구성 요소들을 만들어 서로 연결하고 `App` 객체로 돌려줍니다. `App`에는 `orchestrator`(명령 창구), `engine`, `store`, `registry`, `llm`(가짜 호출처), `scenario`, `settings`가 들어 있습니다.

### 7.2 단계 하나가 실행되는 과정

`Engine.run_step()`이 대기열 맨 앞 단계를 다음 순서로 처리합니다.

1. Task 등록부에서 그 단계의 정보(`TaskSpec`)를 꺼냅니다. 담당 Agent, 입출력 타입, 실행 함수, 실패 정책 등이 들어 있습니다.
2. **입력을 모읍니다.** `TaskSpec.inputs`의 연결 정보(`Bind`)를 보고 산출물 · 설정값 · 사용자 명령 · 작업 지시문 등에서 값을 가져옵니다. 작업 지시문은 `Flow.build_instruction`이 만듭니다 — 재작성 · 재수행이면 워커 조립에서는 조율 LLM이 안내 부분을 다시 쓰고(그 호출도 이 실행 기록에 남음) 문제 내용을 덧붙여 `<Task>.instruction`으로 저장합니다. Task는 저장소에 직접 접근하지 않습니다.
3. 입력을 규격 타입(`contracts/tasks.py`)으로 검사합니다.
4. Task라면 그 Task의 설정 항목(모델 · 호출처 · 온도 · 추론 강도 · 이미지 설정 · 제한 시간)을 입힌 `Tools`를 만들어 함께 넘깁니다. 규칙 단계 · 합치기는 `Tools`를 받지 않습니다.
5. 출력을 규격 타입으로 검사하고, 각 필드를 **새 산출물 버전**으로 보관합니다.
6. 출력의 `check.passed`가 `false`이고 재수행 대상이면, 문제 내용을 담은 `ReworkInput`을 만들어 같은 Task를 다시 부릅니다(재수행).
7. 산출물 버전 · 현재 버전 포인터 · 실행 상태 · 추적 기록을 `CommitBatch` **하나로 한 번에 저장**합니다. 중간에 멈춰도 어디까지 했는지 어긋나지 않게 하기 위해서입니다.

### 7.3 산출물 버전과 되돌리기

- 산출물은 이름별로 버전이 쌓이고(`planDoc@1`, `planDoc@2`, …), **현재 버전 포인터**가 지금 쓰는 버전을 가리킵니다.
- 되돌리기는 **포인터만 옮깁니다.** 이전 버전과 기록은 지우지 않습니다.
- `featureList`는 한 번 정해지면 바뀌지 않습니다. 다른 값이 들어오면 변경분은 무시하고 기록만 남깁니다.

### 7.4 문제가 생겼을 때

| 상황 | 누가 | 처리 |
|---|---|---|
| LLM · 검색 호출 실패, 응답 지연, 형식 오류 | `Tools` | 같은 호출을 최대 5회 **재시도** |
| 재시도를 다 썼고 일시 오류 | `Engine` | 실행을 `재개대기`로 두고 15 → 30 → 60 → 120 → 240분 뒤 실패한 단계부터 **재개** (최대 5번, 총 12시간) |
| 재개 상한 초과, 또는 영구 오류(입력 · 운영) | `Engine` | 실행 **실패**. 단, 재작성 중이었다면 실행은 계속하고 재작성 전 결과로 되돌린 뒤 재작성 기회를 돌려줌 |
| 규칙 단계 · 합치기에서 코드 오류 | `Engine` | 위와 같이 실패 처리 (잠정). `G-04`만 기준 문서대로 오류가 나도 계속 진행 |
| 결과가 검사 불통과 | `Engine` | 문제 내용을 실어(워커에서는 지시문 안내를 다시 써서) 최대 2회 **재수행**. 그래도 불통과면 그대로 다음 단계로 (여섯 Task는 확정 동작 적용) |
| 사용자가 묶음을 골라 요청 (미달이 아니어도) | 명령 창구 + `Engine` + `Flow` | 같은 화면에서 2초 안의 요청을 모아 **재작성** 한 번 → 다시 채점 → 전후 점수를 비교해 높은 쪽을 남김 |
| 추가 조회 `T-C2` · 자격 확인 `G-01`이 어떤 오류로든 끝남 | `Engine` → `Flow` | 실행은 **실패시키지 않음.** 등록부 실패 정책(`rescue_segments`)에 든 구간이라 엔진이 `Flow.on_rescue`로 넘기고, 흐름이 안내(X-C2-FAIL, G-01의 공고 없음은 X-C2-GONE)와 함께 대기 지점으로 돌림. 추가 조회는 기회도 돌려줌 |
| 추가 조회의 수집 상태가 '정상'이 아님 | `Flow` | 오류는 아니지만 실패로 봄 — E-C2-STALE, 조회 전 값으로 되돌리고 기회를 돌려줌 |

일부 Task는 재시도를 다 쓴 예외를 Task 안에서 받아 대체 경로로 갑니다. 예: `T-V2`는 보조 LLM이 실패하면 문자열 대조만으로 점수를 냅니다. 스텁 `T-C2`는 임베딩 검색이 실패하면 BM25 단독 순위로 갑니다. 공고 서버에 연결한 실제 `T-C2`는 대체 경로를 공고 서버가 안에서 하고 결과로 알려 주므로 이 예외를 받지 않습니다.

### 7.5 추적 기록

실행 흐름을 나중에 되짚을 수 있도록 다음을 남깁니다. **산출물 내용은 복사하지 않고 `이름@버전` 참조와 메타 정보만** 남깁니다.

| 기록 | 담는 것 |
|---|---|
| `ExecutionRecord` | 어떤 단계를, 어떤 모델로, 어떤 입력 버전으로 실행해 어떤 출력 버전을 만들었는지 |
| `CallLog` | 호출 한 건과 시도별 결과 · 토큰 사용량 (프롬프트 · 응답 내용은 남기지 않음) |
| `FeedbackLink` | 검사 결과 · 사용자 선택이 어느 실행으로 전달되었는지 |
| `ReworkComparison` | 재작성 전후 점수와 남긴 쪽 |
| `PointerEvent` | 되돌리기로 현재 버전 포인터가 옮겨진 기록 |
| `TraceEvent` | 규격 위반, 재개 예약, 재작성 시작 · 종료 등 |

기록 조회는 `app.store.executions(run_id)`, `app.store.call_logs(run_id)` 등 `Store`의 조회 함수로 합니다.

이 여섯 기록은 실행 건의 마지막 활동 12개월 뒤(워커의 12개월 처리)나 탈퇴 때 식별자 없는 통계 줄(`orch_log_stats`)로 옮기고 지웁니다. 화면 · 시도 번호가 기록 없이도 같도록 실행 건에 카테고리 · 화면 10 비교 기준 버전 · Task별 마지막 시도 번호를 따로 적어 둡니다. 확인용으로 `app.store.log_stats()`가 통계 줄을 돌려줍니다(웹 함수 아님).

---

## 8. Agent 구현을 끼워 넣는 방법

각 Agent 담당자는 Task 함수를 만들어 **`registry.bind(task_id, fn)` 한 줄로 스텁과 바꿔 끼웁니다.** 엔진 코드는 고칠 필요가 없습니다.

### 8.1 지켜야 할 규칙

- **함수 모양:** Task는 `def run(inp: XxxIn, tools: Tools) -> XxxOut`, 규칙 단계 · 합치기는 `def run(inp: XxxIn) -> XxxOut`입니다. 입력 · 출력 타입은 `contracts/tasks.py`에 Task마다 있습니다.
- **동기 함수**로 만듭니다. 병렬 처리가 필요한 곳(`T-P2`)은 Orchestrator가 합니다.
- **LLM · 검색 호출은 반드시 `tools`로 합니다.** HTTP 클라이언트나 SDK를 Task 안에서 직접 부르지 않습니다. `tools`를 거치지 않으면 재시도 · 제한 시간 · 호출 기록 · 재개가 동작하지 않습니다.
  - `tools.llm(messages, schema=..., parse=..., purpose="...")` — LLM 호출. `schema`(pydantic 모델)를 주면 응답 JSON을 검사해 그 타입으로 돌려줍니다.
  - `tools.search(purpose, fn)` — 임베딩 검색 · BM25처럼 LLM이 아닌 호출. `fn(timeout_sec)` 형태로 부릅니다.
  - `tools.image(prompt, image=None, size=None, quality=None, purpose="...")` — 이미지 호출. 결과는 PNG 바이트입니다. `image`(입력 그림)를 주면 그 그림을 바탕으로 고쳐 그리고, 없으면 새로 그립니다. `size` · `quality`를 비우면 그 Task 설정값(`image_size` · `image_quality`)을 씁니다. 재시도 · 제한 시간 규칙은 `tools.llm`과 같습니다. 이미지 설정이 없는 Task가 부르면 호출하지 않고 바로 실패합니다(지금은 `T-B2`만 설정이 있습니다).
- 모델 · 온도 · 추론 강도 · 이미지 모델 · 제한 시간은 `tools`가 그 Task의 설정 항목(`Settings.tasks[Task ID]`)에서 입힙니다. Task가 정하지 않습니다(바꾸는 법은 8.3).
- 재시도를 다 쓴 예외(`ToolCallExhausted`)는 대체 경로가 정해진 Task(`T-V2`, 스텁 `T-C2`)가 아니면 **받지 말고 그대로 올려 보냅니다.** Orchestrator가 재개를 처리합니다. 예외: `T-B2`는 `tools.image`의 예외만 받아 기본 아이콘으로 계속해도 됩니다(관리자 기록 '이미지대체'가 남습니다). `T-B2`의 `tools.llm` 예외는 올려 보냅니다.
- 재수행 대상 Task(`T-S1` · `T-S2` · `T-W1` · `T-W2` · `T-W3` · `T-B1` · `T-B2`)는 출력의 `check`에 자체 검사 결과를 채웁니다. 입력의 `rework_input.is_final_attempt`가 `true`인데도 통과하지 못하면, 확정 동작 대상 Task는 확정 동작을 적용하고 `check.final_action`에 그 내용을 적습니다.

### 8.2 예시

```python
from pydantic import BaseModel
from sbrain.bootstrap import build_stub_app
from sbrain.contracts import TS1In, TS1Out
from sbrain.models import CheckResult, RequirementAnalysis
from sbrain.orchestrator import Tools


class Answer(BaseModel):           # LLM이 돌려줄 JSON의 형태 (예시)
    ok: bool


def my_ts1(inp: TS1In, tools: Tools) -> TS1Out:
    # LLM 호출은 반드시 tools로 한다 (재시도 · 제한 시간 · 호출 기록이 자동으로 붙는다)
    tools.llm([{"role": "user", "content": inp.instruction}], schema=Answer, purpose="요구사항 분석")
    feats = list(inp.item_spec.core_features)
    ra = RequirementAnalysis(problem_statement="…", target_customer="…", feature_list=feats,
                             differentiator="…", use_cases=["…"])
    return TS1Out(requirement_analysis=ra, feature_list=feats,
                  check=CheckResult(passed=True, failures=[]))


app = build_stub_app()
app.registry.bind("T-S1", my_ts1)  # T-S1만 실제 구현으로, 나머지는 스텁 그대로
```

이미지를 쓰는 `T-B2`라면 이렇게 부릅니다(아이콘 그리기가 끝내 실패하면 기본 아이콘으로 계속).

```python
from sbrain.orchestrator import ToolCallExhausted


def draw_icon(tools: Tools, prompt: str) -> bytes | None:
    try:
        return tools.image(prompt, purpose="아이콘")   # 크기 · 품질은 T-B2 설정값(1024x1536 · medium)
    except ToolCallExhausted:
        return None   # T-B2만 허용 — 호출자가 기본 아이콘을 쓴다
```

### 8.3 Task별 모델 바꾸기

모델 · 호출처 · 온도 · 추론 강도 · 이미지 설정은 Task마다 하나씩 `Settings.tasks`에 있습니다. 기본값은 `orchestrator/settings.py`의 `_default_tasks()`이고, 키는 Task ID(`T-C1` … `T-C4`)와 재작성 · 재수행 지시문을 고쳐 쓰는 조율 호출 `지시문 다시 쓰기`입니다. 규칙 단계 · 합치기는 항목이 없습니다. 호출 한 번의 제한 시간은 `Settings.task_timeouts`(키 같음, 이미지는 `T-B2.image`)에 있습니다. 실행 건은 시작할 때 설정을 복사해 끝까지 쓰므로, 바꾼 값은 새로 시작하는 실행 건부터 적용됩니다.

```python
from sbrain.bootstrap import build_stub_app
from sbrain.orchestrator.settings import Settings

s = Settings()
s.tasks["T-B1"] = s.tasks["T-B1"].model_copy(update={"model": "gpt-6-luna-mini"})   # T-B1만 다른 모델로 (예시 이름)
s.task_timeouts["T-B2.image"] = 180                                                # 이미지 호출 한 번 제한 시간
app = build_stub_app(settings=s)   # 워커 · 웹 조립(build_app · build_web)도 settings= 를 받습니다
```

`temperature` · `reasoning_effort`를 `None`으로 두면 호출에 싣지 않습니다(모델 기본값). T-V1 온도 0 · T-P2 온도 0.2 이하는 기준 문서 규칙이라 설정값보다 앞섭니다.

### 8.4 실제 LLM 호출처 연결

LLM 호출처는 `LLMProvider` 인터페이스(`orchestrator/tools.py`)를 구현해 `Engine`의 `providers`에 이름별로 넣습니다. 호출처 이름(`openai`, `gpu-server` 등)은 Task별 설정값(`Settings.tasks`)에 있습니다. 이미지 호출처는 `ImageProvider`를 구현해 `Engine`의 `image_providers`에 넣습니다(OpenAI는 `OpenAIImageProvider`, 실제 API 미확인). OpenAI는 `OpenAIProvider`(`orchestrator/openai_provider.py`)가 있습니다. API 키는 환경 변수 `OPENAI_API_KEY`에서, 없으면 `.env` 파일에서 읽습니다(3절).

```python
from sbrain.orchestrator.openai_provider import OpenAIProvider

app.engine.providers["openai"] = OpenAIProvider()   # 모델은 Task별 Settings.tasks["T-C1"] 등 (조율 Task 기본 gpt-6-luna · 추론 강도 low)
```

```python
class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> str | LLMResponse: ...   # LLMResponse(text, usage: TokenUsage)
```

- `request.timeout_sec`를 HTTP 클라이언트의 timeout으로 겁니다.
- 시간 초과는 `TimeoutError`, 응답 코드 오류는 `ProviderError(status=...)`로 올립니다. 응답 코드로 오류 종류(일시 · 입력 · 운영)가 갈립니다.
- 토큰 사용량을 알 수 있으면 `LLMResponse(text, TokenUsage(...))`로 돌려줍니다(입력 · 캐시 입력 · 출력 · 추론). 문자열만 돌려줘도 동작합니다. 형식 오류로 버린 응답의 사용량도 기록되고, 실행 기록 · 관리자 조회에 합계가 보입니다.
- 가짜 호출처는 `app.llm.usage["T-C1"] = TokenUsage(...)`로 사용량을 돌려줄 수 있습니다.

### 8.5 공고 서버 연결 (T-C2 · G-01)

T-C2 · G-01의 실제 구현은 공고 서버 HTTP API를 부르는 `agents/notice/`입니다. 워커 조립이 주소가 있을 때 끼우며, 직접 끼울 때는 다음과 같습니다(시험은 가짜 전송으로).

```python
from sbrain.agents.notice import NoticeClient, bind_notice

bind_notice(app.registry, NoticeClient("http://example.invalid:8000", transport=fake_transport))
```

- 모든 호출은 Task 안에서 `tools.search`로 합니다(재시도 · 제한 시간 30초 · 호출 기록). HTTP는 표준 라이브러리만 씁니다.
- 공고 서버로 보내는 신청자 정보는 순위 · 판정에 쓰이는 칸뿐입니다(대표자 이름 · 생년월일 · 사업자등록번호 등은 보내지 않음).
- 공고 없음(404 + 본문 `NOTICE_NOT_FOUND`)은 재시도하지 않고 G-01이 `ResourceNotFound`를 올려 X-C2-GONE으로 안내됩니다. 응답에 약속한 키가 없거나 값이 약속 밖이면 `FormatError`로 재시도한 뒤 X-C2-FAIL입니다.
- API 약속(보내는 키 · 받는 키)은 `docs/공고서버_API요청_공고팀전달.md`에 있습니다.

### 8.6 코드 규칙

- 모든 타입은 `SBModel`(`models/base.py`)을 상속합니다. 파이썬 필드는 `snake_case`, JSON으로 내보낼 때(`.dump()`)는 기준 문서의 `camelCase` 이름을 씁니다.
- 기준 문서에 없는 필드를 추가할 때는 `ext()`로 선언합니다. JSON 스키마에 `x-extension` 표시가 붙어 원래 규격과 구분됩니다.
- 기준 문서가 정하지 않은 값을 임시로 정할 때는 주석에 `(잠정)`을 적습니다.

---

## 9. 명령 창구 (웹 서버 연동)

웹 서버는 `build_web(db_url, profile_count=...)`으로 조립한 `SBrainOrchestrator`의 함수만 부릅니다. 웹은 project_id만 알므로 웹용 함수는 모두 **project_id로** 받습니다. 인자 · 돌려주는 모양 · 오류 코드 · 부르는 시점은 **`docs/Orchestrator_웹연동_함수명세.md`**(웹팀 전달용)에 있습니다.

**웹이 부르는 함수**

| 함수 | 화면 | 하는 일 |
|---|---|---|
| `request_start(account_id, project_id)` | 2 | 웹 DB 입력 읽기 · 주인 확인 → 필수 항목(`E-C1-REQUIRED`, 누락 항목 이름) → 프로필(`E-AUTH-PROFILE`) → 동시 실행(`E-RUN-CONCURRENT`, 진행 중 작업 정보) → 시작 요청 '대기'. 결과 `StartCheck` |
| `start_status(project_id)` | 2 | 마지막 시작 요청의 상태(대기 · 처리중 · 완료 · 실패 · 취소) · 코드 · 안내 · run_id |
| `active_work(account_id)` | 2 | 사전 정보를 저장하기 전 동시 실행 확인 — 진행 중인 작업(`ActiveWork`) 또는 `None` |
| `view_project(project_id)` | — | 실행 건이 있으면 `view()`(재시도 · 재개 횟수, 다음 재개 시각, 재작성 화면, 모으는 중 여부, 선택 공고 포함), 없으면 시작 요청 상태 |
| `project_views(project_ids)` | 목록 | 여러 프로젝트의 `view_project`를 한 번에 |
| `wait_project(project_id, timeout_sec=60)` | 3 · 4 | 진행이 멈출 때(대기 지점 · 재개대기 · 끝남)까지 기다린 뒤 `view_project`. 제한 시간을 넘기면 그때 상태 |
| `screen(project_id, n)` | 3 · 4 · 6 · 8 · 9 · 10 · 11 | 화면별 내용(모양 초안, `flow/reads.py`). 대기 지점이 아니면 `SCREEN_NOT_READY`. 화면 10은 문장별 시도 기록 포함 |
| `outputs(project_id)` | 이어하기 · 9 · 10 · 11 | 지금까지 만든 결과(현재 버전)와 묶음별 남은 기회. 실패 · 중단이면 `RUN_NOT_VIEWABLE` |
| `more_candidates_for_project` · `select_announcement_for_project` · `start_writing_for_project` · `decide_for_project` | 3 · 5 · 6 · 8 · 9 | 아래 run_id 명령과 같음. 공고 다시 고르기 · 추가 조회는 자격 통과 뒤에도 작성 시작 전이면 받는다 |
| `request_rework_for_project(project_id, bundle)` | 6 · 8 · 9 | 재작성 묶음 요청(묶음마다 한 번). 같은 화면에서 2초 안의 요청은 재작성 한 번으로 합친다. 접수만 하고 돌아온다(`ReworkAccepted`) |
| `rework_result(project_id)` | 9 | 마지막 재작성 한 건의 결과(진행중 · 완료 · 실패, 전후 점수 · 계획서 섹션 · 파일 경로) |
| `abort_project(project_id)` | — | 대기 요청 취소 · 처리 중 요청 취소 요청 · 진행 중 실행 건 중단 → `AbortResult` |
| `delete_project_data(project_id)` | — | 완전 삭제 — 산출물 · 남은 입력 사본 삭제, 실행 로그 유지(마지막 활동 12개월 뒤 통계로 옮기고 지움). 워커가 단계를 도는 중이면 `BUSY` |
| `delete_account_data(account_id)` | — | 탈퇴(확장) — 프로젝트마다 중단 · 완전 삭제를 마친 뒤. 그 계정의 실행 건 · 산출물 · 기록 · 시작 요청을 통계 줄로 옮긴 뒤 모두 지움 → `AccountDeleteResult`. 처리 중인 일 · 점유 겹침 · 계정 잠금 대기 초과면 `BUSY` |
| `admin_executions(...)` · `admin_calls(execution_id)` | 관리자 | 여러 프로젝트의 실행 기록 · 호출 기록 (메타데이터 · 토큰만, 남은 기록만) |
| `admin_runs(...)` · `admin_score_history(project_id)` · `admin_summary()` · `admin_agent_tasks()` | 관리자 | 실행 건 목록 · 층별 점수 이력 · 운영 요약 · Agent별 Task (메타데이터 · 점수 · 개수만). 실행 건 목록 · 운영 요약은 최근 12개월 실행 건만 |

**워커 · 내부 · 테스트용**

| 함수 | 화면 | 하는 일 |
|---|---|---|
| `run_start_request(request_id, owner, lease_sec)` | 2 | (워커) 요청 점유 → 사전 단계 → 후보가 있으면 실행 건 생성과 요청 '완료'를 한 번에. 웹 조립에서는 `WEB_NOT_ALLOWED` |
| `start_run_for_project(account_id, project_id)` · `start_run(account_id, form, project_id=None)` | 2 | 동기 경로 — 시작 확인과 사전 단계를 차례로 부른다. 결과 `StartResult`. 웹 조립에서는 `WEB_NOT_ALLOWED` |
| `more_candidates(run_id)` | 3 | 공고 추가 조회 (1회, 최대 20건) |
| `select_announcement(run_id, announcement_id)` | 3 | 공고 선택 → 자격요건 확인 대기열 |
| `start_writing(run_id)` | 5 | 계획서 작성 대기열 |
| `decide(run_id, screen, action, selected_orders, confirmed)` | 6 · 8 · 9 | `"진행"` 또는 `"재작성"`. 화면 9에서 점수 미달 상태로 진행하면 먼저 확인 요청(`ConfirmationNeeded`)을 돌려줌. `"재작성"`은 산출물층 지시만 받아 묶음 요청으로 바꾼다(문서층 지시는 `INVALID_ORDER`) |
| `abort(run_id, confirmed)` | — | 확인을 받은 뒤 실행 중단 |
| `advance(run_id)` | — | 다음 대기 지점까지 실행 |
| `tick(now)` | — | 재개 시각이 된 실행을 모두 깨움 (테스트 · 시연용 — 워커는 `Engine.resume(run_id)`로 한 건씩) |
| `view(run_id)` | — | 화면 표시용 상태: 단계 · 진행 상태 · 화면 상태 · 복귀 화면 · 진행률(%) · 현재 작업 한 줄 · 안내 · 알림 |

- 현재 상태에서 받을 수 없는 명령이면 `CommandError`가 납니다 (예: 대기 지점이 아닐 때, 이미 쓴 재작성 기회를 고를 때).
- 실행 상태는 `step`(공고선택 … 결과물)과 `progress`(실행 · 재개대기 · 사용자대기 · 실패 · 완료 · 중단) 두 축으로 관리합니다. 화면 상태(진행 중 · 확인 필요 · 문제 발생 · 완료 · 중단됨)는 `progress`에서 계산합니다.
- **누가 `advance` · `tick`을 부를지:** 워커 프로세스가 공유 MySQL에서 할 일을 가져가(`SKIP LOCKED` + 점유) 처리합니다(`워커_구동_방식_제안.md`, 저장소 미포함, 확정 · 구현 완료). 웹은 명령 · 조회 함수만 부릅니다.
- **웹 테이블 쓰기**는 알림(`notifications`) · 실패 알림(`generation_failure_alerts`) · 검수 회수 문단(`proofread_logs`, 학습 동의 계정의 반려된 T-P2 시도만) INSERT 셋뿐이고, `SqlStore`가 단계 저장과 같은 트랜잭션으로 씁니다. 웹 `projects`(옛 요약 컬럼 `status` · `stage` · `progress_percent` · `notice_id` · `failure_reason` 포함)에는 쓰지 않습니다.
- **공고 선택 · 추가 조회:** 공고 선택은 고른 ID만 남기고 G-01을 넣습니다. 후보에 없으면 `INVALID_ANNOUNCEMENT`, 자격 불통과로 막힌 공고면 `ANNOUNCEMENT_BLOCKED`(화면 3 `blockedAnnouncementIds`)입니다. 선택 공고 · `announcement_id`는 G-01이 성공한 뒤 바뀌므로 웹은 `wait_project`로 기다린 뒤 화면 4를 엽니다. 추가 조회는 첫 조회와 겹친 공고를 `moreCandidates`에서 빼고 첫 조회 카드를 갱신하며(`contentChanged`), 실패하면 기회를 돌려줍니다.
- **재작성 요청 모으기:** 같은 실행 건 · 같은 화면에서 첫 요청부터 2초(잠정) 안에 들어온 묶음 요청은 재작성 한 번(합집합, 기준 문서 순서)으로 합칩니다. 그동안 워커는 그 실행 건을 가져가지 않습니다. 시간이 지난 뒤 · 재작성 중의 요청은 `INVALID_STATE`, 남은 기회가 없으면 `E-G2-LIMIT`입니다. 미달이 아닌 묶음도 받습니다(확장).
- 사용자용 결과(`view_project` · `outputs` · `rework_result` · 화면)에는 관리자용 실패 사유가 없습니다. 실패 사유는 관리자 함수(`admin_runs`)와 `generation_failure_alerts`에만 있습니다.
- **돌려주는 시각**은 모두 시간대 있는 UTC입니다(`.dump()` JSON은 `…Z`). 한국 시각으로 보이는 일은 웹이 합니다. 웹이 넘기는 시간대 없는 시각(`admin_executions`의 `since` · `until`)은 UTC로 봅니다.

---

## 10. 설정값

`orchestrator/settings.py`의 `Settings`에 기본값이 있습니다. 실행을 시작할 때 전체를 실행 건에 복사(`settings_snapshot`)해 끝까지 같은 값을 씁니다. 도중에 관리자가 설정을 바꿔도 진행 중인 실행에는 영향이 없습니다.

| 설정 | 기본값 | 비고 |
|---|---|---|
| 재시도 횟수 · 간격 | 5회 · 2초 | 간격은 잠정 |
| 재개 | 첫 간격 15분, 2배씩, 최대 5번, 총 12시간 | |
| 재수행 횟수 | 2회 | |
| 재작성 횟수 | 묶음마다 1회 | 세 화면(6 · 8 · 9)이 같은 횟수를 씀 |
| 기준 점수 · 층별 배점 | 80점 · 문서층 70 · 산출물층 30 | |
| 검수 동시 처리 수 | 4 | 잠정 |
| 검수 실패 비율 기준 | 30% (모든 문장을 본 뒤 판단) | 잠정 |
| Task별 제한 시간 (호출 한 번) | 대부분 120초, `T-W1` · `T-B1` · `T-B2` 300초, `T-C2` · `G-01` 30초(공고 서버 호출 한 건마다), `T-P2` 60초, `지시문 다시 쓰기` 120초, 이미지 `T-B2.image` 120초 | 잠정 |
| Task별 모델 · 호출처 · 온도 · 추론 강도 · 이미지 (`Settings.tasks`) | 조율 Task · `지시문 다시 쓰기`는 `openai` · `gpt-6-luna` · 추론 강도 low · 온도 없음(사용자 지정). T-B1 · T-B2 · T-V2는 `gpt-6-luna` · 추론 강도 · 온도 보내지 않음, T-B2 이미지 `gpt-image-2.5-flare` · medium · 1024x1536(구현 · 검증-2 담당 요청). 나머지 '미정', 검수 `gpu-server` 등. 규칙 단계 · 합치기는 항목 없음 | 잠정 |

실행 건 설정이 아닌 명령 창구 값(`flow/service.py`)도 있습니다: 재작성 요청을 모으는 시간 2초, 재작성 요청의 점유 재시도 최대 5초, `wait_project` 기본 제한 시간 60초(0.5초마다 다시 읽음) — 모두 잠정이며 관리자 설정으로 바꾸지 않습니다. 12개월 처리 값(한 번에 100건 · 다시 시작 간격 24시간 · 확인 주기 10분 · 작업 점유 = 워커 점유 120초)과 계정 잠금 대기 10초도 같은 성격의 잠정 값입니다.

잠정 항목 목록은 `settings.py`의 `PROVISIONAL`에 있습니다(워커 수치 · 명령 창구 값, 공고 연결의 추천 이유 문장 틀 · 모집 상태 모름 처리 · 선택 공고 자리 표시 양식 · X-C2-GONE 문구 · 공고 서버 호출 하나씩, 작업 분해의 양식 묶음 표 · 참조 조각 대응표, `retention.*` · `store.accountLockTimeoutSec` 포함). 다른 값으로 돌려 보려면 `build_stub_app(settings=Settings(...))`로 넘깁니다.

**관리자 설정 입력:** 워커 · 웹 조립에서는 `DbSettingsProvider`가 웹 `verification_policies` 첫 행을 기본값 위에 덮어씁니다 — `doc_weight` → 문서층 배점, `code_weight + plan_weight` → 산출물층 배점, `pass_threshold` → 기준 점수, `rerun_cap` → 재수행 횟수, `rework_cap` → 재작성 횟수, `token_retry_cap` → 검수 재수행 횟수, `deviation_cap` → 확장 필드에 담아만 둠(잠정). 나머지는 코드 기본값입니다(웹팀 답 대기).

---

## 11. 테스트

```bash
python -m pytest                              # 전체
python -m pytest tests/test_rework.py         # 파일 하나
python -m pytest -k onepage                   # 이름에 onepage가 들어간 테스트만
```

| 파일 | 건수 | 확인하는 것 |
|---|---|---|
| `test_flow_basic.py` | 26 | 20단계 실행 순서, 원페이지 분기, 대기 지점 상태, 자격요건 불통과 후 재선택, 추가 조회, 사전 단계 오류, 동시 실행 · 프로필 차단, 중단 |
| `test_rework.py` | 51 | 화면 6 · 8 · 9 재작성 경로, 묶음 이름 요청 · 같은 화면 요청 모으기(합집합 · 중복 · 늦은 요청 · 진행 중 요청 · BUSY · 모으는 중 중단), 이름 · 층 · 상태 규칙, 미달 아닌 묶음, 묶음 기회, 점수 하락 시 되돌리기, 재작성 실패 시 모은 묶음 기회 반환 |
| `test_redo_resume.py` | 16 | 재수행 횟수 · 확정 동작, 재개 후 성공, 재개 상한 초과 실패, 영구 오류, `featureList` 불변 |
| `test_partial_resume.py` | 15 | 재개 때 받은 결과 이어 쓰기(엔진 장치) — 저장 조건, 재개 때 입력 · 입력 참조, 비거나 연결 없으면 저장 안 함, 영구 오류 · 상한 · 재개 불가 · 흐름에 넘김, 내용이 기록에 없음, 옛 진행 위치 읽기 |
| `test_tools.py` | 6 | 호출 단위 재시도, 오류 분류, 형식 오류, 스레드 안전, 로그에 내용 없음 |
| `test_proofread_trace.py` | 26 | `T-P2` 문장 병렬 처리 · 재수행, 시도별 기록, 반려 시도 `proofread_logs` 행(학습 동의 · 재개 때 중복 없음 · 위반 종류), 옛 구조면 건너뜀, 추적 기록 원칙, 설정값 고정 |
| `test_intake.py` | 22 | 웹 DB 행 → PreInput 변환, 목록 입력 키 이름 변환 · 증빙 표기 · 모르는 키 대체, 확장 필드 · 수익모델 여러 건 · 팀원 없음, 필수 항목 결측 목록, SQL 공급처(SQLite로 웹 스키마 흉내) |
| `test_tc1.py` | 20 | T-C1 아이템 사양 · 회사 정보(확장 필드 포함) 그대로 옮김, 조율 모델 · 추론 강도, 카테고리 기본값 · 추적 기록, 형식 오류 재시도, DB에서 읽어 시작, 참조 자료 발췌 확인 |
| `test_openai_provider.py` | 7 | OpenAI 요청 모양(추론 강도 · 온도 생략 포함) · 오류 변환 (가짜 클라이언트, 네트워크 없음) |
| `test_env.py` | 6 | `.env` 읽기(따옴표 · 주석 · BOM · 빈 값), 환경 변수 우선, API 키를 `.env`에서 읽기 |
| `test_store_contract.py` | 102 | 저장소 계약 — 메모리 · SQLite · MySQL이 같은 동작인지 (점유, 동시 실행 제한, 모으는 중 건너뛰기, 포인터 · 키 순서, 기록 왕복, 반려 시도 조건, 시작 요청 · 끝나면 입력 사본 비우기, 관리자 · 여러 실행 건 조회, 계정 잠금 대기 초과, 기록 옮기기 · 12개월 대상 · 작업 점유) |
| `test_store_sql.py` | 11 | DDL 파일 = 생성 결과, 설정 입력(`verification_policies`), 웹 테이블 구조 확인, `proofread_logs` 옛 구조 · 쓰기 오류, 학습 동의 확인 |
| `test_start_request.py` | 26 | 시작 요청 → 워커 실행, 필수 항목 · 프로필 · 동시 실행, 실패 후 재시도, 취소, 점유 이어받기, 진행 중 작업 확인, 끝난 요청의 입력 사본 비우기 |
| `test_clock.py` | 21 | 시각 — 도움 함수, 시간대 없는 값은 UTC, DB 칸은 시간대 없는 UTC, 웹 표 시각 · `proofread_logs.created_at`, 웹에 돌려주는 시각 전부 UTC, 한국 날짜(G-01 기준일 · 마감 안내 · 스텁), 워커 로그 UTC |
| `test_log_stats.py` | 16 | 통계 줄 계산 — 칸 · 고정 키 · 한국 달 · 카테고리 순서 · 층별 점수 · 최종 점수 · Task별 개수, 식별자 · 자유 글 없음, 시작 요청 묶기 |
| `test_retention.py` | 28 | 12개월 처리 — 기준 시각 · 경계, 진행 중 · 점유 중 건너뜀, 살아 있는 실행 건 · 두 번째 옮김 · 완전 삭제된 실행 건, 시작 요청, 작업 점유 · 종료 신호 · 만료 이어받기, 한 건 실패, 로그 · 요약에 식별자 없음 |
| `test_retention_preserve.py` | 12 | 기록을 지운 뒤에도 카테고리 · 화면 10 · 재작성 결과 · 시도 번호가 같음 |
| `test_account_delete.py` | 21 | 탈퇴 — 통계로 옮기고 모두 지움, 대기 요청 취소, `BUSY`(처리중 요청 · 단계 진행 · 점유 겹침 · 잠금 대기 초과), 다시 부르면 0, 잠금 중 새 시작 요청이 끼어들지 않음, 웹 조립에서 부름 |
| `test_tc3.py` | 55 | 실제 T-C3 — 지시 대상마다 안내 호출(7 · 6번, 동시에 · 결과는 실행 순서), 실패 순서(코드 오류 · 영구 오류 · 일시), 재개 때 빠진 것만 · 누적, 보내는 칸 제한 · 시 · 도만, 참조 조각은 지시문에만, 데이터 격리, LLM 전 확인(자격 · 이력 · E-C3-FORM), 형식 오류 재시도, 재시도 소진 → 재개 |
| `test_task_plan.py` | 50 | 양식 묶음 표(불변식 · 배점 합 70), Task 목록 · 틀 · 맥락 · 확장 출력, 참조 조각 배정, 스텁 T-C3, 뒷 단계가 T-C3 출력을 읽음, `outputs.evaluationItems` |
| `test_instruction.py` | 18 | 지시문 세 부분 나누기 · 안내만 바꾸기(틀 · 참조 바이트 보존) · 안내 정리 · 덧붙임 블록 형식 |
| `test_rewrite.py` | 39 | 재작성 · 재수행 지시문 다시 쓰기 — 언제 부르나, 문서층 Task마다, 반영 실행은 덧붙이기만, 재작성 중 재수행에 재작성 지시 유지, 가리기, 재개 때 재사용, 호출 기록 위치, 되돌리기 제외 |
| `test_worker.py` | 33 | T-C3 · 다시 쓰기 호출만 실제 호출처로, 워커 2개 중복 없음(SQLite · MySQL), 점유 만료 이어받기, 단계 사이 중단, 종료 신호, 하트비트, 재개, 모으는 중 가져가지 않음, 12개월 처리(확인 주기 · 개수만 로그 · 종료 신호 · 작업 점유 하트비트 · 웹 조립은 안 돎), 조립(웹 조립 사전 단계 `WEB_NOT_ALLOWED`, 공고 서버 주소 있음 → 실제 T-C2 · G-01 · 없음 · 빈 값 → 스텁, 주소 형식 오류, 테스트가 실제 주소를 보지 않음) |
| `test_announcement_gate.py` | 42 | 공고 선택은 ID만 · G-01이 선택 공고 · 자격 결과 · 업력을 한 번에 저장, 확인 필요(화면 4만 안내), G-01 실패 시 고르기 전 화면 · X-C2-GONE · X-C2-FAIL, 공고 없음 다시 고르기, 막힌 공고 · `ANNOUNCEMENT_BLOCKED`, 마감 안내, 빈 마감일 · 금액으로 끝까지 |
| `test_more_candidates.py` | 46 | 추가 조회 겹침 빼기 · 첫 조회 카드 갱신 · 내용 바뀜 참 · 거짓, 막힌 공고 풀기, 추가 조회 실패 · 수집 상태 비정상 → 기회 반환 · 화면 3 값 유지, 마감 임박순 안내 문구 |
| `test_step_rescue.py` | 14 | 엔진의 실패를 흐름에 넘기는 장치(정한 구간의 모든 오류, 다른 구간은 그대로, 흐름이 옮기지 않으면 오류) |
| `test_gate_stubs.py` | 20 | 스텁 공고 · 스텁 G-01 판정 규칙 · 업력 셈(사사오입) · 스텁 T-C2 카드 · 상황 조절 |
| `test_notice_client.py` | 40 | 공고 서버 HTTP 클라이언트 (127.0.0.1 임시 서버) — 오류 변환, 공고 없음과 코드 없는 404, 공고 ID 인코딩, 예외에 주소 · 본문 없음, 호출 하나씩 |
| `test_notice_tasks.py` | 225 | 실제 T-C2 · G-01 (가짜 전송) — 보내는 칸 · 시 · 도 17개 바꾸기, 카드 · 상세 · 판정 변환, 약속 밖 응답 거절, 받은 순서 그대로, 공고 없음 |
| `test_reads.py` | 22 | 진행 상태 · 화면 3 ~ 11 · 관리자 실행 기록 조회 · project_id 명령 |
| `test_web_functions.py` | 43 | 진행 상태 새 필드 · 여러 건 · 기다리기, 사용자용 결과에 실패 사유 없음, 지금까지 결과, 재작성 결과, 실패 · 중단 뒤 볼 수 없음, 자격 통과 뒤 다시 고르기, 화면 10 시도 기록 |
| `test_admin_reads.py` | 12 | 관리자 실행 건 목록 · 점수 이력 · 운영 요약 · Agent별 Task, 실행 건 목록 · 운영 요약은 최근 12개월만 |
| `test_summary.py` | 11 | 단계를 저장해도 웹 `projects` 행이 바뀌지 않음, 실패 알림 · 실패 사유 (SQLite · MySQL) |
| `test_tokens.py` | 10 | 토큰 시도별 · 호출 · 실행 합계, OpenAI 매핑, 관리자 조회 |
| `test_abort_delete.py` | 14 | project_id 중단 · 완전 삭제 |
| `test_task_settings.py` | 12 | Task별 설정 — 키 집합 = 등록부 task 단계 + `지시문 다시 쓰기`, 기본값 · 잠정, 새 사본에 `agents` 없음, 옛 사본(`agents`만) 읽기 · 이어 돌기, Task마다 자기 모델 · 온도 규칙, 다시 쓰기 자기 항목, M-4 `model_version`, 워커 나누기 |
| `test_image.py` | 30 | `tools.image` 재시도 · 오류 종류 · 편집 / 새로 그리기 · 크기 · 품질 기본값 · 설정 없는 Task 즉시 실패 · 토큰 · 스레드 · 내용 없음, 실행 기록 이미지 토큰 따로 · 재개 때 이어 더함, 관리자 조회, 조립 · 이미지 호출처 나누기, OpenAI 이미지 어댑터(가짜 클라이언트) |
| `test_artifact_layer.py` | 66 | 산출물층 검증 반영 — 확장 필드, 재작성 사유(통과 필수 조건 · 결함 출처 · 누락 · 부분 인정 · 보류), 스텁 T-V2 1.4판, `planDoc` 입력, 보류 · 진단 사건, G-04 자체 검사, 원페이지 계획서 반영 · 되돌리기, 이전 원문, T-B2 이미지 실패 예외 · '이미지대체' |
| `test_worker_log.py` | 31 | 워커 운영 로그 — 단계 · 실행 건 줄과 키 순서, 단계끝은 저장 뒤, 웹 루트 로거로 안 올라감, 계정 번호 · 내용 없음, 웹 조립 출력 없음, 날짜 · 순번 파일 · 날짜 바뀜 · 이어 쓰기, 자동 삭제, 폴더 잠금, 쓰기 실패해도 계속 |
| `test_mysql_integration.py` | 7 | 실제 웹 스키마 위 MySQL 8 흐름 · 동시 재작성 요청 합치기 · 반려 시도 행 · 삭제 뒤 로그 보존 · 웹 → 워커 조립 · 탈퇴 중 계정 잠금 유지 · 웹 스키마 위치 찾기(DB 없이) |

흐름 테스트(`clock` 고정 장치를 쓰는 테스트)는 **메모리 저장소와 `SqlStore`(SQLite 임시 파일 DB)로 한 번씩** 돕니다(`conftest.py`의 `store_backend`). 위 건수는 이렇게 늘어난 수입니다.

### 상황을 흉내 내는 법

스텁은 `StubScenario`와 `FakeLLM`으로 원하는 상황을 만들 수 있습니다. 새 테스트를 쓸 때 참고하세요. 공통 도움 함수는 `tests/conftest.py`에 있습니다.

```python
from datetime import datetime, timedelta, timezone
from sbrain.agents.stubs import StubScenario
from sbrain.bootstrap import build_stub_app

app = build_stub_app(StubScenario(category="원페이지"))   # 원페이지 카테고리 (T-B1 생략)
app.llm.plan("T-S1", ["timeout"] * 6)   # T-S1의 LLM 호출이 6번(첫 시도 + 재시도 5회) 모두 시간 초과
# … 작성 시작 후 advance → view().progress == "재개대기"
app.orchestrator.tick(datetime.now(timezone.utc) + timedelta(minutes=15))   # 재개 시각에 깨우면 이어서 진행 (시각은 UTC)
```

| 조절 수단 | 예 |
|---|---|
| `StubScenario(category=...)` | `"원페이지"` · `"웹개발"` · `"AI_API"` |
| `StubScenario(doc_scores=[...], art_scores=[...])` | 채점 결과를 차례대로 지정 (재작성 후 점수 변화 등) |
| `StubScenario(check_fail_times={"T-W1": 2})` | 특정 Task의 검사 불통과 횟수 |
| `StubScenario(gate_fail_ids={"A01"})` | 특정 공고의 자격요건 불통과 (그 실행 건에서 막힌 공고가 됨) |
| `StubScenario(raise_in={"M-1"})` | 특정 단계에서 코드 오류 발생 |
| `StubScenario(unknown_ids=…, closed_ids=…, no_deadline_ids=…, no_amount_ids=…, not_found_ids=…)` | 공고별 확인 필요 · 모집 상태 '마감' · 마감일 없음 · 금액 없음 · 공고 없음(테스트 중에 바꾸면 다음 G-01부터 반영) |
| `StubScenario(exhaust_in={"G-01"})` | T-C2 · G-01의 외부 호출이 재시도를 다 씀 |
| `StubScenario(collection_status="지연", deadline_fallback=True)` | 수집 상태 비정상(후보 0건) · 대체 경로 '마감임박순'(적합도 0) |
| `StubScenario(more_ids=[…], more_changes={"A01": {"정보"}}, more_error="코드오류", more_collection_status="지연")` | 추가 조회에서만: 돌려줄 공고 ID(겹침), 카드 내용 바꾸기(정보 · 버전 · 적합도 · 가산점), 오류(코드오류 · 재시도소진), 수집 상태 |
| `StubScenario(null_bonus_ids=…, no_version_ids=…)` | 가산점을 계산하지 못한 카드 · 내용 버전이 없는 카드 |
| `app.llm.plan(task_id, [...])` | 호출 결과를 차례대로 지정: `"ok"` · `"timeout"` · `"rate_limit"`(429) · `"bad_request"`(400) · `"auth"`(401) · `"bad_json"` |

`build_stub_app()`은 테스트 · 시연용이라 재시도 간격만큼 실제로 기다리지 않습니다.

---

## 12. 아직 하지 않은 것 · 확인이 필요한 것

**아직 구현하지 않은 것**

- 실제 Agent 구현 (조율 T-C1 · T-C3 말고는 스텁)
- 신청자 유형별 양식 · 평가항목 · 채점 기준표의 실제 값(담당자 회신 대기 — 받으면 `agents/form_defaults.py`의 표만 바꿈)
- R-8 첨부 문서 텍스트 추출과 웹 DB 첨부(`project_attachments`) 읽기
- 자체 GPU 서버 호출처 어댑터 (OpenAI는 있음)
- 공고 서버 실제 연결 켜기 — 연결 코드는 끝났고, 공고팀 시험 서버로 네 API를 확인했다(2026-10-07, 가짜 신청 정보로 23개 확인 모두 통과 — 준비 확인 2개 포함). 운영 서버 위치 · 주소 · 인증이 정해지고 워커 IP를 공고팀에 알린 뒤 켠다. 그 전까지 스텁 모드
- 가산점 켜기 — 공고팀 가산점이 시험 단계라 스위치(`orchestrator/settings.py` `BONUS_ENABLED`)를 꺼 두었다. 웹 카드의 가산점은 늘 비어 있다. 공고팀이 정리를 알리면 켠다. 고른 뒤 바뀐 모집 상태 반영(지금은 알 수 없음)
- 공유 DB에 Orchestrator 테이블 적용 — `sql/orchestrator_schema.sql`(표 12개)로 담당자가 직접
- 웹 표(실패 알림 · 알림)의 12개월 처리 — 웹팀 몫

**공고팀과 맞출 것** — 운영 서버 위치 · 주소, 동시 호출 안전성(그 전까지 워커 1대), 인증 방식(지금은 없음), 가산점 정리, 워커 IP 전달. 네 API 제공 · 공고 없음이 생기는 경우 · 가산점 입력(생년월일은 아직 보내지 않음)은 2026-10-06 답변으로 정리됐다. 요청서는 `docs/공고서버_API요청_공고팀전달.md`

**웹팀과 맞출 것** — 화면별 모양(초안), 실패 알림 범위, 완전 삭제 · 탈퇴 중 `BUSY` 처리, 오래 걸리는 웹 요청 제한 시간, 화면의 시각 표시(UTC → 한국 시각). 완전 삭제 · 탈퇴 때 `proofread_logs`는 학습에 반영된 행(`trained`)만 남기고 프로젝트 연결을 끊기로 정했다(웹팀 회신 2026-10-05, 웹이 구현). 웹팀이 할 스키마 · 프론트 변경은 `docs/웹연동_변경사항_웹팀전달.md`, 함수 약속은 `docs/Orchestrator_웹연동_함수명세.md`

**타 팀과 합의가 필요한 것** — 자세한 내용은 `docs/Agent_연동_규격_초안.md` 10절

- `tools` 인터페이스(`llm` · `search`)와 "Task 안의 호출은 반드시 `tools`로" 규칙 (전 Agent 팀)
- `G-02a` · `G-02b` 입력 확장(`cycleInfo` 등), `T-P2` 재수행 루프 소유, 양식 · 평가항목 · 채점 기준표 · 서술 형식을 작업 분해 결과에서 받는 것, 지시문 세 부분 구성과 재작성 · 재수행 때 안내 다시 쓰기 등
- `T-P2` 시도별 기록과 검수 회수 문단의 회수 단위(검수), 사용자 재작성 지시의 묶음 이름 · 빈 보완 지시(작성 · 구현)

**기준 문서에 값이나 규칙이 없어 임시로 정한 것** — 목록은 `docs/Orchestrator_구조와_흐름.md` 11절

**T-C1 · 웹 DB 연동** — 웹팀 확인(단위 · 첫 창업 여부 · 팀원 없음)은 끝났다. 잠정값과 남은 사항은 `docs/T-C1_요구사항해석_구현.md` 8 · 9절

**기준 문서(기능정의서 · 기획서)에 반영할 변경** — 수익모델 여러 건, 확장 필드, 팀원 없음, 첫 창업 여부 미수집 등은 `기준문서_개정필요사항_T-C1_사전정보입력.md`(저장소 미포함). 미달이 아닌 묶음 재작성, 재작성 요청 모으기, 문서층 임시 묶음, 자격 통과 뒤 다시 고르기, T-P2 시도별 기록 · 검수 회수 단위는 `기준문서_개정필요사항_워커_웹연동.md`(저장소 미포함). 공고 서버 판정 · 비울 수 있는 날짜 · 금액 · 확인 필요 · 막힌 공고 · X-C2-GONE 등 공고 연결로 달라진 것은 `기준문서_개정필요사항_공고연동.md`(저장소 미포함). 작업 분해 · 지시문 다시 쓰기로 달라진 것은 `기준문서_개정필요사항_T-C3_작업분해.md`(저장소 미포함)

---

## 13. 더 읽을 문서

| 문서 | 내용 | 대상 |
|---|---|---|
| `docs/Orchestrator_구조와_흐름.md` | 실행 흐름도, 재작성 경로, 실행 상태, 저장 · 추적 기록, 잠정값 · 해석 목록 | Orchestrator · 조율 담당, 웹팀 |
| `docs/Agent_연동_규격_초안.md` | Task 함수 · `tools` 규격, Task별 입출력 · 실행 설정 표, 확장 필드, 합의 필요 사항 | 각 Agent 구현 담당 |
| `docs/T-C1_요구사항해석_구현.md` | 웹 DB → PreInput 매핑 · 확장 필드, 필수 항목 재확인, T-C1 처리, 조율 모델 · OpenAI 어댑터, 잠정 · 확인 필요 목록 | 조율 담당, 웹팀 |
| `기준문서_개정필요사항_T-C1_사전정보입력.md` (저장소 미포함) | 기능정의서 · 기획서에 반영할 변경 목록 (T-C1 · 사전 정보 입력) | 기준 문서 관리자 |
| `docs/T-C3_작업분해_구현.md` | T-C3 범위 · 흐름 · 양식 고르기 · 지시문 구성 · LLM 입력 · 다시 쓰기 · 실패 처리 · 잠정 · 확장 목록 · 실제 OpenAI 확인 방법 | 조율 담당 |
| `기준문서_개정필요사항_T-C3_작업분해.md` (저장소 미포함) | 기능정의서에 반영할 변경 목록 (작업 분해 · 재작성 · 재수행 지시문) | 기준 문서 관리자 |
| `기준문서_개정필요사항_워커_웹연동.md` (저장소 미포함) | 기능정의서 · 기획서에 반영할 변경 목록 (재작성 요청 · 문서층 임시 묶음 · 자격 통과 뒤 다시 고르기 · T-P2 시도 기록 · 검수 회수 문단) | 기준 문서 관리자, 검수 팀 |
| `docs/Orchestrator_웹연동_함수명세.md` | 웹이 부르는 함수 전부 — 인자 · 돌려주는 모양 · 오류 코드 · 부르는 시점, 웹 프로세스 조립, 계정 삭제 순서 | 웹팀 |
| `docs/공고서버_API요청_공고팀전달.md` | 공고 서버 네 API 약속 · 판정 규칙 · 공고 없음 규약 · 내용 버전 · 가산점 요청, 운영 조건 질문, 공고팀 합의 요청 ①~⑫에 대한 답 (2026-10-03) | 공고팀 |
| `docs/공고연동_변경사항_웹팀전달.md` | 공고 연결로 바뀐 화면 3 · 4 필드, 내용 바뀜, 막힌 공고 · `ANNOUNCEMENT_BLOCKED`, X-C2-GONE, 추가 조회 실패 시 기회 반환, 마감 안내 (2026-10-03) | 웹팀 |
| `기준문서_개정필요사항_공고연동.md` (저장소 미포함) | 기능정의서에 반영할 변경 목록 (공고 서버 판정 · 비울 수 있는 날짜 · 금액 · 확장 필드 · 안내 코드) | 기준 문서 관리자 |
| `워커_구동_방식_제안.md` (저장소 미포함) | 누가 언제 Orchestrator를 돌릴지 — 워커 방식 (웹팀 합의로 확정, 구현 완료) | 사용자, 웹팀 |
| `docs/웹연동_변경사항_웹팀전달.md` | 웹 백엔드가 더미 파이프라인 대신 Orchestrator로 돌게 하는 변경 — 엔드포인트별 대응, 값 대응표, 필수 웹 스키마 · 프론트 변경 (2026-10-02) | 웹팀 |
| `웹스키마_교체목록_웹팀전달.md` (저장소 미포함) | 웹 스키마의 오케스트레이션 관련 테이블 · 컬럼 교체 · 삭제 · 유지 목록 (기준 문서 근거 포함, 2026-10-02 바뀐 분류는 위 문서) | 웹팀 |
| `작업지시_조율코드반영_워커_웹연동.md` (저장소 미포함) | 워커 · MySQL 저장 · 조회 함수 · 토큰 · 중단 구현 지시 (단계 S0~S9, S8까지 반영) | 구현 세션 |
| `작업지시_기준문서개정_T-C1_웹연동.md` (저장소 미포함) | 기능정의서 · 기획서 개정 지시 (T-C1 사전 정보 입력 · 웹 연동) | 기준 문서 관리 세션 |
| S-Brain Agent 기능정의서 v1.9 (저장소 미포함) | 구현 기준 문서 (Source of Truth) | 전원 |
| 프로젝트 기획서 v1.10 (저장소 미포함) | 서비스 기획 (보조 참고) | 전원 |
