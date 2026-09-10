"""첨부 추출 저장 계약 및 임시 MySQL에서 성공 보존·역전 방지 검증."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import attachment_store as storage
import store_mysql
import test_store_mysql as fixtures


def result(fk=1, status='ok', minute=1):
    return {
        'attachment_fk': fk, 'status': status, 'kind': 'pdf',
        'text': '업력 조건을 확인할 수 없는 공고 본문입니다. 🚀' if status == 'ok' else None,
        'attempt_started_at': '2026-09-08T05:%02d:00+00:00' % minute,
        'attempted_at': '2026-09-08T05:%02d:10+00:00' % minute,
        'source_updated_at': None, 'extractor_version': 'doctext/1.0 test',
        'content_sha256': 'a' * 64 if status == 'ok' else None,
        'error': None if status == 'ok' else 'test error',
    }


class ValidationTests(unittest.TestCase):
    def test_empty_success_rejected(self):
        row = result()
        row['text'] = ' '
        with self.assertRaises(ValueError):
            storage.validate_result(row)

    def test_failed_text_rejected(self):
        row = result(status='parse_error')
        row['text'] = '오류 시 본문을 저장하지 않는다'
        with self.assertRaises(ValueError):
            storage.validate_result(row)

    def test_image_and_unknown_kinds_accepted(self):
        for kind in ('image', 'zip', 'rtf', 'unknown', None):
            row = result(status='unsupported')
            row['kind'] = kind
            self.assertEqual(storage.validate_result(row)['kind'], kind)

    def test_bad_timestamps_and_hash_rejected(self):
        for key, value in [('attempted_at', '2026-09-08T00:00:00'),
                           ('attempted_at', '2026-09-07T00:00:00Z'),
                           ('content_sha256', 'bad')]:
            row = result()
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                storage.validate_result(row)

    def test_error_redaction(self):
        with patch.object(store_mysql.config, 'get', return_value='fake-secret'):
            value = storage.safe_error('fake-secret https://example.com/?key=x password=test')
        self.assertNotIn('fake-secret', value)
        self.assertNotIn('example.com', value)
        self.assertNotIn('password=test', value)


@unittest.skipUnless(os.environ.get('MYSQL_INTEGRATION_TEST') == '1', '명시적으로 설정된 MySQL 통합 검증')
class AttachmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.IntegrationTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixtures.IntegrationTests.tearDownClass.__func__(cls)

    query = fixtures.IntegrationTests.query
    payload = fixtures.IntegrationTests.payload

    def setUp(self):
        self.data = self.payload()
        store_mysql.store_payload(self.connection, self.data, 'b' * 64)
        self.notice_id = self.data['notices'][0]['notice_id']
        self.fk = self.query('SELECT a.id FROM notice_attachments a JOIN notices n ON n.id=a.notice_fk WHERE n.notice_id=%s', (self.notice_id,))[0][0]

    def stored(self):
        return self.query('SELECT last_status,extracted_text,text_chars,last_source_updated_at,text_source_updated_at FROM attachment_texts WHERE attachment_fk=%s', (self.fk,))[0]

    def test_first_failure_then_success_then_failure_preserves_success(self):
        storage.save_attachment_result(self.connection, result(self.fk, 'download_fail'))
        self.assertEqual(self.stored()[0:3], ('download_fail', None, None))
        ok = result(self.fk, minute=2)
        storage.save_attachment_result(self.connection, ok)
        storage.save_attachment_result(self.connection, result(self.fk, 'parse_error', minute=3))
        self.assertEqual(self.stored()[0:3], ('parse_error', ok['text'], len(ok['text'])))

    def test_repeat_and_conflict(self):
        row = result(self.fk)
        self.assertEqual(storage.save_attachment_result(self.connection, row)['status'], 'saved')
        self.assertEqual(storage.save_attachment_result(self.connection, row)['status'], 'unchanged')
        row['text'] = '같은 시각이지만 다른 본문'
        with self.assertRaises(ValueError):
            storage.save_attachment_result(self.connection, row)

    def test_late_old_attempt_does_not_replace_recent(self):
        storage.save_attachment_result(self.connection, result(self.fk, minute=3))
        old = result(self.fk, 'download_fail', minute=1)
        old['attempted_at'] = '2026-09-08T05:59:00Z'
        self.assertEqual(storage.save_attachment_result(self.connection, old)['status'], 'skipped_older_attempt')
        self.assertEqual(self.stored()[0], 'ok')

    def test_source_change_and_old_success_preserved(self):
        storage.save_attachment_result(self.connection, result(self.fk))
        self.query('UPDATE notices SET source_updated_at_raw=%s WHERE notice_id=%s', (json.dumps('v2'), self.notice_id))
        self.assertEqual(storage.save_attachment_result(self.connection, result(self.fk, minute=2))['status'], 'skipped_source_changed')
        current = result(self.fk, 'download_fail', minute=3)
        current['source_updated_at'] = 'v2'
        storage.save_attachment_result(self.connection, current)
        self.assertEqual(self.stored()[3:], ('v2', None))
        current = result(self.fk, minute=4)
        current['source_updated_at'] = 'v2'
        storage.save_attachment_result(self.connection, current)
        self.assertEqual(self.stored()[3:], ('v2', 'v2'))

    def test_fallback_identity_and_mismatch(self):
        row = result(self.fk)
        del row['attachment_fk']
        row.update(notice_id=self.notice_id, role='notice', url='https://www.bizinfo.go.kr/files/notice.pdf')
        self.assertEqual(storage.save_attachment_result(self.connection, row)['attachment_fk'], self.fk)
        row['attachment_fk'] = self.fk
        row['notice_id'] = 'bizinfo:wrong'
        with self.assertRaises(ValueError):
            storage.save_attachment_result(self.connection, row)

    def test_refresh_and_inactivation_do_not_erase(self):
        row = result(self.fk)
        storage.save_attachment_result(self.connection, row)
        store_mysql.store_payload(self.connection, self.data, 'c' * 64)
        self.query('UPDATE notice_attachments SET active=FALSE WHERE id=%s', (self.fk,))
        self.assertEqual(self.stored()[1], row['text'])

    def test_rollback_on_commit_error(self):
        with patch.object(self.connection, 'commit', side_effect=RuntimeError('simulated commit failure')):
            with self.assertRaises(RuntimeError):
                storage.save_attachment_result(self.connection, result(self.fk))
        self.assertEqual(self.query('SELECT COUNT(*) FROM attachment_texts WHERE attachment_fk=%s', (self.fk,))[0][0], 0)

    def test_missing_attachment_and_large_text(self):
        with self.assertRaises(ValueError):
            storage.save_attachment_result(self.connection, result(2**63))
        row = result(self.fk)
        row['text'] = '한글🚀' * 50000
        storage.save_attachment_result(self.connection, row)
        self.assertEqual(self.stored()[1:3], (row['text'], 150000))

    def test_failure_statuses_are_distinct(self):
        for minute, status in enumerate(('image_only', 'unsupported', 'download_fail', 'parse_error', 'empty_text'), 1):
            row = result(self.fk, status, minute)
            row['kind'] = 'image' if status == 'image_only' else 'unknown'
            storage.save_attachment_result(self.connection, row)
            self.assertEqual(self.stored()[0:3], (status, None, None))

    def test_concurrent_results_keep_newer_attempt(self):
        older, newer = result(self.fk, minute=4), result(self.fk, minute=5)
        older['text'], newer['text'] = '과거 성공 본문', '최근 성공 본문'
        def worker(row):
            connection = store_mysql.connect()
            try:
                return storage.save_attachment_result(connection, row)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(worker, (newer, older)))
        self.assertTrue(all(item['status'] in ('saved', 'skipped_older_attempt') for item in outcomes))
        self.assertEqual(self.stored()[1], newer['text'])


if __name__ == '__main__':
    unittest.main()
