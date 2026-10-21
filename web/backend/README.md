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


## 공고 검색 지연 확인

브라우저 개발자 도구의 Network에서 `POST /projects`와
`GET /projects/{project_id}/match-candidates`의 시간을 각각 확인합니다.
API 응답의 `Server-Timing: app;dur=...`는 앱에서 응답 헤더를 준비할 때까지의
처리 시간(ms)입니다. 업로드·응답 다운로드·프록시·네트워크 지연을 포함한 전체 시간은
Network의 Timing과 비교합니다. `X-Request-ID`를 `logs/web-YYYY-MM-DD.log`의
`req_id`와 대조하면 해당 요청의 상태 코드와 `elapsed_ms`를 찾을 수 있습니다.
인증된 실제 사용자 세션으로 확인하며 로그인 정보나 요청 본문을 로그에 추가하지 않습니다.

관리자 공고 목록은 필요한 컬럼만 조회하며 원본 JSON·본문·임베딩 파일 내용은
목록 응답을 위해 가져오지 않습니다. 관리자 임베딩 유무는 DB에서 NULL 여부만 계산합니다.
`recruitment_status=unknown`은 수집 당시 모집 상태를 확보하지 못했다는 원본 값으로
API에서도 보존합니다. 이를 모집중으로 바꾸거나 날짜만으로 확정하지 않습니다.


## 관리자 공고 표시 상태

`GET /admin/notices`는 원본 `recruitment_status`와 별도로 `display_status`를 반환합니다.
프런트엔드는 상태 문구에 `display_status`를 사용하면 됩니다. DB 원본은 변경하지 않습니다.
한국 날짜(UTC+9)를 요청당 한 번 계산하며 다음 우선순위를 적용합니다.

1. 시작일이 마감일보다 늦은 비정상 기간: 확인 필요
2. 마감일이 오늘 이전: 마감
3. 시작일이 오늘 이후: 접수 예정
4. 원본 `closed`: 마감 / 원본 `open`: 모집중
5. 두 날짜 사이(시작일·마감일 당일 포함): 접수기간 내 · 원문 확인
6. 그 외: 확인 필요

원본 상태를 알 수 없고 기간 유형이 `budget_exhaustion`, `rolling`, `until_filled`이면
기간 안에 있더라도 확인 필요로 표시합니다. 날짜만으로 예산 잔액이나 실제 모집 여부를 확정하지 않습니다.
날짜에 시각 정보가 없으므로 마감일 당일의 시간 단위 조기 마감은 판정하지 않습니다.


## 관리자 재채점 편차와 체크리스트 저장

운영 현황의 코드 기준 검증·계획서 대조는 최초 점수 자체가 아니라 **최초 채점과 최근 재작성 후 채점의 차이**입니다.
오케스트레이터는 성공한 `T-V2` 실행의 `codeCheck`·`featureMatch` 점수를 실행 건의 배점으로 환산하고,
최초 이력과 `trigger=재작성` 이력이 모두 있는 최근 12개월 활동 실행 건만 편차 표본으로 셉니다.
일반 재시도·재수행은 재작성 표본을 대신하지 않습니다. 표본 수는 채점 횟수가 아니라 비교 가능한 실행 건 수입니다.
평균은 소수 첫째 자리로 반올림합니다. 웹 API는 각각 `code`·`plan`으로 변환하고,
`round1_avg`, `round2_avg`, `delta_avg`, `sample_count`를 반환합니다.
프런트는 `sample_count=0`일 때 `-`를 표시하고, 표본이 있으면 차이가 0이어도 `0점`을 표시합니다.
운영 현황 진입 시 조회하며 자동 갱신하지 않습니다. 기존 화면의 ‘1회 → 2회’ 문구는 이 집계의
정확한 의미인 ‘최초 → 최근 재작성 후’로 변경하는 것이 맞습니다(이번에는 프런트 코드를 변경하지 않음).

`PUT /admin/checklist`는 부분 변경을 지원하되 생략된 기존 항목까지 포함한 **최종 활성 항목**의
카테고리별 합계를 15점으로 검증합니다. 중복 ID는 422, 없는 ID는 404로 거부하며,
검증 전에 ORM 값을 변경하지 않아 실패한 요청은 기존 설정을 보존합니다.
카테고리 전체 비활성화는 기존 정책대로 허용합니다. 동시 변경은 ID 순서의 행 잠금으로 직렬화합니다
(SQLite 테스트에서는 행 잠금을 검증하지 않으므로 실제 MySQL 동시성 검증은 별도입니다).


## 운영 안정성 보완

- Refresh Token은 유효하고 폐기되지 않은 행을 조건부 UPDATE로 점유한 요청만 회전합니다.
  중복·동시 요청의 패자는 401이며 새 토큰을 만들지 않습니다. 새 토큰 발급 실패 시 기존 토큰 폐기도 롤백합니다.
- 관리자 점수 분포는 하한 포함·상한 미포함으로 집계하며 최상위의 100점만 상한에 포함합니다.
  59.5·69.5·79.5·89.5점도 정확히 한 구간에 포함합니다. 화면 구간 라벨은 유지합니다.
- HWP 임시 파일은 생성 직후 파일 디스크립터를 닫습니다. 준비·변환 단계에서 실패해도 정리를 시도하며,
  정리 실패는 로그에 남기고 원래 변환 오류를 보존합니다.
