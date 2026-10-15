# -*- coding: utf-8 -*-
"""늘어난 신청자 정보가 매칭에 어떻게 쓰이는지 고정한다.

  .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -k test_applicant -v

여기서 지키려는 것
  · 새 항목을 안 넣으면 예전과 **완전히 같은** 질의 문장이 나온다
  · 성별·재창업·인증은 질의 문장이 아니라 **규칙**에만 들어간다
  · 시·군·구는 시·도가 맞는 공고 안에서만 본다
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from datetime import date

from search import app, applicant, rank_rules
from shared import region


def request(**kw):
    base = dict(applicant_type='법인사업자', founded_at='2023-03-01', idea='금형 불량 검출 비전 AI')
    base.update(kw)
    return app.MatchRequest(**base)


class QueryTests(unittest.TestCase):
    def test_new_fields_empty_keeps_old_query(self):
        self.assertEqual(app.build_query(request()),
                         '금형 불량 검출 비전 AI. 창업 4년차 법인사업자')

    def test_industry_and_certificates_join_the_query(self):
        q = app.build_query(request(main_industry='제조업', certifications=['벤처기업'], hiring_plan=True))
        self.assertIn('업종: 제조업', q)
        self.assertIn('보유 인증: 벤처기업', q)
        self.assertIn('고용 계획 있음', q)

    def test_gender_and_name_stay_out_of_the_query(self):
        q = app.build_query(request(gender='여성', name='홍길동', birth_date='1990-05-01',
                                    business_no='1234567890'))
        for word in ('여성', '홍길동', '1990', '1234567890'):
            self.assertNotIn(word, q)


class RuleTests(unittest.TestCase):
    def rule_text(self, req):
        return rank_rules.applicant_text(req.idea, applicant.rule_words(req))

    def test_woman_keeps_women_only_notices(self):
        notice = ('2026년 여성기업 육성사업 공고', '여성기업')
        without = self.rule_text(request())
        with_gender = self.rule_text(request(gender='여성'))
        self.assertEqual(rank_rules.groups_not_matched(*notice, without), ['여성기업'])
        self.assertEqual(rank_rules.groups_not_matched(*notice, with_gender), [])

    def test_restart_keeps_restart_notices(self):
        notice = ('재창업 패키지 모집 공고', '재창업자')
        self.assertEqual(rank_rules.groups_not_matched(*notice, self.rule_text(request())), ['재창업'])
        self.assertEqual(
            rank_rules.groups_not_matched(*notice, self.rule_text(request(first_startup=False))), [])

    def test_certificate_keeps_matching_notices(self):
        notice = ('사회적기업 판로지원 사업', '사회적기업')
        self.assertEqual(
            rank_rules.groups_not_matched(*notice, self.rule_text(request(certifications=['사회적기업']))),
            [])


class StoredOnlyTests(unittest.TestCase):
    def test_age_from_birth_date(self):
        self.assertEqual(applicant.age('1990-05-01', date(2026, 9, 18)), 36)
        self.assertEqual(applicant.age('1990-12-01', date(2026, 9, 18)), 35)
        self.assertIsNone(applicant.age(''))
        self.assertIsNone(applicant.age('생년월일'))

    def test_business_number_is_not_echoed_back(self):
        stored = applicant.stored_only(request(business_no='1234567890'))
        self.assertEqual(stored['사업자등록번호'], '입력함')
        self.assertNotIn('1234567890', str(stored))

    def test_every_stored_field_says_why(self):
        stored = applicant.stored_only(request(
            name='홍길동', birth_date='1990-05-01', business_no='1234567890',
            budget_scale=2000, self_funding=True, equipment=['비전 검사기']))
        for key in stored:
            self.assertIn(key, applicant.why_not_used())


class DistrictTests(unittest.TestCase):
    def test_same_city_is_true(self):
        self.assertIs(region.district_matches('[경기] 시흥시 창업지원', '경기', '경기', '시흥시'), True)

    def test_other_city_in_same_province_is_false(self):
        self.assertIs(region.district_matches('[경기] 성남시 창업지원', '경기', '경기', '시흥시'), False)

    def test_no_city_in_title_is_unknown(self):
        self.assertIsNone(region.district_matches('[경기] 도내 창업지원', '경기', '경기', '시흥시'))

    def test_other_province_is_left_to_the_province_rule(self):
        self.assertIsNone(region.district_matches('[전북] 무주군 지원', '전북', '경기', '시흥시'))

    def test_special_city_names(self):
        self.assertEqual(region.districts_in_title('용인특례시 창업지원', '경기'), {'용인시'})

    def test_nationwide_notice_with_a_city_in_the_title(self):
        # '전국' 공고라도 제목에 특정 시·군이 적혀 있으면 그 시·군 이야기다
        self.assertIs(region.district_matches('전국 대상 (시흥시 소재 기업)', '전국', '경기', '성남시'), False)


if __name__ == '__main__':
    unittest.main()
