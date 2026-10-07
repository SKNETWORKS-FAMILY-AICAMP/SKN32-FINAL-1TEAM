"""가짜 오케스트레이터가 실제 sbrain과 어긋나지 않는지 확인한다. sbrain이 없으면 건너뛴다."""
import dataclasses

import orch_fakes
import pytest

from app.orch.gateway import ALLOWED

service = pytest.importorskip('sbrain.flow.service')

MIRRORED = ['RunView', 'ProjectView', 'ActiveWork', 'StartCheck', 'StartStatus', 'AbortResult', 'DeleteResult',
            'ReworkAccepted', 'ConfirmationNeeded', 'AccountDeleteResult']

# 웹이 부르면 안 되는 함수(명세 11절)
WEB_FORBIDDEN = {'advance', 'tick', 'run_start_request', 'start_run', 'start_run_for_project', 'decide', 'abort'}


@pytest.mark.parametrize('name', MIRRORED)
def test_fake_dataclass_fields_match_real(name):
    real = {f.name for f in dataclasses.fields(getattr(service, name))}
    fake = {f.name for f in dataclasses.fields(getattr(orch_fakes, name))}
    assert fake == real


def test_fake_outputs_fields_match_real():
    reads = pytest.importorskip('sbrain.flow.reads')
    assert set(vars(orch_fakes.make_outputs())) == set(reads.Outputs.model_fields)


def test_fake_gate_screen_fields_match_real():
    reads = pytest.importorskip('sbrain.flow.reads')
    assert set(vars(orch_fakes.make_gate_screen())) == set(reads.GateScreen.model_fields)


def test_fake_proofread_screen_fields_match_real():
    reads = pytest.importorskip('sbrain.flow.reads')
    assert set(vars(orch_fakes.make_proofread_screen())) == set(reads.ProofreadScreen.model_fields)
    assert set(vars(orch_fakes.make_sentence_change('s1', 'x'))) == set(reads.SentenceChange.model_fields)


def test_fake_gate_and_score_view_fields_match_real():
    domain = pytest.importorskip('sbrain.models.domain')
    reads = pytest.importorskip('sbrain.flow.reads')
    assert set(vars(orch_fakes.make_gate())) == set(domain.GateResult.model_fields)
    assert set(vars(orch_fakes.make_score_view())) == set(reads.ScoreView.model_fields)
    scoring = pytest.importorskip('sbrain.models.scoring')
    assert set(vars(orch_fakes.make_feature_match())) == set(scoring.FeatureMatchResult.model_fields)
    assert set(vars(orch_fakes.make_plan_doc())) == set(domain.PlanDoc.model_fields)
    assert set(vars(orch_fakes.make_section('1-1', 't', 'x'))) == set(domain.PlanSection.model_fields)
    assert set(vars(orch_fakes.make_sentence(1, 'x'))) == set(domain.Sentence.model_fields)


def test_fake_admin_results_match_real():
    reads = pytest.importorskip('sbrain.flow.reads')
    pairs = [
        (orch_fakes.make_admin_run(), reads.AdminRun), (orch_fakes.make_admin_execution(), reads.AdminExecution),
        (orch_fakes.make_admin_agent_task(), reads.AdminAgentTask), (orch_fakes.make_score_entry(1.0), reads.ScoreEntry),
        (orch_fakes.make_admin_score_history(), reads.AdminScoreHistory), (orch_fakes.make_admin_summary(), reads.AdminSummary),
        (orch_fakes.make_tokens(), reads.TokenTotals),
    ]
    for fake, real in pairs:
        assert set(vars(fake)) == set(real.model_fields), real.__name__


def test_allowed_functions_exist_on_real_orchestrator():
    missing = [n for n in sorted(ALLOWED) if not callable(getattr(service.SBrainOrchestrator, n, None))]
    assert missing == []


def test_forbidden_functions_are_not_allowed():
    assert ALLOWED.isdisjoint(WEB_FORBIDDEN)


def test_real_artifact_check_models_have_the_fields_the_web_maps():
    """웹이 산출물 응답으로 옮기는 필드(통과 필수 조건 · 부분 인정 기능)가 실제 계약에 있는지 — 이름이 바뀌면 여기서 알아챈다."""
    scoring = pytest.importorskip('sbrain.models.scoring')
    assert {'total', 'checks', 'gate_failures'} <= set(scoring.CodeCheckResult.model_fields)
    assert {'missing_features', 'partial_features', 'withheld', 'findings'} <= set(scoring.FeatureMatchResult.model_fields)
    # 웹 가짜가 쓰는 통과 필수 조건 코드가 실제 허용값과 같은지
    from typing import get_args
    allowed = set(get_args(get_args(scoring.CodeCheckResult.model_fields['gate_failures'].annotation)[0]))
    from app.orch.mapping import GATE_NAMES
    assert set(GATE_NAMES) == allowed
