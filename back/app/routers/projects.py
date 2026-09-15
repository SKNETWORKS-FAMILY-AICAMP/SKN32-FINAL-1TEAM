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
import random
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import agents
from app import pipeline_stages as ps
from app.database import get_db
from app.models import (
    FIXED_TASK_SEQUENCE,
    AgentExecution,
    Artifact,
    ArtifactScoreReason,
    BusinessPlan,
    Company,
    FormatFinding,
    MatchResult,
    PlanScoreReason,
    PlanSection,
    PricingItem,
    Project,
    ProjectAttachment,
    ProofreadLog,
    TeamMember,
    User,
)
from app.schemas import (
    ProjectCreateRequest,
    ProjectDetailOut,
    ProjectOut,
    ProjectStatusOut,
    RetryTaskRequest,
    RetryTaskResponse,
)
from app.security import get_current_user

router = APIRouter(prefix='/projects', tags=['projects'])

# 재시도(POST /projects/{id}/retry-task) 가능한 task_key -> agent_name. FIXED_TASK_SEQUENCE의
# 14단계 중 '조율'(오케스트레이션 체크포인트, 콘텐츠를 만들지 않음) 4개를 뺀 10개 전부 —
# app/agents.py 모듈 docstring의 "Agent 7개 중 여기 6개만 있는 이유" 설명 참고.
_RETRIABLE_TASK_KEYS = {
    'strategy', 'writing',
    'verify1_rubric', 'verify1_evidence',
    'implement_prototype', 'implement_infographic',
    'verify2_static', 'verify2_crosscheck',
    'review_expression', 'review_token_check',
}
_TASK_KEY_TO_AGENT = dict(FIXED_TASK_SEQUENCE)

# 검증-2(verify2_static/verify2_crosscheck)가 artifact_score_reasons 중 어느 item_code를
# 다룰지 구분하는 접두어 — 실제 채점 기준표(rubric) item_code 체계가 정해지면 여기만 고치면 된다.
_VERIFY2_STATIC_PREFIXES = ('CHECK-',)
_VERIFY2_CROSSCHECK_PREFIXES = ('FEATURE-',)


def _num(value: Decimal | None) -> float | None:
    """Decimal -> float. 응답 JSON(changed 필드)에 그대로 넣기 위한 변환."""
    return float(value) if value is not None else None


def _upsert_plan_section(db: Session, plan_id: int, draft) -> dict:
    """plan_sections에 (plan_id, tag)로 찾아서 있으면 갱신, 없으면 새로 만든다 — 전략/작성
    Agent 재시도 공통 로직. draft는 app.agents.SectionDraftResult."""
    section = (
        db.query(PlanSection)
        .filter(PlanSection.plan_id == plan_id, PlanSection.tag == draft.tag)
        .first()
    )
    before = section.body if section is not None else None
    if section is None:
        section = PlanSection(plan_id=plan_id, tag=draft.tag, title=draft.title, body=draft.body)
        db.add(section)
    else:
        section.title = draft.title
        section.body = draft.body
    return {'before': before, 'after': draft.body}

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


@router.get('', response_model=list[ProjectOut])
def list_my_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """내 프로젝트 목록 — 프론트가 "신규 사용자"인지 "이어서 준비 중인 프로젝트가 있는지"를
    서버 기준으로 판단하는 데 쓴다(로컬 저장소에 project_id를 기억해두는 임시방편 대신).
    회사 프로필 자체가 없으면(한 번도 프로젝트를 만든 적 없음) 빈 배열."""
    company = db.query(Company).filter(Company.user_id == current_user.user_id).first()
    if company is None:
        return []
    projects = (
        db.query(Project)
        .filter(Project.company_id == company.company_id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return [ProjectOut.model_validate(p) for p in projects]


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


@router.get('/{project_id}/status', response_model=ProjectStatusOut)
def get_project_status(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """이어하기(기획서 v1.7 4-7절, p.20 8케이스) — 프론트가 이 프로젝트를 다시 열었을 때
    몇 번 화면으로 돌려보내야 하는지를 판별해서 내려준다.

    실제 Agent 파이프라인(다른 팀원이 작업 중인 오케스트레이터)이 각 단계를 시작/진행할
    때마다 match_results.stage(+progress_percent)를 갱신해두면(app/pipeline_stages.py의
    STAGE_* 상수 사용), 이 엔드포인트는 그 값을 읽어 화면 번호로만 바꿔주는 얇은 조회다.
    판별 로직 자체는 verify_resume_cases.py에서 기획서 8케이스 전부에 대해 검증됐다
    (detect_resume_screen()과 동일한 로직 — 거기서는 아직 실제 API가 없어 DB를 직접
    조회해 검증했지만, 여기서는 라우터로 옮기고 소유권 체크(_get_owned_project)만 추가했다).
    """
    project = _get_owned_project(db, project_id, current_user)

    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project.project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    if match is None:
        # 매칭 자체가 없음 — 아직 공고를 고르기 전(8케이스의 ①) -> 화면 3(공고 매칭)으로.
        return ProjectStatusOut(project_id=project.project_id, screen=ps.NO_MATCH_SCREEN)

    screen = ps.STAGE_TO_SCREEN.get(match.stage) if match.stage is not None else None
    return ProjectStatusOut(
        project_id=project.project_id,
        screen=screen,
        stage=match.stage,
        progress_percent=match.progress_percent,
        match_id=match.match_id,
        match_status=match.status,
    )


@router.post('/{project_id}/retry-task', response_model=RetryTaskResponse)
def retry_task(
    project_id: int,
    body: RetryTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """개별 작업 재시도 — 기능정의서 cf. 요구사항 대응(RetryTaskRequest 문서 참고): "재시도
    시 단순히 동일한 결과를 반환하지 않고, 실제 작업을 다시 수행하도록 구현 / 재시도에
    따라 결과물이 실제로 변경되는 것을 확인할 수 있도록 구현".

    실제 작업 재수행 자체(오케스트레이터, Agent 실제 재호출)는 app/agents.py에 인터페이스로
    분리해뒀다 — 이 함수는 DB 조회/락/저장(트랜잭션)만 책임지고, "값을 어떻게 다시 만들지"는
    app.agents의 task_key별 run_*_retry() 함수 호출로 위임한다(전략/작성은 섹션 본문 재작성,
    검증-1/검증-2는 채점 근거 재채점 + 합계 점수 재계산, 구현은 새 파일 저장, 검수는
    format_findings/proofread_logs 새 행 추가 — 매핑은 _RETRIABLE_TASK_KEYS 위 주석과
    app/agents.py 모듈 docstring 참고). 지금은 그 함수들이 전부 더미(무작위) 구현이지만,
    Agent 담당자가 실제 기능을 연동할 때는 app/agents.py 안의 구현부만 바꾸면 되고 이
    라우터는 손댈 필요가 없다. agent_executions는 기존 행을 덮어쓰지 않고 attempt_no를
    증가시켜 항상 새 행으로 쌓는다(재시도 이력 보존 — show_agent_log.py로 확인 가능).
    """
    if body.task_key not in _RETRIABLE_TASK_KEYS:
        raise HTTPException(
            status_code=400,
            detail=(
                f'재시도 가능한 task_key가 아닙니다: {body.task_key!r} '
                f'(가능한 값: {sorted(_RETRIABLE_TASK_KEYS)})'
            ),
        )

    project = _get_owned_project(db, project_id, current_user)

    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project.project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    if match is None:
        raise HTTPException(status_code=404, detail='이 프로젝트엔 아직 매칭 결과가 없어 재시도할 작업이 없습니다')

    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.match_id == match.match_id)
        .order_by(BusinessPlan.plan_id.desc())
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail='이 프로젝트엔 아직 사업계획서가 없어 재시도할 수 없습니다')

    agent_name = _TASK_KEY_TO_AGENT[body.task_key]
    last_attempt = (
        db.query(AgentExecution)
        .filter(AgentExecution.match_id == match.match_id, AgentExecution.task_key == body.task_key)
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    next_attempt_no = (last_attempt.attempt_no + 1) if last_attempt is not None else 1

    changed: dict = {}
    task_key = body.task_key

    if task_key == 'strategy':
        # app/agents.py — 실제 Agent가 연동되면 이 호출 하나만 실제 구현으로 바뀐다(계약은
        # 동일하게 유지). 지금은 더미 구현이 무작위 문구를 돌려준다.
        draft = agents.run_strategy_agent_retry(project.description)
        changed['sections'] = {draft.tag: _upsert_plan_section(db, plan.plan_id, draft)}

    elif task_key == 'writing':
        drafts = agents.run_writing_agent_retry(project.description, tags=['1-1', '2-1'])
        changed['sections'] = {d.tag: _upsert_plan_section(db, plan.plan_id, d) for d in drafts}

    elif task_key in ('verify1_rubric', 'verify1_evidence'):
        reasons = db.query(PlanScoreReason).filter(PlanScoreReason.plan_id == plan.plan_id).all()
        if not reasons:
            raise HTTPException(status_code=404, detail='재채점할 채점 근거(plan_score_reasons)가 없습니다')
        reasons_by_code = {r.item_code: r for r in reasons if r.item_code is not None}
        rubric_input = [(r.item_code, r.max_score or Decimal('10')) for r in reasons if r.item_code is not None]

        if task_key == 'verify1_rubric':
            results = agents.run_verify1_rubric_retry(rubric_input)
        else:
            # E-V1-EVIDENCE: "evidenceLocator 없는 감점은 무효 처리하고 점수를 복원한다" —
            # 이 규칙 자체는 app/agents.py의 run_verify1_evidence_retry() 안에 구현돼 있다.
            results = agents.run_verify1_evidence_retry(rubric_input)

        before_score = plan.doc_score
        item_changes = {}
        for result in results:
            reason = reasons_by_code.get(result.item_code)
            if reason is None:
                continue  # 담당자 구현이 모르는 item_code를 돌려주면 조용히 무시(방어적)
            item_changes[result.item_code] = {
                'before': {'score': _num(reason.score), 'evidence_locator': reason.evidence_locator},
                'after': {'score': _num(result.score), 'evidence_locator': result.evidence_locator},
            }
            reason.score = result.score
            reason.evidence_locator = result.evidence_locator
        plan.doc_score = sum((r.score or Decimal('0')) for r in reasons)
        changed['scores'] = item_changes
        changed['doc_score'] = {'before': _num(before_score), 'after': _num(plan.doc_score)}

    elif task_key in ('implement_prototype', 'implement_infographic'):
        artifact = (
            db.query(Artifact)
            .filter(Artifact.plan_id == plan.plan_id)
            .order_by(Artifact.artifact_id.desc())
            .first()
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail='재시도할 산출물(artifacts)이 없습니다')
        if task_key == 'implement_prototype' and artifact.category == 'onepage':
            raise HTTPException(
                status_code=400,
                detail=(
                    "category='onepage' 산출물은 설계상 실행 파일(executable_path)이 없어서 "
                    '프로토타입 재시도 대상이 아닙니다 (인포그래픽 재시도만 가능)'
                ),
            )

        # 구현 Agent는 파일만 새로 만든다 — 채점(점수 갱신)은 검증-2(verify2_*) 몫이다.
        artifact_kind = 'prototype' if task_key == 'implement_prototype' else 'infographic'
        result = agents.run_implement_agent_retry(
            artifact_kind=artifact_kind, project_description=project.description,
        )

        # 파일은 app/agents.py가 만들어 돌려준 바이트를 그대로 저장한다 — 어디에 저장할지
        # (UPLOAD_DIR)는 여전히 이쪽(호출부) 책임. _save_attachment()는 업로드용이라 재사용
        # 하지 않고, 같은 저장 위치만 맞춘다.
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        stored_name = f'{uuid.uuid4().hex}{result.file_ext}'
        dest_path = os.path.join(UPLOAD_DIR, stored_name)
        with open(dest_path, 'wb') as out:
            out.write(result.file_bytes)
        new_url = f'/uploads/{stored_name}'

        if task_key == 'implement_prototype':
            changed['executable_path'] = {'before': artifact.executable_path, 'after': new_url}
            artifact.executable_path = new_url
        else:
            changed['infographic_path'] = {'before': artifact.infographic_path, 'after': new_url}
            artifact.infographic_path = new_url

    elif task_key in ('verify2_static', 'verify2_crosscheck'):
        artifact = (
            db.query(Artifact)
            .filter(Artifact.plan_id == plan.plan_id)
            .order_by(Artifact.artifact_id.desc())
            .first()
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail='재채점할 산출물(artifacts)이 없습니다')

        prefixes = _VERIFY2_STATIC_PREFIXES if task_key == 'verify2_static' else _VERIFY2_CROSSCHECK_PREFIXES
        all_reasons = (
            db.query(ArtifactScoreReason).filter(ArtifactScoreReason.artifact_id == artifact.artifact_id).all()
        )
        reasons = [r for r in all_reasons if r.item_code and r.item_code.startswith(prefixes)]
        if not reasons:
            raise HTTPException(
                status_code=404,
                detail=f'{task_key}에 해당하는 채점 근거(item_code 접두어 {prefixes})가 없습니다',
            )
        reasons_by_code = {r.item_code: r for r in reasons}
        rubric_input = [(r.item_code, r.max_score or Decimal('10')) for r in reasons]
        results = agents.run_verify2_retry(
            rubric_input, check_kind='static' if task_key == 'verify2_static' else 'crosscheck',
        )

        before_score = artifact.artifact_score
        item_changes = {}
        for result in results:
            reason = reasons_by_code.get(result.item_code)
            if reason is None:
                continue
            item_changes[result.item_code] = {'before': _num(reason.score), 'after': _num(result.score)}
            reason.score = result.score
            reason.evidence_locator = result.evidence_locator
        artifact.artifact_score = sum((r.score or Decimal('0')) for r in all_reasons)
        changed['scores'] = item_changes
        changed['artifact_score'] = {'before': _num(before_score), 'after': _num(artifact.artifact_score)}

    elif task_key == 'review_expression':
        latest = (
            db.query(FormatFinding)
            .filter(FormatFinding.plan_id == plan.plan_id)
            .order_by(FormatFinding.finding_id.desc())
            .first()
        )
        result = agents.run_review_expression_retry(project.description)
        db.add(FormatFinding(
            plan_id=plan.plan_id,
            finding_type=result.finding_type,
            location=result.location,
            message=result.message,
            severity=result.severity,
        ))
        changed['finding'] = {
            'before': latest.message if latest is not None else None,
            'after': result.message,
        }

    elif task_key == 'review_token_check':
        latest = (
            db.query(ProofreadLog)
            .filter(ProofreadLog.plan_id == plan.plan_id)
            .order_by(ProofreadLog.log_id.desc())
            .first()
        )
        result = agents.run_review_token_check_retry(project.description)
        db.add(ProofreadLog(
            plan_id=plan.plan_id,
            original_text=(latest.corrected_text if latest is not None else project.description),
            corrected_text=result.corrected_text,
            reason=result.reason,
        ))
        changed['corrected_text'] = {
            'before': latest.corrected_text if latest is not None else None,
            'after': result.corrected_text,
        }

    else:  # pragma: no cover — _RETRIABLE_TASK_KEYS 체크를 통과했으면 도달할 수 없다.
        raise HTTPException(status_code=500, detail=f'처리 로직이 없는 task_key: {task_key!r}')

    execution = AgentExecution(
        match_id=match.match_id,
        agent_name=agent_name,
        task_key=body.task_key,
        attempt_no=next_attempt_no,
        model_used='dummy-retry',
        rerun_type='rerun',
        token_usage=random.randint(100, 3000),
        status='completed',
    )
    db.add(execution)
    db.commit()

    return RetryTaskResponse(
        project_id=project.project_id,
        match_id=match.match_id,
        task_key=body.task_key,
        agent_name=agent_name,
        attempt_no=next_attempt_no,
        changed=changed,
    )