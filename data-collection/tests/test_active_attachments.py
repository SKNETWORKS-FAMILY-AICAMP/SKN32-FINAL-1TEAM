# -*- coding: utf-8 -*-
"""LLM 단계(10·11·12)가 **지금 공고에 달린 첨부만** 읽고, 길이가 같으면 첨부 번호 순으로 읽는지 (2026-09-29).

Codex 지문 재검수 P1-1: 수집은 목록에서 빠진 첨부를 active=FALSE 로 남기는데, 문서를 만드는 조회가 active 를 보지 않아
치운 첨부의 본문으로 판정·지문을 만들었다. P2-1: 같은 길이 첨부의 순서가 정해지지 않아 지문이 흔들릴 수 있었다.
실제 DB 없음 — 실행한 SQL 을 기록하는 가짜 연결로 본다."""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collect import extract_conditions as ec  # noqa: E402
from experiments.sql_semantic import applicant_type_llm as atl  # noqa: E402
from experiments.sql_semantic import industry_llm_sample as ils  # noqa: E402


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=None):
        self.conn.sqls.append(' '.join(sql.split()))

    def fetchall(self):
        return self.conn.answers.pop(0) if self.conn.answers else []


class Conn:
    def __init__(self, *answers):
        self.sqls, self.answers = [], list(answers)

    def cursor(self):
        return Cursor(self)


def attachment_sql(sqls):
    found = [s for s in sqls if 'attachment_texts' in s]
    assert found, sqls
    return found


class ActiveAttachmentTests(unittest.TestCase):
    def assert_active_and_ordered(self, sql):
        self.assertIn('na.active', sql)
        if 'text_chars DESC' in sql:                  # 첨부를 길이순으로 읽는 조회는 동률이면 첨부 번호 순
            self.assertRegex(sql, r'text_chars DESC, na\.id')

    def test_applicant_types_and_service_fingerprint(self):
        # 11단계와 서비스 지문(search/applicant_types.current_documents)이 같이 쓰는 조회
        conn = Conn()
        atl.load_population(conn)
        for sql in attachment_sql(conn.sqls):
            self.assert_active_and_ordered(sql)

    def test_conditions_targets_and_attachments(self):
        # 10단계: 대상 고르기(EXISTS)와 공고별 첨부 읽기 둘 다
        conn = Conn([(1, 'n1', '제목', '본문', '대상', None, None)], [])
        ec.pick_targets(conn, 10, only_missing_age=False)
        sqls = attachment_sql(conn.sqls)
        self.assertEqual(len(sqls), 2)
        for sql in sqls:
            self.assert_active_and_ordered(sql)

    def test_industry_loaders(self):
        # 12단계(load_items_shared)와 실험용(load_items) — 조회가 공고 행을 여러 번 부르므로 코드 문장으로 본다
        for fn in (ils.load_items_shared, ils.load_items):
            src = ' '.join(inspect.getsource(fn).split())
            self.assertIn('na.active', src, fn.__name__)
            self.assertIn('text_chars DESC, na.id', src, fn.__name__)


if __name__ == '__main__':
    unittest.main()
