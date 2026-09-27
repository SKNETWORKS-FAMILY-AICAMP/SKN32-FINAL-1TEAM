"""설정값 — 기능정의서 시트 1 '횟수 · 간격 설정값' 표와 층별 배점 · Threshold, Agent 등록부 값.

- 실행을 시작할 때 전체를 Run.settingsSnapshot에 고정해 끝까지 쓴다.
- PROVISIONAL에 있는 항목은 기준 문서가 값을 정하지 않아 임시로 둔 값이다(잠정).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models.base import SBModel


class RetrySettings(SBModel):
    retry_count: int = 5                 # 재시도 횟수
    retry_interval_sec: float = 2.0      # 재시도 간격 (잠정)


class ResumeSettings(SBModel):
    first_interval_min: float = 15       # 재개 첫 간격
    multiplier: float = 2                # 재개 간격 배수
    max_count: int = 5                   # 재개 횟수
    total_cap_hours: float = 12          # 재개 총 대기 상한


class RedoSettings(SBModel):
    redo_count: int = 2                  # 재수행 횟수
    proofread_redo_count: int | None = None  # 검수 재수행 횟수. None이면 재수행 횟수와 같음

    @property
    def proofread_limit(self) -> int:
        return self.redo_count if self.proofread_redo_count is None else self.proofread_redo_count


class ReworkSettings(SBModel):
    per_bundle: int = 1                  # 재작성 횟수 (묶음마다)


class ProofreadSettings(SBModel):
    concurrency: int = 4                         # 검수 동시 처리 수 (잠정)
    failure_ratio_threshold: float = 0.3         # 검수 실패 비율 기준 (잠정)
    judge_timing: Literal["전체후"] = "전체후"    # 판단 시점: 모든 문장을 본 뒤 (잠정)


class ScoringSettings(SBModel):
    threshold: float = 80
    doc_layer_max: float = 70
    artifact_layer_max: float = 30


class AgentSetting(SBModel):
    """Agent 등록부 값 — 기획서 5-2에 따라 관리자 설정값."""
    provider: str
    model: str
    temperature: float


def _default_agents() -> dict[str, AgentSetting]:
    # 모델명 · 호출처 · 기본 온도는 기준 문서가 정하지 않았다 (잠정).
    # 조율은 OpenAI, 검수는 자체 GPU 서버의 파인튜닝 모델(기획서 5-2 · 5-7).
    return {
        "조율": AgentSetting(provider="openai", model="미정", temperature=0.7),
        "전략": AgentSetting(provider="미정", model="미정", temperature=0.7),
        "작성": AgentSetting(provider="미정", model="미정", temperature=0.7),
        "구현": AgentSetting(provider="미정", model="미정", temperature=0.7),
        "검증-1": AgentSetting(provider="미정", model="미정", temperature=0.0),
        "검증-2": AgentSetting(provider="미정", model="미정", temperature=0.0),
        "검수": AgentSetting(provider="gpu-server", model="미정", temperature=0.2),
    }


def _default_timeouts() -> dict[str, float]:
    # 제한 시간 (Task별, 초). 기준 문서: '구현하면서 정함' (잠정)
    base = {tid: 120.0 for tid in (
        "T-C1", "T-C3", "T-S1", "T-S2", "T-W2", "T-W3", "T-V1", "T-V2", "T-P1", "T-C4",
    )}
    base.update({"T-W1": 300.0, "T-B1": 300.0, "T-B2": 300.0, "T-C2": 30.0, "T-P2": 60.0})
    return base


class Settings(SBModel):
    retry: RetrySettings = Field(default_factory=RetrySettings)
    resume: ResumeSettings = Field(default_factory=ResumeSettings)
    redo: RedoSettings = Field(default_factory=RedoSettings)
    rework: ReworkSettings = Field(default_factory=ReworkSettings)
    proofread: ProofreadSettings = Field(default_factory=ProofreadSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    task_timeouts: dict[str, float] = Field(default_factory=_default_timeouts)
    agents: dict[str, AgentSetting] = Field(default_factory=_default_agents)


# 기준 문서가 값을 정하지 않아 임시로 둔 항목 (문서 · 화면에 '잠정'으로 표시)
PROVISIONAL: dict[str, str] = {
    "retry.retryIntervalSec": "재시도 간격 — 구현하면서 정함",
    "taskTimeouts": "제한 시간(Task별) — 구현하면서 정함",
    "proofread.concurrency": "검수 동시 처리 수 — 구현하면서 정함",
    "proofread.failureRatioThreshold": "검수 실패 비율 기준 — 구현하면서 정함",
    "proofread.judgeTiming": "검수 실패 비율 판단 시점 — 구현하면서 정함",
    "agents": "Agent별 모델 · 호출처 · 기본 온도, 실행 시작 시점 고정 — 기준 문서에 없음",
}


class SettingsProvider:
    """관리자 설정값 공급처. 실행 시작 때 snapshot()으로 고정한다."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    def current(self) -> Settings:
        return self._settings

    def update(self, settings: Settings) -> None:
        self._settings = settings

    def snapshot(self) -> dict:
        return self._settings.dump()
