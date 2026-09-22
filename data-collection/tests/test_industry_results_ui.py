# -*- coding: utf-8 -*-
"""업종 추출 결과 화면(`/industry-results`) 테스트. 가짜 결과 폴더만 쓴다(DB·LLM 없음)."""
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

from experiments.sql_semantic import industry_results as ir, viewer  # noqa: E402


def v3_row(nid, status, allowed=(), excluded=(), complete=False, downgraded='', llm_status=None):
    return {'notice_id': nid, 'title': '공고 ' + nid, 'category': '기술',
            'regex': {'status': 'unknown'},
            'llm': {'status': status, 'llm_status': llm_status or status,
                    'allowed': [{'text': t, 'label': l, 'label_basis': 'exact' if l else ''} for t, l in allowed],
                    'excluded': [{'text': t} for t in excluded], 'list_complete': complete,
                    'quote': '지원대상: …', 'reason': '', 'downgraded': downgraded, 'dropped': []}}


class IndustryResultsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.run = os.path.join(self.dir, 'industry_llm_full_test')
        os.makedirs(self.run)
        rows = [v3_row('bizinfo:PBLN_1', 'known', [('제조업', '제조업'), ('무역업', '')], complete=True),
                v3_row('kstartup:2', 'known', [('제조업', '제조업')], excluded=['유흥업']),
                v3_row('bizinfo:PBLN_3', 'unknown', downgraded='근거 문장이 원문에 없음', llm_status='known'),
                v3_row('bizinfo:PBLN_4', 'no_limit')]
        with io.open(os.path.join(self.run, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        with io.open(os.path.join(self.run, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'engine': 'gpt-5.6-luna@medium', 'prompt': 'v3', 'take_all': True, 'cost_usd': 0.01}, f)
        self.old = ir.REPORTS
        ir.REPORTS = self.dir

    def tearDown(self):
        ir.REPORTS = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_summary_and_counts(self):
        d = ir.load_run('industry_llm_full_test')
        s = d['summary']
        self.assertEqual((s['total'], s['known'], s['no_limit'], s['unknown']), (4, 2, 1, 1))
        self.assertEqual((s['complete'], s['downgraded'], s['with_excluded']), (1, 1, 1))
        self.assertEqual(d['top_texts'][0], ('제조업', 2))
        self.assertIn(('무역업', 1), d['top_texts'])
        self.assertEqual(d['top_labels'], [('제조업', 2)])          # 무역업은 표준 이름이 아니다
        self.assertEqual(d['top_excluded'], [('유흥업', 1)])

    def test_big_groups(self):
        d = ir.load_run('industry_llm_full_test')
        groups = {code: n for code, _name, n in d['top_groups']}
        self.assertEqual(groups, {'C': 2, 'G': 1})              # 제조업 2건 + 무역업(G) 1건, unknown·no_limit 은 세지 않는다
        self.assertEqual(d['group_coverage'], {'known': 2, 'standard': 2, 'only_field_or_all': 0, 'none': 0})
        row = {r['id']: r for r in d['rows']}['bizinfo:PBLN_1']
        self.assertEqual(row['groups'], ['C', 'G'])
        self.assertEqual(d['group_names']['C'], '제조업')

    def test_urls_from_notice_id(self):
        self.assertTrue(ir.notice_url('bizinfo:PBLN_1').endswith('pblancId=PBLN_1'))
        self.assertTrue(ir.notice_url('kstartup:2').endswith('pbancSn=2'))
        self.assertEqual(ir.notice_url('other:3'), '')

    def test_run_name_is_restricted(self):
        for bad in ('../secret', 'industry_llm_x/../../etc', 'reports', ''):
            self.assertIsNone(ir.run_path(bad))
        self.assertIsNotNone(ir.run_path('industry_llm_full_test'))

    def test_list_runs(self):
        runs = ir.list_runs()
        self.assertEqual([r['name'] for r in runs], ['industry_llm_full_test'])
        self.assertTrue(runs[0]['take_all'])

    def test_counterpart_marks_newly_known(self):
        rough = os.path.join(self.dir, 'industry_llm_full_test_rough')
        os.makedirs(rough)
        rows = [v3_row('bizinfo:PBLN_1', 'known', [('제조업', '제조업')]),
                v3_row('bizinfo:PBLN_3', 'known', [('관광업', '')]),         # 엄격에서는 unknown 이던 것
                v3_row('bizinfo:PBLN_4', 'no_limit')]
        with io.open(os.path.join(rough, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        with io.open(os.path.join(rough, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'engine': 'gpt-5.6-luna@medium', 'prompt': 'v3', 'profile': 'rough',
                       'counterpart': 'industry_llm_full_test', 'reverified_from': 'x'}, f)
        d = ir.load_run('industry_llm_full_test_rough')
        self.assertEqual(d['summary']['newly_known'], 1)
        self.assertEqual({r['id']: r['counter_status'] for r in d['rows']}['bizinfo:PBLN_3'], 'unknown')
        self.assertEqual(ir.default_run(), ir.DEFAULT_RUN)          # 테스트 폴더에는 기본 순서의 폴더가 없다

    def test_matching_status_counts(self):
        final = os.path.join(self.dir, 'industry_llm_full_test_final')
        os.makedirs(final)
        rows = []
        for nid, st, ist in (('a', 'known', 'known'), ('b', 'unknown', 'not_mentioned'), ('c', 'unknown', 'not_mentioned'),
                             ('d', 'unknown', 'excluded_only'), ('e', 'unknown', 'unknown')):
            r = v3_row('bizinfo:PBLN_' + nid, st, [('제조업', '제조업')] if st == 'known' else [])
            r['llm']['industry_status'] = ist
            r['llm']['industry_status_why'] = '자격 문장을 찾지 못함' if ist == 'unknown' else ''
            r['source_run'] = 'long' if nid == 'e' else 'base'
            rows.append(r)
        with io.open(os.path.join(final, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        with io.open(os.path.join(final, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'prompt': 'v3', 'merged_from': {'base': 'base', 'override': 'long', 'override_max_chars': 18000}}, f)
        d = ir.load_run('industry_llm_full_test_final')
        self.assertEqual(d['summary']['istatus'], {'known': 1, 'not_mentioned': 2, 'excluded_only': 1, 'unknown': 1})
        self.assertEqual(d['istatus_names']['not_mentioned'], '제한 없음(언급 없음·추정)')
        e = {r['id']: r for r in d['rows']}['bizinfo:PBLN_e']
        self.assertEqual((e['istatus'], e['istatus_why'], e['source_run']), ('unknown', '자격 문장을 찾지 못함', 'long'))
        self.assertEqual(d['meta']['merged_from']['override_max_chars'], 18000)
        self.assertIsNone(ir.load_run('industry_llm_full_test')['summary']['istatus'])   # 옛 결과는 판정 칸이 없다

    def test_raw_allowed_shown_as_dropped(self):
        row = v3_row('bizinfo:PBLN_9', 'unknown')
        row['llm']['raw_allowed'] = [{'text': '제조업'}]
        self.assertEqual(ir._row(row)['dropped'], ['제조업'])

    def test_api_and_page(self):
        client = TestClient(viewer.app)
        res = client.get('/api/industry-results', params={'run': 'industry_llm_full_test'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['summary']['known'], 2)
        self.assertEqual(client.get('/api/industry-results', params={'run': '../x'}).status_code, 404)
        page = client.get('/industry-results')
        self.assertEqual(page.status_code, 200)
        self.assertIn('업종 추출 결과', page.text)


if __name__ == '__main__':
    unittest.main()
