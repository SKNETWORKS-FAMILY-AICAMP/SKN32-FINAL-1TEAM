"""산출물 파일(프로토타입 · 인포그래픽 · 계획서 파일 …) 내려 주기 (SB-292 · SB-315).

GET /projects/{project_id}/artifact-files/{key}
GET /projects/{project_id}/deliverable.zip   (SB-316 — 최종 결과물 묶음 내려받기)

- 파일은 오케스트레이터의 파일 저장소에 있고, 결과의 파일 참조(FileRef)가 준 `key`로 `read_artifact_file`을 불러 받는다(SB-311).
  웹은 파일 위치(폴더 · 경로)를 알지 못한다 — key의 뜻을 풀지도, 경로로 쓰지도 않고 그대로 넘긴다(S3로 옮겨도 이 라우터는 그대로다).
- **프로젝트 소유자만** 받는다. 관리자도 받지 못한다 — 기획서 6-7: 관리자 열람은 메타데이터로 한정(첨부 파일과 다르다).
  소유자가 아니면 파일이 있는지 알 수 없게 없는 파일과 같은 404로 답한다(다른 프로젝트의 key도 오케스트레이터가 FILE_NOT_FOUND로 막는다).
- 응답의 형식(Content-Type)과 내용은 오케스트레이터가 파일을 넣을 때 기록한 값 그대로다 — 웹이 key의 확장자로 정하지 않는다.
- 프론트는 이 주소로 받은 파일을 샌드박스 iframe(sandbox="allow-scripts", allow-same-origin 없음)에 넣어 연다. 응답 헤더는
  주소를 직접 열 때를 위한 안전장치다: 생성된 HTML이 이 서버의 로그인 정보로 실행되지 않게 샌드박스를 걸고, 외부 주소로 나가지 못하게 한다
  (프로토타입은 외부 파일 · CDN 없는 단일 파일이어야 한다 — 기능정의서 E-B1-DEP).
- 압축(zip)은 웹이 만든다(오케스트레이터는 만들지 않는다 — 명세 5.4절). 계획서는 파일을 받지 않고 계획서(planDoc)로 웹이 직접 만든 .docx를 넣는다
  (SB-341 — `deliverable.planDocFile`은 자리채움 파일이라 쓰지 않는다, 오케스트레이터 안내). 프로토타입 · 인포그래픽은 결과물(deliverable)의 파일을
  참조마다 read_artifact_file로 받아 묶는다. 계획서 그림(planDoc.diagrams의 SVG)은 docx 안에 PNG로 들어가고 원본 SVG는 plan/diagrams/에도
  넣는다(SB-340 — 그림 하나를 못 받으면 그 그림만 뺀다). 프로토타입 · 인포그래픽 파일을 한 파일이라도 못 받으면 일부만 든 압축을 주지 않고 그 오류로 답한다.
"""
import io
import zipfile

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.diagram_images import document_pictures
from app.models import Company, Project, User
from app.orch import OrchGateway, require_gateway
from app.orch.errors import CodedHTTPException, user_message_for
from app.routers.projects import render_plan_docx_for
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


# ── 결과물 묶음 내려받기 (SB-316) ──────────────────────────────────────────────────────────
# 압축 안의 폴더 이름(영문 — 압축 프로그램마다 한글 이름 처리가 달라 피한다)
# 계획서(plan/)는 파일 참조가 아니라 planDoc으로 만들어 넣는다(SB-341) — 여기에는 파일 참조로 받는 폴더만 둔다
_ZIP_FOLDERS = (('prototype_files', 'prototype'), ('infographic_file', 'infographic'))
PLAN_DOCX_NAME = 'plan/business-plan.docx'
DIAGRAM_FOLDER = 'plan/diagrams'  # 계획서 그림(서비스 흐름도 · 서비스 구조도)의 원본 SVG — docx 안의 PNG와 같은 그림
# 파일 하나는 30MB까지(오케스트레이터 규칙)라 계획서 · 프로토타입 · 인포그래픽이 모두 커도 이 안에 든다. 넘으면 메모리를 지키려고 만들지 않는다.
MAX_ZIP_SOURCE_BYTES = 100 * 1024 * 1024


def _deliverable_refs(deliverable) -> list[tuple[str, object]]:
    """(압축 안 폴더, 파일 참조) 목록 — 프로토타입(진입 파일 · 안내 문서 · 자산 순) · 인포그래픽 순. 계획서는 참조가 아니라 직접 만든다."""
    refs: list[tuple[str, object]] = []
    for field, folder in _ZIP_FOLDERS:
        value = getattr(deliverable, field, None)
        for ref in (value if isinstance(value, (list, tuple)) else [value]):
            if ref is not None:
                refs.append((folder, ref))
    return refs


def _unique_name(taken: set[str], folder: str, name: str) -> str:
    """같은 폴더에 같은 이름이 둘이면 뒤의 것에 _2, _3 … 을 붙인다."""
    stem, dot, ext = name.rpartition('.')
    base, suffix = (stem, dot + ext) if dot and stem else (name, '')
    candidate, n = f'{folder}/{name}', 2
    while candidate in taken:
        candidate, n = f'{folder}/{base}_{n}{suffix}', n + 1
    taken.add(candidate)
    return candidate


@router.get('/{project_id}/deliverable.zip')
def download_deliverable_zip(
    project_id: int,
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
    outputs = gateway.outputs(project_id)
    deliverable = outputs.deliverable
    if deliverable is None or outputs.plan_doc is None:
        raise CodedHTTPException(404, 'DELIVERABLE_NOT_READY', '아직 내려받을 수 있는 결과물이 없어요.')
    refs = _deliverable_refs(deliverable)
    if sum(int(getattr(ref, 'size', 0) or 0) for _folder, ref in refs) > MAX_ZIP_SOURCE_BYTES:
        raise CodedHTTPException(413, 'DELIVERABLE_TOO_LARGE', '결과물이 너무 커서 한 번에 묶을 수 없어요. 파일을 하나씩 내려받아 주세요.')
    buffer, taken = io.BytesIO(), set()
    pictures = document_pictures(gateway, project_id, outputs.plan_doc, deliverable)  # 그림(SVG → PNG) — 계획서 docx에 넣고 원본 SVG는 따로 넣는다(SB-340)
    plan_docx = render_plan_docx_for(db, db.get(Project, project_id), outputs.plan_doc, pictures, outputs.table_fallbacks, getattr(deliverable, 'disclaimer', '') or '')  # 파일 참조가 아니라 planDoc으로 만든다(SB-341)
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PLAN_DOCX_NAME, plan_docx)
        taken.add(PLAN_DOCX_NAME)
        for picture in pictures:
            if not picture.is_infographic:  # 인포그래픽 원본은 아래에서 결과물의 infographic/ 폴더로 들어간다
                archive.writestr(_unique_name(taken, DIAGRAM_FOLDER, picture.svg_name), picture.svg)
        for folder, ref in refs:
            file = gateway.read_artifact_file(project_id, ref.key)
            archive.writestr(_unique_name(taken, folder, file.name), file.data)
    return Response(
        content=buffer.getvalue(), media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="deliverable-{project_id}.zip"',
                 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
