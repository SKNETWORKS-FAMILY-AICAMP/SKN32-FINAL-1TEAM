"""웹이 쓰는 함수 (spec 4) — 진행 상태(view_project) · 여러 프로젝트 보기 · 실행 건이 없는 프로젝트(missing_projects) · 기다리기 · 지금까지 결과 · 재작성 결과,
project_id로 부르는 명령, 자격 통과 뒤 공고 다시 고르기 (3.3), 화면 10 시도별 기록, 화면 8 · 9 '진행'."""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta

import pytest
from conftest import (
    executed, make_app, project_record, start_and_select, to_screen6, to_screen8, to_screen9,
)
from flow_helpers import WINDOW, code_of, pid, rework, run_review, started_with_pid
from webdb import new_project

from sbrain.agents.stubs import StubScenario
from sbrain.bootstrap import build_web
from sbrain.flow import ConfirmationNeeded
from sbrain.flow.reads import CandidatesScreen, Outputs, ReworkResult
from sbrain.flow.rework_map import ARTIFACT_BUNDLES, DOCUMENT_BUNDLES
from sbrain.intake import MemoryProjectInputSource
from sbrain.orchestrator.errors import COMMAND_ERROR_CODES, CommandError
from sbrain.orchestrator.store import StartRequest

BUNDLES = list(DOCUMENT_BUNDLES) + list(ARTIFACT_BUNDLES)


def test_new_command_error_codes_are_listed():
    assert {"WEB_NOT_ALLOWED", "RUN_NOT_VIEWABLE", "RUN_NOT_FOUND", "INVALID_STATE"} <= set(COMMAND_ERROR_CODES)


# ── view_project · project_views ──────────────────────────
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


def test_view_project_reports_retry_resume_and_announcement(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    p = pid(app, rid)
    app.llm.plan("T-S1", ["timeout"] * 6)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    v = app.orchestrator.view_project(p).run
    assert (v.progress, v.retry_count, v.resume_count, v.last_error_kind) == ("재개대기", 5, 1, "일시")
    assert v.next_resume_at == app.store.load_run(rid).next_resume_at is not None
    assert (v.announcement_id, v.rework_screen, v.collecting) == ("A01", None, False)
    assert app.orchestrator.outputs(p).selected_announcement.announcement_id == "A01"   # 재개대기도 결과를 본다


def test_view_project_shows_rework_collecting(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    p = pid(app, rid)
    app.orchestrator.request_rework_for_project(p, "문제인식")
    v = app.orchestrator.view_project(p).run
    assert (v.progress, v.collecting, v.rework_screen, v.resume_step) == ("실행", True, 6, 6)
    clock.advance(seconds=WINDOW)
    assert app.orchestrator.view_project(p).run.collecting is False             # 모으는 시간이 끝남


def test_user_results_have_no_failure_reason(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    p = pid(app, rid)
    app.llm.plan("T-S1", ["auth"] * 50)                                          # 영구 오류 → 실패
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    reason = app.store.load_run(rid).failure_reason
    assert reason
    view = app.orchestrator.view_project(p)
    data = asdict(view)
    assert "failure_reason" not in data["run"] and reason not in repr(data)
    assert (view.run.progress, view.run.screen_status, view.run.notices[-1].code) == ("실패", "문제 발생", "E-RUN-FAIL")
    assert app.orchestrator.project_views([p]) == [view]
    assert code_of(lambda: app.orchestrator.outputs(p)) == "RUN_NOT_VIEWABLE"
    assert code_of(lambda: app.orchestrator.rework_result(p)) == "RUN_NOT_VIEWABLE"


def test_project_views_several_projects_at_once(clock):
    source = MemoryProjectInputSource([project_record(project={"project_id": 101}, company={"user_id": 7}),
                                       project_record(project={"project_id": 102}, company={"user_id": 8})])
    app = make_app(clock, project_inputs=source)
    st = app.orchestrator.run_start_request(app.orchestrator.request_start("7", 101).request_id)
    waiting = app.orchestrator.request_start("8", 102)
    views = app.orchestrator.project_views([101, "102", 103])
    assert [v.project_id for v in views] == ["101", "102", "103"]
    assert views[0].run.run_id == st.run_id and views[0].start is None
    assert views[1].run is None and (views[1].start.status, views[1].start.request_id) == ("대기", waiting.request_id)
    assert (views[2].run, views[2].start) == (None, None)
    assert views == [app.orchestrator.view_project(p) for p in (101, 102, 103)]   # view_project와 같은 내용
    assert app.orchestrator.project_views([]) == []


# ── missing_projects ───────────────────────────────────
def two_projects_app(clock):
    source = MemoryProjectInputSource([project_record(project={"project_id": 101}, company={"user_id": 7}),
                                       project_record(project={"project_id": 102}, company={"user_id": 8})])
    return make_app(clock, project_inputs=source)


def test_missing_projects_mixed_returns_values_as_given(clock):
    app = two_projects_app(clock)
    app.orchestrator.run_start_request(app.orchestrator.request_start("7", 101).request_id)   # 실행 건
    app.orchestrator.request_start("8", 102)                                     # 대기 요청만 — 있음
    assert app.orchestrator.missing_projects([101, "102", 103, "104"]) == [103, "104"]
    assert app.orchestrator.missing_projects(["104", 101, 103]) == ["104", 103]   # 넘긴 순서 · 받은 타입 그대로
    assert app.orchestrator.missing_projects([101, "102"]) == []
    assert app.orchestrator.missing_projects([]) == []
    assert app.orchestrator.missing_projects(iter([103])) == [103]


def test_missing_projects_dedupes_by_number_keeping_first_value(clock):
    app = two_projects_app(clock)
    app.orchestrator.request_start("7", 101)
    assert app.orchestrator.missing_projects(["07", 7, "7", 103, "0103", " 7"]) == ["07", 103]
    assert app.orchestrator.missing_projects(["0101", 101, "101"]) == []        # 같은 프로젝트 — 있음


def test_missing_projects_unfinished_request_exists_finished_is_missing(clock):
    app = two_projects_app(clock)
    check = app.orchestrator.request_start("7", 101)
    assert app.orchestrator.missing_projects([101]) == []                       # 대기
    assert app.store.acquire_start_request(check.request_id, "worker-1", 60)
    assert app.orchestrator.missing_projects([101]) == []                       # 처리중
    app.orchestrator.abort_project(101)                                          # 취소 요청 → 워커가 '취소'로 끝냄
    assert app.orchestrator.run_start_request(check.request_id, owner="worker-1").status == "취소"
    assert app.orchestrator.missing_projects([101]) == [101]                    # 끝난 요청만 — 없음
    again = app.orchestrator.request_start("8", 102)
    app.orchestrator.abort_project(102)
    assert app.orchestrator.start_status(102).status == "취소" == app.store.get_start_request(again.request_id).status
    assert app.orchestrator.missing_projects(["102", 101]) == ["102", 101]


def test_missing_projects_rejects_non_numeric_before_reading(clock):
    app = two_projects_app(clock)
    calls: list = []
    original = app.store.existing_projects
    app.store.existing_projects = lambda ids: calls.append(ids) or original(ids)
    for bad in (["abc"], [101, "x-SECRET"], [None], ["1.5"], [""]):
        with pytest.raises(ValueError) as e:
            app.orchestrator.missing_projects(bad)
        assert "SECRET" not in str(e.value) and "abc" not in str(e.value)        # 값은 메시지에 싣지 않는다
    assert calls == []                                                           # 저장소를 읽기 전에 막는다
    assert app.orchestrator.missing_projects(["101"]) == ["101"] and calls == [[101]]   # 저장소에는 정수로


def test_missing_projects_through_web_assembly(tmp_path, db):
    """웹 조립(build_web)에서 부른다 — 실행 건도 요청도 없는 웹 프로젝트는 없음, 대기 요청이 있으면 있음."""
    web = build_web(f"sqlite:///{(tmp_path / 'worker.db').as_posix()}", profile_count=lambda a: 1)
    p, q = new_project(db), new_project(db)
    now = web.orchestrator.now()
    req = StartRequest(request_id="req-MISSING", project_id=str(q), account_id="acct-1", status="대기",
                       form={}, created_at=now, updated_at=now)
    assert web.store.add_start_request(req) is None
    assert web.orchestrator.missing_projects([str(p), q, p]) == [str(p)]
    assert web.store.cancel_start_request(req.request_id) == "취소"
    assert web.orchestrator.missing_projects([q]) == [q]


# ── wait_project ───────────────────────────────────────
def test_wait_project_timeout_returns_state_then(clock):
    app = make_app(clock)
    rid, p = started_with_pid(app)
    app.orchestrator.select_announcement(rid, "A01")                             # '실행' — 워커가 아직 안 가져감
    naps: list[float] = []

    def nap(sec: float) -> None:
        naps.append(sec)
        clock.advance(seconds=sec)
    app.orchestrator.sleep = nap
    t0 = clock.t
    view = app.orchestrator.wait_project(p, timeout_sec=3)
    assert (view.run.step, view.run.progress) == ("자격확인", "실행")             # 제한 시간 — 오류가 아니다
    assert sum(naps) >= 3 and clock.t - t0 < timedelta(seconds=4)


def test_wait_project_returns_at_wait_point(clock):
    app = make_app(clock)
    rid, p = started_with_pid(app)
    app.orchestrator.select_announcement(rid, "A01")
    app.orchestrator.sleep = lambda sec: app.orchestrator.advance(rid)          # 기다리는 동안 워커가 진행
    view = app.orchestrator.wait_project(p)
    assert (view.run.step, view.run.progress) == ("계획서작성", "사용자대기")


def test_wait_project_follows_start_request_and_skips_resume_wait(clock):
    app = make_app(clock, project_inputs=MemoryProjectInputSource([project_record()]))
    check = app.orchestrator.request_start("7", 101)
    app.orchestrator.sleep = lambda sec: app.orchestrator.run_start_request(check.request_id)
    view = app.orchestrator.wait_project(101)                                    # 시작 요청 대기 → 실행 건
    assert view.start is None and (view.run.step, view.run.progress) == ("공고선택", "사용자대기")
    rid = view.run.run_id
    app.orchestrator.select_announcement(rid, "A01")
    app.orchestrator.advance(rid)
    app.llm.plan("T-S1", ["timeout"] * 6)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    naps: list[float] = []
    app.orchestrator.sleep = naps.append
    assert app.orchestrator.wait_project(101).run.progress == "재개대기" and naps == []   # 기다리지 않는다


def test_wait_project_waits_while_rework_collecting(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    p = pid(app, rid)
    app.orchestrator.request_rework_for_project(p, "문제인식")

    def nap(sec: float) -> None:
        clock.advance(seconds=sec)
        app.orchestrator.advance(rid)                                            # 모으는 시간이 지나야 진행된다
    app.orchestrator.sleep = nap
    t0 = clock.t
    view = app.orchestrator.wait_project(p, timeout_sec=10)
    assert (view.run.step, view.run.progress) == ("문서평가", "사용자대기")
    assert clock.t - t0 >= timedelta(seconds=2)


# ── outputs ────────────────────────────────────────────
def test_outputs_accumulate_current_results(clock):
    app = make_app(clock, StubScenario(tp1_targets=4, tp2_behavior={"s-3.1.1-2": ["violate", "ok"]}))
    assert code_of(lambda: app.orchestrator.outputs(424242)) == "RUN_NOT_FOUND"
    rid, p = started_with_pid(app)
    out = app.orchestrator.outputs(p)
    assert isinstance(out, Outputs) and (out.run_id, out.step, out.progress) == (rid, "공고선택", "사용자대기")
    assert len(out.candidates) == 10 and out.more_candidates == [] and out.category == "웹개발"
    assert (out.selected_announcement, out.gate_result, out.plan_doc, out.doc_score, out.prototype,
            out.document_score_report, out.overall_score_report, out.proofread_log, out.deliverable) == (None,) * 9
    assert (out.format_findings, out.sentence_results) == ([], [])
    assert [(u.bundle_id, u.layer, u.used_count, u.remaining) for u in out.rework_usage] == [
        (b, "document", 0, 1) for b in DOCUMENT_BUNDLES] + [(b, "artifact", 0, 1) for b in ARTIFACT_BUNDLES]
    assert out.rework_limit == 1
    app.orchestrator.more_candidates(rid)
    app.orchestrator.advance(rid)
    app.orchestrator.select_announcement(rid, "A01")
    out = app.orchestrator.outputs(p)                                            # 진행 중에도 본다
    assert out.progress == "실행" and len(out.more_candidates) == 10
    assert out.selected_announcement is None and out.gate_result is None         # 선택 공고는 G-01이 받아 온다
    app.orchestrator.advance(rid)
    assert app.orchestrator.outputs(p).selected_announcement.announcement_id == "A01"
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    out = app.orchestrator.outputs(p)
    assert out.gate_result.passed and out.plan_doc.sections and out.doc_score.total == 60.0
    assert out.document_score_report.phase == "document" and out.overall_score_report is None
    assert "settingsSnapshot" not in out.dump()["documentScoreReport"]         # 내부 값은 싣지 않는다
    rework(app, clock, rid, "문제인식")
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    out = app.orchestrator.outputs(p)
    assert out.prototype.kind == "html" and out.infographic and out.code_check and out.feature_match
    assert out.overall_score_report.phase == "overall"
    usage = {u.bundle_id: (u.used_count, u.remaining) for u in out.rework_usage}
    assert usage["문제인식"] == (1, 0) and usage["실현가능성"] == (0, 1) and len(usage) == 6
    app.orchestrator.decide(rid, 8, "진행")
    run_review(app, rid)
    out = app.orchestrator.outputs(p)
    assert out.progress == "완료" and out.deliverable and out.user_message and out.proofread_log
    assert len(out.format_findings) == 4 and len(out.sentence_results) == 4
    tried = {r.sentence_id: [(a.attempt_no, a.adopted) for a in r.attempts] for r in out.sentence_results}
    assert tried["s-3.1.1-2"] == [(1, False), (2, True)]                           # 시도별 기록
    assert "failureReason" not in out.model_dump_json(by_alias=True)


def test_outputs_onepage_has_no_executable_bundle(clock):
    app = make_app(clock, StubScenario(category="원페이지"))
    _, p = started_with_pid(app)
    out = app.orchestrator.outputs(p)
    assert [u.bundle_id for u in out.rework_usage] == list(DOCUMENT_BUNDLES) + ["인포그래픽"]


def test_outputs_and_rework_result_not_viewable_after_abort(clock):
    app = make_app(clock)
    rid, p = started_with_pid(app)
    app.orchestrator.abort(rid, confirmed=True)
    assert code_of(lambda: app.orchestrator.outputs(p)) == "RUN_NOT_VIEWABLE"
    assert code_of(lambda: app.orchestrator.rework_result(p)) == "RUN_NOT_VIEWABLE"
    assert code_of(lambda: app.orchestrator.rework_result(989898)) == "RUN_NOT_FOUND"


# ── rework_result ──────────────────────────────────────
def test_rework_result_collecting_then_done_with_plan_sections(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    p = pid(app, rid)
    assert app.orchestrator.rework_result(p) is None                             # 재작성한 적 없음
    before = app.store.get_pointers(rid)
    acc = app.orchestrator.request_rework_for_project(p, "문제인식")
    r = app.orchestrator.rework_result(p)
    assert isinstance(r, ReworkResult)
    assert (r.status, r.screen, r.bundles, r.cycle_id) == ("진행중", 6, ["문제인식"], acc.cycle_id)
    assert (r.kept, r.before_score, r.before_refs, r.plan_before, r.files, r.rolled_back) == (
        None, None, [], None, [], False)
    clock.advance(seconds=WINDOW)
    app.orchestrator.advance(rid)
    r = app.orchestrator.rework_result(p)
    assert (r.status, r.kept, r.basis, r.before_score, r.after_score) == ("완료", "후", "document", 52.0, 60.0)
    assert f"planDoc@{before['planDoc']}" in r.before_refs and r.ended_at is not None
    after_ref = next(ref for ref in r.after_refs if ref.startswith("planDoc@"))
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert r.plan_before == ctx.get("planDoc", before["planDoc"]).sections
    assert r.plan_after == ctx.get_ref(after_ref).sections
    assert r.files == [] and (r.rolled_back, r.refunded_bundles, r.notice_code) == (False, [], None)


def test_rework_result_artifact_paths_then_failure(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0], art_scores=[(12.0, 7.0), (15.0, 11.0)]))
    rid = to_screen8(app)
    p = pid(app, rid)
    ok = rework(app, clock, rid, "실행 파일")[0]
    r = app.orchestrator.rework_result(p)
    assert (r.status, r.kept, r.screen, r.cycle_id) == ("완료", "후", 8, ok.cycle_id)
    [f] = r.files                                                               # 진입 파일 참조의 전후 (결정 0023)
    assert f.artifact == "prototype"
    assert (f.before_file.name, f.after_file.name) == ("index.html", "index.html")   # 진입 파일명 (2026-09-30 결정 9)
    assert f.before_file.key != f.after_file.key                                 # 넣을 때마다 새 키
    ctx = app.engine.open_context(app.store.load_run(rid))
    assert f.after_file == ctx.get("prototype").entry_file
    assert set(f.dump()) == {"artifact", "beforeFile", "afterFile"}               # 내용 없이 참조만
    assert r.plan_before is None and r.plan_after is None
    app.orchestrator.decide(rid, 8, "진행")
    app.llm.plan("T-B2", ["auth"] * 50)                                          # 영구 오류 → 재작성 실패
    failed = rework(app, clock, rid, "인포그래픽")[0]
    r = app.orchestrator.rework_result(p)
    assert r.cycle_id == failed.cycle_id != ok.cycle_id                          # 이전 성공을 마지막처럼 주지 않는다
    assert (r.status, r.screen, r.rolled_back, r.refunded_bundles, r.notice_code) == (
        "실패", 9, True, ["인포그래픽"], "E-RUN-ROLLBACK")
    assert (r.kept, r.before_score, r.after_score, r.before_refs, r.after_refs, r.plan_before, r.files) == (
        None, None, None, [], [], None, [])
    assert "failureReason" not in r.dump()


# ── 웹 명령 (project_id) ────────────────────────────────
def test_commands_by_project_id(clock):
    """웹은 project_id만 안다 — 명령도 project_id로 부른다."""
    app = make_app(clock)
    rid, p = started_with_pid(app)
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


# ── 자격 통과 뒤 공고 다시 고르기 (3.3) ────────────────────
def test_reselect_announcement_after_gate_pass(clock):
    app = make_app(clock, StubScenario(gate_fail_ids={"A03"}))
    rid = start_and_select(app)                                                  # A01 통과 → 계획서작성 · 사용자대기
    p = pid(app, rid)
    s3 = app.orchestrator.screen(p, 3)
    assert isinstance(s3, CandidatesScreen) and (s3.step, s3.progress) == ("계획서작성", "사용자대기")
    assert len(s3.candidates) == 10 and s3.more_available
    assert code_of(lambda: app.orchestrator.select_announcement_for_project(p, "없는-공고")) == "INVALID_ANNOUNCEMENT"
    app.orchestrator.select_announcement_for_project(p, "A02")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.announcement_id) == ("자격확인", "실행", "A01")  # G-01 전
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.announcement_id) == ("계획서작성", "사용자대기", "A02")
    assert executed(app, rid).count("G-01") == 2                                 # G-01을 다시 돌았다
    ctx = app.engine.open_context(run)
    assert ctx.get("selectedAnnouncement").announcement_id == "A02" and ctx.version("selectedAnnouncement") == 2
    assert app.orchestrator.screen(p, 4).announcement_id == "A02"
    app.orchestrator.select_announcement_for_project(p, "A03")                   # 불통과 공고
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.notices[-1].code) == ("공고선택", "사용자대기", "E-G1-REJECT")


def test_more_candidates_after_gate_pass(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    p = pid(app, rid)
    app.orchestrator.more_candidates_for_project(p)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("공고선택", "사용자대기")       # 추가 조회 뒤 공고선택 대기
    s3 = app.orchestrator.screen(p, 3)
    assert len(s3.more_candidates) == 10 and not s3.more_available
    assert code_of(lambda: app.orchestrator.more_candidates_for_project(p)) == "MORE_LIMIT"


def test_reselection_rejected_after_writing_started(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    p = pid(app, rid)
    app.orchestrator.start_writing(rid)                                          # 계획서작성 · 실행
    for _ in range(2):
        for fn in (lambda: app.orchestrator.select_announcement_for_project(p, "A02"),
                   lambda: app.orchestrator.more_candidates_for_project(p),
                   lambda: app.orchestrator.screen(p, 3)):
            assert code_of(fn) == "INVALID_STATE"
        app.orchestrator.advance(rid)                                            # 문서평가 · 사용자대기에서도
    assert app.store.load_run(rid).state.step == "문서평가"


def test_reselection_rejected_while_worker_holds_lease(clock):
    """작성 시작 뒤 워커가 점유 중이어도 BUSY가 아니라 바로 INVALID_STATE (3.3). BUSY는 받을 수 있는 상태에서만."""
    app = make_app(clock)
    rid = start_and_select(app)
    p = pid(app, rid)
    app.orchestrator.start_writing(rid)                                          # 계획서작성 · 실행
    assert app.store.acquire(rid, "worker-1", 60)                                # 워커가 계획서를 작성하는 중
    for fn in (lambda: app.orchestrator.select_announcement_for_project(p, "A02"),
               lambda: app.orchestrator.more_candidates_for_project(p),
               lambda: app.orchestrator.screen(p, 3)):
        assert code_of(fn) == "INVALID_STATE"
    assert app.store.load_run(rid).announcement_id == "A01"                      # 바뀐 것 없음
    waiting = start_and_select(app, "acc-2")                                     # 받을 수 있는 상태 (계획서작성 · 사용자대기)
    assert app.store.acquire(waiting, "cmd-other", 60)                           # 다른 명령이 점유 중
    for fn in (lambda: app.orchestrator.select_announcement_for_project(pid(app, waiting), "A02"),
               lambda: app.orchestrator.more_candidates_for_project(pid(app, waiting)),
               lambda: app.orchestrator.start_writing_for_project(pid(app, waiting))):
        assert code_of(fn) == "BUSY"


def test_start_and_proceed_rejected_by_state_while_lease_held(clock):
    """작성 시작 · '진행'도 점유 전에 상태를 본다 — 워커가 단계를 도는 중이거나 재작성을 모으는 중이면 BUSY가 아니라
    바로 INVALID_STATE ('모으는 동안 진행 명령'). 웹은 이때 지금 진행 상태를 돌려주면 된다."""
    app = make_app(clock)
    rid = start_and_select(app)
    p = pid(app, rid)
    app.orchestrator.start_writing_for_project(p)                                # 계획서작성 · 실행
    assert app.store.acquire(rid, "worker-1", 60)                                # 워커가 계획서를 작성하는 중
    for fn in (lambda: app.orchestrator.start_writing_for_project(p),
               lambda: app.orchestrator.decide_for_project(p, 6, "진행")):
        assert code_of(fn) == "INVALID_STATE"
    app.store.release(rid, "worker-1")

    rid6 = to_screen6(app, "acc-2")
    p6 = pid(app, rid6)
    app.orchestrator.request_rework_for_project(p6, DOCUMENT_BUNDLES[0])          # 모으는 중
    assert app.store.acquire(rid6, "cmd-other", 60)                              # 다른 묶음 요청이 점유 중
    assert code_of(lambda: app.orchestrator.decide_for_project(p6, 6, "진행")) == "INVALID_STATE"


def test_command_rechecks_state_when_lease_is_taken_in_between(clock, monkeypatch):
    """점유 전 확인은 통과했는데 그사이 다른 명령이 작성을 시작하고 워커가 가져가 점유를 못 잡으면 — 상태를 다시 읽어
    BUSY가 아니라 INVALID_STATE."""
    app = make_app(clock)
    rid = start_and_select(app)
    p = pid(app, rid)
    acquire = app.store.acquire

    def race(run_id, owner, lease_sec):
        monkeypatch.setattr(app.store, "acquire", acquire)
        app.orchestrator.start_writing(rid)                                      # 다른 명령이 먼저 작성 시작
        assert acquire(rid, "worker-1", 60)                                      # 워커가 가져감
        return False
    monkeypatch.setattr(app.store, "acquire", race)
    assert code_of(lambda: app.orchestrator.start_writing_for_project(p)) == "INVALID_STATE"
    assert app.store.load_run(rid).state.step == "계획서작성"


# ── 화면 10 시도별 기록 · 화면 8 · 9 '진행' ────────────────
def test_screen10_includes_attempts(clock):
    app = make_app(clock, StubScenario(tp1_targets=4, tp2_behavior={"s-3.1.1-2": ["violate", "ok"]}))
    rid = to_screen9(app)
    run_review(app, rid)
    s10 = app.orchestrator.screen(pid(app, rid), 10)
    ctx = app.engine.open_context(app.store.load_run(rid))
    results = {r.sentence_id: r.attempts for r in ctx.get("sentenceResults")}
    assert {c.sentence_id: c.attempts for c in s10.sentences} == results       # 학습 동의와 관계없이
    change = next(c for c in s10.sentences if c.sentence_id == "s-3.1.1-2")
    assert [(a.attempt_no, a.adopted, a.token_check.passed) for a in change.attempts] == [
        (1, False, False), (2, True, True)]
    dumped = next(s for s in s10.dump()["sentences"] if s["sentenceId"] == "s-3.1.1-2")
    assert dumped["attempts"][0]["attemptNo"] == 1 and dumped["attempts"][0]["tokenCheck"]["passed"] is False


def test_decide_screen8_and_9_proceed_unchanged(clock):
    app = make_app(clock, StubScenario(doc_scores=[52.0], art_scores=[(12.0, 7.0)]))
    rid = to_screen8(app)
    p = pid(app, rid)
    assert app.orchestrator.decide_for_project(p, 8, "진행") is None
    v = app.orchestrator.view_project(p).run
    assert (v.step, v.progress) == ("종합평가", "사용자대기")
    need = app.orchestrator.decide_for_project(p, 9, "진행")                     # 미달 — 확인받는다
    assert isinstance(need, ConfirmationNeeded) and need.items["현재 점수"] == 71.5   # 대조 7 → 7.5 (1.4판 몫)
    assert app.orchestrator.view_project(p).run.step == "종합평가"
    assert app.orchestrator.decide_for_project(p, 9, "진행", confirmed=True) is None
    app.orchestrator.advance(rid)
    assert app.orchestrator.view_project(p).run.progress == "완료"
