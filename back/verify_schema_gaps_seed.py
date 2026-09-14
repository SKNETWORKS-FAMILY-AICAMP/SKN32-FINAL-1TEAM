"""seed_dummy_pipeline.py가 이번에 추가된 6개 스키마 보강 항목을 실제로 더미값으로
채우는지 확인한다 (verify_new_schema_mysql.py가 ORM 매핑 자체를 실제 MySQL에 대고
확인했다면, 이 스크립트는 "우리가 실제로 배포하는 시딩 스크립트가 이 컬럼들을 빠짐없이
채우는가"를 SQLite로 빠르게 확인하는 쪽이다)."""
import os
import sys

# 이 스크립트는 repo 루트(back/, app/ 패키지와 seed_dummy_pipeline.py가 바로
# 옆에 있는 위치)에서 `python verify_schema_gaps_seed.py`로 실행하는 걸 전제로 한다.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO_ROOT)
os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

# dev.db가 예전 스키마로 이미 있으면 create_all()이 기존 테이블을 안 건드리고
# 넘어가버리니 매번 지우고 새로 만든다.
_DEV_DB = os.path.join(_REPO_ROOT, 'dev.db')
if os.path.exists(_DEV_DB):
    os.remove(_DEV_DB)

import app.database as appdb  # noqa: E402
from app.models import (  # noqa: E402
    AgentExecution,
    ArtifactScoreReason,
    Company,
    EligibilityCheck,
    FormatFinding,
    MatchResult,
    Notice,
    PlanScoreReason,
    Project,
    ProofreadLog,
    RubricItem,
    User,
    VerificationPolicy,
    VerificationScoreHistory,
)
from seed_dummy_pipeline import seed_dummy_pipeline  # noqa: E402

appdb.init_sqlite_dev_db()
db = appdb.SessionLocal()

user = User(email='schema-gap-test@example.com', name='갭테스트', google_sub='schema-gap-sub')
db.add(user)
db.commit()
company = Company(user_id=user.user_id, start_type='온라인', biz_type='AI 서비스', ceo_name='갭테스트')
db.add(company)
db.commit()
project = Project(company_id=company.company_id, description='스키마 보강 항목 확인용', notify_region='서울', notify_industry='IT')
db.add(project)
db.commit()
notice = Notice(notice_id='kstartup:GAP_TEST', source='kstartup', title='갭 테스트용 공고', recruitment_status='open')
db.add(notice)
db.commit()

verdict = seed_dummy_pipeline(db, project_id=project.project_id, notice_id=notice.notice_id, log_agent_executions=True)
db.commit()

print('=== seed_dummy_pipeline()이 신규 컬럼/테이블을 채우는지 확인 ===')
all_ok = True


def check(label, cond):
    global all_ok
    all_ok = all_ok and cond
    print(f'[{"OK" if cond else "FAIL"}] {label}')


plan_id = verdict.plan_id
artifact_id = verdict.artifact_id
match_id = db.query(MatchResult).filter(MatchResult.project_id == project.project_id).one().match_id

elig = db.query(EligibilityCheck).filter(EligibilityCheck.match_id == match_id).one()
check('eligibility_checks.undecidable 기본값 False로 채워짐', elig.undecidable is False)

rubric_count = db.query(RubricItem).count()
check('rubric_items가 전역으로 채워짐 (3개)', rubric_count == 3)

reasons = db.query(PlanScoreReason).filter(PlanScoreReason.plan_id == plan_id).all()
check('plan_score_reasons에 item_code/score/evidence_locator 채워짐', all(
    r.item_code is not None and r.score is not None and r.evidence_locator is not None for r in reasons
))

artifact_reasons = db.query(ArtifactScoreReason).filter(ArtifactScoreReason.artifact_id == artifact_id).all()
check('artifact_score_reasons에 item_code/score/evidence_locator 채워짐', all(
    r.item_code is not None and r.score is not None and r.evidence_locator is not None for r in artifact_reasons
))

findings = db.query(FormatFinding).filter(FormatFinding.plan_id == plan_id).all()
check('format_findings(T-P1) 최소 1건 생성', len(findings) >= 1)

proofreads = db.query(ProofreadLog).filter(ProofreadLog.plan_id == plan_id).all()
check('proofread_logs(T-P2) 최소 1건 생성', len(proofreads) >= 1 and proofreads[0].original_text != proofreads[0].corrected_text)

history = db.query(VerificationScoreHistory).filter(VerificationScoreHistory.plan_id == plan_id).all()
check('verification_score_history 2건(doc/code) + policy 스냅샷', (
    len(history) == 2
    and all(h.policy_id is not None and h.applied_pass_threshold is not None for h in history)
))

policy = db.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
check('verification_policies가 없으면 자동 생성됨 (pass_threshold=80)', policy is not None and policy.pass_threshold == 80)

execs = db.query(AgentExecution).filter(AgentExecution.match_id == match_id).all()
implement_execs = [e for e in execs if e.agent_name == '구현']
check('agent_executions에 task_key 채워짐', all(e.task_key is not None for e in execs))
check('같은 agent_name("구현")의 두 Task가 task_key로 구분됨', {e.task_key for e in implement_execs} == {'implement_prototype', 'implement_infographic'})
check('재시도(attempt_no=2)가 두 "구현" Task 각각에 기록됨(기본 retry_agents 포함)', sorted(e.attempt_no for e in implement_execs) == [1, 1, 2, 2])

print()
if all_ok:
    print('결과: seed_dummy_pipeline.py가 6개 항목 전부 실제로 채우는 것 확인.')
else:
    print('결과: FAIL 항목 있음 — 위 로그 확인.')

db.close()
assert all_ok, '신규 스키마 더미 시딩 검증 실패'