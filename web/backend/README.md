# S-Brain 백엔드 (FastAPI)

## 실행 방법

아래 명령은 전부 **이 디렉터리(`app/main.py`가 있는 위치)에서** 실행합니다.

### 1) 의존성 설치

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt   # 테스트(pytest)/린트(ruff) 실행할 때만 필요
```

### 1-1) 오케스트레이터(sbrain) 설치 · DB · 워커

웹 서버는 오케스트레이터(`agent-orchestration`의 `sbrain` 패키지)를 **같은 프로세스에서 불러** 씁니다. 그래서 위 `requirements.txt`만으로는 서버가 계획서 · 점수 · 산출물 기능을 쓰지 못합니다(MySQL 모드가 아니거나 sbrain이 없으면 해당 API는 503). 아래는 로컬 E2E에서 쓰는 방식이고, 배포 서버의 설치 절차는 확인하지 못했습니다.

```bash
# 같은 가상환경에서 — sbrain과 그 의존성(pydantic · SQLAlchemy · PyMySQL · openai · python-dotenv · requests · beautifulsoup4)이 함께 깔린다
pip install -e ../../agent-orchestration
```

- `agent-orchestration/requirements.txt`만 설치하면 `sbrain` 자체가 빠집니다. `pyproject.toml`로 설치(위 명령)하면 의존성이 같이 옵니다.
- `beautifulsoup4`(`bs4`)는 담당자의 시장 자료 크롤러가 불러서 필요합니다. 실행 흐름에서는 쓰지 않아도 가져오기만 하면 되기 때문에 **없으면 서버가 뜨지 않습니다**(`ModuleNotFoundError: No module named 'bs4'`).
- **DB**: 웹 테이블(`app_schema.sql` · `migrations/`)과 오케스트레이터 테이블(`agent-orchestration/sql/orchestrator_schema.sql`, `orch_` 접두어 14개)이 같은 MySQL에 있어야 합니다. 오케스트레이터 스키마는 `CREATE TABLE IF NOT EXISTS`만 있어 몇 번 실행해도 안전하고, 새 표가 생기면(예: SB-311의 `orch_file_deletions`) 다시 실행해야 합니다. 표가 없으면 `GET /admin/file-deletions` 같은 API가 500입니다.
- **워커**: 단계를 실제로 진행하는 것은 별도 프로세스(`python -m sbrain.worker`, 같은 DB · 같은 `SBRAIN_ARTIFACT_ROOT`)입니다. 웹만 띄우면 시작 요청이 쌓이기만 합니다.
- 옛 버전 오케스트레이터로 만든 실행 건은 새 버전이 읽지 못할 수 있습니다(`GET /result`가 500 — 저장된 계획서의 칸 구성이 달라진 경우). 시연용으로 남겨 둔 옛 실행 건이 있으면 새로 만드는 편이 안전합니다.
- 로컬에서 실제 Agent 호출 없이 흐름만 보려면(조율 T-C1 · T-C3만 실제 OpenAI, 나머지는 스텁): `scripts/prepare_local_mysql.py`로 로컬 DB를 만들고, 워커 대신 `scripts/stub_worker.py`를 띄웁니다(`testing_guide.md`).

### 2) 환경변수(.env)

```bash
cp .env.example .env
```

`.env.example`에 있는 항목:

| 변수 | 용도 |
|---|---|
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL 접속 정보 |
| `GOOGLE_CLIENT_ID` / `JWT_SECRET` | 구글 로그인 / 세션 쿠키(JWT) 서명 |
| `NTS_SERVICE_KEY` | 공공데이터포털 국세청 사업자등록정보 조회 API 키 (디코딩 키) |
| `REQUIRE_BUDGET_SCHEDULE` | 사업비 · 추진 일정 필수 입력 스위치(SB-332). `1`이면 사업비 1건 이상, 예비창업은 1 · 2단계 각 1건 이상, 협약기간 내 일정 1건 이상이 없는 프로젝트 생성을 `E-C1-REQUIRED`로 막는다. 비우면 꺼짐 — 입력 화면 배포 뒤에 켠다 |
| `RHWP_BIN` | 사업계획서 `.hwp` 다운로드용 rhwp 실행 파일 경로. `rhwp.exe`는 용량 문제로 git엔 안 올라가 있어 각자 [공식 릴리즈](https://github.com/edwardkim/rhwp/releases/tag/v0.8.6)에서 받아 이 디렉터리에 `rhwp.exe`로 저장한 뒤 `RHWP_BIN=./rhwp.exe`를 넣어야 함 — 안 받아도 서버는 정상 동작하고 `.hwp` 다운로드만 500 에러가 남. 자세한 다운로드·확인 절차는 `scripts/README.md` 참고 |

`.env.example`엔 없지만 로컬 개발 시 자주 쓰는 변수:

| 변수 | 용도 |
|---|---|
| `DB_BACKEND` | 지정 안 하면(또는 `mysql`) MySQL을 씀. `sqlite`로 주면 MySQL 세팅 없이 개인 로컬 SQLite로만 도는 보조 모드(더미 데이터, 빠른 화면 확인용) |
| `SQLITE_PATH` | `DB_BACKEND=sqlite`일 때 DB 파일 경로를 바꾸고 싶으면 지정 (기본값은 아래 "실행 중 생성되는 파일" 참고) |

### 3) 서버 실행

`.env`에 `MYSQL_*`를 채운 뒤:

```bash
uvicorn app.main:app --reload --port 8000
```

MySQL 세팅 없이 개인 로컬에서 빠르게 띄워만 보고 싶으면(더미 데이터, 화면 확인용):

```bash
DB_BACKEND=sqlite uvicorn app.main:app --reload --port 8000
```

Swagger 문서: http://127.0.0.1:8000/docs

### 4) 테스트 / 린트

```bash
pytest tests/ -q
ruff check .
```

## 실행 중 생성되는 파일/디렉터리

아래 경로는 전부 **리포 루트(`app/`와 같은 레벨, 이 디렉터리) 기준**입니다 — `app/` 안이 아닙니다.

| 위치 | 내용 | 비고 |
|---|---|---|
| `dev.db` | SQLite DB 파일 | **`DB_BACKEND=sqlite`로 직접 지정했을 때만** 생성됨(`app/database.py`) — 기본(MySQL) 실행 중엔 안 생김. `.gitignore` 처리돼 커밋되지 않음 |
| `logs/web-YYYY-MM-DD.log` | 요청 단위 로그(누가 언제, 어떤 API, 성공/실패, 처리시간) | DB엔 안 남기고 파일로만 쌓음(`app/logging_config.py`, `app/request_logging.py`). 이름·이메일 등 개인정보는 기록하지 않음. 하루 20MB 넘으면 `web-YYYY-MM-DD.2.log`처럼 순번을 붙여 회전하고, 보관기간 자동 삭제는 기본 꺼짐(`WEB_LOG_RETENTION_DAYS=0`) |
| `uploads/` | 사용자 첨부파일 + 산출물(인포그래픽/프로토타입 HTML) 실제 파일 | `GET /uploads/{filename}`로만 서빙되며 인증·소유권 확인을 거침(`app/routers/uploads.py`). `.gitignore` 처리돼 커밋되지 않음 |
| `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` | 파이썬/pytest/ruff 캐시 | `.gitignore` 처리됨, 지워도 무방 |

`.hwp`/`.pdf` 다운로드(사업계획서 내보내기, `app/hwp_export.py` / `app/pdf_export.py`)는 요청이 올 때마다 임시 파일로 변환해서 응답으로 바로 내려주고 디스크에 남기지 않습니다.
