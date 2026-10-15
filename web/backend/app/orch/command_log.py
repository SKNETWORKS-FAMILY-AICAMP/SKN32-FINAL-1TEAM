"""웹 명령 로그 — 웹이 오케스트레이터에 넣은 상태 변경 명령을 웹 로그 파일에 한 줄씩 남긴다 (SB-303).

워커는 운영 로그에 단계 시작 · 끝 · 대기 · 재개 예약을 남기지만, 웹 명령 처리 안에서 바로 바뀌는 실행 상태(대기 지점 중단 ·
화면 8 진행 …)는 워커를 거치지 않아 그 로그에 줄이 없다. 이 줄들이 그 빈자리를 채워, 워커 로그와 시각 · 프로젝트 번호로 맞춰
한 실행 건의 흐름을 DB를 열지 않고 따라갈 수 있게 한다(함수 명세 · 웹연동_변경사항 12.4).

한 줄 모양(web-YYYY-MM-DD.log, 기존 웹 로그와 같은 파일):
    cmd at=2026-10-06T05:57:47Z project_id=7 command=decide_for_project screen=8 action=진행 result=ok step=종합평가 progress=사용자대기 elapsed_ms=12
    cmd at=... project_id=7 command=abort_project result=ok run_action=중단 step=결과물 progress=중단 elapsed_ms=8
    cmd at=... project_id=7 command=start_writing_for_project result=error code=BUSY elapsed_ms=3

- at: UTC(Z). 워커 로그가 UTC라 맞춰 보려고 서버 로컬 시각(줄 앞 asctime)과 별개로 적는다.
- result: ok · rejected(시작 요청 거절) · confirmation_required · error(오케스트레이터 오류 코드) · fail(예상 못 한 예외).
- step · progress: 명령 직후 실행 건의 단계 · 진행 상태(읽을 수 있을 때만 — 실행 건이 없으면 생략).
- 넣지 않는 것: 계정 번호(request_start · delete_account_data의 account_id), 산출물 · 입력 내용, 요청 바디. 개인정보 제외 원칙은 요청 로그와 같다.
- 로그를 쓰다 실패해도 명령 자체에는 영향을 주지 않는다.
"""
import datetime
import logging
import time
from collections.abc import Callable
from typing import Any

from app.logging_config import web_logger

# 명령 이름 → (project_id 위치 · 이름 또는 None, 로그에 남길 인자 [(위치, 이름, 기본값)]). 읽기 함수는 남기지 않는다(양이 많고 상태를 안 바꾼다).
# 인자는 계정 번호가 아닌 것만 고른다 — request_start · delete_account_data의 첫 인자는 account_id라 일부러 뺀다.
_COMMANDS: dict[str, tuple[tuple[int, str] | None, tuple[tuple[int, str, Any], ...]]] = {
    'request_start': ((1, 'project_id'), ()),
    'more_candidates_for_project': ((0, 'project_id'), ()),
    'select_announcement_for_project': ((0, 'project_id'), ((1, 'announcement_id', None),)),
    'start_writing_for_project': ((0, 'project_id'), ()),
    'decide_for_project': ((0, 'project_id'), ((1, 'screen', None), (2, 'action', None), (3, 'confirmed', False))),
    'request_rework_for_project': ((0, 'project_id'), ((1, 'bundle', None),)),
    'abort_project': ((0, 'project_id'), ()),
    'delete_project_data': ((0, 'project_id'), ()),
    'delete_account_data': (None, ()),
}

COMMANDS = frozenset(_COMMANDS)


def _arg(args: tuple, kwargs: dict, index: int, name: str, default: Any = None) -> Any:
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _fmt(value: Any) -> str:
    text = str(value)
    return text if text and ' ' not in text else repr(text) if text else "''"


class CommandLog:
    """명령 하나가 끝날 때(성공 · 오류) 한 줄을 남긴다. state_reader가 있으면 명령 직후의 단계 · 진행 상태도 붙인다."""

    def __init__(self, state_reader: Callable[[Any], Any] | None = None, logger: logging.Logger | None = None) -> None:
        self._state_reader = state_reader  # project_id → RunView(실행 건이 없으면 run=None). 읽기 실패는 무시한다
        self._logger = logger or web_logger

    def record(self, name: str, args: tuple, kwargs: dict, started: float, *, value: Any = None,
               error: Exception | None = None, code: str | None = None) -> None:
        if name not in _COMMANDS:
            return
        try:
            self._emit(name, args, kwargs, started, value, error, code)
        except Exception:  # noqa: BLE001 - 로그 때문에 명령이 실패하면 안 된다
            pass

    def _emit(self, name, args, kwargs, started, value, error, code) -> None:
        project_spec, arg_specs = _COMMANDS[name]
        project_id = _arg(args, kwargs, *project_spec) if project_spec is not None else None
        parts = [f"cmd at={datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"]
        if project_id is not None:
            parts.append(f'project_id={project_id}')
        parts.append(f'command={name}')
        for index, arg_name, default in arg_specs:
            found = _arg(args, kwargs, index, arg_name, default)
            if found is not None:
                parts.append(f'{arg_name}={_fmt(found)}')

        level = logging.INFO
        if error is not None and code is not None:      # 오케스트레이터 오류 — 요청이 못 통과한, 예상 가능한 실패
            level = logging.WARNING
            parts.append(f'result=error code={code}')
        elif error is not None:                          # 예상 못 한 예외
            level = logging.ERROR
            parts.append(f'result=fail error_type={type(error).__name__}')
        else:
            result, extra = self._describe(name, value)
            if result != 'ok':
                level = logging.WARNING if result == 'rejected' else logging.INFO
            parts.append(f'result={result}')
            parts.extend(extra)

        if project_id is not None and self._state_reader is not None and name != 'delete_account_data':
            parts.extend(self._state(project_id))
        parts.append(f'elapsed_ms={int((time.monotonic() - started) * 1000)}')
        self._logger.log(level, ' '.join(parts))

    @staticmethod
    def _describe(name: str, value: Any) -> tuple[str, list[str]]:
        if name == 'request_start':  # 거절(동시 실행 · 필수 항목 · 프로필)은 예외가 아니라 결과로 돌아온다
            if getattr(value, 'ok', True):
                return 'ok', []
            return 'rejected', [f'code={getattr(value, "code", None)}']
        if name == 'decide_for_project':  # 확인이 필요하면 값이 돌아오고, 필요 없으면 None
            return ('confirmation_required', []) if value is not None else ('ok', [])
        if name == 'abort_project':
            action = getattr(value, 'run_action', None)
            return 'ok', [f'run_action={action}'] if action else []
        return 'ok', []

    def _state(self, project_id: Any) -> list[str]:
        try:
            run = self._state_reader(project_id).run
        except Exception:  # noqa: BLE001 - 실행 건이 없거나 지워졌으면 상태 없이 남긴다
            return []
        if run is None:
            return []
        return [f'step={_fmt(run.step)}', f'progress={_fmt(run.progress)}']
