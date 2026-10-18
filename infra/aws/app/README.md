# 앱 올리기 (infra/aws/app)

`up.sh`가 만든 웹 서버에 오케스트레이터 워커와 웹(FastAPI + React)을 올린다. 서버 · DB는 [../README.md](../README.md)의 `up.sh`로 먼저 만든다.

```bash
bash infra/aws/up.sh           # 1. 서버 · DB (처음, 그리고 템플릿이 바뀌었을 때)
bash infra/aws/app-env.sh      # 2. 비밀 값 넣기 → 웹 서버에 env 파일 (처음, 그리고 값을 바꿀 때)
bash infra/aws/deploy-app.sh   # 3. 앱 올리기 (코드를 바꿀 때마다)
```

세 스크립트 모두 `--profile` · `--region` · `--stack` · `--yes`를 똑같이 받는다. 윈도우는 Git Bash에서 실행한다.

## 처음 한 번만

1. **템플릿 권한 반영:** 웹 서버가 앱 설정 값과 코드 묶음을 읽는 권한(`WebAppPolicy`)이 템플릿에 있다. 이미 만든 스택이면 `up.sh`를 한 번 더 실행해 반영한다. 서버는 새로 만들어지지 않는다.
2. **웹 주소:** `infra/aws/settings.env.local`에 적는다(커밋 안 됨).
   ```bash
   WEB_DOMAIN=app.example.com     # 실제 도메인
   CERTBOT_EMAIL=me@example.com   # 인증서 만료 안내 메일(선택)
   ```
   DNS에서 이 이름의 A 레코드를 `up.sh`가 보여 준 웹 서버 고정 IP로 연결해 둔다. 연결 전에 올리면 HTTP로만 뜨고, 연결한 뒤 `deploy-app.sh`를 다시 실행하면 그때 인증서를 받는다.
3. **구글 로그인:** Google Cloud 콘솔의 OAuth 클라이언트에 승인된 JavaScript 원본 `https://<WEB_DOMAIN>`을 더한다. 구글 로그인은 HTTPS 주소에서만 된다.

## 2. 비밀 값 — `app-env.sh`

값은 AWS SSM Parameter Store에 SecureString으로 둔다(이름 `/<스택>/app/<이름>`, 표준 등급이라 요금 없음). 서버는 IAM 역할로 읽어 env 파일을 만든다. 입력하는 값은 화면 · 명령줄 · 원격 실행 기록에 나오지 않는다.

| 이름 | 쓰는 곳 | |
|---|---|---|
| `OPENAI_API_KEY` | 워커 | 필수 |
| `GOOGLE_CLIENT_ID` | 웹 백엔드 · 프론트 빌드 | 필수 |
| `JWT_SECRET` | 웹 백엔드(로그인 쿠키 서명) | 필수 — 비워 두면 무작위 값을 만든다 |
| `NTS_SERVICE_KEY` | 웹 백엔드(국세청 사업자 조회, 디코딩 키) | 선택 — 없으면 그 기능만 꺼진다 |
| `SBRAIN_NOTICE_API_URL` | 워커(공고 서버 `http://<내부 주소>:8000`) | 선택 — 없으면 공고 매칭 · 자격 확인이 스텁 |

- 이미 있는 값은 다시 묻지 않는다. 바꿀 때: `bash infra/aws/app-env.sh --reset OPENAI_API_KEY`
- 값을 바꾸면 떠 있던 웹 · 워커를 다시 띄워 새 값을 읽게 한다(워커는 하던 단계를 끝낸 뒤 — 최대 15분).
- **`down.sh`는 이 값을 지우지 않는다.** 스택을 다 지운 뒤 `bash infra/aws/app-env.sh --remove`로 지운다.
- AWS 키는 넣지 않는다. 앱은 서버 IAM 역할로 S3 · Parameter Store에 닿는다.

서버에 생기는 파일(root만 읽음, `systemd`가 읽어 앱에 넘긴다 — 손으로 고치지 않는다):

| 파일 | 내용 |
|---|---|
| `/etc/sbrain/db.env` | `up.sh`가 만든 `MYSQL_*` |
| `/etc/sbrain/worker.env` | `SBRAIN_DB_URL` · `OPENAI_API_KEY` · `SBRAIN_ARTIFACT_ROOT=s3://<버킷>/app/artifacts/` · `AWS_REGION` · 운영 로그 폴더 · `SBRAIN_KIET_SEARCH=1` · (공고 서버 주소) |
| `/etc/sbrain/web.env` | `GOOGLE_CLIENT_ID` · `JWT_SECRET` · 같은 `SBRAIN_ARTIFACT_ROOT` · `AWS_REGION` · `REQUIRE_BUDGET_SCHEDULE=1` · `COOKIE_SECURE=1` · `RHWP_BIN` · (`NTS_SERVICE_KEY`) |

## 3. 앱 올리기 — `deploy-app.sh`

지금 갈래의 **마지막 커밋**을 올린다(`--ref <커밋>`으로 다른 커밋). 커밋하지 않은 변경 · `.env`는 올라가지 않는다.

PC에서는 `agent-orchestration/` · `web/` · `infra/aws/app/`을 `git archive`로 묶어 S3 `deploy/releases/`에 올리고, 서버에서 [install-app.sh](install-app.sh)를 원격 실행(SSM)으로 돌린다. 서버에 GitHub 키를 둘 필요가 없다.

서버에서 하는 일:

1. **패키지:** nginx · certbot · LibreOffice Writer(계획서 PDF) · 한글 글꼴(나눔 · Noto CJK) · Node 22(NodeSource 저장소) · rhwp v0.8.6(`.hwp` 내려받기 — GitHub 릴리스, 못 받으면 `.hwp`만 꺼짐)
2. **코드 · 가상환경:** `/opt/sbrain/releases/<이름>/`에 풀고, 그 안의 `.venv` 하나에 웹 의존성과 오케스트레이터(boto3 포함)를 깐다. `/opt/sbrain/current`가 지금 코드를 가리킨다.
3. **프론트:** `web/frontend`를 `VITE_API_BASE=/api`로 빌드해 `/var/www/sbrain`에 둔다(웹 계정으로 빌드).
4. **서비스 바꾸기:** 워커를 멈추고(하던 단계를 끝낸 뒤) 새 코드로 바꾼 다음 `sbrain-worker --once`로 한 바퀴 점검(DB · 설정 · S3 시작 확인)한다. 통과하면 워커 · 웹을 띄우고 웹 `/health`를 확인한다. **점검이나 확인이 실패하면 바로 앞 코드로 되돌리고 멈춘다.**
5. **nginx:** `/api/` → `127.0.0.1:8000`(FastAPI), 나머지 → 프론트. 같은 주소라 CORS가 필요 없다. `WEB_DOMAIN`이 있으면 Let's Encrypt 인증서를 받아 HTTPS로 열고(이용 약관에 동의하게 된다), HTTP는 HTTPS로 넘긴다. 인증서 갱신은 certbot 타이머가 한다.
6. 옛 코드는 셋만 남기고 지운다.

처음에는 15~25분(LibreOffice · Node 설치), 다음부터는 5~10분 걸린다. 워커가 단계를 하던 중이면 그 단계가 끝날 때까지(최대 15분) 더 기다린다. 워커는 1대만 띄우고 무중단 교체를 쓰지 않는다.

## 서버에서 보기

```bash
ssh -F infra/aws/.out/sbrain-ap-northeast-2/ssh_config sbrain-web
```

```bash
systemctl status sbrain-web sbrain-worker nginx
```

```bash
sudo journalctl -u sbrain-worker -f      # 워커 화면 줄 (파일: /var/log/sbrain/worker)
```

```bash
sudo journalctl -u sbrain-web -f         # 웹 백엔드 (요청 로그 파일: /var/log/sbrain/web)
```

```bash
sudo ls /var/log/sbrain/deploy/          # 올릴 때마다의 설치 기록
```

## 파일

| 파일 | 하는 일 | 어디서 |
|---|---|---|
| [../app-env.sh](../app-env.sh) | 비밀 값 넣기 · env 파일 만들기 | PC |
| [../deploy-app.sh](../deploy-app.sh) | 코드 묶어 올리기 · 설치 실행 | PC |
| [../lib-app.sh](../lib-app.sh) | 두 스크립트의 원격 실행 도우미 | PC |
| [write-app-env.sh](write-app-env.sh) | Parameter Store + `db.env` → `worker.env` · `web.env` | 웹 서버 |
| [install-app.sh](install-app.sh) | 패키지 · 코드 · 가상환경 · 프론트 · 서비스 · nginx · HTTPS | 웹 서버 |
| [sbrain-worker.service](sbrain-worker.service) · [sbrain-web.service](sbrain-web.service) | systemd 서비스 | 웹 서버 `/etc/systemd/system/` |
| [nginx-app.conf](nginx-app.conf) · [nginx-http.conf](nginx-http.conf) · [nginx-https.conf](nginx-https.conf) | nginx 설정(공통 · HTTP만 · HTTPS) | 웹 서버 `/etc/nginx/` |

서버의 서비스 · nginx 설정은 다시 올릴 때마다 이 폴더의 파일로 덮어쓴다. 서버에서 직접 고치지 말고 여기를 고쳐 다시 올린다.

## 한계

- **첨부 파일 · 웹 요청 로그 · 워커 운영 로그는 웹 서버 디스크에 있다**(`/var/lib/sbrain/web/uploads` · `/var/log/sbrain/`). 코드를 다시 올려도 남지만 서버를 새로 만들면 사라진다. 산출물 파일은 S3에 있다.
- 웹 서버 한 대가 nginx · 웹 · 워커 · 프론트 빌드를 모두 맡는다. 빌드하는 1~2분 동안은 서버가 바쁘다.
- 공고 서버 앱은 이 스크립트가 올리지 않는다(공고팀 몫).
