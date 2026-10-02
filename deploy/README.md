# S-Brain 웹 배포

웹 화면과 웹 백엔드를 서버 한 대에 Docker 로 올린다. 담당: 이근준(인프라·배포). 처음 작성 2026-10-02.

```
브라우저 ──https──▶ [web: Caddy]  ──/api/*──▶ [backend: FastAPI :8000] ──3306──▶ 팀 공용 MySQL (기존 EC2)
                     ├ /   화면(React 빌드 결과)        ├ LibreOffice + 나눔 폰트 (계획서 PDF)
                     └ HTTPS 인증서 자동 발급           └ rhwp 리눅스판 (계획서 .hwp)
```

- 화면과 API 가 **같은 주소**라 CORS 설정이나 쿠키 SameSite 문제가 생기지 않는다. 그래서 웹 코드는 고치지 않는다.
- DB 는 새로 만들지 않는다. 웹이 쓰는 표(users·projects 등)는 이미 팀 공용 DB 에 있다(`web/backend/app_schema.sql`).
- 지금 올라가는 것: 웹 화면 + 웹 백엔드(Agent 는 아직 가짜 함수). 공고 매칭 서버·매일 수집 배치·진짜 Agent 는 다음 단계다(맨 아래).

## 파일

| 파일 | 하는 일 |
|---|---|
| `docker-compose.yml` | 두 컨테이너(backend·web)와 저장 공간(업로드·로그·인증서) |
| `backend.Dockerfile` | Python 3.12 + 백엔드 + LibreOffice·나눔 폰트 + rhwp(공식 릴리즈, 체크섬 확인) |
| `web.Dockerfile` | 화면 빌드(Node 22) → Caddy 에 담기 |
| `Caddyfile` | `/api` → 백엔드, 나머지 → 화면, 도메인이면 HTTPS |
| `*.Dockerfile.dockerignore` | 저장소 전체 대신 필요한 폴더만 Docker 로 넘긴다 |
| `.env.example` | 설정 예시. 실제 값은 `.env`(Git 에 안 올라감) |
| `setup_ubuntu.sh` | 새 Ubuntu 서버에 Docker·스왑 준비(한 번) |

## 서버에 올리기

### 1. 서버 만들기 (AWS 콘솔)

- **예산 알림** 먼저: Billing → Budgets (예: $80).
- EC2: Ubuntu 24.04 · **t3.medium(4GB)** · 디스크 gp3 30GB · 키 페어.
  - 백엔드 이미지가 약 0.95GB, 화면 이미지가 약 0.1GB 다. 30GB 면 충분하다.
- 보안그룹: 22 → 내 IP 만, 80·443 → 전체.
- 탄력적 IP 연결. 서버를 껐다 켜도 주소가 안 바뀌어 도메인이 유지된다.
- 팀 DB(기존 EC2)의 3306 이 새 서버에서 열리는지 확인한다. 나중에 3306 을 막을 때 이 서버 IP 만 허용한다.

### 2. 코드 받기와 준비

```bash
git clone https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN32-FINAL-1TEAM.git sbrain
cd sbrain
bash deploy/setup_ubuntu.sh        # Docker·스왑. 끝나면 로그아웃 후 다시 접속
```

> 받는 브랜치에 **최신 웹 코드(main 의 `web/`)와 이 `deploy/` 폴더가 둘 다** 있어야 한다.

### 3. 설정

```bash
cd sbrain/deploy
cp .env.example .env
nano .env
```

- 처음에는 `SITE_ADDRESS` 를 비워 두고 `http://<서버 IP>` 로 먼저 확인한다.
- DB 값은 공고 수집 파이프라인과 같은 DB 다. 웹용 계정 값은 웹 담당에게 받는다.
- `MYSQL_PASSWORD` 에 `@ : / #` 가 들어 있으면 접속 주소가 깨진다. `web/backend/app/database.py` 가 값을 그대로 URL 에 넣기 때문이다.

### 4. 띄우기

```bash
docker compose up -d --build       # 처음 빌드 5분 안팎
docker compose ps                  # backend 가 (healthy) 면 정상
curl -s localhost/api/health       # {"status":"ok"}
```

### 5. 도메인과 HTTPS

1. 도메인의 A 레코드를 서버 IP 로 둔다.
2. `.env` 에 `SITE_ADDRESS=도메인` 을 적고 `docker compose up -d` 한다. Caddy 가 인증서를 받고 http 를 https 로 넘긴다.
3. **구글 로그인**: 구글 클라우드 콘솔 → OAuth 클라이언트 → "승인된 JavaScript 원본"에 `https://도메인` 을 추가한다. 이 클라이언트 ID 를 만든 팀원 계정에서 해야 한다.
4. `VITE_GOOGLE_CLIENT_ID` 를 넣었거나 바꿨으면 화면을 다시 빌드한다: `docker compose up -d --build web`.

## 운영

```bash
git pull && docker compose up -d --build        # 코드 갱신 반영
docker compose logs -f backend                  # 백엔드 로그 (요청 로그 파일은 logs 볼륨)
docker compose restart backend
docker compose down                             # 끄기 (업로드·인증서 볼륨은 남는다)
```

## 알아 둘 것

- **팀 공용 DB 를 같이 쓴다.** 백엔드는 켜질 때 "끊긴 생성 작업"을 DB 에서 찾아 이어 간다(`projects.start_generation_recovery_loop`). 팀원이 로컬에서 띄운 백엔드와 같은 동작이고, DB 클레임으로 중복 실행은 막힌다. 접속자가 만든 계정·프로젝트도 공용 DB 에 쌓인다.
- 백엔드 워커는 1개다. 생성 작업이 프로세스 안의 스레드로 돈다.
- 쿠키가 `secure=False` 로 고정돼 있다(`web/backend/app/security.py` TODO). HTTPS 에서도 동작은 하지만, 보안을 위해 웹 담당이 `True` 로 바꾸는 것이 좋다. 같은 주소 구성이라 CORS 목록(`main.py`)은 고치지 않아도 된다.
- 업로드 파일은 서버 디스크(볼륨 `sbrain_uploads`)에 있다. 서버를 지우면 사라진다.

## 매일 수집 배치 (2026-10-02 서버로 전환)

PC 작업 스케줄러(`S-Brain-DailyCollection`)가 돌리던 `data-collection` 배치를 **2026-10-03 09:00 부터 서버가 돌린다.** 공고 매칭 서버는 옮기지 않았다.

- PC 예약 작업: **사용 안 함**(지우지 않았다).
- 서버 crontab: `0 0 * * * /home/ubuntu/sbrain/deploy/run_batch.sh` (UTC 00:00 = 한국 09:00).
- 로그: 서버 `~/sbrain/data-collection/data/run.log`. 이 PC 의 `data/run.log` 는 10/2 09:05 에서 멈춘다.
- 이 PC 의 8000 매칭 서버는 이 PC `data/` 의 벡터 색인을 읽는다. 그래서 새 공고가 색인에 들어오지 않는다(DB 의 공고 자체는 최신이다). 필요하면 서버 `data/` 를 PC 로 받아 온다.
- **되돌리기**: 서버에서 `crontab -e` 로 그 줄을 지운다 → PC 에서 `Enable-ScheduledTask -TaskName S-Brain-DailyCollection` → 서버 `data/` 를 PC 로 받아 온다(서버가 돈 날이 있으면).

| 파일 | 하는 일 |
|---|---|
| `batch.Dockerfile` · `batch-requirements.txt` | Python 3.12 + **CPU 판** torch + 배치 패키지(배치 PC 버전과 같게 고정) |
| `docker-compose.yml` 의 `batch` | `profiles: [batch]` 라 `compose up` 으로는 안 켜진다. 코드·`data/`·`.env` 는 `~/sbrain/data-collection` 을 그대로 붙인다 |
| `run_batch.sh` | `run_daily.bat` 의 리눅스판. `data-collection/data/run.log` 에 시작·종료를 남긴다 |

서버 배치:
- `~/sbrain/data-collection/` — 코드와 `data/`(PC 에서 복사), `.env`(배치에 필요한 키 8개만, 권한 600)
- `~/sbrain/secrets/ec2-ca.pem` — 팀 DB 암호화 접속용 CA. `.env` 의 Windows 경로는 compose 가 덮는다
- 볼륨 `sbrain_hf_cache` — BGE-M3. **배치 PC 와 같은 리비전 `5617a9f…` 으로 고정**했다. 리비전이 다르면 설정 지문이 바뀌어 공고 전체를 다시 임베딩한다(`shared/embed.py` `fingerprint`)

```bash
bash deploy/run_batch.sh --dry-run      # 수집·정규화만 (DB 쓰기 없음)
bash deploy/run_batch.sh                # 실제 실행 (DB 쓰기·LLM 비용 있음)
```

전환 순서(2026-10-02 11:2x~11:34 에 이렇게 했다):
1. PC 예약 작업을 **껐다**(`Disable-ScheduledTask`, 지우지 않음).
2. 예약과 같은 빈 환경(`env -i … PATH=/usr/bin:/bin`)에서 `run_batch.sh --dry-run` 이 `exit=0` 으로 끝나는 것을 확인했다. 이때 `docker compose run` 이 표준입력을 삼키는 문제를 찾아 `< /dev/null` 을 붙였다.
3. PC 의 `data/` 를 다시 복사했다. 시험으로 바뀐 서버 `data/` 는 `~/sbrain/_old/data_test_20261002` 로 옮겼다(첫 실행 확인 뒤 지운다).
4. 서버 crontab 에 등록했다. cron 서비스 active.
5. 남은 일: 10/3 09:20 쯤 서버 `run.log` 와 DB 를 PC 때처럼 점검한다.

## 다음 단계 (아직 안 함)

1. 공고 매칭 서버(`data-collection/search/app.py`, 메모리 약 2GB)를 붙인다 → 서버를 8GB(t3.large)로 올린다.
2. 매일 수집 배치를 개인 PC 에서 서버로 옮긴다.
3. 진짜 Agent 가 연결되면 다시 배포한다.
4. 팀 DB 3306 을 이 서버 IP 로만 제한한다.

## 시험 기록

**2026-10-02 · 로컬 Docker (Windows, Docker 29.8.1 / Compose v5.5.1)**

- 조건: main(`213b5f3`)의 `web/` 을 꺼내 빌드. 팀 DB 대신 `DB_BACKEND=sqlite`(공용 DB 의 생성 작업을 건드리지 않으려고). 포트 8088.
- 빌드: 두 이미지 모두 성공. rhwp v0.8.6 체크섬 통과. 이미지 크기 backend 943MB · web 95MB.
- 응답:
  - `/` → 화면 200, `/api/health` → 200, `/api/faqs` → 200(DB 조회)
  - `/api/auth/me` → 401(로그인 필요, 정상), 없는 경로 → 화면으로 돌아감
- 브라우저: 화면이 뜨고, 화면이 `localhost:8000` 이 아니라 `/api/auth/me` 를 부르는 것을 확인했다.
- 컨테이너 안 실행:
  - 더미 계획서 두 양식(초기·예비)을 docx → PDF 로 바꿨다. 1.3초·3.3초, 나눔 폰트로 한글 정상.
  - rhwp 로 .hwp 생성 0.5초, HWP 파일 서명 정상.
- 확인하지 못한 것: 구글 로그인(HTTPS 주소와 클라이언트 ID 필요), 팀 MySQL 접속, 실제 EC2 에서의 빌드·메모리.

**2026-10-02 · EC2 `sbrain-web` (c7i-flex.large 4GB, Ubuntu 26.04, Docker 29.1.3 / Compose 2.40.3)**

- 서버 준비: `setup_ubuntu.sh` 로 Docker 와 스왑 2GB 를 설치했다. sudo 없이 `hello-world` 가 돌아간다.
- 코드: GitHub 대신 이 PC 에서 임시로 복사했다(`~/sbrain/SOURCE.txt`). web 은 main `213b5f3`, data-collection 은 PC 작업 폴더(10:54).
- backend 이미지: 빌드 약 1분, 943MB, 빌드 중 서버 메모리 최대 약 818MB.
- batch 이미지: 빌드 119초, 2.47GB. BGE-M3 리비전 `5617a9f…` 을 받는 데 20초. 설정 지문 `0a803d170f58c36e` 가 배치 PC 와 같다.
- 배치 시험 A `--dry-run`: AWS 에서 두 API 모두 응답했다(K-Startup 215건 = 서버 보고, 기업마당 1,444건). 3초, DB 쓰기 없음.
- 배치 시험 B 임베딩: 팀 DB 를 SELECT 만 했다(암호화 접속, 2,714건 0.3초).
  - 임베딩 계획은 "그대로 2,714 · 만들 것 0" 이었다.
  - 실제 공고 112건을 임베딩하고 저장하지 않았다. **109.6초**, 1024차원.
  - 프로세스 최대 메모리 2,435MB, 서버 사용 메모리 최대 1,752MB / 3,811MB, 가장 적었던 여유 메모리 2,058MB, 스왑 8MB.
  - 이때 웹 컨테이너는 켜지 않았다.
