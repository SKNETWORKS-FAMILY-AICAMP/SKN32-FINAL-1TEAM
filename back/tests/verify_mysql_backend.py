"""[로컬 MySQL 검증용] SQLite로만 돌려봤던 백엔드를 실제 MySQL(여기서는 로컬
MariaDB — 팀 공유 AWS MySQL이 아니다) 방언 위에서 돌려서, SQLite에선 절대 검증할 수
없는 것들을 확인한다.

특히 _lock_user_for_concurrency_check()의 SELECT ... FOR UPDATE는 SQLite에서는
조용히 no-op이고(SQLite에 FOR UPDATE 구문 자체가 없음), MySQL/InnoDB에서만 실제로
행 잠금이 걸린다 — 즉 "계정당 동시 실행 1건 제한" 기능의 핵심 로직은 지금까지 한
번도 진짜로 검증된 적이 없었다. 이 스크립트가 그걸 처음으로 두 개의 진짜 동시 트랜잭션으로
검증한다.

실행 전제:
  - 로컬 MariaDB가 떠 있고, sbrain_test / sbrain_test_pw 계정으로 sbrain_test
    데이터베이스에 접근 가능해야 한다 (팀 공유 AWS MySQL이 절대 아님).
  - mysql_schema_notices_stub.sql + app_schema.sql이 이미 그 DB에 적용돼 있어야 한다.

실행:
    python verify_mysql_backend.py
"""
import decimal
import json
import os
import sys
import threading
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tests/ -> back/
sys.path.insert(0, _REPO_ROOT)

# .env보다 먼저 실제 환경변수로 박아둔다 (config.py는 이미 os.environ에 있는 키는
# 안 덮어쓰므로, .env의 DB_BACKEND=sqlite보다 이게 우선한다).
os.environ['DB_BACKEND'] = 'mysql'
os.environ['MYSQL_USER'] = 'sbrain_test'
os.environ['MYSQL_PASSWORD'] = 'sbrain_test_pw'
os.environ['MYSQL_HOST'] = '127.0.0.1'
os.environ['MYSQL_PORT'] = '3306'
os.environ['MYSQL_DATABASE'] = 'sbrain_test'
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

import app.security as security  # noqa: E402
from app.database import IS_SQLITE, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, MatchResult, Notice, Project, User  # noqa: E402
from app.routers.projects import _lock_user_for_concurrency_check  # noqa: E402
from seed_dummy_pipeline import seed_dummy_pipeline  # noqa: E402

assert not IS_SQLITE, 'DB_BACKEND=mysql 로 설정했는데 여전히 SQLite로 잡혔다 — config.py 로딩 순서 확인 필요.'

PASS = []
FAIL = []


def check(name, condition, detail=''):
    if condition:
        PASS.append(name)
        print(f'  [PASS] {name}')
    else:
        FAIL.append((name, detail))
        print(f'  [FAIL] {name}  {detail}')


print(f'=== DB: {engine.url.render_as_string(hide_password=True)} ===\n')

# ── 0. 스키마 스모크 — MySQL 방언으로 각 테이블에 실제 쿼리가 나가는지 -------------
print('[0] 스키마 스모크')
db = SessionLocal()
try:
    for model in (User, Company, Project, Notice, MatchResult):
        db.query(model).count()
    check('모든 핵심 테이블에 SELECT 가능 (MySQL 방언 오류 없음)', True)
finally:
    db.close()

# FK 제약이 SQLite와 달리 MySQL에서는 기본적으로 강제된다는 것도 확인
db = SessionLocal()
try:
    bogus = Company(user_id=999_999_999)
    db.add(bogus)
    try:
        db.commit()
        check('존재하지 않는 user_id로 company insert 시 FK 위반으로 막힘', False, '커밋이 성공해버림(FK 미적용 의심)')
    except IntegrityError:
        db.rollback()
        check('존재하지 않는 user_id로 company insert 시 FK 위반으로 막힘', True)
finally:
    db.close()

# ── 1. 동시성 락 — 핵심 검증 ------------------------------------------------------
print('\n[1] 동시 실행 1건 제한 락 (SELECT ... FOR UPDATE, MySQL에서만 의미있음)')

db = SessionLocal()
try:
    test_user = User(
        google_sub='verify-mysql-lock-sub',
        email='verify-mysql-lock@example.com',
        name='락검증유저',
        role='user',
        status='active',
        notify_enabled=False,
        ai_training_agreed=False,
    )
    # 재실행 대비 — 이전 행이 남아있으면 지우고 새로 만든다
    db.query(User).filter(User.google_sub == 'verify-mysql-lock-sub').delete()
    db.commit()
    db.add(test_user)
    db.commit()
    db.refresh(test_user)
    lock_user_id = test_user.user_id
finally:
    db.close()

timeline = []  # (event, monotonic time) — 스레드 안전하게 append만 하므로 락 불필요
timeline_lock = threading.Lock()


def record(event):
    with timeline_lock:
        timeline.append((event, time.monotonic()))


class _FakeCurrentUser:
    """_lock_user_for_concurrency_check(db, current_user)는 current_user.user_id만
    읽으므로, 실제 함수를 그대로 호출하기 위한 최소 스텁."""

    def __init__(self, user_id):
        self.user_id = user_id


_current_user_stub = _FakeCurrentUser(lock_user_id)


def holder_thread():
    """실제 _lock_user_for_concurrency_check()를 그대로 호출해서 행을 잠그고,
    0.8초 동안 붙들고 있다가 커밋한다 — 그 사이 waiter가 같은 행을 잠그려고 하면
    MySQL에서는 반드시 블록돼야 한다."""
    db = SessionLocal()
    try:
        record('holder:begin')
        _lock_user_for_concurrency_check(db, _current_user_stub)
        record('holder:locked')
        time.sleep(0.8)
        user = db.query(User).filter(User.user_id == lock_user_id).first()
        user.name = '락검증유저-holder가수정'
        db.commit()
        record('holder:committed')
    finally:
        db.close()


def waiter_thread():
    """holder가 락을 먼저 잡도록 살짝 늦게 시작해서, 실제 함수로 같은 행에
    FOR UPDATE를 건다. MySQL이라면 holder가 커밋할 때까지 블록되고, waiter:locked
    시각은 holder:committed 이후여야 한다."""
    time.sleep(0.2)  # holder가 확실히 먼저 락을 잡도록
    db = SessionLocal()
    try:
        record('waiter:begin')
        _lock_user_for_concurrency_check(db, _current_user_stub)
        record('waiter:locked')
        db.commit()
    finally:
        db.close()


t1 = threading.Thread(target=holder_thread)
t2 = threading.Thread(target=waiter_thread)
t1.start()
t2.start()
t1.join(timeout=10)
t2.join(timeout=10)

events = dict(timeline)
print('  timeline:', [(e, round(t - timeline[0][1], 3)) for e, t in timeline])

if 'holder:committed' in events and 'waiter:locked' in events:
    # 서로 다른 커넥션의 파이썬 쪽 타임스탬프라 수 ms 정도의 클라이언트 측 지터가
    # 있을 수 있다 (커밋 직후 record() 호출까지의 시간 등) — 50ms 여유를 둔다.
    blocked_correctly = events['waiter:locked'] >= events['holder:committed'] - 0.05
    check(
        '두 번째 트랜잭션이 첫 번째가 커밋할 때까지 블록됨 (FOR UPDATE가 실제로 걸림)',
        blocked_correctly,
        f"waiter:locked={events.get('waiter:locked')} holder:committed={events.get('holder:committed')}",
    )
    gap = events['waiter:locked'] - events['holder:begin']
    check('블록 시간이 holder의 sleep(0.8s)과 얼추 맞음 (진짜 대기였지, 우연한 순서가 아님)', gap >= 0.7, f'gap={gap:.3f}s')
else:
    check('두 스레드 모두 정상 완료', False, f'events={events}')

# 실제로 이름이 holder가 마지막에 쓴 값으로 반영됐는지 (waiter가 stale 값을 덮어쓰지 않았는지)
db = SessionLocal()
try:
    final_user = db.query(User).filter(User.user_id == lock_user_id).first()
    check('최종 값이 holder가 커밋한 값 (레이스로 덮어써지지 않음)', final_user.name == '락검증유저-holder가수정', final_user.name)
finally:
    db.close()

# ── 2. API 레벨 동시 생성 — 실제 엔드포인트 두 번 거의 동시 호출 ------------------
print('\n[2] API 레벨: 동일 계정으로 POST /projects 두 번 거의 동시에 호출')

client = TestClient(app)


def _login_as(db_user_id: int):
    """issue_access_token으로 세션 JWT를 직접 발급해 쿠키에 심는다 — 쿠키 이름은
    security.SESSION_COOKIE_NAME('sbrain_session')과 정확히 맞춰야 한다."""
    token = security.issue_access_token(db_user_id)
    c = TestClient(app)
    c.cookies.set(security.SESSION_COOKIE_NAME, token)
    return c


db = SessionLocal()
try:
    api_user = User(
        google_sub='verify-mysql-api-sub',
        email='verify-mysql-api@example.com',
        name='API동시성검증유저',
        role='user',
        status='active',
        notify_enabled=False,
        ai_training_agreed=True,
    )
    db.query(User).filter(User.google_sub == 'verify-mysql-api-sub').delete()
    db.commit()
    db.add(api_user)
    db.commit()
    db.refresh(api_user)
    api_user_id = api_user.user_id

    notice = db.query(Notice).first()
    if notice is None:
        notice = Notice(
            notice_id='NOTICE-MYSQL-VERIFY-1',
            source='k-startup',
            title='MySQL 검증용 더미 공고',
            recruitment_status='ongoing',
        )
        db.add(notice)
        db.commit()
finally:
    db.close()

results = {}


def create_project(tag):
    c = _login_as(api_user_id)
    payload = {
        'biz_type': 'IT',
        'ceo_name': '테스터',
        'description': 'MySQL 동시 생성 테스트',
        'team_members': [],
        'pricing_items': [],
    }
    resp = c.post('/projects', data={'payload': json.dumps(payload)})
    results[tag] = resp


r1 = threading.Thread(target=create_project, args=('a',))
r2 = threading.Thread(target=create_project, args=('b',))
r1.start()
r2.start()
r1.join(timeout=15)
r2.join(timeout=15)

statuses = {tag: r.status_code for tag, r in results.items()}
print('  결과:', statuses, {tag: r.text[:200] for tag, r in results.items() if r.status_code >= 400})

# 둘 다 성공(201)일 수도 있다 — 락은 "동시에 들어온 두 요청이 서로의 최신 상태를 보게"
# 만드는 것이지, project 자체를 여러 개 못 만들게 막는 게 아니다(그건 in_progress 매칭이
# 있을 때만 409). 핵심은: 두 응답 다 서버 에러(500)가 아니어야 하고, DB에 실제로 만들어진
# project 개수가 성공(201) 응답 개수와 정확히 일치해야 한다(락 덕분에 순차적으로 안전하게
# 처리됐다는 뜻 — 락이 없었다면 이런 카운트 불일치나 500이 발생할 여지가 있다).
no_server_errors = all(code < 500 for code in statuses.values())
check('두 동시 요청 모두 500 없이 처리됨', no_server_errors, str(statuses))

db = SessionLocal()
try:
    created_count = db.query(Project).join(Company, Company.company_id == Project.company_id).filter(
        Company.user_id == api_user_id
    ).count()
    success_count = sum(1 for code in statuses.values() if code == 201)
    check('DB에 실제로 생성된 project 개수 == 201 응답 개수', created_count == success_count, f'created={created_count} success_count={success_count}')
finally:
    db.close()

# ── 3. 기능 스모크 — 파이프라인 시드 + 계획서 문서 생성 (MySQL Decimal/Date/Text 등 방언) --
print('\n[3] 기능 스모크: seed_dummy_pipeline + plan-document.docx 생성 (MySQL 타입 방언)')

db = SessionLocal()
try:
    smoke_user = User(
        google_sub='verify-mysql-smoke-sub',
        email='verify-mysql-smoke@example.com',
        name='기능스모크유저',
        role='user',
        status='active',
        notify_enabled=False,
        ai_training_agreed=True,
    )
    db.query(User).filter(User.google_sub == 'verify-mysql-smoke-sub').delete()
    db.commit()
    db.add(smoke_user)
    db.commit()
    db.refresh(smoke_user)

    company = Company(user_id=smoke_user.user_id, biz_type='IT', ceo_name='테스터')
    db.add(company)
    db.flush()

    project = Project(
        company_id=company.company_id,
        description='MySQL 기능 스모크용 아이템 설명',
    )
    db.add(project)
    db.flush()
    smoke_project_id = project.project_id
    db.commit()
except Exception as exc:  # noqa: BLE001
    check('Project/Company 생성 (Decimal/Date 등 MySQL 컬럼 타입)', False, repr(exc))
    smoke_project_id = None
else:
    check('Project/Company 생성 (Decimal/Date 등 MySQL 컬럼 타입)', True)
finally:
    db.close()

if smoke_project_id is not None:
    db = SessionLocal()
    try:
        verdict = seed_dummy_pipeline(
            db,
            smoke_project_id,
            doc_score=decimal.Decimal('45.00'),
            artifact_score=decimal.Decimal('37.50'),
            threshold=decimal.Decimal('80.00'),
            write_real_files=True,
        )
        db.commit()
        check('seed_dummy_pipeline() 성공 (plan_sections/score_reasons/verdict 등 일괄 insert)', True)
        check('overall_passed 계산 정상 (82.50 >= 80)', bool(verdict.overall_passed))
    except Exception as exc:  # noqa: BLE001
        check('seed_dummy_pipeline() 성공', False, repr(exc))
    finally:
        db.close()

    db = SessionLocal()
    try:
        smoke_user_id = db.query(User).filter(User.google_sub == 'verify-mysql-smoke-sub').one().user_id
    finally:
        db.close()
    c = _login_as(smoke_user_id)
    resp = c.get(f'/projects/{smoke_project_id}/plan-document.docx')
    check(
        'GET /projects/{id}/plan-document.docx 200 + 실제 docx 바이트',
        resp.status_code == 200 and resp.content[:2] == b'PK',
        f'status={resp.status_code} content_type={resp.headers.get("content-type")} len={len(resp.content)}',
    )

# ── 요약 -------------------------------------------------------------------------
print(f'\n=== 결과: {len(PASS)} PASS / {len(FAIL)} FAIL ===')
if FAIL:
    for name, detail in FAIL:
        print(f'  - {name}: {detail}')
    sys.exit(1)
print('모두 통과.')
