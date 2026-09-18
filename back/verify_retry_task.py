"""POST /projects/{id}/retry-task ("개별 작업 재시도") 검증 — 10개 task_key 전부.

기능정의서 cf. 요구사항: "개별 작업 재시도 시 단순히 동일한 결과를 반환하는 방식이
아닌, 실제 작업을 다시 수행하도록 구현 / 재시도에 따라 결과물이 실제로 변경되는 것을
확인할 수 있도록 구현" — 이 스크립트는 FIXED_TASK_SEQUENCE의 '조율'(오케스트레이션
체크포인트) 4개를 뺀 10개 task_key 전부를 재시도 API로 두 번 이상 연속 호출해서:

  1) 전략/작성(strategy/writing) -> plan_sections 본문이 실제로 달라지는지
  2) 검증-1(verify1_rubric/verify1_evidence) -> plan_score_reasons 점수(+doc_score 합계)가
     실제로 달라지는지, verify1_evidence는 E-V1-EVIDENCE(근거 없는 감점 무효 처리 ->
     만점 복원) 규칙이 실제로 동작하는지까지
  3) 구현(implement_prototype/implement_infographic) -> 산출물 파일 경로(URL)까지 매번
     달라지고, 그 경로에 실제 파일이 새로 생기는지
  4) 검증-2(verify2_static/verify2_crosscheck) -> artifact_score_reasons 중 각자 담당
     item_code 접두어(CHECK-/FEATURE-)만 갈아치우고 나머지는 안 건드리는지
  5) 검수(review_expression/review_token_check) -> format_findings/proofread_logs에
     새 행이 실제로 쌓이는지
  6) agent_executions에 attempt_no가 task_key별로 정확히 쌓이는지(기존 행 덮어쓰지 않음)
  7) 오류 케이스 — 허용 안 된 task_key(400), 매칭/계획서/산출물 없는 상태(404), onepage
     카테고리의 프로토타입 재시도(400, 설계상 executable_path가 없음)
를 전부 assert로 검증한다. 다른 verify_*.py처럼 dev.db를 지우고 새로 만들어서 시작한다.

실행:
    python verify_retry_task.py
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO_ROOT)

_DB_PATH = os.path.join(_REPO_ROOT, 'dev.db')
if os.path.exists(_DB_PATH):
    os.remove(_DB_PATH)  # 이전 실행/다른 스크립트가 남긴 스키마와 섞이지 않도록 항상 새로 만든다

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import app.routers.auth as auth_router  # noqa: E402
import app.security as security  # noqa: E402
from app.database import IS_SQLITE, SessionLocal, init_sqlite_dev_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AgentExecution,
    ArtifactScoreReason,
    FormatFinding,
    MatchResult,
    Notice,
    PlanSection,
    ProofreadLog,
)
from seed_dummy_pipeline import seed_dummy_pipeline  # noqa: E402

assert IS_SQLITE, 'DB_BACKEND=sqlite 가 아니다 — AWS 공유 DB로 보여서 중단.'

init_sqlite_dev_db()

# --- 로그인 monkeypatch (create_test_project.py 등과 동일 패턴) ---------------------
FAKE_EMAIL = 'retry-test@example.com'
fake_sub = f'test-sub-{FAKE_EMAIL}'
security.verify_google_id_token = lambda id_token_str: {
    'sub': fake_sub, 'email': FAKE_EMAIL, 'name': '재시도테스트유저',
}
auth_router.verify_google_id_token = security.verify_google_id_token

client = TestClient(app)

login_res = client.post('/auth/google', json={
    'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True,
})
assert login_res.status_code == 200, f'로그인 실패: {login_res.status_code} {login_res.text}'

payload = {
    'biz_type': 'AI 서비스', 'ceo_name': '재시도테스트유저',
    'description': '재시도 API 검증용 프로젝트',
    'team_members': [], 'pricing_items': [{'service_name': '기본 서비스', 'unit_price': 1000000}],
}
create_res = client.post('/projects', data={'payload': json.dumps(payload)})
assert create_res.status_code == 201, f'프로젝트 생성 실패: {create_res.status_code} {create_res.text}'
project_id = create_res.json()['project_id']
print(f'[준비] project_id={project_id}')

# --- 파이프라인 더미 데이터 채우기 (category='webdev' 기본값 -> executable_path 있음) ---
NOTICE_ID = 'RETRY-TEST-001'

db = SessionLocal()
try:
    notice = Notice(
        notice_id=NOTICE_ID, source='k-startup', title='재시도 테스트용 더미 공고',
        recruitment_status='진행중',
    )
    db.add(notice)
    db.flush()
    # retry_agents=() — 시딩 단계에서 미리 "재시도 흉내" 행을 안 만들게 해서, 10개
    # task_key 전부 동일하게 "초기 실행(attempt_no=1) 다음의 첫 API 재시도는 attempt_no=2"
    # 부터 깨끗하게 검증한다.
    verdict = seed_dummy_pipeline(db, project_id, notice_id=NOTICE_ID, retry_agents=())
    db.commit()
    plan_id = verdict.plan_id
    artifact_id = verdict.artifact_id
    match = db.query(MatchResult).filter(MatchResult.project_id == project_id).one()
    match_id = match.match_id
finally:
    db.close()
print(f'[준비] match_id={match_id} plan_id={plan_id} artifact_id={artifact_id} (category=webdev)')


def retry(task_key: str) -> tuple[int, dict]:
    res = client.post(f'/projects/{project_id}/retry-task', json={'task_key': task_key})
    return res.status_code, res.json()


by_task: dict[str, list[int]] = {}


def _record(task_key: str, body: dict) -> None:
    by_task.setdefault(task_key, []).append(body['attempt_no'])


# ============================================================================
# 1) 전략(strategy) — plan_sections '3-1' 본문이 실제로 달라지는지
# ============================================================================
status1, body1 = retry('strategy')
assert status1 == 200, f'strategy 1차 재시도 실패: {status1} {body1}'
assert body1['attempt_no'] == 2, f'초기 실행(1) 다음인데 attempt_no={body1["attempt_no"]}'
assert body1['agent_name'] == '전략', body1['agent_name']
_record('strategy', body1)
sec_31_after_1 = body1['changed']['sections']['3-1']['after']
sec_31_before_1 = body1['changed']['sections']['3-1']['before']
assert sec_31_before_1 == '더미 본문 — 시장 진입 및 확장 전략을 서술하는 구간입니다.', sec_31_before_1
assert sec_31_after_1 != sec_31_before_1

status1b, body1b = retry('strategy')
assert status1b == 200, f'strategy 2차 재시도 실패: {status1b} {body1b}'
assert body1b['attempt_no'] == 3, body1b['attempt_no']
_record('strategy', body1b)
sec_31_before_2 = body1b['changed']['sections']['3-1']['before']
sec_31_after_2 = body1b['changed']['sections']['3-1']['after']
assert sec_31_before_2 == sec_31_after_1, '2차 재시도의 before가 1차의 after와 달라야 하는데 같음'
assert sec_31_after_2 != sec_31_after_1, '재시도해도 성장 전략 섹션 본문이 그대로다'
db = SessionLocal()
try:
    section = db.query(PlanSection).filter(PlanSection.plan_id == plan_id, PlanSection.tag == '3-1').one()
    assert section.body == sec_31_after_2, 'DB에 실제로 반영이 안 됨(응답값과 DB값이 다름)'
finally:
    db.close()
print('[OK] strategy 재시도: plan_sections[3-1] 본문이 매번 실제로 바뀜(DB 반영 확인, attempt_no 2 -> 3)')

# ============================================================================
# 2) 작성(writing) — plan_sections '1-1'/'2-1' 본문이 실제로 달라지는지
# ============================================================================
status2, body2 = retry('writing')
assert status2 == 200, f'writing 재시도 실패: {status2} {body2}'
assert body2['attempt_no'] == 2, body2['attempt_no']
assert body2['agent_name'] == '작성', body2['agent_name']
_record('writing', body2)
assert set(body2['changed']['sections'].keys()) == {'1-1', '2-1'}
for tag in ('1-1', '2-1'):
    assert body2['changed']['sections'][tag]['after'] != body2['changed']['sections'][tag]['before']
print("[OK] writing 재시도: plan_sections['1-1'/'2-1'] 본문이 둘 다 실제로 바뀜(attempt_no 2)")

# ============================================================================
# 3) 검증-1 · rubric(verify1_rubric) — plan_score_reasons 점수 + doc_score 합계 재계산
# ============================================================================
status3, body3 = retry('verify1_rubric')
assert status3 == 200, f'verify1_rubric 재시도 실패: {status3} {body3}'
assert body3['attempt_no'] == 2, body3['attempt_no']
assert body3['agent_name'] == '검증-1', body3['agent_name']
_record('verify1_rubric', body3)
assert set(body3['changed']['scores'].keys()) == {'PSST-1-1', 'PSST-2-1'}
doc_score_after_3 = body3['changed']['doc_score']['after']
assert body3['changed']['doc_score']['before'] == 58.5, body3['changed']['doc_score']['before']  # seed 기본값

status3b, body3b = retry('verify1_rubric')
assert status3b == 200, f'verify1_rubric 2차 재시도 실패: {status3b} {body3b}'
assert body3b['attempt_no'] == 3, body3b['attempt_no']
_record('verify1_rubric', body3b)
assert body3b['changed']['doc_score']['before'] == doc_score_after_3
assert body3b['changed']['doc_score']['after'] != doc_score_after_3, '재시도해도 doc_score 합계가 그대로다'
print(f"[OK] verify1_rubric 재시도: doc_score {58.5} -> {doc_score_after_3} -> {body3b['changed']['doc_score']['after']}")

# ============================================================================
# 4) 검증-1 · evidence(verify1_evidence) — E-V1-EVIDENCE(근거 없으면 감점 무효 처리 -> 만점
#    복원) 규칙이 실제로 두 경우(근거 있음/없음) 다 발생하는지 반복 호출로 확인
# ============================================================================
saw_evidence_found = False
saw_evidence_restored = False
evidence_attempts: list[int] = []
for _ in range(20):
    status_e, body_e = retry('verify1_evidence')
    assert status_e == 200, f'verify1_evidence 재시도 실패: {status_e} {body_e}'
    evidence_attempts.append(body_e['attempt_no'])
    for _item_code, change in body_e['changed']['scores'].items():
        after = change['after']
        if after['evidence_locator'] is None:
            saw_evidence_restored = True
            # PSST-1-1/PSST-2-1 max_score는 seed 기준 둘 다 10.00 — 만점 복원 확인.
            assert after['score'] == 10.0, f'근거 없음인데 만점(10.0) 복원이 안 됨: {after}'
        else:
            saw_evidence_found = True
    if saw_evidence_found and saw_evidence_restored:
        break
_record('verify1_evidence', {'attempt_no': evidence_attempts[-1]})
by_task['verify1_evidence'] = evidence_attempts
assert saw_evidence_found, '20회 반복해도 "근거 찾음" 케이스가 한 번도 안 나옴(구현 의심)'
assert saw_evidence_restored, (
    '20회 반복해도 E-V1-EVIDENCE(근거 없음 -> 만점 복원) 케이스가 한 번도 안 나옴 — '
    '확률상 이상하거나 규칙이 실제로 동작 안 하는 것'
)
print(f'[OK] verify1_evidence 재시도: {len(evidence_attempts)}회 만에 근거 있음/없음(만점 복원) 두 경우 다 확인')

# ============================================================================
# 5) 구현(implement_prototype) — artifact.executable_path가 매번 실제로 바뀌고 파일도 새로 생김
# ============================================================================
status5, body5 = retry('implement_prototype')
assert status5 == 200, f'implement_prototype 1차 재시도 실패: {status5} {body5}'
assert body5['attempt_no'] == 2, body5['attempt_no']
assert body5['agent_name'] == '구현', body5['agent_name']
_record('implement_prototype', body5)
path_after_1 = body5['changed']['executable_path']['after']
assert path_after_1 is not None and path_after_1.startswith('/uploads/')
file_path_1 = os.path.join(_REPO_ROOT, 'uploads', os.path.basename(path_after_1))
assert os.path.exists(file_path_1), f'재시도로 만들어졌다는 파일이 실제로 없음: {file_path_1}'

status5b, body5b = retry('implement_prototype')
assert status5b == 200, f'implement_prototype 2차 재시도 실패: {status5b} {body5b}'
assert body5b['attempt_no'] == 3, body5b['attempt_no']
_record('implement_prototype', body5b)
path_before_2 = body5b['changed']['executable_path']['before']
path_after_2 = body5b['changed']['executable_path']['after']
assert path_before_2 == path_after_1
assert path_after_2 != path_after_1, f'재시도해도 executable_path가 그대로({path_after_1})다'
file_path_2 = os.path.join(_REPO_ROOT, 'uploads', os.path.basename(path_after_2))
assert os.path.exists(file_path_2), f'2차 재시도 파일이 실제로 없음: {file_path_2}'
assert file_path_1 != file_path_2, '두 번의 재시도가 같은 파일을 가리키고 있음(진짜로 새로 안 만든 것)'
print(f'[OK] implement_prototype 재시도: 매번 새 파일 생성 확인, executable_path {path_after_1} -> {path_after_2}')

# ============================================================================
# 6) 구현(implement_infographic) — infographic_path 변경
# ============================================================================
status6, body6 = retry('implement_infographic')
assert status6 == 200, f'implement_infographic 재시도 실패: {status6} {body6}'
assert body6['attempt_no'] == 2, '구현(프로토타입)과 별개의 attempt_no 계열이어야 함'
_record('implement_infographic', body6)
assert 'infographic_path' in body6['changed']
print(f"[OK] implement_infographic 재시도: infographic_path -> {body6['changed']['infographic_path']['after']}")

# ============================================================================
# 7) 검증-2 · static(verify2_static) — artifact_score_reasons 중 'CHECK-' 접두어만 갈아치움
# ============================================================================
db = SessionLocal()
try:
    feature_before = (
        db.query(ArtifactScoreReason)
        .filter(ArtifactScoreReason.artifact_id == artifact_id, ArtifactScoreReason.item_code == 'FEATURE-MATCH')
        .one()
    )
    feature_score_before_static = feature_before.score
finally:
    db.close()

status7, body7 = retry('verify2_static')
assert status7 == 200, f'verify2_static 재시도 실패: {status7} {body7}'
assert body7['attempt_no'] == 2, body7['attempt_no']
assert body7['agent_name'] == '검증-2', body7['agent_name']
_record('verify2_static', body7)
assert set(body7['changed']['scores'].keys()) == {'CHECK-ENTRY-FILE'}, (
    f"verify2_static이 CHECK- 항목만 건드려야 하는데: {list(body7['changed']['scores'].keys())}"
)
db = SessionLocal()
try:
    feature_after = (
        db.query(ArtifactScoreReason)
        .filter(ArtifactScoreReason.artifact_id == artifact_id, ArtifactScoreReason.item_code == 'FEATURE-MATCH')
        .one()
    )
    assert feature_after.score == feature_score_before_static, (
        'verify2_static이 FEATURE- 항목까지 건드림 — item_code 접두어 필터링이 깨짐'
    )
finally:
    db.close()
print("[OK] verify2_static 재시도: CHECK-ENTRY-FILE만 재채점, FEATURE-MATCH는 안 건드림")

# ============================================================================
# 8) 검증-2 · crosscheck(verify2_crosscheck) — 'FEATURE-' 접두어만 갈아치움
# ============================================================================
db = SessionLocal()
try:
    check_before = (
        db.query(ArtifactScoreReason)
        .filter(ArtifactScoreReason.artifact_id == artifact_id, ArtifactScoreReason.item_code == 'CHECK-ENTRY-FILE')
        .one()
    )
    check_score_before_cross = check_before.score
finally:
    db.close()

status8, body8 = retry('verify2_crosscheck')
assert status8 == 200, f'verify2_crosscheck 재시도 실패: {status8} {body8}'
assert body8['attempt_no'] == 2, body8['attempt_no']
_record('verify2_crosscheck', body8)
assert set(body8['changed']['scores'].keys()) == {'FEATURE-MATCH'}, (
    f"verify2_crosscheck가 FEATURE- 항목만 건드려야 하는데: {list(body8['changed']['scores'].keys())}"
)
db = SessionLocal()
try:
    check_after = (
        db.query(ArtifactScoreReason)
        .filter(ArtifactScoreReason.artifact_id == artifact_id, ArtifactScoreReason.item_code == 'CHECK-ENTRY-FILE')
        .one()
    )
    assert check_after.score == check_score_before_cross, (
        'verify2_crosscheck가 CHECK- 항목까지 건드림 — item_code 접두어 필터링이 깨짐'
    )
finally:
    db.close()
print("[OK] verify2_crosscheck 재시도: FEATURE-MATCH만 재채점, CHECK-ENTRY-FILE은 안 건드림")

# ============================================================================
# 9) 검수 · 표현(review_expression) — format_findings에 새 행이 실제로 쌓이는지
# ============================================================================
db = SessionLocal()
try:
    findings_before = db.query(FormatFinding).filter(FormatFinding.plan_id == plan_id).count()
finally:
    db.close()

status9, body9 = retry('review_expression')
assert status9 == 200, f'review_expression 재시도 실패: {status9} {body9}'
assert body9['attempt_no'] == 2, body9['attempt_no']
assert body9['agent_name'] == '검수', body9['agent_name']
_record('review_expression', body9)
assert body9['changed']['finding']['before'] == '띄어쓰기 오류 2건 발견 (더미)', body9['changed']['finding']['before']
assert body9['changed']['finding']['after'] != body9['changed']['finding']['before']

db = SessionLocal()
try:
    findings_after = db.query(FormatFinding).filter(FormatFinding.plan_id == plan_id).count()
finally:
    db.close()
assert findings_after == findings_before + 1, f'format_findings 행이 안 늘어남: {findings_before} -> {findings_after}'
print(f'[OK] review_expression 재시도: format_findings 새 행 추가 확인({findings_before} -> {findings_after})')

# ============================================================================
# 10) 검수 · 윤문(review_token_check) — proofread_logs에 새 행이 실제로 쌓이는지
# ============================================================================
db = SessionLocal()
try:
    logs_before = db.query(ProofreadLog).filter(ProofreadLog.plan_id == plan_id).count()
finally:
    db.close()

status10, body10 = retry('review_token_check')
assert status10 == 200, f'review_token_check 재시도 실패: {status10} {body10}'
assert body10['attempt_no'] == 2, body10['attempt_no']
_record('review_token_check', body10)
assert body10['changed']['corrected_text']['before'] == (
    '더미 교정문 — 목표 고객이 겪는 문제를 서술하는 구간입니다.'
), body10['changed']['corrected_text']['before']
assert body10['changed']['corrected_text']['after'] != body10['changed']['corrected_text']['before']

db = SessionLocal()
try:
    logs_after = db.query(ProofreadLog).filter(ProofreadLog.plan_id == plan_id).count()
finally:
    db.close()
assert logs_after == logs_before + 1, f'proofread_logs 행이 안 늘어남: {logs_before} -> {logs_after}'
print(f'[OK] review_token_check 재시도: proofread_logs 새 행 추가 확인({logs_before} -> {logs_after})')

# ============================================================================
# 11) agent_executions에 attempt_no가 쌓였는지(기존 행 안 지움) — task_key별로 구분되는지
# ============================================================================
db = SessionLocal()
try:
    execs = (
        db.query(AgentExecution)
        .filter(AgentExecution.match_id == match_id, AgentExecution.rerun_type == 'rerun')
        .order_by(AgentExecution.execution_id)
        .all()
    )
    db_by_task: dict[str, list[int]] = {}
    for e in execs:
        db_by_task.setdefault(e.task_key, []).append(e.attempt_no)
finally:
    db.close()

assert db_by_task.get('strategy') == [2, 3], db_by_task.get('strategy')
assert db_by_task.get('writing') == [2], db_by_task.get('writing')
assert db_by_task.get('verify1_rubric') == [2, 3], db_by_task.get('verify1_rubric')
assert db_by_task.get('verify1_evidence') == evidence_attempts, (
    db_by_task.get('verify1_evidence'), evidence_attempts,
)
assert db_by_task.get('implement_prototype') == [2, 3], db_by_task.get('implement_prototype')
assert db_by_task.get('implement_infographic') == [2], db_by_task.get('implement_infographic')
assert db_by_task.get('verify2_static') == [2], db_by_task.get('verify2_static')
assert db_by_task.get('verify2_crosscheck') == [2], db_by_task.get('verify2_crosscheck')
assert db_by_task.get('review_expression') == [2], db_by_task.get('review_expression')
assert db_by_task.get('review_token_check') == [2], db_by_task.get('review_token_check')
print('[OK] agent_executions 재시도 로그(rerun_type=rerun)가 10개 task_key 전부 정확히 쌓임')

# ============================================================================
# 12) 오류 케이스 — 잘못된 task_key(400, '조율'은 재시도 대상 아님)
# ============================================================================
status_bad, body_bad = retry('coordinate_intake')
assert status_bad == 400, f'재시도 불가능한 task_key인데 400이 아님: {status_bad} {body_bad}'
print(f"[OK] 재시도 불가 task_key('coordinate_intake') -> 400: {body_bad['detail'][:40]}...")

# ============================================================================
# 13) 오류 케이스 — 매칭/계획서 없는 프로젝트(404)
# ============================================================================
FAKE_EMAIL_2 = 'retry-test-2@example.com'
security.verify_google_id_token = lambda id_token_str: {
    'sub': f'test-sub-{FAKE_EMAIL_2}', 'email': FAKE_EMAIL_2, 'name': '재시도테스트유저2',
}
auth_router.verify_google_id_token = security.verify_google_id_token
client.post('/auth/google', json={'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True})
create_res2 = client.post('/projects', data={'payload': json.dumps({
    **payload, 'description': '매칭 없는 프로젝트',
})})
assert create_res2.status_code == 201, f'2번째 계정 프로젝트 생성 실패: {create_res2.status_code} {create_res2.text}'
project_id_2 = create_res2.json()['project_id']
res_nomatch = client.post(f'/projects/{project_id_2}/retry-task', json={'task_key': 'writing'})
assert res_nomatch.status_code == 404, f'매칭 없는데 404가 아님: {res_nomatch.status_code} {res_nomatch.text}'
print(f'[OK] 매칭 없는 프로젝트({project_id_2}) 재시도 -> 404: {res_nomatch.json()["detail"]}')

# ============================================================================
# 14) 오류 케이스 — category='onepage' 산출물의 implement_prototype 재시도(400)
# ============================================================================
db = SessionLocal()
try:
    verdict_onepage = seed_dummy_pipeline(
        db, project_id_2, notice_id=NOTICE_ID, category='onepage',
        log_agent_executions=False,
    )
    db.commit()
finally:
    db.close()
res_onepage = client.post(f'/projects/{project_id_2}/retry-task', json={'task_key': 'implement_prototype'})
assert res_onepage.status_code == 400, f'onepage 프로토타입 재시도인데 400이 아님: {res_onepage.status_code} {res_onepage.text}'
print(f"[OK] onepage 산출물의 implement_prototype 재시도 -> 400: {res_onepage.json()['detail'][:50]}...")
# onepage의 infographic 재시도는 정상 동작해야 한다(인포그래픽은 onepage에도 있음)
res_onepage_info = client.post(f'/projects/{project_id_2}/retry-task', json={'task_key': 'implement_infographic'})
assert res_onepage_info.status_code == 200, (
    f'onepage 산출물의 implement_infographic 재시도가 실패함: {res_onepage_info.status_code} {res_onepage_info.text}'
)
print('[OK] onepage 산출물의 implement_infographic 재시도는 정상 동작(200)')

print()
print('ALL OK — retry-task API(10개 task_key 전부)가 매 호출마다 실제로 값을 바꿔서 반환하는 것까지 전부 확인.')
