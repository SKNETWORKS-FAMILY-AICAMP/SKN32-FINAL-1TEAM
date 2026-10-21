"""관리자 실행 건 목록(admin_runs) · 운영 요약(admin_summary)을 한 시점 읽기 구간으로 — 성능 측정 C 후속 (2026-10-20).

- 값이 같음(흐름 — 메모리 · SQLite): 테스트 안의 '예전 식'(실행 건마다 get_pointers · executions, 운영 요약은 실행 기록 전부를
  list_executions로 읽어 범위 실행 건으로 거름 — 바꾸기 전 reads.py 코드 그대로)을 참조 구현으로 두고 두 조회가 그 값과 같은지
  본다. 재작성 · 되돌리기 · 재수행 · 배점이 다른 실행 건 · 실행 기록 없는 실행 건 · 범위 밖 실행 건 · 12개월 처리 뒤 · 완전 삭제
  뒤 · 탈퇴 뒤.
- 같은 순간(메모리 · SQLite · MySQL, TIMING): 구간의 창구 읽기 뒤 다른 스레드가 새 채점 저장 · 되돌리기 · 완전 삭제 · 탈퇴 ·
  12개월 처리 중 하나를 한다. 결과는 쓰기 전 순간의 참조값이고, 다음 호출은 쓴 뒤 값이다. 메모리 · SQLite는 쓰기가 구간 끝을
  기다리고 MySQL은 기다리지 않는다. 예전처럼 나눠 읽었다면 섞인 값이 나왔을 경우(실행 기록 → 포인터 순 새 채점 = 빈칸,
  실행 건 목록 → 포인터 순 새 채점 · 완전 삭제)는 나눠 읽은 값을 함께 만들어 섞였음을 확인한다. 포인터 → 실행 기록 순 완전
  삭제(지운 점수)도 넣는다.
- 문장 수 · 연결 수(SQLite · MySQL): 실행 건 2개 · 5개에서 같은 SELECT 수, 연결 꺼내기 1번, 실행 기록 전부(record_json)를
  읽는 문장이 없다. admin_summary는 범위판이라 PROJECT_CHUNK를 작게 바꿔도 같은 수다.
- 시계: 두 조회 모두 호출 한 번에 시계를 한 번 부른다(관리자 범위의 기준 시각).

MySQL 테스트 DB는 MySQL 테스트 전체가 함께 쓴다 — 범위로 세는 admin_summary는 다른 테스트의 행도 세므로 같은 DB 전체에서 참조
구현으로 구한 값과 비교하고, admin_runs는 범위 안 실행 건이 모두 들어가는 페이지(PAGE)로 비교한다. 워커가 가져갈 일('실행'
실행 건 · 대기 시작 요청)은 남기지 않는다.
"""
from __future__ import annotations

import typing
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from conftest import TIMING, Backend, Clock, make_app, pre_input, project_for, start_and_select, to_screen6, to_screen9
from flow_helpers import pid, rework, run_review
from store_helpers import count_sql, new_run, sql_backend, uid, write_during_snapshot  # noqa: F401 — sql_backend는 pytest 장치

from sbrain.agents.stubs import StubScenario
from sbrain.flow.log_stats import CURRENT_SCORE_KEYS, SCORE_LAYERS, current_scores, layer_score, scored_task_ids
from sbrain.flow.reads import AdminRun, AdminSummary, LayerChange, ScoreBucket, ScoreEntry, TriggerStat
from sbrain.flow.retention import _retire_one, retention_cutoff, run_retention, start_retention
from sbrain.flow.score_scale import score_maxes
from sbrain.models import Run
from sbrain.models.base import RunProgress
from sbrain.models.clock import UTC_MIN
from sbrain.orchestrator.settings import ScoringSettings, Settings
from sbrain.orchestrator.store import ArtifactVersion, CommitBatch, ExecutionFilter, RunFilter
from sbrain.orchestrator.tools import TokenUsage
from sbrain.orchestrator.trace import ExecutionRecord, PointerEvent
from sbrain.store_sql import store as store_sql_store

PAGE = 1000   # 범위 안 실행 건이 모두 들어가는 페이지 (MySQL은 다른 테스트의 실행 건도 범위 안에 있다)


# ── 예전 식 (참조 구현) — 바꾸기 전 reads.py 코드 그대로 ─────────────────
# 총점 구간만 지금 경계(하한 포함 · 상한 미포함, 100점은 최상위 구간 — 2026-10-21 팀원 SB-414)로 맞춘다.
REF_BUCKETS = (("90~100점", 90, 100), ("80~89점", 80, 90), ("70~79점", 70, 80), ("60~69점", 60, 70),
               ("60점 미만", 0, 60))
REF_TRIGGERS = ("첫실행", "재작성", "재수행")


def _ref_avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _ref_rate(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def _ref_score_events(records: list[ExecutionRecord], maxes) -> dict[str, list[ScoreEntry]]:
    events: dict[str, list[ScoreEntry]] = {layer: [] for layer, _, _ in SCORE_LAYERS}
    for r in records:
        if r.status != "성공":
            continue
        for layer, task, _field in SCORE_LAYERS:
            score = layer_score(layer, r.output_meta, maxes) if r.task_id == task else None
            if score is not None:
                events[layer].append(ScoreEntry(scored_at=r.ended_at, score=score, after_rework=r.trigger == "재작성",
                                                execution_id=r.execution_id))
    for entries in events.values():
        entries.sort(key=lambda e: e.scored_at or UTC_MIN)
    return events


@dataclass
class RunsMoment:
    """admin_runs 예전 식이 읽은 것 — 실행 건 목록과 실행 건마다의 포인터 · 실행 기록 전부."""
    runs: list[Run]
    pointers: dict[str, dict[str, int]]
    records: dict[str, list[ExecutionRecord]]


def runs_moment(orch, *, progress=None, step=None, limit=50, offset=0) -> RunsMoment:
    runs = orch.store.query_runs(RunFilter(progress=progress, step=step, limit=limit, offset=offset,
                                           updated_since=retention_cutoff(orch.now())))
    return RunsMoment(runs, *runs_data(orch.store, runs))


def runs_data(store, runs: list[Run]) -> tuple[dict, dict]:
    """실행 건마다 get_pointers · executions (예전 식의 읽기)."""
    return ({r.run_id: store.get_pointers(r.run_id) for r in runs},
            {r.run_id: store.executions(r.run_id) for r in runs})


def runs_rows(orch, m: RunsMoment) -> list[AdminRun]:
    out = []
    for run in m.runs:
        records = m.records[run.run_id]
        maxes = score_maxes(run.settings_snapshot)
        scores = current_scores(m.pointers[run.run_id], records, maxes=maxes)
        task = run.queue[0] if run.queue else run.current_task
        agent = orch.engine.registry.get(task).agent if task and orch.engine.registry.has(task) else None
        out.append(AdminRun(
            project_id=run.project_id, run_id=run.run_id, step=run.state.step, progress=run.state.progress,
            current_task=task, agent=agent, attempt=records[-1].attempt if records else None,
            updated_at=run.updated_at, doc_score=scores["doc"], artifact_score=scores["artifact"],
            total_score=scores["total"], resume_count=run.resume_count, last_error_kind=run.last_error_kind,
            failure_reason=run.failure_reason, doc_max=maxes.doc, artifact_max=maxes.artifact))
    return out


def ref_admin_runs(orch, **kw) -> list[AdminRun]:
    return runs_rows(orch, runs_moment(orch, **kw))


@dataclass
class SummaryMoment:
    """admin_summary 예전 식이 읽은 것 — 범위 안 실행 건, 실행 기록 전부를 범위 실행 건으로 거른 것, 실행 건마다의 포인터."""
    runs: list[Run]
    by_run: dict[str, list[ExecutionRecord]]
    pointers: dict[str, dict[str, int]]


def summary_moment(orch) -> SummaryMoment:
    runs = orch.store.query_runs(RunFilter(limit=None, updated_since=retention_cutoff(orch.now())))
    in_scope = {run.run_id for run in runs}
    by_run: dict[str, list[ExecutionRecord]] = defaultdict(list)
    for row in orch.store.list_executions(ExecutionFilter(limit=None, order="asc")):
        if row.record.run_id in in_scope:
            by_run[row.record.run_id].append(row.record)
    return SummaryMoment(runs, by_run, {run.run_id: orch.store.get_pointers(run.run_id) for run in runs})


def summary_of(m: SummaryMoment, threshold: float) -> AdminSummary:
    status: Counter[str] = Counter()
    docs: list[float] = []
    totals: list[float] = []
    firsts: dict[str, list[float]] = defaultdict(list)
    afters: dict[str, list[float]] = defaultdict(list)
    reworked = 0
    for run in m.runs:
        status[run.state.progress] += 1
        records = m.by_run.get(run.run_id, [])
        maxes = score_maxes(run.settings_snapshot)
        scores = current_scores(m.pointers[run.run_id], records, maxes=maxes)
        if scores["doc"] is not None:
            docs.append(scores["doc"])
        if scores["total"] is not None:
            totals.append(scores["total"])
        if any(r.trigger == "재작성" for r in records):
            reworked += 1
        for layer, entries in _ref_score_events(records, maxes).items():
            after = [e for e in entries if e.after_rework]
            if entries and after and after[-1].execution_id != entries[0].execution_id:
                firsts[layer].append(entries[0].score)
                afters[layer].append(after[-1].score)
    passed = sum(1 for t in totals if t >= threshold)
    changes = []
    for layer, _, _ in SCORE_LAYERS:
        first_avg, after_avg = _ref_avg(firsts[layer]), _ref_avg(afters[layer])
        delta = round(after_avg - first_avg, 1) if first_avg is not None and after_avg is not None else None
        changes.append(LayerChange(layer=layer, first_avg=first_avg, after_avg=after_avg, delta=delta,
                                   count=len(firsts[layer])))
    every = [r for records in m.by_run.values() for r in records]

    def tokens(r: ExecutionRecord) -> int:
        return (r.input_tokens or 0) + (r.output_tokens or 0)
    triggers = []
    for trig in REF_TRIGGERS:
        mine = [r for r in every if r.trigger == trig]
        triggers.append(TriggerStat(trigger=trig, count=len(mine),
                                    avg_tokens=_ref_avg([float(tokens(r)) for r in mine])))
    with_exec = sum(1 for run in m.runs if m.by_run.get(run.run_id))
    return AdminSummary(
        status_counts={p: status.get(p, 0) for p in typing.get_args(RunProgress)},
        doc_avg=_ref_avg(docs), doc_count=len(docs), total_avg=_ref_avg(totals), total_count=len(totals),
        pass_count=passed, pass_rate=_ref_rate(passed, len(totals)), pass_threshold=threshold,
        reworked_runs=reworked, runs_with_executions=with_exec, rework_rate=_ref_rate(reworked, with_exec),
        score_buckets=[ScoreBucket(label=label, count=sum(1 for t in totals if lo <= t < hi or (hi == 100 and t == 100)))
                       for label, lo, hi in REF_BUCKETS],
        layer_changes=changes, triggers=triggers, total_tokens=sum(tokens(r) for r in every),
        total_image_tokens=sum((r.image_input_tokens or 0) + (r.image_output_tokens or 0) for r in every))


def ref_admin_summary(orch) -> AdminSummary:
    m = summary_moment(orch)
    return summary_of(m, orch.settings.current().scoring.threshold)


# ── 채점 Task 목록 ────────────────────────────────────────
def test_scored_task_ids_from_registry_outputs_and_score_layers(clock):
    """현재 점수 키를 출력하는 Task(등록부 outputs 값)와 층별 채점 Task를 합친 것 — 지금은 T-V1 · T-V2 · G-02b."""
    app = make_app(clock)
    specs = app.registry.specs()
    keys = {key for _, key in CURRENT_SCORE_KEYS}
    want = {s.task_id for s in specs if keys & set(s.outputs.values())} | {task for _, task, _ in SCORE_LAYERS}
    got = scored_task_ids(specs)
    assert set(got) == want and len(got) == len(want)
    assert set(got) == {"T-V1", "T-V2", "G-02b"}


# ── 흐름: 예전 식과 같은 값 (메모리 · SQLite) ─────────────────────
RUN_QUERIES = ({}, {"progress": "사용자대기"}, {"progress": "완료"}, {"step": "문서평가"}, {"limit": 2, "offset": 1},
               {"limit": 3, "offset": 2}, {"limit": 5, "offset": 50})


def same_as_reference(app) -> AdminSummary:
    orch = app.orchestrator
    for kw in RUN_QUERIES:
        assert orch.admin_runs(**kw) == ref_admin_runs(orch, **kw), kw
    summary = orch.admin_summary()
    assert summary == ref_admin_summary(orch)
    return summary


def test_admin_reads_match_old_reads_through_flow(clock):
    app = make_app(clock, StubScenario(doc_scores=[58.0, 52.0, 60.0, 45.0, 70.0, 50.0, 64.0],
                                       art_scores=[(15.0, 11.0), (12.0, 9.0)], check_fail_times={"T-B1": 1}))
    app.llm.usage["T-C1"] = TokenUsage(input_tokens=100, cached_input_tokens=40, output_tokens=20, reasoning_tokens=5)
    orch = app.orchestrator
    # 범위 밖이 될 실행 건 — 문서 평가 대기(58) · 공고선택 대기
    old_doc = to_screen6(app, "acc-old-1")
    old_wait = orch.start_run("acc-old-2", pre_input(), project_id=project_for(app)).run_id
    same_as_reference(app)
    clock.advance(days=400)
    # A: 재작성(52 → 60, 남긴 쪽 후) · 실행 파일 검사 불통과 재수행 · 완료
    a = to_screen6(app, "acc-a")
    rework(app, clock, a, "문제인식")
    orch.decide(a, 6, "진행")
    orch.advance(a)
    orch.decide(a, 8, "진행")
    run_review(app, a)
    b = to_screen6(app, "acc-b")                                                   # 45
    e = to_screen6(app, "acc-e")                                                   # 70 → 재작성 50 → 되돌리기
    rework(app, clock, e, "문제인식")
    app.settings.update(Settings(scoring=ScoringSettings(code_check_max=20, feature_match_max=5)))
    f = to_screen9(app, "acc-f")                                                   # 배점이 다른 실행 건 (C 20 · P 5)
    app.settings.update(Settings())
    c = start_and_select(app, "acc-c")
    app.llm.plan("T-S1", ["auth"])                                                 # 401 — 실패 실행 건
    orch.start_writing(c)
    orch.advance(c)
    app.llm.plan("T-S1", [])
    d = orch.start_run("acc-d", pre_input(), project_id=project_for(app)).run_id   # 공고선택 대기 — 점수 없음
    bare = new_run(clock, uid(), progress="완료")                                  # 실행 기록 · 산출물이 없는 실행 건
    assert app.store.create_run(bare, CommitBatch())
    assert [app.store.load_run(r).state.progress for r in (a, b, e, f, c, d)] == [
        "완료", "사용자대기", "사용자대기", "사용자대기", "실패", "사용자대기"]
    assert app.store.load_run(a).last_rework.kept == "후" and app.store.load_run(e).last_rework.kept == "전"
    assert any(r.trigger == "재수행" for r in app.store.executions(a))

    s = same_as_reference(app)                                                    # 범위 밖 실행 건 둘
    rows = {r.run_id: r for r in orch.admin_runs(limit=PAGE)}
    assert old_doc not in rows and old_wait not in rows and bare.run_id in rows
    assert (rows[f].artifact_max, rows[a].artifact_max) == (25.0, 30.0) and rows[f].artifact_score is not None
    assert rows[e].doc_score == 70.0 and rows[bare.run_id].attempt is None
    assert s.reworked_runs == 2 and s.triggers[2].count > 0 and s.layer_changes[0].count == 2

    assert start_retention(app.store, "w", 60)                                    # 12개월 처리 — 범위 밖 둘의 기록을 옮김
    assert run_retention(app.store, "w", now=clock(), lease_sec=60).summary.runs == 2
    assert app.store.executions(old_doc) == []
    same_as_reference(app)

    orch.delete_project_data(pid(app, b))                                         # 완전 삭제 — 포인터 · 버전만 지움
    assert app.store.get_pointers(b) == {} and app.store.executions(b)
    same_as_reference(app)

    orch.select_announcement(old_wait, "A01")                                     # 기록을 옮긴 실행 건이 범위 안으로
    assert app.store.executions(old_wait) == [] and old_wait in {r.run_id for r in orch.admin_runs(limit=PAGE)}
    same_as_reference(app)
    orch.advance(old_wait)
    same_as_reference(app)

    orch.delete_account_data("acc-e")                                              # 탈퇴 — 실행 건 줄 · 기록을 지움
    assert e not in {r.run_id for r in orch.admin_runs(limit=PAGE)}
    same_as_reference(app)
    app.settings.update(Settings(scoring=ScoringSettings(threshold=50)))          # 기준 점수는 지금 설정
    assert same_as_reference(app).pass_threshold == 50.0


def test_admin_reads_call_clock_once(clock):
    """관리자 범위의 기준 시각 하나 — 시계 호출 순서 · 횟수는 바꾸기 전과 같다 (1밀리초씩 가는 시계로 센다)."""
    app = make_app(clock)
    to_screen6(app, "acc-1")
    for read in (app.orchestrator.admin_runs, app.orchestrator.admin_summary,
                 lambda: ref_admin_runs(app.orchestrator), lambda: ref_admin_summary(app.orchestrator)):
        before = clock.t
        read()
        assert clock.t - before == timedelta(milliseconds=1)


# ── 같은 순간: 구간 안 창구 읽기 뒤 다른 스레드의 쓰기 (메모리 · SQLite · MySQL) ──────────
OWNER = "snapshot-test-writer"


def commit_as_worker(store, rid: str, batch: CommitBatch) -> None:
    """워커처럼 점유를 잡고 저장 한 번 · 점유를 푼다."""
    assert store.acquire(rid, OWNER, 60)
    try:
        store.commit(rid, OWNER, batch)
    finally:
        store.release(rid, OWNER)


def new_score_batch(app, clock: Clock, rid: str, score: float) -> CommitBatch:
    """새 채점 저장 — 워커가 T-V1 단계를 저장하듯 실행 기록 · 산출물 버전 · 포인터 · 실행 건 줄을 한 번에. 값은 미리 만든다
    (쓰기 스레드가 시계 · 저장소를 미리 읽지 않게)."""
    store = app.store
    run = store.load_run(rid)
    last = [r for r in store.executions(rid) if r.task_id == "T-V1" and r.status == "성공"][-1]
    value = store.get_artifact(rid, "docScore", store.get_pointers(rid)["docScore"]).value
    version = store.get_latest_versions(rid)["docScore"] + 1
    now = clock()
    ref = f"docScore@{version}"
    rec = last.model_copy(update=dict(
        execution_id=uid(), attempt=last.attempt + 1, trigger="재작성", outputs=[ref], result_ref=ref,
        output_meta=last.output_meta.model_copy(update={"score": score}), created_at=now, started_at=now, ended_at=now))
    return CommitBatch(run=run.model_copy(update={"updated_at": now}),
                       versions=[ArtifactVersion(rid, "docScore", version, value, rec.execution_id, now)],
                       pointers={"docScore": version}, executions={rec.execution_id: rec})


def pointer_back_batch(app, clock: Clock, rid: str, to_version: int) -> CommitBatch:
    """되돌리기 — 문서층 점수 포인터를 옛 버전으로 옮긴다(포인터 이동 기록과 함께)."""
    store = app.store
    run = store.load_run(rid)
    now = clock()
    current = store.get_pointers(rid)["docScore"]
    return CommitBatch(run=run.model_copy(update={"updated_at": now}), pointers={"docScore": to_version},
                       pointer_events=[PointerEvent(run_id=rid, key="docScore", from_version=current,
                                                    to_version=to_version, reason="되돌리기", at=now)])


def prepared_write(app, clock: Clock, kind: str, target: str, account: str, old: str | None):
    """쓰기 함수 — 다른 스레드에서 부른다. 저장할 값은 여기서(구간 밖, 같은 스레드) 미리 만든다."""
    store, orch = app.store, app.orchestrator
    if kind == "new_score":
        batch = new_score_batch(app, clock, target, 60.0)
        return lambda: commit_as_worker(store, target, batch)
    if kind == "rollback":
        commit_as_worker(store, target, new_score_batch(app, clock, target, 60.0))   # 52 → 60을 먼저 저장해 둔다
        batch = pointer_back_batch(app, clock, target, 1)
        return lambda: commit_as_worker(store, target, batch)
    if kind == "delete":
        project = pid(app, target)
        return lambda: orch.delete_project_data(project)
    if kind == "withdraw":
        return lambda: orch.delete_account_data(account)
    assert kind == "retention" and old is not None
    cutoff = retention_cutoff(clock.t)

    def retire() -> Any:
        # 12개월 처리가 실행 건마다 하는 일 그대로(점유 · 다시 확인 · 통계 줄 · 기록 지우기 한 트랜잭션) — 작업 전체(run_retention)는
        # MySQL 테스트 DB의 다른 테스트 실행 건까지 옮기므로 이 실행 건 하나만 한다
        try:
            return _retire_one(store, old, OWNER, 60, cutoff)
        finally:
            store.release(old, OWNER)
    return retire


FIRST_READ = "query_runs"
CASES = [
    # (함수, 쓰기, 쓰기를 끼울 창구 읽기 — None은 첫 읽기, 예전처럼 나눠 읽었다면 섞인 값이 나오는지)
    pytest.param("runs", "new_score", None, True, id="runs-new_score"),
    pytest.param("summary", "new_score", "scored_executions_since", True, id="summary-new_score-before_pointers"),
    pytest.param("runs", "rollback", "pointers_for_runs", False, id="runs-rollback"),
    pytest.param("summary", "rollback", None, False, id="summary-rollback"),
    pytest.param("runs", "delete", "pointers_for_runs", False, id="runs-delete-after_pointers"),
    pytest.param("runs", "delete", None, True, id="runs-delete"),
    pytest.param("summary", "delete", "execution_totals_since", False, id="summary-delete"),
    pytest.param("runs", "withdraw", "scored_executions", False, id="runs-withdraw"),
    pytest.param("summary", "withdraw", None, False, id="summary-withdraw"),
    pytest.param("runs", "retention", None, False, id="runs-retention"),
    pytest.param("summary", "retention", "scored_executions_since", False, id="summary-retention"),
]


@TIMING
@pytest.mark.parametrize("fn, kind, after, mixed", CASES)
def test_write_during_admin_read_gives_one_moment(any_backend: Backend, fn, kind, after, mixed):
    clock = Clock(backend=any_backend)
    app = make_app(clock, StubScenario(doc_scores=[52.0]))
    orch = app.orchestrator
    old = None
    if kind == "retention":
        old = to_screen6(app, uid())                                               # 12개월 처리 대상이 될 실행 건
        clock.advance(days=400)
    account = uid()
    target = to_screen6(app, account)                                              # 문서 평가 대기 · 52
    to_screen6(app, uid())
    orch.start_run(uid(), pre_input(), project_id=project_for(app))                # 공고선택 대기 — 점수 없음
    write = prepared_write(app, clock, kind, target, account, old)

    if fn == "runs":
        def read() -> Any:
            return orch.admin_runs(limit=PAGE)

        def moment() -> Any:
            return runs_moment(orch, limit=PAGE)

        def value(m) -> Any:
            return runs_rows(orch, m)
    else:
        def read() -> Any:
            return orch.admin_summary()

        def moment() -> Any:
            return summary_moment(orch)

        def value(m) -> Any:
            return summary_of(m, orch.settings.current().scoring.threshold)
    first = moment()
    before = value(first)
    with write_during_snapshot(app.store, write, after=after) as outcome:
        got = read()
    assert outcome.error is None, outcome.error
    assert outcome.started and outcome.finished and outcome.after == (after or FIRST_READ)
    assert outcome.finished_in_snapshot is (any_backend.kind == "mysql")          # 메모리 · SQLite는 쓰기가 구간 끝을 기다림
    later = moment()
    behind = value(later)
    assert got == before                                                           # 쓰기 전 한 순간
    assert read() == behind                                                        # 다음 호출은 쓴 뒤 값
    if kind == "retention":
        assert before == behind                                                    # 12개월 처리 대상은 관리자 범위 밖
        assert app.store.executions(old) == []
    elif fn == "runs":
        assert before != behind
    else:
        # 쓰기가 값을 바꿨는지는 반올림한 요약(공유 MySQL DB 전체 평균 — 실행 건이 많으면 한 실행 건의 변화가 반올림에
        # 묻힌다)이 아니라 그 실행 건의 원자료로 본다 — 실행 건 줄 · 포인터 · 실행 기록 중 하나는 달라야 한다
        def target_data(m: SummaryMoment) -> Any:
            run = next((r for r in m.runs if r.run_id == target), None)
            return run, m.pointers.get(target), m.by_run.get(target, [])
        assert target_data(first) != target_data(later)
    if mixed:                                                                      # 예전처럼 나눠 읽었다면 — 섞인 값
        if fn == "runs":                                                           # 실행 건 목록은 앞, 포인터 · 기록은 뒤
            split = value(RunsMoment(first.runs, *runs_data(app.store, first.runs)))
        else:                                                                      # 실행 건 · 기록은 앞, 포인터는 뒤
            split = value(SummaryMoment(first.runs, first.by_run,
                                        {r.run_id: app.store.get_pointers(r.run_id) for r in first.runs}))
        assert split != before and split != behind
        if fn == "summary":
            assert split.doc_count == before.doc_count - 1                         # 새 채점의 점수가 빈칸
        else:
            row = next(r for r in split if r.run_id == target)
            old_row = next(r for r in before if r.run_id == target)
            assert (row.progress, row.updated_at) == (old_row.progress, old_row.updated_at)   # 쓰기 전 실행 건 줄에
            assert row.doc_score != old_row.doc_score                                          # 쓰기 뒤 점수


# ── 문장 수 · 연결 수 (SQLite · MySQL — 장치 sql_backend는 store_helpers) ──────
# admin_runs 문장 수 시험의 시작 시각 — MySQL 테스트 DB의 다른 실행 건보다 뒤라 페이지가 이 시험의 실행 건이다(끝에 지운다)
LATE = datetime(2030, 1, 6, 9, 0, 0, tzinfo=timezone.utc)


def sql_app(backend: Backend, start: datetime | None = None):
    clock = Clock(start, backend=backend) if start is not None else Clock(backend=backend)
    return make_app(clock, StubScenario(doc_scores=[52.0]))


def scored_runs(app, n: int) -> list[str]:
    """같은 상태 구성의 실행 건 n개 — 문서 평가 대기(포인터 · 채점 기록 있음), 계정은 실행 건마다 새로."""
    return [to_screen6(app, uid()) for _ in range(n)]


def no_whole_record_reads(counts) -> None:
    """실행 기록 JSON을 읽는 문장은 채점 Task로 거른 것뿐 — 실행 기록 전부를 읽지 않는다."""
    reads = [s for s in counts.statements if "record_json" in s]
    assert reads and all("task_id IN" in s and "status" in s for s in reads), reads


def test_admin_runs_select_count_does_not_grow_with_runs(sql_backend, monkeypatch):
    app = sql_app(sql_backend, LATE)
    orch = app.orchestrator
    rids: list[str] = []
    try:
        rids += scored_runs(app, 2)
        orch.admin_runs(limit=2)                                                   # 데우기
        with count_sql(app.store.engine) as two:
            rows2 = orch.admin_runs(limit=2)
        rids += scored_runs(app, 3)
        with count_sql(app.store.engine) as five:
            rows5 = orch.admin_runs(limit=5)
        assert [r.run_id for r in rows2] == rids[1::-1] and [r.run_id for r in rows5] == rids[::-1]
        assert all(r.doc_score == 52.0 and r.attempt == 1 for r in rows5)
        # 실행 건 목록 · 포인터 · 채점 기록 · 마지막 시도 번호 — 한 연결
        assert (two.selects, two.checkouts) == (five.selects, five.checkouts) == (4, 1)
        no_whole_record_reads(five)
        with count_sql(app.store.engine) as empty:
            assert orch.admin_runs(limit=5, offset=100_000) == []                  # 빈 페이지 — 묶어 읽기는 문장 없음
        assert (empty.selects, empty.checkouts) == (1, 1)
        monkeypatch.setattr(store_sql_store, "PROJECT_CHUNK", 2)                   # 5건 = 묶음 3개 — 묶음마다 한 문장
        with count_sql(app.store.engine) as chunked:
            assert orch.admin_runs(limit=5) == rows5
        assert (chunked.selects, chunked.checkouts) == (1 + 3 * 3, 1)
    finally:
        # 2030년 실행 건이 MySQL 테스트 DB에 남으면 뒤 시험의 '최근 순' 페이지 맨 앞에 온다 — 계정째 탈퇴 처리로 지운다
        for account in {app.store.load_run(rid).account_id for rid in rids}:
            orch.delete_account_data(account)
    for rid in rids:                                                               # 지워졌다
        with pytest.raises(KeyError):
            app.store.load_run(rid)


def test_admin_summary_select_count_is_fixed(sql_backend, monkeypatch):
    app = sql_app(sql_backend)
    orch = app.orchestrator
    scored_runs(app, 2)
    orch.admin_summary()                                                           # 데우기
    with count_sql(app.store.engine) as two:
        orch.admin_summary()
    scored_runs(app, 3)
    with count_sql(app.store.engine) as five:
        summary = orch.admin_summary()
    monkeypatch.setattr(store_sql_store, "PROJECT_CHUNK", 2)                       # 범위판 — 묶음 크기와 관계없다
    with count_sql(app.store.engine) as chunked:
        assert orch.admin_summary() == summary
    # 실행 건 목록 · 실행 기록 집계(계기별 · 전체) · 채점 기록 · 포인터 — 한 연결
    assert ((two.selects, two.checkouts) == (five.selects, five.checkouts) == (chunked.selects, chunked.checkouts)
            == (5, 1))
    no_whole_record_reads(five)
    assert summary == ref_admin_summary(orch)
