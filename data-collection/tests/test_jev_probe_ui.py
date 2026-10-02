# -*- coding: utf-8 -*-
"""Jev 채점 시험 화면(`/jev-probe`) 테스트. 가짜 결과 폴더·가짜 평가 파일만 쓴다(DB·모델·Jev 없음). 2026-09-28."""
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

from experiments.sql_semantic import jev_probe_results as jpr, viewer  # noqa: E402

FAKE_SRC = {
    'truth': {('q1', 'bizinfo:PBLN_1'): 2, ('q1', 'kstartup:2'): 0},
    'human_reason': {('q1', 'bizinfo:PBLN_1'): '분야 일치'},
    'llm': {('q1', 'bizinfo:PBLN_1'): {'rel': 2, 'reason': '맞다', 'model': 'm'},
            ('q1', 'kstartup:2'): {'rel': 2, 'reason': '맞다', 'model': 'm'}},
    'persona': {'q1': '신청자 유형: 법인\n사업 아이디어: 비전 AI'},
    'snapshot': {'bizinfo:PBLN_1': {'title': '공고 1'}, 'kstartup:2': {'title': '공고 2'}},
}


def write_run(base, name):
    path = os.path.join(base, name)
    os.makedirs(path)
    with io.open(os.path.join(path, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump({'meta': {'pairs': 2}, 'same_pairs': {'n': 2}}, f)
    rows = [{'qid': 'q1', 'notice_id': 'bizinfo:PBLN_1', 'topic_rel': 1, 'confidence': 0.95,
             'probabilities': {'1': 0.95, '2': 0.05}},
            {'qid': 'q1', 'notice_id': 'kstartup:2', 'topic_rel': 0, 'confidence': 0.5,
             'probabilities': {'0': 0.5, '1': 0.5}}]
    with io.open(os.path.join(path, 'judgments.jsonl'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(json.dumps(r) for r in rows) + '\n')


class JevProbeResultsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_run(self.dir, 'jev_judge_probe_20260928T110547Z')
        write_run(self.dir, 'jev_judge_probe_20260928T110603Z')
        os.makedirs(os.path.join(self.dir, 'jev_judge_probe_bad'))
        self.old = jpr.REPORTS, jpr.sources
        jpr.REPORTS = self.dir
        jpr.sources = lambda: FAKE_SRC

    def tearDown(self):
        jpr.REPORTS, jpr.sources = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_joins_and_bins(self):
        d = jpr.load_run()
        self.assertEqual(d['run'], 'jev_judge_probe_20260928T110603Z')
        p = {x['notice_id']: x for x in d['pairs']}
        self.assertEqual((p['bizinfo:PBLN_1']['human'], p['bizinfo:PBLN_1']['jev'], p['bizinfo:PBLN_1']['llm']), (2, 1, 2))
        self.assertEqual(p['bizinfo:PBLN_1']['title'], '공고 1')
        self.assertTrue(p['kstartup:2']['url'].startswith('https://www.k-startup.go.kr/'))
        # 확신도 0.95 쌍: Jev 틀림(1≠2) · LLM 맞음 / 0.5 쌍: Jev 맞음 · LLM 틀림
        self.assertEqual(d['by_bin']['0.9 이상'], {'jev': {'n': 1, 'exact': 0.0}, 'llm': {'n': 1, 'exact': 1.0}})
        self.assertEqual(d['by_bin']['0.7 미만'], {'jev': {'n': 1, 'exact': 1.0}, 'llm': {'n': 1, 'exact': 0.0}})
        self.assertIsNone(d['by_bin']['0.7~0.9']['jev'])

    def test_rejects_bad_names(self):
        self.assertIsNone(jpr.load_run('../etc'))
        self.assertIsNone(jpr.load_run('jev_judge_probe_bad'))

    def test_api_and_page(self):
        client = TestClient(viewer.app)
        res = client.get('/api/jev-probe')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()['pairs']), 2)
        self.assertEqual(client.get('/api/jev-probe', params={'run': 'nope'}).status_code, 404)
        page = client.get('/jev-probe')
        self.assertEqual(page.status_code, 200)
        self.assertIn('/api/jev-probe', page.text)
        self.assertIn('aria-current="page"', page.text)


if __name__ == '__main__':
    unittest.main()
