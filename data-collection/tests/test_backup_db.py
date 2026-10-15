"""collect/backup_db — 백업 범위와 '읽기만 한다'는 약속. 실제 DB 대신 가짜 연결을 쓴다."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from collect import backup_db

OUR_TABLES = {
    'import_runs', 'notices', 'notice_attachments', 'attachment_texts',
    'notice_conditions', 'notice_applicant_types', 'notice_industries', 'notice_bonus',
}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [('id',), ('body',)]
        self._one = None
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        self.conn.sql.append(sql)
        if sql.startswith('SHOW CREATE TABLE'):
            name = sql.split('`')[1]
            self._one = (name, 'CREATE TABLE `%s` (`id` int)' % name)
        elif sql.startswith('SELECT COUNT(*)'):
            self._one = (1,)
        elif sql.startswith('SELECT DATABASE()'):
            self._one = ('s_brain', 'host', '8.0')
        elif sql.startswith('SELECT * FROM'):
            self._rows = [(1, b'\x00\x01')]

    def fetchone(self):
        return self._one

    def __iter__(self):
        return iter(self._rows)


class FakeConnection:
    def __init__(self):
        self.sql = []
        self.rolled_back = False
        self.closed = False

    def cursor(self, *a):
        return FakeCursor(self)

    def escape(self, value):
        return "'%s'" % value.replace("'", "''")

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class TableScopeTests(unittest.TestCase):
    def test_default_includes_ai_judgment_tables(self):
        self.assertEqual(set(backup_db.CORE_TABLES), OUR_TABLES)

    def test_files_table_only_with_option(self):
        self.assertEqual(backup_db.HEAVY_TABLES, ('attachment_files',))
        self.assertNotIn('attachment_files', backup_db.CORE_TABLES)

    def test_no_other_team_tables(self):
        # 같은 DB 의 웹·조율 테이블(회원·로그인 토큰 등)은 백업에 넣지 않는다
        for name in ('users', 'refresh_tokens', 'projects', 'business_plans'):
            self.assertNotIn(name, backup_db.CORE_TABLES + backup_db.HEAVY_TABLES)


class LiteralTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()

    def test_values(self):
        lit = lambda v: backup_db.literal(self.conn, v)
        self.assertEqual(lit(None), 'NULL')
        self.assertEqual(lit(b'\x00\xff'), '0x00ff')
        self.assertEqual(lit(b''), "''")
        self.assertEqual(lit(True), '1')
        self.assertEqual(lit(Decimal('1.50')), '1.50')
        self.assertEqual(lit(datetime(2026, 10, 7, 9, 0, 0)), "'2026-10-07 09:00:00'")
        self.assertEqual(lit(date(2026, 10, 7)), "'2026-10-07'")
        self.assertEqual(lit("it's"), "'it''s'")


class MainReadOnlyTests(unittest.TestCase):
    def run_main(self, *args):
        conn = FakeConnection()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'b.sql')
            with patch.object(backup_db.store_mysql, 'connect', return_value=conn), \
                    patch.object(sys, 'argv', ['backup_db', '--out', out, *args]), \
                    patch('builtins.print'):
                self.assertEqual(backup_db.main(), 0)
            with open(out, encoding='utf-8') as f:
                text = f.read()
        return conn, text

    def test_reads_in_one_snapshot_and_never_writes(self):
        conn, text = self.run_main()
        self.assertEqual(conn.sql[0], 'START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        for sql in conn.sql[1:]:
            self.assertTrue(sql.startswith(('SELECT', 'SHOW CREATE TABLE')), sql)
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.closed)
        for name in OUR_TABLES:
            self.assertIn('-- %s (1행)' % name, text)
        self.assertNotIn('attachment_files', text)
        self.assertIn('0x0001', text)

    def test_include_files_adds_attachment_files(self):
        conn, text = self.run_main('--include-files')
        self.assertIn('-- attachment_files (1행)', text)



class RestoreTests(unittest.TestCase):
    """백업 파일에서 고른 AI 판정 테이블만 되살린다(결정 0013 되돌리기용)."""

    def make_backup(self):
        conn = FakeConnection()
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp))
        out = os.path.join(tmp, 'b.sql')
        with patch.object(backup_db.store_mysql, 'connect', return_value=conn), \
                patch.object(sys, 'argv', ['backup_db', '--out', out]), patch('builtins.print'):
            backup_db.main()
        return out

    def test_plan_counts_only_chosen_tables(self):
        path = self.make_backup()
        found = backup_db.restore(path, ['notice_bonus'], say=lambda *_: None)
        self.assertEqual(found, {'notice_bonus': {'rows': 1, 'statements': 3}})   # DROP · CREATE · INSERT

    def test_apply_runs_only_chosen_tables_statements(self):
        path = self.make_backup()
        conn = FakeConnection()
        backup_db.restore(path, ['notice_bonus', 'notice_industries'], apply=True, connection=conn, say=lambda *_: None)
        touched = {sql.split('`')[1] for sql in conn.sql if '`' in sql}
        self.assertEqual(touched, {'notice_bonus', 'notice_industries'})
        self.assertTrue(any(sql.startswith('DROP TABLE IF EXISTS `notice_bonus`') for sql in conn.sql))
        self.assertEqual(conn.sql[-1], 'SET FOREIGN_KEY_CHECKS = 1')

    def test_refuses_notice_tables(self):
        path = self.make_backup()
        with self.assertRaises(SystemExit):
            backup_db.restore(path, ['notices'], say=lambda *_: None)

    def test_missing_table_does_nothing(self):
        conn = FakeConnection()
        with tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False, encoding='utf-8') as f:
            f.write('-- s_brain 백업\nSET NAMES utf8mb4;\n')
        self.addCleanup(os.remove, f.name)
        with self.assertRaises(SystemExit):
            backup_db.restore(f.name, ['notice_bonus'], apply=True, connection=conn, say=lambda *_: None)
        self.assertEqual(conn.sql, [])


if __name__ == '__main__':
    unittest.main()
