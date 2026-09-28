"""VerdictOut의 종합 판정 점수 필드(2026-09-22, 프론트 전달사항 10번) — pytest 버전.

검증결과서(front/src/features/workflow/verificationReport.js)가 채워야 하는데 지금까지
VerdictOut엔 overall_passed/model_version/first_pass_passed 3개뿐이라 없었던 값들 —
문서층/자동검증/계획서대조 세 층 점수와 총점·판정기준(routers/projects.py
_build_demo_response 참고)."""
import json

from app.models import Notice, VerificationPolicy


def _payload(**overrides):
    base = {
        'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': None, 'description': 'AI 기반 동네 헬스장 통합 예약 서비스',
        'team_members': [], 'pricing_items': [],
    }
    base.update(overrides)
    return base


def test_verdict_includes_three_layer_score_summary(authed_client, db_session):
    notice = Notice(
        notice_id='NOTICE-VERDICT-SCORE-TEST', source='k-startup', title='테스트 공고',
        organizer='창업진흥원', recruitment_status='open', url='https://example.com/notice/verdict',
    )
    db_session.add(notice)
    db_session.commit()

    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']

    r = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': notice.notice_id})
    assert r.status_code == 200, r.text
    body = r.json()
    verdict = body['verdict']
    plan = body['plan']

    policy = db_session.query(VerificationPolicy).order_by(VerificationPolicy.policy_id.asc()).first()

    # seed_dummy_pipeline이 심어두는 예시 채점 근거: CHECK-ENTRY-FILE 5.00/5.00,
    # FEATURE-MATCH 5.00/5.00 (seed_dummy_pipeline.py 참고) — item_code 접두어로 갈라 합산.
    assert verdict['doc_score'] == plan['doc_score']
    assert verdict['doc_max_score'] == float(policy.doc_weight)
    assert verdict['code_score'] == 5.0
    assert verdict['code_max_score'] == float(policy.code_weight)
    assert verdict['plan_match_score'] == 5.0
    assert verdict['plan_match_max_score'] == float(policy.plan_weight)
    assert verdict['total_score'] == plan['doc_score'] + 5.0 + 5.0
    assert verdict['pass_threshold'] == float(policy.pass_threshold)


def test_get_result_returns_same_score_summary_as_generate(authed_client, db_session):
    """새로고침/재방문(GET /result)해도 같은 요약이 나와야 한다 — _build_demo_response를
    /generate와 /result 둘 다 공유하므로."""
    notice = Notice(
        notice_id='NOTICE-VERDICT-SCORE-RESULT', source='k-startup', title='테스트 공고',
        organizer='창업진흥원', recruitment_status='open', url='https://example.com/notice/verdict2',
    )
    db_session.add(notice)
    db_session.commit()

    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    project_id = r.json()['project_id']
    r = authed_client.post(f'/projects/{project_id}/generate', json={'notice_id': notice.notice_id})
    generate_verdict = r.json()['verdict']

    r = authed_client.get(f'/projects/{project_id}/result')
    assert r.status_code == 200, r.text
    result_verdict = r.json()['verdict']

    assert result_verdict == generate_verdict
