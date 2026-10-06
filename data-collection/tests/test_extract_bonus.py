# -*- coding: utf-8 -*-
"""가점 추출기의 코드 부분(구간 자르기·근거 대조·점수 검사) — 03_bonus 3-1 (2026-10-06). LLM·DB 없음."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collect import extract_bonus as eb  # noqa: E402

TABLE_DOC = ('우대가점 ㆍ중소기업중앙회가 선정한 명문장수기업 인증서 2 ㆍ｢자유무역협정의 이행을 위한 관세법의 특례에 관한 법률｣ '
             '인증서 4 1 제12조에 따른 원산지인증수출자 (유효기간에 한함) ㆍ지역정착과 고용창출을 통한 지역활성화를 위해 7 '
             '주민등록등본(거주자) 2 기업 종사자 중 화순군 거주자 60% 이상 고용기업')


def item(name, quote, points=None, kind='기타', certs=(), regions=(), source=None):
    return {'name': name, 'points': points, 'kind': kind, 'certs': list(certs), 'regions': list(regions),
            'detail': None, 'quote': quote, 'points_source': source, 'group': 'g1', 'program': None,
            'extra_conditions': None}


class SliceTests(unittest.TestCase):
    def test_slices_only_around_bonus_words(self):
        text = '가' * 2000 + ' 여성기업 가점 2점 부여 ' + '나' * 2000
        piece = eb.slice_bonus(text)
        self.assertIn('여성기업 가점 2점', piece)
        self.assertLess(len(piece), 1000)

    def test_no_bonus_word_gives_empty(self):
        self.assertEqual(eb.slice_bonus('지원 대상은 중소기업이다'), '')

    def test_bonus_windows_come_before_preference_windows(self):
        # 앞쪽 '우대'(금리 우대) 구간이 자리를 다 써서 뒤쪽 가점 배점표가 빠지던 문제(2026-10-06 Codex 검수 P2-2, N07)
        text = ' '.join('금리 우대 %d번 설명 %s' % (i, '가' * 300) for i in range(40)) + ' 배점표 기본점수(62점)+가점 신규업체 10'
        doc, complete = eb.build({'body': '', 'target_text': '', 'attachments': [text]}, max_chars=3000)
        self.assertIn('기본점수(62점)+가점 신규업체 10', doc)
        self.assertTrue(complete)
        many = ' '.join('가점 항목 %d %s' % (i, '나' * 800) for i in range(20))
        _doc, complete = eb.build({'body': '', 'target_text': '', 'attachments': [many]}, max_chars=3000)
        self.assertFalse(complete)                                       # 가점 구간을 다 담지 못했다

    def test_preference_only_notice_is_a_target(self):
        # '가점' 말 없이 '우대'만 있는 공고도 대상이다(P2-3) — 전에는 no_mention 으로 0점이 됐다
        self.assertTrue(eb.TARGET_RE.search('여성기업 우대: 선정평가 시 추가 2점 부여'))

    def test_document_labels_sources(self):
        doc = eb.build_document({'body': '개요', 'target_text': '', 'attachments': ['평가 시 우대 가점 3점']})
        self.assertIn('[공고문 첨부 발췌]', doc)
        self.assertNotIn('[공고 개요·지원대상 발췌]', doc)       # 개요에는 가점 말이 없다


class PointsTests(unittest.TestCase):
    def test_numbers_that_can_be_points(self):
        self.assertEqual(eb._points_in('여성기업 해당 10 해당 인증서'), {10.0})        # 표: 단위 없는 숫자
        self.assertEqual(eb._points_in('(거주자) 2 기업 종사자'), {2.0})              # 띄어 쓴 '기업'은 단위가 아니다
        self.assertEqual(eb._points_in('가점 3점, 최대 5 점'), {3.0, 5.0})
        self.assertEqual(eb._points_in('최근 3년 이내 · 30% 이상 · 5개 · 1억원 · 2기 수료'), set())
        # 'N점'이 있으면 그것만, 맨 앞 숫자는 표 연번(2026-10-06 Codex 검수 P1-2)
        self.assertEqual(eb._points_in('1 여성기업 가점 2점'), {2.0})
        self.assertEqual(eb._points_in('1 여성기업 가점'), set())
        # 괄호 속 숫자는 'N점'이 함께 있어도 점수 후보(표본 F05 "가점(3점) : 지역화폐 가맹점(1), 할인여부(1)")
        self.assertEqual(eb._points_in('가점(3점) : 지역화폐 가맹점(1), 할인여부(1)'), {3.0, 1.0})
        self.assertEqual(eb._points_in('(1) 여성기업 가점'), set())
        # 떨어진 배점 칸은 맨 앞 숫자가 점수다(표본 N07 "5 (우대한도 적용)")
        self.assertEqual(eb._points_in('5 (우대한도 적용)', leading=True), {5.0})


class FindQuoteTests(unittest.TestCase):
    def test_exact_and_spacing(self):
        self.assertIsNotNone(eb.find_quote('명문장수기업  인증서', TABLE_DOC))

    def test_table_cells_interleaved_still_found(self):
        # 표가 글자로 바뀌며 "인증서 4 1" 이 끼어든 문장 — LLM 이 칸을 이어 붙인 근거를 인정한다
        span = eb.find_quote('｢자유무역협정의 이행을 위한 관세법의 특례에 관한 법률｣ 제12조에 따른 원산지인증수출자', TABLE_DOC)
        self.assertIsNotNone(span)
        self.assertIn('4 1', span)

    def test_made_up_quote_is_rejected(self):
        self.assertIsNone(eb.find_quote('벤처기업 확인서 보유 기업 가점 3점', TABLE_DOC))

    def test_words_too_far_apart_are_rejected(self):
        doc = '여성기업 ' + '가' * 500 + ' 가점'
        self.assertIsNone(eb.find_quote('여성기업 가점', doc))


class CodexReproTests(unittest.TestCase):
    """2026-10-06 Codex 검수 P1-2 재현 세 가지 — 모두 점수를 승인하면 안 된다."""

    def one(self, doc, quote, points, source=None):
        data = {'has_bonus': True, 'max_total_points': None, 'bonus_info': None, 'uncertain': [],
                'items': [item('여성기업', quote, points, '여성', source=source)]}
        return eb.verify(data, doc)[0]['items']

    def test_points_from_another_line_are_rejected(self):
        doc = '여성기업 가점 9점. ' + '배경 설명 ' * 30 + '여성기업 가점 1점.'
        self.assertIsNone(self.one(doc, '여성기업 가점 1점', 9)[0]['points'])
        self.assertEqual(self.one(doc, '여성기업 가점 1점', 1)[0]['points'], 1)
        self.assertEqual(eb.find_quote('여성기업 가점 1점', doc), '여성기업 가점 1점')     # 실제로 일치한 자리

    def test_serial_number_is_not_points(self):
        self.assertIsNone(self.one('1 여성기업 가점 2점', '1 여성기업 가점', 1)[0]['points'])

    def test_negated_reconstruction_is_not_evidence(self):
        self.assertEqual(self.one('여성기업은 제외하고 벤처기업 가점 1점', '여성기업 가점 1점', 1), [])

    def test_points_source_near_the_quote(self):
        doc = '가점 항목 여성기업 장애인기업 사회적기업 ' + '가' * 50 + ' 해당 시 각 2점 부여'
        self.assertEqual(self.one(doc, '여성기업', 2, source='각 2점')[0]['points'], 2)
        far = '가점 항목 여성기업 ' + '가' * 2000 + ' 각 2점'
        self.assertIsNone(self.one(far, '여성기업', 2, source='각 2점')[0]['points'])

    def test_total_needs_evidence(self):
        data = {'has_bonus': True, 'max_total_points': 5, 'bonus_info': None, 'uncertain': [],
                'items': [item('여성기업', '여성기업 가점 2점', 2, '여성')]}
        self.assertIsNone(eb.verify(data, '여성기업 가점 2점')[0]['max_total_points'])
        self.assertEqual(eb.verify(data, '여성기업 가점 2점 (가점은 최대 5점까지)')[0]['max_total_points'], 5)

    def test_cut_document_cannot_say_none(self):
        out, problems = eb.verify({'has_bonus': False, 'max_total_points': None, 'bonus_info': None,
                                   'uncertain': [], 'items': []}, '가점 표 일부', complete=False)
        self.assertEqual(out['status'], 'unverified')
        self.assertIn('다 담지 못해', problems[0])


class VerifyTests(unittest.TestCase):
    def test_keeps_true_items_and_checks_points_in_span(self):
        data = {'has_bonus': True, 'max_total_points': None, 'bonus_info': '우대가점 ㆍ중소기업중앙회가 선정한 명문장수기업',
                'uncertain': [], 'items': [
            item('원산지인증수출자', '관세법의 특례에 관한 법률｣ 제12조에 따른 원산지인증수출자', 1, '수출'),
            item('화순군 거주자 고용', 'ㆍ지역정착과 고용창출을 통한 지역활성화를 위해 기업 종사자 중 화순군 거주자 60% 이상 고용기업', 2, '고용'),
        ]}
        out, problems = eb.verify(data, TABLE_DOC)
        self.assertEqual(out['status'], 'found')
        self.assertEqual([i['points'] for i in out['items']], [1, 2])       # 점수는 원문 구간에 있다
        self.assertEqual(problems, [])

    def test_made_up_points_become_null(self):
        data = {'has_bonus': True, 'max_total_points': None, 'bonus_info': None, 'uncertain': [],
                'items': [item('명문장수기업', '중소기업중앙회가 선정한 명문장수기업', 9, '인증')]}
        out, problems = eb.verify(data, TABLE_DOC)
        self.assertIsNone(out['items'][0]['points'])
        self.assertIn('점수가 근거에 없어', problems[0])

    def test_all_items_dropped_is_unverified_not_none(self):
        data = {'has_bonus': True, 'max_total_points': 5, 'bonus_info': None, 'uncertain': [],
                'items': [item('지어낸 항목', '벤처기업 확인서 보유 기업 가점 3점', 3)]}
        out, _ = eb.verify(data, TABLE_DOC)
        self.assertEqual((out['status'], out['has_bonus'], out['items']), ('unverified', False, []))

    def test_no_bonus_is_none(self):
        out, _ = eb.verify({'has_bonus': False, 'max_total_points': None, 'bonus_info': None, 'uncertain': [],
                            'items': []}, TABLE_DOC)
        self.assertEqual(out['status'], 'none')

    def test_region_list_with_whole_country_is_cleared_and_bad_values_filtered(self):
        data = {'has_bonus': True, 'max_total_points': 200, 'bonus_info': None, 'uncertain': [], 'items': [
            item('전국', '명문장수기업 인증서', None, '지역', regions=list(eb.REGIONS)),
            item('여성', '명문장수기업 인증서', None, '없는종류', certs=['여성기업', '가짜인증'], regions=['서울', '화성'])]}
        out, _ = eb.verify(data, TABLE_DOC)
        self.assertEqual(out['items'][0]['regions'], [])
        self.assertEqual((out['items'][1]['kind'], out['items'][1]['certs'], out['items'][1]['regions']),
                         ('기타', ['여성기업'], ['서울']))
        self.assertIsNone(out['max_total_points'])                        # 100 초과 한도는 버린다


class BonusInfoAndPlanTests(unittest.TestCase):
    def test_bonus_info_not_in_document_is_replaced_by_item_quotes(self):
        data = {'has_bonus': True, 'max_total_points': None, 'bonus_info': '지어낸 가점 설명 문장입니다', 'uncertain': [],
                'items': [item('명문장수기업', '중소기업중앙회가 선정한 명문장수기업', None, '인증')]}
        out, problems = eb.verify(data, TABLE_DOC)
        self.assertEqual(out['bonus_info'], '중소기업중앙회가 선정한 명문장수기업')
        self.assertIn('가점 원문이 문서와 맞지 않아', problems[0])

    def test_plan_skips_same_document_and_version(self):
        base = {'title': '', 'body': '', 'target_text': '', 'mention': True}
        a = dict(base, notice_id='a', attachments=['가점 3점'], content_version='cv2-a')
        b = dict(base, notice_id='b', attachments=['가점 2점'], content_version='cv2-b')
        c = dict(base, notice_id='c', attachments=['가점 1점'], content_version='cv2-c-new')
        q = dict(base, notice_id='q', attachments=['평가표'], mention=False, content_version='cv2-q')
        r = dict(base, notice_id='r', attachments=['평가표 바뀜'], mention=False, content_version='cv2-r-new')
        done = {'a': (eb.doc_hash(eb.build_document(a)), eb.EXTRACTOR_VERSION, 'cv2-a'),
                'b': (eb.doc_hash(eb.build_document(b)), 'extract_bonus/v0', 'cv2-b'),        # 버전이 다르면 다시
                'c': (eb.doc_hash(eb.build_document(c)), eb.EXTRACTOR_VERSION, 'cv2-c'),       # 발췌 밖이 바뀜(P2-4)
                'q': (eb.NO_MENTION_HASH, eb.EXTRACTOR_VERSION, 'cv2-q'),
                'r': (eb.NO_MENTION_HASH, eb.EXTRACTOR_VERSION, 'cv2-r')}                     # 가점 말 없는 공고도
        call, quiet, keep = eb.plan_work([a, b, c, q, r], done)
        self.assertEqual(([i['notice_id'] for i in call], [i['notice_id'] for i in quiet], [i['notice_id'] for i in keep]),
                         (['b', 'c'], ['r'], ['a', 'q']))
        call, quiet, keep = eb.plan_work([a, b, q], {})
        self.assertEqual(([i['notice_id'] for i in call], [i['notice_id'] for i in quiet]), (['a', 'b'], ['q']))

    def test_daily_batch_without_api_key_skips(self):
        from unittest.mock import patch
        with patch.object(eb.config, 'get', lambda name, default=None: None), \
                patch.object(eb, 'run_full', side_effect=AssertionError('부르면 안 된다')):
            self.assertEqual(eb.run_batch(say=lambda *_: None), {'error': 'no_api_key', 'saved': 0})

    def test_daily_limit_counts_calls_per_korean_day(self):
        # 같은 날 다시 돌려도 하루 상한을 넘지 않는다(2026-10-06 Codex 검수 P2-6). 실패한 호출도 센다
        import tempfile
        from unittest.mock import patch
        path = os.path.join(tempfile.mkdtemp(), 'calls.json')
        seen = []

        def fake_full(limit=None, say=None, report=None, on_calls=None):
            n = min(limit, 350)
            seen.append(n)
            on_calls(n)
            return {'called': n, 'no_mention': 0, 'saved': 0, 'failures': [{}] * n, 'cost_usd': 0, 'left': 350 - n}
        with patch.object(eb.config, 'get', lambda name, default=None: 'key'), \
                patch.object(eb, 'run_full', fake_full), patch.object(eb, '_today_kst', lambda: '2026-10-07'):
            eb.run_batch(limit=300, say=lambda *_: None, daily_file=path)
            eb.run_batch(limit=300, say=lambda *_: None, daily_file=path)
        self.assertEqual(seen, [300, 0])
        self.assertEqual(eb._daily_used('2026-10-07', path), 300)

    def test_no_mention_row_and_save_sql(self):
        row = eb.no_mention_row({'notice_id': 'q', 'title': 't'})
        self.assertEqual(row['result']['status'], 'no_mention')

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, args):
                self.sql, self.args = sql, args

        class Conn:
            cur = Cursor()

            def cursor(self):
                return self.cur
        conn = Conn()
        eb.save(conn, row)
        self.assertIn('ON DUPLICATE KEY UPDATE', conn.cur.sql)
        self.assertEqual(conn.cur.args[:2], ('q', 'no_mention'))
        self.assertEqual(conn.cur.args[4], '[]')


if __name__ == '__main__':
    unittest.main()
