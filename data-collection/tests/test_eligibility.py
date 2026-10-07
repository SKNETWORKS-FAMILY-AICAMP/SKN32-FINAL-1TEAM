"""자격 판정 한 곳(search/eligibility.py) 직접 시험 — 서버·DB 없이 공고 한 건 × 신청자로 부른다.

조건 네 줄 순서, 예비창업자 본문 '가능'이 업력 미달을 덮음, 세부사업별 허용이면 업력 None,
업력 칸 없음 → 공고문 추출 값은 근거로만(판정 None 유지), 설립일 없음 → 업력 None.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from datetime import date

from search import eligibility, gate

TODAY = date(2026, 10, 7)
PRE = '예비창업자'


def notice(age_raw='7년미만', status='open', start='2026-10-01', end='2026-10-31', **extra):
    row = {'notice_id': 'N1', 'age_condition_raw': age_raw, 'recruitment_status': status,
           'apply_start': start, 'apply_end': end, 'apply_period_type': 'fixed',
           'target_category': '중소기업'}
    row.update(extra)
    return row


def types_table(pre_status='not_mentioned', strength='weak', varies=False, evidence='', **info):
    base = {'pre_founder': {'status': pre_status, 'strength': strength, 'evidence': evidence},
            'corporation': {'status': 'allowed', 'evidence': '법인 가능'},
            'sole_proprietor': {'status': 'not_mentioned', 'evidence': ''},
            'varies': varies}
    base.update(info)
    return {'notices': {'N1': base}}


def by_name(checks):
    return {c['조건']: c for c in checks}


class OrderAndShapeTests(unittest.TestCase):
    def test_four_lines_in_order(self):
        checks, months = eligibility.conditions(notice(), 'N1', '법인', '2024-01-01', today=TODAY)
        self.assertEqual([c['조건'] for c in checks],
                         [eligibility.TYPE, eligibility.AGE, eligibility.PERIOD, eligibility.STATUS])
        self.assertEqual(months, 33)
        for c in checks:
            self.assertIn(c['판정'], (True, False, None))
            for key in ('요구', '내 값'):
                self.assertIn(key, c)

    def test_no_types_table_type_line_is_unknown(self):
        checks, _ = eligibility.conditions(notice(), 'N1', '법인', '2024-01-01', today=TODAY)
        line = by_name(checks)[eligibility.TYPE]
        self.assertIsNone(line['판정'])
        self.assertEqual(line['요구'], '중소기업')       # 공고의 지원대상 분류를 그대로 보여 준다

    def test_same_gate_result_as_matching_filter(self):
        # 업력 미달 공고는 정형 필터에서도 빠지고, 자격 판정에서도 미달이다(같은 함수)
        row = notice(age_raw='3년미만')
        checks, months = eligibility.conditions(row, 'N1', '법인', '2020-01-01', today=TODAY)
        self.assertIs(by_name(checks)[eligibility.AGE]['판정'], False)
        self.assertEqual(gate.prefilter(row, months, TODAY)[1], ['업력·신청자 유형'])

    def test_closed_and_past_deadline(self):
        checks, _ = eligibility.conditions(notice(status='closed', end='2026-10-01'), 'N1', '법인',
                                           '2024-01-01', today=TODAY)
        line = by_name(checks)
        self.assertIs(line[eligibility.PERIOD]['판정'], False)
        self.assertIs(line[eligibility.STATUS]['판정'], False)


class PreFounderTests(unittest.TestCase):
    def test_body_allowed_overrides_api_age_no(self):
        # API 업력 칸 "3년미만"은 예비창업자 불가로 읽히지만, 본문에 '가능'이 있으면 본문을 따른다
        table = types_table('allowed', evidence='예비창업자 및 3년 미만 기업')
        checks, months = eligibility.conditions(notice(age_raw='3년미만'), 'N1', PRE, None,
                                                types_table=table, today=TODAY)
        self.assertIsNone(months)
        line = by_name(checks)
        self.assertIs(line[eligibility.TYPE]['판정'], True)
        self.assertIs(line[eligibility.AGE]['판정'], True)
        self.assertIn('본문 우선', line[eligibility.AGE]['요구'])

    def test_body_allowed_with_missing_age_field_passes(self):
        table = types_table('allowed', evidence='예비창업자 또는 창업 3년 미만')
        checks, _ = eligibility.conditions(notice(age_raw=''), 'N1', PRE, None,
                                           types_table=table, today=TODAY)
        self.assertIs(by_name(checks)[eligibility.AGE]['판정'], True)

    def test_body_blocked_is_fail(self):
        table = types_table('not_allowed', strength='strong', evidence='예비창업자 신청 불가')
        checks, _ = eligibility.conditions(notice(age_raw='예비창업자,3년미만'), 'N1', PRE, None,
                                           types_table=table, today=TODAY)
        line = by_name(checks)
        self.assertIs(line[eligibility.TYPE]['판정'], False)
        self.assertIs(line[eligibility.AGE]['판정'], True)        # 업력 칸 자체는 예비 허용

    def test_blocked_but_unread_mention_is_unknown(self):
        # 발췌 밖 원문에도 예비창업자 언급이 있으면 빼지 않는다
        table = types_table('not_allowed', strength='strong', evidence='예비창업자 제외',
                            unread_pre_founder='예비창업자도 신청할 수 있습니다')
        checks, _ = eligibility.conditions(notice(), 'N1', PRE, None, types_table=table, today=TODAY)
        self.assertIsNone(by_name(checks)[eligibility.TYPE]['판정'])

    def test_varies_allowed_makes_age_unknown(self):
        # 세부사업별로 예비창업자 허용이 갈리면 업력 칸이 통과여도 확인 필요로 둔다
        table = types_table('allowed', varies=True, evidence='예비창업자(일부 사업에 한함)')
        checks, _ = eligibility.conditions(notice(age_raw='예비창업자,3년미만'), 'N1', PRE, None,
                                           types_table=table, today=TODAY)
        line = by_name(checks)
        self.assertIsNone(line[eligibility.TYPE]['판정'])
        self.assertIsNone(line[eligibility.AGE]['판정'])
        self.assertIn('세부사업', line[eligibility.AGE]['요구'])

    def test_pre_founder_without_table_api_no_is_fail(self):
        checks, _ = eligibility.conditions(notice(age_raw='3년미만'), 'N1', PRE, None, today=TODAY)
        self.assertIs(by_name(checks)[eligibility.AGE]['판정'], False)


class AgeEvidenceTests(unittest.TestCase):
    AGE_TABLE = {'notices': {'N1': {'min': None, 'max': 7, 'quote': '창업 7년 이내 기업'}}}

    def test_missing_age_field_shows_evidence_only(self):
        checks, _ = eligibility.conditions(notice(age_raw=''), 'N1', '법인', '2015-01-01',
                                           age_table=self.AGE_TABLE, today=TODAY)
        line = by_name(checks)[eligibility.AGE]
        self.assertIsNone(line['판정'])                        # 추출 값으로 판정하지 않는다
        self.assertIn('추정', line['요구'])
        self.assertIn('창업 7년 이내 기업', line['설명'])
        self.assertIn('밖으로', line['설명'])

    def test_unknown_founding_date_is_unknown(self):
        checks, months = eligibility.conditions(notice(age_raw='7년미만'), 'N1', '개인사업자', '',
                                                age_table=self.AGE_TABLE, today=TODAY)
        self.assertIs(months, gate.UNKNOWN_AGE)
        line = by_name(checks)[eligibility.AGE]
        self.assertIsNone(line['판정'])                        # 설립일을 모르면 미달로 보지 않는다
        self.assertTrue(line['설명'].startswith('설립일이 없어'))

    def test_bad_date_is_unknown_not_error(self):
        checks, months = eligibility.conditions(notice(), 'N1', '법인', '2026-02-30', today=TODAY)
        self.assertIs(months, gate.UNKNOWN_AGE)
        self.assertIsNone(by_name(checks)[eligibility.AGE]['판정'])

    def test_passed_age_is_not_replaced(self):
        checks, _ = eligibility.conditions(notice(age_raw='7년미만'), 'N1', '법인', '2024-01-01',
                                           age_table=self.AGE_TABLE, today=TODAY)
        line = by_name(checks)[eligibility.AGE]
        self.assertIs(line['판정'], True)
        self.assertEqual(line['요구'], '업력 7년 미만')


class BusinessTypeTests(unittest.TestCase):
    def test_corporation_evidence_only(self):
        checks, _ = eligibility.conditions(notice(), 'N1', '법인', '2024-01-01',
                                           types_table=types_table(), today=TODAY)
        line = by_name(checks)[eligibility.TYPE]
        self.assertIsNone(line['판정'])                        # 개인·법인은 자동 판정하지 않는다
        self.assertIn('법인 가능', line['요구'])

    def test_sole_proprietor_not_mentioned(self):
        checks, _ = eligibility.conditions(notice(), 'N1', '개인사업자', '2024-01-01',
                                           types_table=types_table(), today=TODAY)
        line = by_name(checks)[eligibility.TYPE]
        self.assertIsNone(line['판정'])
        self.assertIn('관련 문장 없음', line['요구'])


if __name__ == '__main__':
    unittest.main()
