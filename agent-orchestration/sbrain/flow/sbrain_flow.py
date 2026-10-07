"""S-Brain 워크플로 — 구간 · 대기 지점 · 재작성 경로 · 알림 (시트 2 · 5 · 7, 기획서 4-7).

구간(segment)
  PRE      R-8? → T-C1 → T-C2                         (실행 건 생성 전)
  MORE     T-C2 (offset=10)                           → 3 공고 선택 대기
           첫 조회와 겹친 후보는 빼고 첫 조회 카드를 새 내용으로 바꾼다 — 내용 바뀜 표시 · 막힌 공고 풀기 (after_step).
           어떤 오류든 · 수집 상태 비정상이면 조회 전 후보로 두고 기회를 돌려준다 (on_rescue · after_step, spec 4.2.3)
  GATE     G-01                                       → 5 작성 시작 대기 / 3 공고 선택 대기
           G-01이 어떤 오류로 끝나도 실행을 살리고 고르기 전 대기 지점(3 또는 5)으로 돌아간다 (on_rescue)
  WRITE    T-C3 → T-S1 → T-S2 → T-W1 → T-W2 → T-W3 → M-1 → T-V1 → G-02a   → 6 문서 평가 대기
  PROTO    T-B1* → T-B2 → M-2** → G-04 → M-3 → T-V2 → G-02b              → 8 산출물 확인 대기
           G-04 자체 검사가 끝내 불통과면 관리자 기록 후 계속, T-V2 대조 보류 · 진단은 관리자 기록 (after_step)
  REVIEW   G-03 → T-P1 → T-P2 → M-4 → T-C4                               → 11 완료
  REWORK6 · REWORK8 · REWORK9  재작성 사이클 (rework_queue 참고) — 묶음 요청을 모으는 시간 동안 모아 한 번에 연다
                               (service.request_rework_for_project, 지시는 bundle_orders)
  * 원페이지면 생략  ** 원페이지만
G-02b는 T-V2 직후 계산하고(시트 2 "T-V2 종료 직후"), 화면 8을 거쳐 화면 9에서 보여준다.

재작성 · 재수행 지시문 (T-C3 spec 5): 대상 Task의 지시문 입력을 build_instruction이 만든다.
  첫 실행은 taskPlan의 지시문 그대로다. 검사 불통과 재수행 · 사용자 재작성의 대상 · 재작성 중 재수행이면 조율 다시 쓰기
  함수(rewriter, 조립이 끼운다)가 안내 부분만 다시 쓰고, 문제 내용 원문을 덧붙여 <taskId>.instruction으로 저장한다
  (같은 입력으로 재개하면 다시 쓰지 않고 저장한 것을 쓴다). 반영 실행(T-B1)과 다시 쓰기 함수가 없는 조립(스텁)은
  덧붙이기만 한다. 재작성 중 재수행이면 어느 경로든 그 사이클의 재작성 지시도 함께 남긴다(5.4).

산출물층 검증 반영: 재실행 때 T-B1에 이전 원문(previous_source_text)을 준다 — 재작성 대상(initial_redo_state)과 검사
  불통과 재수행(redo_rework_input)만. 반영 실행 · 다른 Task는 채우지 않는다. T-B2 실행 기록에 최종 실패인 이미지 호출이
  있으면 '이미지대체' 사건을 그 실행 기록과 같은 묶음에 남긴다(after_execution — 사용자 화면에는 알리지 않는다).

T-P2 시도 기록: 문장마다 T-P2 함수가 결과를 돌려준 호출 하나가 시도다(호출 실패는 시도가 아니다). 시도는 문장 결과
(sentenceResults)의 attempts에 쌓고, 보호 토큰 검사를 통과하지 못한 시도(반려)는 같은 저장에서 웹 proofread_logs
후보(RejectedAttempt)로 넘긴다 — 학습 동의 확인과 쓰기는 저장소가 한다. 재개해도 이번에 새로 만든 시도만 넘긴다.
"""
from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Callable, Protocol

from ..contracts import tasks as c
from ..models import (
    AnnouncementCard, CompanyInfo, Notice, Notification, RejectedAttempt, ReworkInput, ReworkOrder, Run,
    TaskInstruction, Token, TokenCheckResult,
)
from ..models.clock import kst_today, utc_clock, utc_now
from ..models.run import RedoState, make_state
from ..orchestrator.context import RunContext
from ..orchestrator.engine import Engine, Outcome, StepFailure, ToolsFactory
from ..orchestrator.errors import EMBED_DEADLINE_SUFFIX, ContractError, ToolCallExhausted, message
from ..orchestrator.registry import TaskRegistry, TaskSpec
from ..orchestrator.settings import REWRITE_SETTING_KEY
from ..orchestrator.tools import CallSink, Tools
from ..orchestrator.trace import IMAGE_CALL, CallLog, ExecutionRecord, FeedbackLink
from .catalog import FIRST_CANDIDATES, FORM_SPEC, INSTRUCTION_SUFFIX, MORE_CANDIDATES, RUBRIC
from .instruction import append_problems, extract_frame, replace_guidance
from .rework_map import ARTIFACT_BUNDLES, BUNDLE_LAYER, BUNDLE_TASK, DOCUMENT_TASKS, alt_text_source_missing

WRITE = ["T-C3", "T-S1", "T-S2", "T-W1", "T-W2", "T-W3", "M-1", "T-V1", "G-02a"]
REVIEW = ["G-03", "T-P1", "T-P2", "M-4", "T-C4"]
CYCLE_END = "CYCLE-END"
SCREEN_STEP = {6: "문서평가", 8: "산출물확인", 9: "종합평가"}
STEP_SCREEN = {step: screen for screen, step in SCREEN_STEP.items()}
STEP_LABEL = {CYCLE_END: "재작성 전후 비교"}
# 판정 지시가 없는 묶음의 재작성 지시 문구 (잠정)
REWORK_DEFAULT_REASON = "사용자가 이 묶음의 재작성을 요청했습니다."
# 관리자 사건 종류 · 문구 (잠정 — orchestrator/settings.py PROVISIONAL event.*). 내용 · 지시문은 싣지 않는다
EVENT_MATCH_WITHHELD = "대조보류"
EVENT_V2_DIAGNOSTIC = "검증2진단"
EVENT_README_CHECK_FAILED = "안내문서자체검사실패"
EVENT_IMAGE_FALLBACK = "이미지대체"
EVENT_ALT_SOURCE_MISSING = "대체텍스트출처누락"
ALT_SOURCE_MISSING_DETAIL = "HTML 2번 미충족인데 defect_sources가 비어 있음 — T-B2로 보냄"
IMAGE_FALLBACK_DETAIL = "T-B2 이미지 호출 실패 — 기본 아이콘으로 계속"
# 이전 원문(previous_source_text)을 채우는 Task와 그 원문이 든 산출물 (spec 4.3 — T-B1만)
SOURCE_TEXT_TASK, SOURCE_TEXT_KEY = "T-B1", "prototype"
# 공고를 고를 수 있는 대기 지점 — 공고 선택 명령이 decision의 beforeStep에 남기고, G-01이 실패하면 그리로 돌아간다 (4.3.4)
SELECTION_STEPS = ("공고선택", "계획서작성")


def block_announcement(run: Run, announcement_id: str) -> None:
    """막힌 공고 목록에 넣는다 (자격 불통과, spec 4.3.6). 이미 있으면 그대로 둔다. G-01 결과 저장과 같은 저장에서 부른다."""
    if announcement_id not in run.blocked_announcement_ids:
        run.blocked_announcement_ids.append(announcement_id)


def unblock_announcement(run: Run, announcement_id: str) -> None:
    """막힌 공고 목록에서 뺀다 (추가 조회에서 내용이 바뀜, spec 4.2.2 · 4.3.6). 추가 조회 결과 저장과 같은 저장에서 부른다."""
    if announcement_id in run.blocked_announcement_ids:
        run.blocked_announcement_ids.remove(announcement_id)


# ── 공고 후보 · 추가 조회 (spec 4.2) ──────────────────────
CANDIDATE_LIMIT = 20   # 공고 후보 합계 상한 — 첫 조회 + 추가 조회 (추가 조회는 1회)
# 내용 바뀜을 가르는 공고 정보 필드 (spec 4.2.2 ①) — 적합도 · 추천 이유 · 가산점 · 출처 고지는 보지 않는다
CARD_INFO_FIELDS = ("title", "agency", "apply_end", "apply_period_type", "support_amount_max", "original_url")
# 첫 조회 카드를 추가 조회 카드 내용으로 바꿀 때 그대로 두는 필드 (spec 4.2.2)
CARD_KEPT_FIELDS = ("rank", "display_type")
# 추가 조회 명령(decision)이 남기는 조회 전 T-C2 출력 포인터 — 실패하면 이 버전으로 돌린다 (spec 4.2.3)
MORE_BEFORE_POINTERS = "beforePointers"


def candidate_lists(ctx: RunContext) -> tuple[list[AnnouncementCard], list[AnnouncementCard]]:
    """공고 후보 (첫 조회, 추가 조회) — 화면 3 · outputs · 20건 한도 · 공고 선택 후보 확인이 모두 이것만 쓴다.

    유효한(성공한) 추가 조회가 있으면 그것이 남긴 두 목록(첫 조회 갱신본 firstCandidates · 겹침을 뺀 moreCandidates),
    없으면 첫 조회(candidates@1)와 빈 목록이다. candidates 버전 범위는 읽지 않는다 — 실패한 추가 조회가 남긴 버전은
    없던 것으로 본다 (spec 4.2.3).
    """
    if ctx.has(MORE_CANDIDATES):
        return ctx.get(FIRST_CANDIDATES), ctx.get(MORE_CANDIDATES)
    return (ctx.get("candidates", 1) if ctx.latest.get("candidates") else []), []


def card_content_changed(before: AnnouncementCard, after: AnnouncementCard) -> bool:
    """공고 내용이 바뀌었는지 (spec 4.2.2) — 공고 정보 필드가 다르거나, 두 카드 모두 내용 버전이 있고 서로 다르다.

    한쪽이라도 내용 버전이 없으면 공고 정보만 본다. 적합도 · 추천 이유 · 가산점만 달라졌으면 거짓이다. 이전 자격 결과
    (공고 없음 · 불통과 · 통과)는 보지 않는다.
    """
    if any(getattr(before, f) != getattr(after, f) for f in CARD_INFO_FIELDS):
        return True
    return (before.content_version is not None and after.content_version is not None
            and before.content_version != after.content_version)


def merge_more_candidates(first: list[AnnouncementCard], received: list[AnnouncementCard],
                          ) -> tuple[list[AnnouncementCard], list[AnnouncementCard]]:
    """추가 조회 결과를 첫 조회에 맞춘다 (spec 4.2.2, Orchestrator 규칙 — T-C2 함수는 첫 조회를 모른다).

    - 첫 조회와 공고 ID가 같은 카드는 추가 후보에서 뺀다. 첫 조회의 그 카드는 받은 카드 내용(가산점 · 내용 버전 포함)으로
      바꾸고 자리 · 순위 · 표시 방식은 그대로 두며, contentChanged는 card_content_changed로 정한다.
    - 다시 나오지 않은 첫 조회 카드는 그대로, 추가 후보는 받은 순서 그대로다.
    돌려주는 것: (첫 조회 갱신본, 추가 후보)
    """
    first_ids = {card.announcement_id for card in first}
    again: dict[str, AnnouncementCard] = {}
    for card in received:
        if card.announcement_id in first_ids:
            again.setdefault(card.announcement_id, card)
    refreshed = []
    for card in first:
        new = again.get(card.announcement_id)
        refreshed.append(card if new is None else new.model_copy(update={
            **{f: getattr(card, f) for f in CARD_KEPT_FIELDS}, "content_changed": card_content_changed(card, new)}))
    return refreshed, [card for card in received if card.announcement_id not in first_ids]


# 보호 토큰 종류(시트 4 TokenType) → 웹 proofread_logs.violation_type 표기
VIOLATION_LABEL = {"날짜": "날짜", "수치금액": "수치·금액", "고유명사": "고유명사", "기능명": "기능명"}
# 위반 내용 — 종류를 정하는 순서이기도 하다 (빠진 → 바뀐 → 섞인)
VIOLATION_PARTS = (("빠짐", "missing_tokens"), ("바뀜", "altered_tokens"), ("섞임", "contaminated_tokens"))


def violation_type(check: TokenCheckResult, tokens: list[Token]) -> str | None:
    """위반 토큰을 보호 토큰 목록(G-03)과 값으로 맞춰 처음 맞는 토큰의 종류 (빠진 → 바뀐 → 섞인). 못 맞추면 None."""
    kind: dict[str, str] = {}
    for t in tokens:
        kind.setdefault(t.value, t.type)
    for _, part in VIOLATION_PARTS:
        for value in getattr(check, part):
            if value in kind:
                return VIOLATION_LABEL[kind[value]]
    return None


def violation_note(check: TokenCheckResult) -> str:
    """위반 토큰 목록 전체 — '빠짐: 1억원 / 섞임: A, B' (표기 잠정)."""
    return " / ".join(f"{label}: {', '.join(values)}" for label, part in VIOLATION_PARTS
                      if (values := getattr(check, part)))


def violation_reason(check: TokenCheckResult) -> str:
    """위반 요약 — '보호 토큰 검사 불통과 (빠짐 1건 · 섞임 2건)' (표기 잠정)."""
    counts = [f"{label} {len(values)}건" for label, part in VIOLATION_PARTS if (values := getattr(check, part))]
    return "보호 토큰 검사 불통과" + (f" ({' · '.join(counts)})" if counts else "")


def proto_queue(category: str) -> list[str]:
    onepage = category == "원페이지"
    return ([] if onepage else ["T-B1"]) + ["T-B2"] + (["M-2"] if onepage else []) + ["G-04", "M-3", "T-V2", "G-02b"]


def rework_queue(screen: int, orders: list[ReworkOrder], category: str) -> list[str]:
    """고른 묶음에 따라 다시 돌릴 단계 (실행 순서대로). 합치기는 모든 경로에 들어간다."""
    tasks = {o.task_id for o in orders}
    onepage = category == "원페이지"
    doc = any(o.layer == "document" for o in orders)
    if screen == 6:
        return [t for t in DOCUMENT_TASKS if t in tasks] + ["M-1", "T-V1", CYCLE_END, "G-02a"]
    q: list[str] = []
    if doc:
        q += [t for t in DOCUMENT_TASKS if t in tasks] + ["M-1", "T-V1"]
    if not onepage and (doc or "T-B1" in tasks):
        q.append("T-B1")  # 화면 9 계획서 재작성은 HTML에도 반영 (재작성 횟수 안 씀)
    if "T-B2" in tasks or (onepage and doc):
        q.append("T-B2")  # 원페이지 화면 9 계획서 재작성은 인포그래픽에 반영 (재작성 횟수 안 씀, 2026-09-29 결정 7)
        if onepage:
            q.append("M-2")
    q += ["G-04", "M-3", "T-V2", CYCLE_END, "G-02b"]
    return q


def bundle_orders(bundles: list[str], offered: list[ReworkOrder]) -> dict[str, ReworkOrder]:
    """모은 묶음 → Task별 재작성 지시 (기준 문서 순서: T-W1 · T-W2 · T-W3 · T-B1 · T-B2).

    - 대상(targets)은 그 층에서 모은 묶음 이름이다(기회를 세는 이름과 같다).
    - 산출물층: 그 Task에 대한 판정 지시(사유 · 보완 지시)를 쓴다. 같은 Task 지시가 여럿이면 합친다.
    - 문서층 (임시 처리, 잠정): 어느 묶음이든 계획서 전체(T-W1 · T-W2 · T-W3)를 다시 만든다. 판정이 낸 문서층 지시를
      모두 합쳐 세 Task에 같은 지시로 준다.
    - 해당 판정 지시가 없으면(미달이 아닌 묶음, 확장) 사유 · 보완 지시 모두 고정 문구 REWORK_DEFAULT_REASON을 쓴다.
      판정 지시의 보완 지시가 비어 있어도 같다(시트 4 ReworkOrder.instructionDelta는 비워 둘 수 없다).
    """
    out: dict[str, ReworkOrder] = {}
    docs = [b for b in bundles if BUNDLE_LAYER.get(b) == "document"]
    if docs:
        doc_orders = [o for o in offered if o.layer == "document"]
        for task_id in DOCUMENT_TASKS:
            out[task_id] = _merge_orders(task_id, "document", docs, doc_orders)
    for b in ARTIFACT_BUNDLES:
        if b in bundles:
            task_id = BUNDLE_TASK[b]
            out[task_id] = _merge_orders(task_id, "artifact", [b],
                                         [o for o in offered if o.layer == "artifact" and o.task_id == task_id])
    return out


def _merge_orders(task_id: str, layer: str, targets: list[str], orders: list[ReworkOrder]) -> ReworkOrder:
    reasons = list(dict.fromkeys(o.reason for o in orders if o.reason))
    deltas = list(dict.fromkeys(o.instruction_delta for o in orders if o.instruction_delta))
    return ReworkOrder(task_id=task_id, unit="묶음", targets=list(targets),
                       reason="; ".join(reasons) or REWORK_DEFAULT_REASON,
                       instruction_delta="\n".join(deltas) or REWORK_DEFAULT_REASON, layer=layer)


# ── 재작성 · 재수행 지시문 (T-C3 spec 5) ──────────────────────
REWRITE_AGENT = "조율"           # 다시 쓰기 호출 기록의 Agent 이름 — 옛 설정 사본이면 이 Agent 설정으로 부른다
# 다시 쓰기 호출의 설정 키 — Task별 설정(Settings.tasks)의 '지시문 다시 쓰기' 항목(호출처 · 모델 · 추론 강도)과
# 같은 키의 제한 시간(잠정 120초)을 쓴다. T-C3 설정과 따로 둔다 (orchestrator/settings.py REWRITE_SETTING_KEY)
REWRITE_KEY = REWRITE_SETTING_KEY
MASK_MIN_CHARS = 2               # 이보다 짧은 회사 정보 값은 가리지 않는다 (잠정)
REFLECT_ROLE = "반영"            # 화면 9 계획서 재작성의 T-B1 반영 실행 — 다시 쓰지 않는다 (T-C3 spec 5.1)


class GuidanceRewriter(Protocol):
    """조율의 안내 다시 쓰기 함수 (agents/supervisor/rewrite.py — 조립이 끼운다. 흐름은 agents/를 import하지 않는다).

    문제 내용: 재작성이면 order(묶음 이름 · 사유 · 보완 지시), 재수행이면 issues, 재작성 중 재수행이면 둘 다.
    mask_values는 문제 내용에서 가릴 회사 정보 값이다. 새 안내(정리한 것)를 돌려준다. ToolCallExhausted는 받지 않는다."""

    def __call__(self, *, task_id: str, name: str, frame: str, guidance: str, order: ReworkOrder | None,
                 issues: list[str], mask_values: list[str], tools: Tools) -> str: ...


def rewrite_mask_values(info: CompanyInfo) -> list[str]:
    """다시 쓰기 요청의 문제 내용에서 가릴 회사 정보 값 (T-C3 spec 5.2) — 대표자 이름 · 기업명 · 사업자등록번호, 생년월일(ISO),
    수익모델 단가(revenueUnitPrice · revenueItems[].unitPrice — 숫자만 · 천 단위 쉼표 표기), 대표자 이력 · 팀 구성원의 각 항목.
    MASK_MIN_CHARS보다 짧은 값은 뺀다 (잠정). 같은 값은 한 번만."""
    prices = [info.revenue_unit_price, *(item.unit_price for item in info.revenue_items)]
    values = [info.representative_name, info.company_name, info.business_reg_no, info.birth_date.isoformat(),
              *(form for price in prices for form in (str(price), f"{price:,}")),
              *info.representative_career, *info.team_careers]
    return list(dict.fromkeys(v for v in values if v is not None and len(v.strip()) >= MASK_MIN_CHARS))


def reflect_issues(ctx: RunContext) -> list[str]:
    """화면 9 계획서 재작성 반영 실행(T-B1)의 문제 내용 — 반영 입력을 만들 때와 반영 실행 중 재수행 지시문이 같이 쓴다."""
    return [f"계획서 재작성 반영 ({ctx.ref('planDoc')})"]


def default_instruction_builder(base: str, rework_input: ReworkInput | None) -> str:
    """기존 지시문에 문제가 된 내용을 덧붙인다 — 재작성 · 재수행 입력 하나만 보는 덧붙이기(append_problems와 같은 글자).
    재작성 중 재수행 · 반영 실행 중 재수행은 SBrainFlow.build_instruction이 정한다."""
    return append_problems(base, rework_input)


class SBrainFlow:
    def __init__(
        self,
        registry: TaskRegistry,
        *,
        constants: Callable[[RunContext, str], Any],
        now: Callable[[], datetime] = utc_now,
        rewriter: GuidanceRewriter | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self.registry = registry
        self.constants = constants
        self.now = utc_clock(now)
        # 재작성 · 재수행 때 안내를 다시 쓰는 조율 함수 — 없으면(스텁 조립) 덧붙이기만 한다. 조립이 끼운다
        self.rewriter: GuidanceRewriter | None = rewriter
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:12])
        self.engine: Engine | None = None

    # ── 엔진이 부르는 것 ───────────────────────────────
    def custom_step(self, step_id: str):
        if step_id == CYCLE_END:
            return self._cycle_end
        if step_id == "T-P2":
            return self._run_tp2
        return None

    def build_instruction(self, ctx: RunContext, spec: TaskSpec, task: TaskInstruction,
                          rework_input: ReworkInput | None, rs: RedoState,
                          tools_for: ToolsFactory) -> tuple[str, list[str]]:
        """대상 Task의 지시문 입력 (T-C3 spec 5.1 · 5.3 · 5.4 · 5.5). (지시문, 실행 기록 입력 참조에 더할 산출물 참조)를 돌려준다.

        - 첫 실행(입력 없음): taskPlan의 지시문 그대로.
        - 반영 실행(T-B1, 역할 '반영'): 다시 쓰지 않는다. 반영 블록, 반영 실행 중 재수행이면 반영 블록 → 재수행 블록.
        - 재작성 중 재수행(사이클 · 역할 '대상' · 입력 '재수행'): 그 사이클의 그 Task 재작성 지시도 함께 쓴다(5.4). Task가
          받는 rework_input은 바꾸지 않는다.
        - 다시 쓰기 함수가 없으면 덧붙이기만 한다. 있으면 안내 부분만 다시 쓰고(원래 안내는 늘 taskPlan의 guidance) 문제
          내용 원문을 덧붙여 <taskId>.instruction으로 저장한다. 같은 입력으로 재개하면 저장한 지시문을 쓴다.
        다시 쓰기의 재시도 소진(ToolCallExhausted)은 받지 않는다 — 엔진이 대상 Task를 재개한다(5.7).
        """
        base = task.instruction
        if rework_input is None:
            return base, []
        reflecting = rs.rework_role == REFLECT_ROLE and spec.task_id == "T-B1"   # 반영 실행은 T-B1뿐 (_role)
        cycle_order = self._cycle_order(ctx, spec.task_id, rework_input, rs)
        carried = reflect_issues(ctx) if reflecting and rework_input.mode == "재수행" else None
        if self.rewriter is None or reflecting:
            return append_problems(base, rework_input, cycle_order=cycle_order, reflect_issues=carried), []
        producer = f"orchestrator:{rs.rework_input_ref}"   # 이 지시문을 만든 재작성 · 재수행 입력
        if rs.instruction_ref is not None and ctx.producer_of(rs.instruction_ref) == producer:
            return ctx.get_ref(rs.instruction_ref), [rs.instruction_ref]   # 재개 — 다시 쓰지 않는다 (5.5)
        try:
            frame = extract_frame(base)
        except ValueError:
            raise ContractError(f"{spec.task_id} 지시문에 안내 부분이 없어 다시 쓸 수 없음") from None
        order = rework_input.order or cycle_order
        guidance = self.rewriter(
            task_id=spec.task_id, name=spec.name, frame=frame, guidance=task.guidance, order=order,
            issues=list(rework_input.issues) if rework_input.order is None else [],
            mask_values=rewrite_mask_values(ctx.get("companyInfo")),
            tools=tools_for(REWRITE_AGENT, REWRITE_KEY))
        text = append_problems(replace_guidance(base, guidance), rework_input, cycle_order=cycle_order)
        ref = ctx.put(f"{spec.task_id}{INSTRUCTION_SUFFIX}", text, producer=producer)
        rs.instruction_ref = ref   # 대상 Task가 재시도를 다 쓰면 재개 위치와 같은 저장에 남는다
        return text, [ref]

    @staticmethod
    def _cycle_order(ctx: RunContext, task_id: str, rework_input: ReworkInput, rs: RedoState) -> ReworkOrder | None:
        """재작성 사이클 안에서 대상 Task가 재수행할 때 그 사이클의 그 Task 재작성 지시 (T-C3 spec 5.4). 아니면 None."""
        cyc = ctx.run.cycle
        if (cyc is None or rs.rework_role != "대상" or rework_input.mode != "재수행" or rework_input.order is not None
                or task_id not in cyc.orders_by_task):
            return None
        return ReworkOrder.model_validate(cyc.orders_by_task[task_id])

    def today(self, ctx: RunContext) -> date:
        """G-01 · T-C2 기준일(TODAY) — 한국 날짜 (UTC 15:00 이후는 다음 날)."""
        return kst_today(self.now())

    def constant(self, ctx: RunContext, name: str) -> Any:
        if name == "topK":
            return 10
        return self.constants(ctx, name)

    def setting_value(self, ctx: RunContext, path: str) -> Any:
        """설정값 연결(setting)의 값. 옛 설정 사본(tasks 없이 agents만)에서 'tasks.<키>.<필드>'는 그 키의 Agent별 설정에서
        찾는다 — Task면 담당 Agent, 지시문 다시 쓰기면 조율 (예: M-4 model_version 'tasks.T-P2.model' → 'agents.검수.model')."""
        s = ctx.settings
        parts = path.split(".")
        if s.tasks is None and parts[0] == "tasks" and len(parts) >= 2:
            key = parts[1]
            agent = REWRITE_AGENT if key == REWRITE_KEY else self.registry.get(key).agent
            parts = ["agents", agent, *parts[2:]]
        obj: Any = s
        for part in parts:
            obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
        return obj

    def value(self, ctx: RunContext, name: str, spec: TaskSpec) -> Any:
        if name == "rubricVersion":   # 채점에 쓴 채점 기준표 — T-C3가 고른 것 (T-C3 spec 4)
            return ctx.get(RUBRIC).version
        if name == "cycleInfo":
            cyc = ctx.run.cycle
            if cyc is None:
                return None
            snap = cyc.snapshot
            prev_doc =ctx.get("docScore", snap["docScore"]) if "document" in cyc.rescored_layers and "docScore" in snap else None
            prev_art = ctx.get("artifactScore", snap["artifactScore"]) if "artifact" in cyc.rescored_layers and "artifactScore" in snap else None
            carried = "document" if cyc.screen in (8, 9) and cyc.rescored_layers == ["artifact"] else None
            return c.ReworkCycleInfo(
                cycle_id=cyc.cycle_id, screen=cyc.screen, comparisons=list(cyc.comparisons),
                rescored_layers=list(cyc.rescored_layers), carried_over_layer=carried,
                reworked_task_ids=list(cyc.orders_by_task), previous_doc_score=prev_doc,
                previous_artifact_score=prev_art)
        raise KeyError(name)

    def initial_redo_state(self, ctx: RunContext, spec: TaskSpec) -> RedoState:
        cyc = ctx.run.cycle
        if cyc is None:
            return RedoState(task_id=spec.task_id, trigger="첫실행")
        tid = spec.task_id
        role = self._role(tid, cyc)
        rs = RedoState(task_id=tid, trigger="재작성", rework_role=role)
        if role == "대상":
            order = ReworkOrder.model_validate(cyc.orders_by_task[tid])
            decision = ctx.get_ref(cyc.selected_orders_ref)
            source_refs = list(decision.get("sourceRefs", [])) + [cyc.selected_orders_ref]
            prev = ctx.ref(spec.outputs[spec.primary_output]) if ctx.has(spec.outputs[spec.primary_output]) else ""
            issues = [order.reason] + ([order.instruction_delta] if order.instruction_delta else [])
            # T-B1이면 재작성 직전 prototype 포인터의 원문을 함께 준다 (spec 4.3 — 고쳐 달라는 경우만)
            source = (ctx.get(SOURCE_TEXT_KEY).source_text
                      if tid == SOURCE_TEXT_TASK and ctx.has(SOURCE_TEXT_KEY) else None)
            self._attach_rework(ctx, rs, spec, kind="재작성", source_refs=source_refs,
                                ri=dict(mode="재작성", previous_result_ref=prev, issues=issues, order=order,
                                        previous_source_text=source),
                                bundle_id=",".join(order.targets))
        elif role == REFLECT_ROLE and tid == "T-B1":
            # 계획서 반영 실행 — T-B1 입력에 계획서(plan_doc, 확장)가 있지만, 추적 기록(FeedbackLink)을 위해 계획서 버전을
            # 알리는 재작성 입력(issues)을 그대로 붙인다. 이전 원문은 채우지 않는다(새 계획서로 새로 만든다, spec 4.3).
            # 원페이지 T-B2 반영에는 아무것도 붙이지 않는다 — T-B2는 planDoc을 직접 받아 첫 제작과 같은 경로다(결정 7)
            plan_ref = ctx.ref("planDoc")
            prev = ctx.ref("prototype") if ctx.has("prototype") else ""
            self._attach_rework(ctx, rs, spec, kind="재작성반영", source_refs=[plan_ref],
                                ri=dict(mode="재작성", previous_result_ref=prev, issues=reflect_issues(ctx), order=None),
                                bundle_id=None)
        return rs

    def _attach_rework(self, ctx: RunContext, rs: RedoState, spec: TaskSpec, *, kind: str,
                       source_refs: list[str], ri: dict, bundle_id: str | None) -> None:
        fid, next_id = self.new_id(), self.new_id()
        rework_input = ReworkInput(is_final_attempt=False, source_refs=source_refs, feedback_id=fid, **ri)
        ri_ref = ctx.put(f"{spec.task_id}.reworkInput", rework_input, producer=f"orchestrator:{kind}")
        source_exec = self._producer_execution(ctx, source_refs[0]) if source_refs else None
        ctx.add_feedback(FeedbackLink(
            feedback_id=fid, run_id=ctx.run.run_id, kind=kind, source_execution_id=source_exec,
            source_refs=source_refs, target_task_id=spec.task_id, target_execution_id=next_id,
            via_ref=ri_ref, cycle_id=ctx.run.cycle.cycle_id if ctx.run.cycle else None,
            created_at=self.now()))
        rs.rework_input_ref = ri_ref
        rs.pending_execution_id = next_id
        rs.bundle_id = bundle_id

    @staticmethod
    def _producer_execution(ctx: RunContext, ref: str) -> str | None:
        producer = ctx.producer_of(ref)
        return None if ":" in producer else producer

    @staticmethod
    def _role(task_id: str, cyc) -> str:
        if task_id in cyc.orders_by_task:
            return "대상"
        if task_id.startswith("M-"):
            return "합치기"
        if task_id in ("T-V1", "T-V2"):
            return "재채점"
        if task_id in ("G-02a", "G-02b"):
            return "판정"
        return REFLECT_ROLE  # T-B1(계획서 반영) · T-B2(원페이지 계획서 반영) · G-04

    def after_step(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None:
        out = outcome.outputs
        if step_id == "R-8":
            for doc in out.get("reference_docs", []):
                if doc.extract_status == "실패":
                    self._notice(ctx, "E-C1-DOC", 파일명=doc.file_name)
        elif step_id == "T-C1":
            # category 산출물을 저장하는 같은 저장에서 실행 건에도 적는다(사전 단계면 실행 건 생성 저장) — 기록 통계 줄의
            # 카테고리. 완전 삭제 · 12개월 처리가 지우지 않는다
            ctx.run.category = out["category"]
            if out.get("category_defaulted"):
                # 카테고리 판정 실패 → 웹개발 기본 처리, 로그에 기록 (시트 2 T-C1 ③)
                ctx.add_event("카테고리기본값", f"T-C1 카테고리 판정 실패 — {out['category']}로 기본 처리",
                              refs=[ctx.ref("category")],
                              execution_id=outcome.record.execution_id if outcome.record else None)
        elif step_id == "T-P1":
            # 화면 10의 검수 전 문장 = T-P1이 읽은 계획서 버전(M-4가 새 버전을 만들기 전). 실행 기록이 지워져도 찾을 수
            # 있게 T-P1 성공 저장에서 실행 건에 적는다 (reads._sentence_changes)
            rec = outcome.record
            base = next((i for i in rec.inputs if i.startswith("planDoc@")), None) if rec else None
            if base is not None:
                ctx.run.proofread_base_ref = base
        elif step_id == "T-C2":
            more = ctx.run.segment == "MORE"
            if more and out["collection_status"] != "정상":
                # 수집 상태가 정상이 아니라 매칭하지 않은 추가 조회 — 실패로 본다 (spec 4.2.3). 첫 조회(PRE)는 시작 요청이
                # E-C2-STALE로 끝난다(service.run_start_request)
                self._more_failed(ctx, "E-C2-STALE")
                return
            if out.get("fallback_used"):
                # 대체 경로 안내. 마감 임박순이면 문구 끝에 덧붙인다 (spec 4.1.3) — 첫 조회 · 추가 조회 모두
                suffix = EMBED_DEADLINE_SUFFIX if out.get("fallback_mode") == "마감임박순" else ""
                self._notice(ctx, "E-C2-EMBED", suffix=suffix)
            if more:
                self._keep_more(ctx, out["candidates"], outcome)
        elif step_id == "T-V2":
            self._after_tv2(ctx, out, outcome)
        elif step_id == "G-04":
            # 자체 검사가 재수행 횟수를 다 쓰고도 불통과 — 관리자 기록만 하고 계속한다 (점수 밖, 결정 6). 오류로 건너뛴
            # 경우(단계오류계속)는 출력이 없다
            check = out.get("check")
            if check is not None and not check.passed:
                ctx.add_event(EVENT_README_CHECK_FAILED,
                              f"G-04 자체 검사 불통과 {len(check.failures)}건 — 재수행 횟수를 다 써 그대로 계속",
                              refs=[ctx.ref("G-04.check")],
                              execution_id=outcome.record.execution_id if outcome.record else None)
        elif step_id == "G-01":
            # 선택 공고 · 자격 결과 · 업력을 저장하는 같은 저장에서 공고 포인터를 바꾸고, 불통과면 막는다 (4.3.2 · 4.3.6).
            # 설립일 없음(missingInputs)은 불통과가 아니라 막지 않는다
            aid = out["selected_announcement"].announcement_id
            ctx.run.announcement_id = aid
            gate = out["gate_result"]
            if not gate.passed and not gate.missing_inputs:
                block_announcement(ctx.run, aid)

    @staticmethod
    def _after_tv2(ctx: RunContext, out: dict[str, Any], outcome: Outcome) -> None:
        """T-V2 결과의 관리자 기록 (C3). 흐름은 필드로만 가른다 — findings · diagnostics 문구로 가르지 않는다.

        - 대조 판정 보류(withheld): '대조보류' 사건 (결정 8 — 0점 합산은 T-V2 · 판정이 이미 했다, 화면 '대조 불가'는 웹)
        - 진단(diagnostics): 줄마다 '검증2진단' 사건 (관리자 진단 전용)
        - HTML 2번 미충족인데 결함 출처가 빔(담당자 쪽 누락): '대체텍스트출처누락' 사건 — 재작성 사유는 T-B2로 간다 (C4 규칙 2)
        """
        exec_id = outcome.record.execution_id if outcome.record else None
        fm = out.get("feature_match")
        if fm is not None and fm.withheld:
            ctx.add_event(EVENT_MATCH_WITHHELD, f"T-V2 대조 판정 보류 ({fm.withheld_reason}) — 0점 합산",
                          refs=[ctx.ref("featureMatch")], execution_id=exec_id)
        for line in out.get("diagnostics") or []:
            ctx.add_event(EVENT_V2_DIAGNOSTIC, line, execution_id=exec_id)
        score = out.get("artifact_score")
        if score is not None and alt_text_source_missing(score, ctx.get("prototype").kind):
            ctx.add_event(EVENT_ALT_SOURCE_MISSING, ALT_SOURCE_MISSING_DETAIL,
                          refs=[ctx.ref("codeCheck")], execution_id=exec_id)

    def redo_rework_input(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord,
                          rework_input: ReworkInput) -> ReworkInput:
        """검사 불통과 재수행의 재작성 입력 (엔진 선택 확장 지점). T-B1이면 방금 실행이 만든 prototype의 원문을 채운다 —
        그 실행이 대상 · 반영 · 첫 실행 중 무엇이었든 (spec 4.3). 다른 Task는 그대로다."""
        if spec.task_id != SOURCE_TEXT_TASK or not rec.result_ref.startswith(f"{SOURCE_TEXT_KEY}@"):
            return rework_input
        source = ctx.get_ref(rec.result_ref).source_text
        return rework_input.model_copy(update={"previous_source_text": source})

    def after_execution(self, ctx: RunContext, spec: TaskSpec, rec: ExecutionRecord, calls: list[CallLog]) -> None:
        """실행 기록 하나가 성공으로 저장되는 같은 묶음 (엔진 선택 확장 지점). T-B2 실행에 최종 실패인 이미지 호출이 하나라도
        있으면 '이미지대체' 사건을 남긴다 — 실행 기록마다(재수행으로 다시 돈 앞선 실행 포함, spec 3.3). 내용 · 지시문은 없다."""
        if spec.task_id != "T-B2":
            return
        if any(log.call_type == IMAGE_CALL and log.final_outcome != "성공" for log in calls):
            ctx.add_event(EVENT_IMAGE_FALLBACK, IMAGE_FALLBACK_DETAIL, execution_id=rec.execution_id)

    def on_queue_empty(self, ctx: RunContext) -> None:
        run, seg = ctx.run, ctx.run.segment
        if seg in ("PRE", "MORE"):
            self._wait(ctx, "공고선택", "setup")
        elif seg == "GATE":
            # 판정 결과에 따른 다음 상태 (spec 4.3.2). 확인 필요(unknownConditions)는 막지 않는다 — 화면 4에만 안내.
            # undecidable은 쓰지 않는다(늘 거짓)
            gate = ctx.get("gateResult")
            if gate.passed and not gate.missing_inputs:
                self._wait(ctx, "계획서작성", "setup")
            else:
                if gate.missing_inputs:
                    self._notice(ctx, "E-G1-MISSING")
                else:
                    self._notice(ctx, "E-G1-REJECT", 사유=", ".join(gate.failed_conditions))
                self._wait(ctx, "공고선택", "setup")
        elif seg == "WRITE":
            self._wait(ctx, "문서평가", "document")
            self._notify(ctx, "문서평가", 6)
        elif seg == "PROTO":
            self._wait(ctx, "산출물확인", "artifact")
            self._notify(ctx, "산출물확인", 8)
        elif seg in ("REWORK6", "REWORK8", "REWORK9"):
            screen = run.cycle.screen
            rescored = list(run.cycle.rescored_layers)
            assert self.engine is not None
            self.engine.end_cycle(ctx)
            self._wait(ctx, SCREEN_STEP[screen], "document" if screen == 6 else "artifact")
            # 재작성으로 검증을 다시 실행한 경우에도 알림. 대상 화면은 요청한 화면 (잠정)
            kind = "문서평가" if screen == 6 or rescored == ["document"] else "산출물확인"
            self._notify(ctx, kind, screen)
        elif seg == "REVIEW":
            run.state = make_state("결과물", "완료")
            run.current_phase = "review"
            run.segment, run.segment_total, run.ended_at = None, 0, self.now()
            self._notify(ctx, "표현검수", 10)
        else:
            raise RuntimeError(f"알 수 없는 구간: {seg}")

    def on_unresumable(self, ctx: RunContext, step_id: str, outcome: Outcome) -> None:
        if ctx.provisional:
            return  # 사전 단계 — 실행 건을 만들지 않고 호출한 쪽이 안내한다
        # 재개하지 않는 단계는 사전 단계(T-C1 · T-C2)에서만 돌거나, 실패를 흐름이 받는 구간(추가 조회 T-C2 · 자격 확인 G-01,
        # on_rescue)에서만 돈다. 여기 오면 실행 건이 같은 단계를 되풀이하므로 멈춘다
        raise RuntimeError(f"흐름이 받지 않는 재개 불가 실패: {step_id}")

    def on_rescue(self, ctx: RunContext, step_id: str, failure: StepFailure) -> None:
        """실패 정책이 흐름에 넘긴 실패 (등록부 rescue_segments). 실행을 실패시키지 않는다."""
        if step_id == "T-C2" and ctx.run.segment == "MORE":
            # 추가 조회 실패 (spec 4.2.3) — 재시도 소진 · 코드 오류 · 규격 위반 등 어떤 오류든 X-C2-FAIL(잠정).
            # 실패한 T-C2는 산출물을 남기지 않았다
            self._more_failed(ctx, "X-C2-FAIL")
            return
        if step_id == "G-01":
            # 자격 확인 실패 (spec 4.3.4) — 공고 없음은 X-C2-GONE, 그 밖의 모든 오류는 X-C2-FAIL. 고르기 전 대기 지점으로
            # 돌아가고, 선택 공고 · 자격 결과 · 업력 · announcement_id는 고르기 전 그대로다(G-01이 아무것도 저장하지 않았다).
            # 막힌 공고 목록에도 넣지 않는다(4.3.6)
            self._notice(ctx, "X-C2-GONE" if failure.kind == "대상없음" else "X-C2-FAIL")
            self._wait(ctx, self._before_selection(ctx), "setup")
            return
        raise RuntimeError(f"흐름이 받지 않는 단계 실패: {step_id}")

    # ── 추가 조회 (spec 4.2.2 · 4.2.3) ─────────────────────
    def more_lookup_pointers(self, ctx: RunContext) -> dict[str, int | None]:
        """추가 조회 전 T-C2 출력의 현재 버전 — 추가 조회 명령이 decision에 남기고, 실패하면 이 버전으로 돌린다."""
        return {key: ctx.version(key) for key in self.registry.get("T-C2").outputs.values()}

    def _keep_more(self, ctx: RunContext, received: list[AnnouncementCard], outcome: Outcome) -> None:
        """유효한(성공한) 추가 조회 — 추가 조회 결과(T-C2 출력)와 같은 저장에서 겹침 뺀 추가 후보 · 첫 조회 갱신본을 남기고,
        내용이 바뀐 막힌 공고를 푼다 (4.2.2 · 4.3.6). 내용이 그대로인 막힌 공고는 겹쳐 나와도 막힌 채다."""
        first, _ = candidate_lists(ctx)
        refreshed, more = merge_more_candidates(first, received)
        producer = f"orchestrator:{outcome.record.execution_id}" if outcome.record else "orchestrator:추가조회"
        refs = [ctx.put(FIRST_CANDIDATES, refreshed, producer=producer),
                ctx.put(MORE_CANDIDATES, more, producer=producer)]
        changed = [card.announcement_id for card in refreshed if card.content_changed]
        released = [aid for aid in changed if aid in ctx.run.blocked_announcement_ids]
        for aid in released:
            unblock_announcement(ctx.run, aid)
        ctx.add_event("추가조회반영", f"겹침 {len(received) - len(more)}건 · 내용 바뀜 {len(changed)}건 · "
                                      f"막힘 풀림 {len(released)}건", refs=refs,
                      execution_id=outcome.record.execution_id if outcome.record else None)

    def _more_failed(self, ctx: RunContext, code: str) -> None:
        """실패한 추가 조회 (4.2.3) — 실행을 살리고 안내(X-C2-FAIL · E-C2-STALE) 후 공고선택 · 사용자대기로 간다.

        - 기회를 돌려준다(more_used 거짓 → 화면 3 moreAvailable 참).
        - T-C2 출력 포인터를 조회 전 버전으로 돌린다(수집 상태 비정상이면 T-C2가 새 버전을 남겼다 — 버전은 지우지 않는다).
          화면 3의 수집 상태 · 통과 건수 · 대체 경로 표시는 조회 전 값이고, 후보 목록은 candidate_lists가 실패한 조회를 보지 않는다.
        - 추가 후보 · 첫 조회 갱신본을 남기지 않고, 막힌 공고를 풀지 않는다(4.3.6).
        - 돌아가는 곳은 늘 공고선택이다 — 자격 통과 뒤(계획서작성 · 사용자대기)에 누른 추가 조회도 같다(고르기 전 대기 지점 아님).
        """
        decision = ctx.get_ref(ctx.run.decision_ref) if ctx.run.decision_ref else {}
        before = decision.get(MORE_BEFORE_POINTERS) if isinstance(decision, dict) else None
        for key, version in (before or {}).items():
            if version is not None:
                ctx.move_pointer(key, version, f"추가 조회 실패 — 조회 전으로 ({code})")
        ctx.run.more_used = False
        ctx.add_event("추가조회실패", f"{code} — 조회 전 후보로 두고 추가 조회 기회를 돌려줌")
        self._notice(ctx, code)
        self._wait(ctx, "공고선택", "setup")

    @staticmethod
    def _before_selection(ctx: RunContext) -> str:
        """공고 선택 명령이 남긴 고르기 전 대기 지점(단계). 없거나 알 수 없으면 공고선택."""
        decision = ctx.get_ref(ctx.run.decision_ref) if ctx.run.decision_ref else {}
        step = decision.get("beforeStep") if isinstance(decision, dict) else None
        return step if step in SELECTION_STEPS else "공고선택"

    def on_abort(self, ctx: RunContext) -> None:
        run = ctx.run
        run.queue, run.redo_state, run.cycle, run.rework_screen = [], None, None, None
        run.state = make_state(run.state.step, "중단")
        run.ended_at = self.now()
        ctx.add_event("중단", "사용자 중단 (Task 사이에서 반영)")

    def on_run_failed(self, ctx: RunContext, reason: str) -> None:
        self._notice(ctx, "E-RUN-FAIL")
        self._notify(ctx, "실패", None, scope="실행")

    def on_cycle_failed(self, ctx: RunContext, reason: str) -> None:
        screen = ctx.run.cycle.screen
        assert self.engine is not None
        self.engine.end_cycle(ctx)
        self._wait(ctx, SCREEN_STEP[screen], "document" if screen == 6 else "artifact")
        self._notice(ctx, "E-RUN-ROLLBACK")
        if ctx.run.last_rework is not None:
            ctx.run.last_rework.notice_code = "E-RUN-ROLLBACK"
        self._notify(ctx, "실패", screen, scope="재작성")

    # ── 재작성 전후 비교 (Orchestrator 내부 단계) ──────────
    def _cycle_end(self, engine: Engine, ctx: RunContext) -> Outcome:
        cyc = ctx.run.cycle
        assert cyc is not None
        snap = cyc.snapshot
        doc_changed = ctx.pointers.get("docScore") != snap.get("docScore")
        art_changed = ctx.pointers.get("artifactScore") != snap.get("artifactScore")

        def total(key: str, version: int | None) -> float:
            return ctx.get(key, version).total if version else 0.0

        doc_b, doc_a = total("docScore", snap.get("docScore")), total("docScore", ctx.pointers.get("docScore"))
        art_b, art_a = total("artifactScore", snap.get("artifactScore")), total("artifactScore", ctx.pointers.get("artifactScore"))
        if doc_changed and art_changed:
            basis, before, after = "total", doc_b + art_b, doc_a + art_a
        elif doc_changed:
            basis, before, after = "document", doc_b, doc_a
        elif art_changed:
            basis, before, after = "artifact", art_b, art_a
        else:
            basis, before, after = "none", 0.0, 0.0
        cyc.rescored_layers = [l for l, ch in (("document", doc_changed), ("artifact", art_changed)) if ch]
        engine.compare_and_keep(ctx, before=before, after=after, basis=basis)
        return Outcome("ok")

    # ── T-P2 문장별 병렬 실행기 ────────────────────────
    def _run_tp2(self, engine: Engine, ctx: RunContext) -> Outcome:
        spec = self.registry.get("T-P2")
        s = ctx.settings
        rs = ctx.run.redo_state if ctx.run.redo_state and ctx.run.redo_state.task_id == "T-P2" else None
        resuming = rs is not None and rs.pending_execution_id is not None
        rs = rs or self.initial_redo_state(ctx, spec)
        rec = engine.open_execution(ctx, spec, rs)
        rec.inputs = [ctx.ref(k) for k in ("targetSentenceIds", "protectedTokens", "formatFindings",
                                           "planDoc", FORM_SPEC) if ctx.has(k)]
        targets: list[str] = ctx.get("targetSentenceIds")
        tokens = ctx.get("protectedTokens")

        def finish(results: list[c.SentenceResult], status: str, note: str | None = None) -> Outcome:
            ref = ctx.put("sentenceResults", results, producer=rec.execution_id)
            rec.outputs, rec.result_ref, rec.status, rec.ended_at = [ref], ref, status, self.now()
            rec.output_meta.note = note
            ctx.record_execution(rec)
            ctx.record_attempt(rec)
            ctx.run.redo_state = None
            return Outcome("ok", {"sentence_results": results}, rec)

        if not targets or not tokens:
            # 윤문 대상 0건이면 T-P2를 실행하지 않고, 보호 토큰 0건이면 형식 검수만 하고 윤문을 생략한다
            return finish([], "생략", "윤문 대상 없음" if not targets else "보호 토큰 0건 — 윤문 생략")

        sink = CallSink()
        try:
            cfg = engine.tools_config(ctx, spec)
            rec.model, rec.provider, rec.temperature = cfg.model, cfg.provider, cfg.temperature
            rec.reasoning_effort = cfg.reasoning_effort
            tools = engine.make_tools(ctx, spec, rec, cfg, sink)
            plan = ctx.get("planDoc")
            sentences = {x.sentence_id: x for sec in plan.sections for x in sec.sentences}
            fspec = ctx.get(FORM_SPEC).format_spec   # 서술 형식 — T-C3가 고른 양식 (T-C3 spec 4)
            findings = ctx.get("formatFindings")
            prior = {r.sentence_id: r for r in ctx.get("sentenceResults", default=[])} if resuming else {}
            todo = [sid for sid in targets if sid not in prior or prior[sid].kept_reason == "호출실패"]
            limit = s.redo.proofread_limit

            def one(sid: str) -> c.SentenceResult:
                original = sentences[sid]
                item_tools = tools.for_item(sid)
                hint: list[str] = []
                redo, prev_hash = 0, None
                mine = [f for f in findings if f.sentence_id == sid]
                attempts = list(prior[sid].attempts) if sid in prior else []   # 재개면 이전 시도에 이어서 센다

                def result(**kw: Any) -> c.SentenceResult:
                    return c.SentenceResult(sentence_id=sid, final_redo_count=redo, attempts=attempts, **kw)
                while True:
                    try:
                        out = spec.fn(c.TP2In(sentence=original, protected_tokens=tokens, format_findings=mine,
                                              format_spec=fspec, redo_hint=list(hint), redo_count=redo), item_tools)
                    except ToolCallExhausted:   # 호출 실패는 시도가 아니다
                        return result(adopted=False, kept_reason="호출실패")
                    out = out if isinstance(out, c.TP2Out) else c.TP2Out.model_validate(out)
                    adopted = out.adopted and out.token_check.passed
                    attempts.append(c.ProofreadAttempt(
                        attempt_no=len(attempts) + 1, text=out.revised.text, adopted=adopted,
                        token_check=out.token_check,
                        violation_type=None if out.token_check.passed else violation_type(out.token_check, tokens)))
                    if adopted:
                        return result(adopted=True, revised=out.revised, token_check=out.token_check)
                    h = hashlib.sha256(out.revised.text.encode("utf-8")).hexdigest()
                    if prev_hash is not None and h == prev_hash:
                        return result(adopted=False, kept_reason="조기중단", token_check=out.token_check)
                    if redo >= limit:
                        return result(adopted=False, kept_reason="검증실패", token_check=out.token_check)
                    hint.extend(x for x in out.next_redo_hint if x not in hint)  # 교체하지 않고 누적
                    prev_hash, redo = h, redo + 1

            with ThreadPoolExecutor(max_workers=max(1, s.proofread.concurrency)) as pool:
                done = dict(zip(todo, pool.map(one, todo)))
            engine.collect_calls(ctx, rec, sink)   # 문장별 호출 토큰을 T-P2 실행 기록에 합산
        except Exception as e:  # Agent 코드 오류 등
            engine.collect_calls(ctx, rec, sink)
            return engine.on_step_error(ctx, spec, rec, e)

        # 반려된 시도는 이번 T-P2 저장(완료 또는 재개 예약)과 같은 묶음으로 넘긴다
        self._hand_over_rejected(ctx, rec.model, sentences, prior, done)
        merged = {**prior, **done}
        results = [merged[sid] for sid in targets if sid in merged]
        failed = [r for r in results if r.kept_reason == "호출실패"]
        if failed and len(failed) / len(targets) > s.proofread.failure_ratio_threshold:
            if engine.can_resume(ctx) is not None:
                ref = ctx.put("sentenceResults", results, producer=rec.execution_id)
                rec.outputs, rec.result_ref = [ref], ref
                rs.pending_execution_id = rec.execution_id
                return engine.schedule_resume(ctx, rec, rs, "일시")
            ctx.add_event("검수재개상한", "실패 비율이 기준을 넘었으나 재개 상한 초과 — 원문 유지한 채 완료",
                          execution_id=rec.execution_id)
        return finish(results, "성공")

    @staticmethod
    def _hand_over_rejected(ctx: RunContext, model: str | None, sentences: dict[str, Any],
                            prior: dict[str, c.SentenceResult], done: dict[str, c.SentenceResult]) -> None:
        """이번에 새로 만든 반려된 시도만 저장 묶음에 넘긴다 (이전 저장에서 넘긴 시도는 다시 넘기지 않는다)."""
        for sid, res in done.items():
            before = len(prior[sid].attempts) if sid in prior else 0
            for a in res.attempts[before:]:
                if a.token_check.passed:
                    continue
                ctx.add_rejected_attempt(RejectedAttempt(
                    run_id=ctx.run.run_id, original_text=sentences[sid].text, corrected_text=a.text,
                    reason=violation_reason(a.token_check), attempt_no=a.attempt_no,
                    violation_type=a.violation_type, violation_note=violation_note(a.token_check),
                    model_version=model))

    # ── 도움 함수 ─────────────────────────────────────
    def _wait(self, ctx: RunContext, step: str, phase: str) -> None:
        run = ctx.run
        run.state = make_state(step, "사용자대기")
        run.current_phase = phase
        run.segment, run.segment_total, run.queue = None, 0, []

    def _notice(self, ctx: RunContext, code: str, *, suffix: str = "", **slots: str) -> None:
        """안내를 쌓는다. 문구는 errors.message — suffix는 errors가 둔 덧붙임(EMBED_DEADLINE_SUFFIX)만 쓴다."""
        ctx.run.notices.append(Notice(code=code, message=message(code, **slots) + suffix, at=self.now()))

    def _notify(self, ctx: RunContext, kind: str, target: int | None, scope: str | None = None) -> None:
        ctx.notify(Notification(run_id=ctx.run.run_id, kind=kind, failure_scope=scope, target_step=target,
                                created_at=self.now(), notification_id=self.new_id()))
