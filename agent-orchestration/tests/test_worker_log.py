"""워커 운영 로그 — 단계 · 실행 건 줄(sbrain.run 로거), 날짜 · 순번 파일, 폴더 잠금, 선택 삭제, 쓰기 실패.

엔진 · 흐름은 로거에 정보 수준으로만 남기고, 처리기는 워커(main)만 단다. 테스트는 처리기를 직접 달아 확인한다.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone

import pytest
from conftest import make_app, start_and_select, to_screen6, to_screen9

from sbrain import env
from sbrain.agents.stubs import StubScenario
from sbrain.orchestrator.runlog import RUN_LOGGER, fmt_value
from sbrain.orchestrator.settings import PROVISIONAL
from sbrain.worker_log import (
    LOCK_BUSY_NOTICE, MAX_BYTES, DailyLogFile, LogFolderLock, WorkerOutput, attach_run_log, delete_old_logs,
    detach_run_log, open_worker_output,
)

START_KEYS = ["run", "project", "step", "exec", "trigger", "resumed", "attempt"]
END_KEYS = ["run", "project", "step", "exec", "status", "sec", "model", "tokens", "imageTokens", "errorKind", "error"]
PAIR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')


class Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def runlog():
    """sbrain.run 로거에 목록 처리기를 단다 (테스트가 끝나면 뗀다)."""
    logger = logging.getLogger(RUN_LOGGER)
    h, level = Lines(), logger.level
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    yield h.lines
    logger.removeHandler(h)
    logger.setLevel(level)


def parse(line: str) -> tuple[str, list[str], dict[str, str]]:
    action, _, rest = line.partition(" ")
    pairs = PAIR.findall(rest)
    return action, [k for k, _ in pairs], {k: v.strip('"') for k, v in pairs}


def of(lines: list[str], action: str) -> list[dict[str, str]]:
    return [parse(x)[2] for x in lines if x.split(" ", 1)[0] == action]


class UtcClock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


# ── 단계 · 실행 건 줄 ──────────────────────────────────
def test_step_start_end_lines_and_key_order(clock, runlog):
    app = make_app(clock)
    rid = to_screen6(app)
    pid = app.store.load_run(rid).project_id
    starts, ends = of(runlog, "단계시작"), of(runlog, "단계끝")
    for line in runlog:
        action, keys, _ = parse(line)
        if action == "단계시작":
            assert keys == START_KEYS
        elif action == "단계끝":
            assert keys == END_KEYS
    recs = app.store.executions(rid)
    assert [s["exec"] for s in starts] == [r.execution_id for r in recs]               # 실행 기록마다 시작 한 줄
    assert [e["exec"] for e in ends] == [r.execution_id for r in recs]                 # · 끝 한 줄
    assert {s["run"] for s in starts} == {rid} and {s["project"] for s in starts} == {str(pid)}
    first = starts[0]
    assert (first["step"], first["trigger"], first["resumed"], first["attempt"]) == ("T-C1", "첫실행", "아니오", "1")
    end = ends[0]
    assert end["status"] == "성공" and re.fullmatch(r"\d+\.\d", end["sec"])
    assert end["errorKind"] == "-" and end["error"] == "-" and end["imageTokens"] == "-"
    tc1 = recs[0]
    assert end["model"] == (tc1.model or "-")
    assert end["tokens"] == (str((tc1.input_tokens or 0) + (tc1.output_tokens or 0))
                             if tc1.input_tokens is not None or tc1.output_tokens is not None else "-")


def test_redo_lines_carry_trigger(clock, runlog):
    app = make_app(clock, StubScenario(check_fail_times={"T-S1": 3}))
    to_screen6(app)
    triggers = [s["trigger"] for s in of(runlog, "단계시작") if s["step"] == "T-S1"]
    assert triggers == ["첫실행", "재수행", "재수행"]
    assert len([e for e in of(runlog, "단계끝") if e["step"] == "T-S1"]) == 3


def test_wait_and_run_end_lines(clock, runlog):
    app = make_app(clock)
    rid = to_screen9(app)
    app.orchestrator.decide(rid, 9, "진행")
    app.orchestrator.advance(rid)
    assert app.store.load_run(rid).state.progress == "완료"
    waits = of(runlog, "대기")
    # 엔진이 진행하다 멈춘 대기 지점만 (화면 8 → 9는 명령 창구가 바로 옮겨 엔진이 돌지 않는다)
    assert [w["point"] for w in waits] == ["공고선택", "계획서작성", "문서평가", "산출물확인"]
    assert all(list(w) == ["run", "project", "point"] for w in waits)
    assert of(runlog, "실행끝") == [{"run": rid, "project": str(app.store.load_run(rid).project_id), "status": "완료"}]
    # T-P2 전용 실행기도 실행 기록 하나당 한 쌍
    tp2 = [r.execution_id for r in app.store.executions(rid) if r.task_id == "T-P2"]
    assert [s["exec"] for s in of(runlog, "단계시작") if s["step"] == "T-P2"] == tp2
    assert [e["exec"] for e in of(runlog, "단계끝") if e["step"] == "T-P2"] == tp2


def test_resume_scheduled_and_resumed_lines(clock, runlog):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-S2", ["timeout"] * 6)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    run = app.store.load_run(rid)
    [res] = of(runlog, "재개예약")
    assert list(res) == ["run", "project", "at", "errorKind"]
    assert res["errorKind"] == "일시" and res["at"] == run.next_resume_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = [e for e in of(runlog, "단계끝") if e["step"] == "T-S2"][-1]
    assert (end["status"], end["errorKind"]) == ("재개대기", "일시") and end["error"] != "-"
    clock.advance(minutes=16)
    app.orchestrator.tick(clock.t)
    again = [s for s in of(runlog, "단계시작") if s["step"] == "T-S2"]
    assert [s["resumed"] for s in again] == ["아니오", "예"] and again[0]["exec"] == again[1]["exec"]


def test_run_failed_line(clock, runlog):
    app = make_app(clock)
    rid = start_and_select(app)
    app.llm.plan("T-C3", ["auth"] * 6)
    app.orchestrator.start_writing(rid)
    app.orchestrator.advance(rid)
    assert of(runlog, "실행끝")[-1]["status"] == "실패"
    end = [e for e in of(runlog, "단계끝") if e["step"] == "T-C3"][-1]
    assert end["status"] == "실패" and end["errorKind"] == "운영" and len(end["error"]) <= 200


def test_lines_have_no_account_id_or_content(clock, runlog):
    app = make_app(clock)
    rid = to_screen9(app)
    app.orchestrator.decide(rid, 9, "진행")
    app.orchestrator.advance(rid)
    text = "\n".join(runlog)
    assert "acc-1" not in text                                                     # 계정 번호 없음
    assert "헬스장" not in text and "김서준" not in text                            # 입력 · 신청자 정보 없음
    assert "@" not in text                                                         # 산출물 참조도 넣지 않는다
    for line in runlog:
        assert set(parse(line)[1]) <= set(END_KEYS) | {"trigger", "resumed", "attempt", "point", "at"}


def test_values_with_spaces_are_quoted():
    assert fmt_value("a b") == '"a b"' and fmt_value(None) == "-" and fmt_value("x") == "x"
    assert fmt_value('say "hi"') == '"say \\"hi\\""' and "\n" not in fmt_value("a\nb")


def test_provisional_entries_for_worker_log():
    assert {"workerLog.actions", "workerLog.maxBytes", "workerLog.lockFile"} <= set(PROVISIONAL)


# ── 처리기는 워커만 ────────────────────────────────────
def test_no_handler_outside_worker(clock, capsys):
    logger = logging.getLogger(RUN_LOGGER)
    assert logger.handlers == [] and not logger.isEnabledFor(logging.INFO)
    app = make_app(clock)
    to_screen6(app)
    out = capsys.readouterr()
    assert "단계시작" not in out.out + out.err


def test_web_assembly_emits_nothing(tmp_path, capsys):
    from sbrain.bootstrap import build_web
    from sbrain.store_sql import create_orchestrator_tables, create_sqlite_engine
    path = tmp_path / "web.db"
    create_orchestrator_tables(create_sqlite_engine(path, fast=True))
    build_web(f"sqlite:///{path.as_posix()}", profile_count=lambda a: 1)
    assert logging.getLogger(RUN_LOGGER).handlers == []
    assert capsys.readouterr().out == ""


# ── 파일 ───────────────────────────────────────────────
def T(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 10, day, hour, 0, 0, tzinfo=timezone.utc)


def test_file_name_is_utc_date_and_rolls_over_cap(tmp_path):
    clock = UtcClock(T(6))
    f = DailyLogFile(tmp_path, cap=100, clock=clock)
    line = "x" * 39                                                                # 줄 끝 포함 40바이트
    for _ in range(5):
        f.write(line)
    f.close()
    assert sorted(p.name for p in tmp_path.glob("*.log")) == ["2026-10-06.1.log", "2026-10-06.2.log", "2026-10-06.log"]
    assert (tmp_path / "2026-10-06.log").read_bytes() == (line + "\n").encode() * 2
    assert all(p.stat().st_size <= 100 for p in tmp_path.glob("*.log"))
    assert MAX_BYTES == 20 * 1024 * 1024


def test_date_change_switches_file(tmp_path):
    clock = UtcClock(T(6, 23))
    f = DailyLogFile(tmp_path, clock=clock)
    f.write("밤")
    clock.t = T(7, 0)
    f.write("아침")
    f.close()
    assert (tmp_path / "2026-10-06.log").read_text("utf-8") == "밤\n"
    assert (tmp_path / "2026-10-07.log").read_text("utf-8") == "아침\n"


def test_restart_appends_to_highest_sequence_under_cap(tmp_path):
    (tmp_path / "2026-10-06.log").write_bytes(b"a" * 100)
    (tmp_path / "2026-10-06.1.log").write_bytes(b"b\n")
    f = DailyLogFile(tmp_path, cap=100, clock=UtcClock(T(6)))
    f.write("c")
    f.close()
    assert (tmp_path / "2026-10-06.1.log").read_bytes() == b"b\nc\n"
    (tmp_path / "2026-10-06.1.log").write_bytes(b"b" * 100)                       # 가장 큰 순번이 상한이면 다음 순번
    f = DailyLogFile(tmp_path, cap=100, clock=UtcClock(T(6)))
    f.write("d")
    f.close()
    assert (tmp_path / "2026-10-06.2.log").read_bytes() == b"d\n"


def test_auto_delete_off_by_default_and_n_days(tmp_path):
    names = ["2026-09-01.log", "2026-09-01.3.log", "2026-10-03.log", "2026-10-02.log", "메모.log", "2026-13-40.log",
             "2026-09-01.txt", "worker.lock"]
    for n in names:
        (tmp_path / n).write_text("x")
    DailyLogFile(tmp_path, clock=UtcClock(T(6))).close()                            # 꺼짐 — 아무것도 지우지 않는다
    assert all((tmp_path / n).exists() for n in names)
    clock = UtcClock(T(6))
    f = DailyLogFile(tmp_path, clock=clock, keep_days=3)                            # 시작 때 지운다
    left = {p.name for p in tmp_path.iterdir()}
    assert "2026-09-01.log" not in left and "2026-09-01.3.log" not in left and "2026-10-02.log" not in left
    assert {"2026-10-03.log", "메모.log", "2026-13-40.log", "2026-09-01.txt", "worker.lock"} <= left
    clock.t = T(7)                                                                  # 날짜가 바뀌면 다시 지운다
    f.write("x")
    f.close()
    assert not (tmp_path / "2026-10-03.log").exists() and (tmp_path / "2026-10-07.log").exists()
    assert delete_old_logs(tmp_path, date(2026, 10, 8), 0) == ["2026-10-07.log"]       # 지운 파일 이름을 돌려준다


def test_second_lock_fails_and_falls_back_to_stdout(tmp_path):
    folder = tmp_path / "logs" / "new"                                              # 없으면 만든다
    first: list[str] = []
    a = open_worker_output("w1", str(folder), None, out=first.append)
    assert a.file is not None and (folder / "worker.lock").exists()
    second: list[str] = []
    b = open_worker_output("w2", str(folder), None, out=second.append)
    assert b.file is None
    assert len(second) == 1 and second[0].endswith(f"w2 {LOCK_BUSY_NOTICE}")
    b.write("화면만")
    assert second[-1] == "화면만"
    a.close()
    lock = LogFolderLock.acquire(folder)                                            # 앞 워커가 끝나면 잡힌다
    assert lock is not None
    lock.release()


def test_no_folder_means_stdout_only(tmp_path):
    out: list[str] = []
    o = open_worker_output("w", None, None, out=out.append)
    o.write("줄")
    assert o.file is None and out == ["줄"]
    assert open_worker_output("w", "", "7", out=out.append).file is None


def test_write_failure_does_not_stop_and_notices_once(tmp_path):
    out: list[str] = []
    o = open_worker_output("w", str(tmp_path), None, out=out.append)

    def broken(line: str) -> None:
        raise OSError(28, "No space left on device")
    o.file.write = broken
    for i in range(3):
        o.write(f"줄{i}")
    notices = [x for x in out if "로그 파일" in x]
    assert len(notices) == 1 and [x for x in out if x.startswith("줄")] == ["줄0", "줄1", "줄2"]
    o.close()


def test_keep_days_env_parsing(tmp_path):
    out: list[str] = []
    o = open_worker_output("w", str(tmp_path), "abc", out=out.append)
    assert o.file is not None and o.file.keep_days is None and any("SBRAIN_WORKER_LOG_KEEP_DAYS" in x for x in out)
    o.close()
    o = open_worker_output("w", str(tmp_path), "30", out=out.append)
    assert o.file.keep_days == 30
    o.close()


# ── 워커와 함께 ────────────────────────────────────────
def test_worker_writes_all_lines_to_stdout_and_file(tmp_path, monkeypatch):
    from test_worker import app_on, projects, start
    from sbrain.store_sql import create_orchestrator_tables, create_sqlite_engine
    from sbrain.worker import Worker, WorkerConfig
    from webdb import create_web_tables

    db = create_sqlite_engine(tmp_path / "w.db", fast=True)
    create_orchestrator_tables(db)
    create_web_tables(db)
    source = projects(1)
    app = app_on(db, source)
    screen: list[str] = []
    folder = tmp_path / "logs"
    output = open_worker_output("w9", str(folder), None, out=screen.append)
    w = Worker(app, WorkerConfig(), log=output.write, name="w9")
    handler = attach_run_log(w.run_log_line)
    try:
        start(app, source)
        w.run_once(w.owner(0))
    finally:
        detach_run_log(handler)
        output.close()
    assert logging.getLogger(RUN_LOGGER).handlers == []
    [log] = list(folder.glob("*.log"))
    text = log.read_text("utf-8")
    assert text == "\n".join(screen) + "\n"                                        # 화면과 같은 줄
    assert "가져감 시작요청" in text and "단계시작 run=" in text and "대기 run=" in text
    for line in text.splitlines():
        assert re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\dZ w9(:t0)? ", line), line  # 같은 앞부분
    assert " w9:t0 단계시작 " in text


def test_main_attaches_and_detaches_handlers(monkeypatch, tmp_path, capsys):
    from sbrain.store_sql import create_orchestrator_tables, create_sqlite_engine
    from sbrain.worker import main
    from webdb import create_web_tables
    db = create_sqlite_engine(tmp_path / "worker.db", fast=True)
    create_orchestrator_tables(db)
    create_web_tables(db)
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", tmp_path / "없음.env")
    monkeypatch.setenv("SBRAIN_DB_URL", f"sqlite:///{(tmp_path / 'worker.db').as_posix()}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("SBRAIN_WORKER_LOG_DIR", str(tmp_path / "logs"))
    assert main(["--once"]) == 0
    assert "할 일 없음" in capsys.readouterr().out
    assert logging.getLogger(RUN_LOGGER).handlers == []
    assert (tmp_path / "logs" / "worker.lock").exists()
