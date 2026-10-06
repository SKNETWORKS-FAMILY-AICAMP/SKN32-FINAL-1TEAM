"""Orchestration 계약(`sbrain`)의 최소 대역.

`sbrain`은 팀원의 `feature/SB-86-orchestration-flow` 브랜치에만 있어 이 저장소에서는
import할 수 없다. 그래서 `tasks.py`의 세 진입 함수(run_tb1 · run_tb2 · run_tv2)가
테스트되지 않은 채로 남아 있었는데, 계약 경계에서 생기는 문제가 전부 그 파일에 있다.

여기 정의한 모델은 `agent-orchestration/sbrain/models/`와
`sbrain/contracts/tasks.py`의 필드 이름·타입·제약(Field(ge/le/min_length))을 그대로
옮긴 것이다. 계약이 바뀌면 이 파일도 같이 바꿔야 한다 — 그래야 계약 변경이 테스트
실패로 드러난다. 실물을 대신하는 것이 아니라 **계약을 고정하는 장치**다.

`install()`을 호출하면 sys.modules에 꽂히고, 반환된 patcher를 stop()하면 걷힌다.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ── base ──────────────────────────────────────────────────────


class SBModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        protected_namespaces=(),
    )

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


Category = Literal["원페이지", "웹개발", "AI_API"]
PrototypeKind = Literal["html", "svg-onepage"]
ImageFormat = Literal["png", "svg"]
JudgedBy = Literal["htmlParse", "svgTextParse"]
TokenType = Literal["수치금액", "날짜", "고유명사", "기능명"]
ChartType = Literal["bar", "line", "pie"]
Layer = Literal["document", "artifact"]
ReworkMode = Literal["재작성", "재수행"]
ReworkUnit = Literal["묶음", "Task", "섹션", "차트 1건", "표 1건", "부분", "안내 문서"]


class ToolCallExhausted(Exception):
    def __init__(self, error: str = "호출실패", error_kind: str = "일시", tries: int = 3,
                 call_id: str = "", detail: str = "") -> None:
        super().__init__(f"{error}/{error_kind} tries={tries} {detail}")
        self.error, self.error_kind, self.tries = error, error_kind, tries


class FormatError(Exception):
    pass


class ProviderError(Exception):
    pass


# ── domain ────────────────────────────────────────────────────


class Token(SBModel):
    type: TokenType
    value: str
    count: int


class ItemSpec(SBModel):
    item_name: str
    one_line_summary: str
    target_customer: str
    core_features: list[str] = Field(min_length=1)
    category: Category
    keywords: list[str]


class Sentence(SBModel):
    sentence_id: str
    text: str
    is_title: bool
    paragraph_no: int


class PlanSection(SBModel):
    section_code: str
    title: str
    sentences: list[Sentence]


class ChartSpec(SBModel):
    chart_id: str
    type: ChartType
    title: str
    axis_labels: list[str] = Field(min_length=2, max_length=2)


class TableSpec(SBModel):
    table_id: str
    title: str
    headers: list[str]
    rows: list[list[str]]
    source_ref: str


class PlanDoc(SBModel):
    sections: list[PlanSection]
    feature_list: list[str]
    charts: list[ChartSpec]
    tables: list[TableSpec]
    protected_tokens: list[Token]


class Prototype(SBModel):
    entry_file_path: str
    kind: PrototypeKind
    source_text: str
    asset_paths: list[str]
    readme_path: str | None = None
    implemented_features: list[str]


class Infographic(SBModel):
    image_path: str
    format: ImageFormat
    alt_text: str


# ── rework ────────────────────────────────────────────────────


class CheckResult(SBModel):
    passed: bool
    failures: list[str]
    final_action: str | None = None


class ReworkOrder(SBModel):
    task_id: str
    unit: ReworkUnit
    targets: list[str]
    reason: str
    instruction_delta: str
    layer: Layer


class ReworkInput(SBModel):
    mode: ReworkMode
    previous_result_ref: str
    issues: list[str]
    order: ReworkOrder | None = None
    is_final_attempt: bool


# ── scoring ───────────────────────────────────────────────────


class CodeCheck(SBModel):
    no: int = Field(ge=1, le=8)
    name: str
    weight: float
    passed: bool
    detail: str
    # 확장 필드 — 조율 회신(2026-09-29) 2-2에서 합의. 실계약 반영 전까지 대역에만 있다.
    defect_sources: list[Literal["prototype", "infographic"]] = Field(default_factory=list)


class CodeCheckResult(SBModel):
    total: float = Field(ge=0, le=15)
    checks: list[CodeCheck] = Field(min_length=8, max_length=8)
    # 확장 필드 — 조율 회신 2-2. 비어 있지 않으면 산출물층 0, 조율은 카테고리로 재작성 대상을 정한다.
    gate_failures: list[Literal["entry", "secret", "sandbox"]] = Field(default_factory=list)


class FeatureMatchResult(SBModel):
    score: float = Field(ge=0, le=15)
    missing_features: list[str]
    extra_features: list[str]
    findings: list[str]
    judged_by: JudgedBy


class ArtifactScore(SBModel):
    total: float = Field(ge=0)
    code_check: CodeCheckResult
    feature_match: FeatureMatchResult


# ── contracts ─────────────────────────────────────────────────


class TB1In(SBModel):
    feature_list: list[str]
    item_spec: ItemSpec
    category: Category
    instruction: str
    rework_input: ReworkInput | None = None
    plan_doc: PlanDoc | None = None  # 조율이 추가하기로 한 확장 필드(요청 8, A안)


class TB1Out(SBModel):
    prototype: Prototype
    implemented_features: list[str]
    entry_file_path: str
    check: CheckResult


class TB2In(SBModel):
    plan_doc: PlanDoc
    item_spec: ItemSpec
    category: Category
    instruction: str
    rework_input: ReworkInput | None = None


class TB2Out(SBModel):
    infographic: Infographic
    check: CheckResult


class TV2In(SBModel):
    prototype: Prototype
    infographic: Infographic
    feature_list: list[str]
    # 실계약에는 아직 없다. 조율에 추가를 요청한 필드로,
    # 원페이지 계획서 대조가 계획서 원문을 근거로 쓰려면 필요하다. 기본값 None이라
    # 필드가 없는 지금의 실계약과 같은 호출도 그대로 검사된다.
    plan_doc: PlanDoc | None = None


class TV2Out(SBModel):
    artifact_score: ArtifactScore
    code_check: CodeCheckResult
    feature_match: FeatureMatchResult


_MODEL_NAMES = (
    "SBModel", "Token", "ItemSpec", "Sentence", "PlanSection", "ChartSpec", "TableSpec",
    "PlanDoc", "Prototype", "Infographic", "CheckResult", "ReworkOrder", "ReworkInput",
    "CodeCheck", "CodeCheckResult", "FeatureMatchResult", "ArtifactScore",
)
_CONTRACT_NAMES = ("TB1In", "TB1Out", "TB2In", "TB2Out", "TV2In", "TV2Out")

_MODULE_NAMES = (
    "sbrain", "sbrain.models", "sbrain.contracts", "sbrain.contracts.tasks",
    "sbrain.orchestrator", "sbrain.orchestrator.tools", "sbrain.orchestrator.errors",
)


def build_modules() -> dict[str, types.ModuleType]:
    here = globals()

    def module(name: str, names: tuple[str, ...]) -> types.ModuleType:
        mod = types.ModuleType(name)
        for attr in names:
            setattr(mod, attr, here[attr])
        return mod

    models = module("sbrain.models", _MODEL_NAMES)
    contracts_tasks = module("sbrain.contracts.tasks", _CONTRACT_NAMES + _MODEL_NAMES)
    errors = module("sbrain.orchestrator.errors",
                    ("FormatError", "ProviderError", "ToolCallExhausted"))
    tools_mod = types.ModuleType("sbrain.orchestrator.tools")
    tools_mod.Tools = object
    tools_mod.ToolCallExhausted = ToolCallExhausted

    contracts = types.ModuleType("sbrain.contracts")
    contracts.tasks = contracts_tasks
    orchestrator = types.ModuleType("sbrain.orchestrator")
    orchestrator.errors = errors
    orchestrator.tools = tools_mod
    root = types.ModuleType("sbrain")
    root.models, root.contracts, root.orchestrator = models, contracts, orchestrator

    return {
        "sbrain": root,
        "sbrain.models": models,
        "sbrain.contracts": contracts,
        "sbrain.contracts.tasks": contracts_tasks,
        "sbrain.orchestrator": orchestrator,
        "sbrain.orchestrator.tools": tools_mod,
        "sbrain.orchestrator.errors": errors,
    }


def install():
    """sys.modules에 대역을 꽂는다. 반환값의 stop()으로 되돌린다."""
    from unittest.mock import patch

    if any(name in sys.modules and not name.startswith("sbrain") for name in _MODULE_NAMES):
        raise RuntimeError("예상치 못한 모듈 충돌")
    patcher = patch.dict(sys.modules, build_modules())
    patcher.start()
    return patcher
