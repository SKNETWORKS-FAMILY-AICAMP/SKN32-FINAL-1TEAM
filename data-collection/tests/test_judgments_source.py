# -*- coding: utf-8 -*-
"""서비스가 판정을 공용 DB·파일에서 읽을 때 지금 공고문과 지문이 같은 판정만 쓰는지 (2026-09-28, 2026-09-29 지문 확인).
실제 DB 없음 — 지금 공고문의 지문(current)은 테스트가 직접 넘기거나 current_documents 를 대역으로 바꾼다."""
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

    # ── 지문(문서 해시) 확인 — 2026-09-29 Codex 재검수 P1. current = 지금 공고문의 지문 ──────────────
    NOW = {'n1': 'h1', 'n2': 'h2'}

    def auto(self, conn, current, path=None, mode='auto', **kw):
        # 지문과 함께 원문도 넘긴다(발췌 밖 언급 없음) — 서비스는 항상 원문으로 A안을 확인한다. 원문 없이 지문만
        # 넘기면 strong 불가를 쓰지 않는다(Codex 재재검수 P2, test_current_without_documents_does_not_block)
        documents = None if current is None else {
            nid: {'document_sha256': sha, 'document': '', 'target_text': '', 'body': '', 'attachments': []}
            for nid, sha in current.items()}
        with patch.dict(os.environ, {at.SOURCE_ENV: mode}):
            return at.load_auto(conn, path=path or self.path, documents=documents, **kw)

    def test_fresh_db_rows_are_used(self):
        t = self.auto(Conn(TYPE_DB_ROWS), dict(self.NOW), path=os.path.join(self.tmp, 'none.jsonl'))
        self.assertEqual(t['source'], 'db:notice_applicant_types')
        self.assertEqual(at.pre_founder(t, 'n1'), 'blocked')
        self.assertEqual((t['fresh_from_db'], t['refreshed_from_file'], t['stale']), (2, 0, 0))

    def test_stale_db_blocked_is_not_used_on_host_without_file(self):
        # P1-③: 파일이 없는 곳(EC2·조율 에이전트). 공고문이 바뀐 뒤(h1 → h1-new) 아직 다시 판정하지 못했으면
        # DB 의 옛 'blocked' 로 빼지 않는다 — 그 공고는 '모름'
        t = self.auto(Conn(TYPE_DB_ROWS), {'n1': 'h1-new', 'n2': 'h2'}, path=os.path.join(self.tmp, 'none.jsonl'))
        self.assertIsNone(at.pre_founder(t, 'n1'))
        self.assertEqual((t['stale'], len(t['notices'])), (1, 1))

    def test_old_file_does_not_override_newer_db(self):
        # P1-①: DB 에는 새 판정(h1-new, 가능), 배치 PC 파일에는 옛 판정(h1, 불가 strong). 예전 코드는 지문이 다르면
        # 파일이 새것이라고 보고 DB 를 덮어 'blocked' 가 됐다. 이제 지금 공고문(h1-new)과 같은 DB 를 쓴다
        new_db = [db_row('n1', 'h1-new', pre=('allowed', 'strong', '예비창업자 가능')), TYPE_DB_ROWS[1]]
        self.write_file([file_row('n1', 'h1', 'not_allowed', 'strong', '예비창업자 제외'), file_row('n2', 'h2')])
        t = self.auto(Conn(new_db), {'n1': 'h1-new', 'n2': 'h2'})
        self.assertEqual(at.pre_founder(t, 'n1'), 'allowed')
        self.assertEqual(t['refreshed_from_file'], 0)

    def test_newer_file_is_used_when_db_lags(self):
        # 11단계는 됐는데 13단계가 못 올린 날: DB 는 옛 blocked(h1), 파일은 새 판정(h1-new) — 지금 공고문과 같은 파일
        self.write_file([file_row('n1', 'h1-new', 'allowed', 'strong', '예비창업자 가능'), file_row('n2', 'h2')])
        t = self.auto(Conn(TYPE_DB_ROWS), {'n1': 'h1-new', 'n2': 'h2'})
        self.assertEqual(at.pre_founder(t, 'n1'), 'allowed')
        self.assertEqual((t['refreshed_from_file'], t['fresh_from_db'], t['source']), (1, 1, 'db:notice_applicant_types'))

    def test_when_neither_matches_the_notice_is_unknown(self):
        self.write_file([file_row('n1', 'h1-old', 'not_allowed', 'strong', '예비창업자 제외')])
        t = self.auto(Conn(TYPE_DB_ROWS), {'n1': 'h1-new', 'n2': 'h2'})
        self.assertIsNone(at.pre_founder(t, 'n1'))
        self.assertEqual(t['stale'], 1)

    def test_notice_without_current_document_is_not_used(self):
        t = self.auto(Conn(TYPE_DB_ROWS), {'n1': 'h1'}, path=os.path.join(self.tmp, 'none.jsonl'))
        self.assertNotIn('n2', t['notices'])
        self.assertEqual(t['no_document'], 1)

    def test_corrupted_file_line_does_not_raise(self):
        # P1-②: 결과 파일 한 줄이 깨져도(예: 쓰다가 끊김) 서버 시작이 멈추지 않는다 — 깨진 줄만 건너뛴다
        with io.open(self.path, 'w', encoding='utf-8') as f:
            f.write('{broken\n' + json.dumps(file_row('n2', 'h2')) + '\n' + '"just a string"\n')
        loaded = at.load(self.path)
        self.assertEqual((loaded['bad_lines'], list(loaded['notices'])), (2, ['n2']))
        self.assertIn('건너뛰었다', loaded['error'])
        t = self.auto(Conn(TYPE_DB_ROWS), dict(self.NOW))
        self.assertEqual((t['active'], t['bad_lines']), (True, 2))
        self.assertEqual(at.pre_founder(t, 'n1'), 'blocked')                # DB 의 신선한 판정은 그대로 쓴다

    def test_unreadable_file_does_not_raise(self):
        os.makedirs(self.path)                                              # 파일 자리에 폴더 — 열 수 없다
        loaded = at.load(self.path)
        self.assertFalse(loaded['active'])
        self.assertIn('읽지 못했다', loaded['error'])

    def test_fingerprint_failure_turns_feature_off_without_raising(self):
        def boom(connection):
            raise RuntimeError('db down')
        with patch.object(at, 'current_documents', boom):
            t = self.auto(Conn(TYPE_DB_ROWS), None)
        self.assertFalse(t['active'])
        self.assertIn('지문', t['error'])
        self.assertIsNone(at.pre_founder(t, 'n1'))

    def test_current_is_computed_from_connection_when_not_given(self):
        docs = {nid: {'document_sha256': sha, 'document': '예비창업자 제외', 'target_text': '', 'body': '',
                      'attachments': []} for nid, sha in self.NOW.items()}
        with patch.object(at, 'current_documents', lambda connection: docs):
            t = self.auto(Conn(TYPE_DB_ROWS), None, path=os.path.join(self.tmp, 'none.jsonl'))
        self.assertEqual(at.pre_founder(t, 'n1'), 'blocked')

    def test_no_connection_means_no_judgments(self):
        # 지문을 확인할 수 없으면 옛 판정으로 빼지 않는다 — 기능만 꺼진다(예외 없음)
        self.write_file([file_row('n1', 'h1', 'not_allowed', 'strong', '예비창업자 제외')])
        t = self.auto(None, None)
        self.assertFalse(t['active'])
        self.assertIn('지문', t['error'])

    def test_db_read_failure_uses_fresh_file_rows(self):
        self.write_file([file_row('n1', 'h1', 'not_allowed', 'strong', '예비창업자 제외')])
        t = self.auto(Conn([], fail=True), dict(self.NOW))
        self.assertEqual(at.pre_founder(t, 'n1'), 'blocked')
        self.assertEqual(t['refreshed_from_file'], 1)
        self.assertIn('DB 읽기 실패', t['note'])

    def test_forced_db_without_connection_is_an_error(self):
        t = self.auto(None, dict(self.NOW), mode='db')
        self.assertFalse(t['active'])
        self.assertIn('DB 연결 없음', t['error'])

    def test_forced_db_ignores_file_and_checks_fingerprint(self):
        self.write_file([file_row('n1', 'h1-new', 'allowed', 'strong', '예비창업자 가능')])
        t = self.auto(Conn(TYPE_DB_ROWS), {'n1': 'h1-new', 'n2': 'h2'}, mode='db')
        self.assertIsNone(at.pre_founder(t, 'n1'))                          # 파일은 보지 않고, DB 의 옛 판정은 쓰지 않는다
        self.assertEqual(t['refreshed_from_file'], 0)

    def test_file_mode_never_reads_judgments_from_db(self):
        # file 모드는 판정을 파일에서만 읽는다(DB 의 판정 표는 보지 않는다). 지문은 넘긴 값을 쓴다
        with patch.dict(os.environ, {at.SOURCE_ENV: 'file'}), patch.object(at, 'load', lambda path=None: dict(FILE_TABLE)):
            t = at.load_auto(Conn([], fail=True), current={'f': None})
        self.assertEqual(t['source'], 'file')
        self.assertEqual(t['fresh_from_db'], 0)

    # ── 2026-09-29 Codex 지문 재검수(JUDGMENT_FRESHNESS_REVIEW_20260929) 재현 입력 ────────────────
    def test_codex_p1_3_file_mode_without_fingerprint_is_off(self):
        # 예전: file 모드에 current 가 없으면 지문 확인 없이 옛 '불가'를 그대로 썼다 → blocked
        self.write_file([file_row('n1', 'old', 'not_allowed', 'strong', '예비창업자 제외')])
        with patch.dict(os.environ, {at.SOURCE_ENV: 'file'}):
            t = at.load_auto(None, path=self.path)
        self.assertFalse(t['active'])
        self.assertIsNone(at.pre_founder(t, 'n1'))
        self.assertIn('지문', t['error'])
        # 연결은 있는데 지문 계산이 실패해도 꺼진다
        def boom(connection):
            raise RuntimeError('db down')
        with patch.dict(os.environ, {at.SOURCE_ENV: 'file'}), patch.object(at, 'current_documents', boom):
            self.assertFalse(at.load_auto(Conn([]), path=self.path)['active'])

    def test_codex_p1_3_file_mode_computes_fingerprint_from_connection(self):
        self.write_file([file_row('n1', 'old', 'not_allowed', 'strong', '예비창업자 제외'),
                         file_row('n2', 'h2', 'allowed', 'strong', '예비창업자 가능')])
        docs = {nid: {'document_sha256': sha, 'document': ''} for nid, sha in self.NOW.items()}
        with patch.dict(os.environ, {at.SOURCE_ENV: 'file'}), \
                patch.object(at, 'current_documents', lambda connection: docs):
            t = at.load_auto(Conn(TYPE_DB_ROWS), path=self.path)
        self.assertIsNone(at.pre_founder(t, 'n1'))                          # 지문 다름 → 쓰지 않음
        self.assertEqual(at.pre_founder(t, 'n2'), 'allowed')
        self.assertEqual((t['stale'], t['fresh_from_db']), (1, 0))          # DB 판정은 보지 않았다

    def test_codex_p1_4_structured_notice_id_is_a_bad_line(self):
        # 예전: notice_id 가 목록이면 사전 삽입(try 밖)에서 TypeError 가 서버 시작까지 번졌다
        bad = {'notice_id': ['n1'], 'llm': {'pre_founder': {'status': 'not_allowed', 'strength': 'strong'}}}
        with io.open(self.path, 'w', encoding='utf-8') as f:
            for r in (bad, {'notice_id': {'x': 1}, 'llm': {}}, {'notice_id': '', 'llm': {'varies': True}}, [1, 2],
                      {'notice_id': 'n9', 'llm': 'text'}, file_row('n2', 'h2')):
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        loaded = at.load(self.path)
        self.assertEqual((loaded['bad_lines'], loaded['rows']), (4, 1))    # 빈 llm 줄은 원래 건너뛴다(깨진 줄 아님)
        self.assertEqual(list(loaded['notices']), ['n2'])
        t = self.auto(Conn(TYPE_DB_ROWS), dict(self.NOW))                   # Codex 재현: 정상 DB 2건 + 지문 + auto
        self.assertTrue(t['active'])
        self.assertEqual(t['bad_lines'], 4)
        self.assertEqual(at.pre_founder(t, 'n1'), 'blocked')

    def test_codex_p2_3_empty_judgments_explain_why_feature_is_off(self):
        t = self.auto(Conn([]), dict(self.NOW), path=os.path.join(self.tmp, 'none.jsonl'))
        self.assertFalse(t['active'])
        self.assertIn('0건', t['error'])
        stale = self.auto(Conn(TYPE_DB_ROWS), {'n1': 'new', 'n2': 'new'}, path=os.path.join(self.tmp, 'none.jsonl'))
        self.assertIn('지문 다름 2', stale['error'])

    def test_file_mode_checks_fingerprint_when_given(self):
        self.write_file([file_row('n1', 'h1-old', 'not_allowed', 'strong', '예비창업자 제외'), file_row('n2', 'h2')])
        t = self.auto(None, dict(self.NOW), mode='file')
        self.assertIsNone(at.pre_founder(t, 'n1'))
        self.assertEqual(t['stale'], 1)


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


class UnreadPreFounderTests(unittest.TestCase):
    """발췌 밖 원문 확인(2026-09-29 Codex 재검수 P1-2, 사용자 결정 A안).

    LLM 은 build_document() 발췌(최대 6,000자, 본문·지원대상 머리는 2,000자)만 읽고 지문도 그 해시다. strong 불가인데
    발췌 밖 원문에 '예비창업' 이 있으면 빼지 않고 확인 필요로 둔다."""

    def item(self, body, attachments=()):
        from experiments.sql_semantic import applicant_type_llm as atl
        return atl.prepare({'notice_id': 'n1', 'body': body, 'target_text': '', 'attachments': list(attachments)})

    def judged(self, item, pre=('not_allowed', 'strong', '법인사업자만 신청 가능'), varies=0):
        return at.load_db(Conn([db_row('n1', item['document_sha256'], pre=pre, varies=varies)]))

    def auto(self, table_rows, documents):
        with patch.dict(os.environ, {at.SOURCE_ENV: 'db'}):
            return at.load_auto(Conn(table_rows), documents=documents)

    def test_codex_repro_sentence_beyond_excerpt(self):
        # Codex 재현: 본문 2,100자 뒤에 문장을 더해도 발췌·지문이 같다 → 옛 불가가 신선하게 남던 경우
        head = '지원대상: 법인사업자만 신청 가능. ' + 'A' * 2100
        before, after = self.item(head), self.item(head + ' 예비창업자도 신청 가능.')
        self.assertEqual(before['document_sha256'], after['document_sha256'])
        rows = [db_row('n1', before['document_sha256'], pre=('not_allowed', 'strong', '법인사업자만 신청 가능'))]
        self.assertEqual(at.pre_founder(self.auto(rows, {'n1': before}), 'n1'), 'blocked')     # 언급 없음 → 그대로
        t = self.auto(rows, {'n1': after})
        self.assertIsNone(at.pre_founder(t, 'n1'))                                             # 빼지 않는다
        self.assertEqual(t['unread_pre_founder'], 1)
        verdict, need, why = at.type_check(t, 'n1', at.PRE_FOUNDER)
        self.assertIsNone(verdict)
        self.assertIn('확인 필요', need)
        self.assertIn('예비창업자도 신청 가능', why)

    def test_mention_inside_excerpt_keeps_blocked(self):
        it = self.item('지원대상: 예비창업자 제외, 법인만', ['신청자격 예비창업자 제외'])
        self.assertIsNone(at.unread_pre_founder(it))
        rows = [db_row('n1', it['document_sha256'], pre=('not_allowed', 'strong', '예비창업자 제외'))]
        self.assertEqual(at.pre_founder(self.auto(rows, {'n1': it}), 'n1'), 'blocked')

    def test_whitespace_difference_is_not_unread(self):
        # 발췌는 공백을 합친다 — 원문 줄바꿈만 다른 같은 언급은 읽은 것이다
        it = self.item('지원대상:\n  예비\n창업자   제외')
        self.assertIsNone(at.unread_pre_founder(it))

    def test_mention_in_unread_attachment_part(self):
        # 첨부는 자격 구간(HEADINGS 주변)만 발췌한다 — 멀리 떨어진 서식의 언급은 읽지 않은 곳이다
        far = '신청자격: 법인사업자. ' + '가' * 5000 + ' 제출서류: 개인사업자 또는 예비창업자의 경우 해당사항 없음'
        it = self.item('사업 개요', [far])
        self.assertIn('예비창업자의 경우', at.unread_pre_founder(it))

    def test_only_strong_not_allowed_is_marked(self):
        it = self.item('지원대상: 법인. ' + 'A' * 2100 + ' 예비창업자도 가능')
        for pre in (('allowed', 'strong', '예비창업자 가능'), ('not_allowed', 'weak', '법인'),
                    ('not_mentioned', None, None)):
            t = self.auto([db_row('n1', it['document_sha256'], pre=pre)], {'n1': it})
            self.assertEqual(t['unread_pre_founder'], 0, pre)
        t = self.auto([db_row('n1', it['document_sha256'], pre=('not_allowed', 'strong', '법인'), varies=1)], {'n1': it})
        self.assertEqual(t['unread_pre_founder'], 0)                                           # varies 는 원래 안 뺀다

    def test_mark_unread_skips_other_fingerprint_and_does_not_mutate(self):
        it = self.item('지원대상: 법인. ' + 'A' * 2100 + ' 예비창업자도 가능')
        notices = at.load_db(Conn([db_row('n1', 'old', pre=('not_allowed', 'strong', '법인'))]))['notices']
        self.assertNotIn('unread_pre_founder', at.mark_unread(notices, {'n1': it})['n1'])      # 지문 다름 → 안 봄
        notices = self.judged(it)['notices']
        marked = at.mark_unread(notices, {'n1': it})
        self.assertIn('unread_pre_founder', marked['n1'])
        self.assertNotIn('unread_pre_founder', notices['n1'])                                  # 원래 표는 그대로


    # ── Codex 재재검수(JUDGMENT_FRESHNESS_REVIEW_RECHECK_20260929) 반례 — 위치 조각 대신 횟수로 판단 ──────────
    P = '공고 자격요건 참고문구와 상황 설명: 예비창업자 신청 관련 별도 안내: '

    def assert_unblocked_after(self, before, after):
        self.assertEqual(before['document_sha256'], after['document_sha256'])          # 발췌·지문은 같다
        rows = [db_row('n1', before['document_sha256'], pre=('not_allowed', 'strong', '법인사업자만'))]
        self.assertEqual(at.pre_founder(self.auto(rows, {'n1': before}), 'n1'), 'blocked')
        t = self.auto(rows, {'n1': after})
        self.assertIsNone(at.pre_founder(t, 'n1'))
        self.assertEqual(t['unread_pre_founder'], 1)
        return t

    def test_codex_recheck_repeated_phrase_in_body(self):
        # 읽은 곳의 "…신청 불가" 와 안 읽은 곳의 "…신청 가능" 앞뒤 10자가 같다 — 예전에는 읽은 것으로 착각했다
        old = '지원대상: 법인사업자만 신청 가능. ' + self.P + '신청 불가. ' + 'A' * 2100
        before, after = self.item(old), self.item(old + ' ' + self.P + '신청 가능.')
        t = self.assert_unblocked_after(before, after)
        self.assertIn('예비창업자', t['notices']['n1']['unread_pre_founder'])

    def test_codex_recheck_repeated_phrase_across_two_attachments(self):
        first = '신청자격: ' + self.P + '신청 불가'
        second = '가' * 6500 + ' ' + self.P + '신청 가능'
        before = self.item('사업 개요', [first, '가' * 6500])
        after = self.item('사업 개요', [first, second])
        self.assert_unblocked_after(before, after)

    def test_codex_recheck_line_break_inside_word(self):
        head = '지원대상: 법인사업자만 신청 가능. ' + 'A' * 2100
        for tail in (' 예비\n창업자도 신청 가능', ' 예비창\n업자도 신청 가능', ' 예비 창 업자도 신청 가능', ' 예\n비창업자도 가능'):
            self.assert_unblocked_after(self.item(head), self.item(head + tail))

    def test_all_mentions_read_keeps_blocked_even_when_repeated(self):
        it = self.item('지원대상: 예비창업자 제외. ' + self.P + '신청 불가')     # 두 번 모두 발췌 안
        self.assertIsNone(at.unread_pre_founder(it))
        rows = [db_row('n1', it['document_sha256'], pre=('not_allowed', 'strong', '예비창업자 제외'))]
        self.assertEqual(at.pre_founder(self.auto(rows, {'n1': it}), 'n1'), 'blocked')

    def test_current_without_documents_does_not_block(self):
        # Codex 재재검수 P2: 지문(current)만 넘기면 원문이 없어 발췌 밖을 확인할 수 없다 — 불가를 쓰지 않는다
        it = self.item('지원대상: 법인사업자만 신청 가능. ' + 'A' * 2100 + ' 예비창업자도 신청 가능.')
        rows = [db_row('n1', it['document_sha256'], pre=('not_allowed', 'strong', '법인사업자만'))]
        with patch.dict(os.environ, {at.SOURCE_ENV: 'db'}):
            t = at.load_auto(Conn(rows), current={'n1': it['document_sha256']})
        self.assertIsNone(at.pre_founder(t, 'n1'))
        self.assertEqual((t['unverified_pre_founder'], t['unread_pre_founder']), (1, 0))
        verdict, need, why = at.type_check(t, 'n1', at.PRE_FOUNDER)
        self.assertIsNone(verdict)
        self.assertIn('확인하지 못했습니다', why)
        # 다른 판정(가능·추정)은 원문 없이도 그대로다
        rows = [db_row('n1', 'h', pre=('allowed', 'strong', '예비창업자 가능'))]
        with patch.dict(os.environ, {at.SOURCE_ENV: 'db'}):
            self.assertEqual(at.pre_founder(at.load_auto(Conn(rows), current={'n1': 'h'}), 'n1'), 'allowed')

    # ── Codex 3차 재검수(JUDGMENT_FRESHNESS_REVIEW_RECHECK2_20260929) — 첨부 경계의 가짜 언급 ──────────
    def test_codex_recheck2_attachment_boundary_does_not_hide_unread(self):
        # 첨부 '예비'·'창업' 은 각각 언급이 아닌데, 발췌 전체의 공백을 지우면 붙어 가짜 1회가 생겨 본문 뒤의
        # 안 읽은 "예비창업자도 신청 가능" 을 가렸다 → 조각(빈 줄)마다 센다
        body = '예비창업자 신청 불가. ' + 'A' * 2100
        before = self.item(body, ['예비', '창업'])
        after = self.item(body + ' 예비창업자도 신청 가능.', ['예비', '창업'])
        self.assertIn('예비\n\n창업', after['document'])                        # 발췌가 이 모양이라는 전제
        t = self.assert_unblocked_after(before, after)
        self.assertIn('신청 가능', t['notices']['n1']['unread_pre_founder'])

    def test_attachment_boundary_alone_is_not_a_mention(self):
        # 경계만 있고 안 읽은 언급이 없으면 그대로 blocked(가짜 언급을 원문 쪽으로도 세지 않는다)
        it = self.item('예비창업자 신청 불가.', ['예비', '창업'])
        self.assertIsNone(at.unread_pre_founder(it))
        rows = [db_row('n1', it['document_sha256'], pre=('not_allowed', 'strong', '예비창업자 신청 불가'))]
        self.assertEqual(at.pre_founder(self.auto(rows, {'n1': it}), 'n1'), 'blocked')

    def test_excerpt_chunks_never_join_two_sources(self):
        # 전제 확인: build_document() 는 머리·첨부 발췌 사이에 글자 표시, 첨부끼리는 빈 줄, 한 첨부의 구간끼리는 "---"
        it = self.item('끝이 예비', ['창업으로 시작 끝이 예비', '창업으로 시작', '신청자격: 가 ' + '나' * 3000 + ' 신청자격: 다'])
        self.assertIn('예비창업', ''.join(it['document'].split()))                 # 전체로 지우면 붙는다
        for chunk in it['document'].split('\n\n'):
            self.assertNotIn('예비창업', ''.join(chunk.split()))


if __name__ == '__main__':
    unittest.main()
