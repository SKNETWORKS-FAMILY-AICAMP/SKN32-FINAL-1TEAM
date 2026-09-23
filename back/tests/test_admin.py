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
from app.models import Faq, ImportRun, Notice, ProofreadLog, User, VerificationChecklistItem
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
        json={'pass_threshold': 75, 'rerun_cap': 5, 'deviation_cap': 8, 'token_retry_cap': 4},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['pass_threshold'] == 75.0
    assert body['rerun_cap'] == 5
    assert body['deviation_cap'] == 8.0
    assert body['token_retry_cap'] == 4


@pytest.mark.parametrize('field,value', [
    ('pass_threshold', -1), ('pass_threshold', 101),
    ('pass_threshold', ''), ('deviation_cap', -1),
    ('rerun_cap', -1), ('token_retry_cap', 1.5),
])
def test_invalid_thresholds_do_not_change_policy(admin_client, field, value):
    before = admin_client.get('/admin/policy').json()
    payload = {key: before[key] for key in (
        'pass_threshold', 'rerun_cap', 'deviation_cap', 'token_retry_cap')}
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

def test_get_items_reflects_match_status(admin_client, user_client, db_session):
    project_id = _create_project(user_client)

    res = admin_client.get('/admin/items')
    assert res.status_code == 200, res.text
    matching = [row for row in res.json() if row['project_id'] == project_id]
    assert len(matching) == 1, f'방금 만든 프로젝트가 /admin/items에 안 보임: {res.json()}'
    assert matching[0]['user_name'] == '일반유저테스트'
    assert matching[0]['match_status'] is None, '아직 매칭 전인데 match_status가 비어있지 않음'
    assert matching[0]['status_label'] == '공고 매칭 전'
    assert matching[0]['step'] is None
    assert matching[0]['score'] is None
    assert matching[0]['archived'] is False

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
    # seed_dummy_pipeline은 stage=STAGE_DONE으로 채우므로 완료 상태여야 한다(app/pipeline_stages.py).
    assert matched['status_label'] == '완료', matched
    # FIXED_TASK_SEQUENCE 마지막 행(coordinate_finalize, agent_name='조율')이 최신 실행이어야 한다.
    assert matched['step'] == '조율', matched
    assert matched['attempts'] == 1
    # DEFAULT_DOC_SCORE(58.50) + DEFAULT_ARTIFACT_SCORE(24.00) = 82.50 (seed_dummy_pipeline.py 기본값)
    assert matched['score'] == pytest.approx(82.50), matched
    assert matched['archived'] is False


def test_put_item_archive_toggles_match_archived_at(admin_client, user_client, db_session):
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-ARCHIVE', source='k-startup', title='보관 처리 검증용 더미 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-ARCHIVE', retry_agents=())
    db_session.commit()

    res = admin_client.put(f'/admin/items/{project_id}/archive', json={'archived': True})
    assert res.status_code == 200, res.text
    assert res.json()['archived'] is True

    res = admin_client.get('/admin/items')
    matched = next(row for row in res.json() if row['project_id'] == project_id)
    assert matched['archived'] is True

    res = admin_client.put(f'/admin/items/{project_id}/archive', json={'archived': False})
    assert res.status_code == 200, res.text
    assert res.json()['archived'] is False


def test_put_item_archive_without_match_returns_400(admin_client, user_client):
    project_id = _create_project(user_client)
    res = admin_client.put(f'/admin/items/{project_id}/archive', json={'archived': True})
    assert res.status_code == 400, res.text


def test_get_item_score_history_groups_by_layer(admin_client, user_client, db_session):
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-HISTORY', source='k-startup', title='점수 이력 검증용 더미 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-HISTORY', retry_agents=())
    db_session.commit()

    res = admin_client.get(f'/admin/items/{project_id}/score-history')
    assert res.status_code == 200, res.text
    body = res.json()
    # seed_dummy_pipeline이 verification_score_history에 doc/code 두 layer를 하나씩 남긴다
    # (plan layer는 아직 채점 산식이 없어 만들지 않는다 — seed_dummy_pipeline.py 주석 참고).
    assert len(body['doc']) == 1, body
    assert len(body['code']) == 1, body
    assert body['plan'] == []
    assert body['doc'][0]['score'] == pytest.approx(58.50)
    assert body['code'][0]['score'] == pytest.approx(24.00)


def test_get_item_score_history_without_plan_returns_empty(admin_client, user_client):
    project_id = _create_project(user_client)
    res = admin_client.get(f'/admin/items/{project_id}/score-history')
    assert res.status_code == 200, res.text
    assert res.json() == {'doc': [], 'code': [], 'plan': []}


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

def test_get_agent_tasks_defined_counts_match_fixed_sequence(admin_client):
    res = admin_client.get('/admin/agent-tasks')
    assert res.status_code == 200, res.text
    by_name = {r['agent_name']: r for r in res.json()}
    # FIXED_TASK_SEQUENCE(app/models.py) 기준 — 조율 4개, 전략/작성 각 1개, 나머지 각 2개.
    assert by_name['조율']['defined_task_count'] == 4
    assert by_name['전략']['defined_task_count'] == 1
    assert by_name['작성']['defined_task_count'] == 1
    assert by_name['검증-1']['defined_task_count'] == 2
    assert by_name['구현']['defined_task_count'] == 2
    assert by_name['검증-2']['defined_task_count'] == 2
    assert by_name['검수']['defined_task_count'] == 2
    # 아직 아무 실행도 없는 신선한 테스트 DB에서는 전부 0건·최근 프로젝트 없음이어야 한다.
    assert all(r['total_executions'] == 0 for r in by_name.values())
    assert all(r['recent_project_id'] is None for r in by_name.values())


def test_get_agent_tasks_reflects_recent_execution(admin_client, user_client, db_session):
    project_id = _create_project(user_client, description='에이전트 테스크 검증용 프로젝트')
    notice = Notice(
        notice_id='ADMIN-TEST-AGENTTASK', source='k-startup', title='에이전트 테스크 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-AGENTTASK', retry_agents=())
    db_session.commit()

    res = admin_client.get('/admin/agent-tasks')
    assert res.status_code == 200, res.text
    by_name = {r['agent_name']: r for r in res.json()}
    # FIXED_TASK_SEQUENCE 마지막 행(coordinate_finalize)이 '조율'이라 그 Agent의 최근
    # 실행이 이 프로젝트를 가리켜야 한다.
    assert by_name['조율']['recent_project_id'] == project_id
    assert by_name['조율']['recent_project_description'] == '에이전트 테스크 검증용 프로젝트'
    assert by_name['조율']['recent_status'] == 'success'
    assert by_name['조율']['total_executions'] == 4  # coordinate_intake/user_decision_doc/user_decision_final/coordinate_finalize


# ============================================================================
# 에이전트 테스크 — 운영 지표 요약 (/admin/agent-ops-summary)
# ============================================================================

def test_get_agent_ops_summary_splits_initial_and_rerun(admin_client, user_client, db_session):
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-OPSSUMMARY', source='k-startup', title='운영 지표 요약 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    # 기본 retry_agents=('작성','구현')라 writing 1행 + implement_prototype/infographic 2행,
    # 총 3개의 rerun 행이 FIXED_TASK_SEQUENCE 14행 위에 추가로 쌓인다(seed_dummy_pipeline.py 참고).
    seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-OPSSUMMARY')
    db_session.commit()

    res = admin_client.get('/admin/agent-ops-summary')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['total_executions'] == 17
    assert body['initial_executions'] == 14
    assert body['rerun_executions'] == 3
    assert body['initial_avg_tokens'] == pytest.approx(800.0)
    assert body['rerun_avg_tokens'] == pytest.approx(650.0)
    assert body['total_tokens'] == 14 * 800 + 3 * 650


def test_get_agent_ops_summary_empty_when_no_executions(admin_client):
    res = admin_client.get('/admin/agent-ops-summary')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['total_executions'] == 0
    assert body['initial_avg_tokens'] is None
    assert body['rerun_avg_tokens'] is None


# ============================================================================
# 운영 현황 (/admin/ops-summary)
# ============================================================================

def test_get_ops_summary_aggregates_scores_and_status(admin_client, user_client, db_session):
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-OPS', source='k-startup', title='운영 현황 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    # 기본 doc_score=58.50, artifact_score=24.00, threshold=80.00 -> 합계 82.50으로 통과.
    seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-OPS')
    db_session.commit()

    res = admin_client.get('/admin/ops-summary')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['status_counts'] == {'완료': 1}
    assert body['doc_avg'] == pytest.approx(58.50)
    assert body['doc_count'] == 1
    assert body['total_avg'] == pytest.approx(82.50)
    assert body['total_count'] == 1
    assert body['pass_count'] == 1
    assert body['pass_rate'] == pytest.approx(100.0)
    assert body['pass_threshold'] == pytest.approx(80.0)
    assert body['matches_with_execution'] == 1
    assert body['rerun_matches'] == 1  # 기본 retry_agents가 비어있지 않아 재시도 행이 남는다
    assert body['rerun_rate'] == pytest.approx(100.0)
    buckets = {b['label']: b['count'] for b in body['score_buckets']}
    assert buckets['80~89점'] == 1
    assert sum(buckets.values()) == 1
    # retry_task를 실제로 호출한 적이 없어 verification_score_history엔 layer당 1건뿐이라
    # (1회->2회 비교가 안 됨) 편차는 항상 sample_count=0으로 나온다(admin.py get_ops_summary 주석 참고).
    deviations = {d['layer']: d for d in body['deviations']}
    assert deviations['doc']['sample_count'] == 0
    assert deviations['code']['sample_count'] == 0
    assert deviations['plan']['sample_count'] == 0


def test_get_ops_summary_empty_when_no_projects(admin_client):
    res = admin_client.get('/admin/ops-summary')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['status_counts'] == {}
    assert body['doc_avg'] is None
    assert body['total_count'] == 0
    assert body['pass_rate'] is None
    assert body['rerun_rate'] is None
    assert body['token_violation_rate'] is None


def test_get_ops_summary_token_violation_rate_pinned_to_zero_while_dummy(admin_client, user_client, db_session):
    # run_review_token_check_retry가 아직 더미(무작위) 판정이라, 실제 passed=False
    # 건수가 있어도 위반율은 0으로 고정된다 (진짜 판정 로직이 들어오기 전까지).
    project_id = _create_project(user_client)
    notice = Notice(
        notice_id='ADMIN-TEST-TOKENRATE', source='k-startup', title='토큰 위반율 검증용 공고',
        recruitment_status='진행중',
    )
    db_session.add(notice)
    db_session.flush()
    verdict = seed_dummy_pipeline(db_session, project_id, notice_id='ADMIN-TEST-TOKENRATE', retry_agents=())
    db_session.add(ProofreadLog(
        plan_id=verdict.plan_id, original_text='원문', corrected_text='반려된 시도안',
        attempt_no=2, passed=False, violation_type='날짜', violation_note='테스트 위반', recovery_status='pending',
    ))
    db_session.commit()

    res = admin_client.get('/admin/ops-summary')
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['token_check_count'] == 2
    assert body['token_violation_count'] == 0
    assert body['token_violation_rate'] == pytest.approx(0.0)


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
