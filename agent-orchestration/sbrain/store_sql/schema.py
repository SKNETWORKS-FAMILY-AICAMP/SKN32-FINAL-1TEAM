"""Orchestrator 테이블 정의 — DDL의 단일 원본.

- 이름은 orch_ 접두어. 조회 · 정렬에 쓰는 값은 컬럼으로, 나머지는 모델 전체를 JSON 문자열(run_json ·
  record_json · value)로 둔다.
- JSON은 MySQL JSON 형식이 아니라 문자열(LONGTEXT)로 저장한다. MySQL JSON 형식은 객체 키 순서를 바꿔
  저장하는데, 순서가 뜻을 갖는 값(check_refs · orders_by_task 등)이 메모리 저장소와 다르게 돌아오기 때문이다.
- 문자 집합 · 엔진은 웹 스키마와 같게(InnoDB · utf8mb4 · utf8mb4_bin), 시각은 DATETIME(6).
- 시각 칸에는 시간대 없는 UTC 값을 넣고, 읽으면 UTC를 붙인다(UtcDateTime). 시간대 없는 인자는 UTC로 본다.
- 1단계에서 이후 단계(시작 요청 · 워커 · 요약 값 · 토큰)가 쓸 컬럼까지 넣어 테이블 변경이 다시 생기지 않게 한다.
- 웹 projects 테이블은 외래 키 대상 표시용으로만 둔다. DDL은 ORCH_TABLES만 만든다.
- MySQL DDL 파일은 ddl.py가 만든다. 공유 DB 적용은 사용자가 한다.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import (
    CHAR, BigInteger, Boolean, Column, DateTime, Double, Engine, ForeignKey, Index, Integer, MetaData, String,
    Table, Text, TypeDecorator, UniqueConstraint, false, text,
)
from sqlalchemy.dialects import mysql

from ..models.clock import as_utc, naive_utc


class JsonText(TypeDecorator):
    """JSON 값을 문자열로 저장한다 (키 순서 · 숫자 표기를 그대로 보존)."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(mysql.LONGTEXT() if dialect.name == "mysql" else Text())

    def process_bind_param(self, value: Any, dialect) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def process_result_value(self, value: str | None, dialect) -> Any:
        return None if value is None else json.loads(value)


class UtcDateTime(TypeDecorator):
    """시각 — DB에는 시간대 없는 UTC(MySQL DATETIME(6)), 파이썬에는 시간대 있는 UTC.

    넣을 때(비교 조건의 값 포함) UTC로 바꾼 뒤 시간대를 떼고(시간대 없는 값은 UTC로 본다), 읽을 때 UTC를 붙인다.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(mysql.DATETIME(fsp=6) if dialect.name == "mysql" else DateTime())

    def process_bind_param(self, value: Any, dialect) -> Any:
        return naive_utc(value)

    def process_result_value(self, value: Any, dialect) -> Any:
        return as_utc(value)


METADATA = MetaData()

# 자동 증가 기본키 — SQLite는 INTEGER PRIMARY KEY여야 자동 증가한다
SEQ = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql").with_variant(Integer(), "sqlite")
PROJECT_ID = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")  # 웹 projects.project_id와 같은 형식
TS = UtcDateTime()
TOKENS = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
ZERO = text("0")
TABLE_ARGS: dict[str, Any] = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_bin")


def _id(name: str, comment: str, **kw: Any) -> Column:
    return Column(name, String(64), comment=comment, **kw)


def _seq() -> Column:
    return Column("seq", SEQ, primary_key=True, autoincrement=True, comment="기록 순서")


def _tokens() -> list[Column]:
    return [
        Column("input_tokens", TOKENS, comment="입력 토큰 합계 (캐시 입력 포함)"),
        Column("cached_input_tokens", TOKENS, comment="캐시 입력 토큰 합계 (입력의 일부)"),
        Column("output_tokens", TOKENS, comment="출력 토큰 합계 (추론 포함)"),
        Column("reasoning_tokens", TOKENS, comment="추론 토큰 합계 (출력의 일부)"),
    ]


# 웹 테이블 (app_schema.sql) — 외래 키 대상 표시용. 여기서 만들지 않는다.
WEB_PROJECTS = Table(
    "projects", METADATA,
    Column("project_id", PROJECT_ID, primary_key=True),
    comment="웹 테이블 — 외래 키 대상 표시용",
)

RUNS = Table(
    "orch_runs", METADATA,
    _id("run_id", "실행 건 ID (Run.runId)", primary_key=True),
    Column("account_id", String(64), nullable=False, comment="계정 (Run.accountId = 웹 users.user_id)"),
    Column("project_id", PROJECT_ID,
           ForeignKey("projects.project_id", ondelete="SET NULL", name="fk_orch_runs_project"),
           comment="사전 정보 출처 (Run.projectId, 확장). 완전 삭제되면 NULL — 실행 로그는 남긴다"),
    Column("step", String(20), nullable=False, comment="RunState.step — 단계명"),
    Column("progress", String(10), nullable=False, comment="RunState.progress — 실행 · 재개대기 · 사용자대기 · 실패 · 완료 · 중단"),
    Column("resume_step", Integer, nullable=False, comment="RunState.resumeStep — 이어하기 복귀 화면"),
    Column("current_phase", String(20), nullable=False),
    Column("announcement_id", String(320), comment="선택 공고"),
    Column("rework_screen", Integer),
    Column("current_task", String(40)),
    Column("retry_count", Integer, nullable=False, server_default=ZERO),
    Column("resume_count", Integer, nullable=False, server_default=ZERO),
    Column("next_resume_at", TS, comment="재개 예정 시각 (재개대기)"),
    Column("last_error_kind", String(10), comment="일시 · 입력 · 운영"),
    Column("failure_reason", Text, comment="실패 사유 (확장)"),
    Column("lease_owner", String(200), comment="점유자 (호스트 · 프로세스 · 스레드)"),
    Column("lease_until", TS, comment="점유 만료 시각"),
    Column("collect_until", TS, comment="재작성 요청을 모으는 시간이 끝나는 시각 (확장) — 그 전에는 워커가 가져가지 않는다"),
    Column("abort_requested", Boolean, nullable=False, server_default=false(), comment="중단 요청 — 단계 사이에서 반영"),
    Column("run_json", JsonText, nullable=False, comment="Run 전체 (기준 문서 JSON 이름)"),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("ended_at", TS),
    UniqueConstraint("project_id", name="uq_orch_runs_project"),
    Index("ix_orch_runs_account_progress", "account_id", "progress"),
    Index("ix_orch_runs_progress_lease", "progress", "lease_until"),
    Index("ix_orch_runs_progress_resume", "progress", "next_resume_at"),
    Index("ix_orch_runs_updated", "updated_at"),   # 마지막 활동 시각 — 12개월 처리 대상 · 관리자 조회 하한
    comment="실행 건 (Run) — 실행 상태의 원본. 프로젝트 1건에 최대 1건",
    **TABLE_ARGS,
)

START_REQUESTS = Table(
    "orch_start_requests", METADATA,
    _id("request_id", "시작 요청 ID", primary_key=True),
    Column("project_id", PROJECT_ID, comment="웹 projects.project_id. 테스트 · 시연용 직접 시작은 NULL"),
    Column("account_id", String(64), nullable=False),
    Column("status", String(10), nullable=False, comment="대기 · 처리중 · 완료 · 실패 · 취소"),
    Column("form_json", JsonText, comment="검사를 통과한 PreInput. 요청이 끝나면(완료 · 실패 · 취소) · 완전 삭제 때 비운다"),
    Column("result_code", String(40), comment="실패 코드 (시트 6)"),
    Column("result_message", Text, comment="안내 문구"),
    Column("result_detail", JsonText, comment="실패 상세 — 누락 항목 · 진행 중 작업 등 (확장)"),
    Column("notices", JsonText, comment="안내 목록"),
    _id("run_id", "만든 실행 건"),
    Column("cancel_requested", Boolean, nullable=False, server_default=false(), comment="처리 중 취소 요청"),
    Column("claim_count", Integer, nullable=False, server_default=ZERO, comment="워커가 가져간 횟수 (확장)"),
    Column("lease_owner", String(200)),
    Column("lease_until", TS),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("finished_at", TS),
    Index("ix_orch_start_requests_status_created", "status", "created_at"),
    Index("ix_orch_start_requests_project", "project_id"),
    Index("ix_orch_start_requests_account_status", "account_id", "status"),
    Index("ix_orch_start_requests_status_updated", "status", "updated_at"),   # 끝난 요청의 12개월 처리 대상
    comment="사전 단계 시작 요청 — 웹이 넣고 워커가 처리",
    **TABLE_ARGS,
)

ARTIFACT_VERSIONS = Table(
    "orch_artifact_versions", METADATA,
    _id("run_id", "실행 건", primary_key=True),
    Column("artifact_key", String(200), primary_key=True, comment="산출물 이름"),
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("value", JsonText, comment="산출물 내용 (JSON). 완전 삭제 때 지운다"),
    Column("producer", String(200), nullable=False, comment="만든 실행 ID 또는 user:… · orchestrator:…"),
    Column("created_at", TS, nullable=False),
    comment="산출물 버전 — 산출물 내용은 여기에만 있다",
    **TABLE_ARGS,
)

ARTIFACT_POINTERS = Table(
    "orch_artifact_pointers", METADATA,
    _id("run_id", "실행 건", primary_key=True),
    Column("artifact_key", String(200), primary_key=True),
    Column("version", Integer, nullable=False, comment="현재 버전"),
    comment="산출물 현재 버전 포인터",
    **TABLE_ARGS,
)

POINTER_EVENTS = Table(
    "orch_pointer_events", METADATA,
    _seq(),
    _id("run_id", "실행 건", nullable=False),
    Column("artifact_key", String(200), nullable=False),
    Column("from_version", Integer),
    Column("to_version", Integer, nullable=False),
    Column("reason", String(500), nullable=False),
    _id("cycle_id", "재작성 사이클"),
    Column("at", TS, nullable=False),
    Index("ix_orch_pointer_events_run", "run_id"),
    comment="포인터 이동 (되돌리기) 기록",
    **TABLE_ARGS,
)

EXECUTIONS = Table(
    "orch_executions", METADATA,
    _seq(),
    _id("execution_id", "실행 ID", nullable=False),
    _id("run_id", "실행 건", nullable=False),
    Column("project_id", PROJECT_ID, comment="관리자 조회용 (실행 건에서 복사)"),
    Column("task_id", String(40), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("trigger", String(10), nullable=False, comment="첫실행 · 재작성 · 재수행"),
    Column("bundle_id", String(500)),
    Column("agent", String(20), nullable=False),
    Column("step_kind", String(10), nullable=False, comment="task · rule · merge"),
    Column("model", String(100)),
    Column("provider", String(50)),
    Column("temperature", Double),
    Column("reasoning_effort", String(20)),
    Column("status", String(10), nullable=False, comment="실행 · 성공 · 실패 · 재개대기 · 생략"),
    Column("error_kind", String(10)),
    Column("error", Text),
    _id("cycle_id", "재작성 사이클"),
    Column("redo_count", Integer, nullable=False, server_default=ZERO),
    Column("resume_count", Integer, nullable=False, server_default=ZERO),
    *_tokens(),
    Column("created_at", TS, nullable=False),
    Column("started_at", TS),
    Column("ended_at", TS),
    Column("record_json", JsonText, nullable=False, comment="ExecutionRecord 전체 (산출물 내용 없음)"),
    UniqueConstraint("execution_id", name="uq_orch_executions_execution"),
    Index("ix_orch_executions_project_task_started", "project_id", "task_id", "started_at"),
    Index("ix_orch_executions_status_started", "status", "started_at"),
    Index("ix_orch_executions_started", "started_at"),
    Index("ix_orch_executions_run", "run_id"),
    comment="단계 실행 기록 (AttemptRef 확장) — 관리자 에이전트 테스크 조회",
    **TABLE_ARGS,
)

CALL_LOGS = Table(
    "orch_call_logs", METADATA,
    _seq(),
    _id("call_id", "호출 ID", nullable=False),
    _id("run_id", "실행 건", nullable=False),
    _id("execution_id", "실행 ID", nullable=False),
    Column("task_id", String(40), nullable=False),
    Column("agent", String(20), nullable=False),
    Column("call_type", String(20), nullable=False, comment="llm · search"),
    Column("purpose", String(200), nullable=False),
    Column("item_key", String(200), comment="T-P2 문장 ID 등"),
    Column("provider", String(50)),
    Column("model", String(100)),
    Column("temperature", Double),
    Column("reasoning_effort", String(20)),
    Column("timeout_sec", Double, nullable=False),
    Column("final_outcome", String(10), nullable=False),
    Column("error", String(10), comment="호출실패 · 응답지연 · 형식오류"),
    Column("error_kind", String(10)),
    Column("tries", JsonText, nullable=False, comment="시도별 결과 (토큰 포함)"),
    *_tokens(),
    Column("started_at", TS, comment="첫 시도 시작"),
    Column("ended_at", TS, comment="마지막 시도 끝"),
    UniqueConstraint("call_id", name="uq_orch_call_logs_call"),
    Index("ix_orch_call_logs_execution", "execution_id"),
    Index("ix_orch_call_logs_run", "run_id"),
    comment="LLM · 검색 호출 기록 — 재시도는 tries에 쌓인다. 프롬프트 · 응답 내용 없음",
    **TABLE_ARGS,
)

FEEDBACK_LINKS = Table(
    "orch_feedback_links", METADATA,
    _seq(),
    _id("feedback_id", "피드백 ID", nullable=False),
    _id("run_id", "실행 건", nullable=False),
    Column("kind", String(10), nullable=False, comment="재수행 · 재작성 · 재작성반영"),
    _id("cycle_id", "재작성 사이클"),
    _id("source_execution_id", "보낸 실행"),
    _id("target_execution_id", "받는 실행", nullable=False),
    Column("created_at", TS, nullable=False),
    Column("record_json", JsonText, nullable=False),
    Index("ix_orch_feedback_links_run", "run_id"),
    comment="검사 · 검증 피드백 전달 기록",
    **TABLE_ARGS,
)

REWORK_COMPARISONS = Table(
    "orch_rework_comparisons", METADATA,
    _seq(),
    _id("run_id", "실행 건", nullable=False),
    Column("bundle_id", String(500), nullable=False),
    _id("cycle_id", "재작성 사이클", nullable=False),
    Column("screen", Integer, nullable=False),
    Column("kept", String(2), nullable=False, comment="전 · 후"),
    Column("basis", String(20), nullable=False),
    Column("compared_at", TS, nullable=False),
    Column("record_json", JsonText, nullable=False),
    Index("ix_orch_rework_comparisons_run", "run_id"),
    comment="재작성 전후 비교 (ReworkComparison)",
    **TABLE_ARGS,
)

TRACE_EVENTS = Table(
    "orch_trace_events", METADATA,
    _seq(),
    _id("run_id", "실행 건", nullable=False),
    Column("kind", String(40), nullable=False),
    _id("execution_id", "실행 ID"),
    _id("cycle_id", "재작성 사이클"),
    Column("at", TS, nullable=False),
    Column("record_json", JsonText, nullable=False),
    Index("ix_orch_trace_events_run", "run_id"),
    comment="그 밖의 추적 사건",
    **TABLE_ARGS,
)

LOG_STATS = Table(
    "orch_log_stats", METADATA,
    _seq(),
    Column("kind", String(10), nullable=False, comment="줄 종류 — 실행 · 시작요청"),
    Column("reason", String(10), nullable=False, comment="옮긴 까닭 — 12개월 · 탈퇴"),
    Column("month", CHAR(7), nullable=False, comment="YYYY-MM (한국 날짜 기준)"),
    Column("category", String(20), comment="실행 줄만 — 카테고리"),
    Column("status", String(10), comment="실행 줄 = 진행 상태, 시작요청 줄 = 요청 상태"),
    Column("result_code", String(40), comment="시작요청 줄만 — 실패 코드"),
    Column("part", Integer, nullable=False, server_default=text("1"),
           comment="같은 실행 건에서 몇 번째로 옮긴 기록인지. 시작요청 줄은 1"),
    Column("count", Integer, nullable=False, comment="실행 줄 = 1, 시작요청 줄 = 묶음의 요청 수"),
    Column("data_json", JsonText, comment="실행 줄만 — 개수 묶음 (JSON)"),
    Column("created_at", TS, nullable=False, comment="이 줄을 쓴 시각 (UTC)"),
    Index("ix_orch_log_stats_kind_month", "kind", "month"),
    comment="실행 로그 통계 줄 (확장) — 12개월 처리 · 탈퇴로 지운 기록의 개수. 계정 · 프로젝트 · 실행 건 ID와 자유 글 없음",
    **TABLE_ARGS,
)

JOBS = Table(
    "orch_jobs", METADATA,
    Column("job_name", String(40), primary_key=True, comment="작업 이름 (log_retention 등)"),
    Column("lease_owner", String(200), comment="점유자"),
    Column("lease_until", TS, comment="점유 만료"),
    Column("last_started_at", TS, comment="마지막 시작"),
    Column("last_finished_at", TS, comment="마지막으로 끝까지 마친 시각"),
    Column("last_summary", JsonText, comment="마지막 요약 — 개수만 (JSON)"),
    comment="주기 작업 상태 (확장) — 여러 워커 중 하나만 돌게 하는 점유와 마지막 실행",
    **TABLE_ARGS,
)

# 실행 건 하나에 딸린 기록 표 — 12개월 처리 · 탈퇴 때 통계 줄로 옮기고 지운다
RECORD_TABLES: tuple[Table, ...] = (
    EXECUTIONS, CALL_LOGS, TRACE_EVENTS, FEEDBACK_LINKS, REWORK_COMPARISONS, POINTER_EVENTS,
)

ORCH_TABLES: list[Table] = [
    RUNS, START_REQUESTS, ARTIFACT_VERSIONS, ARTIFACT_POINTERS, POINTER_EVENTS,
    EXECUTIONS, CALL_LOGS, FEEDBACK_LINKS, REWORK_COMPARISONS, TRACE_EVENTS, LOG_STATS, JOBS,
]


def create_orchestrator_tables(engine: Engine) -> None:
    """Orchestrator 테이블만 만든다 (테스트 · 로컬용). 공유 DB는 sql/orchestrator_schema.sql로 사용자가 만든다."""
    METADATA.create_all(engine, tables=ORCH_TABLES)
