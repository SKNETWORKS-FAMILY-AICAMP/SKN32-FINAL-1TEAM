"""T-P2 — 실패 비율을 넘었을 때 운영 오류가 섞였으면 재개하지 않고 실행 실패 (호출 실패 처리 spec 5절).

가짜 결과 대기열은 문장(항목 키)마다 넣는다(남은 대기열은 그 문장 키에만 쓰이고 뒤 단계는 T-P2 키를 부르지 않는다).
일시 오류는 처음 포함 6번 보내므로 6개, 입력 · 운영 오류(4xx)는 한 번만 보내므로 — 재개 뒤 다시 돌 문장이면 — 1개만 넣는다.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import make_app, to_screen9
from flow_helpers import run_review

from sbrain.agents.stubs import StubScenario
from sbrain.orchestrator.settings import Settings

S1, S2, S3 = "s-3.1.1-1", "s-3.1.1-2", "s-3.1.2-1"   # 검수 대상 4문장 중 앞의 셋 (기준 30% — 2/4부터 넘음)


def app_with(clock, plan: dict[str, list[str]], *, settings: Settings | None = None):
    kw = {"settings": settings} if settings is not None else {}
    app = make_app(clock, StubScenario(tp1_targets=4), **kw)
    for sid, outcomes in plan.items():
        app.llm.plan("T-P2", outcomes, item_key=sid)
    return app


def tp2_records(app, rid):
    return [r for r in app.store.executions(rid) if r.task_id == "T-P2"]


def sentence_results(app, rid):
    ctx = app.engine.open_context(app.store.load_run(rid))
    return {r.sentence_id: r for r in ctx.get("sentenceResults")}


def no_resume_settings() -> Settings:
    """재개 상한이 0 — 첫 재개부터 상한을 넘는다."""
    s = Settings()
    s.resume.max_count = 0
    return s


def assert_failed_by_operation_error(app, rid) -> None:
    run = app.store.load_run(rid)
    assert (run.state.progress, run.state.step) == ("실패", "표현검수")
    assert run.last_error_kind == "운영" and run.admin_alert is True
    assert run.next_resume_at is None and run.redo_state is None
    assert run.failure_reason == "T-P2: 영구오류 — 호출실패"
    recs = tp2_records(app, rid)
    assert len(recs) == 1
    rec = recs[0]
    assert (rec.status, rec.error, rec.error_kind) == ("실패", "호출실패", "운영") and rec.ended_at is not None
    kinds = [e.kind for e in app.store.events(rid)]
    assert "실행실패" in kinds and "검수재개상한" not in kinds


@pytest.mark.parametrize("plan", [
    {S1: ["auth"] * 6, S2: ["timeout"] * 6},          # 운영 + 일시
    {S1: ["auth"] * 6, S2: ["auth"] * 6},             # 모두 운영 (API 키 오류)
    {S1: ["auth"] * 6, S2: ["bad_request"] * 6},      # 운영 + 입력
], ids=["auth+timeout", "auth+auth", "auth+bad_request"])
def test_ratio_exceeded_with_operation_error_fails_run(clock, plan):
    app = app_with(clock, plan)
    rid = to_screen9(app)
    run_review(app, rid)
    assert_failed_by_operation_error(app, rid)
    run = app.store.load_run(rid)
    assert run.resume_count == 0 and "재개예약" not in [e.kind for e in app.store.events(rid)]


def test_ratio_exceeded_without_operation_error_resumes(clock):
    """한도 · 일시 · 입력만이면 지금처럼 '일시'로 재개를 예약한다."""
    app = app_with(clock, {S1: ["timeout"] * 6, S2: ["rate_limit"] * 6, S3: ["bad_request"]})   # 400은 한 번만 보낸다
    rid = to_screen9(app)
    run_review(app, rid)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.state.step) == ("재개대기", "표현검수") and run.resume_count == 1
    rec = tp2_records(app, rid)[0]
    assert rec.status == "재개대기"
    res = sentence_results(app, rid)
    assert {sid for sid, r in res.items() if r.kept_reason == "호출실패"} == {S1, S2, S3}
    # 재개하면 '호출실패' 문장만 다시 돌고 끝난다
    clock.t = run.next_resume_at + timedelta(seconds=1)
    app.engine.resume(rid)
    assert app.store.load_run(rid).state.progress == "완료"
    assert all(r.adopted for r in sentence_results(app, rid).values())


def test_operation_error_fails_even_when_resume_cap_is_exceeded(clock):
    """운영 확인은 재개 상한 확인보다 먼저 — 상한을 넘었어도 '원문 유지한 채 완료'가 아니라 실패."""
    app = app_with(clock, {S1: ["auth"] * 6, S2: ["timeout"] * 6}, settings=no_resume_settings())
    rid = to_screen9(app)
    run_review(app, rid)
    assert_failed_by_operation_error(app, rid)


def test_resume_cap_exceeded_without_operation_error_completes_keeping_originals(clock):
    """운영 오류가 없고 재개 상한을 넘었으면 지금처럼 '검수재개상한' 사건과 함께 원문 유지한 채 완료."""
    app = app_with(clock, {S1: ["timeout"] * 6, S2: ["bad_request"] * 6}, settings=no_resume_settings())
    rid = to_screen9(app)
    run_review(app, rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "완료"
    assert "검수재개상한" in [e.kind for e in app.store.events(rid)]
    res = sentence_results(app, rid)
    assert (res[S1].kept_reason, res[S2].kept_reason) == ("호출실패", "호출실패")
    assert tp2_records(app, rid)[0].status == "성공"


def test_ratio_not_exceeded_with_operation_error_completes(clock):
    """실패 비율을 넘지 않으면 운영 오류가 섞여 있어도 지금처럼 원문 유지한 채 완료 (1/4 = 25% ≤ 30%)."""
    app = app_with(clock, {S1: ["auth"] * 6})
    rid = to_screen9(app)
    run_review(app, rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "완료" and run.last_error_kind != "운영"
    res = sentence_results(app, rid)
    assert res[S1].kept_reason == "호출실패" and not res[S1].adopted
    rec = tp2_records(app, rid)[0]
    assert (rec.status, rec.error_kind) == ("성공", None)


def test_operation_error_on_resumed_tp2_fails_run(clock):
    """재개한 T-P2에서 다시 도는 '호출실패' 문장이 운영 오류로 끝나면 그 실행에서 실패한다 (같은 실행 기록)."""
    app = app_with(clock, {S1: ["timeout"] * 6 + ["auth"] * 6, S2: ["timeout"] * 6 + ["auth"] * 6})
    rid = to_screen9(app)
    run_review(app, rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기"
    clock.t = run.next_resume_at + timedelta(seconds=1)
    app.engine.resume(rid)
    assert_failed_by_operation_error(app, rid)
