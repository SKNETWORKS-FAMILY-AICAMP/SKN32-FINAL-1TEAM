"""GET /projects/{id}/result의 계획서 응답 모양 — 항목 번호 · 웹 태그 · 종류, 점수 항목의 태그, 그림 주소 (SB-337).

프론트(재희님)가 계획서 항목을 묶음(태그)별로 묶고, 점수 항목을 같은 항목 번호로 맞추고, 그림을 화면에 보여 주는 데 쓴다.
태그 없는 항목(일반현황 · 개요)은 tag가 null이고 content_type으로 본문 · 표 · 그림을 가른다.

실행:
    pytest tests/test_plan_result_shape.py -v
"""
import json
from types import SimpleNamespace as NS

from orch_fakes import make_diagram, make_file_ref, make_outputs, make_plan_doc, make_score_view, make_section, make_table_fallback


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '결과 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _sections():
    return [
        make_section('2.1.1', '일반현황 초안', '초안 문장'),
        make_section('2.3.6', '그림', content_type='image'),
        make_section('2.4.1', '문제인식 본문', '문제 문장', tag='1-1'),
        make_section('2.5.2', '개발계획 표', '표 글자', tag='2-1', content_type='table'),
        make_section('2.7.1', '대표자 역량', '역량 문장', tag='4-1'),
    ]


def _outputs(sections=None, diagrams=(), table_fallbacks=()):
    plan_doc = make_plan_doc(sections if sections is not None else _sections(), diagrams=list(diagrams))
    items = [NS(item_code=code, score=score, max_score=10.0, evidence_locator=None, comment=f'{code} 평가')
             for code, score in (('2.4.1', 9.0), ('2.5.2', 6.0), ('2.1.1', 8.0), ('없는번호', 5.0))]
    return make_outputs(
        plan_doc=plan_doc, table_fallbacks=list(table_fallbacks), doc_score=NS(total=28.0, items=items), document_score_report=make_score_view(with_artifact=False),
        evaluation_items=[NS(item_code=i.item_code, item_name=f'{i.item_code} 이름', max_score=10.0, description='') for i in items])


def _plan(authed_client, orch, **kwargs):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs(**kwargs)
    r = authed_client.get(f'/projects/{pid}/result')
    assert r.status_code == 200, r.text
    return pid, r.json()['plan']


def test_sections_carry_item_number_tag_and_content_type_in_separate_fields(authed_client, orch):
    _, plan = _plan(authed_client, orch)

    assert [(s['section_code'], s['tag'], s['content_type']) for s in plan['sections']] == [
        ('2.1.1', None, 'section'), ('2.3.6', None, 'image'), ('2.4.1', '1-1', 'section'),
        ('2.5.2', '2-1', 'table'), ('2.7.1', '4-1', 'section')]
    assert plan['sections'][2]['body'] == '문제 문장'
    assert plan['sections'][1]['body'] in (None, '')  # 그림 항목은 문장이 없다


def test_legacy_four_item_plan_keeps_its_item_number_as_the_tag(authed_client, orch):
    legacy = [make_section('1-1', '문제', '본문'), make_section('4-1', '팀', '팀 본문')]
    _, plan = _plan(authed_client, orch, sections=legacy)

    assert [(s['section_code'], s['tag']) for s in plan['sections']] == [('1-1', '1-1'), ('4-1', '4-1')]


def test_score_reasons_get_the_tag_of_the_plan_item_with_the_same_number(authed_client, orch):
    _, plan = _plan(authed_client, orch)

    assert {r['item_code']: r['tag'] for r in plan['score_reasons']} == {
        '2.4.1': '1-1', '2.5.2': '2-1', '2.1.1': None, '없는번호': None}  # 태그 없는 항목 · 계획서에 없는 번호는 null


def test_diagrams_come_with_titles_and_file_urls_user_flow_first(authed_client, orch):
    architecture = make_diagram(flow_type='SERVICE_ARCHITECTURE', image_file=make_file_ref('architecture.svg', key='k/e/u/architecture.svg'))
    flow = make_diagram(flow_type='USER_FLOW', nodes=['가입', '선택', '작성'], image_file=make_file_ref('userflow.svg', key='k/e/u/userflow.svg'))
    pid, plan = _plan(authed_client, orch, diagrams=[architecture, flow])

    assert [(d['diagram_id'], d['flow_type'], d['title'], d['source_ref']) for d in plan['diagrams']] == [
        ('2.3.6-USER_FLOW', 'USER_FLOW', '서비스 흐름도', '2.3.6'),
        ('2.3.6-SERVICE_ARCHITECTURE', 'SERVICE_ARCHITECTURE', '서비스 구조도', '2.3.6')]
    assert plan['diagrams'][0]['image_url'] == f'/projects/{pid}/artifact-files/k/e/u/userflow.svg'
    assert plan['diagrams'][0]['nodes'] == ['가입', '선택', '작성']


def test_no_diagrams_gives_an_empty_list(authed_client, orch):
    _, plan = _plan(authed_client, orch)

    assert plan['diagrams'] == []


def test_table_fallbacks_carry_the_reason_with_the_tag_and_title_of_the_item(authed_client, orch):
    fallbacks = [make_table_fallback('2.5.2', display_reason='입력한 사업비가 없어 표 대신 서술로 작성'),
                 make_table_fallback('9.9.9', reason='내부 원문 2', display_reason='계획서에 없는 번호')]
    _, plan = _plan(authed_client, orch, table_fallbacks=fallbacks)

    assert plan['table_fallbacks'] == [
        {'section_code': '2.5.2', 'tag': '2-1', 'title': '개발계획 표', 'display_reason': '입력한 사업비가 없어 표 대신 서술로 작성'},
        {'section_code': '9.9.9', 'tag': None, 'title': None, 'display_reason': '계획서에 없는 번호'}]
    assert next(s for s in plan['sections'] if s['section_code'] == '2.5.2')['body'] == '표 글자'  # 사유는 본문에 섞이지 않는다


def test_no_table_fallbacks_gives_an_empty_list(authed_client, orch):
    _, plan = _plan(authed_client, orch)

    assert plan['table_fallbacks'] == []


def test_table_fallback_does_not_expose_the_internal_reason(authed_client, orch):
    _, plan = _plan(authed_client, orch, table_fallbacks=[make_table_fallback()])

    assert 'reason' not in plan['table_fallbacks'][0]
    assert '내부 진단 원문' not in str(plan)


def test_score_notices_come_from_each_report_document_for_the_plan_and_overall_for_the_verdict(authed_client, orch):
    pid = _create(authed_client)
    outputs = _outputs()
    outputs.document_score_report = make_score_view(with_artifact=False, notices=['문서 안내'])
    outputs.overall_score_report = make_score_view(notices=['입력 확인 필요 안내', '입력 오류 안내'])
    orch.responses['outputs'] = lambda p: outputs
    body = authed_client.get(f'/projects/{pid}/result').json()

    assert body['plan']['notices'] == ['문서 안내']
    assert body['verdict']['notices'] == ['입력 확인 필요 안내', '입력 오류 안내']


def test_no_score_notices_gives_empty_lists(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs()
    body = authed_client.get(f'/projects/{pid}/result').json()

    assert body['plan']['notices'] == []


def test_deliverable_notes_come_from_the_deliverable_and_the_user_message(authed_client, orch):
    pid = _create(authed_client)
    outputs = _outputs()
    outputs.deliverable = NS(submission_notice='공고별 제출 요건을 확인하세요.', disclaimer='제출 전 본인 확인이 필요합니다.',
                             plan_doc_file=None, prototype_files=[], infographic_file=None)
    outputs.user_message = '미달 항목: 2.4.1 문제 정의'
    orch.responses['outputs'] = lambda p: outputs
    body = authed_client.get(f'/projects/{pid}/result').json()

    assert body['deliverable'] == {'submission_notice': '공고별 제출 요건을 확인하세요.', 'disclaimer': '제출 전 본인 확인이 필요합니다.',
                                   'user_message': '미달 항목: 2.4.1 문제 정의'}
    assert 'plan_doc_file' not in str(body['deliverable'])  # 파일 참조는 싣지 않는다


def test_deliverable_is_null_before_the_deliverable_exists_and_empty_fields_are_null(authed_client, orch):
    pid = _create(authed_client)
    orch.responses['outputs'] = lambda p: _outputs()
    assert authed_client.get(f'/projects/{pid}/result').json()['deliverable'] is None

    outputs = _outputs()
    outputs.deliverable = NS(submission_notice='', disclaimer='', plan_doc_file=None, prototype_files=[], infographic_file=None)
    orch.responses['outputs'] = lambda p: outputs
    assert authed_client.get(f'/projects/{pid}/result').json()['deliverable'] == {
        'submission_notice': None, 'disclaimer': None, 'user_message': None}
