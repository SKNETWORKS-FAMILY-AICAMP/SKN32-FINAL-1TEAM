# 다음 세션 인수인계 — 공고 서버 API(조율 에이전트 창구) 01~04 마무리 (2026-10-06)

기준 시점: 2026-10-06 오후 작업 종료 (Claude)
작업 범위: `data-collection/`만
이 문서가 **최신 진입점**이다. 이전 인계서는 [archive/NEXT_SESSION_HANDOFF_20260929.md](NEXT_SESSION_HANDOFF_20260929.md)다.

## 1. 새 세션이 가장 먼저 할 것

1. 이 문서를 끝까지 읽는다. 이어서 [STATUS](../STATUS.md) 맨 위 두 항목과 [notice_api 진행표](../notice_api/README.md)를 읽는다.
2. 사용자는 이근준이다.
   - **커밋·push는 사용자가 직접 한다.** 묻지 않으면 커밋 이야기도 꺼내지 않는다.
   - 모든 답변·중간 안내를 **한국어**로, 비유를 먼저 들고 쉬운 말로 쓴다.
   - 사용자 터미널은 PowerShell 5.1이다. 알려 줄 명령은 PowerShell 기준으로 쓴다.
3. 작업 브랜치는 `feature/SB-189-data-collection`이다. 10/6 변경은 모두 **미커밋**이다(일부는 사용자가 스테이징해 둔 상태 — 건드리지 않는다).

## 2. 무엇을 하고 있었나 (한 줄)

조율 담당(4nchez)의 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`, 10/3)대로 **공고 서버(`search/app.py`)에 HTTP 창구 4개를 열고 가산점을 만들었다.** 조율 쪽은 우리 코드를 import하지 않고 이 HTTP API를 부른다(9/29 직접 import 결정은 10/3에 바뀜).

한눈에 보는 페이지(비공개, 사용자 계정):
- 작업 흐름: https://claude.ai/artifact/MP9WGh7sM3P2jZGS6tSDe8
- 가산점 판정 방식(실제 계산 값): https://claude.ai/artifact/XdbvF8DhvHBH9LEtv71eJm

## 3. 진행 상황

| 작업 | 상태 | 기록 |
|---|---|---|
| 01 수집 상태 창구·추천 결과 키(`content_version` cv2·`bonus_score`·`bonus_items`) | ✅ | [01](../notice_api/01_status_match/README.md) |
| 02 공고 상세·자격 판정(판정 코드 `search/eligibility.py` 한 곳) | ✅ | [02](../notice_api/02_detail_eligibility/README.md) |
| 03 가산점(추출기 v4·공용 DB `notice_bonus`·계산·순위 세기 0·매일 배치 14단계 코드) | ✅ 구현 / Codex 재검수 지적 **보류** | [03](../notice_api/03_bonus/README.md) |
| Codex 검수 → 13건 반영 → 재검수 "추가 수정 후 재검수 필요"(P1 1·P2 6·P3 2) | 보류(사용자 결정) | [요청](../notice_api/CODEX_REVIEW_REQUEST_20261006.md) · [결과](../notice_api/CODEX_REVIEW_20261006.md) · [응답](../notice_api/CODEX_REVIEW_RESPONSE_20261006.md) · [재검수](../notice_api/CODEX_REVIEW_RECHECK_20261006.md) |
| 04 계약 시험 — 조율 쪽 실제 코드로 8000 HTTP 호출 | ✅ 16/16, 모든 공고 G-01 2,765건 형식 오류 0 | [04](../notice_api/04_contract_test/README.md) |
| **05 답변서**(4nchez에게 보낼 문서) | **다음 할 일** | 아래 4절 |

## 4. 다음 할 일

### 4-1. 05 답변서 (사용자가 새 세션에서 진행 예정)

`docs/notice_api/05_reply/`에 쓴다. 담을 것:
- 요청서 9절 질문 11개 답. 코드로 이미 확인된 답: ② `fallback_mode` 값 3개 그대로(`임베딩단독`·`BM25단독`·`마감임박순`), ③ 지연 = 마지막 저장 24시간 초과·실패 = 저장 기록 없음/최근 배치 실패/출처 부분 실패/기업마당 스냅샷 재사용(`search/collection_status.py`) + **서버가 올린 공고가 24시간 넘거나 저장 시각을 모르면 지연**, ⑪ 정상 결과 `fit_score`는 0이 되지 않음·마감임박순은 null.
- ④ 내용 버전 구성: 공고 원문 칸 + **지금 달린** 첨부 파일 바이트 SHA-256(`cv2-`), 수집 시각·LLM 값 제외.
- ⑤⑥ 가산점: **시험 단계** — 순위 반영 세기 0(순서 안 바뀜), 일부 공고에서 점수가 틀릴 수 있음(Codex 재검수 지적), 판정에 쓰는 입력은 성별·인증·시·도/시·군·구·첫 창업 여부·생년월일(지금 안 보냄 → 청년 가점 모름).
- 계약 문구(P3): `certifications=[]`는 **"확인된 없음"**, `bonus_items.points`는 **합계 한도 적용 뒤 반영분**.
- 한계: **K-Startup은 가산점 늘 null**(첨부 공고문 경로 `/afile/`가 robots.txt 자동 수집 금지, 공공데이터포털 API 4종에 첨부 칸 없음·우대 사항 칸 비어 있음), **사업자 신청자는 "지원대상 유형"이 늘 확인 필요**(개인·법인 자동 판정 안 함, 9/28 결정), `support_amount_text`는 null, 지원 금액은 849건(31%)만.
- 운영 질문 답(8: 동시 호출·재시작·응답 시간, 9: 인증·요청 본문 기록)은 미정 — 배포 위치를 정하면서 답한다. 04에서 잰 응답 시간: 추천 약 0.5초(첫 호출 2.7초), 상세+판정 건당 23ms.
- **실제 연결을 켜기 전 조건**: 가산점 정리(고치거나 모두 null), 공고 서버 내부망 배포, 요청서 8절 확인 목록.

### 4-2. 10/7 09:00 배치 뒤 (몇 분)

```powershell
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
.\.venv\Scripts\python.exe -X utf8 -m search.content_version --compare data/notice_api/content_version_20261006_cv2.json
```
- 새 공고가 들어왔는지(10/4~10/6은 연휴라 0건이었다 — 장애 아님, STATUS 10/6 점검 참고).
- 지문 비교 `by_field`에 날마다 바뀌는 칸이 몰려 있으면 그 칸을 빼고 접두어를 `cv3`로 올린다.

### 4-3. 사용자 결정 대기

- 서버 `sbrain-web` 매일 배치 코드 다시 복사(10/2 복사본이라 14단계 가점 추출이 없다 → 새·바뀐 공고의 가산점은 null이 된다).
- 공고 서버 운영 위치(요청서: AWS 내부망).
- Codex 재검수 지적 처리 방식: 보수적으로 줄이기(확실한 경우만 점수, 저장된 AI 결과 재검사로 비용 거의 0) / 정밀화(재추출 약 $2) / 가산점 전부 null.

## 5. 알아 둘 사실

- **공용 DB 변경(10/6, 사용자 승인):** `notice_bonus` 표 생성(마이그레이션 007), `content_version` 칸 추가(008), v4 2,078행 적재. 기존 공고 표는 바꾸지 않았다. 마이그레이션 SQL을 자동으로 적용하는 코드는 없다.
- **AI 비용(추정):** 가점 추출 합계 약 $3.12(표본 $0.28 + v3 전량 $1.05 + v4 전량 $1.79).
- **이 PC 8000 서버:** 10/6 13:07 KST에 v4 코드로 켜 두었다(Claude가 켬, 사용자 확인용). 끄기 전 사용자에게 묻는다. 이 PC 벡터 색인은 10/2 기준(2,714건)이라 51건은 의미 검색에서 빠진다.
- **계약 시험 다시 돌리기:** 조율 브랜치 코드를 작업 폴더 밖 임시 폴더에 `git archive origin/feature/SB-87-init-supervisor-integration agent-orchestration/sbrain | tar -x -C <임시 폴더>`로 풀고 `python -m experiments.notice_api_contract --sbrain <임시 폴더>\agent-orchestration --all`. 조율 쪽 코드는 우리 `.venv`로 불러진다(pydantic 2.13.5 같음).
- 데이터 쪽은 10/2부터 "최소 작업"이다. 팀원·사용자 요청이나 장애가 아니면 새 과제를 먼저 꺼내지 않는다(이번 작업은 팀원 요청).

## 6. 확인·실행 방법 (`data-collection/`에서)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests          # 10/6 기준 758 통과 · 건너뜀 16
.\.venv\Scripts\python.exe -X utf8 -m collect.extract_bonus --all --plan  # 가점 재추출 대상·예상 비용(부르지 않음)
```
- 서버: 저장소 루트 `.claude/launch.json`의 `search-service`(8000). 창구 시험 화면은 `http://localhost:8000/docs`.

## 7. 하지 말 것

- 사용자 요청 없이 DB 쓰기, EC2 배포·서버 코드 복사, AWS 설정 변경, Git commit·push, 8000 서버 끄기.
- K-Startup 첨부를 자동으로 내려받지 않는다(robots.txt `Disallow: /afile*/`).
- 조율 쪽 폴더(`agent-orchestration/`)는 읽기만 한다(4nchez 담당).
- 업종·지역을 정형 필터나 게이트에 넣지 않는다(순위 신호, 9/28 결정).
