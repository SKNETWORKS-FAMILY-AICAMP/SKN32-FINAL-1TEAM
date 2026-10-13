"""점수 보고서 환산 칸 — 층 점수 · 만점 · 코드 점검 항목 줄을 그 실행 건 배점 기준으로 내보내기 (오케스트레이터 2026-10-11).

오케스트레이터가 검증-2 원점수(코드 점검 15 + 계획서 대조 15)를 그 실행 건의 배점으로 환산해 점수 보고서에 싣는다. 웹은 지금 정책 값을 만점으로 붙이면
관리자가 배점을 바꾼 뒤 '13/10'처럼 어긋나므로 환산 칸을 그대로 쓴다. 환산 칸이 비어 있는 옛 실행 건만 예전 값(원점수 · 지금 정책)을 쓴다.

실행:
    pytest tests/test_score_scaling.py -v
"""
import json
from types import SimpleNamespace as NS

from orch_fakes import (
    make_feature_match,
    make_outputs,
    make_plan_doc,
    make_score_view,
)

from app.models import VerificationPolicy


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '환산 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _check(no, name, weight, earned, applicable=True, passed=None, detail='설명'):
    return NS(no=no, name=name, weight=weight, earned=earned, applicable=applicable,
              passed=(earned == weight) if passed is None else passed, detail=detail, defect_sources=[])


# 그 실행 건 배점: 문서 50 · 코드 점검 20 · 계획서 대조 30 → 산출물층 50. 코드 점검 줄(환산): 얻은 점수 5 + 2(만점 3) + 해당 없음 0 + 12 = 19, 만점 5 + 3 + 0 + 12 = 20
SCALED_ITEMS = [_check(1, '실행', 5.0, 5.0), _check(2, '보안', 3.0, 2.0), _check(3, '접근성', 0.0, 0.0, applicable=False, passed=True,
                                                                                detail='해당 없음 — 이미지가 없음'),
                _check(4, '구조', 12.0, 12.0)]
RAW_ITEMS = [_check(1, '실행', 5.0, 5.0), _check(2, '보안', 3.0, 2.0)]


def _outputs(scaled=True):
    overall = make_score_view(total=82.0, threshold=80.0, passed=True)
    overall.artifact_score.code_check = NS(total=11.0, checks=RAW_ITEMS, gate_failures=[])  # 15점 기준 원점수
    overall.artifact_score.feature_match = make_feature_match(score=9.0)
    overall.doc_score = NS(total=40.0, items=[])
    if scaled:
        overall.doc_layer_max, overall.code_check_score, overall.code_check_max = 50.0, 19.0, 20.0
        overall.feature_match_score, overall.feature_match_max = 18.0, 30.0
        overall.artifact_layer_score, overall.artifact_layer_max = 35.0, 50.0
        overall.code_check_items = SCALED_ITEMS
    return make_outputs(
        step='결과물', progress='완료', category='웹개발', plan_doc=make_plan_doc(), doc_score=NS(total=40.0, items=[]),
        document_score_report=make_score_view(with_artifact=False, doc_layer_max=50.0 if scaled else None),
        overall_score_report=overall, code_check=overall.artifact_score.code_check, feature_match=overall.artifact_score.feature_match,
        prototype=NS(entry_file=NS(key='r/e/u/index.html')), infographic=NS(image_file=NS(key='r/e/u/infographic.svg')))


def _result(client, orch, scaled=True):
    pid = _create(client)
    orch.responses['outputs'] = lambda p: _outputs(scaled)
    r = client.get(f'/projects/{pid}/result')
    assert r.status_code == 200, r.text
    return r.json()


def test_verdict_uses_the_run_s_scaled_scores_and_maxima_not_the_current_policy(authed_client, orch, db_session):
    db_session.add(VerificationPolicy(doc_weight=70, code_weight=15, plan_weight=15, pass_threshold=80))  # 지금 정책은 70 · 15 · 15
    db_session.commit()

    verdict = _result(authed_client, orch)['verdict']

    assert (verdict['doc_score'], verdict['doc_max_score']) == (40.0, 50.0)
    assert (verdict['code_score'], verdict['code_max_score']) == (19.0, 20.0)
    assert (verdict['plan_match_score'], verdict['plan_match_max_score']) == (18.0, 30.0)
    assert (verdict['artifact_score'], verdict['artifact_max_score']) == (35.0, 50.0)


def test_old_runs_without_scaled_fields_keep_the_raw_scores_and_policy_maxima(authed_client, orch):
    body = _result(authed_client, orch, scaled=False)
    verdict, artifact = body['verdict'], body['plan']['artifacts'][0]

    assert (verdict['code_score'], verdict['code_max_score']) == (11.0, 15.0)      # 원점수 · 기본 만점
    assert (verdict['plan_match_score'], verdict['plan_match_max_score']) == (9.0, 15.0)
    assert verdict['artifact_score'] is None and verdict['artifact_max_score'] is None
    assert artifact['artifact_score'] == 30.0 and artifact['artifact_max_score'] is None  # 원점수 합


def test_artifact_layer_score_and_max_come_from_the_scaled_fields(authed_client, orch):
    artifact = _result(authed_client, orch)['plan']['artifacts'][0]

    assert (artifact['artifact_score'], artifact['artifact_max_score']) == (35.0, 50.0)


def test_code_check_rows_use_earned_so_partial_credit_counts_and_not_applicable_is_not_full_marks(authed_client, orch):
    reasons = {r['item_code']: r for r in _result(authed_client, orch)['plan']['artifacts'][0]['score_reasons']}

    assert (reasons['CHECK-보안']['score'], reasons['CHECK-보안']['max_score']) == (2.0, 3.0)   # 부분 점수(passed는 거짓)
    na = reasons['CHECK-접근성']
    assert (na['score'], na['max_score'], na['applicable']) == (0.0, 0.0, False)
    assert 'CHECK-접근성' in reasons and reasons['CHECK-실행']['applicable'] is True


def test_code_check_rows_add_up_to_the_scaled_layer_score_and_max(authed_client, orch):
    body = _result(authed_client, orch)
    rows = [r for r in body['plan']['artifacts'][0]['score_reasons'] if r['item_code'].startswith('CHECK-')]

    assert sum(r['score'] for r in rows) == body['verdict']['code_score']
    assert sum(r['max_score'] for r in rows) == body['verdict']['code_max_score']


def test_feature_match_row_uses_the_scaled_score_and_max(authed_client, orch):
    reasons = {r['item_code']: r for r in _result(authed_client, orch)['plan']['artifacts'][0]['score_reasons']}

    assert (reasons['FEATURE-MATCH']['score'], reasons['FEATURE-MATCH']['max_score']) == (18.0, 30.0)


def test_old_run_rows_fall_back_to_passed_when_earned_is_missing(authed_client, orch):
    """earned · applicable이 없는 옛 줄(검증-2 연동 전)은 예전처럼 passed로 점수를 만든다."""
    pid = _create(authed_client)
    outputs = _outputs(scaled=False)
    legacy = [NS(no=1, name='실행', weight=5.0, passed=True, detail='ok'), NS(no=2, name='보안', weight=10.0, passed=False, detail='no')]
    outputs.code_check.checks = legacy
    orch.responses['outputs'] = lambda p: outputs

    reasons = {r['item_code']: r for r in authed_client.get(f'/projects/{pid}/result').json()['plan']['artifacts'][0]['score_reasons']}

    assert (reasons['CHECK-실행']['score'], reasons['CHECK-보안']['score']) == (5.0, 0)
    assert reasons['CHECK-실행']['applicable'] is True


def test_plan_carries_the_document_layer_max(authed_client, orch):
    assert _result(authed_client, orch)['plan']['doc_max_score'] == 50.0
    assert _result(authed_client, orch, scaled=False)['plan']['doc_max_score'] is None
