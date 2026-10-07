"""공고 추가 조회 규칙 (spec 4.2 · 4.1.3) — 겹침 빼기 · 첫 조회 카드 갱신 · 내용 바뀜 · 막힌 공고 풀기 · 실패 처리.

- 추가 조회 결과에서 첫 조회와 겹치는 공고는 빼고, 첫 조회 카드는 자리 · 순위 · 표시 그대로 새 내용으로 바꾼다.
- 내용 바뀜(contentChanged)은 공고 정보(제목 · 기관 · 마감일 · 모집 형태 · 지원 금액 · 링크)가 달라졌거나 두 카드의
  내용 버전이 모두 있고 다를 때만 참이다. 적합도 · 추천 이유 · 가산점만 달라졌으면 거짓이고, 이전 자격 결과는 보지 않는다.
- 내용이 바뀐 막힌 공고는 추가 조회 결과와 같은 저장에서 풀린다. 실패한 추가 조회는 아무것도 풀지 않는다.
- 추가 조회의 어떤 오류든 X-C2-FAIL, 수집 상태 비정상은 E-C2-STALE — 실행은 살고 공고선택 · 사용자대기로 돌아가며
  기회를 돌려준다. 화면 3 · outputs · 20건 한도 · 공고 선택 후보 확인은 실패한 추가 조회를 없던 것으로 본다.
- 대체 경로가 마감 임박순이면 E-C2-EMBED 문구 끝에 " 마감 임박순으로 보여드립니다."를 붙인다.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

import pytest
from conftest import executed, make_app, pre_input, project_for, start_and_select

from sbrain.agents.stubs import StubScenario
from sbrain.flow.catalog import artifact_types, build_registry
from sbrain.flow.sbrain_flow import card_content_changed
from sbrain.models import AnnouncementCard, BonusItem
from sbrain.orchestrator import settings
from sbrain.orchestrator.errors import CommandError, message

TC2_KEYS = ("candidates", "collectionStatus", "filteredCount", "fallbackUsed", "fallbackMode")
DEADLINE_SUFFIX = " 마감 임박순으로 보여드립니다."


def pid(app, rid: str) -> str:
    return app.store.load_run(rid).project_id


def started(app) -> str:
    res = app.orchestrator.start_run("acc-1", pre_input(), project_id=project_for(app))
    assert res.ok, res
    return res.run_id


def more(app, rid: str) -> None:
    app.orchestrator.more_candidates(rid)
    app.orchestrator.advance(rid)


def select(app, rid: str, aid: str) -> None:
    app.orchestrator.select_announcement(rid, aid)
    app.orchestrator.advance(rid)


def screen3(app, rid: str):
    return app.orchestrator.screen(pid(app, rid), 3)


def ids(cards) -> list[str]:
    return [c.announcement_id for c in cards]


def by_id(cards) -> dict[str, AnnouncementCard]:
    return {c.announcement_id: c for c in cards}


def ctx_of(app, rid: str):
    return app.engine.open_context(app.store.load_run(rid))


def state(app, rid: str) -> tuple[str, str]:
    run = app.store.load_run(rid)
    return run.state.step, run.state.progress


def code_of(fn) -> str:
    with pytest.raises(CommandError) as e:
        fn()
    return e.value.code


def screen_values(s3) -> tuple:
    """추가 조회가 실패하면 그대로여야 하는 화면 3 값 (spec 4.2.3)."""
    return (s3.collection_status, s3.filtered_count, s3.fallback_used, s3.fallback_mode, s3.candidates,
            s3.more_candidates)


def spy_commits(app) -> list[dict]:
    """저장 묶음마다 산출물 키와 그때의 막힌 공고 목록을 남긴다."""
    seen: list[dict] = []
    original = app.store.commit

    def commit(run_id, owner, batch):
        run = batch.run
        seen.append({"keys": {v.key for v in batch.versions},
                     "blocked": list(run.blocked_announcement_ids) if run else None})
        return original(run_id, owner, batch)
    app.store.commit = commit
    return seen


# ── 등록 ─────────────────────────────────────────────
def test_more_lookup_rescued_and_result_artifacts_registered():
    reg = build_registry()
    failure = reg.get("T-C2").failure
    assert failure.rescue_segments == frozenset({"MORE"}) and not failure.resumable   # 첫 조회(PRE)는 그대로
    exact, _ = artifact_types(reg)
    assert exact["firstCandidates"] == exact["moreCandidates"] == list[AnnouncementCard]


# ── 내용 바뀜 비교 (spec 4.2.2) ──────────────────────────
CARD = AnnouncementCard(
    announcement_id="A01", title="공고", agency="기관", apply_end=date(2026, 10, 30), support_amount_max=100,
    fit_score=0.9, rank=1, display_type="card", match_reason="유사", source_notice="출처", original_url="u",
    apply_period_type="기간 있음", content_version="v1", bonus_score=1.0,
    bonus_items=[BonusItem(name="가점", points=1.0)])


@pytest.mark.parametrize("update, changed", [
    ({"title": "공고 (수정)"}, True),
    ({"agency": "다른 기관"}, True),
    ({"apply_end": None}, True),
    ({"apply_period_type": "상시·수시"}, True),
    ({"support_amount_max": None}, True),
    ({"original_url": "u2"}, True),
    ({"content_version": "v2"}, True),                                   # 정보는 같고 내용 버전만 다름
    ({"content_version": None}, False),                                  # 버전이 한쪽에만 — 정보만 본다
    ({"fit_score": 0.1, "match_reason": "다른 이유"}, False),            # 적합도 · 추천 이유만
    ({"bonus_score": 3.0, "bonus_items": []}, False),                    # 가산점만
    ({"source_notice": "다른 출처"}, False),
    ({"rank": 7, "display_type": "list"}, False),
])
def test_card_content_changed(update, changed):
    assert card_content_changed(CARD, CARD.model_copy(update=update)) is changed


def test_card_content_changed_ignores_version_missing_on_first_card():
    old = CARD.model_copy(update={"content_version": None})
    assert card_content_changed(old, CARD) is False
    assert card_content_changed(old, CARD.model_copy(update={"title": "바뀜"})) is True


# ── 겹침 · 갱신 ──────────────────────────────────────────
def test_overlap_removed_and_first_cards_refreshed_in_place(clock):
    sc = StubScenario(more_ids=["A15", "A03", "A11", "A10"], more_changes={"A03": {"적합도"}, "A10": {"정보"}})
    app = make_app(clock, sc)
    rid = started(app)
    before = screen3(app, rid).candidates
    more(app, rid)
    s3 = screen3(app, rid)
    assert ids(s3.more_candidates) == ["A15", "A11"]                              # 겹친 공고는 빼고 받은 순서 그대로
    assert ids(s3.candidates) == ids(before)                                     # 첫 조회 자리 그대로
    assert [(c.rank, c.display_type) for c in s3.candidates] == [(c.rank, c.display_type) for c in before]
    cards = by_id(s3.candidates)
    assert (cards["A03"].rank, cards["A03"].display_type) == (3, "card")         # 추가 조회의 순위(12) · 표시가 아니다
    assert (cards["A03"].fit_score, cards["A03"].match_reason, cards["A03"].content_changed) == (0.5, "유사 (갱신)", False)
    assert (cards["A10"].title, cards["A10"].content_changed) == ("공고 A10 (수정)", True)
    others = [c for c in s3.candidates if c.announcement_id not in ("A03", "A10")]
    assert others == [c for c in before if c.announcement_id not in ("A03", "A10")]   # 다시 나오지 않은 카드는 그대로
    out = app.orchestrator.outputs(pid(app, rid))
    assert (out.candidates, out.more_candidates) == (s3.candidates, s3.more_candidates)
    assert not s3.more_available                                                 # 추가 조회는 1회
    ctx = ctx_of(app, rid)
    assert ctx.get("candidates", 1) == before                                    # 첫 조회 버전은 덮어쓰지 않는다
    assert ids(ctx.get("candidates")) == ["A15", "A03", "A11", "A10"]           # T-C2 출력도 받은 그대로 남는다
    assert isinstance(ctx.get("moreCandidates")[0], AnnouncementCard)           # 저장소에서 다시 읽어도 카드 타입
    assert code_of(lambda: app.orchestrator.select_announcement(rid, "A12")) == "INVALID_ANNOUNCEMENT"
    select(app, rid, "A15")                                                      # 추가 후보에서 고른다
    assert state(app, rid) == ("계획서작성", "사용자대기")
    select(app, rid, "A03")                                                      # 겹쳤던 공고는 첫 조회 후보로 고른다
    assert app.store.load_run(rid).announcement_id == "A03"


def test_content_changed_when_info_or_version_changed(clock):
    sc = StubScenario(more_ids=["A01", "A02", "A11"], more_changes={"A01": {"정보"}, "A02": {"버전"}})
    app = make_app(clock, sc)
    rid = started(app)
    more(app, rid)
    cards = by_id(screen3(app, rid).candidates)
    assert (cards["A01"].title, cards["A01"].content_changed) == ("공고 A01 (수정)", True)
    assert (cards["A02"].title, cards["A02"].content_version, cards["A02"].content_changed) == (
        "공고 A02", "A02-v2", True)                                              # 정보는 같고 내용 버전만 바뀜
    assert cards["A03"].content_changed is False


def test_content_unchanged_for_fit_bonus_or_one_sided_version(clock, bonus_on):
    sc = StubScenario(no_version_ids={"A03"}, more_ids=["A01", "A02", "A03", "A04", "A05"],
                      more_changes={"A01": {"적합도"}, "A02": {"가산점"}, "A03": {"버전"}})
    app = make_app(clock, sc)
    rid = started(app)
    sc.no_version_ids = {"A04"}       # 첫 조회는 A03에만, 추가 조회는 A04에만 내용 버전이 없다
    more(app, rid)
    cards = by_id(screen3(app, rid).candidates)
    assert [cards[a].content_changed for a in ("A01", "A02", "A03", "A04", "A05")] == [False] * 5
    assert (cards["A01"].fit_score, cards["A01"].match_reason) == (0.5, "유사 (갱신)")    # 새 값은 보인다
    assert (cards["A02"].bonus_score, [b.name for b in cards["A02"].bonus_items]) == (2.0, ["가점 항목", "추가 가점"])
    assert (cards["A03"].content_version, cards["A04"].content_version) == ("A03-v2", None)


def test_web_cards_have_no_bonus_when_off_even_for_runs_stored_with_bonus(clock, monkeypatch):
    """가산점이 꺼져 있으면 웹으로 나가는 카드(화면 3 첫 조회 · 추가 조회, 결과 조회)는 모두 비어 있다 — 가산점 값이
    저장된 옛 실행 건도 같다. 저장된 값은 건드리지 않는다(켜면 다시 보인다). 카드 모양(키)은 그대로다."""
    monkeypatch.setattr(settings, "BONUS_ENABLED", True)          # 이번 변경 전처럼 가산점 값을 저장한 실행 건
    sc = StubScenario(more_ids=["A01", "A11"], more_changes={"A01": {"가산점"}})
    app = make_app(clock, sc)
    rid = started(app)
    assert screen3(app, rid).candidates[0].bonus_score == 1.0

    def blank(cards) -> bool:
        return bool(cards) and all((x.bonus_score, x.bonus_items) == (None, []) for x in cards)

    monkeypatch.setattr(settings, "BONUS_ENABLED", False)
    assert blank(screen3(app, rid).candidates)                                   # 첫 조회만 있는 실행 건
    assert blank(app.orchestrator.outputs(pid(app, rid)).candidates)
    monkeypatch.setattr(settings, "BONUS_ENABLED", True)
    more(app, rid)                                                               # 첫 조회 갱신 · 추가 조회도 가산점 값으로 저장
    on = screen3(app, rid)
    assert by_id(on.candidates)["A01"].bonus_score == 2.0 and on.more_candidates[0].bonus_score == 1.0

    monkeypatch.setattr(settings, "BONUS_ENABLED", False)
    s3, out = screen3(app, rid), app.orchestrator.outputs(pid(app, rid))
    for cards in (s3.candidates, s3.more_candidates, out.candidates, out.more_candidates):
        assert blank(cards)
    dumped = s3.dump()["candidates"][0]
    assert (dumped["bonusScore"], dumped["bonusItems"]) == (None, [])           # 키는 그대로, 값만 비어 있다
    monkeypatch.setattr(settings, "BONUS_ENABLED", True)
    assert by_id(screen3(app, rid).candidates)["A01"].bonus_score == 2.0          # 저장된 값은 그대로


def test_reappearing_unchanged_announcement_is_not_marked_whatever_its_gate_result(clock):
    """불통과 · 공고 없음 · 통과였던 공고가 내용 그대로 다시 나오면 내용 바뀜이 아니다 — 이전 자격 결과는 보지 않는다."""
    sc = StubScenario(gate_fail_ids={"A01"}, not_found_ids={"A02"}, more_ids=["A01", "A02", "A03", "A11"])
    app = make_app(clock, sc)
    rid = started(app)
    select(app, rid, "A01")                                                      # 불통과 → 막힘
    select(app, rid, "A02")                                                      # 공고 없음
    assert app.store.load_run(rid).notices[-1].code == "X-C2-GONE"
    select(app, rid, "A03")                                                      # 통과 → 계획서작성
    more(app, rid)
    assert state(app, rid) == ("공고선택", "사용자대기")
    s3 = screen3(app, rid)
    cards = by_id(s3.candidates)
    assert [cards[a].content_changed for a in ("A01", "A02", "A03")] == [False] * 3
    assert ids(s3.more_candidates) == ["A11"] and s3.blocked_announcement_ids == ["A01"]   # 내용 그대로면 막힌 채


# ── 막힌 공고 풀림 (spec 4.2.2 · 4.3.6) ───────────────────
@pytest.mark.parametrize("again", ["불통과", "통과"])
def test_changed_blocked_announcement_is_released_in_same_save(clock, again):
    sc = StubScenario(gate_fail_ids={"A01", "A02"}, more_ids=["A01", "A02", "A11"], more_changes={"A01": {"정보"}})
    app = make_app(clock, sc)
    rid = started(app)
    select(app, rid, "A01")
    select(app, rid, "A02")
    assert app.store.load_run(rid).blocked_announcement_ids == ["A01", "A02"]
    batches = spy_commits(app)
    more(app, rid)
    assert app.store.load_run(rid).blocked_announcement_ids == ["A02"]          # 내용 그대로인 A02는 막힌 채
    [saved] = [b for b in batches if "moreCandidates" in b["keys"]]
    assert {"candidates", "firstCandidates", "moreCandidates"} <= saved["keys"]
    assert saved["blocked"] == ["A02"]                                           # 추가 조회 결과와 같은 저장
    s3 = screen3(app, rid)
    assert s3.blocked_announcement_ids == ["A02"] and by_id(s3.candidates)["A01"].content_changed
    assert code_of(lambda: app.orchestrator.select_announcement(rid, "A02")) == "ANNOUNCEMENT_BLOCKED"
    if again == "통과":
        sc.gate_fail_ids.discard("A01")                                          # 바뀐 공고 조건으로 통과
    select(app, rid, "A01")                                                      # 풀린 공고는 다시 고르고 새로 판정한다
    assert executed(app, rid).count("G-01") == 3
    run = app.store.load_run(rid)
    if again == "불통과":
        assert (run.state.step, run.notices[-1].code) == ("공고선택", "E-G1-REJECT")
        assert run.blocked_announcement_ids == ["A02", "A01"]                    # 다시 막힌다
        assert code_of(lambda: app.orchestrator.select_announcement(rid, "A01")) == "ANNOUNCEMENT_BLOCKED"
        assert code_of(lambda: app.orchestrator.more_candidates(rid)) == "MORE_LIMIT"   # 추가 조회는 한 번뿐
    else:
        assert (run.state.step, run.state.progress, run.announcement_id) == ("계획서작성", "사용자대기", "A01")
        assert run.blocked_announcement_ids == ["A02"]


# ── 실패 (spec 4.2.3) ───────────────────────────────────
def fail_more(sc: StubScenario, app, kind: str) -> Callable[[], None]:
    """추가 조회만 실패하게 한다. 되돌리는 함수를 돌려준다."""
    if kind == "규격위반":
        stub = app.registry.get("T-C2").fn
        app.registry.bind("T-C2", lambda inp, tools: {"candidates": []} if inp.offset > 0 else stub(inp, tools))
        return lambda: app.registry.bind("T-C2", stub)
    if kind == "수집상태":
        sc.more_collection_status = "지연"
        return lambda: setattr(sc, "more_collection_status", None)
    sc.more_error = kind
    return lambda: setattr(sc, "more_error", None)


MORE_FAILURES = {"코드오류": "X-C2-FAIL", "재시도소진": "X-C2-FAIL", "규격위반": "X-C2-FAIL", "수집상태": "E-C2-STALE"}


@pytest.mark.parametrize("kind", list(MORE_FAILURES))
def test_failed_more_lookup_returns_to_selection_with_chance_back(clock, kind):
    # 첫 조회는 대체 경로(BM25단독) — 실패한 추가 조회의 값(수집 상태 · 대체 경로 등)이 화면에 섞이지 않는지 가린다
    sc = StubScenario(embed_fail=True, gate_fail_ids={"A01"}, more_ids=["A01", "A11"], more_changes={"A01": {"정보"}})
    app = make_app(clock, sc)
    rid = started(app)
    select(app, rid, "A01")                                                      # 불통과 → 막힘
    before = screen3(app, rid)
    assert (before.fallback_used, before.fallback_mode, before.blocked_announcement_ids) == (True, "BM25단독", ["A01"])
    out_before = app.orchestrator.outputs(pid(app, rid))
    restore = fail_more(sc, app, kind)
    more(app, rid)
    run = app.store.load_run(rid)
    code = MORE_FAILURES[kind]
    assert (run.state.step, run.state.progress) == ("공고선택", "사용자대기")
    assert (run.notices[-1].code, run.notices[-1].message) == (code, message(code))
    assert (run.more_used, run.failure_reason, run.queue, run.segment) == (False, None, [], None)
    assert "E-RUN-FAIL" not in [n.code for n in run.notices] and app.store.notifications(rid) == []
    assert run.blocked_announcement_ids == ["A01"]                               # 실패한 추가 조회는 풀지 않는다
    s3 = screen3(app, rid)
    assert s3.more_available and screen_values(s3) == screen_values(before)      # 화면 3은 추가 조회 전 그대로
    out = app.orchestrator.outputs(pid(app, rid))
    assert (out.candidates, out.more_candidates) == (out_before.candidates, [])
    ctx = ctx_of(app, rid)
    assert [ctx.version(k) for k in TC2_KEYS] == [1] * 5 and not ctx.has("moreCandidates")
    last = [r for r in app.store.executions(rid) if r.task_id == "T-C2"][-1]
    assert last.status == ("성공" if kind == "수집상태" else "실패")
    if kind == "수집상태":                                                        # 실패한 버전은 지우지 않고 포인터만 돌린다
        assert ctx.latest["collectionStatus"] == 2 and ctx.get("collectionStatus", 2) == "지연"
    restore()
    more(app, rid)                                                               # 돌려받은 기회로 다시
    s3 = screen3(app, rid)
    assert ids(s3.more_candidates) == ["A11"] and not s3.more_available
    assert s3.blocked_announcement_ids == [] and by_id(s3.candidates)["A01"].content_changed


@pytest.mark.parametrize("kind", list(MORE_FAILURES))
def test_failed_more_lookup_after_gate_pass_goes_to_selection(clock, kind):
    sc = StubScenario()
    app = make_app(clock, sc)
    rid = start_and_select(app)                                                  # A01 통과 → 계획서작성 · 사용자대기
    gate = ctx_of(app, rid)
    keys = ("selectedAnnouncement", "gateResult", "businessAgeYears")
    before = [gate.version(k) for k in keys]
    fail_more(sc, app, kind)
    more(app, rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.state.progress, run.notices[-1].code) == ("공고선택", "사용자대기", MORE_FAILURES[kind])
    assert run.announcement_id == "A01" and [ctx_of(app, rid).version(k) for k in keys] == before
    assert screen3(app, rid).more_available


def test_failed_lookup_cards_are_never_visible_selectable_or_counted(clock):
    """수집 상태가 비정상인데 카드를 돌려준 추가 조회 — 실패로 보고, 그 버전의 카드는 화면 · 결과 · 선택 · 한도 어디에도
    잡히지 않는다. 막힌 공고의 바뀐 카드가 있어도 풀지 않는다."""
    app = make_app(clock, StubScenario(gate_fail_ids={"A01"}))
    rid = started(app)
    select(app, rid, "A01")
    first = screen3(app, rid).candidates
    stub = app.registry.get("T-C2").fn

    def abnormal(inp, tools):
        out = stub(inp, tools)
        if inp.offset == 0:
            return out
        changed = first[0].model_copy(update={"title": "바뀐 제목", "rank": 11, "display_type": "list"})
        cards = [changed] + [c.model_copy(update={"announcement_id": f"X{i:02d}"}) for i, c in
                             enumerate(out.candidates[1:], 2)]
        return out.model_copy(update={"candidates": cards, "collection_status": "지연"})
    app.registry.bind("T-C2", abnormal)
    more(app, rid)
    run = app.store.load_run(rid)
    assert (run.state.step, run.notices[-1].code, run.more_used) == ("공고선택", "E-C2-STALE", False)
    assert run.blocked_announcement_ids == ["A01"]
    s3 = screen3(app, rid)
    assert (s3.candidates, s3.more_candidates, s3.more_available) == (first, [], True)
    assert app.orchestrator.outputs(pid(app, rid)).more_candidates == []
    assert code_of(lambda: app.orchestrator.select_announcement(rid, "X02")) == "INVALID_ANNOUNCEMENT"
    ctx = ctx_of(app, rid)
    assert len(ctx.get("candidates", 2)) == 10 and ctx.version("candidates") == 1   # 실패한 버전은 남는다
    app.registry.bind("T-C2", stub)
    more(app, rid)                                                               # 실패한 10건은 20건 한도에 세지 않는다
    s3 = screen3(app, rid)
    assert ids(s3.more_candidates) == [f"A{i}" for i in range(11, 21)] and s3.candidates == first
    assert code_of(lambda: app.orchestrator.select_announcement(rid, "X02")) == "INVALID_ANNOUNCEMENT"


# ── 마감 임박순 안내 (spec 4.1.3) ─────────────────────────
def test_deadline_fallback_notice_gets_suffix(clock):
    app = make_app(clock, StubScenario(deadline_fallback=True))
    res = app.orchestrator.start_run("acc-1", pre_input(), project_id=project_for(app))
    expected = ("E-C2-EMBED", message("E-C2-EMBED") + DEADLINE_SUFFIX)
    assert res.ok and [(n.code, n.message) for n in res.notices] == [expected]   # 첫 조회
    s3 = screen3(app, res.run_id)
    assert (s3.fallback_used, s3.fallback_mode) == (True, "마감임박순") and {c.fit_score for c in s3.candidates} == {0.0}
    more(app, res.run_id)
    notices = app.store.load_run(res.run_id).notices
    assert [(n.code, n.message) for n in notices] == [expected, expected]        # 추가 조회
    other = make_app(clock, StubScenario(embed_fail=True))                       # 다른 대체 경로에는 붙이지 않는다
    res = other.orchestrator.start_run("acc-1", pre_input(), project_id=project_for(other))
    assert [(n.code, n.message) for n in res.notices] == [("E-C2-EMBED", message("E-C2-EMBED"))]
