"""담당자 실행 계약 · 채점 정책 · 항목 기준 — 불러올 때 한 번 읽는 상수 (spec 4.6).

양식 묶음(agents/form_defaults.py)이 계획서 항목 · 제목 · 종류 · 규칙과 채점 기준표를 여기서 끌어낸다(손으로 옮겨 적지 않음).
담당자 자료 전체(resources)를 읽지 않으려고 이 세 파일만 직접 읽는다 — 담당자 코드(llm_runtime · scoring · validation_1)가
같은 파일을 따로 읽는 것과 같은 값이다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent
CONTRACT_PATH = _HERE / "agent_strategy" / "runtime" / "execution_contract.json"
SCORE_RUBRIC_PATH = _HERE / "agent_validation_1" / "res" / "prompts" / "evaluation_rubric.json"
CRITERIA_REGISTRY_PATH = _HERE / "agent_validation_1" / "res" / "reference" / "regulations" / "criteria_registry.json"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


CONTRACT: dict[str, Any] = _json(CONTRACT_PATH)
CONTRACT_VERSION = str(CONTRACT["version"])
SCORE_RUBRIC: dict[str, Any] = _json(SCORE_RUBRIC_PATH)
SCORE_POLICY_VERSION = str(SCORE_RUBRIC["version"])     # 담당자 채점 정책 버전 — 채점 기준표 버전
CRITERIA_REGISTRY: dict[str, Any] = _json(CRITERIA_REGISTRY_PATH)

# 우리 신청자 유형에 대응하는 담당자 문서 유형 (spec 4.6). 일반형(general)은 데이터로 남지만 고르지 않는다
PRE_STARTUP = "pre_startup"
EARLY_STARTUP = "early_startup"


def document_specs(document_type: str) -> list[dict[str, Any]]:
    """담당자 문서 유형의 항목 계약 목록(양식 순서) — 사본."""
    return json.loads(json.dumps(CONTRACT["documents"][document_type], ensure_ascii=False))


def section_criteria(document_type: str, section_id: str) -> list[str]:
    """그 항목의 담당자 기준 문구(criteria_registry의 criteria — 글자 하나면 한 줄 목록). 없으면 빈 목록."""
    section = CRITERIA_REGISTRY.get("documentTypes", {}).get(document_type, {}).get("sections", {}).get(section_id, {})
    raw = section.get("criteria") if isinstance(section, dict) else None
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    return []
