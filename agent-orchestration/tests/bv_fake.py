"""구현 · 검증-2 실구현(T-B1 · T-B2 · T-V2)의 가짜 응답 — 목적별 (네트워크 없음).

- HTML · 변형(외부 의존 · 샌드박스 멈춤 · 샌드박스 무시 · 비밀값): T-B1 응답 코드블록 안의 HTML. 모두 MARK를 담는다(기록에
  새지 않는지 볼 때).
- bv_reply(request): 목적에 맞는 응답 — 'T-B1 HTML 생성' 코드블록, 'T-B2 인포그래픽 정보 추출' JSON, '사업 분야 판정(색)'
  분야 JSON(outdoor → green), '계획서 대조 요소: …'
  요소 JSON, '계획서 대조: …' 요소 판정 · 세 단계 판정 JSON.
- BvProvider: 목적(또는 목적 머리말)별 스크립트('timeout' · 'rate_limit' · 'bad_request' · 'quota' · 'overloaded' · 'boom' ·
  글자)와 받은 요청 · 최대 동시 수. 실패 값은 스텁 가짜 호출처와 같은 raise_fake_failure.
- EchoImage: 가짜 이미지 호출처 — 'echo'(받은 뼈대 그림을 그대로 → 칸 수가 맞다) · 'tiny'(1×1 → 칸 수 불일치) ·
  'garbage'(PNG 아님 → 그림 해석 오류) · 'timeout' · 'rate_limit' · 'quota'(429 + insufficient_quota) ·
  'overloaded'(503 + server_is_overloaded).
- bv_tools: 그 Task의 기본 설정(이미지 설정 포함)을 입힌 tools와 메모리 파일 저장소(실행 건 '실행').
- respond_bv(llm): FakeLLM(task_id별 응답)에 세 Task의 목적별 응답을 단다.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

from sbrain.agents.stubs import FakeImage, raise_fake_failure
from sbrain.models.clock import utc_now
from sbrain.orchestrator.files import MemoryFileStore
from sbrain.orchestrator.settings import Settings
from sbrain.orchestrator.tools import CallSink, ImageResponse, LLMRequest, Tools, ToolsConfig, ToolsContext

BV_TASKS = ("T-B1", "T-B2", "T-V2")
MARK = "가짜산출물표시"                 # HTML · 인포그래픽 내용에 들어가는 표시 — 기록에 새지 않는지 볼 때
ELEMENTS = ["입력칸", "결과 표시"]      # 가짜 요소 뽑기 응답

HTML = ("<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>헬스온</title>\n"
        "<!-- IMPLEMENTED_FEATURES: 회원 등록·조회 | 수업 예약 -->\n"
        "<style>body { color: #0F172A; background-color: #FFFFFF; }</style></head><body><h1>헬스온</h1>\n"
        f"<p>{MARK}</p>\n"
        "<button id=\"btn-member\" data-feature=\"회원 등록·조회\">회원 등록·조회</button>\n"
        "<button id=\"btn-book\" data-feature=\"수업 예약\">수업 예약</button><div id=\"out\"></div>\n"
        "<script>document.getElementById('btn-member').addEventListener('click', function(){"
        "document.getElementById('out').textContent='등록됨';});\n"
        "document.getElementById('btn-book').addEventListener('click', function(){"
        "document.getElementById('out').textContent='예약됨';});</script>\n</body></html>")
SCRIPT_END = "</script>"
VARIANTS = {
    "pass": HTML,
    "dependency": HTML.replace("<head>", '<head><script src="https://cdn.example.com/x.js"></script>'),
    "halting": HTML.replace(SCRIPT_END, "localStorage.setItem('k', 'v');" + SCRIPT_END, 1),
    "ignored": HTML.replace(SCRIPT_END, "alert('예약됨');" + SCRIPT_END, 1),
    "secret": HTML.replace(SCRIPT_END, 'const apiKey = "abcd1234efgh5678";' + SCRIPT_END, 1),
}

# 웹개발 · AI API · 원페이지 지면에 필요한 값을 모두 담는다. 숫자를 넣지 않는다(계획서에 없는 수치로 걸리지 않게).
CONTENT = {
    "item_name": "헬스온", "features": ["회원 등록·조회", "수업 예약"], "target_users": "헬스장",
    "problem": f"회원 관리가 번거롭다 {MARK}", "solution": "회원과 예약을 한곳에서 관리한다",
    "revenue_unit_price": "월 구독", "timeline_baseline": "개발 뒤 출시",
    "flow_steps": ["회원 등록", "수업 고르기", "예약 확인"],
    "pipeline": {"input": "회원 정보", "process": "예약 정리", "output": "예약 안내"},
    "feature_details": [{"name": "회원 등록·조회", "detail": "회원 정보를 입력하면 목록에 보여 준다"},
                        {"name": "수업 예약", "detail": "수업을 고르면 예약을 확인한다"}],
    "key_metrics": [], "solution_steps": ["회원 등록", "수업 예약", "예약 확인"],
}


def bv_reply(request: LLMRequest, html: str = HTML, content: dict | None = None,
             elements: list[str] | None = None) -> str:
    """목적에 맞는 가짜 응답 본문."""
    purpose = request.metadata["purpose"]
    user = request.messages[-1]["content"]
    if purpose == "T-B1 HTML 생성":
        return f"```html:index.html\n{html}\n```"
    if purpose == "T-B2 인포그래픽 정보 추출":
        return json.dumps(content or CONTENT, ensure_ascii=False)
    if purpose == "사업 분야 판정(색)":                      # T-B2 색 — 분야 낱말이 없을 때만 불린다
        return json.dumps({"domain": "outdoor"})
    if purpose.startswith("계획서 대조 요소: "):
        return json.dumps({"elements": elements or ELEMENTS}, ensure_ascii=False)
    if "[확인할 요소]" in user:
        count = len(user.split("[확인할 요소]\n", 1)[1].splitlines())
        return json.dumps({"checks": [{"element": "e", "reason": "있음", "present": True}] * count},
                          ensure_ascii=False)
    return json.dumps({"reason": "계획서와 같다", "verdict": "충족"}, ensure_ascii=False)


class BvProvider:
    """목적별로 답하는 가짜 호출처. scripts[목적] · scripts[(목적, 항목 키)] · prefix[목적 머리말]의 결과를 차례로 쓴다 —
    'timeout' · 'rate_limit'(429) · 'bad_request'(400) · 'quota'(429 + insufficient_quota — 결제 · 한도) ·
    'overloaded'(503 + 코드) · 'boom'(RuntimeError — 재시도 대상이 아닌 오류) · 그 밖의 글자는 응답.
    hold가 있으면 응답 전에 그만큼 기다린다(동시 수 재기). 받은 요청과 최대 동시 수를 모은다."""

    def __init__(self, html: str = HTML, content: dict | None = None, hold: float = 0.0) -> None:
        self.lock = threading.Lock()
        self.requests: list[LLMRequest] = []
        self.scripts: dict[Any, list[str]] = {}
        self.prefix: dict[str, list[str]] = {}
        self.html, self.content, self.hold = html, content, hold
        self.active = self.peak = 0
        self._wait = threading.Event()

    def _outcome(self, purpose: str, item: str | None) -> str | None:
        queue = self.scripts.get((purpose, item)) or self.scripts.get(purpose)
        if not queue:
            queue = next((q for p, q in self.prefix.items() if purpose.startswith(p) and q), None)
        return queue.pop(0) if queue else None

    def complete(self, request: LLMRequest) -> str:
        with self.lock:
            self.requests.append(request)
            outcome = self._outcome(request.metadata["purpose"], request.metadata.get("item_key"))
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.hold:
                self._wait.wait(self.hold)
            if outcome is not None:
                raise_fake_failure(outcome)   # timeout · rate_limit · bad_request · quota · overloaded 등
            if outcome == "boom":
                raise RuntimeError("호출처 버그")
            if outcome is not None:
                return outcome
            return bv_reply(request, self.html, self.content)
        finally:
            with self.lock:
                self.active -= 1

    def purposes(self) -> list[str]:
        return [r.metadata["purpose"] for r in self.requests]


class EchoImage:
    """가짜 이미지 호출처. outcomes를 차례로 쓰고 다 쓰면 default — echo · tiny · garbage · timeout · rate_limit · quota ·
    overloaded."""

    def __init__(self, default: str = "echo", outcomes: list[str] | None = None) -> None:
        self.default, self.outcomes = default, list(outcomes or [])
        self.requests: list = []
        self.lock = threading.Lock()

    def create(self, request) -> ImageResponse:
        with self.lock:
            self.requests.append(request)
            outcome = self.outcomes.pop(0) if self.outcomes else self.default
        raise_fake_failure(outcome)   # timeout · rate_limit · quota · overloaded 등
        if outcome == "tiny":
            return ImageResponse(FakeImage.PNG)
        if outcome == "garbage":
            return ImageResponse(b"not a png at all")
        return ImageResponse(request.image)   # 뼈대 그림 그대로 — 칸 수가 맞는다(타일은 비어 있음)


def bv_tools(provider: Any, task_id: str, *, image: Any = None, retry: int = 1,
             files: MemoryFileStore | None = None, run_id: str = "run-1") -> tuple[Tools, CallSink, MemoryFileStore]:
    """그 Task의 기본 설정(모델 · 이미지 설정)을 입힌 tools와 메모리 파일 저장소."""
    row = Settings().tasks[task_id]
    sink, store = CallSink(), files or MemoryFileStore()
    cfg = ToolsConfig(agent="시험", provider=row.provider, model=row.model, temperature=None, timeout_sec=10,
                      retry_count=retry, retry_interval_sec=0, image_provider=row.image_provider,
                      image_model=row.image_model, image_quality=row.image_quality, image_size=row.image_size,
                      purpose_models=dict(row.purpose_models))
    ctx = ToolsContext(run_id=run_id, execution_id=f"exec-{task_id}", task_id=task_id,
                       providers={"openai": provider}, sink=sink, now=utc_now, sleep=lambda s: None,
                       image_providers={"openai": image} if image is not None else {},
                       files=store, run_progress=lambda: "실행")
    return Tools(cfg, ctx), sink, store


def respond_bv(llm: Any, *, html: Callable[[LLMRequest], str] | str = HTML, content: dict | None = None) -> None:
    """FakeLLM에 세 Task의 목적별 응답을 단다. html은 글자 또는 요청 → 글자 함수(재수행마다 다른 HTML)."""
    def reply(request: LLMRequest) -> str:
        body = html(request) if callable(html) else html
        return bv_reply(request, body, content)
    for task_id in BV_TASKS:
        llm.respond(task_id, reply)
