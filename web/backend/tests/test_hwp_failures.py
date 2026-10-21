import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app import hwp_export as hwp
from tests.test_hwp_table_layout import _data


def test_rhwp_command_has_timeout_and_preserves_success(monkeypatch):
    seen = {}

    def run(args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='ok')

    monkeypatch.setattr(hwp.subprocess, 'run', run)
    assert hwp._run_rhwp(['inspect']) == 'ok'
    assert seen['timeout'] == hwp.RHWP_TIMEOUT_SECONDS


def test_real_stuck_child_is_terminated_on_timeout(monkeypatch):
    monkeypatch.setattr(hwp, 'RHWP_BIN', sys.executable)
    monkeypatch.setattr(hwp, 'RHWP_TIMEOUT_SECONDS', 0.1)
    start = time.monotonic()
    with pytest.raises(hwp.HwpConversionTimeout) as exc:
        hwp._run_rhwp(['-c', 'import time; time.sleep(4)'])
    assert isinstance(exc.value.__cause__, subprocess.TimeoutExpired)
    assert time.monotonic() - start < 3


@pytest.mark.parametrize('stage', ['prepare', 'run'])
def test_failed_export_closes_handles_and_removes_all_temporary_files(monkeypatch, tmp_path, stage):
    allocated = []
    original_mkstemp = hwp.tempfile.mkstemp

    def allocate(suffix):
        fd, path = original_mkstemp(suffix=suffix, dir=tmp_path)
        allocated.append((fd, path))
        return fd, path

    def fail(*args, **kwargs):
        raise RuntimeError('original conversion error')

    monkeypatch.setattr(hwp.tempfile, 'mkstemp', allocate)
    monkeypatch.setattr(hwp, '_prepare_tables', fail if stage == 'prepare' else lambda path, *a: path)
    monkeypatch.setattr(hwp, '_run_rhwp', fail)
    with pytest.raises(RuntimeError, match='original conversion error'):
        hwp.render_plan_hwp(_data(), 'preliminary')
    assert allocated
    assert not list(tmp_path.iterdir())
    for fd, _path in allocated:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_cleanup_error_does_not_hide_original_failure(monkeypatch, tmp_path, caplog):
    original_mkstemp = hwp.tempfile.mkstemp
    original_remove = hwp.os.remove
    files = []

    def allocate(suffix):
        fd, path = original_mkstemp(suffix=suffix, dir=tmp_path)
        files.append(path)
        return fd, path

    def fail(*args, **kwargs):
        raise RuntimeError('original conversion error')

    def denied(path):
        if path in files:
            raise PermissionError('simulated cleanup failure')
        original_remove(path)

    monkeypatch.setattr(hwp.tempfile, 'mkstemp', allocate)
    monkeypatch.setattr(hwp, '_prepare_tables', fail)
    monkeypatch.setattr(hwp.os, 'remove', denied)
    try:
        with pytest.raises(RuntimeError, match='original conversion error'):
            hwp.render_plan_hwp(_data(), 'preliminary')
        assert 'HWP 임시 파일 정리 실패' in caplog.text
    finally:
        for path in files:
            original_remove(path)


def test_download_timeout_returns_structured_504(authed_client, monkeypatch):
    from tests.test_plan_document_endpoint import _payload

    created = authed_client.post('/projects', data={'payload': json.dumps(_payload())})
    assert created.status_code == 201

    def timeout(*args, **kwargs):
        raise hwp.HwpConversionTimeout('conversion timed out')

    monkeypatch.setattr(hwp, 'render_plan_hwp', timeout)
    response = authed_client.get(f"/projects/{created.json()['project_id']}/plan-document.hwp")
    assert response.status_code == 504
    assert response.json()['code'] == 'HWP_CONVERSION_TIMEOUT'


def test_successful_export_removes_temporary_files(monkeypatch, tmp_path):
    original_mkstemp = hwp.tempfile.mkstemp
    files = []

    def allocate(suffix):
        fd, path = original_mkstemp(suffix=suffix, dir=tmp_path)
        files.append(path)
        return fd, path

    def command(args):
        if args[0] == 'run':
            with open(args[1], encoding='utf-8') as plan_file:
                output = json.load(plan_file)['output']
        else:
            output = args[args.index('-o') + 1]
        with open(output, 'wb') as output_file:
            output_file.write(b'converted-hwp')
        return ''

    monkeypatch.setattr(hwp.tempfile, 'mkstemp', allocate)
    monkeypatch.setattr(hwp, '_prepare_tables', lambda path, *a: path)
    monkeypatch.setattr(hwp, '_run_rhwp', command)
    for name in ('_write_cell_lines', '_write_body_sections', '_shape_paragraphs', '_fit_layout'):
        monkeypatch.setattr(hwp, name, lambda path, *args: path)
    assert hwp.render_plan_hwp(_data(), 'preliminary') == b'converted-hwp'
    assert files and not list(tmp_path.iterdir())
