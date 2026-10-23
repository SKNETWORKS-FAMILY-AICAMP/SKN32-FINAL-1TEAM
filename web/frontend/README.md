# S-Brain 프런트엔드

창업 아이템을 입력받아 정부지원사업 공고 매칭 → 자격 확인 → 사업계획서 → 프로토타입 → 검증 → 최종 결과물까지 이어지는 S-Brain의 웹 화면입니다. 랜딩, 프로젝트 워크스페이스, 마이페이지, 관리자 대시보드로 구성되며 모든 데이터는 `web/backend`(FastAPI)에서 받아옵니다.

React 18 · Vite · Tailwind CSS · zustand를 사용합니다.

## 실행

Node.js 22.12 이상이 필요합니다. 백엔드(`web/backend`, 기본 `http://localhost:8000`)가 먼저 떠 있어야 로그인과 프로젝트 기능이 동작합니다. 백엔드 실행 방법은 `web/backend/README.md`를 봅니다.

```sh
cp .env.example .env   # 값 채우기 (아래 "환경 변수")
npm ci
npm run dev            # http://localhost:5174
```

브라우저에서는 **반드시 `http://localhost:5174`로 접속**합니다. `127.0.0.1`로 열면 구글 로그인 origin 검증(`origin_mismatch`)에 걸리고, 로그인이 되더라도 세션 쿠키가 `localhost`와 `127.0.0.1`을 다른 site로 취급해 다음 요청에 실리지 않습니다. (`npm run dev`가 `--host localhost`로 띄우는 것도 같은 이유입니다.)

| 명령 | 하는 일 |
|---|---|
| `npm run dev` | 개발 서버 (포트 5174 고정) |
| `npm run build` | 배포용 정적 파일을 `dist/`에 생성 |
| `npm run preview` | 빌드 결과 미리보기 |
| `npm run check:render` | 주요 화면을 서버 렌더링해 깨지는 컴포넌트가 없는지 확인 (아래 "검증") |
| `npm run standalone` | 빌드 후 상위 폴더에 단일 HTML `S-Brain-redesign.html` 생성. 백엔드 주소는 빌드 시점의 `VITE_API_BASE`가 들어갑니다 |

## 환경 변수

`.env.example`을 복사해 씁니다. `VITE_`로 시작하는 값은 빌드 결과에 그대로 들어가 브라우저로 내려가므로 비밀값을 넣지 않습니다.

| 이름 | 설명 |
|---|---|
| `VITE_GOOGLE_CLIENT_ID` | 구글 로그인 클라이언트 ID |
| `VITE_API_BASE` | 백엔드 주소. 기본 `http://localhost:8000`. 프런트와 마찬가지로 `localhost`로 맞춰야 쿠키가 실립니다 |

## 백엔드 연동

- 모든 호출은 `src/api.js`를 거칩니다. 세션은 httpOnly 쿠키라 매 요청에 `credentials: 'include'`를 붙입니다.
- 액세스 토큰(30분)이 만료돼 401이 오면 `POST /auth/refresh`로 한 번 갱신하고 원래 요청을 다시 보냅니다. 동시에 여러 요청이 401을 받아도 갱신은 한 번만 나갑니다.
- 서버 오류는 `ApiError`(`status`, `detail`, `code`)로 올라옵니다. 화면은 `code`(예: `BUSY`, `CONFIRMATION_REQUIRED`, `E-RUN-CONCURRENT`)로 분기하고, 없으면 `detail` 문구를 보여 줍니다.
- 계획서 · 프로토타입 생성은 시작 요청만 보내고 바로 돌아오며, 진행률은 `GET /projects/{id}/status`를 주기적으로 조회해 표시합니다(`GenerationProgress`, `PlanForm`).
- 관리자 여부는 `GET /auth/me`가 내려주는 `role === 'admin'`으로 판단합니다. 관리자 화면은 `/admin/*` API를 씁니다.
- 서버 시각은 UTC로 오므로 `src/time.js`에서 한국 시간으로 바꿔 표시합니다.

## 화면 흐름

워크스페이스의 화면 전환은 `src/App.jsx`의 `view` 값으로 관리합니다.

1. `intake` — 아이템 정보 입력 (첨부 파일 포함, `POST /projects`)
2. `match-progress` → `match-results` — 공고 매칭 결과 10건, 프로젝트당 1회 다시 찾기
3. `eligibility-gate` — 고른 공고의 자격 확인
4. `plan-progress` → `plan-form` — 사업계획서 생성과 평가 점수, 묶음별 재작성
5. `artifact-progress` → `artifact-result` — 프로토타입(실행 파일) · 인포그래픽과 검증 점수, 재작성
6. `final-verdict` — 종합 평가
7. `review-progress` → `review` — 최종 결과물 다운로드 (사업계획서 .docx/.hwp, prototype.zip, 검증결과서 PDF, 전체 묶음 `deliverable.zip`)

그 밖에 `landing`, `dashboard`(내 프로젝트 · 이어하기 · 삭제), `mypage`(기본 정보 · 역량 · 팀), `admin`이 있습니다. 계정당 동시 실행은 1건이며, 이미 진행 중이면 `RunBlockedDialog`로 이어하기 / 새로 시작을 고르게 합니다.

## 구조

```
src/
├── main.jsx                 진입점
├── App.jsx                  화면 전환, 로그인 상태, 프로젝트별 상태 연결
├── api.js                   백엔드 호출 공용 헬퍼와 엔드포인트별 함수
├── time.js                  UTC → 한국 시간 표시
├── styles.css               디자인 토큰, 공통 · 반응형 스타일
├── components/
│   ├── Landing.jsx          서비스 소개, 결과물 탭, FAQ
│   ├── LandingDepthGallery.jsx  랜딩의 단계별 소개 갤러리
│   ├── Login.jsx            구글 로그인 · 약관 동의 모달
│   ├── Workspace.jsx        워크스페이스 레이아웃, 프로젝트 목록, 검색 · 상태 필터
│   ├── Preparation.jsx      매칭 · 계획서 · 산출물 · 결과물 준비 진행 화면 (서버 진행률 0~100 표시)
│   ├── RunDialogs.jsx       동시 실행 제한 안내, 공고 마감 배너
│   └── Icons.jsx            공통 아이콘과 로고
├── features/
│   ├── Workflow.jsx         workflow/의 화면들을 묶어 내보냄
│   ├── workflow/            화면 흐름 1~7의 각 화면, 재작성(rework.js), 검증결과서 양식(verificationReport.js)
│   ├── mypage/              마이페이지 (기본 정보, 사업자번호, 역량 · 팀)
│   └── Admin.jsx            관리자 대시보드 6개 탭: 공고 관리 · 운영 현황 · 진행 현황 · 에이전트 테스크 · 검증 정책 · 사용자 관리·FAQ
├── store/                   zustand 상태 (워크플로우, 마이페이지)
├── dummyDeliverables.js     projectId가 없는 미리보기 화면 전용 예시 파일 생성기 (실제 프로젝트는 서버 파일을 받음)
├── audit.jsx                audit.html용 화면 상태 점검 페이지
└── assets/fonts/            나눔스퀘어라운드 (외부 폰트 요청 없음)
```

## 검증

- `npm run check:render`: 랜딩, 워크스페이스, 대시보드, 흐름의 각 화면을 서버 렌더링해 정의되지 않은 컴포넌트 · 속성 오류를 잡습니다. 브라우저 클릭 테스트나 백엔드 연동 확인을 대신하지는 않습니다.
- `audit.html`: 여러 화면 상태를 한 페이지에서 직접 확인하는 개발용 검토 페이지입니다. 배포되는 빌드에는 포함되지 않습니다.

## 디자인

화이트 · 라이트 그레이 · 블루를 중심으로 간결한 한국어 제목, 넉넉한 여백, 명확한 행동 버튼을 씁니다. 진행 상황은 큰 진행 숫자와 단계별 상태 목록으로 보여 줍니다. 작은 화면에서는 콘텐츠를 한 열로 배치하고 단계 메뉴만 가로로 스크롤하며, 움직임 감소 설정을 지원합니다. 애니메이션은 별도 라이브러리 없이 CSS로 구현했습니다.
