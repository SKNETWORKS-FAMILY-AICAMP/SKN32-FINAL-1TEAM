"""살아 있는 실행 건 보존 — 12개월 처리로 실행 기록을 옮긴(지운) 뒤에도 사용자용 결과가 같고, 다시 움직이면 이어진다.

- 카테고리는 T-C1 산출물을 저장하는 같은 저장에서 실행 건(Run.category)에 적는다. 완전 삭제 · 기록 옮기기가 지우지 않는다.
- 화면 10의 검수 전 문장은 T-P1 성공 저장 때 실행 건에 적은 계획서 참조(Run.proofread_base_ref)에서 찾는다.
- 시도 번호는 실행 기록 · Run.attempt_max · Run.attempts 중 가장 큰 값에 이어 매긴다 (실패한 시도도 셈).
"""
from __future__ import annotations

from dataclasses import asdict

from conftest import make_app, pre_input, project_for, to_screen6, to_screen9

from sbrain.agents.stubs import StubScenario
from sbrain.orchestrator.store import CommitBatch

WINDOW = 3   # 재작성 모으는 시간(잠정 2초)을 넘기는 초


def pid(app, rid: str) -> str:
    return app.store.load_run(rid).project_id


def retire(app, rid: str) -> None:
    """12개월 처리 흉내 — 점유를 잡고 여섯 기록 표의 줄을 지운다(실행 건 · 산출물은 남김)."""
    assert app.store.acquire(rid, "retire", 60)
    app.store.retire_run(rid, "retire", bump_parts=True)
    app.store.release(rid, "retire")
    assert app.store.executions(rid) == []


def rework(app, clock, rid: str, *bundles: str) -> None:
    for b in bundles:
        app.orchestrator.request_rework_for_project(pid(app, rid), b)
    clock.advance(seconds=WINDOW)
    app.orchestrator.advance(rid)


def finish(app, rid: str) -> None:
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "완료"


# ── 카테고리 ───────────────────────────────────────────
def test_category_written_with_tc1_output_and_kept_after_delete(clock):
    for category in ("웹개발", "원페이지"):
        app = make_app(clock, StubScenario(category=category))
        res = app.orchestrator.start_run("acc-1", pre_input(), project_id=project_for(app))
        assert res.ok
        run = app.store.load_run(res.run_id)
        ctx = app.engine.open_context(run)
        assert run.category == ctx.get("category") == category          # 실행 건 생성 저장에 함께
        assert run.dump()["category"] == category
        retire(app, res.run_id)
        assert app.store.load_run(res.run_id).category == category       # 기록 옮기기가 지우지 않는다
        app.orchestrator.delete_project_data(run.project_id)
        after = app.store.load_run(res.run_id)
        assert after.category == category                               # 완전 삭제도 지우지 않는다
        assert not app.store.get_pointers(res.run_id)                     # (산출물은 지워졌다)


# ── 화면 10 · 지금까지 결과 ───────────────────────────────
def test_screen10_and_outputs_same_after_records_retired(clock):
    app = make_app(clock, StubScenario(tp1_targets=4))
    rid = to_screen9(app)
    finish(app, rid)
    p = pid(app, rid)
    run = app.store.load_run(rid)
    tp1 = [r for r in app.store.executions(rid) if r.task_id == "T-P1" and r.status == "성공"][-1]
    base = next(i for i in tp1.inputs if i.startswith("planDoc@"))
    assert run.proofread_base_ref == base                                # T-P1 성공 저장에서 적음
    ctx = app.engine.open_context(run)
    assert ctx.ref("planDoc") != base                                    # M-4가 새 버전을 만들었다
    s10, s11 = app.orchestrator.screen(p, 10).dump(), app.orchestrator.screen(p, 11).dump()
    out, view = app.orchestrator.outputs(p).dump(), asdict(app.orchestrator.view(rid))
    assert any(s["adopted"] for s in s10["sentences"])
    retire(app, rid)
    assert app.orchestrator.screen(p, 10).dump() == s10                  # 검수 전 문장이 그대로
    assert app.orchestrator.screen(p, 11).dump() == s11
    assert app.orchestrator.outputs(p).dump() == out
    assert asdict(app.orchestrator.view(rid)) == view


def test_screen10_falls_back_to_execution_record_for_old_runs(clock):
    """확장 필드가 없던 실행 건(기록은 있음)은 지금처럼 T-P1 실행 기록의 입력 참조에서 찾는다."""
    app = make_app(clock, StubScenario(tp1_targets=4))
    rid = to_screen9(app)
    finish(app, rid)
    p = pid(app, rid)
    expected = app.orchestrator.screen(p, 10).dump()
    assert app.store.acquire(rid, "old", 60)
    run = app.store.load_run(rid)
    run.proofread_base_ref = None
    app.store.commit(rid, "old", CommitBatch(run=run))
    app.store.release(rid, "old")
    assert app.store.load_run(rid).proofread_base_ref is None
    assert app.orchestrator.screen(p, 10).dump() == expected


# ── 재작성 결과 · 화면 6 · 9 ─────────────────────────────
def test_rework_results_and_screens_same_after_records_retired(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen9(app)
    rework(app, clock, rid, "문제인식")
    p = pid(app, rid)
    assert app.store.load_run(rid).last_rework.status == "완료"
    before = (app.orchestrator.rework_result(p).dump(), app.orchestrator.outputs(p).dump(),
              app.orchestrator.screen(p, 9).dump(), asdict(app.orchestrator.view(rid)))
    retire(app, rid)
    after = (app.orchestrator.rework_result(p).dump(), app.orchestrator.outputs(p).dump(),
             app.orchestrator.screen(p, 9).dump(), asdict(app.orchestrator.view(rid)))
    assert after == before


# ── 시도 번호 이어 가기 ─────────────────────────────────
def test_attempt_numbers_continue_after_failed_rework_and_retire(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0]))
    rid = to_screen6(app)
    app.llm.plan("T-W1", ["auth"] * 6)                                   # 영구 오류 → 재작성 실패 · 되돌림
    rework(app, clock, rid, "문제인식")
    run = app.store.load_run(rid)
    assert run.last_rework.status == "실패"
    tw1 = [r for r in app.store.executions(rid) if r.task_id == "T-W1"]
    failed = max(r.attempt for r in tw1 if r.status == "실패")
    assert failed > max(a.attempt for a in run.attempts if a.task_id == "T-W1")   # 실패 시도는 Run.attempts에 없다
    # 실행 기록을 남긴 같은 저장에서 Task별 마지막 시도 번호를 갱신한다
    assert run.attempt_max == {t: max(r.attempt for r in app.store.executions(rid) if r.task_id == t)
                               for t in {r.task_id for r in app.store.executions(rid)}}
    retire(app, rid)
    app.llm.plan("T-W1", [])
    rework(app, clock, rid, "문제인식")                                   # 다시 움직인다 (돌려받은 기회)
    run = app.store.load_run(rid)
    assert run.last_rework.status == "완료"
    again = [r for r in app.store.executions(rid) if r.task_id == "T-W1"]
    assert [r.attempt for r in again] == [failed + 1]                    # 이전 번호를 다시 쓰지 않는다
    assert run.attempt_max["T-W1"] == failed + 1
    assert any(a.task_id == "T-W1" and a.attempt == failed + 1 for a in run.attempts)


def test_attempt_start_is_max_of_records_field_and_attempts(clock):
    """시도 번호 시작값 = 실행 기록 · attempt_max · Run.attempts 중 가장 큰 값 (엔진 장치, 범용)."""
    app = make_app(clock)
    rid = to_screen6(app)
    run = app.store.load_run(rid)
    from_attempts = max(a.attempt for a in run.attempts if a.task_id == "T-W1")
    retire(app, rid)
    # 확장 필드가 없던 옛 실행 건 — Run.attempts만 남았다
    old = app.store.load_run(rid)
    old.attempt_max = {}
    assert app.engine.open_context(old).next_attempt("T-W1") == from_attempts + 1
    # 확장 필드가 더 크면 그 값에 잇는다
    bigger = app.store.load_run(rid)
    bigger.attempt_max = {"T-W1": from_attempts + 5}
    assert app.engine.open_context(bigger).next_attempt("T-W1") == from_attempts + 6
    # 처음 도는 Task는 1부터
    assert app.engine.open_context(app.store.load_run(rid)).next_attempt("T-NEW") == 1
