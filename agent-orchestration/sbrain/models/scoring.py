"""시트 4 채점 관련 타입.

배점 상한(문서층 70 · 산출물층 30)은 관리자 설정값이라 모델에서 상한을 고정하지 않는다.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .base import JudgedBy, Layer, Phase, SBModel
from .rework import BundleUsage, ReworkComparison, ReworkDiff, ReworkOrder

# 산출물층 환산 칸을 기준 문서 타입에 없는 모양(화면 · 관리자 조회)에 실을 때의 확장 note
SCALE_NOTE = "산출물층 환산"


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
    # 미충족 결함이 있는 산출물. 웹개발 · AI API 2번만 채움.
    # 이름은 구현 · 검증-2 담당 코드와 글자까지 같아야 한다 (담당자는 model_fields에 이 이름이 있을 때만 채운다)
    defect_sources: list[Literal["prototype", "infographic"]] = Field(default_factory=list)
    # 얻은 점수 · 해당 여부. 이름은 구현 · 검증-2 담당 코드와 글자까지 같다. 옛 산출물 호환으로 범위 검사는
    # 음수 금지만 둔다(0 이상 weight 이하는 생산자 규칙). 해당 없음(applicable 거짓) 항목은 passed 참 · earned 0
    earned: float | None = Field(None, ge=0)   # 검사 배점(weight) 기준 얻은 점수. 비면 옛 산출물(값 없음)
    applicable: bool = True                    # 검사할 대상이 있는가 — 거짓이면 해당 없음(배점에서 빼고 다시 환산한 항목)


class CodeCheckResult(SBModel):
    total: float = Field(ge=0, le=15)
    checks: list[CodeCheck] = Field(min_length=8, max_length=8)
    # 통과 필수 조건 중 어긴 것. 비어 있지 않으면 산출물층 0
    gate_failures: list[Literal["entry", "secret", "sandbox"]] = Field(default_factory=list)


class FeatureMatchResult(SBModel):
    score: float = Field(ge=0, le=15)
    missing_features: list[str]
    extra_features: list[str]
    findings: list[str]
    judged_by: JudgedBy
    # 흐름은 아래 칸들로만 가른다. findings 문구로 가르지 않는다
    withheld: bool = False                  # 대조 판정 보류. 0점 합산 · 화면 '대조 불가' · 관리자 알림
    withheld_reason: str | None = None      # 보류 사유 오류코드 (예: E-V2-NOFEATURE)
    partial_features: list[str] = Field(default_factory=list)  # 부분 인정 기능 이름. 1.4판 부분 0.5


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
    # 환산 칸 — 그 실행 건 설정 사본 배점으로 환산한 층 점수 · 만점과 코드 점검 항목 줄.
    # G-02a 보고서는 doc_layer_max만 채우고 나머지는 비운다. artifact_score(검증-2 원점수)는 그대로 싣는다
    doc_layer_max: float | None = None          # 문서층 만점 D (설정 사본 scoring.docLayerMax)
    code_check_score: float | None = None       # 코드 점검 환산 점수
    code_check_max: float | None = None         # 코드 점검 만점 C (설정 사본 scoring.codeCheckMax)
    feature_match_score: float | None = None    # 계획서 대조 환산 점수
    feature_match_max: float | None = None      # 계획서 대조 만점 P (설정 사본 scoring.featureMatchMax)
    artifact_layer_score: float | None = None   # 산출물층 환산 점수 (코드 점검 + 계획서 대조)
    artifact_layer_max: float | None = None     # 산출물층 만점 C + P
    # 코드 점검 항목 줄(CodeCheck 모양: weight = 환산 배점, earned = 환산 점수, detail 앞 숫자 = 환산 점수/환산 배점).
    # G-02a 보고서는 빈 목록
    code_check_items: list[CodeCheck] = Field(default_factory=list)
