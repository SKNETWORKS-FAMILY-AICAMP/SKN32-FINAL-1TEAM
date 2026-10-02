"""[본인 로컬 MySQL 검증용] SB-59(마이페이지 프로필 저장 API)가 로컬에 이미 떠 있는
MySQL 위에서 실제로 동작하는지 빠르게 확인한다. pytest 스위트(tests/test_profile.py)는
안전을 위해 항상 SQLite로만 돌아가게 막아놔서(tests/conftest.py), 진짜 MySQL 방언
검증은 이렇게 별도 스크립트로 한다 — verify_mysql_backend.py와 같은 패턴.

실행 전제
  1. 로컬 MySQL이 떠 있고, .env에 적어둔 계정(DB_BACKEND=mysql, MYSQL_HOST/PORT/
     USER/PASSWORD/DATABASE)으로 접속 가능해야 한다. 이 스크립트는 .env 값을 그대로
     쓴다(다른 계정으로 강제 덮어쓰지 않음) — 지금 팀원 .env는 127.0.0.1:3306,
     database=s_brain, user=root, password 없음으로 돼 있다.
  2. app_schema.sql이 그 DB에 최신 버전으로 적용돼 있어야 한다(user_profiles 테이블
     포함). 전부 CREATE TABLE IF NOT EXISTS라 이미 만들어둔 다른 테이블은 안 건드리고
     안전하게 재실행할 수 있다:
         mysql -u root s_brain < app_schema.sql
     (비밀번호가 있으면 -p 옵션 추가, Workbench로 파일을 열어 실행해도 된다)

실행:
    .\\venv\\Scripts\\python.exe verify_profile_mysql_local.py     (Windows, PowerShell)
    ./venv/bin/python verify_profile_mysql_local.py                (Git Bash/WSL이면)

주의: verify-profile-a@example.com / verify-profile-b@example.com 이라는 더미 계정을
만들어서 쓴다 — 스크립트 시작할 때 그 이메일의 이전 흔적을 먼저 지우고 시작해서 여러
번 돌려도 계속 깨끗하다. 실제 로그인 계정이나 다른 데이터는 전혀 건드리지 않는다.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tests/ -> back/
sys.path.insert(0, _REPO_ROOT)

# .env의 DB_BACKEND=mysql을 그대로 쓴다(이미 그렇게 돼 있음) — 혹시 셸에 다른 값이 남아
# 있을 경우를 대비해 명시적으로 한 번 더 강제한다. HOST/PORT/USER/PASSWORD/DATABASE는
# 일부러 안 건드린다 — .env(=본인 로컬 MySQL 설정)를 그대로 쓰기 위해서다.
os.environ['DB_BACKEND'] = 'mysql'
os.environ.setdefault('GOOGLE_CLIENT_ID', 'verify-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'verify-dummy-secret-not-for-production')

from fastapi.testclient import TestClient  # noqa: E402

import app.routers.auth as auth_router  # noqa: E402
import app.security as security  # noqa: E402
from app.database import IS_SQLITE, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User, UserProfile  # noqa: E402

if IS_SQLITE:
    print('DB_BACKEND가 mysql이 아닙니다 — .env를 확인하세요.', file=sys.stderr)
    raise SystemExit(1)

DUMMY_EMAILS = ('verify-profile-a@example.com', 'verify-profile-b@example.com')

db = SessionLocal()
dummy_users = db.query(User).filter(User.email.in_(DUMMY_EMAILS)).all()
for u in dummy_users:
    db.query(UserProfile).filter(UserProfile.user_id == u.user_id).delete()
for u in dummy_users:
    db.delete(u)
db.commit()
db.close()

client = TestClient(app)
checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('OK  ' if cond else 'FAIL'), name)


def login(email):
    fake_sub = f'verify-sub-{email}'
    security.verify_google_id_token = lambda t: {'sub': fake_sub, 'email': email, 'name': 'verify유저'}
    auth_router.verify_google_id_token = security.verify_google_id_token
    res = client.post('/auth/google', json={'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True})
    assert res.status_code == 200, res.text
    return res.json()['user']


login(DUMMY_EMAILS[0])

res = client.get('/profile/me')
check('GET 저장 전 -> 200', res.status_code == 200)
check('GET 저장 전 -> basic 전부 빈 값', res.json()['basic']['applicantType'] == '')
check('GET 저장 전 -> bizStatus는 null', res.json()['bizStatus'] is None)

body = {
    'basic': {
        'applicantType': 'individual', 'ceoName': '홍길동', 'birthDate': '1995-04-30', 'gender': '남성',
        'bizNo': '132-05-57431', 'openedAt': '2025-05-12', 'industry': '응용 소프트웨어 개발',
        'startType': 'restart', 'home': {'sido': '대전광역시', 'sigungu': '유성구'},
        'hq': {'sido': '', 'sigungu': ''}, 'hqSameAsHome': True,
        'site': {'sido': '', 'sigungu': ''}, 'hasSeparateSite': False, 'relocationPlanned': False,
        'certs': ['벤처기업'],
    },
    'capability': {'careers': [], 'skills': '', 'soloFounder': True, 'team': [], 'hires': [], 'equipment': [], 'partners': []},
    'history': {'pastBusinesses': [], 'yellowUmbrella': False, 'yellowUmbrellaJoinedAt': ''},
}
res = client.put('/profile/me', json=body)
check('PUT -> 200', res.status_code == 200)
check('PUT 응답에 보낸 값 그대로 반영', res.json()['basic']['ceoName'] == '홍길동')

res = client.get('/profile/me')
check('PUT 후 GET -> 저장한 값 그대로', res.json()['basic']['home']['sido'] == '대전광역시')

db = SessionLocal()
row = db.query(UserProfile).filter(
    UserProfile.user_id == db.query(User).filter(User.email == DUMMY_EMAILS[0]).one().user_id
).one()
check('판정용 컬럼 applicant_type 채워짐', row.applicant_type == 'individual')
check('판정용 컬럼 hq_sido == home_sido (hqSameAsHome=True)', row.hq_sido == '대전광역시')
check('판정용 컬럼 biz_no는 숫자만 10자리', row.biz_no == '1320557431')
db.close()

res = client.put('/profile/me', json=body)
db = SessionLocal()
count = db.query(UserProfile).filter(
    UserProfile.user_id == db.query(User).filter(User.email == DUMMY_EMAILS[0]).one().user_id
).count()
check('PUT 두 번 해도 행은 1개(upsert)', count == 1)
db.close()

login(DUMMY_EMAILS[1])
res = client.get('/profile/me')
check('다른 계정 GET은 서로 안 섞임', res.json()['basic']['ceoName'] == '')
login(DUMMY_EMAILS[0])

res = client.put('/profile/me', json=dict(body, basic=dict(body['basic'], applicantType='xxx')))
check('허용값 밖 applicantType -> 422', res.status_code == 422)

os.environ['NTS_SERVICE_KEY'] = 'verify-dummy-key'
import app.routers.biz_check as biz_check  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


biz_check.requests.post = lambda *a, **k: _FakeResponse(200, {
    'request_cnt': 1, 'match_cnt': 1, 'status_code': 'OK',
    'data': [{'b_no': '1320557431', 'b_stt': '계속사업자', 'b_stt_cd': '01',
              'tax_type': '부가가치세 일반과세자', 'tax_type_cd': '01'}],
})
res = client.post('/biz-check', json={'b_no': '132-05-57431'})
check('biz-check 성공(스텁) -> 200', res.status_code == 200)

res = client.get('/profile/me')
biz_status = res.json()['bizStatus']
check('biz-check 성공 후 GET -> bizStatus 채워짐', biz_status is not None)
check('bizStatus.checkedNo가 하이픈 형식', biz_status is not None and biz_status.get('checkedNo') == '132-05-57431')

res = client.put('/profile/me', json=dict(body, basic=dict(body['basic'], bizNo='999-88-77776')))
check('다른 사업자번호로 PUT -> bizStatus 비워짐', res.json()['bizStatus'] is None)

failed = [n for n, ok in checks if not ok]
print()
print(f'{len(checks) - len(failed)}/{len(checks)} 통과')
if failed:
    print('실패:', failed)
    raise SystemExit(1)
print('모두 통과 — 로컬 MySQL에서 SB-59 정상 동작 확인.')
