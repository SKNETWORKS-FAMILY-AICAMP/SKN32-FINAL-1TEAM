"""POST /projects가 project_plan_inputs(ProjectPlanInput, project당 1행)에 IntakeForm.jsx
"사업 계획" 섹션 필드를 실제로 저장하고, GET /projects/{id}(ProjectDetailOut.plan_input)로
그대로 돌려주는지 확인한다. 지금까지는 문서 생성 경로(test_plan_document_endpoint.py)로
occupation/partners 두 필드만 간접 확인됐고, 나머지 필드는 저장 자체를 검증하는 테스트가
없었다."""
import json


def _full_payload(**overrides):
    base = {
        'applicant_type': 'individual', 'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': '2024-01-01', 'description': 'AI 기반 동네 헬스장 통합 예약 서비스',
        'team_members': [], 'pricing_items': [],
        'ceo_birth_date': '1995-05-05',
        'ceo_gender': '여성',
        'region_sido': '서울특별시',
        'region_sigungu': '강남구',
        'main_industry': '정보·통신',
        'certifications': ['여성기업', '벤처기업'],
        'ceo_careers': [{'type': '경력', 'title': 'OO전자 백엔드 개발', 'period': '2019.03-2023.10', 'has_proof': True}],
        'ceo_capability': '풀스택 개발 8년, 팀 리딩 경험',
        'dev_start_month': '2026-10',
        'dev_end_month': '2027-03',
        'self_funding_allowed': True,
        'self_cash_limit': 500,
        'self_in_kind_resources': '사무공간 무상 제공',
        'no_hires': False,
        'hires': [{'job': '백엔드 개발', 'headcount': '1명', 'required_skill': 'Python 3년 이상', 'hire_month': '2026-11'}],
        'no_equipment': False,
        'equipment': [{'name': 'GPU 서버', 'status': '도입 예정'}],
        'no_partners': False,
        'partners': [{'name': '○○대학 · 실증 지원', 'status': '협력 중'}],
    }
    base.update(overrides)
    return base


def test_post_projects_persists_plan_input_fields(authed_client):
    r = authed_client.post('/projects', data={'payload': json.dumps(_full_payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']

    r = authed_client.get(f'/projects/{project_id}')
    assert r.status_code == 200, r.text
    plan_input = r.json()['plan_input']
    assert plan_input is not None

    assert plan_input['ceo_birth_date'] == '1995-05-05'
    assert plan_input['ceo_gender'] == '여성'
    assert plan_input['region_sido'] == '서울특별시'
    assert plan_input['region_sigungu'] == '강남구'
    assert plan_input['main_industry'] == '정보·통신'
    assert plan_input['certifications'] == ['여성기업', '벤처기업']
    assert plan_input['ceo_careers'] == [
        {'type': '경력', 'title': 'OO전자 백엔드 개발', 'period': '2019.03-2023.10', 'has_proof': True},
    ]
    assert plan_input['ceo_capability'] == '풀스택 개발 8년, 팀 리딩 경험'
    assert plan_input['dev_start_month'] == '2026-10'
    assert plan_input['dev_end_month'] == '2027-03'
    assert plan_input['budget_scale_manwon'] is None  # individual/corp 전용이 아니라 그대로 None
    assert plan_input['self_funding_allowed'] is True
    assert plan_input['self_cash_limit'] == 500
    assert plan_input['self_in_kind_resources'] == '사무공간 무상 제공'
    assert plan_input['no_hires'] is False
    assert plan_input['hires'] == [
        {'job': '백엔드 개발', 'headcount': '1명', 'required_skill': 'Python 3년 이상', 'hire_month': '2026-11'},
    ]
    assert plan_input['no_equipment'] is False
    assert plan_input['equipment'] == [{'name': 'GPU 서버', 'status': '도입 예정'}]
    assert plan_input['no_partners'] is False
    assert plan_input['partners'] == [{'name': '○○대학 · 실증 지원', 'status': '협력 중'}]


def test_post_projects_persists_preliminary_budget_scale_and_occupation(authed_client):
    r = authed_client.post('/projects', data={'payload': json.dumps(_full_payload(
        applicant_type='preliminary', founded_at=None,
        self_funding_allowed=None, self_cash_limit=None, self_in_kind_resources=None,
        budget_scale_manwon=1200, occupation='대학생',
    ))})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']

    plan_input = authed_client.get(f'/projects/{project_id}').json()['plan_input']
    assert plan_input['budget_scale_manwon'] == 1200
    assert plan_input['occupation'] == '대학생'
    assert plan_input['self_funding_allowed'] is None


def test_post_projects_with_no_hires_equipment_partners_stores_empty_lists(authed_client):
    r = authed_client.post('/projects', data={'payload': json.dumps(_full_payload(
        no_hires=True, hires=[], no_equipment=True, equipment=[], no_partners=True, partners=[],
    ))})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']

    plan_input = authed_client.get(f'/projects/{project_id}').json()['plan_input']
    assert plan_input['no_hires'] is True
    assert plan_input['hires'] == []
    assert plan_input['no_equipment'] is True
    assert plan_input['equipment'] == []
    assert plan_input['no_partners'] is True
    assert plan_input['partners'] == []


def test_get_project_requires_ownership_for_plan_input(login_as):
    owner = login_as('plan-input-owner@example.com', '주인')
    r = owner.post('/projects', data={'payload': json.dumps(_full_payload())})
    project_id = r.json()['project_id']

    other = login_as('plan-input-other@example.com', '남')
    r = other.get(f'/projects/{project_id}')
    assert r.status_code == 404
