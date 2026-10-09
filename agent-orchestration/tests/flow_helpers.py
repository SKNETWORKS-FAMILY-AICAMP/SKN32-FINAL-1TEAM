"""흐름 테스트 도움 — 스텁 앱(make_app)으로 실행 건을 움직이고 상태 · 기록을 읽는 함수. 여러 테스트 파일이 함께 쓴다.

시작 · 화면까지 가기(start_and_select · to_screen6 등)는 conftest.py에 있다. 여기는 그 뒤에 자주 쓰는 짧은 동작만 둔다.
"""
from __future__ import annotations

import pytest
from conftest import pre_input, project_for

from sbrain.orchestrator.errors import CommandError
from sbrain.orchestrator.tools import LLMRequest

WINDOW = 3   # 재작성 요청을 모으는 시간(잠정 2초)을 넘기는 초


# ── 시작 · 명령 ─────────────────────────────────────────
def started(app, **form) -> str:
    """사전 정보(form으로 칸을 바꿀 수 있다)로 시작해 공고선택 대기까지. 실행 건 ID를 돌려준다."""
    res = app.orchestrator.start_run("acc-1", pre_input(**form), project_id=project_for(app))
    assert res.ok, res
    return res.run_id


def started_with_pid(app) -> tuple[str, str]:
    """started와 같지만 (실행 건 ID, 프로젝트 ID)를 돌려준다 — 웹은 project_id로 부른다."""
    rid = started(app)
    return rid, pid(app, rid)


def select(app, rid: str, aid: str) -> None:
    app.orchestrator.select_announcement(rid, aid)
    app.orchestrator.advance(rid)


def rework(app, clock, rid: str, *bundles: str) -> list:
    """묶음들을 모으는 시간 안에 요청하고, 시간이 지난 뒤 진행한다(워커 대신 advance). 받은 요청 결과 목록을 돌려준다."""
    accepted = [app.orchestrator.request_rework_for_project(pid(app, rid), b) for b in bundles]
    clock.advance(seconds=WINDOW)
    app.orchestrator.advance(rid)
    return accepted


def run_review(app, rid: str) -> None:
    """화면 9에서 '진행'(확인함) — 검수 · 결과물까지 돈다."""
    app.orchestrator.decide(rid, 9, "진행", confirmed=True)
    app.orchestrator.advance(rid)


def finish(app, rid: str) -> None:
    """run_review 뒤 실행 건이 완료인지 확인한다."""
    run_review(app, rid)
    assert app.store.load_run(rid).state.progress == "완료"


def code_of(fn) -> str:
    """명령이 CommandError를 내야 한다 — 그 오류 코드를 돌려준다."""
    with pytest.raises(CommandError) as e:
        fn()
    return e.value.code


# ── 읽기 ───────────────────────────────────────────────
def pid(app, rid: str) -> str:
    return app.store.load_run(rid).project_id


def state(app, rid: str) -> tuple[str, str]:
    run = app.store.load_run(rid)
    return run.state.step, run.state.progress


def ctx_of(app, rid: str):
    return app.engine.open_context(app.store.load_run(rid))


def records_of_task(app, rid: str, task_id: str) -> list:
    """한 Task의 실행 기록(시도 순서)."""
    return [r for r in app.store.executions(rid) if r.task_id == task_id]


def last_cycle_id(app, rid: str) -> str:
    return [e for e in app.store.events(rid) if e.kind == "재작성시작"][-1].cycle_id


def cycle_steps(app, rid: str, cycle_id: str) -> list[str]:
    return [r.task_id for r in app.store.executions(rid) if r.cycle_id == cycle_id]


def usage_of(app, rid: str) -> dict:
    return {u.bundle_id: (u.used_count, u.remaining) for u in app.store.load_run(rid).rework_usage}


def tc3_requests(app_or_llm) -> list[LLMRequest]:
    """T-C3의 LLM 요청 — 앱(app.llm) 또는 가짜 LLM을 받는다."""
    llm = getattr(app_or_llm, "llm", app_or_llm)
    return [r for r in llm.requests if r.metadata["task_id"] == "T-C3"]
