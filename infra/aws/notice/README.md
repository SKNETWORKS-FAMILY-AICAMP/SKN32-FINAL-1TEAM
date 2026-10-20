# 공고 서버 올리기 (infra/aws/notice)

`up.sh`가 만든 공고 서버(사설망, 내부 주소 `10.20.11.10`)에 공고 서버 앱(`data-collection/search/app.py`, 8000번)과 매일 수집 배치(`collect.daily_pipeline`)를 올린다. 서버 · DB는 [../README.md](../README.md)의 `up.sh`로 먼저 만든다.

```bash
bash infra/aws/up.sh             # 1. 서버 · DB (처음, 그리고 템플릿이 바뀌었을 때)
bash infra/aws/deploy-notice.sh  # 2. 공고 서버 · 매일 배치 (코드를 바꿀 때마다)
bash infra/aws/app-env.sh        # 3. 웹 · 워커 비밀 값 — SBRAIN_NOTICE_API_URL=http://10.20.11.10:8000
bash infra/aws/deploy-app.sh     # 4. 웹 · 워커
```

`deploy-app.sh`와 같은 방식이다. PC에서 커밋 하나를 묶어 S3에 올리고, 서버에서 설치 스크립트를 원격 실행(SSM)으로 돌린다. SSH · GitHub 키가 필요 없다. 옵션 `--profile` · `--region` · `--stack` · `--yes`도 같다. 윈도우는 Git Bash에서 실행한다.

## 처음 한 번만

1. **템플릿 권한 반영:** 공고 서버가 수집 키와 코드 묶음을 읽는 권한(`NoticeAppPolicy`)이 템플릿에 있다. 이미 만든 스택이면 `up.sh`를 한 번 더 실행해 반영한다. 서버는 새로 만들어지지 않는다.
2. **수집 키 세 개:** 처음 실행할 때 묻는다. 입력하는 글자는 보이지 않는다.

   | 이름 | 쓰는 곳 |
   |---|---|
   | `KSTARTUP_KEY` | 1단계 K-Startup 수집 (data.go.kr **디코딩** 키) |
   | `BIZINFO_KEY` | 2단계 기업마당 수집 |
   | `OPENAI_API_KEY` | 10 ~ 14단계 LLM 추출 |

   값은 SSM Parameter Store `/<스택>/notice/<이름>`(SecureString)에 둔다. 이미 있으면 다시 묻지 않는다. 바꿀 때: `bash infra/aws/deploy-notice.sh --reset OPENAI_API_KEY`. `down.sh`는 이 값을 지우지 않는다.

3. **데이터 옮기기(선택, 권장):** 새 DB는 비어 있다. 처음부터 배치를 돌리면 모든 공고에 LLM 추출을 다시 한다(비용 · 시간). 팀 EC2의 데이터를 옮기려면 두 파일을 만들어 함께 넘긴다.

   ```bash
   # 매일 배치를 돌리던 서버에서 — 신청자 유형 · 업종 누적 결과, 첨부 파일
   tar -czf data.tar.gz -C <data-collection 폴더> data
   # 팀 EC2 DB 에 닿는 PC 에서 — 공고 · 판정 표 8개 (--include-files 는 쓰지 않는다)
   python -m collect.backup_db --out backup.sql
   ```

   ```bash
   bash infra/aws/deploy-notice.sh --data data.tar.gz --restore-db backup.sql
   ```

   - 그날 매일 배치가 끝난 뒤에 만든다. 수집 상태는 마지막 저장이 24시간 안이어야 '정상'이다.
   - DB는 **공고 표 8개가 모두 비어 있을 때만** 넣는다. 표는 `up.sh`가 이미 만들었으므로 백업의 `DROP` · `CREATE`는 건너뛰고 `INSERT`만 한 트랜잭션으로 넣는다(중간에 실패하면 하나도 남지 않는다).
   - 첨부 원본(`attachment_files`)은 넣지 않는다. 매일 배치 9단계가 `data/attachments`에서 다시 올린다.
   - 한 번 옮기면 서버에 표시가 남아, 같은 옵션으로 다시 실행해도 두 번 넣지 않는다. 옮긴 파일은 끝나면 S3에서 지운다.
   - 묶음 안의 `.env` · `*.lock` · `backup_*.sql`은 풀지 않는다.
   - **옮긴 뒤에는 옛 배치 서버의 매일 예약을 끈다.** 두 곳에서 돌면 같은 날 배치가 두 번 돈다.

## 서버에서 하는 일

[install-notice.sh](install-notice.sh)가 root로 돈다. 몇 번을 다시 실행해도 안전하다.

1. **계정 · 폴더:** 서비스 계정 `sbrain-notice`, 데이터 폴더 `/var/lib/sbrain-notice/data`. 코드의 `data-collection/data`가 이 폴더를 가리키므로 코드를 다시 올려도 배치 누적 결과가 남는다.
2. **설정:** Parameter Store의 수집 키 → `/etc/sbrain/notice.env`(root만 읽음). DB 접속은 `up.sh`가 만든 `/etc/sbrain/db.env`(`MYSQL_*` · `MYSQL_SSL_CA`)를 그대로 쓴다.
3. **코드 · 가상환경:** `/opt/sbrain-notice/releases/<이름>/`에 풀고 그 안의 `.venv`에 CPU 판 torch 2.14.0과 [requirements-notice.txt](requirements-notice.txt)를 깐다. `/opt/sbrain-notice/current`가 지금 코드를 가리킨다.
4. **BGE-M3:** 처음 한 번 계정 홈(`~/.cache/huggingface`, 약 2.3GB)에 받는다. 서비스는 켤 때 인터넷에 묻지 않는다(`HF_HUB_OFFLINE=1`).
5. **(옵션) 데이터 옮기기:** 위 3번.
6. **서비스 바꾸기:** `notice-server`를 새 코드로 다시 띄우고 `/api/health`를 기다린다. **5분 안에 응답이 없으면 바로 앞 코드로 되돌리고 멈춘다.** 켜진 뒤 공고 수 · 벡터 수 · 수집 상태를 보고한다.
7. **매일 배치:** `notice-batch.timer`가 매일 **한국 09:00**에 배치를 돌리고, 배치가 끝나면(성공 · 실패 모두) 공고 서버를 다시 띄워 새 공고를 올린다. 다시 켜는 수십 초 동안 공고 추천이 멈춘다. `--run-batch`를 주면 올린 뒤 한 번 바로 시작한다(기다리지 않는다).

PC 쪽은 마지막에 **웹 서버에서** `http://<공고 서버 주소>:8000/api/collection_status`를 불러 `200`인지 확인한다.

## 서버에서 볼 것

```bash
ssh -F infra/aws/.out/sbrain-ap-northeast-2/ssh_config sbrain-notice
```

| 보고 싶은 것 | 명령 |
|---|---|
| 공고 서버 상태 · 기록 | `systemctl status notice-server` · `journalctl -u notice-server -n 100` |
| 공고 서버 응답 | `curl -s localhost:8000/api/health` · `curl -s localhost:8000/api/collection_status` |
| 매일 배치 다음 실행 | `systemctl list-timers notice-batch.timer` |
| 매일 배치 기록 | `journalctl -u notice-batch -n 200` · `/var/lib/sbrain-notice/data/collect_log.jsonl` |
| 배치 손으로 돌리기 | `sudo systemctl start --no-block notice-batch` |
| 올리기 기록 | `/var/log/sbrain/notice-deploy/<이름>.log` |

## 파일

| 파일 | 하는 일 | 어디서 |
|---|---|---|
| [../deploy-notice.sh](../deploy-notice.sh) | 수집 키 넣기 · 코드 묶어 올리기 · 설치 실행 · 웹 서버에서 확인 | PC |
| [install-notice.sh](install-notice.sh) | 패키지 · 계정 · 설정 · 코드 · 가상환경 · BGE-M3 · 데이터 옮기기 · 서비스 | 공고 서버 |
| [notice-server.service](notice-server.service) | 공고 서버(8000번) 상시 실행 | 공고 서버 |
| [notice-batch.service](notice-batch.service) · [notice-batch.timer](notice-batch.timer) | 매일 한국 09:00 수집 배치, 끝나면 공고 서버 다시 띄우기 | 공고 서버 |
| [requirements-notice.txt](requirements-notice.txt) | 가상환경 패키지(개인 서버 배치와 같은 판) | 공고 서버 |
