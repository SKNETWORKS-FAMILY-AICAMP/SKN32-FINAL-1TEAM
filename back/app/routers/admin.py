"""관리자 대시보드. admin-dashboard.html 이 기대하는 JSON 모양(배점 3개, 판정기준,
체크리스트 배열, 진행 현황, 사용자 관리, FAQ, 에이전트 테스크)에 맞춰 대응한다.
프론트를 React로 다시 짜더라도 이 응답 계약은 유지하면 된다.

[알아둘 것 — admin-dashboard.html 목업과의 차이 (해결됨)]
목업에 있던 "검수(표현) Task 내부 보호 토큰 위반 문단 재시도 상한"(token_retry_cap)은
원래 설계 문서 스키마엔 없었는데, 2026-09-14 팀원과 논의 후 verification_policies에
컬럼을 추가하기로 확정했다 — app_schema.sql의 verification_policies CREATE TABLE 정의에
처음부터 포함시켰다(과도기용 ALTER TABLE 마이그레이션은 두지 않았다). 이제 GET/PUT 둘 다
이 필드를 그대로 다룬다.
"""
import datetime
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import pipeline_stages as ps
from app.database import get_db
from app.models import (
    FIXED_TASK_SEQUENCE,
    AgentExecution,
    Artifact,
    BusinessPlan,
    Faq,
    ImportRun,
    MatchResult,
    Notice,
    Project,
    ProofreadLog,
    User,
    Verdict,
    VerificationChecklistItem,
    VerificationPolicy,
    VerificationScoreHistory,
)
from app.schemas import (
    AgentOpsSummaryOut,
    AgentTaskOut,
    ChecklistItemIn,
    ChecklistItemOut,
    CollectionStatusOut,
    FaqAnswerIn,
    FaqOut,
    ImportRunOut,
    ItemArchiveIn,
    ItemOut,
    ItemScoreHistoryOut,
    LayerDeviationOut,
    NoticeAdminOut,
    NoticeSourceStatusOut,
    OpsSummaryOut,
    PolicyScoresIn,
    PolicyThresholdsIn,
    RecoveryItemOut,
    RecoveryLabelIn,
    ScoreBucketOut,
    ScoreHistoryEntryOut,
    UserOut,
    UserRoleStatusIn,
    VerificationPolicyOut,
)
from app.security import require_admin

router = APIRouter(prefix='/admin', tags=['admin'])

# [2026-09-22, 프론트 전달사항 10번] 기획서 v1.8 5-4 기준 — 산출물 카테고리(html/svg)마다
# 체크리스트 8항목 합계가 이 값이어야 한다(VerificationChecklistItem.category 참고).
_CHECKLIST_CATEGORY_MAX_SCORE = 15.0


def _get_policy(db: Session) -> VerificationPolicy:
    policy = db.query(VerificationPolicy).order_by(VerificationPolicy.policy_id).first()
    if policy is None:
        raise HTTPException(status_code=500, detail='verification_policies 초기 행이 없습니다. app_schema.sql을 확인하세요.')
    return policy


@router.get('/policy', response_model=VerificationPolicyOut)
def get_policy(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return VerificationPolicyOut.model_validate(_get_policy(db))


@router.put('/policy/scores', response_model=VerificationPolicyOut)
def save_policy_scores(body: PolicyScoresIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    total = body.doc_weight + body.code_weight + body.plan_weight
    if round(total, 2) != 100:
        # admin-dashboard.html의 savePolicyScores()와 동일한 검증: 합 100점 아니면 저장 거부
        raise HTTPException(status_code=422, detail=f'배점 합이 100점이어야 합니다(현재 {total}점)')

    policy = _get_policy(db)
    policy.doc_weight, policy.code_weight, policy.plan_weight = body.doc_weight, body.code_weight, body.plan_weight
    db.commit()
    db.refresh(policy)
    return VerificationPolicyOut.model_validate(policy)


@router.put('/policy/thresholds', response_model=VerificationPolicyOut)
def save_policy_thresholds(body: PolicyThresholdsIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    policy = _get_policy(db)
    policy.pass_threshold = body.pass_threshold
    policy.rerun_cap = body.rerun_cap
    policy.deviation_cap = body.deviation_cap
    policy.token_retry_cap = body.token_retry_cap
    db.commit()
    db.refresh(policy)
    # TODO: notifyRecheckCapViolations() 에 해당하는 재채점 편차 점검을
    #       verification_score_history 에 대해 서버에서 돌리고 위반 목록을 함께 응답하도록 확장
    return VerificationPolicyOut.model_validate(policy)


@router.get('/checklist', response_model=list[ChecklistItemOut])
def get_checklist(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    items = db.query(VerificationChecklistItem).order_by(VerificationChecklistItem.check_item_id).all()
    return [ChecklistItemOut.model_validate(i) for i in items]


@router.put('/checklist', response_model=list[ChecklistItemOut])
def save_checklist(body: list[ChecklistItemIn], db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    items = {i.check_item_id: i for i in db.query(VerificationChecklistItem).all()}
    # [2026-09-22 수정, 프론트 전달사항 10번] v1.8 기준 카테고리(html=웹개발·AI API /
    # svg=원페이지)별로 8항목·15점 만점이라, 예전 "전체 합 100점" 검증을 "카테고리별 합
    # 15점" 검증으로 바꿨다 — 다른 카테고리 항목끼리 가중치를 주고받아 맞추는 걸 막는다.
    enabled_total_by_category: dict[str, float] = {}
    for entry in body:
        item = items.get(entry.check_item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f'알 수 없는 검증 항목: {entry.check_item_id}')
        item.weight = entry.weight
        item.enabled = entry.enabled
        if entry.enabled:
            enabled_total_by_category[item.category] = (
                enabled_total_by_category.get(item.category, 0.0) + entry.weight
            )

    bad_categories = {
        category: total for category, total in enabled_total_by_category.items()
        if round(total, 2) != _CHECKLIST_CATEGORY_MAX_SCORE
    }
    if bad_categories:
        db.rollback()
        detail = ', '.join(f"{category}: {total}점" for category, total in bad_categories.items())
        raise HTTPException(
            status_code=422,
            detail=f'사용 중인 항목의 카테고리별 가중치 합이 {_CHECKLIST_CATEGORY_MAX_SCORE}점이어야 합니다({detail})',
        )

    db.commit()
    items_sorted = db.query(VerificationChecklistItem).order_by(VerificationChecklistItem.check_item_id).all()
    return [ChecklistItemOut.model_validate(i) for i in items_sorted]


_STALLED_AFTER = datetime.timedelta(hours=48)


def _build_item_out(db: Session, project: Project) -> ItemOut:
    """진행 현황 탭 행 하나를 실제 DB 값으로 조립한다 — list_items/archive 토글이 공유한다.
    "정체"(stalled)는 마지막 agent_executions 실행 후 48시간 기준(모듈 상단 _STALLED_AFTER)
    — 완료·보관 상태는 정체로 치지 않는다. score는 doc_score+artifact_score 합계(문서
    평가만 끝났으면 doc_score만, 산출물까지 끝났으면 둘 다 더함)."""
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project.project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    if match is None:
        return ItemOut(
            project_id=project.project_id,
            description=project.description,
            user_name=project.company.user.name,
            created_at=project.created_at,
            status_label='공고 매칭 전',
            last_updated=project.created_at,
        )

    latest_execution = (
        db.query(AgentExecution)
        .filter(AgentExecution.match_id == match.match_id)
        .order_by(AgentExecution.execution_id.desc())
        .first()
    )
    last_updated = latest_execution.started_at if latest_execution else project.created_at

    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.match_id == match.match_id)
        .order_by(BusinessPlan.plan_id.desc())
        .first()
    )
    artifact = (
        db.query(Artifact).filter(Artifact.plan_id == plan.plan_id).order_by(Artifact.artifact_id.desc()).first()
        if plan is not None else None
    )
    score = None
    if plan is not None:
        score = float((plan.doc_score or 0) + (artifact.artifact_score if artifact and artifact.artifact_score else 0))

    archived = match.archived_at is not None
    if match.stage == ps.STAGE_DONE:
        status_label = '완료'
    elif match.stage in (ps.STAGE_PLAN_REVIEW_PENDING, ps.STAGE_FINAL_REVIEW_PENDING):
        status_label = '판단 대기'
    elif match.status == 'halted':
        status_label = '중단'
    else:
        status_label = '진행중'

    stalled = (
        not archived
        and status_label == '진행중'
        and (datetime.datetime.utcnow() - last_updated) > _STALLED_AFTER
    )

    return ItemOut(
        project_id=project.project_id,
        description=project.description,
        user_name=project.company.user.name,
        created_at=project.created_at,
        match_status=match.status,
        stage=match.stage,
        status_label=status_label,
        step=latest_execution.agent_name if latest_execution else None,
        attempts=latest_execution.attempt_no if latest_execution else None,
        last_updated=last_updated,
        stalled=stalled,
        score=score,
        archived=archived,
    )


@router.get('/items', response_model=list[ItemOut])
def list_items(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """진행 현황 탭용 — 전체 프로젝트 목록(_build_item_out 참고).

    (이전엔 여기가 `from app.models import Item`을 참조하고 있었다 — items→projects
    개명(backend_decisions.md #5) 때 이 파일만 안 고쳐진 채 남아있던 잔재. main.py에
    admin 라우터가 아직 연결 안 돼 있어서 지금까지는 안 터졌을 뿐, 라우터를 붙이는 순간
    임포트 단계에서 바로 죽었을 버그였다 — Project로 고치고 ItemOut도 실제로 존재하는
    필드로 다시 만들었다. 2026-09-18: 프론트 "진행 현황" 탭이 실제로 쓸 수 있도록
    단계·시도·정체·점수·보관 여부를 채워 확장했다.)"""
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return [_build_item_out(db, project) for project in projects]


@router.put('/items/{project_id}/archive', response_model=ItemOut)
def set_item_archived(
    project_id: int,
    body: ItemArchiveIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """진행 현황 탭의 "보관"/"복원" 버튼 — 사용자가 대시보드에서 직접 지울 때(DELETE
    /projects/{id})와 같은 match_results.archived_at/archived_by를 관리자가 대신
    조작한다. archived_by만 'admin'으로 남겨 사용자 본인이 지운 것과 구분한다."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    if match is None:
        raise HTTPException(status_code=400, detail='아직 매칭 결과가 없어 보관 처리할 수 없습니다')
    if body.archived:
        match.archived_at = datetime.datetime.utcnow()
        match.archived_by = 'admin'
    else:
        match.archived_at = None
        match.archived_by = None
    db.commit()
    return _build_item_out(db, project)


@router.get('/items/{project_id}/score-history', response_model=ItemScoreHistoryOut)
def get_item_score_history(
    project_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """진행 현황 탭의 "이력보기" 모달 — verification_score_history를 layer(doc/code/plan)별로
    묶어 최신순으로 내려준다. 매칭/계획서가 아직 없으면 세 층 모두 빈 목록을 돌려준다
    (에러가 아니라 "아직 이력이 없다"는 정상 상태)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    plan = (
        db.query(BusinessPlan).filter(BusinessPlan.match_id == match.match_id)
        .order_by(BusinessPlan.plan_id.desc()).first()
        if match is not None else None
    )
    if plan is None:
        return ItemScoreHistoryOut()

    rows = (
        db.query(VerificationScoreHistory)
        .filter(VerificationScoreHistory.plan_id == plan.plan_id)
        .order_by(VerificationScoreHistory.scored_at.desc())
        .all()
    )
    grouped: dict[str, list[ScoreHistoryEntryOut]] = {'doc': [], 'code': [], 'plan': []}
    for r in rows:
        if r.layer in grouped:
            grouped[r.layer].append(ScoreHistoryEntryOut(scored_at=r.scored_at, score=float(r.score), is_rerun=r.is_rerun))
    return ItemScoreHistoryOut(**grouped)


@router.get('/notices', response_model=list[NoticeAdminOut])
def list_notices(
    q: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """공고 관리 탭의 "공고 전체 관리" 표 — notices(공고 수집 파이프라인 소유, 읽기 전용
    테이블) 조회만 한다. q가 있으면 제목에 부분일치하는 공고만 최신순으로 최대 limit건
    돌려준다. "공고 수집 현황"/"최근 수집 실행 이력"은 GET /admin/collection-status가
    담당한다(import_runs 기반이라 다른 조회 함수로 뺐다). 상세·삭제 액션은 만들지
    않았다 — notices는 이 앱이 쓰는 게 아니라 다른 팀원의 수집 파이프라인이 다음 배치
    때 다시 채워 넣을 수 있는 테이블이라, 관리자 화면에서 조회 없이 삭제부터 만드는 건
    그 파이프라인과 상의 없이는 위험하다고 판단했다."""
    query = db.query(Notice).order_by(Notice.id.desc())
    if q:
        query = query.filter(Notice.title.contains(q))
    rows = query.limit(min(limit, 500)).all()
    return [
        NoticeAdminOut(
            notice_id=r.notice_id,
            title=r.title,
            source=r.source,
            apply_start=r.apply_start,
            apply_end=r.apply_end,
            recruitment_status=r.recruitment_status,
            has_embedding=r.embedding is not None,
        )
        for r in rows
    ]


_NOTICE_SOURCE_LABEL = {'kstartup': 'K-Startup', 'bizinfo': '기업마당'}


@router.get('/collection-status', response_model=CollectionStatusOut)
def get_collection_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """공고 관리 탭의 "공고 수집 현황" 카드 + "최근 수집 실행 이력" — import_runs(공고
    수집 파이프라인이 남기는 실제 배치 기록)와 notices 집계로 채운다(CollectionStatusOut/
    NoticeSourceStatusOut/ImportRunOut 주석 참고).

    실제 notices.source 값은 kstartup/bizinfo 둘뿐이라(2026-09-18 실데이터 확인) 카드도
    두 개만 나온다 — admin-dashboard.html 목업의 세 번째 카드("지자체 통합공고")는 그런
    출처로 수집된 공고가 실제로 없어서 만들지 않았다. "재수집"/"임베딩만 재생성" 액션도
    다른 팀원의 파이프라인 스크립트를 이 앱에서 실행시킬 방법이 없어 만들지 않았다."""
    latest_run = db.query(ImportRun).order_by(ImportRun.imported_at.desc()).first()
    latest_input_counts: dict = {}
    if latest_run is not None:
        latest_input_counts = ((latest_run.report or {}).get('summary') or {}).get('input_counts') or {}

    distinct_sources = [s for (s,) in db.query(Notice.source).distinct().all()]
    sources = []
    for source in distinct_sources:
        total = db.query(Notice).filter(Notice.source == source).count()
        embedded = db.query(Notice).filter(Notice.source == source, Notice.embedding.isnot(None)).count()
        sources.append(NoticeSourceStatusOut(
            source=source,
            label=_NOTICE_SOURCE_LABEL.get(source, source),
            total_count=total,
            embedded_count=embedded,
            latest_run_input_count=latest_input_counts.get(source),
        ))

    recent_runs = db.query(ImportRun).order_by(ImportRun.imported_at.desc()).limit(10).all()
    run_rows = []
    for r in recent_runs:
        summary = (r.report or {}).get('summary') or {}
        run_rows.append(ImportRunOut(
            run_id=r.run_id,
            generated_at=r.generated_at,
            imported_at=r.imported_at,
            accepted_count=summary.get('accepted_count', r.notice_count),
            input_counts=summary.get('input_counts') or {},
            issue_counts=summary.get('issue_counts') or {},
        ))

    return CollectionStatusOut(sources=sources, recent_runs=run_rows)


@router.get('/users', response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    users = db.query(User).order_by(User.user_id).all()
    return [UserOut.model_validate(u) for u in users]


@router.put('/users/{user_id}', response_model=UserOut)
def update_user(user_id: int, body: UserRoleStatusIn, db: Session = Depends(get_db), current_admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='사용자를 찾을 수 없습니다')
    if body.role is not None and body.role not in ('user', 'admin'):
        raise HTTPException(status_code=422, detail="role은 'user' 또는 'admin' 이어야 합니다")
    if body.status is not None and body.status not in ('active', 'suspended', 'dormant'):
        raise HTTPException(status_code=422, detail="status는 active/suspended/dormant 중 하나여야 합니다")

    # [2026-09-23] 관리자가 이 화면에서 자기 권한을 스스로 내려 관리자 화면에 못 들어가는
    # 사고가 실제로 났다(공유 DB를 직접 고쳐 복구). 되돌리는 것도 이 화면에서만 되므로
    # 자기 자신을 관리자에서 빼는 변경만 막으면 잠길 일이 없다 — 남을 강등할 때는 호출자
    # 본인이 활성 관리자로 남아 있으니(require_admin + get_current_user의 status 검사)
    # "마지막 관리자가 사라지는" 경우 자체가 생기지 않는다.
    # role 해제와 status 비활성화를 함께 보는 이유: get_current_user가 status!='active'
    # 계정을 401로 끊어서, 둘 다 결과가 같다(관리자 화면 접근 상실).
    demoting = body.role is not None and body.role != 'admin' and user.role == 'admin'
    deactivating = body.status is not None and body.status != 'active' and user.status == 'active'
    if user.user_id == current_admin.user_id and (demoting or deactivating):
        raise HTTPException(
            status_code=422,
            detail='자기 자신의 관리자 권한은 해제할 수 없습니다. 다른 관리자에게 요청하세요.',
        )

    if body.role is not None:
        # [2026-09-17] 얼굴 인증(face_verified_at) 게이트는 팀 결정으로 빼기로 확정됐다 —
        # 컬럼 자체도 지웠다(models.py/app_schema.sql 참고, AWS엔 아직 안 올라간 시점).
        user.role = body.role
    if body.status is not None:
        user.status = body.status
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get('/faqs', response_model=list[FaqOut])
def list_all_faqs(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """관리자용 — 비공개(is_visible=False, 미답변) 질문도 전부 포함해서 보여준다."""
    faqs = db.query(Faq).order_by(Faq.created_at.desc()).all()
    return [FaqOut.model_validate(f) for f in faqs]


@router.put('/faqs/{faq_id}', response_model=FaqOut)
def answer_faq(faq_id: int, body: FaqAnswerIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    faq = db.get(Faq, faq_id)
    if faq is None:
        raise HTTPException(status_code=404, detail='FAQ를 찾을 수 없습니다')
    faq.answer = body.answer
    faq.answered_at = datetime.datetime.utcnow()
    # 설계 문서 제약: "노출 여부, 답변 저장 전에는 전환 불가" — 지금 답변을 같이 저장하므로 is_visible 반영 가능
    faq.is_visible = body.is_visible
    db.commit()
    db.refresh(faq)
    return FaqOut.model_validate(faq)


@router.get('/agent-executions', response_model=None)
def list_agent_executions(
    match_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """에이전트 테스크 탭 — 실행 로그 원시 목록. 응답 모델을 스키마로 고정하지 않고
    dict 로 내려서 admin-dashboard.html 쪽 표 컬럼이 바뀌어도 유연하게 대응한다."""
    q = db.query(AgentExecution).order_by(AgentExecution.execution_id.desc())
    if match_id is not None:
        q = q.filter(AgentExecution.match_id == match_id)
    rows = q.limit(min(limit, 500)).all()
    return [
        {
            'execution_id': r.execution_id,
            'match_id': r.match_id,
            'agent_name': r.agent_name,
            'model_used': r.model_used,
            'rerun_type': r.rerun_type,
            'token_usage': r.token_usage,
            'status': r.status,
            'started_at': r.started_at.isoformat() if r.started_at else None,
        }
        for r in rows
    ]


@router.get('/agent-tasks', response_model=list[AgentTaskOut])
def list_agent_tasks(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """에이전트 테스크 탭의 "Task별 보기" — Agent 1개당 한 행(AgentTaskOut 참고).
    defined_task_count는 FIXED_TASK_SEQUENCE(코드에 고정된 실제 파이프라인 구조)에서
    세고, 최근 실행 프로젝트·상태는 agent_executions에서 그 Agent의 execution_id가 가장
    큰(=최신) 행 하나를 찾아 match_id -> project로 거슬러 올라가 채운다."""
    task_keys_by_agent: dict[str, set[str]] = defaultdict(set)
    for task_key, agent_name in FIXED_TASK_SEQUENCE:
        task_keys_by_agent[agent_name].add(task_key)

    rows = []
    for agent_name, task_keys in task_keys_by_agent.items():
        latest = (
            db.query(AgentExecution)
            .filter(AgentExecution.agent_name == agent_name)
            .order_by(AgentExecution.execution_id.desc())
            .first()
        )
        total_executions = db.query(AgentExecution).filter(AgentExecution.agent_name == agent_name).count()

        recent_project_id = None
        recent_project_description = None
        if latest is not None and latest.match_id is not None:
            match = db.get(MatchResult, latest.match_id)
            project = db.get(Project, match.project_id) if match is not None else None
            if project is not None:
                recent_project_id = project.project_id
                recent_project_description = project.description

        rows.append(AgentTaskOut(
            agent_name=agent_name,
            defined_task_count=len(task_keys),
            total_executions=total_executions,
            recent_project_id=recent_project_id,
            recent_project_description=recent_project_description,
            recent_status=latest.status if latest is not None else None,
        ))

    # FIXED_TASK_SEQUENCE에 Agent가 처음 등장하는 순서(조율→전략→작성→...) 그대로 정렬한다.
    order = list(dict.fromkeys(agent_name for _task_key, agent_name in FIXED_TASK_SEQUENCE))
    rows.sort(key=lambda r: order.index(r.agent_name))
    return rows


@router.get('/agent-ops-summary', response_model=AgentOpsSummaryOut)
def get_agent_ops_summary(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """에이전트 테스크 탭의 "운영 지표 요약" 아코디언 — agent_executions/proofread_logs
    전체를 집계한다(AgentOpsSummaryOut 주석 참고 — "선별/전체 재실행" 구분은 이 앱에
    그 값을 남기는 컬럼이 없어 만들지 않았다)."""
    rows = db.query(AgentExecution).all()
    initial = [r for r in rows if r.rerun_type == 'initial']
    rerun = [r for r in rows if r.rerun_type == 'rerun']

    # run_review_token_check_retry가 아직 더미(무작위) 판정이라 실제 위반율로 볼 수 없다.
    # 진짜 판정 로직이 들어오기 전까지는 0으로 고정한다.
    token_check_count = db.query(ProofreadLog).count()
    token_violation_count = 0
    token_violation_rate = 0.0 if token_check_count else None

    return AgentOpsSummaryOut(
        total_executions=len(rows),
        initial_executions=len(initial),
        rerun_executions=len(rerun),
        total_tokens=sum(r.token_usage for r in rows),
        initial_avg_tokens=round(sum(r.token_usage for r in initial) / len(initial), 1) if initial else None,
        rerun_avg_tokens=round(sum(r.token_usage for r in rerun) / len(rerun), 1) if rerun else None,
        token_violation_rate=token_violation_rate,
        token_violation_count=token_violation_count,
        token_check_count=token_check_count,
    )


@router.get('/ops-summary', response_model=OpsSummaryOut)
def get_ops_summary(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """운영 현황 탭 — business_plans/artifacts/verdicts/match_results/agent_executions/
    verification_score_history/proofread_logs 실제 집계값(OpsSummaryOut 주석 참고).
    [2026-09-18] retry_task의 verify1_*/verify2_*가 이제 verification_score_history에
    새 행을 남기므로(app/routers/projects.py 참고) 채점 편차(deviations)도 재채점이
    실제로 있었으면 sample_count>0으로 나온다."""
    projects = db.query(Project).all()
    items = [_build_item_out(db, p) for p in projects]
    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item.status_label] = status_counts.get(item.status_label, 0) + 1

    plans = db.query(BusinessPlan).all()
    doc_scores = [float(p.doc_score) for p in plans if p.doc_score is not None]
    doc_avg = round(sum(doc_scores) / len(doc_scores), 1) if doc_scores else None

    totals: list[float] = []
    for plan in plans:
        if plan.doc_score is None:
            continue
        artifact = (
            db.query(Artifact).filter(Artifact.plan_id == plan.plan_id)
            .order_by(Artifact.artifact_id.desc()).first()
        )
        if artifact is not None and artifact.artifact_score is not None:
            totals.append(float(plan.doc_score) + float(artifact.artifact_score))
    total_avg = round(sum(totals) / len(totals), 1) if totals else None

    policy = _get_policy(db)
    threshold = float(policy.pass_threshold)
    pass_count = sum(1 for t in totals if t >= threshold)
    pass_rate = round(pass_count / len(totals) * 100, 1) if totals else None

    buckets = (('90~100점', 90, 100), ('80~89점', 80, 89), ('70~79점', 70, 79), ('60~69점', 60, 69), ('60점 미만', 0, 59))
    score_buckets = [
        ScoreBucketOut(label=label, count=sum(1 for t in totals if lo <= t <= hi))
        for label, lo, hi in buckets
    ]

    match_ids_with_exec = {mid for (mid,) in db.query(AgentExecution.match_id).distinct().all() if mid is not None}
    rerun_match_ids = {
        mid for (mid,) in db.query(AgentExecution.match_id)
        .filter(AgentExecution.rerun_type == 'rerun').distinct().all() if mid is not None
    }
    matches_with_execution = len(match_ids_with_exec)
    rerun_matches = len(rerun_match_ids)
    rerun_rate = round(rerun_matches / matches_with_execution * 100, 1) if matches_with_execution else None

    history_by_plan_layer: dict[tuple[int, str], list[float]] = {}
    for row in db.query(VerificationScoreHistory).order_by(VerificationScoreHistory.scored_at.asc()).all():
        history_by_plan_layer.setdefault((row.plan_id, row.layer), []).append(float(row.score))

    deviations = []
    for layer in ('doc', 'code', 'plan'):
        pairs = [scores[:2] for (_pid, lyr), scores in history_by_plan_layer.items() if lyr == layer and len(scores) >= 2]
        if not pairs:
            deviations.append(LayerDeviationOut(layer=layer, sample_count=0))
            continue
        round1_avg = round(sum(p[0] for p in pairs) / len(pairs), 1)
        round2_avg = round(sum(p[1] for p in pairs) / len(pairs), 1)
        deviations.append(LayerDeviationOut(
            layer=layer, round1_avg=round1_avg, round2_avg=round2_avg,
            delta_avg=round(round2_avg - round1_avg, 1), sample_count=len(pairs),
        ))

    # [2026-09-18] 보호 토큰 위반율 — proofread_logs 전체 시도(전체 프로젝트) 중
    # passed=False 비율. 모델 버전별로는 못 쪼갠다(어느 버전이 만든 시도인지 남기는
    # 컬럼이 없음, OpsSummaryOut 주석 참고) — 그래서 "전체 평균" 하나만 낸다.
    # run_review_token_check_retry가 아직 더미(무작위) 판정이라 실제 위반율로 볼 수 없다.
    # 진짜 판정 로직이 들어오기 전까지는 0으로 고정한다.
    token_check_count = db.query(ProofreadLog).count()
    token_violation_count = 0
    token_violation_rate = 0.0 if token_check_count else None

    return OpsSummaryOut(
        status_counts=status_counts,
        doc_avg=doc_avg, doc_count=len(doc_scores),
        total_avg=total_avg, total_count=len(totals),
        pass_count=pass_count, pass_rate=pass_rate, pass_threshold=threshold,
        rerun_matches=rerun_matches, matches_with_execution=matches_with_execution, rerun_rate=rerun_rate,
        score_buckets=score_buckets, deviations=deviations,
        token_violation_rate=token_violation_rate, token_violation_count=token_violation_count,
        token_check_count=token_check_count,
    )


def _recovery_item_out(row: ProofreadLog, db: Session) -> RecoveryItemOut:
    """proofread_logs 행(passed=False) 하나를 RecoveryItemOut으로 조립한다 — plan ->
    match -> project -> company -> user로 거슬러 올라가 프로젝트 설명·동의 여부를 찾고,
    plan -> verdicts로 모델 버전을 찾는다(근사치, RecoveryItemOut 주석 참고)."""
    plan = db.get(BusinessPlan, row.plan_id)
    match = db.get(MatchResult, plan.match_id) if plan is not None else None
    project = db.get(Project, match.project_id) if match is not None else None
    user = project.company.user if project is not None else None
    verdict = (
        db.query(Verdict).filter(Verdict.plan_id == row.plan_id).order_by(Verdict.verdict_id.desc()).first()
        if plan is not None else None
    )
    return RecoveryItemOut(
        log_id=row.log_id,
        project_id=project.project_id if project is not None else None,
        project_description=project.description if project is not None else None,
        model_version=verdict.model_version if verdict is not None else None,
        violation_type=row.violation_type,
        occurred_at=row.created_at,
        consent=bool(user.ai_training_agreed) if user is not None else False,
        original=row.original_text,
        attempt=row.corrected_text,
        recovery_status=row.recovery_status or 'pending',
        label=row.recovery_label,
    )


@router.get('/recovery-items', response_model=list[RecoveryItemOut])
def list_recovery_items(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """검수 회수 문단 탭 — proofread_logs 중 passed=False(보호 토큰 위반으로 반려된
    시도)만 최신순으로 내려준다. 동의(consent) 여부로 걸러내는 건 프론트 몫으로 남긴다
    — 관리자가 "동의 안 한 사용자 데이터가 실수로 섞이지 않았는지"를 직접 눈으로
    확인할 수 있어야 하므로 서버가 미리 숨기지 않는다."""
    rows = (
        db.query(ProofreadLog)
        .filter(ProofreadLog.passed.is_(False))
        .order_by(ProofreadLog.log_id.desc())
        .all()
    )
    return [_recovery_item_out(r, db) for r in rows]


@router.put('/recovery-items/{log_id}', response_model=RecoveryItemOut)
def label_recovery_item(
    log_id: int,
    body: RecoveryLabelIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """검수 회수 문단 탭의 라벨링 액션 — pending/labeled/excluded 상태 전환 + 라벨 저장."""
    row = db.get(ProofreadLog, log_id)
    if row is None or row.passed:
        raise HTTPException(status_code=404, detail='반려된 시도(회수 대상)를 찾을 수 없습니다')
    row.recovery_status = body.recovery_status
    row.recovery_label = body.label
    db.commit()
    return _recovery_item_out(row, db)