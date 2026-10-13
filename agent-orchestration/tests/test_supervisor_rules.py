"""조율 규칙 단계 실구현 (impl-verify2 spec 4.7 ~ 4.10 D12 · D14).

- 판정 G-02a · G-02b(agents/supervisor/judge.py): 총점 = 문서층 + 산출물층 환산, 점수 보고서 환산 칸, artifactScore 원점수 그대로,
  E-G2-UNREACHABLE 두 문구(쓰지 않은 묶음의 기회는 설정 사본 rework.perBundle, 쓴 묶음은 reworkUsage.remaining), 통과 필수
  조건 실패 → 환산 0, reworkDiff 산출물층 요약 = 환산 값 / C + P, 배점 0(D = 0 → 표시 점수 0), 산출물 종류는 입력 category,
  코드 · 대조 배점이 다르면 다음 동작이 환산 총점으로 갈림
- 안내 문서 G-04(readme.py): 템플릿 두 종류 낱말 · 빈 슬롯 기본 문구 · 파일 이름(원페이지 한 번) · 마크다운 · files로 넣음 ·
  산출물 본문 없음, 자체 검사
- 조립: 스텁 조립은 실구현을 감싸고(실패 흉내 raise_in · check_fail_times), 워커 조립은 실구현 그대로
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

import pytest
from conftest import make_app, to_screen6, to_screen8
from flow_helpers import ctx_of
from worker_helpers import projects

from sbrain.agents.stubs import FakeLLM, StubScenario, bind_stubs, make_announcement
from sbrain.agents.supervisor import RULE_TASKS, RULES, judge, merge, readme
from sbrain.bootstrap import build_app
from sbrain.contracts import tasks as c
from sbrain.flow.catalog import build_registry
from sbrain.flow.rework_map import DOCUMENT_BUNDLES
from sbrain.flow.score_scale import ScoreMaxes, scale_artifact
from sbrain.models import (
    Announcement, ArtifactScore, BundleUsage, CheckResult, CodeCheck, CodeCheckResult, DocScore, FeatureMatchResult,
    FileRef, Infographic, ItemSpec, Prototype, SectionResult,
)
from sbrain.models.clock import kst_today, utc_now
from sbrain.orchestrator.errors import UNREACHABLE_NO_DOC_CHANCE, message
from sbrain.orchestrator.settings import ReworkSettings, ScoringSettings, Settings

HTML_WEIGHTS = [3, 2, 2, 2, 1, 2, 2, 1]
FIRST = message("E-G2-UNREACHABLE")
FEATURES = ["회원 등록·조회", "수업 예약"]


# ── 도움 ────────────────────────────────────────────────
def snapshot(**scoring) -> dict:
    return Settings(scoring=ScoringSettings(**scoring)).dump()


SKEWED = snapshot(code_check_max=25, feature_match_max=5)          # C = 25 · P = 5 (D = 70)


def artifact(code_total: float, feature: float, *, gate: list[str] | None = None) -> ArtifactScore:
    rows = [CodeCheck(no=i + 1, name=f"c{i + 1}", weight=w, passed=True, detail="", earned=w, applicable=True)
            for i, w in enumerate(HTML_WEIGHTS)]
    if code_total < 15 and not gate:   # 앞 칸부터 불통과로 깎는다 (규칙 확인용 — 합만 맞춘다)
        deficit = 15 - code_total
        for i, row in enumerate(rows):
            take = min(row.weight, deficit)
            if take:
                rows[i] = row.model_copy(update={"earned": row.weight - take, "passed": take == 0})
                deficit -= take
    if gate:
        rows = [r.model_copy(update={"earned": 0, "passed": False}) for r in rows]
    cc = CodeCheckResult(total=0 if gate else code_total, checks=rows, gate_failures=gate or [])
    fm = FeatureMatchResult(score=0 if gate else feature, missing_features=[], extra_features=[], findings=[],
                            judged_by="htmlParse")
    return ArtifactScore(total=0 if gate else code_total + feature, code_check=cc, feature_match=fm)


def doc(total: float) -> DocScore:
    return DocScore(total=total, items=[])


def g02b_in(doc_total: float, art: ArtifactScore, *, snap: dict | None = None, usage: list[BundleUsage] | None = None,
            category: str = "웹개발", **kw) -> c.G02bIn:
    return c.G02bIn(doc_score=doc(doc_total), artifact_score=art, threshold=80, rework_usage=usage or [],
                    settings_snapshot=Settings().dump() if snap is None else snap, category=category, **kw)


def used(bundle: str, remaining: int, layer: str = "document") -> BundleUsage:
    return BundleUsage(bundle_id=bundle, layer=layer, used_count=1, remaining=remaining)


def fref(name: str, media_type: str, key: str | None = None) -> FileRef:
    return FileRef(key=key or f"run-x/e/u/{name}", name=name, media_type=media_type, size=1, sha256="0" * 64)


# ── G-02b 총점 · 환산 칸 ─────────────────────────────────
def test_g02b_total_is_doc_plus_scaled_artifact_and_report_carries_scaled_fields():
    art = artifact(12.0, 3.0)
    out = judge.run_g02b(g02b_in(60.0, art, snap=SKEWED))
    r = out.score_report
    # 코드 12 × 25 ÷ 15 = 20, 대조 3 × 5 ÷ 15 = 1 → 산출물층 21, 총점 60 + 21
    assert (r.code_check_score, r.feature_match_score, r.artifact_layer_score) == (20.0, 1.0, 21.0)
    assert (r.doc_layer_max, r.code_check_max, r.feature_match_max, r.artifact_layer_max) == (70, 25, 5, 30)
    assert r.total == r.display_score == 81.0 and r.passed and out.next_action == "진행가능"
    assert r.artifact_score == art                                              # 검증-2 원점수 그대로
    assert len(r.code_check_items) == 8 and round(sum(ch.weight for ch in r.code_check_items), 2) == 25
    assert round(sum(ch.earned for ch in r.code_check_items), 2) == 20.0


def test_g02b_next_action_splits_on_scaled_total():
    # 같은 원점수(코드 15 · 대조 0)라도 C 15 · P 15면 56 + 15 = 71 → 재작성권유, C 25 · P 5면 56 + 25 = 81 → 진행가능
    art = artifact(15.0, 0.0)
    default = judge.run_g02b(g02b_in(56.0, art))
    skewed = judge.run_g02b(g02b_in(56.0, art, snap=SKEWED))
    assert (default.score_report.total, default.next_action) == (71.0, "재작성권유")
    assert (skewed.score_report.total, skewed.next_action) == (81.0, "진행가능")


def test_g02b_gate_failure_zeroes_scaled_values():
    out = judge.run_g02b(g02b_in(70.0, artifact(0, 0, gate=["entry"]), snap=SKEWED))
    r = out.score_report
    assert (r.code_check_score, r.feature_match_score, r.artifact_layer_score) == (0.0, 0.0, 0.0)
    assert all(ch.earned == 0 for ch in r.code_check_items) and r.total == 70.0
    assert [o.task_id for o in out.rework_orders if o.layer == "artifact"] == ["T-B1"]


@pytest.mark.parametrize("category,task_id", [("원페이지", "T-B2"), ("웹개발", "T-B1"), ("AI_API", "T-B1")])
def test_g02b_kind_from_input_category(category, task_id):
    out = judge.run_g02b(g02b_in(60.0, artifact(0, 0, gate=["entry"]), category=category))
    assert [o.task_id for o in out.rework_orders if o.layer == "artifact"] == [task_id]


def test_g02b_rework_diff_artifact_summary_uses_scaled_values_and_c_plus_p():
    before, after = artifact(12.0, 3.0), artifact(15.0, 15.0)
    ci = c.ReworkCycleInfo(cycle_id="cy", screen=9, comparisons=[], rescored_layers=["artifact"],
                           reworked_task_ids=["T-B1"], previous_doc_score=doc(50.0), previous_artifact_score=before)
    out = judge.run_g02b(g02b_in(60.0, after, snap=SKEWED, cycle_info=ci))
    diffs = {d.layer: d for d in out.rework_diff}
    maxes = ScoreMaxes(70, 25, 5)
    assert diffs["artifact"].before_summary == f"{scale_artifact(before, maxes).artifact_layer_score}/30" == "21.0/30"
    assert diffs["artifact"].after_summary == "30.0/30"
    assert (diffs["document"].before_summary, diffs["document"].after_summary) == ("50.0/70", "60.0/70")
    assert out.score_report.rework_diff == out.rework_diff


def test_g02b_artifact_summary_max_follows_snapshot():
    ci = c.ReworkCycleInfo(cycle_id="cy", screen=8, comparisons=[], rescored_layers=["artifact"],
                           reworked_task_ids=["T-B1"], previous_artifact_score=artifact(15.0, 15.0))
    out = judge.run_g02b(g02b_in(60.0, artifact(15.0, 15.0), snap=snapshot(code_check_max=10, feature_match_max=10),
                                 cycle_info=ci))
    [d] = out.rework_diff
    assert (d.before_summary, d.after_summary) == ("20.0/20", "20.0/20")


# ── E-G2-UNREACHABLE (R-6 ②) ─────────────────────────────
def test_unreachable_first_message_when_document_bundle_unused():
    # 40 + 30 < 80, 문서층 묶음은 아직 쓰지 않음 → 기회는 설정 사본 rework.perBundle(기본 1)
    out = judge.run_g02b(g02b_in(40.0, artifact(15.0, 15.0), usage=[used("실행 파일", 0, "artifact")]))
    assert FIRST in out.score_report.notices and UNREACHABLE_NO_DOC_CHANCE not in out.score_report.notices


def test_unreachable_second_message_when_every_document_bundle_used_up():
    usage = [used(b, 0) for b in DOCUMENT_BUNDLES]
    out = judge.run_g02b(g02b_in(40.0, artifact(15.0, 15.0), usage=usage))
    assert out.score_report.notices == [UNREACHABLE_NO_DOC_CHANCE]
    assert FIRST == "프로토타입만 다시 만들어서는 기준 점수에 이르지 못합니다. 계획서 항목을 함께 선택해주세요."
    assert UNREACHABLE_NO_DOC_CHANCE == "남은 항목을 다시 만들어도 기준 점수에 이르지 못합니다. 이대로 진행할 수 있습니다."


def test_unreachable_used_bundle_counts_its_remaining():
    usage = [used(b, 0) for b in DOCUMENT_BUNDLES[:-1]] + [used(DOCUMENT_BUNDLES[-1], 1)]
    assert judge.run_g02b(g02b_in(40.0, artifact(15.0, 15.0), usage=usage)).score_report.notices == [FIRST]


def test_unreachable_unused_bundle_reads_per_bundle_from_snapshot():
    zero = Settings(rework=ReworkSettings(per_bundle=0)).dump()
    assert judge.run_g02b(g02b_in(40.0, artifact(15.0, 15.0), snap=zero)).score_report.notices == [
        UNREACHABLE_NO_DOC_CHANCE]
    old = {k: v for k, v in Settings().dump().items() if k != "rework"}   # 칸이 없는 사본 → 설정 기본값(1)
    assert judge.run_g02b(g02b_in(40.0, artifact(15.0, 15.0), snap=old)).score_report.notices == [FIRST]
    # 사용 기록이 있는 묶음은 그 remaining — 설정 사본 값보다 앞선다
    one_left = [used(DOCUMENT_BUNDLES[0], 1)]
    assert judge.run_g02b(g02b_in(40.0, artifact(15.0, 15.0), snap=zero, usage=one_left)).score_report.notices == [
        FIRST]


@pytest.mark.parametrize("doc_total,snap,expected", [
    (50.0, None, []),                                                       # 50 + 30 = 80 — 도달 가능
    (55.0, None, []),
    (60.0, snapshot(code_check_max=5, feature_match_max=5), [FIRST]),       # 60 + 10 < 80
    (70.0, snapshot(code_check_max=5, feature_match_max=5), []),            # 70 + 10 = 80
])
def test_unreachable_uses_doc_total_plus_c_plus_p(doc_total, snap, expected):
    out = judge.run_g02b(g02b_in(doc_total, artifact(0, 0), snap=snap))
    assert out.score_report.notices == expected


def test_unreachable_does_not_block_or_change_next_action():
    out = judge.run_g02b(g02b_in(40.0, artifact(10.0, 5.0)))
    assert out.next_action == "재작성권유" and FIRST in out.score_report.notices
    # 계획서 묶음 모두가 후보 (19.7 ②) — 안내는 후보 · 요청을 막지 않는다
    assert {o.targets[0] for o in out.rework_orders if o.layer == "document"} == set(DOCUMENT_BUNDLES)


# ── G-02a · 배점 0 (D12) ─────────────────────────────────
def g02a_in(doc_total: float, snap: dict) -> c.G02aIn:
    return c.G02aIn(doc_score=doc(doc_total), threshold=80, rework_usage=[], settings_snapshot=snap)


def test_g02a_report_fills_only_doc_layer_max():
    r = judge.run_g02a(g02a_in(45.0, snapshot(doc_layer_max=60))).score_report
    assert (r.display_score, r.doc_layer_max) == (75.0, 60)
    assert (r.code_check_score, r.code_check_max, r.feature_match_score, r.feature_match_max, r.artifact_layer_score,
            r.artifact_layer_max, r.code_check_items) == (None, None, None, None, None, None, [])


@pytest.mark.parametrize("doc_total", [0.0, 10.0])
def test_g02a_doc_layer_zero_keeps_zero_and_display_zero(doc_total):
    out = judge.run_g02a(g02a_in(doc_total, snapshot(doc_layer_max=0)))
    r = out.score_report
    assert (r.display_score, r.doc_layer_max, r.passed) == (0.0, 0, False)  # 0을 70으로 바꾸지 않는다
    assert out.next_action == "재작성권유"


def test_g02b_doc_layer_zero_does_not_divide_by_zero():
    out = judge.run_g02b(g02b_in(10.0, artifact(15.0, 15.0), snap=snapshot(doc_layer_max=0)))
    assert out.score_report.doc_layer_max == 0 and out.score_report.total == 40.0
    assert {o.targets[0] for o in out.rework_orders if o.layer == "document"} == set(DOCUMENT_BUNDLES)


def test_g02a_old_snapshot_without_scoring_reads_default_70():
    r = judge.run_g02a(g02a_in(56.0, {})).score_report
    assert (r.display_score, r.doc_layer_max) == (80.0, 70)


# ── 입력 오류 (후보 제외 · 안내) ─────────────────
INPUT_ERROR_TEXT = ("입력한 협약기간 일정이나 사업비가 기준(협약기간 최대 개월 수 · 개발 기간 · 공고 지원 금액 상한)을 벗어나 "
                    "일부 항목이 검증을 통과하지 못했습니다. 이 항목은 다시 만들어도 고쳐지지 않습니다. 이대로 진행하거나, "
                    "입력을 고쳐 새 프로젝트로 다시 만들 수 있습니다.")


def sr(code: str, status: str = "fail", *, missing: bool = False, error: bool = False) -> SectionResult:
    return SectionResult(section_code=code, content_type="section", status=status, score=0.0,
                         verified_ref="planDoc@1", input_missing=missing, input_error=error,
                         issues=[f"{code} 문제"] if status == "fail" else [],
                         warnings=[f"{code} 경고"] if status == "warning" else [])


def test_input_error_notice_text_is_fixed():
    assert judge.INPUT_ERROR_NOTICE == INPUT_ERROR_TEXT
    assert "INPUT_ERROR_NOTICE" in judge.__all__


def test_input_error_items_are_not_bundle_candidates():
    orders = judge.doc_candidates([sr("3.5.2", error=True), sr("3.4.1")], 90.0, 80)
    assert [o.targets for o in orders] == [["문제인식"]]
    # 같은 묶음에 입력 오류 아닌 fail · warning이 있으면 그 묶음은 후보 — 사유에는 그 항목만
    mixed = judge.doc_candidates([sr("3.5.2", error=True), sr("3.5.1", "warning")], 90.0, 80)
    assert [o.targets for o in mixed] == [["실현가능성"]] and "3.5.2" not in mixed[0].reason


def test_input_error_only_keeps_every_bundle_rule_when_score_is_low():
    only = [sr("3.5.2", error=True), sr("3.5.3", error=True)]
    assert judge.doc_candidates(only, 90.0, 80) == []
    low = judge.doc_candidates(only, 60.0, 80)
    assert {o.targets[0] for o in low} == set(DOCUMENT_BUNDLES)


def test_g02a_notices_order_final_action_missing_error_once():
    checks = [CheckResult(passed=False, failures=["x"], final_action="표 제거 · 본문 서술 대체")]
    inp = c.G02aIn(doc_score=doc(60.0), threshold=80, rework_usage=[], settings_snapshot=Settings().dump(),
                   checks=checks, section_results=[sr("3.5.3", "warning", missing=True), sr("3.5.2", error=True),
                                                   sr("3.6.2", error=True)])
    assert judge.run_g02a(inp).score_report.notices == [
        "표 제거 · 본문 서술 대체", judge.INPUT_MISSING_NOTICE, INPUT_ERROR_TEXT]
    plain = inp.model_copy(update={"section_results": [sr("3.5.2")]})
    assert judge.run_g02a(plain).score_report.notices == ["표 제거 · 본문 서술 대체"]


def test_g02b_notices_order_missing_error_unreachable():
    res = [sr("3.5.2", error=True), sr("3.5.3", "warning", missing=True)]
    out = judge.run_g02b(g02b_in(40.0, artifact(15.0, 15.0), section_results=res))
    assert out.score_report.notices == [judge.INPUT_MISSING_NOTICE, INPUT_ERROR_TEXT, FIRST]
    only_error = judge.run_g02b(g02b_in(60.0, artifact(15.0, 15.0), section_results=[sr("3.5.2", error=True)]))
    assert only_error.score_report.notices == [INPUT_ERROR_TEXT]


# ── 흐름 (스텁 조립 — 실구현 판정) ───────────────────────
def test_flow_g02b_unreachable_notice_and_scaled_report(clock):
    app = make_app(clock, StubScenario(doc_scores=[40.0], art_scores=[(15.0, 15.0)]))
    rid = to_screen8(app)
    r = ctx_of(app, rid).get("scoreReport.overall")
    assert FIRST in r.notices
    assert (r.artifact_layer_score, r.artifact_layer_max, r.total) == (30.0, 30, 70.0)


def test_flow_g02b_second_message_when_per_bundle_zero(clock):
    app = make_app(clock, StubScenario(doc_scores=[40.0]), settings=Settings(rework=ReworkSettings(per_bundle=0)))
    rid = to_screen8(app)
    assert UNREACHABLE_NO_DOC_CHANCE in ctx_of(app, rid).get("scoreReport.overall").notices


def test_flow_g02a_doc_layer_zero(clock):
    app = make_app(clock, settings=Settings(scoring=ScoringSettings(doc_layer_max=0)))
    rid = to_screen6(app)
    ctx = ctx_of(app, rid)
    r = ctx.get("scoreReport.document")
    assert (r.display_score, r.doc_layer_max) == (0.0, 0) and ctx.get("G-02a.nextAction") == "재작성권유"


# ── G-04 안내 문서 ───────────────────────────────────────
class PutOnly:
    """파일 창구 흉내 — 넣기만 있다(G-04가 다른 파일을 읽으면 AttributeError)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, str]] = []

    def put(self, name: str, data: bytes, media_type: str) -> FileRef:
        self.calls.append((name, data, media_type))
        return fref(name, media_type)


def g04_in(kind: str = "html", *, item_name: str = "헬스장 예약", title: str | None = "창업지원사업 A01",
           entry: bool = True, assets: list[FileRef] | None = None) -> c.G04In:
    image = fref("onepage.svg" if kind == "svg-onepage" else "infographic.svg", "image/svg+xml")
    if kind == "svg-onepage":
        entry_file = image if entry else None
    else:
        entry_file = fref("index.html", "text/html") if entry else None
    proto = Prototype(entry_file=entry_file, kind=kind, asset_files=assets or [], implemented_features=FEATURES)
    item = ItemSpec(item_name=item_name, one_line_summary="요약 본문 비밀", target_customer="t", core_features=FEATURES,
                    category="원페이지" if kind == "svg-onepage" else "웹개발", keywords=[])
    ann: Announcement = make_announcement("A01", kst_today(utc_now()))
    if title is not None:
        ann = ann.model_copy(update={"title": title})
    return c.G04In(prototype=proto, infographic=Infographic(image_file=image, format="svg", alt_text="alt 비밀"),
                   item_spec=item, announcement=ann)


def run_g04(inp: c.G04In) -> tuple[c.G04Out, str]:
    files = PutOnly()
    out = readme.run(inp, files)
    [(name, data, media_type)] = files.calls
    assert (name, media_type) == ("README.md", "text/markdown") and out.readme_file.name == "README.md"
    return out, data.decode("utf-8")


def test_g04_html_template_sections_files_and_words():
    out, text = run_g04(g04_in("html"))
    assert out.check.passed and out.check.failures == []
    lines = text.splitlines()
    assert lines[0] == "# 실행 · 열람 안내 — 헬스장 예약"
    assert "- 공고: 창업지원사업 A01" in lines
    for heading in ("## 파일 목록", "## 여는 방법", "## AI 생성 고지"):
        assert heading in lines
    assert "이 프로토타입은 AI가 생성했습니다." in text                       # 기획서 6-8 고정 문구
    assert "`index.html`" in text and "`infographic.svg`" in text and "`README.md`" in text
    how = text.split("## 여는 방법")[1].split("## AI 생성 고지")[0]
    assert "실행" in how and "브라우저" in how and "버튼" in how
    assert "인쇄" not in text


def test_g04_onepage_template_lists_entry_once_and_has_read_and_print():
    out, text = run_g04(g04_in("svg-onepage"))
    assert out.check.passed
    assert text.splitlines()[0].startswith("# 열람 · 인쇄 안내")
    files_part = text.split("## 파일 목록")[1].split("## 여는 방법")[0]
    assert files_part.count("onepage.svg") == 1                               # 진입 파일 = 인포그래픽 — 한 번만
    how = text.split("## 여는 방법")[1].split("## AI 생성 고지")[0]
    assert "열람" in how and "인쇄" in how and "브라우저" in how


def test_g04_empty_slots_use_default_texts_and_keep_sections():
    out, text = run_g04(g04_in("html", item_name="", title="", entry=False))
    assert readme.DEFAULT_ITEM_NAME in text and readme.DEFAULT_ANNOUNCEMENT in text and readme.DEFAULT_ENTRY in text
    for heading in ("## 파일 목록", "## 여는 방법", "## AI 생성 고지"):
        assert heading in text
    assert "`infographic.svg`" in text and out.check.passed
    _, onepage = run_g04(g04_in("svg-onepage", entry=False))
    assert "`onepage.svg`" in onepage                                         # 진입 파일이 없으면 인포그래픽은 따로


def test_g04_assets_listed_and_names_only_no_product_content():
    out, text = run_g04(g04_in("html", item_name="줄\n바꿈 이름", assets=[fref("data.json", "application/json")]))
    assert "`data.json`" in text and "# 실행 · 열람 안내 — 줄 바꿈 이름" in text
    assert "요약 본문 비밀" not in text and "alt 비밀" not in text and "<" not in text


def test_g04_self_check_words():
    assert readme.readme_check("실행 방법", "html").passed and readme.readme_check("열람 방법", "html").passed
    bad = readme.readme_check("안내 없음", "html")
    assert not bad.passed and bad.failures == ["안내 문서에 '실행' 또는 '열람' 안내가 없음"]
    half = readme.readme_check("열람만", "svg-onepage")
    assert not half.passed and half.failures == ["안내 문서에 '인쇄' 안내가 없음"]
    assert readme.readme_check("열람 · 인쇄", "svg-onepage").passed


# ── 조립 ────────────────────────────────────────────────
def stub_registry(sc: StubScenario):
    r = build_registry()
    bind_stubs(r, sc)
    return r


def test_stub_assembly_wraps_the_real_rule_functions():
    assert RULE_TASKS == {"G-02a", "G-02b", "G-04", "M-1", "M-2", "M-3", "M-4"}
    assert RULES["G-02b"] is judge.run_g02b and RULES["G-04"] is readme.run and RULES["M-4"] is merge.run_m4
    r = stub_registry(StubScenario())
    for tid, fn in RULES.items():
        assert r.get(tid).fn.__wrapped__ is fn, tid
    # 스텁 조립의 G-02b가 실구현 규칙(환산 · 안내)을 낸다
    inp = g02b_in(40.0, artifact(12.0, 3.0), snap=SKEWED)
    assert r.get("G-02b").fn(inp) == judge.run_g02b(inp)


@pytest.mark.parametrize("task_id", sorted(RULE_TASKS))
def test_stub_assembly_raise_in_still_works(task_id):
    fn = stub_registry(StubScenario(raise_in={task_id})).get(task_id).fn
    with pytest.raises(RuntimeError):
        fn(None, None) if task_id == "G-04" else fn(None)


def test_stub_assembly_g04_check_fail_times_then_real_check():
    sc = StubScenario(check_fail_times={"G-04": 1})
    fn = stub_registry(sc).get("G-04").fn
    files = PutOnly()
    first, second = fn(g04_in(), files), fn(g04_in(), files)
    assert not first.check.passed and second.check.passed and len(files.calls) == 2
    assert first.readme_file.name == second.readme_file.name == "README.md"


def test_worker_assembly_binds_real_rules(tmp_path, db):
    url = f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"
    app = build_app(url, project_inputs=projects(1), llm=FakeLLM())
    for tid, fn in RULES.items():
        assert app.registry.get(tid).fn is fn, tid
