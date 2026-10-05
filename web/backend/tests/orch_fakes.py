"""오케스트레이터 가짜 구현 — gateway · 라우터 · mapping 테스트용.

sbrain의 결과 dataclass와 같은 필드를 가진 사본을 둔다(test_orch_fake_contract가 필드 일치를 확인한다).
FakeOrch는 부른 함수 이름과 인자를 calls에 쌓고, 미리 정한 값(또는 예외, 함수)을 돌려준다.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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


def make_run(**overrides: Any) -> RunView:
    base = dict(run_id='r1', step='계획서작성', progress='실행', screen_status='진행 중', resume_step=5, percent=40,
                current_label='계획서 작성')
    base.update(overrides)
    return RunView(**base)


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
