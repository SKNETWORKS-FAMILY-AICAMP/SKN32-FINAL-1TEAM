"""관리자 조회 결과 → 웹 관리자 응답 값 변환 (웹연동_변경사항_웹팀전달.md 3.9절).

mapping.py처럼 결과 객체는 속성으로만 읽고(duck typing) sbrain을 import하지 않는다.
관리자 화면이 쓰던 값 표기(상태 · 실행 이유)는 그대로 쓸 수 있게 웹 표기로 바꿔 주고, 오케스트레이터 원래 표기는
`*_ko`/`status_label` 등 따로 붙여 둔다 — 화면이 새 표기로 옮겨 가면 그때 없앤다.
"""
import datetime

from app import pipeline_stages as ps
from app import schemas

from .mapping import match_status_of, stage_of

STALLED_AFTER = datetime.timedelta(hours=48)
NO_MATCH_LABEL = '공고 매칭 전'

# RunView.progress / AdminRun.progress → 진행 현황 '상태' 표기
STATUS_LABEL_BY_PROGRESS = {
    '실행': '진행중', '재개대기': '진행중', '사용자대기': '판단 대기', '실패': '실패', '완료': '완료', '중단': '중단',
}

# 실행 기록 상태(성공 · 실패 · 실행 · 재개대기 · 생략) → 웹이 쓰던 표기
EXEC_STATUS_TO_WEB = {
    '성공': ps.GENERATION_STATUS_COMPLETED,
    '실패': ps.GENERATION_STATUS_FAILED,
    '실행': ps.GENERATION_STATUS_IN_PROGRESS,
    '재개대기': ps.GENERATION_STATUS_WAITING_RESUME,
    '생략': 'skipped',
}
EXEC_STATUS_FROM_WEB = {web: ko for ko, web in EXEC_STATUS_TO_WEB.items()}

# 실행 이유(첫실행 · 재작성 · 재수행) → 웹 rerun_type(initial · rerun)
INITIAL_TRIGGER = '첫실행'

# 관리자 층 이름 ↔ 웹 layer(doc · code · plan)
LAYER_TO_WEB = {'docScore': 'doc', 'codeCheck': 'code', 'featureMatch': 'plan'}


def utc(dt: datetime.datetime | None) -> datetime.datetime | None:
    """시간대 있는 UTC로 맞춘다 — 시간대 없는 값은 UTC로 본다(웹 DB 값). 비교 · 뺄셈 때 TypeError를 막는다."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(datetime.UTC)


def exec_status_to_web(status: str | None) -> str | None:
    return EXEC_STATUS_TO_WEB.get(status, status) if status is not None else None


def exec_status_from_web(status: str | None) -> str | None:
    """화면이 보내는 거름 값(웹 표기 · 한글 표기 둘 다)을 오케스트레이터 표기로."""
    return EXEC_STATUS_FROM_WEB.get(status, status) if status is not None else None


# ── 진행 현황 (admin_runs) ────────────────────────────────────────────────────────────
def _base_item(project) -> dict:
    return {
        'project_id': project.project_id,
        'description': project.description,
        'user_name': project.company.user.name,
        'created_at': project.created_at,
    }


def item_no_run(project) -> schemas.ItemOut:
    """실행 건이 없는 프로젝트 = 공고 매칭 전(웹 projects로 만든 행)."""
    return schemas.ItemOut(
        **_base_item(project), status_label=NO_MATCH_LABEL, last_updated=project.created_at,
        archived=project.archived_at is not None)


def _stalled(label: str, archived: bool, updated_at: datetime.datetime | None, now: datetime.datetime) -> bool:
    return (
        not archived and label == '진행중' and updated_at is not None and (now - utc(updated_at)) > STALLED_AFTER
    )


def item_from_run(project, run, now: datetime.datetime | None = None) -> schemas.ItemOut:
    """관리자 진행 현황 한 줄 ← AdminRun(점수는 현재 버전). 마지막 갱신 48시간 넘게 '진행중'이면 stalled."""
    now = now or datetime.datetime.now(datetime.UTC)
    archived = project.archived_at is not None
    label = STATUS_LABEL_BY_PROGRESS[run.progress]
    return schemas.ItemOut(
        **_base_item(project),
        match_status=match_status_of(run.progress),
        failure_reason=run.failure_reason if run.progress == '실패' else None,
        stage=stage_of(run.step),
        status_label=label,
        step=run.agent,
        attempts=run.attempt,
        last_updated=utc(run.updated_at),
        stalled=_stalled(label, archived, run.updated_at, now),
        score=run.total_score,
        archived=archived,
        generation_resume_count=run.resume_count,
        generation_failure_reason=run.failure_reason,
        generation_last_error_kind=run.last_error_kind,
    )


def item_from_view(project, run_view) -> schemas.ItemOut:
    """관리자 조회 범위(최근 12개월) 밖이라 admin_runs에 없는 실행 건 — 진행 상태(RunView)로만 채운다. 점수 · Agent는 없다."""
    label = STATUS_LABEL_BY_PROGRESS[run_view.progress]
    return schemas.ItemOut(
        **_base_item(project),
        match_status=match_status_of(run_view.progress),
        stage=stage_of(run_view.step),
        status_label=label,
        last_updated=project.created_at,
        archived=project.archived_at is not None,
        generation_resume_count=run_view.resume_count,
        generation_last_error_kind=run_view.last_error_kind,
    )


# ── 이력보기 (admin_score_history) ────────────────────────────────────────────────────
def _entries(entries) -> list[schemas.ScoreHistoryEntryOut]:
    return [
        schemas.ScoreHistoryEntryOut(scored_at=utc(e.scored_at), score=e.score, is_rerun=e.after_rework)
        for e in entries
    ]


def score_history_out(history) -> schemas.ItemScoreHistoryOut:
    return schemas.ItemScoreHistoryOut(
        doc=_entries(history.doc_score), code=_entries(history.code_check), plan=_entries(history.feature_match))


# ── 에이전트 테스크 (admin_executions · admin_agent_tasks) ──────────────────────────────
def _token_total(tokens) -> int:
    return (tokens.input_tokens or 0) + (tokens.output_tokens or 0)


def execution_dict(e) -> dict:
    """에이전트 테스크 탭 한 줄. 웹 표기(status · rerun_type)를 그대로 쓰고 오케스트레이터 표기는 *_ko로 덧붙인다.
    프롬프트 · 응답 원문과 output_ref는 없다(메타데이터만)."""
    return {
        'execution_id': e.execution_id,
        'run_id': e.run_id,
        'project_id': int(e.project_id) if e.project_id is not None else None,
        'task_key': e.task_id,
        'agent_name': e.agent,
        'model_used': e.model,
        'rerun_type': 'initial' if e.trigger == INITIAL_TRIGGER else 'rerun',
        'trigger': e.trigger,
        'token_usage': _token_total(e.tokens),
        'status': exec_status_to_web(e.status),
        'status_ko': e.status,
        'error_kind': e.error_kind,
        'error_reason': e.error,
        'retryable': (e.error_kind == ps.ERROR_KIND_TRANSIENT) if e.error_kind is not None else None,
        'attempt': e.attempt,
        'redo_count': e.redo_count,
        'reasoning_effort': e.reasoning_effort,
        'temperature': e.temperature,
        'started_at': utc(e.started_at).isoformat() if e.started_at else None,
        'ended_at': utc(e.ended_at).isoformat() if e.ended_at else None,
        'duration_sec': e.duration_sec,
        'tokens': {
            'input_tokens': e.tokens.input_tokens, 'cached_input_tokens': e.tokens.cached_input_tokens,
            'output_tokens': e.tokens.output_tokens, 'reasoning_tokens': e.tokens.reasoning_tokens,
        },
    }


def agent_task_out(task, descriptions: dict[int, str]) -> schemas.AgentTaskOut:
    project_id = int(task.recent_project_id) if task.recent_project_id is not None else None
    return schemas.AgentTaskOut(
        agent_name=task.agent,
        defined_task_count=task.task_count,
        total_executions=task.execution_count,
        recent_project_id=project_id,
        recent_project_description=descriptions.get(project_id) if project_id is not None else None,
        recent_status=exec_status_to_web(task.recent_status),
    )


# ── 운영 현황 (admin_summary) ─────────────────────────────────────────────────────────
def _trigger_stats(summary):
    initial = [t for t in summary.triggers if t.trigger == INITIAL_TRIGGER]
    rerun = [t for t in summary.triggers if t.trigger != INITIAL_TRIGGER]
    return initial, rerun


def _avg_tokens(stats) -> float | None:
    """계기별 평균 토큰을 실행 기록 수로 가중해 합친다. 기록이 없으면 None."""
    total = sum(t.count for t in stats)
    if not total:
        return None
    return round(sum((t.avg_tokens or 0) * t.count for t in stats) / total, 1)


def ops_summary_out(summary, status_counts: dict[str, int]) -> schemas.OpsSummaryOut:
    """운영 현황 탭. status_counts는 진행 현황 탭과 같은 표(공고 매칭 전 포함)에서 세어 넘긴다."""
    return schemas.OpsSummaryOut(
        status_counts=status_counts,
        doc_avg=summary.doc_avg, doc_count=summary.doc_count,
        total_avg=summary.total_avg, total_count=summary.total_count,
        pass_count=summary.pass_count, pass_rate=summary.pass_rate, pass_threshold=summary.pass_threshold,
        rerun_matches=summary.reworked_runs, matches_with_execution=summary.runs_with_executions,
        rerun_rate=summary.rework_rate,
        score_buckets=[schemas.ScoreBucketOut(label=b.label, count=b.count) for b in summary.score_buckets],
        deviations=[
            schemas.LayerDeviationOut(
                layer=LAYER_TO_WEB.get(c.layer, c.layer), round1_avg=c.first_avg, round2_avg=c.after_avg,
                delta_avg=c.delta, sample_count=c.count)
            for c in summary.layer_changes
        ],
        token_violation_rate=summary.proofread_reject_rate,
        token_violation_count=summary.proofread_rejected,
        token_check_count=summary.proofread_attempts,
    )


def agent_ops_summary_out(summary) -> schemas.AgentOpsSummaryOut:
    initial, rerun = _trigger_stats(summary)
    return schemas.AgentOpsSummaryOut(
        total_executions=sum(t.count for t in summary.triggers),
        initial_executions=sum(t.count for t in initial),
        rerun_executions=sum(t.count for t in rerun),
        total_tokens=summary.total_tokens,
        initial_avg_tokens=_avg_tokens(initial),
        rerun_avg_tokens=_avg_tokens(rerun),
        token_violation_rate=summary.proofread_reject_rate,
        token_violation_count=summary.proofread_rejected,
        token_check_count=summary.proofread_attempts,
    )
