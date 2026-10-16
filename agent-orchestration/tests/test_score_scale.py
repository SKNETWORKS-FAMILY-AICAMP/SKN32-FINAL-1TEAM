"""산출물층 환산 규칙 — 환산 함수 · 코드 점검 항목 줄 · 점수 보고서 환산 칸 도움 함수,
재작성 전후 비교 · 관리자 조회 · 통계 줄이 그 실행 건 설정 사본 배점으로 환산하는지.

흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

import json

import pytest
from conftest import make_app, to_screen8
from flow_helpers import ctx_of, records_of_task, rework

from sbrain.agents.stubs import StubScenario
from sbrain.flow import reads
from sbrain.flow.log_stats import run_stats_row
from sbrain.flow.retention import gather_run_stats
from sbrain.flow.score_scale import (
    RAW_MAX, ScoreMaxes, display_score, scale_artifact, scale_artifact_scores, scale_code_check_items, scale_detail,
    scale_raw, score_maxes, scaled_report_fields,
)
from sbrain.models import ArtifactScore, CodeCheck, CodeCheckResult, DocScore, FeatureMatchResult, ScoreReport
from sbrain.orchestrator.settings import ScoringSettings, Settings

HTML_WEIGHTS = [3, 2, 2, 2, 1, 2, 2, 1]
SKEWED = ScoringSettings(code_check_max=25, feature_match_max=5)     # C = 25 · P = 5 (D = 70)


def skewed_settings(**scoring) -> Settings:
    return Settings(scoring=ScoringSettings(**{"code_check_max": 25, "feature_match_max": 5, **scoring}))


def checks(earned: list[float | None], *, weights=HTML_WEIGHTS, applicable=None, passed=None,
           detail: str = "{e}/{w}점 — 근거 {n}") -> list[CodeCheck]:
    out = []
    for i, (w, e) in enumerate(zip(weights, earned)):
        app = True if applicable is None else applicable[i]
        ok = (e == w) if passed is None else passed[i]
        text = detail.format(e=0 if e is None else f"{e:g}", w=f"{w:g}", n=i + 1) if app else "해당 없음 — 이유"
        out.append(CodeCheck(no=i + 1, name=f"c{i + 1}", weight=w, passed=ok, detail=text, earned=e, applicable=app,
                             defect_sources=["infographic"] if i == 1 else []))
    return out


def cents(x: float) -> int:
    return round(x * 100)


def assert_rows_consistent(rows: list[CodeCheck], code_max: float, layer: float) -> None:
    assert sum(cents(r.weight) for r in rows) == cents(code_max)            # 환산 배점 합 = C
    assert sum(cents(r.earned) for r in rows) == cents(layer)               # 환산 점수 합 = 층 값
    assert all(0 <= r.earned <= r.weight for r in rows)                     # 환산 점수 ≤ 환산 배점
    assert all(r.weight == round(r.weight, 2) and r.earned == round(r.earned, 2) for r in rows)


def artifact(code_total: float, feature: float, rows: list[CodeCheck] | None = None,
             gate: list[str] | None = None) -> ArtifactScore:
    cc = CodeCheckResult(total=code_total, checks=rows or checks([3, 2, 2, 2, 1, 2, 2, 1]), gate_failures=gate or [])
    fm = FeatureMatchResult(score=feature, missing_features=[], extra_features=[], findings=[], judged_by="htmlParse")
    return ArtifactScore(total=0 if gate else code_total + feature, code_check=cc, feature_match=fm)


# ── 배점 읽기 (D · C · P) ───────────────────────────────
def test_score_maxes_from_settings_snapshot_and_old_snapshot():
    assert score_maxes(Settings()) == ScoreMaxes(doc=70, code_check=15, feature_match=15)
    assert score_maxes(None) == score_maxes({}) == ScoreMaxes(70, 15, 15)
    s = skewed_settings(doc_layer_max=60)
    for source in (s, s.scoring, s.dump()):
        assert score_maxes(source) == ScoreMaxes(60, 25, 5)
    old = Settings().dump()
    old["scoring"].pop("codeCheckMax")
    old["scoring"].pop("featureMatchMax")
    assert score_maxes(old) == ScoreMaxes(70, 15, 15)                       # 칸이 없는 옛 사본 → 15 · 15
    assert score_maxes({"scoring": {}}) == ScoreMaxes(70, 15, 15)
    zero = score_maxes({"scoring": {"docLayerMax": 0, "codeCheckMax": 0, "featureMatchMax": 0}})
    assert zero == ScoreMaxes(0, 0, 0)                                     # 0은 기본값으로 바꾸지 않는다
    m = ScoreMaxes(60, 25, 5)
    assert m.artifact == 30 and m.as_stats() == {"docScore": 60.0, "codeCheck": 25.0, "featureMatch": 5.0}


# ── 층 환산 ────────────────────────────────────────────
def test_layer_scaling_formula_and_rounding():
    assert RAW_MAX == 15
    assert scale_raw(12, 25) == 20.0 and scale_raw(9, 5) == 3.0 and scale_raw(15, 15) == 15.0
    assert scale_raw(10, 7) == 4.67 and scale_raw(10, 8) == 5.33              # 소수 둘째 자리 (잠정)
    got = scale_artifact_scores(12, 9, ScoreMaxes(70, 25, 5))
    assert (got.code_check_score, got.feature_match_score, got.artifact_layer_score) == (20.0, 3.0, 23.0)
    got = scale_artifact_scores(10, 10, ScoreMaxes(70, 7, 8))
    assert (got.code_check_score, got.feature_match_score, got.artifact_layer_score) == (4.67, 5.33, 10.0)
    none = scale_artifact_scores(None, None, ScoreMaxes(70, 25, 5))
    assert (none.code_check_score, none.feature_match_score, none.artifact_layer_score) == (None, None, None)
    got = scale_artifact(artifact(12, 9), ScoreMaxes(70, 25, 5))
    assert (got.code_check_score, got.feature_match_score, got.artifact_layer_score) == (20.0, 3.0, 23.0)


def test_gate_failure_zeroes_every_scaled_value():
    art = artifact(12, 9, gate=["entry"])                                   # 원점수가 남아 있어도 칸으로 판단
    got = scale_artifact(art, ScoreMaxes(70, 25, 5))
    assert (got.code_check_score, got.feature_match_score, got.artifact_layer_score) == (0, 0, 0)
    fields = scaled_report_fields(ScoreMaxes(70, 25, 5), art)
    assert fields["artifact_layer_score"] == 0 and fields["code_check_score"] == 0
    assert all(r.earned == 0 for r in fields["code_check_items"])
    assert sum(cents(r.weight) for r in fields["code_check_items"]) == cents(25)   # 배점은 그대로 나눠 싣는다


def test_zero_maxes_stay_zero_without_division_error():
    got = scale_artifact_scores(12, 9, ScoreMaxes(0, 0, 0))
    assert (got.code_check_score, got.feature_match_score, got.artifact_layer_score) == (0, 0, 0)
    got = scale_artifact_scores(12, 9, ScoreMaxes(70, 0, 5))
    assert (got.code_check_score, got.feature_match_score, got.artifact_layer_score) == (0, 3.0, 3.0)
    rows = scale_code_check_items(checks([3, 2, 2, 2, 1, 2, 2, 1]), 0, layer_score=0)
    assert all(r.weight == 0 and r.earned == 0 for r in rows)
    assert display_score(50, 0) == 0                                        # 분모 0 → 표시 점수 0
    assert display_score(56, 70) == 80.0 and display_score(52, 70) == 74.3
    assert scaled_report_fields(ScoreMaxes(0, 0, 0))["doc_layer_max"] == 0


# ── 코드 점검 항목 줄 ───────────────────────────────────
def test_item_rows_rescaled_and_rounding_difference_collected():
    src = checks([2, 2, 2, 2, 1, 2, 2, 1])                                   # 원점수 14 / 15
    layer = scale_raw(14, 7)
    rows = scale_code_check_items(src, 7, layer_score=layer)
    assert_rows_consistent(rows, 7, layer)
    for r, s in zip(rows, src):
        assert (r.no, r.name, r.passed, r.applicable, r.defect_sources) == (
            s.no, s.name, s.passed, s.applicable, s.defect_sources)
        assert r.detail == f"{scale_detail_number(r.earned)}/{scale_detail_number(r.weight)}점 — 근거 {r.no}"
    assert src[0].detail == "2/3점 — 근거 1" and src[0].weight == 3          # 원래 항목은 그대로


def scale_detail_number(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def test_detail_prefix_replaced_only_when_present():
    assert scale_detail("2/3점 — 근거", 4.67, 7) == "4.67/7점 — 근거"
    assert scale_detail("1.5/3점 — 부분 근거", 2.5, 5) == "2.5/5점 — 부분 근거"
    assert scale_detail("0/1점 — 없음", 0, 0.47) == "0/0.47점 — 없음"
    assert scale_detail("", 1, 2) == ""                                       # 앞 숫자 패턴이 없으면 그대로
    assert scale_detail("통과 필수 조건 실패로 검사 생략: entry", 0, 1) == "통과 필수 조건 실패로 검사 생략: entry"
    assert scale_detail("해당 없음 — 이유", 0, 0) == "해당 없음 — 이유"


def test_not_applicable_rows_are_zero_and_others_share_the_max():
    applicable = [True, False, True, True, True, True, True, True]
    src = checks([3, 0, 2, 2, 1, 2, 2, 1], applicable=applicable, passed=[True] * 8)
    rows = scale_code_check_items(src, 15, layer_score=15)                   # 나머지 13점 만점 → 15 환산
    assert (rows[1].weight, rows[1].earned, rows[1].detail) == (0, 0, "해당 없음 — 이유")
    assert rows[1].applicable is False and rows[1].passed is True
    assert rows[0].weight == pytest.approx(15 * 3 / 13, abs=0.011)
    assert_rows_consistent(rows, 15, 15)


def test_old_rows_without_earned_use_pass_fail():
    src = checks([None] * 8, passed=[True, False, True, True, False, True, True, True])
    rows = scale_code_check_items(src, 25)                                   # 층 값을 주지 않으면 항목에서 계산
    earned_raw = 15 - 2 - 1
    assert_rows_consistent(rows, 25, scale_raw(earned_raw, 25))
    assert rows[1].earned == 0 and rows[4].earned == 0
    assert rows[0].earned == pytest.approx(25 * 3 / 15, abs=0.011)


def test_all_rows_not_applicable_gives_all_zero():
    src = checks([0] * 8, applicable=[False] * 8, passed=[True] * 8)
    rows = scale_code_check_items(src, 15, layer_score=0)
    assert all(r.weight == 0 and r.earned == 0 and r.detail == "해당 없음 — 이유" for r in rows)


@pytest.mark.parametrize("code_max", [7, 11, 13, 25, 29.99])
def test_rounding_keeps_sums_for_awkward_maxes(code_max):
    src = checks([3, 1, 2, 0.5, 1, 2, 1.5, 1], passed=[True, False, True, False, True, True, False, True])
    raw = sum(r.earned for r in src)
    layer = scale_raw(raw, code_max)
    assert_rows_consistent(scale_code_check_items(src, code_max, layer_score=layer), code_max, layer)


# ── 점수 보고서 환산 칸 도움 함수 ───────────────────────
def test_report_fields_document_layer_only():
    assert scaled_report_fields(ScoreMaxes(60, 25, 5)) == {"doc_layer_max": 60}


def test_report_fields_artifact_layer():
    art = artifact(14, 9, rows=checks([2, 2, 2, 2, 1, 2, 2, 1]))
    fields = scaled_report_fields(ScoreMaxes(70, 25, 5), art)
    assert {k: v for k, v in fields.items() if k != "code_check_items"} == {
        "doc_layer_max": 70, "code_check_score": 23.33, "code_check_max": 25, "feature_match_score": 3.0,
        "feature_match_max": 5, "artifact_layer_score": 26.33, "artifact_layer_max": 30}
    assert_rows_consistent(fields["code_check_items"], 25, 23.33)
    assert len(fields["code_check_items"]) == 8
    report = ScoreReport(doc_score=DocScore(total=50, items=[]), artifact_score=art, total=76.3, threshold=80,
                         passed=False, failed_task_ids=[], rework_orders=[], rework_usage=[], phase="overall",
                         display_score=76.3, rework_diff=[], comparisons=[], notices=[], settings_snapshot={},
                         rubric_version="r1", **fields)
    assert report.artifact_score.code_check.total == 14                       # 검증-2 원점수는 그대로
    assert report.dump()["codeCheckItems"][0]["detail"].endswith("점 — 근거 1")


# ── 재작성 전후 비교 (CYCLE-END) ─────────────────────────
@pytest.mark.parametrize("first,second,kept", [
    ((12.0, 0.0), (6.0, 10.0), "전"),       # 원점수로는 '후'가 높지만 환산(C 25 · P 5)하면 '전'
    ((6.0, 10.0), (12.0, 0.0), "후"),       # 반대
])
def test_cycle_end_compares_scaled_artifact_layer(clock, first, second, kept):
    app = make_app(clock, StubScenario(art_scores=[first, second]), settings=skewed_settings())
    rid = to_screen8(app)
    rework(app, clock, rid, "실행 파일")
    [comp] = [x for x in app.store.comparisons(rid)]
    ctx = ctx_of(app, rid)
    maxes = ScoreMaxes(70, 25, 5)
    before, after = ctx.get("artifactScore", 1), ctx.get("artifactScore", 2)
    raw_before, raw_after = before.total, after.total
    assert (raw_before < raw_after) == (kept == "전")                        # 원점수로 비교하면 반대 결과
    assert comp.basis == "artifact"
    assert comp.before_score == scale_artifact(before, maxes).artifact_layer_score
    assert comp.after_score == scale_artifact(after, maxes).artifact_layer_score
    assert comp.kept == kept
    assert app.store.load_run(rid).last_rework.kept == kept


# ── 관리자 조회 · 통계 줄 ─────────────────────────
def scaled_run(clock):
    """C 25 · P 5로 시작한 실행 건 — 산출물층 재작성 한 번(첫 채점 · 재작성 뒤 채점) 뒤 지금 설정을 다르게 바꾼다."""
    app = make_app(clock, StubScenario(art_scores=[(12.0, 3.0), (14.0, 9.0)]), settings=skewed_settings())
    rid = to_screen8(app)
    rework(app, clock, rid, "실행 파일")
    app.settings.update(Settings(scoring=ScoringSettings(doc_layer_max=50, code_check_max=10, feature_match_max=20)))
    return app, rid


def tv2_scaled(app, rid) -> list[tuple[float, float, float]]:
    maxes = ScoreMaxes(70, 25, 5)
    out = []
    for r in records_of_task(app, rid, "T-V2"):
        m = r.output_meta
        s = scale_artifact_scores(m.code_check_score, m.feature_match_score, maxes)
        out.append((s.code_check_score, s.feature_match_score, s.artifact_layer_score))
    return out


def test_admin_runs_scale_with_run_snapshot(clock):
    app, rid = scaled_run(clock)
    [row] = [a for a in reads.admin_runs(app.orchestrator, limit=None) if a.run_id == rid]
    current = ctx_of(app, rid).get("artifactScore")
    expected = scale_artifact(current, ScoreMaxes(70, 25, 5)).artifact_layer_score
    assert row.artifact_score == expected and expected != current.total
    assert (row.doc_max, row.artifact_max) == (70, 30)                     # 지금 설정(50 · 30)이 아니라 그 실행 건 배점
    assert row.total_score == ctx_of(app, rid).get("scoreReport.overall").total


def test_admin_score_history_scales_with_run_snapshot(clock):
    app, rid = scaled_run(clock)
    h = reads.admin_score_history(app.orchestrator, app.store.load_run(rid).project_id)
    scaled = tv2_scaled(app, rid)
    assert [e.score for e in reversed(h.code_check)] == [s[0] for s in scaled]
    assert [e.score for e in reversed(h.feature_match)] == [s[1] for s in scaled]
    assert [e.score for e in h.doc_score] == [r.output_meta.score for r in reversed(records_of_task(app, rid, "T-V1"))]
    assert (h.doc_max, h.code_check_max, h.feature_match_max) == (70, 25, 5)


def test_admin_summary_layer_changes_use_scaled_scores(clock):
    app, rid = scaled_run(clock)
    s = reads.admin_summary(app.orchestrator)
    scaled = tv2_scaled(app, rid)
    changes = {x.layer: x for x in s.layer_changes}
    assert (changes["codeCheck"].first_avg, changes["codeCheck"].after_avg) == (
        round(scaled[0][0], 1), round(scaled[-1][0], 1))
    assert (changes["featureMatch"].first_avg, changes["featureMatch"].after_avg) == (
        round(scaled[0][1], 1), round(scaled[-1][1], 1))


def test_stats_row_scales_and_carries_max_scores(clock):
    app, rid = scaled_run(clock)
    run = app.store.load_run(rid)
    assert app.store.acquire(rid, "stats", 60)
    row = gather_run_stats(app.store, run, reason="12개월")
    app.store.release(rid, "stats")
    data = row.data
    assert data["maxScores"] == {"docScore": 70.0, "codeCheck": 25.0, "featureMatch": 5.0}
    scaled = tv2_scaled(app, rid)
    assert [e["score"] for e in data["scores"]["codeCheck"]] == [s[0] for s in scaled]
    assert [e["score"] for e in data["scores"]["featureMatch"]] == [s[1] for s in scaled]
    assert [e["score"] for e in data["scores"]["artifactScore"]] == [s[2] for s in scaled]
    [admin] = [a for a in reads.admin_runs(app.orchestrator, limit=None) if a.run_id == rid]
    assert data["finalScores"]["artifact"] == admin.artifact_score
    text = repr(row) + json.dumps(data, ensure_ascii=False)
    for ident in (rid, run.project_id, run.account_id):
        assert ident not in text
    # 같은 실행 건을 지금 설정과 상관없이 같은 값으로 다시 만든다 (기록을 지운 뒤 · 설정이 바뀐 뒤에도 같은 결과)
    again = run_stats_row(run, _records(app, rid), pointers=app.store.get_pointers(rid), reason="12개월", part=1)
    assert again.data == data


def _records(app, rid):
    from sbrain.flow.log_stats import RunRecords
    s = app.store
    return RunRecords(executions=s.executions(rid), calls=s.call_logs(rid), events=s.events(rid),
                      feedback=s.feedback(rid), comparisons=s.comparisons(rid), pointer_events=s.pointer_events(rid))
