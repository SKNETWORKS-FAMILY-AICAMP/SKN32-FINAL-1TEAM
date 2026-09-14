"""FAQ — 로그인한 사용자가 직접 질문을 등록하고, 공개(답변 완료 + is_visible) FAQ를
목록으로 조회한다.

관리자용 전체 조회/답변(미답변·비공개 포함, GET/PUT /admin/faqs)은 admin.py에 이미
있다. FaqCreateRequest 스키마는 schemas.py에 처음부터 있었지만 이 라우터가 없어서
연결되지 않은 채로 남아 있었다 — 설계 문서(3.3절 API·Agent 정합성 점검)에서 지적된
알려진 갭이었고, 이제 연결한다(2026-09-14).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Faq, User
from app.schemas import FaqCreateRequest, FaqOut
from app.security import get_current_user

router = APIRouter(prefix='/faqs', tags=['faqs'])


@router.post('', response_model=FaqOut, status_code=201)
def create_faq(
    body: FaqCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    faq = Faq(user_id=current_user.user_id, question=body.question)
    db.add(faq)
    db.commit()
    db.refresh(faq)
    return FaqOut.model_validate(faq)


@router.get('', response_model=list[FaqOut])
def list_visible_faqs(db: Session = Depends(get_db)):
    """공개 FAQ 목록 — is_visible=True(=관리자가 답변 저장 시 노출 전환한 것)만 내려준다.
    로그인 여부와 무관하게 누구나 조회 가능(공개 도움말 성격)."""
    faqs = (
        db.query(Faq)
        .filter(Faq.is_visible.is_(True))
        .order_by(Faq.created_at.desc())
        .all()
    )
    return [FaqOut.model_validate(f) for f in faqs]
