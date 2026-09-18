"""6개 스키마 보강 항목(ProofreadLog/FormatFinding, RubricItem, eligibility_checks
구조화, plan/artifact_score_reasons 항목별 점수, verification_score_history 스냅샷,
agent_executions task_key/attempt_no)을 실제 MySQL(MariaDB로 로컬 검증)에 대고 직접
INSERT/SELECT 왕복시켜서 확인한다.

지금까지 다른 verify_*.py는 전부 SQLite로만 검증했는데, SQLite는 타입 체크가 느슨해서
app_schema.sql(MySQL 전용 문법 — JSON, COMMENT, ENGINE 등)이 실제로 유효한 SQL인지는
따로 확인한 적이 없었다. 이번엔 로컬 MariaDB에 app_schema.sql을 그대로 적용해두고
(mysql 클라이언트로 먼저 로드), 그 위에서 SQLAlchemy 세션으로 실제 라운드트립까지
확인한다 — SQLite 검증보다 훨씬 강한 보증이다.

사전 준비(이 스크립트가 직접 하지 않음, 미리 해둬야 함):
  mysql -uroot -e "CREATE DATABASE sbrain_test ..."
  mysql -uroot sbrain_test -e "CREATE TABLE notices (...)"  # 공고 수집팀 테이블 스텁
  mysql -uroot sbrain_test < app_schema.sql
  mysql -uroot -e "CREATE USER 'sbrain'@'127.0.0.1' ...; GRANT ...;"
"""
import decimal
import os
import sys

# 이 스크립트는 repo 루트(back/, app/ 패키지가 바로 옆에 있는 위치)에서
# `python verify_new_schema_mysql.py`로 실행하는 걸 전제로 한다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['DB_BACKEND'] = 'mysql'
os.environ['MYSQL_USER'] = 'sbrain'
os.environ['MYSQL_PASSWORD'] = 'sbrain_pw'
os.environ['MYSQL_HOST'] = '127.0.0.1'
os.environ['MYSQL_PORT'] = '3306'
os.environ['MYSQL_DATABASE'] = 'sbrain_test'
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

import app.database as appdb  # noqa: E402
from app.models import (  # noqa: E402
    AgentExecution,
    ArtifactScoreReason,
    Artifact,
    BusinessPlan,
    Company,
    EligibilityCheck,
    FormatFinding,
    MatchResult,
    Notice,
    PlanScoreReason,
    PlanSection,
    ProofreadLog,
    Project,
    RubricItem,
    User,
    Verdict,
    VerificationPolicy,
    VerificationScoreHistory,
)

db = appdb.SessionLocal()

# 매번 재실행 가능하게 이전 테스트 데이터부터 정리
db.query(User).filter(User.email == 'schema-test@example.com').delete()
db.query(Notice).filter(Notice.notice_id == 'kstartup:SCHEMA_TEST').delete()
db.commit()

user = User(email='schema-test@example.com', name='스키마테스트', google_sub='schema-test-sub')
db.add(user)
db.commit()

company = Company(user_id=user.user_id, biz_type='AI 서비스', ceo_name='스키마테스트')
db.add(company)
db.commit()

project = Project(company_id=company.company_id, description='스키마 보강 검증용')
db.add(project)
db.commit()

notice = Notice(notice_id='kstartup:SCHEMA_TEST', source='kstartup', title='스키마 테스트용 공고', recruitment_status='open')
db.add(notice)
db.commit()

match = MatchResult(project_id=project.project_id, notice_id=notice.notice_id, status='completed')
db.add(match)
db.commit()

# 1) eligibility_checks — failed_conditions/missing_inputs(JSON)/undecidable 왕복 확인
elig_reject = EligibilityCheck(
    match_id=match.match_id, passed=False, undecidable=False,
    failed_conditions=['ageMax 초과', 'regionCodes 불일치'],
)
elig_unparsed = EligibilityCheck(
    match_id=match.match_id, passed=False, undecidable=True,
    missing_inputs=['businessAgeMaxYears'],
)
db.add_all([elig_reject, elig_unparsed])
db.commit()

# 2) rubric_items — 전역 채점 기준표
db.query(RubricItem).filter(RubricItem.item_code == 'PSST-1-1').delete()
db.commit()
rubric = RubricItem(item_code='PSST-1-1', category='문제인식', criterion='목표 고객 정의의 구체성', max_score=decimal.Decimal('10.00'))
db.add(rubric)
db.commit()

# 3) business_plans + plan_sections + plan_score_reasons(item_code/score/max_score/evidence_locator)
plan = BusinessPlan(match_id=match.match_id, doc_score=decimal.Decimal('58.50'), threshold=decimal.Decimal('80.00'))
db.add(plan)
db.commit()

section = PlanSection(plan_id=plan.plan_id, tag='1-1', title='문제 인식', body='더미 본문')
db.add(section)
db.commit()

plan_reason = PlanScoreReason(
    plan_id=plan.plan_id, reason_text='목표 고객 정의가 구체적이라 만점 처리',
    item_code='PSST-1-1', score=decimal.Decimal('10.00'), max_score=decimal.Decimal('10.00'),
    evidence_locator='section:1-1 문단 2',
)
db.add(plan_reason)
db.commit()

# 4) format_findings(T-P1) / proofread_logs(T-P2)
finding = FormatFinding(
    plan_id=plan.plan_id, section_id=section.section_id, finding_type='spacing',
    location='section:1-1 문단 2', message='띄어쓰기 오류 3건', severity='warning',
)
db.add(finding)
db.commit()

proofread = ProofreadLog(
    plan_id=plan.plan_id, section_id=section.section_id,
    original_text='더미 원문입니다.', corrected_text='더미 교정문입니다.', reason='어색한 어미 수정',
)
db.add(proofread)
db.commit()

# 5) artifacts + artifact_score_reasons(item_code/score/max_score/evidence_locator)
artifact = Artifact(plan_id=plan.plan_id, category='webdev', infographic_path='/uploads/x.svg', executable_path='/uploads/x.html')
db.add(artifact)
db.commit()

artifact_reason = ArtifactScoreReason(
    artifact_id=artifact.artifact_id, reason_text='기능 대조 통과',
    item_code='FEATURE-LOGIN', score=decimal.Decimal('5.00'), max_score=decimal.Decimal('5.00'),
    evidence_locator='src/routes/login.tsx',
)
db.add(artifact_reason)
db.commit()

verdict = Verdict(plan_id=plan.plan_id, artifact_id=artifact.artifact_id, overall_passed=True, model_version='v1', first_pass_passed=True)
db.add(verdict)
db.commit()

# 6) agent_executions — task_key/attempt_no
exec1 = AgentExecution(
    match_id=match.match_id, agent_name='구현', task_key='implement_prototype', attempt_no=1,
    model_used='dummy-llm-v1', rerun_type='initial', token_usage=800, status='success',
)
exec2 = AgentExecution(
    match_id=match.match_id, agent_name='구현', task_key='implement_prototype', attempt_no=2,
    model_used='dummy-llm-v1', rerun_type='rerun', token_usage=650, status='success',
)
exec3 = AgentExecution(
    match_id=match.match_id, agent_name='구현', task_key='implement_infographic', attempt_no=1,
    model_used='dummy-llm-v1', rerun_type='initial', token_usage=500, status='success',
)
db.add_all([exec1, exec2, exec3])
db.commit()

# 7) verification_score_history — policy_id + 스냅샷 컬럼
policy = db.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()
history = VerificationScoreHistory(
    plan_id=plan.plan_id, layer='doc', score=decimal.Decimal('58.50'), is_rerun=False,
    policy_id=policy.policy_id, applied_weight=policy.doc_weight,
    applied_pass_threshold=policy.pass_threshold, applied_rerun_cap=policy.rerun_cap,
)
db.add(history)
db.commit()

print('=== 실제 MySQL(MariaDB) 라운드트립 검증 ===')
all_ok = True


def check(label, cond):
    global all_ok
    all_ok = all_ok and cond
    print(f'[{"OK" if cond else "FAIL"}] {label}')


db.expire_all()  # 커밋 후 캐시 말고 실제로 DB에서 다시 읽어오게

elig_reject_db = db.get(EligibilityCheck, elig_reject.check_id)
check('failed_conditions JSON 왕복 (리스트 그대로)', elig_reject_db.failed_conditions == ['ageMax 초과', 'regionCodes 불일치'])
check('undecidable=False 왕복', elig_reject_db.undecidable is False)

elig_unparsed_db = db.get(EligibilityCheck, elig_unparsed.check_id)
check('undecidable=True 왕복', elig_unparsed_db.undecidable is True)
check('missing_inputs JSON 왕복', elig_unparsed_db.missing_inputs == ['businessAgeMaxYears'])

rubric_db = db.query(RubricItem).filter(RubricItem.item_code == 'PSST-1-1').one()
check('rubric_items 생성 확인', rubric_db.max_score == decimal.Decimal('10.00'))

plan_reason_db = db.get(PlanScoreReason, plan_reason.reason_id)
check('plan_score_reasons 항목별 점수 왕복', (
    plan_reason_db.item_code == 'PSST-1-1' and plan_reason_db.score == decimal.Decimal('10.00')
    and plan_reason_db.evidence_locator == 'section:1-1 문단 2'
))

finding_db = db.get(FormatFinding, finding.finding_id)
check('format_findings(T-P1) 생성 확인', finding_db.finding_type == 'spacing' and finding_db.section_id == section.section_id)

proofread_db = db.get(ProofreadLog, proofread.log_id)
check('proofread_logs(T-P2) 생성 확인', proofread_db.corrected_text == '더미 교정문입니다.')

artifact_reason_db = db.get(ArtifactScoreReason, artifact_reason.reason_id)
check('artifact_score_reasons 항목별 점수 왕복', artifact_reason_db.evidence_locator == 'src/routes/login.tsx')

execs_db = db.query(AgentExecution).filter(AgentExecution.match_id == match.match_id).order_by(AgentExecution.execution_id).all()
check('agent_executions 3건 생성 확인', len(execs_db) == 3)
check('같은 agent_name("구현")이 task_key로 구분됨', {e.task_key for e in execs_db} == {'implement_prototype', 'implement_infographic'})
check('attempt_no로 재시도 회차 구분됨', [e.attempt_no for e in execs_db if e.task_key == 'implement_prototype'] == [1, 2])

history_db = db.get(VerificationScoreHistory, history.history_id)
check('verification_score_history 정책 스냅샷 왕복', (
    history_db.policy_id == policy.policy_id
    and history_db.applied_pass_threshold == policy.pass_threshold
    and history_db.applied_weight == policy.doc_weight
))

print()
if all_ok:
    print('결과: 6개 항목 전부 실제 MySQL(MariaDB)에서 INSERT/SELECT 라운드트립 정상 확인.')
else:
    print('결과: FAIL 항목 있음 — 위 로그 확인.')

db.close()
assert all_ok, '스키마 보강 검증 실패'