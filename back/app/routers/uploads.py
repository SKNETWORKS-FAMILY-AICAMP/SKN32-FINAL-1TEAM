"""Private attachment/artifact delivery; preserve existing /uploads URLs."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Artifact, BusinessPlan, Company, MatchResult, Project, ProjectAttachment, User
from app.routers import projects
from app.security import get_current_user

router = APIRouter(prefix='/uploads', tags=['uploads'])


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
                 .join(MatchResult, MatchResult.match_id == BusinessPlan.match_id)
                 .join(Project, Project.project_id == MatchResult.project_id)
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
    )
