"""전략 · 작성 · 검증-1 담당자 함수(F01 ~ F19)의 가짜 LLM 응답 — 목적(F번호)별 (네트워크 없음, spec 7절 2번).

- partner_reply(request): 요청 목적(F번호)에 맞는 JSON. F16은 항목 규칙(exactItems · maxLines)과 울타리 featureList를 지켜
  구조 검사를 통과하는 본문을, F18은 요청한 flowType을 돌려준다.
- PartnerProvider: 목적별 스크립트('timeout' · 'rate_limit' · 'bad_request' · JSON 글자)와 받은 요청을 모으는 가짜 호출처.
- partner_tools: 가짜 호출처 · 메모리 파일 저장소로 만든 tools(실행 건 '실행').
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

from sbrain.agents.partner_sw.purposes import PURPOSES
from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import ProviderError
from sbrain.orchestrator.files import MemoryFileStore
from sbrain.orchestrator.settings import Settings
from sbrain.orchestrator.tools import CallSink, LLMRequest, Tools, ToolsConfig, ToolsContext

PARTNER_TASKS = ("T-S1", "T-S2", "T-W1", "T-W2", "T-V1")   # LLM을 부르는 실구현 Task (T-W3는 규칙 코드)
BODY_MARK = "가짜본문표시"                                  # F16 본문에 들어가는 표시 — 기록에 새지 않는지 볼 때

BASE_REPLIES: dict[str, dict[str, Any]] = {
    "F01": {"summary": "근거 요약", "selectedSourceRefs": []},
    "F02": {"coreFeatures": ["회원 등록·조회", "수업 예약"], "targetCustomer": "헬스장", "deliverables": ["웹 서비스"],
            "differentiation": "예약과 회원 관리를 한곳에서"},
    "F03": {"marketNeed": ["회원 관리 수요"], "marketTrend": ["디지털 전환"], "developmentNeed": ["예약 자동화"]},
    "F04": {"competitors": [{"name": "경쟁 서비스", "productOrService": "예약 앱", "relationship": "직접경쟁",
                             "evidenceRefs": [], "confidence": "low"}]},
    "F05": {"representativeCapabilities": ["운영 경험"], "memberCapabilities": ["개발"], "gaps": []},
    "F06": {"finalGoal": "서비스 출시 계획", "core_technologies": ["회원 등록·조회", "수업 예약"], "kpi": []},
    "F07": {"methods": [{"technology": "웹", "method": "자체 개발", "acquisition": "내부"}],
            "architecture": {"layers": ["화면", "서버", "DB"]}},
    "F08": {"phases": [], "deliverables": ["시제품"]},
    "F09": {"stages": [{"stage": "1단계", "features": ["회원 등록·조회"], "plan": "개발 계획"}]},
    "F10": {"earlyAccess": ["지역 헬스장 제휴"], "matureStage": ["구독 확대"]},
    "F11": {"customer": "헬스장", "revenue": "월 구독", "channels": ["직접 영업"]},
    "F12": {"competition": "예약 · 회원 통합", "entry": "지역 거점", "businessModel": "구독", "investment": "",
            "socialValue": ""},
    "F13": {"equipment": [], "hiring": [], "partners": [], "no_hires": True, "no_equipment": True, "no_partners": True},
    "F14": {"generatedText": "제공된 예산 설명"},
    "F15": {"generatedText": "제공된 일정 설명"},
    "F18": {"nodes": ["사용자", "예약", "회원 관리"], "visualStyle": {"palette": ["#112233", "#445566", "#778899"],
                                                              "background": "#ffffff", "accent": "#000000"}},
    "F19": {"passed": True, "issues": [], "warnings": [], "needsUserConfirmation": [], "sourceRefs": [],
            "generatedText": "검증"},
}


def payload(request: LLMRequest) -> dict[str, Any]:
    return json.loads(request.messages[-1]["content"])


def _section_text(p: dict[str, Any]) -> str:
    """항목 규칙을 지키는 본문 — maxLines 1이면 한 줄, exactItems n이면 번호 n줄. 울타리 기능 이름을 모두 담는다."""
    spec = p.get("section_spec") or {}
    rules = spec.get("rules") or {}
    feats = " · ".join((p.get("source_data") or {}).get("strategy_limits", {}).get("featureList") or [])
    head = f"{feats} 기능을 개발하는 계획임 {BODY_MARK}." if feats else f"서비스를 개발하는 계획임 {BODY_MARK}."
    if rules.get("maxLines") == 1:
        return head
    n = rules.get("exactItems")
    if n:
        return "\n".join([f"1. {head}"] + [f"{i}. 세부 추진 계획임." for i in range(2, n + 1)])
    return f"{head}\n추진 방향을 정리한 계획임."


def partner_reply(request: LLMRequest, overrides: dict[str, Any] | None = None) -> str:
    """목적(F번호)에 맞는 가짜 응답 JSON. overrides[목적]이 있으면 그 사전(또는 함수(request) → 사전)으로 바꾼다."""
    purpose = request.metadata["purpose"]
    override = (overrides or {}).get(purpose)
    if callable(override):
        reply = override(request)
    elif override is not None:
        reply = override
    elif purpose == "F16":
        reply = {"generatedText": _section_text(payload(request)), "facts": [], "sourceRefs": []}
    elif purpose == "F18":
        reply = {**BASE_REPLIES["F18"], "flowType": payload(request).get("flow_type", "USER_FLOW")}
    else:
        reply = BASE_REPLIES[purpose]
    return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)


class PartnerProvider:
    """목적별로 답하는 가짜 호출처. scripts[목적] 또는 scripts[(목적, 항목 키)]의 결과를 차례로 쓴다:
    'timeout' · 'rate_limit'(429, 일시) · 'bad_request'(400, 입력) · 그 밖의 글자는 응답 본문. 받은 요청을 모은다."""

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        self.lock = threading.Lock()
        self.requests: list[LLMRequest] = []
        self.scripts: dict[Any, list[str]] = {}
        self.overrides = dict(overrides or {})
        self.hook: Callable[[LLMRequest], None] | None = None   # 응답 전에 부르는 함수 (동시 수 시험)

    def complete(self, request: LLMRequest) -> str:
        with self.lock:
            self.requests.append(request)
            purpose, item = request.metadata["purpose"], request.metadata.get("item_key")
            queue = self.scripts.get((purpose, item)) or self.scripts.get(purpose)
            outcome = queue.pop(0) if queue else None
        if self.hook is not None:
            self.hook(request)
        if outcome == "timeout":
            raise TimeoutError()
        if outcome == "rate_limit":
            raise ProviderError("429", status=429)
        if outcome == "bad_request":
            raise ProviderError("400", status=400)
        if outcome is not None:
            return outcome
        return partner_reply(request, self.overrides)

    def purposes(self) -> list[str]:
        return [r.metadata["purpose"] for r in self.requests]


def partner_tools(provider: Any, task_id: str, *, retry: int = 2, files: MemoryFileStore | None = None,
                  settings: Settings | None = None) -> tuple[Tools, CallSink, MemoryFileStore]:
    """그 Task의 기본 설정(모델 · 목적별 모델)을 입힌 tools. LLM을 부르지 않는 Task(T-W3)는 호출처 없음."""
    s = settings or Settings()
    row = s.tasks.get(task_id)
    sink, store = CallSink(), files or MemoryFileStore()
    cfg = ToolsConfig(agent="시험", provider=row.provider if row else None, model=row.model if row else None,
                      temperature=None, timeout_sec=10, retry_count=retry, retry_interval_sec=0,
                      purpose_models=dict(row.purpose_models) if row else {})
    ctx = ToolsContext(run_id="run-1", execution_id=f"exec-{task_id}", task_id=task_id,
                       providers={"openai": provider}, sink=sink, now=utc_now, sleep=lambda s: None,
                       files=store, run_progress=lambda: "실행")
    return Tools(cfg, ctx), sink, store


def respond_partner(llm: Any, overrides: dict[str, Any] | None = None,
                    fallback: Callable[[LLMRequest], str] | None = None) -> None:
    """FakeLLM(task_id별 응답)에 실구현 Task의 목적별 응답을 단다. 목적이 F번호가 아니면 fallback(없으면 {"ok": true})."""
    def reply(request: LLMRequest) -> str:
        if request.metadata.get("purpose") in PURPOSES:
            return partner_reply(request, overrides)
        return fallback(request) if fallback else '{"ok": true}'
    for task_id in PARTNER_TASKS:
        llm.respond(task_id, reply)
