# 공용 작업 이력

현재 상태는 [STATUS.md](STATUS.md), 공통 절차는 [AGENTS.md](../AGENTS.md)를 참조한다.
새 기록은 아래 **작업 기록** 제목 바로 아래에 최신순으로 추가한다.
같은 날 여러 작업이면 구별되는 제목을 쓰고, 이전 기록을 정정할 때는 대상 항목을 명시한다.

## 기록 양식

```markdown
### YYYY-MM-DD · 담당 AI/작업자 · 작업명

- 요청·목적:
- 작업 전 상태: 기존 수정이나 관련 문제
- 변경 파일: 경로와 변경한 역할
- 전후 차이·선택 이유: 같은 입력에서 무엇이 달라지는지, 왜 이 방법인지
- 검증: 실행 명령·조건·결과·결과 파일. 실행하지 않았다면 이유
- 미검증·남은 문제:
- 다음 단계:
```

날짜는 한국 시간 기준으로 적는다. 수치에는 측정 조건과 근거를 붙인다.
과거 작업을 새로 수행한 것처럼 기록하지 않는다. 비밀정보와 개인정보는 적지 않는다.

## 작업 기록

### 2026-10-07 · Claude · data-collection 정리 ("다른 사람이 봐도 헷갈리지 않게")

- 요청·목적: 폴더가 복잡해 처음 보는 사람이 헷갈린다. 안 쓰는 파일·문서를 정리한다. 사용자 결정: 1~5단계 모두 진행, Chroma 코드 제거는 나중(문서에 "안 씀"만 표시).
- 조사: 코드 import 정적 분석·`reports/` 폴더 이름 참조 대조·문서 링크 대조(읽기만, 하위 AI 두 개).
- ① 지움(Git 무시 파일, 약 41MB): 루트 `__pycache__/`(옛 평면 구조 pyc), `data/conditions_sample_*.json` 5개(쓰기만 하고 읽는 곳 없음), `data/vecstore/`의 `qdrant`·`faiss.index*`·`chroma_backup_20260921T…`(9/10·9/21 실험 잔재). `.pytest_cache`는 권한 때문에 못 지움(빈 폴더). `data/vecstore/chroma`는 평가 도구가 읽어 남김.
- ② 지움(Git 추적, 약 12MB):
  - `reports/` 7개 — 코드·문서 어디에서도 이름이 안 나오는 것: `_codex_docx_qa`, `_template_codex`, `industry_rank_check_20260928T021723Z`·`T022212Z`, `bonus_sample_20261006T023723Z`, `industry_weight_probe_20260922T020621Z`, `chroma_integrity_20260921T031731Z`.
  - `reports/`의 9/16 전처리 결과서 초안 생성기 3개와 초안 docx 2개(최종본은 `docs/deliverables/`).
  - `search/search_local.py`(옛 시험 CLI), `scripts/`(`backfill_region.py` 일회성 + `__init__.py`).
  - `collect/daily_job.py`의 없는 모듈 `match_bge` 임베딩 코드와 `skip_embed`·`--skip-embed`(배치는 늘 건너뛰어 닿지 않던 길). `daily_pipeline.py` 호출을 맞춤. 로그의 `embedded`·`embed_error` 키도 빠짐(읽는 곳 없음).
  - 남김: `industry_llm_full_luna_20260922_rough_split2/3`, `search_comparison_20260918T053021Z` — 다른 결과의 meta·manifest가 출처로 가리킨다.
- ③ `docs/archive/`로 옮김: `guides/ORCHESTRATION_HANDOFF.md`(9/29 직접 import), `guides/SCHEDULER.md`(PC 예약), `guides/architecture.html`·`ARCHITECTURE.svg`·`hybrid_flow.html`·`pipeline_flow.html`(Chroma·PC 시절 그림), `WORK_SUMMARY_20260929.md`. 가리키던 링크(README·STATUS·WORKLOG·reviews/orchestration 등 70여 개)와 `experiments/orchestration_probe.py` 경로를 고쳤다. archive 인계서 2개의 깨진 상대 링크 26개도 고쳤다. `share/전체흐름.html`·`web/flow.html`(9/28~29 그림) 맨 위에 "지난 기준" 안내를 붙였다.
- ④ 입구 문서: `README.md`를 새로 썼다(13단계·PC 예약·Chroma 설명 → 14단계·서버 배치·메모리 벡터, 무엇이 어디서 도는지 표). `docs/README.md` 1·2·3·5절, `FLOW.md`(맨 위 "지금 바뀐 것 세 가지", 7단계 "공고 서버는 안 씀"), `guides/QUERIES.md`·`TEAM_DATA.md`, `notice_api/README.md` 진행표(+ 연결 지도 HTML·API 사용법 엑셀), `AGENTS.md`=`CLAUDE.md`(결정 0012까지), `standards.md` 13절, `tracking/status.md` 기준일, `eval/README.md`(Chroma 시절 도구 표시), `collect/AGENTS.md`·`search/AGENTS.md`(지운 파일 줄).
- ⑤ 진행 일지 나누기: `STATUS.md` 216행~끝(9/14~9/30 항목과 옛 고정 절) → `archive/STATUS_202609.md`, `WORKLOG.md` 206행~끝(9/17~9/30) → `archive/WORKLOG_202609.md`. 내용은 그대로, 상대 링크만 새 위치에 맞춤(149·170개). STATUS 160KB → 27KB, WORKLOG 436KB → 34KB.
- 검증: 시험 884개 중 868 통과·16 건너뜀·실패 0(정리 전과 같음). 문서 링크 점검(.md 상대 링크): 남은 52개는 정리 전부터 있던 것 — Codex 검수 문서의 `파일:줄번호` 표기와 결과 보존 원칙상 고치지 않는 `reports/` 안 옛 링크.
- 하지 않은 것: Chroma 코드 제거(배치 7단계·EC2 00:10 예약·`ec2_vecstore`의 Chroma 함수·평가 도구) — 서버 작업이 따라와 나중. `run_daily.bat`·`schedule-task.ps1`(되돌리기용), `data/backup_20260914T160825.sql`(유일한 전체 백업), `reviews/`(지표 코드가 셈), `PLAN_ALIGNMENT`(코드 주석이 가리킴)는 그대로.

### 2026-10-07 · Claude · 시험 화면(8000 `/`)에 가산점 표시

- 요청·목적: 가산점을 `/docs`가 아닌 8000번 시험 화면에서도 시험할 수 있게 한다.
- 작업 전 상태: `web/app.html`은 `bonus_score`를 받지만 보여 주지 않았다.
- 변경 파일: `web/app.html`(카드·목록의 가산점 줄, 결과 위 집계, 자격 확인 화면의 가산점 칸 + `/api/notices/{id}` 가점 원문), `web/AGENTS.md`.
- 전후 차이·선택 이유: 화면 표시만 늘었다. 문구는 조율 담당 알림 초안과 같은 "확인된 가산점(일부)"을 쓴다. 0은 "가산점 없음", null은 "가산점 모름"으로 구분한다. 순위·응답은 그대로다.
- 검증: 이 PC 8030 임시 서버에서 여성기업·벤처·경기 성남시(아이디어 = 김포시 공고 제목)로 검색해 20건을 확인했다.
  - 화면: 확인된 가산점 1(120481 +10점)·없음 7·모름 12. 120481 자격 확인 화면에 "벤처기업 10점"과 가점 원문이 나왔다. 브라우저 오류는 없었다.
  - 시험: 884개 중 868 통과·16 건너뜀.
  - 화면 그림(스크린샷)은 앱 창이 그려지지 않아 찍지 못했다. 글자·구조로 확인했다.
- 미검증·남은 문제: 시험 서버 반영은 사용자 몫이다(명령은 STATUS).

### 2026-10-07 · Claude · 가산점 재검수 지적 처리

- 요청·목적: Codex 가산점 재검수(10/7, P1 3·P2 3·P3 1) 지적을 처리한다. 사용자 결정은 다음과 같다.
  - `bonus_score` = 확인된 가산점 부분합(결정 0012).
  - 짚은 틈은 모두 null로 막는다.
  - AI 재호출·재추출 없음, 공용 DB 쓰기 없음, 순위 반영 0.
- 작업 전 상태: 10/7 오전판(확실한 것만 남기기). "가산점 있음"은 열린 공고 1,741건 중 신청자마다 7곳이었고, 재검수가 10점 → 20점(묶음 분리), 8점(한도 불확실), 이어 붙인 근거 10점 경로를 재현했다.
- 변경 파일: `search/bonus.py`(규칙·원문 확인·머리말), `search/app.py`(boot 오류 칸), `collect/extract_bonus.py`(하루 상한 잠금), `tests/test_bonus.py`(`RecheckTests`·`LoadTests`), `tests/test_extract_bonus.py`(동시 실행), `eval/bonus_conservative_compare.py`(`--old`·관찰 공고), 문서(contracts·business-rules 9절·결정 0008·0012·목록·`search/AGENTS.md`·`notice_api/README.md`), 새 `docs/notice_api/CODEX_BONUS_RECHECK2_REQUEST_20261007.md`·`BONUS_NOTICE_DRAFT_20261007.md`.
- 전후 차이·선택 이유: 새 규칙은 "해당 → 모름", "점수 → 없음/null" 방향뿐이라 결과가 양수 → null 쪽으로만 움직인다. 전체 합계 대신 부분합으로 정한 이유는 다음과 같다. 오전에 점수가 나온 8곳이 모두 모르는 묶음을 함께 갖고 있어, 전체 합계로 정하면 0곳이 되기 때문이다.
  - 기대값을 바꾼 기존 시험: `test_independent_bonuses_in_one_sentence`(123858 4점 → null), `test_uncertain_reading`("중복" 메모 1묶음 3점 → null).
- 검증:
  - `python -X utf8 -m unittest discover -s tests` → 884개 중 868 통과·16 건너뜀·실패 0.
  - `python -X utf8 -m eval.bonus_conservative_compare --old <오전판>` → `reports/bonus_conservative_20261007T024147Z/`(신청자 4명: 있음 0·0·7·7 → 0·0·3·3, null로만 이동).
  - 8030 임시 서버 계약 시험 `--all` → 16개 실패 0, 2,825건 형식 오류 0, `boot_errors` 없음(`reports/notice_api_contract_20261007T024341Z/`).
  - 커버리지 다시 잼 → `reports/unit_test_20261007T024611Z/`(범위 621개, 67.5%). 결과서는 새 숫자로 다시 만들고 글자로 대조함(부록 621행 = 통과 605 + 건너뜀 16).
- 미검증·남은 문제: Codex 재재검수 전. 서버 반영은 사용자 몫(명령은 STATUS). 조율 담당 알림은 사용자가 보낸다. 남은 양수 4곳(117928·120481·122147·126642)은 사람이 원문으로 확인하지 않았다. 결과서는 워드 창을 닫은 뒤 바꿔 넣었다.
- 다음 단계: 서버 반영 → Codex 재검수 → 통과하면 "화면에 써도 됨" 알림.

### 2026-10-07 · Claude · 단위 테스트 보강과 워드 결과서

- 요청·목적: 맡은 역할(서비스에 쓰이는 11개 기능)을 단위 테스트로 점검하고 제출용 워드 결과서를 만든다(사용자 결정: 보강 + 결과서, 커버리지 포함, 기능별 요약 + 대표 사례).
- 작업 전 상태: 시험 778개(통과 762·건너뜀 16). `fetch`·`attachment_pipeline`·`hwp5`·`upload_vectors`·`upload_attachments`·`config`·`eligibility`는 직접 검사하는 시험이 없었다.
- 변경 파일: 새 시험 `tests/test_fetch.py`(9)·`test_attachment_pipeline.py`(32)·`test_hwp5.py`(11)·`test_upload_vectors.py`(13)·`test_upload_attachments.py`(8)·`test_config.py`(9)·`test_eligibility.py`(16). 새 결과서 `docs/deliverables/[단위 테스트] 공고 데이터·매칭 단위 테스트 결과서.docx`. 기록 `docs/STATUS.md`·`docs/README.md`·`docs/tracking/status.md`·`docs/standards.md`. 운영 코드·기존 시험 기대값은 바꾸지 않았다.
- 전후 차이·선택 이유: 시험만 더했다. 가짜 응답·가짜 연결·임시 폴더로만 시험해 비용 0, 공용 데이터 무변경.
- 검증: `python -X utf8 -m coverage run -m run_unit`(= `unittest discover -s tests`) → 876개, 통과 860·실패 0·오류 0·건너뜀 16(`MYSQL_INTEGRATION_TEST` 끔). 범위 시험 613개, 범위 줄 커버리지 67.2%(7,095줄 중 4,771줄). 결과 `reports/unit_test_20261007T021113Z/`(README·coverage_summary.json·tests.json·coverage_report.txt·run.log·측정 스크립트). 결과서는 글자로 다시 추출해 요약 숫자·부록 행 수(613, 통과 597·건너뜀 16)를 대조했다.
- 미검증·남은 문제: MySQL 통합 시험 16개(시험용 DB 없음), 실제 외부 API·첨부 샘플·HWP 파일 시험 없음. 커버리지 낮은 곳 `ec2/ec2_vecstore.py` 0%·`search/vecstore.py` 17.4%. 시험 작성 중 기본 경로가 정의 때 묶이는 함정으로 `data/attachment_results.jsonl`에 가짜 37줄이 생겨 지움(실제 기록 없던 새 파일).
- 다음 단계: 사용자가 결과서 검토·제출.

### 2026-10-07 · Claude · 가산점 "확실한 것만 남기기"

- 요청·목적: 10/6 Codex 재검수 지적(P1 1·P2 6·P3 2) 처리 방식을 사용자가 정함 — 재추출 없이 계산만 줄이기.
- 변경 파일: `search/bonus.py`, `collect/extract_bonus.py`, `tests/test_bonus.py`·`test_extract_bonus.py`·`test_match_deh.py`·`test_notice_api.py`, 새 `eval/bonus_conservative_compare.py`, 새 `docs/notice_api/CODEX_BONUS_RECHECK_REQUEST_20261007.md`, 기준 문서(판정 9절·창구·결정 0008·현황·미해결·함정·`search`/`collect` 안내), 진행표.
- 전후 차이·선택 이유: 틀린 점수보다 "모름"이 낫다는 사용자 원칙. 합계 한도는 범위를 확인할 수 없어 자르지 않고 null로 바꿨다 — `bonus_items.points`가 "한도 적용 뒤"에서 "원문 배점"으로 바뀐다(답변서 문구와 달라짐 → 재검수 통과 뒤 알림에 포함). 공고 합계의 "확인된 부분합" 정의는 그대로(재검수에 판단 요청).
- 검증: 시험 778 통과·16 건너뜀(처음 5건 실패 — 근거에 N점이 없는 가짜 항목·옛 기대값·가짜 DB 칸 수 — 모두 시험 쪽을 새 규칙에 맞춤). `python -X utf8 -m eval.bonus_conservative_compare` → 열린 공고(모집 마감 아님 + 마감일 안 지남) 1,741건 전후 표, 재현 공고 값. 처음 실행은 `recruitment_status='open'`만 세어 221건(기업마당은 unknown)이라 버리고 조건을 고쳐 다시 실행. 8030 임시 서버 boot 오류 없음, 계약 시험 `--all` 16/16.
- 미검증·남은 문제: Codex 재검수, 서버 두 곳 반영(사용자), 배치 서버의 첫 14단계 실행(내일 09:00).
- 다음 단계: 재검수 → 조율 담당 알림.

### 2026-10-07 · Claude · 공고 서버 검색에서 벡터 DB(Chroma) 빼기

- 요청·목적: 10/6 결정(벡터 DB 미사용, 결과서 제출)을 코드에 반영하고, 결과가 같은지 확인.
- 작업 전 상태: `search/app.py`가 PC는 `data/vecstore/chroma`, 리눅스는 `ec2/data/vecstore/chroma`(또는 `VECSTORE_PATH`)를 열었다. PC 색인은 10/2분(2,714건)이라 그 뒤 공고가 의미 검색에서 빠졌다.
- 변경 파일: 새 `search/memvec.py`(MemoryCollection — Chroma와 같은 count·query(ids)·get 모양, 거리 1−내적, 같은 거리면 공고 ID 순; 공용 DB 읽기 `load`, 1,024차원·4,096바이트만, 지문 경고), `search/app.py`(`_collection`이 공용 DB 벡터를 올림·0건이면 예외, `boot` 출력·지문 경고, `dense_path` 정상 `memory`, `source` `vectors+bm25`, `/api/health` `vectors`, 머리말), 새 `tests/test_memvec.py`, `tests/test_match_rules.py`(기대값 `memory`), 새 `eval/vector_db_compare.py`, 기준 문서·폴더 안내.
- 전후 차이·선택 이유: 벡터 출처를 공용 DB로 정해(사용자 선택) PC·팀 EC2가 같은 최신 벡터를 쓴다. 인터페이스 모양을 유지해 평가 도구(`CorpusCollection` 등)가 고치지 않고 돈다. 비교는 같은 벡터로 임시 Chroma를 새로 만들어(사용자 선택) 방식 차이만 보이게 했다.
- 검증: `python -X utf8 -m unittest discover -s tests` → 771 통과·16 건너뜀. 처음 1건 실패(`test_boot_normal_has_no_errors` — 가짜 `_collection`이라 지문 정보가 비어 경고가 남) → 벡터 쪽 지문 정보가 없으면 판단하지 않게 고침. `python -X utf8 -m eval.vector_db_compare` → 질의 66, 벡터 2,825, chromadb 1.5.9: 의미 검색 상위 10 겹침 99.5%·순서 같음 63/66·1위 66/66, 추천 상위 3 같음 62/66(93.9%)·상위 10 같음 51/66, 의미 검색 6.58ms vs 7.55ms, `match` 384ms vs 395ms. 다른 4개 질의 중 2개는 상위 3 구성이 같고 순서만 다름. `PORT=8030 python -m search.app`(이 PC, 켤 때 34.9초) → `/api/health` 벡터 2,825·`boot_errors` 없음, 계약 시험 `--url http://127.0.0.1:8030 --all` 16/16, 2,825건 형식 오류 0, 건당 24ms. 임시 서버는 끔.
- 미검증·남은 문제: 팀 EC2 시험 서버 반영 전(사용자 실행). 배치 7단계·EC2 09:10 예약·Chroma 정합성 도구 정리는 이번 범위 밖. `search/app.py` 머리말의 `\.venv` 표기가 SyntaxWarning을 낸다(기존, 동작 무관).
- 다음 단계: 시험 서버 반영 → 바깥에서 `/api/health`·계약 시험.

### 2026-10-07 · Claude · 공고 내용 지문 하루 비교

- 요청·목적: 10/6에 정한 내용 지문(`cv2-`)이 수집 잡음 없이 내용이 바뀔 때만 바뀌는지 하루 지나 확인.
- 변경 파일: STATUS·`docs/tracking/status.md`(현황·남은 일 갱신). 코드 변경 없음.
- 검증: `.\.venv\Scripts\python.exe -X utf8 -m search.content_version --compare data/notice_api/content_version_20261006_cv2.json`(공용 DB 읽기만) → 이전 저장 10/6 00:00:04 UTC → 지금 10/7 00:00:03 UTC, common 2,765 · changed 14 · added 60 · removed 0, by_field `recruitment_status` 13 · `title` 1. 변화 공고를 DB에서 확인: `kstartup:176218`·`179190` 등은 `closed`(K-Startup 목록에서 빠져 모집 종료), `kstartup:179350` 제목 끝 "(수정)". 첨부·링크·접수기간 원본 같은 칸의 잡음 변화 0.
- 결론: `cv2-` 그대로 확정. 접두어를 올리지 않는다.
- 다음 단계: 조율 담당에게 "내용 버전 잠정 → 확정" 알림(사용자).

### 2026-10-06 · Claude · 팀 EC2 시험 서버 안내·확인과 답변서 주소 반영

- 요청·목적: 조율 담당에게 줄 공고 서버 주소. "답변서 공개 시험 서버 없음에서 해당 주소로 변경".
- 작업 전 상태: 팀 EC2 8000에 아무것도 없었음(사용자 `ss -ltn` 확인). 9/15 이후 그 서버에는 색인 갱신용 `~/s-brain`만 있었다.
- 변경: 서버 쪽은 사용자가 직접 했다(코드 복사·패키지·systemd·cron·보안그룹 — 단계는 STATUS 같은 날 항목). 저장소 쪽은 `docs/notice_api/05_reply/README.md`(머리 표·0절·질문 1·3·8·9·3절·4절·5절)와 STATUS.
- 전후 차이·선택 이유: 답변서가 "주소 없음"이던 것을 시험 서버 주소와 접속 조건(시험 기간만 전체 공개·인증 없음·가짜 신청 정보로만, 실제 연결 전 IP 제한)으로 바꿨다. 같은 문서 안에서 어긋나던 문장(함께 시험 미정, PC 색인 10/2 문제, PC 응답 시간)을 함께 맞췄다. 운영 위치·인증·동시 호출·가산점 정리는 그대로 미정.
- 검증: 바깥에서 `GET /api/health` 200(공고 2,765·색인 2,766(워터마크 포함)·`boot_errors` 없음), `/api/collection_status` 정상. 계약 시험 `python -m experiments.notice_api_contract --sbrain <임시>gent-orchestration --url http://43.201.90.238:8000` → 15개 통과(`reports/notice_api_contract_20261006T084646Z/`). systemd 로그로 재시작 반복(65회, 원인 8000 선점) 확인 후 해소. 참고: PowerShell에서 `git archive … | tar -x`는 파이프가 바이너리를 망가뜨려 실패 → `git archive -o 파일` 뒤 `tar -xf`로 해야 한다.
- 미검증·남은 문제: 동시 호출 안전성, 서버 재부팅 직후 첫 기동 시간, 메모리 여유(4GB에 MySQL과 공존).
- 다음 단계: 기준 문서 갱신, 실제 연결 전 IP 제한.

### 2026-10-06 · Claude · 공고 서버 API — 05 답변서

- 요청·목적: 조율 담당 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`, 10/3·10/4)에 답하는 문서. 사용자 요청 "답변서를 써줘".
- 작업 전 상태: 01~04 완료·push 됨. 요청서는 04 계약 시험에 쓴 `b8e7f50` 이후 바뀌지 않음(원격 diff 없음, 10/6 확인).
- 변경 파일: 새 `docs/notice_api/05_reply/README.md`. 진행표 `docs/notice_api/README.md` 05 줄, STATUS, `docs/tracking/status.md`, `docs/contracts.md`(생년월일 답·업력 상한 null 두 뜻·503 본문).
- 전후 차이·선택 이유: 조율 쪽이 답변서를 그대로 믿고 코드·화면 문구를 고치므로, 정하지 않은 것(배포 위치·인증·재시작 방식·동시 호출·가산점 정리·함께 시험)은 "미정"으로 쓰고 날짜를 약속하지 않았다(사용자 선택). 개인정보 최소화로 생년월일은 "아직 보내지 말아 달라". 요청서가 다르게 읽는 값(업력 상한 null = 제한 없음, 공개 시험 서버 있음, `support_amount_text`)을 바로잡았다. 사실 확인 중 새로 알게 된 것: 지금 PC 시험 서버는 10/2 뒤 공고가 하이브리드 추천에 아예 안 나온다(벡터 없는 공고는 RRF 결과에서 빠짐, `search/app.py` 하이브리드 경로), 수집 상태의 "최근 배치 실패·출처 실패" 판정은 배치 일지가 있는 기계에서만 작동한다.
- 검증: 답변서의 사실 주장을 코드와 대조(`search/collection_status.py`·`notice_api.py`·`content_version.py`·`app.py`·`hybrid.py`·`bonus.py`·`applicant.py`, 02·04 기록 수치). 적합도 최솟값은 `RRF_K=60`·`DEPTH=50`으로 계산(하이브리드 약 0.277, 단독 경로 약 0.555). 계획 단계에서 독립 검토 2회(결정 누락 점검·실행 가능성 점검)를 거쳐 지적을 반영. 코드 변경은 없고, 확인용으로 `python -X utf8 -m unittest discover -s tests` → 758개 통과·16개 건너뜀(실패 0).
- 미검증·남은 문제: 동시 호출 안전성, 재시작 중 응답 불가(약 20~25초) 처리, 내용 버전 하루 비교(10/7).
- 다음 단계: 사용자가 답변서를 보낸다. 10/7 배치 뒤 내용 지문 비교 → 바뀌면 조율 담당에게 먼저 알린다.

### 2026-10-06 · Claude · 공고 서버 API — 재검수 지적 보류·K-Startup 첨부 확인·04 계약 시험

- 요청·목적: Codex 재검수 확인 → 사용자가 개선 보류 후 다음 작업 진행을 결정. K-Startup 가산점이 없는 이유 확인과 첨부 확보 가능성 조사. 04 계약 시험.
- 작업 전 상태: 01~03 v4(미커밋), 8000은 v4로 켜짐. Codex 재검수 결과 "추가 수정 후 재검수 필요".
- 변경 파일: 새 `experiments/notice_api_contract.py`, 새 `docs/notice_api/04_contract_test/README.md`, 진행표·결정(`docs/notice_api/README.md`)·STATUS. 결과 `reports/notice_api_contract_20261006T035438Z/`. 판정표 페이지(artifact, 비공개) 게시.
- 전후 차이·선택 이유: 서비스 코드 변경 없음. K-Startup은 robots.txt `Disallow: /afile*/`(첨부 목록·다운로드 경로) 때문에 자동 수집하지 않기로 했다(파이썬 robotparser는 별표를 해석하지 못해 '허용'으로 잘못 답함 — 규칙을 직접 읽어 판단). 공공데이터포털 `kisedKstartupService01` 4개 기능을 1건씩 호출해 공고 첨부 칸이 없음, `prfn_matr`(우대 사항) 열린 221건 모두 빈 값, 외부 안내 주소 186건은 구글 설문·각 기관 사이트로 파일 0건임을 확인. 04는 조율 쪽 코드를 작업 트리 밖 임시 폴더에 `git archive`로 풀어 우리 `.venv`로 불렀다(pydantic 같은 판).
- 검증: 계약 시험 16개 통과 — T-C2 8회(카드 10·rank·시·도 바꾸기), G-01 40회(업력 사사오입 일치), 공고 없음 `ResourceNotFound`, 경로 없음 `ProviderError(404)`, 설립일 없는 사업자 판정 생략, 모든 공고 G-01 2,765건 형식 오류 0(65초). 첫 실행에서 내 시험 코드가 한글 경로(`/없는경로`)를 써서 urllib 인코딩 오류가 났고 영문 경로로 고쳐 다시 돌렸다. OpenAI·DB 쓰기 없음.
- 미검증·남은 문제: 조율 쪽 흐름 전체(워커·저장소·웹)는 범위 밖. 조율 기준 커밋 `b8e7f50`(10/5). 가산점 정확성은 보류 중.
- 다음 단계: 05 답변서.

### 2026-10-06 · Claude · Codex 검수(공고 서버 API 01~03) 13건 반영 — 가산점 추출기 v4·전량 재추출

- 요청·목적: 사용자 "코덱스가 리뷰 남겼는데 확인 바랄게". [검수](notice_api/CODEX_REVIEW_20261006.md)를 확인하고 반영했다. 사용자가 비용은 덜 신경 써도 된다고 해서 재추출까지 진행했다.
- 작업 전 상태: 01~03 미커밋. 검수 결론은 "수정 후 재검수 필요"(P1 2·P2 8·P3 3). 13건 모두 코드에서 재확인했다. v3 결과에서 같은 근거 문장이 점수 항목 여러 개로 나뉜 공고는 103건이었다.
- 변경 파일
  - `collect/extract_bonus.py`: v4. `build_parts`, `locate_all`, `_points_in`, `_total_supported`, `verify(complete)`, `plan_work` 3중 비교, `run_batch` 하루 누적, `--ids`.
  - `search/bonus.py`: `load` 최신성, `item_hit` 추가 조건·전남/광주, `_groups`·`_score_scope`·세부사업.
  - `search/app.py`: boot 가점 최신성, `Weights.bonus` 0.
  - `search/notice_api.py`: `served_status`.
  - `search/content_version.py`: active, cv2.
  - `collect/daily_pipeline.py`: 설명.
  - 새 `db/mysql_migration_008_notice_bonus_content_version.sql`.
  - 시험: `tests/test_extract_bonus.py`·`test_bonus.py`·`test_match_deh.py`·`test_notice_api.py`.
  - 문서: [응답서](notice_api/CODEX_REVIEW_RESPONSE_20261006.md)·03 README·01 README·진행표·FLOW·문서 지도·STATUS.
- 전후 차이·선택 이유: 지적별 내용은 응답서 1절에 있다. 순위 세기는 근거가 부족해 0으로 내렸다. 결과의 `bonus_score`는 그대로 나간다. 지어내지 않는 쪽을 택해 null이 늘었다.
- 검증
  - 표본 30건(검수와 같은 공고) v4 재추출 3회, 약 $0.20. 첫 판의 묶음 오남용·괄호 숫자 누락·같은 문구 두 번을 고쳤다.
  - 공용 DB `notice_bonus`에 칸 추가(008, 사용자 진행 지시). 전량 재추출 2,078행(LLM 969, 실패 0, 약 $1.79, `reports/bonus_full_20261006T024214Z/`).
  - 서버 읽기에서 뺀 행 0. 가상 신청자 '여성기업·벤처·경기 성남시' 가산점 48건(v3 62).
  - 전체 시험 758 통과(건너뜀 16).
  - 10/7 비교 기준 `data/notice_api/content_version_20261006_cv2.json`(cv1 대비 첨부 지문이 바뀐 공고 8건).
- 미검증·남은 문제
  - 사람 정답 없음(표본은 Codex AI 판정과 대조).
  - `points_source`를 LLM이 빼면 점수 null.
  - 병합 표 해석은 LLM 몫.
  - 서버 배치 복사본 미갱신. 8000은 옛 코드.
- 다음 단계: 사용자가 Codex 재검수를 맡긴다 → 04·05. 사용자는 이 대화를 여기서 멈추고 다른 채팅에서 이어 간다.

### 2026-10-06 · Claude · 공고 서버 API 03-2~3-5 — 가점 전량 추출·신청자별 가산점·순위 반영·매일 배치

- 요청·목적: 사용자 "3-2 진행해줘"(공용 DB 표 생성·667건 추출 승인), "3번까지 마무리되면 Codex 검토". 03 나머지를 마치고 Codex 검토 요청서를 쓴다.
- 작업 전 상태: 3-1 완료(추출기·표본). `notice_bonus` 표 없음.
- 변경: 공용 DB에 `notice_bonus` 생성(생성 전 없음 확인)·2,057행 적재. 코드 `collect/extract_bonus.py`(no_mention·bonus_info 대조·`--all`·`run_batch`), 새 `search/bonus.py`, `search/app.py`(boot 가점·결과 가산점·`Weights.bonus` 기본 0.2·`bonus_boost`), `search/notice_api.py`(`bonus_info`), `collect/daily_pipeline.py`(14단계·`--skip-bonus`·`--bonus-limit`), 새 `eval/bonus_rank_eval.py`, 시험(`test_extract_bonus` 17·`test_bonus` 12·`test_notice_api` +3·`test_match_deh`), 문서 `docs/notice_api/03_bonus/`·진행표·[Codex 검토 요청](notice_api/CODEX_REVIEW_REQUEST_20261006.md)·문서 지도·FLOW·STATUS.
- 전후 차이·선택 이유: 추천 결과의 `bonus_score`·`bonus_items`가 신청자 성별·인증·지역에 따라 채워진다(0 = 해당 가점 없음, null = 계산 못 함). 공고 상세 `bonus_info`. 가산점이 있는 후보가 있으면 같은 규칙 묶음 안에서 순서가 바뀐다(세기 0.2). 가산점 후보가 없으면 순서는 전과 같다. 판정 규칙은 실제 데이터 무작위 점검에서 너무 후한 4가지(장애인표준사업장·연구소 조건·여성연구자/가족친화·지역 근거 없는 항목)와 중복 집계, 너무 엄격한 1가지(대표이사 여성)를 고친 결과다.
- 검증: 전량 추출 실패 0·약 $1.05(추정). 전체 시험 745 통과·건너뜀 16. 가상 신청자 4종 분포(예: 여성기업·벤처·경기 성남시 62건 가산점). 순위 측정(`reports/bonus_rank_eval_20261006T015155Z/`) 세기 0.1~0.3 관련도 지표 변화 0. 실제 `boot()` + `/api/match` 가산점 형식 어긋남 0, 속성 없는 신청자 세기 0·0.2 순서 동일. 8000 서버는 건드리지 않았다(10/6에 켠 01·02 코드 그대로).
- 미검증·남은 문제: 사람 정답 없음(AI 참고). K-Startup은 가산점 늘 null. 순위 측정은 가점 공고가 드물어 효과가 작게 잡힘. 서버 매일 배치는 복사본이라 14단계가 아직 돌지 않는다. 10/7 지문 하루 비교 남음.
- 다음 단계: 사용자가 Codex 검토를 맡긴다. 그 뒤 04(조율 쪽 코드로 불러 보기)·05(답변서).

### 2026-10-06 · Claude · 공고 서버 API 03-1 — 가점 추출기와 표본 30건

- 요청·목적: 조율 요청서 3.2(신청자별 가산점). 사용자 결정 "실제로 만든다". 03을 5단계로 나눠 첫 단계로 공고문 가점 추출기를 만들고 표본으로 품질을 본다.
- 작업 전 상태: 01·02 완료(미커밋). 가점 데이터 없음. 10/6 조사: 열린 공고 중 가점 언급 약 610~670건(거의 기업마당), K-Startup은 첨부 미수집.
- 변경 파일: 새 `collect/extract_bonus.py`, 새 `tests/test_extract_bonus.py`(13개), 새 `db/mysql_migration_007_notice_bonus.sql`(실행 안 함), 문서 `docs/notice_api/03_bonus/README.md`·진행표·STATUS. 결과 `reports/bonus_sample_20261006T011805Z/`·`…T012116Z/`.
- 전후 차이·선택 이유: 서비스 동작은 바뀌지 않는다(추출기만 추가). 기존 추출기와 같은 원칙(문서에 적힌 것만, 근거 원문 필수, 근거가 없으면 코드가 버림). v1 결과를 30건 모두 읽고 고쳤다: 선정 뒤 혜택을 가점으로 잡음 → 지시문 규칙, 표 칸이 끼어든 근거를 지어낸 것으로 오판 → "같은 순서·가까이" 대조, 표의 단위 없는 숫자 점수 → 인정, 지역 17곳 → 상한, 가점 없음/모름 구분 → status. 청년 고용을 청년(나이)으로 분류 → v3 지시문.
- 검증: v1 → v2 같은 표본 30건 비교(혜택 오인 3건 해소, 점수 있는 항목 16 → 31). 새 검사를 v1 원본에 다시 적용해 효과를 호출 없이 먼저 확인. 시험 13개 통과. 유료 호출 약 $0.08(추정). DB 쓰기 없음.
- 미검증·남은 문제: 사람 정답 검증 없음(AI 참고). 웹 입력으로 맞출 수 있는 가점 종류가 적어 가산점이 null(정보 없음)인 공고가 많을 것이다. "최대 N점, 1점당 1점" 항목 점수는 최대값으로 적힌다.
- 다음 단계: 3-2(공용 DB `notice_bonus` 표 생성 + 667건 추출, 약 $0.9) — 사용자 승인 필요.

### 2026-10-06 · Claude · 공고 서버 API 02 — 공고 상세·자격 판정 창구

- 요청·목적: 조율 요청서 2.4·2.5. 조율 에이전트가 후보 공고를 고를 때 부르는 공고 상세와 자격 판정 창구를 연다. 자격 판정은 추천의 정형 필터와 같은 규칙이어야 한다.
- 작업 전 상태: 01 완료 직후(미커밋). 화면용 `/api/eligibility`만 있었고 판정 코드가 app.py 안에 있었다.
- 변경 파일: 새 `search/eligibility.py`(app.py 판정 본문을 그대로 옮김, `today`·판정표를 인자로), `search/notice_api.py`(상세·판정 창구, 지원 금액 읽기), `search/app.py`(화면용 판정이 새 함수를 부름 · boot에서 지원 금액 읽기), `tests/test_notice_api.py`(11개 추가), `tests/test_match_deh.py`(가짜 DB 보강), 문서 `docs/notice_api/02_detail_eligibility/`·진행표·FLOW·STATUS.
- 전후 차이·선택 이유: 새 창구 두 개가 생겼다. 화면용 판정 결과는 바뀌지 않는다. 규칙을 복사하지 않고 한 함수로 모은 것은 요청서가 "추천과 판정이 한 곳의 규칙에서 나오게" 해 달라고 했기 때문이다. 새 판정은 지원대상 유형·업력만 보고 접수기간·모집 상태는 보지 않는다. 판정표가 꺼져 있으면 본문 유형을 쓰지 않는다(추천 필터와 같음). 근거·정의는 [02 기록](notice_api/02_detail_eligibility/README.md).
- 검증: 전체 시험 713 통과·건너뜀 16. 실제 `boot()` 후 2,765건 × 신청자 5가지 = 13,825회에서 추천 필터와 다른 결론 0건. 옛 app.py(`99a0bc9`)와 화면용 판정 16,590회 비교 다름 0건. 공고 상세 2,765건 형식 오류 0. 유료 호출·DB 쓰기 없음. 8000 서버는 건드리지 않았다.
- 미검증·남은 문제: 사업자 신청자는 모든 공고에서 "지원대상 유형"이 확인 필요로 나온다(개인·법인 자동 판정 안 함, 9/28 결정). `support_amount_text`는 null. 05 답변서에 적는다.
- 다음 단계: 03(가산점), 사용자가 시작을 정한다.

### 2026-10-06 · Claude · 공고 서버 API 01 — 수집 상태 창구·추천 결과 키

- 요청·목적: 조율 담당(4nchez)의 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`)에 따라 공고 서버에 HTTP 창구를 연다. 사용자가 작업을 01~05로 나눠 하나씩 진행하고, 작업별 기록은 `docs/notice_api/`에 두기로 했다. 이번은 01.
- 작업 전 상태: 깨끗한 작업 트리(`99a0bc9`). 수집 상태 판정 함수는 있었지만 HTTP 창구가 없었고, 추천 결과에 내용 버전·가산점 키가 없었다.
- 변경 파일: 새 `search/notice_api.py`(수집 상태 창구), 새 `search/content_version.py`(공고 내용 지문·하루 비교 명령), `search/app.py`(창구 연결·boot에서 저장 시각과 지문 읽기·결과 키 3개), 새 `tests/test_notice_api.py`(16개), `tests/test_match_deh.py`(boot 가짜 DB 보강), `.gitignore`(`data/notice_api/`), 문서 `docs/notice_api/`(새)·`docs/README.md`·`docs/FLOW.md`·STATUS.
- 전후 차이·선택 이유: `GET /api/collection_status`가 생겼다. DB 판정에 더해 **서버가 메모리에 올린 공고가 24시간을 넘으면 정상 → 지연**으로 내린다(서버를 다시 켜야 새 공고가 반영되기 때문). DB를 못 읽으면 503. 추천 결과 한 건에 `content_version`(원문 칸 + 첨부 파일 바이트 SHA-256, 수집 시각·LLM 값 제외), `bonus_score: null`, `bonus_items: []`가 붙는다. 순위·필터 등 기존 동작은 바뀌지 않는다. 자세한 근거는 [01 기록](notice_api/01_status_match/README.md).
- 검증: 전체 시험 702 통과·건너뜀 16. 실제 DB 지문 2,765건 0.2초·재계산 동일·충돌 0. 실제 `boot()`(25.4초) 후 TestClient로 수집 상태 200 `정상`, 가짜 신청 정보로 추천 offset 0·10 각각 10건·필수 키 누락 없음. 8000 서버는 건드리지 않았다. 유료 호출·DB 쓰기 없음.
- 미검증·남은 문제: 지문이 날마다 수집 잡음으로 바뀌지 않는지는 10/7 배치 뒤 `python -m search.content_version --compare data/notice_api/content_version_20261006.json`으로 확인해야 한다. 이 PC의 8000은 옛 코드라 다시 켜야 새 창구가 열린다.
- 다음 단계: 02(공고 상세·자격 판정), 사용자가 시작을 정한다.

### 2026-10-02 · Claude · 매일 수집 배치를 PC 에서 서버(EC2)로 전환

- 요청·목적: PC 를 꺼 둔 날(10/1 병가) 수집이 멈추는 문제를 없앤다. 웹 배포용으로 만든 개인 계정 EC2 `sbrain-web` 에서 배치만 돌린다(공고 매칭 8000 은 옮기지 않음). 사용자 결정: 시험 1~3단계 뒤 "전환해 줘".
- 작업 전 상태: 10/2 08:43 PC 배치가 밀린 실행으로 돌아 09:05 `exit=0`(공고 2,714건, K-Startup 모집 종료 292건 — 모두 마감일 지난 공고, 인계서의 "10/1 배치 뒤 닫은 건수 확인" 과제는 이것으로 확인). 09:00 정규 실행은 실행 중이라 무시됐다(`IgnoreNew`).
- 변경 파일(data-collection 코드는 고치지 않았다): 저장소 루트 `deploy/` 에 `batch.Dockerfile`·`batch.Dockerfile.dockerignore`·`batch-requirements.txt`(PC .venv 버전 고정, torch 는 CPU 판)·`run_batch.sh`(run_daily.bat 의 리눅스판, 같은 `data/run.log` 에 기록) 추가, `docker-compose.yml` 에 `batch` 서비스(profile) 추가, `deploy/README.md` 에 절차·시험 기록.
- 서버 배치: `~/sbrain/data-collection`(이 PC 작업 폴더 10:54 복사, `.venv`·`docs`·`ml`·`.env` 제외), `.env` 는 배치에 필요한 키 8개만(권한 600), DB CA 는 `~/sbrain/secrets/ec2-ca.pem`(compose 가 `MYSQL_SSL_CA` 를 덮음), BGE-M3 는 볼륨 `sbrain_hf_cache` 에 **리비전 `5617a9f…` 고정**(다르면 `shared/embed.fingerprint` 가 바뀌어 전량 재임베딩).
- 검증(DB 쓰기 0, LLM 0):
  - dry-run: AWS 에서 두 API 응답(K-Startup 215 = 서버 보고, 기업마당 1,444).
  - 예약과 같은 빈 환경 dry-run `exit=0`. 이때 `docker compose run` 이 표준입력을 삼켜 부른 쪽 스크립트가 끊기는 문제를 찾아 `run_batch.sh` 에 `< /dev/null` 을 붙였다.
  - 팀 DB 암호화 SELECT 2,714건 0.3초, `embed.run(plan_only=True)` "그대로 2,714 · 만들 것 0", 설정 지문 PC 와 같음.
  - 실제 공고 112건 임베딩(저장 안 함) 109.6초, 프로세스 최대 2,435MB, 서버 여유 메모리 최저 2,058MB / 3,811MB.
- 전환: PC 예약 작업 `Disable-ScheduledTask`(삭제 안 함) → 시험으로 바뀐 서버 `data/` 를 `~/sbrain/_old/data_test_20261002` 로 옮기고 PC `data/` 재복사(서버 run.log 마지막 줄이 PC 와 같은 09:05 `exit=0`) → crontab `0 0 * * *` 등록, cron active.
- 미검증·남은 문제: 서버에서의 실제 실행(DB 쓰기·LLM)은 아직 없다. 첫 실행은 10/3 09:00. 이 PC 의 8000 색인은 더 이상 갱신되지 않는다. 서버 코드는 복사본이라 PC 코드 수정이 자동 반영되지 않는다. 팀 EC2 의 09:10 Chroma 갱신과 겹치는 기존 문제(인계서 4절)는 그대로다.
- 다음 단계: 10/3 09:20 쯤 서버 run.log·DB 점검, 정상이면 `_old` 정리.

---

2026-09-30 이전 기록은 [archive/WORKLOG_202609.md](archive/WORKLOG_202609.md)로 옮겼다(2026-10-07).
