# 다음 세션 인수인계 — 검색에서 벡터 DB 빼기, 가산점 정리, 단위 테스트 결과서 (2026-10-07)

기준 시점: 2026-10-07 오후 작업 종료 (Claude)
작업 범위: `data-collection/`만
이 문서가 **최신 진입점**이다. 이전 인계서는 [archive/NEXT_SESSION_HANDOFF_20261006.md](archive/NEXT_SESSION_HANDOFF_20261006.md)다.

## 1. 새 세션이 가장 먼저 할 것

1. 이 문서를 끝까지 읽는다. 이어서 [STATUS](STATUS.md) 맨 위 두 항목과 [notice_api 진행표](notice_api/README.md)를 읽는다.
2. 사용자는 이근준이다.
   - **커밋·push는 사용자가 직접 한다.** 묻지 않으면 커밋 이야기도 꺼내지 않는다.
   - 모든 답변·중간 안내를 **한국어**로, 비유를 먼저 들고 쉬운 말로 쓴다.
   - 사용자 터미널은 PowerShell 5.1이다. 알려 줄 명령은 PowerShell 기준으로, **한 블록에 한 명령씩** 쓴다. 서버 명령도 "내 PowerShell에서 실행"인지 "서버에 접속해서 실행"인지 꼭 밝힌다.
3. 작업 브랜치는 `feature/SB-189-data-collection`이다. 10/7 변경은 모두 **미커밋**이다.

## 2. 한 줄 요약

오늘 한 일은 네 가지다.
- 공고 서버 검색에서 Chroma를 뺐다. 공용 DB 벡터를 메모리에서 계산한다.
- 가산점을 "틀린 점수를 내느니 모른다고 한다" 방향으로 두 번 조였다. 뜻은 **확인된 가산점 부분합**이다.
- 단위 테스트를 98개 보강하고 워드 결과서를 만들었다.
- 시험 화면(8000 `/`)에 가산점을 보여 주게 했다.

## 3. 오늘 한 일 (시간 순)

| # | 일 | 결과 | 근거 |
|---|---|---|---|
| ① | 내용 지문 하루 비교 | 공통 2,765건 중 바뀜 14건. 모두 실제 변화(모집 종료 13, 제목 수정 1)라 **`cv2-` 확정**. 05 답변서는 사용자가 조율 담당에게 전달함 | STATUS 10/7 "내용 지문" |
| ② | 공고 서버 검색에서 Chroma 빼기 | 새 `search/memvec.py`. 같은 벡터로 만든 Chroma와 비교: 추천 상위 3 같음 62/66(93.9%), 의미 검색 상위 10 겹침 99.5%. 팀 EC2 시험 서버 반영(사용자), 계약 시험 16/16 | 결정 [0010](tracking/decisions/0010-drop-vector-db.md), `reports/vector_db_compare_20261007T005123Z/` |
| ③ | 가산점 "확실한 것만 남기기"(1차) | 근거 문장의 "N점"만 인정, group으로만 묶기, 앞으로의 조건 모름, 세부사업 다르면 null, 한도 넘으면 null, 하루 호출 기록 보호. "가산점 있음" 26 → 7 | `reports/bonus_conservative_20261007T013412Z/` |
| ④ | 단위 테스트 보강 + 워드 결과서 | 새 시험 파일 7개(98개). 커버리지 측정 도구는 이 PC `.venv`에만 설치. 결과서는 ⑤ 뒤 새 숫자로 다시 만듦 | `docs/deliverables/[단위 테스트] 공고 데이터·매칭 단위 테스트 결과서.docx`, `reports/unit_test_20261007T024611Z/` |
| ⑤ | Codex 재검수 → 지적 처리(2차) | 재검수 결과 "추가 수정 후 재검수 필요"(P1 3·P2 3·P3 1). 사용자 결정에 따라 처리했다(아래 목록). "가산점 있음" 신청자마다 7 → 3, 바뀐 방향은 null 쪽뿐 | [결과](notice_api/CODEX_BONUS_RECHECK_20261007.md) · [재재검수 요청](notice_api/CODEX_BONUS_RECHECK2_REQUEST_20261007.md) · 결정 [0012](tracking/decisions/0012-bonus-confirmed-partial-sum.md) · `reports/bonus_conservative_20261007T024147Z/` |
| ⑥ | 서버 반영(사용자 실행) | 팀 EC2 시험 서버: 바깥에서 확인 완료. `/api/match`로 공고 4곳 대조(123858 null·117356 null·117928 1점·120481 10점), 계약 시험 16/16. 배치 서버 `sbrain-web`: 사용자가 반영했다고 함, **아직 확인 못 함** | `reports/notice_api_contract_20261007T030725Z/` |
| ⑦ | 시험 화면 가산점 표시 | `web/app.html`만 고침. 카드·목록에 "확인된 가산점 +N점(일부)·가산점 없음·가산점 모름", 결과 위 집계, 자격 확인 화면에 항목과 가점 원문. 이 PC 8030에서 확인. **시험 서버 반영은 미확인**(명령은 STATUS 맨 위) | STATUS 10/7 "시험 화면" |
| ⑧ | 가산점 산정 규칙 공유 페이지 | 비공개 페이지(사용자 계정): https://claude.ai/artifact/2Usj5hDmdyGjzF8fuVSB5c — 팀원에게 보여 주려면 공유 메뉴에서 열어야 함 | — |
| ⑨ | 가산점이 적은 이유 분석 | 아래 5-2. 사용자는 "일단 그대로 두기"로 함 | — |
| ⑩ | 설명 자료와 폴더 정리(저녁) | 연결 지도 HTML·API 사용법 엑셀(`notice_api/`). 안 쓰는 파일 정리: 캐시·실험 잔재·안 쓰는 코드·`reports/` 지움, 지난 방식 문서 `archive/`로, `README.md` 새로 씀, STATUS·WORKLOG 9월분 `archive/`로. 시험 884개 그대로 통과. Codex 재재검수는 "나중에"(사용자) | STATUS 맨 위 · WORKLOG "data-collection 정리" |

⑤의 처리 내용:
- `bonus_score` = **확인된 가산점 부분합**(결정 0012)
- 근거에 다른 "N점"이 섞이면 점수 없음
- 근거가 원문에 그대로 이어져 있지 않으면 모름(공고 서버가 켤 때 found 행만 확인)
- 묶음 오분류 가능성(다른 묶음인데 같은 근거·점수, 한 묶음인데 "각")이면 null
- found에 불확실 메모가 하나라도 있으면 null
- 확인할 수 없는 조건 말(`CONDITION_WORDS`)이면 모름
- 하루 호출 상한은 잠금 안에서 읽고 예약(`bonus_busy`)

## 4. 조율 쪽과 바뀐 약속 (응답 키는 그대로)

- `bonus_score`는 **확인된 가산점 부분합**이다. 0 = 해당 없음 확인, null = 확인된 것이 없음. `bonus_items.points`는 **원문 배점**이다. 05 답변서의 "한도 적용 뒤 점수"는 틀린 설명이 됐다. → 정정은 [알림 초안](notice_api/BONUS_NOTICE_DRAFT_20261007.md)에 있다. **아직 보내지 않음**(사용자가 보냄).
- 참고 표시가 바뀌었다(값만 바뀌고 계약 키는 아님):
  - `source`는 `vectors+bm25`
  - 정상일 때 `dense_path`는 `memory`
  - `/api/health`에 `vectors`(건수·버림·지문별 건수)가 생겼다
  - 원문을 못 읽으면 `boot_errors.bonus_documents`가 붙는다
- 가산점은 여전히 **시험 단계**다. "화면에 써도 됨"은 Codex 재재검수를 통과한 뒤 알린다. 순위 반영 세기는 0이다.
- 기준 문서: [contracts.md](contracts.md), [business-rules.md](business-rules.md) 9절.

## 5. 지금 상태

### 5-1. 숫자와 서버
- 시험: **884개 중 868 통과·16 건너뜀**(MySQL 통합 시험), 실패 0. 맡은 범위 시험 621개, 줄 커버리지 67.5%.
- 팀 EC2 시험 서버 `http://43.201.90.238:8000`: 오후 가산점 코드 반영·확인 완료. 화면 파일(`web/app.html`)은 반영 여부 미확인.
- 배치 서버 `sbrain-web`: 오전에 코드 전체를 복사했다(가점 14단계 포함, 이전 코드 `~/sbrain/_old/code_before_20261007.tgz`). 오후 파일 3개(`search/bonus.py`·`search/app.py`·`collect/extract_bonus.py`)는 사용자가 반영했다고 했지만 확인은 못 했다.
- 이 PC에서 켜 둔 서버 없음. 임시 8030은 매번 껐다. 저장소 루트 `.claude/launch.json`에 `search-service-8030` 설정을 더했다(이 PC 확인용).

### 5-2. 가산점이 적은 이유 (열린 공고 1,741건)

| 단계 | 공고 |
|---|---|
| 공고문에서 가점을 찾음 | 311 (가점 말 없음 815, 가점 없음 217, 첨부를 못 읽음 389, 근거 확인 실패 9) |
| 불확실 메모 없음 | 252 |
| 신청자 정보로 판단할 수 있는 항목(여성·장애인·인증·지역·청년·재창업)이 있음 | 104 |
| 그 항목이 규칙을 통과함 | 6 |
| 가장 유리한 가상 신청자(인증 전부·여성·청년·재창업, 17개 시·도)로도 점수가 나옴 | 4 |

판단할 수 있는 항목 274개가 막히는 이유는 다음과 같다. 통과한 항목은 33개다.
- AI가 채운 추가 조건(예: "중소기업"): 103
- 점수를 근거에서 확인 못 함: 96
- 확인할 수 없는 조건 말: 23
- 원문에 근거 없음: 15
- 앞으로의 조건: 4

## 6. 남은 일

### 6-1. 사용자 몫 (순서대로)
1. 조율 담당에게 [가산점 뜻 정리 알림](notice_api/BONUS_NOTICE_DRAFT_20261007.md)을 보낸다.
2. Codex에 [재재검수 요청서](notice_api/CODEX_BONUS_RECHECK2_REQUEST_20261007.md)를 맡긴다. 결과는 `docs/notice_api/CODEX_BONUS_RECHECK2_20261007.md`로 남는다. 통과하면 "화면에 써도 됨"을 알린다.
3. 시험 서버에 화면 파일을 반영한다(명령은 STATUS 맨 위, 재시작 필요 없음).

### 6-2. 10/8 09:00 배치 뒤 확인 (새 세션이 먼저 할 일)
- 가점 추출(14단계)이 처음 돈다. 배치 서버 `~/sbrain/data-collection/data/run.log`에서 `exit=`를 확인한다(0 정상, 4는 후처리 경고). 계획 당시 예상은 부를 것 22건, 약 $0.06이다. 공용 DB `notice_bonus`의 갱신 시각도 본다.
- 오후 파일이 배치 서버에 올라갔는지 확인한다(사용자 PowerShell). 숫자가 1 이상이면 반영된 것이다.

```powershell
ssh -i C:\Users\playdata2\.ssh\sbrain-web.pem ubuntu@13.125.40.88 "grep -c bonus_busy ~/sbrain/data-collection/collect/extract_bonus.py"
```

- 시험 서버는 매일 09:20에 재시작한다. 재시작 뒤 `/api/health`의 `boot_errors`가 비었는지 본다.

### 6-3. 나중에 (사용자가 꺼낼 때)
- **가산점 늘리기**(사용자: 일단 그대로 둠). 비용 0인 것부터 순서대로 적었다.
  1. 뜻을 바꾸지 않는 추가 조건("중소기업" 등)을 허용한다.
  2. 업종(81개)·수출(31개) 항목을 이미 받는 입력(주 업종·인증 "수출기업")으로 채점한다.
  3. 평가표 형식 공고를 위해 가점 재추출(약 $2~5, 재검수 필요).
- 배치 7단계 로컬 Chroma·팀 EC2 09:10 `ec2_vecstore` 예약 정리. 서비스는 더 쓰지 않는다.
- 실제 연결 전에 8000 포트를 부르는 곳 IP로만 제한한다. 운영 서버 위치를 정한다.
- 그 밖의 순서는 [범위 대비 현황](tracking/status.md) "남은 일"을 따른다.

## 7. 확인·실행 방법과 하지 말 것

```powershell
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
```

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

```powershell
.\.venv\Scripts\python.exe -X utf8 -m eval.bonus_conservative_compare --old <이전 bonus.py>
```

- 첫째 블록은 작업 폴더로 이동한다.
- 둘째 블록은 전체 시험을 돌린다. 10/7 기준 884개다.
- 셋째 블록은 가산점 규칙을 바꾼 뒤 전후를 비교한다. 공용 DB는 읽기만 한다. 결과가 null 쪽으로만 움직여야 한다.
- 계약 시험: 조율 브랜치 코드를 `git archive -o 파일 origin/feature/SB-87-init-supervisor-integration agent-orchestration/sbrain`로 묶어 임시 폴더에 `tar -xf`로 푼다. 그다음 `python -m experiments.notice_api_contract --sbrain <폴더>\agent-orchestration --url <서버> --all`을 실행한다.
- 이 PC 확인용 서버: `.claude/launch.json`의 `search-service-8030`. 다 쓰면 끈다.
- **시험 작성 함정:** 배치 모듈의 기본 경로는 함수를 정의할 때 묶인다. 모듈 상수만 바꾸면 실제 `data/`를 쓴다. 함수 자체를 임시 경로로 감싼다([engineering-notes.md](engineering-notes.md) "시험 작성").

**하지 말 것**
- 사용자 요청 없이 하지 않는다: 공용 DB 쓰기, 서버 코드 복사·재시작, AWS 변경, Git commit·push, 켜져 있는 8000·8010 서버 끄기.
- K-Startup 첨부를 자동으로 내려받지 않는다.
- 조율 쪽 폴더(`agent-orchestration/`)는 읽기만 한다.
- 업종·지역을 정형 필터나 게이트에 넣지 않는다(순위 신호).
- 가산점 규칙을 느슨하게 해서 숫자를 늘리지 않는다. 늘리려면 6-3의 방법을 사용자와 정한다.
- 조율 담당에게 "화면에 써도 됨"을 재재검수 통과 전에 말하지 않는다.
