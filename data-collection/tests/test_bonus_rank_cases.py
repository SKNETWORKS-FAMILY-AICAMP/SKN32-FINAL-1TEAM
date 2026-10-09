# -*- coding: utf-8 -*-
"""eval/bonus_rank_cases — 세기 0·0.2 순위 정리 함수(결정 0016, Codex 재재검수 §8). DB·모델 없음."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import bonus_rank_cases as rc  # noqa: E402


class MovesTests(unittest.TestCase):
    def test_moves(self):
        base, boosted = ['a', 'b', 'c', 'd'], ['a', 'c', 'b', 'd']
        self.assertEqual(rc.moves(base, boosted), [('c', 3, 2), ('b', 2, 3)])
        self.assertEqual(rc.moves(base, boosted, focus='c'), [('c', 3, 2)])
        self.assertEqual(rc.moves(base, base), [])
        self.assertEqual(rc.moves(['a'], ['x', 'a']), [('x', None, 1), ('a', 1, 2)])     # 새로 들어온 공고

    def test_keyword_idea(self):
        self.assertEqual(rc.keyword_idea('[전북] 2026년 중소기업육성자금 융자 지원계획 공고'),
                         '중소기업육성자금 융자 관련 지원을 알아보는 중소기업입니다')
        self.assertEqual(rc.keyword_idea('[경기] 공고'), '중소기업 지원 관련 지원을 알아보는 중소기업입니다')

    def test_first_region(self):
        self.assertEqual(rc.first_region('전북'), '전북')
        self.assertEqual(rc.first_region('경북,대구'), '경북')
        self.assertEqual(rc.first_region('전국'), '')
        self.assertEqual(rc.first_region(None), '')

    def test_pick_applicant_uses_service_filter(self):
        class App:
            calls = []

            @staticmethod
            def eligible_with_types(nid, row, age, today, check, types):
                App.calls.append(age)
                return (age is not None and age < 24, [], None)       # 업력 2년 미만만 통과하는 공고

        class Gate:
            @staticmethod
            def applicant_age(kind, founded, today):
                return (today.year - int(founded[:4])) * 12

        got = rc.pick_applicant(App, Gate, 'n', {}, date(2026, 10, 8))
        self.assertEqual(got, ('법인', '2025-01-01'))
        self.assertIsNone(rc.pick_applicant(type('X', (), {'eligible_with_types': staticmethod(lambda *a: (False, [], None))}),
                                            Gate, 'n', {}, date(2026, 10, 8)))


class SummaryTests(unittest.TestCase):
    def test_not_surfaced_and_skipped(self):
        meta = {'run_at': 't', 'today': '2026-10-08', 'boostable': 'b', 'top': 20, 'search': 'hybrid'}
        cases = [{'notice_id': 'x_000001', 'title': '공고', 'bonus_score': 5.0, 'rank_w0': None, 'rank_w02': None, 'moved': [],
                  'results': {'0.0': [], '0.2': []}},
                 {'notice_id': 'x_000002', 'title': '공고2', 'skipped': '공고 서버에 없음'}]
        md = rc.summary_md(meta, cases)
        self.assertIn('20위 밖(검색에 안 뜸)', md)
        self.assertIn('건너뜀: 공고 서버에 없음', md)


if __name__ == '__main__':
    unittest.main()
