"""저장소 시험 도움 — 저장소 계약 테스트와 SqlStore 테스트가 함께 쓰는 실행 건 · 반려 시도 만들기.

여러 테스트가 같은 MySQL DB를 쓰므로 계정 · 실행 건 ID는 uid()로 테스트마다 새로 만든다.
"""
from __future__ import annotations

import uuid

from conftest import Clock

from sbrain.models import RejectedAttempt, Run
from sbrain.models.run import make_state


def uid() -> str:
    return uuid.uuid4().hex[:12]


def new_run(clock: Clock, account: str, *, project_id: str | None = None, progress: str = "실행",
            step: str = "공고선택", **over) -> Run:
    now = clock()
    return Run(run_id=uid(), account_id=account, state=make_state(step, progress), current_phase="setup",
               settings_snapshot={"note": "test"}, updated_at=now, created_at=now, project_id=project_id, **over)


def rejected(run: Run, no: int) -> RejectedAttempt:
    return RejectedAttempt(run_id=run.run_id, original_text="원문 (1억원)", corrected_text=f"반려 {no}",
                           reason="보호 토큰 검사 불통과 (빠짐 1건)", attempt_no=no, violation_type="수치·금액",
                           violation_note="빠짐: 1억원", model_version="미정")
