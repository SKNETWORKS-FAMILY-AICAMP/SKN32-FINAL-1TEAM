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


if __name__ == '__main__':
    unittest.main()
