"""실행 로그 줄 — 단계 실행 · 실행 건 사건을 표준 logging의 이름 붙은 로거(sbrain.run)에 정보 수준으로 남긴다.

- 엔진이 부른다. 범용이다 — 단계 ID와 실행 건 · 실행 기록의 값만 쓰고 S-Brain 이름을 넣지 않는다.
- 줄 모양: '<동작> 키=값 …'. 앞부분(시각 · 워커:스레드)은 처리기를 단 쪽(워커)이 붙인다. 값에 빈칸이 있으면 큰따옴표로 감싼다.
- 넣는 식별자는 실행 건 번호(run) · 웹 프로젝트 번호(project) · 실행 기록 번호(exec), 파일 삭제 줄의 대기열 줄 번호
  (deletion, 결정 0023)까지다. 계정 번호 · 산출물 내용 · 입력 · 지시문 · 프롬프트 · 응답 · 사건 설명 · 파일 이름 · 키는 넣지
  않는다. 자유 문장은 실패한 실행 기록의 error 값(최대 200자)뿐이다.
- 처리기는 워커(python -m sbrain.worker)만 단다(sbrain/worker_log.py). 웹 조립 · 테스트에서는 처리기가 없어 아무것도
  나가지 않는다(로거 수준도 기본 WARNING이라 줄을 만들지 않는다).
- 로그 쓰기 오류는 실행을 멈추지 않는다 — 여기서 난 예외는 삼킨다.
- 동작 이름 · 키 이름은 잠정이다(PROVISIONAL workerLog.actions).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..models.clock import as_utc

RUN_LOGGER = "sbrain.run"
ERROR_MAX = 200     # 단계끝 error 값 길이 상한

# 동작 이름 (잠정)
STEP_START = "단계시작"
STEP_END = "단계끝"
WAIT = "대기"
RUN_END = "실행끝"
RESUME_SCHEDULED = "재개예약"
FILE_DELETED = "파일삭제"              # 파일 삭제 대기열 (확장, 결정 0023)
FILE_DELETE_FAILED = "파일삭제실패"
FILE_DELETE_GAVE_UP = "파일삭제포기"

logger = logging.getLogger(RUN_LOGGER)
# 웹 쪽이 루트 로거를 INFO로 열어도 이 줄이 웹 로그로 새지 않게 — 위로 올려 보내지 않는다. 처리기는 워커가 단 것뿐이다
logger.propagate = False


def fmt_value(value: Any) -> str:
    """값 하나 — 없으면 '-', 줄바꿈은 빈칸으로, 빈칸 · 큰따옴표가 있으면 큰따옴표로 감싼다."""
    if value is None or value == "":
        return "-"
    text = " ".join(str(value).splitlines())
    if any(ch.isspace() for ch in text) or '"' in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def fmt_line(action: str, pairs: list[tuple[str, Any]]) -> str:
    return " ".join([action] + [f"{k}={fmt_value(v)}" for k, v in pairs])


def fmt_utc(at: datetime | None) -> str | None:
    return f"{as_utc(at):%Y-%m-%dT%H:%M:%S}Z" if at is not None else None


def _emit(action: str, pairs: list[tuple[str, Any]]) -> None:
    try:
        if logger.isEnabledFor(logging.INFO):
            logger.info("%s", fmt_line(action, pairs))
    except Exception:   # 로그 때문에 실행이 멈추지 않는다
        pass


def _sum(*values: int | None) -> int | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def step_start(run: Any, rec: Any, *, resumed: bool) -> None:
    """실행 기록 하나의 시작 (재개로 같은 기록을 이어 쓰면 resumed)."""
    _emit(STEP_START, [("run", run.run_id), ("project", run.project_id), ("step", rec.task_id),
                       ("exec", rec.execution_id), ("trigger", rec.trigger), ("resumed", "예" if resumed else "아니오"),
                       ("attempt", rec.attempt)])


def step_end(run: Any, rec: Any, sec: float | None) -> None:
    """실행 기록 하나의 끝 — 그때의 상태(성공 · 실패 · 재개대기 · 생략 …)와 걸린 시간 · 모델 · 토큰 · 오류."""
    failed = rec.status not in ("성공", "생략") and rec.error
    _emit(STEP_END, [("run", run.run_id), ("project", run.project_id), ("step", rec.task_id),
                     ("exec", rec.execution_id), ("status", rec.status),
                     ("sec", f"{sec:.1f}" if sec is not None else None), ("model", rec.model),
                     ("tokens", _sum(rec.input_tokens, rec.output_tokens)),
                     ("imageTokens", _sum(rec.image_input_tokens, rec.image_output_tokens)),
                     ("errorKind", rec.error_kind), ("error", str(rec.error)[:ERROR_MAX] if failed else None)])


def step_end_without_record(run: Any, step_id: str, sec: float | None) -> None:
    """실행 기록을 만들지 않는 단계(엔진 내부 단계 등) — 끝 줄만, 기록 값은 '-'."""
    _emit(STEP_END, [("run", run.run_id), ("project", run.project_id), ("step", step_id), ("exec", None),
                     ("status", None), ("sec", f"{sec:.1f}" if sec is not None else None), ("model", None),
                     ("tokens", None), ("imageTokens", None), ("errorKind", None), ("error", None)])


def wait(run: Any) -> None:
    """사용자 대기 지점에 멈춤 — point는 실행 상태의 단계 값 그대로."""
    _emit(WAIT, [("run", run.run_id), ("project", run.project_id), ("point", run.state.step)])


def run_end(run: Any) -> None:
    """실행 건 끝 — status는 진행 상태 값 그대로(완료 · 실패 · 중단)."""
    _emit(RUN_END, [("run", run.run_id), ("project", run.project_id), ("status", run.state.progress)])


def resume_scheduled(run: Any, kind: str | None) -> None:
    _emit(RESUME_SCHEDULED, [("run", run.run_id), ("project", run.project_id), ("at", fmt_utc(run.next_resume_at)),
                             ("errorKind", kind)])


# ── 파일 삭제 대기열 (확장, 결정 0023) — 식별자는 실행 건 · 대기열 줄 번호까지. 키 · 파일 이름 · 오류 메시지는 넣지 않는다
def file_deleted(row: Any) -> None:
    """실행 건 하나의 파일을 지웠다(대기열 줄을 지움)."""
    _emit(FILE_DELETED, [("run", row.run_id), ("deletion", row.deletion_id)])


def file_delete_failed(row: Any, error_type: str) -> None:
    """지우기 실패 — row는 실패를 적은 뒤의 줄. error는 예외 종류 이름(메시지 아님), attempts는 이번 대기 이후 실패 수."""
    _emit(FILE_DELETE_FAILED, [("run", row.run_id), ("deletion", row.deletion_id), ("errorKind", row.last_error_kind),
                               ("error", error_type), ("attempts", row.attempts)])


def file_delete_gave_up(row: Any) -> None:
    """실패가 포기 횟수에 이르러 '포기'로 바꿨다 — 관리자가 다시 시도할 때까지 워커는 가져가지 않는다."""
    _emit(FILE_DELETE_GAVE_UP, [("run", row.run_id), ("deletion", row.deletion_id), ("attempts", row.attempts)])
