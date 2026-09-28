"""Authored v3 development regressions, NOT an independent or held-out benchmark.

Each pair tests a narrow behavior on surface examples outside the source pool.
Clear means no heuristic review signal; it never means semantic acceptance.
Signal expectations intentionally do not prescribe rule names or a thesaurus.
"""
import unittest

from information_validator_v3 import validate


class InformationValidatorV3BehaviorTest(unittest.TestCase):
    def assert_contract(self, result):
        self.assertEqual(result['semantic_verdict'], 'uncertain')
        self.assertEqual(result['flagged'], bool(result['signals']))
        self.assertNotIn(result.get('routing'), {'accept', 'accepted', 'auto_accept'})
        self.assertFalse(result.get('pair_accepted', False))
        for signal in result['signals']:
            self.assertTrue(signal['code'])
            self.assertTrue(signal['detail'])
            self.assertIn('reference_evidence', signal)
            self.assertIn('candidate_evidence', signal)
            # Additions can legitimately have an empty reference-side feature list.
            self.assertTrue(signal['reference_evidence'] or signal['candidate_evidence'])

    def check_clear(self, reference, candidate):
        result = validate(reference, candidate)
        self.assert_contract(result)
        self.assertFalse(result['flagged'], result['signals'])
        return result

    def check_signal(self, reference, candidate):
        result = validate(reference, candidate)
        self.assert_contract(result)
        self.assertTrue(result['flagged'], result)
        return result

    def test_identity_is_not_automatic_acceptance(self):
        self.check_clear('동해도서관은 독서 모임을 운영한다.', '동해도서관은 독서 모임을 운영한다.')

    def test_noun_ending_ga_is_not_a_subject_particle(self):
        self.check_clear('국가 기록물 보관 기준 마련', '국가 기록물의 보관 기준을 마련한다.')

    def test_noun_ending_i_is_not_a_subject_particle(self):
        self.check_clear('아이 안전 교육 자료 개발', '아이 안전 교육의 자료를 개발한다.')

    def test_attributive_ending_is_not_a_subject_particle(self):
        self.check_clear('연구소가 운영하는 실험실을 학교가 방문한다.',
                         '학교는 연구소가 운영하는 실험실을 방문한다.')

    def test_explicit_subject_object_reordering_is_clear(self):
        self.check_clear('해솔재단이 누리협회를 지원한다.', '누리협회를 해솔재단이 지원한다.')
        self.check_clear('전시회와 강연회를 운영한다.', '강연회와 전시회를 운영한다.')

    def test_explicit_subject_object_swap_is_flagged(self):
        self.check_signal('해솔재단이 누리협회를 지원한다.', '누리협회가 해솔재단을 지원한다.')

    def test_independent_subject_predicates_reorder(self):
        self.check_clear('보람센터는 자료를 수집한다. 새롬센터는 자료를 배포한다.',
                         '새롬센터는 자료를 배포한다. 보람센터는 자료를 수집한다.')

    def test_same_subject_set_different_predicate_binding(self):
        self.check_signal('보람센터는 자료를 수집한다. 새롬센터는 자료를 배포한다.',
                          '보람센터는 자료를 배포한다. 새롬센터는 자료를 수집한다.')

    def test_explicit_purpose_grammatical_paraphrase(self):
        self.check_clear('혼잡 완화를 위한 안내판 설치',
                         '혼잡을 완화하기 위해 안내판을 설치한다.')

    def test_nominal_purpose_expansion(self):
        self.check_clear('설문 참여 확대 기반 마련',
                         '설문 참여 확대를 위한 기반을 마련한다.')

    def test_parallel_activities_do_not_imply_purpose(self):
        self.check_signal('자료를 수집하고 상담실을 운영한다.',
                          '자료를 수집하기 위해 상담실을 운영한다.')

    def test_purpose_and_means_reversed(self):
        self.check_signal('방문객 대기 시간을 줄이기 위해 창구 예약 제도를 확대한다.',
                          '창구 예약 제도를 확대하기 위해 방문객 대기 시간을 줄인다.')
        self.check_signal(
            '서비스 정확도를 높이기 위해 자료를 교차 검증한다. 처리 시간을 줄이기 위해 요청을 일괄 처리한다.',
            '서비스 정확도를 높이기 위해 요청을 일괄 처리한다. 처리 시간을 줄이기 위해 자료를 교차 검증한다.')

    def test_compound_spacing_and_verbalization(self):
        self.check_clear('공공데이터 표준화 사업 추진',
                         '공공 데이터의 표준화 사업을 추진한다.')

    def test_plain_language_expansion_not_new_claim(self):
        self.check_clear('지침의 조속한 배포 추진',
                         '지침을 빠른 시일 안에 배포하도록 추진한다.')

    def test_new_function_is_flagged(self):
        self.check_signal('기준 항목 검색 기능 제공',
                          '기준 항목 검색 및 자동 번역 기능 제공')

    def test_removed_function_is_flagged(self):
        self.check_signal('표준 문서 검색과 자동 번역 기능 제공',
                          '표준 문서 검색 기능 제공')

    def test_strength_preserved_with_grammar_change(self):
        self.check_clear('교통 불편 해소를 위한 노선 개편',
                         '교통 불편을 해소하기 위해 노선을 개편한다.')

    def test_elimination_changed_to_mitigation(self):
        self.check_signal('교통 불편 해소를 위한 노선 개편',
                          '교통 불편 경감을 위한 노선 개편')

    def test_operating_action_grammatical_paraphrase(self):
        self.check_clear('이동 진료 서비스 운영 확대',
                         '이동 진료 서비스의 운영을 확대한다.')

    def test_operating_action_narrowed_to_vehicle_running(self):
        self.check_signal('이동 진료 서비스 운영 확대', '이동 진료 서비스 운행 확대')

    def test_operating_actions_stay_bound_to_their_objects(self):
        reference = '전시관을 운영한다. 셔틀버스를 운행한다.'
        self.check_clear(reference, '셔틀버스를 운행한다. 전시관을 운영한다.')
        self.check_signal(reference, '전시관을 운행한다. 셔틀버스를 운영한다.')

    def test_added_support_action_is_flagged(self):
        self.check_signal('원격 상담 서비스 운영 확대',
                          '원격 상담 서비스 운영 확대 및 이용 지원')

    def test_negation_preserved_with_grammar_change(self):
        self.check_clear('예약 변경은 허용하지 않음', '예약 변경은 허용하지 않는다.')

    def test_negation_removal_is_flagged(self):
        self.check_signal('예약 변경은 허용하지 않는다.', '예약 변경은 허용한다.')

    def test_possibility_preserved(self):
        self.check_clear('야간 자료 열람 가능', '야간에 자료를 열람할 수 있다.')

    def test_possibility_to_guarantee_is_flagged(self):
        self.check_signal('야간 자료 열람 가능', '야간 자료 열람 보장')

    def test_equivalent_money_notation(self):
        self.check_clear('장비 임차료는 4.8만원임', '장비 임차료는 48,000원이다.')

    def test_quantity_binding_survives_clause_reordering(self):
        self.check_clear('해솔반 13명; 다온반 17명', '다온반 17명; 해솔반 13명')

    def test_quantity_values_reassigned_to_same_targets(self):
        self.check_signal('해솔반 13명; 다온반 17명', '해솔반 17명; 다온반 13명')

    def test_condition_clauses_reordered(self):
        self.check_clear('등록을 완료한 경우 좌석을 배정한다. 신청을 취소한 경우 참가비를 환불한다.',
                         '신청을 취소한 경우 참가비를 환불한다. 등록을 완료한 경우 좌석을 배정한다.')

    def test_condition_consequence_binding_swapped(self):
        self.check_signal('등록을 완료한 경우 좌석을 배정한다. 신청을 취소한 경우 참가비를 환불한다.',
                          '등록을 완료한 경우 참가비를 환불한다. 신청을 취소한 경우 좌석을 배정한다.')

    def test_threshold_direction_changed(self):
        self.check_signal('수강생 14명 이상인 반에 강사를 배정한다.',
                          '수강생 14명 미만인 반에 강사를 배정한다.')

    def test_project_status_binding_swapped(self):
        self.check_signal('출입 시스템 개발 완료; 예약 시스템 개발 중',
                          '출입 시스템 개발 중; 예약 시스템 개발 완료')

    def test_invalid_types_rejected(self):
        for reference, candidate in [(None, '후보'), ('원문', 42), ([], '후보')]:
            with self.subTest(reference=reference, candidate=candidate):
                with self.assertRaises(TypeError):
                    validate(reference, candidate)

    def test_empty_text_rejected(self):
        for reference, candidate in [('', '후보'), ('원문', ' \n\t'), (' ', '후보')]:
            with self.subTest(reference=reference, candidate=candidate):
                with self.assertRaises(ValueError):
                    validate(reference, candidate)


if __name__ == '__main__':
    unittest.main()
