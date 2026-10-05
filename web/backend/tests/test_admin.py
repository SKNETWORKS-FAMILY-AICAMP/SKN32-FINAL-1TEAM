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
from app.models import Faq, ImportRun, Notice, Project, ProofreadLog, User, VerificationChecklistItem
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
    # [2026-09-27 신규, 2026-09-29 ageConfirmed 추가] 필수 동의를 완료해야 POST /projects가
    # 열린다(E-AUTH-CONSENT).
    consent_res = client.patch(
        '/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True},
    )
    assert consent_res.status_code == 200, f'필수 동의 실패({email}): {consent_res.status_code} {consent_res.text}'
    # [2026-09-27 신규] 필수 항목을 채운 마이페이지 프로필이 있어야 POST /projects가
    # 열린다(E-AUTH-PROFILE) — conftest.py의 _MINIMAL_PROFILE_PAYLOAD와 동일한 값.
    profile_res = client.post('/profile', json={
        'basic': {
            'applicantType': 'preliminary', 'ceoName': name, 'birthDate': '1990-01-01',
            'gender': 'male', 'region': {'sido': '서울', 'sigungu': ''}, 'industry': 'IT',
        },
        'capability': {'careers': ['테스트 경력'], 'skills': '백엔드 개발', 'soloFounder': True},
    })
    assert profile_res.status_code == 201, f'프로필 생성 실패({email}): {profile_res.status_code} {profile_res.text}'


def _create_project(client: TestClient, description: str = 'admin 검증용 프로젝트') -> int:
    payload = {
        'biz_type': 'AI 서비스', 'ceo_name': '일반유저테스트',
        'description': description,
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
    """role='admin'으로 만들어 관리자 API를 바로 호출할 수 있는 세션.

    [2026-09-17 개정] 얼굴 인증(face_verified_at) 게이트는 팀 결정으로 완전히 빼기로
    확정됐다(admin.py 참고) — 컬럼 자체도 models.py/app_schema.sql에서 지웠으니 여기서도
    더 이상 채울 대상이 없다."""
    ac = _new_client()
    _login(ac, ADMIN_EMAIL, '관리자테스트')

    admin_user = db_session.query(User).filter(User.email == ADMIN_EMAIL).one()
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
        json={
            'pass_threshold': 75, 'rerun_cap': 5, 'rework_cap': 2, 'deviation_cap': 8,
            'token_retry_cap': 4,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['pass_threshold'] == 75.0
    assert body['rerun_cap'] == 5
    assert body['rework_cap'] == 2
    assert body['deviation_cap'] == 8.0
    assert body['token_retry_cap'] == 4
    assert 'regenerate_cap' not in body  # [SB-245] 없는 기능 — 응답 · 입력에서 뺐다


@pytest.mark.parametrize('field,value', [
    ('pass_threshold', -1), ('pass_threshold', 101),
    ('pass_threshold', ''), ('deviation_cap', -1),
    ('rerun_cap', -1), ('token_retry_cap', 1.5),
])
def test_invalid_thresholds_do_not_change_policy(admin_client, field, value):
    before = admin_client.get('/admin/policy').json()
    payload = {key: before[key] for key in (
        'pass_threshold', 'rerun_cap', 'rework_cap', 'deviation_cap', 'token_retry_cap')}
    payload[field] = value
    response = admin_client.put('/admin/policy/thresholds', json=payload)
    assert response.status_code == 422
    assert admin_client.get('/admin/policy').json() == before


def test_negative_scores_with_valid_total_are_rejected(admin_client):
    before = admin_client.get('/admin/policy').json()
    response = admin_client.put('/admin/policy/scores', json={
        'doc_weight': -10, 'code_weight': 55, 'plan_weight': 55,
    })
    assert response.status_code == 422
    assert admin_client.get('/admin/policy').json() == before


def test_negative_checklist_weight_is_rejected(admin_client):
    before = admin_client.get('/admin/checklist').json()
    payload = [dict(check_item_id=item['check_item_id'], weight=0, enabled=True)
               for item in before]
    payload[0]['weight'] = -10
    payload[1]['weight'] = 55
    payload[2]['weight'] = 55
    response = admin_client.put('/admin/checklist', json=payload)
    assert response.status_code == 422
    assert admin_client.get('/admin/checklist').json() == before


# ============================================================================
# 체크리스트
# ============================================================================

def test_get_checklist_seeded_items(admin_client, db_session):
    """[2026-09-22 구조 교체] v1.8 기준 html/svg 두 카테고리 × 8항목 = 16개, 카테고리별
    합계 15점(전체 합 100점 규칙은 더 이상 아님)."""
    res = admin_client.get('/admin/checklist')
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 16, f'seed_dummy_admin_data.py가 16항목(html/svg 8개씩)을 넣었는데 {len(items)}개만 보임'
    for category in ('html', 'svg'):
        enabled_total = sum(i['weight'] for i in items if i['enabled'] and i['category'] == category)
        assert enabled_total == 15, f'{category} 카테고리 enabled 가중치 합이 15가 아님: {enabled_total}'
    # API 응답뿐 아니라 DB 레벨에서도 seed가 중복 없이 정확히 들어갔는지
    assert db_session.query(VerificationChecklistItem).count() == 16


def test_put_checklist_validates_weight_sum_15_per_category(admin_client):
    """[2026-09-22 구조 교체] 카테고리(html/svg) 하나라도 합이 15가 아니면 거부 — 다른
    카테고리 항목끼리 가중치를 주고받아 전체 합만 맞추는 걸 막는 게 핵심이라, 한쪽
    카테고리만 깨뜨려도 막히는지 확인한다."""
    items = admin_client.get('/admin/checklist').json()

    over_body = [
        {'check_item_id': i['check_item_id'], 'weight': 30 if i['category'] == 'html' else i['weight'], 'enabled': True}
        for i in items
    ]
    over = admin_client.put('/admin/checklist', json=over_body)
    assert over.status_code == 422, f'html 카테고리 합이 240인데 422가 아님: {over.status_code} {over.text}'
    assert 'html' in over.json()['detail']

    # weight는 DECIMAL(5,2)라 15/8(=1.875)처럼 소수점 셋째 자리가 필요한 값은 못 쓴다 —
    # 카테고리(8항목)마다 정수로 합 15가 되는 값(2*7 + 1)을 쓴다.
    ok_body = [
        {'check_item_id': i['check_item_id'], 'weight': 1 if idx % 8 == 7 else 2, 'enabled': True}
        for idx, i in enumerate(items)
    ]
    ok = admin_client.put('/admin/checklist', json=ok_body)
    assert ok.status_code == 200, ok.text
    assert [i['weight'] for i in ok.json()] == [1 if idx % 8 == 7 else 2 for idx in range(len(items))]


# ============================================================================
# 진행 현황 (/admin/items)
# ============================================================================

# ============================================================================
# 생성 실패 관리자 알림 (/admin/generation-alerts)
# ============================================================================

def test_generation_alerts_lists_unacknowledged_by_default(admin_client, user_client, db_session):
    import app.pipeline_stages as ps
    from app.models import GenerationFailureAlert

    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-ALERT-LIST', source='k-startup', title='알림 목록 검증용 더미 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    project = db_session.get(Project, project_id)
    project.notice_id = notice.notice_id
    project.status = 'failed'
    project.stage = ps.STAGE_PLAN_WRITING
    project.progress_percent = 70
    project.resume_count = 6
    db_session.flush()
    unacked = GenerationFailureAlert(
        project_id=project_id, stage=ps.STAGE_PLAN_WRITING,
        resume_count=5, last_error_kind=ps.ERROR_KIND_TRANSIENT, failure_reason='미확인 실패(테스트)',
    )
    acked = GenerationFailureAlert(
        project_id=project_id, stage=ps.STAGE_PLAN_WRITING,
        resume_count=5, last_error_kind=ps.ERROR_KIND_TRANSIENT,
        failure_reason='이미 확인한 실패(테스트)', acknowledged_at=datetime.datetime.utcnow(),
    )
    db_session.add_all([unacked, acked])
    db_session.commit()

    res = admin_client.get('/admin/generation-alerts')
    assert res.status_code == 200, res.text
    ids = {row['alert_id'] for row in res.json()}
    assert unacked.alert_id in ids
    assert acked.alert_id not in ids, '기본값은 미확인만 보여줘야 함'

    res_all = admin_client.get('/admin/generation-alerts', params={'include_acknowledged': True})
    ids_all = {row['alert_id'] for row in res_all.json()}
    assert {unacked.alert_id, acked.alert_id} <= ids_all


def test_ack_generation_alert_toggles_acknowledged_at(admin_client, user_client, db_session):
    import app.pipeline_stages as ps
    from app.models import GenerationFailureAlert

    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-ALERT-ACK', source='k-startup', title='알림 확인 처리 검증용 더미 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    project = db_session.get(Project, project_id)
    project.notice_id = notice.notice_id
    project.status = 'failed'
    project.stage = ps.STAGE_PLAN_WRITING
    project.progress_percent = 70
    project.resume_count = 6
    db_session.flush()
    alert = GenerationFailureAlert(
        project_id=project_id, stage=ps.STAGE_PLAN_WRITING,
        resume_count=5, last_error_kind=ps.ERROR_KIND_TRANSIENT, failure_reason='확인 처리 대상(테스트)',
    )
    db_session.add(alert)
    db_session.commit()

    res = admin_client.put(f'/admin/generation-alerts/{alert.alert_id}/ack', json={'acknowledged': True})
    assert res.status_code == 200, res.text
    assert res.json()['acknowledged_at'] is not None

    res = admin_client.put(f'/admin/generation-alerts/{alert.alert_id}/ack', json={'acknowledged': False})
    assert res.status_code == 200, res.text
    assert res.json()['acknowledged_at'] is None


# ============================================================================
# 공고 관리 (/admin/notices)
# ============================================================================

def test_get_notices_lists_and_filters_by_title(admin_client, db_session):
    db_session.add_all([
        Notice(notice_id='NOTICE-A', source='kstartup', title='동네 헬스장 대상 지원사업', recruitment_status='open'),
        Notice(notice_id='NOTICE-B', source='bizinfo', title='전혀 다른 제조업 공고', recruitment_status='closed'),
    ])
    db_session.commit()

    res = admin_client.get('/admin/notices')
    assert res.status_code == 200, res.text
    ids = {r['notice_id'] for r in res.json()}
    assert {'NOTICE-A', 'NOTICE-B'} <= ids
    row_a = next(r for r in res.json() if r['notice_id'] == 'NOTICE-A')
    assert row_a['has_embedding'] is False, '아직 embedding 컬럼을 안 채웠는데 True로 나옴'

    res = admin_client.get('/admin/notices', params={'q': '헬스장'})
    assert res.status_code == 200, res.text
    filtered = res.json()
    assert len(filtered) == 1 and filtered[0]['notice_id'] == 'NOTICE-A'


def test_get_notices_reports_has_embedding(admin_client, db_session):
    db_session.add(Notice(
        notice_id='NOTICE-EMBED', source='kstartup', title='임베딩 있는 공고',
        recruitment_status='open', embedding=b'\x00' * 4096,
    ))
    db_session.commit()

    res = admin_client.get('/admin/notices', params={'q': '임베딩 있는'})
    assert res.status_code == 200, res.text
    assert res.json()[0]['has_embedding'] is True


# ============================================================================
# 공고 수집 현황 (/admin/collection-status)
# ============================================================================

def test_get_collection_status_aggregates_by_source(admin_client, db_session):
    db_session.add_all([
        Notice(notice_id='COLL-K1', source='kstartup', title='K-Startup 공고 1', recruitment_status='open', embedding=b'\x00' * 4096),
        Notice(notice_id='COLL-K2', source='kstartup', title='K-Startup 공고 2', recruitment_status='open'),
        Notice(notice_id='COLL-B1', source='bizinfo', title='기업마당 공고 1', recruitment_status='open', embedding=b'\x00' * 4096),
    ])
    db_session.add(ImportRun(
        run_id='RUN-TEST-1', input_sha256='x' * 64,
        generated_at=datetime.datetime(2026, 9, 18, 0, 0, 0),
        imported_at=datetime.datetime(2026, 9, 18, 0, 0, 5), notice_count=3,
        report={'summary': {'accepted_count': 3, 'input_counts': {'kstartup': 2, 'bizinfo': 1}, 'issue_counts': {'unparsed_period': 1}}},
    ))
    db_session.commit()

    res = admin_client.get('/admin/collection-status')
    assert res.status_code == 200, res.text
    body = res.json()
    by_source = {s['source']: s for s in body['sources']}
    assert by_source['kstartup']['total_count'] == 2
    assert by_source['kstartup']['embedded_count'] == 1
    assert by_source['kstartup']['label'] == 'K-Startup'
    assert by_source['kstartup']['latest_run_input_count'] == 2
    assert by_source['bizinfo']['total_count'] == 1
    assert by_source['bizinfo']['embedded_count'] == 1
    assert by_source['bizinfo']['label'] == '기업마당'

    assert len(body['recent_runs']) == 1
    run = body['recent_runs'][0]
    assert run['run_id'] == 'RUN-TEST-1'
    assert run['generated_at'] == '2026-09-18T00:00:00'
    assert run['imported_at'] == '2026-09-18T00:00:05'
    assert run['accepted_count'] == 3
    assert run['input_counts'] == {'kstartup': 2, 'bizinfo': 1}
    assert run['issue_counts'] == {'unparsed_period': 1}


def test_get_collection_status_empty_when_no_notices(admin_client):
    res = admin_client.get('/admin/collection-status')
    assert res.status_code == 200, res.text
    assert res.json() == {'sources': [], 'recent_runs': []}


# ============================================================================
# 에이전트 테스크 — Task별 보기 (/admin/agent-tasks)
# ============================================================================

# ============================================================================
# 에이전트 테스크 — 운영 지표 요약 (/admin/agent-ops-summary)
# ============================================================================

# ============================================================================
# 운영 현황 (/admin/ops-summary)
# ============================================================================

# ============================================================================
# 검수 회수 문단 (/admin/recovery-items)
# ============================================================================

def test_get_recovery_items_lists_only_failed_attempts(admin_client, user_client, db_session):
    project_id = _create_project(user_client, description='회수 문단 검증용 프로젝트')
    notice = Notice(
        notice_id='ADMIN-TEST-RECOVERY', source='k-startup', title='회수 문단 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-RECOVERY', retry_agents=())
    db_session.add(ProofreadLog(
        plan_id=verdict.plan_id, original_text='2026년 10월 16일 마감', corrected_text='10월 중순 마감',
        attempt_no=2, passed=False, violation_type='날짜', violation_note='날짜 표기 훼손', recovery_status='pending',
    ))
    db_session.commit()

    res = admin_client.get('/admin/recovery-items')
    assert res.status_code == 200, res.text
    items = res.json()
    # seed가 만든 passed=True 1건은 안 보이고, 방금 추가한 passed=False 1건만 보여야 한다.
    assert len(items) == 1
    item = items[0]
    assert item['project_id'] == project_id
    assert item['project_description'] == '회수 문단 검증용 프로젝트'
    assert item['violation_type'] == '날짜'
    assert item['original'] == '2026년 10월 16일 마감'
    assert item['attempt'] == '10월 중순 마감'
    assert item['recovery_status'] == 'pending'
    assert item['model_version'] == 'v1'  # seed_dummy_pipeline의 Verdict.model_version 기본값
    assert item['consent'] is True  # _login 헬퍼가 aiTrainingAgreed=True로 로그인시킴


def test_put_recovery_item_updates_status_and_label(admin_client, user_client, db_session):
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-RECOVERY-PUT', source='k-startup', title='회수 라벨링 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-RECOVERY-PUT', retry_agents=())
    failed = ProofreadLog(
        plan_id=verdict.plan_id, original_text='원문', corrected_text='반려안',
        attempt_no=2, passed=False, violation_type='기능명', recovery_status='pending',
    )
    db_session.add(failed)
    db_session.commit()
    db_session.refresh(failed)

    res = admin_client.put(f'/admin/recovery-items/{failed.log_id}', json={'recovery_status': 'labeled', 'label': '정답 문장'})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['recovery_status'] == 'labeled'
    assert body['label'] == '정답 문장'


def test_put_recovery_item_on_passed_attempt_returns_404(admin_client, user_client, db_session):
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-RECOVERY-PASSED', source='k-startup', title='통과 시도 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-RECOVERY-PASSED', retry_agents=())
    passed_log = db_session.query(ProofreadLog).filter(ProofreadLog.plan_id == verdict.plan_id).one()

    res = admin_client.put(f'/admin/recovery-items/{passed_log.log_id}', json={'recovery_status': 'labeled'})
    assert res.status_code == 404, res.text


def test_put_recovery_item_invalid_status_returns_422(admin_client, user_client, db_session):
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-RECOVERY-422', source='k-startup', title='잘못된 상태값 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-RECOVERY-422', retry_agents=())
    failed = ProofreadLog(
        plan_id=verdict.plan_id, original_text='원문', corrected_text='반려안',
        attempt_no=2, passed=False, recovery_status='pending',
    )
    db_session.add(failed)
    db_session.commit()
    db_session.refresh(failed)

    res = admin_client.put(f'/admin/recovery-items/{failed.log_id}', json={'recovery_status': 'approved'})
    assert res.status_code == 422, res.text


# ============================================================================
# 유저
# ============================================================================

def test_put_users_role_and_status(admin_client, user_client):
    """[2026-09-17 개정] 얼굴 인증(face_verified_at) 게이트는 팀 결정으로 완전히 빼기로
    확정됐다 — 로직뿐 아니라 컬럼 자체도 models.py/app_schema.sql에서 지웠다(AWS 공유
    DB엔 아직 이 스키마가 올라가지 않은 시점이라 컬럼 삭제도 바로 반영). 예전엔 이 테스트가
    "얼굴 등록 전이면 admin 승격이 422로 막혀야 한다"를 검증했는데, 그 개념 자체가 없어졌으니
    이제는 단순히 role/status 변경이 정상 반영되는지만 검증한다."""
    res = admin_client.get('/admin/users')
    assert res.status_code == 200, res.text
    plain_user = next(u for u in res.json() if u['email'] == USER_EMAIL)

    promote = admin_client.put(f"/admin/users/{plain_user['user_id']}", json={'role': 'admin'})
    assert promote.status_code == 200, promote.text
    assert promote.json()['role'] == 'admin'

    suspend = admin_client.put(f"/admin/users/{plain_user['user_id']}", json={'status': 'suspended'})
    assert suspend.status_code == 200, suspend.text
    assert suspend.json()['status'] == 'suspended'


def test_put_users_cannot_drop_own_admin_role(admin_client):
    """[2026-09-23] 관리자가 이 화면에서 자기 권한을 내려 관리자 화면에 못 들어가는 사고가
    실제로 났다 — 되돌리는 것도 이 화면에서만 되므로 DB를 직접 고쳐야 복구된다. role 해제와
    status 비활성화 둘 다 같은 결과(접근 상실)라 둘 다 막힌다."""
    res = admin_client.get('/admin/users')
    assert res.status_code == 200, res.text
    me = next(u for u in res.json() if u['email'] == ADMIN_EMAIL)

    demote = admin_client.put(f"/admin/users/{me['user_id']}", json={'role': 'user'})
    assert demote.status_code == 422, demote.text
    assert '자기 자신' in demote.json()['detail']

    suspend = admin_client.put(f"/admin/users/{me['user_id']}", json={'status': 'suspended'})
    assert suspend.status_code == 422, suspend.text

    # 막혔으면 DB도 그대로여야 한다 — 검증만 하고 롤백되지 않으면 의미가 없다.
    after = admin_client.get('/admin/users')
    still_me = next(u for u in after.json() if u['email'] == ADMIN_EMAIL)
    assert still_me['role'] == 'admin' and still_me['status'] == 'active'


def test_put_users_can_still_demote_another_admin(admin_client, user_client):
    """가드는 "자기 자신"에만 걸린다 — 다른 관리자를 강등하는 정상 운영은 그대로 된다.
    호출자 본인이 활성 관리자로 남으므로 이 경로로는 관리자가 0명이 될 수 없다."""
    res = admin_client.get('/admin/users')
    plain_user = next(u for u in res.json() if u['email'] == USER_EMAIL)

    promote = admin_client.put(f"/admin/users/{plain_user['user_id']}", json={'role': 'admin'})
    assert promote.status_code == 200, promote.text

    demote = admin_client.put(f"/admin/users/{plain_user['user_id']}", json={'role': 'user'})
    assert demote.status_code == 200, demote.text
    assert demote.json()['role'] == 'user'


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


# ============================================================================
# [SB-245] 오케스트레이터 경유 관리자 조회 — 진행 현황 · 이력보기 · 에이전트 테스크 · 운영 현황
# ============================================================================
from types import SimpleNamespace as NS  # noqa: E402

from orch_fakes import (  # noqa: E402
    ProjectView,
    make_admin_agent_task,
    make_admin_execution,
    make_admin_run,
    make_admin_score_history,
    make_admin_summary,
    make_run,
    make_score_entry,
    make_tokens,
)

from app.orch import OrchError  # noqa: E402


def _items(admin_client):
    res = admin_client.get('/admin/items')
    assert res.status_code == 200, res.text
    return {row['project_id']: row for row in res.json()}


def test_items_without_run_are_before_matching(admin_client, user_client):
    project_id = _create_project(user_client)

    row = _items(admin_client)[project_id]

    assert row['status_label'] == '공고 매칭 전'
    assert row['user_name'] == '일반유저테스트'
    assert row['match_status'] is None and row['step'] is None and row['score'] is None
    assert row['archived'] is False and row['stalled'] is False


def test_items_reflect_orchestrator_run(admin_client, user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['admin_runs'] = lambda **kw: [make_admin_run(
        project_id, step='결과물', progress='완료', agent='검수', attempt=2, doc_score=50.0, artifact_score=30.0,
        total_score=82.5, resume_count=1, last_error_kind='일시')]

    row = _items(admin_client)[project_id]

    assert row['match_status'] == 'completed' and row['status_label'] == '완료' and row['stage'] == 'done'
    assert row['step'] == '검수' and row['attempts'] == 2
    assert row['score'] == pytest.approx(82.5)
    assert row['generation_resume_count'] == 1 and row['generation_last_error_kind'] == '일시'
    assert row['last_updated'].endswith('Z') or row['last_updated'].endswith('+00:00')  # 시간대가 붙는다


def test_items_status_labels_by_progress(admin_client, user_client, orch):
    project_id = _create_project(user_client)
    for progress, label in [('실행', '진행중'), ('재개대기', '진행중'), ('사용자대기', '판단 대기'),
                            ('실패', '실패'), ('완료', '완료'), ('중단', '중단')]:
        orch.responses['admin_runs'] = lambda progress=progress, **kw: [make_admin_run(project_id, progress=progress)]
        assert _items(admin_client)[project_id]['status_label'] == label, progress


def test_items_failed_run_shows_failure_reason_to_admin(admin_client, user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['admin_runs'] = lambda **kw: [make_admin_run(
        project_id, progress='실패', resume_count=5, last_error_kind='일시', failure_reason='작성: 재개상한초과 — 시간 초과')]

    row = _items(admin_client)[project_id]

    assert row['status_label'] == '실패'
    assert row['failure_reason'] == '작성: 재개상한초과 — 시간 초과'
    assert row['generation_failure_reason'] == '작성: 재개상한초과 — 시간 초과'
    assert row['generation_resume_count'] == 5


def test_items_stalled_after_48_hours_without_update(admin_client, user_client, orch):
    """시간대 있는 updatedAt과 웹의 현재 시각을 비교해도 TypeError가 나지 않고, 48시간 넘게 '진행중'이면 정체다."""
    project_id = _create_project(user_client)
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=49)
    fresh = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    orch.responses['admin_runs'] = lambda **kw: [make_admin_run(project_id, progress='실행', updated_at=old)]
    assert _items(admin_client)[project_id]['stalled'] is True
    orch.responses['admin_runs'] = lambda **kw: [make_admin_run(project_id, progress='실행', updated_at=fresh)]
    assert _items(admin_client)[project_id]['stalled'] is False
    orch.responses['admin_runs'] = lambda **kw: [make_admin_run(project_id, progress='완료', updated_at=old)]
    assert _items(admin_client)[project_id]['stalled'] is False  # 끝난 것은 정체가 아니다


def test_items_outside_admin_range_falls_back_to_run_view(admin_client, user_client, orch):
    """마지막 활동이 12개월을 넘어 admin_runs에 없는 실행 건도 '공고 매칭 전'으로 잘못 보이지 않는다."""
    project_id = _create_project(user_client)
    orch.responses['project_views'] = lambda ids: [
        ProjectView(str(i), run=make_run(step='결과물', progress='완료')) for i in ids]

    row = _items(admin_client)[project_id]

    assert row['status_label'] == '완료' and row['stage'] == 'done'
    assert row['score'] is None and row['step'] is None  # 점수 · Agent는 범위 밖이라 없다


def test_items_page_through_all_admin_runs(admin_client, user_client, orch):
    project_id = _create_project(user_client)
    pages = []

    def admin_runs(limit, offset):
        pages.append((limit, offset))
        if offset == 0:
            return [make_admin_run(900000 + i) for i in range(limit)]  # 웹에 없는 프로젝트(지워진 것 등)는 무시된다
        return [make_admin_run(project_id, progress='완료')]

    orch.responses['admin_runs'] = admin_runs

    assert _items(admin_client)[project_id]['status_label'] == '완료'
    assert pages == [(200, 0), (200, 200)]


def test_archive_item_uses_run_existence_not_notice(admin_client, user_client, db_session, orch):
    project_id = _create_project(user_client)
    # 실행 건이 없으면 보관할 수 없다
    assert admin_client.put(f'/admin/items/{project_id}/archive', json={'archived': True}).status_code == 400

    orch.responses['view_project'] = lambda pid: ProjectView(str(pid), run=make_run())
    orch.responses['admin_runs'] = lambda **kw: [make_admin_run(project_id, progress='완료', total_score=70.0)]
    res = admin_client.put(f'/admin/items/{project_id}/archive', json={'archived': True})
    assert res.status_code == 200, res.text
    assert res.json()['archived'] is True and res.json()['score'] == pytest.approx(70.0)
    assert _items(admin_client)[project_id]['archived'] is True
    assert not [c for c in orch.calls if c[0] == 'abort_project']  # 보관만 하고 중단은 알리지 않는다

    res = admin_client.put(f'/admin/items/{project_id}/archive', json={'archived': False})
    assert res.status_code == 200 and res.json()['archived'] is False


def test_score_history_groups_layers_from_orchestrator(admin_client, user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['admin_score_history'] = lambda pid: make_admin_score_history(
        doc_score=[make_score_entry(58.5), make_score_entry(55.0, after_rework=True)],
        code_check=[make_score_entry(12.0)], feature_match=[])

    res = admin_client.get(f'/admin/items/{project_id}/score-history')

    assert res.status_code == 200, res.text
    body = res.json()
    assert [(e['score'], e['is_rerun']) for e in body['doc']] == [(58.5, False), (55.0, True)]
    assert [e['score'] for e in body['code']] == [12.0]
    assert body['plan'] == []


def test_score_history_empty_without_run_and_404_without_project(admin_client, user_client, orch):
    project_id = _create_project(user_client)
    orch.responses['admin_score_history'] = OrchError('RUN_NOT_FOUND', 'x')
    res = admin_client.get(f'/admin/items/{project_id}/score-history')
    assert res.status_code == 200 and res.json() == {'doc': [], 'code': [], 'plan': []}
    assert admin_client.get('/admin/items/999999/score-history').status_code == 404


def test_agent_executions_use_web_labels_and_filters(admin_client, orch):
    orch.responses['admin_executions'] = lambda **kw: [
        make_admin_execution(execution_id='e1', status='성공', trigger='첫실행', tokens=make_tokens(100, 20)),
        make_admin_execution(execution_id='e2', status='실패', trigger='재작성', error_kind='일시', error='시간 초과',
                             tokens=make_tokens(None, None)),
        make_admin_execution(execution_id='e3', status='실패', trigger='재수행', error_kind='운영', error='키 오류'),
    ]

    res = admin_client.get('/admin/agent-executions', params={'status': 'failed', 'project_id': 7, 'limit': 900})

    assert res.status_code == 200, res.text
    rows = {r['execution_id']: r for r in res.json()}
    assert rows['e1']['status'] == 'completed' and rows['e1']['rerun_type'] == 'initial'
    assert rows['e1']['token_usage'] == 120 and rows['e1']['agent_name'] == '작성' and rows['e1']['task_key'] == 'T-W1'
    assert rows['e2']['status'] == 'failed' and rows['e2']['status_ko'] == '실패' and rows['e2']['rerun_type'] == 'rerun'
    assert rows['e2']['trigger'] == '재작성' and rows['e2']['token_usage'] == 0
    assert rows['e2']['retryable'] is True and rows['e3']['retryable'] is False
    assert rows['e2']['error_reason'] == '시간 초과'
    assert 'output_ref' not in rows['e1']
    (_args, kwargs), = [(a, k) for n, a, k in orch.calls if n == 'admin_executions']
    assert kwargs == {'project_id': 7, 'status': '실패', 'limit': 500}  # 웹 표기를 한글로 바꿔 넘기고 상한은 500


def test_agent_executions_accept_korean_status_filter(admin_client, orch):
    orch.responses['admin_executions'] = lambda **kw: []
    admin_client.get('/admin/agent-executions', params={'status': '재개대기'})
    (_args, kwargs), = [(a, k) for n, a, k in orch.calls if n == 'admin_executions']
    assert kwargs['status'] == '재개대기' and kwargs['project_id'] is None


def test_agent_tasks_come_from_orchestrator(admin_client, user_client, orch):
    project_id = _create_project(user_client, '최근 실행 프로젝트')
    orch.responses['admin_agent_tasks'] = lambda: [
        make_admin_agent_task(agent='조율', task_count=13, execution_count=40, recent_project_id=str(project_id),
                              recent_status='성공'),
        make_admin_agent_task(agent='구현', task_count=2, execution_count=0, recent_project_id=None, recent_status=None),
    ]

    res = admin_client.get('/admin/agent-tasks')

    assert res.status_code == 200, res.text
    first, second = res.json()
    assert first['agent_name'] == '조율' and first['defined_task_count'] == 13 and first['total_executions'] == 40
    assert first['recent_project_id'] == project_id and first['recent_project_description'] == '최근 실행 프로젝트'
    assert first['recent_status'] == 'completed'
    assert second['recent_project_id'] is None and second['recent_status'] is None


def test_agent_ops_summary_splits_initial_and_rerun(admin_client, orch):
    orch.responses['admin_summary'] = lambda: make_admin_summary(
        triggers=[NS(trigger='첫실행', count=10, avg_tokens=100.0), NS(trigger='재작성', count=2, avg_tokens=300.0),
                  NS(trigger='재수행', count=2, avg_tokens=100.0)],
        total_tokens=1800, proofread_attempts=20, proofread_rejected=5, proofread_reject_rate=25.0)

    body = admin_client.get('/admin/agent-ops-summary').json()

    assert body['total_executions'] == 14 and body['initial_executions'] == 10 and body['rerun_executions'] == 4
    assert body['initial_avg_tokens'] == 100.0 and body['rerun_avg_tokens'] == 200.0  # 실행 수로 가중한 평균
    assert body['total_tokens'] == 1800
    assert (body['token_check_count'], body['token_violation_count'], body['token_violation_rate']) == (20, 5, 25.0)


def test_agent_ops_summary_empty(admin_client, orch):
    orch.responses['admin_summary'] = lambda: make_admin_summary()
    body = admin_client.get('/admin/agent-ops-summary').json()
    assert body['total_executions'] == 0 and body['initial_avg_tokens'] is None and body['rerun_avg_tokens'] is None
    assert body['token_violation_rate'] is None


def test_ops_summary_maps_orchestrator_summary_and_counts_unmatched_projects(admin_client, user_client, orch):
    matched = _create_project(user_client, '매칭된 프로젝트')
    _create_project(user_client, '매칭 전 프로젝트')
    orch.responses['admin_runs'] = lambda **kw: [make_admin_run(matched, progress='사용자대기')]
    orch.responses['admin_summary'] = lambda: make_admin_summary(
        doc_avg=55.5, doc_count=3, total_avg=80.0, total_count=2, pass_count=1, pass_rate=50.0, pass_threshold=80.0,
        reworked_runs=1, runs_with_executions=3, rework_rate=33.3,
        score_buckets=[NS(label='80~89점', count=1), NS(label='60점 미만', count=1)],
        layer_changes=[NS(layer='docScore', first_avg=50.0, after_avg=58.0, delta=8.0, count=2),
                       NS(layer='codeCheck', first_avg=None, after_avg=None, delta=None, count=0),
                       NS(layer='featureMatch', first_avg=10.0, after_avg=12.0, delta=2.0, count=1)],
        proofread_attempts=8, proofread_rejected=2, proofread_reject_rate=25.0)

    body = admin_client.get('/admin/ops-summary').json()

    assert body['status_counts'] == {'판단 대기': 1, '공고 매칭 전': 1}
    assert (body['doc_avg'], body['doc_count'], body['total_avg'], body['total_count']) == (55.5, 3, 80.0, 2)
    assert (body['pass_count'], body['pass_rate'], body['pass_threshold']) == (1, 50.0, 80.0)
    assert (body['rerun_matches'], body['matches_with_execution'], body['rerun_rate']) == (1, 3, 33.3)
    assert [(b['label'], b['count']) for b in body['score_buckets']] == [('80~89점', 1), ('60점 미만', 1)]
    layers = {d['layer']: d for d in body['deviations']}
    assert set(layers) == {'doc', 'code', 'plan'}
    assert (layers['doc']['round1_avg'], layers['doc']['round2_avg'], layers['doc']['delta_avg']) == (50.0, 58.0, 8.0)
    assert layers['code']['sample_count'] == 0 and layers['plan']['sample_count'] == 1
    assert (body['token_check_count'], body['token_violation_count'], body['token_violation_rate']) == (8, 2, 25.0)


def test_ops_summary_empty_when_no_projects(admin_client, orch):
    orch.responses['admin_summary'] = lambda: make_admin_summary()
    body = admin_client.get('/admin/ops-summary').json()
    assert body['status_counts'] == {} and body['doc_avg'] is None and body['total_count'] == 0


def test_admin_orchestrator_endpoints_require_admin(user_client):
    for path in ['/admin/items', '/admin/agent-executions', '/admin/agent-tasks', '/admin/agent-ops-summary',
                 '/admin/ops-summary', '/admin/items/1/score-history']:
        assert user_client.get(path).status_code == 403, path
