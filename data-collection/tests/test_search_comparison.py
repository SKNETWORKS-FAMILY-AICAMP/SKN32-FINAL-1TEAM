# -*- coding: utf-8 -*-
r"""검색 비교 도구의 안전장치 — Codex 리뷰(2026-09-18) 회귀 테스트.

  .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_search_comparison -v

여기서 고정하는 것
  · 실행 중 날짜가 바뀌면 **무효 실행**으로 처리하고 비교표를 만들지 않는다 (종료코드 3)
  · 정합성 검사에 걸리면 검색을 시작하지 않고 멈춘다 (종료코드 2)
  · 검색은 실제로 하지 않는다. app.boot·data_check·app.match 를 가짜로 바꾼다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'eval'))
import shutil
import tempfile
import unittest
from unittest.mock import patch

import search_comparison as sc

HEALTHY = {
    'db_notices': 10, 'chroma_vectors': 10, 'bm25_docs': 10, 'server_rows': 10,
    'db_equals_chroma': True, 'db_equals_bm25': True, 'db_equals_rows': True,
    'bm25_content_checked': True, 'bm25_content_mismatch_count': 0,
    'vector_file': {'checked': True, 'stale_count': 0, 'missing_count': 0},
    # 2026-09-21 부터 Chroma 실제 벡터 검사가 통과해야 비교가 진행된다
    'chroma_content': {'status': '통과', 'failure_lines': []},
    'chroma_content_verified': True,
}


# 서버를 켜기 전 사전 검사(chroma_integrity.check)가 통과한 모양
PREFLIGHT_OK = {'status': '통과', 'chroma_content_verified': True, 'parts': {},
                'corpus_sha256': 'test'}


def fake_response():
    return {'query': '창업 지원', 'count': 5, 'encode_ms': 1.0, 'search_ms': 1.0,
            'depth': 50, 'search_rounds': 1, 'source': 'chroma', 'search': 'dense',
            'demote_groups': False, 'demoted': [], 'region': '', 'demote_region': False,
            'region_demoted': [], 'district': '', 'demote_district': False,
            'district_demoted': [], 'weights': {}, 'rule_words': [], 'stored_only': {},
            'why_not_used': {},
            'results': [{'notice_id': 'n%03d' % i, 'title': '공고 %d' % i, 'score': 0.5,
                         'band': '참고', 'region': '전국', 'apply_start': '', 'apply_end': '',
                         'apply_period_type': 'fixed', 'organizer': '', 'source': 'test',
                         'target_category': '', 'category': '', 'url': '',
                         'rules': {'groups': [], 'off_region': False, 'off_district': False}}
                        for i in range(1, 6)]}


class DateGuardTests(unittest.TestCase):
    """날짜가 섞였는지 판정하는 규칙."""

    def rows(self, *pairs):
        return [{'case_id': 'case%02d' % (i + 1), 'applied_date': b, 'applied_date_after': a}
                for i, (b, a) in enumerate(pairs)]

    def test_single_day_is_fine(self):
        self.assertEqual(sc.date_problems('2026-09-18', '2026-09-18',
                                          self.rows(('2026-09-18', '2026-09-18'))), [])

    def test_end_day_differs(self):
        problems = sc.date_problems('2026-09-18', '2026-09-19',
                                    self.rows(('2026-09-18', '2026-09-18')))
        self.assertTrue(any('종료일' in p for p in problems))

    def test_responses_from_two_days(self):
        problems = sc.date_problems('2026-09-18', '2026-09-19',
                                    self.rows(('2026-09-18', '2026-09-18'),
                                              ('2026-09-19', '2026-09-19')))
        self.assertTrue(any('섞였다' in p for p in problems))

    def test_date_changed_during_one_search(self):
        problems = sc.date_problems('2026-09-18', '2026-09-18',
                                    self.rows(('2026-09-18', '2026-09-19')))
        self.assertTrue(any('도중' in p for p in problems))


class InvalidRunTests(unittest.TestCase):
    """main() 이 실제로 무효 처리·중단을 하는지. 검색은 가짜로 대체한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patcher = patch.object(sc, 'REPORTS', self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def dirs(self):
        return sorted(os.listdir(self.tmp))

    def run_main(self, checks=HEALTHY, days=None):
        """days: date.today() 가 돌려줄 날짜를 순서대로 흉내 낸다."""
        from datetime import date as real_date
        calls = {'n': 0}

        class FakeDate(real_date):
            @classmethod
            def today(cls):
                seq = days or ['2026-09-18']
                value = seq[min(calls['n'], len(seq) - 1)]
                calls['n'] += 1
                return real_date.fromisoformat(value)

        with patch.object(sc.app, 'boot', lambda: None), \
                patch.object(sc, 'preflight_check', lambda: dict(PREFLIGHT_OK)), \
                patch.object(sc, 'data_check', lambda *a, **k: dict(checks)), \
                patch.object(sc.app, 'match', lambda req: fake_response()), \
                patch.object(sc, 'notice_records', lambda ids: []), \
                patch.object(sc, 'git_info', lambda: {'revision': 'test', 'branch': 'test',
                                                      'dirty_files': [], 'local_file_sha256': {}}), \
                patch.object(sc, 'date', FakeDate), \
                patch.object(sys, 'argv', ['search_comparison.py']):
            return sc.main()

    def test_healthy_run_writes_report(self):
        self.assertEqual(self.run_main(), 0)
        made = self.dirs()
        self.assertEqual(len(made), 1)
        files = os.listdir(os.path.join(self.tmp, made[0]))
        self.assertIn('comparison.html', files)
        self.assertIn('human_review.csv', files)

    def test_date_change_marks_run_invalid(self):
        # 40번의 검색 중간부터 날짜가 바뀐다
        days = ['2026-09-18'] * 20 + ['2026-09-19'] * 200
        self.assertEqual(self.run_main(days=days), 3)
        made = self.dirs()
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0].endswith('_INVALID_date_changed'), made[0])
        files = sorted(os.listdir(os.path.join(self.tmp, made[0])))
        self.assertIn('INVALID.md', files)
        self.assertIn('responses.jsonl', files)
        # 정상 결과물은 만들지 않는다
        self.assertNotIn('comparison.html', files)
        self.assertNotIn('human_review.csv', files)
        note = open(os.path.join(self.tmp, made[0], 'INVALID.md'), encoding='utf-8').read()
        self.assertIn('정상 결과로 인용하지 않는다', note)

    def test_integrity_failure_stops_before_searching(self):
        broken = dict(HEALTHY, db_equals_chroma=False)
        calls = []
        with patch.object(sc, 'run_case', lambda *a: calls.append(a)):
            self.assertEqual(self.run_main(checks=broken), 2)
        self.assertEqual(calls, [])          # 검색을 한 번도 하지 않았다
        self.assertEqual(self.dirs(), [])    # 결과 폴더도 남기지 않는다


if __name__ == '__main__':
    unittest.main()
