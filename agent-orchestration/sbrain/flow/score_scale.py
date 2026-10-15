"""산출물층 환산 규칙 (재량 없음, spec 4.6 D9 ~ D12) — 공식은 이 모듈 한 곳에만 둔다.

검증-2 원점수(코드 점검 total c · 계획서 대조 score f, 각각 0 ~ 15)를 그 실행 건 설정 사본의 배점
(D = scoring.docLayerMax · C = scoring.codeCheckMax · P = scoring.featureMatchMax)으로 환산한다.

- 코드 점검 환산 = c × C ÷ 15, 계획서 대조 환산 = f × P ÷ 15, 산출물층 환산 = 둘의 합. 산출물층 만점 = C + P.
- 통과 필수 조건 실패(codeCheck.gateFailures가 비어 있지 않음)면 코드 점검 · 대조 · 산출물층 환산 모두 0이다.
  산출물(artifactScore · codeCheck)을 보는 곳(전후 비교 · 판정 G-02b)은 이 칸으로 판단한다. 실행 기록의 출력 요약만 보는 곳
  (관리자 조회 · 통계 줄)은 생산자가 이 경우 코드 점검 · 대조 원점수를 0으로 낸다는 것에 기댄다.
- 코드 점검 항목 줄: 해당 항목(applicable) 배점 합 W. 해당 항목 i의 환산 배점 = C × weight_i ÷ W, 환산 점수 =
  C × earned_i ÷ W. 해당 없음 항목은 환산 배점 · 점수 0, W = 0이면 모든 항목 0. earned가 비면(옛 산출물) 통과면 배점 · 아니면 0.
- 반올림(잠정, PROVISIONAL scoring.scaledRounding): 환산 값은 소수 둘째 자리(반올림은 0.5 올림). 항목 줄 환산 배점 합 = C,
  환산 점수 합 = 층 값이 되도록 반올림 차이를 해당 항목 하나에 몰아준다 — 환산 점수 차이는 환산 점수가 환산 배점을 넘지
  않는 항목에. 총점 · 표시 점수는 지금처럼 소수 첫째 자리.
- 배점 0(D12): C · P · D가 0이면 그 층 환산은 0이다. 0을 기본값(70 · 15)으로 바꾸지 않고, 나눗셈 오류만 막는다.
  배점 칸이 없는 옛 설정 사본은 기본값(ScoringSettings — 70 · 15 · 15)으로 읽는다.

쓰는 곳: 재작성 전후 비교(sbrain_flow._cycle_end), 판정 G-02b(조율 — 이 모듈을 import한다), 관리자 조회(reads.py),
통계 줄(log_stats.py). 다른 곳에 공식을 다시 쓰지 않는다. 실행 기록의 출력 요약(원점수)은 바꾸지 않는다 — 환산은 읽을 때 ·
통계 줄을 만들 때 그 실행 건 설정 사본으로 한다.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..models.scoring import ArtifactScore, CodeCheck
from ..orchestrator.settings import ScoringSettings, Settings

RAW_MAX = 15.0          # 검증-2 원점수 만점 (코드 점검 · 계획서 대조 각각)
SCALED_DIGITS = 2       # 환산 값 자릿수 (잠정, PROVISIONAL scoring.scaledRounding)
DISPLAY_DIGITS = 1      # 표시 점수 자릿수 (총점과 같음)

_DEFAULTS = ScoringSettings()
# 기준 문서 형식 '얻은 점수/배점점 — 근거'의 앞 숫자 부분 (구현 · 검증-2 담당 detail 예: "2/3점 — 근거")
_DETAIL_PREFIX = re.compile(r"^(\s*)\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*점")


@dataclass(frozen=True)
class ScoreMaxes:
    """그 실행 건 설정 사본의 층별 배점 — 문서층 D · 코드 점검 C · 계획서 대조 P."""
    doc: float = float(_DEFAULTS.doc_layer_max)
    code_check: float = float(_DEFAULTS.code_check_max)
    feature_match: float = float(_DEFAULTS.feature_match_max)

    @property
    def artifact(self) -> float:
        """산출물층 만점 C + P."""
        return round_scaled(self.code_check + self.feature_match)

    def as_stats(self) -> dict[str, float]:
        """통계 줄 data.maxScores 값 (층 이름 → 만점, 숫자만)."""
        return {"docScore": self.doc, "codeCheck": self.code_check, "featureMatch": self.feature_match}


@dataclass(frozen=True)
class ScaledArtifact:
    """산출물층 환산 값. 원점수가 없으면(None) 그 칸도 None, 산출물층은 두 칸이 모두 있을 때만."""
    code_check_score: float | None
    feature_match_score: float | None
    artifact_layer_score: float | None


def _number(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def score_maxes(source: Settings | ScoringSettings | Mapping[str, Any] | None = None) -> ScoreMaxes:
    """D · C · P 읽기 — Settings · ScoringSettings · 설정 사본 사전(Run.settingsSnapshot, JSON 이름) · None.

    칸이 없는(옛 사본) · 숫자가 아닌 값은 기본값(70 · 15 · 15), 0은 0 그대로다.
    """
    if isinstance(source, Settings):
        source = source.scoring
    if isinstance(source, ScoringSettings):
        return ScoreMaxes(float(source.doc_layer_max), float(source.code_check_max), float(source.feature_match_max))
    scoring = source.get("scoring") if isinstance(source, Mapping) else None
    if not isinstance(scoring, Mapping):
        scoring = {}
    d = ScoreMaxes()
    return ScoreMaxes(_number(scoring.get("docLayerMax"), d.doc), _number(scoring.get("codeCheckMax"), d.code_check),
                      _number(scoring.get("featureMatchMax"), d.feature_match))


def round_scaled(value: float) -> float:
    """환산 값 반올림 — 소수 둘째 자리, 0.5 올림 (잠정)."""
    return float(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-SCALED_DIGITS), rounding=ROUND_HALF_UP))


def _cents(value: float) -> int:
    return round(round_scaled(value) * 10 ** SCALED_DIGITS)


def _from_cents(cents: int) -> float:
    return cents / 10 ** SCALED_DIGITS


def scale_raw(raw: float, layer_max: float) -> float:
    """원점수(0 ~ 15) × 배점 ÷ 15, 소수 둘째 자리. 배점이 0이면 0."""
    if not layer_max:
        return 0.0
    return round_scaled(raw * layer_max / RAW_MAX)


def scale_artifact_scores(code_check_raw: float | None, feature_match_raw: float | None, maxes: ScoreMaxes, *,
                          gate_failed: bool = False) -> ScaledArtifact:
    """원점수 두 개 → 환산 값. gate_failed(통과 필수 조건 실패)면 있는 칸은 모두 0. 원점수가 None이면 그 칸도 None."""
    def one(raw: float | None, layer_max: float) -> float | None:
        if raw is None:
            return None
        return 0.0 if gate_failed else scale_raw(raw, layer_max)
    code, feature = one(code_check_raw, maxes.code_check), one(feature_match_raw, maxes.feature_match)
    layer = round_scaled(code + feature) if code is not None and feature is not None else None
    return ScaledArtifact(code, feature, layer)


def scale_artifact(artifact: ArtifactScore, maxes: ScoreMaxes) -> ScaledArtifact:
    """검증-2 산출물층 점수(artifactScore) → 환산 값. 통과 필수 조건 실패는 codeCheck.gateFailures 칸으로 판단한다."""
    return scale_artifact_scores(artifact.code_check.total, artifact.feature_match.score, maxes,
                                 gate_failed=bool(artifact.code_check.gate_failures))


def _number_text(value: float) -> str:
    return f"{value:.{SCALED_DIGITS}f}".rstrip("0").rstrip(".")


def scale_detail(detail: str, score: float, weight: float) -> str:
    """'얻은 점수/배점점 — 근거'의 앞 숫자만 '환산 점수/환산 배점'으로 바꾼다. 앞 숫자 패턴이 없으면 그대로(근거 글도 그대로)."""
    m = _DETAIL_PREFIX.match(detail)
    if m is None:
        return detail
    return f"{m.group(1)}{_number_text(score)}/{_number_text(weight)}점{detail[m.end():]}"


def _earned(ch: CodeCheck) -> float:
    if not ch.applicable:
        return 0.0
    if ch.earned is not None:
        return float(ch.earned)
    return float(ch.weight) if ch.passed else 0.0   # 옛 산출물 — 통과면 배점, 아니면 0


def _give(values: list[int], diff: int, candidates: list[int], ok) -> None:
    """반올림 차이 diff를 받을 수 있는(ok) 첫 후보 하나에 몰아준다. 받을 곳이 없으면 그대로 둔다."""
    if not diff:
        return
    for i in candidates:
        if ok(i, values[i] + diff):
            values[i] += diff
            return


def scale_code_check_items(checks: list[CodeCheck], code_check_max: float, *, layer_score: float | None = None,
                           gate_failed: bool = False) -> list[CodeCheck]:
    """코드 점검 항목 줄을 그 실행 건 배점 C 기준으로 다시 계산한 사본 (CodeCheck 모양 — 원래 항목은 바꾸지 않는다).

    weight = 환산 배점, earned = 환산 점수, detail = 앞 숫자를 '환산 점수/환산 배점'으로 바꾼 글('해당 없음 — 이유'는 그대로).
    no · name · passed · applicable · defectSources는 원본과 같다. layer_score: 환산 점수 합을 맞출 층 값(코드 점검 환산) —
    없으면 항목에서 계산(C × Σearned ÷ W). gate_failed면 환산 점수는 모두 0(배점은 그대로 나눔).
    """
    weights = [float(ch.weight) if ch.applicable else 0.0 for ch in checks]
    total_weight = sum(weights)
    applicable = [i for i, ch in enumerate(checks) if ch.applicable and weights[i] > 0]
    if total_weight <= 0 or not code_check_max:
        w_cents = [0] * len(checks)
        s_cents = [0] * len(checks)
    else:
        earned = [0.0 if gate_failed else _earned(ch) for ch in checks]
        w_cents = [_cents(code_check_max * w / total_weight) if w > 0 else 0 for w in weights]
        s_cents = [_cents(code_check_max * e / total_weight) if weights[i] > 0 else 0 for i, e in enumerate(earned)]
        _give(w_cents, _cents(code_check_max) - sum(w_cents), applicable, lambda i, v: v >= max(s_cents[i], 0))
        if gate_failed:
            target = 0
        elif layer_score is not None:
            target = _cents(layer_score)
        else:
            target = _cents(code_check_max * sum(earned) / total_weight)
        _give(s_cents, target - sum(s_cents), applicable, lambda i, v: 0 <= v <= w_cents[i])
    out = []
    for ch, wc, sc in zip(checks, w_cents, s_cents):
        weight, score = _from_cents(wc), _from_cents(sc)
        detail = scale_detail(ch.detail, score, weight) if ch.applicable else ch.detail
        out.append(ch.model_copy(update={"weight": weight, "earned": score, "detail": detail}))
    return out


def display_score(score: float, layer_max: float) -> float:
    """표시 점수(100점 환산) = 점수 ÷ 만점 × 100, 소수 첫째 자리. 만점이 0이면 0 (나눗셈 오류를 막는다, D12)."""
    if not layer_max:
        return 0.0
    return round(score / layer_max * 100, DISPLAY_DIGITS)


def scaled_report_fields(maxes: ScoreMaxes, artifact: ArtifactScore | None = None) -> dict[str, Any]:
    """점수 보고서 환산 칸 (파이썬 이름 → 값) — ScoreReport(**칸) · model_copy(update=칸)에 그대로 쓴다.

    artifact가 없으면(G-02a 보고서) doc_layer_max만. 있으면(G-02b) doc_layer_max(D) · code_check_score · code_check_max(C) ·
    feature_match_score · feature_match_max(P) · artifact_layer_score · artifact_layer_max(C + P) · code_check_items(항목 줄 8칸).
    검증-2 원점수(artifact_score)는 부르는 쪽이 그대로 싣는다.
    """
    fields: dict[str, Any] = {"doc_layer_max": maxes.doc}
    if artifact is None:
        return fields
    scaled = scale_artifact(artifact, maxes)
    gate_failed = bool(artifact.code_check.gate_failures)
    fields.update(
        code_check_score=scaled.code_check_score, code_check_max=maxes.code_check,
        feature_match_score=scaled.feature_match_score, feature_match_max=maxes.feature_match,
        artifact_layer_score=scaled.artifact_layer_score, artifact_layer_max=maxes.artifact,
        code_check_items=scale_code_check_items(artifact.code_check.checks, maxes.code_check,
                                                layer_score=scaled.code_check_score, gate_failed=gate_failed))
    return fields


__all__ = [
    "DISPLAY_DIGITS", "RAW_MAX", "SCALED_DIGITS", "ScaledArtifact", "ScoreMaxes", "display_score", "round_scaled",
    "scale_artifact", "scale_artifact_scores", "scale_code_check_items", "scale_detail", "scale_raw",
    "scaled_report_fields", "score_maxes",
]
