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


def _read(path: str | None) -> str:
    file = Path(path) if path else None
    return file.read_text(encoding="utf-8") if file and file.is_file() else ""


def plan_text_of(plan_doc) -> str | None:
    """계획서 본문과 표를 대조용 평문으로 편다. PlanDoc 모델과 같은 모양의 dict 둘 다
    받는다. engineering_agent에도 같은 일을 하는 함수가 있지만 import하지 않는다(ADR 0001)."""
    if plan_doc is None:
        return None
    get = (lambda o, k: o.get(k)) if isinstance(plan_doc, dict) else getattr

    def sentence_text(s) -> str:
        return s if isinstance(s, str) else get(s, "text")

    sections = "\n".join(
        f"{get(section, 'title')}\n"
        + "\n".join(sentence_text(s) for s in (get(section, "sentences") or []))
        for section in (get(plan_doc, "sections") or [])
    )
    tables = "\n".join(
        f"{get(table, 'title')}\n" + "\n".join(" | ".join(row) for row in (get(table, "rows") or []))
        for table in (get(plan_doc, "tables") or [])
    )
    return f"{sections}\n{tables}"


def _check_infographic_alt(raw: dict, kind: str, svg: str, alt_text: str) -> None:
    """Infographic.alt_text가 실제 SVG에 들어 있는지. 파일 바깥(계약 필드)과 파일
    안이 어긋나면 화면에 보이는 대체 텍스트와 채점한 파일이 서로 다른 것이다."""
    if not raw["passed"]:
        return
    if not svg or "<svg" not in svg or not alt_text or alt_text not in svg:
        # 결함은 인포그래픽(T-B2) 쪽이다. 원페이지는 칸 전체가 T-B2 몫이라 표시하지 않는다.
        sources = ["infographic"] if kind == "html" else []
        item_rules.fail(raw["items"], _ALT_ITEM[kind], "Infographic.alt_text와 SVG 원문 불일치",
                        sources)
        raw["total"] = item_rules.total(raw["items"])


def score_artifact(*, kind: str, entry_file_path: str, source_text: str,
                   readme_path: str | None, infographic_path: str, infographic_alt_text: str,
                   feature_list: list[str], plan_text: str | None) -> tuple[dict, dict]:
    """산출물층 채점 본체. (코드 점검 결과, 계획서 대조 결과)를 dict로 돌려준다.

    계약 모델에 의존하지 않으므로 sbrain 없이도 돈다.
    """
    readme = _read(readme_path) if readme_path else None
    svg = _read(infographic_path)

    if kind == "svg-onepage":
        raw = compute_infographic_check(entry_file_path, source_text, readme)
        if raw["passed"] and svg != source_text:
            reason = "Infographic.image_path와 Prototype.source_text 불일치"
            raw.update(total=0.0, passed=False, gate_failures=[reason], gate_codes=["entry"],
                       items=item_rules.skipped(
                           tuple((i["id"], i["name"], i["weight"]) for i in raw["items"]),
                           f"통과 필수 조건 실패로 검사 생략: {reason}"))
    else:
        raw = compute_code_check(entry_file_path, source_text, readme, svg)
    _check_infographic_alt(raw, kind, svg, infographic_alt_text)

    feature = match_features(feature_list, source_text if raw["passed"] else "", kind, plan_text)
    return raw, feature


def run_tv2(inp: TV2In, tools: Tools) -> TV2Out:
    from sbrain.contracts.tasks import TV2Out
    from sbrain.models import ArtifactScore, CodeCheck, CodeCheckResult, FeatureMatchResult

    prototype = inp.prototype
    raw, feature_raw = score_artifact(
        kind=prototype.kind, entry_file_path=prototype.entry_file_path,
        source_text=prototype.source_text, readme_path=prototype.readme_path,
        infographic_path=inp.infographic.image_path,
        infographic_alt_text=inp.infographic.alt_text, feature_list=inp.feature_list,
        # plan_doc은 계약 추가 요청 중인 필드다(조율_계약필드_요청_검증2.md). 오기 전에는 None.
        plan_text=plan_text_of(getattr(inp, "plan_doc", None)),
    )
    # gate_failures · defect_sources는 조율이 확장 필드로 추가하는 중이다(조율 회신 2-2).
    # 실계약에 아직 없으면 넣지 않는다 — extra="forbid"라 넣으면 검증 오류가 난다.
    check_extra = "defect_sources" in CodeCheck.model_fields
    result_extra = "gate_failures" in CodeCheckResult.model_fields
    checks = [CodeCheck(no=item["id"], name=item["name"], weight=item["weight"],
                        passed=bool(item["passed"]), detail=item["evidence"],
                        **({"defect_sources": item["defect_sources"]} if check_extra else {}))
              for item in raw["items"]]
    code = CodeCheckResult(total=raw["total"], checks=checks,
                           **({"gate_failures": raw["gate_codes"]} if result_extra else {}))
    feature = FeatureMatchResult(**feature_raw)
    artifact = ArtifactScore(total=code.total + feature.score,
                             code_check=code, feature_match=feature)
    return TV2Out(artifact_score=artifact, code_check=code, feature_match=feature)
