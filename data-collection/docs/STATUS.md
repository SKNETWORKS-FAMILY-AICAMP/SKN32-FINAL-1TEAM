# 현재 작업 상태

마지막 갱신: 2026-10-07 · Claude (**data-collection 정리**) · 그 전: 2026-10-07 Claude (시험 화면에 가산점 표시)

**10/7 하루 정리·다음 세션 진입점: [NEXT_SESSION_HANDOFF_20261007.md](NEXT_SESSION_HANDOFF_20261007.md)** (10/6 인계서는 `archive/`로 옮김)

## 2026-10-07 · Claude · data-collection 정리 끝 ← **다음 채팅은 여기부터**

- 사용자 요청: "다른 사람이 봐도 헷갈리지 않게" 안 쓰는 파일·문서 정리. 1~5단계 모두 했다. 자세한 목록은 WORKLOG 같은 날 항목.
- 한 일: 캐시·실험 잔재 약 41MB(Git 무시), 안 쓰는 코드·`reports/` 약 12MB(Git 추적) 지움. 지난 방식 문서 7개 `archive/`로. 입구 문서(`README.md` 새로 씀, `docs/README.md`, `FLOW.md` 등) 지금 모습에 맞춤. STATUS·WORKLOG 9월분을 `archive/STATUS_202609.md`·`WORKLOG_202609.md`로 떼어 냄.
- 확인: 시험 884개 중 868 통과·16 건너뜀·실패 0. 문서 링크 새로 깨진 것 없음.
- 미커밋. 지운 파일은 `git status`에 ` D`로, 옮긴 문서는 지움 + 새 파일로 보인다.
- 남은 정리(나중): Chroma 코드 제거(배치 7단계·팀 EC2 00:10 예약·`ec2_vecstore`의 Chroma 함수만·평가 도구·`ec2_setup.sh`). `run_daily.bat`·`schedule-task.ps1` 되돌리기용 파일 정리.

## 2026-10-07 · Claude · 시험 화면(8000 `/`)에 가산점 표시

- 사용자 요청: 가산점도 8000번 화면에서 시험할 수 있게 한다.
- 바꾼 것: `web/app.html`만 바꿨다. 서버 코드는 그대로다.
  - 추천 카드·목록마다 "확인된 가산점 +N점(일부)", "가산점 없음", "가산점 모름" 중 하나를 보여 준다. 마우스를 올리면 항목이 보인다.
  - 결과 위에 확인된 가산점 있음·없음·모름 건수를 보여 준다.
  - 자격 확인 화면에 가산점 항목과 공고문 가점 원문(`/api/notices/{id}`의 `bonus_info`)을 보여 준다.
  - "시험 단계 · 순위에는 쓰지 않음"을 함께 적었다.
- 확인: 이 PC 8030 임시 서버(끝나고 끔)에서 여성기업·벤처·경기 성남시로 검색했다.
  - 20건 중 확인된 가산점 1건(김포시 120481 +10점)·없음 7·모름 12가 나왔다.
  - 자격 확인 화면에서 "벤처기업 10점"과 가점 원문을 확인했다. 브라우저 오류는 없었다.
  - 시험 884개 중 868 통과·16 건너뜀.
- 시험 서버 반영: `web/app.html` 한 파일만 올리면 된다. 서버가 화면 파일을 요청마다 새로 읽으므로 재시작은 필요 없다. 명령은 아래와 같다(내 PowerShell에서 실행).

```powershell
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
```

```powershell
scp -i C:\Users\playdata2\.ssh\skn32-1team.pem web/app.html ubuntu@43.201.90.238:/tmp/app.html
```

```powershell
ssh -i C:\Users\playdata2\.ssh\skn32-1team.pem ubuntu@43.201.90.238 "cp ~/notice-server/data-collection/web/app.html ~/app_before_20261007.html && cp /tmp/app.html ~/notice-server/data-collection/web/app.html"
```

## 2026-10-07 · Claude · 가산점 재검수 지적 처리(위 항목으로 이어짐)

- 사용자 결정(10/7 오후): ① `bonus_score` = **확인된 가산점 부분합**(결정 0012) ② Codex 재검수(`docs/notice_api/CODEX_BONUS_RECHECK_20261007.md`, "추가 수정 후 재검수 필요" P1 3·P2 3·P3 1)가 짚은 틈은 **모두 null** ③ 재검수 요청서·조율 담당 알림 초안·서버 반영 명령·단위 테스트 결과서 다시 만들기를 함께 한다.
- 바꾼 것:
  - `search/bonus.py`: 근거에 서로 다른 "N점"이 둘 이상이면 점수 없음. 근거가 지금 원문에 그대로 이어져 있지 않으면 모름(`load`가 found 행 원문 확인, 못 읽으면 null·`boot_errors.bonus_documents`). 묶음 오분류 가능성(다른 묶음 같은 근거·점수 / 한 묶음인데 "각")이면 null. found에 불확실 메모가 하나라도 있으면 null. 확인할 수 없는 조건 말(`CONDITION_WORDS`)이면 모름. 머리말을 다시 씀.
  - `search/app.py` boot.
  - `collect/extract_bonus.run_batch`: 잔여량 읽기·예약·기록을 잠금 안에서 함, 겹치면 `bonus_busy`.
  - 시험, `eval/bonus_conservative_compare.py`(`--old`).
  - 기준 문서(9절·창구 약속·결정 0008·0012·`search/AGENTS.md`·진행표).
- 확인:
  - 시험 884개 중 868 통과·16 건너뜀·실패 0.
  - 전후(오전판 → 지금, 공용 DB SELECT만): "가산점 있음" 신청자마다 7 → 3. 양수 → null과 0 → null만 있었다. 117356·122057·122309(불확실 메모)·123858(1점·3점 섞임)이 null, 117928·120481·122147·126642는 그대로 → `reports/bonus_conservative_20261007T024147Z/`.
  - 8030 임시 서버 계약 시험 `--all` 16개 실패 0·2,825건 형식 오류 0 → `reports/notice_api_contract_20261007T024341Z/`.
- 사용자가 할 일:
  1. Codex 재검수 맡기기 — 요청서 `docs/notice_api/CODEX_BONUS_RECHECK2_REQUEST_20261007.md`.
  2. 조율 담당 알림 보내기 — 초안 `docs/notice_api/BONUS_NOTICE_DRAFT_20261007.md`, "화면에 써도 됨"은 넣지 않음.
  3. ~~서버 반영~~ — 완료(아래).
- 단위 테스트 결과서를 새 숫자(884개·범위 621개·커버리지 67.5%)로 다시 만들었다 → `docs/deliverables/[단위 테스트] 공고 데이터·매칭 단위 테스트 결과서.docx`. (워드 창을 닫은 뒤 바꿔 넣음, 내용 확인함)

**서버 반영 완료(10/7 12시경 KST, 사용자 실행).** 바깥에서 확인했다. `/api/health` `boot_errors` 없음(공고·벡터 2,825). `/api/match`로 공고 4곳을 대조했는데 오후 규칙과 같다: 123858 null(예전 코드면 4점), 117356 null, 117928 1점, 120481 10점(여성기업·벤처·경기 성남시). 계약 시험 `--url http://43.201.90.238:8000 --all`은 16개 실패 0·2,825건 형식 오류 0이다 → `reports/notice_api_contract_20261007T030725Z/`. 배치 서버는 10/8 09:00 배치 `run.log`로 확인한다.

**서버 반영 명령** — PowerShell에서 한 줄씩 차례로 실행한다. 한 단계가 끝난 뒤 다음 단계로 간다.

**준비 ① 작업 폴더로 이동**

```powershell
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
```

**준비 ② 바뀐 파일 3개를 한 묶음으로 만들기**

```powershell
tar -czf $env:TEMP\bonus_fix_20261007.tgz search/bonus.py search/app.py collect/extract_bonus.py
```

**시험 서버(팀 EC2) ① 묶음 보내기**

```powershell
scp -i C:\Users\playdata2\.ssh\skn32-1team.pem $env:TEMP\bonus_fix_20261007.tgz ubuntu@43.201.90.238:/tmp/
```

**시험 서버(팀 EC2) ② 이전 파일 보관 → 새 파일 풀기 → 재시작**

```powershell
ssh -i C:\Users\playdata2\.ssh\skn32-1team.pem ubuntu@43.201.90.238 "cd ~/notice-server/data-collection && tar -czf ~/bonus_before_20261007pm.tgz search/bonus.py search/app.py collect/extract_bonus.py && tar -xzf /tmp/bonus_fix_20261007.tgz && sudo systemctl restart notice-server"
```

**배치 서버(sbrain-web) ① 묶음 보내기**

```powershell
scp -i C:\Users\playdata2\.ssh\sbrain-web.pem $env:TEMP\bonus_fix_20261007.tgz ubuntu@13.125.40.88:/tmp/
```

**배치 서버(sbrain-web) ② 이전 파일 보관 → 새 파일 풀기**(재시작 필요 없음. 다음 09:00 배치부터 반영)

```powershell
ssh -i C:\Users\playdata2\.ssh\sbrain-web.pem ubuntu@13.125.40.88 "cd ~/sbrain/data-collection && tar -czf ~/sbrain/_old/bonus_before_20261007pm.tgz search/bonus.py search/app.py collect/extract_bonus.py && tar -xzf /tmp/bonus_fix_20261007.tgz"
```

**확인 ① 시험 서버 상태**(재시작 뒤 약 10초 기다린다)

```powershell
curl.exe -s http://43.201.90.238:8000/api/health
```

결과의 `boot_errors`에 `bonus`·`bonus_documents`가 없어야 한다.

**확인 ② 조율 쪽 코드로 응답 형식 확인**(1분쯤 걸림)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m experiments.notice_api_contract --sbrain "$env:TEMP\sbrain_contract\agent-orchestration" --url http://43.201.90.238:8000 --all
```

마지막 줄이 "실패 0"이어야 한다.

**되돌리기**(문제가 있을 때만): 서버에서 `tar -xzf ~/bonus_before_20261007pm.tgz -C ~/notice-server/data-collection` 뒤 `sudo systemctl restart notice-server`. 배치 서버는 `~/sbrain/_old/bonus_before_20261007pm.tgz`를 `~/sbrain/data-collection`에 푼다.

## 2026-10-07 · Claude · 단위 테스트 보강과 워드 결과서(위 항목으로 이어짐)

- 사용자 요청: 맡은 역할(서비스에 쓰이는 11개 기능)을 단위 테스트로 점검하고 제출용 워드 결과서를 만든다. 커버리지 포함, 기능별 요약 + 대표 사례.
- 새 시험 7개 파일 98개: `tests/test_fetch.py`·`test_attachment_pipeline.py`·`test_hwp5.py`(HWP 샘플 없이 글자 해석만)·`test_upload_vectors.py`·`test_upload_attachments.py`·`test_config.py`·`test_eligibility.py`. 운영 코드·기존 기대값은 그대로. 외부 API·공용 DB·OpenAI 부르지 않음.
- 확인: `coverage run`으로 전체 876개 → 통과 860·실패 0·건너뜀 16(MySQL 통합 시험, 돌리지 않음). 범위 시험 613개, 범위 줄 커버리지 67.2%(7,095줄 중 4,771). 낮은 곳: `ec2/ec2_vecstore.py` 0%·`search/vecstore.py` 17.4%·`fetch_bizinfo` 33.3%·`store_mysql` 36.7%(통합 시험에서만 도는 SQL) → `reports/unit_test_20261007T021113Z/`(요약·파일별·시험별 JSON·실행 기록·측정 스크립트). `coverage`는 이 PC `.venv`에만 설치(의존성 목록 그대로).
- 결과서: `docs/deliverables/[단위 테스트] 공고 데이터·매칭 단위 테스트 결과서.docx`(개요·요약·기능별 표·대표 사례 33개·한계·부록 파일별 커버리지·시험 613개 목록). 글자로 다시 읽어 숫자 대조함.
- 주의(함정): `attachment_pipeline`·`upload_vectors`·`upload_attachments`의 기본 경로는 **함수 정의 때 묶인다** — 시험에서 모듈 상수(`RESULTS`·`NPZ`·`ATTACH`)만 바꾸면 실제 `data/`를 쓴다. 처음 시험이 `data/attachment_results.jsonl`에 가짜 기록 37줄을 만들어 즉시 지웠고(새 파일·가짜 줄만), 시험은 함수 자체를 임시 경로로 돌리고 실제 파일을 건드리면 실패하게 했다.
- 운영 코드 결함은 찾지 못함. `search/app.py` 머리말 `\.venv` 때문에 SyntaxWarning 한 줄(동작 영향 없음).

## 2026-10-07 · Claude · 가산점 "확실한 것만 남기기"(위 항목으로 이어짐)

- 사용자 결정: 재추출 없이 계산 규칙만 줄인다, 순위 반영 0 유지, Codex 재검수 통과 뒤 조율 쪽에 "화면에 써도 됨" 알림, 배치 서버에 가점 추출(14단계)도 붙인다.
- 바꾼 것: `search/bonus.py`(근거의 "N점"만 인정·group으로만 묶기·앞으로의 조건 모름·세부사업 다르면 null·한도 넘으면 null·불확실 읽기 누락이면 null·none+불확실 null·같은 점수 이름순, `uncertain` 읽기), `collect/extract_bonus.py`(호출 기록 깨지면 그날 부르지 않음·원자적 저장), 시험, 새 `eval/bonus_conservative_compare.py`, 기준 문서.
- 확인: 시험 778 통과·16 건너뜀. 전후(열린 공고 1,741, `reports/bonus_conservative_20261007T013412Z/`): 가산점 있음 여성기업·벤처·성남 26→7, 남성·장애인기업·이노비즈·전남광주 21→7, 123858 3→4점, 117751 10→null, 126504 0→null. 8030 임시 서버 계약 시험 16/16(`reports/notice_api_contract_20261007T013609Z/`).
- Codex 재검수 요청서: `docs/notice_api/CODEX_BONUS_RECHECK_REQUEST_20261007.md`(사용자가 맡김).
- **서버 반영 완료(10/7 10:4x KST, 사용자 실행):** ① 팀 EC2 시험 서버 `search/` 덮어 올리고 재시작 → 바깥에서 `/api/health` 오류 없음·계약 시험 15/15(`reports/notice_api_contract_20261007T014601Z/`). ② 배치 서버 `sbrain-web` 코드(`collect·shared·search·experiments·ec2·db`) 덮어씀, 이전 코드는 `~/sbrain/_old/code_before_20261007.tgz`. `extract_bonus --all --plan`: 첨부·가점 말 있는 열린 공고 2,123 · 부를 것 22 · 가점 말 없음 24 · 그대로 2,077 · 예상 약 $0.06. **내일(10/8) 09:00 배치부터 14단계가 돈다** → `run.log`·`notice_bonus` 갱신 시각 확인.
- 재검수 통과 뒤 조율 담당에게 보낼 알림(초안): "가산점은 확실한 경우만 점수를 주고 나머지는 null로 줄였습니다. 합계 한도를 넘는 경우도 자르지 않고 null이며, bonus_items의 점수는 원문 배점 그대로입니다. 순위에는 계속 섞지 않습니다. 이제 화면에 써도 됩니다."

## 2026-10-07 · Claude · 공고 서버 검색에서 벡터 DB(Chroma) 빼기(위 항목으로 이어짐)

- 사용자 요청. 공고 서버가 켤 때 **공용 DB `notices.embedding`을 메모리에 올리고**(새 `search/memvec.py`) 의미 검색을 전부 비교로 계산한다. Chroma를 열지 않는다(PC·팀 EC2 같음). 조율 쪽 응답 키·값 불변. 참고용 표시만 바뀜: `source` `vectors+bm25`, `dense_path` 정상 `memory`, `/api/health`에 `vectors`(건수·버림·지문별 건수).
- 범위는 공고 서버만. 배치 7단계 로컬 Chroma·팀 EC2 09:10 `ec2_vecstore` 예약·Chroma 정합성 도구는 그대로(나중에 정리).
- 확인: 시험 771개 통과·16 건너뜀(새 `tests/test_memvec.py` 13개). 같은 공용 DB 벡터 2,825건으로 만든 임시 Chroma와 비교 `python -m eval.vector_db_compare` → 추천 상위 3 같음 **62/66(93.9%, 기준 90% 통과)**, 의미 검색 상위 10 겹침 99.5%·1위 66/66 → `reports/vector_db_compare_20261007T005123Z/`. 이 PC 8030 임시 서버(끝나고 끔): `boot_errors` 없음, 벡터 2,825건(지문 1종 `0a803d170f58c36e`), 계약 시험 `--all` 16개 통과·2,825건 형식 오류 0 → `reports/notice_api_contract_20261007T005326Z/`.
- 기준 문서 갱신(구조·운영·보안·함정·판정·창구·결정 0010·현황·미해결·`search`/`ec2`/`eval` 안내). "공고 서버는 PC에서만"도 팀 EC2 시험 서버 기준으로 바로잡음. 보안 문서에 "시험 서버만 시험 기간 전체 공개" 예외를 사용자 결정으로 적음.
- **팀 EC2 시험 서버 반영 완료**(10/7 10:1x KST, 사용자가 `search/`만 덮어 풀고 재시작): 서버 안 `/api/health` 벡터 2,825·버림 0·지문 1종·`boot_errors` 없음. 바깥에서 계약 시험 `--url http://43.201.90.238:8000 --all` 16/16, 2,825건 형식 오류 0, 건당 40ms → `reports/notice_api_contract_20261007T011941Z/`.

## 2026-10-07 · Claude · 내용 지문 하루 비교 통과, 답변서 전달(위 항목으로 이어짐)

- 사용자가 05 답변서를 조율 담당에게 **전달했다**(10/7).
- 10/7 09:00 배치 정상(`import_runs` 00:00:03 UTC = 한국 09:00:03), 새 공고 60건(연휴 뒤 첫 유입).
- `python -m search.content_version --compare data/notice_api/content_version_20261006_cv2.json` → 공통 2,765건 중 바뀜 14건(`recruitment_status` 13 — K-Startup 모집 종료, `title` 1 — `kstartup:179350` 제목에 "(수정)" 붙음), 추가 60·삭제 0. **모두 실제 내용 변화이고 날마다 바뀌는 칸은 없다 → `cv2-` 그대로 확정**(cv3 불필요). 조율 담당에게는 "잠정 → 확정"만 알리면 된다.

## 2026-10-06 · Claude · 팀 EC2에 공고 서버(시험 서버) 올림 · 답변서에 주소 반영(위 항목으로 이어짐)

- **팀 EC2(43.201.90.238)에 공고 서버를 올렸다**(사용자 작업, Claude 안내). 주소 `http://43.201.90.238:8000`(`/docs`). 코드는 이 PC `data-collection/`의 `search·shared·ec2·collect·experiments·web` + 판정 결과 3개를 `~/notice-server/data-collection/`에 **복사**한 것(git 아님 — PC에서 고치면 다시 복사해야 반영). 파이썬 환경은 기존 `~/s-brain/.venv`, DB 설정은 `~/s-brain/.env`를 `ec2/.env`·`.env`로 복사, 색인은 `VECSTORE_PATH=/home/ubuntu/s-brain/data/vecstore/chroma`(매일 09:10 기존 예약이 갱신).
- 상시 실행: systemd `notice-server`(enabled, 죽으면 다시 켬), 매일 한국 09:20 재시작 `/etc/cron.d/notice-server-restart`. 켜는 데 약 8초. **처음에 시험 실행이 8000을 쥐고 있어 상시 실행이 65번 켜졌다 죽기를 반복했다** → 시험 실행을 끄고 다시 켜 정상(MainPID가 8000을 쥠).
- 보안그룹 8000은 **전체 공개(사용자 결정: 시험 기간만)**. 인증 없음. 위험(누구나 호출, `/demo`·`/api/match_rerank` 같은 시연 창구가 큰 모델을 올려 같은 서버의 팀 MySQL이 메모리 부족으로 멈출 수 있음)은 설명함. 실제 연결 전 IP 제한으로 바꾼다.
- 계약 시험(조율 쪽 `b8e7f50` 코드, 인터넷으로): 15개 통과, 추천 약 0.8초 → `reports/notice_api_contract_20261006T084646Z/`.
- 답변서(`notice_api/05_reply/README.md`) 고침: 시험 서버 주소·접속 조건·매일 09:20 재시작(약 10초 응답 불가, 09:00~09:20 "지연" 가능)·시험 결과, 어긋나던 문장(주소 없음·함께 시험 미정·PC 색인 10/2) 정리.
- 남은 일: 기준 문서(구조·운영·보안·함정·현황)에 "공고 서버는 PC에서만" → 팀 EC2 시험 서버로 갱신(이번 범위 밖), 실제 연결 전 8000 IP 제한, 메모리 여유 점검(`free -h`).

## 2026-10-06 · Claude · 공고 서버 API — 05 답변서 작성(위 항목으로 이어짐)

- [05 답변서](notice_api/05_reply/README.md)를 썼다. 조율 담당에게 보내는 일은 사용자가 한다. 코드·DB·서버 변경 없음.
- 사용자가 정한 답: 가산점은 **시험 단계 — 화면에 쓰지 말아 달라**, 지금은 순위에 섞지 않음(정리 방법은 연결 전에 알림), 가점 원문 `bonus_info`는 써도 됨 · **생년월일은 아직 보내지 말아 달라** · `support_amount_text`는 늘 null · 운영(배포 위치·인증·동시 호출·재시작)은 미정 + 아는 사실만 · 공개 시험 서버는 없음(04 계약 시험으로 대신) · 수집 상태 판정의 지금 한계(배치 일지를 못 봄) 밝힘 · 질문 10(양식·평가 항목)은 계획 없음 · 지금 보내되 내용 버전은 잠정.
- 남은 일: 10/7 09:00 배치 뒤 내용 지문 비교(바뀌면 조율 담당에게 **먼저** 알림), 가산점 정리 방법 결정, 배포 위치 결정(접속 주소·인증·재시작 중 응답·함께 시험 방법이 여기에 달림), 서버 배치 코드 다시 복사.


## 2026-10-06 · Claude · 공고 서버 API — Codex 재검수 지적 보류 결정, 04 완료, 05 대기(위 항목으로 이어짐)

- [Codex 재검수](notice_api/CODEX_REVIEW_RECHECK_20261006.md) 결론 "추가 수정 후 재검수 필요"(P1 1·P2 6·P3 2, 01·02·최신성은 통과). **사용자 결정: 개선 보류, 04·05 진행.** 조건: 실제 연결 켜기 전 가산점을 고치거나 모두 null로, 05 답변서에 "가산점 시험 단계" 명시. 근거·조건은 [notice_api/README.md](notice_api/README.md) "10/6 오후 사용자 결정".
- **K-Startup 가산점 null 유지(사용자 결정 ③).** 첨부 경로 `/afile/`는 robots.txt 자동 수집 금지, 공공데이터포털 API 4종에 첨부 칸 없음·우대 사항 칸 비어 있음(10/6 직접 호출).
- **04 완료**([기록](notice_api/04_contract_test/README.md)): 조율 쪽 실제 코드로 8000을 HTTP 호출, 16개 확인 통과, 모든 공고 G-01 2,765건 형식 오류 0. `experiments/notice_api_contract.py`.
- 판정표 페이지(공유용, 비공개): https://claude.ai/artifact/XdbvF8DhvHBH9LEtv71eJm (v4 기준 실제 계산 값).
- 다음: 05 답변서 — 사용자가 **새 세션**에서 진행. 진입점 [NEXT_SESSION_HANDOFF_20261006.md](archive/NEXT_SESSION_HANDOFF_20261006.md)(이전 인계서는 `archive/`로 옮김).
- 작업 흐름 페이지(비공개): https://claude.ai/artifact/MP9WGh7sM3P2jZGS6tSDe8

## 2026-10-06 · Claude · Codex 검수(01~03) 반영 — 재검수 완료(위 항목으로 이어짐)

- [Codex 검수](notice_api/CODEX_REVIEW_20261006.md)는 "수정 후 재검수 필요"(P1 2·P2 8·P3 3)였다. 13건 모두 코드에서 확인했고 모두 반영했다. 응답·재검수 요청은 [CODEX_REVIEW_RESPONSE_20261006.md](notice_api/CODEX_REVIEW_RESPONSE_20261006.md)에 있다. **사용자가 Codex에 재검수를 맡기면 된다.**
- 핵심 변경
  - 가점 추출기 v4: group·program·extra_conditions·points_source, 근거 실제 위치, 연번·부정어 제외, 가점 구간 먼저 12,000자, 우대까지 대상.
  - 가산점 계산: 묶음은 한 번만, 세부사업별 최대, 추가 조건이면 모름, 한도는 큰 항목부터.
  - 최신성: `notice_bonus.content_version`.
  - 내용 지문 `cv2-`(지금 달린 첨부만), 저장 시각 모름 → 지연, 하루 상한은 한국 날짜 기준.
  - **순위 세기 `Weights.bonus` 기본 0.**
- **공용 DB 변경(이번 작업):** `notice_bonus`에 `content_version` 칸 추가([마이그레이션 008](../db/mysql_migration_008_notice_bonus_content_version.sql)). 가점 전량을 v4로 재추출해 2,078행을 저장했다(LLM 969, 실패 0, 약 $1.79). 표본 30건 재추출 3회 약 $0.20.
- 검증: 전체 시험 758 통과(건너뜀 16). 서버 읽기 점검에서 지문·버전이 달라 뺀 행은 0. 가상 신청자별 분포는 응답서 3절에 있다.
- 남은 일
  - Codex 재검수.
  - **10/7 09:00 배치 뒤** `python -m search.content_version --compare data/notice_api/content_version_20261006_cv2.json`(cv1 파일 아님).
  - 서버 `sbrain-web` 배치 코드 다시 복사(14단계·v4는 아직 서버에 없음, 사용자 결정).
  - 04(조율 쪽 코드로 불러 보기)·05(답변서 — P3-2 `certifications=[]` 의미, P3-3 항목 점수 정의 포함).
- 이 PC 8000은 2026-10-06 13:07 KST(04:07 UTC)에 **v4 코드·데이터로 다시 켰다**(사용자 요청). 시작 오류 없음, 내용 지문 `cv2-`, N07 상세에 가점 원문 확인. 끄기 전 사용자 확인.

## 2026-10-06 · Claude · 공고 서버 API(조율 요청) — 01·02·03 완료, Codex 검토 대기

- **03 가산점 완료**([기록](notice_api/03_bonus/README.md)): 공용 DB `notice_bonus`(2,057행, 10/6 사용자 승인으로 생성), 추출 약 $1.05 + 표본 $0.08. 신청자별 가산점(`search/bonus.py`), 순위 반영 기본 세기 0.2, 매일 배치 14단계(코드만).
- **Codex 검토 요청서:** [notice_api/CODEX_REVIEW_REQUEST_20261006.md](notice_api/CODEX_REVIEW_REQUEST_20261006.md) — 사용자가 맡긴다. 결과는 같은 폴더 `CODEX_REVIEW_20261006.md`.
- **서버 배치 주의:** `sbrain-web` 배치는 10/2 복사본 코드라 14단계(가점)가 돌지 않는다. 넣으려면 서버에 코드 다시 복사(사용자 결정). 그 전까지 새 공고의 가점은 손으로 `python -m collect.extract_bonus --all`.
- 이 PC 8000 서버는 10/6 Claude가 01·02 코드로 켠 것(가산점 없음). 끄거나 다시 켜기 전 사용자 확인.

- **02 완료**([기록](notice_api/02_detail_eligibility/README.md)): `GET /api/notices/{id}`, `POST /api/notices/{id}/eligibility`. 판정 코드는 `search/eligibility.py` 한 곳(화면용과 함께 씀, 결과 불변 확인). 실제 데이터 13,825회 추천 필터와 결론 일치. 시험 713 통과.

- 조율 담당(4nchez)의 요청서(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`)대로 공고 서버에 HTTP 창구를 연다. 전체 계획·진행표는 [notice_api/README.md](notice_api/README.md), 작업별 기록은 `docs/notice_api/0N_*/`.
- 사용자 결정(10/6): 작업을 01~05로 나눠 하나씩 진행, 가산점은 실제로 만든다, 서버 위치는 나중에, 답변서는 마지막.
- **01 완료**([기록](notice_api/01_status_match/README.md)): `GET /api/collection_status`, 추천 결과에 `content_version`·`bonus_score`(null)·`bonus_items`([]). 시험 702 통과.
- **10/7 09:00 배치 뒤 할 일:** `python -m search.content_version --compare data/notice_api/content_version_20261006.json`으로 지문이 수집 잡음 없이 유지되는지 확인.
- 참고: 10/6 09:00 서버 배치 저장 확인(import_runs 00:00 UTC). 이 PC 8000은 옛 코드라 새 창구를 쓰려면 다시 켜야 한다.
- **10/6 "수집이 10/3에서 멈춘 것 같다" 점검 — 장애 아님.** 서버 `sbrain-web` 배치는 10/3~10/6 매일 `exit=0`·저장 성공. 새 공고가 10/4~10/6 0건인 것은 API에 새 공고가 없어서다: 기업마당 원본 등록일(`creatPnttm`) 최신이 10/2(금), 평일에만 올라오고 9/24~27 추석에도 0건. 10/3(토 개천절)·10/4(일)·10/5(월 대체공휴일) 연휴. 10/6 09:50 KST 직접 조회에도 10/6 등록분은 아직 없음(전날 공고가 다음 날 API에 잡히는 패턴). **10/7 09:00 배치에서 새 공고가 들어오는지 확인**한다.

## 2026-10-02 · Claude · 매일 배치 서버 전환 — 10/3 09:00 첫 실행 점검 필요

- **매일 수집 배치가 이제 이 PC 가 아니라 서버에서 돈다.** 서버: 개인 AWS 계정의 EC2 `sbrain-web`(c7i-flex.large 4GB, Ubuntu 26.04, Docker). 예약: crontab `0 0 * * *`(UTC 00:00 = 한국 09:00) → `deploy/run_batch.sh` → `batch` 컨테이너에서 `python -m collect.daily_pipeline`.
- **PC 작업 스케줄러 `S-Brain-DailyCollection` 은 사용 안 함으로 바꿨다**(지우지 않음). 이 PC 의 `data/run.log` 는 10/2 09:05 에서 멈춘다. 이후 로그는 서버 `~/sbrain/data-collection/data/run.log` 에 있다.
- 서버 코드는 10/2 10:54 에 이 PC 작업 폴더를 복사한 것이다(미커밋 수정 포함). **이 PC 에서 data-collection 코드를 고쳐도 서버에는 반영되지 않는다.** 다시 복사해야 한다.
- 이 PC 의 8000 은 이 PC `data/` 의 색인을 읽는다. 그래서 새 공고가 색인에 들어오지 않는다. 필요하면 서버 `data/` 를 받아 온다.
- 시험(10/2, DB 쓰기 0·비용 $0): dry-run 두 번 `exit=0`(예약과 같은 빈 환경 포함), 팀 DB 암호화 SELECT 성공, BGE-M3 리비전 `5617a9f…` 고정으로 설정 지문 `0a803d170f58c36e` 가 PC 와 같다(전량 재임베딩 없음), 112건 임베딩 110초·여유 메모리 최저 2,058MB.
- 다음 단계: **10/3 09:20 쯤 서버 run.log·`import_runs`·건수를 PC 때처럼 점검**한다. 정상이면 서버의 `~/sbrain/_old/data_test_20261002` 를 지운다. 되돌리는 방법·구성은 [deploy/README.md](../../deploy/README.md) "매일 수집 배치" 절.

---

2026-09-30 이전 항목과 그때의 고정 절(합의 범위·검증 상태·대기 작업)은 [archive/STATUS_202609.md](archive/STATUS_202609.md)로 옮겼다(2026-10-07).
