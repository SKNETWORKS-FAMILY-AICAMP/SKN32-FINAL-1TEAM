"""GET /projects/{id}/result — 계획서만 끝나고 산출물/판정은 아직 없는 중간 상태에서도
200을 돌려줘야 한다(2026-09-22, 프론트 전달사항 3번) — pytest 버전.

seed_dummy_pipeline은 계획서·산출물·판정을 한 번에 만들어서 이 틈이 평소엔 안 드러나므로,
artifact/verdict 행을 직접 지워서 "계획서만 끝난" 상태를 흉내낸다."""
import json

from app.models import Artifact, Notice, Verdict


def _payload(**overrides):
    base = {
        'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': None, 'description': 'AI 기반 동네 헬스장 통합 예약 서비스',
        'team_members': [], 'pricing_items': [],
    }
    base.update(overrides)
    return base


def test_result_returns_plan_without_verdict_when_prototype_not_done(authed_client, db_session):
    notice = Notice(
        notice_id='NOTICE-RESULT-PARTIAL', source='k-startup', title='테스트 공고',
        organizer='창업진흥원', recruitment_status='open', url='https://example.com/notice/partial',
    )
    db_session.add(notice)
    db_session.commit()

    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    project_id = r.json()['project_id']
    r = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': notice.notice_id})
    assert r.status_code == 200, r.text
    plan_id = r.json()['plan']['plan_id']

    # 프로토타입/검증이 아직 안 끝난 상태를 흉내낸다 — verdict부터(FK 순서), 그다음 artifact 삭제.
    db_session.query(Verdict).filter(Verdict.plan_id == plan_id).delete()
    db_session.query(Artifact).filter(Artifact.plan_id == plan_id).delete()
    db_session.commit()

    r = authed_client.get(f'/projects/{project_id}/result')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['plan']['plan_id'] == plan_id
    assert body['plan']['sections'], '계획서 섹션은 그대로 나와야 함'
    assert body['verdict'] is None, '아직 판정이 없으면 verdict는 None이어야지 404가 나면 안 됨'


def test_result_still_404s_when_no_plan_at_all(authed_client, db_session):
    """공고 매칭까지만 하고 계획서 자체를 아직 시작 안 한 상태는 여전히 404가 맞다."""
    notice = Notice(
        notice_id='NOTICE-RESULT-NOPLAN', source='k-startup', title='테스트 공고',
        organizer='창업진흥원', recruitment_status='open', url='https://example.com/notice/noplan',
    )
    db_session.add(notice)
    db_session.commit()

    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    project_id = r.json()['project_id']

    r = authed_client.get(f'/projects/{project_id}/result')
    assert r.status_code == 404, r.text
