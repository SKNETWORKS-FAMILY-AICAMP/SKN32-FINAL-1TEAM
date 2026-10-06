"""공고 선택 · 자격 확인(G-01) — 선택 명령은 ID만, G-01이 공고 상세 · 자격 결과 · 업력을 한 번에 저장 (spec 4.3 · 4.5).

- 선택 명령은 고른 공고 ID와 고르기 전 대기 지점만 남기고, Run.announcement_id는 G-01이 성공할 때 바뀐다.
- G-01이 어떤 오류로 끝나도 실행은 살고, 안내(X-C2-GONE · X-C2-FAIL)와 함께 고르기 전 대기 지점으로 돌아간다.
- 자격 불통과 공고는 막힌 공고 목록에 들어가고 다시 고를 수 없다(ANNOUNCEMENT_BLOCKED). 공고 없음 · 오류 · 설립일 없음은 막지 않는다.
- 확인 필요(unknownConditions)는 막지 않고 화면 4에만 E-G1-UNPARSED를 붙인다.
- 마감 안내(E-RUN-CLOSED)는 마감일이 지났거나(비었으면 보지 않음) 모집 상태가 '마감'일 때.
"""
from __future__ import annotations

import inspect
from datetime import date

import pytest
from conftest import executed, make_app, pre_input, project_for, to_screen9
from webdb import create_web_tables

from sbrain.agents.stubs import StubScenario, make_announcement
from sbrain.bootstrap import build_stub_app, build_web
from sbrain.contracts import tasks as c
from sbrain.flow import SBrainOrchestrator
from sbrain.flow.catalog import artifact_types, build_registry
from sbrain.models import Announcement, AnnouncementCard, GateResult, Run
from sbrain.orchestrator.errors import COMMAND_ERROR_CODES, CommandError, message
from sbrain.orchestrator.settings import PROVISIONAL, Settings
from sbrain.store_sql import SqlStore, create_orchestrator_tables, create_sqlite_engine

GATE_KEYS = ("selectedAnnouncement", "gateResult", "businessAgeYears")


def pid(app, rid: str) -> str:
    return app.store.load_run(rid).project_id


def started(app, **form) -> str:
    res = app.orchestrator.start_run("acc-1", pre_input(**form), project_id=project_for(app))
    assert res.ok, res
    return res.run_id


def select(app, rid: str, aid: str) -> None:
    app.orchestrator.select_announcement(rid, aid)
    app.orchestrator.advance(rid)


def ctx_of(app, rid: str):
    return app.engine.open_context(app.store.load_run(rid))


def code_of(fn) -> str:
    with pytest.raises(CommandError) as e:
        fn()
    return e.value.code


def state(app, rid: str) -> tuple[str, str]:
    run = app.store.load_run(rid)
    return run.state.step, run.state.progress


def gate_snapshot(app, rid: str) -> tuple:
    """고르기 전 값 — 선택 공고 · 자격 결과 · 업력의 현재 버전과 Run.announcement_id."""
    ctx = ctx_of(app, rid)
    return tuple(ctx.version(k) for k in GATE_KEYS) + (ctx.run.announcement_id,)


def spy_commits(app) -> list[dict]:
    """저장 묶음마다 산출물 키와 그때의 실행 건 값(공고 포인터 · 막힌 공고)을 남긴다."""
    seen: list[dict] = []
    original = app.store.commit

    def commit(run_id, owner, batch):
        run = batch.run
        seen.append({"keys": {v.key for v in batch.versions},
                     "announcement_id": run.announcement_id if run else None,
                     "blocked": list(run.blocked_announcement_ids) if run else None})
        return original(run_id, owner, batch)
    app.store.commit = commit
    return seen


# ── 공고 선택 명령 (4.3.1) ─────────────────────────────
def test_select_records_only_id_and_before_step(clock):
    app = make_app(clock)
    rid = started(app)
    app.orchestrator.select_announcement(rid, "A01")
    run = app.store.load_run(rid)
    assert run.announcement_id is None                                           # 공고 포인터는 G-01이 바꾼다
    assert (run.state.step, run.state.progress, run.queue, run.segment) == ("자격확인", "실행", ["G-01"], "GATE")
    ctx = app.engine.open_context(run)
    assert not any(ctx.has(k) for k in GATE_KEYS)                               # 선택 공고를 만들지 않는다
    decision = ctx.get("decision")
    assert (decision["command"], decision["announcementId"], decision["beforeStep"]) == ("select", "A01", "공고선택")
    app.orchestrator.advance(rid)
    assert state(app, rid) == ("계획서작성", "사용자대기")
    app.orchestrator.select_announcement(rid, "A02")                             # 자격 통과 뒤 다시 고르기
    run = app.store.load_run(rid)
    assert run.announcement_id == "A01" and ctx_of(app, rid).get("decision")["beforeStep"] == "계획서작성"


def test_command_assembly_has_no_announcement_source():
    assert "announcements" not in inspect.signature(SBrainOrchestrator).parameters


def test_web_select_keeps_announcement_until_worker_g01(tmp_path):
    """웹 조립의 공고 선택은 공고를 받지 않는다 — 명령 뒤 announcement_id 그대로, 워커의 G-01이 상세를 받는다."""
    path = tmp_path / "web.db"
    engine = create_sqlite_engine(path, fast=True)
    create_orchestrator_tables(engine)
    create_web_tables(engine)
    worker = build_stub_app(store=SqlStore(engine))
    rid = worker.orchestrator.start_run("acc-1", pre_input()).run_id
    web = build_web(f"sqlite:///{path.as_posix()}", profile_count=lambda a: 1)
    web.orchestrator.select_announcement(rid, "A01")
    run = web.store.load_run(rid)
    assert (run.announcement_id, run.queue) == (None, ["G-01"])
    assert not web.engine.open_context(run).has("selectedAnnouncement")
    assert [r.task_id for r in web.store.executions(rid)] == ["T-C1", "T-C2"]    # 웹은 G-01을 돌지 않는다
    worker.orchestrator.advance(rid)
    run = web.store.load_run(rid)
    assert (run.state.step, run.announcement_id) == ("계획서작성", "A01")
    assert web.engine.open_context(run).get("selectedAnnouncement").announcement_id == "A01"


# ── G-01 (4.3.2) ──────────────────────────────────────
def test_g01_registered_as_task_with_tools():
    spec = build_registry().get("G-01")
    assert (spec.kind, spec.uses_llm, spec.counted, spec.failure.resumable) == ("task", False, False, False)
    assert spec.outputs == {"gate_result": "gateResult", "business_age_years": "businessAgeYears",
                            "selected_announcement": "selectedAnnouncement"}
    assert set(spec.inputs) == {"company_info", "today", "announcement_id"}       # eligibility 연결은 없다
    exact, _ = artifact_types(build_registry())
    assert exact["selectedAnnouncement"] is Announcement                          # 등록부 출력에서 온다 (겹침 없음)
    assert Settings().task_timeouts["G-01"] == 30.0
    for key in ("taskTimeouts.G-01", "announcement.unknownStatus", "announcement.formSpec", "notice.X-C2-GONE"):
        assert key in PROVISIONAL
    fields = c.G01In.model_fields
    assert fields["announcement_id"].is_required() and not fields["eligibility"].is_required()
    assert not fields["eligibility_parsed"].is_required()


def test_g01_saves_announcement_gate_and_age_in_one_step(clock):
    app = make_app(clock)
    rid = started(app)
    batches = spy_commits(app)
    select(app, rid, "A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.announcement_id) == ("계획서작성", "사용자대기", "A01")
    ctx = ctx_of(app, rid)
    ann, gate, age = (ctx.get(k) for k in GATE_KEYS)
    assert ann.announcement_id == "A01" and gate.passed and gate.unknown_conditions == []
    assert age == 1.5                                     # 법인 2025-03-02 설립, 기준일 2026-09-26 → 18개월
    rec = [r for r in app.store.executions(rid) if r.task_id == "G-01"][-1]
    assert set(rec.outputs) == {ctx.ref(k) for k in GATE_KEYS} and rec.status == "성공"
    assert {ctx.producer_of(ctx.ref(k)) for k in GATE_KEYS} == {rec.execution_id}
    [saved] = [b for b in batches if "gateResult" in b["keys"]]                   # 한 번의 저장
    assert set(GATE_KEYS) <= saved["keys"] and saved["announcement_id"] == "A01"


def test_g01_trace_uses_tools_like_tc2(clock):
    app = make_app(clock)
    rid = started(app)
    select(app, rid, "A01")
    recs = {r.task_id: r for r in app.store.executions(rid)}
    assert recs["G-01"].step_kind == "task" and recs["G-01"].model == recs["T-C2"].model
    calls = [c for c in app.store.call_logs(rid) if c.task_id == "G-01"]
    assert [c.purpose for c in calls] == ["공고 상세", "자격 판정"]
    assert {c.timeout_sec for c in calls} == {30.0} and {c.call_type for c in calls} == {"search"}
    dump = "".join(r.model_dump_json() for r in app.store.executions(rid)) + "".join(
        c.model_dump_json() for c in calls)
    assert "창업지원사업" not in dump and "김서준" not in dump                    # 기록에는 공고 · 신청자 내용이 없다


def test_unknown_conditions_pass_and_show_only_on_screen4(clock):
    app = make_app(clock, StubScenario(unknown_ids={"A01"}))
    rid = started(app)
    p = pid(app, rid)
    select(app, rid, "A01")
    assert state(app, rid) == ("계획서작성", "사용자대기")                       # 확인 필요는 막지 않는다
    s4 = app.orchestrator.screen(p, 4)
    assert s4.gate_result.passed and s4.can_start_writing
    assert s4.gate_result.unknown_conditions == ["지원대상 유형", "업력"]
    assert [(n.code, n.message) for n in s4.notices] == [("E-G1-UNPARSED", message("E-G1-UNPARSED"))]
    run = app.store.load_run(rid)
    assert "E-G1-UNPARSED" not in [n.code for n in run.notices]                  # 실행 건 안내 목록에는 쌓지 않는다
    assert "E-G1-UNPARSED" not in [n.code for n in app.orchestrator.view_project(p).run.notices]
    assert app.orchestrator.screen(p, 4).notices[-1].code == "E-G1-UNPARSED"    # 열 때마다 다시 만든다
    select(app, rid, "A02")
    assert [n.code for n in app.orchestrator.screen(p, 4).notices] == []         # 다른 공고를 고르면 사라진다
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert state(app, rid) == ("문서평가", "사용자대기")


def test_missing_founded_at_is_not_blocked_and_skips_judgment(clock):
    app = make_app(clock)
    rid = started(app, founded_at=None)                                          # 법인인데 설립일 없음
    select(app, rid, "A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.notices[-1].code) == ("공고선택", "E-G1-MISSING")
    gate = ctx_of(app, rid).get("gateResult")
    assert (gate.passed, gate.missing_inputs, gate.failed_conditions) == (False, ["foundedAt"], [])
    assert run.blocked_announcement_ids == []
    assert [c.purpose for c in app.store.call_logs(rid) if c.task_id == "G-01"] == ["공고 상세"]  # 판정을 부르지 않는다
    select(app, rid, "A01")                                                      # 막지 않으므로 다시 고를 수 있다
    assert executed(app, rid).count("G-01") == 2


# ── G-01 실패 (4.3.4) · 다시 고르기 (4.3.5) ──────────────
FAILURES = {
    "공고없음": (lambda sc: sc.not_found_ids.add("A02"), "X-C2-GONE"),
    "코드오류": (lambda sc: sc.raise_in.add("G-01"), "X-C2-FAIL"),
    "재시도소진": (lambda sc: sc.exhaust_in.add("G-01"), "X-C2-FAIL"),
}


@pytest.mark.parametrize("kind", list(FAILURES))
def test_g01_failure_from_writing_wait_keeps_previous_selection(clock, kind):
    sc = StubScenario()
    app = make_app(clock, sc)
    rid = started(app)
    select(app, rid, "A01")                                                      # 통과 → 계획서작성 · 사용자대기
    before = gate_snapshot(app, rid)
    FAILURES[kind][0](sc)
    select(app, rid, "A02")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress) == ("계획서작성", "사용자대기")  # 고르기 전 대기 지점
    assert (run.notices[-1].code, run.notices[-1].message) == (FAILURES[kind][1], message(FAILURES[kind][1]))
    assert gate_snapshot(app, rid) == before and run.announcement_id == "A01"
    assert run.blocked_announcement_ids == [] and run.failure_reason is None
    assert "E-RUN-FAIL" not in [n.code for n in run.notices] and app.store.notifications(rid) == []
    assert [r.status for r in app.store.executions(rid) if r.task_id == "G-01"] == ["성공", "실패"]
    assert app.orchestrator.screen(pid(app, rid), 4).announcement_id == "A01"
    app.orchestrator.start_writing(rid)                                          # 이미 통과한 공고로 작성 시작
    app.orchestrator.advance(rid)
    assert state(app, rid) == ("문서평가", "사용자대기")


@pytest.mark.parametrize("kind", list(FAILURES))
def test_g01_failure_from_selection_wait_keeps_previous_selection(clock, kind):
    sc = StubScenario(gate_fail_ids={"A03"})
    app = make_app(clock, sc)
    rid = started(app)
    select(app, rid, "A03")                                                      # 불통과 → 공고선택 · 사용자대기
    before = gate_snapshot(app, rid)
    assert before[-1] == "A03"
    FAILURES[kind][0](sc)
    select(app, rid, "A02")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.notices[-1].code) == ("공고선택", "사용자대기", FAILURES[kind][1])
    assert gate_snapshot(app, rid) == before
    assert run.blocked_announcement_ids == ["A03"]                               # 실패한 공고는 막지 않는다


def test_g01_contract_violation_is_rescued(clock):
    app = make_app(clock)
    rid = started(app)
    app.registry.bind("G-01", lambda inp, tools: {"gate_result": {"passed": True}})
    select(app, rid, "A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.notices[-1].code) == ("공고선택", "사용자대기", "X-C2-FAIL")
    assert run.announcement_id is None and not ctx_of(app, rid).has("gateResult")


def test_not_found_announcement_can_be_selected_again(clock):
    sc = StubScenario(not_found_ids={"A01"})
    app = make_app(clock, sc)
    rid = started(app)
    select(app, rid, "A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.notices[-1].code, run.announcement_id) == ("공고선택", "X-C2-GONE", None)
    assert run.blocked_announcement_ids == [] and not ctx_of(app, rid).has("selectedAnnouncement")
    select(app, rid, "A01")                                                      # 여전히 없으면 같은 안내
    assert [n.code for n in app.store.load_run(rid).notices][-2:] == ["X-C2-GONE", "X-C2-GONE"]
    sc.not_found_ids.discard("A01")                                              # 다시 생겼다
    select(app, rid, "A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.announcement_id) == ("계획서작성", "A01")
    assert executed(app, rid).count("G-01") == 3                                 # 고를 때마다 새로 묻는다


def test_prestage_tc2_errors_still_end_start_request(clock):
    """사전 단계(첫 조회) T-C2의 오류 처리는 그대로 — 시작 요청이 X-C2-FAIL로 끝나고 실행 건은 없다."""
    for sc in (StubScenario(raise_in={"T-C2"}), StubScenario(exhaust_in={"T-C2"})):
        app = make_app(clock, sc)
        res = app.orchestrator.start_run("acc-1", pre_input())
        assert (res.ok, res.code) == (False, "X-C2-FAIL") and app.store.list_runs("acc-1") == []


# ── 막힌 공고 (4.3.6, 풀림 빼고) ─────────────────────────
def test_rejected_announcement_is_blocked_in_same_save(clock):
    app = make_app(clock, StubScenario(gate_fail_ids={"A01"}))
    rid = started(app)
    p = pid(app, rid)
    batches = spy_commits(app)
    select(app, rid, "A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.notices[-1].code) == ("공고선택", "E-G1-REJECT")
    assert run.blocked_announcement_ids == ["A01"] and run.announcement_id == "A01"
    [saved] = [b for b in batches if "gateResult" in b["keys"]]
    assert saved["blocked"] == ["A01"]                                           # G-01 결과와 같은 저장
    s3 = app.orchestrator.screen(p, 3)
    assert s3.blocked_announcement_ids == ["A01"] and s3.dump()["blockedAnnouncementIds"] == ["A01"]
    card_keys = set(s3.dump()["candidates"][0])
    assert card_keys == {f.alias for f in AnnouncementCard.model_fields.values()}  # 카드에는 자격 정보가 없다
    assert not {k for k in card_keys if any(w in k.lower() for w in ("block", "gate", "pass", "eligib"))}
    assert "blockedAnnouncementIds" not in app.orchestrator.outputs(p).dump()   # 막힘은 화면 3에만


def test_blocked_announcement_is_refused_without_change(clock):
    app = make_app(clock, StubScenario(gate_fail_ids={"A01"}))
    rid = started(app)
    p = pid(app, rid)
    select(app, rid, "A01")
    before = app.store.load_run(rid).dump()
    versions = dict(ctx_of(app, rid).latest)
    assert code_of(lambda: app.orchestrator.select_announcement(rid, "A01")) == "ANNOUNCEMENT_BLOCKED"
    assert code_of(lambda: app.orchestrator.select_announcement_for_project(p, "A01")) == "ANNOUNCEMENT_BLOCKED"
    assert code_of(lambda: app.orchestrator.select_announcement(rid, "없는-공고")) == "INVALID_ANNOUNCEMENT"
    assert app.store.load_run(rid).dump() == before and dict(ctx_of(app, rid).latest) == versions
    assert "ANNOUNCEMENT_BLOCKED" in COMMAND_ERROR_CODES
    select(app, rid, "A02")                                                      # 다른 공고는 고를 수 있다
    run = app.store.load_run(rid)
    assert (run.state.step, run.blocked_announcement_ids) == ("계획서작성", ["A01"])
    assert app.orchestrator.screen(p, 3).blocked_announcement_ids == ["A01"]     # 자격 통과 뒤 화면 3에도


def test_blocked_list_survives_reload_and_old_json(clock):
    app = make_app(clock, StubScenario(gate_fail_ids={"A01", "A02"}))
    rid = started(app)
    select(app, rid, "A01")
    select(app, rid, "A02")
    assert app.store.load_run(rid).blocked_announcement_ids == ["A01", "A02"]   # 저장소에서 다시 읽어도 그대로
    data = app.store.load_run(rid).dump()
    data.pop("blockedAnnouncementIds")
    assert Run.model_validate(data).blocked_announcement_ids == []               # 예전 실행 건 JSON은 빈 목록
    other = make_app(clock)
    assert other.store.load_run(started(other)).blocked_announcement_ids == []  # 새 실행 건은 빈 목록에서 시작


def test_old_artifact_json_loads_with_new_defaults():
    old_card = {"announcementId": "A01", "title": "t", "agency": "a", "applyEnd": "2026-10-01",
                "supportAmountMax": 1, "fitScore": 0.5, "rank": 1, "displayType": "card", "matchReason": "m",
                "sourceNotice": "s", "originalUrl": "u"}
    card = AnnouncementCard.model_validate(old_card)
    assert (card.apply_period_type, card.content_changed, card.content_version, card.bonus_score,
            card.bonus_items) == ("모름", False, None, None, [])
    gate = GateResult.model_validate({"passed": True, "failedConditions": [], "missingInputs": [], "undecidable": False})
    assert gate.unknown_conditions == []
    old_ann = make_announcement("A01", date(2026, 9, 26)).dump()
    old_ann.pop("applyPeriodType")
    assert Announcement.model_validate(old_ann).apply_period_type == "모름"
    nullable = Announcement.model_validate({**old_ann, "applyStart": None, "applyEnd": None,
                                            "supportAmountMax": None, "supportAmountText": None})
    assert (nullable.apply_end, nullable.support_amount_max) == (None, None)


# ── 마감 안내 (4.5) ────────────────────────────────────
def test_run_closed_notice_by_deadline_or_status(clock):
    sc = StubScenario(no_deadline_ids={"A01", "A03"}, closed_ids={"A02", "A03"})
    app = make_app(clock, sc)
    rid = started(app)

    def closed() -> bool:
        return "E-RUN-CLOSED" in [n.code for n in app.orchestrator.view(rid).notices]
    select(app, rid, "A01")                                                      # 마감일 없음 · 모집중
    assert ctx_of(app, rid).get("selectedAnnouncement").apply_end is None and not closed()
    select(app, rid, "A02")                                                      # 모집 상태 '마감' (마감일은 남음)
    assert state(app, rid) == ("계획서작성", "사용자대기") and closed()         # G-01은 모집 상태를 판정하지 않는다
    select(app, rid, "A03")                                                      # 마감일 없음 · '마감'
    assert closed()
    select(app, rid, "A04")                                                      # 마감일 30일 뒤 · 모집중
    assert not closed()
    clock.advance(days=31)
    assert closed()                                                              # 마감일이 지났다
    assert "E-RUN-CLOSED" not in [n.code for n in app.store.load_run(rid).notices]   # 알리기만 한다


def test_null_dates_and_amounts_flow_to_the_end(clock):
    """뒤 단계 스텁이 비어 있는 마감일 · 지원 금액에서 멈추지 않는다 — 맥락 값은 null, 보호 토큰은 만들지 않는다."""
    app = make_app(clock, StubScenario(no_deadline_ids={"A01"}, no_amount_ids={"A01"}))
    rid = to_screen9(app)
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    assert state(app, rid) == ("결과물", "완료")
    ctx = ctx_of(app, rid)
    ann = ctx.get("selectedAnnouncement")
    assert (ann.apply_end, ann.support_amount_max, ann.support_amount_text) == (None, None, None)
    context = ctx.get("taskPlan").tasks[0].context
    assert set(context) == {"formVersion", "applyEnd", "supportAmountMax", "evaluationItems", "formatSpec"}
    assert (context["applyEnd"], context["supportAmountMax"]) == (None, None)
    tokens = ctx.get("protectedTokens")
    assert not [t for t in tokens if t.type == "날짜"] and "None" not in [t.value for t in tokens]
