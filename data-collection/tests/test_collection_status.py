# -*- coding: utf-8 -*-
"""수집 상태 판정 — 기능정의서 R-1 ①·R-3 ② (2026-09-28). DB 없음(가짜 연결)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search import collection_status as cs  # noqa: E402

NOW = datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)


def batch(status, hours_ago=3, degraded=None, error=None):
    return {'status': status, 'run_at': NOW - timedelta(hours=hours_ago), 'degraded': degraded or [], 'error': error}


class JudgeTests(unittest.TestCase):
    def test_fresh_store_is_normal(self):
        out = cs.judge(NOW - timedelta(hours=3), NOW, batch('ok'))
        self.assertEqual(out['status'], '정상')
        self.assertFalse(out['block_matching'])

    def test_older_than_24h_is_delayed_and_blocks(self):
        out = cs.judge(NOW - timedelta(hours=25), NOW)
        self.assertEqual(out['status'], '지연')
        self.assertTrue(out['block_matching'])
        self.assertIn('25.0시간', out['reasons'][0])

    def test_no_store_record_is_failure(self):
        self.assertEqual(cs.judge(None, NOW)['status'], '실패')

    def test_latest_batch_error_is_failure_even_if_store_is_fresh(self):
        # 저장은 어제 성공, 오늘 배치는 저장 전 단계에서 실패 — 기존 데이터를 그대로 둔 상태
        out = cs.judge(NOW - timedelta(hours=20), NOW, batch('error', hours_ago=1, error='정규화할 입력이 없다'))
        self.assertEqual(out['status'], '실패')
        self.assertIn('정규화할 입력이 없다', out['reasons'][-1])

    def test_partial_source_failure_is_failure(self):
        out = cs.judge(NOW - timedelta(hours=3), NOW, batch('partial', degraded=['bizinfo']))
        self.assertEqual(out['status'], '실패')
        self.assertIn('bizinfo', out['reasons'][-1])

    def test_old_batch_log_does_not_override_newer_store(self):
        # 로그의 실패가 마지막 저장보다 오래됐으면(그 뒤 성공 저장이 있었으면) 반영하지 않는다
        out = cs.judge(NOW - timedelta(hours=3), NOW, batch('error', hours_ago=30))
        self.assertEqual(out['status'], '정상')

    def test_reused_bizinfo_snapshot_is_failure(self):
        out = cs.judge(NOW - timedelta(hours=3), NOW, None, bizinfo_at=NOW - timedelta(hours=40))
        self.assertEqual(out['status'], '실패')
        self.assertIn('기업마당', out['reasons'][-1])

    def test_bizinfo_stamp_parsed_from_report(self):
        report = {'inputs': [{'source': 'kstartup', 'input_file': 'data/notices.json'},
                             {'source': 'bizinfo', 'input_file': r'C:\x\data\raw\bizinfo_20260928T000004448299Z.json'}]}
        self.assertEqual(cs.bizinfo_snapshot_at(report), datetime(2026, 9, 28, 0, 0, 4, tzinfo=timezone.utc))
        self.assertIsNone(cs.bizinfo_snapshot_at({'inputs': []}))


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        pass

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        return FakeCursor(self.row)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_check_reads_db_and_log(self):
        log = os.path.join(self.tmp, 'collect_log.jsonl')
        with io.open(log, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'status': 'ok', 'count': 1, 'run_at': '2026-09-28T08:59:00'}) + '\n')   # K-Startup 단독 행
            f.write(json.dumps({'status': 'partial', 'job': 'pipeline', 'degraded': ['bizinfo'],
                                'sources': {}, 'run_at': '2026-09-28T09:02:00'}) + '\n')             # 한국 시간
        report = {'inputs': [{'source': 'bizinfo', 'input_file': 'bizinfo_20260928T000004Z.json'}]}
        conn = FakeConnection((datetime(2026, 9, 28, 0, 0, 7), json.dumps(report)))
        out = cs.check(conn, now=NOW, log_path=log)
        self.assertEqual(out['status'], '실패')                  # 로그의 부분 실패(09:02 KST = 00:02 UTC)가 반영됨
        self.assertEqual(out['basis'], ['db', 'log'])
        self.assertEqual(out['latest_batch']['run_at'], '2026-09-28T00:02:00+00:00')

    def test_check_without_log_uses_db_only(self):
        conn = FakeConnection((datetime(2026, 9, 26, 0, 0, 0), '{}'))
        out = cs.check(conn, now=NOW, log_path=os.path.join(self.tmp, 'none.jsonl'))
        self.assertEqual(out['status'], '지연')
        self.assertEqual(out['basis'], ['db'])


class ViewerTests(unittest.TestCase):
    def test_api_and_page(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from experiments.sql_semantic import viewer
        client = TestClient(viewer.app)
        fake_now = cs.judge(NOW - timedelta(hours=30), NOW)
        fake_now.update({'basis': ['db'], 'checked_at': NOW.isoformat(), 'latest_batch': None,
                         'bizinfo_snapshot_at': None, 'stored_counts': None})
        with patch.object(cs, 'check', return_value=fake_now),                 patch.object(cs, 'history', return_value={'runs': [], 'gaps': [], 'blocked_hours': 0,
                                                          'span_days': 0, 'max_age_hours': 24}):
            body = client.get('/api/collection-status').json()
        self.assertEqual(body['now']['status'], '지연')
        with patch.object(cs, 'check', side_effect=RuntimeError('db down')):
            self.assertEqual(client.get('/api/collection-status').status_code, 503)
        self.assertIn('<a href="/collection-status" aria-current="page">', client.get('/collection-status').text)


if __name__ == '__main__':
    unittest.main()
