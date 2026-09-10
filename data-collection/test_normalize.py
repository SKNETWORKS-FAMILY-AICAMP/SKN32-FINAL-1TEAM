"""누락·날짜·HTML·출처별 차이와 중복 처리 검증. 외부 통신 없음."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from normalize import normalize_notice, normalize_sources, rows_from, text


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.k = {'pbanc_sn': 7, 'biz_pbanc_nm': '지원 공고', 'pbanc_ctnt': '<p>본문</p>',
                  'pbanc_rcpt_bgng_dt': '20260901', 'pbanc_rcpt_end_dt': '20260930',
                  'biz_enyy': '예비창업자,3년미만', 'rcrt_prgs_yn': 'Y'}
        self.b = {'pblancId': '7', 'pblancNm': '지원 공고', 'reqstBeginEndDe': '예산 소진시까지',
                  'jrsdInsttNm': '서울특별시', 'trgetNm': '중소기업',
                  'printFlpthNm': '/file?id=1&amp;seq=2', 'printFileNm': '공고.hwp'}

    def test_html_keeps_structure_and_comparison(self):
        self.assertEqual(text('<p>A&nbsp;&amp; B</p><ul><li>업력 &lt; 3년</li></ul><script>x()</script>'),
                         'A & B\n업력 < 3년')
        self.assertEqual(text('금액 < 300만원'), '금액 < 300만원')

    def test_source_id_and_raw_unchanged(self):
        before = copy.deepcopy(self.k)
        result = normalize_notice(self.k, 'kstartup')
        self.assertEqual(result['notice_id'], 'kstartup:7')
        self.assertEqual(result['apply_start'], '2026-09-01')
        self.assertEqual(self.k, before)
        self.assertEqual(result['raw'], before)

    def test_unknown_is_not_unrestricted_or_open(self):
        result = normalize_notice(self.b, 'bizinfo')
        self.assertIsNone(result['age_condition_raw'])
        self.assertIsNone(result['region'])
        self.assertIsNone(result['target_text'])
        self.assertEqual(result['target_category'], '중소기업')
        self.assertEqual(result['recruitment_status'], 'unknown')
        self.assertEqual(result['apply_period_type'], 'budget_exhaustion')
        self.assertEqual(result['apply_period_raw'], '예산 소진시까지')

    def test_invalid_calendar_date_and_reversed_period(self):
        for begin, end, code in [('20260230', '20260301', 'invalid_date'),
                                 ('20260930', '20260901', 'reversed_period')]:
            with self.subTest(code=code):
                self.k.update(pbanc_rcpt_bgng_dt=begin, pbanc_rcpt_end_dt=end)
                result = normalize_notice(self.k, 'kstartup')
                self.assertEqual(result['apply_period_type'], 'unknown')
                self.assertIn(code, [i['code'] for i in result['issues']])

    def test_bizinfo_dates(self):
        self.b['reqstBeginEndDe'] = '2026-9-1 ~ 2026-09-30'
        result = normalize_notice(self.b, 'bizinfo')
        self.assertEqual(result['apply_end'], '2026-09-30')
        self.assertEqual(result['recruitment_status'], 'unknown')

    def test_bad_url_and_relative_attachment(self):
        self.b['pblancUrl'] = 'javascript:alert(1)'
        result = normalize_notice(self.b, 'bizinfo')
        self.assertIsNone(result['url'])
        self.assertEqual(result['attachments'][0]['url'], 'https://www.bizinfo.go.kr/file?id=1&seq=2')
        self.assertIn('invalid_url', [i['code'] for i in result['issues']])

    def test_rejected_rows_and_last_valid_duplicate(self):
        revised = dict(self.k, pbanc_ctnt='수정 내용')
        result = normalize_sources([('kstartup', [self.k, revised, {'pbanc_sn': 7}, None])])
        self.assertEqual(result['summary']['accepted_count'], 1)
        self.assertEqual(result['summary']['rejected_count'], 2)
        self.assertEqual(result['notices'][0]['body'], '수정 내용')
        self.assertEqual(result['same_source_duplicates'][0]['replaced_raw'], self.k)

    def test_cross_source_candidate_does_not_merge(self):
        result = normalize_sources([('kstartup', [self.k]), ('bizinfo', [self.b])])
        self.assertEqual(len(result['notices']), 2)
        self.assertEqual(len(result['cross_source_candidates']), 1)

    def test_missing_dates_and_nonstandard_periods(self):
        for value, expected in [(None, 'unknown'), ('상시 접수', 'rolling'), ('차수별 상이', 'unknown')]:
            with self.subTest(value=value):
                self.b['reqstBeginEndDe'] = value
                result = normalize_notice(self.b, 'bizinfo')
                self.assertEqual(result['apply_period_type'], expected)
                self.assertIsNone(result['apply_end'])

    def test_envelopes_and_error_response(self):
        self.assertEqual(rows_from({'notices': [self.k]}, 'kstartup'), [self.k])
        self.assertEqual(rows_from({'data': [self.k]}, 'kstartup'), [self.k])
        self.assertEqual(rows_from({'jsonArray': [self.b]}, 'bizinfo'), [self.b])
        with self.assertRaises(ValueError):
            rows_from({'error': 'bad key'}, 'bizinfo')

    def test_blank_url_stays_missing(self):
        self.b['pblancUrl'] = '   '
        self.assertIsNone(normalize_notice(self.b, 'bizinfo')['url'])

    def test_cli_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.json'
            output = Path(folder) / 'output.json'
            source.write_text(json.dumps({'data': [self.k]}), encoding='utf-8')
            command = [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('normalize.py')),
                       '--kstartup', str(source), '--output', str(output)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            before = output.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
