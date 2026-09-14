"""관리자 대시보드. admin-dashboard.html 이 기대하는 JSON 모양(배점 3개, 판정기준,
체크리스트 배열, 진행 현황, 사용자 관리, FAQ, 에이전트 테스크)에 맞춰 대응한다.
프론트를 React로 다시 짜더라도 이 응답 계약은 유지하면 된다.

[알아둘 것 — admin-dashboard.html 목업과의 차이 (해결됨)]
목업에 있던 "검수(표현) Task 내부 보호 토큰 위반 문단 재시도 상한"(token_retry_cap)은
원래 설계 문서 스키마엔 없었는데, 2026-09-14 정재희님과 논의 후 verification_policies에
컬럼을 추가하기로 확정했다 — app_schema.sql의 verification_policies CREATE TABLE 정의에
처음부터 포함시켰다(과도기용 ALTER TABLE 마이그레이션은 두지 않았다). 이제 GET/PUT 둘 다
이 필드를 그대로 다룬다.
"""
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AgentExecution,
    Faq,
    MatchResult,
    Project,
    User,
    VerificationChecklistItem,
    VerificationPolicy,
)
from app.schemas import (
    ChecklistItemIn,
    ChecklistItemOut,
    FaqAnswerIn,
    FaqOut,
    ItemOut,
    PolicyScoresIn,
    PolicyThresholdsIn,
    UserOut,
    UserRoleStatusIn,
    VerificationPolicyOut,
)
from app.security import require_admin

router = APIRouter(prefix='/admin', tags=['admin'])


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
    enabled_total = 0.0
    for entry in body:
        item = items.get(entry.check_item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f'알 수 없는 검증 항목: {entry.check_item_id}')
        item.weight = entry.weight
        item.enabled = entry.enabled
        if entry.enabled:
            enabled_total += entry.weight

    if round(enabled_total, 2) != 100:
        # admin-dashboard.html saveChecklistItems() 와 동일한 검증
        db.rollback()
        raise HTTPException(status_code=422, detail=f'사용 중인 항목의 가중치 합이 100점이어야 합니다(현재 {enabled_total}점)')

    db.commit()
    items_sorted = db.query(VerificationChecklistItem).order_by(VerificationChecklistItem.check_item_id).all()
    return [ChecklistItemOut.model_validate(i) for i in items_sorted]


@router.get('/items', response_model=list[ItemOut])
def list_items(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """진행 현황 탭용 — 전체 프로젝트 목록. 정체 판정(48시간)은 최신 match_results.updated_at
    성격의 값이 없어(설계 문서 원안), 지금은 project.created_at 기준으로만 정렬한다 —
    필요해지면 match_results 쪽에 마지막 활동 시각을 추가해야 한다.

    (이전엔 여기가 `from app.models import Item`을 참조하고 있었다 — items→projects
    개명(backend_decisions.md #5) 때 이 파일만 안 고쳐진 채 남아있던 잔재. main.py에
    admin 라우터가 아직 연결 안 돼 있어서 지금까지는 안 터졌을 뿐, 라우터를 붙이는 순간
    임포트 단계에서 바로 죽었을 버그였다 — Project로 고치고 ItemOut도 실제로 존재하는
    필드(schemas.py 참고)로 다시 만들었다.)"""
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    result = []
    for project in projects:
        match = (
            db.query(MatchResult)
            .filter(MatchResult.project_id == project.project_id)
            .order_by(MatchResult.match_id.desc())
            .first()
        )
        result.append(ItemOut(
            project_id=project.project_id,
            description=project.description,
            user_name=project.company.user.name,
            created_at=project.created_at,
            match_status=match.status if match else None,
            stage=match.stage if match else None,
        ))
    return result


@router.get('/users', response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    users = db.query(User).order_by(User.user_id).all()
    return [UserOut.model_validate(u) for u in users]


@router.put('/users/{user_id}', response_model=UserOut)
def update_user(user_id: int, body: UserRoleStatusIn, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='사용자를 찾을 수 없습니다')
    if body.role is not None:
        if body.role not in ('user', 'admin'):
            raise HTTPException(status_code=422, detail="role은 'user' 또는 'admin' 이어야 합니다")
        if body.role == 'admin' and user.face_verified_at is None:
            # 설계 문서: face_verified_at = "관리자 권한 전환 시 얼굴 등록 완료 일시"
            raise HTTPException(status_code=422, detail='관리자 전환 전에 얼굴 등록(얼굴 인증)이 먼저 완료되어야 합니다')
        user.role = body.role
    if body.status is not None:
        if body.status not in ('active', 'suspended', 'dormant'):
            raise HTTPException(status_code=422, detail="status는 active/suspended/dormant 중 하나여야 합니다")
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