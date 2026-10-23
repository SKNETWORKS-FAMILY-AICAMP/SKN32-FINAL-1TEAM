"""Orchestrator가 쓰는 웹 테이블 (웹 스키마 app_schema.sql).

| 테이블 | Orchestrator가 하는 일 |
|---|---|
| notifications | 알림 INSERT, 실행 건 알림 조회(하나 · 여러 프로젝트 한 문장 — 한 시점 창구) |
| generation_failure_alerts | 실패 확정 알림 INSERT |
| verification_policies | 첫 행(policy_id 최솟값)을 설정 입력으로 읽기 |
| project_budget_items · project_schedule_items | 사전 정보(사업비 · 일정) 읽기만 — 읽는 일은 intake/sql_source.py가 한다. 여기에는 컬럼 목록만 둔다 |

- 이 테이블들의 아래 컬럼만 읽고 쓴다. 웹 테이블 쓰기는 notifications · generation_failure_alerts INSERT
  두 가지뿐이다(projects 진행 컬럼은 쓰지 않는다). 그 밖의 웹 테이블 · 컬럼은 건드리지 않는다.
  proofread_logs는 쓰지도 읽지도 않고, 학습 동의(users.ai_training_agreed)도 읽지 않는다 — 검수가 흐름에서
  빠졌다.
- 쓰기는 SqlStore가 단계 저장과 같은 트랜잭션에서 부른다.
- 시각은 시간대 없는 UTC로 넣고(naive_utc), 읽은 시각(웹이 UTC로 쓴 값)에는 UTC를 붙인다(모델이 붙임).
  구조를 DB에서 읽어 오므로 orch_ 테이블의 UtcDateTime 형식이 아니다 — 여기서 직접 바꾼다.
- 구조는 처음 쓸 때 DB에서 읽는다(reflection). 필요한 컬럼(WEB_COLUMNS)이 없으면 SchemaMismatch를 올린다.
  선택 컬럼(WEB_OPTIONAL_COLUMNS)은 없어도 오류가 아니고 None으로 읽는다.
  테이블마다 따로 읽어, 쓰지 않는 테이블이 없어도 다른 기능은 동작한다.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, MetaData, Table, insert, select
from sqlalchemy.exc import NoSuchTableError

from ..intake.sql_source import COLUMNS as INTAKE_COLUMNS
from ..intake.sql_source import OPTIONAL_COLUMNS as INTAKE_OPTIONAL_COLUMNS
from ..intake.sql_source import SchemaMismatch
from ..models import Notification, Run
from ..models.clock import naive_utc

WEB_COLUMNS: dict[str, list[str]] = {
    "notifications": ["notification_id", "project_id", "kind", "failure_scope", "target_step", "channel",
                      "created_at", "read_at"],
    "generation_failure_alerts": ["alert_id", "project_id", "stage", "resume_count", "last_error_kind",
                                  "failure_reason", "created_at"],
    "verification_policies": ["policy_id", "doc_weight", "code_weight", "plan_weight", "pass_threshold",
                              "rerun_cap", "rework_cap", "deviation_cap"],
    # 사업비 · 일정 — 읽기만. 목록의 원본은 intake/sql_source.py COLUMNS (없으면 SchemaMismatch)
    "project_budget_items": INTAKE_COLUMNS["budget_items"],
    "project_schedule_items": INTAKE_COLUMNS["schedule_items"],
}

# 있으면 읽고 없으면 None으로 보는 웹 컬럼 (없어도 SchemaMismatch가 아님)
# - project_budget_items.phase: 웹이 더하기로 한 컬럼
# - verification_policies.token_retry_cap: 검수 재수행 횟수 — 검수가 흐름에서 빠져 웹이 지울 수 있는 컬럼.
#   없으면 코드 기본값(redo.proofreadRedoCount)을 쓴다 (settings_source.py)
WEB_OPTIONAL_COLUMNS: dict[str, list[str]] = {
    "project_budget_items": INTAKE_OPTIONAL_COLUMNS["budget_items"],
    "verification_policies": ["token_retry_cap"],
}


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
        return [_notification(r, run_id) for r in rows]

    def notifications_by_project(self, conn: Connection, run_of: dict[int, str]) -> dict[str, list[Notification]]:
        """여러 프로젝트의 알림을 한 문장으로 (확장 — 한 시점 창구, 2026-10-20).

        run_of: project_id → 그 프로젝트의 실행 건 ID(실행 건 줄의 project_id — 프로젝트 하나에 실행 건 하나). 실행 건마다
        notifications(conn, project_id, run_id)와 같은 값 · 같은 순서(알림 ID 순)이고, 알림이 없는 실행 건은 빠진다.
        run_of를 나누는 일(IN 묶음)은 부르는 쪽이 한다.
        """
        t = self.table(conn, "notifications")
        rows = conn.execute(select(*(t.c[c] for c in WEB_COLUMNS["notifications"]))
                            .where(t.c.project_id.in_(list(run_of))).order_by(t.c.notification_id)).mappings()
        out: dict[str, list[Notification]] = {}
        for r in rows:
            run_id = run_of[r["project_id"]]
            out.setdefault(run_id, []).append(_notification(r, run_id))
        return out

    # ── 실패 알림 ─────────────────────────────────────
    def insert_failure_alert(self, conn: Connection, project_id: int, run: Run, at: datetime) -> None:
        """실패 확정 알림 한 행 — 모든 실패를 쌓고 last_error_kind로 구분한다 (잠정, 웹팀 확인 대기)."""
        t = self.table(conn, "generation_failure_alerts")
        conn.execute(insert(t).values(
            project_id=project_id, stage=run.state.step, resume_count=run.resume_count,
            last_error_kind=run.last_error_kind or "운영", failure_reason=run.failure_reason,
            created_at=naive_utc(at)))

    # ── verification_policies ────────────────────────
    def first_policy(self, conn: Connection) -> dict[str, Any] | None:
        """첫 행 (필요한 컬럼 + 선택 컬럼). 없는 선택 컬럼은 None."""
        t = self.table(conn, "verification_policies")
        optional = WEB_OPTIONAL_COLUMNS["verification_policies"]
        present = [c for c in optional if c in t.c]
        row = conn.execute(select(*(t.c[c] for c in WEB_COLUMNS["verification_policies"] + present))
                           .order_by(t.c.policy_id).limit(1)).mappings().first()
        if row is None:
            return None
        return {**{c: None for c in optional}, **dict(row)}


def _notification(r: Any, run_id: str) -> Notification:
    """웹 notifications 행 하나 → 기준 문서 Notification (runId 자리는 그 실행 건). 알림 읽기 둘이 함께 쓴다."""
    return Notification(run_id=run_id, kind=r["kind"], failure_scope=r["failure_scope"], target_step=r["target_step"],
                        channel=r["channel"], created_at=r["created_at"], read_at=r["read_at"],
                        notification_id=str(r["notification_id"]))
