"""프로젝트 생성(DB 적재) + 조회.

설계 문서 기준으로 "프로젝트"는 companies(회사/예비창업자 프로필) 1건 아래
projects(지원 아이템) N건으로 정규화돼 있다.

[2026-09-15 개정] 예전엔 "회사 프로필은 계정당 1건"이라 가정하고 최초 생성 시 만든 뒤
이후 요청은 재사용했는데(신청자 유형/대표자명/설립일자가 새로 안 바뀜), 프로젝트마다
다른 신청자 정보로 지원하고 싶은 사용자에게 부작용이 있었다. 이제 companies.user_id는
더 이상 UNIQUE가 아니고, POST /projects는 매번 그 요청에 담긴 값으로 회사 프로필을
새로 만든다 — 계정당 여러 프로젝트가 각자 다른 회사 프로필을 가질 수 있다. 계정당 동시
실행 1건 제한(기획서 4-7)은 회사 프로필과 무관하다 — [SB-242]부터 오케스트레이터가 계정 잠금 안에서
최종 확인한다(active_work · request_start).

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
import datetime
import json
import os
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session, object_session

from app.database import get_db
from app.models import (
    Company,
    GenerationFailureAlert,
    Notice,
    NoticeAlert,
    Notification,
    PermanentDeletionLog,
    PricingItem,
    Project,
    ProjectAttachment,
    ProjectBudgetItem,
    ProjectPartner,
    ProjectPlanInput,
    ProjectScheduleItem,
    TeamMember,
    User,
    VerificationPolicy,
)
from app.orch import CodedHTTPException, OrchError, OrchGateway, account_id_of, mapping, require_gateway
from app.proofread_retention import clear_project_logs
from app.routers.profile import compute_has_profile
from app.schemas import (
    DemoGenerateRequest,
    DemoGenerateResponse,
    MatchCandidatesOut,
    NotificationOut,
    NotificationReadIn,
    ProceedRequest,
    ProjectCreateRequest,
    ProjectDetailOut,
    ProjectListItemOut,
    ProjectStatusOut,
    RetryTaskRequest,
    ReworkAcceptedOut,
    ReworkResultOut,
)
from app.security import ACCOUNT_WITHDRAWING, get_current_user

router = APIRouter(prefix='/projects', tags=['projects'])


# repo 루트/uploads — database.py의 _REPO_ROOT 계산 방식과 동일하게 __file__ 기준으로 잡는다
# (app/routers/projects.py 에서 두 단계 위로 올라가면 app/ 이고, 그 위가 repo 루트).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_REPO_ROOT, 'uploads')

# [2026-09-29 신규, 프론트 요청사항 3차 B-5, 팀 확정 2026-09-29] POST /projects 첨부파일
# 상한 — 프론트(front/src/features/workflow/shared.jsx)와 값을 맞춰야 하는 숫자라 여기
# 상수 하나로 모아둔다. 프론트 검사(FileAttach)는 우회 가능하므로 서버에서도 같은 값으로
# 막는다(create_project 참고).
ATTACH_MAX_FILES = int(os.getenv('ATTACH_MAX_FILES', '5'))
ATTACH_MAX_MB = int(os.getenv('ATTACH_MAX_MB', '10'))
ATTACH_MAX_BYTES = ATTACH_MAX_MB * 1024 * 1024

def _save_attachment(file: UploadFile) -> tuple[str, str]:
    """첨부파일을 저장하고 (원본 파일명, 접근 가능한 URL)을 반환한다.
    지금은 로컬 디스크에 저장 — 나중에 S3 등으로 바꿀 때 이 함수 내부만 교체하면 된다.
    /uploads 경로는 로그인 및 프로젝트 소유권 검사 후 파일을 제공한다."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or '')[1]
    stored_name = f'{uuid.uuid4().hex}{ext}'
    dest_path = os.path.join(UPLOAD_DIR, stored_name)
    with open(dest_path, 'wb') as out:
        out.write(file.file.read())
    file_url = f'/uploads/{stored_name}'
    return file.filename or stored_name, file_url


def _create_company_for_project(db: Session, current_user: User, body: ProjectCreateRequest) -> Company:
    """이 프로젝트용 회사 프로필을 새로 만든다. 계정당 여러 프로젝트가 각자 다른 신청자
    유형/대표자명/설립일자를 가질 수 있도록, 재사용하지 않고 매번 새로 만든다 — 동시
    실행 제한은 이 함수가 아니라 _lock_user_for_concurrency_check()가 담당하므로, 여기선
    더 이상 동시 요청을 막기 위한 락이나 insert-then-catch가 필요 없다."""
    company = Company(
        user_id=current_user.user_id,
        # [2026-09-17 배선] IntakeForm.jsx가 필수로 물어보는 신청자 유형이 여기까지 안 실려서
        # 화면에서 고른 값이 버려지고 있었다 — 이제 받아서 저장한다(리뷰 중 발견).
        applicant_type=body.applicant_type,
        biz_type=body.biz_type,
        ceo_name=body.ceo_name,
        founded_at=body.founded_at,
        # [2026-09-17 배선] 컬럼은 있었는데 요청 바디에서 받아서 저장하는 코드가 없었다.
        company_name=body.company_name,
        business_reg_no=body.business_reg_no,
        rep_type=body.rep_type,
    )
    db.add(company)
    db.flush()  # company_id 확보
    return company


@router.get('', response_model=list[ProjectListItemOut])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """대시보드 "내 프로젝트" 목록. [2026-09-15 개정] 계정당 회사 프로필이 이제 여러 건일
    수 있으므로(프로젝트마다 따로 만듦), Company를 거치지 않고 Project를 Company와 join해
    Company.user_id로 직접 필터링한다 — 프로젝트를 한 번도 안 만든 신규 유저는 join 결과가
    그냥 빈 목록이라 별도 분기가 필요 없다.

    [2026-09-28, match_results 테이블 통합] 예전엔 프로젝트마다 가장 최근 MatchResult를
    N+1 쿼리로 따로 조회했었다(project 하나당 쿼리 한 번씩) — match_results가 projects로
    합쳐지면서 그 N+1이 사라지고, 아래처럼 Project 하나만 조회하면 진행 상태까지 전부
    같이 나온다."""
    projects = (
        db.query(Project)
        .join(Company, Company.company_id == Project.company_id)
        .filter(Company.user_id == current_user.user_id)
        .order_by(Project.created_at.desc())
        .all()
    )
    visible = [p for p in projects if p.archived_at is None]  # 사용자가 지운(보관 처리한) 프로젝트는 숨긴다
    # [SB-242] 진행 상태는 projects 컬럼이 아니라 오케스트레이터가 원본이다 — 한 번에 읽는다.
    views = {v.project_id: v for v in gateway.project_views([p.project_id for p in visible])}
    announcement_ids = [v.run.announcement_id for v in views.values() if v.run and v.run.announcement_id]
    titles = {}
    if announcement_ids:
        # 제목만 필요하다 — 엔티티 전체를 읽으면 임베딩 벡터 · 원본 JSON까지 목록 조회마다 끌어온다
        rows = db.query(Notice.notice_id, Notice.title).filter(Notice.notice_id.in_(announcement_ids)).all()
        titles = {notice_id: title for notice_id, title in rows}
    items = []
    for project in visible:
        view = views.get(str(project.project_id))
        announcement_id = view.run.announcement_id if view is not None and view.run is not None else None
        items.append(mapping.project_list_item(project, view, titles.get(announcement_id)))
    return items


@router.get('/notifications', response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """[2026-09-27 신규, SB-141] 화면 헤더 종모양 알림 — 공식 기능정의서 v1.9 Notification
    타입(kind=문서평가/산출물확인/표현검수/실패). GET /projects의 display_status(진행/완료/
    실패 3분류)와는 별개다 — 저건 "지금 상태가 뭔지"를 보여주는 목록 요약이고, 이건
    "그동안 무슨 일이 있었는지"의 이력이다. 반드시 이 경로를 GET /projects/{project_id}
    (line 1396 근처)보다 먼저 등록해야 한다 — 안 그러면 "notifications"가 project_id로
    잘못 매칭된다."""
    query = (
        db.query(Notification)
        .join(Project, Project.project_id == Notification.project_id)
        .join(Company, Company.company_id == Project.company_id)
        .filter(Company.user_id == current_user.user_id)
    )
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return query.order_by(Notification.created_at.desc()).all()


@router.patch('/notifications/{notification_id}/read', response_model=NotificationOut)
def mark_notification_read(
    notification_id: int,
    body: NotificationReadIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = (
        db.query(Notification)
        .join(Project, Project.project_id == Notification.project_id)
        .join(Company, Company.company_id == Project.company_id)
        .filter(Notification.notification_id == notification_id, Company.user_id == current_user.user_id)
        .one_or_none()
    )
    if notification is None:
        raise HTTPException(status_code=404, detail='알림을 찾을 수 없습니다')
    notification.read_at = datetime.datetime.utcnow() if body.read else None
    db.commit()
    db.refresh(notification)
    return notification


# [SB-242] 공고 후보 · 추가 조회 — 공고 추천은 워커가 돌리고 웹은 결과를 읽는다(무작위 임시 후보 제거).
# 응답을 기다리는 제한 시간(초). 명세 기본값은 60초지만 동기 엔드포인트가 스레드를 오래 붙잡지 않도록 줄였다(잠정 —
# 배포 때 웹 서버 · 프록시 제한 시간에 맞춰 다시 정한다). 못 끝내면 status='pending'으로 답하고 프론트가 다시 부른다.
ORCH_WAIT_TIMEOUT_SEC = 25.0
_EXECUTING = ('실행', '재개대기')


def _release_db(db: Session | None) -> None:
    """[SB-266] 워커를 기다리기 전에 이 요청의 DB 연결을 풀에 돌려준다.

    요청의 DB 세션은 쿼리를 한 번 하면 요청이 끝날 때까지 연결을 붙잡는다. 워커를 기다리는 조회는 최대 ORCH_WAIT_TIMEOUT_SEC(운영 25초)
    걸리는데, 그동안 연결을 쥐고 있으면 웹 DB 연결 풀(기본 15개)이 대기 요청으로 차서 DB를 쓰는 다른 요청이 모두 막히고 그 이상이면
    풀 시간 초과(500)가 난다(scripts/load_check.py로 측정). 대기 앞에서는 읽기만 했으므로 rollback으로 연결만 돌려주고, 세션은 그대로 써서
    대기 뒤에 필요하면 새 연결로 다시 읽는다(객체는 다음 접근 때 새로 읽힌다)."""
    if db is not None:
        db.rollback()


def _is_withdrawing(user: User) -> bool:
    """[SB-298] 지금(DB 최신 값) 탈퇴 중인 계정인지 — 탈퇴가 다른 요청에서 막 시작됐을 수 있어 매번 다시 읽는다."""
    session = object_session(user)
    if session is not None:
        session.refresh(user)
    return user.status == ACCOUNT_WITHDRAWING


WITHDRAWING_MESSAGE = '계정 탈퇴를 처리하는 중이라 새로 시작할 수 없어요. 탈퇴를 마저 진행해 주세요.'


def _candidates_response(gateway: OrchGateway, project: Project) -> MatchCandidatesOut:
    project_id = project.project_id
    _release_db(object_session(project))
    view = gateway.wait_project(project_id, timeout_sec=ORCH_WAIT_TIMEOUT_SEC)
    start = view.start
    if view.run is None and start is not None and start.status == '실패' and start.code in mapping.START_RETRYABLE:
        # 다시 시도할 수 있는 시작 실패(명세 3.1) — 같은 프로젝트로 시작 요청을 다시 넣고 기다린다.
        # 탈퇴 중인 계정은 시작 요청을 넣지 않는다(SB-298).
        if _is_withdrawing(project.company.user):
            return MatchCandidatesOut(
                candidates=[], rematch_used=False, status='failed', code='ACCOUNT_WITHDRAWING', message=WITHDRAWING_MESSAGE)
        check = gateway.request_start(account_id_of(project.company.user_id), project_id)
        if not check.ok:
            return MatchCandidatesOut(
                candidates=[], rematch_used=False, status='failed', code=check.code, message=check.message)
        _release_db(object_session(project))
        view = gateway.wait_project(project_id, timeout_sec=ORCH_WAIT_TIMEOUT_SEC)
    if view.run is None:
        return mapping.candidates_unavailable(view.start)
    if view.run.progress in _EXECUTING:
        return mapping.pending_candidates()
    return mapping.candidates_out(gateway.screen(project_id, 3))


@router.get('/{project_id}/match-candidates', response_model=MatchCandidatesOut)
def get_match_candidates(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """공고 후보(화면 3). 사전 단계가 끝났으면 후보를, 아직이면 status='pending'을(프론트가 다시 부른다),
    후보가 없거나 실패면 status='no_match'·'failed'와 안내 문구를 돌려준다. 순서는 공고팀 순위 그대로다."""
    project = _get_owned_project(db, project_id, current_user)
    return _candidates_response(gateway, project)


@router.post('/{project_id}/match-candidates/rematch', response_model=MatchCandidatesOut)
def rematch_candidates(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """공고 추가 조회(다시 찾기) — 1회, 합계 최대 20건. 새 후보가 없으면 message로 안내하고 갱신된 목록을 준다.
    추가 조회가 실패하면 기회를 돌려받으므로 notices에 안내만 붙고 rematch_used는 거짓이다."""
    project = _get_owned_project(db, project_id, current_user)
    gateway.more_candidates_for_project(project_id)
    out = _candidates_response(gateway, project)
    if out.status == 'ready':
        out.message = mapping.rematch_message(out)
    return out


# [SB-243] 공고 선택 → 자격 확인 · 계획서 · 프로토타입 · 종합 평가 · 검수 시작 · 결과 조회.
# 단계를 도는 일은 워커가 하고 웹은 명령을 넣은 뒤 진행 상태(view_project)와 결과(outputs)를 읽는다.
# 같은 단계를 여러 번 시작해도(INVALID_STATE) 한 번만 시작되고 지금 상태를 돌려준다 — 기존 동작 그대로.
_BEFORE_WRITING_STEPS = {
    '공고선택': '먼저 공고를 선택해 주세요.',
    '자격확인': '자격 확인이 끝난 뒤에 시작할 수 있어요.',
}


def _eligibility_response(
    db: Session, gateway: OrchGateway, project_id: int, notice_id: str | None, notices_before: int | None,
) -> DemoGenerateResponse:
    """자격 확인(G-01) 결과를 기다려 화면 4 모양으로 답한다.

    notice_id: 방금 고른 공고(있으면 자격 확인이 그 공고로 끝났는지 본다 — 공고 서버 오류면 고르기 전 값 그대로라 다르다).
    notices_before: 명령 전 안내 개수. 그 뒤에 쌓인 안내(E-G1-* · X-C2-*)만 이번 결과의 안내로 쓴다(None이면 화면 4 안내만).
        GET에서 notice_id만 받은 경우는 명령 전 개수를 모르므로 실패 안내를 전체 안내에서 찾는다(가장 최근 E-G1-* 하나).
    """
    _release_db(db)
    view = gateway.wait_project(project_id, timeout_sec=ORCH_WAIT_TIMEOUT_SEC)
    run = view.run
    if run is None:
        raise OrchError('RUN_NOT_FOUND', str(project_id))
    new_notices = list(run.notices)[notices_before:] if notices_before is not None else []
    # 화면 5에서 다시 고른 공고의 자격 확인이 실패하면 화면 4는 이전 공고 값 그대로다 — 방금 고른 공고(notice_id)와 다르면 실패로 답한다
    failure_notices = new_notices if notices_before is not None or notice_id is None else list(run.notices)
    if run.progress in _EXECUTING:
        return mapping.select_pending(project_id)
    try:
        screen = gateway.screen(project_id, 4)
    except OrchError as exc:
        if exc.code != 'SCREEN_NOT_READY':
            raise
        return mapping.select_failed(project_id, failure_notices)
    if notice_id is not None and screen.announcement_id != notice_id:
        return mapping.select_failed(project_id, failure_notices)
    outputs = gateway.outputs(project_id)
    notices = mapping.notices_out([*new_notices, *screen.notices])
    seen: set[str] = set()
    notices = [n for n in notices if not (n.code in seen or seen.add(n.code))]
    return DemoGenerateResponse(
        project_id=project_id,
        match=mapping.match_out(outputs, screen.announcement_id),
        eligibility=mapping.eligibility_out(screen.gate_result, screen.business_age_years, screen.can_start_writing),
        notices=notices,
    )


@router.post('/{project_id}/generate', response_model=DemoGenerateResponse)
def generate_pipeline_result(
    project_id: int,
    body: DemoGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """공고 선택 → 자격 확인(화면 3 → 4). 고른 공고를 오케스트레이터에 알리면 워커가 공고 상세 · 자격 판정을 받아 온다.
    응답은 DemoGenerateResponse의 status로 갈린다 — 'ready'면 eligibility(통과 · 불통과 · 확인 필요) · match,
    'pending'이면 아직 확인 중(GET /eligibility로 다시 읽는다), 'failed'면 공고 서버 오류 · 공고 없음이라
    고르기 전 화면으로 돌아간다(message 안내). 이 시점엔 계획서 · 점수가 없어 plan 이하는 비어 있다.
    후보에 없는 공고는 422, 자격 불통과로 막힌 공고는 409(오류 코드는 app/orch/errors.py)."""
    _get_owned_project(db, project_id, current_user)
    if not body.notice_id:
        raise CodedHTTPException(422, 'NOTICE_REQUIRED', '고를 공고를 알려 주세요.')
    view = gateway.view_project(project_id)
    notices_before = len(view.run.notices) if view.run is not None else 0
    gateway.select_announcement_for_project(project_id, body.notice_id)
    return _eligibility_response(db, gateway, project_id, body.notice_id, notices_before)


@router.get('/{project_id}/eligibility', response_model=DemoGenerateResponse)
def get_eligibility(
    project_id: int,
    notice_id: str | None = Query(None, description='방금 고른 공고 ID(POST /generate 때 보낸 값). 주면 자격 확인이 그 공고로 끝났는지 확인한다.'),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """자격 확인 결과(화면 4)를 다시 읽는다 — POST /generate가 'pending'으로 답했을 때나 화면을 다시 열 때.

    화면 5에서 다시 고른 공고의 자격 확인이 실패하면 오케스트레이터는 이전 공고의 결과를 그대로 둔다(명세 6.1).
    pending 뒤에 폴링할 때는 notice_id를 붙여야 그 이전 결과를 ready로 받지 않고 status='failed'로 받는다.
    notice_id 없이 부르면 지금 화면 4의 공고 결과를 그대로 준다(화면을 다시 열 때)."""
    _get_owned_project(db, project_id, current_user)
    return _eligibility_response(db, gateway, project_id, notice_id or None, None)


def _start_stage(project_id: int, gateway: OrchGateway, command) -> ProjectStatusOut:
    """단계 시작 명령을 넣고 지금 진행 상태를 돌려준다. 이미 시작됐거나 지난 단계(INVALID_STATE)면 명령 없이 상태만 준다."""
    try:
        command()
    except OrchError as exc:
        if exc.code == 'RUN_NOT_FOUND':
            raise CodedHTTPException(400, 'STAGE_NOT_REACHED', _BEFORE_WRITING_STEPS['공고선택']) from exc
        if exc.code != 'INVALID_STATE':
            raise
    view = gateway.view_project(project_id)
    if view.run is None:
        raise CodedHTTPException(400, 'STAGE_NOT_REACHED', _BEFORE_WRITING_STEPS['공고선택'])
    if view.run.step in _BEFORE_WRITING_STEPS and view.run.progress == '사용자대기':
        raise CodedHTTPException(400, 'STAGE_NOT_REACHED', _BEFORE_WRITING_STEPS[view.run.step])
    return mapping.project_status_out(project_id, view)


@router.post('/{project_id}/plan/start', response_model=ProjectStatusOut)
def start_plan_generation(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """사업계획서 생성 시작(화면 5). 바로 응답하고 작성은 워커가 한다 — 진행은 GET /projects/{id}/status의
    stage='plan_writing' + progress_percent로 보고, 끝나면 stage='plan_review_pending'. 여러 번 불러도 한 번만 시작한다."""
    _get_owned_project(db, project_id, current_user)
    return _start_stage(project_id, gateway, lambda: gateway.start_writing_for_project(project_id))


@router.post('/{project_id}/prototype/start', response_model=ProjectStatusOut)
def start_prototype_generation(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """프로토타입 생성 시작(화면 6 '진행'). stage='prototype_building' + progress_percent로 진행되고,
    끝나면 stage='artifact_review'(산출물 확인, 사용자 확인 대기)."""
    _get_owned_project(db, project_id, current_user)
    return _start_stage(project_id, gateway, lambda: gateway.decide_for_project(project_id, 6, '진행'))


@router.post('/{project_id}/final-review/start', response_model=ProjectStatusOut)
def start_final_review(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """산출물 확인 → 종합 평가(화면 8 → 9, '종합 평가 확인하기'). 실행할 단계 없이 바로 stage='final_review_pending'이 된다.
    [SB-243 신규 — 엔드포인트 이름은 프론트와 합의해 확정(2026-10-06).]"""
    _get_owned_project(db, project_id, current_user)
    return _start_stage(project_id, gateway, lambda: gateway.decide_for_project(project_id, 8, '진행'))


@router.post('/{project_id}/review/start', response_model=ProjectStatusOut)
def start_review(
    project_id: int,
    body: ProceedRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """종합 평가 → 표현 검수(화면 9 → 10). stage='reviewing'으로 진행되고 끝나면 stage='done'.
    기준 점수에 못 미친 채로 진행하면 검수 뒤에는 되돌릴 수 없어 409 + {confirmation_required, reason, items}로 확인을 받는다 —
    사용자가 확인하면 body {"confirmed": true}로 다시 부른다. [SB-243 신규 — 엔드포인트 이름은 프론트와 합의해 확정(2026-10-06).]"""
    _get_owned_project(db, project_id, current_user)
    confirmed = body.confirmed if body is not None else False

    def command():
        needed = gateway.decide_for_project(project_id, 9, '진행', confirmed=confirmed)
        if needed is not None:
            raise CodedHTTPException(409, 'CONFIRMATION_REQUIRED', {
                'confirmation_required': True, 'reason': needed.reason, 'items': needed.items})

    return _start_stage(project_id, gateway, command)


@router.get('/{project_id}/result', response_model=DemoGenerateResponse)
def get_pipeline_result(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """지금까지 만든 결과(계획서 · 점수 · 산출물 · 검수 기록)를 현재 버전으로 돌려준다 — 새로고침 · 이어하기용.
    실행 건이 없으면 404, 실패 · 중단된 실행이면 409(결과를 볼 수 없음), 계획서가 아직 없으면 404(작성 중)."""
    _get_owned_project(db, project_id, current_user)
    outputs = gateway.outputs(project_id)
    if outputs.plan_doc is None:
        raise CodedHTTPException(
            404, 'PLAN_NOT_READY',
            '이 프로젝트엔 아직 계획서가 없습니다 — POST /projects/{id}/plan/start 로 먼저 만들어야 합니다',
        )
    policy = db.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    return mapping.result_out(project_id, outputs, policy, _proofread_originals(gateway, project_id, outputs))


def _proofread_originals(gateway: OrchGateway, project_id: int, outputs) -> dict[str, str] | None:
    """검수 기록이 있을 때 화면 10에서 문장별 검수 전 원문을 읽는다(sentenceId → before) — [SB-297].

    표현 검수가 끝나면 현재 계획서(planDoc)의 문장이 검수 결과 문장으로 바뀌므로, 검수 전 원문은 계획서가 아니라 화면 10에서 읽는다.
    화면 10은 결과물 · 완료에서만 열린다 — 아직 열 수 없으면(검수 중 등) 계획서가 바뀌기 전이라 None(계획서 문장을 쓴다)."""
    if not outputs.sentence_results:
        return None
    try:
        screen = gateway.screen(project_id, 10)
    except OrchError as exc:
        if exc.code in ('SCREEN_NOT_READY', 'INVALID_STATE'):
            return None
        raise
    return {s.sentence_id: s.before for s in screen.sentences}


def _plan_section_bodies(gateway: OrchGateway, project_id: int) -> dict[str, str]:
    """계획서 본문(섹션 코드 → 본문)을 오케스트레이터의 지금 결과에서 읽는다. 실행 건이 없거나 계획서가 아직 없거나
    실패 · 중단이면 비운다 — 그러면 문서는 입력값과 자리표시로 채운 미리보기가 된다(실패 · 중단은 본문을 싣지 않는다)."""
    try:
        outputs = gateway.outputs(project_id)
    except OrchError as exc:
        if exc.code in ('RUN_NOT_FOUND', 'RUN_NOT_VIEWABLE'):
            return {}
        raise
    return mapping.section_bodies(outputs.plan_doc) if outputs.plan_doc is not None else {}


# companies.applicant_type -> 양식의 "사업자 구분" 표기. 사용자가 직접 고른 값이라
# 추측할 필요가 없다 — 예전엔 설립일 유무로 갈랐는데, 개인사업자도 설립일이 있으니
# 항상 '법인사업자'로 찍히는 버그였다(사용자 지적, 생성된 PDF로 확인).
_APPLICANT_TYPE_LABEL = {'corp': '법인사업자', 'individual': '개인사업자', 'preliminary': '예비창업자'}


def _build_plan_document_data(db: Session, project: Project, section_bodies: dict[str, str]):
    """project(+company/team_members/pricing_items/budget_items/schedule_items/partners)와
    생성된 계획서(BusinessPlan.sections)를 공식 양식(별첨1) 구조(app/plan_document_export.py의
    PlanDocumentData)로 옮긴다. 반환값은 (data, template) 튜플 — template은 company.
    applicant_type이 'preliminary'(예비창업자)면 'preliminary', 그 외(individual/corp/
    미입력)면 'early_general'이다. 두 양식은 원본 파일(사용자가 준 초기창업패키지(일반형)/
    예비창업패키지 .docx 2종)을 직접 비교해서 실제로 다른 항목만 갈랐다
    (app/plan_document_export.py 모듈 docstring 참고).

    [2026-09-17 배선] company_name/business_reg_no/rep_type(companies),
    output_summary/tech_field/regional_priority_area(projects),
    project_budget_items/project_schedule_items/project_partners 테이블이 이번에 스키마에
    추가됐지만, 이 함수는 그 뒤로도 계속 하드코딩 placeholder('○○○' 등)를 반환하고 있었다
    — 멘토링 피드백("실제 API·Agent 입출력 구조와 DB 스키마 간 정합성 점검 필요")으로
    발견. 이제 값이 있으면 실제 DB 값을, 없으면(아직 그 화면/Agent가 안 만들어져 입력된
    적이 없는 경우) 기존처럼 원본 양식 안내 표기로 채운다 — 지어내지 않는다는 원칙은
    유지. 정부지원사업비/자기부담금/총사업비는 project_budget_items 행이 있으면 그 금액을
    합산해서 채운다(각 행이 없으면 합계도 낼 수 없으니 placeholder 유지)."""
    from app.plan_document_export import BudgetLineItem, PartnerRow, PlanDocumentData, ScheduleRow, TeamRow

    company = db.get(Company, project.company_id)

    # [2026-09-23] IntakeForm "사업 계획" 섹션 값은 2026-09-22부터 project_plan_inputs에
    # 저장되는데(create_project), 이 함수는 그때 같이 안 고쳐져서 계속 companies/projects만
    # 읽고 있었다 — 그래서 소재지·업종·개발기간을 입력해도 문서엔 ○○로 나왔다(사용자 지적,
    # 생성된 PDF로 확인). 특히 소재지는 '○○도 ○○시·군'이 코드에 박혀 있어 무슨 값을
    # 넣어도 안 바뀌었다. 값이 있으면 쓰고, 없을 때만 기존 placeholder로 돌아간다.
    plan_input = (
        db.query(ProjectPlanInput).filter(ProjectPlanInput.project_id == project.project_id).one_or_none()
    )
    region_text = None
    dev_period_text = None
    if plan_input is not None:
        region_text = ' '.join(x for x in (plan_input.region_sido, plan_input.region_sigungu) if x) or None
        if plan_input.dev_start_month and plan_input.dev_end_month:
            dev_period_text = f'{plan_input.dev_start_month} ~ {plan_input.dev_end_month}'

    def _section_body(tag: str) -> str:
        return section_bodies.get(tag) or '※ 아직 생성된 계획서 문단이 없습니다.'

    def _or_placeholder(value, placeholder):
        return value if value else placeholder

    team_members = project.team_members
    team_rows = [
        TeamRow(str(i + 1), m.role or '팀원', m.role or '-', m.experience or '-', '-')
        for i, m in enumerate(team_members)
    ] or [TeamRow('1', '○○', '○○', '○○', '○○')]
    team_text = '\n'.join(
        f'{m.name}({m.role or "역할 미입력"}): {m.experience or "경력 정보 미입력"}' for m in team_members
    ) or '※ 등록된 팀원 정보가 없습니다.'

    def _won(amount) -> str:
        return f'{amount:,.0f}원' if amount is not None else '○○'

    # 사업비 집행계획: project_budget_items(신규, 정식 입력)가 있으면 그걸 그대로 쓰고,
    # 없으면 예전처럼 pricing_items(수익모델 단가)로 대략 채운다(둘은 다른 개념이라 임시
    # 대체일 뿐 — app_schema.sql의 project_budget_items 테이블 주석 참고).
    budget_items = sorted(project.budget_items, key=lambda b: b.item_order or 0)
    if budget_items:
        budget_rows = [
            BudgetLineItem(
                b.category or '○○', b.execution_plan or '○○', _won(b.total_amount),
                _won(b.government_amount), _won(b.self_cash_amount), _won(b.self_in_kind_amount),
            )
            for b in budget_items
        ]
        total_amount = sum((b.total_amount or 0) for b in budget_items)
        government_amount = sum((b.government_amount or 0) for b in budget_items)
        self_cash = sum((b.self_cash_amount or 0) for b in budget_items)
        self_in_kind = sum((b.self_in_kind_amount or 0) for b in budget_items)
        total_amount_text, government_amount_text = _won(total_amount), _won(government_amount)
        self_cash_text, self_in_kind_text = _won(self_cash), _won(self_in_kind)
    else:
        budget_rows = [
            BudgetLineItem(p.service_name, p.service_name, f'{p.unit_price:,.0f}원' if p.unit_price else '○○', '○○', '○○', '○○')
            for p in project.pricing_items
        ] or [BudgetLineItem('○○', '○○', '○○', '○○', '○○', '○○')]
        total_amount_text = government_amount_text = self_cash_text = self_in_kind_text = '○○,○○○천원'

    feasibility_schedule = sorted(
        (s for s in project.schedule_items if s.section == 'feasibility'), key=lambda s: s.item_order or 0
    )
    growth_schedule = sorted(
        (s for s in project.schedule_items if s.section == 'growth'), key=lambda s: s.item_order or 0
    )

    def _schedule_rows(rows):
        # 세부 일정(project_schedule_items)을 입력받는 화면이 아직 없어 대부분 빈 목록이다.
        # 그때라도 IntakeForm에서 받은 개발 기간은 기간 칸에 넣어준다 — 한 줄이라도 실제
        # 입력값이 보이는 편이 낫다.
        return [
            ScheduleRow(str(i + 1), s.category or '○○', s.period or dev_period_text or '○○.○○ ~ ○○.○○',
                        s.detail or s.content or '○○')
            for i, s in enumerate(rows)
        ] or [ScheduleRow('1', '○○', dev_period_text or '○○.○○ ~ ○○.○○', '○○')]

    # [2026-09-22 수정] 예전엔 project_partners 테이블(project.partners)에서 읽었는데,
    # 그 테이블엔 아무도 값을 넣지 않는다 — IntakeForm.jsx "협력 기관" 입력은 project_plan_inputs
    # 테이블에 JSON(ProjectPlanInput.partners, {name, status} 모양)으로 저장된다
    # (schemas.py PlanPartnerIn 참고). 그래서 실제로 입력해도 사업계획서엔 항상 플레이스홀더만
    # 나오고 있었다(버그). project_partners는 여전히 다른 용도(Agent가 나중에 채우는 협력기관
    # 제안 등)로 남겨두되, 지금 사용자가 직접 입력한 값이 있으면 그걸 우선한다.
    #
    # [2026-09-22 매핑 수정] intake는 {name, status}만 주는데, status('협력 중'/'예정')를
    # 원래 협력시기(날짜/분기 등이 들어가는 칸 — dummy 데이터의 '00.00' 참고)에 넣고
    # 있어서 "협력시기: 협력 중" 같은 의미 안 맞는 문장이 나가고 있었다. status는 협업
    # 진행 상태를 나타내니 협업방안 자리로 옮기고, 실제 값이 없는 보유역량/협력시기는
    # 다른 곳과 같은 자리표시자 관례('○○')를 쓴다(하드코딩 '-' 대신).
    plan_partners = (project.plan_input.partners if project.plan_input else None) or []
    if plan_partners:
        partner_rows = [
            PartnerRow(str(i + 1), p.get('name') or '○○', '○○', p.get('status') or '○○', '○○')
            for i, p in enumerate(plan_partners)
        ]
    else:
        partner_rows = [
            PartnerRow(str(i + 1), p.partner_name or '○○', p.capability or '○○', p.collaboration_plan or '○○', p.collaboration_timing or '○○')
            for i, p in enumerate(sorted(project.partners, key=lambda p: p.item_order or 0))
        ]

    item_desc = project.description or ''
    template = 'preliminary' if company and company.applicant_type == 'preliminary' else 'early_general'

    data = PlanDocumentData(
        기업명=_or_placeholder(company.company_name if company else None, '○○○'),
        개업연월일=str(company.founded_at) if company and company.founded_at else '예비창업자(개업 전)',
        사업자_구분=_APPLICANT_TYPE_LABEL.get(company.applicant_type if company else None, '개인사업자'),
        대표자_유형=_or_placeholder(company.rep_type if company else None, '단독'),
        사업자등록번호=_or_placeholder(company.business_reg_no if company else None, '○○○-○○-○○○○○'),
        사업자_소재지=_or_placeholder(region_text, '○○도 ○○시·군'),
        창업아이템명=item_desc[:60] or '○○기술이 적용된 ○○제품·서비스',
        산출물=_or_placeholder(project.output_summary, '○○ (협약기간 내 목표 — 산출물 형태·수량 입력 필요)'),
        지원분야='○○',
        # 전문기술분야 입력칸은 아직 없다 — 그 전까진 IntakeForm에서 받는 주업종으로 채운다.
        전문기술분야=_or_placeholder(
            project.tech_field or (plan_input.main_industry or plan_input.main_industry_free if plan_input else None),
            '○○·○○',
        ),
        정부지원사업비=government_amount_text,
        자기부담_현금=self_cash_text,
        자기부담_현물=self_in_kind_text,
        총사업비=total_amount_text,
        지방우대_지역_해당여부=_or_placeholder(project.regional_priority_area, '해당 없음'),
        팀구성현황=team_rows,
        아이템_명칭=item_desc[:20] or '○○',
        # [2026-09-22, 재희님 확인] Agent가 아이디어 설명을 보고 직접 짓는 항목 —
        # 전략/작성 시트(2.3/3.3) 참고, 사용자 입력을 받지 않는다.
        아이템_범주='○○',
        아이템_개요=item_desc,
        요약_문제인식=_section_body('1-1'),
        요약_실현가능성=_section_body('2-1'),
        요약_성장전략=_section_body('3-1'),
        요약_팀구성=team_text,
        문제인식_본문=_section_body('1-1'),
        실현가능성_본문=_section_body('2-1'),
        실현가능성_일정=_schedule_rows(feasibility_schedule),
        사업비_집행계획=budget_rows,
        성장전략_본문=_section_body('3-1'),
        성장전략_일정=_schedule_rows(growth_schedule),
        팀구성_본문=team_text,
        팀구성_안=team_rows,
        협력기관=partner_rows,
        # 예비창업패키지 전용(early_general 렌더링에서는 안 쓰임) — 기업(예정)명은
        # company_name을 그대로 재사용한다(예비창업자도 창업 예정 상호를 입력할 수 있음).
        직업=_or_placeholder(project.plan_input.occupation if project.plan_input else None, '○○○'),
        기업예정명=_or_placeholder(company.company_name if company else None, '○○○'),
    )
    return data, template


@router.get('/{project_id}/plan-document.docx')
def download_plan_document(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """사업계획서를 공식 양식(별첨1) 구조로 채운 진짜 .docx로 내려준다
    (app/plan_document_export.py). company.applicant_type이 'preliminary'(예비창업자)면
    예비창업패키지 양식, 그 외면 초기창업패키지(일반형) 양식으로 자동 분기한다
    (_build_plan_document_data 참고). 매칭/계획서가 아직 없어도 막지 않는다 —
    _build_plan_document_data가 없는 값은 원본 양식 안내 표기로 채워서라도 지금
    입력된 정보(프로젝트 설명·팀원)만으로 미리보기를 볼 수 있게 한다."""
    from app.plan_document_export import render_plan_docx

    project = _get_owned_project(db, project_id, current_user)
    data, template = _build_plan_document_data(db, project, _plan_section_bodies(gateway, project_id))
    docx_bytes = render_plan_docx(data, template=template)
    filename = quote('사업계획서.docx')
    return Response(
        content=docx_bytes,
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get('/{project_id}/plan-document.pdf')
def download_plan_document_pdf(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """download_plan_document(.docx)가 만든 그 파일을 그대로 PDF로 변환해 내려준다
    (app/pdf_export.py). 화면 미리보기(plan-form 우측 PDF 뷰어)가 쓰는 엔드포인트라
    inline로 내보낸다 — attachment면 브라우저가 뷰어 대신 다운로드를 띄운다.
    양식을 다시 그리지 않으므로 미리보기와 내려받는 문서가 어긋날 수 없다."""
    from app.pdf_export import PdfConversionError, docx_to_pdf
    from app.plan_document_export import render_plan_docx

    project = _get_owned_project(db, project_id, current_user)
    data, template = _build_plan_document_data(db, project, _plan_section_bodies(gateway, project_id))
    try:
        pdf_bytes = docx_to_pdf(render_plan_docx(data, template=template))
    except PdfConversionError as exc:
        # 설정/환경 문제(LibreOffice 미설치 등)라 요청을 고쳐도 소용없다 — 503으로 구분해 둔다.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    filename = quote('사업계획서.pdf')
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f"inline; filename*=UTF-8''{filename}"},
    )


@router.get('/{project_id}/plan-document.hwp')
def download_plan_document_hwp(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """download_plan_document(.docx)와 같은 데이터로 실제 .hwp를 내려준다
    (app/hwp_export.py, rhwp CLI 기반). [2026-09-18] 예비창업패키지·초기창업패키지
    (일반형) 둘 다 실제 원본 양식 + 좌표 매핑까지 끝났다 — RHWP_BIN(.env.example
    참고)만 실제 rhwp 실행 파일 경로로 맞추면 이 서버에서도 바로 된다."""
    from app.hwp_export import render_plan_hwp

    project = _get_owned_project(db, project_id, current_user)
    data, template = _build_plan_document_data(db, project, _plan_section_bodies(gateway, project_id))
    try:
        hwp_bytes = render_plan_hwp(data, template=template)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = quote('사업계획서.hwp')
    return Response(
        content=hwp_bytes,
        media_type='application/haansofthwp',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post('', response_model=ProjectDetailOut, status_code=201)
async def create_project(
    payload: str = Form(..., description='ProjectCreateRequest 스키마와 동일한 필드를 담은 JSON 문자열'),
    files: list[UploadFile] = File(default_factory=list, description='첨부파일 (여러 개 가능, 없어도 됨)'),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    try:
        body = ProjectCreateRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc

    # [2026-09-27 신규, 2026-09-29 프론트 요청사항 4차 C-1 확장] 필수 동의(이용약관/
    # 개인정보/연령) 게이트 — 공식 기능정의서 v1.9 E-AUTH-CONSENT: "필수 항목에 동의해야
    # 계정과 작업 결과를 보관할 수 있습니다... 진입을 중단한다." 새 실행 시작이 곧
    # "진입"에 해당하므로 여기서 막는다. 로그인 자체(POST /auth/google)는 계정 생성을
    # 위해 막지 않는다 — 동의 화면은 로그인 이후 별도로 뜨고, PATCH /auth/consent가
    # 완료돼야 아래 세 값이 채워진다. age_confirmed_at 게이트 추가로, 이미 terms/
    # privacy만 동의했던 기존 계정도 다음 새 실행 시작 시 재동의를 거치게 된다.
    if (
        current_user.terms_agreed_at is None
        or current_user.privacy_agreed_at is None
        or current_user.age_confirmed_at is None
    ):
        raise CodedHTTPException(
            403, 'E-AUTH-CONSENT',
            '필수 항목(이용약관, 개인정보 수집·이용, 만 16세 이상 확인)에 동의해야 이용할 수 있습니다.',
        )

    # [2026-09-27 신규] 마이페이지 프로필 게이트 — 공식 기능정의서 v1.9 E-AUTH-PROFILE:
    # "필수 항목을 채운 프로필이 생기기 전에는 새 실행을 시작할 수 없다." 최초 로그인
    # 이거나(프로필 0개) 있던 프로필을 전부 지운 경우가 해당한다. has_profile 계산은
    # /auth/me·로그인 응답이 쓰는 것과 같은 함수(compute_has_profile)를 그대로 재사용한다
    # — 슬롯 하나라도 필수 입력을 전부 채웠는지를 본다.
    if not compute_has_profile(db, current_user.user_id):
        raise CodedHTTPException(
            403, 'E-AUTH-PROFILE', '서비스를 이용하려면 먼저 마이페이지에서 프로필을 만들어주세요.',
        )

    # [2026-09-29 신규, 프론트 요청사항 3차 B-5] 첨부파일 개수·용량 상한 — 아직 회사/프로젝트
    # 행을 하나도 안 만든 시점(이 아래부터 DB에 실제로 쓰기 시작한다)에 바로 막아서, 거절될
    # 때 이미 저장된 첨부나 만들어진 프로젝트 행이 남지 않게 한다. UploadFile.size는
    # Starlette가 multipart 파싱 중에 실제로 받은 바이트 수를 이미 채워둔 값이라(우리가
    # 직접 read()하기 전) 파일 내용을 안 읽고도 용량을 확인할 수 있다.
    real_files = [f for f in files if f.filename]
    if len(real_files) > ATTACH_MAX_FILES:
        raise HTTPException(status_code=400, detail=f'첨부파일은 최대 {ATTACH_MAX_FILES}개까지 올릴 수 있어요')
    for f in real_files:
        if (f.size or 0) > ATTACH_MAX_BYTES:
            raise HTTPException(status_code=413, detail=f'"{f.filename}" 파일이 {ATTACH_MAX_MB}MB를 초과했어요')

    # [SB-242] 계정당 동시 실행 1건 제한(기획서 4-7) — 저장하기 전에 오케스트레이터에 묻는다. 진행 중인 작업이
    # 있으면 새 프로젝트를 만들지 않고 409 blocked(이어하기 또는 중단 후 새로 시작 선택)로 답한다. "중단 후 새로
    # 시작"은 기존 DELETE /projects/{id}(abort_project 후 보관)가 맡는다. 최종 확인은 아래 request_start가 계정
    # 잠금 안에서 다시 한다(그 사이에 생긴 작업은 E-RUN-CONCURRENT).
    # [SB-298] 탈퇴 중인 계정은 새 프로젝트를 시작할 수 없다(명세 7.3: 탈퇴 처리 중에는 request_start를 부르지 않는다).
    if current_user.status == ACCOUNT_WITHDRAWING:
        raise CodedHTTPException(409, 'ACCOUNT_WITHDRAWING', WITHDRAWING_MESSAGE)
    account_id = account_id_of(current_user.user_id)
    active = gateway.active_work(account_id)
    if active is not None:
        raise CodedHTTPException(409, 'E-RUN-CONCURRENT', mapping.blocked_detail(active))

    company = _create_company_for_project(db, current_user, body)

    project = Project(
        company_id=company.company_id,
        description=body.description,
        # [2026-09-17 배선] 컬럼은 있었는데 요청 바디에서 받아서 저장하는 코드가 없었다.
        output_summary=body.output_summary,
        tech_field=body.tech_field,
        regional_priority_area=body.regional_priority_area,
    )
    db.add(project)
    db.flush()  # project_id 확보

    for m in body.team_members:
        db.add(TeamMember(project_id=project.project_id, name=m.name, role=m.role, experience=m.experience))
    for p in body.pricing_items:
        db.add(PricingItem(project_id=project.project_id, service_name=p.service_name, unit_price=p.unit_price))
    # [2026-09-22 배선] IntakeForm.jsx "사업 계획" 섹션 — project당 1행(ProjectPlanInput 참고).
    db.add(ProjectPlanInput(
        project_id=project.project_id,
        occupation=body.occupation,
        ceo_birth_date=body.ceo_birth_date,
        ceo_gender=body.ceo_gender,
        region_sido=body.region_sido,
        region_sigungu=body.region_sigungu,
        # [2026-09-28 개정] main_industry는 이제 ENUM(9종, 개인/법인 드롭다운 전용) —
        # 예비창업자는 프론트가 자유 텍스트를 보내므로(app/pipeline_stages.py
        # MAIN_INDUSTRIES 주석 참고) 그 값은 main_industry_free에 담는다.
        main_industry=body.main_industry if body.applicant_type != 'preliminary' else None,
        main_industry_free=body.main_industry if body.applicant_type == 'preliminary' else None,
        certifications=body.certifications,
        ceo_careers=[c.model_dump() for c in body.ceo_careers],
        ceo_capability=body.ceo_capability,
        dev_start_month=body.dev_start_month,
        dev_end_month=body.dev_end_month,
        budget_scale_manwon=body.budget_scale_manwon,
        self_funding_allowed=body.self_funding_allowed,
        self_cash_limit=body.self_cash_limit,
        self_in_kind_resources=body.self_in_kind_resources,
        no_hires=body.no_hires,
        hires=[h.model_dump() for h in body.hires],
        no_equipment=body.no_equipment,
        equipment=[e.model_dump() for e in body.equipment],
        no_partners=body.no_partners,
        partners=[p.model_dump() for p in body.partners],
    ))
    for f in real_files:  # 개수·용량 검증을 이미 통과한 목록(위 참고) — 빈 파일 필드는 여기 없음
        file_name, file_url = _save_attachment(f)
        db.add(ProjectAttachment(project_id=project.project_id, file_name=file_name, file_url=file_url))

    db.commit()
    db.refresh(project)

    # 저장한 입력을 오케스트레이터가 읽어 사전 단계(요구사항 해석 → 공고 매칭)를 시작한다. 시작 요청이 거절되면
    # 방금 만든 프로젝트는 쓸 곳이 없으니 지운다(입력을 고쳐 다시 제출하면 새 프로젝트로 만들어진다).
    # [SB-298] 저장하는 동안 탈퇴가 시작됐을 수 있다 — 시작 요청 직전에 다시 확인한다.
    if _is_withdrawing(current_user):
        _purge_unstarted_project(db, project.project_id)
        raise CodedHTTPException(409, 'ACCOUNT_WITHDRAWING', WITHDRAWING_MESSAGE)
    check = gateway.request_start(account_id, project.project_id)
    if not check.ok:
        _purge_unstarted_project(db, project.project_id)
        raise _start_failure(check)
    # 요청을 넣는 사이에 탈퇴가 시작됐으면 방금 넣은 요청을 거둔다(탈퇴가 끝난 뒤 남은 요청은 지워지지 않는다 — 명세 7.3)
    if _is_withdrawing(current_user):
        gateway.abort_project(project.project_id)
        _purge_unstarted_project(db, project.project_id)
        raise CodedHTTPException(409, 'ACCOUNT_WITHDRAWING', WITHDRAWING_MESSAGE)
    return ProjectDetailOut.model_validate(project)


def _start_failure(check) -> CodedHTTPException:
    """request_start가 거절한 이유(StartCheck)를 웹 응답으로 바꾼다. 오류 이름(code)은 오케스트레이터가 준 코드 그대로다."""
    if check.code == 'E-RUN-CONCURRENT' and check.active is not None:
        return CodedHTTPException(409, 'E-RUN-CONCURRENT', mapping.blocked_detail(check.active))
    if check.code == 'E-AUTH-PROFILE':
        return CodedHTTPException(403, 'E-AUTH-PROFILE', check.message)
    if check.code == 'E-C1-REQUIRED':
        return CodedHTTPException(
            422, 'E-C1-REQUIRED', {'message': check.message, 'code': check.code, 'missing': check.missing})
    return CodedHTTPException(400, check.code or 'BAD_REQUEST', {'message': check.message, 'code': check.code})


@router.get('/{project_id}', response_model=ProjectDetailOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_owned_project(db, project_id, current_user)
    return ProjectDetailOut.model_validate(project)


def _delete_project_rows(db: Session, project: Project) -> None:
    """프로젝트 한 건의 웹 행을 지운다(자식부터). ORM 관계에 delete cascade를 안 걸어뒀고 SQLite는 기본적으로 FK도 강제
    안 하므로 지우는 순서를 직접 지킨다. 실행 건의 결과 · 입력 사본은 오케스트레이터가 갖고 있어(delete_project_data) 여기엔 없다."""
    project_id = project.project_id
    # [SB-246] 검수 회수 문단: 학습 반영 전 행은 지우고 trained 행은 연결만 끊는다(프로젝트 행을 지우기 전에)
    clear_project_logs(db, [project_id])
    db.query(Notification).filter(Notification.project_id == project_id).delete(synchronize_session=False)
    db.query(GenerationFailureAlert).filter(GenerationFailureAlert.project_id == project_id).delete(synchronize_session=False)
    db.query(NoticeAlert).filter(NoticeAlert.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectAttachment).filter(ProjectAttachment.project_id == project_id).delete(synchronize_session=False)
    db.query(TeamMember).filter(TeamMember.project_id == project_id).delete(synchronize_session=False)
    db.query(PricingItem).filter(PricingItem.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectBudgetItem).filter(ProjectBudgetItem.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectScheduleItem).filter(ProjectScheduleItem.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectPartner).filter(ProjectPartner.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectPlanInput).filter(ProjectPlanInput.project_id == project_id).delete(synchronize_session=False)
    company_id = project.company_id
    db.query(Project).filter(Project.project_id == project_id).delete(synchronize_session=False)
    db.query(Company).filter(Company.company_id == company_id).delete(synchronize_session=False)


def _purge_unstarted_project(db: Session, project_id: int) -> None:
    """실행 건이 한 번도 만들어지지 않은 프로젝트를 실제로 지운다(휴지통 · 시작 실패 정리)."""
    project = db.get(Project, project_id)
    if project is not None:
        _delete_project_rows(db, project)
    db.commit()


@router.delete('/{project_id}', status_code=204)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """대시보드 "내 프로젝트"의 휴지통 버튼 — 사용자가 자기 프로젝트를 목록에서 지운다.

    [SB-242] 먼저 오케스트레이터에 중단을 알린다(진행 중인 실행 건 중단, 대기·처리 중인 시작 요청 취소) —
    빠뜨리면 주인 없는 실행 건이 남아 그 계정이 새 작업을 시작하지 못한다. 그다음 실행 건이 한 번이라도
    만들어졌으면(공고 매칭 이후) 실제로 지우지 않고 projects.archived_at/archived_by에 보관 처리만 한다 —
    이미 만든 계획서·산출물을 보존하고 관리자 대시보드(진행 현황 탭)가 계속 "보관중"으로 조회하게 한다.
    실행 건이 없는 프로젝트(매칭 전)는 남길 데이터가 없으니 입력 사본까지 지우고 실제로 지운다."""
    project = _get_owned_project(db, project_id, current_user)
    gateway.abort_project(project_id)
    if gateway.view_project(project_id).run is not None:
        project.archived_at = datetime.datetime.utcnow()
        project.archived_by = 'user'
        db.commit()
        return Response(status_code=204)

    gateway.delete_project_data(project_id)
    _purge_unstarted_project(db, project_id)
    return Response(status_code=204)


def _delete_project_cascade(db: Session, project: Project) -> None:
    """"건별 삭제"(완전 삭제) — 웹 행을 모두 지우고 식별자 없이 '삭제됐다'는 사실과 시각만 남긴다(프론트 요청 4).
    프로젝트 전용 Company 행(1:1)도 같이 지운다."""
    _delete_project_rows(db, project)
    db.add(PermanentDeletionLog())
    db.commit()


@router.delete('/{project_id}/permanent', status_code=204)
def delete_project_permanently(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """"건별 삭제"(완전 삭제) — 프로젝트 기획서 v1.10 6-7절. 보관(archive) 여부·진행 상태와 무관하게 바로 실제로
    지운다 — DELETE /projects/{id}(휴지통, 실행 건이 있으면 archive만 함)와는 독립된 별도 액션이다. 되돌릴 수
    없다 — 프론트는 호출 전 확인 다이얼로그를 거쳐야 한다.

    [SB-244] 먼저 오케스트레이터의 산출물 · 입력 사본을 지운다(`delete_project_data` — 진행 중이면 먼저 중단한다).
    워커가 단계를 도는 중이면 BUSY로 409("잠시 뒤 다시")를 돌려주고 웹 행은 지우지 않는다 — 재시도는 하지 않고
    사용자가 다시 누른다. 그 뒤 웹 행을 지운다(실행 건의 project_id는 비워지고 실행 로그는 남는다)."""
    project = _get_owned_project(db, project_id, current_user)
    gateway.delete_project_data(project_id)
    _delete_project_cascade(db, project)
    return Response(status_code=204)


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
    gateway: OrchGateway = Depends(require_gateway),
):
    """이어하기(기획서 v1.7 4-7절, p.20 8케이스) — 프론트가 이 프로젝트를 다시 열었을 때
    몇 번 화면으로 돌려보내야 하는지를 판별해서 내려준다.

    실제 Agent 파이프라인(다른 팀원이 작업 중인 오케스트레이터)이 각 단계를 시작/진행할
    때마다 projects.stage(+progress_percent)를 갱신해두면(app/pipeline_stages.py의
    STAGE_* 상수 사용), 이 엔드포인트는 그 값을 읽어 화면 번호로만 바꿔주는 얇은 조회다.
    판별 로직 자체는 tests/verify_resume_cases.py에서 기획서 8케이스 전부에 대해 검증됐다
    (detect_resume_screen()과 동일한 로직 — 거기서는 아직 실제 API가 없어 DB를 직접
    조회해 검증했지만, 여기서는 라우터로 옮기고 소유권 체크(_get_owned_project)만 추가했다).
    """
    _get_owned_project(db, project_id, current_user)
    return mapping.project_status_out(project_id, gateway.view_project(project_id))


@router.post('/{project_id}/retry-task', response_model=ReworkAcceptedOut)
def retry_task(
    project_id: int,
    body: RetryTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """재작성 요청 — 화면 6 · 8 · 9의 묶음 하나(문서층 4개 · 산출물층 2개)를 다시 만든다.

    [SB-244] 웹 (task_key, bundle_id)를 오케스트레이터 묶음 이름으로 바꿔 `request_rework_for_project`에 넘긴다 —
    묶음마다 한 번씩 부른다. 접수만 하고 바로 돌아오며(응답은 ReworkAcceptedOut), 실제 재작성은 워커가 하고
    같은 화면에서 모으는 시간 안의 요청은 한 번에 실행된다. 끝난 뒤 전후 비교는 GET /rework-result로 읽는다.
    사용자 재작성 대상이 아닌 task_key(전략 · 검증 · 검수)와 맞지 않는 bundle_id는 400.
    오류: 대기 지점이 아니거나 모으는 시간이 끝났거나 진행 중이면 409, 상한을 다 썼으면 409(E-G2-LIMIT),
    화면에 맞지 않는 층 · 원페이지의 실행 파일이면 422, 실행 건이 없으면 404."""
    _get_owned_project(db, project_id, current_user)
    try:
        orch_bundle = mapping.orch_bundle_of(body.task_key, body.bundle_id)
    except mapping.NotReworkable as exc:
        raise CodedHTTPException(400, 'NOT_REWORKABLE', str(exc)) from exc
    accepted = gateway.request_rework_for_project(project_id, orch_bundle)
    return mapping.rework_accepted_out(project_id, body.task_key, orch_bundle, accepted)


@router.get('/{project_id}/rework-result', response_model=ReworkResultOut)
def get_rework_result(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    gateway: OrchGateway = Depends(require_gateway),
):
    """마지막 재작성 한 건의 결과(진행중 · 완료 · 실패). 재작성한 적이 없으면 404, 실패 · 중단된 실행이면 409."""
    _get_owned_project(db, project_id, current_user)
    result = gateway.rework_result(project_id)
    if result is None:
        raise CodedHTTPException(404, 'NOT_REWORKED_YET', '재작성한 적이 없어요.')
    return mapping.rework_result_out(project_id, result)
