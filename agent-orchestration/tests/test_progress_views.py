"""진행 상태 조회의 한 시점 읽기 — view · view_project · wait_project(끝 조회) · project_views (성능 측정 C 후속,
2026-10-20).

호출 한 번에 저장소의 한 시점 읽기 구간(store.read_snapshot) 하나에서 실행 건(없으면 마지막 시작 요청) · 알림 · 선택 공고를
읽고, 구간을 닫은 뒤 화면 칸을 만든다. 실행 건 컨텍스트를 열지 않고 실행 기록 · 최신 버전을 읽지 않는다.

- 섞인 묶음(메모리 · SQLite): project_views의 각 줄이 그 프로젝트 하나로 부른 view_project와 같다(정수 표준형 ID).
- 마감 안내 · 시계 자리(메모리 · SQLite): 시계는 실행 건마다 지금과 같은 자리 · 순서 — 마감일 비교(마감일이 있을 때만) →
  안내 시각(안내를 붙일 때만) → collecting. 기대값은 지금 식대로 적는다(tests/test_clock.py의 마감 안내 시험 방식).
- 구간 하나 · 읽지 않는 것 · 오류(메모리 · SQLite): 호출마다 구간 하나(겹치지 않음), 빈 목록은 구간 없음, 없는 실행 건은
  KeyError, 선택 공고 포인터만 있고 버전 행이 없으면 KeyError.
- 같은 순간(메모리 · SQLite · MySQL, TIMING): 구간의 첫 읽기 뒤 다른 스레드가 쓰기 하나(시작 요청 → 실행 건, 단계 저장으로
  알림 · 진행 상태가 함께 바뀜, 공고 다시 고르기)를 해도 결과는 앞 순간이고 다음 호출은 뒤 순간이다. 메모리 · SQLite는 쓰기가
  구간 끝을 기다리고, MySQL은 기다리지 않고 끝나도 구간은 앞 순간을 본다.
- 문장 수 · 연결 수(SQLite · MySQL): 실행 건 2개와 5개에서 같은 SELECT 수, 호출마다 연결 1번, 빈 목록은 0번.

MySQL 테스트 DB에 워커가 가져갈 일('실행' 실행 건 · 대기 · 처리중 시작 요청)을 남기지 않게 끝에서 중단 · 취소한다.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from conftest import TIMING, Backend, Clock, make_app, pre_input, project_for, start_and_select
from flow_helpers import pid
from store_helpers import count_sql, sql_backend, uid, write_during_snapshot  # noqa: F401 — sql_backend는 pytest 장치

from sbrain.agents.stubs import StubScenario
from sbrain.flow.service import ProjectView, RunView
from sbrain.models import Notification
from sbrain.models.clock import UTC
from sbrain.models.run import make_state
from sbrain.orchestrator.store import ArtifactVersion, CommitBatch, StartRequest
from sbrain.store_sql import SqlStore

SA = "selectedAnnouncement"
CLOSED = "E-RUN-CLOSED"


# ── 도움 ─────────────────────────────────────────────────
def run_of(view: RunView | ProjectView) -> RunView | None:
    return view if isinstance(view, RunView) else view.run


def closed_at(view: RunView | ProjectView) -> datetime | None:
    """마감 안내(E-RUN-CLOSED)의 시각 — 안내가 없으면 None."""
    run = run_of(view)
    return None if run is None else next((n.at for n in run.notices if n.code == CLOSED), None)


def without_closed_at(view: ProjectView) -> ProjectView:
    """마감 안내의 시각은 부를 때마다 지금이라 비교에서 뺀다."""
    if view.run is None:
        return view
    notices = [n.model_copy(update={"at": None}) if n.code == CLOSED else n for n in view.run.notices]
    return replace(view, run=replace(view.run, notices=notices))


def request_only(app, clock: Clock) -> tuple[str, StartRequest]:
    """시작 요청만 있는 프로젝트 — '대기' 요청 하나(계정은 새로)."""
    p = project_for(app)
    now = clock()
    req = StartRequest(request_id=uid(), project_id=p, account_id=uid(), status="대기", form=pre_input().dump(),
                       created_at=now, updated_at=now)
    assert app.store.add_start_request(req) is None
    return p, req


def app_on(backend: Backend, scenario: StubScenario | None = None):
    clock = Clock(backend=backend)
    return make_app(clock, scenario), clock


class RecordingClock:
    """부를 때마다 1밀리초씩 가고 돌려준 값을 차례로 남기는 시계 — 명령 창구의 시계(orchestrator.now) 자리에 끼운다."""

    def __init__(self, start: datetime) -> None:
        self.t = start
        self.calls: list[datetime] = []

    def __call__(self) -> datetime:
        self.t += timedelta(milliseconds=1)
        self.calls.append(self.t)
        return self.t


class SnapshotWatch:
    """store.read_snapshot을 감싸 연 구간 수와 겹친 깊이를 센다."""

    def __init__(self, store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self.opened = self.depth = self.max_depth = 0
        real = store.read_snapshot

        @contextmanager
        def watched() -> Iterator[Any]:
            self.opened += 1
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
            try:
                with real() as snap:
                    yield snap
            finally:
                self.depth -= 1
        monkeypatch.setattr(store, "read_snapshot", watched)


def refuse(name: str) -> Callable[..., Any]:
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"진행 상태 조회가 {name}을 불렀다")
    return refused


# ── 섞인 묶음 = 프로젝트마다 view_project ─────────────────────
def test_project_views_mixed_batch_matches_view_project(clock):
    """마감된 공고(안내) · 모집 중 공고 · 공고 고르기 전 · 실패(마감된 공고라도 진행 중이 아니라 안내 없음) · 시작 요청만 ·
    없는 프로젝트를 섞고, 만든 순서와 다르게 넘기고 같은 프로젝트를 두 번 넘긴다(정수 · 문자열 ID 섞음)."""
    app = make_app(clock, StubScenario(closed_ids={"A02"}))
    orch = app.orchestrator
    closed = pid(app, start_and_select(app, "acc-1", "A02"))                     # 모집 상태 '마감'
    open_ = pid(app, start_and_select(app, "acc-2", "A01"))
    before_pick = pid(app, orch.start_run("acc-3", pre_input(), project_id=project_for(app)).run_id)
    failed_rid = start_and_select(app, "acc-4", "A02")
    app.llm.plan("T-S1", ["auth"])                                               # 401 — 재시도 없이 실패
    orch.start_writing(failed_rid)
    orch.advance(failed_rid)
    failed = pid(app, failed_rid)
    start_only, _ = request_only(app, clock)
    ids = [failed, closed, "999999", int(before_pick), start_only, closed, open_]
    views = orch.project_views(ids)
    assert [v.project_id for v in views] == [str(p) for p in ids]
    assert [without_closed_at(v) for v in views] == [without_closed_at(orch.view_project(p)) for p in ids]
    assert [v.run.progress if v.run else None for v in views] == [
        "실패", "사용자대기", None, "사용자대기", None, "사용자대기", "사용자대기"]
    assert [v.run.announcement_id if v.run else None for v in views] == ["A02", "A02", None, None, None, "A02", "A01"]
    assert [closed_at(v) is not None for v in views] == [False, True, False, False, False, True, False]
    assert views[4].start.status == "대기" and (views[2].run, views[2].start) == (None, None)
    assert without_closed_at(views[1]) == without_closed_at(views[5])           # 같은 프로젝트는 줄마다 같은 내용


# ── 마감 안내 · 시계 자리 ───────────────────────────────────
def test_deadline_notice_and_clock_calls_stay_in_place(clock):
    """실행 건마다 지금 식과 같은 순서 · 횟수로 시계를 부른다: 선택 공고에 마감일이 있으면 kst_today(now()) 비교(없으면 부르지
    않음), 안내를 붙이면 at=now(), 끝으로 collecting(run, now()). 마감일이 어제면 안내, 오늘이면 없음(한국 날짜), 비어 있으면
    비교하지 않음, 모집 상태가 '마감'이면 마감일과 관계없이 안내."""
    app = make_app(clock, StubScenario(no_deadline_ids={"A03"}, closed_ids={"A04"}))   # 2026-09-26 09:00 UTC (한국 18:00)
    orch = app.orchestrator
    first = start_and_select(app, "acc-1", "A01")                               # 마감일 = G-01 날짜 + 30일
    clock.advance(days=1)                                                       # 한국 9월 27일
    rids = [first, start_and_select(app, "acc-2", "A01"), start_and_select(app, "acc-3", "A03"),
            start_and_select(app, "acc-4", "A04")]
    anns = [app.engine.open_context(app.store.load_run(r)).get(SA) for r in rids]
    assert [(a.apply_end, a.status) for a in anns] == [
        (date(2026, 10, 26), "모집중"), (date(2026, 10, 27), "모집중"), (None, "모집중"), (date(2026, 10, 27), "마감")]
    ps = [pid(app, r) for r in rids]

    rec = RecordingClock(datetime(2026, 10, 26, 15, 0, tzinfo=UTC))             # 한국 10월 27일 0시부터
    orch.now = rec
    views = orch.project_views(ps)
    # 지금 식대로(넘긴 순서): 어제 마감 = 비교 · 안내 · collecting, 오늘 마감 = 비교 · collecting, 마감일 없음 = collecting,
    # 모집 상태 '마감' = 비교(거짓) · 안내 · collecting
    assert len(rec.calls) == 3 + 2 + 1 + 3
    assert [closed_at(v) for v in views] == [rec.calls[1], None, None, rec.calls[7]]
    assert views[0].run.notices[-1].code == views[3].run.notices[-1].code == CLOSED   # 실행 건의 안내 뒤에 붙인다

    # 실행 건 하나 — 첫 시계 값이 마감일 비교에 쓰인다: 첫 값은 한국 10월 26일 23:59:59.999(마감일 당일), 다음은 10월 27일
    rec = RecordingClock(datetime(2026, 10, 26, 14, 59, 59, 998000, tzinfo=UTC))
    orch.now = rec
    assert closed_at(orch.view(rids[0])) is None and len(rec.calls) == 2       # 비교 · collecting
    rec = RecordingClock(datetime(2026, 10, 26, 14, 59, 59, 999000, tzinfo=UTC))   # 첫 값부터 10월 27일
    orch.now = rec
    assert closed_at(orch.view_project(ps[0])) == rec.calls[1] and len(rec.calls) == 3   # 비교 · 안내 · collecting


# ── 구간 하나 · 읽지 않는 것 · 오류 ──────────────────────────
NOT_READ = ("executions", "get_latest_versions", "get_pointers", "get_artifact", "notifications")


def general_methods(store: Any) -> list[str]:
    """저장소 일반 메서드 이름 — 한 시점 구간(read_snapshot) 말고 모두."""
    cls = type(store)
    return [n for n in dir(cls) if not n.startswith("_") and n != "read_snapshot" and callable(getattr(cls, n))]


def test_progress_views_use_one_snapshot_without_run_context(clock, monkeypatch):
    """호출 한 번에 구간 하나(겹치지 않음) — 실행 건 컨텍스트를 열지 않고 실행 기록 · 최신 버전 · 포인터 목록 · 실행 건별 알림을
    읽지 않는다. SQL 저장소는 저장소 일반 메서드를 하나도 부르지 않는다(메모리 창구는 같은 이름 읽기에 저장소 메서드를 쓰므로
    고른 것만 막는다). wait_project는 기다리는 반복이 저장소를 읽고 끝 조회가 구간 하나다. 빈 목록은 구간을 열지 않는다."""
    app = make_app(clock)
    orch = app.orchestrator
    rid = start_and_select(app)                                                 # 진행 중 · 공고 고름 — 선택 공고를 본다
    p = pid(app, rid)
    want = orch.view_project(p)
    store = app.store
    for name in NOT_READ:
        monkeypatch.setattr(store, name, refuse(f"저장소 {name}"))
    monkeypatch.setattr(app.engine, "open_context", refuse("실행 건 컨텍스트(open_context)"))
    watch = SnapshotWatch(store, monkeypatch)
    assert orch.wait_project(p, timeout_sec=0) == want
    assert watch.opened == 1
    if isinstance(store, SqlStore):
        for name in general_methods(store):
            monkeypatch.setattr(store, name, refuse(f"저장소 {name}"))
    assert orch.view(rid) == want.run
    assert orch.view_project(p) == want
    assert orch.project_views([p, "999999", p]) == [want, ProjectView("999999"), want]
    assert orch.project_views([]) == [] and orch.project_views(iter([])) == []
    assert (watch.opened, watch.max_depth) == (4, 1)


def test_missing_run_and_broken_announcement_are_key_errors(clock):
    """없는 실행 건의 view(run_id)는 지금처럼 KeyError. 선택 공고 포인터는 있는데 버전 행이 없으면(깨진 데이터) 두 저장소 모두
    KeyError를 받지 않고 그대로 올린다 — 모양은 get_artifact와 같은 (run_id, key, version)."""
    app = make_app(clock)
    orch = app.orchestrator
    with pytest.raises(KeyError):
        orch.view("no-such-run")
    rid = start_and_select(app)
    p = pid(app, rid)
    version = app.store.get_pointers(rid)[SA] + 5
    owner = f"broken-{uid()}"
    assert app.store.acquire(rid, owner, 60)
    app.store.commit(rid, owner, CommitBatch(run=app.store.load_run(rid), pointers={SA: version}))   # 버전 행 없이 포인터만
    app.store.release(rid, owner)
    for read in (lambda: orch.view(rid), lambda: orch.view_project(p), lambda: orch.project_views([p])):
        with pytest.raises(KeyError) as e:
            read()
        assert e.value.args == ((rid, SA, version),)
    assert orch.view_project("999999") == ProjectView("999999")                 # 구간이 닫혀 다음 조회는 정상


# ── 같은 순간 — 구간의 첫 읽기 뒤 다른 스레드의 쓰기 ──────────────
def seen_by(app, how: str, p: str, rid: str | None = None) -> RunView | ProjectView:
    """진행 상태 조회 하나 — view는 RunView, 나머지는 ProjectView."""
    orch = app.orchestrator
    if how == "view":
        return orch.view(rid)
    if how == "view_project":
        return orch.view_project(p)
    [one] = orch.project_views([p])
    return one


def pending_run_creation(app, clock: Clock) -> tuple[str, str, Callable[[], str]]:
    """'처리중' 시작 요청 하나를 사전 단계까지 돌리고 실행 건 생성 저장(실행 건 + 요청 '완료' 한 트랜잭션)만 남긴다.

    (프로젝트, 요청 ID, 그 저장 함수) — 저장 함수는 다른 스레드에서 불러도 된다(쓸 값은 여기서 다 만들어 둔다).
    """
    p, req = request_only(app, clock)
    store, held = app.store, {}
    real = store.create_run_for_request

    def hold(run, batch, request_id, owner, **kw):
        held.update(args=(run, batch, request_id, owner), kw=kw)
        return "완료"
    store.create_run_for_request = hold
    try:
        assert app.orchestrator.run_start_request(req.request_id).status == "처리중"
    finally:
        del store.create_run_for_request
    return p, req.request_id, lambda: real(*held["args"], **held["kw"])


def pending_step_save(app, clock: Clock, rid: str) -> tuple[str, Callable[[], None]]:
    """단계 저장 하나 — 진행 상태(문서평가 · 사용자대기)와 알림 '문서평가'를 한 묶음으로. 점유는 여기서 잡아 둔다(점유자를 준다)."""
    run = app.store.load_run(rid)
    run.state = make_state("문서평가", "사용자대기")
    batch = CommitBatch(run=run, notifications=[
        Notification(run_id=rid, kind="문서평가", target_step=6, created_at=clock(), notification_id="n")])
    owner = f"writer-{uid()}"
    assert app.store.acquire(rid, owner, 60)
    return owner, lambda: app.store.commit(rid, owner, batch)


def pending_reselection(app, clock: Clock, rid: str, announcement_id: str) -> tuple[str, Callable[[], None]]:
    """공고 다시 고르기의 저장 — G-01 결과처럼 선택 공고 새 버전(모집 상태 '마감') · 포인터와 Run.announcement_id를 한 묶음으로."""
    store = app.store
    run = store.load_run(rid)
    version = store.get_pointers(rid)[SA]
    adapter = app.engine.types.adapter(SA)
    ann = adapter.validate_python(store.get_artifact(rid, SA, version).value)
    picked = adapter.dump_python(ann.model_copy(update={"announcement_id": announcement_id, "status": "마감"}),
                                 mode="json", by_alias=True)
    run.announcement_id = announcement_id
    batch = CommitBatch(run=run, versions=[ArtifactVersion(rid, SA, version + 1, picked, "exec-G-01", clock())],
                        pointers={SA: version + 1})
    owner = f"writer-{uid()}"
    assert store.acquire(rid, owner, 60)
    return owner, lambda: store.commit(rid, owner, batch)


def assert_write_inside(outcome, backend: Backend) -> None:
    assert outcome.started and outcome.error is None and outcome.finished
    assert outcome.finished_in_snapshot is (backend.kind == "mysql")            # 메모리 · SQLite는 쓰기가 구간 끝을 기다린다


@TIMING
@pytest.mark.parametrize("how", ["view_project", "project_views"])
def test_start_request_becoming_run_is_seen_at_one_moment(any_backend, how):
    """시작 요청이 실행 건이 되는 저장이 구간의 첫 읽기(실행 건 찾기) 뒤에 끼어도 결과는 앞 순간('처리중' 요청)이고 다음 호출은
    실행 건이다. 나눠 읽던 예전 방식이면 실행 건 대신 '요청 완료'만 보였다(같은 쓰기를 실행 건 찾기와 시작 요청 읽기 사이에 끼워
    확인한다)."""
    app, clock = app_on(any_backend)
    p, p_req, write = pending_run_creation(app, clock)
    q, q_req, write_q = pending_run_creation(app, clock)
    try:
        split = (app.store.find_run_by_project(q), write_q(), app.store.latest_start_request(q))
        assert split[0] is None and split[1] == "완료" and split[2].status == "완료"   # 앞 순간도 뒤 순간도 아니다
        before = seen_by(app, how, p)
        assert before.run is None and before.start.status == "처리중"
        with write_during_snapshot(app.store, write) as outcome:
            got = seen_by(app, how, p)
        after = seen_by(app, how, p)
    finally:
        for req_id in (p_req, q_req):                                            # 워커가 가져갈 요청을 남기지 않는다
            app.store.cancel_start_request(req_id)
    assert_write_inside(outcome, any_backend)
    assert outcome.result == "완료"
    assert got == before                                                        # 앞 순간
    assert after.start is None and after.run.run_id == app.store.find_run_by_project(p).run_id


@TIMING
@pytest.mark.parametrize("how", ["view", "project_views"])
def test_step_save_changes_progress_and_notifications_at_one_moment(any_backend, how):
    """단계 저장(진행 상태 + 알림 한 묶음)이 구간의 첫 읽기(실행 건) 뒤에 끼어도 결과는 앞 순간 — 진행 상태는 전 것 · 알림은
    새 것으로 섞이지 않는다. 다음 호출은 둘 다 새 것."""
    app, clock = app_on(any_backend)
    rid = start_and_select(app, uid())                                          # 계획서작성 · 사용자대기, 알림 없음
    p = pid(app, rid)
    owner, write = pending_step_save(app, clock, rid)
    try:
        before = seen_by(app, how, p, rid)
        with write_during_snapshot(app.store, write) as outcome:
            got = seen_by(app, how, p, rid)
        after = seen_by(app, how, p, rid)
    finally:
        app.store.release(rid, owner)
    assert_write_inside(outcome, any_backend)
    assert got == before
    assert (run_of(before).step, run_of(before).notifications) == ("계획서작성", [])
    assert (run_of(after).step, [n.kind for n in run_of(after).notifications]) == ("문서평가", ["문서평가"])


@TIMING
@pytest.mark.parametrize("how", ["view_project", "project_views"])
def test_reselected_announcement_and_deadline_notice_at_one_moment(any_backend, how):
    """공고 다시 고르기(선택 공고 새 버전 · 포인터 + Run.announcement_id 한 묶음)가 구간의 첫 읽기 뒤에 끼어도 결과는 앞 순간 —
    공고 ID는 전 공고인데 마감 안내는 새 공고(모집 상태 '마감') 기준으로 섞이지 않는다. 다음 호출은 새 공고와 그 안내."""
    app, clock = app_on(any_backend)
    rid = start_and_select(app, uid(), "A01")                                   # 모집 중 — 안내 없음
    p = pid(app, rid)
    owner, write = pending_reselection(app, clock, rid, "A02")
    try:
        before = seen_by(app, how, p, rid)
        with write_during_snapshot(app.store, write) as outcome:
            got = seen_by(app, how, p, rid)
        after = seen_by(app, how, p, rid)
    finally:
        app.store.release(rid, owner)
    assert_write_inside(outcome, any_backend)
    assert got == before
    assert (run_of(before).announcement_id, closed_at(before)) == ("A01", None)
    assert run_of(after).announcement_id == "A02" and closed_at(after) is not None


# ── 문장 수 · 연결 수 (SQL — 장치 sql_backend는 store_helpers) ─────────
def counted(app, read: Callable[[], Any]):
    """read를 한 번 불러 데운 뒤(웹 표 구조 읽기 · 첫 연결 설정 문장을 뺀다) 두 번째 호출의 문장 · 연결 꺼내기를 센다."""
    read()
    with count_sql(app.store.engine) as counts:
        read()
    return counts


def test_project_views_select_count_does_not_grow_with_runs(sql_backend):
    """공고 고른 진행 중 실행 건 2개와 5개에서 같은 SELECT 수 · 연결 1번. 실행 건이 없는 프로젝트(시작 요청만 · 없는 프로젝트)가
    섞이면 마지막 시작 요청 읽기 한 문장이 더해진다 — 이것도 실행 건 수와 관계없이 같다."""
    app, clock = app_on(sql_backend)
    orch = app.orchestrator
    runs = [pid(app, start_and_select(app, uid())) for _ in range(2)]            # 계획서작성 · 사용자대기, 공고 A01
    start_only, req = request_only(app, clock)
    try:
        two = counted(app, lambda: orch.project_views(runs))
        two_mixed = counted(app, lambda: orch.project_views([start_only, *runs, "999999"]))
        runs += [pid(app, start_and_select(app, uid())) for _ in range(3)]
        five = counted(app, lambda: orch.project_views(runs))
        five_mixed = counted(app, lambda: orch.project_views([start_only, *runs, "999999"]))
        assert all(v.run.announcement_id == "A01" for v in orch.project_views(runs))
    finally:
        app.store.cancel_start_request(req.request_id)                          # 워커가 가져갈 요청을 남기지 않는다
    # 실행 건 1 · 알림 2(실행 건 줄의 project_id · 웹 notifications) · 선택 공고 1
    assert (two.selects, two.checkouts) == (five.selects, five.checkouts) == (4, 1)
    # + 실행 건이 없는 프로젝트의 마지막 시작 요청 1
    assert (two_mixed.selects, two_mixed.checkouts) == (five_mixed.selects, five_mixed.checkouts) == (5, 1)
    assert two.others == five.others and two_mixed.others == five_mixed.others


def test_view_select_counts_and_one_connection(sql_backend):
    """생성 중(계획서작성 · 실행)이고 공고를 고른 실행 건의 view_project · view — 실행 건 1 · 알림 2 · 선택 공고 1, 연결 1번.
    실행 기록 · 최신 버전을 읽지 않는다(예전에는 실행 건 컨텍스트를 열어 포인터 · 최신 버전 · 실행 기록까지 읽었다). 시작 요청만
    있는 프로젝트의 view_project는 실행 건 1 · 마지막 시작 요청 1. project_views([])는 문장 · 연결 0."""
    app, clock = app_on(sql_backend)
    orch = app.orchestrator
    rid = start_and_select(app, uid())
    p = pid(app, rid)
    orch.start_writing(rid)                                                      # 계획서작성 · 실행 — 워커가 아직 안 가져감
    start_only, req = request_only(app, clock)
    try:
        assert (orch.view(rid).step, orch.view(rid).progress) == ("계획서작성", "실행")
        by_project = counted(app, lambda: orch.view_project(p))
        by_run = counted(app, lambda: orch.view(rid))
        request_view = counted(app, lambda: orch.view_project(start_only))
        with count_sql(app.store.engine) as empty:
            assert orch.project_views([]) == []
    finally:
        orch.abort_project(p)                                                    # '실행' 실행 건을 남기지 않는다
        app.store.cancel_start_request(req.request_id)
    assert (by_project.selects, by_project.checkouts) == (by_run.selects, by_run.checkouts) == (4, 1)
    assert (request_view.selects, request_view.checkouts) == (2, 1)
    assert empty.statements == [] and empty.checkouts == 0
    statements = by_project.statements + by_run.statements
    assert not any("orch_executions" in s for s in statements)                  # 실행 기록을 읽지 않는다
    assert not any("max(" in s.lower() for s in statements)                     # 최신 버전(키별 최댓값)을 읽지 않는다
