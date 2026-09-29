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
    GenerationFailureAlert,
    MatchCandidate,
    MatchScoreReason,
    Notice,
    NoticeAlert,
    Notification,
    PermanentDeletionLog,
    PlanCanonicalData,
    PlanScoreReason,
    PlanSection,
    PricingItem,
    Project,
    ProjectAttachment,
    ProjectBudgetItem,
    ProjectPartner,
    ProjectPlanInput,
    ProjectScheduleItem,
    ProofreadLog,
    TeamMember,
    User,
    Verdict,
    VerificationPolicy,
    VerificationScoreHistory,
)
from app.routers.profile import compute_has_profile
from app.schemas import (
    AgentExecutionOut,
    BundleUsageOut,
    BusinessPlanOut,
    DemoGenerateRequest,
    DemoGenerateResponse,
    EligibilityCheckOut,
    MatchCandidateOut,
    MatchCandidatesOut,
    MatchResultOut,
    NotificationOut,
    NotificationReadIn,
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


def _to_decimal(value: float | int | None) -> Decimal | None:
    """_num()의 역변환 — JSON 스냅샷(float)에서 DB 컬럼(Decimal)으로 되돌릴 때 쓴다."""
    return Decimal(str(value)) if value is not None else None


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
        # [2026-09-28 수정, 프론트 2차 요청 C] reason_text를 안 갱신해서 점수가 바뀌어도
        # 사유 문장은 재채점 전('통과' 등) 그대로 남아있던 버그 — 점수와 사유가 같은
        # 재채점 결과에서 같이 나와야 한다.
        reason.reason_text = result.reason_text
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
        # [2026-09-28 수정, 프론트 2차 요청 C] verify1과 같은 이유 — reason_text도 같이 갱신.
        reason.reason_text = result.reason_text
    artifact.artifact_score = sum((r.score or Decimal('0')) for r in all_reasons)

    # [2026-09-18 수정] verify1_* 재채점과 같은 이유 — 산출물층(code)도 재채점 이력을 남긴다.
    policy = _get_verification_policy(db)
    db.add(VerificationScoreHistory(
        plan_id=plan.plan_id, layer='code', score=artifact.artifact_score, is_rerun=True,
        policy_id=policy.policy_id, applied_weight=policy.code_weight,
        applied_pass_threshold=policy.pass_threshold, applied_rerun_cap=policy.rerun_cap,
    ))
    return {'scores': item_changes, 'artifact_score': {'before': _num(before_score), 'after': _num(artifact.artifact_score)}}


# ---------------------------------------------------------------------------
# 재작성 전후 점수 비교 + 버전 보존 (프론트 2차 요청 A-2, 기획서 5-6절)
# ---------------------------------------------------------------------------
# "재작성 전후의 검증 점수를 비교해 높은 쪽을 남긴다", "이전 결과는 삭제하지 않고
# 보존한다" — writing(문서층)/implement_*(산출물층) 재시도는 콘텐츠만 바꾸고 바로
# 확정해버려서, 재작성으로 점수가 떨어져도 그대로 남는 문제가 있었다(rework_comparisons
# 같은 별도 테이블도 없었음).
#
# 문서(plan_sections 등) 쪽은 버전마다 새 행을 쌓지 않고, 재작성 직전 상태를 JSON
# 스냅샷(BusinessPlan.version_history)으로 찍어뒀다가 점수가 낮으면 그 스냅샷으로
# 되돌린다.
#
# [2026-09-29 개정, SB-155] 산출물(artifacts) 쪽은 JSON 스냅샷 대신 실제로 버전마다
# 새 행을 쌓는 방식으로 바꿨다 — 형제 저장소 agent-orchestration의 "이름@버전"(이전
# 버전을 덮어쓰지 않고 쌓는) 설계와 맞춘 것. Artifact.is_current로 "지금 채택된 버전"
# 하나만 표시한다(app/routers/projects.py _get_current_artifact 참고).
#
# 두 방식 모두 GET /result의 plan.sections/plan.artifacts는 항상 지금 채택된 버전
# 하나만 내려가서, 프론트가 "여러 버전 중 뭐가 현재 버전인지" 고민할 필요가 없다
# (정재희님 우려 사항 — API 응답 모양은 안 바뀐다).

def _snapshot_plan_doc_state(plan: BusinessPlan) -> dict:
    """writing 재시도 직전 문서층 상태 스냅샷 — doc_score/plan_sections/plan_score_reasons
    전부를 담는다(작성 재시도가 자동으로 verify1_rubric/evidence까지 재채점하므로, 재작성이
    건드린 태그뿐 아니라 채점 근거 전체가 같이 바뀔 수 있음)."""
    return {
        'doc_score': _num(plan.doc_score),
        'sections': {s.tag: {'title': s.title, 'body': s.body} for s in plan.sections},
        'score_reasons': {
            r.item_code: {
                'score': _num(r.score), 'max_score': _num(r.max_score),
                'evidence_locator': r.evidence_locator, 'reason_text': r.reason_text,
            }
            for r in plan.score_reasons if r.item_code
        },
    }


def _restore_plan_doc_state(plan: BusinessPlan, snapshot: dict) -> None:
    """_snapshot_plan_doc_state가 찍어둔 스냅샷으로 되돌린다 — 재작성 후 점수가
    낮아졌을 때만 호출한다."""
    plan.doc_score = _to_decimal(snapshot['doc_score'])
    sections_by_tag = {s.tag: s for s in plan.sections}
    for tag, saved in snapshot['sections'].items():
        section = sections_by_tag.get(tag)
        if section is not None:
            section.title = saved['title']
            section.body = saved['body']
    reasons_by_code = {r.item_code: r for r in plan.score_reasons if r.item_code}
    for item_code, saved in snapshot['score_reasons'].items():
        reason = reasons_by_code.get(item_code)
        if reason is not None:
            reason.score = _to_decimal(saved['score'])
            reason.max_score = _to_decimal(saved['max_score'])
            reason.evidence_locator = saved['evidence_locator']
            reason.reason_text = saved['reason_text']


# [2026-09-29 신규, SB-155] 산출물(artifacts)은 문서(plan)와 달리 JSON 스냅샷이 아니라
# 버전마다 새 행을 쌓는다 — 형제 저장소 agent-orchestration의 "이름@버전"(이전 버전을
# 덮어쓰지 않고 쌓는 방식) 설계와 맞춘 것. plan_id당 is_current=TRUE는 정확히 한 행만
# 유지한다. API 응답(plan.artifacts는 여전히 1개만 옴)은 바뀌지 않는다 — is_current로
# 필터링해서 내려주기 때문.

def _get_current_artifact(db: Session, plan_id: int) -> Artifact | None:
    """이 plan의 "지금 채택된" 산출물 버전 하나 — GET /result, 재시도, 관리자 화면이
    전부 이 함수를 공유한다. artifact_id 최댓값이 아니라 is_current로 고른다: 재작성이
    거부된(점수가 낮아 채택 안 된) 새 버전은 artifact_id가 더 크면서도 is_current=False일
    수 있기 때문이다."""
    return (
        db.query(Artifact)
        .filter(Artifact.plan_id == plan_id, Artifact.is_current.is_(True))
        .order_by(Artifact.artifact_id.desc())
        .first()
    )


def _clone_artifact_as_new_version(db: Session, old: Artifact) -> Artifact:
    """재작성 직전 산출물을 다음 버전 행으로 복제한다 — 새 파일 경로는 호출부가 바로
    갱신하고, 점수 근거(artifact_score_reasons)는 재채점(_rescore_verify2)이 새 행을
    바로 찾을 수 있도록 여기서 통째로 복사해둔다(재채점은 일부 item_code만 갱신하므로,
    복사해두지 않은 나머지 항목이 새 버전에서 통째로 사라지는 걸 막기 위함)."""
    new = Artifact(
        plan_id=old.plan_id, category=old.category,
        infographic_path=old.infographic_path, executable_path=old.executable_path,
        artifact_score=old.artifact_score, version=old.version + 1, is_current=False,
    )
    db.add(new)
    db.flush()  # artifact_id 확보 — 아래 score_reasons가 이 id를 참조한다.
    for reason in old.score_reasons:
        db.add(ArtifactScoreReason(
            artifact_id=new.artifact_id, reason_text=reason.reason_text, item_code=reason.item_code,
            score=reason.score, max_score=reason.max_score, evidence_locator=reason.evidence_locator,
            display_name=reason.display_name,
        ))
    db.flush()
    return new


def _new_version_wins(before_score: Decimal | None, after_score: Decimal | None) -> bool:
    """재작성 전/후 점수를 비교해 새 버전을 채택(is_current)할지 정한다 — 점수가 없으면
    (아직 채점 근거가 없어 비교 자체가 불가능한 경우) 새 버전을 그냥 채택한다."""
    if before_score is None or after_score is None:
        return True
    return after_score >= before_score


def _decide_version(
    *, before_snapshot: dict, before_score: Decimal | None, after_score: Decimal | None, task_key: str,
) -> dict:
    """재작성 전/후 점수를 비교해 어느 쪽을 남길지 정하고, version_history에 追加할 항목을
    만든다. 점수가 없으면(아직 채점 근거가 없는 초기 파이프라인 전이라 재채점이 조용히
    건너뛰어진 경우) 비교 자체가 불가능하므로 새 버전을 그냥 채택한다."""
    # 둘 중 하나라도 없으면(아직 채점 근거가 없어 비교 자체가 불가능한 경우) 비교하지
    # 않고 새 버전을 그냥 채택한다 — 되돌릴 "이전 점수"라는 게 의미가 없기 때문.
    if before_score is None or after_score is None:
        kept = 'new'
    else:
        kept = 'new' if after_score >= before_score else 'previous'
    return {
        'kept': kept,
        'task_key': task_key,
        'before_score': _num(before_score),
        'after_score': _num(after_score),
        'snapshot': before_snapshot,
        'recorded_at': datetime.datetime.utcnow().isoformat(),
    }


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
        db.flush()  # section_id 확보 — agent_executions.output_ref가 이 행을 참조한다.
    else:
        section.title = draft.title
        section.body = draft.body
    return {'before': before, 'after': draft.body, 'id': section.section_id}


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
        db.flush()  # data_id 확보 — agent_executions.output_ref가 이 행을 참조한다.
    else:
        row.data_json = result.data_json
        row.source_function = result.source_function
    return {'before': before, 'after': result.data_json, 'id': row.data_id}

# repo 루트/uploads — database.py의 _REPO_ROOT 계산 방식과 동일하게 __file__ 기준으로 잡는다
# (app/routers/projects.py 에서 두 단계 위로 올라가면 app/ 이고, 그 위가 repo 루트).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_REPO_ROOT, 'uploads')

# 진행 중으로 취급하는 매칭 상태 — 이 상태의 매칭을 가진 프로젝트가 하나라도 있으면
# 계정당 동시 실행 1건 제한(기획서 4-7, backend_decisions.md #11)에 걸려 새 프로젝트 생성을
# 막는다. [2026-09-26 수정] waiting_resume(자동 재개 대기 중)도 화면상 "진행"으로 보이는
# 실행 중 상태라 포함해야 한다(공식 기능정의서 v1.9 E-RUN-CONCURRENT, R-9) — 빠뜨리면
# 재개 대기 중에도 사용자가 새 프로젝트를 하나 더 만들 수 있는 버그가 된다. failed는
# 여기 안 들어가는 게 맞다("계정당 1건 제한에서 세지 않는다", E-RUN-FAIL).
# [2026-09-28 수정] user_waiting(문서평가/산출물확인/종합평가 등 사용자 판단 대기, RunState.
# screenStatus='확인 필요')도 포함해야 한다 — 기능정의서 v1.9 R-9: "계정당 1건 제한은
# 진행 중·확인 필요만 센다"고 명시. 지금 더미 파이프라인엔 이 상태로 전환되는 코드 경로가
# 아직 없어 당장 트리거되진 않지만(app/pipeline_stages.py 주석 참고), 실제 검증-2/검수
# 단계가 붙어 이 상태가 쓰이기 시작하면 이 튜플이 자동으로 걸러줘야 한다.
ACTIVE_MATCH_STATUSES = (
    ps.GENERATION_STATUS_IN_PROGRESS,
    ps.GENERATION_STATUS_WAITING_RESUME,
    ps.GENERATION_STATUS_USER_WAITING,
)


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
    notices_by_id = {}
    notice_ids = [p.notice_id for p in projects if p.notice_id is not None]
    if notice_ids:
        notices_by_id = {
            n.notice_id: n
            for n in db.query(Notice).filter(Notice.notice_id.in_(notice_ids)).all()
        }
    items = []
    for project in projects:
        if project.archived_at is not None:
            continue  # 사용자가 지운(보관 처리한) 프로젝트는 본인 목록에서 숨긴다 — DELETE /projects/{id} 참고.
        notice_title = None
        screen = ps.NO_MATCH_SCREEN
        if project.notice_id is not None:
            notice = notices_by_id.get(project.notice_id)
            notice_title = notice.title if notice is not None else None
            screen = ps.STAGE_TO_SCREEN.get(project.stage) if project.stage is not None else None
        items.append(ProjectListItemOut(
            project_id=project.project_id,
            description=project.description,
            created_at=project.created_at,
            notice_id=project.notice_id,
            notice_title=notice_title,
            match_status=project.status,
            # [2026-09-23 신규] 화면 헤더 종모양 알림용 — 프론트가 이미 이 목록 엔드포인트를
            # 폴링하고 있어서(NotificationBell, front/src/features/workflow/shared.jsx)
            # 별도 알림 엔드포인트 대신 여기 필드만 추가한다. 서비스 내부 상태(실행/재개대기/
            # 사용자대기/실패/완료/중단)를 화면 문구(진행/확인이 필요합니다/문제가 생겨
            # 멈췄다/완료/중단됨)로 분류한다(app/pipeline_stages.py status_to_display).
            display_status=ps.status_to_display(project.status),
            stage=project.stage,
            progress_percent=project.progress_percent,
            screen=screen,
            resume_count=project.resume_count or 0,
            next_retry_at=project.next_retry_at,
            failure_reason=project.failure_reason,
        ))
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


def _build_demo_response(db: Session, project_id: int, project: Project) -> DemoGenerateResponse:
    """project_id 하나로 DemoGenerateResponse를 조립한다 — POST /generate(방금 막 만든
    project)와 GET /result(예전에 만들어둔 project를 다시 조회) 둘 다 이 함수를 공유한다.

    [2026-09-28, match_results 테이블 통합] 예전엔 match(MatchResult) 인자를 받았으나,
    그 필드들이 전부 Project로 옮겨오면서 project 하나만 받으면 된다."""
    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.project_id == project.project_id)
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
        artifact = _get_current_artifact(db, plan.plan_id)
        if artifact is not None:
            # [2026-09-29 수정, SB-155] artifact_id가 아니라 plan_id로 찾는다 — 산출물이
            # 재작성마다 새 행(다른 artifact_id)으로 쌓이면서, 초기 채점 때 만들어진 verdict가
            # 가리키던 artifact_id와 "지금 현재 버전"의 artifact_id가 달라질 수 있기 때문
            # (Verdict는 plan_id도 갖고 있어 그쪽으로 찾으면 버전이 바뀌어도 계속 찾아진다).
            verdict = (
                db.query(Verdict)
                .filter(Verdict.plan_id == plan.plan_id)
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
        .filter(EligibilityCheck.project_id == project.project_id)
        .order_by(EligibilityCheck.check_id.desc())
        .first()
    )
    executions = (
        db.query(AgentExecution)
        .filter(AgentExecution.project_id == project.project_id)
        .order_by(AgentExecution.execution_id.asc())
        .all()
    )
    policy = _get_verification_policy(db)

    verdict_out = None
    if verdict is not None:
        # [2026-09-22, 프론트 전달사항 10번] 검증결과서 "종합 판정" 행 — 문서층/자동검증/
        # 계획서대조 세 층 점수를 verification_policies 가중치 기준으로 합산한다. 자동검증/
        # 계획서대조는 artifact_score_reasons 하나에 섞여 있어서 item_code 접두어(_VERIFY2_
        # STATIC_PREFIXES='CHECK-'/_VERIFY2_CROSSCHECK_PREFIXES='FEATURE-')로 갈라 합산한다 —
        # _rescore_verify2가 재채점할 때 쓰는 것과 같은 구분.
        code_score = sum(
            (r.score or Decimal('0')) for r in artifact.score_reasons
            if r.item_code and r.item_code.startswith(_VERIFY2_STATIC_PREFIXES)
        )
        plan_match_score = sum(
            (r.score or Decimal('0')) for r in artifact.score_reasons
            if r.item_code and r.item_code.startswith(_VERIFY2_CROSSCHECK_PREFIXES)
        )
        doc_score = plan.doc_score or Decimal('0')
        total_score = doc_score + code_score + plan_match_score
        # [2026-09-28 수정, 프론트 2차 요청 B-3] verdict.overall_passed는 최초 생성 시점에
        # 한 번 저장된 값이라, 그 뒤 재채점으로 doc_score/code_score/plan_match_score가
        # 바뀌어도 안 따라온다 — 총점은 매번 새로 합산하면서 판정은 저장된 값을 그대로
        # 내려주니 "총점 15.07인데 통과"처럼 서로 다른 계산에서 나온 값이 어긋났다.
        # 판정을 항상 그 순간의 총점·기준값에서 유도한다(first_pass_passed는 "최초 결과가
        # 통과였는지"의 역사적 사실이라 그대로 저장값을 쓴다 — 재채점으로 안 바뀌어야 함).
        overall_passed = total_score >= policy.pass_threshold
        verdict_out = VerdictOut(
            overall_passed=overall_passed,
            model_version=verdict.model_version,
            first_pass_passed=verdict.first_pass_passed,
            doc_score=_num(doc_score),
            doc_max_score=_num(policy.doc_weight),
            code_score=_num(code_score),
            code_max_score=_num(policy.code_weight),
            plan_match_score=_num(plan_match_score),
            plan_match_max_score=_num(policy.plan_weight),
            total_score=_num(total_score),
            pass_threshold=_num(policy.pass_threshold),
        )

    # [2026-09-28 신규] 프론트 요청 2 — 화면에 보이는 "묶음(bundle)" 단위 재작성 사용/잔여
    # 횟수. retry_task의 409 판정과 같은 규칙(rerun_type='rerun' AND status='completed'만
    # 센다)을 그대로 써야 화면과 서버가 같은 숫자를 본다 — executions는 이미 조회해뒀으니
    # 쿼리 추가 없이 메모리에서 센다.
    # [2026-09-28 수정] task_key로 세면 writing 하나가 화면상 묶음 3개(본문/그래프/표)를
    # 가리켜서 틀린다 — writing은 bundle_id로, 이미 1:1인 구현 쪽은 task_key로 센 뒤 고정
    # 묶음 이름에 매핑한다(app/pipeline_stages.py WRITING_BUNDLES/TASK_KEY_TO_FIXED_BUNDLE).
    # strategy/verify1_*/verify2_*/review_*는 화면에 "재작성" 버튼이 없는 자동 연동 재시도라
    # 애초에 묶음 개념이 아니므로 이 목록에 안 넣는다.
    rework_used_by_bundle: dict[str, int] = {}
    for e in executions:
        if e.rerun_type != 'rerun' or e.status != ps.GENERATION_STATUS_COMPLETED:
            continue
        if e.task_key == 'writing' and e.bundle_id:
            rework_used_by_bundle[e.bundle_id] = rework_used_by_bundle.get(e.bundle_id, 0) + 1
        elif e.task_key in ps.TASK_KEY_TO_FIXED_BUNDLE:
            bundle = ps.TASK_KEY_TO_FIXED_BUNDLE[e.task_key]
            rework_used_by_bundle[bundle] = rework_used_by_bundle.get(bundle, 0) + 1

    bundle_ids = list(ps.WRITING_BUNDLES)
    if artifact is not None:
        # category='onepage'는 실행 파일(executable_path) 자체가 없어 그 묶음이 없다
        # (retry_task의 같은 규칙 참고 — "category='onepage' 산출물은... 실행 파일이 없어서").
        if artifact.category != 'onepage':
            bundle_ids.append(ps.BUNDLE_ARTIFACT_PROTOTYPE)
        bundle_ids.append(ps.BUNDLE_ARTIFACT_INFOGRAPHIC)

    bundle_usages = [
        BundleUsageOut(
            bundle_id=b,
            layer=ps.BUNDLE_TO_LAYER[b],
            used=rework_used_by_bundle.get(b, 0),
            remaining=max(policy.rework_cap - rework_used_by_bundle.get(b, 0), 0),
        )
        for b in bundle_ids
    ]

    return DemoGenerateResponse(
        project_id=project_id,
        match=MatchResultOut.model_validate(project),
        eligibility=EligibilityCheckOut.model_validate(eligibility),
        plan=BusinessPlanOut.model_validate(plan),
        verdict=verdict_out,
        agent_executions=[AgentExecutionOut.model_validate(e) for e in executions],
        rework_cap=policy.rework_cap,
        bundle_usages=bundle_usages,
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

    [2026-09-28, match_results 테이블 통합] 예전엔 project 하나에 match_results가
    여러 건 쌓일 수 있었다(호출할 때마다 새 세트가 하나 더 쌓임, seed_dummy_pipeline.py
    자체 동작) — 이 엔드포인트 자체 주석에 "임시 데모 우회"라고 명시돼 있던 그 동작이다.
    project(1):match(1)로 합쳐진 지금은 project 행 하나에 이 값들을 얹는 구조라 더 이상
    "여러 세트"가 존재할 수 없다 — project.notice_id가 이미 채워져 있으면(=이미 한 번
    생성됨) seed_dummy_pipeline을 다시 돌려 덮어쓰지 않고, 기존 상태를 그대로 재사용해
    돌려준다(계정당 동시 실행 1건 제한과 같은 "진행 중/완료된 실행은 새로 만들지 않는다"
    원칙, ACTIVE_MATCH_STATUSES/E-RUN-CONCURRENT 참고). 다시 매칭부터 새로 하고 싶으면
    SB-138 패턴대로 새 프로젝트를 만들면 된다(POST /projects)."""
    project = _get_owned_project(db, project_id, current_user)
    if project.notice_id is not None:
        return _build_demo_response(db, project_id, project)

    import seed_dummy_pipeline as _seed_pipeline  # 지연 import — 위 주석 참고(순환 import 회피)

    try:
        # [2026-09-29 신규] seed_dummy_pipeline()의 retry_agents 기본값('작성','구현')은
        # "로컬에서 CLI로 돌려서 이미 재시도 이력이 있는 것처럼 화면을 확인해보는" 용도로
        # 만든 편의 옵션이었는데, 이 엔드포인트가 진짜 유저의 유일한 생성 경로가 되면서
        # (실제 Agent가 아직 안 붙어 이 "임시 데모 우회"가 곧 실서비스 로직이다) 새
        # 프로젝트를 만들 때마다 writing/implement_prototype/implement_infographic에
        # rerun_type='rerun' 행이 미리 하나씩 깔려버렸다 — retry_task의 rework_cap 카운팅이
        # task_key/bundle_id별 rerun+completed 행 개수를 그대로 세기 때문에, 유저가 재작성
        # 버튼을 한 번도 안 눌렀는데도 실행 파일·인포그래픽 재작성이 이미 상한(기본 1회)에
        # 도달한 채로 시작하는 버그였다(문서 재작성 4묶음은 bundle_id가 없는 이 가짜 행과
        # 안 겹쳐서 우연히 무사했다). 실제 유저 생성 경로에는 이 가짜 이력을 남기지 않는다.
        verdict = _seed_pipeline.seed_dummy_pipeline(db, project_id, notice_id=body.notice_id, retry_agents=())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(verdict)

    plan = db.get(BusinessPlan, verdict.plan_id)
    project = db.get(Project, plan.project_id)
    # 공고 선택·자격 확인까지만 끝난 상태 — 계획서/프로토타입 생성은 사용자가 각각
    # POST .../plan/start, .../prototype/start 로 시작한다(stage NULL = 계획서 시작 전).
    project.stage = None
    project.progress_percent = None
    db.commit()
    return _build_demo_response(db, project_id, project)


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

# [2026-09-23 신규, 2026-09-26 정정] 실패 시 자동 "재개" 정책 — 공식 기능정의서 v1.9
# (시트 1_개요 "횟수·간격 설정값", R-11) 기준. 세션 초반엔 단위 없이 전달받아 초 단위로
# 잘못 구현했었다 — 실제로는 "재개 첫 간격" 15분부터 2배씩 늘려(15→30→60→120→240분)
# 최대 5번("재개 횟수")까지 자동 재개하고, 그래도 안 되면 status='failed'로 확정하고
# 관리자 알림(generation_failure_alerts)을 남긴다. 공식 스펙은 이 "재개"(시간을 두고
# 실패 지점부터 다시 시작)와 "재시도"(호출 실패 시 같은 호출을 즉시 다시 보냄, 5회,
# 간격은 구현하면서 정함)를 별개 2단계로 구분하는데, 지금 더미 시뮬레이션엔 개별 호출
# 재시도라는 더 낮은 층위가 없어서(실제 Agent가 API를 호출하기 전까진 의미가 없음)
# 이 코드는 "재개" 계층만 구현한다 — 실제 Agent가 붙으면 그 안에서 별도로 "재시도"
# 계층을 추가하면 된다.
GENERATION_RESUME_MAX_ATTEMPTS = int(os.getenv('GENERATION_RESUME_MAX_ATTEMPTS', '5'))
GENERATION_RESUME_BASE_SECONDS = float(os.getenv('GENERATION_RESUME_BASE_SECONDS', str(15 * 60)))  # 15분
# [2026-09-26 신규] "재개 총 대기 상한" — 재개 대기 + 재개 실행 시간을 모두 합한 바깥
# 상한(12시간). 재개 횟수(5번) 자체를 다 쓰기 전이라도 이 시간을 넘기면 바로 실패로
# 확정한다(무한 반복으로 비용이 발산하지 않게 하는 게 원칙).
GENERATION_RESUME_TOTAL_CAP_SECONDS = float(os.getenv('GENERATION_RESUME_TOTAL_CAP_SECONDS', str(12 * 3600)))  # 12시간

# running_stage -> done_stage. 복구 루프가 어떤 stage들을 감시해야 하는지 여기 한 곳에 모은다
# — _start_generation이 쓰는 (running_stage, done_stage) 쌍과 항상 같은 값이어야 한다.
_RUNNING_GENERATION_STAGES = {
    ps.STAGE_PLAN_WRITING: ps.STAGE_PLAN_REVIEW_PENDING,
    ps.STAGE_PROTOTYPE_BUILDING: ps.STAGE_DONE,
}


def _simulate_generation(project_id: int, running_stage: str, done_stage: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        try:
            project = db.get(Project, project_id)
            step = (project.progress_percent or 0) * DUMMY_GENERATION_STEPS // 100 if project else DUMMY_GENERATION_STEPS
            while step < DUMMY_GENERATION_STEPS:
                time.sleep(DUMMY_GENERATION_STEP_SECONDS)
                db.expire_all()
                project = db.get(Project, project_id)
                if project is None or project.stage != running_stage:
                    return
                step += 1
                if step >= DUMMY_GENERATION_STEPS:
                    project.stage = done_stage
                    project.progress_percent = 100
                    if done_stage == ps.STAGE_DONE:
                        project.status = ps.GENERATION_STATUS_COMPLETED
                        project.failure_reason = None
                    # [2026-09-27 신규, SB-141] 이 stage에 도달한 게 사용자 알림 대상이면
                    # (지금은 문서평가만 실제로 도달 가능 — 산출물확인/표현검수는 아직
                    # 없는 stage) notifications에 한 행 남긴다.
                    notif_kind = ps.STAGE_TO_NOTIFICATION_KIND.get(done_stage)
                    if notif_kind is not None:
                        db.add(Notification(
                            project_id=project.project_id,
                            kind=notif_kind,
                            target_step=ps.NOTIFICATION_KIND_TO_TARGET_STEP[notif_kind],
                        ))
                else:
                    project.progress_percent = step * 100 // DUMMY_GENERATION_STEPS
                project.worker_claimed_at = datetime.datetime.utcnow()  # 하트비트 — 진행 중엔 클레임이 안 늙는다
                # [2026-09-23 신규] 한 스텝이라도 성공하면(=다시 정상 진행되면) 이전 실패
                # 스트릭을 리셋한다 — 재개 예산(5회/12시간)은 "연속 실패"에 대한 것이지, 이
                # 작업 전체 수명 동안 누적되는 값이 아니다.
                project.resume_count = 0
                project.resume_started_at = None
                project.last_error_kind = None
                db.commit()
        except Exception as exc:
            # [2026-09-23 신규, 2026-09-26 정정, 2026-09-27 SB-134 분기 추가] 지금 더미
            # 로직(sleep+progress 증가)은 실패할 일이 없지만, 실제 에이전트가 붙으면 여기서
            # 예외가 날 수 있다. 공식 기능정의서 v1.9(R-11): "재개는 일시 오류일 때만 하며,
            # 재개 상한을 넘기거나 영구 오류가 나면 실행을 실패로 끝낸다." — 그래서 예외를
            # 먼저 분류(pipeline_stages.classify_error_kind)하고 갈린다:
            #   - 일시(ERROR_KIND_TRANSIENT): 기존 그대로 15분 -> 30 -> 60 -> 120 -> 240분
            #     백오프로 최대 5번까지 자동 재개한다(status='waiting_resume').
            #   - 입력·운영(영구 오류): 재개를 아예 시도하지 않고 바로 status='failed'로
            #     확정한다 — 같은 입력이나 API 키 문제는 기다린다고 나아지지 않는다.
            # 두 경우 다 관리자 알림(GenerationFailureAlert)을 남긴다. progress_percent는
            # 안 건드리므로 재개할 때마다 이미 진행된 부분부터 이어간다(처음부터 다시
            # 하지 않음).
            db.rollback()
            project = db.get(Project, project_id)
            if project is not None and project.stage == running_stage:
                now = datetime.datetime.utcnow()
                project.failure_reason = str(exc)[:2000]
                error_kind = ps.classify_error_kind(exc)
                project.last_error_kind = error_kind
                # [2026-09-28 신규] 관리자 "에이전트 테스크" 탭이 stage 단위 실패도 볼 수
                # 있도록 agent_executions에도 남긴다 — 재시도(POST .../retry-task)와 같은
                # attempt_no 채번 규칙(같은 task_key 안에서 이어서 증가)을 쓴다.
                stage_agent_task = ps.STAGE_TO_AGENT_TASK.get(running_stage)
                if stage_agent_task is not None:
                    stage_agent_name, stage_task_key = stage_agent_task
                    last_stage_attempt = (
                        db.query(AgentExecution)
                        .filter(AgentExecution.project_id == project.project_id, AgentExecution.task_key == stage_task_key)
                        .order_by(AgentExecution.attempt_no.desc())
                        .first()
                    )
                    db.add(AgentExecution(
                        project_id=project.project_id,
                        agent_name=stage_agent_name,
                        task_key=stage_task_key,
                        attempt_no=(last_stage_attempt.attempt_no + 1) if last_stage_attempt is not None else 1,
                        model_used='dummy',
                        rerun_type='initial' if last_stage_attempt is None else 'rerun',
                        token_usage=0,
                        status=ps.GENERATION_STATUS_FAILED,
                        error_kind=error_kind,
                        error_reason=project.failure_reason,
                    ))
                if error_kind != ps.ERROR_KIND_TRANSIENT:
                    project.status = ps.GENERATION_STATUS_FAILED
                    project.next_retry_at = None
                    db.add(GenerationFailureAlert(
                        project_id=project.project_id,
                        stage=project.stage,
                        resume_count=project.resume_count or 0,
                        last_error_kind=error_kind,
                        failure_reason=project.failure_reason,
                    ))
                    # [2026-09-27 신규, SB-141] 실행 실패(E-RUN-FAIL) 사용자 알림. 재작성
                    # 실패(failure_scope='재작성')는 재작성 기능(2-1/2-2)이 아직 없어서
                    # 여기선 항상 '실행'이다.
                    db.add(Notification(
                        project_id=project.project_id,
                        kind=ps.NOTIFICATION_KIND_FAILURE,
                        failure_scope=ps.NOTIFICATION_FAILURE_SCOPE_RUN,
                    ))
                    db.commit()
                    return
                if project.resume_count == 0:
                    project.resume_started_at = now  # 이번 실패 스트릭의 시작 시각
                project.resume_count = (project.resume_count or 0) + 1
                elapsed = (now - project.resume_started_at).total_seconds() if project.resume_started_at else 0.0
                if project.resume_count > GENERATION_RESUME_MAX_ATTEMPTS or elapsed > GENERATION_RESUME_TOTAL_CAP_SECONDS:
                    project.status = ps.GENERATION_STATUS_FAILED
                    project.next_retry_at = None
                    db.add(GenerationFailureAlert(
                        project_id=project.project_id,
                        stage=project.stage,
                        resume_count=project.resume_count - 1,
                        last_error_kind=error_kind,
                        failure_reason=project.failure_reason,
                    ))
                    db.add(Notification(
                        project_id=project.project_id,
                        kind=ps.NOTIFICATION_KIND_FAILURE,
                        failure_scope=ps.NOTIFICATION_FAILURE_SCOPE_RUN,
                    ))
                else:
                    delay = GENERATION_RESUME_BASE_SECONDS * (2 ** (project.resume_count - 1))
                    project.status = ps.GENERATION_STATUS_WAITING_RESUME
                    project.next_retry_at = now + datetime.timedelta(seconds=delay)
                db.commit()
    finally:
        db.close()


def _try_claim_and_run(project_id: int, running_stage: str, done_stage: str) -> bool:
    """project_id의 running_stage 작업을 원자적으로 클레임하고, 성공한 경우에만 실행 스레드를
    띄운다. 실패(이미 다른 곳에서 처리 중)하면 아무 것도 안 하고 False를 돌려준다 — 즉시시작
    경로(_start_generation)와 복구 루프(_generation_recovery_loop)가 공유한다."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        stale_before = datetime.datetime.utcnow() - datetime.timedelta(seconds=GENERATION_CLAIM_STALE_SECONDS)
        claimed = (
            db.query(Project)
            .filter(
                Project.project_id == project_id,
                Project.stage == running_stage,
                or_(Project.worker_claimed_at.is_(None), Project.worker_claimed_at < stale_before),
            )
            # [2026-09-23] status='waiting_resume'로 대기하던 행을 자동 재시도가 실제로
            # 집어 들 때, 상태를 다시 '실행'으로 되돌린다(next_retry_at도 비움) — 화면상
            # 둘 다 "진행"으로 같이 보이긴 하지만, 내부 상태는 지금 실제로 도는 중임을
            # 정확히 반영해야 한다.
            .update(
                {Project.worker_claimed_at: datetime.datetime.utcnow(), Project.status: ps.GENERATION_STATUS_IN_PROGRESS, Project.next_retry_at: None},
                synchronize_session=False,
            )
        )
        db.commit()
    finally:
        db.close()
    if claimed == 1:
        threading.Thread(target=_simulate_generation, args=(project_id, running_stage, done_stage), daemon=True).start()
        return True
    return False


def _recover_orphaned_generations_once(db: Session) -> None:
    """진행 중 stage인데 클레임이 없거나 오래된(GENERATION_CLAIM_STALE_SECONDS) projects
    행을 한 번 훑어 이어받는다 — _generation_recovery_loop이 매 tick 호출하고, 테스트도
    무한루프 대신 이 함수 하나만 직접 불러 검증한다.

    [2026-09-23 개정] status='waiting_resume'(자동 백오프 대기 중)인 행도 이제 여기서
    이어받는다 — 단, next_retry_at이 아직 안 지났으면 건드리지 않는다(백오프 간격 준수).
    status='failed'(자동 재시도 5회 소진, 확정된 실패)만 여전히 자동으로 건드리지 않고
    사용자가 "다시 이어가기"를 눌러야(_start_generation) 재개된다."""
    stale_before = datetime.datetime.utcnow() - datetime.timedelta(seconds=GENERATION_CLAIM_STALE_SECONDS)
    now = datetime.datetime.utcnow()
    for running_stage, done_stage in _RUNNING_GENERATION_STAGES.items():
        orphans = (
            db.query(Project.project_id)
            .filter(
                Project.stage == running_stage,
                Project.status != ps.GENERATION_STATUS_FAILED,
                or_(Project.worker_claimed_at.is_(None), Project.worker_claimed_at < stale_before),
                or_(Project.next_retry_at.is_(None), Project.next_retry_at <= now),
            )
            .all()
        )
        for (orphan_project_id,) in orphans:
            _try_claim_and_run(orphan_project_id, running_stage, done_stage)


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
    if project.notice_id is None:
        raise HTTPException(status_code=400, detail='먼저 공고를 선택해 주세요.')
    # [2026-09-22 신규, 프론트 전달사항 4번] "다시 시도" — 실패는 stage를 실패한 단계 그대로
    # 두므로(_simulate_generation), 실패한 바로 그 단계에 대해서만(stage == running_stage)
    # 재시작을 허용한다 — 다른 단계에서 실패했는데 엉뚱한 단계가 리셋되면 안 되니까.
    can_retry_failed = project.status == ps.GENERATION_STATUS_FAILED and project.stage == running_stage
    if project.stage in start_from or can_retry_failed:
        project.stage = running_stage
        project.progress_percent = 0
        project.worker_claimed_at = None  # 새 단계 시작 — 이전 단계의 클레임 흔적을 지운다
        project.status = ps.GENERATION_STATUS_IN_PROGRESS
        project.failure_reason = None
        # [2026-09-23 신규, 2026-09-26 정정] 수동 "다시 이어가기"는 재개 횟수를 0으로
        # 완전히 리셋하지 않고 1로 둔다 — 이 수동 클릭 자체를 재개 1회로 친다(원래 재개
        # 예산 5회의 연장선). 그래서 이 시도도 또 실패하면 바로 2번째 백오프(30분)부터
        # 이어간다. resume_started_at도 지금(수동 클릭 시각)으로 다시 잡아서 "재개 총
        # 대기 상한"(12시간)도 이 시점부터 새로 잰다. 최초 시작(재개가 아니라 처음
        # 시작하는 경우)은 둘 다 비운다.
        project.resume_count = 1 if can_retry_failed else 0
        project.resume_started_at = datetime.datetime.utcnow() if can_retry_failed else None
        project.last_error_kind = None
        project.next_retry_at = None
        db.commit()
    # 이미 진행 중이면(다른 요청/복구 루프가 먼저 클레임했으면) 새로 시작하지 않는다 —
    # _try_claim_and_run의 원자적 UPDATE가 중복 실행 방지를 대신한다. status='waiting_resume'
    # 이면서 next_retry_at이 아직 안 지났으면 여기서도 건드리지 않는다 — 백오프 대기를
    # 사용자가 화면을 다시 열었다고 건너뛰면 안 된다(복구 루프와 같은 규칙).
    backoff_pending = project.status == ps.GENERATION_STATUS_WAITING_RESUME and project.next_retry_at and project.next_retry_at > datetime.datetime.utcnow()
    if project.stage == running_stage and project.status != ps.GENERATION_STATUS_FAILED and not backoff_pending:
        _try_claim_and_run(project.project_id, running_stage, done_stage)
    return ProjectStatusOut(
        project_id=project.project_id,
        screen=ps.STAGE_TO_SCREEN.get(project.stage) if project.stage is not None else None,
        stage=project.stage,
        progress_percent=project.progress_percent,
        match_status=project.status,
        failure_reason=project.failure_reason,
        resume_count=project.resume_count or 0,
        next_retry_at=project.next_retry_at,
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
    불러온다(재생성하지 않음) — 새로고침/재방문 시 "이어서 보기"용."""
    project = _get_owned_project(db, project_id, current_user)
    if project.notice_id is None:
        raise HTTPException(status_code=404, detail='이 프로젝트엔 아직 매칭 결과가 없습니다')
    return _build_demo_response(db, project_id, project)


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
):
    """사업계획서를 공식 양식(별첨1) 구조로 채운 진짜 .docx로 내려준다
    (app/plan_document_export.py). company.applicant_type이 'preliminary'(예비창업자)면
    예비창업패키지 양식, 그 외면 초기창업패키지(일반형) 양식으로 자동 분기한다
    (_build_plan_document_data 참고). 매칭/계획서가 아직 없어도 막지 않는다 —
    _build_plan_document_data가 없는 값은 원본 양식 안내 표기로 채워서라도 지금
    입력된 정보(프로젝트 설명·팀원)만으로 미리보기를 볼 수 있게 한다."""
    from app.plan_document_export import render_plan_docx

    project = _get_owned_project(db, project_id, current_user)
    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.project_id == project_id)
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
    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.project_id == project_id)
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
    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.project_id == project_id)
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

    # [2026-09-27 신규] 필수 동의(이용약관/개인정보) 게이트 — 공식 기능정의서 v1.9
    # E-AUTH-CONSENT: "필수 항목에 동의해야 계정과 작업 결과를 보관할 수 있습니다...
    # 진입을 중단한다." 새 실행 시작이 곧 "진입"에 해당하므로 여기서 막는다. 로그인
    # 자체(POST /auth/google)는 계정 생성을 위해 막지 않는다 — 동의 화면은 로그인
    # 이후 별도로 뜨고, PATCH /auth/consent가 완료돼야 아래 두 값이 채워진다.
    if current_user.terms_agreed_at is None or current_user.privacy_agreed_at is None:
        raise HTTPException(
            status_code=403,
            detail='필수 항목(이용약관, 개인정보 수집·이용)에 동의해야 이용할 수 있습니다.',
        )

    # [2026-09-27 신규] 마이페이지 프로필 게이트 — 공식 기능정의서 v1.9 E-AUTH-PROFILE:
    # "필수 항목을 채운 프로필이 생기기 전에는 새 실행을 시작할 수 없다." 최초 로그인
    # 이거나(프로필 0개) 있던 프로필을 전부 지운 경우가 해당한다. has_profile 계산은
    # /auth/me·로그인 응답이 쓰는 것과 같은 함수(compute_has_profile)를 그대로 재사용한다
    # — 슬롯 하나라도 필수 입력을 전부 채웠는지를 본다.
    if not compute_has_profile(db, current_user.user_id):
        raise HTTPException(
            status_code=403,
            detail='서비스를 이용하려면 먼저 마이페이지에서 프로필을 만들어주세요.',
        )

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
        db.query(Project)
        .join(Company, Company.company_id == Project.company_id)
        .filter(
            Company.user_id == current_user.user_id,
            Project.status.in_(ACTIVE_MATCH_STATUSES),
            Project.archived_at.is_(None),
            or_(Project.stage.is_(None), Project.stage != ps.STAGE_DONE),
        )
        .first()
    )
    if active is not None:
        # [2026-09-27 신규, SB-138] 공식 기능정의서 v1.9 E-RUN-CONCURRENT: "새 Run을 만들지
        # 않고 blocked=true를 반환한다. 진행 중인 작업의 현재 단계를 보여주고 이어하기와
        # 중단 후 새로 시작 중 선택하게 한다." 예전엔 사람이 읽는 문장 하나만 detail로
        # 내려줘서 프론트가 이 선택 화면을 만들 정보(어느 프로젝트인지, 지금 몇 화면인지)를
        # 파싱할 방법이 없었다 — 구조화된 필드로 바꾼다.
        #
        # "중단 후 새로 시작"은 별도 엔드포인트를 새로 만들지 않는다 — 기존 DELETE
        # /projects/{id}가 이미 정확히 이 역할이다(상태와 무관하게 보관 처리하고 계정당
        # 1건 제한에서 제외시킨다, test_archived_running_project_does_not_block 참고).
        # 프론트가 active_project_id로 그 엔드포인트를 부르면 된다. "결과를 다시 볼 수
        # 없다는 사실을 확인받는다"는 프론트 쪽 확인 다이얼로그의 몫이다.
        raise HTTPException(
            status_code=409,
            detail={
                'message': '진행 중인 작업이 있습니다. 이어서 진행하거나, 중단하고 새로 시작할 수 있습니다. 중단하면 지금까지의 결과를 다시 볼 수 없습니다.',
                'blocked': True,
                'active_project_id': active.project_id,
                'active_stage': active.stage,
                'active_screen': ps.STAGE_TO_SCREEN.get(active.stage) if active.stage is not None else None,
                'active_display_status': ps.status_to_display(active.status),
            },
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

    아직 공고 매칭 전(notice_id가 없음)이면 남길 데이터가 없으니 그냥 실제로 지운다.
    매칭 이후(계획서·산출물 등 이미 만들어진 뒤)면 실제로 지우지 않고
    projects.archived_at/archived_by에 보관 처리만 한다(app_schema.sql 설계 그대로
    — "사용자가 프로젝트를 삭제해 보관 처리된 일시") — 이미 만든 계획서·산출물 데이터를
    보존하기 위해서고, 관리자 대시보드(진행 현황 탭)는 이 프로젝트를 계속 "보관중"으로
    조회·복원할 수 있다. list_projects()는 archived_at이 있는 프로젝트를 걸러서 본인
    목록에서는 안 보이게 한다."""
    project = _get_owned_project(db, project_id, current_user)
    if project.notice_id is not None:
        project.archived_at = datetime.datetime.utcnow()
        project.archived_by = 'user'
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


def _delete_artifact_files(artifact: Artifact) -> None:
    """[2026-09-29 신규, SB-160; 2026-09-29 단순화, SB-155] 완전 삭제 시 이 산출물 행이
    디스크에 남긴 파일을 지운다. DB 행만 지우고 파일은 그대로 두면(예전
    _delete_project_cascade가 그랬음) UPLOAD_DIR에 영원히 고아 파일로 남는다. [SB-155]
    산출물이 이제 버전마다 새 행으로 쌓이므로(JSON 스냅샷이 아니라 실제 행), 이 함수를
    부르는 쪽(_delete_project_cascade)이 그 plan의 모든 버전 행을 순회하기만 하면 되고,
    이 함수는 "행 하나 몫의 파일"만 책임지면 된다 — 예전엔 한 행에 여러 버전이
    version_history로 몰려 있어서 여기서 직접 그 목록을 펼쳐야 했다."""
    paths = {artifact.infographic_path, artifact.executable_path}
    for url in paths:
        if not url:
            continue
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(url)))
        except OSError:
            pass


def _delete_project_cascade(db: Session, project: Project) -> None:
    """[2026-09-28 신규] "건별 삭제" — 프로젝트 기획서 v1.10 6-7절 표: 사전 정보 입력값/
    산출물은 "건별 삭제 가능"이라고 명시돼 있다. 위 delete_project()는 매칭 이후엔 archive만
    하고 실제로 안 지우는데(관리자 대시보드 "진행 현황" 탭의 보관중/복원 기능을 위해 일부러
    그렇게 둔 것) — 이 함수는 그것과 독립적으로, 보관 여부와 무관하게 바로 완전히 지우는
    경로다(delete_project_permanently 참고). app/routers/auth.py _delete_account_cascade의
    "프로젝트 하나 분량"과 같은 구조 — 차이는 그 프로젝트 전용 Company 행(1:1, company_id에
    유니크 제약이 없는 이유는 app/models.py Company 주석 참고)도 여기서 같이 지운다는 것.

    [2026-09-28, match_results 테이블 통합] project(1):match(1)로 합쳐지면서 match_ids
    조회 단계 자체가 필요 없어졌다 — project_id로 바로 plan_ids를 구하고, project의
    match 필드들(자식 테이블들)도 project_id로 바로 지운다."""
    project_id = project.project_id
    plan_ids = [p.plan_id for p in db.query(BusinessPlan.plan_id).filter(BusinessPlan.project_id == project_id)]

    if plan_ids:
        artifacts = db.query(Artifact).filter(Artifact.plan_id.in_(plan_ids)).all()
        for artifact in artifacts:
            _delete_artifact_files(artifact)
        artifact_ids = [a.artifact_id for a in artifacts]
        if artifact_ids:
            db.query(ArtifactScoreReason).filter(ArtifactScoreReason.artifact_id.in_(artifact_ids)).delete(synchronize_session=False)
        db.query(Verdict).filter(Verdict.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(Artifact).filter(Artifact.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(ProofreadLog).filter(ProofreadLog.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(FormatFinding).filter(FormatFinding.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(PlanScoreReason).filter(PlanScoreReason.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(PlanCanonicalData).filter(PlanCanonicalData.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(VerificationScoreHistory).filter(VerificationScoreHistory.plan_id.in_(plan_ids)).delete(synchronize_session=False)
        db.query(PlanSection).filter(PlanSection.plan_id.in_(plan_ids)).delete(synchronize_session=False)
    db.query(BusinessPlan).filter(BusinessPlan.project_id == project_id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.project_id == project_id).delete(synchronize_session=False)
    db.query(GenerationFailureAlert).filter(GenerationFailureAlert.project_id == project_id).delete(synchronize_session=False)
    db.query(MatchScoreReason).filter(MatchScoreReason.project_id == project_id).delete(synchronize_session=False)
    db.query(EligibilityCheck).filter(EligibilityCheck.project_id == project_id).delete(synchronize_session=False)
    db.query(AgentExecution).filter(AgentExecution.project_id == project_id).delete(synchronize_session=False)
    db.query(MatchCandidate).filter(MatchCandidate.project_id == project_id).delete(synchronize_session=False)
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
    # [2026-09-28 신규] 프론트 요청 4 — 식별자 없이 "삭제됐다"는 사실과 시각만 남긴다.
    db.add(PermanentDeletionLog())
    db.commit()


@router.delete('/{project_id}/permanent', status_code=204)
def delete_project_permanently(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """"건별 삭제"(완전 삭제) — 프로젝트 기획서 v1.10 6-7절. 보관(archive) 여부·매칭 진행
    상태와 무관하게 바로 실제로 지운다 — DELETE /projects/{id}(휴지통, 매칭 이후엔 archive만
    함)와는 독립된 별도 액션이다. 되돌릴 수 없다 — 프론트는 호출 전 확인 다이얼로그를
    거쳐야 한다.

    [2026-09-28 신규] 프론트 요청 3 — 계획서·프로토타입 생성이 threading.Thread로 도는
    중(_simulate_generation)에 행이 사라지면 그 쓰레드가 없는 project_id를 계속 쓰게
    된다. 지금까지는 프론트가 버튼을 잠그는 게 유일한 방어선이었다 — _RUNNING_GENERATION_
    STAGES(=_simulate_generation이 감시하는 stage 집합, _start_generation과 항상 같은
    값)에 있는 동안이면 서버도 409로 거절한다. 휴지통(delete_project, archive만 함)은
    이 제한과 무관하다."""
    project = _get_owned_project(db, project_id, current_user)
    if project.stage in _RUNNING_GENERATION_STAGES:
        raise HTTPException(status_code=409, detail='생성이 끝난 뒤에 완전히 삭제할 수 있습니다')
    _delete_project_cascade(db, project)
    return Response(status_code=204)


def _get_owned_project(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    if project.company.user_id != user.user_id and user.role != 'admin':
        raise HTTPException(status_code=404, detail='프로젝트를 찾을 수 없습니다')
    return project


def _is_notice_closed(db: Session, notice_id: str | None) -> bool:
    """[2026-09-27 신규, SB-139] 이어하기로 복귀한 시점에 사용자가 고른 공고가 그새
    마감됐는지 확인한다(E-RUN-CLOSED). recruitment_status가 수집 파이프라인 쪽에서
    'open' 외의 값으로 바뀌었거나, apply_end가 오늘보다 이전이면 마감으로 본다 —
    두 신호를 같이 보는 이유는 apply_period_type이 'budget_exhaustion'/'rolling'처럼
    날짜만으로 마감을 판단할 수 없는 경우도 있고(Notice 모델 주석 참고), 반대로
    recruitment_status 갱신이 apply_end 당일 자정에 딱 맞춰 반영된다는 보장도 없기
    때문이다. 공고 자체를 못 찾으면(드묾 — 수집 데이터가 지워진 경우) 마감이 아니라고
    본다: 판단할 근거가 없을 때 실행을 막는 쪽으로 오판하지 않기 위해서다."""
    if notice_id is None:
        return False
    notice = db.query(Notice).filter(Notice.notice_id == notice_id).one_or_none()
    if notice is None:
        return False
    if notice.recruitment_status != 'open':
        return True
    if notice.apply_end is not None and notice.apply_end < datetime.date.today():
        return True
    return False


@router.get('/{project_id}/status', response_model=ProjectStatusOut)
def get_project_status(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    project = _get_owned_project(db, project_id, current_user)

    if project.notice_id is None:
        # 매칭 자체가 없음 — 아직 공고를 고르기 전(8케이스의 ①) -> 화면 3(공고 매칭)으로.
        return ProjectStatusOut(project_id=project.project_id, screen=ps.NO_MATCH_SCREEN)

    screen = ps.STAGE_TO_SCREEN.get(project.stage) if project.stage is not None else None
    return ProjectStatusOut(
        project_id=project.project_id,
        screen=screen,
        stage=project.stage,
        progress_percent=project.progress_percent,
        match_status=project.status,
        failure_reason=project.failure_reason,
        resume_count=project.resume_count or 0,
        next_retry_at=project.next_retry_at,
        notice_closed=_is_notice_closed(db, project.notice_id),
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

    if project.notice_id is None:
        raise HTTPException(status_code=404, detail='이 프로젝트엔 아직 매칭 결과가 없어 재시도할 작업이 없습니다')

    plan = (
        db.query(BusinessPlan)
        .filter(BusinessPlan.project_id == project.project_id)
        .order_by(BusinessPlan.plan_id.desc())
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail='이 프로젝트엔 아직 사업계획서가 없어 재시도할 수 없습니다')

    # [2026-09-28 신규, 프론트 답변 반영] writing은 화면상 묶음 3개를 공유하므로 bundle_id가
    # 필수다 — 안 보내면 어느 묶음을 재작성한 건지 서버가 구분할 수 없다. 그 외 task_key는
    # 이미 묶음과 1:1이라(app/pipeline_stages.py TASK_KEY_TO_FIXED_BUNDLE) 생략하면 그 고정
    # 값으로 채우고, 보냈다면 그 고정값과 일치하는지만 검증한다(둘 다 없는 task_key는 묶음
    # 개념이 아니므로 bundle_id를 그냥 무시한다). 프로젝트/계획서 존재 확인(404)보다는 뒤에
    # 둔다 — "매칭도 없는 프로젝트"에 bundle_id 누락까지 같이 따질 이유가 없다.
    if body.task_key == 'writing':
        if body.bundle_id not in ps.WRITING_BUNDLES:
            raise HTTPException(
                status_code=400,
                detail=f'writing 재시도는 bundle_id가 필요합니다 (가능한 값: {ps.WRITING_BUNDLES})',
            )
        bundle_id = body.bundle_id
    elif body.task_key in ps.TASK_KEY_TO_FIXED_BUNDLE:
        fixed_bundle = ps.TASK_KEY_TO_FIXED_BUNDLE[body.task_key]
        if body.bundle_id is not None and body.bundle_id != fixed_bundle:
            raise HTTPException(
                status_code=400,
                detail=f'{body.task_key!r}의 bundle_id는 {fixed_bundle!r}로 고정입니다',
            )
        bundle_id = fixed_bundle
    else:
        bundle_id = None

    agent_name = _TASK_KEY_TO_AGENT[body.task_key]
    last_attempt = (
        db.query(AgentExecution)
        .filter(AgentExecution.project_id == project.project_id, AgentExecution.task_key == body.task_key)
        .order_by(AgentExecution.attempt_no.desc())
        .first()
    )
    next_attempt_no = (last_attempt.attempt_no + 1) if last_attempt is not None else 1

    # [2026-09-28 신규] 프론트 요청 1 — "재작성" 상한(rework_cap) 초과를 서버가 막는다.
    # 첫 실행(rerun_type='initial', _simulate_generation이 만듦)은 세지 않고, 이 엔드포인트가
    # 만든 행 중 실제로 성공(status='completed')한 것만 센다 — 실패한 재작성은 기획서
    # 5-6절 "재작성이 실패하면 쓴 기회를 돌려준다" 규칙에 따라 소진되지 않는다.
    policy = _get_verification_policy(db)
    rework_used_query = db.query(AgentExecution).filter(
        AgentExecution.project_id == project.project_id,
        AgentExecution.task_key == body.task_key,
        AgentExecution.rerun_type == 'rerun',
        AgentExecution.status == ps.GENERATION_STATUS_COMPLETED,
    )
    # writing만 bundle_id로 추가 필터링한다 — 나머지는 task_key만으로 이미 묶음 하나와
    # 1:1이라 더 좁힐 필요가 없다(위 bundle_id 해석 로직 주석 참고).
    if body.task_key == 'writing':
        rework_used_query = rework_used_query.filter(AgentExecution.bundle_id == bundle_id)
    rework_used = rework_used_query.count()
    if rework_used >= policy.rework_cap:
        raise HTTPException(
            status_code=409,
            detail=f'"{bundle_id}" 항목은 재작성 상한 {policy.rework_cap}회를 이미 사용했습니다',
        )

    changed: dict = {}
    output_ref: dict | list | None = None
    task_key = body.task_key
    # implement_prototype/infographic이 파일을 디스크에 쓴 뒤 DB 트랜잭션이 실패하면(아래
    # except) 방금 쓴 파일이 아무 행도 가리키지 않는 진짜 고아 파일로 남는다 — 이 경우에만
    # 정리 대상이라 여기서 미리 None으로 잡아두고, 파일을 쓴 직후 채운다.
    written_dest_path: str | None = None

    try:
        if task_key == 'strategy':
            # app/agents.py — 실제 Agent가 연동되면 이 호출 하나만 실제 구현으로 바뀐다(계약은
            # 동일하게 유지). 지금은 더미 구현이 무작위 값을 돌려준다. [2026-09-22 수정]
            # plan_sections '3-1' 대신 plan_canonical_data에 쓴다 — agents.py 모듈 docstring의
            # "2026-09-22 수정" 참고(Strategy Agent는 분석 자료를 만들 뿐, 최종 문단은 작성
            # Agent 몫이라는 시트 구조에 맞춤).
            results = agents.run_strategy_agent_retry(project.description)
            changed['canonical_data'] = {r.data_key: _upsert_canonical_data(db, plan.plan_id, r) for r in results}
            output_ref = [{'table': 'plan_canonical_data', 'id': v['id']} for v in changed['canonical_data'].values()]

        elif task_key == 'writing':
            # [2026-09-28 신규, 프론트 2차 요청 A-2] 재작성 직전 상태를 먼저 찍어둔다 —
            # 재채점 후 점수가 떨어지면 이 스냅샷으로 되돌린다.
            before_snapshot = _snapshot_plan_doc_state(plan)
            before_doc_score = plan.doc_score

            # [2026-09-29 수정] 예전엔 bundle_id와 무관하게 항상 ['1-1', '2-1']만 재생성해서,
            # "성장전략"이나 "팀 구성" 묶음을 재작성해도 실제로는 문제인식/실현가능성만 바뀌고
            # 정작 고른 섹션은 그대로였다 — bundle_id가 가리키는 섹션 하나만 정확히 재생성한다.
            drafts = agents.run_writing_agent_retry(
                project.description, tags=[ps.BUNDLE_PSST_TO_SECTION_TAG[bundle_id]],
            )
            changed['sections'] = {d.tag: _upsert_plan_section(db, plan.plan_id, d) for d in drafts}
            output_ref = [{'table': 'plan_sections', 'id': v['id']} for v in changed['sections'].values()]

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

            # [2026-09-28 신규, 프론트 2차 요청 A-2] 기획서 5-6절 — 재작성 전후 점수를
            # 비교해 낮아졌으면 이전 상태로 되돌린다("이전 결과는 삭제하지 않고 보존한다").
            # 채점 근거가 아직 없어 재채점 자체가 안 됐으면(verify1_changed가 비어있으면)
            # 비교할 게 없으니 새 콘텐츠를 그냥 둔다.
            version_entry = _decide_version(
                before_snapshot=before_snapshot, before_score=before_doc_score,
                after_score=plan.doc_score, task_key=task_key,
            )
            if version_entry['kept'] == 'previous':
                _restore_plan_doc_state(plan, before_snapshot)
            plan.version_history = (plan.version_history or []) + [version_entry]
            changed['version_kept'] = version_entry['kept']
            changed['version_comparison'] = {
                'before_score': version_entry['before_score'], 'after_score': version_entry['after_score'],
            }

        elif task_key in ('verify1_rubric', 'verify1_evidence'):
            result = _rescore_verify1(db, plan, task_key)
            if result is None:
                raise HTTPException(status_code=404, detail='재채점할 채점 근거(plan_score_reasons)가 없습니다')
            changed.update(result)
            output_ref = {'table': 'business_plans', 'id': plan.plan_id}

        elif task_key in ('implement_prototype', 'implement_infographic'):
            old_artifact = _get_current_artifact(db, plan.plan_id)
            if old_artifact is None:
                raise HTTPException(status_code=404, detail='재시도할 산출물(artifacts)이 없습니다')
            if task_key == 'implement_prototype' and old_artifact.category == 'onepage':
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "category='onepage' 산출물은 설계상 실행 파일(executable_path)이 없어서 "
                        '프로토타입 재시도 대상이 아닙니다 (인포그래픽 재시도만 가능)'
                    ),
                )

            before_artifact_score = old_artifact.artifact_score

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
            written_dest_path = dest_path  # 아래에서 실패하면 except가 이 파일을 지운다.
            new_url = f'/uploads/{stored_name}'

            # [2026-09-29 신규, SB-155] old_artifact는 그대로 두고(버전 보존), 새 버전 행을
            # 만들어 거기에만 새 파일 경로를 반영한다.
            artifact = _clone_artifact_as_new_version(db, old_artifact)
            if task_key == 'implement_prototype':
                changed['executable_path'] = {'before': old_artifact.executable_path, 'after': new_url}
                artifact.executable_path = new_url
            else:
                changed['infographic_path'] = {'before': old_artifact.infographic_path, 'after': new_url}
                artifact.infographic_path = new_url
            output_ref = {'table': 'artifacts', 'id': artifact.artifact_id}

            # [2026-09-18 추가] writing과 같은 이유 — 구현(파일 재생성)에도 검증-2(static+
            # crosscheck) 재채점을 자동으로 붙인다. 채점 근거가 없으면 조용히 건너뛴다.
            verify2_changed = {}
            for verify2_key in ('verify2_static', 'verify2_crosscheck'):
                result = _rescore_verify2(db, plan, artifact, verify2_key)
                if result is not None:
                    verify2_changed[verify2_key] = result
            if verify2_changed:
                changed['verify2_rescore'] = verify2_changed

            # [2026-09-29 신규, SB-155] 재작성 전후 점수를 비교해 새 버전을 채택할지 정한다
            # — 낮아지면 새 행은 그냥 is_current=False로 남고(파일도 안 지움, "이전 결과는
            # 삭제하지 않고 보존한다"), old_artifact가 계속 현재 버전으로 남는다.
            keep_new = _new_version_wins(before_artifact_score, artifact.artifact_score)
            artifact.is_current = keep_new
            if keep_new:
                old_artifact.is_current = False
            changed['version_kept'] = 'new' if keep_new else 'previous'
            changed['version_comparison'] = {
                'before_score': _num(before_artifact_score), 'after_score': _num(artifact.artifact_score),
            }

        elif task_key in ('verify2_static', 'verify2_crosscheck'):
            artifact = _get_current_artifact(db, plan.plan_id)
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
            output_ref = {'table': 'artifacts', 'id': artifact.artifact_id}

        elif task_key == 'review_expression':
            latest = (
                db.query(FormatFinding)
                .filter(FormatFinding.plan_id == plan.plan_id)
                .order_by(FormatFinding.finding_id.desc())
                .first()
            )
            result = agents.run_review_expression_retry(project.description)
            finding_row = FormatFinding(
                plan_id=plan.plan_id,
                finding_type=result.finding_type,
                location=result.location,
                message=result.message,
                severity=result.severity,
            )
            db.add(finding_row)
            db.flush()  # finding_id 확보 — agent_executions.output_ref가 이 행을 참조한다.
            changed['finding'] = {
                'before': latest.message if latest is not None else None,
                'after': result.message,
            }
            output_ref = {'table': 'format_findings', 'id': finding_row.finding_id}

        elif task_key == 'review_token_check':
            latest = (
                db.query(ProofreadLog)
                .filter(ProofreadLog.plan_id == plan.plan_id)
                .order_by(ProofreadLog.log_id.desc())
                .first()
            )
            next_attempt_no = (latest.attempt_no + 1) if latest is not None else 1
            result = agents.run_review_token_check_retry(project.description, attempt_no=next_attempt_no)
            log_row = ProofreadLog(
                plan_id=plan.plan_id,
                # [2026-09-29 신규] 예전엔 이 필드가 아예 빠져있어서 재시도로 만든 행은
                # 전부 section_id=NULL이 됐다 — 프론트 reviewParagraphsFrom(SB-165)이
                # section_id로 시도 이력을 묶는데, 그러면 최초 시드 행(section_id 있음)과
                # 재시도 행(NULL)이 서로 다른 문단으로 갈라져 보였다. original_text와 같은
                # 이유로 이전 행에서 이어받는다.
                section_id=(latest.section_id if latest is not None else None),
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
            )
            db.add(log_row)
            db.flush()  # log_id 확보 — agent_executions.output_ref가 이 행을 참조한다.
            changed['corrected_text'] = {
                'before': latest.corrected_text if latest is not None else None,
                'after': result.corrected_text,
            }
            changed['score'] = {'before': _num(latest.score) if latest is not None else None, 'after': _num(result.score)}
            changed['passed'] = result.passed
            if not result.passed:
                changed['violation_type'] = result.violation_type
                changed['violation_note'] = result.violation_note
            output_ref = {'table': 'proofread_logs', 'id': log_row.log_id}

        else:  # pragma: no cover — _RETRIABLE_TASK_KEYS 체크를 통과했으면 도달할 수 없다.
            raise HTTPException(status_code=500, detail=f'처리 로직이 없는 task_key: {task_key!r}')
    except HTTPException:
        raise
    except Exception as exc:
        # [2026-09-28 신규] 지금은 app.agents의 run_*_retry()가 전부 더미(무작위)라 실패할
        # 일이 없지만, 실제 Agent가 연동된 뒤에는 여기서 예외가 날 수 있다 — 그때도 이
        # 라우터를 다시 손대지 않도록 실패 기록을 미리 준비해둔다(_simulate_generation의
        # 예외 분류 방식과 동일하게 classify_error_kind를 재사용).
        error_kind = ps.classify_error_kind(exc)
        # [2026-09-29 신규] 이 db.rollback()이 빠져있었다 — 그 결과 implement_prototype/
        # infographic 도중(_clone_artifact_as_new_version으로 flush까지 된 새 버전 행이
        # 있는 상태에서) run_verify2_retry 등이 실패하면, 그 flush된 새 행이 롤백되지 않고
        # 아래 db.commit()에 실패 로그와 함께 그대로 같이 커밋돼버렸다(재채점 전 상태로
        # 반쯤 멈춘 행이 DB에 남는 버그). _simulate_generation의 예외 처리와 같은 패턴으로
        # 맞춘다 — 여기서 롤백해야 아래 "고아 파일 삭제"도 실제로 어떤 행도 안 가리키는
        # 파일만 지우는 게 보장된다(안 그러면 방금 커밋된 행이 가리키는 파일을 지워버림).
        db.rollback()
        # 파일은 썼는데 그 뒤(버전 행 생성/재채점)가 실패해 트랜잭션이 롤백되면, 이 파일은
        # 어떤 DB 행도 가리키지 않는 진짜 고아 파일이다 — SB-155가 보존 대상으로 삼는
        # "채택 안 된 버전"과는 다르므로(그건 행이라도 있다) 여기서는 지운다.
        if written_dest_path is not None and os.path.exists(written_dest_path):
            os.remove(written_dest_path)
        db.add(AgentExecution(
            project_id=project_id,
            agent_name=agent_name,
            task_key=body.task_key,
            bundle_id=bundle_id,
            attempt_no=next_attempt_no,
            model_used='dummy-retry',
            rerun_type='rerun',
            token_usage=0,
            status=ps.GENERATION_STATUS_FAILED,
            error_kind=error_kind,
            error_reason=str(exc)[:2000],
        ))
        db.commit()
        raise HTTPException(
            status_code=502,
            detail={'message': '작업 재시도 중 오류가 발생했습니다', 'task_key': body.task_key, 'error_kind': error_kind},
        ) from exc

    execution = AgentExecution(
        project_id=project.project_id,
        agent_name=agent_name,
        task_key=body.task_key,
        bundle_id=bundle_id,
        attempt_no=next_attempt_no,
        model_used='dummy-retry',
        rerun_type='rerun',
        token_usage=random.randint(100, 3000),
        status=ps.GENERATION_STATUS_COMPLETED,
        output_ref=output_ref,
    )
    db.add(execution)
    db.commit()

    return RetryTaskResponse(
        project_id=project.project_id,
        task_key=body.task_key,
        agent_name=agent_name,
        attempt_no=next_attempt_no,
        changed=changed,
    )
