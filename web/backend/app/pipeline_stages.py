"""Agent 파이프라인 진행 상태(match_results.stage) 상수와, 그 상태를 이어하기 화면
번호로 변환하는 매핑. 실제 Agent 파이프라인이 각 단계를 처리할 때마다 이 값들로
match_results.stage(+progress_percent)를 갱신하게 될 것이므로, 값 이름과 의미를
여기 한 군데에 모아둔다 — seed_dummy_pipeline.py(더미)와 실제 파이프라인 코드,
그리고 GET /projects/{id}/status(이어하기 조회) 엔드포인트가 전부 이 상수를 같이 쓴다.

기획서 v1.7 4-7절(p.20 "중단 시점 | 복귀 화면" 표, 8케이스) 및 existing_user_resume_test_report.md
에서 확인한 문제(6/8케이스가 기존 스키마만으로는 서로 구분 안 됨)를 이 stage 필드로 해소한다.
"""

# 화면 번호는 기획서 4-7절 "기본 흐름 — 사용자" 표(1.로그인 ~ 11.결과물 내려받기) 기준.
STAGE_PLAN_WRITING = 'plan_writing'                # 5. 계획서 작성 (시작 전 ~ 진행 중)
STAGE_PLAN_REVIEW_PENDING = 'plan_review_pending'  # 6. 문서 평가 확인 — 판단 대기
STAGE_PROTOTYPE_BUILDING = 'prototype_building'    # 7. 프로토타입 제작
STAGE_ARTIFACT_REVIEW = 'artifact_review'          # 8. 산출물 확인
STAGE_FINAL_REVIEW_PENDING = 'final_review_pending'  # 9. 종합 평가 확인 — 판단 대기
STAGE_REVIEWING = 'reviewing'                      # 10. 표현 검수 — 편도 진입(4-7), 되돌릴 수 없음
STAGE_DONE = 'done'                                # 11. 결과물 내려받기

# 실행 순서 그대로 나열 — 진행 방향 검증이나 "다음 단계" 계산에 재사용한다.
STAGE_SEQUENCE = (
    STAGE_PLAN_WRITING,
    STAGE_PLAN_REVIEW_PENDING,
    STAGE_PROTOTYPE_BUILDING,
    STAGE_ARTIFACT_REVIEW,
    STAGE_FINAL_REVIEW_PENDING,
    STAGE_REVIEWING,
    STAGE_DONE,
)

# stage -> 이어하기 시 돌아갈 화면 번호. match_results 행 자체가 없는 경우(공고 선택 전,
# 기획서 8케이스의 ①)는 화면 3으로 — 이 경우는 stage 필드가 아니라 "match가 없음"으로
# 이미 구분되므로 이 표엔 넣지 않는다(app/routers/projects.py의 상태 조회 로직 참고).
STAGE_TO_SCREEN = {
    STAGE_PLAN_WRITING: 5,
    STAGE_PLAN_REVIEW_PENDING: 6,
    STAGE_PROTOTYPE_BUILDING: 7,
    STAGE_ARTIFACT_REVIEW: 8,
    STAGE_FINAL_REVIEW_PENDING: 9,
    STAGE_REVIEWING: 10,
    STAGE_DONE: 11,
}
NO_MATCH_SCREEN = 3  # match_results 행이 아예 없을 때(8케이스의 ①) 돌아갈 화면

# [2026-09-23 신규] "서비스 내부 상태" 6종 — match_results.status와 agent_executions.status가
# 공유하는 단일 enum이다(app/models.py에서 SQLAlchemy Enum으로 두 컬럼 다 이 값들로 강제).
# 실행/재개대기(자동 재시도 백오프 중)/사용자대기(판단 대기)/실패(재시도 5회 소진 확정)/
# 완료(최종)/중단(멈춤·계정삭제) — app/routers/projects.py GENERATION_RESUME_MAX_ATTEMPTS 등
# 재시도 정책과 함께 쓴다. GENERATION_STATUS_HALTED는 예전부터 admin.py가 '중단' 판정에 쓰던
# 이름을 그대로 가져온 것(원래도 'halted'였음 — 새 이름을 안 만들고 기존 걸 정식화).
GENERATION_STATUS_IN_PROGRESS = 'in_progress'
GENERATION_STATUS_WAITING_RESUME = 'waiting_resume'
GENERATION_STATUS_USER_WAITING = 'user_waiting'
GENERATION_STATUS_FAILED = 'failed'
GENERATION_STATUS_COMPLETED = 'completed'
GENERATION_STATUS_HALTED = 'halted'
GENERATION_STATUSES = (
    GENERATION_STATUS_IN_PROGRESS,
    GENERATION_STATUS_WAITING_RESUME,
    GENERATION_STATUS_USER_WAITING,
    GENERATION_STATUS_FAILED,
    GENERATION_STATUS_COMPLETED,
    GENERATION_STATUS_HALTED,
)

# 위 상태를 화면 알림 문구로 분류한다. 지금 실제로 코드가 만들어내는 값은 in_progress/
# waiting_resume/failed/completed 4개뿐이라(user_waiting·halted는 아직 트리거하는 곳이
# 없음) 결과적으로 화면엔 3가지(진행/실패/완료)만 실제로 나타난다 — 그래도 나머지 두
# 상태가 나중에 생겼을 때 헤매지 않도록 매핑은 5개 다 채워둔다.
STATUS_TO_DISPLAY = {
    GENERATION_STATUS_IN_PROGRESS: '진행',
    GENERATION_STATUS_WAITING_RESUME: '진행',  # 자동 재시도 대기 중도 사용자에겐 그냥 "진행 중"으로 보여준다
    GENERATION_STATUS_USER_WAITING: '확인이 필요합니다',
    GENERATION_STATUS_FAILED: '문제가 생겨 멈췄다',
    GENERATION_STATUS_COMPLETED: '완료',
    GENERATION_STATUS_HALTED: '중단됨',
}


def status_to_display(match_status: str | None) -> str | None:
    """match_results.status를 화면 알림 문구로 바꾼다. 매칭 자체가 없거나(None) 알 수 없는
    값이면 None을 돌려준다 — 프론트가 그 경우 알림 대상에서 제외하면 된다."""
    if match_status is None:
        return None
    return STATUS_TO_DISPLAY.get(match_status)


# [2026-09-27 신규, SB-134] 실패 원인 분류(공식 기능정의서 v1.9 Run.lastErrorKind) — 일시
# 오류만 재개(자동 백오프 재시도)하고, 입력·운영 오류는 영구 오류로 보고 재개 없이 바로
# 실패로 끝낸다(R-11: "일시 오류일 때만 하며 ... 영구 오류가 나면 실행을 실패로 끝낸다").
ERROR_KIND_TRANSIENT = '일시'    # 네트워크 타임아웃 등 — 시간을 두면 나아질 수 있는 오류
ERROR_KIND_INPUT = '입력'        # 입력 데이터 자체의 문제 — 재시도해도 같은 결과
ERROR_KIND_OPERATIONAL = '운영'  # API 연결 끊김·키 만료·크레딧 소진 등 — 사람이 조치해야 함
ERROR_KINDS = (ERROR_KIND_TRANSIENT, ERROR_KIND_INPUT, ERROR_KIND_OPERATIONAL)

# [주의] 지금 파이프라인은 100% 더미(sleep만 함)라 실제 Agent 호출에서 나는 진짜 오류
# 유형(예외 클래스, 응답 코드)이 아직 없다 — 그래서 이 분류는 예외 메시지의 키워드로
# 판단하는 임시 방편이다. 실제 Agent 호출 계층이 생기면, 예외 클래스나 API 응답 코드로
# 판단하는 훨씬 정확한 방식으로 교체해야 한다(예: 인증 실패 예외 -> 운영, 스키마 검증
# 실패 예외 -> 입력, 나머지 -> 일시).
_OPERATIONAL_KEYWORDS = ('api 연결', '연결 끊', '키 만료', '크레딧', 'api key', 'credit', 'connection refused', 'unauthorized')
_INPUT_KEYWORDS = ('입력값', '형식 오류', 'validation', 'invalid input', 'malformed')


def classify_error_kind(exc: BaseException) -> str:
    """예외가 이미 분류를 갖고 있으면(향후 실제 Agent 연동 시 Orchestration tools.llm의
    ToolCallExhausted처럼 error_kind 속성을 직접 실어오는 예외) 그 값을 그대로 쓰고,
    없을 때만(지금 더미 파이프라인처럼) 예외 메시지 키워드로 추측한다 — 프론트 3차
    요청 B-3. 키워드로도 못 맞추면 기본값은 '일시'다 — 지금까지 해온 대로 "일단 재개를
    시도해본다"는 기존 동작과 같다(모르는 오류를 섣불리 영구 오류로 단정해 재개 기회
    자체를 없애지 않기 위함)."""
    declared = getattr(exc, 'error_kind', None)
    if declared in ERROR_KINDS:
        return declared
    message = str(exc).lower()
    if any(kw in message for kw in _OPERATIONAL_KEYWORDS):
        return ERROR_KIND_OPERATIONAL
    if any(kw in message for kw in _INPUT_KEYWORDS):
        return ERROR_KIND_INPUT
    return ERROR_KIND_TRANSIENT


# [2026-09-27 신규, SB-141] 사용자용 작업 알림(Notification) 종류 — 공식 기능정의서
# v1.9. 문서평가/산출물확인/표현검수는 각 단계(검증-1/검증-2/검수)가 끝났을 때, 실패는
# 실행 실패·재작성 실패 둘 다에 쓴다(failureScope로 구분). '완료'는 kind에 없다 — 결과물
# 화면에 사용자가 직접 들어가 있는 상태라 별도 알림이 필요 없다.
NOTIFICATION_KIND_DOC_REVIEW = '문서평가'
NOTIFICATION_KIND_ARTIFACT_REVIEW = '산출물확인'
NOTIFICATION_KIND_PROOFREADING = '표현검수'
NOTIFICATION_KIND_FAILURE = '실패'
NOTIFICATION_KINDS = (
    NOTIFICATION_KIND_DOC_REVIEW,
    NOTIFICATION_KIND_ARTIFACT_REVIEW,
    NOTIFICATION_KIND_PROOFREADING,
    NOTIFICATION_KIND_FAILURE,
)
NOTIFICATION_FAILURE_SCOPE_RUN = '실행'
NOTIFICATION_FAILURE_SCOPE_REWORK = '재작성'
NOTIFICATION_FAILURE_SCOPES = (NOTIFICATION_FAILURE_SCOPE_RUN, NOTIFICATION_FAILURE_SCOPE_REWORK)
# [주의] 산출물확인/표현검수는 지금 더미 파이프라인에 해당 stage(artifact_review/
# reviewing) 전환 자체가 없어서 아직 트리거되지 않는다(GENERATION_STATUS_USER_WAITING/
# HALTED와 같은 사정) — 실제 검증-2/검수 단계가 붙으면 그때 생성 지점을 추가하면 된다.
NOTIFICATION_CHANNEL_SCREEN = '화면'  # 지금은 이거 하나뿐 — 메일 알림은 향후 도입(4-2 ⑧)

# kind -> 알림을 누르면 들어갈 화면 번호(기획서 4-7 기본 흐름). 문서평가는 검증-1이 끝난
# 뒤 사용자가 판단하는 화면(6), 산출물확인은 검증-2 뒤 점검 결과 화면(8), 표현검수는
# 검수 완료 뒤 결과물 화면(10). 실패는 들어갈 화면이 없어 이어하기 목록으로 연결한다
# (target_step=None).
NOTIFICATION_KIND_TO_TARGET_STEP = {
    NOTIFICATION_KIND_DOC_REVIEW: STAGE_TO_SCREEN[STAGE_PLAN_REVIEW_PENDING],
    NOTIFICATION_KIND_ARTIFACT_REVIEW: STAGE_TO_SCREEN[STAGE_ARTIFACT_REVIEW],
    NOTIFICATION_KIND_PROOFREADING: STAGE_TO_SCREEN[STAGE_REVIEWING],
}

# stage에 도달했을 때 어떤 kind의 알림을 만들지 — _simulate_generation의 성공 경로가
# done_stage로 이 표를 찾아본다. STAGE_ARTIFACT_REVIEW/STAGE_REVIEWING은 지금 더미
# 파이프라인의 (running_stage, done_stage) 조합에 아직 안 나오지만, 실제 검증-2/검수
# 단계가 붙어 나오게 되면 이 표만으로 자동으로 알림이 생긴다(호출부 수정 불필요).
STAGE_TO_NOTIFICATION_KIND = {
    STAGE_PLAN_REVIEW_PENDING: NOTIFICATION_KIND_DOC_REVIEW,
    STAGE_ARTIFACT_REVIEW: NOTIFICATION_KIND_ARTIFACT_REVIEW,
    STAGE_REVIEWING: NOTIFICATION_KIND_PROOFREADING,
}

# [2026-09-28 신규] plan_sections.tag를 MySQL 실제 ENUM 컬럼으로 만들기 위한 고정 코드
# 목록. 공식 기능정의서 v1.9(FormSpec.sectionCodes)는 "'1-1','2-1','3-3' 같은 문자열"이라고만
# 하고 닫힌 집합을 정의하지 않는다(공고마다 양식이 달라질 수 있어서) — 그래서 목록 자체는
# 기능정의서가 아니라 우리가 지금 실제로 지원하는 계획서 템플릿(예비/초기=3섹션, 일반=4섹션)
# 기준으로 정한 것이다. 예비/초기는 agents.py가 이미 쓰고 있는 '1-1'/'2-1'/'3-1'을 그대로
# 두고(라이브 코드 변경 최소화), '일반'(기술개발사업계획서 PartⅡ, 4_(1-2)사업계획서_작성_
# 예시_사업계획서_Part2.pdf 확인) 전용으로 'G-01'~'G-04' 4자 코드를 새로 추가했다.
PLAN_SECTION_TAG_PROBLEM = '1-1'  # 문제인식 (예비·초기)
PLAN_SECTION_TAG_FEASIBILITY = '2-1'  # 실현가능성 (예비·초기)
PLAN_SECTION_TAG_GROWTH = '3-1'  # 성장전략 (예비·초기)
# [2026-09-29 신규, SB-165 후속] SB-165가 재작성 묶음(bundle_id)을 PSST 4항목(문제인식/
# 실현가능성/성장전략/팀 구성)으로 확정했는데, 예비·초기 템플릿엔 "팀 구성"에 대응하는
# 섹션이 없었다 — writing 재시도가 bundle_id를 무시하고 항상 1-1/2-1만 재생성하던 버그의
# 근본 원인. PSST 4번째 항목에 맞춰 4-1을 추가한다(아래 BUNDLE_PSST_TO_SECTION_TAG 참고).
PLAN_SECTION_TAG_TEAM = '4-1'  # 팀 구성 (예비·초기)
PLAN_SECTION_TAG_GENERAL_OVERVIEW = 'G-01'  # 기술개발의 개요 및 필요성 (일반)
PLAN_SECTION_TAG_GENERAL_GOAL = 'G-02'  # 기술개발의 목표 (일반)
PLAN_SECTION_TAG_GENERAL_METHOD = 'G-03'  # 기술개발의 방법 (일반)
PLAN_SECTION_TAG_GENERAL_BIZ_PLAN = 'G-04'  # 사업화 계획 (일반)
PLAN_SECTION_TAGS = (
    PLAN_SECTION_TAG_PROBLEM,
    PLAN_SECTION_TAG_FEASIBILITY,
    PLAN_SECTION_TAG_GROWTH,
    PLAN_SECTION_TAG_TEAM,
    PLAN_SECTION_TAG_GENERAL_OVERVIEW,
    PLAN_SECTION_TAG_GENERAL_GOAL,
    PLAN_SECTION_TAG_GENERAL_METHOD,
    PLAN_SECTION_TAG_GENERAL_BIZ_PLAN,
)

# [2026-09-28 신규] user_profiles.biz_status_cd — 국세청 사업자상태조회(POST /biz-check)
# 응답 코드를 MySQL 실제 ENUM으로 저장한다. 값 자체는 이 프로젝트가 정한 게 아니라 국세청
# API 응답 코드 그대로다(01 계속/02 휴업/03 폐업, models.py UserProfile 기존 주석 참고).
BIZ_STATUS_CODE_ACTIVE = '01'
BIZ_STATUS_CODE_SUSPENDED = '02'
BIZ_STATUS_CODE_CLOSED = '03'
BIZ_STATUS_CODES = (BIZ_STATUS_CODE_ACTIVE, BIZ_STATUS_CODE_SUSPENDED, BIZ_STATUS_CODE_CLOSED)

# [2026-09-28 신규] match_results.stage(=_simulate_generation이 도는 단계) 실패를
# agent_executions에도 남기기 위한 매핑 — 이 테이블엔 stage 컬럼이 없고 agent_name/
# task_key로만 구분하므로, 어느 단계가 실패했는지를 FIXED_TASK_SEQUENCE(app/models.py)의
# 가장 대표적인 task_key로 근사한다(계획서 작성 단계 전체 실패는 '작성'/'writing'으로,
# 프로토타입 제작 단계 전체 실패는 '구현'/'implement_prototype'으로 기록).
STAGE_TO_AGENT_TASK = {
    STAGE_PLAN_WRITING: ('작성', 'writing'),
    STAGE_PROTOTYPE_BUILDING: ('구현', 'implement_prototype'),
}

# [2026-09-28 신규] 마이페이지/프로젝트 작성란 "주업종" — front/src/features/mypage/
# derive.js INDUSTRY_OPTIONS와 동일(개인/법인 전용 드롭다운 9종). 예비창업자는 이
# 목록이 아니라 자유 텍스트를 입력하므로(front IndustryField.selectable=false) 그 값은
# ProjectPlanInput.main_industry_free(자유 문자열)에 따로 담고, 이 ENUM은 main_industry
# 컬럼(개인/법인 전용)에만 적용한다.
MAIN_INDUSTRIES = ('제조', '지식서비스', '기계·소재', '전기·전자', '정보·통신', '화공·섬유', '바이오·의료·생명', '에너지·자원', '공예·디자인')

# [2026-09-28 신규, SB-152 프론트 답변 반영] "재작성" 상한(VerificationPolicy.rework_cap)은
# task_key 단위가 아니라 화면에 보이는 "묶음(bundle)" 단위로 세야 한다 — writing 하나의
# task_key 안에 화면상 별개인 묶음 여러 개가 들어있어서, task_key로만 세면 묶음 하나만
# 재작성해도 다른 묶음 재작성 기회까지 같이 깎이는 버그가 생긴다(프론트 답변 md "⚠ 중요
# — bundle_id를 task_key로 잡으면 안 됩니다" 참고). 산출물(구현) 쪽은 이미 task_key와
# 묶음이 1:1이라 문제 없다.
#
# [2026-09-29 개정, SB-165] 묶음 = Task 이름(본문/차트/표)이 아니라 PSST 평가 항목
# 4개(문제인식/실현가능성/성장전략/팀 구성)로 확정 — front/src/features/workflow/data.js
# DOC_REWORK_BUNDLES와 반드시 같은 값이어야 한다(프론트가 그 라벨을 bundle_id로 그대로
# 보낸다). PSST = Problem·Solution·Scale-up·Team.
BUNDLE_PSST_PROBLEM = '문제인식'
BUNDLE_PSST_SOLUTION = '실현가능성'
BUNDLE_PSST_SCALEUP = '성장전략'
BUNDLE_PSST_TEAM = '팀 구성'
WRITING_BUNDLES = (BUNDLE_PSST_PROBLEM, BUNDLE_PSST_SOLUTION, BUNDLE_PSST_SCALEUP, BUNDLE_PSST_TEAM)

# [2026-09-29 신규] writing 재시도(app/routers/projects.py retry_task)가 bundle_id를
# 무시하고 항상 plan_sections의 1-1/2-1만 재생성하던 버그의 수정 — 묶음마다 정확히
# 재생성해야 할 문서 섹션 하나를 여기서 고정한다(둘 다 이 파일이 소유하는 상수라 여기
# 두는 게 자연스럽다). WRITING_BUNDLES의 모든 항목이 키로 있어야 한다.
BUNDLE_PSST_TO_SECTION_TAG = {
    BUNDLE_PSST_PROBLEM: PLAN_SECTION_TAG_PROBLEM,
    BUNDLE_PSST_SOLUTION: PLAN_SECTION_TAG_FEASIBILITY,
    BUNDLE_PSST_SCALEUP: PLAN_SECTION_TAG_GROWTH,
    BUNDLE_PSST_TEAM: PLAN_SECTION_TAG_TEAM,
}

BUNDLE_ARTIFACT_PROTOTYPE = '실행 파일 제작'
BUNDLE_ARTIFACT_INFOGRAPHIC = '인포그래픽 제작'

BUNDLE_LAYER_DOCUMENT = 'document'
BUNDLE_LAYER_ARTIFACT = 'artifact'

# implement_prototype/implement_infographic은 이미 task_key와 묶음이 1:1이라 요청에
# bundle_id를 따로 안 보내도(또는 보내도) 이 값으로 고정된다.
TASK_KEY_TO_FIXED_BUNDLE = {
    'implement_prototype': BUNDLE_ARTIFACT_PROTOTYPE,
    'implement_infographic': BUNDLE_ARTIFACT_INFOGRAPHIC,
}
BUNDLE_TO_LAYER = {
    BUNDLE_PSST_PROBLEM: BUNDLE_LAYER_DOCUMENT,
    BUNDLE_PSST_SOLUTION: BUNDLE_LAYER_DOCUMENT,
    BUNDLE_PSST_SCALEUP: BUNDLE_LAYER_DOCUMENT,
    BUNDLE_PSST_TEAM: BUNDLE_LAYER_DOCUMENT,
    BUNDLE_ARTIFACT_PROTOTYPE: BUNDLE_LAYER_ARTIFACT,
    BUNDLE_ARTIFACT_INFOGRAPHIC: BUNDLE_LAYER_ARTIFACT,
}