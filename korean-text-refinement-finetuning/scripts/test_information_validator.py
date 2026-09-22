"""Behavioral regressions, authored during v2 development; not a held-out benchmark."""
import unittest

from information_validator import validate


class InformationValidatorTest(unittest.TestCase):
    def check_clear(self, a, b):
        result = validate(a, b)
        self.assertFalse(result['flagged'], result['signals'])
        self.assertEqual(result['semantic_verdict'], 'uncertain')

    def check_signal(self, a, b, code):
        result = validate(a, b)
        self.assertIn(code, [x['code'] for x in result['signals']], result)

    def test_money_equivalent(self):
        self.check_clear('예산은 7천만원임', '예산은 70,000,000원입니다')

    def test_fractional_amount(self):
        self.check_clear('예산은 2.5만원임', '예산은 25,000원임')

    def test_signed_value(self):
        self.check_signal('기온은 -7도임', '기온은 7도임', 'quantity')

    def test_date_notation(self):
        self.check_clear('서비스 운영(’28.3.~)', '서비스를 ’28년 3월부터 운영함')

    def test_date_change(self):
        self.check_signal('서비스 운영(’28.3.~)', '서비스를 ’28년 4월부터 운영함', 'quantity')

    def test_same_values_reassigned(self):
        self.check_signal('서울 7명, 부산 9명', '서울 9명, 부산 7명', 'quantity_binding')

    def test_independent_clause_reordering(self):
        self.check_clear('서울 7명\n부산 9명', '부산 9명\n서울 7명')

    def test_repeated_quantity_omission(self):
        self.check_signal('서울 7명과 부산 7명 참여', '서울 7명 참여', 'quantity')

    def test_condition_flip(self):
        self.check_signal('직원 8명 이하 기업 지원', '직원 8명 이상 기업 지원', 'condition')

    def test_forecast_synonym(self):
        self.check_clear('수요가 증가할 것으로 전망', '수요가 증가할 것으로 보임')

    def test_modality_strengthening(self):
        self.check_signal('2시간 이내 응답을 목표로 함', '2시간 이내 응답을 보장함', 'concept_guarantee')

    def test_tax_condition(self):
        self.check_signal('요금 8만원, 부가세 별도', '요금 8만원, 부가세 포함', 'concept_tax_excluded')

    def test_media_not_negative(self):
        self.check_clear('미디어 교육 운영', '미디어 교육을 운영합니다')

    def test_negative_removed(self):
        self.check_signal('예약은 아직 완료되지 않음', '예약 완료', 'negation')

    def test_new_claim(self):
        self.check_signal('자료 조회 기능 제공', '자료 조회와 자동 백업 기능 제공', 'new_content')

    def test_identity_remains_unverified(self):
        self.check_clear('자료 조회 기능 제공', '자료 조회 기능 제공')

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            validate('원문', ' ')
        with self.assertRaises(TypeError):
            validate(None, '결과')


if __name__ == '__main__':
    unittest.main()
