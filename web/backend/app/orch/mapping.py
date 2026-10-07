"""오케스트레이터 결과 → 웹 응답 값 변환 (웹연동_변경사항_웹팀전달.md 3절 대응표).

- 결과 객체는 속성으로만 읽는다(duck typing). sbrain을 import하지 않아 가짜 오케스트레이터로 테스트할 수 있다.
- 시각은 오케스트레이터가 UTC로 준다(2026-10-05 합의). 웹의 다른 시각 값과 같은 방식(UTC naive)이라 그대로 통과시킨다.
"""
from app import pipeline_stages as ps
from app import schemas
from app.artifact_store import artifact_url

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
        rework_screen=run.rework_screen,
        collecting=run.collecting,
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
        rework_screen=run.rework_screen,
        collecting=run.collecting,
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


# ── 공고 선택 → 자격 확인 (화면 4) · 지금까지 결과 (outputs) ─────────────────────────────
G1_FAILED_CODES = frozenset({'X-C2-GONE', 'X-C2-FAIL'})  # 자격 확인(G-01)이 공고 서버 오류로 못 끝났을 때
SELECT_FAILED_MESSAGE = '공고를 확인하지 못했어요. 잠시 뒤 다시 시도해 주세요.'
FEATURE_MATCH_MAX = 15  # 기능 대조 점수의 상한(오케스트레이터 모델 제약 0~15)
# 웹 정책 행이 없을 때 쓰는 층별 만점(문서 70 · 산출물 30 = 코드 15 + 대조 15, 기능정의서 기본값)
DEFAULT_DOC_MAX, DEFAULT_CODE_MAX, DEFAULT_PLAN_MAX = 70.0, 15.0, 15.0


def notices_out(notices) -> list[schemas.OrchNoticeOut]:
    return [_notice_out(n) for n in notices]


def eligibility_out(
    gate, business_age_years: float | None = None, can_start_writing: bool | None = None,
) -> schemas.EligibilityCheckOut:
    """자격 확인 결과. 업력 · 작성 가능 여부는 화면 4(screen)가 주는 값을 넘긴다. 작성 가능 여부를 모르는 곳(outputs — 이미 작성 단계를
    지난 실행 건)에서는 통과 여부로 대신한다(화면 4도 통과해 작성 단계로 들어가면 참이다)."""
    return schemas.EligibilityCheckOut(
        passed=gate.passed,
        undecidable=gate.undecidable,
        failed_conditions=list(gate.failed_conditions),
        missing_inputs=list(gate.missing_inputs),
        unknown_conditions=list(gate.unknown_conditions),
        business_age_years=business_age_years,
        can_start_writing=gate.passed if can_start_writing is None else can_start_writing,
    )


def _find_card(outputs, announcement_id: str | None):
    for card in [*outputs.candidates, *outputs.more_candidates]:
        if card.announcement_id == announcement_id:
            return card
    return None


def match_out(outputs, announcement_id: str | None = None) -> schemas.MatchResultOut | None:
    """선택 공고와 그 카드(적합도 · 이유). announcement_id를 안 주면 outputs의 선택 공고."""
    selected = outputs.selected_announcement
    notice_id = announcement_id or (selected.announcement_id if selected is not None else None)
    if notice_id is None:
        return None
    card = _find_card(outputs, notice_id)
    return schemas.MatchResultOut(
        notice_id=notice_id,
        fit_score=card.fit_score if card is not None else None,
        reason=card.match_reason if card is not None else None,
        status=match_status_of(outputs.progress),
    )


def select_failed(project_id: int, notices: list) -> schemas.DemoGenerateResponse:
    """공고 서버 오류 · 공고 없음으로 자격 확인을 못 끝냈다 — 고르기 전 화면으로 돌아간다."""
    failed = [n for n in notices if n.code in G1_FAILED_CODES]
    return schemas.DemoGenerateResponse(
        project_id=project_id, status='failed',
        code=failed[-1].code if failed else None,
        message=failed[-1].message if failed else SELECT_FAILED_MESSAGE,
        notices=notices_out(notices))


def select_pending(project_id: int) -> schemas.DemoGenerateResponse:
    return schemas.DemoGenerateResponse(project_id=project_id, status='pending')


# ── 계획서 본문 ───────────────────────────────────────────────────────────────────────
def section_body(section) -> str:
    """섹션의 문장을 문단(paragraph_no)별로 이어 붙인다 — 문단 사이는 줄바꿈."""
    paragraphs: dict[int, list[str]] = {}
    for sentence in section.sentences:
        paragraphs.setdefault(sentence.paragraph_no, []).append(sentence.text)
    return '\n'.join(' '.join(texts) for _, texts in sorted(paragraphs.items()))


def section_bodies(plan_doc) -> dict[str, str]:
    """섹션 코드 → 본문. 계획서 내려받기(.docx · .pdf · .hwp)가 쓴다."""
    return {s.section_code: section_body(s) for s in plan_doc.sections}


def plan_sections_out(plan_doc) -> list[schemas.PlanSectionOut]:
    return [schemas.PlanSectionOut(tag=s.section_code, title=s.title, body=section_body(s)) for s in plan_doc.sections]


# ── 점수 ──────────────────────────────────────────────────────────────────────────────
def plan_score_reasons(outputs) -> list[schemas.PlanScoreReasonOut]:
    """문서층 항목별 점수. 항목 이름은 작업 분해가 고른 평가 항목(evaluationItems)에서 만든다."""
    if outputs.doc_score is None:
        return []
    names = {e.item_code: e.item_name for e in outputs.evaluation_items}
    return [
        schemas.PlanScoreReasonOut(
            reason_text=i.comment, item_code=i.item_code, display_name=names.get(i.item_code),
            score=i.score, max_score=i.max_score)
        for i in outputs.doc_score.items
    ]


WITHHELD_REASON_TEXT = '계획서와 구현 기능을 대조하지 못했습니다(대조 불가). 이 항목은 0점으로 합산됩니다.'


def artifact_score_reasons(outputs) -> list[schemas.ArtifactScoreReasonOut]:
    """산출물층 — 코드 점검은 항목마다 'CHECK-이름', 기능 대조는 하나로 'FEATURE-MATCH'(접두어가 프론트가 층을 가르는 기준)."""
    reasons: list[schemas.ArtifactScoreReasonOut] = []
    if outputs.code_check is not None:
        for c in outputs.code_check.checks:
            reasons.append(schemas.ArtifactScoreReasonOut(
                reason_text=c.detail, item_code=f'CHECK-{c.name}', display_name=c.name,
                score=c.weight if c.passed else 0, max_score=c.weight))
    if outputs.feature_match is not None:
        fm = outputs.feature_match
        notes = [*fm.findings, *[f'누락 기능: {m}' for m in fm.missing_features],
                 *[f'부분 인정 기능: {m}' for m in (getattr(fm, 'partial_features', None) or [])]]
        if fm.withheld:  # 판정 보류 — 점수는 0점으로 합산되고 화면은 '대조 불가'로 보인다(SB-301)
            reason_text = WITHHELD_REASON_TEXT
        else:
            reason_text = ' / '.join(notes) or '계획서와 구현 기능이 맞습니다.'
        reasons.append(schemas.ArtifactScoreReasonOut(
            reason_text=reason_text, item_code='FEATURE-MATCH',
            display_name='계획서 대조', score=fm.score, max_score=FEATURE_MATCH_MAX))
    return reasons


# 통과 필수 조건 코드(구현 Agent · 검증-2 계약의 gate_failures 값) → 화면 이름
GATE_NAMES = {'entry': '진입 파일', 'secret': '비밀값', 'sandbox': '격리 화면 동작'}


def gate_failures_out(outputs) -> list[schemas.GateFailureOut]:
    code_check = outputs.code_check
    return [
        schemas.GateFailureOut(code=code, display_name=GATE_NAMES.get(code, code))
        for code in (getattr(code_check, 'gate_failures', None) or [])
    ]


def _matched(outputs, field: str) -> list[str]:
    """계획서 대조의 기능 목록. 대조가 보류되면 판정하지 않은 것이라 빈 목록이다."""
    fm = outputs.feature_match
    if fm is None or fm.withheld:
        return []
    return list(getattr(fm, field, None) or [])


def artifact_out(project_id: int, outputs) -> schemas.ArtifactOut | None:
    """산출물. 파일 경로는 웹 주소로 바꿔 준다(SB-293) — 원페이지는 두 경로가 같은 onepage.svg라 인포그래픽만 보여 주고 실행 경로는 숨긴다."""
    if outputs.prototype is None and outputs.infographic is None:
        return None
    category = CATEGORY_TO_WEB.get(outputs.category, outputs.category or 'webdev')
    report = outputs.overall_score_report
    artifact_score = report.artifact_score.total if report is not None and report.artifact_score is not None else None
    return schemas.ArtifactOut(
        category=category,
        infographic_path=(artifact_url(project_id, outputs.infographic.image_path)
                          if outputs.infographic is not None else ''),
        # 원페이지는 실행 파일이 없다
        executable_path=(artifact_url(project_id, outputs.prototype.entry_file_path)
                         if outputs.prototype is not None and category != 'onepage' else None),
        artifact_score=artifact_score,
        score_reasons=artifact_score_reasons(outputs),
        gate_failures=gate_failures_out(outputs),
        missing_features=_matched(outputs, 'missing_features'),
        partial_features=_matched(outputs, 'partial_features'),
    )


def verdict_out(outputs, policy) -> schemas.VerdictOut | None:
    """종합 판정. 총점 · 통과는 오케스트레이터 값 그대로(웹이 다시 계산하지 않는다). 만점은 웹 정책(없으면 기본값)의
    지금 값 — 실행 시작 뒤 관리자가 바꿨으면 어긋날 수 있다(명세 3.5)."""
    report = outputs.overall_score_report
    if report is None:
        return None
    artifact = report.artifact_score
    return schemas.VerdictOut(
        overall_passed=report.passed,
        doc_score=report.doc_score.total,
        doc_max_score=float(policy.doc_weight) if policy is not None else DEFAULT_DOC_MAX,
        code_score=artifact.code_check.total if artifact is not None else None,
        code_max_score=float(policy.code_weight) if policy is not None else DEFAULT_CODE_MAX,
        plan_match_score=artifact.feature_match.score if artifact is not None else None,
        plan_match_max_score=float(policy.plan_weight) if policy is not None else DEFAULT_PLAN_MAX,
        plan_match_withheld=bool(artifact is not None and artifact.feature_match.withheld),
        total_score=report.total,
        pass_threshold=report.threshold,
    )


def bundle_usages_out(outputs) -> list[schemas.BundleUsageOut]:
    return [
        schemas.BundleUsageOut(
            bundle_id=web_bundle_id_of(u.bundle_id), layer=u.layer, used=u.used_count, remaining=u.remaining)
        for u in outputs.rework_usage
    ]


# ── 검수 ──────────────────────────────────────────────────────────────────────────────
def _violation_note(token_check) -> str | None:
    parts = []
    if token_check.missing_tokens:
        parts.append('빠짐: ' + ', '.join(token_check.missing_tokens))
    if token_check.altered_tokens:
        parts.append('바뀜: ' + ', '.join(token_check.altered_tokens))
    if token_check.contaminated_tokens:
        parts.append('섞임: ' + ', '.join(token_check.contaminated_tokens))
    return ' / '.join(parts) or None


def proofread_logs_out(outputs, originals: dict[str, str] | None = None) -> list[schemas.ProofreadLogOut]:
    """문장별 시도 기록(모든 계정) → 시도마다 한 줄.

    검수 전 원문(originals: sentenceId → 문장)은 화면 10이 주는 값이다 — 표현 검수가 끝나면 현재 계획서(planDoc)의 문장이
    채택된 검수 결과 문장으로 바뀌므로 계획서에서 읽으면 "검수 전"이 아니게 된다(SB-297). 화면 10을 읽을 수 없을 때(originals 없음)는
    검수가 아직 계획서를 바꾸지 않은 때이므로 현재 계획서의 같은 sentenceId 문장을 쓴다."""
    fallback = {}
    if outputs.plan_doc is not None:
        fallback = {s.sentence_id: s.text for sec in outputs.plan_doc.sections for s in sec.sentences}
    originals = {**fallback, **(originals or {})}
    logs: list[schemas.ProofreadLogOut] = []
    for result in outputs.sentence_results:
        original = originals.get(result.sentence_id, '')
        for a in result.attempts:
            logs.append(schemas.ProofreadLogOut(
                original_text=original, corrected_text=a.text, reason=None, attempt_no=a.attempt_no,
                passed=a.token_check.passed, violation_type=a.violation_type,
                violation_note=_violation_note(a.token_check), section_id=result.sentence_id))
    return logs


def format_findings_out(outputs) -> list[schemas.FormatFindingOut]:
    return [
        schemas.FormatFindingOut(finding_type=f.violation_type, message=f.detail, sentence_id=f.sentence_id)
        for f in outputs.format_findings
    ]


# ── GET /result ───────────────────────────────────────────────────────────────────────
def result_out(project_id: int, outputs, policy, originals: dict[str, str] | None = None) -> schemas.DemoGenerateResponse:
    """outputs(project_id) → 결과 응답. 계획서(planDoc)가 아직 없으면 호출한 쪽이 404로 답한다(plan_doc 확인 뒤 부른다).
    originals: 검수 전 원문(화면 10의 sentences[].before) — 검수 기록이 있을 때 호출한 쪽이 읽어 넘긴다."""
    plan_doc = outputs.plan_doc
    report = outputs.document_score_report
    plan = schemas.BusinessPlanOut(
        doc_score=outputs.doc_score.total if outputs.doc_score is not None else None,
        threshold=report.threshold if report is not None else None,
        sections=plan_sections_out(plan_doc),
        score_reasons=plan_score_reasons(outputs),
        artifacts=[a for a in [artifact_out(project_id, outputs)] if a is not None],
        format_findings=format_findings_out(outputs),
        proofread_logs=proofread_logs_out(outputs, originals),
        feature_list=list(plan_doc.feature_list),
        charts=[c.model_dump(mode='json') for c in plan_doc.charts],
        tables=[t.model_dump(mode='json') for t in plan_doc.tables],
    )
    return schemas.DemoGenerateResponse(
        project_id=project_id,
        match=match_out(outputs),
        eligibility=(eligibility_out(outputs.gate_result, outputs.business_age_years)
                     if outputs.gate_result is not None else None),
        plan=plan,
        verdict=verdict_out(outputs, policy),
        rework_cap=outputs.rework_limit,
        bundle_usages=bundle_usages_out(outputs),
    )


# ── 재작성 접수 · 결과 ────────────────────────────────────────────────────────────────
def rework_accepted_out(project_id: int, task_key: str, orch_bundle: str, accepted) -> schemas.ReworkAcceptedOut:
    """request_rework_for_project 결과 → 접수 응답. orch_bundle은 이번에 요청한 묶음(오케스트레이터 이름)."""
    return schemas.ReworkAcceptedOut(
        project_id=project_id,
        task_key=task_key,
        bundle_id=web_bundle_id_of(orch_bundle),
        cycle_id=accepted.cycle_id,
        screen=accepted.screen,
        bundles=[web_bundle_id_of(b) for b in accepted.bundles],
        collect_until=accepted.collect_until,
        duplicate=accepted.duplicate,
    )


def _plan_section_out(section) -> schemas.PlanSectionOut:
    return schemas.PlanSectionOut(tag=section.section_code, title=section.title, body=section_body(section))


def rework_changed(project_id: int, result) -> dict:
    """예전 retry-task 응답의 changed 모양 — 화면이 전후 비교에 쓰던 값."""
    changed: dict = {}
    if result.plan_before is not None and result.plan_after is not None:
        before = {s.section_code: section_body(s) for s in result.plan_before}
        after = {s.section_code: section_body(s) for s in result.plan_after}
        changed['sections'] = {
            tag: {'before': before.get(tag), 'after': after.get(tag)}
            for tag in [*before, *[t for t in after if t not in before]]
            if before.get(tag) != after.get(tag)
        }
    for f in result.files:
        key = 'executable_path' if f.artifact == 'prototype' else 'infographic_path'
        changed[key] = {'before': artifact_url(project_id, f.before_path), 'after': artifact_url(project_id, f.after_path)}
    if result.kept is not None:
        changed['version_kept'] = 'new' if result.kept == '후' else 'previous'
        changed['version_comparison'] = {'before_score': result.before_score, 'after_score': result.after_score}
    return changed


def rework_result_out(project_id: int, result) -> schemas.ReworkResultOut:
    return schemas.ReworkResultOut(
        project_id=project_id,
        cycle_id=result.cycle_id,
        screen=result.screen,
        bundles=[web_bundle_id_of(b) for b in result.bundles],
        status=result.status,
        started_at=result.started_at,
        ended_at=result.ended_at,
        kept=result.kept,
        basis=result.basis,
        before_score=result.before_score,
        after_score=result.after_score,
        before_refs=list(result.before_refs),
        after_refs=list(result.after_refs),
        plan_before=[_plan_section_out(s) for s in result.plan_before] if result.plan_before is not None else None,
        plan_after=[_plan_section_out(s) for s in result.plan_after] if result.plan_after is not None else None,
        files=[schemas.ReworkFileChangeOut(
            artifact=f.artifact, before_path=artifact_url(project_id, f.before_path),
            after_path=artifact_url(project_id, f.after_path)) for f in result.files],
        rolled_back=result.rolled_back,
        refunded_bundles=[web_bundle_id_of(b) for b in result.refunded_bundles],
        notice_code=result.notice_code,
        changed=rework_changed(project_id, result),
    )
