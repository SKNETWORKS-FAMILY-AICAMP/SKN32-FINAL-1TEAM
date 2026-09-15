"""[2026-09-15] 회사 프로필을 계정당 1건으로 묶던 정책을 풀고, 동시 실행 1건 제한을
User 행 락으로 분리한 수정 검증용. 두 가지를 확인한다:

1. 같은 계정으로 프로젝트를 두 번 만들 때, 두 번째 프로젝트에 입력한 신청자 정보
   (start_type/ceo_name/founded_at)가 첫 번째 프로젝트 것으로 조용히 덮이지 않고
   각자 따로 저장되는지.
2. 계정당 동시 실행 1건 제한(진행 중 매칭이 있으면 새 프로젝트 생성 거부)이 회사
   프로필을 거치지 않고도 여전히 걸리는지.
"""
import datetime
import json

from app.models import Company, MatchResult, Notice, Project


def _payload(**overrides):
    body = dict(
        start_type='예비창업', biz_type=None, ceo_name='김서준', founded_at=None,
        description='동네 헬스장 예약 서비스', notify_region='전국', notify_industry='기타',
        team_members=[], pricing_items=[],
    )
    body.update(overrides)
    return {'payload': json.dumps(body, default=str)}


def test_two_projects_keep_own_company_info(authed_client, db_session):
    r1 = authed_client.post('/projects', data=_payload(start_type='예비창업', ceo_name='김서준', founded_at=None))
    assert r1.status_code == 201, r1.text
    project1 = r1.json()

    r2 = authed_client.post('/projects', data=_payload(
        start_type='사업자', ceo_name='이영희', founded_at='2024-01-10',
    ))
    assert r2.status_code == 201, r2.text
    project2 = r2.json()

    assert project1['company_id'] != project2['company_id'], (
        '두 프로젝트가 같은 company_id를 공유하면 안 된다 — 회사 프로필 재사용 버그가 재발했다는 뜻'
    )

    company1 = db_session.get(Company, project1['company_id'])
    company2 = db_session.get(Company, project2['company_id'])
    assert company1.start_type == '예비창업' and company1.ceo_name == '김서준' and company1.founded_at is None
    assert company2.start_type == '사업자' and company2.ceo_name == '이영희'
    assert company2.founded_at == datetime.date(2024, 1, 10)

    # 같은 계정의 두 프로젝트가 둘 다 대시보드 목록에 나오는지도 같이 확인 (list_projects가
    # 더 이상 "회사 프로필 1건" 가정에 기대지 않고 Company.user_id join으로 도는지).
    listed = authed_client.get('/projects')
    assert listed.status_code == 200
    listed_ids = {p['project_id'] for p in listed.json()}
    assert {project1['project_id'], project2['project_id']} <= listed_ids


def test_concurrency_limit_still_blocks_without_shared_company(authed_client, db_session):
    r1 = authed_client.post('/projects', data=_payload())
    assert r1.status_code == 201, r1.text
    project1_id = r1.json()['project_id']

    # 실제 파이프라인 없이 "진행 중 매칭"만 최소로 흉내낸다 — MatchResult.status 기본값이
    # in_progress라 그대로 커밋하면 된다.
    notice = Notice(
        id=1, notice_id='test:PBLN_0001', source='test', title='테스트 공고',
        target_text=None, category=None, organizer=None, supervising_org=None,
        executing_org=None, apply_start=None, apply_end=None,
        recruitment_status='open', url=None,
    )
    db_session.add(notice)
    db_session.flush()
    db_session.add(MatchResult(project_id=project1_id, notice_id=notice.notice_id, fit_score=80))
    db_session.commit()

    r2 = authed_client.post('/projects', data=_payload(ceo_name='다른 사람'))
    assert r2.status_code == 409, (
        f'진행 중 매칭이 있는데도 새 프로젝트 생성이 막히지 않았다 — 동시 실행 제한이 '
        f'User 락 분리 후 깨졌을 수 있다 (status={r2.status_code}, body={r2.text})'
    )

    # 앞서 만든 회사 프로필이 재사용되지 않고 새로 생겼는지도(막힌 요청은 커밋 전에
    # 거부되니 두 번째 회사 프로필이 남아있으면 안 된다) 확인.
    companies_for_user = db_session.query(Company).join(Project, Project.company_id == Company.company_id).filter(
        Project.project_id == project1_id
    ).count()
    assert companies_for_user == 1
