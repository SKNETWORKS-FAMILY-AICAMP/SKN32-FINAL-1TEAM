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

    # [2026-09-28 수정, 프론트 2차 요청 B-1/C] seed_dummy_pipeline이 심어두는 예시 채점
    # 근거: CHECK-*(webdev 기본 카테고리 -> 'standard' 8항목, 만점 합계 15.00), FEATURE-MATCH
    # 15.00/15.00(seed_dummy_pipeline.py _CODE_CHECK_ITEMS_BY_CATEGORY 참고) — item_code
    # 접두어로 갈라 합산. 예전엔 항목 하나씩(5.00)만 있었는데, 만점이어도 code_weight/
    # plan_weight(15)의 1/3밖에 못 채워서 시연 중 통과 화면을 볼 수 없다는 지적으로 확장.
    assert verdict['doc_score'] == plan['doc_score']
    assert verdict['doc_max_score'] == float(policy.doc_weight)
    assert verdict['code_score'] == 15.0
    assert verdict['code_max_score'] == float(policy.code_weight)
    assert verdict['plan_match_score'] == 15.0
    assert verdict['plan_match_max_score'] == float(policy.plan_weight)
    assert verdict['total_score'] == plan['doc_score'] + 15.0 + 15.0
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


def test_seed_artifact_outcome_fail_reproduces_frontend_demo_scores(authed_client, db_session):
    """[2026-09-29 신규] POST /generate는 seed_dummy_pipeline을 항상 artifact_outcome=
    'pass'(만점)로만 호출해서, 기획서 v1.10 발표 예시(⑪ "문서 86점 통과인데 대조 7/15
    때문에 종합 79점 미달")를 재현할 방법이 없었다 — artifact_outcome='fail'을 직접
    호출해 front/src/features/workflow/data.js의 CODE_CHECK_FAILS_BY_OUTCOME.fail /
    ARTIFACT_SCORE_BY_OUTCOME.fail과 같은 숫자(코드 12/15, 대조 7/15)가 나오는지 확인한다.
    대조 점수는 기능정의서 v1.9 FeatureMatchResult.score 공식(max(0, 15 - 4 × 누락
    건수))대로 계산돼야 한다."""
    import json

    from seed_dummy_pipeline import seed_dummy_pipeline

    notice = Notice(
        notice_id='NOTICE-VERDICT-SCORE-FAIL', source='k-startup', title='테스트 공고',
        organizer='창업진흥원', recruitment_status='open', url='https://example.com/notice/verdict-fail',
    )
    db_session.add(notice)
    db_session.commit()

    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    assert r.status_code == 201, r.text
    project_id = r.json()['project_id']

    seed_dummy_pipeline(db_session, project_id, notice_id=notice.notice_id, artifact_outcome='fail')
    db_session.commit()

    r = authed_client.get(f'/projects/{project_id}/result')
    assert r.status_code == 200, r.text
    verdict = r.json()['verdict']

    assert verdict['code_score'] == 12.0
    assert verdict['plan_match_score'] == 7.0  # max(0, 15 - 4*2) — 기능정의서 공식
    assert verdict['total_score'] == verdict['doc_score'] + 12.0 + 7.0
