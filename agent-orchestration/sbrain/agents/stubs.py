"""스텁 Agent — 뼈대 검증용. 7개 Agent(조율 포함)의 Task와 합치기를 타입에 맞는 더미 결과로 구현한다.

- LLM Task 스텁은 tools.llm을 한 번 이상 불러 tools 경로를 거치게 한다. T-W3는 LLM을 부르지 않는 Task(uses_llm=False)라
  부르지 않는다(부르면 'LLM 설정 없음'으로 바로 실패한다).
- 전략 · 작성 · 검증-1 확장 출력(strategyData · sectionOutputs · diagrams · tableSections · sectionResults 등, spec 4.7)은
  규격에 맞는 더미로 채운다. 계획서 항목은 formSpec의 항목 · 태그 · 종류를 따른다(태그 · 종류 칸이 비면 태그 없음 · 본문).
  T-W1 · T-W2 · T-W3 · T-V1은 목표 항목(reworkInput.targetItems)만 다시 만들고(판정하고) 나머지는 base… 입력을 그대로 잇는다.
  T-W3는 fallbackItems의 표를 본문 서술로 대체하고, 자체 검사 불통과면 그 시도에서 바로 대체한다 (spec 4.8 · 4.10).
- 스텁 T-V1은 StubScenario의 항목 판정(fail · warning · 입력 없음)을 따르고, 스텁 G-02a · G-02b는 계획서 묶음 후보 ·
  다음 동작 · '입력 확인 필요' 안내를 spec 4.12 규칙으로 낸다(문서층 배점은 설정 사본 scoring.docLayerMax).
- StubScenario로 점수 · 검사 결과 · 오류를 조절해 흐름 테스트를 만든다.
- 공고 서버 연결이 없을 때의 T-C2 · G-01(스텁 모드, spec 4.6): 스텁 G-01은 스텁 공고를 직접 만들고 공고 서버 판정과 같은
  원칙(확실히 안 되는 경우만 불통과, 읽지 못한 조건은 확인 필요)으로 판정한다. 스텁 공고에는 업력 상한이 없다.
- 파일(진입 파일 · 인포그래픽 그림 · 안내 문서 · 계획서 파일)은 작은 자리채움 내용을 tools.files(G-04는 파일 창구 인자)로
  넣고 받은 참조(FileRef)를 출력에 싣는다. 차트 그림은 비운다. 스텁 T-V2는 파일을 읽지 않는다(채점 방식 그대로).
- 실제 구현이 나오면 registry.bind(task_id, fn)로 바꿔 끼운다.
"""
from __future__ import annotations

import math
import struct
import threading
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from pydantic import BaseModel

from ..contracts import tasks as c
from ..models import (
    Announcement, AnnouncementCard, ArtifactScore, BonusItem, ChartSpec, CheckResult, CodeCheck,
    CodeCheckResult, CompanyInfo, Deliverable, DiagramSpec, DocScore, DocScoreItem, EligibilityRule,
    FeatureMatchResult, FormatFinding, FormSpec, GateResult,
    Infographic, ItemSpec, MarketAnalysis, MarketSizeItem, PlanDoc, PlanSection,
    ProofreadLog, Prototype, ReferenceDoc, RequirementAnalysis, ReworkDiff, ReworkOrder,
    ScoreReport, SectionResult, Sentence, TableSpec, Token, TokenCheckResult,
)
from ..models.clock import kst_today, utc_clock, utc_now
from ..orchestrator import settings
from ..orchestrator.errors import FormatError, ProviderError, ResourceNotFound, ToolCallExhausted
from ..orchestrator.registry import TaskRegistry
from ..orchestrator.tools import FileTool, ImageRequest, ImageResponse, LLMRequest, LLMResponse, TokenUsage, Tools
from ..flow.rework_map import (
    KIND_TASK, REWORK_DEFAULT_REASON, TASK_BUNDLE, artifact_rework_reasons, document_bundles, order_bundles,
    section_bundle,
)
from .form_defaults import default_evaluation_items, default_form_spec, stub_rubric
from .notice.g01 import PRE_STARTUP, business_age_years   # 업력(년) 반올림은 실제 G-01과 한 곳에서 (스텁 테스트도 이 이름을 쓴다)
from .supervisor import plan as task_plan   # 작업 분해 부품 — 실제 T-C3와 같은 확인 · 양식 고르기 · 목록 · 틀 · 맥락

# 문서층 배점 기본값 — 판정(G-02a · G-02b)은 설정 사본의 scoring.docLayerMax를 쓰고, 사본에 없을 때만 이 값이다 (spec 4.12)
DOC_LAYER_MAX = 70.0
# 입력 없음 항목이 있을 때 점수 보고서 notices에 더하는 안내 (잠정 문구, spec 4.12)
INPUT_MISSING_NOTICE = "입력 확인 필요 — 사업비 집행계획 · 추진 일정을 입력하면 해당 표가 채워집니다."
# 스텁 T-V1의 입력 없음 warning (실구현은 '입력 확인 필요 — <사업비 집행계획 | 추진 일정>', spec 4.9)
STUB_INPUT_MISSING_WARNING = "입력 확인 필요 — 사업비 집행계획 · 추진 일정"
# 코드 점검 8칸 — 구현 · 검증-2 담당 개정안(1.3판)의 배점 · 이름. 진입 파일 · 비밀값 · sandbox는 통과 필수 조건으로 옮겨
# 칸에 없다(gate_failures)
HTML_WEIGHTS = [3, 2, 2, 2, 1, 2, 2, 1]
SVG_WEIGHTS = [2, 3, 2, 2, 2, 2, 1, 1]
HTML_NAMES = ["동작 연결", "대체 텍스트", "label 연결", "명도 대비", "제목 계층", "1440px 폭", "스크립트 동작 오류 없음",
              "임시 문구 없음"]
SVG_NAMES = ["대체 텍스트", "핵심 정보 6항목", "명도 대비", "정보 계층", "잘림 없음", "지면 밖 넘침 없음", "텍스트 실재성",
             "최소 글자 크기"]
# 파일 이름 · 형식 (이름 규칙). 웹개발 · AI API 진입 파일명은 index.html (2026-09-30 결정 9),
# 원페이지는 T-B2가 지면을 onepage.svg로 넣고 M-2가 그 참조를 진입 파일로 감싼다
ENTRY_FILE = "index.html"
ONEPAGE_FILE = "onepage.svg"
INFOGRAPHIC_FILE = "infographic.png"
README_FILE = "README.md"
PLAN_DOC_FILE = "plan.docx"
HTML_TYPE, SVG_TYPE, PNG_TYPE, MARKDOWN_TYPE = "text/html", "image/svg+xml", "image/png", "text/markdown"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# 자리채움 내용 — 스텁 파일은 작다. 계획서 파일은 진짜 워드 파일이 아니다(형식만 워드)
STUB_HTML = "<!doctype html><html lang='ko'><body>스텁 프로토타입</body></html>".encode()
STUB_SVG = "<svg xmlns='http://www.w3.org/2000/svg'><text>원페이지</text></svg>".encode()
STUB_README = "# 실행 · 열람 안내\n\n스텁 안내 문서 — 열람 · 인쇄 · 실행 방법 자리.\n".encode()
STUB_PLAN_DOC = b"stub plan docx placeholder"
# 스텁 공고 · 카드 값 — 모집 형태 표기(spec 4.4), 가산점
PERIOD_FIXED = "기간 있음"
PERIOD_OPEN = "상시·수시"            # 마감일 없는 공고 (no_deadline_ids)
STUB_BONUS = [BonusItem(name="가점 항목", points=1.0)]
STUB_BONUS_CHANGED = [BonusItem(name="가점 항목", points=1.0), BonusItem(name="추가 가점", points=1.0)]
# 추가 조회에서 카드 내용을 바꾸는 종류 (StubScenario.more_changes)
MORE_CHANGE_KINDS = ("정보", "버전", "적합도", "가산점")
# 스텁 T-C3의 안내 — LLM 대신 쓰는 고정 더미 문장
STUB_GUIDANCE = "{task_id} 스텁 안내 — 이 아이템 · 공고에 맞춘 안내 자리입니다."
# 전략 · 작성 · 검증-1 확장 출력의 더미 키 (담당자 canonical 키, spec 4.7)
STRATEGY_KEYS = ("web_data", "item_spec", "team_capability", "development_goal", "development_method", "architecture",
                 "development_plan", "production_plan", "resource_plan", "budget", "schedule", "feasibility_plan",
                 "research", "original_facts")
MARKET_KEYS = ("market_analysis", "competitor_analysis", "marketing_strategy", "business_model", "growth_strategy")
# 스텁 그림 — 담당자 F18의 두 그림(서비스 흐름도 · 서비스 구조도)과 파일 이름 (spec 4.6)
STUB_DIAGRAMS = (("USER_FLOW", "userflow.svg"), ("SERVICE_ARCHITECTURE", "architecture.svg"))
STUB_DIAGRAM_SVG = "<svg xmlns='http://www.w3.org/2000/svg'><text>스텁 그림</text></svg>".encode()
STUB_SCORE_POLICY = "stub-policy-1"   # 스텁 채점 정책 버전 — 채점 기준표 버전이 없을 때

# 기획서 6-8 고정 문구
DISCLAIMER = "본 문서는 S-Brain이 생성한 초안입니다. 제출 전 작성자 본인의 확인과 수정이 필요합니다."
SCORE_NOTICE = "검증 점수는 서비스 내부 기준(rubric 상수)에 따른 값이며 실제 심사 점수가 아닙니다."
PROTOTYPE_NOTICE = "이 프로토타입은 AI가 생성했습니다."
SUBMISSION_NOTICE = "공고에 따라 AI 작성 문서의 제출을 제한하거나 명시를 요구할 수 있습니다. 제출 요건을 확인해주세요."


class Ack(BaseModel):
    ok: bool


# ── 가짜 LLM 호출처 ───────────────────────────────────
class FakeLLM:
    """스크립트대로 응답하는 가짜 호출처. script[(task_id, item_key)] = ['timeout', 'ok', ...]."""

    def __init__(self) -> None:
        self.script: dict[tuple[str, str | None], list[str]] = {}
        self.responders: dict[str, Callable[[LLMRequest], str]] = {}
        self.requests: list[LLMRequest] = []
        self.usage: dict[str, TokenUsage] = {}   # Task별 토큰 사용량 — 응답(형식 오류 응답 포함)에 실어 돌려준다
        self._lock = threading.Lock()

    def plan(self, task_id: str, outcomes: list[str], item_key: str | None = None) -> None:
        self.script[(task_id, item_key)] = list(outcomes)

    def respond(self, task_id: str, fn: Callable[[LLMRequest], str]) -> None:
        """'ok'일 때 돌려줄 응답 본문을 정한다 (실제 Task 구현을 스텁 호출처로 시험할 때)."""
        self.responders[task_id] = fn

    def complete(self, request: LLMRequest) -> str:
        with self._lock:
            self.requests.append(request)
            key = (request.metadata["task_id"], request.metadata.get("item_key"))
            queue = self.script.get(key) or self.script.get((key[0], None)) or []
            outcome = queue.pop(0) if queue else "ok"
        if outcome == "timeout":
            raise TimeoutError()
        if outcome == "rate_limit":
            raise ProviderError("429", status=429)
        if outcome == "bad_request":
            raise ProviderError("400", status=400)
        if outcome == "auth":
            raise ProviderError("401", status=401)
        if outcome == "bad_json":
            return self._with_usage(key[0], "not json")
        responder = self.responders.get(key[0])
        return self._with_usage(key[0], responder(request) if responder else '{"ok": true}')

    def _with_usage(self, task_id: str, reply: str | LLMResponse) -> str | LLMResponse:
        usage = self.usage.get(task_id)
        if usage is None or isinstance(reply, LLMResponse):
            return reply
        return LLMResponse(reply, usage)


def _tiny_png() -> bytes:
    """1×1 흰 점 PNG (가짜 이미지 호출처의 결과)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])   # PNG 파일 머리
    return (signature + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes([0, 255, 255, 255]))) + chunk(b"IEND", b""))


class FakeImage:
    """스크립트대로 응답하는 가짜 이미지 호출처 (확장). script[(task_id, item_key)] = ['timeout', 'ok', ...].

    결과는 늘 같은 작은 PNG(1×1)다. usage[task_id]를 주면 응답(빈 그림 응답 포함)에 사용량을 싣는다 — 없으면 None.
    결과: ok · timeout · rate_limit(429) · bad_request(400) · auth(401) · empty(빈 그림 → 형식 오류).
    requests에는 받은 요청을 모은다(시험 확인용 — 메모리에만 있고 기록에 남지 않는다).
    """
    PNG = _tiny_png()

    def __init__(self) -> None:
        self.script: dict[tuple[str, str | None], list[str]] = {}
        self.requests: list[ImageRequest] = []
        self.usage: dict[str, TokenUsage] = {}
        self._lock = threading.Lock()

    def plan(self, task_id: str, outcomes: list[str], item_key: str | None = None) -> None:
        self.script[(task_id, item_key)] = list(outcomes)

    def create(self, request: ImageRequest) -> ImageResponse:
        with self._lock:
            self.requests.append(request)
            key = (request.metadata["task_id"], request.metadata.get("item_key"))
            queue = self.script.get(key) or self.script.get((key[0], None)) or []
            outcome = queue.pop(0) if queue else "ok"
        usage = self.usage.get(key[0])
        if outcome == "timeout":
            raise TimeoutError()
        if outcome == "rate_limit":
            raise ProviderError("429", status=429)
        if outcome == "bad_request":
            raise ProviderError("400", status=400)
        if outcome == "auth":
            raise ProviderError("401", status=401)
        if outcome == "empty":
            raise FormatError("빈 그림", usage=usage)
        return ImageResponse(self.PNG, usage)


# ── 시나리오 ──────────────────────────────────────────
@dataclass
class StubScenario:
    """흐름 테스트의 상황 조절. 집합 · 사전 값은 테스트 중에 바꿔도 다음 호출부터 반영된다(스텁이 부를 때마다 읽는다)."""
    category: str = "웹개발"
    candidate_count: int = 10
    collection_status: str = "정상"                                         # T-C2 수집 상태. '정상'이 아니면 후보 0건
    gate_fail_ids: set[str] = field(default_factory=set)                    # 신청자 유형이 맞지 않아 불통과인 공고
    doc_scores: list[float] = field(default_factory=lambda: [60.0])         # T-V1 차례대로 (마지막 반복)
    art_scores: list[tuple[float, float]] = field(default_factory=lambda: [(15.0, 11.0)])  # T-V2 (코드, 대조 손잡이 0 ~ 15)
    check_fail_times: dict[str, int] = field(default_factory=dict)          # Task별 검사 불통과 횟수
    omit_final_action: set[str] = field(default_factory=set)                # 확정 동작을 빠뜨릴 Task
    tw1_change_features: bool = False
    # ── 산출물층 검증 (스텁 T-V2 · 1.4판 모양) ──
    partial_features: list[str] | None = None       # 부분 인정으로 둘 기능 — 나머지 충족 · 미충족은 대조 손잡이로 다시 맞춘다
    withhold_feature_match: bool = False            # 대조 판정 보류(E-V2-NOFEATURE)를 흉내 — featureList는 바꿀 수 없어서
    gate_failures: list[str] = field(default_factory=list)                  # 통과 필수 조건 실패 (entry · secret · sandbox)
    alt_defect_sources: list[str] = field(default_factory=lambda: ["infographic"])  # HTML 2번 불통과의 결함 출처
    diagnostics: list[str] = field(default_factory=list)                    # T-V2 진단 (관리자 전용)
    tp1_targets: int = 3
    no_tokens: bool = False
    tp2_behavior: dict[str, list[str]] = field(default_factory=dict)       # 문장별 'ok' · 'violate' · 'same'
    raise_in: set[str] = field(default_factory=set)                         # 코드 오류를 낼 단계
    embed_fail: bool = False                                                # T-C2 임베딩 검색 오류 → BM25단독 대체 경로
    # ── 공고 · 자격 확인 (spec 4.6) ──
    exhaust_in: set[str] = field(default_factory=set)                       # 외부 호출이 재시도를 다 쓰는 단계 (T-C2 · G-01)
    unknown_ids: set[str] = field(default_factory=set)                      # 자격 조건을 읽지 못한 공고 → 확인 필요
    closed_ids: set[str] = field(default_factory=set)                       # 모집 상태 '마감'인 공고
    no_deadline_ids: set[str] = field(default_factory=set)                  # 마감일 없는 공고 (상시·수시)
    no_amount_ids: set[str] = field(default_factory=set)                    # 지원 금액 · 금액 표기가 없는 공고
    not_found_ids: set[str] = field(default_factory=set)                    # G-01이 공고 없음을 받는 공고
    null_bonus_ids: set[str] = field(default_factory=set)                   # 가산점을 계산하지 못한 카드 (null · 빈 목록)
    no_version_ids: set[str] = field(default_factory=set)                   # 내용 버전(contentVersion)이 없는 카드
    deadline_fallback: bool = False                                         # 대체 경로 '마감임박순' — 적합도 0
    # ── 추가 조회(offset > 0)에서만 ──
    more_ids: list[str] | None = None                       # 추가 조회가 돌려줄 공고 ID (첫 조회와 겹치게 할 수 있음)
    more_changes: dict[str, set[str]] = field(default_factory=dict)   # 공고 ID → 바꿀 내용: MORE_CHANGE_KINDS
    more_error: str | None = None                           # '코드오류' · '재시도소진'
    more_collection_status: str | None = None               # 추가 조회의 수집 상태 ('정상'이 아니면 후보 0건)
    # ── 검증-1 항목별 판정 (스텁 T-V1 sectionResults, spec 4.15) — 판정할 때마다 읽는다 ──
    fail_items: set[str] = field(default_factory=set)            # 판정할 때마다 status fail로 둘 항목 번호
    warning_items: set[str] = field(default_factory=set)         # status warning으로 둘 항목 번호
    input_missing_items: set[str] = field(default_factory=set)   # 입력 없음(warning · inputMissing)으로 둘 항목 번호
    fail_item_times: dict[str, int] = field(default_factory=dict)  # 항목 → 처음 몇 번의 판정을 fail로 둘지 (그 뒤 pass)
    # ── 자체 검사 항목 (check.failedItems, spec 4.8) — Task → 불통과로 둘 항목 번호. 비면 항목 없이 불통과 ──
    check_fail_items: dict[str, list[str]] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def tick(self, name: str) -> int:
        with self._lock:
            n = self._counters.get(name, 0)
            self._counters[name] = n + 1
            return n

    def pick(self, name: str, seq: list) -> Any:
        i = self.tick(name)
        return seq[min(i, len(seq) - 1)]


# ── 데이터 공급 (공고 DB · 상수) ──────────────────────────
def make_announcement(announcement_id: str, today: date, *, eligible: bool = True) -> Announcement:
    """스텁 공고 — 업력 상한 없음, 모집 형태 '기간 있음', 양식 · 평가 항목은 기본 양식 (spec 4.6)."""
    return Announcement(
        announcement_id=announcement_id, title=f"창업지원사업 {announcement_id}", agency="중소벤처기업부",
        support_field="창업(06)", apply_start=today - timedelta(days=10), apply_end=today + timedelta(days=30),
        status="모집중",
        eligibility=EligibilityRule(applicant_types=["예비창업자", "개인사업자", "법인"] if eligible else [],
                                    business_age_max_years=None),
        eligibility_parsed=True, support_amount_max=100_000_000, support_amount_text="1억원",
        form_spec=default_form_spec(), evaluation_items=default_evaluation_items(),
        summary_embedding=[], apply_period_type=PERIOD_FIXED,
    )


def stub_announcement(sc: StubScenario, announcement_id: str, today: date) -> Announcement:
    """스텁 G-01이 받는 공고 상세 — 상황 조절(불통과 · 확인 필요 · 마감 · 마감일 없음 · 금액 없음)을 입힌다."""
    update: dict[str, Any] = {}
    if announcement_id in sc.unknown_ids:
        update["eligibility_parsed"] = False
    if announcement_id in sc.closed_ids:
        update["status"] = "마감"
    if announcement_id in sc.no_deadline_ids:
        update.update(apply_end=None, apply_period_type=PERIOD_OPEN)
    if announcement_id in sc.no_amount_ids:
        update.update(support_amount_max=None, support_amount_text=None)
    ann = make_announcement(announcement_id, today, eligible=announcement_id not in sc.gate_fail_ids)
    return ann.model_copy(update=update)


def business_age_months(founded_at: date, today: date) -> int:
    """업력 개월 — 공고팀과 같게 센다: (올해 − 설립 연도) × 12 + (이번 달 − 설립 달), 오늘 날짜가 설립일 날짜보다
    작으면 1을 빼고, 0보다 작으면 0 (spec 4.6)."""
    months = (today.year - founded_at.year) * 12 + (today.month - founded_at.month)
    if today.day < founded_at.day:
        months -= 1
    return max(months, 0)


def stub_gate(company: CompanyInfo, ann: Announcement, today: date) -> tuple[GateResult, float | None]:
    """스텁 자격 판정 — 공고 서버 판정(spec 3.2.2 · 4.3.2)과 같은 원칙. 확실히 안 되는 경우만 불통과다.

    - 사업자(개인사업자 · 법인)인데 설립일이 없으면 판정하지 않고 missingInputs = ['foundedAt'] (E-G1-MISSING).
    - 조건을 읽지 못했으면(eligibilityParsed 거짓) 통과로 보고, 그 신청자에게 해당하는 조건을 확인 필요로 둔다.
    - 신청자 유형이 허용 유형에 없으면 '지원대상 유형', 업력 상한이 있고 업력 개월 ≥ 상한 × 12면 '업력' 불통과.
    - 접수기간 · 모집 상태는 보지 않는다. undecidable은 늘 거짓이다.
    업력(년)은 예비창업자면 None, 사업자면 업력 개월 / 12를 소수 한 자리로 반올림한다.
    """
    business = company.applicant_type != PRE_STARTUP
    if business and company.founded_at is None:
        return GateResult(passed=False, failed_conditions=[], missing_inputs=["foundedAt"], undecidable=False), None
    months = business_age_months(company.founded_at, today) if business and company.founded_at else None
    age_years = business_age_years(months) if months is not None else None
    if not ann.eligibility_parsed:
        unknown = ["지원대상 유형"] + (["업력"] if business else [])
        return GateResult(passed=True, failed_conditions=[], missing_inputs=[], undecidable=False,
                          unknown_conditions=unknown), age_years
    rule = ann.eligibility
    failed = []
    if company.applicant_type not in rule.applicant_types:
        failed.append("지원대상 유형")
    if months is not None and rule.business_age_max_years is not None and months >= rule.business_age_max_years * 12:
        failed.append("업력")
    return GateResult(passed=not failed, failed_conditions=failed, missing_inputs=[], undecidable=False), age_years


def make_constants() -> Callable:
    """상수 공급처 (조립이 흐름에 넘긴다). 채점 기준표는 이제 T-C3 출력(rubric 산출물)에서 오고, 이 공급처의 'rubric'을
    읽는 단계는 없다 — 조립(bootstrap)이 쓰므로 남겨 둔다."""
    rubric = stub_rubric()

    def constants(ctx, name: str) -> Any:
        if name == "rubric":
            return rubric
        raise KeyError(name)
    return constants


# ── 공통 도움 ─────────────────────────────────────────
def _ask(tools: Tools, purpose: str) -> None:
    tools.llm([{"role": "user", "content": purpose}], schema=Ack, purpose=purpose)


def _check(sc: StubScenario, task_id: str, rework_input, final_action: str, *, immediate: bool = False) -> CheckResult:
    """자체 검사 — check_fail_times[task_id]번까지 불통과. 불통과 항목은 check_fail_items[task_id](failedItems).
    확정 동작은 마지막 재수행 시도에서 채운다 — immediate면(재수행 없이 바로 확정하는 T-W3, spec 4.8) 그 시도에서."""
    fail_times = sc.check_fail_times.get(task_id, 0)
    n = sc.tick(f"check:{task_id}")
    if n < fail_times:
        failure = f"{task_id} 검사 불통과 {n + 1}"
        last = immediate or (rework_input is not None and rework_input.is_final_attempt)
        final = last and task_id not in sc.omit_final_action
        return CheckResult(passed=False, failures=[failure], final_action=final_action if final else None,
                           failed_items={code: [failure] for code in sc.check_fail_items.get(task_id, [])})
    return CheckResult(passed=True, failures=[])


def _targets(rework_input) -> set[str] | None:
    """재수행 · 재작성 입력의 목표 항목 — 없거나 비었으면 None(첫 실행 · 모든 항목, spec 4.7)."""
    return set(rework_input.target_items) if rework_input is not None and rework_input.target_items else None


def _form_items(form: FormSpec) -> list[tuple[str, str, str | None, str]]:
    """양식의 계획서 항목 (번호, 제목, 태그, 종류) — 양식 순서. 태그 · 종류 칸이 항목 수와 맞지 않으면(비어 있음 등)
    태그 없음 · 본문으로 본다."""
    codes, titles = form.section_codes, form.section_titles
    tags = form.section_tags if len(form.section_tags) == len(codes) else [None] * len(codes)
    kinds = form.section_kinds if len(form.section_kinds) == len(codes) else ["section"] * len(codes)
    return list(zip(codes, titles, tags, kinds))


def _stub_sentences(code: str, title: str) -> list[Sentence]:
    return [Sentence(sentence_id=f"s-{code}-{i}", text=f"{title} 문장 {i} (1억원)", is_title=False, paragraph_no=1)
            for i in range(1, 3)]


def _maybe_raise(sc: StubScenario, step: str) -> None:
    if step in sc.raise_in:
        raise RuntimeError(f"{step} 스텁 오류")


def _doc_score(total: float, maxes: list[tuple[str, float]]) -> DocScore:
    """문서층 점수 — 평가항목 = 계획서 항목(spec 4.9). 총점(시나리오 doc_scores)을 항목 배점 비율로 나누고(소수 둘째 자리,
    마지막 항목이 나머지) 항목 점수 합 = 총점이 되게 한다. 항목이 없으면 항목 없이 총점만."""
    items, acc = [], 0.0
    whole = sum(m for _, m in maxes) or 1.0
    for i, (code, m) in enumerate(maxes):
        s = round(m * total / whole, 2) if i < len(maxes) - 1 else round(total - acc, 2)
        acc += s
        items.append(DocScoreItem(item_code=code, score=s, max_score=m, evidence_locator=code, comment="감점 없음"))
    return DocScore(total=total, items=items)


def _doc_layer_max(snapshot: dict[str, Any] | None) -> float:
    """설정 사본의 문서층 배점(scoring.docLayerMax) — 없으면 기본 70 (spec 4.12)."""
    value = ((snapshot or {}).get("scoring") or {}).get("docLayerMax")
    return float(value) if value else DOC_LAYER_MAX


def _doc_candidates(results: list[SectionResult] | None, doc_display: float, threshold: float) -> list[ReworkOrder]:
    """계획서 묶음 재작성 지시 (spec 4.12) — 묶음 · 항목은 짝짓기 표(rework_map)로 가른다.

    1. 묶음마다 그 묶음 항목 중 fail · warning이고 입력 없음이 아닌 항목이 있으면 후보 — Task는 그 묶음 첫 항목 종류의 Task,
       사유 · 보완 지시는 '<항목 번호> <issues · warnings>' 줄을 이은 것.
    2. 문서층 표시 점수가 기준 미만인데 1의 후보가 없으면 묶음 모두가 후보(판정 지시가 없는 묶음의 고정 문구).
    3. 기회를 다 쓴 묶음도 그대로 넣는다(웹이 고를 수 없게 표시하고 Orchestrator도 거절한다).
    판정(results)이 없으면(None) 1의 후보는 없는 것으로 본다."""
    results = list(results or [])
    first_kind: dict[str, str] = {}
    flagged: dict[str, list[SectionResult]] = {}
    for r in results:
        bundle = section_bundle(r.section_code)
        if bundle is None:
            continue
        first_kind.setdefault(bundle, r.content_type)
        if r.status in ("fail", "warning") and not r.input_missing:
            flagged.setdefault(bundle, []).append(r)

    def order(bundle: str, reason: str) -> ReworkOrder:
        task_id = KIND_TASK.get(first_kind.get(bundle, "section"), "T-W1")
        return ReworkOrder(task_id=task_id, unit="묶음", targets=[bundle], reason=reason, instruction_delta=reason,
                           layer="document")
    orders = []
    for bundle in document_bundles():
        if bundle in flagged:
            lines = [f"{r.section_code} {' · '.join([*r.issues, *r.warnings]) or r.status}" for r in flagged[bundle]]
            orders.append(order(bundle, "\n".join(lines)))
    if not orders and doc_display < threshold:
        orders = [order(bundle, REWORK_DEFAULT_REASON) for bundle in document_bundles()]
    return orders


def _input_notices(results: list[SectionResult] | None) -> list[str]:
    """입력 없음 항목이 하나라도 있으면 '입력 확인 필요' 안내 (spec 4.12)."""
    return [INPUT_MISSING_NOTICE] if any(r.input_missing for r in results or []) else []


def _code_check(sc: StubScenario, kind: str, code_total: float) -> CodeCheckResult:
    """결손 점수를 칸에 나눠 불통과로 표시한다. HTML 2번 불통과면 결함 출처를 채운다(시나리오 alt_defect_sources).
    통과 필수 조건 실패(시나리오 gate_failures)면 칸 검사를 생략한 것으로 보고 모두 불통과 · 합계 0이다."""
    weights, names = (HTML_WEIGHTS, HTML_NAMES) if kind == "html" else (SVG_WEIGHTS, SVG_NAMES)
    if sc.gate_failures:
        detail = f"통과 필수 조건 실패로 검사 생략: {', '.join(sc.gate_failures)}"
        checks = [CodeCheck(no=i + 1, name=names[i], weight=weights[i], passed=False, detail=detail) for i in range(8)]
        return CodeCheckResult(total=0, checks=checks, gate_failures=list(sc.gate_failures))
    deficit, failed = 15 - code_total, set()
    for no in (4, 5, 3, 6, 8, 2, 7):
        w = weights[no - 1]
        if deficit >= w:
            failed.add(no)
            deficit -= w
    checks = [CodeCheck(no=i + 1, name=names[i], weight=weights[i], passed=(i + 1) not in failed, detail="",
                        defect_sources=list(sc.alt_defect_sources) if kind == "html" and i == 1 and 2 in failed else [])
              for i in range(8)]
    return CodeCheckResult(total=code_total, checks=checks)


def _feature_match(sc: StubScenario, features: list[str], knob: float, judged: str) -> FeatureMatchResult:
    """스텁 대조 — 1.4판 모양 (충족 1 · 부분 0.5 · 미충족 0).

    - 기능 수 m, 손잡이(0 ~ 15)로 인정 몫 u = round(손잡이 ÷ 15 × m × 2) ÷ 2. 앞에서부터 충족 floor(u)개, .5면 부분 1개,
      나머지 미충족.
    - 시나리오 partial_features가 있으면 그 기능을 부분으로 두고, 나머지를 앞에서부터 충족 floor(u − 0.5 × 부분 수)개 ·
      나머지 미충족으로 다시 맞춘다.
    - 점수 = 15 × (충족 + 0.5 × 부분) ÷ m. 기능이 없거나 시나리오 withhold_feature_match면 보류(E-V2-NOFEATURE) · 0점.
    findings 첫 줄은 '인정 n/m개 (규칙 a건 → LLM 확인: 충족 x · 부분 y · 미충족 z)' — 스텁은 규칙 탈락이 없어 a = m.
    """
    m = len(features)
    if m == 0 or sc.withhold_feature_match:
        return FeatureMatchResult(score=0, missing_features=[], extra_features=[],
                                  findings=["대조 판정 보류 (E-V2-NOFEATURE)"], judged_by=judged,
                                  withheld=True, withheld_reason="E-V2-NOFEATURE")
    u = round(knob / 15 * m * 2) / 2
    if sc.partial_features is not None:
        partial = [f for f in features if f in sc.partial_features]
        rest = [f for f in features if f not in partial]
        n_full = max(0, min(len(rest), math.floor(u - 0.5 * len(partial))))
        full, missing = rest[:n_full], rest[n_full:]
    else:
        n_full = math.floor(u)
        full = features[:n_full]
        partial = features[n_full:n_full + 1] if u - n_full == 0.5 else []
        missing = features[n_full + len(partial):]
    recognized = len(full) + 0.5 * len(partial)
    findings = [f"인정 {recognized:g}/{m}개 (규칙 {m}건 → LLM 확인: 충족 {len(full)} · 부분 {len(partial)} · "
                f"미충족 {len(missing)})"]
    findings += [f"'{f}' 기능이 프로토타입에 존재하지 않습니다." for f in missing]
    findings += [f"{f}: 부분 인정 — 일부 요소가 빠졌습니다." for f in partial]
    return FeatureMatchResult(score=15 * recognized / m, missing_features=missing, partial_features=partial,
                              extra_features=[], findings=findings, judged_by=judged)


# ── 스텁 묶기 ─────────────────────────────────────────
def bind_stubs(registry: TaskRegistry, sc: StubScenario, *, now: Callable[[], datetime] = utc_now) -> None:
    now = utc_clock(now)                 # 시간대 있는 UTC (시간대 없는 시계는 UTC로 본다)
    today = lambda: kst_today(now())  # noqa: E731 — 스텁의 '오늘'은 한국 날짜

    def r8(inp: c.R8In) -> c.R8Out:
        return c.R8Out(reference_docs=[ReferenceDoc(doc_id=f"doc-{i}", file_name=f.file_name, format=f.format,
                                                    extracted_text="추출 텍스트", extract_status="성공",
                                                    original_discarded_at=now())
                                       for i, f in enumerate(inp.attachments)])

    def tc1(inp: c.TC1In, tools: Tools) -> c.TC1Out:
        _ask(tools, "카테고리 판정")
        f = inp.form_input
        item = ItemSpec(item_name=f.idea_text[:20], one_line_summary=f.idea_text, target_customer="소상공인",
                        core_features=["회원 등록·조회", "수업 예약"], category=sc.category, keywords=["헬스장"])
        # companyInfo는 폼 값을 코드로 그대로 옮긴다 (LLM에 맡기지 않음)
        company = CompanyInfo(**{k: getattr(f, k) for k in CompanyInfo.model_fields if hasattr(f, k)})
        return c.TC1Out(item_spec=item, category=sc.category, company_info=company,
                        category_reason="화면 중심 서비스", confidence=0.8)

    def tc2(inp: c.TC2In, tools: Tools) -> c.TC2Out:
        more = inp.offset > 0
        _maybe_raise(sc, "T-C2")
        if more and sc.more_error == "코드오류":
            raise RuntimeError("T-C2 추가 조회 스텁 오류")
        status = sc.more_collection_status if more and sc.more_collection_status else sc.collection_status
        tools.search("수집 상태", lambda timeout: status)
        if status != "정상":   # 수집 상태가 정상이 아니면 매칭하지 않는다 — 후보 0건 (spec 4.1.1)
            return c.TC2Out(candidates=[], collection_status=status, filtered_count=0, fallback_used=False)
        mode = None
        try:
            tools.search("임베딩 검색", lambda timeout: _search_or_fail(sc.embed_fail))
        except ToolCallExhausted:
            mode = "BM25단독"  # 임베딩 검색 오류 → BM25 단독 순위 (5-3)
        down = "T-C2" in sc.exhaust_in or (more and sc.more_error == "재시도소진")
        tools.search("BM25 검색", lambda timeout: _search_or_fail(down))
        if sc.deadline_fallback:
            mode = "마감임박순"   # 적합도 0 — 실제 점수가 아니다 (spec 4.1.3)
        if more and sc.more_ids is not None:
            ids = list(sc.more_ids)
        else:
            n = sc.candidate_count if not more else min(10, sc.candidate_count)
            ids = [f"A{inp.offset + i + 1:02d}" for i in range(n)]
        cards = [_card(sc, aid, inp.offset + i + 1, inp.today, more=more, fit_zero=mode == "마감임박순")
                 for i, aid in enumerate(ids)]
        return c.TC2Out(candidates=cards, collection_status=status, filtered_count=len(cards),
                        fallback_used=mode is not None, fallback_mode=mode)

    def g01(inp: c.G01In, tools: Tools) -> c.G01Out:
        """스텁 G-01 — 공고 서버 대신 스텁 공고를 만들고 판정한다(spec 4.6). 호출은 실제 구현처럼 상세 · 판정 둘이다."""
        _maybe_raise(sc, "G-01")
        aid = inp.announcement_id
        down = "G-01" in sc.exhaust_in

        def detail(timeout: float) -> Announcement | None:
            _search_or_fail(down)
            return None if aid in sc.not_found_ids else stub_announcement(sc, aid, inp.today)   # 공고 없음은 값으로
        ann = tools.search("공고 상세", detail)
        if ann is None:
            raise ResourceNotFound("공고 없음 — 공고 상세")
        company = inp.company_info
        if company.applicant_type != PRE_STARTUP and company.founded_at is None:
            gate, age = stub_gate(company, ann, inp.today)   # 설립일 없는 사업자 — 판정을 부르지 않는다 (spec 4.3.2 ②)
        else:
            gate, age = tools.search("자격 판정", lambda timeout: stub_gate(company, ann, inp.today))
        return c.G01Out(gate_result=gate, business_age_years=age, selected_announcement=ann)

    def tc3(inp: c.TC3In, tools: Tools) -> c.TC3Out:
        """스텁 T-C3 (spec 6.2) — 확인 · 양식 고르기 · Task 목록 · 틀 · 맥락 · 확장 출력은 실제 T-C3와 같은 부품으로 만들고,
        안내만 LLM 대신 고정 더미 문장이다. 확인(① · ② · ④)은 LLM을 부르기 전에 한다."""
        bundle = task_plan.prepare(inp)
        _ask(tools, "작업 분해")
        guidance = {t: STUB_GUIDANCE.format(task_id=t) for t in task_plan.instructed_tasks(inp.item_spec.category)}
        return task_plan.assemble(inp, bundle, guidance)

    def ts1(inp: c.TS1In, tools: Tools) -> c.TS1Out:
        _ask(tools, "요구사항 분석")
        feats = list(inp.item_spec.core_features)
        ra = RequirementAnalysis(problem_statement="문제", target_customer="고객", feature_list=feats,
                                 differentiator="차별점", use_cases=["사례"])
        document_type = "pre_startup" if inp.company_info.applicant_type == PRE_STARTUP else "early_startup"
        strategy = {k: {} for k in STRATEGY_KEYS}
        strategy.update(strategy_limits={"featureList": list(inp.item_spec.core_features)}, document_type=document_type)
        return c.TS1Out(requirement_analysis=ra, feature_list=feats, strategy_data=strategy,
                        check=_check(sc, "T-S1", inp.rework_input, "itemSpec.coreFeatures 승계"))

    def ts2(inp: c.TS2In, tools: Tools) -> c.TS2Out:
        _ask(tools, "시장 분석")
        ma = MarketAnalysis(market_definition="시장", competitors=["경쟁사"], positioning="포지션",
                            market_size=[MarketSizeItem(label="국내 시장", value=1200, unit="억원",
                                                        source_name="통계청", basis="추정")])
        return c.TS2Out(market_analysis=ma, numeric_tokens=[Token(type="수치금액", value="1200억원", count=1)],
                        market_strategy_data={k: {} for k in MARKET_KEYS},
                        check=_check(sc, "T-S2", inp.rework_input, "출처 없는 수치 제거"))

    def tw1(inp: c.TW1In, tools: Tools) -> c.TW1Out:
        """양식의 모든 항목을 양식 순서로 담는다. 본문 항목만 문장을 쓰고(호출 하나씩 — 목적 '섹션 <항목> 작성'), 표 · 그림
        항목은 문장 0개다(표 서술은 T-W3가 만들고 M-1이 바꾼다). 목표 항목(reworkInput.targetItems)이 있으면 그 항목만 다시
        쓰고 나머지는 직전 계획서 · 항목 결과(base…)를 그대로 싣는다 (spec 4.7)."""
        feats = list(inp.requirement_analysis.feature_list)
        if sc.tw1_change_features:
            feats = feats + ["임의 기능"]
        targets = _targets(inp.rework_input)
        base = {s.section_code: s for s in inp.base_plan_doc.sections} if inp.base_plan_doc else {}
        base_out = dict(inp.base_section_outputs or {})
        sections, outputs = [], {}
        for code, title, tag, kind in _form_items(inp.form_spec):
            if targets is not None and code not in targets and code in base:
                sections.append(base[code])
                if code in base_out:
                    outputs[code] = base_out[code]
                continue
            sentences: list[Sentence] = []
            if kind == "section":
                _ask(tools, f"섹션 {code} 작성")
                sentences = _stub_sentences(code, title)
                outputs[code] = {"generatedText": "\n".join(s.text for s in sentences), "facts": [], "sourceRefs": [],
                                 "needsUserConfirmation": [], "issues": []}
            sections.append(PlanSection(section_code=code, title=title, sentences=sentences, tag=tag,
                                        content_type=kind))
        plan = PlanDoc(sections=sections, feature_list=feats, charts=[], tables=[], protected_tokens=[])
        return c.TW1Out(plan_doc=plan, sections=sections, feature_list=feats, section_outputs=outputs,
                        check=_check(sc, "T-W1", inp.rework_input, "입력에 없는 경력 서술 삭제"))

    def tw2(inp: c.TW2In, tools: Tools) -> c.TW2Out:
        """그림 항목(계획서의 contentType image)마다 두 그림을 SVG 파일로 넣는다(항목마다 호출 하나 — 목적 '그림 <항목> 작성').
        그림 항목이 없으면 빈 목록이다(호출은 '그래프' 하나). 목표 항목이 있으면 그 항목만 다시 그리고 나머지는 직전 그림 ·
        항목 결과(base…)를 그대로 싣는다 (spec 4.7)."""
        chart = ChartSpec(chart_id="chart-1", type="bar", title="시장 규모", axis_labels=["연도", "억원"],
                          series=[{"x": 2026, "y": 1200}], source_ref="1-1")
        targets = _targets(inp.rework_input)
        base_diagrams = list(inp.base_diagrams or [])
        base_out = dict(inp.base_diagram_outputs or {})
        diagrams, outputs, asked = [], {}, False
        for sec in inp.plan_doc.sections:
            if sec.content_type != "image":
                continue
            code = sec.section_code
            if targets is not None and code not in targets and code in base_out:
                diagrams += [d for d in base_diagrams if d.source_ref == code]
                outputs[code] = base_out[code]
                continue
            _ask(tools, f"그림 {code} 작성")
            asked = True
            specs = []
            for flow_type, name in STUB_DIAGRAMS:
                ref = tools.files.put(name, STUB_DIAGRAM_SVG, SVG_TYPE)
                nodes = ["사용자", "서비스", "결과"]
                diagrams.append(DiagramSpec(diagram_id=f"{sec.section_code}-{flow_type}", flow_type=flow_type,
                                            nodes=nodes, visual_style={}, source_ref=sec.section_code, image_file=ref))
                specs.append({"flowType": flow_type, "nodes": nodes, "visualStyle": {}})
            outputs[sec.section_code] = {"imageSpecs": specs, "imageTypes": [f for f, _ in STUB_DIAGRAMS],
                                         "nodes": specs[0]["nodes"], "flowType": STUB_DIAGRAMS[0][0],
                                         "visualStyle": {}, "generatedText": "", "facts": [], "sourceRefs": [],
                                         "issues": []}
        if not asked and targets is None:
            _ask(tools, "그래프")   # 그림 항목이 없는 양식 — LLM Task 스텁은 호출 경로를 한 번 거친다
        return c.TW2Out(charts=[chart], diagrams=diagrams, diagram_outputs=outputs,
                        check=_check(sc, "T-W2", inp.rework_input, "차트 폐기 · 참조 문구 제거"))

    def tw3(inp: c.TW3In, tools: Tools) -> c.TW3Out:
        """규칙 코드 Task — LLM을 부르지 않는다(uses_llm=False). 표 항목마다 표(tables, sourceRef = 항목 번호) · 서술 문장
        (tableSections) · 결과(tableOutputs)를 낸다.

        - 목표 항목이 있으면 그 표만 다시 만들고 나머지는 직전 표 · 서술 · 결과(base…)를 그대로 싣는다 (spec 4.7).
        - 표 대체(fallbackItems — 검증-1 재수행 뒤에도 fail인 표, spec 4.10): 그 표를 tables에서 빼고 서술을 대체 본문으로
          바꾸며 tableOutputs에 tableFallbackUsed · fallbackReason(그 항목 문제를 ' · '로 이은 것)을 남긴다.
        - 자체 검사 불통과면 재수행 없이 그 시도에서 바로 확정 동작(걸린 표 → 본문 서술 대체, spec 4.8)."""
        ri = inp.rework_input
        targets = _targets(ri)
        check = _check(sc, "T-W3", ri, "표 제거 · 본문 서술 대체", immediate=True)
        fallback = dict.fromkeys(ri.fallback_items if ri is not None else [])
        if not check.passed and check.final_action:
            fallback.update(dict.fromkeys(check.failed_items))
        reasons = {**check.failed_items, **(ri.target_items if ri is not None else {})}
        base_sections = {s.section_code: s for s in inp.base_table_sections or []}
        base_out = dict(inp.base_table_outputs or {})
        base_tables = {t.source_ref: t for t in inp.base_tables or []}
        tables, sections, outputs = [], [], {}
        for code, title, tag, kind in _form_items(inp.form_spec):
            if kind != "table":
                continue
            if code in fallback:
                sentences = [Sentence(sentence_id=f"s-{code}-1", text=f"{title} 표 대신 본문 서술 (대체)",
                                      is_title=False, paragraph_no=1)]
                sections.append(PlanSection(section_code=code, title=title, sentences=sentences, tag=tag,
                                            content_type="table"))
                outputs[code] = {"generatedText": sentences[0].text, "tables": [], "issues": [],
                                 "tableFallbackUsed": True, "fallbackReason": " · ".join(reasons.get(code, []))}
                continue
            if targets is not None and code not in targets and code in base_sections:
                sections.append(base_sections[code])
                if code in base_out:
                    outputs[code] = base_out[code]
                if code in base_tables:
                    tables.append(base_tables[code])
                continue
            sentences = _stub_sentences(code, title)
            tables.append(TableSpec(table_id=f"table-{code}", title=title[:20], headers=["항목", "금액"],
                                    rows=[["개발", "5천만원"]], source_ref=code))
            sections.append(PlanSection(section_code=code, title=title, sentences=sentences, tag=tag,
                                        content_type="table"))
            outputs[code] = {"generatedText": "\n".join(s.text for s in sentences),
                             "tables": [{"columns": ["항목", "금액"], "rows": [{"항목": "개발", "금액": "5천만원"}],
                                         "rules": {}}],
                             "issues": [], "tableFallbackUsed": False, "fallbackReason": ""}
        return c.TW3Out(tables=tables, table_sections=sections, table_outputs=outputs, check=check)

    def m1(inp: c.M1In) -> c.M1Out:
        """차트 · 표를 싣고, 표 항목 문장은 tableSections의 같은 항목으로 바꾸며, 그림 목록은 통째로 바꾼다 (spec 4.7)."""
        _maybe_raise(sc, "M-1")
        by_code = {s.section_code: s for s in inp.table_sections}
        sections = [by_code.get(s.section_code, s) for s in inp.plan_doc.sections]
        return c.M1Out(plan_doc=inp.plan_doc.model_copy(update={
            "charts": inp.charts, "tables": inp.tables, "sections": sections, "diagrams": list(inp.diagrams)}))

    def tv1(inp: c.TV1In, tools: Tools) -> c.TV1Out:
        """문서층 점수와 항목별 판정 (spec 4.9 모양).

        - 평가항목 = 계획서 항목: 총점(시나리오 doc_scores 차례)을 항목 배점(평가항목 maxScore — 없으면 70 ÷ 항목 수)으로
          나눈다(_doc_score). 항목 판정 점수 = 항목 점수 ÷ 배점 × 100.
        - 판정은 시나리오대로: 입력 없음(input_missing_items) → warning · inputMissing, fail(fail_items · fail_item_times)
          → fail, warning_items → warning, 나머지 pass. verifiedRef = 입력 plan_doc_ref(없으면 'planDoc').
        - 목표 항목(reworkInput.targetItems)이 있으면 그 항목만 판정하고 나머지는 직전 판정(baseSectionResults)을 그대로 잇는다."""
        _ask(tools, "문서층 채점")
        items = _form_items(inp.form_spec)
        evals = {e.item_code: e.max_score for e in inp.evaluation_items}
        maxes = [(code, evals.get(code, DOC_LAYER_MAX / max(len(items), 1))) for code, _, _, _ in items]
        ds = _doc_score(sc.pick("T-V1", sc.doc_scores), maxes)
        scored = {it.item_code: (it.score / it.max_score * 100 if it.max_score else 0.0) for it in ds.items}
        targets = _targets(inp.rework_input)
        base = {r.section_code: r for r in inp.base_section_results or []}
        ref = inp.plan_doc_ref or "planDoc"

        def judge(code: str, tag: str | None, kind: str) -> SectionResult:
            score = round(scored.get(code, 0.0), 2)
            common = dict(section_code=code, tag=tag, content_type=kind, score=score, verified_ref=ref)
            if code in sc.input_missing_items:
                return SectionResult(status="warning", warnings=[STUB_INPUT_MISSING_WARNING], input_missing=True,
                                     **common)
            times = sc.fail_item_times.get(code, 0)
            if code in sc.fail_items or (times and sc.tick(f"judge:{code}") < times):
                return SectionResult(status="fail", issues=[f"{code} 결함 (스텁)"], deductions=["결함"], **common)
            if code in sc.warning_items:
                return SectionResult(status="warning", warnings=[f"{code} 보완 권장 (스텁)"], **common)
            return SectionResult(status="pass", **common)
        results = [base[code] if targets is not None and code not in targets and code in base else judge(code, tag, kind)
                   for code, _, tag, kind in items]
        return c.TV1Out(doc_score=ds, items=ds.items, variance_flag=False, section_results=results,
                        score_policy_version=inp.rubric.version or STUB_SCORE_POLICY)

    def g02a(inp: c.G02aIn) -> c.G02aOut:
        """문서 평가 판정 — 표시 점수(문서층 → 100점 환산, 배점은 설정 사본 scoring.docLayerMax)로 다음 동작을 정하고,
        계획서 묶음 후보는 항목 판정(sectionResults)으로 낸다 (spec 4.12)."""
        _maybe_raise(sc, "G-02a")
        display = round(inp.doc_score.total / _doc_layer_max(inp.settings_snapshot) * 100, 1)
        orders = _doc_candidates(inp.section_results, display, inp.threshold)
        na = _next_action(display >= inp.threshold, orders, inp.rework_usage)
        report = ScoreReport(
            doc_score=inp.doc_score, artifact_score=None, total=inp.doc_score.total, threshold=inp.threshold,
            passed=display >= inp.threshold, failed_task_ids=sorted({o.task_id for o in orders}),
            rework_orders=orders, rework_usage=inp.rework_usage, phase="document", display_score=display,
            carried_over_layer=None, rework_diff=[],
            comparisons=inp.cycle_info.comparisons if inp.cycle_info else [],
            notices=[ch.final_action for ch in (inp.checks or []) if ch.final_action]
            + _input_notices(inp.section_results),
            settings_snapshot=inp.settings_snapshot, rubric_version=inp.rubric_version)
        return c.G02aOut(score_report=report, failed_task_ids=report.failed_task_ids, rework_orders=orders,
                         next_action=na)

    def tb1(inp: c.TB1In, tools: Tools) -> c.TB1Out:
        _ask(tools, "실행 파일 제작")
        entry = tools.files.put(ENTRY_FILE, STUB_HTML, HTML_TYPE)
        proto = Prototype(entry_file=entry, kind="html", asset_files=[], implemented_features=list(inp.feature_list))
        return c.TB1Out(prototype=proto, implemented_features=list(inp.feature_list),
                        entry_file=entry, check=_check(sc, "T-B1", inp.rework_input, ""))

    def tb2(inp: c.TB2In, tools: Tools) -> c.TB2Out:
        _ask(tools, "인포그래픽 제작")
        if inp.category == "원페이지":   # 원페이지 지면 — M-2가 이 참조를 프로토타입 진입 파일로 감싼다
            fmt, image = "svg", tools.files.put(ONEPAGE_FILE, STUB_SVG, SVG_TYPE)
        else:
            fmt, image = "png", tools.files.put(INFOGRAPHIC_FILE, FakeImage.PNG, PNG_TYPE)
        return c.TB2Out(infographic=Infographic(image_file=image, format=fmt, alt_text="인포그래픽"),
                        check=_check(sc, "T-B2", inp.rework_input, ""))

    def m2(inp: c.M2In) -> c.M2Out:
        # 파일을 열지 않고 인포그래픽 그림 참조를 그대로 진입 파일로 감싼다 (같은 실행 건의 참조)
        return c.M2Out(prototype=Prototype(entry_file=inp.infographic.image_file, kind="svg-onepage",
                                           asset_files=[], implemented_features=list(inp.feature_list)))

    def g04(inp: c.G04In, files: FileTool) -> c.G04Out:
        # 자체 검사는 check_fail_times['G-04']로 불통과를 흉내 낸다. 실구현(템플릿 · 낱말 검사)이 지킬 것 — 웹개발 · AI API
        # README에는 '실행' 또는 '열람', 원페이지 README에는 '열람'과 '인쇄'가 들어가야 한다(구현 · 검증-2 담당 요청, 검증-2
        # 진단 기준과 같음). 끝내 실패해 AI 생성 고지(기획서 6-8)가 빠져도 T-C4 전달은 막지 않는다 (잠정 — 사용자 미답)
        # 파일을 쓰는 규칙 단계 — 엔진이 파일 창구를 두 번째 인자로 넘긴다
        _maybe_raise(sc, "G-04")
        readme = files.put(README_FILE, STUB_README, MARKDOWN_TYPE)
        return c.G04Out(readme_file=readme, check=_check(sc, "G-04", None, ""))

    def m3(inp: c.M3In) -> c.M3Out:
        _maybe_raise(sc, "M-3")
        return c.M3Out(prototype=inp.prototype.model_copy(update={"readme_file": inp.readme_file}))

    def tv2(inp: c.TV2In, tools: Tools) -> c.TV2Out:
        try:
            _ask(tools, "대조 보조")
            judged = "htmlParse" if inp.prototype.kind == "html" else "svgTextParse"
        except ToolCallExhausted:
            judged = "htmlParse" if inp.prototype.kind == "html" else "svgTextParse"  # 문자열 대조만으로 산출
        code_total, feat = sc.pick("T-V2", sc.art_scores)
        fm = _feature_match(sc, list(inp.feature_list), feat, judged)
        cc = _code_check(sc, inp.prototype.kind, code_total)
        total = 0.0 if cc.gate_failures else cc.total + fm.score   # 통과 필수 조건 실패면 산출물층 0
        return c.TV2Out(artifact_score=ArtifactScore(total=total, code_check=cc, feature_match=fm),
                        code_check=cc, feature_match=fm, diagnostics=list(sc.diagnostics))

    def g02b(inp: c.G02bIn) -> c.G02bOut:
        """종합 평가 판정 — 다음 동작은 두 층 합산 점수, 계획서 묶음 후보는 G-02a와 같은 규칙(문서층 표시 점수 기준),
        산출물 묶음 후보는 지금 규칙 그대로 (spec 4.12)."""
        dmax = _doc_layer_max(inp.settings_snapshot)
        total = round(inp.doc_score.total + inp.artifact_score.total, 1)
        doc_display = round(inp.doc_score.total / dmax * 100, 1)
        orders = (_doc_candidates(inp.section_results, doc_display, inp.threshold)
                  + _art_orders(inp.artifact_score, sc.category))
        na = _next_action(total >= inp.threshold, orders, inp.rework_usage)
        ci = inp.cycle_info
        diff: list[ReworkDiff] = []
        if ci is not None:
            if ci.previous_doc_score is not None:
                diff.append(ReworkDiff(task_id="T-W1", layer="document", label="문서층",
                                       before_summary=f"{ci.previous_doc_score.total}/{dmax:g}",
                                       after_summary=f"{inp.doc_score.total}/{dmax:g}"))
            if ci.previous_artifact_score is not None:
                diff.append(ReworkDiff(task_id="T-V2", layer="artifact", label="산출물층",
                                       before_summary=f"{ci.previous_artifact_score.total}/30",
                                       after_summary=f"{inp.artifact_score.total}/30"))
        report = ScoreReport(
            doc_score=inp.doc_score, artifact_score=inp.artifact_score, total=total, threshold=inp.threshold,
            passed=total >= inp.threshold, failed_task_ids=sorted({o.task_id for o in orders}),
            rework_orders=orders, rework_usage=inp.rework_usage, phase="overall", display_score=total,
            carried_over_layer=ci.carried_over_layer if ci else None, rework_diff=diff,
            comparisons=ci.comparisons if ci else [], notices=_input_notices(inp.section_results),
            settings_snapshot=inp.settings_snapshot, rubric_version=inp.rubric_version)
        return c.G02bOut(score_report=report, failed_task_ids=report.failed_task_ids, rework_orders=orders,
                         next_action=na, rework_diff=diff)

    def g03(inp: c.G03In) -> c.G03Out:
        if sc.no_tokens:
            return c.G03Out(protected_tokens=[])
        a = inp.announcement
        # 공고의 금액 표기 · 마감일이 비어 있으면 그 보호 토큰은 만들지 않는다 (spec 5)
        tokens = ([Token(type="수치금액", value=a.support_amount_text, count=1)] if a.support_amount_text else [])
        tokens += [Token(type="날짜", value=a.apply_end.isoformat(), count=1)] if a.apply_end else []
        tokens += [Token(type="고유명사", value=a.title, count=1),
                   Token(type="고유명사", value=inp.company_info.representative_name, count=1)]
        tokens += [Token(type="기능명", value=f, count=1) for f in inp.feature_list] + list(inp.numeric_tokens)
        return c.G03Out(protected_tokens=tokens)

    def tp1(inp: c.TP1In, tools: Tools) -> c.TP1Out:
        _ask(tools, "형식 검수")
        ids = [s.sentence_id for sec in inp.plan_doc.sections for s in sec.sentences][: sc.tp1_targets]
        return c.TP1Out(format_findings=[FormatFinding(sentence_id=i, violation_type="종결형", detail="단정형으로")
                                         for i in ids], target_sentence_ids=ids)

    def tp2(inp: c.TP2In, tools: Tools) -> c.TP2Out:
        tools.llm([{"role": "user", "content": inp.sentence.text}], schema=Ack, purpose=f"윤문 재수행 {inp.redo_count}")
        plan = sc.tp2_behavior.get(inp.sentence.sentence_id, ["ok"])
        behavior = plan[min(inp.redo_count, len(plan) - 1)]
        if behavior == "ok":
            revised = inp.sentence.model_copy(update={"text": inp.sentence.text + " (윤문)"})
            return c.TP2Out(revised=revised, adopted=True, final_redo_count=inp.redo_count,
                            token_check=TokenCheckResult(passed=True, missing_tokens=[], altered_tokens=[],
                                                         contaminated_tokens=[]))
        text = "동일 출력" if behavior == "same" else f"변형 {inp.redo_count}"
        return c.TP2Out(revised=inp.sentence.model_copy(update={"text": text}), adopted=False,
                        final_redo_count=inp.redo_count,
                        token_check=TokenCheckResult(passed=False, missing_tokens=["1억원"], altered_tokens=[],
                                                     contaminated_tokens=[]),
                        next_redo_hint=["'1억원' 유지"])

    def m4(inp: c.M4In) -> c.M4Out:
        by_id = {r.sentence_id: r for r in inp.sentence_results}
        sections = [sec.model_copy(update={"sentences": [
            by_id[s.sentence_id].revised if s.sentence_id in by_id and by_id[s.sentence_id].adopted else s
            for s in sec.sentences]}) for sec in inp.plan_doc.sections]
        n = len(inp.target_sentence_ids)
        first_pass = sum(1 for r in inp.sentence_results if r.adopted and r.final_redo_count == 0)
        log = ProofreadLog(
            total_sentences=n, adopted_count=sum(1 for r in inp.sentence_results if r.adopted),
            retained_by_check_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "검증실패"],
            retained_by_call_failure_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "호출실패"],
            early_stopped_sentence_ids=[r.sentence_id for r in inp.sentence_results if r.kept_reason == "조기중단"],
            token_preservation_rate=(first_pass / n) if n else 1.0, model_version=inp.model_version)
        return c.M4Out(plan_doc=inp.plan_doc.model_copy(update={"sections": sections}), proofread_log=log)

    def tc4(inp: c.TC4In, tools: Tools) -> c.TC4Out:
        # 계획서 파일은 자리채움(형식만 워드). 프로토타입은 참조 목록 — 진입 파일(있으면) · 안내 문서(있으면) · 자산.
        # 내려받기용 압축은 웹이 만든다
        plan_file = tools.files.put(PLAN_DOC_FILE, STUB_PLAN_DOC, DOCX_TYPE)
        proto = inp.prototype
        proto_files = [f for f in (proto.entry_file, proto.readme_file) if f is not None] + list(proto.asset_files)
        d = Deliverable(plan_doc_file=plan_file, prototype_files=proto_files,
                        infographic_file=inp.infographic.image_file, score_report=inp.score_report,
                        proofread_log=inp.proofread_log, disclaimer=DISCLAIMER, prototype_notice=PROTOTYPE_NOTICE,
                        score_notice=SCORE_NOTICE, submission_notice=SUBMISSION_NOTICE)
        return c.TC4Out(deliverable=d, user_message="계획서 · 프로토타입 · 검증 결과를 내려받을 수 있습니다.")

    for tid, fn in {
        "R-8": r8, "T-C1": tc1, "T-C2": tc2, "G-01": g01, "T-C3": tc3, "T-S1": ts1, "T-S2": ts2,
        "T-W1": tw1, "T-W2": tw2, "T-W3": tw3, "M-1": m1, "T-V1": tv1, "G-02a": g02a, "T-B1": tb1,
        "T-B2": tb2, "M-2": m2, "G-04": g04, "M-3": m3, "T-V2": tv2, "G-02b": g02b, "G-03": g03,
        "T-P1": tp1, "T-P2": tp2, "M-4": m4, "T-C4": tc4,
    }.items():
        registry.bind(tid, fn)


def _search_or_fail(fail: bool) -> list:
    if fail:
        raise ProviderError("stub down", status=503)
    return []


def _card(sc: StubScenario, aid: str, rank: int, today: date, *, more: bool, fit_zero: bool) -> AnnouncementCard:
    """스텁 카드 — 내용은 공고 ID로 정한다(같은 공고는 첫 조회 · 추가 조회에서 같은 내용). 추가 조회에서만
    more_changes의 종류대로 바꾼다: 정보(제목) · 버전(contentVersion만) · 적합도(적합도 · 추천 이유만) · 가산점(가산점만).
    contentChanged는 늘 거짓 — "내용 바뀜"은 흐름(Orchestrator)이 정한다."""
    changes = set(sc.more_changes.get(aid, ())) if more else set()
    if changes - set(MORE_CHANGE_KINDS):
        raise ValueError(f"more_changes 종류는 {MORE_CHANGE_KINDS} 중에서: {sorted(changes - set(MORE_CHANGE_KINDS))}")
    no_deadline = aid in sc.no_deadline_ids
    if not settings.BONUS_ENABLED or aid in sc.null_bonus_ids:   # 가산점 스위치 꺼짐(기본, 잠정)이면 만들지 않는다
        bonus = None
    else:
        bonus = STUB_BONUS_CHANGED if "가산점" in changes else STUB_BONUS
    return AnnouncementCard(
        announcement_id=aid, title=f"공고 {aid}" + (" (수정)" if "정보" in changes else ""), agency="기관",
        apply_end=None if no_deadline else today + timedelta(days=30),
        support_amount_max=None if aid in sc.no_amount_ids else 100_000_000,
        fit_score=0.0 if fit_zero else (0.5 if "적합도" in changes else 0.9),
        rank=rank, display_type="card" if rank <= 3 else "list",
        match_reason="유사 (갱신)" if "적합도" in changes else "유사",
        source_notice="본 AI 요약 정보는 K-Startup 공고 내용을 바탕으로 생성되었습니다.",
        original_url="https://example.invalid",
        apply_period_type=PERIOD_OPEN if no_deadline else PERIOD_FIXED, content_changed=False,
        content_version=None if aid in sc.no_version_ids else f"{aid}-v{2 if '버전' in changes else 1}",
        bonus_score=None if bonus is None else sum(b.points for b in bonus),
        bonus_items=[] if bonus is None else [b.model_copy() for b in bonus])


def _art_orders(score: ArtifactScore, category: str) -> list[ReworkOrder]:
    """산출물층 재작성 지시 — 다시 돌릴 Task · 사유는 공용 규칙(artifact_rework_reasons)을 쓴다. 보류된 대조는 이미 0점이라
    재정규화하지 않는다(2026-09-30 결정 8)."""
    kind = "svg-onepage" if category == "원페이지" else "html"
    return [ReworkOrder(task_id=task_id, unit="묶음", targets=[TASK_BUNDLE[task_id]], reason="; ".join(rs),
                        instruction_delta="; ".join(rs), layer="artifact")
            for task_id, rs in artifact_rework_reasons(score, kind).items()]


def _next_action(passed: bool, orders: list[ReworkOrder], usage) -> str:
    if passed:
        return "진행가능"
    remaining = {u.bundle_id: u.remaining for u in usage}
    names = [b for o in orders for b in order_bundles(o)]   # 기회를 세는 묶음 이름 (spec 3.2)
    if names and all(remaining.get(b, 1) <= 0 for b in names):
        return "상한도달"
    return "재작성권유"

