# -*- coding: utf-8 -*-
"""13단계 판정 올리기 — 가짜 결과 파일·가짜 DB 로 (2026-09-28). 실제 DB 없음."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collect import upload_judgments as up  # noqa: E402
from search import applicant_types as at  # noqa: E402


def cell(status, strength=None, evidence=None):
    return {'status': status, 'strength': strength, 'evidence': evidence}


TYPE_ROWS = [
    {'notice_id': 'n1', 'document_sha256': 'a' * 64, 'usage': {'in': 100, 'out': 20},
     'llm': {'varies': False, 'reason': '명시 불가',
             'pre_founder': cell('not_allowed', 'strong', '예비창업자 제외'),
             'sole_proprietor': cell('allowed', 'strong', '개인사업자'), 'corporation': cell('not_mentioned')}},
    {'notice_id': 'n2', 'document_sha256': 'b' * 64, 'usage': {},
     'llm': {'varies': False, 'reason': '',
             'pre_founder': cell('not_mentioned'), 'sole_proprietor': cell('not_mentioned', None, '사업자 미등록 업체 제외'),
             'corporation': cell('not_mentioned')}},
    {'notice_id': 'gone', 'document_sha256': 'c' * 64, 'usage': {},
     'llm': {'varies': False, 'pre_founder': cell('allowed', 'strong', '예비창업자'),
             'sole_proprietor': cell('not_mentioned'), 'corporation': cell('not_mentioned')}},
]
INDUSTRY_ROWS = [
    {'notice_id': 'n1', 'document_sha256': 'd' * 64, 'source_run': 'run_a', 'usage': {'in': 10, 'out': 5},
     'llm': {'industry_status': 'known', 'status': 'known', 'list_complete': True, 'truncated': False,
             'scope_unresolved': False, 'quote': '도내 제조업을 영위하는 중소기업', 'quote_role': 'eligibility',
             'excerpt_cap': 6000, 'profile': 'rough',
             'allowed': [{'text': '제조업', 'label': '', 'evidence': '도내 제조업을 영위하는 중소기업'}], 'excluded': []}},
    {'notice_id': 'n2', 'document_sha256': 'e' * 64, 'usage': {},
     'llm': {'industry_status': 'unknown', 'status': 'unknown', 'allowed': [], 'excluded': []}},
]


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=None):
        if sql.startswith('SELECT notice_id FROM notices'):
            self.rows = [(n,) for n in self.db['notices']]
        else:
            table = sql.split(' FROM ')[1].strip()
            cols = sql[len('SELECT '):sql.index(' FROM ')].split(', ')
            self.rows = [tuple(r.get(c) for c in cols) for r in self.db[table].values()]

    def fetchall(self):
        return self.rows

    def executemany(self, sql, values):
        table = sql.split()[2]
        cols = sql[sql.index('(') + 1:sql.index(')')].split(', ')
        for v in values:
            self.db[table][v[0]] = dict(zip(cols, v))
        self.db['writes'] += len(values)


class FakeConn:
    def __init__(self):
        self.db = {'notices': ['n1', 'n2'], 'notice_applicant_types': {}, 'notice_industries': {}, 'writes': 0}

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        pass


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.types = self.write('types', TYPE_ROWS, {'engine': 'gpt-5.6-luna@medium', 'prompt_sha256': 'p' * 64})
        self.inds = self.write('inds', INDUSTRY_ROWS, {'engine': 'gpt-5.6-luna@medium', 'prompt': 'v3',
                                                       'prompt_sha256': 'q' * 64, 'profile': 'rough'})
        # 13단계는 지금 공고문(current_documents)을 DB 에서 읽는다 — 가짜 DB 에는 없으니 대역.
        # 기본은 결과 파일과 지문이 같고 발췌 밖 언급이 없는 공고문(n1 은 그대로 blocked)
        self.documents = {'n1': self.doc('a' * 64, '예비창업자 제외'), 'n2': self.doc('b' * 64, '')}
        docs = patch.object(at, 'current_documents', lambda connection: self.documents)
        docs.start()
        self.addCleanup(docs.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, rows, meta):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        with io.open(os.path.join(d, 'results.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        with io.open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        return os.path.join(d, 'results.jsonl')

    def run_up(self, conn, dry_run=False):
        return up.run(dry_run=dry_run, connection=conn, types_path=self.types, industry_path=self.inds,
                      say=lambda *_: None)

    def test_type_rows_carry_service_verdict(self):
        rows = {r['notice_id']: r for r in up.type_rows(self.types, self.documents)}
        self.assertEqual(rows['n1']['pre_founder_verdict'], 'blocked')        # 명시 불가 strong → 빼기
        self.assertEqual(rows['n2']['pre_founder_verdict'], 'implied_no')     # 등록 사업자 전용 표현 → 뒤로
        self.assertEqual(rows['n2']['registered_only_phrase'], '사업자 미등록')
        self.assertEqual(rows['n1']['extractor_version'], 'applicant_type_llm gpt-5.6-luna@medium')
        self.assertEqual(rows['n1']['prompt_tokens'], 100)

    def test_industry_rows_compute_sections_and_rank_flag(self):
        rows = {r['notice_id']: r for r in up.industry_rows(self.inds)}
        self.assertEqual(rows['n1']['allowed_sections'], ['C'])
        self.assertTrue(rows['n1']['usable_for_rank'])
        self.assertEqual(rows['n1']['source_run'], 'run_a')
        self.assertIsNone(rows['n2']['allowed_sections'])
        self.assertFalse(rows['n2']['usable_for_rank'])

    def test_plan_does_not_write_and_skips_unknown_notices(self):
        conn = FakeConn()
        out = self.run_up(conn, dry_run=True)
        self.assertEqual(conn.db['writes'], 0)
        self.assertEqual((out['types']['new'], out['types']['no_notice']), (2, 1))   # 'gone' 은 notices 에 없다
        self.assertEqual(out['industries']['new'], 2)

    def test_second_run_uploads_only_changes(self):
        conn = FakeConn()
        self.run_up(conn)
        self.assertEqual(conn.db['writes'], 4)
        again = self.run_up(conn)
        self.assertEqual((again['types']['same'], again['types']['uploaded']), (2, 0))
        self.assertEqual((again['industries']['same'], again['industries']['uploaded']), (2, 0))
        # 한 행의 근거가 바뀌면 그 행만 올린다
        conn.db['notice_applicant_types']['n1']['reason'] = '옛 이유'
        third = self.run_up(conn)
        self.assertEqual((third['types']['changed'], third['types']['uploaded']), (1, 1))

    def test_file_much_smaller_than_db_warns_but_still_uploads_changes(self):
        # 2026-09-29: 파일의 공고가 DB 보다 크게 적으면 경고만 남기고 맞는 행은 올린다(예전에는 전부 막아 정상 갱신도
        # 멈췄다 — Codex 재검수 P2). 서비스가 지문으로 옛 판정을 거르므로 여기서 전부 막을 이유가 없다
        conn = FakeConn()
        self.run_up(conn)
        conn.db['notice_applicant_types']['n1']['reason'] = '옛 이유'       # n1 은 올릴 게 있다
        writes = conn.db['writes']
        small = self.write('small', TYPE_ROWS[:1], {'engine': 'gpt-5.6-luna@medium'})
        out = up.run(connection=conn, types_path=small, industry_path=self.inds, say=lambda *_: None)
        self.assertNotIn('error', out['types'])
        self.assertIn('확인 필요', out['types']['warning'])
        self.assertEqual((out['types']['changed'], out['types']['uploaded']), (1, 1))
        self.assertEqual(conn.db['writes'], writes + 1)

    def test_warning_counts_only_notices_that_still_exist(self):
        # 수집에서 빠져 notices 에 없는 공고('gone')는 파일·DB 공고 수에 넣지 않는다 — 부풀려 경고를 피하지 않게
        conn = FakeConn()
        self.run_up(conn)
        only_gone = self.write('gone', [TYPE_ROWS[2], TYPE_ROWS[0]], {'engine': 'gpt-5.6-luna@medium'})
        out = up.run(dry_run=True, connection=conn, types_path=only_gone, industry_path=self.inds, say=lambda *_: None)
        self.assertIn('warning', out['types'])                             # 살아 있는 공고는 1/2

    def test_duplicated_notice_in_file_is_not_uploaded(self):
        # 같은 공고가 두 줄이면 어느 줄이 맞는지 모른다 — 이 표는 올리지 않는다(Codex 재검수 P2: 중복이 90% 검사를 통과했다)
        conn = FakeConn()
        self.run_up(conn)
        conn.db['notice_applicant_types']['n1']['reason'] = '옛 이유'
        writes = conn.db['writes']
        dup = self.write('dup', [TYPE_ROWS[0], TYPE_ROWS[0], TYPE_ROWS[1]], {'engine': 'gpt-5.6-luna@medium'})
        out = up.run(connection=conn, types_path=dup, industry_path=self.inds, say=lambda *_: None)
        self.assertIn('겹쳐', out['types']['error'])
        self.assertEqual(conn.db['writes'], writes)

    # ── 발췌 밖 원문 확인(2026-09-29 Codex 재검수 P1-2, A안) — DB 결론 칸도 서비스와 같아야 한다 ──────────
    def doc(self, sha, document, attachments=()):
        return {'document_sha256': sha, 'document': document, 'target_text': '', 'body': document,
                'attachments': list(attachments)}

    def test_type_rows_downgrade_blocked_when_unread_part_mentions_pre_founder(self):
        docs = {'n1': self.doc('a' * 64, '예비창업자 제외', ['[서식] 예비창업자도 신청 가능한 세부사업 안내'])}
        rows = {r['notice_id']: r for r in up.type_rows(self.types, docs)}
        self.assertIsNone(rows['n1']['pre_founder_verdict'])                # blocked → NULL(확인 필요)
        self.assertEqual(rows['n1']['pre_founder_status'], 'not_allowed')   # LLM 원래 값은 그대로 올린다

    def test_type_rows_keep_blocked_only_when_checked(self):
        def verdict(documents):
            return {r['notice_id']: r for r in up.type_rows(self.types, documents)}['n1']['pre_founder_verdict']
        # 원문의 언급이 모두 발췌에 있다 → 그대로 blocked
        self.assertEqual(verdict({'n1': self.doc('a' * 64, '예비창업자 제외 ' * 2)}), 'blocked')
        # 확인할 수 없으면 blocked 로 올리지 않는다(Codex 재재검수 P2): 지문이 다른 공고문 · 공고문 없음 · 원문 인자 없음
        self.assertIsNone(verdict({'n1': self.doc('z' * 64, '예비창업자 제외')}))
        self.assertIsNone(verdict({}))
        self.assertIsNone(verdict(None))

    def test_run_uploads_downgraded_verdict(self):
        self.documents = {'n1': self.doc('a' * 64, '예비창업자 제외', ['예비창업자도 신청 가능'])}
        conn = FakeConn()
        self.run_up(conn)
        self.assertIsNone(conn.db['notice_applicant_types']['n1']['pre_founder_verdict'])

    def test_type_rows_attachment_boundary_does_not_hide_unread(self):
        # Codex 3차 재검수: 첨부 '예비'·'창업' 경계의 가짜 언급이 안 읽은 진짜 언급을 가려 blocked 로 올리던 경로
        from experiments.sql_semantic import applicant_type_llm as atl
        body = '예비창업자 신청 불가. ' + 'A' * 2100 + ' 예비창업자도 신청 가능.'
        item = atl.prepare({'notice_id': 'n1', 'target_text': '', 'body': body, 'attachments': ['예비', '창업']})
        row = dict(TYPE_ROWS[0], document_sha256=item['document_sha256'])
        path = self.write('boundary', [row], {'engine': 'gpt-5.6-luna@medium'})
        rows = {r['notice_id']: r for r in up.type_rows(path, {'n1': item})}
        self.assertIsNone(rows['n1']['pre_founder_verdict'])

    def test_run_skips_types_when_current_documents_fail(self):
        def boom(connection):
            raise RuntimeError('db down')
        conn = FakeConn()
        with patch.object(at, 'current_documents', boom):
            out = self.run_up(conn)
        self.assertIn('공고문', out['types']['error'])
        self.assertEqual(conn.db['notice_applicant_types'], {})              # 신청자 유형은 올리지 않았다
        self.assertEqual(out['industries']['uploaded'], 2)                  # 업종 표는 그대로 올린다

    def test_missing_file_is_reported_not_raised(self):
        out = up.run(dry_run=True, connection=FakeConn(), types_path=os.path.join(self.tmp, 'none.jsonl'),
                     industry_path=self.inds, say=lambda *_: None)
        self.assertIn('error', out['types'])


if __name__ == '__main__':
    unittest.main()
