"""Private attachment/artifact delivery; preserve existing /uploads URLs."""
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Artifact, BusinessPlan, Company, Project, ProjectAttachment, User
from app.routers import projects
from app.security import get_current_user

router = APIRouter(prefix='/uploads', tags=['uploads'])

# [2026-09-29 신규, 프론트 요청사항 5차 D-3] FileResponse에 media_type을 안 주면 Starlette가
# mimetypes.guess_type()으로 추측하는데, 이건 OS(특히 Windows 레지스트리)에 따라 .svg
# 확장자가 아예 등록 안 돼 있어 None이 나올 수 있다 — 그러면 브라우저가 image/*가 아닌
# 응답으로 받아 인포그래픽 미리보기가 깨진다. 실제로 이 산출물 파일들의 확장자는
# ImplementArtifactResult.file_ext(app/agents.py)가 정하는 닫힌 집합이라, OS 추측에
# 기대지 않고 여기서 직접 명시한다 — 첨부파일(임의 확장자)은 이 표에 없으면 그대로
# mimetypes.guess_type()으로 추측한다(다운로드용이라 정확한 미리보기가 필요 없음).
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
    artifacts = (db.query(Artifact)
                 .join(BusinessPlan, BusinessPlan.plan_id == Artifact.plan_id)
                 .join(Project, Project.project_id == BusinessPlan.project_id)
                 .join(Company, Company.company_id == Project.company_id)
                 .filter(or_(Artifact.executable_path == url, Artifact.infographic_path == url)))
    if user.role != 'admin':
        attachments = attachments.filter(Company.user_id == user.user_id)
        artifacts = artifacts.filter(Company.user_id == user.user_id)
    attachment = attachments.first()
    if attachment is None and artifacts.first() is None:
        raise HTTPException(status_code=404, detail='파일을 찾을 수 없습니다')

    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
    # Generated HTML must not execute with the API origin's credentials.
    headers['Content-Security-Policy'] = 'sandbox allow-scripts'
    return FileResponse(
        path, filename=attachment.file_name if attachment else filename,
        content_disposition_type='attachment' if attachment else 'inline', headers=headers,
        media_type=_resolve_media_type(path),
    )
