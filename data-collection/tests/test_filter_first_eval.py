# -*- coding: utf-8 -*-
"""eval/filter_first_eval.py 의 지표 계산 — DB·Chroma·모델 없이 순수 함수만 본다 (2026-09-28)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'eval')):
    if p not in sys.path:
        sys.path.insert(0, p)

import filter_first_eval as ffe  # noqa: E402


class QueryMetricsTests(unittest.TestCase):
    def test_bounds_and_useful(self):
        ranked = ['a', 'b', 'c', 'd']
        rels = {'a': 2, 'b': 0, 'd': 2}                 # c 는 미판정
        eligible = {'a': True, 'b': True, 'c': True, 'd': False}
        m = ffe.query_metrics(ranked, rels, eligible)
        self.assertEqual(m['returned'], 4)
        self.assertAlmostEqual(m['ineligible_k'], 0.25)
        self.assertAlmostEqual(m['p3_lo'], 1 / 3)       # a 만
        self.assertAlmostEqual(m['p3_hi'], 2 / 3)       # a + 미판정 c
        self.assertEqual((m['useful3_lo'], m['useful3_hi']), (1, 2))
        self.assertEqual((m['usefulk_lo'], m['usefulk_hi']), (1, 2))   # d 는 내용이 맞아도 신청 불가
        self.assertAlmostEqual(m['unjudged3'], 1 / 3)

    def test_empty_result(self):
        m = ffe.query_metrics([], {'a': 2}, {})
        self.assertIsNone(m['ineligible_k'])
        self.assertEqual((m['returned'], m['p3_lo'], m['usefulk_hi']), (0, 0, 0))

    def test_mean_skips_none(self):
        self.assertEqual(ffe.mean([None, 1, 3]), 2)
        self.assertIsNone(ffe.mean([None]))


class VectorOnlyTests(unittest.TestCase):
    """처음 방식(벡터만) 재현 스위치 — 이름이 틀리면 MatchRequest 가 조용히 무시해 스위치가 켜진 채 남는다."""

    def test_switches_are_real_fields_and_all_off(self):
        from search import app
        fields = app.MatchRequest.model_fields
        for key in ffe.VECTOR_ONLY:
            self.assertIn(key, fields, key)
        req = app.MatchRequest(idea='x', applicant_type='예비창업자', **ffe.VECTOR_ONLY)
        self.assertEqual(req.search, 'dense')
        # 매칭을 바꾸는 켜고 끄는 스위치는 모두 꺼져 있어야 한다(새 스위치가 생기면 여기서 걸린다)
        # (hiring_plan 은 신청자 입력이라 기본값 False 로 통과한다)
        toggles = [k for k, f in fields.items() if f.annotation is bool]
        on = [k for k in toggles if getattr(req, k)]
        self.assertEqual(on, [], '벡터만인데 켜진 스위치: %s' % on)

    def test_render_has_three_columns_and_old_summary_still_renders(self):
        meta = {'as_of': '2026-09-15', 'queries': 2, 'k': 10, 'corpus_notices': 5, 'corpus_before': '2026-09-16',
                'legacy_commit': 'abc', 'qrels_pairs': 3, 'judges': 'all'}
        row = {'label': '신청 불가@10', 'better': 'lower', 'vector_only': 0.3, 'legacy': 0.05, 'filter_first': 0.0,
               'diff': (-0.05, -0.1, 0.0), 'diff_vs_vector': (-0.3, -0.4, -0.2)}
        text = '\n'.join(ffe.render(meta, {'hybrid': {'ineligible_k': row}}))
        self.assertIn('| 신청 불가@10 | 30.0% | 5.0% | 0.0% | -0.300 [-0.400, -0.200] | -0.050 [-0.100, +0.000] | 낮을수록 |', text)
        old = {k: v for k, v in row.items() if k not in ('vector_only', 'diff_vs_vector')}
        self.assertIn('| 신청 불가@10 | - | 5.0% | 0.0% | - |', '\n'.join(ffe.render(meta, {'hybrid': {'ineligible_k': old}})))


if __name__ == '__main__':
    unittest.main()
