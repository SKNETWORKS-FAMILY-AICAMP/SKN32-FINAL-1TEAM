"""GET /projects/{id}/plan-document.docx 확인.
- 매칭/계획서가 아직 없는 프로젝트에서도 200 + 유효 docx(공식 양식 구조)가 나오는지
- generate 이후엔 실제 PlanSection 본문(문제인식/실현가능성/성장전략)이 채워지는지
검증한다."""
import io
import json

from docx import Document

from app.models import Notice


def _payload(**overrides):
    base = {
        'start_type': '예비창업', 'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': None, 'description': 'AI 기반 동네 헬스장 통합 예약 서비스',
        'notify_region': '서울특별시', 'notify_industry': '지식서비스',
        'team_members': [{'name': '박테스트', 'role': '대표', 'experience': '4년'}],
        'pricing_items': [{'service_name': '서버 호스팅', 'unit_price': 50000}],
    }
    base.update(overrides)
    return base


def _seed_notice(db_session):
    notice = Notice(
        notice_id='NOTICE-PLAN-DOC-TEST-1', source='k-startup',
        title='2026년도 초기창업패키지(일반형)', organizer='창업진흥원',
        recruitment_status='open', url='https://example.com/notice/1',
    )
    db_session.add(notice)
    db_session.commit()
    db_session.refresh(notice)
    return notice


def test_plan_document_before_generate_returns_valid_docx(authed_client, db_session):
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']

    r = authed_client.get(f'/projects/{project_id}/plan-document.docx')
    assert r.status_code == 200
    assert r.headers['content-type'] == (
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    assert r.content[:2] == b'PK'

    doc = Document(io.BytesIO(r.content))
    full_text = '\n'.join(p.text for p in doc.paragraphs)
    table_text = '\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert '초기창업패키지' in full_text
    assert len(doc.tables) >= 5
    # placeholder notation for fields we don't collect yet (기업명 등은 아직 DB에 없음)
    assert '○' in table_text


def test_plan_document_after_generate_contains_real_sections(authed_client, db_session):
    notice = _seed_notice(db_session)
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    project_id = r.json()['project_id']

    r = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': notice.notice_id})
    assert r.status_code == 200, r.text
    plan_sections = r.json()['plan']['sections']
    body_1_1 = next(s['body'] for s in plan_sections if s['tag'] == '1-1')

    r = authed_client.get(f'/projects/{project_id}/plan-document.docx')
    assert r.status_code == 200
    doc = Document(io.BytesIO(r.content))
    full_text = '\n'.join(p.text for p in doc.paragraphs)
    assert '1. 문제 인식(Problem)_창업 아이템의 필요성' in full_text
    assert body_1_1[:15] in full_text  # 실제 생성된 계획서 본문이 들어갔는지


def test_plan_document_requires_ownership(login_as, db_session):
    owner = login_as('owner@example.com', '주인')
    r = owner.post('/projects', data={'payload': json.dumps(_payload())})
    project_id = r.json()['project_id']

    other = login_as('other@example.com', '남')
    r = other.get(f'/projects/{project_id}/plan-document.docx')
    assert r.status_code == 404
