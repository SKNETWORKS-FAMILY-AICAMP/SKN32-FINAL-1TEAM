"""화면 조회 — 웹이 project_id로 부르는 화면 3 · 4 · 6 · 8 · 9 · 10 · 11과 화면 오류.

진행 상태(view_project) · project_id 명령은 test_web_functions.py, 관리자 조회는 test_admin_reads.py가 본다.
"""
from __future__ import annotations

import pytest
from conftest import make_app, start_and_select, to_screen6, to_screen8, to_screen9
from flow_helpers import pid, rework, started_with_pid

from sbrain.agents.stubs import StubScenario
from sbrain.flow.reads import CandidatesScreen, DocumentScreen
from sbrain.orchestrator.errors import CommandError


# ── 화면 ──────────────────────────────────────────────
def test_screen3_first_and_more_candidates(clock):
    app = make_app(clock)
    rid, p = started_with_pid(app)
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
    rid, p = started_with_pid(app)
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
    rework(app, clock, rid, "문제인식", "실현가능성", "성장전략")
    usage = {u.bundle_id: u.remaining for u in app.store.load_run(rid).rework_usage}
    assert usage == {"문제인식": 0, "실현가능성": 0, "성장전략": 0}
    s6 = app.orchestrator.screen(p, 6)                                           # 4개 중 가장 많이 남은 값 (잠정)
    assert s6.rework_options and all(o.remaining == 1 and o.selectable for o in s6.rework_options)
    rework(app, clock, rid, "팀 구성")
    s6 = app.orchestrator.screen(p, 6)
    assert s6.rework_options and all(o.remaining == 0 and not o.selectable for o in s6.rework_options)


def test_screen9_rework_options_follow_bundle_counts(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0], art_scores=[(12.0, 7.0)]))
    rid = to_screen8(app)
    p = pid(app, rid)
    s8 = app.orchestrator.screen(p, 8)
    assert [(o.order.task_id, o.bundles, o.remaining, o.selectable) for o in s8.rework_options] == [
        ("T-B1", ["실행 파일"], 1, True)]
    rework(app, clock, rid, "실행 파일")
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
