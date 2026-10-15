"""저장소 시험 도움 — 저장소 계약 테스트와 SqlStore 테스트가 함께 쓰는 실행 건 만들기.

여러 테스트가 같은 MySQL DB를 쓰므로 계정 · 실행 건 ID는 uid()로 테스트마다 새로 만든다.
"""
from __future__ import annotations

import uuid

from conftest import Clock

from sbrain.models import Run
from sbrain.models.run import make_state


def uid() -> str:
    return uuid.uuid4().hex[:12]


def new_run(clock: Clock, account: str, *, project_id: str | None = None, progress: str = "실행",
            step: str = "공고선택", **over) -> Run:
    now = clock()
    return Run(run_id=uid(), account_id=account, state=make_state(step, progress), current_phase="setup",
               settings_snapshot={"note": "test"}, updated_at=now, created_at=now, project_id=project_id, **over)
