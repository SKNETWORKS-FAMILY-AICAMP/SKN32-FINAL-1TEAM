# 다음 세션 인수인계 — 조율 에이전트 연결 준비 마무리 (2026-09-29)

기준 시점: 2026-09-29 오전 작업 종료 (Claude), 같은 날 오후 판정표 P1 수정·프로젝트 점검 반영
작업 범위: `data-collection/`만
이 문서가 **최신 진입점**이다. 이전 인계서는 [archive/NEXT_SESSION_HANDOFF_20260928.md](NEXT_SESSION_HANDOFF_20260928.md)다.

## 1. 새 세션이 가장 먼저 할 것

1. 이 문서를 끝까지 읽는다. 이어서 [STATUS](../STATUS.md) 맨 위 항목들과 [WORKLOG](../WORKLOG.md)의 2026-09-29 항목들을 읽는다.
2. **Git 상태부터 확인한다.**
   - `feature/SB-46-data-collection`은 **PR #10으로 main에 머지됐고**(merge commit `7ab629c`, 마지막 작업 커밋 `7e5e83f`) **삭제됐다**(로컬·GitHub).
   - **지금 작업 브랜치는 `feature/SB-189-data-collection`이다.** main `7ab629c`에서 갈라졌다. 커밋 메시지는 `SB-189 …`, PR 제목은 `[SB-189] …`로 쓴다([docs/git-strategy.md](../../../docs/git-strategy.md), CI가 PR 제목을 검사한다).
   - 다른 브랜치로 옮기기 전에 `git fetch origin main:main`으로 로컬 main을 최신으로 둔다. 9/29에 로컬 main이 40커밋 뒤처져 체크아웃이 막힌 적이 있다.
3. 사용자는 이근준이다.
   - 커밋·push는 사용자가 직접 한다.
   - 설명은 비유를 먼저 들고 쉬운 말로 한다. 중간 안내까지 모두 한국어로 쓴다.

## 2. 9/29에 한 일

| 작업 | 상태 | 근거 |
|---|---|---|
| 9/29 매일 배치 점검 | ✅ 정상. 신규 49건, DB·파일 각 2,525행 일치. Codex도 독립 확인 | WORKLOG "9/29 매일 배치 결과 점검" |
| 조율 에이전트용 **함수 설명서** | ✅ 작성 → Codex 검수 → 개정 → 재검수 **조건부 승인** | [guides/ORCHESTRATION_HANDOFF.md](ORCHESTRATION_HANDOFF.md), [reviews/orchestration/](../reviews/orchestration) |
| 검증 스크립트 | ✅ 설명서의 코드 블록을 그대로 꺼내 D(빠른 시작)·A(T-C2)·B(G-01 2,525건 × 5가지 경우)·C(조율 스텁 흐름)를 확인. 모두 통과 | `experiments/orchestration_probe.py` |
| Codex 판정표 P1(9/28) | ✅ 세 건과 13단계 90% 가드 수정(판정마다 공고문 지문 대조) → Codex 보류(P1 4·P2 3) → 7건 반영(P1-2는 A안) → Codex 2차 보류(A안 경계 2·호출 우회 1) → 횟수 비교·확인 못 한 불가 미사용 반영 → Codex 3차 보류(첨부 경계 가짜 언급) → 조각별 횟수 반영 → ✅ **Codex 승인** | [Codex 승인](../reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK3_20260929.md), [3차 응답](../reviews/integration/JUDGMENT_FRESHNESS_REVIEW_RECHECK2_RESPONSE_20260929.md) |
| 8010 결과 공유 페이지 | ✅ 서버 없이 여는 HTML 5장과 생성 스크립트 | [share/README.md](../../share/README.md) |
| 프로젝트 전체 점검(읽기만) | ✅ 테스트 637개 통과, 9/29 배치 정상. 문서 불일치는 정리했고 코드 과제는 4절 4번에 남김 | WORKLOG "9/29 프로젝트 점검" |

## 3. 9/29 사용자 결정

| 결정 | 내용 |
|---|---|
| 연결 방식 | 조율 쪽이 공고팀 코드를 **직접 import 해서 부른다**(`app.boot()` 한 번 → `app.match()`). 공고팀 서버는 따로 켜지 않는다 |
| 공고팀 역할 | 코드를 조율 쪽에 끼우지 않고 **설명서만 전달**한다. 조율 담당(4nchez)은 우리 브랜치를 다른 브랜치로 머지해 작업한다 |
| G-01 | **모름·입력 누락 = 통과.** 확실히 안 되는 경우만 불합격이다 |
| 접수 시작 전 공고 | **고를 수 있다.** G-01은 접수기간을 보지 않는다(매칭 필터와 같음) |

## 4. 남은 일 (사용자가 순서를 정한다)

1. **Codex 재검수 P2 네 건 — 반영 완료. 2차 재검수 지적도 반영(3차 개정, [2차 응답](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK2_RESPONSE_20260929.md)). 남은 것은 조율 담당 합의.** [재검수 응답](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK_RESPONSE_20260929.md)을 본다.
   - Codex 제출 전 내부 교차 검토에서 6건을 더 고쳤다.
   - 특히 `tc2()`의 수집 상태 분기는 **첫 조회에만** 적용한다. 조율 흐름은 더 보기 뒤에 수집 상태를 보지 않기 때문이다.
   - **9/30 Codex 4차 재검수 승인**([RECHECK4](../reviews/orchestration/ORCHESTRATION_HANDOFF_REVIEW_RECHECK4_20260930.md)) — 설명서 쪽 검수는 끝났다.
2. **조율 담당과 합의**: 설명서 2절 ①마감일, ②금액, ③양식·평가 항목, ⑦확인 필요 표시가 급하다. 합의 뒤 **실제 공고 공급**으로 통합 시험을 한다.
3. ~~**판정표 지문 수정은 Codex 승인됨**(9/29). 9/30 배치에서 10·11·12단계가 비활성 첨부 공고 5건씩 다시 판정하고, 13단계가 신청자 유형 결론(A안 2건, 재판정 뒤 126490)을 올리는지 확인한다.~~ → **9/30 확인 완료**(정상, WORKLOG 9/30).
   - [조율 설명서](ORCHESTRATION_HANDOFF.md)의 `search/app.py` 줄 번호는 9/29 승인 뒤 맞췄다(`MatchRequest` 294 등). `daily_pipeline.py` 종료 코드 4 주석도 9/29에 고쳤다.
4. **9/29 점검에서 나온 코드 과제**(아직 손대지 않음, 사용자가 순서를 정한다)
   - EC2 색인 누락 가능성: `collect/upload_vectors.py`가 묶음마다 같은 시각을 찍고, `ec2/ec2_vecstore.py`는 `> 워터마크`로 고른다. 업로드 도중 09:10 갱신이 돌면 나머지 묶음이 빠진다. 벡터를 전부 다시 올리는 날이 위험하다.
   - ~~K-Startup 조기 마감: 모집 중 목록만 받고 빠진 공고를 닫지 않는다. 마감일 전에 닫힌 공고가 `open`으로 남는다.~~ → **9/30 수정(A안), Codex 재검수 승인**([RECHECK](../reviews/integration/KSTARTUP_CLOSE_MISSING_REVIEW_RECHECK_20260930.md)). **10/1 배치 뒤 닫은 건수를 확인한다**(예상 약 235건, 로그와 `import_runs.report.closed_missing`).
   - `collect/backup_db.py` 백업 대상에 LLM 결과 표(`notice_conditions`·`notice_applicant_types`·`notice_industries`)가 없다.
   - `collect/daily_job.py`가 없는 모듈 `match_bge`를 부른다(매일 배치는 이 경로를 건너뛰어 영향 없음).
   - 보안: 옛 인계서 `archive/HANDOFF.md`에 DB 포트 3306 "개방"과 EC2 주소가 적혀 있다. 저장소 공개 여부 확인 뒤 포트 제한(AWS 설정, 사용자 승인 필요)과 문서 가리기를 정한다.
5. **작은 후속**
   - 업력 상한 오류 `bizinfo:PBLN_000000000126783` — "5년 이상"인데 상한 5가 들어갔다. `age_quote_problem` 보완이 필요하다.
   - 9/28 기획서 대조 C·F·G.
6. **8000/8010 공유**(사용자 검토 중)
   - 8000을 공개하려면 새 EC2 인스턴스를 권한다. 8GB·같은 리전/VPC로 만들면 조율 에이전트도 함께 올릴 수 있다.
   - 8010은 대부분 저장된 결과를 보여 주는 화면이라 **결과 페이지로 공유**하는 편이 낫다(서버 불필요). 9/29에 5장을 만들었다([share/](../../share/README.md)).
   - `/compare`·`/industry-probe`·근거 보기는 8000과 실험 DB에 기대서 이 방식으로는 공유할 수 없다.
   - 8000 공개는 결정 전이다.

## 5. 알아 둘 사실

- **실험 DB**(`notice_match_sql_lab`, 로컬)는 9/18 스냅샷 1,852건에서 멈춰 있다.
  - 서비스(8000), 매일 배치, 조율 연결은 이 DB를 쓰지 않는다.
  - 8010의 `/compare` "새 방식" 칸과 근거 보기(`/api/evidence`)만 쓴다.
  - 서비스 업종 순위 파일 `final5`(1,852건)도 그 시절 목록으로 만들었다. 업종 순위는 꺼져 있다. 다시 켤 때는 `final6`(2,525건)으로 바꾼다.
- **매일 09:00 배치**(작업 스케줄러)는 이 PC 작업 폴더의 **지금 체크아웃된 코드**로 돈다. 브랜치를 바꿀 때는 data-collection 최신 코드가 있는 브랜치(main 등)에 있어야 한다. `.venv`·`.env`·`data/`는 Git이 추적하지 않아 브랜치를 바꿔도 남는다.
- main에는 조율 에이전트(`agent-orchestration/`, SB-85 #9)가 머지돼 있다. 검증 기준 `deb5c81`과 같다. 그래서 검증 스크립트는 `--sbrain ..\agent-orchestration`으로 바로 돌릴 수 있다.

## 6. 확인·실행 방법 (`data-collection/`에서)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests                      # 전체 테스트 (9/29 기준 637개 통과·건너뜀 13)
.\.venv\Scripts\python.exe -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration   # 설명서 검증
.\.venv\Scripts\python.exe -X utf8 -m collect.upload_judgments --plan                  # 판정표 DB·파일 대조 (읽기만)
```

- 서버: 저장소 루트 `.claude/launch.json`의 `search-service`(8000)와 `verify-viewer`(8010). 9/29 오후 기준 둘 다 켜져 있다(8000은 판정표 수정 코드로 다시 켰다).
- `gh` CLI는 이 PC에 없다. PR 확인은 웹에서 한다.

## 7. 하지 말 것

- 업종·지역을 정형 필터나 게이트에 넣지 않는다.
- 설명서에 적힌 함수(`app.boot`·`app.match`·`app.eligibility`·`collection_status.check`·`app.STATE['rows']`)의 이름과 입출력을 바꾸지 않는다. 바꿔야 하면 **설명서를 먼저 고치고 사용자에게 알린다**(조율 쪽이 이 함수들을 직접 부른다).
- 사용자 요청 없이 DB 쓰기, EC2 배포, AWS 설정 변경, Git commit·push를 하지 않는다. 유료 API는 비용을 먼저 확인받는다.
- 기존 `reports/` 결과 폴더를 덮어쓰지 않는다.
