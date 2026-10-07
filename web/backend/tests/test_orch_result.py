"""[SB-243] GET /projects/{id}/result — outputs()를 웹 응답(DemoGenerateResponse)으로 바꾼다."""
import json
from types import SimpleNamespace as NS

from orch_fakes import (
    Card,
    Dumpable,
    make_feature_match,
    make_gate,
    make_outputs,
    make_plan_doc,
    make_proofread_screen,
    make_score_view,
    make_section,
    make_sentence_change,
)

from app.orch import OrchError


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '결과 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _result(client, pid):
    return client.get(f'/projects/{pid}/result')


def test_result_404_when_no_run(authed_client):
    pid = _create(authed_client)
    assert _result(authed_client, pid).status_code == 404


def test_result_404_while_plan_is_not_written_yet(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: make_outputs(step='계획서작성', progress='실행', plan_doc=None)
    r = _result(authed_client, pid)
    assert r.status_code == 404 and '계획서' in r.json()['detail']
    assert r.json()['code'] == 'PLAN_NOT_READY'


def test_result_409_when_run_failed_or_aborted(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = OrchError('RUN_NOT_VIEWABLE', 'x')
    r = _result(authed_client, pid)
    assert r.status_code == 409 and r.json()['code'] == 'RUN_NOT_VIEWABLE'


def test_result_requires_ownership(login_as, orch):
    pid = _create(login_as('owner@example.com'))
    orch.responses['outputs'] = lambda p: make_outputs(plan_doc=make_plan_doc())
    assert _result(login_as('other@example.com'), pid).status_code == 404


def test_result_with_plan_only_has_no_verdict_or_artifacts(authed_client, orch):
    pid = _create(authed_client)
    sections = [make_section('1-1', '문제 인식', '첫 문단.', '둘째 문단.')]
    sections[0].sentences[1].paragraph_no = 1  # 같은 문단이면 이어 붙는다
    orch.responses['outputs'] = lambda p: make_outputs(
        plan_doc=make_plan_doc(sections),
        doc_score=NS(total=18.0, items=[NS(item_code='문제인식', score=18.0, max_score=20.0, evidence_locator=None, comment='좋아요')]),
        document_score_report=make_score_view(threshold=80.0, with_artifact=False),
        evaluation_items=[NS(item_code='문제인식', item_name='문제 인식', max_score=20.0, description='')],
        gate_result=make_gate(), business_age_years=2.5, candidates=[Card(announcement_id='N-01', title='공고1')],
        selected_announcement=NS(announcement_id='N-01', title='공고1'))

    body = _result(authed_client, pid).json()

    assert body['verdict'] is None
    assert body['eligibility']['business_age_years'] == 2.5 and body['eligibility']['can_start_writing'] is True  # [SB-274]
    assert body['plan']['plan_id'] is None
    assert body['plan']['sections'] == [{'tag': '1-1', 'title': '문제 인식', 'body': '첫 문단. 둘째 문단.'}]
    assert body['plan']['doc_score'] == 18.0 and body['plan']['threshold'] == 80.0
    assert body['plan']['score_reasons'] == [{
        'reason_text': '좋아요', 'item_code': '문제인식', 'display_name': '문제 인식', 'score': 18.0, 'max_score': 20.0}]
    assert body['plan']['artifacts'] == []
    assert body['plan']['feature_list'] == ['예약', '결제']
    assert body['eligibility']['passed'] is True
    assert body['match']['notice_id'] == 'N-01' and body['match']['fit_score'] == 0.8
    assert 'agent_executions' not in body  # [SB-247] 관리자 조회가 대신한다


def test_result_paragraphs_are_separated_by_newlines(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: make_outputs(
        plan_doc=make_plan_doc([make_section('2-1', '실현 가능성', '문단1', '문단2')]))
    body = _result(authed_client, pid).json()
    assert body['plan']['sections'][0]['body'] == '문단1\n문단2'


def test_result_charts_and_tables_are_passed_through(authed_client, orch):
    pid = _create(authed_client)
    chart = Dumpable(chart_id='c1', type='bar', title='시장 규모')
    table = Dumpable(table_id='t1', title='경쟁사', headers=['이름'], rows=[['A']])
    orch.responses['outputs'] = lambda p: make_outputs(plan_doc=make_plan_doc(charts=[chart], tables=[table]))
    plan = _result(authed_client, pid).json()['plan']
    assert plan['charts'] == [{'chart_id': 'c1', 'type': 'bar', 'title': '시장 규모'}]
    assert plan['tables'][0]['headers'] == ['이름']


def _full_outputs(category='웹개발', **overrides):
    checks = [NS(no=1, name='실행', weight=5.0, passed=True, detail='잘 돌아가요'),
              NS(no=2, name='보안', weight=10.0, passed=False, detail='키가 노출돼요')]
    report = make_score_view(total=82.0, threshold=80.0, passed=True)
    report.artifact_score.code_check = NS(total=5.0, checks=checks)
    report.artifact_score.feature_match = make_feature_match(
        score=12.0, missing_features=['결제'], findings=['로그인 일부 누락'], judged_by='AI')
    base = dict(
        step='결과물', progress='완료', category=category, plan_doc=make_plan_doc(),
        doc_score=NS(total=52.0, items=[]), document_score_report=make_score_view(with_artifact=False),
        overall_score_report=report,
        prototype=NS(entry_file_path='/uploads/p/index.html'), infographic=NS(image_path='/uploads/p/info.png'),
        code_check=report.artifact_score.code_check, feature_match=report.artifact_score.feature_match,
        format_findings=[NS(sentence_id='s1', violation_type='띄어쓰기', detail='붙여 쓴 곳이 있어요')],
        rework_usage=[NS(bundle_id='문제인식', layer='document', used_count=1, remaining=0),
                      NS(bundle_id='실행 파일', layer='artifact', used_count=0, remaining=1)],
        rework_limit=1)
    base.update(overrides)
    return make_outputs(**base)


def test_result_maps_verdict_artifact_and_bundle_usages(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _full_outputs()
    body = _result(authed_client, pid).json()

    verdict = body['verdict']
    assert verdict['overall_passed'] is True
    assert verdict['total_score'] == 82.0 and verdict['pass_threshold'] == 80.0
    assert verdict['doc_score'] == 52.0 and verdict['code_score'] == 5.0 and verdict['plan_match_score'] == 12.0
    # 웹 정책 행이 없으면 기본 만점(문서 70 · 코드 15 · 대조 15)
    assert (verdict['doc_max_score'], verdict['code_max_score'], verdict['plan_match_max_score']) == (70.0, 15.0, 15.0)
    assert verdict['model_version'] is None and verdict['first_pass_passed'] is None
    assert verdict['plan_match_withheld'] is False

    artifact = body['plan']['artifacts'][0]
    assert artifact['category'] == 'webdev'
    assert artifact['executable_path'] == '/uploads/p/index.html'
    assert artifact['infographic_path'] == '/uploads/p/info.png'
    assert artifact['artifact_score'] == 30.0
    reasons = {r['item_code']: r for r in artifact['score_reasons']}
    assert reasons['CHECK-실행']['score'] == 5.0 and reasons['CHECK-실행']['max_score'] == 5.0
    assert reasons['CHECK-보안']['score'] == 0 and reasons['CHECK-보안']['max_score'] == 10.0
    assert reasons['FEATURE-MATCH']['score'] == 12.0
    assert '누락 기능: 결제' in reasons['FEATURE-MATCH']['reason_text']

    assert body['plan']['format_findings'] == [{
        'finding_type': '띄어쓰기', 'message': '붙여 쓴 곳이 있어요', 'severity': None, 'sentence_id': 's1'}]
    assert body['rework_cap'] == 1
    assert body['bundle_usages'] == [
        {'bundle_id': '문제인식', 'layer': 'document', 'used': 1, 'remaining': 0},
        {'bundle_id': '실행 파일 제작', 'layer': 'artifact', 'used': 0, 'remaining': 1},
    ]


def test_onepage_result_has_no_executable_path(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _full_outputs(category='원페이지')
    artifact = _result(authed_client, pid).json()['plan']['artifacts'][0]
    assert artifact['category'] == 'onepage' and artifact['executable_path'] is None


def test_result_proofread_attempts_become_logs_grouped_by_sentence(authed_client, orch):
    pid = _create(authed_client)
    ok = NS(passed=True, missing_tokens=[], altered_tokens=[], contaminated_tokens=[])
    bad = NS(passed=False, missing_tokens=['1억원'], altered_tokens=['A'], contaminated_tokens=['B'])
    results = [NS(sentence_id='s1', adopted=True, revised=None, kept_reason=None, final_redo_count=1, token_check=ok, attempts=[
        NS(attempt_no=1, text='시도1', adopted=False, token_check=bad, violation_type='수치·금액'),
        NS(attempt_no=2, text='시도2', adopted=True, token_check=ok, violation_type=None)])]
    plan_doc = make_plan_doc([make_section('1-1', '문제', '원문 문장')])
    plan_doc.sections[0].sentences[0].sentence_id = 's1'
    orch.responses['outputs'] = lambda p: _full_outputs(plan_doc=plan_doc, sentence_results=results)
    orch.responses['screen'] = lambda p, n: make_proofread_screen([make_sentence_change('s1', '원문 문장')])

    logs = _result(authed_client, pid).json()['plan']['proofread_logs']

    assert [(log['attempt_no'], log['passed'], log['corrected_text']) for log in logs] == [(1, False, '시도1'), (2, True, '시도2')]
    assert all(log['section_id'] == 's1' and log['original_text'] == '원문 문장' for log in logs)
    assert logs[0]['violation_type'] == '수치·금액'
    assert logs[0]['violation_note'] == '빠짐: 1억원 / 바뀜: A / 섞임: B'
    assert logs[1]['violation_note'] is None


# ── [SB-301] 계획서 대조 보류 — "대조 불가" ─────────────────────────────────────────────────
def _withheld_outputs():
    outputs = _full_outputs()
    withheld = make_feature_match(
        score=0.0, findings=['기능 목록이 비어 있어요'], judged_by='규칙', withheld=True, withheld_reason='E-V2-NOFEATURE')
    outputs.overall_score_report.artifact_score.feature_match = withheld
    outputs.feature_match = withheld
    return outputs


def test_result_marks_withheld_plan_match(authed_client, orch):
    """대조가 보류되면 점수는 0점으로 합산되어 오지만 화면은 0점이 아니라 '대조 불가'로 보여 줘야 한다."""
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _withheld_outputs()
    body = _result(authed_client, pid).json()

    verdict = body['verdict']
    assert verdict['plan_match_withheld'] is True
    assert verdict['plan_match_score'] == 0.0 and verdict['plan_match_max_score'] == 15.0
    assert verdict['total_score'] == 82.0  # 총점은 오케스트레이터 값 그대로(웹이 다시 계산하지 않는다)
    reasons = {r['item_code']: r for r in body['plan']['artifacts'][0]['score_reasons']}
    assert '대조 불가' in reasons['FEATURE-MATCH']['reason_text']
    assert reasons['FEATURE-MATCH']['score'] == 0.0 and reasons['FEATURE-MATCH']['max_score'] == 15.0
    assert 'E-V2-NOFEATURE' not in str(body)  # 보류 사유 코드는 사용자에게 내지 않는다


def test_result_without_withheld_keeps_findings_text(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _full_outputs()
    body = _result(authed_client, pid).json()
    reasons = {r['item_code']: r for r in body['plan']['artifacts'][0]['score_reasons']}
    assert '로그인 일부 누락' in reasons['FEATURE-MATCH']['reason_text']
    assert '대조 불가' not in reasons['FEATURE-MATCH']['reason_text']


# ── [SB-297] 검수 전 원문 ─────────────────────────────────────────────────────────────────
def _reviewed_outputs(plan_text: str):
    """표현 검수가 끝난 결과 — 현재 계획서(planDoc)의 문장은 채택된 검수 결과 문장이다."""
    ok = NS(passed=True, missing_tokens=[], altered_tokens=[], contaminated_tokens=[])
    results = [NS(sentence_id='s1', adopted=True, revised=None, kept_reason=None, final_redo_count=0, token_check=ok, attempts=[
        NS(attempt_no=1, text='검수 결과 문장', adopted=True, token_check=ok, violation_type=None)])]
    plan_doc = make_plan_doc([make_section('1-1', '문제', plan_text)])
    plan_doc.sections[0].sentences[0].sentence_id = 's1'
    return _full_outputs(plan_doc=plan_doc, sentence_results=results)


def test_result_original_text_comes_from_screen_10_not_the_revised_plan(authed_client, orch):
    """검수가 끝나면 계획서 문장이 검수 결과 문장으로 바뀐다 — 검수 전 원문은 화면 10의 before에서 읽어야 한다."""
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _reviewed_outputs('검수 결과 문장')
    orch.responses['screen'] = lambda p, n: make_proofread_screen([make_sentence_change('s1', '검수 전 원문 문장', '검수 결과 문장', True)])

    logs = _result(authed_client, pid).json()['plan']['proofread_logs']

    assert [(log['original_text'], log['corrected_text']) for log in logs] == [('검수 전 원문 문장', '검수 결과 문장')]
    assert [args for name, args, _ in orch.calls if name == 'screen'] == [(pid, 10)]


def test_result_original_text_falls_back_to_plan_while_screen_10_is_closed(authed_client, orch):
    """화면 10이 아직 열리지 않았으면(검수 중) 계획서가 바뀌기 전이라 계획서 문장이 원문이다."""
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _reviewed_outputs('아직 바뀌지 않은 원문')
    orch.responses['screen'] = OrchError('SCREEN_NOT_READY', '화면 10')

    logs = _result(authed_client, pid).json()['plan']['proofread_logs']

    assert [log['original_text'] for log in logs] == ['아직 바뀌지 않은 원문']


def test_result_does_not_open_screen_10_without_proofread_attempts(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _full_outputs()

    assert _result(authed_client, pid).status_code == 200
    assert [name for name, _, _ in orch.calls if name == 'screen'] == []


def test_result_screen_10_errors_other_than_not_ready_are_not_hidden(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _reviewed_outputs('x')
    orch.responses['screen'] = OrchError('RUN_NOT_FOUND', 'x')

    assert _result(authed_client, pid).status_code == 404


# ── 기획서 v1.11 4-5 · 5-4: 통과 필수 조건 결과 · 대조 누락 · 부분 인정 기능 ──────────────────────────────
def test_artifact_has_empty_gate_failures_and_features_by_default(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _full_outputs()
    artifact = _result(authed_client, pid).json()['plan']['artifacts'][0]
    assert artifact['gate_failures'] == [] and artifact['partial_features'] == []
    assert artifact['missing_features'] == ['결제']  # _full_outputs의 대조 결과


def test_gate_failures_are_named_for_the_screen(authed_client, orch):
    """통과 필수 조건을 어기면 산출물층이 0점이 되므로 화면이 어긴 조건을 이름으로 보여 줄 수 있어야 한다."""
    pid = _create(authed_client)
    outputs = _full_outputs()
    outputs.code_check.gate_failures = ['entry', 'sandbox']
    orch.responses['outputs'] = lambda p: outputs
    artifact = _result(authed_client, pid).json()['plan']['artifacts'][0]
    assert artifact['gate_failures'] == [
        {'code': 'entry', 'display_name': '진입 파일'}, {'code': 'sandbox', 'display_name': '격리 화면 동작'}]


def test_unknown_gate_code_is_passed_through_by_code(authed_client, orch):
    pid = _create(authed_client)
    outputs = _full_outputs()
    outputs.code_check.gate_failures = ['secret', 'brand-new']
    orch.responses['outputs'] = lambda p: outputs
    names = {g['code']: g['display_name'] for g in _result(authed_client, pid).json()['plan']['artifacts'][0]['gate_failures']}
    assert names == {'secret': '비밀값', 'brand-new': 'brand-new'}


def test_partial_features_are_listed_and_explained(authed_client, orch):
    pid = _create(authed_client)
    outputs = _full_outputs()
    outputs.feature_match.partial_features = ['알림']
    orch.responses['outputs'] = lambda p: outputs
    artifact = _result(authed_client, pid).json()['plan']['artifacts'][0]
    assert artifact['partial_features'] == ['알림'] and artifact['missing_features'] == ['결제']
    reasons = {r['item_code']: r for r in artifact['score_reasons']}
    assert '부분 인정 기능: 알림' in reasons['FEATURE-MATCH']['reason_text']
    assert '누락 기능: 결제' in reasons['FEATURE-MATCH']['reason_text']


def test_withheld_match_lists_no_features(authed_client, orch):
    """대조가 보류되면 기능을 판정하지 않은 것이라 누락 · 부분 목록을 내지 않는다."""
    pid = _create(authed_client)
    outputs = _full_outputs()
    outputs.feature_match.withheld = True
    outputs.feature_match.partial_features = ['알림']
    orch.responses['outputs'] = lambda p: outputs
    artifact = _result(authed_client, pid).json()['plan']['artifacts'][0]
    assert artifact['missing_features'] == [] and artifact['partial_features'] == []
