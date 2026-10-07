"""산출물 폴더 삭제와 고아 청소 (SB-294).

영구 삭제 · 탈퇴는 웹 행을 지운 뒤 그 프로젝트의 산출물 폴더(모든 시도)를 지운다. 휴지통(보관)은 파일을 남긴다.
지우지 못한 폴더는 고아 청소(`sweep_orphans`, scripts/sweep_artifacts.py)가 치운다.

실행:
    pytest tests/test_artifact_cleanup.py -v
"""
import json
import os
import subprocess
import sys
import time

import pytest
from orch_fakes import ProjectView, make_run

from app import artifact_store
from app.models import Project
from app.orch import OrchError

ATTEMPT_A = 'a' * 32
ATTEMPT_B = 'b' * 32


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, 'ARTIFACT_DIR', str(tmp_path))
    return tmp_path


def _create(client, description='산출물 삭제 테스트') -> int:
    r = client.post('/projects', data={'payload': json.dumps({'description': description})})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _put(store, project_id, attempt=ATTEMPT_A, filename='index.html', content='<html/>'):
    folder = store / str(project_id) / attempt
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text(content, encoding='utf-8')
    return folder / filename


def _age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


# ── 영구 삭제 ─────────────────────────────────────────────────────────────────────────
def test_permanent_delete_removes_all_attempt_folders(authed_client, db_session, store):
    pid = _create(authed_client)
    _put(store, pid, ATTEMPT_A)
    _put(store, pid, ATTEMPT_B, 'infographic.svg')

    assert authed_client.delete(f'/projects/{pid}/permanent').status_code == 204

    assert not (store / str(pid)).exists()
    assert db_session.query(Project).filter_by(project_id=pid).count() == 0


def test_permanent_delete_leaves_other_projects_files(authed_client, store):
    mine = _create(authed_client, '지울 프로젝트')
    other = _create(authed_client, '남길 프로젝트')
    _put(store, mine)
    kept = _put(store, other)

    assert authed_client.delete(f'/projects/{mine}/permanent').status_code == 204

    assert kept.is_file()


def test_permanent_delete_without_files_is_fine(authed_client, store):
    pid = _create(authed_client)

    assert authed_client.delete(f'/projects/{pid}/permanent').status_code == 204


def test_busy_permanent_delete_keeps_files(authed_client, db_session, orch, store):
    """BUSY로 멈추면 웹 행도 파일도 그대로 — 다시 누르면 그때 지워진다."""
    pid = _create(authed_client)
    kept = _put(store, pid)
    orch.responses['delete_project_data'] = OrchError('BUSY', '단계 진행 중')

    assert authed_client.delete(f'/projects/{pid}/permanent').status_code == 409
    assert kept.is_file()

    orch.responses.pop('delete_project_data')
    assert authed_client.delete(f'/projects/{pid}/permanent').status_code == 204
    assert not (store / str(pid)).exists()


def test_failed_folder_delete_does_not_fail_the_request(authed_client, db_session, store, monkeypatch):
    """파일을 못 지워도(잠김 · 권한) 삭제 요청은 성공 — 웹 행은 이미 지워졌고 남은 폴더는 고아 청소가 치운다."""
    pid = _create(authed_client)
    _put(store, pid)

    def locked(path, **_kw):
        raise PermissionError('잠김')
    monkeypatch.setattr(artifact_store.shutil, 'rmtree', locked)

    assert authed_client.delete(f'/projects/{pid}/permanent').status_code == 204
    assert db_session.query(Project).filter_by(project_id=pid).count() == 0
    assert (store / str(pid)).exists()


# ── 휴지통(보관) ──────────────────────────────────────────────────────────────────────
def test_trash_of_a_project_with_a_run_keeps_the_files(authed_client, orch, store):
    """실행 건이 있으면 보관만 하므로 산출물도 남는다(관리자 진행 현황이 계속 조회한다)."""
    orch.responses['view_project'] = lambda pid: ProjectView(str(pid), run=make_run())
    pid = _create(authed_client)
    kept = _put(store, pid)

    assert authed_client.delete(f'/projects/{pid}').status_code == 204

    assert kept.is_file()


def test_trash_of_an_unstarted_project_removes_its_folder(authed_client, store):
    pid = _create(authed_client)
    _put(store, pid)

    assert authed_client.delete(f'/projects/{pid}').status_code == 204

    assert not (store / str(pid)).exists()


# ── 탈퇴 ──────────────────────────────────────────────────────────────────────────────
def test_account_withdrawal_removes_every_project_folder_including_archived(authed_client, orch, store):
    orch.responses['view_project'] = lambda pid: ProjectView(str(pid), run=make_run())
    first = _create(authed_client, '첫 프로젝트')
    second = _create(authed_client, '둘째 프로젝트')
    authed_client.delete(f'/projects/{second}')  # 보관(archive)
    _put(store, first)
    _put(store, second, ATTEMPT_B)

    assert authed_client.delete('/auth/me').status_code == 204

    assert not (store / str(first)).exists() and not (store / str(second)).exists()


def test_account_withdrawal_leaves_other_accounts_files(login_as, store):
    other_pid = _create(login_as('other@example.com'))
    kept = _put(store, other_pid)
    mine = login_as('leaver@example.com')
    my_pid = _create(mine)
    _put(store, my_pid)

    assert mine.delete('/auth/me').status_code == 204

    assert not (store / str(my_pid)).exists()
    assert kept.is_file()


def test_busy_withdrawal_keeps_files_until_it_completes(authed_client, orch, store):
    pid = _create(authed_client)
    kept = _put(store, pid)
    orch.responses['delete_account_data'] = OrchError('BUSY', '점유 중')

    assert authed_client.delete('/auth/me').status_code == 409
    assert kept.is_file()

    orch.responses['delete_account_data'] = lambda account_id: None
    assert authed_client.delete('/auth/me').status_code == 204
    assert not (store / str(pid)).exists()


# ── 폴더 삭제 함수 ────────────────────────────────────────────────────────────────────
def test_delete_project_artifacts_reports_what_happened(store):
    _put(store, 5)

    assert artifact_store.delete_project_artifacts(5) is True
    assert artifact_store.delete_project_artifacts(5) is False  # 이미 없다


def test_delete_never_follows_a_link_out_of_the_store(store, tmp_path_factory):
    """프로젝트 폴더 안의 링크는 링크만 떼고 가리키는 바깥 파일은 지우지 않는다(Windows는 정션으로 확인)."""
    outside = tmp_path_factory.mktemp('outside')
    precious = outside / 'precious.txt'
    precious.write_text('남아야 함', encoding='utf-8')
    folder = store / '9'
    folder.mkdir()
    (folder / 'plain.txt').write_text('x', encoding='utf-8')
    link = folder / ATTEMPT_A
    try:
        if sys.platform == 'win32':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
        else:
            os.symlink(outside, link, target_is_directory=True)
    except (OSError, subprocess.CalledProcessError, NotImplementedError):
        pytest.skip('이 환경에서는 디렉터리 링크를 만들 수 없음')

    assert artifact_store.delete_project_artifacts(9) is True

    assert not folder.exists()
    assert precious.is_file()


def test_delete_project_dir_that_is_itself_a_link_removes_only_the_link(store, tmp_path_factory):
    outside = tmp_path_factory.mktemp('outside_root')
    (outside / 'precious.txt').write_text('남아야 함', encoding='utf-8')
    link = store / '11'
    try:
        if sys.platform == 'win32':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
        else:
            os.symlink(outside, link, target_is_directory=True)
    except (OSError, subprocess.CalledProcessError, NotImplementedError):
        pytest.skip('이 환경에서는 디렉터리 링크를 만들 수 없음')

    artifact_store.delete_project_artifacts(11)

    assert not os.path.lexists(link)
    assert (outside / 'precious.txt').is_file()


# ── 고아 청소 ─────────────────────────────────────────────────────────────────────────
def test_sweep_removes_only_folders_without_a_project(store):
    _put(store, 1)
    _put(store, 2)
    _put(store, 3)

    swept = artifact_store.sweep_orphans({1, 3}, min_age_seconds=0)

    assert swept == [2]
    assert (store / '1').is_dir() and (store / '3').is_dir() and not (store / '2').exists()


def test_sweep_ignores_names_that_are_not_project_numbers(store):
    (store / 'notes').mkdir()
    (store / 'readme.txt').write_text('x', encoding='utf-8')
    (store / '12abc').mkdir()
    _put(store, 4)

    swept = artifact_store.sweep_orphans(set(), min_age_seconds=0)

    assert swept == [4]
    assert (store / 'notes').is_dir() and (store / 'readme.txt').is_file() and (store / '12abc').is_dir()


def test_sweep_keeps_recently_changed_folders(store):
    fresh = _put(store, 6)
    old = _put(store, 7)
    _age(store / '7', 2 * 3600)
    _age(store / '6', 10)

    swept = artifact_store.sweep_orphans(set())  # 기본 여유 1시간

    assert swept == [7]
    assert fresh.is_file() and not old.exists()


def test_sweep_dry_run_deletes_nothing(store):
    kept = _put(store, 8)

    assert artifact_store.sweep_orphans(set(), min_age_seconds=0, dry_run=True) == [8]
    assert kept.is_file()


def test_sweep_with_missing_store_folder_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, 'ARTIFACT_DIR', str(tmp_path / 'not-created'))

    assert artifact_store.sweep_orphans(set(), min_age_seconds=0) == []


def test_sweep_script_uses_the_projects_table(authed_client, db_session, store, monkeypatch):
    """스크립트 한 번: 프로젝트가 있는 폴더(보관 포함)는 남기고, 행이 없는 폴더만 지운다."""
    import importlib.util
    import pathlib

    live = _create(authed_client)
    _put(store, live)
    _put(store, 99999)
    _age(store / '99999', 2 * 3600)
    script = pathlib.Path(__file__).resolve().parent.parent / 'scripts' / 'sweep_artifacts.py'
    spec = importlib.util.spec_from_file_location('sweep_artifacts', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'SessionLocal', lambda: db_session_factory(db_session))
    monkeypatch.setattr(sys, 'argv', ['sweep_artifacts.py'])

    assert module.main() == 0

    assert (store / str(live)).is_dir() and not (store / '99999').exists()


class db_session_factory:
    """스크립트가 session.close()를 불러도 테스트 세션이 닫히지 않게 감싼다."""

    def __init__(self, session):
        self._session = session

    def query(self, *args):
        return self._session.query(*args)

    def close(self):
        pass
