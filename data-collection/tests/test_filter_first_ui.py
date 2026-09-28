# -*- coding: utf-8 -*-
"""매칭 순서 비교 화면(`/filter-first-eval`) 테스트. 가짜 결과 폴더만 쓴다(DB·모델 없음). 2026-09-28."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from experiments.sql_semantic import filter_first_results as ffr, viewer  # noqa: E402


def write_run(base, name, with_notices=True):
    path = os.path.join(base, name)
    os.makedirs(path)
    data = {'meta': {'as_of': '2026-09-15'}, 'summary': {'hybrid': {}},
            'lists': [{'qid': 'q1', 'mode': 'hybrid', 'system': 'legacy', 'ranked': ['bizinfo:PBLN_1', 'kstartup:2'],
                       'ineligible': ['kstartup:2'], 'why': {'kstartup:2': ['접수 마감']}}]}
    if with_notices:
        data['notices'] = {'bizinfo:PBLN_1': {'title': '공고 1'}, 'kstartup:2': {'title': '공고 2'}}
        data['queries'] = [{'qid': 'q1', 'idea': '아이디어'}]
    with io.open(os.path.join(path, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


class FilterFirstResultsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_run(self.dir, 'filter_first_eval_20260928T004448Z', with_notices=False)
        write_run(self.dir, 'filter_first_eval_20260928T004842Z')
        os.makedirs(os.path.join(self.dir, 'filter_first_eval_bad'))
        self.old = ffr.REPORTS
        ffr.REPORTS = self.dir

    def tearDown(self):
        ffr.REPORTS = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_latest_first_and_urls(self):
        d = ffr.load_run()
        self.assertEqual(d['run'], 'filter_first_eval_20260928T004842Z')
        self.assertEqual(d['runs'], ['filter_first_eval_20260928T004842Z', 'filter_first_eval_20260928T004448Z'])
        self.assertTrue(d['notices']['bizinfo:PBLN_1']['url'].startswith('https://www.bizinfo.go.kr/'))
        self.assertEqual(d['notices']['kstartup:2']['title'], '공고 2')

    def test_old_run_without_notices_still_loads(self):
        d = ffr.load_run('filter_first_eval_20260928T004448Z')
        self.assertEqual(d['notices']['kstartup:2']['title'], '')
        self.assertEqual(d['queries'], [{'qid': 'q1'}])

    def test_rejects_bad_names(self):
        self.assertIsNone(ffr.load_run('../etc'))
        self.assertIsNone(ffr.load_run('filter_first_eval_bad'))

    def test_api_and_page(self):
        client = TestClient(viewer.app)
        res = client.get('/api/filter-first-eval')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['run'], 'filter_first_eval_20260928T004842Z')
        self.assertEqual(client.get('/api/filter-first-eval', params={'run': 'nope'}).status_code, 404)
        page = client.get('/filter-first-eval')
        self.assertEqual(page.status_code, 200)
        self.assertIn('/api/filter-first-eval', page.text)


if __name__ == '__main__':
    unittest.main()
