"""웹 테이블 쓰기 — 단계를 저장해도 웹 projects는 그대로, 알림 · 실패 알림은 단계 저장과 같은 트랜잭션 (SqlStore: SQLite · MySQL 8).

메모리 저장소는 웹 테이블이 없다. 실행 건의 실패 사유(Run.failureReason)는 두 저장소 모두 확인한다.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from conftest import Backend, Clock, make_app, pre_input, project_for, start_and_select, to_screen6
from sqlalchemy import text
from webdb import project_row

from sbrain.orchestrator.store import CommitBatch
from sbrain.store_sql.web_tables import WEB_COLUMNS


@pytest.fixture(params=["sql", "mysql"])
def sql_app(request, tmp_path):
    clock = Clock()
    return make_app(clock, store=Backend(request.param, tmp_path).make_store(clock)), clock


def account() -> str:
    """MySQL은 여러 테스트가 같은 DB를 쓰므로 계정을 테스트마다 새로 만든다 (계정당 진행 중 1건 제한)."""
    return uuid.uuid4().hex[:12]


def project_of(app, rid: str) -> int:
    return int(app.store.load_run(rid).project_id)


class ProjectWatch:
    """실행 건을 만든 직후의 웹 projects 행을 기억해 두고, 나중에 그대로인지 본다."""

    def __init__(self, app, rid: str) -> None:
        self.app, self.pid = app, project_of(app, rid)
        self.before = project_row(app.store.engine, self.pid)
        assert self.before["status"] is None and self.before["notice_id"] is None

    def unchanged(self) -> bool:
        return project_row(self.app.store.engine, self.pid) == self.before


def alerts(app, rid: str) -> list[tuple]:
    with app.store.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(
            "SELECT stage, resume_count, last_error_kind, failure_reason FROM generation_failure_alerts "
            "WHERE project_id = :p ORDER BY alert_id"), {"p": project_of(app, rid)})]


def web_notifications(app, rid: str) -> list[tuple]:
    with app.store.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(
            "SELECT kind, target_step FROM notifications WHERE project_id = :p ORDER BY notification_id"),
            {"p": project_of(app, rid)})]


def test_project_row_unchanged_through_whole_run(sql_app):
    app, _ = sql_app
    pid = project_for(app)
    before = project_row(app.store.engine, int(pid))                             # 실행 건을 만들기 전
    res = app.orchestrator.start_run(account(), pre_input(), project_id=pid)
    rid = res.run_id
    app.orchestrator.select_announcement(rid, "A01")                             # 공고 A01 → 자격 통과
    app.orchestrator.advance(rid)
    watch = ProjectWatch(app, rid)
    assert watch.before == before
    seen = []
    app.llm.respond("T-S1", lambda r: seen.append(watch.unchanged()) or '{"ok": true}')
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)                                                # 단계마다 저장
    assert seen == [True] and watch.unchanged()
    app.orchestrator.decide(rid, 6, "진행")
    app.orchestrator.advance(rid)
    app.orchestrator.decide(rid, 8, "진행")
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "완료"
    assert watch.unchanged()                                                     # 진행 컬럼 5개를 쓰지 않는다
    assert web_notifications(app, rid) == [("문서평가", 6), ("산출물확인", 8), ("표현검수", 10)]
    assert alerts(app, rid) == []
    assert not [e for e in app.store.events(rid) if e.kind == "공고ID없음"]       # 선택 공고 ID 확인을 하지 않는다


def test_web_columns_no_longer_write_projects_or_read_notices():
    assert WEB_COLUMNS["projects"] == ["project_id", "company_id"]               # 학습 동의 확인용으로 읽기만
    assert "notices" not in WEB_COLUMNS
    assert {"users", "companies", "proofread_logs"} <= set(WEB_COLUMNS)


def test_permanent_failure_sets_reason_and_one_alert(sql_app):
    app, _ = sql_app
    rid = start_and_select(app, account())
    watch = ProjectWatch(app, rid)
    app.llm.plan("T-C3", ["auth"] * 6)                                            # 401 → 운영 (영구 오류)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert run.failure_reason == "T-C3: 영구오류 — 호출실패"
    assert watch.unchanged()                                                     # failure_reason도 쓰지 않는다
    assert alerts(app, rid) == [("계획서작성", 0, "운영", run.failure_reason)]
    assert web_notifications(app, rid) == [("실패", None)]
    assert app.store.acquire(rid, "again", 60)                                   # 실패 뒤 다시 저장해도
    app.store.commit(rid, "again", CommitBatch(run=run))
    assert len(alerts(app, rid)) == 1                                             # 알림은 실패로 바뀔 때 한 번


def test_resume_limit_failure_is_temporary_kind(sql_app):
    app, clock = sql_app
    rid = start_and_select(app, account())
    watch = ProjectWatch(app, rid)
    app.llm.plan("T-S1", ["timeout"] * 200)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "재개대기" and watch.unchanged()
    for _ in range(5):                                                           # 이 실행 건만 (공유 MySQL DB)
        clock.t = app.store.load_run(rid).next_resume_at + timedelta(seconds=1)
        app.engine.resume(rid)
    run = app.store.load_run(rid)
    assert run.failure_reason == "T-S1: 재개상한초과 — 응답지연"
    assert alerts(app, rid) == [("계획서작성", 5, "일시", run.failure_reason)]
    assert watch.unchanged()


def test_abort_is_halted(sql_app):
    app, _ = sql_app
    rid = to_screen6(app, account())
    watch = ProjectWatch(app, rid)
    app.orchestrator.abort(rid, confirmed=True)
    assert app.store.load_run(rid).state.progress == "중단"
    assert watch.unchanged() and alerts(app, rid) == []


def test_failure_reason_on_run(clock):
    """두 저장소 모두 — 실패 사유는 실행 건에 남는다 (웹 projects에는 쓰지 않는다)."""
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-C3", ["bad_request"] * 6)                                     # 400 → 입력 (영구 오류)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    assert (run.state.progress, run.last_error_kind, run.failure_reason) == ("실패", "입력", "T-C3: 영구오류 — 호출실패")
    assert app.orchestrator.view(rid).percent == 0
