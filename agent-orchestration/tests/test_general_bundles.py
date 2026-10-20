"""새 재작성 묶음 '일반현황 · 개요' · '그림' (스위치 — 2026-10-16 배포부터 코드에서 켬, flow/rework_map.py GENERAL_BUNDLES_ENABLED).

- 테스트는 꺼진 값으로 돈다(conftest 자동 픽스처 — 코드 값은 CODE_SWITCHES로 확인).
- 꺼져 있으면 묶음 4개, 일반현황 · 개요 · 그림 항목은 태그 · 묶음 없음, 그 이름의 재작성 요청은 INVALID_ORDER.
- 켜면(테스트에서는 monkeypatch로 켜고 끝나면 되돌린다): 문서층 묶음 6개(일반현황 · 개요, 그림, 문제인식, 실현가능성, 성장전략,
  팀 구성), 태그 0-1 · 0-2(가장 긴 앞부분 — 2.3.6이 2.3을 이긴다), 새로 고른 양식 · 계획서 항목에 태그, 재작성 요청 접수,
  그림 묶음은 T-W2만 · 일반현황 · 개요는 T-W1만 다시 만든다, 판정의 '묶음 모두' 후보에 그림이 없다, 그림 fail이면 그림 후보.
- 표를 읽는 곳은 부를 때마다 그때의 표 · 스위치를 본다(켠 뒤 이미 있던 실행 건에도 바로 적용, 끄면 목록 · 접수에서 빠짐).
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

import pytest
from conftest import CODE_SWITCHES, make_app, to_screen6
from flow_helpers import code_of, ctx_of, cycle_steps, pid, rework, usage_of

from sbrain.agents.form_defaults import select_form
from sbrain.agents.stubs import StubScenario
from sbrain.agents.supervisor import judge
from sbrain.flow import rework_map
from sbrain.flow.sbrain_flow import bundle_orders
from sbrain.models import SectionResult

OLD = ("문제인식", "실현가능성", "성장전략", "팀 구성")
GENERAL, FIGURE = "일반현황 · 개요", "그림"
NEW = (GENERAL, FIGURE, *OLD)
IMAGE = "3.3.6"


@pytest.fixture
def general_on(monkeypatch):
    """새 묶음 스위치를 이 테스트 동안만 켠다 (끝나면 monkeypatch가 되돌린다)."""
    monkeypatch.setattr(rework_map, "GENERAL_BUNDLES_ENABLED", True)


def sr(code: str, kind: str = "section", status: str = "fail") -> SectionResult:
    return SectionResult(section_code=code, content_type=kind, status=status, score=0.0, verified_ref="planDoc@1",
                         issues=[f"{code} 문제"] if status == "fail" else [],
                         warnings=[f"{code} 경고"] if status == "warning" else [])


# ── 코드 값 = 켬 (배포 값) ───────────────────────────────
def test_switch_is_on_in_code():
    assert CODE_SWITCHES["GENERAL_BUNDLES_ENABLED"] is True


# ── 스위치 꺼짐 = 묶음 4개 ───────────────────────────────
def test_switch_off_nothing_changes():
    assert rework_map.GENERAL_BUNDLES_ENABLED is False                         # conftest가 끈 값
    assert rework_map.document_bundles() == OLD
    for code in ("2.1.1", "2.2.2", "2.3.5", "2.3.6", "3.1.1", "3.3.6"):
        assert rework_map.section_tag_bundle(code) is None
    assert rework_map.bundle_layer(GENERAL) is None and rework_map.bundle_layer(FIGURE) is None
    assert rework_map.bundle_layer("문제인식") == "document" and rework_map.bundle_layer("실행 파일") == "artifact"
    assert rework_map.every_bundle_candidates() == OLD
    tags = select_form("법인").form_spec.section_tags
    assert "0-1" not in tags and "0-2" not in tags


def test_switch_off_low_score_candidates_are_the_four_bundles():
    orders = judge.doc_candidates([], 50.0, 80)
    assert [o.targets[0] for o in orders] == list(OLD)


# ── 스위치 켬 ────────────────────────────────────────────
def test_switch_on_six_bundles_tags_and_longest_prefix(general_on):
    assert rework_map.document_bundles() == NEW
    assert rework_map.section_tag_bundle("2.1.1") == ("0-1", GENERAL)
    assert rework_map.section_tag_bundle("2.2.2") == ("0-1", GENERAL)
    assert rework_map.section_tag_bundle("2.3.5") == ("0-1", GENERAL)
    assert rework_map.section_tag_bundle("3.3.1") == ("0-1", GENERAL)
    assert rework_map.section_tag_bundle("2.3.6") == ("0-2", FIGURE)          # 2.3.6이 2.3을 이긴다
    assert rework_map.section_tag_bundle("3.3.6") == ("0-2", FIGURE)
    assert rework_map.section_tag_bundle("2.4.1") == ("1-1", "문제인식")       # 나머지는 지금과 같음
    assert rework_map.section_tag_bundle("3.7.4") == ("4-1", "팀 구성")
    assert all(rework_map.bundle_layer(b) == "document" for b in NEW)
    assert rework_map.every_bundle_candidates() == (GENERAL, *OLD)            # '묶음 모두'에서 그림 제외


def test_switch_on_new_forms_get_new_tags(general_on):
    form = select_form("예비창업자").form_spec
    tags = dict(zip(form.section_codes, form.section_tags))
    assert tags["2.1.1"] == tags["2.2.1"] == tags["2.3.5"] == "0-1"
    assert tags["2.3.6"] == "0-2" and tags["2.4.1"] == "1-1"
    early = select_form("법인").form_spec
    assert dict(zip(early.section_codes, early.section_tags))["3.3.6"] == "0-2"
    assert rework_map.bundle_sections(FIGURE, early.section_codes) == ["3.3.6"]


def test_switch_on_bundle_orders_pick_kind_tasks(general_on):
    form = select_form("법인").form_spec
    assert list(bundle_orders([FIGURE], [], form)) == ["T-W2"]
    assert list(bundle_orders([GENERAL], [], form)) == ["T-W1"]
    assert list(bundle_orders([GENERAL, FIGURE, "실현가능성"], [], form)) == ["T-W1", "T-W2", "T-W3"]


def test_switch_on_candidates_figure_only_when_flagged(general_on):
    # 그림 항목 fail → 그림 후보(T-W2), 일반현황 항목 fail → 일반현황 · 개요 후보(T-W1)
    orders = judge.doc_candidates([sr("3.1.1"), sr(IMAGE, "image"), sr("3.4.1", status="pass")], 90.0, 80)
    assert [(o.task_id, o.targets) for o in orders] == [("T-W1", [GENERAL]), ("T-W2", [FIGURE])]
    # 점수 미달 · 후보 없음 → 묶음 모두, 그림은 빼고
    low = judge.doc_candidates([sr(IMAGE, "image", "pass"), sr("3.1.1", status="pass")], 50.0, 80)
    assert [o.targets[0] for o in low] == [GENERAL, *OLD]
    assert all(o.reason == rework_map.REWORK_DEFAULT_REASON for o in low)


# ── 흐름 (스텁 앱 — 법인 3.1.1 ~ 3.7.4) ─────────────────────
def test_switch_on_figure_rework_remakes_only_image_with_tw2(clock, general_on):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    plan = ctx_of(app, rid).get("planDoc")
    assert {s.section_code: s.tag for s in plan.sections}[IMAGE] == "0-2"     # 새 계획서에 새 태그
    usage = [u.bundle_id for u in app.orchestrator.outputs(pid(app, rid)).rework_usage]
    assert usage[:6] == list(NEW)
    [acc] = rework(app, clock, rid, FIGURE)
    assert cycle_steps(app, rid, acc.cycle_id) == ["T-W2", "M-1", "T-V1", "G-02a"]
    assert usage_of(app, rid) == {FIGURE: (1, 0)}


def test_switch_on_general_rework_remakes_general_items_with_tw1(clock, general_on):
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0]))
    rid = to_screen6(app)
    [acc] = rework(app, clock, rid, GENERAL)
    assert cycle_steps(app, rid, acc.cycle_id) == ["T-W1", "M-1", "T-V1", "G-02a"]
    latest = app.store.get_latest_versions(rid)["T-W1.reworkInput"]
    targets = list(ctx_of(app, rid).get("T-W1.reworkInput", latest).target_items)
    assert targets == ["3.1.1", "3.1.2", "3.1.3", "3.1.4", "3.1.5", "3.1.6", "3.2.1", "3.2.2",
                       "3.3.1", "3.3.2", "3.3.3", "3.3.4", "3.3.5"]
    assert usage_of(app, rid) == {GENERAL: (1, 0)}


def test_switch_read_at_call_time_for_existing_runs(clock, monkeypatch):
    # 꺼진 채 만든 실행 건 — 그 이름은 받지 않는다. 켜면 바로 받는다(이미 만든 계획서 태그는 그대로). 다시 끄면 목록 · 접수에서 빠진다
    app = make_app(clock, StubScenario(doc_scores=[52.0, 60.0, 60.0]))
    rid = to_screen6(app)
    assert code_of(lambda: app.orchestrator.request_rework_for_project(pid(app, rid), FIGURE)) == "INVALID_ORDER"
    monkeypatch.setattr(rework_map, "GENERAL_BUNDLES_ENABLED", True)
    assert {s.section_code: s.tag for s in ctx_of(app, rid).get("planDoc").sections}[IMAGE] is None
    [acc] = rework(app, clock, rid, FIGURE)
    assert cycle_steps(app, rid, acc.cycle_id) == ["T-W2", "M-1", "T-V1", "G-02a"]
    monkeypatch.setattr(rework_map, "GENERAL_BUNDLES_ENABLED", False)
    assert [u.bundle_id for u in app.orchestrator.outputs(pid(app, rid)).rework_usage][:4] == list(OLD)
    assert FIGURE not in [u.bundle_id for u in app.orchestrator.outputs(pid(app, rid)).rework_usage]
    assert code_of(lambda: app.orchestrator.request_rework_for_project(pid(app, rid), FIGURE)) == "INVALID_ORDER"
    assert usage_of(app, rid) == {FIGURE: (1, 0)}                                 # 이미 쓴 기록은 지우지 않는다
