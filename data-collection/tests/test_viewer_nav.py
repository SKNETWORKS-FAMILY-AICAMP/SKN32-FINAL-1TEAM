# -*- coding: utf-8 -*-
"""검증 화면 공통 메뉴 테스트 (2026-09-28 사용자 요청 — 화면을 메뉴로 오간다). DB·모델 없음."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from experiments.sql_semantic import viewer  # noqa: E402

client = TestClient(viewer.app)


class NavTests(unittest.TestCase):
    def test_every_menu_page_has_all_links_and_marks_itself(self):
        for path, _label in viewer.NAV:
            html = client.get(path).text
            self.assertEqual(html.count('class="sbnav"'), 1, path)
            for other, label in viewer.NAV:
                self.assertIn('<a href="%s"' % other, html, (path, other))
                self.assertIn(label, html)
            self.assertEqual(html.count('aria-current="page"'), 1, path)
            self.assertIn('<a href="%s" aria-current="page">' % path, html, path)

    def test_menu_sits_right_after_body(self):
        html = client.get('/industry-results').text
        body_end = html.index('>', html.index('<body')) + 1
        self.assertTrue(html[body_end:].startswith('<style>.sbnav'))

    def test_selftest_page_has_no_menu(self):
        self.assertNotIn('class="sbnav"', client.get('/compare/selftest').text)

    def test_flow_page_and_its_numbers(self):
        html = client.get('/flow').text
        self.assertIn('전체 흐름', html)
        self.assertIn('/api/flow', html)
        body = client.get('/api/flow').json()
        self.assertIn('active', body['industry'])
        self.assertIn('filter_first_eval', body['latest'])

    def test_page_without_body_gets_menu_in_front(self):
        self.assertTrue(viewer.nav_html('/').startswith('<style>'))


if __name__ == '__main__':
    unittest.main()
