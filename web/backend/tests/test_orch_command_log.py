"""app/orch/command_log.py — 웹이 넣은 상태 변경 명령을 웹 로그에 한 줄씩 남긴다 (SB-303)."""
import logging
import re
from types import SimpleNamespace as NS

import pytest

from app.logging_config import web_logger
from app.orch import OrchError
from app.orch.gateway import OrchGateway


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def log_lines():
    """web_logger는 propagate=False라 caplog로 못 잡는다 — 핸들러를 잠깐 붙여 줄을 모은다."""
    handler = _ListHandler()
    web_logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        web_logger.removeHandler(handler)


class _FakeOrch:
    """명령 · 읽기 함수를 흉내 낸다. 동작은 responses로 정한다(값 또는 던질 예외)."""

    def __init__(self, **responses) -> None:
        self.responses = responses
        self.calls: list[tuple] = []

    def _answer(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        value = self.responses.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    def view_project(self, project_id):
        return self._answer('view_project', project_id)

    def abort_project(self, project_id):
        return self._answer('abort_project', project_id)

    def decide_for_project(self, project_id, screen, action, confirmed=False):
        return self._answer('decide_for_project', project_id, screen, action, confirmed=confirmed)

    def request_start(self, account_id, project_id):
        return self._answer('request_start', account_id, project_id)

    def delete_account_data(self, account_id):
        return self._answer('delete_account_data', account_id)

    def start_writing_for_project(self, project_id):
        return self._answer('start_writing_for_project', project_id)

    def select_announcement_for_project(self, project_id, announcement_id):
        return self._answer('select_announcement_for_project', project_id, announcement_id)

    def request_rework_for_project(self, project_id, bundle):
        return self._answer('request_rework_for_project', project_id, bundle)

    def delete_project_data(self, project_id):
        return self._answer('delete_project_data', project_id)


def _run_view(step='종합평가', progress='사용자대기'):
    return NS(run=NS(step=step, progress=progress))


def _cmd_lines(records) -> list[str]:
    return [r.getMessage() for r in records if r.getMessage().startswith('cmd ')]


def test_decide_logs_project_command_args_and_resulting_state(log_lines):
    orch = _FakeOrch(view_project=_run_view('종합평가', '사용자대기'))
    OrchGateway(orch, log_state=True).decide_for_project(7, 8, '진행')

    (line,) = _cmd_lines(log_lines)
    assert re.match(r'^cmd at=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z project_id=7 command=decide_for_project ', line)
    assert 'screen=8' in line and 'action=진행' in line and 'confirmed=False' in line
    assert 'result=ok' in line and 'step=종합평가' in line and 'progress=사용자대기' in line
    assert re.search(r'elapsed_ms=\d+$', line)
    assert log_lines[-1].levelno == logging.INFO


def test_decide_needing_confirmation_is_logged_as_such(log_lines):
    orch = _FakeOrch(decide_for_project=NS(reason='미달', items={}), view_project=_run_view('산출물확인', '사용자대기'))
    OrchGateway(orch, log_state=True).decide_for_project(7, 9, '진행')

    (line,) = _cmd_lines(log_lines)
    assert 'result=confirmation_required' in line


def test_abort_logs_what_was_done(log_lines):
    orch = _FakeOrch(abort_project=NS(run_action='중단'), view_project=_run_view('결과물', '중단'))
    OrchGateway(orch, log_state=True).abort_project(7)

    (line,) = _cmd_lines(log_lines)
    assert 'command=abort_project' in line and 'result=ok' in line and 'run_action=중단' in line
    assert 'progress=중단' in line


def test_request_start_never_logs_the_account_and_marks_rejection(log_lines):
    orch = _FakeOrch(request_start=NS(ok=False, code='E-RUN-CONCURRENT'), view_project=NS(run=None))
    OrchGateway(orch, log_state=True).request_start('acct-12345', 7)

    (line,) = _cmd_lines(log_lines)
    assert 'acct-12345' not in line and 'account' not in line
    assert 'project_id=7' in line and 'result=rejected' in line and 'code=E-RUN-CONCURRENT' in line
    assert 'step=' not in line  # 실행 건이 없으면 상태는 생략
    assert log_lines[-1].levelno == logging.WARNING


def test_delete_account_logs_command_only(log_lines):
    orch = _FakeOrch()
    OrchGateway(orch, log_state=True).delete_account_data('acct-12345')

    (line,) = _cmd_lines(log_lines)
    assert 'command=delete_account_data' in line and 'result=ok' in line
    assert 'acct-12345' not in line and 'project_id' not in line
    assert [c[0] for c in orch.calls] == ['delete_account_data']  # 상태를 읽으려고 다른 함수를 부르지 않는다


def test_orchestrator_error_is_logged_with_code_and_still_raised(log_lines):
    orch = _FakeOrch(start_writing_for_project=OrchError('BUSY', 'x'))
    with pytest.raises(OrchError) as err:
        OrchGateway(orch, log_state=True).start_writing_for_project(7)

    assert err.value.code == 'BUSY'
    (line,) = _cmd_lines(log_lines)
    assert 'command=start_writing_for_project' in line and 'result=error code=BUSY' in line
    assert log_lines[-1].levelno == logging.WARNING


def test_unexpected_exception_is_logged_as_error_and_reraised(log_lines):
    orch = _FakeOrch(abort_project=RuntimeError('내부 사정 abc'))
    with pytest.raises(RuntimeError):
        OrchGateway(orch, log_state=True).abort_project(7)

    (line,) = _cmd_lines(log_lines)
    assert 'result=fail error_type=RuntimeError' in line and 'abc' not in line  # 예외 내용은 싣지 않는다
    assert log_lines[-1].levelno == logging.ERROR


def test_read_functions_are_not_logged(log_lines):
    orch = _FakeOrch(view_project=_run_view())
    gateway = OrchGateway(orch, log_state=True)
    gateway.view_project(7)

    assert _cmd_lines(log_lines) == []


def test_selected_announcement_and_rework_bundle_are_logged(log_lines):
    orch = _FakeOrch(view_project=_run_view('계획서작성', '사용자대기'))
    gateway = OrchGateway(orch, log_state=True)
    gateway.select_announcement_for_project(7, 'N-01')
    gateway.request_rework_for_project(7, '문제인식')

    first, second = _cmd_lines(log_lines)
    assert 'command=select_announcement_for_project' in first and 'announcement_id=N-01' in first
    assert 'command=request_rework_for_project' in second and 'bundle=문제인식' in second


def test_state_is_not_read_when_disabled(log_lines):
    """테스트용 가짜 오케스트레이터를 쓰는 곳은 부르는 함수 기록이 달라지지 않게 상태를 읽지 않는다."""
    orch = _FakeOrch()
    OrchGateway(orch).abort_project(7)

    (line,) = _cmd_lines(log_lines)
    assert 'step=' not in line and 'progress=' not in line
    assert [c[0] for c in orch.calls] == ['abort_project']


def test_failure_to_read_state_does_not_break_the_command(log_lines):
    orch = _FakeOrch(abort_project=NS(run_action='중단'), view_project=OrchError('RUN_NOT_FOUND', 'x'))
    result = OrchGateway(orch, log_state=True).abort_project(7)

    assert result.run_action == '중단'
    (line,) = _cmd_lines(log_lines)
    assert 'result=ok' in line and 'step=' not in line


def test_logging_failure_never_breaks_the_command(monkeypatch):
    orch = _FakeOrch(abort_project=NS(run_action='중단'))
    gateway = OrchGateway(orch, log_state=True)
    monkeypatch.setattr(gateway._command_log, '_emit', lambda *a, **k: 1 / 0)

    assert gateway.abort_project(7).run_action == '중단'
