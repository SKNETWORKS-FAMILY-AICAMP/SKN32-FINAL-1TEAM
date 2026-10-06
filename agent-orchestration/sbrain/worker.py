"""워커 — 시작 요청 · 진행 · 재개를 가져가 처리하는 별도 프로세스.

    python -m sbrain.worker            # 계속 돈다 (Ctrl+C · SIGTERM으로 멈춤)
    python -m sbrain.worker --once     # 한 바퀴만 돌고 끝낸다 (점검용)

- 웹 서버와 같은 공유 MySQL을 본다(웹팀 합의 2026-09-30). 웹은 요청 · 명령만 넣고, 단계는 워커가 돈다.
- 스레드마다 한 바퀴에 ① 시작 요청 ② '실행' 실행 건 ③ 재개 시각이 된 실행 건 순서로 하나씩 가져간다.
  할 일이 없으면 조회 주기만큼 쉰다. 같은 실행 건은 점유로 한 곳만 처리한다.
- ④ 작업 확인 주기(10분, 잠정)마다 한 스레드가 실행 로그 보관 기간 작업(flow/retention.py)을 돌 때인지 확인한다.
  여러 워커 중 한 대만, 마지막으로 끝까지 마친 지 24시간(잠정)이 지났을 때만 돈다(작업 점유 orch_jobs).
  도는 동안 그 스레드는 다른 일을 가져가지 않고, 하트비트가 작업 점유를 연장한다. 종료 신호면 실행 건 사이에서 멈춘다.
  이 작업의 로그는 시작 · 끝과 개수만 남긴다(실행 건 ID 없음).
- 점유자 이름은 스레드마다 다르다(호스트:프로세스:스레드). 하트비트 스레드가 처리 중인 점유를 연장한다.
- 종료 신호(SIGINT · SIGTERM)를 받으면 새 일을 가져가지 않고, 하던 단계를 끝낸 뒤 점유를 풀고 끝난다.
  남은 단계는 '실행'으로 남아 다른 워커가 이어받는다.
- 단계 밖 오류(DB 오류 등)는 기록하고, 그 실행 건의 점유를 다시 잡아 두어 점유 시간 뒤에 다시 시도하게 한다 (잠정).
- 설정: SBRAIN_DB_URL(필수), OPENAI_API_KEY(필수), SBRAIN_WORKER_POLL_SEC · SBRAIN_WORKER_THREADS ·
  SBRAIN_WORKER_LEASE_SEC(선택). 모두 환경 변수 → agent-orchestration/.env 순서로 읽는다.
- 로그는 표준 출력에 한 줄씩 — 가져간 일과 끝난 상태만. 프롬프트 · 응답 내용은 남기지 않는다.
  줄 앞의 시각은 UTC다(끝의 Z — 예: 2026-09-26 09:00:05Z).
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable

from .bootstrap import App
from .env import get_env
from .flow.retention import JOB_NAME, run_retention, start_retention
from .models.clock import utc_now

# 잠정값 (orchestrator/settings.py PROVISIONAL에도 적는다)
POLL_SEC = 1.0
THREADS = 4
LEASE_SEC = 120.0
JOB_CHECK_SEC = 600.0   # 보관 기간 작업을 돌 때인지 확인하는 주기 (10분)
JOB_KIND = "작업"        # 하트비트 대상 종류 — 주기 작업 점유 (ID 자리에는 작업 이름)


@dataclass(frozen=True)
class WorkerConfig:
    poll_sec: float = POLL_SEC       # 할 일이 없을 때 쉬는 시간
    threads: int = THREADS           # 동시에 처리하는 일 수
    lease_sec: float = LEASE_SEC     # 점유 시간 — 하트비트가 끊기면 이만큼 뒤에 다른 워커가 이어받는다 (작업 점유도 같다)
    job_check_sec: float = JOB_CHECK_SEC   # 보관 기간 작업을 돌 때인지 확인하는 주기

    @property
    def heartbeat_sec(self) -> float:
        """하트비트 주기 — 점유 시간의 1/4 (120초 → 30초, 잠정)."""
        return self.lease_sec / 4

    @classmethod
    def from_env(cls) -> WorkerConfig:
        return cls(poll_sec=float(get_env("SBRAIN_WORKER_POLL_SEC", str(POLL_SEC))),
                   threads=int(get_env("SBRAIN_WORKER_THREADS", str(THREADS))),
                   lease_sec=float(get_env("SBRAIN_WORKER_LEASE_SEC", str(LEASE_SEC))))


class Worker:
    def __init__(self, app: App, config: WorkerConfig | None = None, *,
                 log: Callable[[str], None] | None = None, name: str | None = None) -> None:
        self.app = app
        self.config = config or WorkerConfig()
        self.name = name or f"{socket.gethostname()}:{os.getpid()}"
        self._log = log or _print
        self.stopping = threading.Event()
        self._held: dict[tuple[str, str], str] = {}     # (종류, ID) → 점유자 — 하트비트 대상
        self._held_lock = threading.Lock()
        self._next_job_check = 0.0                      # 다음 작업 확인 시각 (time.monotonic)
        self._job_lock = threading.Lock()
        app.engine.stop_requested = self.stopping.is_set

    def owner(self, index: int) -> str:
        return f"{self.name}:t{index}"

    def stop(self) -> None:
        """새 일을 가져가지 않는다. 하던 단계는 끝낸다."""
        self.stopping.set()

    # ── 한 바퀴 ───────────────────────────────────────
    def run_once(self, owner: str) -> list[str]:
        """① 시작 요청 ② '실행' 실행 건 ③ 재개 시각이 된 실행 건을 하나씩 가져가 처리한다. 한 일을 돌려준다.

        ④ 작업 확인 주기가 됐으면 보관 기간 작업을 확인해 돌 때면 돈다(돌려주는 목록에는 넣지 않는다 — 로그에만).
        """
        store, lease = self.app.store, self.config.lease_sec
        steps = (
            ("시작요청", lambda: store.claim_start_request(owner, lease), self._start),
            ("진행", lambda: store.claim_ready_run(owner, lease), self._advance),
            ("재개", lambda: store.claim_due_resume(owner, lease, self.app.engine.now()), self._resume),
        )
        done = []
        for kind, claim, work in steps:
            if self.stopping.is_set():
                break
            item = claim()
            if item is not None:
                done.append(self._do(kind, item, owner, work))
        if not self.stopping.is_set() and self._job_check_due():
            self._retention(owner)
        return done

    # ── ④ 보관 기간 작업 ───────────────────────────────
    def _job_check_due(self) -> bool:
        """작업 확인 주기가 됐는지 — 이 프로세스의 스레드 중 하나만 참을 받는다."""
        with self._job_lock:
            now = time.monotonic()
            if now < self._next_job_check:
                return False
            self._next_job_check = now + self.config.job_check_sec
            return True

    def _retention(self, owner: str) -> None:
        """작업 점유를 잡으면 보관 기간 작업을 끝까지(또는 종료 신호까지) 돈다. 로그는 시작 · 끝과 개수만.

        오류는 종류만 남긴다. 실행 건 점유 경로(_do의 점유 다시 잡기)를 타지 않는다.
        """
        store, lease = self.app.store, self.config.lease_sec
        try:
            if not start_retention(store, owner, lease):
                return
        except Exception as e:
            self.log(owner, f"오류 보관 작업 시작 {type(e).__name__}")
            return
        key = (JOB_KIND, JOB_NAME)
        with self._held_lock:
            self._held[key] = owner
        self.log(owner, "보관 작업 시작")
        try:
            out = run_retention(store, owner, now=self.app.engine.now(), lease_sec=lease,
                                stop=self.stopping.is_set, log=lambda text: self.log(owner, text))
        finally:
            with self._held_lock:
                self._held.pop(key, None)
        s = out.summary
        self.log(owner, f"보관 작업 {'끝' if out.finished else '멈춤'} — 옮긴 실행 건 {s.runs} · "
                        f"지운 실행 건 {s.deleted_runs} · 옮긴 시작 요청 {s.requests} · 건너뜀 {s.skipped}")

    def _start(self, request_id: str, owner: str) -> str:
        st = self.app.orchestrator.run_start_request(request_id, owner, self.config.lease_sec)
        return st.status + (f" {st.code}" if st.code else "") + (f" run={st.run_id}" if st.run_id else "")

    def _advance(self, run_id: str, owner: str) -> str:
        return self.app.engine.advance(run_id, owner, self.config.lease_sec)

    def _resume(self, run_id: str, owner: str) -> str:
        return str(self.app.engine.resume(run_id, owner, self.config.lease_sec))

    def _do(self, kind: str, item: str, owner: str, work: Callable[[str, str], str]) -> str:
        key = (kind, item)
        with self._held_lock:
            self._held[key] = owner
        self.log(owner, f"가져감 {kind} {item}")
        try:
            result = work(item, owner)
        except Exception as e:  # 단계 밖 오류 — 기록하고 점유 시간 뒤에 다시 시도
            result = f"오류 {type(e).__name__}"
            self.log(owner, f"오류 {kind} {item}: {type(e).__name__}: {str(e)[:200]}")
            if kind != "시작요청":   # 시작 요청은 점유를 풀지 않아 만료 뒤 다시 시도된다
                self.app.store.acquire(item, owner, self.config.lease_sec)
        finally:
            with self._held_lock:
                self._held.pop(key, None)
        self.log(owner, f"끝 {kind} {item} → {result}")
        return f"{kind} {item} {result}"

    # ── 스레드 · 하트비트 ──────────────────────────────
    def loop(self, index: int) -> None:
        owner = self.owner(index)
        while not self.stopping.is_set():
            try:
                done = self.run_once(owner)
            except Exception as e:  # 가져가기 자체의 오류 (DB 연결 등)
                self.log(owner, f"오류 가져가기: {type(e).__name__}: {str(e)[:200]}")
                done = []
            if not done:
                self.stopping.wait(self.config.poll_sec)

    def heartbeat(self) -> None:
        """처리 중인 실행 건 · 시작 요청 · 주기 작업의 점유를 연장한다. 놓친 점유는 기록만 한다."""
        with self._held_lock:
            held = list(self._held.items())
        store, lease = self.app.store, self.config.lease_sec
        for (kind, item), owner in held:
            try:
                if kind == "시작요청":
                    ok = store.renew_start_request(item, owner, lease)
                elif kind == JOB_KIND:
                    ok = store.renew_job(item, owner, lease)
                else:
                    ok = store.renew(item, owner, lease)
            except Exception as e:
                ok = False
                self.log(owner, f"오류 하트비트 {kind} {item}: {type(e).__name__}")
            if not ok:
                self.log(owner, f"점유 잃음 {kind} {item}")

    def run(self) -> None:
        """스레드 풀로 돈다. stop()이 불리면 하던 단계를 끝낸 뒤 돌아온다."""
        self.log(self.name, f"시작 — 스레드 {self.config.threads}, 점유 {self.config.lease_sec:g}초, "
                            f"조회 {self.config.poll_sec:g}초")
        beating = threading.Event()

        def beat() -> None:
            while not beating.wait(self.config.heartbeat_sec):
                self.heartbeat()
        hb = threading.Thread(target=beat, name="sbrain-heartbeat", daemon=True)
        hb.start()
        try:
            with ThreadPoolExecutor(self.config.threads, thread_name_prefix="sbrain-worker") as pool:
                futures = [pool.submit(self.loop, i) for i in range(self.config.threads)]
                pending = set(futures)
                while pending:   # 짧게 나눠 기다려 신호 처리기가 돌 수 있게 한다
                    _, pending = wait(pending, timeout=0.5, return_when=FIRST_EXCEPTION)
                for f in futures:
                    f.result()
        finally:
            beating.set()
            hb.join()
        self.log(self.name, "끝")

    def log(self, who: str, text: str) -> None:
        self._log(f"{utc_now():%Y-%m-%d %H:%M:%S}Z {who} {text}")


def _print(line: str) -> None:
    print(line, flush=True)


def install_signal_handlers(worker: Worker) -> None:
    def handle(signum, _frame) -> None:
        worker.log(worker.name, f"종료 신호 {signal.Signals(signum).name} — 하던 단계를 끝내고 멈춘다")
        worker.stop()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):   # SIGBREAK는 Windows (Ctrl+Break)
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sbrain.worker", description="S-Brain 워커")
    parser.add_argument("--once", action="store_true", help="한 바퀴만 돌고 끝낸다 (점검용)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    missing = [k for k in ("SBRAIN_DB_URL", "OPENAI_API_KEY") if not get_env(k)]
    if missing:
        print(f"설정 없음: {', '.join(missing)} — 환경 변수 또는 agent-orchestration/.env에 넣는다 (.env.example 참고)",
              file=sys.stderr)
        return 2
    from .bootstrap import build_app
    worker = Worker(build_app(), WorkerConfig.from_env())
    if args.once:
        for line in worker.run_once(worker.owner(0)) or ["할 일 없음"]:
            print(line)
        return 0
    install_signal_handlers(worker)
    worker.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
