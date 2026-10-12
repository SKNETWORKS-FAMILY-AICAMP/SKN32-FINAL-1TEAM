"""오케스트레이터 가짜 구현 — gateway · 라우터 · mapping 테스트용.

sbrain의 결과 dataclass와 같은 필드를 가진 사본을 둔다(test_orch_fake_contract가 필드 일치를 확인한다).
FakeOrch는 부른 함수 이름과 인자를 calls에 쌓고, 미리 정한 값(또는 예외, 함수)을 돌려준다.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from typing import Any

from app.orch.errors import OrchError


@dataclass
class Notice:
    code: str
    message: str
    at: datetime


@dataclass
class RunView:
    run_id: str
    step: str
    progress: str
    screen_status: str
    resume_step: int
    percent: int
    current_label: str | None
    notices: list = field(default_factory=list)
    notifications: list = field(default_factory=list)
    retry_count: int = 0
    resume_count: int = 0
    next_resume_at: datetime | None = None
    last_error_kind: str | None = None
    rework_screen: int | None = None
    collecting: bool = False
    announcement_id: str | None = None


@dataclass
class ProjectView:
    project_id: str
    run: RunView | None = None
    start: Any = None


@dataclass
class ActiveWork:
    project_id: str | None
    run_id: str | None = None
    request_id: str | None = None
    step: str | None = None
    resume_step: int | None = None
    screen_status: str = '진행 중'


@dataclass
class StartCheck:
    ok: bool
    request_id: str | None = None
    code: str | None = None
    message: str | None = None
    missing: list = field(default_factory=list)
    active: ActiveWork | None = None


@dataclass
class StartStatus:
    request_id: str
    status: str
    code: str | None = None
    message: str | None = None
    notices: list = field(default_factory=list)
    run_id: str | None = None
    active: ActiveWork | None = None


@dataclass
class AbortResult:
    project_id: str
    cancelled_requests: list = field(default_factory=list)
    cancel_requested: list = field(default_factory=list)
    run_id: str | None = None
    run_action: str | None = None


@dataclass
class DeleteResult:
    project_id: str
    abort: AbortResult
    run_id: str | None = None
    deleted_artifacts: bool = False
    cleared_forms: int = 0


@dataclass
class AccountDeleteResult:
    account_id: str
    cancelled_requests: list = field(default_factory=list)
    aborted_runs: list = field(default_factory=list)
    deleted_runs: int = 0
    deleted_requests: int = 0
    stats_rows: int = 0


@dataclass
class ReworkAccepted:
    project_id: str | None
    run_id: str
    cycle_id: str
    screen: int
    bundles: list
    collect_until: datetime
    duplicate: bool = False


@dataclass
class ConfirmationNeeded:
    reason: str
    items: dict


@dataclass
class BonusItem:
    name: str
    points: float


@dataclass
class Card:
    announcement_id: str
    title: str
    agency: str = '테스트기관'
    apply_end: Any = None
    support_amount_max: int | None = None
    fit_score: float = 0.8
    rank: int = 1
    display_type: str = 'card'
    match_reason: str = '아이디어와 맞는 공고예요'
    source_notice: str = '출처: 테스트'
    original_url: str = 'https://example.com/n'
    apply_period_type: str = '기간 있음'
    content_changed: bool = False
    content_version: str | None = None
    bonus_score: float | None = None
    bonus_items: list = field(default_factory=list)


@dataclass
class CandidatesScreen:
    candidates: list
    more_candidates: list = field(default_factory=list)
    more_available: bool = True
    collection_status: str = '정상'
    filtered_count: int = 0
    fallback_used: bool = False
    fallback_mode: str | None = None
    blocked_announcement_ids: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    screen: int = 3
    project_id: str | None = None
    run_id: str = 'r1'
    step: str = '공고선택'
    progress: str = '사용자대기'


def make_cards(start: int, count: int) -> list[Card]:
    return [Card(announcement_id=f'N-{i:02d}', title=f'테스트 공고 {i}', rank=i) for i in range(start, start + count)]


def make_run(**overrides: Any) -> RunView:
    base = dict(run_id='r1', step='계획서작성', progress='실행', screen_status='진행 중', resume_step=5, percent=40,
                current_label='계획서 작성')
    base.update(overrides)
    return RunView(**base)


class Dumpable(NS):
    """pydantic 모델처럼 model_dump를 가진 값(차트 · 표)."""

    def model_dump(self, mode: str = 'python') -> dict:
        return dict(vars(self))


def make_sentence(i: int, text: str, paragraph_no: int = 1, is_title: bool = False) -> NS:
    return NS(sentence_id=f's{i}', text=text, is_title=is_title, paragraph_no=paragraph_no)


def make_sentence_change(sentence_id: str, before: str, after: str | None = None, adopted: bool = False, **overrides: Any) -> NS:
    """화면 10 문장 하나의 전후(SentenceChange)."""
    base = dict(sentence_id=sentence_id, before=before, after=after, adopted=adopted, kept_reason=None, attempts=[])
    base.update(overrides)
    return NS(**base)


def make_proofread_screen(sentences: list | None = None, **overrides: Any) -> NS:
    """화면 10(ProofreadScreen)의 필드."""
    base = dict(
        screen=10, project_id=None, run_id='r1', step='결과물', progress='완료', notices=[], format_findings=[],
        sentences=list(sentences or []), proofread_log=None)
    base.update(overrides)
    return NS(**base)


def make_section(code: str, title: str, *texts: str, tag: str | None = None, content_type: str = 'section') -> NS:
    """texts마다 문장 하나, 문단 번호는 인자 순서대로 1부터(문단 사이는 줄바꿈으로 이어진다).

    tag(웹 태그 1-1 ~ 4-1 또는 None) · content_type(section · table · image)은 SB-310에서 늘었다 — 기본은 태그 없음 · 본문이고,
    image 항목은 문장이 0개다(texts를 비운다)."""
    return NS(section_code=code, title=title, sentences=[make_sentence(i, t, paragraph_no=i) for i, t in enumerate(texts, 1)],
              tag=tag, content_type=content_type)


def make_file_ref(name: str, key: str | None = None, media_type: str = 'image/svg+xml', size: int = 1, sha256: str = '0' * 64) -> NS:
    """산출물 파일 참조(FileRef)의 필드."""
    return NS(key=key or f'r1/e1/uniq/{name}', name=name, media_type=media_type, size=size, sha256=sha256)


def make_diagram(source_ref: str = '2.3.6', flow_type: str = 'USER_FLOW', nodes: list | None = None, **overrides: Any) -> NS:
    """계획서 그림 하나(DiagramSpec) — 그림 항목(2.3.6 · 3.3.6)마다 서비스 흐름도 · 서비스 구조도 두 개가 온다."""
    base = dict(
        diagram_id=f'{source_ref}-{flow_type}', flow_type=flow_type, nodes=list(nodes or ['시작', '처리', '완료']),
        visual_style={'palette': ['#1F2937']}, source_ref=source_ref, image_file=make_file_ref(f'{source_ref}_{flow_type}.svg'))
    base.update(overrides)
    return NS(**base)


def make_plan_doc(sections: list | None = None, **overrides: Any) -> NS:
    base = dict(
        sections=sections if sections is not None else [make_section('1-1', '문제 인식', '문제를 설명한다.', '근거를 든다.')],
        feature_list=['예약', '결제'], charts=[], tables=[], protected_tokens=[], diagrams=[])
    base.update(overrides)
    return NS(**base)


def make_gate(passed: bool = True, **overrides: Any) -> NS:
    base = dict(passed=passed, failed_conditions=[], missing_inputs=[], undecidable=False, unknown_conditions=[])
    base.update(overrides)
    return NS(**base)


def make_gate_screen(announcement_id: str = 'N-01', gate: NS | None = None, **overrides: Any) -> NS:
    """화면 4(GateScreen)의 필드."""
    base = dict(
        screen=4, project_id=None, run_id='r1', step='계획서작성', progress='사용자대기', notices=[],
        announcement_id=announcement_id, gate_result=gate or make_gate(), business_age_years=None, can_start_writing=True)
    base.update(overrides)
    return NS(**base)


def make_feature_match(**overrides: Any) -> NS:
    """계획서 대조 결과(FeatureMatchResult) — 확장 필드(withheld · withheld_reason · partial_features) 포함."""
    base = dict(
        score=15.0, missing_features=[], extra_features=[], findings=[], judged_by='규칙', withheld=False,
        withheld_reason=None, partial_features=[])
    base.update(overrides)
    return NS(**base)


def make_score_view(total: float = 82.0, threshold: float = 80.0, passed: bool = True, with_artifact: bool = True, **overrides: Any) -> NS:
    """화면 점수 보고서(ScoreView). 환산 칸(그 실행 건 배점으로 환산한 점수 · 만점, SB-345)은 모두 None · 빈 목록이 기본이다 — 옛 실행 건은 비어 온다."""
    artifact = NS(
        total=30.0, code_check=NS(total=15.0, checks=[]), feature_match=make_feature_match(),
    ) if with_artifact else None
    base = dict(
        display_score=total, total=total, threshold=threshold, passed=passed, phase='종합',
        doc_score=NS(total=52.0, items=[]), artifact_score=artifact, carried_over_layer=None, comparisons=[], notices=[],
        doc_layer_max=None, code_check_score=None, code_check_max=None, feature_match_score=None, feature_match_max=None,
        artifact_layer_score=None, artifact_layer_max=None, code_check_items=[])
    base.update(overrides)
    return NS(**base)


def make_table_fallback(section_code: str = '2.5.2', reason: str = '내부 진단 원문', display_reason: str = '쉬운 안내') -> NS:
    """표 대체 사유 하나(TableFallback) — test_orch_fake_contract가 실제 모델과 칸을 맞춰 본다."""
    return NS(section_code=section_code, reason=reason, display_reason=display_reason)


def make_outputs(**overrides: Any) -> NS:
    """outputs(project_id) 결과 — sbrain.flow.reads.Outputs와 같은 필드(test_orch_fake_contract가 확인한다)."""
    base = dict(
        project_id='1', run_id='r1', step='문서평가', progress='사용자대기', candidates=[], more_candidates=[],
        selected_announcement=None, gate_result=None, business_age_years=None, category=None, plan_doc=None,
        table_fallbacks=[], doc_score=None, document_score_report=None, overall_score_report=None, prototype=None, infographic=None,
        code_check=None, feature_match=None, format_findings=[], sentence_results=[], proofread_log=None,
        deliverable=None, user_message=None, rework_usage=[], rework_limit=1, evaluation_items=[])
    base.update(overrides)
    return NS(**base)


def make_tokens(input_tokens: int | None = None, output_tokens: int | None = None) -> NS:
    return NS(input_tokens=input_tokens, cached_input_tokens=None, output_tokens=output_tokens, reasoning_tokens=None)


def make_admin_run(project_id: int | str = 1, **overrides: Any) -> NS:
    """admin_runs 한 줄(AdminRun) — updated_at은 시간대 있는 UTC."""
    base = dict(
        project_id=str(project_id), run_id='r1', step='계획서작성', progress='실행', current_task='작성-1', agent='작성',
        attempt=1, updated_at=datetime.now(UTC), doc_score=None, artifact_score=None, total_score=None,
        resume_count=0, last_error_kind=None, failure_reason=None, doc_max=None, artifact_max=None)
    base.update(overrides)
    return NS(**base)


def make_admin_execution(**overrides: Any) -> NS:
    base = dict(
        project_id='1', run_id='r1', execution_id='e1', task_id='T-W1', agent='작성', attempt=1, trigger='첫실행',
        redo_count=0, status='성공', model='gpt-test', reasoning_effort=None, temperature=None, error_kind=None,
        error=None, started_at=datetime.now(UTC), ended_at=None, duration_sec=1.5, tokens=make_tokens(100, 20),
        image_input_tokens=None, image_output_tokens=None)
    base.update(overrides)
    return NS(**base)


def make_admin_agent_task(**overrides: Any) -> NS:
    base = dict(agent='작성', task_count=3, task_ids=['T-W1'], execution_count=5, recent_project_id='1',
                recent_status='성공')
    base.update(overrides)
    return NS(**base)


def make_score_entry(score: float, after_rework: bool = False, scored_at: datetime | None = None) -> NS:
    return NS(scored_at=scored_at or datetime.now(UTC), score=score, after_rework=after_rework, execution_id='e1')


def make_admin_score_history(**overrides: Any) -> NS:
    base = dict(project_id='1', run_id='r1', doc_score=[], code_check=[], feature_match=[],
                doc_max=None, code_check_max=None, feature_match_max=None)
    base.update(overrides)
    return NS(**base)


def make_file_deletion(**overrides: Any) -> NS:
    """admin_file_deletions 한 줄(AdminFileDeletion) — 시각은 시간대 있는 UTC."""
    now = datetime.now(UTC)
    base = dict(
        deletion_id='d1', run_id='r1', status='포기', attempts=3, last_error_kind='운영', created_at=now, next_at=now,
        last_tried_at=now, gave_up_at=now, retried_by=None, retried_at=None, retry_count=0)
    base.update(overrides)
    return NS(**base)


def make_admin_summary(**overrides: Any) -> NS:
    base = dict(
        status_counts={}, doc_avg=None, doc_count=0, total_avg=None, total_count=0, pass_count=0, pass_rate=None,
        pass_threshold=80.0, reworked_runs=0, runs_with_executions=0, rework_rate=None, score_buckets=[],
        layer_changes=[], triggers=[], total_tokens=0, total_image_tokens=0, proofread_attempts=0, proofread_rejected=0,
        proofread_reject_rate=None)
    base.update(overrides)
    return NS(**base)


def run_not_found(*_args: Any, **_kwargs: Any) -> None:
    raise OrchError('RUN_NOT_FOUND', '실행 건 없음')


def default_responses() -> dict[str, Any]:
    """진행 중인 작업 없음 · 시작 요청 통과 · 실행 건 없음 — 라우터 테스트의 기본 상태."""
    return {
        'admin_runs': lambda **kwargs: [],
        'outputs': run_not_found,
        'screen': run_not_found,
        'active_work': None,
        'request_start': lambda account_id, project_id: StartCheck(ok=True, request_id='req-1'),
        'view_project': lambda project_id: ProjectView(project_id=str(project_id)),
        'wait_project': lambda project_id, timeout_sec=60.0: ProjectView(project_id=str(project_id)),
        'project_views': lambda project_ids: [ProjectView(project_id=str(i)) for i in project_ids],
        'delete_account_data': lambda account_id: AccountDeleteResult(account_id=str(account_id)),
        'abort_project': lambda project_id: AbortResult(project_id=str(project_id)),
        'delete_project_data': lambda project_id: DeleteResult(
            project_id=str(project_id), abort=AbortResult(project_id=str(project_id))),
    }


class FakeOrch:
    """responses: {함수 이름: 돌려줄 값 | 올릴 예외 | 호출될 함수}. 정하지 않은 함수는 None을 돌려준다."""

    def __init__(self, **responses: Any) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        if name.startswith('_') or name in ('responses', 'calls'):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            value = self.responses.get(name)
            if isinstance(value, Exception):
                raise value
            if callable(value):
                return value(*args, **kwargs)
            return value

        return call
