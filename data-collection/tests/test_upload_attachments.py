"""9단계 첨부 원본 올리기(collect/upload_attachments.py) — 공용 DB 없이 임시 폴더·가짜 연결로 확인한다.

이미 있는 해시 건너뛰기, 해시 이름이 아닌 파일 무시, 상한 파일(내용 ≠ 이름) 올리지 않기, 커밋 단위.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from collect import upload_attachments as up


class FakeCursor(object):
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if sql.startswith('INSERT'):
            self.db.inserted.append(params)

    def fetchall(self):
        return [(h,) for h in self.db.remote]


class FakeConnection(object):
    def __init__(self, remote=()):
        self.remote, self.inserted, self.commits, self.closed = set(remote), [], 0, False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # local_files 의 기본 폴더는 정의할 때 묶이므로 함수 자체를 임시 폴더 쪽으로 돌린다
        original = up.local_files
        patcher = patch.object(up, 'local_files', lambda root=None: original(root or self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def put(self, data, ext='pdf', name=None):
        sha = hashlib.sha256(data).hexdigest()
        folder = os.path.join(self.tmp.name, sha[:2])
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, (name or sha) + '.' + ext), 'wb') as f:
            f.write(data)
        return sha


class LocalFilesTests(Base):
    def test_hash_named_files_only(self):
        sha = self.put(b'pdf body', 'PDF')
        self.put(b'x', 'txt', name='readme')
        out = up.local_files(self.tmp.name)
        self.assertEqual(list(out), [sha])
        path, ext, size = out[sha]
        self.assertEqual((ext, size), ('pdf', 8))       # 확장자는 소문자로

    def test_empty_folder(self):
        self.assertEqual(up.local_files(os.path.join(self.tmp.name, 'none')), {})


class RunTests(Base):
    def test_no_files_is_error(self):
        out = up.run(connection=FakeConnection(), say=lambda *_: None)
        self.assertEqual(out['error'], 'no_local_files')

    def test_skips_hashes_already_in_db(self):
        a = self.put(b'first file', 'pdf')
        b = self.put(b'second file', 'hwp')
        db = FakeConnection(remote={a})
        out = up.run(connection=db, say=lambda *_: None)
        self.assertEqual(out['uploaded'], 1)
        self.assertEqual(len(db.inserted), 1)
        sha, size, ext, blob = db.inserted[0]
        self.assertEqual((sha, size, ext, blob), (b, len(b'second file'), 'hwp', b'second file'))
        self.assertEqual(db.commits, 1)
        self.assertFalse(db.closed)

    def test_plan_only_does_not_insert(self):
        self.put(b'one')
        self.put(b'two')
        db = FakeConnection()
        out = up.run(plan_only=True, connection=db, say=lambda *_: None)
        self.assertEqual((out['local'], out['remote'], out['todo'], out['uploaded']), (2, 0, 2, 0))
        self.assertEqual(db.inserted, [])

    def test_corrupt_file_not_uploaded(self):
        good = self.put(b'good')
        fake_name = hashlib.sha256(b'original').hexdigest()
        self.put(b'changed later', 'pdf', name=fake_name)      # 이름은 다른 내용의 해시
        db = FakeConnection()
        out = up.run(connection=db, say=lambda *_: None)
        self.assertEqual(out['uploaded'], 1)
        self.assertEqual(out['hash_mismatch'], 1)
        self.assertEqual([p[0] for p in db.inserted], [good])

    def test_limit_and_commit_chunks(self):
        for i in range(5):
            self.put(('file %d' % i).encode() * 10)
        db = FakeConnection()
        with patch.object(up, 'COMMIT_BYTES', 100):
            out = up.run(limit=3, connection=db, say=lambda *_: None)
        self.assertEqual(out['uploaded'], 3)
        self.assertEqual(db.commits, 2)          # 60바이트 둘째 파일에서 100 넘음 → 한 번 + 마지막 한 번

    def test_own_connection_closed(self):
        self.put(b'x')
        db = FakeConnection()
        with patch.object(up.store_mysql, 'connect', return_value=db):
            up.run(plan_only=True, say=lambda *_: None)
        self.assertTrue(db.closed)


if __name__ == '__main__':
    unittest.main()
