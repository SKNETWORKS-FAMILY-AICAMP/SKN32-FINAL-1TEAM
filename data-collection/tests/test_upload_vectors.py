"""8단계 벡터 올리기(collect/upload_vectors.py) — 공용 DB 없이 임시 npz·가짜 연결로 확인한다.

올릴 대상 고르기(바뀐 것만), 바이트 모양(1,024차원 float32 리틀엔디안 = 4,096바이트), 공고가 없는 벡터 건너뛰기.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from collect import upload_vectors as up
from shared import embed


def write_npz(path, ids, shas, vectors, meta=None):
    np.savez(path, notice_ids=np.array(ids), input_sha256=np.array(shas),
             vectors=vectors, meta=np.array(json.dumps(meta if meta is not None else embed.meta())))


class FakeCursor(object):
    def __init__(self, db):
        self.db = db
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.db.selects.append(sql)

    def fetchall(self):
        return list(self.db.remote_rows)

    def executemany(self, sql, rows):
        self.db.updates.append(list(rows))
        self.rowcount = sum(1 for r in rows if r[-1] in self.db.known)


class FakeConnection(object):
    def __init__(self, remote_rows=(), known=()):
        self.remote_rows, self.known = list(remote_rows), set(known)
        self.selects, self.updates, self.commits, self.closed = [], [], 0, False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class PlanTests(unittest.TestCase):
    def test_only_new_or_changed(self):
        local = {'a': ('h1', b''), 'b': ('h2', b''), 'c': ('h3', b''), 'd': ('h4', b'')}
        remote = {'a': ('h1', 'fp'),          # 같음 → 건너뜀
                  'b': ('old', 'fp'),         # 내용이 바뀜
                  'c': ('h3', 'old-fp')}      # 설정이 바뀜, d 는 DB 에 없음
        self.assertEqual(up.plan(local, remote, 'fp'), ['b', 'c', 'd'])

    def test_nothing_changed(self):
        local = {'a': ('h1', b'')}
        self.assertEqual(up.plan(local, {'a': ('h1', 'fp')}, 'fp'), [])


class LoadLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'emb.npz')
        patcher = patch.object(embed, 'resolved_revision', return_value='rev-test')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bytes_are_float32_little_endian_4096(self):
        vectors = np.random.RandomState(0).rand(2, 1024).astype('float32')
        write_npz(self.path, ['n1', 'n2'], ['s1', 's2'], vectors)
        local, fingerprint = up.load_local(self.path)
        self.assertEqual(set(local), {'n1', 'n2'})
        sha, blob = local['n1']
        self.assertEqual(sha, 's1')
        self.assertEqual(len(blob), 4096)
        np.testing.assert_array_equal(np.frombuffer(blob, dtype='<f4'), vectors[0])
        self.assertEqual(fingerprint, embed.fingerprint())

    def test_values_in_little_endian_order(self):
        vectors = np.arange(1024, dtype='float32').reshape(1, 1024)
        write_npz(self.path, ['n1'], ['s1'], vectors)
        blob = up.load_local(self.path)[0]['n1'][1]
        self.assertEqual(blob[:4], np.array([0], dtype='<f4').tobytes())
        self.assertEqual(blob[4:8], np.array([1], dtype='<f4').tobytes())

    def test_non_float32_rejected(self):
        write_npz(self.path, ['n1'], ['s1'], np.zeros((1, 1024), dtype='float64'))
        with self.assertRaises(ValueError):
            up.load_local(self.path)

    def test_missing_file(self):
        self.assertEqual(up.load_local(os.path.join(self.tmp.name, 'none.npz')), ({}, None))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'emb.npz')
        # load_local 의 기본 경로는 정의할 때 묶이므로 함수 자체를 임시 파일 쪽으로 돌린다
        original = up.load_local
        for p in (patch.object(embed, 'resolved_revision', return_value='rev-test'),
                  patch.object(up, 'load_local', lambda path=None: original(self.path))):
            p.start()
            self.addCleanup(p.stop)
        vectors = np.ones((3, 1024), dtype='float32')
        write_npz(self.path, ['n1', 'n2', 'n3'], ['s1', 's2', 's3'], vectors)
        self.fp = embed.fingerprint()

    def test_no_local_vectors_is_error(self):
        os.remove(self.path)
        out = up.run(connection=FakeConnection(), say=lambda *_: None)
        self.assertEqual(out['error'], 'no_local_vectors')

    def test_plan_only_does_not_write(self):
        db = FakeConnection(remote_rows=[('n1', 's1', self.fp)])
        out = up.run(plan_only=True, connection=db, say=lambda *_: None)
        self.assertEqual((out['local'], out['remote'], out['todo'], out['uploaded']), (3, 1, 2, 0))
        self.assertEqual(db.updates, [])
        self.assertFalse(db.closed)               # 받은 연결은 닫지 않는다

    def test_uploads_changed_only_and_counts_missing_notices(self):
        db = FakeConnection(remote_rows=[('n1', 's1', self.fp)], known={'n2'})
        out = up.run(connection=db, say=lambda *_: None)
        self.assertEqual(len(db.updates), 1)
        rows = db.updates[0]
        self.assertEqual([r[-1] for r in rows], ['n2', 'n3'])
        blob, dim, sha, fp, _, nid = rows[0]
        self.assertEqual((len(blob), dim, sha, fp, nid), (4096, 1024, 's2', self.fp, 'n2'))
        self.assertEqual(out['uploaded'], 1)
        self.assertEqual(out['skipped_no_notice'], 1)   # 공고가 DB 에 없으면 새로 만들지 않는다
        self.assertEqual(out['dim'], 1024)
        self.assertEqual(db.commits, 1)

    def test_batches_of_100(self):
        vectors = np.ones((250, 1024), dtype='float32')
        ids = ['n%03d' % i for i in range(250)]
        write_npz(self.path, ids, ['s'] * 250, vectors)
        db = FakeConnection(known=ids)
        out = up.run(connection=db, say=lambda *_: None)
        self.assertEqual([len(b) for b in db.updates], [100, 100, 50])
        self.assertEqual(db.commits, 3)
        self.assertEqual(out['uploaded'], 250)

    def test_limit(self):
        db = FakeConnection(known={'n1', 'n2', 'n3'})
        out = up.run(limit=2, connection=db, say=lambda *_: None)
        self.assertEqual(out['uploaded'], 2)

    def test_fingerprint_mismatch_warns(self):
        write_npz(self.path, ['n1'], ['s1'], np.ones((1, 1024), dtype='float32'), meta={'model': 'other'})
        said = []
        up.run(plan_only=True, connection=FakeConnection(), say=said.append)
        self.assertTrue(any('경고' in s for s in said))

    def test_own_connection_closed(self):
        db = FakeConnection()
        with patch.object(up.store_mysql, 'connect', return_value=db):
            up.run(plan_only=True, say=lambda *_: None)
        self.assertTrue(db.closed)


if __name__ == '__main__':
    unittest.main()
