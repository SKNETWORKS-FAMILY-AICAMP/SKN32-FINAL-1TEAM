"""산출물 파일(프로토타입 · 인포그래픽) 내려 주기 (SB-292).

GET /projects/{project_id}/artifact-files/{attempt_id}/{filename}

- **프로젝트 소유자만** 받는다. 관리자도 받지 못한다 — 기획서 6-7: 관리자 열람은 메타데이터로 한정(첨부 파일과 다르다).
  소유자가 아니면 파일이 있는지 알 수 없게 없는 파일과 같은 404로 답한다.
- 열 수 있는 파일은 artifact_store의 세 이름(index.html · infographic.svg · onepage.svg)과 정해진 폴더 구조뿐이다.
- 프론트는 이 주소로 받은 파일을 샌드박스 iframe(sandbox="allow-scripts", allow-same-origin 없음)에 넣어 연다. 응답 헤더는
  주소를 직접 열 때를 위한 안전장치다: 생성된 HTML이 이 서버의 로그인 정보로 실행되지 않게 샌드박스를 걸고, 외부 주소로 나가지 못하게 한다
  (프로토타입은 외부 파일 · CDN 없는 단일 파일이어야 한다 — 기능정의서 E-B1-DEP).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import artifact_store
from app.database import get_db
from app.models import Company, Project, User
from app.security import get_current_user

router = APIRouter(prefix='/projects', tags=['artifact-files'])

NOT_FOUND = '파일을 찾을 수 없습니다'

# 단일 파일 프로토타입이 쓰는 것만 허용: 인라인 스크립트 · 스타일, data: 이미지 · 글꼴. 네트워크로 나가는 것은 모두 막는다.
_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data: blob:; font-src data:; media-src data: blob:")


@router.get('/{project_id}/artifact-files/{attempt_id}/{filename}')
def download_artifact_file(
    project_id: int,
    attempt_id: str,
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    owned = (db.query(Project.project_id)
             .join(Company, Company.company_id == Project.company_id)
             .filter(Project.project_id == project_id, Company.user_id == user.user_id)
             .first())
    if owned is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    path = artifact_store.artifact_file(project_id, attempt_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return FileResponse(
        path, media_type=artifact_store.ARTIFACT_MEDIA_TYPES[filename],
        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': _CSP})
