"""오케스트레이터(sbrain) 호출의 유일한 통로.

- 웹이 부를 수 있는 함수만 허용 목록으로 열고(함수 명세 1절), 사전 단계 실행 · 진행 · 재개(run_start_request ·
  advance · tick · resume)는 막는다(명세 11절).
- sbrain의 CommandError는 OrchError로 바꿔 올린다. sbrain은 gateway를 만들 때만 가져온다(지연 import) —
  테스트는 가짜 오케스트레이터로 gateway를 만들어 sbrain 없이 돈다.
- 주인 확인은 하지 않는다. 라우터가 모든 호출 앞에서 한다(명세 6절 1번).
"""
import functools
import os
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from .errors import OrchError

# 명세 1절 표의 함수. 이 밖의 이름은 WEB_NOT_ALLOWED.
ALLOWED = frozenset({
    'active_work', 'request_start', 'start_status',
    'view_project', 'project_views', 'wait_project',
    'screen', 'outputs', 'rework_result',
    'more_candidates_for_project', 'select_announcement_for_project', 'start_writing_for_project',
    'decide_for_project', 'request_rework_for_project',
    'abort_project', 'delete_project_data',
    'admin_executions', 'admin_calls', 'admin_runs', 'admin_score_history', 'admin_summary', 'admin_agent_tasks',
})


def _translate(exc: Exception) -> OrchError | None:
    if isinstance(exc, OrchError):
        return exc
    try:
        from sbrain.orchestrator.errors import CommandError
    except ImportError:
        return None
    if isinstance(exc, CommandError):
        return OrchError(exc.code, exc.detail)
    return None


class OrchGateway:
    def __init__(self, orchestrator: Any) -> None:
        self._orch = orchestrator

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith('_'):
            raise AttributeError(name)
        if name not in ALLOWED:
            raise OrchError('WEB_NOT_ALLOWED', name)
        fn = getattr(self._orch, name)

        @functools.wraps(fn)
        def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                err = _translate(exc)
                if err is None:
                    raise
                raise err from exc

        return call


def account_id_of(user_id: int) -> str:
    """오케스트레이터의 account_id는 웹 users.user_id를 문자열로 쓴다(명세 2.5절)."""
    return str(user_id)


def _default_db_url() -> str:
    """SBRAIN_DB_URL이 있으면 그 값, 없으면 웹이 쓰는 MySQL. 오케스트레이터는 SQLite를 지원하지 않는다."""
    explicit = os.environ.get('SBRAIN_DB_URL')
    if explicit:
        return explicit
    from app import database
    if database.IS_SQLITE:
        raise RuntimeError('오케스트레이터는 MySQL이 필요합니다 — DB_BACKEND=mysql로 하거나 SBRAIN_DB_URL을 설정하세요')
    return database._DATABASE_URL


def build_gateway(*, profile_count: Callable[[str], int], db_url: str | None = None) -> OrchGateway:
    """서버 시작 때 한 번 만든다. 여러 스레드에서 함께 써도 된다(상태는 DB에만 있다)."""
    from sbrain.bootstrap import build_web
    app = build_web(db_url or _default_db_url(), profile_count=profile_count)
    return OrchGateway(app.orchestrator)


_gateway: OrchGateway | None = None


def init_gateway(gateway: OrchGateway) -> None:
    global _gateway
    _gateway = gateway


def reset_gateway() -> None:
    global _gateway
    _gateway = None


def get_gateway() -> OrchGateway:
    """서버 시작에서 init_gateway를 부르지 않았으면 분명하게 실패한다."""
    if _gateway is None:
        raise RuntimeError('오케스트레이터 gateway가 초기화되지 않았습니다 — init_gateway를 먼저 부르세요')
    return _gateway


def require_gateway() -> OrchGateway:
    """라우터용 FastAPI 의존성. 준비 전(예: SQLite 개발 모드)에는 500 대신 503으로 알린다."""
    try:
        return get_gateway()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail='작업 서버가 아직 준비되지 않았어요. 잠시 뒤 다시 시도해 주세요.') from exc
