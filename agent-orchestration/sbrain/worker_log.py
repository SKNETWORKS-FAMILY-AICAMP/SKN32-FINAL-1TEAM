"""워커 운영 로그 출력 — 화면(표준 출력)과 폴더의 날짜 · 순번 파일. 워커(python -m sbrain.worker)만 쓴다.

- 워커가 남기는 모든 줄(가져감 · 끝남 · 보관 작업 · 오류 · 종료 신호)과 엔진 · 흐름이 로거 sbrain.run에 남긴 줄
  (orchestrator/runlog.py — 단계시작 · 단계끝 · 대기 · 실행끝 · 재개예약)을 같은 앞부분('시각Z 워커:스레드')으로 쓴다.
- 폴더: SBRAIN_WORKER_LOG_DIR (환경 변수 → agent-orchestration/.env, get_env). 비우면 화면에만 쓴다. 없으면 만든다.
- 파일 이름: UTC 날짜 YYYY-MM-DD.log. 그날 파일이 상한(20MB, 잠정)을 넘게 되면 YYYY-MM-DD.1.log, .2.log … 로 넘긴다.
  UTC 0시가 지나면 다음 줄부터 새 날짜 파일. 다시 켜면 오늘 날짜 파일 중 순번이 가장 큰 파일이 상한 미만이면 이어 쓴다.
  UTF-8, 줄 끝 '\\n'.
- 자동 삭제: 기본 꺼짐. SBRAIN_WORKER_LOG_KEEP_DAYS에 양의 정수 N을 넣으면 워커 시작 때와 날짜가 바뀔 때, 이름의 날짜가
  오늘(UTC)보다 N일 넘게 지난 로그 파일(이름 모양 YYYY-MM-DD[.n].log)만 지운다. 다른 파일은 건드리지 않는다.
- 폴더 하나에 워커 하나: 폴더 안 worker.lock을 OS 배타 잠금으로 잡는다(Windows msvcrt · 그 밖 fcntl). 프로세스가 끝나면
  OS가 푼다. 못 잡으면 안내 한 줄을 화면에 남기고 화면에만 쓴다.
- 한 프로세스의 여러 스레드는 잠금으로 한 줄씩 쓴다. 파일 쓰기에 실패해도(디스크 가득 등) 실행은 멈추지 않는다 —
  안내 한 줄을 화면에 남기고(같은 실패가 이어지는 동안 반복하지 않는다), 다음 줄부터 다시 파일에 쓰기를 시도한다.
- 상한 · 시계는 바꿔 넣을 수 있다(테스트). 폴더 경로 · 환경 변수 값은 줄에 남기지 않는다.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import IO, Callable

from .models.clock import utc_now
from .orchestrator.runlog import RUN_LOGGER

LOG_DIR_ENV = "SBRAIN_WORKER_LOG_DIR"
KEEP_DAYS_ENV = "SBRAIN_WORKER_LOG_KEEP_DAYS"

# 잠정값 (orchestrator/settings.py PROVISIONAL에도 적는다)
MAX_BYTES = 20 * 1024 * 1024   # 한 파일 상한 20MB — 넘게 되면 다음 순번 파일
LOCK_FILE = "worker.lock"
LOCK_BUSY_NOTICE = "로그 폴더를 다른 워커가 쓰고 있어 파일에 남기지 않는다"

LOG_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:\.(\d+))?\.log$")


def _log_date(name: str) -> tuple[date, int] | None:
    """로그 파일 이름 → (날짜, 순번). 이름 모양이 아니거나 없는 날짜면 None."""
    m = LOG_NAME.match(name)
    if m is None:
        return None
    try:
        day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return day, int(m.group(4) or 0)


def file_name(day: date, seq: int) -> str:
    return f"{day:%Y-%m-%d}.log" if seq == 0 else f"{day:%Y-%m-%d}.{seq}.log"


def delete_old_logs(folder: Path, today: date, keep_days: int) -> list[str]:
    """이름의 날짜가 today보다 keep_days일 넘게 지난 로그 파일을 지운다. 지운 이름(정렬)을 돌려준다. 실패한 파일은 건너뛴다."""
    removed = []
    limit = today - timedelta(days=keep_days)
    for p in Path(folder).iterdir():
        parsed = _log_date(p.name)
        if parsed is None or parsed[0] >= limit or not p.is_file():
            continue
        try:
            p.unlink()
            removed.append(p.name)
        except OSError:
            pass
    return sorted(removed)


class DailyLogFile:
    """UTC 날짜 · 순번 파일에 줄을 이어 쓴다. 처음 쓸 때 연다. 쓰기 오류는 올려 보낸다(WorkerOutput이 받는다)."""

    def __init__(self, folder: str | os.PathLike[str], *, cap: int = MAX_BYTES,
                 clock: Callable[[], datetime] = utc_now, keep_days: int | None = None) -> None:
        self.folder = Path(folder)
        self.cap = cap
        self.clock = clock
        self.keep_days = keep_days
        self._day: date | None = None
        self._seq = 0
        self._size = 0
        self._fh: IO[bytes] | None = None
        self._cleaned = clock().date()   # 마지막으로 자동 삭제를 확인한 날짜
        if keep_days is not None:   # 워커 시작 때
            delete_old_logs(self.folder, self._cleaned, keep_days)

    @property
    def path(self) -> Path | None:
        return self.folder / file_name(self._day, self._seq) if self._day is not None else None

    def _last_seq(self, day: date) -> int:
        seqs = [parsed[1] for p in self.folder.iterdir() if (parsed := _log_date(p.name)) and parsed[0] == day]
        return max(seqs, default=0)

    def _open(self, day: date, seq: int) -> None:
        self.close()
        self._day, self._seq = day, seq
        path = self.folder / file_name(day, seq)
        self._fh = open(path, "ab")
        self._size = path.stat().st_size

    def write(self, line: str) -> None:
        data = (line + "\n").encode("utf-8")
        day = self.clock().date()
        if day != self._cleaned:   # 날짜가 바뀔 때
            self._cleaned = day
            if self.keep_days is not None:
                delete_old_logs(self.folder, day, self.keep_days)
        if day != self._day:
            seq = self._last_seq(day)
            path = self.folder / file_name(day, seq)
            if path.exists() and path.stat().st_size >= self.cap:      # 다시 켤 때 — 가장 큰 순번이 상한이면 다음 순번
                seq += 1
            self._open(day, seq)
        elif self._fh is None:   # 앞선 쓰기 실패로 닫혔다 — 같은 파일을 다시 연다
            self._open(day, self._seq)
        if self._size > 0 and self._size + len(data) > self.cap:
            self._open(day, self._seq + 1)
        try:
            assert self._fh is not None
            self._fh.write(data)
            self._fh.flush()
        except Exception:
            self.close()
            raise
        self._size += len(data)

    def close(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass


class LogFolderLock:
    """폴더 안 worker.lock의 OS 배타 잠금 (기다리지 않는다). 프로세스가 끝나면 OS가 푼다."""

    def __init__(self, fh: IO[bytes]) -> None:
        self._fh = fh

    @classmethod
    def acquire(cls, folder: str | os.PathLike[str]) -> LogFolderLock | None:
        fh = open(Path(folder) / LOCK_FILE, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return None
        return cls(fh)

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            fh.close()


def _print(line: str) -> None:
    print(line, flush=True)


class WorkerOutput:
    """워커 줄을 화면에, 파일이 있으면 파일에도 쓴다. 스레드끼리 줄이 섞이지 않게 잠근다. 어떤 쓰기 오류도 올리지 않는다."""

    def __init__(self, name: str, *, out: Callable[[str], None] | None = None,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.name = name
        self.out = out or _print
        self.clock = clock
        self.file: DailyLogFile | None = None
        self.lock: LogFolderLock | None = None
        self._mutex = threading.Lock()
        self._failing = False

    def _screen(self, line: str) -> None:
        try:
            self.out(line)
        except Exception:
            pass

    def notice(self, text: str) -> None:
        """워커 자신의 안내 한 줄 (화면에만) — 워커 줄과 같은 앞부분."""
        with self._mutex:
            self._screen(f"{self.clock():%Y-%m-%d %H:%M:%S}Z {self.name} {text}")

    def write(self, line: str) -> None:
        with self._mutex:
            self._screen(line)
            if self.file is None:
                return
            try:
                self.file.write(line)
                self._failing = False
            except Exception as e:
                if not self._failing:   # 같은 실패가 이어지는 동안 한 번만
                    self._failing = True
                    self._screen(f"{self.clock():%Y-%m-%d %H:%M:%S}Z {self.name} 로그 파일 쓰기 실패 "
                                 f"{type(e).__name__} — 화면에만 쓴다 (다음 줄부터 다시 시도)")

    def close(self) -> None:
        with self._mutex:
            if self.file is not None:
                self.file.close()
                self.file = None
            if self.lock is not None:
                self.lock.release()
                self.lock = None


def _keep_days(value: str | None, output: WorkerOutput) -> int | None:
    if not value:
        return None
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n <= 0:
        output.notice(f"{KEEP_DAYS_ENV} 값이 양의 정수가 아니어서 로그 파일 자동 삭제를 끈다")
        return None
    return n


def open_worker_output(name: str, folder: str | None, keep_days: str | None, *,
                       out: Callable[[str], None] | None = None, cap: int = MAX_BYTES,
                       clock: Callable[[], datetime] = utc_now) -> WorkerOutput:
    """워커 출력을 만든다. folder가 비면 화면만. 폴더를 만들 수 없거나 잠금을 못 잡으면 안내 한 줄 뒤 화면만."""
    output = WorkerOutput(name, out=out, clock=clock)
    if not folder:
        return output
    days = _keep_days(keep_days, output)
    path = Path(folder)
    try:
        path.mkdir(parents=True, exist_ok=True)
        lock = LogFolderLock.acquire(path)
    except OSError as e:
        output.notice(f"로그 폴더를 쓸 수 없어 파일에 남기지 않는다 {type(e).__name__}")
        return output
    if lock is None:
        output.notice(LOCK_BUSY_NOTICE)
        return output
    output.lock = lock
    try:
        output.file = DailyLogFile(path, cap=cap, clock=clock, keep_days=days)
    except OSError as e:
        output.notice(f"로그 폴더를 쓸 수 없어 파일에 남기지 않는다 {type(e).__name__}")
        output.close()
    return output


class RunLogHandler(logging.Handler):
    """sbrain.run 로거의 줄을 워커 출력으로 보낸다. 쓰기 오류는 삼킨다(실행을 멈추지 않는다)."""

    def __init__(self, write: Callable[[str], None]) -> None:
        super().__init__(logging.INFO)
        self._write = write

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._write(record.getMessage())
        except Exception:
            pass


def attach_run_log(write: Callable[[str], None]) -> RunLogHandler:
    """워커만 부른다 — 로거에 처리기를 달고 정보 수준을 켠다. 루트 로거로는 올리지 않는다."""
    logger = logging.getLogger(RUN_LOGGER)
    handler = RunLogHandler(write)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return handler


def detach_run_log(handler: RunLogHandler) -> None:
    logger = logging.getLogger(RUN_LOGGER)
    logger.removeHandler(handler)
    # 다른 쪽(예: pytest)이 단 처리기는 세지 않는다 — 워커 처리기가 다 빠지면 수준을 되돌린다.
    # 위로 올리지 않는 것은 그대로 둔다(runlog — 웹 로그로 새지 않게).
    if not any(isinstance(h, RunLogHandler) for h in logger.handlers):
        logger.setLevel(logging.NOTSET)
