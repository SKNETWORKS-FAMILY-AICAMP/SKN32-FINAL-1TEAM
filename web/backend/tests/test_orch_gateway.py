"""app/orch/gateway.py — 허용 목록 · 오류 변환 · 초기화."""
import pytest
from orch_fakes import FakeOrch, ProjectView, make_run

from app.orch import gateway as gw
from app.orch.errors import OrchError


def test_allowed_call_passes_args_and_returns_value():
    view = ProjectView(project_id='7', run=make_run())
    orch = FakeOrch(view_project=view)
    result = gw.OrchGateway(orch).view_project(7)
    assert result is view
    assert orch.calls == [('view_project', (7,), {})]


def test_keyword_arguments_are_forwarded():
    orch = FakeOrch(wait_project=ProjectView(project_id='7'))
    gw.OrchGateway(orch).wait_project(7, timeout_sec=5)
    assert orch.calls == [('wait_project', (7,), {'timeout_sec': 5})]


@pytest.mark.parametrize('name', [
    'advance', 'tick', 'resume', 'run_start_request', 'start_run', 'start_run_for_project', 'decide', 'abort',
])
def test_pre_stage_and_worker_functions_are_blocked_without_calling(name):
    orch = FakeOrch()
    with pytest.raises(OrchError) as err:
        getattr(gw.OrchGateway(orch), name)
    assert err.value.code == 'WEB_NOT_ALLOWED'
    assert orch.calls == []


def test_private_names_are_plain_attribute_errors():
    with pytest.raises(AttributeError):
        getattr(gw.OrchGateway(FakeOrch()), '_anything')  # noqa: B009 -- 이름 앞 밑줄 동작을 일부러 확인


def test_command_error_becomes_orch_error():
    errors = pytest.importorskip('sbrain.orchestrator.errors')
    orch = FakeOrch(request_rework_for_project=errors.CommandError('E-G2-LIMIT', '문제인식'))
    with pytest.raises(OrchError) as err:
        gw.OrchGateway(orch).request_rework_for_project(7, '문제인식')
    assert (err.value.code, err.value.detail) == ('E-G2-LIMIT', '문제인식')


def test_orch_error_passes_through_unchanged():
    original = OrchError('BUSY', 'x')
    with pytest.raises(OrchError) as err:
        gw.OrchGateway(FakeOrch(abort_project=original)).abort_project(7)
    assert err.value is original


def test_other_exceptions_propagate_unchanged():
    with pytest.raises(ValueError, match='boom'):
        gw.OrchGateway(FakeOrch(view_project=ValueError('boom'))).view_project(7)


def test_account_id_is_user_id_as_string():
    assert gw.account_id_of(42) == '42'


def test_get_gateway_requires_init_and_reset_clears():
    gw.reset_gateway()
    with pytest.raises(RuntimeError):
        gw.get_gateway()
    gateway = gw.OrchGateway(FakeOrch())
    gw.init_gateway(gateway)
    try:
        assert gw.get_gateway() is gateway
    finally:
        gw.reset_gateway()
    with pytest.raises(RuntimeError):
        gw.get_gateway()


def test_default_db_url_prefers_sbrain_env_and_refuses_sqlite(monkeypatch):
    monkeypatch.setenv('SBRAIN_DB_URL', 'mysql+pymysql://u:p@h/db')
    assert gw._default_db_url() == 'mysql+pymysql://u:p@h/db'
    monkeypatch.delenv('SBRAIN_DB_URL')
    with pytest.raises(RuntimeError, match='MySQL'):
        gw._default_db_url()  # 테스트는 DB_BACKEND=sqlite로 돈다
