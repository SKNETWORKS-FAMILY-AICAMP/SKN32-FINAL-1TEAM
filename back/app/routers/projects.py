"""프로젝트 생성(DB 적재) + 조회.

설계 문서 기준으로 "프로젝트"는 companies(회사/예비창업자 프로필) 1건 아래
projects(지원 아이템) N건으로 정규화돼 있다.

[2026-09-15 개정] 예전엔 "회사 프로필은 계정당 1건"이라 가정하고 최초 생성 시 만든 뒤
이후 요청은 재사용했는데(신청자 유형/대표자명/설립일자가 새로 안 바뀜), 프로젝트마다
다른 신청자 정보로 지원하고 싶은 사용자에게 부작용이 있었다. 이제 companies.user_id는
더 이상 UNIQUE가 아니고, POST /projects는 매번 그 요청에 담긴 값으로 회사 프로필을
새로 만든다 — 계정당 여러 프로젝트가 각자 다른 회사 프로필을 가질 수 있다. 계정당 동시
실행 1건 제한(기획서 4-7, backend_decisions.md #11)은 회사 프로필이 아니라 User 행 자체를
잠그는 방식으로 분리했다(_lock_user_for_concurrency_check 참고) — 원래 그 제한을 위해
회사 프로필을 계정당 1건으로 묶었던 건데, 락 대상과 데이터 저장소가 같은 테이블이라 이런
부작용이 생겼던 것이었다.

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
import random
import sys
import threading
import time
import uuid
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import or_
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
    EligibilityCheck,
    FormatFinding,
    MatchCandidate,
    MatchResult,
    Notice,
    PlanCanonicalData,
    PlanScoreReason,
    PlanSection,
    PricingItem,
    Project,
    ProjectAttachment,
    ProjectPlanInput,
    ProofreadLog,
    TeamMember,
    User,
    Verdict,
    VerificationPolicy,
    VerificationScoreHistory,
)
from app.schemas import (
    AgentExecutionOut,
    BusinessPlanOut,
    DemoGenerateRequest,
    DemoGenerateResponse,
    EligibilityCheckOut,
    MatchCandidateOut,
    MatchCandidatesOut,
    MatchResultOut,
    ProjectCreateRequest,
    ProjectDetailOut,
    ProjectListItemOut,
    ProjectStatusOut,
    RetryTaskRequest,
    RetryTaskResponse,
    VerdictOut,
)
from app.security import get_current_user

# [2026-09-15, 프론트 통합 임시 구현] seed_dummy_pipeline.py(repo 루트, back/)를 그대로
# 불러다 쓴다 — 오케스트레이터가 아직 없어서(app/agents.py 모듈 docstring 참고)
# "매칭→자격판정→계획서→산출물→최종판정"을 실제로 만들어주는 API가 하나도 없었는데,
# 이미 이 더미 함수가 정확히 그 모양을 만들어주고 있어서 새로 짜지 않고 재사용한다.
# database.py의 _REPO_ROOT 계산 방식과 동일하게 __file__ 기준으로 repo 루트를 잡는다.
# 주의: seed_dummy_pipeline.py 쪽에서 다시 `from app.routers.projects import UPLOAD_DIR`로
# 이 모듈을 가져오기 때문에, 여기서 모듈 최상단에 바로 import하면 순환 import로 죽는다 —
# 그래서 generate_pipeline_result() 안에서 실제 호출 시점에만 지연 import한다(이땐 이
# 모듈이 이미 다 로드된 뒤라 UPLOAD_DIR도 이미 정의돼 있어 안전하다).
_REPO_ROOT_FOR_SEED = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT_FOR_SEED not in sys.path:
    sys.path.insert(0, _REPO_ROOT_FOR_SEED)

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


def _get_verification_policy(db: Session) -> VerificationPolicy:
    """verification_policies는 운영 중 1행만 유지하는 설계다(app_schema.sql 주석) —
    seed_dummy_pipeline.py가 이미 이 행을 보장해두므로, retry_task 시점엔 항상 있어야
    정상이다. 없으면(예: seed 없이 직접 만든 plan) 500으로 명확히 알린다."""
    policy = db.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    if policy is None:
        raise HTTPException(status_code=500, detail='verification_policies 초기 행이 없습니다.')
    return policy


def _rescore_verify1(db: Session, plan: BusinessPlan, verify1_task_key: str) -> dict | None:
    """검증-1(문서층) 재채점 — verify1_rubric/verify1_evidence 두 task_key가 공유하는 로직을
    뽑아냈다. plan_score_reasons가 아직 없으면(초기 파이프라인이 한 번도 안 돌았거나 등)
    None을 돌려준다 — 이 함수를 직접 호출하는 재시도 요청(verify1_rubric/verify1_evidence
    task_key)은 호출부에서 그 경우 404로 막고, '작성' 재시도에 딸려오는 자동 재검증
    (2026-09-18 추가, "재작성하면 점수도 바뀌어야 하지 않냐"는 지적)에서는 그냥 건너뛴다
    (작성 자체는 이미 성공했으니 그 응답까지 실패시킬 이유가 없음)."""
    reasons = db.query(PlanScoreReason).filter(PlanScoreReason.plan_id == plan.plan_id).all()
    if not reasons:
        return None
    reasons_by_code = {r.item_code: r for r in reasons if r.item_code is not None}
    rubric_input = [(r.item_code, r.max_score or Decimal('10')) for r in reasons if r.item_code is not None]

    if verify1_task_key == 'verify1_rubric':
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

    # [2026-09-18 수정] 재채점 시에도 verification_score_history에 새 행을 남긴다 — 예전엔
    # plan.doc_score만 갱신하고 이력을 안 남겨서, 관리자 대시보드 "운영 현황"의 채점 편차
    # (1회→2회)가 재시도가 있어도 항상 0건으로 보이는 버그가 있었다.
    policy = _get_verification_policy(db)
    db.add(VerificationScoreHistory(
        plan_id=plan.plan_id, layer='doc', score=plan.doc_score, is_rerun=True,
        policy_id=policy.policy_id, applied_weight=policy.doc_weight,
        applied_pass_threshold=policy.pass_threshold, applied_rerun_cap=policy.rerun_cap,
    ))
    return {'scores': item_changes, 'doc_score': {'before': _num(before_score), 'after': _num(plan.doc_score)}}


def _rescore_verify2(db: Session, plan: BusinessPlan, artifact: Artifact, verify2_task_key: str) -> dict | None:
    """검증-2(산출물층) 재채점 — verify2_static/verify2_crosscheck 공유 로직. 채점 근거가
    없으면(구현 재시도에 딸려오는 자동 재검증에서) None."""
    prefixes = _VERIFY2_STATIC_PREFIXES if verify2_task_key == 'verify2_static' else _VERIFY2_CROSSCHECK_PREFIXES
    all_reasons = db.query(ArtifactScoreReason).filter(ArtifactScoreReason.artifact_id == artifact.artifact_id).all()
    reasons = [r for r in all_reasons if r.item_code and r.item_code.startswith(prefixes)]
    if not reasons:
        return None
    reasons_by_code = {r.item_code: r for r in reasons}
    rubric_input = [(r.item_code, r.max_score or Decimal('10')) for r in reasons]
    results = agents.run_verify2_retry(
        rubric_input, check_kind='static' if verify2_task_key == 'verify2_static' else 'crosscheck',
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

    # [2026-09-18 수정] verify1_* 재채점과 같은 이유 — 산출물층(code)도 재채점 이력을 남긴다.
    policy = _get_verification_policy(db)
    db.add(VerificationScoreHistory(
        plan_id=plan.plan_id, layer='code', score=artifact.artifact_score, is_rerun=True,
        policy_id=policy.policy_id, applied_weight=policy.code_weight,
        applied_pass_threshold=policy.pass_threshold, applied_rerun_cap=policy.rerun_cap,
    ))
    return {'scores': item_changes, 'artifact_score': {'before': _num(before_score), 'after': _num(artifact.artifact_score)}}


def _upsert_plan_section(db: Session, plan_id: int, draft) -> dict:
    """plan_sections에 (plan_id, tag)로 찾아서 있으면 갱신, 없으면 새로 만든다 — 작성
    Agent 재시도 로직. draft는 app.agents.SectionDraftResult."""
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


def _upsert_canonical_data(db: Session, plan_id: int, result) -> dict:
    """plan_canonical_data에 (plan_id, data_key)로 찾아서 있으면 갱신, 없으면 새로 만든다 —
    _upsert_plan_section과 같은 패턴, 전략 Agent(F01~F15) 재시도 전용. result는
    app.agents.CanonicalDataResult."""
    row = (
        db.query(PlanCanonicalData)
        .filter(PlanCanonicalData.plan_id == plan_id, PlanCanonicalData.data_key == result.data_key)
        .first()
    )
    before = row.data_json if row is not None else None
    if row is None:
        row = PlanCanonicalData(
            plan_id=plan_id, data_key=result.data_key,
            data_json=result.data_json, source_function=result.source_function,
        )
        db.add(row)
    else:
        row.data_json = result.data_json
        row.source_function = result.source_function
    return {'before': before, 'after': result.data_json}

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
    /uploads 경로는 로그인 및 프로젝트 소유권 검사 후 파일을 제공한다."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or '')[1]
    stored_name = f'{uuid.uuid4().hex}{ext}'
    dest_path = os.path.join(UPLOAD_DIR, stored_name)
    with open(dest_path, 'wb') as out:
        out.write(file.file.read())
    file_url = f'/uploads/{stored_name}'
    return file.filename or stored_name, file_url


def _lock_user_for_concurrency_check(db: Session, current_user: User) -> None:
    """계정당 동시 실행 1건 제한(기획서 4-7, backend_decisions.md #11)을 위한 락 지점.

    User 행은 계정마다 정확히 1개, 항상 이미 존재한다(로그인 시점에 만들어짐) — 그래서
    회사 프로필처럼 "없으면 만드는" 동작이 필요 없고, 그냥 잠그기만 하면 된다. 이 락을
    create_project()에서 회사/프로젝트를 만들기 전에 가장 먼저 걸어서, 같은 유저가 거의
    동시에 두 번 요청을 보내도 두 번째 요청은 첫 번째 트랜잭션이 끝날 때까지 대기했다가
    최신 상태(진행 중 매칭 여부)로 다시 판정하게 한다 — 그렇지 않으면 두 요청이 동시에
    "진행 중 매칭 없음"을 읽어 둘 다 통과해버리는 race가 이론상 가능하다.

    SQLite는 FOR UPDATE 구문 자체가 없어 이 호출이 조용히 무시되지만, SQLite는 쓰기
    트랜잭션을 파일 단위로 직렬화하므로 로컬 개발 환경에서는 어차피 문제되지 않는다 —
    운영(MySQL)에서만 실제로 잠금이 걸린다.

    [2026-09-15 개정] 원래는 companies.user_id UNIQUE 제약 덕분에 항상 존재가 보장되는
    회사 프로필 행을 락 대상으로 재사용했었다 — 그런데 그러면서 "동시성 제어용 락 앵커"와
    "신청자 정보 저장소"가 같은 테이블이 돼버려, 프로젝트마다 다른 신청자 정보를 쓰고
    싶어도 두 번째 프로젝트부터 값이 무시되는 부작용이 생겼다. User 행은 애초에 계정과
    1:1이라 회사 프로필처럼 "계정당 1건" 가정을 새로 만들 필요도 없고, 회사 프로필 데이터
    모델도 프로젝트마다 자유롭게 둘 수 있어 더 깔끔하다."""
    db.query(User).filter(User.user_id == current_user.user_id).with_for_update().first()


def _create_company_for_project(db: Session, current_user: User, body: ProjectCreateRequest) -> Company:
    """이 프로젝트용 회사 프로필을 새로 만든다. 계정당 여러 프로젝트가 각자 다른 신청자
    유형/대표자명/설립일자를 가질 수 있도록, 재사용하지 않고 매번 새로 만든다 — 동시
    실행 제한은 이 함수가 아니라 _lock_user_for_concurrency_check()가 담당하므로, 여기선
    더 이상 동시 요청을 막기 위한 락이나 insert-then-catch가 필요 없다."""
    company = Company(
        user_id=current_user.user_id,
        # [2026-09-17 배선] IntakeForm.jsx가 필수로 물어보는 신청자 유형이 여기까지 안 실려서
        # 화면에서 고른 값이 버려지고 있었다 — 이제 받아서 저장한다(하정원님 지적으로 발견).
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
):
    """대시보드 "내 프로젝트" 목록. [2026-09-15 개정] 계정당 회사 프로필이 이제 여러 건일
    수 있으므로(프로젝트마다 따로 만듦), Company를 거치지 않고 Project를 Company와 join해
    Company.user_id로 직접 필터링한다 — 프로젝트를 한 번도 안 만든 신규 유저는 join 결과가
    그냥 빈 목록이라 별도 분기가 필요 없다. 프로젝트마다 가장 최근 매칭(있으면) 요약을
    같이 내려서, 목록 화면에서 진행 상태를 바로 보여줄 수 있게 한다 — GET /projects/{id}/status와
    같은 stage->screen 매핑을 쓴다."""
    projects = (
        db.query(Project)
        .join(Company, Company.company_id == Project.company_id)
        .filter(Company.user_id == current_user.user_id)
        .order_by(Project.created_at.desc())
        .all()
    )
    items = []
    for project in projects:
        match = (
            db.query(MatchResult)
            .filter(MatchResult.project_id == project.project_id)
            .order_by(MatchResult.match_id.desc())
            .first()
        )
        if match is not None and match.archived_at is not None:
            continue  # 사용자가 지운(보관 처리한) 프로젝트는 본인 목록에서 숨긴다 — DELETE /projects/{id} 참고.
        notice_title = None
        screen = ps.NO_MATCH_SCREEN
        if match is not None:
            notice = db.query(Notice).filter(Notice.notice_id == match.notice_id).one_or_none()
            notice_title = notice.title if notice is not None else None
            screen = ps.STAGE_TO_SCREEN.get(match.stage) if match.stage is not None else None
        items.append(ProjectListItemOut(
            project_id=project.project_id,
            description=project.description,
            created_at=project.created_at,
            notice_id=match.notice_id if match is not None else None,
            notice_title=notice_title,
            match_status=match.status if match is not None else None,
            failure_reason=match.failure_reason if match is not None and match.status == 'failed' else None,
            stage=match.stage if match is not None else None,
            progress_percent=match.progress_percent if match is not None else None,
            screen=screen,
        ))
    return items


MATCH_CANDIDATES_PER_BATCH = 10


def _add_candidate_batch(db: Session, project_id: int, batch: int, exclude_notice_ids: list[str]) -> int:
    """[임시 구현] 실제 임베딩 유사도 매칭(notices.embedding_status 반영 이후 예정)이 아직 없어서,
    모집중(open) 공고 중 아직 안 보여준 것을 골라 무작위 적합도를 붙여 저장한다."""
    def pick(open_only: bool):
        q = db.query(Notice)
        if open_only:
            q = q.filter(Notice.recruitment_status == 'open')
        if exclude_notice_ids:
            q = q.filter(Notice.notice_id.notin_(exclude_notice_ids))
        return q.order_by(Notice.id.asc()).limit(MATCH_CANDIDATES_PER_BATCH).all()

    # 모집중 공고가 모자라면(로컬 개발 DB가 비어있는 등) 마감된 공고라도 채운다 —
    # 화면이 빈 채로 막히는 것보다는 흐름을 테스트해볼 수 있는 쪽이 낫다.
    notices = pick(open_only=True) or pick(open_only=False)
    for notice in notices:
        db.add(MatchCandidate(
            project_id=project_id,
            notice_id=notice.notice_id,
            batch=batch,
            # [임시] 실제 가산점 산정 전까지 1~5점 랜덤
            bonus_score=Decimal(random.randint(1, 5)),
            reason=f'"{notice.title[:30]}" — 아이템 설명과 키워드가 겹치는 것으로 보입니다.',
        ))
    db.commit()
    return len(notices)


def _candidates_response(db: Session, project_id: int) -> MatchCandidatesOut:
    rows = db.query(MatchCandidate).filter(MatchCandidate.project_id == project_id).all()
    notices = {
        n.notice_id: n
        for n in db.query(Notice).filter(Notice.notice_id.in_([r.notice_id for r in rows])).all()
    } if rows else {}
    candidates = []
    for r in rows:
        notice = notices.get(r.notice_id)
        if notice is None:
            continue
        candidates.append(MatchCandidateOut(
            notice_id=notice.notice_id,
            title=notice.title,
            org=notice.organizer or notice.supervising_org or notice.executing_org,
            apply_end=notice.apply_end,
            bonus_score=float(r.bonus_score),
            reason=r.reason,
            url=notice.url,
            batch=r.batch,
        ))
    # 재실행 후보(batch 2)가 위로, 각 묶음 안에서는 가산점 높은 순
    candidates.sort(key=lambda c: (-c.batch, -c.bonus_score))
    return MatchCandidatesOut(candidates=candidates, rematch_used=any(r.batch == 2 for r in rows))


@router.get('/{project_id}/match-candidates', response_model=MatchCandidatesOut)
def get_match_candidates(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """처음 부르면 후보 10건을 뽑아 저장하고, 그 뒤로는 저장된 후보를 그대로 돌려준다 —
    새로고침할 때마다 새 후보가 나오면 재실행 1회 제한이 무의미해진다.
    사용자가 이 중 하나를 고르면 POST /projects/{id}/generate 로 match_results 행이 생긴다."""
    _get_owned_project(db, project_id, current_user)
    exists = db.query(MatchCandidate.candidate_id).filter(MatchCandidate.project_id == project_id).first()
    if exists is None:
        _add_candidate_batch(db, project_id, batch=1, exclude_notice_ids=[])
    return _candidates_response(db, project_id)


@router.post('/{project_id}/match-candidates/rematch', response_model=MatchCandidatesOut)
def rematch_candidates(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """공고 매칭 재실행 — 프로젝트당 1회. 앞서 보여준 후보는 지우지 않고 새 후보 10건을 더한다."""
    _get_owned_project(db, project_id, current_user)
    shown = db.query(MatchCandidate).filter(MatchCandidate.project_id == project_id).all()
    if not shown:
        raise HTTPException(status_code=400, detail='먼저 공고 매칭 결과를 불러와 주세요.')
    if any(r.batch == 2 for r in shown):
        raise HTTPException(status_code=409, detail='공고 다시 찾기는 한 번만 할 수 있어요.')
    added = _add_candidate_batch(db, project_id, batch=2, exclude_notice_ids=[r.notice_id for r in shown])
    if added == 0:
        raise HTTPException(status_code=404, detail='지금은 더 보여드릴 공고가 없어요.')
    return _candidates_response(db, project_id)


def _build_demo_response(db: Session, project_id: int, match: MatchResult) -> DemoGenerateResponse:
    """match_id 하나로 DemoGenerateResponse를 조립한다 — POST /generate(방금 막 만든 match)와
    GET /result(예전에 만들어둔 match를 다시 조회) 둘 다 이 함수를 공유한다."""
    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.match_id == match.match_id)
        .order_by(BusinessPlan.plan_id.desc())
        .first()
    )
    # [2026-09-22 수정, 프론트 전달사항 3번] 예전엔 verdict(=artifact)까지 없으면 통째로
    # 404였다 — 계획서만 먼저 끝나고 프로토타입/검증은 아직인 상태(실제 단계별 생성
    # 흐름에선 흔한 중간 상태)에서도 "완성된 계획서"는 돌려줘야 한다는 요구사항과
    # 어긋났다. 이제 plan이 있으면(=계획서 작성이 끝났으면) 200을 내려주고, artifact/
    # verdict가 아직 없으면 verdict만 None으로 비워서 응답한다.
    artifact = None
    verdict = None
    if plan is not None:
        artifact = (
            db.query(Artifact).filter(Artifact.plan_id == plan.plan_id).order_by(Artifact.artifact_id.desc()).first()
        )
        if artifact is not None:
            verdict = (
                db.query(Verdict)
                .filter(Verdict.artifact_id == artifact.artifact_id)
                .order_by(Verdict.verdict_id.desc())
                .first()
            )
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail='이 프로젝트엔 아직 계획서가 없습니다 — POST /projects/{id}/generate 또는 .../plan/start 로 먼저 만들어야 합니다',
        )

    eligibility = (
        db.query(EligibilityCheck)
        .filter(EligibilityCheck.match_id == match.match_id)
        .order_by(EligibilityCheck.check_id.desc())
        .first()
    )
    executions = (
        db.query(AgentExecution)
        .filter(AgentExecution.match_id == match.match_id)
        .order_by(AgentExecution.execution_id.asc())
        .all()
    )

    verdict_out = None
    if verdict is not None:
        # [2026-09-22, 프론트 전달사항 10번] 검증결과서 "종합 판정" 행 — 문서층/자동검증/
        # 계획서대조 세 층 점수를 verification_policies 가중치 기준으로 합산한다. 자동검증/
        # 계획서대조는 artifact_score_reasons 하나에 섞여 있어서 item_code 접두어(_VERIFY2_
        # STATIC_PREFIXES='CHECK-'/_VERIFY2_CROSSCHECK_PREFIXES='FEATURE-')로 갈라 합산한다 —
        # _rescore_verify2가 재채점할 때 쓰는 것과 같은 구분.
        policy = _get_verification_policy(db)
        code_score = sum(
            (r.score or Decimal('0')) for r in artifact.score_reasons
            if r.item_code and r.item_code.startswith(_VERIFY2_STATIC_PREFIXES)
        )
        plan_match_score = sum(
            (r.score or Decimal('0')) for r in artifact.score_reasons
            if r.item_code and r.item_code.startswith(_VERIFY2_CROSSCHECK_PREFIXES)
        )
        doc_score = plan.doc_score or Decimal('0')
        verdict_out = VerdictOut(
            overall_passed=verdict.overall_passed,
            model_version=verdict.model_version,
            first_pass_passed=verdict.first_pass_passed,
            doc_score=_num(doc_score),
            doc_max_score=_num(policy.doc_weight),
            code_score=_num(code_score),
            code_max_score=_num(policy.code_weight),
            plan_match_score=_num(plan_match_score),
            plan_match_max_score=_num(policy.plan_weight),
            total_score=_num(doc_score + code_score + plan_match_score),
            pass_threshold=_num(policy.pass_threshold),
        )

    return DemoGenerateResponse(
        project_id=project_id,
        match=MatchResultOut.model_validate(match),
        eligibility=EligibilityCheckOut.model_validate(eligibility),
        plan=BusinessPlanOut.model_validate(plan),
        verdict=verdict_out,
        agent_executions=[AgentExecutionOut.model_validate(e) for e in executions],
    )


@router.post('/{project_id}/generate', response_model=DemoGenerateResponse)
def generate_pipeline_result(
    project_id: int,
    body: DemoGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """[2026-09-15, 프론트 통합 임시 구현] 사용자가 매칭 후보 중 하나를 고른 뒤 호출 —
    seed_dummy_pipeline.py의 더미 로직으로 매칭+자격판정+계획서+산출물+최종판정을 한 번에
    만들어서 DB에 저장하고, 화면(매칭결과~검수)이 그대로 쓸 수 있는 모양으로 돌려준다.

    주의(임시 구현의 한계, 나중에 실제 오케스트레이터로 교체 시 참고): seed_dummy_pipeline은
    "이미 판정까지 끝난 프로젝트"를 한 번에 만드는 스크립트라 stage를 곧장 STAGE_DONE으로
    채운다 — 그래서 이 호출이 끝난 뒤 사용자가 새로고침하면 GET /projects/{id}/status는
    항상 "11.결과물 내려받기" 화면으로 돌려보낸다(중간 화면 5~10에서 이어하기는 못 함).
    지금은 프론트가 이 응답 하나를 화면 상태로 들고 있다가 순서대로 넘기는 방식으로 우회한다.
    호출할 때마다 새 매칭/계획서/산출물/판정 세트가 하나 더 쌓인다(seed_dummy_pipeline.py
    자체 동작) — 이미 만든 프로젝트를 다시 보기만 하려면 이 엔드포인트 대신
    GET /projects/{id}/result 를 쓴다."""
    _get_owned_project(db, project_id, current_user)
    import seed_dummy_pipeline as _seed_pipeline  # 지연 import — 위 주석 참고(순환 import 회피)

    try:
        verdict = _seed_pipeline.seed_dummy_pipeline(db, project_id, notice_id=body.notice_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(verdict)

    plan = db.get(BusinessPlan, verdict.plan_id)
    match = db.get(MatchResult, plan.match_id)
    # 공고 선택·자격 확인까지만 끝난 상태 — 계획서/프로토타입 생성은 사용자가 각각
    # POST .../plan/start, .../prototype/start 로 시작한다(stage NULL = 계획서 시작 전).
    match.stage = None
    match.progress_percent = None
    db.commit()
    return _build_demo_response(db, project_id, match)


# ---------------------------------------------------------------------------
# [더미 콘텐츠 + 실제 비동기 인프라, 2026-09-22] 계획서·프로토타입을 실제로 만드는 로직
# (_simulate_generation 본문)은 여전히 sleep+progress_percent 증가 흉내다 — 실제 에이전트
# 파이프라인은 별도 작업(프론트 전달사항 1번 "실제 에이전트 파이프라인으로 교체")이고, 오늘
# 바꾼 건 그걸 "어떻게 돌리는가"다.
#
# 예전엔 threading.Thread(daemon=True) + 프로세스 메모리 안의 _running_generations 셋으로
# 중복 실행만 막았는데, 그러면 (a) 서버가 재시작되면 스레드가 통째로 사라지고 진행률이
# 영영 멈추고, (b) uvicorn을 여러 워커 프로세스로 띄우면 워커마다 셋이 따로 있어서 같은
# match_id가 워커 수만큼 중복 실행될 수 있었다. Redis 등 별도 브로커를 새로 두지 않기로
# 했으므로(팀 인프라에 아직 없음), match_results에 클레임 시각 컬럼 하나(worker_claimed_at)
# 를 추가해서 "지금 어떤 프로세스가 이 stage를 처리 중인지"를 DB 자체로 표현한다:
#   - _try_claim_and_run: UPDATE ... WHERE stage=X AND (클레임 없음 또는 오래됨) 을
#     한 번의 원자적 SQL 문으로 실행해 rowcount로 성공 여부를 판정한다 — 여러 프로세스가
#     동시에 같은 match_id를 클레임하려 해도 DB 행 잠금 덕에 단 하나만 성공한다.
#   - _simulate_generation은 매 스텝 커밋마다 worker_claimed_at도 같이 갱신한다(하트비트) —
#     정상 진행 중인 작업은 클레임이 계속 "최근"으로 유지되어 다른 프로세스가 가로채지 않는다.
#   - _generation_recovery_loop: 앱 시작 시(그리고 주기적으로) "진행 중 stage인데 클레임이
#     없거나 오래된" match_results 행을 찾아 다시 클레임·실행한다 — 서버가 재시작돼 스레드가
#     죽었거나, 워커 프로세스 자체가 죽은 경우를 이 루프가 이어받는다.
# ---------------------------------------------------------------------------
DUMMY_GENERATION_STEPS = 10
DUMMY_GENERATION_STEP_SECONDS = float(os.getenv('DUMMY_GENERATION_STEP_SECONDS', '1.5'))
# 클레임이 이만큼 갱신 안 되면 "처리하던 워커가 죽었다"고 보고 다른 워커가 가로챈다.
# 스텝 간격(기본 1.5초)보다 충분히 커야 정상 진행 중인 작업을 실수로 가로채지 않는다.
GENERATION_CLAIM_STALE_SECONDS = float(os.getenv('GENERATION_CLAIM_STALE_SECONDS', '30'))
# 복구 루프가 "고아" 작업(클레임 없음/오래됨)을 찾는 주기.
GENERATION_POLL_INTERVAL_SECONDS = float(os.getenv('GENERATION_POLL_INTERVAL_SECONDS', '10'))

# running_stage -> done_stage. 복구 루프가 어떤 stage들을 감시해야 하는지 여기 한 곳에 모은다
# — _start_generation이 쓰는 (running_stage, done_stage) 쌍과 항상 같은 값이어야 한다.
_RUNNING_GENERATION_STAGES = {
    ps.STAGE_PLAN_WRITING: ps.STAGE_PLAN_REVIEW_PENDING,
    ps.STAGE_PROTOTYPE_BUILDING: ps.STAGE_DONE,
}


def _simulate_generation(match_id: int, running_stage: str, done_stage: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        try:
            match = db.get(MatchResult, match_id)
            step = (match.progress_percent or 0) * DUMMY_GENERATION_STEPS // 100 if match else DUMMY_GENERATION_STEPS
            while step < DUMMY_GENERATION_STEPS:
                time.sleep(DUMMY_GENERATION_STEP_SECONDS)
                db.expire_all()
                match = db.get(MatchResult, match_id)
                if match is None or match.stage != running_stage:
                    return
                step += 1
                if step >= DUMMY_GENERATION_STEPS:
                    match.stage = done_stage
                    match.progress_percent = 100
                    if done_stage == ps.STAGE_DONE:
                        match.status = 'completed'
                        match.failure_reason = None
                else:
                    match.progress_percent = step * 100 // DUMMY_GENERATION_STEPS
                match.worker_claimed_at = datetime.datetime.utcnow()  # 하트비트 — 진행 중엔 클레임이 안 늙는다
                db.commit()
        except Exception as exc:
            # [2026-09-22 신규, 프론트 전달사항 4번] 지금 더미 로직(sleep+progress 증가)은
            # 실패할 일이 없지만, 실제 에이전트가 붙으면 여기서 예외가 날 수 있다 — 그때
            # 스레드가 조용히 죽어버리면 클레임만 남아 복구 루프가 영원히 못 잡아내는(stage는
            # running_stage인데 아무도 안 돌리는) 상태가 된다. status='failed'로 명시적으로
            # 남기고, stage는 실패한 단계 그대로 둔다 — 복구 루프는 status='failed'를 건드리지
            # 않으므로(_recover_orphaned_generations_once) 자동 재시도되지 않고, 사용자가
            # "다시 시도"(plan/start·prototype/start 재호출)해야 재개된다.
            db.rollback()
            match = db.get(MatchResult, match_id)
            if match is not None and match.stage == running_stage:
                match.status = 'failed'
                match.failure_reason = str(exc)[:2000]
                db.commit()
    finally:
        db.close()


def _try_claim_and_run(match_id: int, running_stage: str, done_stage: str) -> bool:
    """match_id의 running_stage 작업을 원자적으로 클레임하고, 성공한 경우에만 실행 스레드를
    띄운다. 실패(이미 다른 곳에서 처리 중)하면 아무 것도 안 하고 False를 돌려준다 — 즉시시작
    경로(_start_generation)와 복구 루프(_generation_recovery_loop)가 공유한다."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        stale_before = datetime.datetime.utcnow() - datetime.timedelta(seconds=GENERATION_CLAIM_STALE_SECONDS)
        claimed = (
            db.query(MatchResult)
            .filter(
                MatchResult.match_id == match_id,
                MatchResult.stage == running_stage,
                or_(MatchResult.worker_claimed_at.is_(None), MatchResult.worker_claimed_at < stale_before),
            )
            .update({MatchResult.worker_claimed_at: datetime.datetime.utcnow()}, synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()
    if claimed == 1:
        threading.Thread(target=_simulate_generation, args=(match_id, running_stage, done_stage), daemon=True).start()
        return True
    return False


def _recover_orphaned_generations_once(db: Session) -> None:
    """진행 중 stage인데 클레임이 없거나 오래된(GENERATION_CLAIM_STALE_SECONDS) match_results
    행을 한 번 훑어 이어받는다 — _generation_recovery_loop이 매 tick 호출하고, 테스트도
    무한루프 대신 이 함수 하나만 직접 불러 검증한다."""
    stale_before = datetime.datetime.utcnow() - datetime.timedelta(seconds=GENERATION_CLAIM_STALE_SECONDS)
    for running_stage, done_stage in _RUNNING_GENERATION_STAGES.items():
        orphans = (
            db.query(MatchResult.match_id)
            .filter(
                MatchResult.stage == running_stage,
                # [2026-09-22 신규] 이미 실패로 확정된 작업은 자동으로 다시 돌리지 않는다 —
                # 사용자가 "다시 시도"를 눌러야(_start_generation) 재개된다.
                MatchResult.status != 'failed',
                or_(MatchResult.worker_claimed_at.is_(None), MatchResult.worker_claimed_at < stale_before),
            )
            .all()
        )
        for (orphan_match_id,) in orphans:
            _try_claim_and_run(orphan_match_id, running_stage, done_stage)


def _generation_recovery_loop() -> None:
    """앱이 살아있는 동안 계속 도는 백그라운드 루프 — 재시작 직후 멈춰있던 작업이나, 스레드가
    예외로 죽어 클레임이 오래된 작업을 찾아 이어받는다. 이 루프 자체는 무슨 일이 있어도
    죽으면 안 되므로 매 tick을 통째로 try/except로 감싼다."""
    from app.database import SessionLocal

    while True:
        try:
            db = SessionLocal()
            try:
                _recover_orphaned_generations_once(db)
            finally:
                db.close()
        except Exception:
            pass  # 이번 tick만 건너뛰고 다음 tick에 다시 시도 — 루프 자체는 계속 산다
        time.sleep(GENERATION_POLL_INTERVAL_SECONDS)


def start_generation_recovery_loop() -> None:
    """app/main.py가 앱 시작 시 한 번 호출한다(백그라운드 데몬 스레드로 루프를 띄움)."""
    threading.Thread(target=_generation_recovery_loop, daemon=True).start()


def _start_generation(db: Session, project: Project, start_from: tuple, running_stage: str, done_stage: str) -> ProjectStatusOut:
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project.project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    if match is None:
        raise HTTPException(status_code=400, detail='먼저 공고를 선택해 주세요.')
    # [2026-09-22 신규, 프론트 전달사항 4번] "다시 시도" — 실패는 stage를 실패한 단계 그대로
    # 두므로(_simulate_generation), 실패한 바로 그 단계에 대해서만(stage == running_stage)
    # 재시작을 허용한다 — 다른 단계에서 실패했는데 엉뚱한 단계가 리셋되면 안 되니까.
    can_retry_failed = match.status == 'failed' and match.stage == running_stage
    if match.stage in start_from or can_retry_failed:
        match.stage = running_stage
        match.progress_percent = 0
        match.worker_claimed_at = None  # 새 단계 시작 — 이전 단계의 클레임 흔적을 지운다
        match.status = 'in_progress'
        match.failure_reason = None
        db.commit()
    # 이미 진행 중이면(다른 요청/복구 루프가 먼저 클레임했으면) 새로 시작하지 않는다 —
    # _try_claim_and_run의 원자적 UPDATE가 중복 실행 방지를 대신한다.
    if match.stage == running_stage and match.status != 'failed':
        _try_claim_and_run(match.match_id, running_stage, done_stage)
    return ProjectStatusOut(
        project_id=project.project_id,
        screen=ps.STAGE_TO_SCREEN.get(match.stage) if match.stage is not None else None,
        stage=match.stage,
        progress_percent=match.progress_percent,
        match_id=match.match_id,
        match_status=match.status,
        failure_reason=match.failure_reason,
    )


@router.post('/{project_id}/plan/start', response_model=ProjectStatusOut)
def start_plan_generation(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """사업계획서 생성 시작. 바로 응답하고 생성은 백그라운드에서 돈다 — 진행 상황은
    GET /projects/{id}/status 의 stage='plan_writing' + progress_percent 로 확인한다.
    끝나면 stage='plan_review_pending'. 여러 번 불러도 한 번만 시작한다."""
    project = _get_owned_project(db, project_id, current_user)
    return _start_generation(db, project, (None,), ps.STAGE_PLAN_WRITING, ps.STAGE_PLAN_REVIEW_PENDING)


@router.post('/{project_id}/prototype/start', response_model=ProjectStatusOut)
def start_prototype_generation(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """프로토타입 생성 시작(계획서 완료 후). stage='prototype_building' + progress_percent 로
    진행되고, 끝나면 [더미] 이후 화면(산출물 확인~검수)이 아직 서버 단계를 안 쓰므로 곧장 'done'."""
    project = _get_owned_project(db, project_id, current_user)
    return _start_generation(db, project, (ps.STAGE_PLAN_REVIEW_PENDING,), ps.STAGE_PROTOTYPE_BUILDING, ps.STAGE_DONE)


@router.get('/{project_id}/result', response_model=DemoGenerateResponse)
def get_pipeline_result(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """[2026-09-15, 프론트 통합 임시 구현] POST /generate로 이미 만들어둔 결과를 다시
    불러온다(재생성하지 않음) — 새로고침/재방문 시 "이어서 보기"용. 가장 최근 매칭
    기준으로 조회한다."""
    _get_owned_project(db, project_id, current_user)
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    if match is None:
        raise HTTPException(status_code=404, detail='이 프로젝트엔 아직 매칭 결과가 없습니다')
    return _build_demo_response(db, project_id, match)


# companies.applicant_type -> 양식의 "사업자 구분" 표기. 사용자가 직접 고른 값이라
# 추측할 필요가 없다 — 예전엔 설립일 유무로 갈랐는데, 개인사업자도 설립일이 있으니
# 항상 '법인사업자'로 찍히는 버그였다(사용자 지적, 생성된 PDF로 확인).
_APPLICANT_TYPE_LABEL = {'corp': '법인사업자', 'individual': '개인사업자', 'preliminary': '예비창업자'}


def _build_plan_document_data(db: Session, project: Project, plan: BusinessPlan | None):
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
    section_by_tag = {s.tag: s for s in (plan.sections if plan is not None else [])}

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
        section = section_by_tag.get(tag)
        return section.body if section is not None and section.body else '※ 아직 생성된 계획서 문단이 없습니다.'

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
            project.tech_field or (plan_input.main_industry if plan_input else None), '○○·○○'),
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
):
    """사업계획서를 공식 양식(별첨1) 구조로 채운 진짜 .docx로 내려준다
    (app/plan_document_export.py). company.applicant_type이 'preliminary'(예비창업자)면
    예비창업패키지 양식, 그 외면 초기창업패키지(일반형) 양식으로 자동 분기한다
    (_build_plan_document_data 참고). 매칭/계획서가 아직 없어도 막지 않는다 —
    _build_plan_document_data가 없는 값은 원본 양식 안내 표기로 채워서라도 지금
    입력된 정보(프로젝트 설명·팀원)만으로 미리보기를 볼 수 있게 한다."""
    from app.plan_document_export import render_plan_docx

    project = _get_owned_project(db, project_id, current_user)
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    plan = None
    if match is not None:
        plan = (
            db.query(BusinessPlan)
            .filter(BusinessPlan.match_id == match.match_id)
            .order_by(BusinessPlan.plan_id.desc())
            .first()
        )

    data, template = _build_plan_document_data(db, project, plan)
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
):
    """download_plan_document(.docx)가 만든 그 파일을 그대로 PDF로 변환해 내려준다
    (app/pdf_export.py). 화면 미리보기(plan-form 우측 PDF 뷰어)가 쓰는 엔드포인트라
    inline로 내보낸다 — attachment면 브라우저가 뷰어 대신 다운로드를 띄운다.
    양식을 다시 그리지 않으므로 미리보기와 내려받는 문서가 어긋날 수 없다."""
    from app.pdf_export import PdfConversionError, docx_to_pdf
    from app.plan_document_export import render_plan_docx

    project = _get_owned_project(db, project_id, current_user)
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    plan = None
    if match is not None:
        plan = (
            db.query(BusinessPlan)
            .filter(BusinessPlan.match_id == match.match_id)
            .order_by(BusinessPlan.plan_id.desc())
            .first()
        )

    data, template = _build_plan_document_data(db, project, plan)
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
):
    """download_plan_document(.docx)와 같은 데이터로 실제 .hwp를 내려준다
    (app/hwp_export.py, rhwp CLI 기반). [2026-09-18] 예비창업패키지·초기창업패키지
    (일반형) 둘 다 실제 원본 양식 + 좌표 매핑까지 끝났다 — RHWP_BIN(.env.example
    참고)만 실제 rhwp 실행 파일 경로로 맞추면 이 서버에서도 바로 된다."""
    from app.hwp_export import render_plan_hwp

    project = _get_owned_project(db, project_id, current_user)
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    plan = None
    if match is not None:
        plan = (
            db.query(BusinessPlan)
            .filter(BusinessPlan.match_id == match.match_id)
            .order_by(BusinessPlan.plan_id.desc())
            .first()
        )

    data, template = _build_plan_document_data(db, project, plan)
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
):
    try:
        body = ProjectCreateRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc

    # 계정당 동시 실행 1건 제한(기획서 4-7, backend_decisions.md #11)의 락은 회사 프로필이
    # 아니라 계정(User 행) 자체를 잠가서 건다 — 회사 프로필을 만들기 전에 가장 먼저 걸어야
    # 같은 유저가 거의 동시에 두 번 요청을 보내도 두 번째 요청이 첫 번째 트랜잭션이 끝날
    # 때까지 대기했다가 최신 상태로 판정한다(_lock_user_for_concurrency_check 참고).
    _lock_user_for_concurrency_check(db, current_user)

    # 진행 중(in_progress) 매칭을 가진 프로젝트가 있는지로 판단한다(projects 자체엔 상태
    # 컬럼이 없다 — 설계 문서 원안). [2026-09-15 개정] 계정당 회사 프로필이 이제 여러 건일
    # 수 있어 Company.company_id 하나로는 못 좁히고, Company.user_id로 전체를 본다. 위에서
    # 이미 User 행을 잠갔으므로 이 조회 자체엔 with_for_update()가 필요 없다.
    active = (
        db.query(MatchResult)
        .join(Project, Project.project_id == MatchResult.project_id)
        .join(Company, Company.company_id == Project.company_id)
        .filter(
            Company.user_id == current_user.user_id,
            MatchResult.status.in_(ACTIVE_MATCH_STATUSES),
            MatchResult.archived_at.is_(None),
            or_(MatchResult.stage.is_(None), MatchResult.stage != ps.STAGE_DONE),
        )
        .first()
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=f'진행 중인 프로젝트(project_id={active.project_id})가 있습니다. 이어서 진행하거나 먼저 중단해주세요.',
        )

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
        main_industry=body.main_industry,
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


@router.delete('/{project_id}', status_code=204)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """대시보드 "내 프로젝트"의 휴지통 버튼 — 사용자가 자기 프로젝트를 목록에서 지운다.

    아직 공고 매칭 전(match_results 자체가 없음)이면 남길 데이터가 없으니 그냥 실제로
    지운다. 매칭 이후(계획서·산출물 등 이미 만들어진 뒤)면 실제로 지우지 않고
    match_results.archived_at/archived_by에 보관 처리만 한다(app_schema.sql 설계 그대로
    — "사용자가 프로젝트를 삭제해 보관 처리된 일시") — 이미 만든 계획서·산출물 데이터를
    보존하기 위해서고, 관리자 대시보드(진행 현황 탭)는 이 프로젝트를 계속 "보관중"으로
    조회·복원할 수 있다. list_projects()는 archived_at이 있는 프로젝트를 걸러서 본인
    목록에서는 안 보이게 한다."""
    project = _get_owned_project(db, project_id, current_user)
    match = (
        db.query(MatchResult)
        .filter(MatchResult.project_id == project.project_id)
        .order_by(MatchResult.match_id.desc())
        .first()
    )
    if match is not None:
        match.archived_at = datetime.datetime.utcnow()
        match.archived_by = 'user'
        db.commit()
        return Response(status_code=204)

    # 매칭 자체가 없던 프로젝트 — 진짜로 지운다. ORM 관계에 delete cascade를 안 걸어뒀고
    # SQLite는 기본적으로 FK도 강제 안 하므로, 자식 행을 먼저 지우는 순서를 직접 지킨다.
    db.query(ProjectAttachment).filter(ProjectAttachment.project_id == project_id).delete()
    db.query(TeamMember).filter(TeamMember.project_id == project_id).delete()
    db.query(PricingItem).filter(PricingItem.project_id == project_id).delete()
    db.query(MatchCandidate).filter(MatchCandidate.project_id == project_id).delete()
    db.query(ProjectPlanInput).filter(ProjectPlanInput.project_id == project_id).delete()
    db.query(Project).filter(Project.project_id == project_id).delete()
    db.commit()
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
        failure_reason=match.failure_reason,
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
        # 동일하게 유지). 지금은 더미 구현이 무작위 값을 돌려준다. [2026-09-22 수정]
        # plan_sections '3-1' 대신 plan_canonical_data에 쓴다 — agents.py 모듈 docstring의
        # "2026-09-22 수정" 참고(Strategy Agent는 분석 자료를 만들 뿐, 최종 문단은 작성
        # Agent 몫이라는 시트 구조에 맞춤).
        results = agents.run_strategy_agent_retry(project.description)
        changed['canonical_data'] = {r.data_key: _upsert_canonical_data(db, plan.plan_id, r) for r in results}

    elif task_key == 'writing':
        drafts = agents.run_writing_agent_retry(project.description, tags=['1-1', '2-1'])
        changed['sections'] = {d.tag: _upsert_plan_section(db, plan.plan_id, d) for d in drafts}

        # [2026-09-18 추가] "본문/그래프/표를 재작성했는데 왜 점수가 그대로냐"는 지적(하정원님)
        # — 작성은 콘텐츠만 바꾸고 채점은 검증-1 몫이라 그동안 점수가 안 바뀌었는데, 실제
        # 화면에도 검증-1을 따로 재시도하는 버튼이 없어(재작성 버튼뿐) 사용자가 점수를 갱신할
        # 방법 자체가 없었다. 그래서 작성 재시도에 검증-1(rubric+evidence) 재채점을 자동으로
        # 붙인다 — 채점 근거가 아직 없으면(초기 파이프라인 전) 조용히 건너뛴다.
        verify1_changed = {}
        for verify1_key in ('verify1_rubric', 'verify1_evidence'):
            result = _rescore_verify1(db, plan, verify1_key)
            if result is not None:
                verify1_changed[verify1_key] = result
        if verify1_changed:
            changed['verify1_rescore'] = verify1_changed

    elif task_key in ('verify1_rubric', 'verify1_evidence'):
        result = _rescore_verify1(db, plan, task_key)
        if result is None:
            raise HTTPException(status_code=404, detail='재채점할 채점 근거(plan_score_reasons)가 없습니다')
        changed.update(result)

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

        # [2026-09-18 추가] writing과 같은 이유 — 구현(파일 재생성)에도 검증-2(static+
        # crosscheck) 재채점을 자동으로 붙인다. 채점 근거가 없으면 조용히 건너뛴다.
        verify2_changed = {}
        for verify2_key in ('verify2_static', 'verify2_crosscheck'):
            result = _rescore_verify2(db, plan, artifact, verify2_key)
            if result is not None:
                verify2_changed[verify2_key] = result
        if verify2_changed:
            changed['verify2_rescore'] = verify2_changed

    elif task_key in ('verify2_static', 'verify2_crosscheck'):
        artifact = (
            db.query(Artifact)
            .filter(Artifact.plan_id == plan.plan_id)
            .order_by(Artifact.artifact_id.desc())
            .first()
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail='재채점할 산출물(artifacts)이 없습니다')

        result = _rescore_verify2(db, plan, artifact, task_key)
        if result is None:
            prefixes = _VERIFY2_STATIC_PREFIXES if task_key == 'verify2_static' else _VERIFY2_CROSSCHECK_PREFIXES
            raise HTTPException(
                status_code=404,
                detail=f'{task_key}에 해당하는 채점 근거(item_code 접두어 {prefixes})가 없습니다',
            )
        changed.update(result)

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
        next_attempt_no = (latest.attempt_no + 1) if latest is not None else 1
        result = agents.run_review_token_check_retry(project.description, attempt_no=next_attempt_no)
        db.add(ProofreadLog(
            plan_id=plan.plan_id,
            original_text=(latest.corrected_text if latest is not None else project.description),
            corrected_text=result.corrected_text,
            reason=result.reason,
            attempt_no=next_attempt_no,
            score=result.score,
            passed=result.passed,
            violation_type=result.violation_type,
            violation_note=result.violation_note,
            # passed=False인 시도는 그 즉시 "검수 회수 문단" 탭의 라벨링 대기열로 들어간다.
            recovery_status=None if result.passed else 'pending',
        ))
        changed['corrected_text'] = {
            'before': latest.corrected_text if latest is not None else None,
            'after': result.corrected_text,
        }
        changed['score'] = {'before': _num(latest.score) if latest is not None else None, 'after': _num(result.score)}
        changed['passed'] = result.passed
        if not result.passed:
            changed['violation_type'] = result.violation_type
            changed['violation_note'] = result.violation_note

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
