"""시트 4 채점 관련 타입.

배점 상한(문서층 70 · 산출물층 30)은 관리자 설정값이라 모델에서 상한을 고정하지 않는다.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import JudgedBy, Layer, Phase, SBModel
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


class CodeCheckResult(SBModel):
    total: float = Field(ge=0, le=15)
    checks: list[CodeCheck] = Field(min_length=8, max_length=8)


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
