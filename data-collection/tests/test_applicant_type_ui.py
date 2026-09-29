# -*- coding: utf-8 -*-
"""신청자 유형 결과 화면(`/applicant-types`) — 가짜 결과 폴더만 쓴다(DB·LLM 없음). 2026-09-28."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from experiments.sql_semantic import applicant_type_results as atr, viewer  # noqa: E402

client = TestClient(viewer.app)


def cell(status, strength=None, evidence=None, dropped=None):
    return {'status': status, 'strength': strength, 'evidence': evidence, 'dropped': dropped, 'raw_status': status}


ROWS = [
    {'notice_id': 'bizinfo:PBLN_1', 'source': 'bizinfo', 'title': '사업자 전용', 'target_category': '소상공인',
     'legacy': {'business_type': [], 'pre_startup_allowed': True},
     'llm': {'pre_founder': cell('not_allowed', 'strong', '사업자등록증 보유'), 'sole_proprietor': cell('not_mentioned'),
             'corporation': cell('not_mentioned'), 'varies': False, 'reason': 'r'}},
    {'notice_id': 'kstartup:2', 'source': 'kstartup', 'title': '예비 가능', 'age_condition_raw': '3년미만',
     'llm': {'pre_founder': cell('allowed', 'strong', '여성 예비창업자'), 'sole_proprietor': cell('not_mentioned'),
             'corporation': cell('not_mentioned'), 'varies': False, 'reason': ''}},
]


class ApplicantTypeUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        done = os.path.join(self.tmp, 'applicant_type_llm_20260928T000000Z')
        os.makedirs(done)
        with io.open(os.path.join(done, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for r in ROWS:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        with io.open(os.path.join(done, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'run_at': '2026-09-28T00:00:00+00:00', 'engine': 'x', 'n': 2, 'n_bizinfo': 1,
                       'n_kstartup': 1, 'failures': 0, 'cost_usd': 0.01}, f)
        running = os.path.join(self.tmp, 'applicant_type_llm_full_20260928T010000Z')
        os.makedirs(running)
        with io.open(os.path.join(running, 'checkpoint.jsonl'), 'w', encoding='utf-8') as f:
            f.write('{}\n{}\n{}\n')
        self.patch = patch.object(atr, 'REPORTS', self.tmp)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp)

    def test_runs_show_running_progress_and_default_is_finished(self):
        body = client.get('/api/applicant-types/runs').json()
        running = [r for r in body['runs'] if r['running']]
        self.assertEqual(running[0]['progress'], 3)
        self.assertEqual(body['default'], 'applicant_type_llm_20260928T000000Z')
        out = client.get('/api/applicant-types?run=applicant_type_llm_full_20260928T010000Z').json()
        self.assertTrue(out['running'])

    def test_summary_and_diffs(self):
        d = client.get('/api/applicant-types').json()
        s = d['summary']
        self.assertEqual(s['pre_strong_no'], 1)
        self.assertEqual(s['gate_any'], 1)
        self.assertEqual(s['legacy_diff'], 1)          # 기존 4o-mini 는 예비 가능, LLM 은 불가
        self.assertEqual(s['api_diff'], 1)             # API "3년미만" → 예비 불가, 본문은 가능
        row = next(r for r in d['rows'] if r['id'] == 'bizinfo:PBLN_1')
        self.assertIn('bizinfo.go.kr', row['url'])

    def test_bad_run_name_is_rejected(self):
        self.assertEqual(client.get('/api/applicant-types?run=../etc').status_code, 404)

    def test_page_has_menu(self):
        html = client.get('/applicant-types').text
        self.assertIn('<a href="/applicant-types" aria-current="page">', html)
        self.assertIn('/api/applicant-types', html)


if __name__ == '__main__':
    unittest.main()
