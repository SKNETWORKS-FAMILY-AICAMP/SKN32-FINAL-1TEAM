"""가짜 오케스트레이터가 실제 sbrain과 어긋나지 않는지 확인한다. sbrain이 없으면 건너뛴다."""
import dataclasses

import orch_fakes
import pytest

from app.orch.gateway import ALLOWED

service = pytest.importorskip('sbrain.flow.service')

MIRRORED = ['RunView', 'ProjectView', 'ActiveWork', 'StartCheck', 'StartStatus', 'AbortResult', 'DeleteResult',
            'ReworkAccepted', 'ConfirmationNeeded']

# 웹이 부르면 안 되는 함수(명세 11절)
WEB_FORBIDDEN = {'advance', 'tick', 'run_start_request', 'start_run', 'start_run_for_project', 'decide', 'abort'}


@pytest.mark.parametrize('name', MIRRORED)
def test_fake_dataclass_fields_match_real(name):
    real = {f.name for f in dataclasses.fields(getattr(service, name))}
    fake = {f.name for f in dataclasses.fields(getattr(orch_fakes, name))}
    assert fake == real


def test_allowed_functions_exist_on_real_orchestrator():
    missing = [n for n in sorted(ALLOWED) if not callable(getattr(service.SBrainOrchestrator, n, None))]
    assert missing == []


def test_forbidden_functions_are_not_allowed():
    assert ALLOWED.isdisjoint(WEB_FORBIDDEN)
