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