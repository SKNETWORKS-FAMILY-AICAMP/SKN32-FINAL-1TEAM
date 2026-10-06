"""T-P2 문장 병렬 처리 · 시도별 기록 · 웹 proofread_logs(검수 회수 문단)와 추적 기록 원칙."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from conftest import Backend, Clock, executed, make_app, pre_input, set_consent, to_screen9
from mysqldb import old_proofread_logs
from webdb import OLD_PROOFREAD_LOGS, PROOFREAD_LOGS, count_rows, proofread_rows, use_old_proofread_logs

from sbrain.agents.stubs import StubScenario
from sbrain.contracts.tasks import SentenceResult
from sbrain.flow.sbrain_flow import violation_note, violation_reason, violation_type
from sbrain.models import Token, TokenCheckResult, extension_fields
from sbrain.orchestrator.trace import ExecutionRecord
from sbrain.store_sql import SqlStore

# 문장별 T-P2 결과 (재수행 횟수 순서): 채택 · 반려 뒤 채택 · 반려 뒤 조기 중단 · 반려만 (검수 재수행 2회)
BEHAVIOR = {
    "s-1-1-1": ["ok"],
    "s-1-1-2": ["violate", "ok"],
    "s-2-1-1": ["violate", "same", "same"],
    "s-2-1-2": ["violate", "violate", "violate"],
}
TARGETS = list(BEHAVIOR)


def run_review(app, rid):
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)


def sentence_results(app, rid):
    ctx = app.engine.open_context(app.store.load_run(rid))
    return {r.sentence_id: r for r in ctx.get("sentenceResults")}, ctx


def test_tp2_redo_early_stop_and_keep_original(clock):
    sc = StubScenario(tp1_targets=4, tp2_behavior={
        "s-1-1-1": ["ok"],
        "s-1-1-2": ["violate", "ok"],             # 1회 재수행 후 채택
        "s-2-1-1": ["violate", "same", "same"],   # 지시를 바꿔도 같은 출력 → 조기 중단
        "s-2-1-2": ["violate", "violate", "violate"],  # 검수 재수행 횟수 초과 → 원문 유지
    })
    app = make_app(clock, sc)
    rid = to_screen9(app)
    run_review(app, rid)
    res, ctx = sentence_results(app, rid)
    assert res["s-1-1-1"].adopted and res["s-1-1-1"].final_redo_count == 0
    assert res["s-1-1-2"].adopted and res["s-1-1-2"].final_redo_count == 1
    assert res["s-2-1-1"].kept_reason == "조기중단"
    assert (res["s-2-1-2"].kept_reason, res["s-2-1-2"].final_redo_count) == ("검증실패", 2)
    log = ctx.get("proofreadLog")
    assert log.adopted_count == 2 and log.early_stopped_sentence_ids == ["s-2-1-1"]
    assert log.retained_by_check_ids == ["s-2-1-2"] and log.token_preservation_rate == 0.25
    # 채택 문장만 계획서에 반영
    plan = ctx.get("planDoc")
    texts = {s.sentence_id: s.text for sec in plan.sections for s in sec.sentences}
    assert texts["s-1-1-1"].endswith("(윤문)") and not texts["s-2-1-2"].endswith("(윤문)")
    # 호출 로그는 문장별, 입력 · 출력 이력은 Task 단위
    tp2 = [r for r in app.store.executions(rid) if r.task_id == "T-P2"]
    assert len(tp2) == 1 and tp2[0].outputs == ["sentenceResults@1"]
    assert tp2[0].temperature <= 0.2
    calls = [c for c in app.store.call_logs(rid) if c.task_id == "T-P2"]
    assert {c.item_key for c in calls} == set(res)
    assert sum(1 for c in calls if c.item_key == "s-2-1-2") == 3  # 첫 호출 + 재수행 2회


def test_tp2_redo_hint_accumulates(clock):
    sc = StubScenario(tp1_targets=1, tp2_behavior={"s-1-1-1": ["violate", "violate", "ok"]})
    app = make_app(clock, sc)
    seen = []
    base = app.registry.get("T-P2").fn

    def spy(inp, tools):
        seen.append(list(inp.redo_hint))
        return base(inp, tools)
    app.registry.bind("T-P2", spy)
    rid = to_screen9(app)
    run_review(app, rid)
    assert seen == [[], ["'1억원' 유지"], ["'1억원' 유지"]]  # 교체하지 않고 누적 (같은 문구는 한 번)


def test_tp2_call_failures_keep_original_or_resume_by_ratio(clock):
    sc = StubScenario(tp1_targets=4)
    app = make_app(clock, sc)
    app.llm.plan("T-P2", ["timeout"] * 6, item_key="s-1-1-1")  # 1/4 = 25% ≤ 30% → 원문 유지하고 완료
    rid = to_screen9(app)
    run_review(app, rid)
    res, _ = sentence_results(app, rid)
    assert res["s-1-1-1"].kept_reason == "호출실패"
    assert app.store.load_run(rid).state.progress == "완료"

    app = make_app(clock, StubScenario(tp1_targets=4))
    for sid in ("s-1-1-1", "s-1-1-2"):
        app.llm.plan("T-P2", ["timeout"] * 6, item_key=sid)  # 2/4 = 50% > 30% → 재개
    rid = to_screen9(app, account="acc-2")
    run_review(app, rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기" and run.state.step == "표현검수"
    clock.advance(minutes=16)
    app.orchestrator.tick(clock.t)
    res, _ = sentence_results(app, rid)
    assert all(r.adopted for r in res.values())  # 실패한 문장만 다시 처리
    assert app.store.load_run(rid).state.progress == "완료"
    tp2 = [r for r in app.store.executions(rid) if r.task_id == "T-P2"]
    assert len(tp2) == 1 and tp2[0].resume_count == 1


def test_tp2_skipped_when_no_tokens(clock):
    app = make_app(clock, StubScenario(no_tokens=True))
    rid = to_screen9(app)
    run_review(app, rid)
    tp2 = [r for r in app.store.executions(rid) if r.task_id == "T-P2"][0]
    assert tp2.status == "생략" and "보호 토큰" in tp2.output_meta.note
    assert app.store.load_run(rid).state.progress == "완료"


def test_trace_covers_rule_and_merge_steps_without_content(clock):
    app = make_app(clock)
    res = app.orchestrator.start_run("acc-1", pre_input())
    rid = res.run_id
    app.orchestrator.select_announcement(rid, "A01")
    app.orchestrator.advance(rid)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    recs = {r.task_id: r for r in app.store.executions(rid)}
    for tid in ("M-1", "G-02a"):
        assert recs[tid].step_kind in ("rule", "merge") and recs[tid].model is None
        assert recs[tid].inputs and recs[tid].outputs
    # G-01은 tools를 받는 Task(공고 서버 호출, LLM 없음) — 모델 표시는 T-C2와 같다 (spec 5)
    assert recs["G-01"].step_kind == "task" and recs["G-01"].model == recs["T-C2"].model
    assert recs["G-01"].inputs and recs["G-01"].outputs
    # 첫 실행도 입력 산출물명@버전을 남긴다
    assert "planDoc@2" in recs["T-V1"].inputs and "planDoc@1" in recs["M-1"].inputs
    assert recs["T-S1"].model == "미정" and recs["T-S1"].agent == "전략"
    # 기록에는 산출물 내용이 없다 (참조와 메타만)
    dump = "".join(r.model_dump_json() for r in app.store.executions(rid))
    assert "헬스장" not in dump and "김서준" not in dump
    assert extension_fields(ExecutionRecord)  # 확장 필드 표시


def test_settings_snapshot_fixed_at_start(clock):
    app = make_app(clock)
    res = app.orchestrator.start_run("acc-1", pre_input())
    s = app.settings.current().model_copy(deep=True)
    s.scoring.threshold = 50
    s.agents["전략"].model = "바뀐 모델"
    app.settings.update(s)
    app.orchestrator.select_announcement(res.run_id, "A01")
    app.orchestrator.advance(res.run_id)
    app.orchestrator.start_writing(res.run_id)
    app.orchestrator.advance(res.run_id)
    recs = {r.task_id: r for r in app.store.executions(res.run_id)}
    assert recs["T-S1"].model == "미정"  # 실행 시작 시점 값
    ctx = app.engine.open_context(app.store.load_run(res.run_id))
    assert ctx.get("scoreReport.document").threshold == 80
    assert ctx.get("scoreReport.document").settings_snapshot["scoring"]["threshold"] == 80


# ── 시도별 기록 · 웹 proofread_logs ──────────────────────
def original_texts(app, rid) -> dict[str, str]:
    """T-P2가 받은 계획서(윤문 전)의 문장."""
    ctx = app.engine.open_context(app.store.load_run(rid))
    tp2 = next(r for r in app.store.executions(rid) if r.task_id == "T-P2")
    plan = ctx.get_ref(next(ref for ref in tp2.inputs if ref.startswith("planDoc@")))
    return {s.sentence_id: s.text for sec in plan.sections for s in sec.sentences}


def test_tp2_records_every_attempt(clock):
    app = make_app(clock, StubScenario(tp1_targets=4, tp2_behavior=BEHAVIOR))
    rid = to_screen9(app)
    run_review(app, rid)
    res, _ = sentence_results(app, rid)
    assert {sid: [(a.attempt_no, a.adopted, a.token_check.passed) for a in r.attempts] for sid, r in res.items()} == {
        "s-1-1-1": [(1, True, True)],
        "s-1-1-2": [(1, False, False), (2, True, True)],
        "s-2-1-1": [(1, False, False), (2, False, False), (3, False, False)],   # 조기 중단한 시도도 시도
        "s-2-1-2": [(1, False, False), (2, False, False), (3, False, False)],
    }
    rejected, adopted = res["s-1-1-2"].attempts
    assert (rejected.text, rejected.token_check.missing_tokens, rejected.violation_type) == ("변형 0", ["1억원"], "수치·금액")
    assert adopted.text.endswith("(윤문)") and adopted.violation_type is None
    assert [a.text for a in res["s-2-1-1"].attempts] == ["변형 0", "동일 출력", "동일 출력"]
    assert "attempts" in extension_fields(SentenceResult)
    assert app.store.rejected_attempts(rid) == []                     # 학습 미동의 — 시도 기록은 산출물에만


def test_rejected_attempts_go_to_proofread_logs_when_owner_agreed(clock):
    app = make_app(clock, StubScenario(tp1_targets=4, tp2_behavior=BEHAVIOR))
    rid = to_screen9(app)
    set_consent(app, rid)                                             # 프로젝트를 만들 때는 미동의 — 쓰는 순간 읽는다
    run_review(app, rid)
    res, _ = sentence_results(app, rid)
    original = original_texts(app, rid)
    rows = app.store.rejected_attempts(rid)
    assert [(r.original_text, r.corrected_text, r.attempt_no) for r in rows] == [
        (original[sid], a.text, a.attempt_no) for sid in TARGETS for a in res[sid].attempts if not a.token_check.passed]
    assert len(rows) == 7                                             # 반려된 시도마다 한 행
    first = rows[0]
    assert (first.original_text, first.corrected_text) == (original["s-1-1-2"], "변형 0")
    assert (first.reason, first.violation_type, first.violation_note) == (
        "보호 토큰 검사 불통과 (빠짐 1건)", "수치·금액", "빠짐: 1억원")
    tp2 = next(r for r in app.store.executions(rid) if r.task_id == "T-P2")
    assert {r.model_version for r in rows} == {tp2.model} == {"미정"}   # 그 시도를 만든 T-P2 실행의 모델
    if isinstance(app.store, SqlStore):                               # 웹 행: 나머지 컬럼은 웹 기본값
        raw = proofread_rows(app.store.engine, int(app.store.load_run(rid).project_id))
        assert len(raw) == 7 and all(not r["passed"] and r["recovery_status"] == "pending" for r in raw)
        assert {(r["plan_id"], r["section_id"], float(r["score"]), r["recovery_label"]) for r in raw} == {
            (None, None, 100.0, None)}
        assert raw[0]["corrected_text"] == "변형 0" and raw[0]["model_version"] == "미정"


def test_tp2_resume_continues_attempt_numbers_without_duplicate_rows(clock):
    app = make_app(clock, StubScenario(tp1_targets=4, tp2_behavior={"s-1-1-1": ["violate", "ok"]}))
    app.llm.plan("T-P2", ["ok"] + ["timeout"] * 6, item_key="s-1-1-1")   # 시도 1 반려 → 재수행 호출 실패
    app.llm.plan("T-P2", ["timeout"] * 6, item_key="s-1-1-2")            # 첫 호출부터 실패 — 시도가 아니다
    rid = to_screen9(app)
    set_consent(app, rid)
    run_review(app, rid)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기"                                # 2/4 = 50% > 30% → 재개
    res, _ = sentence_results(app, rid)
    assert res["s-1-1-1"].kept_reason == "호출실패" and [a.attempt_no for a in res["s-1-1-1"].attempts] == [1]
    assert res["s-1-1-2"].kept_reason == "호출실패" and res["s-1-1-2"].attempts == []
    assert [r.attempt_no for r in app.store.rejected_attempts(rid)] == [1]  # 재개 예약 저장과 같은 트랜잭션
    clock.t = run.next_resume_at + timedelta(seconds=1)
    app.engine.resume(rid)
    res, _ = sentence_results(app, rid)
    assert [(a.attempt_no, a.adopted) for a in res["s-1-1-1"].attempts] == [(1, False), (2, False), (3, True)]
    assert [(a.attempt_no, a.adopted) for a in res["s-1-1-2"].attempts] == [(1, True)]
    assert [r.attempt_no for r in app.store.rejected_attempts(rid)] == [1, 2]   # 같은 시도를 두 번 쓰지 않는다
    assert app.store.load_run(rid).state.progress == "완료"


def test_violation_type_follows_missing_altered_contaminated_order():
    tokens = [Token(type="날짜", value="2026-10-01", count=1), Token(type="고유명사", value="헬스온", count=1),
              Token(type="수치금액", value="1억원", count=1), Token(type="기능명", value="회원 관리", count=1)]

    def check(m=(), a=(), c=()) -> TokenCheckResult:
        return TokenCheckResult(passed=False, missing_tokens=list(m), altered_tokens=list(a),
                                contaminated_tokens=list(c))
    assert violation_type(check(m=["1억원", "2026-10-01"], a=["헬스온"]), tokens) == "수치·금액"
    assert violation_type(check(m=["없는 값"], a=["헬스온"], c=["1억원"]), tokens) == "고유명사"   # 못 맞추면 다음
    assert violation_type(check(a=["2026-10-01"], c=["헬스온"]), tokens) == "날짜"
    assert violation_type(check(c=["회원 관리"]), tokens) == "기능명"
    assert violation_type(check(m=["없는 값"]), tokens) is None
    assert violation_type(check(), tokens) is None
    both = check(m=["1억원"], c=["헬스온", "회원 관리"])
    assert violation_note(both) == "빠짐: 1억원 / 섞임: 헬스온, 회원 관리"            # 위반 토큰 목록 전체
    assert violation_reason(both) == "보호 토큰 검사 불통과 (빠짐 1건 · 섞임 2건)"
    assert (violation_note(check()), violation_reason(check())) == ("", "보호 토큰 검사 불통과")


def test_rejected_attempt_content_stays_out_of_records(clock):
    """proofread_logs 행만 문장 내용을 갖는다 — 실행 기록 · 호출 기록 · 추적 사건 · 관리자 조회에는 없다."""
    app = make_app(clock, StubScenario(tp1_targets=4, tp2_behavior=BEHAVIOR))
    rid = to_screen9(app)
    set_consent(app, rid)
    run_review(app, rid)
    assert app.store.rejected_attempts(rid)
    pid = app.store.load_run(rid).project_id
    tp2 = next(r for r in app.store.executions(rid) if r.task_id == "T-P2")
    models = [*app.store.executions(rid), *app.store.call_logs(rid), *app.store.events(rid),
              *app.store.feedback(rid), *app.store.pointer_events(rid), *app.store.notifications(rid),
              *app.orchestrator.admin_executions(project_id=pid, limit=100),
              *app.orchestrator.admin_calls(tp2.execution_id)]
    blob = "".join(m.model_dump_json() for m in models)
    for content in ("변형 0", "동일 출력", "문장 1 (1억원)", "(윤문)"):
        assert content not in blob


@pytest.fixture(params=["sql", "mysql"])
def old_web(request, tmp_path):
    """웹 proofread_logs가 아직 옛 모양(project_id · model_version 없음, plan_id NOT NULL)인 SqlStore 앱."""
    clock = Clock()
    store = Backend(request.param, tmp_path).make_store(clock)

    def app(scenario: StubScenario):
        return make_app(clock, scenario, store=store)
    if request.param == "sql":
        use_old_proofread_logs(store.engine)
        yield app, clock
    else:
        with old_proofread_logs(store.engine):
            yield app, clock


def test_old_proofread_logs_structure_skips_rows_but_saves_step(old_web):
    make, clock = old_web
    app = make(StubScenario(tp1_targets=4, tp2_behavior={"s-1-1-1": ["violate", "ok"]}))
    app.llm.plan("T-P2", ["ok"] + ["timeout"] * 6, item_key="s-1-1-1")
    app.llm.plan("T-P2", ["timeout"] * 6, item_key="s-1-1-2")
    rid = to_screen9(app, account=uuid.uuid4().hex[:12])
    set_consent(app, rid)
    run_review(app, rid)                                              # 반려 시도가 있는 T-P2 저장 1 (재개 예약)
    run = app.store.load_run(rid)
    assert run.state.progress == "재개대기"
    clock.t = run.next_resume_at + timedelta(seconds=1)
    app.engine.resume(rid)                                            # 반려 시도가 있는 T-P2 저장 2
    assert app.store.load_run(rid).state.progress == "완료"            # 단계 저장 · 검수는 정상
    res, _ = sentence_results(app, rid)
    assert [a.attempt_no for a in res["s-1-1-1"].attempts] == [1, 2, 3]
    skipped = [e for e in app.store.events(rid) if e.kind == "검수회수기록생략"]
    assert len(skipped) == 1                                          # 실행 건마다 한 번
    assert "변형" not in skipped[0].detail and "1억원" not in skipped[0].detail   # 내용 없이 이유만
    assert app.store.rejected_attempts(rid) == []
    assert count_rows(app.store.engine, "proofread_logs") == 0


@pytest.mark.parametrize("backend", ["sql", "mysql"])
def test_proofread_logs_writes_start_after_web_schema_change_without_restart(backend, tmp_path):
    """맞지 않는 구조는 기억하지 않는다 — 웹팀이 구조를 바꾸면 같은 프로세스(같은 저장소)의 다음 T-P2 저장부터 쓴다."""
    clock = Clock()
    store = Backend(backend, tmp_path).make_store(clock)
    scenario = StubScenario(tp1_targets=1, tp2_behavior={"s-1-1-1": ["violate", "ok"]})

    def review_once() -> str:
        app = make_app(clock, scenario, store=store)
        rid = to_screen9(app, account=uuid.uuid4().hex[:12])
        set_consent(app, rid)
        run_review(app, rid)
        assert store.load_run(rid).state.progress == "완료"
        return rid

    if backend == "sql":
        use_old_proofread_logs(store.engine)
        old_rid = review_once()
        OLD_PROOFREAD_LOGS.drop(store.engine)                           # 웹팀의 스키마 변경
        PROOFREAD_LOGS.create(store.engine)
    else:
        with old_proofread_logs(store.engine):
            old_rid = review_once()
    assert [e.kind for e in store.events(old_rid)].count("검수회수기록생략") == 1
    assert store.rejected_attempts(old_rid) == []

    rid = review_once()                                                 # 다시 띄우지 않고 같은 저장소로
    assert "검수회수기록생략" not in [e.kind for e in store.events(rid)]
    rows = proofread_rows(store.engine, int(store.load_run(rid).project_id))
    assert [(r["attempt_no"], bool(r["passed"])) for r in rows] == [(1, False)]


def test_test_web_proofread_logs_shape():
    """테스트용 웹 proofread_logs — project_id는 NULL 허용 · projects 삭제 때 SET NULL, created_at이 있다(저장 시각을 넣음)."""
    col = PROOFREAD_LOGS.c.project_id
    assert col.nullable and [fk.ondelete for fk in col.foreign_keys] == ["SET NULL"]
    assert "created_at" in PROOFREAD_LOGS.c and "created_at" in OLD_PROOFREAD_LOGS.c
