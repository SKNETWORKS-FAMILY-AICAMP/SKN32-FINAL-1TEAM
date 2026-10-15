"""시트 4 채점 관련 타입.

배점 상한(문서층 70 · 산출물층 30)은 관리자 설정값이라 모델에서 상한을 고정하지 않는다.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .base import JudgedBy, Layer, Phase, SBModel, ext
from .rework import BundleUsage, ReworkComparison, ReworkDiff, ReworkOrder


class DocScoreItem(SBModel):
    item_code: str
    score: float
    max_score: float
    evidence_locator: str | None = None
    comment: str


class DocScore(SBModel):
    total: float = Field(ge=0)
    items: list[DocScoreItem]


class CodeCheck(SBModel):
    no: int = Field(ge=1, le=8)
    name: str
    weight: float
    passed: bool
    detail: str
    # 확장 — 이름은 구현 · 검증-2 담당 코드와 글자까지 같아야 한다 (담당자는 model_fields에 이 이름이 있을 때만 채운다)
    defect_sources: list[Literal["prototype", "infographic"]] = ext(
        default_factory=list, note="미충족 결함이 있는 산출물. 웹개발 · AI API 2번만 채움")


class CodeCheckResult(SBModel):
    total: float = Field(ge=0, le=15)
    checks: list[CodeCheck] = Field(min_length=8, max_length=8)
    gate_failures: list[Literal["entry", "secret", "sandbox"]] = ext(
        default_factory=list, note="통과 필수 조건 중 어긴 것. 비어 있지 않으면 산출물층 0")


class FeatureMatchResult(SBModel):
    score: float = Field(ge=0, le=15)
    missing_features: list[str]
    extra_features: list[str]
    findings: list[str]
    judged_by: JudgedBy
    # 확장 — 흐름은 이 칸들로만 가른다. findings 문구로 가르지 않는다
    withheld: bool = ext(False, note="대조 판정 보류. 0점 합산 · 화면 '대조 불가' · 관리자 알림")
    withheld_reason: str | None = ext(None, note="보류 사유 오류코드 (예: E-V2-NOFEATURE)")
    partial_features: list[str] = ext(default_factory=list, note="부분 인정 기능 이름. 1.4판 부분 0.5")


class ArtifactScore(SBModel):
    total: float = Field(ge=0)
    code_check: CodeCheckResult
    feature_match: FeatureMatchResult


class ScoreReport(SBModel):
    doc_score: DocScore
    artifact_score: ArtifactScore | None = None
    total: float = Field(ge=0, le=100)
    threshold: float
    passed: bool
    failed_task_ids: list[str]
    rework_orders: list[ReworkOrder]
    rework_usage: list[BundleUsage]
    phase: Phase
    display_score: float = Field(ge=0, le=100)
    carried_over_layer: Layer | None = None
    rework_diff: list[ReworkDiff]
    comparisons: list[ReworkComparison]
    notices: list[str]
    settings_snapshot: dict[str, Any]
    rubric_version: str
