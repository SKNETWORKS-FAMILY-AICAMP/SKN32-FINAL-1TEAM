"""웹 백엔드가 구현 Agent(T-B1 · T-B2)를 부르는 진입점.

백엔드(back/app/agents.py `run_implement_agent_retry`)는 계약 모델을 모르고 평평한 값
(category · feature_list · item_spec dict · plan_doc dict · instruction · rework_issues)을
넘긴다. 이 함수가 그 값을 계약 입력(TB1In · TB2In)으로 조립하고, 만들어진 파일을 바이트로
읽어 돌려준다. 저장 위치는 백엔드가 정한다.

LLM 호출에 쓰는 tools는 조율(agent-orchestration)이 만든 Tools 인스턴스를 받는다. 구현 코드는
tools.llm만 부르므로 어떤 모델을 쓰는지 모른다.
"""
from __future__ import annotations

from pathlib import Path

from engineering_agent.tasks import run_tb1, run_tb2


def _plan_doc(plan_doc: dict | None, feature_list: list[str]) -> dict:
    """백엔드 plan_doc dict를 PlanDoc 계약 모양으로 맞춘다.

    백엔드는 문장을 글자 목록(`sentences: ["...", ...]`)으로 넘기는데, 계약의 PlanSection은
    문장마다 sentence_id · text · is_title · paragraph_no를 요구한다. 글자만 온 문장은 여기서
    채워 넣는다. 이미 계약 모양인 문장은 그대로 둔다.
    """
    plan_doc = dict(plan_doc or {})
    sections = []
    for i, section in enumerate(plan_doc.get("sections") or [], start=1):
        code = str(section.get("section_code") or i)
        sentences = [
            s if isinstance(s, dict) else
            {"sentence_id": f"{code}-{j}", "text": str(s), "is_title": False, "paragraph_no": j}
            for j, s in enumerate(section.get("sentences") or [], start=1)
        ]
        sections.append({"section_code": code, "title": section.get("title", ""),
                         "sentences": sentences})
    return {
        "sections": sections,
        "feature_list": plan_doc.get("feature_list") or list(feature_list),
        "charts": plan_doc.get("charts") or [],
        "tables": plan_doc.get("tables") or [],
        "protected_tokens": plan_doc.get("protected_tokens") or [],
    }


def _read_bytes(path: str) -> bytes | None:
    file = Path(path) if path else None
    return file.read_bytes() if file and file.is_file() else None


def implement_artifact(*, artifact_kind: str, category: str, feature_list: list[str],
                       item_spec: dict, tools, plan_doc: dict | None = None,
                       instruction: str = "", rework_issues: list[str] | None = None) -> dict:
    """artifact_kind='prototype'(T-B1, index.html) | 'infographic'(T-B2, SVG)을 만든다.

    반환: {
        "file_bytes": bytes | None,  # T-B1 자체 게이트에 걸리면 파일이 없어 None
        "file_ext": ".html" | ".svg",
        "file_path": str,            # 구현 Agent가 저장한 원본 경로 (engineering_agent/output/...)
        "alt_text": str,             # 인포그래픽 대체 텍스트. 검증-2에 넘긴다. prototype이면 ""
        "passed": bool,              # 자체 검사 통과 여부
        "failures": list[str],       # 자체 검사 실패 사유. 재수행 시 rework_issues로 다시 넘긴다
        "implemented_features": list[str],
    }
    호출 자체가 실패하면(LLM 재시도 소진 등) 예외를 그대로 올린다 — 완전실패_예외처리 R1.
    """
    from sbrain.contracts.tasks import TB1In, TB2In
    from sbrain.models import ItemSpec, PlanDoc, ReworkInput

    spec = ItemSpec(**{"core_features": list(feature_list), "category": category,
                       "keywords": [], **item_spec})
    # 백엔드의 재작성은 사용자가 고른 산출물 재작성이다. 구현 Agent는 issues만 읽는다.
    rework = (ReworkInput(mode="재작성", previous_result_ref="", issues=list(rework_issues),
                          order=None, is_final_attempt=False)
              if rework_issues else None)

    if artifact_kind == "prototype":
        if category == "원페이지":
            raise ValueError("원페이지는 T-B1(prototype)을 호출하지 않는다 — 인포그래픽만 만든다")
        out = run_tb1(TB1In(feature_list=list(feature_list), item_spec=spec, category=category,
                            instruction=instruction, rework_input=rework), tools)
        return {
            "file_bytes": _read_bytes(out.entry_file_path), "file_ext": ".html",
            "file_path": out.entry_file_path, "alt_text": "",
            "passed": out.check.passed, "failures": list(out.check.failures),
            "implemented_features": list(out.implemented_features),
        }

    if artifact_kind == "infographic":
        doc = PlanDoc(**_plan_doc(plan_doc, feature_list))
        out = run_tb2(TB2In(plan_doc=doc, item_spec=spec, category=category,
                            instruction=instruction, rework_input=rework), tools)
        return {
            "file_bytes": _read_bytes(out.infographic.image_path), "file_ext": ".svg",
            "file_path": out.infographic.image_path, "alt_text": out.infographic.alt_text,
            "passed": out.check.passed, "failures": list(out.check.failures),
            "implemented_features": [],
        }

    raise ValueError(f"알 수 없는 artifact_kind: {artifact_kind!r} (prototype | infographic)")
