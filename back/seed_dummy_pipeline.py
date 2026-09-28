"""이미 만들어진 프로젝트 하나에 매칭→자격판정→사업계획서→산출물→최종판정까지
Agent 파이프라인 전체 결과를 더미 값으로 한 번에 적재한다.

DB_BACKEND=sqlite 일 때만 동작한다 — seed_dummy_notices.py와 같은 이유로, 팀 공유
AWS MySQL에 실수로 가짜 판정 결과를 쌓는 사고를 막기 위해서다.

Agent를 실제로 호출하지 않고, 각 단계가 끝났을 때 남았을 법한 최종 산출물 모양만
흉내 낸다 — 결과 조회 화면 · 이력 화면처럼 "이미 판정까지 끝난 프로젝트"가 있어야
테스트해볼 수 있는 부분을, Agent 파이프라인이 실제로 붙기 전에 먼저 만들어볼 수 있게
하려는 용도다.

준비물: 이 스크립트를 돌리기 전에
  1) python seed_dummy_notices.py       (매칭 대상 공고가 있어야 함)
  2) POST /projects 로 프로젝트를 하나 만들어둘 것 (project_id 필요)

실행:
    python seed_dummy_pipeline.py <project_id>
    python seed_dummy_pipeline.py 1 --category onepage --doc-score 65 --artifact-score 20

여러 번 실행하면 그때마다 새 매칭/계획서/산출물/판정 세트가 하나씩 더 쌓인다
(실제로 재수행 사이클마다 이전 결과를 지우지 않고 이력으로 남기는 것과 같은 모양 —
기능정의서 G-02: "이전 결과는 삭제하지 않고 점수 변화 이력으로 보존한다").
"""
import argparse
import datetime
import decimal
import os
import sys
import uuid

from app import pipeline_stages
from app.database import IS_SQLITE, SessionLocal, init_sqlite_dev_db
from app.models import (
    FIXED_TASK_SEQUENCE,
    AgentExecution,
    Artifact,
    ArtifactScoreReason,
    BusinessPlan,
    Company,
    EligibilityCheck,
    FormatFinding,
    MatchResult,
    Notice,
    PlanScoreReason,
    PlanSection,
    Project,
    ProofreadLog,
    RubricItem,
    Verdict,
    VerificationPolicy,
    VerificationScoreHistory,
)
from app.routers.projects import UPLOAD_DIR  # POST /projects 첨부파일과 같은 /uploads/ 디렉터리를 재사용

# 기능정의서(G-02, R-6)의 Threshold 기본값. models.py의 VerificationPolicy.pass_threshold
# 기본값도 70이었다가 이 숫자와 안 맞는 문제가 있었는데(db_review_response.md 2장 (B)-3
# 참고), 2026-09-13 팀 확정으로 80이 맞는 걸로 정리돼서 models.py/app_schema.sql 쪽
# 기본값도 80으로 맞춰뒀다. 이제 이 두 값은 같은 숫자를 가리킨다.
DEFAULT_THRESHOLD = decimal.Decimal('80.00')

# app/models.py의 Artifact.category 컬럼 주석 기준(onepage/webdev/aiapi, 영문 소문자).
# 기능정의서 쪽 타입 정의는 같은 값을 '원페이지'/'웹개발'/'AI_API'(한글) enum으로 적어놔서
# 표기가 다르다 — 이것도 나중에 한쪽으로 맞춰야 한다.
VALID_CATEGORIES = ('onepage', 'webdev', 'aiapi')
DEFAULT_CATEGORY = 'webdev'

DEFAULT_DOC_SCORE = decimal.Decimal('58.50')  # 0~70
DEFAULT_ARTIFACT_SCORE = decimal.Decimal('24.00')  # 0~30 (합계 82.50 → 기본 Threshold 80 통과)

_DUMMY_INFOGRAPHIC_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="480" height="320">
  <rect width="480" height="320" fill="#eef2ff"/>
  <text x="24" y="48" font-size="22" fill="#1e293b">더미 인포그래픽 (seed_dummy_pipeline.py)</text>
  <text x="24" y="80" font-size="14" fill="#475569">실제 Agent가 생성한 이미지가 아니라, 다운로드 테스트용 더미 파일입니다.</text>
</svg>""".encode()


def _dummy_prototype_html(project_description: str) -> bytes:
    return f"""<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>더미 프로토타입</title></head>
<body>
  <h1>더미 프로토타입 (seed_dummy_pipeline.py)</h1>
  <p>실제 Agent가 생성한 프로토타입이 아니라, 다운로드 테스트용 더미 파일입니다.</p>
  <p>원본 아이디어 설명: {project_description}</p>
</body>
</html>""".encode()


def _write_dummy_file(content: bytes, ext: str) -> str:
    """UPLOAD_DIR(POST /projects 첨부파일과 같은 디렉터리)에 실제 바이트를 파일로 써서,
    /uploads/<이름>으로 실제 다운로드가 되는 URL을 돌려준다. 예전 버전은 이 경로를
    문자열로만 채워놓고 실제 파일은 만들지 않았는데, "산출물 다운로드"를 실제로
    테스트하려면 그 경로에 진짜 파일이 있어야 해서 여기서 직접 디스크에 쓴다."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored_name = f'{uuid.uuid4().hex}{ext}'
    with open(os.path.join(UPLOAD_DIR, stored_name), 'wb') as out:
        out.write(content)
    return f'/uploads/{stored_name}'


def _log_agent_executions(db, match_id: int, retry_agents: tuple[str, ...] = ()) -> None:
    """agent_executions에 고정 Task 14단계(models.py의 FIXED_TASK_SEQUENCE)를 한 번씩
    기록하고, retry_agents에 들어있는 에이전트는 재시도 1회가 더 있었던 것처럼 행을
    하나 더 남긴다 — "개별 작업 재시도" 단계를 실제로 수행하는 API는 아직 없어서,
    재시도가 일어났다는 사실만이라도 이 테이블에 남겨 흐름을 흉내 낸다.

    task_key를 같이 남긴다 — retry_agents가 '구현'이면 FIXED_TASK_SEQUENCE에 '구현'이
    두 번(implement_prototype/implement_infographic) 나오는데, agent_name만 봐서는
    "어느 구현이 재시도됐는지" 구분이 안 됐던 문제(existing_user_resume_test_report.md
    지적)를 여기서 해결한다 — 둘 다 재시도된 것처럼 만들어서 attempt_no로 회차까지
    구분되는 걸 보여준다."""
    for task_key, agent_name in FIXED_TASK_SEQUENCE:
        db.add(AgentExecution(
            match_id=match_id, agent_name=agent_name, task_key=task_key, attempt_no=1,
            model_used='dummy-llm-v1', rerun_type='initial', token_usage=800,
            status=pipeline_stages.GENERATION_STATUS_COMPLETED,
        ))
        if agent_name in retry_agents:
            db.add(AgentExecution(
                match_id=match_id, agent_name=agent_name, task_key=task_key, attempt_no=2,
                model_used='dummy-llm-v1', rerun_type='rerun', token_usage=650,
                status=pipeline_stages.GENERATION_STATUS_COMPLETED,
            ))


# T-V1(문서층 채점)이 참조하는 전역 고정 채점 기준표 더미값 — 실제 값은 기획팀이
# 확정해서 관리자 화면으로 넣게 될 것이고, 지금은 아래 seed_dummy_pipeline()이 만드는
# PlanSection의 section_code(1-1/2-1/3-1)와 1:1로 맞춘 자리만 채워둔다.
_DUMMY_RUBRIC_ITEMS = (
    ('PSST-1-1', '문제인식', '목표 고객이 겪는 문제 정의가 구체적인가', decimal.Decimal('10.00')),
    ('PSST-2-1', '실현가능성', '팀 역량과 실행 계획이 충분히 서술됐는가', decimal.Decimal('10.00')),
    ('PSST-3-1', '성장전략', '시장 진입·확장 전략이 구체적인가', decimal.Decimal('10.00')),
)


def _ensure_rubric_items(db) -> None:
    """rubric_items는 프로젝트마다 새로 만드는 게 아니라 전역 고정값이라(RubricItem
    클래스 주석 참고), 이미 있으면 건너뛰고 없을 때만 한 번 채운다 — seed_dummy_notices.py
    와 같은 "있으면 스킵" 방식이되, commit()은 하지 않는다(flush()만) — 이 함수는
    seed_dummy_pipeline() 안에서 아직 커밋 전인 다른 행들과 같은 트랜잭션 중간에
    호출되므로, 여기서 commit해버리면 "커밋 시점은 호출한 쪽이 정한다"는 이 파일의
    원칙(모듈 docstring 참고)이 깨진다."""
    for item_code, category, criterion, max_score in _DUMMY_RUBRIC_ITEMS:
        if db.query(RubricItem).filter(RubricItem.item_code == item_code).one_or_none() is None:
            db.add(RubricItem(item_code=item_code, category=category, criterion=criterion, max_score=max_score))
    db.flush()


def _ensure_verification_policy(db) -> VerificationPolicy:
    """verification_policies는 "운영 중 정책은 1행만 유지"하는 설계라(app_schema.sql
    주석) app_schema.sql은 MySQL에 이 1행을 부트스트랩 INSERT로 미리 넣어두는데,
    SQLite 로컬 개발 모드(init_sqlite_dev_db())는 테이블만 만들고 행은 안 채운다 —
    admin 라우터가 아직 main.py에 등록 전이라 그 기본값을 넣어줄 API도 없다. 그래서
    이 시딩 스크립트가 직접, 없을 때만 1행을 만든다(모델 기본값 그대로 — pass_threshold
    80 등). _ensure_rubric_items와 같은 이유로 commit()이 아니라 flush()만 한다."""
    policy = db.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
    if policy is None:
        policy = VerificationPolicy()
        db.add(policy)
        db.flush()
    return policy


# ---------------------------------------------------------------------------
# 자격판정 더미 로직 (G-01) — [2026-09-15, 프론트 통합 임시 구현]
# ---------------------------------------------------------------------------
# 예전엔 EligibilityCheck(passed=True)로 무조건 통과만 냈는데, 그러면 EligibilityGate
# 화면의 불통과/미결정 분기를 실제로는 절대 볼 수 없었다(프론트 확인 결과). notices
# 테이블엔 신청자격을 구조화된 컬럼으로 담을 곳이 없어서(target_text가 자유 텍스트
# 설명뿐이라), seed_dummy_notices.py가 만든 6개 공고에 한해 이 표에 신청자격을 흉내낸
# 규칙을 하드코딩해뒀다 — 나중에 공고 수집 파이프라인이 구조화된 자격요건을 내려주게
# 되면 이 표는 통째로 걷어내고 실제 값으로 바꾸면 된다.
#
# applicant_type: '예비창업자'(company.founded_at이 NULL이어야 통과) |
#   '사업자'(founded_at이 있어야 통과, age_limit_years가 있으면 업력도 그 안이어야
#   함) | '제한없음'(항상 통과).
# unverifiable: IntakeForm이 아예 묻지 않는 조건이라 통과/불통과를 정할 수 없는 항목
#   설명 — 다른 구조화 조건이 전부 통과인데 이게 하나라도 있으면 그 공고는
#   "미결정"(undecidable)이 된다.
_DUMMY_ELIGIBILITY_RULES = {
    'kstartup:PBLN_0001': dict(applicant_type='예비창업자', age_limit_years=None, unverifiable=()),
    'kstartup:PBLN_0002': dict(applicant_type='사업자', age_limit_years=3, unverifiable=()),
    'kstartup:PBLN_0003': dict(applicant_type='예비창업자', age_limit_years=None, unverifiable=()),
    'bizinfo:PBLN_1001': dict(
        applicant_type='제한없음', age_limit_years=None,
        unverifiable=('소상공인(매출액·상시근로자 수 기준) 해당 여부',),
    ),
    'bizinfo:PBLN_1002': dict(
        applicant_type='사업자', age_limit_years=None,
        unverifiable=('수출 실적 보유 여부',),
    ),
    'bizinfo:PBLN_1003': dict(
        applicant_type='사업자', age_limit_years=None,
        unverifiable=('비수도권 소재 여부',),
    ),
}


def _years_since(founded_at: datetime.date, today: datetime.date) -> int:
    years = today.year - founded_at.year
    if (today.month, today.day) < (founded_at.month, founded_at.day):
        years -= 1
    return years


def _evaluate_dummy_eligibility(
    company: Company, notice: Notice,
) -> tuple[bool, bool, list[str] | None, list[str] | None]:
    """공고 하나에 대해 회사 프로필(company)이 신청 자격을 충족하는지 더미로 평가한다.
    구조화 조건(신청자유형·업력·접수기간)은 실제로 비교해서 판정하고, IntakeForm이
    아예 묻지 않는 조건(_DUMMY_ELIGIBILITY_RULES의 unverifiable)은 "미결정"으로 뺀다.
    반환값은 EligibilityCheck 컬럼과 그대로 대응한다: (passed, undecidable,
    failed_conditions, missing_inputs)."""
    rule = _DUMMY_ELIGIBILITY_RULES.get(notice.notice_id)
    if rule is None:
        # 표에 없는 공고(수동으로 만든 테스트용 notice 등) — 조건을 모르니 무조건 통과 처리.
        return True, False, None, None

    failed_conditions: list[str] = []
    today = datetime.date.today()

    is_pre_founding = company.founded_at is None
    age_years = None if is_pre_founding else _years_since(company.founded_at, today)

    applicant_type = rule['applicant_type']
    if applicant_type == '예비창업자' and not is_pre_founding:
        failed_conditions.append('신청대상: 예비창업자만 지원 가능 — 설립일자가 입력되어 있어 기업으로 판단됨')
    elif applicant_type == '사업자':
        if is_pre_founding:
            failed_conditions.append('신청대상: 사업자(설립 이력 있는 기업)만 지원 가능 — 예비창업자로 판단됨')
        elif rule['age_limit_years'] is not None and age_years > rule['age_limit_years']:
            failed_conditions.append(
                f"업력 상한: 창업 {rule['age_limit_years']}년 이내만 지원 가능 — 현재 업력 {age_years}년"
            )

    if notice.apply_end is not None and today > notice.apply_end:
        failed_conditions.append(f'접수기간: {notice.apply_end} 마감 — 접수 종료된 공고')

    missing_inputs = list(rule['unverifiable'])

    if failed_conditions:
        return False, False, failed_conditions, (missing_inputs or None)
    if missing_inputs:
        return False, True, None, missing_inputs
    return True, False, None, None


def seed_dummy_pipeline(
    db,
    project_id: int,
    notice_id: str | None = None,
    category: str = DEFAULT_CATEGORY,
    doc_score: decimal.Decimal | str | float = DEFAULT_DOC_SCORE,
    artifact_score: decimal.Decimal | str | float = DEFAULT_ARTIFACT_SCORE,
    threshold: decimal.Decimal | str | float = DEFAULT_THRESHOLD,
    write_real_files: bool = True,
    log_agent_executions: bool = True,
    retry_agents: tuple[str, ...] = ('작성', '구현'),
) -> Verdict:
    """project_id 하나에 대해 파이프라인 전체 결과(매칭 1건 + 그 아래 자격판정 1건 +
    사업계획서 1건(섹션 3개, 채점 근거 2개) + 산출물 1건(채점 근거 2개) + 최종판정 1건)를
    만들어 세션에 add()하고 verdict 객체를 반환한다.

    db.commit()은 이 함수 안에서 하지 않는다 — 호출한 쪽(CLI의 main(), 또는 이 함수를
    가져다 쓰는 다른 코드)이 원하는 시점에 커밋하도록 남겨둔다.

    project_id: 이미 존재하는 projects.project_id (POST /projects로 미리 만들어둬야 함).
    notice_id: 매칭 대상 공고의 notice_id. 생략하면 DB에 있는 공고 중 아무거나 하나를
               고른다(먼저 seed_dummy_notices.py를 실행해 공고가 있어야 함).
    category: 'onepage' | 'webdev' | 'aiapi'. 'onepage'면 실행 파일이 없는 산출물로
              (executable_path=None) 만든다 — 기능정의서 T-B1이 원페이지에서는
              생략된다는 것과 맞춘 것. Project 모델엔 아직 이 값을 저장하는 컬럼이
              없어서(db_review_response.md 2장 참고) 여기서는 인자로만 받는다.
    doc_score / artifact_score / threshold: 더미 점수. 기본값은 둘을 합쳐 82.50점으로
              기본 threshold(80)를 통과하는 값이라 verdict.overall_passed도 기본 True.
    write_real_files: True면 infographic_path/executable_path에 실제 파일을 만들어서
              (/uploads/ 아래, POST /projects 첨부파일과 같은 방식) 진짜로 다운로드
              가능하게 한다. False면 예전처럼 존재하지 않는 경로 문자열만 채운다.
    log_agent_executions: True면 agent_executions에 고정 Task 14단계 실행 로그를 남긴다.
    retry_agents: log_agent_executions=True일 때, 재시도가 있었던 것처럼 행을 하나 더
              남길 에이전트 이름들. 기본값은 ('작성', '구현') — 신규 유저 흐름의
              "보고서 생성 후 개별 재시도" · "프로토타입 생성 후 개별 재시도" 두 단계에
              대응한다.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"category는 {VALID_CATEGORIES} 중 하나여야 합니다: {category!r}")

    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f'project_id={project_id} 인 프로젝트가 없습니다 — 먼저 POST /projects로 만들어두세요')

    if notice_id is None:
        notice = db.query(Notice).first()
        if notice is None:
            raise ValueError('notices 테이블이 비어 있습니다 — 먼저 python seed_dummy_notices.py 를 실행하세요')
        notice_id = notice.notice_id
    else:
        notice = db.query(Notice).filter(Notice.notice_id == notice_id).one_or_none()
        if notice is None:
            raise ValueError(f'notice_id={notice_id!r} 인 공고가 없습니다')

    doc_score = decimal.Decimal(str(doc_score))
    artifact_score = decimal.Decimal(str(artifact_score))
    threshold = decimal.Decimal(str(threshold))
    overall_passed = (doc_score + artifact_score) >= threshold

    # 1) 매칭 — status='completed': 이 더미 결과는 "판정까지 이미 끝난" 상태를 흉내 내는
    #    것이라, 'in_progress'로 두면 동시 실행 제한(backend_decisions.md #11) 체크에
    #    걸려서 이 프로젝트로는 더 이상 새 프로젝트를 못 만드는 부작용이 생긴다.
    #    stage/progress_percent도 같은 이유로 "끝까지 다 돈 상태"인 STAGE_DONE/100으로
    #    채운다 — 이어하기 판별(app/pipeline_stages.py)이 이 프로젝트를 중간 단계로
    #    오인해 엉뚱한 화면으로 돌려보내지 않도록.
    match = MatchResult(
        project_id=project_id,
        notice_id=notice_id,
        fit_score=decimal.Decimal('87.50'),
        reason='더미 매칭 결과 — 실제 임베딩 유사도 계산 없이 임의로 채운 값입니다.',
        status=pipeline_stages.GENERATION_STATUS_COMPLETED,
        stage=pipeline_stages.STAGE_DONE,
        progress_percent=100,
    )
    db.add(match)
    db.flush()  # match.match_id 확보

    # 2) 자격판정 (G-01) — _DUMMY_ELIGIBILITY_RULES(공고별 더미 신청자격)로 회사
    #    프로필(company.founded_at 기준 예비창업자/사업자 판정 + 업력 + 접수기간)을
    #    실제로 비교해서 통과/불통과/미결정 세 갈래로 나눈다. 이전엔 무조건
    #    passed=True로 고정돼 있어서 EligibilityGate의 불통과/미결정 분기를 화면에서
    #    볼 방법이 없었다.
    company = db.get(Company, project.company_id)
    elig_passed, elig_undecidable, elig_failed, elig_missing = _evaluate_dummy_eligibility(company, notice)
    db.add(EligibilityCheck(
        match_id=match.match_id, passed=elig_passed, undecidable=elig_undecidable,
        failed_conditions=elig_failed, missing_inputs=elig_missing,
    ))

    # 3) 사업계획서 (문서층, T-W1~W3 산출물)
    plan = BusinessPlan(match_id=match.match_id, doc_score=doc_score, threshold=threshold)
    db.add(plan)
    db.flush()  # plan.plan_id 확보

    _ensure_rubric_items(db)  # rubric_items(전역 고정값)가 없으면 채워둔다

    # section_code는 기능정의서 FormSpec.sectionCodes 표기('1-1' 등)를 그대로 흉내 냈다.
    # rubric_items의 item_code(PSST-1-1 등)와 맞춰뒀다 — 아래 PlanScoreReason에서 참조.
    sections = {}
    for section_code, title, body in (
        ('1-1', '문제 인식', '더미 본문 — 목표 고객이 겪는 문제를 서술하는 구간입니다.'),
        ('2-1', '실현 가능성', '더미 본문 — 팀 역량과 실행 계획을 서술하는 구간입니다.'),
        ('3-1', '성장 전략', '더미 본문 — 시장 진입 및 확장 전략을 서술하는 구간입니다.'),
    ):
        section = PlanSection(plan_id=plan.plan_id, tag=section_code, title=title, body=body)
        db.add(section)
        db.flush()  # section.section_id 확보 (아래 format_findings에서 참조)
        sections[section_code] = section

    # item_code/score/max_score/evidence_locator — db_review_response.md 2장 (B)-2
    # 대응: rubric_items의 item_code와 맞춘 항목 단위 채점 + 근거 위치.
    for item_code, score, max_score, reason_text, evidence_locator in (
        ('PSST-1-1', decimal.Decimal('10.00'), decimal.Decimal('10.00'),
         '문제 인식 항목: 목표 고객 정의가 구체적이라 만점 처리 (더미 근거)', 'section:1-1 문단 2'),
        ('PSST-2-1', decimal.Decimal('8.00'), decimal.Decimal('10.00'),
         '실현 가능성 항목: 팀 경력 서술이 짧아 2점 감점 (더미 근거)', 'section:2-1 문단 1'),
    ):
        db.add(PlanScoreReason(
            plan_id=plan.plan_id, reason_text=reason_text, item_code=item_code,
            score=score, max_score=max_score, evidence_locator=evidence_locator,
        ))

    # 표현 검수(화면 10, T-P1/T-P2) 더미 — db_review_response.md/existing_user_resume_
    # test_report.md에서 저장할 곳이 없다고 지적했던 부분. T-P1은 지적만(FormatFinding),
    # T-P2는 실제로 고친 전/후 텍스트(ProofreadLog)를 남긴다.
    db.add(FormatFinding(
        plan_id=plan.plan_id, section_id=sections['1-1'].section_id, finding_type='spacing',
        location='section:1-1 문단 1', message='띄어쓰기 오류 2건 발견 (더미)', severity='warning',
    ))
    db.add(ProofreadLog(
        plan_id=plan.plan_id, section_id=sections['1-1'].section_id,
        original_text='더미 원문 — 목표고객이겪는문제를 서술하는 구간입니다.',
        corrected_text='더미 교정문 — 목표 고객이 겪는 문제를 서술하는 구간입니다.',
        reason='띄어쓰기 교정 (더미)',
    ))

    # 4) 산출물 (산출물층, T-B1/T-B2)
    if write_real_files:
        infographic_path = _write_dummy_file(_DUMMY_INFOGRAPHIC_SVG, '.svg')
        executable_path = None if category == 'onepage' else _write_dummy_file(
            _dummy_prototype_html(project.description), '.html'
        )
    else:
        infographic_path = '/uploads/dummy_infographic.svg'
        executable_path = None if category == 'onepage' else '/uploads/dummy_prototype.html'

    artifact = Artifact(
        plan_id=plan.plan_id,
        category=category,
        infographic_path=infographic_path,
        executable_path=executable_path,
        artifact_score=artifact_score,
    )
    db.add(artifact)
    db.flush()  # artifact.artifact_id 확보

    for item_code, score, max_score, reason_text, evidence_locator in (
        ('CHECK-ENTRY-FILE', decimal.Decimal('5.00'), decimal.Decimal('5.00'),
         '코드 검증: 진입 파일 존재 확인 — 통과 (더미 근거)', 'dist/index.html'),
        ('FEATURE-MATCH', decimal.Decimal('5.00'), decimal.Decimal('5.00'),
         '기능 대조: featureList 대비 누락 기능 없음 — 통과 (더미 근거)', 'src/App.tsx'),
    ):
        db.add(ArtifactScoreReason(
            artifact_id=artifact.artifact_id, reason_text=reason_text, item_code=item_code,
            score=score, max_score=max_score, evidence_locator=evidence_locator,
        ))

    # 5) 최종판정 (G-02)
    verdict = Verdict(
        plan_id=plan.plan_id,
        artifact_id=artifact.artifact_id,
        overall_passed=overall_passed,
        model_version='v1',
        first_pass_passed=overall_passed,
    )
    db.add(verdict)
    db.flush()  # verdict.verdict_id 확보

    # 5-1) 검증 이력 (verification_score_history) — db_review_response.md 2장 (B)-3
    #    대응: 판정 당시 정책값(policy_id + 스냅샷)을 같이 남겨야 나중에 정책 기본값이
    #    바뀌어도 "그때 기준으로" 재현할 수 있다. 지금 정책 테이블은 1행만 유지하는
    #    설계라(app_schema.sql 주석) 그 1행을 그대로 읽어서 스냅샷을 뜬다.
    policy = _ensure_verification_policy(db)
    # doc=문서층(계획서 채점), code=산출물층(자동 코드 검증) — 더미라 이 함수가 이미
    # 갖고 있는 doc_score/artifact_score를 그대로 재사용한다. plan(계획서 대조) layer는
    # 별도 점수 산식이 아직 없어서(기능정의서에 상세 미정) 이번엔 만들지 않는다.
    for layer, layer_score, weight in (
        ('doc', doc_score, policy.doc_weight),
        ('code', artifact_score, policy.code_weight),
    ):
        db.add(VerificationScoreHistory(
            plan_id=plan.plan_id, layer=layer, score=layer_score, is_rerun=False,
            policy_id=policy.policy_id, applied_weight=weight,
            applied_pass_threshold=policy.pass_threshold, applied_rerun_cap=policy.rerun_cap,
        ))

    # 6) Agent 실행 로그 (관리자 대시보드 "에이전트 테스크" 탭 대응) — "개별 작업 재시도"
    #    단계를 실제로 수행하는 API가 아직 없어서, 재시도가 있었다는 사실만 로그로 남긴다.
    if log_agent_executions:
        _log_agent_executions(db, match_id=match.match_id, retry_agents=retry_agents)

    return verdict


def main() -> None:
    if not IS_SQLITE:
        print(
            '[seed_dummy_pipeline] DB_BACKEND가 sqlite가 아니다 — 팀 공유 AWS MySQL로 보인다.\n'
            '                      여기에 더미 판정 결과를 쌓으면 안 되니 중단한다.\n'
            '                      .env에 DB_BACKEND=sqlite 를 설정하고 다시 실행하세요.',
            file=sys.stderr,
        )
        raise SystemExit(1)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project_id', type=int, help='이미 POST /projects로 만들어둔 프로젝트의 project_id')
    parser.add_argument('--notice-id', default=None, help='생략하면 DB에 있는 공고 중 아무거나 하나를 쓴다')
    parser.add_argument('--category', default=DEFAULT_CATEGORY, choices=VALID_CATEGORIES)
    parser.add_argument('--doc-score', default=str(DEFAULT_DOC_SCORE), help='문서층 점수 (0~70)')
    parser.add_argument('--artifact-score', default=str(DEFAULT_ARTIFACT_SCORE), help='산출물층 점수 (0~30)')
    parser.add_argument('--threshold', default=str(DEFAULT_THRESHOLD), help='통과 기준 총점')
    parser.add_argument('--no-files', action='store_true', help='실제 파일을 만들지 않고 경로 문자열만 채운다')
    parser.add_argument('--no-agent-log', action='store_true', help='agent_executions 로그를 남기지 않는다')
    args = parser.parse_args()

    init_sqlite_dev_db()  # 테이블이 아직 없으면 만든다 (이미 있으면 아무 일도 안 함)

    db = SessionLocal()
    try:
        verdict = seed_dummy_pipeline(
            db,
            project_id=args.project_id,
            notice_id=args.notice_id,
            category=args.category,
            doc_score=args.doc_score,
            artifact_score=args.artifact_score,
            threshold=args.threshold,
            write_real_files=not args.no_files,
            log_agent_executions=not args.no_agent_log,
        )
        db.commit()
        plan_row = db.get(BusinessPlan, verdict.plan_id)  # Verdict엔 plan 관계가 없어 match_id는 따로 조회
        print(
            f'[seed_dummy_pipeline] project_id={args.project_id} 파이프라인 결과 적재 완료 — '
            f'match_id={plan_row.match_id}, plan_id={verdict.plan_id}, '
            f'artifact_id={verdict.artifact_id}, verdict_id={verdict.verdict_id}, '
            f'overall_passed={verdict.overall_passed}'
        )
    except ValueError as exc:
        db.rollback()
        print(f'[seed_dummy_pipeline] 오류: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        db.close()


if __name__ == '__main__':
    main()