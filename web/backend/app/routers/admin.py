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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Faq,
    GenerationFailureAlert,
    ImportRun,
    Notice,
    Project,
    ProofreadLog,
    User,
    VerificationChecklistItem,
    VerificationPolicy,
)
from app.orch import OrchError, OrchGateway, admin_mapping, require_gateway
from app.proofread_retention import TRAINED
from app.schemas import (
    AgentOpsSummaryOut,
    AgentTaskOut,
    ChecklistItemIn,
    ChecklistItemOut,
    CollectionStatusOut,
    FaqAnswerIn,
    FaqOut,
    GenerationFailureAlertAckIn,
    GenerationFailureAlertOut,
    ImportRunOut,
    ItemArchiveIn,
    ItemOut,
    ItemScoreHistoryOut,
    NoticeAdminOut,
    NoticeSourceStatusOut,
    OpsSummaryOut,
    PolicyScoresIn,
    PolicyThresholdsIn,
    RecoveryItemOut,
    RecoveryLabelIn,
    RecoveryTrainedIn,
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
    policy.rework_cap = body.rework_cap
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


_ADMIN_PAGE = 200  # admin_runs를 한 번에 가져오는 줄 수


def _all_admin_runs(gateway: OrchGateway) -> dict[int, object]:
    """관리자 조회 범위(마지막 활동이 최근 12개월 안)의 실행 건을 모두 읽는다 — project_id → AdminRun.
    웹에서 지워진 프로젝트의 실행 건(project_id 없음)은 뺀다."""
    runs: dict[int, object] = {}
    offset = 0
    while True:
        page = gateway.admin_runs(limit=_ADMIN_PAGE, offset=offset)
        for run in page:
            if run.project_id is not None:
                runs[int(run.project_id)] = run
        if len(page) < _ADMIN_PAGE:
            return runs
        offset += _ADMIN_PAGE


def _build_items(db: Session, gateway: OrchGateway, projects: list[Project] | None = None) -> list[ItemOut]:
    """진행 현황 탭 행 — 웹 projects 하나당 한 줄. 실행 건이 있으면 오케스트레이터 값(단계 · 시도 · 점수 · 정체),
    없으면 '공고 매칭 전'이다. 관리자 조회 범위(12개월) 밖의 실행 건은 진행 상태만으로 채운다(점수 · Agent 없음)."""
    if projects is None:
        projects = db.query(Project).order_by(Project.created_at.desc()).all()
    runs = _all_admin_runs(gateway)
    outside_range = [p.project_id for p in projects if p.project_id not in runs]
    views = {int(v.project_id): v for v in gateway.project_views(outside_range)} if outside_range else {}
    now = datetime.datetime.now(datetime.UTC)
    items = []
    for project in projects:
        run = runs.get(project.project_id)
        if run is not None:
            items.append(admin_mapping.item_from_run(project, run, now))
            continue
        view = views.get(project.project_id)
        if view is not None and view.run is not None:
            items.append(admin_mapping.item_from_view(project, view.run))
        else:
            items.append(admin_mapping.item_no_run(project))
    return items


@router.get('/items', response_model=list[ItemOut])
def list_items(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    gateway: OrchGateway = Depends(require_gateway),
):
    """진행 현황 탭용 — 전체 프로젝트 목록(_build_items 참고). [SB-245] 단계 · 시도 · 점수 · 정체(48시간)는
    오케스트레이터 admin_runs 값이고, 설명 · 사용자 · 등록일 · 보관 여부는 웹 테이블 값이다."""
    return _build_items(db, gateway)


@router.put('/items/{project_id}/archive', response_model=ItemOut)
def set_item_archived(
    project_id: int,
    body: ItemArchiveIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    gateway: OrchGateway = Depends(require_gateway),
):
    """진행 현황 탭의 "보관"/"복원" 버튼 — 사용자가 대시보드에서 직접 지울 때(DELETE
    /projects/{id})와 같은 projects.archived_at/archived_by를 관리자가 대신
    조작한다. archived_by만 'admin'으로 남겨 사용자 본인이 지운 것과 구분한다.

    [SB-245] "아직 매칭 결과가 없다"는 실행 건 유무로 판단한다. 진행 중인 실행 건을 보관만 하면 그 계정은 그
    실행 건이 끝날 때까지 새 작업을 시작할 수 없다(동시 실행 제한) — 보관할 때 오케스트레이터에 중단을 알릴지는
    정해지지 않아 지금은 보관만 한다(사용자 휴지통과 달리 관리자 보관은 되돌릴 수 있어야 해서)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    if gateway.view_project(project_id).run is None:
        raise HTTPException(status_code=400, detail='아직 매칭 결과가 없어 보관 처리할 수 없습니다')
    if body.archived:
        project.archived_at = datetime.datetime.utcnow()
        project.archived_by = 'admin'
    else:
        project.archived_at = None
        project.archived_by = None
    db.commit()
    return _build_items(db, gateway, [project])[0]


@router.get('/generation-alerts', response_model=list[GenerationFailureAlertOut])
def list_generation_alerts(
    include_acknowledged: bool = False,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """생성 작업(계획서/프로토타입)이 status='failed'로 확정될 때마다(자동 재시도 5회 소진
    또는 영구 오류로 즉시 확정) 쌓이는 관리자 알림 목록 — 기본은 아직 확인 안 한 것만
    최신순으로 보여준다(include_acknowledged=true면 확인 처리된 것까지 전부). 각 행의
    regenerate_exhausted가 True면 "처음부터 다시 생성" 연속 실패 상한까지 도달한 건이라
    우선 확인이 필요하다."""
    query = db.query(GenerationFailureAlert)
    if not include_acknowledged:
        query = query.filter(GenerationFailureAlert.acknowledged_at.is_(None))
    return query.order_by(GenerationFailureAlert.alert_id.desc()).all()


@router.put('/generation-alerts/{alert_id}/ack', response_model=GenerationFailureAlertOut)
def ack_generation_alert(
    alert_id: int,
    body: GenerationFailureAlertAckIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """관리자가 실패 알림을 확인 처리(또는 취소)한다 — 재시도 자체와는 무관하다(사용자는
    확인 여부와 상관없이 "다시 이어가기"를 누를 수 있음)."""
    alert = db.get(GenerationFailureAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail='알림을 찾을 수 없습니다')
    alert.acknowledged_at = datetime.datetime.utcnow() if body.acknowledged else None
    db.commit()
    return alert


@router.get('/items/{project_id}/score-history', response_model=ItemScoreHistoryOut)
def get_item_score_history(
    project_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    gateway: OrchGateway = Depends(require_gateway),
):
    """진행 현황 탭의 "이력보기" 모달 — 층(doc/code/plan)별 채점 이력을 최신순으로 내려준다.
    [SB-245] 오케스트레이터 admin_score_history 값이다. 실행 건이 아직 없으면 세 층 모두 빈 목록을 돌려준다
    (에러가 아니라 "아직 이력이 없다"는 정상 상태)."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    try:
        history = gateway.admin_score_history(project_id)
    except OrchError as exc:
        if exc.code == 'RUN_NOT_FOUND':
            return ItemScoreHistoryOut()
        raise
    return admin_mapping.score_history_out(history)


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
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    _admin: User = Depends(require_admin),
    gateway: OrchGateway = Depends(require_gateway),
):
    """에이전트 테스크 탭 — 실행 기록 목록(메타데이터만, 최신순). 응답 모델을 스키마로 고정하지 않고 dict로 내려
    표 컬럼이 바뀌어도 유연하게 대응한다.

    [SB-245] 오케스트레이터 admin_executions 값이다. status 거름 값은 웹 표기(failed · completed …)와 한글 표기(실패 ·
    성공 …)를 모두 받고, 응답의 status · rerun_type은 화면이 쓰던 웹 표기로 주면서 원래 표기를 status_ko · trigger로
    덧붙인다. error_kind/error_reason은 실패 기록에만 있고 retryable은 error_kind가 '일시'(자동 재개 대상)인지다.
    프롬프트 · 응답 원문과 output_ref는 없다.

    [SB-302] token_usage · tokens는 글 토큰만이고, 이미지 호출 토큰은 image_token_usage(합) · image_tokens(입력 · 출력)로 따로 준다."""
    rows = gateway.admin_executions(
        project_id=project_id, status=admin_mapping.exec_status_from_web(status), limit=min(limit, 500))
    return [admin_mapping.execution_dict(r) for r in rows]


@router.get('/agent-tasks', response_model=list[AgentTaskOut])
def list_agent_tasks(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    gateway: OrchGateway = Depends(require_gateway),
):
    """에이전트 테스크 탭의 "Task별 보기" — Agent 1개당 한 행(AgentTaskOut 참고).
    [SB-245] 오케스트레이터 admin_agent_tasks 값이다(등록된 Task 수는 규칙 · 합치기 단계를 포함해 세므로 웹의 옛
    FIXED_TASK_SEQUENCE 기준 개수와 다르다). 최근 실행 프로젝트의 설명만 웹 projects에서 채운다."""
    tasks = gateway.admin_agent_tasks()
    project_ids = [int(t.recent_project_id) for t in tasks if t.recent_project_id is not None]
    descriptions = (
        {p.project_id: p.description for p in db.query(Project).filter(Project.project_id.in_(project_ids))}
        if project_ids else {}
    )
    return [admin_mapping.agent_task_out(t, descriptions) for t in tasks]


@router.get('/agent-ops-summary', response_model=AgentOpsSummaryOut)
def get_agent_ops_summary(
    _admin: User = Depends(require_admin),
    gateway: OrchGateway = Depends(require_gateway),
):
    """에이전트 테스크 탭의 "운영 지표 요약" 아코디언 — [SB-245] 오케스트레이터 admin_summary 값이다(최근 12개월 범위).
    최초 실행 대비 재작성 · 재수행 실행의 평균 토큰, 표현 검수 시도 중 보호 토큰 검사 불통과 비율."""
    return admin_mapping.agent_ops_summary_out(gateway.admin_summary())


@router.get('/ops-summary', response_model=OpsSummaryOut)
def get_ops_summary(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    gateway: OrchGateway = Depends(require_gateway),
):
    """운영 현황 탭 — [SB-245] 오케스트레이터 admin_summary 값(최근 12개월 범위: 점수 평균 · 통과율 · 구간 · 재작성
    비율 · 층별 변화 · 표현 검수)이다. 상태별 건수만 진행 현황 탭과 같은 표(공고 매칭 전 포함)에서 센다."""
    status_counts: dict[str, int] = {}
    for item in _build_items(db, gateway):
        status_counts[item.status_label] = status_counts.get(item.status_label, 0) + 1
    return admin_mapping.ops_summary_out(gateway.admin_summary(), status_counts)


def _recovery_item_out(row: ProofreadLog, db: Session) -> RecoveryItemOut:
    """proofread_logs 행 하나를 RecoveryItemOut으로 조립한다.

    [SB-246] 워커가 쓴 행은 project_id로 프로젝트 · 회사 · 사용자를 찾고 모델 버전은 행의 model_version이다. 프로젝트가 지워져 연결이 끊긴 행(학습에 반영된 trained 행)은 프로젝트 설명이 없고,
    동의 여부는 trained 행이면 동의한 것으로 본다(동의한 계정의 행만 학습에 쓰였다)."""
    project = db.get(Project, row.project_id) if row.project_id is not None else None
    user = project.company.user if project is not None else None
    return RecoveryItemOut(
        log_id=row.log_id,
        project_id=project.project_id if project is not None else None,
        project_description=project.description if project is not None else None,
        model_version=row.model_version,
        violation_type=row.violation_type,
        occurred_at=row.created_at,
        consent=bool(user.ai_training_agreed) if user is not None else row.recovery_status == TRAINED,
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
    if row.recovery_status == TRAINED:
        raise HTTPException(status_code=409, detail='이미 학습 데이터로 내보낸 행은 바꿀 수 없습니다')
    row.recovery_status = body.recovery_status
    row.recovery_label = body.label
    db.commit()
    return _recovery_item_out(row, db)


@router.post('/recovery-items/trained', response_model=list[RecoveryItemOut])
def mark_recovery_items_trained(
    body: RecoveryTrainedIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """학습 데이터로 내보낸 행을 recovery_status='trained'로 표시한다 — 이 표시가 있는 행만 프로젝트 완전 삭제 ·
    탈퇴 · 동의 철회 뒤에도 남는다(웹연동_변경사항 11.7). 내보내기 도구가 내보낸 log_id 목록으로 부른다.

    라벨링을 마친(labeled) 행만 표시할 수 있다 — 동의가 없거나(excluded) 아직 대기(pending)인 행은 학습에 쓰지 않으므로
    하나라도 섞여 있으면 아무것도 바꾸지 않고 409를 돌려준다. 없는 log_id는 404."""
    rows = db.query(ProofreadLog).filter(ProofreadLog.log_id.in_(body.log_ids)).all()
    missing = set(body.log_ids) - {r.log_id for r in rows}
    if missing:
        raise HTTPException(status_code=404, detail=f'없는 검수 회수 문단입니다: {sorted(missing)}')
    not_ready = [r.log_id for r in rows if r.recovery_status not in ('labeled', TRAINED)]
    if not_ready:
        raise HTTPException(status_code=409, detail=f'라벨링을 마친 행만 학습 반영으로 표시할 수 있습니다: {sorted(not_ready)}')
    for row in rows:
        row.recovery_status = TRAINED
    db.commit()
    return [_recovery_item_out(r, db) for r in rows]
