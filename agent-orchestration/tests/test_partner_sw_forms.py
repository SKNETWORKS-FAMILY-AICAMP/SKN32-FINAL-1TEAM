"""양식 묶음 = 담당자 계약 항목 · 짝짓기 표 한 곳 · 목적 이름 상수 · 패키지 자료 (spec 4.2 · 4.6, 결정 0024)."""
from __future__ import annotations

import pathlib
import tomllib

import pytest

from sbrain.agents import form_defaults
from sbrain.agents.form_defaults import FORM_TABLE, form_problem, select_form
from sbrain.agents.partner_sw import contract, purposes
from sbrain.flow import rework_map
from sbrain.flow.rework_map import (
    DOCUMENT_BUNDLES, SECTION_BUNDLE_TABLE, bundle_sections, section_bundle, section_tag, section_tag_bundle,
)
from sbrain.orchestrator.settings import Settings

CODE_DIR = pathlib.Path(__file__).resolve().parents[1]
PARTNER_DIR = CODE_DIR / "sbrain" / "agents" / "partner_sw"
CASES = [("예비창업자", "pre_startup", 25), ("개인사업자", "early_startup", 24), ("법인", "early_startup", 24)]


# ── 양식 묶음 = 담당자 계약 (spec 4.6) ──────────────────────
@pytest.mark.parametrize("applicant,document_type,count", CASES)
def test_form_bundle_matches_partner_contract(applicant, document_type, count):
    specs = contract.CONTRACT["documents"][document_type]
    b = select_form(applicant)
    form = b.form_spec
    assert form_problem(applicant) is None
    assert len(form.section_codes) == count
    assert form.section_codes == [s["sectionId"] for s in specs]                 # 순서 그대로
    assert form.section_titles == [s["title"] for s in specs]
    assert form.section_kinds == [s["contentType"] for s in specs]
    assert form.section_tags == [section_tag(c) for c in form.section_codes]
    assert len(form.section_tags) == len(form.section_kinds) == count
    assert form.form_version == f"{document_type}@{contract.CONTRACT['version']}"
    assert applicant in form.applicant_types
    assert (form.max_chars_per_section, form.attachment_required) == (None, False)


@pytest.mark.parametrize("applicant,document_type,count", CASES)
def test_evaluation_items_and_rubric_are_one_per_section(applicant, document_type, count):
    b = select_form(applicant)
    codes, titles = b.form_spec.section_codes, b.form_spec.section_titles
    assert [e.item_code for e in b.evaluation_items] == codes
    assert [e.item_name for e in b.evaluation_items] == [t[:40] for t in titles]
    assert [e.description for e in b.evaluation_items] == titles
    assert all(e.max_score == pytest.approx(70 / count) for e in b.evaluation_items)
    assert sum(e.max_score for e in b.evaluation_items) == pytest.approx(70)
    assert [r.item_code for r in b.rubric.items] == codes
    assert (b.rubric.rubric_id, b.rubric.version) == ("partner-sw", contract.SCORE_RUBRIC["version"])
    for item, e, code in zip(b.rubric.items, b.evaluation_items, codes):
        assert item.criteria == contract.section_criteria(document_type, code) and item.criteria
        assert item.score_bands == [{"min": 0, "max": e.max_score}] and item.evidence_required


def test_kinds_and_tags_of_known_sections():
    pre = select_form("예비창업자").form_spec
    kinds = dict(zip(pre.section_codes, pre.section_kinds))
    tags = dict(zip(pre.section_codes, pre.section_tags))
    assert kinds["2.3.6"] == "image" and kinds["2.5.2"] == kinds["2.5.3"] == kinds["2.6.2"] == "table"
    assert tags["2.1.1"] is None and tags["2.3.6"] is None and tags["2.3.5"] is None
    assert (tags["2.4.1"], tags["2.5.4"], tags["2.6.2"], tags["2.7.4"]) == ("1-1", "2-1", "3-1", "4-1")
    early = select_form("법인").form_spec
    etags = dict(zip(early.section_codes, early.section_tags))
    assert etags["3.3.6"] is None and (etags["3.4.1"], etags["3.5.3"], etags["3.6.1"], etags["3.7.1"]) == (
        "1-1", "2-1", "3-1", "4-1")


def test_general_contract_is_not_selected():
    assert "general" in contract.CONTRACT["documents"]                                # 데이터로는 남는다
    assert all(not b.form_spec.form_version.startswith("general") for b in FORM_TABLE.values())


def test_selected_bundle_is_a_copy():
    b = select_form("법인")
    b.form_spec.section_codes.append("9.9.9")
    b.evaluation_items.pop()
    assert len(select_form("법인").form_spec.section_codes) == 24
    assert len(select_form("법인").evaluation_items) == 24


def test_contract_documents_are_copies():
    contract.document_specs("pre_startup")[0]["sectionId"] = "바꿈"
    assert contract.document_specs("pre_startup")[0]["sectionId"] == "2.1.1"


# ── 짝짓기 표 한 곳 (spec 4.6) ──────────────────────────────
def test_pairing_table_lookup():
    assert section_tag_bundle("2.4.1") == ("1-1", "문제인식")
    assert section_tag_bundle("3.5.3") == ("2-1", "실현가능성")
    assert section_tag_bundle("2.6.2") == ("3-1", "성장전략")
    assert section_tag_bundle("3.7.4") == ("4-1", "팀 구성")
    for code in ("2.1.1", "2.2.2", "2.3.6", "3.3.6", "3.1.4", "1-1", ""):
        assert section_tag_bundle(code) is None and section_tag(code) is None and section_bundle(code) is None


def test_bundle_sections_follow_form_order():
    codes = select_form("예비창업자").form_spec.section_codes
    assert bundle_sections("문제인식", codes) == ["2.4.1"]
    assert bundle_sections("실현가능성", codes) == ["2.5.1", "2.5.2", "2.5.3", "2.5.4"]
    assert bundle_sections("팀 구성", codes) == ["2.7.1", "2.7.2", "2.7.3", "2.7.4"]
    assert bundle_sections("없는 묶음", codes) == []
    early = select_form("법인").form_spec.section_codes
    assert bundle_sections("성장전략", early) == ["3.6.1", "3.6.2"]


def test_document_bundles_come_from_pairing_table():
    assert DOCUMENT_BUNDLES == ("문제인식", "실현가능성", "성장전략", "팀 구성")     # 웹 화면 묶음 이름 4개
    assert set(DOCUMENT_BUNDLES) == {b for _, b in SECTION_BUNDLE_TABLE.values()}
    assert all(rework_map.BUNDLE_LAYER[b] == "document" for b in DOCUMENT_BUNDLES)


def test_changing_pairing_table_changes_section_tags(monkeypatch):
    # 2.3.x(그림 2.3.6 포함)를 한 묶음에 넣으면 고른 양식의 태그 · 묶음 항목이 따라 바뀐다 (표 하나만 바꿈)
    monkeypatch.setitem(SECTION_BUNDLE_TABLE, "2.3", ("1-1", "문제인식"))
    form = select_form("예비창업자").form_spec
    tags = dict(zip(form.section_codes, form.section_tags))
    assert tags["2.3.6"] == "1-1" and tags["2.3.1"] == "1-1" and tags["2.2.1"] is None
    assert bundle_sections("문제인식", form.section_codes) == ["2.3.1", "2.3.2", "2.3.3", "2.3.4", "2.3.5", "2.3.6",
                                                               "2.4.1"]
    # 가장 긴 앞부분이 이긴다 — 항목 하나만 다른 묶음으로
    monkeypatch.setitem(SECTION_BUNDLE_TABLE, "2.3.6", ("2-1", "실현가능성"))
    assert section_bundle("2.3.6") == "실현가능성" and section_bundle("2.3.5") == "문제인식"


# ── 목적 이름 (spec 4.2) ────────────────────────────────────
def test_purpose_constants_are_f01_to_f19():
    assert purposes.PURPOSES == frozenset(f"F{n:02d}" for n in range(1, 20))
    assert (purposes.F01, purposes.F16, purposes.F19) == ("F01", "F16", "F19")


def test_default_purpose_models_use_purpose_constants():
    keys = {p for setting in Settings().tasks.values() for p in setting.purpose_models}
    assert keys and keys <= purposes.PURPOSES


def test_partner_llm_functions_are_purposes():
    llm_functions = {fid for fid, cfg in contract.CONTRACT["functions"].items() if cfg.get("apiModel")}
    assert llm_functions <= purposes.PURPOSES


# ── 패키지 자료 (spec 4.1) ──────────────────────────────────
def test_package_data_covers_partner_data_files():
    config = tomllib.loads((CODE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"]["package-data"]
    covered: set[pathlib.Path] = set()
    for package, patterns in package_data.items():
        base = CODE_DIR.joinpath(*package.split("."))
        assert (base / "__init__.py").is_file(), package
        for pattern in patterns:
            covered.update(p.resolve() for p in base.glob(pattern) if p.is_file())
    data = {p.resolve() for folder in ("agent_strategy/res", "agent_strategy/runtime", "agent_validation_1/res")
            for p in (PARTNER_DIR / folder).rglob("*") if p.suffix in (".json", ".md")}
    assert data and data <= covered
    assert any(p.name == "raw_kiet_results.json" for p in data)
