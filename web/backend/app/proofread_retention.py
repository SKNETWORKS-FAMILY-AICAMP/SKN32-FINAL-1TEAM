"""proofread_logs(검수 회수 문단) 보관 규칙 — 학습에 반영된 행만 남긴다 (웹연동_변경사항_웹팀전달.md 11.7).

이 표의 행에는 문장 내용이 들어 있다. 프로젝트 완전 삭제 · 계정 탈퇴 · 학습 동의 철회 때 그 사용자의 행을 지우되,
이미 학습 데이터로 내보낸 행(recovery_status='trained')은 되돌릴 수 없어 남기고 프로젝트와의 연결만 끊는다.
`labeled`(라벨링을 마침)는 아직 학습 반영 전이라 지우는 쪽이다 — `trained`와 헷갈리지 않는다.

외래 키(project_id · plan_id)는 ON DELETE SET NULL이지만 SQLite 테스트 DB는 외래 키를 강제하지 않으므로, 연결 끊기는
여기서 직접 한다(MySQL에서도 같은 결과라 해가 없다).
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import BusinessPlan, Company, Project, ProofreadLog

TRAINED = 'trained'


def user_project_ids(db: Session, user_id: int) -> list[int]:
    """그 사용자의 모든 프로젝트(보관된 것 포함)."""
    return [
        pid for (pid,) in db.query(Project.project_id)
        .join(Company, Project.company_id == Company.company_id).filter(Company.user_id == user_id)
    ]


def _scope(db: Session, project_ids: list[int]):
    """project_ids 프로젝트에 딸린 행 — 워커가 쓴 행(project_id)과 더미 시절 행(plan_id → business_plans)."""
    plan_ids = [pid for (pid,) in db.query(BusinessPlan.plan_id).filter(BusinessPlan.project_id.in_(project_ids))]
    conditions = [ProofreadLog.project_id.in_(project_ids)]
    if plan_ids:
        conditions.append(ProofreadLog.plan_id.in_(plan_ids))
    return or_(*conditions)


def delete_untrained_logs(db: Session, project_ids: list[int]) -> int:
    """학습에 반영되지 않은 행(pending · labeled · excluded · 상태 없음)을 지운다. 지운 줄 수를 돌려준다."""
    if not project_ids:
        return 0
    return (
        db.query(ProofreadLog)
        .filter(_scope(db, project_ids), or_(ProofreadLog.recovery_status.is_(None), ProofreadLog.recovery_status != TRAINED))
        .delete(synchronize_session=False)
    )


def detach_trained_logs(db: Session, project_ids: list[int]) -> int:
    """학습에 반영된(trained) 행은 남기고 프로젝트 · 계획서 연결만 끊는다 — 프로젝트 행을 지우기 전에 부른다."""
    if not project_ids:
        return 0
    return (
        db.query(ProofreadLog)
        .filter(_scope(db, project_ids), ProofreadLog.recovery_status == TRAINED)
        .update({ProofreadLog.project_id: None, ProofreadLog.plan_id: None, ProofreadLog.section_id: None},
                synchronize_session=False)
    )


def clear_project_logs(db: Session, project_ids: list[int]) -> None:
    """완전 삭제 · 탈퇴 — 반영 전 행을 지우고 trained 행은 연결을 끊는다. 프로젝트 · 계획서 행을 지우기 전에 부른다."""
    delete_untrained_logs(db, project_ids)
    detach_trained_logs(db, project_ids)
