"""사업비 · 추진 일정 필수 확인 (SB-332).

스위치(REQUIRE_BUDGET_SCHEDULE)가 꺼져 있으면(기본) 아무것도 막지 않는다 — 입력 화면이 배포되기 전에 켜면 모든 계획서 작성이 막히기
때문이다. 켜면 사업비 1건 이상, 예비창업은 1단계 · 2단계 각 1건 이상, 협약기간 내(feasibility) 일정 1건 이상을 요구하고, 어기면
오케스트레이터의 필수 확인과 같은 모양(E-C1-REQUIRED · missing 이름)으로 422를 준다. 협약 이후(growth) 일정은 선택이다."""
import json

import pytest

from app import schemas
from app.models import Project, ProjectBudgetItem
from app.routers import projects as projects_router


def _budget(**overrides):
    row = {'category': '외주용역비', 'execution_plan': '앱 개발 외주', 'total_amount': 100,
           'government_amount': 100, 'self_cash_amount': 0, 'self_in_kind_amount': 0}
    row.update(overrides)
    return row


def _schedule(**overrides):
    row = {'section': 'feasibility', 'category': '개발', 'content': '모델 고도화', 'period': '2026.05~2026.07'}
    row.update(overrides)
    return row


def _body(applicant_type='corp', **overrides):
    base = {'applicant_type': applicant_type, 'ceo_name': '가', 'description': '아이디어'}
    base.update(overrides)
    return schemas.ProjectCreateRequest.model_validate(base)


def _form(applicant_type='corp', **overrides):
    base = {'applicant_type': applicant_type, 'biz_type': '법인', 'ceo_name': '박테스트', 'founded_at': '2024-01-01',
            'description': 'AI 기반 서비스', 'team_members': [], 'pricing_items': []}
    base.update(overrides)
    return {'payload': json.dumps(base)}


# ── 조건 계산 ────────────────────────────────────────────────────────────────────────────
def test_nothing_missing_when_every_condition_is_met():
    body = _body('corp', budget_items=[_budget()], schedule_items=[_schedule()])
    assert projects_router.missing_budget_schedule(body) == []


def test_business_owner_without_anything_misses_budget_and_agreement_schedule():
    assert projects_router.missing_budget_schedule(_body('corp')) == ['사업비 집행계획', '추진 일정(협약기간 내)']
    assert projects_router.missing_budget_schedule(_body('individual')) == ['사업비 집행계획', '추진 일정(협약기간 내)']


def test_preliminary_without_anything_also_misses_both_phases():
    assert projects_router.missing_budget_schedule(_body('preliminary')) == [
        '사업비 집행계획', '사업비 집행계획(1단계)', '사업비 집행계획(2단계)', '추진 일정(협약기간 내)']


def test_preliminary_needs_both_phases():
    only_first = _body('preliminary', budget_items=[_budget(phase='1단계')], schedule_items=[_schedule()])
    assert projects_router.missing_budget_schedule(only_first) == ['사업비 집행계획(2단계)']
    only_second = _body('preliminary', budget_items=[_budget(phase='2단계')], schedule_items=[_schedule()])
    assert projects_router.missing_budget_schedule(only_second) == ['사업비 집행계획(1단계)']
    both = _body('preliminary', budget_items=[_budget(phase='1단계'), _budget(phase='2단계')], schedule_items=[_schedule()])
    assert projects_router.missing_budget_schedule(both) == []


def test_business_owner_does_not_need_phases():
    body = _body('corp', budget_items=[_budget()], schedule_items=[_schedule()])
    assert '사업비 집행계획(1단계)' not in projects_router.missing_budget_schedule(body)


def test_growth_schedule_alone_does_not_satisfy_the_agreement_schedule():
    body = _body('corp', budget_items=[_budget()], schedule_items=[_schedule(section='growth')])
    assert projects_router.missing_budget_schedule(body) == ['추진 일정(협약기간 내)']


def test_growth_schedule_is_optional():
    body = _body('corp', budget_items=[_budget()], schedule_items=[_schedule()])
    assert all(s.section == 'feasibility' for s in body.schedule_items)
    assert projects_router.missing_budget_schedule(body) == []


# ── 스위치 ──────────────────────────────────────────────────────────────────────────────
def test_switch_is_off_by_default():
    assert projects_router.REQUIRE_BUDGET_SCHEDULE is False


def test_nothing_is_blocked_while_the_switch_is_off(authed_client, db_session):
    r = authed_client.post('/projects', data=_form())
    assert r.status_code == 201, r.text
    assert db_session.query(Project).count() == 1


@pytest.fixture()
def switch_on(monkeypatch):
    monkeypatch.setattr(projects_router, 'REQUIRE_BUDGET_SCHEDULE', True)


def test_switch_on_blocks_with_e_c1_required_and_saves_nothing(authed_client, db_session, orch, switch_on):
    r = authed_client.post('/projects', data=_form())
    assert r.status_code == 422, r.text
    assert r.json()['code'] == 'E-C1-REQUIRED'
    assert r.json()['detail'] == {
        'message': '필수 항목이 비어 있어요', 'code': 'E-C1-REQUIRED', 'missing': ['사업비 집행계획', '추진 일정(협약기간 내)']}
    assert db_session.query(Project).count() == 0
    assert not [c for c in orch.calls if c[0] == 'request_start']


def test_switch_on_blocks_a_preliminary_project_missing_the_second_phase(authed_client, db_session, switch_on):
    payload = _form('preliminary', budget_items=[_budget(phase='1단계')], schedule_items=[_schedule()])
    r = authed_client.post('/projects', data=payload)
    assert r.status_code == 422, r.text
    assert r.json()['detail']['missing'] == ['사업비 집행계획(2단계)']
    assert db_session.query(Project).count() == 0


def test_switch_on_lets_a_complete_project_through(authed_client, db_session, switch_on):
    payload = _form('corp', budget_items=[_budget()], schedule_items=[_schedule()])
    r = authed_client.post('/projects', data=payload)
    assert r.status_code == 201, r.text
    assert db_session.query(ProjectBudgetItem).count() == 1
