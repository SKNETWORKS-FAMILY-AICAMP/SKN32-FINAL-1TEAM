"""오케스트레이터 결과 → 웹 응답 값 변환 (웹연동_변경사항_웹팀전달.md 3절 대응표).

- 결과 객체는 속성으로만 읽는다(duck typing). sbrain을 import하지 않아 가짜 오케스트레이터로 테스트할 수 있다.
- 시각은 오케스트레이터가 UTC로 준다(2026-10-05 합의). 웹의 다른 시각 값과 같은 방식(UTC naive)이라 그대로 통과시킨다.
"""
from app import pipeline_stages as ps
from app import schemas

# 3.1 단계 — 기준 문서 단계 ↔ 웹 stage. 공고선택 · 자격확인은 웹 stage가 없다(NULL).
STEP_TO_STAGE: dict[str, str | None] = {
    '공고선택': None,
    '자격확인': None,
    '계획서작성': ps.STAGE_PLAN_WRITING,
    '문서평가': ps.STAGE_PLAN_REVIEW_PENDING,
    '프로토타입제작': ps.STAGE_PROTOTYPE_BUILDING,
    '산출물확인': ps.STAGE_ARTIFACT_REVIEW,
    '종합평가': ps.STAGE_FINAL_REVIEW_PENDING,
    '표현검수': ps.STAGE_REVIEWING,
    '결과물': ps.STAGE_DONE,
}

# 3.2 진행 상태 — progress ↔ 웹 match_status (화면 문구는 ps.status_to_display가 만든다)
PROGRESS_TO_MATCH_STATUS: dict[str, str] = {
    '실행': ps.GENERATION_STATUS_IN_PROGRESS,
    '재개대기': ps.GENERATION_STATUS_WAITING_RESUME,
    '사용자대기': ps.GENERATION_STATUS_USER_WAITING,
    '실패': ps.GENERATION_STATUS_FAILED,
    '완료': ps.GENERATION_STATUS_COMPLETED,
    '중단': ps.GENERATION_STATUS_HALTED,
}

# 3.4 카테고리
CATEGORY_TO_WEB: dict[str, str] = {'원페이지': 'onepage', '웹개발': 'webdev', 'AI_API': 'aiapi'}

CLOSED_NOTICE_CODE = 'E-RUN-CLOSED'

# progress_percent를 내려줄 단계. 한 단계 안에서도 오래 걸리는 구간만(웹 기존 규칙 + 표현 검수). 잠정(명세 12절).
_PERCENT_STEPS = frozenset({'계획서작성', '프로토타입제작', '표현검수'})
_RUNNING = frozenset({'실행', '재개대기'})


def match_status_of(progress: str) -> str:
    return PROGRESS_TO_MATCH_STATUS[progress]


def display_status_of(progress: str) -> str | None:
    return ps.status_to_display(match_status_of(progress))


def stage_of(step: str) -> str | None:
    return STEP_TO_STAGE[step]


def progress_percent_of(run) -> int | None:
    """실행 중인 오래 걸리는 구간(또는 재작성 중)만 값이 있고 나머지는 None."""
    if run.progress not in _RUNNING:
        return None
    if run.step in _PERCENT_STEPS or run.rework_screen is not None:
        return run.percent
    return None


def notice_closed_of(run) -> bool:
    return any(n.code == CLOSED_NOTICE_CODE for n in run.notices)


class NotReworkable(ValueError):
    """사용자 재작성 대상이 아닌 task_key이거나 묶음 이름이 맞지 않음."""


# 3.3 재작성 묶음 — 웹 (task_key, bundle_id) ↔ 오케스트레이터 묶음 이름
_ARTIFACT_BUNDLES: dict[str, tuple[str, str]] = {
    'implement_prototype': (ps.BUNDLE_ARTIFACT_PROTOTYPE, '실행 파일'),
    'implement_infographic': (ps.BUNDLE_ARTIFACT_INFOGRAPHIC, '인포그래픽'),
}
_ORCH_TO_WEB_BUNDLE: dict[str, str] = {
    **{name: name for name in ps.WRITING_BUNDLES},
    **{orch: web for web, orch in _ARTIFACT_BUNDLES.values()},
}


def orch_bundle_of(task_key: str, bundle_id: str | None) -> str:
    """retry-task 요청 → request_rework_for_project의 bundle 이름."""
    if task_key == 'writing':
        if bundle_id not in ps.WRITING_BUNDLES:
            raise NotReworkable(f'writing 재작성은 bundle_id가 필요합니다: {bundle_id!r}')
        return bundle_id
    if task_key in _ARTIFACT_BUNDLES:
        web_name, orch_name = _ARTIFACT_BUNDLES[task_key]
        if bundle_id is not None and bundle_id != web_name:
            raise NotReworkable(f'{task_key}의 묶음은 {web_name!r}입니다: {bundle_id!r}')
        return orch_name
    raise NotReworkable(f'사용자 재작성 대상이 아닙니다: {task_key!r}')


def web_bundle_id_of(orch_bundle: str) -> str:
    """reworkUsage의 묶음 이름 → 웹 bundle_id."""
    return _ORCH_TO_WEB_BUNDLE[orch_bundle]


def project_status_out(project_id: int, view) -> schemas.ProjectStatusOut:
    """GET /projects/{id}/status 응답 (view = view_project 결과). 실패 사유는 사용자 응답에 싣지 않는다."""
    run = view.run
    if run is None:
        return schemas.ProjectStatusOut(project_id=project_id, screen=ps.NO_MATCH_SCREEN)
    return schemas.ProjectStatusOut(
        project_id=project_id,
        screen=run.resume_step,
        stage=stage_of(run.step),
        progress_percent=progress_percent_of(run),
        match_status=match_status_of(run.progress),
        failure_reason=None,
        resume_count=run.resume_count,
        next_retry_at=run.next_resume_at,
        notice_closed=notice_closed_of(run),
    )
