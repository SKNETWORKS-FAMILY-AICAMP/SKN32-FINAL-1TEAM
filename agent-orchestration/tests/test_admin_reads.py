"""관리자 조회 (spec 4.2) — 실행 건 목록 · 점수 이력 · 운영 요약 · Agent별 Task · 실행 기록 · 호출 기록.
메타데이터 · 점수 · 개수만."""
from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import executed, make_app, pre_input, project_for, start_and_select, to_screen6
from flow_helpers import pid, rework, run_review

from sbrain.agents.stubs import StubScenario
from sbrain.orchestrator.errors import CommandError
from sbrain.orchestrator.settings import ScoringSettings, Settings
from sbrain.orchestrator.tools import TokenUsage

# 문장별 T-P2 결과: 채택 · 반려 뒤 채택 · 반려 뒤 조기 중단 · 반려만 → 시도 9건, 반려 7건
BEHAVIOR = {
    "s-1-1-1": ["ok"],
    "s-1-1-2": ["violate", "ok"],
    "s-2-1-1": ["violate", "same", "same"],
    "s-2-1-2": ["violate", "violate", "violate"],
}
CONTENT = ("헬스장", "문장", "(윤문)", "변형", "동일 출력", "1억원", "창업지원사업", "김서준")


def fixture(clock):
    """완료 A(화면 6 재작성 52 → 60, 총점 86) · 화면 6 대기 B(45) · 실패 C(T-S1 영구 오류) · 공고선택 대기 D."""
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0, 45.0], tp1_targets=4, tp2_behavior=BEHAVIOR))
    app.llm.usage["T-C1"] = TokenUsage(input_tokens=100, cached_input_tokens=40, output_tokens=20,
                                       reasoning_tokens=5)
    a = to_screen6(app, "acc-1")
    rework(app, clock, a, "문제인식")
    app.orchestrator.decide(a, 6, "진행")
    app.orchestrator.advance(a)
    app.orchestrator.decide(a, 8, "진행")
    run_review(app, a)
    b = to_screen6(app, "acc-2")
    c = start_and_select(app, "acc-3")
    app.llm.plan("T-S1", ["auth"] * 50)
    app.orchestrator.start_writing(c)
    app.orchestrator.advance(c)
    d = app.orchestrator.start_run("acc-4", pre_input(), project_id=project_for(app)).run_id
    assert [app.store.load_run(r).state.progress for r in (a, b, c, d)] == ["완료", "사용자대기", "실패", "사용자대기"]
    return app, a, b, c, d


def records(app, *rids):
    return [r for rid in rids for r in app.store.executions(rid)]


def tokens(r) -> int:
    return (r.input_tokens or 0) + (r.output_tokens or 0)


def no_content(*results) -> None:
    text = "".join(x.model_dump_json(by_alias=True) for x in results)
    assert not [w for w in CONTENT if w in text]                                 # 산출물 · 입력 · 문장 내용 없음


def test_admin_runs_list_filters_and_pages(clock):
    app, a, b, c, d = fixture(clock)
    rows = app.orchestrator.admin_runs()
    assert [r.run_id for r in rows] == [d, c, b, a]                              # 마지막 갱신 최근 순
    ra = rows[-1]
    assert (ra.project_id, ra.step, ra.progress, ra.current_task, ra.agent, ra.attempt) == (
        pid(app, a), "결과물", "완료", "T-C4", "조율", 1)
    assert (ra.doc_score, ra.artifact_score, ra.total_score) == (60.0, 26.25, 86.2)   # 대조 손잡이 11 → 11.25 (1.4판 몫)
    assert (ra.resume_count, ra.last_error_kind, ra.failure_reason) == (0, None, None)
    assert ra.updated_at == app.store.load_run(a).updated_at
    [rc] = app.orchestrator.admin_runs(progress="실패")
    run_c = app.store.load_run(c)
    assert (rc.run_id, rc.current_task, rc.agent, rc.last_error_kind) == (c, "T-S1", "전략", "운영")
    assert rc.failure_reason == run_c.failure_reason and rc.failure_reason       # 관리자용 실패 사유
    assert (rc.doc_score, rc.artifact_score, rc.total_score) == (None, None, None)
    [rb] = app.orchestrator.admin_runs(step="문서평가")
    assert (rb.run_id, rb.doc_score, rb.artifact_score, rb.total_score) == (b, 45.0, None, None)
    assert [r.run_id for r in app.orchestrator.admin_runs(progress="사용자대기")] == [d, b]
    assert [r.run_id for r in app.orchestrator.admin_runs(limit=2, offset=1)] == [c, b]
    assert app.orchestrator.admin_runs(progress="사용자대기", step="공고선택")[0].run_id == d
    app.orchestrator.select_announcement(d, "A01")                               # 명령 뒤 '실행' — 다음에 돌 단계
    [rd] = app.orchestrator.admin_runs(progress="실행")
    assert (rd.run_id, rd.step, rd.current_task, rd.agent) == (d, "자격확인", "G-01", "조율")
    no_content(*rows)


def test_admin_score_history_by_layer(clock):
    app, a, b, c, d = fixture(clock)
    h = app.orchestrator.admin_score_history(pid(app, a))
    assert (h.project_id, h.run_id) == (pid(app, a), a)
    assert [(e.score, e.after_rework) for e in h.doc_score] == [(60.0, True), (52.0, False)]   # 최근 순
    assert [(e.score, e.after_rework) for e in h.code_check] == [(15.0, False)]
    assert [(e.score, e.after_rework) for e in h.feature_match] == [(11.25, False)]   # 기능 2개 중 1.5 인정
    assert all(e.scored_at and e.execution_id for e in h.doc_score + h.code_check + h.feature_match)
    hb = app.orchestrator.admin_score_history(pid(app, b))
    assert [e.score for e in hb.doc_score] == [45.0] and hb.code_check == [] and hb.feature_match == []
    hc = app.orchestrator.admin_score_history(pid(app, c))                     # 실패 실행 건도 본다
    assert (hc.doc_score, hc.code_check, hc.feature_match) == ([], [], [])
    with pytest.raises(CommandError) as e:
        app.orchestrator.admin_score_history(777777)
    assert e.value.code == "RUN_NOT_FOUND"
    no_content(h, hb)


def test_admin_summary_values(clock):
    app, a, b, c, d = fixture(clock)
    s = app.orchestrator.admin_summary()
    assert s.status_counts == {"실행": 0, "재개대기": 0, "사용자대기": 2, "실패": 1, "완료": 1, "중단": 0}
    assert (s.doc_avg, s.doc_count) == (52.5, 2)                                 # 현재 버전 문서층 점수 (A 60 · B 45)
    assert (s.total_avg, s.total_count, s.pass_count, s.pass_rate, s.pass_threshold) == (86.2, 1, 1, 100.0, 80.0)
    assert (s.reworked_runs, s.runs_with_executions, s.rework_rate) == (1, 4, 25.0)
    assert [(x.label, x.count) for x in s.score_buckets] == [
        ("90~100점", 0), ("80~89점", 1), ("70~79점", 0), ("60~69점", 0), ("60점 미만", 0)]
    assert [(x.layer, x.first_avg, x.after_avg, x.delta, x.count) for x in s.layer_changes] == [
        ("docScore", 52.0, 60.0, 8.0, 1), ("codeCheck", None, None, None, 0), ("featureMatch", None, None, None, 0)]
    recs = records(app, a, b, c, d)
    assert [t.trigger for t in s.triggers] == ["첫실행", "재작성", "재수행"]
    for t in s.triggers:
        mine = [r for r in recs if r.trigger == t.trigger]
        assert t.count == len(mine)
        assert t.avg_tokens == (round(sum(tokens(r) for r in mine) / len(mine), 1) if mine else None)
    assert s.triggers[1].count > 0 and s.triggers[2].count == 0
    assert s.total_tokens == sum(tokens(r) for r in recs) == 4 * 120               # T-C1만 토큰을 냈다
    assert (s.proofread_attempts, s.proofread_rejected, s.proofread_reject_rate) == (9, 7, 77.8)
    app.settings.update(Settings(scoring=ScoringSettings(threshold=90)))          # 기준 점수는 지금 설정
    s2 = app.orchestrator.admin_summary()
    assert (s2.pass_count, s2.pass_rate, s2.pass_threshold) == (0, 0.0, 90.0)
    no_content(s)


def test_admin_summary_empty(clock):
    app = make_app(clock)
    s = app.orchestrator.admin_summary()
    assert set(s.status_counts.values()) == {0}
    assert (s.doc_avg, s.doc_count, s.total_avg, s.total_count, s.pass_count, s.pass_rate) == (None, 0, None, 0, 0, None)
    assert (s.reworked_runs, s.runs_with_executions, s.rework_rate, s.total_tokens) == (0, 0, None, 0)
    assert all(x.count == 0 for x in s.score_buckets) and all(x.count == 0 for x in s.layer_changes)
    assert all((t.count, t.avg_tokens) == (0, None) for t in s.triggers)
    assert (s.proofread_attempts, s.proofread_rejected, s.proofread_reject_rate) == (0, 0, None)


def test_admin_agent_tasks(clock):
    app, a, b, c, d = fixture(clock)
    tasks = app.orchestrator.admin_agent_tasks()
    assert [t.agent for t in tasks] == ["조율", "전략", "작성", "구현", "검증-1", "검증-2", "검수"]
    specs = app.registry.specs()
    recs = records(app, a, b, c, d)
    for t in tasks:
        assert t.task_ids == [s.task_id for s in specs if s.agent == t.agent] and t.task_count == len(t.task_ids)
        assert t.execution_count == len([r for r in recs if r.agent == t.agent])
    by = {t.agent: t for t in tasks}
    assert (by["조율"].recent_project_id, by["조율"].recent_status) == (pid(app, d), "성공")
    assert (by["전략"].recent_project_id, by["전략"].recent_status) == (pid(app, c), "실패")
    assert (by["검수"].recent_project_id, by["검수"].recent_status) == (pid(app, a), "성공")
    assert sum(t.task_count for t in tasks) == len(specs)
    no_content(*tasks)


def test_admin_runs_and_summary_limited_to_last_twelve_months(clock):
    """admin_runs · admin_summary는 마지막 활동이 최근 12개월 안인 실행 건만 (기준 시각은 보관 기간 작업과 같다)."""
    app, a, b, c, d = fixture(clock)
    old = records(app, a, b, c, d)
    edge = app.store.load_run(d).updated_at
    clock.t = edge.replace(year=edge.year + 1) - timedelta(milliseconds=2)       # 다음 호출 = 기준 시각이 마지막 활동 직전
    assert d in [r.run_id for r in app.orchestrator.admin_runs()]
    clock.t = edge.replace(year=edge.year + 1)                                   # 기준 시각이 마지막 활동 바로 뒤
    assert d not in [r.run_id for r in app.orchestrator.admin_runs()]
    clock.advance(days=30)
    app.llm.plan("T-S1", [])
    e = to_screen6(app, "acc-5")
    rows = app.orchestrator.admin_runs()
    assert [r.run_id for r in rows] == [e] and app.orchestrator.admin_runs(progress="완료") == []
    s = app.orchestrator.admin_summary()
    assert s.status_counts == {"실행": 0, "재개대기": 0, "사용자대기": 1, "실패": 0, "완료": 0, "중단": 0}
    mine = records(app, e)
    assert (s.runs_with_executions, s.reworked_runs, s.total_count, s.pass_count) == (1, 0, 0, 0)
    assert s.doc_count == (1 if rows[0].doc_score is not None else 0)
    assert [t.count for t in s.triggers] == [len([r for r in mine if r.trigger == t])
                                             for t in ("첫실행", "재작성", "재수행")]
    assert s.total_tokens == sum(tokens(r) for r in mine)
    assert (s.proofread_attempts, s.layer_changes[0].count) == (0, 0)            # A의 검수 · 재작성 변화는 범위 밖
    assert len(app.orchestrator.admin_executions(limit=None)) == len(old) + len(mine)   # 실행 기록 조회는 그대로
    assert app.orchestrator.admin_score_history(pid(app, a)).doc_score                  # 점수 이력도 그대로
    app.orchestrator.select_announcement(d, "A01")                               # 다시 움직이면 범위 안으로
    assert d in [r.run_id for r in app.orchestrator.admin_runs()]


# ── 실행 기록 · 호출 기록 조회 ─────────────────────────────
def test_admin_executions_filters_and_order(clock):
    app = make_app(clock)
    rid1 = to_screen6(app, "acc-1")
    rid2 = start_and_select(app, "acc-2")
    p1, p2 = pid(app, rid1), pid(app, rid2)
    rows = app.orchestrator.admin_executions(limit=100)
    assert [(r.project_id, r.task_id) for r in rows[:3]] == [(p2, "G-01"), (p2, "T-C2"), (p2, "T-C1")]  # 최근 순
    asc = app.orchestrator.admin_executions(project_id=p1, order="asc", limit=100)
    assert [r.task_id for r in asc] == executed(app, rid1)
    assert [r.project_id for r in app.orchestrator.admin_executions(task_id="T-C1")] == [p2, p1]
    assert [r.task_id for r in app.orchestrator.admin_executions(agent="전략", order="asc")] == ["T-S1", "T-S2"]
    assert app.orchestrator.admin_executions(status="실패") == []
    page = app.orchestrator.admin_executions(project_id=p1, order="asc", limit=3, offset=2)
    assert [r.task_id for r in page] == executed(app, rid1)[2:5]
    first2 = app.store.executions(rid2)[0].started_at
    assert {r.project_id for r in app.orchestrator.admin_executions(since=first2, limit=100)} == {p2}
    assert {r.project_id for r in app.orchestrator.admin_executions(until=first2, limit=100)} == {p1}
    tc1 = app.orchestrator.admin_executions(project_id=p1, task_id="T-C1")[0]
    assert (tc1.agent, tc1.attempt, tc1.trigger, tc1.status, tc1.model, tc1.reasoning_effort) == (
        "조율", 1, "첫실행", "성공", "gpt-6-luna", "low")
    assert tc1.duration_sec is not None and tc1.duration_sec >= 0 and tc1.tokens.input_tokens is None
    text = "".join(r.model_dump_json() for r in rows)
    assert "헬스장" not in text                                                    # 산출물 · 입력 내용은 싣지 않는다


def test_admin_calls_with_tries(clock):
    app = make_app(clock)
    app.llm.plan("T-S1", ["timeout", "ok"])
    rid = to_screen6(app)
    rec = next(r for r in app.store.executions(rid) if r.task_id == "T-S1")
    [call] = app.orchestrator.admin_calls(rec.execution_id)
    assert (call.call_type, call.final_outcome, call.model) == ("llm", "성공", "미정")
    assert [(t.no, t.outcome, t.error_kind) for t in call.tries] == [(1, "응답지연", "일시"), (2, "성공", None)]
    assert call.tokens.output_tokens is None and app.orchestrator.admin_calls("없는-실행") == []
