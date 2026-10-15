# -*- coding: utf-8 -*-
"""eval/metrics_logs — 배치 기록 합치기·중복 제거·순서·못 읽음 처리 (서버 없이)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import metrics_logs as ml  # noqa: E402


def jl(*rows):
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)


class CollectLogMergeTests(unittest.TestCase):
    def test_same_run_counted_once_and_sorted(self):
        a = jl({'run_at': '2026-09-15T09:00:01', 'job': 'pipeline', 'status': 'ok'},
               {'run_at': '2026-09-14T09:36:01', 'job': 'pipeline', 'status': 'ok'})
        b = jl({'run_at': '2026-09-15T09:00:01', 'job': 'pipeline', 'status': 'ok', 'extra': 1},
               {'run_at': '2026-10-14T00:00:04', 'job': 'pipeline', 'status': 'ok'})
        rows = ml.merge_collect_logs(a, b)
        self.assertEqual([r['run_at'] for r in rows],
                         ['2026-09-14T09:36:01', '2026-09-15T09:00:01', '2026-10-14T00:00:04'])
        self.assertNotIn('extra', rows[1])          # 먼저 나온 것(복사본)을 남긴다

    def test_job_is_part_of_identity(self):
        rows = ml.merge_collect_logs(jl({'run_at': 't1', 'job': 'pipeline'}, {'run_at': 't1', 'count': 5}))
        self.assertEqual(len(rows), 2)

    def test_broken_and_blank_lines_skipped(self):
        rows = ml.merge_collect_logs('{"run_at": "t1", "job": "pipeline"}\n\n{"run_at": "t2", "jo')
        self.assertEqual(len(rows), 1)

    def test_empty_inputs(self):
        self.assertEqual(ml.merge_collect_logs('', None), [])


class RunLogMergeTests(unittest.TestCase):
    PC = ('[2026-09-15  9:00:01.87] start\n'
          '  업종 추출 47건 · 약 $0.0206\n'
          '[2026-09-15  9:12:00.10] exit=0\n')
    SERVER = ('[2026-09-15  9:00:01.87] start\n'
              '  업종 추출 47건 · 약 $0.0206\n'
              '[2026-09-15  9:12:00.10] exit=0\n'
              '[2026-10-14 09:00:02] start\n'
              '  업종 추출 47건 · 약 $0.0206\n'
              '[2026-10-14 09:08:18] exit=0\n')

    def test_blocks_deduped_but_same_text_on_other_days_kept(self):
        merged = ml.merge_run_logs(self.PC, self.SERVER)
        self.assertEqual(merged.count('[2026-09-15  9:00:01.87] start'), 1)
        self.assertEqual(merged.count('업종 추출 47건'), 2)          # 줄 단위로 지우지 않는다

    def test_order_by_header_time_handles_both_formats(self):
        merged = ml.merge_run_logs('[2026-10-14 09:00:02] start\n', '[2026-09-15  9:00:01.87] start\n')
        self.assertLess(merged.index('2026-09-15'), merged.index('2026-10-14'))

    def test_header_key_pads_hour(self):
        self.assertEqual(ml._header_key('[2026-09-15  9:00:01.87] start'), '2026-09-15 09:00:01')
        self.assertIsNone(ml._header_key('  업종 추출'))

    def test_carriage_return_inside_line_kept(self):
        text = '[2026-09-15 09:00:00] start\nBatches: 0%\rBatches: 100%\r\n[2026-09-15 09:01:00] exit=0\n'
        merged = ml.merge_run_logs(text)
        self.assertIn('Batches: 0%\rBatches: 100%', merged)
        self.assertEqual(merged.count('\n'), 3)

    def test_preamble_before_first_header_kept(self):
        merged = ml.merge_run_logs('머리 없는 줄\n[2026-09-15 09:00:00] start\n')
        self.assertTrue(merged.startswith('머리 없는 줄'))


class LoadAndSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {'host': 'u@h', 'key': 'k', 'remote': '/r', 'name': 'test-batch'}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_paths_are_gitignored_names(self):
        p = ml.snapshot_paths('sbrain-web', self.tmp)
        self.assertEqual(os.path.dirname(p['collect_log.jsonl']), self.tmp)   # 하위 폴더가 아니다
        self.assertTrue(p['collect_log.jsonl'].endswith('.jsonl'))
        self.assertTrue(p['run.log'].endswith('.log'))

    def test_server_unreachable_falls_back_to_snapshot(self):
        p = ml.snapshot_paths('test-batch', self.tmp)
        with open(p['collect_log.jsonl'], 'w', encoding='utf-8') as f:
            f.write(jl({'run_at': '2026-09-14T09:36:01', 'job': 'pipeline'}))
        with mock.patch.object(ml, 'fetch', return_value=({'collect_log.jsonl': None, 'run.log': None},
                                                           ['collect_log.jsonl: 복사 실패(종료 코드 255)'])):
            got = ml.load(self.cfg, data_dir=self.tmp)
        self.assertEqual(len(got['collect_rows']), 1)
        self.assertEqual(got['sources'], ['이 PC 복사본(test-batch)'])
        self.assertTrue(got['errors'])
        joined = ' '.join(got['sources'] + got['errors'])
        self.assertNotIn('u@h', joined)                 # 주소를 드러내지 않는다

    def test_snapshot_keeps_rows_only_in_copy(self):
        p = ml.snapshot_paths('test-batch', self.tmp)
        with open(p['collect_log.jsonl'], 'w', encoding='utf-8') as f:
            f.write(jl({'run_at': '2026-09-14T09:36:01', 'job': 'pipeline'}))
        live = {'collect_log.jsonl': jl({'run_at': '2026-10-20T04:00:01', 'job': 'pipeline'}),
                'run.log': '[2026-10-20 04:00:01] start\n'}
        with mock.patch.object(ml, 'fetch', return_value=(live, [])):
            r = ml.snapshot(self.cfg, data_dir=self.tmp)
        self.assertTrue(r['saved'])
        rows = ml.merge_collect_logs(ml._read(p['collect_log.jsonl']))
        self.assertEqual([x['run_at'] for x in rows], ['2026-09-14T09:36:01', '2026-10-20T04:00:01'])

    def test_snapshot_not_saved_when_nothing_read(self):
        with mock.patch.object(ml, 'fetch', return_value=({'collect_log.jsonl': None, 'run.log': None}, ['x'])):
            r = ml.snapshot(self.cfg, data_dir=self.tmp)
        self.assertFalse(r['saved'])
        self.assertFalse(os.listdir(self.tmp))

    def test_settings_env_override(self):
        with mock.patch.dict(os.environ, {'METRICS_BATCH_HOST': 'x@y', 'METRICS_BATCH_NAME': 'team'}):
            cfg = ml.settings()
        self.assertEqual(cfg['host'], 'x@y')
        self.assertEqual(cfg['name'], 'team')

    def test_summary(self):
        s = ml.summary([{'run_at': '2026-09-14T09:36:01', 'job': 'pipeline'}, {'run_at': '2026-10-14T00:00:04', 'job': 'pipeline'},
                        {'run_at': '2026-10-14T00:01:00', 'count': 3}])
        self.assertEqual((s['pipeline_runs'], s['first_day'], s['last_day']), (2, '2026-09-14', '2026-10-14'))


if __name__ == '__main__':
    unittest.main()
