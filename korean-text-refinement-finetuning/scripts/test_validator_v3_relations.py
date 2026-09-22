"""Authored behavioral regressions, not an independent semantic benchmark."""
import unittest

from validator_v3_relations import collect_signals


class RelationSignalsTest(unittest.TestCase):
    def signal(self, a, b, code):
        result = collect_signals(a, b)
        self.assertIn(code, [s['code'] for s in result], result)

    def clear(self, a, b):
        self.assertEqual([], collect_signals(a, b))

    def test_topic_amount_swap(self):
        self.signal('일반 이용료는 월 8만원이며 보관 비용은 월 2만원이다',
                    '일반 이용료는 월 2만원이며 보관 비용은 월 8만원이다',
                    'quantity_topic_binding')

    def test_topic_amount_normal_reorder_and_units(self):
        self.clear('일반 이용료는 월 8만원이며 보관 비용은 월 2만원이다',
                   '보관 비용은 월 20,000원이다. 일반 이용료는 월 80,000원이다')

    def test_quantity_compound_names_not_shared_head(self):
        self.clear('산들반 19명; 은하반 27명', '은하반 27명; 산들반 19명')
        self.signal('산들반 19명; 은하반 27명', '산들반 27명; 은하반 19명',
                    'quantity_topic_binding')
        self.signal('대전 19명, 춘천 27명', '대전 27명, 춘천 19명',
                    'quantity_topic_binding')

    def test_completion_progress_swap(self):
        self.signal('상담 화면 제작을 완료했으며 주소 검색은 개발 중이다',
                    '주소 검색을 완료했으며 상담 화면 제작은 개발 중이다',
                    'task_status_binding')

    def test_completion_progress_normal_reorder(self):
        self.clear('상담 화면 제작을 완료한 상태이며 주소 검색은 개발 중이다',
                   '주소 검색은 개발 중이며 상담 화면 제작을 완료했다')

    def test_completion_condition_not_future_result(self):
        self.clear('추진단 구성 완료 시, 자료 검토를 추진할 예정',
                   '추진단 구성이 완료되면 자료 검토를 추진할 예정이다')
        self.clear('향후 추진단 구성 완료를 통해 자료 검토가 정상 추진될 것으로 전망',
                   '향후 추진단 구성이 완료되면 자료 검토가 정상 추진될 것으로 전망')

    def test_deadline_attaches_to_action(self):
        self.signal('평일 08:30~17:30에 서류를 접수하고 접수 후 36시간 이내 심사를 목표로 함',
                    '36시간 이내에 서류를 접수하고 접수 후 평일 08:30~17:30에 심사를 목표로 함',
                    'temporal_action_binding')

    def test_deadline_normal_clause_reorder(self):
        self.clear('평일 08:30~17:30에 서류를 접수하고 접수 후 36시간 이내 심사를 목표로 함',
                   '접수 후 36시간 이내 심사를 목표로 함. 평일 08:30~17:30에 서류를 접수함')

    def test_criteria_reassigned_to_actions(self):
        self.signal('직원 8명 이하의 지역 제조사를 지원 대상으로 설정함\n디지털 장비가 없는 소상공인을 우선 접촉할 계획임',
                    '디지털 장비가 없는 소상공인을 지원 대상으로 설정함\n직원 8명 이하의 지역 제조사를 우선 접촉할 계획임',
                    'event_argument_binding')

    def test_criteria_normal_clause_reorder(self):
        self.clear('직원 8명 이하의 지역 제조사를 지원 대상으로 설정함\n디지털 장비가 없는 소상공인을 우선 접촉할 계획임',
                   '디지털 장비가 없는 소상공인을 우선 접촉할 계획임\n직원 8명 이하의 지역 제조사를 지원 대상으로 설정함')

    def test_threshold_operator_attached_to_action(self):
        reference = '압력이 16bar 이상이면 차단하고 압력이 16bar 미만이면 가동한다'
        # Known quantity units are deliberately used for the actual assertion;
        # arbitrary engineering units are outside this rule's quantity parser.
        reference = '표본 16개 이상이면 가열하고 표본 16개 미만이면 냉각한다'
        self.signal(reference, '표본 16개 미만이면 가열하고 표본 16개 이상이면 냉각한다',
                    'condition_action_binding')
        self.clear(reference, '표본 16개 미만이면 냉각하고 표본 16개 이상이면 가열한다')

    def test_negated_target_reassigned(self):
        reference = '계약서를 전송한다. 안내서를 전송하지 않는다'
        self.signal(reference, '계약서를 전송하지 않는다. 안내서를 전송한다',
                    'predicate_polarity_binding')
        self.clear(reference, '안내서를 전송하지 않는다. 계약서를 전송한다')

    def test_possibility_target_reassigned(self):
        reference = '자료실은 열람할 수 있다. 보관실은 열람할 수 없다'
        self.signal(reference, '자료실은 열람할 수 없다. 보관실은 열람할 수 있다',
                    'predicate_polarity_binding')
        self.clear(reference, '보관실은 열람할 수 없다. 자료실은 열람할 수 있다')

    def test_negative_attributive_does_not_negate_action(self):
        self.clear('장비가 없는 소상공인을 지원한다',
                   '장비를 보유하지 않은 소상공인을 지원한다')

    def test_dependency_arguments_reversed(self):
        self.signal('장비 구매는 심사 결과에 따라 승인 여부가 결정됨',
                    '심사 결과는 장비 구매 승인 여부에 따라 결정됨',
                    'relation_argument_dependence')

    def test_dependency_topic_reordered_normally(self):
        self.clear('장비 구매는 심사 결과에 따라 승인 여부가 결정됨',
                   '심사 결과에 따라 장비 구매 승인 여부가 결정됨')

    def test_means_reassigned(self):
        self.signal('산학 협업을 통해 현장 사례 발굴, 공개 강연을 제작하여 지역 인식 확대',
                    '지역 인식 확대를 통해 현장 사례를 발굴하고, 산학 협업으로 공개 강연 제작',
                    'relation_argument_means')

    def test_multiple_means_normal_reordered(self):
        self.clear('산학 협업을 통해 현장 사례 발굴\n교사 연수를 통해 수업 역량 강화',
                   '교사 연수를 통해 수업 역량을 강화함\n산학 협업을 통해 현장 사례를 발굴함')

    def test_parenthetical_numbers_not_bound_to_unrelated_predicate(self):
        self.clear('교육 운영(2028년 4월)\n설문 조사는 2028년 7월에 실시',
                   '설문 조사는 2028년 7월에 실시\n교육 운영(2028년 4월)')

    def test_no_signal_is_not_acceptance(self):
        self.clear('새 사례를 수집함', '새 사례를 수집함')


if __name__ == '__main__':
    unittest.main()
