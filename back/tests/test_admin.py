"""app/routers/admin.py — pytest 버전 (verify_admin.py를 대체).

원래 verify_admin.py는 스크립트 하나를 위에서 아래로 실행하면서 상태(로그인 세션,
정지시킨 계정 등)를 공유하는 방식이었다. pytest로 옮기면서는 tests/conftest.py의
db_session 픽스처가 테스트 함수마다 DB를 비워주기 때문에, 그 공유를 그대로 가져오면
"어느 테스트가 먼저 실행됐는지"에 결과가 좌우되는 숨은 버그가 생긴다 — 그래서 각
테스트가 필요한 로그인/시딩을 매번 직접 준비하도록 독립적으로 나눴다. 대신 실패했을 때
정확히 어느 엔드포인트/케이스가 깨졌는지 pytest 리포트에서 바로 보인다(기존엔 스크립트가
중간에 assert로 멈추면 그 이후 항목은 아예 실행이 안 돼서 한 번에 하나씩만 알 수 있었음).

실행:
    pytest tests/test_admin.py -v
"""
import datetime
import json

import pytest
from fastapi.testclient import TestClient

import app.routers.auth as auth_router
import app.security as security
from app.models import Faq, Notice, User, VerificationChecklistItem
from seed_dummy_admin_data import main as seed_admin_data_main
from seed_dummy_pipeline import seed_dummy_pipeline

ADMIN_EMAIL = 'admin-test@example.com'
USER_EMAIL = 'plain-user@example.com'


def _new_client() -> TestClient:
    # app.main을 모듈 최상단에서 import하면 안 된다 — app.main은 import되는 순간
    # init_sqlite_dev_db()를 바로 실행해서 테이블을 만드는데, 이게 conftest.py의
    # 세션 스코프 _fresh_test_db 픽스처(테스트 세션 시작 시 test.db를 지우고 새로
    # 만드는)보다 먼저(pytest가 테스트 파일을 수집하는 시점에) 실행돼버리면 "지워진
    # 뒤의 파일"과 "그 전에 만들어진 연결"이 꼬여서 sqlite3.OperationalError: attempt
    # to write a readonly database 같은 알기 어려운 에러가 난다. 그래서 conftest.py의
    # client 픽스처와 똑같이, 실제로 클라이언트가 필요한 시점(테스트 실행 중)에만
    # 함수 안에서 지연 import한다.
    from app.main import app
    return TestClient(app)


def _login(client: TestClient, email: str, name: str) -> None:
    fake_sub = f'test-sub-{email}'
    security.verify_google_id_token = lambda id_token_str: {'sub': fake_sub, 'email': email, 'name': name}
    auth_router.verify_google_id_token = security.verify_google_id_token
    res = client.post('/auth/google', json={'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True})
    assert res.status_code == 200, f'로그인 실패({email}): {res.status_code} {res.text}'


def _create_project(client: TestClient, description: str = 'admin 검증용 프로젝트') -> int:
    payload = {
        'start_type': '온라인', 'biz_type': 'AI 서비스', 'ceo_name': '일반유저테스트',
        'description': description, 'notify_region': '서울', 'notify_industry': 'IT',
        'team_members': [], 'pricing_items': [],
    }
    res = client.post('/projects', data={'payload': json.dumps(payload)})
    assert res.status_code == 201, res.text
    return res.json()['project_id']


@pytest.fixture()
def seeded_admin_data(db_session):
    """verification_policies 초기행 + checklist 8항목 + faq 3건을 채운다.

    seed_dummy_admin_data.main()은 FAQ를 달 유저가 하나도 없으면 더미 유저를 만드는데,
    admin_client/user_client 로그인보다 먼저 이 픽스처를 실행해서(픽스처 의존 순서상
    보장됨) 원래 verify_admin.py와 동일한 순서를 유지한다 — 다만 어느 계정이 FAQ
    소유자가 되는지는 테스트에서 확인하지 않으니 실제로는 순서가 결과에 영향 없다.
    """
    seed_admin_data_main()


@pytest.fixture()
def admin_client(db_session, seeded_admin_data):
    """role='admin' + face_verified_at 까지 채워서 관리자 API를 바로 호출할 수 있는 세션."""
    ac = _new_client()
    _login(ac, ADMIN_EMAIL, '관리자테스트')

    # 관리자 승격 — admin.py 규칙: role='admin' 전환 전에 face_verified_at(얼굴 등록)이
    # 먼저 있어야 한다. API로는 얼굴 등록 엔드포인트가 아직 없어서(다른 팀원 작업 범위)
    # 여기선 DB를 직접 건드려 "이미 얼굴 등록까지 끝낸 관리자"인 것처럼 만든다.
    admin_user = db_session.query(User).filter(User.email == ADMIN_EMAIL).one()
    admin_user.face_verified_at = datetime.datetime.utcnow()
    admin_user.role = 'admin'
    db_session.commit()
    # role은 매 요청 get_current_user에서 DB로 조회하니 재로그인이 꼭 필요하진 않지만,
    # 그 조회 방식이 나중에 JWT에 role을 캐싱하는 식으로 바뀌어도 이 테스트가 계속 맞게
    # 동작하도록 명시적으로 다시 로그인해둔다.
    _login(ac, ADMIN_EMAIL, '관리자테스트')
    return ac


@pytest.fixture()
def user_client(seeded_admin_data):
    """관리자가 아닌 일반 로그인 세션 (프로젝트 생성 등에 사용)."""
    uc = _new_client()
    _login(uc, USER_EMAIL, '일반유저테스트')
    return uc


# ============================================================================
# 정책
# ============================================================================

def test_get_policy_defaults(admin_client):
    res = admin_client.get('/admin/policy')
    assert res.status_code == 200, res.text
    policy = res.json()
    assert policy['pass_threshold'] == 80.0, f'기본 pass_threshold가 80이 아님: {policy}'
    assert policy['token_retry_cap'] == 2, f'기본 token_retry_cap이 2가 아님: {policy}'


def test_put_policy_scores_validates_sum_100(admin_client):
    bad = admin_client.put('/admin/policy/scores', json={'doc_weight': 70, 'code_weight': 20, 'plan_weight': 20})
    assert bad.status_code == 422, f'합 110인데 422가 아님: {bad.status_code} {bad.text}'

    ok = admin_client.put('/admin/policy/scores', json={'doc_weight': 60, 'code_weight': 25, 'plan_weight': 15})
    assert ok.status_code == 200, ok.text
    assert ok.json()['doc_weight'] == 60.0


def test_put_policy_thresholds(admin_client):
    res = admin_client.put(
        '/admin/policy/thresholds',
        json={'pass_threshold': 75, 'rerun_cap': 5, 'deviation_cap': 8, 'token_retry_cap': 4},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['pass_threshold'] == 75.0
    assert body['rerun_cap'] == 5
    assert body['deviation_cap'] == 8.0
    assert body['token_retry_cap'] == 4


# ============================================================================
# 체크리스트
# ============================================================================

def test_get_checklist_seeded_items(admin_client, db_session):
    res = admin_client.get('/admin/checklist')
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 8, f'seed_dummy_admin_data.py가 8항목을 넣었는데 {len(items)}개만 보임'
    enabled_total = sum(i['weight'] for i in items if i['enabled'])
    assert enabled_total == 100, f'enabled 항목 가중치 합이 100이 아님: {enabled_total}'
    # API 응답뿐 아니라 DB 레벨에서도 seed가 중복 없이 정확히 들어갔는지
    assert db_session.query(VerificationChecklistItem).count() == 8


def test_put_checklist_validates_weight_sum_100(admin_client):
    items = admin_client.get('/admin/checklist').json()

    over_body = [{'check_item_id': i['check_item_id'], 'weight': 30, 'enabled': True} for i in items]
    over = admin_client.put('/admin/checklist', json=over_body)
    assert over.status_code == 422, f'합 240인데 422가 아님: {over.status_code} {over.text}'

    ok_body = [{'check_item_id': i['check_item_id'], 'weight': 12.5, 'enabled': True} for i in items]
    ok = admin_client.put('/admin/checklist', json=ok_body)
    assert ok.status_code == 200, ok.text
    assert all(i['weight'] == 12.5 for i in ok.json())


# ============================================================================
# 진행 현황 (/admin/items)
# ============================================================================

def test_get_items_reflects_match_status(admin_client, user_client, db_session):
    project_id = _create_project(user_client)

    res = admin_client.get('/admin/items')
    assert res.status_code == 200, res.text
    matching = [row for row in res.json() if row['project_id'] == project_id]
    assert len(matching) == 1, f'방금 만든 프로젝트가 /admin/items에 안 보임: {res.json()}'
    assert matching[0]['user_name'] == '일반유저테스트'
    assert matching[0]['match_status'] is None, '아직 매칭 전인데 match_status가 비어있지 않음'

    notice = Notice(
        notice_id='ADMIN-TEST-001', source='k-startup', title='admin 검증용 더미 공고', recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-001', retry_agents=())
    db_session.commit()

    res = admin_client.get('/admin/items')
    matched = next(row for row in res.json() if row['project_id'] == project_id)
    assert matched['match_status'] == 'completed', matched


# ============================================================================
# 유저
# ============================================================================

def test_put_users_role_requires_face_verification(admin_client, user_client):
    res = admin_client.get('/admin/users')
    assert res.status_code == 200, res.text
    plain_user = next(u for u in res.json() if u['email'] == USER_EMAIL)

    # face_verified_at 없이 admin 승격 시도 -> 422
    no_face = admin_client.put(f"/admin/users/{plain_user['user_id']}", json={'role': 'admin'})
    assert no_face.status_code == 422, f'얼굴 등록 전인데 관리자 승격이 막히지 않음: {no_face.status_code} {no_face.text}'

    # status 변경은 얼굴 등록과 무관하게 바로 반영돼야 함
    suspend = admin_client.put(f"/admin/users/{plain_user['user_id']}", json={'status': 'suspended'})
    assert suspend.status_code == 200, suspend.text
    assert suspend.json()['status'] == 'suspended'


# ============================================================================
# FAQ
# ============================================================================

def test_get_put_faqs(admin_client, db_session):
    res = admin_client.get('/admin/faqs')
    assert res.status_code == 200, res.text
    faqs = res.json()
    assert len(faqs) == 3, f'seed_dummy_admin_data.py가 3건 넣었는데 {len(faqs)}건만 보임'
    unanswered = [f for f in faqs if f['answer'] is None]
    assert len(unanswered) == 1, f'미답변 FAQ가 정확히 1건이어야 하는데: {unanswered}'

    target_faq_id = unanswered[0]['faq_id']
    answer_res = admin_client.put(f'/admin/faqs/{target_faq_id}', json={
        'answer': '공고 수집 파이프라인이 임베딩 유사도로 자동 매칭합니다.', 'is_visible': True,
    })
    assert answer_res.status_code == 200, answer_res.text
    answered = answer_res.json()
    assert answered['answer'] is not None
    assert answered['is_visible'] is True
    assert answered['answered_at'] is not None

    row = db_session.get(Faq, target_faq_id)
    assert row.answer == answered['answer'], 'DB에 실제로 반영이 안 됨'


# ============================================================================
# 에이전트 실행 로그
# ============================================================================

def test_get_agent_executions(admin_client, user_client, db_session):
    project_id = _create_project(user_client, description='에이전트 로그 검증용 프로젝트')
    notice = Notice(
        notice_id='ADMIN-TEST-002', source='k-startup', title='admin 검증용 더미 공고2', recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-002', retry_agents=())
    db_session.commit()

    res = admin_client.get('/admin/agent-executions')
    assert res.status_code == 200, res.text
    assert len(res.json()) >= 10, f'seed_dummy_pipeline이 남긴 실행 로그가 안 보임: {len(res.json())}건'


# ============================================================================
# 권한 — 403(비관리자) / 401(정지 계정) 구분
# ============================================================================

def test_non_admin_gets_403(seeded_admin_data):
    # 정지된 계정과 섞이면 403/401이 뒤섞여 보이니, 순수하게 "활성 계정인데 관리자가
    # 아님"만 보려고 전용 계정으로 로그인한다 (test_suspended_account_gets_401과 계정을
    # 공유하지 않는 이유).
    plain_client = _new_client()
    _login(plain_client, 'plain-user-2@example.com', '일반유저테스트2')

    for method, path, kwargs in (
        ('get', '/admin/policy', {}),
        ('get', '/admin/checklist', {}),
        ('get', '/admin/items', {}),
        ('get', '/admin/users', {}),
        ('get', '/admin/faqs', {}),
        ('get', '/admin/agent-executions', {}),
    ):
        res = getattr(plain_client, method)(path, **kwargs)
        assert res.status_code == 403, f'일반 유저가 {path} 접근했는데 403이 아님: {res.status_code}'


def test_suspended_account_gets_401(admin_client, user_client):
    # 관리자가 user_client 본인 계정을 정지시킨 뒤, 그 계정 스스로 admin API를 호출하면
    # 403(권한 없음)이 아니라 401(계정 사용 불가)이어야 한다 — require_admin의 권한
    # 체크보다 로그인 유효성 체크가 먼저 걸리는 게 맞는 순서라서, 두 상태가 실제로
    # 구분되는지까지 확인한다.
    res = admin_client.get('/admin/users')
    plain_user = next(u for u in res.json() if u['email'] == USER_EMAIL)
    suspend = admin_client.put(f"/admin/users/{plain_user['user_id']}", json={'status': 'suspended'})
    assert suspend.status_code == 200, suspend.text

    suspended_res = user_client.get('/admin/policy')
    assert suspended_res.status_code == 401, f'정지된 계정인데 401이 아님: {suspended_res.status_code}'
