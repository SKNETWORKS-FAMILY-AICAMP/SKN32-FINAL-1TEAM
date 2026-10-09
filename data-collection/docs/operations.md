# 실행과 운영

모든 명령은 `data-collection/` 폴더에서 PowerShell로 실행한다(따로 적은 것 제외).

## 1. 처음 준비

전제: Windows, Python 3.12, 팀 DB 접속 정보와 CA 파일, API 키.

```powershell
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env          # 아래 3절 값을 채운다
```

- `.env`를 채우기 전에는 수집·DB 명령이 "환경변수 … 가 없습니다"로 끝난다.
- 학습(`ml/`)도 할 PC만: `pip install -r requirements-ml.txt` 뒤 torch를 GPU 판으로 따로 설치한다(`pip uninstall -y torch` → `pip install torch --index-url https://download.pytorch.org/whl/cu124`, 확인 `python -c "import torch; print(torch.cuda.is_available())"`).
- 빈 DB를 처음 만들 때만: 먼저 `… -m collect.daily_pipeline --dry-run`으로 정규화 파일(`data/normalized/notices_*.json`)을 만든 뒤 `.\.venv\Scripts\python.exe -X utf8 -m shared.store_mysql data\normalized\<파일> --init-db`(DB와 없는 테이블을 만들고 그 파일을 저장한다, DDL 권한 필요). 이어서 `db/mysql_migration_002…008`을 번호 순서대로 손으로 적용한다(앞 번호가 만든 테이블·칸을 뒤 번호가 쓴다). 입력 검증만 하려면 `--check`. **팀 공용 DB에는 이미 적용돼 있으니 다시 돌리지 않는다.**

## 2. 자주 쓰는 명령

| 하는 일 | 명령 | 부작용 |
|---|---|---|
| 시험 전체 | `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests` | 없음 |
| MySQL 통합 시험까지 | `$env:MYSQL_INTEGRATION_TEST='1'` 뒤 위 명령 | 시험용 DB 쓰기 |
| 배치 수집·정규화만 | `.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline --dry-run` | API 호출만, DB 쓰기 없음 |
| 배치 전체(손으로) | `.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline` | **공용 DB 쓰기·LLM 비용** — 사용자 승인. 서버 배치와 같은 날 겹치지 않게 한다 |
| 공고 서버 | `.\.venv\Scripts\python.exe -X utf8 -m search.app` → `http://127.0.0.1:8000` (창구 시험 화면 `/docs`). 다른 포트는 `$env:PORT='8030'` | 켤 때 약 35초(PC)·메모리 약 2GB. 공용 DB 벡터를 메모리에 올린다 |
| 검증 화면 | `.\.venv\Scripts\python.exe -X utf8 -m experiments.sql_semantic.viewer` → `http://127.0.0.1:8010` (`/flow` 전체 흐름) | 읽기만. `/compare`는 8000을 부른다 |
| 판정 화면 | `.\.venv\Scripts\python.exe -X utf8 eval\label_app.py` → `http://127.0.0.1:8001` | 사람 판정 파일 쓰기 |
| 첨부 대상만 세기 | `.\.venv\Scripts\python.exe -X utf8 -m collect.attachment_pipeline --plan` | 없음 |
| 가점 재추출 계획 | `.\.venv\Scripts\python.exe -X utf8 -m collect.extract_bonus --all --plan` | 없음(부르지 않음) |
| 내용 지문 저장·비교 | `… -m search.content_version --save <파일>` / `--compare <파일>` | DB 읽기만 |
| 공유 HTML 다시 만들기 | `.\.venv\Scripts\python.exe -X utf8 share\build_<이름>.py` | 파일만 |

저장소 루트 `.claude/launch.json`에 `search-service`(8000)·`verify-viewer`(8010)가 등록돼 있다.

배치 명령줄 옵션: `--dry-run` · `--skip-store` · `--skip-attach` · `--attach-limit N` · `--attach-interval S` · `--skip-embed` · `--embed-limit N` · `--skip-upload` · `--skip-files` · `--force`(건수 급감 경고 무시) · `--skip-conditions` · `--conditions-limit N` · `--skip-applicant-types` · `--applicant-types-limit N` · `--skip-industries` · `--industries-limit N` · `--skip-judgments` · `--skip-bonus` · `--bonus-limit N`.

## 3. 환경 변수

`.env`(PC: `data-collection/.env`)에 둔다. 이미 설정된 환경 변수가 `.env`보다 우선한다.

| 이름 | 쓰는 곳 | 뜻·주의 |
|---|---|---|
| `KSTARTUP_KEY` | 배치 1단계 | 공공데이터포털 **디코딩** 인증키 |
| `BIZINFO_KEY` | 배치 2단계 | 기업마당 `crtfcKey`. 위와 다른 값 |
| `MYSQL_HOST`·`MYSQL_PORT`·`MYSQL_DATABASE`(`s_brain`)·`MYSQL_USER`·`MYSQL_PASSWORD` | 배치·서버·평가 | 팀 공용 DB |
| `MYSQL_SSL_CA` | 위와 같음 | CA 파일 경로(PC `data/ec2-ca.pem`). 팀 DB는 필수 |
| `MYSQL_SSL` | 위와 같음 | `1`이면 CA 없이 암호화만 |
| `OPENAI_API_KEY` | 배치 10~14단계, LLM 실험 | 개인 결제 계정 키. 없으면 LLM 단계를 건너뛴다. `.env.example`에는 아직 없다 |
| `TYPESAFE_API_KEY`·`JUDGE_MODEL` | `eval/jev_judge_probe` 등 평가 | 평가 전용 |
| `PORT` | 공고 서버 | 기본 8000 |
| `VECSTORE_PATH` | `ec2/ec2_vecstore.py` | Chroma 위치. 기본 `ec2/data/vecstore/chroma`. 공고 서버는 2026-10-07부터 읽지 않는다 |
| `APPLICANT_TYPES_SOURCE`·`APPLICANT_TYPES_RESULTS` | 공고 서버 | 신청자 유형 판정 출처 `auto`(기본, DB→파일)·`db`·`file`, 파일 경로 |
| `INDUSTRY_SOURCE`·`INDUSTRY_RESULTS` | 공고 서버 | 업종 판정 출처 `file`(기본)·`auto`·`db`, 파일 경로(기본 `reports/industry_llm_full_luna_20260928_final5/results.jsonl`) |
| `AGE_RERUN_RESULTS` | 공고 서버 | 업력 근거 파일 경로 |
| `SQL_LAB_HOST`·`SQL_LAB_PORT`·`SQL_LAB_USER`·`SQL_LAB_PASSWORD`·`SQL_LAB_DATABASE` | `experiments/sql_semantic` | 로컬 실험 DB. 하나라도 없으면 실험 DB에 연결하지 않는다 |
| `SERVICE_URL` | 검증 화면 | 비교할 공고 서버(기본 `http://127.0.0.1:8000`) |
| `MYSQL_INTEGRATION_TEST` | 시험 | `1`이면 MySQL 통합 시험 실행 |
| `HF_HUB_OFFLINE` | 임베딩 | 코드가 `1`로 둔다. 모델을 처음 받을 때만 풀어야 한다 |

배치 서버 `.env`는 배치용 키 8개만 담고, compose가 `MYSQL_SSL_CA=/app/secrets/ec2-ca.pem`·`HF_HUB_OFFLINE=1`로 덮는다.

## 4. 매일 배치 운영 (서버)

- 서버: 개인 AWS EC2 `sbrain-web`(13.125.40.88, c7i-flex.large 4GB, Docker). SSH 키 `C:\Users\playdata2\.ssh\sbrain-web.pem`, 22번은 사용자 IP만.
- 예약: 서버 crontab `0 0 * * * /home/ubuntu/sbrain/deploy/run_batch.sh` (한국 09:00).
- 구성: 저장소 루트 `deploy/batch.Dockerfile`(Python 3.12 + CPU torch), `deploy/batch-requirements.txt`, compose `batch` 서비스(profile이라 `compose up`으로는 안 켜짐). 코드·`data/`·`.env`는 서버 `~/sbrain/data-collection`을 그대로 붙이고, BGE-M3는 볼륨 `sbrain_hf_cache`.
- 손으로 돌리기(서버에서): `bash deploy/run_batch.sh --dry-run`(DB 쓰기 없음) / `bash deploy/run_batch.sh`(실제).
- 로그: 서버 `~/sbrain/data-collection/data/run.log`(시작·`exit=` 줄), `collect_log.jsonl`.
- **서버 코드 갱신**: PC 작업 폴더를 서버 `~/sbrain/data-collection`으로 다시 복사한다(사용자 결정 뒤). 복사 범위에 `experiments/`, 서버가 읽는 `reports/` 결과 파일, `db/`가 들어가야 한다. 서버 `data/`와 `.env`는 덮지 않는다.
- **PC로 되돌리기**: ① 서버 `crontab -e`로 그 줄을 지운다 ② PC에서 `Enable-ScheduledTask -TaskName S-Brain-DailyCollection` ③ 서버 `data/`를 PC로 받아 온다(서버가 돈 날이 있으면). 순서를 바꾸면 같은 날 두 곳에서 배치가 돌 수 있다(잠금은 각자 `data/collection.lock`이라 서로 못 막는다).
- PC 예약 작업 관리(되돌린 경우): `.\schedule-task.ps1`(미리보기) · `-Mode Install [-At 09:00]` · `-Mode Status` · `-Mode Run` · `-Mode Uninstall`. 예약이 부르는 것은 `run_daily.bat`이고 `data/run.log`에 시작·종료를 남긴다.

## 5. 팀 EC2 (공용 DB)

- 호스트 43.201.90.238(계정 `ubuntu`, SSH 키 `C:\Users\playdata2\.ssh\skn32-1team.pem`, 22번은 사용자 IP만). MySQL `s_brain`과 공고 시험 서버가 같은 서버에 있다. 4GB + 스왑 2GB(스왑은 메모리 부족 때 `mysqld`가 죽는 것을 막는 안전망).
- **백업(이 PC에서, 손으로):** `.\.venv\Scripts\python.exe -X utf8 -m collect.backup_db --include-files` → `data/backup_<시각>.sql`(Git 제외). 공용 DB를 읽기만 하고(한 시점 스냅샷), 우리 테이블 9개(공고 4 + AI 판정 4 + 첨부 원본)만 담는다. 다른 팀 테이블(회원·토큰 등)은 넣지 않는다. 2026-10-07 기준 약 1.7GB(첨부 원본이 16진 글자라 커짐), 1분 남짓. 첨부 원본을 빼면(`--include-files` 없이) 훨씬 작다. 마지막 백업: `data/backup_20261007T165318.sql`(10/7, gpt-6-luna로 다시 뽑기 직전, 첨부 원본 제외) · `data/backup_20261007T153141.sql`(10/7, 첨부 원본 포함). 9/14 백업은 휴지통으로 보냄. 복원은 `DROP TABLE` 뒤 다시 만드는 SQL이라 **공용 DB에 바로 넣지 않는다** — 먼저 사용자와 정한다.
- **AI 모델 바꾸기(결정 0013 방식):** ① `-m eval.model_switch_compare --plan` → 실제 실행으로 단계별 40건 비교(공용 DB 쓰기 없음) ② 승인 뒤 각 모듈의 `MODEL` 상수만 바꾼다(11·12단계는 엔진이 다르면 저절로 다시 뽑는다, 14단계는 추출기 버전이 바뀌어 다시 뽑는다) ③ PC에서 `-m collect.backup_db` + 배치 서버 `data/applicant_types`·`data/industries` 압축 ④ 배치 서버에 코드 복사 → `applicant_type_daily --limit 3500`·`industry_daily --limit 3500`(오늘 부른 수 포함 상한)·`upload_judgments`·`extract_bonus --all` ⑤ 시험 서버에 코드 복사·재시작(가점은 서버가 새 추출기 버전만 읽는다) ⑥ 계약 시험. **되돌리기:** 서버 코드·판정 파일은 `_old/` 압축으로, 공용 DB AI 표만 `-m collect.backup_db --restore <백업> --tables notice_bonus,…`(계획만) → `--apply`(사용자 승인 뒤). `--apply`는 표를 지우고 다시 만들어서 백업 뒤에 들어온 새 공고의 판정 행도 사라진다(다음 매일 배치가 다시 채운다). 중간에 끊기면 일부 표만 되살아나니 같은 명령을 다시 실행한다.
- 예전 색인 갱신: crontab `10 0 * * *`(한국 09:10)에 `ec2_vecstore.py`(증분). 공고 서버는 더 쓰지 않지만 지우지 않았다(나중에 정리). 전체 재생성은 `--rebuild`, 상태는 `--stat`.

## 6. 공고 서버 운영

- **시험 서버**: 팀 EC2 `http://43.201.90.238:8000`(조율 담당에게 주소 전달함, 시험 기간만 전체 공개·인증 없음). 운영 서버 위치는 미정(조율 요청서는 AWS 내부망).
  - 상시 실행: `sudo systemctl status notice-server` / `restart` / `journalctl -u notice-server -n 30`. 설정 `/etc/systemd/system/notice-server.service`(작업 폴더 `~/notice-server/data-collection`, `~/s-brain/.venv/bin/python -m search.app`, `HF_HUB_OFFLINE=1`). 켜는 데 약 8초.
  - 매일 한국 09:20 재시작(`/etc/cron.d/notice-server-restart`). 09:00 배치 저장 뒤 09:20 재시작 전까지는 수집 상태가 `지연`일 수 있다.
  - 코드 갱신: 이 PC `data-collection/`에서 바뀐 폴더를 `tar -czf`로 묶어 `scp` → 서버에서 `~/notice-server/data-collection/`에 덮어 풀기 → `sudo systemctl restart notice-server`. DB 설정은 서버의 `ec2/.env`(=`~/s-brain/.env` 복사본)라 덮지 않는다.
  - 8000을 손으로 따로 켜 둔 채 상시 실행을 켜면 "포트 사용 중"으로 죽기를 반복한다(`NRestarts`가 늘어남). 손으로 켠 것을 먼저 끈다.
- 이 PC 개발 서버: 배치 뒤 새 공고를 반영하려면 **다시 켠다**. 켜기 전·끄기 전에 사용자에게 확인한다.
- 켠 뒤 확인: `/api/health`의 `boot_errors`가 비었는지, `notices`·`indexed`(올린 벡터 수)·`vectors.fingerprints`·`bm25_indexed`, `applicant_types.active`.
- 조율 쪽이 부르는 창구: `/api/collection_status`·`/api/match`·`/api/notices/{id}`·`/api/notices/{id}/eligibility`.
- **가산점 순위 반영 목록(결정 0017)** — `search/bonus_reviewed.json`(원문 대조를 마친 공고만 순위에 얹음, 기본 세기 0.2). 켠 뒤 확인: `/api/health` `boot_errors`에 `bonus_reviewed`가 없어야 한다(있으면 목록 전체 미사용, 순위 반영 0건).
  - 목록 추가(사용자가 요청할 때, 발표 전 주 1~2회 권장): PC에서 `.\.venv\Scripts\python.exe -X utf8 -m eval.bonus_boostable` → 결과의 "새 후보"·"다시 대조 필요"를 Claude가 원문과 대조 → "맞음"만 `... -m eval.bonus_boostable --write-reviewed <공고ID …> --note "<근거>"`(지문·승인 항목은 도구가 채운다 — 손으로 쓰지 않는다) → 시험 서버에 `search/bonus_reviewed.json`만 올리고 `notice-server` 재시작. 목록 추가 때마다 조율 담당에게 알리지는 않는다.
  - 공고문이 바뀌거나, 가점을 다시 뽑거나, 첨부 글을 다시 뽑으면(원문 지문 — 결정 0018) 그 공고는 지문이 달라져 자동으로 순위 반영·"원문 대조됨"이 멈춘다("다시 대조 필요"로 보임). 화면 표시도 같이 빠진다.
  - 목록 파일 값이 이상하면(지문 빠짐, 점수가 글자·음수 등) 공고 서버가 목록 전체를 쓰지 않는다 — `boot_errors.bonus_reviewed` 확인.
  - 되돌리기: 빠르게 — 목록 파일을 `{"version": 1, "notices": {}}`로 올리고 재시작(순위 반영 0건, 표시는 그대로). 완전히 — `~/_old/`의 묶음으로 `search/bonus.py`·`search/app.py`·`search/bonus_reviewed.json`·`web/app.html`을 되돌리고 재시작.
