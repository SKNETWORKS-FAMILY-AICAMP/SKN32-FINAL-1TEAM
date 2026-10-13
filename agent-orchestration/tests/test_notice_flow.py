"""실제 T-C2 · G-01을 흐름 안에서 (메모리 · SQLite 저장소) — 가짜 전송으로 시험한다. 네트워크에 나가지 않는다.

- 시 · 도 바꾸기가 매칭 요청에 실리고, 고른 공고 · 업력이 저장된다. 실행 · 호출 기록에 공고 내용 · 신청자 정보 · 주소가 없다.
- 판정 모름(E-G1-UNPARSED)은 화면 4에만, 공고 없음은 X-C2-GONE으로 고르기 전 대기 지점에, 수집 지연은 시작에서 끝낸다.
"""
from __future__ import annotations

import pytest
from conftest import executed, make_app, pre_input
from flow_helpers import select, started
from notice_fake import FAKE_URL, FakeNoticeServer, gate

from sbrain.agents.notice import NoticeClient, bind_notice
from sbrain.orchestrator.errors import message


# ── 흐름 안에서 (메모리 · SQLite) ─────────────────────────
def notice_app(clock, server: FakeNoticeServer):
    app = make_app(clock)
    bind_notice(app.registry, NoticeClient(FAKE_URL, transport=server))
    return app


def test_real_tasks_run_through_the_flow(clock):
    server = FakeNoticeServer()
    server.gates["bizinfo:B02"] = gate(business_age_months=18)
    app = notice_app(clock, server)
    rid = started(app, region="경기도 수원시 영통구")
    pid = app.store.load_run(rid).project_id
    s3 = app.orchestrator.screen(pid, 3)
    assert [cd.announcement_id for cd in s3.candidates] == ["kstartup:A01", "bizinfo:B02", "kstartup:A03"]
    assert (s3.collection_status, s3.filtered_count) == ("정상", 42)
    assert server.calls[1][2]["region"] == "경기" and server.calls[1][2]["district"] == "수원시 영통구"
    select(app, rid, "bizinfo:B02")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.announcement_id) == ("계획서작성", "사용자대기", "bizinfo:B02")
    ctx = app.engine.open_context(run)
    assert ctx.get("selectedAnnouncement").title == "창업지원 bizinfo:B02" and ctx.get("businessAgeYears") == 1.5
    calls = app.store.call_logs(rid)
    assert [(cl.task_id, cl.purpose) for cl in calls] == [
        ("T-C1", "카테고리 판정"), ("T-C2", "수집 상태"), ("T-C2", "공고 매칭"), ("G-01", "공고 상세"), ("G-01", "자격 판정")]
    dump = "".join(r.model_dump_json() for r in app.store.executions(rid)) + "".join(
        cl.model_dump_json() for cl in calls)
    assert "창업지원" not in dump and "김서준" not in dump and "example.invalid" not in dump


def test_real_g01_unknown_conditions_only_on_screen4(clock):
    server = FakeNoticeServer()
    server.gates["kstartup:A01"] = gate(unknown_conditions=["지원대상 유형", "업력"])
    app = notice_app(clock, server)
    rid = started(app, region="경기도 수원시 영통구")
    pid = app.store.load_run(rid).project_id
    select(app, rid, "kstartup:A01")
    assert app.store.load_run(rid).state.step == "계획서작성"
    s4 = app.orchestrator.screen(pid, 4)
    assert s4.gate_result.unknown_conditions == ["지원대상 유형", "업력"] and s4.can_start_writing
    assert [(n.code, n.message) for n in s4.notices] == [("E-G1-UNPARSED", message("E-G1-UNPARSED"))]
    assert "E-G1-UNPARSED" not in [n.code for n in app.store.load_run(rid).notices]


@pytest.mark.parametrize("where", ["상세", "판정"])
def test_real_g01_not_found_goes_back_with_gone(clock, where):
    server = FakeNoticeServer()
    (server.not_found if where == "상세" else server.gate_not_found).add("kstartup:A01")
    app = notice_app(clock, server)
    rid = started(app, region="경기도 수원시 영통구")
    select(app, rid, "kstartup:A01")
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.notices[-1].code, run.announcement_id) == (
        "공고선택", "사용자대기", "X-C2-GONE", None)
    assert run.blocked_announcement_ids == []
    server.not_found.clear()
    server.gate_not_found.clear()                                                  # 다시 생겼다
    select(app, rid, "kstartup:A01")
    assert app.store.load_run(rid).announcement_id == "kstartup:A01"
    assert executed(app, rid).count("G-01") == 2


def test_real_tc2_stale_collection_ends_start_request(clock):
    server = FakeNoticeServer()
    server.status = {"status": "지연"}
    app = notice_app(clock, server)
    res = app.orchestrator.start_run("acc-1", pre_input())
    assert (res.ok, res.code) == (False, "E-C2-STALE")
    assert ("POST", "/api/match") not in server.paths()
