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
# 완료(최종)/중단(멈춤·계정삭제) — app/routers/projects.py GENERATION_RETRY_MAX_ATTEMPTS 등
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