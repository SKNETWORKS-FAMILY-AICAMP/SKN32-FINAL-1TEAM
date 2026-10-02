"""설정값 — 기능정의서 시트 1 '횟수 · 간격 설정값' 표와 층별 배점 · Threshold, Agent 등록부 값.

- 실행을 시작할 때 전체를 Run.settingsSnapshot에 고정해 끝까지 쓴다.
- PROVISIONAL에 있는 항목은 기준 문서가 값을 정하지 않아 임시로 둔 값이다(잠정).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models.base import SBModel, ext


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
    deviation_cap: float | None = ext(None, note="문서층 재채점 편차 상한 — 웹 verification_policies 값을 담아만 둔다 (검증-1 연동 전)")


# 추론 강도 — OpenAI 추론 모델의 reasoning_effort 값 (모델마다 받는 값이 다르다)
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class AgentSetting(SBModel):
    """Agent 등록부 값 — 기획서 5-2에 따라 관리자 설정값.

    temperature가 None이면 호출에 싣지 않는다. 추론 모델은 온도 대신 추론 강도(reasoning_effort, 확장)를 쓴다.
    """
    provider: str
    model: str
    temperature: float | None
    reasoning_effort: ReasoningEffort | None = None


def _default_agents() -> dict[str, AgentSetting]:
    # 모델명 · 호출처 · 기본 온도는 기준 문서가 정하지 않았다 (잠정).
    # 조율은 OpenAI, 검수는 자체 GPU 서버의 파인튜닝 모델(기획서 5-2 · 5-7).
    # 조율 모델은 사용자 지정(2026-09-30): 후보 gpt-5-mini · gpt-5.6-luna · gpt-6-luna 중 가장 싼 gpt-6-luna,
    # 추론 강도 low. 추론 모델이라 온도를 보내지 않는다.
    return {
        "조율": AgentSetting(provider="openai", model="gpt-6-luna", temperature=None, reasoning_effort="low"),
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
    "agents": "Agent별 모델 · 호출처 · 기본 온도 · 추론 강도, 실행 시작 시점 고정 — 기준 문서에 없음 "
              "(조율 gpt-6-luna · low는 사용자 지정, 나머지 Agent는 미정)",
    "scoring.deviationCap": "문서층 재채점 편차 상한 (확장) — 웹 verification_policies.deviation_cap을 담아만 둔다. "
                            "검증-1 연동 전이라 쓰는 곳 없음",
    # 워커 (sbrain/worker.py · flow/service.py) — 실행 건 설정값이 아니라 워커 프로세스 값이다
    "worker.pollSec": "할 일이 없을 때 쉬는 시간 1초 (SBRAIN_WORKER_POLL_SEC)",
    "worker.threads": "워커 스레드 4 (SBRAIN_WORKER_THREADS)",
    "worker.leaseSec": "점유 시간 120초 (SBRAIN_WORKER_LEASE_SEC) — 워커가 멈추면 이만큼 뒤에 다른 워커가 이어받는다",
    "worker.heartbeatSec": "하트비트 30초 — 점유 시간의 1/4",
    "worker.maxStartClaims": "시작 요청을 가져간 횟수 상한 3 — 넘으면 E-C1-TIMEOUT으로 끝낸다",
    "worker.errorBackoff": "단계 밖 오류 뒤 그 실행 건을 점유 시간만큼 다시 가져가지 않는다",
    # 재작성 요청 (flow/service.py) — 실행 건 설정값이 아니라 명령 창구 값이다
    "reworkRequest.collectSec": "재작성 요청을 모으는 시간 2초 — 같은 화면에서 첫 요청부터 이 시간 안의 요청을 "
                                "재작성 한 번으로 합친다. 그동안 워커는 그 실행 건을 가져가지 않는다",
    "reworkRequest.leaseRetrySec": "재작성 요청의 점유 재시도 최대 5초 — 그래도 못 잡으면 BUSY",
    # 진행 기다리기 (flow/service.py wait_project) — 명령 창구 값이다
    "waitProject.timeoutSec": "wait_project 기본 제한 시간 60초 — 넘기면 그때의 진행 상태를 그대로 준다",
    "waitProject.pollSec": "wait_project가 DB를 다시 읽는 간격 0.5초",
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
