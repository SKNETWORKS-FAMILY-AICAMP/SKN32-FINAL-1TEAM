# -*- coding: utf-8 -*-
"""eval/bonus_boostable — 어떤 입력 조합으로든 가산점이 양수가 되는 공고를 찾는지(결정 0015 전 확인 도구)."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import bonus_boostable as bb  # noqa: E402

TODAY = date(2026, 10, 8)


def item(**kw):
    base = {'kind': '인증', 'points': 2, 'name': 'x', 'certs': [], 'regions': [], 'detail': None,
            'quote': 'x 2점', 'group': None, 'program': None, 'extra_conditions': None}
    base.update(kw)
    return base


def found(*items, cap=None):
    return {'status': 'found', 'max_total_points': cap, 'bonus_info': 'x', 'items': list(items), 'uncertain': []}


class CandidateInputsTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(bb.candidate_inputs(item(kind='인증', certs=['메인비즈', '모르는인증']), TODAY),
                         [{'certifications': ['메인비즈']}])
        self.assertEqual(bb.candidate_inputs(item(kind='여성'), TODAY),
                         [{'gender': '여성'}, {'certifications': ['여성기업']}])
        self.assertEqual(bb.candidate_inputs(item(kind='재창업'), TODAY), [{'first_startup': False}])
        self.assertEqual(bb.candidate_inputs(item(kind='고용'), TODAY), [])

    def test_region_includes_named_district_and_extra_cert(self):
        it = item(kind='지역', regions=['경기도'], name='김포시 소재 벤처기업', quote='김포시 소재 벤처기업 2점')
        got = bb.candidate_inputs(it, TODAY)
        self.assertIn({'region': '경기', 'district': '김포시', 'certifications': ['벤처기업']}, got)

    def test_youth_birth_is_within_limit(self):
        from search import applicant
        got = bb.candidate_inputs(item(kind='청년', name='만 39세 이하 대표', quote='만 39세 이하 대표 2점'), TODAY)
        self.assertEqual(len(got), 1)
        self.assertLessEqual(applicant.age(got[0]['birth_date'], TODAY), 39)
        low = bb.candidate_inputs(item(kind='청년', name='만 19세 이하', quote='만 19세 이하 2점'), TODAY)
        self.assertLessEqual(applicant.age(low[0]['birth_date'], TODAY), 19)


class FindPositiveTests(unittest.TestCase):
    def test_finds_combination_that_scores(self):
        entry = found(item(kind='인증', certs=['이노비즈'], name='이노비즈', points=3, quote='이노비즈 인증 기업 3점'))
        combos, tried = bb.find_positive(entry, TODAY)
        self.assertEqual([c['input'] for c in combos], [{'certifications': ['이노비즈']}])
        self.assertEqual(combos[0]['score'], 3.0)
        self.assertGreaterEqual(tried, 1)

    def test_never_positive_is_empty(self):
        # 근거에 점수가 없거나(점수 인정 안 됨), 맞힐 수 없는 종류만 있으면 어떤 조합으로도 양수가 아니다
        entry = found(item(kind='인증', certs=['이노비즈'], quote='이노비즈 인증 기업 우대'),
                      item(kind='고용', quote='신규 고용 2점'))
        self.assertEqual(bb.find_positive(entry, TODAY)[0], [])
        self.assertEqual(bb.find_positive(None, TODAY)[0], [])

    def test_single_beats_union_over_cap(self):
        # 둘 다 가지면 합 6점 > 한도 5점 → null. 하나씩이면 양수 — "다 가진 신청자 하나"로 대신하면 놓친다
        entry = found(item(kind='인증', certs=['벤처기업'], name='벤처', points=3, quote='벤처기업 3점', group='a'),
                      item(kind='인증', certs=['이노비즈'], name='이노비즈', points=3, quote='이노비즈 3점', group='b'), cap=5)
        combos, _ = bb.find_positive(entry, TODAY)
        self.assertEqual(sorted(c['input']['certifications'][0] for c in combos), ['벤처기업', '이노비즈'])

    def test_merge_rejects_conflicting_values(self):
        self.assertIsNone(bb.merge_inputs([{'region': '경기'}, {'region': '서울'}]))
        self.assertEqual(bb.merge_inputs([{'certifications': ['b']}, {'certifications': ['a'], 'gender': '여성'}]),
                         {'certifications': ['a', 'b'], 'gender': '여성'})


class MovementTests(unittest.TestCase):
    def test_movement_names(self):
        self.assertEqual(bb.movement(5.0, 5.0), '같음')
        self.assertEqual(bb.movement(None, None), '같음')
        self.assertEqual(bb.movement(5.0, None), '양수→null')
        self.assertEqual(bb.movement(6.0, 5.0), '양수→더 작은 양수')
        for old, new in ((None, 5.0), (0, 5.0), (5.0, 6.0), (0, None), (5.0, 0)):
            self.assertEqual(bb.movement(old, new), '그 밖', (old, new))

    def test_movement_detail_separates_null_to_positive(self):
        # 결정 0019 — null → 양수만 '모름→양수'로 떼고, 나머지는 movement 와 같다
        self.assertEqual(bb.movement_detail(None, 5.0), '모름→양수')
        for old, new in ((0, 5.0), (5.0, 6.0), (0, None), (5.0, 0), (None, 0), (5.0, 5.0), (None, None), (5.0, None), (6.0, 5.0)):
            self.assertEqual(bb.movement_detail(old, new), bb.movement(old, new), (old, new))

    def test_trial_inputs_cover_singles_pairs_and_all(self):
        entry = found(item(kind='인증', certs=['벤처기업'], quote='벤처 2점'), item(kind='인증', certs=['이노비즈'], quote='이노비즈 2점'),
                      item(kind='여성', quote='여성 2점'))
        got = bb.trial_inputs(entry, TODAY)
        self.assertIn({'certifications': ['벤처기업']}, got)
        self.assertIn({'certifications': ['벤처기업', '이노비즈']}, got)
        self.assertIn({'certifications': ['벤처기업', '여성기업', '이노비즈'], 'gender': '여성'}, got)
        self.assertEqual(len(got), len({str(sorted(g.items())) for g in got}))          # 겹침 없음


class ReviewedListTests(unittest.TestCase):
    """원문 대조를 마친 공고 목록(결정 0017) — 승인 항목·분류·쓰기."""

    def combos(self):
        return [{'input': {'certifications': ['여성기업']}, 'score': 5.0, 'items': [{'name': '여성기업', 'points': 5.0}]},
                {'input': {'certifications': ['장애인기업']}, 'score': 5.0, 'items': [{'name': '장애인기업', 'points': 5.0}]}]

    def test_approved_items_and_status(self):
        self.assertEqual(bb.approved_items(self.combos()),
                         [{'name': '여성기업', 'points': 5.0}, {'name': '장애인기업', 'points': 5.0}])
        entry = {'row_fingerprint': 'bf1-a', 'evidence_fingerprint': 'ev1-a'}
        listed = {'n': {'content_version': 'cv', 'row_fingerprint': 'bf1-a', 'evidence_fingerprint': 'ev1-a',
                        'approved_items': bb.approved_items(self.combos())}}
        self.assertEqual(bb.review_status(listed, 'n', entry, 'cv', self.combos()), 'listed')
        self.assertEqual(bb.review_status(listed, 'n', entry, 'cv2', self.combos()), 'recheck')        # 공고 내용이 바뀜
        self.assertEqual(bb.review_status(listed, 'n', {'row_fingerprint': 'bf1-b', 'evidence_fingerprint': 'ev1-a'}, 'cv', self.combos()), 'recheck')
        partial = {'n': dict(listed['n'], approved_items=[{'name': '여성기업', 'points': 5.0}])}
        self.assertEqual(bb.review_status(partial, 'n', entry, 'cv', self.combos()), 'recheck')      # 승인 밖 항목이 관측됨
        self.assertEqual(bb.review_status({}, 'n', entry, 'cv', self.combos()), 'new')

    def test_write_reviewed(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'r.json')
            table = {'n': {'row_fingerprint': 'bf1-a', 'evidence_fingerprint': 'ev1-a'}}
            data = bb.write_reviewed(path, ['n'], table, {'n': 'cv'}, {'n': self.combos()}, 'v4', TODAY, note='맞음')
            self.assertEqual(data['notices']['n']['row_fingerprint'], 'bf1-a')
            self.assertEqual(data['notices']['n']['reviewed_by'], 'Claude 원문 대조(AI 참고)')
            self.assertEqual(json.load(open(path, encoding='utf-8'))['notices']['n']['content_version'], 'cv')
            from search import bonus
            self.assertIn('n', bonus.load_reviewed(path))
            with self.assertRaises(ValueError):                                         # 양수가 관측되지 않은 공고
                bb.write_reviewed(path, ['x'], table, {}, {'n': self.combos()}, 'v4', TODAY)


class RawContextTests(unittest.TestCase):
    def test_finds_quote_ignoring_spaces(self):
        raw = '앞 내용 ' * 10 + '여성 기업\n가점 2점' + ' 뒤 내용' * 10
        got = bb._raw_context(raw, '여성기업 가점 2점')
        self.assertIn('여성 기업\n가점 2점', got)
        self.assertIsNone(bb._raw_context(raw, '없는 문장'))


if __name__ == '__main__':
    unittest.main()
