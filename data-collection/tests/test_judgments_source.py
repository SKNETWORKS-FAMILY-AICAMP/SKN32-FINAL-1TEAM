# -*- coding: utf-8 -*-
"""서비스가 판정을 공용 DB 에서 먼저 읽고, 없거나 덜 올라갔거나 옛 값이면 파일로 넘어가는지 (2026-09-28). 실제 DB 없음."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search import applicant_types as at  # noqa: E402
from search import industry_rank as ir  # noqa: E402


def db_row(nid, sha, pre=('not_mentioned', None, None), sole=('not_mentioned', None, None), varies=0):
    # 순서: notice_id, varies, document_sha256, pre(status,strength,evidence), sole(...), corp(...)
    return (nid, varies, sha) + tuple(pre) + tuple(sole) + ('not_mentioned', None, None)


TYPE_DB_ROWS = [
    db_row('n1', 'h1', pre=('not_allowed', 'strong', '예비창업자 제외'), sole=('allowed', 'strong', '개인')),
    db_row('n2', 'h2', sole=('not_mentioned', None, '사업자 미등록 업체 제외')),
]
FILE_TABLE = {'active': True, 'source': 'file', 'rows': 1, 'notices': {'f': {}}, 'error': None}


class Cursor:
    def __init__(self, rows, fail=False):
        self.rows, self.fail = rows, fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=None):
        if self.fail:
            raise RuntimeError('db down')

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return (len(self.rows),)


class Conn:
    def __init__(self, rows, fail=False):
        self.rows, self.fail = rows, fail

    def cursor(self):
        return Cursor(self.rows, self.fail)


def file_row(nid, sha, pre_status='not_mentioned', strength=None, evidence=None):
    cell = lambda s='not_mentioned': {'status': s, 'strength': None, 'evidence': None}   # noqa: E731
    return {'notice_id': nid, 'document_sha256': sha,
            'llm': {'varies': False, 'pre_founder': {'status': pre_status, 'strength': strength, 'evidence': evidence},
                    'sole_proprietor': cell(), 'corporation': cell()}}


class ApplicantTypesSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'results.jsonl')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_file(self, rows):
        with io.open(self.path, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def test_db_rows_give_same_verdicts_as_file_logic(self):
        table = at.load_db(Conn(TYPE_DB_ROWS))
        self.assertEqual(table['source'], 'db:notice_applicant_types')
        self.assertEqual(at.pre_founder(table, 'n1'), 'blocked')
        self.assertEqual(at.pre_founder(table, 'n2'), 'implied_no')          # 등록 사업자 규칙을 지금 코드로 다시 계산
        self.assertEqual(table['notices']['n1']['document_sha256'], 'h1')

    def test_auto_prefers_complete_db_and_falls_back_otherwise(self):
        with patch.dict(os.environ, {at.SOURCE_ENV: 'auto'}), patch.object(at, 'load', lambda path=None: dict(FILE_TABLE)):
            self.assertEqual(at.load_auto(Conn(TYPE_DB_ROWS), path=self.path)['source'], 'db:notice_applicant_types')
            empty = at.load_auto(Conn([]), path=self.path)
            self.assertEqual((empty['source'], empty['note']), ('file', 'DB 표가 비어 있음 — 파일을 쓴다'))
            broken = at.load_auto(Conn([], fail=True), path=self.path)
            self.assertIn('DB 읽기 실패', broken['note'])
            self.assertEqual(at.load_auto(None, path=self.path)['source'], 'file')     # 연결 없음 → 파일(auto)

    def test_partial_upload_is_not_trusted(self):
        # DB 행이 공고 수의 95% 미만이면 덜 올라간 것 — 파일이 있으면 파일, 없으면 DB 를 쓰되 알린다(Codex 검수 P1)
        self.write_file([file_row('n1', 'h1')])
        with patch.dict(os.environ, {at.SOURCE_ENV: 'auto'}):
            t = at.load_auto(Conn(TYPE_DB_ROWS), path=self.path, expected=100)
            self.assertNotEqual(t['source'], 'db:notice_applicant_types')
            self.assertIn('95%', t['note'])
            no_file = at.load_auto(Conn(TYPE_DB_ROWS), path=os.path.join(self.tmp, 'none.jsonl'), expected=100)
            self.assertEqual(no_file['source'], 'db:notice_applicant_types')
            self.assertIn('파일이 없어 DB 를 쓴다', no_file['note'])

    def test_stale_db_row_is_replaced_by_newer_file_row(self):
        # 11단계는 됐는데 13단계가 실패한 날: DB 의 옛 'blocked'(h1)가 아니라 파일의 새 판정(h1-new)을 쓴다
        self.write_file([file_row('n1', 'h1-new'), file_row('n2', 'h2')])
        with patch.dict(os.environ, {at.SOURCE_ENV: 'auto'}):
            t = at.load_auto(Conn(TYPE_DB_ROWS), path=self.path, expected=2)
        self.assertEqual(t['source'], 'db:notice_applicant_types')
        self.assertIsNone(at.pre_founder(t, 'n1'))                          # 옛 blocked 를 쓰지 않는다
        self.assertEqual(t['refreshed_from_file'], 1)

    def test_forced_db_without_connection_is_an_error(self):
        with patch.dict(os.environ, {at.SOURCE_ENV: 'db'}):
            t = at.load_auto(None, path=self.path)
        self.assertFalse(t['active'])
        self.assertIn('DB 연결 없음', t['error'])

    def test_file_mode_never_touches_db(self):
        with patch.dict(os.environ, {at.SOURCE_ENV: 'file'}), patch.object(at, 'load', lambda path=None: dict(FILE_TABLE)):
            self.assertEqual(at.load_auto(Conn([], fail=True))['source'], 'file')


class IndustrySourceTests(unittest.TestCase):
    ROWS = [('n1', json.dumps(['C']), json.dumps([{'text': '제조업'}]))]

    def test_db_rows(self):
        table = ir.load_db(Conn(self.ROWS))
        self.assertEqual(table['notices']['n1'], {'sections': ['C'], 'allowed': ['제조업']})

    def test_default_stays_on_file_until_switched(self):
        # 2026-09-28 결정: 업종은 Codex 재검수·사람 판정 뒤 바꾼다 — 기본은 파일
        with patch.dict(os.environ, {}, clear=False), patch.object(ir, 'load', lambda path=None: dict(FILE_TABLE)):
            os.environ.pop(ir.SOURCE_ENV, None)
            self.assertEqual(ir.load_auto(Conn(self.ROWS))['source'], 'file')
            with patch.dict(os.environ, {ir.SOURCE_ENV: 'auto'}):
                self.assertEqual(ir.load_auto(Conn(self.ROWS))['source'], 'db:notice_industries')
                self.assertEqual(ir.load_auto(Conn(self.ROWS), expected=100)['source'], 'file')   # 덜 올라감
            with patch.dict(os.environ, {ir.SOURCE_ENV: 'db'}):
                self.assertIn('DB 연결 없음', ir.load_auto(None)['error'])


if __name__ == '__main__':
    unittest.main()
