# -*- coding: utf-8 -*-
r"""Chroma 실제 벡터 검증 테스트 — docs/CHROMA_INTEGRITY_TASK_20260918.md '필요한 테스트'.

  .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_chroma_integrity -v

**외부 DB·모델·실제 Chroma 를 부르지 않는다.** 가짜 벡터·가짜 컬렉션으로 확인한다.
여기 통과했다고 실제 색인이 맞다는 뜻은 아니다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'eval'))
import io
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import chroma_integrity as ci
import search_comparison as sc

DIM = 4
META = {'model': 'BAAI/bge-m3', 'revision': 'rev1', 'input_version': 'v1:x', 'max_tokens': 512,
        'dim': DIM, 'dtype': 'float32', 'normalized': True, 'byte_order': 'little'}


def vectors(n, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, DIM)).astype('float32')
    return v / np.linalg.norm(v, axis=1, keepdims=True)


class CompareVectorsTests(unittest.TestCase):
    def setUp(self):
        self.ids = ['a', 'b', 'c']
        self.vecs = vectors(3)

    def run_cmp(self, chroma_ids, chroma_vecs, ids=None, vecs=None):
        return ci.compare_vectors(ids or self.ids, self.vecs if vecs is None else vecs,
                                  chroma_ids, chroma_vecs, DIM)

    def test_same_vectors_in_different_order_pass(self):
        out = self.run_cmp(['c', 'a', 'b'], [self.vecs[2].tolist(), self.vecs[0].tolist(),
                                             self.vecs[1].tolist()])
        self.assertEqual(out['status'], ci.PASS)
        self.assertEqual(out['compared'], 3)
        self.assertEqual(out['byte_equal'], 3)
        self.assertEqual(out['max_abs_diff'], 0.0)

    def test_changed_vector_same_id_is_mismatch(self):
        changed = self.vecs.copy()
        changed[1] = vectors(1, seed=9)[0]
        out = self.run_cmp(self.ids, changed.tolist())
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertEqual(out['mismatch_examples'][0]['notice_id'], 'b')

    def test_within_tolerance_passes_but_is_not_byte_equal(self):
        nudged = self.vecs.copy()
        nudged[0, 0] += 5e-7                      # 허용 1e-6 이내
        out = self.run_cmp(self.ids, nudged.tolist())
        self.assertEqual(out['status'], ci.PASS)
        self.assertEqual(out['byte_equal'], 2)    # 바이트 일치와 허용 오차 일치를 구분한다

    def test_renormalized_copy_is_counted_separately(self):
        """코사인 색인은 저장할 때 다시 정규화한다. 그 차이는 통과지만 따로 센다."""
        stretched = self.vecs * np.float32(1.0000001)             # 길이가 1 보다 살짝 큰 NPZ
        again = (stretched.astype('float64')
                 / np.linalg.norm(stretched.astype('float64'), axis=1, keepdims=True)).astype('float32')
        out = ci.compare_vectors(self.ids, stretched, self.ids, again.tolist(), DIM)
        self.assertEqual(out['status'], ci.PASS)
        self.assertEqual(out['byte_equal'] + out['renormalized_equal']
                         + out['within_tolerance_other'], 3)
        self.assertGreaterEqual(out['renormalized_equal'], 1)

    def test_over_tolerance_is_mismatch(self):
        nudged = self.vecs.copy()
        nudged[0, 0] += 5e-6                      # 허용 1e-6 초과
        out = self.run_cmp(self.ids, nudged.tolist())
        self.assertEqual(out['status'], ci.MISMATCH)

    def test_high_cosine_is_not_enough(self):
        """코사인이 0.999 넘어도 원소가 다르면 불일치다."""
        close = self.vecs.copy()
        close[2] = close[2] + 1e-3
        close[2] /= np.linalg.norm(close[2])
        self.assertGreater(float(np.dot(close[2], self.vecs[2])), 0.999)
        self.assertEqual(self.run_cmp(self.ids, close.tolist())['status'], ci.MISMATCH)

    def test_missing_extra_duplicate_ids(self):
        out = self.run_cmp(['a', 'b', 'b', 'z'], [self.vecs[0].tolist(), self.vecs[1].tolist(),
                                                  self.vecs[1].tolist(), self.vecs[2].tolist()])
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertEqual(out['only_in_npz'], ['c'])
        self.assertEqual(out['only_in_chroma'], ['z'])
        self.assertEqual(out['chroma_duplicates'], ['b'])

    def test_broken_vectors(self):
        nan = self.vecs[2].tolist()
        nan[0] = float('nan')
        out = self.run_cmp(self.ids, [None, [0.1, 0.2], nan])
        self.assertEqual(out['status'], ci.MISMATCH)
        problems = {b['notice_id']: b['problem'] for b in out['broken']}
        self.assertEqual(problems['a'], '벡터 없음')
        self.assertIn('차원', problems['b'])
        self.assertIn('NaN', problems['c'])

    # ---- NPZ 쪽 이상 (2026-09-21 Codex 리뷰 P1). 예전에는 NaN 이 '통과', 차원 오류가 예외였다

    def test_npz_nan_is_not_pass(self):
        bad = self.vecs.copy()
        bad[1, 0] = np.nan
        out = self.run_cmp(self.ids, self.vecs.tolist(), vecs=bad)
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertEqual(out['npz_broken'][0]['notice_id'], 'b')
        self.assertIn('NaN', out['npz_broken'][0]['problem'])
        self.assertEqual(out['within_tolerance_other'], 0)

    def test_npz_inf_is_not_pass(self):
        bad = self.vecs.copy()
        bad[0, 2] = np.inf
        out = self.run_cmp(self.ids, self.vecs.tolist(), vecs=bad)
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertEqual(out['npz_broken_count'], 1)

    def test_npz_wrong_dimension_is_reported_not_raised(self):
        wrong = np.zeros((3, 2), dtype='float32')              # 기대 4차원
        out = self.run_cmp(self.ids, self.vecs.tolist(), vecs=wrong)
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertEqual(out['npz_broken_count'], 3)
        self.assertEqual(out['compared'], 0)

    def test_npz_problems_are_named_by_source(self):
        bad = self.vecs.copy()
        bad[0, 0] = np.nan
        out = self.run_cmp(self.ids, self.vecs.tolist(), vecs=bad)
        self.assertTrue(any('NPZ 벡터 이상' in p for p in out['problems']))
        self.assertFalse(any('Chroma 벡터 이상' in p for p in out['problems']))

    def test_length_mismatch_is_unverified(self):
        out = self.run_cmp(self.ids, self.vecs[:2].tolist())
        self.assertEqual(out['status'], ci.UNVERIFIED)

    def test_empty_is_not_pass(self):
        out = ci.compare_vectors([], np.zeros((0, DIM), dtype='float32'), [], [], DIM)
        self.assertEqual(out['status'], ci.UNVERIFIED)


class CompareMetaTests(unittest.TestCase):
    def test_all_same_passes(self):
        out = ci.compare_meta(json.dumps(META), META, META)
        self.assertEqual(out['status'], ci.PASS)

    def test_revision_differs_is_mismatch(self):
        out = ci.compare_meta(json.dumps(dict(META, revision='old')), META, META)
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertIn('revision', out['reason'])

    def test_missing_chroma_meta_is_unverified_not_filled_from_npz(self):
        out = ci.compare_meta(None, META, META)
        self.assertEqual(out['status'], ci.UNVERIFIED)
        self.assertNotIn('chroma', out)          # NPZ 값으로 대신 채우지 않는다

    def test_unparseable_meta_is_unverified(self):
        self.assertEqual(ci.compare_meta('{not json', META, META)['status'], ci.UNVERIFIED)

    def test_missing_field_is_unverified(self):
        partial = {k: v for k, v in META.items() if k != 'max_tokens'}
        self.assertEqual(ci.compare_meta(json.dumps(partial), META, META)['status'], ci.UNVERIFIED)


class CompareDbTests(unittest.TestCase):
    def test_stale_missing_extra(self):
        out = ci.compare_db({'a': 'h1', 'b': 'NEW', 'd': 'h4'}, ['a', 'b', 'c'], ['h1', 'h2', 'h3'])
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertEqual(out['stale_examples'], ['b'])
        self.assertEqual(out['missing_examples'], ['d'])
        self.assertEqual(out['extra_examples'], ['c'])

    def test_empty_db_is_unverified(self):
        self.assertEqual(ci.compare_db({}, ['a'], ['h'])['status'], ci.UNVERIFIED)


class FakeCollection:
    def __init__(self, ids, vecs, metadata, fail=False, with_watermark=True):
        self.ids = list(ids) + (['__watermark__'] if with_watermark else [])
        self.vecs = list(vecs) + ([[0.0] * DIM] if with_watermark else [])
        self.metadata = metadata
        self.fail = fail

    def count(self):
        return len(self.ids)

    def get(self, include=None, limit=None, offset=0):
        if self.fail:
            raise RuntimeError('조회 실패')
        end = offset + (limit or len(self.ids))
        return {'ids': self.ids[offset:end], 'embeddings': self.vecs[offset:end]}

    # 쓰기 함수 — 불리면 테스트가 실패한다
    def add(self, *a, **k):
        raise AssertionError('검사 중 add 호출')

    upsert = delete = add


class CheckTests(unittest.TestCase):
    """check() 전체 흐름. 임시 폴더에 가짜 NPZ·Chroma 폴더를 만든다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ids = ['a', 'b', 'c']
        self.vecs = vectors(3)
        self.npz = os.path.join(self.tmp, 'emb.npz')
        np.savez(self.npz, vectors=self.vecs, notice_ids=np.array(self.ids),
                 input_sha256=np.array(['h1', 'h2', 'h3']), meta=np.array(json.dumps(META)))
        self.chroma_dir = os.path.join(self.tmp, 'chroma')
        os.makedirs(self.chroma_dir)
        with io.open(os.path.join(self.chroma_dir, 'chroma.sqlite3'), 'wb') as f:
            f.write(b'fake')
        self.db = lambda: ({'a': 'h1', 'b': 'h2', 'c': 'h3'}, 'corpus')

    def run_check(self, col, db=None):
        opener = lambda _d, _c: (None, col, None)     # noqa: E731
        return ci.check(db or self.db, self.npz, self.chroma_dir, 'notices_v1', META,
                        open_collection=opener)

    def healthy(self, **kw):
        return FakeCollection(self.ids, self.vecs.tolist(), {'embed_meta': json.dumps(META)}, **kw)

    def test_healthy_passes_and_watermark_is_excluded(self):
        out = self.run_check(self.healthy())
        self.assertEqual(out['status'], ci.PASS)
        self.assertTrue(out['chroma_content_verified'])
        self.assertEqual(out['parts']['npz_chroma']['chroma_count'], 3)   # 워터마크 제외
        self.assertTrue(out['chroma_vector_set_sha256'])

    def test_query_failure_is_unverified(self):
        out = self.run_check(self.healthy(fail=True))
        self.assertEqual(out['status'], ci.UNVERIFIED)
        self.assertFalse(out['chroma_content_verified'])

    def test_meta_mismatch_blocks_verification(self):
        col = FakeCollection(self.ids, self.vecs.tolist(),
                             {'embed_meta': json.dumps(dict(META, dim=1024))})
        out = self.run_check(col)
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertFalse(out['chroma_content_verified'])

    # ---- 대표 플래그는 DB→NPZ→Chroma 전체가 통과해야 참 (Codex 리뷰 P2)

    def test_db_problems_keep_flag_false(self):
        cases = {
            'stale': {'a': 'h1', 'b': 'OLD', 'c': 'h3'},
            'missing': {'a': 'h1', 'b': 'h2', 'c': 'h3', 'd': 'h4'},
            'extra': {'a': 'h1', 'b': 'h2'},
        }
        for name, shas in cases.items():
            out = self.run_check(self.healthy(), db=lambda s=shas: (s, 'corpus'))
            self.assertEqual(out['parts']['npz_chroma']['status'], ci.PASS, name)
            self.assertEqual(out['parts']['db_npz']['status'], ci.MISMATCH, name)
            self.assertFalse(out['chroma_content_verified'], name)

    def test_db_unreadable_keeps_flag_false(self):
        def fail():
            raise RuntimeError('접속 실패')
        out = self.run_check(self.healthy(), db=fail)
        self.assertEqual(out['status'], ci.UNVERIFIED)
        self.assertFalse(out['chroma_content_verified'])

    # ---- NPZ 파일 자체 문제 → traceback 이 아니라 '확인 실패' 결과 (Codex 리뷰 P1-4)

    def save_npz(self, **arrays):
        np.savez(self.npz, **arrays)

    def test_npz_missing_file_is_unverified(self):
        os.remove(self.npz)
        out = self.run_check(self.healthy())
        self.assertEqual(out['status'], ci.UNVERIFIED)
        self.assertFalse(out['chroma_content_verified'])
        self.assertIn('npz', out['parts'])

    def test_npz_missing_key_is_unverified(self):
        self.save_npz(vectors=self.vecs, notice_ids=np.array(self.ids), meta=np.array(json.dumps(META)))
        out = self.run_check(self.healthy())
        self.assertEqual(out['status'], ci.UNVERIFIED)

    def test_npz_length_mismatch_is_unverified(self):
        self.save_npz(vectors=self.vecs, notice_ids=np.array(self.ids),
                      input_sha256=np.array(['h1', 'h2']), meta=np.array(json.dumps(META)))
        out = self.run_check(self.healthy())
        self.assertEqual(out['status'], ci.UNVERIFIED)
        self.assertTrue(any('길이' in p for p in out['parts']['npz']['problems']))

    def test_npz_nan_through_full_check_is_not_verified(self):
        bad = self.vecs.copy()
        bad[2, 1] = np.nan
        self.save_npz(vectors=bad, notice_ids=np.array(self.ids),
                      input_sha256=np.array(['h1', 'h2', 'h3']), meta=np.array(json.dumps(META)))
        out = self.run_check(self.healthy())
        self.assertEqual(out['status'], ci.MISMATCH)
        self.assertFalse(out['chroma_content_verified'])

    def test_unverified_run_still_writes_report(self):
        os.remove(self.npz)
        out = self.run_check(self.healthy())
        report = os.path.join(self.tmp, 'report')
        ci.write_report(out, report)
        self.assertTrue(os.path.isfile(os.path.join(report, 'summary.md')))
        with io.open(os.path.join(report, 'summary.md'), encoding='utf-8') as f:
            self.assertIn('확인 실패', f.read())

    def test_db_change_during_check_is_unverified(self):
        calls = {'n': 0}

        def db():
            calls['n'] += 1
            return ({'a': 'h1', 'b': 'h2', 'c': 'h3'}, 'corpus-%d' % calls['n'])

        out = self.run_check(self.healthy(), db=db)
        self.assertEqual(out['status'], ci.UNVERIFIED)
        self.assertIn('DB 공고 내용이 검사 중에 바뀌었다', out['snapshot']['changed'])

    def test_original_folder_is_not_modified_by_open_copy(self):
        """open_copy 는 원본이 아니라 복사본을 연다 — 원본 폴더 지문이 그대로여야 한다."""
        before = ci.folder_fingerprint(self.chroma_dir)

        def fake_client(path):
            self.assertNotEqual(os.path.abspath(path), os.path.abspath(self.chroma_dir))
            with io.open(os.path.join(path, 'chroma.sqlite3'), 'ab') as f:   # 사본만 건드린다
                f.write(b'touched')

            class C:
                def get_collection(_self, name):
                    return None
            return C()

        import types
        fake = types.SimpleNamespace(PersistentClient=fake_client)
        with patch.dict(sys.modules, {'chromadb': fake}):
            _client, _col, tmp = ci.open_copy(self.chroma_dir, 'notices_v1')
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(ci.folder_fingerprint(self.chroma_dir), before)


class CheckOnlyModeTests(unittest.TestCase):
    """--check-only 는 검색·워밍업·인코딩·색인 생성을 부르지 않는다."""

    def test_check_only_calls_nothing_dangerous(self):
        def boom(*a, **k):
            raise AssertionError('검사 전용 모드에서 부르면 안 되는 함수가 불렸다')

        from search import vecstore
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        fake_result = ({'status': ci.PASS}, None)

        def fake_run(**kw):
            return 0, {'status': ci.PASS}, tmp

        with patch.object(sc.app, 'boot', boom), \
                patch.object(sc.app, 'match', boom), \
                patch.object(sc, 'run_case', boom), \
                patch.object(vecstore, 'build_chroma', boom), \
                patch.object(vecstore, 'embed_query', boom), \
                patch.object(vecstore, 'sync', boom), \
                patch.object(ci, 'run', fake_run), \
                patch.object(sys, 'argv', ['search_comparison.py', '--check-only']):
            self.assertEqual(sc.main(), 0)
        del fake_result

    def test_run_uses_no_model_or_index_writes(self):
        """ci.run 자체도 인코딩·색인 생성 없이 끝난다 (가짜 DB·컬렉션)."""
        from search import vecstore

        def boom(*a, **k):
            raise AssertionError('불리면 안 된다')

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ids, vecs = ['a'], vectors(1)
        npz = os.path.join(tmp, 'e.npz')
        np.savez(npz, vectors=vecs, notice_ids=np.array(ids), input_sha256=np.array(['h']),
                 meta=np.array(json.dumps(META)))
        store = os.path.join(tmp, 'store')
        os.makedirs(os.path.join(store, 'chroma'))
        col = FakeCollection(ids, vecs.tolist(), {'embed_meta': json.dumps(META)})
        with patch.object(vecstore, 'NPZ', npz), patch.object(vecstore, 'STORE', store), \
                patch.object(vecstore, 'build_chroma', boom), \
                patch.object(vecstore, 'embed_query', boom), \
                patch('shared.embed.meta', lambda *a, **k: META):
            code, result, outdir = ci.run(say=lambda *_: None, db_loader=lambda: ({'a': 'h'}, 'c'),
                                          open_collection=lambda d, c: (None, col, None),
                                          outdir=os.path.join(tmp, 'report'))
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(outdir, 'integrity.json')))
        self.assertTrue(os.path.isfile(os.path.join(outdir, 'summary.md')))


class PreflightOrderTests(unittest.TestCase):
    """일반 비교 실행: 사전 검사가 실패하면 서버·모델을 **켜기 전에** 멈춘다 (Codex 리뷰 P2)."""

    def test_failed_preflight_calls_no_boot_encode_or_match(self):
        calls = []

        def record(name):
            def fn(*a, **k):
                calls.append(name)
                raise AssertionError('%s 가 불렸다' % name)
            return fn

        failed = {'status': ci.MISMATCH, 'chroma_content_verified': False,
                  'parts': {'npz_chroma': {'status': ci.MISMATCH,
                                           'problems': ['벡터 값이 다른 공고 1건']}}}
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with patch.object(sc, 'preflight_check', lambda: dict(failed)), \
                patch.object(sc.app, 'boot', record('app.boot')), \
                patch.object(sc.app, '_encode', record('app._encode')), \
                patch.object(sc.app, 'match', record('app.match')), \
                patch.object(sc, 'data_check', record('data_check')), \
                patch.object(sc, 'run_case', record('run_case')), \
                patch.object(sc, 'REPORTS', tmp), \
                patch.object(sys, 'argv', ['search_comparison.py']):
            self.assertEqual(sc.main(), 2)
        self.assertEqual(calls, [])
        self.assertEqual(os.listdir(tmp), [])             # 결과 폴더도 만들지 않는다

    def test_passed_preflight_then_boots_and_rechecks(self):
        order = []
        ok = {'status': ci.PASS, 'chroma_content_verified': True, 'parts': {}, 'corpus_sha256': 'x'}
        broken = {'db_equals_chroma': False, 'db_equals_bm25': True, 'db_equals_rows': True,
                  'bm25_content_checked': True, 'bm25_content_mismatch_count': 0,
                  'vector_file': {'checked': True, 'stale_count': 0, 'missing_count': 0},
                  'chroma_content': {'status': ci.PASS, 'failure_lines': []},
                  'chroma_content_verified': True, 'db_notices': 1, 'chroma_vectors': 1,
                  'bm25_docs': 1, 'server_rows': 1}
        with patch.object(sc, 'preflight_check', lambda: order.append('preflight') or dict(ok)), \
                patch.object(sc.app, 'boot', lambda: order.append('boot')), \
                patch.object(sc, 'data_check', lambda pre=None: order.append('data_check') or dict(broken)), \
                patch.object(sys, 'argv', ['search_comparison.py']):
            self.assertEqual(sc.main(), 2)                # 부팅 뒤 검사에서 ID 불일치로 멈춘다
        self.assertEqual(order, ['preflight', 'boot', 'data_check'])


class PreflightReuseTests(unittest.TestCase):
    """사전 검사 결과는 DB·NPZ·Chroma 가 그 뒤로 그대로일 때만 다시 쓴다 (Codex 후속 리뷰 P2).

    실제 chroma_integrity.check 로 통과한 사전 검사를 만든 뒤 파일을 바꿔 본다.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ids = ['a', 'b', 'c']
        self.vecs = vectors(3)
        self.npz = os.path.join(self.tmp, 'emb.npz')
        self.save(self.vecs)
        self.chroma_dir = os.path.join(self.tmp, 'chroma')
        os.makedirs(self.chroma_dir)
        with io.open(os.path.join(self.chroma_dir, 'chroma.sqlite3'), 'wb') as f:
            f.write(b'v1')
        col = FakeCollection(self.ids, self.vecs.tolist(), {'embed_meta': json.dumps(META)})
        self.pre = ci.check(lambda: ({'a': 'h1', 'b': 'h2', 'c': 'h3'}, 'corpus'), self.npz,
                            self.chroma_dir, 'notices_v1', META,
                            open_collection=lambda _d, _c: (None, col, None))
        self.assertTrue(self.pre['chroma_content_verified'])

    def save(self, vecs):
        np.savez(self.npz, vectors=vecs, notice_ids=np.array(self.ids),
                 input_sha256=np.array(['h1', 'h2', 'h3']), meta=np.array(json.dumps(META)))

    def now(self):
        return {'npz_sha256': ci.file_sha256(self.npz),
                'chroma_files': ci.folder_fingerprint(self.chroma_dir)}

    def test_nothing_changed_reuses(self):
        self.assertIsNone(sc.preflight_reuse_problem(self.pre, 'corpus', self.now()))

    def test_db_changed_rechecks(self):
        self.assertIn('DB', sc.preflight_reuse_problem(self.pre, 'other', self.now()))

    def test_npz_vector_only_change_same_ids_rechecks(self):
        changed = self.vecs.copy()
        changed[0] = vectors(1, seed=7)[0]             # ID·입력 해시는 그대로, 벡터 값만 바뀐다
        self.save(changed)
        self.assertIn('NPZ', sc.preflight_reuse_problem(self.pre, 'corpus', self.now()))

    def test_chroma_only_change_rechecks(self):
        with io.open(os.path.join(self.chroma_dir, 'chroma.sqlite3'), 'wb') as f:
            f.write(b'v2')                             # 같은 ID 의 벡터가 바뀐 색인 파일을 흉내 낸다
        self.assertIn('Chroma', sc.preflight_reuse_problem(self.pre, 'corpus', self.now()))

    def test_failed_or_incomplete_preflight_is_not_reused(self):
        self.assertIsNotNone(sc.preflight_reuse_problem(None, 'corpus', self.now()))
        failed = dict(self.pre, chroma_content_verified=False)
        self.assertIsNotNone(sc.preflight_reuse_problem(failed, 'corpus', self.now()))
        no_snapshot = {k: v for k, v in self.pre.items() if k != 'snapshot'}
        self.assertIsNotNone(sc.preflight_reuse_problem(no_snapshot, 'corpus', self.now()))

    def test_fingerprint_for_manifest(self):
        fp = sc.data_fingerprint(self.pre, 'corpus')
        self.assertEqual(fp['corpus_sha256'], 'corpus')
        self.assertEqual(fp['npz_sha256'], ci.file_sha256(self.npz))
        self.assertTrue(fp['chroma_files_sha256'])
        self.assertTrue(fp['npz_vector_set_sha256'])
        self.assertTrue(fp['chroma_vector_set_sha256'])


class ComparisonStopsTests(unittest.TestCase):
    """Chroma 내용이 확인되지 않으면 비교 실행이 검색 전에 멈춘다."""

    def base(self, **kw):
        checks = {'db_equals_chroma': True, 'db_equals_bm25': True, 'db_equals_rows': True,
                  'bm25_content_checked': True, 'bm25_content_mismatch_count': 0,
                  'vector_file': {'checked': True, 'stale_count': 0, 'missing_count': 0},
                  'chroma_content': {'status': ci.PASS, 'failure_lines': []},
                  'chroma_content_verified': True}
        checks.update(kw)
        return checks

    def test_verified_has_no_failure(self):
        self.assertEqual(sc.integrity_failures(self.base()), [])

    def test_unverified_or_mismatch_is_a_failure(self):
        for status in (ci.MISMATCH, ci.UNVERIFIED):
            bad = sc.integrity_failures(self.base(
                chroma_content={'status': status, 'failure_lines': ['[npz_chroma] 예시 사유']},
                chroma_content_verified=False))
            self.assertTrue(any('Chroma 실제 벡터' in line for line in bad), status)
            self.assertTrue(any('예시 사유' in line for line in bad))

    def test_missing_check_result_is_a_failure(self):
        checks = self.base()
        del checks['chroma_content_verified']
        self.assertTrue(sc.integrity_failures(checks))


if __name__ == '__main__':
    unittest.main()
