"""산출물 파일 읽기 · 파일 삭제 대기열 관리자 함수 · 파일 저장소 조립 (결정 0023 · spec 4.7 · 4.8).

- read_artifact_file: 저장된 내용 · 형식(넣을 때 기록한 값), 다른 실행 건 키 · 키 규칙 위반 · 없는 파일 · sha256 불일치는
  FILE_NOT_FOUND, 실패 · 중단 실행 건 RUN_NOT_VIEWABLE, 실행 건 없음 RUN_NOT_FOUND, 저장소 설정 없음 FILE_STORE_UNAVAILABLE.
  거절 사유에 키 · 이름을 싣지 않는다.
- admin_file_deletions · admin_retry_file_deletion: 줄 모양(키 접두어 없음), 누른 관리자 기록, '대기' 줄 INVALID_STATE,
  없는 줄 FILE_DELETION_NOT_FOUND.
- 조립: 워커는 SBRAIN_ARTIFACT_ROOT 필수(없음 · 상대 경로면 시작하지 않음, 값은 메시지에 없음, 폴더를 만든다), 웹은 선택 ·
  읽기 전용(쓰기 · 지우기 거절, 폴더를 만들지 않음), 스텁 조립은 메모리.
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처). 임시 폴더는 pytest tmp_path만 쓴다. 네트워크 없음.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ARTIFACT_ROOT_KEY, Clock, make_app, start_and_select, to_screen8
from flow_helpers import pid
from store_helpers import uid
from worker_helpers import real_worker_app, worker, worker_to_screen6

from sbrain import env
from sbrain.agents.stubs import FakeLLM
from sbrain.bootstrap import artifact_root_problem, build_app, build_stub_app, build_web
from sbrain.flow.reads import AdminFileDeletion, ArtifactFile
from sbrain.intake import MemoryProjectInputSource
from sbrain.orchestrator.errors import COMMAND_ERROR_CODES, CommandError
from sbrain.orchestrator.file_deletion import MAX_ATTEMPTS, RETRY_SEC
from sbrain.orchestrator.files import FileMeta, FileStoreReadOnly, LocalFolderFileStore, MemoryFileStore, sha256_hex
from sbrain.worker import main

ROW_KEYS = {"deletionId", "runId", "status", "attempts", "lastErrorKind", "createdAt", "nextAt", "lastTriedAt",
            "gaveUpAt", "retriedBy", "retriedAt", "retryCount"}


def code_of(call) -> CommandError:
    with pytest.raises(CommandError) as e:
        call()
    return e.value


def put(files, key: str, data: bytes, media_type: str = "text/html", sha: str | None = None) -> None:
    files.write(key, data, FileMeta(name=key.rsplit("/", 1)[1], media_type=media_type, size=len(data),
                                    sha256=sha or sha256_hex(data)))


def no_env_file(monkeypatch, tmp_path) -> None:
    """개발 PC의 agent-orchestration/.env를 읽지 않게 한다."""
    monkeypatch.setattr(env, "DEFAULT_ENV_FILE", tmp_path / "없음.env")


def sqlite_url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"


# ── 웹 파일 읽기 ─────────────────────────────────────────
def test_read_returns_stored_content_and_metadata(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    p = pid(app, rid)
    out = app.orchestrator.outputs(p)
    for ref in (out.prototype.entry_file, out.infographic.image_file):
        f = app.orchestrator.read_artifact_file(p, ref.key)
        assert isinstance(f, ArtifactFile)
        assert f.data == app.engine.files.read(ref.key)
        assert (f.name, f.media_type, f.size, f.sha256) == (ref.name, ref.media_type, ref.size, ref.sha256)
        assert ref.name not in repr(f) and ref.key not in repr(f)               # repr에 이름 · 내용 없음
    assert app.orchestrator.files is app.engine.files                             # 스텁 조립은 엔진의 메모리 저장소


def test_media_type_and_name_come_from_stored_metadata(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    key = f"{rid}/e9/u9/notes.md"
    put(app.engine.files, key, b"# notes", media_type="text/markdown")
    f = app.orchestrator.read_artifact_file(pid(app, rid), key)
    assert (f.name, f.media_type, f.data, f.size) == ("notes.md", "text/markdown", b"# notes", 7)


def test_other_runs_key_bad_key_and_missing_file_are_not_found(clock):
    app = make_app(clock)
    rid = to_screen8(app, "acc-1")
    other = to_screen8(app, "acc-2")
    p = pid(app, rid)
    other_key = app.orchestrator.outputs(pid(app, other)).prototype.entry_file.key
    keys = [other_key,                                                            # 다른 프로젝트의 파일
            f"{rid}/e/u/none.html",                                               # 저장소에 없음
            f"../{rid}/e/u/index.html", f"{rid}/../x/index.html", "", rid, f"/{rid}/e/u/index.html",
            f"{rid}\\e\\u\\index.html", f"{rid}/e/u/.hidden"]                      # 키 규칙 위반
    for key in keys:
        e = code_of(lambda: app.orchestrator.read_artifact_file(p, key))
        assert e.code == "FILE_NOT_FOUND", key
        assert (key == "" or key not in str(e)) and "index.html" not in str(e)    # 사유에 키 · 이름 없음


def test_hash_mismatch_is_not_found(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    key = f"{rid}/e1/u1/index.html"
    put(app.engine.files, key, b"<html>A</html>", sha=sha256_hex(b"<html>B</html>"))   # 저장된 sha256과 내용이 다름
    e = code_of(lambda: app.orchestrator.read_artifact_file(pid(app, rid), key))
    assert e.code == "FILE_NOT_FOUND" and "index.html" not in str(e)


def test_hash_mismatch_in_local_folder_is_not_found(tmp_path):
    app = build_stub_app()
    app.engine.files = app.orchestrator.files = LocalFolderFileStore(tmp_path / "files", create=True)
    rid = start_and_select(app)
    key = f"{rid}/e1/u1/index.html"
    put(app.engine.files, key, b"<html>A</html>")
    p = pid(app, rid)
    assert app.orchestrator.read_artifact_file(p, key).data == b"<html>A</html>"
    (tmp_path / "files" / rid / "e1" / "u1" / "index.html").write_bytes(b"<html>X</html>")   # 디스크에서 바뀜
    assert code_of(lambda: app.orchestrator.read_artifact_file(p, key)).code == "FILE_NOT_FOUND"


def test_failed_aborted_and_missing_runs(clock):
    app = make_app(clock)
    rid = to_screen8(app, "acc-1")
    p = pid(app, rid)
    key = app.orchestrator.outputs(p).prototype.entry_file.key
    app.orchestrator.abort(rid, confirmed=True)                                   # 중단
    assert code_of(lambda: app.orchestrator.read_artifact_file(p, key)).code == "RUN_NOT_VIEWABLE"
    failed = start_and_select(app, "acc-2")
    app.llm.plan("T-S1", ["auth"] * 50)                                           # 영구 오류 → 실패
    app.orchestrator.start_writing(failed)
    app.orchestrator.advance(failed)
    assert app.store.load_run(failed).state.progress == "실패"
    fp = pid(app, failed)
    assert code_of(lambda: app.orchestrator.read_artifact_file(fp, f"{failed}/e/u/index.html")).code == "RUN_NOT_VIEWABLE"
    assert code_of(lambda: app.orchestrator.read_artifact_file("987654", key)).code == "RUN_NOT_FOUND"


def test_store_unavailable(clock):
    app = make_app(clock)
    rid = start_and_select(app)
    app.orchestrator.files = None
    e = code_of(lambda: app.orchestrator.read_artifact_file(pid(app, rid), f"{rid}/e/u/index.html"))
    assert e.code == "FILE_STORE_UNAVAILABLE"
    assert {"FILE_NOT_FOUND", "FILE_STORE_UNAVAILABLE", "FILE_DELETION_NOT_FOUND"} <= set(COMMAND_ERROR_CODES)


# ── 워커 조립 + 웹 조립: 같은 폴더 ─────────────────────────────
def test_web_reads_files_written_by_worker(tmp_path, db):
    app, web, _, source = real_worker_app(tmp_path)
    assert isinstance(app.engine.files, LocalFolderFileStore) and not app.engine.files.read_only
    assert app.engine.files.root == (tmp_path / "artifacts").resolve()
    rid = worker_to_screen6(app, web, source)
    web.orchestrator.decide(rid, 6, "진행")
    worker(app, lease_sec=60).run_once("w")
    assert web.store.load_run(rid).state.step == "산출물확인"
    p = web.store.load_run(rid).project_id
    ref = web.orchestrator.outputs(p).prototype.entry_file
    f = web.orchestrator.read_artifact_file(p, ref.key)
    assert f.data == app.engine.files.read(ref.key) and f.media_type == "text/html"
    assert web.engine.files is None                                               # 웹은 엔진에 저장소를 넘기지 않는다
    reader = web.orchestrator.files
    assert isinstance(reader, LocalFolderFileStore) and reader.read_only
    with pytest.raises(FileStoreReadOnly):                                        # 웹은 쓰지도 지우지도 않는다
        put(reader, f"{rid}/e/u/x.html", b"x")
    with pytest.raises(FileStoreReadOnly):
        reader.delete_prefix(f"{rid}/")
    assert app.engine.files.read(ref.key) == f.data                               # 그대로 남아 있다


def test_web_without_or_relative_root_only_read_is_unavailable(tmp_path, db, monkeypatch):
    no_env_file(monkeypatch, tmp_path)
    url = sqlite_url(tmp_path)
    source = MemoryProjectInputSource()
    for value in (None, "relative/artifacts", "artifacts"):
        if value is None:
            monkeypatch.delenv(ARTIFACT_ROOT_KEY, raising=False)
        else:
            monkeypatch.setenv(ARTIFACT_ROOT_KEY, value)
        web = build_web(url, profile_count=lambda a: 1, project_inputs=source)    # 조립은 된다
        assert web.orchestrator.files is None and web.engine.files is None
        rid = uid()
        web.store.delete_artifacts(rid)                                           # 다른 함수는 그대로 (대기열 넣기는 DB만)
        assert [r.run_id for r in web.orchestrator.admin_file_deletions() if r.run_id == rid] == [rid]
    assert not Path("relative/artifacts").exists()
    web = build_web(url, profile_count=lambda a: 1, project_inputs=source, artifact_root="rel/x")   # 인자도 같다
    assert web.orchestrator.files is None


def test_web_opens_existing_root_read_only_and_does_not_create(tmp_path, db, monkeypatch):
    root = tmp_path / "없는폴더"
    monkeypatch.setenv(ARTIFACT_ROOT_KEY, str(root))
    web = build_web(sqlite_url(tmp_path), profile_count=lambda a: 1, project_inputs=MemoryProjectInputSource())
    assert web.orchestrator.files.read_only and not root.exists()                # 폴더를 만들지 않는다
    with pytest.raises(ValueError):
        LocalFolderFileStore(root, create=True, read_only=True)


# ── 워커 조립 · 시작 ─────────────────────────────────────────
def test_build_app_requires_absolute_root_and_creates_folder(tmp_path, db, monkeypatch):
    no_env_file(monkeypatch, tmp_path)
    url = sqlite_url(tmp_path)
    monkeypatch.delenv(ARTIFACT_ROOT_KEY, raising=False)
    with pytest.raises(RuntimeError) as e:
        build_app(url, project_inputs=MemoryProjectInputSource(), llm=FakeLLM())
    assert ARTIFACT_ROOT_KEY in str(e.value) and "없음" in str(e.value)
    secret = "relative-secret-folder"
    for value in (secret, f"{secret}/x"):
        monkeypatch.setenv(ARTIFACT_ROOT_KEY, value)
        with pytest.raises(RuntimeError) as e:
            build_app(url, project_inputs=MemoryProjectInputSource(), llm=FakeLLM())
        assert "절대 경로가 아님" in str(e.value) and secret not in str(e.value)  # 값은 싣지 않는다
    assert not Path(secret).exists()
    root = tmp_path / "새" / "artifacts"
    monkeypatch.setenv(ARTIFACT_ROOT_KEY, str(root))
    app = build_app(url, project_inputs=MemoryProjectInputSource(), llm=FakeLLM())
    assert root.is_dir() and app.engine.files.root == root.resolve() and app.orchestrator.files is app.engine.files
    other = tmp_path / "인자"
    app = build_app(url, project_inputs=MemoryProjectInputSource(), llm=FakeLLM(), artifact_root=str(other))
    assert other.is_dir()
    assert artifact_root_problem(None) == "없음" and artifact_root_problem("") == "없음"
    assert artifact_root_problem("a/b") == "절대 경로가 아님" and artifact_root_problem(str(root)) is None


def test_worker_main_refuses_missing_or_relative_root(tmp_path, db, monkeypatch, capsys):
    no_env_file(monkeypatch, tmp_path)
    monkeypatch.setenv("SBRAIN_DB_URL", sqlite_url(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")                      # 할 일이 없어 호출하지 않는다
    monkeypatch.delenv(ARTIFACT_ROOT_KEY, raising=False)
    assert main(["--once"]) == 2
    assert f"설정 없음: {ARTIFACT_ROOT_KEY}" in capsys.readouterr().err
    secret = "relative-secret-root"
    monkeypatch.setenv(ARTIFACT_ROOT_KEY, secret)
    assert main(["--once"]) == 2
    err = capsys.readouterr().err
    assert "절대 경로가 아님" in err and secret not in err
    assert not Path(secret).exists()
    root = tmp_path / "artifacts-main"
    monkeypatch.setenv(ARTIFACT_ROOT_KEY, str(root))
    assert main(["--once"]) == 0 and root.is_dir()


def test_stub_app_uses_memory_store():
    app = build_stub_app()
    assert isinstance(app.engine.files, MemoryFileStore) and app.orchestrator.files is app.engine.files


# ── 관리자: 파일 삭제 대기열 ─────────────────────────────────
def give_up(app, clock: Clock, rid: str):
    row = app.store.file_deletion_for_run(rid)
    clock.t = max(clock.t, row.next_at)
    for _ in range(MAX_ATTEMPTS):
        [held] = [r for r in app.store.claim_file_deletions(1000, RETRY_SEC) if r.run_id == rid]
        row = app.store.fail_file_deletion(held.deletion_id, held.next_at, "일시", retry_sec=RETRY_SEC,
                                           max_attempts=MAX_ATTEMPTS)
        clock.advance(seconds=RETRY_SEC + 1)
    assert row.status == "포기"
    return row


def test_admin_list_and_retry(clock):
    app = make_app(clock)
    waiting, gave = uid(), uid()
    app.store.delete_artifacts(waiting)
    clock.advance(seconds=1)
    app.store.delete_artifacts(gave)
    row = give_up(app, clock, gave)
    rows = app.orchestrator.admin_file_deletions()
    assert [r.run_id for r in rows] == [gave, waiting]                            # 넣은 시각 최근 순
    assert all(isinstance(r, AdminFileDeletion) for r in rows)
    dumped = rows[0].dump()
    assert set(dumped) == ROW_KEYS and "keyPrefix" not in dumped                  # 키 접두어 없음
    assert (dumped["status"], dumped["attempts"], dumped["lastErrorKind"]) == ("포기", MAX_ATTEMPTS, "일시")
    assert [r.run_id for r in app.orchestrator.admin_file_deletions(status="포기")] == [gave]
    assert [r.run_id for r in app.orchestrator.admin_file_deletions(status="대기")] == [waiting]
    assert len(app.orchestrator.admin_file_deletions(limit=1, offset=1)) == 1
    with pytest.raises(ValueError):
        app.orchestrator.admin_file_deletions(status="완료")
    # 다시 시도 — 누른 관리자 · 시각 · 횟수를 남기고 바로 가져갈 수 있게 한다
    out = app.orchestrator.admin_retry_file_deletion(row.deletion_id, "admin-7")
    assert (out.status, out.attempts, out.retried_by, out.retry_count) == ("대기", 0, "admin-7", 1)
    assert out.retried_at is not None and out.gave_up_at is None and out.next_at <= clock.t
    stored = app.store.get_file_deletion(row.deletion_id)
    assert (stored.retried_by, stored.retry_count, stored.status) == ("admin-7", 1, "대기")
    # '대기' 줄은 INVALID_STATE, 없는 줄은 FILE_DELETION_NOT_FOUND — 사유에 ID 없음
    e = code_of(lambda: app.orchestrator.admin_retry_file_deletion(row.deletion_id, "admin-7"))
    assert e.code == "INVALID_STATE" and row.deletion_id not in str(e)
    missing = uid()
    e = code_of(lambda: app.orchestrator.admin_retry_file_deletion(missing, "admin-7"))
    assert e.code == "FILE_DELETION_NOT_FOUND" and missing not in str(e)
    assert app.store.get_file_deletion(row.deletion_id).retry_count == 1          # 거절은 아무것도 바꾸지 않는다


def test_admin_functions_work_in_web_assembly(tmp_path, db):
    web = build_web(sqlite_url(tmp_path), profile_count=lambda a: 1, project_inputs=MemoryProjectInputSource())
    rid = uid()
    web.store.delete_artifacts(rid)
    [row] = [r for r in web.orchestrator.admin_file_deletions(status="대기") if r.run_id == rid]
    e = code_of(lambda: web.orchestrator.admin_retry_file_deletion(row.deletion_id, "admin-1"))
    assert e.code == "INVALID_STATE"
