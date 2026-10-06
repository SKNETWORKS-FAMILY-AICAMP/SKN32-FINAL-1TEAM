# 공고 서버 API — 조율 에이전트 요청 대응

조율 담당(4nchez)이 보낸 요청서대로 공고 서버(`search/app.py`)에 HTTP 창구를 연다.
이 폴더는 **작업별 기록장**이다. 코드는 기존 자리(`search/`·`collect/`·`db/`·`tests/`)에 두고, 각 작업 폴더의 README에 무엇을 어디에 바꿨는지 적는다.

| 항목 | 내용 |
|---|---|
| 요청서 | `origin/feature/SB-87-init-supervisor-integration:agent-orchestration/docs/공고서버_API요청_공고팀전달.md` (2026-10-03, 10-04 보완) |
| 조율 쪽 연결 코드 | 같은 브랜치 `agent-orchestration/sbrain/agents/notice/` — `SBRAIN_NOTICE_API_URL`을 넣어야 켜진다. 지금은 꺼짐 |
| 연결 방식 변경 | 9/29 "조율 쪽이 우리 코드를 직접 import"([옛 설명서](../guides/ORCHESTRATION_HANDOFF.md)) → 10/3 "공고 서버 HTTP API를 부른다" |
| 시작 | 2026-10-06 |

## 사용자 결정 (2026-10-06)

- 작업을 01~05로 나눠 **하나씩** 진행한다. 한 작업이 끝나면 멈추고 보고한다.
- 가산점은 **실제로 만든다**(LLM 가점 추출 → 신청자별 계산 → 순위 소폭 반영).
- 공고 서버를 어디에 올릴지는 나중에 정한다. 01~05는 PC에서 한다.
- 구현을 먼저 하고, 4nchez에게 보낼 답변서는 마지막(05)에 쓴다.

## 진행표

| 작업 | 내용 | 상태 |
|---|---|---|
| [01_status_match](01_status_match/README.md) | `GET /api/collection_status` 창구, `/api/match` 결과에 `content_version`·`bonus_score`·`bonus_items` | ✅ 10/6 완료 (10/7 배치 뒤 지문 하루 비교 남음) |
| [02_detail_eligibility](02_detail_eligibility/README.md) | `GET /api/notices/{id}`, `POST /api/notices/{id}/eligibility` (기존 판정 규칙을 `search/eligibility.py`로 옮겨 함께 씀) | ✅ 10/6 완료 |
| [03_bonus](03_bonus/README.md) | 가점 추출(LLM) → DB 표 → 신청자별 계산 → 순위 반영 → 매일 배치 연결 | ✅ 10/6 완료 → Codex 검수 반영으로 **추출기 v4·전량 재추출**, 순위 세기 **0**(보류), 매일 배치 14단계는 서버 복사 전 |
| [Codex 검토 요청](CODEX_REVIEW_REQUEST_20261006.md) | 01~03 묶음 검토 | [결과](CODEX_REVIEW_20261006.md): 수정 후 재검수 필요(P1 2·P2 8·P3 3) → [응답·재검수 요청](CODEX_REVIEW_RESPONSE_20261006.md)(13건 반영) |
| [04_contract_test](04_contract_test/README.md) | 조율 쪽 실제 연결 코드(`make_tc2`·`make_g01`·`NoticeClient`)로 8000 서버를 HTTP로 불러 보기(가짜 신청 정보) | ✅ 10/6 완료 — 16개 확인 통과, 모든 공고 G-01 2,765건 형식 오류 0 |
| [05_reply](05_reply/README.md) | 질문 11개 답변·제공 범위·한계를 정리한 답변서 | ✅ 10/6 작성 — 보내기는 사용자 |
| (나중) 배포 | 공고 서버를 올릴 곳 결정, 내부망 전용 | 미정 |

## 2026-10-06 오후 사용자 결정

- **Codex 재검수(P1 1·P2 6·P3 2) 개선은 보류**하고 04·05로 넘어간다. 근거: 조율 쪽 실제 연결이 꺼져 있고(`SBRAIN_NOTICE_API_URL` 미설정) 순위 세기 0이라 지금 사용자 영향이 없다. 남은 지적은 [재검수 결과](CODEX_REVIEW_RECHECK_20261006.md) 8절.
- **실제 연결을 켜기 전 조건:** 가산점을 고치거나(보수적으로 줄이기 — 확실한 경우만 점수, 나머지 null) `bonus_score`를 모두 null로 내보낸다. 05 답변서에 "가산점은 시험 단계"로 적는다.
- **K-Startup 가산점은 null 유지.** 첨부 공고문 경로(`/afile/`)는 robots.txt `Disallow: /afile*/`로 자동 수집 금지, 공공데이터포털 K-Startup API 4종(공고·사업 소개·콘텐츠·통계)에도 공고 첨부 칸이 없고 우대 사항 칸(`prfn_matr`)은 열린 221건 모두 비어 있음(10/6 직접 호출 확인). 창업진흥원 요청은 발표 뒤 과제. 05 답변서에 한계로 적는다.

## 미리 정한 기본 규칙 (바꾸려면 사용자 확인)

- 가산점 `0`/`null`: 공고에 가점이 없거나 모든 항목이 확실히 "해당 없음"이면 `0`. 가점 정보를 못 읽었거나(K-Startup 등) 해당 항목 없이 "모름"만 남으면 `null`. 하나라도 해당하면 해당 항목 점수 합.
- 점수 없이 "가점 부여"라고만 적힌 항목은 합계에 넣지 않는다.
- K-Startup 첨부 공고문 수집은 범위 밖(열린 221건 모두 첨부 없음, 10/6 DB 조회). 가산점은 `null`.

## 10/6 조사 메모 (DB 읽기만)

- 열린 공고 2,459건 중 공고문(API 본문+첨부)에 "가점·가산점"이 나오는 공고 611건(기업마당 609 · K-Startup 2).
- 가점 구절 주변 키워드(대략): 이전 실적 35% · 고용 27% · 지역 24% · 수출 23% · 특허 17% · 여성 17% · 벤처류 인증 15% · 장애인 14% · 청년(나이) 10%. 웹 입력으로 판단할 수 있는 것은 지역·성별·인증 정도다.
