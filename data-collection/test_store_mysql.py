"""기본은 입력 검증, MYSQL_INTEGRATION_TEST=1이면 독립 임시 DB 통합 검증."""
import copy
import json
import os
import unittest
import uuid
from unittest.mock import patch

import normalize
import store_mysql as store


def sample_payload():
    payload = normalize.normalize_sources([('bizinfo', [{
        'pblancId': 'sample', 'pblancNm': '한글 공고 🚀', 'bsnsSumryCn': '<p>지원 내용</p>',
        'reqstBeginEndDe': '예산 소진시까지', 'printFlpthNm': '/files/notice.pdf',
        'printFileNm': '공고문.pdf',
    }])])
    payload['generated_at'] = '2026-09-08T03:00:00+00:00'
    return payload


class ValidationTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(store.validate_payload(sample_payload()).hour, 3)

    def test_duplicate_id_rejected(self):
        payload = sample_payload()
        payload['notices'] *= 2
        with self.assertRaises(ValueError):
            store.validate_payload(payload)

    def test_unversioned_or_missing_field_rejected(self):
        for field in ('title', 'raw', 'source_id'):
            payload = sample_payload()
            del payload['notices'][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                store.validate_payload(payload)

    def test_rejected_rows_not_silently_saved(self):
        payload = sample_payload()
        payload['rejected'] = [{'reason': 'test'}]
        with self.assertRaises(ValueError):
            store.validate_payload(payload)

    def test_database_identifier_rejected(self):
        with patch.object(store.config, 'get', return_value='db`; DROP DATABASE x'), self.assertRaises(ValueError):
            store.database_name()


@unittest.skipUnless(os.environ.get('MYSQL_INTEGRATION_TEST') == '1', 'MySQL 통합 검증은 명시적 실행')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dbname = 'sbrain_test_' + uuid.uuid4().hex
        store.config.load()
        cls.env = patch.dict(os.environ, {'MYSQL_DATABASE': cls.dbname})
        cls.env.start()
        cls.connection = None
        cls.created = False
        try:
            # UUID DB를 생성하므로 기존 사용자 테이블과 섞이지 않는다.
            cls.connection = store.connect(init_db=True)
            cls.created = True
            store.init_schema(cls.connection)
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.connection:
                if cls.created and cls.dbname.startswith('sbrain_test_'):
                    with cls.connection.cursor() as cursor:
                        cursor.execute('DROP DATABASE `' + cls.dbname + '`')
                cls.connection.close()
        finally:
            cls.env.stop()

    def query(self, sql, args=()):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, args)
            result = cursor.fetchall()
        self.connection.commit()
        return result

    def payload(self):
        payload = sample_payload()
        row = payload['notices'][0]
        row['source_id'] = uuid.uuid4().hex
        row['notice_id'] = 'bizinfo:' + row['source_id']
        return payload

    def test_roundtrip_update_and_reimport(self):
        payload = self.payload()
        row = payload['notices'][0]
        store.store_payload(self.connection, payload, 'a' * 64)
        store.store_payload(self.connection, payload, 'a' * 64)
        result = self.query('SELECT id,title,region,apply_end,raw FROM notices WHERE notice_id=%s', (row['notice_id'],))[0]
        self.assertEqual(result[1], '한글 공고 🚀')
        self.assertIsNone(result[2])
        self.assertIsNone(result[3])
        self.assertEqual(json.loads(result[4]), row['raw'])
        self.assertEqual(self.query('SELECT COUNT(*) FROM notice_attachments WHERE notice_fk=%s', (result[0],))[0][0], 1)
        self.query("UPDATE notice_attachments SET download_status='downloaded' WHERE notice_fk=%s", (result[0],))
        payload['generated_at'] = '2026-09-09T03:00:00+00:00'
        row['title'] = '갱신한 제목'
        store.store_payload(self.connection, payload, 'b' * 64)
        self.assertEqual(self.query('SELECT title FROM notices WHERE id=%s', (result[0],))[0][0], '갱신한 제목')
        self.assertEqual(self.query('SELECT download_status FROM notice_attachments WHERE notice_fk=%s', (result[0],))[0][0], 'downloaded')

    def test_older_snapshot_skipped(self):
        payload = self.payload()
        store.store_payload(self.connection, payload, 'c' * 64)
        old = copy.deepcopy(payload)
        old['generated_at'] = '2026-09-07T03:00:00+00:00'
        old['notices'][0]['title'] = '과거 제목'
        result = store.store_payload(self.connection, old, 'd' * 64)
        self.assertEqual(result['skipped_older'], 1)
        self.assertEqual(self.query('SELECT title FROM notices WHERE notice_id=%s', (old['notices'][0]['notice_id'],))[0][0], '한글 공고 🚀')

    def test_database_error_rolls_back_whole_input(self):
        payload = self.payload()
        first = payload['notices'][0]
        first['source_id'] = 'a_' + first['source_id']
        first['notice_id'] = 'bizinfo:' + first['source_id']
        broken = copy.deepcopy(first)
        broken['source_id'] = 'z_' + uuid.uuid4().hex
        broken['notice_id'] = 'bizinfo:' + broken['source_id']
        # 유효 문자열이지만 MySQL TEXT 용량을 초과하여 첫 행 저장 뒤 DB 오류를 유도한다.
        broken['title'] = 'x' * 70000
        payload['notices'].append(broken)
        before = self.query('SELECT COUNT(*) FROM import_runs')[0][0]
        with self.assertRaises(Exception):
            store.store_payload(self.connection, payload, 'e' * 64)
        self.assertEqual(self.query('SELECT COUNT(*) FROM notices WHERE notice_id=%s', (first['notice_id'],))[0][0], 0)
        self.assertEqual(self.query('SELECT COUNT(*) FROM import_runs')[0][0], before)


if __name__ == '__main__':
    unittest.main()
