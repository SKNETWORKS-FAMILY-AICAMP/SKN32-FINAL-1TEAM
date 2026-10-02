# -*- coding: utf-8 -*-
"""매칭 후보 수(D)·대체 검색(E)·적합도(H) — 기능정의서 R-3·T-C2 (2026-09-28). DB·모델 없음."""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from search import app  # noqa: E402
from test_match_rules import FakeCollection, notice, state  # noqa: E402


def rows(n=25, expired=()):
    out = {}
    for i in range(1, n + 1):
        nid = 'n%02d' % i
        out[nid] = notice(nid, apply_end='2000-01-01' if i in expired else '2099-%02d-01' % (1 + (n - i) % 12))
    return out


def run(rs, encode=None, bm25_error=None, chroma_error=None, **kw):
    kw.setdefault('search', 'hybrid')
    req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원', **kw)
    st = state(rs)
    if bm25_error:
        def broken(*a, **k):
            raise bm25_error
        st['bm25'].search = broken
    if chroma_error:
        def broken_query(*a, **k):
            raise chroma_error
        st['collection'].query = broken_query
        st['collection'].get = broken_query
    enc = encode or (lambda text: [0.0, 0.0, 0.0, 0.0])
    with patch.dict(app.STATE, st, clear=True), patch.object(app, '_encode', enc):
        return app.match(req)


def ids(out):
    return [r['notice_id'] for r in out['results']]


class PagingTests(unittest.TestCase):
    def test_first_page_is_ten_with_three_cards(self):
        out = run(rows())
        self.assertEqual(len(out['results']), 10)
        self.assertEqual([r['rank'] for r in out['results']], list(range(1, 11)))
        self.assertEqual([r['display_type'] for r in out['results']], ['card'] * 3 + ['list'] * 7)
        self.assertTrue(out['has_more'])

    def test_second_page_continues_and_stops_at_twenty(self):
        first, second = run(rows()), run(rows(), offset=10)
        self.assertEqual([r['rank'] for r in second['results']], list(range(11, 21)))
        self.assertFalse(set(ids(first)) & set(ids(second)))
        self.assertFalse(second['has_more'])                       # 누적 20건이 최대
        self.assertEqual(len(run(rows(), offset=10, top=15)['results']), 10)   # 20을 넘지 않게 자른다
        self.assertEqual(run(rows(), offset=20)['results'], [])

    def test_large_top_without_offset_is_not_capped_for_direct_calls(self):
        # 평가 스크립트는 match() 를 직접 불러 top 을 크게 줘 후보 전체를 받는다(쪽수 제한은 offset 을 쓸 때만)
        self.assertEqual(len(run(rows(), top=100)['results']), 25)

    def test_public_route_never_returns_more_than_twenty(self):
        # 공개 경로 /api/match 는 기능정의서 T-C2 최대 20건(2026-09-28 Codex 통합 검수 P2)
        def api(**kw):
            req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원',
                                   search='hybrid', **kw)
            with patch.dict(app.STATE, state(rows()), clear=True), \
                    patch.object(app, '_encode', lambda text: [0.0, 0.0, 0.0, 0.0]):
                return app.api_match(req)
        self.assertEqual(len(api(top=100)['results']), 20)
        self.assertEqual(len(api(top=100, offset=10)['results']), 10)
        self.assertEqual(api(top=100, offset=30)['results'], [])
        self.assertEqual(len(api()['results']), 10)                   # 기본값은 그대로


class FallbackTests(unittest.TestCase):
    def test_normal_hybrid_has_no_fallback_and_fit_is_one_for_double_first(self):
        out = run(rows())
        self.assertFalse(out['fallback_used'])
        self.assertIsNone(out['fallback_mode'])
        self.assertEqual(out['results'][0]['fit_score'], 1.0)         # 두 검색 모두 1위
        self.assertTrue(all(0 < r['fit_score'] <= 1 for r in out['results']))
        self.assertIn('두 검색 모두 1위', out['fit_basis'])

    def test_embedding_failure_falls_back_to_bm25_and_keeps_filter(self):
        def broken(text):
            raise RuntimeError('model down')
        out = run(rows(expired=(1, 2)), encode=broken)
        self.assertTrue(out['fallback_used'])
        self.assertEqual(out['fallback_mode'], 'BM25단독')
        self.assertIn('RuntimeError', out['search_errors']['embedding']['error'])
        self.assertNotIn('n01', ids(out))                          # 정형 필터는 대체 경로에서도 돈다
        self.assertEqual(len(out['results']), 10)
        self.assertIsNone(out['results'][0]['score'])               # 유사도가 없다
        self.assertEqual(out['results'][0]['fit_score'], 1.0)       # 사용한 검색(BM25) 1위

    def test_chroma_failure_also_falls_back_to_bm25(self):
        out = run(rows(), chroma_error=RuntimeError('index broken'))
        self.assertEqual(out['fallback_mode'], 'BM25단독')
        self.assertEqual(out['search_errors']['embedding']['where'], '의미 검색')

    def test_extra_vector_lookup_failure_keeps_hybrid_order_without_500(self):
        # query() 는 되는데 BM25 에서만 찾은 공고의 벡터 조회(get)가 실패(2026-09-28 Codex 통합 검수 P1)
        class HalfBroken(FakeCollection):
            def query(self, query_embeddings=None, n_results=10, ids=None):
                found = FakeCollection.query(self, query_embeddings, n_results, ids)
                return {'ids': [found['ids'][0][:5]], 'distances': [found['distances'][0][:5]]}

            def get(self, ids=None, include=None):
                raise RuntimeError('get timeout')

        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원')
        rs = rows()
        st = dict(state(rs), collection=HalfBroken(list(rs)))
        with patch.dict(app.STATE, st, clear=True), patch.object(app, '_encode', lambda t: [0.0] * 4):
            out = app.match(req)
        self.assertIsNone(out['fallback_mode'])                         # 순위는 하이브리드 그대로
        self.assertEqual(out['search_errors']['embedding']['where'], '벡터 추가 조회')
        self.assertEqual(len(out['results']), 10)
        scores = [r['score'] for r in out['results']]
        self.assertTrue(any(sc is None for sc in scores))              # BM25 에서만 찾은 공고는 유사도 없이
        self.assertTrue(any(sc is not None for sc in scores))

    def test_vector_db_closed_at_boot_goes_to_bm25(self):
        req = app.MatchRequest(applicant_type='법인사업자', founded_at='2025-01-01', idea='창업 지원')
        st = dict(state(rows()), collection=None, vector_ids=None,
                  boot_errors={'vector_db': {'where': '벡터 DB 연결', 'error': 'SystemExit: 색인 없음'}})
        with patch.dict(app.STATE, st, clear=True), patch.object(app, '_encode', lambda t: [0.0] * 4):
            out = app.match(req)
        self.assertEqual(out['fallback_mode'], 'BM25단독')
        self.assertIn('색인 없음', out['search_errors']['embedding']['error'])
        self.assertEqual(len(out['results']), 10)

    def test_bm25_failure_falls_back_to_embedding(self):
        out = run(rows(), bm25_error=ValueError('bm25 down'))
        self.assertEqual(out['fallback_mode'], '임베딩단독')
        self.assertEqual(ids(out)[:3], ['n01', 'n02', 'n03'])
        self.assertIsNotNone(out['results'][0]['score'])

    def test_both_fail_orders_by_deadline_without_fit(self):
        def broken(text):
            raise RuntimeError('model down')
        rs = rows(5)
        out = run(rs, encode=broken, bm25_error=ValueError('bm25 down'))
        self.assertEqual(out['fallback_mode'], '마감임박순')
        ends = [r['apply_end'] for r in out['results']]
        self.assertEqual(ends, sorted(ends))
        self.assertTrue(all(r['fit_score'] is None for r in out['results']))
        self.assertIsNone(out['fit_basis'])

    def test_dense_mode_is_not_a_fallback(self):
        out = run(rows(), search='dense')
        self.assertIsNone(out['fallback_mode'])
        self.assertEqual(out['results'][0]['fit_score'], 1.0)


class BootTests(unittest.TestCase):
    """서버 시작 때 벡터 DB·임베딩이 죽어 있어도 서버는 열린다(2026-09-28 Codex 통합 검수 P1)."""

    def boot(self, collection, encode):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql):
                pass

            def fetchall(self):
                return [tuple(notice('n01').get(f) for f in app.FIELDS)]

        class Conn:
            def cursor(self):
                return Cursor()

            def close(self):
                pass

        from search import age_evidence, applicant_types, hybrid, industry_rank
        with patch.dict(app.STATE, {}, clear=True),                 patch.object(age_evidence, 'load', lambda conn=None: {'notices': {}, 'sources': [], 'error': None}), \
                patch.object(app, '_collection', collection), patch.object(app, '_connect', Conn), \
                patch.object(app, '_build_bm25', lambda: hybrid.BM25([('n01', '창업 지원')])), \
                patch.object(app, '_encode', encode), patch.object(app, 'ON_EC2', False), \
                patch.object(industry_rank, 'load_auto', lambda *a, **k: {'notices': {}, 'source': None, 'error': None}), \
                patch.object(applicant_types, 'load_auto', lambda *a, **k: {'notices': {}, 'source': None, 'error': None}):
            app.boot()
            return dict(app.STATE)

    def test_boot_survives_missing_vector_db_and_embedding(self):
        def no_index():
            raise SystemExit('Chroma 색인이 없다')

        def no_model(text):
            raise RuntimeError('model down')
        st = self.boot(no_index, no_model)
        self.assertIsNone(st['collection'])
        self.assertEqual(set(st['boot_errors']), {'vector_db', 'embedding'})
        self.assertEqual(len(st['rows']), 1)                             # 공고 정보·BM25 는 올라와 있다
        self.assertEqual(len(st['bm25']), 1)

    def test_boot_normal_has_no_errors(self):
        st = self.boot(lambda: FakeCollection(['n01']), lambda text: [0.0] * 4)
        self.assertEqual(st['boot_errors'], {})
        self.assertEqual(st['vector_ids'], {'n01'})


if __name__ == '__main__':
    unittest.main()
