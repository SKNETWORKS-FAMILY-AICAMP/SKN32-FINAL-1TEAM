# -*- coding: utf-8 -*-
"""메모리 벡터 묶음(search/memvec.py)과 공고 서버 기동 때 벡터 올리기 (2026-10-07, 벡터 DB 빼기)."""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np  # noqa: E402

from search import memvec  # noqa: E402


def unit(*xs):
    v = np.zeros(memvec.DIM, dtype='float32')
    for i, x in enumerate(xs):
        v[i] = x
    return v / np.linalg.norm(v)


def blob(v):
    return np.asarray(v, dtype='<f4').tobytes()


class MemoryCollectionTests(unittest.TestCase):
    def setUp(self):
        self.col = memvec.MemoryCollection(
            ['a', 'b', 'c', 'd'], np.vstack([unit(1, 0), unit(0.9, 0.1), unit(0, 1), unit(0.9, 0.1)]))
        self.q = unit(1, 0).tolist()

    def test_count(self):
        self.assertEqual(self.col.count(), 4)

    def test_query_orders_by_distance_and_id(self):
        out = self.col.query(query_embeddings=[self.q], n_results=4)
        # b·d 는 같은 벡터라 거리가 같다 → 공고 ID 순
        self.assertEqual(out['ids'][0], ['a', 'b', 'd', 'c'])
        self.assertAlmostEqual(out['distances'][0][0], 0.0, places=5)
        self.assertTrue(all(x <= y + 1e-7 for x, y in zip(out['distances'][0], out['distances'][0][1:])))

    def test_query_within_ids_and_ignores_unknown(self):
        out = self.col.query(query_embeddings=[self.q], ids=['c', 'b', 'zzz'], n_results=5)
        self.assertEqual(out['ids'][0], ['b', 'c'])

    def test_query_empty_scope(self):
        self.assertEqual(self.col.query(query_embeddings=[self.q], ids=[], n_results=5), {'ids': [[]], 'distances': [[]]})
        self.assertEqual(self.col.query(query_embeddings=[self.q], n_results=0)['ids'], [[]])

    def test_distance_is_one_minus_dot(self):
        out = self.col.query(query_embeddings=[self.q], ids=['c'], n_results=1)
        self.assertAlmostEqual(out['distances'][0][0], 1.0, places=5)

    def test_get_shape(self):
        self.assertEqual(self.col.get(include=[])['ids'], ['a', 'b', 'c', 'd'])
        self.assertNotIn('embeddings', self.col.get(ids=['a']))
        got = self.col.get(ids=['c', 'zzz'], include=['embeddings'])
        self.assertEqual(got['ids'], ['c'])
        self.assertEqual(len(got['embeddings'][0]), memvec.DIM)

    def test_empty_collection(self):
        col = memvec.MemoryCollection([], [])
        self.assertEqual(col.count(), 0)
        self.assertEqual(col.query(query_embeddings=[self.q], n_results=3)['ids'], [[]])


class RowsTests(unittest.TestCase):
    def test_drops_wrong_shape(self):
        rows = [('a', blob(unit(1)), 1024, 'fp1'),
                ('b', blob(unit(0, 1)), 1024, 'fp1'),
                ('c', b'\x00' * 100, 1024, 'fp1'),            # 길이 틀림
                ('d', blob(unit(1)), 768, 'fp1'),             # 차원 틀림
                ('e', None, None, None)]
        col, info = memvec.rows_to_collection(rows)
        self.assertEqual(col.ids, ['a', 'b'])
        self.assertEqual(info, {'count': 2, 'dropped': 2, 'fingerprints': {'fp1': 2}})

    def test_load_selects_only(self):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, *args):
                self.sql = sql

            def fetchall(self):
                return [('a', blob(unit(1)), 1024, 'fp1')]

        class Conn:
            def __init__(self):
                self.c = Cursor()

            def cursor(self):
                return self.c

        conn = Conn()
        col, info = memvec.load(conn)
        self.assertTrue(conn.c.sql.lstrip().upper().startswith('SELECT'))
        self.assertEqual(col.count(), 1)

    def test_fingerprint_warning(self):
        self.assertIsNone(memvec.fingerprint_warning({'fingerprints': {'x': 3}}, 'x'))
        self.assertIsNone(memvec.fingerprint_warning({'fingerprints': {'x': 3}}, None))
        self.assertIsNone(memvec.fingerprint_warning({}, 'x'))
        self.assertIn('다른 설정 지문', memvec.fingerprint_warning({'fingerprints': {'x': 3, 'y': 1}}, 'x'))
        self.assertIn('없다', memvec.fingerprint_warning({'fingerprints': {'y': 1}}, 'x'))


class BootVectorTests(unittest.TestCase):
    """app._collection — 공용 DB 벡터를 올리고, 0건·실패면 boot 가 의미 검색 없이 연다."""

    def conn_with(self, rows=None, fail=False):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, *args):
                if fail:
                    raise RuntimeError('DB 끊김')

            def fetchall(self):
                return rows or []

        class Conn:
            closed = False

            def cursor(self):
                return Cursor()

            def close(self):
                Conn.closed = True
        return Conn

    def test_collection_from_db(self):
        from search import app
        Conn = self.conn_with([('a', blob(unit(1)), 1024, 'fp'), ('b', blob(unit(0, 1)), 1024, 'fp')])
        with patch.dict(app.STATE, {}, clear=True), patch.object(app, '_connect', Conn):
            col = app._collection()
            self.assertEqual(col.count(), 2)
            self.assertEqual(app.STATE['vectors_info']['count'], 2)
        self.assertTrue(Conn.closed)

    def test_zero_vectors_raises(self):
        from search import app
        with patch.dict(app.STATE, {}, clear=True), patch.object(app, '_connect', self.conn_with([])):
            with self.assertRaises(RuntimeError):
                app._collection()

    def test_db_failure_raises(self):
        from search import app
        with patch.dict(app.STATE, {}, clear=True), patch.object(app, '_connect', self.conn_with(fail=True)):
            with self.assertRaises(RuntimeError):
                app._collection()


if __name__ == '__main__':
    unittest.main()
