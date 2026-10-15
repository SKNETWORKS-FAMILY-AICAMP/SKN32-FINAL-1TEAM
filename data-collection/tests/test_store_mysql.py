"""기본은 입력 검증, MYSQL_INTEGRATION_TEST=1이면 독립 임시 DB 통합 검증."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import copy
import json
import os
import unittest
import uuid
from unittest.mock import patch

from collect import normalize
from shared import store_mysql as store


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


class FakeCursor:
    """close_missing 이 보내는 SQL 만 기록한다. SELECT 는 open_rows 를 돌려준다."""

    def __init__(self, open_rows):
        self.open_rows = open_rows
        self.calls = []

    def execute(self, sql, args=()):
        self.calls.append((sql, list(args)))

    def fetchall(self):
        return self.open_rows


class CloseMissingTests(unittest.TestCase):
    """K-Startup 모집 중 목록에서 빠진 공고를 closed 로 바꾼다(2026-09-30). DB 없이 SQL 만 본다."""

    OPEN = [(1, '100', 'kstartup:100'), (2, '101', 'kstartup:101'), (3, 102, 'kstartup:102')]
    STAMP, RUN = '2026-10-01 00:05:00', 'r' * 32

    def close(self, cursor, listed):
        return store.close_missing(cursor, listed, self.STAMP, self.RUN)

    def test_목록에_없는_open_공고만_닫는다(self):
        cursor = FakeCursor(self.OPEN)
        closed = self.close(cursor, {'kstartup': {'100', '102'}})
        self.assertEqual(closed, {'kstartup': ['kstartup:101']})
        select, update = cursor.calls
        self.assertIn("recruitment_status='open'", select[0])
        self.assertEqual(select[1], ['kstartup', self.STAMP])
        self.assertTrue(update[0].startswith("UPDATE notices SET recruitment_status='closed'"))
        self.assertEqual(update[1], [self.STAMP, self.RUN, 2])

    def test_이_목록보다_최신인_행은_닫지_않는다(self):
        # Codex 검수 P1-1: 늦게 도착한 옛 목록이 최신 open 행을 닫으면 안 된다 — SELECT 가 snapshot_at < stamp 로 거른다
        cursor = FakeCursor([])
        self.close(cursor, {'kstartup': {'100'}})
        self.assertIn('snapshot_at < %s', cursor.calls[0][0])

    def test_닫은_행의_시각과_실행을_바꾼다(self):
        # Codex 검수 P1-1: 옛 파일 재적재(upsert 의 snapshot_at > stamp 보호)가 닫힌 행을 되살리지 않게
        cursor = FakeCursor(self.OPEN)
        self.close(cursor, {'kstartup': {'100'}})
        self.assertIn('snapshot_at=%s, last_import_id=%s', cursor.calls[1][0])

    def test_목록_번호가_숫자여도_글자로_맞춘다(self):
        cursor = FakeCursor(self.OPEN)
        closed = self.close(cursor, {'kstartup': {100, 101, 102}})
        self.assertEqual(closed, {'kstartup': []})
        self.assertEqual(len(cursor.calls), 1)            # SELECT 만, UPDATE 없음

    def test_빈_목록이면_아무것도_닫지_않는다(self):
        for listed in (None, {}, {'kstartup': set()}):
            cursor = FakeCursor(self.OPEN)
            with self.subTest(listed=listed):
                self.assertEqual(self.close(cursor, listed), {})
                self.assertEqual(cursor.calls, [])

    def test_많으면_500건씩_나눠_닫는다(self):
        rows = [(i, str(i), 'kstartup:%d' % i) for i in range(1, 1202)]
        cursor = FakeCursor(rows)
        closed = self.close(cursor, {'kstartup': {'1'}})
        self.assertEqual(len(closed['kstartup']), 1200)
        self.assertEqual([len(args) - 2 for _, args in cursor.calls[1:]], [500, 500, 200])


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

    def kstartup_payload(self, ids, stamp):
        rows = [{'pbanc_sn': i, 'biz_pbanc_nm': 'K 공고 %s' % i, 'pbanc_rcpt_end_dt': '20991231',
                 'rcrt_prgs_yn': 'Y'} for i in ids]
        payload = normalize.normalize_sources([('kstartup', {'notices': rows})])
        payload['generated_at'] = stamp
        return payload

    def test_목록에서_빠지면_닫고_다시_나오면_연다(self):
        a, b = 'it' + uuid.uuid4().hex[:10], 'it' + uuid.uuid4().hex[:10]
        store.store_payload(self.connection, self.kstartup_payload([a, b], '2026-09-10T00:00:00+00:00'), 'f' * 64)
        result = store.store_payload(self.connection, self.kstartup_payload([a], '2026-09-11T00:00:00+00:00'),
                                     'f' * 64, listed={'kstartup': {a}})
        self.assertIn('kstartup:' + b, json.loads(self.query(
            'SELECT report FROM import_runs WHERE run_id=%s', (result['run_id'],))[0][0])['closed_missing']['kstartup'])
        status = dict(self.query('SELECT source_id, recruitment_status FROM notices WHERE source_id IN (%s,%s)', (a, b)))
        self.assertEqual(status, {a: 'open', b: 'closed'})
        store.store_payload(self.connection, self.kstartup_payload([a, b], '2026-09-12T00:00:00+00:00'),
                            'f' * 64, listed={'kstartup': {a, b}})
        status = dict(self.query('SELECT source_id, recruitment_status FROM notices WHERE source_id IN (%s,%s)', (a, b)))
        self.assertEqual(status, {a: 'open', b: 'open'})

    def test_닫은_뒤_옛_파일을_다시_넣어도_열리지_않는다(self):
        a, b = 'it' + uuid.uuid4().hex[:10], 'it' + uuid.uuid4().hex[:10]
        t1 = self.kstartup_payload([a, b], '2026-09-20T00:10:00+00:00')
        store.store_payload(self.connection, t1, 'f' * 64)
        store.store_payload(self.connection, self.kstartup_payload([a], '2026-09-20T00:20:00+00:00'),
                            'f' * 64, listed={'kstartup': {a}})
        again = store.store_payload(self.connection, t1, 'f' * 64)          # 옛 파일 재적재(listed 없음)
        self.assertEqual(again['skipped_older'], 2)
        status = dict(self.query('SELECT source_id, recruitment_status FROM notices WHERE source_id IN (%s,%s)', (a, b)))
        self.assertEqual(status, {a: 'open', b: 'closed'})

    def test_늦게_온_옛_목록은_최신_공고를_닫지_않는다(self):
        a, b = 'it' + uuid.uuid4().hex[:10], 'it' + uuid.uuid4().hex[:10]
        store.store_payload(self.connection, self.kstartup_payload([a, b], '2026-09-21T00:30:00+00:00'), 'f' * 64)
        late = store.store_payload(self.connection, self.kstartup_payload([a], '2026-09-21T00:20:00+00:00'),
                                   'f' * 64, listed={'kstartup': {a}})
        self.assertEqual(late['skipped_older'], 1)
        status = dict(self.query('SELECT source_id, recruitment_status FROM notices WHERE source_id IN (%s,%s)', (a, b)))
        self.assertEqual(status, {a: 'open', b: 'open'})

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
