# -*- coding: utf-8 -*-
"""gate.py 자격 판정 테스트 — 특히 3값 판정(decisions.md D4).

  .\.venv\Scripts\python.exe -X utf8 -m unittest test_gate -v
"""
import unittest
from datetime import date

import gate

TODAY = date(2026, 9, 8)


def verdicts(result):
    return {c['조건']: c['판정'] for c in result['checks']}


class ParseEnyy(unittest.TestCase):
    def test_기본형(self):
        self.assertEqual(gate.parse_enyy('7년미만'), (False, 84))
        self.assertEqual(gate.parse_enyy('예비창업자,1년미만'), (True, 12))
        self.assertEqual(gate.parse_enyy('예비창업자'), (True, None))

    def test_최댓값을_상한으로_본다(self):
        self.assertEqual(gate.parse_enyy('1년미만,3년미만,10년미만')[1], 120)

    def test_해석_가능_여부(self):
        self.assertTrue(gate.understood('7년미만'))
        self.assertTrue(gate.understood('예비창업자'))
        self.assertFalse(gate.understood(''))
        self.assertFalse(gate.understood(None))
        self.assertFalse(gate.understood('해석할 수 없는 값'))


class 세값판정(unittest.TestCase):
    """D4 — 조건 없음(None)을 미달(False)로 뭉개지 않는다."""

    def test_업력_조건이_없으면_판단_불가다(self):
        n = {'notice_id': 'bizinfo:X', 'age_condition_raw': None,
             'apply_period_type': 'fixed', 'apply_start': '2026-09-01',
             'apply_end': '2026-09-30', 'recruitment_status': 'unknown'}
        r = gate.judge(n, 29, TODAY)
        self.assertIsNone(verdicts(r)['업력'])
        self.assertTrue(r['passed'], '조건이 없는데 탈락시키면 안 된다')

    def test_업력_미달은_그대로_탈락이다(self):
        n = {'notice_id': 'kstartup:X', 'age_condition_raw': '1년미만',
             'apply_period_type': 'fixed', 'apply_start': '2026-09-01',
             'apply_end': '2026-09-30', 'recruitment_status': 'open'}
        r = gate.judge(n, 29, TODAY)
        self.assertFalse(verdicts(r)['업력'])
        self.assertFalse(r['passed'])

    def test_해석_못한_업력은_판단_불가다(self):
        n = {'notice_id': 'x:1', 'age_condition_raw': '알 수 없는 표기',
             'apply_period_type': 'unknown', 'recruitment_status': 'unknown'}
        self.assertIsNone(verdicts(gate.judge(n, 29, TODAY))['업력'])

    def test_예산_소진시까지는_판단_불가지_미달이_아니다(self):
        for kind in ('budget_exhaustion', 'rolling', 'until_filled'):
            n = {'notice_id': 'bizinfo:X', 'age_condition_raw': None,
                 'apply_period_type': kind, 'apply_start': None,
                 'apply_end': None, 'recruitment_status': 'unknown'}
            r = gate.judge(n, 29, TODAY)
            self.assertIsNone(verdicts(r)['접수기간'], kind)
            self.assertTrue(r['passed'], kind)

    def test_마감일이_지났으면_탈락이다(self):
        n = {'notice_id': 'bizinfo:X', 'age_condition_raw': None,
             'apply_period_type': 'fixed', 'apply_start': '2026-08-01',
             'apply_end': '2026-08-31', 'recruitment_status': 'unknown'}
        r = gate.judge(n, 29, TODAY)
        self.assertFalse(verdicts(r)['접수기간'])
        self.assertFalse(r['passed'])

    def test_모집상태_없음은_판단_불가다(self):
        n = {'notice_id': 'bizinfo:X', 'age_condition_raw': None,
             'apply_period_type': 'rolling', 'recruitment_status': 'unknown'}
        r = gate.judge(n, 29, TODAY)
        self.assertIsNone(verdicts(r)['모집 상태'])
        self.assertEqual(r['unknown'], 3)

    def test_모집_마감은_탈락이다(self):
        n = {'notice_id': 'x:1', 'age_condition_raw': '7년미만',
             'apply_period_type': 'fixed', 'apply_start': '2026-09-01',
             'apply_end': '2026-09-30', 'recruitment_status': 'closed'}
        self.assertFalse(gate.judge(n, 29, TODAY)['passed'])


class K스타트업원본(unittest.TestCase):
    """정규화 이전 경로가 그대로 동작해야 한다."""

    def raw(self, **kw):
        base = {'biz_enyy': '예비창업자,3년미만,7년미만',
                'pbanc_rcpt_bgng_dt': '20260901', 'pbanc_rcpt_end_dt': '20260930',
                'rcrt_prgs_yn': 'Y'}
        base.update(kw)
        return base

    def test_통과(self):
        r = gate.judge(self.raw(), 29, TODAY)
        self.assertTrue(r['passed'])
        self.assertEqual(r['unknown'], 0, 'K-Startup 은 필드가 다 차 있다')

    def test_업력_초과는_탈락(self):
        self.assertFalse(gate.judge(self.raw(), 96, TODAY)['passed'])

    def test_예비창업자(self):
        self.assertTrue(gate.judge(self.raw(), None, TODAY)['passed'])
        self.assertFalse(gate.judge(self.raw(biz_enyy='7년미만'), None, TODAY)['passed'])

    def test_모집종료(self):
        self.assertFalse(gate.judge(self.raw(rcrt_prgs_yn='N'), 29, TODAY)['passed'])


class 기타(unittest.TestCase):
    def test_업력_개월수_계산(self):
        self.assertEqual(gate.business_age_months('2024-03-15', date(2026, 9, 8)), 29)
        self.assertEqual(gate.business_age_months('2026-09-09', date(2026, 9, 8)), 0)
        self.assertIsNone(gate.business_age_months(None))

    def test_날짜_두_형식을_모두_읽는다(self):
        self.assertEqual(gate.parse_ymd('20260908'), date(2026, 9, 8))
        self.assertEqual(gate.parse_ymd('2026-09-08'), date(2026, 9, 8))
        self.assertIsNone(gate.parse_ymd('2026/9/8'))
        self.assertIsNone(gate.parse_ymd(''))

    def test_마감일_없으면_남은일수도_없다(self):
        n = {'notice_id': 'x:1', 'apply_period_type': 'rolling', 'apply_end': None}
        self.assertIsNone(gate.deadline_days(n, TODAY))
        self.assertEqual(gate.deadline_days({'pbanc_rcpt_end_dt': '20260918'}, TODAY), 10)

    def test_표시기호(self):
        self.assertEqual(gate.mark(True), 'O')
        self.assertEqual(gate.mark(False), 'X')
        self.assertEqual(gate.mark(None), '?', 'None 을 X 로 뭉개면 D4 가 무의미해진다')


if __name__ == '__main__':
    unittest.main()
