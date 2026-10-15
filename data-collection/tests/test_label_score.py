# -*- coding: utf-8 -*-
"""Codex 판정 대조(label_score) — 가짜 꾸러미로 (2026-09-28). 표준 라이브러리만."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiments.sql_semantic import label_score as ls  # noqa: E402


def cell(status, strength=None):
    return {'status': status, 'strength': strength, 'evidence': None}


def llm(pre, sole=('not_mentioned',), corp=('not_mentioned',)):
    return {'pre_founder': cell(*pre), 'sole_proprietor': cell(*sole), 'corporation': cell(*corp)}


def write(folder, name, rows):
    with io.open(os.path.join(folder, name), 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


class LabelScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        write(self.tmp, 'answers_hidden.jsonl', [
            {'item_id': 'P001', 'group': 'A', 'notice_id': 'n1', 'varies': False, 'llm': llm(('not_allowed', 'strong'))},
            {'item_id': 'P002', 'group': 'A', 'notice_id': 'n2', 'varies': False, 'llm': llm(('not_allowed', 'strong'))},
            {'item_id': 'P003', 'group': 'B', 'notice_id': 'n3', 'varies': False, 'llm': llm(('allowed', 'strong'))},
            {'item_id': 'P004', 'group': 'E', 'notice_id': 'n4', 'varies': False, 'llm': llm(('implied_no', 'strong'))},
            {'item_id': 'P005', 'group': 'F', 'notice_id': 'n5', 'varies': False, 'llm': llm(('not_mentioned',))},
            {'item_id': 'I001', 'group': 'industry', 'notice_id': 'n6'},
        ])
        write(self.tmp, 'applicant_labels.jsonl', [
            {'item_id': 'P001', 'pre_founder': 'not_allowed', 'sole_proprietor': 'not_mentioned', 'corporation': 'not_mentioned'},
            {'item_id': 'P002', 'pre_founder': 'allowed', 'sole_proprietor': 'not_mentioned', 'corporation': 'not_mentioned'},
            {'item_id': 'P003', 'pre_founder': 'allowed', 'sole_proprietor': 'not_mentioned', 'corporation': 'not_mentioned'},
            {'item_id': 'P004', 'pre_founder': 'implied_no', 'sole_proprietor': 'not_mentioned', 'corporation': 'not_mentioned'},
            {'item_id': 'P005', 'pre_founder': 'not_mentioned', 'sole_proprietor': 'not_allowed', 'corporation': 'not_mentioned'},
        ])
        write(self.tmp, 'industry_labels.jsonl', [
            {'item_id': 'I001', 'restricted': True, 'sections': [{'code': 'I', 'verdict': 'ineligible'},
                                                                 {'code': 'C', 'verdict': 'eligible'}]},
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_scores(self):
        s = ls.score(self.tmp)
        self.assertEqual(s['gate_pre_strong'], {'hit': 1, 'total': 2, 'rate': 0.5})
        self.assertEqual(s['gate_pre_strong_wrong_allowed'], ['P002'])       # 신청 가능한 공고를 뺄 오류
        self.assertEqual(s['b_text_over_api']['hit'], 1)
        self.assertEqual(s['pre_implied_no']['hit'], 1)
        self.assertEqual(s['missed_in_F'], ['P005'])
        self.assertEqual(s['industry_section_verdicts'], {'ineligible': 1, 'eligible': 1})
        self.assertEqual(s['industry_wrong_push'][0]['section'], 'C')

    def test_main_writes_files(self):
        ls.main([self.tmp])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'score.md')))
        with io.open(os.path.join(self.tmp, 'score.md'), encoding='utf-8') as f:
            self.assertIn('AI 참고 정답', f.read())

    def test_empty_labels_do_not_crash(self):
        os.remove(os.path.join(self.tmp, 'applicant_labels.jsonl'))
        s = ls.score(self.tmp)
        self.assertEqual(s['applicant_labeled'], 0)
        self.assertIsNone(s['gate_pre_strong']['rate'])


if __name__ == '__main__':
    unittest.main()
