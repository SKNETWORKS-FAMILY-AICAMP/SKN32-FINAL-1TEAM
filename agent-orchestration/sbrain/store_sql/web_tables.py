"""Orchestrator가 쓰는 웹 테이블 (웹 스키마 app_schema.sql).

| 테이블 | Orchestrator가 하는 일 |
|---|---|
| notifications | 알림 INSERT, 실행 건 알림 조회 |
| generation_failure_alerts | 실패 확정 알림 INSERT |
| proofread_logs | 반려된 T-P2 시도 INSERT('검수 회수 문단'), 실행 건 행 조회 — 웹 스키마 변경(project_id 기준) 전제 |
| projects · companies · users | 학습 동의 확인 — projects.company_id → companies.user_id → users.ai_training_agreed 읽기만 |
| verification_policies | 첫 행(policy_id 최솟값)을 설정 입력으로 읽기 |
| project_budget_items · project_schedule_items | 사전 정보(사업비 · 일정, spec 4.3) 읽기만 — 읽는 일은 intake/sql_source.py가 한다. 여기에는 컬럼 목록만 둔다 |

- 이 테이블들의 아래 컬럼만 읽고 쓴다. 웹 테이블 쓰기는 notifications · generation_failure_alerts ·
  proofread_logs INSERT 세 가지뿐이다(projects 진행 컬럼은 쓰지 않는다). 그 밖의 웹 테이블 · 컬럼은 건드리지 않는다.
- 쓰기는 SqlStore가 단계 저장과 같은 트랜잭션에서 부른다.
- 시각은 시간대 없는 UTC로 넣고(naive_utc), 읽은 시각(웹이 UTC로 쓴 값)에는 UTC를 붙인다(모델이 붙임).
  구조를 DB에서 읽어 오므로 orch_ 테이블의 UtcDateTime 형식이 아니다 — 여기서 직접 바꾼다.
- 구조는 처음 쓸 때 DB에서 읽는다(reflection). 필요한 컬럼이 없으면 SchemaMismatch를 올린다.
  테이블마다 따로 읽어, 쓰지 않는 테이블이 없어도 다른 기능은 동작한다.
- proofread_logs만 예외: 구조가 맞지 않으면 SchemaMismatch를 올리지 않고 이유를 돌려준다(proofread_logs()).
  T-P2 단계 저장이 되돌려져 워커가 T-P2(LLM 호출)를 끝없이 다시 돌지 않게 하려는 것이다. 맞지 않는 구조는
  기억하지 않아, 웹 스키마가 바뀌면 다음 저장부터 쓴다.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, MetaData, Table, false, insert, select
from sqlalchemy.exc import DBAPIError, NoSuchTableError

from ..intake.sql_source import COLUMNS as INTAKE_COLUMNS
from ..intake.sql_source import OPTIONAL_COLUMNS as INTAKE_OPTIONAL_COLUMNS
from ..intake.sql_source import SchemaMismatch
from ..models import Notification, RejectedAttempt, Run
from ..models.clock import naive_utc


class ProofreadWriteError(RuntimeError):
    """웹 proofread_logs INSERT 실패 — 메시지에 문장 내용을 싣지 않는다 (오류 종류 · 코드만)."""

# proofread_logs에 Orchestrator가 채우는 컬럼 (웹 스키마 변경 뒤 모양 — 웹팀 확인 전 잠정)
# created_at은 DB 기본값에 맡기지 않고 단계 저장 시각(UTC)을 넣는다
PROOFREAD_WRITE = ["project_id", "original_text", "corrected_text", "reason", "attempt_no", "passed",
                   "violation_type", "violation_note", "recovery_status", "model_version", "created_at"]

WEB_COLUMNS: dict[str, list[str]] = {
    "projects": ["project_id", "company_id"],
    "companies": ["company_id", "user_id"],
    "users": ["user_id", "ai_training_agreed"],
    "notifications": ["notification_id", "project_id", "kind", "failure_scope", "target_step", "channel",
                      "created_at", "read_at"],
    "generation_failure_alerts": ["alert_id", "project_id", "stage", "resume_count", "last_error_kind",
                                  "failure_reason", "created_at"],
    "proofread_logs": PROOFREAD_WRITE,
    "verification_policies": ["policy_id", "doc_weight", "code_weight", "plan_weight", "pass_threshold",
                              "rerun_cap", "rework_cap", "deviation_cap", "token_retry_cap"],
    # 사업비 · 일정 (spec 4.3) — 읽기만. 목록의 원본은 intake/sql_source.py COLUMNS (없으면 SchemaMismatch)
    "project_budget_items": INTAKE_COLUMNS["budget_items"],
    "project_schedule_items": INTAKE_COLUMNS["schedule_items"],
}

# 있으면 읽고 없으면 None으로 보는 웹 컬럼 (없어도 SchemaMismatch가 아님) — phase는 웹이 더하기로 한 컬럼 (spec 4.3)
WEB_OPTIONAL_COLUMNS: dict[str, list[str]] = {
    "project_budget_items": INTAKE_OPTIONAL_COLUMNS["budget_items"],
}

RECOVERY_PENDING = "pending"   # '검수 회수 문단' 탭 라벨링 전


class WebTables:
    def __init__(self) -> None:
        self._tables: dict[str, Table] = {}
        self._lock = threading.Lock()

    def table(self, conn: Connection, name: str) -> Table:
        """테이블 구조 (처음 한 번 DB에서 읽는다). 진행 중인 트랜잭션의 연결로 읽는다."""
        with self._lock:
            if name not in self._tables:
                try:
                    table = Table(name, MetaData(), autoload_with=conn)
                except NoSuchTableError:  # 접속 오류 등은 그대로 올린다
                    raise SchemaMismatch(f"웹 DB에 {name} 테이블이 없음") from None
                lacking = [c for c in WEB_COLUMNS[name] if c not in table.c]
                if lacking:
                    raise SchemaMismatch(f"웹 DB {name}: 컬럼 없음 {lacking}")
                if name == "proofread_logs":
                    unfilled = _unfilled_required(table, PROOFREAD_WRITE)
                    if unfilled:
                        raise SchemaMismatch(f"웹 DB {name}: 채우지 않는 필수 컬럼 {unfilled}")
                self._tables[name] = table
            return self._tables[name]

    # ── notifications ────────────────────────────────
    def insert_notifications(self, conn: Connection, project_id: int, items: list[Notification]) -> None:
        """기준 문서 Notification의 runId 자리에 project_id를 쓴다. notification_id는 DB가 정한다."""
        t = self.table(conn, "notifications")
        conn.execute(insert(t), [
            dict(project_id=project_id, kind=n.kind, failure_scope=n.failure_scope, target_step=n.target_step,
                 channel=n.channel, created_at=naive_utc(n.created_at), read_at=naive_utc(n.read_at))
            for n in items])

    def notifications(self, conn: Connection, project_id: int, run_id: str) -> list[Notification]:
        t = self.table(conn, "notifications")
        rows = conn.execute(select(*(t.c[c] for c in WEB_COLUMNS["notifications"]))
                            .where(t.c.project_id == project_id).order_by(t.c.notification_id)).mappings()
        return [Notification(run_id=run_id, kind=r["kind"], failure_scope=r["failure_scope"],
                             target_step=r["target_step"], channel=r["channel"], created_at=r["created_at"],
                             read_at=r["read_at"], notification_id=str(r["notification_id"])) for r in rows]

    # ── 실패 알림 ─────────────────────────────────────
    def insert_failure_alert(self, conn: Connection, project_id: int, run: Run, at: datetime) -> None:
        """실패 확정 알림 한 행 — 모든 실패를 쌓고 last_error_kind로 구분한다 (잠정, 웹팀 확인 대기)."""
        t = self.table(conn, "generation_failure_alerts")
        conn.execute(insert(t).values(
            project_id=project_id, stage=run.state.step, resume_count=run.resume_count,
            last_error_kind=run.last_error_kind or "운영", failure_reason=run.failure_reason,
            created_at=naive_utc(at)))

    # ── 학습 동의 ─────────────────────────────────────
    def training_agreed(self, conn: Connection, project_id: int) -> bool:
        """프로젝트 주인 계정이 지금 학습 데이터 편입에 동의했는지 (projects → companies → users). 행이 없으면 False."""
        p, c, u = self.table(conn, "projects"), self.table(conn, "companies"), self.table(conn, "users")
        agreed = conn.execute(
            select(u.c.ai_training_agreed)
            .select_from(p.join(c, c.c.company_id == p.c.company_id).join(u, u.c.user_id == c.c.user_id))
            .where(p.c.project_id == project_id)).scalar()
        return bool(agreed)

    # ── proofread_logs (검수 회수 문단) ──────────────────
    def proofread_logs(self, conn: Connection) -> tuple[Table | None, str]:
        """쓸 수 있으면 (표, ""), 구조가 맞지 않으면 (None, 이유). SchemaMismatch를 올리지 않는다."""
        try:
            return self.table(conn, "proofread_logs"), ""
        except SchemaMismatch as e:
            return None, str(e)

    def insert_rejected_attempts(self, conn: Connection, table: Table, project_id: int,
                                 items: list[RejectedAttempt], at: datetime) -> None:
        """반려된 시도마다 한 행 — passed=FALSE, recovery_status='pending', created_at = 저장 시각 at(시간대 없는 UTC).
        나머지 컬럼은 웹 기본값.

        DB 오류는 오류 코드만 남긴 예외로 바꿔 올린다 — 원래 메시지의 SQL 인자 · 값에 문장 내용이 들어 있다.
        """
        try:
            conn.execute(insert(table), [
                dict(project_id=project_id, original_text=a.original_text, corrected_text=a.corrected_text,
                     reason=a.reason, attempt_no=a.attempt_no, passed=False, violation_type=a.violation_type,
                     violation_note=a.violation_note, recovery_status=RECOVERY_PENDING,
                     model_version=a.model_version, created_at=naive_utc(at))
                for a in items])
        except DBAPIError as e:
            code = e.orig.args[0] if e.orig is not None and e.orig.args else None
            raise ProofreadWriteError(f"웹 DB proofread_logs 쓰기 실패: {type(e.orig).__name__} {code}") from None

    def rejected_attempts(self, conn: Connection, project_id: int, run_id: str) -> list[RejectedAttempt]:
        table, _ = self.proofread_logs(conn)
        if table is None:
            return []
        rows = conn.execute(select(*(table.c[c] for c in PROOFREAD_WRITE))
                            .where(table.c.project_id == project_id, table.c.passed == false())
                            .order_by(*table.primary_key.columns)).mappings()
        return [RejectedAttempt(run_id=run_id, original_text=r["original_text"], corrected_text=r["corrected_text"],
                                reason=r["reason"] or "", attempt_no=r["attempt_no"],
                                violation_type=r["violation_type"], violation_note=r["violation_note"] or "",
                                model_version=r["model_version"]) for r in rows]

    # ── verification_policies ────────────────────────
    def first_policy(self, conn: Connection) -> dict[str, Any] | None:
        t = self.table(conn, "verification_policies")
        row = conn.execute(select(*(t.c[c] for c in WEB_COLUMNS["verification_policies"]))
                           .order_by(t.c.policy_id).limit(1)).mappings().first()
        return dict(row) if row is not None else None


def _unfilled_required(table: Table, filled: list[str]) -> list[str]:
    """채우지 않는데 NULL을 받지 않고 기본값도 없는 컬럼 (기본키 제외) — INSERT가 실패한다 (잠정)."""
    return [c.name for c in table.columns
            if c.name not in filled and not c.primary_key and not c.nullable
            and c.server_default is None and c.default is None]
