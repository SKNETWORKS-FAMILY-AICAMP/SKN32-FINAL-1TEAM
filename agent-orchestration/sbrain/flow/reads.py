"""조회 — 웹이 project_id로 부르는 화면 조회 · 지금까지 결과 · 재작성 결과와 관리자 조회 (확장).

화면 모양은 **초안**이다. 웹팀과 맞춰 고친다. 모델은 기준 문서 타입을 그대로 싣고, 내부 값(실행 설정 스냅샷 등)은 뺀다.

| 화면 | 열리는 때 | 내용 (산출물 키는 flow/catalog.py 출력 연결, 현재 버전) |
|---|---|---|
| 3 공고 후보 | 공고선택 · 사용자대기, 계획서작성 · 사용자대기(자격 통과 뒤 작성 시작 전, 3.3) | 후보는 sbrain_flow.candidate_lists(첫 조회 candidates@1, 유효한 추가 조회가 있으면 firstCandidates · moreCandidates), collectionStatus, filteredCount, fallbackUsed · fallbackMode, 막힌 공고 blockedAnnouncementIds(Run) |
| 4 자격 확인 | 공고선택 · 계획서작성 사용자대기, gateResult가 있을 때 | gateResult(확인 필요 unknownConditions면 notices에 E-G1-UNPARSED), businessAgeYears |
| 6 문서 평가 | 문서평가 · 사용자대기 | planDoc, scoreReport.document, G-02a.failedTaskIds · reworkOrders · nextAction |
| 8 산출물 확인 | 산출물확인 · 사용자대기 | prototype, infographic, codeCheck, featureMatch, G-02b.reworkOrders(산출물층) |
| 9 종합 평가 | 종합평가 · 사용자대기 | scoreReport.overall, G-02b.reworkOrders · nextAction, reworkDiff |
| 10 검수 전후 | 결과물 · 완료 | formatFindings, sentenceResults(문장별 전후 · 시도별 기록), proofreadLog |
| 11 결과물 | 결과물 · 완료 | deliverable, userMessage, planDoc, prototype, infographic |

- 재작성 목록은 묶음별 남은 기회를 함께 싣는다(묶음 요청 request_rework_for_project와 같은 묶음 이름으로 센다).
- 대기 지점이 아니거나 아직 없는 화면은 CommandError("SCREEN_NOT_READY"). 화면 3은 작성을 시작한 뒤에는
  INVALID_STATE다(공고 다시 고르기 · 추가 조회와 같은 거절, 3.3).
- 지금까지 결과(outputs) · 재작성 결과(rework_result)는 실패 · 중단 실행 건이면 CommandError("RUN_NOT_VIEWABLE").
  사용자용 결과에는 관리자용 실패 사유를 싣지 않는다 — 실패는 진행 상태와 안내(E-RUN-FAIL)로만 보인다.
- 관리자 조회는 메타데이터 · 점수 · 개수만 돌려준다. 산출물 · 입력 · 문장 내용을 싣지 않는다(기획서 4-7 · 6-7).
"""
from __future__ import annotations

import typing
from collections import Counter, defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from ..contracts.tasks import ProofreadAttempt, SentenceResult
from ..models import (
    Announcement, AnnouncementCard, BundleUsage, Deliverable, GateResult, Notice, PlanDoc, PlanSection, Prototype,
    ReworkDiff, ReworkOrder, Run,
)
from ..models.base import (
    AgentName, CollectionStatus, FallbackMode, KeptReason, KeptSide, NextAction, RunProgress, SBModel, ext,
)
from ..models.clock import UTC_MIN
from ..models.domain import EvalItem, FormatFinding, Infographic, ProofreadLog
from ..models.rework import ReworkComparison
from ..models.run import ReworkResultStatus
from ..models.scoring import ArtifactScore, CodeCheckResult, DocScore, FeatureMatchResult, ScoreReport
from ..orchestrator.context import RunContext, parse_ref
from ..orchestrator.errors import CommandError, message
from ..orchestrator.store import ExecutionFilter, RunFilter
from ..orchestrator.trace import ExecutionRecord
# 층별 채점 출처 · 현재 점수는 기록 통계 줄(finalScores · scores)과 같은 정의 하나 — log_stats.py에 있다
from .log_stats import SCORE_LAYERS
from .log_stats import current_scores as _current_scores
from .retention import retention_cutoff
from .rework_map import ARTIFACT_BUNDLES, BUNDLE_EXECUTABLE, BUNDLE_LAYER, DOCUMENT_BUNDLES, order_bundles
from .sbrain_flow import CANDIDATE_LIMIT, candidate_lists

if TYPE_CHECKING:
    from .service import SBrainOrchestrator


# ── 화면 모양 (초안) ───────────────────────────────────
class Screen(SBModel):
    """화면 조회 공통 (초안)."""
    screen: int
    project_id: str | None
    run_id: str
    step: str
    progress: str
    notices: list[Notice]


class ReworkOption(SBModel):
    """재작성 목록 한 줄 (초안) — 미달 항목의 재작성 지시와 묶음별 남은 기회."""
    order: ReworkOrder
    bundles: list[str]          # 기회를 세는 묶음 이름 (문서층: 문서층 묶음 4개, 산출물층: Task 묶음)
    remaining: int              # 남은 기회 (문서층: 4개 중 가장 많이 남은 값, 잠정)
    selectable: bool            # 고를 수 있는지 (기회가 없으면 E-G2-LIMIT, 원페이지는 T-B1 없음)


class ScoreView(SBModel):
    """점수 보고서에서 화면에 보일 부분 (초안) — 실행 설정 스냅샷 · 채점 기준 버전은 뺀다."""
    display_score: float
    total: float
    threshold: float
    passed: bool
    phase: str
    doc_score: DocScore
    artifact_score: ArtifactScore | None = None
    carried_over_layer: str | None = None
    comparisons: list[ReworkComparison] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


class CandidatesScreen(Screen):
    """3 공고 후보. 자격 정보는 막힌 공고(blockedAnnouncementIds)뿐이다 — 카드에는 싣지 않는다(spec 4.2.2 · 4.3.6).

    candidates는 첫 조회(추가 조회에 다시 나온 카드는 새 내용 · contentChanged), moreCandidates는 첫 조회와 겹친 공고를 뺀
    추가 조회 후보다. 실패한 추가 조회는 없던 것으로 본다 — 후보 · 수집 상태 · 대체 경로 표시가 조회 전 그대로다(4.2.3).
    """
    candidates: list[AnnouncementCard]
    more_candidates: list[AnnouncementCard]
    more_available: bool
    collection_status: CollectionStatus
    filtered_count: int
    fallback_used: bool
    fallback_mode: FallbackMode | None = None
    blocked_announcement_ids: list[str] = ext(
        default_factory=list, note="막힌 공고 ID — 자격 불통과로 이 실행 건에서 고를 수 없는 공고 (Run 값 그대로)")


class GateScreen(Screen):
    """4 자격 확인 결과. 확인 필요 조건(gateResult.unknownConditions)이 있으면 notices에 E-G1-UNPARSED를 붙인다 —
    실행 건 안내 목록에는 쌓지 않고 열 때마다 지금 자격 결과로 다시 만든다(spec 4.3.3)."""
    announcement_id: str | None
    gate_result: GateResult
    business_age_years: float | None = None
    can_start_writing: bool


class DocumentScreen(Screen):
    """6 문서 평가 — 계획서 · 환산 점수 · 미달 항목 · 재작성 목록 · 다음 동작."""
    plan_doc: PlanDoc
    score: ScoreView
    failed_task_ids: list[str]
    rework_options: list[ReworkOption]
    next_action: NextAction


class ArtifactScreen(Screen):
    """8 산출물 확인 — 프로토타입 · 인포그래픽 · 코드 점검 · 기능 대조 · 재작성 목록(산출물층)."""
    prototype: Prototype
    infographic: Infographic
    code_check: CodeCheckResult
    feature_match: FeatureMatchResult
    rework_options: list[ReworkOption]


class OverallScreen(Screen):
    """9 종합 평가 — 종합 점수 · 층별 내역(score 안) · 재작성 목록 · 다음 동작 · 변경 내역."""
    score: ScoreView
    rework_options: list[ReworkOption]
    next_action: NextAction
    rework_diff: list[ReworkDiff]


class SentenceChange(SBModel):
    """검수 대상 문장 하나의 전후 (초안). 채택하지 않았으면 after는 없고 원문이 남는다.

    attempts: T-P2 시도별 기록(SentenceResult.attempts) — 학습 동의와 관계없이 모든 계정에 준다.
    """
    sentence_id: str
    before: str
    after: str | None
    adopted: bool
    kept_reason: KeptReason | None = None
    attempts: list[ProofreadAttempt] = Field(default_factory=list)


class ProofreadScreen(Screen):
    """10 검수 전후 — 형식 지적, 문장별 전후, 검수 로그."""
    format_findings: list[FormatFinding]
    sentences: list[SentenceChange]
    proofread_log: ProofreadLog


class ResultScreen(Screen):
    """11 결과물."""
    deliverable: Deliverable
    user_message: str
    plan_doc: PlanDoc
    prototype: Prototype
    infographic: Infographic


# ── 지금까지 결과 · 재작성 결과 (확장) ─────────────────────
class Outputs(SBModel):
    """outputs 결과 — 진행 중 · 대기 중 · 재개대기 · 완료 실행 건이 지금까지 만든 결과(현재 버전).

    없는 것은 None · 빈 목록. 점수 보고서는 화면과 같은 ScoreView(실행 설정 스냅샷 없음)다.
    rework_usage: 묶음 이름 6개(문서층 4 · 산출물층 2, 원페이지는 실행 파일 제외)별 사용 수 · 남은 기회.
    rework_limit: 실행 시작 때 고정한 묶음마다의 재작성 상한.
    """
    project_id: str | None
    run_id: str
    step: str
    progress: str
    candidates: list[AnnouncementCard]                 # 첫 조회
    more_candidates: list[AnnouncementCard]            # 추가 조회
    selected_announcement: Announcement | None = None
    gate_result: GateResult | None = None
    business_age_years: float | None = None
    category: str | None = None
    plan_doc: PlanDoc | None = None
    doc_score: DocScore | None = None
    document_score_report: ScoreView | None = None     # scoreReport.document (G-02a)
    overall_score_report: ScoreView | None = None      # scoreReport.overall (G-02b)
    prototype: Prototype | None = None
    infographic: Infographic | None = None
    code_check: CodeCheckResult | None = None
    feature_match: FeatureMatchResult | None = None
    format_findings: list[FormatFinding] = Field(default_factory=list)
    sentence_results: list[SentenceResult] = Field(default_factory=list)   # 시도별 기록(attempts) 포함
    proofread_log: ProofreadLog | None = None
    deliverable: Deliverable | None = None
    user_message: str | None = None
    rework_usage: list[BundleUsage]
    rework_limit: int
    evaluation_items: list[EvalItem] = ext(
        default_factory=list,
        note="작업 분해(T-C3)가 고른 평가 항목(현재 버전). T-C3 전이면 빈 목록. 웹은 점수 항목 이름을 docScore.items[].itemCode와 "
             "이 목록의 itemCode로 맞춰 itemName에서 만든다 — 선택 공고의 evaluationItems는 자리 표시 값이다")


class ReworkFileChange(SBModel):
    """재작성으로 바뀐 산출물 파일의 전후 경로 (prototype: 진입 파일, infographic: 이미지)."""
    artifact: str
    before_path: str | None = None
    after_path: str | None = None


class ReworkResult(SBModel):
    """rework_result 결과 — 마지막 재작성 한 건 (Run.lastRework를 화면에 맞게 편 것).

    공통: 모은 묶음 · 화면 · 상태(진행중 · 완료 · 실패). 완료면 남긴 쪽 · 전후 점수 · 바뀐 산출물 전후 참조,
    계획서가 바뀌었으면 전후 섹션 본문, 산출물이 바뀌었으면 전후 파일 경로. 실패면 되돌렸다는 사실 · 돌려준 묶음 ·
    안내 코드만(전후 내용 없음). 실패 원인(관리자용)은 싣지 않는다.
    """
    project_id: str | None
    run_id: str
    cycle_id: str
    screen: int
    bundles: list[str]
    status: ReworkResultStatus
    started_at: datetime
    ended_at: datetime | None = None
    # 완료
    kept: KeptSide | None = None
    basis: str | None = None
    before_score: float | None = None
    after_score: float | None = None
    before_refs: list[str] = Field(default_factory=list)
    after_refs: list[str] = Field(default_factory=list)
    plan_before: list[PlanSection] | None = None
    plan_after: list[PlanSection] | None = None
    files: list[ReworkFileChange] = Field(default_factory=list)
    # 실패
    rolled_back: bool = False
    refunded_bundles: list[str] = Field(default_factory=list)
    notice_code: str | None = None


# ── 관리자 모양 (초안) ─────────────────────────────────
class TokenTotals(SBModel):
    """토큰 합계 — 입력은 캐시 입력을 포함한 전체, 출력은 추론을 포함한 전체. 기록이 없으면 None."""
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None


class AdminExecution(SBModel):
    """관리자 '에이전트 테스크' 한 줄 (초안, 메타데이터만)."""
    project_id: str | None
    run_id: str
    execution_id: str
    task_id: str
    agent: str
    attempt: int
    trigger: str                # 이유: 첫실행 · 재작성 · 재수행
    redo_count: int
    status: str
    model: str | None
    reasoning_effort: str | None
    temperature: float | None
    error_kind: str | None
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_sec: float | None
    tokens: TokenTotals


class AdminTry(SBModel):
    no: int
    outcome: str
    error_kind: str | None
    detail: str | None
    started_at: datetime
    ended_at: datetime
    tokens: TokenTotals


class AdminCall(SBModel):
    """실행 하나의 호출 기록 한 줄 (초안, 메타데이터만)."""
    call_id: str
    purpose: str
    item_key: str | None
    call_type: str
    provider: str | None
    model: str | None
    final_outcome: str
    error: str | None
    error_kind: str | None
    tries: list[AdminTry]
    tokens: TokenTotals


class AdminRun(SBModel):
    """관리자 실행 건 목록 한 줄 (메타데이터 · 점수만).

    current_task: 지금 단계(대기열 맨 앞, 비었으면 마지막으로 돈 단계), agent: 그 담당 Agent(내부 단계 CYCLE-END는 None),
    attempt: 가장 나중에 기록된 실행의 시도 번호.
    점수는 현재 버전(되돌리기 반영) — 문서층 docScore.total, 산출물층 artifactScore.total, 총점 scoreReport.overall.total.
    failure_reason: 관리자용 실패 사유 (사용자용 결과에는 없다).
    """
    project_id: str | None
    run_id: str
    step: str
    progress: str
    current_task: str | None
    agent: str | None
    attempt: int | None
    updated_at: datetime
    doc_score: float | None = None
    artifact_score: float | None = None
    total_score: float | None = None
    resume_count: int
    last_error_kind: str | None = None
    failure_reason: str | None = None


class ScoreEntry(SBModel):
    """채점 한 번 — 시각(실행 끝 시각), 점수, 재작성 사이클 안의 채점인지."""
    scored_at: datetime | None
    score: float
    after_rework: bool
    execution_id: str


class AdminScoreHistory(SBModel):
    """admin_score_history 결과 — 층별 채점 이력, 최근 순 (웹 이력보기와 같은 순서).

    doc_score: 문서층(T-V1 docScore.total), code_check: 코드 점검(T-V2 codeCheck.total),
    feature_match: 계획서 대조(T-V2 featureMatch.score). 되돌린 채점도 남는다(채점 기록이다).
    """
    project_id: str | None
    run_id: str
    doc_score: list[ScoreEntry]
    code_check: list[ScoreEntry]
    feature_match: list[ScoreEntry]


class ScoreBucket(SBModel):
    label: str
    count: int


class LayerChange(SBModel):
    """층별 첫 채점 대비 재작성 뒤 평균 변화. layer: docScore · codeCheck · featureMatch."""
    layer: str
    first_avg: float | None = None
    after_avg: float | None = None
    delta: float | None = None
    count: int = 0


class TriggerStat(SBModel):
    """시도 계기별 실행 기록 수와 평균 토큰 (입력 + 출력, 토큰 기록이 없는 실행은 0으로 센다)."""
    trigger: str
    count: int
    avg_tokens: float | None = None


class AdminSummary(SBModel):
    """admin_summary 결과 — 운영 요약 (개수 · 점수 · 토큰만). 정의는 각 필드 주석과 admin_summary docstring."""
    status_counts: dict[str, int]          # 진행 상태별 실행 건 수 (실행 · 재개대기 · 사용자대기 · 실패 · 완료 · 중단)
    doc_avg: float | None = None           # 현재 문서층 점수 평균 (소수 1자리)
    doc_count: int = 0
    total_avg: float | None = None         # 현재 총점(scoreReport.overall.total) 평균
    total_count: int = 0
    pass_count: int = 0                    # 총점 ≥ 기준 점수(지금 설정)
    pass_rate: float | None = None         # pass_count / total_count × 100
    pass_threshold: float
    reworked_runs: int = 0                 # 재작성 실행 기록이 있는 실행 건
    runs_with_executions: int = 0          # 실행 기록이 하나라도 있는 실행 건 (재작성 비율의 분모)
    rework_rate: float | None = None       # reworked_runs / runs_with_executions × 100
    score_buckets: list[ScoreBucket]
    layer_changes: list[LayerChange]
    triggers: list[TriggerStat]
    total_tokens: int = 0                  # 모든 실행 기록의 입력 + 출력 토큰
    proofread_attempts: int = 0            # T-P2 시도 수 (현재 sentenceResults의 attempts)
    proofread_rejected: int = 0            # 보호 토큰 검사를 통과하지 못한 시도
    proofread_reject_rate: float | None = None   # proofread_rejected / proofread_attempts × 100


class AdminAgentTask(SBModel):
    """Agent별 등록된 Task 수(규칙 단계 · 합치기 포함), 실행 기록 수, 가장 최근(시작 시각) 실행의 프로젝트 · 상태."""
    agent: str
    task_count: int
    task_ids: list[str]
    execution_count: int
    recent_project_id: str | None = None
    recent_status: str | None = None


# ── 화면 조회 ──────────────────────────────────────────
SCREEN_STATES: dict[int, set[tuple[str, str]]] = {
    3: {("공고선택", "사용자대기"), ("계획서작성", "사용자대기")},   # 자격 통과 뒤 다시 고르기 (3.3)
    4: {("공고선택", "사용자대기"), ("계획서작성", "사용자대기")},
    6: {("문서평가", "사용자대기")},
    8: {("산출물확인", "사용자대기")},
    9: {("종합평가", "사용자대기")},
    10: {("결과물", "완료")},
    11: {("결과물", "완료")},
}


def screen(orch: SBrainOrchestrator, project_id: int | str, number: int) -> Screen:
    if number not in SCREEN_STATES:
        raise CommandError("INVALID_SCREEN", str(number))
    run = orch.store.find_run_by_project(project_id)
    if run is None:
        raise CommandError("RUN_NOT_FOUND", str(project_id))
    state = (run.state.step, run.state.progress)
    if number == 3 and run.current_phase != "setup":
        # 작성을 시작한 뒤에는 공고 후보를 열지 않는다 — 공고 다시 고르기 · 추가 조회와 같은 거절 (3.3)
        raise CommandError("INVALID_STATE", f"화면 3 — 작성 시작 뒤 ({state[0]} · {state[1]})")
    if state not in SCREEN_STATES[number]:
        raise CommandError("SCREEN_NOT_READY", f"화면 {number} — 지금 {state[0]} · {state[1]}")
    ctx = orch.engine.open_context(run)
    if number == 4 and not ctx.has("gateResult"):
        raise CommandError("SCREEN_NOT_READY", "화면 4 — 자격 확인 전")
    base: dict[str, Any] = dict(screen=number, project_id=run.project_id, run_id=run.run_id, step=state[0],
                                progress=state[1], notices=list(run.notices))
    if number == 3:
        first, more = candidate_lists(ctx)
        return CandidatesScreen(
            **base, candidates=first, more_candidates=more,
            more_available=not run.more_used and len(first) + len(more) < CANDIDATE_LIMIT,
            collection_status=ctx.get("collectionStatus"), filtered_count=ctx.get("filteredCount"),
            fallback_used=ctx.get("fallbackUsed"), fallback_mode=ctx.get("fallbackMode", default=None),
            blocked_announcement_ids=list(run.blocked_announcement_ids))
    if number == 4:
        gate = ctx.get("gateResult")
        if gate.unknown_conditions:   # 확인 필요 — 막지 않는 안내, 화면 4에만 (spec 4.3.3)
            base["notices"] = [*base["notices"],
                               Notice(code="E-G1-UNPARSED", message=message("E-G1-UNPARSED"), at=orch.now())]
        return GateScreen(**base, announcement_id=run.announcement_id, gate_result=gate,
                          business_age_years=ctx.get("businessAgeYears", default=None),
                          can_start_writing=state[0] == "계획서작성")
    if number == 6:
        return DocumentScreen(
            **base, plan_doc=ctx.get("planDoc"), score=_score(ctx.get("scoreReport.document")),
            failed_task_ids=ctx.get("G-02a.failedTaskIds"),
            rework_options=_options(ctx, ctx.get("G-02a.reworkOrders")), next_action=ctx.get("G-02a.nextAction"))
    if number == 8:
        orders = [o for o in ctx.get("G-02b.reworkOrders") if o.layer == "artifact"]
        return ArtifactScreen(
            **base, prototype=ctx.get("prototype"), infographic=ctx.get("infographic"),
            code_check=ctx.get("codeCheck"), feature_match=ctx.get("featureMatch"),
            rework_options=_options(ctx, orders))
    if number == 9:
        return OverallScreen(
            **base, score=_score(ctx.get("scoreReport.overall")),
            rework_options=_options(ctx, ctx.get("G-02b.reworkOrders")), next_action=ctx.get("G-02b.nextAction"),
            rework_diff=ctx.get("reworkDiff"))
    if number == 10:
        return ProofreadScreen(**base, format_findings=ctx.get("formatFindings"),
                               sentences=_sentence_changes(orch, ctx), proofread_log=ctx.get("proofreadLog"))
    return ResultScreen(**base, deliverable=ctx.get("deliverable"), user_message=ctx.get("userMessage"),
                        plan_doc=ctx.get("planDoc"), prototype=ctx.get("prototype"),
                        infographic=ctx.get("infographic"))


def _score(report: ScoreReport) -> ScoreView:
    return ScoreView(display_score=report.display_score, total=report.total, threshold=report.threshold,
                     passed=report.passed, phase=report.phase, doc_score=report.doc_score,
                     artifact_score=report.artifact_score, carried_over_layer=report.carried_over_layer,
                     comparisons=list(report.comparisons), notices=list(report.notices))


def _options(ctx: RunContext, orders: list[ReworkOrder]) -> list[ReworkOption]:
    """판정 지시를 그대로 보여 주고, 묶음 · 남은 기회는 묶음 요청(request_rework_for_project)과 같은 이름으로 센다.

    산출물층 지시 → 그 Task의 묶음(실행 파일 · 인포그래픽). 문서층 지시 → 문서층 묶음 4개 전부, 남은 기회는 4개 중
    가장 많이 남은 값(잠정 — 임시 처리에서는 어느 이름으로 요청해도 계획서 전체를 다시 만든다). 고를 수 있음 = 그 값 > 0
    (원페이지 실행 파일 · 요청할 수 없는 묶음은 고를 수 없음).
    """
    usage = {u.bundle_id: u.remaining for u in ctx.run.rework_usage}
    per_bundle = ctx.settings.rework.per_bundle
    onepage = ctx.get("category") == "원페이지"
    out = []
    for o in orders:
        bundles = order_bundles(o)
        remaining = max((usage.get(b, per_bundle) for b in bundles), default=per_bundle)
        blocked = any(b not in BUNDLE_LAYER for b in bundles) or (onepage and BUNDLE_EXECUTABLE in bundles)
        out.append(ReworkOption(order=o, bundles=bundles, remaining=remaining,
                                selectable=remaining > 0 and not blocked))
    return out


def _sentence_changes(orch: SBrainOrchestrator, ctx: RunContext) -> list[SentenceChange]:
    """검수 전 문장은 T-P1이 읽은 계획서 버전에서 찾는다 (M-4가 새 버전을 만들기 전).

    T-P1 성공 저장에서 실행 건에 적은 참조(Run.proofread_base_ref)를 먼저 본다 — 12개월 처리로 실행 기록이 지워져도
    같은 문장이 나온다. 이 값이 없던 실행 건은 지금처럼 T-P1 실행 기록의 입력 참조에서 찾는다.
    """
    ref = ctx.run.proofread_base_ref
    if ref is None:
        tp1 = [r for r in orch.store.executions(ctx.run.run_id) if r.task_id == "T-P1" and r.status == "성공"]
        ref = next((i for i in tp1[-1].inputs if i.startswith("planDoc@")), None) if tp1 else None
    before: PlanDoc = ctx.get_ref(ref) if ref else ctx.get("planDoc")
    text = {s.sentence_id: s.text for sec in before.sections for s in sec.sentences}
    results: list[SentenceResult] = ctx.get("sentenceResults", default=[])
    return [SentenceChange(sentence_id=r.sentence_id, before=text.get(r.sentence_id, ""),
                           after=r.revised.text if r.adopted and r.revised else None, adopted=r.adopted,
                           kept_reason=r.kept_reason, attempts=list(r.attempts)) for r in results]


# ── 지금까지 결과 · 재작성 결과 ─────────────────────────────
NOT_VIEWABLE = ("실패", "중단")
FILE_PATHS = {"prototype": "entry_file_path", "infographic": "image_path"}   # 재작성 결과에 보일 파일 경로


def _viewable_run(orch: SBrainOrchestrator, project_id: int | str) -> Run:
    run = orch.store.find_run_by_project(project_id)
    if run is None:
        raise CommandError("RUN_NOT_FOUND", str(project_id))
    if run.state.progress in NOT_VIEWABLE:
        raise CommandError("RUN_NOT_VIEWABLE", f"{project_id}: {run.state.progress}")
    return run


def outputs(orch: SBrainOrchestrator, project_id: int | str) -> Outputs:
    run = _viewable_run(orch, project_id)
    ctx = orch.engine.open_context(run)

    def cur(key: str) -> Any:
        return ctx.get(key, default=None)
    first, more = candidate_lists(ctx)   # 화면 3과 같은 후보 — 실패한 추가 조회는 보지 않는다
    document, overall = cur("scoreReport.document"), cur("scoreReport.overall")
    category = cur("category")
    return Outputs(
        project_id=run.project_id, run_id=run.run_id, step=run.state.step, progress=run.state.progress,
        candidates=first, more_candidates=more,
        selected_announcement=cur("selectedAnnouncement"), gate_result=cur("gateResult"),
        business_age_years=cur("businessAgeYears"), category=category, plan_doc=cur("planDoc"),
        doc_score=cur("docScore"), document_score_report=_score(document) if document is not None else None,
        overall_score_report=_score(overall) if overall is not None else None,
        prototype=cur("prototype"), infographic=cur("infographic"), code_check=cur("codeCheck"),
        feature_match=cur("featureMatch"), format_findings=cur("formatFindings") or [],
        sentence_results=cur("sentenceResults") or [], proofread_log=cur("proofreadLog"),
        deliverable=cur("deliverable"), user_message=cur("userMessage"),
        rework_usage=_bundle_usage(ctx, category), rework_limit=ctx.settings.rework.per_bundle,
        evaluation_items=cur("evaluationItems") or [])


def _bundle_usage(ctx: RunContext, category: str | None) -> list[BundleUsage]:
    """묶음 이름 6개의 사용 수 · 남은 기회 (쓴 적 없는 묶음은 상한 그대로). 원페이지는 실행 파일이 없다."""
    used = {u.bundle_id: u for u in ctx.run.rework_usage}
    per_bundle = ctx.settings.rework.per_bundle
    names = [b for b in (*DOCUMENT_BUNDLES, *ARTIFACT_BUNDLES)
             if not (category == "원페이지" and b == BUNDLE_EXECUTABLE)]
    return [used[b].model_copy() if b in used else
            BundleUsage(bundle_id=b, layer=BUNDLE_LAYER[b], used_count=0, remaining=per_bundle) for b in names]


def rework_result(orch: SBrainOrchestrator, project_id: int | str) -> ReworkResult | None:
    run = _viewable_run(orch, project_id)
    s = run.last_rework
    if s is None:
        return None
    base: dict[str, Any] = dict(project_id=run.project_id, run_id=run.run_id, cycle_id=s.cycle_id, screen=s.screen,
                                bundles=list(s.bundles), status=s.status, started_at=s.started_at, ended_at=s.ended_at)
    if s.status == "실패":   # 되돌림 · 돌려준 묶음 · 안내만 (전후 내용 없음)
        return ReworkResult(**base, rolled_back=s.rolled_back, refunded_bundles=list(s.refunded_bundles),
                            notice_code=s.notice_code)
    if s.status != "완료":   # 진행중 — 이전 재작성 결과를 마지막처럼 주지 않는다
        return ReworkResult(**base)
    ctx = orch.engine.open_context(run)
    before = dict(parse_ref(r) for r in s.before_refs)
    after = dict(parse_ref(r) for r in s.after_refs)

    def value(key: str, version: int | None) -> Any:
        if version is None:
            return None
        try:
            return ctx.get(key, version)
        except KeyError:   # 완전 삭제 뒤
            return None

    def sections(version: int | None) -> list[PlanSection] | None:
        plan = value("planDoc", version)
        return list(plan.sections) if plan is not None else None

    def path(key: str, version: int | None) -> str | None:
        obj = value(key, version)
        return getattr(obj, FILE_PATHS[key]) if obj is not None else None
    changed_plan = "planDoc" in before or "planDoc" in after
    files = [ReworkFileChange(artifact=k, before_path=path(k, before.get(k)), after_path=path(k, after.get(k)))
             for k in FILE_PATHS if k in before or k in after]
    return ReworkResult(
        **base, kept=s.kept, basis=s.basis, before_score=s.before_score, after_score=s.after_score,
        before_refs=list(s.before_refs), after_refs=list(s.after_refs),
        plan_before=sections(before.get("planDoc")) if changed_plan else None,
        plan_after=sections(after.get("planDoc")) if changed_plan else None, files=files)


# ── 관리자 조회 ────────────────────────────────────────
def admin_executions(orch: SBrainOrchestrator, *, project_id: int | str | None = None, task_id: str | None = None,
                     status: str | None = None, agent: str | None = None, since: datetime | None = None,
                     until: datetime | None = None, limit: int = 50, offset: int = 0,
                     order: Literal["desc", "asc"] = "desc") -> list[AdminExecution]:
    rows = orch.store.list_executions(ExecutionFilter(
        project_id=project_id, task_id=task_id, status=status, agent=agent, since=since, until=until,
        limit=limit, offset=offset, order=order))
    out = []
    for row in rows:
        r = row.record
        duration = (r.ended_at - r.started_at).total_seconds() if r.started_at and r.ended_at else None
        out.append(AdminExecution(
            project_id=row.project_id, run_id=r.run_id, execution_id=r.execution_id, task_id=r.task_id,
            agent=r.agent, attempt=r.attempt, trigger=r.trigger, redo_count=r.redo_count, status=r.status,
            model=r.model, reasoning_effort=r.reasoning_effort, temperature=r.temperature, error_kind=r.error_kind,
            error=r.error, started_at=r.started_at, ended_at=r.ended_at, duration_sec=duration, tokens=_tokens(r)))
    return out


def admin_calls(orch: SBrainOrchestrator, execution_id: str) -> list[AdminCall]:
    return [AdminCall(
        call_id=c.call_id, purpose=c.purpose, item_key=c.item_key, call_type=c.call_type, provider=c.provider,
        model=c.model, final_outcome=c.final_outcome, error=c.error, error_kind=c.error_kind, tokens=_tokens(c),
        tries=[AdminTry(no=t.no, outcome=t.outcome, error_kind=t.error_kind, detail=t.detail,
                        started_at=t.started_at, ended_at=t.ended_at, tokens=_tokens(t)) for t in c.tries])
        for c in orch.store.execution_calls(execution_id)]


def _tokens(obj: Any) -> TokenTotals:
    """토큰 기록 (작업지시 S6에서 기록 필드가 생긴다 — 그 전에는 모두 None)."""
    return TokenTotals(**{f: getattr(obj, f, None) for f in TokenTotals.model_fields})


# 총점 구간 — 웹 admin.py ops-summary와 같은 경계 · 같은 비교(정수 경계 양 끝 포함, lo ≤ 총점 ≤ hi)
SCORE_BUCKETS = (("90~100점", 90, 100), ("80~89점", 80, 89), ("70~79점", 70, 79), ("60~69점", 60, 69),
                 ("60점 미만", 0, 59))
TRIGGERS = ("첫실행", "재작성", "재수행")


def _score_events(records: list[ExecutionRecord]) -> dict[str, list[ScoreEntry]]:
    """층별 채점 기록 (오래된 순). 채점 = 성공한 T-V1 · T-V2 실행, 재작성 뒤 = 재작성 사이클 안의 실행(trigger 재작성)."""
    events: dict[str, list[ScoreEntry]] = {layer: [] for layer, _, _ in SCORE_LAYERS}
    for r in records:
        if r.status != "성공":
            continue
        for layer, task, field in SCORE_LAYERS:
            score = getattr(r.output_meta, field) if r.task_id == task else None
            if score is not None:
                events[layer].append(ScoreEntry(scored_at=r.ended_at, score=score, after_rework=r.trigger == "재작성",
                                                execution_id=r.execution_id))
    for entries in events.values():
        entries.sort(key=lambda e: e.scored_at or UTC_MIN)
    return events


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def _admin_since(orch: SBrainOrchestrator) -> datetime:
    """관리자 실행 건 목록 · 운영 요약의 범위 시작 — 지금에서 12개월 전 (보관 기간 작업의 기준 시각과 같다)."""
    return retention_cutoff(orch.now())


def admin_runs(orch: SBrainOrchestrator, *, progress: str | None = None, step: str | None = None, limit: int = 50,
               offset: int = 0) -> list[AdminRun]:
    """여러 프로젝트의 실행 건 (마지막 갱신 최근 순). 진행 상태 · 단계로 거르고 limit · offset으로 나눈다.

    마지막 활동(updated_at)이 최근 12개월 안인 실행 건만 — 기준 시각은 보관 기간 작업과 같은 계산(retention_cutoff).
    """
    out = []
    for run in orch.store.query_runs(RunFilter(progress=progress, step=step, limit=limit, offset=offset,
                                               updated_since=_admin_since(orch))):
        records = orch.store.executions(run.run_id)
        scores = _current_scores(orch.store.get_pointers(run.run_id), records)
        # 지금 Task — 대기열 맨 앞(도는 중 · 다음에 돌 단계, 재개대기면 재개할 단계), 대기열이 비었으면 마지막으로 돈 단계
        task = run.queue[0] if run.queue else run.current_task
        agent = orch.engine.registry.get(task).agent if task and orch.engine.registry.has(task) else None
        out.append(AdminRun(
            project_id=run.project_id, run_id=run.run_id, step=run.state.step, progress=run.state.progress,
            current_task=task, agent=agent, attempt=records[-1].attempt if records else None,
            updated_at=run.updated_at, doc_score=scores["doc"], artifact_score=scores["artifact"],
            total_score=scores["total"], resume_count=run.resume_count, last_error_kind=run.last_error_kind,
            failure_reason=run.failure_reason))
    return out


def admin_score_history(orch: SBrainOrchestrator, project_id: int | str) -> AdminScoreHistory:
    run = orch.store.find_run_by_project(project_id)
    if run is None:
        raise CommandError("RUN_NOT_FOUND", str(project_id))
    events = _score_events(orch.store.executions(run.run_id))
    return AdminScoreHistory(project_id=run.project_id, run_id=run.run_id,
                             **{field: list(reversed(events[layer])) for layer, field in (
                                 ("docScore", "doc_score"), ("codeCheck", "code_check"),
                                 ("featureMatch", "feature_match"))})


def admin_summary(orch: SBrainOrchestrator) -> AdminSummary:
    """운영 요약 — 모든 실행 건 · 실행 기록에서 센다 (웹 admin.py ops-summary · agent-ops-summary 대응).

    정의 (웹의 지금 계산과 같게 맞춘 것):
    - 문서층 · 총점 평균: 현재 버전 점수(되돌리기 반영)가 있는 실행 건의 평균, 소수 1자리. 총점은 판정(G-02b)의
      scoreReport.overall.total이다(웹은 doc_score + artifact_score).
    - 통과: 총점 ≥ 기준 점수(지금 설정 scoring.threshold). 통과율 = 통과 수 / 총점이 있는 실행 건 수 × 100.
    - 총점 구간: 90~100 · 80~89 · 70~79 · 60~69 · 60 미만, 각 구간은 정수 경계 양 끝 포함(lo ≤ 총점 ≤ hi) — 웹과 같다.
    - 재작성 비율 = 재작성 실행 기록이 있는 실행 건 / 실행 기록이 하나라도 있는 실행 건 × 100.
    - 층별 변화: 실행 건마다 그 층의 첫 채점과 마지막 재작성 뒤 채점(재작성 사이클 안의 마지막 채점)이 둘 다 있는 것만
      센다. 첫 평균 · 재작성 뒤 평균은 소수 1자리, 차이 = 재작성 뒤 평균 - 첫 평균(반올림한 평균끼리, 웹과 같다).
    - 시도 계기별: 실행 기록 수, 평균 토큰 = (입력 + 출력) 합 / 그 계기의 실행 기록 수(토큰 기록이 없는 실행은 0).
    - 표현 검수: 실행 건마다 현재 sentenceResults의 시도(attempts) 수 · 보호 토큰 검사 불통과 시도 수,
      반려 비율 = 반려 / 시도 × 100.
    - 비율은 분모가 0이면 None, 백분율 소수 1자리.

    범위: 마지막 활동(updated_at)이 최근 12개월 안인 실행 건과 그 실행 건들의 실행 기록만 센다(admin_runs와 같은 기준
    시각, retention_cutoff) — 진행 상태별 건수 · 점수 · 재작성 · 층별 변화 · 계기별 · 토큰 · 표현 검수가 모두 같은 범위다.

    우리 기록으로 셀 수 없어 뺀 것: 실행 건이 없는 프로젝트(웹의 '공고 매칭 전')는 세지 않고, 진행 상태는 웹의 상태
    표시('판단 대기' 등) 대신 실행 건의 진행 상태로 센다. 완전 삭제한 실행 건은 현재 점수 · 표현 검수 시도를 셀 수 없어
    그 항목에서 빠진다(채점 이력 · 실행 기록 수 · 토큰은 남는다).
    """
    runs = orch.store.query_runs(RunFilter(limit=None, updated_since=_admin_since(orch)))
    in_scope = {run.run_id for run in runs}
    by_run: dict[str, list[ExecutionRecord]] = defaultdict(list)
    for row in orch.store.list_executions(ExecutionFilter(limit=None, order="asc")):
        if row.record.run_id in in_scope:   # 범위 밖(12개월 전) 실행 건의 기록은 세지 않는다
            by_run[row.record.run_id].append(row.record)
    status: Counter[str] = Counter()
    docs: list[float] = []
    totals: list[float] = []
    firsts: dict[str, list[float]] = defaultdict(list)
    afters: dict[str, list[float]] = defaultdict(list)
    reworked = attempts = rejected = 0
    for run in runs:
        status[run.state.progress] += 1
        records = by_run.get(run.run_id, [])
        pointers = orch.store.get_pointers(run.run_id)
        scores = _current_scores(pointers, records)
        if scores["doc"] is not None:
            docs.append(scores["doc"])
        if scores["total"] is not None:
            totals.append(scores["total"])
        if any(r.trigger == "재작성" for r in records):
            reworked += 1
        for layer, entries in _score_events(records).items():
            after = [e for e in entries if e.after_rework]
            if entries and after and after[-1].execution_id != entries[0].execution_id:
                firsts[layer].append(entries[0].score)
                afters[layer].append(after[-1].score)
        if "sentenceResults" in pointers:
            try:
                results = orch.store.get_artifact(run.run_id, "sentenceResults", pointers["sentenceResults"]).value
            except KeyError:
                results = []
            for res in results or []:   # 개수만 센다 — 문장 내용은 읽어 싣지 않는다
                for a in res.get("attempts", []):
                    attempts += 1
                    rejected += 0 if (a.get("tokenCheck") or {}).get("passed") else 1
    threshold = orch.settings.current().scoring.threshold
    passed = sum(1 for t in totals if t >= threshold)
    changes = []
    for layer, _, _ in SCORE_LAYERS:
        first_avg, after_avg = _avg(firsts[layer]), _avg(afters[layer])
        delta = round(after_avg - first_avg, 1) if first_avg is not None and after_avg is not None else None
        changes.append(LayerChange(layer=layer, first_avg=first_avg, after_avg=after_avg, delta=delta,
                                   count=len(firsts[layer])))
    every = [r for records in by_run.values() for r in records]

    def tokens(r: ExecutionRecord) -> int:
        return (r.input_tokens or 0) + (r.output_tokens or 0)
    triggers = []
    for trig in TRIGGERS:
        mine = [r for r in every if r.trigger == trig]
        triggers.append(TriggerStat(trigger=trig, count=len(mine),
                                    avg_tokens=_avg([float(tokens(r)) for r in mine])))
    with_exec = sum(1 for run in runs if by_run.get(run.run_id))
    return AdminSummary(
        status_counts={p: status.get(p, 0) for p in typing.get_args(RunProgress)},
        doc_avg=_avg(docs), doc_count=len(docs), total_avg=_avg(totals), total_count=len(totals),
        pass_count=passed, pass_rate=_rate(passed, len(totals)), pass_threshold=threshold,
        reworked_runs=reworked, runs_with_executions=with_exec, rework_rate=_rate(reworked, with_exec),
        score_buckets=[ScoreBucket(label=label, count=sum(1 for t in totals if lo <= t <= hi))
                       for label, lo, hi in SCORE_BUCKETS],
        layer_changes=changes, triggers=triggers, total_tokens=sum(tokens(r) for r in every),
        proofread_attempts=attempts, proofread_rejected=rejected, proofread_reject_rate=_rate(rejected, attempts))


def admin_agent_tasks(orch: SBrainOrchestrator) -> list[AdminAgentTask]:
    """Agent별(기준 문서 Agent 순서) 등록된 단계 수 · 실행 기록 수 · 가장 최근 실행(시작 시각)의 프로젝트 · 상태."""
    specs = orch.engine.registry.specs()
    agents = list(typing.get_args(AgentName))
    agents += [a for a in dict.fromkeys(s.agent for s in specs) if a not in agents]
    out = []
    for agent in agents:
        ids = [s.task_id for s in specs if s.agent == agent]
        latest = orch.store.list_executions(ExecutionFilter(agent=agent, limit=1))
        out.append(AdminAgentTask(
            agent=agent, task_count=len(ids), task_ids=ids,
            execution_count=orch.store.count_executions(ExecutionFilter(agent=agent)),
            recent_project_id=latest[0].project_id if latest else None,
            recent_status=latest[0].record.status if latest else None))
    return out


__all__ = [
    "AdminAgentTask", "AdminCall", "AdminExecution", "AdminRun", "AdminScoreHistory", "AdminSummary", "AdminTry",
    "ArtifactScreen", "CandidatesScreen", "DocumentScreen", "GateScreen", "LayerChange", "Outputs", "OverallScreen",
    "ProofreadScreen", "ResultScreen", "ReworkFileChange", "ReworkOption", "ReworkResult", "Screen", "ScoreBucket",
    "ScoreEntry", "ScoreView", "SentenceChange", "TokenTotals", "TriggerStat", "admin_agent_tasks", "admin_calls",
    "admin_executions", "admin_runs", "admin_score_history", "admin_summary", "outputs", "rework_result", "screen",
]
