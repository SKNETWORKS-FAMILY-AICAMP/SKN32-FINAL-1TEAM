"""[2026-09-15] 회사 프로필을 계정당 1건으로 묶던 정책을 풀고, 동시 실행 1건 제한을
User 행 락으로 분리한 수정 검증용. 두 가지를 확인한다:

1. 같은 계정으로 프로젝트를 두 번 만들 때, 두 번째 프로젝트에 입력한 신청자 정보
   (ceo_name/founded_at)가 첫 번째 프로젝트 것으로 조용히 덮이지 않고
   각자 따로 저장되는지.
2. 계정당 동시 실행 1건 제한(진행 중 매칭이 있으면 새 프로젝트 생성 거부)이 회사
   프로필을 거치지 않고도 여전히 걸리는지.

[2026-09-17] start_type/notify_region/notify_industry는 IntakeForm.jsx에 입력칸이
아예 없어서 항상 고정값('예비창업'/'전국'/'기타' 등)만 보내고 있던 가짜 필드였다
(담당자 지적, "지워" 지시로 ProjectCreateRequest에서 제거) — 이 테스트 파일도
같이 정리했다. [2026-09-18] 그 뒤로 모든 행이 NULL로만 쌓이는 게 확인돼 컬럼 자체도
완전히 지웠다(companies.start_type/projects.notify_region/notify_industry) —
_payload()가 안 보내도 여전히 201로 성공해야 한다.
"""
import datetime
import json

from orch_fakes import ActiveWork

from app.models import Company


def _payload(**overrides):
    body = dict(
        biz_type=None, ceo_name='김서준', founded_at=None,
        description='동네 헬스장 예약 서비스',
        team_members=[], pricing_items=[],
    )
    body.update(overrides)
    return {'payload': json.dumps(body, default=str)}


def test_two_projects_keep_own_company_info(authed_client, db_session):
    r1 = authed_client.post('/projects', data=_payload(ceo_name='김서준', founded_at=None))
    assert r1.status_code == 201, r1.text
    project1 = r1.json()

    r2 = authed_client.post('/projects', data=_payload(
        ceo_name='이영희', founded_at='2024-01-10',
    ))
    assert r2.status_code == 201, r2.text
    project2 = r2.json()

    assert project1['company_id'] != project2['company_id'], (
        '두 프로젝트가 같은 company_id를 공유하면 안 된다 — 회사 프로필 재사용 버그가 재발했다는 뜻'
    )

    company1 = db_session.get(Company, project1['company_id'])
    company2 = db_session.get(Company, project2['company_id'])
    assert company1.ceo_name == '김서준' and company1.founded_at is None
    assert company2.ceo_name == '이영희'
    assert company2.founded_at == datetime.date(2024, 1, 10)

    # 같은 계정의 두 프로젝트가 둘 다 대시보드 목록에 나오는지도 같이 확인 (list_projects가
    # 더 이상 "회사 프로필 1건" 가정에 기대지 않고 Company.user_id join으로 도는지).
    listed = authed_client.get('/projects')
    assert listed.status_code == 200
    listed_ids = {p['project_id'] for p in listed.json()}
    assert {project1['project_id'], project2['project_id']} <= listed_ids


def test_concurrency_limit_still_blocks_without_shared_company(authed_client, db_session, orch):
    """[SB-242] 동시 실행 제한은 오케스트레이터가 계정 단위로 판단한다 — 회사 프로필과 무관하다.
    막힌 요청은 회사 프로필도 새로 만들지 않아야 한다."""
    r1 = authed_client.post('/projects', data=_payload())
    assert r1.status_code == 201, r1.text
    project1_id = r1.json()['project_id']
    orch.responses['active_work'] = ActiveWork(project_id=str(project1_id), run_id='r1', step='계획서작성',
                                               resume_step=5)

    r2 = authed_client.post('/projects', data=_payload(ceo_name='다른 사람'))
    assert r2.status_code == 409, r2.text
    assert r2.json()['detail']['active_project_id'] == project1_id
    assert db_session.query(Company).count() == 1, '막힌 요청이 회사 프로필을 만들었다'


def test_applicant_type_is_persisted(authed_client, db_session):
    """[2026-09-17] IntakeForm.jsx가 필수로 물어보는 "신청자 유형"이 요청 바디에도 안 실리고
    저장할 컬럼도 없어서 화면에서 고른 값이 버려지고 있었다(리뷰 중 발견) — 이제
    받아서 companies.applicant_type에 저장되는지 확인한다."""
    res = authed_client.post('/projects', data=_payload(applicant_type='individual'))
    assert res.status_code == 201, res.text
    project = res.json()

    company = db_session.get(Company, project['company_id'])
    assert company.applicant_type == 'individual'


def test_applicant_type_omitted_stays_null(authed_client, db_session):
    """기존 호출자(create_test_project.py 등)처럼 applicant_type을 아예 안 보내도 여전히
    201로 성공해야 한다 — 필수 필드로 만들지 않았다."""
    res = authed_client.post('/projects', data=_payload())
    assert res.status_code == 201, res.text
    company = db_session.get(Company, res.json()['company_id'])
    assert company.applicant_type is None


def test_invalid_applicant_type_returns_422(authed_client):
    res = authed_client.post('/projects', data=_payload(applicant_type='xxx'))
    assert res.status_code == 422
