"""산출물 파일(프로토타입 · 인포그래픽 · 계획서 파일 …) 내려 주기 (SB-292 · SB-315).

GET /projects/{project_id}/artifact-files/{key}

- 파일은 오케스트레이터의 파일 저장소에 있고, 결과의 파일 참조(FileRef)가 준 `key`로 `read_artifact_file`을 불러 받는다(SB-311).
  웹은 파일 위치(폴더 · 경로)를 알지 못한다 — key의 뜻을 풀지도, 경로로 쓰지도 않고 그대로 넘긴다(S3로 옮겨도 이 라우터는 그대로다).
- **프로젝트 소유자만** 받는다. 관리자도 받지 못한다 — 기획서 6-7: 관리자 열람은 메타데이터로 한정(첨부 파일과 다르다).
  소유자가 아니면 파일이 있는지 알 수 없게 없는 파일과 같은 404로 답한다(다른 프로젝트의 key도 오케스트레이터가 FILE_NOT_FOUND로 막는다).
- 응답의 형식(Content-Type)과 내용은 오케스트레이터가 파일을 넣을 때 기록한 값 그대로다 — 웹이 key의 확장자로 정하지 않는다.
- 프론트는 이 주소로 받은 파일을 샌드박스 iframe(sandbox="allow-scripts", allow-same-origin 없음)에 넣어 연다. 응답 헤더는
  주소를 직접 열 때를 위한 안전장치다: 생성된 HTML이 이 서버의 로그인 정보로 실행되지 않게 샌드박스를 걸고, 외부 주소로 나가지 못하게 한다
  (프로토타입은 외부 파일 · CDN 없는 단일 파일이어야 한다 — 기능정의서 E-B1-DEP).
"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, Project, User
from app.orch import OrchGateway, require_gateway
from app.orch.errors import CodedHTTPException, user_message_for
from app.security import get_current_user

router = APIRouter(prefix='/projects', tags=['artifact-files'])

# 주인이 아닌 경우와 없는 파일이 같은 응답이 되도록 같은 코드 · 문구를 쓴다
NOT_FOUND_CODE = 'FILE_NOT_FOUND'

# 단일 파일 프로토타입이 쓰는 것만 허용: 인라인 스크립트 · 스타일, data: 이미지 · 글꼴. 네트워크로 나가는 것은 모두 막는다.
_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data: blob:; font-src data:; media-src data: blob:")


@router.get('/{project_id}/artifact-files/{key:path}')
def download_artifact_file(
    project_id: int,
    key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    owned = (db.query(Project.project_id)
             .join(Company, Company.company_id == Project.company_id)
             .filter(Project.project_id == project_id, Company.user_id == user.user_id)
             .first())
    if owned is None:
        raise CodedHTTPException(404, NOT_FOUND_CODE, user_message_for(NOT_FOUND_CODE))
    # 주인 확인 뒤에 부른다. 오류(FILE_NOT_FOUND · FILE_STORE_UNAVAILABLE · RUN_NOT_VIEWABLE …)는 공통 오류 처리가 상태와 문구로 바꾼다.
    file = gateway.read_artifact_file(project_id, key)
    return Response(
        content=file.data, media_type=file.media_type,
        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': _CSP})
