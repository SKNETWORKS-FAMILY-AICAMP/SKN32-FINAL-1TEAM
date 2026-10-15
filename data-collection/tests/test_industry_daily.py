# -*- coding: utf-8 -*-
"""매일 배치 12단계 업종 추출 — 가짜 공고·가짜 호출로 (2026-09-28). DB·LLM 없음."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collect import industry_daily as daily  # noqa: E402
from experiments.sql_semantic import industry_llm_sample as ils  # noqa: E402

DOC = '[지원대상] 도내 제조업을 영위하는 중소기업'


def item(nid, target=DOC):
    return ils.prepare({'notice_id': nid, 'title': nid, 'body': '', 'target_text': target, 'target_category': '',
                        'category': '', 'subcategory': '', 'attachments': [], 'regex': None})


ANSWER = {'status': 'known', 'allowed': [{'text': '제조업', 'label': '제조업', 'evidence': '도내 제조업을 영위하는 중소기업'}],
          'excluded': [], 'no_limit_text': '', 'list_complete': True, 'quote': '도내 제조업을 영위하는 중소기업',
          'reason': ''}


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, 'industries')
        self.reports = os.path.join(self.tmp, 'reports')
        os.makedirs(self.reports)
        self.seed = os.path.join(self.tmp, 'seed.jsonl')
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def call(self, it):
        self.calls.append(it['notice_id'])
        return ANSWER, {'in': 1000, 'out': 200, 'model': 'fake'}

    def write_seed(self, rows):
        with io.open(self.seed, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def run_batch(self, population, call=None, **kw):
        kw.setdefault('today', '2026-09-29')
        with patch.object(ils, 'pick_shared', lambda conn: [it['notice_id'] for it in population]), \
                patch.object(ils, 'load_items_shared', lambda conn, ids, max_chars=None: population):
            return daily.run_batch(connection=object(), call=call or self.call, out_dir=self.out, say=lambda *_: None,
                                   reports_dir=self.reports, seed=self.seed, **kw)

    def test_starts_from_seed_and_calls_only_new(self):
        old = item('a')
        self.write_seed([{'notice_id': 'a', 'document_sha256': old['document_sha256'], 'source_run': 'final6',
                          'llm': {'status': 'unknown'}, 'engine': ils.engine_id(daily.MODEL, daily.EFFORT)}])
        out = self.run_batch([old, item('b')])
        self.assertEqual(self.calls, ['b'])
        self.assertEqual((out['extracted'], out['total']), (1, 2))
        rows = {r['notice_id']: r for r in daily.read_jsonl(os.path.join(self.out, 'results.jsonl'))}
        self.assertEqual(rows['b']['llm']['industry_status'], 'known')       # 코드 검사(verify_v3)를 거친 값
        self.assertEqual(rows['b']['llm']['excerpt_cap'], 6000)               # 잘림 판정에 상한을 넘겼다
        self.assertEqual(rows['b']['source_run'], 'industry_daily_20260929')
        self.assertEqual(rows['a']['source_run'], 'final6')                   # 씨앗 행은 그대로
        with io.open(os.path.join(self.out, 'meta.json'), encoding='utf-8') as f:
            meta = json.load(f)
        self.assertEqual((meta['prompt'], meta['engine'], meta['profile']), ('v3', ils.engine_id(daily.MODEL, daily.EFFORT), 'rough'))
        self.assertEqual(rows['b']['engine'], ils.engine_id(daily.MODEL, daily.EFFORT))   # 행마다 엔진
        # 다시 돌리면 부르지 않는다
        self.calls.clear()
        again = self.run_batch([old, item('b')])
        self.assertEqual((again['extracted'], self.calls), (0, []))

    def test_other_engine_is_called_again_with_same_length(self):
        # 엔진이 없는 옛 행(gpt-5.6-luna@medium)과 엔진이 다른 행은 문서가 같아도 다시 뽑는다(결정 0013).
        # 9/28 에 18,000자로 다시 읽은 행은 18,000자로 다시 읽는다
        short = item('a')
        longer = ils.prepare({'notice_id': 'b', 'title': 'b', 'body': '', 'target_text': DOC, 'target_category': '',
                              'category': '', 'subcategory': '', 'regex': None,
                              'attachments': ['지원대상 제조업 업종 ' * 3000]})
        long_doc = ils.prepare(dict(longer), 18000)
        os.makedirs(os.path.join(self.reports, 'final6'))
        with io.open(os.path.join(self.reports, 'final6', 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'max_chars': 18000}, f)                                # 길게 다시 읽은 실행
        self.write_seed([
            {'notice_id': 'a', 'document_sha256': short['document_sha256'], 'llm': {'status': 'unknown'}},
            {'notice_id': 'b', 'document_sha256': long_doc['document_sha256'], 'source_run': 'final6',
             'llm': {'status': 'unknown', 'excerpt_cap': 18000}, 'engine': 'gpt-5.6-luna@medium'},
        ])
        seen = {}

        def call(it):
            seen[it['notice_id']] = len(it['document'])
            return self.call(it)
        out = self.run_batch([short, longer], call=call, limit=10)
        self.assertEqual(sorted(self.calls), ['a', 'b'])
        self.assertGreater(seen['b'], 6000)                                    # 기존 결과와 같은 길이
        rows = {r['notice_id']: r for r in daily.read_jsonl(os.path.join(self.out, 'results.jsonl'))}
        self.assertEqual(rows['b']['llm']['excerpt_cap'], 18000)
        self.assertEqual({rows['a']['engine'], rows['b']['engine']}, {ils.engine_id(daily.MODEL, daily.EFFORT)})
        self.assertEqual(out['extracted'], 2)
        self.calls.clear()
        self.run_batch([short, longer], call=call, limit=10, today='2026-09-30')
        self.assertEqual(self.calls, [])                                        # 새 엔진이면 다시 부르지 않는다

    def test_changed_document_is_called_again(self):
        self.write_seed([])
        self.run_batch([item('a')])
        self.calls.clear()
        self.run_batch([item('a', target='[지원대상] 도내 정보통신업 기업')], today='2026-09-30')
        self.assertEqual(self.calls, ['a'])

    def test_daily_limit_and_failures(self):
        self.write_seed([])
        population = [item('n%02d' % i) for i in range(5)]
        self.run_batch(population, limit=2)
        self.run_batch(population, limit=2)
        self.assertEqual(len(self.calls), 2)                                  # 같은 날 합이 상한

        def broken(it):
            self.calls.append(it['notice_id'])
            raise RuntimeError('api down')
        self.calls.clear()
        for day in ('2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04'):
            out = self.run_batch([item('x')], call=broken, today=day)
        self.assertEqual(self.calls.count('x'), daily.MAX_FAILURES)           # 세 번 실패하면 멈춘다
        self.assertEqual(out['gave_up'], 1)

    def test_lock_blocks_second_run(self):
        from collect import job_lock
        self.write_seed([])
        os.makedirs(self.out, exist_ok=True)
        with job_lock.acquire(os.path.join(self.out, 'run.lock')):
            out = self.run_batch([item('a')])
        self.assertEqual((out['error'], self.calls), ('busy', []))

    def test_upload_reads_daily_file_when_present(self):
        from collect import upload_judgments as up
        with patch.object(up, 'INDUSTRY_DAILY', os.path.join(self.tmp, 'none.jsonl')):
            self.assertEqual(up.industry_default_path(), up.INDUSTRY_SEED)
        path = os.path.join(self.tmp, 'daily.jsonl')
        io.open(path, 'w').close()
        with patch.object(up, 'INDUSTRY_DAILY', path):
            self.assertEqual(up.industry_default_path(), path)


if __name__ == '__main__':
    unittest.main()
