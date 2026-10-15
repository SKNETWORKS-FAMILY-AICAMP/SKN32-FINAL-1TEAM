"""평가 항목이 계획서 항목마다 하나(24 ~ 25개)가 되어도 문서층 점수 응답이 그대로 나온다 (SB-338).

SB-310 이후 outputs.evaluationItems · docScore.items는 계획서 항목 하나하나다(itemCode = 항목 번호, itemName = 항목 제목 앞 40자,
배점 = 문서층 배점 ÷ 항목 수). 편차 검사는 하지 않아 varianceFlag는 늘 거짓이고, 웹은 이 값을 읽지 않는다. 관리자 설정의 편차 상한(deviation_cap)은
저장만 한다."""
import json
from types import SimpleNamespace as NS

from orch_fakes import make_gate, make_outputs, make_plan_doc, make_score_view

from app import schemas


def _create(client) -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': '점수 항목 테스트'})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _codes(count: int, prefix: str = '2') -> list[str]:
    """예비창업 양식 항목 번호 — 2.1.1 ~ 2.7.4 중 count개(순서만 의미 있다)."""
    return [f'{prefix}.{i // 4 + 1}.{i % 4 + 1}' for i in range(count)]


def _outputs(count: int, per_item: float, *, unnamed: tuple[str, ...] = ()):
    codes = _codes(count)
    items = [NS(item_code=c, score=round(per_item - (0.1 if n % 5 == 0 else 0), 2), max_score=per_item, evidence_locator=None,
                comment=f'{c} 근거') for n, c in enumerate(codes)]
    names = [NS(item_code=c, item_name=f'{c} 항목 제목 ' + '가' * 30, max_score=per_item, description='') for c in codes if c not in unnamed]
    total = round(sum(i.score for i in items), 2)
    return codes, items, make_outputs(
        plan_doc=make_plan_doc(), doc_score=NS(total=total, items=items), evaluation_items=names, gate_result=make_gate(),
        document_score_report=make_score_view(total=total, with_artifact=False))


def test_25_items_come_back_in_order_with_names_and_float_scores(authed_client, orch):
    pid = _create(authed_client)
    codes, items, outputs = _outputs(25, 2.8)
    orch.responses['outputs'] = lambda p: outputs
    plan = authed_client.get(f'/projects/{pid}/result').json()['plan']

    reasons = plan['score_reasons']
    assert [r['item_code'] for r in reasons] == codes
    assert all(r['display_name'] == f"{r['item_code']} 항목 제목 " + '가' * 30 for r in reasons)  # 제목 앞 40자 그대로 내려간다
    assert all(r['max_score'] == 2.8 for r in reasons)
    assert [r['score'] for r in reasons] == [i.score for i in items]
    assert [r['reason_text'] for r in reasons] == [f'{c} 근거' for c in codes]
    assert abs(sum(r['score'] for r in reasons) - plan['doc_score']) < 0.01  # 항목 점수를 더하면 문서층 총점


def test_24_items_for_business_owners_work_the_same(authed_client, orch):
    pid = _create(authed_client)
    codes = [f'3.{i // 4 + 1}.{i % 4 + 1}' for i in range(24)]
    items = [NS(item_code=c, score=2.9, max_score=2.9, evidence_locator=None, comment='') for c in codes]
    orch.responses['outputs'] = lambda p: make_outputs(
        plan_doc=make_plan_doc(), doc_score=NS(total=69.6, items=items), gate_result=make_gate(),
        evaluation_items=[NS(item_code=c, item_name=c, max_score=2.9, description='') for c in codes],
        document_score_report=make_score_view(total=69.6, with_artifact=False))
    plan = authed_client.get(f'/projects/{pid}/result').json()['plan']
    assert len(plan['score_reasons']) == 24
    assert plan['score_reasons'][0]['reason_text'] == ''  # 근거가 비어도 항목은 그대로 나온다


def test_item_without_a_matching_evaluation_item_has_no_display_name(authed_client, orch):
    pid = _create(authed_client)
    codes, _items, outputs = _outputs(25, 2.8, unnamed=('2.1.1',))
    orch.responses['outputs'] = lambda p: outputs
    reasons = authed_client.get(f'/projects/{pid}/result').json()['plan']['score_reasons']
    assert reasons[0]['item_code'] == '2.1.1' and reasons[0]['display_name'] is None
    assert reasons[1]['display_name'] is not None


def test_result_has_no_variance_field(authed_client, orch):
    """편차 검사를 하지 않는다(varianceFlag 늘 거짓) — 웹 응답에 편차 칸이 없다."""
    pid = _create(authed_client)
    _codes_, _items, outputs = _outputs(25, 2.8)
    orch.responses['outputs'] = lambda p: outputs
    body = authed_client.get(f'/projects/{pid}/result').json()
    assert 'variance' not in json.dumps(body).lower()


def test_deviation_cap_is_documented_as_stored_but_unused():
    for model in (schemas.PolicyThresholdsIn, schemas.VerificationPolicyOut):
        description = model.model_json_schema()['properties']['deviation_cap']['description']
        assert '쓰이지 않는다' in description and '저장만' in description
