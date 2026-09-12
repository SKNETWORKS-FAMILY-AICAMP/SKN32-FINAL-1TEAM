"""프로젝트 생성(DB 적재) + 조회.

설계 문서 기준으로 "프로젝트"는 companies(회사/예비창업자 프로필) 1건 아래
projects(지원 아이템) N건으로 정규화돼 있다. 계정에 회사 프로필이 없으면 최초 생성 시
같이 만들고, 이미 있으면 재사용한다(회사 프로필은 계정당 보통 1건을 가정).

URL/DB 테이블/컬럼/응답 필드까지 전부 `project`로 통일했다(backend_decisions.md #5 개정 —
원래는 URL만 /projects, DB는 items 그대로 두기로 했다가, API 표면과 DB 이름이 다르면
헷갈린다는 이유로 DB까지 다 바꾸기로 했다).

POST /projects 는 #6(첨부파일 처리) 확정대로 multipart/form-data 로 폼 데이터와
파일을 한 번에 받는다. 구조화된 필드(회사/아이템/팀원/단가)는 JSON 문자열로 감싸서
`payload` 라는 폼 필드 하나로 보내고, 실제 파일들은 `files` 라는 폼 필드로 따로 보낸다
— multipart 요청 안에서 UploadFile과 중첩된 리스트(JSON body)를 같이 받는 FastAPI의
표준적인 절충 방식이다. 저장은 우선 로컬 디스크(/uploads/)에 하고, 나중에 S3 등으로
바꿀 걸 대비해서 저장 로직을 _save_attachment() 함수 하나로 감쌌다 — 나중엔 이 함수
내부만 바꾸면 된다.
"""
import json
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, MatchResult, PricingItem, Project, ProjectAttachment, TeamMember, User
from app.schemas import ProjectCreateRequest, ProjectDetailOut
from app.security import get_current_user

router = APIRouter(prefix='/projects', tags=['projects'])

# repo 루트/uploads — database.py의 _REPO_ROOT 계산 방식과 동일하게 __file__ 기준으로 잡는다
# (app/routers/projects.py 에서 두 단계 위로 올라가면 app/ 이고, 그 위가 repo 루트).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_REPO_ROOT, 'uploads')

# 진행 중으로 취급하는 매칭 상태 — 이 상태의 매칭을 가진 프로젝트가 하나라도 있으면
# 계정당 동시 실행 1건 제한(기획서 4-7, backend_decisions.md #11)에 걸려 새 프로젝트 생성을 막는다.
ACTIVE_MATCH_STATUSES = ('in_progress',)


def _save_attachment(file: UploadFile) -> tuple[str, str]:
    """첨부파일을 저장하고 (원본 파일명, 접근 가능한 URL)을 반환한다.
    지금은 로컬 디스크에 저장 — 나중에 S3 등으로 바꿀 때 이 함수 내부만 교체하면 된다.
    (main.py 에서 /uploads 를 StaticFiles로 mount 해뒀어야 이 URL로 실제 접근이 된다.)"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or '')[1]
    stored_name = f'{uuid.uuid4().hex}{ext}'
    dest_path = os.path.join(UPLOAD_DIR, stored_name)
    with open(dest_path, 'wb') as out:
        out.write(file.file.read())
    file_url = f'/uploads/{stored_name}'
    return file.filename or stored_name, file_url


def _get_or_create_company(db: Session, current_user: User, body: ProjectCreateRequest) -> Company:
    """회사 프로필을 조회하거나, 없으면 만든다 — "계정당 회사 프로필 1건"이 동시 요청에서도
    깨지지 않도록 insert 후 실패하면 잡는 방식(insert-then-catch)을 쓴다.

    단순히 "조회해서 없으면 생성"만 하면, 같은 유저가 거의 동시에 두 번 요청을 보냈을 때
    둘 다 "없음"을 보고 각자 회사 프로필을 만들어버리는 race가 생긴다 — 그러면 프로필이
    2건이 되고, POST /projects의 동시 실행 제한 체크(진행 중 매칭 여부)도 어느 프로필
    기준으로 봐야 할지 갈라져서 무력화된다. companies.user_id에 건 UNIQUE 제약(app_schema.sql)
    덕분에 두 번째 INSERT는 DB가 IntegrityError로 막아주므로, 그 경우엔 롤백하고 첫 번째
    요청이 막 커밋한 행을 다시 조회해서 그걸 재사용한다."""
    company = db.query(Company).filter(Company.user_id == current_user.user_id).with_for_update().first()
    if company is not None:
        return company

    company = Company(
        user_id=current_user.user_id,
        start_type=body.start_type,
        biz_type=body.biz_type,
        ceo_name=body.ceo_name,
        founded_at=body.founded_at,
    )
    db.add(company)
    try:
        db.flush()  # company_id 확보 — 여기서 UNIQUE 제약 위반이면 IntegrityError
    except IntegrityError:
        db.rollback()
        # 동시 요청이 먼저 커밋한 행을 재사용한다. with_for_update()로 잠가서 이후
        # 진행 중 매칭 체크가 그 요청의 커밋 결과를 확실히 보고 판정하게 한다.
        company = db.query(Company).filter(Company.user_id == current_user.user_id).with_for_update().first()
        if company is None:
            # 이론상 도달 불가(IntegrityError가 났다는 건 이미 행이 있다는 뜻) — 방어적으로만 둠.
            raise HTTPException(status_code=500, detail='회사 프로필 생성 중 오류가 발생했습니다') from None
    return company


@router.post('', response_model=ProjectDetailOut, status_code=201)
async def create_project(
    payload: str = Form(..., description='ProjectCreateRequest 스키마와 동일한 필드를 담은 JSON 문자열'),
    files: list[UploadFile] = File(default_factory=list, description='첨부파일 (여러 개 가능, 없어도 됨)'),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        body = ProjectCreateRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc

    company = _get_or_create_company(db, current_user, body)

    # 계정당 동시 실행 1건 제한(기획서 4-7, backend_decisions.md #11) — projects 자체에는
    # 상태 컬럼이 없어(설계 문서 원안), 진행 중(in_progress) 매칭을 가진 프로젝트가 있는지로
    # 대신 판단한다. with_for_update()로 해당 행을 잠가서, 같은 유저가 거의 동시에 두 번
    # 요청을 보내도 두 번째 요청은 첫 번째 트랜잭션이 끝날 때까지 대기했다가 최신 상태로
    # 다시 판정한다 (그렇지 않으면 두 요청이 동시에 "진행 중 매칭 없음"을 읽어 둘 다
    # 통과해버리는 race가 이론상 가능하다). SQLite는 FOR UPDATE 구문 자체가 없어 이
    # 호출이 조용히 무시되지만, SQLite는 쓰기 트랜잭션을 파일 단위로 직렬화하므로 로컬
    # 개발 환경에서는 어차피 문제되지 않는다 — 운영(MySQL)에서만 실제로 잠금이 걸린다.
    active = (
        db.query(MatchResult)
        .join(Project, Project.project_id == MatchResult.project_id)
        .filter(Project.company_id == company.company_id, MatchResult.status.in_(ACTIVE_MATCH_STATUSES))
        .with_for_update()
        .first()
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=f'진행 중인 프로젝트(project_id={active.project_id})가 있습니다. 이어서 진행하거나 먼저 중단해주세요.',
        )

    project = Project(
        company_id=company.company_id,
        description=body.description,
        notify_region=body.notify_region,
        notify_industry=body.notify_industry,
    )
    db.add(project)
    db.flush()  # project_id 확보

    for m in body.team_members:
        db.add(TeamMember(project_id=project.project_id, name=m.name, role=m.role, experience=m.experience))
    for p in body.pricing_items:
        db.add(PricingItem(project_id=project.project_id, service_name=p.service_name, unit_price=p.unit_price))
    for f in files:
        if not f.filename:
            continue  # 빈 파일 필드는 건너뜀 (프론트가 파일 선택 안 하고 제출한 경우)
        file_name, file_url = _save_attachment(f)
        db.add(ProjectAttachment(project_id=project.project_id, file_name=file_name, file_url=file_url))

    db.commit()
    db.refresh(project)
    return ProjectDetailOut.model_validate(project)


@router.get('/{project_id}', response_model=ProjectDetailOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_owned_project(db, project_id, current_user)
    return ProjectDetailOut.model_validate(project)


def _get_owned_project(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    if project.company.user_id != user.user_id and user.role != 'admin':
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    return project