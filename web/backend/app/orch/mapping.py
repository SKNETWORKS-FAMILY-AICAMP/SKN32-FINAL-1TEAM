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


# ── 진행 중인 작업이 있어 새로 시작할 수 없을 때(409 blocked) ──────────────────────────
BLOCKED_MESSAGE = ('진행 중인 작업이 있습니다. 이어서 진행하거나, 중단하고 새로 시작할 수 있습니다. '
                   '중단하면 지금까지의 결과를 다시 볼 수 없습니다.')

# RunView.screen_status(진행 중 · 확인 필요 · 문제 발생 · 완료 · 중단됨) → 웹 display_status
_SCREEN_STATUS_TO_DISPLAY: dict[str, str | None] = {
    '진행 중': ps.status_to_display(ps.GENERATION_STATUS_IN_PROGRESS),
    '확인 필요': ps.status_to_display(ps.GENERATION_STATUS_USER_WAITING),
    '문제 발생': ps.status_to_display(ps.GENERATION_STATUS_FAILED),
    '완료': ps.status_to_display(ps.GENERATION_STATUS_COMPLETED),
    '중단됨': ps.status_to_display(ps.GENERATION_STATUS_HALTED),
}


def blocked_detail(active) -> dict:
    """E-RUN-CONCURRENT 409 응답 본문 — ActiveWork(active_work · request_start가 준다)를 웹의 기존 blocked 모양으로."""
    return {
        'message': BLOCKED_MESSAGE,
        'blocked': True,
        'active_project_id': int(active.project_id) if active.project_id is not None else None,
        'active_stage': stage_of(active.step) if active.step is not None else None,
        # 사전 단계(실행 건 없음)가 진행 중이면 결과는 화면 3에서 보인다
        'active_screen': active.resume_step if active.resume_step is not None else ps.NO_MATCH_SCREEN,
        'active_display_status': _SCREEN_STATUS_TO_DISPLAY.get(active.screen_status),
    }


# ── 프로젝트 목록 ─────────────────────────────────────────────────────────────────────
def project_list_item(project, view, notice_title: str | None) -> schemas.ProjectListItemOut:
    """GET /projects 한 줄. 실행 건이 없으면 '매칭 전'(screen=3, 나머지 비움). 사용자 응답이라 실패 사유는 비운다."""
    run = view.run if view is not None else None
    base = {
        'project_id': project.project_id,
        'description': project.description,
        'created_at': project.created_at,
    }
    if run is None:
        return schemas.ProjectListItemOut(**base, screen=ps.NO_MATCH_SCREEN)
    return schemas.ProjectListItemOut(
        **base,
        notice_id=run.announcement_id,
        notice_title=notice_title,
        match_status=match_status_of(run.progress),
        display_status=display_status_of(run.progress),
        stage=stage_of(run.step),
        progress_percent=progress_percent_of(run),
        screen=run.resume_step,
        resume_count=run.resume_count,
        next_retry_at=run.next_resume_at,
        failure_reason=None,
    )


# ── 공고 후보 (화면 3) ────────────────────────────────────────────────────────────────
# 마지막 시작 요청이 이 코드로 실패했으면 웹이 request_start를 다시 부른다(명세 3.1 · 6절 6번)
START_RETRYABLE = frozenset({'E-C1-TIMEOUT', 'X-C2-FAIL', 'E-C2-STALE'})
NO_MATCH_CODE = 'E-C2-NOMATCH'
# 추가 조회가 실패해 기회를 돌려받았다는 안내 — 이게 있으면 '더 보여드릴 공고가 없어요'를 붙이지 않는다
MORE_FAILED_CODES = frozenset({'X-C2-FAIL', 'E-C2-STALE'})
NO_MORE_MESSAGE = '지금은 더 보여드릴 공고가 없어요.'


def _notice_out(notice) -> schemas.OrchNoticeOut:
    return schemas.OrchNoticeOut(code=notice.code, message=notice.message)


def candidate_out(card, batch: int) -> schemas.MatchCandidateOut:
    return schemas.MatchCandidateOut(
        notice_id=card.announcement_id,
        title=card.title,
        org=card.agency,
        apply_end=card.apply_end,
        bonus_score=card.bonus_score,
        reason=card.match_reason,
        url=card.original_url,
        batch=batch,
        rank=card.rank,
        fit_score=card.fit_score,
        content_changed=card.content_changed,
        apply_period_type=card.apply_period_type,
        bonus_items=[schemas.BonusItemOut(name=b.name, points=b.points) for b in card.bonus_items],
        source_notice=card.source_notice,
    )


def candidates_out(screen) -> schemas.MatchCandidatesOut:
    """화면 3(`screen(project_id, 3)`) → 후보 응답. 순서는 공고팀 순위(rank) 그대로 — 웹이 다시 정렬하지 않는다."""
    candidates = [candidate_out(c, 1) for c in screen.candidates]
    candidates += [candidate_out(c, 2) for c in screen.more_candidates]
    return schemas.MatchCandidatesOut(
        candidates=candidates,
        rematch_used=not screen.more_available,
        notices=[_notice_out(n) for n in screen.notices],
        blocked_notice_ids=list(screen.blocked_announcement_ids),
    )


def candidates_unavailable(start) -> schemas.MatchCandidatesOut:
    """실행 건이 아직 없을 때의 응답. start = 마지막 시작 요청(없으면 None)."""
    if start is None:
        return schemas.MatchCandidatesOut(
            candidates=[], rematch_used=False, status='failed',
            message='공고 매칭이 아직 시작되지 않았어요. 새 프로젝트로 다시 시작해 주세요.')
    notices = [_notice_out(n) for n in start.notices]
    if start.status == '실패':
        status = 'no_match' if start.code == NO_MATCH_CODE else 'failed'
        return schemas.MatchCandidatesOut(
            candidates=[], rematch_used=False, status=status, code=start.code, message=start.message,
            notices=notices)
    if start.status == '취소':
        return schemas.MatchCandidatesOut(
            candidates=[], rematch_used=False, status='failed', message='취소된 작업이에요.', notices=notices)
    return pending_candidates(notices)


def pending_candidates(notices: list | None = None) -> schemas.MatchCandidatesOut:
    return schemas.MatchCandidatesOut(candidates=[], rematch_used=False, status='pending', notices=notices or [])


def rematch_message(out: schemas.MatchCandidatesOut) -> str | None:
    """추가 조회 결과에 붙일 문구 — 새 후보가 없고, 실패 안내도 없을 때만 '더 보여드릴 공고가 없어요'."""
    if any(n.code in MORE_FAILED_CODES for n in out.notices):
        return None
    if any(c.batch == 2 for c in out.candidates):
        return None
    return NO_MORE_MESSAGE
