"""Orchestration의 T-V2 계약에 맞춘 산출물층 검증 Task."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from verification_agent.feature_match import match_features
from verification_agent.rules import items as item_rules
from verification_agent.score import compute_code_check, compute_infographic_check

if TYPE_CHECKING:
    from sbrain.contracts.tasks import TV2In, TV2Out
    from sbrain.orchestrator.tools import Tools

# 대체 텍스트 칸 번호. HTML은 2번, 원페이지는 1번이다(rules/r4.py, rules/r4_onepage.py).
_ALT_ITEM = {"html": 2, "svg-onepage": 1}


def _read(path: str) -> str:
    file = Path(path) if path else None
    return file.read_text(encoding="utf-8") if file and file.is_file() else ""


def _plan_text(plan_doc) -> str | None:
    """계획서 본문과 표를 대조용 평문으로 편다. engineering_agent에도 같은 일을 하는
    함수가 있지만 import하지 않는다(ADR 0001)."""
    if plan_doc is None:
        return None
    sections = "\n".join(
        f"{section.title}\n" + "\n".join(sentence.text for sentence in section.sentences)
        for section in plan_doc.sections
    )
    tables = "\n".join(
        f"{table.title}\n" + "\n".join(" | ".join(row) for row in table.rows)
        for table in plan_doc.tables
    )
    return f"{sections}\n{tables}"


def _check_infographic_alt(raw: dict, kind: str, svg: str, alt_text: str) -> None:
    """Infographic.alt_text가 실제 SVG에 들어 있는지. 파일 바깥(계약 필드)과 파일
    안이 어긋나면 화면에 보이는 대체 텍스트와 채점한 파일이 서로 다른 것이다."""
    if not raw["passed"]:
        return
    if not svg or "<svg" not in svg or not alt_text or alt_text not in svg:
        item_rules.fail(raw["items"], _ALT_ITEM[kind], "Infographic.alt_text와 SVG 원문 불일치")
        raw["total"] = item_rules.total(raw["items"])


def run_tv2(inp: TV2In, tools: Tools) -> TV2Out:
    from sbrain.contracts.tasks import TV2Out
    from sbrain.models import ArtifactScore, CodeCheck, CodeCheckResult, FeatureMatchResult

    prototype = inp.prototype
    source = prototype.source_text
    readme = _read(prototype.readme_path) if prototype.readme_path else None
    svg = _read(inp.infographic.image_path)
    # plan_doc은 계약 추가 요청 중인 필드다(조율_계약필드_요청_검증2.md). 오기 전에는 None.
    plan_text = _plan_text(getattr(inp, "plan_doc", None))

    if prototype.kind == "svg-onepage":
        raw = compute_infographic_check(prototype.entry_file_path, source, readme)
        if raw["passed"] and svg != source:
            reason = "Infographic.image_path와 Prototype.source_text 불일치"
            raw.update(total=0.0, passed=False, gate_failures=[reason],
                       items=item_rules.skipped(
                           tuple((i["id"], i["name"], i["weight"]) for i in raw["items"]),
                           f"통과 필수 조건 실패로 검사 생략: {reason}"))
    else:
        raw = compute_code_check(prototype.entry_file_path, source, readme, svg)
    _check_infographic_alt(raw, prototype.kind, svg, inp.infographic.alt_text)

    checks = [CodeCheck(no=item["id"], name=item["name"], weight=item["weight"],
                        passed=bool(item["passed"]), detail=item["evidence"])
              for item in raw["items"]]
    code = CodeCheckResult(total=raw["total"], checks=checks)
    feature = FeatureMatchResult(**match_features(
        inp.feature_list, source if raw["passed"] else "", prototype.kind, plan_text,
    ))
    artifact = ArtifactScore(total=code.total + feature.score,
                             code_check=code, feature_match=feature)
    return TV2Out(artifact_score=artifact, code_check=code, feature_match=feature)
