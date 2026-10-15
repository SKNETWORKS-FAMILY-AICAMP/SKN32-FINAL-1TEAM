"""POST /projects 첨부파일 개수·용량 상한 — 프론트 요청사항 3차 B-5.

지금까지는 첨부파일에 개수·크기 제한이 전혀 없어서(app/routers/projects.py
_save_attachment가 file.file.read()로 전체를 메모리에 올림), 서버 메모리·디스크가
파일 하나로도 크게 튈 수 있었다. 프론트(FileAttach)는 올리기 전에 막지만 우회 가능하므로
서버에서도 같은 값(ATTACH_MAX_FILES=5, ATTACH_MAX_MB=10)으로 막는다.
"""
import json

from app.models import Project
from app.routers.projects import ATTACH_MAX_BYTES, ATTACH_MAX_FILES


def _payload(**overrides):
    base = {
        'biz_type': '개인', 'ceo_name': '박테스트',
        'founded_at': None, 'description': '첨부파일 상한 테스트용 프로젝트',
        'team_members': [], 'pricing_items': [],
    }
    base.update(overrides)
    return base


def _small_file(name='ok.txt', size=10):
    return (name, b'x' * size, 'text/plain')


def test_more_than_max_files_rejected_with_400(authed_client, db_session):
    files = [('files', _small_file(f'f{i}.txt')) for i in range(ATTACH_MAX_FILES + 1)]
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())}, files=files)
    assert r.status_code == 400, r.text
    assert str(ATTACH_MAX_FILES) in r.json()['detail']
    assert db_session.query(Project).count() == 0, '거절됐는데 프로젝트 행이 남으면 안 됨'


def test_oversized_file_rejected_with_413_and_filename(authed_client, db_session):
    files = [('files', ('too-big.bin', b'x' * (ATTACH_MAX_BYTES + 1), 'application/octet-stream'))]
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())}, files=files)
    assert r.status_code == 413, r.text
    assert 'too-big.bin' in r.json()['detail']
    assert db_session.query(Project).count() == 0, '거절됐는데 프로젝트 행이 남으면 안 됨'


def test_oversized_file_among_others_leaves_no_orphan_attachments(authed_client, db_session, tmp_path, monkeypatch):
    """제한 안에 드는 파일들 뒤에 초과 파일이 섞여 있어도, 앞선 파일들이 디스크에
    저장된 채로 남으면 안 된다 — 검증을 전부 저장하기 전에 먼저 끝내야 한다."""
    import app.routers.projects as projects_router

    upload_dir = tmp_path / 'uploads'
    monkeypatch.setattr(projects_router, 'UPLOAD_DIR', str(upload_dir))

    files = [
        ('files', _small_file('a.txt')),
        ('files', _small_file('b.txt')),
        ('files', ('too-big.bin', b'x' * (ATTACH_MAX_BYTES + 1), 'application/octet-stream')),
    ]
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())}, files=files)
    assert r.status_code == 413, r.text
    assert db_session.query(Project).count() == 0
    assert not upload_dir.exists() or list(upload_dir.iterdir()) == [], '앞선 정상 파일들이 디스크에 남아있으면 안 됨(오카운트 방지)'


def test_within_limits_still_succeeds(authed_client, db_session):
    files = [('files', _small_file(f'ok{i}.txt')) for i in range(ATTACH_MAX_FILES)]
    r = authed_client.post('/projects', data={'payload': json.dumps(_payload())}, files=files)
    assert r.status_code == 201, r.text
    assert len(r.json()['attachments']) == ATTACH_MAX_FILES
