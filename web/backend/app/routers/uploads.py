"""Private attachment delivery; preserve existing /uploads URLs.

[SB-247] 이 경로는 첨부파일만 제공한다(예전 artifacts 테이블 기준 소유 확인은 테이블과 함께 없어졌다).
[SB-292] 산출물(프로토타입 · 인포그래픽) 파일은 구현 Agent가 정한 폴더 구조로 저장되고 별도 경로로 내려 준다 —
app/routers/artifact_files.py (소유자만, 관리자 제외 — 이 첨부 경로와 다르다)."""
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, Project, ProjectAttachment, User
from app.routers import projects
from app.security import get_current_user

router = APIRouter(prefix='/uploads', tags=['uploads'])

# [2026-09-29 신규, 프론트 요청사항 5차 D-3] FileResponse에 media_type을 안 주면 Starlette가
# mimetypes.guess_type()으로 추측하는데, 이건 OS(특히 Windows 레지스트리)에 따라 .svg
# 확장자가 아예 등록 안 돼 있어 None이 나올 수 있다 — 그러면 브라우저가 image/*가 아닌
# 응답으로 받아 인포그래픽 미리보기가 깨진다. 산출물 확장자는 닫힌 집합(svg · html)이라 OS 추측에 기대지 않고
# 여기서 직접 명시한다 — 첨부파일(임의 확장자)은 이 표에 없으면 그대로 mimetypes.guess_type()으로 추측한다.
_KNOWN_ARTIFACT_MEDIA_TYPES = {
    '.svg': 'image/svg+xml',
    '.html': 'text/html',
}


def _resolve_media_type(path: Path) -> str | None:
    return _KNOWN_ARTIFACT_MEDIA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0]


@router.get('/{filename}')
def download_upload(filename: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    root = Path(projects.UPLOAD_DIR).resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')

    url = f'/uploads/{filename}'
    attachments = (db.query(ProjectAttachment)
                   .join(Project, Project.project_id == ProjectAttachment.project_id)
                   .join(Company, Company.company_id == Project.company_id)
                   .filter(ProjectAttachment.file_url == url))
    if user.role != 'admin':
        attachments = attachments.filter(Company.user_id == user.user_id)
    attachment = attachments.first()
    if attachment is None:
        raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')

    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
    # Generated HTML must not execute with the API origin's credentials.
    headers['Content-Security-Policy'] = 'sandbox allow-scripts'
    return FileResponse(
        path, filename=attachment.file_name if attachment else filename,
        content_disposition_type='attachment' if attachment else 'inline', headers=headers,
        media_type=_resolve_media_type(path),
    )
