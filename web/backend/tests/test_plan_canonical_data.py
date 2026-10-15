"""app/models.py PlanCanonicalData(2026-09-22 신규) — pytest 버전.

Strategy Agent(구글 드라이브 "전략/작성/검증1" 시트 F01~F15)가 쓸 중간 산출물 저장소.
아직 그 Agent도, 이 테이블을 읽고 쓰는 라우터 코드도 없다 — 지금은 스키마만 먼저 준비해두는
단계라, 이 테스트는 "테이블/모델이 의도대로 배선됐는지"(FK, JSON 왕복, (plan_id, data_key)
유일성)만 확인한다."""
import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Notice, PlanCanonicalData


def _payload(**overrides):
    base = {
        'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': None, 'description': 'AI 기반 동네 헬스장 통합 예약 서비스',
        'team_members': [], 'pricing_items': [],
    }
    base.update(overrides)
    return base


def _create_plan(authed_client, db_session):
    """POST /generate로 실제 엔드포인트를 태워 business_plans 행을 하나 만든다 —
    match/company/project FK를 손으로 채우는 대신 기존 파이프라인을 재사용."""
    notice = Notice(
        notice_id='NOTICE-CANONICAL-TEST', source='k-startup', title='테스트 공고',
        organizer='창업진흥원', recruitment_status='open', url='https://example.com/notice/canonical',
    )
    db_session.add(notice)
    db_session.commit()

    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']
    r = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': notice.notice_id})
    assert r.status_code == 200, r.text
    return r.json()['plan']['plan_id']


def test_json_round_trips_and_survives_reload(authed_client, db_session):
    plan_id = _create_plan(authed_client, db_session)
    payload = {
        'trend_summary': '소규모 헬스장 시장은 통합 관리 솔루션 도입률이 낮다',
        'pain_points': ['수기 장부 운영 부담', '회원권 잔여 횟수 수작업 관리'],
        'segments': [{'name': '소규모 헬스장', 'size': '전국 약 12,000곳'}],
    }
    db_session.add(PlanCanonicalData(
        plan_id=plan_id, data_key='market_analysis', data_json=payload, source_function='F03',
    ))
    db_session.commit()

    db_session.expire_all()
    row = (
        db_session.query(PlanCanonicalData)
        .filter(PlanCanonicalData.plan_id == plan_id, PlanCanonicalData.data_key == 'market_analysis')
        .one()
    )
    assert row.data_json == payload, 'JSON이 저장 전후로 그대로 왕복해야 함'
    assert row.source_function == 'F03'


def test_same_plan_can_hold_multiple_canonical_blocks(authed_client, db_session):
    """한 plan_id 안에 market_analysis/team_capability처럼 서로 다른 data_key가 여러 개
    공존해야 한다 — F01~F15가 각자 다른 블록을 만들어 쌓는 구조."""
    plan_id = _create_plan(authed_client, db_session)
    db_session.add_all([
        PlanCanonicalData(plan_id=plan_id, data_key='market_analysis', data_json={'a': 1}, source_function='F03'),
        PlanCanonicalData(plan_id=plan_id, data_key='team_capability', data_json={'b': 2}, source_function='F05'),
    ])
    db_session.commit()

    rows = db_session.query(PlanCanonicalData).filter(PlanCanonicalData.plan_id == plan_id).all()
    assert {r.data_key for r in rows} == {'market_analysis', 'team_capability'}


def test_duplicate_data_key_for_same_plan_is_rejected(authed_client, db_session):
    """(plan_id, data_key) 유일성 — F03이 재시도로 두 번 불려도 market_analysis가 plan당
    하나만 있어야 한다(_upsert_plan_section과 같은 원칙, 실제 upsert 헬퍼는 Strategy Agent
    라우팅 코드가 붙을 때 같이 추가한다)."""
    plan_id = _create_plan(authed_client, db_session)
    db_session.add(PlanCanonicalData(plan_id=plan_id, data_key='market_analysis', data_json={'a': 1}))
    db_session.commit()

    db_session.add(PlanCanonicalData(plan_id=plan_id, data_key='market_analysis', data_json={'a': 2}))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
