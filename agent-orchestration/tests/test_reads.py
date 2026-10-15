"""조회 — 웹이 project_id로 부르는 화면 조회 · 진행 상태, 관리자 실행 기록 조회."""
from __future__ import annotations

import pytest
from conftest import (
    executed, make_app, pre_input, project_for, project_record, start_and_select, to_screen6, to_screen8, to_screen9,
)

from sbrain.agents.stubs import StubScenario
from sbrain.flow.reads import CandidatesScreen, DocumentScreen
from sbrain.intake import MemoryProjectInputSource
from sbrain.orchestrator.errors import CommandError


def pid(app, rid: str) -> str:
    return app.store.load_run(rid).project_id


def started(app) -> tuple[str, str]:
    res = app.orchestrator.start_run("acc-1", pre_input(), project_id=project_for(app))
    assert res.ok
    return res.run_id, pid(app, res.run_id)


# ── 진행 상태 ──────────────────────────────────────────
def test_view_project_follows_request_then_run(clock):
    app = make_app(clock, project_inputs=MemoryProjectInputSource([project_record()]))
    empty = app.orchestrator.view_project(101)
    assert (empty.run, empty.start) == (None, None)
    check = app.orchestrator.request_start("7", 101)
    waiting = app.orchestrator.view_project(101)
    assert waiting.run is None and (waiting.start.status, waiting.start.request_id) == ("대기", check.request_id)
    st = app.orchestrator.run_start_request(check.request_id)
    view = app.orchestrator.view_project(101)
    assert view.start is None and view.run.run_id == st.run_id
    assert (view.run.step, view.run.screen_status) == ("공고선택", "확인 필요")


# ── 화면 ──────────────────────────────────────────────
def test_screen3_first_and_more_candidates(clock):
    app = make_app(clock)
    rid, p = started(app)
    s3 = app.orchestrator.screen(p, 3)
    assert isinstance(s3, CandidatesScreen) and (s3.screen, s3.run_id, s3.project_id) == (3, rid, p)
    assert len(s3.candidates) == 10 and s3.more_candidates == [] and s3.more_available
    assert (s3.collection_status, s3.fallback_used) == ("정상", False)
    app.orchestrator.more_candidates(rid)
    app.orchestrator.advance(rid)
    s3 = app.orchestrator.screen(p, 3)
    assert len(s3.more_candidates) == 10 and not s3.more_available            # 추가 조회는 1회
    assert s3.dump()["moreCandidates"][0]["announcementId"]                     # JSON은 기준 문서 이름


def test_screen_errors(clock):
    app = make_app(clock)
    rid = start_and_select(app)                                                  # 계획서작성 · 사용자대기
    p = pid(app, rid)
    for number, code in ((6, "SCREEN_NOT_READY"), (5, "INVALID_SCREEN")):
        with pytest.raises(CommandError) as e:
            app.orchestrator.screen(p, number)
        assert e.value.code == code
    assert isinstance(app.orchestrator.screen(p, 3), CandidatesScreen)          # 자격 통과 뒤에도 공고 후보 (3.3)
    app.orchestrator.select_announcement(rid, "A02")                             # 자격 확인 중 — 대기 지점이 아님
    with pytest.raises(CommandError) as e:
        app.orchestrator.screen(p, 3)
    assert e.value.code == "SCREEN_NOT_READY"
    with pytest.raises(CommandError) as e:
        app.orchestrator.screen(999999, 3)
    assert e.value.code == "RUN_NOT_FOUND"


def test_screen4_gate_result(clock):
    app = make_app(clock, StubScenario(gate_fail_ids={"A01"}))
    rid, p = started(app)
    with pytest.raises(CommandError, match="자격 확인 전"):
        app.orchestrator.screen(p, 4)
    app.orchestrator.select_announcement(rid, "A01")
    app.orchestrator.advance(rid)
    s4 = app.orchestrator.screen(p, 4)                                           # 불통과 → 공고선택으로 돌아옴
    assert not s4.gate_result.passed and s4.gate_result.failed_conditions and not s4.can_start_writing
    assert s4.notices[-1].code == "E-G1-REJECT"
    assert app.orchestrator.screen(p, 3).candidates                              # 다른 공고를 고를 수 있다
    app.orchestrator.select_announcement(rid, "A02")
    app.orchestrator.advance(rid)
    s4 = app.orchestrator.screen(p, 4)
    assert s4.gate_result.passed and s4.can_start_writing and s4.announcement_id == "A02"


DOC_BUNDLES = ["문제인식", "실현가능성", "성장전략", "팀 구성"]


def rework_then_wait(app, clock, rid, *bundles):
    """묶음 요청 → 모으는 시간(잠정 2초)이 지난 뒤 진행."""
    for b in bundles:
        app.orchestrator.request_rework_for_project(pid(app, rid), b)
    clock.advance(seconds=3)
    app.orchestrator.advance(rid)


def test_screen6_plan_score_and_rework_options(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 45.0]))               # 미달 → 재작성 뒤에도 미달
    rid = to_screen6(app)
    p = pid(app, rid)
    s6 = app.orchestrator.screen(p, 6)
    assert isinstance(s6, DocumentScreen)
    assert s6.plan_doc.sections and s6.score.phase == "document" and s6.score.threshold == 80
    assert s6.next_action == "재작성권유" and s6.failed_task_ids
    assert s6.rework_options and all(o.remaining == 1 and o.selectable for o in s6.rework_options)
    # 문서층 지시의 묶음은 문서층 묶음 4개 전부 (판정 지시의 대상 이름이 아니라 기회를 세는 이름)
    assert all(o.bundles == DOC_BUNDLES for o in s6.rework_options)
    assert "settingsSnapshot" not in s6.dump()["score"]                          # 내부 값은 싣지 않는다
    rework_then_wait(app, clock, rid, "문제인식", "실현가능성", "성장전략")
    usage = {u.bundle_id: u.remaining for u in app.store.load_run(rid).rework_usage}
    assert usage == {"문제인식": 0, "실현가능성": 0, "성장전략": 0}
    s6 = app.orchestrator.screen(p, 6)                                           # 4개 중 가장 많이 남은 값 (잠정)
    assert s6.rework_options and all(o.remaining == 1 and o.selectable for o in s6.rework_options)
    rework_then_wait(app, clock, rid, "팀 구성")
    s6 = app.orchestrator.screen(p, 6)
    assert s6.rework_options and all(o.remaining == 0 and not o.selectable for o in s6.rework_options)


def test_screen9_rework_options_follow_bundle_counts(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0], art_scores=[(12.0, 7.0)]))
    rid = to_screen8(app)
    p = pid(app, rid)
    s8 = app.orchestrator.screen(p, 8)
    assert [(o.order.task_id, o.bundles, o.remaining, o.selectable) for o in s8.rework_options] == [
        ("T-B1", ["실행 파일"], 1, True)]
    rework_then_wait(app, clock, rid, "실행 파일")
    assert [(o.remaining, o.selectable) for o in app.orchestrator.screen(p, 8).rework_options] == [(0, False)]
    app.orchestrator.decide(rid, 8, "진행")
    s9 = app.orchestrator.screen(p, 9)
    by_layer = {(o.order.layer, o.remaining, o.selectable) for o in s9.rework_options}
    assert by_layer == {("document", 1, True), ("artifact", 0, False)}            # 화면 8에서 쓴 묶음은 9에서 못 고름


def test_screen8_and_screen9(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    p = pid(app, rid)
    s8 = app.orchestrator.screen(p, 8)
    assert s8.prototype.kind == "html" and len(s8.code_check.checks) == 8 and s8.feature_match is not None
    assert all(o.order.layer == "artifact" for o in s8.rework_options)
    app.orchestrator.decide(rid, 8, "진행")
    s9 = app.orchestrator.screen(p, 9)
    assert s9.score.phase == "overall" and s9.score.artifact_score is not None    # 층별 내역
    assert s9.next_action in ("진행가능", "재작성권유", "상한도달") and isinstance(s9.rework_diff, list)
    assert {o.order.layer for o in s9.rework_options} <= {"document", "artifact"}


def test_screen10_and_11_after_completion(clock):
    app = make_app(clock, StubScenario(tp1_targets=4))
    rid = to_screen9(app)
    p = pid(app, rid)
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    s10 = app.orchestrator.screen(p, 10)
    assert len(s10.sentences) == 4 and s10.proofread_log.total_sentences == 4
    ctx = app.engine.open_context(app.store.load_run(rid))
    final = {s.sentence_id: s.text for sec in ctx.get("planDoc").sections for s in sec.sentences}
    for change in s10.sentences:
        assert change.before                                                    # 검수 전 문장
        if change.adopted:
            assert change.after == final[change.sentence_id] != change.before
    s11 = app.orchestrator.screen(p, 11)
    assert s11.deliverable and s11.user_message and s11.plan_doc.sections
    with pytest.raises(CommandError, match="SCREEN_NOT_READY"):
        app.orchestrator.screen(p, 6)


# ── 관리자 ─────────────────────────────────────────────
def test_admin_executions_filters_and_order(clock):
    app = make_app(clock)
    rid1 = to_screen6(app, "acc-1")
    rid2 = start_and_select(app, "acc-2")
    p1, p2 = pid(app, rid1), pid(app, rid2)
    rows = app.orchestrator.admin_executions(limit=100)
    assert [(r.project_id, r.task_id) for r in rows[:3]] == [(p2, "G-01"), (p2, "T-C2"), (p2, "T-C1")]  # 최근 순
    asc = app.orchestrator.admin_executions(project_id=p1, order="asc", limit=100)
    assert [r.task_id for r in asc] == executed(app, rid1)
    assert [r.project_id for r in app.orchestrator.admin_executions(task_id="T-C1")] == [p2, p1]
    assert [r.task_id for r in app.orchestrator.admin_executions(agent="전략", order="asc")] == ["T-S1", "T-S2"]
    assert app.orchestrator.admin_executions(status="실패") == []
    page = app.orchestrator.admin_executions(project_id=p1, order="asc", limit=3, offset=2)
    assert [r.task_id for r in page] == executed(app, rid1)[2:5]
    first2 = app.store.executions(rid2)[0].started_at
    assert {r.project_id for r in app.orchestrator.admin_executions(since=first2, limit=100)} == {p2}
    assert {r.project_id for r in app.orchestrator.admin_executions(until=first2, limit=100)} == {p1}
    tc1 = app.orchestrator.admin_executions(project_id=p1, task_id="T-C1")[0]
    assert (tc1.agent, tc1.attempt, tc1.trigger, tc1.status, tc1.model, tc1.reasoning_effort) == (
        "조율", 1, "첫실행", "성공", "gpt-6-luna", "low")
    assert tc1.duration_sec is not None and tc1.duration_sec >= 0 and tc1.tokens.input_tokens is None
    text = "".join(r.model_dump_json() for r in rows)
    assert "헬스장" not in text                                                    # 산출물 · 입력 내용은 싣지 않는다


def test_admin_calls_with_tries(clock):
    app = make_app(clock)
    app.llm.plan("T-S1", ["timeout", "ok"])
    rid = to_screen6(app)
    rec = next(r for r in app.store.executions(rid) if r.task_id == "T-S1")
    [call] = app.orchestrator.admin_calls(rec.execution_id)
    assert (call.call_type, call.final_outcome, call.model) == ("llm", "성공", "미정")
    assert [(t.no, t.outcome, t.error_kind) for t in call.tries] == [(1, "응답지연", "일시"), (2, "성공", None)]
    assert call.tokens.output_tokens is None and app.orchestrator.admin_calls("없는-실행") == []


# ── 웹 명령 (project_id) ────────────────────────────────
def test_commands_by_project_id(clock):
    """웹은 project_id만 안다 — 명령도 project_id로 부른다."""
    app = make_app(clock)
    rid, p = started(app)
    orch = app.orchestrator
    orch.more_candidates_for_project(p)
    orch.advance(rid)
    orch.select_announcement_for_project(p, "A11")                               # 추가 조회 결과에서 선택
    orch.advance(rid)
    orch.start_writing_for_project(p)
    orch.advance(rid)
    assert orch.view_project(p).run.step == "문서평가"
    orch.decide_for_project(p, 6, "진행")
    orch.advance(rid)
    assert orch.view_project(p).run.step == "산출물확인"
    with pytest.raises(CommandError) as e:
        orch.start_writing_for_project("989898")
    assert e.value.code == "RUN_NOT_FOUND"
