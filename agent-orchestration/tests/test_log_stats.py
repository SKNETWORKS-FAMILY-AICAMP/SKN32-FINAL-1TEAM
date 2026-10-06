"""실행 로그 → 통계 줄 (기록 옮기기 4.1 ~ 4.4) — 식별자 · 자유 글 없이 개수 · 점수 · 고정 값만."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import to_screen6

from sbrain.agents.stubs import StubScenario
from sbrain.flow.log_stats import RunRecords, run_stats_row, start_request_rows
from sbrain.flow.reads import admin_runs
from sbrain.models import Notice, ReworkComparison, Run
from sbrain.models.run import make_state
from sbrain.orchestrator.store import LogStatsRow, StartRequest
from sbrain.orchestrator.trace import (
    CallLog, CallTry, ExecutionRecord, FeedbackLink, OutputMeta, PointerEvent, TraceEvent,
)

UTC = timezone.utc
T0 = datetime(2026, 1, 31, 16, 0, tzinfo=UTC)   # 한국 2026-02-01 01:00
M = "MARKER"                                     # 식별자 · 자유 글 표시 — 통계 줄 어디에도 나오면 안 된다

TOP_KEYS = {"step", "scores", "finalScores", "tasks", "rework", "run"}
SCORE_KEYS = {"docScore", "codeCheck", "featureMatch", "artifactScore", "overall"}
TASK_KEYS = {"runs", "status", "resumes", "retries", "errorKinds", "callErrorKinds", "tokens"}


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def make_run(**over) -> Run:
    base = dict(run_id=f"{M}-run", account_id=f"{M}-acc", state=make_state("결과물", "완료"), current_phase="review",
                settings_snapshot={}, updated_at=at(500), created_at=T0, project_id=f"{M}-proj",
                announcement_id=f"{M}-ann", failure_reason=f"{M} 실패 사유", retry_count=2, resume_count=1,
                last_error_kind="일시", blocked_announcement_ids=[f"{M}-blocked"], proofread_base_ref=f"{M}ref@1",
                notices=[Notice(code="E-RUN-CLOSED", message=f"{M} 공고 안내", at=T0)])
    base.update(over)
    return Run(**base)


def rec(n: int, task: str, trigger: str = "첫실행", status: str = "성공", *, ended: int, outputs=(), meta=None,
        **over) -> ExecutionRecord:
    base = dict(execution_id=f"{M}-ex-{n}", run_id=f"{M}-run", task_id=task, attempt=n, trigger=trigger,
                bundle_id=f"{M}-bundle", result_ref=f"{M}result@{n}", created_at=at(ended - 1), agent="작성",
                step_kind="task", model=f"{M}-model", provider=f"{M}-prov", status=status,
                inputs=[f"{M}input@1"], outputs=[f"{M}out@{n}", *outputs], output_meta=meta or OutputMeta(),
                cycle_id=f"{M}-cycle" if trigger == "재작성" else None, error=f"{M} 오류 요약" if status == "실패" else None,
                feedback_in=[f"{M}-fb"], started_at=at(ended - 1), ended_at=at(ended))
    base.update(over)
    return ExecutionRecord(**base)


def try_(no: int, error_kind: str | None = None) -> CallTry:
    return CallTry(no=no, started_at=T0, ended_at=T0, outcome="호출실패" if error_kind else "성공",
                   error_kind=error_kind, detail=f"{M} 상세")


def call(n: int, task: str, tries: list[CallTry]) -> CallLog:
    return CallLog(call_id=f"{M}-call-{n}", run_id=f"{M}-run", execution_id=f"{M}-ex-{n}", task_id=task,
                   agent="작성", call_type="llm", purpose=f"{M} 목적", item_key=f"{M}-item", model=f"{M}-model",
                   timeout_sec=30, tries=tries, final_outcome="성공", error=None)


def comparison(cycle: str, kept: str) -> ReworkComparison:
    return ReworkComparison(bundle_id=f"{M}-bundle", before_refs=[f"{M}a@1"], after_refs=[f"{M}a@2"],
                            before_score=50.0, after_score=60.0, kept=kept, cycle_id=f"{M}-{cycle}", screen=6,
                            basis="document", compared_at=T0)


def event(kind: str) -> TraceEvent:
    return TraceEvent(run_id=f"{M}-run", kind=kind, detail=f"{M} 사건 설명", refs=[f"{M}ref@1"],
                      execution_id=f"{M}-ex-1", cycle_id=f"{M}-cycle", at=T0)


def feedback() -> FeedbackLink:
    return FeedbackLink(feedback_id=f"{M}-fb", run_id=f"{M}-run", kind="재수행", source_execution_id=f"{M}-ex-1",
                        source_refs=[f"{M}src@1"], target_task_id="T-W1", target_execution_id=f"{M}-ex-2",
                        via_ref=f"{M}via@1", created_at=T0)


def pointer_event() -> PointerEvent:
    return PointerEvent(run_id=f"{M}-run", key="docScore", from_version=2, to_version=1, reason=f"{M} 되돌리기",
                        cycle_id=f"{M}-cycle", at=T0)


def full_records() -> RunRecords:
    """T-W1 네 번(첫실행 · 재수행 실패 · 재수행 · 재작성 재개대기), 채점 다섯 층(되돌린 재작성 채점 포함), 실패한 채점 하나."""
    executions = [
        # 일부러 끝 시각 순서와 다르게 둔다 — 점수는 끝 시각 순이어야 한다
        rec(9, "T-V1", "재작성", ended=90, outputs=["docScore@2"], meta=OutputMeta(score=60.0)),
        rec(1, "T-W1", ended=10, input_tokens=1000, output_tokens=700, reasoning_tokens=100),
        rec(2, "T-W1", "재수행", "실패", ended=20, error_kind="일시", resume_count=1, input_tokens=200,
            cached_input_tokens=50, output_tokens=100),
        rec(3, "T-W1", "재수행", ended=30),
        rec(4, "T-W1", "재작성", "재개대기", ended=95, resume_count=2),
        rec(5, "T-V1", ended=40, outputs=["docScore@1"], meta=OutputMeta(score=52.0)),
        rec(6, "T-V1", "재작성", "실패", ended=91, error_kind="운영", meta=OutputMeta(score=99.0)),
        rec(7, "T-V2", ended=50, outputs=["artifactScore@1", "codeCheck@1", "featureMatch@1"],
            meta=OutputMeta(score=55.0, code_check_score=30.0, feature_match_score=25.0)),
        rec(8, "G-02b", "재작성", ended=60, outputs=["scoreReport.overall@1"], meta=OutputMeta(score=81.0)),
        rec(10, "M-1", ended=70, step_kind="merge"),
    ]
    calls = [
        call(1, "T-W1", [try_(1, "일시"), try_(2, "일시"), try_(3)]),
        call(2, "T-W1", [try_(1)]),
        call(3, "T-W1", [try_(1, "일시"), try_(2, "입력")]),
        call(5, "T-V1", [try_(1)]),
    ]
    return RunRecords(executions=executions, calls=calls,
                      events=[event("재작성실패"), event("재작성시작"), event("재작성실패")],
                      feedback=[feedback()], comparisons=[comparison("c1", "후"), comparison("c1", "전"),
                                                          comparison("c2", "후")],
                      pointer_events=[pointer_event()])


POINTERS = {"docScore": 1, "artifactScore": 1, "scoreReport.overall": 1, "planDoc": 3}


def row_of(**over) -> LogStatsRow:
    kw = dict(pointers=POINTERS, reason="12개월", part=2)
    kw.update(over)
    run = kw.pop("run", make_run())
    records = kw.pop("records", full_records())
    row = run_stats_row(run, records, **kw)
    assert row is not None
    return row


# ── 줄 칸 ─────────────────────────────────────────────
def test_row_columns():
    row = row_of(category_fallback="원페이지")
    assert (row.kind, row.reason, row.part, row.count, row.status, row.result_code) == (
        "실행", "12개월", 2, 1, "완료", None)
    assert row.month == "2026-02"                       # 2026-01-31 16:00 UTC = 한국 2026-02-01
    assert row.category == "원페이지"
    assert row.created_at is None                       # 저장소가 쓴다


def test_month_is_kst():
    assert row_of(run=make_run(created_at=datetime(2026, 1, 31, 14, 59, tzinfo=UTC))).month == "2026-01"
    assert row_of(run=make_run(created_at=datetime(2026, 1, 31, 15, 0, tzinfo=UTC))).month == "2026-02"


def test_category_precedence():
    assert row_of(run=make_run(category="웹개발"), category_fallback="원페이지").category == "웹개발"
    assert row_of(run=make_run(category=None), category_fallback="AI_API").category == "AI_API"
    assert row_of(run=make_run(category=None)).category is None
    # 카테고리 값이 아닌 글은 싣지 않는다
    assert row_of(run=make_run(category=None), category_fallback=f"{M} 자유 글").category is None


def test_reason_and_part_checked():
    with pytest.raises(ValueError):
        row_of(reason=f"{M}")
    with pytest.raises(ValueError):
        row_of(part=0)


def test_no_records_no_row():
    assert run_stats_row(make_run(), RunRecords(), pointers=POINTERS, reason="탈퇴", part=1) is None
    # 여섯 기록 중 어느 하나라도 있으면 줄을 쓴다
    for name, value in (("executions", full_records().executions[:1]), ("calls", full_records().calls[:1]),
                        ("events", [event("재작성시작")]), ("feedback", [feedback()]),
                        ("comparisons", [comparison("c1", "후")]), ("pointer_events", [pointer_event()])):
        row = run_stats_row(make_run(), RunRecords(**{name: value}), pointers={}, reason="탈퇴", part=1)
        assert row is not None and row.reason == "탈퇴", name
        assert set(row.data) == TOP_KEYS


# ── data_json 키 (4.2) ───────────────────────────────
def test_data_keys_exact():
    data = row_of().data
    assert set(data) == TOP_KEYS
    assert set(data["scores"]) == SCORE_KEYS
    for entries in data["scores"].values():
        for e in entries:
            assert set(e) == {"score", "afterRework"}
    assert set(data["finalScores"]) == {"doc", "artifact", "total"}
    assert set(data["rework"]) == {"cycles", "kept", "failed"}
    assert set(data["run"]) == {"retryCount", "resumeCount", "lastErrorKind"}
    for task in data["tasks"].values():
        assert set(task) == TASK_KEYS
        assert set(task["tokens"]) == {"input", "cachedInput", "output", "reasoning"}
        assert set(task["runs"]) <= {"첫실행", "재작성", "재수행"}
        assert set(task["status"]) <= {"성공", "실패", "재개대기", "생략", "실행"}
        assert set(task["errorKinds"]) <= {"일시", "입력", "운영"}
        assert set(task["callErrorKinds"]) <= {"일시", "입력", "운영"}
    json.dumps(data)                                    # JSON으로 저장된다


def test_scores_in_time_order_with_rework_flag():
    scores = row_of().data["scores"]
    # 실패한 T-V1(99점)은 채점이 아니다. 되돌린 재작성 채점(60점)도 넣는다
    assert scores["docScore"] == [{"score": 52.0, "afterRework": False}, {"score": 60.0, "afterRework": True}]
    assert scores["codeCheck"] == [{"score": 30.0, "afterRework": False}]
    assert scores["featureMatch"] == [{"score": 25.0, "afterRework": False}]
    assert scores["artifactScore"] == [{"score": 55.0, "afterRework": False}]
    assert scores["overall"] == [{"score": 81.0, "afterRework": True}]


def test_empty_layers_are_empty_lists():
    only_w1 = RunRecords(executions=full_records().executions[1:2])
    data = run_stats_row(make_run(), only_w1, pointers={}, reason="12개월", part=1).data
    assert data["scores"] == {k: [] for k in SCORE_KEYS}


def test_final_scores_follow_pointers():
    assert row_of().data["finalScores"] == {"doc": 52.0, "artifact": 55.0, "total": 81.0}   # docScore는 되돌림
    assert row_of(pointers={"docScore": 2}).data["finalScores"] == {"doc": 60.0, "artifact": None, "total": None}
    assert row_of(pointers={}).data["finalScores"] == {"doc": None, "artifact": None, "total": None}   # 완전 삭제 뒤


def test_task_counts():
    tasks = row_of().data["tasks"]
    assert set(tasks) == {"T-W1", "T-V1", "T-V2", "G-02b", "M-1"}   # 실행 기록이 있는 Task만 (합치기 포함)
    w1 = tasks["T-W1"]
    assert {k: v for k, v in w1["runs"].items() if v} == {"첫실행": 1, "재수행": 2, "재작성": 1}
    assert {k: v for k, v in w1["status"].items() if v} == {"성공": 2, "실패": 1, "재개대기": 1}
    assert w1["resumes"] == 3
    assert w1["retries"] == (3 + 1 + 2) - 3                        # 시도 수 − 호출 수
    assert {k: v for k, v in w1["errorKinds"].items() if v} == {"일시": 1}
    assert {k: v for k, v in w1["callErrorKinds"].items() if v} == {"일시": 3, "입력": 1}
    assert w1["tokens"] == {"input": 1200, "cachedInput": 50, "output": 800, "reasoning": 100}
    v1 = tasks["T-V1"]
    assert {k: v for k, v in v1["status"].items() if v} == {"성공": 2, "실패": 1}
    assert {k: v for k, v in v1["errorKinds"].items() if v} == {"운영": 1}
    assert v1["retries"] == 0
    assert v1["tokens"] == {"input": 0, "cachedInput": 0, "output": 0, "reasoning": 0}   # 없는 값은 0
    assert tasks["T-V2"]["retries"] == 0 and not any(tasks["T-V2"]["callErrorKinds"].values())


def test_rework_and_run_blocks():
    data = row_of().data
    assert data["rework"]["cycles"] == 2
    assert {k: v for k, v in data["rework"]["kept"].items() if v} == {"전": 1, "후": 2}
    assert data["rework"]["failed"] == 2
    assert data["run"] == {"retryCount": 2, "resumeCount": 1, "lastErrorKind": "일시"}
    assert data["step"] == "결과물"


# ── 식별자 · 자유 글 없음 ─────────────────────────────
def test_no_identifiers_or_free_text():
    row = row_of(category_fallback=f"{M}")
    text = repr(row) + json.dumps(row.data, ensure_ascii=False)
    assert M not in text
    rows = start_request_rows(requests(), "탈퇴")
    text = repr(rows) + "".join(json.dumps(r.data, ensure_ascii=False) for r in rows)
    assert M not in text


# ── 시작 요청 줄 ──────────────────────────────────────
def request(n: int, status: str, created: datetime, code: str | None = None) -> StartRequest:
    return StartRequest(request_id=f"{M}-req-{n}", project_id=f"{M}-proj-{n}", account_id=f"{M}-acc",
                        status=status, form={"ideaText": f"{M} 아이디어"}, result_code=code,
                        result_message=f"{M} 안내" if code else None, result_detail={"x": f"{M}"},
                        notices=[Notice(code="E-C2-EMBED", message=f"{M}", at=created)], run_id=f"{M}-run-{n}",
                        lease_owner=f"{M}-owner", created_at=created, updated_at=created + timedelta(days=40),
                        finished_at=created)


def requests() -> list[StartRequest]:
    jan = datetime(2026, 1, 10, tzinfo=UTC)
    return [
        request(1, "완료", jan),
        request(2, "완료", jan + timedelta(days=1)),
        request(3, "실패", jan, "E-C2-NOMATCH"),
        request(4, "실패", jan, "E-C2-NOMATCH"),
        request(5, "실패", jan, "E-C1-TIMEOUT"),
        request(6, "취소", datetime(2026, 1, 31, 15, 30, tzinfo=UTC)),   # 한국 2월
        request(7, "완료", datetime(2026, 2, 3, tzinfo=UTC)),
        request(8, "실패", jan, f"{M}-code"),                             # 모르는 코드는 싣지 않는다
    ]


def test_start_request_grouping():
    rows = start_request_rows(requests(), "12개월")
    got = {(r.month, r.status, r.result_code): r.count for r in rows}
    assert got == {
        ("2026-01", "완료", None): 2,
        ("2026-01", "실패", "E-C2-NOMATCH"): 2,
        ("2026-01", "실패", "E-C1-TIMEOUT"): 1,
        ("2026-01", "실패", None): 1,
        ("2026-02", "취소", None): 1,
        ("2026-02", "완료", None): 1,
    }
    for r in rows:
        assert (r.kind, r.reason, r.part, r.category, r.data, r.created_at) == ("시작요청", "12개월", 1, None, None,
                                                                                 None)
    assert sum(r.count for r in rows) == len(requests())
    assert start_request_rows([], "탈퇴") == []


def test_start_request_checks():
    with pytest.raises(ValueError):
        start_request_rows([request(1, "대기", T0)], "12개월")       # 끝나지 않은 요청
    with pytest.raises(ValueError):
        start_request_rows(requests(), "기타")


# ── 실제 흐름 기록으로 ────────────────────────────────
def records_of(store, run_id: str) -> RunRecords:
    return RunRecords(executions=store.executions(run_id), calls=store.call_logs(run_id), events=store.events(run_id),
                      feedback=store.feedback(run_id), comparisons=store.comparisons(run_id),
                      pointer_events=store.pointer_events(run_id))


def test_from_real_flow_and_store_round_trip(clock):
    from conftest import make_app
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app, "acc-1")
    run = app.store.load_run(rid)
    app.orchestrator.request_rework_for_project(run.project_id, "문제인식")
    clock.advance(seconds=3)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    records = records_of(app.store, rid)
    pointers = app.store.get_pointers(rid)
    category = app.store.get_artifact(rid, "category", pointers["category"]).value
    row = run_stats_row(run, records, pointers=pointers, reason="12개월", part=run.stats_parts + 1,
                        category_fallback=category)
    assert row is not None and row.category == category and row.part == 1
    data = row.data
    assert set(data["tasks"]) == {r.task_id for r in records.executions}
    assert [e["afterRework"] for e in data["scores"]["docScore"]] == [False, True]
    assert data["rework"]["cycles"] == len({c.cycle_id for c in records.comparisons}) >= 1
    # 관리자 실행 건 목록의 현재 점수와 같은 계산
    admin = next(a for a in admin_runs(app.orchestrator, limit=None) if a.run_id == rid)
    assert data["finalScores"] == {"doc": admin.doc_score, "artifact": admin.artifact_score,
                                   "total": admin.total_score}
    text = repr(row) + json.dumps(data, ensure_ascii=False)
    for ident in (rid, run.project_id, run.account_id, run.announcement_id,
                  *(r.execution_id for r in records.executions), *(c.call_id for c in records.calls)):
        assert ident and ident not in text
    # 저장소가 그대로 저장한다
    assert app.store.acquire(rid, "retire", 60)
    app.store.retire_run(rid, "retire", stats=row, bump_parts=True)
    app.store.release(rid, "retire")
    saved = app.store.log_stats("실행")
    assert len(saved) == 1 and saved[0].data == data and saved[0].month == row.month
    assert app.store.executions(rid) == [] and app.store.load_run(rid).stats_parts == 1
