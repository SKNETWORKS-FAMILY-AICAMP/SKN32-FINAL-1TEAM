# S-Brain 백엔드 테스트 방법 정리 (2026-09-14)

`back/`(repo 루트)에서 실행하는 걸 기준으로 정리했다. 전부 `DB_BACKEND=sqlite`(로컬 `dev.db`) 기준이라 AWS 공유 DB엔 영향 없다.

---

## 0. 사전 준비 (한 번만)

```
cd back
python -m venv venv
venv\Scripts\activate        # (WSL/맥이면 source venv/bin/activate)
pip install -r requirements.txt
```

`.env.example`을 복사해서 `.env`로 만들고 `DB_BACKEND=sqlite`로 해둔다. (아래 검증 스크립트들은 스크립트 안에서 `DB_BACKEND=sqlite`를 자동으로 세팅하는 것도 있어서 `.env` 없이도 돌아가지만, `uvicorn`으로 서버를 직접 켤 땐 `.env`가 필요하다.)

---

## 1. 서버 없이 바로 되는 것 — 검증 스크립트 4개

전부 스크립트 안에서 `DB_BACKEND=sqlite`를 자동 세팅하고, `dev.db`를 매번 지우고 새로 만들어서 스키마가 항상 최신 상태로 시작한다. 그냥 실행하면 된다.

```
python verify_resume_cases.py       # 이어하기 8케이스 stage/progress_percent 판별 검증
python verify_status_endpoint.py    # GET /projects/{id}/status API 실제 HTTP 왕복 검증
python verify_schema_gaps_seed.py   # 이번에 추가한 6개 스키마 항목이 실제로 채워지는지 검증
python verify_retry_task.py         # POST /projects/{id}/retry-task — 재시도할 때마다 실제로 값이 바뀌는지 검증
```

마지막 줄에 `ALL OK` 또는 `결과: ... 확인.`이 뜨면 통과, 중간에 `assert`가 걸려서 에러 나면 뭔가 깨진 것.

이 4개는 각자 자기만의 임시 `dev.db`를 지우고 새로 만들기 때문에, **2번에서 만든 프로젝트 데이터와는 무관**하다 — 이 스크립트들을 돌리고 나면 2번에서 만든 project_id는 지워진다는 뜻. 순서를 꼭 지킬 필요는 없지만, 같은 `dev.db`를 계속 쓰면서 테스트하고 싶으면 이 4개를 먼저 돌리고 나서 2번을 진행하는 게 깔끔하다.

### 1-1. admin.py는 `verify_admin.py`가 아니라 pytest로 (2026-09-14부터)

`app/routers/admin.py`(정책/체크리스트/진행현황/유저/FAQ/에이전트로그)는 원래 `python verify_admin.py`로 확인했는데, 지금은 `tests/test_admin.py`로 옮겨서 `verify_admin.py`는 지웠다 — 실행은 아래처럼 `pytest`로 한다(`tests/conftest.py`가 `DB_BACKEND=sqlite`로 자동 전환해주는 것도 그대로, 위 4개 스크립트와 달리 `back/dev.db`가 아니라 `back/test.db`라는 별도 파일을 쓰고 테스트가 끝나면 테이블 내용을 비워서 다음 테스트에 안 새게 해준다).

```
pytest tests/test_admin.py -v
```

정책 배점 100 검증/체크리스트 가중치 100 검증/`GET /admin/items` 진행현황/유저 승격(얼굴인증 게이트)/FAQ(미답변 조회·답변 저장)/에이전트 실행로그, 그리고 일반 계정 403·정지 계정 401 구분까지 총 11개 테스트로 나뉘어 있다 — `python verify_admin.py` 한 덩어리로 돌리던 것과 확인 내용은 동일하지만, 중간에 하나가 깨져도 나머지가 계속 실행돼서 pytest 리포트에 한 번에 다 보인다는 게 다르다.

나머지 4개(`verify_resume_cases.py` 등)도 언젠가 `test_*.py`로 옮길 계획이지만 아직은 그대로다 — 옮겨지면 여기도 같이 업데이트할 것.

---

## 2. 실제 흐름으로 테스트 (구글 로그인 없이)

진짜 구글 로그인(`login_test.html`)은 Google Cloud Console에 origin 등록이 필요해서 지금 당장 안 될 수 있다 — 그거 없이도 아래 3개 스크립트로 전체 흐름을 터미널에서 테스트할 수 있다. 전부 `app/security.py`의 구글 토큰 검증 함수만 가짜로 바꿔서(monkeypatch) 실제 코드 경로(로그인 → 프로젝트 생성 → 상태 조회)는 그대로 태운다.

### 2-1. 프로젝트 생성 (project_id 받기)

```
python create_test_project.py
```

```
로그인 성공 (test@example.com)
프로젝트 생성 완료 — project_id=2
```

같은 `--email`로 다시 실행하면 같은 계정으로 로그인된다(이미 진행 중인 프로젝트가 있으면 409가 나는 게 정상 — 동시 실행 1건 제한). 새 프로젝트를 또 만들고 싶으면 이메일을 바꾼다:

```
python create_test_project.py --email test2@example.com --description "다른 아이디어"
```

### 2-2. 더미 파이프라인 채우기

```
python seed_dummy_pipeline.py 2
```

(`2`는 2-1에서 나온 project_id로) 매칭 → 자격판정 → 계획서 → 산출물 → 최종 판정 → 실행 로그까지 전체 체인을 더미값으로 채운다. `--no-files` 붙이면 실제 더미 파일 생성 없이 경로 문자열만 채운다.

### 2-3. 결과 확인

```
python check_project_status.py 2
```

```
GET /projects/2/status -> 200
{"project_id":2,"screen":11,"stage":"done","progress_percent":100,"match_id":2,"match_status":"completed"}
```

**주의**: `create_test_project.py`의 로그인은 그 스크립트를 실행한 프로세스 안에서만 유효한 세션이라, 브라우저나 Swagger(`/docs`)에서 직접 `/projects/2/status`를 열면 항상 "로그인이 필요합니다"(401)가 뜬다 — 이건 버그가 아니라 정상 동작이다. 브라우저 없이 확인하려면 `check_project_status.py`처럼 로그인 + 조회를 같이 하는 스크립트를 써야 한다.

`--email`은 `create_test_project.py`에 줬던 것과 같아야 한다(기본값 그대로면 둘 다 안 건드리면 됨). 다른 이메일로 조회하면 일부러 404(본인 프로젝트 아님)가 나오도록 돼 있다 — 소유권 체크 확인용으로도 쓸 수 있다.

### 2-4. 개별 작업 재시도 (`POST /projects/{id}/retry-task`)

기능정의서 cf. 요구사항("재시도해도 같은 결과만 나오면 안 되고, 실제로 결과가 바뀌어야 한다") 대응 API. `login_test.html`이나 로그인된 브라우저 세션으로 Swagger(`/docs`)에서 직접 호출해보는 게 제일 빠르다 — `check_project_status.py`처럼 별도 스크립트로 감쌀 필요 없이, 로그인만 돼 있으면 그대로 호출된다.

Swagger에서 `POST /projects/{project_id}/retry-task`를 찾아 body에 task_key 하나를 넣고 실행한다. `조율`(오케스트레이션 체크포인트 4개 — coordinate_intake 등)만 빼고 나머지 10개 전부 재시도 가능하고, 각각 어느 테이블을 갱신하는지는 다음과 같다(자세한 매핑 근거는 `app/agents.py` 모듈 docstring 참고):

| task_key | agent_name | 갱신 대상 | 응답 `changed` 모양 |
|---|---|---|---|
| `strategy` | 전략 | `plan_sections` (`3-1`) | `{"sections": {"3-1": {"before","after"}}}` |
| `writing` | 작성 | `plan_sections` (`1-1`/`2-1`) | `{"sections": {"1-1": {...}, "2-1": {...}}}` |
| `verify1_rubric` | 검증-1 | `plan_score_reasons` + `doc_score` | `{"scores": {item_code: {"before","after"}}, "doc_score": {"before","after"}}` |
| `verify1_evidence` | 검증-1 | 〃 (+ E-V1-EVIDENCE: 근거 없으면 만점 복원) | 〃 |
| `implement_prototype` | 구현 | `artifacts.executable_path` (+ 새 파일) | `{"executable_path": {"before","after"}}` |
| `implement_infographic` | 구현 | `artifacts.infographic_path` (+ 새 파일) | `{"infographic_path": {"before","after"}}` |
| `verify2_static` | 검증-2 | `artifact_score_reasons`(item_code `CHECK-*`) + `artifact_score` | `{"scores": {...}, "artifact_score": {"before","after"}}` |
| `verify2_crosscheck` | 검증-2 | `artifact_score_reasons`(item_code `FEATURE-*`) + `artifact_score` | 〃 |
| `review_expression` | 검수 | `format_findings` 새 행 | `{"finding": {"before","after"}}` |
| `review_token_check` | 검수 | `proofread_logs` 새 행 | `{"corrected_text": {"before","after"}}` |

예시(`writing`):

```json
{ "task_key": "writing" }
```

```json
{
  "project_id": 2, "match_id": 2, "task_key": "writing",
  "agent_name": "작성", "attempt_no": 3,
  "changed": {
    "sections": {
      "1-1": { "before": "...", "after": "..." },
      "2-1": { "before": "...", "after": "..." }
    }
  }
}
```

**같은 body로 다시 호출해보면** `attempt_no`가 1씩 올라가고, `changed`에 담긴 값이 task_key마다 매번 실제로 달라진다 — 이게 이 API가 확인해야 하는 핵심(고정값 반환이 아니라 실제로 다시 계산/재작성). `implement_prototype`/`implement_infographic`은 값뿐 아니라 `/uploads/`에 더미 파일을 매번 새로 하나씩 만들어서 `executable_path`/`infographic_path` 경로 자체도 같이 바뀐다. `verify1_evidence`는 항목마다 대략 30% 확률로 "근거를 못 찾음"을 흉내내는데, 그 경우 `evidence_locator`가 `null`이 되면서 점수가 만점으로 복원된다(E-V1-EVIDENCE 규칙) — 여러 번 호출해봐야 두 경우를 다 볼 수 있다.

먼저 `python seed_dummy_pipeline.py <project_id>`로 계획서/산출물까지 채워둔 프로젝트여야 호출된다(계획서/산출물이 없으면 404). `category='onepage'`인 산출물에 `implement_prototype`을 호출하면 400이 나는 게 정상(원페이지는 설계상 실행 파일이 없음) — 그런 경우엔 `implement_infographic`만 재시도 가능하다.

`python verify_retry_task.py`가 이 API의 10개 task_key 전부와 정상/오류 케이스를 자동으로 검증해준다(1번 참고).

---

## 3. 실제 서버 띄워서 테스트 (Swagger, 구글 로그인 포함)

```
uvicorn app.main:app --reload --port 8000
```

`http://localhost:8000/docs`(Swagger)에서 로그인 없이 되는 API는 바로 호출해볼 수 있다(`127.0.0.1`이 아니라 `localhost`로 — 아래 로그인 테스트와 같은 이유로 세션 쿠키가 안 실려간다). 로그인이 필요한 API(`POST /projects`, `GET /projects/{id}/status` 등)는 실제 구글 로그인이 돼야 브라우저 세션에 쿠키가 생겨서 Swagger에서도 테스트 가능해진다.

### 구글 로그인 + 프로젝트 생성 테스트 (`login_test.html`)

`login_test.html`은 로그인만 하는 게 아니라, 로그인 성공하면 화면에 **프로젝트 만들기 폼**이 나타난다 — 실제 브라우저 세션(쿠키)으로 `POST /projects`까지 그대로 테스트할 수 있다(성공하면 project_id가 나옴 → `python seed_dummy_pipeline.py <project_id>`로 이어가면 됨).

**반드시 웹서버로 띄워서 `http://`로 열어야 한다** — 더블클릭해서 `file://`로 열면 Google Identity Services가 원천적으로 막는다(`file:` origin은 등록 자체가 불가능).

```
cd tests
python -m http.server 5174
```

브라우저에서 **`http://localhost:5174/login_test.html`**로 접속. **`127.0.0.1`이 아니라 꼭 `localhost`로 접속할 것** — 백엔드가 쿠키를 `localhost:8000` 기준으로 내려주는데, 브라우저 SameSite 판정에서 `localhost`와 `127.0.0.1`은 서로 다른 site로 취급돼서, 페이지를 `127.0.0.1`로 열면 로그인 자체는 성공해도 그다음 요청(프로젝트 생성 등)에 쿠키가 안 실려가 버린다(`app/security.py`의 `set_session_cookie` 주석 참고).

그리고 Google Cloud Console → API 및 서비스 → 사용자 인증 정보 → 해당 OAuth 클라이언트 → **승인된 자바스크립트 원본**에 등록(저장 버튼까지 누르기, 반영까지 몇 분~몇 시간 걸릴 수 있음):
- `http://localhost:5174` (이것만 있으면 됨 — 위 이유로 `127.0.0.1`은 안 씀)

이게 되면 `login_test.html`에서 로그인 → 프로젝트 생성까지 화면에서 바로 확인되고, 그 project_id로 Swagger(`http://localhost:8000/docs`, 이것도 `127.0.0.1` 아니고 `localhost`로)에서도 같은 브라우저 세션이면 `GET /projects/{id}/status`가 바로 된다.

---

## 4. (선택) notices 더미 공고 넣기

매칭 로직 테스트하려면 `notices`에 공고가 몇 개는 있어야 한다:

```
python seed_dummy_notices.py
```

`recruitment_status`(진행중/마감), `embedding_status`, 그리고 테스트용으로 임시로 추가한 `eligibility_rule`/`form_spec`(G-01/G-02 로직 테스트용 더미, 실제 AWS DB엔 없는 SQLite 전용 컬럼)까지 채워진 공고 6건이 들어간다. 여러 번 실행해도 안전하다(`notice_id` 중복이면 건너뜀).

---

## 5. (선택, 로컬에 MySQL/MariaDB 있을 때만) 실제 MySQL로 스키마 검증

```
python verify_new_schema_mysql.py
```

로컬에 MariaDB/MySQL 서버가 떠 있고 `sbrain`/`sbrain_pw` 계정에 `sbrain_test` DB가 있어야 돌아간다. 없으면 안 돌려도 된다 — SQLite 기반 검증(1번)으로 로직 자체는 충분히 확인 가능하고, 이건 실제 MySQL 계열 DB에서도 타입/제약이 문제없는지 한 번 더 확인하는 용도다(이미 내가 한 번 돌려서 확인해둠).

---

## 요약 — 뭘 언제 쓰나

| 하고 싶은 것 | 쓸 것 |
|---|---|
| 스키마/로직이 안 깨졌는지 빠르게 확인 | 1번 (`verify_*.py` 4개) |
| admin.py(정책/체크리스트/유저/FAQ 등)가 안 깨졌는지 확인 | 1-1번 (`pytest tests/test_admin.py`) |
| 재시도가 진짜로 값을 바꿔서 반환하는지 확인 | 2-4번 (Swagger) 또는 `verify_retry_task.py` |
| 화면 테스트용 더미 프로젝트 하나 빨리 만들기 (로그인 안 되는 지금) | 2번 (`create_test_project.py` → `seed_dummy_pipeline.py` → `check_project_status.py`) |
| 진짜 구글 로그인 플로우 자체를 확인 | 3번 (`login_test.html`, origin 등록 필요) |
| 매칭/공고 조회 로직 테스트 | 4번 (`seed_dummy_notices.py`) |
| 실제 MySQL 계열 DB에서도 문제없는지 확인 | 5번 (`verify_new_schema_mysql.py`, 선택) |
