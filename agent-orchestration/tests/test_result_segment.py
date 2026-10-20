"""결과물 구간 — 검수 구간 · R-8을 흐름에서 뺌.

- 화면 9 '진행' 뒤에는 T-C4 하나만 돈다: (결과물, 실행) → (결과물, 완료), 알림 '결과물' · 화면 11. 검수 Task(G-03 · T-P1 ·
  T-P2 · M-4) 실행 기록이 없고 결과물 묶음의 검수 기록 칸은 비어 있다.
- T-C4가 실패하면 (결과물, 실패) — 웹 실패 알림의 stage도 '결과물'(웹 테이블을 쓰는 SQLite 저장소).
- 미달 상태 진행 확인 이름은 '결과 통합 진입 확인'.
- 첨부가 있는 사전 정보로 시작해도 사전 단계는 T-C1 → T-C2이고 R-8 실행 기록이 없다.
- 흐름에서 뺀 단계의 스텁과 등록부 줄은 남는다.
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

from datetime import datetime, timezone

from conftest import executed, make_app, to_screen9
from flow_helpers import ctx_of, started, state
from sqlalchemy import text

from sbrain.agents.stubs import StubScenario, bind_stubs
from sbrain.flow.catalog import OUT_OF_FLOW_STEPS, build_registry
from sbrain.flow.sbrain_flow import RESULT
from sbrain.models import File
from sbrain.models.run import RESUME_STEP
from sbrain.orchestrator.settings import PROVISIONAL
from sbrain.store_sql.store import SqlStore

PROOFREAD_STEPS = ("G-03", "T-P1", "T-P2", "M-4")


def test_screen9_proceed_runs_only_tc4_to_result(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    before = len(executed(app, rid))
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.state.resume_step) == ("결과물", "실행", 11)
    assert (run.segment, run.segment_total, run.queue) == ("RESULT", 1, ["T-C4"])
    assert run.current_phase == "review"
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("결과물", "완료")
    assert run.segment is None and run.ended_at is not None and run.current_phase == "review"
    assert executed(app, rid)[before:] == ["T-C4"]
    assert not set(PROOFREAD_STEPS) & set(executed(app, rid))
    assert [(n.kind, n.target_step) for n in app.store.notifications(rid)] == [
        ("문서평가", 6), ("산출물확인", 8), ("결과물", 11)]
    assert ctx_of(app, rid).get("deliverable").proofread_log is None
    assert run.proofread_base_ref is None


def test_tc4_failure_is_result_failed(clock):
    app = make_app(clock, StubScenario(raise_in={"T-C4"}))
    rid = to_screen9(app)
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    assert state(app, rid) == ("결과물", "실패")
    assert [(n.kind, n.target_step) for n in app.store.notifications(rid)][-1] == ("실패", None)
    if isinstance(app.store, SqlStore):
        with app.store.engine.connect() as conn:
            stages = [r[0] for r in conn.execute(text(
                "SELECT stage FROM generation_failure_alerts WHERE project_id = :p"),
                {"p": int(app.store.load_run(rid).project_id)})]
        assert stages == ["결과물"]


def test_below_threshold_confirmation_is_result_entry(clock):
    app = make_app(clock, StubScenario(doc_scores=[50.0], art_scores=[(10.0, 7.0)]))
    rid = to_screen9(app)
    need = app.orchestrator.decide(rid, 9, "진행")
    assert need is not None and need.reason == "결과 통합 진입 확인"
    assert set(need.items) == {"현재 점수", "기준", "남는 미달 항목", "되돌릴 수 없음"}
    assert state(app, rid) == ("종합평가", "사용자대기")


def test_attachments_do_not_add_r8_to_pre_stage(clock):
    app = make_app(clock)
    files = [File(file_name="첨부.docx", format="docx", uploaded_at=datetime(2026, 9, 1, tzinfo=timezone.utc))]
    rid = started(app, attachments=files)
    assert executed(app, rid) == ["T-C1", "T-C2"]
    assert "R-8" not in executed(app, rid)


def test_out_of_flow_steps_keep_registry_rows_and_stubs():
    r = build_registry()
    bind_stubs(r, StubScenario())
    assert OUT_OF_FLOW_STEPS == frozenset({"R-8", "G-03", "T-P1", "T-P2", "M-4"})
    for tid in OUT_OF_FLOW_STEPS:
        assert r.get(tid).fn is not None, tid
    assert RESULT == ["T-C4"]
    assert not OUT_OF_FLOW_STEPS & set(RESULT)


def test_result_step_types_and_provisional():
    assert "표현검수" not in RESUME_STEP and RESUME_STEP["결과물"] == 11
    assert "tc4.runState" not in PROVISIONAL       # 결과 통합 중 '결과물 · 실행'은 기준 문서 시트 4 RunState.step
    assert not any("표현검수" in v for v in PROVISIONAL.values())
