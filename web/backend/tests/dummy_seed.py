"""더미 파이프라인(seed_dummy_pipeline) 결과를 직접 심는 테스트 도우미 — 재작성(retry-task) · 업로드 등 아직 더미 테이블에
기대는 테스트용이다. [SB-247]에서 더미 테이블과 함께 없앤다."""
import json

from app.models import Notice, Project


def payload(**overrides):
    base = {
        'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': None, 'description': 'AI 기반 동네 헬스장 통합 예약 서비스',
        'team_members': [], 'pricing_items': [],
    }
    base.update(overrides)
    return base


def seed_notice(db_session, notice_id: str) -> Notice:
    notice = Notice(
        notice_id=notice_id, source='k-startup', title='테스트 공고', organizer='창업진흥원',
        recruitment_status='open', url=f'https://example.com/notice/{notice_id}',
    )
    db_session.add(notice)
    db_session.commit()
    db_session.refresh(notice)
    return notice


def create_match(authed_client, db_session, notice_id: str) -> Project:
    """프로젝트를 만들고 더미 파이프라인 결과(계획서 · 산출물 · 판정)를 DB에 직접 심는다."""
    import seed_dummy_pipeline

    notice = seed_notice(db_session, notice_id)
    r = authed_client.post('/projects', data={'payload': json.dumps(payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']
    seed_dummy_pipeline.seed_dummy_pipeline(db_session, project_id, notice_id=notice.notice_id, retry_agents=())
    db_session.commit()
    db_session.expire_all()
    return db_session.get(Project, project_id)
